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

VERSION = "10.40.8.21-semantic-master-timeline-quality-gate"
INSTALL_MARKER = "V10_40_8_21_SEMANTIC_MASTER_TIMELINE_QUALITY_GATE"
_INSTALLED = False
_LOCK = threading.RLock()


EDIT_PRESETS: dict[str, dict[str, Any]] = {
    "restrained": {
        "label": "克制短句精剪",
        "description": "短句大字幕、轻推近、少量真实音效和主题贴纸。",
        "max_major_effects_per_30s": 7,
        "min_effect_gap_seconds": 2.7,
        "zoom_strength": 0.032,
        "micro_zoom_strength": 0.010,
    },
    "balanced": {
        "label": "参考节奏精剪",
        "description": "大号短字幕、真实音效、语义贴纸和更密镜头，贴近参考节奏。",
        "max_major_effects_per_30s": 11,
        "min_effect_gap_seconds": 1.75,
        "zoom_strength": 0.052,
        "micro_zoom_strength": 0.016,
    },
    "strong": {
        "label": "强节奏短句精剪",
        "description": "更密短句、重点词、真实音效和更多主题贴纸。",
        "max_major_effects_per_30s": 15,
        "min_effect_gap_seconds": 1.15,
        "zoom_strength": 0.068,
        "micro_zoom_strength": 0.022,
    },
}

SFX_LEVELS: dict[str, dict[str, Any]] = {
    "off": {"label": "关闭音效", "volume": 0.0, "max_per_30s": 0},
    "light": {"label": "轻音效", "volume": 0.26, "max_per_30s": 6},
    "balanced": {"label": "标准音效", "volume": 0.42, "max_per_30s": 10},
    "strong": {"label": "强音效", "volume": 0.58, "max_per_30s": 14},
}

STICKER_LEVELS: dict[str, dict[str, Any]] = {
    "off": {"label": "关闭贴纸", "max_per_30s": 0, "min_gap": 99.0},
    "light": {"label": "少量贴纸", "max_per_30s": 3, "min_gap": 5.0},
    "balanced": {"label": "标准贴纸", "max_per_30s": 6, "min_gap": 3.0},
    "rich": {"label": "丰富贴纸", "max_per_30s": 10, "min_gap": 2.0},
}

SUBTITLE_PRESETS: dict[str, dict[str, Any]] = {
    "dynamic_white_yellow": {
        "label": "白黄大字跳词",
        "description": "白字黑描边，重点词亮黄；每屏 3-7 字，无底框。",
        "font_size": 108,
        "impact_size": 148,
        "primary": "&H00FFFFFF",
        "highlight": "&H0000E8FF",
        "accent": "&H0000A5FF",
        "outline": "&H00111111",
        "back": "&H00000000",
        "border_style": 1,
        "outline_width": 8,
        "shadow": 3,
        "margin_v": 250,
        "alignment": 2,
    },
    "dynamic_black_box": {
        "label": "橙白大字冲击",
        "description": "无黑底条，橙白大词与中心重击。",
        "font_size": 106,
        "impact_size": 152,
        "primary": "&H00FFFFFF",
        "highlight": "&H000096FF",
        "accent": "&H00004BFF",
        "outline": "&H00111111",
        "back": "&H00000000",
        "border_style": 1,
        "outline_width": 8,
        "shadow": 3,
        "margin_v": 250,
        "alignment": 2,
    },
    "dynamic_gold_property": {
        "label": "金白地产大字",
        "description": "金色关键词配白字，适合预算、区域与资产内容。",
        "font_size": 104,
        "impact_size": 146,
        "primary": "&H00FFFFFF",
        "highlight": "&H004BC8FF",
        "accent": "&H0000D7FF",
        "outline": "&H00130F17",
        "back": "&H00000000",
        "border_style": 1,
        "outline_width": 9,
        "shadow": 3,
        "margin_v": 252,
        "alignment": 2,
    },
    "dynamic_minimal_pro": {
        "label": "极简专业大字",
        "description": "无底色大白字、轻描边，画面干净专业。",
        "font_size": 98,
        "impact_size": 132,
        "primary": "&H00FFFFFF",
        "highlight": "&H00E8D6C8",
        "accent": "&H00FFFFFF",
        "outline": "&H003A3541",
        "back": "&H00000000",
        "border_style": 1,
        "outline_width": 6,
        "shadow": 3,
        "margin_v": 248,
        "alignment": 2,
    },
    "dynamic_red_hook": {
        "label": "红黄疑问大字",
        "description": "疑问、风险和数字用红黄大词重击。",
        "font_size": 110,
        "impact_size": 158,
        "primary": "&H00FFFFFF",
        "highlight": "&H00004BFF",
        "accent": "&H0000E8FF",
        "outline": "&H00101010",
        "back": "&H00000000",
        "border_style": 1,
        "outline_width": 9,
        "shadow": 4,
        "margin_v": 255,
        "alignment": 2,
    },
    "dynamic_dual_line": {
        "label": "清单节奏大字",
        "description": "单行短句为主，清单词逐条大字出现。",
        "font_size": 102,
        "impact_size": 142,
        "primary": "&H00FFFFFF",
        "highlight": "&H0000D7FF",
        "accent": "&H000096FF",
        "outline": "&H00151418",
        "back": "&H00000000",
        "border_style": 1,
        "outline_width": 7,
        "shadow": 3,
        "margin_v": 245,
        "alignment": 2,
    },
}

SFX_ASSET_MAP: dict[str, tuple[str, float]] = {
    "hook_punch": ("hook_punch.wav", 1.10),
    "question_pulse": ("question_ping.wav", 0.92),
    "turn_focus": ("turn_whoosh.wav", 0.90),
    "data_card": ("data_tick.wav", 1.00),
    "risk_alert": ("risk_warning.wav", 0.94),
    "comparison_card": ("comparison_swipe.wav", 0.82),
    "list_card": ("list_tick.wav", 0.78),
    "evidence_pip": ("camera_click.wav", 0.82),
    "cta_tag": ("cta_ding.wav", 1.00),
    "keyword_focus": ("soft_pop.wav", 0.90),
}

STICKER_ROLE_DEFAULTS: dict[str, list[str]] = {
    "hook": ["point", "warning", "question"],
    "question": ["question", "search"],
    "turn": ["point", "check"],
    "data": ["chart", "money"],
    "risk": ["warning", "search"],
    "comparison": ["chart", "clipboard"],
    "list": ["clipboard", "check"],
    "evidence": ["camera", "search", "map"],
    "cta": ["comment", "bell", "point"],
    "knowledge": ["check", "pin"],
}

STICKER_TEXT_RULES: list[tuple[re.Pattern[str], list[str]]] = [
    (re.compile(r"买房|房子|楼盘|住宅|公寓|置业", re.I), ["house", "office", "key"]),
    (re.compile(r"钥匙|收房|交付|入住", re.I), ["key", "check", "house"]),
    (re.compile(r"吉隆坡|马来西亚|KLCC|区域|位置|地段|板块", re.I), ["pin", "map", "palm"]),
    (re.compile(r"价格|预算|租金|现金|马币|回报|收益|升值|投资", re.I), ["money", "chart"]),
    (re.compile(r"交通|地铁|通勤|线路|车程|出行", re.I), ["metro", "car", "map"]),
    (re.compile(r"商场|购物|商业|配套", re.I), ["shopping", "pin"]),
    (re.compile(r"餐饮|吃饭|美食|生活", re.I), ["food", "shopping"]),
    (re.compile(r"施工|在建|工地|工程|交付周期", re.I), ["construction", "key"]),
    (re.compile(r"租客|人口|客户|人群|白领", re.I), ["people", "office"]),
    (re.compile(r"风险|避坑|不要|不能|错误|踩坑|误区", re.I), ["warning", "search"]),
    (re.compile(r"第一|第二|第三|第四|清单|步骤|重点", re.I), ["clipboard", "check"]),
    (re.compile(r"实拍|证据|报告|数据|截图|现场", re.I), ["camera", "search"]),
    (re.compile(r"为什么|怎么|是不是|吗", re.I), ["question", "search"]),
    (re.compile(r"关注|评论|私信|留言|联系|收藏", re.I), ["comment", "bell", "point"]),
]

STICKER_POSITIONS = ["left_top", "right_top", "left_mid", "right_mid"]

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


def _asset_root() -> Path:
    return Path(__file__).resolve().parents[1] / "assets" / "dynamic_edit_v2"


def _sfx_root() -> Path:
    return _asset_root() / "sfx"


def _sticker_root() -> Path:
    return _asset_root() / "stickers"


def _deterministic_choice(options: list[str], key: str) -> str:
    if not options:
        return ""
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return options[int.from_bytes(digest[:4], "big") % len(options)]


def _choose_sticker(event: dict[str, Any], index: int) -> str:
    text = str(event.get("source_text") or "")
    role = str(event.get("role") or "knowledge")
    for pattern, options in STICKER_TEXT_RULES:
        if pattern.search(text):
            return _deterministic_choice(options, f"{event.get('id')}:{text}:{index}")
    return _deterministic_choice(STICKER_ROLE_DEFAULTS.get(role) or ["check"], f"{event.get('id')}:{role}:{index}")


