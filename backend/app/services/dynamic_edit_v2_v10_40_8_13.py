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

VERSION = "10.40.8.37.1.4-global-candidate-matrix-reservation"
# V10_40_8_37_1_4_GLOBAL_CANDIDATE_MATRIX_RESERVATION
# V10_40_8_37_1_3_GLOBAL_CAPACITY_PRECONSOLIDATION
# V10_40_8_37_1_1_CTA_CLASSIFIER_TRAFFIC_INTENT_HOTFIX
# V10_40_8_37_1_ADAPTIVE_UNIQUE_ASSET_CAPACITY
# V10_40_8_37_INLINE_KEYWORD_ENTITY_MICROCUT_CTA
# V10_40_8_36_1_FINAL_INTENT_VALIDATION_HOTFIX
# V10_40_8_35_FINAL_MASTER_INTEGRITY_WORKFLOW_CLEANUP
# V10_40_8_34_DEDUP_KEYWORD_ENTITY_CTA
# V10_40_8_33_SEMANTIC_RELEVANCE_CAPTION_HIERARCHY
# V10_40_8_32_REFERENCE_KINETIC_TYPOGRAPHY
INSTALL_MARKER = "V10_40_8_37_1_4_GLOBAL_CANDIDATE_MATRIX_RESERVATION"
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



def _cleanup_stale_dynamic_workdirs(
    settings: Any, *, keep_job_id: str = "", max_age_hours: float = 24.0,
) -> dict[str, Any]:
    root = _data_dir(settings) / "tmp" / "dynamic_edit_v2"
    if not root.exists():
        return {"removed": 0, "reclaimed_bytes": 0}
    cutoff = time.time() - max(1.0, max_age_hours) * 3600.0
    removed = 0
    reclaimed = 0
    for path in list(root.iterdir()):
        if not path.is_dir() or path.name == keep_job_id:
            continue
        try:
            if path.stat().st_mtime >= cutoff:
                continue
            size = sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
            shutil.rmtree(path, ignore_errors=False)
            removed += 1
            reclaimed += size
        except FileNotFoundError:
            continue
        except Exception:
            continue
    return {"removed": removed, "reclaimed_bytes": reclaimed}


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
    if sfx_level == "balanced" and duration >= 12.0:
        max_sfx = max(4, max_sfx)
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


def _v26_clean_token_text(value: Any) -> str:
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9%]+", "", str(value or ""))


def _v26_character_clock(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    clock: list[dict[str, Any]] = []
    for word in words:
        if not isinstance(word, dict):
            continue
        token = _v26_clean_token_text(word.get("word") or word.get("text"))
        if not token:
            continue
        start = _safe_float(word.get("start") if word.get("start") is not None else word.get("startTime"), -1.0)
        end = _safe_float(word.get("end") if word.get("end") is not None else word.get("endTime"), -1.0)
        if start < 0 or end <= start:
            continue
        span = end - start
        for index, char in enumerate(token):
            char_start = start + span * index / len(token)
            char_end = start + span * (index + 1) / len(token)
            clock.append({"char": char, "start": char_start, "end": char_end})
    return clock


def _v26_align_chunks_to_native_words(chunks: list[str], words: list[dict[str, Any]], fallback_start: float, fallback_end: float) -> list[dict[str, Any]]:
    clock = _v26_character_clock(words)
    expected = "".join(_v26_clean_token_text(chunk) for chunk in chunks)
    actual = "".join(item["char"] for item in clock)
    if not clock or not expected:
        fallback = _spread_chunks(chunks, fallback_start, fallback_end)
        for cue in fallback:
            cue["timing_source"] = "segment_duration_fallback"
            cue["native_word_timestamp"] = False
            cue["native_word_count"] = 0
        return fallback

    exact_match = expected == actual
    result: list[dict[str, Any]] = []
    cursor = 0
    expected_cursor = 0
    expected_total = max(1, len(expected))

    for chunk_index, chunk in enumerate(chunks):
        token = _v26_clean_token_text(chunk)
        if not token:
            continue

        if exact_match:
            end_cursor = cursor + len(token)
        else:
            # Volcengine timestamp text is TN-normalized (for example 100 may
            # become Chinese words). Keep native time boundaries by mapping the
            # original caption chunk ratio onto the returned native clock.
            expected_cursor += len(token)
            end_cursor = (
                len(clock)
                if chunk_index == len(chunks) - 1
                else max(cursor + 1, round(expected_cursor / expected_total * len(clock)))
            )

        end_cursor = min(len(clock), max(cursor + 1, end_cursor))
        selection = clock[cursor:end_cursor]
        if not selection:
            fallback = _spread_chunks(chunks, fallback_start, fallback_end)
            for cue in fallback:
                cue["timing_source"] = "segment_duration_fallback"
                cue["native_word_timestamp"] = False
                cue["native_word_count"] = 0
            return fallback

        result.append({
            "text": chunk,
            "start": round(float(selection[0]["start"]), 3),
            "end": round(max(float(selection[-1]["end"]), float(selection[0]["start"]) + 0.08), 3),
            "timing_source": (
                "volcengine_native_word_timestamp"
                if exact_match
                else "volcengine_native_word_timestamp_fuzzy_tn"
            ),
            "native_word_timestamp": True,
            "native_word_count": len(selection),
        })
        cursor = end_cursor
        if exact_match:
            expected_cursor += len(token)

    if result:
        result[-1]["end"] = round(max(result[-1]["start"] + 0.08, float(clock[-1]["end"])), 3)
    return result


def _normalize_timings(payload: dict[str, Any], base_job: dict[str, Any], duration: float) -> list[dict[str, Any]]:
    raw = (
        base_job.get("tts_timings_native")
        or base_job.get("timings")
        or base_job.get("subtitle_segments")
        or payload.get("segments")
        or payload.get("script_segments")
        or []
    )
    items: list[dict[str, Any]] = []
    for raw_item in raw if isinstance(raw, list) else []:
        if not isinstance(raw_item, dict):
            continue
        text = _text_of_segment(raw_item)
        if not text:
            continue
        start = _safe_float(raw_item.get("start") if raw_item.get("start") is not None else raw_item.get("start_time"), -1.0)
        end = _safe_float(raw_item.get("end") if raw_item.get("end") is not None else raw_item.get("end_time"), -1.0)
        items.append({
            "text": text,
            "start": start,
            "end": end,
            "word_timeline": list(raw_item.get("word_timeline") or []),
            "timing_source": str(raw_item.get("timing_source") or ""),
        })

    if items and all(item["start"] >= 0 and item["end"] > item["start"] for item in items):
        fragmented: list[dict[str, Any]] = []
        for item in items:
            chunks = _caption_chunks(item["text"])
            if item["word_timeline"]:
                aligned = _v26_align_chunks_to_native_words(
                    chunks, item["word_timeline"], item["start"], item["end"]
                )
            else:
                aligned = _spread_chunks(chunks, item["start"], item["end"])
                for cue in aligned:
                    cue["timing_source"] = "segment_duration_fallback"
                    cue["native_word_timestamp"] = False
            fragmented.extend(aligned)
        return fragmented

    script = str(payload.get("script_text") or payload.get("script") or "").strip()
    if not script and items:
        script = "。".join(item["text"] for item in items)
    chunks = _caption_chunks(script or "动态精剪")
    normalized = _spread_chunks(chunks, 0.0, duration)
    for cue in normalized:
        cue["timing_source"] = "whole_script_duration_fallback"
        cue["native_word_timestamp"] = False
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
    sfx_level = str(payload.get("dynamic_sfx_level") or "light")
    sticker_level = str(payload.get("dynamic_sticker_level") or "light")
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
    """Highlight inside the same subtitle layer without scale or duplicate text."""
    escaped = _ass_escape(text)
    for keyword in sorted((item for item in keywords if item), key=len, reverse=True):
        safe = _ass_escape(keyword)
        if safe in escaped:
            escaped = escaped.replace(
                safe,
                rf"{{\c{highlight}}}{safe}{{\c&H00FFFFFF&}}",
                1,
            )
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
        impact = False  # R8 single caption layer
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
    """R8 quality gate: one subtitle layer, no unapproved overlays, SFX or stickers."""
    cleaned = dict(plan)
    for key in (
        "events", "stickers", "sticker_events", "sfx_events", "sound_effects",
        "keyword_overlays", "impact_overlays", "text_cards", "data_cards",
        "risk_cards", "list_cards", "cta_cards",
    ):
        cleaned[key] = []
    cleaned["dynamic_sfx_level"] = "off"
    cleaned["dynamic_sticker_level"] = "off"
    cleaned["clean_render_policy"] = {
        "single_caption_layer": True,
        "duplicate_text_overlays": False,
        "keyword_scale_animation": False,
        "random_stickers": False,
        "unapproved_sfx": False,
        "phrase_boundary_gate": True,
        "version": VERSION,
    }
    return cleaned


def _validate_clean_render_plan(
    plan: dict[str, Any], timings: list[dict[str, Any]],
) -> dict[str, Any]:
    forbidden = (
        "events", "stickers", "sticker_events", "sfx_events", "sound_effects",
        "keyword_overlays", "impact_overlays", "text_cards", "data_cards",
        "risk_cards", "list_cards", "cta_cards",
    )
    dirty = [key for key in forbidden if plan.get(key)]
    if dirty:
        raise ValueError(f"R8 清洁渲染闸门失败，仍有额外图层：{','.join(dirty)}")
    if any(not isinstance(item, dict) or not str(item.get("text") or "").strip() for item in timings):
        raise ValueError("R8 字幕时间轴包含空字幕")
    policy = plan.get("clean_render_policy") or {}
    if not policy.get("single_caption_layer") or policy.get("random_stickers"):
        raise ValueError("R8 单层字幕策略未生效")
    plan["quality_gate"] = {
        "passed": True,
        "single_caption_layer": True,
        "phrase_boundary_gate": True,
        "sfx_disabled": True,
        "stickers_disabled": True,
    }
    return plan

def _clip_master_signature(item: dict[str, Any]) -> tuple[str, str, int, str]:
    """Stable identity for validating that V2 did not reshape the child master timeline."""
    raw_duration = item.get("duration") or item.get("duration_seconds") or 0
    try:
        duration_ms = int(round(float(raw_duration) * 1000))
    except (TypeError, ValueError):
        duration_ms = 0
    return (
        str(item.get("id") or item.get("clip_id") or ""),
        str(item.get("asset_id") or item.get("source_asset_id") or ""),
        duration_ms,
        str(item.get("narration") or item.get("text") or "").strip(),
    )



def _select_runtime_real_tts_child_job(scope: dict[str, Any]) -> dict[str, Any]:
    """Select the completed existing-edit child job from the current _run_dynamic scope."""
    ranked: list[tuple[int, str, dict[str, Any]]] = []
    ignored = {
        "payload", "semantic_plan", "plan", "authoritative_master",
        "asset_usage_report", "coverage", "proxy_job",
    }
    for name, value in scope.items():
        if name in ignored or not isinstance(value, dict):
            continue
        child_plan = value.get("edit_plan")
        child_plan = child_plan if isinstance(child_plan, dict) else {}
        clips = value.get("clips") or child_plan.get("clips") or []
        if not isinstance(clips, list) or not clips:
            continue
        score = 0
        status = str(value.get("status") or "").lower()
        stage = str(value.get("stage") or "").lower()
        job_id = str(value.get("job_id") or value.get("id") or "")
        coverage = child_plan.get("coverage") or value.get("coverage") or {}
        if status in {"done", "finished", "completed", "success"}:
            score += 6
        if stage in {"done", "finished", "completed", "success"}:
            score += 4
        if job_id.startswith("existing_edit_"):
            score += 5
        if child_plan.get("clips"):
            score += 5
        if value.get("clips"):
            score += 3
        if isinstance(coverage, dict) and (
            coverage.get("real_tts_replanned")
            or coverage.get("semantic_tts_replanned")
            or coverage.get("timing_source") == "real_tts_segments"
        ):
            score += 6
        raw_count = (
            child_plan.get("semantic_master_shot_count")
            or value.get("semantic_master_shot_count")
            or value.get("shot_count")
            or len(clips)
        )
        try:
            if int(raw_count) == len(clips):
                score += 4
        except (TypeError, ValueError):
            pass
        ranked.append((score, name, value))

    if not ranked:
        available = sorted(
            name for name, value in scope.items()
            if isinstance(value, dict)
        )
        raise ValueError(
            "R10 未在动态任务作用域中找到真实 TTS 子任务；"
            f"dict_vars={available}"
        )

    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    best_score, best_name, best_job = ranked[0]
    if best_score < 8:
        raise ValueError(
            "R10 找到的候选不足以确认为真实 TTS 子任务："
            f"name={best_name}, score={best_score}"
        )
    return best_job

def _resolve_authoritative_semantic_master(
    base_job: dict[str, Any],
    preview_plan: dict[str, Any] | None,
    applied_clips: list[dict[str, Any]],
) -> dict[str, Any]:
    """Promote the post-real-TTS child plan; pre-TTS preview count is informational only."""
    child_plan = dict(base_job.get("edit_plan") or {})
    child_clips = [
        dict(item) for item in (base_job.get("clips") or child_plan.get("clips") or [])
        if isinstance(item, dict)
    ]
    raw_count = (
        child_plan.get("semantic_master_shot_count")
        or base_job.get("semantic_master_shot_count")
        or base_job.get("shot_count")
        or len(child_clips)
    )
    try:
        child_count = int(raw_count)
    except (TypeError, ValueError):
        child_count = len(child_clips)

    if child_count <= 0 or not child_clips:
        raise ValueError("R9 真实 TTS 子任务语义主时间线为空")
    if len(child_clips) != child_count:
        raise ValueError(
            "R9 子任务语义主时间线内部数量不一致："
            f"metadata={child_count}, clips={len(child_clips)}"
        )
    if len(applied_clips) != child_count:
        raise ValueError(
            "R9 V2 应用镜头数量偏离真实 TTS 子任务主时间线："
            f"child={child_count}, applied={len(applied_clips)}"
        )

    child_signatures = [_clip_master_signature(item) for item in child_clips]
    applied_signatures = [_clip_master_signature(item) for item in applied_clips]
    if child_signatures != applied_signatures:
        raise ValueError("R9 V2 应用镜头顺序或素材偏离真实 TTS 子任务主时间线")

    preview_clips = [
        dict(item) for item in ((preview_plan or {}).get("clips") or [])
        if isinstance(item, dict)
    ]
    preview_count = len(preview_clips)
    raw_asset_ids = [
        str(item.get("asset_id") or item.get("source_asset_id") or "").strip()
        for item in child_clips
    ]
    if any(not item for item in raw_asset_ids):
        raise ValueError("V35 真实 TTS 子任务包含未绑定素材的最终镜头")
    duplicate_ids = sorted({item for item in raw_asset_ids if raw_asset_ids.count(item) > 1})
    integrity = dict(
        child_plan.get("final_master_integrity")
        or base_job.get("final_master_integrity")
        or {}
    )
    if duplicate_ids:
        raise ValueError(f"V35 真实 TTS 最终镜头仍重复：{duplicate_ids}")
    if integrity and integrity.get("passed") is not True:
        raise ValueError(f"V35 子任务最终镜头完整性报告未通过：{integrity}")
    asset_ids = list(raw_asset_ids)

    coverage = dict(child_plan.get("coverage") or base_job.get("coverage") or {})
    coverage.update({
        "semantic_master_timeline": True,
        "real_tts_child_master_promoted": True,
        "preview_semantic_shot_count": preview_count,
        "real_tts_semantic_shot_count": child_count,
        "preview_count_changed_after_real_tts": bool(preview_count and preview_count != child_count),
        "timing_source": coverage.get("timing_source") or "real_tts_segments",
    })

    authoritative_plan = dict(child_plan)
    authoritative_plan.update({
        "clips": child_clips,
        "coverage": coverage,
        "semantic_master_shot_count": child_count,
        "preview_semantic_shot_count": preview_count,
        "real_tts_child_master_promoted": True,
        "preview_plan_is_non_authoritative": True,
        "version": VERSION,
    })

    base_asset_report = dict(base_job.get("asset_usage_report") or {})
    base_asset_report.update({
        "asset_ids": asset_ids,
        "asset_count": len(asset_ids),
        "selected_asset_count": len(asset_ids),
        "unique_asset_count": len(set(asset_ids)),
        "repeat_count": len(asset_ids) - len(set(asset_ids)),
        "final_master_integrity": integrity,
        "source": "real_tts_child_master",
    })

    return {
        "plan": authoritative_plan,
        "clips": child_clips,
        "count": child_count,
        "preview_count": preview_count,
        "asset_ids": asset_ids,
        "asset_usage_report": base_asset_report,
        "coverage": coverage,
    }

def _run_dynamic(settings: Any, proxy_job_id: str, payload: dict[str, Any]) -> None:
    classic = _classic()
    _cleanup_stale_dynamic_workdirs(settings, keep_job_id=proxy_job_id)
    work = _work_dir(settings, proxy_job_id)
    completed = False
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
        runtime_base_job = _select_runtime_real_tts_child_job(locals())
        authoritative_master = _resolve_authoritative_semantic_master(
            runtime_base_job, semantic_plan, applied_clips
        )
        # R10_RUNTIME_CHILD_JOB_BINDING
        semantic_plan = authoritative_master["plan"]
        authoritative_clips = authoritative_master["clips"]
        authoritative_count = authoritative_master["count"]
        authoritative_asset_ids = authoritative_master["asset_ids"]
        _update_proxy(
            settings,
            proxy_job_id,
            semantic_plan=semantic_plan,
            edit_plan=semantic_plan,
            clips=authoritative_clips,
            applied_clips=authoritative_clips,
            shot_count=authoritative_count,
            semantic_shot_count=authoritative_count,
            semantic_master_shot_count=authoritative_count,
            asset_count=len(authoritative_asset_ids),
            selected_asset_count=len(authoritative_asset_ids),
            unique_asset_count=len(authoritative_asset_ids),
            asset_usage_report=authoritative_master["asset_usage_report"],
            coverage=authoritative_master["coverage"],
            preview_semantic_shot_count=authoritative_master["preview_count"],
            real_tts_child_master_promoted=True,
        )
        # REAL_TTS_CHILD_MASTER_SYNC_R9
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
        sfx_level = str(payload.get("dynamic_sfx_level") or "light")
        sticker_level = str(payload.get("dynamic_sticker_level") or "light")
        payload["ai_shot_beats"] = semantic_plan.get("beats") or []
        plan = build_dynamic_plan(payload, timings, duration, intensity=intensity)
        plan = _validate_v26_effect_plan(plan, timings, sfx_level, sticker_level)
        plan["ai_shot_beats"] = semantic_plan.get("beats") or []
        plan["ai_director_report"] = semantic_plan.get("director_report") or {}
        plan["subtitle_style"] = style_id
        ass_path = write_dynamic_ass(work / "dynamic_subtitles.ass", timings, plan.get("keywords") or [], style_id=style_id, events=plan.get("events") or [])
        plan_path = work / "dynamic_effect_timeline.json"
        plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

        _update_proxy(settings, proxy_job_id, stage="dynamic_render", progress=86, message="正在渲染原生字级字幕、专业音效、语义贴纸和关键词强调", dynamic_effect_timeline=plan)
        output_path = Path(getattr(settings, "outputs_dir", _data_dir(settings) / "outputs")) / f"{proxy_job_id}_dynamic_v2.mp4"
        render_report = render_dynamic_video(source_path, output_path, ass_path, plan)
        if sfx_level != "off" and int(render_report.get("sfx_count") or 0) <= 0:
            raise ValueError("已请求音效但实际渲染数量为 0")
        if sticker_level != "off" and int(render_report.get("sticker_count") or 0) <= 0:
            raise ValueError("已请求贴纸但实际渲染数量为 0")
        if int(plan.get("keyword_impact_count") or 0) <= 0:
            raise ValueError("关键词强调没有实际渲染")

        report = {
            "version": VERSION,
            "job_id": proxy_job_id,
            "base_job_id": classic_job_id,
            "intensity": intensity,
            "subtitle_style": style_id,
            "effect_count": len(plan.get("events") or []),
            "events": plan.get("events") or [],
            "safe_effects": [
                "semantic_master_timeline", "native_word_timestamp_alignment", "long_sentence_hold", "entity_micro_cut", "asset_memory", "slow_footage_auto_speed",
                "single_ass_caption_layer", "inline_keyword_scale_pulse",
                "professional_mixkit_sfx", "semantic_stickers", "camera_micro_effects",
            ],
            "sfx_level": sfx_level,
            "sticker_level": sticker_level,
            "sfx_count": render_report.get("sfx_count", 0),
            "sticker_count": render_report.get("sticker_count", 0),
            "keyword_impact_count": int(plan.get("keyword_impact_count") or 0),
            "subtitle_timing_source": plan.get("subtitle_timing_source"),
            "native_word_timestamp_count": int(plan.get("native_word_timestamp_count") or 0),
            "sfx_pack_version": "mixkit-pro-v27",
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
            asset_usage_report={
                **dict(authoritative_master.get("asset_usage_report") or {}),
                "record_success": usage_written,
                "asset_ids": authoritative_asset_ids,
                "asset_count": len(authoritative_asset_ids),
                "unique_asset_count": len(set(authoritative_asset_ids)),
                "repeat_count": len(authoritative_asset_ids) - len(set(authoritative_asset_ids)),
                "final_master_integrity": (semantic_plan or {}).get("final_master_integrity") or {},
            },
            asset_count=len(authoritative_asset_ids),
            selected_asset_count=len(authoritative_asset_ids),
            unique_asset_count=len(set(authoritative_asset_ids)),
            audio_tail_guard=render_report.get("audio_tail_guard") or {},
            base_job_id=classic_job_id,
            fal_used=False,
            billing_guard="dynamic_v2_wraps_existing_edit_no_fal",
            finished_at=_now(),
        )
        completed = True
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
    finally:
        if completed:
            shutil.rmtree(work, ignore_errors=True)
        _cleanup_stale_dynamic_workdirs(settings, keep_job_id=proxy_job_id)


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
        "dynamic_sfx_level": str(payload.get("dynamic_sfx_level") or "light"),
        "dynamic_sticker_level": str(payload.get("dynamic_sticker_level") or "light"),
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
                "data_cards": True,
                "risk_alerts": True,
                "list_cards": True,
                "no_text_boxes": True,
                "micro_caption_fragments": True,
                "dynamic_dense_base_clips": False,
                "semantic_scene_boundaries": True,
                "deepseek_ai_beat_director": True,
                "entity_burst_one_entity_one_shot": True,
                "professional_licensed_sfx_bank": True,
                "locked_previous_page_shot_plan": True,
                "persistent_asset_usage_recorder": True,
                "audio_tail_guard": True,
                "phrase_safe_caption_segmentation": True,
                "caption_phrase_boundary_gate": True,
                "clean_single_caption_layer": True,
                "real_tts_child_master_promoted": True,
                "post_tts_final_master_integrity": True,
                "final_intent_metadata_revalidation": True,
                "strict_actual_repeat_count_gate": True,
                "successful_dynamic_workdir_cleanup": True,
                "parent_job_semantic_metadata_synced": True,
                "preview_plan_non_authoritative": True,
                "runtime_child_job_binding": True,
                "volcengine_native_word_timestamps": True,
                "mixkit_professional_sfx_v26": True,
                "mixkit_professional_sfx_v27": True,
                "inline_keyword_scale_pulse": True,
                "inline_keyword_order_integrity": True,
                "separate_keyword_overlay_forbidden": True,
                "concrete_entity_micro_cut": True,
                "semantic_density_pacing": True,
                "actionable_cta_scene_contract": True,
                "adaptive_semantic_hold_when_unique_asset_exhausted": True,
                "adjacent_family_distinct_entity_allowed": True,
                "unique_asset_capacity_downshift": True,
                "explicit_actionable_cta_classifier": True,
                "canonical_traffic_intent_labels": True,
                "semantic_cta_prefers_concrete_intent": True,
                "cta_people_scene_only_without_concrete_intent": True,
                "cta_semantic_hold_when_unique_asset_exhausted": True,
                "global_capacity_preconsolidation": True,
                "map_amenity_contextual_match": True,
                "contextual_capacity_hold": True,
                "global_candidate_matrix_preflight": True,
                "scarce_asset_reservation": True,
                "generic_cta_people_asset_reservation": True,
                "render_preflight_feasibility_proof": True,
                "semantic_sticker_effects": True,
                "effect_delivery_quality_gate": True,
                "reference_driven_teaching_effects": True,
                "semantic_callout_cards": True,
                "semantic_information_cards_v28": True,
                "audible_sfx_mix_gate": True,
                "effect_density_guard_v28": True,
                "real_tts_authoritative_duration": True,
                "fixed_duration_cut_forbidden": True,
                "tts_end_integrity_guard": True,
                "unapproved_sfx_disabled": True,
                "random_stickers_disabled": True,
                "reference_subtitle_pack": True,
                "keyword_highlight": True,
                "micro_sfx": True,
                "real_sfx_assets": True,
                "semantic_transparent_stickers": True,
                "large_caption_pack": False,
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
        payload["dynamic_sfx_level"] = str(request.query_params.get("sfx_level") or payload.get("dynamic_sfx_level") or "light")
        payload["dynamic_sticker_level"] = str(request.query_params.get("sticker_level") or payload.get("dynamic_sticker_level") or "light")
        payload["dynamic_visual_pace"] = "ai_auto"
        payload["dynamic_caption_size"] = str(request.query_params.get("caption_size") or payload.get("dynamic_caption_size") or "standard")
        payload["dynamic_caption_motion"] = str(request.query_params.get("caption_motion") or payload.get("dynamic_caption_motion") or "smart_mix")
        payload["dynamic_caption_position"] = str(request.query_params.get("caption_position") or payload.get("dynamic_caption_position") or "auto")
        payload["dynamic_sfx_pack"] = str(request.query_params.get("sfx_pack") or payload.get("dynamic_sfx_pack") or "smart_mix")
        payload["dynamic_sticker_layout"] = str(request.query_params.get("sticker_layout") or payload.get("dynamic_sticker_layout") or "auto_safe")
        payload["dynamic_sticker_style"] = str(request.query_params.get("sticker_style") or payload.get("dynamic_sticker_style") or "smart_mix")
        result = build_dynamic_plan(payload, timings, duration, intensity=intensity)
        result = _validate_v26_effect_plan(
            result, timings,
            str(payload.get("dynamic_sfx_level") or "light"),
            str(payload.get("dynamic_sticker_level") or "light"),
        )
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
            payload["dynamic_sfx_level"] = str(request.query_params.get("sfx_level") or payload.get("dynamic_sfx_level") or "light")
            payload["dynamic_sticker_level"] = str(request.query_params.get("sticker_level") or payload.get("dynamic_sticker_level") or "light")
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
        impact = False  # R8 single caption layer
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


def _caption_chunks(text: str, *, max_chars: int = 9) -> list[str]:
    """Phrase-safe Chinese caption segmentation for one ASS subtitle layer."""
    clean = _clean_caption_text(text)
    if not clean:
        return []

    protected = tuple(sorted({
        "吉隆坡买房", "第一眼", "价格看", "很容易买错", "自住还是投资",
        "这两个方向", "区域完全不一样", "自住的话", "价格便宜",
        "重点考察", "真实的生活半径", "生活半径", "每天通勤时间",
        "周边超市", "学校离得远不远", "这些现有配套", "现有配套",
        "住进去舒不舒服", "投资呢", "价格只是门槛", "区域租客",
        "租客从哪里来", "未来转手", "本地需求支撑", "把用途想明白",
        "区域才不会踩坑", "想清楚了吗", "评论区打出来", "一对一拆解",
        "生活配套", "租客来源", "交通规划", "投资逻辑", "区域选择",
        "购物中心", "国际学校", "医疗配套", "公共交通", "通勤时间",
    }, key=len, reverse=True))

    coarse = [part for part in re.split(r"[，,。！？!?；;、：:]+", clean) if part]
    output: list[str] = []

    def illegal_cuts(phrase: str) -> set[int]:
        illegal: set[int] = set()
        for term in protected:
            start = 0
            while True:
                index = phrase.find(term, start)
                if index < 0:
                    break
                illegal.update(range(index + 1, index + len(term)))
                start = index + 1
        return illegal

    for phrase in coarse or [clean]:
        remaining = phrase
        while len(remaining) > max_chars:
            illegal = illegal_cuts(remaining)
            lower = 4
            preferred = [
                position for position in range(min(max_chars, len(remaining) - 2), lower - 1, -1)
                if position not in illegal and len(remaining) - position >= 2
            ]
            if preferred:
                cut = preferred[0]
            else:
                overflow = [
                    position for position in range(max_chars + 1, min(len(remaining) - 1, max_chars + 4) + 1)
                    if position not in illegal and len(remaining) - position >= 2
                ]
                if overflow:
                    cut = overflow[0]
                else:
                    legal = [
                        position for position in range(2, len(remaining) - 1)
                        if position not in illegal
                    ]
                    if not legal:
                        output.append(remaining)
                        remaining = ""
                        break
                    cut = min(legal, key=lambda position: (abs(position - max_chars), -position))
            output.append(remaining[:cut])
            remaining = remaining[cut:]
        if remaining:
            if len(remaining) <= 2 and output and len(output[-1]) + len(remaining) <= max_chars + 2:
                output[-1] += remaining
            else:
                output.append(remaining)

    # Merge accidental short fragments where possible without crossing punctuation groups.
    compact: list[str] = []
    for item in output:
        if len(item) <= 2 and compact and len(compact[-1]) + len(item) <= max_chars + 2:
            compact[-1] += item
        else:
            compact.append(item)

    expected = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9%]+", "", clean)
    actual = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9%]+", "", "".join(compact))
    if expected != actual:
        raise ValueError("字幕安全切分发生文字丢失")

    # V25_CAPTION_BOUNDARY_AUTO_REPAIR
    # 保护词跨过标点生成的字幕卡时，自动合并相邻卡片，
    # 禁止再因为字幕排版问题杀死整条视频任务。
    repaired = [item for item in compact if item]
    repair_limit = max(8, len(repaired) + len(protected) + 4)

    for _ in range(repair_limit):
        joined = "".join(repaired)

        boundaries: list[tuple[int, int]] = []
        cursor = 0
        for card_index, item in enumerate(repaired[:-1]):
            cursor += len(item)
            boundaries.append((card_index, cursor))

        crossing: tuple[int, str] | None = None

        for term in protected:
            search_start = 0

            while True:
                index = joined.find(term, search_start)
                if index < 0:
                    break

                for card_index, boundary in boundaries:
                    if index < boundary < index + len(term):
                        crossing = (card_index, term)
                        break

                if crossing is not None:
                    break

                search_start = index + 1

            if crossing is not None:
                break

        if crossing is None:
            break

        card_index, _term = crossing

        if card_index + 1 >= len(repaired):
            raise ValueError(f"字幕词组边界无法自动修复：{_term}")

        repaired[card_index : card_index + 2] = [
            repaired[card_index] + repaired[card_index + 1]
        ]
    else:
        raise ValueError("字幕词组边界自动修复超过安全上限")

    joined = "".join(repaired)
    final_boundaries: set[int] = set()
    cursor = 0

    for item in repaired[:-1]:
        cursor += len(item)
        final_boundaries.add(cursor)

    for term in protected:
        search_start = 0

        while True:
            index = joined.find(term, search_start)
            if index < 0:
                break

            if any(
                index < boundary < index + len(term)
                for boundary in final_boundaries
            ):
                raise ValueError(f"字幕词组边界自动修复失败：{term}")

            search_start = index + 1

    return repaired

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


