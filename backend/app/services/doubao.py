from __future__ import annotations

import base64
import json
import re
import subprocess
from pathlib import Path
from typing import Optional

import httpx

from app.config import Settings
from app.schemas import InspirationExtractResponse


VIDEO_EXTS = {'.mp4', '.mov', '.m4v', '.webm'}


def _guess_mime(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == '.mov':
        return 'video/quicktime'
    if ext == '.webm':
        return 'video/webm'
    return 'video/mp4'


def _to_data_url(path: Path, max_mb: int = 25) -> str:
    size_mb = path.stat().st_size / 1024 / 1024
    if size_mb > max_mb:
        raise RuntimeError(f'参考视频 {size_mb:.1f}MB，超过 {max_mb}MB。请先截取 30-60 秒精华片段或使用视频 URL。')
    raw = base64.b64encode(path.read_bytes()).decode('ascii')
    return f'data:{_guess_mime(path)};base64,{raw}'


def _json_from_text(text: str) -> dict:
    text = text.strip()
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?', '', text, flags=re.I).strip()
        text = re.sub(r'```$', '', text).strip()
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r'\{.*\}', text, flags=re.S)
        if not m:
            raise
        return json.loads(m.group(0))


def _local_probe(path: Path) -> list[str]:
    tips: list[str] = []
    try:
        proc = subprocess.run([
            'ffprobe', '-v', 'error', '-select_streams', 'a', '-show_entries', 'stream=codec_type', '-of', 'csv=p=0', str(path)
        ], capture_output=True, text=True, timeout=30)
        tips.append('检测到音轨，可用豆包视频理解提取口播/字幕。' if 'audio' in proc.stdout else '未检测到音轨，需要依赖视频画面理解。')
    except Exception:
        tips.append('本地未能检测音轨，不影响上传到豆包视频理解。')
    return tips


async def extract_with_doubao(settings: Settings, video_path: Optional[Path], source_url: str = '', manual_text: str = '') -> InspirationExtractResponse:
    warnings: list[str] = []

    if manual_text.strip():
        return InspirationExtractResponse(
            status='manual_text',
            source_name=source_url or (video_path.name if video_path else '手动粘贴'),
            transcript=manual_text.strip(),
            summary='已使用手动粘贴内容作为参考文案。',
            structure=['开头钩子', '痛点放大', '解决方案', '信任背书', '行动引导'],
            warnings=['手动粘贴模式：可立即用于 DeepSeek 原创改写。'],
        )

    api_key = settings.ark_api_key.strip()
    model = settings.ark_video_model.strip()
    if not api_key or not model:
        if video_path:
            warnings.extend(_local_probe(video_path))
        warnings.append('未配置 ARK_API_KEY / ARK_VIDEO_MODEL：无法自动调用豆包视频理解。')
        return InspirationExtractResponse(
            status='need_config',
            source_name=source_url or (video_path.name if video_path else ''),
            summary='未配置豆包视频理解接口。',
            structure=['配置 ARK_API_KEY', '配置 ARK_VIDEO_MODEL=Doubao-Seed-2.0-lite 接入点/模型 ID', '上传参考视频或填写 URL', '提取竞品结构', '再原创改写'],
            warnings=warnings,
        )

    prompt = '''
你是短视频拆解助手。请分析这个视频，提取：
1. 口播文案/字幕文案；
2. 前 3 秒钩子；
3. 痛点、卖点、信任背书、CTA；
4. 镜头结构和剪辑节奏。
只输出 JSON，字段：transcript, summary, structure, hooks, selling_points。不要 Markdown。
'''.strip()

    content: list[dict] = [{'type': 'text', 'text': prompt}]
    if source_url.strip():
        content.append({'type': 'video_url', 'video_url': {'url': source_url.strip()}})
    elif video_path:
        content.append({'type': 'video_url', 'video_url': {'url': _to_data_url(video_path)}})
    else:
        return InspirationExtractResponse(status='missing_source', warnings=['请上传参考视频、填写视频 URL，或手动粘贴文案。'])

    url = settings.ark_base_url.rstrip('/') + '/chat/completions'
    headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}
    body = {'model': model, 'messages': [{'role': 'user', 'content': content}], 'temperature': 0.2, 'stream': False}

    async with httpx.AsyncClient(timeout=180) as client:
        try:
            resp = await client.post(url, headers=headers, json=body)
        except httpx.HTTPError as exc:
            raise RuntimeError(f'豆包/火山方舟视频理解请求失败：{exc}') from exc

    if resp.status_code >= 400:
        raise RuntimeError(f'豆包/火山方舟返回错误 {resp.status_code}：{resp.text[:1000]}')

    data = resp.json()
    content_text = data.get('choices', [{}])[0].get('message', {}).get('content', '')
    payload = _json_from_text(content_text)
    return InspirationExtractResponse(
        status='ok',
        source_name=source_url or (video_path.name if video_path else ''),
        transcript=str(payload.get('transcript', '')).strip(),
        summary=str(payload.get('summary', '')).strip(),
        structure=[str(x) for x in payload.get('structure', [])][:20],
        hooks=[str(x) for x in payload.get('hooks', [])][:12],
        selling_points=[str(x) for x in payload.get('selling_points', [])][:12],
        warnings=warnings,
    )
