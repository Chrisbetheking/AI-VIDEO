from __future__ import annotations

import json
import mimetypes
import os
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import requests


BASE_DIR = Path(os.getenv("AI_VIDEO_BACKEND_DIR", "/opt/ai-video/backend"))
SUBTITLE_DIR = BASE_DIR / "data" / "subtitles"
BURN_DIR = BASE_DIR / "data" / "subtitle-burns"
TEST_DIR = BASE_DIR / "data" / "subtitle-test"


def _ensure_dirs() -> None:
    SUBTITLE_DIR.mkdir(parents=True, exist_ok=True)
    BURN_DIR.mkdir(parents=True, exist_ok=True)
    TEST_DIR.mkdir(parents=True, exist_ok=True)


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def ffprobe_available() -> bool:
    return shutil.which("ffprobe") is not None


def _run(cmd: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
    )


def get_media_duration_seconds(path: str | Path, default: float = 12.0) -> float:
    if not ffprobe_available():
        return default

    try:
        proc = _run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            timeout=30,
        )
        if proc.returncode == 0:
            value = float((proc.stdout or "").strip())
            if value > 0:
                return value
    except Exception:
        pass

    return default


def _srt_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds or 0))
    ms = int(round((seconds - int(seconds)) * 1000))
    total = int(seconds)
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text


def split_text(text: str, max_chars: int = 18) -> list[str]:
    text = _clean_text(text)
    if not text:
        return []

    parts = re.split(r"([。！？!?；;，,、])", text)
    merged: list[str] = []
    buf = ""

    for item in parts:
        if not item:
            continue
        buf += item
        if item in "。！？!?；;，,、" or len(buf) >= max_chars:
            merged.append(buf.strip())
            buf = ""

    if buf.strip():
        merged.append(buf.strip())

    final: list[str] = []
    for part in merged:
        part = part.strip()
        if not part:
            continue
        if len(part) <= max_chars + 4:
            final.append(part)
        else:
            for i in range(0, len(part), max_chars):
                final.append(part[i:i + max_chars])

    return final


def _normalize_time(value: Any, fallback: Optional[float] = None) -> Optional[float]:
    if value is None:
        return fallback

    try:
        num = float(value)
    except Exception:
        return fallback

    if num > 1000:
        num = num / 1000.0

    return max(0.0, num)


def segments_to_cues(segments: list[dict[str, Any]], duration: float = 12.0) -> list[dict[str, Any]]:
    clean_segments = []

    for item in segments or []:
        if not isinstance(item, dict):
            continue

        text = (
            item.get("text")
            or item.get("copy")
            or item.get("content")
            or item.get("sentence")
            or item.get("line")
            or ""
        )
        text = _clean_text(text)
        if not text:
            continue

        start = _normalize_time(
            item.get("start")
            if item.get("start") is not None
            else item.get("start_time")
            if item.get("start_time") is not None
            else item.get("begin")
            if item.get("begin") is not None
            else item.get("from")
        )

        end = _normalize_time(
            item.get("end")
            if item.get("end") is not None
            else item.get("end_time")
            if item.get("end_time") is not None
            else item.get("stop")
            if item.get("stop") is not None
            else item.get("to")
        )

        clean_segments.append({"text": text, "start": start, "end": end})

    if not clean_segments:
        return []

    count = len(clean_segments)
    cursor = 0.0
    default_span = max(1.2, float(duration or 12.0) / max(count, 1))

    cues = []
    for idx, item in enumerate(clean_segments):
        start = item["start"]
        end = item["end"]

        if start is None:
            start = cursor

        if end is None or end <= start:
            end = start + default_span

        cursor = end

        cues.append(
            {
                "index": idx + 1,
                "start": float(start),
                "end": float(end),
                "text": item["text"],
            }
        )

    return cues


def text_to_cues(text: str, duration: float = 12.0, max_chars: int = 18) -> list[dict[str, Any]]:
    parts = split_text(text, max_chars=max_chars)
    if not parts:
        return []

    duration = max(2.0, float(duration or 12.0))
    gap = 0.06
    span = max(1.2, duration / len(parts))

    cues = []
    for idx, part in enumerate(parts):
        start = idx * span
        end = min(duration, start + span - gap)
        cues.append(
            {
                "index": idx + 1,
                "start": start,
                "end": max(start + 0.8, end),
                "text": part,
            }
        )

    return cues


