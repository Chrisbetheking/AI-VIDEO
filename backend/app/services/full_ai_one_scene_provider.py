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
    visual_mode: str = "single_background_loop"


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
            dur = _first_value(res, ["duration"])
            url = _first_value(res, ["audio_url", "audio", "mp3", "wav", "path"])
            try:
                dur_f = float(dur) if dur is not None else fallback
            except Exception:
                dur_f = fallback
            return max(dur_f, 1.0), str(url or ""), res
        except Exception as exc:
            last = {"ok": False, "error": str(exc)}
    return fallback, "", last


def _prompt(city: str, topic: str, scene: str = "") -> str:
    # V10.13: fixed single background. Do not let fal infer “real-estate brochure / storyboard”.
    base = str(scene or "").strip()
    if not base:
        base = (
            "single uncut vertical 9:16 realistic phone video of one clean modern Kuala Lumpur condominium living room interior, "
            "one full-screen image only, one locked camera angle, slow subtle natural movement, warm daylight, premium but realistic, "
            "no people, no readable text, no skyline landmark, no project name"
        )
    return (
        f"{base}. Only one normal interior background shot filling the whole screen. "
        "Single continuous shot, one camera angle, no cuts, no multiple rooms, no agent, no brochure layout. "
        "Absolutely no montage, no collage, no split screen, no multi-panel, no grid, no storyboard, no picture-in-picture. "
        "No documents, no charts, no calculator, no UI, no screenshots, no readable text, no fake labels. "
        "Do not show KLCC or Petronas Twin Towers, no famous landmark towers, no beach, no island, no ocean."
    )


def _split_subtitle_chunks(script: str, max_chars: int = 12) -> List[str]:
    text = re.sub(r"\s+", " ", str(script or "").strip())
    if not text:
        return []
    # First split by Chinese punctuation, then by commas, then by fixed short chunks.
    rough = [x.strip() for x in re.split(r"(?<=[。！？!?；;])", text) if x.strip()]
    if not rough:
        rough = [text]
    out: List[str] = []
    for part in rough:
        pieces = [x.strip() for x in re.split(r"(?<=[，,、：:])", part) if x.strip()]
        for piece in pieces or [part]:
            piece = piece.strip()
            while len(piece) > max_chars:
                cut = max_chars
                for mark in "，,、 ":
                    pos = piece.rfind(mark, 0, max_chars + 1)
                    if pos >= 6:
                        cut = pos + 1
                        break
                out.append(piece[:cut].strip())
                piece = piece[cut:].strip()
            if piece:
                out.append(piece)
    # Merge tiny fragments but keep TikTok/Douyin short rhythm.
    merged: List[str] = []
    buf = ""
    for part in out:
        if buf and len(buf) + len(part) <= max_chars:
            buf += part
        else:
            if buf:
                merged.append(buf)
            buf = part
    if buf:
        merged.append(buf)
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
            parts = _split_subtitle_chunks(str(cue.get("text") or ""), max_chars=12) or [str(cue.get("text") or "")]
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

    parts = _split_subtitle_chunks(script, max_chars=12)
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


