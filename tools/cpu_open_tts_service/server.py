"""
CPU Open-Source TTS experiment service.

Runs ChatTTS and (optionally) OpenVoice on CPU only.
Standalone service on 127.0.0.1:7861 — does NOT touch the main backend.

Endpoints:
  GET  /health       – service status
  POST /synthesize   – generate speech

Modes:
  chattts_only     – ChatTTS Chinese speech (natural, not voice-cloned)
  openvoice_clone  – OpenVoice tone color conversion (requires reference audio)
"""

from __future__ import annotations

import io
import json
import logging
import os
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Force CPU
os.environ["CUDA_VISIBLE_DEVICES"] = ""

import torch
import torchaudio
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("cpu-open-tts")

# ---- Config ----
OUTPUT_DIR = Path(os.environ.get("CPU_TTS_OUTPUT_DIR", str(Path(__file__).parent / "outputs")))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

DEVICE = "cpu"
SAMPLE_RATE = 24000


# ---- Models (lazy load) ----
_chat_tts = None
_openvoice_se = None
_openvoice_tone = None


def _load_chat_tts():
    global _chat_tts
    if _chat_tts is not None:
        return _chat_tts
    log.info("Loading ChatTTS on CPU (first call, ~30-60s)...")
    from ChatTTS import ChatTTS as _ChatTTS
    model = _ChatTTS.ChatTTS()
    model.load(source="local", device=DEVICE, compile=False)
    _chat_tts = model
    log.info("ChatTTS loaded")
    return _chat_tts


def _load_openvoice():
    global _openvoice_se, _openvoice_tone
    if _openvoice_se is not None:
        return _openvoice_se, _openvoice_tone
    log.info("Loading OpenVoice on CPU (first call, ~60-120s)...")
    from openvoice.api import ToneColorConverter, BaseSpeakerTTS
    ckpt_base = os.environ.get("OPENVOICE_BASE_CKPT", "checkpoints_v2/base_speakers/EN")
    ckpt_converter = os.environ.get("OPENVOICE_CONVERTER_CKPT", "checkpoints_v2/converter")
    config_path = os.path.join(ckpt_converter, "config.json")
    if not os.path.exists(config_path):
        raise RuntimeError(f"OpenVoice converter checkpoint not found at {ckpt_converter}")

    base_speaker_tts = BaseSpeakerTTS(f"{ckpt_base}/config.json", device=DEVICE)
    base_speaker_tts.load_ckpt(f"{ckpt_base}/checkpoint.pth")

    tone_converter = ToneColorConverter(f"{ckpt_converter}/config.json", device=DEVICE)
    tone_converter.load_ckpt(f"{ckpt_converter}/checkpoint.pth")

    _openvoice_se = base_speaker_tts
    _openvoice_tone = tone_converter
    log.info("OpenVoice loaded")
    return _openvoice_se, _openvoice_tone


# ---- Schemas ----

class SynthesizeRequest(BaseModel):
    text: str
    reference_audio: str = ""   # path to reference mp3/wav
    mode: str = "chattts_only"  # chattts_only | openvoice_clone


class SynthesizeResponse(BaseModel):
    ok: bool
    file_path: str
    duration_seconds: float
    mode: str
    message: str = ""


class HealthResponse(BaseModel):
    ok: bool
    mode: str = "cpu_open_tts"
    device: str = DEVICE
    chattts_loaded: bool = False
    openvoice_loaded: bool = False


# ---- App ----

app = FastAPI(title="CPU Open TTS Experiment", version="0.1.0")


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        ok=True,
        chattts_loaded=_chat_tts is not None,
        openvoice_loaded=_openvoice_se is not None,
    )


@app.post("/synthesize", response_model=SynthesizeResponse)
def synthesize(req: SynthesizeRequest) -> SynthesizeResponse:
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Missing 'text' field")

    mode = req.mode.strip().lower()
    if mode not in ("chattts_only", "openvoice_clone"):
        raise HTTPException(status_code=400, detail=f"Unknown mode: {mode}. Use chattts_only or openvoice_clone")

    start = time.time()

    try:
        if mode == "chattts_only":
            return _synthesize_chattts(text)
        else:
            return _synthesize_openvoice(text, req.reference_audio)
    except Exception as exc:
        log.error(f"Synthesis failed: {exc}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Synthesis failed: {exc}")


def _synthesize_chattts(text: str) -> SynthesizeResponse:
    model = _load_chat_tts()

    # ChatTTS expects refiner text as list
    wavs = model.infer(
        [text],
        skip_refine_text=False,
        do_text_normalization=True,
        params_refine_text={"prompt": "[oral_2][laugh_0][break_6]"},
    )

    audio = wavs[0]  # numpy array
    if not isinstance(audio, torch.Tensor):
        audio = torch.from_numpy(audio)

    audio = audio.unsqueeze(0) if audio.dim() == 1 else audio
    duration = audio.shape[-1] / SAMPLE_RATE

    out_path = OUTPUT_DIR / f"chattts_{int(time.time())}.wav"
    torchaudio.save(str(out_path), audio.float(), SAMPLE_RATE)

    return SynthesizeResponse(
        ok=True,
        file_path=str(out_path),
        duration_seconds=round(duration, 2),
        mode="chattts_only",
        message="ChatTTS synthesis complete",
    )


def _synthesize_openvoice(text: str, ref_path: str) -> SynthesizeResponse:
    if not ref_path or not Path(ref_path).exists():
        raise HTTPException(status_code=400, detail=f"Reference audio not found: {ref_path}")

    base_tts, tone_converter = _load_openvoice()

    # Step 1: Generate base English speech
    # OpenVoice base speaker works best with English; we pass Chinese text via transliteration hint
    # For pure Chinese, use ChatTTS first then convert
    log.info("OpenVoice: generating base speech...")
    src_path = OUTPUT_DIR / f"openvoice_src_{int(time.time())}.wav"

    # Generate with base speaker (English-oriented, best effort for Chinese)
    base_tts.tts(text, speaker="default", output_path=str(src_path), speed=1.0)

    # Step 2: Tone color conversion
    log.info(f"OpenVoice: converting tone from reference: {ref_path}")
    out_path = OUTPUT_DIR / f"openvoice_out_{int(time.time())}.wav"

    # Extract source and target speaker embeddings
    source_se = torchaudio.functional.compute_kaldi_pitch(
        torchaudio.load(str(src_path))[0], sample_rate=16000
    ) if False else tone_converter.extract_se(str(src_path))

    # Simple conversion
    tone_converter.convert(
        audio_src_path=str(src_path),
        src_se=source_se,
        tgt_audio_path=ref_path,
        output_path=str(out_path),
        tau=0.3,
    )

    # Probe duration
    info = torchaudio.info(str(out_path))
    duration = info.num_frames / info.sample_rate if info.sample_rate > 0 else 0

    return SynthesizeResponse(
        ok=True,
        file_path=str(out_path),
        duration_seconds=round(duration, 2),
        mode="openvoice_clone",
        message="OpenVoice tone conversion complete (experimental CPU)",
    )


# ---- Entrypoint ----

if __name__ == "__main__":
    port = int(os.environ.get("CPU_TTS_PORT", "7861"))
    log.info(f"Starting CPU Open TTS service on 127.0.0.1:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
