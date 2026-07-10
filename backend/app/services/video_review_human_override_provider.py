from __future__ import annotations

from typing import Any

from fastapi import Body, FastAPI, HTTPException

from app.services import video_review_gate_provider as gate


def _ai_issues(report: dict[str, Any]) -> list[dict[str, Any]]:
    ai = report.get("ai_review") or {}
    raw = ai.get("issues") if isinstance(ai, dict) else []
    return [item for item in (raw or []) if isinstance(item, dict)]


def install_video_review_human_override_provider(app: FastAPI) -> None:
    if getattr(app.state, "video_review_human_override_installed", False):
        return
    app.state.video_review_human_override_installed = True

    @app.get("/api/video/review-override/health")
    def review_override_health() -> dict[str, Any]:
        return {
            "ok": True,
            "provider": "video_review_human_override_provider",
            "version": "v10.35",
            "rule": (
                "mechanical review must pass; a human may override AI findings "
                "only with a written reason"
            ),
        }

    @app.post("/api/video/review/{job_id}/human-override")
    async def human_override_review(
        job_id: str,
        payload: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any]:
        report = gate._load_review(job_id)
        status_before = str(report.get("status") or "not_reviewed")

        if status_before in {"not_reviewed", "reviewing", "review_error"}:
            raise HTTPException(status_code=409, detail="请先完成自动审查")

        if status_before == "approved" and bool(report.get("packaging_unlocked")):
            return {
                "ok": True,
                "job_id": job_id,
                "message": "该视频已经通过审查",
                "review": report,
                "cover_result": report.get("cover_result"),
                "cover_error": report.get("cover_error") or "",
            }

        mechanical = report.get("mechanical") or {}
        if not bool(mechanical.get("passed")):
            raise HTTPException(
                status_code=409,
                detail="机械检查未通过，不能按误报覆盖。请先修复音视频、分辨率、黑帧或文件问题。",
            )

        ai_review = report.get("ai_review") or {}
        issues = _ai_issues(report)
        ai_failed = bool(ai_review.get("available")) and ai_review.get("passed") is False

        if not issues and not ai_failed:
            raise HTTPException(
                status_code=409,
                detail="当前没有需要覆盖的豆包审查问题，请使用普通‘通过并生成封面’。",
            )

        reviewer = str(payload.get("reviewer") or "human").strip() or "human"
        note = str(payload.get("note") or "").strip()
        if len(note) < 4:
            raise HTTPException(
                status_code=422,
                detail="请填写人工确认原因，至少4个字，便于后续审计。",
            )

        now = gate._now()
        override_record = {
            "confirmed": True,
            "reviewer": reviewer,
            "reason": note,
            "confirmed_at": now,
            "status_before": status_before,
            "ai_passed_before": ai_review.get("passed"),
            "ai_score": ai_review.get("score"),
            "overridden_issues": issues,
        }

        report.update(
            {
                "ok": True,
                "status": "approved",
                "approved": True,
                "packaging_unlocked": True,
                "reviewer": reviewer,
                "approval_mode": "human_false_positive_override",
                "approval_note": note,
                "human_override": override_record,
                "approved_at": now,
                "summary": "人工完整观看后确认豆包提示为误报，已通过并解锁封面及图文包装",
            }
        )
        gate._save_review(job_id, report)

        job = gate._load_job(job_id)
        if job:
            job["review_status"] = "approved"
            job["review_approved_at"] = now
            job["reviewer"] = reviewer
            job["review_approval_mode"] = "human_false_positive_override"
            job["review_approval_note"] = note
            job["packaging_unlocked"] = True
            gate._save_job(job_id, job)

        cover_result = None
        cover_error = ""

        if bool(payload.get("generate_cover", True)):
            cover_payload = {
                "job_id": job_id,
                "title": str(payload.get("title") or gate._job_title(job)),
                "script_text": gate._job_script(job),
                "keywords": payload.get("keywords") or [],
                "platform": str(payload.get("platform") or "douyin"),
                "style": str(payload.get("style") or "专业顾问"),
                "slide_count": 7,
                "cta": str(payload.get("cta") or ""),
                "use_video_frame": True,
            }
            try:
                cover_result = await gate._post_local_json(
                    "/api/graphic-window/video-cover/generate",
                    cover_payload,
                )
                report["cover_result"] = cover_result
                report["cover_generated_at"] = gate._now()
                report.pop("cover_error", None)
                gate._save_review(job_id, report)
            except Exception as exc:
                cover_error = str(exc)
                report["cover_error"] = cover_error
                gate._save_review(job_id, report)

        return {
            "ok": True,
            "job_id": job_id,
            "status": "approved",
            "approved": True,
            "packaging_unlocked": True,
            "approval_mode": "human_false_positive_override",
            "message": (
                "已记录人工误报确认，并生成9:16封面"
                if cover_result
                else "已记录人工误报确认并解锁包装；封面未生成或生成失败"
            ),
            "cover_result": cover_result,
            "cover_error": cover_error,
            "review": report,
        }