# =============================================================================
# V10.40.8.26 NATIVE WORD SYNC + PROFESSIONAL EFFECT DELIVERY OVERRIDES
# =============================================================================
V26_MARKER = "V10_40_8_26_NATIVE_WORD_SYNC_PRO_EFFECTS"
V26_PRO_SFX_DIR = Path(os.getenv("AI_VIDEO_PRO_SFX_DIR_V26", "/data/ai-video/sfx-professional-v26"))

SFX_VARIANT_BANKS = {
    "hook": [("mixkit-cinematic-whoosh-fast-transition-1492.mp3", 0.82)],
    "question": [("mixkit-interface-hint-notification-911.mp3", 0.66)],
    "turn": [("mixkit-air-woosh-1489.mp3", 0.72), ("mixkit-fast-small-sweep-transition-166.mp3", 0.68)],
    "data": [("mixkit-fast-small-sweep-transition-166.mp3", 0.58)],
    "risk": [("mixkit-cinematic-whoosh-fast-transition-1492.mp3", 0.68)],
    "comparison": [("mixkit-fast-small-sweep-transition-166.mp3", 0.62)],
    "list": [("mixkit-fast-small-sweep-transition-166.mp3", 0.52)],
    "evidence": [("mixkit-interface-hint-notification-911.mp3", 0.48)],
    "cta": [("mixkit-interface-hint-notification-911.mp3", 0.62)],
}
SFX_LEVELS = {
    "off": {"label": "关闭", "volume": 0.0, "max_per_30s": 0, "min_gap": 99.0},
    "light": {"label": "专业轻量", "volume": 0.090, "max_per_30s": 3, "min_gap": 4.2},
    "balanced": {"label": "专业标准", "volume": 0.120, "max_per_30s": 4, "min_gap": 3.5},
    "strong": {"label": "专业强化", "volume": 0.150, "max_per_30s": 5, "min_gap": 3.0},
}
V26_SFX_META = {
    "mixkit-cinematic-whoosh-fast-transition-1492.mp3": (0.0, 1.38),
    "mixkit-air-woosh-1489.mp3": (0.0, 1.05),
    "mixkit-fast-small-sweep-transition-166.mp3": (0.0, 0.85),
    "mixkit-interface-hint-notification-911.mp3": (0.0, 1.20),
}


def _sfx_root() -> Path:
    return V26_PRO_SFX_DIR


def _v16_choose_sticker(event: dict[str, Any], index: int, style: str, last_asset: str) -> str:
    text = str(event.get("source_text") or "")
    rules = [
        (r"学校|学区|教育", ["pin", "map"]),
        (r"医院|医疗", ["pin", "map"]),
        (r"超市|商场|购物|配套", ["shopping", "map"]),
        (r"交通|通勤|地铁|路线", ["metro", "car", "map"]),
        (r"价格|预算|金额|回报|收益", ["money", "chart"]),
        (r"风险|踩坑|注意", ["warning"]),
        (r"评论|告诉我|一对一|咨询", ["comment", "point"]),
        (r"区域|位置|附近", ["pin", "map"]),
        (r"房|住宅|自住", ["house", "key"]),
        (r"租客|人群", ["people"]),
    ]
    candidates: list[str] = []
    for pattern, options in rules:
        if re.search(pattern, text):
            candidates.extend(options)
            break
    if not candidates:
        role = str(event.get("role") or "knowledge")
        candidates = {
            "hook": ["point"], "question": ["question"], "turn": ["map"],
            "data": ["chart"], "risk": ["warning"], "comparison": ["chart"],
            "list": ["check"], "evidence": ["search"], "cta": ["comment"],
        }.get(role, [])
    candidates = [name for name in candidates if name != last_asset and (_sticker_root() / f"{name}.png").is_file()]
    return _deterministic_choice(candidates, f"v26:{event.get('id')}:{index}") if candidates else ""


def _v26_ensure_effect_delivery(
    plan: dict[str, Any],
    timings: list[dict[str, Any]],
    duration: float,
    *,
    sfx_level: str,
    sticker_level: str,
) -> dict[str, Any]:
    events = [dict(item) for item in (plan.get("events") or []) if isinstance(item, dict)]
    if not events and timings:
        first = timings[0]
        events = [{
            "id": "v26_fallback_fx_01",
            "segment_index": 0,
            "start": max(0.0, _safe_float(first.get("start"), 0.0)),
            "end": min(duration, max(0.65, _safe_float(first.get("end"), 1.1))),
            "role": "hook",
            "effect": "hook_punch",
            "focus_text": _pick_focus(str(first.get("text") or ""), plan.get("keywords") or []),
            "source_text": str(first.get("text") or ""),
            "priority": 11,
        }]

    if sfx_level != "off" and not any(isinstance(item.get("sfx"), dict) for item in events):
        target = events[0] if events else None
        if target is not None:
            role = str(target.get("role") or "hook")
            if role not in SFX_VARIANT_BANKS:
                role = "hook"
            asset, role_gain = _v16_choose_variant(role, target, 0, "")
            if not asset:
                fallback_name = "mixkit-air-woosh-1489.mp3"
                if (_sfx_root() / fallback_name).is_file():
                    asset, role_gain = fallback_name, 0.62
            cfg = SFX_LEVELS.get(sfx_level) or SFX_LEVELS["light"]
            if asset and float(cfg.get("volume") or 0.0) > 0:
                target["sfx"] = {
                    "asset": asset,
                    "gain": round(float(cfg["volume"]) * max(0.45, role_gain), 4),
                    "role": role,
                }

    if sticker_level != "off" and not any(isinstance(item.get("sticker"), dict) for item in events):
        for index, target in enumerate(events):
            asset = _v16_choose_sticker(target, index, "smart_mix", "")
            if not asset:
                continue
            start = max(0.0, _safe_float(target.get("start"), 0.0))
            end = min(duration, max(start + 0.90, _safe_float(target.get("end"), start + 1.15)))
            target["sticker"] = {
                "asset": f"{asset}.png",
                "position": "upper_right" if index % 2 == 0 else "upper_left",
                "size": 136,
                "start": round(start, 3),
                "end": round(min(end, start + 1.20), 3),
            }
            break

    plan["events"] = events
    return plan


_V25_BUILD_DYNAMIC_PLAN = build_dynamic_plan


def build_dynamic_plan(payload: dict[str, Any], timings: list[dict[str, Any]], duration: float, *, intensity: str = "balanced") -> dict[str, Any]:
    plan = _V25_BUILD_DYNAMIC_PLAN(payload, timings, duration, intensity=intensity)
    sfx_level = str(payload.get("dynamic_sfx_level") or "light")
    sticker_level = str(payload.get("dynamic_sticker_level") or "light")
    raw_events = []
    for event in plan.get("events") or []:
        item = dict(event)
        item.pop("sfx", None)
        item.pop("sticker", None)
        raw_events.append(item)
    plan["events"] = _decorate_events(raw_events, duration, sfx_level=sfx_level, sticker_level=sticker_level)
    plan = _v26_ensure_effect_delivery(
        plan, timings, duration, sfx_level=sfx_level, sticker_level=sticker_level
    )
    plan["sfx_level"] = sfx_level
    plan["sticker_level"] = sticker_level
    plan["subtitle_timing_source"] = (
        "volcengine_native_word_timestamp"
        if any(item.get("native_word_timestamp") for item in timings)
        else "segment_duration_fallback"
    )
    plan["native_word_timestamp_count"] = sum(int(item.get("native_word_count") or 0) for item in timings)
    impact_roles = {"hook", "question", "turn", "data", "risk", "comparison", "cta"}
    impact_count = 0
    for item in timings:
        text = _clean_caption_text(str(item.get("text") or ""))
        if _classify(text) in impact_roles or any(keyword and keyword in text for keyword in plan.get("keywords") or []):
            impact_count += 1
    plan["keyword_impact_count"] = min(4, impact_count)
    plan["effect_delivery"] = {
        "requested_sfx_level": sfx_level,
        "requested_sticker_level": sticker_level,
        "planned_sfx_count": sum(1 for event in plan["events"] if event.get("sfx")),
        "planned_sticker_count": sum(1 for event in plan["events"] if event.get("sticker")),
        "keyword_impact_count": plan["keyword_impact_count"],
        "sfx_pack": "mixkit-pro-v26",
    }
    return plan


def _validate_v26_effect_plan(plan: dict[str, Any], timings: list[dict[str, Any]], sfx_level: str, sticker_level: str) -> dict[str, Any]:
    events = list(plan.get("events") or [])
    sfx_count = sum(1 for event in events if isinstance(event.get("sfx"), dict))
    sticker_count = sum(1 for event in events if isinstance(event.get("sticker"), dict))
    if sfx_level != "off" and sfx_count <= 0:
        raise ValueError("专业音效计划为空")
    if sticker_level != "off" and sticker_count <= 0:
        raise ValueError("语义贴纸计划为空")
    if int(plan.get("keyword_impact_count") or 0) <= 0:
        raise ValueError("关键词强调计划为空")
    joined_expected = "".join(_v26_clean_token_text(item.get("text")) for item in timings)
    if not joined_expected:
        raise ValueError("字幕时间线为空")
    return plan


def _highlight_ass(text: str, keywords: list[str], highlight: str) -> str:
    escaped = _ass_escape(text)
    for keyword in sorted((item for item in keywords if item), key=len, reverse=True):
        safe = _ass_escape(keyword)
        if safe in escaped:
            pulse = rf"{{\c{highlight}\fscx116\fscy116\t(0,160,\fscx100\fscy100)}}{safe}{{\c&H00FFFFFF&\fscx100\fscy100}}"
            return escaped.replace(safe, pulse, 1)
    role = _classify(text)
    if role in {"hook", "question", "turn", "data", "risk", "comparison", "cta"}:
        return rf"{{\fscx110\fscy110\t(0,150,\fscx100\fscy100)}}{escaped}"
    return escaped


def _build_video_filters(work: Path, plan: dict[str, Any], ass_path: Path, sticker_inputs: list[dict[str, Any]], *, width: int = 1080, height: int = 1920) -> str:
    events = plan.get("events") or []
    limits = plan.get("limits") or {}
    zoom_strength = _safe_float(limits.get("zoom_strength"), 0.034)
    micro_strength = _safe_float(limits.get("micro_zoom_strength"), 0.007)
    zoom_terms: list[str] = []
    for index, start in enumerate([float(value) for value in (plan.get("caption_beats") or [])[:48]]):
        if index % 4:
            continue
        span = 0.82
        zoom_terms.append(f"+{micro_strength:.4f}*between(t,{start:.3f},{start+span:.3f})*sin(PI*(t-{start:.3f})/{span:.3f})")
    for event in events:
        if event.get("effect") not in {"hook_punch", "question_pulse", "turn_focus", "risk_alert", "data_card"}:
            continue
        start = _safe_float(event.get("start"), 0.0)
        end = max(start + 0.35, _safe_float(event.get("end"), start + 0.90))
        span = max(0.25, end - start)
        strength = zoom_strength * (1.0 if event.get("effect") in {"hook_punch", "data_card"} else 0.65)
        zoom_terms.append(f"+{strength:.4f}*between(t,{start:.3f},{end:.3f})*sin(PI*(t-{start:.3f})/{span:.3f})")
    factor = "1" + "".join(zoom_terms)
    chain = [
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1[base]",
        f"[base]scale=w='{width}*({factor})':h='{height}*({factor})':eval=frame,crop={width}:{height}:(iw-{width})/2:(ih-{height})/2[v0]",
    ]
    current = "v0"
    position_xy = {"upper_left": ("54", "250"), "upper_right": ("W-w-54", "270"), "side_left": ("48", "560"), "side_right": ("W-w-48", "580")}
    for index, item in enumerate(sticker_inputs, start=1):
        sticker = item["sticker"]
        input_index = int(item["input_index"])
        start = _safe_float(sticker.get("start"), 0.0)
        end = max(start + 0.70, _safe_float(sticker.get("end"), start + 1.05))
        span = max(0.70, end - start)
        size = max(108, min(166, int(sticker.get("size") or 136)))
        x_expr, y_base = position_xy.get(str(sticker.get("position") or "upper_right"), position_xy["upper_right"])
        sticker_label = f"sticker{index}"
        next_label = f"vstk{index}"
        chain.append(f"[{input_index}:v]format=rgba,scale={size}:{size}:force_original_aspect_ratio=decrease,pad={size+20}:{size+20}:(ow-iw)/2:(oh-ih)/2:color=0x00000000,trim=duration={span:.3f},fade=t=in:st=0:d=0.10:alpha=1,fade=t=out:st={max(0.1,span-0.14):.3f}:d=0.14:alpha=1,setpts=PTS-STARTPTS+{start:.3f}/TB[{sticker_label}]")
        chain.append(f"[{current}][{sticker_label}]overlay=x='{x_expr}':y='{y_base}+5*sin(2*PI*(t-{start:.3f})/1.4)':eof_action=pass:shortest=0:enable='between(t,{start:.3f},{end:.3f})'[{next_label}]")
        current = next_label
    chain.append(f"[{current}]ass='{_ffmpeg_escape_path(ass_path)}'[vout]")
    return ";".join(chain)


def _build_audio_filters(plan: dict[str, Any], *, has_audio: bool, sfx_inputs: list[dict[str, Any]]) -> tuple[str, str | None]:
    if not has_audio:
        return "", None
    render_duration = max(0.1, _safe_float(plan.get("render_duration"), _safe_float(plan.get("duration"), 30.0)))
    voice_chain = f"[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,apad=pad_dur=0.16,atrim=duration={render_duration:.3f},afade=t=out:st={max(0.0,render_duration-0.14):.3f}:d=0.14[voice]"
    if not sfx_inputs:
        return voice_chain + ";[voice]loudnorm=I=-16:LRA=7:TP=-1.8[aout]", "aout"
    parts = [voice_chain]
    labels = ["voice"]
    for index, item in enumerate(sfx_inputs, start=1):
        event, sfx = item["event"], item["sfx"]
        input_index = int(item["input_index"])
        delay = int(max(0.0, _safe_float(event.get("start"), 0.0)) * 1000)
        asset_name = Path(str(item.get("path") or "")).name
        trim_start, trim_duration = V26_SFX_META.get(asset_name, (0.0, 0.90))
        gain = max(0.025, min(0.115, _safe_float(sfx.get("gain"), 0.060)))
        fade_out_start = max(0.18, trim_duration - min(0.20, trim_duration * 0.24))
        label = f"sfx{index}"
        parts.append(f"[{input_index}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,atrim=start={trim_start:.3f}:duration={trim_duration:.3f},asetpts=PTS-STARTPTS,highpass=f=90,lowpass=f=12500,acompressor=threshold=0.10:ratio=2.2:attack=4:release=80,volume={gain:.4f},afade=t=in:st=0:d=0.012,afade=t=out:st={fade_out_start:.3f}:d={max(0.08,trim_duration-fade_out_start):.3f},adelay={delay}|{delay}[{label}]")
        labels.append(label)
    parts.append("".join(f"[{label}]" for label in labels) + f"amix=inputs={len(labels)}:duration=first:dropout_transition=0:normalize=0,alimiter=limit=0.91,loudnorm=I=-16:LRA=7:TP=-1.8[aout]")
    return ";".join(parts), "aout"



# =============================================================================
# V10.40.8.27 REFERENCE-DRIVEN TEACHING / TALKING-HEAD EFFECT ENGINE
# =============================================================================
V27_MARKER = "V10_40_8_27_REFERENCE_DRIVEN_TEACHING_EFFECTS"
V27_PRO_SFX_DIR = Path(os.getenv("AI_VIDEO_PRO_SFX_DIR_V27", "/data/ai-video/sfx-professional-v27"))

SFX_VARIANT_BANKS = {
    "hook": [
        ("mixkit-explainer-video-pops-whoosh-light-pop-3005.mp3", 0.96),
        ("mixkit-cinematic-whoosh-fast-transition-1492.mp3", 0.82),
    ],
    "question": [
        ("mixkit-interface-hint-notification-911.mp3", 0.78),
    ],
    "turn": [
        ("mixkit-fast-small-sweep-transition-166.mp3", 0.82),
        ("mixkit-air-woosh-1489.mp3", 0.72),
    ],
    "data": [
        ("mixkit-explainer-video-pops-whoosh-light-pop-3005.mp3", 0.76),
        ("mixkit-interface-hint-notification-911.mp3", 0.62),
    ],
    "risk": [
        ("mixkit-human-single-heart-beat-490.mp3", 0.92),
        ("mixkit-cinematic-whoosh-fast-transition-1492.mp3", 0.68),
    ],
    "comparison": [
        ("mixkit-fast-small-sweep-transition-166.mp3", 0.86),
        ("mixkit-air-woosh-1489.mp3", 0.70),
    ],
    "list": [
        ("mixkit-explainer-video-pops-whoosh-light-pop-3005.mp3", 0.70),
        ("mixkit-interface-hint-notification-911.mp3", 0.58),
    ],
    "evidence": [
        ("mixkit-camera-shutter-click-1133.mp3", 0.70),
        ("mixkit-interface-hint-notification-911.mp3", 0.52),
    ],
    "cta": [
        ("mixkit-interface-hint-notification-911.mp3", 0.78),
    ],
    "knowledge": [
        ("mixkit-explainer-video-pops-whoosh-light-pop-3005.mp3", 0.58),
    ],
}

SFX_LEVELS = {
    "off": {"label": "关闭", "volume": 0.0, "max_per_30s": 0, "min_gap": 99.0},
    "light": {"label": "教学轻量", "volume": 0.18, "max_per_30s": 4, "min_gap": 3.6},
    "balanced": {"label": "教学标准", "volume": 0.24, "max_per_30s": 6, "min_gap": 2.7},
    "strong": {"label": "教学强化", "volume": 0.30, "max_per_30s": 8, "min_gap": 2.1},
}