def _decorate_events(
    events: list[dict[str, Any]],
    duration: float,
    *,
    sfx_level: str,
    sticker_level: str,
) -> list[dict[str, Any]]:
    result = [dict(item) for item in events]
    sfx_cfg = SFX_LEVELS.get(sfx_level) or SFX_LEVELS["balanced"]
    sticker_cfg = STICKER_LEVELS.get(sticker_level) or STICKER_LEVELS["balanced"]

    max_sfx = max(0, int(math.ceil(max(1.0, duration) / 30.0 * int(sfx_cfg["max_per_30s"]))))
    for event in result[:max_sfx]:
        asset_name, gain = SFX_ASSET_MAP.get(str(event.get("effect") or "keyword_focus"), SFX_ASSET_MAP["keyword_focus"])
        if float(sfx_cfg["volume"]) > 0 and (_sfx_root() / asset_name).exists():
            event["sfx"] = {
                "asset": asset_name,
                "gain": round(float(sfx_cfg["volume"]) * float(gain), 4),
            }

    max_stickers = max(0, int(math.ceil(max(1.0, duration) / 30.0 * int(sticker_cfg["max_per_30s"]))))
    min_gap = float(sticker_cfg["min_gap"])
    used = 0
    last_start = -999.0
    last_asset = ""
    position_index = 0
    for index, event in enumerate(result):
        if used >= max_stickers:
            break
        start = _safe_float(event.get("start"), 0.0)
        if start - last_start < min_gap:
            continue
        asset = _choose_sticker(event, index)
        if not asset or asset == last_asset or not (_sticker_root() / f"{asset}.png").exists():
            alternatives = [name for name in STICKER_ROLE_DEFAULTS.get(str(event.get("role") or "knowledge"), ["check"]) if name != last_asset]
            asset = _deterministic_choice(alternatives or ["check"], f"fallback:{event.get('id')}:{index}")
        path = _sticker_root() / f"{asset}.png"
        if not path.exists():
            continue
        event_end = max(start + 0.75, _safe_float(event.get("end"), start + 1.15))
        span = min(1.45, max(0.78, event_end - start))
        event["sticker"] = {
            "asset": f"{asset}.png",
            "position": STICKER_POSITIONS[position_index % len(STICKER_POSITIONS)],
            "size": 178 + (position_index % 3) * 18,
            "start": round(start, 3),
            "end": round(min(duration, start + span), 3),
        }
        used += 1
        last_start = start
        last_asset = asset
        position_index += 1
    return result


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


