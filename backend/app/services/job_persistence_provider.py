from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional


DEFAULT_DB_PATH = "/opt/ai-video/backend/data/jobs.sqlite3"
DB_PATH = Path(os.getenv("AI_VIDEO_JOB_DB_PATH", DEFAULT_DB_PATH))


def _now() -> float:
    return time.time()


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _json_loads(value: Optional[str], fallback: Any = None) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def init_job_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS video_jobs (
                job_id TEXT PRIMARY KEY,
                job_type TEXT,
                status TEXT,
                stage TEXT,
                message TEXT,
                source_path TEXT,
                video_url TEXT,
                audio_url TEXT,
                request_json TEXT,
                response_json TEXT,
                result_json TEXT,
                error TEXT,
                created_at REAL,
                updated_at REAL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_video_jobs_type ON video_jobs(job_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_video_jobs_status ON video_jobs(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_video_jobs_updated ON video_jobs(updated_at)")
        conn.commit()


def _extract_video_url(data: dict[str, Any]) -> str:
    result = data.get("result") if isinstance(data.get("result"), dict) else {}
    return (
        data.get("video_url")
        or result.get("video_url")
        or data.get("final_video_url")
        or ""
    )


def _extract_audio_url(data: dict[str, Any]) -> str:
    result = data.get("result") if isinstance(data.get("result"), dict) else {}
    return (
        data.get("audio_url")
        or result.get("audio_url")
        or data.get("final_audio_url")
        or ""
    )


def infer_job_type(path: str, job_id: str = "") -> str:
    if "/full-ai/" in path or job_id.startswith("full_ai"):
        return "full_ai"
    if "/compose/" in path or job_id.startswith("compose"):
        return "compose"
    if "/fal/" in path or job_id.startswith("fal_"):
        return "fal"
    return "video"


def save_job_response(
    job_id: str,
    job_type: str,
    response_data: dict[str, Any],
    source_path: str = "",
    request_data: Optional[dict[str, Any]] = None,
) -> None:
    if not job_id:
        return

    init_job_db()

    now = _now()
    status = str(response_data.get("status") or response_data.get("state") or "")
    stage = str(response_data.get("stage") or "")
    message = str(response_data.get("message") or "")
    error = response_data.get("error")
    result = response_data.get("result") if isinstance(response_data.get("result"), dict) else {}
    video_url = _extract_video_url(response_data)
    audio_url = _extract_audio_url(response_data)

    with sqlite3.connect(DB_PATH) as conn:
        existing = conn.execute(
            "SELECT created_at, request_json FROM video_jobs WHERE job_id=?",
            (job_id,),
        ).fetchone()

        created_at = float(existing[0]) if existing and existing[0] else now
        old_request_json = existing[1] if existing and existing[1] else None
        request_json = _json_dumps(request_data) if request_data is not None else old_request_json

        conn.execute(
            """
            INSERT INTO video_jobs (
                job_id, job_type, status, stage, message, source_path,
                video_url, audio_url, request_json, response_json, result_json,
                error, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                job_type=excluded.job_type,
                status=excluded.status,
                stage=excluded.stage,
                message=excluded.message,
                source_path=excluded.source_path,
                video_url=excluded.video_url,
                audio_url=excluded.audio_url,
                request_json=COALESCE(excluded.request_json, video_jobs.request_json),
                response_json=excluded.response_json,
                result_json=excluded.result_json,
                error=excluded.error,
                updated_at=excluded.updated_at
            """,
            (
                job_id,
                job_type,
                status,
                stage,
                message,
                source_path,
                video_url,
                audio_url,
                request_json,
                _json_dumps(response_data),
                _json_dumps(result),
                str(error) if error else "",
                created_at,
                now,
            ),
        )
        conn.commit()


def get_job(job_id: str) -> Optional[dict[str, Any]]:
    if not job_id or not DB_PATH.exists():
        return None

    init_job_db()

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM video_jobs WHERE job_id=?",
            (job_id,),
        ).fetchone()

    if not row:
        return None

    response_data = _json_loads(row["response_json"], {}) or {}

    if not isinstance(response_data, dict):
        response_data = {}

    response_data.setdefault("ok", True)
    response_data.setdefault("job_id", row["job_id"])
    response_data.setdefault("type", row["job_type"])
    response_data.setdefault("status", row["status"] or "restored")
    response_data.setdefault("stage", row["stage"] or "restored_from_sqlite")
    response_data.setdefault("message", row["message"] or "任务状态已从 SQLite 持久化记录恢复")

    if row["video_url"]:
        response_data.setdefault("video_url", row["video_url"])
    if row["audio_url"]:
        response_data.setdefault("audio_url", row["audio_url"])

    response_data["_restored_from_sqlite"] = True
    response_data["_persisted_at"] = row["updated_at"]

    return response_data


def list_recent_jobs(limit: int = 20) -> list[dict[str, Any]]:
    init_job_db()

    limit = max(1, min(int(limit or 20), 100))

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT job_id, job_type, status, stage, message, video_url, audio_url, created_at, updated_at
            FROM video_jobs
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return [dict(row) for row in rows]


def health() -> dict[str, Any]:
    init_job_db()

    with sqlite3.connect(DB_PATH) as conn:
        count = conn.execute("SELECT COUNT(*) FROM video_jobs").fetchone()[0]

    return {
        "ok": True,
        "provider": "sqlite",
        "db_path": str(DB_PATH),
        "job_count": count,
    }
