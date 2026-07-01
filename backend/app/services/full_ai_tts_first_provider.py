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
from pydantic import BaseModel


router = APIRouter(prefix="/api/video/full-ai/tts-first", tags=["full-ai-tts-first"])
_jobs: Dict[str, Dict[str, Any]] = {}


KL_SCENES = [
    "KLCC Twin Towers skyline with luxury high-rise condominium in the foreground, Kuala Lumpur premium real estate commercial, vertical 9:16 cinematic video",
    "Kuala Lumpur city-view luxury condo balcony overlooking the Petronas Twin Towers, premium Malaysia property lifestyle, vertical 9:16",
    "modern luxury condo living room with floor-to-ceiling windows and KLCC skyline outside, high-end real estate commercial, vertical 9:16",
    "premium condominium lobby in Kuala Lumpur, elegant residential atmosphere, luxury property marketing video, vertical 9:16",
    "infinity pool on a high-rise condo rooftop with Kuala Lumpur skyline and residential towers, premium Malaysia condo lifestyle, vertical 9:16",
    "TRX financial district and luxury residential towers in Kuala Lumpur, cinematic city lifestyle, vertical 9:16",
    "Mont Kiara upscale condominium neighborhood, family-friendly premium residential lifestyle, vertical 9:16",
    "night skyline of Kuala Lumpur with high-rise residential towers and city lights, premium property atmosphere, vertical 9:16",
]

PENANG_SCENES = [
    "Penang ocean-view condominium balcony with elegant seaside second-home lifestyle, Malaysia real estate commercial, vertical 9:16",
    "Gurney Drive coastal skyline with modern residential towers, premium Penang property lifestyle, vertical 9:16",
    "modern apartment interior facing the sea in Penang, warm tropical daylight, vertical 9:16",
    "coastal residential pool with palm trees and premium Penang lifestyle, vertical 9:16",
]

LANGKAWI_SCENES = [
    "Langkawi tropical villa and resort-style residential pool, premium Malaysia second-home lifestyle, vertical 9:16",
    "luxury island residence in Langkawi with tropical greenery and resort pool, vertical 9:16",
]

SABAH_SCENES = [
    "Sabah sunset ocean view with premium seaside apartment atmosphere, Malaysia property lifestyle, vertical 9:16",
    "Kota Kinabalu coastal residential tower with marina lifestyle atmosphere, vertical 9:16",
]


class TTSFirstStartRequest(BaseModel):
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


def _target_duration(req: TTSFirstStartRequest) -> float:
    v = req.duration_seconds or req.target_duration_seconds or 20
    try:
        return max(5.0, min(float(v), 180.0))
    except Exception:
        return 20.0


def _target_chars(seconds: float) -> tuple[int, int]:
    # 中文短视频口播大概 4.3-5.3 字/秒
    return int(seconds * 4.3), int(seconds * 5.3)


def _normalize_script(title: str, script: str, seconds: float, city: str) -> str:
    title = (title or "马来西亚买房，别只看价格").strip()
    script = (script or "").strip()
    min_chars, max_chars = _target_chars(seconds)

    if not script:
        if city == "kuala_lumpur":
            script = (
                f"{title}。很多人买房第一眼只看价格，但在吉隆坡，真正要先看区域、用途和流动性。"
                "KLCC、TRX、Mont Kiara 这类位置，看的不是热闹，而是生活半径、出租需求和未来转手。"
                "自住、出租和家庭配置，判断标准完全不一样。先把需求筛清楚，再去看房，才不会被带节奏。"
            )
        else:
            script = (
                f"{title}。马来西亚买房不要只看价格，要先看用途、城市和生活方式。"
                "不同城市适合不同人群，投资、自住、第二家园和养老，判断标准完全不一样。"
                "先把需求和预算筛清楚，再去看项目，才不会被带节奏。"
            )

    # 太短就补到目标时长附近
    while len(script) < min_chars:
        if city == "kuala_lumpur":
            addon = " 吉隆坡重点看 KLCC、TRX、Mont Kiara 的区位价值、生活配套、出租需求和转手流动性。"
        else:
            addon = " 不同城市的生活方式和投资逻辑不一样，先确定用途，再匹配区域和产品。"
        script += addon

    # 太长就裁掉
    if len(script) > max_chars:
        script = script[:max_chars].rstrip("，。,. ") + "。"

    return script


