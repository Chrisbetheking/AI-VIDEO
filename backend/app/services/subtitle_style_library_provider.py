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
        "id": "real_estate_gold",
        "name": "金色地产讲解",
        "description": "专业讲房默认款：金色重点、黑色半透明底，手机端最清楚。",
        "primary": "#FFF7CC",
        "background": "rgba(20,16,8,0.72)",
        "accent": "#F6C44F",
        "ass_primary": "&H00CCF7FF",
        "ass_outline": "&H00101010",
        "ass_back": "&HAA081014",
        "font_size": 58,
        "outline": 3,
        "shadow": 1,
        "margin_v": 150,
        "border_style": 4,
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
        "font_size": 56,
        "outline": 4,
        "shadow": 1,
        "margin_v": 145,
        "border_style": 1,
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
        "font_size": 52,
        "outline": 1,
        "shadow": 0,
        "margin_v": 130,
        "border_style": 4,
    },
    {
        "id": "clean_blue",
        "name": "蓝白干净款",
        "description": "适合生活日常、城市生活方式、华人区介绍。",
        "primary": "#EFF6FF",
        "background": "rgba(30,64,175,0.72)",
        "accent": "#93C5FD",
        "ass_primary": "&H00FFF6EF",
        "ass_outline": "&H00AF401E",
        "ass_back": "&HAAAF401E",
        "font_size": 54,
        "outline": 2,
        "shadow": 1,
        "margin_v": 145,
        "border_style": 4,
    },
    {
        "id": "large_yellow",
        "name": "大黄字重点款",
        "description": "适合强钩子、预算、评论区承接，视觉冲击强。",
        "primary": "#FDE047",
        "background": "rgba(17,24,39,0.78)",
        "accent": "#F97316",
        "ass_primary": "&H0047E0FD",
        "ass_outline": "&H00271811",
        "ass_back": "&HAA271811",
        "font_size": 62,
        "outline": 4,
        "shadow": 1,
        "margin_v": 155,
        "border_style": 4,
    },
]


def _style(style_id: str) -> dict[str, Any]:
    for item in SUBTITLE_STYLES:
        if item["id"] == style_id:
            return item
    return SUBTITLE_STYLES[0]


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


def _ass_escape(text: str) -> str:
    value = re.sub(r"\s+", " ", str(text or "").strip())
    value = value.replace("{", "（").replace("}", "）")
    # ASS supports \N for line break; keep lines short for 9:16.
    if len(value) > 18:
        chunks = [value[i:i+18] for i in range(0, len(value), 18)]
        value = r"\N".join(chunks[:2])
    return value


def _make_ass(cues: list[dict[str, Any]], style_id: str, prefix: str = "subtitle_style") -> Path:
    _ensure_dirs()
    style = _style(style_id)
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
Style: Default,{font},{style['font_size']},{style['ass_primary']},&H00FFFFFF,{style['ass_outline']},{style['ass_back']},-1,0,0,0,100,100,0,0,{style['border_style']},{style['outline']},{style['shadow']},2,70,70,{style['margin_v']},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for cue in cues:
        start = _ass_time(float(cue.get("start") or 0))
        end = _ass_time(float(cue.get("end") or 0))
        text = _ass_escape(str(cue.get("text") or ""))
        lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}\n")
    ass_path.write_text("".join(lines), encoding="utf-8")
    return ass_path


def _make_cues(text: str = "", segments: Optional[list[dict[str, Any]]] = None, duration: float = 12.0) -> list[dict[str, Any]]:
    if segments:
        cues = segments_to_cues(segments, duration=duration)
    else:
        cues = []
    if not cues:
        cues = text_to_cues(text, duration=duration, max_chars=18)
    if not cues:
        raise ValueError("没有可生成字幕的文案或 script_segments")
    return cues


def burn_subtitles_with_style_and_upload(
    video_url: str = "",
    video_path: str = "",
    text: str = "",
    segments: Optional[list[dict[str, Any]]] = None,
    duration: Optional[float] = None,
    style_id: str = "real_estate_gold",
    prefix: str = "wizard_subtitle",
    object_key: str = "",
) -> dict[str, Any]:
    _ensure_dirs()
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg 不可用，无法烧录字幕")

    input_path = _download_to_tmp(video_url) if video_url else Path(video_path)
    if not input_path.exists():
        raise FileNotFoundError(f"视频文件不存在: {input_path}")
    media_duration = float(duration or get_media_duration_seconds(input_path, default=12.0))
    cues = _make_cues(text=text, segments=segments, duration=media_duration)
    ass_path = _make_ass(cues, style_id=style_id, prefix=prefix)
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
        "style": _style(style_id),
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
<text x="360" y="985" text-anchor="middle" font-family="Arial, sans-serif" font-size="36" font-weight="800" fill="{html.escape(primary)}">吉隆坡买房，先看区域和用途</text>
<text x="360" y="1026" text-anchor="middle" font-family="Arial, sans-serif" font-size="28" font-weight="700" fill="{html.escape(primary)}">预算、出租、转手要分开判断</text>
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
    prefix: str = "wizard_subtitle_manual"


@router.get("/health")
def health() -> dict[str, Any]:
    _ensure_dirs()
    return {"ok": True, "provider": "subtitle_style_library_v1", "style_count": len(SUBTITLE_STYLES), "work_dir": str(WORK_DIR)}


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
        prefix=req.prefix,
    )


def install_subtitle_style_library(app: FastAPI) -> None:
    app.include_router(router)
