"""Human overlay (green screen) compositing for MVP."""

from __future__ import annotations

import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class HumanOverlayResult:
    output_path: Optional[Path]
    mode: str  # none, human_intro, human_pip
    warnings: List[str] = field(default_factory=list)


HUMAN_POSITIONS = {
    "right_bottom": "W-w-20:H-h-20",
    "left_bottom": "20:H-h-20",
    "center_bottom": "(W-w)/2:H-h-20",
}

HUMAN_SCALES = {
    "30%": 0.30,
    "40%": 0.40,
    "50%": 0.50,
}


def _run_cmd(cmd: list[str], timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)


def _ffmpeg_path_str(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def chromakey_filter(
    color: str = "0x00FF00",
    similarity: float = 0.30,
    blend: float = 0.10,
) -> str:
    """FFmpeg chromakey filter string for green screen removal."""
    return f"chromakey={color}:{similarity:.2f}:{blend:.2f}"


def overlay_human_on_video(
    base_video: Path,
    human_video: Path,
    output_path: Path,
    position: str = "right_bottom",
    scale_pct: str = "40%",
    take_first_seconds: float = 0.0,
    keep_human_audio: bool = False,
) -> HumanOverlayResult:
    """Overlay a green-screen human video onto a base video.

    Args:
        base_video: The main content video.
        human_video: Green-screen human footage.
        output_path: Where to write the composited MP4.
        position: One of right_bottom, left_bottom, center_bottom.
        scale_pct: Scale percentage for the human overlay.
        take_first_seconds: If > 0, only use first N seconds of human video.
        keep_human_audio: If True, mix human audio with base audio.
    """
    warnings: List[str] = []

    if not human_video or not human_video.exists():
        return HumanOverlayResult(
            output_path=base_video,
            mode="none",
            warnings=["No human video provided, using base video as-is."],
        )

    scale_factor = HUMAN_SCALES.get(scale_pct, 0.40)
    pos_expr = HUMAN_POSITIONS.get(position, HUMAN_POSITIONS["right_bottom"])

    # Build the filter chain
    chroma = chromakey_filter()
    overlay_filter = (
        f"[1:v]{chroma},scale=iw*{scale_factor:.2f}:-1[fg];"
        f"[0:v][fg]overlay={pos_expr}:format=auto"
    )

    cmd = ["ffmpeg", "-y", "-i", _ffmpeg_path_str(base_video)]

    if take_first_seconds > 0:
        cmd += ["-t", f"{take_first_seconds:.2f}"]

    cmd += ["-i", _ffmpeg_path_str(human_video)]

    if take_first_seconds > 0:
        cmd += ["-ss", "0", "-t", f"{take_first_seconds:.2f}"]

    cmd += ["-filter_complex", overlay_filter]
    cmd += ["-map", "0:a:0?"]  # base audio

    if keep_human_audio:
        cmd += ["-map", "1:a:0?"]
        cmd += ["-filter:a", "amix=inputs=2:duration=first"]
        cmd += ["-c:a", "aac", "-b:a", "128k"]
    else:
        cmd += ["-c:a", "aac", "-b:a", "128k"]

    cmd += [
        "-c:v", "libx264", "-preset", "veryfast",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(output_path),
    ]

    proc = _run_cmd(cmd)
    if proc.returncode != 0:
        warnings.append(f"Human overlay failed, falling back to base video: {proc.stderr[-500:]}")
        return HumanOverlayResult(
            output_path=base_video,
            mode="none",
            warnings=warnings,
        )

    return HumanOverlayResult(
        output_path=output_path,
        mode="human_intro" if scale_pct in ("40%", "50%") else "human_pip",
        warnings=warnings,
    )


def build_human_overlay_filter(
    scale_pct: str = "40%",
    position: str = "right_bottom",
    chroma_color: str = "0x00FF00",
    chroma_similarity: float = 0.30,
    chroma_blend: float = 0.10,
) -> str:
    """Build the FFmpeg filter string for human green-screen overlay.

    Returns a filter_complex string that can be embedded into a wider compose pipeline.
    """
    scale_factor = HUMAN_SCALES.get(scale_pct, 0.40)
    pos_expr = HUMAN_POSITIONS.get(position, HUMAN_POSITIONS["right_bottom"])
    chroma = chromakey_filter(color=chroma_color, similarity=chroma_similarity, blend=chroma_blend)
    return (
        f"[1:v]{chroma},scale=iw*{scale_factor:.2f}:-1[fg];"
        f"[0:v][fg]overlay={pos_expr}:format=auto"
    )
