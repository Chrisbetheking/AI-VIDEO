from __future__ import annotations

import html
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

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
    u = str(url or '').lower()
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
    """极轻量公开采集。默认关闭，只有 HEAT_RADAR_PUBLIC_FETCH=true 时才会调用。"""
    try:
        timeout_raw = _setting(settings, 'collector_timeout_seconds', 6) or 6
        timeout = min(max(int(timeout_raw), 3), 8)
    except Exception:
        timeout = 6
    headers = {
        'User-Agent': _setting(settings, 'collector_user_agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122 Safari/537.36'),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    }
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
            res = await client.get(url)
            if res.status_code >= 400:
                warnings.append(f'{url}: 公开页面读取失败 HTTP {res.status_code}')
                return None
            text = (res.text or '')[:200_000]
            title, desc = _title_from_html(text)
    except BaseException as exc:
        warnings.append(f'{url}: 公开页面读取失败：{str(exc)[:160]}')
        return None
    if not title and not desc:
        warnings.append(f'{url}: 没读到标题/描述，平台可能需要登录、客户端渲染或限制公开访问。')
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
        'raw': {'description': desc, 'note': '轻量公开采集只能拿公开标题/描述；点赞评论收藏需官方 API、第三方数据平台或备注/CSV 导入。'},
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


def _line_looks_like_heat_record(line: str) -> bool:
    """判断备注/粘贴内容是不是一条真实热度记录，而不是操作说明。

    之前把“每天查看所有视频，采集点赞评论前三条”这种说明误识别成内容，
    导致页面出现假数据。现在必须满足：有 URL，或有明确数字指标。
    """
    raw = str(line or '').strip()
    if not raw:
        return False
    if URL_RE.search(raw):
        return True
    metric_with_number = re.search(r'(赞|点赞|评论|收藏|分享|转发|播放|浏览|like|comment|favorite|share|view)[：:\s]*[0-9]', raw, re.I)
    if metric_with_number:
        return True
    # CSV/表格行：标题,链接,点赞,评论... 这种也允许；纯说明文字不允许。
    cells = [x.strip() for x in re.split(r'[,，\t|｜]', raw) if x.strip()]
    has_number = any(re.search(r'\d', c) for c in cells)
    has_metric_word = any(any(w in c.lower() for w in ['赞', '点赞', '评论', '收藏', '分享', '播放', '浏览', 'like', 'comment', 'view']) for c in cells)
    return len(cells) >= 3 and has_number and has_metric_word


def _manual_line_to_item(line: str, account: Dict[str, Any], keywords: List[str]) -> Dict[str, Any] | None:
    raw = _clean_text(line, 1000)
    if not raw or not _line_looks_like_heat_record(raw):
        return None
    urls = URL_RE.findall(raw)
    url = urls[0] if urls else str(account.get('url') or '')
    title = raw.replace(url, '').strip(' -｜|') if url else raw
    item = {
        'id': str(uuid.uuid4()),
        'date': today_key(),
        'platform': _platform_from_url(url, str(account.get('platform') or '真实数据导入')),
        'account_id': str(account.get('id') or ''),
        'account_name': str(account.get('name') or '真实数据导入'),
        'title': title[:180] or url or '真实热度内容',
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
        'source_mode': 'manual_or_csv_real_data_line',
        'raw': {'line': raw},
        'warnings': [],
    }
    item['heat_score'] = heat_score(item) or 1
    return item


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


def _time_sort_value(item: Dict[str, Any]) -> str:
    return str(item.get('published_at') or item.get('collected_at') or item.get('created_at') or item.get('date') or '')


def _normalize_existing_item(item: Dict[str, Any]) -> Dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    title = str(item.get('title') or item.get('topic') or '').strip()
    url = str(item.get('url') or item.get('source_url') or '').strip()
    # 过滤早期的关键词模拟/操作说明数据，避免“真实采集”里混假内容。
    source_mode = str(item.get('source_mode') or '').lower()
    if 'seed' in source_mode or 'local' in source_mode or 'demo' in source_mode:
        return None
    if not title and not url:
        return None
    out = dict(item)
    out.setdefault('id', str(uuid.uuid4()))
    out.setdefault('date', str(item.get('date') or today_key()))
    out.setdefault('platform', str(item.get('platform') or '历史留存'))
    out.setdefault('account_id', str(item.get('account_id') or ''))
    out.setdefault('account_name', str(item.get('account_name') or '历史留存'))
    out.setdefault('title', title or url or '历史留存内容')
    out.setdefault('url', url)
    out.setdefault('collected_at', str(item.get('collected_at') or item.get('created_at') or now_iso()))
    out.setdefault('like_count', _num(item.get('like_count')))
    out.setdefault('comment_count', _num(item.get('comment_count')))
    out.setdefault('favorite_count', _num(item.get('favorite_count')))
    out.setdefault('share_count', _num(item.get('share_count')))
    out.setdefault('view_count', _num(item.get('view_count')))
    out['heat_score'] = int(item.get('heat_score') or heat_score(out) or 1)
    out['source_mode'] = str(item.get('source_mode') or 'recent_saved_fallback')
    return out


