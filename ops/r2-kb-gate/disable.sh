#!/usr/bin/env bash
set -Eeuo pipefail

PROD="${PROD:-/opt/ai-video}"
PYTHON="${PYTHON:-$PROD/backend/.venv/bin/python}"
STATE_FILE="${R2_KB_GATE_STATE_FILE:-/data/ai-video/backend-data/r2-kb-access-gate.json}"

export APP_DATA_DIR="${APP_DATA_DIR:-/data/ai-video/backend-data}"
export R2_KB_GATE_STATE_FILE="$STATE_FILE"

cd "$PROD/backend"

MESSAGE="${R2_KB_GATE_MESSAGE:-R2 knowledge base access is temporarily suspended. Please check the R2 account balance and billing status, then contact the administrator.}"

"$PYTHON" - "$MESSAGE" <<'PY'
import sys
from app.services.r2_kb_access_gate import write_state

message = sys.argv[1]

state = write_state(
    suspended=True,
    message=message,
    blocked_prefixes=[
        "/api/knowledge",
        "/api/storage/status",
        "/api/assets",
        "/api/video/r2",
        "/api/video/r2-direct-upload",
        "/api/video/asset-zip",
    ],
    updated_by="disable.sh",
)

print("R2 KNOWLEDGE BASE ACCESS: SUSPENDED")
print("data_preserved: true")
print("bucket_deleted: false")
print("message:", state["message"])
print("state_file:", __import__("os").environ["R2_KB_GATE_STATE_FILE"])
PY

curl -fsS \
  http://127.0.0.1:8000/api/admin/r2-kb-gate/status |
python3 -m json.tool
