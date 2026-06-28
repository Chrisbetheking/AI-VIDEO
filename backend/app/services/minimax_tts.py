"""MiniMax TTS / voice clone provider.

Full flow:
  Reference audio upload -> file_id -> voice clone -> voice_id -> TTS synthesis.
Voice IDs are persisted to backend/data/minimax_voice.json.
"""

from __future__ import annotations

import base64
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from app.config import Settings


MINIMAX_TTS_BASE = "https://api.minimaxi.com/v1"

# Local persist path for voice_id
VOICE_JSON_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "minimax_voice.json"


# ---- Data classes ----

@dataclass
class MiniMaxTTSStatus:
    enabled: bool = False
    configured: bool = False
    has_api_key: bool = False
    has_voice_id: bool = False
    voice_id_masked: str = ""
    model: str = ""
    message: str = ""


@dataclass
class MiniMaxTTSResult:
    ok: bool = False
    enabled: bool = False
    file_path: Optional[Path] = None
    file_name: str = ""
    duration_seconds: float = 0.0
    provider: str = "minimax"
    message: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class VoiceCloneResult:
    ok: bool = False
    file_id: str = ""
    voice_id: str = ""
    message: str = ""
    raw_preview: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)


# ---- Voice ID persistence ----

def _ensure_voice_dir() -> None:
    VOICE_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)


