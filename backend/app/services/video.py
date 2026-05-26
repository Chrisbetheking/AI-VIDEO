from __future__ import annotations

import math
import os
import re
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List, Optional, Tuple, Union

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


@dataclass
class MediaClip:
    path: Path
    kind: str = ""
    image_seconds: float = 2.8
    video_start: float = 0.0
    video_end: float = 0.0
    order: int = 0


def _env_int(name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except Exception:
        value = default
    return max(low, min(high, value))


def target_size() -> tuple[int, int]:
    # Render free instance只有 512MB。默认 720x1280，避免 1080x1920 合成时 OOM。
    width = _env_int("COMPOSE_VIDEO_WIDTH", 540, 360, 1080)
    height = _env_int("COMPOSE_VIDEO_HEIGHT", 960, 640, 1920)
    width = width if width % 2 == 0 else width - 1
    height = height if height % 2 == 0 else height - 1
    return width, height


def run_cmd(cmd: list[str], timeout: int = 480) -> subprocess.CompletedProcess[str]:
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



_PUNCT_ONLY_RE = re.compile(r'^[\s。！？!?，,、；;：:.．…·“”"\'（）()【】\[\]-]+$')


def clean_subtitle_text(text: str) -> str:
    text = normalize_text(text)
    text = text.replace('……', '…')
    # 字幕不需要单独显示句号，避免出现独立“。”或“.”一帧。
    text = re.sub(r'[。．\.]+$', '', text).strip()
    text = re.sub(r'^[。．\.,，、；;：:]+', '', text).strip()
    return '' if _PUNCT_ONLY_RE.match(text or '') else text


def subtitle_chunks(text: str, max_chars: int = 14) -> List[str]:
    raw = normalize_text(text)
    if not raw:
        return []
    # 先按语义标点断句；标点留在前句，不产生独立标点行。
    pieces = [p.strip() for p in re.split(r'(?<=[，,。！？!?；;：:])', raw) if p.strip()]
    chunks: list[str] = []
    for piece in pieces or [raw]:
        piece = clean_subtitle_text(piece)
        if not piece:
            continue
        while len(piece) > max_chars:
            cut = max(piece.rfind('，', 0, max_chars), piece.rfind(',', 0, max_chars), piece.rfind('、', 0, max_chars), piece.rfind(' ', 0, max_chars))
            if cut <= 4:
                cut = max_chars
            chunk = clean_subtitle_text(piece[:cut])
            if chunk:
                chunks.append(chunk)
            piece = piece[cut:].strip(' ，,、')
        piece = clean_subtitle_text(piece)
        if piece:
            chunks.append(piece)
    # 再做一遍兜底过滤，避免任何孤立标点。
    return [c for c in chunks if c and not _PUNCT_ONLY_RE.match(c)][:20]

def split_script(text: str, max_chars: int = 14) -> List[str]:
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


def _append_srt_line(lines: list[str], index: int, start: float, end: float, text: str) -> int:
    if end <= start:
        end = start + 0.8
    clean = clean_subtitle_text(text)
    if not clean:
        return index
    # 口播字幕不要太长，否则会挡住人物主体。每句尽量 12-14 字；不显示孤立标点。
    chunks = subtitle_chunks(clean, max_chars=14) or [clean]
    chunks = [clean_subtitle_text(c) for c in chunks if clean_subtitle_text(c)]
    if not chunks:
        return index
    if len(chunks) <= 1:
        lines.append(f"{index}\n{fmt_srt_time(start)} --> {fmt_srt_time(end)}\n{chunks[0]}\n")
        return index + 1
    weights = [max(2, len(re.sub(r'[，,、；;：:！？!?]', '', c))) for c in chunks]
    total_weight = max(1, sum(weights))
    cursor = start
    for chunk, weight in zip(chunks, weights):
        span = max(0.35, (end - start) * weight / total_weight)
        next_end = min(end, cursor + span)
        if next_end <= cursor + 0.2:
            next_end = min(end, cursor + 0.35)
        lines.append(f"{index}\n{fmt_srt_time(cursor)} --> {fmt_srt_time(next_end)}\n{chunk}\n")
        cursor = next_end
        index += 1
    return index


def create_srt(script: str, duration: float, output_path: Path, subtitle_segments: Optional[list[dict[str, Any]]] = None) -> None:
    lines: List[str] = []
    index = 1
    if subtitle_segments:
        for seg in subtitle_segments:
            try:
                text = str(seg.get('text') or '').strip()
                start = float(seg.get('start') or 0)
                end = float(seg.get('end') or 0)
            except Exception:
                continue
            if text:
                index = _append_srt_line(lines, index, start, min(end, duration), text)
    if not lines:
        chunks = subtitle_chunks(script) or split_script(script)
        duration = max(duration, len(chunks) * 1.2)
        weights = [max(4, len(chunk)) for chunk in chunks]
        total_weight = sum(weights)
        cursor = 0.0
        for chunk, weight in zip(chunks, weights):
            seg = max(1.0, duration * weight / total_weight)
            start = cursor
            end = min(duration, cursor + seg)
            cursor = end
            index = _append_srt_line(lines, index, start, end, chunk)
    output_path.write_text("\n".join(lines), encoding="utf-8")


def ffmpeg_subtitle_path(path: Path) -> str:
    value = str(path.resolve()).replace("\\", "/")
    return value.replace(":", "\\:").replace("'", "\\'")


def _video_codec_args() -> list[str]:
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


def _coerce_clip(item: Union[Path, MediaClip], order: int = 0) -> Optional[MediaClip]:
    if isinstance(item, MediaClip):
        return item if item.path.exists() else None
    if isinstance(item, Path) and item.exists() and (is_image(item) or is_video(item)):
        return MediaClip(path=item, kind='image' if is_image(item) else 'video', order=order)
    return None


def _clip_duration(clip: MediaClip, fallback: float) -> float:
    if is_image(clip.path):
        return max(0.5, min(20.0, float(clip.image_seconds or fallback)))
    start = max(0.0, float(clip.video_start or 0.0))
    end = max(0.0, float(clip.video_end or 0.0))
    if end > start + 0.3:
        return max(0.5, min(30.0, end - start))
    return max(1.0, min(12.0, fallback))


def _concat_escape(path: Path) -> str:
    return str(path.resolve()).replace("'", "'\\''")


def _render_clip_to_temp(clip: MediaClip, duration: float, output_path: Path, w: int, h: int, fps: int) -> tuple[Optional[Path], Optional[str]]:
    """Render one material into a small normalized mp4.

    A single FFmpeg filter graph with many inputs can kill the Render free instance.
    Rendering clips one by one uses much less memory and avoids browser `Failed to fetch`.
    """
    duration = max(0.6, min(30.0, float(duration or 1.0)))
    vf = (
        f"scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h},setsar=1,fps={fps},format=yuv420p"
    )
    if is_image(clip.path):
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-loop", "1", "-t", f"{duration:.2f}", "-i", str(clip.path),
            "-vf", vf,
            "-an",
            *_video_codec_args(),
            str(output_path),
        ]
    else:
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
        start = max(0.0, float(clip.video_start or 0.0))
        if start > 0:
            cmd += ["-ss", f"{start:.2f}"]
        cmd += [
            "-t", f"{duration:.2f}", "-i", str(clip.path),
            "-vf", vf,
            "-an",
            *_video_codec_args(),
            str(output_path),
        ]
    proc = run_cmd(cmd, timeout=max(120, int(duration * 12)))
    if proc.returncode != 0 or not output_path.exists() or output_path.stat().st_size < 2048:
        return None, proc.stderr[-800:] or 'unknown ffmpeg error'
    return output_path, None