def _caption_chunks(text: str, *, max_chars: int = 9) -> list[str]:
    clean = _clean_caption_text(text)
    if not clean:
        return []
    protected = (
        "吉隆坡买房", "第一眼", "自住还是投资", "这两个方向", "区域完全不一样",
        "真实的生活半径", "每天通勤时间", "周边超市", "学校离得远不远",
        "这些现有配套", "住进去舒不舒服", "价格只是门槛", "区域租客",
        "本地需求支撑", "把用途想明白", "区域才不会踩坑", "一对一拆解",
        "生活半径", "生活配套", "租客来源", "交通规划", "投资逻辑", "区域选择",
    )
    coarse = [x for x in re.split(r"[，,。！？!?；;、：:]+", clean) if x]
    output: list[str] = []
    for phrase in coarse or [clean]:
        remaining = phrase
        while len(remaining) > max_chars:
            cut = max_chars
            for candidate in range(max_chars, 3, -1):
                left, right = remaining[:candidate], remaining[candidate:]
                if any(term.startswith(right) and term in remaining for term in protected):
                    continue
                if any(left.endswith(term[:-1]) and right.startswith(term[-1:]) for term in protected if len(term) > 1):
                    continue
                if len(right) == 1:
                    continue
                cut = candidate
                break
            output.append(remaining[:cut])
            remaining = remaining[cut:]
        if remaining:
            if len(remaining) <= 2 and output and len(output[-1]) + len(remaining) <= max_chars:
                output[-1] += remaining
            else:
                output.append(remaining)
    expected = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9%]+", "", clean)
    actual = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9%]+", "", "".join(output))
    if expected != actual:
        raise ValueError("字幕安全切分发生文字丢失")
    return [item for item in output if item]

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
    sfx_level = "off"  # V21 quality gate: disable unapproved SFX bank
    sticker_level = "off"  # V21 quality gate: disable random stickers
    selected = _decorate_events(
        selected,
        duration,
        sfx_level=sfx_level,
        sticker_level=sticker_level,
    )
    return {
        "version": VERSION,
        "intensity": intensity,
        "sfx_level": sfx_level,
        "sticker_level": sticker_level,
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
    return clean[: max(3, min(7, int(limit or 7)))]


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
        raw_text = _clean_caption_text(str(item.get("text") or ""))
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
            y = 820 + (index % 3) * 125
            animation = rf"{{\an5\pos(540,{y})\fad(45,70)\fscx122\fscy122\t(0,150,\fscx100\fscy100)}}"
            style = "Impact"
        else:
            y = 1410 + (index % 2) * 92
            animation = rf"{{\an5\pos(540,{y})\fad(55,70)\fscx116\fscy116\t(0,130,\fscx100\fscy100)}}"
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


def _collect_sticker_inputs(plan: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for event in plan.get("events") or []:
        sticker = event.get("sticker")
        if not isinstance(sticker, dict):
            continue
        path = _sticker_root() / str(sticker.get("asset") or "")
        if path.is_file():
            result.append({"event": event, "sticker": sticker, "path": path})
    return result


def _collect_sfx_inputs(plan: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for event in plan.get("events") or []:
        sfx = event.get("sfx")
        if not isinstance(sfx, dict):
            continue
        path = _sfx_root() / str(sfx.get("asset") or "")
        if path.is_file():
            result.append({"event": event, "sfx": sfx, "path": path})
    return result


def _build_video_filters(
    work: Path,
    plan: dict[str, Any],
    ass_path: Path,
    sticker_inputs: list[dict[str, Any]],
    *,
    width: int = 1080,
    height: int = 1920,
) -> str:
    events = plan.get("events") or []
    limits = plan.get("limits") or {}
    zoom_strength = _safe_float(limits.get("zoom_strength"), 0.052)
    micro_strength = _safe_float(limits.get("micro_zoom_strength"), 0.016)
    zoom_terms: list[str] = []

    beats = [float(value) for value in (plan.get("caption_beats") or [])[:44]]
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
        "hook_punch": ("#FFE22E", 146, 470),
        "question_pulse": ("#FF4F66", 138, 610),
        "turn_focus": ("#FF9D36", 132, 455),
        "data_card": ("#FFE22E", 152, 560),
        "risk_alert": ("#FF4F4F", 142, 510),
        "comparison_card": ("#FFFFFF", 122, 410),
        "list_card": ("#FFE46B", 128, 420),
        "evidence_pip": ("#FFFFFF", 118, 400),
        "cta_tag": ("#FFFFFF", 126, 470),
        "keyword_focus": ("#FFE22E", 126, 430),
    }
    for index, (event, text_path) in enumerate(_event_text_files(work, plan), start=1):
        effect = str(event.get("effect") or "keyword_focus")
        color, font_size, y = palette.get(effect, palette["keyword_focus"])
        start = _safe_float(event.get("start"), 0.0)
        end = max(start + 0.28, _safe_float(event.get("end"), start + 0.9))
        next_label = f"vtxt{index}"
        x_expr = "(w-text_w)/2" if index % 3 else r"max(38\,(w-text_w)/2-170)"
        alpha = (
            f"if(lt(t,{start + 0.10:.3f}),(t-{start:.3f})/0.10,"
            f"if(gt(t,{end - 0.10:.3f}),({end:.3f}-t)/0.10,1))"
        )
        chain.append(
            f"[{current}]drawtext=textfile='{_ffmpeg_escape_path(text_path)}'{font_opt}:expansion=none:"
            f"fontsize={font_size}:fontcolor={color}:borderw=7:bordercolor=black@0.88:shadowx=2:shadowy=3:"
            f"x={x_expr}:y={y}:alpha='{alpha}':enable='between(t,{start:.3f},{end:.3f})'[{next_label}]"
        )
        current = next_label

    position_xy = {
        "left_top": ("62", "330"),
        "right_top": ("W-w-62", "350"),
        "left_mid": ("58", "760"),
        "right_mid": ("W-w-58", "790"),
    }
    for index, item in enumerate(sticker_inputs, start=1):
        sticker = item["sticker"]
        input_index = int(item["input_index"])
        start = _safe_float(sticker.get("start"), 0.0)
        end = max(start + 0.55, _safe_float(sticker.get("end"), start + 1.0))
        span = max(0.55, end - start)
        size = max(120, min(230, int(sticker.get("size") or 180)))
        position = str(sticker.get("position") or "right_top")
        x_expr, y_base = position_xy.get(position, position_xy["right_top"])
        sticker_label = f"sticker{index}"
        next_label = f"vstk{index}"
        chain.append(
            f"[{input_index}:v]format=rgba,scale={size}:{size}:force_original_aspect_ratio=decrease,"
            f"pad={size + 34}:{size + 34}:(ow-iw)/2:(oh-ih)/2:color=0x00000000,"
            f"rotate='0.045*sin(2*PI*t/1.18)':ow=rotw(iw):oh=roth(ih):c=none,"
            f"trim=duration={span:.3f},fade=t=in:st=0:d=0.10:alpha=1,"
            f"fade=t=out:st={max(0.1, span - 0.14):.3f}:d=0.14:alpha=1,"
            f"setpts=PTS-STARTPTS+{start:.3f}/TB[{sticker_label}]"
        )
        y_expr = f"{y_base}+14*sin(2*PI*(t-{start:.3f})/1.10)"
        chain.append(
            f"[{current}][{sticker_label}]overlay=x='{x_expr}':y='{y_expr}':"
            f"eof_action=pass:shortest=0:enable='between(t,{start:.3f},{end:.3f})'[{next_label}]"
        )
        current = next_label

    ass_escaped = _ffmpeg_escape_path(ass_path)
    chain.append(f"[{current}]ass='{ass_escaped}'[vout]")
    return ";".join(chain)


def _build_audio_filters(
    plan: dict[str, Any],
    *,
    has_audio: bool,
    sfx_inputs: list[dict[str, Any]],
) -> tuple[str, str | None]:
    if not has_audio:
        return "", None
    if not sfx_inputs:
        return "", "0:a?"

    parts: list[str] = ["[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[voice]"]
    labels: list[str] = ["voice"]
    for index, item in enumerate(sfx_inputs, start=1):
        event = item["event"]
        sfx = item["sfx"]
        input_index = int(item["input_index"])
        delay = int(max(0.0, _safe_float(event.get("start"), 0.0)) * 1000)
        gain = max(0.05, min(0.65, _safe_float(sfx.get("gain"), 0.32)))
        label = f"sfx{index}"
        parts.append(
            f"[{input_index}:a]aresample=48000,pan=stereo|c0=c0|c1=c0,"
            f"atrim=0:0.85,asetpts=PTS-STARTPTS,volume={gain:.4f},"
            f"afade=t=in:st=0:d=0.008,afade=t=out:st=0.55:d=0.18,"
            f"adelay={delay}|{delay}[{label}]"
        )
        labels.append(label)
    parts.append(
        "".join(f"[{label}]" for label in labels)
        + f"amix=inputs={len(labels)}:duration=first:dropout_transition=0:normalize=0,"
        "alimiter=limit=0.97,loudnorm=I=-16:LRA=7:TP=-1.5[aout]"
    )
    return ";".join(parts), "aout"


def render_dynamic_video(
    input_path: Path,
    output_path: Path,
    ass_path: Path,
    plan: dict[str, Any],
) -> dict[str, Any]:
    info = _probe(input_path)
    sticker_inputs = _collect_sticker_inputs(plan)
    sfx_inputs = _collect_sfx_inputs(plan)

    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(input_path),
    ]
    next_input_index = 1
    for item in sticker_inputs:
        item["input_index"] = next_input_index
        sticker = item["sticker"]
        span = max(0.6, _safe_float(sticker.get("end"), 1.0) - _safe_float(sticker.get("start"), 0.0))
        cmd += [
            "-loop",
            "1",
            "-framerate",
            f"{info['fps']:.3f}",
            "-t",
            f"{span:.3f}",
            "-i",
            str(item["path"]),
        ]
        next_input_index += 1
    for item in sfx_inputs:
        item["input_index"] = next_input_index
        cmd += ["-i", str(item["path"])]
        next_input_index += 1

    video_filters = _build_video_filters(input_path.parent, plan, ass_path, sticker_inputs)
    audio_filters, audio_label = _build_audio_filters(
        plan,
        has_audio=bool(info["has_audio"]),
        sfx_inputs=sfx_inputs,
    )
    filter_complex = video_filters + (";" + audio_filters if audio_filters else "")
    cmd += [
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
    cmd += ["-movflags", "+faststart", "-shortest", str(output_path)]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(cmd, check=True, timeout=7200)
    rendered = _probe(output_path)
    if rendered["duration"] < max(1.0, info["duration"] - 0.6):
        raise RuntimeError("动态精剪输出时长异常")
    return {
        "input": info,
        "output": rendered,
        "ffmpeg_command": cmd,
        "sticker_count": len(sticker_inputs),
        "sfx_count": len(sfx_inputs),
        "sticker_assets": [item["path"].name for item in sticker_inputs],
        "sfx_assets": [item["path"].name for item in sfx_inputs],
    }




def _apply_clean_single_caption_policy(plan: dict[str, Any]) -> dict[str, Any]:
    """V21: one ASS subtitle layer only; no duplicate text cards or random stickers."""
    cleaned = dict(plan)
    cleaned["events"] = []
    cleaned["stickers"] = []
    cleaned["sfx_events"] = []
    cleaned["clean_render_policy"] = {
        "single_caption_layer": True,
        "duplicate_text_overlays": False,
        "random_stickers": False,
        "sfx_temporarily_disabled": True,
    }
    return cleaned

def _run_dynamic(settings: Any, proxy_job_id: str, payload: dict[str, Any]) -> None:
    classic = _classic()
    work = _work_dir(settings, proxy_job_id)
    try:
        _update_proxy(settings, proxy_job_id, status="running", stage="semantic_plan", progress=2, message="正在读取上一页镜头并生成语义切镜计划")
        from app.services.semantic_shot_director_v10_40_8_19 import prepare_classic_payload

        prepared = prepare_classic_payload(settings, payload, proxy_job_id)
        classic_payload = dict(prepared["payload"])
        semantic_plan = dict(prepared["plan"])
        classic_payload["dynamic_v2_parent_job_id"] = proxy_job_id
        _update_proxy(
            settings,
            proxy_job_id,
            semantic_shot_plan=semantic_plan,
            asset_usage_report=semantic_plan.get("usage_report") or {},
            message=(
                f"已按上一页锁定 {len(semantic_plan.get('clips') or [])} 个镜头"
                if semantic_plan.get("locked")
                else f"已生成 {len(semantic_plan.get('clips') or [])} 个语义镜头，优先使用未重复素材"
            ),
        )
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

        applied_clips = (
            ((base.get("edit_plan") or {}).get("clips") if isinstance(base.get("edit_plan"), dict) else None)
            or base.get("clips")
            or ((classic_payload.get("edit_plan") or {}).get("clips") if isinstance(classic_payload.get("edit_plan"), dict) else None)
            or []
        )
        if hasattr(classic, "_record_asset_usage") and applied_clips:
            classic._record_asset_usage(settings, proxy_job_id, applied_clips)

        source_url = str(base.get("no_subtitle_video_url") or base.get("raw_video_url") or base.get("video_url") or "")
        if not source_url:
            raise RuntimeError("稳定底片没有可用视频地址")
        source_suffix = Path(urllib.parse.urlparse(source_url).path).suffix or ".mp4"
        source_path = _download(source_url, work / f"classic_base{source_suffix}")
        info = _probe(source_path)
        duration = max(
            0.1,
            _safe_float(info.get("audio_duration"), 0.0)
            or _safe_float(base.get("duration_seconds"), info["duration"])
            or info["duration"],
        )
        timings = _normalize_timings(payload, base, duration)
        intensity = str(payload.get("dynamic_edit_intensity") or "balanced")
        style_id = str(payload.get("dynamic_subtitle_style") or "dynamic_white_yellow")
        sfx_level = str(payload.get("dynamic_sfx_level") or "balanced")
        sticker_level = str(payload.get("dynamic_sticker_level") or "balanced")
        payload["ai_shot_beats"] = semantic_plan.get("beats") or []
        plan = build_dynamic_plan(payload, timings, duration, intensity=intensity)
        plan = _apply_clean_single_caption_policy(plan)  # CLEAN_SINGLE_CAPTION_POLICY_V21
        plan["ai_shot_beats"] = semantic_plan.get("beats") or []
        plan["ai_director_report"] = semantic_plan.get("director_report") or {}
        plan["subtitle_style"] = style_id
        ass_path = write_dynamic_ass(work / "dynamic_subtitles.ass", timings, plan.get("keywords") or [], style_id=style_id)
        plan_path = work / "dynamic_effect_timeline.json"
        plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

        _update_proxy(settings, proxy_job_id, stage="dynamic_render", progress=86, message="正在渲染可调字幕、多样动效、低音量多样音效和安全区贴纸", dynamic_effect_timeline=plan)
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
            "safe_effects": ["semantic_zoom", "large_kinetic_captions", "transparent_theme_stickers", "real_sfx_assets", "dynamic_ass_subtitles"],
            "sfx_level": sfx_level,
            "sticker_level": sticker_level,
            "sfx_count": render_report.get("sfx_count", 0),
            "sticker_count": render_report.get("sticker_count", 0),
            "shot_plan_applied": bool((classic_payload.get("edit_plan") or {}).get("clips")),
            "locked_shot_plan_count": len((classic_payload.get("edit_plan") or {}).get("clips") or []),
            "semantic_shot_plan": semantic_plan,
            "asset_usage_report": semantic_plan.get("usage_report") or {},
            "audio_tail_guard": render_report.get("audio_tail_guard") or {},
            "person_cutout": {"requested": False, "status": "deferred_until_mask_quality_gate"},
            "render": render_report,
            "created_at": _now(),
        }
        report_path = work / "dynamic_edit_report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        _update_proxy(settings, proxy_job_id, stage="upload", progress=96, message="正在上传动态精剪版并保留稳定版")
        dynamic_url = classic._url(settings, output_path, "videos/existing-edit-v2/final")
        classic_url = str(base.get("video_url") or base.get("output_url") or source_url)
        from app.services.semantic_shot_director_v10_40_8_19 import record_success

        usage_written = record_success(
            settings,
            proxy_job_id,
            list((semantic_plan or {}).get("clips") or []),
        )
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
            dynamic_sfx_level=sfx_level,
            dynamic_sticker_level=sticker_level,
            shot_plan_applied=bool((classic_payload.get("edit_plan") or {}).get("clips")),
            locked_shot_plan_count=len((classic_payload.get("edit_plan") or {}).get("clips") or []),
            semantic_shot_plan=semantic_plan,
            asset_usage_report=usage_written,
            audio_tail_guard=render_report.get("audio_tail_guard") or {},
            base_job_id=classic_job_id,
            fal_used=False,
            billing_guard="dynamic_v2_wraps_existing_edit_no_fal",
            finished_at=_now(),
        )
    except Exception as exc:
        error_type = type(exc).__name__
        error_detail = " ".join(str(exc).split())[:240] or error_type
        _update_proxy(
            settings,
            proxy_job_id,
            status="failed",
            stage="failed",
            progress=0,
            error_type=error_type,
            error=error_detail,
            message=(
                f"动态精剪 V2 失败：{error_type}: "
                f"{error_detail}；A10-R4 原版仍可用"
            ),
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
        "dynamic_sfx_level": str(payload.get("dynamic_sfx_level") or "balanced"),
        "dynamic_sticker_level": str(payload.get("dynamic_sticker_level") or "balanced"),
        "dynamic_visual_pace": str(payload.get("dynamic_visual_pace") or "balanced"),
        "dynamic_caption_size": str(payload.get("dynamic_caption_size") or "standard"),
        "dynamic_caption_motion": str(payload.get("dynamic_caption_motion") or "smart_mix"),
        "dynamic_caption_position": str(payload.get("dynamic_caption_position") or "auto"),
        "dynamic_sfx_pack": str(payload.get("dynamic_sfx_pack") or "smart_mix"),
        "dynamic_sticker_layout": str(payload.get("dynamic_sticker_layout") or "auto_safe"),
        "dynamic_sticker_style": str(payload.get("dynamic_sticker_style") or "smart_mix"),
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
            "sfx_levels": SFX_LEVELS,
            "sticker_levels": STICKER_LEVELS,
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
                "dynamic_dense_base_clips": False,
                "semantic_scene_boundaries": True,
                "deepseek_ai_beat_director": True,
                "entity_burst_one_entity_one_shot": True,
                "professional_cc0_sfx_bank": True,
                "locked_previous_page_shot_plan": True,
                "persistent_asset_usage_recorder": True,
                "audio_tail_guard": True,
                "phrase_safe_caption_segmentation": True,
                "reference_subtitle_pack": True,
                "keyword_highlight": True,
                "micro_sfx": False,
                "real_sfx_assets": True,
                "semantic_transparent_stickers": True,
                "large_caption_pack": True,
                "person_cutout_quality_gate": "phase_2",
                "fal_forbidden": True,
            },
        }

    @app.get("/api/video/existing-edit-v2/presets")
    def presets() -> dict[str, Any]:
        return {"ok": True, "version": VERSION, "edit_presets": EDIT_PRESETS, "subtitle_presets": SUBTITLE_PRESETS, "sfx_levels": SFX_LEVELS, "sticker_levels": STICKER_LEVELS}

    @app.post("/api/video/existing-edit-v2/plan")
    async def plan(request: Request) -> dict[str, Any]:
        payload = await request.json()
        duration = _safe_float(payload.get("target_duration_seconds"), 30.0)
        timings = _normalize_timings(payload, {}, duration)
        intensity = str(request.query_params.get("intensity") or payload.get("dynamic_edit_intensity") or "balanced")
        payload["dynamic_sfx_level"] = str(request.query_params.get("sfx_level") or payload.get("dynamic_sfx_level") or "balanced")
        payload["dynamic_sticker_level"] = str(request.query_params.get("sticker_level") or payload.get("dynamic_sticker_level") or "balanced")
        payload["dynamic_visual_pace"] = "ai_auto"
        payload["dynamic_caption_size"] = str(request.query_params.get("caption_size") or payload.get("dynamic_caption_size") or "standard")
        payload["dynamic_caption_motion"] = str(request.query_params.get("caption_motion") or payload.get("dynamic_caption_motion") or "smart_mix")
        payload["dynamic_caption_position"] = str(request.query_params.get("caption_position") or payload.get("dynamic_caption_position") or "auto")
        payload["dynamic_sfx_pack"] = str(request.query_params.get("sfx_pack") or payload.get("dynamic_sfx_pack") or "smart_mix")
        payload["dynamic_sticker_layout"] = str(request.query_params.get("sticker_layout") or payload.get("dynamic_sticker_layout") or "auto_safe")
        payload["dynamic_sticker_style"] = str(request.query_params.get("sticker_style") or payload.get("dynamic_sticker_style") or "smart_mix")
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
            payload["dynamic_sfx_level"] = str(request.query_params.get("sfx_level") or payload.get("dynamic_sfx_level") or "balanced")
            payload["dynamic_sticker_level"] = str(request.query_params.get("sticker_level") or payload.get("dynamic_sticker_level") or "balanced")
            payload["dynamic_visual_pace"] = "ai_auto"
            payload["dynamic_caption_size"] = str(request.query_params.get("caption_size") or payload.get("dynamic_caption_size") or "standard")
            payload["dynamic_caption_motion"] = str(request.query_params.get("caption_motion") or payload.get("dynamic_caption_motion") or "smart_mix")
            payload["dynamic_caption_position"] = str(request.query_params.get("caption_position") or payload.get("dynamic_caption_position") or "auto")
            payload["dynamic_sfx_pack"] = str(request.query_params.get("sfx_pack") or payload.get("dynamic_sfx_pack") or "smart_mix")
            payload["dynamic_sticker_layout"] = str(request.query_params.get("sticker_layout") or payload.get("dynamic_sticker_layout") or "auto_safe")
            payload["dynamic_sticker_style"] = str(request.query_params.get("sticker_style") or payload.get("dynamic_sticker_style") or "smart_mix")
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


