#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path("/opt/ai-video")
MAIN = ROOT / "backend/app/main.py"
SERVICES = ROOT / "backend/app/services"

LEGACY = [
    "full_ai_final_guard_provider",
    "full_ai_postprocess_guard_provider",
    "full_ai_tts_first_provider",
    "full_ai_tts_first_v2_provider",
    "full_ai_tts_first_v3_provider",
    "fal_prompt_guard_v10_6_provider",
    "fal_prompt_guard_v10_7_provider",
    "fal_prompt_guard_v10_11_provider",
    "fal_prompt_guard_v10_12_provider",
    "fal_prompt_guard_v10_13_provider",
    "fal_prompt_guard_v10_15_provider",
    "fal_prompt_guard_v10_16_provider",
    "fal_prompt_guard_v10_17_provider",
    "fal_prompt_guard_v10_18_provider",
]

text = MAIN.read_text(encoding="utf-8", errors="ignore") if MAIN.exists() else ""
active = []
present = []

for name in LEGACY:
    path = SERVICES / f"{name}.py"
    if path.exists():
        present.append(name)
    if name in text:
        active.append(name)

daemon_threads = []
for path in SERVICES.glob("*.py"):
    raw = path.read_text(encoding="utf-8", errors="ignore")
    if "threading.Thread" in raw and "daemon=True" in raw:
        daemon_threads.append(path.name)

report = {
    "ok": True,
    "main_file": str(MAIN),
    "legacy_files_present": present,
    "legacy_names_referenced_by_main": active,
    "providers_using_daemon_threads": sorted(daemon_threads),
    "review_gate_present": "AI_VIDEO_REVIEW_GATE_V1_START" in text,
    "graphic_window_repo_sync_present": "AI_VIDEO_GRAPHIC_WINDOW_REPO_SYNC_V1_START" in text,
    "recommendation": (
        "本补丁不自动删除旧 provider。先让审查闸门稳定运行，再分批迁移旧路由，避免一次性破坏生产。"
    ),
}

print(json.dumps(report, ensure_ascii=False, indent=2))
