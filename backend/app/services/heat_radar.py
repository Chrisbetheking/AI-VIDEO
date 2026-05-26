from __future__ import annotations

import asyncio
import html
import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Tuple
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from app.config import Settings
from app.services.deepseek import DeepSeekError, _chat_json
from app.services.memory import MemoryStore

URL_RE = re.compile(r'https?://[^\s，。！？!！；;）)]+', re.I)
TITLE_RE = re.compile(r'<title[^>]*>(.*?)</title>', re.I | re.S)
DESC_RE = re.compile(r'<meta[^>]+(?:name|property)=["\'](?:description|og:description)["\'][^>]+content=["\']([^"\']+)["\']', re.I | re.S)
RENDER_DATA_RE = re.compile(r'<script[^>]+id=["\']RENDER_DATA["\'][^>]*>(.*?)</script>', re.I | re.S)
JSON_STATE_RE = re.compile(r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', re.I | re.S)
DOUYIN_VIDEO_RE = re.compile(r'/(?:video|note)/(\d+)|(?:aweme_id|modal_id|item_id)=([0-9]{8,})', re.I)

CN_TZ = timezone(timedelta(hours=8))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def today_key() -> str:
    return datetime.now(CN_TZ).date().isoformat()


def _clean_text(value: Any, limit: int = 300) -> str:
    text = re.sub(r'\s+', ' ', html.unescape(str(value or ''))).strip()
    return text[:limit]


def _split_keywords(raw: Any, limit: int = 40) -> List[str]:
    if isinstance(raw, list):
        source = raw
    else:
        source = re.split(r'[,，#\n\s/]+', str(raw or ''))
    out: List[str] = []
    for item in source:
        text = str(item or '').strip(' #，,\n\t/')
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
            v = value.strip().lower().replace(',', '').replace(' ', '')
            if not v:
                return 0
            multiplier = 1
            if v.endswith('w') or v.endswith('万'):
                multiplier = 10000
                v = v[:-1]
            elif v.endswith('k'):
                multiplier = 1000
                v = v[:-1]
            return max(0, int(float(v) * multiplier))
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
        + (10 if item.get('url') else 0)
    )


def _platform_from_url(url: str, fallback: str = '') -> str:
    u = (url or '').lower()
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


def _extract_urls(*parts: Any) -> List[str]:
    seen: set[str] = set()
    urls: List[str] = []
    for part in parts:
        for url in URL_RE.findall(str(part or '')):
            u = url.strip().rstrip('.,，。；;')
            if u and u not in seen:
                seen.add(u)
                urls.append(u)
    return urls


def _metric_value(text: str, names: List[str]) -> int:
    name_pat = '|'.join(map(re.escape, names))
    m = re.search(rf'(?:{name_pat})\s*[:：]?\s*([0-9]+(?:\.[0-9]+)?\s*(?:万|w|W|k|K)?)', text, re.I)
    if not m:
        return 0
    return _num(m.group(1))


def _looks_like_metrics(text: str) -> bool:
    return bool(re.search(r'(赞|点赞|评论|收藏|分享|转发|播放|浏览)\s*[:：]?\s*\d', text))


def _line_title(line: str, fallback: str) -> str:
    cleaned = URL_RE.sub('', line or '')
    cleaned = re.sub(r'(赞|点赞|评论|收藏|分享|转发|播放|浏览)\s*[:：]?\s*[0-9]+(?:\.[0-9]+)?\s*(?:万|w|W|k|K)?', '', cleaned)
    cleaned = _clean_text(cleaned, 140).strip(' -—｜|:：，,')
    return cleaned or fallback


def _make_item(account: Dict[str, Any], *, title: str, url: str = '', description: str = '', source_mode: str = 'manual_or_public', line: str = '', published_at: str = '', raw: Dict[str, Any] | None = None) -> Dict[str, Any]:
    raw_line = line or ' '.join([title, description])
    item = {
        'id': str(uuid.uuid4()),
        'date': today_key(),
        'platform': _platform_from_url(url, str(account.get('platform') or '')),
        'account_id': str(account.get('id') or ''),
        'account_name': str(account.get('name') or '公开来源'),
        'title': _clean_text(title or str(account.get('name') or '公开内容'), 180),
        'description': _clean_text(description, 900),
        'url': url,
        'published_at': published_at,
        'collected_at': now_iso(),
        'like_count': _metric_value(raw_line, ['赞', '点赞', 'like', 'likes']),
        'comment_count': _metric_value(raw_line, ['评论', 'comment', 'comments']),
        'favorite_count': _metric_value(raw_line, ['收藏', '藏', 'favorite', 'favorites']),
        'share_count': _metric_value(raw_line, ['分享', '转发', 'share', 'shares']),
        'view_count': _metric_value(raw_line, ['播放', '浏览', '观看', 'view', 'views']),
        'heat_score': 0,
        'keyword': ','.join(_split_keywords(account.get('tags'), 5)),
        'tags': _split_keywords(account.get('tags'), 8),
        'thumbnail_url': '',
        'source_mode': source_mode,
        'raw': raw or {'line': line},
        'warnings': [],
    }
    item['heat_score'] = heat_score(item)
    return item


