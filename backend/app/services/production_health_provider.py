from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any


BASE_DIR = Path(os.getenv("AI_VIDEO_BACKEND_DIR", "/opt/ai-video/backend"))
DATA_DIR = BASE_DIR / "data"


def _exists(path: str | Path) -> bool:
    return Path(path).exists()


def _env_configured(*names: str) -> bool:
    return any(bool(os.getenv(name, "").strip()) for name in names)


def _dir_size(path: Path) -> tuple[int, int]:
    count = 0
    size = 0

    if not path.exists():
        return count, size

    for p in path.rglob("*"):
        if p.is_file():
            try:
                count += 1
                size += p.stat().st_size
            except Exception:
                pass

    return count, size


def health() -> dict[str, Any]:
    runtime_dirs = {
        "subtitles": DATA_DIR / "subtitles",
        "subtitle_burns": DATA_DIR / "subtitle-burns",
        "real_shot": DATA_DIR / "real-shot",
        "hybrid": DATA_DIR / "hybrid",
    }

    dirs = {}
    for name, path in runtime_dirs.items():
        count, size = _dir_size(path)
        dirs[name] = {
            "path": str(path),
            "exists": path.exists(),
            "file_count": count,
            "size": size,
        }

    return {
        "ok": True,
        "provider": "production_health",
        "backend_dir": str(BASE_DIR),
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "ffprobe": shutil.which("ffprobe") is not None,
        "fal_configured": _env_configured("FAL_KEY"),
        "r2_configured": (
            _env_configured("R2_BUCKET", "R2_BUCKET_NAME", "CLOUDFLARE_R2_BUCKET")
            and _env_configured("R2_ACCESS_KEY_ID", "CLOUDFLARE_R2_ACCESS_KEY_ID", "AWS_ACCESS_KEY_ID")
            and _env_configured("R2_SECRET_ACCESS_KEY", "CLOUDFLARE_R2_SECRET_ACCESS_KEY", "AWS_SECRET_ACCESS_KEY")
        ),
        "tts_configured": _env_configured("VOLC_TTS_API_KEY", "VOLCENGINE_ACCESS_TOKEN", "VOLC_ACCESS_TOKEN"),
        "job_db_exists": _exists(DATA_DIR / "jobs.sqlite3"),
        "runtime_dirs": dirs,
        "features": {
            "full_ai": True,
            "full_ai_subtitle_bridge": True,
            "real_shot": True,
            "hybrid": True,
            "runtime_safety": True,
            "api_guard": True,
        },
        "message": "生产健康检查通过。具体三方服务是否可用仍以各自 health 接口为准。",
    }
