from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import Depends, HTTPException, Request

VERSION = "10.40.8.14-reference-kinetic-captions"
INSTALL_MARKER = "V10_40_8_14_REFERENCE_KINETIC_CAPTIONS"
_INSTALLED = False
_LOCK = threading.RLock()

EDIT_PRESETS: dict[str, dict[str, Any]] = {
    "restrained": {
        "label": "克制短句精剪",
        "description": "字幕拆成短句，轻推近与少量重点词，不使用文本框。",
        "max_major_effects_per_30s": 7,
        "min_effect_gap_seconds": 2.7,
        "zoom_strength": 0.032,
        "micro_zoom_strength": 0.010,
        "sfx_volume": 0.028,
    },
    "balanced": {
        "label": "参考节奏精剪",
        "description": "3-8 字短字幕、更多镜头、跳词和构图变化，贴近参考视频节奏。",
        "max_major_effects_per_30s": 11,
        "min_effect_gap_seconds": 1.75,
        "zoom_strength": 0.052,
        "micro_zoom_strength": 0.016,
        "sfx_volume": 0.040,
    },
    "strong": {
        "label": "强节奏短句精剪",
        "description": "更密的短句字幕、重点词与镜头变化，但不添加大块文本框。",
        "max_major_effects_per_30s": 15,
        "min_effect_gap_seconds": 1.15,
        "zoom_strength": 0.068,
        "micro_zoom_strength": 0.022,
        "sfx_volume": 0.052,
    },
}

SUBTITLE_PRESETS: dict[str, dict[str, Any]] = {
    "dynamic_white_yellow": {
        "label": "白黄短句跳词",
        "description": "白字黑描边，重点词亮黄；每屏 3-8 字，无底框。",
        "font_size": 82,
        "impact_size": 104,
        "primary": "&H00FFFFFF",
        "highlight": "&H0000E8FF",
        "accent": "&H0000A5FF",
        "outline": "&H00111111",
        "back": "&H00000000",
        "border_style": 1,
        "outline_width": 6,
        "shadow": 2,
        "margin_v": 250,
        "alignment": 2,
    },
    "dynamic_black_box": {
        "label": "橙白视觉冲击",
        "description": "取消黑底条，改为橙白短句与中心重击词。",
        "font_size": 80,
        "impact_size": 106,
        "primary": "&H00FFFFFF",
        "highlight": "&H000096FF",
        "accent": "&H00004BFF",
        "outline": "&H00111111",
        "back": "&H00000000",
        "border_style": 1,
        "outline_width": 6,
        "shadow": 2,
        "margin_v": 250,
        "alignment": 2,
    },
    "dynamic_gold_property": {
        "label": "金白地产短句",
        "description": "金色关键词配白字，适合预算、区域与资产内容，无底框。",
        "font_size": 80,
        "impact_size": 104,
        "primary": "&H00FFFFFF",
        "highlight": "&H004BC8FF",
        "accent": "&H0000D7FF",
        "outline": "&H00130F17",
        "back": "&H00000000",
        "border_style": 1,
        "outline_width": 7,
        "shadow": 2,
        "margin_v": 252,
        "alignment": 2,
    },
    "dynamic_minimal_pro": {
        "label": "极简白字口播",
        "description": "短白字、轻描边，不加底色，适合干净专业画面。",
        "font_size": 76,
        "impact_size": 96,
        "primary": "&H00FFFFFF",
        "highlight": "&H00E8D6C8",
        "accent": "&H00FFFFFF",
        "outline": "&H003A3541",
        "back": "&H00000000",
        "border_style": 1,
        "outline_width": 4,
        "shadow": 2,
        "margin_v": 248,
        "alignment": 2,
    },
    "dynamic_red_hook": {
        "label": "红黄疑问重击",
        "description": "疑问、风险和数字用红黄短词放大，不使用横向文本框。",
        "font_size": 82,
        "impact_size": 112,
        "primary": "&H00FFFFFF",
        "highlight": "&H00004BFF",
        "accent": "&H0000E8FF",
        "outline": "&H00101010",
        "back": "&H00000000",
        "border_style": 1,
        "outline_width": 7,
        "shadow": 3,
        "margin_v": 255,
        "alignment": 2,
    },
    "dynamic_dual_line": {
        "label": "清单节奏短句",
        "description": "仍以单行短句为主，清单词逐条出现，不再显示长双行。",
        "font_size": 78,
        "impact_size": 100,
        "primary": "&H00FFFFFF",
        "highlight": "&H0000D7FF",
        "accent": "&H000096FF",
        "outline": "&H00151418",
        "back": "&H00000000",
        "border_style": 1,
        "outline_width": 5,
        "shadow": 2,
        "margin_v": 245,
        "alignment": 2,
    },
}

