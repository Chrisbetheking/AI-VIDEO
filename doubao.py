from __future__ import annotations

import base64
import json
import re
import subprocess
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx

from app.config import Settings
from app.schemas import InspirationExtractResponse


VIDEO_EXTS = {'.mp4', '.mov', '.m4v', '.webm'}
URL_RE = re.compile(r'https?://[^\s，。！？!！；;]+', re.I)
DOUYIN_BOILERPLATE_RE = re.compile(
    r'(复制此链接.*?$|打开抖音搜索.*?$|打开Dou音搜索.*?$|直接观看视频.*?$|https?://[^\s，。！？!！；;]+)',
    re.I | re.S,
)


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


def _is_valid_http_url(value: str) -> bool:
    try:
        parsed = urlparse(value.strip())
        return parsed.scheme in {'http', 'https'} and bool(parsed.netloc)
    except Exception:
        return False


def _clean_share_caption(raw: str) -> str:
    text = (raw or '').strip()
    if not text:
        return ''
    text = DOUYIN_BOILERPLATE_RE.sub('', text).strip()
    text = re.sub(r'\s+', ' ', text).strip(' ，。!！;；')
    # 去掉抖音口令前缀，如“1.58 z@t.RX aNJ:/ :8pm 03/28”
    text = re.sub(r'^\s*\d+(?:\.\d+)?\s+[A-Za-z0-9@._:/\-\s]{4,80}?\s+', '', text).strip()
    return text


def parse_competitor_input(source_url: str = '', manual_text: str = '') -> tuple[str, str, list[str]]:
    """Parse copied Douyin share text.

    Returns: (clean_url, reference_text, warnings)
    - clean_url: actual first URL inside the share text, if any.
    - reference_text: caption/copy extracted from pasted share text or manual_text.
    """
    warnings: list[str] = []
    raw_source = (source_url or '').strip()
    raw_manual = (manual_text or '').strip()

    urls = URL_RE.findall(raw_source)
    clean_url = urls[0].rstrip('，。!！;；') if urls else ''

    if raw_manual:
        reference_text = raw_manual
    else:
        reference_text = _clean_share_caption(raw_source)

    if raw_source and not clean_url and not raw_manual:
        # 用户把纯文案误填到 URL 框，也允许当竞品文案使用。
        reference_text = raw_source
        warnings.append('检测到“视频 URL”框里不是链接，已自动当作竞品文案处理。')

    if clean_url and raw_source != clean_url:
        warnings.append('已从抖音/分享口令中自动提取真实链接，并把链接前的文字作为竞品文案参考。')

    if clean_url and ('douyin.com' in clean_url or 'iesdouyin.com' in clean_url):
        warnings.append('抖音短链通常不是直连视频文件。若要分析画面/剪辑节奏，建议上传下载后的 MP4；当前会优先使用分享文案拆解钩子。')

    return clean_url, reference_text.strip(), warnings


def _manual_response(reference_text: str, source_name: str, warnings: list[str]) -> InspirationExtractResponse:
    hashtag_list = re.findall(r'#\s*([^#\s，。！？!！；;]+)', reference_text)
    first_sentence = re.split(r'[。！？!\n]', reference_text.strip())[0].strip()[:120]
    structure = ['开头钩子', '制造焦虑/痛点', '点出机会或代价', '给出观点/方案', '行动引导']
    if hashtag_list:
        structure.append('话题标签：' + '、'.join(hashtag_list[:8]))
    return InspirationExtractResponse(
        status='share_text',
        source_name=source_name or '抖音分享口令/竞品文案',
        transcript=reference_text,
        summary=first_sentence or '已使用分享口令/竞品文案作为参考。',
        structure=structure,
        hooks=[first_sentence] if first_sentence else [],
        selling_points=hashtag_list[:12],
        warnings=warnings + ['已进入同行采集模式：只学习钩子、结构和表达方式，不直接照搬原文。'],
    )


