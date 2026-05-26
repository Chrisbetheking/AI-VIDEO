from __future__ import annotations

import asyncio
import html
import json
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

URL_RE = re.compile(r'https?://[^\s，。！？!！；;]+', re.I)
TITLE_RE = re.compile(r'<title[^>]*>(.*?)</title>', re.I | re.S)
DESC_RE = re.compile(r'<meta[^>]+(?:name|property)=["\'](?:description|og:description)["\'][^>]+content=["\']([^"\']+)["\']', re.I | re.S)
OG_TITLE_RE = re.compile(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', re.I | re.S)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def today_key() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _setting(settings: Settings, name: str, default: Any) -> Any:
    return getattr(settings, name, default)


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
    match = OG_TITLE_RE.search(text or '')
    if match:
        title = _clean_text(match.group(1), 180)
    if not title:
        match = TITLE_RE.search(text or '')
        if match:
            title = _clean_text(match.group(1), 180)
    match = DESC_RE.search(text or '')
    if match:
        desc = _clean_text(match.group(1), 500)
    return title, desc


def _is_real_url(value: Any) -> bool:
    return str(value or '').strip().startswith(('http://', 'https://'))


async def _fetch_html_meta(settings: Settings, url: str, account: Dict[str, Any], warnings: List[str]) -> Dict[str, Any] | None:
    """轻量公开采集：只读公开页面 HTML 的标题/描述，不调用重型解析器，避免 Render 免费实例被打崩。"""
    headers = {
        'User-Agent': _setting(settings, 'collector_user_agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122 Safari/537.36'),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Referer': 'https://www.douyin.com/',
    }
    timeout = min(max(int(_setting(settings, 'collector_timeout_seconds', 8) or 8), 4), 12)
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
            res = await client.get(url)
            if res.status_code >= 400:
                warnings.append(f'{url}: 公开页面读取失败 HTTP {res.status_code}')
                return None
            # 避免大页面占内存，只解析前 300KB。
            text = res.text[:300_000]
            title, desc = _title_from_html(text)
    except Exception as exc:
        warnings.append(f'{url}: 公开页面读取失败：{str(exc)[:160]}')
        return None
    if not title and not desc:
        warnings.append(f'{url}: 未读取到标题/描述，平台可能需要登录、客户端渲染或限制公开访问。')
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
        'heat_score': 1,
        'keyword': ','.join(_split_keywords(account.get('tags'), 5)),
        'tags': _split_keywords(account.get('tags'), 8),
        'thumbnail_url': '',
        'source_mode': 'public_html_safe',
        'raw': {'description': desc, 'note': '轻量公开采集只能拿公开标题/描述，点赞评论等热度字段需官方 API 或第三方数据源。'},
        'warnings': [],
    }
    item['heat_score'] = heat_score(item) or 1
    return item


def _extract_number_from_text(patterns: List[str], text: str) -> int:
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            return _num(m.group(1))
    return 0


def _manual_line_to_item(line: str, account: Dict[str, Any], keywords: List[str]) -> Dict[str, Any] | None:
    """把运营粘贴的真实标题/链接/数据转成 item。用于没有企业认证时的真实数据兜底。"""
    raw = _clean_text(line, 800)
    if not raw:
        return None
    urls = URL_RE.findall(raw)
    url = urls[0] if urls else str(account.get('url') or '')
    title = raw
    if url:
        title = title.replace(url, '').strip(' -｜|') or url
    item = {
        'id': str(uuid.uuid4()),
        'date': today_key(),
        'platform': _platform_from_url(url, str(account.get('platform') or '手动真实数据')),
        'account_id': str(account.get('id') or ''),
        'account_name': str(account.get('name') or '手动导入'),
        'title': title[:180],
        'description': raw,
        'url': url,
        'published_at': '',
        'collected_at': now_iso(),
        'like_count': _extract_number_from_text([r'(?:赞|点赞|like)[：:\s]*([\d.,万wk]+)'], raw),
        'comment_count': _extract_number_from_text([r'(?:评论|comment)[：:\s]*([\d.,万wk]+)'], raw),
        'favorite_count': _extract_number_from_text([r'(?:收藏|favorite|fav)[：:\s]*([\d.,万wk]+)'], raw),
        'share_count': _extract_number_from_text([r'(?:分享|转发|share)[：:\s]*([\d.,万wk]+)'], raw),
        'view_count': _extract_number_from_text([r'(?:播放|浏览|view)[：:\s]*([\d.,万wk]+)'], raw),
        'heat_score': 0,
        'keyword': ','.join([k for k in keywords if k and k in raw][:6]),
        'tags': [k for k in keywords if k and k in raw][:8],
        'thumbnail_url': '',
        'source_mode': 'manual_real_data_line',
        'raw': {'line': raw},
        'warnings': [],
    }
    item['heat_score'] = heat_score(item) or 1
    return item


