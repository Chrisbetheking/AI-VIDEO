from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any


BASE_DIR = Path(os.getenv("AI_VIDEO_BACKEND_DIR", "/opt/ai-video/backend"))
DATA_DIR = BASE_DIR / "data"

DEFAULT_MAX_UPLOAD_MB = int(os.getenv("AI_VIDEO_MAX_UPLOAD_MB", "300"))
DEFAULT_MAX_UPLOAD_BYTES = DEFAULT_MAX_UPLOAD_MB * 1024 * 1024

CLEANUP_DIRS = [
    DATA_DIR / "subtitles",
    DATA_DIR / "subtitle-burns",
    DATA_DIR / "subtitle-test",
    DATA_DIR / "real-shot",
    DATA_DIR / "hybrid",
]

SKIP_FILENAMES = {
    "jobs.sqlite",
    "jobs.sqlite3",
    "jobs.db",
    "jobs.sqlite3-shm",
    "jobs.sqlite3-wal",
}


def get_max_upload_bytes() -> int:
    try:
        mb = int(os.getenv("AI_VIDEO_MAX_UPLOAD_MB", str(DEFAULT_MAX_UPLOAD_MB)))
    except Exception:
        mb = DEFAULT_MAX_UPLOAD_MB
    return max(1, mb) * 1024 * 1024


def get_max_upload_mb() -> int:
    return int(get_max_upload_bytes() / 1024 / 1024)


def is_upload_too_large(content_length: str | None) -> tuple[bool, int, int]:
    max_bytes = get_max_upload_bytes()

    if not content_length:
        return False, 0, max_bytes

    try:
        size = int(content_length)
    except Exception:
        return False, 0, max_bytes

    return size > max_bytes, size, max_bytes


def _safe_file_info(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": str(path),
        "size": stat.st_size,
        "mtime": stat.st_mtime,
        "age_hours": round((time.time() - stat.st_mtime) / 3600, 2),
    }


def cleanup_runtime_files(
    max_age_hours: float = 24.0,
    dry_run: bool = True,
    max_delete_files: int = 200,
) -> dict[str, Any]:
    now = time.time()
    threshold = now - max_age_hours * 3600

    candidates: list[dict[str, Any]] = []
    deleted: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for root in CLEANUP_DIRS:
        if not root.exists():
            continue

        for path in root.rglob("*"):
            if not path.is_file():
                continue

            if path.name in SKIP_FILENAMES:
                continue

            try:
                stat = path.stat()
            except Exception as exc:
                errors.append({"path": str(path), "error": str(exc)})
                continue

            if stat.st_mtime > threshold:
                continue

            info = _safe_file_info(path)
            candidates.append(info)

            if not dry_run and len(deleted) < max_delete_files:
                try:
                    path.unlink()
                    deleted.append(info)
                except Exception as exc:
                    errors.append({"path": str(path), "error": str(exc)})

    total_candidate_size = sum(x.get("size", 0) for x in candidates)
    total_deleted_size = sum(x.get("size", 0) for x in deleted)

    return {
        "ok": True,
        "dry_run": dry_run,
        "max_age_hours": max_age_hours,
        "max_delete_files": max_delete_files,
        "candidate_count": len(candidates),
        "deleted_count": len(deleted),
        "candidate_size": total_candidate_size,
        "deleted_size": total_deleted_size,
        "cleanup_dirs": [str(x) for x in CLEANUP_DIRS],
        "candidates": candidates[:50],
        "deleted": deleted[:50],
        "errors": errors[:50],
        "message": "runtime 文件清理检查完成。dry_run=true 时不会删除文件。",
    }


def data_dir_summary() -> dict[str, Any]:
    summary: dict[str, Any] = {
        "base_dir": str(BASE_DIR),
        "data_dir": str(DATA_DIR),
        "dirs": [],
    }

    for root in CLEANUP_DIRS:
        file_count = 0
        total_size = 0

        if root.exists():
            for path in root.rglob("*"):
                if path.is_file():
                    try:
                        file_count += 1
                        total_size += path.stat().st_size
                    except Exception:
                        pass

        summary["dirs"].append(
            {
                "path": str(root),
                "exists": root.exists(),
                "file_count": file_count,
                "size": total_size,
            }
        )

    return summary


def health() -> dict[str, Any]:
    return {
        "ok": True,
        "provider": "runtime_safety",
        "max_upload_mb": get_max_upload_mb(),
        "max_upload_bytes": get_max_upload_bytes(),
        "cleanup": data_dir_summary(),
        "message": "runtime safety 已启用：上传大小限制 + 临时文件清理。",
    }
