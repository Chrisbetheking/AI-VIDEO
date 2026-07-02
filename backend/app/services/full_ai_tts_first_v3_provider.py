from __future__ import annotations

import json
import math
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib import request as urlrequest

from fastapi import APIRouter, FastAPI
from pydantic import BaseModel, ConfigDict

from app.services.subtitle_style_library_provider import burn_subtitles_with_style_and_upload
try:
    from app.services.job_persistence_provider import save_job_response
except Exception:  # pragma: no cover
    save_job_response = None

router = APIRouter(prefix="/api/video/full-ai/tts-first-v3", tags=["full-ai-tts-first-v3"])
_jobs: Dict[str, Dict[str, Any]] = {}

SCENES_KL = [
    "modern Kuala Lumpur condominium lobby entrance, agent opening glass door, one continuous handheld phone video",
    "modern condo living room, sofa and warm daylight through floor-to-ceiling window, one continuous handheld phone video",
    "condo balcony with ordinary Kuala Lumpur residential skyline and greenery, no famous towers, one continuous handheld phone video",
    "condominium swimming pool deck with plants and lounge chairs, one continuous handheld phone video",
    "clean condominium gym with treadmills and city light through windows, one continuous handheld phone video",
    "agent showing a client the apartment kitchen and dining area, natural walkthrough, one continuous handheld phone video",
    "modern bedroom and wardrobe detail, warm daylight, one continuous handheld phone video",
    "Mont Kiara residential street with condo entrance, trees and cafe frontage, one continuous handheld phone video",
]
SCENES_OTHER = {
    "penang": [
        "Penang apartment living room with tropical daylight, one continuous handheld phone video",
        "Gurney Drive residential area street-level lifestyle, one continuous handheld phone video",
        "Penang condo balcony with soft sea breeze and residential towers, one continuous handheld phone video",
        "condo pool deck and family lifestyle in Penang, one continuous handheld phone video",
    ],
    "johor": [
        "Johor Bahru modern apartment living room, family self-stay feel, one continuous handheld phone video",
        "Medini condo entrance and residential community, one continuous handheld phone video",
        "Johor condo kitchen and dining area, practical family living, one continuous handheld phone video",
        "street-level shopping and commute lifestyle near Johor residences, one continuous handheld phone video",
    ],
    "langkawi": [
        "Langkawi resort-style residential pool and tropical greenery, one continuous handheld phone video",
        "quiet island residence living room for long-stay lifestyle, one continuous handheld phone video",
        "villa entrance and garden walkway in Langkawi, one continuous handheld phone video",
    ],
    "sabah": [
        "Kota Kinabalu modern apartment living room with sunset daylight, one continuous handheld phone video",
        "Sabah residential balcony with coastal city atmosphere, one continuous handheld phone video",
        "resort-style community facilities in Sabah residential development, one continuous handheld phone video",
    ],
}

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
    subtitle_style_id: str = "real_estate_gold"


def _persist(job_id: str) -> None:
    if not save_job_response:
        return
    try:
        job = dict(_jobs.get(job_id) or {})
        if job:
            save_job_response(job_id, "tts_first_v3", job, source_path="/api/video/full-ai/tts-first-v3")
    except Exception as exc:
        print("TTS_FIRST_V3_PERSIST_FAILED", exc, flush=True)


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


def _city(title: str, script: str, user_city: str) -> str:
    raw = f"{user_city} {title} {script}".lower()
    if "penang" in raw or "槟城" in raw: return "penang"
    if "johor" in raw or "新山" in raw: return "johor"
    if "langkawi" in raw or "兰卡威" in raw: return "langkawi"
    if "sabah" in raw or "沙巴" in raw or "亚庇" in raw: return "sabah"
    return "kuala_lumpur"


def _duration(raw: Dict[str, Any]) -> float:
    v = raw.get("duration_seconds") or raw.get("target_duration_seconds") or raw.get("targetSeconds") or 20
    try:
        return max(8.0, min(float(v), 60.0))
    except Exception:
        return 20.0