def _douyin_headers(settings: Settings, url: str = 'https://www.douyin.com/') -> Dict[str, str]:
    cookie = os.getenv('DOUYIN_WEB_COOKIE', '').strip() or os.getenv('HEAT_RADAR_DOUYIN_COOKIE', '').strip()
    headers = {
        'User-Agent': getattr(settings, 'collector_user_agent', '') or 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,application/json,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Referer': 'https://www.douyin.com/',
        'Origin': 'https://www.douyin.com',
    }
    if cookie:
        headers['Cookie'] = cookie
    return headers



def _douyin_cookie_file_from_env() -> str:
    """Create a temporary Netscape cookie file from DOUYIN_WEB_COOKIE for yt-dlp.

    yt-dlp works much better with a cookie file than with only raw Cookie headers.
    The file is best-effort and safe to omit when no cookie is configured.
    """
    raw = os.getenv('DOUYIN_WEB_COOKIE', '').strip() or os.getenv('HEAT_RADAR_DOUYIN_COOKIE', '').strip()
    if not raw:
        return ''
    try:
        lines = ['# Netscape HTTP Cookie File']
        for part in raw.split(';'):
            if '=' not in part:
                continue
            name, value = part.split('=', 1)
            name = name.strip()
            value = value.strip()
            if not name:
                continue
            # domain, include_subdomains, path, secure, expiry, name, value
            lines.append(f'.douyin.com\tTRUE\t/\tFALSE\t2147483647\t{name}\t{value}')
            lines.append(f'www.douyin.com\tFALSE\t/\tFALSE\t2147483647\t{name}\t{value}')
        if len(lines) <= 1:
            return ''
        path = os.path.join(tempfile.gettempdir(), 'douyin_web_cookie.txt')
        with open(path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')
        return path
    except Exception:
        return ''


def _flatten_ytdlp_entries(info: Any, limit: int) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    if not isinstance(info, dict):
        return entries
    raw_entries = info.get('entries')
    if raw_entries is None:
        entries = [info]
    else:
        for entry in raw_entries:
            if isinstance(entry, dict):
                entries.append(entry)
            if len(entries) >= limit:
                break
    return entries[:limit]


def _ytdlp_extract_sync(url: str, limit: int, headers: Dict[str, str]) -> Dict[str, Any]:
    """Run yt-dlp in-process.

    This is the strongest no-enterprise fallback for Douyin profile pages because
    yt-dlp keeps up with many public web changes better than our hand-written
    HTML/API parser. It still obeys public-page limits: no login bypass, no
    CAPTCHA bypass, no auto-comment/private-message behavior.
    """
    from yt_dlp import YoutubeDL  # type: ignore

    cookiefile = _douyin_cookie_file_from_env()
    opts: Dict[str, Any] = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'ignoreerrors': True,
        'noplaylist': False,
        'playlistend': max(3, min(int(limit or 3), 12)),
        'extract_flat': 'in_playlist',
        'socket_timeout': int(os.getenv('HEAT_RADAR_YTDLP_SOCKET_TIMEOUT', '12')),
        'retries': 1,
        'fragment_retries': 0,
        'nocheckcertificate': True,
        'http_headers': {k: v for k, v in headers.items() if v},
    }
    if cookiefile:
        opts['cookiefile'] = cookiefile
    with YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False) or {}


