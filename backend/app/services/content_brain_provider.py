from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, FastAPI, Query
from pydantic import BaseModel, Field

from app.config import get_settings
from app.services.storage import maybe_upload_to_r2

try:
    from app.services.comment_lead_provider import DB_PATH as COMMENT_LEAD_DB_PATH
except Exception:  # pragma: no cover
    COMMENT_LEAD_DB_PATH = Path("/opt/ai-video/backend/data/comment-leads/comment_leads.sqlite3")

BASE_DIR = Path(os.getenv("AI_VIDEO_BACKEND_DIR", "/opt/ai-video/backend"))
DB_PATH = Path(os.getenv("AI_VIDEO_CONTENT_BRAIN_DB_PATH", str(BASE_DIR / "data" / "content-brain" / "content_brain.sqlite3")))
EXPORT_DIR = BASE_DIR / "data" / "content-brain" / "exports"

router = APIRouter(prefix="/api/video/content-brain", tags=["content-brain"])

VALID_STATUS = {"pending", "approved", "rejected"}
VALID_TYPES = {"lead_question", "topic", "hook", "script", "visual_rule", "market_note", "reply_template"}

TYPE_LABELS = {
    "lead_question": "客户问题",
    "topic": "选题",
    "hook": "开头钩子",
    "script": "口播文案",
    "visual_rule": "画面规则",
    "market_note": "市场知识",
    "reply_template": "回复模板",
}


class BrainCardIn(BaseModel):
    title: str = ""
    type: str = "market_note"
    source: str = "manual_input"
    content: str = ""
    tags: list[str] = Field(default_factory=list)
    score: int = 70
    status: str = "pending"
    decisionReason: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)


class ImportMarkdownRequest(BaseModel):
    markdown: str
    source: str = "obsidian_markdown"
    status: str = "pending"


class StatusRequest(BaseModel):
    id: str = ""
    ids: list[str] = Field(default_factory=list)
    reason: str = ""


class LinkOpenClawRequest(BaseModel):
    limit: int = 80
    min_score: int = 55
    status: str = "pending"


class SuggestTopicsRequest(BaseModel):
    query: str = ""
    city: str = "吉隆坡"
    market: str = "马来西亚房产"
    content_type: str = "investment"
    limit: int = 12


def _now_ts() -> float:
    return time.time()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _json_loads(value: Optional[str], fallback: Any = None) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _clean(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())


def _split_tags(text: Any) -> list[str]:
    if isinstance(text, list):
        raw = " ".join(str(x) for x in text)
    else:
        raw = str(text or "")
    out: list[str] = []
    for item in re.split(r"[，,\n#\s/|]+", raw):
        item = item.strip()
        if item and item not in out:
            out.append(item)
    return out[:18]


def _uid(prefix: str = "brain") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:18]}"


def _normalize_type(value: str) -> str:
    v = str(value or "").strip()
    return v if v in VALID_TYPES else "market_note"


