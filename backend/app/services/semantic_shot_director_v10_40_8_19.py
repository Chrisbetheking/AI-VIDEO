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

VERSION = "10.40.8.31-clean-text-pro-stickers"
# V10_40_8_31_CLEAN_TEXT_PRO_STICKERS
# REAL_TTS_CHILD_MASTER_SYNC_R9
REGISTRY_FILE = "existing_edit_asset_usage.json"
_REGISTRY_LOCK = threading.RLock()

_TRANSITIONS = (
    "但是", "不过", "然而", "其实", "真正", "反而", "所以", "然后", "再看", "最后",
    "如果", "对于", "至于", "第一", "第二", "第三", "第四", "另外", "同时", "而且",
)
_ENTITY_TERMS = (
    "商场", "购物中心", "学校", "国际学校", "医院", "诊所", "地铁", "轻轨", "公交",
    "公园", "超市", "餐厅", "咖啡馆", "咖啡厅", "咖啡店", "商业街", "图书馆", "写字楼", "办公区", "机场", "高铁", "车站",
    "银行", "菜市场", "健身房", "泳池", "会所", "大学", "幼儿园", "小学", "中学",
)

# V21 hard semantic intents. Exact semantic meaning outranks freshness and uniqueness.
_INTENT_ALIASES: dict[str, tuple[str, ...]] = {
    "学校": ("学校", "校园", "教室", "学生", "小学", "中学", "大学", "school", "campus", "classroom"),
    "超市": ("超市", "便利店", "杂货店", "生鲜", "supermarket", "grocery", "convenience store"),
    "商场": ("商场", "购物中心", "商业中心", "mall", "shopping centre", "shopping center"),
    "医院": ("医院", "诊所", "医疗", "hospital", "clinic", "medical"),
    "通勤": ("通勤", "交通", "道路", "街道", "地铁", "轻轨", "公交", "驾车", "commute", "traffic", "road", "metro", "train"),
    "餐厅": ("餐厅", "餐饮", "饭店", "restaurant", "dining", "food"),
    "咖啡厅": ("咖啡厅", "咖啡馆", "咖啡店", "coffee shop", "cafe", "café"),
    "公园": ("公园", "绿地", "花园", "park", "garden"),
    "办公": ("办公", "写字楼", "办公室", "白领", "office", "workplace"),
    "住宅": ("住宅", "公寓", "楼盘", "社区", "小区", "residential", "apartment", "condo"),
}
_NEUTRAL_VISUAL_TERMS = (
    "城市", "街景", "道路", "住宅", "公寓", "社区", "人物", "咨询", "地图", "区域",
    "city", "street", "road", "residential", "apartment", "people", "consulting", "map",
)
_UNRELATED_ENTITY_TERMS = tuple(sorted(set(_ENTITY_TERMS) | {"海岛", "海滩", "烧烤", "聚餐", "美食", "beach", "island", "barbecue"}))

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



