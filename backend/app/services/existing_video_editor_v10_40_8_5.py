from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import shutil
import subprocess
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx
from fastapi import Depends, HTTPException, Request

from app.schemas import VoiceSegment
from app.services.storage import maybe_upload_to_r2
from app.services.subtitle_style_library_provider import (
    burn_subtitles_with_style_and_upload,
)
from app.services.tts import synthesize_tts_segments
from app.services.subtitle_edit_director_v10_40_8_7 import (
    burn_directed_subtitles_with_upload,
    direct_existing_video,
)

VERSION = "10.40.8.8-a10-r2"
# V10_40_8_8_A10_R2_ADAPTIVE_QUALITY_GATE_FIX: adaptive quality gate
# V10_40_8_8_A10_KEYWORD_BURST_EDIT_QUALITY_A1: A10 reports and health
INSTALL_MARKER = "existing_video_smart_edit_v10_40_8_5_2"
_LOCK = threading.RLock()
_INSTALLED = False
_ACTIVE: set[str] = set()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _jobs_path(settings: Any) -> Path:
    return settings.data_dir / "existing_video_edit_jobs.json"


def _load_jobs(settings: Any) -> dict[str, dict[str, Any]]:
    path = _jobs_path(settings)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_jobs(settings: Any, jobs: dict[str, dict[str, Any]]) -> None:
    path = _jobs_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _update_job(settings: Any, job_id: str, **patch: Any) -> dict[str, Any]:
    with _LOCK:
        jobs = _load_jobs(settings)
        item = dict(jobs.get(job_id) or {"job_id": job_id, "version": VERSION})
        item.update(patch)
        item["version"] = VERSION
        item["updated_at"] = _now()
        jobs[job_id] = item
        _save_jobs(settings, jobs)
        return dict(item)