def _normalize_ytdlp_entry(account: Dict[str, Any], entry: Dict[str, Any], source_url: str, source_mode: str) -> Dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    title = _clean_text(
        entry.get('title')
        or entry.get('fulltitle')
        or entry.get('description')
        or entry.get('alt_title')
        or entry.get('id')
        or str(account.get('name') or '抖音视频'),
        180,
    )
    desc = _clean_text(entry.get('description') or entry.get('title') or '', 700)
    raw_url = str(entry.get('webpage_url') or entry.get('url') or entry.get('original_url') or source_url or '')
    if raw_url and raw_url.startswith('//'):
        raw_url = 'https:' + raw_url
    if raw_url and not raw_url.startswith('http'):
        # Flat playlist entries sometimes return only an ID or relative URL.
        vid = _extract_video_id(raw_url) or str(entry.get('id') or '')
        raw_url = f'https://www.douyin.com/video/{vid}' if vid and re.fullmatch(r'\d{8,}', vid) else source_url
    vid = _extract_video_id(raw_url) or str(entry.get('id') or '')
    if vid and re.fullmatch(r'\d{8,}', vid):
        raw_url = f'https://www.douyin.com/video/{vid}'
    published_at = ''
    if entry.get('timestamp'):
        published_at = _published_from_ts(entry.get('timestamp'))
    elif entry.get('release_timestamp'):
        published_at = _published_from_ts(entry.get('release_timestamp'))
    item = _make_item(
        account,
        title=title,
        url=raw_url or source_url,
        description=desc,
        source_mode=source_mode,
        published_at=published_at,
        raw={'yt_dlp': {k: entry.get(k) for k in ['id', 'title', 'webpage_url', 'url', 'duration', 'timestamp', 'view_count', 'like_count', 'comment_count', 'repost_count'] if k in entry}},
    )
    item['like_count'] = _num(entry.get('like_count') or entry.get('like_count_str'))
    item['comment_count'] = _num(entry.get('comment_count') or entry.get('comment_count_str'))
    item['favorite_count'] = _num(entry.get('favorite_count') or entry.get('collect_count'))
    item['share_count'] = _num(entry.get('repost_count') or entry.get('share_count'))
    item['view_count'] = _num(entry.get('view_count') or entry.get('play_count'))
    item['thumbnail_url'] = str(entry.get('thumbnail') or '')
    item['heat_score'] = heat_score(item)
    if not item.get('title') and not item.get('url'):
        return None
    return item


async def _collect_douyin_with_ytdlp(settings: Settings, account: Dict[str, Any], input_url: str, warnings: List[str], limit: int) -> List[Dict[str, Any]]:
    if os.getenv('HEAT_RADAR_DISABLE_YTDLP', '').strip().lower() in {'1', 'true', 'yes', 'on'}:
        return []
    if not input_url.startswith('http'):
        return []
    timeout = max(12, min(int(os.getenv('HEAT_RADAR_YTDLP_TIMEOUT', '38') or '38'), 75))
    try:
        headers = _douyin_headers(settings, input_url)
        info = await asyncio.wait_for(asyncio.to_thread(_ytdlp_extract_sync, input_url, limit, headers), timeout=timeout)
        entries = _flatten_ytdlp_entries(info, max(3, limit))
        items: List[Dict[str, Any]] = []
        is_profile = bool(info.get('entries'))
        for entry in entries[:max(3, limit)]:
            item = _normalize_ytdlp_entry(account, entry, input_url, 'douyin_ytdlp_profile_recent3' if is_profile else 'douyin_ytdlp_video')
            if item:
                items.append(item)
        items = _dedupe_items(items)[:limit]
        if items:
            warnings.append(f'yt-dlp 已从抖音公开页提取 {len(items)} 条最近内容。')
            return items
        warnings.append('yt-dlp 没有返回视频条目，继续使用网页/API兜底。')
    except Exception as exc:
        warnings.append(f'yt-dlp 抖音采集失败，继续使用网页/API兜底：{str(exc)[:220]}')
    return []


def _extract_aweme_ids_from_text(text: str, limit: int = 6) -> List[str]:
    ids: List[str] = []
    for pattern in [
        r'"aweme_id"\s*:\s*"?(\d{8,})"?',
        r'"awemeId"\s*:\s*"?(\d{8,})"?',
        r'"itemId"\s*:\s*"?(\d{8,})"?',
        r'"modal_id"\s*:\s*"?(\d{8,})"?',
        r'/video/(\d{8,})',
        r'aweme_id=(\d{8,})',
    ]:
        for m in re.finditer(pattern, text or ''):
            vid = m.group(1)
            if vid not in ids:
                ids.append(vid)
            if len(ids) >= limit:
                return ids
    return ids


async def _resolve_url(settings: Settings, url: str, warnings: List[str]) -> str:
    """Resolve share links such as https://v.douyin.com/xxxx/ into the real page URL."""
    url = (url or '').strip()
    if not url.startswith('http'):
        return url
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True, headers=_douyin_headers(settings, url)) as client:
            res = await client.get(url)
            final = str(res.url)
            # Some share pages include an intermediate href rather than a normal redirect.
            if ('v.douyin.com' in final or 'iesdouyin.com/share' in final) and res.text:
                m = re.search(r'https://www\.douyin\.com/[^"\'<>\s]+', res.text)
                if m:
                    final = html.unescape(m.group(0))
            return final or url
    except Exception as exc:
        warnings.append(f'{url}: 短链转换失败：{str(exc)[:160]}')
        return url


