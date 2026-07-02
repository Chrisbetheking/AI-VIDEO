from __future__ import annotations

from typing import Any
from fastapi import APIRouter, FastAPI

from app.services.job_persistence_provider import list_recent_jobs

router = APIRouter(prefix="/api/video/wizard-video", tags=["wizard-video-recovery"])


def _status_done(job: dict[str, Any]) -> bool:
    return str(job.get("status") or "").lower() in {"done", "completed", "success", "succeeded", "finished"}


def _done_video(job: dict[str, Any]) -> bool:
    return _status_done(job) and bool(job.get("video_url"))


def _rank(job: dict[str, Any]) -> int:
    """Prefer v2/subtitled results over raw compose/full_ai outputs."""
    jt = str(job.get("job_type") or "").lower()
    stage = str(job.get("stage") or "").lower()
    url = str(job.get("video_url") or "").lower()
    if jt == "tts_first_v2":
        if "subtitle" in stage or "subtitle" in url or "tts_first_v2" in url:
            return 0
        return 1
    if jt == "full_ai" and "subtitle" in url:
        return 2
    if jt == "full_ai":
        return 3
    if jt == "compose":
        return 4
    return 9


@router.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "provider": "wizard_video_recovery_v2", "prefer_tts_first_v2": True, "prefer_subtitled": True}


@router.get("/latest-done")
def latest_done(limit: int = 30) -> dict[str, Any]:
    jobs = list_recent_jobs(limit=max(1, min(int(limit or 30), 100)))
    done = [j for j in jobs if _done_video(j)]
    # Keep recency, but prefer proper v2/subtitled result when timestamps are close.
    done_sorted = sorted(done, key=lambda j: (_rank(j), -float(j.get("updated_at") or 0)))
    latest = done_sorted[0] if done_sorted else None
    return {"ok": True, "job": latest, "count": len(done), "jobs": done_sorted[:10], "raw_done_jobs": done[:10]}


def install_wizard_video_recovery(app: FastAPI) -> None:
    app.include_router(router)
