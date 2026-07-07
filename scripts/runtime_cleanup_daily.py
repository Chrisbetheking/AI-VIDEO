from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BASE_DIR = Path("/opt/ai-video/backend")
sys.path.insert(0, str(BASE_DIR))

from app.services.runtime_safety_provider import cleanup_runtime_files


def main() -> None:
    max_age_hours = float(os.getenv("AI_VIDEO_CLEANUP_MAX_AGE_HOURS", "24"))
    max_delete_files = int(os.getenv("AI_VIDEO_CLEANUP_MAX_DELETE_FILES", "500"))

    result = cleanup_runtime_files(
        max_age_hours=max_age_hours,
        dry_run=False,
        max_delete_files=max_delete_files,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
