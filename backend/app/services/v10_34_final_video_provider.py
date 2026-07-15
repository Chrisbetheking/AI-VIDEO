from __future__ import annotations

"""V10.34 final video provider: no-hang FAL pipeline.

Key production guarantees:
- Does not call the old /api/video/fal/storyboard/start aggregator, because that can hide
  a blocking FAL child task and keep the parent full_ai job running forever.
- Generates FAL shot-by-shot with hard per-shot and total timeouts.
- Fails loudly with shot-level metadata if no raw_clip/video_url is produced.
- Preserves semantic per-shot prompts and uses FFmpeg subtitle burn + crossfade compose.
"""

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

import cv2
import requests

from fastapi import FastAPI, Request
from starlette.responses import JSONResponse

from app.services.integration_hub_v10_40_7 import extract_frames, text_score, watermark_score
from app.services.subtitle_style_library_provider import burn_subtitles_with_style_and_upload

try:
    from app.services.v10_34_production_provider import (
        SAFE_TRANSITION,
        negative_prompt,
        sanitize_shots_for_fal,
        save_raw_fal_shot,
        semantic_shot_plan,
        validate_completed,
        json_dir,
    )
except Exception:  # pragma: no cover
    SAFE_TRANSITION = "smooth_dissolve_no_flash"
    def negative_prompt(existing: str = "") -> str:
        return (existing + ", cut, flash, hard transition, text, watermark").strip(", ")
    def sanitize_shots_for_fal(shots: List[dict], title: str = "") -> List[dict]:
        return shots
    def save_raw_fal_shot(parent_job_id: str, idx: int, shot: dict, video_url: str, fal_result: dict | None = None) -> dict:
        return {"ok": True, "raw_clip": video_url, "raw_clip_url": video_url, "prompt": shot.get("prompt", "")}
    def semantic_shot_plan(payload: dict) -> dict:
        return {"ok": True, "shots": payload.get("shots") or []}
    def validate_completed(job: dict) -> dict:
        return {"ok": True, "errors": []}
    def json_dir() -> Path:
        p = Path("/opt/ai-video/storage/v10_34")
        p.mkdir(parents=True, exist_ok=True)
        return p


JOBS: Dict[str, Dict[str, Any]] = {}
FINAL_VERSION = "v10.40.7-engine-source-fix"

MAX_FAL_SHOTS = max(10, min(12, int(os.getenv("AI_VIDEO_MAX_FAL_SHOTS", "12"))))
FAL_PER_SHOT_TIMEOUT = max(60, int(os.getenv("AI_VIDEO_FAL_PER_SHOT_TIMEOUT_SECONDS", "360")))
FAL_TOTAL_TIMEOUT = max(1800, int(os.getenv("AI_VIDEO_FAL_TOTAL_TIMEOUT_SECONDS", "2700")))
FAL_POLL_INTERVAL = max(3, int(os.getenv("AI_VIDEO_FAL_POLL_INTERVAL_SECONDS", "5")))
STALE_JOB_TIMEOUT = max(300, int(os.getenv("AI_VIDEO_STALE_JOB_TIMEOUT_SECONDS", "900")))

BLOCKED_PROMPT_TERMS = re.compile(r"\b(cut|smooth_cut|flash|hard cut|quick cut|hard transition|pull_out|pull out|jump cut|white flash)\b", re.I)

CAMERA_MOVES = [
    "slow dolly-in toward the entrance or room focal point, stable gimbal motion",
    "smooth lateral tracking from left to right, one steady movement",
    "smooth lateral tracking from right to left, one steady movement",
    "gentle tilt-down from building facade to entrance, controlled movement",
    "slow push-through along corridor or lobby path, natural parallax",
    "slow pull-back revealing the wider room, not a transition",
    "locked-off shot with subtle natural human motion and depth",
]

SCENE_MAP = [
    ("生活配套", ["生活", "配套", "超市", "商超", "诊所", "医院", "餐饮", "吃饭", "咖啡", "花费", "消费", "便利"], "neighborhood convenience around a Kuala Lumpur residential community: cafe, supermarket entrance, clinic exterior, everyday residents walking, no readable signs"),
    ("交通出勤", ["交通", "出勤", "通勤", "地铁", "捷运", "MRT", "LRT", "公交", "开车", "路程"], "daily commute near a condo: residential driveway, cars moving slowly, people walking toward transit, street-level Kuala Lumpur context"),
    ("教育家庭", ["教育", "学校", "孩子", "留学", "国际学校", "陪读", "华语", "华人区"], "family living atmosphere: parents and child walking in a clean residential neighborhood, school-zone feeling without readable school names"),
    ("户型采光", ["户型", "采光", "客厅", "卧室", "厨房", "阳台", "大堂", "泳池", "健身房", "动线"], "condo interior and amenities: bright living room, bedroom, kitchen, balcony greenery, lobby, pool or gym, one location only"),
    ("区域地段", ["吉隆坡", "新山", "槟城", "森林城市", "区域", "地段", "KL", "Kuala"], "ordinary Malaysian city residential context: condo entrance, neighborhood amenities, street-level high-rise residential area, not repeating iconic towers"),
    ("租售投资", ["出租", "租金", "租客", "投资", "回报", "流动性", "转手", "资产", "150万", "预算", "长期", "价值", "长持"], "property viewing and rental lifestyle: agent showing apartment, clean lobby, balcony city view, quality residential details"),
    ("承接咨询", ["私信", "评论", "咨询", "了解", "留言", "评论区", "开销", "价值"], "consultation handoff: real estate advisor speaking with client in a condo lobby or viewing room, friendly service atmosphere"),
]


def _admin_headers() -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    try:
        token = Path("/root/ai-video-admin-token.txt").read_text(encoding="utf-8").strip()
        if token:
            headers["X-AI-Video-Token"] = token
    except Exception:
        pass
    return headers


def _post_json(path: str, payload: Dict[str, Any], timeout: int = 300) -> Dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urlrequest.Request("http://127.0.0.1:8000" + path, data=body, headers=_admin_headers(), method="POST")
    with urlrequest.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw or "{}")


