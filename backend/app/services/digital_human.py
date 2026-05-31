from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote, urlencode, urlparse

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
    """Fallback: static image/video card + audio. Not true lip-sync."""
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
        vf_parts.append("drawbox=x=0:y=1580:w=1080:h=220:color=black@0.45:t=fill")
        vf_parts.append(f"drawtext=text='{safe_title}':x=(w-text_w)/2:y=1640:fontcolor=white:fontsize=54:box=0")
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
    """Call a custom external GPU/API worker."""
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
    message = data.get('message') or ('数字人任务已完成。' if video_url else '数字人任务已提交，等待外部 GPU/API 引擎处理。')
    return DigitalHumanResult(
        status=status,
        engine=engine or settings.digital_human_engine,
        message=message,
        video_url=video_url,
        job_id=str(data.get('job_id') or data.get('task_id') or data.get('id') or ''),
        warnings=list(data.get('warnings') or []),
        raw=data,
    )


def _fal_headers(settings: Settings) -> dict[str, str]:
    key = (settings.fal_key or '').strip()
    if not key:
        raise RuntimeError('未配置 FAL_KEY，无法调用 fal.ai Lipsync。请把 fal API Key 放到 Render 环境变量，不要写在前端代码里。')
    return {
        'Authorization': f'Key {key}',
        'Content-Type': 'application/json',
    }


def _fal_endpoint(settings: Settings) -> str:
    endpoint = (settings.fal_lipsync_endpoint or 'fal-ai/sync-lipsync').strip().strip('/')
    return endpoint or 'fal-ai/sync-lipsync'


def _extract_fal_video_url(data: Any) -> str:
    if isinstance(data, dict):
        # fal queue result may be {video:{url}} or SDK-like {data:{video:{url}}}.
        for path in [
            ('video', 'url'), ('data', 'video', 'url'), ('output', 'video', 'url'),
            ('video_url',), ('output_url',), ('result_url',), ('url',),
        ]:
            cur: Any = data
            ok = True
            for key in path:
                if isinstance(cur, dict) and key in cur:
                    cur = cur[key]
                else:
                    ok = False
                    break
            if ok and isinstance(cur, str) and cur.startswith(('http://', 'https://')):
                return cur
        for v in data.values():
            found = _extract_fal_video_url(v)
            if found:
                return found
    elif isinstance(data, list):
        for item in data:
            found = _extract_fal_video_url(item)
            if found:
                return found
    elif isinstance(data, str) and data.startswith(('http://', 'https://')):
        low = data.lower()
        if any(x in low for x in ('.mp4', '.mov', '.webm', 'video', 'fal.media')):
            return data
    return ''


def _add_logs_param(url: str) -> str:
    url = (url or '').strip()
    if not url:
        return url
    if 'logs=' in url:
        return url
    return url + ('&' if '?' in url else '?') + 'logs=1'


async def _fal_get_json(client: httpx.AsyncClient, url: str, headers: dict[str, str]) -> dict[str, Any]:
    res = await client.get(url, headers=headers)
    text = res.text
    if res.status_code >= 400:
        raise RuntimeError(f'fal.ai 请求失败 HTTP {res.status_code}: {text[:1200]}')
    try:
        data = res.json()
    except Exception:
        raise RuntimeError(f'fal.ai 没有返回 JSON：{text[:1200]}')
    return data if isinstance(data, dict) else {'data': data}


async def _fal_try_get_json(client: httpx.AsyncClient, urls: list[str], headers: dict[str, str]) -> tuple[dict[str, Any] | None, str, str]:
    """Try several fal queue URLs. Return (data, url, error_text).

    fal's REST submit response includes exact status_url/response_url. Using those is
    safer than rebuilding URLs from endpoint + request_id, especially when a model
    changes path/version.
    """
    errors: list[str] = []
    seen: set[str] = set()
    for url in urls:
        url = (url or '').strip()
        if not url or url in seen:
            continue
        seen.add(url)
        try:
            return await _fal_get_json(client, url, headers), url, ''
        except Exception as exc:
            errors.append(f'{url} => {exc}')
    return None, '', '；'.join(errors)[-1800:]


