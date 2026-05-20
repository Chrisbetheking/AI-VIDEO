from __future__ import annotations

import asyncio
import subprocess
import uuid
from pathlib import Path
from typing import Optional, Tuple

from app.config import Settings


def run_cmd(cmd: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)


def probe_duration(path: Path) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    proc = run_cmd(cmd, timeout=30)
    if proc.returncode != 0:
        return 0.0
    try:
        return max(0.0, float(proc.stdout.strip()))
    except ValueError:
        return 0.0


def estimate_speech_duration(text: str) -> float:
    # 中文普通口播约 4.5~5.5 字/秒，这里偏保守，保证字幕和画面时长足够。
    text_len = len("".join(text.split()))
    return min(180.0, max(4.0, text_len / 4.5))


def create_silent_audio(output_path: Path, duration: float) -> None:
    duration = max(1.0, duration)
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-t",
        f"{duration:.2f}",
        "-c:a",
        "libmp3lame",
        "-q:a",
        "4",
        str(output_path),
    ]
    proc = run_cmd(cmd, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(f"生成静音音频失败：{proc.stderr[-800:]}")


async def synthesize_tts(settings: Settings, text: str, voice: Optional[str] = None, rate: Optional[str] = None) -> Tuple[Path, float, Optional[str]]:
    output = settings.outputs_dir / f"tts_{uuid.uuid4().hex}.mp3"
    selected_voice = voice or settings.tts_voice
    selected_rate = rate or settings.tts_rate
    warning: Optional[str] = None

    if settings.tts_provider.lower() == "edge":
        try:
            import edge_tts  # type: ignore

            communicate = edge_tts.Communicate(text, selected_voice, rate=selected_rate)
            await communicate.save(str(output))
            duration = probe_duration(output) or estimate_speech_duration(text)
            return output, duration, None
        except Exception as exc:  # noqa: BLE001
            warning = f"云端 TTS 失败，已降级为静音音频：{exc}"
            if not settings.allow_mock_tts:
                raise RuntimeError(warning) from exc
    else:
        warning = f"未知 TTS_PROVIDER={settings.tts_provider}，已降级为静音音频。"
        if not settings.allow_mock_tts:
            raise RuntimeError(warning)

    # 保证现场演示不断链：TTS 调不通时仍然输出可合成音频。
    duration = estimate_speech_duration(text)
    await asyncio.to_thread(create_silent_audio, output, duration)
    return output, duration, warning