ROLE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("hook", re.compile(r"真的|千万|一定要|别再|90%|98%|大多数|很多人|先别|记住", re.I)),
    ("question", re.compile(r"为什么|怎么|到底|是不是|吗[？?]?|疑问|问题", re.I)),
    ("turn", re.compile(r"但是|然而|其实|真正|反而|结果|却|重点是|关键是", re.I)),
    ("data", re.compile(r"\d+(?:\.\d+)?\s*(?:%|万|亿|年|个月|天|套|个|条|公里|分钟|RM|马币|人民币)?", re.I)),
    ("risk", re.compile(r"风险|避坑|不要|不能|错误|踩坑|亏|贵|陷阱|误区", re.I)),
    ("comparison", re.compile(r"对比|相比|一边|另一边|不同|区别|前者|后者|不是.*而是", re.I)),
    ("list", re.compile(r"第一|第二|第三|第四|第[一二三四五六七八九十]+|这几点|三点|四点|步骤|清单", re.I)),
    ("evidence", re.compile(r"地图|数据|截图|报告|实拍|现场|证据|规划|线路|户型图", re.I)),
    ("cta", re.compile(r"关注|评论|私信|留言|收藏|转发|找我|联系|主页", re.I)),
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _classic() -> Any:
    from app.services import existing_video_editor_v10_40_8_5 as classic

    return classic


def _data_dir(settings: Any) -> Path:
    raw = getattr(settings, "data_dir", None) or "/opt/ai-video/backend/data"
    return Path(raw)


def _work_dir(settings: Any, job_id: str) -> Path:
    path = _data_dir(settings) / "tmp" / "dynamic_edit_v2" / job_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _update_proxy(settings: Any, job_id: str, **updates: Any) -> dict[str, Any]:
    # Do not call classic._update_job here: the classic helper forcibly rewrites
    # every job version to A10-R4. Dynamic proxy jobs share the persistence file
    # for frontend compatibility, but must retain their own version and mode.
    classic = _classic()
    with classic._LOCK:
        jobs = classic._load_jobs(settings)
        item = dict(jobs.get(job_id) or {"job_id": job_id})
        item.update(updates)
        item["version"] = VERSION
        item["mode"] = "dynamic_edit_v2"
        item["updated_at"] = _now()
        jobs[job_id] = item
        classic._save_jobs(settings, jobs)
        return dict(item)


def _save_proxy(settings: Any, job: dict[str, Any]) -> None:
    classic = _classic()
    with classic._LOCK:
        jobs = classic._load_jobs(settings)
        jobs[str(job["job_id"])] = job
        classic._save_jobs(settings, jobs)


def _read_proxy(settings: Any, job_id: str) -> dict[str, Any] | None:
    classic = _classic()
    with classic._LOCK:
        return classic._load_jobs(settings).get(job_id)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _probe(path: Path) -> dict[str, Any]:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=codec_type,width,height,r_frame_rate",
        "-of",
        "json",
        str(path),
    ]
    data = json.loads(subprocess.check_output(cmd, text=True))
    streams = data.get("streams") or []
    video = next((x for x in streams if x.get("codec_type") == "video"), {})
    has_audio = any(x.get("codec_type") == "audio" for x in streams)
    rate = str(video.get("r_frame_rate") or "30/1")
    try:
        n, d = rate.split("/", 1)
        fps = float(n) / max(1.0, float(d))
    except Exception:
        fps = 30.0
    return {
        "duration": _safe_float((data.get("format") or {}).get("duration"), 0.0),
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "fps": max(20.0, min(60.0, fps or 30.0)),
        "has_audio": has_audio,
    }


def _download(url: str, destination: Path, timeout: int = 900) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "AI-VIDEO-Dynamic-V2/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response, destination.open("wb") as output:
        shutil.copyfileobj(response, output, length=1024 * 1024)
    if destination.stat().st_size < 1024:
        raise RuntimeError(f"下载结果过小：{url}")
    return destination


def _text_of_segment(item: dict[str, Any]) -> str:
    return str(
        item.get("text")
        or item.get("narration_segment")
        or item.get("narration")
        or item.get("script")
        or ""
    ).strip()


def _clean_caption_text(text: str) -> str:
    clean = re.sub(r"\s+", "", str(text or "")).strip()
    clean = re.sub(r"^[，,。；;、：:]+|[，,。；;、：:]+$", "", clean)
    return clean


