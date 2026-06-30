from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from PIL import Image, ImageStat


BASE_DIR = Path(os.getenv("AI_VIDEO_BACKEND_DIR", "/opt/ai-video/backend"))
WATERMARK_DIR = BASE_DIR / "data" / "watermark-check"
FRAME_DIR = WATERMARK_DIR / "frames"
SHEET_DIR = WATERMARK_DIR / "sheets"
DOWNLOAD_DIR = WATERMARK_DIR / "downloads"
TEST_DIR = WATERMARK_DIR / "test"


def _ensure_dirs() -> None:
    for d in (WATERMARK_DIR, FRAME_DIR, SHEET_DIR, DOWNLOAD_DIR, TEST_DIR):
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


def make_job_id(prefix: str = "watermark") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:18]}"


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

    try:
        duration = float(fmt.get("duration") or 0)
    except Exception:
        duration = 0.0

    meta.update(
        {
            "ffprobe": True,
            "duration": duration,
            "width": video_stream.get("width"),
            "height": video_stream.get("height"),
            "video_codec": video_stream.get("codec_name"),
            "frame_rate": video_stream.get("r_frame_rate"),
        }
    )

    return meta


def extract_frames(video_path: Path, job_id: str, sample_count: int = 6) -> list[Path]:
    _ensure_dirs()

    meta = probe_video(video_path)
    duration = float(meta.get("duration") or 0)

    if duration <= 0:
        times = [0]
    else:
        sample_count = max(1, min(int(sample_count or 6), 12))
        times = [(duration * (i + 1)) / (sample_count + 1) for i in range(sample_count)]

    out_dir = FRAME_DIR / job_id
    out_dir.mkdir(parents=True, exist_ok=True)

    frames: list[Path] = []

    for idx, t in enumerate(times, start=1):
        out = out_dir / f"frame_{idx:02d}.jpg"

        cmd = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{t:.3f}",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-q:v",
            "3",
            str(out),
        ]

        proc = _run(cmd, timeout=120)

        if proc.returncode == 0 and out.exists():
            frames.append(out)

    return frames


def _region_stats(img: Image.Image, box: tuple[int, int, int, int]) -> dict[str, Any]:
    region = img.crop(box).convert("L")
    region = region.resize((120, 80))

    stat = ImageStat.Stat(region)
    mean = float(stat.mean[0])
    std = float(stat.stddev[0])

    px = region.load()
    w, h = region.size

    diff_total = 0
    diff_count = 0
    extreme = 0
    total = w * h

    for y in range(0, h, 2):
        for x in range(0, w, 2):
            v = px[x, y]

            if v < 25 or v > 230:
                extreme += 1

            if x + 2 < w:
                diff_total += abs(v - px[x + 2, y])
                diff_count += 1

            if y + 2 < h:
                diff_total += abs(v - px[x, y + 2])
                diff_count += 1

    edge = diff_total / max(1, diff_count)
    extreme_ratio = extreme / max(1, total / 4)

    score = round((std / 55.0) + (edge / 32.0) + (extreme_ratio * 1.6), 3)

    return {
        "mean": round(mean, 2),
        "std": round(std, 2),
        "edge": round(edge, 2),
        "extreme_ratio": round(extreme_ratio, 4),
        "score": score,
    }


def analyze_frame(frame_path: Path) -> dict[str, Any]:
    img = Image.open(frame_path).convert("RGB")
    w, h = img.size

    cw = max(80, int(w * 0.24))
    ch = max(80, int(h * 0.16))

    boxes = {
        "top_left": (0, 0, cw, ch),
        "top_right": (w - cw, 0, w, ch),
        "bottom_left": (0, h - ch, cw, h),
        "bottom_right": (w - cw, h - ch, w, h),
    }

    regions = {name: _region_stats(img, box) for name, box in boxes.items()}

    return {
        "frame": str(frame_path),
        "width": w,
        "height": h,
        "regions": regions,
    }


