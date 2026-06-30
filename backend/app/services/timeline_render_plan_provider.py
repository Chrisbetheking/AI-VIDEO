from __future__ import annotations

import os
import uuid
from typing import Any


def _round(x: Any, ndigits: int = 3) -> float:
    try:
        return round(float(x), ndigits)
    except Exception:
        return 0.0


def _srt_time(seconds: float) -> str:
    ms_total = int(round(float(seconds) * 1000))
    h = ms_total // 3600000
    ms_total %= 3600000
    m = ms_total // 60000
    ms_total %= 60000
    s = ms_total // 1000
    ms = ms_total % 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _build_srt(segments: list[dict[str, Any]]) -> str:
    lines: list[str] = []

    for i, seg in enumerate(segments, start=1):
        text = str(seg.get("subtitle_text") or seg.get("text") or "").strip()
        start = _round(seg.get("start"))
        end = _round(seg.get("end"))

        lines.append(str(i))
        lines.append(f"{_srt_time(start)} --> {_srt_time(end)}")
        lines.append(text)
        lines.append("")

    return "\n".join(lines).strip()


def _normalize_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    current = 0.0
    for i, raw in enumerate(segments or []):
        text = str(raw.get("text") or raw.get("subtitle_text") or "").strip()

        start = raw.get("start")
        end = raw.get("end")
        duration = raw.get("duration")

        if start is None:
            start = current

        if duration is None and end is not None:
            duration = max(0.2, float(end) - float(start))

        if duration is None:
            duration = 2.0

        end = float(start) + float(duration)

        item = dict(raw)
        item.update(
            {
                "index": i,
                "text": text,
                "subtitle_text": text,
                "start": _round(start),
                "end": _round(end),
                "duration": _round(duration),
                "sync_source": raw.get("sync_source") or "provided_segments",
            }
        )

        out.append(item)
        current = float(end)

    return out


def _material_label(material: dict[str, Any], fallback_index: int) -> str:
    return (
        str(material.get("id") or "").strip()
        or str(material.get("name") or "").strip()
        or str(material.get("path") or "").strip()
        or str(material.get("url") or "").strip()
        or f"material_{fallback_index + 1}"
    )


def _material_duration(material: dict[str, Any]) -> float | None:
    for key in ("duration", "duration_seconds", "source_duration"):
        value = material.get(key)
        if value is not None:
            try:
                v = float(value)
                if v > 0:
                    return v
            except Exception:
                pass
    return None


