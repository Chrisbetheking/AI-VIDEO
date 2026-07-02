from __future__ import annotations

import json
import math
import os
import re
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib import request as urlrequest

from fastapi import APIRouter, FastAPI
from pydantic import BaseModel, ConfigDict

from app.services.subtitle_style_library_provider import burn_subtitles_with_style_and_upload

router = APIRouter(prefix="/api/video/full-ai/tts-first-v2", tags=["full-ai-tts-first-v2"])
_jobs: Dict[str, Dict[str, Any]] = {}

KL_DIVERSE_SCENES = [
    "Kuala Lumpur establishing shot: KLCC Twin Towers far in skyline with luxury high-rise condominium foreground, use only once",
    "modern luxury condo living room in Kuala Lumpur with floor-to-ceiling windows and city view, no Twin Towers close-up",
    "condo balcony overlooking Kuala Lumpur city skyline, residential towers and warm daylight, no repeated KLCC landmark shot",
    "TRX and Bukit Bintang urban context, premium residential neighborhood, commute and lifestyle radius",
    "Mont Kiara upscale condominium community, street-level residential lifestyle and family-friendly environment",
    "premium condominium lobby, security desk, elegant entrance and resident lounge in Kuala Lumpur",
    "high-rise condo facilities: swimming pool, gym and landscaped deck, premium residential lifestyle",
    "real estate agent showing apartment interior, opening door, walking through living room and balcony",
    "modern condo kitchen, dining area and bedroom details, warm natural light, self-stay comfort",
]

PENANG_SCENES = [
    "Penang Gurney Drive residential skyline and urban second-home lifestyle",
    "Penang condo balcony with sea view, premium tropical residential atmosphere",
    "modern apartment interior in Penang with warm tropical daylight",
    "coastal residential pool and family lifestyle in Penang",
]

JOHOR_SCENES = [
    "Johor Bahru modern residential district and city skyline",
    "Medini premium condo community and family self-stay lifestyle",
    "Johor condo interior with practical family living details",
    "city commute, shopping mall and daily living radius in Johor Bahru",
]

LANGKAWI_SCENES = [
    "Langkawi tropical villa and resort-style residential pool",
    "luxury island residence with tropical greenery and second-home lifestyle",
    "quiet resort residence interior for long-stay living",
]

SABAH_SCENES = [
    "Kota Kinabalu coastal residential tower and sunset city lifestyle",
    "Sabah premium apartment balcony with marina and city atmosphere",
    "resort-style community facilities in Sabah residential development",
]


class TTSFirstV2StartRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    title: str = "马来西亚买房，别只看价格"
    topic: str = ""
    script_text: str = ""
    target_duration_seconds: float = 20
    duration_seconds: Optional[float] = None
    city: str = ""
    content_type: str = ""
    voice: str = "default"
    fps: int = 30
    width: int = 1080
    height: int = 1920
    extra: Dict[str, Any] = {}


def _admin_headers() -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    try:
        token = Path("/root/ai-video-admin-token.txt").read_text(encoding="utf-8").strip()
        if token:
            headers["X-AI-Video-Token"] = token
    except Exception:
        pass
    return headers


def _post_json(url: str, payload: Dict[str, Any], timeout: int = 180) -> Dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urlrequest.Request(url, data=body, headers=_admin_headers(), method="POST")
    with urlrequest.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw or "{}")


def _get_json(url: str, timeout: int = 60) -> Dict[str, Any]:
    req = urlrequest.Request(url, headers=_admin_headers(), method="GET")
    with urlrequest.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw or "{}")


def _target_duration(raw: Dict[str, Any]) -> float:
    v = raw.get("duration_seconds") or raw.get("target_duration_seconds") or raw.get("targetSeconds") or 20
    try:
        return max(5.0, min(float(v), 180.0))
    except Exception:
        return 20.0


def _target_chars(seconds: float) -> tuple[int, int]:
    return int(seconds * 4.3), int(seconds * 5.3)


