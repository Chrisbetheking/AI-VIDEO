from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, Query

VERSION = "10.40.8.6-a1"
DATA_ROOT = Path(os.getenv("AI_VIDEO_DATA_DIR", "/opt/ai-video/backend/data"))
DB_PATH = Path(
    os.getenv(
        "AI_VIDEO_PRODUCTION_MEMORY_DB",
        str(DATA_ROOT / "production_memory_v10_40_8_6.sqlite3"),
    )
)
EXISTING_JOBS = DATA_ROOT / "existing_video_edit_jobs.json"
_LOCK = threading.RLock()
_WATCHER_STARTED = False


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _init_db() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS content_runs (
              content_id TEXT PRIMARY KEY,
              topic TEXT NOT NULL DEFAULT '',
              direction TEXT NOT NULL DEFAULT '',
              audience TEXT NOT NULL DEFAULT '',
              market TEXT NOT NULL DEFAULT '',
              city TEXT NOT NULL DEFAULT '',
              source TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL DEFAULT 'draft',
              latest_script TEXT NOT NULL DEFAULT '',
              created_at REAL NOT NULL,
              updated_at REAL NOT NULL,
              metadata_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS script_versions (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              content_id TEXT NOT NULL,
              job_id TEXT NOT NULL DEFAULT '',
              version_no INTEGER NOT NULL,
              script_text TEXT NOT NULL,
              script_hash TEXT NOT NULL,
              source TEXT NOT NULL DEFAULT '',
              created_at REAL NOT NULL,
              UNIQUE(content_id, script_hash)
            );

            CREATE TABLE IF NOT EXISTS production_jobs (
              job_id TEXT PRIMARY KEY,
              content_id TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT '',
              material_mode TEXT NOT NULL DEFAULT 'auto',
              voice_json TEXT NOT NULL DEFAULT '{}',
              result_url TEXT NOT NULL DEFAULT '',
              payload_json TEXT NOT NULL DEFAULT '{}',
              updated_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS asset_usage (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              content_id TEXT NOT NULL,
              job_id TEXT NOT NULL,
              segment_index INTEGER NOT NULL DEFAULT 0,
              segment_text TEXT NOT NULL DEFAULT '',
              asset_id TEXT NOT NULL DEFAULT '',
              asset_name TEXT NOT NULL DEFAULT '',
              asset_url TEXT NOT NULL DEFAULT '',
              selected_by TEXT NOT NULL DEFAULT 'auto',
              match_score REAL NOT NULL DEFAULT 0,
              match_reason TEXT NOT NULL DEFAULT '',
              clip_start REAL NOT NULL DEFAULT 0,
              clip_end REAL NOT NULL DEFAULT 0,
              created_at REAL NOT NULL,
              UNIQUE(job_id, segment_index, asset_id, clip_start, clip_end)
            );

            CREATE INDEX IF NOT EXISTS idx_asset_usage_asset
              ON asset_usage(asset_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_script_hash
              ON script_versions(script_hash);
            CREATE INDEX IF NOT EXISTS idx_content_updated
              ON content_runs(updated_at DESC);
            """
        )


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _first(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = data.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _script_from_job(job: dict[str, Any]) -> str:
    payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
    segments = (
        job.get("timings")
        or job.get("segments")
        or payload.get("segments")
        or payload.get("script_segments")
        or []
    )
    if isinstance(segments, list):
        parts = [
            _clean_text(item.get("text") or item.get("narration"))
            for item in segments
            if isinstance(item, dict)
            and _clean_text(item.get("text") or item.get("narration"))
        ]
        if parts:
            return "。".join(parts)

    return _clean_text(
        _first(job, "script_text", "script", "tts_script", "copy")
        or _first(payload, "script_text", "script", "copy")
    )


def _content_id(job: dict[str, Any], script: str) -> str:
    payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
    direct = _clean_text(
        _first(job, "content_id", "project_id")
        or _first(payload, "content_id", "project_id")
    )
    if direct:
        return direct

    topic = _clean_text(
        _first(job, "topic", "title")
        or _first(payload, "topic", "title")
    )
    digest = hashlib.sha256(
        f"{topic}\n{script}".encode("utf-8")
    ).hexdigest()[:20]
    return f"content_{digest}"


def _asset_rows(job: dict[str, Any]) -> list[dict[str, Any]]:
    plan = job.get("edit_plan") if isinstance(job.get("edit_plan"), dict) else {}
    result = job.get("result") if isinstance(job.get("result"), dict) else {}
    if not plan and isinstance(result.get("edit_plan"), dict):
        plan = result["edit_plan"]

    candidates: list[Any] = []
    for container in (plan, job, result):
        for key in (
            "clips",
            "assets",
            "selected_assets",
            "manual_assets",
            "auto_assets",
            "asset_usage",
        ):
            value = container.get(key)
            if isinstance(value, list):
                candidates.extend(value)

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    for index, item in enumerate(candidates, start=1):
        if not isinstance(item, dict):
            continue

        asset = item.get("asset") if isinstance(item.get("asset"), dict) else item
        asset_id = _clean_text(
            _first(asset, "asset_id", "id", "source_id")
            or _first(item, "asset_id", "id", "source_id")
        )
        asset_url = _clean_text(
            _first(asset, "url", "r2_url", "source_url")
            or _first(item, "url", "r2_url", "source_url")
        )
        asset_name = _clean_text(
            _first(asset, "name", "filename", "original_name")
            or _first(item, "name", "filename", "original_name")
        )

        try:
            clip_start = float(
                _first(item, "start", "start_time", "clip_start") or 0
            )
            clip_end = float(
                _first(item, "end", "end_time", "clip_end") or 0
            )
        except (TypeError, ValueError):
            clip_start = 0.0
            clip_end = 0.0

        unique_key = (
            f"{asset_id}|{asset_url}|{clip_start:.3f}|{clip_end:.3f}"
        )
        if not (asset_id or asset_url) or unique_key in seen:
            continue
        seen.add(unique_key)

        try:
            segment_index = int(
                _first(item, "segment_index", "index", "clip_index") or index
            )
        except (TypeError, ValueError):
            segment_index = index

        try:
            match_score = float(
                _first(item, "match_score", "score") or 0
            )
        except (TypeError, ValueError):
            match_score = 0.0

        rows.append(
            {
                "segment_index": segment_index,
                "segment_text": _clean_text(
                    _first(item, "segment_text", "narration", "text")
                ),
                "asset_id": asset_id,
                "asset_name": asset_name,
                "asset_url": asset_url,
                "selected_by": _clean_text(
                    _first(
                        item,
                        "selected_by",
                        "selection_source",
                        "source",
                    )
                    or ("human" if item.get("locked") else "auto")
                ),
                "match_score": match_score,
                "match_reason": json.dumps(
                    _first(
                        item,
                        "match_reason",
                        "reasons",
                        "keywords",
                    )
                    or [],
                    ensure_ascii=False,
                ),
                "clip_start": clip_start,
                "clip_end": clip_end,
            }
        )

    return rows


def _next_version(
    conn: sqlite3.Connection,
    content_id: str,
) -> int:
    row = conn.execute(
        """
        SELECT COALESCE(MAX(version_no), 0) AS value
        FROM script_versions
        WHERE content_id=?
        """,
        (content_id,),
    ).fetchone()
    return int(row["value"] or 0) + 1


def ingest_job(
    job_id: str,
    job: dict[str, Any],
) -> dict[str, Any]:
    now = time.time()
    script = _script_from_job(job)
    content_id = _content_id(job, script)
    payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}

    topic = _clean_text(
        _first(job, "topic", "title")
        or _first(payload, "topic", "title")
    )
    direction = _clean_text(
        _first(job, "direction", "content_type")
        or _first(payload, "direction", "content_type")
    )
    status = _clean_text(
        _first(job, "status", "stage") or "unknown"
    )
    material_mode = _clean_text(
        _first(job, "material_selection_mode")
        or _first(payload, "material_selection_mode")
        or (
            "hybrid"
            if _first(payload, "selected_assets", "asset_context")
            else "auto"
        )
    )
    result_url = _clean_text(
        _first(
            job,
            "subtitled_video_url",
            "video_url",
            "output_url",
            "result_url",
        )
    )
    voice = (
        job.get("voice_settings")
        or payload.get("voice_settings")
        or payload.get("segment_voice_settings")
        or {}
    )
    rows = _asset_rows(job)

    with _LOCK, _connect() as conn:
        existing = conn.execute(
            """
            SELECT created_at
            FROM content_runs
            WHERE content_id=?
            """,
            (content_id,),
        ).fetchone()
        created_at = (
            float(existing["created_at"])
            if existing
            else now
        )

        conn.execute(
            """
            INSERT OR REPLACE INTO content_runs
            (
              content_id,
              topic,
              direction,
              audience,
              market,
              city,
              source,
              status,
              latest_script,
              created_at,
              updated_at,
              metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                content_id,
                topic,
                direction,
                _clean_text(
                    _first(payload, "audience", "target_audience")
                ),
                _clean_text(_first(payload, "market")),
                _clean_text(_first(payload, "city")),
                _clean_text(
                    _first(payload, "source", "source_mode")
                    or "existing_edit"
                ),
                status,
                script,
                created_at,
                now,
                json.dumps(
                    {
                        "job_id": job_id,
                        "coverage": job.get("coverage") or {},
                    },
                    ensure_ascii=False,
                ),
            ),
        )

        if script:
            script_hash = hashlib.sha256(
                script.encode("utf-8")
            ).hexdigest()
            conn.execute(
                """
                INSERT OR IGNORE INTO script_versions
                (
                  content_id,
                  job_id,
                  version_no,
                  script_text,
                  script_hash,
                  source,
                  created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    content_id,
                    job_id,
                    _next_version(conn, content_id),
                    script,
                    script_hash,
                    "existing_edit_job",
                    now,
                ),
            )

        conn.execute(
            """
            INSERT OR REPLACE INTO production_jobs
            (
              job_id,
              content_id,
              status,
              material_mode,
              voice_json,
              result_url,
              payload_json,
              updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                content_id,
                status,
                material_mode,
                json.dumps(
                    voice,
                    ensure_ascii=False,
                    default=str,
                ),
                result_url,
                json.dumps(
                    job,
                    ensure_ascii=False,
                    default=str,
                ),
                now,
            ),
        )

        for row in rows:
            conn.execute(
                """
                INSERT OR IGNORE INTO asset_usage
                (
                  content_id,
                  job_id,
                  segment_index,
                  segment_text,
                  asset_id,
                  asset_name,
                  asset_url,
                  selected_by,
                  match_score,
                  match_reason,
                  clip_start,
                  clip_end,
                  created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    content_id,
                    job_id,
                    row["segment_index"],
                    row["segment_text"],
                    row["asset_id"],
                    row["asset_name"],
                    row["asset_url"],
                    row["selected_by"],
                    row["match_score"],
                    row["match_reason"],
                    row["clip_start"],
                    row["clip_end"],
                    now,
                ),
            )

    return {
        "ok": True,
        "content_id": content_id,
        "job_id": job_id,
        "script_recorded": bool(script),
        "asset_usage_count": len(rows),
        "material_mode": material_mode,
    }


def _jobs_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    nested = value.get("jobs")
    if isinstance(nested, dict):
        return nested
    return value


def _watch_loop() -> None:
    last_signature = ""
    while True:
        try:
            if EXISTING_JOBS.exists():
                stat = EXISTING_JOBS.stat()
                signature = f"{stat.st_mtime_ns}:{stat.st_size}"
                if signature != last_signature:
                    jobs = _jobs_mapping(
                        _read_json(EXISTING_JOBS, {})
                    )
                    for job_id, job in jobs.items():
                        if isinstance(job, dict):
                            ingest_job(str(job_id), job)
                    last_signature = signature
        except Exception as exc:
            error_file = (
                DATA_ROOT
                / "production_memory_watcher_error.log"
            )
            with error_file.open(
                "a",
                encoding="utf-8",
            ) as handle:
                handle.write(
                    f"{time.time()} "
                    f"{type(exc).__name__}: "
                    f"{exc}\n"
                )
        time.sleep(5)


def _start_watcher() -> None:
    global _WATCHER_STARTED
    if _WATCHER_STARTED:
        return
    _WATCHER_STARTED = True
    thread = threading.Thread(
        target=_watch_loop,
        name="production-memory-v10-40-8-6",
        daemon=True,
    )
    thread.start()


def _bigrams(value: str) -> set[str]:
    text = re.sub(r"\s+", "", _clean_text(value))
    return {
        text[index : index + 2]
        for index in range(max(0, len(text) - 1))
    }


def _similarity(left: str, right: str) -> float:
    a = _bigrams(left)
    b = _bigrams(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def install_production_memory_v10_40_8_6(
    app: FastAPI,
) -> None:
    if getattr(
        app.state,
        "production_memory_v10_40_8_6_installed",
        False,
    ):
        return

    app.state.production_memory_v10_40_8_6_installed = True
    _init_db()
    _start_watcher()

    @app.get("/api/video/production-memory/health")
    def memory_health() -> dict[str, Any]:
        with _connect() as conn:
            counts = {
                "content_runs": conn.execute(
                    "SELECT COUNT(*) AS n FROM content_runs"
                ).fetchone()["n"],
                "script_versions": conn.execute(
                    "SELECT COUNT(*) AS n FROM script_versions"
                ).fetchone()["n"],
                "production_jobs": conn.execute(
                    "SELECT COUNT(*) AS n FROM production_jobs"
                ).fetchone()["n"],
                "asset_usage": conn.execute(
                    "SELECT COUNT(*) AS n FROM asset_usage"
                ).fetchone()["n"],
            }

        return {
            "ok": True,
            "version": VERSION,
            "db_path": str(DB_PATH),
            "watching": str(EXISTING_JOBS),
            "counts": counts,
            "features": {
                "script_version_history": True,
                "asset_usage_history": True,
                "automatic_job_ingest": True,
                "duplicate_check": True,
                "material_mode_record": True,
            },
        }

    @app.get("/api/video/production-memory/history")
    def memory_history(
        limit: int = Query(50, ge=1, le=500),
    ) -> dict[str, Any]:
        with _connect() as conn:
            rows = conn.execute(
                """
                SELECT
                  c.*,
                  p.job_id,
                  p.material_mode,
                  p.result_url
                FROM content_runs c
                LEFT JOIN production_jobs p
                  ON p.content_id = c.content_id
                ORDER BY c.updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return {
            "ok": True,
            "items": [dict(row) for row in rows],
        }

    @app.get("/api/video/production-memory/assets/recent")
    def recent_assets(
        limit: int = Query(100, ge=1, le=1000),
    ) -> dict[str, Any]:
        with _connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM asset_usage
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return {
            "ok": True,
            "items": [dict(row) for row in rows],
        }

    @app.post(
        "/api/video/production-memory/duplicate-check"
    )
    def duplicate_check(
        payload: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any]:
        candidate = _clean_text(
            payload.get("script")
            or payload.get("text")
        )
        threshold = float(
            payload.get("threshold")
            or 0.68
        )

        with _connect() as conn:
            rows = conn.execute(
                """
                SELECT
                  content_id,
                  topic,
                  latest_script,
                  updated_at
                FROM content_runs
                WHERE latest_script != ''
                ORDER BY updated_at DESC
                LIMIT 500
                """
            ).fetchall()

        matches = []
        for row in rows:
            score = _similarity(
                candidate,
                str(row["latest_script"] or ""),
            )
            if score >= threshold:
                matches.append(
                    {
                        "content_id": row["content_id"],
                        "topic": row["topic"],
                        "score": round(score, 4),
                        "updated_at": row["updated_at"],
                    }
                )

        matches.sort(
            key=lambda item: item["score"],
            reverse=True,
        )
        top_score = (
            matches[0]["score"]
            if matches
            else 0.0
        )

        return {
            "ok": True,
            "duplicate": top_score >= 0.82,
            "needs_new_angle": (
                0.68 <= top_score < 0.82
            ),
            "top_score": top_score,
            "matches": matches[:20],
            "policy": {
                "block_at": 0.82,
                "change_angle_at": 0.68,
            },
        }

    @app.post(
        "/api/video/production-memory/ingest/{job_id}"
    )
    def manual_ingest(
        job_id: str,
    ) -> dict[str, Any]:
        jobs = _jobs_mapping(
            _read_json(EXISTING_JOBS, {})
        )
        job = jobs.get(job_id)
        if not isinstance(job, dict):
            return {
                "ok": False,
                "error": "job_not_found",
                "job_id": job_id,
            }
        return ingest_job(job_id, job)
