from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any
import os


BASE_DIR = Path(os.getenv("AI_VIDEO_BACKEND_DIR", "/opt/ai-video/backend"))
DB_PATH = BASE_DIR / "data" / "openclaw-content" / "openclaw_content.sqlite3"


TITLE_KEYS = ["title", "video_title", "post_title", "caption", "desc", "description", "标题", "文案", "描述"]
URL_KEYS = ["url", "video_url", "post_url", "source_url", "share_url", "permalink", "link", "链接"]
AUTHOR_KEYS = ["author", "username", "user", "nickname", "account", "账号", "作者", "昵称"]
PLATFORM_KEYS = ["platform", "site", "channel", "source_platform", "平台"]
LIKE_KEYS = ["likes", "like_count", "digg_count", "点赞", "点赞数"]
COMMENT_KEYS = ["comments", "comment_count", "reply_count", "评论", "评论数"]
SHARE_KEYS = ["shares", "share_count", "转发", "分享数"]
VIEW_KEYS = ["views", "view_count", "play_count", "播放", "播放量"]
DURATION_KEYS = ["duration", "duration_seconds", "video_duration", "时长"]


HOOK_WORDS = ["别只看", "千万别", "避坑", "踩坑", "后悔", "真相", "普通人", "第一次", "一定要", "很多人", "没人告诉你"]
BUY_WORDS = ["买房", "购房", "房价", "首付", "贷款", "预算", "户型", "楼盘", "公寓", "别墅"]
INVEST_WORDS = ["投资", "租金", "回报", "收益", "出租", "转手", "升值", "roi", "yield"]
LOCATION_WORDS = ["地段", "区域", "位置", "学校", "商场", "交通", "市中心", "地铁", "周边"]
PAIN_WORDS = ["坑", "风险", "贵", "被骗", "不靠谱", "担心", "怕", "后悔"]
CTA_WORDS = ["私信", "评论", "收藏", "关注", "留言", "联系", "领取", "清单"]


def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB_PATH)


def init_db():
    conn = _conn()
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS openclaw_content_intel (
            id TEXT PRIMARY KEY,
            created_at INTEGER,
            platform TEXT,
            author TEXT,
            source_url TEXT,
            title TEXT,
            score INTEGER,
            topic_angle TEXT,
            content_type TEXT,
            tags_json TEXT,
            script_hook TEXT,
            shot_hint TEXT,
            raw_json TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def _clean(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "").strip())


def _first(item: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in item and item.get(key) not in (None, ""):
            return item.get(key)

    lower = {str(k).lower(): k for k in item.keys()}
    for key in keys:
        real = lower.get(key.lower())
        if real is not None and item.get(real) not in (None, ""):
            return item.get(real)

    return None


def _num(v: Any) -> int:
    if v is None:
        return 0
    if isinstance(v, (int, float)):
        return int(v)

    text = _clean(v).lower().replace(",", "")
    if not text:
        return 0

    mult = 1
    if text.endswith("k"):
        mult = 1000
        text = text[:-1]
    elif text.endswith("w") or text.endswith("万"):
        mult = 10000
        text = text[:-1]
    elif text.endswith("m"):
        mult = 1000000
        text = text[:-1]

    try:
        return int(float(text) * mult)
    except Exception:
        return 0


def _contains(text: str, words: list[str]) -> bool:
    t = text.lower()
    return any(w.lower() in t for w in words)


def _parse_json(obj: Any) -> list[Any]:
    if isinstance(obj, list):
        return obj

    if isinstance(obj, dict):
        for key in ["videos", "posts", "items", "data", "records", "rows", "results", "aweme_list"]:
            v = obj.get(key)
            if isinstance(v, list):
                return v

        for key in ["data", "result", "payload"]:
            v = obj.get(key)
            if isinstance(v, dict):
                nested = _parse_json(v)
                if nested:
                    return nested

        return [obj]

    return []


def _parse_csv(raw: str) -> list[dict[str, Any]]:
    text = raw.strip()
    if not text:
        return []

    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",\t;|")
    except Exception:
        dialect = csv.excel

    try:
        rows = [dict(r) for r in csv.DictReader(io.StringIO(text), dialect=dialect) if r]
    except Exception:
        rows = []

    return rows


def parse_export(raw_export: Any) -> list[Any]:
    if raw_export is None:
        return []

    if isinstance(raw_export, list):
        return raw_export

    if isinstance(raw_export, dict):
        return _parse_json(raw_export)

    raw = str(raw_export or "").strip()
    if not raw:
        return []

    try:
        return _parse_json(json.loads(raw))
    except Exception:
        pass

    rows = _parse_csv(raw)
    if rows:
        return rows

    return [{"title": x.strip()} for x in raw.splitlines() if x.strip()]


