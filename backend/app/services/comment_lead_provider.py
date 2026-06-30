from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any


BASE_DIR = Path(os.getenv("AI_VIDEO_BACKEND_DIR", "/opt/ai-video/backend"))
DB_PATH = Path(os.getenv("AI_VIDEO_COMMENT_LEAD_DB_PATH", str(BASE_DIR / "data" / "comment-leads" / "comment_leads.sqlite3")))


BUY_WORDS = ["买房", "购房", "房价", "价格", "首付", "贷款", "月供", "预算", "户型", "公寓", "别墅", "看房", "楼盘", "买哪里", "怎么买"]
INVEST_WORDS = ["投资", "回报", "租金", "出租", "转手", "升值", "收益", "roi", "yield", "resale", "rental"]
LOCATION_WORDS = ["地段", "区域", "位置", "附近", "交通", "学校", "商场", "医院", "市中心", "地铁", "哪个区", "哪里"]
URGENCY_WORDS = ["现在", "马上", "近期", "今年", "下个月", "尽快", "急", "today", "now", "soon"]
QUESTION_WORDS = ["吗", "呢", "？", "?", "怎么", "多少", "哪里", "哪个", "靠谱吗", "值得", "可以"]
OBJECTION_WORDS = ["贵", "坑", "被骗", "不靠谱", "风险", "担心", "怕", "问题", "后悔", "踩坑"]
CONTACT_WORDS = ["私信", "联系", "微信", "电话", "whatsapp", "dm", "pm", "contact", "wx"]
COMPETITOR_WORDS = ["中介", "博主", "开发商", "房产号", "直播", "楼盘号"]


def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB_PATH)


