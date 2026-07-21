from __future__ import annotations

import json
import math
import re
import subprocess
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any

VERSION = "10.40.8.12-a10-r4"

_FAMILY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "aerial_city": (
        "双子塔", "klcc", "天际线", "航拍", "地标", "城市全景", "tower",
        "skyline", "aerial", "petronas", "市中心", "高楼", "建筑外观",
    ),
    "street_transport": (
        "交通", "地铁", "轻轨", "道路", "车流", "通勤", "出行", "步行",
        "公交", "捷运", "lrt", "mrt", "rail", "road", "street", "traffic",
    ),
    "residential_interior": (
        "户型", "室内", "客厅", "卧室", "厨房", "公寓", "住宅", "样板间",
        "condo", "interior", "living room", "bedroom", "home", "unit",
    ),
    "lifestyle_commercial": (
        "生活半径", "配套", "商场", "超市", "餐饮", "食物", "医院", "学校",
        "便利店", "商业", "社区", "生活", "mall", "shopping", "food",
        "restaurant", "amenities", "clinic", "school", "commercial",
    ),
    "people_transaction": (
        "租客", "买家", "投资", "自住", "交易", "中介", "白领", "办公",
        "出租", "转手", "租赁", "tenant", "buyer", "agent", "office",
        "investment", "rental", "resale", "people",
    ),
    "construction_delivery": (
        "交付", "施工", "工地", "在建", "工程", "进度", "建设", "开发商",
        "delivery", "construction", "site", "developer", "building progress",
    ),
    "map_data": (
        "区域用途", "区域", "地图", "规划", "板块", "距离", "位置", "范围",
        "map", "location", "district", "zoning", "planning", "area use",
    ),
    "risk_detail": (
        "风险", "成本", "维护", "物业", "预算", "价格", "贷款", "费用",
        "risk", "cost", "maintenance", "budget", "price", "fee",
    ),
}

_IMPORTANT_PHRASES = (
    "吉隆坡", "很容易买错", "自住还是投资", "生活半径", "真实配套",
    "租客来源", "未来转手", "二手市场流动性", "现有交通", "交通",
    "交付周期", "区域用途", "物业维护成本", "风险", "再去看房",
)


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return " ".join(_text(item) for item in value)
    if isinstance(value, dict):
        return " ".join(_text(item) for item in value.values())
    return str(value)


def _asset_id(asset: dict[str, Any]) -> str:
    return str(
        asset.get("id")
        or asset.get("asset_id")
        or asset.get("r2_key")
        or asset.get("filename")
        or asset.get("asset_url")
        or asset.get("url")
        or ""
    ).strip()


def _asset_url(asset: dict[str, Any]) -> str:
    return str(
        asset.get("asset_url")
        or asset.get("url")
        or asset.get("r2_url")
        or ""
    ).strip()


def _intel(asset: dict[str, Any]) -> dict[str, Any]:
    value = asset.get("asset_intelligence") or asset.get("intelligence") or {}
    return dict(value) if isinstance(value, dict) else {}


def _asset_blob(asset: dict[str, Any]) -> str:
    intel = _intel(asset)
    return _text(
        [
            asset.get("original_name"), asset.get("filename"), asset.get("name"),
            asset.get("title"), asset.get("description"), asset.get("scene"),
            asset.get("analysis_description"), asset.get("primary_category"),
            asset.get("secondary_category"), asset.get("ai_title"),
            asset.get("ai_description"), asset.get("ai_primary_category"),
            asset.get("ai_secondary_category"), asset.get("ai_keywords"),
            intel,
        ]
    ).lower()


def _tokens(value: Any) -> set[str]:
    text = _text(value).lower()
    words = set(re.findall(r"[a-z0-9_]{2,}", text))
    zh = "".join(re.findall(r"[\u4e00-\u9fff]", text))
    for width in (2, 3, 4):
        words.update(zh[i : i + width] for i in range(max(0, len(zh) - width + 1)))
    return {word for word in words if word}