def save_voice_id(voice_id: str, file_id: str = "", voice_name: str = "") -> Dict[str, Any]:
    """Persist voice_id to local JSON file."""
    _ensure_voice_dir()
    data: Dict[str, Any] = {}
    if VOICE_JSON_PATH.exists():
        try:
            data = json.loads(VOICE_JSON_PATH.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data["voice_id"] = voice_id
    data["file_id"] = file_id
    data["voice_name"] = voice_name or f"voice_{voice_id[:12]}"
    data["created_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    VOICE_JSON_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def load_voice_data() -> Dict[str, Any]:
    """Load saved voice data from local JSON."""
    if not VOICE_JSON_PATH.exists():
        return {}
    try:
        return json.loads(VOICE_JSON_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_voice_id() -> str:
    """Load saved voice_id. Returns empty string if not found."""
    return str(load_voice_data().get("voice_id", "")).strip()


# ---- Status ----

def get_minimax_tts_status(settings: Settings) -> MiniMaxTTSStatus:
    """Return rich MiniMax TTS provider status."""
    has_key = bool(getattr(settings, "minimax_api_key", ""))
    saved_id = load_voice_id()
    env_id = getattr(settings, "minimax_voice_id", "") or ""
    has_voice = bool(saved_id or env_id)
    enabled = bool(
        getattr(settings, "minimax_tts_enabled", False)
        and has_key
        and has_voice
    )
    voice_id = saved_id or env_id
    masked = _mask_id(voice_id) if voice_id else ""

    return MiniMaxTTSStatus(
        enabled=enabled,
        configured=bool(has_key and has_voice),
        has_api_key=has_key,
        has_voice_id=has_voice,
        voice_id_masked=masked,
        model=getattr(settings, "minimax_tts_model", "speech-2.8-hd") or "",
        message=(
            "MiniMax TTS is ready"
            if enabled
            else "MiniMax TTS is disabled, missing API key, or missing voice_id"
        ),
    )


def _mask_id(value: str) -> str:
    if len(value) <= 8:
        return value[:4] + "***"
    return value[:8] + "***"


# ---- Upload & Clone ----

async def upload_reference_audio(
    settings: Settings,
    file_bytes: bytes,
    filename: str,
) -> Dict[str, Any]:
    """Upload reference audio to MiniMax. Returns {file_id, ...}"""
    api_key = settings.minimax_api_key.strip()
    url = f"{MINIMAX_TTS_BASE}/files/upload"

    # Build multipart form
    import io
    boundary = f"----FormBoundary{uuid.uuid4().hex[:16]}"

    import email.mime.multipart
    import email.mime.base
    import email.mime.text
    import email.mime.application

    # Simple manual multipart
    purpose = "voice_clone"
    body_parts = []
    body_parts.append(f'--{boundary}')
    body_parts.append(f'Content-Disposition: form-data; name="purpose"')
    body_parts.append('')
    body_parts.append(purpose)
    body_parts.append(f'--{boundary}')
    body_parts.append(f'Content-Disposition: form-data; name="file"; filename="{filename}"')
    content_type = "audio/mpeg" if filename.lower().endswith(".mp3") else "audio/wav"
    body_parts.append(f'Content-Type: {content_type}')
    body_parts.append('')
    body_bytes = ("\r\n".join(body_parts) + "\r\n").encode("utf-8")
    body_bytes += file_bytes
    body_bytes += f"\r\n--{boundary}--\r\n".encode("utf-8")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(url, headers=headers, content=body_bytes)

    if resp.status_code >= 400:
        return {"ok": False, "message": f"Upload HTTP {resp.status_code}: {resp.text[:500]}"}

    data = resp.json()
    base_resp = data.get("base_resp", {})
    if base_resp.get("status_code", -1) != 0:
        return {
            "ok": False,
            "message": f"Upload error: {base_resp.get('status_msg', 'unknown')}",
            "raw_preview": json.dumps(data, ensure_ascii=False)[:300],
        }

    file_id = str(data.get("file", {}).get("file_id", ""))
    if not file_id:
        return {
            "ok": False,
            "message": "Upload succeeded but no file_id returned",
            "raw_preview": json.dumps(data, ensure_ascii=False)[:300],
        }

    return {"ok": True, "file_id": file_id, "raw": data}


async def create_voice_clone(
    settings: Settings,
    file_id: str,
    voice_id: str,
) -> Dict[str, Any]:
    """Create a voice clone from an uploaded file_id."""
    api_key = settings.minimax_api_key.strip()
    url = f"{MINIMAX_TTS_BASE}/voice_clone"

    body = {
        "file_id": int(file_id) if file_id.isdigit() else file_id,
        "voice_id": voice_id,
        "language_boost": "Chinese",
        "noise_reduction": 0,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=180) as client:
        resp = await client.post(url, headers=headers, json=body)

    if resp.status_code >= 400:
        return {"ok": False, "message": f"Clone HTTP {resp.status_code}: {resp.text[:500]}"}

    data = resp.json()
    base_resp = data.get("base_resp", {})
    status_code = base_resp.get("status_code", -1)

    # status_code 0 = success, some versions return different codes
    if status_code != 0:
        return {
            "ok": False,
            "message": f"Clone error {status_code}: {base_resp.get('status_msg', 'unknown')}",
            "raw_preview": json.dumps(data, ensure_ascii=False)[:300],
        }

    return {"ok": True, "voice_id": voice_id, "message": "Voice clone created", "raw": data}


# ---- TTS Synthesis ----

def _minimax_disabled() -> MiniMaxTTSResult:
    return MiniMaxTTSResult(
        ok=False,
        enabled=False,
        message="MiniMax TTS is disabled or missing API key / voice_id",
    )


async def synthesize_minimax(
    settings: Settings,
    text: str,
    voice_id: Optional[str] = None,
    model: Optional[str] = None,
) -> MiniMaxTTSResult:
    """Call MiniMax TTS API to synthesize speech. Auto-loads saved voice_id."""
    if not getattr(settings, "minimax_tts_enabled", False) or not getattr(settings, "minimax_api_key", ""):
        return _minimax_disabled()

    api_key = settings.minimax_api_key.strip()
    resolved_voice = (
        (voice_id or "").strip()
        or load_voice_id()
        or (settings.minimax_voice_id or "").strip()
        or ""
    )
    resolved_model = (model or settings.minimax_tts_model or "speech-2.8-hd").strip()

    if not resolved_voice:
        return MiniMaxTTSResult(
            ok=False,
            enabled=True,
            message="MiniMax TTS missing voice_id. Upload reference audio and create voice clone first.",
        )

    url = f"{MINIMAX_TTS_BASE}/t2a_v2"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": resolved_model,
        "text": text,
        "stream": False,
        "voice_setting": {
            "voice_id": resolved_voice,
            "speed": 1.0,
            "vol": 1.0,
            "pitch": 0,
        },
        "audio_setting": {
            "sample_rate": 32000,
            "bitrate": 128000,
            "format": "mp3",
            "channel": 1,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(url, headers=headers, json=body)
    except Exception as exc:
        return MiniMaxTTSResult(
            ok=False,
            enabled=True,
            message=f"MiniMax TTS request failed: {exc}",
        )

    if resp.status_code >= 400:
        return MiniMaxTTSResult(
            ok=False,
            enabled=True,
            message=f"MiniMax TTS HTTP {resp.status_code}: {resp.text[:500]}",
        )

    data = resp.json()
    base_resp = data.get("base_resp", {})
    status_code = base_resp.get("status_code", -1)

    if status_code != 0:
        return MiniMaxTTSResult(
            ok=False,
            enabled=True,
            message=f"MiniMax TTS error {status_code}: {base_resp.get('status_msg', 'unknown')}",
            raw=data,
        )

    audio_hex = data.get("data", {}).get("audio", "")
    if not audio_hex:
        audio_hex = data.get("audio", "") or data.get("data", {}).get("audio_data", "")

    if not audio_hex:
        return MiniMaxTTSResult(
            ok=False,
            enabled=True,
            message="MiniMax TTS returned no audio data",
            raw=data,
        )

    try:
        audio_bytes = bytes.fromhex(audio_hex)
    except ValueError:
        try:
            audio_bytes = base64.b64decode(audio_hex)
        except Exception:
            return MiniMaxTTSResult(
                ok=False,
                enabled=True,
                message="MiniMax TTS returned unparseable audio data",
                raw=data,
            )

    output = settings.outputs_dir / f"minimax_tts_{uuid.uuid4().hex}.mp3"
    output.write_bytes(audio_bytes)

    duration = _probe_duration(output) or _estimate_duration(text)

    return MiniMaxTTSResult(
        ok=True,
        enabled=True,
        file_path=output,
        file_name=output.name,
        duration_seconds=duration,
        provider="minimax",
        message="ok",
        raw=data,
    )


def _probe_duration(path: Path) -> float:
    import subprocess
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        if proc.returncode == 0:
            return max(0.0, float(proc.stdout.strip()))
    except Exception:
        pass
    return 0.0


def _estimate_duration(text: str) -> float:
    text_len = len("".join(text.split()))
    return min(180.0, max(1.0, text_len / 4.5))
