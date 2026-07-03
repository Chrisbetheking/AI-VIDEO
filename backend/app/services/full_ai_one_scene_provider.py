from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib import request as urlrequest
from urllib.parse import urlparse

import requests
from fastapi import APIRouter, FastAPI
from pydantic import BaseModel, ConfigDict

from app.services.subtitle_style_library_provider import burn_subtitles_with_style_and_upload
from app.services.subtitle_provider import upload_file_to_r2, get_media_duration_seconds

try:
    from app.services.job_persistence_provider import save_job_response
except Exception:  # pragma: no cover
    save_job_response = None

router = APIRouter(prefix="/api/video/full-ai/one-scene", tags=["full-ai-one-scene"])
_jobs: Dict[str, Dict[str, Any]] = {}

BASE_DIR = Path(os.getenv("AI_VIDEO_BACKEND_DIR", "/opt/ai-video/backend"))
WORK_DIR = BASE_DIR / "data" / "one-scene-video"

class StartReq(BaseModel):
    model_config = ConfigDict(extra="allow")
    title: str = "马来西亚买房，别只看价格"
    topic: str = ""
    script_text: str = ""
    target_duration_seconds: float = 20
    duration_seconds: Optional[float] = None
    city: str = ""
    voice: str = "default"
    burn_subtitles: bool = True
    subtitle_style_id: str = "douyin_pop"
    background_scene: str = ""
    visual_mode: str = "single_scene_dynamic"
    dynamic_shot_count: int = 4


def _ensure() -> None:
    WORK_DIR.mkdir(parents=True, exist_ok=True)


def _persist(job_id: str) -> None:
    if not save_job_response:
        return
    try:
        job = dict(_jobs.get(job_id) or {})
        if job:
            save_job_response(job_id, "one_scene", job, source_path="/api/video/full-ai/one-scene")
    except Exception as exc:
        print("ONE_SCENE_PERSIST_FAILED", exc, flush=True)


def _headers() -> Dict[str, str]:
    h = {"Content-Type": "application/json"}
    try:
        token = Path("/root/ai-video-admin-token.txt").read_text(encoding="utf-8").strip()
        if token:
            h["X-AI-Video-Token"] = token
    except Exception:
        pass
    return h


def _post_json(url: str, payload: Dict[str, Any], timeout: int = 180) -> Dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urlrequest.Request(url, data=body, headers=_headers(), method="POST")
    with urlrequest.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw or "{}")


def _get_json(url: str, timeout: int = 60) -> Dict[str, Any]:
    req = urlrequest.Request(url, headers=_headers(), method="GET")
    with urlrequest.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw or "{}")


def _first_value(obj: Any, keys: List[str]) -> Optional[Any]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            lk = str(k).lower()
            if any(x in lk for x in keys):
                return v
        for v in obj.values():
            got = _first_value(v, keys)
            if got is not None:
                return got
    elif isinstance(obj, list):
        for v in obj:
            got = _first_value(v, keys)
            if got is not None:
                return got
    return None