def _normalize_script(title: str, script: str, seconds: float, city: str) -> str:
    title = (title or "马来西亚买房，别只看价格").strip()
    script = (script or "").strip()
    min_chars, max_chars = _target_chars(seconds)
    if not script:
        if city == "kuala_lumpur":
            script = (
                f"{title}。很多人买房第一眼只看价格，但在吉隆坡，真正要先看区域、用途和流动性。"
                "如果是自住，要看生活半径、通勤、社区品质和长期舒适度。"
                "如果是投资，要看租客来源、出租稳定性和未来转手。先把用途筛清楚，再看项目。"
            )
        else:
            script = f"{title}。马来西亚不同城市适合不同用途，自住、投资、第二家园和养老的判断标准不一样。"
    while len(script) < min_chars:
        script += " 先判断区域成熟度、真实需求、生活半径和未来转手，再比较价格和配套。"
    if len(script) > max_chars:
        script = script[:max_chars].rstrip("，。,. ") + "。"
    return script


def _infer_city(title: str, script: str, user_city: str = "") -> str:
    if user_city:
        t = user_city.lower()
        if "penang" in t or "槟城" in user_city: return "penang"
        if "langkawi" in t or "兰卡威" in user_city: return "langkawi"
        if "sabah" in t or "沙巴" in user_city or "亚庇" in user_city: return "sabah"
        if "johor" in t or "新山" in user_city: return "johor"
        return "kuala_lumpur"
    raw = f"{title}\n{script}".lower()
    if any(k in raw for k in ["槟城", "penang", "gurney"]): return "penang"
    if any(k in raw for k in ["兰卡威", "langkawi"]): return "langkawi"
    if any(k in raw for k in ["沙巴", "sabah", "kota kinabalu", "亚庇"]): return "sabah"
    if any(k in raw for k in ["新山", "johor", "medini"]): return "johor"
    return "kuala_lumpur"


def _scenes_for_city(city: str) -> List[str]:
    if city == "penang": return PENANG_SCENES
    if city == "johor": return JOHOR_SCENES
    if city == "langkawi": return LANGKAWI_SCENES
    if city == "sabah": return SABAH_SCENES
    return KL_DIVERSE_SCENES


def _split_script(script: str, count: int) -> List[str]:
    parts = [x.strip() for x in re.split(r"[。！？!?；;\n]+", script) if x.strip()]
    if not parts: return [script] * count
    result = ["" for _ in range(count)]
    for i, part in enumerate(parts):
        result[i % count] = (result[i % count] + "。" + part).strip("。")
    return [x or parts[min(i, len(parts)-1)] for i, x in enumerate(result)]


def _is_klcc_heavy(text: str) -> bool:
    raw = str(text or "").lower()
    return any(k in raw for k in ["klcc", "twin towers", "petronas", "双子塔"])


def _clean_scene_for_kl(scene: str, index: int) -> str:
    if index <= 1:
        return scene
    if _is_klcc_heavy(scene):
        return KL_DIVERSE_SCENES[(index - 1) % len(KL_DIVERSE_SCENES)]
    return scene


def _shot_prompt(city: str, index: int, narration_segment: str, scene: str = "") -> str:
    scenes = _scenes_for_city(city)
    main_scene = scene or scenes[(index - 1) % len(scenes)]
    if city == "kuala_lumpur":
        main_scene = _clean_scene_for_kl(main_scene, index)
        city_rule = (
            f"Kuala Lumpur only. Shot {index}: show a different real-estate scene. "
            "KLCC Twin Towers may appear only once as a far establishing landmark; do not repeat the same Twin Towers skyline. "
            "Use condo interior, balcony city view, lobby, pool, gym, agent showing apartment, TRX/Bukit Bintang context, Mont Kiara community, kitchen or bedroom details. "
            "No beach, no island, no seaside, no Langkawi/Sabah/Penang sea."
        )
    else:
        city_rule = "Use city-matched Malaysia real-estate visuals. Avoid fake project names, exact prices, exact ROI and unreadable text."
    return (
        "Premium 9:16 cinematic vertical video for Malaysia real-estate content.\n"
        f"Main scene: {main_scene}.\n"
        f"Narration meaning: {narration_segment[:90]}.\n"
        f"{city_rule}\n"
        "Visual diversity rule: every shot must show a different place or detail; mix exterior, interior, balcony, lobby, facilities, neighborhood and agent showing apartment. "
        "Ultra realistic, premium real estate commercial, natural lighting, clean composition, high detail, smooth camera movement, mobile-first vertical framing. "
        "No readable text, no logo, no watermark, no fake project name, no exact price, no exact ROI, no exact school name, no black borders."
    )