def _extract_video_id(url: str) -> str:
    m = DOUYIN_VIDEO_RE.search(url or '')
    if not m:
        return ''
    return m.group(1) or m.group(2) or ''


def _extract_sec_uid(url: str, html_text: str = '') -> str:
    candidates: List[str] = []
    parsed = urlparse(url or '')
    qs = parse_qs(parsed.query or '')
    for key in ['sec_uid', 'sec_user_id']:
        candidates.extend(qs.get(key) or [])
    m = re.search(r'/user/([^/?#]+)', parsed.path or '')
    if m:
        candidates.append(m.group(1))
    for text in [url, html_text or '']:
        candidates.extend(re.findall(r'(MS4wLjAB[0-9A-Za-z_\-\.]+)', text))
        candidates.extend(re.findall(r'"sec_uid"\s*:\s*"([^"]+)"', text))
        candidates.extend(re.findall(r'"sec_user_id"\s*:\s*"([^"]+)"', text))
    for c in candidates:
        c = unquote(str(c or '')).strip()
        if c:
            return c
    return ''


def _walk_json(obj: Any) -> Iterable[Any]:
    yield obj
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _walk_json(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_json(v)


def _parse_render_json(html_text: str) -> List[Any]:
    payloads: List[Any] = []
    for regex in [RENDER_DATA_RE, JSON_STATE_RE]:
        for m in regex.finditer(html_text or ''):
            raw = html.unescape(m.group(1) or '').strip()
            if not raw:
                continue
            for candidate in [raw, unquote(raw)]:
                try:
                    payloads.append(json.loads(candidate))
                    break
                except Exception:
                    continue
    # Generic fallback: find aweme_list JSON fragments if present.
    return payloads


def _published_from_ts(ts: Any) -> str:
    n = _num(ts)
    if n <= 0:
        return ''
    # Douyin create_time is usually seconds.
    if n > 10_000_000_000:
        n = n // 1000
    try:
        return datetime.fromtimestamp(n, tz=timezone.utc).isoformat()
    except Exception:
        return ''


def _normalize_aweme(account: Dict[str, Any], aweme: Dict[str, Any], source_mode: str = 'douyin_web_api') -> Dict[str, Any] | None:
    if not isinstance(aweme, dict):
        return None
    aweme_id = str(aweme.get('aweme_id') or aweme.get('id') or aweme.get('item_id') or '')
    desc = _clean_text(aweme.get('desc') or aweme.get('share_info', {}).get('share_desc') or aweme.get('caption') or '', 500)
    title = desc or _clean_text(aweme.get('share_info', {}).get('share_title') or aweme.get('seo_info', {}).get('seo_ocr_content') or '抖音视频', 180)
    url = f'https://www.douyin.com/video/{aweme_id}' if aweme_id else str(aweme.get('share_url') or aweme.get('url') or '')
    stats = aweme.get('statistics') or aweme.get('stats') or {}
    published_at = _published_from_ts(aweme.get('create_time') or aweme.get('createTime'))
    item = _make_item(account, title=title, url=url, description=desc, source_mode=source_mode, published_at=published_at, raw={'aweme': aweme})
    item['like_count'] = _num(stats.get('digg_count') or stats.get('like_count') or stats.get('diggCount'))
    item['comment_count'] = _num(stats.get('comment_count') or stats.get('commentCount'))
    item['favorite_count'] = _num(stats.get('collect_count') or stats.get('favorite_count') or stats.get('collectCount'))
    item['share_count'] = _num(stats.get('share_count') or stats.get('shareCount'))
    item['view_count'] = _num(stats.get('play_count') or stats.get('playCount'))
    video = aweme.get('video') or {}
    cover = video.get('cover') or video.get('origin_cover') or video.get('dynamic_cover') or {}
    if isinstance(cover, dict):
        urls = cover.get('url_list') or cover.get('urlList') or []
        if urls:
            item['thumbnail_url'] = str(urls[0])
    item['heat_score'] = heat_score(item)
    return item


async def _fetch_douyin_post_api(settings: Settings, sec_uid: str, account: Dict[str, Any], warnings: List[str], limit: int) -> List[Dict[str, Any]]:
    if not sec_uid:
        return []
    url = 'https://www.douyin.com/aweme/v1/web/aweme/post/'
    params = {
        'device_platform': 'webapp',
        'aid': '6383',
        'channel': 'channel_pc_web',
        'sec_user_id': sec_uid,
        'max_cursor': '0',
        'locate_query': 'false',
        'show_live_replay_strategy': '1',
        'need_time_list': '1',
        'time_list_query': '0',
        'count': str(max(3, min(limit, 10))),
        'publish_video_strategy_type': '2',
        'from_user_page': '1',
        'update_version_code': '170400',
        'pc_client_type': '1',
        'version_code': '290100',
        'version_name': '29.1.0',
        'cookie_enabled': 'true',
        'screen_width': '1920',
        'screen_height': '1080',
        'browser_language': 'zh-CN',
        'browser_platform': 'Win32',
        'browser_name': 'Chrome',
        'browser_version': '124.0.0.0',
    }
    try:
        async with httpx.AsyncClient(timeout=12, follow_redirects=True, headers=_douyin_headers(settings)) as client:
            res = await client.get(url, params=params)
            if res.status_code >= 400:
                warnings.append(f'抖音主页接口 HTTP {res.status_code}：公开接口可能要求 Cookie/验证。')
                return []
            data = res.json()
    except Exception as exc:
        warnings.append(f'抖音主页最近视频接口失败：{str(exc)[:180]}')
        return []
    awemes = data.get('aweme_list') or data.get('awemeList') or []
    if not awemes:
        status_msg = data.get('status_msg') or data.get('message') or ''
        warnings.append(f'抖音主页接口未返回最近视频。{status_msg}'.strip())
        return []
    items: List[Dict[str, Any]] = []
    for aweme in awemes[:limit]:
        item = _normalize_aweme(account, aweme, source_mode='douyin_profile_recent_api')
        if item:
            items.append(item)
    return items


async def _fetch_douyin_detail(settings: Settings, aweme_id: str, account: Dict[str, Any], warnings: List[str]) -> List[Dict[str, Any]]:
    if not aweme_id:
        return []
    url = 'https://www.douyin.com/aweme/v1/web/aweme/detail/'
    params = {
        'device_platform': 'webapp',
        'aid': '6383',
        'aweme_id': aweme_id,
        'pc_client_type': '1',
        'version_code': '290100',
        'version_name': '29.1.0',
        'cookie_enabled': 'true',
        'screen_width': '1920',
        'screen_height': '1080',
        'browser_language': 'zh-CN',
        'browser_platform': 'Win32',
        'browser_name': 'Chrome',
        'browser_version': '124.0.0.0',
    }
    try:
        async with httpx.AsyncClient(timeout=12, follow_redirects=True, headers=_douyin_headers(settings)) as client:
            res = await client.get(url, params=params)
            if res.status_code < 400:
                data = res.json()
                aweme = data.get('aweme_detail') or data.get('aweme') or data.get('item')
                item = _normalize_aweme(account, aweme or {}, source_mode='douyin_video_detail_api')
                if item:
                    return [item]
            warnings.append(f'抖音视频详情接口未返回：{aweme_id} HTTP {res.status_code}')
    except Exception as exc:
        warnings.append(f'抖音视频详情接口失败：{str(exc)[:180]}')
    return []


async def _fetch_html(settings: Settings, url: str, warnings: List[str]) -> tuple[str, str]:
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True, headers=_douyin_headers(settings, url)) as client:
            res = await client.get(url)
            final = str(res.url)
            if res.status_code >= 400:
                warnings.append(f'{url}: 页面读取失败 HTTP {res.status_code}')
                return final, ''
            return final, res.text or ''
    except Exception as exc:
        warnings.append(f'{url}: 页面读取失败：{str(exc)[:160]}')
        return url, ''


