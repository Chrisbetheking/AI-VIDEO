import os
import uuid
import base64
import requests
from pathlib import Path

API_KEY = os.environ["VOLC_TTS_API_KEY"]
CLUSTER = os.environ.get("VOLC_TTS_CLUSTER", "volcano_icl")
VOICE_TYPE = os.environ["VOLC_TTS_VOICE_TYPE"]
ENDPOINT = "https://openspeech.bytedance.com/api/v1/tts"

TEXT = "来马来西亚买房，区域选错，几百万直接打水漂。"

payload = {
    "app": {
        "cluster": CLUSTER
    },
    "user": {
        "uid": "ai-video-growth-studio"
    },
    "audio": {
        "voice_type": VOICE_TYPE,
        "encoding": "mp3",
        "speed_ratio": 1.0,
        "volume_ratio": 1.0,
        "pitch_ratio": 1.0
    },
    "request": {
        "reqid": str(uuid.uuid4()),
        "text": TEXT,
        "text_type": "plain",
        "operation": "query"
    }
}

headers = {
    "x-api-key": API_KEY,
    "Content-Type": "application/json"
}

resp = requests.post(ENDPOINT, headers=headers, json=payload, timeout=180)

print("HTTP status:", resp.status_code)
print("Content-Type:", resp.headers.get("content-type"))

try:
    data = resp.json()
except Exception:
    print(resp.text[:2000])
    raise

print("code:", data.get("code"))
print("message:", data.get("message"))

if not data.get("data"):
    print("FULL RESPONSE:", data)
    raise SystemExit("ERROR: 没有返回音频 data")

audio = base64.b64decode(data["data"])
out = Path("volc_tts_test.mp3")
out.write_bytes(audio)

print("saved:", out.resolve())
print("size:", out.stat().st_size)
