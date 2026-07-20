from __future__ import annotations

import asyncio
import json
import math
import os
import re
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Iterable, Sequence

VERSION = "10.40.8.7-a9-r3"
DIRECTOR_MARKER = "ai_subtitle_edit_director_v10_40_8_7_a9_r3"

_PUNCT = re.compile(r'''[\s，。！？、；：,.!?;:"'“”‘’（）()〖〗\[\]《》<>/\\|·•…—_-]+''')
_BOUNDARY = re.compile(r"(?<=[。！？!?；;])|\n+")
_CONNECTORS = (
    "第一", "第二", "第三", "第四", "但是", "不过", "所以", "因此",
    "真正", "关键是", "重点是", "最后", "结论是", "记住", "别只看",
    "不要只看",
)
_PROTECTED = (
    "吉隆坡房子", "吉隆坡买房", "第一眼", "自住还是投资", "自住需求",
    "投资需求", "区域成熟度", "真实持有成本", "转手难度", "物业费",
    "门牌税", "水电费", "现金流", "租金回报", "第二家园",
)
_PRIORITY = (
    "别只看价格", "不要只看价格", "很容易买错", "容易买错", "区域成熟",
    "自住还是投资", "真实持有成本", "转手难度", "持有成本", "现金流",
    "租金回报", "物业费", "门牌税", "水电费", "预算", "风险", "避坑",
    "关键", "重点", "结论",
)
_STOPWORDS = {"这个", "一个", "我们", "就是", "可以", "其实", "然后", "如果", "因为", "很多", "比较", "视频", "素材", "画面", "镜头"}


def _canonical(value: Any) -> str:
    return _PUNCT.sub("", str(value or "")).strip()


def _display(value: Any) -> str:
    return _canonical(value)


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"0", "false", "off", "no", "none", "disabled"}


def _tokens(value: Any) -> set[str]:
    text = str(value or "").lower()
    result = set(re.findall(r"[a-z0-9%+_-]{2,}|[\u4e00-\u9fff]{2,}", text))
    zh = "".join(re.findall(r"[\u4e00-\u9fff]", text))
    for width in (2, 3, 4):
        result.update(zh[i : i + width] for i in range(max(0, len(zh) - width + 1)))
    return {item for item in result if item not in _STOPWORDS}


def _timing_bounds(item: dict[str, Any], cursor: float) -> tuple[float, float]:
    start_value = item.get("start") if item.get("start") is not None else item.get("start_time")
    end_value = item.get("end") if item.get("end") is not None else item.get("end_time")
    start = _float(item.get("start_ms"), 0.0) / 1000.0 if item.get("start_ms") is not None else _float(start_value, cursor)
    if item.get("end_ms") is not None:
        end = _float(item.get("end_ms"), 0.0) / 1000.0
    elif end_value is not None:
        end = _float(end_value, start)
    elif item.get("duration") is not None:
        end = start + _float(item.get("duration"), 0.0)
    else:
        end = start
    return max(0.0, start), max(start, end)


def _inside_protected(text: str, position: int) -> bool:
    for phrase in _PROTECTED:
        start = text.find(phrase)
        while start >= 0:
            if start < position < start + len(phrase):
                return True
            start = text.find(phrase, start + 1)
    return False


def _break_candidates(text: str) -> list[int]:
    result: set[int] = set()
    for connector in _CONNECTORS:
        start = text.find(connector)
        while start >= 0:
            if start > 0:
                result.add(start)
            after = start + len(connector)
            if after < len(text):
                result.add(after)
            start = text.find(connector, start + 1)
    grammar = set("的了和与但也还就再才是把被给让向从到在有看说做买卖")
    for pos in range(2, len(text) - 1):
        if text[pos - 1] in grammar or text[pos] in grammar:
            result.add(pos)
    return sorted(pos for pos in result if not _inside_protected(text, pos))


def _best_break(text: str, minimum: int, maximum: int, target: int) -> int:
    valid = [pos for pos in _break_candidates(text) if minimum <= pos <= maximum]
    if valid:
        return min(valid, key=lambda pos: (abs(pos - target), pos))
    for distance in range(maximum - minimum + 1):
        for pos in (target - distance, target + distance):
            if minimum <= pos <= maximum and not _inside_protected(text, pos):
                return pos
    return max(minimum, min(maximum, target))


def _split_long(text: str, max_chars: int = 18) -> list[str]:
    remaining = _display(text)
    if not remaining:
        return []
    result: list[str] = []
    while len(remaining) > max_chars:
        minimum = 7 if len(remaining) > 14 else 4
        maximum = min(max_chars, len(remaining) - 4)
        target = min(max_chars - 2, max(minimum, round(len(remaining) / 2)))
        split_at = _best_break(remaining, minimum, maximum, target)
        result.append(remaining[:split_at])
        remaining = remaining[split_at:]
    if remaining:
        result.append(remaining)
    return result


def _semantic_units(text: str, max_chars: int = 18) -> list[str]:
    raw = str(text or "").strip()
    if not raw:
        return []
    sentences = [item.strip() for item in _BOUNDARY.split(raw) if item.strip()] or [raw]
    units: list[str] = []
    connector_pattern = re.compile("(" + "|".join(re.escape(x) for x in sorted(_CONNECTORS, key=len, reverse=True)) + ")")
    for sentence in sentences:
        clean = _display(sentence)
        if not clean:
            continue
        chunks: list[str] = []
        cursor = 0
        if len(clean) > max_chars:
            for match in connector_pattern.finditer(clean):
                if match.start() > cursor and match.start() - cursor >= 5:
                    chunks.append(clean[cursor : match.start()])
                    cursor = match.start()
        chunks.append(clean[cursor:])
        for chunk in chunks:
            units.extend(_split_long(chunk, max_chars=max_chars))
    merged: list[str] = []
    index = 0
    while index < len(units):
        current = units[index]
        if len(current) < 5 and index + 1 < len(units) and len(current) + len(units[index + 1]) <= max_chars:
            merged.append(current + units[index + 1])
            index += 2
            continue
        if merged and len(current) < 4 and len(merged[-1]) + len(current) <= max_chars:
            merged[-1] += current
        else:
            merged.append(current)
        index += 1
    if "".join(merged) != _canonical(raw):
        return _split_long(_canonical(raw), max_chars=max_chars)
    return merged


def _merge_short_duration(units: list[str], duration: float, minimum: float = 0.62) -> list[str]:
    result = list(units)
    while len(result) > 1 and duration / len(result) < minimum:
        candidates = []
        for index in range(len(result) - 1):
            combined = result[index] + result[index + 1]
            candidates.append((max(0, len(combined) - 20) * 100 + len(combined), index))
        _, index = min(candidates)
        result[index : index + 2] = [result[index] + result[index + 1]]
    return result


def _keywords(text: str, ai_keywords: Iterable[str] = ()) -> list[str]:
    value = _display(text)
    candidates: list[tuple[int, int, str]] = []
    def add(word: Any, priority: int) -> None:
        clean = _display(word)
        if clean and clean in value and 2 <= len(clean) <= 10:
            candidates.append((priority, len(clean), clean))
    for word in ai_keywords:
        add(word, 120)
    for word in _PRIORITY:
        add(word, 100)
    for match in re.finditer(r"(?:RM|人民币|美元|马币)?\d+(?:\.\d+)?(?:万|千|亿|%|年|个月|套|层|分钟|秒)?", value, re.I):
        add(match.group(0), 110)
    for word in _PROTECTED:
        add(word, 90)
    output: list[str] = []
    seen: set[str] = set()
    for _priority, _length, word in sorted(candidates, reverse=True):
        if word.lower() not in seen:
            seen.add(word.lower())
            output.append(word)
        if len(output) >= 2:
            break
    return output