def _caption_chunks(text: str, *, max_chars: int = 8) -> list[str]:
    clean = _clean_caption_text(text)
    if not clean:
        return []

    semantic = re.sub(
        r"(但是|不过|所以|如果|比如|然后|因为|其实|真正|而是|先看|再看|最后|第一|第二|第三|第四)",
        r"|\1",
        clean,
    )
    coarse = [
        item.strip("|，,。！？!?；;、：:")
        for item in re.split(r"[|，,。！？!?；;、：:]+", semantic)
        if item.strip("|，,。！？!?；;、：:")
    ]
    protected_suffixes = (
        "生活半径", "现金流", "回报率", "交通规划", "生活配套", "租客来源",
        "交付周期", "区域用途", "区域选择", "投资逻辑", "真实价格", "项目风险",
        "楼盘位置", "户型设计", "预算区间", "未来规划",
    )
    output: list[str] = []
    for item in coarse or [clean]:
        remaining = item
        while len(remaining) > max_chars:
            cut = min(6, max_chars)
            protected_cut = False
            for suffix in protected_suffixes:
                if remaining.endswith(suffix) and 3 <= len(remaining) - len(suffix) <= max_chars:
                    cut = len(remaining) - len(suffix)
                    protected_cut = True
                    break
            if len(remaining) - cut == 1:
                cut -= 1
            # Do not strand pronouns or particles at the end of a caption.
            if not protected_cut and cut > 3 and remaining[cut - 1] in "你我他她这那的和与":
                cut -= 1
            output.append(remaining[:cut])
            remaining = remaining[cut:]
        if remaining:
            if len(remaining) == 1 and output and len(output[-1]) < max_chars:
                output[-1] += remaining
            else:
                output.append(remaining)
    compact = [item for item in output if item]
    for index in range(len(compact) - 1):
        if len(compact[index]) >= 3 and compact[index][-1] in "你我他她":
            compact[index + 1] = compact[index][-1] + compact[index + 1]
            compact[index] = compact[index][:-1]
    return [item for item in compact if item]


def _spread_chunks(chunks: list[str], start: float, end: float) -> list[dict[str, Any]]:
    if not chunks:
        return []
    span = max(0.36, end - start)
    weights = [max(2, len(_clean_caption_text(item))) for item in chunks]
    total = max(1, sum(weights))
    cursor = start
    result: list[dict[str, Any]] = []
    for index, (chunk, weight) in enumerate(zip(chunks, weights)):
        if index == len(chunks) - 1:
            chunk_end = end
        else:
            chunk_end = min(end, cursor + span * weight / total)
        if chunk_end <= cursor:
            chunk_end = min(end, cursor + 0.36)
        result.append({"text": chunk, "start": round(cursor, 3), "end": round(chunk_end, 3)})
        cursor = chunk_end
    if result:
        result[-1]["end"] = round(max(result[-1]["start"] + 0.28, end), 3)
    return result


def _normalize_timings(payload: dict[str, Any], base_job: dict[str, Any], duration: float) -> list[dict[str, Any]]:
    raw = base_job.get("timings") or base_job.get("subtitle_segments") or payload.get("segments") or payload.get("script_segments") or []
    items: list[dict[str, Any]] = []
    for raw_item in raw if isinstance(raw, list) else []:
        if not isinstance(raw_item, dict):
            continue
        text = _text_of_segment(raw_item)
        if not text:
            continue
        start = _safe_float(raw_item.get("start") or raw_item.get("start_time"), -1.0)
        end = _safe_float(raw_item.get("end") or raw_item.get("end_time"), -1.0)
        items.append({"text": text, "start": start, "end": end})

    if items and all(item["start"] >= 0 and item["end"] > item["start"] for item in items):
        fragmented: list[dict[str, Any]] = []
        for item in items:
            fragmented.extend(_spread_chunks(_caption_chunks(item["text"]), item["start"], item["end"]))
        return fragmented

    script = str(payload.get("script_text") or payload.get("script") or "").strip()
    if not script and items:
        script = "。".join(item["text"] for item in items)
    chunks = _caption_chunks(script or "动态精剪")
    weights = [max(2, len(_clean_caption_text(item))) for item in chunks]
    total = max(1, sum(weights))
    cursor = 0.0
    normalized: list[dict[str, Any]] = []
    for index, (chunk, weight) in enumerate(zip(chunks, weights)):
        end = duration if index == len(chunks) - 1 else min(duration, cursor + duration * weight / total)
        normalized.append({"text": chunk, "start": round(cursor, 3), "end": round(end, 3)})
        cursor = end
    return normalized


def _classify(text: str) -> str:
    for role, pattern in ROLE_PATTERNS:
        if pattern.search(text):
            return role
    return "knowledge"


def _keywords(payload: dict[str, Any], timings: list[dict[str, Any]]) -> list[str]:
    found: list[str] = []
    for item in payload.get("keyword_insights") or []:
        value = str(item.get("value") if isinstance(item, dict) else item or "").strip()
        if value and value not in found:
            found.append(value)
    if found:
        return found[:24]
    joined = " ".join(item["text"] for item in timings)
    for pattern in [r"\d+(?:\.\d+)?(?:%|万|亿|年|个月|天|套|个|条)?", r"[\u4e00-\u9fff]{2,6}(?:风险|预算|交通|配套|区域|用途|租客|交付|规划)"]:
        for match in re.findall(pattern, joined):
            value = str(match).strip()
            if value and value not in found:
                found.append(value)
    return found[:16]


def _pick_focus(text: str, keywords: list[str]) -> str:
    for keyword in keywords:
        if keyword and keyword in text:
            return keyword[:12]
    number = re.search(r"\d+(?:\.\d+)?\s*(?:%|万|亿|年|个月|天|套|个|条|公里|分钟)?", text)
    if number:
        return number.group(0).strip()[:12]
    cleaned = re.sub(r"[，。！？!?；;、\s]", "", text)
    return cleaned[:8] or "重点"


