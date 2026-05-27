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
    """Return a Netscape cookie file path for Douyin collectors.

    Priority:
    1) DOUYIN_COOKIE_FILE / DOUYIN_WEB_COOKIE_FILE / HEAT_RADAR_DOUYIN_COOKIE_FILE / COLLECTOR_COOKIE_FILE
       pointing to a Netscape cookies.txt file.
    2) DOUYIN_WEB_COOKIE / HEAT_RADAR_DOUYIN_COOKIE raw browser Cookie header.

    Without a valid logged-in cookie Douyin often returns a login/verification page,
    so a profile URL may only resolve to the homepage and not its recent videos.
    """
    for name in ['DOUYIN_COOKIE_FILE', 'DOUYIN_WEB_COOKIE_FILE', 'HEAT_RADAR_DOUYIN_COOKIE_FILE', 'COLLECTOR_COOKIE_FILE']:
        fp = os.getenv(name, '').strip()
        if fp and os.path.exists(fp):
            return fp

    raw = os.getenv('DOUYIN_WEB_COOKIE', '').strip() or os.getenv('HEAT_RADAR_DOUYIN_COOKIE', '').strip()
    if not raw:
        return ''
    try:
        # Allow users to paste a small Netscape cookie file directly as an env var.
        if '\t' in raw and '.douyin.com' in raw:
            path = os.path.join(tempfile.gettempdir(), 'douyin_web_cookie_netscape.txt')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(raw if raw.endswith('\n') else raw + '\n')
            return path

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
            lines.append(f'.iesdouyin.com\tTRUE\t/\tFALSE\t2147483647\t{name}\t{value}')
        if len(lines) <= 1:
            return ''
        path = os.path.join(tempfile.gettempdir(), 'douyin_web_cookie.txt')
        with open(path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')
        return path
    except Exception:
        return ''


def _has_douyin_cookie() -> bool:
    return bool(_douyin_cookie_file_from_env())


def _douyin_blocked_hint(text: str) -> str:
    blob = (text or '').lower()
    if any(x in blob for x in ['captcha', 'verify', '验证', '登录', 'login', 'fresh cookies', 'cookies', '安全验证']):
        return '抖音返回登录/验证页，主页最近视频需要配置 DOUYIN_WEB_COOKIE 或 DOUYIN_COOKIE_FILE。'
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
    """Run yt-dlp in-process, profile-first.

    For Douyin homepages, flat extraction can sometimes return only the profile
    itself. We therefore run a playlist/full metadata pass first with cookies
    when available, capped to 3-6 entries and skip_download=True.
    """
    from yt_dlp import YoutubeDL  # type: ignore

    cookiefile = _douyin_cookie_file_from_env()
    base_opts: Dict[str, Any] = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'ignoreerrors': True,
        'noplaylist': False,
        'playlistend': max(3, min(int(limit or 3), 6)),
        'socket_timeout': int(os.getenv('HEAT_RADAR_YTDLP_SOCKET_TIMEOUT', '12')),
        'retries': 1,
        'fragment_retries': 0,
        'nocheckcertificate': True,
        'http_headers': {k: v for k, v in headers.items() if v},
    }
    if cookiefile:
        base_opts['cookiefile'] = cookiefile

    attempts = []
    full_opts = dict(base_opts)
    full_opts['extract_flat'] = False
    attempts.append(full_opts)
    flat_opts = dict(base_opts)
    flat_opts['extract_flat'] = 'in_playlist'
    attempts.append(flat_opts)

    last: Dict[str, Any] = {}
    for opts in attempts:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False) or {}
        last = info
        entries = _flatten_ytdlp_entries(info, max(3, limit))
        if any(_extract_video_id(str(e.get('webpage_url') or e.get('url') or e.get('id') or '')) for e in entries if isinstance(e, dict)):
            return info
    return last

def _is_douyin_profile_url(url: str) -> bool:
    value = (url or '').lower()
    return '/user/' in value or 'douyin.com/user' in value or 'profile' in value


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

    # 关键修复：yt-dlp 在未登录/触发验证时，经常把“主页本身”当成 1 条结果返回。
    # 这种结果没有 /video/{aweme_id}，不能冒充最近视频，否则页面就会一直显示账号卡片。
    if 'douyin' in (raw_url + source_url).lower() and not _extract_video_id(raw_url):
        if _is_douyin_profile_url(raw_url) or _is_douyin_profile_url(source_url) or 'user' in str(entry.get('extractor_key') or '').lower():
            return None
    if 'profile_recent3' in source_mode and not _extract_video_id(raw_url):
        return None
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
        msg = str(exc)[:260]
        hint = _douyin_blocked_hint(msg)
        if hint:
            warnings.append(hint)
        warnings.append(f'yt-dlp 抖音采集失败，继续使用网页/API兜底：{msg}')
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
        candidates.extend(re.findall(r'"secUid"\s*:\s*"([^"]+)"', text))
        candidates.extend(re.findall(r'"sec_user_id"\s*:\s*"([^"]+)"', text))
        candidates.extend(re.findall(r'"secUserId"\s*:\s*"([^"]+)"', text))
        candidates.extend(re.findall(r"authorSecId[\"']?\s*[:=]\s*[\"']([^\"']+)", text))
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
    text = html_text or ''
    for regex in [RENDER_DATA_RE, JSON_STATE_RE]:
        for m in regex.finditer(text):
            raw = html.unescape(m.group(1) or '').strip()
            if not raw:
                continue
            candidates = [raw, unquote(raw)]
            try:
                candidates.append(unquote(unquote(raw)))
            except Exception:
                pass
            for candidate in candidates:
                try:
                    payloads.append(json.loads(candidate))
                    break
                except Exception:
                    continue

    for pattern in [
        r'window\.__INITIAL_STATE__\s*=\s*({.*?})\s*</script>',
        r'window\.__UNIVERSAL_DATA_FOR_REHYDRATION__\s*=\s*({.*?})\s*</script>',
        r'window\._ROUTER_DATA\s*=\s*({.*?})\s*</script>',
    ]:
        for m in re.finditer(pattern, text, re.I | re.S):
            raw = html.unescape(m.group(1) or '').strip()
            if not raw:
                continue
            try:
                payloads.append(json.loads(raw))
            except Exception:
                continue
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
            hint = _douyin_blocked_hint(res.text or '')
            if hint:
                warnings.append(hint)
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