def cues_to_srt(cues: list[dict[str, Any]]) -> str:
    blocks = []

    for idx, cue in enumerate(cues, start=1):
        start = _srt_time(float(cue.get("start", 0)))
        end = _srt_time(float(cue.get("end", 0)))
        text = _clean_text(str(cue.get("text", "")))
        blocks.append(f"{idx}\n{start} --> {end}\n{text}")

    return "\n\n".join(blocks).strip() + "\n"


def make_srt(
    text: str = "",
    segments: Optional[list[dict[str, Any]]] = None,
    duration: float = 12.0,
    max_chars: int = 18,
    prefix: str = "subtitle",
) -> dict[str, Any]:
    _ensure_dirs()

    cues = segments_to_cues(segments or [], duration=duration) if segments else []
    if not cues:
        cues = text_to_cues(text, duration=duration, max_chars=max_chars)

    if not cues:
        raise ValueError("没有可生成字幕的文本或 segments")

    srt_text = cues_to_srt(cues)
    safe_prefix = re.sub(r"[^a-zA-Z0-9_-]+", "_", prefix or "subtitle").strip("_") or "subtitle"
    filename = f"{safe_prefix}_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.srt"
    path = SUBTITLE_DIR / filename
    path.write_text(srt_text, encoding="utf-8")

    return {
        "ok": True,
        "cues": cues,
        "srt_text": srt_text,
        "srt_path": str(path),
        "filename": filename,
    }


def _download_to_tmp(url: str) -> Path:
    _ensure_dirs()

    parsed = urlparse(url)
    suffix = Path(parsed.path).suffix or ".mp4"
    target = TEST_DIR / f"input_{uuid.uuid4().hex[:12]}{suffix}"

    with requests.get(url, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        with target.open("wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)

    return target


def _ffmpeg_subtitle_path(path: Path) -> str:
    value = str(path)
    value = value.replace("\\", "\\\\")
    value = value.replace(":", "\\:")
    value = value.replace("'", "\\'")
    return value


def burn_subtitles(
    video_url: str = "",
    video_path: str = "",
    text: str = "",
    segments: Optional[list[dict[str, Any]]] = None,
    duration: Optional[float] = None,
    max_chars: int = 18,
    prefix: str = "subtitle_burn",
) -> dict[str, Any]:
    _ensure_dirs()

    if not ffmpeg_available():
        raise RuntimeError("ffmpeg 不可用，无法烧录字幕")

    if video_url:
        input_path = _download_to_tmp(video_url)
    elif video_path:
        input_path = Path(video_path)
    else:
        raise ValueError("必须提供 video_url 或 video_path")

    if not input_path.exists():
        raise FileNotFoundError(f"视频文件不存在: {input_path}")

    media_duration = float(duration or get_media_duration_seconds(input_path, default=12.0))
    srt_result = make_srt(
        text=text,
        segments=segments,
        duration=media_duration,
        max_chars=max_chars,
        prefix=prefix,
    )

    safe_prefix = re.sub(r"[^a-zA-Z0-9_-]+", "_", prefix or "subtitle_burn").strip("_") or "subtitle_burn"
    output_path = BURN_DIR / f"{safe_prefix}_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.mp4"

    srt_path = Path(srt_result["srt_path"])
    subtitle_filter = (
        f"subtitles='{_ffmpeg_subtitle_path(srt_path)}':"
        "force_style='FontName=Noto Sans CJK SC,FontSize=18,Alignment=2,"
        "MarginV=120,Outline=2,Shadow=1,BorderStyle=1'"
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(input_path),
        "-vf",
        subtitle_filter,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-c:a",
        "copy",
        str(output_path),
    ]

    proc = _run(cmd, timeout=600)

    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or "ffmpeg subtitle burn failed")

    return {
        "ok": True,
        "input_path": str(input_path),
        "output_path": str(output_path),
        "srt_path": str(srt_path),
        "duration": media_duration,
        "srt_text": srt_result["srt_text"],
        "cues": srt_result["cues"],
    }


def create_self_test_video() -> Path:
    _ensure_dirs()

    if not ffmpeg_available():
        raise RuntimeError("ffmpeg 不可用，无法创建测试视频")

    output = TEST_DIR / f"subtitle_self_test_{uuid.uuid4().hex[:8]}.mp4"

    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "color=c=black:s=720x1280:d=5",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-shortest",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        str(output),
    ]

    proc = _run(cmd, timeout=120)

    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or "ffmpeg self test video failed")

    return output


def health() -> dict[str, Any]:
    _ensure_dirs()

    return {
        "ok": True,
        "ffmpeg": ffmpeg_available(),
        "ffprobe": ffprobe_available(),
        "subtitle_dir": str(SUBTITLE_DIR),
        "burn_dir": str(BURN_DIR),
    }
