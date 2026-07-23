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
    # Keep sentence-final punctuation so the cloud voice can preserve falling,
    # questioning and emphatic intonation. Only remove dangling comma separators.
    return re.sub(r"[，,]+$", "", text).strip()

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
                'with_timestamp': 1,
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
                'with_timestamp': 1,
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
    audio_duration = probe_duration(output)
    native_words = _extract_volcengine_word_timestamps(data, audio_duration=audio_duration)
    _timestamp_sidecar(output).write_text(
        json.dumps({
            'source': 'volcengine_native_word_timestamp' if native_words else 'timestamp_unavailable',
            'request_id': reqid,
            'log_id': resp.headers.get('X-Tt-Logid') or resp.headers.get('x-tt-logid'),
            'audio_duration': round(audio_duration, 4),
            'words': native_words,
        }, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
    return output




def _jsonish(value: Any) -> Any:
    current = value
    for _ in range(4):
        if not isinstance(current, str):
            break
        stripped = current.strip()
        if not stripped or stripped[0] not in "[{":
            break
        try:
            current = json.loads(stripped)
        except Exception:
            break
    return current


def _extract_volcengine_word_timestamps(payload: Any, *, audio_duration: float = 0.0) -> list[dict[str, Any]]:
    """Extract V1/V3 timestamp words from dicts, lists, or JSON-encoded addition fields."""
    candidates: list[dict[str, Any]] = []

    def visit(value: Any) -> None:
        value = _jsonish(value)
        if isinstance(value, dict):
            word = value.get("word") if value.get("word") is not None else value.get("text")
            start = next((value.get(k) for k in ("startTime", "start_time", "start", "begin_time", "beginTime") if value.get(k) is not None), None)
            end = next((value.get(k) for k in ("endTime", "end_time", "end", "finish_time", "finishTime") if value.get(k) is not None), None)
            if word is not None and start is not None and end is not None:
                try:
                    candidates.append({"word": str(word), "start": float(start), "end": float(end), "confidence": value.get("confidence")})
                except Exception:
                    pass
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)
    if not candidates:
        return []
    # Deduplicate recursive hits. Some responses expose the same timestamp list
    # both as parsed JSON and as a JSON-encoded `addition` field.
    unique: dict[tuple[str, float, float], dict[str, Any]] = {}
    for item in candidates:
        key = (str(item.get("word") or ""), round(float(item["start"]), 6), round(float(item["end"]), 6))
        unique[key] = item
    candidates = list(unique.values())
    candidates.sort(key=lambda item: (item["start"], item["end"], len(str(item.get("word") or ""))))
    maximum = max(item["end"] for item in candidates)
    # V3 examples use seconds; V1 timestamp payloads commonly use milliseconds.
    # Compare against the actual audio duration so long (>180 s) clips are not
    # accidentally divided by 1000.
    if maximum > 1000.0 or (audio_duration > 0 and maximum > audio_duration * 4.0 + 5.0):
        for item in candidates:
            item["start"] /= 1000.0
            item["end"] /= 1000.0

    # If both a sentence-level interval and finer word/character intervals are
    # returned, keep the finer intervals and drop the enclosing aggregate.
    fine_candidates: list[dict[str, Any]] = []
    for index, item in enumerate(candidates):
        contained = 0
        for other_index, other in enumerate(candidates):
            if index == other_index:
                continue
            if float(item["start"]) <= float(other["start"]) and float(other["end"]) <= float(item["end"]):
                if (float(other["end"]) - float(other["start"])) < (float(item["end"]) - float(item["start"])) - 0.001:
                    contained += 1
        if contained >= 2 and len(str(item.get("word") or "")) > 1:
            continue
        fine_candidates.append(item)
    candidates = fine_candidates or candidates
    candidates.sort(key=lambda item: (item["start"], item["end"]))

    cleaned: list[dict[str, Any]] = []
    last_end = 0.0
    for item in candidates:
        word = str(item.get("word") or "")
        start = max(0.0, float(item["start"]))
        end = max(start + 0.001, float(item["end"]))
        if end + 0.02 < last_end:
            continue
        cleaned.append({"word": word, "start": round(start, 4), "end": round(end, 4), "confidence": item.get("confidence"), "source": "volcengine_native_timestamp"})
        last_end = max(last_end, end)
    return cleaned


def _timestamp_sidecar(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".timestamps.json")

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
                    native_meta: dict[str, Any] = {}
                    sidecar = _timestamp_sidecar(raw)
                    if sidecar.is_file():
                        try:
                            loaded = json.loads(sidecar.read_text(encoding='utf-8'))
                            native_meta = loaded if isinstance(loaded, dict) else {}
                        except Exception:
                            native_meta = {}
                    wav = tmp_dir / f'{index:02d}_voice.wav'
                    await asyncio.to_thread(_convert_to_standard_wav, raw, wav)
                    try:
                        raw.unlink(missing_ok=True)
                        sidecar.unlink(missing_ok=True)
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
                native_words = []
                if provider in {'volcengine', 'doubao', 'bytedance'}:
                    for word in native_meta.get('words') or []:
                        if not isinstance(word, dict):
                            continue
                        try:
                            native_words.append({
                                **word,
                                'start': round(start_time + float(word.get('start') or 0.0), 4),
                                'end': round(start_time + float(word.get('end') or 0.0), 4),
                            })
                        except Exception:
                            continue
                timings.append({
                    'index': index,
                    'text': text,
                    'start': round(start_time, 3),
                    'end': round(end_time, 3),
                    'duration': round(seg_duration, 3),
                    'word_timeline': native_words,
                    'native_word_timestamp_count': len(native_words),
                    'timing_source': (
                        'volcengine_native_word_timestamp'
                        if native_words
                        else 'segment_duration_fallback'
                    ),
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


# =============================================================================
# V10.40.8.28 SEMANTIC EDITOR ENGINE — TTS END INTEGRITY
# =============================================================================
V28_TTS_END_PAD_SECONDS = 0.58
_V27_SYNTHESIZE_TTS_SEGMENTS = synthesize_tts_segments


def _v28_append_audio_tail(path: Path, seconds: float = V28_TTS_END_PAD_SECONDS) -> float:
    """Append a real silence tail. Never trim or time-stretch the spoken suffix."""
    original = probe_duration(path)
    if original <= 0:
        return original
    temporary = path.with_name(path.stem + '_v28_tail' + path.suffix)
    command = [
        'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
        '-i', str(path),
        '-af', f'apad=pad_dur={max(0.35, seconds):.3f}',
        '-c:a', 'libmp3lame', '-q:a', '2',
        str(temporary),
    ]
    proc = run_cmd(command, timeout=180)
    if proc.returncode != 0 or not temporary.exists():
        raise RuntimeError(f'V28 配音尾部保护失败：{proc.stderr[-900:]}')
    temporary.replace(path)
    final = probe_duration(path)
    if final < original + max(0.28, seconds - 0.12):
        raise RuntimeError(f'V28 配音尾部保护长度不足：before={original:.3f}, after={final:.3f}')
    return final


async def synthesize_tts_segments(settings: Settings, segments: list[VoiceSegment], voice: Optional[str] = None, overall_rate: Optional[str] = None) -> Tuple[Path, float, Optional[str], list[dict[str, Any]]]:
    output, duration, warning, timings = await _V27_SYNTHESIZE_TTS_SEGMENTS(
        settings, segments, voice=voice, overall_rate=overall_rate
    )
    speech_end = max((float(item.get('end') or 0.0) for item in timings if isinstance(item, dict)), default=duration)
    final_duration = await asyncio.to_thread(_v28_append_audio_tail, output)
    tail_seconds = max(0.0, final_duration - speech_end)
    if tail_seconds < 0.32:
        raise RuntimeError(
            f'V28 配音尾部安全区不足：speech_end={speech_end:.3f}, audio={final_duration:.3f}'
        )
    for item in timings:
        if isinstance(item, dict):
            item['tts_audio_duration_seconds'] = round(final_duration, 4)
            item['tts_tail_hold_seconds'] = round(tail_seconds, 4)
    return output, final_duration, warning, timings


# =============================================================================
# V10.40.8.29 NATURAL CONTINUOUS TTS — GROUPED SEMANTIC DELIVERY
# =============================================================================
V29_MAX_GROUP_CHARS = 92
V29_MAX_GROUP_SEGMENTS = 4
_V28_SYNTHESIZE_TTS_SEGMENTS = synthesize_tts_segments


def _v29_clean_alignment_text(value: Any) -> str:
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9%]+", "", str(value or ""))


def _v29_same_voice_profile(left: VoiceSegment, right: VoiceSegment) -> bool:
    return (
        abs(float(left.speed_ratio) - float(right.speed_ratio)) <= 0.03
        and abs(float(left.volume_ratio) - float(right.volume_ratio)) <= 0.05
        and abs(float(left.pitch_ratio) - float(right.pitch_ratio)) <= 0.03
        and str(left.emotion or "") == str(right.emotion or "")
    )


def _v29_strong_group_boundary(current: VoiceSegment, following: VoiceSegment | None) -> bool:
    if following is None:
        return True
    current_text = sanitize_tts_text(current.text)
    next_text = sanitize_tts_text(following.text)
    if int(current.pause_after_ms or 0) >= 360:
        return True
    if not _v29_same_voice_profile(current, following):
        return True
    if re.match(r"^(第一|第二|第三|第四|最后|总结|注意|重点|评论|关注|下一条)", next_text):
        return True
    if re.search(r"(评论|留言|关注|下一条|私信)", current_text):
        return True
    return False


def _v29_join_group_text(items: list[VoiceSegment]) -> str:
    parts: list[str] = []
    for segment in items:
        value = sanitize_tts_text(segment.text)
        if not value:
            continue
        if parts and not re.search(r"[。！？；，]$", parts[-1]):
            parts[-1] += "，"
        parts.append(value)
    return "".join(parts)


def _v29_group_voice_segments(segments: list[VoiceSegment]) -> tuple[list[VoiceSegment], list[list[int]]]:
    usable = [segment for segment in segments[:30] if sanitize_tts_text(segment.text)]
    groups: list[list[VoiceSegment]] = []
    mappings: list[list[int]] = []
    current: list[VoiceSegment] = []
    current_indexes: list[int] = []
    current_chars = 0

    for index, segment in enumerate(usable):
        value = sanitize_tts_text(segment.text)
        next_chars = len(_v29_clean_alignment_text(value))
        would_overflow = (
            current
            and (
                len(current) >= V29_MAX_GROUP_SEGMENTS
                or current_chars + next_chars > V29_MAX_GROUP_CHARS
                or not _v29_same_voice_profile(current[-1], segment)
            )
        )
        if would_overflow:
            groups.append(current)
            mappings.append(current_indexes)
            current = []
            current_indexes = []
            current_chars = 0
        current.append(segment)
        current_indexes.append(index)
        current_chars += next_chars
        following = usable[index + 1] if index + 1 < len(usable) else None
        if _v29_strong_group_boundary(segment, following):
            groups.append(current)
            mappings.append(current_indexes)
            current = []
            current_indexes = []
            current_chars = 0
    if current:
        groups.append(current)
        mappings.append(current_indexes)

    grouped_segments: list[VoiceSegment] = []
    for items in groups:
        first = items[0]
        last = items[-1]
        grouped_segments.append(VoiceSegment(
            text=_v29_join_group_text(items),
            emotion=first.emotion,
            speed_ratio=float(first.speed_ratio),
            volume_ratio=float(first.volume_ratio),
            pitch_ratio=float(first.pitch_ratio),
            pause_after_ms=max(0, min(320, int(last.pause_after_ms or 0))),
        ))
    return grouped_segments, mappings


def _v29_split_group_timing(
    group_timing: dict[str, Any],
    original_segments: list[VoiceSegment],
    original_indexes: list[int],
    group_id: int,
) -> list[dict[str, Any]]:
    group_start = float(group_timing.get("start") or 0.0)
    group_end = max(group_start + 0.05, float(group_timing.get("end") or group_start))
    words = [dict(item) for item in (group_timing.get("word_timeline") or []) if isinstance(item, dict)]
    words.sort(key=lambda item: (float(item.get("start") or 0.0), float(item.get("end") or 0.0)))
    lengths = [max(1, len(_v29_clean_alignment_text(original_segments[index].text))) for index in original_indexes]
    total = max(1, sum(lengths))
    output: list[dict[str, Any]] = []

    if words:
        word_lengths = [max(1, len(_v29_clean_alignment_text(item.get("word") or item.get("text")))) for item in words]
        cumulative_words: list[int] = []
        running = 0
        for length in word_lengths:
            running += length
            cumulative_words.append(running)
        word_cursor = 0
        consumed_chars = 0
        for local_index, (original_index, wanted_length) in enumerate(zip(original_indexes, lengths)):
            consumed_chars += wanted_length
            target_chars = max(1, round(cumulative_words[-1] * consumed_chars / total))
            end_word = word_cursor
            while end_word + 1 < len(words) and cumulative_words[end_word] < target_chars:
                end_word += 1
            selected = words[word_cursor : end_word + 1] or words[min(word_cursor, len(words) - 1): min(word_cursor, len(words) - 1) + 1]
            seg_start = float(selected[0].get("start") or group_start)
            seg_end = float(selected[-1].get("end") or seg_start + 0.05)
            if local_index == len(original_indexes) - 1:
                seg_end = max(seg_end, group_end)
            output.append({
                "index": original_index + 1,
                "text": sanitize_tts_text(original_segments[original_index].text),
                "start": round(seg_start, 3),
                "end": round(max(seg_start + 0.05, seg_end), 3),
                "duration": round(max(0.05, seg_end - seg_start), 3),
                "word_timeline": selected,
                "native_word_timestamp_count": len(selected),
                "timing_source": "volcengine_native_word_timestamp",
                "continuous_group_id": group_id,
                "continuous_group_size": len(original_indexes),
            })
            word_cursor = min(len(words), end_word + 1)
    else:
        cursor = group_start
        for local_index, (original_index, wanted_length) in enumerate(zip(original_indexes, lengths)):
            seg_end = group_end if local_index == len(original_indexes) - 1 else cursor + (group_end - group_start) * wanted_length / total
            output.append({
                "index": original_index + 1,
                "text": sanitize_tts_text(original_segments[original_index].text),
                "start": round(cursor, 3),
                "end": round(max(cursor + 0.05, seg_end), 3),
                "duration": round(max(0.05, seg_end - cursor), 3),
                "word_timeline": [],
                "native_word_timestamp_count": 0,
                "timing_source": "continuous_group_duration_fallback",
                "continuous_group_id": group_id,
                "continuous_group_size": len(original_indexes),
            })
            cursor = seg_end
    return output


async def synthesize_tts_segments(
    settings: Settings,
    segments: list[VoiceSegment],
    voice: Optional[str] = None,
    overall_rate: Optional[str] = None,
) -> Tuple[Path, float, Optional[str], list[dict[str, Any]]]:
    grouped_segments, mappings = _v29_group_voice_segments(segments)
    if not grouped_segments:
        raise RuntimeError("V29 连续配音分组后没有可合成文本")
    output, duration, warning, grouped_timings = await _V28_SYNTHESIZE_TTS_SEGMENTS(
        settings,
        grouped_segments,
        voice=voice,
        overall_rate=overall_rate,
    )
    usable_original = [segment for segment in segments[:30] if sanitize_tts_text(segment.text)]
    expanded: list[dict[str, Any]] = []
    for group_index, original_indexes in enumerate(mappings, start=1):
        timing = grouped_timings[group_index - 1] if group_index - 1 < len(grouped_timings) else {}
        expanded.extend(_v29_split_group_timing(timing, usable_original, original_indexes, group_index))
    expanded.sort(key=lambda item: int(item.get("index") or 0))
    if len(expanded) != len(usable_original):
        raise RuntimeError(
            f"V29 连续配音时间展开数量错误：expected={len(usable_original)}, actual={len(expanded)}"
        )
    tail_seconds = max(0.0, duration - max((float(item.get("end") or 0.0) for item in expanded), default=duration))
    for item in expanded:
        item["tts_audio_duration_seconds"] = round(duration, 4)
        item["tts_tail_hold_seconds"] = round(tail_seconds, 4)
        item["continuous_tts"] = True
        item["continuous_group_count"] = len(grouped_segments)
    return output, duration, warning, expanded
