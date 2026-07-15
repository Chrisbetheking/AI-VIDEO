from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import unquote, urlparse

import cv2
import httpx
import numpy as np
from fastapi import Body, FastAPI, HTTPException, Query

from app.services.collector_control import (
    collector_queue_mirror_status,
    collector_worker_heartbeat,
)

VERSION = "10.40.8.2"
MODE = "runtime_recovery_queue_bridge"
BASE = Path(os.getenv("AI_VIDEO_BASE", "/opt/ai-video"))
STORAGE = BASE / "storage"
ROOT = Path(os.getenv("AI_VIDEO_INTEGRATION_ROOT", str(STORAGE / "integration_hub_v10_40_7")))
KNOWLEDGE_FILE = ROOT / "knowledge_cards.json"
MIGRATION_FILE = ROOT / "migration_report.json"
OLD_BRAIN_DB = BASE / "backend" / "data" / "content-brain" / "content_brain.sqlite3"
OLD_HUB_KNOWLEDGE = STORAGE / "integration_hub_v10_40_6" / "knowledge_cards.json"
VAULT_CANDIDATES = [STORAGE / "obsidian-vault", BASE / "storage" / "obsidian-vault", Path("/opt/obsidian-vault"), Path("/root/obsidian-vault")]
RUN_FILE = ROOT / "openclaw_runs.json"
CONFIG_FILE = ROOT / "config.json"
AUDIT_ROOT = ROOT / "audits"
for path in (ROOT, AUDIT_ROOT):
    path.mkdir(parents=True, exist_ok=True)

ALLOWED_ROOTS = [BASE.resolve(), STORAGE.resolve(), Path("/tmp").resolve()]
OPENCLAW_HEALTH = ["/api/openclaw/health", "/api/collector/health", "/api/video/openclaw/health"]
OPENCLAW_START = ["/api/openclaw/discovery/start", "/api/collector/commands", "/api/collector/commands/create"]
OPENCLAW_JOB = ["/api/openclaw/discovery/job/{job_id}", "/api/collector/runs/{job_id}", "/api/collector/commands/{job_id}"]
OPENCLAW_RESULTS = ["/api/video/comment-leads/recent?limit=300", "/api/openclaw/videos", "/api/openclaw/accounts", "/api/collector/runs/latest"]
INTERNAL_KEYWORD = re.compile(r"^(?:ai_?kw|keyword|kw|region|area|audience|crowd|user|区域|人群|城市|标签)[_-]?\d+(?:[_-].*)?$", re.I)

KNOWLEDGE_COLLECTIONS = {"lead", "copy", "video", "visual", "research"}
COLLECTION_FOLDERS = {
    "lead": "01-截流线索",
    "copy": "02-生产文案",
    "video": "03-视频知识",
    "visual": "04-画面规则",
    "research": "05-研究与历史",
}
ACTIVE_RUN_STATUSES = {"queued", "pending", "created", "starting", "running", "processing", "collecting", "analyzing"}


def infer_collection(raw: Dict[str, Any], card_type: str = "", lane: str = "", source: str = "") -> str:
    explicit = text(raw.get("collection") or raw.get("knowledge_collection") or raw.get("bucket")).lower()
    if explicit in KNOWLEDGE_COLLECTIONS:
        return explicit
    joined = " ".join([card_type, lane, source, text(raw.get("title")), text(raw.get("content"))]).lower()
    if lane == "reply" or card_type in {"lead_question", "reply_template"} or any(token in joined for token in ["openclaw", "comment_lead", "客户线索", "评论截流"]):
        return "lead"
    if lane == "visual" or card_type == "visual_rule" or any(token in joined for token in ["镜头", "画面规则", "素材规则", "字幕规则"]):
        return "visual"
    if card_type in {"topic", "hook", "script", "production_copy", "copy_template"} or any(token in joined for token in ["生产文案", "选题", "标题", "钩子", "口播"]):
        return "copy"
    if lane == "video":
        return "video"
    return "research"


def run_progress(value: Dict[str, Any]) -> int:
    candidates = [
        value.get("progress"),
        value.get("percent"),
        as_dict(value.get("raw")).get("progress"),
        as_dict(value.get("response")).get("progress"),
        as_dict(as_dict(value.get("response")).get("data")).get("progress"),
    ]
    for candidate in candidates:
        try:
            number = float(candidate)
        except Exception:
            continue
        if 0 <= number <= 1:
            number *= 100
        return max(0, min(100, int(round(number))))
    return 0


def run_stage(value: Dict[str, Any]) -> str:
    for candidate in [
        value.get("stage"), value.get("status"), value.get("message"),
        as_dict(value.get("raw")).get("stage"),
        as_dict(value.get("response")).get("stage"),
        as_dict(value.get("response")).get("status"),
    ]:
        clean = text(candidate)
        if clean:
            return clean
    return "queued"


def run_counts(value: Dict[str, Any]) -> Dict[str, int]:
    combined = {}
    for source in [value, as_dict(value.get("raw")), as_dict(value.get("response")), as_dict(as_dict(value.get("response")).get("data"))]:
        combined.update(source)
    result: Dict[str, int] = {}
    aliases = {
        "accounts": ["accounts", "account_count", "accounts_collected", "discovered_accounts"],
        "videos": ["videos", "video_count", "videos_collected", "discovered_videos"],
        "comments": ["comments", "comment_count", "comments_collected"],
        "leads": ["leads", "lead_count", "qualified_leads"],
    }
    for key, names in aliases.items():
        for name in names:
            try:
                result[key] = max(result.get(key, 0), int(float(combined.get(name) or 0)))
            except Exception:
                pass
    return result


def public_run(value: Dict[str, Any]) -> Dict[str, Any]:
    item = as_dict(value)
    request = as_dict(item.get("request"))
    status = text(item.get("status") or run_stage(item) or "queued")
    created_at = int(item.get("created_at") or 0)
    updated_at = int(item.get("updated_at") or created_at or 0)
    queue_age_seconds = max(0, now() - created_at) if created_at and status.lower() in {"queued", "pending", "waiting"} else 0
    queue_stalled = bool(queue_age_seconds >= 90 and status.lower() in {"queued", "pending", "waiting"})
    return {
        **item,
        "job_id": text(item.get("job_id")),
        "status": status,
        "stage": run_stage(item),
        "progress": run_progress(item),
        "counts": run_counts(item),
        "account_profile": text(item.get("account_profile") or request.get("account_profile") or "company_main"),
        "mission_type": text(item.get("mission_type") or request.get("mission_type") or "comments"),
        "is_active": status.lower() in ACTIVE_RUN_STATUSES,
        "queue_age_seconds": queue_age_seconds,
        "queue_stalled": queue_stalled,
        "updated_at": updated_at,
    }


def now() -> int:
    return int(time.time())