def _fit_action(source_duration: float | None, target_duration: float, fit_mode: str) -> dict[str, Any]:
    if source_duration is None:
        return {
            "action": "unknown_source_duration",
            "source_duration": None,
            "target_duration": _round(target_duration),
            "note": "未提供素材时长，真实渲染前建议用 ffprobe 补全。",
        }

    diff = source_duration - target_duration

    if abs(diff) <= 0.08:
        return {
            "action": "use_as_is",
            "source_duration": _round(source_duration),
            "target_duration": _round(target_duration),
            "delta": _round(diff),
        }

    if source_duration > target_duration:
        return {
            "action": "trim",
            "source_duration": _round(source_duration),
            "target_duration": _round(target_duration),
            "trim_from": 0,
            "trim_to": _round(target_duration),
            "delta": _round(diff),
        }

    if fit_mode == "loop":
        loops = int(target_duration // source_duration) + 1
        return {
            "action": "loop_then_trim",
            "source_duration": _round(source_duration),
            "target_duration": _round(target_duration),
            "loop_count": loops,
            "trim_to": _round(target_duration),
            "delta": _round(diff),
        }

    if fit_mode == "freeze":
        return {
            "action": "pad_freeze_last_frame",
            "source_duration": _round(source_duration),
            "target_duration": _round(target_duration),
            "pad_seconds": _round(target_duration - source_duration),
            "delta": _round(diff),
        }

    return {
        "action": "speed_adjust",
        "source_duration": _round(source_duration),
        "target_duration": _round(target_duration),
        "speed_factor": _round(source_duration / max(target_duration, 0.001)),
        "delta": _round(diff),
    }


def build_render_plan(
    segments: list[dict[str, Any]],
    materials: list[dict[str, Any]],
    audio_url: str = "",
    fit_mode: str = "loop",
    material_strategy: str = "round_robin",
    output_profile: str = "vertical_720x1280",
    burn_subtitle: bool = True,
) -> dict[str, Any]:
    normalized_segments = _normalize_segments(segments)

    if not normalized_segments:
        raise ValueError("segments 不能为空。请先用 /api/video/timeline/tts-align 生成真实时间轴。")

    materials = materials or []
    if not materials:
        raise ValueError("materials 不能为空。至少传入一个素材 path 或 url。")

    render_id = f"timeline_render_plan_{uuid.uuid4().hex[:18]}"

    timeline_total = _round(normalized_segments[-1].get("end"))

    clips: list[dict[str, Any]] = []
    warnings: list[str] = []

    for i, seg in enumerate(normalized_segments):
        if material_strategy == "one_to_one":
            material_index = min(i, len(materials) - 1)
        else:
            material_index = i % len(materials)

        mat = materials[material_index]
        target_duration = _round(seg.get("duration"))
        source_duration = _material_duration(mat)
        fit = _fit_action(source_duration, target_duration, fit_mode)

        if source_duration is None:
            warnings.append(f"segment {i}: 素材未提供 duration，真实渲染前需要 ffprobe。")

        clip = {
            "clip_index": i,
            "segment_index": seg.get("index", i),
            "start": _round(seg.get("start")),
            "end": _round(seg.get("end")),
            "target_duration": target_duration,
            "text": seg.get("text") or "",
            "subtitle_text": seg.get("subtitle_text") or seg.get("text") or "",
            "shot_hint": seg.get("shot_hint") or "normal",
            "emotion": seg.get("emotion") or "neutral",
            "emphasis": seg.get("emphasis") or 1.0,
            "sync_source": seg.get("sync_source") or "provided_segments",
            "material": {
                "material_index": material_index,
                "label": _material_label(mat, material_index),
                "path": mat.get("path") or "",
                "url": mat.get("url") or "",
                "type": mat.get("type") or "video",
                "source_duration": source_duration,
            },
            "fit": fit,
        }

        clips.append(clip)

    srt_preview = _build_srt(normalized_segments)

    ffmpeg_plan = {
        "render_mode": "dry_plan_only",
        "output_profile": output_profile,
        "audio_url": audio_url,
        "burn_subtitle": burn_subtitle,
        "expected_total_duration": timeline_total,
        "steps": [
            "1. ffprobe 素材真实时长",
            "2. 按每个 segment target_duration trim / loop / freeze 素材",
            "3. concat 所有 clip",
            "4. 对齐 TTS audio_url",
            "5. 按 srt_preview 烧录字幕",
            "6. 输出最终视频",
        ],
    }

    return {
        "ok": True,
        "provider": "timeline_render_plan_v1",
        "render_id": render_id,
        "status": "planned",
        "dry_run": True,
        "timeline_total_duration": timeline_total,
        "clip_count": len(clips),
        "material_count": len(materials),
        "fit_mode": fit_mode,
        "material_strategy": material_strategy,
        "output_profile": output_profile,
        "audio_url": audio_url,
        "burn_subtitle": burn_subtitle,
        "clips": clips,
        "srt_preview": srt_preview,
        "ffmpeg_plan": ffmpeg_plan,
        "warnings": warnings,
        "message": "Timeline Render Plan v1 构建完成：这里只生成渲染计划，不调用 fal.ai，不合成视频，不上传 R2。",
    }


def health() -> dict[str, Any]:
    return {
        "ok": True,
        "provider": "timeline_render_plan_v1",
        "message": "Timeline Render Plan v1 可用：把真实 TTS 时间轴、字幕、素材映射成可执行渲染计划。",
        "features": [
            "segment_to_clip_mapping",
            "material_round_robin",
            "one_to_one_material_mapping",
            "trim_loop_freeze_speed_fit",
            "srt_preview",
            "ffmpeg_plan_preview",
        ],
    }


def self_test() -> dict[str, Any]:
    return build_render_plan(
        segments=[
            {
                "index": 0,
                "start": 0.0,
                "end": 5.712,
                "duration": 5.712,
                "text": "来马来西亚买房，千万别只看价格。",
                "shot_hint": "slow_emphasis",
                "emotion": "neutral",
                "emphasis": 1.25,
                "sync_source": "tts_segment_timing",
            },
            {
                "index": 1,
                "start": 5.832,
                "end": 12.6,
                "duration": 6.768,
                "text": "第三看未来转手难度，很多人踩坑，是因为买错区域。",
                "shot_hint": "normal",
                "emotion": "neutral",
                "emphasis": 1.0,
                "sync_source": "tts_segment_timing",
            },
        ],
        materials=[
            {
                "id": "real_estate_clip_1",
                "path": "/opt/ai-video/backend/data/real-shot/uploads/example_1.mp4",
                "duration": 8.0,
                "type": "video",
            },
            {
                "id": "real_estate_clip_2",
                "path": "/opt/ai-video/backend/data/real-shot/uploads/example_2.mp4",
                "duration": 4.0,
                "type": "video",
            },
        ],
        audio_url="https://example.com/audio.mp3",
    )
