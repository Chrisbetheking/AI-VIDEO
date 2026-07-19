# V10_27L_FINAL_FAL_PROMPT_PURGE
from __future__ import annotations

import base64
import html
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import requests
from fastapi import APIRouter, FastAPI
from pydantic import BaseModel, ConfigDict

from app.services.subtitle_provider import (
    get_media_duration_seconds,
    segments_to_cues,
    text_to_cues,
    upload_file_to_r2,
)

BASE_DIR = Path(os.getenv("AI_VIDEO_BACKEND_DIR", "/opt/ai-video/backend"))
WORK_DIR = BASE_DIR / "data" / "subtitle-style-library"

router = APIRouter(prefix="/api/video/subtitle-library", tags=["subtitle-library"])


def _ensure_dirs() -> None:
    WORK_DIR.mkdir(parents=True, exist_ok=True)


SUBTITLE_STYLES: list[dict[str, Any]] = [
    {
        "id": "douyin_pop",
        "name": "抖音大字弹幕款",
        "description": "短视频口播默认款：大白字、粗黑描边、轻微弹入，接近抖音/剪映口播字幕。",
        "primary": "#FFFFFF",
        "background": "transparent",
        "accent": "#FDE047",
        "ass_primary": "&H00FFFFFF",
        "ass_outline": "&H00000000",
        "ass_back": "&H00000000",
        "font_size": 82,
        "outline": 5,
        "shadow": 0,
        "margin_v": 250,
        "border_style": 1,
        "max_chars": 8,
        "max_lines": 2,
        "ass_prefix": r"{ad(70,70)}",
    },
    {
        "id": "douyin_yellow_pop",
        "name": "抖音黄字重点款",
        "description": "强钩子/避坑款：亮黄大字、黑描边、移动端很醒目。",
        "primary": "#FFE45C",
        "background": "transparent",
        "accent": "#FFFFFF",
        "ass_primary": "&H005CE4FF",
        "ass_outline": "&H00000000",
        "ass_back": "&H00000000",
        "font_size": 84,
        "outline": 5,
        "shadow": 0,
        "margin_v": 250,
        "border_style": 1,
        "max_chars": 8,
        "max_lines": 2,
        "ass_prefix": r"{ad(70,70)}",
    },
    {
        "id": "douyin_black_bubble",
        "name": "抖音黑底口播款",
        "description": "黑色半透明圆角条，大白字，适合画面复杂时保清晰。",
        "primary": "#FFFFFF",
        "background": "rgba(0,0,0,0.62)",
        "accent": "#FDE047",
        "ass_primary": "&H00FFFFFF",
        "ass_outline": "&H00000000",
        "ass_back": "&H99000000",
        "font_size": 78,
        "outline": 1,
        "shadow": 0,
        "margin_v": 235,
        "border_style": 4,
        "max_chars": 9,
        "max_lines": 2,
        "ass_prefix": r"{ad(70,70)}",
    },
    {
        "id": "real_estate_gold",
        "name": "金色地产讲解",
        "description": "专业讲房默认款：金色重点、黑色半透明底，手机端最清楚。",
        "primary": "#FFF7CC",
        "background": "rgba(20,16,8,0.72)",
        "accent": "#F6C44F",
        "ass_primary": "&H00CCF7FF",
        "ass_outline": "&H00101010",
        "ass_back": "&HAA081014",
        "font_size": 78,
        "outline": 2,
        "shadow": 0,
        "margin_v": 235,
        "border_style": 4,
        "max_chars": 9,
        "max_lines": 2,
        "ass_prefix": r"{ad(70,70)}",
    },
    {
        "id": "white_outline",
        "name": "白字黑描边",
        "description": "最稳妥的通用字幕，不挡画面，适合真实素材和 AI 素材。",
        "primary": "#FFFFFF",
        "background": "transparent",
        "accent": "#111827",
        "ass_primary": "&H00FFFFFF",
        "ass_outline": "&H00000000",
        "ass_back": "&H00000000",
        "font_size": 78,
        "outline": 4,
        "shadow": 0,
        "margin_v": 235,
        "border_style": 1,
        "max_chars": 9,
        "max_lines": 2,
        "ass_prefix": r"{ad(70,70)}",
    },
    {
        "id": "black_bar",
        "name": "黑底信息条",
        "description": "信息密度高，适合避坑、区域拆解、投资逻辑类视频。",
        "primary": "#FFFFFF",
        "background": "rgba(0,0,0,0.68)",
        "accent": "#60A5FA",
        "ass_primary": "&H00FFFFFF",
        "ass_outline": "&H00000000",
        "ass_back": "&HAA000000",
        "font_size": 74,
        "outline": 1,
        "shadow": 0,
        "margin_v": 220,
        "border_style": 4,
        "max_chars": 10,
        "max_lines": 2,
        "ass_prefix": r"{ad(70,70)}",
    },
    {
        "id": "clean_premium",
        "name": "极简高级大字",
        "description": "无底色大白字、柔和描边，适合高级感楼盘和人物画面。",
        "primary": "#FFFFFF",
        "background": "transparent",
        "accent": "#C4B5FD",
        "ass_primary": "&H00FFFFFF",
        "ass_outline": "&H0020182F",
        "ass_back": "&H00000000",
        "font_size": 78,
        "outline": 5,
        "shadow": 1,
        "margin_v": 250,
        "border_style": 1,
        "max_chars": 9,
        "max_lines": 2,
        "ass_prefix": r"{ad(70,70)}",
    },
    {
        "id": "xiaohongshu_alert",
        "name": "小红书醒目款",
        "description": "高饱和黄白大字，适合避坑、预算和清单类短视频。",
        "primary": "#FFFFFF",
        "background": "rgba(96,46,12,0.72)",
        "accent": "#FDE047",
        "ass_primary": "&H00FFFFFF",
        "ass_outline": "&H00131313",
        "ass_back": "&HAA0C2E60",
        "font_size": 82,
        "outline": 4,
        "shadow": 0,
        "margin_v": 250,
        "border_style": 4,
        "max_chars": 8,
        "max_lines": 2,
        "ass_prefix": r"{ad(70,70)}",
    },
    {
        "id": "professional_two_line",
        "name": "专业解释双行款",
        "description": "字号仍然醒目，但允许较长专业信息自然分两行。",
        "primary": "#FFFFFF",
        "background": "rgba(15,23,42,0.72)",
        "accent": "#60A5FA",
        "ass_primary": "&H00FFFFFF",
        "ass_outline": "&H00000000",
        "ass_back": "&HAA2A170F",
        "font_size": 74,
        "outline": 2,
        "shadow": 0,
        "margin_v": 230,
        "border_style": 4,
        "max_chars": 10,
        "max_lines": 2,
        "ass_prefix": r"{ad(70,70)}",
    },
]

