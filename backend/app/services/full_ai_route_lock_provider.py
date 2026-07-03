"""
AI VIDEO V10.19 Route Lock Provider

Purpose:
- The frontend may still call the legacy one-scene API:
    POST /api/video/full-ai/one-scene/start
    GET  /api/video/full-ai/one-scene/job/{job_id}
- That old route creates indoor-only one_scene jobs and bypasses the semantic storyboard planner.
- This provider removes the legacy one-scene start/job routes at runtime and replaces them with wrappers
  that proxy to the TTS-first semantic storyboard route.

Install this provider AFTER full_ai_one_scene_provider in app.main.
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Tuple

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/video/full-ai/one-scene", tags=["full-ai-route-lock-v10-19"])


def _internal_base_url() -> str:
    """Internal loopback URL for calling the already-mounted tts-first endpoints."""
    explicit = (os.getenv("AI_VIDEO_INTERNAL_API_BASE") or "").strip().rstrip("/")
    if explicit:
        return explicit
    port = (os.getenv("PORT") or os.getenv("BACKEND_PORT") or "8000").strip()
    return f"http://127.0.0.1:{port}"


async def _proxy_json(method: str, path: str, payload: Dict[str, Any] | None = None) -> JSONResponse:
    """Proxy request to the internal FastAPI service. Uses httpx if available."""
    url = _internal_base_url() + path
    try:
        import httpx  # type: ignore

        timeout = httpx.Timeout(1800.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            if method.upper() == "POST":
                resp = await client.post(url, json=payload or {}, headers={"X-AI-VIDEO-ROUTE-LOCK": "one-scene-to-tts-first"})
            else:
                resp = await client.get(url, headers={"X-AI-VIDEO-ROUTE-LOCK": "one-scene-to-tts-first"})
        try:
            data = resp.json()
        except Exception:
            data = {"ok": False, "error": resp.text[:2000]}
        if isinstance(data, dict):
            data.setdefault("route_lock", "one_scene_to_tts_first")
            data.setdefault("legacy_route_blocked", True)
            data.setdefault("target_route", path)
        return JSONResponse(status_code=resp.status_code, content=data)
    except Exception as exc:
        return JSONResponse(
            status_code=502,
            content={
                "ok": False,
                "error": "route_lock_proxy_failed",
                "detail": str(exc),
                "route_lock": "one_scene_to_tts_first",
                "target_route": path,
            },
        )


@router.get("/route-lock-health")
async def route_lock_health() -> Dict[str, Any]:
    return {
        "ok": True,
        "provider": "full_ai_route_lock_v10_19",
        "one_scene_start_locked": True,
        "one_scene_job_locked": True,
        "target": "/api/video/full-ai/tts-first",
        "semantic_storyboard_required": True,
        "timestamp": time.time(),
    }


@router.post("/start")
async def locked_one_scene_start(request: Request) -> JSONResponse:
    """Legacy one-scene start route is now locked to TTS-first semantic storyboard."""
    try:
        raw = await request.json()
        if not isinstance(raw, dict):
            raw = {"raw_request": raw}
    except Exception:
        raw = {}

    raw.update(
        {
            "route_lock": "one_scene_to_tts_first",
            "force_tts_first_semantic_storyboard": True,
            "disable_one_scene_fallback": True,
            "requested_from_legacy_endpoint": "/api/video/full-ai/one-scene/start",
        }
    )
    return await _proxy_json("POST", "/api/video/full-ai/tts-first/start", raw)


@router.get("/job/{job_id}")
async def locked_one_scene_job(job_id: str) -> JSONResponse:
    """Legacy one-scene job route now proxies to TTS-first job status."""
    return await _proxy_json("GET", f"/api/video/full-ai/tts-first/job/{job_id}")


def _remove_legacy_one_scene_routes(app: FastAPI) -> List[Tuple[str, str]]:
    """Remove old one-scene start/job routes so the route-lock wrappers win route matching."""
    removed: List[Tuple[str, str]] = []
    keep = []
    for r in list(app.router.routes):
        path = getattr(r, "path", "") or ""
        methods = sorted(list(getattr(r, "methods", []) or []))
        method_text = ",".join(methods)
        is_legacy_start = path == "/api/video/full-ai/one-scene/start"
        is_legacy_job = path == "/api/video/full-ai/one-scene/job/{job_id}"
        if is_legacy_start or is_legacy_job:
            removed.append((method_text, path))
            continue
        keep.append(r)
    app.router.routes[:] = keep
    return removed


def _patch_wizard_recovery_provider() -> None:
    """Best-effort runtime patch: allow latest-done strict recovery to see tts_first semantic jobs too."""
    try:
        from app.services import wizard_video_recovery_provider as recovery  # type: ignore

        def _is_semantic_or_one_scene(job: Dict[str, Any]) -> bool:
            jt = str(job.get("job_type") or job.get("type") or "")
            jid = str(job.get("job_id") or job.get("id") or "")
            provider = str(job.get("provider") or "")
            visual_version = str(job.get("visual_prompt_version") or "")
            return (
                jt in {"one_scene", "tts_first", "tts_first_semantic", "full_ai_tts_first"}
                or jid.startswith("one_scene_")
                or jid.startswith("tts_first_")
                or bool(job.get("single_scene"))
                or provider.startswith("full_ai_tts_first_semantic")
                or visual_version.startswith("tts_first_semantic")
            )

        recovery._is_one_scene = _is_semantic_or_one_scene  # type: ignore[attr-defined]
        recovery.AI_VIDEO_ROUTE_LOCK_PATCHED = True  # type: ignore[attr-defined]
    except Exception as exc:
        print("V10_19_ROUTE_LOCK_RECOVERY_PATCH_FAILED", exc)


def install_full_ai_route_lock(app: FastAPI) -> None:
    removed = _remove_legacy_one_scene_routes(app)
    _patch_wizard_recovery_provider()
    app.include_router(router)
    print(
        "V10_19_ROUTE_LOCK_INSTALLED",
        {
            "provider": "full_ai_route_lock_v10_19",
            "removed_legacy_routes": removed,
            "one_scene_start_locked_to": "/api/video/full-ai/tts-first/start",
            "one_scene_job_locked_to": "/api/video/full-ai/tts-first/job/{job_id}",
            "semantic_storyboard_required": True,
        },
    )