def text(value: Any) -> str:
    return str(value or "").strip()


def as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def uid(prefix: str) -> str:
    return f"{prefix}_{now()}_{uuid.uuid4().hex[:10]}"


def clean_keyword(value: Any) -> str:
    value = re.sub(r"\s+", " ", text(value)).strip("#*-—_ ")
    if not value or INTERNAL_KEYWORD.match(value):
        return ""
    if re.search(r"internal|placeholder|占位|字段id|keyword_id", value, re.I):
        return ""
    if len(value) < 2 or len(value) > 18:
        return ""
    return value


def clean_keywords(values: Iterable[Any], limit: int = 30) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for value in values:
        item = clean_keyword(value)
        key = item.lower()
        if not item or key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= limit:
            break
    return out


def normalize_card(raw: Dict[str, Any], source: str = "integration") -> Dict[str, Any]:
    content = text(raw.get("content") or raw.get("text") or raw.get("question"))
    title = text(raw.get("title")) or content[:36] or "未命名知识"
    tags = raw.get("tags")
    if isinstance(tags, str):
        tags = re.split(r"[,，#\s]+", tags)
    status = text(raw.get("status") or "pending").lower()
    if status not in {"pending", "approved", "rejected"}:
        status = "pending"
    try:
        score = max(0, min(100, int(float(raw.get("score") or 70))))
    except Exception:
        score = 70
    card_type = text(raw.get("type") or raw.get("card_type") or "market_note")
    lane = text(raw.get("lane") or "video")
    card_source = text(raw.get("source") or source)
    collection = infer_collection(raw, card_type, lane, card_source)
    return {
        "id": text(raw.get("id")) or uid("brain"),
        "title": title[:90],
        "type": card_type,
        "lane": lane,
        "collection": collection,
        "source": card_source,
        "source_ref": text(raw.get("source_ref") or raw.get("url") or raw.get("path")),
        "content": content[:5000],
        "tags": clean_keywords(as_list(tags)),
        "score": score,
        "status": status,
        "decision_reason": text(raw.get("decision_reason") or raw.get("decisionReason") or "等待人工审核。"),
        "created_at": int(raw.get("created_at") or raw.get("createdAt") or now()),
        "updated_at": now(),
        "used_count": int(raw.get("used_count") or raw.get("usedCount") or 0),
        "raw": raw.get("raw") if isinstance(raw.get("raw"), dict) else {},
    }


def card_key(card: Dict[str, Any]) -> str:
    seed = "|".join([text(card.get("collection")), text(card.get("type")), text(card.get("title")), text(card.get("content"))[:220]])
    return hashlib.sha256(re.sub(r"\s+", "", seed).lower().encode()).hexdigest()


def load_cards() -> List[Dict[str, Any]]:
    return [normalize_card(as_dict(item)) for item in as_list(read_json(KNOWLEDGE_FILE, [])) if isinstance(item, dict)]


