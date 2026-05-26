from __future__ import annotations

import asyncio
import html
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse

import httpx

from app.config import Settings
from app.services.collector import collector_cookie_path
from app.services.deepseek import DeepSeekError, _chat_json
from app.services.memory import MemoryStore

URL_RE = re.compile(r'https?://[^\s，。！？!！；;]+', re.I)
TITLE_RE = re.compile(r'<title[^>]*>(.*?)</title>', re.I | re.S)
DESC_RE = re.compile(r'<meta[^>]+(?:name|property)=["\'](?:description|og:description)["\'][^>]+content=["\']([^"\']+)["\']', re.I | re.S)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def today_key() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _clean_text(value: Any, limit: int = 300) -> str:
    text = re.sub(r'\s+', ' ', html.unescape(str(value or ''))).strip()
    return text[:limit]


def _split_keywords(raw: Any, limit: int = 40) -> List[str]:
    if isinstance(raw, list):
        source = raw
    else:
        source = re.split(r'[,，#\n\s]+', str(raw or ''))
    out: List[str] = []
    for item in source:
        text = str(item or '').strip(' #，,\n\t')
        if text and text not in out:
            out.append(text)
        if len(out) >= limit:
            break
    return out


def _num(value: Any) -> int:
    try:
        if value is None:
            return 0
        if isinstance(value, str):
            v = value.strip().lower().replace(',', '')
            multiplier = 1
            if v.endswith('w') or v.endswith('万'):
                multiplier = 10000
                v = v[:-1]
            elif v.endswith('k'):
                multiplier = 1000
                v = v[:-1]
            return int(float(v) * multiplier)
        return max(0, int(float(value)))
    except Exception:
        return 0


def heat_score(item: Dict[str, Any]) -> int:
    return int(
        _num(item.get('like_count'))
        + _num(item.get('comment_count')) * 5
        + _num(item.get('favorite_count')) * 4
        + _num(item.get('share_count')) * 6
        + min(_num(item.get('view_count')) // 100, 5000)
    )


def _is_specific_content_url(url: str) -> bool:
    u = url.lower()
    return any(x in u for x in ['/video/', '/note/', 'v.douyin.com', 'xhslink.com', '/discover/item/', '.mp4'])


def _entry_url(entry: Dict[str, Any]) -> str:
    for key in ('webpage_url', 'original_url', 'url'):
        value = str(entry.get(key) or '').strip()
        if value.startswith('http'):
            return value
    return ''


def _platform_from_url(url: str, fallback: str = '') -> str:
    u = url.lower()
    if 'douyin' in u or 'iesdouyin' in u:
        return '抖音'
    if 'xiaohongshu' in u or 'xhslink' in u:
        return '小红书'
    if 'weixin' in u or 'channels' in u:
        return '视频号/微信'
    if 'baidu' in u:
        return '百度'
    return fallback or '公开网页'


def _title_from_html(text: str) -> Tuple[str, str]:
    title = ''
    desc = ''
    match = TITLE_RE.search(text or '')
    if match:
        title = _clean_text(match.group(1), 180)
    match = DESC_RE.search(text or '')
    if match:
        desc = _clean_text(match.group(1), 500)
    return title, desc


async def _fetch_html_meta(settings: Settings, url: str, account: Dict[str, Any], warnings: List[str]) -> Dict[str, Any] | None:
    headers = {
        'User-Agent': settings.collector_user_agent,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Referer': 'https://www.douyin.com/',
    }
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=headers) as client:
            res = await client.get(url)
            if res.status_code >= 400:
                warnings.append(f'{url}: 公开页面读取失败 HTTP {res.status_code}')
                return None
            title, desc = _title_from_html(res.text)
    except Exception as exc:
        warnings.append(f'{url}: 公开页面读取失败：{str(exc)[:180]}')
        return None
    if not title and not desc:
        warnings.append(f'{url}: 没有读取到标题/描述，平台可能需要登录或动态渲染。')
        return None
    item = {
        'id': str(uuid.uuid4()),
        'date': today_key(),
        'platform': _platform_from_url(url, str(account.get('platform') or '')),
        'account_id': str(account.get('id') or ''),
        'account_name': str(account.get('name') or '公开来源'),
        'title': title or desc[:80] or '公开内容',
        'description': desc,
        'url': url,
        'published_at': '',
        'collected_at': now_iso(),
        'like_count': 0,
        'comment_count': 0,
        'favorite_count': 0,
        'share_count': 0,
        'view_count': 0,
        'heat_score': 0,
        'keyword': ','.join(_split_keywords(account.get('tags'), 5)),
        'tags': _split_keywords(account.get('tags'), 8),
        'thumbnail_url': '',
        'source_mode': 'public_html',
        'raw': {'description': desc},
        'warnings': [],
    }
    item['heat_score'] = heat_score(item)
    return item