def _split_script(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if not text:
        return []
    parts = [
        item.strip(" ，,。！？!?；;")
        for item in re.split(r"(?<=[。！？!?；;])|\n+", text)
        if item.strip(" ，,。！？!?；;")
    ]
    if len(parts) == 1 and len(parts[0]) > 32:
        raw = parts[0]
        parts = [raw[i : i + 22] for i in range(0, len(raw), 22)]
    return parts[:40]


def _speech_parts(payload: dict[str, Any]) -> list[str]:
    parts = [
        str(item.get("text") or "").strip()
        for item in (payload.get("script_segments") or [])
        if isinstance(item, dict) and str(item.get("text") or "").strip()
    ]
    return parts or _split_script(
        str(payload.get("script_text") or payload.get("script") or "")
    )


def _tokens(text: str) -> set[str]:
    text = str(text or "").lower()
    words = re.findall(r"[a-z0-9_]{2,}|[\u4e00-\u9fff]{2,}", text)
    zh = "".join(re.findall(r"[\u4e00-\u9fff]", text))
    words += [zh[i : i + 2] for i in range(max(0, len(zh) - 1))]
    stop = {
        "这个",
        "一个",
        "我们",
        "就是",
        "可以",
        "视频",
        "素材",
        "画面",
        "项目",
        "介绍",
        "相关",
    }
    return {word for word in words if word not in stop}


def _asset_id(asset: dict[str, Any]) -> str:
    return str(
        asset.get("id")
        or asset.get("asset_id")
        or asset.get("r2_key")
        or asset.get("filename")
        or ""
    ).strip()


def _asset_url(asset: dict[str, Any]) -> str:
    return str(asset.get("url") or asset.get("r2_url") or "").strip()


def _asset_intelligence(asset: dict[str, Any]) -> dict[str, Any]:
    value = asset.get("asset_intelligence") or asset.get("intelligence") or {}
    return dict(value) if isinstance(value, dict) else {}


def _asset_text(asset: dict[str, Any]) -> str:
    intel = _asset_intelligence(asset)
    fields = [
        asset.get("original_name"),
        asset.get("filename"),
        asset.get("ai_title"),
        asset.get("ai_description"),
        asset.get("ai_primary_category"),
        asset.get("ai_secondary_category"),
        intel.get("title"),
        intel.get("description"),
        intel.get("primary_category"),
        intel.get("secondary_category"),
        intel.get("location"),
        intel.get("scene"),
        " ".join(asset.get("ai_keywords") or []),
        " ".join(intel.get("keywords") or []),
        " ".join(intel.get("recommended_topics") or []),
    ]
    return " ".join(str(item or "") for item in fields)


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _usable_seconds(asset: dict[str, Any]) -> float:
    intel = _asset_intelligence(asset)
    technical = intel.get("technical") if isinstance(intel.get("technical"), dict) else {}
    duration = (
        _float(asset.get("duration"))
        or _float(asset.get("duration_seconds"))
        or _float(technical.get("duration"))
    )
    if duration <= 0:
        return 4.0
    # Conservatively exclude unusable heads/tails instead of counting the entire file.
    return round(max(2.4, min(7.0, duration * 0.72)), 3)


def _eligible_video(asset: dict[str, Any]) -> bool:
    if str(asset.get("kind") or "").lower() != "video":
        return False
    if not _asset_url(asset):
        return False
    if bool(asset.get("deleted")):
        return False
    if str(asset.get("usage_role") or "content").lower() == "avatar":
        return False
    intel = _asset_intelligence(asset)
    if str(intel.get("analysis_status") or "").lower() == "failed":
        return False
    clean = intel.get("cleanliness") or asset.get("ai_cleanliness") or {}
    if isinstance(clean, dict) and str(clean.get("status") or "").lower() == "failed":
        return False
    return True


def _public_asset(asset: dict[str, Any], source: str) -> dict[str, Any]:
    intel = _asset_intelligence(asset)
    return {
        "id": _asset_id(asset),
        "asset_id": _asset_id(asset),
        "name": str(
            asset.get("original_name")
            or asset.get("filename")
            or intel.get("title")
            or _asset_id(asset)
        ),
        "filename": str(asset.get("filename") or ""),
        "kind": "video",
        "url": _asset_url(asset),
        "r2_url": _asset_url(asset),
        "selection_source": source,
        "locked": source == "manual",
        "estimated_usable_seconds": _usable_seconds(asset),
        "title": str(intel.get("title") or asset.get("ai_title") or ""),
        "description": str(
            intel.get("description") or asset.get("ai_description") or ""
        ),
        "primary_category": str(
            intel.get("primary_category") or asset.get("ai_primary_category") or ""
        ),
        "secondary_category": str(
            intel.get("secondary_category")
            or asset.get("ai_secondary_category")
            or ""
        ),
        "quality_score": int(
            _float(intel.get("quality_score") or asset.get("ai_quality_score"), 60)
        ),
    }


def _load_library_assets(settings: Any) -> list[dict[str, Any]]:
    if settings is None:
        return []
    try:
        from app.services.asset_intelligence_v10_40_8_4_3 import (
            _assets_map,
            _load_index,
        )

        assets = _assets_map(settings)
        index = _load_index(settings)
    except Exception:
        return []

    result: list[dict[str, Any]] = []
    for asset_id, raw in assets.items():
        if not isinstance(raw, dict):
            continue
        asset = dict(raw)
        asset.setdefault("id", asset_id)
        record = index.get(asset_id) if isinstance(index, dict) else None
        if isinstance(record, dict) and record:
            asset["asset_intelligence"] = {
                **_asset_intelligence(asset),
                **record,
            }
        if _eligible_video(asset):
            result.append(asset)
    return result


def _merge_candidates(
    selected: list[dict[str, Any]], library: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    manual: list[dict[str, Any]] = []
    auto_pool: list[dict[str, Any]] = []
    seen: set[str] = set()

    for raw in selected:
        asset = dict(raw)
        aid = _asset_id(asset)
        if not aid or aid in seen or not _eligible_video(asset):
            continue
        asset["_selection_source"] = "manual"
        asset["_locked"] = True
        manual.append(asset)
        seen.add(aid)

    for raw in library:
        asset = dict(raw)
        aid = _asset_id(asset)
        if not aid or aid in seen or not _eligible_video(asset):
            continue
        asset["_selection_source"] = "auto"
        asset["_locked"] = False
        auto_pool.append(asset)
        seen.add(aid)

    return manual, auto_pool


def _score(segment: str, asset: dict[str, Any], reuse: int) -> float:
    segment_tokens = _tokens(segment)
    asset_tokens = _tokens(_asset_text(asset))
    intel = _asset_intelligence(asset)
    quality = _float(asset.get("ai_quality_score") or intel.get("quality_score"), 60)
    clean = intel.get("cleanliness") or asset.get("ai_cleanliness") or {}
    clean_bonus = (
        -100.0
        if isinstance(clean, dict)
        and str(clean.get("status") or "").lower() == "failed"
        else 5.0
    )
    manual_bonus = 18.0 if asset.get("_selection_source") == "manual" else 0.0
    unused_bonus = 12.0 if reuse == 0 else 0.0
    text = _asset_text(asset).lower()
    return (
        len(segment_tokens & asset_tokens) * 9
        + sum(1 for token in segment_tokens if token in text) * 3
        + quality / 18
        + clean_bonus
        + manual_bonus
        + unused_bonus
        - reuse * 24
    )


def _durations(count: int, target: float) -> list[float]:
    count = max(1, int(count))
    target = max(float(target or 15), count * 1.0)
    base = target / count
    values = [round(base, 3) for _ in range(count)]
    values[-1] = round(values[-1] + target - sum(values), 3)
    return values


def _visual_parts(parts: list[str], count: int) -> list[str]:
    if not parts:
        return []
    if count <= len(parts):
        return parts[:count]
    result: list[str] = []
    for index in range(count):
        result.append(parts[index % len(parts)])
    return result


def _desired_clip_count(
    parts: list[str], manual_count: int, target: float, pace: str
) -> int:
    seconds_per_clip = {
        "fast": 2.8,
        "normal": 3.8,
        "slow": 4.8,
        "relaxed": 4.8,
    }.get(str(pace or "normal").lower(), 3.8)
    count = max(
        len(parts),
        manual_count,
        int(math.ceil(max(1.0, target) / seconds_per_clip)),
    )
    return max(1, min(count, 24))


def build_edit_plan(
    payload: dict[str, Any],
    *,
    settings: Any = None,
    target_duration_override: float | None = None,
) -> dict[str, Any]:
    parts = _speech_parts(payload)
    if not parts:
        raise ValueError("缺少口播文案，无法匹配现有视频")

    selected = [
        dict(item)
        for item in (
            payload.get("selected_assets")
            or payload.get("asset_context")
            or payload.get("r2_material_context")
            or []
        )
        if isinstance(item, dict)
    ]
    # V10_40_8_6_A2_R2_AUTO_MATERIAL_SEMANTIC
    library_assets = _load_library_assets(settings)
    manual, auto_pool = _merge_candidates(
        selected,
        library_assets,
    )
    material_mode = str(
        payload.get("material_selection_mode")
        or ("hybrid" if manual else "auto")
    ).strip().lower()

    if material_mode not in {"auto", "hybrid", "manual"}:
        material_mode = (
            "hybrid"
            if manual
            else "auto"
        )

    if material_mode == "auto":
        manual, auto_pool = _merge_candidates(
            [],
            library_assets,
        )
    elif material_mode == "manual":
        auto_pool = []

    if material_mode == "manual" and not manual:
        raise ValueError(
            "纯人工模式没有锁定视频素材。请先从素材库带入视频"
        )

    if not manual and not auto_pool:
        raise ValueError(
            "R2 素材库没有可用视频。请确认素材已经上传、"
            "具有可访问 URL，并且素材分析没有失败"
        )

    target = float(
        target_duration_override
        or payload.get("actual_tts_duration_seconds")
        or payload.get("target_duration_seconds")
        or 30
    )
    target = max(1.0, target)
    auto_fill = material_mode in {"auto", "hybrid"}
    clip_count = _desired_clip_count(
        parts,
        len(manual),
        target,
        str(payload.get("edit_pace") or "normal"),
    )
    if not auto_fill:
        clip_count = max(len(parts), len(manual))

    visual_parts = _visual_parts(parts, clip_count)
    durations = _durations(len(visual_parts), target)
    reuse: dict[str, int] = {}
    unused_manual = {_asset_id(item) for item in manual}
    candidates = [*manual, *(auto_pool if auto_fill else [])]
    if not candidates:
        raise ValueError("没有满足条件的 R2 视频素材，无法生成剪辑计划")
    clips: list[dict[str, Any]] = []
    auto_used: dict[str, dict[str, Any]] = {}
    manual_used: dict[str, dict[str, Any]] = {}

    for index, (part, duration) in enumerate(
        zip(visual_parts, durations), start=1
    ):
        # Every manually selected asset is locked and consumed before automatic fill.
        if unused_manual:
            pool = [item for item in manual if _asset_id(item) in unused_manual]
        else:
            pool = candidates

        ranked = sorted(
            pool,
            key=lambda asset: _score(
                part, asset, reuse.get(_asset_id(asset), 0)
            ),
            reverse=True,
        )
        if not ranked:
            ranked = manual
        chosen = ranked[0]
        aid = _asset_id(chosen)
        unused_manual.discard(aid)
        source = str(chosen.get("_selection_source") or "manual")
        reuse[aid] = reuse.get(aid, 0) + 1
        if source == "manual":
            manual_used[aid] = chosen
        else:
            auto_used[aid] = chosen

        intel = _asset_intelligence(chosen)
        title = str(
            chosen.get("ai_title")
            or intel.get("title")
            or chosen.get("original_name")
            or chosen.get("filename")
            or f"素材{index}"
        )
        description = str(
            chosen.get("ai_description") or intel.get("description") or title
        )
        clips.append(
            {
                "id": f"existing_clip_{index}",
                "index": index,
                "title": title,
                "scene": description,
                "description": description,
                "narration": part,
                "duration": duration,
                "duration_seconds": duration,
                "source": "r2",
                "selection_source": source,
                "manual_locked": source == "manual",
                "asset_id": aid,
                "asset_ids": [aid],
                "asset_url": _asset_url(chosen),
                "asset_name": str(
                    chosen.get("original_name")
                    or chosen.get("filename")
                    or title
                ),
                "start_time": 0.0,
                "end_time": duration,
                "auto_start": True,
                "preserve_audio": str(
                    payload.get("voice_mode") or "tts_with_ambient"
                )
                != "tts_only",
                "speed": 1.0,
                "transition": "轻柔淡化",
                "camera": "保留原片运镜",
                "match_score": round(
                    _score(part, chosen, max(0, reuse[aid] - 1)), 2
                ),
                "analysis_description": description,
            }
        )

    # Keep all locked assets visible in the result even if a future pace cap changes.
    for item in manual:
        manual_used.setdefault(_asset_id(item), item)

    invalid_r2_clips = [
        item
        for item in clips
        if str(item.get("source") or "").lower() != "r2"
        or not str(item.get("asset_url") or "").strip()
    ]

    if invalid_r2_clips:
        raise ValueError(
            "R2 自动匹配返回了未绑定视频 URL 的片段，"
            "已阻止进入剪辑"
        )

    manual_seconds = round(
        sum(_usable_seconds(item) for item in manual_used.values()), 3
    )
    auto_seconds = round(
        sum(_usable_seconds(item) for item in auto_used.values()), 3
    )
    required_seconds = round(target * 1.08, 3)
    source_seconds = round(manual_seconds + auto_seconds, 3)
    coverage = {
        "actual_tts_seconds": round(target, 3),
        "required_seconds_with_buffer": required_seconds,
        "timeline_seconds": round(sum(item["duration"] for item in clips), 3),
        "manual_selected_count": len(manual),
        "manual_used_count": len(manual_used),
        "auto_selected_count": len(auto_used),
        "manual_estimated_seconds": manual_seconds,
        "auto_estimated_seconds": auto_seconds,
        "estimated_unique_source_seconds": source_seconds,
        "estimated_shortage_seconds": round(
            max(0.0, required_seconds - source_seconds), 3
        ),
        "auto_fill_enabled": auto_fill,
        "real_tts_replanned": target_duration_override is not None,
        "status": (
            "covered"
            if source_seconds >= required_seconds
            else "reused_with_guard"
        ),
    }

    return {
        "ok": True,
        "version": VERSION,
        "mode": "existing_edit",
        "material_selection_mode": material_mode,
        "fal_used": False,
        "billing_guard": "existing_edit_no_fal",
        "message": (
            f"人工锁定 {len(manual)} 条，系统自动补充 {len(auto_used)} 条，"
            f"按 {target:.1f} 秒口播生成 {len(clips)} 个剪辑片段"
        ),
        "clips": clips,
        "manual_selected_assets": [
            _public_asset(item, "manual") for item in manual_used.values()
        ],
        "auto_selected_assets": [
            _public_asset(item, "auto") for item in auto_used.values()
        ],
        "selected_video_count": len(manual),
        "auto_selected_video_count": len(auto_used),
        "target_duration_seconds": round(
            sum(item["duration"] for item in clips), 3
        ),
        "coverage": coverage,
    }


def _run(
    command: list[str], timeout: int = 1800
) -> subprocess.CompletedProcess[str]:
    process = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if process.returncode != 0:
        raise RuntimeError(
            (process.stderr or process.stdout or "命令执行失败")[-3000:]
        )
    return process


def _probe(path: Path) -> dict[str, Any]:
    process = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,width,height",
            "-of",
            "json",
            str(path),
        ],
        60,
    )
    data = json.loads(process.stdout or "{}")
    streams = data.get("streams") or []
    video = next(
        (item for item in streams if item.get("codec_type") == "video"), {}
    )
    return {
        "duration": _float((data.get("format") or {}).get("duration")),
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "has_audio": any(
            item.get("codec_type") == "audio" for item in streams
        ),
    }


