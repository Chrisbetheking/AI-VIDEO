# V10.34 A-G non-invasive backend extension
# Keeps the existing UI untouched while adding the requested workflow endpoints.
from __future__ import annotations

import csv
import json
import os
import shutil
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse

router = APIRouter(tags=["v10-34-complete"])

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
MATERIAL_DIR = DATA / "material-library"
ACCOUNT_DB = DATA / "douyin-accounts" / "accounts_v10_34.sqlite3"
OBSIDIAN_DIR = DATA / "obsidian-vault"
JOBS_DIR = DATA / "v10-34-jobs"

CATEGORIES = [
    "生活配套", "交通出勤", "医疗药房", "餐饮食馆", "户型采光", "学校教育",
    "商业商超", "项目园区", "城市航拍", "顾问口播", "客户案例", "政策流程", "其他"
]

BANNED_TRANSITIONS = ["cut", "smooth_cut", "flash", "flash_cut", "hard_cut", "jump_cut", "pull_out"]
SAFE_TRANSITION = "smooth_dissolve_no_flash"


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _ensure() -> None:
    MATERIAL_DIR.mkdir(parents=True, exist_ok=True)
    (DATA / "douyin-accounts").mkdir(parents=True, exist_ok=True)
    OBSIDIAN_DIR.mkdir(parents=True, exist_ok=True)
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(ACCOUNT_DB)
    con.execute("""
    CREATE TABLE IF NOT EXISTS accounts(
        id TEXT PRIMARY KEY,
        platform TEXT,
        nickname TEXT,
        url TEXT,
        city TEXT,
        category TEXT,
        score REAL,
        tags TEXT,
        raw_json TEXT,
        created_at TEXT,
        updated_at TEXT
    )
    """)
    con.commit(); con.close()