def _normalize_status(value: str) -> str:
    v = str(value or "").strip()
    return v if v in VALID_STATUS else "pending"


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS content_brain_cards (
                id TEXT PRIMARY KEY,
                title TEXT,
                card_type TEXT,
                source TEXT,
                content TEXT,
                tags_json TEXT,
                score INTEGER,
                status TEXT,
                decision_reason TEXT,
                raw_json TEXT,
                used_count INTEGER DEFAULT 0,
                created_at REAL,
                updated_at REAL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_content_brain_status ON content_brain_cards(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_content_brain_type ON content_brain_cards(card_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_content_brain_updated ON content_brain_cards(updated_at)")
        conn.commit()


def _row_to_card(row: sqlite3.Row) -> dict[str, Any]:
    tags = _json_loads(row["tags_json"], []) or []
    raw = _json_loads(row["raw_json"], {}) or {}
    return {
        "id": row["id"],
        "title": row["title"] or "",
        "type": row["card_type"] or "market_note",
        "type_label": TYPE_LABELS.get(row["card_type"], row["card_type"]),
        "source": row["source"] or "",
        "content": row["content"] or "",
        "tags": tags if isinstance(tags, list) else [],
        "score": int(row["score"] or 0),
        "status": row["status"] or "pending",
        "decisionReason": row["decision_reason"] or "",
        "decision_reason": row["decision_reason"] or "",
        "usedCount": int(row["used_count"] or 0),
        "used_count": int(row["used_count"] or 0),
        "createdAt": datetime.fromtimestamp(float(row["created_at"] or 0), tz=timezone.utc).isoformat() if row["created_at"] else "",
        "updatedAt": datetime.fromtimestamp(float(row["updated_at"] or 0), tz=timezone.utc).isoformat() if row["updated_at"] else "",
        "raw": raw,
    }


def _upsert_card(card: dict[str, Any]) -> dict[str, Any]:
    init_db()
    now = _now_ts()
    card_id = str(card.get("id") or _uid("brain"))
    title = _clean(card.get("title")) or _clean(card.get("content"))[:32] or "未命名知识"
    content = _clean(card.get("content")) or title
    card_type = _normalize_type(str(card.get("type") or card.get("card_type") or "market_note"))
    status = _normalize_status(str(card.get("status") or "pending"))
    tags = _split_tags(card.get("tags") or f"{title} {content}")
    score = max(0, min(int(card.get("score") or 70), 100))
    source = _clean(card.get("source") or "manual_input")
    decision = _clean(card.get("decisionReason") or card.get("decision_reason") or "等待人工判断是否进入内容大脑。")
    raw = card.get("raw") if isinstance(card.get("raw"), dict) else {}

    with _conn() as conn:
        old = conn.execute("SELECT created_at, used_count FROM content_brain_cards WHERE id=?", (card_id,)).fetchone()
        created = float(old["created_at"]) if old and old["created_at"] else now
        used_count = int(card.get("usedCount") or card.get("used_count") or (old["used_count"] if old else 0) or 0)
        conn.execute(
            """
            INSERT INTO content_brain_cards (
                id, title, card_type, source, content, tags_json, score, status,
                decision_reason, raw_json, used_count, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title=excluded.title,
                card_type=excluded.card_type,
                source=excluded.source,
                content=excluded.content,
                tags_json=excluded.tags_json,
                score=excluded.score,
                status=excluded.status,
                decision_reason=excluded.decision_reason,
                raw_json=excluded.raw_json,
                used_count=excluded.used_count,
                updated_at=excluded.updated_at
            """,
            (
                card_id, title, card_type, source, content, _json_dumps(tags), score, status,
                decision, _json_dumps(raw), used_count, created, now,
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM content_brain_cards WHERE id=?", (card_id,)).fetchone()
        return _row_to_card(row)


def _classify_markdown_block(block: str) -> tuple[str, int, list[str]]:
    lower = block.lower()
    card_type = "market_note"
    score = 70
    if re.search(r"评论|私信|客户|预算|能买吗|华语|华人|咨询|首付|贷款", block):
        card_type, score = "lead_question", 82
    if re.search(r"选题|主题|标题|话题|系列", block):
        card_type, score = "topic", 78
    if re.search(r"hook|开头|钩子|前三秒|反常识", lower):
        card_type, score = "hook", 80
    if re.search(r"镜头|画面|素材|b-roll|室内|阳台|大堂|泳池|客厅|卧室|厨房|看房", lower):
        card_type, score = "visual_rule", 76
    if re.search(r"回复|私信|评论区|话术", block):
        card_type, score = "reply_template", 74
    tags = _split_tags("马来西亚 吉隆坡 房产 客户问题 选题 镜头 " + block[:80])
    return card_type, score, tags


def markdown_to_cards(markdown: str, source: str = "obsidian_markdown", status: str = "pending") -> list[dict[str, Any]]:
    text = str(markdown or "").strip()
    if not text:
        return []
    blocks = [x.strip() for x in re.split(r"\n(?=#{1,4}\s)|\n---+\n|\n\s*\n+", text) if len(x.strip()) > 10]
    cards: list[dict[str, Any]] = []
    for block in blocks[:120]:
        title_match = re.search(r"^#{1,4}\s+(.+)$", block, flags=re.M)
        title = _clean(title_match.group(1) if title_match else block[:32])
        content = re.sub(r"^#{1,4}\s+", "", block, flags=re.M).strip()
        card_type, score, tags = _classify_markdown_block(content)
        cards.append({
            "id": _uid("md"),
            "title": title,
            "type": card_type,
            "source": source,
            "content": content,
            "tags": tags,
            "score": score,
            "status": _normalize_status(status),
            "decisionReason": "Markdown/Obsidian 导入，等待人工确认是否进入内容大脑。",
            "raw": {"source_text": block},
        })
    return cards


def _lead_row_to_card(row: sqlite3.Row) -> dict[str, Any]:
    raw = _json_loads(row["raw_json"], {}) or {}
    score = int(row["lead_score"] or 0)
    priority = str(row["priority"] or "")
    text = _clean(row["text_redacted"] or raw.get("text") or "")
    title = text[:36] or f"{priority} 级线索问题"
    tags = _split_tags(f"OpenClaw {priority} {row['platform']} {row['video_title']} {row['author']} {text}")
    decision = "A/B 级真实客户问题，建议进入待审核；人工确认后沉淀为客户问题库。" if priority in {"A", "B"} else "低意向或信息不足，默认不建议沉淀。"
    return {
        "id": f"lead_{row['id']}",
        "title": title,
        "type": "lead_question",
        "source": "openclaw_comment_leads",
        "content": text,
        "tags": tags,
        "score": score,
        "status": "pending" if priority in {"A", "B"} else "rejected",
        "decisionReason": decision,
        "raw": {
            "lead_id": row["id"],
            "platform": row["platform"],
            "source_url": row["source_url"],
            "video_title": row["video_title"],
            "author": row["author"],
            "priority": priority,
            "intents": _json_loads(row["intents_json"], []),
            "capture_angle": row["capture_angle"],
            "suggested_action": row["suggested_action"],
            "reply_draft": row["reply_draft"],
            "raw": raw,
        },
    }


def _card_to_markdown(card: dict[str, Any]) -> str:
    tags = card.get("tags") or []
    return "\n".join([
        f"# {card.get('title') or '未命名知识'}",
        "",
        f"- 类型：{TYPE_LABELS.get(card.get('type'), card.get('type'))}",
        f"- 来源：{card.get('source') or ''}",
        f"- 分数：{card.get('score') or 0}",
        f"- 状态：{card.get('status') or ''}",
        f"- 标签：{', '.join(tags)}",
        f"- 判断：{card.get('decisionReason') or card.get('decision_reason') or ''}",
        "",
        str(card.get("content") or ""),
        "",
    ])


@router.get("/health")
def health() -> dict[str, Any]:
    init_db()
    with _conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM content_brain_cards").fetchone()[0]
        approved = conn.execute("SELECT COUNT(*) FROM content_brain_cards WHERE status='approved'").fetchone()[0]
        pending = conn.execute("SELECT COUNT(*) FROM content_brain_cards WHERE status='pending'").fetchone()[0]
    return {
        "ok": True,
        "provider": "content_brain_sqlite_v1",
        "db_path": str(DB_PATH),
        "total": total,
        "approved": approved,
        "pending": pending,
    }


@router.get("/cards")
def list_cards(
    status: str = Query("approved"),
    type: str = Query("all"),
    query: str = Query(""),
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    init_db()
    clauses = []
    params: list[Any] = []
    if status and status != "all":
        clauses.append("status=?")
        params.append(_normalize_status(status))
    if type and type != "all":
        clauses.append("card_type=?")
        params.append(_normalize_type(type))
    if query:
        clauses.append("(title LIKE ? OR content LIKE ? OR tags_json LIKE ?)")
        q = f"%{query}%"
        params.extend([q, q, q])
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    sql = f"SELECT * FROM content_brain_cards{where} ORDER BY updated_at DESC LIMIT ?"
    params.append(limit)
    with _conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return {"ok": True, "cards": [_row_to_card(row) for row in rows], "count": len(rows)}


@router.post("/cards")
def create_card(req: BrainCardIn) -> dict[str, Any]:
    card = _upsert_card(req.model_dump())
    return {"ok": True, "card": card}


@router.post("/import-markdown")
def import_markdown(req: ImportMarkdownRequest) -> dict[str, Any]:
    cards = markdown_to_cards(req.markdown, source=req.source, status=req.status)
    saved = [_upsert_card(card) for card in cards]
    return {"ok": True, "cards": saved, "count": len(saved)}


def _set_status(ids: list[str], status: str, reason: str = "") -> list[dict[str, Any]]:
    init_db()
    now = _now_ts()
    out: list[dict[str, Any]] = []
    with _conn() as conn:
        for card_id in ids:
            if not card_id:
                continue
            old = conn.execute("SELECT decision_reason FROM content_brain_cards WHERE id=?", (card_id,)).fetchone()
            if not old:
                continue
            final_reason = reason or old["decision_reason"] or "人工更新状态。"
            conn.execute(
                "UPDATE content_brain_cards SET status=?, decision_reason=?, updated_at=? WHERE id=?",
                (_normalize_status(status), final_reason, now, card_id),
            )
        conn.commit()
        for card_id in ids:
            row = conn.execute("SELECT * FROM content_brain_cards WHERE id=?", (card_id,)).fetchone()
            if row:
                out.append(_row_to_card(row))
    return out


@router.post("/approve")
def approve(req: StatusRequest) -> dict[str, Any]:
    ids = req.ids or ([req.id] if req.id else [])
    cards = _set_status(ids, "approved", req.reason or "人工确认：值得进入内容大脑。")
    return {"ok": True, "cards": cards, "count": len(cards)}


@router.post("/reject")
def reject(req: StatusRequest) -> dict[str, Any]:
    ids = req.ids or ([req.id] if req.id else [])
    cards = _set_status(ids, "rejected", req.reason or "人工确认：暂不沉淀。")
    return {"ok": True, "cards": cards, "count": len(cards)}


@router.post("/mark-used/{card_id}")
def mark_used(card_id: str) -> dict[str, Any]:
    init_db()
    with _conn() as conn:
        conn.execute("UPDATE content_brain_cards SET used_count=COALESCE(used_count,0)+1, updated_at=? WHERE id=?", (_now_ts(), card_id))
        conn.commit()
        row = conn.execute("SELECT * FROM content_brain_cards WHERE id=?", (card_id,)).fetchone()
    return {"ok": bool(row), "card": _row_to_card(row) if row else None}


@router.post("/link-openclaw-leads")
def link_openclaw_leads(req: LinkOpenClawRequest) -> dict[str, Any]:
    if not Path(COMMENT_LEAD_DB_PATH).exists():
        return {"ok": True, "cards": [], "count": 0, "message": "comment lead db not found"}
    limit = max(1, min(int(req.limit or 80), 300))
    min_score = max(0, min(int(req.min_score or 55), 100))
    rows: list[sqlite3.Row] = []
    conn = sqlite3.connect(COMMENT_LEAD_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT * FROM comment_leads
            WHERE lead_score >= ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (min_score, limit),
        ).fetchall()
    finally:
        conn.close()
    cards = []
    for row in rows:
        card = _lead_row_to_card(row)
        if req.status in VALID_STATUS:
            card["status"] = req.status if card["status"] != "rejected" else "rejected"
        cards.append(_upsert_card(card))
    return {"ok": True, "cards": cards, "count": len(cards)}


@router.post("/suggest-topics")
def suggest_topics(req: SuggestTopicsRequest) -> dict[str, Any]:
    data = list_cards(status="approved", type="all", query=req.query or req.city or req.market, limit=120)
    cards = data.get("cards") or []
    seed_text = "\n".join(f"{c.get('title')} {c.get('content')} {' '.join(c.get('tags') or [])}" for c in cards)
    base_tags = _split_tags(f"{req.query} {req.city} {req.market} {req.content_type} {seed_text}")

    templates = [
        "{city}买房别只看价格，先看这三个判断标准",
        "{city}自住和投资，选房逻辑完全不一样",
        "预算有限怎么买{city}公寓？先筛区域和用途",
        "评论区问得最多：{city}哪里更适合出租？",
        "买{market}前，先把预算、区域、用途说清楚",
        "为什么同样预算，有人买得稳，有人买完后悔？",
        "{city}房产别只拍地标，真正该看房内和配套",
        "华人客户最关心的{city}买房问题，一条讲清楚",
    ]
    city = req.city or "吉隆坡"
    market = req.market or "马来西亚房产"
    topics = []
    for idx, tpl in enumerate(templates[: max(1, min(req.limit, 20))], start=1):
        title = tpl.format(city=city, market=market)
        topics.append({
            "id": f"topic_{idx}",
            "title": title,
            "hook": f"很多人一上来就问价格，但{city}买房真正先看的是需求、区域和后续流动性。",
            "tags": base_tags[:10],
            "source_card_count": len(cards),
            "suggested_visuals": ["城市建立镜头", "房内客厅", "阳台城市景", "大堂/泳池/健身房", "顾问带看", "评论区CTA"],
        })
    return {"ok": True, "topics": topics, "source_cards": cards[:20]}


@router.post("/export-obsidian")
def export_obsidian(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    status = str(payload.get("status") or "approved")
    data = list_cards(status=status, type="all", query="", limit=500)
    cards = data.get("cards") or []
    body = "\n---\n".join(_card_to_markdown(card) for card in cards)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = EXPORT_DIR / f"ai-video-content-brain-{time.strftime('%Y%m%d_%H%M%S')}.md"
    out.write_text(body, encoding="utf-8")
    public_url = maybe_upload_to_r2(get_settings(), out, prefix="content-brain/obsidian")
    return {
        "ok": True,
        "count": len(cards),
        "markdown": body,
        "local_path": str(out),
        "public_url": public_url or "",
    }


def install_content_brain(app: FastAPI) -> None:
    init_db()
    app.include_router(router)