async def _download(url: str, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(1800, connect=30),
        follow_redirects=True,
    ) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            with destination.open("wb") as stream:
                async for chunk in response.aiter_bytes(1024 * 1024):
                    if chunk:
                        stream.write(chunk)
    if destination.stat().st_size < 1024:
        raise RuntimeError(f"素材下载失败：{url}")
    return destination


def _size(ratio: str) -> tuple[int, int]:
    if ratio == "16:9":
        return 1920, 1080
    if ratio == "1:1":
        return 1080, 1080
    return 1080, 1920


def _stable_start(asset_id: str, total: float, needed: float) -> float:
    available = max(0.0, total - needed - 0.15)
    if available <= 0.05:
        return 0.0
    seed = int(hashlib.sha256(asset_id.encode()).hexdigest()[:8], 16)
    return round((seed % 10000) / 10000 * available, 3)


def _normalize_clip(
    source: Path,
    destination: Path,
    *,
    start: float,
    duration: float,
    speed: float,
    width: int,
    height: int,
    keep_audio: bool,
) -> None:
    info = _probe(source)
    speed = max(0.75, min(1.5, float(speed or 1)))
    duration = max(0.65, float(duration))
    needed = duration * speed
    start = max(
        0.0,
        min(start, max(0.0, float(info["duration"] or needed) - needed)),
    )
    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{start:.3f}",
        "-t",
        f"{needed:.3f}",
        "-i",
        str(source),
        "-f",
        "lavfi",
        "-t",
        f"{duration:.3f}",
        "-i",
        "anullsrc=channel_layout=stereo:sample_rate=44100",
    ]
    video_filter = (
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar=1,fps=30,setpts=PTS/{speed:.5f},"
        f"tpad=stop_mode=clone:stop_duration={duration:.3f},"
        f"trim=duration={duration:.3f}[v]"
        ""
        ""
    )
    if keep_audio and info["has_audio"]:
        audio_filter = (
            f"[0:a]atrim=0:{needed:.3f},asetpts=N/SR/TB,"
            f"atempo={speed:.5f},aresample=44100,volume=0.22,"
            f"apad=pad_dur={duration:.3f},atrim=duration={duration:.3f}[a]"
        )
    else:
        audio_filter = "[1:a]anull[a]"
    command += [
        "-filter_complex",
        f"{video_filter};{audio_filter}",
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-t",
        f"{duration:.3f}",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "22",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-ar",
        "44100",
        "-ac",
        "2",
        "-movflags",
        "+faststart",
        str(destination),
    ]
    _run(command)


