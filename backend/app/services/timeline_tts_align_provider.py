from __future__ import annotations

import json
import os
import time
import urllib.request
import urllib.error
import uuid
from typing import Any

from app.services.timeline_engine_provider import build_timeline


LOCAL_TTS_URL = os.getenv("AI_VIDEO_LOCAL_TTS_URL", "http://127.0.0.1:8000/api/tts-segments").strip()


def _srt_time(seconds: float) -> str:
    ms_total = int(round(float(seconds) * 1000))
    h = ms_total // 3600000
    ms_total %= 3600000
    m = ms_total // 60000
    ms_total %= 60000
    s = ms_total // 1000
    ms = ms_total % 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _build_srt_from_segments(segments: list[dict[str, Any]]) -> str:
    lines: list[str] = []

    for i, seg in enumerate(segments, start=1):
        start = float(seg.get("start") or 0)
        end = float(seg.get("end") or start)
        text = str(seg.get("subtitle_text") or seg.get("text") or "").strip()

        lines.append(str(i))
        lines.append(f"{_srt_time(start)} --> {_srt_time(end)}")
        lines.append(text)
        lines.append("")

    return "\n".join(lines).strip()


def _build_shot_plan_from_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []

    for i, seg in enumerate(segments):
        plan.append(
            {
                "index": i,
                "start": round(float(seg.get("start") or 0), 3),
                "end": round(float(seg.get("end") or 0), 3),
                "duration": round(float(seg.get("duration") or 0), 3),
                "text": seg.get("text") or "",
                "shot_hint": seg.get("shot_hint") or "normal",
                "emotion": seg.get("emotion") or "neutral",
                "emphasis": seg.get("emphasis") or 1.0,
                "sync_source": seg.get("sync_source") or "timeline_estimate",
            }
        )

    return plan


def _timeline_segments_for_tts(timeline: dict[str, Any]) -> list[dict[str, Any]]:
    items = timeline.get("segments") or []
    payload_segments: list[dict[str, Any]] = []

    for item in items:
        text = str(item.get("text") or "").strip()
        if not text:
            continue

        payload_segments.append(
            {
                "index": int(item.get("index") or 0) + 1,
                "text": text,
                "pause_after_ms": 120,
                "speed_ratio": 1.0,
            }
        )

    return payload_segments