def _scene_family(value: Any, *, fallback: str = "generic") -> str:
    text = _text(value).lower()
    scores = {
        family: sum(3 if len(word) >= 4 else 1 for word in words if word in text)
        for family, words in _FAMILY_KEYWORDS.items()
    }
    if not scores or max(scores.values(), default=0) <= 0:
        return fallback
    return max(scores, key=scores.get)


def _cluster_id(asset: dict[str, Any]) -> str:
    intel = _intel(asset)
    for key in (
        "visual_cluster_id", "perceptual_cluster_id", "scene_cluster_id",
        "phash", "dhash", "frame_hash", "duplicate_group",
    ):
        value = asset.get(key) or intel.get(key)
        if value:
            return f"explicit:{str(value).strip()}"
    blob = _asset_blob(asset)
    if any(word in blob for word in ("双子塔", "klcc", "petronas")):
        return "semantic:klcc_petronas_landmark"
    if any(word in blob for word in ("merdeka 118", "默迪卡118", "独立118")):
        return "semantic:merdeka_118_landmark"
    return f"asset:{_asset_id(asset)}"


def _quality(asset: dict[str, Any]) -> float:
    intel = _intel(asset)
    for value in (
        asset.get("quality_score"), asset.get("ai_quality_score"),
        intel.get("quality_score"), intel.get("score"),
    ):
        try:
            return max(0.0, min(100.0, float(value)))
        except (TypeError, ValueError):
            pass
    return 60.0


def _normalise_asset(asset: dict[str, Any], source: str) -> dict[str, Any] | None:
    item = dict(asset)
    aid = _asset_id(item)
    url = _asset_url(item)
    if not aid or not url:
        return None
    kind = str(item.get("kind") or "video").lower()
    if kind not in {"video", "movie", "clip", ""}:
        return None
    item["id"] = aid
    item["asset_id"] = aid
    item["asset_url"] = url
    item["url"] = url
    item["selection_source"] = str(item.get("selection_source") or source)
    item["scene_family"] = str(
        item.get("scene_family") or _scene_family(_asset_blob(item))
    )
    item["visual_cluster_id"] = _cluster_id(item)
    item["quality_score"] = _quality(item)
    return item


def _load_library_assets(settings: Any) -> list[dict[str, Any]]:
    if settings is None:
        return []
    try:
        from app.services.asset_intelligence_v10_40_8_4_3 import _assets_map, _load_index
        assets = _assets_map(settings)
        index = _load_index(settings)
    except Exception:
        return []
    output: list[dict[str, Any]] = []
    for aid, raw in (assets or {}).items():
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        item.setdefault("id", aid)
        record = index.get(aid) if isinstance(index, dict) else None
        if isinstance(record, dict):
            item["asset_intelligence"] = {**_intel(item), **record}
        normalised = _normalise_asset(item, "library")
        if normalised:
            output.append(normalised)
    return output


