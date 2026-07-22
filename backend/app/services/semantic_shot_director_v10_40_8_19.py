from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "10.40.8.20-real-tts-semantic-generation-fix"
REGISTRY_FILE = "existing_edit_asset_usage.json"
_REGISTRY_LOCK = threading.RLock()

_TRANSITIONS = (
    "但是", "不过", "然而", "其实", "真正", "反而", "所以", "然后", "再看", "最后",
    "如果", "对于", "至于", "第一", "第二", "第三", "第四", "另外", "同时", "而且",
)
_ENTITY_TERMS = (
    "商场", "购物中心", "学校", "国际学校", "医院", "诊所", "地铁", "轻轨", "公交",
    "公园", "超市", "餐厅", "咖啡馆", "写字楼", "办公区", "机场", "高铁", "车站",
    "银行", "菜市场", "健身房", "泳池", "会所", "大学", "幼儿园", "小学", "中学",
)
_THEME_TERMS = {
    "交通": ("交通", "地铁", "轻轨", "通勤", "线路", "车程", "出行", "机场", "高铁"),
    "配套": ("配套", "商场", "餐饮", "生活", "学校", "医院", "医疗", "超市", "公园"),
    "预算": ("价格", "预算", "租金", "现金流", "回报", "收益", "总价", "月供"),
    "人群": ("租客", "客户", "白领", "家庭", "自住", "投资", "学生"),
    "风险": ("风险", "避坑", "产权", "交付", "退出", "转手", "税费"),
    "区域": ("区域", "地段", "板块", "位置", "吉隆坡", "KLCC", "TRX", "新山", "槟城"),
}
_STOP = {"这个", "一个", "我们", "就是", "可以", "视频", "素材", "画面", "项目", "介绍", "相关"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _classic() -> Any:
    from app.services import existing_video_editor_v10_40_8_5 as classic
    return classic


def _data_dir(settings: Any) -> Path:
    return Path(getattr(settings, "data_dir", None) or "/opt/ai-video/backend/data")


def _registry_path(settings: Any) -> Path:
    return _data_dir(settings) / REGISTRY_FILE


def _load_registry(settings: Any) -> dict[str, Any]:
    path = _registry_path(settings)
    if not path.exists():
        return {"version": VERSION, "assets": {}, "jobs": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("registry is not object")
        data.setdefault("assets", {})
        data.setdefault("jobs", {})
        return data
    except Exception:
        return {"version": VERSION, "assets": {}, "jobs": {}}


def _save_registry(settings: Any, data: dict[str, Any]) -> None:
    path = _registry_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    data["version"] = VERSION
    data["updated_at"] = _now()
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def _asset_url(item: dict[str, Any]) -> str:
    nested = item.get("asset") if isinstance(item.get("asset"), dict) else {}
    media = item.get("media") if isinstance(item.get("media"), dict) else {}
    r2 = item.get("r2") if isinstance(item.get("r2"), dict) else {}
    preview = item.get("preview") if isinstance(item.get("preview"), dict) else {}
    return _text(
        item.get("asset_url") or item.get("assetUrl") or item.get("r2_url") or item.get("r2Url")
        or item.get("video_url") or item.get("videoUrl") or item.get("download_url") or item.get("downloadUrl")
        or item.get("public_url") or item.get("publicUrl") or item.get("signed_url") or item.get("signedUrl")
        or item.get("url") or nested.get("url") or nested.get("r2_url") or nested.get("r2Url")
        or nested.get("video_url") or nested.get("public_url") or media.get("url") or media.get("video_url")
        or r2.get("url") or r2.get("public_url") or preview.get("url") or preview.get("video_url")
    )


def _asset_id(item: dict[str, Any]) -> str:
    nested = item.get("asset") if isinstance(item.get("asset"), dict) else {}
    url = _asset_url(item)
    return _text(
        item.get("asset_id") or item.get("assetId") or item.get("id") or item.get("r2_key")
        or item.get("r2Key") or item.get("object_key") or item.get("objectKey") or item.get("key")
        or item.get("filename") or item.get("original_name") or nested.get("id") or nested.get("asset_id")
        or nested.get("assetId") or nested.get("r2_key")
        or (hashlib.sha256(url.encode()).hexdigest()[:24] if url else "")
    )


def _asset_name(item: dict[str, Any]) -> str:
    nested = item.get("asset") if isinstance(item.get("asset"), dict) else {}
    return _text(
        item.get("asset_name") or item.get("assetName") or item.get("original_name") or item.get("filename")
        or item.get("name") or item.get("title") or nested.get("name") or nested.get("filename")
    )


def _clip_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        for key in ("clips", "shots", "items", "shot_plan", "manual_shot_plan"):
            nested = value.get(key)
            if isinstance(nested, list):
                return [dict(x) for x in nested if isinstance(x, dict)]
        return []
    if isinstance(value, list):
        return [dict(x) for x in value if isinstance(x, dict)]
    return []


def _extract_previous_page_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for candidate in (
        payload.get("edit_plan"), payload.get("manual_shot_plan"), payload.get("manualShotPlan"),
        payload.get("shot_plan"), payload.get("shotPlan"), payload.get("shots"),
    ):
        items = _clip_list(candidate)
        if items:
            return items
    return []


def _asset_text(asset: dict[str, Any]) -> str:
    intel = asset.get("asset_intelligence") if isinstance(asset.get("asset_intelligence"), dict) else {}
    values = [
        _asset_name(asset), asset.get("ai_title"), asset.get("ai_description"),
        asset.get("ai_primary_category"), asset.get("ai_secondary_category"),
        intel.get("title"), intel.get("description"), intel.get("primary_category"),
        intel.get("secondary_category"), intel.get("scene"), intel.get("location"),
        " ".join(asset.get("ai_keywords") or []), " ".join(intel.get("keywords") or []),
    ]
    return " ".join(_text(x) for x in values if _text(x))


def _asset_aliases(asset: dict[str, Any]) -> set[str]:
    values = {_asset_id(asset), _asset_name(asset), _asset_url(asset)}
    for key in ("id", "asset_id", "assetId", "r2_key", "r2Key", "object_key", "objectKey", "key", "filename", "original_name"):
        values.add(_text(asset.get(key)))
    return {x.lower() for x in values if x}


def _candidate_assets(settings: Any, payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    classic = _classic()
    selected_raw: list[Any] = []
    for value in (
        payload.get("selected_assets"), payload.get("asset_context"), payload.get("r2_material_context"),
        payload.get("selectedAssets"), payload.get("assetContext"),
    ):
        if isinstance(value, list):
            selected_raw.extend(value)
    previous = _extract_previous_page_items(payload)
    library = classic._load_library_assets(settings)

    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source, items in (("previous_page", previous), ("manual", selected_raw), ("auto", library)):
        for raw in items:
            if not isinstance(raw, dict):
                continue
            item = dict(raw)
            aid = _asset_id(item)
            url = _asset_url(item)
            if not aid and not url:
                continue
            key = aid or url
            if key in seen:
                continue
            candidate = dict(item)
            candidate["_selection_source"] = source
            if url:
                candidate["asset_url"] = url
            if aid:
                candidate["asset_id"] = aid
            result.append(candidate)
            seen.add(key)

    # Resolve previous-page items that carry only an id/name/key against the R2 library.
    library_index: list[tuple[set[str], dict[str, Any]]] = [(_asset_aliases(dict(x)), dict(x)) for x in library if isinstance(x, dict)]
    resolved_previous: list[dict[str, Any]] = []
    for item in previous:
        item = dict(item)
        if _asset_url(item):
            item["_selection_source"] = "previous_page"
            resolved_previous.append(item)
            continue
        aliases = _asset_aliases(item)
        matched: dict[str, Any] | None = None
        for candidate_aliases, library_item in library_index:
            if aliases & candidate_aliases:
                matched = library_item
                break
        if matched:
            merged = {**matched, **item, "asset_url": _asset_url(matched), "asset_id": _asset_id(matched), "_selection_source": "previous_page"}
            resolved_previous.append(merged)

    # A previous-page card may only carry asset_id / filename. The raw entry was
    # already inserted into `result` before the R2 lookup and therefore could
    # suppress the fully resolved library item. Replace that placeholder with
    # the resolved object so the final editor never sees “1 镜头 / 0 素材”.
    if resolved_previous:
        resolved_by_id = {_asset_id(item): item for item in resolved_previous if _asset_id(item)}
        merged_result: list[dict[str, Any]] = []
        merged_ids: set[str] = set()
        for candidate in result:
            aid = _asset_id(candidate)
            if aid and aid in resolved_by_id:
                merged = {**candidate, **resolved_by_id[aid], "_selection_source": "previous_page"}
                merged_result.append(merged)
                merged_ids.add(aid)
            else:
                merged_result.append(candidate)
        for aid, item in resolved_by_id.items():
            if aid not in merged_ids:
                merged_result.insert(0, item)
        result = merged_result
    return result, resolved_previous


def _speech_units(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw: Any = []
    for key in ("tts_segments", "subtitle_segments", "segments", "script_segments", "voice_segments"):
        value = payload.get(key)
        if isinstance(value, list) and value:
            raw = value
            break
    units: list[dict[str, Any]] = []
    for index, item in enumerate(raw if isinstance(raw, list) else []):
        if not isinstance(item, dict):
            continue
        text = _text(item.get("text") or item.get("narration") or item.get("copy") or item.get("script"))
        if not text:
            continue
        start = _safe_float(item.get("start") if item.get("start") is not None else item.get("start_time"), -1.0)
        end = _safe_float(item.get("end") if item.get("end") is not None else item.get("end_time"), -1.0)
        duration = _safe_float(item.get("duration") or item.get("duration_seconds"), 0.0)
        if end <= start and start >= 0 and duration > 0:
            end = start + duration
        units.append({"index": len(units), "text": text, "start": start, "end": end})

    script = _text(payload.get("script_text") or payload.get("script") or "")
    if not units:
        parts = [x.strip() for x in re.split(r"(?<=[。！？!?；;])|\n+", script) if x.strip()]
        if not parts and script:
            parts = [script]
        target = max(1.0, _safe_float(payload.get("target_duration_seconds") or payload.get("duration"), 30.0))
        weights = [max(2, len(re.sub(r"\s+", "", part))) for part in parts] or [1]
        cursor = 0.0
        for index, (part, weight) in enumerate(zip(parts, weights)):
            end = target if index == len(parts) - 1 else cursor + target * weight / sum(weights)
            units.append({"index": index, "text": part, "start": round(cursor, 3), "end": round(end, 3)})
            cursor = end
    elif not all(unit["start"] >= 0 and unit["end"] > unit["start"] for unit in units):
        target = max(1.0, _safe_float(payload.get("target_duration_seconds") or payload.get("duration"), 30.0))
        weights = [max(2, len(re.sub(r"\s+", "", unit["text"]))) for unit in units]
        cursor = 0.0
        for index, (unit, weight) in enumerate(zip(units, weights)):
            end = target if index == len(units) - 1 else cursor + target * weight / sum(weights)
            unit["start"] = round(cursor, 3)
            unit["end"] = round(end, 3)
            cursor = end
    return units


def _entities(text: str) -> list[str]:
    found: list[str] = []
    for term in sorted(_ENTITY_TERMS, key=len, reverse=True):
        if term in text and term not in found:
            found.append(term)
    return found


def _themes(text: str) -> set[str]:
    lower = text.lower()
    return {name for name, terms in _THEME_TERMS.items() if any(term.lower() in lower for term in terms)}


def _tokens(text: str) -> set[str]:
    raw = _text(text).lower()
    words = re.findall(r"[a-z0-9_]{2,}|[\u4e00-\u9fff]{2,}", raw)
    zh = "".join(re.findall(r"[\u4e00-\u9fff]", raw))
    words += [zh[i : i + 2] for i in range(max(0, len(zh) - 1))]
    return {x for x in words if x not in _STOP}


def _fallback_beats(units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    beats: list[dict[str, Any]] = []
    index = 0
    while index < len(units):
        unit = units[index]
        entities = _entities(unit["text"])
        if len(entities) >= 2:
            beats.append({
                "unit_indexes": [index], "beat_type": "entity_burst", "entities": entities[:8],
                "reason": "并列具体地点/配套逐项展示", "asset_keywords": entities[:8],
            })
            index += 1
            continue

        group = [index]
        start = unit["start"]
        end = unit["end"]
        theme = _themes(unit["text"])
        while index + 1 < len(units):
            nxt = units[index + 1]
            next_entities = _entities(nxt["text"])
            next_theme = _themes(nxt["text"])
            has_turn = any(token in nxt["text"] for token in _TRANSITIONS)
            if next_entities or has_turn or (theme and next_theme and theme != next_theme) or nxt["end"] - start > 6.8:
                break
            group.append(index + 1)
            index += 1
            end = nxt["end"]
            theme |= next_theme
        joined = "".join(units[i]["text"] for i in group)
        beat_type = "turn" if any(token in joined for token in ("但是", "不过", "然而", "真正", "所以")) else "hold"
        beats.append({
            "unit_indexes": group, "beat_type": beat_type, "entities": [],
            "reason": "普通讲解保持主镜头" if beat_type == "hold" else "逻辑转折切镜",
            "asset_keywords": sorted(theme) or [joined[:12]],
        })
        index += 1
    return beats


def _run_async(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(coro)).result()


def _ai_beats(settings: Any, units: list[dict[str, Any]], assets: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from app.services.deepseek import _chat_json

    unit_payload = [
        {"index": unit["index"], "start": round(unit["start"], 3), "end": round(unit["end"], 3), "text": unit["text"]}
        for unit in units
    ]
    asset_payload = [
        {
            "asset_id": _asset_id(asset), "name": _asset_name(asset), "source": asset.get("_selection_source"),
            "description": _asset_text(asset)[:240],
        }
        for asset in assets[:60]
    ]
    system = (
        "你是剪映/CapCut 风格的资深短视频剪辑导演。你的任务不是按固定秒数切镜，而是根据口播语义决定镜头边界。"
        "必须输出严格 JSON，不要 Markdown。普通解释句应保持一个主镜头，只有语义对象变化、转折、证据或并列实体时切换。"
    )
    user = f"""
口播时间单元：
{json.dumps(unit_payload, ensure_ascii=False)}

可用素材摘要：
{json.dumps(asset_payload, ensure_ascii=False)}

输出 JSON：
{{
  "beats": [
    {{
      "unit_indexes": [0,1],
      "beat_type": "hold|entity_burst|turn|comparison|evidence|cta",
      "entities": ["商场","学校","医院"],
      "asset_keywords": ["商场","学校","医院"],
      "reason": "为什么此处保持或切镜"
    }}
  ],
  "director_notes": ["整体剪辑判断"]
}}

硬规则：
1. 所有 unit index 必须且只能覆盖一次，顺序不变，不能漏句。
2. 常规解释、观点、铺垫：合并相邻单元，尽量保持 3–7 秒同一镜头；字幕变化不等于切镜。
3. 出现“商场、学校、医院、地铁、公园、超市”等并列具体实体：beat_type=entity_burst，entities 中逐项列出，一个实体一个镜头。
4. 转折、对比、证据、地图、数据、CTA 才单独切镜。
5. 不要为了快节奏把完整句子拆碎；不要按标点机械切镜。
6. asset_keywords 用于匹配素材，不能编造素材 ID。
""".strip()
    payload = _run_async(_chat_json(settings, system, user, temperature=0.18, timeout=75))
    raw = payload.get("beats") if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        raise ValueError("DeepSeek 未返回 beats")

    beats: list[dict[str, Any]] = []
    covered: list[int] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        indexes = item.get("unit_indexes") or []
        indexes = [int(x) for x in indexes if isinstance(x, (int, float)) or str(x).isdigit()]
        indexes = sorted({x for x in indexes if 0 <= x < len(units)})
        if not indexes:
            continue
        beat_type = _text(item.get("beat_type") or "hold")
        if beat_type not in {"hold", "entity_burst", "turn", "comparison", "evidence", "cta"}:
            beat_type = "hold"
        entities = [_text(x) for x in (item.get("entities") or []) if _text(x)]
        if beat_type == "entity_burst" and len(entities) < 2:
            entities = _entities("".join(units[x]["text"] for x in indexes))
            if len(entities) < 2:
                beat_type = "hold"
        beats.append({
            "unit_indexes": indexes,
            "beat_type": beat_type,
            "entities": entities[:10],
            "asset_keywords": [_text(x) for x in (item.get("asset_keywords") or []) if _text(x)][:10],
            "reason": _text(item.get("reason"))[:160],
        })
        covered.extend(indexes)

    if sorted(covered) != list(range(len(units))) or len(covered) != len(set(covered)):
        raise ValueError("DeepSeek beats 未完整且唯一覆盖口播单元")
    beats.sort(key=lambda x: x["unit_indexes"][0])
    notes = payload.get("director_notes") if isinstance(payload, dict) else []
    report = {"used_ai": True, "fallback": False, "director_notes": notes if isinstance(notes, list) else [str(notes)]}
    return beats, report


def _history_entry(registry: dict[str, Any], aid: str) -> dict[str, Any]:
    raw = (registry.get("assets") or {}).get(aid) or {}
    return raw if isinstance(raw, dict) else {}


def _score_asset(query: str, asset: dict[str, Any], registry: dict[str, Any], current_use: int, previous_id: str) -> float:
    aid = _asset_id(asset)
    text = _asset_text(asset)
    history = _history_entry(registry, aid)
    overlap = len(_tokens(query) & _tokens(text))
    theme_overlap = len(_themes(query) & _themes(text))
    # Concrete entity bursts (商场 / 学校 / 医院 …) must prefer an exact
    # matching clip over merely fresh or high-quality material.
    exact_entities = sum(1 for term in _ENTITY_TERMS if term in query and term in text)
    exact_phrase = 1 if query and len(query) <= 16 and query in text else 0
    quality = _safe_float(asset.get("ai_quality_score") or (asset.get("asset_intelligence") or {}).get("quality_score"), 60)
    source = asset.get("_selection_source")
    source_bonus = 58.0 if source == "previous_page" else 28.0 if source == "manual" else 0.0
    fresh_bonus = 22.0 if not history else 0.0
    historical_count = int(_safe_float(history.get("use_count"), 0))
    immediate_repeat = 95.0 if aid and aid == previous_id else 0.0
    return (
        overlap * 11.0 + theme_overlap * 22.0 + exact_entities * 95.0 + exact_phrase * 55.0
        + quality / 14.0 + source_bonus + fresh_bonus
        - current_use * 120.0 - historical_count * 8.0 - immediate_repeat
    )


def _choose_asset(query: str, candidates: list[dict[str, Any]], registry: dict[str, Any], use_count: dict[str, int], previous_id: str) -> dict[str, Any]:
    valid = [asset for asset in candidates if _asset_url(asset)]
    if not valid:
        raise ValueError("R2 素材库没有可解析的视频 URL")

    # In an entity burst, semantic correctness outranks the no-repeat rule.
    # Reusing the actual school clip for “学校” is better than showing a fresh
    # hospital clip merely to keep every asset unique.
    requested_entities = [term for term in _ENTITY_TERMS if term in query]
    exact = [
        asset for asset in valid
        if requested_entities and any(term in _asset_text(asset) for term in requested_entities)
    ]
    if exact:
        pool = exact
    else:
        unused = [asset for asset in valid if use_count.get(_asset_id(asset), 0) == 0]
        pool = unused or [asset for asset in valid if _asset_id(asset) != previous_id] or valid
    return max(pool, key=lambda asset: _score_asset(query, asset, registry, use_count.get(_asset_id(asset), 0), previous_id))


def _expand_beats(units: list[dict[str, Any]], beats: list[dict[str, Any]]) -> list[dict[str, Any]]:
    expanded: list[dict[str, Any]] = []
    for beat in beats:
        indexes = beat["unit_indexes"]
        start = units[indexes[0]]["start"]
        end = units[indexes[-1]]["end"]
        text = "".join(units[index]["text"] for index in indexes)
        if beat["beat_type"] == "entity_burst" and len(beat.get("entities") or []) >= 2:
            entities = beat["entities"]
            span = max(0.8 * len(entities), end - start)
            weights = [max(2, len(entity)) for entity in entities]
            cursor = start
            for entity_index, (entity, weight) in enumerate(zip(entities, weights)):
                item_end = end if entity_index == len(entities) - 1 else min(end, cursor + span * weight / sum(weights))
                if item_end - cursor < 0.65:
                    item_end = min(end, cursor + 0.65)
                expanded.append({
                    **beat, "text": entity, "query": entity, "start": cursor, "end": item_end,
                    "duration": max(0.65, item_end - cursor), "entity": entity,
                })
                cursor = item_end
        else:
            expanded.append({
                **beat, "text": text, "query": " ".join(beat.get("asset_keywords") or []) + " " + text,
                "start": start, "end": end, "duration": max(0.8, end - start), "entity": "",
            })
    return expanded


def build_plan(settings: Any, payload: dict[str, Any], job_id: str) -> dict[str, Any]:
    units = _speech_units(payload)
    if not units:
        raise ValueError("缺少可用于 AI 镜头导演的口播稿")
    candidates, resolved_previous = _candidate_assets(settings, payload)
    if resolved_previous:
        # Previous-page selections are the priority pool, while R2 remains a fallback
        # only when the selected list is too small for all semantic beats.
        previous_ids = {_asset_id(item) for item in resolved_previous}
        for item in candidates:
            if _asset_id(item) in previous_ids:
                item["_selection_source"] = "previous_page"
    try:
        beats, director_report = _ai_beats(settings, units, candidates)
    except Exception as exc:
        beats = _fallback_beats(units)
        director_report = {"used_ai": False, "fallback": True, "fallback_reason": str(exc)[:500], "director_notes": ["DeepSeek 不可用，已使用语义规则兜底。"]}

    expanded = _expand_beats(units, beats)
    with _REGISTRY_LOCK:
        registry = _load_registry(settings)
    use_count: dict[str, int] = {}
    previous_id = ""
    clips: list[dict[str, Any]] = []
    for index, item in enumerate(expanded, 1):
        chosen = _choose_asset(item["query"], candidates, registry, use_count, previous_id)
        aid = _asset_id(chosen)
        use_count[aid] = use_count.get(aid, 0) + 1
        previous_id = aid
        duration = round(max(0.65, _safe_float(item.get("duration"), 2.8)), 3)
        title = _asset_name(chosen) or _text(chosen.get("ai_title")) or f"素材 {index}"
        clips.append({
            "id": f"ai_beat_{index}", "index": index, "title": title,
            "scene": _asset_text(chosen) or title, "description": _asset_text(chosen) or title,
            "narration": item["text"], "duration": duration, "duration_seconds": duration,
            "source": "r2", "selection_source": chosen.get("_selection_source") or "auto",
            "manual_locked": chosen.get("_selection_source") == "previous_page",
            "asset_id": aid, "asset_ids": [aid], "asset_url": _asset_url(chosen),
            "asset_name": title, "start_time": 0.0, "end_time": duration, "auto_start": True,
            "preserve_audio": _text(payload.get("voice_mode") or "tts_with_ambient") != "tts_only",
            "speed": 1.0, "transition": "轻柔淡化", "camera": "保留原片运镜",
            "beat_type": item["beat_type"], "beat_reason": item.get("reason") or "",
            "speech_start": round(item["start"], 3), "speech_end": round(item["end"], 3),
            "entity": item.get("entity") or "", "semantic_themes": sorted(_themes(item["text"])),
            "history_use_count": int(_safe_float(_history_entry(registry, aid).get("use_count"), 0)),
            "current_job_use_count": use_count[aid],
        })

    ids = [_text(clip.get("asset_id")) for clip in clips]
    total = round(sum(_safe_float(clip.get("duration"), 0.0) for clip in clips), 3)
    return {
        "ok": True, "version": VERSION, "source": "ai_semantic_beat_director",
        "locked": bool(resolved_previous), "clips": clips, "beats": beats,
        "speech_units": units, "target_duration_seconds": total,
        "director_report": director_report,
        "usage_report": {
            "clip_count": len(clips), "unique_asset_count": len(set(ids)),
            "repeat_count": max(0, len(clips) - len(set(ids))), "asset_ids": ids,
            "registry_file": str(_registry_path(settings)),
            "previous_page_resolved": len(resolved_previous),
            "previous_page_requested": len(_extract_previous_page_items(payload)),
        },
    }


def prepare_classic_payload(settings: Any, payload: dict[str, Any], job_id: str) -> dict[str, Any]:
    # V10_40_8_20_REAL_TTS_SEMANTIC_GENERATION_FIX: the pre-TTS semantic plan is only a preview/candidate pool.
    # Auto and hybrid jobs must stay unlocked so the classic renderer can generate
    # real TTS first, then run this semantic director again with true start/end data.
    plan = build_plan(settings, payload, job_id)
    next_payload = dict(payload)
    requested_mode = _text(
        payload.get("material_selection_mode")
        or payload.get("selection_mode")
        or ("hybrid" if _extract_previous_page_items(payload) else "auto")
    ).lower()
    if requested_mode not in {"auto", "hybrid", "manual"}:
        requested_mode = "hybrid" if _extract_previous_page_items(payload) else "auto"

    next_payload["burn_subtitles"] = False
    next_payload["edit_plan"] = {
        "clips": plan["clips"],
        "source": plan["source"],
        "version": VERSION,
        "timing_source": "pre_tts_preview",
    }
    next_payload["material_selection_mode"] = requested_mode
    next_payload["lock_edit_plan"] = requested_mode == "manual"
    next_payload["auto_fill_assets"] = requested_mode != "manual"
    next_payload["semantic_tts_replan"] = True
    next_payload["tts_timing_required"] = True
    next_payload["shot_director"] = "ai_auto"
    next_payload["asset_usage_job_id"] = job_id
    next_payload["semantic_director_version"] = VERSION
    next_payload["ai_shot_beats"] = plan.get("beats") or []
    next_payload["target_duration_seconds"] = (
        plan["target_duration_seconds"]
        or next_payload.get("target_duration_seconds")
        or 30
    )
    return {"payload": next_payload, "plan": plan}

def record_success(settings: Any, job_id: str, clips: list[dict[str, Any]]) -> dict[str, Any]:
    ids = [_text(item.get("asset_id")) for item in clips if _text(item.get("asset_id"))]
    with _REGISTRY_LOCK:
        data = _load_registry(settings)
        assets = data.setdefault("assets", {})
        jobs = data.setdefault("jobs", {})
        for aid in ids:
            entry = assets.setdefault(aid, {})
            entry["use_count"] = int(_safe_float(entry.get("use_count"), 0)) + 1
            entry["last_used_at"] = _now()
            history = entry.setdefault("jobs", [])
            if job_id not in history:
                history.append(job_id)
            entry["jobs"] = history[-30:]
        jobs[job_id] = {"asset_ids": ids, "unique_asset_ids": list(dict.fromkeys(ids)), "created_at": _now()}
        _save_registry(settings, data)
    return {"ok": True, "job_id": job_id, "asset_ids": ids, "unique_asset_count": len(set(ids)), "repeat_count": max(0, len(ids) - len(set(ids))), "registry_file": str(_registry_path(settings))}
