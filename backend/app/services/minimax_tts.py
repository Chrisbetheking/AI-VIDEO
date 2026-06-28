"""MiniMax TTS / voice clone provider.

Supports MiniMax speech synthesis for /api/tts-segments and compose-video.
Does NOT replace volcengine TTS — runs as an alternative provider.
"""

from __future__ import annotations

import base64
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import httpx

from app.config import Settings


MINIMAX_TTS_BASE = "https://api.minimaxi.com/v1"


@dataclass
class MiniMaxTTSStatus:
    enabled: bool = False
    model: str = ""
    voice_id: str = ""
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


def get_minimax_tts_status(settings: Settings) -> MiniMaxTTSStatus:
    enabled = bool(
        getattr(settings, "minimax_tts_enabled", False)
        and getattr(settings, "minimax_api_key", "")
        and getattr(settings, "minimax_voice_id", "")
    )
    return MiniMaxTTSStatus(
        enabled=enabled,
        model=getattr(settings, "minimax_tts_model", "speech-2.8-hd") or "",
        voice_id=getattr(settings, "minimax_voice_id", "") or "",
        message=(
            "MiniMax TTS is ready"
            if enabled
            else "MiniMax TTS is disabled, missing API key, or missing voice_id"
        ),
    )


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
    """Call MiniMax TTS API to synthesize speech. Returns a MiniMaxTTSResult."""
    if not getattr(settings, "minimax_tts_enabled", False) or not getattr(settings, "minimax_api_key", ""):
        return _minimax_disabled()

    api_key = settings.minimax_api_key.strip()
    resolved_voice = (voice_id or settings.minimax_voice_id or "").strip()
    resolved_model = (model or settings.minimax_tts_model or "speech-2.8-hd").strip()

    if not resolved_voice:
        return MiniMaxTTSResult(
            ok=False,
            enabled=True,
            message="MiniMax TTS missing voice_id. Set MINIMAX_VOICE_ID or pass voice_id in request.",
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

    # Extract audio — MiniMax returns hex-encoded audio in data.audio
    audio_hex = data.get("data", {}).get("audio", "")
    if not audio_hex:
        # Some endpoints return base64
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

    # Probe duration
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