def _deep_get_string(obj: Any, key_pred) -> Optional[str]:
    """Find a string URL/path by key. Never return duration numbers as audio paths."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            lk = str(k).lower()
            if key_pred(lk) and isinstance(v, str) and v.strip():
                return v.strip()
        for v in obj.values():
            got = _deep_get_string(v, key_pred)
            if got:
                return got
    elif isinstance(obj, list):
        for v in obj:
            got = _deep_get_string(v, key_pred)
            if got:
                return got
    return None


def _looks_like_audio_ref(value: str) -> bool:
    v = str(value or "").strip()
    if not v:
        return False
    low = v.lower().split("?")[0]
    return v.startswith("http://") or v.startswith("https://") or v.startswith("/") or low.endswith((".mp3", ".wav", ".m4a", ".aac", ".ogg"))


def _extract_audio_url(tts_res: Dict[str, Any]) -> str:
    # Exact audio-url style keys first. Avoid matching audio_duration_seconds.
    def exact_audio_key(k: str) -> bool:
        return k in {
            "audio_url", "audiofile_url", "audio_file_url", "audio", "url", "output_url",
            "result_url", "file_url", "mp3_url", "wav_url", "audio_path", "path",
            "local_path", "public_url", "r2_url",
        }
    got = _deep_get_string(tts_res, exact_audio_key)
    if got and _looks_like_audio_ref(got):
        return got

    # Fallback: any key that clearly describes an audio/mp3/wav file URL/path, not duration.
    def fuzzy_audio_key(k: str) -> bool:
        if "duration" in k or "seconds" in k or "time" in k or "length" in k:
            return False
        return ("audio" in k or "mp3" in k or "wav" in k or "m4a" in k or "aac" in k) and ("url" in k or "path" in k or "file" in k)
    got = _deep_get_string(tts_res, fuzzy_audio_key)
    if got and _looks_like_audio_ref(got):
        return got
    return ""


def _extract_duration(tts_res: Dict[str, Any], fallback: float) -> float:
    names = ["audio_duration_seconds", "duration_seconds", "duration", "total_duration", "audio_duration", "length_seconds"]
    def walk(obj: Any) -> Optional[float]:
        if isinstance(obj, dict):
            for k, v in obj.items():
                if str(k).lower() in names:
                    try:
                        return float(v)
                    except Exception:
                        pass
            for v in obj.values():
                got = walk(v)
                if got is not None:
                    return got
        elif isinstance(obj, list):
            # Sum per-segment durations when no total exists.
            vals = []
            for item in obj:
                if isinstance(item, dict):
                    for key in ("duration_seconds", "duration"):
                        try:
                            if key in item:
                                vals.append(float(item[key]))
                        except Exception:
                            pass
            if vals:
                return sum(vals)
            for v in obj:
                got = walk(v)
                if got is not None:
                    return got
        return None
    got = walk(tts_res)
    try:
        return max(float(got if got is not None else fallback), 1.0)
    except Exception:
        return max(float(fallback), 1.0)


def _video_url(data: Dict[str, Any]) -> str:
    for k in ("video_url", "url", "output_url", "result_url"):
        v = data.get(k)
        if isinstance(v, str) and v:
            return v
    r = data.get("result") if isinstance(data.get("result"), dict) else {}
    for k in ("video_url", "url", "output_url", "result_url"):
        v = r.get(k)
        if isinstance(v, str) and v:
            return v
    return ""


def _done(data: Dict[str, Any]) -> bool:
    t = f"{data.get('status','')} {data.get('stage','')}".lower()
    return any(x in t for x in ["done", "completed", "success", "succeeded", "finished"])


def _failed(data: Dict[str, Any]) -> bool:
    t = f"{data.get('status','')} {data.get('stage','')} {data.get('error','')}".lower()
    return any(x in t for x in ["failed", "error"])


def _download(url: str, suffix: str = "") -> Path:
    _ensure()
    parsed = urlparse(url)
    ext = suffix or Path(parsed.path).suffix or ".bin"
    path = WORK_DIR / f"dl_{uuid.uuid4().hex[:12]}{ext}"
    with requests.get(url, stream=True, timeout=240) as resp:
        resp.raise_for_status()
        with path.open("wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
    return path


def _duration(raw: Dict[str, Any]) -> float:
    v = raw.get("duration_seconds") or raw.get("target_duration_seconds") or raw.get("targetSeconds") or 20
    try:
        return max(8.0, min(float(v), 60.0))
    except Exception:
        return 20.0


def _clean_script(title: str, script: str, seconds: float) -> str:
    script = re.sub(r"\s+", " ", str(script or "").strip())
    title = re.sub(r"\s+", " ", str(title or "马来西亚买房，别只看价格").strip())
    dirty = ["评论区答疑模板", "数字人模板", "OpenClaw", "内容大脑", "R2素材自动标签", "类型：", "模式：", "用途："]
    for d in dirty:
        script = script.replace(d, "")
    script = re.sub(r"\b\d{1,3}\.?\b", "", script)
    if not script:
        script = f"{title}。很多人买房第一眼只看价格，但真正要先看区域、用途和流动性。自住要看生活半径和社区品质，投资要看租客来源和未来转手。先判断需求，再看项目。"
    max_chars = int(seconds * 4.5)
    min_chars = int(seconds * 3.2)
    while len(script) < min_chars:
        script += " 先判断真实需求，再看区域成熟度、出租需求和生活便利。"
    if len(script) > max_chars:
        script = script[:max_chars].rstrip("，。,. ") + "。"
    return script


def _tts(script: str, voice: str) -> tuple[float, str, Dict[str, Any]]:
    fallback = max(6.0, len(script) / 4.6)
    payloads = [
        {"text": script, "voice": voice},
        {"script_text": script, "voice": voice},
        {"segments": [{"text": script}], "voice": voice},
    ]
    last: Dict[str, Any] = {}
    for p in payloads:
        try:
            res = _post_json("http://127.0.0.1:8000/api/tts-segments", p, timeout=240)
            last = res
            dur_f = _extract_duration(res, fallback=fallback)
            audio_url = _extract_audio_url(res)
            # V10.14: fail early with useful diagnostics instead of treating audio_duration as a file path.
            if not audio_url:
                res_keys = list(res.keys()) if isinstance(res, dict) else []
                raise RuntimeError(f"TTS finished but no downloadable audio_url/path was found; top_keys={res_keys}")
            return max(dur_f, 1.0), audio_url, res
        except Exception as exc:
            last = {"ok": False, "error": str(exc)}
    return fallback, "", last


def _clean_subtitle_text(text: str) -> str:
    value = re.sub(r"\s+", "", _to_cn_digits(str(text or "")).strip())
    # 字幕只保留纯文字，去掉标点并把阿拉伯数字转成中文数字。
    value = re.sub(r"[，。！？、；：,.!?;:\"'“”‘’（）()【】\[\]《》<>\/\\|·•…—_-]+", "", value)
    return value.strip()


def _clean_keyword(value: str) -> str:
    v = _clean_subtitle_text(value)
    bad = ["评论区答疑模板", "数字人模板", "OpenClaw", "内容大脑", "R2素材", "类型", "模式", "用途", "模板", "规则", "字幕库", "素材库"]
    if any(b.lower() in v.lower() for b in bad):
        return ""
    if re.fullmatch(r"\d{1,3}", v):
        return ""
    if len(v) < 2 or len(v) > 10:
        return ""
    return v


def _extract_highlight_keywords(raw: Dict[str, Any], title: str, script: str) -> List[str]:
    values: List[str] = []
    def add(x: Any):
        if isinstance(x, str):
            values.extend(re.split(r"[,，、\s]+", x))
        elif isinstance(x, dict):
            for k in ("value", "keyword", "text", "label", "name", "term"):
                if x.get(k):
                    add(str(x.get(k)))
        elif isinstance(x, list):
            for item in x:
                add(item)
    for key in ("keyword_insights", "ai_keyword_insights", "keywords", "manualKeywords", "manual_keywords"):
        add(raw.get(key))
    add(title)
    # 房产口播常用高亮词，确保字幕里重点词能变色变大。
    values.extend(["吉隆坡", "马来西亚", "买房", "价格", "预算", "区域", "自住", "投资", "出租", "租金", "通勤", "转手", "流动性", "生活半径", "社区品质", "MontKiara", "TRX"])
    seen = set()
    out: List[str] = []
    for v in values:
        clean = _clean_keyword(str(v))
        if clean and clean.lower() not in seen:
            seen.add(clean.lower())
            out.append(clean)
    # 长词优先，避免“吉隆坡”被“吉”之类误切。
    return sorted(out[:24], key=len, reverse=True)


BANNED_VISUAL_NEGATIVE = (
    "office desk, desk, paperwork, papers, document, documents, floorplan, floor plan, blueprint, brochure, booklet, contract, "
    "calculator, pen, pencil, hand, hands, fingers, person, people, human, meeting, consultant, agent at desk, business meeting, "
    "chart, graph, tablet UI, computer screen, laptop, phone screen, readable text, fake text, labels, logo, watermark, "
    "collage, split screen, grid, multi panel, storyboard, poster, magazine layout, slideshow, picture in picture, black border, white border, "
    "Petronas Twin Towers, KLCC, landmark towers, beach, ocean, island"
)

# Words that must NEVER appear in the positive prompt. They may exist only in negative_prompt.
BANNED_POSITIVE_TOKENS = [
    "office", "desk", "paper", "papers", "document", "documents", "floorplan", "floor plan", "blueprint", "brochure", "contract",
    "calculator", "pen", "pencil", "hand", "hands", "finger", "fingers", "person", "people", "human", "meeting", "consultant",
    "chart", "graph", "tablet", "computer", "laptop", "phone screen", "readable text", "fake text", "text overlay", "logo", "watermark",
    "collage", "split screen", "grid", "multi panel", "storyboard", "poster", "slideshow", "picture in picture", "petronas", "klcc", "beach", "ocean",
    "no ", "without ", "avoid ", "禁止", "不要", "不能", "无纸", "没有人", "无手",
]

REQUIRED_VISUAL_TERMS = [
    "condominium apartment interior", "furnished", "living room", "sofa", "tv feature wall", "floor-to-ceiling windows", "kitchen", "bedroom",
]

VISUAL_CONTRACT = (
    "AI_VIDEO_V10_18_VISUAL_CONTRACT: generate ONLY wide room-level furnished Kuala Lumpur condominium apartment interior walkthrough footage. "
    "The frame is dominated by apartment architecture and furniture: sofa, TV feature wall, curtains, wooden floor, balcony glass, kitchen cabinets, bed and wardrobe. "
    "Standing eye-level wide-angle gimbal camera movement. Full-screen vertical 9:16 realistic property viewing video."
)

FALLBACK_PROMPTS = [
    (
        "vertical 9:16 realistic smartphone property viewing video, AI_VIDEO_V10_18_VISUAL_CONTRACT, "
        "wide room-level shot inside a clean modern furnished Kuala Lumpur high-rise condominium apartment interior, "
        "living room with sofa, rug, TV feature wall, curtains, wooden floor, ceiling lights and floor-to-ceiling windows, "
        "standing eye-level gimbal camera, slow forward walkthrough from doorway into the living room, premium natural daylight, full-screen architectural footage"
    ),
    (
        "vertical 9:16 realistic smartphone property viewing video, AI_VIDEO_V10_18_VISUAL_CONTRACT, "
        "wide room-level shot from living room toward balcony glass inside a clean furnished Kuala Lumpur condominium apartment interior, "
        "sofa, curtains, balcony sliding door, residential city view through floor-to-ceiling windows, wooden floor and warm daylight, "
        "standing eye-level gimbal camera, slow left-to-right pan across the apartment space, full-screen architectural footage"
    ),
    (
        "vertical 9:16 realistic smartphone property viewing video, AI_VIDEO_V10_18_VISUAL_CONTRACT, "
        "wide room-level shot of open kitchen and dining corner connected to living room inside a clean modern furnished Kuala Lumpur condominium apartment interior, "
        "kitchen cabinets, countertop, dining chairs, sofa edge, TV wall and window light visible in one continuous home layout, "
        "standing eye-level gimbal camera, slow smooth dolly movement, full-screen architectural footage"
    ),
    (
        "vertical 9:16 realistic smartphone property viewing video, AI_VIDEO_V10_18_VISUAL_CONTRACT, "
        "wide room-level shot inside a clean staged master bedroom of a Kuala Lumpur condominium apartment interior, "
        "bed, wardrobe, curtains, bedside lights, wooden floor and soft natural window light, "
        "standing eye-level gimbal camera, slow gentle move from doorway into the bedroom, full-screen architectural footage"
    ),
]


def _has_banned_positive(prompt: str) -> bool:
    low = str(prompt or "").lower()
    return any(tok in low for tok in BANNED_POSITIVE_TOKENS)


def _normalize_visual_prompt(prompt: str) -> str:
    p = re.sub(r"\s+", " ", str(prompt or "").strip())
    # Remove accidental negative language from positive prompt. A video model can latch onto the object even after "no".
    p = re.sub(r"(?i)\b(no|without|avoid)\s+[^,.，。;；]{1,80}[,.，。;；]?", " ", p)
    p = re.sub(r"\s+", " ", p).strip(" ,，.;；")
    return p


def _validate_visual_prompt(prompt: str) -> tuple[bool, str]:
    p = _normalize_visual_prompt(prompt)
    if len(p) < 90:
        return False, "too_short"
    if _has_banned_positive(p):
        return False, "banned_token_in_positive_prompt"
    low = p.lower()
    must = ["vertical 9:16", "condominium apartment interior", "wide", "room", "living", "sofa", "window"]
    missing = [x for x in must if x not in low]
    if len(missing) >= 3:
        return False, "missing_core_interior_terms:" + ",".join(missing)
    return True, "ok"


def _extract_json_object(text: str) -> Dict[str, Any]:
    raw = str(text or "").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I | re.S).strip()
    try:
        return json.loads(raw)
    except Exception:
        pass
    m = re.search(r"\{.*\}", raw, flags=re.S)
    if m:
        return json.loads(m.group(0))
    raise ValueError("DeepSeek did not return JSON")


def _deepseek_chat(messages: List[Dict[str, str]], timeout: int = 45) -> Dict[str, Any]:
    api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("AI_VIDEO_DEEPSEEK_API_KEY")
    base_url = (os.getenv("DEEPSEEK_BASE_URL") or os.getenv("AI_VIDEO_DEEPSEEK_BASE_URL") or "https://api.deepseek.com").rstrip("/")
    model = os.getenv("DEEPSEEK_MODEL") or os.getenv("AI_VIDEO_DEEPSEEK_MODEL") or "deepseek-chat"
    if not api_key:
        return {"ok": False, "error": "DEEPSEEK_API_KEY not configured"}
    try:
        resp = requests.post(
            f"{base_url}/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "messages": messages, "temperature": 0.2, "response_format": {"type": "json_object"}},
            timeout=timeout,
        )
        if resp.status_code >= 400:
            return {"ok": False, "error": f"DeepSeek HTTP {resp.status_code}: {resp.text[:500]}"}
        data = resp.json()
        content = (((data.get("choices") or [{}])[0]).get("message") or {}).get("content") or ""
        parsed = _extract_json_object(content)
        parsed["ok"] = True
        parsed["model"] = model
        return parsed
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _build_visual_planner_prompt(city: str, topic: str, count: int) -> List[Dict[str, str]]:
    forbidden = ", ".join(BANNED_POSITIVE_TOKENS[:36])
    system = (
        "You are a strict visual prompt planner for AI real estate short videos. "
        "Return ONLY valid JSON. You do not generate marketing copy. You only generate visual prompts."
    )
    user = f"""