def _split_long_speech_units(units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep a spoken sentence intact.

    Long narration is not a reason to cut. Real cuts are created later only by
    semantic turns, evidence/comparison beats, or concrete entity bursts such
    as 咖啡厅 / 商场 / 学校. This prevents comma-level mechanical switching.
    """
    output: list[dict[str, Any]] = []
    for index, unit in enumerate(units):
        item = dict(unit)
        item["index"] = index
        item["sentence_hold"] = True
        output.append(item)
    return output


def _speech_units(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw: Any = []
    # SEMANTIC_MASTER_TIMELINE_V21
# CAPTION_PHRASE_SAFE_CLEAN_RENDER_R8: captions never alter shot planning: shot planning consumes sentence-level speech units.
    # Subtitle fragments are presentation-only and must never create visual cuts.
    for key in ("semantic_speech_units", "tts_sentence_segments", "script_segments", "voice_segments", "tts_segments"):
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
        units.append({
            "index": len(units), "text": text, "start": start, "end": end,
            "word_timeline": [dict(x) for x in (item.get("word_timeline") or []) if isinstance(x, dict)],
            "timing_source": _text(item.get("timing_source") or ""),
        })

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
    return _split_long_speech_units(units)

def _entities(text: str) -> list[str]:
    spans: list[tuple[int, int, str]] = []
    for term in sorted(_ENTITY_TERMS, key=len, reverse=True):
        search_from = 0
        while True:
            position = text.find(term, search_from)
            if position < 0:
                break
            end = position + len(term)
            if not any(max(position, left) < min(end, right) for left, right, _ in spans):
                spans.append((position, end, term))
            search_from = position + max(1, len(term))
    spans.sort(key=lambda item: (item[0], -len(item[2])))
    found: list[str] = []
    for _, _, term in spans:
        if term not in found:
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
    category_counts: dict[str, int] = {}
    for asset in assets:
        intel = asset.get("asset_intelligence") if isinstance(asset.get("asset_intelligence"), dict) else {}
        category = _text(
            intel.get("primary_category") or asset.get("ai_primary_category")
            or intel.get("scene") or "未分类"
        )[:24]
        category_counts[category] = category_counts.get(category, 0) + 1
    library_summary = {
        "asset_count": len(assets),
        "top_categories": sorted(category_counts.items(), key=lambda item: (-item[1], item[0]))[:18],
    }
    system = (
        "你是剪映/CapCut 风格的资深知识口播剪辑导演。你只判断语义镜头边界，不按固定秒数或字幕碎片切镜。"
        "长句、解释句、观点句即使有多个逗号，也优先保持同一主镜头；只有具体场景列表、逻辑转折、证据、对比、流程或CTA才切换。"
        "必须输出严格 JSON，不要 Markdown。"
    )
    user = f"""
口播时间单元：
{json.dumps(unit_payload, ensure_ascii=False)}

素材库概况：
{json.dumps(library_summary, ensure_ascii=False)}

输出 JSON：
{{
  "beats": [
    {{
      "unit_indexes": [0,1],
      "beat_type": "hold|entity_burst|turn|comparison|evidence|cta",
      "entities": ["咖啡厅","商场","学校"],
      "asset_keywords": ["咖啡厅","商场","学校"],
      "reason": "为什么此处保持或切镜"
    }}
  ],
  "director_notes": ["整体剪辑判断"]
}}

硬规则：
1. 所有 unit index 必须且只能覆盖一次，顺序不变，不能漏句。
2. 普通解释、观点、铺垫和完整长句：优先合并相邻单元，同一意思可保持 5–11 秒；逗号和字幕变化都不触发切镜。
3. 单个长句即使超过 7 秒，只要语义对象没有改变，就保持一个镜头，不得机械拆分。
4. 出现“咖啡厅、商场、学校、医院、地铁、公园、超市”等并列具体地点：beat_type=entity_burst，按出现顺序列出 entities，一个地点一个相邻小镜头。
5. 转折、对比、证据、地图、流程、数据、CTA 才单独切镜。
6. 不要为了快节奏拆碎完整句子；小场景快切只服务具体实体列表。
7. asset_keywords 只写语义词，不编造素材 ID。素材选择由后续全库检索完成。
""".strip()
    payload = _run_async(_chat_json(settings, system, user, temperature=0.12, timeout=75))
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
        combined = "".join(units[x]["text"] for x in indexes)
        entities = [_text(x) for x in (item.get("entities") or []) if _text(x)]
        detected_entities = _entities(combined)
        if len(detected_entities) >= 2:
            beat_type = "entity_burst"
            entities = detected_entities
        elif beat_type == "entity_burst" and len(entities) < 2:
            beat_type = "hold"
            entities = []
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
    report = {
        "used_ai": True,
        "fallback": False,
        "asset_library_count": len(assets),
        "director_notes": notes if isinstance(notes, list) else [str(notes)],
    }
    return beats, report


def _history_entry(registry: dict[str, Any], aid: str) -> dict[str, Any]:
    raw = (registry.get("assets") or {}).get(aid) or {}
    return raw if isinstance(raw, dict) else {}


def _recent_job_ids(registry: dict[str, Any], limit: int) -> list[str]:
    jobs = registry.get("jobs") or {}
    rows: list[tuple[str, str]] = []
    if isinstance(jobs, dict):
        for job_id, raw in jobs.items():
            item = raw if isinstance(raw, dict) else {}
            rows.append((_text(item.get("created_at")), _text(job_id)))
    rows.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [job_id for _, job_id in rows[: max(0, limit)] if job_id]


def _recent_use_count(registry: dict[str, Any], aid: str, limit: int) -> int:
    jobs = registry.get("jobs") or {}
    count = 0
    for job_id in _recent_job_ids(registry, limit):
        raw = jobs.get(job_id) if isinstance(jobs, dict) else None
        item = raw if isinstance(raw, dict) else {}
        ids = item.get("asset_ids") or []
        if aid in ids:
            count += 1
    return count


def _score_asset(query: str, asset: dict[str, Any], registry: dict[str, Any], current_use: int, previous_id: str) -> float:
    aid = _asset_id(asset)
    text = _asset_text(asset)
    history = _history_entry(registry, aid)
    overlap = len(_tokens(query) & _tokens(text))
    theme_overlap = len(_themes(query) & _themes(text))
    exact_entities = sum(1 for term in _ENTITY_TERMS if term in query and term in text)
    exact_phrase = 1 if query and len(query) <= 16 and query in text else 0
    quality = _safe_float(asset.get("ai_quality_score") or (asset.get("asset_intelligence") or {}).get("quality_score"), 60)
    source = asset.get("_selection_source")
    source_bonus = 58.0 if source == "previous_page" else 28.0 if source == "manual" else 0.0
    historical_count = int(_safe_float(history.get("use_count"), 0))
    recent_3 = _recent_use_count(registry, aid, 3)
    recent_10 = _recent_use_count(registry, aid, 10)
    fresh_bonus = 30.0 if historical_count == 0 else 0.0
    immediate_repeat = 110.0 if aid and aid == previous_id else 0.0
    return (
        overlap * 11.0 + theme_overlap * 22.0 + exact_entities * 95.0 + exact_phrase * 55.0
        + quality / 14.0 + source_bonus + fresh_bonus
        - current_use * 135.0
        - recent_3 * 42.0
        - max(0, recent_10 - recent_3) * 13.0
        - min(historical_count, 20) * 4.0
        - immediate_repeat
    )


def _asset_duration(asset: dict[str, Any]) -> float:
    intel = asset.get("asset_intelligence") if isinstance(asset.get("asset_intelligence"), dict) else {}
    technical = intel.get("technical") if isinstance(intel.get("technical"), dict) else {}
    return max(0.0, _safe_float(
        asset.get("duration") or asset.get("duration_seconds")
        or intel.get("duration") or technical.get("duration"),
        0.0,
    ))


def _segment_overlap_ratio(start: float, end: float, other_start: float, other_end: float) -> float:
    overlap = max(0.0, min(end, other_end) - max(start, other_start))
    return overlap / max(0.001, min(end - start, other_end - other_start))


def _choose_source_segment_start(
    asset: dict[str, Any],
    registry: dict[str, Any],
    duration: float,
    speed: float,
    semantic_seed: str,
) -> tuple[float, bool, str]:
    aid = _asset_id(asset)
    total = _asset_duration(asset)
    needed = max(0.55, duration * speed)
    available = max(0.0, total - needed - 0.12)
    if total <= 0 or available <= 0.10:
        return 0.0, True, "素材时长未知或不足，渲染时自动取段"
    history = _history_entry(registry, aid)
    recent = history.get("recent_segments") or []
    recent_windows = [
        (_safe_float(item.get("source_start"), 0.0), _safe_float(item.get("source_end"), 0.0))
        for item in recent[-12:] if isinstance(item, dict)
    ]
    slots = sorted({round(available * ratio, 3) for ratio in (0.0, 0.18, 0.36, 0.54, 0.72, 0.90, 1.0)})
    acceptable = []
    for slot in slots:
        end = slot + needed
        worst = max((_segment_overlap_ratio(slot, end, left, right) for left, right in recent_windows if right > left), default=0.0)
        if worst < 0.55:
            acceptable.append(slot)
    pool = acceptable or slots
    seed = int(hashlib.sha256(f"{aid}|{semantic_seed}".encode()).hexdigest()[:8], 16)
    chosen = pool[seed % len(pool)]
    reason = "避开该素材最近使用片段" if acceptable else "整条素材可用片段有限，选择稳定位置"
    return chosen, False, reason


def _motion_profile(asset: dict[str, Any], beat_type: str, duration: float) -> tuple[float, str]:
    intel = asset.get("asset_intelligence") if isinstance(asset.get("asset_intelligence"), dict) else {}
    technical = intel.get("technical") if isinstance(intel.get("technical"), dict) else {}
    motion_text = " ".join(_text(value) for value in (
        _asset_text(asset), intel.get("motion"), intel.get("camera_motion"), intel.get("pace"),
        intel.get("movement"), technical.get("motion"), technical.get("pace"),
    ) if _text(value)).lower()
    fast_terms = ("快切", "快速", "车流", "延时", "奔跑", "fast", "timelapse", "hyperlapse")
    static_terms = ("静态", "固定镜头", "几乎不动", "照片感", "still", "static", "locked shot")
    slow_terms = ("缓慢", "慢推", "慢速", "轻微平移", "航拍", "慢摇", "slow", "gentle", "drone")
    detail_terms = ("合同", "文件", "表格", "条款", "户型图", "屏幕", "特写")
    if any(term in motion_text for term in fast_terms):
        return 1.0, "素材自身已有较快运动，保持原速"
    if any(term in motion_text for term in detail_terms):
        return 1.0, "信息特写需要可读性，保持原速"
    if any(term in motion_text for term in static_terms):
        speed = 1.20 if beat_type == "entity_burst" else 1.15
        return speed, "固定/静态素材自动轻加速"
    if any(term in motion_text for term in slow_terms):
        speed = 1.16 if beat_type == "entity_burst" else 1.10
        if duration >= 7.0:
            speed = min(1.18, speed + 0.03)
        return speed, "慢推/航拍素材自动轻加速"
    return 1.0, "运动节奏正常，保持原速"


def _requested_intents(query: str) -> list[str]:
    lowered = _text(query).lower()
    found: list[str] = []
    for intent, aliases in _INTENT_ALIASES.items():
        if any(alias.lower() in lowered for alias in aliases) and intent not in found:
            found.append(intent)
    return found


def _asset_matches_intent(asset: dict[str, Any], intent: str) -> bool:
    text = _asset_text(asset).lower()
    aliases = _INTENT_ALIASES.get(intent) or (intent,)
    return any(alias.lower() in text for alias in aliases)


def _is_neutral_asset(asset: dict[str, Any]) -> bool:
    text = _asset_text(asset).lower()
    if any(term.lower() in text for term in _UNRELATED_ENTITY_TERMS):
        return False
    return any(term.lower() in text for term in _NEUTRAL_VISUAL_TERMS)


def _enforce_beat_rhythm(units: list[dict[str, Any]], beats: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Long explanatory sentences hold; concrete places micro-cut."""
    if not units or not beats:
        return beats
    output: list[dict[str, Any]] = []
    for beat in beats:
        indexes = sorted(int(x) for x in (beat.get("unit_indexes") or []))
        beat_type = _text(beat.get("beat_type") or "hold")
        if not indexes or beat_type == "entity_burst":
            output.append(dict(beat))
            continue
        max_hold = 11.5 if beat_type == "hold" else 8.0
        # Never split inside a single spoken sentence. Split only between source
        # sentence units when a combined beat becomes genuinely too long.
        if len(indexes) == 1:
            item = dict(beat)
            item["cadence_mode"] = "long_sentence_hold" if units[indexes[0]]["end"] - units[indexes[0]]["start"] >= 6.0 else "semantic_hold"
            output.append(item)
            continue
        chunk: list[int] = []
        chunk_start = units[indexes[0]]["start"]
        for unit_index in indexes:
            candidate_end = units[unit_index]["end"]
            if chunk and candidate_end - chunk_start > max_hold:
                item = dict(beat)
                item["unit_indexes"] = chunk
                item["cadence_mode"] = "semantic_hold"
                item["reason"] = (str(item.get("reason") or "") + "；仅在完整句间分镜").strip("；")
                output.append(item)
                chunk = []
                chunk_start = units[unit_index]["start"]
            chunk.append(unit_index)
        if chunk:
            item = dict(beat)
            item["unit_indexes"] = chunk
            item["cadence_mode"] = "semantic_hold"
            output.append(item)

    merged: list[dict[str, Any]] = []
    for beat in output:
        idx = beat.get("unit_indexes") or []
        span = units[idx[-1]]["end"] - units[idx[0]]["start"] if idx else 0.0
        if (
            merged and span < 2.0 and beat.get("beat_type") == "hold"
            and merged[-1].get("beat_type") == "hold"
            and units[idx[-1]]["end"] - units[merged[-1]["unit_indexes"][0]]["start"] <= 11.5
        ):
            merged[-1]["unit_indexes"] = [*merged[-1]["unit_indexes"], *idx]
            merged[-1]["cadence_mode"] = "semantic_hold"
        else:
            merged.append(dict(beat))
    return merged


def _choose_asset(query: str, candidates: list[dict[str, Any]], registry: dict[str, Any], use_count: dict[str, int], previous_id: str) -> dict[str, Any]:
    valid = [asset for asset in candidates if _asset_url(asset)]
    if not valid:
        raise ValueError("R2 素材库没有可解析的视频 URL")

    intents = _requested_intents(query)
    exact = [asset for asset in valid if intents and all(_asset_matches_intent(asset, intent) for intent in intents)]
    if exact:
        pool = exact
        match_status = "exact_entity"
    elif intents:
        neutral = [asset for asset in valid if _is_neutral_asset(asset)]
        if not neutral:
            raise ValueError(f"缺少语义匹配素材：{'/'.join(intents)}；已阻止随机错配")
        pool = neutral
        match_status = "neutral_fallback"
    else:
        pool = [asset for asset in valid if _asset_id(asset) != previous_id] or valid
        match_status = "semantic_general"

    ranked = sorted(
        ((asset, _score_asset(query, asset, registry, use_count.get(_asset_id(asset), 0), previous_id)) for asset in pool),
        key=lambda item: item[1],
        reverse=True,
    )
    chosen, best_score = ranked[0]
    chosen_id = _asset_id(chosen)
    best_recent3 = _recent_use_count(registry, chosen_id, 3)
    # If a recent asset only wins narrowly, explore a fresh/less-recent candidate.
    # Exact semantic fit still wins when the score gap is material.
    if best_recent3 > 0 or use_count.get(chosen_id, 0) > 0:
        alternatives = [
            (asset, score) for asset, score in ranked[1:]
            if use_count.get(_asset_id(asset), 0) == 0 and _recent_use_count(registry, _asset_id(asset), 3) == 0
        ]
        if alternatives:
            alt, alt_score = alternatives[0]
            if alt_score >= best_score - 18.0:
                chosen, best_score = alt, alt_score
                chosen_id = _asset_id(chosen)
                selection_reason = "匹配度接近，优先采用最近三条未使用素材"
            else:
                selection_reason = "旧素材语义明显更契合，允许高匹配复用"
        else:
            selection_reason = "没有接近质量的新素材，保留最佳匹配"
    else:
        selection_reason = "语义最佳且最近三条未使用"

    result = dict(chosen)
    result["_semantic_match_status"] = match_status
    result["_semantic_requested_intents"] = intents
    result["_semantic_score"] = round(best_score, 3)
    result["_selection_reason"] = selection_reason
    result["_recent_3_use_count"] = _recent_use_count(registry, chosen_id, 3)
    result["_recent_10_use_count"] = _recent_use_count(registry, chosen_id, 10)
    result["_alternatives"] = [
        {"asset_id": _asset_id(asset), "asset_name": _asset_name(asset), "score": round(score, 3)}
        for asset, score in ranked[:4] if _asset_id(asset) != chosen_id
    ][:3]
    return result


def _entity_time_windows(text: str, entities: list[str], start: float, end: float) -> list[tuple[str, float, float]]:
    """Create adjacent, stable micro-shot windows for an explicit place/object list.

    These windows intentionally follow the spoken list order and share the available
    phrase span evenly.  We do not create cuts from commas elsewhere; this helper is
    called only after the semantic director has classified a concrete entity list.
    """
    del text  # The semantic entity order is already preserved by _entities().
    if not entities:
        return []
    span = max(0.01, float(end) - float(start))
    step = span / len(entities)
    windows: list[tuple[str, float, float]] = []
    cursor = float(start)
    for index, entity in enumerate(entities):
        item_start = cursor
        item_end = float(end) if index == len(entities) - 1 else float(start) + step * (index + 1)
        item_end = max(item_start, min(float(end), item_end))
        windows.append((entity, round(item_start, 4), round(item_end, 4)))
        cursor = item_end
    return windows


def _expand_beats(units: list[dict[str, Any]], beats: list[dict[str, Any]]) -> list[dict[str, Any]]:
    expanded: list[dict[str, Any]] = []
    for beat in beats:
        indexes = beat["unit_indexes"]
        start = units[indexes[0]]["start"]
        end = units[indexes[-1]]["end"]
        text = "".join(units[index]["text"] for index in indexes)
        if beat["beat_type"] == "entity_burst" and len(beat.get("entities") or []) >= 2:
            entities = beat["entities"]
            for entity, item_start, item_end in _entity_time_windows(text, entities, start, end):
                expanded.append({
                    **beat,
                    "text": entity,
                    "query": entity,
                    "start": item_start,
                    "end": item_end,
                    "duration": max(0.01, item_end - item_start),
                    "entity": entity,
                    "cadence_mode": "entity_micro_cut",
                })
        else:
            expanded.append({
                **beat,
                "text": text,
                "query": " ".join(beat.get("asset_keywords") or []) + " " + text,
                "start": start,
                "end": end,
                "duration": max(0.8, end - start),
                "entity": "",
                "cadence_mode": beat.get("cadence_mode") or ("long_sentence_hold" if end - start >= 6.0 else "semantic_hold"),
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

    beats = _enforce_beat_rhythm(units, beats)
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
        duration = round(max(0.55, _safe_float(item.get("duration"), 2.8)), 3)
        speed, speed_reason = _motion_profile(chosen, _text(item.get("beat_type")), duration)
        source_start, auto_start, segment_reason = _choose_source_segment_start(
            chosen, registry, duration, speed, f"{item.get('text')}|{item.get('entity')}|{index}"
        )
        title = _asset_name(chosen) or _text(chosen.get("ai_title")) or f"素材 {index}"
        clips.append({
            "id": f"ai_beat_{index}", "index": index, "title": title,
            "scene": _asset_text(chosen) or title, "description": _asset_text(chosen) or title,
            "narration": item["text"], "duration": duration, "duration_seconds": duration,
            "source": "r2", "selection_source": chosen.get("_selection_source") or "auto",
            "manual_locked": chosen.get("_selection_source") == "previous_page",
            "asset_id": aid, "asset_ids": [aid], "asset_url": _asset_url(chosen),
            "asset_name": title,
            "start_time": round(source_start, 3),
            "end_time": round(source_start + duration * speed, 3),
            "auto_start": auto_start,
            "preserve_audio": _text(payload.get("voice_mode") or "tts_with_ambient") != "tts_only",
            "speed": round(speed, 3), "transition": "轻柔淡化",
            "camera": "原片运镜 + 自动轻加速" if speed > 1.001 else "保留原片运镜",
            "beat_type": item["beat_type"], "beat_reason": item.get("reason") or "",
            "speech_start": round(item["start"], 3), "speech_end": round(item["end"], 3),
            "entity": item.get("entity") or "", "semantic_themes": sorted(_themes(item["text"])),
            "cadence_mode": item.get("cadence_mode") or "semantic_hold",
            "speed_reason": speed_reason,
            "segment_selection_reason": segment_reason,
            "history_use_count": int(_safe_float(_history_entry(registry, aid).get("use_count"), 0)),
            "recent_3_use_count": int(chosen.get("_recent_3_use_count") or 0),
            "recent_10_use_count": int(chosen.get("_recent_10_use_count") or 0),
            "current_job_use_count": use_count[aid],
            "semantic_score": _safe_float(chosen.get("_semantic_score"), 0.0),
            "selection_reason": chosen.get("_selection_reason") or "",
            "alternative_assets": chosen.get("_alternatives") or [],
            "semantic_match_status": chosen.get("_semantic_match_status") or "semantic_general",
            "semantic_requested_intents": chosen.get("_semantic_requested_intents") or [],
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
            "asset_library_count": len(candidates),
            "recent_memory_window_jobs": 10,
            "cadence_policy": "long_sentence_hold_entity_micro_cut",
            "auto_speed_enabled": True,
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
    next_payload["enforce_semantic_master_timeline"] = True
    next_payload["ai_shot_beats"] = plan.get("beats") or []
    next_payload["target_duration_seconds"] = (
        plan["target_duration_seconds"]
        or next_payload.get("target_duration_seconds")
        or 30
    )
    return {"payload": next_payload, "plan": plan}

def record_success(settings: Any, job_id: str, clips: list[dict[str, Any]]) -> dict[str, Any]:
    normalized_clips: list[dict[str, Any]] = []
    for item in clips:
        if not isinstance(item, dict):
            continue
        aid = _text(item.get("asset_id"))
        if not aid:
            continue
        normalized_clips.append({
            "asset_id": aid,
            "asset_name": _text(item.get("asset_name") or item.get("title")),
            "source_start": round(_safe_float(item.get("actual_start_time") or item.get("start_time"), 0.0), 3),
            "source_end": round(_safe_float(item.get("actual_end_time") or item.get("end_time"), 0.0), 3),
            "timeline_duration": round(_safe_float(item.get("duration"), 0.0), 3),
            "semantic_role": _text(item.get("beat_type") or item.get("teaching_component") or "hold"),
            "entity": _text(item.get("entity")),
            "cadence_mode": _text(item.get("cadence_mode") or "semantic_hold"),
            "speed": round(_safe_float(item.get("speed"), 1.0), 3),
        })
    ids = [item["asset_id"] for item in normalized_clips]
    with _REGISTRY_LOCK:
        data = _load_registry(settings)
        assets = data.setdefault("assets", {})
        jobs = data.setdefault("jobs", {})
        now = _now()
        for clip in normalized_clips:
            aid = clip["asset_id"]
            entry = assets.setdefault(aid, {})
            entry["use_count"] = int(_safe_float(entry.get("use_count"), 0)) + 1
            entry["last_used_at"] = now
            entry["last_used_job_id"] = job_id
            history = entry.setdefault("jobs", [])
            if job_id not in history:
                history.append(job_id)
            entry["jobs"] = history[-50:]
            recent_segments = entry.setdefault("recent_segments", [])
            recent_segments.append({"job_id": job_id, **clip, "used_at": now})
            entry["recent_segments"] = recent_segments[-30:]
            roles = entry.setdefault("semantic_roles", {})
            role = clip["semantic_role"] or "hold"
            roles[role] = int(_safe_float(roles.get(role), 0)) + 1
        jobs[job_id] = {
            "asset_ids": ids,
            "unique_asset_ids": list(dict.fromkeys(ids)),
            "clips": normalized_clips,
            "created_at": now,
        }
        # Keep a bounded but useful recent-job memory.
        if len(jobs) > 200:
            ordered = sorted(jobs.items(), key=lambda row: _text((row[1] or {}).get("created_at")) if isinstance(row[1], dict) else "")
            for old_job_id, _ in ordered[:-200]:
                jobs.pop(old_job_id, None)
        _save_registry(settings, data)
    return {
        "ok": True,
        "job_id": job_id,
        "asset_ids": ids,
        "unique_asset_count": len(set(ids)),
        "repeat_count": max(0, len(ids) - len(set(ids))),
        "clip_usage_records": len(normalized_clips),
        "registry_file": str(_registry_path(settings)),
    }



# =============================================================================
# V10.40.8.29 NATURAL CADENCE + ASSET MEMORY — TEACHING COMPONENT PLAN
# =============================================================================
def _v28_component_type(text: str, beat_type: str = '') -> str:
    value = _text(text)
    if re.search(r'(流程|第一步|第二步|第三步|签署|支付.*抵扣)', value):
        return 'flow'
    if re.search(r'(三件事|三点|分别|①|②|③|清单|确认)', value):
        return 'checklist'
    if re.search(r'(不等于|≠|不是.*而是|自住.*投资|投资.*自住|对比|区别)', value):
        return 'comparison'
    if re.search(r'(风险|注意|别被|不要|避免|误区|搞错)', value):
        return 'risk'
    if re.search(r'(评论|留言|关注|下一条|告诉我|私信)', value):
        return 'cta'
    if re.search(r'(为什么|怎么|到底|吗|？)', value):
        return 'question'
    if beat_type == 'entity_burst':
        return 'entity_labels'
    if beat_type in {'evidence'}:
        return 'evidence'
    return 'caption_emphasis'


_V27_BUILD_PLAN = build_plan


def build_plan(settings: Any, payload: dict[str, Any], job_id: str) -> dict[str, Any]:
    # UI target duration is a planning hint only. Real start/end values win.
    next_payload = dict(payload)
    units = next_payload.get('semantic_speech_units') or next_payload.get('tts_segments') or []
    real_end = max(
        (_safe_float(item.get('end'), 0.0) for item in units if isinstance(item, dict)),
        default=0.0,
    )
    if real_end > 0:
        next_payload['target_duration_seconds'] = real_end
        next_payload['duration'] = real_end
    plan = _V27_BUILD_PLAN(settings, next_payload, job_id)
    components = []
    for index, clip in enumerate(plan.get('clips') or [], start=1):
        narration = _text(clip.get('narration'))
        beat_type = _text(clip.get('beat_type'))
        component = _v28_component_type(narration, beat_type)
        clip['teaching_component'] = component
        if component != 'caption_emphasis':
            components.append({
                'id': f'component_{index}',
                'clip_id': clip.get('id'),
                'type': component,
                'text': narration[:42],
                'start': _safe_float(clip.get('start_time'), 0.0),
                'duration': _safe_float(clip.get('duration'), 0.0),
            })
    plan['teaching_components'] = components
    plan['duration_policy'] = 'real_tts_authoritative_no_fixed_cut'
    plan['cadence_policy'] = 'long_sentence_hold_entity_micro_cut'
    plan['asset_memory_policy'] = 'recent_3_explore_recent_10_penalty_high_match_reuse'
    plan['slow_footage_auto_speed'] = True
    plan['production_brief_used'] = bool(_text(next_payload.get('production_brief')))
    return plan

# =============================================================================
# V10.40.8.30 STABLE SEQUENCE + CONCRETE-SCENE DIRECTOR
# =============================================================================
# V10_40_8_30_STABLE_SEQUENCE_EFFECTS

# Concrete service/decision scenes are allowed to micro-cut in spoken order.
# Generic framing words such as “用途” remain in the narration but do not create
# an empty visual shot.
_ENTITY_TERMS = tuple(dict.fromkeys((*_ENTITY_TERMS, "交通", "商圈", "租客来源")))
_INTENT_ALIASES = {
    **_INTENT_ALIASES,
    "商圈": ("商圈", "商业街", "商业中心", "商场", "购物中心", "餐饮", "咖啡厅", "mall", "shopping", "commercial district"),
    "租客来源": ("租客", "租房", "白领", "学生", "办公区", "写字楼", "通勤人群", "tenant", "renter", "office worker", "student"),
}
_UNRELATED_ENTITY_TERMS = tuple(sorted(set(_UNRELATED_ENTITY_TERMS) | {"交通", "商圈", "租客来源"}))

_V29_BUILD_PLAN_STABLE_SEQUENCE = build_plan


def _v30_visual_family(asset: dict[str, Any]) -> str:
    text = _asset_text(asset).lower()
    families = (
        ("city_landmark", ("双子塔", "klcc", "天际线", "城市航拍", "城市远景", "skyline", "twin tower", "drone city")),
        ("street_market", ("菜市场", "老街", "街市", "市场", "market street", "wet market")),
        ("cafe", ("咖啡厅", "咖啡馆", "咖啡店", "cafe", "coffee shop")),
        ("mall", ("商场", "购物中心", "商业中心", "mall", "shopping centre", "shopping center")),
        ("school", ("学校", "校园", "大学", "小学", "中学", "school", "campus")),
        ("traffic", ("交通", "道路", "地铁", "轻轨", "车流", "road", "metro", "traffic")),
        ("tenant", ("租客", "白领", "学生", "办公区", "写字楼", "tenant", "office worker")),
        ("contract", ("合同", "签字", "spa", "文件", "条款", "contract", "signing")),
        ("residential", ("住宅", "公寓", "楼盘", "社区", "样板间", "apartment", "condo", "residential")),
    )
    for family, terms in families:
        if any(term in text for term in terms):
            return family
    return ""


def _v30_role_for_text(text: str) -> str:
    value = _text(text)
    if re.search(r"(评论|留言|告诉我|(?:帮你|给你)[^。！？!?，,]{0,16}分析|私信|关注|下一条)", value):
        return "cta"
    if re.search(r"(最看重什么|怎么看|怎么选|吗|？|到底)", value):
        return "question"
    if re.search(r"(别光听|不要只看|别被|风险|注意|误区)", value):
        return "risk"
    if re.search(r"(自住.*投资|投资.*自住|自住.*出租|出租.*自住|对比|区别)", value):
        return "comparison"
    return "hold"


def _v30_split_endgame(text: str, start: float, end: float) -> list[dict[str, Any]]:
    """Split a long closing beat into risk/question/CTA only when the script has
    those actual semantic clauses. This avoids an 8-second skyline ending while
    keeping ordinary long explanations stable.
    """
    duration = max(0.0, end - start)
    if duration < 5.2 or not re.search(r"(评论|留言|告诉我|(?:帮你|给你)[^。！？!?，,]{0,16}分析|私信|关注|最看重什么|别光听|不要只看)", text):
        return []
    raw = [x.strip() for x in re.split(r"(?<=[。！？!?；;])|[，,](?=(?:你|我|别|不要|评论|留言|关注))", text) if x.strip()]
    if len(raw) < 2:
        markers = [m.start() for m in re.finditer(r"(别光听|不要只看|你最看重什么|评论|留言|告诉我|(?:我|我们)?(?:帮你|给你)[^。！？!?，,]{0,16}分析|关注)", text)]
        if len(markers) >= 2:
            raw = []
            cursor = 0
            for position in markers[1:]:
                raw.append(text[cursor:position])
                cursor = position
            raw.append(text[cursor:])
            raw = [x.strip() for x in raw if x.strip()]
    grouped: list[dict[str, str]] = []
    for clause in raw:
        role = _v30_role_for_text(clause)
        if grouped and grouped[-1]["role"] == role:
            grouped[-1]["text"] += clause
        else:
            grouped.append({"role": role, "text": clause})
    meaningful = [item for item in grouped if item["role"] in {"risk", "question", "cta"}]
    if len(meaningful) < 2:
        return []
    weights = [max(3, len(re.sub(r"\s+", "", item["text"]))) for item in grouped]
    total = max(1, sum(weights))
    cursor = start
    output: list[dict[str, Any]] = []
    for index, (item, weight) in enumerate(zip(grouped, weights)):
        item_end = end if index == len(grouped) - 1 else cursor + duration * weight / total
        output.append({
            "text": item["text"],
            "role": item["role"],
            "start": round(cursor, 4),
            "end": round(item_end, 4),
            "duration": round(max(0.7, item_end - cursor), 4),
        })
        cursor = item_end
    return output


def _v30_rank_distinct_asset(
    query: str,
    candidates: list[dict[str, Any]],
    registry: dict[str, Any],
    use_count: dict[str, int],
    previous_id: str,
    previous_family: str,
) -> dict[str, Any] | None:
    valid = [item for item in candidates if _asset_url(item) and _asset_id(item) != previous_id]
    if not valid:
        return None
    intents = _requested_intents(query)
    if intents:
        exact = [item for item in valid if all(_asset_matches_intent(item, intent) for intent in intents)]
        if exact:
            valid = exact
    ranked = sorted(
        valid,
        key=lambda item: _score_asset(query, item, registry, use_count.get(_asset_id(item), 0), previous_id),
        reverse=True,
    )
    for item in ranked:
        family = _v30_visual_family(item)
        if previous_family and family == previous_family and family in {"city_landmark", "street_market", "contract"}:
            continue
        return item
    return ranked[0] if ranked else None


def _v30_apply_asset(
    clip: dict[str, Any],
    asset: dict[str, Any],
    registry: dict[str, Any],
    semantic_seed: str,
) -> dict[str, Any]:
    item = dict(clip)
    aid = _asset_id(asset)
    duration = max(0.55, _safe_float(item.get("duration"), 2.8))
    speed, speed_reason = _motion_profile(asset, _text(item.get("beat_type")), duration)
    source_start, auto_start, segment_reason = _choose_source_segment_start(asset, registry, duration, speed, semantic_seed)
    title = _asset_name(asset) or _text(asset.get("ai_title")) or item.get("asset_name") or "R2 素材"
    item.update({
        "asset_id": aid,
        "asset_ids": [aid],
        "asset_url": _asset_url(asset),
        "asset_name": title,
        "title": title,
        "scene": _asset_text(asset) or title,
        "description": _asset_text(asset) or title,
        "selection_source": asset.get("_selection_source") or "auto",
        "start_time": round(source_start, 3),
        "end_time": round(source_start + duration * speed, 3),
        "auto_start": auto_start,
        "speed": round(speed, 3),
        "speed_reason": speed_reason,
        "segment_selection_reason": segment_reason,
        "visual_family": _v30_visual_family(asset),
    })
    return item


def _v30_resequence_plan(settings: Any, payload: dict[str, Any], job_id: str, plan: dict[str, Any]) -> dict[str, Any]:
    candidates, _ = _candidate_assets(settings, payload)
    by_id = {_asset_id(item): item for item in candidates if _asset_id(item)}
    with _REGISTRY_LOCK:
        registry = _load_registry(settings)
    output: list[dict[str, Any]] = []
    use_count: dict[str, int] = {}
    previous_id = ""
    previous_family = ""

    for source_index, raw_clip in enumerate(plan.get("clips") or [], start=1):
        clip = dict(raw_clip)
        speech_start = _safe_float(clip.get("speech_start"), 0.0)
        speech_end = max(speech_start + 0.2, _safe_float(clip.get("speech_end"), speech_start + _safe_float(clip.get("duration"), 0.0)))
        narration = _text(clip.get("narration"))
        splits = _v30_split_endgame(narration, speech_start, speech_end)
        specs = splits or [{
            "text": narration,
            "role": _v30_role_for_text(narration),
            "start": speech_start,
            "end": speech_end,
            "duration": max(0.55, speech_end - speech_start),
        }]

        for local_index, spec in enumerate(specs, start=1):
            next_clip = dict(clip)
            next_clip["id"] = f"{clip.get('id') or 'clip'}_v30_{local_index}" if len(specs) > 1 else clip.get("id")
            next_clip["narration"] = spec["text"]
            next_clip["duration"] = round(max(0.55, _safe_float(spec.get("duration"), 0.8)), 3)
            next_clip["duration_seconds"] = next_clip["duration"]
            next_clip["speech_start"] = round(_safe_float(spec.get("start"), speech_start), 3)
            next_clip["speech_end"] = round(_safe_float(spec.get("end"), speech_end), 3)
            role = _text(spec.get("role") or next_clip.get("beat_type") or "hold")
            if role in {"risk", "question", "cta", "comparison"}:
                next_clip["beat_type"] = role
                next_clip["cadence_mode"] = "semantic_endgame"
                next_clip["beat_reason"] = "结尾按风险/问题/互动语义收束，禁止单一城市空镜拖满"

            current_asset = by_id.get(_text(next_clip.get("asset_id")))
            current_family = _v30_visual_family(current_asset or next_clip)
            must_replace = (
                not current_asset
                or _text(next_clip.get("asset_id")) == previous_id
                or (previous_family and current_family == previous_family and current_family in {"city_landmark", "street_market", "contract"})
                or len(specs) > 1 and local_index > 1
            )
            if must_replace:
                role_query = {
                    "risk": "风险提醒 合同 条款 注意",
                    "question": "人物 思考 咨询 选择",
                    "cta": "人物 手机 评论 咨询 互动",
                    "comparison": "自住 投资 对比 住宅 租客",
                }.get(role, "")
                query = " ".join(x for x in (role_query, _text(next_clip.get("entity")), spec["text"]) if x)
                replacement = _v30_rank_distinct_asset(query, candidates, registry, use_count, previous_id, previous_family)
                if replacement is not None:
                    next_clip = _v30_apply_asset(next_clip, replacement, registry, f"{job_id}|{source_index}|{local_index}|{query}")
                    next_clip["selection_reason"] = "连续画面去重：改用同语义不同素材/角度"
                    current_asset = replacement
                    current_family = _v30_visual_family(replacement)
            elif current_asset is not None:
                next_clip["visual_family"] = current_family

            # Source trim must follow the newly split timeline duration. Keeping
            # the old source_end would silently reintroduce a long/repeated range.
            source_start = max(0.0, _safe_float(next_clip.get("start_time"), 0.0))
            source_speed = max(0.75, _safe_float(next_clip.get("speed"), 1.0))
            next_clip["end_time"] = round(source_start + _safe_float(next_clip.get("duration"), 0.0) * source_speed, 3)
            aid = _text(next_clip.get("asset_id"))
            if aid:
                use_count[aid] = use_count.get(aid, 0) + 1
            next_clip["sequence_guard"] = {
                "adjacent_same_asset_forbidden": True,
                "adjacent_generic_family_forbidden": True,
                "previous_asset_id": previous_id,
                "previous_visual_family": previous_family,
                "passed": not (aid and aid == previous_id),
            }
            output.append(next_clip)
            previous_id = aid
            previous_family = _text(next_clip.get("visual_family") or current_family)

    for index, clip in enumerate(output, start=1):
        clip["index"] = index
    ids = [_text(item.get("asset_id")) for item in output if _text(item.get("asset_id"))]
    plan = dict(plan)
    plan["clips"] = output
    plan["target_duration_seconds"] = round(sum(_safe_float(item.get("duration"), 0.0) for item in output), 3)
    report = dict(plan.get("usage_report") or {})
    report.update({
        "clip_count": len(output),
        "unique_asset_count": len(set(ids)),
        "repeat_count": max(0, len(ids) - len(set(ids))),
        "asset_ids": ids,
        "adjacent_duplicate_guard": True,
        "generic_family_guard": True,
        "semantic_endgame_split": True,
    })
    plan["usage_report"] = report
    plan["sequence_policy"] = "no_adjacent_asset_or_generic_family_repeat"
    return plan


def build_plan(settings: Any, payload: dict[str, Any], job_id: str) -> dict[str, Any]:
    plan = _V29_BUILD_PLAN_STABLE_SEQUENCE(settings, payload, job_id)
    plan = _v30_resequence_plan(settings, payload, job_id, plan)
    components: list[dict[str, Any]] = []
    for index, clip in enumerate(plan.get("clips") or [], start=1):
        narration = _text(clip.get("narration"))
        component = _v28_component_type(narration, _text(clip.get("beat_type")))
        clip["teaching_component"] = component
        if component != "caption_emphasis":
            components.append({
                "id": f"component_{index}",
                "clip_id": clip.get("id"),
                "type": component,
                "text": narration[:42],
                "start": _safe_float(clip.get("speech_start"), 0.0),
                "duration": _safe_float(clip.get("duration"), 0.0),
            })
    plan["teaching_components"] = components
    plan["version"] = VERSION
    plan["cadence_policy"] = "stable_long_sentence_concrete_scene_micro_cut"
    plan["asset_memory_policy"] = "recent_memory_plus_adjacent_visual_family_guard"
    return plan