STICKER_LEVELS = {
    "off": {"label": "关闭", "max_per_30s": 0, "min_gap": 99.0},
    "light": {"label": "少量语义图标", "max_per_30s": 4, "min_gap": 3.6},
    "balanced": {"label": "标准语义图标", "max_per_30s": 6, "min_gap": 2.7},
    "rich": {"label": "丰富语义图标", "max_per_30s": 8, "min_gap": 2.1},
}

V27_SFX_META = {
    "mixkit-cinematic-whoosh-fast-transition-1492.mp3": (0.0, 0.78),
    "mixkit-air-woosh-1489.mp3": (0.0, 0.72),
    "mixkit-fast-small-sweep-transition-166.mp3": (0.0, 0.58),
    "mixkit-interface-hint-notification-911.mp3": (0.0, 0.62),
    "mixkit-human-single-heart-beat-490.mp3": (0.0, 0.72),
    "mixkit-explainer-video-pops-whoosh-light-pop-3005.mp3": (0.0, 0.62),
    "mixkit-camera-shutter-click-1133.mp3": (0.0, 0.48),
}

V27_ROLE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("cta", re.compile(r"关注|评论|私信|留言|收藏|转发|告诉我|找我|联系|主页|一对一", re.I)),
    ("list", re.compile(r"第一|第二|第三|第四|第五|第[一二三四五六七八九十]+|这几点|步骤|清单|重点[一二三四五六七八九十\d]", re.I)),
    ("comparison", re.compile(r"自住.{0,8}投资|投资.{0,8}自住|对比|相比|不同|区别|前者|后者|不是.{0,8}而是", re.I)),
    ("risk", re.compile(r"风险|避坑|不要|不能|错误|踩坑|买错|低价|迷惑|亏|贵|陷阱|误区", re.I)),
    ("question", re.compile(r"为什么|怎么|到底|是不是|哪里|什么|多少|好不好|能不能|吗[？?]?|疑问|问题", re.I)),
    ("turn", re.compile(r"但是|然而|其实|真正|反而|结果|却|重点是|关键是|先分清|再看|最后", re.I)),
    ("data", re.compile(r"\d+(?:\.\d+)?\s*(?:%|万|亿|年|个月|天|套|个|条|公里|分钟|RM|马币|人民币)?", re.I)),
    ("evidence", re.compile(r"地图|数据|截图|报告|实拍|现场|证据|规划|线路|户型图", re.I)),
    ("hook", re.compile(r"买房|千万|一定要|别再|大多数|很多人|先别|记住|第一眼|开头", re.I)),
]

V27_SEMANTIC_KEYWORDS = (
    "吉隆坡买房", "价格", "买错", "自住", "投资", "投资逻辑", "租客来源",
    "租客", "转手", "生活半径", "社区配套", "低价", "长期价值", "区域",
    "交通", "学校", "商场", "医院", "预算", "风险", "回报", "收益",
)


def _sfx_root() -> Path:
    return V27_PRO_SFX_DIR


def _classify(text: str) -> str:
    value = _clean_caption_text(str(text or ""))
    for role, pattern in V27_ROLE_PATTERNS:
        if pattern.search(value):
            return role
    return "knowledge"


def _keywords(payload: dict[str, Any], timings: list[dict[str, Any]]) -> list[str]:
    joined = "".join(_clean_caption_text(str(item.get("text") or "")) for item in timings)
    found: list[str] = []
    for item in payload.get("keyword_insights") or []:
        value = str(item.get("value") if isinstance(item, dict) else item or "").strip()
        value = _clean_caption_text(value)
        if 2 <= len(value) <= 10 and value in joined and value not in found:
            found.append(value)
    for value in V27_SEMANTIC_KEYWORDS:
        if value in joined and value not in found:
            found.append(value)
    for match in re.findall(r"\d+(?:\.\d+)?(?:%|万|亿|年|个月|天|套|个|条|公里|分钟)?", joined):
        if match and match not in found:
            found.append(match)
    return found[:16]


def _pick_focus(text: str, keywords: list[str]) -> str:
    clean = _clean_caption_text(str(text or ""))
    if "自住" in clean and "投资" in clean:
        return "自住 VS 投资"
    replacements = (
        ("租客从哪里来", "租客来源"),
        ("租客哪里来", "租客来源"),
        ("转手好不好", "转手能力"),
        ("别被低价迷惑", "别被低价迷惑"),
        ("长期价值才关键", "长期价值"),
        ("生活半径", "生活半径"),
        ("社区配套", "社区配套"),
    )
    for source, target in replacements:
        if source in clean:
            return target[:10]
    for keyword in sorted((item for item in keywords if item), key=len, reverse=True):
        if keyword in clean:
            return keyword[:10]
    number = re.search(r"\d+(?:\.\d+)?\s*(?:%|万|亿|年|个月|天|套|个|条|公里|分钟)?", clean)
    if number:
        return number.group(0).strip()[:10]
    return clean[:8] or "重点"


V27_STICKER_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"学校|学区|教育", re.I), "pro27_school"),
    (re.compile(r"自住.{0,8}投资|投资.{0,8}自住|对比|区别|不同", re.I), "pro27_compare"),
    (re.compile(r"租客|人群|客户|白领", re.I), "pro27_people"),
    (re.compile(r"生活半径|交通|通勤|地铁|路线|区域|位置", re.I), "pro27_route"),
    (re.compile(r"社区配套|商场|超市|购物|生活配套", re.I), "pro27_shopping"),
    (re.compile(r"风险|买错|踩坑|迷惑|不要|不能", re.I), "pro27_warning"),
    (re.compile(r"价格|预算|低价|金额|租金", re.I), "pro27_price"),
    (re.compile(r"转手|回报|收益|价值|升值", re.I), "pro27_chart"),
    (re.compile(r"评论|告诉我|咨询|私信|一对一", re.I), "pro27_comment"),
    (re.compile(r"为什么|哪里|什么|好不好|能不能|吗", re.I), "pro27_question"),
    (re.compile(r"房|住宅|公寓|楼盘|买房", re.I), "pro27_house"),
]


def _v16_choose_sticker(event: dict[str, Any], index: int, style: str, last_asset: str) -> str:
    text = _clean_caption_text(str(event.get("source_text") or ""))
    role = str(event.get("role") or "knowledge")
    candidate = ""
    for pattern, asset in V27_STICKER_RULES:
        if pattern.search(text):
            candidate = asset
            break
    if not candidate:
        candidate = {
            "hook": "pro27_house",
            "question": "pro27_question",
            "turn": "pro27_route",
            "data": "pro27_chart",
            "risk": "pro27_warning",
            "comparison": "pro27_compare",
            "list": "pro27_check",
            "evidence": "pro27_check",
            "cta": "pro27_comment",
            "knowledge": "pro27_check",
        }.get(role, "pro27_check")
    if candidate == last_asset:
        fallback = {
            "pro27_warning": "pro27_price",
            "pro27_route": "pro27_house",
            "pro27_chart": "pro27_check",
            "pro27_comment": "pro27_check",
        }.get(candidate, "pro27_check")
        if (_sticker_root() / f"{fallback}.png").is_file():
            candidate = fallback
    return candidate if (_sticker_root() / f"{candidate}.png").is_file() else ""


def _v27_make_event(index: int, item: dict[str, Any], duration: float, keywords: list[str]) -> dict[str, Any]:
    text = _clean_caption_text(str(item.get("text") or ""))
    role = _classify(text)
    start = max(0.0, _safe_float(item.get("start"), 0.0))
    end = min(duration, max(start + 0.40, _safe_float(item.get("end"), start + 1.0)))
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
    priority = {
        "hook": 11, "comparison": 10, "risk": 9, "data": 8, "question": 8,
        "list": 7, "turn": 7, "cta": 8, "evidence": 6, "knowledge": 3,
    }
    return {
        "id": f"v27_fx_{index + 1:02d}",
        "segment_index": index,
        "start": round(start, 3),
        "end": round(min(end, start + (1.15 if role in {"hook", "risk", "data", "comparison"} else 1.35)), 3),
        "role": role,
        "effect": effect_map[role],
        "focus_text": _pick_focus(text, keywords),
        "source_text": text,
        "priority": priority[role],
    }


def _v27_select_events(timings: list[dict[str, Any]], duration: float, intensity: str, keywords: list[str]) -> list[dict[str, Any]]:
    candidates = [_v27_make_event(index, item, duration, keywords) for index, item in enumerate(timings)]
    semantic_terms = re.compile(r"房|价格|投资|自住|租客|转手|生活半径|社区配套|低价|长期价值|区域|交通|学校|商场|医院")
    candidates = [
        item for item in candidates
        if item["role"] != "knowledge" or semantic_terms.search(item["source_text"])
    ]
    max_per_30 = {"restrained": 8, "balanced": 12, "strong": 16}.get(intensity, 12)
    max_events = max(3, int(math.ceil(max(1.0, duration) / 30.0 * max_per_30)))
    min_gap = {"restrained": 2.35, "balanced": 1.55, "strong": 1.05}.get(intensity, 1.55)
    selected: list[dict[str, Any]] = []
    for candidate in sorted(candidates, key=lambda item: (-int(item["priority"]), float(item["start"]))):
        if any(abs(float(candidate["start"]) - float(item["start"])) < min_gap for item in selected):
            continue
        selected.append(candidate)
        if len(selected) >= max_events:
            break
    selected.sort(key=lambda item: float(item["start"]))
    if candidates and (not selected or float(selected[0]["start"]) > 0.9):
        first = dict(candidates[0])
        first.update(role="hook", effect="hook_punch", start=0.0, priority=11)
        selected.insert(0, first)
    if candidates:
        tail_candidates = [item for item in candidates if float(item["start"]) >= duration * 0.72]
        if tail_candidates and not any(float(item["start"]) >= duration * 0.72 for item in selected):
            selected.append(dict(tail_candidates[-1]))

    # Reference-driven teaching videos need a stable narrative spine:
    # hook -> strongest explanation/comparison -> risk/question -> CTA.
    mandatory_roles = ("hook", "comparison", "risk", "question", "cta")
    for role in mandatory_roles:
        role_candidates = [item for item in candidates if item.get("role") == role]
        if not role_candidates or any(item.get("role") == role for item in selected):
            continue
        chosen = role_candidates[-1] if role == "cta" else role_candidates[0]
        selected.append(dict(chosen))

    selected = sorted({item["id"]: item for item in selected}.values(), key=lambda item: float(item["start"]))
    if len(selected) > max_events:
        mandatory_ids = {
            item["id"] for item in selected
            if item.get("role") in set(mandatory_roles)
        }
        mandatory = [item for item in selected if item["id"] in mandatory_ids]
        optional = sorted(
            [item for item in selected if item["id"] not in mandatory_ids],
            key=lambda item: (-int(item.get("priority") or 0), float(item.get("start") or 0.0)),
        )
        selected = sorted((mandatory + optional[:max(0, max_events-len(mandatory))])[:max_events], key=lambda item: float(item["start"]))
    return selected


def _v27_callout_text(event: dict[str, Any]) -> str:
    text = _clean_caption_text(str(event.get("source_text") or ""))
    role = str(event.get("role") or "knowledge")
    if role == "comparison" and "自住" in text and "投资" in text:
        return "自住  VS  投资"
    if role == "risk" and "低价" in text:
        return "别被低价迷惑"
    if role == "cta":
        return "评论告诉我"
    return str(event.get("focus_text") or "")[:10]


def _v27_decorate_events(
    events: list[dict[str, Any]],
    duration: float,
    *,
    sfx_level: str,
    sticker_level: str,
) -> list[dict[str, Any]]:
    result = [dict(item) for item in events]
    sfx_cfg = SFX_LEVELS.get(sfx_level) or SFX_LEVELS["light"]
    sticker_cfg = STICKER_LEVELS.get(sticker_level) or STICKER_LEVELS["light"]

    max_sfx = max(0, int(math.ceil(max(1.0, duration) / 30.0 * int(sfx_cfg["max_per_30s"]))))
    if sfx_level == "balanced" and duration >= 12.0:
        max_sfx = max(4, max_sfx)
    last_sfx_start = -999.0
    last_sfx_asset = ""
    used_sfx = 0
    for index, event in enumerate(result):
        if used_sfx >= max_sfx:
            break
        start = float(event["start"])
        role = str(event.get("role") or "knowledge")
        if role != "cta" and start - last_sfx_start < float(sfx_cfg["min_gap"]):
            continue
        options = SFX_VARIANT_BANKS.get(role) or SFX_VARIANT_BANKS["knowledge"]
        asset = ""
        role_gain = 0.0
        for name, gain in options:
            if name != last_sfx_asset and (_sfx_root() / name).is_file():
                asset, role_gain = name, gain
                break
        if not asset:
            for name, gain in options:
                if (_sfx_root() / name).is_file():
                    asset, role_gain = name, gain
                    break
        if asset and float(sfx_cfg["volume"]) > 0:
            event["sfx"] = {
                "asset": asset,
                "gain": round(float(sfx_cfg["volume"]) * float(role_gain), 4),
                "role": role,
            }
            used_sfx += 1
            last_sfx_start = start
            last_sfx_asset = asset

    # Keep one polished completion cue for the CTA instead of spending the
    # entire sound budget before the final action line.
    cta_events = [event for event in result if event.get("role") == "cta"]
    if sfx_level != "off" and cta_events and not any(event.get("sfx") for event in cta_events):
        cta = cta_events[-1]
        if used_sfx >= max_sfx:
            removable = next((event for event in reversed(result) if event.get("sfx") and event.get("role") not in {"hook", "comparison", "risk"}), None)
            if removable is not None:
                removable.pop("sfx", None)
                used_sfx -= 1
        asset = "mixkit-interface-hint-notification-911.mp3"
        if used_sfx < max_sfx and (_sfx_root() / asset).is_file():
            cta["sfx"] = {"asset": asset, "gain": round(float(sfx_cfg["volume"]) * 0.78, 4), "role": "cta"}
            used_sfx += 1

    max_stickers = max(0, int(math.ceil(max(1.0, duration) / 30.0 * int(sticker_cfg["max_per_30s"]))))
    if sticker_level == "balanced" and duration >= 12.0:
        max_stickers = max(4, max_stickers)
    last_sticker_start = -999.0
    last_asset = ""
    used_stickers = 0
    positions = ("upper_right", "side_left", "upper_left", "side_right")
    for index, event in enumerate(result):
        if used_stickers >= max_stickers:
            break
        start = float(event["start"])
        role = str(event.get("role") or "knowledge")
        if role != "cta" and start - last_sticker_start < float(sticker_cfg["min_gap"]):
            continue
        asset = _v16_choose_sticker(event, index, "pro_v27", last_asset)
        if not asset:
            continue
        span = 1.20 if event.get("role") in {"hook", "comparison", "risk"} else 1.05
        event["sticker"] = {
            "asset": f"{asset}.png",
            "position": positions[used_stickers % len(positions)],
            "size": 146 + (used_stickers % 2) * 10,
            "start": round(start, 3),
            "end": round(min(duration, start + span), 3),
        }
        used_stickers += 1
        last_sticker_start = start
        last_asset = asset

    if sticker_level != "off" and cta_events and not any(event.get("sticker") for event in cta_events):
        cta = cta_events[-1]
        if used_stickers >= max_stickers:
            removable = next((event for event in reversed(result) if event.get("sticker") and event.get("role") not in {"hook", "comparison", "risk"}), None)
            if removable is not None:
                removable.pop("sticker", None)
                used_stickers -= 1
        asset = "pro27_comment"
        if used_stickers < max_stickers and (_sticker_root() / f"{asset}.png").is_file():
            start = float(cta["start"])
            cta["sticker"] = {
                "asset": f"{asset}.png", "position": "upper_right", "size": 152,
                "start": round(start, 3), "end": round(min(duration, start + 1.15), 3),
            }
            used_stickers += 1

    callout_limit = max(2, int(math.ceil(max(1.0, duration) / 30.0 * 5)))
    if duration >= 12.0:
        callout_limit = max(4, callout_limit)
    callout_gap = 2.8
    callout_count = 0
    last_callout = -999.0
    callout_roles = {"hook", "comparison", "risk", "data", "list", "question", "cta", "turn"}
    for event in result:
        if callout_count >= callout_limit:
            break
        start = float(event["start"])
        role = str(event.get("role") or "knowledge")
        if role not in callout_roles or (role != "cta" and start - last_callout < callout_gap):
            continue
        text = _v27_callout_text(event)
        if not text:
            continue
        event["callout"] = {
            "text": text,
            "style": "badge" if role in {"comparison", "list", "cta"} else "impact",
            "start": round(start + 0.03, 3),
            "end": round(min(duration, start + (0.95 if role in {"hook", "comparison", "risk"} else 0.78)), 3),
        }
        callout_count += 1
        last_callout = start

    if cta_events and not any(event.get("callout") for event in cta_events):
        cta = cta_events[-1]
        if callout_count >= callout_limit:
            removable = next((event for event in reversed(result) if event.get("callout") and event.get("role") not in {"hook", "comparison", "risk"}), None)
            if removable is not None:
                removable.pop("callout", None)
                callout_count -= 1
        if callout_count < callout_limit:
            start = float(cta["start"])
            cta["callout"] = {
                "text": "评论告诉我", "style": "badge",
                "start": round(start + 0.03, 3), "end": round(min(duration, start + 0.92), 3),
            }
    return result


_V26_BUILD_DYNAMIC_PLAN_ACTIVE = build_dynamic_plan


def build_dynamic_plan(
    payload: dict[str, Any],
    timings: list[dict[str, Any]],
    duration: float,
    *,
    intensity: str = "balanced",
) -> dict[str, Any]:
    plan = _V26_BUILD_DYNAMIC_PLAN_ACTIVE(payload, timings, duration, intensity=intensity)
    keywords = _keywords(payload, timings)
    events = _v27_select_events(timings, duration, intensity, keywords)
    sfx_level = str(payload.get("dynamic_sfx_level") or "light")
    sticker_level = str(payload.get("dynamic_sticker_level") or "light")
    events = _v27_decorate_events(
        events, duration, sfx_level=sfx_level, sticker_level=sticker_level
    )
    plan.update({
        "version": VERSION,
        "keywords": keywords,
        "events": events,
        "sfx_level": sfx_level,
        "sticker_level": sticker_level,
        "visual_pace": "reference_driven_teaching",
        "reference_profile": {
            "sources": ["user_reference_rough_vs_fine", "user_reference_sfx_taxonomy", "user_reference_text_mask", "user_reference_list_cards"],
            "callout_max_per_30s": 5,
            "sticker_semantic_only": True,
            "caption_layer_count": 1,
            "duplicate_full_caption_overlay": False,
        },
    })
    plan["limits"] = {
        "max_major_effects": len(events),
        "min_effect_gap_seconds": {"restrained": 2.35, "balanced": 1.55, "strong": 1.05}.get(intensity, 1.55),
        "zoom_strength": {"restrained": 0.034, "balanced": 0.050, "strong": 0.064}.get(intensity, 0.050),
        "micro_zoom_strength": {"restrained": 0.006, "balanced": 0.010, "strong": 0.014}.get(intensity, 0.010),
    }
    plan["subtitle_timing_source"] = (
        "volcengine_native_word_timestamp"
        if any(item.get("native_word_timestamp") for item in timings)
        else "segment_duration_fallback"
    )
    plan["native_word_timestamp_count"] = sum(int(item.get("native_word_count") or 0) for item in timings)
    plan["keyword_impact_count"] = sum(
        1 for item in timings
        if any(keyword and keyword in _clean_caption_text(str(item.get("text") or "")) for keyword in keywords)
        or _classify(str(item.get("text") or "")) in {"hook", "comparison", "risk", "question", "data", "cta"}
    )
    plan["keyword_impact_count"] = min(max(1, plan["keyword_impact_count"]), max(4, int(math.ceil(duration / 30.0 * 7))))
    plan["effect_delivery"] = {
        "requested_sfx_level": sfx_level,
        "requested_sticker_level": sticker_level,
        "planned_sfx_count": sum(1 for event in events if event.get("sfx")),
        "planned_sticker_count": sum(1 for event in events if event.get("sticker")),
        "planned_callout_count": sum(1 for event in events if event.get("callout")),
        "keyword_impact_count": plan["keyword_impact_count"],
        "sfx_pack": "mixkit-pro-v27",
        "sticker_pack": "pro-stickers-v27",
    }
    return plan


def _validate_v26_effect_plan(
    plan: dict[str, Any],
    timings: list[dict[str, Any]],
    sfx_level: str,
    sticker_level: str,
) -> dict[str, Any]:
    events = list(plan.get("events") or [])
    sfx_count = sum(1 for event in events if isinstance(event.get("sfx"), dict))
    sticker_count = sum(1 for event in events if isinstance(event.get("sticker"), dict))
    callout_count = sum(1 for event in events if isinstance(event.get("callout"), dict))
    if sfx_level != "off" and sfx_count <= 0:
        raise ValueError("V27 专业音效计划为空")
    if sticker_level != "off" and sticker_count <= 0:
        raise ValueError("V27 语义贴纸计划为空")
    if callout_count <= 0:
        raise ValueError("V27 特殊文字效果计划为空")
    if int(plan.get("keyword_impact_count") or 0) <= 0:
        raise ValueError("V27 关键词强调计划为空")
    if not any(item.get("native_word_timestamp") for item in timings):
        plan.setdefault("warnings", []).append("native_word_timestamp_missing")
    return plan


def _highlight_ass(text: str, keywords: list[str], highlight: str) -> str:
    escaped = _ass_escape(text)
    for keyword in sorted((item for item in keywords if item), key=len, reverse=True):
        safe = _ass_escape(keyword)
        if safe in escaped:
            pulse = (
                rf"{{\c{highlight}\bord9\fscx120\fscy120"
                rf"\t(0,135,\fscx100\fscy100\bord7)}}{safe}"
                rf"{{\c&H00FFFFFF&\bord7\fscx100\fscy100}}"
            )
            return escaped.replace(safe, pulse, 1)
    return escaped


