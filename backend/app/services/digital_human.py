from __future__ import annotations

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


async def _volc_call(settings: Settings, action: str, body: dict[str, Any]) -> dict[str, Any]:
    url, headers, body_bytes = _volc_auth_headers(settings, action, body)
    async with httpx.AsyncClient(timeout=settings.digital_human_timeout_seconds) as client:
        res = await client.post(url, headers=headers, content=body_bytes)
        text = res.text
        if res.status_code >= 400:
            raise RuntimeError(f'火山即梦接口失败 HTTP {res.status_code}: {text[:1200]}')
        try:
            data = res.json()
        except Exception:
            raise RuntimeError(f'火山即梦接口未返回 JSON：{text[:1200]}')
    if isinstance(data, dict) and data.get('ResponseMetadata', {}).get('Error'):
        err = data['ResponseMetadata']['Error']
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
        if cur:
            return str(cur).lower()
    for k, v in _walk_values(data):
        if k in {'status', 'Status', 'state', 'State'} and v:
            return str(v).lower()
    return ''


def _asset_to_url_or_base64(path: Path, url: str) -> dict[str, str]:
    """Prefer public URL. If not public, send base64. Different Jimeng APIs may require one or the other.

    The request includes both url/base64 to maximize compatibility; if your API docs require exact field names,
    override by editing this payload section only.
    """
    if url.startswith(('http://', 'https://')):
        return {'url': url}
    raw = path.read_bytes()
    return {'base64': base64.b64encode(raw).decode('utf-8')}


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
    avatar_path: Path,
    audio_path: Path,
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

    deadline = time.time() + max(30, settings.jimeng_max_wait_seconds)
    last_data: dict[str, Any] = submit_data
    while time.time() < deadline:
        await _sleep_async(max(2, settings.jimeng_poll_seconds))
        query_body = {'req_key': req_key, 'ReqKey': req_key, 'TaskId': task_id, 'task_id': task_id, 'JobId': task_id, 'id': task_id}
        last_data = await _volc_call(settings, get_action, query_body)
        video_url = _extract_video_url(last_data)
        status = _extract_status(last_data)
        if video_url:
            return DigitalHumanResult(
                status='done', engine=f'jimeng:{model}', message='火山即梦数字人视频已生成。',
                video_url=video_url, job_id=task_id, raw=last_data, warnings=[]
            )
        if status in {'failed', 'fail', 'error', 'canceled', 'cancelled'}:
            return DigitalHumanResult(
                status='failed', engine=f'jimeng:{model}', message=f'火山即梦任务失败：{status}',
                job_id=task_id, raw=last_data, warnings=['请在火山控制台查看该任务失败原因。']
            )

    return DigitalHumanResult(
        status='running', engine=f'jimeng:{model}', message='火山即梦任务已提交，仍在生成中。稍后在火山控制台或后续查询接口查看结果。',
        job_id=task_id, raw=last_data, warnings=['生成时间超过本次等待上限，任务可能仍在火山侧排队处理。']
    )


async def _sleep_async(seconds: int) -> None:
    import asyncio
    await asyncio.sleep(seconds)