def _items_from_render_data(account: Dict[str, Any], payloads: List[Any], limit: int) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for payload in payloads:
        for node in _walk_json(payload):
            if isinstance(node, dict):
                # Direct aweme object.
                if node.get('aweme_id') or node.get('desc') and node.get('statistics'):
                    item = _normalize_aweme(account, node, source_mode='douyin_render_data')
                    if item:
                        items.append(item)
                # aweme list nested in any key.
                for key in ['aweme_list', 'awemeList', 'post', 'items']:
                    value = node.get(key)
                    if isinstance(value, list):
                        for aweme in value:
                            if isinstance(aweme, dict):
                                item = _normalize_aweme(account, aweme, source_mode='douyin_render_data')
                                if item:
                                    items.append(item)
            if len(items) >= limit:
                return _dedupe_items(items)[:limit]
    return _dedupe_items(items)[:limit]


async def _collect_douyin_url(settings: Settings, account: Dict[str, Any], input_url: str, warnings: List[str], limit: int) -> List[Dict[str, Any]]:
    # Strongest public fallback first: yt-dlp can often read a Douyin profile's
    # latest playlist entries even when the web API needs dynamic params.
    ytdlp_items = await _collect_douyin_with_ytdlp(settings, account, input_url, warnings, max(3, limit))
    if ytdlp_items:
        return ytdlp_items[:limit]

    final_url = await _resolve_url(settings, input_url, warnings)
    if final_url != input_url:
        warnings.append(f'短链已转换：{input_url} → {final_url}')
    video_id = _extract_video_id(final_url)
    if video_id:
        items = await _fetch_douyin_detail(settings, video_id, account, warnings)
        if items:
            return items[:limit]
    final_url, html_text = await _fetch_html(settings, final_url, warnings)
    video_id = video_id or _extract_video_id(final_url) or _extract_video_id(html_text)
    if video_id:
        items = await _fetch_douyin_detail(settings, video_id, account, warnings)
        if items:
            return items[:limit]
    render_items = _items_from_render_data(account, _parse_render_json(html_text), limit)
    if render_items:
        return render_items[:limit]

    html_ids = _extract_aweme_ids_from_text(html_text, max(3, limit))
    html_items: List[Dict[str, Any]] = []
    for vid in html_ids[:max(3, limit)]:
        detail_items = await _fetch_douyin_detail(settings, vid, account, warnings)
        if detail_items:
            html_items.extend(detail_items)
        else:
            html_items.append(_make_item(account, title=f'{account.get("name") or "抖音账号"} 最近视频 {vid}', url=f'https://www.douyin.com/video/{vid}', description='从主页 HTML 识别到视频 ID，但公开详情接口未返回热度指标。', source_mode='douyin_html_aweme_id'))
    if html_items:
        return _dedupe_items(html_items)[:limit]

    sec_uid = _extract_sec_uid(final_url, html_text)
    if sec_uid:
        items = await _fetch_douyin_post_api(settings, sec_uid, account, warnings, limit)
        if items:
            return items[:limit]
        ytdlp_final_items = await _collect_douyin_with_ytdlp(settings, account, final_url, warnings, max(3, limit))
        if ytdlp_final_items:
            return ytdlp_final_items[:limit]
        title, desc = _title_from_html(html_text)
        placeholder = _make_item(
            account,
            title=(title or str(account.get('name') or '抖音账号主页已转换')),
            url=final_url,
            description='主页短链已转换，并识别到 sec_uid；但公开接口没有返回最近三条。建议在 Render 环境变量添加 DOUYIN_WEB_COOKIE，或粘贴具体视频链接。',
            source_mode='douyin_profile_resolved_no_posts',
            raw={'sec_uid': sec_uid, 'final_url': final_url},
        )
        placeholder['warnings'] = ['主页已转换，但未拿到最近视频列表。']
        return [placeholder]
    title, desc = _title_from_html(html_text)
    return [_make_item(
        account,
        title=title or str(account.get('name') or '抖音公开链接已留存'),
        url=final_url,
        description=desc or '公开链接已留存，但没有识别到视频 ID 或 sec_uid。请确认链接不是过期短链。',
        source_mode='douyin_public_url_unresolved',
        raw={'final_url': final_url},
    )]


