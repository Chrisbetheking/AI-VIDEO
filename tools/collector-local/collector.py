from __future__ import annotations


def _force_safe_console() -> None:
    import os as _os
    import sys as _sys
    _os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
    for _stream in (_sys.stdout, _sys.stderr):
        try:
            _stream.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass

_force_safe_console()

import argparse
import asyncio
import json
import os
import random
import re

import httpx
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from playwright.async_api import BrowserContext, Page, async_playwright

from excel_io import write_excel, excel_rows_to_accounts
from state import CollectorState, SingleRunLock
from utils import normalize_video_url, split_tags, within_recent_days
from uploader import report_event, upload_video_intake
from cookie_manager import refresh_cookies_from_context
from video_resolver import resolve_videos_for_items


async def human_delay(min_s: int, max_s: int) -> None:
    await asyncio.sleep(random.randint(max(1, min_s), max(min_s, max_s)))


def _split_tags_value(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    return split_tags(value)


def _extract_accounts_list(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("accounts", "items", "data", "results"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []


def _normalize_account(raw: dict[str, Any]) -> dict[str, Any] | None:
    raw_obj = raw.get("raw") if isinstance(raw.get("raw"), dict) else {}
    name = str(raw.get("name") or raw.get("account_name") or raw_obj.get("name") or raw_obj.get("account_name") or "").strip()
    platform = str(raw.get("platform") or raw_obj.get("platform") or "抖音").strip()
    tags = _split_tags_value(raw.get("tags") or raw.get("positioning") or raw_obj.get("tags") or raw_obj.get("positioning"))
    notes = str(raw.get("notes") or raw.get("remark") or raw_obj.get("notes") or "").strip()
    url = str(raw.get("url") or raw.get("account_url") or raw.get("profile_url") or raw_obj.get("url") or raw_obj.get("account_url") or "").strip()
    if (not url) or "REPLACE_ME" in url:
        url = first_url_from_text(notes) or url
    status = str(raw.get("status") or raw.get("review_status") or "").lower()
    if status in {"paused", "pause", "archived", "archive", "disabled"}:
        return None
    if not url or "REPLACE_ME" in url:
        return None
    # 第一版只让抖音 Worker 处理抖音链接，避免小红书/视频号混进去空跑。
    platform_text = (platform + " " + url).lower()
    if "douyin" not in platform_text and "抖音" not in platform_text and "v.douyin" not in platform_text:
        return None
    return {
        "name": name or "未命名账号",
        "platform": platform or "抖音",
        "url": url,
        "tags": tags or ["马来西亚房产", "海外置业"],
        "notes": notes,
        "source": "site_account_library",
    }


def load_local_accounts(path: str | Path = "accounts.seed.json") -> list[dict[str, Any]]:
    file_path = Path(path)
    if not file_path.exists():
        return []
    data = json.loads(file_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise RuntimeError("accounts.seed.json 必须是数组")
    return [a for a in (_normalize_account(x) for x in data if isinstance(x, dict)) if a]


def load_accounts_from_site() -> list[dict[str, Any]]:
    api_base = os.getenv("API_BASE_URL", "").rstrip("/")
    if not api_base:
        return []
    url = f"{api_base}/api/heat-radar/accounts"
    try:
        with httpx.Client(timeout=60) as client:
            resp = client.get(url)
            resp.raise_for_status()
            raw_accounts = _extract_accounts_list(resp.json())
    except Exception as exc:
        print(f"读取主网站账号库失败，改用本地 accounts.seed.json：{exc}")
        return []
    accounts = [a for a in (_normalize_account(x) for x in raw_accounts if isinstance(x, dict)) if a]
    print(f"从主网站账号库读取到 {len(accounts)} 个可采集抖音账号。")
    return accounts


def load_accounts(path: str | Path = "accounts.seed.json") -> list[dict[str, Any]]:
    # 默认从主网站账号库读取；accounts.seed.json 只是离线兜底，不再作为主账号库。
    source = os.getenv("ACCOUNT_SOURCE", "site").lower()
    if source != "local":
        site_accounts = load_accounts_from_site()
        if site_accounts:
            return site_accounts
    local_accounts = load_local_accounts(path)
    print(f"使用本地账号文件 {path}，可采集账号 {len(local_accounts)} 个。")
    return local_accounts


def first_url_from_text(text: str) -> str:
    match = re.search(r"https?://[^\s，。！？!！；;）)]+", str(text or ""), re.I)
    return match.group(0).rstrip("，。!！;；") if match else ""


async def looks_like_login_or_verify(page: Page) -> bool:
    """Conservative Douyin login/verification detector.

    Douyin profile pages may contain hidden/login-related copy even when the
    user is already logged in. Treat it as login/verify only when there is a
    clear blocking overlay and no visible profile/work grid.
    """
    try:
        current_url = (page.url or "").lower()
        if "passport" in current_url or "login" in current_url or "verify" in current_url:
            return True
    except Exception:
        pass

    js = r'''
    () => {
      const body = document.body;
      const text = (body && body.innerText || '').slice(0, 12000);
      const hasProfileSignals = /作品\s*\d+/.test(text) || /粉丝\s*[\d.万wW]+/.test(text) || /获赞\s*[\d.万wW]+/.test(text);
      const hasWorkTab = text.includes('作品') && (text.includes('推荐') || text.includes('喜欢'));
      const hasVisibleCards = Array.from(document.querySelectorAll('div, a, img, video')).some((el) => {
        const r = el.getBoundingClientRect && el.getBoundingClientRect();
        if (!r || r.width < 60 || r.height < 60) return false;
        const t = (el.innerText || el.getAttribute('alt') || el.getAttribute('title') || el.getAttribute('aria-label') || '').trim();
        return /置顶|#|\d+/.test(t);
      });
      if (hasProfileSignals || hasWorkTab || hasVisibleCards) return false;
      const blockingLogin = /(扫码登录|手机登录|验证码登录|请登录|登录后|安全验证|滑块|拖动滑块|验证身份|login|captcha|verify)/i.test(text);
      return blockingLogin;
    }
    '''
    try:
        result = await page.evaluate(js)
        return bool(result)
    except Exception:
        pass

    text = ""
    try:
        text = (await page.locator("body").inner_text(timeout=3000))[:3000]
    except Exception:
        pass
    return any(k in text for k in ["扫码登录", "验证码登录", "请登录", "安全验证", "滑块", "captcha"])


async def extract_account_name(page: Page, fallback: str) -> str:
    candidates: list[str] = []
    for selector in ["h1", "[class*=nickname]", "[class*=name]", "title"]:
        try:
            if selector == "title":
                value = await page.title()
            else:
                value = await page.locator(selector).first.inner_text(timeout=1000)
            value = re.sub(r"[\n\r\t]+", " ", value or "").strip()
            if value:
                candidates.append(value.replace(" - 抖音", "").replace("的抖音", ""))
        except Exception:
            continue
    return candidates[0][:80] if candidates else fallback



def _safe_int(value: Any) -> int | str:
    try:
        if value in (None, ""):
            return ""
        return int(float(value))
    except Exception:
        return ""


def _format_create_time(value: Any) -> str:
    try:
        ts = int(float(value))
        if ts <= 0:
            return ""
        # 抖音 create_time 通常是秒级时间戳；太大的按毫秒处理。
        if ts > 10_000_000_000:
            ts = ts // 1000
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
    except Exception:
        return ""


def _pick_url_list(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("url_list", "urls", "urlList"):
            urls = value.get(key)
            if isinstance(urls, list) and urls:
                return str(urls[0])
        for key in ("uri", "url"):
            if value.get(key):
                return str(value.get(key))
    if isinstance(value, list) and value:
        return str(value[0])
    return ""


def _video_from_aweme(obj: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize a Douyin aweme-like object to our video item shape."""
    if not isinstance(obj, dict):
        return None
    aweme_id = str(obj.get("aweme_id") or obj.get("awemeId") or obj.get("id") or "").strip()
    desc = str(obj.get("desc") or obj.get("title") or obj.get("caption") or obj.get("text") or "").strip()
    # 部分接口外层是 item/aweme_info。
    if not aweme_id and isinstance(obj.get("aweme_info"), dict):
        return _video_from_aweme(obj.get("aweme_info") or {})
    if not aweme_id and isinstance(obj.get("aweme"), dict):
        return _video_from_aweme(obj.get("aweme") or {})
    if not aweme_id:
        return None
    stat = obj.get("statistics") or obj.get("stats") or obj.get("stat") or {}
    video = obj.get("video") or {}
    cover = ""
    video_play_url = ""
    if isinstance(video, dict):
        cover = _pick_url_list(video.get("cover")) or _pick_url_list(video.get("origin_cover")) or _pick_url_list(video.get("dynamic_cover"))
        # 页面/API 里如果已经有 play_addr/download_addr，先带给后面的解析层；没有也没关系。
        video_play_url = (
            _pick_url_list(video.get("play_addr"))
            or _pick_url_list(video.get("playAddr"))
            or _pick_url_list(video.get("download_addr"))
            or _pick_url_list(video.get("downloadAddr"))
            or _pick_url_list(video.get("bit_rate"))
        )
    published_at = _format_create_time(obj.get("create_time") or obj.get("createTime"))
    video_url = f"https://www.douyin.com/video/{aweme_id}"
    return {
        "video_url": normalize_video_url(video_url),
        "video_title": re.sub(r"\s+", " ", desc or aweme_id).strip()[:160],
        "published_at": published_at,
        "thumbnail_url": cover,
        "video_play_url": video_play_url,
        "is_pinned": bool(obj.get("is_top") or obj.get("isTop") or obj.get("is_pinned") or obj.get("isPinned")),
        "like_count": _safe_int(stat.get("digg_count") or stat.get("diggCount") or stat.get("like_count")),
        "comment_count": _safe_int(stat.get("comment_count") or stat.get("commentCount")),
        "favorite_count": _safe_int(stat.get("collect_count") or stat.get("collectCount") or stat.get("favorite_count")),
        "share_count": _safe_int(stat.get("share_count") or stat.get("shareCount")),
        "view_count": _safe_int(stat.get("play_count") or stat.get("playCount") or stat.get("view_count")),
        "raw_text": desc,
    }


def _walk_aweme_objects(data: Any, limit: int = 120) -> list[dict[str, Any]]:
    """Recursively search API/state JSON for aweme/video objects."""
    found: list[dict[str, Any]] = []
    seen_obj: set[int] = set()

    def walk(x: Any, depth: int) -> None:
        if len(found) >= limit or depth > 12:
            return
        if isinstance(x, dict):
            obj_id = id(x)
            if obj_id in seen_obj:
                return
            seen_obj.add(obj_id)
            item = _video_from_aweme(x)
            if item:
                found.append(item)
            # 常见列表字段优先走，减少无意义遍历。
            priority_keys = [
                "aweme_list", "awemeList", "aweme_list_resp", "post", "items", "list",
                "data", "item_list", "itemList", "user_post", "userPost", "video_list", "videoList",
            ]
            for key in priority_keys:
                if key in x:
                    walk(x.get(key), depth + 1)
            for key, value in list(x.items())[:300]:
                if key not in priority_keys:
                    walk(value, depth + 1)
        elif isinstance(x, list):
            for value in x[:300]:
                walk(value, depth + 1)

    walk(data, 0)
    return found


def _dedupe_videos(videos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in videos:
        url = normalize_video_url(str(item.get("video_url") or ""))
        if not url or url in seen:
            continue
        seen.add(url)
        copied = dict(item)
        copied["video_url"] = url
        deduped.append(copied)
    return deduped


async def setup_douyin_network_capture(page: Page) -> tuple[list[dict[str, Any]], list[asyncio.Task[Any]]]:
    """Capture Douyin JSON responses while the page loads.

    公开采集项目通常不是只读 DOM，而是结合 Playwright 登录态 + 页面接口响应。
    我们只采公开视频元数据，下载和视频理解交给主站后端。
    """
    captured: list[dict[str, Any]] = []
    tasks: list[asyncio.Task[Any]] = []

    async def handle_response(resp: Any) -> None:
        url = getattr(resp, "url", "") or ""
        if "douyin.com" not in url:
            return
        # 用户主页作品列表、详情、推荐流等接口通常都含 aweme/post/item/detail。
        if not any(k in url.lower() for k in ("aweme", "post", "item", "detail", "feed", "search")):
            return
        try:
            data = await resp.json()
        except Exception:
            return
        captured.extend(_walk_aweme_objects(data))

    def on_response(resp: Any) -> None:
        tasks.append(asyncio.create_task(handle_response(resp)))

    page.on("response", on_response)
    return captured, tasks


async def settle_and_scroll_profile(page: Page) -> None:
    """Give Douyin time to hydrate and scroll enough for recent videos to appear."""
    await page.wait_for_load_state("domcontentloaded", timeout=60000)
    await page.wait_for_timeout(4000)
    for _ in range(5):
        try:
            await page.mouse.wheel(0, 900)
        except Exception:
            pass
        await page.wait_for_timeout(1800)
    # 再回到顶部附近，避免停在空白处。
    try:
        await page.evaluate("window.scrollTo(0, 0)")
    except Exception:
        pass
    await page.wait_for_timeout(1200)


async def extract_videos_from_frontend_state(page: Page) -> list[dict[str, Any]]:
    """Read hydrated React/SSR state from Douyin page, then normalize in Python."""
    js = r"""
    () => {
      const out = [];
      const seen = new WeakSet();
      const roots = [];
      for (const key of [
        '__INITIAL_STATE__', '__UNIVERSAL_DATA_FOR_REHYDRATION__',
        'RENDER_DATA', '_ROUTER_DATA', 'SIGI_STATE', '__data'
      ]) {
        try { if (window[key]) roots.push(window[key]); } catch (e) {}
      }
      function addFromObject(o) {
        if (!o || typeof o !== 'object') return;
        const id = String(o.aweme_id || o.awemeId || o.id || '');
        const desc = String(o.desc || o.title || o.caption || o.text || '');
        const stat = o.statistics || o.stats || o.stat || {};
        const video = o.video || {};
        const coverObj = video.cover || video.origin_cover || video.dynamic_cover || {};
        const coverList = coverObj.url_list || coverObj.urls || coverObj.urlList || [];
        if (id && (desc || video || stat)) {
          out.push({
            aweme_id: id,
            desc,
            create_time: o.create_time || o.createTime || '',
            is_top: o.is_top || o.isTop || o.is_pinned || o.isPinned || false,
            statistics: stat,
            video: { cover: { url_list: Array.isArray(coverList) ? coverList.slice(0, 1) : [] } }
          });
        }
      }
      function visit(x, depth) {
        if (!x || depth > 12 || out.length > 160) return;
        if (Array.isArray(x)) {
          for (const v of x.slice(0, 300)) visit(v, depth + 1);
          return;
        }
        if (typeof x === 'object') {
          if (seen.has(x)) return;
          seen.add(x);
          addFromObject(x);
          const keys = Object.keys(x).slice(0, 300);
          for (const k of keys) visit(x[k], depth + 1);
        }
      }
      for (const r of roots) visit(r, 0);
      return out;
    }
    """
    try:
        raw = await page.evaluate(js)
    except Exception:
        raw = []
    return _walk_aweme_objects(raw)


async def extract_videos_from_html(page: Page) -> list[dict[str, Any]]:
    try:
        html = await page.content()
    except Exception:
        return []
    videos: list[dict[str, Any]] = []
    ids: set[str] = set()
    for pattern in [r'"aweme_id"\s*:\s*"?(\d{12,})"?', r'/video/(\d{12,})', r'modal_id=(\d{12,})']:
        for match in re.finditer(pattern, html):
            aweme_id = match.group(1)
            if aweme_id in ids:
                continue
            ids.add(aweme_id)
            start = max(0, match.start() - 600)
            end = min(len(html), match.end() + 1200)
            chunk = html[start:end]
            title = ""
            for title_pattern in [r'"desc"\s*:\s*"([^"]{1,180})"', r'"title"\s*:\s*"([^"]{1,180})"']:
                m = re.search(title_pattern, chunk)
                if m:
                    title = m.group(1)
                    break
            title = title.encode('utf-8', 'ignore').decode('unicode_escape', 'ignore') if '\\u' in title else title
            videos.append({
                "video_url": f"https://www.douyin.com/video/{aweme_id}",
                "video_title": re.sub(r"\s+", " ", title or aweme_id).strip()[:160],
                "published_at": "",
                "thumbnail_url": "",
                "is_pinned": "置顶" in chunk or '"is_top":true' in chunk,
                "raw_text": title,
            })
    return videos

async def extract_video_links(page: Page, network_videos: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Best-effort extraction from current Douyin profile/video page.

    Order:
    1. Current URL if it is a video page.
    2. Network JSON captured from Douyin aweme/post/detail APIs.
    3. Hydrated frontend state on window.
    4. HTML/script fallback.
    5. Visible DOM links fallback.
    """
    normalized: list[dict[str, Any]] = []

    # 1) Current page is a video page.
    try:
        current_url = page.url or ""
        m = re.search(r"video/(\d+)", current_url) or re.search(r"modal_id=(\d+)", current_url)
        if m:
            title = (await page.title()) or "抖音视频"
            normalized.append({
                "video_url": normalize_video_url(f"https://www.douyin.com/video/{m.group(1)}"),
                "video_title": re.sub(r"\s+", " ", title).replace(" - 抖音", "").strip()[:160],
                "published_at": "",
                "thumbnail_url": "",
                "is_pinned": False,
                "raw_text": title,
            })
    except Exception:
        pass

    # 2) Network API captured videos.
    if network_videos:
        normalized.extend(network_videos)

    # 3) Frontend hydrated state.
    normalized.extend(await extract_videos_from_frontend_state(page))

    # 4) HTML/script fallback.
    normalized.extend(await extract_videos_from_html(page))

    # 5) DOM fallback.
    locator = page.locator('a[href*="/video/"], a[href*="modal_id="]')
    try:
        count = min(await locator.count(), 120)
    except Exception:
        count = 0
    for i in range(count):
        a = locator.nth(i)
        try:
            href = (await a.get_attribute("href")) or ""
            if href.startswith("/"):
                href = "https://www.douyin.com" + href
            m = re.search(r"video/(\d+)", href) or re.search(r"modal_id=(\d+)", href)
            if not m:
                continue
            # Parent text is often richer than anchor text.
            raw_text = ""
            try:
                raw_text = await a.evaluate("""
                el => {
                  let n = el;
                  for (let i = 0; i < 6 && n; i++, n = n.parentElement) {
                    const t = (n.innerText || '').trim();
                    if (t.length > 10) return t;
                  }
                  return (el.innerText || el.getAttribute('title') || el.getAttribute('aria-label') || '').trim();
                }
                """)
            except Exception:
                raw_text = ""
            title_attr = (await a.get_attribute("title")) or (await a.get_attribute("aria-label")) or ""
            title = (title_attr or raw_text.split("\n")[0] if raw_text else "").strip()
            if not title or title in {"作品", "视频"} or re.fullmatch(r"\d+", title):
                title = raw_text[:80] or m.group(1)
            published_at = ""
            for pattern in [r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", r"\d{1,2}[-/]\d{1,2}", r"\d+天前", r"昨天", r"今天", r"小时前", r"分钟前"]:
                mm = re.search(pattern, raw_text)
                if mm:
                    published_at = mm.group(0)
                    break
            normalized.append({
                "video_url": normalize_video_url(f"https://www.douyin.com/video/{m.group(1)}"),
                "video_title": title[:160],
                "published_at": published_at,
                "thumbnail_url": "",
                "is_pinned": "置顶" in raw_text,
                "raw_text": raw_text,
            })
        except Exception:
            continue

    # 6) Visible card DOM fallback: Douyin often renders cards as clickable divs
    # without normal anchor hrefs. Extract title/like/pinned from visible cards and
    # pair them with collected video IDs in DOM order.
    try:
        cards = await page.evaluate(r'''
        () => {
          const out = [];
          const nodes = Array.from(document.querySelectorAll('div')).filter((el) => {
            const r = el.getBoundingClientRect && el.getBoundingClientRect();
            if (!r || r.width < 120 || r.height < 120) return false;
            const t = (el.innerText || '').trim();
            return t && (t.includes('置顶') || /#/.test(t) || /\d+/.test(t)) && r.top > 250;
          });
          for (const el of nodes.slice(0, 80)) {
            const text = (el.innerText || '').replace(/\s+/g, ' ').trim();
            if (!text || text.length < 3) continue;
            const html = el.outerHTML || '';
            const idMatch = html.match(/(?:video\/|modal_id=|aweme_id["']?[:=]["']?)(\d{12,})/);
            const likeMatch = text.match(/(?:^|\s)(\d+(?:\.\d+)?[万wW]?)(?:\s|$)/);
            out.push({
              id: idMatch ? idMatch[1] : '',
              text,
              like: likeMatch ? likeMatch[1] : '',
              is_pinned: text.includes('置顶')
            });
          }
          return out;
        }
        ''')
        existing_ids = []
        for item in normalized:
            m = re.search(r"video/(\d{12,})", str(item.get("video_url") or ""))
            if m:
                existing_ids.append(m.group(1))
        for idx, card in enumerate(cards or []):
            aweme_id = str(card.get("id") or (existing_ids[idx] if idx < len(existing_ids) else "")).strip()
            if not aweme_id:
                continue
            text = re.sub(r"\s+", " ", str(card.get("text") or "")).strip()
            title = re.sub(r"^(置顶\s*)?", "", text).strip()[:160] or aweme_id
            like_raw = str(card.get("like") or "").strip()
            like_count: Any = ""
            if like_raw:
                try:
                    like_count = int(float(like_raw.lower().replace('w','').replace('万','')) * (10000 if ('万' in like_raw or 'w' in like_raw.lower()) else 1))
                except Exception:
                    like_count = ""
            normalized.append({
                "video_url": normalize_video_url(f"https://www.douyin.com/video/{aweme_id}"),
                "video_title": title,
                "published_at": "",
                "thumbnail_url": "",
                "is_pinned": bool(card.get("is_pinned")),
                "like_count": like_count,
                "comment_count": "",
                "favorite_count": "",
                "share_count": "",
                "view_count": "",
                "raw_text": text,
            })
    except Exception:
        pass

    return _dedupe_videos(normalized)


def _merge_video_detail(base: dict[str, Any], detail: dict[str, Any]) -> dict[str, Any]:
    """Merge richer detail-page metadata into an existing profile-card item."""
    merged = dict(base)
    for key in [
        "video_title", "published_at", "thumbnail_url", "video_play_url",
        "resolved_video_url", "raw_text", "download_method", "analysis_mode",
        "video_download_status", "video_download_error",
    ]:
        value = detail.get(key)
        if value not in (None, "", [], {}):
            old = merged.get(key)
            # Prefer detail title only when it is not a generic browser title or it is longer.
            if key == "video_title" and old and len(str(old)) >= len(str(value)) and "抖音" not in str(old):
                continue
            merged[key] = value
    for key in ["like_count", "comment_count", "favorite_count", "share_count", "view_count"]:
        value = detail.get(key)
        if value not in (None, "", 0, "0"):
            merged[key] = value
    if detail.get("is_pinned"):
        merged["is_pinned"] = True
    return merged


def _video_id_from_url(url: str) -> str:
    match = re.search(r"(?:video/|modal_id=)(\d{10,})", str(url or ""))
    return match.group(1) if match else ""


async def enrich_video_with_own_page(context: BrowserContext, video: dict[str, Any], account: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    """Open one isolated page for one video, capture Network/SSR/DOM, then close it.

    This is deliberately sequential and conservative: one page handles one video, then
    the caller uploads that video before moving to the next account. If Douyin blocks
    the detail page, we return the original profile-level metadata instead of losing it.
    """
    video_url = normalize_video_url(str(video.get("video_url") or ""))
    if not video_url:
        return video
    page: Page | None = None
    try:
        page = await context.new_page()
        network_videos, network_tasks = await setup_douyin_network_capture(page)
        await page.goto(video_url, wait_until="domcontentloaded", timeout=int(cfg.get("video_page_timeout_ms") or 60000))
        await page.wait_for_timeout(int(cfg.get("video_page_wait_ms") or 4500))
        if network_tasks:
            await asyncio.gather(*network_tasks, return_exceptions=True)
        details = await extract_video_links(page, network_videos=network_videos)
        target_id = _video_id_from_url(video_url)
        chosen: dict[str, Any] | None = None
        if target_id:
            for item in details:
                if _video_id_from_url(str(item.get("video_url") or "")) == target_id:
                    chosen = item
                    break
        if not chosen and details:
            chosen = details[0]
        if chosen:
            video = _merge_video_detail(video, chosen)
            video["download_method"] = video.get("download_method") or "page_network"
            report_event(
                "video_page_captured",
                f"单视频页面采集成功：{video.get('video_title') or video_url}",
                account_name=str(account.get("name") or ""),
                account_url=str(account.get("url") or ""),
                video_title=str(video.get("video_title") or ""),
                video_url=video_url,
            )
        else:
            video.setdefault("video_download_status", "text_fallback")
            video.setdefault("analysis_mode", "text_fallback")
            video["video_download_error"] = (str(video.get("video_download_error") or "") + " | 单视频页未抓到详情").strip(" |")
        return video
    except Exception as exc:
        video.setdefault("analysis_mode", "text_fallback")
        video.setdefault("video_download_status", "text_fallback")
        video["video_download_error"] = (str(video.get("video_download_error") or "") + f" | 单视频页采集失败：{type(exc).__name__}: {exc}").strip(" |")[-1500:]
        report_event(
            "video_page_failed",
            f"单视频页面采集失败，保留主页数据：{video.get('video_title') or video_url}",
            level="warning",
            account_name=str(account.get("name") or ""),
            account_url=str(account.get("url") or ""),
            video_title=str(video.get("video_title") or ""),
            video_url=video_url,
            error_detail=str(exc)[:1000],
        )
        return video
    finally:
        if page:
            await page.close()


async def enrich_selected_videos(context: BrowserContext, selected: list[dict[str, Any]], account: dict[str, Any], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    if os.getenv("PER_VIDEO_PAGE_ENABLED", "true").strip().lower() in {"0", "false", "no", "off"}:
        return selected
    limit = int(os.getenv("PER_VIDEO_PAGE_LIMIT", str(len(selected))) or len(selected))
    enriched: list[dict[str, Any]] = []
    for idx, item in enumerate(selected, start=1):
        if idx <= limit and item.get("video_url"):
            print(f"  [{idx}/{len(selected)}] 单视频页面采集：{str(item.get('video_title') or item.get('video_url'))[:80]}")
            item = await enrich_video_with_own_page(context, dict(item), account, cfg)
        enriched.append(item)
    return enriched


def upload_rows_immediately(rows: list[dict[str, Any]], dry_run: bool = False) -> dict[str, Any]:
    """Upload current account rows immediately so a later account/page cannot wipe the batch."""
    accounts = excel_rows_to_accounts(rows)
    if not accounts or not any(a.get("recent_items") for a in accounts):
        return {"ok": False, "sent": 0, "reason": "no_real_video_rows"}
    return upload_video_intake(accounts, dry_run=dry_run)

def apply_video_strategy(videos: list[dict[str, Any]], pinned_limit: int, recent_days: int, fallback_limit: int) -> list[dict[str, Any]]:
    pinned = [v for v in videos if v.get("is_pinned")][:pinned_limit]
    recent = [v for v in videos if not v.get("is_pinned") and within_recent_days(v.get("published_at"), recent_days)]
    selected: list[dict[str, Any]] = []
    seen = set()
    for v in pinned + recent:
        key = v.get("video_url")
        if key and key not in seen:
            selected.append(v)
            seen.add(key)
    if len([v for v in selected if not v.get("is_pinned")]) == 0:
        for v in videos:
            key = v.get("video_url")
            if key and key not in seen:
                selected.append(v)
                seen.add(key)
            if len(selected) >= pinned_limit + fallback_limit:
                break
    return selected


async def crawl_one_account(context: BrowserContext, account: dict[str, Any], cfg: dict[str, Any], state: CollectorState) -> list[dict[str, Any]]:
    page = await context.new_page()
    raw_url = str(account.get("url") or "").strip()
    account_name = str(account.get("name") or "").strip() or "未命名账号"
    tags = ",".join(split_tags(account.get("tags")))
    notes = str(account.get("notes") or "").strip()
    # 如果账号库里还是 REPLACE_ME，就从备注里抓第一个分享链接，避免空跑。
    url = raw_url
    if (not url) or "REPLACE_ME" in url:
        url = first_url_from_text(notes) or raw_url
    try:
        if not url or "REPLACE_ME" in url:
            raise RuntimeError("账号 URL 为空或仍是 REPLACE_ME，请在 accounts.seed.json 填真实主页/视频分享链接")
        network_videos, network_tasks = await setup_douyin_network_capture(page)
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await settle_and_scroll_profile(page)
        if network_tasks:
            await asyncio.gather(*network_tasks, return_exceptions=True)
        if await looks_like_login_or_verify(page):
            # 全自动模式：不再卡住等待 Enter。
            # 只有显式传 --manual-login 或 MANUAL_LOGIN=true 时，才允许人工处理验证码。
            if cfg.get("manual_login") and not cfg["headless"]:
                print(f"检测到登录/验证页：{account_name}。请在浏览器中完成登录/验证。")
                input("完成后回到这个黑窗口按回车继续；没有完成就不要按：")
                await settle_and_scroll_profile(page)
                if network_tasks:
                    await asyncio.gather(*network_tasks, return_exceptions=True)
            else:
                wait_s = int(cfg.get("auto_verify_wait_seconds") or 0)
                print(f"检测到登录/验证页：{account_name}。全自动模式不等待人工，等待 {wait_s} 秒后跳过该账号。")
                report_event(
                    "account_verify_required",
                    f"账号需要登录/验证，自动跳过：{account_name}",
                    level="warning",
                    account_name=account_name,
                    account_url=url,
                    error_detail="douyin_login_or_verify_required",
                )
                if wait_s > 0:
                    await page.wait_for_timeout(wait_s * 1000)
                    await settle_and_scroll_profile(page)
                    if network_tasks:
                        await asyncio.gather(*network_tasks, return_exceptions=True)
            if await looks_like_login_or_verify(page):
                state.mark_account(url, "login_or_verify")
                return [
                    {
                        "platform": account.get("platform", "抖音"),
                        "account_name": account_name,
                        "account_url": url,
                        "account_id": "",
                        "followers_count": "",
                        "total_likes": "",
                        "last_post_at": "",
                        "video_title": "",
                        "video_url": "",
                        "published_at": "",
                        "like_count": "",
                        "comment_count": "",
                        "favorite_count": "",
                        "share_count": "",
                        "view_count": "",
                        "thumbnail_url": "",
                        "resolved_video_url": "",
                        "video_play_url": "",
                        "analysis_mode": "text_fallback",
                        "video_download_status": "empty",
                        "video_download_error": "",
                        "download_method": "",
                        "is_pinned": "",
                        "tags": tags,
                        "notes": f"需要人工登录/验证。{notes}",
                    }
                ]
        account_name = await extract_account_name(page, account_name)
        videos = await extract_video_links(page, network_videos=network_videos)
        selected = apply_video_strategy(
            videos,
            pinned_limit=int(cfg["pinned_limit"]),
            recent_days=int(cfg["recent_days"]),
            fallback_limit=int(cfg["fallback_recent_limit"]),
        )
        # 稳定版：每条视频单独开一个 page，抓 Network/页面注水/DOM，然后关页。
        # 这样不会因为一个主页滚动状态或一条视频卡住而丢掉整批。
        try:
            selected = await enrich_selected_videos(context, selected, account, cfg)
        except Exception as enrich_exc:
            print(f"单视频页面增强层异常，保留主页采集数据：{type(enrich_exc).__name__}: {enrich_exc}")
        # 多层视频解析：页面/API 直连 -> yt-dlp -> 自建 Cobalt -> 文案降级。
        # 失败不阻断采集，但会把 analysis_mode / video_download_status 带到后端和前端日志。
        last_video_resolve_error = ""
        try:
            selected = await resolve_videos_for_items(selected, page=page)
        except Exception as resolve_exc:
            last_video_resolve_error = f"{type(resolve_exc).__name__}: {resolve_exc}"
            print(f"视频解析层异常，降级为文案分析：{last_video_resolve_error}")
            for item in selected:
                item.setdefault("analysis_mode", "text_fallback")
                item.setdefault("video_download_status", "text_fallback")
                item["video_download_error"] = (str(item.get("video_download_error") or "") + f" | {last_video_resolve_error}").strip(" |")[-1500:]
        rows: list[dict[str, Any]] = []
        include_seen = cfg["include_seen"]
        for video in selected:
            video_url = video.get("video_url", "")
            if video_url and state.is_seen(video_url) and not include_seen:
                continue
            rows.append(
                {
                    "platform": account.get("platform", "抖音"),
                    "account_name": account_name,
                    "account_url": url,
                    "account_id": "",
                    "followers_count": "",
                    "total_likes": "",
                    "last_post_at": video.get("published_at", ""),
                    "video_title": video.get("video_title", ""),
                    "video_url": video_url,
                    "published_at": video.get("published_at", ""),
                    "like_count": video.get("like_count", ""),
                    "comment_count": video.get("comment_count", ""),
                    "favorite_count": video.get("favorite_count", ""),
                    "share_count": video.get("share_count", ""),
                    "view_count": video.get("view_count", ""),
                    "thumbnail_url": video.get("thumbnail_url", ""),
                    "resolved_video_url": video.get("resolved_video_url", ""),
                    "video_play_url": video.get("video_play_url", ""),
                    "analysis_mode": video.get("analysis_mode", "text_fallback"),
                    "video_download_status": video.get("video_download_status", "pending"),
                    "video_download_error": video.get("video_download_error", ""),
                    "download_method": video.get("download_method", ""),
                    "is_pinned": "是" if video.get("is_pinned") else "否",
                    "tags": tags,
                    "notes": notes,
                }
            )
        if not rows:
            rows.append(
                {
                    "platform": account.get("platform", "抖音"),
                    "account_name": account_name,
                    "account_url": url,
                    "account_id": "",
                    "followers_count": "",
                    "total_likes": "",
                    "last_post_at": "",
                    "video_title": "",
                    "video_url": "",
                    "published_at": "",
                    "like_count": "",
                    "comment_count": "",
                    "favorite_count": "",
                    "share_count": "",
                    "view_count": "",
                    "thumbnail_url": "",
                    "resolved_video_url": "",
                    "video_play_url": "",
                    "analysis_mode": "text_fallback",
                    "video_download_status": "empty",
                    "video_download_error": last_video_resolve_error,
                    "download_method": "",
                    "is_pinned": "",
                    "tags": tags,
                    "notes": f"未发现新增视频或全部已采集。{notes}",
                }
            )
        state.mark_account(url, "ok")
        return rows
    except Exception as exc:
        state.mark_account(url, "error")
        return [
            {
                "platform": account.get("platform", "抖音"),
                "account_name": account_name,
                "account_url": url,
                "account_id": "",
                "followers_count": "",
                "total_likes": "",
                "last_post_at": "",
                "video_title": "",
                "video_url": "",
                "published_at": "",
                "like_count": "",
                "comment_count": "",
                "favorite_count": "",
                "share_count": "",
                "view_count": "",
                "thumbnail_url": "",
                "is_pinned": "",
                "tags": tags,
                "notes": f"采集失败：{exc}",
            }
        ]
    finally:
        await page.close()


async def run_collector(args: argparse.Namespace) -> Path:
    load_dotenv()
    default_limit = int(os.getenv("BATCH_ACCOUNT_LIMIT", "1"))
    if getattr(args, "once", False):
        batch_limit = 1
    elif int(getattr(args, "limit", 0) or 0) > 0:
        batch_limit = int(getattr(args, "limit", 0) or 0)
    else:
        batch_limit = default_limit

    min_delay = int(os.getenv("MIN_DELAY_SECONDS", "8"))
    max_delay = int(os.getenv("MAX_DELAY_SECONDS", "18"))
    output_dir = Path(os.getenv("OUTPUT_DIR", "output"))
    state = CollectorState(os.getenv("STATE_DB", "collector_state.sqlite3"))
    accounts = load_accounts(args.accounts)

    account_keyword = str(getattr(args, "account", "") or "").strip().lower()
    if account_keyword:
        accounts = [
            a for a in accounts
            if account_keyword in str(a.get("name") or "").lower()
            or account_keyword in str(a.get("url") or "").lower()
            or account_keyword in str(a.get("notes") or "").lower()
        ]

    selected_accounts = state.choose_accounts(accounts, limit=batch_limit)
    if not selected_accounts:
        raise RuntimeError("没有可采集账号：请先在主网站账号库保存带抖音主页/分享链接的账号，或设置 ACCOUNT_SOURCE=local 后维护 accounts.seed.json")

    run_id = f"douyin_batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    state.start_run(run_id)
    cfg = {
        "headless": args.headless,
        "manual_login": bool(getattr(args, "manual_login", False)) or os.getenv("MANUAL_LOGIN", "false").lower() == "true",
        "auto_verify_wait_seconds": int(os.getenv("AUTO_VERIFY_WAIT_SECONDS", "8")),
        "pinned_limit": int(os.getenv("PINNED_LIMIT", "3")),
        "recent_days": int(os.getenv("RECENT_DAYS", "3")),
        "fallback_recent_limit": int(os.getenv("FALLBACK_RECENT_LIMIT", "6")),
        "include_seen": (os.getenv("SKIP_SEEN", "false").lower() != "true") or os.getenv("INCLUDE_SEEN", "false").lower() == "true" or args.include_seen,
        "video_page_timeout_ms": int(os.getenv("VIDEO_PAGE_TIMEOUT_MS", "60000")),
        "video_page_wait_ms": int(os.getenv("VIDEO_PAGE_WAIT_MS", "4500")),
    }

    rows: list[dict[str, Any]] = []
    try:
        async with async_playwright() as p:
            user_data_dir = os.getenv("USER_DATA_DIR", "profiles/douyin")
            context = await p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=args.headless,
                viewport={"width": 1366, "height": 900},
                locale="zh-CN",
            )
            # 每轮任务开始自动从当前 Chrome profile 导出新 cookies，给 yt-dlp / 解析层使用。
            await refresh_cookies_from_context(context)
            for idx, account in enumerate(selected_accounts):
                account_label = account.get('name') or account.get('url')
                print(f"[{idx + 1}/{len(selected_accounts)}] 采集：{account_label}")
                report_event("account_started", f"开始采集账号：{account_label}", account_name=str(account.get('name') or ''), account_url=str(account.get('url') or ''), progress={"total_accounts": len(selected_accounts), "completed_accounts": idx})
                before_count = len(rows)
                try:
                    account_rows = await crawl_one_account(context, account, cfg, state)
                    rows.extend(account_rows)
                    found_count = max(0, len(rows) - before_count)
                    report_event("account_finished", f"账号采集完成：{account_label}，发现 {found_count} 条视频", account_name=str(account.get('name') or ''), account_url=str(account.get('url') or ''), progress={"total_accounts": len(selected_accounts), "completed_accounts": idx + 1, "success_videos": len(rows)})
                    if os.getenv("IMMEDIATE_VIDEO_INTAKE", "true").lower() not in {"0", "false", "no", "off"}:
                        print("本账号采集完成，立即提交主网站分析；提交完再进入下一个账号。")
                        try:
                            upload_rows_immediately(account_rows, dry_run=bool(getattr(args, "dry_run", False)))
                        except Exception as upload_exc:
                            print(f"本账号即时上传失败，已保留 Excel，继续后续账号：{type(upload_exc).__name__}: {upload_exc}")
                            report_event("account_upload_failed", f"本账号即时上传失败：{account_label}", level="error", account_name=str(account.get('name') or ''), account_url=str(account.get('url') or ''), error_detail=str(upload_exc)[:1000])
                except Exception as exc:
                    report_event("account_failed", f"账号采集失败：{account_label}", level="error", account_name=str(account.get('name') or ''), account_url=str(account.get('url') or ''), error_detail=str(exc), progress={"total_accounts": len(selected_accounts), "completed_accounts": idx + 1})
                    raise
                if idx < len(selected_accounts) - 1:
                    if getattr(args, "no_delay", False):
                        delay = 0
                    else:
                        delay = random.randint(min_delay, max_delay)
                    if delay > 0:
                        print(f"等待 {delay} 秒后采集下一个账号…")
                        report_event("delay", f"限速等待 {delay} 秒；如需演示可勾选快速模式/--no-delay", progress={"total_accounts": len(selected_accounts), "completed_accounts": idx + 1})
                        await asyncio.sleep(delay)
                    else:
                        print("跳过账号间等待，继续采集下一个账号…")
            await context.close()
        output_path = output_dir / f"douyin_hot_accounts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        write_excel(rows, output_path)
        state.finish_run(run_id, "ok", f"rows={len(rows)} file={output_path}")
        print(f"Excel 已生成：{output_path}")
        return output_path
    except Exception as exc:
        state.finish_run(run_id, "error", str(exc))
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="跑一次采集")
    parser.add_argument("--headful", action="store_true", help="显示浏览器，适合第一次登录")
    parser.add_argument("--headless", action="store_true", help="无头运行")
    parser.add_argument("--include-seen", action="store_true", help="重复视频也写入 Excel")
    parser.add_argument("--accounts", default="accounts.seed.json")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--account", default="")
    parser.add_argument("--no-delay", action="store_true")
    parser.add_argument("--manual-login", action="store_true")
    args = parser.parse_args()
    load_dotenv()
    if not args.headful and not args.headless:
        args.headless = os.getenv("HEADLESS", "false").lower() == "true"
    if args.headful:
        args.headless = False
    lock_path = os.getenv("LOCK_FILE", "collector.lock")
    with SingleRunLock(lock_path):
        asyncio.run(run_collector(args))


if __name__ == "__main__":
    main()
