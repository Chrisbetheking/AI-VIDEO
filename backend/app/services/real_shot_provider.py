from __future__ import annotations

import json
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

from app.services.subtitle_provider import (
    burn_subtitles,
    burn_subtitles_and_upload,
)


BASE_DIR = Path(os.getenv("AI_VIDEO_BACKEND_DIR", "/opt/ai-video/backend"))
REAL_SHOT_DIR = BASE_DIR / "data" / "real-shot"
UPLOAD_DIR = REAL_SHOT_DIR / "uploads"
DOWNLOAD_DIR = REAL_SHOT_DIR / "downloads"
PROCESSED_DIR = REAL_SHOT_DIR / "processed"
TEST_DIR = REAL_SHOT_DIR / "test"


def _ensure_dirs() -> None:
    for d in (UPLOAD_DIR, DOWNLOAD_DIR, PROCESSED_DIR, TEST_DIR):
        d.mkdir(parents=True, exist_ok=True)


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


def make_job_id(prefix: str = "real_shot") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:18]}"


def sanitize_filename(name: str) -> str:
    raw = Path(name or "upload.mp4").name
    raw = re.sub(r"[^a-zA-Z0-9._-]+", "_", raw).strip("._")
    return raw or "upload.mp4"


def unique_path(directory: Path, filename: str) -> Path:
    _ensure_dirs()
    safe = sanitize_filename(filename)
    stem = Path(safe).stem or "video"
    suffix = Path(safe).suffix or ".mp4"
    return directory / f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}_{stem}{suffix}"


def probe_video(path: str | Path) -> dict[str, Any]:
    p = Path(path)

    if not p.exists():
        raise FileNotFoundError(f"视频文件不存在: {p}")

    meta: dict[str, Any] = {
        "path": str(p),
        "filename": p.name,
        "size": p.stat().st_size,
        "exists": True,
    }

    if not ffprobe_available():
        meta.update({"ffprobe": False})
        return meta

    proc = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration,size,bit_rate:stream=index,codec_type,codec_name,width,height,r_frame_rate",
            "-of",
            "json",
            str(p),
        ],
        timeout=60,
    )

    if proc.returncode != 0:
        meta.update(
            {
                "ffprobe": False,
                "ffprobe_error": proc.stderr,
            }
        )
        return meta

    try:
        data = json.loads(proc.stdout or "{}")
    except Exception:
        data = {}

    fmt = data.get("format") or {}
    streams = data.get("streams") or []

    video_stream = next((s for s in streams if s.get("codec_type") == "video"), {}) or {}
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), {}) or {}

    try:
        duration = float(fmt.get("duration") or 0)
    except Exception:
        duration = 0.0

    meta.update(
        {
            "ffprobe": True,
            "duration": duration,
            "bit_rate": fmt.get("bit_rate"),
            "width": video_stream.get("width"),
            "height": video_stream.get("height"),
            "video_codec": video_stream.get("codec_name"),
            "audio_codec": audio_stream.get("codec_name"),
            "frame_rate": video_stream.get("r_frame_rate"),
            "has_audio": bool(audio_stream),
        }
    )

    return meta


def download_video(video_url: str) -> Path:
    _ensure_dirs()

    parsed = urlparse(video_url)
    suffix = Path(parsed.path).suffix or ".mp4"
    target = DOWNLOAD_DIR / f"download_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:10]}{suffix}"

    with requests.get(video_url, stream=True, timeout=180) as resp:
        resp.raise_for_status()
        with target.open("wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)

    return target


def create_self_test_video() -> Path:
    _ensure_dirs()

    if not ffmpeg_available():
        raise RuntimeError("ffmpeg 不可用，无法创建实拍测试视频")

    output = TEST_DIR / f"real_shot_self_test_{uuid.uuid4().hex[:8]}.mp4"

    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=s=720x1280:rate=24:d=4",
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
        raise RuntimeError(proc.stderr or "ffmpeg real-shot self test video failed")

    return output


def process_real_shot(
    video_path: str = "",
    video_url: str = "",
    text: str = "",
    segments: Optional[list[dict[str, Any]]] = None,
    burn_subtitle: bool = False,
    upload_r2: bool = False,
    dry_run: bool = True,
    max_chars: int = 18,
    prefix: str = "real_shot",
) -> dict[str, Any]:
    _ensure_dirs()

    job_id = make_job_id("real_shot")

    if video_url:
        source_path = download_video(video_url)
        source_type = "url"
    elif video_path:
        source_path = Path(video_path)
        source_type = "path"
    else:
        raise ValueError("必须提供 video_path 或 video_url")

    metadata = probe_video(source_path)

    plan = {
        "burn_subtitle": bool(burn_subtitle),
        "upload_r2": bool(upload_r2),
        "has_text": bool((text or "").strip()),
        "segments_count": len(segments or []),
        "max_chars": max_chars,
    }

    if dry_run:
        return {
            "ok": True,
            "job_id": job_id,
            "type": "real_shot",
            "status": "planned",
            "stage": "dry_run",
            "message": "实拍视频 dry_run 通过：已读取视频信息，未烧字幕，未上传 R2，未调用 fal.ai。",
            "source_type": source_type,
            "video_path": str(source_path),
            "metadata": metadata,
            "plan": plan,
        }

    result: dict[str, Any] = {}

    if burn_subtitle:
        if not text and not segments:
            raise ValueError("burn_subtitle=true 时必须提供 text 或 segments")

        if upload_r2:
            result = burn_subtitles_and_upload(
                video_path=str(source_path),
                text=text,
                segments=segments,
                max_chars=max_chars,
                prefix=prefix or "real_shot",
            )
            video_url_out = result.get("video_url") or result.get("url") or ""
        else:
            result = burn_subtitles(
                video_path=str(source_path),
                text=text,
                segments=segments,
                max_chars=max_chars,
                prefix=prefix or "real_shot",
            )
            video_url_out = result.get("output_path") or ""
    else:
        video_url_out = str(source_path)

    return {
        "ok": True,
        "job_id": job_id,
        "type": "real_shot",
        "status": "done",
        "stage": "processed",
        "message": "实拍视频处理完成，未调用 fal.ai。",
        "source_type": source_type,
        "video_path": str(source_path),
        "video_url": video_url_out,
        "metadata": metadata,
        "plan": plan,
        "result": result,
    }


def health() -> dict[str, Any]:
    _ensure_dirs()

    return {
        "ok": True,
        "provider": "real_shot",
        "ffmpeg": ffmpeg_available(),
        "ffprobe": ffprobe_available(),
        "upload_dir": str(UPLOAD_DIR),
        "processed_dir": str(PROCESSED_DIR),
        "message": "实拍视频处理服务可用，不调用 fal.ai。",
    }