async def _fetch_html_meta(settings: Settings, url: str, account: Dict[str, Any], warnings: List[str]) -> Dict[str, Any] | None:
    # Non-Douyin lightweight title fetch. It is safe and short-timeout; no heavy crawler.
    if not url.startswith('http'):
        return None
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True, headers=_douyin_headers(settings, url)) as client:
            res = await client.get(url)
            if res.status_code >= 400:
                warnings.append(f'{url}: 公开页面读取失败 HTTP {res.status_code}')
                return None
            title, desc = _title_from_html(res.text)
            final_url = str(res.url)
    except Exception as exc:
        warnings.append(f'{url}: 公开页面读取失败：{str(exc)[:160]}')
        return None
    if not title and not desc:
        return None
    return _make_item(account, title=title or desc[:80] or '公开内容', url=final_url or url, description=desc, source_mode='public_html')


def _parse_account_notes(account: Dict[str, Any], warnings: List[str], limit: int) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    notes = str(account.get('notes') or '')
    url = str(account.get('url') or '').strip()
    fallback_title = str(account.get('name') or '竞品账号观察').strip() or '竞品账号观察'

    for line in re.split(r'[\n\r]+', notes):
        line = line.strip()
        if not line:
            continue
        line_urls = _extract_urls(line)
        if line_urls:
            for u in line_urls[:3]:
                items.append(_make_item(account, title=_line_title(line, fallback_title), url=u, description=line, source_mode='account_note_url', line=line))
        elif _looks_like_metrics(line):
            items.append(_make_item(account, title=_line_title(line, fallback_title), url=url if url.startswith('http') else '', description=line, source_mode='account_note_metrics', line=line))
        if len(items) >= limit:
            break

    if len(items) < limit and url.startswith('http'):
        already = {str(x.get('url') or '') for x in items}
        if url not in already:
            mode = 'account_content_url' if any(x in url.lower() for x in ['/video/', '/note/', 'v.douyin.com', 'xhslink.com']) else 'account_homepage_observation'
            title = fallback_title if mode == 'account_content_url' else f'{fallback_title}｜账号主页已留存'
            desc = '公开链接已留存；如果平台不开放最近视频列表，需要补具体视频/笔记链接、Cookie、第三方数据或官方 API。'
            items.append(_make_item(account, title=title, url=url, description=desc, source_mode=mode, line=desc))

    if not items:
        warnings.append(f'{fallback_title}: 没有具体视频/笔记链接，也没有点赞/评论/收藏等真实指标。')
    return items[:limit]