def _extract_first_value(obj: Any, key_patterns: List[str]) -> Optional[Any]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            lk = str(k).lower()
            if any(p in lk for p in key_patterns): return v
        for v in obj.values():
            found = _extract_first_value(v, key_patterns)
            if found is not None: return found
    elif isinstance(obj, list):
        for v in obj:
            found = _extract_first_value(v, key_patterns)
            if found is not None: return found
    return None


def _ffprobe_duration(path_or_url: str) -> Optional[float]:
    if not path_or_url: return None
    try:
        proc = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", path_or_url], capture_output=True, text=True, timeout=30)
        if proc.returncode == 0:
            d = float((json.loads(proc.stdout or "{}").get("format") or {}).get("duration") or 0)
            return d if d > 0 else None
    except Exception:
        return None
    return None


def _estimate_audio_duration(script: str) -> float:
    return max(5.0, len(script) / 4.8)


def _tts_duration(script: str, voice: str) -> tuple[float, Dict[str, Any]]:
    payloads = [
        {"text": script, "voice": voice},
        {"script_text": script, "voice": voice},
        {"copy": script, "voice": voice},
        {"segments": [{"text": script}], "voice": voice},
    ]
    last_error = ""
    for payload in payloads:
        try:
            res = _post_json("http://127.0.0.1:8000/api/tts-segments", payload, timeout=180)
            dur_val = _extract_first_value(res, ["duration"])
            if dur_val is not None:
                try:
                    d = float(dur_val)
                    if d > 0: return d, res
                except Exception: pass
            audio_val = _extract_first_value(res, ["audio_url", "audio", "mp3", "wav", "path"])
            if isinstance(audio_val, str):
                d = _ffprobe_duration(audio_val)
                if d: return d, res
            return _estimate_audio_duration(script), res
        except Exception as exc:
            last_error = str(exc)
    return _estimate_audio_duration(script), {"ok": False, "fallback": "estimated_duration", "error": last_error}