def _yt_opts(settings: Settings, *, flat: bool, limit: int = 3) -> Dict[str, Any]:
    opts: Dict[str, Any] = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'ignoreerrors': True,
        'socket_timeout': min(max(settings.collector_timeout_seconds, 30), 240),
        'retries': 1,
        'playlistend': max(1, min(limit, 20)),
        'http_headers': {
            'User-Agent': settings.collector_user_agent,
            'Referer': 'https://www.douyin.com/',
        },
    }
    if flat:
        opts['extract_flat'] = True
    cookie_path = collector_cookie_path(settings)
    if cookie_path.exists() and cookie_path.stat().st_size > 20:
        opts['cookiefile'] = str(cookie_path)
    return opts


def _info_to_item(info: Dict[str, Any], url: str, account: Dict[str, Any]) -> Dict[str, Any]:
    webpage_url = _entry_url(info) or url
    title = _clean_text(info.get('title') or info.get('fulltitle') or info.get('description') or webpage_url, 180)
    item = {
        'id': str(uuid.uuid4()),
        'date': today_key(),
        'platform': _platform_from_url(webpage_url, str(account.get('platform') or '')),
        'account_id': str(account.get('id') or ''),
        'account_name': str(account.get('name') or info.get('uploader') or '公开来源'),
        'title': title or '公开内容',
        'description': _clean_text(info.get('description') or '', 700),
        'url': webpage_url,
        'published_at': str(info.get('upload_date') or info.get('timestamp') or ''),
        'collected_at': now_iso(),
        'like_count': _num(info.get('like_count')),
        'comment_count': _num(info.get('comment_count')),
        'favorite_count': _num(info.get('favorite_count') or info.get('favorites')),
        'share_count': _num(info.get('repost_count') or info.get('share_count')),
        'view_count': _num(info.get('view_count') or info.get('play_count')),
        'heat_score': 0,
        'keyword': ','.join(_split_keywords(account.get('tags'), 5)),
        'tags': _split_keywords(account.get('tags'), 8),
        'thumbnail_url': str(info.get('thumbnail') or ''),
        'source_mode': 'yt_dlp_public',
        'raw': {
            'extractor': info.get('extractor'),
            'duration': info.get('duration'),
            'uploader': info.get('uploader'),
            'uploader_url': info.get('uploader_url'),
        },
        'warnings': [],
    }
    item['heat_score'] = heat_score(item)
    return item