def _concat(clips: list[Path], destination: Path) -> None:
    command = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    for clip in clips:
        command += ["-i", str(clip)]
    refs = "".join(
        f"[{index}:v:0][{index}:a:0]" for index in range(len(clips))
    )
    command += [
        "-filter_complex",
        f"{refs}concat=n={len(clips)}:v=1:a=1[v][a]",
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "21",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-movflags",
        "+faststart",
        str(destination),
    ]
    _run(command, 3600)


def _mix(
    base: Path, tts: Path | None, mode: str, destination: Path
) -> None:
    if mode == "retain_original" or not tts:
        shutil.copy2(base, destination)
        return
    audio_filter = (
        "[0:a]volume=0.16[amb];"
        "[1:a]volume=1,apad[voice];"
        "[amb][voice]amix=inputs=2:duration=first:normalize=0[a]"
        if mode == "tts_with_ambient"
        else "[1:a]volume=1,apad[a]"
    )
    _run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(base),
            "-i",
            str(tts),
            "-filter_complex",
            audio_filter,
            "-map",
            "0:v:0",
            "-map",
            "[a]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            "-movflags",
            "+faststart",
            str(destination),
        ]
    )


def _url(settings: Any, path: Path, prefix: str) -> str:
    return (
        maybe_upload_to_r2(settings, path, prefix=prefix)
        or f"/files/outputs/{path.name}"
    )