def _looks_like_douyin_gate(html_text: str) -> bool:
    text = (html_text or '')[:5000].lower()
    return any(x in text for x in ['captcha', 'verify', '验证', '登录后查看', '安全验证', '访问过于频繁'])


def _douyin_profile_extract_urls_from_html(html_text: str, limit: int) -> List[str]:
    ids = _extract_aweme_ids_from_text(html_text or '', max(6, limit * 2))
    urls: List[str] = []
    for vid in ids:
        url = f'https://www.douyin.com/video/{vid}'
        if url not in urls:
            urls.append(url)
        if len(urls) >= limit:
            break
    return urls


async def _collect_douyin_profile_http(settings: Settings, account: Dict[str, Any], input_url: str, warnings: List[str], limit: int) -> List[Dict[str, Any]]:
    final_url, html_text = await _fetch_html(settings, input_url, warnings)
    if not html_text:
        return []
    if _looks_like_douyin_gate(html_text):
        warnings.append('抖音返回登录/验证页：Cookie 可能过期，或该环境触发验证。')
        return []

    render_items = _items_from_render_data(account, _parse_render_json(html_text), max(3, limit))
    if render_items:
        warnings.append(f'已从抖音主页前端数据识别 {len(render_items)} 条视频。')
        return render_items[:limit]

    sec_uid = _extract_sec_uid(final_url, html_text)
    if sec_uid:
        api_items = await _fetch_douyin_post_api(settings, sec_uid, account, warnings, max(3, limit))
        if api_items:
            warnings.append(f'已通过抖音主页接口获取 {len(api_items)} 条最近视频。')
            return api_items[:limit]

    urls = _douyin_profile_extract_urls_from_html(html_text, max(3, limit))
    html_items: List[Dict[str, Any]] = []
    for url in urls:
        vid = _extract_video_id(url)
        detail_items = await _fetch_douyin_detail(settings, vid, account, warnings) if vid else []
        if detail_items:
            html_items.extend(detail_items)
        else:
            html_items.append(_make_item(account, title=f'{account.get("name") or "抖音账号"} 最近视频 {vid}', url=url, description='从抖音主页 HTML 识别到视频链接。', source_mode='douyin_profile_html_link'))
        if len(html_items) >= limit:
            break
    if html_items:
        warnings.append(f'已从抖音主页链接区域识别 {len(html_items)} 条视频。')
        return _dedupe_items(html_items)[:limit]

    if sec_uid:
        warnings.append('已识别账号 sec_uid，但主页接口没有返回视频列表；Cookie 可能过期或触发验证。')
    else:
        warnings.append('已读取抖音主页，但未识别到 sec_uid 或视频链接。')
    return []


async def _collect_douyin_url(settings: Settings, account: Dict[str, Any], input_url: str, warnings: List[str], limit: int) -> List[Dict[str, Any]]:
    final_url = await _resolve_url(settings, input_url, warnings)
    if final_url != input_url:
        warnings.append(f'短链已转换：{input_url} → {final_url}')

    # 抖音主页：不要先走 yt-dlp。先用 Cookie 读取主页前端数据/API，等于“看页面里有哪些视频”。
    if _is_douyin_profile_url(final_url or input_url):
        profile_items = await _collect_douyin_profile_http(settings, account, final_url or input_url, warnings, max(3, limit))
        if profile_items:
            return profile_items[:limit]
        if os.getenv('HEAT_RADAR_PROFILE_YTDLP_FALLBACK', '').strip().lower() in {'1', 'true', 'yes', 'on'}:
            ytdlp_items = await _collect_douyin_with_ytdlp(settings, account, final_url or input_url, warnings, max(3, limit))
            if ytdlp_items:
                return ytdlp_items[:limit]
        warnings.append('抖音主页本轮没有拿到视频列表；保留现有热点，不清空页面。')
        return []

    # 具体视频链接：先用轻量详情接口；失败后再用 yt-dlp/HTML 兜底。
    video_id = _extract_video_id(final_url)
    if video_id:
        items = await _fetch_douyin_detail(settings, video_id, account, warnings)
        if items:
            return items[:limit]

    ytdlp_items = await _collect_douyin_with_ytdlp(settings, account, final_url or input_url, warnings, max(3, limit))
    if ytdlp_items:
        return ytdlp_items[:limit]

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
            html_items.append(_make_item(account, title=f'{account.get("name") or "抖音账号"} 视频 {vid}', url=f'https://www.douyin.com/video/{vid}', description='从页面 HTML 识别到视频 ID，但公开详情接口未返回热度指标。', source_mode='douyin_html_aweme_id'))
    if html_items:
        return _dedupe_items(html_items)[:limit]

    title, desc = _title_from_html(html_text)
    return [_make_item(
        account,
        title=title or str(account.get('name') or '抖音公开链接已留存'),
        url=final_url,
        description=desc or '公开链接已留存，但没有识别到视频 ID。',
        source_mode='douyin_public_url_observation',
        raw={'final_url': final_url, 'cookie_configured': _has_douyin_cookie()},
    )]


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
            lower_url = url.lower()
            # 抖音主页不再生成“账号主页已留存”卡片，避免冒充最近三条。
            # 只有具体视频/笔记链接才作为真实内容进入热度池。
            is_douyin_home = ('douyin.com' in lower_url and '/user/' in lower_url) or ('v.douyin.com' in lower_url and '/video/' not in lower_url)
            if not is_douyin_home:
                mode = 'account_content_url' if any(x in lower_url for x in ['/video/', '/note/', 'v.douyin.com', 'xhslink.com']) else 'account_homepage_observation'
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
    real_posts = [x for x in collected if 'observation' not in str(x.get('source_mode') or '').lower()]
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
        'summary': '热度雷达只展示真实采集或真实留存内容：今天没有新内容时，自动回看最近 3 条。',
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
        'douyin_cookie_configured': _has_douyin_cookie(),
        'requires_cookie': any('DOUYIN_WEB_COOKIE' in w or '登录 Cookie' in w or '验证' in w for w in warnings),
    }



def _safe_list(value: Any, fallback: List[str] | None = None, limit: int = 8) -> List[str]:
    if isinstance(value, list):
        items = value
    elif isinstance(value, str):
        items = re.split(r'[\n；;]+', value)
    else:
        items = []
    out: List[str] = []
    for item in items:
        text = _clean_text(item, 240)
        if text and text not in out:
            out.append(text)
        if len(out) >= limit:
            break
    return out or (fallback or [])