# =============================================================================
# V10.40.8.16 BALANCED EDITING STUDIO OVERRIDES
# =============================================================================
V16_MARKER = "V10_40_8_16_BALANCED_EDITING_STUDIO"
_V16_CONTEXT = threading.local()

PACE_PROFILES: dict[str, dict[str, Any]] = {
    "calm": {"label": "舒缓讲解", "seconds_per_clip": 3.20, "max_clips": 16},
    "balanced": {"label": "均衡精剪", "seconds_per_clip": 2.55, "max_clips": 22},
    "punchy": {"label": "紧凑口播", "seconds_per_clip": 2.10, "max_clips": 27},
}

EDIT_PRESETS = {
    "restrained": {
        "label": "克制",
        "description": "主要动效少而准，不让字幕、贴纸和镜头同时抢画面。",
        "max_major_effects_per_30s": 5,
        "min_effect_gap_seconds": 3.80,
        "zoom_strength": 0.026,
        "micro_zoom_strength": 0.006,
    },
    "balanced": {
        "label": "均衡",
        "description": "镜头约 2.5 秒一换，字幕动效更丰富，但主要重击保持间隔。",
        "max_major_effects_per_30s": 7,
        "min_effect_gap_seconds": 2.80,
        "zoom_strength": 0.038,
        "micro_zoom_strength": 0.008,
    },
    "strong": {
        "label": "加强",
        "description": "适合强钩子短视频，但仍限制镜头和重音密度。",
        "max_major_effects_per_30s": 10,
        "min_effect_gap_seconds": 2.10,
        "zoom_strength": 0.048,
        "micro_zoom_strength": 0.010,
    },
}

SFX_LEVELS = {
    "off": {"label": "关闭", "volume": 0.0, "max_per_30s": 0, "min_gap": 99.0},
    "light": {"label": "轻柔", "volume": 0.09, "max_per_30s": 3, "min_gap": 3.80},
    "balanced": {"label": "均衡", "volume": 0.15, "max_per_30s": 5, "min_gap": 3.00},
    "strong": {"label": "明显", "volume": 0.22, "max_per_30s": 7, "min_gap": 2.45},
}

STICKER_LEVELS = {
    "off": {"label": "关闭", "max_per_30s": 0, "min_gap": 99.0},
    "light": {"label": "少量", "max_per_30s": 2, "min_gap": 8.0},
    "balanced": {"label": "均衡", "max_per_30s": 3, "min_gap": 6.0},
    "rich": {"label": "丰富", "max_per_30s": 5, "min_gap": 4.5},
}

CAPTION_SIZE_PRESETS = {
    "compact": 92,
    "standard": 110,
    "large": 128,
    "xlarge": 146,
}

CAPTION_MOTION_PRESETS = {
    "smart_mix": "智能混合",
    "pop_bounce": "弹跳放大",
    "slide_mix": "左右滑入",
    "lift_fade": "上浮淡入",
    "elastic": "弹性回弹",
    "rotate_snap": "轻旋归位",
    "typewriter": "逐字扫入",
    "impact_cut": "关键词重击",
    "clean_fade": "极简淡入",
}

CAPTION_POSITION_PRESETS = {
    "auto": "智能避让",
    "lower": "底部安全区",
    "middle": "中部强调区",
}

SFX_VARIANT_BANKS: dict[str, list[tuple[str, float]]] = {
    "hook": [
        ("hook_low_hit_a.wav", 0.86),
        ("hook_low_hit_b.wav", 0.78),
        ("hook_snap.wav", 0.74),
    ],
    "question": [
        ("question_soft_ping.wav", 0.68),
        ("question_pluck.wav", 0.62),
        ("question_rise.wav", 0.58),
    ],
    "turn": [
        ("turn_air_whoosh.wav", 0.66),
        ("turn_reverse_sweep.wav", 0.60),
        ("turn_soft_swipe.wav", 0.56),
    ],
    "data": [
        ("data_tick_a.wav", 0.64),
        ("data_tick_b.wav", 0.58),
        ("data_drop.wav", 0.60),
    ],
    "risk": [
        ("risk_low_alert.wav", 0.62),
        ("risk_tap.wav", 0.55),
        ("risk_short_alarm.wav", 0.50),
    ],
    "comparison": [
        ("compare_slide_a.wav", 0.54),
        ("compare_slide_b.wav", 0.50),
        ("compare_toggle.wav", 0.48),
    ],
    "list": [
        ("list_click_a.wav", 0.50),
        ("list_click_b.wav", 0.46),
        ("list_wood_tap.wav", 0.44),
    ],
    "evidence": [
        ("evidence_camera_soft.wav", 0.48),
        ("evidence_confirm.wav", 0.46),
    ],
    "cta": [
        ("cta_chime_a.wav", 0.58),
        ("cta_chime_b.wav", 0.54),
        ("cta_confirm.wav", 0.50),
    ],
}

ICON_STICKERS = {
    "house", "office", "key", "pin", "map", "palm", "money", "chart",
    "metro", "car", "shopping", "food", "construction", "people", "warning",
    "search", "clipboard", "check", "camera", "comment", "bell", "point", "question",
}
DOODLE_STICKERS = {
    "doodle_arrow_curve", "doodle_arrow_up", "doodle_burst", "doodle_brackets",
    "doodle_circle", "doodle_check", "doodle_route", "doodle_sparkles",
    "doodle_underline", "doodle_warning", "doodle_question", "doodle_price_tag",
}

_V15_BUILD_DYNAMIC_PLAN = build_dynamic_plan


def _v16_context(payload: dict[str, Any]) -> dict[str, Any]:
    size_raw = str(payload.get("dynamic_caption_size") or "standard")
    try:
        size_value = max(84, min(160, int(float(size_raw))))
    except Exception:
        size_value = CAPTION_SIZE_PRESETS.get(size_raw, 110)
    return {
        "visual_pace": str(payload.get("dynamic_visual_pace") or "balanced"),
        "caption_size": size_value,
        "caption_motion": str(payload.get("dynamic_caption_motion") or "smart_mix"),
        "caption_position": str(payload.get("dynamic_caption_position") or "auto"),
        "sfx_pack": str(payload.get("dynamic_sfx_pack") or "smart_mix"),
        "sticker_layout": str(payload.get("dynamic_sticker_layout") or "auto_safe"),
        "sticker_style": str(payload.get("dynamic_sticker_style") or "smart_mix"),
    }


def _v16_semantic_roles() -> set[str]:
    return {"hook", "question", "turn", "data", "risk", "comparison", "list", "evidence", "cta"}