def aggregate_risk(frame_results: list[dict[str, Any]]) -> dict[str, Any]:
    region_names = ["top_left", "top_right", "bottom_left", "bottom_right"]

    agg: dict[str, Any] = {}

    for name in region_names:
        scores = [
            float(item.get("regions", {}).get(name, {}).get("score", 0))
            for item in frame_results
        ]
        avg = sum(scores) / max(1, len(scores))
        max_score = max(scores) if scores else 0

        agg[name] = {
            "avg_score": round(avg, 3),
            "max_score": round(max_score, 3),
            "suspected": avg >= 1.35 or max_score >= 1.75,
        }

    suspected = [k for k, v in agg.items() if v["suspected"]]

    max_avg = max([v["avg_score"] for v in agg.values()] or [0])

    if suspected and max_avg >= 1.65:
        risk = "high"
    elif suspected:
        risk = "medium"
    else:
        risk = "low"

    return {
        "risk_level": risk,
        "suspected_regions": suspected,
        "region_scores": agg,
        "note": "这是基于角落高对比/边缘复杂度的启发式水印风险检测，不等于 OCR 或人工审核。",
    }


def create_contact_sheet(frames: list[Path], job_id: str) -> str:
    _ensure_dirs()

    if not frames:
        return ""

    thumbs = []

    for f in frames:
        img = Image.open(f).convert("RGB")
        img.thumbnail((240, 426))
        canvas = Image.new("RGB", (240, 426), (18, 18, 18))
        x = (240 - img.width) // 2
        y = (426 - img.height) // 2
        canvas.paste(img, (x, y))
        thumbs.append(canvas)

    cols = min(3, len(thumbs))
    rows = math.ceil(len(thumbs) / cols)

    sheet = Image.new("RGB", (cols * 240, rows * 426), (10, 10, 10))

    for idx, img in enumerate(thumbs):
        x = (idx % cols) * 240
        y = (idx // cols) * 426
        sheet.paste(img, (x, y))

    out = SHEET_DIR / f"{job_id}_contact_sheet.jpg"
    sheet.save(out, quality=88)

    return str(out)


def check_watermark(
    video_path: str = "",
    video_url: str = "",
    sample_count: int = 6,
    prefix: str = "watermark",
) -> dict[str, Any]:
    _ensure_dirs()

    if not ffmpeg_available():
        raise RuntimeError("ffmpeg 不可用，无法抽帧")

    job_id = make_job_id(prefix or "watermark")

    if video_url:
        source = download_video(video_url)
        source_type = "url"
    elif video_path:
        source = Path(video_path)
        source_type = "path"
    else:
        raise ValueError("必须提供 video_path 或 video_url")

    if not source.exists():
        raise FileNotFoundError(f"视频文件不存在: {source}")

    metadata = probe_video(source)
    frames = extract_frames(source, job_id=job_id, sample_count=sample_count)

    frame_results = [analyze_frame(f) for f in frames]
    risk = aggregate_risk(frame_results)
    contact_sheet = create_contact_sheet(frames, job_id)

    return {
        "ok": True,
        "job_id": job_id,
        "type": "watermark_check",
        "status": "done",
        "stage": "analyzed",
        "message": "水印 / Logo 抽帧检测完成，未调用 fal.ai，未上传 R2。",
        "source_type": source_type,
        "video_path": str(source),
        "metadata": metadata,
        "sample_count": len(frames),
        "frames": [str(f) for f in frames],
        "contact_sheet": contact_sheet,
        "risk": risk,
    }


def create_self_test_video(with_logo: bool = True) -> Path:
    _ensure_dirs()

    if not ffmpeg_available():
        raise RuntimeError("ffmpeg 不可用，无法创建测试视频")

    out = TEST_DIR / f"watermark_self_test_{uuid.uuid4().hex[:8]}.mp4"

    vf = "testsrc2=s=720x1280:rate=24:d=4"

    if with_logo:
        draw = "drawtext=text='LOGO':x=w-tw-24:y=24:fontsize=52:fontcolor=white:box=1:boxcolor=black@0.55"
        vf = f"{vf},{draw}"

    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        vf,
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
        str(out),
    ]

    proc = _run(cmd, timeout=120)

    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or "watermark self-test video failed")

    return out


def health() -> dict[str, Any]:
    _ensure_dirs()

    return {
        "ok": True,
        "provider": "watermark_check",
        "ffmpeg": ffmpeg_available(),
        "ffprobe": ffprobe_available(),
        "watermark_dir": str(WATERMARK_DIR),
        "message": "水印 / Logo 抽帧检测服务可用，不调用 fal.ai。",
    }
