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




_DEFAULT_HIGHLIGHT_WORDS = ['第二家园', 'MM2H', '税费', '预算', '国际学校', '吉隆坡', '新山', '避坑', '风险', '流程', '身份', '资产配置', '养老', '子女教育', '私信', '报告', '马来西亚']

def _subtitle_keywords(raw: str = '', script: str = '') -> list[str]:
    words: list[str] = []
    for item in re.split(r'[,，、/\s]+', raw or ''):
        item = clean_subtitle_text(item)
        if item and len(item) >= 2 and item not in words:
            words.append(item)
    # AI/前端没传时，后端兜底从业务高频词里自动识别。
    for item in _DEFAULT_HIGHLIGHT_WORDS:
        if item in (script or '') and item not in words:
            words.append(item)
    return words[:12]


def _apply_srt_emphasis(text: str, preset: str = 'douyin_boss', keywords: Optional[list[str]] = None) -> str:
    if not text or not keywords:
        return text
    color = '#FFD84D' if preset != 'clean_trust' else '#FFFFFF'
    if preset == 'cta_pop':
        color = '#FF3B30'
    out = text
    for word in sorted([w for w in keywords if w and w in out], key=len, reverse=True):
        safe = re.escape(word)
        out = re.sub(safe, f'<font color="{color}"><b>{word}</b></font>', out, count=1)
    return out

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


def _append_srt_line(lines: list[str], index: int, start: float, end: float, text: str, *, preset: str = 'douyin_boss', keywords: Optional[list[str]] = None) -> int:
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
        line_text = _apply_srt_emphasis(chunks[0], preset, keywords)
        lines.append(f"{index}\n{fmt_srt_time(start)} --> {fmt_srt_time(end)}\n{line_text}\n")
        return index + 1
    weights = [max(2, len(re.sub(r'[，,、；;：:！？!?]', '', c))) for c in chunks]
    total_weight = max(1, sum(weights))
    cursor = start
    for chunk, weight in zip(chunks, weights):
        span = max(0.35, (end - start) * weight / total_weight)
        next_end = min(end, cursor + span)
        if next_end <= cursor + 0.2:
            next_end = min(end, cursor + 0.35)
        line_text = _apply_srt_emphasis(chunk, preset, keywords)
        lines.append(f"{index}\n{fmt_srt_time(cursor)} --> {fmt_srt_time(next_end)}\n{line_text}\n")
        cursor = next_end
        index += 1
    return index




