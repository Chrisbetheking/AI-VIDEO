from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.services.assets_store import now_iso, upsert_asset
from app.services.memory import MemoryStore
from app.services.storage import public_r2_url

try:
    from PIL import Image, ImageChops, ImageFilter
except Exception:  # pragma: no cover - health endpoint reports this
    Image = None  # type: ignore[assignment]
    ImageChops = None  # type: ignore[assignment]
    ImageFilter = None  # type: ignore[assignment]

VERSION = "10.40.8.9-r2-smart-vertical-reframe"
ROUTER_PREFIX = "/api/assets/r2-reframe"
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi"}
DEFAULT_OUTPUT_PREFIX = "vertical-9x16"
DEFAULT_SOURCE_PREFIX = "uploads"
TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920
TARGET_RATIO = TARGET_WIDTH / TARGET_HEIGHT

router = APIRouter(prefix=ROUTER_PREFIX, tags=["R2 Smart Vertical Reframe"])
_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="r2-vertical-reframe")
_STATE_LOCK = threading.RLock()
_RUNNING_JOB_ID: str | None = None
_CANCELLED: set[str] = set()


class ScanRequest(BaseModel):
    prefix: str = DEFAULT_SOURCE_PREFIX
    limit: int = Field(default=500, ge=1, le=2000)
    only_landscape: bool = True


class ReframeJobRequest(BaseModel):
    object_keys: list[str] = Field(default_factory=list, min_length=1, max_length=500)
    output_prefix: str = DEFAULT_OUTPUT_PREFIX
    mode: Literal["smart_crop", "center_crop", "fit_blur"] = "smart_crop"
    force: bool = False
    skip_non_landscape: bool = True
    register_assets: bool = True
    delete_local_after_upload: bool = True
    sample_count: int = Field(default=12, ge=4, le=24)
    max_input_mb: int = Field(default=1200, ge=20, le=5000)
    reserve_free_mb: int = Field(default=1536, ge=512, le=8192)
    crf: int = Field(default=21, ge=16, le=30)
    preset: Literal["ultrafast", "superfast", "veryfast", "faster", "fast", "medium"] = "veryfast"


@dataclass
class VideoProbe:
    width: int
    height: int
    duration: float
    fps: float
    has_audio: bool
    rotation: int

    @property
    def display_width(self) -> int:
        return self.height if abs(self.rotation) in {90, 270} else self.width

    @property
    def display_height(self) -> int:
        return self.width if abs(self.rotation) in {90, 270} else self.height

    @property
    def ratio(self) -> float:
        return self.display_width / max(1, self.display_height)


# ------------------------------ persistence ------------------------------

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_api_token(request: Request) -> None:
    # Local server maintenance commands may call the API over loopback without
    # copying a production token into terminal history. Browser/external calls
    # must use the same token header contract as the existing API Guard.
    host = request.client.host if request.client else ""
    if host in {"127.0.0.1", "::1", "localhost"}:
        return
    expected = os.getenv("AI_VIDEO_API_TOKEN", "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="后端未配置 AI_VIDEO_API_TOKEN")
    supplied = (request.headers.get("x-ai-video-token") or "").strip()
    if not supplied:
        authorization = (request.headers.get("authorization") or "").strip()
        if authorization.lower().startswith("bearer "):
            supplied = authorization[7:].strip()
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="该接口需要 X-AI-Video-Token 或 Bearer Token")