def _rank_today_or_recent(items: List[Dict[str, Any]], limit: int = 3) -> Tuple[List[Dict[str, Any]], str]:
    """优先返回今天真实采集 TopN；今天没有则返回最近留存 TopN。"""
    normalized = [x for x in (_normalize_existing_item(i) for i in items) if x]
    if not normalized:
        return [], 'empty'
    today = today_key()
    today_items = [x for x in normalized if str(x.get('date') or '').startswith(today)]
    if today_items:
        return sorted(today_items, key=lambda x: int(x.get('heat_score') or 0), reverse=True)[:limit], 'today_top'
    # 没有今天内容：先按发布时间/采集时间取最近一批，再按热度取 TopN。
    recent_pool = sorted(normalized, key=_time_sort_value, reverse=True)[: max(20, limit * 4)]
    return sorted(recent_pool, key=lambda x: int(x.get('heat_score') or 0), reverse=True)[:limit], 'recent_top_fallback'


def _fallback_analysis(top_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    topics = [str(x.get('title') or '')[:60] for x in top_items if x.get('title')]
    if not topics:
        topics = ['暂无真实热度内容']
    return {
        'summary': '热度雷达已进入安全模式：不再让 Render 因公开网页采集而 500。当前只分析已保存账号、备注/CSV 里的真实数据，以及可选轻量公开标题。',
        'content_angles': [f'围绕「{t}」做原创反打/解释内容' for t in topics[:5] if t != '暂无真实热度内容'],
        'customer_intents': ['税费/流程判断', '城市比较', '第二家园/身份规划', '教育家庭选盘'],
        'lead_magnets': ['马来西亚买房税费测算表', 'MM2H 与购房要求对照表', '吉隆坡 vs 新山选盘表'],
        'reply_hooks': ['这个问题很多家庭都会先卡在资格、预算和城市选择上。', '如果你是为了教育/身份/养老，选盘逻辑完全不同。'],
        'next_actions': ['先把竞品账号库固定下来。', '没有企业认证前，真实点赞/评论/收藏建议通过备注、CSV、飞瓜/蝉妈妈/千瓜导出接入。', '若要测试公开标题采集，在 Render 环境变量加 HEAT_RADAR_PUBLIC_FETCH=true。'],
    }


async def analyze_heat_items(settings: Settings, top_items: List[Dict[str, Any]], keywords: List[str]) -> Dict[str, Any]:
    if not top_items:
        return _fallback_analysis([])
    if str(os.getenv('HEAT_RADAR_AI_ANALYSIS', 'false')).lower() not in {'1', 'true', 'yes', 'on'}:
        return _fallback_analysis(top_items)
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
        payload = await _chat_json(settings, system, user, temperature=0.25, timeout=25)
        for key in ['content_angles', 'customer_intents', 'lead_magnets', 'reply_hooks', 'next_actions']:
            value = payload.get(key)
            if isinstance(value, str):
                payload[key] = _split_keywords(value, 12)
            elif not isinstance(value, list):
                payload[key] = []
        payload.setdefault('summary', '今日热度分析已完成。')
        return payload
    except (DeepSeekError, BaseException) as exc:
        analysis = _fallback_analysis(top_items)
        analysis['warnings'] = [f'AI 分析失败，已降级规则分析：{str(exc)[:200]}']
        return analysis


def _safe_memory_insert(memory: MemoryStore, collection: str, item: Dict[str, Any], warnings: List[str]) -> bool:
    try:
        memory.insert(collection, item)
        return True
    except BaseException as exc:
        warnings.append(f'{collection} 保存失败，已跳过：{str(exc)[:160]}')
        return False


async def run_public_heat_radar(settings: Settings, memory: MemoryStore, req: Any) -> Dict[str, Any]:
    """永不打挂 Render 的热度雷达安全入口。"""
    warnings: List[str] = []
    keywords = _split_keywords(getattr(req, 'keywords', []), 60)
    accounts: List[Dict[str, Any]] = []

    try:
        if bool(getattr(req, 'include_saved_accounts', True)):
            try:
                saved = memory.list('heat_radar_accounts', limit=80)
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
            except BaseException as exc:
                warnings.append(f'读取账号库失败：{str(exc)[:160]}')

        for acc in getattr(req, 'accounts', []) or []:
            try:
                payload = acc.model_dump() if hasattr(acc, 'model_dump') else dict(acc)
                accounts.append(payload)
            except BaseException:
                continue

        manual_lines: List[tuple[str, Dict[str, Any]]] = []
        for acc in accounts:
            text = str(acc.get('notes') or '')
            for line in re.split(r'[\n]+', text):
                line = line.strip()
                if len(line) > 10 and _line_looks_like_heat_record(line):
                    manual_lines.append((line, acc))

        deduped: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for acc in accounts:
            key = str(acc.get('url') or acc.get('name') or '').strip()
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(acc)

        collected: List[Dict[str, Any]] = []
        for line, acc in manual_lines[:80]:
            item = _manual_line_to_item(line, acc, keywords)
            if item:
                collected.append(item)

        public_fetch_enabled = str(os.getenv('HEAT_RADAR_PUBLIC_FETCH', 'false')).lower() in {'1', 'true', 'yes', 'on'}
        if public_fetch_enabled:
            max_accounts = int(os.getenv('HEAT_RADAR_MAX_PUBLIC_ACCOUNTS', '2') or '2')
            max_accounts = max(1, min(max_accounts, 3))
            for acc in deduped[:max_accounts]:
                url = str(acc.get('url') or '').strip()
                if not _is_real_url(url):
                    continue
                item = await _fetch_html_meta(settings, url, acc, warnings)
                if item:
                    collected.append(item)
        else:
            if deduped:
                warnings.append('安全模式已关闭公开网页抓取，避免 Render 免费实例 500。需要测试公开标题采集时设置 HEAT_RADAR_PUBLIC_FETCH=true。')

        if not deduped and not manual_lines:
            warnings.append('没有可采集的账号/链接。请先添加竞品账号主页、公开视频链接，或在备注里粘贴真实数据行；如果今天没新内容，系统会自动回看最近 3 条历史留存。')

        collected = _dedupe_items(collected)
        for item in collected:
            item['heat_score'] = heat_score(item) or int(item.get('heat_score') or 1)
            title_blob = ' '.join([str(item.get('title') or ''), str(item.get('description') or ''), str(item.get('keyword') or '')])
            matched = [k for k in keywords if k and k in title_blob]
            if matched:
                item['matched_keywords'] = matched[:6]

        existing_items: List[Dict[str, Any]] = []
        try:
            existing_items = [_normalize_existing_item(x) for x in memory.list('heat_radar_items', limit=300)]
            existing_items = [x for x in existing_items if x]
        except BaseException as exc:
            warnings.append(f'读取历史热度留存失败：{str(exc)[:160]}')

        ranked_input = collected + existing_items
        top_items, top_mode = _rank_today_or_recent(ranked_input, limit=3)
        if top_mode == 'recent_top_fallback':
            warnings.append('今天没有采集到新内容，已自动展示最近留存的 3 条高热内容。')
            for item in top_items:
                item['source_mode'] = str(item.get('source_mode') or '') + '_recent_fallback'
                item['date_basis'] = 'recent_when_no_today_content'
        elif top_mode == 'empty':
            warnings.append('没有可展示的真实内容。请先添加具体视频/笔记链接，或在账号备注里粘贴真实热度数据行。')

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
                    'event_type': 'heat_radar_public_crawl_safe_mode',
                    'title': f'{today_key()} 热度雷达安全采集',
                    'payload': {'top_items': top_items, 'analysis': analysis, 'warnings': warnings[:80]},
                })
            except BaseException as exc:
                warnings.append(f'学习事件保存失败：{str(exc)[:160]}')

        return {
            'ok': True,
            'source_mode': 'heat_radar_safe_mode_no_crash',
            'top_mode': top_mode,
            'fallback_used': top_mode == 'recent_top_fallback',
            'accounts_count': len(deduped),
            'collected_count': len(collected),
            'saved_count': saved_count,
            'top_items': top_items,
            'analysis': analysis,
            'warnings': warnings[:80],
            'next_actions': analysis.get('next_actions') or _fallback_analysis(top_items).get('next_actions'),
        }
    except BaseException as exc:
        return {
            'ok': False,
            'source_mode': 'heat_radar_hard_guard',
            'accounts_count': 0,
            'collected_count': 0,
            'saved_count': 0,
            'top_items': [],
            'analysis': _fallback_analysis([]),
            'warnings': [f'热度雷达异常已兜底：{str(exc)[:240]}'],
            'next_actions': ['后端已兜底，不会再打挂 Render。', '先添加具体链接或在备注里粘真实数据行。', '后续接官方/第三方数据源后再打开自动采集。'],
        }
