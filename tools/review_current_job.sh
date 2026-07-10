#!/usr/bin/env bash
set -euo pipefail

JOB_ID="${1:-}"

if [ -z "$JOB_ID" ]; then
  JOB_ID="$(curl -fsS http://127.0.0.1:8000/api/video/review/latest | python3 -c 'import json,sys; print(json.load(sys.stdin).get("job_id",""))')"
fi

if [ -z "$JOB_ID" ]; then
  echo "没有找到已完成任务"
  exit 1
fi

echo "=== 自动审查：$JOB_ID ==="
curl -fsS -X POST "http://127.0.0.1:8000/api/video/review/$JOB_ID/run"   -H 'Content-Type: application/json'   -d '{"force_ai":true,"force":true}'   | python3 -m json.tool

echo ""
echo "=== 闸门状态 ==="
curl -fsS "http://127.0.0.1:8000/api/video/review/$JOB_ID/gate" | python3 -m json.tool

echo ""
echo "审查通过后仍需在网页点击「通过并生成9:16封面」，不会自动跳过人工确认。"