def _job_file(settings: Settings) -> Path:
    path = settings.data_dir / "r2-smart-vertical-reframe" / "jobs.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load_jobs(settings: Settings) -> dict[str, dict[str, Any]]:
    path = _job_file(settings)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_jobs(settings: Settings, jobs: dict[str, dict[str, Any]]) -> None:
    path = _job_file(settings)
    tmp = path.with_suffix(".tmp")
    # Keep the newest 100 jobs only.
    ordered = sorted(jobs.items(), key=lambda item: item[1].get("created_at", ""), reverse=True)[:100]
    tmp.write_text(json.dumps(dict(ordered), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _update_job(settings: Settings, job_id: str, **updates: Any) -> dict[str, Any]:
    with _STATE_LOCK:
        jobs = _load_jobs(settings)
        current = jobs.get(job_id, {"id": job_id})
        current.update(updates)
        current["updated_at"] = _utc_now()
        jobs[job_id] = current
        _save_jobs(settings, jobs)
        return current


def _get_job(settings: Settings, job_id: str) -> dict[str, Any] | None:
    with _STATE_LOCK:
        return _load_jobs(settings).get(job_id)


# ------------------------------ R2 helpers ------------------------------

def _r2_client(settings: Settings):
    import boto3  # type: ignore
    from botocore.config import Config  # type: ignore

    endpoint = f"https://{settings.r2_account_id}.r2.cloudflarestorage.com"
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        region_name="auto",
        config=Config(
            connect_timeout=15,
            read_timeout=300,
            retries={"max_attempts": 5, "mode": "adaptive"},
            signature_version="s3v4",
        ),
    )


def _normalize_key(key: str) -> str:
    key = (key or "").strip().lstrip("/")
    if not key or ".." in Path(key).parts:
        raise ValueError("非法 R2 object_key")
    return key


def _normalize_prefix(prefix: str) -> str:
    return (prefix or "").strip().strip("/")


def _safe_filename_from_key(key: str) -> str:
    name = Path(key).name
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in name)
    return safe[:180] or "source.mp4"


def _list_r2_objects(settings: Settings, prefix: str, limit: int) -> list[dict[str, Any]]:
    client = _r2_client(settings)
    normalized = _normalize_prefix(prefix)
    prefix_value = f"{normalized}/" if normalized else ""
    items: list[dict[str, Any]] = []
    token: str | None = None
    while len(items) < limit:
        kwargs: dict[str, Any] = {
            "Bucket": settings.r2_bucket_name,
            "Prefix": prefix_value,
            "MaxKeys": min(1000, limit - len(items)),
        }
        if token:
            kwargs["ContinuationToken"] = token
        response = client.list_objects_v2(**kwargs)
        for obj in response.get("Contents", []) or []:
            key = str(obj.get("Key") or "")
            if not key or key.endswith("/") or Path(key).suffix.lower() not in VIDEO_EXTENSIONS:
                continue
            items.append(
                {
                    "key": key,
                    "name": Path(key).name,
                    "size_bytes": int(obj.get("Size") or 0),
                    "etag": str(obj.get("ETag") or "").strip('"'),
                    "last_modified": obj.get("LastModified").isoformat() if obj.get("LastModified") else "",
                    "url": public_r2_url(settings, key),
                }
            )
            if len(items) >= limit:
                break
        if not response.get("IsTruncated") or len(items) >= limit:
            break
        token = response.get("NextContinuationToken")
    return items


def _head_object(settings: Settings, key: str) -> dict[str, Any]:
    response = _r2_client(settings).head_object(Bucket=settings.r2_bucket_name, Key=key)
    return {
        "content_length": int(response.get("ContentLength") or 0),
        "content_type": str(response.get("ContentType") or ""),
        "etag": str(response.get("ETag") or "").strip('"'),
        "metadata": response.get("Metadata") or {},
    }


def _object_exists(settings: Settings, key: str) -> bool:
    try:
        _r2_client(settings).head_object(Bucket=settings.r2_bucket_name, Key=key)
        return True
    except Exception:
        return False


def _download_object(settings: Settings, key: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    _r2_client(settings).download_file(settings.r2_bucket_name, key, str(destination))


def _upload_object(settings: Settings, source: Path, key: str, metadata: dict[str, str]) -> str:
    _r2_client(settings).upload_file(
        str(source),
        settings.r2_bucket_name,
        key,
        ExtraArgs={
            "ContentType": "video/mp4",
            "Metadata": {str(k): str(v)[:1024] for k, v in metadata.items()},
            "CacheControl": "public, max-age=31536000, immutable",
        },
    )
    return public_r2_url(settings, key)


# ------------------------------ ffmpeg / focus analysis ------------------------------

def _run(command: list[str], *, timeout: int = 7200) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
    )


