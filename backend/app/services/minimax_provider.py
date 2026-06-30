"""MiniMax / Hailuo video generation provider (experimental).

Optional B-roll material generator for real_estate and foreign_trade.
Does NOT replace existing TTS, digital human, or lead capture pipelines.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import httpx

from app.config import Settings


MINIMAX_BASE_URL = "https://api.minimaxi.com/v1"


@dataclass
class MiniMaxStatus:
    enabled: bool = False
    video_model: str = ""
    tts_model: str = ""
    message: str = ""


@dataclass
class MiniMaxVideoResult:
    ok: bool = False
    enabled: bool = False
    task_id: str = ""
    status: str = "pending"  # pending, processing, completed, failed
    video_url: Optional[str] = None
    message: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)


def get_minimax_status(settings: Settings) -> MiniMaxStatus:
    """Return the current MiniMax provider status."""
    enabled = bool(
        getattr(settings, 'minimax_enabled', False)
        and getattr(settings, 'minimax_api_key', '')
    )
    return MiniMaxStatus(
        enabled=enabled,
        video_model=getattr(settings, 'minimax_video_model', 'MiniMax-Hailuo-2.3') or '',
        tts_model=getattr(settings, 'minimax_tts_model', '') or '',
        message="MiniMax provider is ready" if enabled else "MiniMax provider is disabled or missing API key",
    )


def _minimax_disabled() -> MiniMaxVideoResult:
    return MiniMaxVideoResult(
        ok=False,
        enabled=False,
        message="MiniMax provider is disabled or missing API key",
    )


async def text_to_video(
    settings: Settings,
    prompt: str,
    negative_prompt: str = "",
    duration_seconds: int = 5,
    resolution: str = "1080p",
) -> MiniMaxVideoResult:
    """Generate video from text prompt using MiniMax Hailuo.

    Args:
        settings: App settings with MiniMax credentials.
        prompt: Text prompt describing the desired video.
        negative_prompt: What to avoid in the video.
        duration_seconds: Target duration (5, 10).
        resolution: Output resolution (720p, 1080p).
    """
    if not getattr(settings, 'minimax_enabled', False) or not getattr(settings, 'minimax_api_key', ''):
        return _minimax_disabled()

    model = getattr(settings, 'minimax_video_model', 'MiniMax-Hailuo-2.3') or 'MiniMax-Hailuo-2.3'
    api_key = getattr(settings, 'minimax_api_key', '')

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "prompt": prompt[:2000],
        "negative_prompt": negative_prompt[:1000] if negative_prompt else "",
        "duration": duration_seconds,
        "resolution": resolution,
    }

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{MINIMAX_BASE_URL}/video/generation",
                headers=headers,
                json=payload,
            )
            data = resp.json()
            task_id = data.get("task_id", "") or data.get("id", "")
            return MiniMaxVideoResult(
                ok=True,
                enabled=True,
                task_id=task_id,
                status="pending",
                message="Video generation submitted",
                raw=data,
            )
    except httpx.TimeoutException:
        return MiniMaxVideoResult(
            ok=False, enabled=True, message="MiniMax API timeout",
        )
    except Exception as exc:
        return MiniMaxVideoResult(
            ok=False, enabled=True, message=f"MiniMax API error: {str(exc)[:500]}",
        )


async def image_to_video(
    settings: Settings,
    image_url: str,
    prompt: str = "",
    duration_seconds: int = 5,
) -> MiniMaxVideoResult:
    """Generate video from image using MiniMax Hailuo.

    Args:
        settings: App settings with MiniMax credentials.
        image_url: Public URL of the source image.
        prompt: Optional text to guide motion.
        duration_seconds: Target duration (5, 10).
    """
    if not getattr(settings, 'minimax_enabled', False) or not getattr(settings, 'minimax_api_key', ''):
        return _minimax_disabled()

    model = getattr(settings, 'minimax_video_model', 'MiniMax-Hailuo-2.3') or 'MiniMax-Hailuo-2.3'
    api_key = getattr(settings, 'minimax_api_key', '')

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "image_url": image_url,
        "prompt": prompt[:2000] if prompt else "smooth camera movement, cinematic",
        "duration": duration_seconds,
    }

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{MINIMAX_BASE_URL}/video/generation",
                headers=headers,
                json=payload,
            )
            data = resp.json()
            task_id = data.get("task_id", "") or data.get("id", "")
            return MiniMaxVideoResult(
                ok=True,
                enabled=True,
                task_id=task_id,
                status="pending",
                message="Image-to-video generation submitted",
                raw=data,
            )
    except httpx.TimeoutException:
        return MiniMaxVideoResult(
            ok=False, enabled=True, message="MiniMax API timeout",
        )
    except Exception as exc:
        return MiniMaxVideoResult(
            ok=False, enabled=True, message=f"MiniMax API error: {str(exc)[:500]}",
        )


async def query_video_status(
    settings: Settings,
    task_id: str,
) -> MiniMaxVideoResult:
    """Query the status of a MiniMax video generation task."""
    if not getattr(settings, 'minimax_enabled', False) or not getattr(settings, 'minimax_api_key', ''):
        return _minimax_disabled()

    api_key = getattr(settings, 'minimax_api_key', '')
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{MINIMAX_BASE_URL}/video/status/{task_id}",
                headers=headers,
            )
            data = resp.json()
            status = data.get("status", "unknown")
            video_url = data.get("video_url", "") or data.get("result", {}).get("video_url", "")
            return MiniMaxVideoResult(
                ok=True,
                enabled=True,
                task_id=task_id,
                status=status,
                video_url=video_url or None,
                message=f"Task status: {status}",
                raw=data,
            )
    except Exception as exc:
        return MiniMaxVideoResult(
            ok=False, enabled=True, task_id=task_id,
            message=f"MiniMax status query error: {str(exc)[:500]}",
        )


# B-roll prompt templates for industry packs
BROLL_PROMPTS: Dict[str, List[str]] = {
    "real_estate": [
        "Aerial drone shot of modern luxury condominium in Kuala Lumpur city center, KLCC skyline, golden hour lighting, cinematic 4K",
        "Elegant interior of a high-end apartment with floor-to-ceiling windows overlooking tropical cityscape, natural light, smooth pan",
        "Family walking through a green park in a residential community, children playing, warm sunset, Malaysia lifestyle",
        "Modern kitchen with marble countertops in a luxury condo, slow dolly movement, soft lighting",
    ],
    "foreign_trade": [
        "Modern factory production line with workers quality checking products, clean industrial lighting, smooth tracking shot",
        "Warehouse with neatly stacked shipping boxes ready for export, forklift moving pallets, professional lighting",
        "Close-up of product samples on a white desk, hands picking up items, catalog photoshoot style",
        "Shipping containers at port, crane loading, cinematic establishing shot, golden hour",
    ],
}


def get_broll_prompts(industry: str, count: int = 2) -> List[str]:
    """Get pre-built B-roll prompts for a given industry."""
    prompts = BROLL_PROMPTS.get(industry, BROLL_PROMPTS["real_estate"])
    return prompts[:max(1, min(count, len(prompts)))]