def _infer_city(title: str, script: str, user_city: str = "") -> str:
    if user_city:
        t = user_city.lower()
        if "penang" in t or "槟城" in user_city:
            return "penang"
        if "langkawi" in t or "兰卡威" in user_city:
            return "langkawi"
        if "sabah" in t or "沙巴" in user_city:
            return "sabah"
        if "johor" in t or "新山" in user_city:
            return "johor"
        return "kuala_lumpur"

    raw = f"{title}\n{script}".lower()
    if any(k in raw for k in ["槟城", "penang", "gurney"]):
        return "penang"
    if any(k in raw for k in ["兰卡威", "langkawi"]):
        return "langkawi"
    if any(k in raw for k in ["沙巴", "sabah", "kota kinabalu"]):
        return "sabah"
    if any(k in raw for k in ["吉隆坡", "klcc", "petronas", "trx", "mont kiara", "kuala lumpur", "kl "]):
        return "kuala_lumpur"

    # 默认马来西亚房产就是吉隆坡，不默认海边
    return "kuala_lumpur"


def _scenes_for_city(city: str) -> List[str]:
    if city == "penang":
        return PENANG_SCENES
    if city == "langkawi":
        return LANGKAWI_SCENES
    if city == "sabah":
        return SABAH_SCENES
    return KL_SCENES


def _split_script(script: str, count: int) -> List[str]:
    parts = [x.strip() for x in re.split(r"[。！？!?；;\n]+", script) if x.strip()]
    if not parts:
        return [script] * count

    # 合并/分配到 count 份
    result = ["" for _ in range(count)]
    for i, part in enumerate(parts):
        result[i % count] = (result[i % count] + "。" + part).strip("。")
    return [x or parts[min(i, len(parts)-1)] for i, x in enumerate(result)]


def _shot_prompt(city: str, index: int, narration_segment: str) -> str:
    scenes = _scenes_for_city(city)
    scene = scenes[(index - 1) % len(scenes)]

    purpose = "illustrate Malaysia real estate location value and premium property lifestyle"
    if city == "kuala_lumpur":
        purpose = "illustrate Kuala Lumpur property location value, KLCC city living, rental demand and premium condo lifestyle"
    elif city in {"penang", "langkawi", "sabah"}:
        purpose = "illustrate Malaysia second-home lifestyle, coastal property living and premium residential atmosphere"

    return (
        "Premium 9:16 cinematic vertical video for Malaysia real-estate content.\n"
        f"Main scene: {scene}.\n"
        f"Purpose: {purpose}.\n"
        f"Narration meaning: {narration_segment[:80]}.\n"
        "Style: ultra realistic, premium real estate commercial, natural lighting, clean composition, high detail, "
        "smooth camera movement, mobile-first vertical framing.\n"
        "Rules: no readable text, no logo, no watermark, no fake project name, no exact price, no exact ROI, "
        "no exact school name, no black borders."
    )


def _extract_first_value(obj: Any, key_patterns: List[str]) -> Optional[Any]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            lk = str(k).lower()
            if any(p in lk for p in key_patterns):
                return v
        for v in obj.values():
            found = _extract_first_value(v, key_patterns)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = _extract_first_value(v, key_patterns)
            if found is not None:
                return found
    return None


def _ffprobe_duration(path_or_url: str) -> Optional[float]:
    if not path_or_url:
        return None
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", path_or_url],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode == 0:
            data = json.loads(proc.stdout or "{}")
            d = float(data.get("format", {}).get("duration") or 0)
            if d > 0:
                return d
    except Exception:
        return None
    return None


def _estimate_audio_duration(script: str) -> float:
    # 兜底估算：中文 4.8 字/秒
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
                    if d > 0:
                        return d, res
                except Exception:
                    pass

            audio_val = _extract_first_value(res, ["audio_url", "audio", "mp3", "wav", "path"])
            if isinstance(audio_val, str):
                d = _ffprobe_duration(audio_val)
                if d:
                    return d, res

            return _estimate_audio_duration(script), res
        except Exception as exc:
            last_error = str(exc)

    return _estimate_audio_duration(script), {"ok": False, "fallback": "estimated_duration", "error": last_error}


def _plan_shots(script: str, audio_duration: float, city: str) -> List[Dict[str, Any]]:
    shot_count = max(1, math.ceil(audio_duration / 4.5))
    if audio_duration >= 16:
        shot_count = max(shot_count, 4)

    segments = _split_script(script, shot_count)
    each = audio_duration / shot_count

    shots = []
    for i in range(1, shot_count + 1):
        seg = segments[i - 1] if i - 1 < len(segments) else ""
        shots.append({
            "index": i,
            "prompt": _shot_prompt(city, i, seg),
            "visual_prompt": _shot_prompt(city, i, seg),
            "narration_segment": seg,
            "duration_seconds": round(each, 2),
            "image_url": None,
            "shot_id": None,
        })
    return shots