def _plan_shots(script: str, audio_duration: float, city: str, raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw_shots = raw.get("shots") if isinstance(raw.get("shots"), list) else []
    default_count = max(4 if audio_duration >= 16 else 1, math.ceil(audio_duration / 4.5))
    shot_count = max(1, min(int(raw.get("max_shots") or len(raw_shots) or default_count), 50))
    segments = _split_script(script, shot_count)
    each = audio_duration / shot_count
    scenes = _scenes_for_city(city)
    shots: list[dict[str, Any]] = []
    for i in range(1, shot_count + 1):
        raw_item = raw_shots[i - 1] if i - 1 < len(raw_shots) and isinstance(raw_shots[i - 1], dict) else {}
        seg = str(raw_item.get("narration_segment") or raw_item.get("narration") or segments[i - 1] if i - 1 < len(segments) else "")
        scene = str(raw_item.get("scene") or raw_item.get("title") or scenes[(i - 1) % len(scenes)])
        if city == "kuala_lumpur":
            scene = _clean_scene_for_kl(scene, i)
        prompt = _shot_prompt(city, i, seg, scene=scene)
        duration = raw_item.get("duration_seconds") or raw_item.get("duration") or each
        try: duration = float(duration)
        except Exception: duration = each
        shots.append({
            "index": i,
            "title": scene,
            "scene": scene,
            "prompt": prompt,
            "visual_prompt": prompt,
            "narration_segment": seg,
            "duration_seconds": round(duration, 2),
            "image_url": raw_item.get("image_url"),
            "asset_ids": raw_item.get("asset_ids") or raw_item.get("assetIds") or [],
            "source": raw_item.get("source") or "ai",
        })
    return shots


def _video_url_from(data: Dict[str, Any]) -> str:
    for k in ("video_url", "url", "output_url", "result_url"):
        v = data.get(k)
        if isinstance(v, str) and v: return v
    result = data.get("result") if isinstance(data.get("result"), dict) else {}
    for k in ("video_url", "url", "output_url", "result_url"):
        v = result.get(k)
        if isinstance(v, str) and v: return v
    return ""


def _is_done(data: Dict[str, Any]) -> bool:
    text = f"{data.get('status','')} {data.get('stage','')}".lower()
    return any(x in text for x in ["completed", "succeeded", "success", "done", "finished"])


def _is_failed(data: Dict[str, Any]) -> bool:
    text = f"{data.get('status','')} {data.get('stage','')}".lower()
    return any(x in text for x in ["failed", "error"])


def _burn_job_subtitles(job_id: str, raw_video_url: str) -> None:
    job = _jobs[job_id]
    try:
        raw = job.get("request") or {}
        style_id = str(raw.get("subtitle_style_id") or (raw.get("subtitle_style") or {}).get("id") or "real_estate_gold")
        job.update({"stage": "subtitle_burn", "status": "running", "progress": 92, "raw_video_url": raw_video_url})
        res = burn_subtitles_with_style_and_upload(
            video_url=raw_video_url,
            text=str(job.get("script_text") or raw.get("script_text") or ""),
            segments=raw.get("script_segments") if isinstance(raw.get("script_segments"), list) else None,
            duration=float(job.get("audio_duration_seconds") or raw.get("duration_seconds") or raw.get("target_duration_seconds") or 12),
            style_id=style_id,
            prefix=f"tts_first_v2_{job_id}",
        )
        job.update({
            "ok": True,
            "status": "completed",
            "stage": "completed",
            "progress": 100,
            "video_url": res.get("video_url") or raw_video_url,
            "subtitled_video_url": res.get("video_url"),
            "subtitle_result": res,
            "updated_at": time.time(),
        })
    except Exception as exc:
        job.update({
            "ok": True,
            "status": "completed",
            "stage": "completed_with_subtitle_error",
            "progress": 100,
            "video_url": raw_video_url,
            "raw_video_url": raw_video_url,
            "subtitle_error": str(exc),
            "updated_at": time.time(),
        })


def _run_job(job_id: str, raw: Dict[str, Any]) -> None:
    try:
        _jobs[job_id].update({"stage": "script", "progress": 10})
        title = str(raw.get("title") or raw.get("topic") or "马来西亚买房，别只看价格")
        user_script = str(raw.get("script_text") or "")
        target = _target_duration(raw)
        city = _infer_city(title, user_script, str(raw.get("city") or ""))
        script = _normalize_script(title, user_script, target, city)
        _jobs[job_id].update({"city": city, "target_duration_seconds": target, "script_text": script, "script_chars": len(script), "progress": 25, "stage": "tts"})

        audio_duration, tts_result = _tts_duration(script, str(raw.get("voice") or "default"))
        _jobs[job_id].update({"audio_duration_seconds": round(audio_duration, 2), "tts_result": tts_result, "progress": 50, "stage": "shot_plan"})
        shots = _plan_shots(script, audio_duration, city, raw)

        print(f"TTS_FIRST_V2_AUDIO_DURATION={audio_duration:.2f}", flush=True)
        print(f"TTS_FIRST_V2_SHOT_COUNT={len(shots)}", flush=True)
        print(f"TTS_FIRST_V2_CITY_LOCK={city}", flush=True)
        print(f"TTS_FIRST_V2_FINAL_PROMPT_1={shots[0]['prompt'][:260] if shots else ''}", flush=True)

        child_payload = dict(raw)
        child_payload.update({
            "title": title,
            "topic": title,
            "script_text": script,
            "duration_seconds": round(audio_duration, 2),
            "target_duration_seconds": round(audio_duration, 2),
            "target_seconds": round(audio_duration, 2),
            "targetDuration": round(audio_duration, 2),
            "shots": shots,
            "max_shots": len(shots),
            "fal_fill_shots": len(shots),
            "width": int(raw.get("width") or 1080),
            "height": int(raw.get("height") or 1920),
            "fps": int(raw.get("fps") or 30),
            "city": city,
            "visual_prompt_version": "tts_first_v2_diverse_kl_subtitle_v1",
        })
        _jobs[job_id].update({"shots": shots, "shot_count": len(shots), "progress": 65, "stage": "full_ai_start", "child_payload_preview": {"duration_seconds": child_payload["duration_seconds"], "shot_count": len(shots), "city": city, "first_prompt": shots[0]["prompt"][:220] if shots else ""}})
        child = _post_json("http://127.0.0.1:8000/api/video/full-ai/start", child_payload, timeout=120)
        child_job_id = child.get("job_id") or child.get("id") or (child.get("data") or {}).get("job_id")
        _jobs[job_id].update({"ok": True, "stage": "delegated", "status": "running", "progress": 75, "child_job_id": child_job_id, "child_start_result": child, "updated_at": time.time()})
    except Exception as exc:
        _jobs[job_id].update({"ok": False, "status": "failed", "stage": "failed", "error": str(exc), "updated_at": time.time()})


@router.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "provider": "full_ai_tts_first_v2", "logic": "script -> tts -> diverse shot plan -> full-ai -> subtitle burn -> R2", "subtitle": True, "visual_diversity": True}