def _normalize_script(title: str, script: str, seconds: float, city: str) -> str:
    script = (script or "").strip()
    title = (title or "马来西亚买房，别只看价格").strip()
    if not script:
        script = f"{title}。很多人买房第一眼只看价格，但真正要先看区域、用途和流动性。自住要看生活半径和社区品质，投资要看租客来源和未来转手。"
    min_chars, max_chars = int(seconds * 4.0), int(seconds * 5.0)
    while len(script) < min_chars:
        script += " 先判断真实需求，再看区域成熟度、出租需求和生活便利。"
    if len(script) > max_chars:
        script = script[:max_chars].rstrip("，。,. ") + "。"
    return script


def _first_value(obj: Any, keys: List[str]) -> Optional[Any]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            lk = str(k).lower()
            if any(x in lk for x in keys): return v
        for v in obj.values():
            got = _first_value(v, keys)
            if got is not None: return got
    elif isinstance(obj, list):
        for v in obj:
            got = _first_value(v, keys)
            if got is not None: return got
    return None


def _tts(script: str, voice: str) -> tuple[float, str, Dict[str, Any]]:
    fall_dur = max(6.0, len(script) / 4.6)
    payloads = [{"text": script, "voice": voice}, {"script_text": script, "voice": voice}, {"segments": [{"text": script}], "voice": voice}]
    last: Dict[str, Any] = {}
    for p in payloads:
        try:
            res = _post_json("http://127.0.0.1:8000/api/tts-segments", p, timeout=180)
            last = res
            dur = _first_value(res, ["duration"])
            url = _first_value(res, ["audio_url", "audio", "mp3", "wav", "path"])
            try: dur_f = float(dur) if dur is not None else fall_dur
            except Exception: dur_f = fall_dur
            return dur_f if dur_f > 0 else fall_dur, str(url or ""), res
        except Exception as exc:
            last = {"ok": False, "error": str(exc)}
    return fall_dur, "", last


def _split(script: str, count: int) -> List[str]:
    parts = [x.strip() for x in re.split(r"[。！？!?；;\n]+", script) if x.strip()]
    if not parts: parts = [script]
    out = ["" for _ in range(count)]
    for i, p in enumerate(parts):
        out[i % count] = (out[i % count] + "。" + p).strip("。")
    return [x or parts[min(i, len(parts)-1)] for i, x in enumerate(out)]


def _scenes(city: str) -> List[str]:
    return SCENES_OTHER.get(city) or SCENES_KL


def _shot_count(audio_duration: float, raw: Dict[str, Any]) -> int:
    # Quality first: do not ask fal for long complicated shots. Use short independent scenes.
    raw_max = raw.get("max_shots") or raw.get("fal_fill_shots")
    try:
        if raw_max:
            return max(2, min(int(raw_max), 10))
    except Exception:
        pass
    return max(2, min(math.ceil(audio_duration / 7.0), 8))


def _prompt(scene: str) -> str:
    return (
        f"{scene}. Vertical 9:16 realistic phone video, one continuous camera take, full screen single scene only. "
        "No editing, no montage, no collage, no split screen, no panels, no grid, no brochure, no poster, no documents, no charts, no calculator, no readable text. "
        "Natural lighting, realistic Malaysian condominium environment, smooth slow handheld camera movement, clean residential atmosphere. "
        "Do not show KLCC, Petronas Twin Towers, beach, island, ocean, fake project name, exact price or ROI."
    )


def _video_url(data: Dict[str, Any]) -> str:
    for k in ("video_url", "url", "output_url", "result_url"):
        v = data.get(k)
        if isinstance(v, str) and v: return v
    r = data.get("result") if isinstance(data.get("result"), dict) else {}
    for k in ("video_url", "url", "output_url", "result_url"):
        v = r.get(k)
        if isinstance(v, str) and v: return v
    return ""