def _heat_items_brief(items: List[Dict[str, Any]]) -> str:
    rows: List[str] = []
    for idx, item in enumerate(items[:8], 1):
        title = _clean_text(item.get('topic') or item.get('title') or '未命名热度', 180)
        platform = item.get('platform', '')
        account = item.get('account_name', '')
        intent = _clean_text(item.get('intent') or item.get('customer_intent') or '', 220)
        signal = _clean_text(item.get('signal') or item.get('description') or '', 400)
        score = item.get('score') or item.get('heat_score') or 0
        url = item.get('source_url') or item.get('url') or ''
        evidence = []
        if score:
            evidence.append(f'热度分 {score}')
        for label, key in [('赞', 'like_count'), ('评', 'comment_count'), ('藏', 'favorite_count'), ('转', 'share_count'), ('播', 'view_count')]:
            value = item.get(key)
            if value:
                evidence.append(f'{label}{value}')
        rows.append(
            f"{idx}. 【热点来源】平台:{platform}｜账号:{account}｜标题:{title}\n"
            f"   【热度证据】{' / '.join(evidence) or signal or '已采集到公开内容'}\n"
            f"   【客户意图】{intent or '待判断'}\n"
            f"   【原始信号】{signal}\n"
            f"   【链接】{url}"
        )
    return '\n'.join(rows)


def _fallback_rewrite_payload(req: Any, reason: str = '') -> Dict[str, Any]:
    items = list(getattr(req, 'heat_items', []) or [])
    lead_magnet_default = str(getattr(req, 'lead_magnet', '') or '《马来西亚置业避坑报告》')
    audience_default = str(getattr(req, 'audience', '') or '有马来西亚置业、第二家园、子女教育或资产配置需求的华人家庭')
    conversion_default = str(getattr(req, 'conversion_goal', '') or f'私信领取{lead_magnet_default}，进入顾问需求筛选')
    source_evidence: List[str] = []
    variants: List[Dict[str, Any]] = []
    source_items = items[:3] or [{'topic': getattr(req, 'industry', '') or '马来西亚置业避坑', 'intent': '资格/预算/流程判断', 'signal': '行业档案通用热点'}]
    for idx, first in enumerate(source_items, 1):
        topic = str(first.get('topic') or first.get('title') or getattr(req, 'industry', '') or '马来西亚置业避坑')
        intent = str(first.get('intent') or '资格/预算/流程判断')
        lead_magnet = str(first.get('lead_magnet') or lead_magnet_default)
        signal = str(first.get('signal') or first.get('description') or '')
        score = first.get('score') or first.get('heat_score') or 0
        url = str(first.get('source_url') or first.get('url') or '')
        evidence_line = f'{idx}. {first.get("platform", "热度来源")} / {first.get("account_name", "公开来源")} / {topic} / 热度{score} / {signal[:120]} / {url}'
        source_evidence.append(evidence_line)
        hook = f'刷到“{topic}”这种内容，先别急着跟风，真正要看的是这 3 个判断。'
        script = (
            f'{hook}\n'
            f'第一，先确认它对应的真实需求是什么。很多人看热闹，其实背后问的是“{intent}”。\n'
            f'第二，不要只学标题，要把问题换成自己的判断框架：目的、预算、城市、身份和长期持有成本。\n'
            f'第三，结尾不要硬卖项目，要给用户一个能继续了解的入口。比如先领一份{lead_magnet}，再判断自己适不适合看房。\n'
            f'所以如果你也在关注“{topic}”，可以先私信我“报告”，我把这份资料发你，先把条件和常见坑看清楚。'
        )
        variants.append({
            'source_topic': topic,
            'target_audience': audience_default[:260],
            'customer_intent': intent,
            'content_goal': '把采集到的热度话题改写成原创解释型内容，建立专业信任',
            'conversion_goal': conversion_default,
            'lead_magnet': lead_magnet,
            'title': f'{topic}，别只看热闹，先看这 3 点',
            'hook': hook,
            'script': script,
            'caption': f'这条是根据今天热度雷达里的“{topic}”重新做的原创解释，不照搬内容，只拆解背后的客户问题。需要{lead_magnet}，私信“报告”。',
            'tags': ['马来西亚房产', '第二家园', '海外置业', '买房避坑'],
            'shots': ['展示热度关键词卡片', '顾问正面口播解释', '三点判断框架卡片', '结尾展示资料包领取提示'],
            'imitation_notes': ['参考热点的提问角度，不复制标题和原文', '保留“问题入口 + 三点判断 + 资料承接”的结构'],
            'differentiation': ['加入自己的资格判断框架', '用资料包承接而不是硬广卖项目'],
            'risk_notes': ['不承诺收益', '不搬运竞品素材', '不暗示一定能办理成功'],
            'source_evidence': [evidence_line],
            'adaptation_map': [f'热点问题：{topic}', f'改写角度：把围观热度转成顾问判断', f'承接方式：{lead_magnet}'],
        })
    return {
        'overview': '已按当前热度雷达内容生成规则版原创仿写；每条稿子都绑定了采集到的热点来源，不再空口改写。',
        'chosen_target': audience_default[:260],
        'target_reason': f'当前热度集中在“{source_items[0].get("topic") or source_items[0].get("title") or "行业热点"}”，适合用问题解释和资料包承接筛选客户。',
        'content_objective': '从真实热点切入，做原创解释内容，引导用户领取资料包并进入咨询。',
        'primary_intent': str(source_items[0].get('intent') or '资格/预算/流程判断'),
        'lead_magnet': lead_magnet_default,
        'rewrite_strategy': ['先引用热度雷达里的真实热点作为选题依据', '只迁移结构和客户问题，不复制原文/画面', '用自己的顾问判断框架重写', '结尾用网页资料包承接'],
        'source_evidence': source_evidence,
        'variants': variants[:3],
        'publish_checklist': ['标题必须原创', '口播里不要说“抄/仿某账号”', '评论区置顶资料关键词', '发布后把评论问题回流热度雷达'],
        'warnings': [reason] if reason else [],
    }