async def query_fal_lipsync(
    settings: Settings,
    *,
    request_id: str,
    status_url: str = '',
    response_url: str = '',
    endpoint: str = '',
) -> DigitalHumanResult:
    """Query a queued fal.ai lipsync request and return a normalized result.

    Prefer the exact status_url/response_url returned by fal at submit time.
    This avoids false failures when a model endpoint/version changes or fal returns
    405 on a reconstructed status URL.
    """
    request_id = (request_id or '').strip()
    if request_id.startswith('fal:'):
        request_id = request_id.split(':', 1)[1]
    if not request_id:
        raise RuntimeError('缺少 fal request_id，无法查询数字人任务。')
    endpoint = (endpoint or _fal_endpoint(settings)).strip().strip('/')
    headers = _fal_headers(settings)
    base = f'https://queue.fal.run/{endpoint}/requests/{request_id}'

    async with httpx.AsyncClient(timeout=max(30, min(settings.digital_human_timeout_seconds, 120))) as client:
        status_candidates = [
            _add_logs_param(status_url),
            f'{base}/status?logs=1',
            f'{base}/status',
        ]
        status_data, used_status_url, status_error = await _fal_try_get_json(client, status_candidates, headers)

        # If status polling is rejected by fal (commonly HTTP 405 on stale/rebuilt URL),
        # try the response endpoint directly. Completed requests can often be recovered.
        response_candidates = [
            response_url,
            str((status_data or {}).get('response_url') or ''),
            f'{base}/response',
        ]
        if status_data is None:
            result_data, used_response_url, response_error = await _fal_try_get_json(client, response_candidates, headers)
            if result_data is None:
                return DigitalHumanResult(
                    status='running',
                    engine=f'fal:{endpoint}',
                    message='fal.ai 已扣费/已提交，但状态接口暂时无法查询；请稍后再点查询，或去 fal 后台 Request History 查看结果。',
                    job_id=f'fal:{request_id}',
                    warnings=[f'状态查询失败：{status_error}', f'结果查询失败：{response_error}'],
                    raw={'request_id': request_id, 'status_url': status_url, 'response_url': response_url, 'status_error': status_error, 'response_error': response_error},
                )
            video_url = _extract_fal_video_url(result_data)
            if video_url:
                return DigitalHumanResult(
                    status='done', engine=f'fal:{endpoint}', message='fal.ai 真人模板口型同步已生成。',
                    video_url=video_url, job_id=f'fal:{request_id}', warnings=[], raw={**result_data, '_used_response_url': used_response_url},
                )
            return DigitalHumanResult(
                status='running', engine=f'fal:{endpoint}',
                message='fal.ai 任务已提交，但结果暂未返回视频 URL。请稍后再查询。',
                job_id=f'fal:{request_id}', warnings=[status_error, response_error], raw=result_data,
            )

        status = str(status_data.get('status') or '').upper()
        response_url = response_url or str(status_data.get('response_url') or '')
        if status != 'COMPLETED':
            if status_data.get('error'):
                return DigitalHumanResult(
                    status='failed', engine=f'fal:{endpoint}', message=f"fal.ai 任务失败：{status_data.get('error')}",
                    job_id=f'fal:{request_id}', warnings=[str(status_data.get('error_type') or '')], raw={**status_data, '_used_status_url': used_status_url},
                )
            message = 'fal.ai 正在排队/生成中。'
            if status == 'IN_QUEUE' and status_data.get('queue_position') is not None:
                message += f" 当前队列位置：{status_data.get('queue_position')}。"
            elif status == 'IN_PROGRESS':
                message += ' 模型正在处理视频口型。'
            return DigitalHumanResult(
                status='running', engine=f'fal:{endpoint}', message=message,
                job_id=f'fal:{request_id}', warnings=[], raw={**status_data, '_used_status_url': used_status_url},
            )

        result_data, used_response_url, response_error = await _fal_try_get_json(client, response_candidates, headers)
    if result_data is None:
        return DigitalHumanResult(
            status='running', engine=f'fal:{endpoint}',
            message='fal.ai 显示已完成，但结果接口暂时不可读；请稍后再查询一次。',
            job_id=f'fal:{request_id}', warnings=[response_error], raw={**(status_data or {}), 'response_error': response_error},
        )
    video_url = _extract_fal_video_url(result_data)
    if not video_url:
        return DigitalHumanResult(
            status='failed', engine=f'fal:{endpoint}', message='fal.ai 已完成，但响应里没有找到 video.url。请展开 raw 检查返回结构。',
            job_id=f'fal:{request_id}', warnings=['未识别到 fal 输出视频 URL。'], raw={**result_data, '_used_response_url': used_response_url},
        )
    return DigitalHumanResult(
        status='done', engine=f'fal:{endpoint}', message='fal.ai 真人模板口型同步已生成。',
        video_url=video_url, job_id=f'fal:{request_id}', warnings=[], raw={**result_data, '_used_response_url': used_response_url},
    )