def _extract_with_ytdlp(settings: Settings, url: str, account: Dict[str, Any], limit: int, warnings: List[str]) -> List[Dict[str, Any]]:
    if not settings.enable_ytdlp_collector:
        warnings.append('ENABLE_YTDLP_COLLECTOR=false，跳过公开采集器。')
        return []
    try:
        import yt_dlp  # type: ignore
    except Exception as exc:
        warnings.append(f'yt-dlp 不可用：{exc}')
        return []

    urls: List[str] = []
    try:
        if _is_specific_content_url(url):
            urls = [url]
        else:
            with yt_dlp.YoutubeDL(_yt_opts(settings, flat=True, limit=limit * 2)) as ydl:
                info = ydl.extract_info(url, download=False)
            entries = info.get('entries') if isinstance(info, dict) else None
            if isinstance(entries, list):
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    entry_url = _entry_url(entry)
                    if entry_url and entry_url not in urls:
                        urls.append(entry_url)
                    elif entry.get('url') and str(entry.get('url')).startswith('http'):
                        urls.append(str(entry.get('url')))
                    if len(urls) >= limit:
                        break
            else:
                direct = _entry_url(info) if isinstance(info, dict) else ''
                if direct:
                    urls.append(direct)
    except Exception as exc:
        warnings.append(f'{url}: 账号/链接发现失败：{str(exc)[:240]}')
        return []

    items: List[Dict[str, Any]] = []
    for item_url in urls[:limit]:
        try:
            with yt_dlp.YoutubeDL(_yt_opts(settings, flat=False, limit=1)) as ydl:
                info = ydl.extract_info(item_url, download=False)
            if isinstance(info, dict):
                items.append(_info_to_item(info, item_url, account))
        except Exception as exc:
            warnings.append(f'{item_url}: 内容热度采集失败：{str(exc)[:240]}')
    return items


async def _collect_account(settings: Settings, account: Dict[str, Any], limit: int, warnings: List[str]) -> List[Dict[str, Any]]:
    url = str(account.get('url') or '').strip()
    if not url.startswith('http'):
        warnings.append(f"{account.get('name') or '未命名账号'}: 没有主页/视频链接，跳过。")
        return []
    items = await asyncio.to_thread(_extract_with_ytdlp, settings, url, account, limit, warnings)
    if not items and _is_specific_content_url(url):
        fallback = await _fetch_html_meta(settings, url, account, warnings)
        if fallback:
            items.append(fallback)
    return items


