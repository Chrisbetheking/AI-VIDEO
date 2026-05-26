from __future__ import annotations

import base64
import uuid
from pathlib import Path
from typing import Any

import httpx

from app.config import Settings




_FORBIDDEN_PROMPT_PHRASES = [
    '不要文字', '不要有文字', '不要加文字', '无文字', '没有文字', '不带文字', '去掉文字', '不要中文', '不要英文',
    'no text', 'without text', 'do not include text', 'no words', 'no letters', 'no typography'
]


def _clean_user_prompt(prompt: str) -> str:
    """Seedream sometimes treats negative text instructions as visible content.

    Keep user visual intent, but remove explicit "no text" phrases from the main prompt
    and put them into negative_prompt instead.
    """
    text = (prompt or '').strip()
    for phrase in _FORBIDDEN_PROMPT_PHRASES:
        text = text.replace(phrase, '')
        text = text.replace(phrase.upper(), '')
        text = text.replace(phrase.title(), '')
    text = '，'.join([part.strip(' ，,;；') for part in text.replace('\n', '，').split('，') if part.strip(' ，,;；')])
    return text[:1800] or '精美商业场景背景，真实光影，高级质感，适合短视频和图文引流'


def _visual_only_prompt(prompt: str) -> str:
    clean = _clean_user_prompt(prompt)
    return (
        f"{clean}\n"
        "生成纯视觉素材：真实场景、人物/物体、光影、构图、氛围和留白区域。"
        "标题、卖点、字幕、编号、品牌字样全部由后期系统叠加；画面本身保持干净。"
    )


def _negative_prompt() -> str:
    return (
        "汉字, 中文, 英文, 数字, 字母, words, letters, typography, captions, subtitles, "
        "watermark, logo, signboard, poster text, UI text, button text, label text, QR code, messy hands, distorted face"
    )

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
            'prompt': _visual_only_prompt(prompt),
            'negative_prompt': _negative_prompt(),
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