def save_cards(cards: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for item in cards:
        card = normalize_card(item)
        key = card_key(card)
        if key in seen:
            continue
        seen.add(key)
        out.append(card)
    out.sort(key=lambda card: (card.get("status") != "approved", -int(card.get("score") or 0), -int(card.get("updated_at") or 0)))
    out = out[:2000]
    atomic_json(KNOWLEDGE_FILE, out)
    return out


def merge_cards(incoming: Iterable[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
    cards = load_cards()
    index = {card_key(card): card for card in cards}
    added = 0
    for item in incoming:
        card = normalize_card(as_dict(item))
        key = card_key(card)
        if key in index:
            old = index[key]
            old["score"] = max(int(old.get("score") or 0), int(card.get("score") or 0))
            old["tags"] = clean_keywords([*as_list(old.get("tags")), *as_list(card.get("tags"))])
            old["updated_at"] = now()
        else:
            cards.append(card)
            index[key] = card
            added += 1
    return save_cards(cards), added


def markdown_cards(markdown: str, source: str, source_ref: str = "", collection: str = "") -> List[Dict[str, Any]]:
    blocks = [block.strip() for block in re.split(r"\n(?=#{1,4}\s)|\n---+\n|\n\s*\n+", text(markdown)) if len(block.strip()) >= 12]
    out: List[Dict[str, Any]] = []
    for block in blocks[:200]:
        match = re.search(r"^#{1,4}\s+(.+)$", block, re.M)
        title = text(match.group(1) if match else block[:50].replace("\n", " "))
        lower = block.lower()
        card_type, lane = "market_note", "video"
        if re.search(r"评论|私信|客户|咨询|预算|能买吗|需求", block):
            card_type, lane = "lead_question", "reply"
        if re.search(r"回复|跟进|话术", block):
            card_type, lane = "reply_template", "reply"
        if re.search(r"镜头|画面|素材|b-roll|水印|字幕|转场", lower):
            card_type, lane = "visual_rule", "visual"
        if re.search(r"选题|主题|标题|话题", block):
            card_type, lane = "topic", "video"
        if re.search(r"hook|开头|钩子|前三秒", lower):
            card_type, lane = "hook", "video"
        resolved_collection = collection if collection in KNOWLEDGE_COLLECTIONS else infer_collection({"title": title, "content": block}, card_type, lane, source)
        out.append({
            "title": title,
            "type": card_type,
            "lane": lane,
            "collection": resolved_collection,
            "source": source,
            "source_ref": source_ref,
            "content": re.sub(r"^#{1,4}\s+", "", block, flags=re.M).strip(),
            "tags": clean_keywords(re.findall(r"[\u4e00-\u9fffA-Za-z0-9_-]{2,12}", title)[:8]),
            "score": 76 if card_type in {"lead_question", "hook", "topic"} else 68,
            "status": "pending",
            "decision_reason": "Obsidian/Markdown 自动同步，等待人工审核。",
        })
    return out


def extract_rows(value: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                out.append(item)
                out.extend(extract_rows(item))
    elif isinstance(value, dict):
        for key, child in value.items():
            if key in {"items", "comments", "leads", "records", "results", "rows", "videos", "accounts", "comment_leads", "data", "latest"}:
                out.extend(extract_rows(child))
    return out


def lead_card(item: Dict[str, Any], collection: str = "lead") -> Optional[Dict[str, Any]]:
    body = text(item.get("text") or item.get("comment") or item.get("message") or item.get("question") or item.get("content"))
    if len(body) < 5:
        return None
    try:
        score = int(float(item.get("score") or item.get("lead_score") or item.get("priority_score") or 60))
    except Exception:
        score = 60
    priority = text(item.get("priority") or item.get("grade")).upper()
    if priority == "A": score = max(score, 85)
    if priority == "B": score = max(score, 70)
    if score < 55:
        return None
    return {
        "title": body[:42], "type": "lead_question", "lane": "reply", "collection": collection if collection in KNOWLEDGE_COLLECTIONS else "lead", "source": "openclaw",
        "source_ref": text(item.get("source_url") or item.get("video_url") or item.get("account_url")),
        "content": body, "tags": clean_keywords([item.get("account_name"), item.get("author"), priority, "OpenClaw", "客户问题"]),
        "score": score, "status": "pending", "decision_reason": "OpenClaw A/B 级或高分客户问题，等待人工批准。", "raw": item,
    }



def _old_sqlite_cards(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        for row in conn.execute("SELECT * FROM content_brain_cards ORDER BY updated_at DESC"):
            raw = dict(row)
            tags = []
            try:
                parsed = json.loads(text(raw.get("tags_json")) or "[]")
                tags = parsed if isinstance(parsed, list) else []
            except Exception:
                tags = []
            extra = {}
            try:
                parsed = json.loads(text(raw.get("raw_json")) or "{}")
                extra = parsed if isinstance(parsed, dict) else {}
            except Exception:
                extra = {}
            rows.append({
                "id": text(raw.get("id")),
                "title": text(raw.get("title")),
                "type": text(raw.get("card_type") or "market_note"),
                "lane": text(extra.get("lane") or ("reply" if "reply" in text(raw.get("card_type")).lower() else "visual" if "visual" in text(raw.get("card_type")).lower() else "video")),
                "source": text(raw.get("source") or "legacy_content_brain_sqlite"),
                "source_ref": str(path),
                "content": text(raw.get("content")),
                "tags": tags,
                "score": int(raw.get("score") or 70),
                "status": text(raw.get("status") or "pending"),
                "decision_reason": text(raw.get("decision_reason") or "从旧内容大脑迁移。"),
                "used_count": int(raw.get("used_count") or 0),
                "created_at": int(float(raw.get("created_at") or now())),
                "updated_at": int(float(raw.get("updated_at") or now())),
                "raw": extra,
            })
        conn.close()
    except Exception:
        return []
    return rows


def _discover_vault() -> Optional[Path]:
    configured = vault_path()
    if configured:
        return configured
    candidates: List[Path] = []
    for candidate in VAULT_CANDIDATES:
        try:
            path = candidate.expanduser().resolve()
            if path.exists() and path.is_dir() and any(path.rglob("*.md")):
                candidates.append(path)
        except Exception:
            continue
    if not candidates:
        return None
    candidates.sort(key=lambda path: len(list(path.rglob("*.md"))), reverse=True)
    chosen = candidates[0]
    cfg = config()
    cfg["obsidian_vault"] = str(chosen)
    atomic_json(CONFIG_FILE, cfg)
    return chosen


def run_legacy_migration(force: bool = False, sync_vault: bool = True) -> Dict[str, Any]:
    previous = read_json(MIGRATION_FILE, {})
    if previous and not force:
        return previous
    before = len(load_cards())
    imported_sources: Dict[str, int] = {}
    incoming: List[Dict[str, Any]] = []
    old_sqlite = _old_sqlite_cards(OLD_BRAIN_DB)
    incoming.extend(old_sqlite)
    imported_sources["legacy_sqlite"] = len(old_sqlite)
    old_hub = [as_dict(item) for item in as_list(read_json(OLD_HUB_KNOWLEDGE, []))]
    incoming.extend(old_hub)
    imported_sources["v10_40_6_json"] = len(old_hub)
    vault = _discover_vault()
    vault_files = 0
    vault_cards: List[Dict[str, Any]] = []
    if sync_vault and vault:
        files = sorted(vault.rglob("*.md"), key=lambda path: path.stat().st_mtime, reverse=True)
        vault_files = len(files)
        for path in files[:1000]:
            try:
                vault_cards.extend(markdown_cards(path.read_text(encoding="utf-8"), "obsidian_vault", str(path.relative_to(vault))))
            except Exception:
                pass
        incoming.extend(vault_cards)
    imported_sources["obsidian_vault"] = len(vault_cards)
    cards, added = merge_cards(incoming)
    report = {
        "ok": True,
        "version": VERSION,
        "before": before,
        "after": len(cards),
        "added": added,
        "sources": imported_sources,
        "old_sqlite_rows": len(old_sqlite),
        "legacy_sqlite_rows": len(old_sqlite),
        "vault_markdown_files": vault_files,
        "legacy_db_exists": OLD_BRAIN_DB.exists(),
        "vault": str(vault) if vault else "",
        "vault_files": vault_files,
        "created_at": now(),
    }
    atomic_json(MIGRATION_FILE, report)
    return report

def config() -> Dict[str, Any]:
    value = read_json(CONFIG_FILE, {})
    value = value if isinstance(value, dict) else {}
    env = text(os.getenv("AI_VIDEO_OBSIDIAN_VAULT"))
    if env: value["obsidian_vault"] = env
    return value


def vault_path() -> Optional[Path]:
    raw = text(config().get("obsidian_vault"))
    if not raw: return None
    path = Path(raw).expanduser().resolve()
    return path if path.exists() and path.is_dir() else None


def git_pull(vault: Path) -> Dict[str, Any]:
    if not (vault / ".git").exists():
        return {"attempted": False, "ok": True, "message": "不是 Git 仓库"}
    try:
        result = subprocess.run(["git", "-C", str(vault), "pull", "--ff-only"], check=True, capture_output=True, text=True, timeout=90)
        return {"attempted": True, "ok": True, "message": (result.stdout or "git pull 完成").strip()[-1000:]}
    except Exception as exc:
        return {"attempted": True, "ok": False, "message": str(exc)}


async def internal_json(app: FastAPI, method: str, path: str, payload: Optional[Dict[str, Any]] = None, timeout: float = 120.0) -> Tuple[int, Dict[str, Any]]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://internal", timeout=timeout) as client:
        response = await client.request(method.upper(), path, json=payload)
    try: data = response.json()
    except Exception: data = {"ok": False, "body": response.text[:2000]}
    if not isinstance(data, dict): data = {"ok": response.status_code < 400, "value": data}
    return response.status_code, data


async def first_available(app: FastAPI, method: str, paths: Sequence[str], payload: Optional[Dict[str, Any]] = None, timeout: float = 120.0) -> Tuple[str, int, Dict[str, Any]]:
    attempts = []
    for path in paths:
        status, data = await internal_json(app, method, path, payload, timeout)
        attempts.append({"path": path, "status": status})
        if status < 400 or status not in {404, 405}:
            data.setdefault("_attempts", attempts)
            return path, status, data
    return "", 404, {"ok": False, "attempts": attempts, "detail": "没有可用接口"}


def resolve_path(value: Any) -> Optional[Path]:
    raw = text(value)
    if not raw: return None
    parsed = urlparse(raw)
    if parsed.scheme in {"http", "https"}:
        marker = "/storage/"
        path_text = unquote(parsed.path)
        if marker not in path_text: return None
        raw = str(STORAGE / path_text.split(marker, 1)[1])
    path = Path(raw).expanduser().resolve()
    if not path.exists() or not path.is_file(): return None
    if not any(root == path or root in path.parents for root in ALLOWED_ROOTS): return None
    return path


def probe(path: Path) -> Dict[str, Any]:
    result = subprocess.run([shutil.which("ffprobe") or "ffprobe", "-v", "error", "-show_entries", "stream=width,height,codec_type:format=duration", "-of", "json", str(path)], check=True, capture_output=True, text=True, timeout=45)
    data = json.loads(result.stdout or "{}")
    video = next((as_dict(item) for item in as_list(data.get("streams")) if text(as_dict(item).get("codec_type")) == "video"), {})
    return {"duration": float(as_dict(data.get("format")).get("duration") or 0), "width": int(video.get("width") or 0), "height": int(video.get("height") or 0)}


def extract_frames(path: Path, output: Path, count: int) -> Tuple[List[Path], Dict[str, Any]]:
    info = probe(path)
    duration = max(0.1, float(info["duration"]))
    output.mkdir(parents=True, exist_ok=True)
    frames = []
    for index, second in enumerate(np.linspace(min(0.25, duration * .03), max(.25, duration - .25), max(4, min(20, count)))):
        target = output / f"frame_{index:02d}.jpg"
        subprocess.run([shutil.which("ffmpeg") or "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{second:.3f}", "-i", str(path), "-frames:v", "1", "-vf", "scale=360:-2", "-q:v", "2", str(target)], check=True, capture_output=True, text=True, timeout=45)
        if target.exists() and target.stat().st_size > 1000: frames.append(target)
    return frames, info


def dhash(image: np.ndarray, size: int = 16) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(gray, (size + 1, size), interpolation=cv2.INTER_AREA)
    return small[:, 1:] > small[:, :-1]


def hist_sim(a: np.ndarray, b: np.ndarray) -> float:
    ah = cv2.calcHist([a], [0, 1], None, [32, 32], [0, 256, 0, 256]); bh = cv2.calcHist([b], [0, 1], None, [32, 32], [0, 256, 0, 256])
    cv2.normalize(ah, ah); cv2.normalize(bh, bh)
    return float(cv2.compareHist(ah, bh, cv2.HISTCMP_CORREL))


def text_score(image: np.ndarray, allow_bottom: bool) -> Tuple[float, List[Dict[str, Any]]]:
    h, w = image.shape[:2]; top = int(h * .04); bottom = int(h * (.76 if allow_bottom else .96)); roi = image[top:bottom]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    grad = cv2.morphologyEx(gray, cv2.MORPH_GRADIENT, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
    _, binary = cv2.threshold(grad, 45, 255, cv2.THRESH_BINARY)
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (9, 3)))
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    regions = []; area = 0.0
    for contour in contours:
        x, y, rw, rh = cv2.boundingRect(contour); aspect = rw / max(rh, 1)
        if rw < 16 or rh < 5 or rw > w * .94 or rh > h * .16 or aspect < 1.2 or aspect > 25: continue
        fill = cv2.contourArea(contour) / max(rw * rh, 1)
        if fill < .08: continue
        regions.append({"x": x, "y": y + top, "w": rw, "h": rh}); area += rw * rh * min(2.5, max(1.0, aspect / 3))
    count_score = min(1.0, len(regions) / 10); area_score = min(1.0, area / max(1, roi.shape[0] * roi.shape[1] * .055)); density = min(1.0, max(0.0, (float(np.mean(binary > 0)) - .035) / .11))
    return min(1.0, .48 * count_score + .34 * area_score + .18 * density), regions[:30]


def watermark_score(images: Sequence[np.ndarray]) -> Dict[str, Any]:
    best = {"score": 0.0, "corner": "", "stability": 0.0, "edge_density": 0.0}
    corners = {"top_left": (0, 0, .22, .18), "top_right": (.78, 0, 1, .18), "bottom_left": (0, .82, .22, 1), "bottom_right": (.78, .82, 1, 1)}
    for name, (x1, y1, x2, y2) in corners.items():
        patches = []; densities = []
        for image in images:
            h, w = image.shape[:2]; patch = image[int(h*y1):int(h*y2), int(w*x1):int(w*x2)]
            gray = cv2.resize(cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY), (96, 96)); patches.append(gray); densities.append(float(np.mean(cv2.Canny(gray, 70, 150) > 0)))
        sims = [float(cv2.matchTemplate(a, b, cv2.TM_CCOEFF_NORMED)[0,0]) for a, b in zip(patches, patches[1:])]
        stability = float(np.median(sims)) if sims else 0; edge = float(np.median(densities)); score = max(0.0, min(1.0, ((stability-.58)/.34) * min(1.0, edge/.12)))
        if score > best["score"]: best = {"score": round(score,4), "corner": name, "stability": round(stability,4), "edge_density": round(edge,4)}
    return best


def duplicate_metrics(images: Sequence[np.ndarray], duration: float) -> Dict[str, Any]:
    hashes = [dhash(image) for image in images]
    reps: List[int] = []
    assignments: List[int] = []

    for index, image_hash in enumerate(hashes):
        match = -1
        for cluster, rep in enumerate(reps):
            if (
                int(np.count_nonzero(image_hash != hashes[rep])) <= 28
                and hist_sim(images[index], images[rep]) >= .78
            ):
                match = cluster
                break
        if match < 0:
            reps.append(index)
            match = len(reps) - 1
        assignments.append(match)

    longest = current = 1
    for a, b in zip(assignments, assignments[1:]):
        current = current + 1 if a == b else 1
        longest = max(longest, current)

    # dHash 对推拉、平移和航拍运动很敏感，同一栋楼轻微移动时会被误判成
    # 多个“新镜头”。再用相邻帧颜色分布 + 低分辨率结构相关性估算
    # 真正场景切换，专门拦截连续数秒只是同一建筑缓慢移动的情况。
    scene_runs: List[int] = []
    current_scene_run = 1
    scene_clusters = 1
    adjacent_scene_similarity: List[Dict[str, float]] = []

    for first, second in zip(images, images[1:]):
        histogram = hist_sim(first, second)
        first_gray = cv2.resize(
            cv2.cvtColor(first, cv2.COLOR_BGR2GRAY),
            (64, 64),
            interpolation=cv2.INTER_AREA,
        )
        second_gray = cv2.resize(
            cv2.cvtColor(second, cv2.COLOR_BGR2GRAY),
            (64, 64),
            interpolation=cv2.INTER_AREA,
        )
        first_flat = first_gray.astype(np.float32).ravel()
        second_flat = second_gray.astype(np.float32).ravel()
        if float(np.std(first_flat)) < 1e-6 or float(np.std(second_flat)) < 1e-6:
            structure = 1.0 if float(np.mean(np.abs(first_flat - second_flat))) < 6 else 0.0
        else:
            structure = float(np.corrcoef(first_flat, second_flat)[0, 1])
            if not math.isfinite(structure):
                structure = 0.0

        scene_cut = histogram < .72 or structure < .25
        adjacent_scene_similarity.append({
            "histogram": round(histogram, 4),
            "structure": round(structure, 4),
            "scene_cut": bool(scene_cut),
        })
        if scene_cut:
            scene_runs.append(current_scene_run)
            current_scene_run = 1
            scene_clusters += 1
        else:
            current_scene_run += 1
    scene_runs.append(current_scene_run)

    interval = duration / max(len(images) - 1, 1)
    required = max(4, min(10, math.ceil(duration / 4.5)))
    max_same_scene_seconds = max(scene_runs or [1]) * interval

    return {
        "unique_clusters": len(reps),
        "scene_clusters": scene_clusters,
        "effective_unique_scenes": min(len(reps), scene_clusters),
        "required_unique": required,
        "max_similar_run_seconds": round(longest * interval, 2),
        "max_same_scene_seconds": round(max_same_scene_seconds, 2),
        "duplicate_ratio": round(
            sum(1 for a, b in zip(assignments, assignments[1:]) if a == b)
            / max(len(images) - 1, 1),
            4,
        ),
        "scene_run_frames": scene_runs,
        "adjacent_scene_similarity": adjacent_scene_similarity,
    }


def audit_image(path: Path) -> Dict[str, Any]:
    image = cv2.imread(str(path))
    if image is None: raise HTTPException(422, "无法读取图片素材")
    score, regions = text_score(image, False); h, w = image.shape[:2]; reasons=[]
    if score >= .38: reasons.append("图片疑似含标题、字幕、价格、Logo 或伪文字")
    if w < 540 or h < 720: reasons.append("图片分辨率过低")
    return {"ok": True, "version": VERSION, "path": str(path), "media_type": "image", "passed": not reasons, "status": "clean" if not reasons else "quarantine", "width": w, "height": h, "embedded_text_score": round(score,4), "embedded_text_regions": regions[:20], "reasons": reasons, "created_at": now()}


def audit_video(path: Path, allow_bottom: bool, count: int) -> Dict[str, Any]:
    audit_id = uid("audit"); output = AUDIT_ROOT / audit_id; frames, info = extract_frames(path, output, count); images = [cv2.imread(str(frame)) for frame in frames]; images = [image for image in images if image is not None]
    if len(images) < 3: raise HTTPException(500, "关键帧不足")
    scores=[]; suspicious=[]
    for idx, image in enumerate(images):
        score, regions = text_score(image, allow_bottom); scores.append(score)
        if score >= .34: suspicious.append({"frame": idx, "score": round(score,4), "regions": regions[:8]})
    embedded = float(np.percentile(scores,75)); water = watermark_score(images); duplicates = duplicate_metrics(images,float(info["duration"])); reasons=[]
    if embedded >= .42: reasons.append("画面上半区或中部疑似存在素材自带字幕、标题或伪文字")
    if water["score"] >= .42: reasons.append(f"{water['corner']} 疑似存在固定头像、Logo 或水印")
    if duplicates["effective_unique_scenes"] < duplicates["required_unique"]:
        reasons.append("有效不同场景数量不足，疑似重复使用同一楼盘或同类画面")
    if max(
        float(duplicates["max_similar_run_seconds"]),
        float(duplicates["max_same_scene_seconds"]),
    ) > 5.0:
        reasons.append("同一场景连续停留超过 5 秒，镜头节奏或素材去重不合格")
    report = {"ok": True, "version": VERSION, "audit_id": audit_id, "path": str(path), "passed": not reasons, "status": "clean" if not reasons else "quarantine", "duration": round(float(info["duration"]),3), "width": info["width"], "height": info["height"], "embedded_text_score": round(embedded,4), "embedded_text_frames": suspicious, "watermark": water, "duplicates": duplicates, "reasons": reasons, "frame_paths": [str(frame) for frame in frames], "created_at": now()}
    atomic_json(output / "report.json", report); return report


def knowledge_context(cards: Sequence[Dict[str, Any]], topic: str, city: str, market: str, limit: int) -> Dict[str, Any]:
    keys = clean_keywords(re.split(r"[,，、\s]+", " ".join([topic, city, market])))
    approved = [
        card for card in cards
        if card.get("status") == "approved"
        and text(card.get("collection")) in {"copy", "video", "research"}
    ]
    scored=[]; counts={"obsidian":0,"openclaw":0,"competitor":0,"history":0,"lead_isolated":sum(1 for c in cards if c.get("collection")=="lead"),"visual_isolated":sum(1 for c in cards if c.get("collection")=="visual")}
    for card in approved:
        source = text(card.get("source")).lower(); group = "obsidian" if "obsidian" in source else "openclaw" if "openclaw" in source else "competitor" if any(token in source for token in ["heat","douyin","competitor","collector"]) else "history"; counts[group]+=1
        hay = " ".join([text(card.get("title")), text(card.get("content")), " ".join(as_list(card.get("tags")))]).lower(); match = sum(1 for key in keys if key.lower() in hay); scored.append((float(card.get("score") or 0)+match*18+min(12,int(card.get("used_count") or 0)*2),card))
    scored.sort(key=lambda pair: pair[0], reverse=True); selected=[card for _,card in scored[:max(1,min(30,limit))]]
    return {"ok": True, "version": VERSION, "counts": {**counts, "approved_total":len(approved), "pending_total":sum(1 for c in cards if c.get("status")=="pending")}, "cards":selected, "selected_ids":[c.get("id") for c in selected], "query":{"topic":topic,"city":city,"market":market,"keywords":keys}}


def install_integration_hub_v10_40_7(app: FastAPI) -> None:
    if getattr(app.state, "integration_hub_v10_40_7_installed", False):
        return

    app.state.integration_hub_v10_40_7_installed = True
    migration = run_legacy_migration(force=False, sync_vault=True)

    @app.get("/api/video/integration/health")
    def health():
        vault = _discover_vault(); return {"ok":True,"version":VERSION,"mode":MODE,"knowledge_backend":True,"obsidian_configured":bool(vault),"obsidian_vault":str(vault) if vault else "","legacy_migration":read_json(MIGRATION_FILE,migration),"knowledge_total":len(load_cards()),"openclaw_orchestration":True,"asset_cleanliness_gate":True,"video_visual_integrity_gate":True,"graphic_window_embedded_tab":True,"button_contracts":True,"engine_source_fix":True,"knowledge_isolation":True,"persistent_openclaw_runs":True,"account_profile_isolation":True,"realtime_progress":True,"storage":str(ROOT)}

    @app.get("/api/video/integration/knowledge/cards")
    def get_cards(status: str = Query("all"), source: str = Query(""), lane: str = Query("all"), collection: str = Query("all"), limit: int = Query(500, ge=1, le=2000)):
        cards=load_cards();
        if status!="all": cards=[c for c in cards if c.get("status")==status]
        if source: cards=[c for c in cards if source.lower() in text(c.get("source")).lower()]
        if lane!="all": cards=[c for c in cards if c.get("lane")==lane]
        if collection!="all": cards=[c for c in cards if c.get("collection")==collection]
        collections={name:sum(1 for c in cards if c.get("collection")==name) for name in sorted(KNOWLEDGE_COLLECTIONS)}
        return {"ok":True,"version":VERSION,"cards":cards[:limit],"count":min(len(cards),limit),"total":len(cards),"collections":collections}

    @app.post("/api/video/integration/knowledge/cards")
    def create_card(payload: Dict[str, Any] = Body(default_factory=dict)):
        cards, added = merge_cards([payload]); return {"ok":True,"version":VERSION,"added":added,"count":len(cards)}

    @app.post("/api/video/integration/knowledge/import-markdown")
    def import_markdown(payload: Dict[str, Any] = Body(default_factory=dict)):
        cards, added = merge_cards(markdown_cards(text(payload.get("markdown")), text(payload.get("source") or "manual_markdown"), text(payload.get("source_ref")), text(payload.get("collection")))); return {"ok":True,"version":VERSION,"added":added,"count":len(cards)}

    @app.post("/api/video/integration/knowledge/cards/{card_id}/decision")
    def decide(card_id: str, payload: Dict[str, Any] = Body(default_factory=dict)):
        status=text(payload.get("status") or payload.get("decision")).lower()
        if status not in {"pending","approved","rejected"}: raise HTTPException(422,"status 必须是 pending/approved/rejected")
        cards=load_cards(); found=False
        for card in cards:
            if card.get("id")==card_id:
                card["status"]=status
                next_collection=text(payload.get("collection"))
                if next_collection in KNOWLEDGE_COLLECTIONS: card["collection"]=next_collection
                card["decision_reason"]=text(payload.get("reason") or f"人工设置为 {status}")
                card["updated_at"]=now(); found=True
        if not found: raise HTTPException(404,f"找不到知识卡：{card_id}")
        save_cards(cards); return {"ok":True,"version":VERSION}

    @app.post("/api/video/integration/knowledge/cards/{card_id}/mark-used")
    def mark_used(card_id: str):
        cards=load_cards(); found=False
        for card in cards:
            if card.get("id")==card_id: card["used_count"]=int(card.get("used_count") or 0)+1; card["updated_at"]=now(); found=True
        if not found: raise HTTPException(404,f"找不到知识卡：{card_id}")
        save_cards(cards); return {"ok":True,"version":VERSION}

    @app.get("/api/video/integration/knowledge/context")
    def context(topic: str = Query(""), city: str = Query(""), market: str = Query(""), limit: int = Query(12, ge=1, le=30)):
        return knowledge_context(load_cards(), topic, city, market, limit)


    @app.get("/api/video/integration/migration/status")
    def migration_status():
        return {"ok": True, "version": VERSION, "report": read_json(MIGRATION_FILE, {}), "knowledge_total": len(load_cards()), "legacy_db_exists": OLD_BRAIN_DB.exists()}

    @app.post("/api/video/integration/migration/run")
    def migration_run(payload: Dict[str, Any] = Body(default_factory=dict)):
        return run_legacy_migration(force=bool(payload.get("force")), sync_vault=bool(payload.get("sync_vault", True)))

    @app.get("/api/video/integration/obsidian/status")
    def obsidian_status():
        vault=_discover_vault(); return {"ok":True,"version":VERSION,"configured":bool(vault),"vault":str(vault) if vault else "","git":bool(vault and (vault/".git").exists()),"markdown_files":len(list(vault.rglob("*.md"))) if vault else 0,"migration":read_json(MIGRATION_FILE,{})}

    @app.post("/api/video/integration/obsidian/config")
    def obsidian_config(payload: Dict[str, Any] = Body(default_factory=dict)):
        raw=text(payload.get("vault_path"));
        if not raw: raise HTTPException(422,"请填写 Vault 路径")
        path=Path(raw).expanduser().resolve();
        if not path.exists() or not path.is_dir(): raise HTTPException(422,"Vault 路径不存在或不是目录")
        cfg=config(); cfg["obsidian_vault"]=str(path); atomic_json(CONFIG_FILE,cfg); return {"ok":True,"version":VERSION,"vault":str(path),"git":(path/".git").exists()}

    @app.post("/api/video/integration/obsidian/sync")
    def obsidian_sync(payload: Dict[str, Any] = Body(default_factory=dict)):
        vault=vault_path();
        if not vault: raise HTTPException(409,"尚未配置有效 Vault")
        git=git_pull(vault) if payload.get("git_pull",True) else {"attempted":False,"ok":True}; incoming=[]; files=sorted(vault.rglob("*.md"), key=lambda p:p.stat().st_mtime, reverse=True)
        for path in files[:int(payload.get("max_files") or 500)]:
            try: incoming.extend(markdown_cards(path.read_text(encoding="utf-8"),"obsidian_vault",str(path.relative_to(vault))))
            except Exception: pass
        cards,added=merge_cards(incoming); return {"ok":True,"version":VERSION,"vault":str(vault),"git":git,"files_scanned":len(files),"cards_parsed":len(incoming),"added":added,"total":len(cards)}

    @app.post("/api/video/integration/obsidian/writeback")
    def obsidian_writeback(payload: Dict[str, Any] = Body(default_factory=dict)):
        vault=vault_path();
        if not vault: raise HTTPException(409,"尚未配置有效 Vault")
        root_folder=vault/text(payload.get("folder") or "AI-VIDEO-Content-Brain"); root_folder.mkdir(parents=True,exist_ok=True); written=0; by_collection={}
        for card in [c for c in load_cards() if c.get("status")=="approved"][:int(payload.get("limit") or 500)]:
            collection=text(card.get("collection")) if text(card.get("collection")) in KNOWLEDGE_COLLECTIONS else "research"
            folder=root_folder/COLLECTION_FOLDERS[collection]; folder.mkdir(parents=True,exist_ok=True)
            safe=re.sub(r"[^\w\u4e00-\u9fff.-]+","_",text(card.get("title")))[:80] or text(card.get("id")); target=folder/f"{safe}_{text(card.get('id'))[-8:]}.md"
            target.write_text("\n".join([f"# {text(card.get('title'))}","",f"- 隔离区：{collection}",f"- 来源：{text(card.get('source'))}",f"- 类型：{text(card.get('type'))}",f"- 分区：{text(card.get('lane'))}",f"- 分数：{card.get('score')}",f"- 标签：{', '.join(as_list(card.get('tags')))}","",text(card.get("content")),""]),encoding="utf-8")
            written+=1; by_collection[collection]=by_collection.get(collection,0)+1
        return {"ok":True,"version":VERSION,"folder":str(root_folder),"written":written,"by_collection":by_collection,"folders":COLLECTION_FOLDERS}

    @app.get("/api/video/integration/openclaw/status")
    async def openclaw_status():
        attempts=[]
        fallback_online=False
        fallback_detail={}
        fallback_endpoint=""
        for path in OPENCLAW_HEALTH:
            status,data=await internal_json(app,"GET",path,timeout=30)
            attempts.append({"path":path,"status":status})
            if status<400 and data.get("ok",True) is not False:
                fallback_online=True
                fallback_detail=as_dict(data)
                fallback_endpoint=path
                break

        heartbeat=collector_worker_heartbeat(max_age_seconds=20)
        collector_worker_online=bool(heartbeat.get("online"))
        login_ok=bool(
            fallback_detail.get("login_ok")
            or fallback_detail.get("logged_in")
            or fallback_detail.get("authenticated")
        )
        backend_online=bool(fallback_online or collector_worker_online)
        return {
            "ok": True,
            "version": VERSION,
            "online": backend_online,
            "backend_online": backend_online,
            "worker_online": collector_worker_online,
            "collector_worker_online": collector_worker_online,
            "fallback_worker_online": fallback_online,
            "login_ok": login_ok,
            "endpoint": fallback_endpoint or "/api/collector/commands/next",
            "detail": fallback_detail,
            "collector_heartbeat": heartbeat,
            "attempts": attempts,
        }

    @app.get("/api/video/integration/openclaw/queue-status")
    def openclaw_queue_status(limit: int = Query(50, ge=1, le=200)):
        return {"ok": True, "version": VERSION, **collector_queue_mirror_status(limit)}

    @app.get("/api/video/integration/openclaw/runs")
    def openclaw_runs(account_profile: str = Query(""), active_only: bool = Query(False), limit: int = Query(30, ge=1, le=200)):
        runs=read_json(RUN_FILE,{})
        values=[public_run(as_dict(value)) for value in (runs.values() if isinstance(runs,dict) else [])]
        if account_profile: values=[item for item in values if item.get("account_profile")==account_profile]
        if active_only: values=[item for item in values if item.get("is_active")]
        values.sort(key=lambda item:int(item.get("updated_at") or item.get("created_at") or 0),reverse=True)
        return {"ok":True,"version":VERSION,"runs":values[:limit],"total":len(values)}

    @app.get("/api/video/integration/openclaw/latest")
    def openclaw_latest(account_profile: str = Query("company_main")):
        data=openclaw_runs(account_profile=account_profile,active_only=False,limit=50)
        values=as_list(data.get("runs"))
        active=next((item for item in values if item.get("is_active")),None)
        return {"ok":True,"version":VERSION,"account_profile":account_profile,"run":active or (values[0] if values else None),"active":bool(active)}

    async def _start_real_openclaw(payload: Dict[str, Any], *, supersedes: str = "") -> Dict[str, Any]:
        health=await openclaw_status()
        if not health.get("backend_online"):
            raise HTTPException(503,"OpenClaw 后端离线，无法开始采集。")
        if not health.get("collector_worker_online"):
            raise HTTPException(503,"ECS Collector Worker 没有真实心跳，已阻止继续堆积 queued 任务。")
        if text(payload.get("platform") or "douyin").lower()=="douyin" and not health.get("login_ok"):
            raise HTTPException(409,"Worker 已在线，但抖音账号尚未登录。请登录对应隔离账号后再启动任务。")

        account_profile=text(payload.get("account_profile") or "company_main")
        request={
            **payload,
            "account_profile": account_profile,
            "source": text(payload.get("source") or "integration_hub_v10_40_8_2"),
            "run_openclaw_analysis": True,
            "persist_results": True,
        }

        # 新 OpenClaw discovery 优先；不存在时，把完整任务封装进 legacy raw，
        # 避免 Pydantic 只保留 limit/account 导致 raw={}、任务无法执行。
        endpoint="/api/openclaw/discovery/start"
        status,data=await internal_json(app,"POST",endpoint,request,timeout=180)
        if status>=400:
            seed_accounts=[text(item) for item in as_list(request.get("seed_accounts")) if text(item)]
            keyword=text(request.get("keyword") or request.get("market"))
            limit=max(1,min(int(request.get("max_accounts") or len(seed_accounts) or 1),120))
            legacy_payload={
                "limit": limit,
                "account": seed_accounts[0] if seed_accounts else keyword,
                "headful": True,
                "no_delay": limit<=3,
                "mode": text(request.get("mission_type") or "manual"),
                "message": f"等待 ECS Worker 领取：{text(request.get('mission_type') or 'comments')} · {limit} 个账号",
                "raw": request,
            }
            endpoint="/api/collector/commands"
            status,data=await internal_json(app,"POST",endpoint,legacy_payload,timeout=180)

        if status>=400:
            raise HTTPException(status,data)
        job_id=text(data.get("job_id") or data.get("run_id") or data.get("command_id") or data.get("id"))
        if not job_id:
            raise HTTPException(502,"采集接口返回成功但没有 job_id/run_id，已阻止假成功。")

        runs=read_json(RUN_FILE,{})
        runs=runs if isinstance(runs,dict) else {}
        if supersedes and supersedes in runs:
            old=as_dict(runs.get(supersedes))
            runs[supersedes]={
                **old,
                "status":"superseded",
                "stage":"superseded",
                "is_active":False,
                "superseded_by":job_id,
                "updated_at":now(),
            }
        runs[job_id]={
            "job_id":job_id,
            "status":text(data.get("status") or "queued"),
            "stage":text(data.get("stage") or data.get("status") or "queued"),
            "progress":run_progress(data),
            "account_profile":account_profile,
            "mission_type":text(request.get("mission_type") or "comments"),
            "endpoint":endpoint,
            "request":request,
            "response":data,
            "created_at":now(),
            "updated_at":now(),
            "supersedes":supersedes,
        }
        atomic_json(RUN_FILE,runs)
        return {
            "ok":True,
            "version":VERSION,
            **public_run(runs[job_id]),
            "online":True,
            "endpoint":endpoint,
            "raw":data,
        }

    @app.post("/api/video/integration/openclaw/start")
    async def openclaw_start(payload: Dict[str, Any] = Body(default_factory=dict)):
        return await _start_real_openclaw(payload)

    @app.post("/api/video/integration/openclaw/requeue/{job_id}")
    async def openclaw_requeue(job_id: str):
        runs=read_json(RUN_FILE,{})
        local=as_dict(runs.get(job_id)) if isinstance(runs,dict) else {}
        if not local:
            raise HTTPException(404,f"找不到可重新排队的任务：{job_id}")
        request=as_dict(local.get("request"))
        if not request:
            raise HTTPException(409,"旧任务没有保存完整请求参数，不能安全重新排队。")
        return await _start_real_openclaw(request,supersedes=job_id)

    def _mirror_command(job_id: str) -> Dict[str, Any]:
        mirror=collector_queue_mirror_status(200)
        for command in as_list(mirror.get("commands")):
            command_id=text(command.get("id") or command.get("command_id"))
            if command_id==job_id:
                return as_dict(command)
        return {}

    @app.get("/api/video/integration/openclaw/job/{job_id}")
    async def openclaw_job(job_id: str):
        runs=read_json(RUN_FILE,{})
        local=as_dict(runs.get(job_id)) if isinstance(runs,dict) else {}
        mirror=_mirror_command(job_id)
        if mirror:
            data=mirror
            endpoint="/api/collector/commands/next · local mirror"
            status=200
        else:
            paths=[path.format(job_id=job_id) for path in OPENCLAW_JOB]
            endpoint,status,data=await first_available(app,"GET",paths,timeout=90)

        if status>=400:
            if local:
                public=public_run(local)
                return {
                    "ok":True,
                    "version":VERSION,
                    **public,
                    "upstream_available":False,
                }
            raise HTTPException(404,f"找不到 OpenClaw 任务：{job_id}")

        returned=text(data.get("job_id") or data.get("run_id") or data.get("command_id") or data.get("id") or job_id)
        if returned!=job_id:
            raise HTTPException(409,"OpenClaw 状态接口返回不同任务 ID，已阻止串任务。")
        status_text=text(data.get("status") or data.get("stage") or "running")
        if isinstance(runs,dict):
            runs[job_id]={
                **local,
                "job_id":job_id,
                "status":status_text,
                "stage":text(data.get("stage") or status_text),
                "progress":run_progress(data),
                "endpoint":endpoint,
                "response":data,
                "updated_at":now(),
            }
            atomic_json(RUN_FILE,runs)
        return {
            "ok":True,
            "version":VERSION,
            **public_run(as_dict(runs.get(job_id)) if isinstance(runs,dict) else {"job_id":job_id,"status":status_text,"response":data}),
            "endpoint":endpoint,
            "raw":data,
        }

    @app.get("/api/video/wizard-video/latest-done")
    def wizard_video_latest_done(
        limit: int = Query(30, ge=1, le=100),
        strict_one_scene: int = Query(1),
    ):
        try:
            from app.services.job_persistence_provider import get_job, list_recent_jobs
            jobs=list_recent_jobs(max(limit,100))
        except Exception as exc:
            raise HTTPException(500,f"读取视频任务持久化失败：{exc}")

        terminal={"done","completed","success","finished"}
        candidates=[]
        for item in jobs:
            status=text(item.get("status")).lower()
            job_type=text(item.get("job_type")).lower()
            video_url=text(item.get("video_url"))
            if status not in terminal or not video_url:
                continue
            if job_type not in {"full_ai","compose","one_scene","video"}:
                continue
            candidates.append(item)

        if not candidates:
            raise HTTPException(404,"暂时没有已完成并带 video_url 的成片任务")

        candidates.sort(key=lambda item:float(item.get("updated_at") or item.get("created_at") or 0),reverse=True)
        found=candidates[0]
        detailed=get_job(text(found.get("job_id"))) or {}
        merged={**found,**as_dict(detailed)}
        merged["video_url"]=text(merged.get("video_url") or found.get("video_url"))
        merged["recovery_job_type"]=text(found.get("job_type"))
        merged["workflow_bound"]=text(found.get("job_type")).lower() in {"full_ai","one_scene"}
        return {
            "ok":True,
            "version":VERSION,
            "job":merged,
            "recovery_mode":"exact_full_ai" if merged["workflow_bound"] else "latest_completed_compose",
            "strict_one_scene_requested":bool(strict_one_scene),
        }

    @app.post("/api/video/integration/openclaw/harvest/{job_id}")
    async def harvest(job_id: str, payload: Dict[str, Any] = Body(default_factory=dict)):
        # First read the exact job payload, then only accept global rows that explicitly
        # declare the same job/run/command id. This prevents cross-task knowledge leaks.
        job_paths=[path.format(job_id=job_id) for path in OPENCLAW_JOB]
        job_endpoint,job_status,job_data=await first_available(app,"GET",job_paths,timeout=90)
        rows=[]; sources=[{"path":job_endpoint or "job-specific", "status":job_status, "rows":0}]
        if job_status<400:
            returned=text(job_data.get("job_id") or job_data.get("run_id") or job_data.get("id") or job_id)
            if returned!=job_id: raise HTTPException(409,"OpenClaw 结果返回不同任务 ID，已阻止串任务。")
            job_rows=extract_rows(job_data); rows.extend(job_rows); sources[0]["rows"]=len(job_rows)
        for path in OPENCLAW_RESULTS:
            status,data=await internal_json(app,"GET",path,timeout=90)
            extracted=extract_rows(data) if status<400 else []
            bound=[]
            for row in extracted:
                row_id=text(row.get("job_id") or row.get("run_id") or row.get("command_id") or row.get("collector_run_id"))
                if row_id==job_id: bound.append(row)
            rows.extend(bound)
            sources.append({"path":path,"status":status,"rows":len(extracted),"bound_rows":len(bound)})
        collection=text(payload.get("collection") or "lead"); cards=[card for card in (lead_card(row, collection) for row in rows) if card]
        merged,added=merge_cards(cards)
        return {"ok":True,"version":VERSION,"job_id":job_id,"strict_job_binding":True,"rows_read":len(rows),"qualified_cards":len(cards),"added_to_brain":added,"brain_total":len(merged),"collection":collection,"sources":sources}

    @app.post("/api/video/integration/assets/gate")
    def asset_gate(payload: Dict[str, Any] = Body(default_factory=dict)):
        path=resolve_path(payload.get("path") or payload.get("url"));
        if not path: raise HTTPException(404,"找不到可审计的本地素材文件")
        report=audit_image(path) if path.suffix.lower() in {".jpg",".jpeg",".png",".webp",".bmp"} else audit_video(path,False,int(payload.get("sample_count") or 10))
        atomic_json(AUDIT_ROOT/f"asset_{hashlib.sha256(str(path).encode()).hexdigest()[:20]}.json",report); return report

    @app.post("/api/video/integration/video/audit")
    def video_audit(payload: Dict[str, Any] = Body(default_factory=dict)):
        path=resolve_path(payload.get("path") or payload.get("url"));
        if not path: raise HTTPException(404,"找不到当前任务的本地视频文件")
        return audit_video(path,bool(payload.get("allow_bottom_subtitle",True)),int(payload.get("sample_count") or 14))
