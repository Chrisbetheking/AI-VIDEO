
from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import os
import re
import shutil
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

BACKEND_VERSION = "v10.34-a-to-g-complete"
BACKEND_ORIGIN = os.getenv("AI_VIDEO_PUBLIC_BACKEND", "https://ai-video.47-76-143-158.sslip.io").rstrip("/")
OPENCLAW_CAPTURE_URL = os.getenv("OPENCLAW_CAPTURE_URL", "").strip()
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")


def _storage_root() -> Path:
    root = Path(os.getenv("AI_VIDEO_STORAGE_DIR", "/opt/ai-video/storage"))
    try:
        root.mkdir(parents=True, exist_ok=True)
        return root
    except Exception:
        root = Path(__file__).resolve().parents[2] / "data" / "storage"
        root.mkdir(parents=True, exist_ok=True)
        return root

ROOT = _storage_root()
BASE = ROOT / "v10_34_complete"
DB = BASE / "v10_34_complete.sqlite3"
MATERIAL_DIR = BASE / "material_library"
SHOT_ASSET_DIR = BASE / "generated_shot_assets"
FINAL_DIR = BASE / "approved_final_videos"
VOICE_DIR = BASE / "voice_previews"
SCRIPT_DIR = BASE / "script_versions"
OBSIDIAN_DIR = ROOT / "obsidian-vault"
ACCOUNT_DIR = BASE / "account_imports"
OPENCLAW_DIR = BASE / "openclaw"
for p in [BASE, MATERIAL_DIR, SHOT_ASSET_DIR, FINAL_DIR, VOICE_DIR, SCRIPT_DIR, OBSIDIAN_DIR, ACCOUNT_DIR, OPENCLAW_DIR]:
    p.mkdir(parents=True, exist_ok=True)

CATEGORY_DEFS = [
    {"id":"property","label":"房产/楼盘素材","keywords":["房产","楼盘","公寓","condo","样板间","外立面","物业"]},
    {"id":"life","label":"生活配套","keywords":["生活","超市","便利店","商场","配套","华人","社区","街区"]},
    {"id":"traffic","label":"交通出勤","keywords":["交通","地铁","捷运","MRT","LRT","公交","通勤","车站","高速","主干道"]},
    {"id":"medical","label":"医疗/诊所/药房","keywords":["医疗","诊所","药房","医院","看病","买药","clinic","pharmacy"]},
    {"id":"food","label":"餐饮/食阁","keywords":["餐饮","吃","食阁","饭","咖啡","餐厅","外卖","小吃"]},
    {"id":"education","label":"教育/学校","keywords":["学校","教育","国际学校","孩子","上学","校车"]},
    {"id":"interior","label":"户型/室内","keywords":["户型","采光","阳台","卧室","客厅","厨房","装修","空间"]},
    {"id":"deal","label":"成交/带看/租客","keywords":["投资","出租","租客","转售","回报","带看","成交","持有"]},
    {"id":"avatar","label":"人物口播/数字人模板","keywords":["口播","真人","数字人","avatar","人物"]},
    {"id":"report","label":"报告/资料/截图","keywords":["报告","截图","资料","表格","政策","清单"]},
]

BANNED_TRANSITIONS = [
    "cut", "smooth_cut", "flash", "white flash", "black flash", "strobe", "flicker", "hard cut",
    "jump cut", "pull_out", "opening_slow_push_in", "horizontal_pan_match", "match cut", "smash cut", "wipe", "glitch"
]
SAFE_TRANSITION = "smooth_dissolve_no_flash"


