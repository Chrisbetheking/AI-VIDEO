#!/usr/bin/env bash
set -u

SRC=$(find data/outputs outputs -type f -name "digital_human_fal019f14a3*.mp4" 2>/dev/null | sort | tail -1)

if [ -z "$SRC" ] || [ ! -f "$SRC" ]; then
  echo "没找到数字人视频"
  exit 0
fi

TS=$(date +%Y%m%d_%H%M%S)
OUT="data/outputs/final_delivery_${TS}.mp4"
COVER="data/outputs/final_cover_${TS}.jpg"

mkdir -p data/outputs

echo "SRC=$SRC"
echo "OUT=$OUT"

echo
echo "===== 1. 制作 9:16 平台交付版 ====="
ffmpeg -y -i "$SRC" \
  -filter_complex "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=24:1[bg];[0:v]scale=1080:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2[v]" \
  -map "[v]" -map 0:a? \
  -c:v libx264 -preset veryfast -crf 20 \
  -c:a aac -b:a 160k \
  -af "loudnorm=I=-16:TP=-1.5:LRA=11" \
  -movflags +faststart \
  -shortest "$OUT"

echo
echo "===== 2. 导出封面图 ====="
ffmpeg -y -ss 00:00:01 -i "$OUT" -frames:v 1 "$COVER"

echo
echo "===== 3. 本地质检 ====="
ffprobe -v error \
  -show_entries format=duration,size,bit_rate \
  -show_entries stream=codec_type,codec_name,width,height,r_frame_rate \
  -of json "$OUT"

echo
echo "===== 4. 上传 R2 ====="
export OUT COVER
python3 - <<'PY'
import os
from pathlib import Path
from app.settings import get_settings
from app.services.storage import maybe_upload_to_r2

s = get_settings()

out = Path(os.environ["OUT"])
cover = Path(os.environ["COVER"])

video_url = maybe_upload_to_r2(s, out, prefix="videos/final-delivery")
cover_url = maybe_upload_to_r2(s, cover, prefix="covers/final-delivery")

print("FINAL_VIDEO_URL=" + (video_url or ""))
print("FINAL_COVER_URL=" + (cover_url or ""))
print("LOCAL_VIDEO=" + str(out))
print("LOCAL_COVER=" + str(cover))
PY
