#!/usr/bin/env bash
set -Eeuo pipefail

PROD="${PROD:-/opt/ai-video}"
PYTHON="${PYTHON:-$PROD/backend/.venv/bin/python}"
STATE_FILE="${R2_KB_GATE_STATE_FILE:-/data/ai-video/backend-data/r2-kb-access-gate.json}"

export APP_DATA_DIR="${APP_DATA_DIR:-/data/ai-video/backend-data}"
export R2_KB_GATE_STATE_FILE="$STATE_FILE"

cd "$PROD/backend"

"$PYTHON" <<'PY'
from app.services.r2_kb_access_gate import write_state

state = write_state(
    suspended=False,
    updated_by="enable.sh",
)

print("R2 KNOWLEDGE BASE ACCESS: OPEN")
print("data_preserved: true")
print("bucket_deleted: false")
print("state_file:", __import__("os").environ["R2_KB_GATE_STATE_FILE"])
PY

curl -fsS \
  http://127.0.0.1:8000/api/admin/r2-kb-gate/status |
python3 -m json.tool