async def _collect_account(settings: Settings, account: Dict[str, Any], limit: int, warnings: List[str]) -> List[Dict[str, Any]]:
    urls = _extract_urls(account.get('url'), account.get('notes'))
    collected: List[Dict[str, Any]] = []
    douyin_urls = [u for u in urls if 'douyin.com' in u.lower() or 'iesdouyin.com' in u.lower()]
    for url in douyin_urls[:3]:
        try:
            collected.extend(await _collect_douyin_url(settings, account, url, warnings, limit))
        except Exception as exc:
            warnings.append(f'{url}: 抖音采集失败：{str(exc)[:200]}')
        if len(collected) >= limit:
            break

    # Parse manual metric lines as additional real items.
    collected.extend(_parse_account_notes(account, warnings, limit))

    enriched: List[Dict[str, Any]] = []
    for item in collected:
        url = str(item.get('url') or '')
        if item.get('source_mode', '').startswith('douyin_'):
            enriched.append(item)
            continue
        meta = None
        if url and 'douyin.com' not in url.lower():
            meta = await _fetch_html_meta(settings, url, account, warnings)
        if meta:
            for key in ['like_count', 'comment_count', 'favorite_count', 'share_count', 'view_count']:
                if item.get(key):
                    meta[key] = item.get(key, meta.get(key, 0))
            meta['heat_score'] = heat_score(meta)
            enriched.append(meta)
        else:
            enriched.append(item)
    return _dedupe_items(enriched)[:limit]


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


def _item_date_cn(item: Dict[str, Any]) -> str:
    for field in ['published_at', 'collected_at']:
        value = str(item.get(field) or '')
        if not value:
            continue
        try:
            dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
            return dt.astimezone(CN_TZ).date().isoformat()
        except Exception:
            continue
    return str(item.get('date') or '')[:10]