CUSTOM_STYLE_KEYS = {"font_size", "outline", "shadow", "margin_v", "border_style", "max_chars", "max_lines", "ass_primary", "ass_outline", "ass_back", "ass_prefix"}

def _style(style_id: str, custom: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    base = next((dict(item) for item in SUBTITLE_STYLES if item["id"] == style_id), dict(SUBTITLE_STYLES[0]))
    for key, value in (custom or {}).items():
        if key not in CUSTOM_STYLE_KEYS:
            continue
        if key == "font_size":
            base[key] = max(72, min(150, int(value)))
        elif key == "outline":
            base[key] = max(0, min(16, int(value)))
        elif key == "shadow":
            base[key] = max(0, min(8, int(value)))
        elif key == "margin_v":
            base[key] = max(120, min(520, int(value)))
        elif key == "max_chars":
            base[key] = max(7, min(20, int(value)))
        elif key == "max_lines":
            base[key] = max(1, min(2, int(value)))
        else:
            base[key] = value
    return base


def _ffmpeg_path(path: Path) -> str:
    value = str(path)
    value = value.replace("\\", "\\\\")
    value = value.replace(":", "\\:")
    value = value.replace("'", "\\'")
    return value


def _download_to_tmp(url: str) -> Path:
    _ensure_dirs()
    parsed = urlparse(url)
    suffix = Path(parsed.path).suffix or ".mp4"
    target = WORK_DIR / f"input_{uuid.uuid4().hex[:12]}{suffix}"
    with requests.get(url, stream=True, timeout=180) as resp:
        resp.raise_for_status()
        with target.open("wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
    return target


def _ass_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds or 0))
    cs = int(round((seconds - int(seconds)) * 100))
    total = int(seconds)
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"



