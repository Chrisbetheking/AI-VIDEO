from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path
from typing import Dict, Optional, Tuple

TARGET_W = 1080
TARGET_H = 1920
TARGET_FPS = 30


def _run(cmd: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)


def ffprobe_size(path: Path) -> Tuple[int, int]:
    proc = _run([
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=p=0:s=x",
        str(path),
    ], timeout=60)

    text = (proc.stdout or "").strip()
    if "x" not in text:
        return 0, 0

    try:
        w, h = text.split("x", 1)
        return int(w), int(h)
    except Exception:
        return 0, 0


def detect_crop(path: Path) -> Optional[Dict[str, float]]:
    if not Path(path).exists():
        return None

    proc = _run([
        "ffmpeg", "-hide_banner",
        "-ss", "0",
        "-i", str(path),
        "-t", "2.5",
        "-vf", "cropdetect=24:2:0",
        "-f", "null", "-"
    ], timeout=90)

    text = (proc.stderr or "") + "\n" + (proc.stdout or "")
    crops = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", text)
    if not crops:
        return None

    full_w, full_h = ffprobe_size(path)
    if full_w <= 0 or full_h <= 0:
        return None

    parsed = []
    for w, h, x, y in crops:
        w, h, x, y = int(w), int(h), int(x), int(y)
        if w > 0 and h > 0:
            parsed.append((w * h, w, h, x, y))

    if not parsed:
        return None

    _, crop_w, crop_h, crop_x, crop_y = max(parsed, key=lambda v: v[0])
    content_ratio = (crop_w * crop_h) / float(full_w * full_h)

    return {
        "full_w": full_w,
        "full_h": full_h,
        "crop_w": crop_w,
        "crop_h": crop_h,
        "crop_x": crop_x,
        "crop_y": crop_y,
        "content_ratio": round(content_ratio, 4),
        "black_ratio": round(max(0.0, 1.0 - content_ratio), 4),
        "crop_filter": f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y}",
    }


def build_input_video_filter(input_index: int, path: Path, label: str, width: int = TARGET_W, height: int = TARGET_H, fps: int = TARGET_FPS) -> str:
    crop = detect_crop(Path(path))
    prefix = ""

    if crop:
        content_ratio = float(crop.get("content_ratio") or 1.0)
        if 0.08 < content_ratio < 0.999:
            prefix = f"{crop['crop_filter']},"

    return (
        f"[{input_index}:v]"
        f"{prefix}"
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar=1,fps={fps},format=yuv420p[{label}]"
    )


def normalize_to_vertical(input_path: Path, output_path: Path, duration: Optional[float] = None) -> Path:
    input_path = Path(input_path)
    output_path = Path(output_path)

    crop = detect_crop(input_path)
    prefix = ""

    if crop:
        content_ratio = float(crop.get("content_ratio") or 1.0)
        if 0.08 < content_ratio < 0.999:
            prefix = f"{crop['crop_filter']},"

    vf = (
        f"{prefix}"
        f"scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=increase,"
        f"crop={TARGET_W}:{TARGET_H},setsar=1,fps={TARGET_FPS},format=yuv420p"
    )

    cmd = ["ffmpeg", "-y", "-i", str(input_path), "-vf", vf]
    if duration:
        cmd += ["-t", f"{float(duration):.2f}"]
    cmd += [
        "-an",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        str(output_path),
    ]

    proc = _run(cmd, timeout=900)
    if proc.returncode != 0:
        raise RuntimeError(f"9:16 标准化失败：{proc.stderr[-1800:]}\nCMD: {' '.join(shlex.quote(c) for c in cmd)}")

    return output_path


def inspect_video_quality(path: Path, max_black_ratio: float = 0.15) -> Dict[str, object]:
    path = Path(path)
    if not path.exists():
        return {"ok": False, "reason": "file_missing", "message": f"视频文件不存在：{path}"}

    w, h = ffprobe_size(path)
    if w <= 0 or h <= 0:
        return {"ok": False, "reason": "probe_failed", "message": "无法读取视频分辨率"}

    aspect = w / float(h)
    expected = 9 / 16

    if abs(aspect - expected) > 0.035:
        return {
            "ok": False,
            "reason": "bad_aspect_ratio",
            "message": f"视频不是 9:16，当前分辨率 {w}x{h}",
            "width": w,
            "height": h,
        }

    crop = detect_crop(path)
    if crop:
        black_ratio = float(crop.get("black_ratio") or 0)
        if black_ratio > max_black_ratio:
            return {
                "ok": False,
                "reason": "black_border_too_large",
                "message": f"黑边/空画布过多：{black_ratio:.1%}，已拦截废片。",
                "width": w,
                "height": h,
                "crop": crop,
            }

    return {
        "ok": True,
        "reason": "passed",
        "message": "9:16 质检通过",
        "width": w,
        "height": h,
        "crop": crop,
    }


def polish_final_vertical_no_edge(input_path: Path, output_path: Path | None = None) -> Path:
    """Final polish: remove even tiny black edge bars, then scale back to 1080x1920.

    Example:
    1080x1920 video with cropdetect=1072:1920:4:0
    -> crop left/right 4px
    -> scale back to 1080x1920
    """
    input_path = Path(input_path)
    output_path = Path(output_path) if output_path else input_path

    crop = detect_crop(input_path)
    if not crop:
        return input_path

    full_w = int(crop.get("full_w") or 0)
    full_h = int(crop.get("full_h") or 0)
    crop_w = int(crop.get("crop_w") or 0)
    crop_h = int(crop.get("crop_h") or 0)
    content_ratio = float(crop.get("content_ratio") or 1.0)

    if full_w <= 0 or full_h <= 0 or crop_w <= 0 or crop_h <= 0:
        return input_path

    # 只要检测到不是完整画布，就最终裁一次。
    # content_ratio 低于 0.08 通常是误检，跳过。
    if not (0.08 < content_ratio < 0.9999):
        return input_path

    tmp_out = output_path.with_suffix(".zero_edge_tmp.mp4")

    vf = (
        f"{crop['crop_filter']},"
        f"scale={TARGET_W}:{TARGET_H}:flags=lanczos,"
        f"setsar=1,fps={TARGET_FPS},format=yuv420p"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "18",
        "-c:a", "copy",
        str(tmp_out),
    ]

    proc = _run(cmd, timeout=900)
    if proc.returncode != 0:
        raise RuntimeError(f"最终去边失败：{proc.stderr[-1800:]}")

    if output_path == input_path:
        tmp_out.replace(input_path)
        return input_path

    tmp_out.replace(output_path)
    return output_path
