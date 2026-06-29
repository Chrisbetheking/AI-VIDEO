"""Volcengine/Doubao voice clone V3 service.

Flow: upload reference audio -> train voice clone -> get voice_type/speaker_id
Voice data persisted to backend/data/volcengine_voice.json
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from app.config import Settings


# Voice clone API endpoints (V3)
VOLC_TTS_BASE = "https://openspeech.bytedance.com/api/v3"

# Local persist path
VOICE_JSON_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "volcengine_voice.json"


@dataclass
class VoiceCloneStatus:
    ok: bool = True
    has_app_id: bool = False
    has_access_token: bool = False
    has_voice_type: bool = False
    voice_type_masked: str = ""
    voice_name: str = ""
    cluster: str = "volcano_icl"
    resource_id: str = "seed-icl-2.0"
    created_at: str = ""
    message: str = ""


@dataclass
class VoiceCloneResult:
    ok: bool = False
    voice_type: str = ""
    voice_name: str = ""
    message: str = ""
    raw_preview: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)


# ---- Voice JSON persistence ----

def _ensure_voice_dir() -> None:
    VOICE_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)


def save_voice_data(voice_type: str, voice_name: str = "", resource_id: str = "", cluster: str = "") -> Dict[str, Any]:
    _ensure_voice_dir()
    data: Dict[str, Any] = {
        "voice_type": voice_type,
        "voice_name": voice_name or f"voice_{voice_type[:12]}",
        "resource_id": resource_id or "seed-icl-2.0",
        "cluster": cluster or "volcano_icl",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    VOICE_JSON_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def load_voice_data() -> Dict[str, Any]:
    if not VOICE_JSON_PATH.exists():
        return {}
    try:
        return json.loads(VOICE_JSON_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_voice_type() -> str:
    return str(load_voice_data().get("voice_type", "")).strip()


def _mask(value: str) -> str:
    if len(value) <= 6:
        return value[:3] + "***"
    return value[:4] + "***"


# ---- Status ----

def get_voice_clone_status(settings: Settings) -> VoiceCloneStatus:
    has_app_id = bool(getattr(settings, "volcengine_app_id", ""))
    has_token = bool(getattr(settings, "volcengine_access_token", ""))
    saved = load_voice_data()
    saved_vt = saved.get("voice_type", "")
    env_vt = getattr(settings, "volcengine_voice_type", "") or ""
    voice_type = saved_vt or env_vt

    return VoiceCloneStatus(
        ok=True,
        has_app_id=has_app_id,
        has_access_token=has_token,
        has_voice_type=bool(voice_type),
        voice_type_masked=_mask(voice_type) if voice_type else "",
        voice_name=saved.get("voice_name", "") or (voice_type[:12] if voice_type else ""),
        cluster=saved.get("cluster", getattr(settings, "volcengine_cluster", "volcano_icl")) or "",
        resource_id=saved.get("resource_id", getattr(settings, "volcengine_resource_id", "seed-icl-2.0")) or "",
        created_at=saved.get("created_at", ""),
        message="Voice clone configured" if voice_type else "No voice_type saved. Upload reference audio to train.",
    )


# ---- Upload & Train ----

async def upload_and_train_voice(
    settings: Settings,
    file_bytes: bytes,
    filename: str,
    voice_name: str = "",
) -> VoiceCloneResult:
    """Upload reference audio to Volcengine and train voice clone V3.

    The Volcengine voice clone V3 API supports multipart upload with
    speaker training in a single call. The response includes the
    voice_type / speaker_id that can be used with seed-icl-2.0 TTS.
    """
    app_id = getattr(settings, "volcengine_app_id", "")
    access_token = getattr(settings, "volcengine_access_token", "")
    resource_id = getattr(settings, "volcengine_resource_id", "seed-icl-2.0") or "seed-icl-2.0"
    cluster = getattr(settings, "volcengine_cluster", "volcano_icl") or "volcano_icl"

    if not app_id or not access_token:
        return VoiceCloneResult(
            ok=False,
            message="Missing VOLCENGINE_APP_ID or VOLCENGINE_ACCESS_TOKEN",
        )

    # Voice clone V3 endpoint: upload + train
    url = f"{VOLC_TTS_BASE}/voice_clone"

    boundary = f"----FormBoundary{uuid.uuid4().hex[:16]}"

    # Build multipart form
    parts = []
    parts.append(f'--{boundary}')
    parts.append(f'Content-Disposition: form-data; name="appid"')
    parts.append('')
    parts.append(app_id)
    parts.append(f'--{boundary}')
    parts.append(f'Content-Disposition: form-data; name="token"')
    parts.append('')
    parts.append(access_token)
    parts.append(f'--{boundary}')
    parts.append(f'Content-Disposition: form-data; name="cluster"')
    parts.append('')
    parts.append(cluster)
    parts.append(f'--{boundary}')
    parts.append(f'Content-Disposition: form-data; name="resource_id"')
    parts.append('')
    parts.append(resource_id)
    parts.append(f'--{boundary}')
    parts.append(f'Content-Disposition: form-data; name="voice_name"')
    parts.append('')
    parts.append(voice_name or f"voice_{int(time.time())}")
    parts.append(f'--{boundary}')
    parts.append(f'Content-Disposition: form-data; name="audio"; filename="{filename}"')
    ct = "audio/mpeg" if filename.lower().endswith(".mp3") else "audio/wav"
    parts.append(f'Content-Type: {ct}')
    parts.append('')

    body_bytes = ("\r\n".join(parts) + "\r\n").encode("utf-8")
    body_bytes += file_bytes
    body_bytes += f"\r\n--{boundary}--\r\n".encode("utf-8")

    headers = {
        "Authorization": f"Bearer;{access_token}",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }

    # Also try JSON-based approach (some V3 endpoints)
    json_url = f"{VOLC_TTS_BASE}/voice_clone/create"
    json_body = {
        "app": {
            "appid": app_id,
            "token": access_token,
            "cluster": cluster,
        },
        "resource_id": resource_id,
        "voice_name": voice_name or f"voice_{int(time.time())}",
        "audio_format": filename.split(".")[-1] if "." in filename else "mp3",
    }

    last_error = ""
    last_raw = ""

    # Try multipart first
    try:
        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(url, headers=headers, content=body_bytes)
    except Exception as exc:
        last_error = f"Multipart request failed: {exc}"
    else:
        if resp.status_code < 400:
            data = resp.json()
            code = str(data.get("code", ""))
            voice_type = (
                data.get("voice_type", "")
                or data.get("speaker_id", "")
                or data.get("data", {}).get("voice_type", "")
                or data.get("result", {}).get("voice_type", "")
            )
            if voice_type:
                return VoiceCloneResult(
                    ok=True,
                    voice_type=voice_type,
                    voice_name=voice_name or voice_type,
                    message="Voice clone trained successfully",
                    raw=data,
                )
            if code in ("3000", "0"):
                last_raw = json.dumps(data, ensure_ascii=False)[:300]
                last_error = f"Response code {code} but no voice_type found"
            else:
                msg = data.get("message", "")
                if "resource ID is mismatched" in msg:
                    return VoiceCloneResult(
                        ok=False,
                        message="当前声音不属于 seed-icl-2.0 资源，请使用豆包声音复刻 V3 训练出的字符版/ICL 兼容音色。",
                        raw_preview=msg,
                    )
                last_error = f"HTTP {resp.status_code}: code={code}, msg={msg}"
                last_raw = json.dumps(data, ensure_ascii=False)[:300]
        else:
            last_error = f"HTTP {resp.status_code}: {resp.text[:300]}"

    # Try JSON endpoint as fallback
    try:
        json_headers = {
            "Authorization": f"Bearer;{access_token}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(json_url, headers=json_headers, json=json_body)
    except Exception as exc:
        last_error += f" | JSON fallback: {exc}"
        return VoiceCloneResult(
            ok=False,
            message=last_error,
            raw_preview=last_raw,
        )

    if resp.status_code < 400:
        data = resp.json()
        code = str(data.get("code", ""))
        voice_type = (
            data.get("voice_type", "")
            or data.get("speaker_id", "")
            or data.get("data", {}).get("voice_type", "")
            or data.get("result", {}).get("voice_type", "")
        )
        if voice_type:
            return VoiceCloneResult(
                ok=True,
                voice_type=voice_type,
                voice_name=voice_name or voice_type,
                message="Voice clone trained successfully",
                raw=data,
            )
        last_error += f" | JSON endpoint: code={code}, no voice_type"
    else:
        last_error += f" | JSON endpoint HTTP {resp.status_code}"

    return VoiceCloneResult(
        ok=False,
        message=last_error,
        raw_preview=last_raw or resp.text[:300] if 'resp' in dir() else "",
    )