def build_video_base(asset_paths: Iterable[Union[Path, MediaClip]], duration: float, output_path: Path) -> Tuple[Path, List[str]]:
    warnings: List[str] = []
    duration = max(3.0, min(float(duration), float(_env_int("COMPOSE_MAX_SECONDS", 60, 5, 180))))
    max_assets = _env_int("COMPOSE_MAX_ASSETS", 8, 1, 12)
    clips = [_coerce_clip(item, idx) for idx, item in enumerate(asset_paths)]
    valid_clips = [c for c in clips if c is not None and c.path.exists() and (is_image(c.path) or is_video(c.path))]
    valid_clips.sort(key=lambda c: c.order)
    original_count = len(valid_clips)
    valid_clips = valid_clips[:max_assets]
    if not valid_clips:
        return build_default_base(duration, output_path)

    w, h = target_size()
    fps = _env_int("COMPOSE_FPS", 18, 12, 30)
    fallback_per_duration = max(1.5, duration / max(1, len(valid_clips)))
    task = uuid.uuid4().hex[:10]
    tmp_dir = output_path.parent.parent / "tmp" if output_path.parent.name == "outputs" else output_path.parent
    tmp_dir.mkdir(parents=True, exist_ok=True)

    normalized_paths: list[Path] = []
    used_duration = 0.0
    for idx, clip in enumerate(valid_clips):
        remaining = max(0.8, duration - used_duration)
        if remaining <= 0.8:
            break
        clip_duration = min(_clip_duration(clip, fallback_per_duration), remaining)
        rendered = tmp_dir / f"clip_{task}_{idx:02d}.mp4"
        rendered_path, err = _render_clip_to_temp(clip, clip_duration, rendered, w, h, fps)
        if rendered_path:
            normalized_paths.append(rendered_path)
            used_duration += clip_duration
        else:
            warnings.append(f"素材 {idx + 1} 预处理失败，已跳过：{err}")

    if original_count > len(valid_clips):
        warnings.append(f"为保证后端稳定，本次最多使用前 {len(valid_clips)} 个素材；更多素材请升级后端或降低时长。")

    if not normalized_paths:
        warnings.append("所有素材预处理失败，已降级默认背景，避免服务崩溃。")
        return build_default_base(duration, output_path)

    concat_file = tmp_dir / f"concat_{task}.txt"
    # 如果素材总时长短于配音时长，循环素材列表补足整条音频，避免视频只出现前几段就结束。
    target_duration = max(3.0, duration)
    repeated: list[Path] = []
    loop_budget = max(1, int(math.ceil(target_duration / max(0.5, used_duration or target_duration))))
    for _ in range(min(loop_budget, 20)):
        repeated.extend(normalized_paths)
        if len(repeated) >= 80:
            break
    concat_file.write_text("".join(f"file '{_concat_escape(p)}'\n" for p in repeated), encoding="utf-8")

    # First try stream-copy concat because all temporary clips have the same codec/size/fps.
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_file),
        "-t", f"{target_duration:.2f}",
        "-c", "copy",
        str(output_path),
    ]
    proc = run_cmd(cmd, timeout=max(180, int(target_duration * 8)))
    if proc.returncode != 0 or not output_path.exists() or output_path.stat().st_size < 4096:
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "concat", "-safe", "0", "-i", str(concat_file),
            "-t", f"{target_duration:.2f}",
            *_video_codec_args(),
            str(output_path),
        ]
        proc = run_cmd(cmd, timeout=max(240, int(target_duration * 12)))

    try:
        concat_file.unlink(missing_ok=True)
        for item in normalized_paths:
            item.unlink(missing_ok=True)
    except Exception:
        pass

    if proc.returncode == 0 and output_path.exists() and output_path.stat().st_size >= 4096:
        return output_path, warnings

    warnings.append(f"素材合成失败，已降级默认背景：{proc.stderr[-1000:]}")
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
    *,
    subtitle_size: int = 18,
    subtitle_margin_v: int = 70,
    subtitle_position: str = 'bottom_safe',
) -> List[str]:
    warnings: List[str] = []
    w, h = target_size()
    vf = f"scale={w}:{h},format=yuv420p"
    if subtitle_path and subtitle_path.exists():
        sub_path = ffmpeg_subtitle_path(subtitle_path)
        font_size = max(12, min(36, int(subtitle_size or 18)))
        margin_v = max(20, min(320, int(subtitle_margin_v or 70)))
        if subtitle_position == 'middle_low':
            margin_v = max(margin_v, 220)
        elif subtitle_position == 'center':
            margin_v = max(margin_v, 360)
        # 默认放底部安全区：不压脸；用半透明描边保证不同素材上可读。
        style = f"FontName=Noto Sans CJK SC,FontSize={font_size},PrimaryColour=&H00FFFFFF,OutlineColour=&H70000000,BorderStyle=1,Outline=2.4,Shadow=0.7,Alignment=2,MarginV={margin_v},Bold=1"
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

    proc = run_cmd(cmd, timeout=max(240, int(duration * 14)))
    if proc.returncode == 0:
        return warnings

    warnings.append(f"字幕烧录失败，已降级为无字幕视频：{proc.stderr[-1000:]}")
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
    proc2 = run_cmd(cmd, timeout=max(240, int(duration * 12)))
    if proc2.returncode != 0:
        raise RuntimeError(f"最终视频合成失败：{proc2.stderr[-1500:]}")
    return warnings