def _rank_top3(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(items, key=lambda x: (int(x.get('heat_score') or 0), str(x.get('published_at') or x.get('collected_at') or '')), reverse=True)[:3]


def _recent3(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(items, key=lambda x: (str(x.get('published_at') or ''), str(x.get('collected_at') or '')), reverse=True)[:3]


def _pick_top_items(collected: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], str, bool]:
    today = today_key()
    real_posts = [x for x in collected if not str(x.get('source_mode') or '').endswith('_observation')]
    today_items = [x for x in real_posts if _item_date_cn(x) == today]
    if today_items:
        return _rank_top3(today_items), 'today_top3', False
    if real_posts:
        return _recent3(real_posts), 'recent3_no_today', True
    if collected:
        return collected[:3], 'resolved_homepage_no_posts', True
    return [], 'empty', True


def _recent_real_items(memory: MemoryStore, limit: int = 3) -> List[Dict[str, Any]]:
    rows = memory.list('heat_radar_items', limit=120)
    valid: List[Dict[str, Any]] = []
    for item in rows:
        mode = str(item.get('source_mode') or '').lower()
        if any(x in mode for x in ['seed', 'demo', 'local_fake']):
            continue
        if not (item.get('url') or item.get('title')):
            continue
        valid.append(item)
    return _recent3(valid)[:limit]


def _fallback_analysis(top_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    topics = [str(x.get('title') or '')[:60] for x in top_items if x.get('title')]
    if not topics:
        topics = ['补具体视频/笔记链接或 DOUYIN_WEB_COOKIE', '接入第三方/官方数据源', '补点赞评论收藏指标']
    return {
        'summary': '已按真实来源运行热度雷达：优先采集今天内容；今天没有新内容时，自动回看最近 3 条。不会再生成本地假数据。',
        'content_angles': [f'围绕「{t}」做原创跟进/解释内容' for t in topics[:5]],
        'customer_intents': ['税费/流程判断', '城市比较', '第二家园/身份规划', '教育家庭选盘'],
        'lead_magnets': ['马来西亚买房税费测算表', 'MM2H 与购房要求对照表', '吉隆坡 vs 新山选盘表'],
        'reply_hooks': ['这个问题先看你的用途和预算，再判断城市/区域。', '我整理了一个对照表，可以先帮你判断方向。'],
        'next_actions': ['主页短链已支持自动转换；若拿不到最近三条，在 Render 添加 DOUYIN_WEB_COOKIE。', '给重点竞品补 1-3 条具体视频链接，系统可立即分析。', '后续企业认证后替换为巨量/抖音/百度 API。'],
    }


async def analyze_heat_items(settings: Settings, top_items: List[Dict[str, Any]], keywords: List[str]) -> Dict[str, Any]:
    if not top_items:
        return _fallback_analysis([])
    if os.getenv('HEAT_RADAR_AI_ANALYSIS', '').strip().lower() not in {'1', 'true', 'yes', 'on'}:
        return _fallback_analysis(top_items)
    lines = []
    for i, item in enumerate(top_items[:12], start=1):
        lines.append(
            f"{i}. 平台：{item.get('platform')}｜账号：{item.get('account_name')}｜标题：{item.get('title')}｜"
            f"赞{item.get('like_count')} 评论{item.get('comment_count')} 收藏{item.get('favorite_count')} 分享{item.get('share_count')}｜链接：{item.get('url')}"
        )
    system = '你是中国社媒获客热度雷达分析师。只基于已采集到的真实数据分析，不要编造数据。输出严格 JSON。'
    user = f"""
监控关键词：{', '.join(keywords[:30]) or '未填写'}
今日/最近真实采集内容：
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

    deduped: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for acc in accounts:
        key = str(acc.get('url') or acc.get('name') or acc.get('notes') or '').strip()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(acc)

    if not deduped:
        warnings.append('没有可采集的账号/链接。请先添加竞品账号主页、具体公开视频链接，或在备注里粘贴真实数据行。')

    collected: List[Dict[str, Any]] = []
    for acc in deduped[:20]:
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

    top_items, top_mode, fallback_used = _pick_top_items(collected)
    if not top_items:
        recent = _recent_real_items(memory, 3)
        if recent:
            top_items = recent
            top_mode = 'recent_stored_fallback'
            fallback_used = True
            warnings.append('本轮没有采到新内容，已回看历史真实留存 3 条。')
        else:
            warnings.append('本轮没有真实内容可展示：请补具体视频/笔记链接，或在 Render 添加 DOUYIN_WEB_COOKIE 后重试主页采集。')
    elif top_mode == 'recent3_no_today':
        warnings.append('今天没有新视频/新笔记，已自动回看最近 3 条。')
    elif top_mode == 'resolved_homepage_no_posts':
        warnings.append('主页链接已转换/留存，但公开接口没有返回最近三条；建议添加 DOUYIN_WEB_COOKIE 或补具体视频链接。')

    analysis = await analyze_heat_items(settings, top_items, keywords)

    saved_count = 0
    if bool(getattr(req, 'save_to_memory', True)):
        for item in collected:
            try:
                memory.insert('heat_radar_items', item)
                saved_count += 1
            except Exception as exc:
                warnings.append(f'保存热度内容失败：{str(exc)[:160]}')
        try:
            memory.insert('heat_daily_top3', {
                'date': today_key(),
                'summary': analysis.get('summary', ''),
                'top_items': top_items,
                'analysis': analysis,
                'keywords': keywords,
                'accounts_count': len(deduped),
                'top_mode': top_mode,
                'fallback_used': fallback_used,
                'raw': {'warnings': warnings[:80]},
            })
            memory.save_learning_event({
                'event_type': 'heat_radar_public_crawl',
                'title': f'{today_key()} 自动热度雷达',
                'payload': {'top_items': top_items, 'analysis': analysis, 'warnings': warnings[:80], 'top_mode': top_mode},
            })
        except Exception as exc:
            warnings.append(f'保存每日 Top3 失败：{str(exc)[:160]}')

    return {
        'ok': True,
        'source_mode': 'douyin_homepage_converter_public_recent3_without_enterprise_api',
        'accounts_count': len(deduped),
        'collected_count': len(collected),
        'saved_count': saved_count,
        'top_items': top_items,
        'analysis': analysis,
        'warnings': warnings[:80],
        'next_actions': analysis.get('next_actions') or _fallback_analysis(top_items).get('next_actions'),
        'top_mode': top_mode,
        'fallback_used': fallback_used,
    }