def _run_job(job_id: str, raw: Dict[str, Any]) -> None:
    try:
        _jobs[job_id]["stage"] = "script"
        _jobs[job_id]["progress"] = 10

        title = str(raw.get("title") or raw.get("topic") or "马来西亚买房，别只看价格")
        user_script = str(raw.get("script_text") or "")
        target = float(raw.get("duration_seconds") or raw.get("target_duration_seconds") or raw.get("targetSeconds") or 20)
        city = _infer_city(title, user_script, str(raw.get("city") or ""))

        script = _normalize_script(title, user_script, target, city)
        _jobs[job_id].update({
            "city": city,
            "target_duration_seconds": target,
            "script_text": script,
            "script_chars": len(script),
            "progress": 25,
            "stage": "tts",
        })

        audio_duration, tts_result = _tts_duration(script, str(raw.get("voice") or "default"))
        _jobs[job_id].update({
            "audio_duration_seconds": round(audio_duration, 2),
            "tts_result": tts_result,
            "progress": 50,
            "stage": "shot_plan",
        })

        shots = _plan_shots(script, audio_duration, city)

        print(f"TTS_FIRST_AUDIO_DURATION={audio_duration:.2f}")
        print(f"TTS_FIRST_SHOT_COUNT={len(shots)}")
        print(f"TTS_FIRST_CITY_LOCK={city}")
        print(f"TTS_FIRST_FINAL_PROMPT_1={shots[0]['prompt'][:260]}")

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
            "width": 1080,
            "height": 1920,
            "fps": int(raw.get("fps") or 30),
            "city": city,
            "visual_prompt_version": "tts_first_city_lock_v1",
        })

        _jobs[job_id].update({
            "shots": shots,
            "shot_count": len(shots),
            "progress": 65,
            "stage": "full_ai_start",
            "child_payload_preview": {
                "duration_seconds": child_payload["duration_seconds"],
                "shot_count": len(shots),
                "city": city,
                "first_prompt": shots[0]["prompt"][:220],
            }
        })

        child = _post_json("http://127.0.0.1:8000/api/video/full-ai/start", child_payload, timeout=120)
        child_job_id = child.get("job_id") or child.get("id") or child.get("data", {}).get("job_id")

        _jobs[job_id].update({
            "ok": True,
            "stage": "delegated",
            "status": "running",
            "progress": 75,
            "child_job_id": child_job_id,
            "child_start_result": child,
        })

    except Exception as exc:
        _jobs[job_id].update({
            "ok": False,
            "status": "failed",
            "stage": "failed",
            "error": str(exc),
            "updated_at": time.time(),
        })


@router.get("/health")
def health():
    return {
        "ok": True,
        "provider": "full_ai_tts_first_v1",
        "logic": "script -> tts -> audio duration -> shot count -> city lock -> full-ai compose",
    }


@router.post("/start")
def start(req: TTSFirstStartRequest):
    job_id = "tts_first_" + uuid.uuid4().hex[:18]
    raw = req.model_dump()
    _jobs[job_id] = {
        "ok": True,
        "job_id": job_id,
        "status": "running",
        "stage": "queued",
        "progress": 1,
        "created_at": time.time(),
        "request": raw,
    }
    threading.Thread(target=_run_job, args=(job_id, raw), daemon=True).start()
    return {"ok": True, "job_id": job_id, "status": "running", "stage": "queued"}


@router.get("/job/{job_id}")
def get_job(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        return {"ok": False, "status": "not_found", "job_id": job_id}

    child_job_id = job.get("child_job_id")
    if child_job_id:
        try:
            child = _get_json(f"http://127.0.0.1:8000/api/video/full-ai/job/{child_job_id}", timeout=60)
            merged = dict(job)
            merged["child_job"] = child
            if child.get("status") in {"completed", "succeeded", "success"} or child.get("stage") in {"completed", "succeeded", "success"}:
                merged["status"] = "completed"
                merged["stage"] = "completed"
                merged["progress"] = 100
                for k in ("video_url", "url", "output_url", "result_url"):
                    if child.get(k):
                        merged["video_url"] = child.get(k)
                if isinstance(child.get("result"), dict):
                    for k in ("video_url", "url", "output_url", "result_url"):
                        if child["result"].get(k):
                            merged["video_url"] = child["result"].get(k)
            return merged
        except Exception as exc:
            job["child_poll_error"] = str(exc)

    return job


def install_full_ai_tts_first(app: FastAPI) -> None:
    app.include_router(router)