def _v16_choose_variant(role: str, event: dict[str, Any], index: int, last_asset: str) -> tuple[str, float]:
    options = list(SFX_VARIANT_BANKS.get(role) or [])
    if not options:
        return "", 0.0
    context = getattr(_V16_CONTEXT, "config", {}) or {}
    pack = str(context.get("sfx_pack") or "pro_short_video")
    allowed = SFX_PACK_FILES.get(pack)
    if allowed:
        filtered = [item for item in options if item[0] in allowed]
        if filtered:
            options = filtered
    ordered = sorted(
        options,
        key=lambda item: hashlib.sha256(
            f"{pack}:{event.get('id')}:{event.get('source_text')}:{index}:{item[0]}".encode("utf-8")
        ).digest(),
    )
    for asset, role_gain in ordered:
        if asset != last_asset and (_sfx_root() / asset).exists():
            return asset, role_gain
    for asset, role_gain in ordered:
        if (_sfx_root() / asset).exists():
            return asset, role_gain
    return "", 0.0


def _v16_choose_sticker(event: dict[str, Any], index: int, style: str, last_asset: str) -> str:
    base = _choose_sticker(event, index)
    role = str(event.get("role") or "knowledge")
    text = str(event.get("source_text") or "")
    doodle_by_role = {
        "hook": ["doodle_burst", "doodle_arrow_curve", "doodle_sparkles"],
        "question": ["doodle_question", "doodle_circle", "doodle_arrow_curve"],
        "turn": ["doodle_arrow_curve", "doodle_brackets", "doodle_underline"],
        "data": ["doodle_price_tag", "doodle_circle", "doodle_underline"],
        "risk": ["doodle_warning", "doodle_brackets", "doodle_circle"],
        "comparison": ["doodle_brackets", "doodle_arrow_up", "doodle_underline"],
        "list": ["doodle_check", "doodle_underline", "doodle_brackets"],
        "evidence": ["doodle_circle", "doodle_arrow_curve", "doodle_sparkles"],
        "cta": ["doodle_arrow_up", "doodle_sparkles", "doodle_check"],
    }
    if style == "icons":
        candidates = [base]
    elif style == "doodles":
        candidates = doodle_by_role.get(role, ["doodle_sparkles", "doodle_underline"])
    else:
        candidates = [base] + doodle_by_role.get(role, [])
        if re.search(r"价格|预算|钱|回报|收益", text):
            candidates += ["money", "chart", "doodle_price_tag"]
        if re.search(r"区域|位置|交通|路线", text):
            candidates += ["pin", "map", "doodle_route", "doodle_arrow_curve"]
    candidates = [x for x in candidates if x and x != last_asset and (_sticker_root() / f"{x}.png").exists()]
    return _deterministic_choice(candidates, f"v16:{event.get('id')}:{index}:{style}") if candidates else ""


def _v16_sticker_position(layout: str, event: dict[str, Any], index: int, last_side: str) -> tuple[str, str]:
    if layout == "top":
        choices = ["upper_left", "upper_right"]
    elif layout == "side":
        choices = ["side_left", "side_right"]
    else:
        # Default auto mode never uses the middle center or the subtitle zone.
        choices = ["upper_left", "upper_right", "side_left", "side_right"]
        if str(event.get("role")) in {"hook", "question", "risk", "data"}:
            choices = ["upper_left", "upper_right"]
    filtered = [item for item in choices if ("left" if "left" in item else "right") != last_side]
    selected = _deterministic_choice(filtered or choices, f"position:{event.get('id')}:{index}")
    return selected, ("left" if "left" in selected else "right")


def _decorate_events(
    events: list[dict[str, Any]],
    duration: float,
    *,
    sfx_level: str,
    sticker_level: str,
) -> list[dict[str, Any]]:
    result = [dict(item) for item in events]
    context = getattr(_V16_CONTEXT, "config", {}) or {}
    sfx_cfg = SFX_LEVELS.get(sfx_level) or SFX_LEVELS["balanced"]
    sticker_cfg = STICKER_LEVELS.get(sticker_level) or STICKER_LEVELS["balanced"]

    max_sfx = max(0, int(math.ceil(max(1.0, duration) / 30.0 * int(sfx_cfg["max_per_30s"]))))
    sfx_gap = float(sfx_cfg["min_gap"])
    used_sfx = 0
    last_sfx_start = -999.0
    last_sfx_asset = ""
    for index, event in enumerate(result):
        role = str(event.get("role") or "knowledge")
        start = _safe_float(event.get("start"), 0.0)
        if used_sfx >= max_sfx:
            break
        if role not in _v16_semantic_roles() or start - last_sfx_start < sfx_gap:
            continue
        asset, role_gain = _v16_choose_variant(role, event, index, last_sfx_asset)
        if not asset or float(sfx_cfg["volume"]) <= 0:
            continue
        event["sfx"] = {
            "asset": asset,
            "gain": round(float(sfx_cfg["volume"]) * role_gain, 4),
            "role": role,
        }
        used_sfx += 1
        last_sfx_start = start
        last_sfx_asset = asset

    max_stickers = max(0, int(math.ceil(max(1.0, duration) / 30.0 * int(sticker_cfg["max_per_30s"]))))
    sticker_gap = float(sticker_cfg["min_gap"])
    sticker_style = str(context.get("sticker_style") or "smart_mix")
    sticker_layout = str(context.get("sticker_layout") or "auto_safe")
    used_stickers = 0
    last_sticker_start = -999.0
    last_sticker_asset = ""
    last_side = ""
    for index, event in enumerate(result):
        if used_stickers >= max_stickers:
            break
        start = _safe_float(event.get("start"), 0.0)
        role = str(event.get("role") or "knowledge")
        if role == "knowledge" or start - last_sticker_start < sticker_gap:
            continue
        asset = _v16_choose_sticker(event, index, sticker_style, last_sticker_asset)
        if not asset:
            continue
        position, side = _v16_sticker_position(sticker_layout, event, index, last_side)
        event_end = max(start + 0.85, _safe_float(event.get("end"), start + 1.25))
        span = min(1.35, max(0.90, event_end - start))
        event["sticker"] = {
            "asset": f"{asset}.png",
            "position": position,
            "size": 132 + (index % 3) * 10,
            "start": round(start, 3),
            "end": round(min(duration, start + span), 3),
        }
        used_stickers += 1
        last_sticker_start = start
        last_sticker_asset = asset
        last_side = side
    return result


def build_dynamic_plan(
    payload: dict[str, Any],
    timings: list[dict[str, Any]],
    duration: float,
    *,
    intensity: str = "balanced",
) -> dict[str, Any]:
    context = _v16_context(payload)
    _V16_CONTEXT.config = context
    plan = _V15_BUILD_DYNAMIC_PLAN(payload, timings, duration, intensity=intensity)
    visual_pace = context["visual_pace"] if context["visual_pace"] in PACE_PROFILES else "balanced"
    plan["version"] = VERSION
    plan["visual_pace"] = visual_pace
    plan["caption_size"] = context["caption_size"]
    plan["caption_motion"] = context["caption_motion"]
    plan["caption_position"] = context["caption_position"]
    plan["sfx_pack"] = context["sfx_pack"]
    plan["sticker_layout"] = context["sticker_layout"]
    plan["sticker_style"] = context["sticker_style"]
    plan["pace_profile"] = PACE_PROFILES[visual_pace]
    return plan


def _v16_y_position(position: str, role: str, index: int) -> int:
    if position == "middle":
        return 900 + (index % 2) * 110
    if position == "lower":
        return 1435 + (index % 2) * 90
    if role in {"hook", "question", "data", "risk", "turn"}:
        return 820 + (index % 2) * 120
    return 1435 + (index % 2) * 88


def _v16_karaoke(text: str) -> str:
    chars = []
    for char in text:
        chars.append(r"{\kf7}" + char)
    return "".join(chars)


def _v16_motion(
    motion: str,
    role: str,
    index: int,
    x: int,
    y: int,
    text: str,
) -> tuple[str, str]:
    choices = ["pop_bounce", "slide_left", "slide_right", "lift_fade", "elastic", "rotate_snap", "clean_fade"]
    if motion == "smart_mix":
        if role in {"hook", "data", "risk"}:
            motion = ["pop_bounce", "elastic", "impact_cut"][index % 3]
        elif role in {"question", "turn", "comparison"}:
            motion = ["slide_left", "slide_right", "rotate_snap"][index % 3]
        else:
            motion = choices[index % len(choices)]
    elif motion == "slide_mix":
        motion = "slide_left" if index % 2 == 0 else "slide_right"

    if motion == "typewriter":
        return rf"{{\an5\pos({x},{y})\fad(45,65)}}", _v16_karaoke(text)
    if motion == "slide_left":
        return rf"{{\an5\move(-180,{y},{x},{y},0,210)\fad(30,70)}}", text
    if motion == "slide_right":
        return rf"{{\an5\move(1260,{y},{x},{y},0,210)\fad(30,70)}}", text
    if motion == "lift_fade":
        return rf"{{\an5\move({x},{y + 105},{x},{y},0,190)\fad(55,80)}}", text
    if motion == "elastic":
        return rf"{{\an5\pos({x},{y})\fscx58\fscy58\t(0,115,\fscx118\fscy118)\t(115,235,\fscx100\fscy100)\fad(30,70)}}", text
    if motion == "rotate_snap":
        return rf"{{\an5\pos({x},{y})\frz-9\fscx112\fscy112\t(0,185,\frz0\fscx100\fscy100)\fad(35,70)}}", text
    if motion == "impact_cut":
        return rf"{{\an5\pos({x},{y})\fscx150\fscy150\t(0,105,\fscx96\fscy96)\t(105,180,\fscx100\fscy100)\fad(20,55)}}", text
    if motion == "clean_fade":
        return rf"{{\an5\pos({x},{y})\fad(110,110)}}", text
    return rf"{{\an5\pos({x},{y})\fscx132\fscy132\t(0,155,\fscx100\fscy100)\fad(35,70)}}", text