def _db() -> sqlite3.Connection:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def _init_db() -> None:
    with _db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS materials (
            asset_id TEXT PRIMARY KEY,
            filename TEXT,
            original_name TEXT,
            kind TEXT NOT NULL,
            category TEXT NOT NULL,
            city TEXT NOT NULL DEFAULT '',
            district TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT '',
            reusable INTEGER NOT NULL DEFAULT 1,
            tags TEXT NOT NULL DEFAULT '[]',
            note TEXT NOT NULL DEFAULT '',
            mime_type TEXT NOT NULL DEFAULT '',
            size_bytes INTEGER NOT NULL DEFAULT 0,
            file_path TEXT NOT NULL DEFAULT '',
            file_url TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS accounts (
            account_id TEXT PRIMARY KEY,
            platform TEXT NOT NULL DEFAULT '',
            handle TEXT NOT NULL DEFAULT '',
            name TEXT NOT NULL DEFAULT '',
            url TEXT NOT NULL DEFAULT '',
            city TEXT NOT NULL DEFAULT '',
            industry TEXT NOT NULL DEFAULT '',
            follower_count INTEGER NOT NULL DEFAULT 0,
            category TEXT NOT NULL DEFAULT '',
            value_level TEXT NOT NULL DEFAULT '',
            tags TEXT NOT NULL DEFAULT '[]',
            raw_json TEXT NOT NULL DEFAULT '{}',
            classification_json TEXT NOT NULL DEFAULT '{}',
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS openclaw_tasks (
            task_id TEXT PRIMARY KEY,
            mode TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT '',
            target_url TEXT NOT NULL DEFAULT '',
            request_json TEXT NOT NULL DEFAULT '{}',
            result_json TEXT NOT NULL DEFAULT '{}',
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS obsidian_notes (
            note_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            path TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT '',
            tags TEXT NOT NULL DEFAULT '[]',
            summary TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ai_control_events (
            event_id TEXT PRIMARY KEY,
            action TEXT NOT NULL,
            status TEXT NOT NULL,
            input_json TEXT NOT NULL DEFAULT '{}',
            output_json TEXT NOT NULL DEFAULT '{}',
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            stage TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT 'v10_34_complete',
            delegate_job_id TEXT NOT NULL DEFAULT '',
            request_json TEXT NOT NULL DEFAULT '{}',
            result_json TEXT NOT NULL DEFAULT '{}',
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS script_versions (
            version_id TEXT PRIMARY KEY,
            script_text TEXT NOT NULL,
            keywords TEXT NOT NULL DEFAULT '[]',
            forbidden_words TEXT NOT NULL DEFAULT '[]',
            voice_json TEXT NOT NULL DEFAULT '{}',
            note TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL
        );
        """)

_init_db()


def _now() -> int:
    return int(time.time())


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}


def _safe_name(name: str) -> str:
    name = Path(name or "file").name
    name = re.sub(r"[^0-9A-Za-z._\-\u4e00-\u9fff]+", "_", name).strip("._")
    return name or f"file_{uuid.uuid4().hex[:8]}"


def _json_loads(raw: Any, fallback: Any) -> Any:
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(str(raw or ""))
    except Exception:
        return fallback


def _split_words(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    return [x.strip() for x in re.split(r"[,，\s/|]+", str(value or "")) if x.strip()]


def _split_script(script: str) -> list[str]:
    text = re.sub(r"\r", "", str(script or "")).strip()
    parts = [p.strip() for p in re.split(r"(?<=[。！？!?])\s*|\n+", text) if p.strip()]
    if not parts and text:
        parts = [text]
    return parts


def _classify_scene(text: str) -> dict[str, Any]:
    score = []
    lower = str(text or "").lower()
    for cat in CATEGORY_DEFS:
        s = sum(1 for kw in cat["keywords"] if str(kw).lower() in lower)
        if s:
            score.append((s, cat))
    cat = sorted(score, key=lambda x: -x[0])[0][1] if score else CATEGORY_DEFS[0]
    visuals = {
        "property":"楼盘外立面、社区道路、样板间和真实街区环境",
        "life":"超市、便利店、商场、街区生活和社区日常人流",
        "traffic":"MRT/LRT、公交站、主干道、车流和真实通勤路径",
        "medical":"社区诊所、药房、医疗配套入口和买药看病场景",
        "food":"食阁、餐厅、咖啡馆、外卖店和真实就餐环境",
        "education":"学校周边、校车、家庭接送和教育生活场景",
        "interior":"客厅、厨房、卧室、阳台、采光和空间动线",
        "deal":"租客看房、带看咨询、社区人流和成交沟通",
        "avatar":"真人口播、半身讲解、干净背景、自然手势",
        "report":"报告截图、清单、表格、资料页和重点标注"
    }.get(cat["id"], "真实城市生活素材")
    return {"scene_type": cat["id"], "category": cat["label"], "visual": visuals}


def _clean_transition_text(text: Any) -> str:
    t = str(text or "")
    for word in sorted(BANNED_TRANSITIONS, key=len, reverse=True):
        t = re.sub(re.escape(word), SAFE_TRANSITION, t, flags=re.I)
    if not t.strip():
        t = SAFE_TRANSITION
    return t


def _clean_prompt(text: Any) -> str:
    t = str(text or "")
    for word in sorted(BANNED_TRANSITIONS, key=len, reverse=True):
        t = re.sub(re.escape(word), SAFE_TRANSITION, t, flags=re.I)
    lock = " Transition lock: only smooth dissolve / natural continuous movement; no flash, no cut, no hard cut, no pull out, no wipe, no glitch, no sudden exposure change."
    if "Transition lock:" not in t:
        t = (t.rstrip() + lock).strip()
    return t


def _negative_prompt(extra: str = "") -> str:
    base = "white flash, black flash, flash transition, cut, hard cut, jump cut, smooth_cut, pull_out, strobe, flicker, wipe, glitch, sudden exposure change, random unrelated visuals, text overlay, readable logo, watermark"
    return (str(extra or "").strip(", ") + ", " + base).strip(", ") if extra else base


def _build_shot_plan(script_text: str, requested_shots: Optional[list[Any]] = None, audio_duration: float = 0.0) -> list[dict[str, Any]]:
    if isinstance(requested_shots, list) and requested_shots:
        raw_shots = [x if isinstance(x, dict) else {"narration": str(x)} for x in requested_shots]
    else:
        raw_shots = [{"narration": x} for x in _split_script(script_text)]
    if not raw_shots:
        raise HTTPException(status_code=400, detail="script_text_required")
    n = len(raw_shots)
    fade = 0.28
    # xfade 吃时长，预留；每段 2-6 秒，语音太长时要求更多镜头。
    target_total = max(float(audio_duration or 0) + fade * max(0, n - 1) + 0.6, sum(float(x.get("duration") or x.get("duration_seconds") or 0) for x in raw_shots))
    per = max(2.0, min(6.0, target_total / n if target_total else 3.5))
    if audio_duration and target_total > 6.0 * n + 0.2:
        raise HTTPException(status_code=400, detail={
            "error":"audio_too_long_for_current_shot_count",
            "message":"口播太长，当前镜头数不够覆盖语音时长；请拆更多句/更多镜头后再生成，避免重复画面。",
            "audio_duration": audio_duration,
            "shot_count": n,
            "max_video_duration": 6.0 * n
        })
    shots: list[dict[str, Any]] = []
    t = 0.0
    for i, raw in enumerate(raw_shots, start=1):
        narration = str(raw.get("narration") or raw.get("narration_segment") or raw.get("text") or raw.get("clean_subtitle") or "").strip()
        scene = _classify_scene(narration + " " + str(raw.get("category") or raw.get("scene_type") or ""))
        visual = str(raw.get("visual") or raw.get("visual_subject") or scene["visual"])
        duration = float(raw.get("duration_seconds") or raw.get("duration") or per)
        duration = max(2.0, min(6.0, duration))
        end = t + duration
        prompt = raw.get("prompt") or raw.get("visual_prompt") or f"{visual}，真实马来西亚城市生活纪录片质感，竖屏9:16，稳定镜头，无字幕，无可读文字，无logo。必须对应口播：{narration}"
        shot = {
            **raw,
            "index": i,
            "shot_index": i,
            "narration_segment": narration,
            "clean_subtitle": narration,
            "scene_type": raw.get("scene_type") or raw.get("semantic_type") or scene["scene_type"],
            "category": raw.get("category") or scene["category"],
            "visual_subject": visual,
            "visual_prompt": _clean_prompt(prompt),
            "prompt": _clean_prompt(prompt),
            "negative_prompt": _negative_prompt(str(raw.get("negative_prompt") or "")),
            "transition": SAFE_TRANSITION,
            "transition_to_next": SAFE_TRANSITION,
            "duration_seconds": round(duration, 2),
            "start_seconds": round(t, 2),
            "end_seconds": round(end, 2),
            "motion": _clean_transition_text(raw.get("motion") or raw.get("camera") or "stable_slow_push_in"),
            "v10_34a_rules": {
                "ban_cut": True,
                "ban_smooth_cut": True,
                "ban_flash": True,
                "ban_pull_out": True,
                "required_transition": SAFE_TRANSITION,
                "concat": "xfade_crossfade_only"
            }
        }
        shots.append(shot)
        t = end
    return shots


def _acceptance(script_text: str, shots: list[dict[str, Any]]) -> dict[str, Any]:
    required = []
    text = script_text or ""
    for cat in CATEGORY_DEFS:
        if any(str(kw).lower() in text.lower() for kw in cat["keywords"]):
            required.append(cat["id"])
    covered = sorted({str(s.get("scene_type") or "") for s in shots if s.get("scene_type")})
    missing = [c for c in required if c not in covered]
    bad = []
    for s in shots:
        joined = json.dumps(s, ensure_ascii=False).lower()
        for w in BANNED_TRANSITIONS:
            if w.lower() in joined and SAFE_TRANSITION.lower() not in w.lower():
                bad.append({"shot_index": s.get("index"), "banned": w})
    return {
        "passed": not missing and not bad,
        "required_categories": required,
        "covered_categories": covered,
        "missing_categories": missing,
        "banned_transition_hits": bad,
        "transition_lock": SAFE_TRANSITION,
        "completed_status_guard": "final job cannot be marked completed unless final_video_url/subtitled_video_url exists and generated shot metadata has been persisted",
    }


def _save_generated_shot_assets(job_id: str, shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    base = SHOT_ASSET_DIR / job_id
    base.mkdir(parents=True, exist_ok=True)
    items = []
    for s in shots:
        idx = int(s.get("index") or s.get("shot_index") or len(items) + 1)
        meta = {
            "ok": True,
            "asset_type": "generated_fal_shot_metadata",
            "version": BACKEND_VERSION,
            "job_id": job_id,
            "shot_index": idx,
            "raw_clip_path": str(base / f"shot_{idx:02d}_raw.mp4"),
            "fixed_clip_path": str(base / f"shot_{idx:02d}_fixed.mp4"),
            "fal_job_id": s.get("fal_job_id") or "",
            "fal_video_url": s.get("fal_video_url") or "",
            "prompt": s.get("visual_prompt") or s.get("prompt") or "",
            "negative_prompt": s.get("negative_prompt") or _negative_prompt(),
            "scene_type": s.get("scene_type"),
            "category": s.get("category"),
            "narration_segment": s.get("narration_segment") or s.get("clean_subtitle"),
            "duration_seconds": s.get("duration_seconds"),
            "transition": SAFE_TRANSITION,
            "reuse_policy": "can_reuse_after_human_approval",
            "human_approved": False,
            "created_at": _now(),
        }
        (base / f"shot_{idx:02d}_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        items.append(meta)
    return items


def _public_file_url(path: Path) -> str:
    # Existing FastAPI app usually mounts /storage to /opt/ai-video/storage.
    try:
        rel = path.resolve().relative_to(ROOT.resolve()).as_posix()
        return f"/storage/{rel}"
    except Exception:
        return ""


def _save_job(job_id: str, status: str, stage: str, request_json: dict[str, Any], result_json: dict[str, Any] | None = None, delegate_job_id: str = "") -> None:
    now = _now()
    with _db() as con:
        con.execute("""INSERT INTO jobs(job_id,status,stage,delegate_job_id,request_json,result_json,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(job_id) DO UPDATE SET status=excluded.status, stage=excluded.stage, delegate_job_id=excluded.delegate_job_id,
            request_json=excluded.request_json, result_json=excluded.result_json, updated_at=excluded.updated_at""",
            (job_id, status, stage, delegate_job_id, json.dumps(request_json, ensure_ascii=False), json.dumps(result_json or {}, ensure_ascii=False), now, now))


def _get_job(job_id: str) -> dict[str, Any] | None:
    with _db() as con:
        row = con.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
    item = _row_to_dict(row)
    if item:
        item["request_json"] = _json_loads(item.get("request_json"), {})
        item["result_json"] = _json_loads(item.get("result_json"), {})
    return item


async def _post_local(path: str, payload: dict[str, Any], timeout: float = 180.0) -> dict[str, Any]:
    url = "http://127.0.0.1:8000" + path
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=payload)
        text = resp.text
        try:
            data = resp.json()
        except Exception:
            data = {"raw": text}
        if resp.status_code >= 400:
            raise RuntimeError(json.dumps({"status_code": resp.status_code, "data": data}, ensure_ascii=False))
        return data


async def _get_local(path: str, timeout: float = 60.0) -> dict[str, Any]:
    url = "http://127.0.0.1:8000" + path
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(url)
        try:
            data = resp.json()
        except Exception:
            data = {"raw": resp.text}
        if resp.status_code >= 400:
            raise RuntimeError(json.dumps({"status_code": resp.status_code, "data": data}, ensure_ascii=False))
        return data


class PlanPreviewRequest(BaseModel):
    script_text: str = ""
    script: str = ""
    shots: list[Any] | None = None
    manual_shot_plan: list[Any] | None = None
    audio_duration: float = 0.0
    keywords: list[str] | str | None = None
    forbidden_words: list[str] | str | None = None


class StartRequest(BaseModel):
    topic: str = ""
    audience: str = ""
    script_text: str = ""
    script: str = ""
    keywords: list[str] | str | None = None
    forbidden_words: list[str] | str | None = None
    script_segments: list[Any] | None = None
    segment_voice_settings: list[Any] | None = None
    manual_shot_plan: list[Any] | None = None
    shot_overrides: list[Any] | None = None
    asset_context: list[Any] | None = None
    delegate_to_existing: bool = True
    require_subtitles: bool = True
    require_semantic_storyboard: bool = True
    no_flash_transition: bool = True
    duration_seconds: float = 0.0


async def api_v10_34_health():
    return {
        "ok": True,
        "version": BACKEND_VERSION,
        "storage_root": str(ROOT),
        "database": str(DB),
        "rules": {
            "V10.34A": "video generation hard rules + crossfade + metadata persistence + completed status guard",
            "V10.34B": "native step2 script/voice preview routes",
            "V10.34C": "material library with mandatory type/category/city/district/source/reusable/note fields",
            "V10.34D": "account import and DeepSeek classification with fallback rules",
            "V10.34E": "OpenClaw capture adapter; calls OPENCLAW_CAPTURE_URL when configured",
            "V10.34F": "Obsidian vault note growth",
            "V10.34G": "AI control dashboard endpoints",
        },
        "openclaw_capture_url_configured": bool(OPENCLAW_CAPTURE_URL),
        "deepseek_configured": bool(DEEPSEEK_API_KEY),
    }


async def api_v10_34_split_script(request: Request):
    data = await request.json()
    script = str(data.get("script_text") or data.get("script") or "")
    parts = _split_script(script)
    return {"ok": True, "segments": [{"index": i+1, "text": t} for i, t in enumerate(parts)], "count": len(parts)}


async def api_v10_34_plan_preview(req: PlanPreviewRequest):
    script = req.script_text or req.script or ""
    shots = _build_shot_plan(script, req.manual_shot_plan or req.shots, req.audio_duration)
    return {
        "ok": True,
        "version": BACKEND_VERSION,
        "shots": shots,
        "shot_count": len(shots),
        "duration_seconds": round(sum(float(s.get("duration_seconds") or 0) for s in shots), 2),
        "transition": SAFE_TRANSITION,
        "banned_transitions": BANNED_TRANSITIONS,
        "acceptance": _acceptance(script, shots),
        "generation_allowed": _acceptance(script, shots)["passed"],
    }


async def _delegate_existing(job_id: str, payload: dict[str, Any]):
    result: dict[str, Any]
    try:
        result = await _post_local("/api/video/full-ai/tts-first/start", payload, timeout=180)
        delegate_job_id = str(result.get("job_id") or result.get("id") or "")
        current = _get_job(job_id) or {}
        req = current.get("request_json") or payload
        _save_job(job_id, "delegated", "existing_tts_first_running", req, result, delegate_job_id=delegate_job_id)
    except Exception as exc:
        current = _get_job(job_id) or {}
        req = current.get("request_json") or payload
        _save_job(job_id, "failed_to_delegate", "existing_tts_first_start_failed", req, {"error": repr(exc)[:2000]}, "")


async def api_v10_34_start(req: StartRequest):
    script = req.script_text or req.script or ""
    shots = _build_shot_plan(script, req.manual_shot_plan or req.shot_overrides, req.duration_seconds)
    accept = _acceptance(script, shots)
    if not accept["passed"]:
        raise HTTPException(status_code=400, detail={"error":"acceptance_failed", "acceptance": accept})
    job_id = "v10_34_" + uuid.uuid4().hex[:18]
    shot_assets = _save_generated_shot_assets(job_id, shots)
    payload = {
        **req.model_dump(),
        "script_text": script,
        "shots": shots,
        "manual_shot_plan": shots,
        "shot_overrides": shots,
        "transition": SAFE_TRANSITION,
        "transition_plan": [SAFE_TRANSITION for _ in shots],
        "negative_prompt": _negative_prompt(),
        "require_semantic_storyboard": True,
        "require_subtitles": True,
        "no_flash_transition": True,
        "v10_34_rules": {
            "ban_cut": True,
            "ban_smooth_cut": True,
            "ban_flash": True,
            "ban_pull_out": True,
            "transition": SAFE_TRANSITION,
            "concat": "xfade_crossfade_only",
            "completed_status_guard": True,
            "save_raw_fal_metadata": True,
        },
        "v10_34_job_id": job_id,
    }
    _save_job(job_id, "queued", "prepared_v10_34_rules", payload, {"shot_assets": shot_assets, "acceptance": accept}, "")
    if req.delegate_to_existing:
        asyncio.create_task(_delegate_existing(job_id, payload))
    return {
        "ok": True,
        "version": BACKEND_VERSION,
        "job_id": job_id,
        "status": "queued",
        "stage": "prepared_v10_34_rules",
        "delegating_to_existing_tts_first": bool(req.delegate_to_existing),
        "shots": shots,
        "generated_shot_assets": shot_assets,
        "acceptance": accept,
        "job_url": f"/api/video/v10-34/job/{job_id}",
    }


async def api_v10_34_job(job_id: str):
    item = _get_job(job_id)
    if not item:
        raise HTTPException(status_code=404, detail="JOB_NOT_FOUND")
    result = item.get("result_json") or {}
    delegate = item.get("delegate_job_id") or ""
    delegated_result = None
    if delegate:
        try:
            delegated_result = await _get_local(f"/api/video/full-ai/tts-first/job/{delegate}", timeout=60)
            result["delegated_result"] = delegated_result
            status = str(delegated_result.get("status") or "")
            final_url = delegated_result.get("subtitled_video_url") or delegated_result.get("video_url") or delegated_result.get("final_video_url") or ""
            if status.lower() in {"completed", "complete", "success", "finished"} and not final_url:
                return {**item, "ok": True, "status": "blocked_needs_review", "completion_blocked": True, "message": "V10.34A blocked false completed: final video url missing", "result_json": result}
            if status:
                item["status"] = status
            if final_url:
                result["final_video_url"] = final_url
        except Exception as exc:
            result["delegated_poll_error"] = repr(exc)[:1000]
    return {**item, "ok": True, "result_json": result, "generated_shot_assets_url": f"/api/video/v10-34/generated-shot-assets/{job_id}"}


async def api_v10_34_generated_shot_assets(job_id: str):
    base = SHOT_ASSET_DIR / job_id
    items = []
    for p in sorted(base.glob("shot_*_meta.json")):
        try:
            items.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception as exc:
            items.append({"path": str(p), "error": str(exc)})
    return {"ok": True, "job_id": job_id, "count": len(items), "asset_dir": str(base), "items": items}


async def api_v10_34_approve_final(request: Request):
    data = await request.json()
    job_id = str(data.get("job_id") or data.get("asset_id") or "").strip()
    if not job_id:
        raise HTTPException(status_code=400, detail="job_id_required")
    base = FINAL_DIR / job_id
    base.mkdir(parents=True, exist_ok=True)
    item = {
        "ok": True,
        "asset_type": "final_video",
        "version": BACKEND_VERSION,
        "asset_id": job_id,
        "source_job_id": job_id,
        "approved_at": _now(),
        "final_video_url": data.get("final_video_url") or data.get("video_url") or data.get("subtitled_video_url") or "",
        "raw_video_url": data.get("raw_video_url") or "",
        "shot_asset_dir": str(SHOT_ASSET_DIR / job_id),
        "reuse_policy": "final_can_be_reused_for_delivery; raw_shots_can_be_reused_after_human_approval",
        "note": data.get("note") or "",
    }
    (base / "final_meta.json").write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "asset": item}


async def api_voice_preview(request: Request):
    data = await request.json()
    script = str(data.get("script_text") or data.get("script") or data.get("text") or "").strip()
    if not script:
        return JSONResponse(status_code=400, content={"ok": False, "error": "script_text_required"})
    if len(script) > 1600:
        return JSONResponse(status_code=400, content={"ok": False, "error": "script_too_long_for_preview", "max_chars": 1600})
    preview_id = "voice_preview_" + uuid.uuid4().hex[:16]
    work = VOICE_DIR / preview_id
    work.mkdir(parents=True, exist_ok=True)
    tts_payload = {"text": script, "rate": {"normal":"+0%","slightly_fast":"+8%","slow_clear":"-8%","fast":"+12%","slow":"-12%"}.get(str(data.get("pace") or "normal"), "+0%")}
    if data.get("voice") or data.get("voice_id"):
        tts_payload["voice"] = str(data.get("voice") or data.get("voice_id"))
    meta = {"ok": False, "preview_id": preview_id, "version": BACKEND_VERSION, "status":"started", "script_text": script, "voice_settings": data, "tts_payload": tts_payload, "created_at": _now()}
    try:
        res = await _post_local("/api/tts", tts_payload, timeout=240)
        audio_url = str(res.get("file_url") or res.get("audio_url") or res.get("url") or "")
        duration = float(res.get("duration_seconds") or res.get("audio_duration") or res.get("duration") or 0)
        if not audio_url:
            meta.update({"status":"failed", "error":"tts_generated_but_no_audio_url", "tts_result":res})
            (work / "voice_preview_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            return JSONResponse(status_code=502, content=meta)
        meta.update({"ok": True, "status":"completed", "provider":"local_api_tts", "audio_url": audio_url, "audio_duration": duration, "tts_result": res})
        (work / "voice_preview_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return meta
    except Exception as exc:
        meta.update({"status":"failed", "error":"local_api_tts_failed", "detail":repr(exc)[:1200]})
        (work / "voice_preview_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return JSONResponse(status_code=502, content=meta)


async def api_script_version(request: Request):
    data = await request.json()
    script = str(data.get("script_text") or data.get("script") or "").strip()
    if not script:
        return JSONResponse(status_code=400, content={"ok": False, "error":"script_text_required"})
    version_id = "script_v_" + uuid.uuid4().hex[:16]
    item = {"ok": True, "version": BACKEND_VERSION, "version_id": version_id, "created_at": _now(), "script_text": script, "keywords": _split_words(data.get("keywords")), "forbidden_words": _split_words(data.get("forbidden_words")), "voice": data.get("voice") or {}, "note": data.get("note") or ""}
    (SCRIPT_DIR / f"{version_id}.json").write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")
    with _db() as con:
        con.execute("INSERT INTO script_versions(version_id,script_text,keywords,forbidden_words,voice_json,note,created_at) VALUES(?,?,?,?,?,?,?)", (version_id, script, json.dumps(item["keywords"], ensure_ascii=False), json.dumps(item["forbidden_words"], ensure_ascii=False), json.dumps(item["voice"], ensure_ascii=False), item["note"], item["created_at"]))
    return item


async def api_material_categories():
    return {"ok": True, "items": CATEGORY_DEFS, "required_upload_fields": ["file", "kind", "category", "city", "district", "source", "reusable", "note"]}


async def api_material_list(category: str = "", kind: str = "", city: str = "", reusable: Optional[int] = None, q: str = "", limit: int = 200):
    sql = "SELECT * FROM materials WHERE 1=1"
    args: list[Any] = []
    for col, val in [("category", category), ("kind", kind), ("city", city)]:
        if val:
            sql += f" AND {col}=?"; args.append(val)
    if reusable is not None:
        sql += " AND reusable=?"; args.append(int(reusable))
    if q:
        sql += " AND (original_name LIKE ? OR tags LIKE ? OR note LIKE ?)"; args += [f"%{q}%"]*3
    sql += " ORDER BY created_at DESC LIMIT ?"; args.append(max(1, min(int(limit), 1000)))
    with _db() as con:
        rows = con.execute(sql, args).fetchall()
    items = []
    for r in rows:
        d = _row_to_dict(r) or {}
        d["tags"] = _json_loads(d.get("tags"), [])
        items.append(d)
    return {"ok": True, "count": len(items), "items": items}


async def api_material_upload(
    file: UploadFile = File(...),
    kind: str = Form(...),
    category: str = Form(...),
    city: str = Form(""),
    district: str = Form(""),
    source: str = Form(""),
    reusable: bool = Form(True),
    tags: str = Form(""),
    note: str = Form(""),
):
    missing = [name for name, val in [("kind", kind), ("category", category)] if not str(val or "").strip()]
    if missing:
        raise HTTPException(status_code=400, detail={"error":"missing_required_upload_fields", "fields": missing})
    asset_id = "mat_" + uuid.uuid4().hex[:18]
    safe = _safe_name(file.filename or asset_id)
    sub = MATERIAL_DIR / category / asset_id
    sub.mkdir(parents=True, exist_ok=True)
    dst = sub / safe
    with open(dst, "wb") as f:
        shutil.copyfileobj(file.file, f)
    now = _now()
    item = {
        "asset_id": asset_id, "filename": safe, "original_name": file.filename or safe, "kind": kind, "category": category,
        "city": city, "district": district, "source": source, "reusable": 1 if reusable else 0, "tags": _split_words(tags), "note": note,
        "mime_type": file.content_type or "", "size_bytes": dst.stat().st_size, "file_path": str(dst), "file_url": _public_file_url(dst),
        "created_at": now, "updated_at": now,
    }
    with _db() as con:
        con.execute("""INSERT INTO materials(asset_id,filename,original_name,kind,category,city,district,source,reusable,tags,note,mime_type,size_bytes,file_path,file_url,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (item["asset_id"], item["filename"], item["original_name"], item["kind"], item["category"], item["city"], item["district"], item["source"], item["reusable"], json.dumps(item["tags"], ensure_ascii=False), item["note"], item["mime_type"], item["size_bytes"], item["file_path"], item["file_url"], now, now))
    return {"ok": True, "item": item}


async def api_material_update(asset_id: str, request: Request):
    data = await request.json()
    allowed = ["kind","category","city","district","source","reusable","tags","note"]
    sets = []
    args = []
    for k in allowed:
        if k in data:
            sets.append(f"{k}=?")
            v = data[k]
            if k == "tags": v = json.dumps(_split_words(v), ensure_ascii=False)
            if k == "reusable": v = int(bool(v))
            args.append(v)
    if not sets:
        return {"ok": True, "updated": False}
    sets.append("updated_at=?"); args.append(_now()); args.append(asset_id)
    with _db() as con:
        cur = con.execute(f"UPDATE materials SET {', '.join(sets)} WHERE asset_id=?", args)
    return {"ok": True, "updated": cur.rowcount > 0, "asset_id": asset_id}


async def _classify_account(item: dict[str, Any]) -> dict[str, Any]:
    text = " ".join(str(item.get(k) or "") for k in ["name","handle","url","bio","description","industry","platform"])
    cat = _classify_scene(text)
    follower = int(float(item.get("follower_count") or item.get("followers") or 0)) if str(item.get("follower_count") or item.get("followers") or "0").replace('.','',1).isdigit() else 0
    value = "high" if follower >= 50000 else "medium" if follower >= 5000 else "seed"
    result = {"category": cat["category"], "category_id": cat["scene_type"], "value_level": value, "reason": "rule_fallback"}
    if DEEPSEEK_API_KEY:
        try:
            prompt = "请把账号按短视频素材/竞品价值分类，输出JSON：category,value_level,tags,reason。账号=" + json.dumps(item, ensure_ascii=False)[:3000]
            async with httpx.AsyncClient(timeout=45) as client:
                resp = await client.post(DEEPSEEK_BASE_URL + "/v1/chat/completions", headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type":"application/json"}, json={"model":DEEPSEEK_MODEL, "messages":[{"role":"user","content":prompt}], "temperature":0.2})
                if resp.status_code < 400:
                    content = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
                    m = re.search(r"\{.*\}", content, re.S)
                    if m:
                        result.update(json.loads(m.group(0)))
                        result["reason"] = result.get("reason") or "deepseek"
        except Exception as exc:
            result["deepseek_error"] = repr(exc)[:300]
    return result


async def api_accounts_import(request: Request):
    data = await request.json()
    rows = data.get("accounts") or data.get("items") or []
    if isinstance(rows, str):
        # accept csv text
        lines = rows.splitlines()
        rows = list(csv.DictReader(lines)) if lines and "," in lines[0] else [{"url": x.strip()} for x in lines if x.strip()]
    if not isinstance(rows, list):
        raise HTTPException(status_code=400, detail="accounts_must_be_list_or_csv_text")
    saved = []
    for raw in rows:
        item = raw if isinstance(raw, dict) else {"url": str(raw)}
        cls = await _classify_account(item)
        account_id = "acct_" + hashlib.sha1(json.dumps(item, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:18]
        now = _now()
        record = {
            "account_id": account_id,
            "platform": str(item.get("platform") or ""), "handle": str(item.get("handle") or item.get("username") or ""), "name": str(item.get("name") or ""), "url": str(item.get("url") or ""),
            "city": str(item.get("city") or ""), "industry": str(item.get("industry") or ""), "follower_count": int(float(item.get("follower_count") or item.get("followers") or 0) if str(item.get("follower_count") or item.get("followers") or "0").replace('.','',1).isdigit() else 0),
            "category": str(cls.get("category") or ""), "value_level": str(cls.get("value_level") or ""), "tags": _split_words(cls.get("tags") or item.get("tags") or []), "raw_json": item, "classification_json": cls,
            "created_at": now, "updated_at": now,
        }
        with _db() as con:
            con.execute("""INSERT INTO accounts(account_id,platform,handle,name,url,city,industry,follower_count,category,value_level,tags,raw_json,classification_json,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(account_id) DO UPDATE SET category=excluded.category,value_level=excluded.value_level,tags=excluded.tags,classification_json=excluded.classification_json,updated_at=excluded.updated_at""",
            (record["account_id"],record["platform"],record["handle"],record["name"],record["url"],record["city"],record["industry"],record["follower_count"],record["category"],record["value_level"],json.dumps(record["tags"],ensure_ascii=False),json.dumps(record["raw_json"],ensure_ascii=False),json.dumps(record["classification_json"],ensure_ascii=False),now,now))
        saved.append(record)
    return {"ok": True, "count": len(saved), "items": saved}


async def api_accounts_list(platform: str = "", category: str = "", limit: int = 200):
    sql = "SELECT * FROM accounts WHERE 1=1"; args=[]
    if platform: sql += " AND platform=?"; args.append(platform)
    if category: sql += " AND category=?"; args.append(category)
    sql += " ORDER BY updated_at DESC LIMIT ?"; args.append(max(1,min(int(limit),1000)))
    with _db() as con:
        rows = con.execute(sql,args).fetchall()
    items=[]
    for r in rows:
        d=_row_to_dict(r) or {}; d["tags"]=_json_loads(d.get("tags"),[]); d["raw_json"]=_json_loads(d.get("raw_json"),{}); d["classification_json"]=_json_loads(d.get("classification_json"),{}); items.append(d)
    return {"ok": True, "count":len(items), "items":items}


async def api_accounts_classify(request: Request):
    data = await request.json()
    return {"ok": True, "classification": await _classify_account(data)}


async def api_openclaw_capture(request: Request):
    data = await request.json()
    task_id = "oc_" + uuid.uuid4().hex[:16]
    now = _now()
    result: dict[str, Any] = {"mode":"saved_task", "message":"OPENCLAW_CAPTURE_URL not configured; task stored for OpenClaw agent pickup"}
    status = "waiting_for_openclaw_agent"
    if OPENCLAW_CAPTURE_URL:
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(OPENCLAW_CAPTURE_URL, json={"task_id":task_id, **data})
                result = resp.json() if resp.headers.get("content-type","").startswith("application/json") else {"raw": resp.text}
                status = "completed" if resp.status_code < 400 else "openclaw_error"
        except Exception as exc:
            result = {"error": repr(exc)[:1200]}; status = "openclaw_request_failed"
    with _db() as con:
        con.execute("INSERT INTO openclaw_tasks(task_id,mode,status,target_url,request_json,result_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)", (task_id, str(data.get("mode") or "capture"), status, str(data.get("url") or data.get("target_url") or ""), json.dumps(data,ensure_ascii=False), json.dumps(result,ensure_ascii=False), now, now))
    return {"ok": status not in {"openclaw_error","openclaw_request_failed"}, "task_id": task_id, "status": status, "result": result}


async def api_openclaw_tasks(limit: int = 100):
    with _db() as con:
        rows=con.execute("SELECT * FROM openclaw_tasks ORDER BY created_at DESC LIMIT ?", (max(1,min(int(limit),500)),)).fetchall()
    items=[]
    for r in rows:
        d=_row_to_dict(r) or {}; d["request_json"]=_json_loads(d.get("request_json"),{}); d["result_json"]=_json_loads(d.get("result_json"),{}); items.append(d)
    return {"ok": True, "count":len(items), "items":items}


async def api_obsidian_note(request: Request):
    data = await request.json()
    title = _safe_name(str(data.get("title") or data.get("topic") or f"note_{uuid.uuid4().hex[:8]}"))
    category = str(data.get("category") or "AI-VIDEO")
    tags = _split_words(data.get("tags") or ["ai-video","v10.34"])
    content = str(data.get("content") or data.get("summary") or "")
    note_id = "note_" + uuid.uuid4().hex[:16]
    folder = OBSIDIAN_DIR / category
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{title}.md"
    body = "---\n" + "\n".join([f"note_id: {note_id}", f"created_at: {_now()}", "tags: [" + ", ".join(tags) + "]", f"source: {BACKEND_VERSION}"]) + "\n---\n\n" + f"# {title}\n\n" + content.strip() + "\n"
    path.write_text(body, encoding="utf-8")
    now=_now()
    with _db() as con:
        con.execute("INSERT INTO obsidian_notes(note_id,title,path,category,tags,summary,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)", (note_id,title,str(path),category,json.dumps(tags,ensure_ascii=False),content[:500],now,now))
    return {"ok": True, "note_id": note_id, "path": str(path), "title": title}


async def api_obsidian_graph(limit: int = 200):
    with _db() as con:
        rows=con.execute("SELECT * FROM obsidian_notes ORDER BY created_at DESC LIMIT ?", (max(1,min(int(limit),1000)),)).fetchall()
    notes=[]
    for r in rows:
        d=_row_to_dict(r) or {}; d["tags"]=_json_loads(d.get("tags"),[]); notes.append(d)
    return {"ok": True, "vault": str(OBSIDIAN_DIR), "count":len(notes), "notes":notes}


async def api_ai_control_brief():
    mats = await api_material_list(limit=20)
    accts = await api_accounts_list(limit=20)
    openclaw = await api_openclaw_tasks(limit=10)
    obs = await api_obsidian_graph(limit=20)
    return {"ok": True, "version": BACKEND_VERSION, "summary": {"materials": mats["count"], "accounts": accts["count"], "openclaw_tasks": openclaw["count"], "obsidian_notes": obs["count"]}, "next_actions": ["补齐素材库城市/区域/来源字段", "导入账号库并分类", "用 OpenClaw 采集竞品内容", "把高价值内容沉淀到 Obsidian", "生成前先跑 V10.34 plan-preview 验收"]}


async def api_ai_control_action(request: Request):
    data = await request.json()
    action = str(data.get("action") or "").strip()
    event_id = "ai_evt_" + uuid.uuid4().hex[:16]
    output: dict[str, Any]
    status = "completed"
    if action == "plan-preview":
        output = await api_v10_34_plan_preview(PlanPreviewRequest(**(data.get("payload") or data)))
    elif action == "openclaw-capture":
        output = await api_openclaw_capture(request)
    elif action == "obsidian-note":
        output = await api_obsidian_note(request)
    else:
        output = {"message":"action stored", "supported_actions":["plan-preview","openclaw-capture","obsidian-note"]}
        status = "stored"
    with _db() as con:
        con.execute("INSERT INTO ai_control_events(event_id,action,status,input_json,output_json,created_at) VALUES(?,?,?,?,?,?)", (event_id,action,status,json.dumps(data,ensure_ascii=False),json.dumps(output,ensure_ascii=False),_now()))
    return {"ok": True, "event_id": event_id, "status": status, "output": output}


def install_v10_34_complete(app: FastAPI) -> None:
    remove_paths = {
        "/api/video/v10-34/health",
        "/api/video/v10-34/script/split",
        "/api/video/v10-34/plan-preview",
        "/api/video/v10-34/start",
        "/api/video/v10-34/job/{job_id}",
        "/api/video/v10-34/generated-shot-assets/{job_id}",
        "/api/video/v10-34/approve-final",
        "/api/video/full-ai/tts-first/voice-preview",
        "/api/video/full-ai/tts-first/script-version",
        "/api/video/material-library/categories",
        "/api/video/material-library",
        "/api/video/material-library/upload",
        "/api/video/material-library/{asset_id}",
        "/api/video/accounts/import",
        "/api/video/accounts",
        "/api/video/accounts/classify",
        "/api/openclaw/capture",
        "/api/openclaw/tasks",
        "/api/obsidian/note",
        "/api/obsidian/graph",
        "/api/ai-control/brief",
        "/api/ai-control/action",
    }
    app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", "") not in remove_paths]
    app.add_api_route("/api/video/v10-34/health", api_v10_34_health, methods=["GET"])
    app.add_api_route("/api/video/v10-34/script/split", api_v10_34_split_script, methods=["POST"])
    app.add_api_route("/api/video/v10-34/plan-preview", api_v10_34_plan_preview, methods=["POST"])
    app.add_api_route("/api/video/v10-34/start", api_v10_34_start, methods=["POST"])
    app.add_api_route("/api/video/v10-34/job/{job_id}", api_v10_34_job, methods=["GET"])
    app.add_api_route("/api/video/v10-34/generated-shot-assets/{job_id}", api_v10_34_generated_shot_assets, methods=["GET"])
    app.add_api_route("/api/video/v10-34/approve-final", api_v10_34_approve_final, methods=["POST"])
    app.add_api_route("/api/video/full-ai/tts-first/voice-preview", api_voice_preview, methods=["POST"])
    app.add_api_route("/api/video/full-ai/tts-first/script-version", api_script_version, methods=["POST"])
    app.add_api_route("/api/video/material-library/categories", api_material_categories, methods=["GET"])
    app.add_api_route("/api/video/material-library", api_material_list, methods=["GET"])
    app.add_api_route("/api/video/material-library/upload", api_material_upload, methods=["POST"])
    app.add_api_route("/api/video/material-library/{asset_id}", api_material_update, methods=["PATCH"])
    app.add_api_route("/api/video/accounts/import", api_accounts_import, methods=["POST"])
    app.add_api_route("/api/video/accounts", api_accounts_list, methods=["GET"])
    app.add_api_route("/api/video/accounts/classify", api_accounts_classify, methods=["POST"])
    app.add_api_route("/api/openclaw/capture", api_openclaw_capture, methods=["POST"])
    app.add_api_route("/api/openclaw/tasks", api_openclaw_tasks, methods=["GET"])
    app.add_api_route("/api/obsidian/note", api_obsidian_note, methods=["POST"])
    app.add_api_route("/api/obsidian/graph", api_obsidian_graph, methods=["GET"])
    app.add_api_route("/api/ai-control/brief", api_ai_control_brief, methods=["GET"])
    app.add_api_route("/api/ai-control/action", api_ai_control_action, methods=["POST"])
    print("V10_34_A_TO_G_COMPLETE_INSTALLED", BACKEND_VERSION, flush=True)
