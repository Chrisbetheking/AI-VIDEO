from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import unquote, urlparse

import httpx
from fastapi import BackgroundTasks, Body, FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder


VERSION = "10.40.1"
MODE = "real_main_compose_workflow_hub"

BASE = Path(os.getenv("AI_VIDEO_BASE", "/opt/ai-video"))
STORAGE = BASE / "storage"
JOB_ROOT = Path(
    os.getenv(
        "AI_VIDEO_JOB_ROOT",
        str(STORAGE / "v10_34" / "final_jobs"),
    )
)
AUTO_ROOT = Path(
    os.getenv(
        "AI_VIDEO_AUTO_PACKAGING_ROOT",
        str(STORAGE / "graphic_window" / "auto_packaging"),
    )
)
WORKFLOW_ROOT = Path(
    os.getenv(
        "AI_VIDEO_WORKFLOW_ROOT",
        str(STORAGE / "graphic_window" / "workflow"),
    )
)
DELIVERY_ROOT = Path(
    os.getenv(
        "AI_VIDEO_FINAL_DELIVERY_ROOT",
        str(STORAGE / "graphic_window" / "final_delivery"),
    )
)

FINAL_JOB_STATUS = {
    "completed",
    "succeeded",
    "success",
    "done",
    "finished",
}
FAILED_JOB_STATUS = {
    "failed",
    "error",
    "cancelled",
    "canceled",
}
APPROVED_STATUS = {
    "approved",
    "passed",
}
REJECTED_STATUS = {
    "rejected",
    "failed",
}


def _now() -> int:
    return int(time.time())


def _safe_job_id(value: str) -> str:
    cleaned = re.sub(
        r"[^A-Za-z0-9._-]+",
        "_",
        str(value or ""),
    )
    return cleaned.strip("._") or "unknown_job"