async def extract_with_doubao(settings: Settings, video_path: Optional[Path], source_url: str = '', manual_text: str = '') -> InspirationExtractResponse:
    parsed_url, reference_text, warnings = parse_competitor_input(source_url, manual_text)

    if reference_text and not video_path:
        # 抖音复制口令/同行文案：先当作竞品采集文本使用。
        # 这样不会把一整段口令错误传给 video_url，也不会被 Ark 判定为 invalid URL。
        return _manual_response(reference_text, parsed_url or source_url, warnings)

    api_key = settings.ark_api_key.strip()
    model = settings.ark_video_model.strip()
    if not api_key or not model:
        if video_path:
            warnings.extend(_local_probe(video_path))
        warnings.append('未配置 ARK_API_KEY / ARK_VIDEO_MODEL：无法自动调用豆包视频理解。')
        if reference_text:
            return _manual_response(reference_text, parsed_url or source_url or (video_path.name if video_path else ''), warnings)
        return InspirationExtractResponse(
            status='need_config',
            source_name=parsed_url or source_url or (video_path.name if video_path else ''),
            summary='未配置豆包视频理解接口。',
            structure=['配置 ARK_API_KEY', '配置 ARK_VIDEO_MODEL=Doubao-Seed-2.0-lite 接入点/模型 ID', '上传参考视频或填写 URL', '提取竞品结构', '再原创改写'],
            warnings=warnings,
        )

    prompt = f"""
你是短视频同行拆解助手。请分析参考视频/参考文案，提取：
1. 口播文案/字幕文案；
2. 前 3 秒钩子；
3. 痛点、卖点、信任背书、CTA；
4. 镜头结构和剪辑节奏；
5. 可以借鉴的表达结构，但不要照抄原文。

用户额外提供的分享文案/标题/话题：
{reference_text or '无'}

只输出 JSON，字段：transcript, summary, structure, hooks, selling_points。不要 Markdown。
""".strip()

    content: list[dict] = [{'type': 'text', 'text': prompt}]
    if video_path:
        content.append({'type': 'video_url', 'video_url': {'url': _to_data_url(video_path)}})
    elif parsed_url and _is_valid_http_url(parsed_url):
        content.append({'type': 'video_url', 'video_url': {'url': parsed_url}})
    elif reference_text:
        return _manual_response(reference_text, parsed_url or source_url, warnings)
    else:
        return InspirationExtractResponse(status='missing_source', warnings=['请上传参考视频、粘贴抖音分享口令，或手动粘贴竞品文案。'])

    url = settings.ark_base_url.rstrip('/') + '/chat/completions'
    headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}
    body = {'model': model, 'messages': [{'role': 'user', 'content': content}], 'temperature': 0.2, 'stream': False}

    async with httpx.AsyncClient(timeout=180) as client:
        try:
            resp = await client.post(url, headers=headers, json=body)
        except httpx.HTTPError as exc:
            raise RuntimeError(f'豆包/火山方舟视频理解请求失败：{exc}') from exc

    if resp.status_code >= 400:
        # 如果 URL 被豆包拒绝，但分享文案已经提取出来，就自动降级到同行采集文案模式。
        if reference_text:
            warnings.append(f'豆包视频理解暂时无法读取该视频链接，已改用分享文案拆解。原始错误：{resp.text[:300]}')
            return _manual_response(reference_text, parsed_url or source_url, warnings)
        raise RuntimeError(f'豆包/火山方舟返回错误 {resp.status_code}：{resp.text[:1000]}')

    data = resp.json()
    content_text = data.get('choices', [{}])[0].get('message', {}).get('content', '')
    payload = _json_from_text(content_text)
    return InspirationExtractResponse(
        status='ok',
        source_name=parsed_url or source_url or (video_path.name if video_path else ''),
        transcript=str(payload.get('transcript', '')).strip() or reference_text,
        summary=str(payload.get('summary', '')).strip(),
        structure=[str(x) for x in payload.get('structure', [])][:20],
        hooks=[str(x) for x in payload.get('hooks', [])][:12],
        selling_points=[str(x) for x in payload.get('selling_points', [])][:12],
        warnings=warnings,
    )