def _dedupe_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: set[str] = set()
    out: List[Dict[str, Any]] = []
    for item in items:
        key = str(item.get('url') or item.get('title') or item.get('id'))
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _rank_top3(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(items, key=lambda x: int(x.get('heat_score') or 0), reverse=True)[:3]


def _fallback_analysis(top_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    topics = [str(x.get('title') or '')[:60] for x in top_items]
    return {
        'summary': '已基于公开热度数据生成今日雷达。没有官方 API 时，系统只展示实际抓到的公开内容，不编造热度。',
        'content_angles': [f'围绕「{t}」做原创反打/解释内容' for t in topics[:5]],
        'customer_intents': ['税费/流程判断', '城市比较', '第二家园/身份规划', '教育家庭选盘'],
        'lead_magnets': ['马来西亚买房税费测算表', 'MM2H 与购房要求对照表', '吉隆坡 vs 新山选盘表'],
        'next_actions': ['给每个竞品账号补充具体视频链接，公开主页抓不到时上传 Cookies 或等官方/第三方数据源。', '把热度最高的话题一键转为口播文案和图文引流包。'],
    }


async def analyze_heat_items(settings: Settings, top_items: List[Dict[str, Any]], keywords: List[str]) -> Dict[str, Any]:
    if not top_items:
        return _fallback_analysis([])
    lines = []
    for i, item in enumerate(top_items[:12], start=1):
        lines.append(
            f"{i}. 平台：{item.get('platform')}｜账号：{item.get('account_name')}｜标题：{item.get('title')}｜"
            f"赞{item.get('like_count')} 评论{item.get('comment_count')} 收藏{item.get('favorite_count')} 分享{item.get('share_count')}｜链接：{item.get('url')}"
        )
    system = '你是中国社媒获客热度雷达分析师。只基于已采集到的真实数据分析，不要编造数据。输出严格 JSON。'
    user = f"""
监控关键词：{', '.join(keywords[:30]) or '未填写'}
今日真实采集内容：
{chr(10).join(lines)}

请输出 JSON：
{{
  "summary": "一句话总结今天热度方向",
  "content_angles": ["我们应该跟进的原创选题"],
  "customer_intents": ["客户真实需求/疑问"],
  "lead_magnets": ["适合承接的资料包/报告"],
  "reply_hooks": ["适合评论区/私信的人工回复开头"],
  "next_actions": ["今天运营要做的动作"]
}}
""".strip()
    try:
        payload = await _chat_json(settings, system, user, temperature=0.35, timeout=90)
        for key in ['content_angles', 'customer_intents', 'lead_magnets', 'reply_hooks', 'next_actions']:
            value = payload.get(key)
            if isinstance(value, str):
                payload[key] = _split_keywords(value, 12)
            elif not isinstance(value, list):
                payload[key] = []
        payload.setdefault('summary', '今日热度分析已完成。')
        return payload
    except (DeepSeekError, Exception) as exc:
        analysis = _fallback_analysis(top_items)
        analysis['warnings'] = [f'AI 分析失败，已降级规则分析：{str(exc)[:240]}']
        return analysis


async def run_public_heat_radar(settings: Settings, memory: MemoryStore, req: Any) -> Dict[str, Any]:
    warnings: List[str] = []
    limit = max(1, min(int(getattr(req, 'limit_per_account', 3) or 3), 6))
    keywords = _split_keywords(getattr(req, 'keywords', []), 60)
    accounts: List[Dict[str, Any]] = []

    if bool(getattr(req, 'include_saved_accounts', True)):
        saved = memory.list('heat_radar_accounts', limit=80)
        if saved:
            accounts.extend(saved)
        else:
            # 兼容旧竞品账号库。
            for comp in memory.list('competitor_accounts', limit=50):
                accounts.append({
                    'id': comp.get('id'),
                    'name': comp.get('name'),
                    'platform': comp.get('platform'),
                    'url': comp.get('url'),
                    'tags': comp.get('positioning') or comp.get('notes') or '',
                    'notes': comp.get('notes') or '',
                })

    for acc in getattr(req, 'accounts', []) or []:
        payload = acc.model_dump() if hasattr(acc, 'model_dump') else dict(acc)
        accounts.append(payload)

    # 去重：URL 优先，其次名称。
    deduped: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for acc in accounts:
        key = str(acc.get('url') or acc.get('name') or '').strip()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(acc)

    if not deduped:
        warnings.append('没有可自动采集的账号/链接。请先添加竞品账号主页或具体公开视频链接。')

    collected: List[Dict[str, Any]] = []
    for acc in deduped[:30]:
        try:
            items = await _collect_account(settings, acc, limit, warnings)
            collected.extend(items)
        except Exception as exc:
            warnings.append(f"{acc.get('name') or acc.get('url')}: 采集失败：{str(exc)[:240]}")

    collected = _dedupe_items(collected)
    for item in collected:
        item['heat_score'] = heat_score(item)
        title_blob = ' '.join([str(item.get('title') or ''), str(item.get('description') or ''), str(item.get('keyword') or '')])
        matched = [k for k in keywords if k and k in title_blob]
        if matched:
            item['matched_keywords'] = matched[:6]

    top_items = _rank_top3(collected)
    analysis = await analyze_heat_items(settings, top_items, keywords)

    saved_count = 0
    if bool(getattr(req, 'save_to_memory', True)):
        for item in collected:
            memory.insert('heat_radar_items', item)
            saved_count += 1
        memory.insert('heat_daily_top3', {
            'date': today_key(),
            'summary': analysis.get('summary', ''),
            'top_items': top_items,
            'analysis': analysis,
            'keywords': keywords,
            'accounts_count': len(deduped),
            'raw': {'warnings': warnings[:80]},
        })
        memory.save_learning_event({
            'event_type': 'heat_radar_public_crawl',
            'title': f'{today_key()} 自动热度雷达',
            'payload': {'top_items': top_items, 'analysis': analysis, 'warnings': warnings[:80]},
        })

    return {
        'ok': True,
        'source_mode': 'public_crawler_without_enterprise_api',
        'accounts_count': len(deduped),
        'collected_count': len(collected),
        'saved_count': saved_count,
        'top_items': top_items,
        'analysis': analysis,
        'warnings': warnings[:80],
        'next_actions': analysis.get('next_actions') or _fallback_analysis(top_items).get('next_actions'),
    }