def _lines(text: str, strong: str = "") -> list[str]:
    value = _display(text)
    strong = _display(strong)
    if strong and len(value) > len(strong):
        if value.startswith(strong) and 3 <= len(value[len(strong):]) <= 12:
            return [strong, value[len(strong):]]
        if value.endswith(strong) and 3 <= len(value[:-len(strong)]) <= 12:
            return [value[:-len(strong)], strong]
    if len(value) <= 10:
        return [value]
    split_at = _best_break(value, max(3, len(value) // 2 - 3), min(len(value) - 3, len(value) // 2 + 3), len(value) // 2)
    return [value[:split_at], value[split_at:]]


def _font_size(text: str, strong: bool) -> int:
    length = len(_display(text))
    size = 108 if length <= 6 else 100 if length <= 10 else 94 if length <= 14 else 88 if length <= 18 else 84
    return max(84, min(112, size + (4 if strong else 0)))


def _allocate(units: list[str], start: float, end: float) -> list[tuple[str, float, float]]:
    weights = [max(1.0, len(_display(item))) for item in units]
    remaining_weight = sum(weights)
    cursor = start
    result: list[tuple[str, float, float]] = []
    for index, (unit, weight) in enumerate(zip(units, weights)):
        unit_end = end if index == len(units) - 1 else cursor + (end - cursor) * weight / remaining_weight
        result.append((unit, round(cursor, 3), round(unit_end, 3)))
        cursor = unit_end
        remaining_weight -= weight
    return result


def _subtitle_plan(
    timings: Sequence[dict[str, Any]],
    *,
    target_duration: float,
    ai_units: dict[int, list[str]] | None = None,
    ai_keywords: Iterable[str] = (),
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cues: list[dict[str, Any]] = []
    source_text = ""
    output_text = ""
    cursor = 0.0
    for segment_index, timing in enumerate(timings, start=1):
        if not isinstance(timing, dict):
            continue
        raw = str(timing.get("text") or timing.get("subtitle_text") or "").strip()
        if not raw:
            continue
        start, end = _timing_bounds(timing, cursor)
        source = _canonical(raw)
        source_text += source
        proposed = [_display(x) for x in (ai_units or {}).get(segment_index, []) if _display(x)]
        units = proposed if proposed and "".join(proposed) == source else _semantic_units(raw)
        units = _merge_short_duration(units, max(0.01, end - start))
        for unit, cue_start, cue_end in _allocate(units, start, end):
            words = _keywords(unit, ai_keywords)
            strong = words[0] if words and (words[0] in _PRIORITY or re.search(r"\d", words[0])) else ""
            display_lines = _lines(unit, strong)
            cues.append({
                "index": len(cues) + 1,
                "segment_index": segment_index,
                "text": unit,
                "subtitle_text": unit,
                "display_lines": display_lines[:2],
                "start": cue_start,
                "end": cue_end,
                "duration": round(max(0.0, cue_end - cue_start), 3),
                "font_size": _font_size(unit, bool(strong)),
                "bold": True,
                "keywords": words,
                "strong_keyword": strong,
                "emphasis_mode": "separate_line" if strong and strong in display_lines and len(display_lines) == 2 else "scale_color" if words else "normal",
                "exact_tts": True,
                "director_version": VERSION,
            })
            output_text += _canonical(unit)
        cursor = end
    if source_text != output_text:
        raise ValueError("AI 字幕导演文字守恒校验失败：字幕与真实口播不一致")
    report = {
        "version": VERSION,
        "cue_count": len(cues),
        "source_char_count": len(source_text),
        "output_char_count": len(output_text),
        "text_preserved": source_text == output_text,
        "max_lines": max((len(item["display_lines"]) for item in cues), default=0),
        "minimum_font_size": min((item["font_size"] for item in cues), default=0),
        "maximum_font_size": max((item["font_size"] for item in cues), default=0),
        "strong_emphasis_count": sum(1 for item in cues if item.get("strong_keyword")),
        "tts_aligned": True,
    }
    return cues, report


def _durations(target: float, count: int) -> list[float]:
    weights = []
    for index in range(count):
        if index == 0:
            weight = 0.62
        elif index == 1:
            weight = 0.76
        elif index < 4:
            weight = 0.88
        elif index == count - 1:
            weight = 0.82
        else:
            weight = 1.08 if index % 4 == 0 else 0.94 if index % 3 == 0 else 1.0
        weights.append(weight)
    scale = target / sum(weights)
    values = [max(0.68, min(2.65, item * scale)) for item in weights]
    for _ in range(8):
        diff = target - sum(values)
        if abs(diff) < 0.001:
            break
        adjustable = [i for i, value in enumerate(values) if (diff > 0 and value < 2.65) or (diff < 0 and value > 0.68)]
        if not adjustable:
            break
        share = diff / len(adjustable)
        for index in adjustable:
            values[index] = max(0.68, min(2.65, values[index] + share))
    values = [round(item, 3) for item in values]
    values[-1] = round(values[-1] + target - sum(values), 3)
    return values


def _asset_id(clip: dict[str, Any]) -> str:
    return str(clip.get("asset_id") or clip.get("id") or clip.get("asset_name") or "").strip()


def _asset_url(clip: dict[str, Any]) -> str:
    return str(clip.get("asset_url") or clip.get("url") or clip.get("r2_url") or "").strip()


def _clip_text(clip: dict[str, Any]) -> str:
    return " ".join(str(clip.get(key) or "") for key in ("narration", "title", "scene", "description", "analysis_description", "asset_name"))


def _cue_at(cues: Sequence[dict[str, Any]], position: float) -> dict[str, Any]:
    for cue in cues:
        if _float(cue.get("start")) <= position <= _float(cue.get("end")):
            return dict(cue)
    return dict(cues[-1]) if cues else {}


def _edit_plan(
    clips: Sequence[dict[str, Any]],
    cues: Sequence[dict[str, Any]],
    *,
    target_duration: float,
    pace: str,
    preferred: dict[int, list[str]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    candidates = [dict(item) for item in clips if isinstance(item, dict) and str(item.get("source") or "").lower() == "r2" and _asset_url(item)]
    if not candidates:
        raise ValueError("AI 剪辑导演没有收到可用的 R2 视频片段")
    seconds_per_shot = {"fast": 1.55, "normal": 1.85, "slow": 2.15, "relaxed": 2.15}.get(str(pace or "normal").lower(), 1.85)
    count = max(max(1, min(len(cues), 10)), min(24, int(round(max(1.0, target_duration) / seconds_per_shot))))
    durations = _durations(target_duration, count)
    output: list[dict[str, Any]] = []
    reuse: dict[str, int] = {}
    previous = ""
    cursor = 0.0
    switches = 0
    for position, duration in enumerate(durations, start=1):
        cue = _cue_at(cues, cursor + duration / 2)
        cue_text = str(cue.get("text") or "")
        cue_tokens = _tokens(cue_text)
        preferred_ids = set((preferred or {}).get(int(cue.get("index") or 0), []))
        ranked = []
        candidate_pool = [
            candidate
            for candidate in candidates
            if not (
                len(candidates) > 1
                and _asset_id(candidate) == previous
            )
        ] or list(candidates)
        for candidate in candidate_pool:
            aid = _asset_id(candidate)
            candidate_text = _clip_text(candidate).lower()
            overlap = len(cue_tokens & _tokens(candidate_text))
            contains = sum(1 for token in cue_tokens if token and token in candidate_text)
            score = overlap * 11 + contains * 3.5 + _float(candidate.get("match_score")) * 0.15 - reuse.get(aid, 0) * 17
            if candidate.get("manual_locked") and reuse.get(aid, 0) == 0:
                score += 32
            if aid in preferred_ids:
                score += 45
            if len(candidates) > 1 and aid == previous:
                score -= 120
            ranked.append((score, candidate))
        ranked.sort(key=lambda item: item[0], reverse=True)
        selected = dict(ranked[0][1])
        aid = _asset_id(selected)
        reuse_index = reuse.get(aid, 0)
        reuse[aid] = reuse_index + 1
        start_time = max(0.15, _float(selected.get("start_time")) + reuse_index * (duration * 1.35 + 0.45))
        role = "hook" if cursor < 3.0 else "conclusion" if position == count else "body"
        if previous and aid != previous:
            switches += 1
        output.append({
            **selected,
            "id": f"director_clip_{position:02d}",
            "index": position,
            "duration": round(duration, 3),
            "duration_seconds": round(duration, 3),
            "narration": cue_text,
            "source": "r2",
            "asset_id": aid,
            "asset_ids": [aid],
            "asset_url": _asset_url(selected),
            "start_time": round(start_time, 3),
            "end_time": round(start_time + duration, 3),
            "auto_start": False,
            "speed": 1.04 if role == "hook" else 1.0,
            "transition": "开场硬切" if position == 1 else "直接切" if aid != previous else "动作匹配切",
            "camera": "轻微推进" if role == "hook" or position % 4 == 0 else "保留原片运镜",
            "pace_role": role,
            "cue_index": int(cue.get("index") or 0),
            "director_reason": f"口播语义匹配「{cue_text[:18]}」；应用连续素材避重和动态镜头时长",
            "director_version": VERSION,
        })
        previous = aid
        cursor += duration
    output[-1]["duration"] = round(output[-1]["duration"] + target_duration - sum(_float(item.get("duration")) for item in output), 3)
    output[-1]["duration_seconds"] = output[-1]["duration"]
    if any(str(item.get("source") or "").lower() != "r2" or not _asset_url(item) for item in output):
        raise ValueError("AI 剪辑导演生成了未绑定 R2 URL 的镜头")
    report = {
        "version": VERSION,
        "input_clip_count": len(candidates),
        "output_clip_count": len(output),
        "target_duration_seconds": round(target_duration, 3),
        "timeline_duration_seconds": round(sum(_float(item.get("duration")) for item in output), 3),
        "average_clip_seconds": round(target_duration / max(1, len(output)), 3),
        "minimum_clip_seconds": round(min(_float(item.get("duration")) for item in output), 3),
        "maximum_clip_seconds": round(max(_float(item.get("duration")) for item in output), 3),
        "hook_clip_count": sum(1 for item in output if item.get("pace_role") == "hook"),
        "semantic_switches": switches,
        "consecutive_same_asset_count": sum(1 for a, b in zip(output, output[1:]) if _asset_id(a) == _asset_id(b)),
        "dynamic_rhythm": True,
        "hard_cut_default": True,
        "universal_fade_removed": True,
    }
    return output, report


def _validate_ai(payload: dict[str, Any], timings: Sequence[dict[str, Any]]) -> tuple[dict[int, list[str]], list[str], dict[int, list[str]]]:
    units: dict[int, list[str]] = {}
    timing_text = {index: _canonical(item.get("text") or "") for index, item in enumerate(timings, start=1) if isinstance(item, dict)}
    for item in payload.get("subtitle_segments") or []:
        if not isinstance(item, dict):
            continue
        index = int(_float(item.get("segment_index"), 0))
        values = [_display(value) for value in item.get("units") or [] if _display(value)]
        if index in timing_text and values and "".join(values) == timing_text[index]:
            units[index] = values
    keywords = []
    for item in payload.get("keywords") or []:
        word = item.get("word") or item.get("value") if isinstance(item, dict) else item
        clean = _display(word)
        if 2 <= len(clean) <= 10 and clean not in keywords:
            keywords.append(clean)
    preferred: dict[int, list[str]] = {}
    for item in payload.get("visual_intents") or []:
        if not isinstance(item, dict):
            continue
        cue_index = int(_float(item.get("cue_index"), 0))
        ids = [str(value).strip() for value in item.get("preferred_asset_ids") or [] if str(value).strip()]
        if cue_index > 0 and ids:
            preferred[cue_index] = ids
    return units, keywords[:18], preferred


async def _ai_proposal(settings: Any, timings: Sequence[dict[str, Any]], clips: Sequence[dict[str, Any]]) -> tuple[dict[int, list[str]], list[str], dict[int, list[str]], dict[str, Any]]:
    if settings is None:
        return {}, [], {}, {"ai_used": False, "fallback_reason": "settings unavailable"}
    try:
        from app.services.deepseek import _chat_json
        timing_data = [{"segment_index": index, "text": str(item.get("text") or ""), "start": item.get("start", item.get("start_time")), "end": item.get("end", item.get("end_time"))} for index, item in enumerate(timings, start=1) if isinstance(item, dict)]
        clip_data = [{"asset_id": _asset_id(item), "title": str(item.get("title") or ""), "scene": str(item.get("scene") or ""), "description": str(item.get("description") or item.get("analysis_description") or "")} for item in clips[:32] if isinstance(item, dict)]
        system = "你是短视频字幕导演和剪辑导演。必须输出严格 JSON。不能改写、增删或调换口播文字。每个字幕段 units 拼接后必须与原文去除标点空格后完全一致。"
        user = f'''真实 TTS 分段：\n{json.dumps(timing_data, ensure_ascii=False)}\n\n可用 R2 素材：\n{json.dumps(clip_data, ensure_ascii=False)}\n\n要求：字幕每屏通常 8-18 字、最多两行；不拆开地名项目名、第一眼、吉隆坡房子、自住还是投资、真实持有成本、转手难度；每段最多一个强重点和一个次重点；画面意图必须具体。\n输出 JSON：{{"subtitle_segments":[{{"segment_index":1,"units":["原文字幕块"]}}],"keywords":[{{"word":"重点词"}}],"visual_intents":[{{"cue_index":1,"intent":"具体画面","preferred_asset_ids":["素材ID"]}}]}}'''
        proposal = await asyncio.wait_for(_chat_json(settings, system, user, temperature=0.28, timeout=55), timeout=65)
        units, keywords, preferred = _validate_ai(proposal, timings)
        return units, keywords, preferred, {"ai_used": True, "valid_ai_segment_count": len(units), "ai_keyword_count": len(keywords), "ai_visual_intent_count": len(preferred)}
    except Exception as exc:
        return {}, [], {}, {"ai_used": False, "fallback_reason": str(exc)[:500]}


async def direct_existing_video(
    *,
    settings: Any,
    payload: dict[str, Any],
    timings: Sequence[dict[str, Any]],
    clips: Sequence[dict[str, Any]],
    target_duration: float,
) -> dict[str, Any]:
    enabled = _bool(payload.get("ai_subtitle_director"), True) or _bool(payload.get("ai_edit_director"), True)
    if enabled:
        ai_units, ai_keywords, preferred, ai_report = await _ai_proposal(settings, timings, clips)
    else:
        ai_units, ai_keywords, preferred, ai_report = {}, [], {}, {"ai_used": False, "fallback_reason": "disabled by payload"}
    subtitle_segments, subtitle_report = _subtitle_plan(timings, target_duration=target_duration, ai_units=ai_units, ai_keywords=ai_keywords)
    directed_clips, edit_report = _edit_plan(clips, subtitle_segments, target_duration=target_duration, pace=str(payload.get("edit_pace") or "normal"), preferred=preferred)
    all_keywords: list[str] = []
    seen: set[str] = set()
    for value in [*ai_keywords, *[word for cue in subtitle_segments for word in cue.get("keywords") or []]]:
        clean = _display(value)
        if clean and clean.lower() not in seen:
            seen.add(clean.lower())
            all_keywords.append(clean)
    requested = payload.get("subtitle_style") if isinstance(payload.get("subtitle_style"), dict) else {}
    style = {
        **requested,
        "font_size": max(96, int(_float(requested.get("font_size"), 100))),
        "outline": max(7, int(_float(requested.get("outline"), 8))),
        "shadow": max(2, int(_float(requested.get("shadow"), 2))),
        "margin_v": max(260, int(_float(requested.get("margin_v"), 300))),
        "max_chars": min(11, max(8, int(_float(requested.get("max_chars"), 10)))),
        "max_lines": 2,
        "bold": True,
        "dynamic_font_size": True,
        "strong_keyword_scale": 1.22,
    }
    return {
        "ok": True,
        "version": VERSION,
        "director_marker": DIRECTOR_MARKER,
        "subtitle_segments": subtitle_segments,
        "subtitle_keywords": all_keywords[:20],
        "subtitle_style": style,
        "clips": directed_clips,
        "subtitle_report": {**subtitle_report, **ai_report},
        "edit_report": edit_report,
        "report": {"version": VERSION, "ai": ai_report, "subtitle": subtitle_report, "edit": edit_report},
    }


def _ass_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds or 0))
    total_cs = int(round(seconds * 100))
    hours, remainder = divmod(total_cs, 360000)
    minutes, remainder = divmod(remainder, 6000)
    secs, cs = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"


def _ass_color(value: Any, default: str) -> str:
    text = str(value or default).strip()
    if text.startswith("&H"):
        return text if text.endswith("&") else text + "&"
    if re.fullmatch(r"#[0-9A-Fa-f]{6}", text):
        return "&H00" + text[5:7] + text[3:5] + text[1:3] + "&"
    return default


def _highlight(line: str, keywords: Sequence[str], strong: str, size: int, primary: str, accent: str) -> str:
    value = _display(line).replace("{", "（").replace("}", "）").replace("\\", "＼")
    ordered = []
    if _display(strong):
        ordered.append(_display(strong))
    for word in keywords:
        clean = _display(word)
        if clean and clean not in ordered:
            ordered.append(clean)
    for word in sorted(ordered[:2], key=len, reverse=True):
        if word not in value:
            continue
        scale = 1.22 if word == _display(strong) else 1.10
        word_size = min(132, int(size * scale))
        tag = r"{\1c" + accent + r"\fs" + str(word_size) + r"\b1}"
        reset = r"{\1c" + primary + r"\fs" + str(size) + r"\b1}"
        value = value.replace(word, tag + word + reset, 1)
    return value


def _ffmpeg_path(path: Path) -> str:
    return str(path).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def _build_ass(segments: Sequence[dict[str, Any]], subtitle_style: dict[str, Any], keywords: Sequence[str], prefix: str) -> Path:
    backend_dir = Path(os.getenv("AI_VIDEO_BACKEND_DIR", "/opt/ai-video/backend"))
    work_dir = backend_dir / "data" / "subtitle-edit-director"
    work_dir.mkdir(parents=True, exist_ok=True)
    ass_path = work_dir / f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.ass"
    font = os.getenv("AI_VIDEO_SUBTITLE_FONT", "Noto Sans CJK SC")
    base_size = max(84, min(128, int(_float(subtitle_style.get("font_size"), 100))))
    outline = max(5, min(14, int(_float(subtitle_style.get("outline"), 8))))
    shadow = max(0, min(6, int(_float(subtitle_style.get("shadow"), 2))))
    margin_v = max(180, min(480, int(_float(subtitle_style.get("margin_v"), 300))))
    primary = _ass_color(subtitle_style.get("ass_primary") or subtitle_style.get("primary"), "&H00FFFFFF&")
    outline_color = _ass_color(subtitle_style.get("ass_outline") or "#000000", "&H00000000&")
    back = _ass_color(subtitle_style.get("ass_back") or "&H00000000", "&H00000000&")
    accent = _ass_color(subtitle_style.get("accent") or "#FFE45C", "&H005CE4FF&")
    header = f'''[Script Info]\nScriptType: v4.00+\nWrapStyle: 0\nScaledBorderAndShadow: yes\nPlayResX: 1080\nPlayResY: 1920\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,{font},{base_size},{primary},&H00FFFFFF&,{outline_color},{back},-1,0,0,0,100,100,0,0,1,{outline},{shadow},2,72,72,{margin_v},1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'''
    lines = [header]
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        start, end = _float(segment.get("start")), _float(segment.get("end"))
        if end <= start:
            continue
        cue_size = max(84, min(118, int(_float(segment.get("font_size"), base_size))))
        cue_keywords = [_display(x) for x in (segment.get("keywords") or keywords) if _display(x)]
        strong = _display(segment.get("strong_keyword") or "")
        display_lines = [_display(x) for x in (segment.get("display_lines") or [segment.get("text") or ""]) if _display(x)][:2]
        if not display_lines:
            continue
        rendered = [_highlight(line, cue_keywords, strong, cue_size, primary, accent) for line in display_lines]
        prefix_tag = r"{\an2\b1\fs" + str(cue_size) + r"\1c" + primary + r"\bord" + str(outline) + r"\shad" + str(shadow) + r"\fad(45,45)}"
        rendered_text = r"\N".join(rendered)
        lines.append(
            f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},"
            f"Default,,0,0,0,,{prefix_tag}{rendered_text}\n"
        )
    ass_path.write_text("".join(lines), encoding="utf-8")
    return ass_path


def burn_directed_subtitles_with_upload(
    *, video_url: str = "", video_path: str = "", text: str = "",
    segments: Sequence[dict[str, Any]] | None = None, duration: float | None = None,
    style_id: str = "douyin_pop", keywords: Sequence[str] | None = None,
    prefix: str = "a9_directed_subtitle", object_key: str = "",
    subtitle_style: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not video_path:
        raise ValueError("A9 字幕导演当前生产链路必须传入本地视频路径")
    source = Path(video_path)
    if not source.exists():
        raise FileNotFoundError(f"视频文件不存在：{source}")
    if not segments:
        raise ValueError("A9 字幕导演没有收到真实 TTS 字幕段")
    style = dict(subtitle_style or {})
    ass_path = _build_ass(segments, style, list(keywords or []), prefix)
    backend_dir = Path(os.getenv("AI_VIDEO_BACKEND_DIR", "/opt/ai-video/backend"))
    output_dir = backend_dir / "data" / "subtitle-edit-director"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.mp4"
    command = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(source), "-vf", f"ass='{_ffmpeg_path(ass_path)}'", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-c:a", "copy", "-movflags", "+faststart", str(output_path)]
    process = subprocess.run(command, capture_output=True, text=True, timeout=1200, check=False)
    if process.returncode != 0:
        raise RuntimeError((process.stderr or process.stdout or "A9 ASS 字幕烧录失败")[-4000:])
    if not object_key:
        object_key = f"videos/existing-edit/subtitled/{time.strftime('%Y/%m/%d')}/{uuid.uuid4().hex}_{output_path.name}"
    from app.services.subtitle_provider import upload_file_to_r2
    upload = upload_file_to_r2(output_path, object_key=object_key)
    url = str(upload.get("url") or "")
    if not url:
        raise RuntimeError("A9 字幕成片上传 R2 后没有返回 URL")
    return {"ok": True, "version": VERSION, "video_url": url, "url": url, "style_id": style_id, "style": style, "duration": duration, "cues": list(segments), "ass_path": str(ass_path), "output_path": str(output_path), "r2": upload, "director_marker": DIRECTOR_MARKER}

# =====================================================================
# V10.40.8.8 A10 KEYWORD BURST + EDIT QUALITY DIRECTOR
# =====================================================================

_A9_DIRECT_EXISTING_VIDEO = direct_existing_video
_A9_BUILD_ASS = _build_ass

VERSION = "10.40.8.8-a10-r2"
DIRECTOR_MARKER = "keyword_burst_edit_quality_v10_40_8_8_a10_r2"

_A10_BURST_PHRASES = (
    "第一句就问价格",
    "只看价格",
    "别只看价格",
    "区域成熟度",
    "开发商是否靠谱",
    "开发商靠不靠谱",
    "自住还是投资",
    "二手市场流动性",
    "真实持有成本",
    "物业维护成本",
    "交付周期",
    "转手难度",
    "风险也大",
    "容易买错",
    "很容易买错",
    "先想清楚",
    "再去看房",
    "价格",
    "开发商",
    "用途",
    "流动性",
    "持有成本",
    "风险",
)
_A10_RISK_WORDS = (
    "风险",
    "买错",
    "不稳",
    "烂尾",
    "空置",
    "转手难",
    "维护成本",
)
_A10_ACTION_WORDS = (
    "别只看",
    "不要只看",
    "先想清楚",
    "再去看房",
    "一定要",
)


def _a10_character_boundaries(
    text: str,
    start: float,
    end: float,
) -> list[float]:
    value = _display(text)
    if not value:
        return [round(start, 3), round(end, 3)]
    duration = max(0.04, end - start)
    weights: list[float] = []
    for char in value:
        if char.isdigit():
            weight = 1.08
        elif char.isascii():
            weight = 0.86
        else:
            weight = 1.0
        weights.append(weight)
    total = sum(weights) or 1.0
    result = [start]
    cursor = start
    for weight in weights:
        cursor += duration * weight / total
        result.append(cursor)
    result[-1] = end
    return [round(item, 3) for item in result]


def _a10_native_word_items(
    timing: dict[str, Any],
) -> list[dict[str, Any]]:
    raw = (
        timing.get("word_timings")
        or timing.get("words")
        or timing.get("word_timestamps")
        or timing.get("char_timings")
        or []
    )
    output: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return output
    for item in raw:
        if not isinstance(item, dict):
            continue
        word = _display(
            item.get("word")
            or item.get("text")
            or item.get("char")
            or ""
        )
        if not word:
            continue
        start = (
            _float(item.get("start_ms")) / 1000.0
            if item.get("start_ms") is not None
            else _float(
                item.get("start")
                if item.get("start") is not None
                else item.get("start_time")
            )
        )
        end = (
            _float(item.get("end_ms")) / 1000.0
            if item.get("end_ms") is not None
            else _float(
                item.get("end")
                if item.get("end") is not None
                else item.get("end_time"),
                start,
            )
        )
        if end <= start:
            continue
        output.append(
            {
                "word": word,
                "start": round(start, 3),
                "end": round(end, 3),
                "source": "tts_native",
            }
        )
    return output


def _a10_timeline_for_cue(
    cue: dict[str, Any],
    original_timings: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    text = _display(
        cue.get("text")
        or cue.get("subtitle_text")
        or ""
    )
    start = _float(cue.get("start"))
    end = _float(cue.get("end"), start)
    if not text or end <= start:
        return []

    segment_index = int(
        _float(cue.get("segment_index"), 0)
    )
    if 1 <= segment_index <= len(original_timings):
        source_timing = original_timings[
            segment_index - 1
        ]
        if isinstance(source_timing, dict):
            native = _a10_native_word_items(
                source_timing
            )
            if native:
                selected = [
                    item
                    for item in native
                    if item["end"] >= start - 0.04
                    and item["start"] <= end + 0.04
                ]
                if selected:
                    return selected

    boundaries = _a10_character_boundaries(
        text,
        start,
        end,
    )
    return [
        {
            "word": char,
            "start": boundaries[index],
            "end": boundaries[index + 1],
            "source": "tts_segment_forced",
        }
        for index, char in enumerate(text)
    ]


def _a10_keyword_timing(
    cue: dict[str, Any],
    keyword: str,
) -> tuple[float, float, str]:
    text = _display(
        cue.get("text")
        or cue.get("subtitle_text")
        or ""
    )
    word = _display(keyword)
    cue_start = _float(
        cue.get("start")
    )
    cue_end = _float(
        cue.get("end"),
        cue_start,
    )
    position = text.find(word)

    timeline = [
        item
        for item in (
            cue.get("word_timeline")
            or []
        )
        if isinstance(item, dict)
        and _display(
            item.get("word")
            or item.get("text")
            or ""
        )
    ]

    if (
        position >= 0
        and word
        and timeline
    ):
        assembled = ""
        spans: list[
            tuple[
                int,
                int,
                dict[str, Any],
            ]
        ] = []

        for item in timeline:
            token = _display(
                item.get("word")
                or item.get("text")
                or ""
            )
            token_start = len(
                assembled
            )
            assembled += token
            spans.append(
                (
                    token_start,
                    len(assembled),
                    item,
                )
            )

        end_position = (
            position + len(word)
        )
        matched = [
            item
            for token_start, token_end, item
            in spans
            if (
                token_end > position
                and token_start < end_position
            )
        ]

        if matched:
            word_start = _float(
                matched[0].get(
                    "start"
                ),
                cue_start,
            )
            spoken_end = _float(
                matched[-1].get(
                    "end"
                ),
                word_start,
            )
            visual_duration = max(
                0.58,
                min(
                    1.05,
                    spoken_end
                    - word_start
                    + 0.16,
                ),
            )
            visual_end = min(
                cue_end,
                word_start
                + visual_duration,
            )
            source = (
                "tts_native"
                if all(
                    item.get("source")
                    == "tts_native"
                    for item in matched
                )
                else "tts_segment_forced"
            )
            return (
                round(
                    word_start,
                    3,
                ),
                round(
                    visual_end,
                    3,
                ),
                source,
            )

    if position < 0 or not word:
        midpoint = (
            cue_start
            + (
                cue_end - cue_start
            )
            * 0.5
        )
        return (
            round(
                midpoint,
                3,
            ),
            round(
                min(
                    cue_end,
                    midpoint + 0.62,
                ),
                3,
            ),
            "cue_midpoint_fallback",
        )

    boundaries = (
        _a10_character_boundaries(
            text,
            cue_start,
            cue_end,
        )
    )
    word_start = boundaries[
        position
    ]
    spoken_end = boundaries[
        min(
            len(text),
            position + len(word),
        )
    ]
    visual_duration = max(
        0.58,
        min(
            1.05,
            spoken_end
            - word_start
            + 0.16,
        ),
    )
    return (
        round(
            word_start,
            3,
        ),
        round(
            min(
                cue_end,
                word_start
                + visual_duration,
            ),
            3,
        ),
        "tts_segment_forced",
    )


def _a10_burst_category(word: str) -> str:
    value = _display(word)
    if re.search(r"\d", value):
        return "number"
    if any(
        item in value
        for item in _A10_RISK_WORDS
    ):
        return "risk"
    if any(
        item in value
        for item in _A10_ACTION_WORDS
    ):
        return "action"
    return "decision"


def _a10_candidate_score(
    word: str,
    cue: dict[str, Any],
    cue_index: int,
) -> int:
    value = _display(word)
    score = min(14, len(value)) * 4
    if value in _A10_BURST_PHRASES:
        score += 60
    if re.search(r"\d", value):
        score += 45
    if any(
        item in value
        for item in _A10_RISK_WORDS
    ):
        score += 40
    if any(
        item in value
        for item in _A10_ACTION_WORDS
    ):
        score += 34
    if cue_index <= 2:
        score += 18
    if cue.get("strong_keyword") == value:
        score += 30
    return score


def _a10_build_keyword_bursts(
    cues: Sequence[dict[str, Any]],
    original_timings: Sequence[dict[str, Any]],
    target_duration: float,
    payload: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    requested = int(
        _float(
            payload.get("keyword_burst_count"),
            round(
                max(
                    1.0,
                    target_duration,
                )
                / 5.0
            ),
        )
    )
    target_count = max(
        4,
        min(10, requested),
    )
    candidates: list[dict[str, Any]] = []

    for cue_index, cue in enumerate(
        cues,
        start=1,
    ):
        text = _display(
            cue.get("text")
            or ""
        )
        if not text:
            continue
        words: list[str] = []
        strong = _display(
            cue.get("strong_keyword")
            or ""
        )
        if strong:
            words.append(strong)
        words.extend(
            _display(item)
            for item in (
                cue.get("keywords")
                or []
            )
            if _display(item)
        )
        for phrase in _A10_BURST_PHRASES:
            if phrase in text:
                words.append(phrase)
        for match in re.finditer(
            r"(?:RM|人民币|美元|马币)?"
            r"\d+(?:\.\d+)?"
            r"(?:万|千|亿|%|年|个月|套|层)?",
            text,
            re.I,
        ):
            words.append(
                match.group(0)
            )

        seen: set[str] = set()
        for word in words:
            clean = _display(word)
            if (
                not clean
                or clean in seen
                or clean not in text
                or len(clean) > 12
            ):
                continue
            seen.add(clean)
            (
                burst_start,
                burst_end,
                timing_source,
            ) = _a10_keyword_timing(
                cue,
                clean,
            )
            candidates.append(
                {
                    "text": clean,
                    "start": burst_start,
                    "end": burst_end,
                    "cue_index": int(
                        cue.get("index")
                        or cue_index
                    ),
                    "segment_index": int(
                        cue.get("segment_index")
                        or 0
                    ),
                    "category": (
                        _a10_burst_category(
                            clean
                        )
                    ),
                    "score": (
                        _a10_candidate_score(
                            clean,
                            cue,
                            cue_index,
                        )
                    ),
                    "timing_source": (
                        timing_source
                    ),
                    "director_version": VERSION,
                }
            )

    selected: list[dict[str, Any]] = []
    for candidate in sorted(
        candidates,
        key=lambda item: (
            -int(item["score"]),
            float(item["start"]),
            -len(str(item["text"])),
        ),
    ):
        if any(
            candidate["text"]
            == item["text"]
            or abs(
                candidate["start"]
                - item["start"]
            )
            < 2.35
            for item in selected
        ):
            continue
        selected.append(candidate)
        if len(selected) >= target_count:
            break

    early = [
        item
        for item in candidates
        if float(item["start"]) <= 4.0
    ]
    if (
        early
        and not any(
            float(item["start"]) <= 4.0
            for item in selected
        )
    ):
        hook = max(
            early,
            key=lambda item: int(
                item["score"]
            ),
        )
        if selected:
            selected[-1] = hook
        else:
            selected.append(hook)

    selected.sort(
        key=lambda item: float(
            item["start"]
        )
    )
    for index, item in enumerate(
        selected,
        start=1,
    ):
        item["index"] = index
        item["duration"] = round(
            max(
                0.0,
                float(item["end"])
                - float(item["start"]),
            ),
            3,
        )
        item["animation"] = (
            "pop_overshoot_settle"
        )
        item["scale_in"] = 0.62
        item["scale_peak"] = 1.42
        item["scale_settle"] = 1.12

    report = {
        "version": VERSION,
        "enabled": _bool(
            payload.get(
                "keyword_burst_enabled"
            ),
            True,
        ),
        "target_count": target_count,
        "burst_count": len(selected),
        "first_burst_seconds": (
            round(
                float(
                    selected[0]["start"]
                ),
                3,
            )
            if selected
            else None
        ),
        "minimum_spacing_seconds": (
            round(
                min(
                    float(
                        current["start"]
                    )
                    - float(
                        previous["start"]
                    )
                    for previous, current
                    in zip(
                        selected,
                        selected[1:],
                    )
                ),
                3,
            )
            if len(selected) > 1
            else None
        ),
        "categories": {
            category: sum(
                1
                for item in selected
                if item["category"]
                == category
            )
            for category in (
                "decision",
                "risk",
                "number",
                "action",
            )
        },
        "independent_ass_layer": True,
        "cut_sync_requested": True,
    }
    return selected, report


def _a10_quality_score(
    candidate: dict[str, Any],
) -> float:
    score = _float(
        candidate.get("quality_score"),
        70.0,
    )
    blur = _float(
        candidate.get("blur_score"),
        0.0,
    )
    shake = _float(
        candidate.get("shake_score"),
        0.0,
    )
    exposure = _float(
        candidate.get("exposure_score"),
        70.0,
    )
    score += max(
        -20.0,
        min(
            15.0,
            (exposure - 60.0) * 0.25,
        ),
    )
    score -= max(
        0.0,
        blur,
    ) * 0.35
    score -= max(
        0.0,
        shake,
    ) * 0.45
    if candidate.get("low_quality") is True:
        score -= 35.0
    return score


def _a10_unique_candidates(
    clips: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in clips:
        if not isinstance(item, dict):
            continue
        if (
            str(
                item.get("source")
                or ""
            ).lower()
            != "r2"
        ):
            continue
        if not _asset_url(item):
            continue
        key = (
            _asset_id(item)
            or _asset_url(item)
        )
        if key in seen:
            continue
        seen.add(key)
        output.append(
            dict(item)
        )
    return output


def _a10_merge_candidates(
    *groups: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in groups:
        for item in _a10_unique_candidates(group):
            key = _asset_id(item) or _asset_url(item)
            if not key or key in seen:
                continue
            seen.add(key)
            output.append(dict(item))
    return output


def _a10_boundaries(
    target_duration: float,
    desired_count: int,
    cues: Sequence[dict[str, Any]],
    bursts: Sequence[dict[str, Any]],
) -> tuple[list[float], list[float], list[float]]:
    target = max(
        1.0,
        float(target_duration),
    )
    min_shot = 0.72
    max_shot = 2.75
    desired = max(
        1,
        min(28, desired_count),
    )
    hard = [
        float(item["start"])
        for item in bursts
        if (
            min_shot
            <= float(item["start"])
            <= target - min_shot
        )
    ]
    soft = [
        _float(item.get("start"))
        for item in cues
        if (
            min_shot
            <= _float(
                item.get("start")
            )
            <= target - min_shot
        )
    ]
    boundaries = [0.0, target]
    accepted_burst_starts: list[float] = []
    skipped_burst_starts: list[float] = []

    def can_add(value: float) -> bool:
        ordered = sorted(
            boundaries + [value]
        )
        return all(
            current - previous
            >= min_shot - 1e-6
            for previous, current
            in zip(
                ordered,
                ordered[1:],
            )
        )

    for value in sorted(
        set(
            round(item, 3)
            for item in hard
        )
    ):
        if can_add(value):
            boundaries.append(value)
            accepted_burst_starts.append(value)
        else:
            skipped_burst_starts.append(value)

    for value in sorted(
        set(
            round(item, 3)
            for item in soft
        )
    ):
        if len(boundaries) - 1 >= desired:
            break
        if can_add(value):
            boundaries.append(value)

    while True:
        boundaries.sort()
        gaps = [
            (
                boundaries[index + 1]
                - boundaries[index],
                index,
            )
            for index in range(
                len(boundaries) - 1
            )
        ]
        largest, index = max(gaps)
        if (
            (
                len(boundaries) - 1
                >= desired
                and largest <= max_shot
            )
            or largest < 2 * min_shot
        ):
            break
        left = boundaries[index]
        split = round(
            left
            + largest
            * (
                0.48
                if index % 2 == 0
                else 0.52
            ),
            3,
        )
        if not can_add(split):
            break
        boundaries.append(split)
        if len(boundaries) - 1 >= 28:
            break

    boundaries = sorted(
        round(item, 3)
        for item in boundaries
    )
    boundaries[-1] = round(
        target,
        3,
    )
    return (
        boundaries,
        sorted(accepted_burst_starts),
        sorted(skipped_burst_starts),
    )


def _a10_select_asset(
    candidates: Sequence[dict[str, Any]],
    cue_text: str,
    previous_asset: str,
    reuse: dict[str, int],
    interval_index: int,
) -> dict[str, Any]:
    cue_tokens = _tokens(cue_text)
    ranked: list[
        tuple[float, dict[str, Any]]
    ] = []
    for candidate in candidates:
        asset_id = (
            _asset_id(candidate)
            or _asset_url(candidate)
        )
        candidate_text = _clip_text(
            candidate
        ).lower()
        overlap = len(
            cue_tokens
            & _tokens(candidate_text)
        )
        contains = sum(
            1
            for token in cue_tokens
            if (
                token
                and token
                in candidate_text
            )
        )
        score = (
            overlap * 12.0
            + contains * 4.0
            + _float(
                candidate.get(
                    "match_score"
                )
            )
            * 0.18
            + _a10_quality_score(
                candidate
            )
            * 0.25
            - reuse.get(
                asset_id,
                0,
            )
            * 18.0
        )
        if (
            asset_id == previous_asset
            and len(candidates) > 1
        ):
            score -= 180.0
        if (
            candidate.get(
                "manual_locked"
            )
            and reuse.get(
                asset_id,
                0,
            )
            == 0
        ):
            score += 32.0
        stable = (
            sum(
                ord(char)
                for char in asset_id
            )
            % 101
        )
        score += (
            (
                stable
                + interval_index * 17
            )
            % 101
        ) * 0.001
        ranked.append(
            (
                score,
                candidate,
            )
        )
    ranked.sort(
        key=lambda item: item[0],
        reverse=True,
    )
    if previous_asset and len(candidates) > 1:
        for _, candidate in ranked:
            candidate_id = (
                _asset_id(candidate)
                or _asset_url(candidate)
            )
            if candidate_id != previous_asset:
                return dict(candidate)
    return dict(ranked[0][1])


def _a10_edit_timeline(
    input_clips: Sequence[dict[str, Any]],
    base_clips: Sequence[dict[str, Any]],
    cues: Sequence[dict[str, Any]],
    bursts: Sequence[dict[str, Any]],
    target_duration: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    candidates = _a10_merge_candidates(
        input_clips,
        base_clips,
    )
    if not candidates:
        raise ValueError(
            "A10 剪辑导演没有可用的 R2 候选素材"
        )

    candidate_count = len(candidates)
    if candidate_count == 1:
        desired = min(
            12,
            max(
                len(cues),
                int(round(max(1.0, target_duration) / 3.6)),
            ),
        )
    elif candidate_count <= 3:
        desired = min(
            18,
            max(
                len(cues),
                int(round(max(1.0, target_duration) / 2.25)),
            ),
        )
    else:
        desired = max(
            len(base_clips),
            min(
                26,
                int(round(max(1.0, target_duration) / 1.72)),
            ),
        )

    (
        boundaries,
        synchronized_burst_starts,
        overlay_only_burst_starts,
    ) = _a10_boundaries(
        target_duration,
        desired,
        cues,
        bursts,
    )
    output: list[
        dict[str, Any]
    ] = []
    reuse: dict[str, int] = {}
    previous_asset = ""
    burst_starts = [
        float(item["start"])
        for item in bursts
    ]
    synchronized_start_set = {
        round(item, 3)
        for item in synchronized_burst_starts
    }

    for index, (left, right) in enumerate(
        zip(
            boundaries,
            boundaries[1:],
        ),
        start=1,
    ):
        duration = round(
            right - left,
            3,
        )
        midpoint = (
            left + duration / 2
        )
        cue = _cue_at(
            cues,
            midpoint,
        )
        cue_text = str(
            cue.get("text")
            or ""
        )
        selected = _a10_select_asset(
            candidates,
            cue_text,
            previous_asset,
            reuse,
            index,
        )
        asset_id = (
            _asset_id(selected)
            or _asset_url(selected)
        )
        use_index = reuse.get(
            asset_id,
            0,
        )
        reuse[asset_id] = (
            use_index + 1
        )
        source_base = max(
            0.12,
            _float(
                selected.get(
                    "start_time"
                ),
                0.0,
            ),
        )
        source_start = (
            source_base
            + use_index
            * (
                duration * 1.43
                + 0.61
            )
        )
        source_duration = _float(
            selected.get(
                "source_duration"
            )
            or selected.get(
                "media_duration"
            )
            or selected.get(
                "asset_duration"
            ),
            0.0,
        )
        if (
            source_duration
            > duration + 0.3
        ):
            max_start = max(
                0.1,
                source_duration
                - duration
                - 0.15,
            )
            source_start = min(
                source_start,
                max_start,
            )

        burst = next(
            (
                item
                for item in bursts
                if (
                    round(float(item["start"]), 3)
                    in synchronized_start_set
                    and abs(float(item["start"]) - left) <= 0.035
                )
            ),
            None,
        )
        if left < 3.0:
            role = "hook"
        elif (
            right
            >= target_duration - 2.5
        ):
            role = "conclusion"
        elif burst:
            role = "keyword_impact"
        else:
            role = "body"

        output.append(
            {
                **selected,
                "id": (
                    f"a10_clip_"
                    f"{index:02d}"
                ),
                "index": index,
                "source": "r2",
                "asset_id": asset_id,
                "asset_ids": [
                    asset_id
                ],
                "asset_url": _asset_url(
                    selected
                ),
                "duration": duration,
                "duration_seconds": (
                    duration
                ),
                "timeline_start": round(
                    left,
                    3,
                ),
                "timeline_end": round(
                    right,
                    3,
                ),
                "start_time": round(
                    source_start,
                    3,
                ),
                "end_time": round(
                    source_start
                    + duration,
                    3,
                ),
                "narration": cue_text,
                "cue_index": int(
                    cue.get("index")
                    or 0
                ),
                "pace_role": role,
                "transition": (
                    "关键词冲击硬切"
                    if burst
                    else "直接切"
                ),
                "camera": (
                    "关键词同步轻推"
                    if burst
                    else "保留原片运镜"
                ),
                "keyword_burst": (
                    dict(burst)
                    if burst
                    else None
                ),
                "cut_reason": (
                    (
                        f"爆词「"
                        f"{burst['text']}」"
                        "同步切点"
                    )
                    if burst
                    else (
                        f"口播语义「"
                        f"{cue_text[:18]}」"
                    )
                ),
                "quality_score": round(
                    _a10_quality_score(
                        selected
                    ),
                    2,
                ),
                "director_version": VERSION,
            }
        )
        previous_asset = asset_id

    duration_sum = round(
        sum(
            float(
                item["duration"]
            )
            for item in output
        ),
        3,
    )
    consecutive = sum(
        1
        for previous, current
        in zip(
            output,
            output[1:],
        )
        if (
            previous["asset_id"]
            == current["asset_id"]
        )
    )
    selected_assets = {
        item["asset_id"]
        for item in output
    }
    alignment_errors = []
    timeline_boundaries = [
        float(item["timeline_start"])
        for item in output
    ]
    for burst_start in synchronized_burst_starts:
        alignment_errors.append(
            min(
                abs(boundary - burst_start)
                for boundary in timeline_boundaries
            )
        )
    max_alignment = max(
        alignment_errors,
        default=0.0,
    )
    low_quality = sum(
        1
        for item in output
        if float(
            item.get(
                "quality_score"
            )
            or 0.0
        )
        < 42.0
    )
    hard_failures: list[str] = []
    if (
        abs(
            duration_sum
            - target_duration
        )
        > 0.03
    ):
        hard_failures.append(
            "timeline_duration_mismatch"
        )
    if any(
        not item.get("asset_url")
        for item in output
    ):
        hard_failures.append(
            "missing_r2_url"
        )
    if (
        consecutive
        and len(candidates) > 1
    ):
        hard_failures.append(
            "consecutive_same_asset"
        )
    if max_alignment > 0.08:
        hard_failures.append(
            "keyword_cut_alignment"
        )

    quality_gate = {
        "version": VERSION,
        "passed": not hard_failures,
        "hard_failures": hard_failures,
        "warnings": (
            ["single_asset_pool_reused"]
            if len(candidates) == 1
            else []
        )
        + (
            ["asset_diversity_low"]
            if (
                len(candidates) > 1
                and len(selected_assets) < min(4, len(candidates))
            )
            else []
        )
        + (
            ["keyword_overlay_without_cut"]
            if overlay_only_burst_starts
            else []
        )
        + (
            ["low_quality_clip_selected"]
            if low_quality
            else []
        ),
        "shot_count": len(output),
        "timeline_duration_seconds": (
            duration_sum
        ),
        "minimum_shot_seconds": round(
            min(
                float(
                    item["duration"]
                )
                for item in output
            ),
            3,
        ),
        "maximum_shot_seconds": round(
            max(
                float(
                    item["duration"]
                )
                for item in output
            ),
            3,
        ),
        "average_shot_seconds": round(
            target_duration
            / max(
                1,
                len(output),
            ),
            3,
        ),
        "unique_asset_count": len(
            selected_assets
        ),
        "candidate_asset_count": len(
            candidates
        ),
        "consecutive_same_asset_count": (
            consecutive
        ),
        "low_quality_selected_count": (
            low_quality
        ),
        "keyword_cut_max_error_seconds": round(
            max_alignment,
            3,
        ),
        "keyword_cut_requested_count": len(burst_starts),
        "keyword_cut_sync_count": sum(
            1
            for item in output
            if item.get("keyword_burst")
        ),
        "keyword_overlay_only_count": len(overlay_only_burst_starts),
        "candidate_pool_merged": True,
        "single_asset_graceful_fallback": len(candidates) == 1,
        "forced_no_repeat": len(candidates) > 1,
        "hook_shot_count": sum(
            1
            for item in output
            if item.get(
                "pace_role"
            )
            == "hook"
        ),
        "universal_fade_removed": True,
    }
    if hard_failures:
        raise ValueError(
            "A10 剪辑质量门禁失败："
            + "、".join(
                hard_failures
            )
        )
    return output, quality_gate


async def direct_existing_video(
    *,
    settings: Any,
    payload: dict[str, Any],
    timings: Sequence[dict[str, Any]],
    clips: Sequence[dict[str, Any]],
    target_duration: float,
) -> dict[str, Any]:
    base = await _A9_DIRECT_EXISTING_VIDEO(
        settings=settings,
        payload=payload,
        timings=timings,
        clips=clips,
        target_duration=target_duration,
    )
    cues = [
        dict(item)
        for item in (
            base.get(
                "subtitle_segments"
            )
            or []
        )
    ]
    for cue in cues:
        cue["word_timeline"] = (
            _a10_timeline_for_cue(
                cue,
                timings,
            )
        )

    enabled = _bool(
        payload.get(
            "keyword_burst_enabled"
        ),
        True,
    )
    if enabled:
        bursts, burst_report = (
            _a10_build_keyword_bursts(
                cues,
                timings,
                target_duration,
                payload,
            )
        )
    else:
        bursts, burst_report = [], {
            "version": VERSION,
            "enabled": False,
            "burst_count": 0,
            "independent_ass_layer": False,
            "cut_sync_requested": False,
        }

    for cue in cues:
        cue["keyword_bursts"] = [
            dict(item)
            for item in bursts
            if int(
                item.get(
                    "cue_index"
                )
                or 0
            )
            == int(
                cue.get("index")
                or 0
            )
        ]

    directed_clips, quality_gate = (
        _a10_edit_timeline(
            clips,
            base.get("clips")
            or [],
            cues,
            bursts,
            target_duration,
        )
    )
    burst_report = {
        **burst_report,
        "cut_sync_actual": (
            quality_gate[
                "keyword_cut_sync_count"
            ]
        ),
        "cut_sync_max_error_seconds": (
            quality_gate[
                "keyword_cut_max_error_seconds"
            ]
        ),
        "overlay_only_count": quality_gate.get(
            "keyword_overlay_only_count",
            0,
        ),
        "adaptive_cut_policy": True,
    }
    edit_report = {
        **(
            base.get(
                "edit_report"
            )
            or {}
        ),
        "version": VERSION,
        "output_clip_count": len(
            directed_clips
        ),
        "timeline_duration_seconds": (
            quality_gate[
                "timeline_duration_seconds"
            ]
        ),
        "average_clip_seconds": (
            quality_gate[
                "average_shot_seconds"
            ]
        ),
        "minimum_clip_seconds": (
            quality_gate[
                "minimum_shot_seconds"
            ]
        ),
        "maximum_clip_seconds": (
            quality_gate[
                "maximum_shot_seconds"
            ]
        ),
        "consecutive_same_asset_count": (
            quality_gate[
                "consecutive_same_asset_count"
            ]
        ),
        "keyword_cut_sync": True,
        "semantic_role_match": True,
        "quality_gate_passed": (
            quality_gate[
                "passed"
            ]
        ),
    }
    subtitle_report = {
        **(
            base.get(
                "subtitle_report"
            )
            or {}
        ),
        "version": VERSION,
        "word_timeline": True,
        "word_timeline_source": (
            "tts_native_or_"
            "forced_segment_alignment"
        ),
        "keyword_burst_count": len(
            bursts
        ),
        "independent_keyword_layer": True,
    }
    style = {
        **(
            base.get(
                "subtitle_style"
            )
            or {}
        ),
        "keyword_burst_enabled": (
            enabled
        ),
        "keyword_burst_font_size": max(
            132,
            int(
                _float(
                    payload.get(
                        "keyword_burst_"
                        "font_size"
                    ),
                    146,
                )
            ),
        ),
        "keyword_burst_y": max(
            700,
            min(
                1250,
                int(
                    _float(
                        payload.get(
                            "keyword_burst_y"
                        ),
                        980,
                    )
                ),
            ),
        ),
        "keyword_burst_outline": max(
            10,
            int(
                _float(
                    payload.get(
                        "keyword_burst_"
                        "outline"
                    ),
                    12,
                )
            ),
        ),
    }
    report = {
        "version": VERSION,
        "ai": (
            (
                base.get("report")
                or {}
            ).get("ai")
            or {}
        ),
        "subtitle": subtitle_report,
        "keyword_burst": (
            burst_report
        ),
        "edit": edit_report,
        "quality_gate": quality_gate,
    }
    return {
        **base,
        "version": VERSION,
        "director_marker": (
            DIRECTOR_MARKER
        ),
        "subtitle_segments": cues,
        "subtitle_style": style,
        "keyword_bursts": bursts,
        "keyword_burst_report": (
            burst_report
        ),
        "clips": directed_clips,
        "subtitle_report": (
            subtitle_report
        ),
        "edit_report": edit_report,
        "edit_quality_gate": (
            quality_gate
        ),
        "report": report,
    }


def _a10_burst_color(
    category: str,
) -> str:
    return {
        "risk": "&H003C4CFF&",
        "number": "&H00FF76D8&",
        "action": "&H005CE4FF&",
        "decision": "&H005CE4FF&",
    }.get(
        str(category),
        "&H005CE4FF&",
    )


def _a10_ass_escape(
    value: Any,
) -> str:
    return (
        _display(value)
        .replace(
            "{",
            "（",
        )
        .replace(
            "}",
            "）",
        )
        .replace(
            "\\",
            "＼",
        )
    )


def _a10_burst_dialogue(
    event: dict[str, Any],
    *,
    font_size: int,
    y: int,
    outline: int,
) -> str:
    start = max(
        0.0,
        _float(
            event.get("start")
        )
        - 0.055,
    )
    end = max(
        start + 0.42,
        _float(
            event.get("end"),
            start + 0.7,
        ),
    )
    duration_ms = max(
        420,
        int(
            round(
                (end - start)
                * 1000
            )
        ),
    )
    peak_end = min(
        115,
        max(
            75,
            int(
                duration_ms * 0.16
            ),
        ),
    )
    settle_end = min(
        230,
        max(
            150,
            int(
                duration_ms * 0.32
            ),
        ),
    )
    fade_start = max(
        settle_end + 80,
        duration_ms - 105,
    )
    color = _a10_burst_color(
        str(
            event.get("category")
            or "decision"
        )
    )
    word = _a10_ass_escape(
        event.get("text")
        or ""
    )
    if not word:
        return ""
    tag = (
        r"{\an5\pos(540,"
        + str(y)
        + r")"
        + r"\b1\fs"
        + str(font_size)
        + r"\1c"
        + color
        + r"\3c&H00101010&"
        + r"\bord"
        + str(outline)
        + r"\shad4\4c&H70000000&"
        + r"\blur0.7"
        + r"\fscx62\fscy62"
        + r"\alpha&HFF&\frz-2"
        + r"\t(0,"
        + str(peak_end)
        + r",\alpha&H00&"
        + r"\fscx142\fscy142"
        + r"\frz0)"
        + r"\t("
        + str(peak_end)
        + r","
        + str(settle_end)
        + r",\fscx112\fscy112)"
        + r"\t("
        + str(settle_end)
        + r","
        + str(fade_start)
        + r",\fscx106\fscy106)"
        + r"\t("
        + str(fade_start)
        + r","
        + str(duration_ms)
        + r",\alpha&HFF&"
        + r"\fscx96\fscy96)"
        + r"}"
    )
    return (
        f"Dialogue: 5,"
        f"{_ass_time(start)},"
        f"{_ass_time(end)},"
        f"Burst,,0,0,0,,"
        f"{tag}{word}\n"
    )


def _build_ass(
    segments: Sequence[dict[str, Any]],
    subtitle_style: dict[str, Any],
    keywords: Sequence[str],
    prefix: str,
) -> Path:
    backend_dir = Path(
        os.getenv(
            "AI_VIDEO_BACKEND_DIR",
            "/opt/ai-video/backend",
        )
    )
    work_dir = (
        backend_dir
        / "data"
        / "subtitle-edit-director"
    )
    work_dir.mkdir(
        parents=True,
        exist_ok=True,
    )
    ass_path = work_dir / (
        f"{prefix}_"
        f"{time.strftime('%Y%m%d_%H%M%S')}_"
        f"{uuid.uuid4().hex[:8]}.ass"
    )
    font = os.getenv(
        "AI_VIDEO_SUBTITLE_FONT",
        "Noto Sans CJK SC",
    )
    base_size = max(
        84,
        min(
            128,
            int(
                _float(
                    subtitle_style.get(
                        "font_size"
                    ),
                    100,
                )
            ),
        ),
    )
    outline = max(
        5,
        min(
            14,
            int(
                _float(
                    subtitle_style.get(
                        "outline"
                    ),
                    8,
                )
            ),
        ),
    )
    shadow = max(
        0,
        min(
            6,
            int(
                _float(
                    subtitle_style.get(
                        "shadow"
                    ),
                    2,
                )
            ),
        ),
    )
    margin_v = max(
        180,
        min(
            480,
            int(
                _float(
                    subtitle_style.get(
                        "margin_v"
                    ),
                    300,
                )
            ),
        ),
    )
    primary = _ass_color(
        subtitle_style.get(
            "ass_primary"
        )
        or subtitle_style.get(
            "primary"
        ),
        "&H00FFFFFF&",
    )
    outline_color = _ass_color(
        subtitle_style.get(
            "ass_outline"
        )
        or "#000000",
        "&H00000000&",
    )
    back = _ass_color(
        subtitle_style.get(
            "ass_back"
        )
        or "&H00000000",
        "&H00000000&",
    )
    accent = _ass_color(
        subtitle_style.get(
            "accent"
        )
        or "#FFE45C",
        "&H005CE4FF&",
    )
    burst_size = max(
        120,
        min(
            190,
            int(
                _float(
                    subtitle_style.get(
                        "keyword_burst_"
                        "font_size"
                    ),
                    146,
                )
            ),
        ),
    )
    burst_y = max(
        700,
        min(
            1250,
            int(
                _float(
                    subtitle_style.get(
                        "keyword_burst_y"
                    ),
                    980,
                )
            ),
        ),
    )
    burst_outline = max(
        9,
        min(
            18,
            int(
                _float(
                    subtitle_style.get(
                        "keyword_burst_"
                        "outline"
                    ),
                    12,
                )
            ),
        ),
    )
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n"
        "PlayResX: 1080\n"
        "PlayResY: 1920\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, "
        "PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, "
        "Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, "
        "MarginV, Encoding\n"
        f"Style: Default,{font},{base_size},"
        f"{primary},&H00FFFFFF&,"
        f"{outline_color},{back},-1,0,0,0,"
        f"100,100,0,0,1,{outline},{shadow},"
        f"2,72,72,{margin_v},1\n"
        f"Style: Burst,{font},{burst_size},"
        "&H005CE4FF&,&H00FFFFFF&,"
        "&H00101010&,&H70000000&,-1,0,0,0,"
        f"100,100,1,0,1,{burst_outline},4,"
        "5,40,40,0,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, "
        "Name, MarginL, MarginR, MarginV, "
        "Effect, Text\n"
    )
    lines = [header]
    all_bursts: list[
        dict[str, Any]
    ] = []

    for segment in segments:
        if not isinstance(
            segment,
            dict,
        ):
            continue
        start = _float(
            segment.get("start")
        )
        end = _float(
            segment.get("end"),
            start,
        )
        if end <= start:
            continue
        cue_size = max(
            84,
            min(
                118,
                int(
                    _float(
                        segment.get(
                            "font_size"
                        ),
                        base_size,
                    )
                ),
            ),
        )
        cue_keywords = [
            _display(item)
            for item in (
                segment.get(
                    "keywords"
                )
                or keywords
            )
            if _display(item)
        ]
        strong = _display(
            segment.get(
                "strong_keyword"
            )
            or ""
        )
        display_lines = [
            _display(item)
            for item in (
                segment.get(
                    "display_lines"
                )
                or [
                    segment.get(
                        "text"
                    )
                    or ""
                ]
            )
            if _display(item)
        ][:2]
        if not display_lines:
            continue
        rendered = [
            _highlight(
                line,
                cue_keywords,
                strong,
                cue_size,
                primary,
                accent,
            )
            for line in display_lines
        ]
        prefix_tag = (
            r"{\an2\b1\fs"
            + str(cue_size)
            + r"\1c"
            + primary
            + r"\bord"
            + str(outline)
            + r"\shad"
            + str(shadow)
            + r"\fad(35,45)}"
        )
        rendered_text = r"\N".join(
            rendered
        )
        lines.append(
            f"Dialogue: 0,"
            f"{_ass_time(start)},"
            f"{_ass_time(end)},"
            f"Default,,0,0,0,,"
            f"{prefix_tag}"
            f"{rendered_text}\n"
        )
        for event in (
            segment.get(
                "keyword_bursts"
            )
            or []
        ):
            if isinstance(
                event,
                dict,
            ):
                all_bursts.append(
                    dict(event)
                )

    seen_events: set[
        tuple[str, float]
    ] = set()
    for event in sorted(
        all_bursts,
        key=lambda item: _float(
            item.get("start")
        ),
    ):
        key = (
            _display(
                event.get("text")
                or ""
            ),
            round(
                _float(
                    event.get("start")
                ),
                2,
            ),
        )
        if key in seen_events:
            continue
        seen_events.add(key)
        dialogue = _a10_burst_dialogue(
            event,
            font_size=burst_size,
            y=burst_y,
            outline=burst_outline,
        )
        if dialogue:
            lines.append(dialogue)

    ass_path.write_text(
        "".join(lines),
        encoding="utf-8",
    )
    return ass_path
