#!/usr/bin/env bash
set -Eeuo pipefail

curl -fsS \
  http://127.0.0.1:8000/api/admin/r2-kb-gate/status |
python3 -m json.tool