def _json_read(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(
            path.read_text(encoding="utf-8")
        )
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _atomic_json(
    path: Path,
    data: Dict[str, Any],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    temp = path.with_suffix(
        path.suffix + f".tmp.{os.getpid()}.{_now()}"
    )
    temp.write_text(
        json.dumps(
            jsonable_encoder(data),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    temp.replace(path)


def _job_json_path(job_id: str) -> Path:
    return JOB_ROOT / f"{job_id}.json"


def _job_dir(job_id: str) -> Path:
    return JOB_ROOT / job_id


def _workflow_dir(job_id: str) -> Path:
    return WORKFLOW_ROOT / _safe_job_id(job_id)


def _selection_path(job_id: str) -> Path:
    return _workflow_dir(job_id) / "selection.json"


def _delivery_meta_path(job_id: str) -> Path:
    return _workflow_dir(job_id) / "delivery.json"


def _automation_path(job_id: str) -> Path:
    return AUTO_ROOT / f"{_safe_job_id(job_id)}.json"



COMPOSE_REGISTRY_PATH = WORKFLOW_ROOT / "compose_registry.json"
VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm"}


def _compose_registry() -> Dict[str, Any]:
    return _json_read(COMPOSE_REGISTRY_PATH)


def _absolute_public_url(value: Any) -> str:
    raw = _string(value)
    if not raw:
        return ""

    parsed = urlparse(raw)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return raw

    base = (
        _string(
            os.getenv("AI_VIDEO_PUBLIC_BASE_URL")
        )
        or _string(
            os.getenv("PUBLIC_BASE_URL")
        )
        or "https://ai-video.47-76-143-158.sslip.io"
    ).rstrip("/")

    if raw.startswith("/"):
        return base + raw

    return base + "/" + raw.lstrip("/")


def _allowed_video_roots() -> List[Path]:
    candidates = [
        STORAGE,
        BASE / "backend" / "app" / "static",
        BASE / "backend" / "static",
        BASE / "backend" / "outputs",
        BASE / "backend" / "output",
        BASE / "outputs",
        BASE / "output",
        BASE / "frontend" / "public",
        Path("/tmp"),
    ]
    roots: List[Path] = []

    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except Exception:
            continue

        if resolved.exists() and resolved not in roots:
            roots.append(resolved)

    return roots


def _is_allowed_video(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except Exception:
        return False

    if (
        not resolved.exists()
        or not resolved.is_file()
        or resolved.suffix.lower() not in VIDEO_SUFFIXES
    ):
        return False

    for root in _allowed_video_roots():
        try:
            resolved.relative_to(root)
            return True
        except Exception:
            continue

    return False


def _video_candidates_from_url(
    raw_url: str,
) -> List[Path]:
    raw = _string(raw_url)
    if not raw:
        return []

    parsed = urlparse(raw)
    url_path = unquote(parsed.path or raw)
    candidates: List[Path] = []

    mappings = [
        ("/storage/", STORAGE),
        (
            "/static/",
            BASE / "backend" / "app" / "static",
        ),
        (
            "/media/",
            BASE / "backend" / "app" / "static",
        ),
        (
            "/outputs/",
            BASE / "backend" / "outputs",
        ),
    ]

    for prefix, root in mappings:
        if prefix in url_path:
            relative = url_path.split(prefix, 1)[1]
            candidates.append(root / relative)

    if url_path.startswith("/"):
        candidates.extend([
            BASE / url_path.lstrip("/"),
            BASE / "backend" / "app" / url_path.lstrip("/"),
        ])

    return candidates


def _resolve_compose_video(
    payload: Dict[str, Any],
) -> Path:
    explicit = _string(
        payload.get("local_path")
        or payload.get("video_path")
        or payload.get("output_path")
    )

    candidates: List[Path] = []

    if explicit:
        candidates.append(Path(explicit))

    candidates.extend(
        _video_candidates_from_url(
            _string(payload.get("video_url"))
        )
    )

    video_name = Path(
        _string(payload.get("video_name"))
    ).name

    if video_name:
        for root in _allowed_video_roots():
            candidates.extend([
                root / video_name,
                root / "videos" / video_name,
                root / "output" / video_name,
                root / "outputs" / video_name,
                root / "generated" / video_name,
            ])

    checked = set()

    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except Exception:
            continue

        key = str(resolved)
        if key in checked:
            continue
        checked.add(key)

        if _is_allowed_video(resolved):
            return resolved

    if video_name:
        job_root_resolved = JOB_ROOT.resolve()

        for root in _allowed_video_roots():
            try:
                for found in root.rglob(video_name):
                    try:
                        found_resolved = found.resolve()
                        found_resolved.relative_to(
                            job_root_resolved
                        )
                        # Do not rediscover a previously registered
                        # workflow copy as if it were the original
                        # /api/compose output.
                        continue
                    except ValueError:
                        pass
                    except Exception:
                        continue

                    if _is_allowed_video(found_resolved):
                        return found_resolved
            except Exception:
                continue

    raise HTTPException(
        status_code=422,
        detail=(
            "已经收到成片地址，但在服务器找不到对应视频文件。"
            "请确认 /api/compose 返回的 video_name 与本地文件一致。"
        ),
    )


def _split_keywords(value: Any) -> List[str]:
    if isinstance(value, list):
        return [
            _string(item)
            for item in value
            if _string(item)
        ][:30]

    return [
        item
        for item in re.split(
            r"[,，、\s]+",
            _string(value),
        )
        if item
    ][:30]


def _compose_fingerprint(
    video_path: Path,
    payload: Dict[str, Any],
) -> str:
    stat = video_path.stat()
    source = "|".join([
        str(video_path.resolve()),
        str(stat.st_size),
        str(stat.st_mtime_ns),
        _string(payload.get("video_url")),
        _string(payload.get("title")),
        _string(payload.get("script_text")),
    ])
    return hashlib.sha256(
        source.encode("utf-8")
    ).hexdigest()


def _link_or_copy(
    source: Path,
    destination: Path,
) -> None:
    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if destination.exists():
        return

    try:
        os.link(
            source,
            destination,
        )
    except Exception:
        shutil.copy2(
            source,
            destination,
        )


def _basic_srt(
    script_text: str,
) -> str:
    lines = [
        item.strip()
        for item in re.split(
            r"(?<=[。！？!?])\s*|\n+",
            script_text,
        )
        if item.strip()
    ]

    if not lines:
        return ""

    duration = max(
        2.0,
        min(
            6.0,
            42.0 / max(1, len(lines)),
        ),
    )
    rows = []

    def stamp(seconds: float) -> str:
        milliseconds = int(
            round(seconds * 1000)
        )
        hours, remainder = divmod(
            milliseconds,
            3_600_000,
        )
        minutes, remainder = divmod(
            remainder,
            60_000,
        )
        secs, millis = divmod(
            remainder,
            1000,
        )
        return (
            f"{hours:02d}:{minutes:02d}:"
            f"{secs:02d},{millis:03d}"
        )

    for index, line in enumerate(lines, 1):
        start = (index - 1) * duration
        end = index * duration
        rows.extend([
            str(index),
            f"{stamp(start)} --> {stamp(end)}",
            line,
            "",
        ])

    return "\n".join(rows)


def _register_compose_job(
    payload: Dict[str, Any],
) -> Tuple[str, bool, Dict[str, Any]]:
    video_path = _resolve_compose_video(
        payload
    )
    fingerprint = _compose_fingerprint(
        video_path,
        payload,
    )
    registry = _compose_registry()
    jobs = _dict(
        registry.get("jobs")
    )

    existing_job_id = _string(
        jobs.get(fingerprint)
    )

    if (
        existing_job_id
        and _job_json_path(
            existing_job_id
        ).exists()
    ):
        return (
            existing_job_id,
            True,
            _json_read(
                _job_json_path(
                    existing_job_id
                )
            ),
        )

    job_id = (
        "mainui_v10401_"
        + fingerprint[:20]
    )
    job_dir = _job_dir(job_id)
    job_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    target_suffix = (
        video_path.suffix.lower()
        if video_path.suffix.lower()
        in VIDEO_SUFFIXES
        else ".mp4"
    )
    target_video = (
        job_dir
        / f"final_video{target_suffix}"
    )
    _link_or_copy(
        video_path,
        target_video,
    )

    title = (
        _string(payload.get("title"))
        or "主界面合成视频"
    )
    script_text = _string(
        payload.get("script_text")
        or payload.get("script")
    )
    keywords = _split_keywords(
        payload.get("keywords")
    )
    video_url = _absolute_public_url(
        payload.get("video_url")
    )
    video_name = (
        _string(payload.get("video_name"))
        or video_path.name
    )
    duration = float(
        payload.get("duration_seconds")
        or 0
    )

    (job_dir / "script.txt").write_text(
        script_text,
        encoding="utf-8",
    )
    (job_dir / "source.json").write_text(
        json.dumps(
            jsonable_encoder(payload),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    srt_text = _basic_srt(
        script_text
    )
    if srt_text:
        (job_dir / "subtitles.srt").write_text(
            srt_text,
            encoding="utf-8",
        )

    timestamp = _now()
    result = {
        "video_url": video_url,
        "video_name": video_name,
        "local_path": str(target_video),
        "video_path": str(target_video),
        "output_path": str(target_video),
        "final_video_path": str(target_video),
        "subtitled_video_path": str(target_video),
        "duration_seconds": duration,
    }

    job = {
        "ok": True,
        "job_id": job_id,
        "status": "completed",
        "progress": 100,
        "stage": "main_ui_compose_registered",
        "source_type": "main_ui_compose",
        "created_at": timestamp,
        "updated_at": timestamp,
        "video_url": video_url,
        "video_name": video_name,
        "local_path": str(target_video),
        "video_path": str(target_video),
        "output_path": str(target_video),
        "final_video_path": str(target_video),
        "subtitled_video_path": str(target_video),
        "duration_seconds": duration,
        "subtitle_source": "original_script",
        "request": {
            "title": title,
            "topic": title,
            "script_text": script_text,
            "script": script_text,
            "keywords": keywords,
            "manual_keywords": keywords,
            "description": _string(
                payload.get("description")
            ),
            "cta": _string(
                payload.get("cta")
            ),
            "style": _string(
                payload.get("style")
            ),
            "platform": _string(
                payload.get("platform")
                or "小红书"
            ),
            "source": _string(
                payload.get("source")
                or "main_interface_compose"
            ),
        },
        "result": {
            **result,
            "subtitle_source": "original_script",
        },
        "final_video": {
            "url": video_url,
            "path": str(target_video),
            "local_path": str(target_video),
            "name": video_name,
        },
        "child_job": {
            "job_id": job_id,
            "status": "completed",
            "progress": 100,
            "stage": "main_ui_compose_registered",
            "result": result,
        },
        "workflow_bridge": {
            "version": VERSION,
            "fingerprint": fingerprint,
            "source_video_path": str(
                video_path
            ),
            "registered_video_path": str(
                target_video
            ),
        },
    }

    _atomic_json(
        _job_json_path(job_id),
        job,
    )

    jobs[fingerprint] = job_id
    registry.update({
        "version": VERSION,
        "updated_at": timestamp,
        "jobs": jobs,
    })
    _atomic_json(
        COMPOSE_REGISTRY_PATH,
        registry,
    )

    return job_id, False, job

def _string(value: Any) -> str:
    return str(value or "").strip()


def _dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _status(value: Any) -> str:
    return _string(value).lower()


def _is_job_done(job: Dict[str, Any]) -> bool:
    status = _status(job.get("status"))
    stage = _status(job.get("stage"))
    joined = f"{status} {stage}"
    return any(
        token in joined
        for token in FINAL_JOB_STATUS
    )


def _is_job_failed(job: Dict[str, Any]) -> bool:
    status = _status(job.get("status"))
    stage = _status(job.get("stage"))
    joined = f"{status} {stage}"
    return any(
        token in joined
        for token in FAILED_JOB_STATUS
    )


def _review_approved(review: Dict[str, Any]) -> bool:
    return (
        bool(review.get("approved"))
        or _status(review.get("status"))
        in APPROVED_STATUS
    )


def _review_rejected(review: Dict[str, Any]) -> bool:
    return (
        review.get("approved") is False
        and _status(review.get("status"))
        in REJECTED_STATUS
    )


def _packaging_completed(
    packaging: Dict[str, Any],
) -> bool:
    if not packaging:
        return False

    status = _status(packaging.get("status"))
    if status == "completed":
        return True

    cover = _dict(
        packaging.get("cover_result")
    )
    xhs = _dict(
        packaging.get("xhs_result")
    )
    return (
        cover.get("ok") is True
        and xhs.get("ok") is True
    )


def _package_cover_result(
    packaging: Dict[str, Any],
    review: Dict[str, Any],
) -> Dict[str, Any]:
    cover = _dict(
        packaging.get("cover_result")
    )
    if cover:
        return cover

    automation = _dict(
        packaging.get("automation")
    )
    cover = _dict(
        automation.get("cover_result")
    )
    if cover:
        return cover

    return _dict(review.get("cover_result"))


def _package_xhs_result(
    packaging: Dict[str, Any],
) -> Dict[str, Any]:
    xhs = _dict(
        packaging.get("xhs_result")
    )
    if xhs:
        return xhs

    automation = _dict(
        packaging.get("automation")
    )
    return _dict(
        automation.get("xhs_result")
    )


def _safe_payload_from_job(
    job_id: str,
    job: Dict[str, Any],
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    request = _dict(job.get("request"))
    extra = _dict(payload)

    raw_keywords = (
        extra.get("keywords")
        or request.get("keywords")
        or request.get("manual_keywords")
        or []
    )

    if isinstance(raw_keywords, str):
        keywords = [
            item
            for item in re.split(
                r"[,，、\s]+",
                raw_keywords,
            )
            if item
        ]
    else:
        keywords = [
            _string(item)
            for item in _list(raw_keywords)
            if _string(item)
        ]

    return {
        "job_id": job_id,
        "title": (
            _string(extra.get("title"))
            or _string(request.get("title"))
            or _string(request.get("topic"))
            or "AI 视频发布素材"
        ),
        "script_text": (
            _string(extra.get("script_text"))
            or _string(request.get("script_text"))
            or _string(request.get("script"))
        ),
        "keywords": keywords,
        "platform": (
            _string(extra.get("platform"))
            or "小红书"
        ),
        "style": (
            _string(extra.get("style"))
            or "专业顾问"
        ),
        "slide_count": int(
            extra.get("slide_count")
            or 7
        ),
        "cta": (
            _string(extra.get("cta"))
            or _string(request.get("cta"))
            or "留下预算和用途，我帮你拆解"
        ),
    }


async def _internal_json(
    app: FastAPI,
    method: str,
    path: str,
    payload: Optional[Dict[str, Any]] = None,
    timeout: float = 180.0,
) -> Tuple[int, Dict[str, Any]]:
    transport = httpx.ASGITransport(
        app=app,
    )
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://internal",
        timeout=timeout,
    ) as client:
        response = await client.request(
            method.upper(),
            path,
            json=payload,
        )

    try:
        data = response.json()
    except Exception:
        data = {
            "ok": False,
            "error": "non_json_response",
            "body": response.text[:2000],
        }

    if not isinstance(data, dict):
        data = {
            "ok": False,
            "value": data,
        }

    return response.status_code, data


async def _get_optional(
    app: FastAPI,
    path: str,
) -> Dict[str, Any]:
    status, data = await _internal_json(
        app,
        "GET",
        path,
        timeout=60,
    )

    if status == 404:
        return {}

    if status >= 400:
        return {
            "ok": False,
            "error": "upstream_error",
            "status_code": status,
            "detail": data,
        }

    return data


async def _load_job(
    app: FastAPI,
    job_id: str,
) -> Dict[str, Any]:
    status, data = await _internal_json(
        app,
        "GET",
        f"/api/video/full-ai/one-scene/job/{job_id}",
        timeout=60,
    )

    if status < 400 and data:
        returned_job_id = _string(
            data.get("job_id")
        )
        if returned_job_id and returned_job_id != job_id:
            raise HTTPException(
                status_code=409,
                detail=(
                    "任务接口返回了不同 job_id，"
                    "为避免串任务已停止。"
                ),
            )
        return data

    local = _json_read(
        _job_json_path(job_id)
    )

    if local:
        returned_job_id = _string(
            local.get("job_id")
        )
        if returned_job_id and returned_job_id != job_id:
            raise HTTPException(
                status_code=409,
                detail=(
                    "本地任务文件 job_id 不一致，"
                    "为避免串任务已停止。"
                ),
            )
        return local

    raise HTTPException(
        status_code=404,
        detail=f"找不到任务：{job_id}",
    )


def _selection_for(
    job_id: str,
) -> Dict[str, Any]:
    return _json_read(
        _selection_path(job_id)
    )


def _delivery_for(
    job_id: str,
) -> Dict[str, Any]:
    return _json_read(
        _delivery_meta_path(job_id)
    )


def _image_urls(
    result: Dict[str, Any],
) -> List[Dict[str, Any]]:
    return [
        item
        for item in _list(result.get("images"))
        if isinstance(item, dict)
    ]


def _cover_count(
    cover: Dict[str, Any],
) -> int:
    return int(
        cover.get("cover_count")
        or len(_image_urls(cover))
        or 0
    )


def _xhs_count(
    xhs: Dict[str, Any],
) -> int:
    return int(
        xhs.get("page_count")
        or len(_image_urls(xhs))
        or 0
    )


def _next_action(
    job: Dict[str, Any],
    review: Dict[str, Any],
    gate: Dict[str, Any],
    packaging: Dict[str, Any],
    selection: Dict[str, Any],
    delivery: Dict[str, Any],
) -> str:
    if _is_job_failed(job):
        return "fix_video_job"

    if not _is_job_done(job):
        return "wait_for_video"

    if not review:
        return "run_review"

    review_status = _status(
        review.get("status")
    )

    if review_status in {
        "",
        "not_reviewed",
        "review_error",
        "error",
    }:
        return "run_review"

    if review_status in {
        "running",
        "pending",
        "reviewing",
    }:
        return "wait_for_review"

    if _review_rejected(review):
        return "return_to_edit"

    mechanical = _dict(
        review.get("mechanical")
    )
    if (
        review_status == "review_failed"
        and mechanical.get("passed") is False
    ):
        return "return_to_edit"

    if not _review_approved(review):
        return "human_review"

    unlocked = (
        gate.get("packaging_unlocked") is True
        or review.get("packaging_unlocked") is True
    )

    if not unlocked:
        return "human_review"

    if not _packaging_completed(packaging):
        return "backfill_packaging"

    if not selection:
        return "select_cover"

    if not delivery:
        return "build_final_delivery"

    return "ready_to_publish"


def _stage_payload(
    next_action: str,
) -> Tuple[int, List[Dict[str, Any]]]:
    mapping = {
        "wait_for_video": 4,
        "fix_video_job": 4,
        "run_review": 4,
        "wait_for_review": 4,
        "human_review": 4,
        "return_to_edit": 4,
        "backfill_packaging": 5,
        "select_cover": 5,
        "build_final_delivery": 6,
        "ready_to_publish": 6,
    }
    active = mapping.get(
        next_action,
        1,
    )

    labels = [
        "内容来源",
        "文案与声音",
        "镜头与素材",
        "成片与审查",
        "封面与图文",
        "发布与交付",
    ]

    stages = []

    for index, label in enumerate(
        labels,
        1,
    ):
        if (
            next_action == "ready_to_publish"
            and index <= 6
        ):
            state = "done"
        elif index < active:
            state = "done"
        elif index == active:
            state = "active"
        else:
            state = "pending"

        stages.append({
            "index": index,
            "label": label,
            "state": state,
        })

    return active, stages


def _normalize_packaging(
    packaging: Dict[str, Any],
    review: Dict[str, Any],
) -> Dict[str, Any]:
    if not packaging:
        return {}

    cover = _package_cover_result(
        packaging,
        review,
    )
    xhs = _package_xhs_result(
        packaging,
    )

    normalized = dict(packaging)
    normalized["cover_result"] = cover
    normalized["xhs_result"] = xhs
    normalized["cover_count"] = _cover_count(
        cover
    )
    normalized["page_count"] = _xhs_count(
        xhs
    )
    normalized["completed"] = (
        _packaging_completed(packaging)
    )
    return normalized


async def _workflow_snapshot(
    app: FastAPI,
    job_id: str,
) -> Dict[str, Any]:
    job = await _load_job(
        app,
        job_id,
    )

    review = await _get_optional(
        app,
        f"/api/video/review/{job_id}",
    )
    gate = await _get_optional(
        app,
        f"/api/video/review/{job_id}/gate",
    )
    packaging = await _get_optional(
        app,
        f"/api/graphic-window/automation/{job_id}",
    )

    if (
        packaging.get("error")
        or packaging.get("detail")
    ):
        packaging = {}

    if not packaging:
        packaging = _json_read(
            _automation_path(job_id)
        )

    packaging = _normalize_packaging(
        packaging,
        review,
    )

    selection = _selection_for(
        job_id,
    )
    delivery = _delivery_for(
        job_id,
    )

    next_action = _next_action(
        job,
        review,
        gate,
        packaging,
        selection,
        delivery,
    )
    stage_index, stages = _stage_payload(
        next_action
    )

    return {
        "ok": True,
        "version": VERSION,
        "mode": MODE,
        "job_id": job_id,
        "strict_job_binding": True,
        "job": job,
        "review": review,
        "gate": gate,
        "packaging": packaging,
        "selection": selection,
        "delivery": delivery,
        "next_action": next_action,
        "stage_index": stage_index,
        "stages": stages,
        "updated_at": _now(),
    }


def _packaging_manifest(
    job_id: str,
    payload: Dict[str, Any],
    cover_result: Dict[str, Any],
    xhs_result: Dict[str, Any],
) -> Dict[str, Any]:
    cover_ok = (
        cover_result.get("ok") is True
        and _cover_count(cover_result) >= 3
    )
    xhs_ok = (
        xhs_result.get("ok") is True
        and _xhs_count(xhs_result) >= 7
    )

    if cover_ok and xhs_ok:
        status = "completed"
    elif cover_ok or xhs_ok:
        status = "partial_failed"
    else:
        status = "failed"

    errors = []

    if not cover_ok:
        errors.append(
            "三套封面未完整生成"
        )

    if not xhs_ok:
        errors.append(
            "七页小红书图文未完整生成"
        )

    return {
        "version": VERSION,
        "mode": "workflow_backfill_packaging",
        "status": status,
        "job_id": job_id,
        "approved": True,
        "started_at": _now(),
        "completed_at": _now(),
        "request_payload": payload,
        "cover_result": cover_result,
        "xhs_result": xhs_result,
        "cover_ok": cover_ok,
        "xhs_ok": xhs_ok,
        "errors": errors,
        "manifest_path": str(
            _automation_path(job_id)
        ),
        "source": "v10_40_workflow_hub",
    }


def _persist_packaging(
    job_id: str,
    manifest: Dict[str, Any],
) -> None:
    _atomic_json(
        _automation_path(job_id),
        manifest,
    )

    job_dir = _job_dir(job_id)
    if job_dir.exists():
        _atomic_json(
            job_dir
            / "auto_packaging_result.json",
            manifest,
        )

    job_json = _job_json_path(job_id)
    if job_json.exists():
        job = _json_read(job_json)
        job["auto_packaging"] = {
            "version": manifest.get("version"),
            "mode": manifest.get("mode"),
            "status": manifest.get("status"),
            "updated_at": manifest.get(
                "completed_at"
            ),
            "manifest_path": manifest.get(
                "manifest_path"
            ),
            "cover_count": _cover_count(
                _dict(
                    manifest.get("cover_result")
                )
            ),
            "page_count": _xhs_count(
                _dict(
                    manifest.get("xhs_result")
                )
            ),
        }
        _atomic_json(
            job_json,
            job,
        )


async def _backfill_packaging(
    app: FastAPI,
    job_id: str,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    snapshot = await _workflow_snapshot(
        app,
        job_id,
    )

    existing_packaging = _dict(
        snapshot.get("packaging")
    )
    if _packaging_completed(
        existing_packaging
    ):
        return existing_packaging

    review = _dict(
        snapshot.get("review")
    )
    gate = _dict(
        snapshot.get("gate")
    )

    unlocked = (
        gate.get("packaging_unlocked") is True
        or review.get("packaging_unlocked") is True
    )

    if not _review_approved(review) or not unlocked:
        raise HTTPException(
            status_code=409,
            detail=(
                "只有已经人工批准并解锁包装的任务"
                "才能补齐封面和图文。"
            ),
        )

    job = _dict(snapshot.get("job"))
    request_payload = _safe_payload_from_job(
        job_id,
        job,
        payload,
    )

    cover_status, cover_result = await _internal_json(
        app,
        "POST",
        "/api/graphic-window/video-cover/generate",
        request_payload,
        timeout=240,
    )

    if cover_status >= 400:
        cover_result = {
            "ok": False,
            "error": "cover_generation_failed",
            "status_code": cover_status,
            "detail": cover_result,
        }

    xhs_status, xhs_result = await _internal_json(
        app,
        "POST",
        "/api/graphic-window/xiaohongshu/generate",
        request_payload,
        timeout=240,
    )

    if xhs_status >= 400:
        xhs_result = {
            "ok": False,
            "error": "xhs_generation_failed",
            "status_code": xhs_status,
            "detail": xhs_result,
        }

    manifest = _packaging_manifest(
        job_id,
        request_payload,
        cover_result,
        xhs_result,
    )
    _persist_packaging(
        job_id,
        manifest,
    )

    return manifest


def _allowed_local_path(
    value: Any,
) -> Optional[Path]:
    raw = _string(value)
    if not raw:
        return None

    path = Path(raw)

    try:
        resolved = path.resolve()
        base = BASE.resolve()
        resolved.relative_to(base)
    except Exception:
        return None

    if not resolved.exists() or not resolved.is_file():
        return None

    return resolved


def _recursive_find_path(
    value: Any,
    keys: Iterable[str],
) -> Optional[Path]:
    key_set = {
        item.lower()
        for item in keys
    }

    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in key_set:
                path = _allowed_local_path(item)
                if path:
                    return path

        for item in value.values():
            found = _recursive_find_path(
                item,
                keys,
            )
            if found:
                return found

    if isinstance(value, list):
        for item in value:
            found = _recursive_find_path(
                item,
                keys,
            )
            if found:
                return found

    return None


def _public_base(
    results: Iterable[Dict[str, Any]],
) -> str:
    explicit = (
        _string(
            os.getenv(
                "AI_VIDEO_PUBLIC_BASE_URL"
            )
        )
        or _string(
            os.getenv("PUBLIC_BASE_URL")
        )
    )

    if explicit:
        return explicit.rstrip("/")

    for result in results:
        candidates = [
            result.get("download_zip_url"),
            result.get("content_trace_url"),
        ]
        candidates.extend(
            item.get("url")
            for item in _image_urls(result)
        )

        for value in candidates:
            raw = _string(value)
            if "/storage/" not in raw:
                continue

            parsed = urlparse(raw)
            if parsed.scheme and parsed.netloc:
                return (
                    f"{parsed.scheme}://"
                    f"{parsed.netloc}"
                )

    return (
        "https://ai-video.47-76-143-158.sslip.io"
    )


def _storage_url(
    path: Path,
    public_base: str,
) -> str:
    try:
        relative = path.resolve().relative_to(
            STORAGE.resolve()
        )
    except Exception:
        return ""

    return (
        public_base.rstrip("/")
        + "/storage/"
        + str(relative).replace(os.sep, "/")
    )


def _write_text(
    path: Path,
    text: str,
) -> None:
    path.write_text(
        text,
        encoding="utf-8",
    )


def _zip_add(
    archive: zipfile.ZipFile,
    path: Optional[Path],
    arcname: str,
) -> bool:
    if not path:
        return False

    if not path.exists() or not path.is_file():
        return False

    archive.write(
        path,
        arcname=arcname,
    )
    return True


def _selected_cover(
    cover_result: Dict[str, Any],
    selection: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], int]:
    images = _image_urls(
        cover_result
    )

    if not images:
        return None, -1

    selected_url = _string(
        selection.get("url")
    )
    selected_index = int(
        selection.get("index")
        if selection.get("index") is not None
        else -1
    )

    if selected_url:
        for index, item in enumerate(images):
            if _string(item.get("url")) == selected_url:
                return item, index

    if 0 <= selected_index < len(images):
        return images[selected_index], selected_index

    return images[0], 0


def _publish_copy(
    cover_result: Dict[str, Any],
    xhs_result: Dict[str, Any],
) -> str:
    title = (
        _string(
            xhs_result.get("publish_title")
        )
        or _string(
            cover_result.get("publish_title")
        )
    )
    description = (
        _string(
            xhs_result.get(
                "publish_description"
            )
        )
        or _string(
            cover_result.get(
                "publish_description"
            )
        )
    )
    hashtags = (
        _list(xhs_result.get("hashtags"))
        or _list(cover_result.get("hashtags"))
    )
    hashtag_text = " ".join(
        f"#{_string(item).lstrip('#')}"
        for item in hashtags
        if _string(item)
    )

    return "\n\n".join(
        item
        for item in [
            title,
            description,
            hashtag_text,
        ]
        if item
    )


async def _build_delivery(
    app: FastAPI,
    job_id: str,
) -> Dict[str, Any]:
    snapshot = await _workflow_snapshot(
        app,
        job_id,
    )
    packaging = _dict(
        snapshot.get("packaging")
    )
    review = _dict(
        snapshot.get("review")
    )
    job = _dict(
        snapshot.get("job")
    )
    selection = _dict(
        snapshot.get("selection")
    )

    if not _packaging_completed(packaging):
        raise HTTPException(
            status_code=409,
            detail="封面和图文包还没有完整生成。",
        )

    cover_result = _package_cover_result(
        packaging,
        review,
    )
    xhs_result = _package_xhs_result(
        packaging,
    )

    selected, selected_index = _selected_cover(
        cover_result,
        selection,
    )

    if not selected:
        raise HTTPException(
            status_code=409,
            detail="还没有可用封面。",
        )

    if not selection:
        selection = {
            "job_id": job_id,
            "index": selected_index,
            "url": selected.get("url"),
            "path": selected.get("path"),
            "selected_at": _now(),
            "auto_selected": True,
        }
        _atomic_json(
            _selection_path(job_id),
            selection,
        )

    package_id = (
        f"final_delivery_v1040_"
        f"{_safe_job_id(job_id)}_"
        f"{_now()}"
    )
    package_dir = DELIVERY_ROOT / package_id
    package_dir.mkdir(
        parents=True,
        exist_ok=False,
    )

    manifest_path = (
        package_dir
        / "workflow_manifest.json"
    )
    review_path = (
        package_dir
        / "review_report.json"
    )
    publish_path = (
        package_dir
        / "publish_copy.txt"
    )

    workflow_manifest = {
        "version": VERSION,
        "mode": MODE,
        "job_id": job_id,
        "package_id": package_id,
        "selected_cover": selection,
        "video_status": job.get("status"),
        "review_status": review.get("status"),
        "review_score": review.get(
            "overall_score"
        ),
        "cover_count": _cover_count(
            cover_result
        ),
        "page_count": _xhs_count(
            xhs_result
        ),
        "created_at": _now(),
    }

    _atomic_json(
        manifest_path,
        workflow_manifest,
    )
    _atomic_json(
        review_path,
        review,
    )
    _write_text(
        publish_path,
        _publish_copy(
            cover_result,
            xhs_result,
        ),
    )

    video_path = (
        _allowed_local_path(
            _dict(
                review.get("mechanical")
            ).get("local_path")
        )
        or _recursive_find_path(
            job,
            {
                "final_video_path",
                "subtitled_video_path",
                "output_path",
                "local_path",
                "video_path",
            },
        )
    )

    selected_path = _allowed_local_path(
        selected.get("path")
    )

    cover_local_paths = [
        path
        for path in (
            _allowed_local_path(
                item.get("path")
            )
            for item in _image_urls(
                cover_result
            )
        )
        if path
    ]
    xhs_local_paths = [
        path
        for path in (
            _allowed_local_path(
                item.get("path")
            )
            for item in _image_urls(
                xhs_result
            )
        )
        if path
    ]

    if not video_path:
        raise HTTPException(
            status_code=409,
            detail=(
                "最终视频本地文件不存在，"
                "停止生成不完整交付包。"
            ),
        )

    if not selected_path:
        raise HTTPException(
            status_code=409,
            detail=(
                "主封面本地文件不存在，"
                "停止生成不完整交付包。"
            ),
        )

    if len(cover_local_paths) < 3:
        raise HTTPException(
            status_code=409,
            detail=(
                "本地三套封面文件不完整，"
                "请先重试封面包装。"
            ),
        )

    if len(xhs_local_paths) < 7:
        raise HTTPException(
            status_code=409,
            detail=(
                "本地七页图文文件不完整，"
                "请先重试小红书包装。"
            ),
        )

    trace_path = (
        _allowed_local_path(
            xhs_result.get(
                "content_trace_path"
            )
        )
    )

    if not trace_path:
        package_id_xhs = _string(
            xhs_result.get("package_id")
        )
        if package_id_xhs:
            candidate = (
                STORAGE
                / "graphic_window"
                / package_id_xhs
                / "content_trace.json"
            )
            trace_path = _allowed_local_path(
                candidate
            )

    if not trace_path:
        raise HTTPException(
            status_code=409,
            detail=(
                "事实链文件不存在，"
                "停止生成不完整交付包。"
            ),
        )

    zip_path = package_dir / "final_delivery.zip"

    included = []

    with zipfile.ZipFile(
        zip_path,
        "w",
        zipfile.ZIP_DEFLATED,
    ) as archive:
        if _zip_add(
            archive,
            video_path,
            "final_video.mp4",
        ):
            included.append(
                "final_video.mp4"
            )

        selected_suffix = (
            selected_path.suffix.lower()
            if selected_path
            else ".jpg"
        )
        if selected_suffix not in {
            ".jpg",
            ".jpeg",
            ".png",
            ".webp",
        }:
            selected_suffix = ".jpg"

        if _zip_add(
            archive,
            selected_path,
            f"selected_cover{selected_suffix}",
        ):
            included.append(
                f"selected_cover{selected_suffix}"
            )

        for index, item in enumerate(
            _image_urls(cover_result),
            1,
        ):
            path = _allowed_local_path(
                item.get("path")
            )
            suffix = (
                path.suffix.lower()
                if path
                else ".jpg"
            )
            arcname = (
                f"all_3_covers/"
                f"cover_{index:02d}{suffix}"
            )
            if _zip_add(
                archive,
                path,
                arcname,
            ):
                included.append(arcname)

        for index, item in enumerate(
            _image_urls(xhs_result),
            1,
        ):
            path = _allowed_local_path(
                item.get("path")
            )
            suffix = (
                path.suffix.lower()
                if path
                else ".jpg"
            )
            arcname = (
                f"xiaohongshu_7_pages/"
                f"xhs_{index:02d}{suffix}"
            )
            if _zip_add(
                archive,
                path,
                arcname,
            ):
                included.append(arcname)

        archive.write(
            publish_path,
            arcname="publish_copy.txt",
        )
        archive.write(
            review_path,
            arcname="review_report.json",
        )
        archive.write(
            manifest_path,
            arcname="workflow_manifest.json",
        )
        included.extend([
            "publish_copy.txt",
            "review_report.json",
            "workflow_manifest.json",
        ])

        if _zip_add(
            archive,
            trace_path,
            "content_trace.json",
        ):
            included.append(
                "content_trace.json"
            )

    public_base = _public_base(
        [
            cover_result,
            xhs_result,
        ]
    )

    delivery = {
        "ok": True,
        "version": VERSION,
        "mode": "final_delivery_bundle",
        "job_id": job_id,
        "package_id": package_id,
        "selected_cover": selection,
        "included_files": included,
        "zip_path": str(zip_path),
        "download_zip_url": _storage_url(
            zip_path,
            public_base,
        ),
        "created_at": _now(),
    }

    _atomic_json(
        _delivery_meta_path(job_id),
        delivery,
    )

    job_json = _job_json_path(job_id)
    if job_json.exists():
        current = _json_read(job_json)
        current["final_delivery"] = delivery
        current["selected_cover"] = selection
        _atomic_json(
            job_json,
            current,
        )

    return delivery



async def _auto_review_registered_job(
    app: FastAPI,
    job_id: str,
) -> None:
    try:
        status, result = await _internal_json(
            app,
            "POST",
            f"/api/video/review/{job_id}/run",
            {
                "source": (
                    "main_interface_auto_review"
                ),
            },
            timeout=300,
        )

        record = {
            "version": VERSION,
            "job_id": job_id,
            "status_code": status,
            "ok": status < 400,
            "completed_at": _now(),
            "result": result,
        }
    except Exception as exc:
        record = {
            "version": VERSION,
            "job_id": job_id,
            "status_code": 0,
            "ok": False,
            "completed_at": _now(),
            "error": str(exc),
        }

    _atomic_json(
        _workflow_dir(job_id)
        / "auto_review_launch.json",
        record,
    )


def install_main_workflow_provider(
    app: FastAPI,
) -> None:
    if getattr(
        app.state,
        "main_workflow_provider_installed",
        False,
    ):
        return

    app.state.main_workflow_provider_installed = True

    for directory in (
        WORKFLOW_ROOT,
        DELIVERY_ROOT,
        AUTO_ROOT,
    ):
        directory.mkdir(
            parents=True,
            exist_ok=True,
        )

    @app.get(
        "/api/video/workflow/health"
    )
    def workflow_health():
        return {
            "ok": True,
            "version": VERSION,
            "mode": MODE,
            "strict_job_binding": True,
            "historical_packaging_backfill": True,
            "final_delivery_bundle": True,
            "main_ui_compose_bridge": True,
            "auto_review_after_compose": True,
            "stages": 6,
            "fal_called": False,
            "regenerate_video": False,
        }

    @app.post(
        "/api/video/workflow/register-compose"
    )
    async def register_compose(
        background_tasks: BackgroundTasks,
        payload: Dict[str, Any] = Body(
            default_factory=dict
        ),
    ):
        if not _string(
            payload.get("video_url")
            or payload.get("video_name")
            or payload.get("local_path")
        ):
            raise HTTPException(
                status_code=422,
                detail="缺少成片地址或文件名。",
            )

        job_id, cached, job = (
            _register_compose_job(
                payload
            )
        )
        snapshot = await _workflow_snapshot(
            app,
            job_id,
        )

        should_auto_review = (
            snapshot.get("next_action")
            == "run_review"
        )

        if should_auto_review:
            background_tasks.add_task(
                _auto_review_registered_job,
                app,
                job_id,
            )

        return {
            "ok": True,
            "version": VERSION,
            "mode": "main_ui_compose_bridge",
            "job_id": job_id,
            "cached": cached,
            "job": job,
            "workflow": snapshot,
            "next_action": snapshot.get(
                "next_action"
            ),
            "auto_review_scheduled": (
                should_auto_review
            ),
            "run_review_endpoint": (
                f"/api/video/workflow/"
                f"{job_id}/run-review"
            ),
        }

    @app.get(
        "/api/video/workflow/{job_id}"
    )
    async def get_workflow(
        job_id: str,
    ):
        return await _workflow_snapshot(
            app,
            job_id,
        )

    @app.post(
        "/api/video/workflow/{job_id}/run-review"
    )
    async def run_review(
        job_id: str,
        payload: Dict[str, Any] = Body(
            default_factory=dict
        ),
    ):
        await _load_job(
            app,
            job_id,
        )
        status, result = await _internal_json(
            app,
            "POST",
            f"/api/video/review/{job_id}/run",
            payload,
            timeout=240,
        )

        if status >= 400:
            raise HTTPException(
                status_code=status,
                detail=result,
            )

        return await _workflow_snapshot(
            app,
            job_id,
        )

    @app.post(
        "/api/video/workflow/{job_id}/approve"
    )
    async def approve_workflow(
        job_id: str,
        payload: Dict[str, Any] = Body(
            default_factory=dict
        ),
    ):
        job = await _load_job(
            app,
            job_id,
        )
        request_payload = {
            **_safe_payload_from_job(
                job_id,
                job,
                payload,
            ),
            **payload,
            "reviewer": (
                _string(
                    payload.get("reviewer")
                )
                or "human_main_interface"
            ),
            "generate_cover": False,
            "generate_xhs": False,
            "auto_package": True,
        }

        status, result = await _internal_json(
            app,
            "POST",
            f"/api/video/review/{job_id}/approve",
            request_payload,
            timeout=360,
        )

        if status >= 400:
            raise HTTPException(
                status_code=status,
                detail=result,
            )

        snapshot = await _workflow_snapshot(
            app,
            job_id,
        )

        if (
            snapshot.get("next_action")
            == "backfill_packaging"
        ):
            await _backfill_packaging(
                app,
                job_id,
                request_payload,
            )
            snapshot = await _workflow_snapshot(
                app,
                job_id,
            )

        snapshot["approval_result"] = result
        return snapshot

    @app.post(
        "/api/video/workflow/{job_id}/reject"
    )
    async def reject_workflow(
        job_id: str,
        payload: Dict[str, Any] = Body(
            default_factory=dict
        ),
    ):
        await _load_job(
            app,
            job_id,
        )
        request_payload = {
            **payload,
            "reviewer": (
                _string(
                    payload.get("reviewer")
                )
                or "human_main_interface"
            ),
            "reason": (
                _string(
                    payload.get("reason")
                )
                or "主界面人工驳回，返回文案或镜头修改"
            ),
        }
        status, result = await _internal_json(
            app,
            "POST",
            f"/api/video/review/{job_id}/reject",
            request_payload,
            timeout=120,
        )

        if status >= 400:
            raise HTTPException(
                status_code=status,
                detail=result,
            )

        snapshot = await _workflow_snapshot(
            app,
            job_id,
        )
        snapshot["reject_result"] = result
        return snapshot

    @app.post(
        "/api/video/workflow/{job_id}/human-override"
    )
    async def human_override(
        job_id: str,
        payload: Dict[str, Any] = Body(
            default_factory=dict
        ),
    ):
        job = await _load_job(
            app,
            job_id,
        )
        override_note = (
            _string(
                payload.get("note")
                or payload.get("reason")
            )
            or "人工完整观看后确认审片提示为误报"
        )

        request_payload = {
            **_safe_payload_from_job(
                job_id,
                job,
                payload,
            ),
            **payload,
            "reviewer": (
                _string(
                    payload.get("reviewer")
                )
                or "human_main_interface"
            ),
            "decision": (
                _string(
                    payload.get("decision")
                )
                or "approved"
            ),
            "status": (
                _string(
                    payload.get("status")
                )
                or "approved"
            ),
            "note": override_note,
            "reason": override_note,
            "generate_cover": False,
            "generate_xhs": False,
            "auto_package": True,
        }

        status, result = await _internal_json(
            app,
            "POST",
            (
                f"/api/video/review/"
                f"{job_id}/human-override"
            ),
            request_payload,
            timeout=240,
        )

        if status >= 400:
            raise HTTPException(
                status_code=status,
                detail=result,
            )

        snapshot = await _workflow_snapshot(
            app,
            job_id,
        )

        if (
            snapshot.get("next_action")
            == "backfill_packaging"
        ):
            await _backfill_packaging(
                app,
                job_id,
                request_payload,
            )
            snapshot = await _workflow_snapshot(
                app,
                job_id,
            )

        snapshot["override_result"] = result
        return snapshot

    @app.post(
        "/api/video/workflow/{job_id}/backfill-packaging"
    )
    async def backfill_packaging(
        job_id: str,
        payload: Dict[str, Any] = Body(
            default_factory=dict
        ),
    ):
        manifest = await _backfill_packaging(
            app,
            job_id,
            payload,
        )
        snapshot = await _workflow_snapshot(
            app,
            job_id,
        )
        snapshot["backfill_result"] = manifest
        return snapshot

    @app.post(
        "/api/video/workflow/{job_id}/select-cover"
    )
    async def select_cover(
        job_id: str,
        payload: Dict[str, Any] = Body(
            default_factory=dict
        ),
    ):
        snapshot = await _workflow_snapshot(
            app,
            job_id,
        )
        packaging = _dict(
            snapshot.get("packaging")
        )
        review = _dict(
            snapshot.get("review")
        )
        cover_result = _package_cover_result(
            packaging,
            review,
        )
        images = _image_urls(
            cover_result
        )

        if not images:
            raise HTTPException(
                status_code=409,
                detail="该任务还没有封面。",
            )

        index = int(
            payload.get("index")
            if payload.get("index") is not None
            else -1
        )
        url = _string(
            payload.get("url")
        )

        selected = None

        if url:
            for item in images:
                if _string(item.get("url")) == url:
                    selected = item
                    index = images.index(item)
                    break

        if selected is None:
            if not 0 <= index < len(images):
                raise HTTPException(
                    status_code=422,
                    detail="封面序号无效。",
                )
            selected = images[index]

        selection = {
            "job_id": job_id,
            "index": index,
            "url": selected.get("url"),
            "path": selected.get("path"),
            "title": selected.get("title"),
            "role": selected.get("role"),
            "selected_at": _now(),
            "selected_by": (
                _string(
                    payload.get("selected_by")
                )
                or "human_main_interface"
            ),
        }

        _atomic_json(
            _selection_path(job_id),
            selection,
        )

        job_json = _job_json_path(job_id)
        if job_json.exists():
            job = _json_read(job_json)
            job["selected_cover"] = selection
            _atomic_json(
                job_json,
                job,
            )

        return await _workflow_snapshot(
            app,
            job_id,
        )

    @app.post(
        "/api/video/workflow/{job_id}/finalize"
    )
    async def finalize_workflow(
        job_id: str,
    ):
        await _load_job(
            app,
            job_id,
        )
        delivery = await _build_delivery(
            app,
            job_id,
        )
        snapshot = await _workflow_snapshot(
            app,
            job_id,
        )
        snapshot["finalize_result"] = delivery
        return snapshot

    @app.get(
        "/api/video/workflow/{job_id}/delivery"
    )
    async def get_delivery(
        job_id: str,
    ):
        await _load_job(
            app,
            job_id,
        )
        delivery = _delivery_for(
            job_id,
        )

        if not delivery:
            raise HTTPException(
                status_code=404,
                detail="该任务还没有最终交付包。",
            )

        return delivery