def _env_float(name: str, default: float, low: float, high: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except Exception:
        value = default
    return max(low, min(high, value))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _weighted_text_segments(script: str, duration: float) -> list[dict[str, Any]]:
    chunks = subtitle_chunks(script) or split_script(script)
    if not chunks:
        return []
    duration = max(float(duration or 0), len(chunks) * 0.9, 1.0)
    weights = [max(3, len(re.sub(r'[，,、；;：:！？!?。．\.\s]', '', chunk))) for chunk in chunks]
    total_weight = max(1, sum(weights))
    cursor = 0.0
    out: list[dict[str, Any]] = []
    for chunk, weight in zip(chunks, weights):
        span = max(0.75, duration * weight / total_weight)
        start = cursor
        end = min(duration, cursor + span)
        cursor = end
        out.append({'text': chunk, 'start': start, 'end': end})
    return out


def _normalize_subtitle_segments(script: str, duration: float, subtitle_segments: Optional[list[dict[str, Any]]] = None) -> list[dict[str, Any]]:
    """Build stable subtitle timings and compensate late drift.

    The front-end/TTS segment durations are sometimes estimated per line. In a long
   口播, small errors accumulate and the later subtitles become slow. This function:
    1. rescales segment time to the real final audio duration;
    2. applies a small progressive lead, so later subtitles appear earlier;
    3. removes isolated punctuation and fixes overlaps.

    Environment knobs:
    - SUBTITLE_GLOBAL_LEAD_MS, default 120
    - SUBTITLE_PROGRESSIVE_LEAD_MS, default 650
    - SUBTITLE_TIMING_SCALE, default auto
    """
    duration = max(float(duration or 0), 1.0)
    raw_segments = subtitle_segments or []
    # 如果字幕仍然偏慢，可在 Render 设置 SUBTITLE_FORCE_WEIGHTED_TIMELINE=true，
    # 直接按最终音频长度和文案字数重建时间轴，绕开前端旧时间轴累计误差。
    if os.getenv('SUBTITLE_FORCE_WEIGHTED_TIMELINE', '').strip().lower() in {'1', 'true', 'yes', 'on'}:
        return _weighted_text_segments(script, duration)
    segments: list[dict[str, Any]] = []

    for seg in raw_segments:
        if not isinstance(seg, dict):
            continue
        text = clean_subtitle_text(str(seg.get('text') or ''))
        if not text:
            continue
        start = max(0.0, _safe_float(seg.get('start'), 0.0))
        end = max(0.0, _safe_float(seg.get('end'), 0.0))
        if end <= start:
            dur = max(0.55, _safe_float(seg.get('duration'), 0.0))
            end = start + dur
        # Ignore obviously broken segment timings that are far outside the audio.
        if start > duration * 1.8:
            continue
        segments.append({'text': text, 'start': start, 'end': end})

    # If no reliable timing came from TTS/front-end, estimate from the final audio length.
    if len(segments) < 1:
        segments = _weighted_text_segments(script, duration)

    if not segments:
        return []

    segments.sort(key=lambda x: (x['start'], x['end']))

    last_end = max((_safe_float(x.get('end'), 0.0) for x in segments), default=duration)
    if last_end <= 0:
        last_end = duration
    auto_scale = duration / last_end if last_end else 1.0
    scale_env = os.getenv('SUBTITLE_TIMING_SCALE', '').strip().lower()
    if scale_env and scale_env not in {'auto', '0'}:
        try:
            scale = float(scale_env)
        except Exception:
            scale = auto_scale
    else:
        # 终极修复：只要前端/TTS 给了时间轴，就统一按最终音频真实时长缩放。
        # 以前只有偏差 >0.45s 才缩放，长视频会出现“前面还行、后面越来越慢”。
        scale = auto_scale if 0.45 <= auto_scale <= 1.95 else 1.0

    global_lead = _env_float('SUBTITLE_GLOBAL_LEAD_MS', 160.0, 0.0, 1000.0) / 1000.0
    progressive_lead = _env_float('SUBTITLE_PROGRESSIVE_LEAD_MS', 950.0, 0.0, 2500.0) / 1000.0

    shifted: list[dict[str, Any]] = []
    for seg in segments:
        start = _safe_float(seg.get('start'), 0.0) * scale
        end = _safe_float(seg.get('end'), start + 0.8) * scale
        if end <= start:
            end = start + 0.8
        progress = min(1.0, max(0.0, start / max(duration, 0.1)))
        lead = global_lead + progressive_lead * progress
        # Shift later subtitles earlier more aggressively to counter cumulative TTS pauses.
        start = max(0.0, start - lead)
        end = max(start + 0.45, end - lead)
        if start >= duration:
            continue
        end = min(duration, end)
        shifted.append({'text': clean_subtitle_text(seg.get('text', '')), 'start': start, 'end': end})

    shifted = [x for x in shifted if x['text']]
    if not shifted:
        return []

    # Resolve overlaps by shortening the previous caption, not by delaying the next caption.
    for i in range(len(shifted) - 1):
        cur = shifted[i]
        nxt = shifted[i + 1]
        if cur['end'] > nxt['start'] - 0.04:
            cur['end'] = max(cur['start'] + 0.35, nxt['start'] - 0.04)
    for item in shifted:
        if item['end'] <= item['start'] + 0.25:
            item['end'] = min(duration, item['start'] + 0.55)
    return shifted
def create_srt(script: str, duration: float, output_path: Path, subtitle_segments: Optional[list[dict[str, Any]]] = None, subtitle_style_preset: str = 'douyin_boss', subtitle_keywords: str = '') -> None:
    lines: List[str] = []
    index = 1
    normalized_segments = _normalize_subtitle_segments(script, duration, subtitle_segments=subtitle_segments)
    keywords = _subtitle_keywords(subtitle_keywords, script)
    for seg in normalized_segments:
        index = _append_srt_line(lines, index, float(seg['start']), float(seg['end']), str(seg['text']), preset=subtitle_style_preset, keywords=keywords)
    if not lines:
        index = _append_srt_line(lines, index, 0.0, max(1.0, duration), script[:24] or ' ', preset=subtitle_style_preset, keywords=keywords)
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




def _ass_color_from_hex(hex_color: str, alpha: str = '00') -> str:
    """Convert #RRGGBB to ASS &HAABBGGRR."""
    value = (hex_color or '#ffffff').strip().lstrip('#')
    if len(value) != 6:
        value = 'ffffff'
    rr, gg, bb = value[0:2], value[2:4], value[4:6]
    return f"&H{alpha}{bb}{gg}{rr}"


def _subtitle_force_style(preset: str, font_size: int, margin_v: int, alignment: int = 2) -> str:
    preset = (preset or 'douyin_boss').strip().lower()
    base = {
        'FontName': 'Noto Sans CJK SC',
        'FontSize': str(font_size),
        'Alignment': str(alignment),
        'MarginV': str(margin_v),
        'Bold': '1',
        'BorderStyle': '1',
        'Shadow': '0.8',
    }
    if preset == 'knowledge_highlight':
        base.update({
            'PrimaryColour': _ass_color_from_hex('#ffffff'),
            'OutlineColour': _ass_color_from_hex('#0f172a', '55'),
            'BackColour': _ass_color_from_hex('#000000', '78'),
            'Outline': '2.8',
        })
    elif preset == 'clean_trust':
        base.update({
            'PrimaryColour': _ass_color_from_hex('#ffffff'),
            'OutlineColour': _ass_color_from_hex('#111827', '48'),
            'Outline': '2.2',
            'Shadow': '0.5',
        })
    elif preset == 'cta_pop':
        base.update({
            'PrimaryColour': _ass_color_from_hex('#FFD84D'),
            'OutlineColour': _ass_color_from_hex('#111827', '28'),
            'Outline': '3.4',
            'Shadow': '1.2',
        })
    else:
        # douyin_boss: 抖音常见老板口播大字，白字黑描边，重点词由前端/AI 放到更短字幕块里显示。
        base.update({
            'PrimaryColour': _ass_color_from_hex('#ffffff'),
            'OutlineColour': _ass_color_from_hex('#000000', '30'),
            'Outline': '3.2',
            'Shadow': '0.9',
        })
    return ','.join(f'{k}={v}' for k, v in base.items())

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
    subtitle_style_preset: str = 'douyin_boss',
    subtitle_keywords: str = '',
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
        # 默认放底部安全区：不压脸；字幕样式用整套模板控制，不再让用户单独挑颜色。
        style = _subtitle_force_style(subtitle_style_preset, font_size, margin_v, alignment=2)
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
    subtitle_style_preset: str = 'douyin_boss',
    subtitle_keywords: str = '',
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

    create_srt(script, duration, subtitle_path, subtitle_segments=subtitle_segments, subtitle_style_preset=subtitle_style_preset, subtitle_keywords=subtitle_keywords)
    if subtitle_segments:
        warnings.append('字幕已按最终音频时长重新缩放，并对后半段自动提前，减少越往后越慢的问题。')
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
        subtitle_style_preset=subtitle_style_preset,
        subtitle_keywords=subtitle_keywords,
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