def _to_cn_digits(text: str) -> str:
    table = str.maketrans({"0":"零","1":"一","2":"二","3":"三","4":"四","5":"五","6":"六","7":"七","8":"八","9":"九"})
    return str(text or "").translate(table)


def _strip_subtitle_punctuation(text: str) -> str:
    value = str(text or "").replace("\\N", " ").replace("\\n", " ").replace("\\r", " ").replace("\n", " ").replace("\r", " ")
    value = re.sub(r"\s+", "", _to_cn_digits(value).strip())
    # 纯文字字幕：去掉中英文标点，把 3/5/10 这种数字转成中文，避免口播字幕像 PPT。
    value = re.sub(r"[，。！？、；：,.!?;:\"'“”‘’（）()【】\[\]《》<>/\\|·•…—_-]+", "", value)
    return value.strip()


def _clean_keyword(value: str) -> str:
    v = _strip_subtitle_punctuation(value)
    bad = ["评论区答疑模板", "数字人模板", "OpenClaw", "内容大脑", "R2素材", "类型", "模式", "用途", "模板", "规则", "字幕库", "素材库"]
    if any(b.lower() in v.lower() for b in bad):
        return ""
    if re.fullmatch(r"\d{1,3}", v):
        return ""
    if len(v) < 2 or len(v) > 10:
        return ""
    return v


def _ass_tag_for_highlight(style: dict[str, Any]) -> str:
    # V10.40.8.6-A4: color + bold only. Never enlarge glyph width.
    return r"{\1c&H003FE8FF&\b1}"

def _ass_tag_reset(style: dict[str, Any]) -> str:
    primary = str(style.get("ass_primary") or "&H00FFFFFF")
    if not primary.endswith("&"):
        primary += "&"
    return r"{\1c" + primary + r"\b0\fscx100\fscy100}"

def _apply_keyword_highlight(text: str, keywords: Optional[list[str]], style: dict[str, Any]) -> str:
    value = text
    kws = []
    seen = set()
    for k in keywords or []:
        ck = _clean_keyword(str(k))
        if ck and ck.lower() not in seen:
            seen.add(ck.lower())
            kws.append(ck)
    kws.sort(key=len, reverse=True)
    hi = _ass_tag_for_highlight(style)
    reset = _ass_tag_reset(style)
    # 逐词替换，避免重复套标签。
    for kw in kws[:20]:
        try:
            value = re.sub(re.escape(kw), lambda m: hi + m.group(0) + reset, value)
        except Exception:
            pass
    return value

def _balanced_wrap_no_loss(
    value: str,
    max_chars: int,
) -> list[str]:
    value = str(value or "")
    max_chars = max(6, min(int(max_chars or 8), 12))

    if len(value) <= max_chars:
        return [value]

    if len(value) > max_chars * 2:
        raise ValueError("字幕卡超过双行安全长度")

    lower = max(1, len(value) - max_chars)
    upper = min(max_chars, len(value) - 1)
    midpoint = len(value) / 2.0
    boundaries = set("的了和与但也还就再才是把在对按先每要会可")

    candidates: list[tuple[float, int]] = []
    for pos in range(lower, upper + 1):
        left = value[pos - 1]
        right = value[pos] if pos < len(value) else ""
        score = abs(pos - midpoint)
        if left in boundaries or right in boundaries:
            score -= 1.5
        candidates.append((score, pos))

    split_at = min(candidates)[1]
    lines = [value[:split_at], value[split_at:]]

    if any(len(line) > max_chars for line in lines):
        raise ValueError("字幕换行后仍然超出安全字符数")

    return lines