Generate {count} positive English prompts for fal.ai text-to-video.
Business goal: Malaysia / Kuala Lumpur real estate short video.
Topic: {topic or 'Kuala Lumpur condo viewing'}
City: {city or 'Kuala Lumpur'}

ABSOLUTE VISUAL RULES:
1. Positive prompts must describe ONLY wide room-level furnished condominium apartment interior walkthrough footage.
2. Required visual content: living room, sofa, TV feature wall, floor-to-ceiling windows, balcony glass, kitchen cabinets, bedroom, wardrobe, natural daylight.
3. Camera: vertical 9:16 smartphone video, standing eye-level, wide-angle, smooth gimbal, slow push or pan.
4. Same apartment / same style / coherent property tour across all prompts.
5. Do NOT include any text overlay, labels, signs, logo, watermark, floorplan, calculator, papers, hands, people, office desk, documents, brochure, chart, laptop, phone, meeting, consultant, KLCC, Petronas, beach.
6. CRITICAL: Do not put negative phrases such as "no papers" or "without people" inside the positive prompt. Just describe the desired apartment interior.
7. Do not use the words: {forbidden}

Return JSON exactly in this schema:
{{
  "visual_contract": "one sentence summary",
  "shots": [
    {{"name":"living room push", "prompt":"..."}},
    {{"name":"balcony window pan", "prompt":"..."}},
    {{"name":"kitchen dining move", "prompt":"..."}}
  ],
  "negative_prompt": "comma separated forbidden objects"
}}
""".strip()
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _repair_prompt_with_contract(prompt: str, fallback: str) -> str:
    p = _normalize_visual_prompt(prompt)
    ok, _ = _validate_visual_prompt(p)
    if ok:
        return p
    return fallback


def _deepseek_scene_prompts(city: str, topic: str, requested_count: int = 3) -> Dict[str, Any]:
    count = max(3, min(int(requested_count or 3), 4))
    planner = _deepseek_chat(_build_visual_planner_prompt(city, topic, count), timeout=55)
    fallback = FALLBACK_PROMPTS[:count]
    prompts: List[str] = []
    reasons: List[str] = []
    if planner.get("ok"):
        shots = planner.get("shots") if isinstance(planner.get("shots"), list) else []
        for i, item in enumerate(shots[:count]):
            raw_prompt = item.get("prompt") if isinstance(item, dict) else str(item)
            raw_prompt = _normalize_visual_prompt(raw_prompt)
            ok, reason = _validate_visual_prompt(raw_prompt)
            if ok:
                prompts.append(raw_prompt)
            else:
                prompts.append(fallback[min(i, len(fallback)-1)])
                reasons.append(f"shot_{i+1}:{reason}")
    else:
        reasons.append(str(planner.get("error") or "deepseek_unavailable"))
        prompts = fallback
    while len(prompts) < count:
        prompts.append(fallback[len(prompts) % len(fallback)])
    # Final hard validation: never allow banned positive words to pass downstream.
    final: List[str] = []
    for i, p in enumerate(prompts[:count]):
        ok, reason = _validate_visual_prompt(p)
        if ok:
            final.append(p)
        else:
            final.append(fallback[min(i, len(fallback)-1)])
            reasons.append(f"final_{i+1}:{reason}")
    return {
        "ok": bool(planner.get("ok")),
        "source": "deepseek" if planner.get("ok") else "curated_fallback",
        "planner": planner,
        "prompts": final,
        "validation_notes": reasons,
        "negative_prompt": BANNED_VISUAL_NEGATIVE,
    }


def _scene_prompts(city: str, topic: str, requested_count: int = 3) -> List[str]:
    plan = _deepseek_scene_prompts(city, topic, requested_count=requested_count)
    return list(plan.get("prompts") or FALLBACK_PROMPTS[:max(3, min(int(requested_count or 3), 4))])

def _to_cn_digits(text: str) -> str:
    table = str.maketrans({"0":"零","1":"一","2":"二","3":"三","4":"四","5":"五","6":"六","7":"七","8":"八","9":"九"})
    return str(text or "").translate(table)


def _split_subtitle_chunks(script: str, max_chars: int = 9) -> List[str]:
    """Make Douyin-style subtitle chunks: pure text, one short phrase per cue.

    Avoid the old ugly two-line split like “生活还不 / 方便”.
    """
    text = _to_cn_digits(str(script or ""))
    text = re.sub(r"\s+", " ", text.strip())
    if not text:
        return []
    # punctuation marks are boundaries first, then removed by _clean_subtitle_text
    rough = [x.strip() for x in re.split(r"[。！？!?；;，,、：:\n]+", text) if x.strip()] or [text]
    preferred_breakers = ["因为", "但是", "如果", "不是", "而是", "先看", "再看", "第一", "第二", "第三", "自住", "投资", "出租", "区域", "配套", "通勤", "生活"]
    out: List[str] = []
    for piece in rough:
        piece = _clean_subtitle_text(piece)
        if not piece:
            continue
        # Insert soft boundaries before important connector words when the phrase is too long.
        if len(piece) > max_chars + 3:
            for b in preferred_breakers:
                piece = piece.replace(b, "|" + b)
        for part in [x for x in piece.split("|") if x]:
            part = _clean_subtitle_text(part)
            while len(part) > max_chars:
                # Keep the last chunk from being one lonely character.
                cut = max_chars
                rest = len(part) - cut
                if rest == 1:
                    cut -= 1
                out.append(part[:cut])
                part = part[cut:]
            if part:
                out.append(part)
    # merge very short chunks only when it does not exceed max length
    merged: List[str] = []
    for part in out:
        if merged and len(merged[-1]) <= 3 and len(merged[-1]) + len(part) <= max_chars:
            merged[-1] += part
        else:
            merged.append(part)
    return [x for x in merged if x]

def _tts_segment_cues(tts_res: Dict[str, Any], duration: float) -> List[Dict[str, Any]]:
    # Try to use backend TTS per-segment timing if it exists. Different TTS providers use different keys.
    candidates: List[Any] = []
    for key in ("segments", "audio_segments", "items", "results"):
        value = tts_res.get(key) if isinstance(tts_res, dict) else None
        if isinstance(value, list):
            candidates = value
            break
    cues: List[Dict[str, Any]] = []
    t = 0.05
    for item in candidates:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or item.get("sentence") or item.get("content") or "").strip()
        if not text:
            continue
        start = item.get("start") or item.get("start_time") or item.get("start_seconds")
        end = item.get("end") or item.get("end_time") or item.get("end_seconds")
        dur = item.get("duration") or item.get("duration_seconds")
        try:
            st = float(start) if start is not None else t
            en = float(end) if end is not None else st + float(dur)
        except Exception:
            continue
        en = min(float(duration), max(st + 0.45, en))
        cues.append({"text": text, "start": round(max(0.0, st), 2), "end": round(en, 2)})
        t = en
    return cues


def _subtitle_cues(script: str, duration: float, tts_res: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    duration = max(1.0, float(duration or 1.0))
    # Prefer exact TTS segment timing, then split long TTS lines into Douyin-sized chunks.
    raw = _tts_segment_cues(tts_res or {}, duration)
    if raw:
        refined: List[Dict[str, Any]] = []
        for cue in raw:
            parts = _split_subtitle_chunks(str(cue.get("text") or ""), max_chars=9) or [str(cue.get("text") or "")]
            st = float(cue.get("start") or 0)
            en = float(cue.get("end") or st + 1.0)
            span = max(0.5, en - st)
            weights = [max(2, len(x)) for x in parts]
            total = sum(weights) or 1
            cur = st
            for i, (part, w) in enumerate(zip(parts, weights)):
                nxt = en if i == len(parts) - 1 else min(en, cur + span * w / total)
                refined.append({"text": part, "start": round(cur, 2), "end": round(max(cur + 0.45, nxt), 2)})
                cur = nxt
        return refined

    parts = _split_subtitle_chunks(script, max_chars=9)
    if not parts:
        return [{"text": script.strip(), "start": 0.05, "end": round(duration, 2)}]
    weights = [max(2, len(p)) for p in parts]
    total = sum(weights) or 1
    usable = max(0.8, duration - 0.1)
    cues: List[Dict[str, Any]] = []
    t = 0.05
    for i, (p, w) in enumerate(zip(parts, weights)):
        # Short chunks. Avoid old long-sentence subtitles staying on screen too long.
        seg_d = usable * w / total
        seg_d = max(0.55, min(seg_d, 2.15))
        if i == len(parts) - 1:
            end = duration
        else:
            end = min(duration, t + seg_d)
        cues.append({"text": p, "start": round(t, 2), "end": round(max(t + 0.45, end), 2)})
        t = end
        if t >= duration - 0.15:
            break
    if cues:
        cues[-1]["end"] = round(duration, 2)
    return cues

def _poll_fal(job_id: str, timeout_s: int = 900) -> Dict[str, Any]:
    deadline = time.time() + timeout_s
    last: Dict[str, Any] = {}
    while time.time() < deadline:
        last = _get_json(f"http://127.0.0.1:8000/api/video/fal/job/{job_id}", timeout=60)
        if _failed(last) or (_done(last) and _video_url(last)):
            return last
        time.sleep(8)
    return {"ok": False, "status": "failed", "error": "fal one-scene shot timeout", "last": last}


def _resolve_audio(audio_url: str) -> Path:
    audio_ref = str(audio_url or "").strip()
    if audio_ref.startswith("http://") or audio_ref.startswith("https://"):
        return _download(audio_ref, Path(urlparse(audio_ref).path).suffix or ".mp3")
    candidates = [Path(audio_ref)]
    if audio_ref and not Path(audio_ref).is_absolute():
        candidates.extend([BASE_DIR / audio_ref, BASE_DIR / "data" / audio_ref, Path("/tmp") / audio_ref])
    audio = next((x for x in candidates if x.exists()), candidates[0] if candidates else Path(""))
    if not audio.exists():
        raise RuntimeError(f"TTS 音频不存在或不可下载: {audio_url}; checked={ [str(x) for x in candidates] }")
    return audio


def _compose_dynamic_scene_with_audio(video_urls: List[str], audio_url: str, duration: float, prefix: str) -> Path:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg 不可用，无法合成单场景动态视频")
    _ensure()
    if not video_urls:
        raise RuntimeError("没有可用的单场景动态画面 URL")
    clips = [_download(u, ".mp4") for u in video_urls]
    audio = _resolve_audio(audio_url)
    # 先把 2~4 个全屏动态角度拼成一个无声背景视频，再循环铺满整段配音。
    bg_mix = WORK_DIR / f"{prefix}_dynamic_bg_{uuid.uuid4().hex[:8]}.mp4"
    inputs: List[str] = []
    filters: List[str] = []
    labels: List[str] = []
    for i, clip in enumerate(clips):
        inputs.extend(["-i", str(clip)])
        labels.append(f"[v{i}]")
        filters.append(f"[{i}:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30,setsar=1,trim=duration=5,setpts=PTS-STARTPTS[v{i}]")
    filter_complex = ";".join(filters) + ";" + "".join(labels) + f"concat=n={len(clips)}:v=1:a=0,format=yuv420p[v]"
    cmd_bg = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[v]", "-an",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
        "-movflags", "+faststart",
        str(bg_mix),
    ]
    proc = subprocess.run(cmd_bg, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=900)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or "dynamic scene concat failed")

    out = WORK_DIR / f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.mp4"
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-stream_loop", "-1", "-i", str(bg_mix),
        "-i", str(audio),
        "-t", str(round(float(duration) + 0.12, 2)),
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest", "-movflags", "+faststart",
        str(out),
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=900)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or "dynamic scene ffmpeg compose failed")
    return out


def _make_thumbnail(video_path: Path, prefix: str) -> Dict[str, Any]:
    try:
        thumb = WORK_DIR / f"{prefix}_{uuid.uuid4().hex[:8]}_cover.jpg"
        subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", "1.0", "-i", str(video_path), "-frames:v", "1", "-q:v", "2", str(thumb)], check=True, timeout=60)
        upload = upload_file_to_r2(thumb, object_key=f"images/video-covers/{time.strftime('%Y/%m/%d')}/{thumb.name}")
        return {"ok": True, "thumbnail_url": upload.get("url"), "r2": upload}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _run(job_id: str, raw: Dict[str, Any]) -> None:
    job = _jobs[job_id]
    try:
        title = str(raw.get("title") or raw.get("topic") or "马来西亚买房，别只看价格")
        target = _duration(raw)
        script = _clean_script(title, str(raw.get("script_text") or ""), target)
        job.update({"stage": "tts", "progress": 8, "script_text": script, "target_duration_seconds": target, "updated_at": time.time()}); _persist(job_id)

        audio_dur, audio_url, tts_res = _tts(script, str(raw.get("voice") or "default"))
        job.update({"stage": "one_scene_fal", "progress": 25, "audio_duration_seconds": round(audio_dur, 2), "audio_url": audio_url, "tts_result": tts_res, "updated_at": time.time()}); _persist(job_id)

        scene_count = max(3, min(int(raw.get("dynamic_shot_count") or raw.get("fal_fill_shots") or 3), 4))
        visual_plan = _deepseek_scene_prompts(str(raw.get("city") or ""), title, requested_count=scene_count)
        prompts = list(visual_plan.get("prompts") or [])
        job.update({"visual_prompt_planner": visual_plan, "visual_prompt_source": visual_plan.get("source"), "visual_prompt_validation_notes": visual_plan.get("validation_notes") or [], "updated_at": time.time()}); _persist(job_id)
        fal_results: List[Dict[str, Any]] = []
        bg_urls: List[str] = []
        for idx, prompt in enumerate(prompts, start=1):
            job.update({"stage": f"one_scene_fal_{idx}_of_{len(prompts)}", "progress": 25 + int(35 * (idx - 1) / max(1, len(prompts))), "updated_at": time.time()}); _persist(job_id)
            print(f"ONE_SCENE_DEEPSEEK_VALIDATED_PROMPT_{idx}=" + prompt[:1200], flush=True)
            start = _post_json("http://127.0.0.1:8000/api/video/fal/shot/start", {
                "prompt": prompt,
                "duration_seconds": 5.0,
                "duration": 5.0,
                "width": 1080,
                "height": 1920,
                "fps": int(raw.get("fps") or 30),
                "negative_prompt": BANNED_VISUAL_NEGATIVE,
            }, timeout=120)
            fid = start.get("job_id") or start.get("id") or (start.get("data") or {}).get("job_id")
            if not fid:
                raise RuntimeError(f"fal dynamic scene {idx} did not return job_id: {start}")
            fal_done = _poll_fal(str(fid), timeout_s=1200)
            bg_url = _video_url(fal_done)
            if not bg_url:
                raise RuntimeError(f"fal dynamic scene {idx} failed/no video_url: {fal_done}")
            fal_results.append(fal_done)
            bg_urls.append(bg_url)
        job.update({"stage": "compose_dynamic_scene", "progress": 70, "background_video_urls": bg_urls, "background_video_url": bg_urls[0] if bg_urls else "", "fal_results": fal_results, "updated_at": time.time()}); _persist(job_id)

        composed_path = _compose_dynamic_scene_with_audio(bg_urls, audio_url, audio_dur, prefix=job_id)
        raw_upload = upload_file_to_r2(composed_path, object_key=f"videos/one-scene/raw/{time.strftime('%Y/%m/%d')}/{composed_path.name}")
        raw_url = raw_upload.get("url") or ""

        final_url = raw_url
        subtitle_res: Dict[str, Any] = {}
        subtitle_error = ""
        if bool(raw.get("burn_subtitles", True)):
            job.update({"stage": "subtitle_burn_exact_script", "progress": 88, "raw_video_url": raw_url, "updated_at": time.time()}); _persist(job_id)
            cues = _subtitle_cues(script, float(audio_dur), tts_res)
            highlight_keywords = _extract_highlight_keywords(raw, title, script)
            try:
                subtitle_res = burn_subtitles_with_style_and_upload(
                    video_path=str(composed_path),
                    text=script,
                    segments=cues,
                    duration=float(audio_dur),
                    style_id=str(raw.get("subtitle_style_id") or "douyin_pop"),
                    keywords=highlight_keywords,
                    prefix=f"one_scene_{job_id}",
                    object_key=f"videos/one-scene/subtitled/{time.strftime('%Y/%m/%d')}/{uuid.uuid4().hex}_{job_id}.mp4",
                )
                final_url = str(subtitle_res.get("video_url") or raw_url)
            except Exception as sub_exc:
                subtitle_error = str(sub_exc)
                print(f"ONE_SCENE_SUBTITLE_BURN_FAILED job_id={job_id} error={subtitle_error}", flush=True)
                subtitle_res = {"ok": False, "error": subtitle_error, "fallback_raw_video_url": raw_url}
                final_url = raw_url

        thumb = _make_thumbnail(composed_path, prefix=job_id)
        job.update({
            "ok": True,
            "status": "completed",
            "stage": "completed",
            "progress": 100,
            "video_url": final_url,
            "subtitled_video_url": final_url if subtitle_res else "",
            "raw_video_url": raw_url,
            "thumbnail_url": thumb.get("thumbnail_url") or "",
            "subtitle_result": subtitle_res,
            "subtitle_error": subtitle_error,
            "thumbnail_result": thumb,
            "single_scene": True,
            "dynamic_single_scene": True,
            "shot_count": len(bg_urls),
            "updated_at": time.time(),
        }); _persist(job_id)
    except Exception as exc:
        err = str(exc)
        print(f"ONE_SCENE_FAILED job_id={job_id} stage={job.get('stage')} error={err}", flush=True)
        job.update({"ok": False, "status": "failed", "stage": "failed", "progress": 100, "error": err, "message": err, "audio_url": job.get("audio_url") or "", "background_video_url": job.get("background_video_url") or "", "updated_at": time.time()}); _persist(job_id)


@router.get("/health")
def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "provider": "full_ai_one_scene_v10_18",
        "single_scene": True,
        "shot_count": 3,
        "dynamic_single_scene": True,
        "dynamic_shot_count": 3,
        "real_condo_tour_visuals": True,
        "positive_prompt_without_banned_words": True,
        "negative_prompt_only_for_forbidden_objects": True,
        "interior_architecture_only": True,
        "no_office_papers_floorplans": True,
        "same_theme_multi_angle": True,
        "exact_script_subtitles": True,
        "douyin_subtitle_styles": True,
        "short_chunk_subtitle_timing": True,
        "safe_audio_url_extraction": True,
        "failure_error_exposed": True,
        "raw_video_fallback": True,
        "no_static_single_frame_loop": True,
        "punctuation_free_subtitles": True,
        "digits_converted_to_chinese": True,
        "one_line_short_subtitles": True,
        "keyword_highlight_scale": True,
        "deepseek_visual_prompt_planner": True,
        "hard_prompt_validation": True,
        "positive_prompt_banned_word_filter": True,
        "curated_fallback_when_deepseek_invalid": True,
        "no_multi_shots": True,
    }


@router.post("/start")
def start(req: StartReq) -> Dict[str, Any]:
    job_id = "one_scene_" + uuid.uuid4().hex[:18]
    raw = req.model_dump()
    _jobs[job_id] = {"ok": True, "job_id": job_id, "job_type": "one_scene", "status": "running", "stage": "queued", "progress": 1, "created_at": time.time(), "updated_at": time.time(), "request": raw}
    _persist(job_id)
    threading.Thread(target=_run, args=(job_id, raw), daemon=True).start()
    return {"ok": True, "job_id": job_id, "status": "running", "stage": "queued", "single_scene": True, "message": "已启动 V10.18 纯公寓内景动态看房视频：禁用桌面纸张计算器，使用干净室内镜头。"}


@router.get("/job/{job_id}")
def get_job(job_id: str) -> Dict[str, Any]:
    return dict(_jobs.get(job_id) or {"ok": False, "job_id": job_id, "status": "not_found"})


def install_full_ai_one_scene(app: FastAPI) -> None:
    app.include_router(router)
