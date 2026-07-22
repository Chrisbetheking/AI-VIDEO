from __future__ import annotations

import hashlib
import json
import math
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "10.40.8.18-clean-semantic-director"
REGISTRY_FILE = "existing_edit_asset_usage.json"
_REGISTRY_LOCK = threading.RLock()

_TRANSITIONS = (
    "但是", "不过", "然而", "其实", "真正", "反而", "所以", "然后", "再看", "最后",
    "如果", "对于", "至于", "第一", "第二", "第三", "第四", "另外", "同时", "而且",
)
_THEME_TERMS = {
    "交通": ("交通", "地铁", "通勤", "线路", "车程", "出行"),
    "配套": ("配套", "商场", "餐饮", "生活", "学校", "医疗"),
    "预算": ("价格", "预算", "租金", "现金流", "回报", "收益"),
    "人群": ("租客", "客户", "白领", "家庭", "自住", "投资"),
    "风险": ("风险", "避坑", "产权", "交付", "退出", "转手"),
    "区域": ("区域", "地段", "板块", "位置", "吉隆坡", "KLCC", "TRX"),
}
_STOP = {"这个", "一个", "我们", "就是", "可以", "视频", "素材", "画面", "项目", "介绍", "相关"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


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


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _asset_url(item: dict[str, Any]) -> str:
    nested = item.get("asset") if isinstance(item.get("asset"), dict) else {}
    return _text(
        item.get("asset_url")
        or item.get("assetUrl")
        or item.get("r2_url")
        or item.get("url")
        or nested.get("url")
        or nested.get("r2_url")
    )


def _asset_id(item: dict[str, Any]) -> str:
    nested = item.get("asset") if isinstance(item.get("asset"), dict) else {}
    url = _asset_url(item)
    return _text(
        item.get("asset_id")
        or item.get("assetId")
        or item.get("id")
        or item.get("r2_key")
        or item.get("filename")
        or nested.get("id")
        or nested.get("asset_id")
        or (hashlib.sha256(url.encode()).hexdigest()[:24] if url else "")
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


def _extract_explicit_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    # Priority follows the user's visible workflow: final edit plan, manual shot plan,
    # generic shot plan, then shot overrides. We never silently replace a valid URL.
    candidates = (
        payload.get("edit_plan"),
        payload.get("manual_shot_plan"),
        payload.get("manualShotPlan"),
        payload.get("shot_plan"),
        payload.get("shotPlan"),
        payload.get("shots"),
    )
    base: list[dict[str, Any]] = []
    for candidate in candidates:
        items = _clip_list(candidate)
        if items and any(_asset_url(item) for item in items):
            base = items
            break

    overrides = _clip_list(payload.get("shot_overrides") or payload.get("shotOverrides"))
    if base and overrides:
        by_id = {
            _text(item.get("id") or item.get("shot_id") or item.get("shotId")): item
            for item in overrides
        }
        merged: list[dict[str, Any]] = []
        for index, item in enumerate(base):
            key = _text(item.get("id") or item.get("shot_id") or item.get("shotId"))
            override = by_id.get(key) or (overrides[index] if index < len(overrides) else {})
            merged.append({**item, **override})
        base = merged
    return base


def _normalize_explicit_plan(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items = _extract_explicit_items(payload)
    clips: list[dict[str, Any]] = []
    for index, item in enumerate(items, 1):
        url = _asset_url(item)
        if not url:
            continue
        aid = _asset_id(item)
        start = max(0.0, _safe_float(item.get("start_time") if item.get("start_time") is not None else item.get("startTime"), 0.0))
        end = _safe_float(item.get("end_time") if item.get("end_time") is not None else item.get("endTime"), 0.0)
        duration = _safe_float(item.get("duration_seconds") or item.get("duration"), 0.0)
        if duration <= 0 and end > start:
            duration = end - start
        duration = max(0.8, duration or 3.2)
        narration = _text(
            item.get("narration")
            or item.get("copy")
            or item.get("text")
            or item.get("script")
            or item.get("voiceover")
        )
        title = _text(item.get("title") or item.get("scene") or item.get("description") or f"镜头 {index}")
        clips.append(
            {
                "id": _text(item.get("id") or f"locked_shot_{index}"),
                "index": index,
                "title": title,
                "scene": _text(item.get("scene") or item.get("description") or title),
                "description": _text(item.get("description") or item.get("scene") or title),
                "narration": narration,
                "duration": round(duration, 3),
                "duration_seconds": round(duration, 3),
                "source": "r2",
                "selection_source": "previous_page",
                "manual_locked": True,
                "asset_id": aid,
                "asset_ids": [aid],
                "asset_url": url,
                "asset_name": _text(item.get("asset_name") or item.get("assetName") or title),
                "start_time": start,
                "end_time": round(end if end > start else start + duration, 3),
                "auto_start": False,
                "preserve_audio": bool(item.get("preserve_audio") if item.get("preserve_audio") is not None else item.get("preserveAudio", False)),
                "speed": max(0.75, min(1.5, _safe_float(item.get("speed"), 1.0))),
                "transition": _text(item.get("transition") or "轻柔淡化"),
                "camera": _text(item.get("camera") or item.get("motion") or "保留原片运镜"),
            }
        )
    return clips


def _script_segments(payload: dict[str, Any]) -> list[str]:
    values = []
    for item in payload.get("script_segments") or []:
        if isinstance(item, dict):
            text = _text(item.get("text") or item.get("narration") or item.get("copy"))
            if text:
                values.append(text)
    if values:
        return values
    raw = _text(payload.get("script_text") or payload.get("script") or "")
    return [x for x in re.split(r"(?<=[。！？!?；;])", raw) if _text(x)]


def _insert_transition_boundaries(text: str) -> str:
    output = text
    for token in _TRANSITIONS:
        output = re.sub(rf"(?<!^){re.escape(token)}", f"|{token}", output)
    return output


def _split_long_clause(clause: str, max_chars: int) -> list[str]:
    clause = clause.strip(" ，,。！？!?；;、：:")
    if not clause:
        return []
    if len(clause) <= max_chars:
        return [clause]
    comma_parts = [x for x in re.split(r"[，,、：:]+", _insert_transition_boundaries(clause)) if x]
    output: list[str] = []
    buffer = ""
    for part in comma_parts:
        for atom in [x for x in part.split("|") if x]:
            if buffer and len(buffer) + len(atom) > max_chars:
                output.append(buffer)
                buffer = atom
            else:
                buffer += atom
    if buffer:
        output.append(buffer)
    if len(output) <= 1:
        # One sentence may use one or two shots, but never character-by-character cuts.
        midpoint = max(8, min(len(clause) - 8, len(clause) // 2))
        output = [clause[:midpoint], clause[midpoint:]]
    return [x for x in output if x]


def semantic_clauses(payload: dict[str, Any], pace: str = "balanced") -> list[str]:
    max_chars = {"calm": 28, "balanced": 23, "punchy": 19}.get(pace, 23)
    output: list[str] = []
    for segment in _script_segments(payload):
        sentences = [x for x in re.split(r"[。！？!?；;]+", segment) if _text(x)]
        for sentence in sentences or [segment]:
            output.extend(_split_long_clause(sentence, max_chars))
    # Merge tiny fragments back into their neighbor. Subtitle fragments never define shots.
    merged: list[str] = []
    for item in output:
        if merged and len(item) <= 4:
            merged[-1] += item
        elif merged and len(merged[-1]) <= 4:
            merged[-1] += item
        else:
            merged.append(item)
    return merged[:36]


def _tokens(text: str) -> set[str]:
    raw = _text(text).lower()
    words = re.findall(r"[a-z0-9_]{2,}|[\u4e00-\u9fff]{2,}", raw)
    zh = "".join(re.findall(r"[\u4e00-\u9fff]", raw))
    words += [zh[i : i + 2] for i in range(max(0, len(zh) - 1))]
    return {x for x in words if x not in _STOP}


def _asset_text(asset: dict[str, Any]) -> str:
    intel = asset.get("asset_intelligence") if isinstance(asset.get("asset_intelligence"), dict) else {}
    values = [
        asset.get("original_name"), asset.get("filename"), asset.get("ai_title"),
        asset.get("ai_description"), asset.get("ai_primary_category"), asset.get("ai_secondary_category"),
        intel.get("title"), intel.get("description"), intel.get("primary_category"),
        intel.get("secondary_category"), intel.get("scene"), intel.get("location"),
        " ".join(asset.get("ai_keywords") or []), " ".join(intel.get("keywords") or []),
    ]
    return " ".join(_text(x) for x in values if x)


def _themes(text: str) -> set[str]:
    return {name for name, terms in _THEME_TERMS.items() if any(term.lower() in text.lower() for term in terms)}


def _candidate_assets(settings: Any, payload: dict[str, Any]) -> list[dict[str, Any]]:
    classic = _classic()
    selected_raw = (
        payload.get("selected_assets")
        or payload.get("asset_context")
        or payload.get("r2_material_context")
        or []
    )
    selected = [dict(x) for x in selected_raw if isinstance(x, dict)]
    library = classic._load_library_assets(settings)
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source, items in (("manual", selected), ("auto", library)):
        for item in items:
            aid = classic._asset_id(item)
            url = classic._asset_url(item)
            if not aid or not url or aid in seen or not classic._eligible_video(item):
                continue
            candidate = dict(item)
            candidate["_selection_source"] = source
            result.append(candidate)
            seen.add(aid)
    return result


def _history_entry(registry: dict[str, Any], aid: str) -> dict[str, Any]:
    raw = (registry.get("assets") or {}).get(aid) or {}
    return raw if isinstance(raw, dict) else {}


def _score_asset(clause: str, asset: dict[str, Any], registry: dict[str, Any], current_use: int) -> float:
    classic = _classic()
    aid = classic._asset_id(asset)
    history = _history_entry(registry, aid)
    text = _asset_text(asset)
    overlap = len(_tokens(clause) & _tokens(text))
    theme_overlap = len(_themes(clause) & _themes(text))
    quality = _safe_float(asset.get("ai_quality_score") or (asset.get("asset_intelligence") or {}).get("quality_score"), 60)
    manual_bonus = 25.0 if asset.get("_selection_source") == "manual" else 0.0
    fresh_bonus = 20.0 if not history else 0.0
    historical_count = int(_safe_float(history.get("use_count"), 0))
    recent_jobs = history.get("jobs") if isinstance(history.get("jobs"), list) else []
    return (
        overlap * 10.0
        + theme_overlap * 18.0
        + quality / 16.0
        + manual_bonus
        + fresh_bonus
        - current_use * 110.0
        - historical_count * 7.0
        - min(30.0, len(recent_jobs[-5:]) * 4.0)
    )


def _weighted_durations(clauses: list[str], target: float, pace: str) -> list[float]:
    if not clauses:
        return []
    target = max(float(target or 30.0), len(clauses) * 1.2)
    weights = [max(5, len(x)) for x in clauses]
    raw = [target * weight / sum(weights) for weight in weights]
    low, high = {
        "calm": (2.4, 5.4),
        "balanced": (1.9, 4.6),
        "punchy": (1.6, 3.8),
    }.get(pace, (1.9, 4.6))
    clipped = [min(high, max(low, x)) for x in raw]
    scale = target / sum(clipped)
    values = [round(x * scale, 3) for x in clipped]
    values[-1] = round(values[-1] + target - sum(values), 3)
    return values


def _auto_plan(settings: Any, payload: dict[str, Any], job_id: str) -> list[dict[str, Any]]:
    pace = _text(payload.get("dynamic_visual_pace") or "balanced")
    clauses = semantic_clauses(payload, pace)
    if not clauses:
        raise ValueError("缺少可用于语义切镜的口播文案")
    target = _safe_float(payload.get("target_duration_seconds") or payload.get("duration"), 30.0)
    durations = _weighted_durations(clauses, target, pace)
    candidates = _candidate_assets(settings, payload)
    if not candidates:
        raise ValueError("R2 素材库没有可用视频，无法生成语义镜头计划")
    with _REGISTRY_LOCK:
        registry = _load_registry(settings)
    classic = _classic()
    use_count: dict[str, int] = {}
    unused = {classic._asset_id(x) for x in candidates}
    clips: list[dict[str, Any]] = []
    previous_id = ""
    for index, (clause, duration) in enumerate(zip(clauses, durations), 1):
        pool = [x for x in candidates if classic._asset_id(x) in unused]
        if not pool:
            pool = [x for x in candidates if classic._asset_id(x) != previous_id] or candidates
        ranked = sorted(
            pool,
            key=lambda asset: _score_asset(clause, asset, registry, use_count.get(classic._asset_id(asset), 0)),
            reverse=True,
        )
        chosen = ranked[0]
        aid = classic._asset_id(chosen)
        unused.discard(aid)
        use_count[aid] = use_count.get(aid, 0) + 1
        previous_id = aid
        title = _text(chosen.get("ai_title") or chosen.get("original_name") or chosen.get("filename") or f"素材 {index}")
        clips.append(
            {
                "id": f"semantic_shot_{index}", "index": index, "title": title,
                "scene": _asset_text(chosen) or title, "description": _asset_text(chosen) or title,
                "narration": clause, "duration": duration, "duration_seconds": duration,
                "source": "r2", "selection_source": chosen.get("_selection_source") or "auto",
                "manual_locked": chosen.get("_selection_source") == "manual",
                "asset_id": aid, "asset_ids": [aid], "asset_url": classic._asset_url(chosen),
                "asset_name": _text(chosen.get("original_name") or chosen.get("filename") or title),
                "start_time": 0.0, "end_time": duration, "auto_start": True,
                "preserve_audio": _text(payload.get("voice_mode") or "tts_with_ambient") != "tts_only",
                "speed": 1.0, "transition": "轻柔淡化", "camera": "保留原片运镜",
                "semantic_themes": sorted(_themes(clause)),
                "history_use_count": int(_safe_float(_history_entry(registry, aid).get("use_count"), 0)),
                "current_job_use_count": use_count[aid],
            }
        )
    return clips


def build_plan(settings: Any, payload: dict[str, Any], job_id: str) -> dict[str, Any]:
    explicit = _normalize_explicit_plan(payload)
    source = "previous_page_shot_plan" if explicit else "semantic_auto_selection"
    clips = explicit or _auto_plan(settings, payload, job_id)
    total = round(sum(_safe_float(x.get("duration"), 0.0) for x in clips), 3)
    ids = [_text(x.get("asset_id")) for x in clips]
    unique = len(set(ids))
    return {
        "ok": True,
        "version": VERSION,
        "source": source,
        "locked": bool(explicit),
        "clips": clips,
        "target_duration_seconds": total,
        "usage_report": {
            "clip_count": len(clips),
            "unique_asset_count": unique,
            "repeat_count": max(0, len(clips) - unique),
            "asset_ids": ids,
            "registry_file": str(_registry_path(settings)),
        },
    }


def prepare_classic_payload(settings: Any, payload: dict[str, Any], job_id: str) -> dict[str, Any]:
    plan = build_plan(settings, payload, job_id)
    next_payload = dict(payload)
    next_payload["burn_subtitles"] = False
    next_payload["edit_plan"] = {"clips": plan["clips"], "source": plan["source"], "version": VERSION}
    next_payload["lock_edit_plan"] = True
    next_payload["material_selection_mode"] = "manual"
    next_payload["asset_usage_job_id"] = job_id
    next_payload["semantic_director_version"] = VERSION
    next_payload["target_duration_seconds"] = plan["target_duration_seconds"] or next_payload.get("target_duration_seconds") or 30
    return {"payload": next_payload, "plan": plan}


def record_success(settings: Any, job_id: str, clips: list[dict[str, Any]]) -> dict[str, Any]:
    ids = [_text(item.get("asset_id")) for item in clips if _text(item.get("asset_id"))]
    with _REGISTRY_LOCK:
        data = _load_registry(settings)
        assets = data.setdefault("assets", {})
        jobs = data.setdefault("jobs", {})
        for aid in ids:
            item = assets.setdefault(aid, {"use_count": 0, "jobs": []})
            item["use_count"] = int(_safe_float(item.get("use_count"), 0)) + 1
            item["last_used_at"] = _now()
            job_ids = item.setdefault("jobs", [])
            if job_id not in job_ids:
                job_ids.append(job_id)
                del job_ids[:-30]
        jobs[job_id] = {"asset_ids": ids, "unique_asset_count": len(set(ids)), "created_at": _now()}
        if len(jobs) > 200:
            for old in sorted(jobs, key=lambda key: _text(jobs[key].get("created_at")))[:-200]:
                jobs.pop(old, None)
        _save_registry(settings, data)
    return {"asset_ids": ids, "unique_asset_count": len(set(ids)), "repeat_count": max(0, len(ids) - len(set(ids)))}