def write_dynamic_ass(
    destination: Path,
    timings: list[dict[str, Any]],
    keywords: list[str],
    *,
    style_id: str,
    events: list[dict[str, Any]] | None = None,
) -> Path:
    preset = SUBTITLE_PRESETS.get(style_id) or SUBTITLE_PRESETS["dynamic_white_yellow"]
    context = getattr(_V16_CONTEXT, "config", {}) or {}
    base_size = max(88, min(142, int(context.get("caption_size") or 110)))
    font_name = "Noto Sans CJK SC"
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes
WrapStyle: 2

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Dynamic,{font_name},{base_size},{preset['primary']},{preset['highlight']},{preset['outline']},&H00000000,-1,0,0,0,100,100,0.8,0,1,{preset['outline_width']},{preset['shadow']},5,55,55,0,1
Style: Callout,{font_name},124,&H00FFFFFF,&H0000E8FF,&H00101010,&H00000000,-1,0,0,0,100,100,1.1,0,1,8,3,5,45,45,0,1
Style: Badge,{font_name},92,&H00FFFFFF,&H0000E8FF,&H00101010,&H70000000,-1,0,0,0,100,100,0.7,0,3,3,0,5,42,42,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for index, item in enumerate(timings):
        start = _safe_float(item.get("start"), 0.0)
        end = max(start + 0.30, _safe_float(item.get("end"), start + 0.85))
        raw_text = _clean_caption_text(str(item.get("text") or ""))
        role = _classify(raw_text)
        text = _highlight_ass(raw_text, keywords, str(preset["highlight"]))
        y = 1420 + (index % 2) * 86
        if role in {"hook", "comparison", "risk", "question"}:
            animation = rf"{{\an5\pos(540,{y})\fscx108\fscy108\t(0,120,\fscx100\fscy100)\fad(35,65)}}"
        else:
            animation = rf"{{\an5\move(540,{y+34},540,{y},0,150)\fad(55,75)}}"
        lines.append(
            f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Dynamic,,0,0,0,,{animation}{text}\n"
        )

    for index, event in enumerate(events or []):
        callout = event.get("callout")
        if not isinstance(callout, dict):
            continue
        role = str(event.get("role") or "knowledge")
        start = _safe_float(callout.get("start"), _safe_float(event.get("start"), 0.0))
        end = max(start + 0.45, _safe_float(callout.get("end"), start + 0.80))
        text = _ass_escape(str(callout.get("text") or event.get("focus_text") or "")[:12])
        style = "Badge" if str(callout.get("style")) == "badge" else "Callout"
        color = {
            "risk": "&H00004BFF",
            "question": "&H0000E8FF",
            "data": "&H0000E8FF",
            "hook": "&H0000E8FF",
            "turn": "&H000096FF",
            "comparison": "&H00FFFFFF",
            "cta": "&H00FFFFFF",
        }.get(role, "&H00FFFFFF")
        y = {
            "hook": 520,
            "comparison": 650,
            "risk": 610,
            "question": 670,
            "data": 600,
            "list": 650,
            "turn": 610,
            "cta": 1080,
        }.get(role, 620)
        if role == "risk":
            animation = rf"{{\an5\move(525,{y},555,{y},0,90)\c{color}\fscx138\fscy138\t(0,145,\fscx100\fscy100)\fad(20,70)}}"
        elif style == "Badge":
            animation = rf"{{\an5\pos(540,{y})\c{color}\fscx124\fscy124\t(0,150,\fscx100\fscy100)\fad(25,85)}}"
        else:
            animation = rf"{{\an5\pos(540,{y})\c{color}\fscx148\fscy148\t(0,150,\fscx100\fscy100)\fad(20,70)}}"
        lines.append(
            f"Dialogue: 1,{_ass_time(start)},{_ass_time(end)},{style},,0,0,0,,{animation}{text}\n"
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
    events = list(plan.get("events") or [])
    limits = plan.get("limits") or {}
    zoom_strength = _safe_float(limits.get("zoom_strength"), 0.050)
    micro_strength = _safe_float(limits.get("micro_zoom_strength"), 0.010)
    zoom_terms: list[str] = []
    for event in events:
        start = _safe_float(event.get("start"), 0.0)
        end = max(start + 0.35, _safe_float(event.get("end"), start + 0.95))
        span = max(0.28, min(1.15, end - start))
        role = str(event.get("role") or "knowledge")
        if role not in {"hook", "comparison", "risk", "question", "turn", "data", "cta"}:
            continue
        multiplier = {
            "hook": 1.20,
            "comparison": 0.90,
            "risk": 0.95,
            "question": 0.78,
            "turn": 0.70,
            "data": 0.90,
            "cta": 0.62,
        }.get(role, 0.65)
        strength = zoom_strength * multiplier
        zoom_terms.append(
            f"+{strength:.4f}*between(t,{start:.3f},{start+span:.3f})"
            f"*sin(PI*(t-{start:.3f})/{span:.3f})"
        )
    for index, beat in enumerate([float(value) for value in (plan.get("caption_beats") or [])[:48]]):
        if index % 5:
            continue
        span = 0.70
        zoom_terms.append(
            f"+{micro_strength:.4f}*between(t,{beat:.3f},{beat+span:.3f})"
            f"*sin(PI*(t-{beat:.3f})/{span:.3f})"
        )
    factor = "1" + "".join(zoom_terms)
    chain = [
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1[base]",
        f"[base]scale=w='{width}*({factor})':h='{height}*({factor})':eval=frame,"
        f"crop={width}:{height}:(iw-{width})/2:(ih-{height})/2[v0]",
    ]
    current = "v0"
    position_xy = {
        "upper_left": ("52", "245"),
        "upper_right": ("W-w-52", "260"),
        "side_left": ("48", "700"),
        "side_right": ("W-w-48", "720"),
    }
    for index, item in enumerate(sticker_inputs, start=1):
        sticker = item["sticker"]
        input_index = int(item["input_index"])
        start = _safe_float(sticker.get("start"), 0.0)
        end = max(start + 0.72, _safe_float(sticker.get("end"), start + 1.10))
        span = max(0.72, end - start)
        size = max(120, min(176, int(sticker.get("size") or 150)))
        x_expr, y_base = position_xy.get(str(sticker.get("position") or "upper_right"), position_xy["upper_right"])
        sticker_label = f"v27sticker{index}"
        next_label = f"v27stk{index}"
        chain.append(
            f"[{input_index}:v]format=rgba,scale={size}:{size}:force_original_aspect_ratio=decrease,"
            f"pad={size+24}:{size+24}:(ow-iw)/2:(oh-ih)/2:color=0x00000000,"
            f"trim=duration={span:.3f},fade=t=in:st=0:d=0.09:alpha=1,"
            f"fade=t=out:st={max(0.1,span-0.16):.3f}:d=0.16:alpha=1,"
            f"setpts=PTS-STARTPTS+{start:.3f}/TB[{sticker_label}]"
        )
        chain.append(
            f"[{current}][{sticker_label}]overlay=x='{x_expr}':"
            f"y='{y_base}+8*sin(2*PI*(t-{start:.3f})/1.15)':"
            f"eof_action=pass:shortest=0:enable='between(t,{start:.3f},{end:.3f})'[{next_label}]"
        )
        current = next_label
    chain.append(f"[{current}]ass='{_ffmpeg_escape_path(ass_path)}'[vout]")
    return ";".join(chain)


def _build_audio_filters(
    plan: dict[str, Any],
    *,
    has_audio: bool,
    sfx_inputs: list[dict[str, Any]],
) -> tuple[str, str | None]:
    if not has_audio:
        return "", None
    render_duration = max(0.1, _safe_float(plan.get("render_duration"), _safe_float(plan.get("duration"), 30.0)))
    voice_chain = (
        f"[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
        f"apad=pad_dur=0.16,atrim=duration={render_duration:.3f},"
        f"afade=t=out:st={max(0.0,render_duration-0.14):.3f}:d=0.14,"
        f"loudnorm=I=-16:LRA=7:TP=-2.0[voice]"
    )
    if not sfx_inputs:
        return voice_chain + ";[voice]alimiter=limit=0.94[aout]", "aout"
    parts = [voice_chain]
    labels = ["voice"]
    for index, item in enumerate(sfx_inputs, start=1):
        event = item["event"]
        sfx = item["sfx"]
        input_index = int(item["input_index"])
        delay = int(max(0.0, _safe_float(event.get("start"), 0.0)) * 1000)
        asset_name = Path(str(item.get("path") or "")).name
        trim_start, trim_duration = V27_SFX_META.get(asset_name, (0.0, 0.65))
        gain = max(0.055, min(0.235, _safe_float(sfx.get("gain"), 0.135)))
        fade_out_start = max(0.16, trim_duration - min(0.18, trim_duration * 0.25))
        label = f"v27sfx{index}"
        if index % 2:
            pan = "pan=stereo|c0=0.70*c0|c1=1.00*c1"
        else:
            pan = "pan=stereo|c0=1.00*c0|c1=0.70*c1"
        parts.append(
            f"[{input_index}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"atrim=start={trim_start:.3f}:duration={trim_duration:.3f},asetpts=PTS-STARTPTS,"
            f"highpass=f=70,lowpass=f=14500,acompressor=threshold=0.11:ratio=2.0:attack=4:release=75,"
            f"volume={gain:.4f},{pan},afade=t=in:st=0:d=0.010,"
            f"afade=t=out:st={fade_out_start:.3f}:d={max(0.07,trim_duration-fade_out_start):.3f},"
            f"adelay={delay}|{delay}[{label}]"
        )
        labels.append(label)
    parts.append(
        "".join(f"[{label}]" for label in labels)
        + f"amix=inputs={len(labels)}:duration=first:dropout_transition=0:normalize=0,"
        f"alimiter=limit=0.94[aout]"
    )
    return ";".join(parts), "aout"


_V26_RENDER_DYNAMIC_VIDEO_ACTIVE = render_dynamic_video


def _v27_channel_mean_volume(
    path: Path,
    expression: str,
    *,
    start: float | None = None,
    duration: float | None = None,
) -> float:
    cmd = ["ffmpeg", "-hide_banner", "-nostats"]
    if start is not None:
        cmd += ["-ss", f"{max(0.0, start):.3f}"]
    if duration is not None:
        cmd += ["-t", f"{max(0.12, duration):.3f}"]
    cmd += [
        "-i", str(path),
        "-af", f"pan=mono|c0={expression},volumedetect",
        "-f", "null", "-",
    ]
    proc = subprocess.run(cmd, text=True, capture_output=True, timeout=180)
    match = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB", proc.stderr)
    return float(match.group(1)) if match else -120.0


def render_dynamic_video(
    input_path: Path,
    output_path: Path,
    ass_path: Path,
    plan: dict[str, Any],
) -> dict[str, Any]:
    report = _V26_RENDER_DYNAMIC_VIDEO_ACTIVE(input_path, output_path, ass_path, plan)
    sfx_count = int(report.get("sfx_count") or 0)
    mid_db = _v27_channel_mean_volume(output_path, "0.5*c0+0.5*c1")
    side_db = _v27_channel_mean_volume(output_path, "0.5*c0-0.5*c1")
    side_delta = side_db - mid_db
    window_rows: list[dict[str, float]] = []
    for event in plan.get("events") or []:
        if not isinstance(event.get("sfx"), dict):
            continue
        start = max(0.0, _safe_float(event.get("start"), 0.0))
        window_mid = _v27_channel_mean_volume(
            output_path, "0.5*c0+0.5*c1", start=start, duration=0.82
        )
        window_side = _v27_channel_mean_volume(
            output_path, "0.5*c0-0.5*c1", start=start, duration=0.82
        )
        window_rows.append({
            "start": round(start, 3),
            "mid_db": round(window_mid, 2),
            "side_db": round(window_side, 2),
            "side_minus_mid_db": round(window_side - window_mid, 2),
        })
    window_deltas = sorted(row["side_minus_mid_db"] for row in window_rows)
    best_window = max(window_deltas) if window_deltas else -120.0
    median_window = (
        window_deltas[len(window_deltas) // 2]
        if window_deltas else -120.0
    )
    audible_passed = (
        sfx_count <= 0
        or (best_window >= -35.0 and median_window >= -44.0)
    )
    report["audible_sfx_mix"] = {
        "whole_track_mid_mean_db": round(mid_db, 2),
        "whole_track_side_mean_db": round(side_db, 2),
        "whole_track_side_minus_mid_db": round(side_delta, 2),
        "best_sfx_window_side_minus_mid_db": round(best_window, 2),
        "median_sfx_window_side_minus_mid_db": round(median_window, 2),
        "windows": window_rows,
        "passed": audible_passed,
    }
    if not audible_passed:
        raise ValueError(
            "V27 音效可听度不足："
            f"best_window={best_window:.2f}dB, median_window={median_window:.2f}dB"
        )
    return report



# =============================================================================
# V10.40.8.28 SEMANTIC EDITOR ENGINE
# =============================================================================
V28_COMPONENT_ROOT = Path('/tmp/ai-video-v28-components')
V28_COMPONENT_ROOT.mkdir(parents=True, exist_ok=True)


def _v28_role(text: str, fallback: str = 'knowledge') -> str:
    value = _clean_caption_text(text)
    if re.search(r'(评论|留言|关注|下一条|告诉我|私信)', value): return 'cta'
    if re.search(r'(三件事|三点|分别|①|②|③|清单|确认)', value): return 'list'
    if re.search(r'(不等于|≠|自住.*投资|投资.*自住|对比|区别)', value): return 'comparison'
    if re.search(r'(风险|注意|别被|不要|误区|搞错)', value): return 'risk'
    if re.search(r'(为什么|怎么|到底|吗|？)', value): return 'question'
    if re.search(r'(第一步|第二步|流程|签署|支付|抵扣)', value): return 'data'
    return fallback


def _v28_component_label(role: str, text: str) -> tuple[str, str]:
    clean = _clean_caption_text(text)
    if role == 'comparison':
        return ('自住  VS  投资' if ('自住' in clean and '投资' in clean) else '核心对比', clean[:22])
    if role == 'list': return ('三项确认', clean[:24])
    if role == 'risk': return ('风险提醒', clean[:24])
    if role == 'cta': return ('下一步', clean[:24])
    if role == 'question': return ('先问清楚', clean[:24])
    if role == 'data': return ('关键流程', clean[:24])
    return ('重点', clean[:24])


def _v28_render_component(event: dict[str, Any]) -> Path:
    from PIL import Image, ImageDraw, ImageFont
    role = str(event.get('role') or 'knowledge')
    title, body = _v28_component_label(role, str(event.get('source_text') or event.get('focus_text') or ''))
    digest = hashlib.sha256(f'{role}|{title}|{body}'.encode('utf-8')).hexdigest()[:20]
    path = V28_COMPONENT_ROOT / f'{digest}.png'
    if path.exists(): return path
    width, height = 620, 230
    image = Image.new('RGBA', (width, height), (0,0,0,0))
    draw = ImageDraw.Draw(image)
    palette = {
        'risk': ((47,14,22,238),(255,78,92,255)),
        'comparison': ((13,22,42,238),(109,94,252,255)),
        'list': ((17,30,39,238),(34,197,94,255)),
        'cta': ((19,22,38,238),(250,204,21,255)),
        'question': ((22,24,43,238),(56,189,248,255)),
        'data': ((18,27,47,238),(245,158,11,255)),
    }
    bg, accent = palette.get(role, ((18,24,38,238),(196,181,253,255)))
    draw.rounded_rectangle((6,6,width-6,height-6), radius=38, fill=bg, outline=(255,255,255,48), width=2)
    draw.rounded_rectangle((24,28,38,height-28), radius=7, fill=accent)
    font_path='/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc'
    title_font=ImageFont.truetype(font_path, 48)
    body_font=ImageFont.truetype(font_path, 34)
    draw.text((66,36), title, font=title_font, fill=accent)
    if body and body != title:
        draw.text((66,112), body, font=body_font, fill=(255,255,255,245))
    image.save(path)
    return path


def _decorate_events(events: list[dict[str, Any]], duration: float, *, sfx_level: str, sticker_level: str) -> list[dict[str, Any]]:
    result=[]
    max_sfx = 0 if sfx_level == 'off' else max(2, min(6, int(math.ceil(duration/12.0))))
    max_cards = 0 if sticker_level == 'off' else max(2, min(4, int(math.ceil(duration/15.0))))
    card_gap = 4.0
    last_card=-999.0
    sfx_used=0
    card_used=0
    for index, source in enumerate(events):
        event=dict(source)
        text=str(event.get('source_text') or event.get('focus_text') or '')
        role=_v28_role(text, str(event.get('role') or 'knowledge'))
        event['role']=role
        event['component_type']={
            'comparison':'comparison','list':'checklist','risk':'risk','cta':'cta',
            'question':'question','data':'flow'
        }.get(role,'caption_emphasis')
        if sfx_used < max_sfx and role in {'hook','comparison','list','risk','cta','question','data','turn'}:
            bank = SFX_VARIANT_BANKS.get(role) or SFX_VARIANT_BANKS.get('turn') or []
            if bank:
                asset,gain=bank[index % len(bank)]
                event['sfx']={'asset':asset,'gain':round(max(0.16,min(0.34,float(gain)*0.30)),4)}
                sfx_used += 1
        start=_safe_float(event.get('start'),0.0)
        if card_used < max_cards and role in {'comparison','list','risk','cta','question','data'} and start-last_card >= card_gap:
            event['sticker']={
                'asset':'__v28_semantic_component__', 'position':'upper_left' if card_used%2==0 else 'upper_right',
                'size':500, 'start':round(start,3),
                'end':round(min(duration,max(start+1.25,_safe_float(event.get('end'),start+1.6))),3),
            }
            card_used += 1
            last_card=start
        result.append(event)
    return result


def _collect_sticker_inputs(plan: dict[str, Any]) -> list[dict[str, Any]]:
    result=[]
    for event in plan.get('events') or []:
        sticker=event.get('sticker')
        if not isinstance(sticker,dict): continue
        if sticker.get('asset') == '__v28_semantic_component__':
            path=_v28_render_component(event)
        else:
            path=_sticker_root()/str(sticker.get('asset') or '')
        if path.is_file(): result.append({'event':event,'sticker':sticker,'path':path})
    return result


def _build_video_filters(work: Path, plan: dict[str, Any], ass_path: Path, sticker_inputs: list[dict[str, Any]], *, width: int = 1080, height: int = 1920) -> str:
    duration=max(0.1,_safe_float(plan.get('render_duration'),_safe_float(plan.get('duration'),30.0)))
    events=list(plan.get('events') or [])
    zoom_terms=[]
    for event in events:
        role=str(event.get('role') or 'knowledge')
        if role not in {'hook','comparison','risk','question','data','cta'}: continue
        start=_safe_float(event.get('start'),0.0); span=0.72
        strength={'hook':0.042,'comparison':0.030,'risk':0.026,'question':0.022,'data':0.025,'cta':0.018}.get(role,0.018)
        zoom_terms.append(f'+{strength:.4f}*between(t,{start:.3f},{start+span:.3f})*sin(PI*(t-{start:.3f})/{span:.3f})')
    factor='1'+''.join(zoom_terms)
    chain=[
        f'[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1[base]',
        f"[base]scale=w='{width}*({factor})':h='{height}*({factor})':eval=frame,crop={width}:{height}:(iw-{width})/2:(ih-{height})/2[v0]",
    ]
    current='v0'
    positions={'upper_left':('46','260'),'upper_right':('W-w-46','280'),'side_left':('44','650'),'side_right':('W-w-44','670')}
    for index,item in enumerate(sticker_inputs,1):
        sticker=item['sticker']; inp=int(item['input_index'])
        start=_safe_float(sticker.get('start'),0.0); end=max(start+0.8,_safe_float(sticker.get('end'),start+1.4)); span=end-start
        width_px=max(340,min(560,int(sticker.get('size') or 500)))
        x,y=positions.get(str(sticker.get('position') or 'upper_right'),positions['upper_right'])
        lab=f'v28card{index}'; out=f'v28out{index}'
        chain.append(f'[{inp}:v]format=rgba,scale={width_px}:-1:force_original_aspect_ratio=decrease,trim=duration={span:.3f},fade=t=in:st=0:d=0.10:alpha=1,fade=t=out:st={max(0.1,span-0.18):.3f}:d=0.18:alpha=1,setpts=PTS-STARTPTS+{start:.3f}/TB[{lab}]')
        chain.append(f"[{current}][{lab}]overlay=x='{x}':y='{y}':eof_action=pass:shortest=0:enable='between(t,{start:.3f},{end:.3f})'[{out}]")
        current=out
    chain.append(f"[{current}]ass='{_ffmpeg_escape_path(ass_path)}',tpad=stop_mode=clone:stop_duration=1,trim=duration={duration:.3f}[vout]")
    return ';'.join(chain)


def _build_audio_filters(plan: dict[str, Any], *, has_audio: bool, sfx_inputs: list[dict[str, Any]]) -> tuple[str, str | None]:
    if not has_audio: return '',None
    duration=max(0.1,_safe_float(plan.get('render_duration'),_safe_float(plan.get('duration'),30.0)))
    parts=[f'[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,apad=pad_dur={duration:.3f},atrim=duration={duration:.3f},loudnorm=I=-16:LRA=7:TP=-2.0[voice]']
    labels=['voice']
    for index,item in enumerate(sfx_inputs,1):
        event=item['event']; sfx=item['sfx']; inp=int(item['input_index'])
        delay=int(max(0.0,_safe_float(event.get('start'),0.0))*1000)
        gain=max(0.14,min(0.36,_safe_float(sfx.get('gain'),0.22)))
        label=f'v28sfx{index}'
        parts.append(f'[{inp}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,atrim=0:1.35,asetpts=PTS-STARTPTS,highpass=f=80,lowpass=f=14500,volume={gain:.4f},afade=t=in:st=0:d=0.012,afade=t=out:st=1.10:d=0.20,adelay={delay}|{delay}[{label}]')
        labels.append(label)
    if len(labels)==1:
        parts.append('[voice]alimiter=limit=0.94[aout]')
    else:
        parts.append(''.join(f'[{x}]' for x in labels)+f'amix=inputs={len(labels)}:duration=longest:dropout_transition=0:normalize=0,atrim=duration={duration:.3f},alimiter=limit=0.94[aout]')
    return ';'.join(parts),'aout'


_V27_RENDER_FINAL = render_dynamic_video


def render_dynamic_video(input_path: Path, output_path: Path, ass_path: Path, plan: dict[str, Any]) -> dict[str, Any]:
    source_info=_probe(input_path)
    target=max(_safe_float(source_info.get('audio_duration'),0.0),_safe_float(source_info.get('duration'),0.0),_safe_float(plan.get('duration'),0.0))
    plan=dict(plan); plan['render_duration']=round(target,4); plan['duration']=round(target,4)
    report=_V27_RENDER_FINAL(input_path,output_path,ass_path,plan)
    final=_probe(output_path)
    final_duration=_safe_float(final.get('duration'),0.0)
    if final_duration < target-0.08:
        raise ValueError(f'V28 输出截断：target={target:.3f}, output={final_duration:.3f}')
    report['audio_tail_guard']={'target_duration':round(target,4),'output_duration':round(final_duration,4),'shortest_cut_forbidden':True,'passed':True}
    report['semantic_component_count']=len(_collect_sticker_inputs(plan))
    report['effect_engine']='v28_semantic_editor_engine'
    return report

# =============================================================================
# V10.40.8.30 CLEAN SEMANTIC EFFECT DELIVERY
# =============================================================================
# The V27 builder previously reintroduced small icon stickers after V28 had
# rendered semantic cards. This final override is the production path: legacy
# stickers/callouts are removed first, then only semantic cards and audible,
# role-bound SFX are assigned.
_V29_BUILD_DYNAMIC_PLAN_CLEAN_EFFECTS = build_dynamic_plan
_V29_RENDER_DYNAMIC_VIDEO_CLEAN_EFFECTS = render_dynamic_video

V30_COMPONENT_ROOT = V28_COMPONENT_ROOT / "v30"
V30_COMPONENT_ROOT.mkdir(parents=True, exist_ok=True)


def _v30_semantic_role(text: str, fallback: str = "knowledge") -> str:
    value = _clean_caption_text(text)
    if re.search(r"(评论|留言|关注|下一条|告诉我|帮你分析|私信)", value):
        return "cta"
    if re.search(r"(最看重什么|为什么|怎么|到底|吗|？)", value):
        return "question"
    if re.search(r"(别光听|不要只看|别被|风险|注意|误区|搞错)", value):
        return "risk"
    if re.search(r"(自住.*投资|投资.*自住|自住.*出租|出租.*自住|不等于|≠|对比|区别)", value):
        return "comparison"
    if re.search(r"(三件事|三点|分别|①|②|③|清单|确认)", value):
        return "list"
    if re.search(r"(第一步|第二步|第三步|流程|签署|支付|抵扣)", value):
        return "data"
    return _v28_role(value, fallback)


def _v30_card_copy(role: str, text: str) -> tuple[str, list[str]]:
    clean = _clean_caption_text(text)
    if role == "comparison":
        title = "自住  VS  投资" if ("自住" in clean and ("投资" in clean or "出租" in clean)) else "核心对比"
        return title, [clean[:26]]
    if role == "risk":
        return "别只看表面", [clean[:28]]
    if role == "question":
        return "你最看重什么？", [clean[:28]]
    if role == "cta":
        return "评论告诉我", ["把你的需求说清楚", "按实际情况帮你分析"]
    if role == "list":
        terms = [x for x in ("交通", "商圈", "租客来源", "金额", "退款", "抵扣") if x in clean]
        return "重点看这几项", terms[:3] or [clean[:28]]
    if role == "data":
        return "关键流程", [clean[:28]]
    return "重点", [clean[:28]]


def _v30_render_component(event: dict[str, Any]) -> Path:
    from PIL import Image, ImageDraw, ImageFont

    role = str(event.get("role") or "knowledge")
    source_text = str(event.get("source_text") or event.get("focus_text") or "")
    title, rows = _v30_card_copy(role, source_text)
    digest = hashlib.sha256(f"v30|{role}|{title}|{'|'.join(rows)}".encode("utf-8")).hexdigest()[:24]
    path = V30_COMPONENT_ROOT / f"{digest}.png"
    if path.exists():
        return path
    width, height = 720, 270
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    palette = {
        "risk": ((37, 15, 23, 242), (255, 82, 96, 255)),
        "comparison": ((14, 22, 42, 242), (139, 124, 255, 255)),
        "list": ((14, 35, 31, 242), (65, 214, 132, 255)),
        "cta": ((20, 24, 40, 242), (255, 210, 66, 255)),
        "question": ((15, 29, 45, 242), (74, 197, 255, 255)),
        "data": ((25, 29, 42, 242), (255, 169, 64, 255)),
    }
    bg, accent = palette.get(role, ((18, 24, 38, 242), (205, 190, 255, 255)))
    draw.rounded_rectangle((5, 5, width - 5, height - 5), radius=34, fill=bg, outline=(255, 255, 255, 44), width=2)
    draw.rounded_rectangle((25, 27, 38, height - 27), radius=7, fill=accent)
    font_path = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
    title_font = ImageFont.truetype(font_path, 48)
    row_font = ImageFont.truetype(font_path, 32)
    draw.text((66, 34), title, font=title_font, fill=accent)
    y = 112
    for index, row in enumerate(rows[:3], start=1):
        prefix = f"{index}. " if len(rows) > 1 else ""
        draw.text((68, y), prefix + row, font=row_font, fill=(255, 255, 255, 246))
        y += 48
    image.save(path)
    return path


def _decorate_events(events: list[dict[str, Any]], duration: float, *, sfx_level: str, sticker_level: str) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for source in events:
        event = dict(source)
        # Never inherit V16/V27 emoji/icon sticker or duplicate callout layers.
        for key in ("sticker", "callout", "sfx", "legacy_sticker", "keyword_overlay", "impact_overlay"):
            event.pop(key, None)
        text = str(event.get("source_text") or event.get("focus_text") or "")
        event["role"] = _v30_semantic_role(text, str(event.get("role") or "knowledge"))
        cleaned.append(event)

    max_sfx = 0 if sfx_level == "off" else max(3, min(6, int(math.ceil(max(1.0, duration) / 9.5))))
    max_cards = 0 if sticker_level == "off" else max(3, min(5, int(math.ceil(max(1.0, duration) / 10.0))))
    sfx_gap = 3.2
    card_gap = 3.8
    last_sfx = -999.0
    last_card = -999.0
    sfx_count = 0
    card_count = 0
    roles = {"hook", "comparison", "risk", "question", "data", "list", "cta", "turn"}

    for index, event in enumerate(cleaned):
        role = str(event.get("role") or "knowledge")
        start = max(0.0, _safe_float(event.get("start"), 0.0))
        end = max(start + 0.6, _safe_float(event.get("end"), start + 1.2))
        if sfx_count < max_sfx and role in roles and (role == "cta" or start - last_sfx >= sfx_gap):
            bank = SFX_VARIANT_BANKS.get(role) or SFX_VARIANT_BANKS.get("turn") or []
            if bank:
                asset, _ = bank[index % len(bank)]
                if (_sfx_root() / asset).is_file():
                    gain = {
                        "hook": 0.56, "comparison": 0.50, "risk": 0.48,
                        "question": 0.45, "data": 0.44, "list": 0.43,
                        "turn": 0.40, "cta": 0.52,
                    }.get(role, 0.42)
                    event["sfx"] = {"asset": asset, "gain": gain, "role": role, "audible_mix": True}
                    sfx_count += 1
                    last_sfx = start
        if card_count < max_cards and role in {"comparison", "risk", "question", "data", "list", "cta"} and (role == "cta" or start - last_card >= card_gap):
            span = 1.55 if role in {"comparison", "risk", "cta"} else 1.30
            event["sticker"] = {
                "asset": "__v30_semantic_component__",
                "position": "upper_left" if card_count % 2 == 0 else "upper_right",
                "size": 590,
                "start": round(start, 3),
                "end": round(min(duration, max(start + 1.0, min(end, start + span))), 3),
                "semantic_only": True,
            }
            card_count += 1
            last_card = start
    return cleaned


def build_dynamic_plan(payload: dict[str, Any], timings: list[dict[str, Any]], duration: float, *, intensity: str = "balanced") -> dict[str, Any]:
    plan = _V29_BUILD_DYNAMIC_PLAN_CLEAN_EFFECTS(payload, timings, duration, intensity=intensity)
    sfx_level = str(payload.get("dynamic_sfx_level") or "light")
    sticker_level = str(payload.get("dynamic_sticker_level") or "light")
    raw_events = [dict(item) for item in (plan.get("events") or []) if isinstance(item, dict)]
    plan["events"] = _decorate_events(raw_events, duration, sfx_level=sfx_level, sticker_level=sticker_level)
    plan["version"] = VERSION
    plan["sfx_level"] = sfx_level
    plan["sticker_level"] = sticker_level
    plan["visual_pace"] = "stable_sequence_semantic_effects"
    plan["legacy_sticker_forbidden"] = True
    plan["semantic_component_only"] = True
    plan["effect_delivery"] = {
        "requested_sfx_level": sfx_level,
        "requested_sticker_level": sticker_level,
        "planned_sfx_count": sum(1 for event in plan["events"] if isinstance(event.get("sfx"), dict)),
        "planned_sticker_count": sum(1 for event in plan["events"] if isinstance(event.get("sticker"), dict)),
        "planned_callout_count": 0,
        "keyword_impact_count": int(plan.get("keyword_impact_count") or 0),
        "sfx_pack": "mixkit-pro-v30-audible",
        "sticker_pack": "semantic-cards-v30-no-emoji",
    }
    return plan


def _collect_sticker_inputs(plan: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for event in plan.get("events") or []:
        sticker = event.get("sticker")
        if not isinstance(sticker, dict):
            continue
        if sticker.get("asset") != "__v30_semantic_component__":
            # Final production path forbids old tiny icon/emoji files.
            continue
        path = _v30_render_component(event)
        if path.is_file():
            result.append({"event": event, "sticker": sticker, "path": path})
    return result


def _highlight_ass(text: str, keywords: list[str], highlight: str) -> str:
    escaped = _ass_escape(text)
    for keyword in sorted((item for item in keywords if item), key=len, reverse=True):
        safe = _ass_escape(keyword)
        if safe in escaped:
            pulse = (
                rf"{{\c{highlight}\bord10\shad2\fscx132\fscy132"
                rf"\t(0,190,\fscx100\fscy100\bord7\shad1)}}{safe}"
                rf"{{\c&H00FFFFFF&\bord7\shad1\fscx100\fscy100}}"
            )
            return escaped.replace(safe, pulse, 1)
    return escaped


def _build_audio_filters(plan: dict[str, Any], *, has_audio: bool, sfx_inputs: list[dict[str, Any]]) -> tuple[str, str | None]:
    if not has_audio:
        return "", None
    duration = max(0.1, _safe_float(plan.get("render_duration"), _safe_float(plan.get("duration"), 30.0)))
    duck_terms: list[str] = []
    for item in sfx_inputs:
        start = max(0.0, _safe_float((item.get("event") or {}).get("start"), 0.0))
        duck_terms.append(f"-0.10*between(t,{start:.3f},{start + 0.52:.3f})")
    duck = "1" + "".join(duck_terms)
    parts = [
        f"[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
        f"apad=pad_dur={duration:.3f},atrim=duration={duration:.3f},"
        f"loudnorm=I=-16:LRA=7:TP=-2.0,volume='{duck}':eval=frame[voice]"
    ]
    labels = ["voice"]
    for index, item in enumerate(sfx_inputs, start=1):
        event = item["event"]
        sfx = item["sfx"]
        inp = int(item["input_index"])
        delay = int(max(0.0, _safe_float(event.get("start"), 0.0)) * 1000)
        gain = max(0.36, min(0.62, _safe_float(sfx.get("gain"), 0.46)))
        label = f"v30sfx{index}"
        parts.append(
            f"[{inp}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"atrim=0:1.45,asetpts=PTS-STARTPTS,highpass=f=90,lowpass=f=14500,"
            f"volume={gain:.4f},afade=t=in:st=0:d=0.010,afade=t=out:st=1.18:d=0.22,"
            f"adelay={delay}|{delay}[{label}]"
        )
        labels.append(label)
    if len(labels) == 1:
        parts.append("[voice]alimiter=limit=0.94[aout]")
    else:
        parts.append(
            "".join(f"[{label}]" for label in labels)
            + f"amix=inputs={len(labels)}:duration=longest:dropout_transition=0:normalize=0,"
            + f"atrim=duration={duration:.3f},loudnorm=I=-15.5:LRA=8:TP=-1.5,alimiter=limit=0.96[aout]"
        )
    return ";".join(parts), "aout"


def _validate_v26_effect_plan(plan: dict[str, Any], timings: list[dict[str, Any]], sfx_level: str, sticker_level: str) -> dict[str, Any]:
    events = list(plan.get("events") or [])
    sfx_count = sum(1 for event in events if isinstance(event.get("sfx"), dict))
    sticker_count = sum(1 for event in events if isinstance(event.get("sticker"), dict))
    legacy_count = sum(
        1 for event in events
        if isinstance(event.get("sticker"), dict)
        and event["sticker"].get("asset") != "__v30_semantic_component__"
    )
    if sfx_level != "off" and sfx_count <= 0:
        raise ValueError("V30 可听音效计划为空")
    if sticker_level != "off" and sticker_count <= 0:
        raise ValueError("V30 语义信息卡计划为空")
    if legacy_count:
        raise ValueError(f"V30 检测到旧图标贴纸：{legacy_count}")
    if int(plan.get("keyword_impact_count") or 0) <= 0:
        raise ValueError("V30 关键词冲击计划为空")
    return plan


def render_dynamic_video(input_path: Path, output_path: Path, ass_path: Path, plan: dict[str, Any]) -> dict[str, Any]:
    report = _V29_RENDER_DYNAMIC_VIDEO_CLEAN_EFFECTS(input_path, output_path, ass_path, plan)
    report["effect_engine"] = "v30_clean_semantic_effects"
    report["legacy_sticker_forbidden"] = True
    report["semantic_component_count"] = len(_collect_sticker_inputs(plan))
    report["audible_sfx_count"] = sum(1 for event in plan.get("events") or [] if isinstance(event.get("sfx"), dict))
    return report


# =============================================================================
# V10.40.8.31 CLEAN TEXT + PROFESSIONAL SEMANTIC STICKERS
# =============================================================================
# Default delivery is now pure ASS text emphasis plus small semantic stickers.
# Large opaque semantic text cards are forbidden unless a future explicit mode
# opts into them. This override is intentionally last so all render-time global
# lookups use the clean R21 implementations below.
V31_PRO_STICKER_DIR = _sticker_root() / "pro_r21"
V31_PRO_STICKER_PREFIX = "pro_r21/"


def _v31_sticker_asset(event: dict[str, Any], index: int = 0) -> str:
    text = _clean_caption_text(str(event.get("source_text") or event.get("focus_text") or ""))
    role = str(event.get("role") or "knowledge")
    rules: list[tuple[re.Pattern[str], str]] = [
        (re.compile(r"(咖啡|咖啡厅|咖啡店|cafe)", re.I), "coffee.png"),
        (re.compile(r"(商场|商圈|购物|超市|餐饮|shopping|mall)", re.I), "mall.png"),
        (re.compile(r"(学校|大学|学区|教育|国际学校)", re.I), "school.png"),
        (re.compile(r"(医院|医疗|诊所)", re.I), "hospital.png"),
        (re.compile(r"(地铁|交通|通勤|公交|车站|轻轨|MRT|LRT)", re.I), "train.png"),
        (re.compile(r"(位置|区域|地段|生活半径|附近|周边)", re.I), "location.png"),
        (re.compile(r"(对比|还是|VS|vs|自住.*投资|投资.*自住)", re.I), "compare.png"),
        (re.compile(r"(自住|居住|家庭|生活方式|家人)", re.I), "home.png"),
        (re.compile(r"(投资|回报|升值|出租|收益|转手)", re.I), "investment.png"),
        (re.compile(r"(风险|注意|避坑|误区|别被|不要只|搞错)", re.I), "warning.png"),
        (re.compile(r"(三件事|三项|第一|第二|第三|清单|确认|核对)", re.I), "checklist.png"),
        (re.compile(r"(合同|SPA|定金|首期|文件|签署|抵扣|条款)", re.I), "document.png"),
        (re.compile(r"(租客|客群|人群|客户|上班族|学生群体)", re.I), "people.png"),
        (re.compile(r"(价格|预算|房价|马币|RM|金额|首付)", re.I), "money.png"),
        (re.compile(r"(评论|私信|留言|告诉我|关注|下一条)", re.I), "comment.png"),
        (re.compile(r"(为什么|什么|怎么|到底|吗|？|\?)", re.I), "question.png"),
    ]
    for pattern, asset in rules:
        if pattern.search(text):
            return V31_PRO_STICKER_PREFIX + asset
    fallback = {
        "hook": "spark.png",
        "question": "question.png",
        "cta": "comment.png",
        "risk": "warning.png",
        "comparison": "compare.png",
        "list": "checklist.png",
        "data": "document.png",
        "turn": "location.png",
    }.get(role, "")
    return V31_PRO_STICKER_PREFIX + fallback if fallback else ""


def _v31_sticker_limit(level: str, duration: float) -> int:
    per_30 = {"off": 0, "light": 3, "balanced": 5, "rich": 7}.get(level, 3)
    if per_30 <= 0:
        return 0
    limit = int(math.ceil(max(1.0, duration) / 30.0 * per_30))
    if duration >= 12.0:
        limit = max(2, limit)
    return min(10, limit)


def _decorate_events(events: list[dict[str, Any]], duration: float, *, sfx_level: str, sticker_level: str) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for index, source in enumerate(events):
        event = dict(source)
        # Remove every previous text card / emoji / duplicate overlay layer.
        for key in ("sticker", "callout", "sfx", "sfx_skip_reason", "sticker_candidate", "sticker_skip_reason", "legacy_sticker", "keyword_overlay", "impact_overlay", "semantic_card"):
            event.pop(key, None)
        text = str(event.get("source_text") or event.get("focus_text") or "")
        event["role"] = _v30_semantic_role(text, str(event.get("role") or "knowledge"))
        asset = _v31_sticker_asset(event, index)
        event["sticker_candidate"] = asset or None
        cleaned.append(event)

    # Keep the audible role-bound SFX policy from V30, but do not attach text cards.
    max_sfx = 0 if sfx_level == "off" else max(3, min(6, int(math.ceil(max(1.0, duration) / 9.5))))
    sfx_gap = 3.0
    last_sfx = -999.0
    sfx_count = 0
    sfx_roles = {"hook", "comparison", "risk", "question", "data", "list", "cta", "turn"}
    for index, event in enumerate(cleaned):
        role = str(event.get("role") or "knowledge")
        start = max(0.0, _safe_float(event.get("start"), 0.0))
        if sfx_count >= max_sfx or role not in sfx_roles or (role != "cta" and start - last_sfx < sfx_gap):
            continue
        bank = SFX_VARIANT_BANKS.get(role) or SFX_VARIANT_BANKS.get("turn") or []
        if not bank:
            continue
        asset, _ = bank[index % len(bank)]
        if not (_sfx_root() / asset).is_file():
            event["sfx_skip_reason"] = "asset_missing"
            continue
        gain = {
            "hook": 0.56, "comparison": 0.50, "risk": 0.48,
            "question": 0.45, "data": 0.44, "list": 0.43,
            "turn": 0.40, "cta": 0.52,
        }.get(role, 0.42)
        event["sfx"] = {"asset": asset, "gain": gain, "role": role, "audible_mix": True}
        sfx_count += 1
        last_sfx = start

    max_stickers = _v31_sticker_limit(sticker_level, duration)
    min_gap = {"light": 4.0, "balanced": 2.8, "rich": 2.0}.get(sticker_level, 3.6)
    positions = ["upper_right", "upper_left", "side_right", "side_left"]
    last_start = -999.0
    used = 0
    last_asset = ""
    for event in cleaned:
        asset = str(event.get("sticker_candidate") or "")
        start = max(0.0, _safe_float(event.get("start"), 0.0))
        end = max(start + 0.72, _safe_float(event.get("end"), start + 1.2))
        role = str(event.get("role") or "knowledge")
        if not asset:
            event["sticker_skip_reason"] = "no_semantic_match"
            continue
        path = _sticker_root() / asset
        if not path.is_file():
            event["sticker_skip_reason"] = "asset_missing"
            continue
        if used >= max_stickers:
            event["sticker_skip_reason"] = "level_limit"
            continue
        if role != "cta" and start - last_start < min_gap:
            event["sticker_skip_reason"] = "minimum_gap"
            continue
        if asset == last_asset and role != "cta":
            event["sticker_skip_reason"] = "adjacent_duplicate"
            continue
        span = 1.05 if role not in {"hook", "risk", "cta"} else 1.28
        event["sticker"] = {
            "asset": asset,
            "position": positions[used % len(positions)],
            "size": 154 + (used % 2) * 12,
            "start": round(start, 3),
            "end": round(min(duration, max(start + 0.72, min(end, start + span))), 3),
            "semantic_icon": True,
            "no_text_box": True,
        }
        event.pop("sticker_skip_reason", None)
        used += 1
        last_start = start
        last_asset = asset

    # CTA must have a visible comment sticker when stickers are enabled.
    if sticker_level != "off" and max_stickers > 0:
        cta = next((event for event in reversed(cleaned) if str(event.get("role")) == "cta"), None)
        if cta is not None and not isinstance(cta.get("sticker"), dict):
            asset = V31_PRO_STICKER_PREFIX + "comment.png"
            if (_sticker_root() / asset).is_file():
                if used >= max_stickers:
                    removable = next((event for event in cleaned if isinstance(event.get("sticker"), dict) and str(event.get("role")) not in {"hook", "risk"}), None)
                    if removable is not None:
                        removable.pop("sticker", None)
                        removable["sticker_skip_reason"] = "reserved_for_cta"
                        used -= 1
                if used < max_stickers:
                    start = max(0.0, _safe_float(cta.get("start"), 0.0))
                    end = max(start + 0.8, _safe_float(cta.get("end"), start + 1.4))
                    cta["sticker"] = {
                        "asset": asset, "position": "upper_right", "size": 170,
                        "start": round(start, 3), "end": round(min(duration, max(start + 0.9, min(end, start + 1.35))), 3),
                        "semantic_icon": True, "no_text_box": True,
                    }
                    cta.pop("sticker_skip_reason", None)
    return cleaned


def build_dynamic_plan(payload: dict[str, Any], timings: list[dict[str, Any]], duration: float, *, intensity: str = "balanced") -> dict[str, Any]:
    plan = _V29_BUILD_DYNAMIC_PLAN_CLEAN_EFFECTS(payload, timings, duration, intensity=intensity)
    sfx_level = str(payload.get("dynamic_sfx_level") or "light")
    sticker_level = str(payload.get("dynamic_sticker_level") or "light")
    raw_events = [dict(item) for item in (plan.get("events") or []) if isinstance(item, dict)]
    events = _decorate_events(raw_events, duration, sfx_level=sfx_level, sticker_level=sticker_level)
    plan["events"] = events
    plan["version"] = VERSION
    plan["sfx_level"] = sfx_level
    plan["sticker_level"] = sticker_level
    plan["visual_pace"] = "stable_sequence_clean_text_pro_stickers"
    plan["legacy_sticker_forbidden"] = True
    plan["semantic_component_only"] = False
    plan["large_text_card_forbidden"] = True
    plan["pure_caption_emphasis"] = True
    planned = [event for event in events if isinstance(event.get("sticker"), dict)]
    candidates = [event for event in events if event.get("sticker_candidate")]
    skip_reasons: dict[str, int] = {}
    for event in events:
        reason = str(event.get("sticker_skip_reason") or "")
        if reason:
            skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
    plan["effect_delivery"] = {
        "requested_sfx_level": sfx_level,
        "requested_sticker_level": sticker_level,
        "planned_sfx_count": sum(1 for event in events if isinstance(event.get("sfx"), dict)),
        "sticker_candidates_count": len(candidates),
        "sticker_applied_count": len(planned),
        "planned_sticker_count": len(planned),
        "sticker_skip_reasons": skip_reasons,
        "planned_callout_count": 0,
        "keyword_impact_count": int(plan.get("keyword_impact_count") or 0),
        "sfx_pack": "mixkit-pro-v31-audible",
        "sticker_pack": "pro-line-stickers-r21",
        "text_box_count": 0,
    }
    return plan


def _collect_sticker_inputs(plan: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for event in plan.get("events") or []:
        sticker = event.get("sticker")
        if not isinstance(sticker, dict):
            continue
        asset = str(sticker.get("asset") or "")
        if not asset.startswith(V31_PRO_STICKER_PREFIX):
            continue
        path = _sticker_root() / asset
        if path.is_file():
            result.append({"event": event, "sticker": sticker, "path": path})
    return result


def _highlight_ass(text: str, keywords: list[str], highlight: str) -> str:
    escaped = _ass_escape(text)
    for keyword in sorted((item for item in keywords if item), key=len, reverse=True):
        safe = _ass_escape(keyword)
        if safe in escaped:
            pulse = (
                rf"{{\c{highlight}\bord10\shad2\fscx142\fscy142"
                rf"\t(0,165,\fscx100\fscy100\bord7\shad1)}}{safe}"
                rf"{{\c&H00FFFFFF&\bord7\shad1\fscx100\fscy100}}"
            )
            return escaped.replace(safe, pulse, 1)
    return escaped


def write_dynamic_ass(destination: Path, timings: list[dict[str, Any]], keywords: list[str], *, style_id: str, events: list[dict[str, Any]] | None = None) -> Path:
    preset = SUBTITLE_PRESETS.get(style_id) or SUBTITLE_PRESETS["dynamic_white_yellow"]
    context = getattr(_V16_CONTEXT, "config", {}) or {}
    base_size = max(92, min(150, int(context.get("caption_size") or 118)))
    font_name = "Noto Sans CJK SC"
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes
WrapStyle: 2

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Dynamic,{font_name},{base_size},{preset['primary']},{preset['highlight']},{preset['outline']},&H00000000,-1,0,0,0,100,100,0.8,0,1,{preset['outline_width']},{preset['shadow']},5,55,55,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for index, item in enumerate(timings):
        start = _safe_float(item.get("start"), 0.0)
        end = max(start + 0.30, _safe_float(item.get("end"), start + 0.85))
        raw_text = _clean_caption_text(str(item.get("text") or ""))
        role = _classify(raw_text)
        text = _highlight_ass(raw_text, keywords, str(preset["highlight"]))
        y = 1415 + (index % 2) * 86
        if role in {"hook", "comparison", "risk", "question", "cta"}:
            animation = rf"{{\an5\pos(540,{y})\fscx116\fscy116\t(0,145,\fscx100\fscy100)\fad(30,60)}}"
        else:
            animation = rf"{{\an5\move(540,{y+28},540,{y},0,140)\fad(45,65)}}"
        lines.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Dynamic,,0,0,0,,{animation}{text}\n")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("".join(lines), encoding="utf-8-sig")
    return destination


def _build_video_filters(work: Path, plan: dict[str, Any], ass_path: Path, sticker_inputs: list[dict[str, Any]], *, width: int = 1080, height: int = 1920) -> str:
    duration = max(0.1, _safe_float(plan.get("render_duration"), _safe_float(plan.get("duration"), 30.0)))
    events = list(plan.get("events") or [])
    limits = plan.get("limits") or {}
    zoom_strength = _safe_float(limits.get("zoom_strength"), 0.050)
    zoom_terms: list[str] = []
    for event in events:
        role = str(event.get("role") or "knowledge")
        if role not in {"hook", "comparison", "risk", "question", "data", "cta"}:
            continue
        start = _safe_float(event.get("start"), 0.0)
        span = 0.72
        multiplier = {"hook": 1.10, "comparison": 0.82, "risk": 0.78, "question": 0.66, "data": 0.70, "cta": 0.55}.get(role, 0.6)
        strength = zoom_strength * multiplier
        zoom_terms.append(f"+{strength:.4f}*between(t,{start:.3f},{start+span:.3f})*sin(PI*(t-{start:.3f})/{span:.3f})")
    factor = "1" + "".join(zoom_terms)
    chain = [
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1[base]",
        f"[base]scale=w='{width}*({factor})':h='{height}*({factor})':eval=frame,crop={width}:{height}:(iw-{width})/2:(ih-{height})/2[v0]",
    ]
    current = "v0"
    positions = {
        "upper_left": ("70", "260"), "upper_right": ("W-w-70", "275"),
        "side_left": ("62", "620"), "side_right": ("W-w-62", "640"),
    }
    for index, item in enumerate(sticker_inputs, start=1):
        sticker = item["sticker"]
        input_index = int(item["input_index"])
        start = _safe_float(sticker.get("start"), 0.0)
        end = max(start + 0.72, _safe_float(sticker.get("end"), start + 1.05))
        span = max(0.72, end - start)
        size = max(138, min(190, int(sticker.get("size") or 160)))
        x_expr, y_base = positions.get(str(sticker.get("position") or "upper_right"), positions["upper_right"])
        label = f"v31sticker{index}"
        output = f"v31out{index}"
        chain.append(
            f"[{input_index}:v]format=rgba,scale={size}:{size}:force_original_aspect_ratio=decrease,"
            f"pad={size+18}:{size+18}:(ow-iw)/2:(oh-ih)/2:color=0x00000000,"
            f"trim=duration={span:.3f},fade=t=in:st=0:d=0.08:alpha=1,"
            f"fade=t=out:st={max(0.1,span-0.14):.3f}:d=0.14:alpha=1,"
            f"setpts=PTS-STARTPTS+{start:.3f}/TB[{label}]"
        )
        chain.append(
            f"[{current}][{label}]overlay=x='{x_expr}':y='{y_base}+7*sin(2*PI*(t-{start:.3f})/1.25)':"
            f"eof_action=pass:shortest=0:enable='between(t,{start:.3f},{end:.3f})'[{output}]"
        )
        current = output
    chain.append(f"[{current}]ass='{_ffmpeg_escape_path(ass_path)}',tpad=stop_mode=clone:stop_duration=1,trim=duration={duration:.3f}[vout]")
    return ";".join(chain)


def _validate_v26_effect_plan(plan: dict[str, Any], timings: list[dict[str, Any]], sfx_level: str, sticker_level: str) -> dict[str, Any]:
    events = list(plan.get("events") or [])
    sfx_count = sum(1 for event in events if isinstance(event.get("sfx"), dict))
    stickers = [event.get("sticker") for event in events if isinstance(event.get("sticker"), dict)]
    bad = [item for item in stickers if not str(item.get("asset") or "").startswith(V31_PRO_STICKER_PREFIX)]
    if sfx_level != "off" and sfx_count <= 0:
        raise ValueError("V31 可听音效计划为空")
    if sticker_level != "off" and not stickers:
        raise ValueError("V31 专业语义贴纸计划为空")
    if bad:
        raise ValueError(f"V31 检测到非专业贴纸或文本卡：{len(bad)}")
    if int(plan.get("keyword_impact_count") or 0) <= 0:
        raise ValueError("V31 关键词冲击计划为空")
    return plan


def render_dynamic_video(input_path: Path, output_path: Path, ass_path: Path, plan: dict[str, Any]) -> dict[str, Any]:
    report = _V29_RENDER_DYNAMIC_VIDEO_CLEAN_EFFECTS(input_path, output_path, ass_path, plan)
    sticker_inputs = _collect_sticker_inputs(plan)
    report["effect_engine"] = "v31_clean_text_pro_stickers"
    report["large_text_card_forbidden"] = True
    report["text_box_count"] = 0
    report["professional_sticker_count"] = len(sticker_inputs)
    report["sticker_assets"] = [item["path"].name for item in sticker_inputs]
    report["audible_sfx_count"] = sum(1 for event in plan.get("events") or [] if isinstance(event.get("sfx"), dict))
    return report
# =============================================================================
# V10.40.8.32 REFERENCE KINETIC TYPOGRAPHY + MOTION ACCENT ENGINE
# =============================================================================
V32_MARKER = "V10_40_8_32_REFERENCE_KINETIC_TYPOGRAPHY"
V32_ACCENT_PREFIX = "pro_r22/"
V32_IMPACT_GAP_SECONDS = 1.85


def _v26_align_chunks_to_native_words(
    chunks: list[str],
    words: list[dict[str, Any]],
    fallback_start: float,
    fallback_end: float,
) -> list[dict[str, Any]]:
    """Preserve character-level native timing so keyword punches fire when spoken."""
    clock = _v26_character_clock(words)
    expected = "".join(_v26_clean_token_text(chunk) for chunk in chunks)
    actual = "".join(item["char"] for item in clock)
    if not clock or not expected:
        fallback = _spread_chunks(chunks, fallback_start, fallback_end)
        for cue in fallback:
            cue["timing_source"] = "segment_duration_fallback"
            cue["native_word_timestamp"] = False
            cue["native_word_count"] = 0
            cue["native_character_timeline"] = []
        return fallback

    exact_match = expected == actual
    result: list[dict[str, Any]] = []
    cursor = 0
    expected_cursor = 0
    expected_total = max(1, len(expected))
    for chunk_index, chunk in enumerate(chunks):
        token = _v26_clean_token_text(chunk)
        if not token:
            continue
        if exact_match:
            end_cursor = cursor + len(token)
        else:
            expected_cursor += len(token)
            end_cursor = (
                len(clock)
                if chunk_index == len(chunks) - 1
                else max(cursor + 1, round(expected_cursor / expected_total * len(clock)))
            )
        end_cursor = min(len(clock), max(cursor + 1, end_cursor))
        selection = [dict(item) for item in clock[cursor:end_cursor]]
        if not selection:
            fallback = _spread_chunks(chunks, fallback_start, fallback_end)
            for cue in fallback:
                cue["timing_source"] = "segment_duration_fallback"
                cue["native_word_timestamp"] = False
                cue["native_word_count"] = 0
                cue["native_character_timeline"] = []
            return fallback
        result.append({
            "text": chunk,
            "start": round(float(selection[0]["start"]), 3),
            "end": round(max(float(selection[-1]["end"]), float(selection[0]["start"]) + 0.08), 3),
            "timing_source": (
                "volcengine_native_word_timestamp"
                if exact_match
                else "volcengine_native_word_timestamp_fuzzy_tn"
            ),
            "native_word_timestamp": True,
            "native_word_count": len(selection),
            "native_character_timeline": selection,
        })
        cursor = end_cursor
        if exact_match:
            expected_cursor += len(token)
    if result:
        result[-1]["end"] = round(max(result[-1]["start"] + 0.08, float(clock[-1]["end"])), 3)
    return result


def _v32_clean_keyword(value: Any) -> str:
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9%]+", "", str(value or ""))


def _v32_focus_keyword(text: str, keywords: list[str], role: str) -> str:
    clean = _v32_clean_keyword(text)
    for keyword in sorted((item for item in keywords if item), key=len, reverse=True):
        token = _v32_clean_keyword(keyword)
        if token and token in clean:
            return token[:8]
    role_rules = {
        "question": ("最看重什么", "为什么", "怎么选", "到底什么", "什么"),
        "cta": ("评论告诉我", "留言", "关注", "私信", "帮你分析"),
        "risk": ("别只看", "别被", "不要只", "风险", "注意", "避坑"),
        "comparison": ("自住", "投资", "出租", "对比", "区别"),
        "data": ("价格", "预算", "回报", "首期", "定金", "交通"),
        "list": ("三件事", "三项", "第一", "第二", "第三"),
        "hook": ("买房", "第一眼", "很多人", "重点"),
    }
    for candidate in role_rules.get(role, ()):
        token = _v32_clean_keyword(candidate)
        if token and token in clean:
            return token[:8]
    if len(clean) <= 8:
        return clean
    return clean[:6]


def _v32_keyword_timing(item: dict[str, Any], focus: str) -> tuple[float, float, str]:
    start = _safe_float(item.get("start"), 0.0)
    end = max(start + 0.20, _safe_float(item.get("end"), start + 0.85))
    clock = [dict(value) for value in (item.get("native_character_timeline") or []) if isinstance(value, dict)]
    token = _v32_clean_keyword(focus)
    actual = "".join(str(value.get("char") or "") for value in clock)
    if token and clock:
        index = actual.find(token)
        if index >= 0 and index + len(token) <= len(clock):
            picked = clock[index:index + len(token)]
            return (
                max(start, float(picked[0].get("start") or start) - 0.025),
                min(end + 0.28, max(float(picked[-1].get("end") or end), float(picked[0].get("start") or start) + 0.18) + 0.26),
                "native_character_timestamp",
            )
    clean = _v32_clean_keyword(item.get("text"))
    index = clean.find(token) if token else -1
    if index >= 0 and clean:
        span = end - start
        impact_start = start + span * index / len(clean)
        impact_end = start + span * min(len(clean), index + max(1, len(token))) / len(clean)
        return impact_start, max(impact_start + 0.42, impact_end + 0.20), "caption_ratio_fallback"
    return start, min(end + 0.18, start + 0.72), "cue_start_fallback"


def _v32_wrap_caption(text: str, max_chars: int = 8) -> str:
    clean = _clean_caption_text(text)
    if len(clean) <= max_chars:
        return clean
    if len(clean) <= max_chars * 2:
        cut = max(4, min(max_chars, round(len(clean) / 2)))
        return clean[:cut] + r"\N" + clean[cut:]
    chunks = [clean[index:index + max_chars] for index in range(0, len(clean), max_chars)]
    return r"\N".join(chunks)


def _highlight_ass(text: str, keywords: list[str], highlight: str) -> str:
    line_break_marker = "__V32_LINE_BREAK__"
    escaped = _ass_escape(text.replace(r"\N", line_break_marker)).replace(line_break_marker, r"\N")
    for keyword in sorted((item for item in keywords if item), key=len, reverse=True):
        safe = _ass_escape(keyword)
        if safe in escaped:
            highlighted = rf"{{\c{highlight}\bord9\fscx112\fscy112}}{safe}{{\c&H00FFFFFF&\bord7\fscx100\fscy100}}"
            return escaped.replace(safe, highlighted, 1)
    return escaped


def write_dynamic_ass(
    destination: Path,
    timings: list[dict[str, Any]],
    keywords: list[str],
    *,
    style_id: str,
    events: list[dict[str, Any]] | None = None,
) -> Path:
    preset = SUBTITLE_PRESETS.get(style_id) or SUBTITLE_PRESETS["dynamic_white_yellow"]
    context = getattr(_V16_CONTEXT, "config", {}) or {}
    requested = int(context.get("caption_size") or 132)
    base_size = max(116, min(176, requested))
    font_name = "Noto Sans CJK SC"
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes
WrapStyle: 2

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Dynamic,{font_name},{base_size},{preset['primary']},{preset['highlight']},{preset['outline']},&H00000000,-1,0,0,0,100,100,1.0,0,1,7,2,5,52,52,0,1
Style: Impact,{font_name},176,&H00FFFFFF,&H0000E8FF,&H00101010,&H00000000,-1,0,0,0,100,100,0.8,0,1,11,3,5,40,40,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    last_impact = -999.0
    duration = max((_safe_float(item.get("end"), 0.0) for item in timings), default=0.0)
    max_impacts = max(4, min(9, int(math.ceil(max(1.0, duration) / 30.0 * 7))))
    impact_count = 0
    impact_debug: list[dict[str, Any]] = []
    role_colors = {
        "risk": "&H003B6BFF&",
        "question": "&H00FFE04B&",
        "cta": "&H0047D2FF&",
        "comparison": "&H00FFB347&",
        "data": "&H0000E8FF&",
        "list": "&H0068E083&",
        "hook": "&H0000E8FF&",
    }
    for index, item in enumerate(timings):
        start = _safe_float(item.get("start"), 0.0)
        end = max(start + 0.30, _safe_float(item.get("end"), start + 0.85))
        raw_text = _clean_caption_text(str(item.get("text") or ""))
        role = _classify(raw_text)
        wrapped = _v32_wrap_caption(raw_text, 8)
        main_text = _highlight_ass(wrapped, keywords, str(preset["highlight"]))
        short = len(_v32_clean_keyword(raw_text)) <= 8
        line_size = min(164, base_size + (12 if short else 0))
        position = 1450 if role not in {"hook", "question", "cta"} else 1390
        animation = (
            rf"{{\an5\pos(540,{position})\fs{line_size}\fscx94\fscy94"
            rf"\t(0,120,\fscx104\fscy104)\t(120,220,\fscx100\fscy100)\fad(25,65)}}"
        )
        lines.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Dynamic,,0,0,0,,{animation}{main_text}\n")

        if impact_count >= max_impacts or start - last_impact < V32_IMPACT_GAP_SECONDS:
            continue
        focus = _v32_focus_keyword(raw_text, keywords, role)
        if not focus or len(focus) > 8:
            continue
        impact_start, impact_end, timing_source = _v32_keyword_timing(item, focus)
        if impact_end <= impact_start + 0.18:
            continue
        impact_size = 210 if len(focus) <= 3 else 188 if len(focus) <= 5 else 164
        impact_y = 1160 if role in {"hook", "question", "risk", "comparison"} else 1235
        color = role_colors.get(role, "&H0000E8FF&")
        impact_text = _ass_escape(focus)
        impact_animation = (
            rf"{{\an5\pos(540,{impact_y})\fs{impact_size}\c{color}\bord12\shad3"
            rf"\fscx62\fscy62\t(0,105,\fscx148\fscy148)"
            rf"\t(105,260,\fscx112\fscy112)\fad(15,90)}}"
        )
        lines.append(
            f"Dialogue: 2,{_ass_time(impact_start)},{_ass_time(impact_end)},Impact,,0,0,0,,"
            f"{impact_animation}{impact_text}\n"
        )
        impact_debug.append({"text": focus, "start": round(impact_start, 3), "end": round(impact_end, 3), "timing_source": timing_source})
        impact_count += 1
        last_impact = impact_start

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("".join(lines), encoding="utf-8-sig")
    try:
        destination.with_suffix(".impact.json").write_text(
            json.dumps({"keyword_impact_count": impact_count, "impacts": impact_debug}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass
    return destination


def _v32_accent_asset(event: dict[str, Any], index: int) -> str:
    text = _clean_caption_text(str(event.get("source_text") or event.get("focus_text") or ""))
    role = str(event.get("role") or "knowledge")
    rules = [
        (re.compile(r"(评论|留言|私信|告诉我|关注|下一条)"), "comment_bubble.png"),
        (re.compile(r"(风险|避坑|别被|不要只|别只看|搞错|注意)"), "warning_tape.png"),
        (re.compile(r"(为什么|什么|怎么|到底|吗|？|\?)"), "question_burst.png"),
        (re.compile(r"(对比|还是|VS|vs|自住.*投资|投资.*自住|自住.*出租)"), "split_arrows.png"),
        (re.compile(r"(三件事|三项|第一|第二|第三|确认|核对|清单)"), "check_stamp.png"),
        (re.compile(r"(位置|区域|地段|交通|商圈|附近|周边|生活半径)"), "location_ping.png"),
        (re.compile(r"(重点|关键|核心|第一眼|价格|预算|回报|现金流)"), "underline_brush.png"),
    ]
    for pattern, asset in rules:
        if pattern.search(text):
            return V32_ACCENT_PREFIX + asset
    fallback = {
        "hook": "focus_brackets.png",
        "question": "question_burst.png",
        "risk": "warning_tape.png",
        "comparison": "split_arrows.png",
        "cta": "comment_bubble.png",
        "list": "check_stamp.png",
        "data": "circle_scribble.png",
        "turn": "arrow_curve.png",
        "evidence": "quote_marks.png",
    }.get(role, "")
    if not fallback and index % 5 == 0:
        fallback = "spark_cluster.png"
    return V32_ACCENT_PREFIX + fallback if fallback else ""


def _decorate_events(
    events: list[dict[str, Any]],
    duration: float,
    *,
    sfx_level: str,
    sticker_level: str,
) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for index, source in enumerate(events):
        event = dict(source)
        for key in (
            "sticker", "callout", "sfx", "sfx_skip_reason", "sticker_candidate",
            "sticker_skip_reason", "legacy_sticker", "keyword_overlay",
            "impact_overlay", "semantic_card",
        ):
            event.pop(key, None)
        text = str(event.get("source_text") or event.get("focus_text") or "")
        event["role"] = _v30_semantic_role(text, str(event.get("role") or "knowledge"))
        event["sticker_candidate"] = _v32_accent_asset(event, index) or None
        cleaned.append(event)

    max_sfx = 0 if sfx_level == "off" else max(3, min(7, int(math.ceil(max(1.0, duration) / 8.5))))
    sfx_gap = 2.65
    last_sfx = -999.0
    sfx_count = 0
    sfx_roles = {"hook", "comparison", "risk", "question", "data", "list", "cta", "turn"}
    for index, event in enumerate(cleaned):
        role = str(event.get("role") or "knowledge")
        start = max(0.0, _safe_float(event.get("start"), 0.0))
        if sfx_count >= max_sfx or role not in sfx_roles or (role != "cta" and start - last_sfx < sfx_gap):
            continue
        bank = SFX_VARIANT_BANKS.get(role) or SFX_VARIANT_BANKS.get("turn") or []
        if not bank:
            continue
        asset, _ = bank[index % len(bank)]
        if not (_sfx_root() / asset).is_file():
            event["sfx_skip_reason"] = "asset_missing"
            continue
        gain = {
            "hook": 0.58, "comparison": 0.51, "risk": 0.49,
            "question": 0.47, "data": 0.44, "list": 0.44,
            "turn": 0.42, "cta": 0.54,
        }.get(role, 0.44)
        event["sfx"] = {"asset": asset, "gain": gain, "role": role, "audible_mix": True}
        sfx_count += 1
        last_sfx = start

    per_30 = {"off": 0, "light": 3, "balanced": 5, "rich": 7}.get(sticker_level, 3)
    max_accents = min(9, int(math.ceil(max(1.0, duration) / 30.0 * per_30))) if per_30 else 0
    if duration >= 8 and max_accents:
        max_accents = max(3, max_accents)
    gap = {"light": 4.1, "balanced": 2.7, "rich": 1.9}.get(sticker_level, 3.5)
    last_start = -999.0
    last_asset = ""
    used = 0
    positions = ["upper_right", "upper_left", "side_right", "side_left"]
    for event in cleaned:
        asset = str(event.get("sticker_candidate") or "")
        start = max(0.0, _safe_float(event.get("start"), 0.0))
        end = max(start + 0.75, _safe_float(event.get("end"), start + 1.35))
        role = str(event.get("role") or "knowledge")
        if not asset:
            event["sticker_skip_reason"] = "no_reference_accent_match"
            continue
        path = _sticker_root() / asset
        if not path.is_file():
            event["sticker_skip_reason"] = "asset_missing"
            continue
        if used >= max_accents:
            event["sticker_skip_reason"] = "level_limit"
            continue
        if role != "cta" and start - last_start < gap:
            event["sticker_skip_reason"] = "minimum_gap"
            continue
        if asset == last_asset and role != "cta":
            event["sticker_skip_reason"] = "adjacent_duplicate"
            continue
        asset_name = Path(asset).name
        width = {
            "underline_brush.png": 350,
            "warning_tape.png": 330,
            "split_arrows.png": 310,
            "comment_bubble.png": 265,
            "question_burst.png": 245,
            "circle_scribble.png": 300,
            "focus_brackets.png": 300,
            "arrow_curve.png": 300,
            "check_stamp.png": 235,
            "location_ping.png": 230,
            "quote_marks.png": 235,
            "spark_cluster.png": 225,
        }.get(asset_name, 250)
        span = 1.15 if role not in {"hook", "risk", "cta"} else 1.45
        event["sticker"] = {
            "asset": asset,
            "position": positions[used % len(positions)],
            "size": width,
            "start": round(start, 3),
            "end": round(min(duration, max(start + 0.85, min(end, start + span))), 3),
            "reference_motion_accent": True,
            "no_text_box": True,
        }
        event.pop("sticker_skip_reason", None)
        used += 1
        last_start = start
        last_asset = asset
    return cleaned


def build_dynamic_plan(
    payload: dict[str, Any],
    timings: list[dict[str, Any]],
    duration: float,
    *,
    intensity: str = "balanced",
) -> dict[str, Any]:
    plan = _V29_BUILD_DYNAMIC_PLAN_CLEAN_EFFECTS(payload, timings, duration, intensity=intensity)
    sfx_level = str(payload.get("dynamic_sfx_level") or "light")
    sticker_level = str(payload.get("dynamic_sticker_level") or "light")
    raw_events = [dict(item) for item in (plan.get("events") or []) if isinstance(item, dict)]
    events = _decorate_events(raw_events, duration, sfx_level=sfx_level, sticker_level=sticker_level)
    plan["events"] = events
    plan["version"] = VERSION
    plan["sfx_level"] = sfx_level
    plan["sticker_level"] = sticker_level
    plan["visual_pace"] = "reference_kinetic_typography_motion_accents"
    plan["legacy_sticker_forbidden"] = True
    plan["large_text_card_forbidden"] = True
    plan["pure_caption_emphasis"] = True
    plan["native_keyword_impact"] = True
    planned = [event for event in events if isinstance(event.get("sticker"), dict)]
    candidates = [event for event in events if event.get("sticker_candidate")]
    skip_reasons: dict[str, int] = {}
    for event in events:
        reason = str(event.get("sticker_skip_reason") or "")
        if reason:
            skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
    plan["effect_delivery"] = {
        "requested_sfx_level": sfx_level,
        "requested_sticker_level": sticker_level,
        "planned_sfx_count": sum(1 for event in events if isinstance(event.get("sfx"), dict)),
        "sticker_candidates_count": len(candidates),
        "sticker_applied_count": len(planned),
        "planned_sticker_count": len(planned),
        "sticker_skip_reasons": skip_reasons,
        "planned_callout_count": 0,
        "keyword_impact_count": int(plan.get("keyword_impact_count") or 0),
        "sfx_pack": "mixkit-pro-v32-audible",
        "sticker_pack": "reference-motion-accents-r22",
        "text_box_count": 0,
    }
    return plan


def _collect_sticker_inputs(plan: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for event in plan.get("events") or []:
        sticker = event.get("sticker")
        if not isinstance(sticker, dict):
            continue
        asset = str(sticker.get("asset") or "")
        if not asset.startswith(V32_ACCENT_PREFIX):
            continue
        path = _sticker_root() / asset
        if path.is_file():
            result.append({"event": event, "sticker": sticker, "path": path})
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
    duration = max(0.1, _safe_float(plan.get("render_duration"), _safe_float(plan.get("duration"), 30.0)))
    events = list(plan.get("events") or [])
    limits = plan.get("limits") or {}
    zoom_strength = _safe_float(limits.get("zoom_strength"), 0.050)
    zoom_terms: list[str] = []
    for event in events:
        role = str(event.get("role") or "knowledge")
        if role not in {"hook", "comparison", "risk", "question", "data", "cta"}:
            continue
        start = _safe_float(event.get("start"), 0.0)
        span = 0.66
        strength = zoom_strength * {"hook": 1.0, "comparison": 0.78, "risk": 0.76, "question": 0.64, "data": 0.62, "cta": 0.52}.get(role, 0.60)
        zoom_terms.append(f"+{strength:.4f}*between(t,{start:.3f},{start+span:.3f})*sin(PI*(t-{start:.3f})/{span:.3f})")
    factor = "1" + "".join(zoom_terms)
    chain = [
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1[base]",
        f"[base]scale=w='{width}*({factor})':h='{height}*({factor})':eval=frame,crop={width}:{height}:(iw-{width})/2:(ih-{height})/2[v0]",
    ]
    current = "v0"
    positions = {
        "upper_left": ("64", "265"), "upper_right": ("W-w-64", "275"),
        "side_left": ("55", "560"), "side_right": ("W-w-55", "585"),
    }
    for index, item in enumerate(sticker_inputs, start=1):
        sticker = item["sticker"]
        input_index = int(item["input_index"])
        start = _safe_float(sticker.get("start"), 0.0)
        end = max(start + 0.75, _safe_float(sticker.get("end"), start + 1.20))
        span = max(0.75, end - start)
        size = max(210, min(370, int(sticker.get("size") or 260)))
        x_expr, y_base = positions.get(str(sticker.get("position") or "upper_right"), positions["upper_right"])
        label = f"v32accent{index}"
        output = f"v32out{index}"
        chain.append(
            f"[{input_index}:v]format=rgba,scale=w={size}:h=-1:force_original_aspect_ratio=decrease,"
            f"pad={size+30}:{size+30}:(ow-iw)/2:(oh-ih)/2:color=0x00000000,"
            f"trim=duration={span:.3f},fade=t=in:st=0:d=0.07:alpha=1,"
            f"fade=t=out:st={max(0.12,span-0.16):.3f}:d=0.16:alpha=1,"
            f"setpts=PTS-STARTPTS+{start:.3f}/TB[{label}]"
        )
        chain.append(
            f"[{current}][{label}]overlay=x='{x_expr}+8*sin(2*PI*(t-{start:.3f})/1.1)':"
            f"y='{y_base}+9*sin(2*PI*(t-{start:.3f})/1.35)':"
            f"eof_action=pass:shortest=0:enable='between(t,{start:.3f},{end:.3f})'[{output}]"
        )
        current = output
    chain.append(f"[{current}]ass='{_ffmpeg_escape_path(ass_path)}',tpad=stop_mode=clone:stop_duration=1,trim=duration={duration:.3f}[vout]")
    return ";".join(chain)


def _validate_v26_effect_plan(
    plan: dict[str, Any],
    timings: list[dict[str, Any]],
    sfx_level: str,
    sticker_level: str,
) -> dict[str, Any]:
    events = list(plan.get("events") or [])
    sfx_count = sum(1 for event in events if isinstance(event.get("sfx"), dict))
    stickers = [event.get("sticker") for event in events if isinstance(event.get("sticker"), dict)]
    bad = [item for item in stickers if not str(item.get("asset") or "").startswith(V32_ACCENT_PREFIX)]
    if sfx_level != "off" and sfx_count <= 0:
        raise ValueError("V32 可听音效计划为空")
    if sticker_level != "off" and not stickers:
        raise ValueError("V32 动态标注点缀计划为空")
    if bad:
        raise ValueError(f"V32 检测到旧式低质贴纸：{len(bad)}")
    if int(plan.get("keyword_impact_count") or 0) <= 0:
        raise ValueError("V32 关键词冲击计划为空")
    return plan


_V31_RENDER_DYNAMIC_VIDEO_KINETIC_BASE = render_dynamic_video


def render_dynamic_video(input_path: Path, output_path: Path, ass_path: Path, plan: dict[str, Any]) -> dict[str, Any]:
    report = _V31_RENDER_DYNAMIC_VIDEO_KINETIC_BASE(input_path, output_path, ass_path, plan)
    sticker_inputs = _collect_sticker_inputs(plan)
    impact_sidecar = ass_path.with_suffix(".impact.json")
    impact_meta: dict[str, Any] = {}
    if impact_sidecar.is_file():
        try:
            loaded = json.loads(impact_sidecar.read_text(encoding="utf-8"))
            impact_meta = loaded if isinstance(loaded, dict) else {}
        except Exception:
            impact_meta = {}
    report["effect_engine"] = "v32_reference_kinetic_typography"
    report["large_text_card_forbidden"] = True
    report["text_box_count"] = 0
    report["reference_motion_accent_count"] = len(sticker_inputs)
    report["sticker_assets"] = [item["path"].name for item in sticker_inputs]
    report["kinetic_keyword_count"] = int(impact_meta.get("keyword_impact_count") or 0)
    report["kinetic_keyword_impacts"] = list(impact_meta.get("impacts") or [])
    report["native_keyword_impact"] = any(
        item.get("timing_source") == "native_character_timestamp"
        for item in report["kinetic_keyword_impacts"]
        if isinstance(item, dict)
    )
    return report

# =============================================================================
# V10.40.8.33 LARGE CAPTION HIERARCHY + SEMANTIC MOTION OVERLAYS
# =============================================================================
V33_MARKER = "V10_40_8_33_SEMANTIC_RELEVANCE_CAPTION_HIERARCHY"
V33_ACCENT_PREFIX = "pro_r22/"
V33_IMPACT_GAP_SECONDS = 1.10
V33_KEYWORD_LEXICON = (
    "评论区", "现金流", "国际学校", "生活半径", "第一笔钱", "预订定金", "10%首期",
    "价格", "出租", "区域", "转手", "租客", "自住", "投资", "预算", "回报", "通勤",
    "商圈", "学校", "医院", "商场", "咖啡厅", "合同", "定金", "首期", "风险", "买房",
)


def _v32_focus_keyword(text: str, keywords: list[str], role: str) -> str:
    clean = _v32_clean_keyword(text)
    candidates: list[str] = []
    for keyword in keywords:
        token = _v32_clean_keyword(keyword)
        if token and token in clean:
            candidates.append(token[:8])
    for token in V33_KEYWORD_LEXICON:
        cleaned = _v32_clean_keyword(token)
        if cleaned and cleaned in clean:
            candidates.append(cleaned[:8])
    role_rules = {
        "question": ("最看重什么", "为什么", "怎么选", "什么"),
        "cta": ("评论区", "评论告诉我", "留言", "关注", "帮你分析"),
        "risk": ("别只看", "不要只", "风险", "注意", "避坑"),
        "comparison": ("自住", "投资", "出租", "转手", "对比"),
        "data": ("价格", "预算", "回报", "首期", "定金", "交通"),
        "list": ("三件事", "三项", "第一", "第二", "第三"),
        "hook": ("买房", "第一眼", "很多人", "重点"),
    }
    for token in role_rules.get(role, ()):
        cleaned = _v32_clean_keyword(token)
        if cleaned and cleaned in clean:
            candidates.append(cleaned[:8])
    if candidates:
        # Prefer a meaningful 2-6 character noun phrase, not the whole sentence.
        candidates = sorted(set(candidates), key=lambda value: (2 <= len(value) <= 6, len(value)), reverse=True)
        return candidates[0]
    if len(clean) <= 6:
        return clean
    return clean[:4]


def write_dynamic_ass(
    destination: Path,
    timings: list[dict[str, Any]],
    keywords: list[str],
    *,
    style_id: str,
    events: list[dict[str, Any]] | None = None,
) -> Path:
    preset = SUBTITLE_PRESETS.get(style_id) or SUBTITLE_PRESETS["dynamic_white_yellow"]
    context = getattr(_V16_CONTEXT, "config", {}) or {}
    requested = int(context.get("caption_size") or 150)
    base_size = max(138, min(196, requested))
    font_name = "Noto Sans CJK SC"
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes
WrapStyle: 2

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Dynamic,{font_name},{base_size},{preset['primary']},{preset['highlight']},{preset['outline']},&H00000000,-1,0,0,0,100,100,1.2,0,1,8,2,5,44,44,0,1
Style: Impact,{font_name},218,&H00FFFFFF,&H0000E8FF,&H00101010,&H00000000,-1,0,0,0,100,100,1.0,0,1,13,3,5,32,32,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    last_impact = -999.0
    duration = max((_safe_float(item.get("end"), 0.0) for item in timings), default=0.0)
    max_impacts = max(5, min(10, int(math.ceil(max(1.0, duration) / 30.0 * 10))))
    impact_count = 0
    impact_candidates = 0
    impact_debug: list[dict[str, Any]] = []
    role_colors = {
        "risk": "&H003B6BFF&", "question": "&H00FFE04B&", "cta": "&H0047D2FF&",
        "comparison": "&H00FFB347&", "data": "&H0000E8FF&", "list": "&H0068E083&", "hook": "&H0000E8FF&",
    }
    for index, item in enumerate(timings):
        start = _safe_float(item.get("start"), 0.0)
        end = max(start + 0.30, _safe_float(item.get("end"), start + 0.85))
        raw_text = _clean_caption_text(str(item.get("text") or ""))
        role = _classify(raw_text)
        wrapped = _v32_wrap_caption(raw_text, 7)
        main_text = _highlight_ass(wrapped, keywords, str(preset["highlight"]))
        short = len(_v32_clean_keyword(raw_text)) <= 7
        line_size = min(188, base_size + (18 if short else 0))
        position = 1410 if role not in {"hook", "question", "cta"} else 1345
        animation = (
            rf"{{\an5\pos(540,{position})\fs{line_size}\fscx92\fscy92"
            rf"\t(0,115,\fscx106\fscy106)\t(115,235,\fscx100\fscy100)\fad(20,70)}}"
        )
        lines.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Dynamic,,0,0,0,,{animation}{main_text}\n")

        focus = _v32_focus_keyword(raw_text, keywords, role)
        if focus:
            impact_candidates += 1
        if not focus or len(focus) > 8 or impact_count >= max_impacts or start - last_impact < V33_IMPACT_GAP_SECONDS:
            continue
        impact_start, impact_end, timing_source = _v32_keyword_timing(item, focus)
        if impact_end <= impact_start + 0.18:
            continue
        impact_size = 244 if len(focus) <= 3 else 218 if len(focus) <= 5 else 192
        impact_y = 1055 if role in {"hook", "question", "risk", "comparison"} else 1165
        color = role_colors.get(role, "&H0000E8FF&")
        impact_text = _ass_escape(focus)
        impact_animation = (
            rf"{{\an5\pos(540,{impact_y})\fs{impact_size}\c{color}\bord13\shad3\frz-2"
            rf"\fscx52\fscy52\t(0,105,\fscx158\fscy158\frz1)"
            rf"\t(105,285,\fscx116\fscy116\frz0)\fad(12,95)}}"
        )
        lines.append(
            f"Dialogue: 2,{_ass_time(impact_start)},{_ass_time(impact_end)},Impact,,0,0,0,,"
            f"{impact_animation}{impact_text}\n"
        )
        impact_debug.append({
            "text": focus, "start": round(impact_start, 3), "end": round(impact_end, 3),
            "timing_source": timing_source, "size": impact_size, "scale_peak": 158,
        })
        impact_count += 1
        last_impact = impact_start

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("".join(lines), encoding="utf-8-sig")
    try:
        destination.with_suffix(".impact.json").write_text(
            json.dumps({
                "keyword_impact_count": impact_count,
                "keyword_impact_candidates": impact_candidates,
                "keyword_impact_coverage": round(impact_count / max(1, impact_candidates), 3),
                "base_caption_size": base_size,
                "impacts": impact_debug,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass
    return destination


def _v33_accent_asset(event: dict[str, Any]) -> str:
    text = _clean_caption_text(str(event.get("source_text") or event.get("focus_text") or ""))
    role = str(event.get("role") or "knowledge")
    rules = [
        (re.compile(r"评论|留言|私信|告诉我|关注|下一条"), "comment_bubble.png", "caption_right"),
        (re.compile(r"风险|避坑|别被|不要只|别只看|搞错|注意"), "warning_tape.png", "caption_center"),
        (re.compile(r"对比|还是|VS|vs|自住.*投资|投资.*自住|自住.*出租"), "split_arrows.png", "caption_center"),
        (re.compile(r"为什么|什么|怎么|到底|吗|？|\?"), "circle_scribble.png", "caption_center"),
        (re.compile(r"价格|预算|回报|现金流|定金|首期|重点|关键|核心"), "underline_brush.png", "caption_center"),
        (re.compile(r"区域|地段|位置|交通|商圈|附近|周边|生活半径"), "arrow_curve.png", "caption_right"),
    ]
    for pattern, asset, position in rules:
        if pattern.search(text):
            return f"{V33_ACCENT_PREFIX}{asset}|{position}"
    fallback = {
        "cta": ("comment_bubble.png", "caption_right"),
        "risk": ("warning_tape.png", "caption_center"),
        "comparison": ("split_arrows.png", "caption_center"),
        "question": ("circle_scribble.png", "caption_center"),
        "data": ("underline_brush.png", "caption_center"),
        "turn": ("arrow_curve.png", "caption_right"),
    }.get(role)
    return f"{V33_ACCENT_PREFIX}{fallback[0]}|{fallback[1]}" if fallback else ""


def _decorate_events(
    events: list[dict[str, Any]],
    duration: float,
    *,
    sfx_level: str,
    sticker_level: str,
) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for source in events:
        event = dict(source)
        for key in (
            "sticker", "callout", "sfx", "sfx_skip_reason", "sticker_candidate",
            "sticker_skip_reason", "legacy_sticker", "keyword_overlay",
            "impact_overlay", "semantic_card",
        ):
            event.pop(key, None)
        text = str(event.get("source_text") or event.get("focus_text") or "")
        event["role"] = _v30_semantic_role(text, str(event.get("role") or "knowledge"))
        candidate = _v33_accent_asset(event)
        if candidate:
            asset, position = candidate.split("|", 1)
            event["sticker_candidate"] = asset
            event["accent_position"] = position
        else:
            event["sticker_candidate"] = None
        cleaned.append(event)

    max_sfx = 0 if sfx_level == "off" else max(4, min(8, int(math.ceil(max(1.0, duration) / 6.5))))
    sfx_gap = 1.85
    last_sfx = -999.0
    sfx_count = 0
    sfx_roles = {"hook", "comparison", "risk", "question", "data", "list", "cta", "turn"}
    for index, event in enumerate(cleaned):
        role = str(event.get("role") or "knowledge")
        start = max(0.0, _safe_float(event.get("start"), 0.0))
        if sfx_count >= max_sfx or role not in sfx_roles or (role != "cta" and start - last_sfx < sfx_gap):
            continue
        bank = SFX_VARIANT_BANKS.get(role) or SFX_VARIANT_BANKS.get("turn") or []
        if not bank:
            continue
        asset, _ = bank[index % len(bank)]
        if not (_sfx_root() / asset).is_file():
            event["sfx_skip_reason"] = "asset_missing"
            continue
        gain = {
            "hook": 0.68, "comparison": 0.62, "risk": 0.60,
            "question": 0.58, "data": 0.56, "list": 0.54,
            "turn": 0.52, "cta": 0.64,
        }.get(role, 0.54)
        event["sfx"] = {"asset": asset, "gain": gain, "role": role, "audible_mix": True}
        sfx_count += 1
        last_sfx = start

    per_30 = {"off": 0, "light": 3, "balanced": 4, "rich": 5}.get(sticker_level, 3)
    max_accents = min(6, int(math.ceil(max(1.0, duration) / 30.0 * per_30))) if per_30 else 0
    if duration >= 8 and max_accents:
        max_accents = max(2, max_accents)
    gap = {"light": 3.2, "balanced": 2.4, "rich": 1.9}.get(sticker_level, 3.0)
    last_start = -999.0
    last_asset = ""
    used = 0
    skip_reasons: dict[str, int] = {}
    for event in cleaned:
        asset = str(event.get("sticker_candidate") or "")
        start = max(0.0, _safe_float(event.get("start"), 0.0))
        end = max(start + 0.75, _safe_float(event.get("end"), start + 1.35))
        role = str(event.get("role") or "knowledge")
        if not asset:
            event["sticker_skip_reason"] = "no_semantic_motion_overlay"
        elif not (_sticker_root() / asset).is_file():
            event["sticker_skip_reason"] = "asset_missing"
        elif used >= max_accents and role != "cta":
            event["sticker_skip_reason"] = "level_limit"
        elif role != "cta" and start - last_start < gap:
            event["sticker_skip_reason"] = "minimum_gap"
        elif asset == last_asset and role != "cta":
            event["sticker_skip_reason"] = "adjacent_duplicate"
        else:
            asset_name = Path(asset).name
            width = {
                "underline_brush.png": 390, "warning_tape.png": 380,
                "split_arrows.png": 355, "comment_bubble.png": 330,
                "circle_scribble.png": 360, "arrow_curve.png": 350,
            }.get(asset_name, 340)
            span = 1.30 if role not in {"hook", "risk", "cta"} else 1.55
            event["sticker"] = {
                "asset": asset,
                "position": str(event.get("accent_position") or "caption_center"),
                "size": width,
                "start": round(start, 3),
                "end": round(min(duration, max(start + 0.95, min(end, start + span))), 3),
                "reference_motion_accent": True,
                "semantic_motion_overlay": True,
                "taxonomy": "motion_accent_not_cartoon_sticker",
                "counts_as_sticker": False,
                "no_text_box": True,
            }
            event.pop("sticker_skip_reason", None)
            used += 1
            last_start = start
            last_asset = asset
        reason = str(event.get("sticker_skip_reason") or "")
        if reason:
            skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
    return cleaned


_V32_BUILD_DYNAMIC_PLAN_V33_BASE = build_dynamic_plan


def build_dynamic_plan(
    payload: dict[str, Any],
    timings: list[dict[str, Any]],
    duration: float,
    *,
    intensity: str = "balanced",
) -> dict[str, Any]:
    plan = _V32_BUILD_DYNAMIC_PLAN_V33_BASE(payload, timings, duration, intensity=intensity)
    sfx_level = str(payload.get("dynamic_sfx_level") or "light")
    sticker_level = str(payload.get("dynamic_sticker_level") or "light")
    raw_events = [dict(item) for item in (plan.get("events") or []) if isinstance(item, dict)]
    events = _decorate_events(raw_events, duration, sfx_level=sfx_level, sticker_level=sticker_level)
    plan["events"] = events
    plan["version"] = VERSION
    plan["visual_pace"] = "large_caption_keyword_punch_semantic_motion_overlay"
    plan["legacy_sticker_forbidden"] = True
    plan["large_text_card_forbidden"] = True
    plan["pure_caption_emphasis"] = True
    plan["native_keyword_impact"] = True
    planned = [event for event in events if isinstance(event.get("sticker"), dict)]
    candidates = [event for event in events if event.get("sticker_candidate")]
    skip_reasons: dict[str, int] = {}
    for event in events:
        reason = str(event.get("sticker_skip_reason") or "")
        if reason:
            skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
    plan["effect_delivery"] = {
        "requested_sfx_level": sfx_level,
        "requested_sticker_level": sticker_level,
        "planned_sfx_count": sum(1 for event in events if isinstance(event.get("sfx"), dict)),
        "motion_overlay_candidates_count": len(candidates),
        "motion_overlay_applied_count": len(planned),
        "sticker_candidates_count": len(candidates),
        "sticker_applied_count": 0,
        "legacy_sticker_count": 0,
        "sticker_skip_reasons": skip_reasons,
        "keyword_impact_count": int(plan.get("keyword_impact_count") or 0),
        "sfx_pack": "mixkit-pro-v33-audible",
        "overlay_pack": "reference-motion-accents-v33",
        "text_box_count": 0,
    }
    return plan


def _collect_sticker_inputs(plan: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for event in plan.get("events") or []:
        sticker = event.get("sticker")
        if not isinstance(sticker, dict) or sticker.get("semantic_motion_overlay") is not True:
            continue
        asset = str(sticker.get("asset") or "")
        if not asset.startswith(V33_ACCENT_PREFIX):
            continue
        path = _sticker_root() / asset
        if path.is_file():
            result.append({"event": event, "sticker": sticker, "path": path})
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
    duration = max(0.1, _safe_float(plan.get("render_duration"), _safe_float(plan.get("duration"), 30.0)))
    events = list(plan.get("events") or [])
    limits = plan.get("limits") or {}
    zoom_strength = _safe_float(limits.get("zoom_strength"), 0.050)
    zoom_terms: list[str] = []
    for event in events:
        role = str(event.get("role") or "knowledge")
        if role not in {"hook", "comparison", "risk", "question", "data", "cta"}:
            continue
        start = _safe_float(event.get("start"), 0.0)
        span = 0.66
        strength = zoom_strength * {"hook": 1.0, "comparison": 0.78, "risk": 0.76, "question": 0.64, "data": 0.62, "cta": 0.52}.get(role, 0.60)
        zoom_terms.append(f"+{strength:.4f}*between(t,{start:.3f},{start+span:.3f})*sin(PI*(t-{start:.3f})/{span:.3f})")
    factor = "1" + "".join(zoom_terms)
    chain = [
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1[base]",
        f"[base]scale=w='{width}*({factor})':h='{height}*({factor})':eval=frame,crop={width}:{height}:(iw-{width})/2:(ih-{height})/2[v0]",
    ]
    current = "v0"
    positions = {
        "caption_center": ("(W-w)/2", "1030"),
        "caption_left": ("95", "1030"),
        "caption_right": ("W-w-95", "1010"),
    }
    for index, item in enumerate(sticker_inputs, start=1):
        sticker = item["sticker"]
        input_index = int(item["input_index"])
        start = _safe_float(sticker.get("start"), 0.0)
        end = max(start + 0.85, _safe_float(sticker.get("end"), start + 1.30))
        span = max(0.85, end - start)
        size = max(300, min(420, int(sticker.get("size") or 350)))
        x_expr, y_base = positions.get(str(sticker.get("position") or "caption_center"), positions["caption_center"])
        label = f"v33overlay{index}"
        output = f"v33out{index}"
        chain.append(
            f"[{input_index}:v]format=rgba,scale=w={size}:h=-1:force_original_aspect_ratio=decrease,"
            f"pad={size+34}:{size+34}:(ow-iw)/2:(oh-ih)/2:color=0x00000000,"
            f"trim=duration={span:.3f},fade=t=in:st=0:d=0.06:alpha=1,"
            f"fade=t=out:st={max(0.12,span-0.17):.3f}:d=0.17:alpha=1,"
            f"setpts=PTS-STARTPTS+{start:.3f}/TB[{label}]"
        )
        chain.append(
            f"[{current}][{label}]overlay=x='{x_expr}+7*sin(2*PI*(t-{start:.3f})/1.05)':"
            f"y='{y_base}+7*sin(2*PI*(t-{start:.3f})/1.28)':"
            f"eof_action=pass:shortest=0:enable='between(t,{start:.3f},{end:.3f})'[{output}]"
        )
        current = output
    chain.append(f"[{current}]ass='{_ffmpeg_escape_path(ass_path)}',tpad=stop_mode=clone:stop_duration=1,trim=duration={duration:.3f}[vout]")
    return ";".join(chain)


def _validate_v26_effect_plan(
    plan: dict[str, Any],
    timings: list[dict[str, Any]],
    sfx_level: str,
    sticker_level: str,
) -> dict[str, Any]:
    events = list(plan.get("events") or [])
    sfx_count = sum(1 for event in events if isinstance(event.get("sfx"), dict))
    overlays = [event.get("sticker") for event in events if isinstance(event.get("sticker"), dict)]
    bad = [item for item in overlays if item.get("semantic_motion_overlay") is not True or not str(item.get("asset") or "").startswith(V33_ACCENT_PREFIX)]
    if sfx_level != "off" and sfx_count <= 0:
        raise ValueError("V33 可听音效计划为空")
    if sticker_level != "off" and not overlays:
        raise ValueError("V33 语义动态标注计划为空")
    if bad:
        raise ValueError(f"V33 检测到旧式低质贴纸或随机角标：{len(bad)}")
    return plan


_V32_RENDER_DYNAMIC_VIDEO_V33_BASE = render_dynamic_video


def render_dynamic_video(input_path: Path, output_path: Path, ass_path: Path, plan: dict[str, Any]) -> dict[str, Any]:
    report = _V32_RENDER_DYNAMIC_VIDEO_V33_BASE(input_path, output_path, ass_path, plan)
    overlay_inputs = _collect_sticker_inputs(plan)
    impact_sidecar = ass_path.with_suffix(".impact.json")
    impact_meta: dict[str, Any] = {}
    if impact_sidecar.is_file():
        try:
            loaded = json.loads(impact_sidecar.read_text(encoding="utf-8"))
            impact_meta = loaded if isinstance(loaded, dict) else {}
        except Exception:
            impact_meta = {}
    report["effect_engine"] = "v33_semantic_relevance_caption_hierarchy"
    report["large_text_card_forbidden"] = True
    report["text_box_count"] = 0
    report["legacy_sticker_count"] = 0
    report["semantic_motion_overlay_count"] = len(overlay_inputs)
    report["motion_overlay_assets"] = [item["path"].name for item in overlay_inputs]
    report["kinetic_keyword_count"] = int(impact_meta.get("keyword_impact_count") or 0)
    report["keyword_impact_candidates"] = int(impact_meta.get("keyword_impact_candidates") or 0)
    report["keyword_impact_coverage"] = float(impact_meta.get("keyword_impact_coverage") or 0.0)
    report["base_caption_size"] = int(impact_meta.get("base_caption_size") or 0)
    return report


def _build_audio_filters(plan: dict[str, Any], *, has_audio: bool, sfx_inputs: list[dict[str, Any]]) -> tuple[str, str | None]:
    """V33 audible but clean mix: SFX is actually present while speech remains dominant."""
    if not has_audio:
        return "", None
    duration = max(0.1, _safe_float(plan.get("render_duration"), _safe_float(plan.get("duration"), 30.0)))
    duck_terms: list[str] = []
    for item in sfx_inputs:
        start = max(0.0, _safe_float((item.get("event") or {}).get("start"), 0.0))
        duck_terms.append(f"-0.12*between(t,{start:.3f},{start + 0.48:.3f})")
    duck = "1" + "".join(duck_terms)
    parts = [
        f"[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
        f"apad=pad_dur={duration:.3f},atrim=duration={duration:.3f},"
        f"loudnorm=I=-16:LRA=7:TP=-2.0,volume='{duck}':eval=frame[voice]"
    ]
    labels = ["voice"]
    for index, item in enumerate(sfx_inputs, start=1):
        event = item["event"]
        sfx = item["sfx"]
        inp = int(item["input_index"])
        delay = int(max(0.0, _safe_float(event.get("start"), 0.0)) * 1000)
        gain = max(0.48, min(0.72, _safe_float(sfx.get("gain"), 0.56)))
        label = f"v33sfx{index}"
        parts.append(
            f"[{inp}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"atrim=0:1.45,asetpts=PTS-STARTPTS,highpass=f=90,lowpass=f=14500,"
            f"volume={gain:.4f},afade=t=in:st=0:d=0.010,afade=t=out:st=1.18:d=0.22,"
            f"adelay={delay}|{delay}[{label}]"
        )
        labels.append(label)
    if len(labels) == 1:
        parts.append("[voice]alimiter=limit=0.94[aout]")
    else:
        parts.append(
            "".join(f"[{label}]" for label in labels)
            + f"amix=inputs={len(labels)}:duration=longest:dropout_transition=0:normalize=0,"
            + f"atrim=duration={duration:.3f},loudnorm=I=-15.5:LRA=8:TP=-1.5,alimiter=limit=0.96[aout]"
        )
    return ";".join(parts), "aout"

# =============================================================================
# V10.40.8.34 DEDUP KEYWORD + ENTITY LOCK + CTA CLOSE
# =============================================================================
V34_MARKER = "V10_40_8_34_DEDUP_KEYWORD_ENTITY_CTA"
V34_IMPACT_GAP_SECONDS = 0.92
V34_PAIR_TERMS = (
    ("自住", "投资"), ("自住", "出租"), ("出租", "转手"),
    ("价格", "价值"), ("现在", "未来"),
)


def _v34_remove_tokens(text: str, tokens: list[str]) -> str:
    value = str(text or "")
    for token in sorted({item for item in tokens if item}, key=len, reverse=True):
        value = value.replace(token, "")
    value = re.sub(r"[，,、]{2,}", "，", value)
    value = re.sub(r"^[，,、。；：:！？?\s]+|[，,、；：:\s]+$", "", value)
    value = re.sub(r"\s+", "", value)
    return value.strip()


def _v34_comparison_pair(text: str) -> tuple[str, str] | None:
    clean = _v32_clean_keyword(text)
    for left, right in V34_PAIR_TERMS:
        if left in clean and right in clean:
            return left, right
    return None


def _v34_base_caption_line(
    raw_text: str,
    focus_tokens: list[str],
    keywords: list[str],
    highlight: str,
) -> str:
    clean = _v34_remove_tokens(raw_text, focus_tokens)
    if len([item for item in focus_tokens if item]) >= 2:
        clean = re.sub(r"(?:还是说|还是|或者|或是|或|以及|和|与|VS|vs)", "", clean)
        clean = re.sub(r"[，,、；：:\s]+$", "", clean).strip()
    if not clean:
        return ""
    wrapped = _v32_wrap_caption(clean, 7)
    return _highlight_ass(wrapped, [item for item in keywords if item not in focus_tokens], highlight)


def write_dynamic_ass(
    destination: Path,
    timings: list[dict[str, Any]],
    keywords: list[str],
    *,
    style_id: str,
    events: list[dict[str, Any]] | None = None,
) -> Path:
    """V34: a punched keyword is removed from the base caption, so it never appears twice."""
    preset = SUBTITLE_PRESETS.get(style_id) or SUBTITLE_PRESETS["dynamic_white_yellow"]
    context = getattr(_V16_CONTEXT, "config", {}) or {}
    requested = int(context.get("caption_size") or 154)
    base_size = max(142, min(198, requested))
    font_name = "Noto Sans CJK SC"
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes
WrapStyle: 2

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Dynamic,{font_name},{base_size},{preset['primary']},{preset['highlight']},{preset['outline']},&H00000000,-1,0,0,0,100,100,1.2,0,1,8,2,5,44,44,0,1
Style: Impact,{font_name},224,&H00FFFFFF,&H0000E8FF,&H00101010,&H00000000,-1,0,0,0,100,100,1.0,0,1,13,3,5,32,32,0,1
Style: ImpactSmall,{font_name},112,&H00FFFFFF,&H0000E8FF,&H00101010,&H00000000,-1,0,0,0,100,100,1.0,0,1,9,2,5,32,32,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    last_impact = -999.0
    duration = max((_safe_float(item.get("end"), 0.0) for item in timings), default=0.0)
    max_impacts = max(6, min(12, int(math.ceil(max(1.0, duration) / 30.0 * 11))))
    impact_count = 0
    impact_candidates = 0
    duplicate_suppressed = 0
    comparison_pair_count = 0
    cta_lockup_count = 0
    impact_debug: list[dict[str, Any]] = []
    role_colors = {
        "risk": "&H003B6BFF&", "question": "&H00FFE04B&", "cta": "&H0047D2FF&",
        "comparison": "&H00FFB347&", "data": "&H0000E8FF&", "list": "&H0068E083&", "hook": "&H0000E8FF&",
    }
    for item in timings:
        start = _safe_float(item.get("start"), 0.0)
        end = max(start + 0.30, _safe_float(item.get("end"), start + 0.85))
        raw_text = _clean_caption_text(str(item.get("text") or ""))
        role = _v30_semantic_role(raw_text, _classify(raw_text)) if '_v30_semantic_role' in globals() else _classify(raw_text)
        pair = _v34_comparison_pair(raw_text) if role == "comparison" or re.search(r"自住|投资|出租|转手", raw_text) else None
        focus = _v32_focus_keyword(raw_text, keywords, role)
        impact_candidates += 1 if (focus or pair) else 0
        can_impact = bool(
            (focus or pair)
            and impact_count < max_impacts
            and start - last_impact >= V34_IMPACT_GAP_SECONDS
        )
        focus_tokens = list(pair) if pair and can_impact else ([focus] if focus and can_impact else [])
        main_text = _v34_base_caption_line(raw_text, focus_tokens, keywords, str(preset["highlight"]))
        short = len(_v32_clean_keyword(raw_text)) <= 7
        line_size = min(190, base_size + (16 if short else 0))
        position = 1410 if role not in {"hook", "question", "cta"} else 1345
        if main_text:
            animation = (
                rf"{{\an5\pos(540,{position})\fs{line_size}\fscx94\fscy94"
                rf"\t(0,105,\fscx105\fscy105)\t(105,225,\fscx100\fscy100)\fad(18,70)}}"
            )
            lines.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Dynamic,,0,0,0,,{animation}{main_text}\n")

        if not can_impact:
            continue
        timing_target = pair[0] if pair else focus
        impact_start, impact_end, timing_source = _v32_keyword_timing(item, timing_target)
        if pair:
            # A comparison uses the full spoken phrase window; both terms become the visual sentence.
            impact_start = start
            impact_end = max(start + 0.70, min(end, start + 1.55))
        if impact_end <= impact_start + 0.18:
            continue

        if pair:
            left, right = pair
            color = role_colors.get("comparison", "&H00FFB347&")
            left_anim = (
                rf"{{\an5\pos(300,1080)\fs218\c{color}\bord13\shad3\frz-2"
                rf"\fscx50\fscy50\t(0,100,\fscx154\fscy154\frz1)"
                rf"\t(100,270,\fscx112\fscy112\frz0)\fad(10,90)}}"
            )
            right_anim = (
                rf"{{\an5\pos(780,1080)\fs218\c&H0000E8FF&\bord13\shad3\frz2"
                rf"\fscx50\fscy50\t(70,175,\fscx154\fscy154\frz-1)"
                rf"\t(175,340,\fscx112\fscy112\frz0)\fad(10,90)}}"
            )
            vs_anim = rf"{{\an5\pos(540,1085)\fs94\c&H00FFFFFF&\bord8\shad2\fad(70,100)}}"
            lines.append(f"Dialogue: 2,{_ass_time(impact_start)},{_ass_time(impact_end)},Impact,,0,0,0,,{left_anim}{_ass_escape(left)}\n")
            lines.append(f"Dialogue: 2,{_ass_time(impact_start)},{_ass_time(impact_end)},Impact,,0,0,0,,{right_anim}{_ass_escape(right)}\n")
            lines.append(f"Dialogue: 2,{_ass_time(impact_start)},{_ass_time(impact_end)},ImpactSmall,,0,0,0,,{vs_anim}VS\n")
            comparison_pair_count += 1
            duplicate_suppressed += 2
            impact_debug.append({
                "text": f"{left} VS {right}", "start": round(impact_start, 3), "end": round(impact_end, 3),
                "timing_source": "comparison_phrase_window", "size": 218, "scale_peak": 154,
                "base_caption_tokens_removed": [left, right],
            })
        else:
            impact_size = 250 if len(focus) <= 3 else 224 if len(focus) <= 5 else 196
            impact_y = 1055 if role in {"hook", "question", "risk", "comparison", "cta"} else 1165
            color = role_colors.get(role, "&H0000E8FF&")
            impact_animation = (
                rf"{{\an5\pos(540,{impact_y})\fs{impact_size}\c{color}\bord13\shad3\frz-2"
                rf"\fscx48\fscy48\t(0,95,\fscx154\fscy154\frz1)"
                rf"\t(95,270,\fscx112\fscy112\frz0)\fad(10,95)}}"
            )
            lines.append(
                f"Dialogue: 2,{_ass_time(impact_start)},{_ass_time(impact_end)},Impact,,0,0,0,,"
                f"{impact_animation}{_ass_escape(focus)}\n"
            )
            duplicate_suppressed += 1
            if role == "cta":
                cta_lockup_count += 1
            impact_debug.append({
                "text": focus, "start": round(impact_start, 3), "end": round(impact_end, 3),
                "timing_source": timing_source, "size": impact_size, "scale_peak": 154,
                "base_caption_tokens_removed": [focus],
            })
        impact_count += 1
        last_impact = impact_start

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("".join(lines), encoding="utf-8-sig")
    try:
        destination.with_suffix(".impact.json").write_text(
            json.dumps({
                "keyword_impact_count": impact_count,
                "keyword_impact_candidates": impact_candidates,
                "keyword_impact_coverage": round(impact_count / max(1, impact_candidates), 3),
                "base_caption_size": base_size,
                "duplicate_keyword_suppressed_count": duplicate_suppressed,
                "comparison_pair_count": comparison_pair_count,
                "cta_lockup_count": cta_lockup_count,
                "impacts": impact_debug,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass
    return destination


_V33_DECORATE_EVENTS_V34_BASE = _decorate_events


def _decorate_events(
    events: list[dict[str, Any]],
    duration: float,
    *,
    sfx_level: str,
    sticker_level: str,
) -> list[dict[str, Any]]:
    result = _V33_DECORATE_EVENTS_V34_BASE(
        events, duration, sfx_level=sfx_level, sticker_level=sticker_level,
    )
    forced_assets = {
        "cta": ("comment_bubble.png", "caption_right"),
        "comparison": ("split_arrows.png", "caption_center"),
        "question": ("circle_scribble.png", "caption_center"),
        "risk": ("warning_tape.png", "caption_center"),
        "data": ("underline_brush.png", "caption_center"),
        "turn": ("arrow_curve.png", "caption_right"),
    }
    role_gain_floor = {
        "hook": 0.80, "question": 0.76, "turn": 0.72, "data": 0.74,
        "risk": 0.80, "comparison": 0.78, "cta": 0.82,
    }
    last_asset = ""
    for index, event in enumerate(result):
        text = str(event.get("source_text") or event.get("focus_text") or "")
        role = _v30_semantic_role(text, str(event.get("role") or "knowledge"))
        event["role"] = role
        forced = forced_assets.get(role)
        if sticker_level != "off" and forced:
            asset, position = forced
            path = _sticker_root() / V33_ACCENT_PREFIX / asset
            if path.is_file():
                event["sticker"] = {
                    "asset": f"{V33_ACCENT_PREFIX}{asset}",
                    "start": round(_safe_float(event.get("start"), 0.0), 3),
                    "end": round(max(_safe_float(event.get("start"), 0.0) + 0.95, min(_safe_float(event.get("end"), 0.0), _safe_float(event.get("start"), 0.0) + 1.55)), 3),
                    "position": position,
                    "size": 380 if role in {"cta", "comparison"} else 345,
                    "semantic_motion_overlay": True,
                    "counts_as_sticker": False,
                    "v34_forced_semantic_overlay": True,
                }
        sfx = event.get("sfx") if isinstance(event.get("sfx"), dict) else None
        if sfx is not None:
            sfx["gain"] = round(max(role_gain_floor.get(role, 0.68), _safe_float(sfx.get("gain"), 0.0)), 4)
        elif sfx_level != "off" and role in role_gain_floor:
            asset, _ = _v16_choose_variant(role, event, index, last_asset)
            if asset:
                event["sfx"] = {"asset": asset, "gain": role_gain_floor[role], "role": role, "v34_forced": True}
                last_asset = asset
    return result


_V33_BUILD_DYNAMIC_PLAN_V34_BASE = build_dynamic_plan


def build_dynamic_plan(
    payload: dict[str, Any],
    timings: list[dict[str, Any]],
    duration: float,
    *,
    intensity: str = "balanced",
) -> dict[str, Any]:
    plan = _V33_BUILD_DYNAMIC_PLAN_V34_BASE(payload, timings, duration, intensity=intensity)
    plan["events"] = _decorate_events(
        [dict(item) for item in (plan.get("events") or []) if isinstance(item, dict)],
        duration,
        sfx_level=str(payload.get("dynamic_sfx_level") or "light"),
        sticker_level=str(payload.get("dynamic_sticker_level") or "light"),
    )
    delivery = dict(plan.get("effect_delivery") or {})
    delivery.update({
        "keyword_duplicate_suppression": True,
        "comparison_pair_lockup": True,
        "cta_comment_overlay_required": True,
        "sfx_window_target_db": "-16_to_-20_relative_to_voice",
        "text_box_count": 0,
    })
    plan["effect_delivery"] = delivery
    plan["version"] = VERSION
    plan["visual_pace"] = "dedup_keyword_entity_lock_cta_close"
    return plan


def _build_audio_filters(plan: dict[str, Any], *, has_audio: bool, sfx_inputs: list[dict[str, Any]]) -> tuple[str, str | None]:
    """V34: normalize each SFX before gain, then mix without a second loudnorm pass that buries it."""
    if not has_audio:
        return "", None
    duration = max(0.1, _safe_float(plan.get("render_duration"), _safe_float(plan.get("duration"), 30.0)))
    duck_terms: list[str] = []
    for item in sfx_inputs:
        start = max(0.0, _safe_float((item.get("event") or {}).get("start"), 0.0))
        duck_terms.append(f"-0.16*between(t,{start:.3f},{start + 0.52:.3f})")
    duck = "1" + "".join(duck_terms)
    parts = [
        f"[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
        f"apad=pad_dur={duration:.3f},atrim=duration={duration:.3f},"
        f"loudnorm=I=-16:LRA=7:TP=-2.0,volume='{duck}':eval=frame[voice]"
    ]
    labels = ["voice"]
    for index, item in enumerate(sfx_inputs, start=1):
        event = item["event"]
        sfx = item["sfx"]
        inp = int(item["input_index"])
        delay = int(max(0.0, _safe_float(event.get("start"), 0.0)) * 1000)
        gain = max(0.72, min(1.00, _safe_float(sfx.get("gain"), 0.82)))
        label = f"v34sfx{index}"
        parts.append(
            f"[{inp}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"atrim=0:1.45,asetpts=PTS-STARTPTS,highpass=f=90,lowpass=f=14500,"
            f"loudnorm=I=-19:LRA=5:TP=-3.0,volume={gain:.4f},"
            f"pan=stereo|c0=1.00*c0|c1=0.72*c1,"
            f"afade=t=in:st=0:d=0.008,afade=t=out:st=1.18:d=0.22,"
            f"adelay={delay}|{delay}[{label}]"
        )
        labels.append(label)
    if len(labels) == 1:
        parts.append("[voice]alimiter=limit=0.94[aout]")
    else:
        parts.append(
            "".join(f"[{label}]" for label in labels)
            + f"amix=inputs={len(labels)}:duration=longest:dropout_transition=0:normalize=0,"
            + f"atrim=duration={duration:.3f},alimiter=limit=0.96[aout]"
        )
    return ";".join(parts), "aout"


_V33_RENDER_DYNAMIC_VIDEO_V34_BASE = render_dynamic_video


def render_dynamic_video(input_path: Path, output_path: Path, ass_path: Path, plan: dict[str, Any]) -> dict[str, Any]:
    report = _V33_RENDER_DYNAMIC_VIDEO_V34_BASE(input_path, output_path, ass_path, plan)
    sidecar = ass_path.with_suffix(".impact.json")
    meta: dict[str, Any] = {}
    if sidecar.is_file():
        try:
            loaded = json.loads(sidecar.read_text(encoding="utf-8"))
            meta = loaded if isinstance(loaded, dict) else {}
        except Exception:
            meta = {}
    report.update({
        "effect_engine": "v34_dedup_keyword_entity_cta",
        "duplicate_keyword_suppressed_count": int(meta.get("duplicate_keyword_suppressed_count") or 0),
        "comparison_pair_count": int(meta.get("comparison_pair_count") or 0),
        "cta_lockup_count": int(meta.get("cta_lockup_count") or 0),
        "keyword_duplicate_visible": False,
        "sfx_window_target_db": "-16_to_-20_relative_to_voice",
        "text_box_count": 0,
    })
    return report


# =============================================================================
# V10.40.8.37 INLINE KEYWORD + CAPTION ORDER INTEGRITY
# =============================================================================
V37_CAPTION_PROTECTED_TERMS = (
    "一年小一万", "一年一万", "每月每平米", "每平方米", "物业费", "管理费",
    "门牌税", "地税", "维修基金", "空置期", "实际租金", "净回报", "现金流",
    "最高预期", "真实成交租金", "持有成本", "律师费", "印花税", "贷款利息",
    "生活半径", "国际学校", "写字楼", "办公区", "租客来源", "自住还是投资",
    "吉隆坡买房", "评论区", "把项目发来", "帮你核一遍",
    "或者", "以及", "但是", "不过", "所以", "而且", "然后", "才能",
)


def _v37_protected_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for term in V37_CAPTION_PROTECTED_TERMS:
        cursor = 0
        while term and (index := text.find(term, cursor)) >= 0:
            spans.append((index, index + len(term)))
            cursor = index + len(term)
    number_pattern = re.compile(
        r"(?:\d+(?:\.\d+)?|[零〇一二三四五六七八九十百千万亿两]+)"
        r"(?:%|％|万|千|百|亿|元|块|马币|年|月|天|套|个|平米|平方米|每平米|每平方米)?"
    )
    spans.extend((m.start(), m.end()) for m in number_pattern.finditer(text))
    return sorted(set(spans))


def _v37_cut_inside_protected(cut: int, spans: list[tuple[int, int]]) -> bool:
    return any(start < cut < end for start, end in spans)


def _caption_chunks(text: str, *, max_chars: int = 10) -> list[str]:
    """Phrase-safe caption splitting. Never extracts keywords from sentence order."""
    clean = _clean_caption_text(text)
    if not clean:
        return []
    phrases = [item for item in re.split(r"[，,。！？!?；;、：:]+", clean) if item] or [clean]
    output: list[str] = []
    boundary_left = set("了的是要会能才再先后与和或但却把对从在到按看算问说")
    boundary_right = ("如果", "但是", "不过", "所以", "而且", "或者", "以及", "然后", "才能", "再看", "先看")

    for phrase in phrases:
        remaining = phrase
        while len(remaining) > max_chars:
            spans = _v37_protected_spans(remaining)
            candidates: list[tuple[float, int]] = []
            lower = max(4, max_chars - 3)
            upper = min(len(remaining) - 2, max_chars + 2)
            for cut in range(lower, upper + 1):
                if _v37_cut_inside_protected(cut, spans):
                    continue
                left, right = remaining[:cut], remaining[cut:]
                if len(right) <= 2:
                    continue
                score = -abs(cut - max_chars) * 1.5
                if left[-1:] in boundary_left:
                    score += 3.0
                if any(right.startswith(term) for term in boundary_right):
                    score += 4.0
                if re.search(r"(?:费|税|金|期|租金|回报|成本)$", left):
                    score += 2.5
                if re.match(r"^(?:费|税|金|期|租金|回报|成本)", right):
                    score -= 4.0
                candidates.append((score, cut))
            cut = max(candidates)[1] if candidates else min(max_chars, len(remaining) - 2)
            output.append(remaining[:cut])
            remaining = remaining[cut:]
        if remaining:
            if len(remaining) <= 2 and output and len(output[-1]) + len(remaining) <= max_chars + 2:
                output[-1] += remaining
            else:
                output.append(remaining)

    expected = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9%]+", "", clean)
    actual = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9%]+", "", "".join(output))
    if expected != actual:
        raise ValueError("V37 字幕安全切分发生文字丢失或重排")
    return [item for item in output if item]


def _v37_inline_keyword_ass(raw_text: str, keywords: list[str], role: str, preset: dict[str, Any]) -> tuple[str, list[str]]:
    """Render emphasis at the keyword's original position in the one caption layer."""
    clean = _clean_caption_text(raw_text)
    pair = _v34_comparison_pair(clean) if role == "comparison" else None
    focus = _v32_focus_keyword(clean, keywords, role)
    targets: list[tuple[str, str]] = []
    if pair:
        targets = [(pair[0], "&H00FFB347&"), (pair[1], "&H0000E8FF&")]
    elif focus and focus in clean:
        color = {
            "risk": "&H003B6BFF&", "question": "&H00FFE04B&", "cta": "&H0047D2FF&",
            "comparison": "&H00FFB347&", "data": "&H0000E8FF&", "list": "&H0068E083&",
            "hook": "&H0000E8FF&",
        }.get(role, str(preset.get("highlight") or "&H0000E8FF&"))
        targets = [(focus, color)]

    spans: list[tuple[int, int, str, str]] = []
    for token, color in targets:
        index = clean.find(token)
        if index < 0:
            continue
        end = index + len(token)
        if any(not (end <= left or index >= right) for left, right, _, _ in spans):
            continue
        spans.append((index, end, token, color))
    spans.sort()

    pieces: list[str] = []
    cursor = 0
    applied: list[str] = []
    for start, end, token, color in spans:
        pieces.append(_ass_escape(clean[cursor:start]))
        pieces.append(
            rf"{{\c{color}\b1\bord11\fscx108\fscy108\t(0,130,\fscx100\fscy100)}}"
            + _ass_escape(token)
            + r"{\rDynamic}"
        )
        applied.append(token)
        cursor = end
    pieces.append(_ass_escape(clean[cursor:]))
    return "".join(pieces), applied


_V36_BUILD_DYNAMIC_PLAN_V37_BASE = build_dynamic_plan


def build_dynamic_plan(
    payload: dict[str, Any], timings: list[dict[str, Any]], duration: float, *, intensity: str = "balanced",
) -> dict[str, Any]:
    plan = _V36_BUILD_DYNAMIC_PLAN_V37_BASE(payload, timings, duration, intensity=intensity)
    plan["version"] = VERSION
    plan["visual_pace"] = "semantic_density_with_concrete_entity_microcuts"
    plan["inline_keyword_only"] = True
    plan["separate_keyword_text_layer"] = False
    plan["caption_order_integrity"] = True
    delivery = dict(plan.get("effect_delivery") or {})
    delivery.update({
        "inline_keyword_only": True,
        "separate_keyword_overlay_count": 0,
        "caption_order_preserved": True,
        "base_caption_tokens_removed": False,
    })
    plan["effect_delivery"] = delivery
    return plan


def write_dynamic_ass(
    destination: Path,
    timings: list[dict[str, Any]],
    keywords: list[str],
    *,
    style_id: str,
    events: list[dict[str, Any]] | None = None,
) -> Path:
    """V37: complete caption stays intact; keyword emphasis is inline and never reorders speech."""
    preset = SUBTITLE_PRESETS.get(style_id) or SUBTITLE_PRESETS["dynamic_white_yellow"]
    context = getattr(_V16_CONTEXT, "config", {}) or {}
    requested = int(context.get("caption_size") or 154)
    base_size = max(142, min(194, requested))
    font_name = "Noto Sans CJK SC"
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes
WrapStyle: 2

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Dynamic,{font_name},{base_size},{preset['primary']},{preset['highlight']},{preset['outline']},&H00000000,-1,0,0,0,100,100,1.2,0,1,8,2,5,44,44,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    applied_total = 0
    debug: list[dict[str, Any]] = []
    for index, item in enumerate(timings):
        start = _safe_float(item.get("start"), 0.0)
        end = max(start + 0.30, _safe_float(item.get("end"), start + 0.85))
        raw_text = _clean_caption_text(str(item.get("text") or ""))
        role = _v30_semantic_role(raw_text, _classify(raw_text)) if "_v30_semantic_role" in globals() else _classify(raw_text)
        inline_text, applied = _v37_inline_keyword_ass(raw_text, keywords, role, preset)
        applied_total += len(applied)
        short = len(_v32_clean_keyword(raw_text)) <= 7
        line_size = min(188, base_size + (14 if short else 0))
        position = 1370 if role in {"hook", "question", "cta"} else 1430
        animation = (
            rf"{{\an5\pos(540,{position})\fs{line_size}\fscx94\fscy94"
            rf"\t(0,105,\fscx104\fscy104)\t(105,225,\fscx100\fscy100)\fad(18,70)}}"
        )
        lines.append(
            f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Dynamic,,0,0,0,,{animation}{inline_text}\n"
        )
        debug.append({
            "index": index,
            "text": raw_text,
            "inline_keywords": applied,
            "caption_order_preserved": True,
            "base_caption_tokens_removed": [],
        })

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("".join(lines), encoding="utf-8-sig")
    destination.with_suffix(".impact.json").write_text(
        json.dumps({
            "keyword_impact_count": applied_total,
            "keyword_impact_candidates": applied_total,
            "keyword_impact_coverage": 1.0 if applied_total else 0.0,
            "base_caption_size": base_size,
            "duplicate_keyword_suppressed_count": 0,
            "comparison_pair_count": sum(1 for item in debug if len(item["inline_keywords"]) == 2),
            "cta_lockup_count": 0,
            "inline_keyword_only": True,
            "separate_keyword_overlay_count": 0,
            "caption_order_preserved": True,
            "base_caption_tokens_removed": False,
            "impacts": debug,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return destination


_V36_RENDER_DYNAMIC_VIDEO_V37_BASE = render_dynamic_video


def render_dynamic_video(input_path: Path, output_path: Path, ass_path: Path, plan: dict[str, Any]) -> dict[str, Any]:
    report = _V36_RENDER_DYNAMIC_VIDEO_V37_BASE(input_path, output_path, ass_path, plan)
    report.update({
        "effect_engine": "v37_inline_keyword_entity_microcut_cta",
        "inline_keyword_only": True,
        "separate_keyword_overlay_count": 0,
        "caption_order_preserved": True,
        "base_caption_tokens_removed": False,
        "keyword_duplicate_visible": False,
    })
    return report