def build_dynamic_plan(
    payload: dict[str, Any],
    timings: list[dict[str, Any]],
    duration: float,
    *,
    intensity: str = "balanced",
) -> dict[str, Any]:
    preset = EDIT_PRESETS.get(intensity) or EDIT_PRESETS["balanced"]
    keywords = _keywords(payload, timings)
    min_gap = float(preset["min_effect_gap_seconds"])
    max_effects = max(2, int(math.ceil(max(1.0, duration) / 30.0 * int(preset["max_major_effects_per_30s"]))))
    candidates: list[dict[str, Any]] = []
    priority = {"hook": 10, "data": 9, "risk": 8, "question": 7, "turn": 7, "comparison": 6, "list": 6, "evidence": 5, "cta": 5, "knowledge": 2}
    effect_map = {
        "hook": "hook_punch",
        "question": "question_pulse",
        "turn": "turn_focus",
        "data": "data_card",
        "risk": "risk_alert",
        "comparison": "comparison_card",
        "list": "list_card",
        "evidence": "evidence_pip",
        "cta": "cta_tag",
        "knowledge": "keyword_focus",
    }
    for index, item in enumerate(timings):
        text = item["text"]
        role = _classify(text)
        start = max(0.0, _safe_float(item.get("start"), 0.0))
        end = min(duration, max(start + 0.45, _safe_float(item.get("end"), start + 1.4)))
        effect_end = min(end, start + (1.25 if role in {"hook", "data", "risk"} else 1.7))
        candidates.append(
            {
                "id": f"fx_{index + 1:02d}",
                "segment_index": index,
                "start": round(start, 3),
                "end": round(effect_end, 3),
                "role": role,
                "effect": effect_map[role],
                "focus_text": _pick_focus(text, keywords),
                "source_text": text,
                "priority": priority[role],
            }
        )
    selected: list[dict[str, Any]] = []
    for candidate in sorted(candidates, key=lambda x: (-x["priority"], x["start"])):
        if any(abs(candidate["start"] - item["start"]) < min_gap for item in selected):
            continue
        selected.append(candidate)
        if len(selected) >= max_effects:
            break
    selected.sort(key=lambda x: x["start"])
    if timings and (not selected or selected[0]["start"] > 1.2):
        first = dict(candidates[0])
        first.update(effect="hook_punch", role="hook", start=0.0, end=min(1.15, duration), priority=11)
        selected.insert(0, first)
    if timings and duration >= 12 and not any(item["start"] >= duration * 0.75 for item in selected):
        tail = dict(candidates[-1])
        tail.update(effect="cta_tag" if tail["role"] == "cta" else "keyword_focus", start=max(0.0, min(duration - 1.3, tail["start"])), end=min(duration, max(tail["start"] + 1.1, tail["end"])))
        selected.append(tail)
    selected.sort(key=lambda x: x["start"])
    return {
        "version": VERSION,
        "intensity": intensity,
        "subtitle_style": str(payload.get("dynamic_subtitle_style") or "dynamic_white_yellow"),
        "duration": round(duration, 3),
        "keywords": keywords,
        "events": selected,
        "caption_beats": [round(_safe_float(item.get("start"), 0.0), 3) for item in timings],
        "caption_count": len(timings),
        "visual_pace": "dynamic_dense",
        "limits": {
            "max_major_effects": max_effects,
            "min_effect_gap_seconds": min_gap,
            "zoom_strength": preset["zoom_strength"],
            "micro_zoom_strength": preset.get("micro_zoom_strength", 0.016),
        },
    }


def _ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours}:{minutes:02d}:{secs:05.2f}"


def _ass_escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")


def _wrap_text(text: str, limit: int) -> str:
    clean = _clean_caption_text(text)
    return clean[: max(3, min(8, int(limit or 8)))]


def _highlight_ass(text: str, keywords: list[str], highlight: str) -> str:
    escaped = _ass_escape(text)
    for keyword in sorted((x for x in keywords if x), key=len, reverse=True):
        safe = _ass_escape(keyword)
        if safe in escaped:
            escaped = escaped.replace(safe, rf"{{\c{highlight}\fscx108\fscy108}}{safe}{{\c&H00FFFFFF&\fscx100\fscy100}}", 1)
            break
    return escaped


def _font_name() -> str:
    candidates = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return path
    return ""


