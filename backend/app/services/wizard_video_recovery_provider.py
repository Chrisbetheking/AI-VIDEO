from __future__ import annotations

from typing import Any
from fastapi import APIRouter, FastAPI

from app.services.job_persistence_provider import list_recent_jobs

router = APIRouter(prefix="/api/video/wizard-video", tags=["wizard-video-recovery"])


def _status_done(job: dict[str, Any]) -> bool:
    return str(job.get("status") or "").lower() in {"done", "completed", "success", "succeeded", "finished"}


def _done_video(job: dict[str, Any]) -> bool:
    return _status_done(job) and bool(job.get("video_url"))


def _is_one_scene(job: dict[str, Any]) -> bool:
    jid = str(job.get("job_id") or "").lower()
    jt = str(job.get("job_type") or "").lower()
    return jt == "one_scene" or jid.startswith("one_scene_") or bool(job.get("single_scene"))


def _rank(job: dict[str, Any]) -> int:
    # V10.13: never auto-recover old tts_first_v2/v3 montage videos into the one-scene wizard.
    if not _is_one_scene(job):
        return 999
    url = str(job.get("video_url") or "").lower()
    stage = str(job.get("stage") or "").lower()
    if job.get("subtitled_video_url") or "subtitled" in url or "subtitle" in stage:
        return 0
    return 1


@router.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "provider": "wizard_video_recovery_v10_13",
        "strict_one_scene_only": True,
        "prefer_subtitled": True,
        "reject_tts_first_v2": True,
        "avoid_raw_compose": True,
    }


@router.get("/latest-done")
def latest_done(limit: int = 30) -> dict[str, Any]:
    jobs = list_recent_jobs(limit=max(1, min(int(limit or 30), 100)))
    done = [j for j in jobs if _done_video(j) and _is_one_scene(j)]
    done_sorted = sorted(done, key=lambda j: (_rank(j), -float(j.get("updated_at") or 0)))
    latest = done_sorted[0] if done_sorted else None
    return {"ok": True, "job": latest, "count": len(done), "jobs": done_sorted[:10], "strict_one_scene_only": True}


def install_wizard_video_recovery(app: FastAPI) -> None:
    app.include_router(router)