def write_dynamic_ass(
    destination: Path,
    timings: list[dict[str, Any]],
    keywords: list[str],
    *,
    style_id: str,
) -> Path:
    preset = SUBTITLE_PRESETS.get(style_id) or SUBTITLE_PRESETS["dynamic_white_yellow"]
    context = getattr(_V16_CONTEXT, "config", {}) or {}
    base_size = int(context.get("caption_size") or preset.get("font_size") or 110)
    base_size = max(84, min(160, base_size))
    impact_size = min(176, max(base_size + 22, int(base_size * 1.28)))
    motion = str(context.get("caption_motion") or "smart_mix")
    position = str(context.get("caption_position") or "auto")
    font_name = "Noto Sans CJK SC"
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes
WrapStyle: 2

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Dynamic,{font_name},{base_size},{preset['primary']},{preset['highlight']},{preset['outline']},&H00000000,-1,0,0,0,100,100,1.0,0,1,{preset['outline_width']},{preset['shadow']},5,45,45,0,1
Style: Impact,{font_name},{impact_size},{preset['primary']},{preset['highlight']},{preset['outline']},&H00000000,-1,0,0,0,100,100,1.1,0,1,{preset['outline_width'] + 1},{preset['shadow']},5,40,40,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    last_motion = ""
    for index, item in enumerate(timings):
        start = _safe_float(item.get("start"), 0.0)
        end = max(start + 0.30, _safe_float(item.get("end"), start + 0.85))
        raw_text = _clean_caption_text(str(item.get("text") or ""))
        role = _classify(raw_text)
        impact = False  # V21 no second giant text layer
        style = "Impact" if impact else "Dynamic"
        text = _highlight_ass(raw_text, keywords, str(preset["highlight"]))
        if impact:
            role_color = {
                "data": preset.get("highlight"),
                "risk": "&H00004BFF",
                "question": preset.get("accent"),
                "turn": preset.get("accent"),
                "hook": preset.get("highlight"),
            }.get(role, preset.get("highlight"))
            text = rf"{{\c{role_color}}}{text}"
        y = _v16_y_position(position, role, index)
        selected_motion = motion
        if motion == "smart_mix":
            candidates = ["clean_fade", "lift_fade"]
            selected_motion = candidates[index % len(candidates)]
            if selected_motion == last_motion:
                selected_motion = candidates[(index + 1) % len(candidates)]
        animation, animated_text = _v16_motion(selected_motion, role, index, 540, y, text)
        last_motion = selected_motion
        lines.append(
            f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},{style},,0,0,0,,{animation}{animated_text}\n"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("".join(lines), encoding="utf-8-sig")
    return destination


def _build_video_filters(
    work: Path,
    plan: dict[str, Any],
    ass_path: Path,
    sticker_inputs: list[dict[str, Any]],
    *,
    width: int = 1080,
    height: int = 1920,
) -> str:
    events = plan.get("events") or []
    limits = plan.get("limits") or {}
    zoom_strength = _safe_float(limits.get("zoom_strength"), 0.038)
    micro_strength = _safe_float(limits.get("micro_zoom_strength"), 0.008)
    zoom_terms: list[str] = []

    # Caption animation does not force a shot change. Micro zoom occurs only on
    # every fourth caption beat, preventing the restless V15 feeling.
    beats = [float(value) for value in (plan.get("caption_beats") or [])[:48]]
    for index, start in enumerate(beats):
        if index % 4:
            continue
        span = 0.88
        zoom_terms.append(
            f"+{micro_strength:.4f}*between(t,{start:.3f},{start + span:.3f})*sin(PI*(t-{start:.3f})/{span:.3f})"
        )
    for event in events:
        if event.get("effect") not in {"hook_punch", "question_pulse", "turn_focus", "risk_alert", "data_card"}:
            continue
        start = _safe_float(event.get("start"), 0.0)
        end = max(start + 0.35, _safe_float(event.get("end"), start + 0.95))
        span = max(0.25, end - start)
        strength = zoom_strength * (1.05 if event.get("effect") in {"hook_punch", "data_card"} else 0.70)
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
        "hook_punch": ("#FFE22E", 142, 470),
        "question_pulse": ("#FF6A72", 132, 590),
        "turn_focus": ("#FF9D36", 128, 470),
        "data_card": ("#FFE22E", 148, 560),
        "risk_alert": ("#FF5757", 138, 510),
    }
    focus_events = [
        (event, text_path)
        for event, text_path in _event_text_files(work, plan)
        if str(event.get("effect") or "") in palette
    ]
    focus_limit = max(2, int(math.ceil(max(1.0, _safe_float(plan.get("duration"), 30.0)) / 30.0 * 4)))
    for index, (event, text_path) in enumerate(focus_events[:focus_limit], start=1):
        effect = str(event.get("effect") or "hook_punch")
        color, font_size, y = palette[effect]
        start = _safe_float(event.get("start"), 0.0)
        end = max(start + 0.30, _safe_float(event.get("end"), start + 0.95))
        next_label = f"vtxt{index}"
        x_expr = "(w-text_w)/2" if index % 2 else r"max(45\,(w-text_w)/2-145)"
        alpha = (
            f"if(lt(t,{start + 0.10:.3f}),(t-{start:.3f})/0.10,"
            f"if(gt(t,{end - 0.10:.3f}),({end:.3f}-t)/0.10,1))"
        )
        chain.append(
            f"[{current}]drawtext=textfile='{_ffmpeg_escape_path(text_path)}'{font_opt}:expansion=none:"
            f"fontsize={font_size}:fontcolor={color}:borderw=7:bordercolor=black@0.86:shadowx=2:shadowy=3:"
            f"x={x_expr}:y={y}:alpha='{alpha}':enable='between(t,{start:.3f},{end:.3f})'[{next_label}]"
        )
        current = next_label

    position_xy = {
        "upper_left": ("54", "250"),
        "upper_right": ("W-w-54", "270"),
        "side_left": ("48", "560"),
        "side_right": ("W-w-48", "580"),
    }
    for index, item in enumerate(sticker_inputs, start=1):
        sticker = item["sticker"]
        input_index = int(item["input_index"])
        start = _safe_float(sticker.get("start"), 0.0)
        end = max(start + 0.70, _safe_float(sticker.get("end"), start + 1.05))
        span = max(0.70, end - start)
        size = max(105, min(172, int(sticker.get("size") or 140)))
        position = str(sticker.get("position") or "upper_right")
        x_expr, y_base = position_xy.get(position, position_xy["upper_right"])
        sticker_label = f"sticker{index}"
        next_label = f"vstk{index}"
        chain.append(
            f"[{input_index}:v]format=rgba,scale={size}:{size}:force_original_aspect_ratio=decrease,"
            f"pad={size + 22}:{size + 22}:(ow-iw)/2:(oh-ih)/2:color=0x00000000,"
            f"rotate='0.020*sin(2*PI*t/1.45)':ow=rotw(iw):oh=roth(ih):c=none,"
            f"trim=duration={span:.3f},fade=t=in:st=0:d=0.12:alpha=1,"
            f"fade=t=out:st={max(0.1, span - 0.16):.3f}:d=0.16:alpha=1,"
            f"setpts=PTS-STARTPTS+{start:.3f}/TB[{sticker_label}]"
        )
        y_expr = f"{y_base}+7*sin(2*PI*(t-{start:.3f})/1.35)"
        chain.append(
            f"[{current}][{sticker_label}]overlay=x='{x_expr}':y='{y_expr}':"
            f"eof_action=pass:shortest=0:enable='between(t,{start:.3f},{end:.3f})'[{next_label}]"
        )
        current = next_label

    ass_escaped = _ffmpeg_escape_path(ass_path)
    chain.append(f"[{current}]ass='{ass_escaped}'[vout]")
    return ";".join(chain)


def _build_audio_filters(
    plan: dict[str, Any],
    *,
    has_audio: bool,
    sfx_inputs: list[dict[str, Any]],
) -> tuple[str, str | None]:
    if not has_audio:
        return "", None
    if not sfx_inputs:
        return "", "0:a?"

    parts: list[str] = ["[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[voice]"]
    labels: list[str] = ["voice"]
    for index, item in enumerate(sfx_inputs, start=1):
        event = item["event"]
        sfx = item["sfx"]
        input_index = int(item["input_index"])
        delay = int(max(0.0, _safe_float(event.get("start"), 0.0)) * 1000)
        # V16 caps effective SFX gain far below V15. Transient sounds remain
        # audible but no longer dominate narration.
        gain = max(0.025, min(0.22, _safe_float(sfx.get("gain"), 0.10)))
        label = f"sfx{index}"
        parts.append(
            f"[{input_index}:a]aresample=48000,pan=stereo|c0=c0|c1=c0,"
            f"atrim=0:0.72,asetpts=PTS-STARTPTS,highpass=f=80,lowpass=f=12500,"
            f"volume={gain:.4f},afade=t=in:st=0:d=0.012,"
            f"afade=t=out:st=0.48:d=0.18,adelay={delay}|{delay}[{label}]"
        )
        labels.append(label)
    parts.append(
        "".join(f"[{label}]" for label in labels)
        + f"amix=inputs={len(labels)}:duration=first:dropout_transition=0:normalize=0,"
        "alimiter=limit=0.94,loudnorm=I=-16:LRA=7:TP=-1.8[aout]"
    )
    return ";".join(parts), "aout"



# =============================================================================
# V10.40.8.17 SEMANTIC SHOT DIRECTOR OVERRIDES
# =============================================================================
V17_MARKER = "V10_40_8_17_SEMANTIC_SHOT_DIRECTOR"

V17_PROTECTED_CAPTION_PHRASES = tuple(sorted({
    "吉隆坡", "马来西亚", "第一眼", "真实价格", "真实用途", "先看你的真实用途",
    "自住还是出租", "生活半径", "交通和生活半径", "产权校验", "退出路径",
    "产权校验和退出路径", "租客来源", "交付周期", "交通规划", "生活配套",
    "现金流", "回报率", "预算区间", "区域选择", "投资逻辑", "未来规划",
    "不要只看价格", "先看区域和用途", "再看交通", "提前想清楚",
}, key=len, reverse=True))

V17_ORPHAN_START = set("的了是在和与或但却吗呢啊呀也就都而及把被给从到对")
V17_ORPHAN_END = set("的了是在和与或但却把被给从到对")
V17_SEMANTIC_BOUNDARIES = (
    "但是", "不过", "然而", "所以", "如果", "比如", "然后", "因为", "其实",
    "真正", "而是", "先看", "再看", "最后", "另外", "同时", "而且", "接下来",
    "第一", "第二", "第三", "第四", "关键是", "重点是",
)


