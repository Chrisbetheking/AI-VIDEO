from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import httpx
from fastapi import Depends, HTTPException, Request

from app.services.assets_store import read_assets, upsert_asset
from app.services.memory import MemoryStore


VERSION = "10.40.8.4.3"
INSTALL_MARKER = "doubao_asset_intelligence_v10_40_8_4_3"
TERMINAL_STATUSES = {"done", "failed", "cancelled"}
ANALYZABLE_KINDS = {"image", "video"}

CATEGORIES = [
    "房屋室内",
    "楼盘外观",
    "样板间",
    "生活配套",
    "商业商场",
    "交通出行",
    "学校教育",
    "医疗资源",
    "城市地标",
    "自然景观",
    "街道社区",
    "人物生活",
    "餐饮娱乐",
    "施工现场",
    "地图与资料",
    "其他",
]

_LOCK = threading.RLock()
_ACTIVE_JOB_ID = ""
_WORKER_STARTED = False
_INSTALLED = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(str(os.getenv(name, default)).strip())
    except Exception:
        value = default
    return max(minimum, min(maximum, value))


def _env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(str(os.getenv(name, default)).strip())
    except Exception:
        value = default
    return max(minimum, min(maximum, value))


def _truthy(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _index_path(settings: Any) -> Path:
    path = settings.data_dir / "asset_intelligence_index.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _jobs_path(settings: Any) -> Path:
    path = settings.data_dir / "asset_intelligence_jobs.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _control_path(settings: Any) -> Path:
    path = settings.data_dir / "asset_intelligence_control.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    temp.replace(path)


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _load_index(settings: Any) -> dict[str, dict[str, Any]]:
    value = _read_json(_index_path(settings), {})
    return value if isinstance(value, dict) else {}


def _save_index(settings: Any, value: dict[str, dict[str, Any]]) -> None:
    ordered = sorted(value.items(), key=lambda item: str(item[1].get("updated_at") or ""), reverse=True)
    _atomic_write_json(_index_path(settings), dict(ordered[:5000]))


def _load_jobs(settings: Any) -> dict[str, dict[str, Any]]:
    value = _read_json(_jobs_path(settings), {})
    return value if isinstance(value, dict) else {}


def _save_jobs(settings: Any, value: dict[str, dict[str, Any]]) -> None:
    ordered = sorted(value.items(), key=lambda item: str(item[1].get("created_at") or ""), reverse=True)
    _atomic_write_json(_jobs_path(settings), dict(ordered[:200]))


def _control_defaults() -> dict[str, Any]:
    return {
        "auto_enabled": _truthy(os.getenv("ASSET_INTELLIGENCE_AUTO_ENABLED"), True),
        "auto_batch_size": _env_int("ASSET_INTELLIGENCE_AUTO_BATCH", 6, 1, 30),
        "poll_seconds": _env_int("ASSET_INTELLIGENCE_POLL_SECONDS", 12, 5, 300),
        "include_avatar_assets": _truthy(os.getenv("ASSET_INTELLIGENCE_INCLUDE_AVATARS"), False),
        "updated_at": _now_iso(),
    }


def _load_control(settings: Any) -> dict[str, Any]:
    value = _read_json(_control_path(settings), {})
    return {**_control_defaults(), **(value if isinstance(value, dict) else {})}


def _save_control(settings: Any, patch: dict[str, Any]) -> dict[str, Any]:
    value = {**_load_control(settings), **patch, "updated_at": _now_iso()}
    value["auto_enabled"] = bool(value.get("auto_enabled"))
    value["auto_batch_size"] = max(1, min(30, int(value.get("auto_batch_size") or 6)))
    value["poll_seconds"] = max(5, min(300, int(value.get("poll_seconds") or 12)))
    value["include_avatar_assets"] = bool(value.get("include_avatar_assets"))
    _atomic_write_json(_control_path(settings), value)
    return value


def _asset_id(asset: dict[str, Any]) -> str:
    return str(asset.get("id") or Path(str(asset.get("filename") or "")).stem).strip()


def _raw_dict(asset: dict[str, Any]) -> dict[str, Any]:
    raw = asset.get("raw")
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return dict(parsed) if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _ark_model(settings: Any) -> str:
    return str(os.getenv("ASSET_INTELLIGENCE_MODEL") or getattr(settings, "ark_video_model", "") or "").strip()


def _ark_key(settings: Any) -> str:
    return str(getattr(settings, "ark_api_key", "") or "").strip()


def _ark_base(settings: Any) -> str:
    return str(getattr(settings, "ark_base_url", "") or "https://ark.cn-beijing.volces.com/api/v3").rstrip("/")


def _configured(settings: Any) -> bool:
    return bool(_ark_key(settings) and _ark_model(settings))


def _json_from_text(text: str) -> dict[str, Any]:
    value = str(text or "").strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?", "", value, flags=re.I).strip()
        value = re.sub(r"```$", "", value).strip()
    try:
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    match = re.search(r"\{.*\}", value, flags=re.S)
    if not match:
        raise ValueError("豆包没有返回可解析的 JSON")
    parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("豆包返回结果不是 JSON 对象")
    return parsed


def _safe_list(value: Any, limit: int = 12) -> list[str]:
    if isinstance(value, str):
        values = re.split(r"[,，、;；\n]+", value)
    elif isinstance(value, list):
        values = value
    else:
        values = []
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = re.sub(r"\s+", " ", str(item or "")).strip()[:40]
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def _clip_text(value: Any, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _orientation(width: int, height: int) -> str:
    if width <= 0 or height <= 0:
        return "未知"
    ratio = width / max(1, height)
    if ratio < 0.82:
        return "竖屏"
    if ratio > 1.22:
        return "横屏"
    return "方形"


def _normalize_cleanliness(value: Any) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    flags = {
        "watermark": bool(source.get("watermark", False)),
        "subtitle": bool(source.get("subtitle", False)),
        "qr_code": bool(source.get("qr_code", False)),
        "large_face": bool(source.get("large_face", False)),
        "advertising_text": bool(source.get("advertising_text", False)),
        "blur": bool(source.get("blur", False)),
        "too_dark": bool(source.get("too_dark", False)),
        "severe_shake": bool(source.get("severe_shake", False)),
    }
    raw_status = str(source.get("status") or "").strip().lower()
    if any(flags.values()):
        status = "failed"
    elif raw_status in {"passed", "pass", "clean", "ok", "通过", "干净"}:
        status = "passed"
    else:
        status = "uncertain"
    reasons = _safe_list(source.get("reasons") or source.get("reason"), 8)
    return {"status": status, **flags, "reasons": reasons}


def normalize_intelligence(payload: dict[str, Any], *, asset: dict[str, Any], technical: dict[str, Any], model: str) -> dict[str, Any]:
    category = _clip_text(payload.get("primary_category"), 30)
    if category not in CATEGORIES:
        category = "其他"
    secondary = _clip_text(payload.get("secondary_category"), 40) or category
    subjects = _safe_list(payload.get("subjects"), 12)
    keywords = _safe_list(payload.get("keywords"), 16)
    recommended = _safe_list(payload.get("recommended_topics"), 10)
    for item in subjects + [category, secondary]:
        if item and item not in keywords:
            keywords.append(item)
    keywords = keywords[:16]
    try:
        quality_score = int(round(float(payload.get("quality_score", 0))))
    except Exception:
        quality_score = 0
    quality_score = max(0, min(100, quality_score))
    cleanliness = _normalize_cleanliness(payload.get("cleanliness"))
    width = int(technical.get("width") or 0)
    height = int(technical.get("height") or 0)
    duration = max(0.0, float(technical.get("duration") or 0))
    confidence_raw = payload.get("confidence", 0)
    try:
        confidence = max(0.0, min(1.0, float(confidence_raw)))
    except Exception:
        confidence = 0.0
    title = _clip_text(payload.get("title"), 80)
    if not title:
        title = _clip_text(asset.get("original_name") or asset.get("filename"), 80)
    description = _clip_text(payload.get("description"), 300)
    return {
        "asset_id": _asset_id(asset),
        "filename": str(asset.get("filename") or ""),
        "original_name": str(asset.get("original_name") or asset.get("filename") or ""),
        "kind": str(asset.get("kind") or ""),
        "analysis_status": "completed",
        "title": title,
        "description": description,
        "primary_category": category,
        "secondary_category": secondary,
        "location": _clip_text(payload.get("location"), 80) or "未知",
        "scene": _clip_text(payload.get("scene"), 80) or "未知场景",
        "subjects": subjects,
        "camera_motion": _clip_text(payload.get("camera_motion"), 60) or ("静态" if asset.get("kind") == "image" else "未知"),
        "orientation": _clip_text(payload.get("orientation"), 20) or _orientation(width, height),
        "keywords": keywords,
        "cleanliness": cleanliness,
        "quality_score": quality_score,
        "recommended_topics": recommended,
        "visible_text": _safe_list(payload.get("visible_text"), 12),
        "confidence": confidence,
        "technical": {
            "width": width,
            "height": height,
            "duration": round(duration, 3),
            "frame_count": int(technical.get("frame_count") or 0),
        },
        "provider": "doubao_ark",
        "model": model,
        "updated_at": _now_iso(),
    }


def _probe_video(path: Path) -> dict[str, Any]:
    command = [
        "ffprobe", "-v", "error",
        "-show_entries", "stream=codec_type,width,height:format=duration",
        "-of", "json", str(path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=60, check=True)
    data = json.loads(result.stdout or "{}")
    stream = next((item for item in data.get("streams", []) if item.get("codec_type") == "video"), {})
    try:
        duration = float((data.get("format") or {}).get("duration") or 0)
    except Exception:
        duration = 0.0
    return {
        "width": int(stream.get("width") or 0),
        "height": int(stream.get("height") or 0),
        "duration": max(0.0, duration),
    }


def _download_asset(url: str, target: Path) -> None:
    max_bytes = _env_int("ASSET_INTELLIGENCE_DOWNLOAD_MB", 512, 20, 4096) * 1024 * 1024
    total = 0
    target.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=httpx.Timeout(300.0, connect=30.0), follow_redirects=True) as client:
        with client.stream("GET", url) as response:
            response.raise_for_status()
            with target.open("wb") as output:
                for chunk in response.iter_bytes(1024 * 1024):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError(f"素材下载超过 {max_bytes // 1024 // 1024}MB")
                    output.write(chunk)


def _resolve_asset_file(settings: Any, asset: dict[str, Any], work_dir: Path) -> Path:
    filename = Path(str(asset.get("filename") or "asset.bin")).name
    local = settings.uploads_dir / filename
    if local.exists() and local.is_file():
        return local
    url = str(asset.get("r2_url") or asset.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        raise ValueError("素材既没有本地文件，也没有可下载的 R2 URL")
    target = work_dir / filename
    _download_asset(url, target)
    return target


def _prepare_image_frame(path: Path, target: Path) -> dict[str, Any]:
    from PIL import Image, ImageOps

    target.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        width, height = image.size
        image.thumbnail((1280, 1280))
        image.save(target, "JPEG", quality=82, optimize=True)
    return {"width": int(width), "height": int(height), "duration": 0.0, "frame_count": 1}


def _video_timestamps(duration: float) -> list[float]:
    if duration <= 0:
        return [0.0]
    if duration <= 8:
        ratios = [0.18, 0.50, 0.82]
    elif duration <= 30:
        ratios = [0.10, 0.35, 0.62, 0.90]
    else:
        ratios = [0.06, 0.27, 0.50, 0.73, 0.94]
    return [max(0.0, min(duration - 0.05, duration * ratio)) for ratio in ratios]


def _prepare_video_frames(path: Path, target_dir: Path) -> tuple[list[Path], dict[str, Any]]:
    technical = _probe_video(path)
    target_dir.mkdir(parents=True, exist_ok=True)
    frames: list[Path] = []
    for index, timestamp in enumerate(_video_timestamps(float(technical.get("duration") or 0))):
        target = target_dir / f"frame_{index + 1:02d}.jpg"
        command = [
            "ffmpeg", "-y", "-v", "error", "-ss", f"{timestamp:.3f}", "-i", str(path),
            "-frames:v", "1", "-vf", "scale=960:-2:force_original_aspect_ratio=decrease",
            "-q:v", "3", str(target),
        ]
        try:
            subprocess.run(command, capture_output=True, text=True, timeout=90, check=True)
            if target.exists() and target.stat().st_size > 1000:
                frames.append(target)
        except Exception:
            target.unlink(missing_ok=True)
    if not frames:
        raise ValueError("视频关键帧提取失败")
    technical["frame_count"] = len(frames)
    return frames, technical


def _data_url(path: Path) -> str:
    raw = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/jpeg;base64,{raw}"


def _prompt(asset: dict[str, Any], technical: dict[str, Any]) -> str:
    return f"""
你是房地产短视频素材库的视觉理解与净素材审查员。根据提供的图片或同一视频的多张关键帧，用中文输出严格 JSON。

素材文件名：{asset.get('original_name') or asset.get('filename')}
素材类型：{asset.get('kind')}
技术信息：{json.dumps(technical, ensure_ascii=False)}

任务：
1. 给出用户一眼能看懂的素材标题和客观描述；
2. 从指定一级分类中选择且只能选择一个：{json.dumps(CATEGORIES, ensure_ascii=False)}；
3. 给出具体二级分类、地点、室内/室外、白天/夜晚、主体、运镜、横竖屏、关键词和适合口播主题；
4. 审查水印、字幕、二维码、大面积人脸、广告文字、模糊、过暗、严重抖动；
5. 质量评分 0-100；
6. 不确定的地点必须写“未知”，不得凭空认定具体楼盘、学校、商场或地标；
7. 视频多帧存在不同内容时，描述主要内容并补充变化；
8. pending/unknown 不等于不合格。只有明确检测到问题时 cleanliness.status 才能是 failed。

只输出以下 JSON 对象，不要 Markdown：
{{
  "title": "20字左右标题",
  "description": "40-120字客观描述",
  "primary_category": "指定一级分类之一",
  "secondary_category": "具体二级分类",
  "location": "地点或未知",
  "scene": "室内/室外 + 白天/夜晚 + 场景",
  "subjects": ["主体1", "主体2"],
  "camera_motion": "静态/横移/推进/后退/跟拍/手持/未知",
  "orientation": "横屏/竖屏/方形",
  "keywords": ["关键词1", "关键词2"],
  "cleanliness": {{
    "status": "passed/failed/uncertain",
    "watermark": false,
    "subtitle": false,
    "qr_code": false,
    "large_face": false,
    "advertising_text": false,
    "blur": false,
    "too_dark": false,
    "severe_shake": false,
    "reasons": []
  }},
  "quality_score": 0,
  "recommended_topics": ["适合口播主题1"],
  "visible_text": [],
  "confidence": 0.0
}}
""".strip()


def _message_text(data: dict[str, Any]) -> str:
    value = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if text:
                    parts.append(str(text))
            elif item:
                parts.append(str(item))
        return "\n".join(parts)
    return str(value or "")


def _call_ark(settings: Any, prompt: str, frames: list[Path]) -> dict[str, Any]:
    api_key = _ark_key(settings)
    model = _ark_model(settings)
    if not api_key or not model:
        raise RuntimeError("未配置 ARK_API_KEY / ARK_VIDEO_MODEL")
    url = _ark_base(settings) + "/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    last_error = ""
    frame_groups = [frames[:5], frames[:3], frames[:1]]
    for attempt, frame_group in enumerate(frame_groups, start=1):
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        content.extend({"type": "image_url", "image_url": {"url": _data_url(frame)}} for frame in frame_group)
        body = {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "temperature": 0.1,
            "stream": False,
        }
        try:
            with httpx.Client(timeout=httpx.Timeout(210.0, connect=30.0), follow_redirects=True) as client:
                response = client.post(url, headers=headers, json=body)
            if response.status_code >= 400:
                last_error = f"豆包返回 {response.status_code}：{response.text[:800]}"
                if response.status_code in {400, 413, 422, 429, 500, 502, 503} and attempt < len(frame_groups):
                    time.sleep(1.2 * attempt)
                    continue
                raise RuntimeError(last_error)
            return _json_from_text(_message_text(response.json()))
        except (httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
            last_error = str(exc)
            if attempt < len(frame_groups):
                time.sleep(1.2 * attempt)
                continue
            raise RuntimeError(f"豆包素材理解请求失败：{last_error}") from exc
    raise RuntimeError(last_error or "豆包素材理解失败")


def _persist_asset_intelligence(settings: Any, memory: MemoryStore, asset: dict[str, Any], record: dict[str, Any]) -> None:
    raw = _raw_dict(asset)
    raw["asset_intelligence"] = record
    allowed = {
        "id", "filename", "original_name", "kind", "url", "r2_url", "r2_key",
        "size_bytes", "duration", "width", "height", "folder", "source_type",
        "usage_role", "workspace_id", "deleted", "created_at", "updated_at", "raw",
    }
    payload = {key: value for key, value in asset.items() if key in allowed}
    payload["id"] = _asset_id(asset)
    payload["raw"] = raw
    payload["updated_at"] = _now_iso()
    upsert_asset(settings, payload, memory, require_supabase=False)


def _set_index_record(settings: Any, asset_id: str, record: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        index = _load_index(settings)
        index[asset_id] = record
        _save_index(settings, index)
    return record


def _analyze_one(settings: Any, memory: MemoryStore, asset: dict[str, Any], job_id: str) -> dict[str, Any]:
    asset_id = _asset_id(asset)
    model = _ark_model(settings)
    processing = {
        "asset_id": asset_id,
        "filename": str(asset.get("filename") or ""),
        "original_name": str(asset.get("original_name") or asset.get("filename") or ""),
        "kind": str(asset.get("kind") or ""),
        "analysis_status": "processing",
        "provider": "doubao_ark",
        "model": model,
        "job_id": job_id,
        "updated_at": _now_iso(),
    }
    _set_index_record(settings, asset_id, processing)
    work_dir = settings.tmp_dir / "asset_intelligence" / job_id / asset_id
    shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        if not _configured(settings):
            raise RuntimeError("未配置 ARK_API_KEY / ARK_VIDEO_MODEL")
        media_path = _resolve_asset_file(settings, asset, work_dir)
        kind = str(asset.get("kind") or "")
        if kind == "image":
            frame = work_dir / "image.jpg"
            technical = _prepare_image_frame(media_path, frame)
            frames = [frame]
        elif kind == "video":
            frames, technical = _prepare_video_frames(media_path, work_dir / "frames")
        else:
            raise ValueError(f"不支持的素材类型：{kind}")
        payload = _call_ark(settings, _prompt(asset, technical), frames)
        record = normalize_intelligence(payload, asset=asset, technical=technical, model=model)
        record["job_id"] = job_id
        _set_index_record(settings, asset_id, record)
        try:
            _persist_asset_intelligence(settings, memory, asset, record)
        except Exception as exc:
            record["persistence_warning"] = str(exc)[:500]
            _set_index_record(settings, asset_id, record)
        return record
    except Exception as exc:
        message = str(exc)[:1000]
        status = "need_config" if "ARK_API_KEY" in message or "ARK_VIDEO_MODEL" in message else "failed"
        record = {
            **processing,
            "analysis_status": status,
            "error": message,
            "updated_at": _now_iso(),
        }
        _set_index_record(settings, asset_id, record)
        return record
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _update_job(settings: Any, job_id: str, **patch: Any) -> dict[str, Any]:
    with _LOCK:
        jobs = _load_jobs(settings)
        current = dict(jobs.get(job_id) or {"job_id": job_id})
        current.update(patch)
        current["updated_at"] = _now_iso()
        jobs[job_id] = current
        _save_jobs(settings, jobs)
        return current


def _public_job(job: dict[str, Any]) -> dict[str, Any]:
    return dict(job)


def _assets_map(settings: Any) -> dict[str, dict[str, Any]]:
    memory = MemoryStore(settings)
    try:
        assets = read_assets(settings, memory, limit=3000)
    except Exception:
        assets = read_assets(settings, None, limit=3000)
    result: dict[str, dict[str, Any]] = {}
    for item in assets:
        if not isinstance(item, dict):
            continue
        key = _asset_id(item)
        if key:
            result[key] = dict(item)
    return result


def _run_job(settings: Any, job_id: str, asset_ids: list[str], force: bool) -> None:
    global _ACTIVE_JOB_ID
    memory = MemoryStore(settings)
    success = 0
    failed = 0
    skipped = 0
    try:
        _update_job(settings, job_id, status="running", stage="analyzing", progress=1, started_at=_now_iso())
        assets = _assets_map(settings)
        index = _load_index(settings)
        total = len(asset_ids)
        for position, asset_id in enumerate(asset_ids, start=1):
            asset = assets.get(asset_id)
            if not asset:
                failed += 1
                continue
            old_status = str((index.get(asset_id) or {}).get("analysis_status") or "")
            if not force and old_status in {"completed", "manual"}:
                skipped += 1
                continue
            _update_job(
                settings,
                job_id,
                current_asset_id=asset_id,
                current_file=str(asset.get("original_name") or asset.get("filename") or ""),
                processed=position - 1,
                progress=min(96, 2 + int((position - 1) / max(1, total) * 94)),
                summary={"success": success, "failed": failed, "skipped": skipped, "total": total},
            )
            result = _analyze_one(settings, memory, asset, job_id)
            if result.get("analysis_status") in {"completed", "manual"}:
                success += 1
            else:
                failed += 1
            _update_job(
                settings,
                job_id,
                processed=position,
                progress=min(98, 2 + int(position / max(1, total) * 96)),
                summary={"success": success, "failed": failed, "skipped": skipped, "total": total},
            )
            time.sleep(_env_float("ASSET_INTELLIGENCE_REQUEST_GAP", 0.8, 0.0, 10.0))
        _update_job(
            settings,
            job_id,
            status="done",
            stage="finished",
            progress=100,
            current_asset_id="",
            current_file="",
            summary={"success": success, "failed": failed, "skipped": skipped, "total": total},
            message=f"豆包素材分析完成：成功 {success}，失败 {failed}，跳过 {skipped}",
            finished_at=_now_iso(),
        )
    except Exception as exc:
        _update_job(
            settings,
            job_id,
            status="failed",
            stage="failed",
            progress=100,
            error=str(exc)[:1000],
            finished_at=_now_iso(),
        )
    finally:
        with _LOCK:
            if _ACTIVE_JOB_ID == job_id:
                _ACTIVE_JOB_ID = ""


def _create_job(settings: Any, asset_ids: list[str], *, force: bool, source: str) -> dict[str, Any]:
    global _ACTIVE_JOB_ID
    unique = list(dict.fromkeys(str(item).strip() for item in asset_ids if str(item).strip()))
    if not unique:
        raise ValueError("没有需要分析的素材")
    with _LOCK:
        if _ACTIVE_JOB_ID:
            active = _load_jobs(settings).get(_ACTIVE_JOB_ID)
            if active and str(active.get("status")) not in TERMINAL_STATUSES:
                reused = dict(active)
                reused["reused"] = True
                return reused
            _ACTIVE_JOB_ID = ""
        job_id = f"asset_ai_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        job = {
            "job_id": job_id,
            "version": VERSION,
            "status": "queued",
            "stage": "queued",
            "progress": 0,
            "message": "等待豆包分析素材",
            "asset_ids": unique,
            "force": bool(force),
            "source": source,
            "processed": 0,
            "current_asset_id": "",
            "current_file": "",
            "summary": {"success": 0, "failed": 0, "skipped": 0, "total": len(unique)},
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        jobs = _load_jobs(settings)
        jobs[job_id] = job
        _save_jobs(settings, jobs)
        _ACTIVE_JOB_ID = job_id
    thread = threading.Thread(target=_run_job, args=(settings, job_id, unique, bool(force)), daemon=True, name=f"asset-ai-{job_id[-8:]}")
    thread.start()
    return job


def _pending_asset_ids(settings: Any, *, limit: int, include_avatars: bool) -> list[str]:
    assets = _assets_map(settings)
    index = _load_index(settings)
    pending: list[str] = []
    for asset_id, asset in assets.items():
        if str(asset.get("kind") or "") not in ANALYZABLE_KINDS:
            continue
        if bool(asset.get("deleted")):
            continue
        if not include_avatars and str(asset.get("usage_role") or "content") == "avatar":
            continue
        status = str((index.get(asset_id) or {}).get("analysis_status") or "pending")
        if status in {"pending", "need_config", ""}:
            pending.append(asset_id)
        if len(pending) >= limit:
            break
    return pending


def _summary(index: dict[str, dict[str, Any]], asset_ids: set[str]) -> dict[str, int]:
    result = {"total": len(asset_ids), "completed": 0, "manual": 0, "processing": 0, "pending": 0, "failed": 0, "need_config": 0, "clean_passed": 0, "clean_failed": 0, "clean_uncertain": 0}
    for asset_id in asset_ids:
        item = index.get(asset_id) or {}
        status = str(item.get("analysis_status") or "pending")
        if status not in result:
            status = "pending"
        result[status] += 1
        clean = str((item.get("cleanliness") or {}).get("status") or "")
        if clean == "passed":
            result["clean_passed"] += 1
        elif clean == "failed":
            result["clean_failed"] += 1
        elif status in {"completed", "manual"}:
            result["clean_uncertain"] += 1
    return result


def _repair_stale(settings: Any) -> None:
    global _ACTIVE_JOB_ID
    with _LOCK:
        jobs = _load_jobs(settings)
        changed = False
        for job_id, job in jobs.items():
            if str(job.get("status") or "") in {"queued", "running"}:
                job.update(status="failed", stage="recovered_after_restart", progress=100, error="后端重启后任务已终止，可重新发起", finished_at=_now_iso(), updated_at=_now_iso())
                changed = True
        if changed:
            _save_jobs(settings, jobs)
        index = _load_index(settings)
        for asset_id, record in index.items():
            if str(record.get("analysis_status") or "") == "processing":
                record.update(analysis_status="pending", error="后端重启后恢复为待分析", updated_at=_now_iso())
                changed = True
        if changed:
            _save_index(settings, index)
        _ACTIVE_JOB_ID = ""


def _auto_loop(settings: Any) -> None:
    while True:
        try:
            control = _load_control(settings)
            if control.get("auto_enabled") and _configured(settings):
                with _LOCK:
                    active = bool(_ACTIVE_JOB_ID)
                if not active:
                    ids = _pending_asset_ids(settings, limit=int(control.get("auto_batch_size") or 6), include_avatars=bool(control.get("include_avatar_assets")))
                    if ids:
                        _create_job(settings, ids, force=False, source="auto")
            time.sleep(int(control.get("poll_seconds") or 12))
        except Exception:
            time.sleep(15)


def _ensure_worker(settings: Any) -> None:
    global _WORKER_STARTED
    with _LOCK:
        if _WORKER_STARTED:
            return
        _WORKER_STARTED = True
    _repair_stale(settings)
    thread = threading.Thread(target=_auto_loop, args=(settings,), daemon=True, name="asset-intelligence-auto")
    thread.start()


def _find_asset(settings: Any, asset_id: str) -> Optional[dict[str, Any]]:
    return _assets_map(settings).get(asset_id)


def install_asset_intelligence(app: Any, get_settings: Callable[..., Any]) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    if any(getattr(route, "path", "") == "/api/assets/intelligence/health" for route in getattr(app, "routes", [])):
        _INSTALLED = True
        return
    settings_at_install = get_settings()
    _ensure_worker(settings_at_install)

    @app.get("/api/assets/intelligence/health")
    def asset_intelligence_health(settings: Any = Depends(get_settings)) -> dict[str, Any]:
        assets = _assets_map(settings)
        index = _load_index(settings)
        return {
            "ok": True,
            "version": VERSION,
            "mode": INSTALL_MARKER,
            "configured": _configured(settings),
            "model": _ark_model(settings),
            "provider": "doubao_ark",
            "auto_worker": True,
            "control": _load_control(settings),
            "summary": _summary(index, set(assets.keys())),
            "categories": CATEGORIES,
        }

    @app.get("/api/assets/intelligence")
    def asset_intelligence_list(limit: int = 3000, settings: Any = Depends(get_settings)) -> dict[str, Any]:
        assets = _assets_map(settings)
        index = _load_index(settings)
        items: list[dict[str, Any]] = []
        for asset_id, asset in assets.items():
            record = dict(index.get(asset_id) or {})
            if not record:
                record = {
                    "asset_id": asset_id,
                    "filename": str(asset.get("filename") or ""),
                    "original_name": str(asset.get("original_name") or asset.get("filename") or ""),
                    "kind": str(asset.get("kind") or ""),
                    "analysis_status": "pending",
                }
            items.append(record)
        items.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        jobs = _load_jobs(settings)
        active = jobs.get(_ACTIVE_JOB_ID) if _ACTIVE_JOB_ID else None
        return {
            "ok": True,
            "version": VERSION,
            "items": items[: max(1, min(int(limit or 3000), 5000))],
            "summary": _summary(index, set(assets.keys())),
            "control": _load_control(settings),
            "active_job": _public_job(active) if active else None,
            "categories": CATEGORIES,
        }

    @app.post("/api/assets/intelligence/analyze")
    async def asset_intelligence_analyze(request: Request, settings: Any = Depends(get_settings)) -> dict[str, Any]:
        try:
            body = await request.json()
        except Exception:
            body = {}
        body = body if isinstance(body, dict) else {}
        force = bool(body.get("force"))
        ids = [str(item) for item in (body.get("asset_ids") or []) if str(item).strip()]
        limit = max(1, min(500, int(body.get("limit") or 120)))
        include_avatars = bool(body.get("include_avatar_assets", False))
        if not ids:
            if force:
                assets = _assets_map(settings)
                ids = [asset_id for asset_id, asset in assets.items() if str(asset.get("kind") or "") in ANALYZABLE_KINDS and (include_avatars or str(asset.get("usage_role") or "content") != "avatar")][:limit]
            else:
                ids = _pending_asset_ids(settings, limit=limit, include_avatars=include_avatars)
        if not ids:
            return {"ok": True, "version": VERSION, "status": "nothing_to_analyze", "message": "没有待分析素材"}
        try:
            return _public_job(_create_job(settings, ids, force=force, source="manual"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/assets/intelligence/jobs/{job_id}")
    def asset_intelligence_job(job_id: str, settings: Any = Depends(get_settings)) -> dict[str, Any]:
        safe_id = re.sub(r"[^A-Za-z0-9_-]", "", job_id)[:160]
        job = _load_jobs(settings).get(safe_id)
        if not job:
            raise HTTPException(status_code=404, detail="素材分析任务不存在")
        return _public_job(job)

    @app.get("/api/assets/intelligence/jobs")
    def asset_intelligence_jobs(limit: int = 20, settings: Any = Depends(get_settings)) -> dict[str, Any]:
        jobs = list(_load_jobs(settings).values())
        jobs.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        return {"ok": True, "version": VERSION, "jobs": [_public_job(item) for item in jobs[: max(1, min(int(limit or 20), 100))]], "total": len(jobs)}

    @app.post("/api/assets/intelligence/control")
    async def asset_intelligence_control(request: Request, settings: Any = Depends(get_settings)) -> dict[str, Any]:
        try:
            body = await request.json()
        except Exception:
            body = {}
        body = body if isinstance(body, dict) else {}
        patch: dict[str, Any] = {}
        for key in ("auto_enabled", "auto_batch_size", "poll_seconds", "include_avatar_assets"):
            if key in body:
                patch[key] = body[key]
        return {"ok": True, "version": VERSION, "control": _save_control(settings, patch)}

    @app.patch("/api/assets/intelligence/{asset_id}")
    async def asset_intelligence_update(asset_id: str, request: Request, settings: Any = Depends(get_settings)) -> dict[str, Any]:
        safe_id = re.sub(r"[^A-Za-z0-9_-]", "", asset_id)[:160]
        asset = _find_asset(settings, safe_id)
        if not asset:
            raise HTTPException(status_code=404, detail="素材不存在")
        try:
            body = await request.json()
        except Exception:
            body = {}
        body = body if isinstance(body, dict) else {}
        index = _load_index(settings)
        current = dict(index.get(safe_id) or {"asset_id": safe_id})
        for key, limit_value in (("title", 80), ("description", 300), ("secondary_category", 40), ("location", 80), ("scene", 80), ("camera_motion", 60), ("orientation", 20)):
            if key in body:
                current[key] = _clip_text(body.get(key), limit_value)
        if body.get("primary_category") in CATEGORIES:
            current["primary_category"] = body["primary_category"]
        for key, list_limit in (("keywords", 16), ("subjects", 12), ("recommended_topics", 10)):
            if key in body:
                current[key] = _safe_list(body.get(key), list_limit)
        if "quality_score" in body:
            try:
                current["quality_score"] = max(0, min(100, int(body.get("quality_score"))))
            except Exception:
                pass
        if "cleanliness" in body:
            current["cleanliness"] = _normalize_cleanliness(body.get("cleanliness"))
        current.update(analysis_status="manual", provider="human", model="manual", updated_at=_now_iso())
        _set_index_record(settings, safe_id, current)
        try:
            _persist_asset_intelligence(settings, MemoryStore(settings), asset, current)
        except Exception as exc:
            current["persistence_warning"] = str(exc)[:500]
            _set_index_record(settings, safe_id, current)
        return {"ok": True, "version": VERSION, "item": current}

    @app.get("/api/assets/intelligence/search")
    def asset_intelligence_search(q: str, limit: int = 30, settings: Any = Depends(get_settings)) -> dict[str, Any]:
        query = re.sub(r"\s+", " ", str(q or "")).strip().lower()
        if not query:
            return {"ok": True, "version": VERSION, "items": []}
        tokens = [item for item in re.split(r"[\s,，、;；]+", query) if item]
        index = _load_index(settings)
        assets = _assets_map(settings)
        scored: list[tuple[int, dict[str, Any]]] = []
        for asset_id, record in index.items():
            if str(record.get("analysis_status") or "") not in {"completed", "manual"}:
                continue
            title = str(record.get("title") or "").lower()
            category = f"{record.get('primary_category', '')} {record.get('secondary_category', '')}".lower()
            keywords = " ".join(_safe_list(record.get("keywords"), 30)).lower()
            description = str(record.get("description") or "").lower()
            score = 0
            for token in tokens:
                if token in title:
                    score += 8
                if token in keywords:
                    score += 6
                if token in category:
                    score += 5
                if token in description:
                    score += 2
            if score <= 0:
                continue
            asset = assets.get(asset_id) or {}
            scored.append((score, {**record, "score": score, "url": str(asset.get("r2_url") or asset.get("url") or "")}))
        scored.sort(key=lambda item: (-item[0], -int(item[1].get("quality_score") or 0)))
        return {"ok": True, "version": VERSION, "query": q, "items": [item for _, item in scored[: max(1, min(int(limit or 30), 100))]]}

    _INSTALLED = True
