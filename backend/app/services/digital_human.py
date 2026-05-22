from __future__ import annotations

import json
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import httpx

from app.config import Settings


IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.webp'}
VIDEO_EXTS = {'.mp4', '.mov', '.m4v', '.webm'}
AUDIO_EXTS = {'.mp3', '.wav', '.m4a', '.aac', '.ogg'}


@dataclass
class DigitalHumanResult:
    status: str
    engine: str
    message: str
    video_path: Optional[Path] = None
    video_url: Optional[str] = None
    job_id: Optional[str] = None
    warnings: list[str] | None = None
    raw: dict[str, Any] | None = None


def _run(cmd: list[str], timeout: int = 240) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)


def _probe_duration(path: Path) -> float:
    proc = _run([
        'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1', str(path)
    ], timeout=30)
    if proc.returncode != 0:
        return 0.0
    try:
        return max(0.0, float(proc.stdout.strip()))
    except Exception:
        return 0.0


def create_static_avatar_preview(settings: Settings, avatar_path: Path, audio_path: Path, title: str = '') -> Path:
    """Fallback: not true lip-sync. It creates a 9:16 talking-card preview from image/video + audio.

    Real digital-human lip-sync should be performed by SadTalker / MuseTalk / Wav2Lip / LivePortrait worker.
    This fallback keeps the product usable when no GPU worker is configured.
    """
    out = settings.outputs_dir / f'digital_human_preview_{uuid.uuid4().hex}.mp4'
    avatar_ext = avatar_path.suffix.lower()
    duration = _probe_duration(audio_path) or 12.0

    vf_parts = [
        "scale=1080:1920:force_original_aspect_ratio=increase",
        "crop=1080:1920",
        "format=yuv420p",
    ]
    if title:
        safe_title = title.replace("'", "\\'").replace(':', '：')[:40]
        vf_parts.append(
            "drawbox=x=0:y=1580:w=1080:h=220:color=black@0.45:t=fill"
        )
        vf_parts.append(
            f"drawtext=text='{safe_title}':x=(w-text_w)/2:y=1640:fontcolor=white:fontsize=54:box=0"
        )
    vf = ','.join(vf_parts)

    if avatar_ext in IMAGE_EXTS:
        cmd = [
            'ffmpeg', '-y', '-loop', '1', '-i', str(avatar_path), '-i', str(audio_path),
            '-t', f'{duration:.2f}', '-vf', vf,
            '-c:v', 'libx264', '-preset', 'veryfast', '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-b:a', '160k', '-shortest', str(out)
        ]
    elif avatar_ext in VIDEO_EXTS:
        cmd = [
            'ffmpeg', '-y', '-stream_loop', '-1', '-i', str(avatar_path), '-i', str(audio_path),
            '-t', f'{duration:.2f}', '-vf', vf,
            '-map', '0:v:0', '-map', '1:a:0',
            '-c:v', 'libx264', '-preset', 'veryfast', '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-b:a', '160k', '-shortest', str(out)
        ]
    else:
        raise ValueError('数字人形象素材必须是图片或视频。')

    proc = _run(cmd, timeout=max(120, int(duration) + 180))
    if proc.returncode != 0:
        raise RuntimeError(f'生成数字人预览失败：{proc.stderr[-1200:]}')
    return out


async def call_external_digital_human_worker(
    settings: Settings,
    *,
    avatar_url: str,
    audio_url: str,
    script: str,
    title: str,
    engine: str,
    driver_video_url: str = '',
) -> DigitalHumanResult:
    """Call an external GPU worker.

    Expected webhook JSON response examples:
    {"status":"done","video_url":"https://.../out.mp4","job_id":"..."}
    {"status":"queued","job_id":"...","message":"queued"}
    """
    if not settings.digital_human_webhook_url:
        raise RuntimeError('未配置 DIGITAL_HUMAN_WEBHOOK_URL，无法调用真实数字人引擎。')

    headers = {'Content-Type': 'application/json'}
    if settings.digital_human_webhook_token:
        headers['Authorization'] = f'Bearer {settings.digital_human_webhook_token}'

    payload = {
        'engine': engine or settings.digital_human_engine,
        'avatar_url': avatar_url,
        'audio_url': audio_url,
        'driver_video_url': driver_video_url,
        'script': script,
        'title': title,
        'output_ratio': '9:16',
        'workspace_id': settings.workspace_id,
    }
    async with httpx.AsyncClient(timeout=settings.digital_human_timeout_seconds) as client:
        res = await client.post(settings.digital_human_webhook_url, headers=headers, json=payload)
        text = res.text
        if res.status_code >= 400:
            raise RuntimeError(f'数字人引擎调用失败 HTTP {res.status_code}: {text[:1000]}')
        try:
            data = res.json()
        except Exception:
            raise RuntimeError(f'数字人引擎没有返回 JSON：{text[:1000]}')

    video_url = data.get('video_url') or data.get('output_url') or data.get('result_url')
    status = data.get('status') or ('done' if video_url else 'queued')
    message = data.get('message') or ('数字人任务已完成。' if video_url else '数字人任务已提交，等待外部 GPU 引擎处理。')
    return DigitalHumanResult(
        status=status,
        engine=engine or settings.digital_human_engine,
        message=message,
        video_url=video_url,
        job_id=str(data.get('job_id') or data.get('id') or ''),
        warnings=list(data.get('warnings') or []),
        raw=data,
    )