async def _collect_account(settings: Settings, account: Dict[str, Any], warnings: List[str]) -> List[Dict[str, Any]]:
    url = str(account.get('url') or '').strip()
    if not _is_real_url(url):
        warnings.append(f"{account.get('name') or '未命名账号'}: 没有有效公开链接，跳过自动采集。")
        return []
    item = await _fetch_html_meta(settings, url, account, warnings)
    return [item] if item else []


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
    topics = [str(x.get('title') or '')[:60] for x in top_items if x.get('title')]
    if not topics:
        topics = ['马来西亚房产', '第二家园/MM2H', '吉隆坡/新山房产']
    return {
        'summary': '热度雷达已稳定运行。当前未接官方/第三方数据源时，只展示系统实际读取到的公开标题/导入数据，不编造点赞评论。',
        'content_angles': [f'围绕「{t}」做原创反打/解释内容' for t in topics[:5]],
        'customer_intents': ['税费/流程判断', '城市比较', '第二家园/身份规划', '教育家庭选盘'],
        'lead_magnets': ['马来西亚买房税费测算表', 'MM2H 与购房要求对照表', '吉隆坡 vs 新山选盘表'],
        'reply_hooks': ['这个问题很多家庭都会先卡在资格、预算和城市选择上。', '如果你是为了教育/身份/养老，选盘逻辑完全不同。'],
        'next_actions': ['补充具体公开视频/笔记链接可提升采集成功率。', '要看到真实点赞/评论/收藏，建议后续接飞瓜/蝉妈妈/千瓜导出或官方 API。'],
    }


async def analyze_heat_items(settings: Settings, top_items: List[Dict[str, Any]], keywords: List[str]) -> Dict[str, Any]:
    if not top_items:
        return _fallback_analysis([])
    lines = []
    for i, item in enumerate(top_items[:12], start=1):
        lines.append(
            f"{i}. 平台：{item.get('platform')}｜账号：{item.get('account_name')}｜标题：{item.get('title')}｜"
            f"赞{item.get('like_count')} 评论{item.get('comment_count')} 收藏{item.get('favorite_count')} 分享{item.get('share_count')}｜链接：{item.get('url')}｜来源：{item.get('source_mode')}"
        )
    system = '你是中国社媒获客热度雷达分析师。只基于已采集/导入的数据分析，不要编造数据。输出严格 JSON。'
    user = f"""
监控关键词：{', '.join(keywords[:30]) or '未填写'}
今日数据：
{chr(10).join(lines)}

请输出 JSON：
{{
  "summary": "一句话总结今天热度方向，并说明数据来源限制",
  "content_angles": ["我们应该跟进的原创选题"],
  "customer_intents": ["客户真实需求/疑问"],
  "lead_magnets": ["适合承接的资料包/报告"],
  "reply_hooks": ["适合评论区/私信的人工回复开头"],
  "next_actions": ["今天运营要做的动作"]
}}
""".strip()
    try:
        payload = await _chat_json(settings, system, user, temperature=0.25, timeout=45)
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
        analysis['warnings'] = [f'AI 分析失败，已降级规则分析：{str(exc)[:200]}']
        return analysis


def _safe_memory_insert(memory: MemoryStore, collection: str, item: Dict[str, Any], warnings: List[str]) -> bool:
    try:
        memory.insert(collection, item)
        return True
    except Exception as exc:
        warnings.append(f'{collection} 保存失败，已跳过：{str(exc)[:160]}')
        return False


