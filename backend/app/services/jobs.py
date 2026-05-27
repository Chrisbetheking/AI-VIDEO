from __future__ import annotations

import uuid
from typing import Any, Optional

from app.services.memory import MemoryStore, now_iso


def create_job(memory: MemoryStore, job_type: str, input_payload: dict[str, Any] | None = None, *, title: str = '') -> dict[str, Any]:
    job = {
        'id': str(uuid.uuid4()),
        'type': job_type,
        'title': title or job_type,
        'status': 'queued',
        'progress': 0,
        'input': input_payload or {},
        'output': {},
        'error': '',
        'started_at': None,
        'finished_at': None,
    }
    return memory.insert('jobs', job, require_supabase=False)


def start_job(memory: MemoryStore, job_id: str) -> dict[str, Any]:
    return memory.update_by_id('jobs', job_id, {'status': 'running', 'progress': 1, 'started_at': now_iso()})


def update_job(memory: MemoryStore, job_id: str, *, status: Optional[str] = None, progress: Optional[int] = None, output: dict[str, Any] | None = None, error: str = '') -> dict[str, Any]:
    patch: dict[str, Any] = {}
    if status is not None:
        patch['status'] = status
        if status in {'succeeded', 'failed', 'cancelled'}:
            patch['finished_at'] = now_iso()
    if progress is not None:
        patch['progress'] = max(0, min(100, int(progress)))
    if output is not None:
        patch['output'] = output
    if error:
        patch['error'] = error
    return memory.update_by_id('jobs', job_id, patch)


def get_job(memory: MemoryStore, job_id: str) -> dict[str, Any] | None:
    rows = memory.list('jobs', limit=1, extra_params={'id': f'eq.{job_id}'})
    return rows[0] if rows else None


def list_jobs(memory: MemoryStore, limit: int = 50) -> list[dict[str, Any]]:
    return memory.list('jobs', limit=limit)
