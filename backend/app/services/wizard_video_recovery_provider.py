from __future__ import annotations

from typing import Any
from fastapi import APIRouter, FastAPI

from app.services.job_persistence_provider import list_recent_jobs

router = APIRouter(prefix="/api/video/wizard-video", tags=["wizard-video-recovery"])


def _done_video(job: dict[str, Any]) -> bool:
    return str(job.get("status") or "").lower() in {"done", "completed", "success", "succeeded", "finished"} and bool(job.get("video_url"))


@router.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "provider": "wizard_video_recovery_v1"}


@router.get("/latest-done")
def latest_done(limit: int = 30) -> dict[str, Any]:
    jobs = list_recent_jobs(limit=max(1, min(int(limit or 30), 100)))
    done = [j for j in jobs if _done_video(j)]
    latest = done[0] if done else None
    return {"ok": True, "job": latest, "count": len(done), "jobs": done[:10]}


def install_wizard_video_recovery(app: FastAPI) -> None:
    app.include_router(router)