def init_db():
    conn = _conn()
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS comment_leads (
            id TEXT PRIMARY KEY,
            created_at INTEGER,
            platform TEXT,
            source_url TEXT,
            video_title TEXT,
            author TEXT,
            text_redacted TEXT,
            lead_score INTEGER,
            priority TEXT,
            intents_json TEXT,
            capture_angle TEXT,
            suggested_action TEXT,
            reply_draft TEXT,
            raw_json TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def _clean(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())


def _redact(text: str) -> str:
    text = _clean(text)
    text = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[EMAIL_REDACTED]", text)
    text = re.sub(r"(\+?\d[\d\s\-]{7,}\d)", "[PHONE_REDACTED]", text)
    text = re.sub(r"(微信|vx|wechat|wx)[:：]?\s*[A-Za-z0-9_\-]{4,}", r"\1:[WECHAT_REDACTED]", text, flags=re.I)
    return text


def _contains_any(text: str, words: list[str]) -> bool:
    lower = text.lower()
    return any(w.lower() in lower for w in words)


def _detect_intents(text: str) -> list[str]:
    intents: list[str] = []

    if _contains_any(text, BUY_WORDS):
        intents.append("buying_intent")

    if _contains_any(text, INVEST_WORDS):
        intents.append("investment_intent")

    if _contains_any(text, LOCATION_WORDS):
        intents.append("location_interest")

    if _contains_any(text, URGENCY_WORDS):
        intents.append("urgency")

    if _contains_any(text, QUESTION_WORDS):
        intents.append("question")

    if _contains_any(text, OBJECTION_WORDS):
        intents.append("objection_or_pain")

    if _contains_any(text, CONTACT_WORDS):
        intents.append("contact_intent")

    if _contains_any(text, COMPETITOR_WORDS):
        intents.append("competitor_context")

    if not intents:
        intents.append("general_interest")

    return intents


def _score_comment(text: str, meta: dict[str, Any], intents: list[str]) -> int:
    score = 8

    weights = {
        "buying_intent": 28,
        "investment_intent": 22,
        "location_interest": 16,
        "urgency": 18,
        "question": 12,
        "objection_or_pain": 14,
        "contact_intent": 26,
        "competitor_context": 8,
        "general_interest": 4,
    }

    for intent in intents:
        score += weights.get(intent, 0)

    try:
        likes = int(meta.get("like_count") or meta.get("likes") or 0)
        replies = int(meta.get("reply_count") or meta.get("replies") or 0)
        score += min(10, likes // 5)
        score += min(8, replies * 2)
    except Exception:
        pass

    if len(text) >= 18:
        score += 5

    if len(text) >= 45:
        score += 5

    return max(0, min(100, score))


def _priority(score: int) -> str:
    if score >= 75:
        return "A"
    if score >= 55:
        return "B"
    if score >= 35:
        return "C"
    return "D"


def _capture_angle(intents: list[str]) -> str:
    if "contact_intent" in intents:
        return "主动联系型线索"
    if "buying_intent" in intents and "location_interest" in intents:
        return "买房区域决策"
    if "investment_intent" in intents:
        return "投资回报关注"
    if "objection_or_pain" in intents:
        return "避坑疑虑"
    if "question" in intents:
        return "评论区问答截流"
    return "泛兴趣线索"


def _suggested_action(score: int, intents: list[str]) -> str:
    if score >= 75:
        return "优先人工回复，并引导对方补充预算、区域、自住/投资需求。"
    if "question" in intents:
        return "公开评论区回答问题，避免硬广，最后追问一个筛选问题。"
    if "objection_or_pain" in intents:
        return "先共情风险点，再给出核验清单，不要直接推盘。"
    if "investment_intent" in intents:
        return "围绕租金回报、转手难度、区域供需做专业回复。"
    return "加入素材池观察，后续用于选题和脚本灵感。"


def _reply_draft(text: str, intents: list[str], context: dict[str, Any]) -> str:
    market = _clean(context.get("market") or "马来西亚")
    project = _clean(context.get("project") or "")
    project_part = f"{project} " if project else ""

    if "contact_intent" in intents:
        return f"可以，我建议先看你的预算、用途和目标区域。{project_part}具体价格和房源要以官方最新资料为准，你更偏自住还是投资？"

    if "buying_intent" in intents and "location_interest" in intents:
        return f"买{market}房子不能只看价格，区域、租金需求和未来转手都要一起看。你现在主要纠结哪个区域？我可以按自住/投资帮你拆一下。"

    if "investment_intent" in intents:
        return f"投资的话建议先看三点：租客来源、空置风险、未来转手难度。单看租金回报容易踩坑，你更关注稳定出租还是资产升值？"

    if "objection_or_pain" in intents:
        return f"这个担心很正常。买房前一定要核验开发商资料、交付时间、产权/贷款条件和周边真实配套，不能只看宣传图。你最担心哪一块？"

    if "question" in intents:
        return f"这个问题要看预算、用途和区域。{market}不同区域差别挺大，不能一概而论。你是考虑自住、投资，还是给孩子/家人配置？"

    return f"这个点很多人也会忽略。看房不能只看表面，区域、配套、租金和转手都要一起判断。"


def _normalize_comment(item: Any) -> dict[str, Any]:
    if isinstance(item, str):
        return {"text": item}

    if not isinstance(item, dict):
        return {"text": str(item)}

    text = item.get("text") or item.get("comment") or item.get("content") or item.get("body") or ""
    return {
        **item,
        "text": text,
    }


def analyze_comments(
    comments: list[Any],
    campaign_context: dict[str, Any] | None = None,
    save: bool = True,
    max_items: int = 200,
) -> dict[str, Any]:
    init_db()

    campaign_context = campaign_context or {}
    comments = comments or []

    if not comments:
        raise ValueError("comments 不能为空。请传入评论文本列表或评论对象列表。")

    comments = comments[: max(1, min(int(max_items or 200), 500))]

    leads: list[dict[str, Any]] = []

    for raw in comments:
        item = _normalize_comment(raw)
        text = _clean(item.get("text"))
        if not text:
            continue

        redacted = _redact(text)
        intents = _detect_intents(text)
        score = _score_comment(text, item, intents)
        pri = _priority(score)
        angle = _capture_angle(intents)
        action = _suggested_action(score, intents)
        draft = _reply_draft(text, intents, campaign_context)

        lead = {
            "lead_id": f"comment_lead_{uuid.uuid4().hex[:18]}",
            "platform": item.get("platform") or campaign_context.get("platform") or "",
            "source_url": item.get("source_url") or item.get("url") or campaign_context.get("source_url") or "",
            "video_title": item.get("video_title") or campaign_context.get("video_title") or "",
            "author": item.get("author") or item.get("username") or "",
            "text": redacted,
            "lead_score": score,
            "priority": pri,
            "intents": intents,
            "capture_angle": angle,
            "suggested_action": action,
            "reply_draft": draft,
            "material_tags": _material_tags(intents),
            "script_hook": _script_hook(intents),
            "raw_meta": {
                "like_count": item.get("like_count") or item.get("likes") or 0,
                "reply_count": item.get("reply_count") or item.get("replies") or 0,
                "created_at": item.get("created_at") or "",
            },
        }

        leads.append(lead)

    leads.sort(key=lambda x: x["lead_score"], reverse=True)

    if save:
        _save_leads(leads)

    intent_counts: dict[str, int] = {}
    for lead in leads:
        for intent in lead["intents"]:
            intent_counts[intent] = intent_counts.get(intent, 0) + 1

    return {
        "ok": True,
        "provider": "comment_lead_engine_v1",
        "status": "done",
        "total_comments": len(comments),
        "lead_count": len(leads),
        "a_priority_count": sum(1 for x in leads if x["priority"] == "A"),
        "b_priority_count": sum(1 for x in leads if x["priority"] == "B"),
        "intent_counts": intent_counts,
        "leads": leads,
        "message": "评论区线索分析完成：只做线索识别、优先级排序和人工回复建议，不自动私信、不自动批量评论。",
    }


def _material_tags(intents: list[str]) -> list[str]:
    tags = ["comment_lead"]

    if "buying_intent" in intents:
        tags.append("buyer")
    if "investment_intent" in intents:
        tags.append("investment")
    if "location_interest" in intents:
        tags.append("location")
    if "objection_or_pain" in intents:
        tags.append("pain_point")
    if "question" in intents:
        tags.append("faq")

    return tags


def _script_hook(intents: list[str]) -> str:
    if "objection_or_pain" in intents:
        return "很多人买海外房产踩坑，不是因为房子不好，而是因为没看懂这几个风险点。"
    if "investment_intent" in intents:
        return "海外房产投资别只看租金回报，真正影响转手的是这三个因素。"
    if "location_interest" in intents:
        return "同一个城市，不同区域的买房逻辑完全不一样。"
    if "buying_intent" in intents:
        return "第一次买海外房产，别急着问价格，先看这三件事。"
    return "评论区问得最多的问题，其实暴露了很多买房误区。"


def _save_leads(leads: list[dict[str, Any]]):
    conn = _conn()
    c = conn.cursor()
    now = int(time.time())

    for lead in leads:
        c.execute(
            """
            INSERT OR REPLACE INTO comment_leads (
                id, created_at, platform, source_url, video_title, author,
                text_redacted, lead_score, priority, intents_json,
                capture_angle, suggested_action, reply_draft, raw_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                lead["lead_id"],
                now,
                lead.get("platform") or "",
                lead.get("source_url") or "",
                lead.get("video_title") or "",
                lead.get("author") or "",
                lead.get("text") or "",
                int(lead.get("lead_score") or 0),
                lead.get("priority") or "",
                json.dumps(lead.get("intents") or [], ensure_ascii=False),
                lead.get("capture_angle") or "",
                lead.get("suggested_action") or "",
                lead.get("reply_draft") or "",
                json.dumps(lead, ensure_ascii=False),
            ),
        )

    conn.commit()
    conn.close()


def recent_leads(limit: int = 50) -> dict[str, Any]:
    init_db()
    limit = max(1, min(int(limit or 50), 200))

    conn = _conn()
    c = conn.cursor()
    c.execute(
        """
        SELECT raw_json
        FROM comment_leads
        ORDER BY created_at DESC, lead_score DESC
        LIMIT ?
        """,
        (limit,),
    )
    rows = c.fetchall()
    conn.close()

    leads = []
    for row in rows:
        try:
            leads.append(json.loads(row[0]))
        except Exception:
            pass

    return {
        "ok": True,
        "provider": "comment_lead_engine_v1",
        "count": len(leads),
        "leads": leads,
    }


def health() -> dict[str, Any]:
    return {
        "ok": True,
        "provider": "comment_lead_engine_v1",
        "message": "评论区线索引擎可用：分析公开评论/导出评论，识别买房意向、投资意向、疑虑点和高优先级跟进对象。",
        "features": [
            "comment_scoring",
            "intent_detection",
            "priority_ranking",
            "reply_draft",
            "script_hook",
            "lead_persistence",
            "no_auto_dm_no_auto_comment",
        ],
    }


def self_test() -> dict[str, Any]:
    return analyze_comments(
        comments=[
            {
                "platform": "tiktok",
                "author": "user_a",
                "text": "马来西亚买房首付大概要多少？哪个区域比较适合投资出租？",
                "like_count": 18,
                "reply_count": 3,
                "video_title": "马来西亚买房避坑",
            },
            {
                "platform": "tiktok",
                "author": "user_b",
                "text": "感觉海外房产水很深，怕踩坑，有没有靠谱的核验清单？",
                "like_count": 9,
                "reply_count": 1,
            },
            {
                "platform": "youtube",
                "author": "user_c",
                "text": "这个楼盘看起来不错",
                "like_count": 1,
                "reply_count": 0,
            },
        ],
        campaign_context={
            "market": "马来西亚",
            "video_title": "马来西亚买房避坑",
            "platform": "tiktok",
        },
        save=False,
    )
