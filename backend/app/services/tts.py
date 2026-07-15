from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Optional, Tuple, Iterable, Any

import httpx

from app.config import Settings
from app.services.volcengine_voice_clone import load_voice_type
from app.schemas import TTSVoice, VoiceSegment


def sanitize_tts_text(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"\\(?:N|n|r|t)", "，", text)
    text = text.replace("\r", "，").replace("\n", "，").replace("\t", " ")
    text = re.sub(r"[／/\\|｜]+", "，", text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[，,]{2,}", "，", text)
    text = re.sub(r"，([。！？；])", r"\1", text)
    return text.strip("，。 ")

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
    env_voice_type = (os.environ.get('VOLC_TTS_VOICE_TYPE') or os.environ.get('VOLCENGINE_VOICE_TYPE') or '').strip()
    configured_voice_type = (env_voice_type or settings.volcengine_voice_type or load_voice_type() or '').strip()
    if configured_voice_type and not any(v.id == configured_voice_type for v in voices):
        voices.append(TTSVoice(id=configured_voice_type, name='豆包默认音色 / 复刻音色', provider='volcengine', note='来自 VOLC_TTS_VOICE_TYPE / VOLCENGINE_VOICE_TYPE 或已训练复刻音色'))
    if not voices:
        voices.append(TTSVoice(id='default', name='未配置云端音色', provider=settings.tts_provider, note='请配置 VOLCENGINE_VOICE_TYPE 或 TTS_VOICES_JSON'))
    return voices


def get_tts_voices(settings: Settings) -> list[TTSVoice]:
    # 正式版不再枚举 Windows SAPI；云端音色来自环境变量/火山控制台。
    return _configured_voices(settings)


async def synthesize_volcengine_v1(settings: Settings, text: str, voice: Optional[str], rate: Optional[str], speed_ratio: Optional[float] = None, volume_ratio: float = 1.0, pitch_ratio: float = 1.0) -> Path:
    text = sanitize_tts_text(text)
    if not text:
        raise RuntimeError("清洗后没有可合成的口播文本")
    """
    火山新版 API Key 接入优先：
    - header: x-api-key
    - app.cluster: volcano_icl
    - audio.voice_type: 复刻音色 ID，例如 S_toaCOKs32

    若未配置 VOLC_TTS_API_KEY，则保留旧版 AppID + AccessToken 兼容逻辑。
    """
    requested_voice = (voice or '').strip()
    env_api_key = (os.environ.get('VOLC_TTS_API_KEY') or '').strip()
    env_cluster = (os.environ.get('VOLC_TTS_CLUSTER') or '').strip()
    env_voice_type = (os.environ.get('VOLC_TTS_VOICE_TYPE') or os.environ.get('VOLCENGINE_VOICE_TYPE') or '').strip()
    env_endpoint = (os.environ.get('VOLC_TTS_ENDPOINT') or '').strip()

    if requested_voice.lower() in {'', 'default', 'auto', 'cloned'}:
        voice_type = (env_voice_type or settings.volcengine_voice_type or load_voice_type() or settings.tts_voice or '').strip()
    else:
        voice_type = requested_voice

    if voice_type.lower() in {'', 'default', 'auto', 'cloned'}:
        raise RuntimeError('缺少 VOLC_TTS_VOICE_TYPE；请填火山控制台“音色ID/voice_type”，不要填 default。')

    cluster = (env_cluster or settings.volcengine_cluster or 'volcano_icl').strip()
    endpoint = (env_endpoint or settings.volcengine_tts_endpoint or 'https://openspeech.bytedance.com/api/v1/tts').strip()

    speed = max(0.5, min(2.0, float(speed_ratio if speed_ratio is not None else _speed_ratio(rate))))
    volume = max(0.2, min(3.0, float(volume_ratio)))
    pitch = max(0.5, min(2.0, float(pitch_ratio)))

    reqid = uuid.uuid4().hex

    if env_api_key:
        # 新版 API Key 模式：与你刚刚 test_volc_apikey_tts.py 跑通的结构一致
        body = {
            'app': {
                'cluster': cluster,
            },
            'user': {
                'uid': getattr(settings, 'volcengine_uid', '') or 'ai-video-growth-studio',
            },
            'audio': {
                'voice_type': voice_type,
                'encoding': 'mp3',
                'speed_ratio': speed,
                'volume_ratio': volume,
                'pitch_ratio': pitch,
            },
            'request': {
                'reqid': reqid,
                'text': text,
                'text_type': 'plain',
                'operation': 'query',
            },
        }
        headers = {
            'x-api-key': env_api_key,
            'Content-Type': 'application/json',
        }
    else:
        # 旧版 AppID + AccessToken 兼容模式
        if not settings.volcengine_app_id.strip() or not settings.volcengine_access_token.strip():
            raise RuntimeError('缺少豆包语音配置：请配置 VOLC_TTS_API_KEY，或旧版 VOLCENGINE_APP_ID / VOLCENGINE_ACCESS_TOKEN。')

        body = {
            'app': {
                'appid': settings.volcengine_app_id,
                'token': settings.volcengine_access_token,
                'cluster': cluster,
            },
            'user': {
                'uid': settings.volcengine_uid,
            },
            'audio': {
                'voice_type': voice_type,
                'encoding': 'mp3',
                'speed_ratio': speed,
                'volume_ratio': volume,
                'pitch_ratio': pitch,
            },
            'request': {
                'reqid': reqid,
                'text': text,
                'text_type': 'plain',
                'operation': 'query',
            },
        }
        headers = {
            'Authorization': f'Bearer;{settings.volcengine_access_token}',
            'Content-Type': 'application/json',
        }

    async with httpx.AsyncClient(timeout=180) as client:
        resp = await client.post(endpoint, headers=headers, json=body)

    if resp.status_code >= 400:
        raise RuntimeError(f'豆包语音合成失败 HTTP {resp.status_code} (cluster={cluster}, voice_type={voice_type})：{resp.text[:1000]}')

    try:
        data = resp.json()
    except Exception:
        raise RuntimeError(f'豆包语音返回不是 JSON：{resp.text[:1000]}')

    code = str(data.get('code', '3000'))
    if code not in {'3000', '0', 'success', 'Success'} and not data.get('data'):
        raise RuntimeError(f'豆包语音合成失败：{json.dumps(data, ensure_ascii=False)[:1000]}')

    audio_b64 = data.get('data') or data.get('audio') or data.get('result', {}).get('audio')
    if not audio_b64:
        raise RuntimeError(f'豆包语音返回中没有音频 data 字段：{json.dumps(data, ensure_ascii=False)[:1000]}')

    output = settings.outputs_dir / f'tts_{uuid.uuid4().hex}.mp3'
    output.parent.mkdir(parents=True, exist_ok=True)
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
    text = sanitize_tts_text(text)
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




def _make_silence_wav(path: Path, milliseconds: int) -> None:
    seconds = max(0.05, milliseconds / 1000)
    cmd = [
        'ffmpeg', '-y', '-f', 'lavfi', '-i', 'anullsrc=channel_layout=stereo:sample_rate=44100',
        '-t', f'{seconds:.3f}', '-c:a', 'pcm_s16le', str(path),
    ]
    proc = run_cmd(cmd, timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(f'生成停顿音频失败：{proc.stderr[-800:]}')


def _convert_to_standard_wav(src: Path, dst: Path) -> None:
    cmd = ['ffmpeg', '-y', '-i', str(src), '-ar', '44100', '-ac', '2', '-c:a', 'pcm_s16le', str(dst)]
    proc = run_cmd(cmd, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(f'音频标准化失败：{proc.stderr[-1000:]}')


def _concat_wavs(parts: Iterable[Path], output: Path) -> None:
    part_list = [p for p in parts if p.exists() and p.stat().st_size > 0]
    if not part_list:
        raise RuntimeError('没有可合并的分段音频。')
    list_path = output.parent / f'concat_{uuid.uuid4().hex}.txt'
    list_path.write_text('\n'.join("file '" + str(p).replace("'", "'\\''") + "'" for p in part_list), encoding='utf-8')
    cmd = ['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', str(list_path), '-c:a', 'libmp3lame', '-q:a', '3', str(output)]
    proc = run_cmd(cmd, timeout=240)
    list_path.unlink(missing_ok=True)
    if proc.returncode != 0:
        raise RuntimeError(f'分段音频合并失败：{proc.stderr[-1200:]}')


async def synthesize_tts_segments(settings: Settings, segments: list[VoiceSegment], voice: Optional[str] = None, overall_rate: Optional[str] = None) -> Tuple[Path, float, Optional[str], list[dict[str, Any]]]:
    if not segments:
        raise RuntimeError('缺少分段配音内容。')

    provider = settings.tts_provider.lower().strip()
    tmp_dir = settings.tmp_dir / f'tts_segments_{uuid.uuid4().hex}'
    tmp_dir.mkdir(parents=True, exist_ok=True)
    wav_parts: list[Path] = []
    warnings: list[str] = []
    timings: list[dict[str, Any]] = []
    cursor = 0.0

    try:
        usable_segments = [seg for seg in segments[:30] if sanitize_tts_text(seg.text)]
        for index, segment in enumerate(usable_segments, start=1):
            text = sanitize_tts_text(segment.text)
            try:
                if provider in {'volcengine', 'doubao', 'bytedance'}:
                    raw = await synthesize_volcengine_v1(
                        settings,
                        text,
                        voice,
                        overall_rate,
                        speed_ratio=segment.speed_ratio,
                        volume_ratio=segment.volume_ratio,
                        pitch_ratio=segment.pitch_ratio,
                    )
                    wav = tmp_dir / f'{index:02d}_voice.wav'
                    await asyncio.to_thread(_convert_to_standard_wav, raw, wav)
                    try:
                        raw.unlink(missing_ok=True)
                    except Exception:
                        pass
                elif provider in {'sapi', 'windows', 'local'}:
                    wav = tmp_dir / f'{index:02d}_voice.wav'
                    await asyncio.to_thread(synthesize_sapi_to_wav, wav, text, voice or 'default', str(segment.speed_ratio))
                else:
                    raise RuntimeError(f'未知 TTS_PROVIDER={settings.tts_provider}')

                seg_duration = probe_duration(wav) or estimate_speech_duration(text)
                start_time = cursor
                end_time = start_time + seg_duration
                timings.append({
                    'index': index,
                    'text': text,
                    'start': round(start_time, 3),
                    'end': round(end_time, 3),
                    'duration': round(seg_duration, 3),
                })
                wav_parts.append(wav)
                cursor = end_time
                if segment.pause_after_ms > 0 and index < len(usable_segments):
                    pause_ms = int(segment.pause_after_ms)
                    pause = tmp_dir / f'{index:02d}_pause.wav'
                    await asyncio.to_thread(_make_silence_wav, pause, pause_ms)
                    wav_parts.append(pause)
                    cursor += max(0.0, pause_ms / 1000)
            except Exception as exc:
                warnings.append(f'第 {index} 段配音失败：{exc}')
                if not settings.allow_mock_tts:
                    raise
                silent_duration = estimate_speech_duration(text)
                silent = tmp_dir / f'{index:02d}_silent.wav'
                await asyncio.to_thread(_make_silence_wav, silent, int(silent_duration * 1000))
                timings.append({
                    'index': index,
                    'text': text,
                    'start': round(cursor, 3),
                    'end': round(cursor + silent_duration, 3),
                    'duration': round(silent_duration, 3),
                })
                cursor += silent_duration + max(0, segment.pause_after_ms) / 1000
                wav_parts.append(silent)

        output = settings.outputs_dir / f'tts_segments_{uuid.uuid4().hex}.mp3'
        await asyncio.to_thread(_concat_wavs, wav_parts, output)
        duration = probe_duration(output) or cursor or sum(estimate_speech_duration(seg.text) + seg.pause_after_ms / 1000 for seg in segments)
        warning = '；'.join(warnings) if warnings else None
        return output, duration, warning, timings
    finally:
        # 保留最终输出，清理临时分段文件。
        try:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass

async def synthesize_tts(settings: Settings, text: str, voice: Optional[str] = None, rate: Optional[str] = None) -> Tuple[Path, float, Optional[str]]:
    text = sanitize_tts_text(text)
    if not text:
        raise RuntimeError("清洗后没有可合成的口播文本")
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