def _voice_segments(
    payload: dict[str, Any], parts: list[str]
) -> list[VoiceSegment]:
    raw = payload.get("script_segments") or []
    settings_map = payload.get("segment_voice_settings") or {}
    result: list[VoiceSegment] = []
    for index, text in enumerate(parts, 1):
        item = (
            raw[index - 1]
            if index - 1 < len(raw) and isinstance(raw[index - 1], dict)
            else {}
        )
        voice = settings_map.get(str(item.get("id") or f"seg_{index}")) or {}
        result.append(
            VoiceSegment(
                text=text,
                emotion=str(voice.get("emotion") or "自然可信"),
                speed_ratio=float(
                    voice.get("speed") or voice.get("speed_ratio") or 1
                ),
                volume_ratio=float(
                    voice.get("volume") or voice.get("volume_ratio") or 1
                ),
                pitch_ratio=float(
                    voice.get("pitch") or voice.get("pitch_ratio") or 1
                ),
                pause_after_ms=int(
                    voice.get("pauseAfter")
                    or voice.get("pause_after_ms")
                    or 220
                ),
            )
        )
    return result


def _cues(parts: list[str], target: float) -> list[dict[str, Any]]:
    durations = _durations(len(parts), target)
    output: list[dict[str, Any]] = []
    cursor = 0.0
    for index, (text, duration) in enumerate(zip(parts, durations), start=1):
        output.append(
            {
                "index": index,
                "text": text,
                "start": round(cursor, 3),
                "end": round(cursor + duration, 3),
                "duration": round(duration, 3),
            }
        )
        cursor += duration
    return output