async def compose_video(
    settings: Settings,
    script: str,
    asset_paths: Iterable[Union[Path, MediaClip]],
    duration_seconds: int,
    audio_path: Optional[Path] = None,
    voice: Optional[str] = None,
    rate: Optional[str] = None,
    subtitle_segments: Optional[list[dict[str, Any]]] = None,
    subtitle_size: int = 18,
    subtitle_margin_v: int = 70,
    subtitle_position: str = 'bottom_safe',
) -> VideoResult:
    warnings: List[str] = []

    if audio_path is None or not audio_path.exists():
        audio_path, audio_duration, tts_warning = await synthesize_tts(settings, script, voice=voice, rate=rate)
        if tts_warning:
            warnings.append(tts_warning)
    else:
        audio_duration = probe_duration(audio_path)

    duration_cap = float(_env_int("COMPOSE_MAX_SECONDS", 60, 5, 180))
    # 视频时长优先跟音频走，避免“素材时长输入”和口播时长不一致导致字幕/语音错位。
    duration = max(audio_duration or 0, 5.0)
    if not audio_duration:
        duration = max(float(duration_seconds), 5.0)
    if duration > duration_cap:
        warnings.append(f"为避免 Render 免费实例合成超时/爆内存，本次视频时长从 {duration:.1f}s 限制为 {duration_cap:.1f}s。")
        duration = duration_cap

    task_id = uuid.uuid4().hex
    base_video = settings.tmp_dir / f"base_{task_id}.mp4"
    subtitle_path = settings.outputs_dir / f"sub_{task_id}.srt"
    output_video = settings.outputs_dir / f"video_{task_id}.mp4"

    create_srt(script, duration, subtitle_path, subtitle_segments=subtitle_segments)
    base_video, base_warnings = build_video_base(list(asset_paths), duration, base_video)
    warnings.extend(base_warnings)
    warnings.extend(burn_subtitles_and_audio(
        base_video,
        subtitle_path,
        audio_path,
        output_video,
        duration,
        subtitle_size=subtitle_size,
        subtitle_margin_v=subtitle_margin_v,
        subtitle_position=subtitle_position,
    ))

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