def _done(data: Dict[str, Any]) -> bool:
    t = f"{data.get('status','')} {data.get('stage','')}".lower()
    return any(x in t for x in ["done", "completed", "success", "succeeded", "finished"])


def _failed(data: Dict[str, Any]) -> bool:
    t = f"{data.get('status','')} {data.get('stage','')} {data.get('error','')}".lower()
    return any(x in t for x in ["failed", "error"])


def _poll_fal(job_id: str, timeout_s: int = 900) -> Dict[str, Any]:
    deadline = time.time() + timeout_s
    last: Dict[str, Any] = {}
    while time.time() < deadline:
        last = _get_json(f"http://127.0.0.1:8000/api/video/fal/job/{job_id}", timeout=60)
        if _failed(last) or (_done(last) and _video_url(last)):
            return last
        time.sleep(8)
    return {"ok": False, "status": "failed", "error": "fal shot timeout", "last": last}


def _poll_compose(job_id: str, timeout_s: int = 900) -> Dict[str, Any]:
    deadline = time.time() + timeout_s
    last: Dict[str, Any] = {}
    while time.time() < deadline:
        last = _get_json(f"http://127.0.0.1:8000/api/video/compose/job/{job_id}", timeout=60)
        if _failed(last) or (_done(last) and _video_url(last)):
            return last
        time.sleep(8)
    return {"ok": False, "status": "failed", "error": "compose timeout", "last": last}