def write_dynamic_ass(
    destination: Path,
    timings: list[dict[str, Any]],
    keywords: list[str],
    *,
    style_id: str,
) -> Path:
    preset = SUBTITLE_PRESETS.get(style_id) or SUBTITLE_PRESETS["dynamic_white_yellow"]
    font_name = "Noto Sans CJK SC"
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes
WrapStyle: 2

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Dynamic,{font_name},{preset['font_size']},{preset['primary']},{preset['highlight']},{preset['outline']},{preset['back']},-1,0,0,0,100,100,1.0,0,{preset['border_style']},{preset['outline_width']},{preset['shadow']},2,55,55,{preset['margin_v']},1
Style: Impact,{font_name},{preset['impact_size']},{preset['primary']},{preset['highlight']},{preset['outline']},{preset['back']},-1,0,0,0,100,100,1.2,0,{preset['border_style']},{preset['outline_width'] + 1},{preset['shadow']},5,45,45,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for index, item in enumerate(timings):
        start = _safe_float(item.get("start"), 0.0)
        end = max(start + 0.28, _safe_float(item.get("end"), start + 0.8))
        raw_text = _wrap_text(str(item.get("text") or ""), 8)
        text = _highlight_ass(raw_text, keywords, str(preset["highlight"]))
        role = _classify(raw_text)
        impact = role in {"hook", "data", "risk", "question", "turn"} and len(raw_text) <= 7
        if impact:
            role_color = {
                "data": preset.get("highlight"),
                "risk": "&H00004BFF",
                "question": preset.get("accent"),
                "turn": preset.get("accent"),
                "hook": preset.get("highlight"),
            }.get(role, preset.get("highlight"))
            text = rf"{{\c{role_color}}}{text}"
            y = 880 + (index % 3) * 105
            animation = rf"{{\an5\pos(540,{y})\fad(45,70)\fscx132\fscy132\t(0,150,\fscx100\fscy100)}}"
            style = "Impact"
        else:
            y = 1435 + (index % 2) * 72
            animation = rf"{{\an5\pos(540,{y})\fad(55,70)\fscx112\fscy112\t(0,130,\fscx100\fscy100)}}"
            style = "Dynamic"
        lines.append(
            f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},{style},,0,0,0,,{animation}{text}\n"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("".join(lines), encoding="utf-8-sig")
    return destination


def _ffmpeg_escape_path(path: Path) -> str:
    return str(path).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")


def _event_text_files(work: Path, plan: dict[str, Any]) -> list[tuple[dict[str, Any], Path]]:
    result: list[tuple[dict[str, Any], Path]] = []
    text_dir = work / "effect-text"
    text_dir.mkdir(parents=True, exist_ok=True)
    for event in plan.get("events") or []:
        path = text_dir / f"{event['id']}.txt"
        path.write_text(_clean_caption_text(str(event.get("focus_text") or "重点"))[:8], encoding="utf-8")
        result.append((event, path))
    return result


def _build_video_filters(
    work: Path,
    plan: dict[str, Any],
    ass_path: Path,
    *,
    width: int = 1080,
    height: int = 1920,
) -> str:
    events = plan.get("events") or []
    limits = plan.get("limits") or {}
    zoom_strength = _safe_float(limits.get("zoom_strength"), 0.052)
    micro_strength = _safe_float(limits.get("micro_zoom_strength"), 0.016)
    zoom_terms: list[str] = []

    # Small reframing beats follow the short subtitle rhythm. They create the
    # reference-video feeling without covering the picture with UI cards.
    beats = [float(value) for value in (plan.get("caption_beats") or [])[:40]]
    for index, start in enumerate(beats):
        if index % 2:
            continue
        span = 0.68 if index % 4 else 0.92
        zoom_terms.append(
            f"+{micro_strength:.4f}*between(t,{start:.3f},{start + span:.3f})*sin(PI*(t-{start:.3f})/{span:.3f})"
        )
    for event in events:
        if event.get("effect") in {"hook_punch", "question_pulse", "turn_focus", "risk_alert", "keyword_focus", "data_card"}:
            start = _safe_float(event.get("start"), 0.0)
            end = max(start + 0.3, _safe_float(event.get("end"), start + 0.9))
            span = max(0.2, end - start)
            strength = zoom_strength * (1.15 if event.get("effect") in {"hook_punch", "data_card"} else 0.78)
            zoom_terms.append(f"+{strength:.4f}*between(t,{start:.3f},{end:.3f})*sin(PI*(t-{start:.3f})/{span:.3f})")

    factor = "1" + "".join(zoom_terms)
    chain = [
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1[base]",
        f"[base]scale=w='{width}*({factor})':h='{height}*({factor})':eval=frame,crop={width}:{height}:(iw-{width})/2:(ih-{height})/2[v0]",
    ]
    current = "v0"
    fontfile = _font_name()
    font_opt = f":fontfile='{_ffmpeg_escape_path(Path(fontfile))}'" if fontfile else ""
    palette = {
        "hook_punch": ("#FFE22E", 126, 520),
        "question_pulse": ("#FF4F66", 118, 650),
        "turn_focus": ("#FF9D36", 112, 500),
        "data_card": ("#FFE22E", 132, 610),
        "risk_alert": ("#FF4F4F", 120, 560),
        "comparison_card": ("#FFFFFF", 102, 440),
        "list_card": ("#FFE46B", 106, 450),
        "evidence_pip": ("#FFFFFF", 98, 430),
        "cta_tag": ("#FFFFFF", 104, 520),
        "keyword_focus": ("#FFE22E", 104, 470),
    }
    for index, (event, text_path) in enumerate(_event_text_files(work, plan), start=1):
        effect = str(event.get("effect") or "keyword_focus")
        color, font_size, y = palette.get(effect, palette["keyword_focus"])
        start = _safe_float(event.get("start"), 0.0)
        end = max(start + 0.28, _safe_float(event.get("end"), start + 0.9))
        next_label = f"v{index}"
        x_expr = "(w-text_w)/2" if index % 3 else r"max(38\,(w-text_w)/2-170)"
        alpha = (
            f"if(lt(t,{start + 0.10:.3f}),(t-{start:.3f})/0.10,"
            f"if(gt(t,{end - 0.10:.3f}),({end:.3f}-t)/0.10,1))"
        )
        filter_part = (
            f"[{current}]drawtext=textfile='{_ffmpeg_escape_path(text_path)}'{font_opt}:expansion=none:"
            f"fontsize={font_size}:fontcolor={color}:borderw=6:bordercolor=black@0.86:shadowx=2:shadowy=3:"
            f"x={x_expr}:y={y}:alpha='{alpha}':enable='between(t,{start:.3f},{end:.3f})'[{next_label}]"
        )
        chain.append(filter_part)
        current = next_label
    ass_escaped = _ffmpeg_escape_path(ass_path)
    chain.append(f"[{current}]ass='{ass_escaped}'[vout]")
    return ";".join(chain)


