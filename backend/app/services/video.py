from __future__ import annotations

import math
import os
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


def _env_int(name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except Exception:
        value = default
    return max(low, min(high, value))


def target_size() -> tuple[int, int]:
    # Render free instance只有 512MB。默认改成 720x1280，避免 1080x1920 合成时 OOM 导致前端 Failed to fetch。
    width = _env_int("COMPOSE_VIDEO_WIDTH", 720, 360, 1080)
    height = _env_int("COMPOSE_VIDEO_HEIGHT", 1280, 640, 1920)
    # x264/yuv420p 要求偶数尺寸。
    width = width if width % 2 == 0 else width - 1
    height = height if height % 2 == 0 else height - 1
    return width, height


def run_cmd(cmd: list[str], timeout: int = 480) -> subprocess.CompletedProcess[str]:
    # 限制线程数，防止免费实例内存/CPU 被 ffmpeg 打满。
    env = os.environ.copy()
    env.setdefault("OMP_NUM_THREADS", "1")
    env.setdefault("OPENBLAS_NUM_THREADS", "1")
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False, env=env)


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
    value = str(path.resolve()).replace("\\", "/")
    return value.replace(":", "\\:").replace("'", "\\'")


def _video_codec_args() -> list[str]:
    # ultrafast + CRF 30：牺牲一点体积换稳定，防止 Render 免费实例爆内存。
    return ["-c:v", "libx264", "-preset", "ultrafast", "-crf", os.getenv("COMPOSE_VIDEO_CRF", "30"), "-threads", "1", "-pix_fmt", "yuv420p"]


def _color_base_cmd(duration: float, output_path: Path) -> list[str]:
    w, h = target_size()
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "warning", "-y",
        "-f", "lavfi", "-i", f"color=c=0x111827:s={w}x{h}:r=24:d={duration:.2f}",
        "-t", f"{duration:.2f}",
        *_video_codec_args(),
        str(output_path),
    ]


def build_default_base(duration: float, output_path: Path) -> Tuple[Path, List[str]]:
    proc = run_cmd(_color_base_cmd(duration, output_path), timeout=240)
    if proc.returncode != 0:
        raise RuntimeError(f"生成默认背景视频失败：{proc.stderr[-1200:]}")
    return output_path, ["素材不可用或合成压力过高，已使用轻量默认背景，避免 Render 免费实例崩溃。"]


def build_video_base(asset_paths: List[Path], duration: float, output_path: Path) -> Tuple[Path, List[str]]:
    warnings: List[str] = []
    duration = max(3.0, min(float(duration), float(_env_int("COMPOSE_MAX_SECONDS", 75, 5, 180))))
    max_assets = _env_int("COMPOSE_MAX_ASSETS", 4, 1, 8)
    valid_paths = [p for p in asset_paths if p.exists() and (is_image(p) or is_video(p))][:max_assets]
    if not valid_paths:
        return build_default_base(duration, output_path)

    w, h = target_size()
    fps = _env_int("COMPOSE_FPS", 24, 12, 30)
    per_duration = max(2.0, duration / len(valid_paths))
    cmd: List[str] = ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-y"]
    for path in valid_paths:
        if is_image(path):
            cmd += ["-loop", "1", "-t", f"{per_duration:.2f}", "-i", str(path)]
        else:
            # 视频素材只拿前几秒，循环会显著增加内存/CPU，免费实例先稳。
            cmd += ["-t", f"{per_duration:.2f}", "-i", str(path)]

    filter_parts: List[str] = []
    video_labels: List[str] = []
    for i, _path in enumerate(valid_paths):
        label = f"v{i}"
        filter_parts.append(
            f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},setsar=1,fps={fps},format=yuv420p[{label}]"
        )
        video_labels.append(f"[{label}]")
    filter_parts.append("".join(video_labels) + f"concat=n={len(valid_paths)}:v=1:a=0[outv]")

    cmd += [
        "-filter_complex", ";".join(filter_parts),
        "-map", "[outv]",
        "-t", f"{duration:.2f}",
        *_video_codec_args(),
        str(output_path),
    ]
    proc = run_cmd(cmd, timeout=max(240, int(duration * 12)))
    if proc.returncode == 0:
        if len(asset_paths) > len(valid_paths):
            warnings.append(f"为保证 Render 稳定，本次只使用前 {len(valid_paths)} 个可用素材。")
        return output_path, warnings

    warnings.append(f"素材合成失败，已降级默认背景：{proc.stderr[-900:]}")
    try:
        output_path.unlink(missing_ok=True)
    except Exception:
        pass
    default_path, default_warnings = build_default_base(duration, output_path)
    warnings.extend(default_warnings)
    return default_path, warnings