async def generate_heat_radar_rewrite(settings: Settings, req: Any) -> Dict[str, Any]:
    items = list(getattr(req, 'heat_items', []) or [])
    if not items:
        return _fallback_rewrite_payload(req, '当前没有热度内容，已按行业档案生成通用方案。')

    heat_brief = _heat_items_brief(items)
    lead_magnet = getattr(req, 'lead_magnet', '') or '网页资料包/避坑报告/预算测算表'
    system = (
        '你是短视频增长编导和获客策略负责人。你的任务是读取“当前热度雷达”的真实内容，'
        '判断目标客户和客户意图，再把高热话题改写成原创口播/图文。必须只迁移结构和选题，不照抄原文、不搬运素材。'
        '输出严格 JSON。'
    )
    user = f'''
当前业务：{getattr(req, 'industry', '') or '马来西亚房产置业 / 第二家园 / 国际学校'}
目标客户档案：{getattr(req, 'audience', '') or '华人家庭、企业主、高净值家庭、留学家庭、养老度假人群'}
核心卖点/行业档案：{getattr(req, 'selling_points', '')[:3000]}
转化目标：{getattr(req, 'conversion_goal', '') or '私信咨询 / 领取资料包 / 加微信顾问沟通'}
承接资料包：{lead_magnet}
内容风格：{getattr(req, 'style', '') or '老板口播、真实可信、强钩子、强转化'}
目标时长：{getattr(req, 'target_duration_seconds', 35)} 秒
平台：{getattr(req, 'platform', 'douyin')}

当前热度雷达 Top 内容：
{heat_brief}

请输出 JSON：
{{
  "overview":"一句话说明这批热度该怎么跟",
  "chosen_target":"本次最应该打的目标客户",
  "target_reason":"为什么选这个目标",
  "content_objective":"这条内容要完成什么转化任务",
  "primary_intent":"客户核心意图",
  "lead_magnet":"建议承接资料包",
  "rewrite_strategy":["仿写策略/结构迁移点"],
  "source_evidence":["用于改写的热点依据：平台/账号/标题/热度/链接"],
  "variants":[{{
    "source_topic":"参考的热度话题",
    "target_audience":"这条内容打谁",
    "customer_intent":"这群人为什么会被这条内容吸引",
    "content_goal":"内容目标",
    "conversion_goal":"转化目标",
    "lead_magnet":"承接资料包",
    "title":"原创标题",
    "hook":"前三秒钩子",
    "script":"完整口播稿，适合 30-45 秒，强钩子，中文自然口语，不照抄原内容",
    "caption":"发布简介",
    "tags":["话题标签"],
    "shots":["镜头/图文页建议"],
    "imitation_notes":["参考结构，不复制内容"],
    "differentiation":["我们和竞品不同的角度"],
    "risk_notes":["合规/表达风险"],
    "source_evidence":["这条稿子参考了哪条热度内容，必须包含标题/平台/热度信号"],
    "adaptation_map":["原热点的钩子是什么", "我们改成什么原创角度", "用哪个资料承接"]
  }}],
  "publish_checklist":["发布前检查事项"],
  "warnings":["注意事项"]
}}

要求：
1. variants 输出 2-3 条，第一条最推荐。
2. 不要出现“仿某某账号”这种公开表达，内部可以叫参考结构。
3. 目标一定要明确到人群和场景，例如“关注子女教育和第二家园身份的华人家庭”。
4. 结尾必须用资料包/网页报告承接。
5. 不承诺收益、不制造移民成功承诺。
'''.strip()
    try:
        payload = await _chat_json(settings, system, user, temperature=0.72, timeout=90)
        variants = payload.get('variants') if isinstance(payload, dict) else []
        if not isinstance(variants, list) or not variants:
            raise ValueError('empty variants')
        payload['rewrite_strategy'] = _safe_list(payload.get('rewrite_strategy'), ['保留热度问题入口', '换成自己的顾问判断框架', '用资料包承接'], 8)
        payload['source_evidence'] = _safe_list(payload.get('source_evidence'), _heat_items_brief(items).split('\n')[:6], 8)
        payload['publish_checklist'] = _safe_list(payload.get('publish_checklist'), ['标题原创', '结尾引导资料包', '评论区置顶关键词'], 8)
        payload['warnings'] = _safe_list(payload.get('warnings'), [], 5)
        cleaned_variants = []
        for v in variants[:3]:
            if not isinstance(v, dict):
                continue
            v['tags'] = _safe_list(v.get('tags'), ['马来西亚房产', '第二家园', '海外置业'], 8)
            v['shots'] = _safe_list(v.get('shots'), ['顾问正面口播', '资料包画面', '关键词卡片'], 8)
            v['imitation_notes'] = _safe_list(v.get('imitation_notes'), ['只参考结构，不复制原文'], 6)
            v['differentiation'] = _safe_list(v.get('differentiation'), ['加入自己的顾问判断和资料包承接'], 6)
            v['risk_notes'] = _safe_list(v.get('risk_notes'), ['不承诺收益，不搬运竞品素材'], 6)
            v['source_evidence'] = _safe_list(v.get('source_evidence'), [_heat_items_brief(items[:1])], 4)
            v['adaptation_map'] = _safe_list(v.get('adaptation_map'), ['热点问题 → 原创判断框架', '竞品结构 → 自己的顾问视角', '围观流量 → 资料包承接'], 6)
            cleaned_variants.append(v)
        payload['variants'] = cleaned_variants or _fallback_rewrite_payload(req).get('variants')
        return payload
    except Exception as exc:
        return _fallback_rewrite_payload(req, f'AI 仿写失败，已使用规则版：{str(exc)[:240]}')


# ---------------------------------------------------------------------------
# OpenClaw / external browser-agent ingestion
# ---------------------------------------------------------------------------

def _parse_dt(value: Any) -> datetime | None:
    text = str(value or '').strip()
    if not text:
        return None
    try:
        if text.endswith('Z'):
            text = text[:-1] + '+00:00'
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=CN_TZ)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass
    for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d', '%Y/%m/%d %H:%M', '%Y/%m/%d']:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=CN_TZ).astimezone(timezone.utc)
        except Exception:
            continue
    return None