def _safe_subtitle_cards(text: str, max_chars: int) -> list[str]:
    value = _strip_subtitle_punctuation(str(text or ""))
    if not value:
        return []

    max_chars = max(6, min(int(max_chars or 8), 12))
    card_limit = max_chars * 2
    boundaries = set("的了和与但也还就再才是把在对按先每要会可")
    cards: list[str] = []
    remaining = value

    while len(remaining) > card_limit:
        split_at = card_limit

        for pos in range(
            card_limit,
            max(max_chars, card_limit - 5) - 1,
            -1,
        ):
            left = remaining[pos - 1]
            right = remaining[pos] if pos < len(remaining) else ""
            if left in boundaries or right in boundaries:
                split_at = pos
                break

        cards.append(remaining[:split_at])
        remaining = remaining[split_at:]

    if remaining:
        cards.append(remaining)

    if any(len(card) > card_limit for card in cards):
        raise ValueError("字幕拆卡后仍超出安全长度")

    return cards


def _expand_cues_for_safe_layout(
    cues: list[dict[str, Any]],
    style: dict[str, Any],
) -> list[dict[str, Any]]:
    max_chars = int(style.get("max_chars") or 8)
    result: list[dict[str, Any]] = []

    for cue in cues:
        start = max(0.0, float(cue.get("start") or 0))
        end = max(start + 0.05, float(cue.get("end") or start + 0.05))
        cards = _safe_subtitle_cards(
            str(cue.get("text") or ""),
            max_chars=max_chars,
        )

        if not cards:
            continue

        total_chars = max(1, sum(len(card) for card in cards))
        cursor = start
        consumed = 0

        for index, card in enumerate(cards):
            consumed += len(card)

            if index == len(cards) - 1:
                card_end = end
            else:
                card_end = start + (end - start) * consumed / total_chars

            result.append(
                {
                    **cue,
                    "text": card,
                    "start": round(cursor, 3),
                    "end": round(max(cursor + 0.05, card_end), 3),
                }
            )
            cursor = card_end

    return result

def _ass_escape(text: str, max_chars: int = 9, keywords: Optional[list[str]] = None, style: Optional[dict[str, Any]] = None) -> str:
    style = style or {}
    value = _strip_subtitle_punctuation(str(text or ""))
    value = value.replace("{", "（").replace("}", "）")
    max_chars = max(7, min(int(max_chars or 9), 20))

    # V10.40.8.3.2: max_chars 只控制换行，绝不能再切掉字幕尾部。
    # 即使样式原来声明 max_lines=1，超长口播也自动安全换成两行。
    wrapped = _balanced_wrap_no_loss(value, max_chars=max_chars)
    value = r"\N".join(wrapped)

    value = _apply_keyword_highlight(value, keywords=keywords, style=style)
    return value

