#!/bin/bash
# Run CPU Open TTS service
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/venv/bin/activate"
export CPU_TTS_PORT="${CPU_TTS_PORT:-7861}"
export CPU_TTS_OUTPUT_DIR="${CPU_TTS_OUTPUT_DIR:-$SCRIPT_DIR/outputs}"
mkdir -p "$CPU_TTS_OUTPUT_DIR"
echo "Starting CPU Open TTS on http://127.0.0.1:$CPU_TTS_PORT"
exec python "$SCRIPT_DIR/server.py"