def _loop_with_audio(video_url: str, audio_url: str, duration: float, prefix: str) -> Path:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg 不可用，无法合成单画面视频")
    _ensure()
    bg = _download(video_url, ".mp4")
    audio = _download(audio_url, ".mp3") if audio_url.startswith("http") else Path(audio_url)
    if not audio.exists():
        raise RuntimeError(f"TTS 音频不存在或不可下载: {audio_url}")
    out = WORK_DIR / f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.mp4"
    # Loop one generated visual behind the whole audio. This avoids multiple-shot/collage failure entirely.
    vf = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30"
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-stream_loop", "-1", "-i", str(bg),
        "-i", str(audio),
        "-t", str(round(float(duration) + 0.12, 2)),
        "-map", "0:v:0", "-map", "1:a:0",
        "-vf", vf,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest", "-movflags", "+faststart",
        str(out),
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=900)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or "one-scene ffmpeg compose failed")
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

        prompt = _prompt(str(raw.get("city") or ""), title, str(raw.get("background_scene") or ""))
        print("ONE_SCENE_PROMPT=" + prompt[:600], flush=True)
        start = _post_json("http://127.0.0.1:8000/api/video/fal/shot/start", {
            "prompt": prompt,
            "duration_seconds": 5.0,
            "duration": 5.0,
            "width": 1080,
            "height": 1920,
            "fps": int(raw.get("fps") or 30),
            "negative_prompt": "collage, split screen, multi panel, grid, brochure, poster, storyboard, picture in picture, documents, charts, calculator, readable text, KLCC, Petronas Twin Towers",
        }, timeout=120)
        fid = start.get("job_id") or start.get("id") or (start.get("data") or {}).get("job_id")
        if not fid:
            raise RuntimeError(f"fal one-scene did not return job_id: {start}")
        fal_done = _poll_fal(str(fid), timeout_s=1200)
        bg_url = _video_url(fal_done)
        if not bg_url:
            raise RuntimeError(f"fal one-scene failed/no video_url: {fal_done}")
        job.update({"stage": "compose_one_scene", "progress": 70, "background_video_url": bg_url, "fal_result": fal_done, "updated_at": time.time()}); _persist(job_id)

        composed_path = _loop_with_audio(bg_url, audio_url, audio_dur, prefix=job_id)
        raw_upload = upload_file_to_r2(composed_path, object_key=f"videos/one-scene/raw/{time.strftime('%Y/%m/%d')}/{composed_path.name}")
        raw_url = raw_upload.get("url") or ""

        final_url = raw_url
        subtitle_res: Dict[str, Any] = {}
        if bool(raw.get("burn_subtitles", True)):
            job.update({"stage": "subtitle_burn_exact_script", "progress": 88, "raw_video_url": raw_url, "updated_at": time.time()}); _persist(job_id)
            cues = _subtitle_cues(script, float(audio_dur), tts_res)
            subtitle_res = burn_subtitles_with_style_and_upload(
                video_path=str(composed_path),
                text=script,
                segments=cues,
                duration=float(audio_dur),
                style_id=str(raw.get("subtitle_style_id") or "douyin_pop"),
                prefix=f"one_scene_{job_id}",
                object_key=f"videos/one-scene/subtitled/{time.strftime('%Y/%m/%d')}/{uuid.uuid4().hex}_{job_id}.mp4",
            )
            final_url = str(subtitle_res.get("video_url") or raw_url)

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
            "thumbnail_result": thumb,
            "single_scene": True,
            "shot_count": 1,
            "updated_at": time.time(),
        }); _persist(job_id)
    except Exception as exc:
        job.update({"ok": False, "status": "failed", "stage": "failed", "progress": 100, "error": str(exc), "updated_at": time.time()}); _persist(job_id)


@router.get("/health")
def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "provider": "full_ai_one_scene_v10_13",
        "single_scene": True,
        "shot_count": 1,
        "loop_visual_to_audio": True,
        "exact_script_subtitles": True,
        "douyin_subtitle_styles": True,
        "short_chunk_subtitle_timing": True,
        "no_multi_shots": True,
    }


@router.post("/start")
def start(req: StartReq) -> Dict[str, Any]:
    job_id = "one_scene_" + uuid.uuid4().hex[:18]
    raw = req.model_dump()
    _jobs[job_id] = {"ok": True, "job_id": job_id, "job_type": "one_scene", "status": "running", "stage": "queued", "progress": 1, "created_at": time.time(), "updated_at": time.time(), "request": raw}
    _persist(job_id)
    threading.Thread(target=_run, args=(job_id, raw), daemon=True).start()
    return {"ok": True, "job_id": job_id, "status": "running", "stage": "queued", "single_scene": True, "message": "已启动 V10.13 单画面视频：一个背景画面 + 抖音大字字幕 + 按 TTS 实际时长切字幕。"}


@router.get("/job/{job_id}")
def get_job(job_id: str) -> Dict[str, Any]:
    return dict(_jobs.get(job_id) or {"ok": False, "job_id": job_id, "status": "not_found"})


def install_full_ai_one_scene(app: FastAPI) -> None:
    app.include_router(router)