async def call_fal_lipsync(
    settings: Settings,
    *,
    video_url: str,
    audio_url: str,
    script: str = '',
    title: str = '',
    sync_mode: str = '',
) -> DigitalHumanResult:
    """Submit a fal.ai video-to-video lip-sync job.

    fal-ai/sync-lipsync expects a public `video_url` and `audio_url`.
    It is best used with a 5-20s real presenter template video plus generated TTS audio.
    """
    if not video_url or not video_url.startswith(('http://', 'https://')):
        raise RuntimeError('fal Lipsync 需要公网可访问的真人模板视频 URL。请确认素材已上传到 R2 或 Render 可公开访问。')
    if not audio_url or not audio_url.startswith(('http://', 'https://')):
        raise RuntimeError('fal Lipsync 需要公网可访问的配音音频 URL。请先生成配音，并确认音频可访问。')

    endpoint = _fal_endpoint(settings)
    headers = _fal_headers(settings)
    payload: dict[str, Any] = {
        'video_url': video_url,
        'audio_url': audio_url,
        'sync_mode': sync_mode or settings.fal_lipsync_sync_mode or 'cut_off',
    }
    # fal-ai/sync-lipsync supports model=lipsync-1.9.0-beta / 1.8.0 / 1.7.1.
    if endpoint == 'fal-ai/sync-lipsync' and (settings.fal_lipsync_model or '').strip():
        payload['model'] = settings.fal_lipsync_model.strip()
    if title or script:
        payload['metadata'] = {'title': title[:120], 'script_preview': script[:300]}

    submit_url = f'https://queue.fal.run/{endpoint}'
    async with httpx.AsyncClient(timeout=max(30, min(settings.digital_human_timeout_seconds, 120))) as client:
        res = await client.post(submit_url, headers=headers, json=payload)
        text = res.text
        if res.status_code >= 400:
            raise RuntimeError(f'fal.ai 提交失败 HTTP {res.status_code}: {text[:1200]}')
        try:
            data = res.json()
        except Exception:
            raise RuntimeError(f'fal.ai 提交接口没有返回 JSON：{text[:1200]}')
        if not isinstance(data, dict):
            data = {'data': data}
        data.setdefault('endpoint', endpoint)

        # Some fal endpoints may return the result directly; queue endpoints return request_id/status_url/response_url.
        direct_video_url = _extract_fal_video_url(data)
        if direct_video_url:
            return DigitalHumanResult(
                status='done', engine=f'fal:{endpoint}', message='fal.ai 真人模板口型同步已生成。',
                video_url=direct_video_url, job_id=str(data.get('request_id') or ''), warnings=[], raw={**data, 'endpoint': endpoint},
            )

        request_id = str(data.get('request_id') or '').strip()
        if not request_id:
            raise RuntimeError(f'fal.ai 提交成功，但未返回 request_id：{json.dumps(data, ensure_ascii=False)[:1000]}')

        deadline = time.time() + max(0, min(settings.fal_lipsync_initial_wait_seconds, settings.digital_human_timeout_seconds - 5))
        last_status: dict[str, Any] = data
        while time.time() < deadline:
            await asyncio.sleep(max(2, min(settings.fal_lipsync_poll_seconds, 15)))
            result = await query_fal_lipsync(settings, request_id=request_id)
            last_status = result.raw or {}
            if result.video_url or result.status in {'failed', 'error'}:
                return result

    return DigitalHumanResult(
        status='running', engine=f'fal:{endpoint}',
        message='fal.ai 任务已提交，仍在排队/生成中。请稍后点击“查询当前数字人任务”。',
        job_id=f'fal:{request_id}', warnings=['为避免 Render/浏览器长时间等待，已切换为异步查询。'], raw={**(last_status or {}), 'endpoint': endpoint},
    )