def _run(job_id: str, raw: Dict[str, Any]) -> None:
    job = _jobs[job_id]
    try:
        title = str(raw.get("title") or raw.get("topic") or "马来西亚买房，别只看价格")
        target = _duration(raw)
        city = _city(title, str(raw.get("script_text") or ""), str(raw.get("city") or ""))
        script = _normalize_script(title, str(raw.get("script_text") or ""), target, city)
        job.update({"stage": "tts", "progress": 10, "city": city, "script_text": script, "target_duration_seconds": target, "updated_at": time.time()}); _persist(job_id)

        audio_dur, audio_url, tts_res = _tts(script, str(raw.get("voice") or "default"))
        count = _shot_count(audio_dur, raw)
        scenes = _scenes(city)
        segs = _split(script, count)
        per = max(3.0, min(5.0, audio_dur / count))
        shots = []
        for i in range(count):
            scene = scenes[i % len(scenes)]
            shots.append({"index": i + 1, "scene": scene, "title": scene, "duration_seconds": round(per, 2), "narration_segment": segs[i], "prompt": _prompt(scene), "visual_prompt": _prompt(scene)})
        job.update({"stage": "fal_shots", "progress": 20, "audio_duration_seconds": round(audio_dur, 2), "audio_url": audio_url, "tts_result": tts_res, "shot_count": count, "shots": shots, "updated_at": time.time()}); _persist(job_id)
        print(f"TTS_FIRST_V3_SHOT_COUNT={count}", flush=True)
        print(f"TTS_FIRST_V3_PROMPT_1={shots[0]['prompt'][:260] if shots else ''}", flush=True)

        video_urls: List[str] = []
        fal_jobs: List[Dict[str, Any]] = []
        for i, shot in enumerate(shots, start=1):
            job.update({"stage": f"fal_shot_{i}_of_{count}", "progress": 20 + int(50 * (i-1) / max(count, 1)), "updated_at": time.time()}); _persist(job_id)
            start = _post_json("http://127.0.0.1:8000/api/video/fal/shot/start", {
                "prompt": shot["prompt"],
                "duration_seconds": shot["duration_seconds"],
                "duration": shot["duration_seconds"],
                "width": 1080,
                "height": 1920,
                "fps": int(raw.get("fps") or 30),
                "negative_prompt": "collage, split screen, multi panel, grid, brochure, poster, documents, charts, calculator, readable text, KLCC, Petronas Twin Towers",
            }, timeout=120)
            fid = start.get("job_id") or start.get("id") or (start.get("data") or {}).get("job_id")
            if not fid:
                raise RuntimeError(f"fal shot {i} did not return job_id: {start}")
            done = _poll_fal(str(fid), timeout_s=1200)
            fal_jobs.append({"start": start, "done": done})
            url = _video_url(done)
            if not url:
                raise RuntimeError(f"fal shot {i} failed/no video_url: {done}")
            video_urls.append(url)
            job.update({"video_urls": video_urls, "fal_jobs": fal_jobs, "updated_at": time.time()}); _persist(job_id)

        job.update({"stage": "compose", "progress": 78, "updated_at": time.time()}); _persist(job_id)
        compose_start = _post_json("http://127.0.0.1:8000/api/video/compose/urls/start", {
            "title": title,
            "video_urls": video_urls,
            "urls": video_urls,
            "audio_url": audio_url,
            "upload": True,
            "folder": "videos/full-ai-v3",
            "width": 1080,
            "height": 1920,
            "fps": int(raw.get("fps") or 30),
        }, timeout=120)
        cid = compose_start.get("job_id") or compose_start.get("id") or (compose_start.get("data") or {}).get("job_id")
        if not cid:
            raise RuntimeError(f"compose did not return job_id: {compose_start}")
        compose_done = _poll_compose(str(cid), timeout_s=1200)
        raw_video_url = _video_url(compose_done)
        if not raw_video_url:
            raise RuntimeError(f"compose failed/no video_url: {compose_done}")

        final_url = raw_video_url
        subtitle_res: Dict[str, Any] = {}
        if bool(raw.get("burn_subtitles", True)):
            job.update({"stage": "subtitle_burn", "progress": 92, "raw_video_url": raw_video_url, "updated_at": time.time()}); _persist(job_id)
            subtitle_res = burn_subtitles_with_style_and_upload(
                video_url=raw_video_url,
                text=script,
                segments=raw.get("script_segments") if isinstance(raw.get("script_segments"), list) else None,
                duration=float(audio_dur),
                style_id=str(raw.get("subtitle_style_id") or "real_estate_gold"),
                prefix=f"tts_first_v3_{job_id}",
            )
            final_url = str(subtitle_res.get("video_url") or raw_video_url)

        job.update({
            "ok": True,
            "status": "completed",
            "stage": "completed",
            "progress": 100,
            "video_url": final_url,
            "subtitled_video_url": final_url if subtitle_res else "",
            "raw_video_url": raw_video_url,
            "compose_result": compose_done,
            "subtitle_result": subtitle_res,
            "updated_at": time.time(),
        }); _persist(job_id)
    except Exception as exc:
        job.update({"ok": False, "status": "failed", "stage": "failed", "progress": 100, "error": str(exc), "updated_at": time.time()}); _persist(job_id)


@router.get("/health")
def health() -> Dict[str, Any]:
    return {"ok": True, "provider": "full_ai_tts_first_v3", "version": "v10_11", "bypass_full_ai_parent": True, "direct_fal_shots": True, "single_scene_prompts": True, "subtitle": True, "persistent_v3_jobs": True}


@router.post("/start")
def start(req: StartReq) -> Dict[str, Any]:
    job_id = "tts_first_v3_" + uuid.uuid4().hex[:18]
    raw = req.model_dump()
    _jobs[job_id] = {"ok": True, "job_id": job_id, "job_type": "tts_first_v3", "status": "running", "stage": "queued", "progress": 1, "created_at": time.time(), "updated_at": time.time(), "request": raw}
    _persist(job_id)
    threading.Thread(target=_run, args=(job_id, raw), daemon=True).start()
    return {"ok": True, "job_id": job_id, "status": "running", "stage": "queued"}


@router.get("/job/{job_id}")
def get_job(job_id: str) -> Dict[str, Any]:
    return dict(_jobs.get(job_id) or {"ok": False, "job_id": job_id, "status": "not_found"})


def install_full_ai_tts_first_v3(app: FastAPI) -> None:
    app.include_router(router)
