from __future__ import annotations

import base64
import uuid
from pathlib import Path
from typing import Any

import httpx

from app.config import Settings


class ImageGenerationError(RuntimeError):
    pass


def _provider(settings: Settings) -> str:
    return (settings.image_provider or '').strip().lower().replace('_', '-').replace(' ', '-') or 'volcengine'


def _api_key(settings: Settings) -> str:
    provider = _provider(settings)
    if provider in {'volcengine', 'ark', 'doubao', 'seedream', 'jimeng'}:
        return (getattr(settings, 'volcengine_image_api_key', '') or settings.ark_api_key or '').strip()
    if provider in {'dashscope', 'qwen', 'aliyun', 'bailian'}:
        return settings.dashscope_api_key.strip()
    return ''


def _base_url(settings: Settings) -> str:
    return (getattr(settings, 'image_base_url', '') or settings.ark_base_url or 'https://ark.cn-beijing.volces.com/api/v3').rstrip('/')


def _extract_image_url(data: dict[str, Any]) -> str:
    for path in [('data', 0, 'url'), ('data', 0, 'image_url'), ('images', 0, 'url'), ('result', 'url'), ('Result', 'url')]:
        cur: Any = data
        ok = True
        for key in path:
            try:
                cur = cur[key] if isinstance(key, int) else cur.get(key)
            except Exception:
                ok = False
                break
            if cur is None:
                ok = False
                break
        if ok and isinstance(cur, str) and cur.startswith(('http://', 'https://')):
            return cur
    return ''


def _extract_b64(data: dict[str, Any]) -> str:
    for path in [('data', 0, 'b64_json'), ('data', 0, 'image_base64'), ('images', 0, 'b64_json')]:
        cur: Any = data
        ok = True
        for key in path:
            try:
                cur = cur[key] if isinstance(key, int) else cur.get(key)
            except Exception:
                ok = False
                break
            if cur is None:
                ok = False
                break
        if ok and isinstance(cur, str) and len(cur) > 100:
            return cur
    return ''


async def generate_image_to_file(settings: Settings, prompt: str, *, size: str = '', quality: str = '') -> tuple[Path, str, list[str]]:
    provider = _provider(settings)
    key = _api_key(settings)
    if not key:
        raise ImageGenerationError('缺少图片模型 API Key。火山请填 ARK_API_KEY 或 VOLCENGINE_IMAGE_API_KEY。')

    model = settings.image_model.strip() or 'doubao-seedream-5-0-260128'
    out = settings.outputs_dir / f'ai_image_{uuid.uuid4().hex}.png'
    warnings: list[str] = []

    if provider in {'volcengine', 'ark', 'doubao', 'seedream', 'jimeng'}:
        url = f'{_base_url(settings)}/images/generations'
        body = {
            'model': model,
            'prompt': prompt,
            'response_format': 'url',
            'size': size or getattr(settings, 'image_size', '') or '2K',
            'stream': False,
            'watermark': False,
        }
        headers = {'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'}
        async with httpx.AsyncClient(timeout=180, follow_redirects=True) as client:
            resp = await client.post(url, headers=headers, json=body)
            if resp.status_code >= 400:
                raise ImageGenerationError(f'火山图片生成失败 HTTP {resp.status_code}: {resp.text[:1000]}')
            data = resp.json()
            image_url = _extract_image_url(data)
            b64 = _extract_b64(data)
            if image_url:
                img_resp = await client.get(image_url)
                if img_resp.status_code >= 400 or not img_resp.content:
                    raise ImageGenerationError(f'图片结果下载失败 HTTP {img_resp.status_code}')
                out.write_bytes(img_resp.content)
                return out, image_url, warnings
            if b64:
                out.write_bytes(base64.b64decode(b64))
                return out, '', warnings
            raise ImageGenerationError(f'火山图片接口未返回可识别图片地址：{str(data)[:1000]}')

    # Placeholder for DashScope/Qwen-Image. Avoid silently failing with wrong endpoint.
    raise ImageGenerationError(f'当前代码优先支持火山 Seedream。请设置 IMAGE_PROVIDER=volcengine。当前：{provider}')
