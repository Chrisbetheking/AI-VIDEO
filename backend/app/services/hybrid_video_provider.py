from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from app.services.subtitle_provider import burn_subtitles, upload_file_to_r2


BASE_DIR = Path(os.getenv("AI_VIDEO_BACKEND_DIR", "/opt/ai-video/backend"))
HYBRID_DIR = BASE_DIR / "data" / "hybrid"
INPUT_DIR = HYBRID_DIR / "inputs"
OUTPUT_DIR = HYBRID_DIR / "outputs"
TEST_DIR = HYBRID_DIR / "test"


def _ensure_dirs() -> None:
    for d in (INPUT_DIR, OUTPUT_DIR, TEST_DIR):
        d.mkdir(parents=True, exist_ok=True)


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def ffprobe_available() -> bool:
    return shutil.which("ffprobe") is not None


def _run(cmd: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
    )


def make_job_id(prefix: str = "hybrid") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:18]}"


def probe_video(path: str | Path) -> dict[str, Any]:
    p = Path(path)

    meta: dict[str, Any] = {
        "path": str(p),
        "filename": p.name,
        "exists": p.exists(),
    }

    if p.exists():
        meta["size"] = p.stat().st_size

    if not p.exists() or not ffprobe_available():
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
        meta["ffprobe"] = False
        meta["ffprobe_error"] = proc.stderr
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


def download_video(video_url: str, prefix: str = "hybrid") -> Path:
    _ensure_dirs()

    parsed = urlparse(video_url)
    suffix = Path(parsed.path).suffix or ".mp4"
    target = INPUT_DIR / f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:10]}{suffix}"

    with requests.get(video_url, stream=True, timeout=180) as resp:
        resp.raise_for_status()
        with target.open("wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)

    return target


def create_test_video(label: str = "clip", color: str = "blue", duration: float = 3.0) -> Path:
    _ensure_dirs()

    if not ffmpeg_available():
        raise RuntimeError("ffmpeg 不可用，无法创建混合成片测试视频")

    output = TEST_DIR / f"hybrid_{label}_{uuid.uuid4().hex[:8]}.mp4"

    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"color=c={color}:s=720x1280:d={float(duration)}",
        "-vf",
        f"drawtext=text='{label}':fontcolor=white:fontsize=48:x=(w-text_w)/2:y=(h-text_h)/2",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-an",
        str(output),
    ]

    proc = _run(cmd, timeout=120)

    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or "ffmpeg hybrid test video failed")

    return output


def _prepare_clip(path: str = "", url: str = "", prefix: str = "hybrid") -> Path:
    if url:
        return download_video(url, prefix=prefix)

    if path:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"视频文件不存在: {p}")
        return p

    raise ValueError("clip 缺少 path 或 url")


def _normalize_clip(input_path: Path, index: int) -> Path:
    _ensure_dirs()

    output = OUTPUT_DIR / f"normalized_{index:02d}_{uuid.uuid4().hex[:8]}.mp4"

    vf = "scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=24"

    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(input_path),
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-an",
        str(output),
    ]

    proc = _run(cmd, timeout=600)

    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or f"normalize clip failed: {input_path}")

    return output


def _concat_clips(paths: list[Path], prefix: str = "hybrid") -> Path:
    _ensure_dirs()

    if not paths:
        raise ValueError("没有可拼接的视频片段")

    list_path = OUTPUT_DIR / f"concat_{uuid.uuid4().hex[:8]}.txt"
    output = OUTPUT_DIR / f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.mp4"

    with list_path.open("w", encoding="utf-8") as f:
        for p in paths:
            escaped = str(p).replace("'", "'\\''")
            f.write(f"file '{escaped}'\n")

    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_path),
        "-c",
        "copy",
        str(output),
    ]

    proc = _run(cmd, timeout=600)

    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or "concat clips failed")

    return output


def process_hybrid_video(
    real_video_path: str = "",
    real_video_url: str = "",
    ai_video_paths: list[str] | None = None,
    ai_video_urls: list[str] | None = None,
    order: str = "ai_first",
    text: str = "",
    burn_subtitle: bool = False,
    upload_r2: bool = False,
    dry_run: bool = True,
    max_chars: int = 18,
    prefix: str = "hybrid",
) -> dict[str, Any]:
    _ensure_dirs()

    ai_video_paths = ai_video_paths or []
    ai_video_urls = ai_video_urls or []
    job_id = make_job_id("hybrid")

    real_clip = _prepare_clip(real_video_path, real_video_url, prefix="real")
    ai_clips = []

    for idx, p in enumerate(ai_video_paths):
        if p:
            ai_clips.append(_prepare_clip(path=p, prefix=f"ai_path_{idx}"))

    for idx, u in enumerate(ai_video_urls):
        if u:
            ai_clips.append(_prepare_clip(url=u, prefix=f"ai_url_{idx}"))

    if not ai_clips:
        clips = [real_clip]
    elif order == "real_first":
        clips = [real_clip] + ai_clips
    else:
        clips = ai_clips + [real_clip]

    metadata = [probe_video(p) for p in clips]

    plan = {
        "clips_count": len(clips),
        "ai_clips_count": len(ai_clips),
        "order": order,
        "burn_subtitle": bool(burn_subtitle),
        "upload_r2": bool(upload_r2),
        "has_text": bool((text or "").strip()),
        "max_chars": max_chars,
        "note": "混合成片只拼接已有视频，不调用 fal.ai。",
    }

    if dry_run:
        return {
            "ok": True,
            "job_id": job_id,
            "type": "hybrid",
            "status": "planned",
            "stage": "dry_run",
            "message": "混合成片 dry_run 通过：已读取素材信息，未拼接，未上传 R2，未调用 fal.ai。",
            "clips": [str(p) for p in clips],
            "metadata": metadata,
            "plan": plan,
        }

    normalized = [_normalize_clip(p, idx + 1) for idx, p in enumerate(clips)]
    output_path = _concat_clips(normalized, prefix=prefix or "hybrid")

    result: dict[str, Any] = {
        "output_path": str(output_path),
        "normalized_clips": [str(p) for p in normalized],
    }

    final_path = output_path
    final_url = str(output_path)

    if burn_subtitle:
        if not text.strip():
            raise ValueError("burn_subtitle=true 时必须提供 text")
        burned = burn_subtitles(
            video_path=str(output_path),
            text=text,
            max_chars=max_chars,
            prefix=prefix or "hybrid",
        )
        result["subtitle_burn"] = burned
        final_path = Path(burned["output_path"])
        final_url = str(final_path)

    if upload_r2:
        uploaded = upload_file_to_r2(final_path)
        result["r2"] = uploaded
        final_url = uploaded["url"]

    return {
        "ok": True,
        "job_id": job_id,
        "type": "hybrid",
        "status": "done",
        "stage": "finished",
        "message": "混合成片完成，未调用 fal.ai。",
        "video_path": str(final_path),
        "video_url": final_url,
        "clips": [str(p) for p in clips],
        "metadata": metadata,
        "plan": plan,
        "result": result,
    }


def health() -> dict[str, Any]:
    _ensure_dirs()

    return {
        "ok": True,
        "provider": "hybrid",
        "ffmpeg": ffmpeg_available(),
        "ffprobe": ffprobe_available(),
        "output_dir": str(OUTPUT_DIR),
        "message": "混合成片服务可用，只处理已有素材，不调用 fal.ai。",
    }
