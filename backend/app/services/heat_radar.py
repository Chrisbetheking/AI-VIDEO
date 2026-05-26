from __future__ import annotations

import html
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse

import httpx

from app.config import Settings
from app.services.deepseek import DeepSeekError, _chat_json
from app.services.memory import MemoryStore

URL_RE = re.compile(r'https?://[^\s，。！？!！；;）)]+', re.I)
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
            v = value.strip().lower().replace(',', '')
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
        + (1 if item.get('url') else 0)
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
    # 支持：赞123、点赞 1.2万、评论:34、收藏0、分享 5、播放 3000
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


def _make_item(account: Dict[str, Any], *, title: str, url: str = '', description: str = '', source_mode: str = 'manual_or_public', line: str = '') -> Dict[str, Any]:
    raw_line = line or ' '.join([title, description])
    item = {
        'id': str(uuid.uuid4()),
        'date': today_key(),
        'platform': _platform_from_url(url, str(account.get('platform') or '')),
        'account_id': str(account.get('id') or ''),
        'account_name': str(account.get('name') or '公开来源'),
        'title': _clean_text(title or str(account.get('name') or '公开内容'), 180),
        'description': _clean_text(description, 700),
        'url': url,
        'published_at': '',
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
        'raw': {'line': line},
        'warnings': [],
    }
    item['heat_score'] = heat_score(item)
    return item


async def _fetch_html_meta(settings: Settings, url: str, account: Dict[str, Any], warnings: List[str]) -> Dict[str, Any] | None:
    if os.getenv('HEAT_RADAR_PUBLIC_FETCH', '').strip().lower() not in {'1', 'true', 'yes', 'on'}:
        return None
    headers = {
        'User-Agent': getattr(settings, 'collector_user_agent', '') or 'Mozilla/5.0',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Referer': 'https://www.douyin.com/',
    }
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True, headers=headers) as client:
            res = await client.get(url)
            if res.status_code >= 400:
                warnings.append(f'{url}: 公开页面读取失败 HTTP {res.status_code}')
                return None
            title, desc = _title_from_html(res.text)
    except Exception as exc:
        warnings.append(f'{url}: 公开页面读取失败：{str(exc)[:160]}')
        return None
    if not title and not desc:
        warnings.append(f'{url}: 没有读取到标题/描述，平台可能需要登录或动态渲染。')
        return None
    return _make_item(account, title=title or desc[:80] or '公开内容', url=url, description=desc, source_mode='public_html')


def _parse_account_notes(account: Dict[str, Any], warnings: List[str], limit: int) -> List[Dict[str, Any]]:
    """从账号 URL、备注、标签中提取真实可追溯内容。

    不编造点赞/评论；只要有公开链接或用户手动写了指标，就进入热度池。
    """
    items: List[Dict[str, Any]] = []
    notes = str(account.get('notes') or '')
    url = str(account.get('url') or '').strip()
    fallback_title = str(account.get('name') or '竞品账号观察').strip() or '竞品账号观察'

    # 逐行解析：优先保留带链接或带真实指标的行。
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

    # 如果账号主链接本身是具体内容链接，也要作为真实公开链接留存。
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
    items = _parse_account_notes(account, warnings, limit)
    # 对带 URL 的条目可选读取标题；失败不影响展示。
    enriched: List[Dict[str, Any]] = []
    for item in items:
        url = str(item.get('url') or '')
        meta = await _fetch_html_meta(settings, url, account, warnings) if url else None
        if meta:
            # 保留手动指标，用公开 title 替换更干净的标题。
            for key in ['like_count', 'comment_count', 'favorite_count', 'share_count', 'view_count']:
                meta[key] = item.get(key, meta.get(key, 0))
            meta['heat_score'] = heat_score(meta)
            enriched.append(meta)
        else:
            enriched.append(item)
    return enriched[:limit]


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
    return sorted(items, key=lambda x: (int(x.get('heat_score') or 0), str(x.get('collected_at') or '')), reverse=True)[:3]


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
    return _rank_top3(valid)[:limit]


def _fallback_analysis(top_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    topics = [str(x.get('title') or '')[:60] for x in top_items if x.get('title')]
    if not topics:
        topics = ['补充竞品具体视频/笔记链接', '补充点赞评论收藏指标', '接入第三方/官方数据源']
    return {
        'summary': '已进入安全热度雷达：只基于账号库公开链接、备注/CSV 真实数据和历史留存分析，不再生成本地假数据。',
        'content_angles': [f'围绕「{t}」做原创跟进/解释内容' for t in topics[:5]],
        'customer_intents': ['税费/流程判断', '城市比较', '第二家园/身份规划', '教育家庭选盘'],
        'lead_magnets': ['马来西亚买房税费测算表', 'MM2H 与购房要求对照表', '吉隆坡 vs 新山选盘表'],
        'reply_hooks': ['这个问题先看你的用途和预算，再判断城市/区域。', '我整理了一个对照表，可以先帮你判断方向。'],
        'next_actions': ['给竞品账号备注补 1-3 条具体视频/笔记链接。', '如果主页无法公开列出最近视频，后续接 Cookie、第三方数据平台或官方 API。', '把热度最高的话题一键转为口播文案和图文引流包。'],
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
    top_mode = 'today_top3'
    fallback_used = False
    if not top_items:
        recent = _recent_real_items(memory, 3)
        if recent:
            top_items = recent
            top_mode = 'recent_top_fallback'
            fallback_used = True
            warnings.append('本轮没有采到新内容，已回看最近真实留存 3 条。')
        else:
            warnings.append('本轮没有真实内容可展示：请补具体视频/笔记链接，或在备注/导入框粘贴一行真实数据。')

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
        'source_mode': 'public_links_notes_csv_without_enterprise_api',
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
