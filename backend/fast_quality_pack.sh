#!/usr/bin/env bash
set -u

BASE="http://127.0.0.1:8000"

echo "===== 1. 后端健康检查 ====="
curl -s "$BASE/api/health" | python3 -m json.tool || true

echo
echo "===== 2. 找最新数字人成片 ====="
LATEST_DH=$(find data/outputs outputs -type f -name "digital_human_*.mp4" 2>/dev/null | sort | tail -1)
echo "LATEST_DH=$LATEST_DH"

echo
echo "===== 3. 找最新音频 ====="
LATEST_AUDIO=$(find data/outputs outputs uploads -type f \( -iname "*.mp3" -o -iname "*.wav" -o -iname "*.m4a" \) 2>/dev/null | sort | tail -1)
echo "LATEST_AUDIO=$LATEST_AUDIO"

echo
echo "===== 4. 生成一段高质量正式口播文案 ====="
cat > /tmp/final_script.txt <<'EOF'
来马来西亚买房，最怕的不是价格高，而是区域选错。
同样是吉隆坡，有的地方租客稳定、转手容易；有的地方看起来便宜，后期却很难出租。
如果你是为了孩子教育、第二家园、资产配置，第一步不是看样板间，而是先看区域、交通、学校和真实租售数据。
真正稳的房子，不是销售说出来的，是市场长期验证出来的。
EOF

cat /tmp/final_script.txt

echo
echo "===== 5. 生成 TTS 音频 ====="
TTS_JSON=$(curl -s -X POST "$BASE/api/tts" \
  -H "Content-Type: application/json" \
  -d "$(python3 - <<'PY'
import json
text=open('/tmp/final_script.txt','r',encoding='utf-8').read()
print(json.dumps({"text":text,"voice":"default","rate":"0%"}, ensure_ascii=False))
PY
)")
echo "$TTS_JSON" | python3 -m json.tool

AUDIO_NAME=$(python3 - <<PY
import json
data=json.loads('''$TTS_JSON''')
print(data.get("file_name",""))
PY
)

echo "AUDIO_NAME=$AUDIO_NAME"

echo
echo "===== 6. 发起正式 fal 数字人口播 ====="
CREATE_JSON=$(curl -s -X POST "$BASE/api/digital-human/create" \
  -H "Content-Type: application/json" \
  -d "$(python3 - <<PY
import json
script=open('/tmp/final_script.txt','r',encoding='utf-8').read()
print(json.dumps({
  "avatar_file_name":"avatar_template.mp4",
  "audio_file_name":"$AUDIO_NAME",
  "title":"马来西亚房产避坑正式样片",
  "script":script,
  "engine":"fal_lipsync",
  "consent_confirmed":True
}, ensure_ascii=False))
PY
)")
echo "$CREATE_JSON" | python3 -m json.tool

JOB_ID=$(python3 - <<PY
import json
data=json.loads('''$CREATE_JSON''')
print(data.get("job_id",""))
PY
)

VIDEO_URL=$(python3 - <<PY
import json
data=json.loads('''$CREATE_JSON''')
print(data.get("video_url",""))
PY
)

echo
echo "JOB_ID=$JOB_ID"
echo "VIDEO_URL=$VIDEO_URL"

if [ -n "$VIDEO_URL" ]; then
  echo "数字人直接完成：$VIDEO_URL"
  exit 0
fi

if [ -z "$JOB_ID" ]; then
  echo "没有拿到 job_id，把上面 JSON 发给我。"
  exit 0
fi

echo
echo "===== 7. 轮询数字人结果 ====="
for i in {1..30}; do
  echo
  echo "----- check $i -----"
  STATUS_JSON=$(curl -sG "$BASE/api/digital-human/status" \
    --data-urlencode "job_id=$JOB_ID" \
    --data-urlencode "model=fal_lipsync")
  echo "$STATUS_JSON" | python3 -m json.tool

  DONE_URL=$(python3 - <<PY
import json
data=json.loads('''$STATUS_JSON''')
print(data.get("video_url",""))
PY
)
  if [ -n "$DONE_URL" ]; then
    echo
    echo "===== 成功，最终数字人口播视频 ====="
    echo "$DONE_URL"
    exit 0
  fi
  sleep 15
done

echo "还在生成，稍后继续查 JOB_ID=$JOB_ID"