async def run_public_heat_radar(settings: Settings, memory: MemoryStore, req: Any) -> Dict[str, Any]:
    """Render 安全版热度雷达：不会因为公开采集失败导致后端重启/前端断连。"""
    warnings: List[str] = []
    keywords = _split_keywords(getattr(req, 'keywords', []), 60)
    accounts: List[Dict[str, Any]] = []

    if bool(getattr(req, 'include_saved_accounts', True)):
        try:
            saved = memory.list('heat_radar_accounts', limit=60)
            if saved:
                accounts.extend(saved)
            else:
                for comp in memory.list('competitor_accounts', limit=30):
                    accounts.append({
                        'id': comp.get('id'),
                        'name': comp.get('name'),
                        'platform': comp.get('platform'),
                        'url': comp.get('url'),
                        'tags': comp.get('positioning') or comp.get('notes') or '',
                        'notes': comp.get('notes') or '',
                    })
        except Exception as exc:
            warnings.append(f'读取账号库失败：{str(exc)[:160]}')

    for acc in getattr(req, 'accounts', []) or []:
        try:
            payload = acc.model_dump() if hasattr(acc, 'model_dump') else dict(acc)
            accounts.append(payload)
        except Exception:
            continue

    # 从 notes/tags 支持粘贴真实数据行：标题 链接 赞/评论/收藏。
    manual_lines: List[str] = []
    for acc in accounts:
        text = str(acc.get('notes') or '')
        for line in re.split(r'[\n]+', text):
            if len(line.strip()) > 10 and (URL_RE.search(line) or any(k in line for k in ['赞', '评论', '收藏', '播放'])):
                manual_lines.append(line.strip())

    # 去重账号，Render 免费实例先最多处理 5 个公开链接，避免前端断连。
    deduped: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for acc in accounts:
        key = str(acc.get('url') or acc.get('name') or '').strip()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(acc)

    if not deduped and not manual_lines:
        warnings.append('没有可采集的账号/链接。请先添加竞品账号主页、公开视频链接，或在备注里粘贴真实内容数据。')

    collected: List[Dict[str, Any]] = []

    # 先把备注里的真实数据行转成 item，保证没有官方 API 时也能展示真实人工采集数据。
    for line in manual_lines[:60]:
        item = _manual_line_to_item(line, {'name': '备注导入', 'platform': '真实数据导入'}, keywords)
        if item:
            collected.append(item)

    max_accounts = int(os.getenv('HEAT_RADAR_MAX_PUBLIC_ACCOUNTS', '5') or '5')
    max_accounts = max(1, min(max_accounts, 8))
    for acc in deduped[:max_accounts]:
        try:
            items = await _collect_account(settings, acc, warnings)
            collected.extend(items)
        except Exception as exc:
            warnings.append(f"{acc.get('name') or acc.get('url')}: 采集失败：{str(exc)[:180]}")

    collected = _dedupe_items(collected)
    for item in collected:
        item['heat_score'] = heat_score(item) or int(item.get('heat_score') or 1)
        title_blob = ' '.join([str(item.get('title') or ''), str(item.get('description') or ''), str(item.get('keyword') or '')])
        matched = [k for k in keywords if k and k in title_blob]
        if matched:
            item['matched_keywords'] = matched[:6]

    top_items = _rank_top3(collected)
    analysis = await analyze_heat_items(settings, top_items, keywords)

    saved_count = 0
    if bool(getattr(req, 'save_to_memory', True)):
        for item in collected[:120]:
            if _safe_memory_insert(memory, 'heat_radar_items', item, warnings):
                saved_count += 1
        _safe_memory_insert(memory, 'heat_daily_top3', {
            'date': today_key(),
            'summary': analysis.get('summary', ''),
            'top_items': top_items,
            'analysis': analysis,
            'keywords': keywords,
            'accounts_count': len(deduped),
            'raw': {'warnings': warnings[:80]},
        }, warnings)
        try:
            memory.save_learning_event({
                'event_type': 'heat_radar_public_crawl',
                'title': f'{today_key()} 自动热度雷达',
                'payload': {'top_items': top_items, 'analysis': analysis, 'warnings': warnings[:80]},
            })
        except Exception as exc:
            warnings.append(f'学习事件保存失败：{str(exc)[:160]}')

    return {
        'ok': True,
        'source_mode': 'public_crawler_safe_no_enterprise_api',
        'accounts_count': len(deduped),
        'collected_count': len(collected),
        'saved_count': saved_count,
        'top_items': top_items,
        'analysis': analysis,
        'warnings': warnings[:80],
        'next_actions': analysis.get('next_actions') or _fallback_analysis(top_items).get('next_actions'),
    }