def _parse_fps(value: str) -> float:
    try:
        numerator, denominator = value.split("/", 1)
        return float(numerator) / max(1.0, float(denominator))
    except Exception:
        try:
            return float(value)
        except Exception:
            return 30.0


def _probe_video(path: Path) -> VideoProbe:
    result = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ],
        timeout=60,
    )
    payload = json.loads(result.stdout)
    streams = payload.get("streams") or []
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    if not video_stream:
        raise RuntimeError("文件中没有视频流")
    rotation = 0
    tags = video_stream.get("tags") or {}
    if str(tags.get("rotate") or "").lstrip("-").isdigit():
        rotation = int(tags["rotate"]) % 360
    for side in video_stream.get("side_data_list") or []:
        if side.get("rotation") is not None:
            rotation = int(side.get("rotation") or 0) % 360
    duration = float(video_stream.get("duration") or (payload.get("format") or {}).get("duration") or 0.0)
    return VideoProbe(
        width=int(video_stream.get("width") or 0),
        height=int(video_stream.get("height") or 0),
        duration=max(0.01, duration),
        fps=max(1.0, min(120.0, _parse_fps(str(video_stream.get("avg_frame_rate") or "30/1")))),
        has_audio=any(s.get("codec_type") == "audio" for s in streams),
        rotation=rotation,
    )


def _sample_times(duration: float, count: int) -> list[float]:
    if duration <= 0.5:
        return [0.0]
    count = max(4, min(count, 24))
    start = min(0.25, duration * 0.05)
    end = max(start, duration - min(0.25, duration * 0.05))
    if count == 1:
        return [(start + end) / 2]
    return [start + (end - start) * i / (count - 1) for i in range(count)]


def _extract_sample_frames(source: Path, probe: VideoProbe, frame_dir: Path, count: int) -> list[tuple[float, Path]]:
    frame_dir.mkdir(parents=True, exist_ok=True)
    output: list[tuple[float, Path]] = []
    for index, timestamp in enumerate(_sample_times(probe.duration, count)):
        target = frame_dir / f"frame_{index:03d}.jpg"
        try:
            _run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-ss",
                    f"{timestamp:.3f}",
                    "-i",
                    str(source),
                    "-frames:v",
                    "1",
                    "-vf",
                    "scale=320:-2:flags=fast_bilinear",
                    "-q:v",
                    "3",
                    "-y",
                    str(target),
                ],
                timeout=90,
            )
            if target.exists() and target.stat().st_size > 512:
                output.append((timestamp, target))
        except Exception:
            continue
    return output


def _column_scores(image, previous=None) -> list[float]:
    gray = image.convert("L")
    edges = gray.filter(ImageFilter.FIND_EDGES)
    width, height = gray.size
    edge_pixels = edges.load()
    diff_pixels = None
    if previous is not None:
        try:
            diff = ImageChops.difference(gray, previous.convert("L"))
            diff_pixels = diff.load()
        except Exception:
            diff_pixels = None
    scores: list[float] = []
    center = (width - 1) / 2.0
    for x in range(width):
        edge_sum = 0.0
        motion_sum = 0.0
        for y in range(height):
            edge_sum += float(edge_pixels[x, y])
            if diff_pixels is not None:
                motion_sum += float(diff_pixels[x, y])
        center_bias = 1.0 - min(1.0, abs(x - center) / max(1.0, center))
        scores.append(edge_sum + motion_sum * 0.55 + center_bias * height * 18.0)
    return scores


