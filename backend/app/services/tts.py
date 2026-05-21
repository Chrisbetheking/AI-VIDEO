from __future__ import annotations

import asyncio
import base64
import json
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Optional, Tuple

import httpx

from app.config import Settings
from app.schemas import TTSVoice


def run_cmd(cmd: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)


def probe_duration(path: Path) -> float:
    cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', str(path)]
    proc = run_cmd(cmd, timeout=30)
    if proc.returncode != 0:
        return 0.0
    try:
        return max(0.0, float(proc.stdout.strip()))
    except ValueError:
        return 0.0


def estimate_speech_duration(text: str) -> float:
    text_len = len(''.join(text.split()))
    return min(180.0, max(4.0, text_len / 4.5))


def create_silent_audio(output_path: Path, duration: float) -> None:
    duration = max(1.0, duration)
    cmd = [
        'ffmpeg', '-y', '-f', 'lavfi', '-i', 'anullsrc=channel_layout=stereo:sample_rate=44100',
        '-t', f'{duration:.2f}', '-c:a', 'libmp3lame', '-q:a', '4', str(output_path),
    ]
    proc = run_cmd(cmd, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(f'生成静音音频失败：{proc.stderr[-800:]}')


def _speed_ratio(rate: Optional[str]) -> float:
    if not rate:
        return 1.0
    value = str(rate).strip()
    try:
        if value.endswith('%'):
            pct = int(value.replace('%', ''))
            return max(0.5, min(2.0, 1.0 + pct / 100))
        return max(0.5, min(2.0, float(value)))
    except Exception:
        return 1.0


def _configured_voices(settings: Settings) -> list[TTSVoice]:
    voices: list[TTSVoice] = []
    if settings.tts_voices_json.strip():
        try:
            data = json.loads(settings.tts_voices_json)
            if isinstance(data, dict):
                data = [data]
            for item in data:
                if isinstance(item, dict) and item.get('id'):
                    voices.append(TTSVoice(
                        id=str(item.get('id')),
                        name=str(item.get('name') or item.get('id')),
                        provider=str(item.get('provider') or settings.tts_provider),
                        language=str(item.get('language') or 'zh-CN'),
                        note=str(item.get('note') or ''),
                    ))
        except Exception:
            pass
    if settings.volcengine_voice_type.strip() and not any(v.id == settings.volcengine_voice_type for v in voices):
        voices.append(TTSVoice(id=settings.volcengine_voice_type, name='豆包默认音色 / 复刻音色', provider='volcengine', note='来自 VOLCENGINE_VOICE_TYPE'))
    if not voices:
        voices.append(TTSVoice(id='default', name='未配置云端音色', provider=settings.tts_provider, note='请配置 VOLCENGINE_VOICE_TYPE 或 TTS_VOICES_JSON'))
    return voices


def get_tts_voices(settings: Settings) -> list[TTSVoice]:
    # 正式版不再枚举 Windows SAPI；云端音色来自环境变量/火山控制台。
    return _configured_voices(settings)


async def synthesize_volcengine_v1(settings: Settings, text: str, voice: Optional[str], rate: Optional[str]) -> Path:
    if not settings.volcengine_app_id.strip() or not settings.volcengine_access_token.strip():
        raise RuntimeError('缺少豆包语音配置：VOLCENGINE_APP_ID / VOLCENGINE_ACCESS_TOKEN。')
    voice_type = (voice or settings.volcengine_voice_type or '').strip()
    if voice_type in {'', 'default'}:
        raise RuntimeError('缺少 VOLCENGINE_VOICE_TYPE；如果是声音复刻，请填复刻成功后的音色 ID。')

    reqid = uuid.uuid4().hex
    body = {
        'app': {
            'appid': settings.volcengine_app_id,
            'token': settings.volcengine_access_token,
            'cluster': settings.volcengine_cluster,
        },
        'user': {'uid': settings.volcengine_uid},
        'audio': {
            'voice_type': voice_type,
            'encoding': 'mp3',
            'speed_ratio': _speed_ratio(rate),
            'volume_ratio': 1.0,
            'pitch_ratio': 1.0,
        },
        'request': {
            'reqid': reqid,
            'text': text,
            'text_type': 'plain',
            'operation': 'query',
            'with_frontend': 1,
            'frontend_type': 'unitTson',
        },
    }
    headers = {'Authorization': f'Bearer;{settings.volcengine_access_token}', 'Content-Type': 'application/json'}
    async with httpx.AsyncClient(timeout=180) as client:
        resp = await client.post(settings.volcengine_tts_endpoint, headers=headers, json=body)
    if resp.status_code >= 400:
        raise RuntimeError(f'豆包语音合成失败 HTTP {resp.status_code}：{resp.text[:1000]}')
    data = resp.json()
    # 常见成功码 3000；兼容部分网关只返回 data/audio 字段
    if str(data.get('code', '3000')) not in {'3000', '0', 'success'} and not data.get('data'):
        raise RuntimeError(f'豆包语音合成失败：{json.dumps(data, ensure_ascii=False)[:1000]}')
    audio_b64 = data.get('data') or data.get('audio') or data.get('result', {}).get('audio')
    if not audio_b64:
        raise RuntimeError(f'豆包语音返回中没有音频 data 字段：{json.dumps(data, ensure_ascii=False)[:1000]}')
    output = settings.outputs_dir / f'tts_{uuid.uuid4().hex}.mp3'
    output.write_bytes(base64.b64decode(audio_b64))
    return output


def parse_sapi_rate(rate: Optional[str]) -> int:
    if not rate:
        return 0
    value = str(rate).strip()
    try:
        if value.endswith('%'):
            pct = int(value.replace('%', ''))
            return max(-10, min(10, round(pct / 10)))
        return max(-10, min(10, int(value)))
    except Exception:
        return 0


def synthesize_sapi_to_wav(output_path: Path, text: str, voice: Optional[str], rate: Optional[str]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sapi_rate = parse_sapi_rate(rate)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        text_path = tmp_dir / 'tts_text.txt'
        ps1_path = tmp_dir / 'sapi_tts.ps1'
        text_path.write_text(text or ' ', encoding='utf-8')
        voice_value = (voice or '').strip()
        script = f'''
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Speech
$textPath = {json.dumps(str(text_path))}
$outputPath = {json.dumps(str(output_path))}
$voiceName = {json.dumps(voice_value)}
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.Rate = {sapi_rate}
$synth.Volume = 100
if ($voiceName -and $voiceName -ne "default" -and $voiceName -ne "sapi") {{ try {{ $synth.SelectVoice($voiceName) }} catch {{ }} }}
$text = Get-Content -LiteralPath $textPath -Raw -Encoding UTF8
$synth.SetOutputToWaveFile($outputPath)
$synth.Speak($text) | Out-Null
$synth.Dispose()
'''.strip()
        ps1_path.write_text(script, encoding='utf-8')
        proc = run_cmd(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(ps1_path)], timeout=240)
        if proc.returncode != 0:
            raise RuntimeError(f'Windows SAPI 配音失败：{proc.stderr[-1200:] or proc.stdout[-1200:]}')


async def synthesize_tts(settings: Settings, text: str, voice: Optional[str] = None, rate: Optional[str] = None) -> Tuple[Path, float, Optional[str]]:
    provider = settings.tts_provider.lower().strip()
    warning: Optional[str] = None

    try:
        if provider in {'volcengine', 'doubao', 'bytedance'}:
            output = await synthesize_volcengine_v1(settings, text, voice, rate)
        elif provider in {'sapi', 'windows', 'local'}:
            output = settings.outputs_dir / f'tts_{uuid.uuid4().hex}.wav'
            await asyncio.to_thread(synthesize_sapi_to_wav, output, text, voice or 'default', rate)
        else:
            raise RuntimeError(f'未知 TTS_PROVIDER={settings.tts_provider}')
        duration = probe_duration(output) or estimate_speech_duration(text)
        return output, duration, None
    except Exception as exc:
        if not settings.allow_mock_tts:
            raise
        output = settings.outputs_dir / f'tts_{uuid.uuid4().hex}.mp3'
        duration = estimate_speech_duration(text)
        await asyncio.to_thread(create_silent_audio, output, duration)
        warning = f'TTS 失败，已按 ALLOW_MOCK_TTS 降级为静音：{exc}'
        return output, duration, warning