def burn_subtitles_and_audio(
    base_video: Path,
    subtitle_path: Optional[Path],
    audio_path: Optional[Path],
    output_path: Path,
    duration: float,
) -> List[str]:
    warnings: List[str] = []
    w, h = target_size()
    vf = f"scale={w}:{h},format=yuv420p"
    if subtitle_path and subtitle_path.exists():
        sub_path = ffmpeg_subtitle_path(subtitle_path)
        font_size = _env_int("COMPOSE_SUBTITLE_SIZE", 16, 12, 28)
        margin_v = _env_int("COMPOSE_SUBTITLE_MARGIN", 120, 40, 260)
        style = f"FontName=Noto Sans CJK SC,FontSize={font_size},PrimaryColour=&H00FFFFFF,OutlineColour=&H80000000,BorderStyle=1,Outline=2,Shadow=1,Alignment=2,MarginV={margin_v}"
        vf += f",subtitles='{sub_path}':force_style='{style}'"

    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-y", "-i", str(base_video)]
    if audio_path and audio_path.exists():
        cmd += ["-i", str(audio_path)]
    cmd += ["-vf", vf]
    if audio_path and audio_path.exists():
        cmd += ["-map", "0:v:0", "-map", "1:a:0", "-shortest"]
    cmd += ["-t", f"{duration:.2f}", *_video_codec_args()]
    if audio_path and audio_path.exists():
        cmd += ["-c:a", "aac", "-b:a", "96k"]
    cmd += ["-movflags", "+faststart", str(output_path)]

    proc = run_cmd(cmd, timeout=max(240, int(duration * 12)))
    if proc.returncode == 0:
        return warnings

    # 字幕滤镜最容易因为字体/路径失败；自动降级无字幕，但不能让前端直接 Failed to fetch。
    warnings.append(f"字幕烧录失败，已降级为无字幕视频：{proc.stderr[-900:]}")
    try:
        output_path.unlink(missing_ok=True)
    except Exception:
        pass

    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-y", "-i", str(base_video)]
    if audio_path and audio_path.exists():
        cmd += ["-i", str(audio_path)]
    cmd += ["-vf", f"scale={w}:{h},format=yuv420p"]
    if audio_path and audio_path.exists():
        cmd += ["-map", "0:v:0", "-map", "1:a:0", "-shortest"]
    cmd += ["-t", f"{duration:.2f}", *_video_codec_args()]
    if audio_path and audio_path.exists():
        cmd += ["-c:a", "aac", "-b:a", "96k"]
    cmd += ["-movflags", "+faststart", str(output_path)]
    proc2 = run_cmd(cmd, timeout=max(240, int(duration * 10)))
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

    duration_cap = float(_env_int("COMPOSE_MAX_SECONDS", 75, 5, 180))
    duration = max(float(duration_seconds), audio_duration or 0, 5.0)
    if duration > duration_cap:
        warnings.append(f"为避免 Render 免费实例合成超时/爆内存，本次视频时长从 {duration:.1f}s 限制为 {duration_cap:.1f}s。")
        duration = duration_cap

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
    except Exception:
        pass

    return VideoResult(
        video_path=output_video,
        subtitle_path=subtitle_path,
        audio_path=audio_path,
        duration_seconds=duration,
        warnings=warnings,
    )