def _post_json(url: str, payload: dict[str, Any], timeout: int = 300) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
    }

    token = os.getenv("AI_VIDEO_API_TOKEN", "").strip()
    if token:
        headers["X-AI-Video-Token"] = token

    req = urllib.request.Request(
        url=url,
        data=body,
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw or "{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"TTS HTTP {exc.code}: {raw[:1000]}") from exc


def _proportional_align(
    timeline_segments: list[dict[str, Any]],
    total_duration: float,
    source: str,
) -> list[dict[str, Any]]:
    estimated_total = sum(float(x.get("duration") or 0) for x in timeline_segments)
    if estimated_total <= 0:
        estimated_total = max(total_duration, 0.01)

    current = 0.0
    aligned: list[dict[str, Any]] = []

    for i, seg in enumerate(timeline_segments):
        est = float(seg.get("duration") or 0)
        if i == len(timeline_segments) - 1:
            duration = max(0.2, float(total_duration) - current)
        else:
            duration = max(0.2, float(total_duration) * est / estimated_total)

        start = round(current, 3)
        end = round(start + duration, 3)

        item = dict(seg)
        item.update(
            {
                "index": i,
                "start": start,
                "end": end,
                "duration": round(duration, 3),
                "sync_source": source,
                "timeline_estimated_start": seg.get("start"),
                "timeline_estimated_end": seg.get("end"),
                "timeline_estimated_duration": seg.get("duration"),
            }
        )
        aligned.append(item)

        current = end

    return aligned


def _direct_align(
    timeline_segments: list[dict[str, Any]],
    tts_segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    aligned: list[dict[str, Any]] = []

    for i, seg in enumerate(timeline_segments):
        tts_seg = tts_segments[i] if i < len(tts_segments) else {}

        start = float(tts_seg.get("start") or 0)
        end = float(tts_seg.get("end") or start)
        duration = float(tts_seg.get("duration") or max(0.2, end - start))

        item = dict(seg)
        item.update(
            {
                "index": i,
                "start": round(start, 3),
                "end": round(end, 3),
                "duration": round(duration, 3),
                "sync_source": "tts_segment_timing",
                "tts_text": tts_seg.get("text") or "",
                "timeline_estimated_start": seg.get("start"),
                "timeline_estimated_end": seg.get("end"),
                "timeline_estimated_duration": seg.get("duration"),
            }
        )
        aligned.append(item)

    return aligned


def build_tts_aligned_timeline(
    text: str,
    voice: str = "default",
    overall_rate: str = "0%",
    tts_provider: str | None = None,
    target_duration: float | None = None,
    dry_run: bool = True,
    speech_rate_cps: float = 4.2,
    min_segment_duration: float = 1.8,
    max_segment_duration: float = 6.5,
) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        raise ValueError("text 不能为空")

    timeline = build_timeline(
        text=text,
        target_duration=target_duration,
        speech_rate_cps=speech_rate_cps,
        min_segment_duration=min_segment_duration,
        max_segment_duration=max_segment_duration,
    )

    timeline_segments = timeline.get("segments") or []
    estimated_total = float(timeline.get("total_duration") or 0)
    align_id = f"timeline_tts_align_{uuid.uuid4().hex[:18]}"

    if dry_run:
        aligned_segments = [
            {
                **seg,
                "sync_source": "timeline_estimate_dry_run",
                "timeline_estimated_start": seg.get("start"),
                "timeline_estimated_end": seg.get("end"),
                "timeline_estimated_duration": seg.get("duration"),
            }
            for seg in timeline_segments
        ]

        return {
            "ok": True,
            "provider": "timeline_tts_align_v1",
            "align_id": align_id,
            "dry_run": True,
            "status": "planned",
            "timeline_id": timeline.get("timeline_id"),
            "audio_url": "",
            "audio_duration": 0,
            "estimated_total_duration": round(estimated_total, 3),
            "actual_total_duration": 0,
            "drift_seconds": 0,
            "segment_count": len(aligned_segments),
            "segments": aligned_segments,
            "srt_preview": _build_srt_from_segments(aligned_segments),
            "shot_plan": _build_shot_plan_from_segments(aligned_segments),
            "tts_payload_preview": {
                "text": text,
                "voice": voice,
                "overall_rate": overall_rate,
                "segments": _timeline_segments_for_tts(timeline),
            },
            "message": "dry_run 已通过：未调用 TTS。真实执行时会用 TTS 返回的真实音频时长回写 timeline。",
        }

    tts_payload = {
        "text": text,
        "voice": voice,
        "overall_rate": overall_rate,
        "segments": _timeline_segments_for_tts(timeline),
    }

    if tts_provider:
        tts_payload["tts_provider"] = tts_provider

    tts_result = _post_json(LOCAL_TTS_URL, tts_payload, timeout=300)

    audio_url = (
        tts_result.get("file_url")
        or tts_result.get("audio_url")
        or tts_result.get("url")
        or ""
    )

    audio_duration = float(tts_result.get("duration_seconds") or tts_result.get("duration") or 0)
    tts_segments = tts_result.get("segments") or []

    if isinstance(tts_segments, list) and len(tts_segments) == len(timeline_segments):
        aligned_segments = _direct_align(timeline_segments, tts_segments)
        sync_mode = "direct_tts_segment_timing"
    else:
        aligned_segments = _proportional_align(
            timeline_segments,
            total_duration=audio_duration or estimated_total,
            source="tts_total_duration_proportional",
        )
        sync_mode = "proportional_from_tts_total_duration"

    actual_total = 0.0
    if aligned_segments:
        actual_total = float(aligned_segments[-1].get("end") or 0)

    drift = round(actual_total - estimated_total, 3)

    response = {
        "ok": True,
        "provider": "timeline_tts_align_v1",
        "align_id": align_id,
        "dry_run": False,
        "status": "done",
        "sync_mode": sync_mode,
        "timeline_id": timeline.get("timeline_id"),
        "audio_url": audio_url,
        "audio_duration": round(audio_duration, 3),
        "estimated_total_duration": round(estimated_total, 3),
        "actual_total_duration": round(actual_total, 3),
        "drift_seconds": drift,
        "segment_count": len(aligned_segments),
        "segments": aligned_segments,
        "srt_preview": _build_srt_from_segments(aligned_segments),
        "shot_plan": _build_shot_plan_from_segments(aligned_segments),
        "tts_warning": tts_result.get("warning"),
        "tts_result_summary": {
            "file_name": tts_result.get("file_name"),
            "duration_seconds": tts_result.get("duration_seconds"),
            "segments_count": len(tts_segments) if isinstance(tts_segments, list) else 0,
        },
        "message": "Timeline 已用 TTS 真实音频时长回写。后续字幕和镜头应使用这里返回的 segments / srt_preview / shot_plan。",
    }

    return response


def health() -> dict[str, Any]:
    return {
        "ok": True,
        "provider": "timeline_tts_align_v1",
        "local_tts_url": LOCAL_TTS_URL,
        "message": "Timeline → TTS 对齐桥可用：dry_run 不调用 TTS，dry_run=false 会生成 TTS 并用真实音频时长回写时间轴。",
    }


def self_test(dry_run: bool = True) -> dict[str, Any]:
    return build_tts_aligned_timeline(
        text="AI视频要解决同步问题，必须先统一时间轴。然后用真实语音时长回写字幕和镜头节奏。",
        dry_run=dry_run,
    )