async def _render(
    settings: Any, job_id: str, payload: dict[str, Any]
) -> None:
    work = settings.tmp_dir / "existing_video_edit" / job_id
    work.mkdir(parents=True, exist_ok=True)
    try:
        parts = _speech_parts(payload)
        if not parts:
            raise ValueError("缺少口播文案，无法剪辑")

        mode = str(payload.get("voice_mode") or "tts_with_ambient")
        tts: Path | None = None
        warning: str | None = None
        _update_job(
            settings,
            job_id,
            status="running",
            stage="tts",
            progress=5,
            message=(
                "正在生成配音并读取真实时长"
                if mode != "retain_original"
                else "保留原声模式，正在计算剪辑时长"
            ),
        )

        if mode != "retain_original":
            tts, audio_duration, warning, timings = (
                await synthesize_tts_segments(
                    settings,
                    _voice_segments(payload, parts),
                    voice=str(payload.get("voice") or "") or None,
                    overall_rate=str(payload.get("overall_rate") or "") or None,
                )
            )
            target = max(1.0, float(audio_duration))
        else:
            target = max(
                1.0,
                float(payload.get("target_duration_seconds") or 30),
            )
            timings = _cues(parts, target)

        # Rebuild after TTS. This is the core guard against short material and
        # repeated tail footage when the actual narration is longer than target.
        incoming_plan = (
            payload.get("edit_plan")
            if isinstance(payload.get("edit_plan"), dict)
            else {}
        )
        incoming_clips = (
            incoming_plan.get("clips")
            if isinstance(incoming_plan.get("clips"), list)
            else []
        )
        run_material_mode = str(
            payload.get("material_selection_mode")
            or ("hybrid" if payload.get("selected_assets") else "auto")
        ).strip().lower()
        valid_incoming_plan = bool(incoming_clips) and all(
            isinstance(item, dict)
            and str(item.get("source") or "").lower() == "r2"
            and bool(str(item.get("asset_url") or "").strip())
            for item in incoming_clips
        )
        locked_plan = bool(payload.get("lock_edit_plan"))
        use_locked_plan = (
            locked_plan
            and run_material_mode != "auto"
            and valid_incoming_plan
        )

        if use_locked_plan:
            plan = dict(payload["edit_plan"])
            clips = [dict(item) for item in plan["clips"]]
            original = max(
                0.001, sum(float(item.get("duration") or 2) for item in clips)
            )
            factor = target / original
            for clip in clips:
                clip["duration"] = round(
                    max(1.0, float(clip.get("duration") or 2) * factor), 3
                )
            clips[-1]["duration"] = round(
                clips[-1]["duration"]
                + target
                - sum(float(item["duration"]) for item in clips),
                3,
            )
            plan["clips"] = clips
            plan.setdefault("coverage", {})
            plan["coverage"].update(
                {
                    "actual_tts_seconds": round(target, 3),
                    "timeline_seconds": round(target, 3),
                    "real_tts_replanned": True,
                    "manual_plan_locked": True,
                }
            )
        else:
            plan = build_edit_plan(
                payload,
                settings=settings,
                target_duration_override=target,
            )
            clips = [dict(item) for item in plan["clips"]]

        # V10_40_8_7_A9_R3_SPLIT_SOURCE_CONTRACT: runtime director
        director_result = await direct_existing_video(
            settings=settings,
            payload=payload,
            timings=timings,
            clips=clips,
            target_duration=target,
        )
        clips = [dict(item) for item in director_result["clips"]]
        timings = [dict(item) for item in director_result["subtitle_segments"]]
        plan = {**plan, "clips": clips, "director": director_result["report"]}
        payload = {
            **payload,
            "subtitle_style": director_result["subtitle_style"],
            "keyword_insights": [
                {"value": value}
                for value in director_result["subtitle_keywords"]
            ],
        }

        _update_job(
            settings,
            job_id,
            stage="asset_autofill",
            progress=9,
            message=plan.get("message"),
            edit_plan=plan,
            coverage=plan.get("coverage"),
            manual_selected_assets=plan.get("manual_selected_assets"),
            auto_selected_assets=plan.get("auto_selected_assets"),
            audio_duration_seconds=round(target, 3),
            fal_used=False,
        )

        width, height = _size(str(payload.get("output_ratio") or "9:16"))
        cache: dict[str, Path] = {}
        normalized: list[Path] = []

        for position, clip in enumerate(clips, start=1):
            _update_job(
                settings,
                job_id,
                stage="clip_render",
                progress=10 + int((position - 1) / len(clips) * 55),
                current_clip=position,
                current_file=clip.get("asset_name"),
                message=f"正在剪辑 {position}/{len(clips)}",
            )
            source_url = str(clip.get("asset_url") or "")
            key = hashlib.sha256(source_url.encode()).hexdigest()[:16]
            if source_url not in cache:
                suffix = Path(source_url.split("?", 1)[0]).suffix or ".mp4"
                cache[source_url] = await _download(
                    source_url, work / "sources" / f"{key}{suffix}"
                )
            source = cache[source_url]
            info = _probe(source)
            duration = float(clip["duration"])
            speed = float(clip.get("speed") or 1)
            needed = duration * speed
            start = (
                _stable_start(
                    str(clip.get("asset_id") or key),
                    float(info["duration"] or needed),
                    needed,
                )
                if clip.get("auto_start", True)
                or float(clip.get("start_time") or 0) <= 0
                else float(clip.get("start_time") or 0)
            )
            destination = work / "clips" / f"{position:03d}.mp4"
            destination.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(
                _normalize_clip,
                source,
                destination,
                start=start,
                duration=duration,
                speed=speed,
                width=width,
                height=height,
                keep_audio=(
                    mode in {"retain_original", "tts_with_ambient"}
                    and clip.get("preserve_audio", True)
                ),
            )
            clip["actual_start_time"] = start
            clip["actual_end_time"] = round(start + needed, 3)
            normalized.append(destination)

        _update_job(
            settings,
            job_id,
            stage="concat",
            progress=70,
            message="正在合并片段",
        )
        base = settings.outputs_dir / f"{job_id}_clips.mp4"
        await asyncio.to_thread(_concat, normalized, base)

        mixed = settings.outputs_dir / f"{job_id}_mixed.mp4"
        _update_job(
            settings,
            job_id,
            stage="audio_mix",
            progress=80,
            message="正在混音",
        )
        await asyncio.to_thread(_mix, base, tts, mode, mixed)

        raw_url = _url(settings, mixed, "videos/existing-edit/raw")
        audio_url = _url(settings, tts, "audio/existing-edit") if tts else ""
        final_url = raw_url
        subtitle_result = None

        if bool(payload.get("burn_subtitles", True)):
            _update_job(
                settings,
                job_id,
                stage="subtitle_burn",
                progress=90,
                message="正在烧录字幕",
            )
            keywords = [
                str(item.get("value") or "")
                for item in (payload.get("keyword_insights") or [])
                if isinstance(item, dict) and item.get("value")
            ]
            subtitle_result = await asyncio.to_thread(
                burn_directed_subtitles_with_upload,
                video_path=str(mixed),
                text=str(payload.get("script_text") or ""),
                segments=timings,
                duration=target,
                style_id=str(
                    payload.get("subtitle_style_id") or "douyin_pop"
                ),
                keywords=keywords,
                prefix=f"{job_id}_subtitle",
                object_key=(
                    "videos/existing-edit/subtitled/"
                    f"{datetime.now().strftime('%Y/%m/%d')}/{job_id}.mp4"
                ),
                subtitle_style=(
                    payload.get("subtitle_style")
                    if isinstance(payload.get("subtitle_style"), dict)
                    else None
                ),
            )
            final_url = str(
                subtitle_result.get("video_url")
                or subtitle_result.get("url")
                or raw_url
            )

        final_plan = {**plan, "clips": clips}
        _update_job(
            settings,
            job_id,
            status="done",
            stage="finished",
            progress=100,
            message=(
                f"现有视频智能剪辑完成：人工 {len(plan.get('manual_selected_assets') or [])} 条，"
                f"自动补充 {len(plan.get('auto_selected_assets') or [])} 条，"
                f"{len(clips)} 个片段，未调用 FAL"
            ),
            video_url=final_url,
            output_url=final_url,
            raw_video_url=raw_url,
            no_subtitle_video_url=raw_url,
            audio_url=audio_url,
            subtitled_video_url=final_url if subtitle_result else "",
            audio_duration_seconds=round(target, 3),
            duration_seconds=round(
                sum(float(item["duration"]) for item in clips), 3
            ),
            shot_count=len(clips),
            clips=clips,
            edit_plan=final_plan,
            coverage=final_plan.get("coverage"),
            manual_selected_assets=final_plan.get("manual_selected_assets"),
            auto_selected_assets=final_plan.get("auto_selected_assets"),
            timings=timings,
            subtitle_director=director_result.get("subtitle_report"),
            edit_director=director_result.get("edit_report"),
            director_report=director_result.get("report"),
            director_version=director_result.get("version"),
            keyword_bursts=director_result.get("keyword_bursts"),
            keyword_burst_report=director_result.get("keyword_burst_report"),
            edit_quality_gate=director_result.get("edit_quality_gate"),
            tts_warning=warning,
            fal_used=False,
            billing_guard="existing_edit_no_fal",
            finished_at=_now(),
        )
    except Exception as exc:
        _update_job(
            settings,
            job_id,
            status="failed",
            stage="failed",
            progress=100,
            error=str(exc)[:3000],
            message=f"现有视频剪辑失败：{exc}",
            fal_used=False,
            billing_guard="existing_edit_no_fal",
            finished_at=_now(),
        )
    finally:
        with _LOCK:
            _ACTIVE.discard(job_id)