def _build_audio_filters(plan: dict[str, Any], *, has_audio: bool) -> tuple[str, str | None]:
    if not has_audio:
        return "", None
    events = [event for event in (plan.get("events") or []) if event.get("effect") in {"hook_punch", "data_card", "risk_alert", "turn_focus", "cta_tag"}]
    if not events:
        return "", "0:a?"
    volume = _safe_float(EDIT_PRESETS.get(str(plan.get("intensity")), EDIT_PRESETS["balanced"]).get("sfx_volume"), 0.05)
    parts: list[str] = []
    labels: list[str] = ["0:a"]
    for index, event in enumerate(events[:10], start=1):
        frequency = 920 if event.get("effect") in {"hook_punch", "data_card"} else 620
        delay = int(max(0.0, _safe_float(event.get("start"), 0.0)) * 1000)
        label = f"sfx{index}"
        parts.append(
            f"sine=frequency={frequency}:sample_rate=48000:duration=0.085,volume={volume:.4f},"
            f"afade=t=in:st=0:d=0.012,afade=t=out:st=0.052:d=0.033,adelay={delay}|{delay}[{label}]"
        )
        labels.append(label)
    parts.append("".join(f"[{label}]" for label in labels) + f"amix=inputs={len(labels)}:duration=first:dropout_transition=0,alimiter=limit=0.95[aout]")
    return ";".join(parts), "aout"


def render_dynamic_video(
    input_path: Path,
    output_path: Path,
    ass_path: Path,
    plan: dict[str, Any],
) -> dict[str, Any]:
    info = _probe(input_path)
    video_filters = _build_video_filters(input_path.parent, plan, ass_path)
    audio_filters, audio_label = _build_audio_filters(plan, has_audio=bool(info["has_audio"]))
    filter_complex = video_filters + (";" + audio_filters if audio_filters else "")
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(input_path),
        "-filter_complex",
        filter_complex,
        "-map",
        "[vout]",
    ]
    if audio_label == "aout":
        cmd += ["-map", "[aout]"]
    elif info["has_audio"]:
        cmd += ["-map", "0:a?"]
    cmd += [
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-r",
        f"{info['fps']:.3f}",
    ]
    if info["has_audio"]:
        cmd += ["-c:a", "aac", "-b:a", "192k"]
    cmd += ["-movflags", "+faststart", str(output_path)]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(cmd, check=True, timeout=7200)
    rendered = _probe(output_path)
    if rendered["duration"] < max(1.0, info["duration"] - 0.6):
        raise RuntimeError("动态精剪输出时长异常")
    return {"input": info, "output": rendered, "ffmpeg_command": cmd}