@router.post("/start")
def start(req: TTSFirstV2StartRequest):
    job_id = "tts_first_v2_" + uuid.uuid4().hex[:18]
    raw = req.model_dump()
    _jobs[job_id] = {"ok": True, "job_id": job_id, "status": "running", "stage": "queued", "progress": 1, "created_at": time.time(), "updated_at": time.time(), "request": raw}
    threading.Thread(target=_run_job, args=(job_id, raw), daemon=True).start()
    return {"ok": True, "job_id": job_id, "status": "running", "stage": "queued"}


@router.get("/job/{job_id}")
def get_job(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        return {"ok": False, "status": "not_found", "job_id": job_id}
    child_job_id = job.get("child_job_id")
    if child_job_id and job.get("status") not in {"completed", "failed"}:
        try:
            child = _get_json(f"http://127.0.0.1:8000/api/video/full-ai/job/{child_job_id}", timeout=60)
            job["child_job"] = child
            if _is_failed(child):
                job.update({"status": "failed", "stage": "failed", "progress": 100, "error": child.get("error") or child.get("message") or "child full_ai failed", "updated_at": time.time()})
            elif _is_done(child):
                raw_video_url = _video_url_from(child)
                if raw_video_url:
                    burn_required = bool((job.get("request") or {}).get("burn_subtitles", True))
                    if burn_required and not job.get("subtitle_burn_started") and not job.get("subtitled_video_url"):
                        job["subtitle_burn_started"] = True
                        threading.Thread(target=_burn_job_subtitles, args=(job_id, raw_video_url), daemon=True).start()
                    elif not burn_required:
                        job.update({"status": "completed", "stage": "completed", "progress": 100, "video_url": raw_video_url, "updated_at": time.time()})
                else:
                    job.update({"status": "running", "stage": "waiting_video_url", "progress": 90, "updated_at": time.time()})
            else:
                # mirror useful status
                job.update({"stage": child.get("stage") or job.get("stage"), "status": "running", "progress": max(float(job.get("progress") or 75), 80), "updated_at": time.time()})
        except Exception as exc:
            job["child_poll_error"] = str(exc)
    return dict(job)


def install_full_ai_tts_first_v2(app: FastAPI) -> None:
    app.include_router(router)
