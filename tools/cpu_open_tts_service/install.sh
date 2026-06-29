#!/bin/bash
# ============================================================
# CPU Open-Source TTS experiment - install script
# Run on Ubuntu 22.04+ (4-core / 8GB RAM minimum)
# ============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"
echo "=== CPU Open TTS Install ==="
echo "Dir: $SCRIPT_DIR"

# 1. System dependencies
echo "[1/5] Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y -qq python3.10-venv python3-pip ffmpeg git wget 2>/dev/null || true

# 2. Create venv
echo "[2/5] Creating Python venv..."
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"
pip install --upgrade pip

# 3. Install PyTorch CPU-only
echo "[3/5] Installing PyTorch CPU..."
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu

# 4. Install ChatTTS
echo "[4/5] Installing ChatTTS..."
pip install ChatTTS transformers soundfile

# Install other deps from requirements
pip install -r "$SCRIPT_DIR/requirements.txt" 2>/dev/null || true

# 5. OpenVoice (manual clone - experimental)
echo "[5/5] OpenVoice (optional, manual)..."
OPENVOICE_DIR="$SCRIPT_DIR/../OpenVoice"
if [ ! -d "$OPENVOICE_DIR" ]; then
    echo "  OpenVoice not found. To install:"
    echo "    cd $SCRIPT_DIR/.."
    echo "    git clone https://github.com/myshell-ai/OpenVoice.git"
    echo "    cd OpenVoice"
    echo "    pip install -e ."
    echo "    wget https://myshell-public-repo-host.s3.amazonaws.com/openvoice/checkpoints_v2_0417.zip"
    echo "    unzip checkpoints_v2_0417.zip"
fi

echo ""
echo "=== Install complete ==="
echo "Run: source $VENV_DIR/bin/activate && python server.py"
echo "Test: curl http://127.0.0.1:7861/health"