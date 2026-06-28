from __future__ import annotations

import math
import shlex
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.config import Settings
from app.services.effect_planner import (
    StickerCue,
    TimedSegment,
    clean_narration_text,
    plan_stickers,
    remove_repeated_intro,
    split_narration,
    wrap_cn,
)
from app.services.tts import probe_duration, synthesize_tts

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}



@dataclass
class MediaClip:
    """Material clip for compose-video. Path is the resolved local file."""
    path: Path
    order: int = 0
    kind: str = ""
    url: str = ""
    filename: str = ""
    source_type: str = ""
    image_seconds: float = 2.8
    video_start: float = 0.0
    video_end: float = 0.0


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


def fmt_ass_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    cs = int(round((seconds - math.floor(seconds)) * 100))
    total = int(math.floor(seconds))
    s = total % 60
    m = (total // 60) % 60
    h = total // 3600
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def ffmpeg_filter_path(path: Path) -> str:
    value = str(path.resolve()).replace("\\", "/")
    return value.replace(":", "\\:").replace("'", "\\'")


def _ass_escape(text: str) -> str:
    return str(text).replace("{", "").replace("}", "").replace("\n", r"\N")


def _ass_color_for_tone(tone: str) -> str:
    # ASS color: &HAABBGGRR. These are text colors, not random heavy stickers.
    return {
        "warning": "&H0000D7FF",  # yellow-ish
        "money": "&H0045F6A3",    # green-ish
        "school": "&H00FFE59A",
        "home": "&H00FFD08A",
        "location": "&H00FFFFFF",
        "legal": "&H00A8E6FF",
        "soft": "&H00FFFFFF",
    }.get((tone or "soft").lower(), "&H00FFFFFF")



def create_srt(script: str, total_seconds: float, output_path: Path) -> None:
    """Generate a simple SRT file from a script."""
    parts = remove_repeated_intro(split_narration(script, max_chars=24)) or [" "]
    weights = [max(4, len(p)) for p in parts]
    total_w = sum(weights) or 1
    total_seconds = max(float(total_seconds or 0), len(parts) * 1.1)
    lines: List[str] = []
    cursor = 0.0
    for idx, (part, w) in enumerate(zip(parts, weights), start=1):
        dur = max(0.9, total_seconds * w / total_w)
        start = cursor
        end = total_seconds if idx == len(parts) else min(total_seconds, cursor + dur)
        start_ts = fmt_ass_time(start).replace(".", ",")
        end_ts = fmt_ass_time(end).replace(".", ",")
        lines.append(f"{idx}")
        lines.append(f"{start_ts} --> {end_ts}")
        lines.append(part)
        lines.append("")
        cursor = end
    output_path.write_text("\n".join(lines), encoding="utf-8")


def ffmpeg_subtitle_path(path: Path) -> str:
    """Return an ffmpeg-safe subtitle path for -vf subtitles filter."""
    return str(path.resolve()).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def split_script(script: str, max_chars: int = 24) -> List[str]:
    """Split a script into sentence-level chunks for subtitles."""
    return remove_repeated_intro(split_narration(script, max_chars=max_chars)) or [" "]


def create_smart_ass(
    segments: List[TimedSegment],
    stickers: List[StickerCue],
    output_path: Path,
    font_size: int = 80,
    margin_v: int = 170,
    subtitle_keywords: str = "",
) -> None:
    """Create one ASS file containing synced subtitles + keyword text overlays.

    Keyword overlays are pure text (no black box, no BackColour, no drawtext box=1).
    They use a brief scale-up animation and fade out.
    """
    # Fallback: if font_size < 70, bump to 80.
    if font_size < 70:
        font_size = 80
    sticker_fs = max(32, int(font_size * 0.72))
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes
WrapStyle: 2

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Main,Noto Sans CJK SC,{font_size},&H00FFFFFF,&H000000FF,&HBE000000,&H00000000,-1,0,0,0,100,100,0,0,1,5,1,2,70,70,{margin_v},1
Style: Sticker,Noto Sans CJK SC,{sticker_fs},&H00FFFFFF,&H000000FF,&HAA000000,&H00000000,-1,0,0,0,100,100,0,0,1,7,2,7,30,30,30,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
""".format(font_size=font_size, margin_v=margin_v, sticker_fs=sticker_fs)
    lines: List[str] = [header]
    for seg in segments:
        if seg.end <= seg.start:
            continue
        text = _ass_escape(wrap_cn(seg.text, max_chars=14))
        override = r"{\fad(60,80)}"
        lines.append(
            f"Dialogue: 0,{fmt_ass_time(seg.start)},{fmt_ass_time(seg.end)},Main,,0,0,0,,{override}{text}\n"
        )

    for cue in stickers:
        if cue.end <= cue.start or not cue.text:
            continue
        color = _ass_color_for_tone(cue.tone)
        keyword_text = _ass_escape(cue.text)
        # Subtle sticker: small pop, fades in/out, fixed away from mouth/subtitle center.
        override = (
            r"{\an8"
            rf"\pos({int(cue.x)},{int(cue.y)})"
            r"\fad(180,320)"
            rf"\1c{color}"
            r"\t(0,200,\fscx114\fscy114)"
            r"\t(200,500,\fscx100\fscy100)"
            r"}"
        )
        lines.append(
            f"Dialogue: 2,{fmt_ass_time(cue.start)},{fmt_ass_time(cue.end)},Sticker,,0,0,0,,{override}{keyword_text}\n"
        )
    output_path.write_text("".join(lines), encoding="utf-8")


def _concat_audio_files(paths: List[Path], output: Path) -> None:
    if not paths:
        raise RuntimeError("没有可拼接的配音片段")
    list_file = output.with_suffix(".txt")
    list_file.write_text("\n".join(f"file '{str(p.resolve()).replace(chr(39), chr(39)+chr(92)+chr(39)+chr(39))}'" for p in paths), encoding="utf-8")
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file), "-c:a", "libmp3lame", "-q:a", "4", str(output)]
    proc = run_cmd(cmd, timeout=240)
    try:
        list_file.unlink(missing_ok=True)
    except Exception:
        pass
    if proc.returncode != 0:
        raise RuntimeError(f"配音分段拼接失败：{proc.stderr[-1000:]}")


async def synthesize_segmented_audio(
    settings: Settings,
    script: str,
    voice: Optional[str] = None,
    rate: Optional[str] = None,
) -> Tuple[Path, List[TimedSegment], float, List[str]]:
    """Generate TTS per sentence. This is the key fix for audio/subtitle sync."""
    warnings: List[str] = []
    parts = remove_repeated_intro(split_narration(script, max_chars=24))
    if not parts:
        parts = [" "]

    audio_parts: List[Path] = []
    timed: List[TimedSegment] = []
    cursor = 0.0
    for idx, text in enumerate(parts, start=1):
        p, duration, warning = await synthesize_tts(settings, text, voice=voice, rate=rate)
        if warning:
            warnings.append(warning)
        duration = probe_duration(p) or duration or max(1.0, len(text) / 4.5)
        audio_parts.append(p)
        timed.append(TimedSegment(index=idx, text=text, start=cursor, end=cursor + duration))
        cursor += duration

    out = settings.outputs_dir / f"tts_segments_{uuid.uuid4().hex}.mp3"
    _concat_audio_files(audio_parts, out)
    total = probe_duration(out) or cursor
    # Correct last segment if concat encoder adds tiny drift.
    if timed:
        timed[-1].end = max(timed[-1].end, total)
    return out, timed, total, warnings


def estimate_segments_for_existing_audio(script: str, total_duration: float) -> List[TimedSegment]:
    """Fallback when caller gives an existing full audio file. Less accurate than segmented TTS."""
    parts = remove_repeated_intro(split_narration(script, max_chars=24)) or [" "]
    weights = [max(4, len(p)) for p in parts]
    total_w = sum(weights) or 1
    cursor = 0.0
    segments: List[TimedSegment] = []
    total_duration = max(float(total_duration or 0), len(parts) * 1.1)
    for idx, (part, w) in enumerate(zip(parts, weights), start=1):
        dur = max(0.9, total_duration * w / total_w)
        start = cursor
        end = total_duration if idx == len(parts) else min(total_duration, cursor + dur)
        segments.append(TimedSegment(index=idx, text=part, start=start, end=end))
        cursor = end
    return segments


def build_video_base(asset_paths: List[Path], duration: float, output_path: Path) -> Tuple[Path, List[str]]:
    warnings: List[str] = []
    duration = max(3.0, duration)
    if not asset_paths:
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"color=c=0x111827:s=1080x1920:r=30:d={duration:.2f}",
            "-vf", "format=yuv420p",
            "-c:v", "libx264", "-preset", "veryfast",
            "-t", f"{duration:.2f}",
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
            # Loop short B-roll so video timeline never ends early.
            cmd += ["-stream_loop", "-1", "-t", f"{per_duration:.2f}", "-i", str(path)]

    filter_parts: List[str] = []
    video_labels: List[str] = []
    for i, _path in enumerate(valid_paths):
        label = f"v{i}"
        # 9:16 full-screen crop. No random generated objects.
        filter_parts.append(
            f"[{i}:v]scale=1080:1920:force_original_aspect_ratio=increase,"
            f"crop=1080:1920,setsar=1,fps=30,format=yuv420p[{label}]"
        )
        video_labels.append(f"[{label}]")
    filter_parts.append("".join(video_labels) + f"concat=n={len(valid_paths)}:v=1:a=0[outv]")

    cmd += [
        "-filter_complex", ";".join(filter_parts),
        "-map", "[outv]",
        "-t", f"{duration:.2f}",
        "-c:v", "libx264", "-preset", "veryfast",
        "-pix_fmt", "yuv420p",
        str(output_path),
    ]
    proc = run_cmd(cmd, timeout=900)
    if proc.returncode != 0:
        raise RuntimeError(f"素材合成失败：{proc.stderr[-1500:]}\nCMD: {' '.join(shlex.quote(c) for c in cmd)}")
    return output_path, warnings


def burn_ass_and_audio(
    base_video: Path,
    ass_path: Optional[Path],
    audio_path: Optional[Path],
    output_path: Path,
    duration: float,
) -> List[str]:
    warnings: List[str] = []
    vf = "scale=1080:1920,format=yuv420p"
    if ass_path and ass_path.exists():
        sub_path = ffmpeg_filter_path(ass_path)
        vf += f",subtitles='{sub_path}'"

    cmd = ["ffmpeg", "-y", "-i", str(base_video)]
    has_audio = bool(audio_path and audio_path.exists())
    if has_audio:
        cmd += ["-i", str(audio_path)]
    cmd += ["-vf", vf]
    if has_audio:
        # Do NOT use -shortest. It cuts the video when narration is shorter.
        cmd += ["-map", "0:v:0", "-map", "1:a:0", "-af", "apad"]
    cmd += [
        "-t", f"{duration:.2f}",
        "-c:v", "libx264", "-preset", "veryfast",
        "-c:a", "aac", "-b:a", "128k",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(output_path),
    ]
    proc = run_cmd(cmd, timeout=900)
    if proc.returncode == 0:
        return warnings

    # Fallback without subtitles, but still keep full duration.
    warnings.append(f"字幕/贴纸烧录失败，已降级为无字幕视频：{proc.stderr[-900:]}")
    cmd = ["ffmpeg", "-y", "-i", str(base_video)]
    if has_audio:
        cmd += ["-i", str(audio_path)]
    cmd += ["-vf", "scale=1080:1920,format=yuv420p"]
    if has_audio:
        cmd += ["-map", "0:v:0", "-map", "1:a:0", "-af", "apad"]
    cmd += [
        "-t", f"{duration:.2f}",
        "-c:v", "libx264", "-preset", "veryfast",
        "-c:a", "aac", "-b:a", "128k",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(output_path),
    ]
    proc2 = run_cmd(cmd, timeout=900)
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
    subtitle_segments: Optional[List[Dict[str, Any]]] = None,
    subtitle_size: int = 80,
    subtitle_margin_v: int = 170,
    subtitle_position: str = "bottom_safe",
    subtitle_style_preset: str = "douyin_boss",
    subtitle_keywords: str = "",
    keyword_sfx_enabled: bool = True,
    keyword_sfx_volume: float = 0.16,
) -> VideoResult:
    warnings: List[str] = []
    script = clean_narration_text(script)

    # Use caller-provided subtitle_segments when available (avoids re-synthesizing TTS).
    if subtitle_segments is not None and len(subtitle_segments) > 0:
        segments: List[TimedSegment] = []
        for item in subtitle_segments:
            segments.append(TimedSegment(
                index=int(item.get("index", 0)),
                text=str(item.get("text", "")),
                start=float(item.get("start", 0)),
                end=float(item.get("end", 0)),
            ))
        if audio_path and audio_path.exists():
            audio_duration = probe_duration(audio_path)
        else:
            audio_duration = segments[-1].end if segments else 5.0
    elif audio_path is None or not audio_path.exists():
        audio_path, segments, audio_duration, tts_warnings = await synthesize_segmented_audio(
            settings, script, voice=voice, rate=rate
        )
        warnings.extend(tts_warnings)
    else:
        audio_duration = probe_duration(audio_path)
        segments = estimate_segments_for_existing_audio(script, audio_duration)
        warnings.append("使用了已有整段音频：字幕只能按文本估算；想更准请不要传 audio_file_name，让系统分句生成 TTS。")

    # Final duration follows audio (narration) length. Assets stretch/fill to match.
    duration = max(audio_duration or 0, segments[-1].end if segments else 0, 5.0)

    task_id = uuid.uuid4().hex
    base_video = settings.tmp_dir / f"base_{task_id}.mp4"
    ass_path = settings.outputs_dir / f"sub_{task_id}.ass"
    output_video = settings.outputs_dir / f"video_{task_id}.mp4"

    stickers = await plan_stickers(settings, title="", script=script, segments=segments, max_stickers=6)
    create_smart_ass(segments, stickers, ass_path, font_size=subtitle_size, margin_v=subtitle_margin_v, subtitle_keywords=subtitle_keywords)

    base_video, base_warnings = build_video_base(list(asset_paths), duration, base_video)
    warnings.extend(base_warnings)
    warnings.extend(burn_ass_and_audio(base_video, ass_path, audio_path, output_video, duration))

    try:
        base_video.unlink(missing_ok=True)
    except Exception:
        pass

    if stickers:
        warnings.append(f"AI 已按内容自动加入 {len(stickers)} 个轻量贴纸提示。")

    return VideoResult(
        video_path=output_video,
        subtitle_path=ass_path,
        audio_path=audio_path,
        duration_seconds=duration,
        warnings=warnings,
    )