def _make_ass(cues: list[dict[str, Any]], style_id: str, prefix: str = "subtitle_style", keywords: Optional[list[str]] = None, subtitle_style: Optional[dict[str, Any]] = None) -> Path:
    _ensure_dirs()
    # V10_40_8_6_A4_SUBTITLE_SAFE_LAYOUT
    style = _style(style_id, subtitle_style)
    cues = _expand_cues_for_safe_layout(cues, style)
    ass_path = WORK_DIR / f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.ass"
    font = os.getenv("AI_VIDEO_SUBTITLE_FONT", "Noto Sans CJK SC")
    header = f"""[Script Info]
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{style['font_size']},{style['ass_primary']},&H00FFFFFF,{style['ass_outline']},{style['ass_back']},-1,0,0,0,100,100,0,0,{style['border_style']},{style['outline']},{style['shadow']},2,96,96,{style['margin_v']},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    max_chars = int(style.get("max_chars") or 12)
    ass_prefix = str(style.get("ass_prefix") or "")
    for cue in cues:
        start = _ass_time(float(cue.get("start") or 0))
        end = _ass_time(float(cue.get("end") or 0))
        text = ass_prefix + _ass_escape(str(cue.get("text") or ""), max_chars=max_chars, keywords=keywords, style=style)
        # ASS Events 必须严格包含 10 个字段：
        # Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text。
        # 旧实现缺少 Effect/Text 前的占位字段，导致 \t / \fscx / \fscy 控制标签被当作普通文字烧进视频。
        lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}\n")

    content = "".join(lines)
    for line in content.splitlines():
        if not line.startswith("Dialogue:"):
            continue
        fields = line.split(":", 1)[1].lstrip().split(",", 9)
        if len(fields) != 10:
            raise ValueError(f"ASS Dialogue 字段数量错误：{len(fields)}，必须为 10")
        if not fields[9].strip():
            raise ValueError("ASS Dialogue Text 字段为空")

    ass_path.write_text(content, encoding="utf-8")
    return ass_path


# V10.40.8.5.3 EXACT TTS SUBTITLE
def _make_cues(
    text: str = "",
    segments: Optional[list[dict[str, Any]]] = None,
    duration: float = 12.0,
) -> list[dict[str, Any]]:
    cues: list[dict[str, Any]] = []
    cursor = 0.0

    if segments:
        for item in segments:
            if not isinstance(item, dict):
                continue

            raw_text = str(item.get("text") or "").strip()

            if not raw_text:
                continue

            start_value = (
                item.get("start")
                if item.get("start") is not None
                else item.get("start_time")
            )

            end_value = (
                item.get("end")
                if item.get("end") is not None
                else item.get("end_time")
            )

            duration_value = item.get("duration")

            try:
                if start_value is None:
                    start_time = cursor
                else:
                    start_time = float(start_value)

                if end_value is not None:
                    end_time = float(end_value)
                elif duration_value is not None:
                    end_time = start_time + float(duration_value)
                else:
                    continue
            except (TypeError, ValueError):
                continue

            if item.get("start_ms") is not None:
                start_time = float(item["start_ms"]) / 1000.0

            if item.get("end_ms") is not None:
                end_time = float(item["end_ms"]) / 1000.0

            start_time = max(0.0, start_time)
            end_time = min(float(duration), end_time)

            if end_time <= start_time:
                continue

            clean_text = re.sub(r"\s+", "", raw_text)

            clean_text = re.sub(
                r"[，。！？、；：,.!?;:\"'“”‘’（）()〖〗\[\]《》<>/\\|·•…—_-]+",
                "",
                clean_text,
            ).strip()

            if not clean_text:
                continue

            cues.append(
                {
                    "index": len(cues) + 1,
                    "text": clean_text,
                    "start": round(start_time, 3),
                    "end": round(end_time, 3),
                    "duration": round(end_time - start_time, 3),
                    "exact_tts": True,
                }
            )

            cursor = end_time

    if not cues:
        cues = text_to_cues(
            text,
            duration=duration,
            max_chars=18,
        )

    if not cues:
        raise ValueError(
            "没有可生成字幕的文案或 script_segments"
        )

    return cues


def burn_subtitles_with_style_and_upload(
    video_url: str = "",
    video_path: str = "",
    text: str = "",
    segments: Optional[list[dict[str, Any]]] = None,
    duration: Optional[float] = None,
    style_id: str = "real_estate_gold",
    keywords: Optional[list[str]] = None,
    prefix: str = "wizard_subtitle",
    object_key: str = "",
    subtitle_style: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    _ensure_dirs()
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg 不可用，无法烧录字幕")

    input_path = _download_to_tmp(video_url) if video_url else Path(video_path)
    if not input_path.exists():
        raise FileNotFoundError(f"视频文件不存在: {input_path}")
    media_duration = float(duration or get_media_duration_seconds(input_path, default=12.0))
    cues = _make_cues(text=text, segments=segments, duration=media_duration)
    ass_path = _make_ass(cues, style_id=style_id, prefix=prefix, keywords=keywords, subtitle_style=subtitle_style)
    output_path = WORK_DIR / f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.mp4"

    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(input_path),
        "-vf", f"ass='{_ffmpeg_path(ass_path)}'",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
        "-c:a", "copy",
        str(output_path),
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=900)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or "ffmpeg ass subtitle burn failed")

    if not object_key:
        object_key = f"videos/subtitled/{time.strftime('%Y/%m/%d')}/{uuid.uuid4().hex}_{output_path.name}"
    upload = upload_file_to_r2(output_path, object_key=object_key)
    return {
        "ok": True,
        "video_url": upload["url"],
        "url": upload["url"],
        "style_id": style_id,
        "style": _style(style_id, subtitle_style),
        "duration": media_duration,
        "cues": cues,
        "ass_path": str(ass_path),
        "output_path": str(output_path),
        "r2": upload,
    }


def _preview_svg(style: dict[str, Any]) -> str:
    primary = style.get("primary") or "#fff"
    bg = (style.get("background") or "rgba(0,0,0,.65)").replace("rgba", "rgb")
    accent = style.get("accent") or "#f59e0b"
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="720" height="1280" viewBox="0 0 720 1280">
<defs><linearGradient id="g" x1="0" x2="1" y1="0" y2="1"><stop stop-color="#dbeafe"/><stop offset="1" stop-color="#f5d0fe"/></linearGradient></defs>
<rect width="720" height="1280" fill="url(#g)"/>
<rect x="80" y="940" width="560" height="110" rx="24" fill="{html.escape(bg)}" opacity="0.88"/>
<rect x="140" y="1038" width="440" height="8" rx="4" fill="{html.escape(accent)}"/>
<text x="360" y="985" text-anchor="middle" font-family="Arial, sans-serif" font-size="48" font-weight="800" fill="{html.escape(primary)}">吉隆坡买房，先看区域和用途</text>
<text x="360" y="1026" text-anchor="middle" font-family="Arial, sans-serif" font-size="38" font-weight="700" fill="{html.escape(primary)}">预算、出租、转手要分开判断</text>
</svg>'''
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")


class PreviewRequest(BaseModel):
    style_id: str = "real_estate_gold"
    text: str = "吉隆坡买房，先看区域和用途"


class BurnRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    video_url: str = ""
    video_path: str = ""
    text: str = ""
    segments: list[dict[str, Any]] = []
    duration: Optional[float] = None
    style_id: str = "real_estate_gold"
    keywords: list[str] = []
    prefix: str = "wizard_subtitle_manual"
    subtitle_style: dict[str, Any] = {}


@router.get("/health")
def health() -> dict[str, Any]:
    _ensure_dirs()
    return {"ok": True, "provider": "subtitle_style_library_v10_40_7", "style_count": len(SUBTITLE_STYLES), "punctuation_free": True, "keyword_highlight_scale": True, "large_douyin_font": True, "larger_keyword_highlight": True, "one_line_no_punctuation": True, "digits_converted_to_chinese": True, "work_dir": str(WORK_DIR)}


@router.get("/styles")
def styles() -> dict[str, Any]:
    return {"ok": True, "styles": [{**item, "preview_svg": _preview_svg(item)} for item in SUBTITLE_STYLES]}


@router.post("/preview")
def preview(req: PreviewRequest) -> dict[str, Any]:
    style = _style(req.style_id)
    return {"ok": True, "style": style, "preview_svg": _preview_svg(style)}


@router.post("/burn-upload")
def burn_upload(req: BurnRequest) -> dict[str, Any]:
    return burn_subtitles_with_style_and_upload(
        video_url=req.video_url,
        video_path=req.video_path,
        text=req.text,
        segments=req.segments,
        duration=req.duration,
        style_id=req.style_id,
        keywords=req.keywords,
        prefix=req.prefix,
        subtitle_style=req.subtitle_style,
    )


def install_subtitle_style_library(app: FastAPI) -> None:
    app.include_router(router)