def _thread(settings: Any, job_id: str, payload: dict[str, Any]) -> None:
    asyncio.run(_render(settings, job_id, payload))


def _start(settings: Any, payload: dict[str, Any]) -> dict[str, Any]:
    preliminary = build_edit_plan(
        payload,
        settings=settings,
    )
    resolved_material_mode = str(
        preliminary.get("material_selection_mode")
        or payload.get("material_selection_mode")
        or "auto"
    ).strip().lower()
    payload = {
        **payload,
        "material_selection_mode": resolved_material_mode,
        "edit_plan": preliminary,
        "auto_fill_assets": resolved_material_mode != "manual",
    }
    job_id = (
        f"existing_edit_{datetime.now().strftime('%Y%m%d_%H%M%S')}_"
        f"{uuid.uuid4().hex[:8]}"
    )
    job = {
        "job_id": job_id,
        "job_type": "existing_video_edit",
        "version": VERSION,
        "status": "queued",
        "stage": "queued",
        "progress": 0,
        "message": "等待 ECS 后端生成 TTS，并按真实时长自动补选素材",
        "mode": "existing_edit",
        "material_selection_mode": resolved_material_mode,
        "fal_used": False,
        "billing_guard": "existing_edit_no_fal",
        "edit_plan": preliminary,
        "coverage": preliminary.get("coverage"),
        "manual_selected_assets": preliminary.get("manual_selected_assets"),
        "auto_selected_assets": preliminary.get("auto_selected_assets"),
        "created_at": _now(),
        "updated_at": _now(),
    }
    with _LOCK:
        jobs = _load_jobs(settings)
        jobs[job_id] = job
        _save_jobs(settings, jobs)
        _ACTIVE.add(job_id)
    threading.Thread(
        target=_thread,
        args=(settings, job_id, dict(payload)),
        daemon=True,
        name=f"existing-edit-{job_id[-8:]}",
    ).start()
    return job