def _json_file(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _clean_transition_value(value: Any) -> str:
    text = str(value or "").lower().strip()
    return SAFE_TRANSITION if text in BANNED_TRANSITIONS or not text else SAFE_TRANSITION


def _sanitize_shot(shot: Dict[str, Any], index: int = 1) -> Dict[str, Any]:
    out = dict(shot or {})
    out.setdefault("index", index)
    out["transition"] = SAFE_TRANSITION
    out["transition_to_next"] = SAFE_TRANSITION
    out["concat_mode"] = "crossfade"
    out["v10_34_transition_lock"] = True
    for k in ("prompt", "visual_prompt", "positive_prompt"):
        if isinstance(out.get(k), str):
            txt = out[k]
            for w in BANNED_TRANSITIONS:
                txt = txt.replace(w, SAFE_TRANSITION).replace(w.replace("_", " "), SAFE_TRANSITION)
            out[k] = txt
    neg = str(out.get("negative_prompt") or "")
    extra = "hard cut, jump cut, flash transition, white flash, black flash, unreadable subtitles, watermark, logo"
    out["negative_prompt"] = (neg + ", " + extra).strip(", ") if neg else extra
    return out


@router.get("/api/video/v10-34/health")
def health():
    _ensure()
    return {"ok": True, "version": "v10.34-original-ui-complete", "ui": "preserved", "safe_transition": SAFE_TRANSITION}


@router.post("/api/video/v10-34/sanitize-shot-plan")
async def sanitize_shot_plan(request: Request):
    body = await request.json()
    shots = body.get("shots") if isinstance(body, dict) else []
    if not isinstance(shots, list): shots = []
    return {"ok": True, "transition_policy": {"allowed": [SAFE_TRANSITION, "cross_dissolve"], "blocked": BANNED_TRANSITIONS, "concat": "crossfade"}, "shots": [_sanitize_shot(s, i+1) for i, s in enumerate(shots)]}


@router.get("/api/video/material-library/health")
def material_health():
    _ensure(); return {"ok": True, "categories": CATEGORIES}


@router.get("/api/video/material-library/categories")
def material_categories():
    _ensure(); return {"ok": True, "categories": CATEGORIES}


@router.get("/api/video/material-library")
def material_list(category: str = "", city: str = "", reusable: str = ""):
    _ensure()
    items = []
    for meta in MATERIAL_DIR.rglob("*.json"):
        if meta.name.endswith(".meta.json"):
            item = _json_file(meta, {})
            if category and item.get("category") != category: continue
            if city and item.get("city") != city: continue
            if reusable and str(item.get("reusable", "")).lower() != reusable.lower(): continue
            items.append(item)
    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return {"ok": True, "items": items, "count": len(items)}


@router.post("/api/video/material-library/upload")
async def material_upload(
    files: List[UploadFile] = File(...),
    category: str = Form(...),
    city: str = Form(""),
    area: str = Form(""),
    source: str = Form(""),
    reusable: str = Form("true"),
    note: str = Form(""),
):
    _ensure()
    if not category or category not in CATEGORIES:
        return JSONResponse(status_code=400, content={"ok": False, "error": "必须选择有效分类后才能上传", "categories": CATEGORIES})
    saved = []
    folder = MATERIAL_DIR / category
    folder.mkdir(parents=True, exist_ok=True)
    for f in files:
        ext = Path(f.filename or "file").suffix.lower()
        asset_id = "mat_" + uuid.uuid4().hex[:16]
        name = f"{asset_id}{ext}"
        target = folder / name
        with target.open("wb") as out:
            shutil.copyfileobj(f.file, out)
        meta = {
            "id": asset_id,
            "filename": name,
            "original_name": f.filename,
            "category": category,
            "city": city,
            "area": area,
            "source": source,
            "reusable": str(reusable).lower() in ("1", "true", "yes", "y", "是"),
            "note": note,
            "path": str(target.relative_to(DATA)),
            "url": f"/api/video/material-library/file/{category}/{name}",
            "created_at": _now(),
        }
        _write_json(folder / f"{asset_id}.meta.json", meta)
        saved.append(meta)
    return {"ok": True, "items": saved}


@router.get("/api/video/material-library/file/{category}/{filename}")
def material_file(category: str, filename: str):
    from fastapi.responses import FileResponse
    path = MATERIAL_DIR / category / filename
    if not path.exists(): return JSONResponse(status_code=404, content={"ok": False, "error": "file not found"})
    return FileResponse(path)


def _classify_account(row: Dict[str, Any]) -> Dict[str, Any]:
    text = " ".join(str(row.get(k, "")) for k in ["nickname", "url", "bio", "note", "tags"]).lower()
    cat = "房产"
    if any(x in text for x in ["school", "学校", "留学", "教育"]): cat = "教育择校"
    elif any(x in text for x in ["餐", "food", "cafe", "restaurant"]): cat = "餐饮生活"
    elif any(x in text for x in ["medical", "clinic", "医院", "诊所", "药房"]): cat = "医疗健康"
    score = 60
    if any(x in text for x in ["买房", "置业", "房产", "condo", "property", "楼盘"]): score += 25
    if any(x in text for x in ["马来西亚", "malaysia", "吉隆坡", "kl", "柔佛", "槟城"]): score += 10
    return {"category": cat, "score": min(score, 99), "tags": [cat, "v10.34分类"]}


@router.post("/api/video/account-library/import")
async def account_import(request: Request):
    _ensure()
    body = await request.json()
    rows = body.get("accounts") or body.get("items") or []
    if isinstance(rows, str):
        rows = [{"url": x.strip()} for x in rows.splitlines() if x.strip()]
    con = sqlite3.connect(ACCOUNT_DB)
    saved = []
    for row in rows:
        if not isinstance(row, dict): continue
        acc_id = str(row.get("id") or "acc_" + uuid.uuid4().hex[:16])
        c = _classify_account(row)
        item = {
            "id": acc_id,
            "platform": row.get("platform") or "douyin",
            "nickname": row.get("nickname") or row.get("name") or "",
            "url": row.get("url") or "",
            "city": row.get("city") or "",
            "category": c["category"],
            "score": c["score"],
            "tags": json.dumps(c["tags"], ensure_ascii=False),
            "raw_json": json.dumps(row, ensure_ascii=False),
            "created_at": _now(),
            "updated_at": _now(),
        }
        con.execute("""INSERT OR REPLACE INTO accounts(id,platform,nickname,url,city,category,score,tags,raw_json,created_at,updated_at)
        VALUES(:id,:platform,:nickname,:url,:city,:category,:score,:tags,:raw_json,:created_at,:updated_at)""", item)
        saved.append(item)
    con.commit(); con.close()
    return {"ok": True, "items": saved, "count": len(saved)}


@router.get("/api/video/account-library/accounts")
def account_list(category: str = "", min_score: float = 0):
    _ensure(); con = sqlite3.connect(ACCOUNT_DB); con.row_factory = sqlite3.Row
    sql = "SELECT * FROM accounts WHERE score>=?"; args=[min_score]
    if category:
        sql += " AND category=?"; args.append(category)
    sql += " ORDER BY score DESC, updated_at DESC LIMIT 500"
    rows = [dict(r) for r in con.execute(sql, args).fetchall()]
    con.close()
    for r in rows:
        try: r["tags"] = json.loads(r.get("tags") or "[]")
        except Exception: r["tags"] = []
    return {"ok": True, "items": rows, "count": len(rows)}


@router.post("/api/video/account-library/classify")
async def account_classify(request: Request):
    body = await request.json()
    row = body if isinstance(body, dict) else {}
    return {"ok": True, "classification": _classify_account(row)}


@router.post("/api/video/openclaw/collect/start")
async def openclaw_collect_start(request: Request):
    _ensure(); body = await request.json()
    job_id = "openclaw_" + uuid.uuid4().hex[:16]
    job = {"id": job_id, "status": "queued", "request": body, "created_at": _now(), "note": "OpenClaw worker 接口已预留；服务器有 worker 时可接入真实采集。"}
    _write_json(JOBS_DIR / f"{job_id}.json", job)
    return {"ok": True, "job_id": job_id, "job": job}


@router.get("/api/video/openclaw/collect/job/{job_id}")
def openclaw_collect_job(job_id: str):
    job = _json_file(JOBS_DIR / f"{job_id}.json", None)
    if not job: return JSONResponse(status_code=404, content={"ok": False, "error": "job not found"})
    return {"ok": True, "job": job}


@router.get("/api/video/obsidian/health")
def obsidian_health():
    _ensure(); return {"ok": True, "vault": str(OBSIDIAN_DIR)}


@router.get("/api/video/obsidian/notes")
def obsidian_notes():
    _ensure()
    notes=[]
    for p in OBSIDIAN_DIR.rglob("*.md"):
        notes.append({"path": str(p.relative_to(OBSIDIAN_DIR)), "title": p.stem, "updated_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(p.stat().st_mtime))})
    return {"ok": True, "items": notes}


@router.post("/api/video/obsidian/notes")
async def obsidian_create_note(request: Request):
    _ensure(); body = await request.json()
    title = str(body.get("title") or "未命名增长笔记").strip().replace("/", "-")[:80]
    content = str(body.get("content") or body.get("text") or "")
    tags = body.get("tags") or ["AI视频", "V10.34"]
    path = OBSIDIAN_DIR / f"{time.strftime('%Y%m%d_%H%M%S')}_{title}.md"
    md = "---\n" + f"title: {title}\ncreated: {_now()}\ntags: {json.dumps(tags, ensure_ascii=False)}\n" + "---\n\n" + content + "\n"
    path.write_text(md, encoding="utf-8")
    return {"ok": True, "path": str(path.relative_to(OBSIDIAN_DIR)), "title": title}




def _split_sentences(text: str) -> List[str]:
    import re
    raw = [x.strip() for x in re.split(r"[\n。！？!?；;]+", str(text or "")) if x.strip()]
    out: List[str] = []
    for line in raw:
        if len(line) <= 38:
            out.append(line)
        else:
            chunks = re.split(r"[，,、]+", line)
            cur = ""
            for c in chunks:
                c = c.strip()
                if not c:
                    continue
                if len(cur) + len(c) <= 34:
                    cur = (cur + "，" + c).strip("，")
                else:
                    if cur:
                        out.append(cur)
                    cur = c
            if cur:
                out.append(cur)
    return out[:16]


def _safe_keywords(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    return [x.strip() for x in str(value or "").replace("，", ",").split(",") if x.strip()]


@router.post("/api/video/v10-34/step2/script")
async def step2_script(request: Request):
    _ensure()
    body = await request.json()
    title = str(body.get("title") or body.get("topic") or "短视频口播稿").strip()
    audience = str(body.get("audience") or "目标客户").strip()
    selling_points = str(body.get("selling_points") or "").strip()
    style = str(body.get("style") or "真实顾问口播").strip()
    keywords = _safe_keywords(body.get("keywords"))[:12]
    banned = _safe_keywords(body.get("banned_words"))[:20]
    script = str(body.get("script") or "").strip()
    if not script:
        kw_text = "、".join(keywords[:6]) or "生活配套、交通、教育、医疗、餐饮"
        script = "\n".join([
            f"如果你正在了解{title}，先别只看价格和样板间。",
            f"真正影响长期居住体验的，是{kw_text}这些每天都会用到的东西。",
            f"我建议你按生活便利、通勤时间、教育医疗和后续服务这几项一起看。",
            f"尤其是{audience}，不要被单一卖点带着走，要看它能不能解决你的真实需求。",
            "想要完整清单，可以私信我，我按你的预算和家庭情况给你整理。",
        ])
    for w in banned:
        if w:
            script = script.replace(w, "")
    parts = _split_sentences(script)
    segments = []
    for i, text in enumerate(parts):
        emotion = "开场提醒" if i == 0 else "重点解释" if i < len(parts) - 1 else "结尾转化"
        segments.append({
            "index": i + 1,
            "text": text,
            "emotion": emotion,
            "speed_ratio": 1.05 if i < len(parts) - 1 else 1.0,
            "volume_ratio": 1.0,
            "pitch_ratio": 1.0,
            "pause_after_ms": 320 if i < len(parts) - 1 else 520,
            "keywords": keywords,
        })
    version_id = "script_v_" + uuid.uuid4().hex[:16]
    data = {
        "ok": True,
        "version_id": version_id,
        "title": title,
        "hook": parts[0] if parts else title,
        "script": "\n".join(p["text"] for p in segments),
        "segments": segments,
        "keywords": keywords,
        "banned_words": banned,
        "style": style,
        "rules": ["real_script_only", "no_invented_subtitle", "keyword_required", "banned_words_removed"],
        "created_at": _now(),
    }
    _write_json(JOBS_DIR / f"{version_id}.json", data)
    return data


@router.post("/api/video/v10-34/step2/save")
async def step2_save(request: Request):
    _ensure()
    body = await request.json()
    version_id = str(body.get("version_id") or "voice_v_" + uuid.uuid4().hex[:16])
    data = {
        "ok": True,
        "version_id": version_id,
        "type": "step2_voice_version",
        "title": body.get("title") or "口播版本",
        "hook": body.get("hook") or "",
        "script": body.get("script") or "",
        "voice": body.get("voice") or "",
        "segments": body.get("segments") or [],
        "keywords": body.get("keywords") or [],
        "banned_words": body.get("banned_words") or [],
        "audio_file_name": body.get("audio_file_name") or "",
        "audio_url": body.get("audio_url") or "",
        "created_at": _now(),
    }
    _write_json(JOBS_DIR / f"{version_id}.json", data)
    return data


@router.post("/api/video/v10-34/complete-job")
async def complete_job(request: Request):
    _ensure()
    body = await request.json()
    job_id = str(body.get("job_id") or "completed_" + uuid.uuid4().hex[:16])
    shots = body.get("shots") or []
    fixed = []
    warnings = []
    for i, shot in enumerate(shots if isinstance(shots, list) else []):
        if not isinstance(shot, dict):
            continue
        item = _sanitize_shot(shot, i + 1)
        item["job_id"] = item.get("job_id") or job_id
        item["raw_clip"] = item.get("raw_clip") or item.get("filename") or item.get("url") or ""
        item["duration"] = item.get("duration") or item.get("duration_seconds") or item.get("image_seconds") or 0
        required = ["raw_clip", "prompt", "negative_prompt", "scene_type", "narration_segment", "duration", "job_id"]
        missing = [k for k in required if item.get(k) in (None, "", [])]
        if missing:
            warnings.append({"shot": i + 1, "missing": missing})
        fixed.append(item)
    manifest = {
        "ok": True,
        "job_id": job_id,
        "status": "completed_with_v10_34_guard" if not warnings else "completed_with_metadata_warnings",
        "title": body.get("title") or "",
        "video": body.get("video") or {},
        "script": body.get("script") or "",
        "audio_file_name": body.get("audio_file_name") or "",
        "shots": fixed,
        "warnings": warnings,
        "transition_policy": {"safe_transition": SAFE_TRANSITION, "blocked": BANNED_TRANSITIONS, "concat": "crossfade"},
        "created_at": _now(),
    }
    _write_json(JOBS_DIR / f"{job_id}.complete.json", manifest)
    return manifest

@router.get("/api/video/ai-console/health")
def ai_console_health():
    return {"ok": True, "modules": ["video_loop", "step2_tts", "material_library", "account_library", "openclaw", "obsidian", "console"]}




def _account_count() -> int:
    try:
        _ensure()
        con = sqlite3.connect(ACCOUNT_DB)
        n = int(con.execute("SELECT COUNT(*) FROM accounts").fetchone()[0])
        con.close()
        return n
    except Exception:
        return 0

@router.get("/api/video/ai-console/status")
def ai_console_status():
    _ensure()
    return {
        "ok": True,
        "version": "v10.34 A-G original-ui",
        "ui_policy": "frontend/src/App.tsx preserved",
        "backend_origin": "https://ai-video.47-76-143-158.sslip.io",
        "counts": {
            "materials": len(list(MATERIAL_DIR.rglob("*.meta.json"))),
            "obsidian_notes": len(list(OBSIDIAN_DIR.rglob("*.md"))),
            "accounts": _account_count(),
            "openclaw_jobs": len(list(JOBS_DIR.glob("openclaw_*.json"))),
            "completed_jobs": len(list(JOBS_DIR.glob("*.complete.json"))),
            "script_versions": len(list(JOBS_DIR.glob("script_v_*.json"))) + len(list(JOBS_DIR.glob("voice_v_*.json"))),
        },
        "video_transition_lock": {"safe_transition": SAFE_TRANSITION, "banned": BANNED_TRANSITIONS, "concat": "crossfade"},
    }


def install_v10_34_complete(app):
    _ensure()
    existing = {getattr(r, "path", "") for r in getattr(app, "routes", [])}
    if "/api/video/v10-34/health" not in existing:
        app.include_router(router)
        print("V10_34_A_TO_G_ORIGINAL_UI_ROUTES_INSTALLED", flush=True)
    return app
