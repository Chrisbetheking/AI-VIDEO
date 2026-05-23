from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.config import Settings
from app.services.deepseek import DeepSeekError, _chat_json
from app.services.doubao import extract_with_doubao, parse_competitor_input
from app.services.collector import collector_cookie_path
from app.services.memory import MemoryStore

URL_RE = re.compile(r'https?://[^\s，。！？!！；;]+', re.I)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _split_seed_links(raw: str) -> List[str]:
    items: List[str] = []
    for part in re.split(r'[\n,，\s]+', raw or ''):
        part = part.strip().rstrip('，。!！;；')
        if part.startswith('http') and part not in items:
            items.append(part)
    return items[:30]


def _clean_list(values: Any, limit: int = 20) -> List[str]:
    if isinstance(values, str):
        values = re.split(r'[,，#\n]', values)
    if not isinstance(values, list):
        return []
    out: List[str] = []
    for value in values:
        text = str(value or '').strip(' #，,\n\t')
        if text and text not in out:
            out.append(text)
        if len(out) >= limit:
            break
    return out


def _entry_url(entry: dict) -> str:
    for key in ('webpage_url', 'original_url', 'url'):
        value = str(entry.get(key) or '').strip()
        if value.startswith('http'):
            return value
    # yt-dlp flat playlist sometimes returns an id only. Leave empty rather than inventing URL.
    return ''


def discover_recent_video_urls(settings: Settings, source_url: str, limit: int = 3) -> tuple[List[str], List[str]]:
    """Best-effort account/profile discovery using yt-dlp flat extraction.

    This is intentionally conservative: it only uses URLs the platform/yt-dlp exposes.
    If Douyin asks for fresh cookies, the warning is returned and the caller can keep
    learning from saved share captions instead of breaking the workflow.
    """
    warnings: List[str] = []
    source_url = (source_url or '').strip()
    if not source_url.startswith('http'):
        return [], ['账号链接为空或不是 URL，跳过自动发现。']
    if not settings.enable_ytdlp_collector:
        return [], ['未启用 ENABLE_YTDLP_COLLECTOR，跳过账号自动发现。']

    try:
        import yt_dlp  # type: ignore
    except Exception as exc:
        return [], [f'yt-dlp 未安装或不可用：{exc}']

    cookie_path = collector_cookie_path(settings)
    cookiefile = str(cookie_path) if cookie_path.exists() and cookie_path.stat().st_size > 20 else ''
    opts: dict[str, Any] = {
        'extract_flat': True,
        'skip_download': True,
        'playlistend': max(1, min(limit, 10)),
        'quiet': True,
        'no_warnings': True,
        'socket_timeout': min(max(settings.collector_timeout_seconds, 30), 240),
        'retries': 1,
        'ignoreerrors': True,
        'http_headers': {
            'User-Agent': settings.collector_user_agent,
            'Referer': 'https://www.douyin.com/',
        },
    }
    if cookiefile:
        opts['cookiefile'] = cookiefile

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(source_url, download=False)
    except Exception as exc:
        return [], [f'账号自动发现失败：{str(exc)[:300]}']

    if not info:
        return [], ['账号自动发现没有返回内容，可能需要 Cookies 或平台限制。']

    urls: List[str] = []
    entries = info.get('entries') if isinstance(info, dict) else None
    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            url = _entry_url(entry)
            if url and url not in urls:
                urls.append(url)
            if len(urls) >= limit:
                break
    elif isinstance(info, dict):
        url = _entry_url(info)
        if url:
            urls.append(url)

    if not urls:
        warnings.append('未能从账号页发现可采集视频。可以粘贴具体视频口令，或配置最新 douyin_cookies.txt。')
    return urls[:limit], warnings


