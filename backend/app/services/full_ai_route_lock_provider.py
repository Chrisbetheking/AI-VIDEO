"""
AI VIDEO V10.21 Route Lock Provider - block stale one-scene recovery

Purpose:
- V10.20 locked legacy one-scene start/job routes and sanitized old request bodies.
- The UI can still display old cached/latest-done one_scene_* jobs through the recovery endpoint
  or browser state. That makes the user think semantic storyboard failed even when the new route
  lock is installed.
- V10.21 keeps the legacy start route locked to TTS-first semantic storyboard, but strictly blocks
  old one_scene_* job recovery and teaches wizard recovery to return only tts_first semantic jobs.

Install this provider AFTER full_ai_one_scene_provider and wizard_video_recovery_provider in app.main.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Tuple

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/video/full-ai/one-scene", tags=["full-ai-route-lock-v10-21"])

LIST_FIELDS = {"script_segments", "segment_voice_settings", "manual_shot_plan", "transition_plan"}
DICT_FIELDS = {"shot_overrides", "asset_context", "avatar_config", "keyword_insights", "extra"}


def _internal_base_url() -> str:
    explicit = (os.getenv("AI_VIDEO_INTERNAL_API_BASE") or "").strip().rstrip("/")
    if explicit:
        return explicit
    port = (os.getenv("PORT") or os.getenv("BACKEND_PORT") or "8000").strip()
    return f"http://127.0.0.1:{port}"


def _try_json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return None
    if text.lower() in {"null", "undefined", "none"}:
        return None
    if text[0:1] in {"[", "{"}:
        try:
            return json.loads(text)
        except Exception:
            return value
    return value


def _as_list(value: Any) -> List[Dict[str, Any]]:
    value = _try_json(value)
    if value is None or value == "":
        return []
    if isinstance(value, list):
        out: List[Dict[str, Any]] = []
        for i, item in enumerate(value, start=1):
            item = _try_json(item)
            if isinstance(item, dict):
                out.append(item)
            elif item is not None and item != "":
                out.append({"index": i, "value": item})
        return out
    if isinstance(value, dict):
        out = []
        for k, v in value.items():
            v = _try_json(v)
            if isinstance(v, dict):
                item = dict(v)
                item.setdefault("key", str(k))
                out.append(item)
            elif v is not None and v != "":
                out.append({"key": str(k), "value": v})
        return out
    return []


def _as_dict(value: Any) -> Dict[str, Any]:
    value = _try_json(value)
    if value is None or value == "":
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return {str(i + 1): item for i, item in enumerate(value)}
    return {"value": value}


def _normalize_duration(raw: Dict[str, Any]) -> None:
    if raw.get("target_duration_seconds") not in (None, ""):
        return
    for key in ("duration_seconds", "targetDurationSeconds", "target_duration", "duration", "video_duration", "target_seconds"):
        val = raw.get(key)
        if val in (None, ""):
            continue
        try:
            raw["target_duration_seconds"] = float(val)
            return
        except Exception:
            continue


def _normalize_script(raw: Dict[str, Any]) -> None:
    if raw.get("script_text"):
        return
    for key in ("script", "scriptText", "voiceover_text", "voiceText", "copy", "content"):
        val = raw.get(key)
        if isinstance(val, str) and val.strip():
            raw["script_text"] = val.strip()
            return
    segs = _as_list(raw.get("script_segments"))
    if segs:
        texts = []
        for seg in segs:
            for k in ("text", "content", "line", "sentence", "narration"):
                v = seg.get(k)
                if isinstance(v, str) and v.strip():
                    texts.append(v.strip())
                    break
        if texts:
            raw["script_text"] = "。".join(texts)


def _normalize_legacy_payload(raw: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(raw or {})

    if not data.get("title") and data.get("topic"):
        data["title"] = data.get("topic")
    if not data.get("topic") and data.get("title"):
        data["topic"] = data.get("title")
    if data.get("city") in (None, "") and data.get("location"):
        data["city"] = data.get("location")

    if "segments" in data and "script_segments" not in data:
        data["script_segments"] = data.get("segments")
    if "voice_settings" in data and "segment_voice_settings" not in data:
        data["segment_voice_settings"] = data.get("voice_settings")
    if "assets" in data and "asset_context" not in data:
        data["asset_context"] = data.get("assets")
    if "avatar" in data and "avatar_config" not in data:
        data["avatar_config"] = data.get("avatar")
    if "keywords" in data and "keyword_insights" not in data:
        data["keyword_insights"] = data.get("keywords")

    for field in LIST_FIELDS:
        data[field] = _as_list(data.get(field))
    for field in DICT_FIELDS:
        data[field] = _as_dict(data.get(field))

    _normalize_duration(data)
    _normalize_script(data)

    data.setdefault("target_duration_seconds", 20)
    data.setdefault("city", "kuala_lumpur")
    data.setdefault("content_type", "real_estate")
    data.setdefault("voice", "default")
    data.setdefault("width", 1080)
    data.setdefault("height", 1920)

    data["route_lock"] = "one_scene_to_tts_first_v10_21"
    data["force_tts_first_semantic_storyboard"] = True
    data["disable_one_scene_fallback"] = True
    data["disable_legacy_one_scene_recovery"] = True
    data["requested_from_legacy_endpoint"] = "/api/video/full-ai/one-scene/start"
    data["route_lock_body_sanitized"] = True
    data.setdefault("extra", {})
    if isinstance(data["extra"], dict):
        data["extra"].update({
            "route_lock_body_sanitized": True,
            "route_lock_version": "v10.21",
            "disable_legacy_one_scene_recovery": True,
        })
    return data


async def _proxy_json(method: str, path: str, payload: Dict[str, Any] | None = None) -> JSONResponse:
    url = _internal_base_url() + path
    try:
        import httpx  # type: ignore
        timeout = httpx.Timeout(1800.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            if method.upper() == "POST":
                resp = await client.post(
                    url,
                    json=payload or {},
                    headers={"X-AI-VIDEO-ROUTE-LOCK": "one-scene-to-tts-first-v10-21"},
                )
            else:
                resp = await client.get(url, headers={"X-AI-VIDEO-ROUTE-LOCK": "one-scene-to-tts-first-v10-21"})
        try:
            data = resp.json()
        except Exception:
            data = {"ok": False, "error": resp.text[:2000]}
        if isinstance(data, dict):
            data.setdefault("route_lock", "one_scene_to_tts_first_v10_21")
            data.setdefault("legacy_route_blocked", True)
            data.setdefault("target_route", path)
            data.setdefault("route_lock_body_sanitized", bool(payload and payload.get("route_lock_body_sanitized")))
            # Make it obvious in the UI/debug payload that this is not the old one-scene pipeline.
            if isinstance(data.get("job_id"), str) and data["job_id"].startswith("tts_first_"):
                data.setdefault("job_type", "tts_first")
                data.setdefault("semantic_storyboard_required", True)
        return JSONResponse(status_code=resp.status_code, content=data)
    except Exception as exc:
        return JSONResponse(
            status_code=502,
            content={
                "ok": False,
                "error": "route_lock_proxy_failed",
                "detail": str(exc),
                "route_lock": "one_scene_to_tts_first_v10_21",
                "target_route": path,
            },
        )


@router.get("/route-lock-health")
async def route_lock_health() -> Dict[str, Any]:
    return {
        "ok": True,
        "provider": "full_ai_route_lock_v10_21",
        "one_scene_start_locked": True,
        "one_scene_job_locked": True,
        "target": "/api/video/full-ai/tts-first",
        "semantic_storyboard_required": True,
        "legacy_body_sanitizer": True,
        "legacy_one_scene_recovery_blocked": True,
        "latest_done_should_return": "tts_first_semantic_only",
        "normalizes_fields": sorted(list(LIST_FIELDS | DICT_FIELDS)),
        "timestamp": time.time(),
    }


@router.post("/start")
async def locked_one_scene_start(request: Request) -> JSONResponse:
    try:
        raw = await request.json()
        if not isinstance(raw, dict):
            raw = {"raw_request": raw}
    except Exception:
        raw = {}
    normalized = _normalize_legacy_payload(raw)
    print("V10_21_ROUTE_LOCK_START_TO_TTS_FIRST", {
        "script_len": len(str(normalized.get("script_text") or "")),
        "duration": normalized.get("target_duration_seconds"),
        "city": normalized.get("city"),
        "body_sanitized": True,
    })
    return await _proxy_json("POST", "/api/video/full-ai/tts-first/start", normalized)


@router.get("/job/{job_id}")
async def locked_one_scene_job(job_id: str) -> JSONResponse:
    if str(job_id).startswith("one_scene_"):
        # Do not allow the UI to keep showing old cached/recovered one-scene MP4s as if they were
        # generated by the semantic storyboard pipeline.
        return JSONResponse(
            status_code=410,
            content={
                "ok": False,
                "status": "legacy_one_scene_blocked",
                "job_id": job_id,
                "error": "legacy_one_scene_job_blocked_by_v10_21",
                "message": "旧 one_scene 成片已被禁用，请重新生成 tts_first 语义分镜成片。",
                "route_lock": "one_scene_to_tts_first_v10_21",
                "legacy_one_scene_recovery_blocked": True,
                "target": "/api/video/full-ai/tts-first/start",
            },
        )
    return await _proxy_json("GET", f"/api/video/full-ai/tts-first/job/{job_id}")


def _remove_legacy_one_scene_routes(app: FastAPI) -> List[Tuple[str, str]]:
    removed: List[Tuple[str, str]] = []
    keep = []
    for r in list(app.router.routes):
        path = getattr(r, "path", "") or ""
        methods = sorted(list(getattr(r, "methods", []) or []))
        method_text = ",".join(methods)
        is_legacy_start = path == "/api/video/full-ai/one-scene/start"
        is_legacy_job = path == "/api/video/full-ai/one-scene/job/{job_id}"
        is_route_lock_health = path == "/api/video/full-ai/one-scene/route-lock-health"
        if is_legacy_start or is_legacy_job or is_route_lock_health:
            removed.append((method_text, path))
            continue
        keep.append(r)
    app.router.routes[:] = keep
    return removed


def _is_tts_first_semantic_job(job: Dict[str, Any]) -> bool:
    jt = str(job.get("job_type") or job.get("type") or "")
    jid = str(job.get("job_id") or job.get("id") or "")
    provider = str(job.get("provider") or "")
    visual_version = str(job.get("visual_prompt_version") or "")
    route_lock = str(job.get("route_lock") or "")
    request = job.get("request") if isinstance(job.get("request"), dict) else {}
    req_visual_version = str(request.get("visual_prompt_version") or "") if isinstance(request, dict) else ""
    force_semantic = bool(request.get("force_tts_first_semantic_storyboard")) if isinstance(request, dict) else False
    return (
        jt in {"tts_first", "tts_first_semantic", "full_ai_tts_first"}
        or jid.startswith("tts_first_")
        or provider.startswith("full_ai_tts_first_semantic")
        or visual_version.startswith("tts_first_semantic")
        or req_visual_version.startswith("tts_first_semantic")
        or route_lock.startswith("one_scene_to_tts_first")
        or force_semantic
    )


def _patch_wizard_recovery_provider() -> None:
    try:
        from app.services import wizard_video_recovery_provider as recovery  # type: ignore

        def _semantic_only(job: Dict[str, Any]) -> bool:
            return _is_tts_first_semantic_job(job)

        recovery._is_one_scene = _semantic_only  # type: ignore[attr-defined]
        recovery.AI_VIDEO_ROUTE_LOCK_PATCHED = True  # type: ignore[attr-defined]
        recovery.AI_VIDEO_LEGACY_ONE_SCENE_RECOVERY_BLOCKED = True  # type: ignore[attr-defined]
        print("V10_21_RECOVERY_PATCHED_SEMANTIC_ONLY")
    except Exception as exc:
        print("V10_21_ROUTE_LOCK_RECOVERY_PATCH_FAILED", exc)


def install_full_ai_route_lock(app: FastAPI) -> None:
    removed = _remove_legacy_one_scene_routes(app)
    _patch_wizard_recovery_provider()
    app.include_router(router)
    print(
        "V10_21_ROUTE_LOCK_INSTALLED",
        {
            "provider": "full_ai_route_lock_v10_21",
            "removed_legacy_routes": removed,
            "one_scene_start_locked_to": "/api/video/full-ai/tts-first/start",
            "one_scene_job_locked_to": "/api/video/full-ai/tts-first/job/{job_id}",
            "semantic_storyboard_required": True,
            "legacy_body_sanitizer": True,
            "legacy_one_scene_recovery_blocked": True,
        },
    )