def normalize_item(item: Any, campaign_context: dict[str, Any] | None = None) -> dict[str, Any]:
    campaign_context = campaign_context or {}

    if isinstance(item, str):
        item = {"title": item}

    if not isinstance(item, dict):
        item = {"title": str(item)}

    title = _clean(_first(item, TITLE_KEYS))
    url = _clean(_first(item, URL_KEYS))
    author = _first(item, AUTHOR_KEYS)
    platform = _clean(_first(item, PLATFORM_KEYS)) or _clean(campaign_context.get("platform"))

    if isinstance(author, dict):
        author = author.get("nickname") or author.get("username") or author.get("name") or author.get("id")

    text_pool = " ".join(
        _clean(x)
        for x in [
            title,
            item.get("desc"),
            item.get("description"),
            item.get("caption"),
            item.get("ocr_text"),
            item.get("asr_text"),
        ]
        if x
    )

    return {
        "platform": platform,
        "author": _clean(author),
        "source_url": url or _clean(campaign_context.get("source_url")),
        "title": title,
        "text_pool": text_pool or title,
        "likes": _num(_first(item, LIKE_KEYS)),
        "comments": _num(_first(item, COMMENT_KEYS)),
        "shares": _num(_first(item, SHARE_KEYS)),
        "views": _num(_first(item, VIEW_KEYS)),
        "duration": _num(_first(item, DURATION_KEYS)),
        "raw": item,
    }