def _run_dynamic(settings: Any, proxy_job_id: str, payload: dict[str, Any]) -> None:
    classic = _classic()
    work = _work_dir(settings, proxy_job_id)
    try:
        _update_proxy(settings, proxy_job_id, status="running", stage="classic_base_start", progress=2, message="正在保留 A10-R4 稳定底片")
        classic_payload = dict(payload)
        classic_payload["burn_subtitles"] = False
        classic_payload["edit_pace"] = "dynamic_dense"
        classic_payload["dynamic_v2_parent_job_id"] = proxy_job_id
        classic_job = classic._start(settings, classic_payload)
        classic_job_id = str(classic_job["job_id"])
        _update_proxy(settings, proxy_job_id, base_job_id=classic_job_id, classic_job_id=classic_job_id)
        deadline = time.time() + 6 * 3600
        base: dict[str, Any] | None = None
        while time.time() < deadline:
            base = classic._load_jobs(settings).get(classic_job_id)
            if not base:
                time.sleep(1.5)
                continue
            status = str(base.get("status") or "")
            base_progress = int(_safe_float(base.get("progress"), 0.0))
            _update_proxy(
                settings,
                proxy_job_id,
                status="running",
                stage=f"base_{base.get('stage') or status}",
                progress=min(82, max(3, int(base_progress * 0.80))),
                message=f"稳定底片：{base.get('message') or status}",
                current_clip=base.get("current_clip"),
                current_file=base.get("current_file"),
            )
            if status == "done":
                break
            if status in {"failed", "cancelled"}:
                raise RuntimeError(f"A10-R4 稳定底片失败：{base.get('error') or base.get('message')}")
            time.sleep(2.0)
        if not base or str(base.get("status")) != "done":
            raise TimeoutError("等待 A10-R4 稳定底片超时")

        source_url = str(base.get("no_subtitle_video_url") or base.get("raw_video_url") or base.get("video_url") or "")
        if not source_url:
            raise RuntimeError("稳定底片没有可用视频地址")
        source_suffix = Path(urllib.parse.urlparse(source_url).path).suffix or ".mp4"
        source_path = _download(source_url, work / f"classic_base{source_suffix}")
        info = _probe(source_path)
        duration = max(0.1, _safe_float(base.get("duration_seconds"), info["duration"]) or info["duration"])
        timings = _normalize_timings(payload, base, duration)
        intensity = str(payload.get("dynamic_edit_intensity") or "balanced")
        style_id = str(payload.get("dynamic_subtitle_style") or "dynamic_white_yellow")
        plan = build_dynamic_plan(payload, timings, duration, intensity=intensity)
        plan["subtitle_style"] = style_id
        ass_path = write_dynamic_ass(work / "dynamic_subtitles.ass", timings, plan.get("keywords") or [], style_id=style_id)
        plan_path = work / "dynamic_effect_timeline.json"
        plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

        _update_proxy(settings, proxy_job_id, stage="dynamic_render", progress=86, message="正在渲染动态构图、信息卡和参考字幕", dynamic_effect_timeline=plan)
        output_path = Path(getattr(settings, "outputs_dir", _data_dir(settings) / "outputs")) / f"{proxy_job_id}_dynamic_v2.mp4"
        render_report = render_dynamic_video(source_path, output_path, ass_path, plan)
        report = {
            "version": VERSION,
            "job_id": proxy_job_id,
            "base_job_id": classic_job_id,
            "intensity": intensity,
            "subtitle_style": style_id,
            "effect_count": len(plan.get("events") or []),
            "events": plan.get("events") or [],
            "safe_effects": ["semantic_zoom", "keyword_card", "data_card", "risk_alert", "list_card", "dynamic_ass_subtitles", "generated_micro_sfx"],
            "person_cutout": {"requested": False, "status": "deferred_until_mask_quality_gate"},
            "render": render_report,
            "created_at": _now(),
        }
        report_path = work / "dynamic_edit_report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        _update_proxy(settings, proxy_job_id, stage="upload", progress=96, message="正在上传动态精剪版并保留稳定版")
        dynamic_url = classic._url(settings, output_path, "videos/existing-edit-v2/final")
        classic_url = str(base.get("video_url") or base.get("output_url") or source_url)
        _update_proxy(
            settings,
            proxy_job_id,
            status="done",
            stage="finished",
            progress=100,
            message="动态精剪 V2 完成；A10-R4 稳定版和新版同时保留",
            video_url=dynamic_url,
            output_url=dynamic_url,
            dynamic_video_url=dynamic_url,
            subtitled_video_url=dynamic_url,
            raw_video_url=source_url,
            no_subtitle_video_url=source_url,
            classic_video_url=classic_url,
            base_video_url=classic_url,
            ab_outputs={"classic_a10_r4": classic_url, "dynamic_v2": dynamic_url},
            timings=timings,
            dynamic_effect_timeline=plan,
            dynamic_edit_report=report,
            dynamic_subtitle_style=style_id,
            dynamic_edit_intensity=intensity,
            base_job_id=classic_job_id,
            fal_used=False,
            billing_guard="dynamic_v2_wraps_existing_edit_no_fal",
            finished_at=_now(),
        )
    except Exception as exc:
        _update_proxy(
            settings,
            proxy_job_id,
            status="failed",
            stage="failed",
            progress=100,
            error=str(exc)[:3000],
            message=f"动态精剪 V2 失败：{exc}；A10-R4 原版未被修改",
            fal_used=False,
            billing_guard="dynamic_v2_no_fal",
            finished_at=_now(),
        )


def _thread(settings: Any, job_id: str, payload: dict[str, Any]) -> None:
    _run_dynamic(settings, job_id, payload)


