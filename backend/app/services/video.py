from __future__ import annotations

import math
import re
import shlex
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from app.config import Settings
from app.services.tts import probe_duration, synthesize_tts

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}


@dataclass
class VideoResult:
    video_path: Path
    subtitle_path: Optional[Path]
    audio_path: Optional[Path]
    duration_seconds: float
    warnings: List[str]


def run_cmd(cmd: list[str], timeout: int = 600) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)


def is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTS


def is_video(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTS


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\u3000", " ")).strip()


def split_script(text: str, max_chars: int = 18) -> List[str]:
    text = normalize_text(text)
    if not text:
        return [" "]
    parts: List[str] = []
    for sentence in re.split(r"(?<=[。！？!?；;])", text):
        sentence = sentence.strip()
        if not sentence:
            continue
        while len(sentence) > max_chars:
            cut = max(sentence.rfind("，", 0, max_chars), sentence.rfind(",", 0, max_chars), sentence.rfind(" ", 0, max_chars))
            if cut <= 4:
                cut = max_chars
            parts.append(sentence[:cut].strip(" ，,"))
            sentence = sentence[cut:].strip(" ，,")
        if sentence:
            parts.append(sentence)
    return parts or [text[:max_chars]]


def fmt_srt_time(seconds: float) -> str:
    seconds = max(0, seconds)
    ms = int(round((seconds - math.floor(seconds)) * 1000))
    total = int(math.floor(seconds))
    s = total % 60
    m = (total // 60) % 60
    h = total // 3600
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def create_srt(script: str, duration: float, output_path: Path) -> None:
    chunks = split_script(script)
    duration = max(duration, len(chunks) * 1.2)
    weights = [max(4, len(chunk)) for chunk in chunks]
    total_weight = sum(weights)
    cursor = 0.0
    lines: List[str] = []
    for idx, (chunk, weight) in enumerate(zip(chunks, weights), start=1):
        seg = max(1.2, duration * weight / total_weight)
        start = cursor
        end = min(duration, cursor + seg)
        if idx == len(chunks):
            end = duration
        cursor = end
        lines.append(f"{idx}\n{fmt_srt_time(start)} --> {fmt_srt_time(end)}\n{chunk}\n")
    output_path.write_text("\n".join(lines), encoding="utf-8")


def ffmpeg_subtitle_path(path: Path) -> str:
    # subtitles filter path escaping for ffmpeg/libass on Linux/macOS.
    value = str(path.resolve())
    value = value.replace("\\", "/")
    value = value.replace(":", "\\:").replace("'", "\\'")
    return value


def build_video_base(asset_paths: List[Path], duration: float, output_path: Path) -> Tuple[Path, List[str]]:
    warnings: List[str] = []
    duration = max(3.0, duration)

    if not asset_paths:
        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x111827:s=1080x1920:r=30:d={duration:.2f}",
            "-vf",
            "format=yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-t",
            f"{duration:.2f}",
            str(output_path),
        ]
        proc = run_cmd(cmd)
        if proc.returncode != 0:
            raise RuntimeError(f"生成默认背景视频失败：{proc.stderr[-1000:]}")
        warnings.append("未上传素材，已使用默认背景生成视频。")
        return output_path, warnings

    valid_paths = [p for p in asset_paths if p.exists() and (is_image(p) or is_video(p))]
    if not valid_paths:
        return build_video_base([], duration, output_path)

    per_duration = max(2.0, duration / len(valid_paths))
    cmd: List[str] = ["ffmpeg", "-y"]
    for path in valid_paths:
        if is_image(path):
            cmd += ["-loop", "1", "-t", f"{per_duration:.2f}", "-i", str(path)]
        else:
            cmd += ["-stream_loop", "-1", "-t", f"{per_duration:.2f}", "-i", str(path)]

    filter_parts: List[str] = []
    video_labels: List[str] = []
    for i, _path in enumerate(valid_paths):
        label = f"v{i}"
        filter_parts.append(
            f"[{i}:v]scale=1080:1920:force_original_aspect_ratio=increase,"
            f"crop=1080:1920,setsar=1,fps=30,format=yuv420p[{label}]"
        )
        video_labels.append(f"[{label}]")
    filter_parts.append("".join(video_labels) + f"concat=n={len(valid_paths)}:v=1:a=0[outv]")

    cmd += [
        "-filter_complex",
        ";".join(filter_parts),
        "-map",
        "[outv]",
        "-t",
        f"{duration:.2f}",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-pix_fmt",
        "yuv420p",
        str(output_path),
    ]
    proc = run_cmd(cmd)
    if proc.returncode != 0:
        raise RuntimeError(f"素材合成失败：{proc.stderr[-1500:]}\nCMD: {' '.join(shlex.quote(c) for c in cmd)}")
    return output_path, warnings


def burn_subtitles_and_audio(
    base_video: Path,
    subtitle_path: Optional[Path],
    audio_path: Optional[Path],
    output_path: Path,
    duration: float,
) -> List[str]:
    warnings: List[str] = []
    vf = "scale=1080:1920,format=yuv420p"
    if subtitle_path and subtitle_path.exists():
        sub_path = ffmpeg_subtitle_path(subtitle_path)
        # Alignment=2 底部居中；MarginV 控制离底部距离。
        style = "FontName=Noto Sans CJK SC,FontSize=17,PrimaryColour=&H00FFFFFF,OutlineColour=&H80000000,BorderStyle=1,Outline=2,Shadow=1,Alignment=2,MarginV=180"
        vf += f",subtitles='{sub_path}':force_style='{style}'"

    cmd = ["ffmpeg", "-y", "-i", str(base_video)]
    if audio_path and audio_path.exists():
        cmd += ["-i", str(audio_path)]
    cmd += ["-vf", vf]
    if audio_path and audio_path.exists():
        cmd += ["-map", "0:v:0", "-map", "1:a:0", "-shortest"]
    cmd += [
        "-t",
        f"{duration:.2f}",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    proc = run_cmd(cmd)
    if proc.returncode == 0:
        return warnings

    # 字幕滤镜在某些系统可能因字体/路径失败，降级为无字幕版本。
    warnings.append(f"字幕烧录失败，已降级为无字幕视频：{proc.stderr[-800:]}")
    cmd = ["ffmpeg", "-y", "-i", str(base_video)]
    if audio_path and audio_path.exists():
        cmd += ["-i", str(audio_path)]
    cmd += ["-vf", "scale=1080:1920,format=yuv420p"]
    if audio_path and audio_path.exists():
        cmd += ["-map", "0:v:0", "-map", "1:a:0", "-shortest"]
    cmd += [
        "-t",
        f"{duration:.2f}",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    proc2 = run_cmd(cmd)
    if proc2.returncode != 0:
        raise RuntimeError(f"最终视频合成失败：{proc2.stderr[-1500:]}")
    return warnings


async def compose_video(
    settings: Settings,
    script: str,
    asset_paths: Iterable[Path],
    duration_seconds: int,
    audio_path: Optional[Path] = None,
    voice: Optional[str] = None,
    rate: Optional[str] = None,
) -> VideoResult:
    warnings: List[str] = []

    if audio_path is None or not audio_path.exists():
        audio_path, audio_duration, tts_warning = await synthesize_tts(settings, script, voice=voice, rate=rate)
        if tts_warning:
            warnings.append(tts_warning)
    else:
        audio_duration = probe_duration(audio_path)

    duration = max(float(duration_seconds), audio_duration or 0, 5.0)
    task_id = uuid.uuid4().hex
    base_video = settings.tmp_dir / f"base_{task_id}.mp4"
    subtitle_path = settings.outputs_dir / f"sub_{task_id}.srt"
    output_video = settings.outputs_dir / f"video_{task_id}.mp4"

    create_srt(script, duration, subtitle_path)
    base_video, base_warnings = build_video_base(list(asset_paths), duration, base_video)
    warnings.extend(base_warnings)
    warnings.extend(burn_subtitles_and_audio(base_video, subtitle_path, audio_path, output_video, duration))

    try:
        base_video.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass

    return VideoResult(
        video_path=output_video,
        subtitle_path=subtitle_path,
        audio_path=audio_path,
        duration_seconds=duration,
        warnings=warnings,
    )