def score_item(item: dict[str, Any]) -> int:
    text = item["text_pool"]
    score = 10

    if _contains(text, HOOK_WORDS):
        score += 24
    if _contains(text, BUY_WORDS):
        score += 20
    if _contains(text, INVEST_WORDS):
        score += 18
    if _contains(text, LOCATION_WORDS):
        score += 14
    if _contains(text, PAIN_WORDS):
        score += 16
    if _contains(text, CTA_WORDS):
        score += 8

    likes = item.get("likes", 0)
    comments = item.get("comments", 0)
    shares = item.get("shares", 0)
    views = item.get("views", 0)

    score += min(15, likes // 100)
    score += min(20, comments // 10)
    score += min(10, shares // 20)
    score += min(10, views // 10000)

    if comments >= 20:
        score += 8

    if len(text) >= 20:
        score += 4

    return max(0, min(100, score))


def detect_angle(text: str) -> str:
    if _contains(text, PAIN_WORDS):
        return "避坑风险型"
    if _contains(text, INVEST_WORDS):
        return "投资回报型"
    if _contains(text, LOCATION_WORDS):
        return "区域决策型"
    if _contains(text, BUY_WORDS):
        return "买房决策型"
    if _contains(text, HOOK_WORDS):
        return "爆点钩子型"
    return "泛内容灵感型"


def detect_content_type(text: str) -> str:
    if "清单" in text or "步骤" in text or "流程" in text:
        return "checklist"
    if "对比" in text or "vs" in text.lower():
        return "comparison"
    if _contains(text, PAIN_WORDS):
        return "pain_point"
    if _contains(text, INVEST_WORDS):
        return "investment"
    return "education"


def tags_for(text: str) -> list[str]:
    tags = ["openclaw_content"]

    if _contains(text, BUY_WORDS):
        tags.append("buyer")
    if _contains(text, INVEST_WORDS):
        tags.append("investment")
    if _contains(text, LOCATION_WORDS):
        tags.append("location")
    if _contains(text, PAIN_WORDS):
        tags.append("risk")
    if _contains(text, HOOK_WORDS):
        tags.append("hook")
    if _contains(text, CTA_WORDS):
        tags.append("lead_capture")

    return tags


def script_hook_for(text: str, angle: str) -> str:
    if angle == "避坑风险型":
        return "很多人买海外房产踩坑，不是因为房子不好，而是因为一开始就看错了这几个点。"
    if angle == "投资回报型":
        return "海外房产投资别只看租金回报，真正决定能不能赚钱的是这三件事。"
    if angle == "区域决策型":
        return "同一个城市，不同区域的买房逻辑完全不一样，买错区域比买贵更可怕。"
    if angle == "买房决策型":
        return "第一次买海外房产，别急着问价格，先把这三个问题想清楚。"
    return "评论区问得最多的问题，其实暴露了一个很多人忽略的买房误区。"


def shot_hint_for(angle: str, content_type: str) -> str:
    if angle == "避坑风险型":
        return "problem_warning"
    if angle == "投资回报型":
        return "data_explain"
    if angle == "区域决策型":
        return "location_compare"
    if content_type == "checklist":
        return "checklist_steps"
    return "opening_hook"


def analyze_content(
    raw_export: Any = None,
    items: list[Any] | None = None,
    campaign_context: dict[str, Any] | None = None,
    save: bool = True,
    max_items: int = 300,
) -> dict[str, Any]:
    init_db()
    campaign_context = campaign_context or {}

    raw_items = items if items else parse_export(raw_export)
    if not raw_items:
        raise ValueError("没有解析到内容数据。请传 OpenClaw 导出的 JSON / CSV / 文本。")

    raw_items = raw_items[: max(1, min(int(max_items or 300), 1000))]

    insights = []

    for raw in raw_items:
        item = normalize_item(raw, campaign_context=campaign_context)
        text = item["text_pool"]
        if not text:
            continue

        score = score_item(item)
        angle = detect_angle(text)
        content_type = detect_content_type(text)
        tags = tags_for(text)
        hook = script_hook_for(text, angle)
        shot_hint = shot_hint_for(angle, content_type)

        insight = {
            "insight_id": f"openclaw_content_{uuid.uuid4().hex[:18]}",
            "platform": item["platform"],
            "author": item["author"],
            "source_url": item["source_url"],
            "title": item["title"],
            "score": score,
            "priority": "A" if score >= 75 else "B" if score >= 55 else "C" if score >= 35 else "D",
            "topic_angle": angle,
            "content_type": content_type,
            "tags": tags,
            "script_hook": hook,
            "shot_hint": shot_hint,
            "timeline_suggestion": {
                "opening": hook,
                "recommended_segments": [
                    "痛点/问题开场",
                    "核心判断标准",
                    "真实案例或对比",
                    "评论区引导问题",
                ],
            },
            "comment_capture_angle": comment_capture_angle(angle),
            "metrics": {
                "likes": item["likes"],
                "comments": item["comments"],
                "shares": item["shares"],
                "views": item["views"],
                "duration": item["duration"],
            },
            "raw": item["raw"],
        }

        insights.append(insight)

    insights.sort(key=lambda x: x["score"], reverse=True)

    if save:
        save_insights(insights)

    return {
        "ok": True,
        "provider": "openclaw_content_intel_v1",
        "status": "done",
        "count": len(insights),
        "a_priority_count": sum(1 for x in insights if x["priority"] == "A"),
        "b_priority_count": sum(1 for x in insights if x["priority"] == "B"),
        "insights": insights,
        "message": "OpenClaw 内容采集增强完成：把同行视频/帖子导出数据转成选题、脚本 hook、素材标签和 timeline shot_hint。",
    }


def comment_capture_angle(angle: str) -> str:
    if angle == "避坑风险型":
        return "你最担心海外买房哪一步踩坑？评论区打出来，我按风险点拆。"
    if angle == "投资回报型":
        return "你更关注租金回报还是未来转手？评论区说预算和区域。"
    if angle == "区域决策型":
        return "你正在看哪个区域？评论区发出来，我帮你判断适合自住还是投资。"
    return "你现在是自住、投资还是资产配置？评论区打出来。"


def save_insights(insights: list[dict[str, Any]]):
    conn = _conn()
    c = conn.cursor()
    now = int(time.time())

    for x in insights:
        c.execute(
            """
            INSERT OR REPLACE INTO openclaw_content_intel (
                id, created_at, platform, author, source_url, title,
                score, topic_angle, content_type, tags_json, script_hook,
                shot_hint, raw_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                x["insight_id"],
                now,
                x.get("platform") or "",
                x.get("author") or "",
                x.get("source_url") or "",
                x.get("title") or "",
                int(x.get("score") or 0),
                x.get("topic_angle") or "",
                x.get("content_type") or "",
                json.dumps(x.get("tags") or [], ensure_ascii=False),
                x.get("script_hook") or "",
                x.get("shot_hint") or "",
                json.dumps(x, ensure_ascii=False),
            ),
        )

    conn.commit()
    conn.close()


def health() -> dict[str, Any]:
    return {
        "ok": True,
        "provider": "openclaw_content_intel_v1",
        "message": "OpenClaw 内容采集增强可用：分析同行视频/帖子导出数据，产出选题、脚本 hook、素材标签、评论区截流角度。",
        "features": [
            "json_csv_text_parse",
            "topic_scoring",
            "script_hook_generation",
            "shot_hint_generation",
            "comment_capture_angle",
            "timeline_suggestion",
            "no_auto_scrape_no_auto_comment",
        ],
    }


def self_test() -> dict[str, Any]:
    csv_text = """author,title,likes,comments,shares,views,platform,url
agent_a,马来西亚买房千万别只看价格，这三个区域最容易踩坑,1200,88,42,56000,tiktok,https://example.com/v1
agent_b,海外房产投资租金回报到底怎么算？很多人第一步就错了,850,66,25,43000,tiktok,https://example.com/v2
agent_c,第一次买房首付预算怎么定？普通人一定要看,300,12,8,12000,youtube,https://example.com/v3
"""
    return analyze_content(
        raw_export=csv_text,
        campaign_context={"market": "马来西亚", "platform": "tiktok"},
        save=False,
    )