def _get_json(path: str, timeout: int = 60) -> Dict[str, Any]:
    req = urlrequest.Request("http://127.0.0.1:8000" + path, headers=_admin_headers(), method="GET")
    with urlrequest.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw or "{}")


def _ffprobe_duration(path_or_url: str, default: float = 0.0) -> float:
    if not path_or_url:
        return default
    try:
        cp = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path_or_url)
        ], capture_output=True, text=True, timeout=45)
        if cp.returncode == 0:
            data = json.loads(cp.stdout or "{}")
            val = float((data.get("format") or {}).get("duration") or 0)
            if val > 0:
                return val
    except Exception:
        pass
    return default


def _sanitize_script_text(value: Any) -> str:
    """One canonical clean text for copy, TTS, subtitles and shot narration."""
    text = str(value or "")
    text = re.sub(r"\\(?:N|n|r|t)", "，", text)
    text = text.replace("\r", "，").replace("\n", "，").replace("\t", " ")
    text = re.sub(r"[／/\\|｜]+", "，", text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[，,]{2,}", "，", text)
    text = re.sub(r"[。．]{2,}", "。", text)
    text = re.sub(r"，([。！？；])", r"\1", text)
    text = re.sub(r"([。！？；])，", r"\1", text)
    return text.strip("，。 ")


def _target_shot_count(audio_duration: float) -> int:
    duration = max(1.0, float(audio_duration or 20.0))
    return max(4, min(MAX_FAL_SHOTS, int(math.ceil(duration / 4.0))))


SCENE_LABEL_EN = {
    "生活配套": "neighborhood daily life",
    "交通出勤": "daily commute",
    "教育家庭": "family and education lifestyle",
    "户型采光": "apartment interior and daylight",
    "区域地段": "residential neighborhood context",
    "租售投资": "property viewing and rental lifestyle",
    "承接咨询": "real estate consultation",
    "语义带看": "property viewing lifestyle",
}

SCENE_VISUAL_VARIANTS = {
    "生活配套": [
        "residents walking through a clean condominium retail courtyard with cafe seating and greenery, no signs",
        "a family carrying groceries through a modern residential lobby, natural daily-life motion",
        "a quiet neighborhood walkway beside a condominium with trees and everyday residents",
    ],
    "交通出勤": [
        "residents leaving a condominium driveway during a normal morning commute, cars moving slowly",
        "a pedestrian walking from a residential entrance toward urban transit, no station signs",
        "street-level residential traffic near a Kuala Lumpur condominium, stable realistic movement",
    ],
    "教育家庭": [
        "parents and a child walking through a safe residential courtyard, no school branding",
        "a family discussing daily plans in a bright apartment dining area",
        "parents preparing a child for the day inside a modern family apartment",
    ],
    "户型采光": [
        "a bright modern apartment living room with large windows and natural daylight",
        "a clean condominium kitchen and dining area with realistic residential details",
        "a calm apartment balcony with greenery and a generic Kuala Lumpur residential view",
        "a modern condominium bedroom with warm daylight and uncluttered styling",
    ],
    "区域地段": [
        "an ordinary Kuala Lumpur high-rise residential street with trees and pedestrian activity",
        "a condominium entrance and drop-off area in a real Malaysian residential neighborhood",
        "a landscaped residential courtyard surrounded by modern apartment buildings",
    ],
    "租售投资": [
        "a real estate advisor showing a clean apartment living room to a client",
        "a tenant viewing a condominium kitchen and balcony with an advisor",
        "a property inspection scene focused on room quality and practical details",
    ],
    "承接咨询": [
        "a real estate advisor and client having a friendly discussion in a clean condominium lounge",
        "an advisor explaining a home viewing to a couple in a bright apartment",
        "a professional consultation at a residential lobby seating area",
    ],
    "语义带看": [
        "a smooth walk-through of a clean modern condominium interior",
        "an advisor opening the door and guiding a client into a bright apartment",
        "a realistic residential lobby and amenity area with natural people movement",
    ],
}


def _visual_for_scene(scene_type: str, index: int, fallback: str = "") -> str:
    choices = SCENE_VISUAL_VARIANTS.get(scene_type) or SCENE_VISUAL_VARIANTS["语义带看"]
    return choices[(max(1, index) - 1) % len(choices)] or fallback


def _expand_shots_to_target(shots: List[Dict[str, Any]], audio_duration: float, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    target = _target_shot_count(audio_duration)
    if not shots:
        return []
    topic = str(payload.get("topic") or payload.get("title") or "Malaysia property")
    city = str(payload.get("city") or "Kuala Lumpur")
    each = round(float(audio_duration or 20.0) / target, 2)
    expanded: List[Dict[str, Any]] = []
    for pos in range(target):
        source_index = min(len(shots) - 1, int(pos * len(shots) / target))
        source = dict(shots[source_index])
        narration = _sanitize_script_text(source.get("narration_segment") or source.get("narration") or source.get("text") or "")
        scene_type, fallback_visual = _scene_for_text(narration)
        scene_type = str(source.get("scene_type") or scene_type)
        visual = _visual_for_scene(scene_type, pos + 1, str(source.get("scene") or fallback_visual))
        prompt = _build_prompt(pos + 1, topic, city, narration, scene_type, visual)
        source.update({
            "id": f"engine_shot_{pos + 1}",
            "index": pos + 1,
            "scene_type": scene_type,
            "scene": visual,
            "narration": narration,
            "narration_segment": narration,
            "duration": each,
            "duration_seconds": each,
            "source": "ai",
            "camera": _motion_for_shot(pos + 1, scene_type),
            "transition": SAFE_TRANSITION,
            "prompt": prompt,
            "visual_prompt": prompt,
            "negative_prompt": negative_prompt(
                "subtitles, captions, readable text, pseudo text, gibberish letters, logo, watermark, avatar, "
                "price tag, signboard, poster, document, chart, calculator, UI, split screen, collage, hard cut, flash"
            ),
            "asset_ids": [],
        })
        expanded.append(source)
    return sanitize_shots_for_fal(expanded, topic)


def _download_generated_clip(url: str, job_id: str, shot_index: int, attempt: int) -> Path:
    root = Path(os.getenv("AI_VIDEO_BASE", "/opt/ai-video")) / "storage" / "v10_40_7" / "shot_audits" / job_id
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"shot_{shot_index:02d}_attempt_{attempt}.mp4"
    with requests.get(url, stream=True, timeout=240) as response:
        response.raise_for_status()
        with target.open("wb") as handle:
            for chunk in response.iter_content(1024 * 1024):
                if chunk:
                    handle.write(chunk)
    if not target.exists() or target.stat().st_size < 1024:
        raise RuntimeError("生成镜头下载后为空")
    return target


def _audit_generated_clip(path: Path, job_id: str, shot_index: int, attempt: int) -> Dict[str, Any]:
    frames_dir = path.parent / f"shot_{shot_index:02d}_attempt_{attempt}_frames"
    frames, info = extract_frames(path, frames_dir, 6)
    text_scores: List[float] = []
    text_frames: List[Dict[str, Any]] = []
    images = []
    for frame in frames:
        image = cv2.imread(str(frame))
        if image is None:
            continue
        images.append(image)
        score, regions = text_score(image, allow_bottom=False)
        text_scores.append(float(score))
        if score >= 0.48:
            text_frames.append({"frame": str(frame), "score": round(float(score), 4), "regions": regions[:8]})
    ordered = sorted(text_scores)
    percentile = ordered[min(len(ordered) - 1, int(len(ordered) * 0.75))] if ordered else 0.0
    water = watermark_score(images) if images else {"score": 0.0}
    water_value = float(water.get("score") or 0.0)
    reasons = []
    if percentile >= 0.48:
        reasons.append("镜头疑似包含模型生成字幕、标题或乱码")
    if water_value >= 0.42:
        reasons.append("镜头疑似包含固定头像、Logo 或水印")
    return {
        "ok": True,
        "job_id": job_id,
        "shot_index": shot_index,
        "attempt": attempt,
        "path": str(path),
        "duration": info.get("duration"),
        "passed": not reasons,
        "embedded_text_score": round(percentile, 4),
        "watermark_score": round(water_value, 4),
        "text_frames": text_frames,
        "watermark": water,
        "reasons": reasons,
        "frame_paths": [str(item) for item in frames],
    }


def _retry_prompt(shot: Dict[str, Any], index: int, attempt: int) -> str:
    scene_type = str(shot.get("scene_type") or "语义带看")
    visual = _visual_for_scene(scene_type, index + attempt - 1, str(shot.get("scene") or ""))
    camera = _motion_for_shot(index + attempt - 1, scene_type)
    if attempt >= 3:
        visual = (
            "a clean modern condominium interior with natural daylight, plain walls, unbranded furniture, "
            "an advisor and client moving naturally, no signs or display screens"
        )
        camera = "locked-off stable shot with subtle natural human motion"
    return (
        "Vertical 9:16 photorealistic cinematic real-estate B-roll in Malaysia. "
        f"Main subject: {visual}. Camera: {camera}. "
        "One continuous full-screen camera shot, realistic natural lighting, clean architectural surfaces, "
        "ordinary people moving naturally, no montage and no split screen. "
        "Every visible surface is blank and unbranded; there are no signs, screens, posters, labels, letters, "
        "numbers, captions, subtitles, logos, watermarks, avatars, stickers, documents or pseudo-text."
    )


def _collect_keywords(payload: Dict[str, Any], shots: List[Dict[str, Any]]) -> List[str]:
    values: List[str] = []
    for key in ("keywords", "manual_keywords", "selected_keywords"):
        raw = payload.get(key)
        if isinstance(raw, str):
            values.extend(re.split(r"[,，、\s]+", raw))
        elif isinstance(raw, list):
            values.extend(str(item) for item in raw)
    for key in ("keyword_insights", "ai_keyword_insights"):
        for item in payload.get(key) or []:
            if isinstance(item, dict):
                values.append(str(item.get("value") or item.get("keyword") or ""))
            else:
                values.append(str(item))
    for shot in shots:
        for item in shot.get("highlight_keywords") or shot.get("keywords") or []:
            values.append(str(item.get("value") if isinstance(item, dict) else item))
    clean: List[str] = []
    seen = set()
    for value in values:
        item = _sanitize_script_text(value)
        if not item or re.fullmatch(r"(?:ai_)?kw_?\d+|(?:region|区域|人群|keyword)_?\d+|.+_id", item, re.I):
            continue
        if 2 <= len(item) <= 10 and item.lower() not in seen:
            seen.add(item.lower())
            clean.append(item)
    return clean[:24]

def _extract_script(payload: Dict[str, Any]) -> str:
    for key in ("script_text", "script", "copy", "text", "narration"):
        value = _sanitize_script_text(payload.get(key))
        if value:
            return value
    parts = []
    for item in payload.get("segments") or []:
        if isinstance(item, dict):
            value = _sanitize_script_text(item.get("text") or item.get("narration") or item.get("narration_segment"))
            if value:
                parts.append(value)
    return "。".join(parts)

def _split_segments(script: str, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for item in payload.get("segments") or []:
        if isinstance(item, dict):
            clean = _sanitize_script_text(item.get("text") or item.get("narration") or item.get("narration_segment"))
            if clean:
                next_item = dict(item)
                next_item["text"] = clean
                next_item["narration"] = clean
                next_item["narration_segment"] = clean
                out.append(next_item)
    if out:
        return out
    clean_script = _sanitize_script_text(script)
    parts = [item.strip() for item in re.split(r"[。！？!?；;]+", clean_script) if item.strip()]
    return [{"text": item, "narration": item, "narration_segment": item} for item in parts] or [{"text": clean_script or "马来西亚房产内容"}]

def _scene_for_text(text: str) -> tuple[str, str]:
    lower = text.lower()
    for scene_type, keys, visual in SCENE_MAP:
        if any(str(k).lower() in lower or str(k) in text for k in keys):
            return scene_type, visual
    return "语义带看", "real estate viewing sequence: agent showing condo interior, residential lobby, street-level neighborhood context, natural lifestyle details"


def _motion_for_shot(index: int, scene_type: str) -> str:
    if scene_type in {"交通出勤", "生活配套"}:
        return CAMERA_MOVES[(index + 1) % len(CAMERA_MOVES)]
    if scene_type == "户型采光":
        return CAMERA_MOVES[(index + 4) % len(CAMERA_MOVES)]
    return CAMERA_MOVES[(index - 1) % len(CAMERA_MOVES)]


def _build_prompt(index: int, topic: str, city: str, segment: str, scene_type: str, visual: str) -> str:
    camera = _motion_for_shot(index, scene_type)
    city_en = "Kuala Lumpur" if any(item in str(city).lower() for item in ("吉隆坡", "kuala", "kl")) else "Malaysia"
    category = SCENE_LABEL_EN.get(scene_type, "residential lifestyle")
    visual = _visual_for_scene(scene_type, index, visual)
    prompt = f"""Vertical 9:16 photorealistic cinematic Malaysia real-estate B-roll.
Location context: {city_en}.
Scene category: {category}.
Main subject: {visual}.
Camera: {camera}.
One continuous full-screen shot with stable movement, realistic natural lighting, clean depth and ordinary residential detail.
Every visible surface is blank and unbranded. The scene contains no signs, screens, posters, labels, letters, numbers, captions, subtitles, logos, watermarks, avatars, stickers, documents, charts, calculators, UI or pseudo-text.
No montage, split screen, collage, flash, black frame or iconic skyline repetition.
""".strip()
    return BLOCKED_PROMPT_TERMS.sub("continuous camera movement", prompt)

def _fallback_semantic_shots(payload: Dict[str, Any], audio_duration: float) -> List[Dict[str, Any]]:
    script = _extract_script(payload)
    segments = _split_segments(script, payload)
    base: List[Dict[str, Any]] = []
    for index, segment in enumerate(segments, 1):
        narration = _sanitize_script_text(segment.get("text"))
        scene_type, visual = _scene_for_text(narration)
        base.append({
            "id": f"semantic_source_{index}",
            "index": index,
            "scene_type": scene_type,
            "scene": visual,
            "narration": narration,
            "narration_segment": narration,
            "highlight_keywords": segment.get("highlight_keywords") or segment.get("keywords") or [],
        })
    return _expand_shots_to_target(base, audio_duration, payload)

def _semantic_shots(payload: Dict[str, Any], audio_duration: float) -> List[Dict[str, Any]]:
    sem_payload = dict(payload)
    sem_payload["script"] = _extract_script(payload)
    sem_payload["script_text"] = sem_payload["script"]
    sem_payload["segments"] = _split_segments(sem_payload["script"], payload)
    sem_payload["target_duration_seconds"] = audio_duration
    sem_payload["duration_seconds"] = audio_duration
    sem_payload["target_shot_count"] = _target_shot_count(audio_duration)
    try:
        data = _post_json("/api/video/v10-34/semantic-shots", sem_payload, timeout=120)
        shots = data.get("shots") or data.get("shot_plan") or []
        if isinstance(shots, list) and shots:
            fixed: List[Dict[str, Any]] = []
            for index, shot in enumerate(shots, 1):
                if not isinstance(shot, dict):
                    continue
                narration = _sanitize_script_text(shot.get("narration_segment") or shot.get("narration") or shot.get("text"))
                scene_type, visual = _scene_for_text(narration)
                item = dict(shot)
                item.update({
                    "index": index,
                    "scene_type": item.get("scene_type") or scene_type,
                    "scene": item.get("scene") or visual,
                    "narration": narration,
                    "narration_segment": narration,
                })
                fixed.append(item)
            if fixed:
                return _expand_shots_to_target(fixed, audio_duration, payload)
    except Exception as exc:
        print("V10407_SEMANTIC_SHOTS_FALLBACK=" + str(exc)[:1000])
    return _fallback_semantic_shots(payload, audio_duration)

def _merge_generation_shots(shots: List[Dict[str, Any]], audio_duration: float, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Preserve the duration-based target count instead of collapsing a 30s video to five long shots."""
    return _expand_shots_to_target(shots, audio_duration, payload) if shots else []

def _tts(script: str, payload: Dict[str, Any]) -> tuple[str, float, Dict[str, Any]]:
    clean_script = _sanitize_script_text(script)
    clean_segments = _split_segments(clean_script, payload)
    tts_payload = {
        "text": clean_script,
        "segments": clean_segments,
        "voice": payload.get("voice") or "default",
        "overall_rate": payload.get("overall_rate") or "+0%",
    }
    data = _post_json("/api/tts-segments", tts_payload, timeout=300)
    for key in ("segments", "tts_segments", "items", "cues", "timeline"):
        if isinstance(data.get(key), list):
            for item in data[key]:
                if isinstance(item, dict):
                    item["text"] = _sanitize_script_text(item.get("text") or item.get("line") or item.get("sentence"))
    audio_url = data.get("file_url") or data.get("audio_url") or data.get("url") or ""
    duration = float(data.get("duration_seconds") or data.get("audio_duration_seconds") or 0 or 0)
    if not duration:
        duration = _ffprobe_duration(audio_url, default=max(5.0, len(clean_script) / 4.6))
    if not audio_url:
        raise RuntimeError("TTS 没有返回 audio_url/file_url，不能继续生成视频")
    return audio_url, duration, data

def _extract_video_url(data: Dict[str, Any]) -> str:
    if not isinstance(data, dict):
        return ""
    for key in ("video_url", "output_url", "url"):
        if isinstance(data.get(key), str) and data.get(key):
            return data[key]
    result = data.get("result")
    if isinstance(result, dict):
        for key in ("video_url", "output_url", "url"):
            if isinstance(result.get(key), str) and result.get(key):
                return result[key]
        if isinstance(result.get("video"), dict) and result["video"].get("url"):
            return result["video"]["url"]
    return ""


def _save_job_snapshot(job_id: str) -> None:
    try:
        d = json_dir() / "final_jobs"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{job_id}.json").write_text(json.dumps(JOBS.get(job_id, {}), ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _fail_job(job: Dict[str, Any], code: str, detail: str, stage: str = "failed") -> None:
    job.update({
        "ok": False,
        "status": "failed",
        "stage": stage,
        "message": detail,
        "error": {"code": code, "detail": detail, "safe_to_retry": True, "should_retry": True},
        "progress": min(int(job.get("progress") or 0), 99),
        "updated_at": time.time(),
    })


def _poll_fal_shot(parent_job_id: str, fal_job_id: str, idx: int, total: int, per_shot_timeout: int, total_deadline: float) -> Dict[str, Any]:
    job = JOBS[parent_job_id]
    deadline = min(time.time() + per_shot_timeout, total_deadline)
    last: Dict[str, Any] = {}
    polls = 0
    while time.time() < deadline:
        polls += 1
        try:
            last = _get_json(f"/api/video/fal/job/{fal_job_id}", timeout=75)
        except Exception as exc:
            last = {"ok": False, "status": "poll_error", "error": str(exc)}
        status = str(last.get("status") or last.get("stage") or "").lower()
        elapsed = round(time.time() - float(job.get("fal_started_at") or time.time()), 1)
        job.update({
            "stage": "fal_shot_generating",
            "message": f"正在生成第 {idx}/{total} 个 AI 画面镜头",
            "current_fal_job_id": fal_job_id,
            "current_shot": idx,
            "total_shots": total,
            "progress": min(68, 45 + int(22 * (idx - 1) / max(1, total))),
            "fal_elapsed_seconds": elapsed,
            "updated_at": time.time(),
        })
        job.setdefault("fal_poll_tail", [])
        job["fal_poll_tail"] = (job["fal_poll_tail"] + [{"shot": idx, "polls": polls, "status": status, "fal_job_id": fal_job_id, "time": time.time()}])[-12:]
        _save_job_snapshot(parent_job_id)
        if status in {"done", "completed", "succeeded", "success"}:
            video_url = _extract_video_url(last)
            if not video_url:
                return {"ok": False, "status": "failed", "code": "FAL_DONE_WITHOUT_VIDEO_URL", "detail": "FAL 子任务完成但没有 video_url/raw_clip", "last": last, "fal_job_id": fal_job_id}
            return {"ok": True, "status": "done", "video_url": video_url, "last": last, "fal_job_id": fal_job_id}
        if status in {"failed", "error", "timeout", "not_found"}:
            return {"ok": False, "status": status, "code": "FAL_SHOT_FAILED", "detail": str(last)[:1200], "last": last, "fal_job_id": fal_job_id}
        time.sleep(FAL_POLL_INTERVAL)
    return {"ok": False, "status": "timeout", "code": "FAL_SHOT_TIMEOUT", "detail": f"FAL 第 {idx}/{total} 镜头超过 {per_shot_timeout}s 未产出 raw_clip", "last": last, "fal_job_id": fal_job_id}


def _generate_fal_shots(job_id: str, shots: List[Dict[str, Any]], payload: Dict[str, Any]) -> List[str]:
    job = JOBS[job_id]
    video_urls: List[str] = []
    raw_records: List[Dict[str, Any]] = []
    shot_records: List[Dict[str, Any]] = []
    shot_audits: List[Dict[str, Any]] = []
    total = len(shots)
    total_deadline = time.time() + FAL_TOTAL_TIMEOUT
    job["fal_started_at"] = time.time()
    job["fal_generation_mode"] = "shot_by_shot_visual_audit_retry"
    job["fal_timeout_policy"] = {
        "per_shot_seconds": FAL_PER_SHOT_TIMEOUT,
        "total_seconds": FAL_TOTAL_TIMEOUT,
        "max_fal_shots": MAX_FAL_SHOTS,
        "max_attempts_per_shot": 3,
    }

    for idx, shot in enumerate(shots, start=1):
        accepted_url = ""
        accepted_record: Dict[str, Any] = {}
        for attempt in range(1, 4):
            if time.time() >= total_deadline:
                raise RuntimeError(f"FAL 总超时：{FAL_TOTAL_TIMEOUT}s 内没有完成全部镜头")
            prompt = _retry_prompt(shot, idx, attempt)
            shot_payload = {
                "prompt": prompt,
                "mode": payload.get("mode") or "quick",
                "image_url": shot.get("image_url") or None,
                "resolution": payload.get("resolution") or "720p",
                "num_frames": int(payload.get("num_frames") or 81),
                "frames_per_second": int(payload.get("frames_per_second") or 16),
                "negative_prompt": negative_prompt(
                    "subtitles, captions, readable text, pseudo text, gibberish letters, logo, watermark, avatar, "
                    "signboard, poster, price, numbers, document, chart, calculator, UI, split screen, collage, flash"
                ),
                "video_quality": payload.get("video_quality") or "high",
                "video_write_mode": payload.get("video_write_mode") or "balanced",
            }
            job.update({
                "stage": "fal_shot_start",
                "message": f"生成并检查第 {idx}/{total} 个镜头，第 {attempt}/3 次",
                "current_shot_prompt": prompt,
                "current_shot_attempt": attempt,
                "updated_at": time.time(),
            })
            _save_job_snapshot(job_id)
            start = _post_json("/api/video/fal/shot/start", shot_payload, timeout=45)
            fal_job_id = start.get("job_id")
            if not fal_job_id:
                raise RuntimeError("FAL shot/start 没有返回 job_id：" + str(start)[:1000])
            rec = {
                "index": idx,
                "attempt": attempt,
                "fal_job_id": fal_job_id,
                "prompt": prompt,
                "negative_prompt": shot_payload["negative_prompt"],
                "scene_type": shot.get("scene_type"),
                "narration_segment": shot.get("narration_segment"),
                "duration": shot.get("duration") or shot.get("duration_seconds"),
                "transition": SAFE_TRANSITION,
                "status": "running",
                "start_response": start,
                "started_at": time.time(),
            }
            shot_records.append(rec)
            job["fal_shot_records"] = shot_records
            _save_job_snapshot(job_id)
            polled = _poll_fal_shot(job_id, fal_job_id, idx, total, FAL_PER_SHOT_TIMEOUT, total_deadline)
            rec.update({"poll_result": polled, "finished_at": time.time(), "elapsed_seconds": round(time.time() - rec["started_at"], 1)})
            if not polled.get("ok"):
                rec["status"] = "generation_failed"
                continue
            video_url = str(polled.get("video_url") or "")
            try:
                local_clip = _download_generated_clip(video_url, job_id, idx, attempt)
                audit = _audit_generated_clip(local_clip, job_id, idx, attempt)
            except Exception as exc:
                audit = {"ok": False, "passed": False, "shot_index": idx, "attempt": attempt, "reasons": [f"镜头下载或审查失败：{exc}"]}
            rec["visual_audit"] = audit
            shot_audits.append(audit)
            job["shot_visual_audits"] = shot_audits
            if not audit.get("passed"):
                rec["status"] = "visual_rejected"
                _save_job_snapshot(job_id)
                continue
            rec.update({"status": "done", "video_url": video_url, "raw_clip": video_url})
            accepted_url = video_url
            accepted_record = save_raw_fal_shot(job_id, idx, shot, video_url, polled.get("last") if isinstance(polled.get("last"), dict) else {})
            break
        if not accepted_url:
            reasons = [reason for audit in shot_audits if int(audit.get("shot_index") or 0) == idx for reason in audit.get("reasons") or []]
            raise RuntimeError(f"第 {idx}/{total} 个镜头连续三次出现字幕、水印或审查失败：" + "；".join(reasons[-3:]))
        raw_records.append(accepted_record)
        video_urls.append(accepted_url)
        job.update({
            "fal_shot_records": shot_records,
            "shot_visual_audits": shot_audits,
            "raw_shots": raw_records,
            "video_urls": video_urls,
            "progress": min(70, 48 + int(22 * idx / max(1, total))),
            "updated_at": time.time(),
        })
        _save_job_snapshot(job_id)
    if len(video_urls) != total:
        raise RuntimeError("不是所有镜头都通过单镜头画面审查，停止合成")
    return video_urls

def _poll(path_template: str, job_id: str, timeout_seconds: int, interval: int = 4) -> Dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last: Dict[str, Any] = {}
    while time.time() < deadline:
        last = _get_json(path_template.format(job_id=job_id), timeout=90)
        status = str(last.get("status") or last.get("stage") or "").lower()
        if status in {"done", "failed", "completed", "succeeded", "success", "error", "timeout"}:
            return last
        time.sleep(interval)
    return {"ok": False, "status": "timeout", "last": last, "job_id": job_id}


def _run_final_job(job_id: str, payload: Dict[str, Any]) -> None:
    job = JOBS[job_id]
    try:
        script = _extract_script(payload)
        if not script or len(script) < 3:
            raise RuntimeError("没有口播稿，不能生成视频")

        job.update({"stage": "tts", "message": "正在生成/读取口播音频", "progress": 12, "updated_at": time.time()})
        _save_job_snapshot(job_id)
        audio_url, audio_duration, tts_result = _tts(script, payload)
        job.update({"audio_url": audio_url, "audio_duration_seconds": round(audio_duration, 2), "tts_result": tts_result, "progress": 25, "updated_at": time.time()})
        _save_job_snapshot(job_id)

        job.update({"stage": "semantic_shots", "message": "DeepSeek/语义导演正在按口播重建镜头和提示词", "progress": 32, "updated_at": time.time()})
        _save_job_snapshot(job_id)
        semantic_shots = _semantic_shots(payload, audio_duration)
        if not semantic_shots:
            raise RuntimeError("语义镜头为空，不能触发 FAL 烧钱")
        fal_shots = _merge_generation_shots(semantic_shots, audio_duration, payload)
        if not fal_shots:
            raise RuntimeError("FAL 镜头为空，不能触发生成")
        job.update({"shots": semantic_shots, "fal_shots": fal_shots, "shot_count": len(semantic_shots), "fal_shot_count": len(fal_shots), "target_shot_count": _target_shot_count(audio_duration), "progress": 40, "updated_at": time.time()})
        _save_job_snapshot(job_id)

        job.update({"stage": "fal_shot_generating", "message": "正在逐镜头生成 AI 画面；已禁用旧 storyboard 聚合器", "progress": 45, "updated_at": time.time()})
        _save_job_snapshot(job_id)
        video_urls = _generate_fal_shots(job_id, fal_shots, payload)
        if not video_urls:
            raise RuntimeError("FAL 没有 raw_clip/video_url，不能 completed")

        job.update({"stage": "compose_crossfade", "message": "正在用叠化/crossfade 合成，避免闪屏硬切", "progress": 76, "updated_at": time.time()})
        _save_job_snapshot(job_id)
        compose_payload = {
            "title": payload.get("title") or payload.get("topic") or "AI 视频",
            "video_urls": video_urls,
            "audio_url": audio_url,
            "width": int(payload.get("width") or 1080),
            "height": int(payload.get("height") or 1920),
            "fps": int(payload.get("fps") or 30),
            "upload": True,
            "folder": payload.get("folder") or "videos/full-ai-v10-34-final",
            "transition_policy": SAFE_TRANSITION,
            "crossfade_duration": 0.35,
        }
        compose_start = _post_json("/api/video/compose/urls/start", compose_payload, timeout=90)
        compose_job_id = compose_start.get("job_id")
        if not compose_job_id:
            raise RuntimeError("compose 没有返回 job_id")
        compose_result = _poll("/api/video/compose/job/{job_id}", compose_job_id, timeout_seconds=1200, interval=3)
        job.update({"compose_job_id": compose_job_id, "compose_result": compose_result, "updated_at": time.time()})
        if str(compose_result.get("status") or "").lower() not in {"done", "completed", "succeeded", "success"}:
            raise RuntimeError("视频合成失败：" + str(compose_result)[:1000])
        result = compose_result.get("result") if isinstance(compose_result.get("result"), dict) else compose_result
        raw_final_url = result.get("video_url") or ((result.get("r2") or {}).get("public_url")) or compose_result.get("video_url") or ""
        local_path = result.get("local_path") or ""
        video_duration = float(result.get("duration_seconds") or _ffprobe_duration(local_path or raw_final_url, default=0.0) or 0.0)
        if not raw_final_url and not local_path:
            raise RuntimeError("合成完成但没有 final video_url/local_path")
        if video_duration and audio_duration and audio_duration > video_duration + 0.75:
            # The patched compose provider should fit video to audio before this point.
            # Keep the job alive with an explicit diagnostic instead of silently completing a bad file.
            job["duration_guard_warning"] = f"compose 返回视频 {video_duration:.2f}s 仍短于音频 {audio_duration:.2f}s"
            raise RuntimeError(f"音频时长 {audio_duration:.2f}s 大于视频时长 {video_duration:.2f}s，compose 未正确拉长，不能 completed")

        job.update({"stage": "subtitle_burn", "message": "AI 字幕导演正在压缩字幕、去标点、放大变色关键词并烧录", "progress": 88, "raw_final_video_url": raw_final_url, "video_duration_seconds": round(video_duration or audio_duration, 2), "updated_at": time.time()})
        _save_job_snapshot(job_id)
        subtitle_style_id = str(payload.get("subtitle_style_id") or "douyin_pop")
        subtitle_style = payload.get("subtitle_style") if isinstance(payload.get("subtitle_style"), dict) else {}
        subtitle_result = burn_subtitles_with_style_and_upload(
            video_url="" if local_path and Path(str(local_path)).exists() else raw_final_url,
            video_path=local_path if local_path and Path(str(local_path)).exists() else "",
            text=script,
            segments=_director_subtitle_segments(script, audio_duration, semantic_shots, tts_result),
            duration=audio_duration or video_duration,
            style_id=subtitle_style_id,
            keywords=_collect_keywords(payload, semantic_shots),
            prefix="full_ai_v10407_engine_subtitle",
            subtitle_style=subtitle_style,
        )
        subtitled_url = subtitle_result.get("video_url") or subtitle_result.get("url") or ""
        if not subtitle_result.get("ok") or not subtitled_url:
            raise RuntimeError("字幕烧录没有返回字幕版视频，不能 completed：" + str(subtitle_result)[:1000])

        final_job = {
            **job,
            "subtitled_video_url": subtitled_url,
            "video_url": subtitled_url,
            "output_url": subtitled_url,
            "subtitle_result": subtitle_result,
            "status": "completed",
            "stage": "completed",
            "message": "带字幕、叠化转场、安全闭环视频生成完成",
        }
        valid = validate_completed(final_job)
        if not valid.get("ok"):
            raise RuntimeError("质量校验未通过，不能 completed：" + "; ".join(valid.get("errors") or []))
        job.update(final_job)
        job.update({"ok": True, "progress": 100, "version": FINAL_VERSION, "updated_at": time.time()})
        job["result"] = {
            "ok": True,
            "video_url": subtitled_url,
            "subtitled_video_url": subtitled_url,
            "raw_final_video_url": raw_final_url,
            "audio_url": audio_url,
            "raw_shots": job.get("raw_shots") or [],
            "shots": semantic_shots,
            "fal_shots": fal_shots,
            "transition_policy": SAFE_TRANSITION,
            "subtitle_required": True,
            "subtitle_burned": True,
            "subtitle_style_id": str(payload.get("subtitle_style_id") or "douyin_pop"),
            "shot_visual_audits": job.get("shot_visual_audits") or [],
            "compose_job_id": compose_job_id,
            "fal_generation_mode": "shot_by_shot_visual_audit_retry",
        "engine_source_fix": True,
        }
    except Exception as exc:
        _fail_job(job, "FINAL_VIDEO_GENERATION_FAILED", "V10.34 最终视频生成失败，未标记 completed：" + str(exc), stage=str(job.get("stage") or "failed"))
    finally:
        job["updated_at"] = time.time()
        _save_job_snapshot(job_id)


def _director_subtitle_segments(script: str, duration: float, shots: List[Dict[str, Any]] | None = None, tts_result: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
    duration = float(duration or 10.0)
    max_chars = 11

    def split_phrases(value: Any) -> List[str]:
        clean = _sanitize_script_text(value)
        if not clean:
            return []
        primary = [item for item in re.split(r"[。！？；]+", clean) if item]
        result: List[str] = []
        for sentence in primary:
            chunks = [item for item in re.split(r"(?<=[，,])|(?=但是|尤其|如果|所以|而且|另外|最后|首先)", sentence) if item]
            for chunk in chunks:
                chunk = chunk.strip("，,")
                while len(chunk) > max_chars:
                    cut = max_chars
                    for pos in range(max_chars, max(4, max_chars - 4), -1):
                        if chunk[pos - 1:pos] in "的了和与但也还就再才是":
                            cut = pos
                            break
                    result.append(chunk[:cut])
                    chunk = chunk[cut:]
                if chunk:
                    result.append(chunk)
        return [item for item in result if item]

    sources: List[Dict[str, Any]] = []
    tr = tts_result or {}
    for key in ("segments", "tts_segments", "items", "cues", "timeline"):
        arr = tr.get(key)
        if not isinstance(arr, list):
            continue
        for item in arr:
            if not isinstance(item, dict):
                continue
            clean = _sanitize_script_text(item.get("text") or item.get("line") or item.get("sentence") or item.get("narration"))
            if not clean:
                continue
            start = item.get("start") if item.get("start") is not None else item.get("start_time") if item.get("start_time") is not None else item.get("start_seconds")
            end = item.get("end") if item.get("end") is not None else item.get("end_time") if item.get("end_time") is not None else item.get("end_seconds")
            sources.append({"text": clean, "start": start, "end": end, "keywords": item.get("highlight_keywords") or item.get("keywords") or []})
        if sources:
            break
    if not sources:
        for shot in shots or []:
            if not isinstance(shot, dict):
                continue
            clean = _sanitize_script_text(shot.get("narration_segment") or shot.get("narration") or shot.get("text"))
            if clean:
                sources.append({"text": clean, "keywords": shot.get("highlight_keywords") or shot.get("keywords") or []})
    if not sources:
        sources = [{"text": _sanitize_script_text(script), "keywords": []}]

    out: List[Dict[str, Any]] = []
    cursor = 0.0
    total_weight = sum(max(1, len(_sanitize_script_text(source.get("text")))) for source in sources) or 1
    for source in sources:
        phrases = split_phrases(source.get("text"))
        if not phrases:
            continue
        source_start = source.get("start")
        source_end = source.get("end")
        if source_start is None or source_end is None:
            source_start = cursor
            source_span = duration * max(1, len(_sanitize_script_text(source.get("text")))) / total_weight
            source_end = min(duration, float(source_start) + source_span)
        source_start = max(0.0, float(source_start))
        source_end = min(duration, max(source_start + 0.3, float(source_end)))
        phrase_total = sum(max(1, len(item)) for item in phrases)
        phrase_cursor = source_start
        for index, phrase in enumerate(phrases):
            span = (source_end - source_start) * max(1, len(phrase)) / phrase_total
            phrase_end = source_end if index == len(phrases) - 1 else min(source_end, phrase_cursor + max(0.45, span))
            out.append({
                "text": phrase,
                "start": round(phrase_cursor, 3),
                "end": round(phrase_end, 3),
                "highlight_keywords": source.get("keywords") or [],
            })
            phrase_cursor = phrase_end
        cursor = source_end
    if out:
        out[-1]["end"] = round(duration, 3)
    return out

def _timed_subtitle_segments(script: str, duration: float) -> List[Dict[str, Any]]:
    # Backward-compatible wrapper. The real logic is now _director_subtitle_segments.
    return _director_subtitle_segments(script, duration, shots=None, tts_result=None)

def _start(payload: Dict[str, Any]) -> Dict[str, Any]:
    job_id = "full_ai_v1034_" + uuid.uuid4().hex[:18]
    now = time.time()
    JOBS[job_id] = {
        "ok": True,
        "job_id": job_id,
        "status": "running",
        "stage": "queued",
        "message": "V10.34 最终视频任务已创建",
        "version": FINAL_VERSION,
        "progress": 1,
        "created_at": now,
        "updated_at": now,
        "request": payload,
        "subtitle_required": True,
        "transition_policy": SAFE_TRANSITION,
        "fal_generation_mode": "shot_by_shot_visual_audit_retry",
    }
    _save_job_snapshot(job_id)
    threading.Thread(target=_run_final_job, args=(job_id, payload), daemon=True).start()
    return JOBS[job_id]


def _maybe_mark_stale(job: Dict[str, Any]) -> Dict[str, Any]:
    try:
        if str(job.get("status") or "").lower() != "running":
            return job
        stage = str(job.get("stage") or "")
        if not any(x in stage for x in ["fal", "semantic", "storyboard"]):
            return job
        updated = float(job.get("updated_at") or job.get("created_at") or 0)
        if updated and time.time() - updated > STALE_JOB_TIMEOUT:
            _fail_job(job, "STALE_RUNNING_JOB_TIMEOUT", f"任务在 {stage} 阶段超过 {STALE_JOB_TIMEOUT}s 没有更新，已自动失败，避免继续烧钱。", stage="fal_timeout")
            try:
                JOBS[job.get("job_id", "")] = job
                _save_job_snapshot(str(job.get("job_id")))
            except Exception:
                pass
    except Exception:
        pass
    return job


def _get_job(job_id: str) -> Dict[str, Any]:
    if job_id in JOBS:
        return _maybe_mark_stale(JOBS[job_id])
    try:
        p = json_dir() / "final_jobs" / f"{job_id}.json"
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            data = _maybe_mark_stale(data)
            if str(data.get("status") or "").lower() == "failed":
                p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            return data
    except Exception:
        pass
    return {"ok": False, "status": "not_found", "job_id": job_id}


def install_v10_34_final_video(app: FastAPI) -> None:
    if getattr(app.state, "v10_34_final_video_installed", False):
        return
    app.state.v10_34_final_video_installed = True

    @app.middleware("http")
    async def _v1034_final_video_middleware(request: Request, call_next):
        path = request.url.path
        method = request.method.upper()
        if method == "GET" and path == "/api/video/v10-34/final/health":
            return JSONResponse({
                "ok": True,
                "version": FINAL_VERSION,
                "max_fal_shots": MAX_FAL_SHOTS,
                "target_shots_30_seconds": _target_shot_count(30.0),
                "per_shot_visual_audit_retry": True,
                "raw_narration_removed_from_visual_prompt": True,
                "subtitle_runtime_style": True,
                "script_sanitizer": True,
            })
        if method == "POST" and path in {"/api/video/full-ai/one-scene/start", "/api/video/v10-34/final/start"}:
            try:
                payload = await request.json()
            except Exception:
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            return JSONResponse(_start(payload))
        if method == "GET" and (path.startswith("/api/video/full-ai/one-scene/job/") or path.startswith("/api/video/v10-34/final/job/")):
            job_id = path.rstrip("/").split("/")[-1]
            return JSONResponse(_get_job(job_id))
        return await call_next(request)