def _probe(path: Path) -> dict[str, Any]:
    cmd = [
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration:stream=codec_type,width,height,r_frame_rate,duration",
        "-of", "json", str(path),
    ]
    data = json.loads(subprocess.check_output(cmd, text=True))
    streams = data.get("streams") or []
    video = next((x for x in streams if x.get("codec_type") == "video"), {})
    audio = next((x for x in streams if x.get("codec_type") == "audio"), {})
    rate = str(video.get("r_frame_rate") or "30/1")
    try:
        n, d = rate.split("/", 1)
        fps = float(n) / max(1.0, float(d))
    except Exception:
        fps = 30.0
    format_duration = _safe_float((data.get("format") or {}).get("duration"), 0.0)
    video_duration = _safe_float(video.get("duration"), format_duration)
    audio_duration = _safe_float(audio.get("duration"), 0.0)
    return {
        "duration": format_duration or video_duration or audio_duration,
        "video_duration": video_duration or format_duration,
        "audio_duration": audio_duration,
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "fps": max(20.0, min(60.0, fps or 30.0)),
        "has_audio": bool(audio),
    }


def _caption_forbidden_cuts(text: str) -> set[int]:
    forbidden: set[int] = set()
    for phrase in V17_PROTECTED_CAPTION_PHRASES:
        start = 0
        while True:
            index = text.find(phrase, start)
            if index < 0:
                break
            forbidden.update(range(index + 1, index + len(phrase)))
            start = index + 1
    return forbidden


def _caption_dp_segment(text: str, max_chars: int = 10) -> list[str]:
    text = _clean_caption_text(text)
    if not text:
        return []
    if len(text) <= max_chars + 2:
        return [text]
    forbidden = _caption_forbidden_cuts(text)
    n = len(text)
    inf = 10**9
    cost = [inf] * (n + 1)
    prev = [-1] * (n + 1)
    cost[0] = 0
    boundary_positions = {0, n}
    for marker in V17_SEMANTIC_BOUNDARIES:
        start = 0
        while True:
            idx = text.find(marker, start)
            if idx < 0:
                break
            boundary_positions.add(idx)
            boundary_positions.add(idx + len(marker))
            start = idx + 1
    for i in range(n):
        if cost[i] >= inf:
            continue
        for j in range(i + 2, min(n, i + max_chars + 3) + 1):
            if j < n and j in forbidden:
                continue
            chunk = text[i:j]
            length = len(chunk)
            penalty = abs(length - 7) * 1.4
            if length < 4:
                penalty += 18
            if length > max_chars:
                penalty += (length - max_chars) * 8
            if chunk[0] in V17_ORPHAN_START:
                penalty += 22
            if chunk[-1] in V17_ORPHAN_END:
                penalty += 18
            if j in boundary_positions:
                penalty -= 4
            if i in boundary_positions:
                penalty -= 2
            if cost[i] + penalty < cost[j]:
                cost[j] = cost[i] + penalty
                prev[j] = i
    if prev[n] < 0:
        return [text]
    chunks: list[str] = []
    cursor = n
    while cursor > 0:
        start = prev[cursor]
        if start < 0:
            return [text]
        chunks.append(text[start:cursor])
        cursor = start
    chunks.reverse()
    # Merge accidental orphan/single-character pieces without deleting text.
    merged: list[str] = []
    for chunk in chunks:
        if merged and (len(chunk) == 1 or chunk[0] in V17_ORPHAN_START):
            merged[-1] += chunk
        else:
            merged.append(chunk)
    if len(merged) > 1 and (len(merged[-1]) == 1 or merged[-1][-1] in V17_ORPHAN_END):
        merged[-2] += merged[-1]
        merged.pop()
    return [item for item in merged if item]


def _caption_chunks(text: str, *, max_chars: int = 10) -> list[str]:
    raw = re.sub(r"\\s+", "", str(text or "")).strip()
    if not raw:
        return []
    clauses = [
        item.strip("，,。！？!?；;、：:")
        for item in re.split(r"[，,。！？!?；;、：:]+", raw)
        if item.strip("，,。！？!?；;、：:")
    ]
    output: list[str] = []
    for clause in clauses or [raw]:
        output.extend(_caption_dp_segment(clause, max_chars=max_chars))
    # 字幕切分会主动移除句号、逗号等标点。
    # 完整性检查只比较真正的文字、数字和百分号，不能把标点差异当成内容丢失。
    expected_text = re.sub(
        r"[^\\u4e00-\\u9fffA-Za-z0-9%]+",
        "",
        _clean_caption_text(raw),
    )
    actual_text = re.sub(
        r"[^\\u4e00-\\u9fffA-Za-z0-9%]+",
        "",
        "".join(output),
    )
    if actual_text != expected_text:
        raise ValueError(
            "字幕切分内容不一致："
            f"expected={expected_text[:120]!r}, "
            f"actual={actual_text[:120]!r}"
        )
    return output


def _normalize_locked_shot_plan(payload: dict[str, Any]) -> dict[str, Any]:
    raw_candidates: list[Any] = []
    edit_plan = payload.get("edit_plan")
    if isinstance(edit_plan, dict):
        raw_candidates.append(edit_plan.get("clips"))
    raw_candidates.extend([
        payload.get("shot_plan"), payload.get("shotPlan"), payload.get("shots"),
    ])
    raw: list[Any] = []
    for candidate in raw_candidates:
        if isinstance(candidate, list) and candidate:
            raw = candidate
            break
    clips: list[dict[str, Any]] = []
    for index, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            continue
        nested = item.get("asset") if isinstance(item.get("asset"), dict) else {}
        url = str(
            item.get("asset_url") or item.get("assetUrl") or item.get("r2_url")
            or item.get("url") or nested.get("url") or nested.get("r2_url") or ""
        ).strip()
        if not url:
            continue
        asset_id = str(
            item.get("asset_id") or item.get("assetId") or item.get("id")
            or nested.get("id") or nested.get("asset_id") or hashlib.sha256(url.encode()).hexdigest()[:20]
        ).strip()
        start = _safe_float(item.get("start_time") if item.get("start_time") is not None else item.get("startTime"), 0.0)
        end = _safe_float(item.get("end_time") if item.get("end_time") is not None else item.get("endTime"), 0.0)
        duration = _safe_float(item.get("duration_seconds") or item.get("duration"), 0.0)
        if duration <= 0 and end > start:
            duration = end - start
        duration = max(0.65, duration or 3.2)
        narration = str(item.get("narration") or item.get("copy") or item.get("text") or item.get("script") or "").strip()
        title = str(item.get("title") or item.get("scene") or item.get("description") or f"镜头 {index}").strip()
        clips.append({
            "id": str(item.get("id") or f"locked_shot_{index}"),
            "index": index,
            "title": title,
            "scene": str(item.get("scene") or item.get("description") or title),
            "description": str(item.get("description") or item.get("scene") or title),
            "narration": narration,
            "duration": round(duration, 3),
            "duration_seconds": round(duration, 3),
            "source": "r2",
            "selection_source": "manual",
            "manual_locked": True,
            "asset_id": asset_id,
            "asset_ids": [asset_id],
            "asset_url": url,
            "asset_name": str(item.get("asset_name") or item.get("assetName") or nested.get("name") or title),
            "start_time": max(0.0, start),
            "end_time": max(start + 0.1, end) if end > start else round(max(0.0, start) + duration, 3),
            "auto_start": False,
            "preserve_audio": bool(item.get("preserve_audio") if item.get("preserve_audio") is not None else item.get("preserveAudio", False)),
            "speed": max(0.75, min(1.5, _safe_float(item.get("speed"), 1.0))),
            "transition": str(item.get("transition") or "轻柔淡化"),
            "camera": str(item.get("camera") or "保留原片运镜"),
        })
    return {"clips": clips, "source": "previous_page_shot_plan", "locked": bool(clips)}


def _build_audio_filters(
    plan: dict[str, Any], *, has_audio: bool, sfx_inputs: list[dict[str, Any]],
) -> tuple[str, str | None]:
    if not has_audio:
        return "", None
    render_duration = max(0.1, _safe_float(plan.get("render_duration"), _safe_float(plan.get("duration"), 30.0)))
    voice_chain = (
        f"[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
        f"apad=pad_dur=0.16,atrim=duration={render_duration:.3f},"
        f"afade=t=out:st={max(0.0, render_duration - 0.14):.3f}:d=0.14[voice]"
    )
    if not sfx_inputs:
        return voice_chain + ";[voice]loudnorm=I=-16:LRA=7:TP=-1.8[aout]", "aout"
    parts: list[str] = [voice_chain]
    labels: list[str] = ["voice"]
    for index, item in enumerate(sfx_inputs, start=1):
        event = item["event"]
        sfx = item["sfx"]
        input_index = int(item["input_index"])
        delay = int(max(0.0, _safe_float(event.get("start"), 0.0)) * 1000)
        gain = max(0.018, min(0.16, _safe_float(sfx.get("gain"), 0.08)))
        label = f"sfx{index}"
        parts.append(
            f"[{input_index}:a]aresample=48000,pan=stereo|c0=c0|c1=c0,"
            f"atrim=0:0.62,asetpts=PTS-STARTPTS,highpass=f=90,lowpass=f=11500,"
            f"volume={gain:.4f},afade=t=in:st=0:d=0.012,"
            f"afade=t=out:st=0.40:d=0.16,adelay={delay}|{delay}[{label}]"
        )
        labels.append(label)
    parts.append(
        "".join(f"[{label}]" for label in labels)
        + f"amix=inputs={len(labels)}:duration=first:dropout_transition=0:normalize=0,"
        "alimiter=limit=0.90,loudnorm=I=-16:LRA=7:TP=-2.0[aout]"
    )
    return ";".join(parts), "aout"


