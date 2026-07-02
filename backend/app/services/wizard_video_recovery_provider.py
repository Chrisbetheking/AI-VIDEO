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
    jt = str(job.get("job_type") or "").lower()
    url = str(job.get("video_url") or "").lower()
    stage = str(job.get("stage") or "").lower()
    if jt == "tts_first_v3":
        if "tts_first_v3" in url or job.get("subtitled_video_url") or "subtitle" in stage:
            return 0
        return 1
    if jt == "tts_first_v2":
        if "tts_first_v2" in url or job.get("subtitled_video_url") or "subtitle" in stage:
            return 2
        return 3
    if jt == "full_ai" and "subtitle" in url:
        return 4
    # Raw full_ai/compose is intentionally lower priority because it may be the non-subtitled collage output.
    if jt == "full_ai": return 7
    if jt == "compose": return 8
    return 9


@router.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "provider": "wizard_video_recovery_v3", "prefer_tts_first_v3": True, "prefer_subtitled": True, "avoid_raw_compose": True}


@router.get("/latest-done")
def latest_done(limit: int = 30) -> dict[str, Any]:
    jobs = list_recent_jobs(limit=max(1, min(int(limit or 30), 100)))
    done = [j for j in jobs if _done_video(j)]
    done_sorted = sorted(done, key=lambda j: (_rank(j), -float(j.get("updated_at") or 0)))
    latest = done_sorted[0] if done_sorted else None
    return {"ok": True, "job": latest, "count": len(done), "jobs": done_sorted[:10], "raw_done_jobs": done[:10]}


def install_wizard_video_recovery(app: FastAPI) -> None:
    app.include_router(router)