def _best_window_center(image, previous=None) -> tuple[float, float]:
    width, height = image.size
    crop_width = max(2, min(width, int(round(height * TARGET_RATIO))))
    scores = _column_scores(image, previous)
    prefix = [0.0]
    for value in scores:
        prefix.append(prefix[-1] + value)
    best_x = max(0, (width - crop_width) // 2)
    best_score = -1.0
    all_scores: list[float] = []
    for x in range(0, max(1, width - crop_width + 1)):
        score = prefix[x + crop_width] - prefix[x]
        all_scores.append(score)
        if score > best_score:
            best_score = score
            best_x = x
    mean_score = sum(all_scores) / max(1, len(all_scores))
    confidence = max(0.0, min(1.0, (best_score - mean_score) / max(1.0, abs(mean_score))))
    center_ratio = (best_x + crop_width / 2.0) / max(1.0, width)
    return max(0.0, min(1.0, center_ratio)), confidence


def _smooth_focus_points(points: list[tuple[float, float, float]], duration: float) -> list[tuple[float, float]]:
    if not points:
        return [(0.0, 0.5), (duration, 0.5)]
    # Median neighborhood rejects single-frame saliency spikes.
    medians: list[float] = []
    centers = [p[1] for p in points]
    for index, value in enumerate(centers):
        neighborhood = centers[max(0, index - 1) : min(len(centers), index + 2)]
        medians.append(sorted(neighborhood)[len(neighborhood) // 2] if neighborhood else value)
    smoothed: list[tuple[float, float]] = []
    current = 0.5
    last_t = 0.0
    max_speed = 0.10  # At most 10% of the frame width per second.
    for (timestamp, _center, confidence), median_center in zip(points, medians):
        alpha = 0.22 + min(0.43, confidence * 0.43)
        desired = current * (1.0 - alpha) + median_center * alpha
        delta_t = max(0.05, timestamp - last_t)
        allowed = max_speed * delta_t
        desired = max(current - allowed, min(current + allowed, desired))
        current = max(0.12, min(0.88, desired))
        smoothed.append((timestamp, current))
        last_t = timestamp
    if smoothed[0][0] > 0:
        smoothed.insert(0, (0.0, smoothed[0][1]))
    if smoothed[-1][0] < duration:
        smoothed.append((duration, smoothed[-1][1]))
    return smoothed


def _analyze_focus(source: Path, probe: VideoProbe, work_dir: Path, sample_count: int) -> dict[str, Any]:
    if Image is None:
        return {"points": [(0.0, 0.5), (probe.duration, 0.5)], "confidence": 0.0, "fallback": "pillow_missing"}
    samples = _extract_sample_frames(source, probe, work_dir / "frames", sample_count)
    if not samples:
        return {"points": [(0.0, 0.5), (probe.duration, 0.5)], "confidence": 0.0, "fallback": "frame_extract_failed"}
    raw_points: list[tuple[float, float, float]] = []
    previous = None
    for timestamp, path in samples:
        with Image.open(path) as image:
            current = image.convert("RGB")
            center, confidence = _best_window_center(current, previous)
            raw_points.append((timestamp, center, confidence))
            previous = current.copy()
    smoothed = _smooth_focus_points(raw_points, probe.duration)
    confidence = sum(point[2] for point in raw_points) / max(1, len(raw_points))
    return {
        "points": smoothed,
        "raw_points": raw_points,
        "confidence": round(confidence, 4),
        "fallback": "" if confidence >= 0.02 else "low_confidence_center_weighted",
    }


def _linear_center_expression(points: list[tuple[float, float]]) -> str:
    """Build a short FFmpeg expression returning center ratio in [0,1]."""
    if not points:
        return "0.5"
    points = sorted(points)
    expression = f"{points[-1][1]:.6f}"
    for index in range(len(points) - 2, -1, -1):
        t0, c0 = points[index]
        t1, c1 = points[index + 1]
        if t1 <= t0:
            segment = f"{c1:.6f}"
        else:
            slope = (c1 - c0) / (t1 - t0)
            segment = f"({c0:.6f}+({slope:.8f})*(t-{t0:.6f}))"
        expression = f"if(lt(t,{t1:.6f}),{segment},{expression})"
    return expression


def _crop_filter(probe: VideoProbe, focus_points: list[tuple[float, float]], mode: str) -> tuple[str, dict[str, Any]]:
    width = probe.display_width
    height = probe.display_height
    if width <= 0 or height <= 0:
        raise RuntimeError("无法读取视频宽高")

    # Keep the full source height and crop the horizontal dimension to 9:16.
    crop_height = height - (height % 2)
    crop_width = int(math.floor(crop_height * TARGET_RATIO))
    crop_width -= crop_width % 2
    crop_width = max(2, min(width - (width % 2), crop_width))
    max_x = max(0, width - crop_width)

    if mode == "fit_blur" or width / max(1, height) <= TARGET_RATIO:
        vf = (
            f"split=2[bg][fg];"
            f"[bg]scale={TARGET_WIDTH}:{TARGET_HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={TARGET_WIDTH}:{TARGET_HEIGHT},boxblur=30:15[blur];"
            f"[fg]scale={TARGET_WIDTH}:{TARGET_HEIGHT}:force_original_aspect_ratio=decrease[front];"
            f"[blur][front]overlay=(W-w)/2:(H-h)/2,setsar=1"
        )
        return vf, {"strategy": "fit_blur", "crop_width": width, "crop_height": height}

    if mode == "center_crop":
        x_expression = str(max_x // 2)
        strategy = "center_crop"
    else:
        center_expression = _linear_center_expression(focus_points)
        # x = desired_center * width - crop_width/2, clamped to valid bounds.
        x_expression = f"max(0,min({max_x},({center_expression})*{width}-{crop_width / 2:.3f}))"
        strategy = "smart_crop"

    vf = f"crop={crop_width}:{crop_height}:x='{x_expression}':y=0,scale={TARGET_WIDTH}:{TARGET_HEIGHT}:flags=lanczos,setsar=1"
    return vf, {
        "strategy": strategy,
        "crop_width": crop_width,
        "crop_height": crop_height,
        "max_x": max_x,
        "focus_points": focus_points,
    }


def _render_vertical(source: Path, output: Path, probe: VideoProbe, mode: str, focus: dict[str, Any], crf: int, preset: str) -> dict[str, Any]:
    output.parent.mkdir(parents=True, exist_ok=True)
    vf, plan = _crop_filter(probe, focus.get("points") or [], mode)
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-preset",
        preset,
        "-crf",
        str(crf),
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-ar",
        "48000",
        "-movflags",
        "+faststart",
        "-metadata:s:v:0",
        "rotate=0",
        "-y",
        str(output),
    ]
    _run(command, timeout=max(900, int(probe.duration * 30)))
    if not output.exists() or output.stat().st_size < 1024:
        raise RuntimeError("FFmpeg 未生成有效竖屏文件")
    result_probe = _probe_video(output)
    if result_probe.display_width != TARGET_WIDTH or result_probe.display_height != TARGET_HEIGHT:
        raise RuntimeError(f"输出尺寸异常：{result_probe.display_width}x{result_probe.display_height}")
    return {**plan, "output_probe": result_probe.__dict__, "ffmpeg_filter": vf}


# ------------------------------ job execution ------------------------------

def _output_key(source_key: str, source_etag: str, output_prefix: str) -> str:
    prefix = _normalize_prefix(output_prefix) or DEFAULT_OUTPUT_PREFIX
    source_stem = Path(source_key).stem
    safe_stem = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in source_stem)[:100]
    digest = hashlib.sha256(f"{source_key}|{source_etag}|{VERSION}".encode("utf-8")).hexdigest()[:12]
    return f"{prefix}/{safe_stem}_{digest}_9x16.mp4"


def _disk_preflight(work_root: Path, source_size: int, reserve_free_mb: int) -> None:
    usage = shutil.disk_usage(work_root)
    reserve = reserve_free_mb * 1024 * 1024
    # Download + encoded output + frames. Do not begin unless the job can finish while preserving reserve.
    required = int(source_size * 2.35) + 256 * 1024 * 1024 + reserve
    if usage.free < required:
        raise RuntimeError(
            f"本地临时空间不足：可用 {usage.free / 1024 / 1024:.0f}MB，"
            f"本条至少需要 {required / 1024 / 1024:.0f}MB（含 {reserve_free_mb}MB 安全保留）。"
        )


def _register_derived_asset(
    settings: Settings,
    *,
    source_key: str,
    output_key: str,
    output_url: str,
    output_size: int,
    probe: VideoProbe,
    plan: dict[str, Any],
) -> dict[str, Any]:
    asset_id = Path(output_key).stem
    payload = {
        "id": asset_id,
        "filename": Path(output_key).name,
        "original_name": f"竖屏转换_{Path(source_key).name}",
        "kind": "video",
        "url": output_url,
        "r2_url": output_url,
        "r2_key": output_key,
        "size_bytes": output_size,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "folder": "vertical_9x16",
        "source_type": "r2_smart_vertical_reframe",
        "source_r2_key": source_key,
        "workspace_id": settings.workspace_id,
        "deleted": False,
        "width": TARGET_WIDTH,
        "height": TARGET_HEIGHT,
        "duration": probe.duration,
        "aspect_ratio": "9:16",
        "reframe_version": VERSION,
        "reframe_strategy": plan.get("strategy"),
        "focus_confidence": plan.get("focus_confidence", 0.0),
        "derived_from": source_key,
    }
    try:
        memory = MemoryStore(settings)
    except Exception:
        memory = None
    return upsert_asset(settings, payload, memory, require_supabase=False)


def _process_one(settings: Settings, job_id: str, source_key: str, request: ReframeJobRequest, index: int, total: int) -> dict[str, Any]:
    if job_id in _CANCELLED:
        raise RuntimeError("任务已取消")
    source_key = _normalize_key(source_key)
    suffix = Path(source_key).suffix.lower()
    if suffix not in VIDEO_EXTENSIONS:
        raise RuntimeError(f"不支持的视频格式：{suffix or 'unknown'}")

    head = _head_object(settings, source_key)
    source_size = int(head["content_length"])
    if source_size <= 0:
        raise RuntimeError("R2 对象大小为 0")
    if source_size > request.max_input_mb * 1024 * 1024:
        raise RuntimeError(f"文件超过单条上限 {request.max_input_mb}MB")

    output_key = _output_key(source_key, str(head.get("etag") or ""), request.output_prefix)
    if not request.force and _object_exists(settings, output_key):
        return {
            "source_key": source_key,
            "output_key": output_key,
            "output_url": public_r2_url(settings, output_key),
            "status": "skipped_existing",
        }

    work_parent = settings.tmp_dir / "r2-smart-vertical-reframe"
    work_parent.mkdir(parents=True, exist_ok=True)
    _disk_preflight(work_parent, source_size, request.reserve_free_mb)

    work_dir = Path(tempfile.mkdtemp(prefix=f"{job_id[:8]}_{index:03d}_", dir=work_parent))
    local_source = work_dir / _safe_filename_from_key(source_key)
    local_output = work_dir / "vertical_9x16.mp4"
    try:
        _update_job(
            settings,
            job_id,
            current_index=index,
            current_source_key=source_key,
            progress=round((index - 1) / max(1, total) * 100, 2),
            message=f"正在下载第 {index}/{total} 条素材",
        )
        _download_object(settings, source_key, local_source)
        if local_source.stat().st_size != source_size:
            raise RuntimeError("R2 下载后的文件大小不一致")
        probe = _probe_video(local_source)

        if request.skip_non_landscape and probe.ratio <= 1.0 and request.mode != "fit_blur":
            return {
                "source_key": source_key,
                "status": "skipped_non_landscape",
                "source_probe": probe.__dict__,
                "message": "源视频不是横屏，默认不重复转换。",
            }

        if probe.ratio <= TARGET_RATIO * 1.03:
            effective_mode = "fit_blur"
        else:
            effective_mode = request.mode

        _update_job(settings, job_id, message=f"正在分析主体并转换第 {index}/{total} 条素材")
        focus = (
            _analyze_focus(local_source, probe, work_dir, request.sample_count)
            if effective_mode == "smart_crop"
            else {"points": [(0.0, 0.5), (probe.duration, 0.5)], "confidence": 1.0, "fallback": ""}
        )
        plan = _render_vertical(local_source, local_output, probe, effective_mode, focus, request.crf, request.preset)
        plan["focus_confidence"] = focus.get("confidence", 0.0)
        plan["focus_fallback"] = focus.get("fallback", "")

        _update_job(settings, job_id, message=f"正在上传第 {index}/{total} 条竖屏素材到 R2")
        output_url = _upload_object(
            settings,
            local_output,
            output_key,
            metadata={
                "source-key-sha256": hashlib.sha256(source_key.encode("utf-8")).hexdigest(),
                "source-etag": str(head.get("etag") or ""),
                "reframe-version": VERSION,
                "reframe-strategy": str(plan.get("strategy") or ""),
                "workspace-id": settings.workspace_id,
            },
        )
        registered: dict[str, Any] | None = None
        if request.register_assets:
            registered = _register_derived_asset(
                settings,
                source_key=source_key,
                output_key=output_key,
                output_url=output_url,
                output_size=local_output.stat().st_size,
                probe=probe,
                plan=plan,
            )

        return {
            "source_key": source_key,
            "output_key": output_key,
            "output_url": output_url,
            "status": "completed",
            "source_probe": probe.__dict__,
            "plan": plan,
            "registered_asset_id": (registered or {}).get("id", ""),
            "output_size_bytes": local_output.stat().st_size,
        }
    finally:
        if request.delete_local_after_upload:
            shutil.rmtree(work_dir, ignore_errors=True)


def _run_job(settings: Settings, job_id: str, request_payload: dict[str, Any]) -> None:
    global _RUNNING_JOB_ID
    request = ReframeJobRequest(**request_payload)
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    _RUNNING_JOB_ID = job_id
    try:
        _update_job(settings, job_id, status="running", started_at=_utc_now(), message="任务开始", progress=0.0)
        total = len(request.object_keys)
        for index, source_key in enumerate(request.object_keys, start=1):
            if job_id in _CANCELLED:
                _update_job(settings, job_id, status="cancelled", message="任务已取消", finished_at=_utc_now())
                return
            try:
                result = _process_one(settings, job_id, source_key, request, index, total)
                results.append(result)
            except Exception as exc:
                failures.append(
                    {
                        "source_key": source_key,
                        "error": f"{type(exc).__name__}: {str(exc)[:1200]}",
                    }
                )
            _update_job(
                settings,
                job_id,
                results=results,
                failures=failures,
                completed_count=len(results),
                failed_count=len(failures),
                progress=round(index / max(1, total) * 100, 2),
                message=f"已处理 {index}/{total} 条素材",
            )
        final_status = "completed" if not failures else ("partial" if results else "failed")
        _update_job(
            settings,
            job_id,
            status=final_status,
            progress=100.0,
            finished_at=_utc_now(),
            message=f"任务结束：成功 {len(results)}，失败 {len(failures)}",
        )
    except Exception as exc:
        _update_job(
            settings,
            job_id,
            status="failed",
            finished_at=_utc_now(),
            error=f"{type(exc).__name__}: {str(exc)[:2000]}",
            message="任务异常退出",
        )
    finally:
        _RUNNING_JOB_ID = None
        _CANCELLED.discard(job_id)


# ------------------------------ API ------------------------------

@router.get("/health")
def health(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    ffmpeg = shutil.which("ffmpeg") is not None
    ffprobe = shutil.which("ffprobe") is not None
    free = shutil.disk_usage(settings.tmp_dir).free
    return {
        "ok": bool(settings.r2_enabled and ffmpeg and ffprobe),
        "version": VERSION,
        "mode": "r2_source_to_r2_vertical_9x16",
        "r2_enabled": settings.r2_enabled,
        "ffmpeg": ffmpeg,
        "ffprobe": ffprobe,
        "pillow": Image is not None,
        "max_concurrency": 1,
        "running_job_id": _RUNNING_JOB_ID,
        "local_free_mb": round(free / 1024 / 1024, 1),
        "features": {
            "r2_source_of_truth": True,
            "original_never_overwritten": True,
            "smart_saliency_crop": True,
            "motion_aware_focus": True,
            "smooth_focus_path": True,
            "center_crop_fallback": True,
            "fit_blur_fallback": True,
            "audio_preserved": True,
            "asset_auto_register": True,
            "sequential_low_disk_worker": True,
            "job_persistence": True,
        },
    }


@router.post("/scan")
def scan(
    request: ScanRequest,
    _auth: None = Depends(_require_api_token),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    if not settings.r2_enabled:
        raise HTTPException(status_code=503, detail="R2 未配置")
    try:
        items = _list_r2_objects(settings, request.prefix, request.limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"R2 列表读取失败：{type(exc).__name__}: {exc}") from exc
    # Scan is intentionally cheap: exact landscape filtering happens after ffprobe in a job.
    return {
        "ok": True,
        "prefix": _normalize_prefix(request.prefix),
        "count": len(items),
        "items": items,
        "note": "创建任务后会用 ffprobe 精确识别横屏；scan 阶段不下载完整视频。",
    }


@router.post("/jobs")
def create_job(
    request: ReframeJobRequest,
    _auth: None = Depends(_require_api_token),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    if not settings.r2_enabled:
        raise HTTPException(status_code=503, detail="R2 未配置")
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise HTTPException(status_code=503, detail="FFmpeg/FFprobe 不可用")
    cleaned_keys: list[str] = []
    seen: set[str] = set()
    for raw in request.object_keys:
        try:
            key = _normalize_key(raw)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if key not in seen:
            cleaned_keys.append(key)
            seen.add(key)
    request.object_keys = cleaned_keys
    if not request.object_keys:
        raise HTTPException(status_code=400, detail="object_keys 不能为空")

    job_id = f"r2vr_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:10]}"
    job = {
        "id": job_id,
        "status": "queued",
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
        "workspace_id": settings.workspace_id,
        "request": request.model_dump(),
        "total_count": len(request.object_keys),
        "completed_count": 0,
        "failed_count": 0,
        "progress": 0.0,
        "results": [],
        "failures": [],
        "message": "已进入单并发处理队列",
        "version": VERSION,
    }
    with _STATE_LOCK:
        jobs = _load_jobs(settings)
        jobs[job_id] = job
        _save_jobs(settings, jobs)
    _EXECUTOR.submit(_run_job, settings, job_id, request.model_dump())
    return {"ok": True, "job": job}


@router.get("/jobs")
def list_jobs(
    limit: int = 20,
    _auth: None = Depends(_require_api_token),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    limit = max(1, min(100, int(limit)))
    jobs = sorted(_load_jobs(settings).values(), key=lambda row: row.get("created_at", ""), reverse=True)[:limit]
    return {"ok": True, "count": len(jobs), "jobs": jobs}


@router.get("/jobs/{job_id}")
def get_job(
    job_id: str,
    _auth: None = Depends(_require_api_token),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    job = _get_job(settings, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"ok": True, "job": job}


@router.post("/jobs/{job_id}/cancel")
def cancel_job(
    job_id: str,
    _auth: None = Depends(_require_api_token),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    job = _get_job(settings, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job.get("status") in {"completed", "partial", "failed", "cancelled"}:
        return {"ok": True, "job": job, "message": "任务已经结束"}
    _CANCELLED.add(job_id)
    updated = _update_job(settings, job_id, cancel_requested=True, message="已请求取消；当前文件处理结束后停止")
    return {"ok": True, "job": updated}