def _days_since(value: Any) -> int:
    dt = _parse_dt(value)
    if not dt:
        return 9999
    return max(0, int((datetime.now(timezone.utc) - dt).total_seconds() // 86400))


def _freshness_score(days: int, max_stale_days: int = 90) -> int:
    if days <= 3:
        return 30
    if days <= 7:
        return 27
    if days <= 14:
        return 22
    if days <= 30:
        return 16
    if days <= 60:
        return 9
    if days <= max_stale_days:
        return 4
    return -18


def _relevance_score(text: str, keywords: List[str]) -> int:
    blob = (text or '').lower()
    keys = [str(k or '').strip().lower() for k in keywords if str(k or '').strip()]
    if not keys:
        keys = ['马来西亚', '大马', '吉隆坡', '新山', '槟城', '第二家园', 'mm2h', '房产', '买房', '置业', '生活成本', '国际学校', '陪读', '养老', '医疗', '交通', '华人区']
    hits = [k for k in keys if k and k in blob]
    score = min(22, len(hits) * 5)
    if any(k in blob for k in ['马来西亚', '大马', '吉隆坡', '新山', '槟城', 'mm2h', '第二家园']):
        score += 8
    if any(k in blob for k in ['买房', '房产', '置业', '投资', '税费', '流程', '预算', '租金', '回报']):
        score += 8
    # 买房客户会关心的不只是房价，生活、教育、医疗、交通同样可作为收录依据。
    if any(k in blob for k in ['生活', '生活成本', '超市', '买菜', '交通', '地铁', '通勤', '医疗', '医院', '教育', '学校', '国际学校', '陪读', '养老', '安全', '华人', '社区', '签证', '身份']):
        score += 7
    return max(0, min(35, score))


def _intent_score(text: str) -> int:
    blob = (text or '').lower()
    groups = [
        ['预算', '价格', '房价', '税费', '贷款', '租金', '回报'],
        ['教育', '国际学校', '陪读', '孩子', '上学'],
        ['医疗', '养老', '医院', '保险'],
        ['生活成本', '买菜', '超市', '交通', '通勤', '安全', '华人区', '社区'],
        ['第二家园', 'mm2h', '签证', '身份', '移民'],
        ['流程', '避坑', '注意', '真实', '实拍', '经验'],
    ]
    hits = sum(1 for group in groups if any(k in blob for k in group))
    return max(0, min(25, hits * 5))


def _rewrite_value_score(text: str, items: List[Dict[str, Any]]) -> int:
    blob = (text or '').lower()
    value = 0
    if any(k in blob for k in ['为什么', '避坑', '真实', '成本', '流程', '对比', '经验', '适合', '不适合']):
        value += 4
    if any(item.get('is_pinned') or item.get('raw', {}).get('is_pinned') for item in items):
        value += 3
    if len(items) >= 3:
        value += 3
    return max(0, min(10, value))


def _account_type_from_text(text: str) -> str:
    blob = (text or '').lower()
    if any(k in blob for k in ['房产', '买房', '置业', '楼盘', '租金', '回报']):
        return '马来西亚房产/置业'
    if any(k in blob for k in ['第二家园', 'mm2h', '签证', '身份', '移民']):
        return '第二家园/身份政策'
    if any(k in blob for k in ['国际学校', '陪读', '教育', '孩子', '上学']):
        return '教育/陪读生活'
    if any(k in blob for k in ['医疗', '养老', '医院']):
        return '医疗/养老生活'
    if any(k in blob for k in ['生活', '买菜', '超市', '交通', '通勤', '华人', '社区', '安全']):
        return '马来西亚生活方式'
    return '泛生活/待观察'


def _normalize_openclaw_item(raw: Dict[str, Any], fallback_account: Dict[str, Any] | None = None, source_name: str = 'openclaw') -> Dict[str, Any]:
    fallback_account = fallback_account or {}
    tags = raw.get('tags') or fallback_account.get('tags') or []
    if isinstance(tags, str):
        tags = _split_keywords(tags, 12)
    item = {
        'id': str(raw.get('id') or f"heat_{source_name}_{uuid.uuid4().hex[:12]}"),
        'date': today_key(),
        'platform': _clean_text(raw.get('platform') or fallback_account.get('platform') or _platform_from_url(str(raw.get('url') or fallback_account.get('url') or ''), '公开平台'), 40),
        'account_id': str(raw.get('account_id') or fallback_account.get('id') or ''),
        'account_name': _clean_text(raw.get('account_name') or fallback_account.get('name') or '未命名账号', 80),
        'title': _clean_text(raw.get('title') or raw.get('topic') or raw.get('desc') or '未命名内容', 220),
        'description': _clean_text(raw.get('description') or raw.get('desc') or '', 800),
        'url': str(raw.get('url') or raw.get('source_url') or '').strip(),
        'published_at': str(raw.get('published_at') or raw.get('create_time') or raw.get('time') or ''),
        'collected_at': str(raw.get('collected_at') or now_iso()),
        'like_count': _num(raw.get('like_count') or raw.get('likes') or raw.get('digg_count') or raw.get('赞')),
        'comment_count': _num(raw.get('comment_count') or raw.get('comments') or raw.get('评论')),
        'favorite_count': _num(raw.get('favorite_count') or raw.get('collect_count') or raw.get('favorites') or raw.get('收藏')),
        'share_count': _num(raw.get('share_count') or raw.get('shares') or raw.get('分享')),
        'view_count': _num(raw.get('view_count') or raw.get('play_count') or raw.get('views') or raw.get('播放')),
        'keyword': ','.join(_split_keywords(raw.get('keyword') or raw.get('keywords') or tags, 8)),
        'tags': tags[:12] if isinstance(tags, list) else [],
        'thumbnail_url': str(raw.get('thumbnail_url') or raw.get('cover') or ''),
        'is_pinned': bool(raw.get('is_pinned') or raw.get('pinned') or raw.get('is_top')),
        'source_mode': f'{source_name}_automation',
        'raw': raw,
        'warnings': [],
    }
    item['heat_score'] = heat_score(item)
    return item


def _account_key(account: Dict[str, Any]) -> str:
    return str(account.get('url') or account.get('account_url') or account.get('name') or account.get('account_name') or '').strip().lower()


def _account_items_for_review(memory: MemoryStore, account: Dict[str, Any], extra_items: List[Dict[str, Any]] | None = None) -> List[Dict[str, Any]]:
    extra_items = extra_items or []
    name = str(account.get('name') or account.get('account_name') or '').strip()
    url = str(account.get('url') or account.get('account_url') or '').strip()
    aid = str(account.get('id') or account.get('account_id') or '').strip()
    rows: List[Dict[str, Any]] = []
    for item in extra_items:
        if aid and str(item.get('account_id') or '') == aid:
            rows.append(item)
        elif name and str(item.get('account_name') or '').strip() == name:
            rows.append(item)
        elif url and (str(item.get('account_url') or '') == url or str(item.get('raw', {}).get('account_url') or '') == url):
            rows.append(item)
    try:
        for item in memory.list('heat_radar_items', limit=300):
            if aid and str(item.get('account_id') or '') == aid:
                rows.append(item)
            elif name and str(item.get('account_name') or '').strip() == name:
                rows.append(item)
            elif url and (str(item.get('url') or '').startswith(url) or str(item.get('raw', {}).get('account_url') or '') == url):
                rows.append(item)
    except Exception:
        pass
    return _dedupe_items(rows)


def _review_account_value(account: Dict[str, Any], items: List[Dict[str, Any]], keywords: List[str], max_stale_days: int = 90, accept_min_score: int = 72) -> Dict[str, Any]:
    title_blob = ' '.join([
        str(account.get('name') or account.get('account_name') or ''),
        str(account.get('tags') or ''),
        str(account.get('notes') or ''),
        ' '.join(str(x.get('title') or '') for x in items[:10]),
        ' '.join(str(x.get('description') or '') for x in items[:10]),
        ' '.join(str(x.get('raw', {}).get('analysis_summary') or '') for x in items[:10]),
    ])
    latest = ''
    latest_dt: datetime | None = None
    for item in items:
        if item.get('is_pinned') or item.get('raw', {}).get('is_pinned'):
            continue
        dt = _parse_dt(item.get('published_at') or item.get('collected_at') or item.get('date'))
        if dt and (latest_dt is None or dt > latest_dt):
            latest_dt = dt
            latest = dt.isoformat()
    if not latest and account.get('last_post_at'):
        dt = _parse_dt(account.get('last_post_at'))
        if dt:
            latest_dt = dt
            latest = dt.isoformat()
    days = _days_since(latest) if latest else 9999

    relevance = _relevance_score(title_blob, keywords)                   # 35%
    intent_part = _intent_score(title_blob)                              # 25%
    freshness_raw = _freshness_score(days, max_stale_days)
    freshness = max(0, min(20, int(freshness_raw * 20 / 30)))            # 20%
    top_heat = sum(sorted([int(x.get('heat_score') or heat_score(x)) for x in items], reverse=True)[:3])
    heat_part = min(10, int(top_heat / 450)) if top_heat else 0          # 10%
    rewrite_part = _rewrite_value_score(title_blob, items)               # 10%
    score = max(0, min(100, relevance + intent_part + freshness + heat_part + rewrite_part))

    account_type = _account_type_from_text(title_blob)
    target_value = '能补充买房客户关心的生活、教育、医疗、交通或身份信息。' if account_type != '泛生活/待观察' else '相关性暂不稳定，需要观察是否能转成马来西亚置业内容。'
    intents = []
    if any(k in title_blob for k in ['生活', '买菜', '交通', '医疗', '教育', '养老', '华人']):
        intents.append('了解马来西亚真实生活环境')
    if any(k in title_blob for k in ['房产', '买房', '置业', '租金', '预算']):
        intents.append('判断买房预算、区域和回报')
    if any(k in title_blob.lower() for k in ['mm2h', '第二家园', '签证', '身份']):
        intents.append('理解第二家园/身份政策')
    intents = intents or ['判断账号是否适合长期观察']
    opportunities = [
        f'{account_type}：把账号内容转成买房前顾虑清单',
        '从真实生活体验切入，再承接马来西亚置业资料包',
    ]
    risk_notes = []
    if heat_part <= 2:
        risk_notes.append('互动热度一般，不能只按点赞判断，要看内容是否能回答客户顾虑。')
    if account_type == '泛生活/待观察':
        risk_notes.append('账号不是直接房产号，先观察内容是否能稳定关联马来西亚生活/置业。')

    if days > max_stale_days * 2 and len(items) == 0:
        decision = 'archive'
        reason = f'超过 {max_stale_days * 2} 天没有可用新内容，也没有历史热度记录。'
        next_action = '暂停自动采集；保留档案但不占用每日采集额度。'
    elif days > max_stale_days and score < 58:
        decision = 'archive'
        reason = f'最近内容距今约 {days} 天，且相关性/客户顾虑价值不足。'
        next_action = '移入观察/归档；以后有新视频链接再恢复。'
    elif score >= accept_min_score:
        decision = 'accept'
        reason = '账号与马来西亚置业/生活顾虑相关，且近期更新或置顶内容有长期参考价值。'
        next_action = '加入固定账号库；每天采置顶视频和近期内容。'
    elif score >= 52:
        decision = 'watch'
        reason = '有一定目标客户参考价值，但稳定性或内容垂直度还需观察。'
        next_action = '加入观察池；连续采集到相关视频后再固定。'
    else:
        decision = 'reject'
        reason = '当前内容与马来西亚置业客户需求关联较弱。'
        next_action = '暂不加入固定库；换更垂直的博主或关键词。'

    return {
        'account_name': _clean_text(account.get('name') or account.get('account_name') or '未命名账号', 80),
        'platform': _clean_text(account.get('platform') or '公开平台', 40),
        'account_url': str(account.get('url') or account.get('account_url') or ''),
        'decision': decision,
        'score': int(score),
        'freshness_score': int(freshness),
        'relevance_score': int(relevance),
        'heat_score': int(heat_part),
        'latest_post_at': latest,
        'days_since_latest': int(days),
        'recent_items_count': len(items),
        'reason': reason,
        'next_action': next_action,
        'account_type': account_type,
        'target_value': target_value,
        'customer_intents': intents[:5],
        'content_opportunities': opportunities[:5],
        'risk_notes': risk_notes[:5],
    }


def _existing_account_keys(memory: MemoryStore) -> set[str]:
    keys: set[str] = set()
    try:
        for acc in memory.list('heat_radar_accounts', limit=300):
            key = _account_key(acc)
            if key:
                keys.add(key)
    except Exception:
        pass
    return keys


async def ingest_openclaw_heat_radar(settings: Settings, memory: MemoryStore, req: Any) -> Dict[str, Any]:
    token = os.getenv('HEAT_RADAR_INGEST_TOKEN', '').strip() or os.getenv('OPENCLAW_INGEST_TOKEN', '').strip()
    if token and str(getattr(req, 'token', '') or '') != token:
        raise PermissionError('HEAT_RADAR_INGEST_TOKEN 不匹配。')

    source_name = _clean_text(getattr(req, 'source_name', '') or 'openclaw', 40).lower().replace(' ', '_')
    run_id = str(getattr(req, 'run_id', '') or f'{source_name}_{datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")}')
    keywords = _split_keywords(getattr(req, 'keywords', []), 80)
    max_stale_days = int(getattr(req, 'max_stale_days', 90) or 90)
    accept_min = int(getattr(req, 'auto_accept_min_score', 72) or 72)
    warnings: List[str] = []

    account_payloads: List[Dict[str, Any]] = []
    for acc in getattr(req, 'accounts', []) or []:
        payload = acc.model_dump() if hasattr(acc, 'model_dump') else dict(acc)
        payload.setdefault('id', payload.get('id') or f'openclaw_acc_{uuid.uuid4().hex[:12]}')
        if isinstance(payload.get('tags'), str):
            payload['tags'] = _split_keywords(payload.get('tags'), 12)
        account_payloads.append(payload)

    normalized_items: List[Dict[str, Any]] = []
    for item in getattr(req, 'items', []) or []:
        payload = item.model_dump() if hasattr(item, 'model_dump') else dict(item)
        fallback = {}
        name = str(payload.get('account_name') or '').strip()
        if name:
            fallback = next((a for a in account_payloads if str(a.get('name') or '').strip() == name), {})
        normalized_items.append(_normalize_openclaw_item(payload, fallback, source_name))

    # Also accept recent_items nested under accounts.
    for acc in account_payloads:
        for item in acc.get('recent_items') or []:
            payload = item.model_dump() if hasattr(item, 'model_dump') else dict(item)
            payload.setdefault('account_name', acc.get('name'))
            payload.setdefault('account_url', acc.get('url'))
            payload.setdefault('platform', acc.get('platform'))
            normalized_items.append(_normalize_openclaw_item(payload, acc, source_name))

    normalized_items = _dedupe_items(normalized_items)
    for item in normalized_items:
        item['run_id'] = run_id
        item['source_name'] = source_name

    decisions = [_review_account_value(acc, _account_items_for_review(memory, acc, normalized_items), keywords, max_stale_days, accept_min) for acc in account_payloads]
    accepted = [d for d in decisions if d['decision'] == 'accept']
    watch = [d for d in decisions if d['decision'] == 'watch']
    rejected = [d for d in decisions if d['decision'] == 'reject']
    archived = [d for d in decisions if d['decision'] == 'archive']

    saved_items = 0
    saved_accounts = 0
    if bool(getattr(req, 'save_to_memory', True)):
        for item in normalized_items[:300]:
            try:
                memory.insert('heat_radar_items', item)
                saved_items += 1
            except Exception as exc:
                warnings.append(f'保存采集内容失败：{str(exc)[:160]}')
        try:
            existing = _existing_account_keys(memory)
            for acc in account_payloads:
                review = next((d for d in accepted if d.get('account_name') == (acc.get('name') or acc.get('account_name'))), None)
                if not review or not bool(getattr(req, 'auto_add_accounts', True)):
                    continue
                key = _account_key(acc)
                if key and key in existing:
                    continue
                item = {
                    'name': acc.get('name') or acc.get('account_name') or review.get('account_name'),
                    'platform': acc.get('platform') or review.get('platform') or '公开平台',
                    'url': acc.get('url') or acc.get('account_url') or review.get('account_url'),
                    'tags': ','.join(acc.get('tags') or keywords[:6]),
                    'notes': f"OpenClaw 自动加入｜评分 {review.get('score')}｜{review.get('reason')}",
                    'pinned': True,
                    'created_at': now_iso(),
                    'raw': {'source': source_name, 'run_id': run_id, 'review': review, 'account': acc},
                }
                memory.insert('heat_radar_accounts', item)
                saved_accounts += 1
                if key:
                    existing.add(key)
        except Exception as exc:
            warnings.append(f'自动写入账号库失败：{str(exc)[:160]}')
        for review in decisions:
            try:
                memory.insert('heat_radar_account_reviews', {'run_id': run_id, 'source_name': source_name, **review, 'created_at': now_iso()})
            except Exception:
                pass
        try:
            top_items = _rank_top3(normalized_items)
            memory.insert('heat_daily_top3', {
                'date': today_key(),
                'summary': f'{source_name} 自动采集 {len(normalized_items)} 条，入库账号 {saved_accounts} 个。',
                'top_items': top_items,
                'analysis': _fallback_analysis(top_items),
                'keywords': keywords,
                'accounts_count': len(account_payloads),
                'top_mode': 'openclaw_ingest',
                'fallback_used': False,
                'raw': {'run_id': run_id, 'decisions': decisions},
            })
        except Exception:
            pass

    top_items = _rank_top3(normalized_items)
    return {
        'ok': True,
        'source_name': source_name,
        'run_id': run_id,
        'received_accounts': len(account_payloads),
        'received_items': len(normalized_items),
        'saved_accounts': saved_accounts,
        'saved_items': saved_items,
        'accepted_accounts': accepted,
        'watch_accounts': watch,
        'rejected_accounts': rejected,
        'archived_accounts': archived,
        'top_items': top_items,
        'warnings': warnings[:60],
        'next_actions': [
            '让 OpenClaw 每天把账号主页和最近视频 JSON POST 到该接口',
            '评分达标账号会自动进入固定账号库；过久不更新的账号进入归档建议',
            '热度雷达继续基于真实入库内容做 AI 改写和目标判断',
        ],
    }


async def audit_heat_radar_accounts(settings: Settings, memory: MemoryStore, req: Any) -> Dict[str, Any]:
    token = os.getenv('HEAT_RADAR_INGEST_TOKEN', '').strip() or os.getenv('OPENCLAW_INGEST_TOKEN', '').strip()
    if token and str(getattr(req, 'token', '') or '') != token:
        raise PermissionError('HEAT_RADAR_INGEST_TOKEN 不匹配。')
    keywords = _split_keywords(getattr(req, 'keywords', []), 80)
    max_stale_days = int(getattr(req, 'max_stale_days', 90) or 90)
    accounts: List[Dict[str, Any]] = []
    if bool(getattr(req, 'include_saved_accounts', True)):
        accounts.extend(memory.list('heat_radar_accounts', limit=200))
    for acc in getattr(req, 'accounts', []) or []:
        accounts.append(acc.model_dump() if hasattr(acc, 'model_dump') else dict(acc))
    deduped: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for acc in accounts:
        key = _account_key(acc)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(acc)
    reviews = [_review_account_value(acc, _account_items_for_review(memory, acc), keywords, max_stale_days=max_stale_days) for acc in deduped]
    keep = [r for r in reviews if r['decision'] == 'accept']
    watch = [r for r in reviews if r['decision'] in {'watch', 'reject'}]
    archive = [r for r in reviews if r['decision'] == 'archive']
    for r in reviews:
        try:
            memory.insert('heat_radar_account_reviews', {'run_id': f'audit_{today_key()}', **r, 'created_at': now_iso()})
        except Exception:
            pass
    return {
        'ok': True,
        'reviewed_count': len(reviews),
        'keep': keep,
        'watch': watch,
        'archive': archive,
        'warnings': [],
        'next_actions': [
            '保留 keep 账号继续自动采集',
            'watch 账号保留观察，连续几天无热度再移出',
            'archive 账号建议暂停采集，避免浪费采集额度',
        ],
    }


async def analyze_heat_radar_video_intake(settings: Settings, memory: MemoryStore, req: Any) -> Dict[str, Any]:
    token = os.getenv('HEAT_RADAR_INGEST_TOKEN', '').strip() or os.getenv('OPENCLAW_INGEST_TOKEN', '').strip()
    if token and str(getattr(req, 'token', '') or '') != token:
        raise PermissionError('HEAT_RADAR_INGEST_TOKEN 不匹配。')

    from app.services.collector import collect_public_video_best_effort
    from app.services.doubao import extract_with_doubao
    from app.services.storage import maybe_upload_to_r2

    warnings: List[str] = []
    account = {
        'name': getattr(req, 'account_name', '') or '未命名账号',
        'platform': getattr(req, 'platform', '') or '抖音',
        'url': getattr(req, 'account_url', '') or '',
        'tags': getattr(req, 'tags', []) or [],
        'notes': getattr(req, 'notes', '') or '',
    }
    raw_item = {
        'platform': account['platform'],
        'account_name': account['name'],
        'account_url': account['url'],
        'title': getattr(req, 'title', '') or '未命名视频',
        'url': getattr(req, 'video_url', '') or '',
        'published_at': getattr(req, 'published_at', '') or '',
        'like_count': getattr(req, 'like_count', 0) or 0,
        'comment_count': getattr(req, 'comment_count', 0) or 0,
        'favorite_count': getattr(req, 'favorite_count', 0) or 0,
        'share_count': getattr(req, 'share_count', 0) or 0,
        'view_count': getattr(req, 'view_count', 0) or 0,
        'is_pinned': bool(getattr(req, 'is_pinned', False)),
        'tags': getattr(req, 'tags', []) or [],
    }
    item = _normalize_openclaw_item(raw_item, account, 'video_intake')

    r2_video_url = ''
    extraction = {}
    video_url = str(getattr(req, 'video_url', '') or '').strip()
    if video_url:
        collected, collector_warnings = await collect_public_video_best_effort(settings, video_url)
        warnings.extend(collector_warnings)
        if collected and collected.path.exists():
            uploaded = maybe_upload_to_r2(settings, collected.path, prefix='heat-radar-videos')
            r2_video_url = uploaded or f'/files/uploads/{collected.path.name}'
            item['raw']['r2_video_url'] = r2_video_url
            item['raw']['collector_method'] = collected.method
            try:
                ex = await extract_with_doubao(settings, collected.path, source_url=video_url, manual_text=getattr(req, 'title', '') or '')
                extraction = ex.model_dump() if hasattr(ex, 'model_dump') else dict(ex)
                item['description'] = (ex.summary or item.get('description') or '')[:800]
                item['raw']['analysis_summary'] = ex.summary
                item['raw']['analysis_transcript'] = ex.transcript
                item['raw']['analysis_hooks'] = ex.hooks
                item['raw']['analysis_structure'] = ex.structure
                warnings.extend(ex.warnings or [])
            except Exception as exc:
                warnings.append(f'视频理解失败，已保留采集数据：{str(exc)[:220]}')
        else:
            warnings.append('未下载到视频文件，仅保存链接和标题供 AI/规则判断。')

    review = _review_account_value(account, [item], _split_keywords(getattr(req, 'tags', []) or []), max_stale_days=90, accept_min_score=72)

    # 有视频理解结果时，再用强推理模型补充判断；失败不阻断入库。
    if extraction:
        try:
            payload = await _chat_json(
                settings,
                '你是马来西亚房产获客账号筛选助手。只输出 JSON。',
                json.dumps({
                    'task': '判断该视频/账号是否值得收录进马来西亚房产获客热度雷达',
                    'account': account,
                    'video': raw_item,
                    'video_understanding': extraction,
                    'rules': '不要只看点赞；生活、教育、医疗、交通、华人社区、陪读、养老、第二家园、预算和真实体验都可作为收录依据。',
                    'output_schema': {'decision': 'accept/watch/reject/archive', 'score': 0, 'account_type': '', 'target_value': '', 'customer_intents': [], 'content_opportunities': [], 'risk_notes': [], 'reason': ''},
                }, ensure_ascii=False),
                temperature=0.2,
                timeout=90,
            )
            for key in ['decision', 'score', 'account_type', 'target_value', 'customer_intents', 'content_opportunities', 'risk_notes', 'reason']:
                if key in payload:
                    review[key] = payload[key]
        except Exception as exc:
            warnings.append(f'强推理模型审核失败，已使用规则评分：{str(exc)[:220]}')

    saved_item = memory.insert('heat_radar_items', item)
    if saved_item.get('_memory_warning'):
        warnings.append(saved_item['_memory_warning'])
    if bool(getattr(req, 'auto_save_review', True)):
        saved_review = memory.insert('heat_radar_account_reviews', {'run_id': f'video_intake_{today_key()}', 'source_name': 'video_intake', **review, 'raw': {'item_id': saved_item.get('id'), 'extraction': extraction}, 'created_at': now_iso()})
        if saved_review.get('_memory_warning'):
            warnings.append(saved_review['_memory_warning'])

    return {
        'ok': True,
        'item': saved_item,
        'review': review,
        'extraction': extraction,
        'r2_video_url': r2_video_url,
        'warnings': warnings[:80],
        'next_actions': ['在页面查看 AI 收录判断', 'accept 账号可手动保存进账号库', '置顶视频用于判断账号定位，近期视频用于判断活跃度'],
    }