def _hash_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hmac_sha256(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode('utf-8'), hashlib.sha256).digest()


def _volc_auth_headers(settings: Settings, action: str, body: dict[str, Any]) -> tuple[str, dict[str, str], bytes]:
    """Volcengine OpenAPI V4 signing for service=cv.

    Endpoint path is '/', query contains Action and Version.
    """
    if not settings.jimeng_access_key_id or not settings.jimeng_secret_access_key:
        raise RuntimeError('未配置 JIMENG_ACCESS_KEY_ID / JIMENG_SECRET_ACCESS_KEY。')

    endpoint = settings.jimeng_endpoint.rstrip('/')
    parsed = urlparse(endpoint)
    host = parsed.netloc
    path = parsed.path or '/'
    if path != '/':
        path = path.rstrip('/') + '/'
    query = urlencode({'Action': action, 'Version': settings.jimeng_version})
    url = f'{endpoint}{path}?{query}'

    body_bytes = json.dumps(body, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    now = datetime.now(timezone.utc)
    x_date = now.strftime('%Y%m%dT%H%M%SZ')
    short_date = now.strftime('%Y%m%d')

    method = 'POST'
    canonical_uri = path
    canonical_query = query
    canonical_headers = f'content-type:application/json\nhost:{host}\nx-date:{x_date}\n'
    signed_headers = 'content-type;host;x-date'
    payload_hash = _hash_sha256(body_bytes)
    canonical_request = '\n'.join([method, canonical_uri, canonical_query, canonical_headers, signed_headers, payload_hash])
    credential_scope = f'{short_date}/{settings.jimeng_region}/{settings.jimeng_service}/request'
    string_to_sign = '\n'.join(['HMAC-SHA256', x_date, credential_scope, _hash_sha256(canonical_request.encode('utf-8'))])

    k_date = _hmac_sha256(settings.jimeng_secret_access_key.encode('utf-8'), short_date)
    k_region = hmac.new(k_date, settings.jimeng_region.encode('utf-8'), hashlib.sha256).digest()
    k_service = hmac.new(k_region, settings.jimeng_service.encode('utf-8'), hashlib.sha256).digest()
    k_signing = hmac.new(k_service, b'request', hashlib.sha256).digest()
    signature = hmac.new(k_signing, string_to_sign.encode('utf-8'), hashlib.sha256).hexdigest()

    authorization = (
        f'HMAC-SHA256 Credential={settings.jimeng_access_key_id}/{credential_scope}, '
        f'SignedHeaders={signed_headers}, Signature={signature}'
    )
    headers = {
        'Content-Type': 'application/json',
        'Host': host,
        'X-Date': x_date,
        'Authorization': authorization,
    }
    return url, headers, body_bytes


async def _volc_call(settings: Settings, action: str, body: dict[str, Any], *, raise_response_error: bool = True) -> dict[str, Any]:
    url, headers, body_bytes = _volc_auth_headers(settings, action, body)
    async with httpx.AsyncClient(timeout=settings.digital_human_timeout_seconds) as client:
        res = await client.post(url, headers=headers, content=body_bytes)
        text = res.text
        if res.status_code >= 400:
            # Query endpoints may return HTTP 400 with a valid JSON body such as
            # {ResponseMetadata:{Error:{Code:'50215', Message:'Input invalid for this service'}}}.
            # When raise_response_error=False, pass that JSON back to the caller so the UI can
            # mark the cached task_id as invalid and show the clear/re-submit action instead of
            # surfacing a generic HTTP 500.
            if not raise_response_error:
                try:
                    return res.json()
                except Exception:
                    return {
                        'ResponseMetadata': {
                            'Error': {
                                'Code': str(res.status_code),
                                'Message': text[:1200] or 'HTTP error from Jimeng API',
                            }
                        },
                        'http_status': res.status_code,
                    }
            if res.status_code == 429 or '50430' in text or 'Concurrent Limit' in text:
                raise RuntimeError('火山即梦并发限流：当前账号/模型正在生成中的任务还没结束，不能重复提交。请等待当前任务完成后再新建，或用已有 task_id 查询结果。原始返回：' + text[:900])
            raise RuntimeError(f'火山即梦接口失败 HTTP {res.status_code}: {text[:1200]}')
        try:
            data = res.json()
        except Exception:
            raise RuntimeError(f'火山即梦接口未返回 JSON：{text[:1200]}')
    if isinstance(data, dict) and data.get('ResponseMetadata', {}).get('Error'):
        err = data['ResponseMetadata']['Error']
        code = str(err.get('Code') or '')
        msg = str(err.get('Message') or '')
        if not raise_response_error:
            return data
        if code == '50430' or 'Concurrent Limit' in msg:
            raise RuntimeError('火山即梦并发限流：当前账号/模型正在生成中的任务还没结束，不能重复提交。请等待当前任务完成后再新建，或用已有 task_id 查询结果。')
        raise RuntimeError(f"火山即梦接口错误：{err.get('Code')} {err.get('Message')}")
    return data


def _get_path(data: dict[str, Any], path: tuple[str, ...]) -> Any:
    cur: Any = data
    for p in path:
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        else:
            return None
    return cur


def _walk_values(obj: Any):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k, v
            yield from _walk_values(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_values(v)


def _extract_task_id(data: dict[str, Any]) -> str:
    """Extract Jimeng task id from several real Volcengine response shapes.

    OmniHuman submit commonly returns:
    {"Result":{"code":10000,"data":{"task_id":"..."}}}
    """
    preferred_paths = [
        ('Result', 'data', 'task_id'), ('Result', 'data', 'TaskId'), ('Result', 'data', 'taskId'),
        ('Result', 'data', 'job_id'), ('Result', 'data', 'JobId'), ('Result', 'data', 'jobId'),
        ('Result', 'task_id'), ('Result', 'TaskId'), ('Result', 'taskId'),
        ('Result', 'JobId'), ('Result', 'job_id'), ('Result', 'jobId'),
        ('data', 'task_id'), ('data', 'TaskId'), ('data', 'taskId'),
        ('result', 'task_id'), ('result', 'TaskId'), ('result', 'taskId'),
        ('task_id',), ('TaskId',), ('taskId',), ('job_id',), ('JobId',), ('jobId',),
    ]
    for path in preferred_paths:
        val = _get_path(data, path)
        if val:
            return str(val)

    # Recursive fallback: avoid request_id/requestId, which is not a task id.
    task_keys = {'task_id', 'TaskId', 'taskId', 'job_id', 'JobId', 'jobId'}
    for k, v in _walk_values(data):
        if k in task_keys and v:
            return str(v)
    return ''


def _extract_video_url(data: dict[str, Any]) -> str:
    for path in [
        ('Result', 'data', 'video_url'), ('Result', 'data', 'VideoUrl'), ('Result', 'data', 'videoUrl'),
        ('Result', 'data', 'output_url'), ('Result', 'data', 'OutputUrl'), ('Result', 'data', 'result_url'),
        ('Result', 'data', 'url'), ('Result', 'data', 'Url'),
        ('Result', 'VideoUrl'), ('Result', 'video_url'), ('Result', 'OutputUrl'), ('Result', 'output_url'),
        ('Result', 'Url'), ('Result', 'url'),
        ('data', 'video_url'), ('data', 'output_url'), ('data', 'url'),
        ('result', 'video_url'), ('result', 'output_url'), ('result', 'url'),
    ]:
        cur = _get_path(data, path)
        if isinstance(cur, str) and cur.startswith(('http://', 'https://')):
            return cur
        if isinstance(cur, list):
            for item in cur:
                if isinstance(item, str) and item.startswith(('http://', 'https://')):
                    return item

    urls: list[str] = []
    for _k, v in _walk_values(data):
        if isinstance(v, str) and v.startswith(('http://', 'https://')):
            urls.append(v)
    for u in urls:
        low = u.lower()
        if any(x in low for x in ('.mp4', '.mov', '.m3u8', 'video', 'tos-', 'volc')):
            return u
    return urls[0] if urls else ''


def _extract_status(data: dict[str, Any]) -> str:
    for path in [
        ('Result', 'data', 'status'), ('Result', 'data', 'Status'), ('Result', 'data', 'state'), ('Result', 'data', 'State'),
        ('Result', 'status'), ('Result', 'Status'), ('Result', 'state'), ('Result', 'State'),
        ('data', 'status'), ('data', 'state'), ('result', 'status'), ('result', 'state'),
    ]:
        cur = _get_path(data, path)
        if cur is not None and cur != '':
            return str(cur).lower()
    for k, v in _walk_values(data):
        if k in {'status', 'Status', 'state', 'State'} and v is not None and v != '':
            return str(v).lower()
    return ''


def _extract_code(data: dict[str, Any]) -> str:
    for path in [
        ('Result', 'code'), ('Result', 'Code'), ('Result', 'status'), ('Result', 'Status'),
        ('Result', 'data', 'code'), ('Result', 'data', 'Code'),
        ('code',), ('Code',), ('status',), ('Status',),
    ]:
        cur = _get_path(data, path)
        if cur is not None and cur != '':
            return str(cur)
    return ''


def _extract_message(data: dict[str, Any]) -> str:
    for path in [
        ('Result', 'message'), ('Result', 'Message'), ('Result', 'msg'),
        ('Result', 'data', 'message'), ('Result', 'data', 'Message'), ('Result', 'data', 'msg'),
        ('message',), ('Message',), ('msg',),
    ]:
        cur = _get_path(data, path)
        if cur:
            return str(cur)
    err = data.get('ResponseMetadata', {}).get('Error') if isinstance(data, dict) else None
    if isinstance(err, dict):
        return str(err.get('Message') or err.get('Code') or '')
    return ''


def _compact_raw(data: dict[str, Any], limit: int = 900) -> str:
    try:
        text = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    except Exception:
        text = str(data)
    return text[:limit] + ('...' if len(text) > limit else '')


def _asset_to_url_or_base64(path: Optional[Path], url: str) -> dict[str, str]:
    """Prefer public URL. If not public, send base64. Different Jimeng APIs may require one or the other.

    The request includes both url/base64 to maximize compatibility; if your API docs require exact field names,
    override by editing this payload section only.
    """
    if url.startswith(('http://', 'https://')):
        return {'url': url}
    if path and path.exists():
        raw = path.read_bytes()
        return {'base64': base64.b64encode(raw).decode('utf-8')}
    raise RuntimeError('缺少可访问的素材 URL 或本地文件，无法提交数字人任务。')


def _jimeng_actions(settings: Settings, model: str) -> tuple[str, str, str]:
    """Return submit action, get action and req_key for the selected Jimeng model.

    Volcengine Jimeng APIs require req_key in both submit and query payloads.
    Missing req_key returns: Invalid Input Parameters: missing req_key.
    """
    model = (model or '').lower()
    if model in {'quick', 'quickmode', 'omnihuman10', 'omni10', 'jimeng_quick'}:
        return settings.jimeng_quick_submit_action, settings.jimeng_quick_get_action, settings.jimeng_quick_req_key
    if model in {'video30', 'video3', 'jimeng_video30'}:
        return settings.jimeng_video30_submit_action, settings.jimeng_video30_get_action, settings.jimeng_video30_req_key
    return settings.jimeng_omni15_submit_action, settings.jimeng_omni15_get_action, settings.jimeng_omni15_req_key


async def call_jimeng_digital_human(
    settings: Settings,
    *,
    avatar_path: Optional[Path],
    audio_path: Optional[Path],
    avatar_url: str,
    audio_url: str,
    script: str,
    title: str,
    model: str = 'omnihuman15',
    driver_video_url: str = '',
) -> DigitalHumanResult:
    """Call Volcengine Jimeng / OmniHuman digital-human API.

    This wrapper supports the common submit-task + poll-result pattern.
    It intentionally keeps payload generous because Jimeng action payload fields vary by model/version.
    If 火山 API Explorer shows exact field names for your enabled model, adjust the payload in one place below.
    """
    if not settings.jimeng_enabled:
        raise RuntimeError('未启用 JIMENG_ENABLED=true。')

    submit_action, get_action, req_key = _jimeng_actions(settings, model)
    image_payload = _asset_to_url_or_base64(avatar_path, avatar_url)
    audio_payload = _asset_to_url_or_base64(audio_path, audio_url)

    submit_body: dict[str, Any] = {
        # 火山即梦必填服务标识。OmniHuman1.5 固定为 jimeng_realman_avatar_picture_omni_v15。
        'req_key': req_key,
        'ReqKey': req_key,
        # OmniHuman / 数字人常见输入
        'image_url': image_payload.get('url', ''),
        'image_base64': image_payload.get('base64', ''),
        'audio_url': audio_payload.get('url', ''),
        'audio_base64': audio_payload.get('base64', ''),
        # Some actions use camel case.
        'ImageUrl': image_payload.get('url', ''),
        'ImageBase64': image_payload.get('base64', ''),
        'AudioUrl': audio_payload.get('url', ''),
        'AudioBase64': audio_payload.get('base64', ''),
        # Metadata / output preference.
        'prompt': script or title or '生成自然口播数字人视频',
        'Prompt': script or title or '生成自然口播数字人视频',
        'title': title,
        'Title': title,
        'ratio': '9:16',
        'Ratio': '9:16',
        'resolution': '720p',
        'Resolution': '720p',
    }
    if driver_video_url:
        submit_body.update({'driver_video_url': driver_video_url, 'DriverVideoUrl': driver_video_url})

    submit_data = await _volc_call(settings, submit_action, submit_body)
    task_id = _extract_task_id(submit_data)
    video_url = _extract_video_url(submit_data)
    if video_url:
        return DigitalHumanResult(
            status='done', engine=f'jimeng:{model}', message='火山即梦数字人视频已生成。',
            video_url=video_url, job_id=task_id, raw=submit_data, warnings=[]
        )
    if not task_id:
        return DigitalHumanResult(
            status='submitted', engine=f'jimeng:{model}', message='火山即梦任务已提交，但响应里没有识别到 task_id。请到火山控制台/API Explorer 对照字段名。',
            job_id='', raw=submit_data, warnings=['未识别到 task_id，可能需要按你开通模型的接口文档调整 payload 字段。']
        )

    # Render 免费实例 / Cloudflare 前端不适合在一个 HTTP 请求里等 OmniHuman 跑完。
    # 默认只提交任务并返回 task_id，前端点击“查询结果”再走 /api/digital-human/status/{task_id}。
    if not getattr(settings, 'jimeng_wait_for_result', False):
        return DigitalHumanResult(
            status='running',
            engine=f'jimeng:{model}',
            message='火山即梦任务已提交，正在生成中。请稍等 1-5 分钟后点击“查询数字人结果”。',
            job_id=task_id,
            raw=submit_data,
            warnings=['已改为异步提交模式，避免 Render 免费实例请求超时。']
        )

    deadline = time.time() + max(30, min(settings.jimeng_max_wait_seconds, settings.digital_human_timeout_seconds - 5))
    last_data: dict[str, Any] = submit_data
    while time.time() < deadline:
        await _sleep_async(max(2, settings.jimeng_poll_seconds))
        result = await query_jimeng_digital_human(settings, task_id=task_id, model=model)
        last_data = result.raw or last_data
        if result.video_url or result.status in {'done', 'failed'}:
            return result

    return DigitalHumanResult(
        status='running', engine=f'jimeng:{model}', message='火山即梦任务已提交，仍在生成中。稍后点击“查询数字人结果”。',
        job_id=task_id, raw=last_data, warnings=['生成时间超过本次等待上限，任务可能仍在火山侧排队处理。']
    )


async def query_jimeng_digital_human(settings: Settings, *, task_id: str, model: str = 'omnihuman15') -> DigitalHumanResult:
    """Query Volcengine Jimeng task result by task_id without submitting a new job.

    Keep the body strict. Volcengine docs for OmniHuman1.5 GetResult use only:
    {"req_key":"jimeng_realman_avatar_picture_omni_v15", "task_id":"<task_id>"}
    Extra TaskId/JobId fields may be ignored by some Jimeng actions, so this version avoids them.
    """
    if not task_id:
        raise RuntimeError('缺少 task_id，无法查询数字人任务。')
    _submit_action, get_action, req_key = _jimeng_actions(settings, model)
    query_body = {'req_key': req_key, 'task_id': task_id}
    data = await _volc_call(settings, get_action, query_body, raise_response_error=False)

    # 火山有时会对错误 task_id / 错误模型返回 200 + ResponseMetadata.Error，
    # 旧代码会把它作为 500 抛给前端，导致用户不知道是任务 ID 不匹配还是仍在生成。
    # 这里改成结构化结果，并保留 raw，方便在页面上直接看到火山原始返回。
    err = data.get('ResponseMetadata', {}).get('Error') if isinstance(data, dict) else None
    if isinstance(err, dict):
        err_code = str(err.get('Code') or '')
        err_msg = str(err.get('Message') or '')
        raw_hint = _compact_raw(data, 900)
        if err_code == '50215' or 'Input invalid for this service' in err_msg:
            return DigitalHumanResult(
                status='failed',
                engine=f'jimeng:{model}',
                message='这个 task_id 不是当前 OmniHuman1.5 服务的有效任务，通常是浏览器缓存了旧任务、任务模型不匹配，或上次提交没有真正生成有效 task_id。请清除当前任务后重新提交。',
                job_id=task_id,
                raw=data,
                warnings=[
                    '火山返回 50215：Input invalid for this service。',
                    '处理办法：点击“清除当前任务”，确认模型选择 OmniHuman1.5，再重新生成数字人片段。',
                    f'原始响应片段：{raw_hint}',
                ],
            )
        if err_code == '50430' or 'Concurrent Limit' in err_msg:
            return DigitalHumanResult(
                status='running',
                engine=f'jimeng:{model}',
                message='火山即梦当前并发已满，说明已有任务正在生成或排队。不要重复提交，稍后继续查询。',
                job_id=task_id,
                raw=data,
                warnings=['火山返回 50430：并发限制。一般等当前任务结束后会恢复。'],
            )
        return DigitalHumanResult(
            status='failed',
            engine=f'jimeng:{model}',
            message=f'火山即梦查询失败：{err_code} {err_msg}',
            job_id=task_id,
            raw=data,
            warnings=[f'原始响应片段：{raw_hint}'],
        )

    video_url = _extract_video_url(data)
    status = _extract_status(data)
    code = _extract_code(data)
    message = _extract_message(data)
    raw_hint = _compact_raw(data, 700)

    if video_url:
        return DigitalHumanResult(
            status='done', engine=f'jimeng:{model}', message='火山即梦数字人视频已生成。',
            video_url=video_url, job_id=task_id, raw=data, warnings=[]
        )

    failed_codes = {'50200', '50400', '50500', '50000', '-1'}
    failed_words = {'failed', 'fail', 'error', 'canceled', 'cancelled', 'timeout', 'rejected'}
    if code in failed_codes or status in failed_words or any(w in (message or '').lower() for w in ['fail', 'error', 'denied', 'invalid']):
        return DigitalHumanResult(
            status='failed',
            engine=f'jimeng:{model}',
            message=f'火山即梦任务失败：{message or status or code or "unknown"}',
            job_id=task_id,
            raw=data,
            warnings=[f'火山返回：code={code or "-"} status={status or "-"} message={message or "-"}', f'原始响应片段：{raw_hint}'],
        )

    # Some Jimeng result APIs return code/status=10000 while the video is still queued, and only add video_url when ready.
    if code == '10000' or status in {'10000', 'running', 'pending', 'queueing', 'queued', 'processing', 'created', 'submitted', '0', '1'} or not status:
        return DigitalHumanResult(
            status='running',
            engine=f'jimeng:{model}',
            message=(
                '火山即梦任务仍在生成或排队中。OmniHuman1.5 不是实时接口，1 并发/排队时可能需要 10-30 分钟；'
                '页面会自动轮询，生成完成后会出现视频 URL。'
            ),
            job_id=task_id,
            raw=data,
            warnings=[f'火山查询返回：code={code or "-"} status={status or "-"} message={message or "-"}'],
        )

    return DigitalHumanResult(
        status=status or 'running',
        engine=f'jimeng:{model}',
        message=f'火山即梦任务未返回视频 URL：status={status or "-"} code={code or "-"} message={message or "-"}',
        job_id=task_id,
        raw=data,
        warnings=[f'原始响应片段：{raw_hint}'],
    )

async def _sleep_async(seconds: int) -> None:
    import asyncio
    await asyncio.sleep(seconds)