def _candidate_pool(
    settings: Any,
    payload: dict[str, Any],
    clips: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    raw_items: list[tuple[dict[str, Any], str]] = []
    for key, source in (
        ("selected_assets", "manual"),
        ("asset_context", "context"),
        ("r2_material_context", "context"),
    ):
        for item in payload.get(key) or []:
            if isinstance(item, dict):
                raw_items.append((dict(item), source))
    for clip in clips:
        if not isinstance(clip, dict):
            continue
        item = {
            **clip,
            "id": clip.get("asset_id") or clip.get("id"),
            "url": clip.get("asset_url") or clip.get("url"),
            "name": clip.get("asset_name") or clip.get("title"),
            "kind": "video",
        }
        raw_items.append((item, "director"))
    raw_items.extend((item, "library") for item in _load_library_assets(settings))
    seen: set[str] = set()
    output: list[dict[str, Any]] = []
    for raw, source in raw_items:
        item = _normalise_asset(raw, source)
        if not item:
            continue
        aid = item["asset_id"]
        if aid in seen:
            continue
        seen.add(aid)
        output.append(item)
    return output


def _clip_narration(clip: dict[str, Any]) -> str:
    return str(
        clip.get("narration")
        or clip.get("text")
        or clip.get("scene")
        or clip.get("description")
        or ""
    )


def _score_asset(
    narration: str,
    required_family: str,
    asset: dict[str, Any],
    *,
    index: int,
    total: int,
) -> float:
    family = str(asset.get("scene_family") or "generic")
    overlap = len(_tokens(narration) & _tokens(_asset_blob(asset)))
    score = overlap * 11.0 + float(asset.get("quality_score") or 60) / 10.0
    if family == required_family:
        score += 95.0
    elif family == "generic":
        score += 10.0
    if asset.get("selection_source") == "manual":
        score += 8.0
    if index == total - 1 and family == "aerial_city":
        score -= 38.0
    return score


def _apply_asset_to_clip(
    clip: dict[str, Any],
    asset: dict[str, Any],
    *,
    reason: str,
    semantic_score: float,
) -> dict[str, Any]:
    result = dict(clip)
    aid = str(asset["asset_id"])
    result.update(
        {
            "source": "r2",
            "asset_id": aid,
            "asset_ids": [aid],
            "asset_url": str(asset["asset_url"]),
            "asset_name": str(
                asset.get("original_name")
                or asset.get("filename")
                or asset.get("name")
                or asset.get("title")
                or aid
            ),
            "title": str(
                asset.get("title")
                or asset.get("ai_title")
                or asset.get("name")
                or result.get("title")
                or aid
            ),
            "scene_family": str(asset.get("scene_family") or "generic"),
            "visual_cluster_id": str(asset.get("visual_cluster_id") or _cluster_id(asset)),
            "selection_source": str(asset.get("selection_source") or "library"),
            "a10_r4_selection_reason": reason,
            "a10_r4_semantic_score": round(float(semantic_score), 3),
        }
    )
    return result


def _select_assets(
    clips: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not clips or not candidates:
        return clips, {
            "strict_single_use_possible": False,
            "relaxations": ["empty_clip_or_candidate_pool"],
        }
    total = len(clips)
    unique_cluster_count = len({str(item["visual_cluster_id"]) for item in candidates})
    strict_possible = len(candidates) >= total and unique_cluster_count >= total
    max_aerial = max(1, int(math.floor(total * 0.35)))
    used_assets: Counter[str] = Counter()
    used_clusters: Counter[str] = Counter()
    family_counts: Counter[str] = Counter()
    relaxations: list[str] = []
    selected: list[dict[str, Any]] = []

    for index, clip in enumerate(clips):
        narration = _clip_narration(clip)
        required = _scene_family(narration)
        ranked = sorted(
            candidates,
            key=lambda asset: _score_asset(
                narration, required, asset, index=index, total=total
            ),
            reverse=True,
        )

        def allowed(asset: dict[str, Any], level: int) -> bool:
            aid = str(asset["asset_id"])
            cluster = str(asset["visual_cluster_id"])
            family = str(asset.get("scene_family") or "generic")
            if level <= 0 and (used_assets[aid] or used_clusters[cluster]):
                return False
            if level <= 1 and used_clusters[cluster]:
                return False
            if family == "aerial_city" and family_counts[family] >= max_aerial:
                return False
            if len(selected) >= 2:
                previous = [str(item.get("scene_family") or "generic") for item in selected[-2:]]
                if previous == [family, family]:
                    return False
            if index == total - 1 and level <= 2 and used_assets[aid]:
                return False
            return True

        chosen: dict[str, Any] | None = None
        chosen_level = 0
        if bool(clip.get("manual_locked")):
            current_id = str(clip.get("asset_id") or "")
            chosen = next(
                (asset for asset in ranked if str(asset.get("asset_id") or "") == current_id),
                None,
            )
            if chosen:
                chosen_level = 5
                relaxations.append(f"slot_{index + 1}_manual_lock_preserved")
        if not chosen:
            for level in range(4):
                chosen = next((asset for asset in ranked if allowed(asset, level)), None)
                if chosen:
                    chosen_level = level
                    break
        if not chosen:
            chosen = ranked[0]
            chosen_level = 4
        if chosen_level:
            relaxations.append(f"slot_{index + 1}_relax_{chosen_level}")
        aid = str(chosen["asset_id"])
        cluster = str(chosen["visual_cluster_id"])
        score = _score_asset(narration, required, chosen, index=index, total=total)
        reason = (
            "strict_unseen_semantic_match"
            if chosen_level == 0
            else f"semantic_match_relaxation_{chosen_level}"
        )
        updated = _apply_asset_to_clip(
            clip, chosen, reason=reason, semantic_score=score
        )
        selected.append(updated)
        used_assets[aid] += 1
        used_clusters[cluster] += 1
        family_counts[str(updated.get("scene_family") or "generic")] += 1

    supported_families = {
        str(item.get("scene_family") or "generic") for item in candidates
    } - {"generic"}
    required_diversity = min(4, len(supported_families), total)
    missing = [family for family in sorted(supported_families) if family not in family_counts]
    if required_diversity and len([x for x in family_counts if x != "generic"]) < required_diversity:
        replace_positions = [
            int(round((total - 1) * fraction)) for fraction in (0.2, 0.45, 0.7, 0.88)
        ]
        for family, position in zip(missing, replace_positions):
            if len([x for x in family_counts if x != "generic"]) >= required_diversity:
                break
            alternatives = [
                asset for asset in candidates
                if asset.get("scene_family") == family
                and not used_assets[str(asset["asset_id"])]
                and not used_clusters[str(asset["visual_cluster_id"])]
            ]
            if not alternatives:
                continue
            old = selected[position]
            old_aid = str(old.get("asset_id") or "")
            old_cluster = str(old.get("visual_cluster_id") or "")
            old_family = str(old.get("scene_family") or "generic")
            chosen = max(alternatives, key=lambda item: _quality(item))
            selected[position] = _apply_asset_to_clip(
                old,
                chosen,
                reason="scene_diversity_rebalance",
                semantic_score=_score_asset(
                    _clip_narration(old), family, chosen, index=position, total=total
                ),
            )
            used_assets[old_aid] -= 1
            used_clusters[old_cluster] -= 1
            family_counts[old_family] -= 1
            used_assets[str(chosen["asset_id"])] += 1
            used_clusters[str(chosen["visual_cluster_id"])] += 1
            family_counts[family] += 1

    asset_counts = Counter(str(item.get("asset_id") or "") for item in selected)
    cluster_counts = Counter(str(item.get("visual_cluster_id") or "") for item in selected)
    family_counts = Counter(str(item.get("scene_family") or "generic") for item in selected)
    ending_fresh = bool(selected) and asset_counts[str(selected[-1].get("asset_id") or "")] == 1
    report = {
        "strict_single_use_possible": strict_possible,
        "candidate_asset_count": len(candidates),
        "candidate_visual_cluster_count": unique_cluster_count,
        "selected_asset_count": len(selected),
        "asset_use_counts": dict(asset_counts),
        "visual_cluster_use_counts": dict(cluster_counts),
        "scene_family_counts": dict(family_counts),
        "scene_family_count": len([key for key, value in family_counts.items() if value > 0]),
        "maximum_asset_reuse": max(asset_counts.values(), default=0),
        "maximum_visual_cluster_reuse": max(cluster_counts.values(), default=0),
        "aerial_city_share": round(family_counts.get("aerial_city", 0) / max(1, total), 4),
        "aerial_city_maximum_share": 0.35,
        "fresh_ending_asset": ending_fresh,
        "relaxations": relaxations,
    }
    return selected, report


def _spread_keywords(
    timings: list[dict[str, Any]],
    existing: list[str],
    target_duration: float,
) -> tuple[list[str], dict[str, Any]]:
    candidates: list[tuple[str, float]] = []
    seen: set[str] = set()
    for item in timings:
        text = str(item.get("text") or "")
        start = float(item.get("start") or 0)
        end = float(item.get("end") or start)
        center = (start + end) / 2
        matches = [phrase for phrase in _IMPORTANT_PHRASES if phrase in text]
        if not matches:
            clean = re.sub(r"[，。！？、；：,.!?;:\s]+", "", text)
            if 2 <= len(clean) <= 10:
                matches = [clean]
            elif len(clean) > 10:
                matches = [clean[:8]]
        for phrase in matches:
            if phrase and phrase not in seen:
                seen.add(phrase)
                candidates.append((phrase, center))
    for phrase in existing:
        phrase = str(phrase or "").strip()
        if phrase and phrase not in seen:
            seen.add(phrase)
            candidates.append((phrase, target_duration / 2))

    desired = 6 if target_duration >= 26 else 5 if target_duration >= 18 else 4
    desired = min(desired, len(candidates))
    if desired <= 0:
        return existing[:6], {"count": len(existing[:6]), "positions": []}
    target_positions = [
        target_duration * fraction
        for fraction in ([0.08, 0.25, 0.43, 0.61, 0.79, 0.93][:desired])
    ]
    selected: list[tuple[str, float]] = []
    remaining = list(candidates)
    for target in target_positions:
        if not remaining:
            break
        item = min(remaining, key=lambda pair: abs(pair[1] - target))
        selected.append(item)
        remaining.remove(item)
    selected.sort(key=lambda pair: pair[1])
    keywords = [phrase for phrase, _ in selected]
    positions = [round(center, 3) for _, center in selected]
    gaps = [round(positions[i] - positions[i - 1], 3) for i in range(1, len(positions))]
    return keywords, {
        "count": len(keywords),
        "positions": positions,
        "gaps": gaps,
        "timeline_coverage_ratio": round(
            (positions[-1] - positions[0]) / max(0.001, target_duration), 4
        ) if len(positions) >= 2 else 0.0,
    }


def _shape_clip_timeline(
    clips: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Fix only clearly bad pacing without moving the total narration duration.

    - The opening shot is never shorter than 0.7s when the second shot can lend time.
    - Shots longer than 2.8s are split in place, so later timeline boundaries do not move.
    - Extra split shots are unlocked so the visual selector can assign fresh footage.
    """
    shaped = [dict(item) for item in clips]
    changes: list[dict[str, Any]] = []
    if len(shaped) >= 2:
        first = max(0.0, float(shaped[0].get("duration") or 0))
        second = max(0.0, float(shaped[1].get("duration") or 0))
        if first < 0.7 and second > 1.3 + (0.7 - first):
            delta = 0.7 - first
            shaped[0]["duration"] = round(0.7, 3)
            shaped[0]["duration_seconds"] = round(0.7, 3)
            shaped[1]["duration"] = round(second - delta, 3)
            shaped[1]["duration_seconds"] = round(second - delta, 3)
            changes.append({
                "type": "hook_minimum",
                "from": round(first, 3),
                "to": 0.7,
                "borrowed_from_next": round(delta, 3),
            })

    output: list[dict[str, Any]] = []
    for item in shaped:
        duration = max(0.05, float(item.get("duration") or 0))
        maximum = 2.8
        pieces = max(1, int(math.ceil(duration / maximum)))
        if pieces == 1:
            output.append(item)
            continue
        base = round(duration / pieces, 3)
        piece_durations = [base for _ in range(pieces)]
        piece_durations[-1] = round(
            piece_durations[-1] + duration - sum(piece_durations), 3
        )
        changes.append({
            "type": "split_long_shot",
            "asset_id": str(item.get("asset_id") or ""),
            "from": round(duration, 3),
            "pieces": piece_durations,
        })
        for piece_index, piece_duration in enumerate(piece_durations):
            piece = dict(item)
            piece["duration"] = piece_duration
            piece["duration_seconds"] = piece_duration
            piece["a10_r4_split_piece"] = piece_index + 1
            piece["a10_r4_split_total"] = pieces
            if piece_index > 0:
                piece["manual_locked"] = False
                piece["selection_source"] = "a10_r4_split_autofill"
            output.append(piece)

    for index, item in enumerate(output, start=1):
        item["index"] = index
        item["id"] = f"a10_r4_clip_{index}"
    return output, {
        "changed": bool(changes),
        "changes": changes,
        "input_shot_count": len(clips),
        "output_shot_count": len(output),
        "timeline_seconds": round(
            sum(float(item.get("duration") or 0) for item in output), 3
        ),
    }


def _duration_guard(clips: list[dict[str, Any]]) -> dict[str, Any]:
    if not clips:
        return {"first_shot_seconds": 0, "maximum_shot_seconds": 0, "warnings": []}
    durations = [max(0.0, float(item.get("duration") or 0)) for item in clips]
    warnings: list[str] = []
    if durations[0] < 0.7:
        warnings.append("hook_shot_below_0_7_seconds")
    if max(durations, default=0) > 3.2:
        warnings.append("shot_above_3_2_seconds")
    for item, duration in zip(clips, durations):
        if str(item.get("scene_family") or "") == "aerial_city" and duration > 3.0:
            warnings.append("static_city_shot_above_3_seconds")
            break
    return {
        "first_shot_seconds": round(durations[0], 3),
        "minimum_shot_seconds": round(min(durations), 3),
        "maximum_shot_seconds": round(max(durations), 3),
        "average_shot_seconds": round(sum(durations) / max(1, len(durations)), 3),
        "recommended_hook_minimum_seconds": 0.7,
        "recommended_normal_range_seconds": [1.3, 2.8],
        "recommended_static_city_maximum_seconds": 3.0,
        "warnings": sorted(set(warnings)),
    }


def apply_a10_r4_director_guard(
    *,
    settings: Any,
    director_result: dict[str, Any],
    payload: dict[str, Any],
    target_duration: float,
) -> dict[str, Any]:
    result = deepcopy(director_result)
    clips = [dict(item) for item in result.get("clips") or [] if isinstance(item, dict)]
    clips, timeline_shape_report = _shape_clip_timeline(clips)
    timings = [
        dict(item) for item in result.get("subtitle_segments") or [] if isinstance(item, dict)
    ]
    candidates = _candidate_pool(settings, payload, clips)
    selected, visual_report = _select_assets(clips, candidates)
    result["clips"] = selected

    existing_keywords = [str(item) for item in result.get("subtitle_keywords") or []]
    keywords, keyword_report = _spread_keywords(
        timings, existing_keywords, float(target_duration or 0)
    )
    if keywords:
        result["subtitle_keywords"] = keywords

    duration_report = _duration_guard(selected)
    hard_failures: list[str] = []
    warnings: list[str] = list(duration_report.get("warnings") or [])
    if visual_report.get("strict_single_use_possible"):
        if visual_report.get("maximum_asset_reuse", 0) > 1:
            hard_failures.append("asset_reused_despite_sufficient_pool")
        if visual_report.get("maximum_visual_cluster_reuse", 0) > 1:
            hard_failures.append("visual_cluster_reused_despite_sufficient_pool")
        if not visual_report.get("fresh_ending_asset"):
            hard_failures.append("ending_asset_not_fresh")
    elif visual_report.get("maximum_asset_reuse", 0) > 1:
        warnings.append("single_use_relaxed_for_small_pool")
    if float(visual_report.get("aerial_city_share") or 0) > 0.35:
        hard_failures.append("landmark_share_above_35_percent")
    supported_diversity = min(
        4,
        int(visual_report.get("candidate_visual_cluster_count") or 0),
        len(selected),
    )
    if float(target_duration or 0) >= 24 and supported_diversity >= 4:
        if int(visual_report.get("scene_family_count") or 0) < 4:
            hard_failures.append("fewer_than_four_scene_families")
    if keyword_report.get("count", 0) >= 4 and keyword_report.get("timeline_coverage_ratio", 0) < 0.55:
        warnings.append("keyword_bursts_not_spread_across_timeline")

    a10_r4_report = {
        "version": VERSION,
        "passed": not hard_failures,
        "hard_failures": hard_failures,
        "warnings": sorted(set(warnings)),
        "visual": visual_report,
        "keywords": keyword_report,
        "shot_duration": duration_report,
        "timeline_shape": timeline_shape_report,
        "audio_target": {
            "integrated_lufs": -16.0,
            "lra_lu": 7.0,
            "true_peak_dbfs": -1.5,
        },
    }
    result["version"] = VERSION
    report = dict(result.get("report") or {})
    report.update(
        {
            "version": VERSION,
            "a10_r4": a10_r4_report,
            "strict_visual_single_use": bool(visual_report.get("strict_single_use_possible")),
            "semantic_scene_diversity": True,
            "fresh_ending_shot": bool(visual_report.get("fresh_ending_asset")),
            "landmark_share_cap": 0.35,
            "timeline_wide_keyword_policy": True,
            "loudness_normalization": True,
        }
    )
    result["report"] = report
    quality = dict(result.get("edit_quality_gate") or {})
    previous_failures = [
        item for item in quality.get("hard_failures") or []
        if item not in {
            "asset_reused_despite_sufficient_pool",
            "visual_cluster_reused_despite_sufficient_pool",
            "ending_asset_not_fresh",
            "landmark_share_above_35_percent",
            "fewer_than_four_scene_families",
        }
    ]
    quality.update(
        {
            "version": VERSION,
            "passed": not (previous_failures + hard_failures),
            "hard_failures": previous_failures + hard_failures,
            "warnings": sorted(set((quality.get("warnings") or []) + warnings)),
            "a10_r4": a10_r4_report,
        }
    )
    result["edit_quality_gate"] = quality
    repeat = dict(result.get("global_repeat_report") or {})
    repeat.update(
        {
            "version": VERSION,
            "asset_use_counts": visual_report.get("asset_use_counts"),
            "visual_cluster_use_counts": visual_report.get("visual_cluster_use_counts"),
            "max_asset_reuse_count": visual_report.get("maximum_asset_reuse"),
            "max_visual_cluster_reuse_count": visual_report.get("maximum_visual_cluster_reuse"),
            "strict_single_use_possible": visual_report.get("strict_single_use_possible"),
            "strict_single_use_passed": (
                visual_report.get("maximum_asset_reuse", 0) <= 1
                and visual_report.get("maximum_visual_cluster_reuse", 0) <= 1
            ),
            "fresh_ending_asset": visual_report.get("fresh_ending_asset"),
            "aerial_city_share": visual_report.get("aerial_city_share"),
            "scene_family_counts": visual_report.get("scene_family_counts"),
            "whole_video_repeat_guard_passed": not any(
                failure in hard_failures for failure in (
                    "asset_reused_despite_sufficient_pool",
                    "visual_cluster_reused_despite_sufficient_pool",
                    "ending_asset_not_fresh",
                )
            ),
        }
    )
    result["global_repeat_report"] = repeat
    result["a10_r4_report"] = a10_r4_report
    return result


def measure_audio_loudness(path: Path | str) -> dict[str, Any]:
    source = Path(path)
    command = [
        "ffmpeg", "-hide_banner", "-nostats", "-i", str(source),
        "-filter_complex", "ebur128=framelog=verbose", "-f", "null", "-",
    ]
    process = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=600,
        check=False,
    )
    text = process.stderr or ""
    summary = text.rsplit("Summary:", 1)[-1] if "Summary:" in text else text
    patterns = {
        "integrated_lufs": r"\bI:\s*(-?\d+(?:\.\d+)?)\s*LUFS",
        "lra_lu": r"\bLRA:\s*(-?\d+(?:\.\d+)?)\s*LU",
        "true_peak_dbfs": r"\bPeak:\s*(-?\d+(?:\.\d+)?)\s*dBFS",
    }
    result: dict[str, Any] = {
        "ok": process.returncode == 0,
        "target_integrated_lufs": -16.0,
        "target_lra_lu": 7.0,
        "target_true_peak_dbfs": -1.5,
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, summary)
        result[key] = float(match.group(1)) if match else None
    result["within_short_video_target"] = bool(
        result.get("integrated_lufs") is not None
        and -18.0 <= float(result["integrated_lufs"]) <= -14.0
        and (
            result.get("true_peak_dbfs") is None
            or float(result["true_peak_dbfs"]) <= -1.0
        )
    )
    if process.returncode != 0:
        result["error"] = summary[-1500:]
    return result


def write_report(path: Path | str, report: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