async def analyze_creator_method(settings: Settings, *, industry: str, audience: str, videos: List[Dict[str, Any]], learn_goal: str) -> Dict[str, Any]:
    sample_lines: List[str] = []
    for idx, item in enumerate(videos[:12], start=1):
        hooks = item.get('hooks') or []
        structure = item.get('structure') or []
        text = item.get('transcript') or item.get('manual_text') or item.get('summary') or ''
        sample_lines.append(
            f"样本{idx}\n"
            f"来源：{item.get('source_name','')}\n"
            f"摘要：{item.get('summary','')}\n"
            f"钩子：{'；'.join(hooks) if isinstance(hooks, list) else hooks}\n"
            f"结构：{'；'.join(structure) if isinstance(structure, list) else structure}\n"
            f"原文片段：{str(text)[:900]}"
        )

    if not sample_lines:
        return {
            'summary': '暂时没有足够样本，先采集 3-5 条同行视频或口令。',
            'creator_methods': [],
            'hook_formulas': [],
            'transfer_rules': [],
            'next_collect_targets': [],
            'warnings': ['样本不足，未调用 AI 深度学习。'],
        }

    system = '你是短视频增长策略分析师，只学习结构和方法，禁止复刻原文。'
    user = f"""
目标行业：{industry or '未填写'}
目标客户：{audience or '未填写'}
学习目标：{learn_goal or '学习同行爆款的钩子结构、情绪推进、节奏和转化逻辑，但不要模仿具体文案。'}

请分析这些同行样本，输出可迁移到本行业的“做视频办法”，不是照抄文案。
重点提炼：
1. 开头钩子公式，例如损失厌恶、反常识、直接点名、结果承诺、身份代入；
2. 情绪推进方式，例如先焦虑、再解释、再给方案、最后行动；
3. 画面和剪辑节奏建议；
4. 如何迁移到当前行业，给出可用模板；
5. 后台下一步应该继续采集什么类型的视频。

同行样本：
{chr(10).join(sample_lines)}

只输出 JSON：
{{
  "summary": "一句话总结这个博主/同行的打法",
  "creator_methods": ["方法1", "方法2"],
  "hook_formulas": [{{"name":"公式名", "logic":"为什么有效", "template":"可迁移模板，不含原文照抄", "example":"换成当前行业后的示例"}}],
  "emotional_curve": ["情绪步骤"],
  "visual_editing_rules": ["画面/剪辑规则"],
  "transfer_rules": ["迁移到当前行业的规则"],
  "forbidden_copying_rules": ["避免侵权/同质化规则"],
  "next_collect_targets": ["下一步采集目标"],
  "score": 0
}}
""".strip()
    try:
        payload = await _chat_json(settings, system, user, temperature=0.35, timeout=120)
    except DeepSeekError as exc:
        return {
            'summary': 'AI 学习分析失败，已保留采集样本。',
            'creator_methods': [],
            'hook_formulas': [],
            'transfer_rules': [],
            'next_collect_targets': [],
            'warnings': [str(exc)],
        }

    payload.setdefault('summary', '已完成同行打法学习。')
    payload['creator_methods'] = _clean_list(payload.get('creator_methods'), 20)
    payload['emotional_curve'] = _clean_list(payload.get('emotional_curve'), 12)
    payload['visual_editing_rules'] = _clean_list(payload.get('visual_editing_rules'), 12)
    payload['transfer_rules'] = _clean_list(payload.get('transfer_rules'), 12)
    payload['forbidden_copying_rules'] = _clean_list(payload.get('forbidden_copying_rules'), 12)
    payload['next_collect_targets'] = _clean_list(payload.get('next_collect_targets'), 12)
    try:
        payload['score'] = int(payload.get('score') or 70)
    except Exception:
        payload['score'] = 70
    return payload


async def run_auto_collection(settings: Settings, memory: MemoryStore, req: Any) -> Dict[str, Any]:
    warnings: List[str] = []
    limit = max(1, min(int(getattr(req, 'limit', 3) or 3), 8))
    learn_goal = str(getattr(req, 'learn_goal', '') or settings.auto_collector_learn_goal)
    seed_links = _split_seed_links(str(getattr(req, 'seed_links', '') or settings.auto_collector_seed_links))
    include_account_urls = bool(getattr(req, 'include_account_urls', True))

    ctx = memory.context()
    profile = ctx.get('profile') or {}
    competitors = ctx.get('competitors') or []

    sources: List[str] = []
    sources.extend(seed_links)
    if include_account_urls:
        for comp in competitors[:20]:
            url = str(comp.get('url') or '').strip()
            if url and url.startswith('http') and url not in sources:
                sources.append(url)

    if not sources:
        warnings.append('没有可采集来源。请先在竞品账号库保存账号主页/爆款链接，或在自动采集里粘贴种子链接。')

    discovered: List[str] = []
    for source in sources[:20]:
        # 如果是具体视频短链/分享链接，直接纳入；如果像主页，尝试发现最新视频。
        if any(x in source.lower() for x in ['/video/', 'v.douyin.com', '.mp4', '.mov', '.webm']):
            if source not in discovered:
                discovered.append(source)
        else:
            urls, ds_warnings = await asyncio.to_thread(discover_recent_video_urls, settings, source, min(limit, 3))
            warnings.extend([f'{source}: {w}' for w in ds_warnings])
            for url in urls:
                if url not in discovered:
                    discovered.append(url)
        if len(discovered) >= limit:
            break

    collected_items: List[Dict[str, Any]] = []
    for url in discovered[:limit]:
        try:
            result = await extract_with_doubao(settings, None, source_url=url, manual_text='')
            item = {
                'source_name': result.source_name or url,
                'platform': 'douyin' if 'douyin' in url.lower() else 'unknown',
                'source_url': url,
                'manual_text': '',
                'transcript': result.transcript,
                'summary': result.summary,
                'structure': result.structure,
                'hooks': result.hooks,
                'selling_points': result.selling_points,
                'status': result.status,
                'collector_status': result.collector_status,
                'collected_video_url': result.collected_video_url or '',
                'raw': {'auto_agent': True, 'warnings': result.warnings, 'collected_video_name': result.collected_video_name},
            }
            memory.save_competitor_video(item)
            collected_items.append(item)
            warnings.extend([f'{url}: {w}' for w in (result.warnings or [])[:4]])
        except Exception as exc:
            warnings.append(f'{url}: 自动采集失败：{str(exc)[:260]}')

    recent_videos = collected_items or ctx.get('videos') or []
    learning = await analyze_creator_method(
        settings,
        industry=str(profile.get('industry') or ''),
        audience=str(profile.get('audience') or ''),
        videos=recent_videos,
        learn_goal=learn_goal,
    )

    event = memory.save_learning_event({
        'event_type': 'auto_creator_learning',
        'title': '自动学习同行视频打法',
        'payload': {
            'run_id': str(uuid.uuid4()),
            'run_at': _now(),
            'sources': sources,
            'discovered_urls': discovered,
            'collected_count': len(collected_items),
            'learn_goal': learn_goal,
            'learning': learning,
            'warnings': warnings[:80],
        },
    })

    return {
        'ok': True,
        'mode': 'auto_creator_learning',
        'sources_count': len(sources),
        'discovered_count': len(discovered),
        'collected_count': len(collected_items),
        'saved_event_id': event.get('id'),
        'learning': learning,
        'warnings': warnings[:80],
    }