def render_dynamic_video(
    input_path: Path, output_path: Path, ass_path: Path, plan: dict[str, Any],
) -> dict[str, Any]:
    info = _probe(input_path)
    video_duration = _safe_float(info.get("video_duration"), info.get("duration") or 0.0)
    audio_duration = _safe_float(info.get("audio_duration"), 0.0)
    if info.get("has_audio") and audio_duration > 0:
        render_duration = min(video_duration or audio_duration + 0.12, audio_duration + 0.12)
    else:
        render_duration = video_duration or _safe_float(info.get("duration"), 0.0)
    render_duration = max(0.1, render_duration)
    plan["render_duration"] = round(render_duration, 3)
    plan["duration"] = min(_safe_float(plan.get("duration"), render_duration), render_duration)

    sticker_inputs = _collect_sticker_inputs(plan)
    sfx_inputs = [
        item for item in _collect_sfx_inputs(plan)
        if _safe_float(item.get("event", {}).get("start"), 0.0) < render_duration - 0.18
    ]
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(input_path)]
    next_input_index = 1
    for item in sticker_inputs:
        item["input_index"] = next_input_index
        sticker = item["sticker"]
        span = max(0.6, _safe_float(sticker.get("end"), 1.0) - _safe_float(sticker.get("start"), 0.0))
        cmd += ["-loop", "1", "-framerate", f"{info['fps']:.3f}", "-t", f"{span:.3f}", "-i", str(item["path"])]
        next_input_index += 1
    for item in sfx_inputs:
        item["input_index"] = next_input_index
        cmd += ["-i", str(item["path"])]
        next_input_index += 1
    video_filters = _build_video_filters(input_path.parent, plan, ass_path, sticker_inputs)
    audio_filters, audio_label = _build_audio_filters(plan, has_audio=bool(info["has_audio"]), sfx_inputs=sfx_inputs)
    cmd += ["-filter_complex", video_filters + (";" + audio_filters if audio_filters else ""), "-map", "[vout]"]
    if audio_label == "aout":
        cmd += ["-map", "[aout]"]
    cmd += [
        "-t", f"{render_duration:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-r", f"{info['fps']:.3f}",
    ]
    if info["has_audio"]:
        cmd += ["-c:a", "aac", "-b:a", "192k"]
    cmd += ["-movflags", "+faststart", str(output_path)]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(cmd, check=True, timeout=7200)
    rendered = _probe(output_path)
    output_video = _safe_float(rendered.get("video_duration"), rendered.get("duration") or 0.0)
    output_audio = _safe_float(rendered.get("audio_duration"), 0.0)
    delta = abs(output_video - output_audio) if output_audio > 0 else 0.0
    if abs(output_video - render_duration) > 0.35:
        raise RuntimeError(f"动态精剪输出时长异常：expected={render_duration:.3f}, actual={output_video:.3f}")
    if output_audio > 0 and delta > 0.25:
        raise RuntimeError(f"动态精剪音画尾部不一致：video={output_video:.3f}, audio={output_audio:.3f}")
    return {
        "input": info, "output": rendered, "ffmpeg_command": cmd,
        "sticker_count": len(sticker_inputs), "sfx_count": len(sfx_inputs),
        "sticker_assets": [item["path"].name for item in sticker_inputs],
        "sfx_assets": [item["path"].name for item in sfx_inputs],
        "audio_tail_guard": {
            "enabled": True, "input_video_duration": round(video_duration, 3),
            "input_audio_duration": round(audio_duration, 3), "render_duration": round(render_duration, 3),
            "output_video_duration": round(output_video, 3), "output_audio_duration": round(output_audio, 3),
            "output_delta_seconds": round(delta, 3),
        },
    }


# =============================================================================
# V10.40.8.19 AI BEAT DIRECTOR + PROFESSIONAL CC0 SFX OVERRIDES
# =============================================================================
V19_MARKER = "V10_40_8_19_AI_BEAT_DIRECTOR_PRO_SFX"
V19_PRO_SFX_DIR = Path(os.getenv("AI_VIDEO_PRO_SFX_DIR", "/data/ai-video/sfx-professional-v19"))

# These files are downloaded directly by the deployment script from
# VideoEditingSFX's CC0 library. They are not repackaged in this ZIP.
SFX_VARIANT_BANKS = {
    "hook": [
        ("cinematic-heavy-hit.mp3", 0.44),
        ("simple-whoosh-1.mp3", 0.30),
        ("pop-sound.mp3", 0.25),
    ],
    "question": [
        ("pop-sound.mp3", 0.27),
        ("chime.mp3", 0.23),
        ("button-pressed.mp3", 0.20),
    ],
    "turn": [
        ("swoosh-fast-1.mp3", 0.28),
        ("swipe.mp3", 0.24),
        ("deep-whoosh-1.mp3", 0.26),
    ],
    "data": [
        ("click-button.mp3", 0.20),
        ("pop-sound.mp3", 0.23),
        ("button-pressed.mp3", 0.18),
    ],
    "risk": [
        ("cinematic-heavy-hit.mp3", 0.32),
        ("swoosh-fast-with-thud.mp3", 0.29),
        ("deep-whoosh-1.mp3", 0.25),
    ],
    "comparison": [
        ("swoosh-fast-with-thud.mp3", 0.27),
        ("cinematic-reverse-1.mp3", 0.24),
        ("swipe.mp3", 0.21),
    ],
    "list": [
        ("pop-sound.mp3", 0.19),
        ("button-pressed.mp3", 0.17),
        ("click-button.mp3", 0.16),
    ],
    "evidence": [
        ("analog-shutter.mp3", 0.20),
        ("camera-1.mp3", 0.18),
        ("click-button.mp3", 0.15),
    ],
    "cta": [
        ("apple-pay-success.mp3", 0.22),
        ("success.mp3", 0.20),
        ("chime.mp3", 0.20),
    ],
}


SFX_LEVELS = {
    "off": {"label": "关闭", "volume": 0.0, "max_per_30s": 0, "min_gap": 99.0},
    "light": {"label": "专业轻量", "volume": 0.075, "max_per_30s": 3, "min_gap": 4.6},
    "balanced": {"label": "专业标准", "volume": 0.105, "max_per_30s": 4, "min_gap": 3.8},
    "strong": {"label": "专业强化", "volume": 0.135, "max_per_30s": 5, "min_gap": 3.2},
}

SFX_PACK_FILES: dict[str, set[str]] = {
    "pro_clean_ui": {
        "pop-sound.mp3", "click-button.mp3", "button-pressed.mp3", "chime.mp3",
        "apple-pay-success.mp3", "success.mp3", "swipe.mp3", "analog-shutter.mp3", "camera-1.mp3",
    },
    "pro_cinematic_light": {
        "cinematic-heavy-hit.mp3", "simple-whoosh-1.mp3", "deep-whoosh-1.mp3",
        "swoosh-fast-1.mp3", "swoosh-fast-with-thud.mp3", "cinematic-reverse-1.mp3",
        "chime.mp3", "success.mp3", "analog-shutter.mp3",
    },
}


V19_SFX_META = {
    "simple-whoosh-1.mp3": (0.0, 1.05),
    "deep-whoosh-1.mp3": (0.0, 1.55),
    "swoosh-fast-1.mp3": (0.0, 1.00),
    "swoosh-fast-with-thud.mp3": (0.0, 1.20),
    "cinematic-heavy-hit.mp3": (0.0, 1.55),
    "cinematic-reverse-1.mp3": (0.0, 1.45),
    "pop-sound.mp3": (0.0, 0.90),
    "click-button.mp3": (0.0, 0.85),
    "button-pressed.mp3": (0.0, 0.85),
    "chime.mp3": (0.0, 1.35),
    "apple-pay-success.mp3": (0.0, 1.30),
    "success.mp3": (0.0, 1.20),
    "swipe.mp3": (0.0, 1.00),
    "analog-shutter.mp3": (0.0, 1.05),
    "camera-1.mp3": (0.0, 1.05),
}



def _sfx_root() -> Path:
    return V19_PRO_SFX_DIR


def _build_audio_filters(
    plan: dict[str, Any], *, has_audio: bool, sfx_inputs: list[dict[str, Any]],
) -> tuple[str, str | None]:
    if not has_audio:
        return "", None
    render_duration = max(0.1, _safe_float(plan.get("render_duration"), _safe_float(plan.get("duration"), 30.0)))
    voice_chain = (
        f"[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
        f"apad=pad_dur=0.16,atrim=duration={render_duration:.3f},"
        f"afade=t=out:st={max(0.0, render_duration - 0.14):.3f}:d=0.14[voice]"
    )
    if not sfx_inputs:
        return voice_chain + ";[voice]loudnorm=I=-16:LRA=7:TP=-1.8[aout]", "aout"
    parts: list[str] = [voice_chain]
    labels: list[str] = ["voice"]
    for index, item in enumerate(sfx_inputs, start=1):
        event = item["event"]
        sfx = item["sfx"]
        input_index = int(item["input_index"])
        delay = int(max(0.0, _safe_float(event.get("start"), 0.0)) * 1000)
        asset_name = Path(str(item.get("path") or "")).name
        trim_start, trim_duration = V19_SFX_META.get(asset_name, (0.0, 1.25))
        gain = max(0.010, min(0.105, _safe_float(sfx.get("gain"), 0.045)))
        fade_out_start = max(0.20, trim_duration - min(0.24, trim_duration * 0.22))
        label = f"sfx{index}"
        parts.append(
            f"[{input_index}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"atrim=start={trim_start:.3f}:duration={trim_duration:.3f},asetpts=PTS-STARTPTS,"
            f"highpass=f=45,lowpass=f=18000,acompressor=threshold=0.12:ratio=2.4:attack=5:release=90,"
            f"volume={gain:.4f},afade=t=in:st=0:d=0.018,"
            f"afade=t=out:st={fade_out_start:.3f}:d={max(0.08, trim_duration-fade_out_start):.3f},"
            f"adelay={delay}|{delay}[{label}]"
        )
        labels.append(label)
    parts.append(
        "".join(f"[{label}]" for label in labels)
        + f"amix=inputs={len(labels)}:duration=first:dropout_transition=0:normalize=0,"
        "alimiter=limit=0.88,loudnorm=I=-16:LRA=7:TP=-2.0[aout]"
    )
    return ";".join(parts), "aout"
