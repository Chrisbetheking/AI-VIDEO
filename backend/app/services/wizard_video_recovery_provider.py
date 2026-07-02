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
    # V10.12: one_scene is the intended final pipeline: one visual + exact-script subtitles.
    if jt == "one_scene":
        return 0 if (job.get("subtitled_video_url") or "subtitled" in url or "subtitle" in stage) else 1
    if jt == "tts_first_v3":
        if "tts_first_v3" in url or job.get("subtitled_video_url") or "subtitle" in stage:
            return 3
        return 4
    if jt == "tts_first_v2":
        if "tts_first_v2" in url or job.get("subtitled_video_url") or "subtitle" in stage:
            return 5
        return 6
    if jt == "full_ai" and "subtitle" in url:
        return 7
    if jt == "full_ai": return 10
    if jt == "compose": return 11
    return 12


@router.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "provider": "wizard_video_recovery_v10_12", "prefer_one_scene": True, "prefer_subtitled": True, "avoid_raw_compose": True}


@router.get("/latest-done")
def latest_done(limit: int = 30) -> dict[str, Any]:
    jobs = list_recent_jobs(limit=max(1, min(int(limit or 30), 100)))
    done = [j for j in jobs if _done_video(j)]
    done_sorted = sorted(done, key=lambda j: (_rank(j), -float(j.get("updated_at") or 0)))
    latest = done_sorted[0] if done_sorted else None
    return {"ok": True, "job": latest, "count": len(done), "jobs": done_sorted[:10], "raw_done_jobs": done[:10]}


def install_wizard_video_recovery(app: FastAPI) -> None:
    app.include_router(router)
