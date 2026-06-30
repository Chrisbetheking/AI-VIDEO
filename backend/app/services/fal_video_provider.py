from __future__ import annotations

import os
import time
import uuid
import traceback
from typing import Any, Dict, List, Optional

import fal_client


QUICK_T2V = os.getenv("FAL_QUICK_T2V_MODEL", "fal-ai/wan/v2.2-a14b/text-to-video/turbo")
STANDARD_T2V = os.getenv("FAL_STANDARD_T2V_MODEL", "fal-ai/wan/v2.2-a14b/text-to-video")
QUICK_I2V = os.getenv("FAL_QUICK_I2V_MODEL", "fal-ai/wan/v2.2-a14b/image-to-video/turbo")
STANDARD_I2V = os.getenv("FAL_STANDARD_I2V_MODEL", "fal-ai/wan/v2.2-a14b/image-to-video")


def fal_ready() -> bool:
    return bool(os.getenv("FAL_KEY"))


def pick_model(mode: str, image_url: Optional[str]) -> str:
    mode = (mode or "quick").lower().strip()

    if image_url:
        if mode in {"standard", "high", "quality"}:
            return STANDARD_I2V
        return QUICK_I2V

    if mode in {"standard", "high", "quality"}:
        return STANDARD_T2V
    return QUICK_T2V


def extract_video_url(data: Any) -> Optional[str]:
    if isinstance(data, dict):
        if isinstance(data.get("video"), dict) and data["video"].get("url"):
            return data["video"]["url"]

        if isinstance(data.get("videos"), list) and data["videos"]:
            first = data["videos"][0]
            if isinstance(first, dict) and first.get("url"):
                return first["url"]

        if data.get("url") and isinstance(data.get("url"), str):
            return data["url"]

        for v in data.values():
            found = extract_video_url(v)
            if found:
                return found

    if isinstance(data, list):
        for item in data:
            found = extract_video_url(item)
            if found:
                return found

    return None


def build_arguments(
    prompt: str,
    mode: str = "quick",
    image_url: Optional[str] = None,
    resolution: str = "720p",
    num_frames: int = 81,
    frames_per_second: int = 16,
    negative_prompt: str = "",
    video_quality: str = "high",
    video_write_mode: str = "balanced",
) -> Dict[str, Any]:
    args: Dict[str, Any] = {
        "prompt": prompt,
    }

    if negative_prompt:
        args["negative_prompt"] = negative_prompt

    if image_url:
        args["image_url"] = image_url
        args["resolution"] = resolution or "720p"

        if mode in {"standard", "high", "quality"}:
            args["num_frames"] = int(num_frames)
            args["frames_per_second"] = int(frames_per_second)
            args["video_quality"] = video_quality
            args["video_write_mode"] = video_write_mode
        return args

    args["num_frames"] = int(num_frames)
    args["frames_per_second"] = int(frames_per_second)
    args["video_quality"] = video_quality
    args["video_write_mode"] = video_write_mode
    return args


def generate_fal_video(
    prompt: str,
    mode: str = "quick",
    image_url: Optional[str] = None,
    resolution: str = "720p",
    num_frames: int = 81,
    frames_per_second: int = 16,
    negative_prompt: str = "",
    video_quality: str = "high",
    video_write_mode: str = "balanced",
) -> Dict[str, Any]:
    if not fal_ready():
        raise RuntimeError("FAL_KEY is not configured")

    model = pick_model(mode=mode, image_url=image_url)
    args = build_arguments(
        prompt=prompt,
        mode=mode,
        image_url=image_url,
        resolution=resolution,
        num_frames=num_frames,
        frames_per_second=frames_per_second,
        negative_prompt=negative_prompt,
        video_quality=video_quality,
        video_write_mode=video_write_mode,
    )

    started_at = time.time()

    result = fal_client.subscribe(
        model,
        arguments=args,
        with_logs=True,
    )

    video_url = extract_video_url(result)

    return {
        "ok": True,
        "provider": "fal",
        "model": model,
        "mode": mode,
        "image_mode": bool(image_url),
        "video_url": video_url,
        "raw_result": result,
        "elapsed_seconds": round(time.time() - started_at, 2),
    }


def safe_error(e: Exception) -> Dict[str, Any]:
    return {
        "ok": False,
        "error": str(e),
        "traceback_tail": traceback.format_exc()[-4000:],
    }


def make_job_id(prefix: str = "fal_video") -> str:
    return prefix + "_" + uuid.uuid4().hex[:18]