def _repair(settings: Any) -> None:
    jobs = _load_jobs(settings)
    changed = False
    for item in jobs.values():
        if str(item.get("status") or "") in {"queued", "running"}:
            item.update(
                status="failed",
                stage="recovered_after_restart",
                progress=100,
                error="后端重启导致剪辑中断，请重新发起；不会调用 FAL",
                finished_at=_now(),
                updated_at=_now(),
            )
            changed = True
    if changed:
        _save_jobs(settings, jobs)


def install_existing_video_editor(
    app: Any, get_settings: Callable[..., Any]
) -> None:
    global _INSTALLED
    if _INSTALLED or any(
        getattr(route, "path", "") == "/api/video/existing-edit/health"
        for route in getattr(app, "routes", [])
    ):
        _INSTALLED = True
        return

    _repair(get_settings())

    @app.get("/api/video/existing-edit/health")
    def health(settings: Any = Depends(get_settings)) -> dict[str, Any]:
        jobs = _load_jobs(settings)
        return {
            "ok": True,
            "version": VERSION,
            "mode": INSTALL_MARKER,
            "ffmpeg": bool(shutil.which("ffmpeg")),
            "ffprobe": bool(shutil.which("ffprobe")),
            "tts_provider": str(getattr(settings, "tts_provider", "")),
            "r2_enabled": bool(getattr(settings, "r2_enabled", False)),
            "fal_used": False,
            "running_jobs": sum(
                1
                for item in jobs.values()
                if item.get("status") in {"queued", "running"}
            ),
            "features": {
                "semantic_asset_match": True,
                "manual_asset_lock": True,
                "auto_fill_by_real_tts": True,
                "library_wide_autofill": True,
                "coverage_report": True,
                "video_clip_trim": True,
                "vertical_crop": True,
                "tts": True,
                "ambient_mix": True,
                "subtitle_burn": True,
                "ai_subtitle_director": True,
                "semantic_sentence_breaking": True,
                "tts_aligned_subtitle_cues": True,
                "dynamic_subtitle_font": True,
                "strong_keyword_emphasis": True,
                "ai_edit_director": True,
                "dynamic_edit_rhythm": True,
                "consecutive_asset_guard": True,
                "hard_cut_default": True,
                "word_level_timeline": True,
                "keyword_burst_layer": True,
                "keyword_burst_pop_animation": True,
                "keyword_burst_cut_sync": True,
                "semantic_role_match": True,
                "edit_quality_gate": True,
                "source_range_reuse_guard": True,
                "candidate_pool_merge": True,
                "forced_no_repeat": True,
                "single_asset_graceful_fallback": True,
                "adaptive_burst_cut_policy": True,
                "overlay_only_burst_fallback": True,
                "job_persistence": True,
                "fal_forbidden": True,
            },
        }

    @app.post("/api/video/existing-edit/plan")
    async def plan(
        request: Request, settings: Any = Depends(get_settings)
    ) -> dict[str, Any]:
        try:
            return build_edit_plan(await request.json(), settings=settings)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/video/existing-edit/start")
    async def start(
        request: Request, settings: Any = Depends(get_settings)
    ) -> dict[str, Any]:
        try:
            return _start(settings, await request.json())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/video/existing-edit/jobs/latest")
    def latest(
        done_only: bool = False, settings: Any = Depends(get_settings)
    ) -> dict[str, Any]:
        items = list(_load_jobs(settings).values())
        items = [
            item
            for item in items
            if not done_only or item.get("status") == "done"
        ]
        items.sort(
            key=lambda item: str(
                item.get("updated_at") or item.get("created_at") or ""
            ),
            reverse=True,
        )
        return {
            "ok": True,
            "version": VERSION,
            "job": items[0] if items else None,
        }

    @app.get("/api/video/existing-edit/jobs")
    def jobs(
        limit: int = 30, settings: Any = Depends(get_settings)
    ) -> dict[str, Any]:
        items = sorted(
            _load_jobs(settings).values(),
            key=lambda item: str(
                item.get("updated_at") or item.get("created_at") or ""
            ),
            reverse=True,
        )
        return {
            "ok": True,
            "version": VERSION,
            "jobs": items[: max(1, min(limit, 100))],
        }

    @app.get("/api/video/existing-edit/jobs/{job_id}")
    def job(
        job_id: str, settings: Any = Depends(get_settings)
    ) -> dict[str, Any]:
        item = _load_jobs(settings).get(job_id)
        if not item:
            raise HTTPException(status_code=404, detail="现有视频剪辑任务不存在")
        return item

    _INSTALLED = True