def start_dynamic(settings: Any, payload: dict[str, Any]) -> dict[str, Any]:
    job_id = f"dynamic_edit_v2_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    job = {
        "job_id": job_id,
        "job_type": "dynamic_existing_video_edit_v2",
        "version": VERSION,
        "status": "queued",
        "stage": "queued",
        "progress": 0,
        "message": "等待生成 A10-R4 稳定底片和动态精剪版",
        "mode": "dynamic_edit_v2",
        "edit_engine": "dynamic_v2",
        "dynamic_edit_intensity": str(payload.get("dynamic_edit_intensity") or "balanced"),
        "dynamic_subtitle_style": str(payload.get("dynamic_subtitle_style") or "dynamic_white_yellow"),
        "fal_used": False,
        "billing_guard": "dynamic_v2_no_fal",
        "created_at": _now(),
        "updated_at": _now(),
    }
    _save_proxy(settings, job)
    threading.Thread(target=_thread, args=(settings, job_id, dict(payload)), daemon=True, name=f"dynamic-v2-{job_id[-8:]}").start()
    return job


def install_dynamic_edit_v2(app: Any, get_settings: Callable[..., Any]) -> None:
    global _INSTALLED
    if _INSTALLED or any(getattr(route, "path", "") == "/api/video/existing-edit-v2/health" for route in getattr(app, "routes", [])):
        _INSTALLED = True
        return

    @app.get("/api/video/existing-edit-v2/health")
    def health(settings: Any = Depends(get_settings)) -> dict[str, Any]:
        jobs = _classic()._load_jobs(settings)
        dynamic_jobs = [item for item in jobs.values() if str(item.get("mode") or "") == "dynamic_edit_v2"]
        return {
            "ok": True,
            "version": VERSION,
            "mode": INSTALL_MARKER,
            "classic_engine_preserved": True,
            "classic_health_path": "/api/video/existing-edit/health",
            "ffmpeg": bool(shutil.which("ffmpeg")),
            "ffprobe": bool(shutil.which("ffprobe")),
            "fal_used": False,
            "running_jobs": sum(1 for item in dynamic_jobs if item.get("status") in {"queued", "running"}),
            "edit_presets": EDIT_PRESETS,
            "subtitle_presets": SUBTITLE_PRESETS,
            "features": {
                "ab_outputs": True,
                "classic_a10_r4_retained": True,
                "semantic_effect_timeline": True,
                "dynamic_zoom": True,
                "hook_punch": True,
                "data_cards": False,
                "risk_alerts": True,
                "list_cards": False,
                "no_text_boxes": True,
                "micro_caption_fragments": True,
                "dynamic_dense_base_clips": True,
                "reference_subtitle_pack": True,
                "keyword_highlight": True,
                "micro_sfx": True,
                "person_cutout_quality_gate": "phase_2",
                "fal_forbidden": True,
            },
        }

    @app.get("/api/video/existing-edit-v2/presets")
    def presets() -> dict[str, Any]:
        return {"ok": True, "version": VERSION, "edit_presets": EDIT_PRESETS, "subtitle_presets": SUBTITLE_PRESETS}

    @app.post("/api/video/existing-edit-v2/plan")
    async def plan(request: Request) -> dict[str, Any]:
        payload = await request.json()
        duration = _safe_float(payload.get("target_duration_seconds"), 30.0)
        timings = _normalize_timings(payload, {}, duration)
        intensity = str(request.query_params.get("intensity") or payload.get("dynamic_edit_intensity") or "balanced")
        result = build_dynamic_plan(payload, timings, duration, intensity=intensity)
        return {"ok": True, "version": VERSION, "plan": result, "timings": timings}

    @app.post("/api/video/existing-edit-v2/start")
    async def start(request: Request, settings: Any = Depends(get_settings)) -> dict[str, Any]:
        try:
            payload = await request.json()
            if not isinstance(payload, dict):
                raise ValueError("请求体必须是 JSON object")
            payload = dict(payload)
            payload["dynamic_edit_intensity"] = str(request.query_params.get("intensity") or payload.get("dynamic_edit_intensity") or "balanced")
            payload["dynamic_subtitle_style"] = str(request.query_params.get("subtitle_style") or payload.get("dynamic_subtitle_style") or "dynamic_white_yellow")
            payload["edit_engine"] = "dynamic_v2"
            payload["burn_subtitles"] = False
            return start_dynamic(settings, payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/video/existing-edit-v2/jobs/latest")
    def latest(done_only: bool = False, settings: Any = Depends(get_settings)) -> dict[str, Any]:
        items = [item for item in _classic()._load_jobs(settings).values() if str(item.get("mode") or "") == "dynamic_edit_v2"]
        if done_only:
            items = [item for item in items if item.get("status") == "done"]
        items.sort(key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""), reverse=True)
        return {"ok": True, "version": VERSION, "job": items[0] if items else None}

    @app.get("/api/video/existing-edit-v2/jobs/{job_id}")
    def job(job_id: str, settings: Any = Depends(get_settings)) -> dict[str, Any]:
        item = _read_proxy(settings, job_id)
        if not item or str(item.get("mode") or "") != "dynamic_edit_v2":
            raise HTTPException(status_code=404, detail="动态精剪 V2 任务不存在")
        return item

    _INSTALLED = True
