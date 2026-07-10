from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import Body, FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from starlette.requests import Request
from starlette.responses import Response


VERSION = "10.39"
MODE = "review_approved_auto_cover_and_xhs"
APPROVE_RE = re.compile(r"^/api/video/review/(?P<job_id>[^/]+)/approve$")

BASE = Path(os.getenv("AI_VIDEO_BASE", "/opt/ai-video"))
STORAGE = BASE / "storage"
AUTO_ROOT = Path(
    os.getenv(
        "AI_VIDEO_AUTO_PACKAGING_ROOT",
        str(STORAGE / "graphic_window" / "auto_packaging"),
    )
)
JOB_ROOT = Path(
    os.getenv(
        "AI_VIDEO_JOB_ROOT",
        str(STORAGE / "v10_34" / "final_jobs"),
    )
)

_JOB_LOCKS: Dict[str, asyncio.Lock] = {}


def _now() -> int:
    return int(time.time())


def _safe_job_id(job_id: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", str(job_id or ""))
    return value.strip("._") or "unknown_job"


def _manifest_path(job_id: str) -> Path:
    AUTO_ROOT.mkdir(parents=True, exist_ok=True)
    return AUTO_ROOT / f"{_safe_job_id(job_id)}.json"


def _job_folder_result_path(job_id: str) -> Optional[Path]:
    folder = JOB_ROOT / job_id
    if folder.exists() and folder.is_dir():
        return folder / "auto_packaging_result.json"
    return None


def _job_json_path(job_id: str) -> Path:
    return JOB_ROOT / f"{job_id}.json"


def _atomic_write_json(path: Path, value: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}.{_now()}")
    temp.write_text(
        json.dumps(jsonable_encoder(value), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp.replace(path)


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _payload_hash(payload: Dict[str, Any]) -> str:
    stable = {
        "job_id": str(payload.get("job_id") or ""),
        "title": str(payload.get("title") or ""),
        "script_text": str(payload.get("script_text") or ""),
        "keywords": payload.get("keywords") or [],
        "style": str(payload.get("style") or ""),
        "cta": str(payload.get("cta") or ""),
        "platform": str(payload.get("platform") or ""),
    }
    raw = json.dumps(
        stable,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _approved(review: Dict[str, Any], status_code: int) -> bool:
    if not 200 <= status_code < 300:
        return False
    if str(review.get("status") or "").lower() != "approved":
        return False
    if review.get("approved") is False:
        return False
    if review.get("packaging_unlocked") is False:
        return False
    return True


def _result_ok(value: Any) -> bool:
    return isinstance(value, dict) and value.get("ok") is True


def _result_summary(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        return {"ok": False, "error": "missing_result"}
    return {
        "ok": value.get("ok"),
        "mode": value.get("mode"),
        "style": value.get("style"),
        "package_id": value.get("package_id"),
        "cover_count": value.get("cover_count"),
        "page_count": value.get("page_count"),
        "download_zip_url": value.get("download_zip_url"),
        "content_trace_url": value.get("content_trace_url"),
        "warnings": value.get("warnings") or [],
        "error": value.get("error"),
        "message": value.get("message"),
    }


def _find_route(app: FastAPI, path: str, method: str = "POST"):
    target_method = method.upper()
    for route in app.router.routes:
        route_path = getattr(route, "path", None)
        methods = getattr(route, "methods", None) or set()
        if route_path == path and target_method in methods:
            endpoint = getattr(route, "endpoint", None)
            if endpoint:
                return endpoint
    raise RuntimeError(f"未找到内部接口：{target_method} {path}")


async def _call_internal_post(
    app: FastAPI,
    path: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    endpoint = _find_route(app, path, "POST")

    if inspect.iscoroutinefunction(endpoint):
        try:
            result = await endpoint(payload)
        except TypeError:
            result = await endpoint(payload=payload)
    else:
        def invoke():
            try:
                return endpoint(payload)
            except TypeError:
                return endpoint(payload=payload)
        result = await asyncio.to_thread(invoke)

    encoded = jsonable_encoder(result)
    if isinstance(encoded, dict):
        return encoded
    return {
        "ok": False,
        "error": "unexpected_internal_result",
        "value": encoded,
    }


def _packaging_payload(job_id: str, approve_payload: Dict[str, Any]) -> Dict[str, Any]:
    keywords = approve_payload.get("keywords") or []
    if isinstance(keywords, str):
        keywords = [x for x in re.split(r"[,，\s]+", keywords) if x]

    return {
        "job_id": job_id,
        "title": str(approve_payload.get("title") or ""),
        "script_text": str(approve_payload.get("script_text") or ""),
        "keywords": keywords,
        "platform": str(approve_payload.get("platform") or "小红书"),
        "style": str(approve_payload.get("style") or "专业顾问"),
        "slide_count": int(approve_payload.get("slide_count") or 7),
        "cta": str(approve_payload.get("cta") or ""),
    }


def _public_automation(
    manifest: Dict[str, Any],
    cached: bool = False,
) -> Dict[str, Any]:
    cover_result = manifest.get("cover_result")
    xhs_result = manifest.get("xhs_result")
    return {
        "ok": manifest.get("status") == "completed",
        "status": manifest.get("status"),
        "version": manifest.get("version"),
        "mode": manifest.get("mode"),
        "job_id": manifest.get("job_id"),
        "started_at": manifest.get("started_at"),
        "completed_at": manifest.get("completed_at"),
        "cached": cached,
        "cover_ok": _result_ok(cover_result),
        "xhs_ok": _result_ok(xhs_result),
        "cover_summary": _result_summary(cover_result),
        "xhs_summary": _result_summary(xhs_result),
        "manifest_path": manifest.get("manifest_path"),
        "job_folder_result_path": manifest.get("job_folder_result_path"),
        "job_json_updated": manifest.get("job_json_updated", False),
        "errors": manifest.get("errors") or [],
        "cover_result": cover_result,
        "xhs_result": xhs_result,
    }


def _persist_into_job(job_id: str, manifest: Dict[str, Any]) -> Dict[str, Any]:
    result = {
        "job_folder_result_path": "",
        "job_json_updated": False,
    }

    folder_path = _job_folder_result_path(job_id)
    if folder_path:
        _atomic_write_json(folder_path, manifest)
        result["job_folder_result_path"] = str(folder_path)

    job_json = _job_json_path(job_id)
    if job_json.exists():
        job = _read_json(job_json)
        job["auto_packaging"] = {
            "version": manifest.get("version"),
            "mode": manifest.get("mode"),
            "status": manifest.get("status"),
            "updated_at": manifest.get("completed_at"),
            "manifest_path": manifest.get("manifest_path"),
            "job_folder_result_path": result["job_folder_result_path"],
            "cover": _result_summary(manifest.get("cover_result")),
            "xiaohongshu": _result_summary(manifest.get("xhs_result")),
        }
        _atomic_write_json(job_json, job)
        result["job_json_updated"] = True

    return result


async def _run_packaging(
    app: FastAPI,
    job_id: str,
    approve_payload: Dict[str, Any],
    existing_cover: Optional[Dict[str, Any]] = None,
    force: bool = False,
) -> Dict[str, Any]:
    lock = _JOB_LOCKS.setdefault(job_id, asyncio.Lock())

    async with lock:
        payload = _packaging_payload(job_id, approve_payload)
        digest = _payload_hash(payload)
        manifest_path = _manifest_path(job_id)
        existing = _read_json(manifest_path)

        if (
            not force
            and existing.get("status") == "completed"
            and existing.get("payload_hash") == digest
            and _result_ok(existing.get("cover_result"))
            and _result_ok(existing.get("xhs_result"))
        ):
            return _public_automation(existing, cached=True)

        working = {
            "version": VERSION,
            "mode": MODE,
            "status": "running",
            "job_id": job_id,
            "approved": True,
            "started_at": _now(),
            "completed_at": None,
            "payload_hash": digest,
            "request_payload": payload,
            "manifest_path": str(manifest_path),
            "cover_result": existing_cover,
            "xhs_result": None,
            "errors": [],
        }
        _atomic_write_json(manifest_path, working)
        errors = []

        cover_result = existing_cover
        if not _result_ok(cover_result):
            try:
                cover_result = await _call_internal_post(
                    app,
                    "/api/graphic-window/video-cover/generate",
                    payload,
                )
            except Exception as exc:
                cover_result = {
                    "ok": False,
                    "error": "cover_generation_exception",
                    "message": str(exc),
                }
                errors.append(f"三套封面生成失败：{exc}")

        try:
            xhs_result = await _call_internal_post(
                app,
                "/api/graphic-window/xiaohongshu/generate",
                payload,
            )
        except Exception as exc:
            xhs_result = {
                "ok": False,
                "error": "xhs_generation_exception",
                "message": str(exc),
            }
            errors.append(f"小红书图文包生成失败：{exc}")

        if not _result_ok(cover_result):
            message = (
                cover_result.get("message")
                or cover_result.get("error")
                or "未知错误"
            )
            errors.append(f"三套封面未完成：{message}")

        if not _result_ok(xhs_result):
            message = (
                xhs_result.get("message")
                or xhs_result.get("error")
                or "未知错误"
            )
            errors.append(f"小红书图文包未完成：{message}")

        cover_ok = _result_ok(cover_result)
        xhs_ok = _result_ok(xhs_result)
        status = (
            "completed"
            if cover_ok and xhs_ok
            else "partial_failed"
            if cover_ok or xhs_ok
            else "failed"
        )

        manifest = {
            **working,
            "status": status,
            "completed_at": _now(),
            "cover_result": cover_result,
            "xhs_result": xhs_result,
            "errors": list(dict.fromkeys(errors)),
        }

        job_persist = _persist_into_job(job_id, manifest)
        manifest.update(job_persist)
        _atomic_write_json(manifest_path, manifest)

        if job_persist.get("job_folder_result_path"):
            _atomic_write_json(
                Path(job_persist["job_folder_result_path"]),
                manifest,
            )

        return _public_automation(manifest)


async def _read_response_body(response: Response) -> bytes:
    body = getattr(response, "body", None)
    if body is not None:
        return bytes(body)

    chunks = []
    async for chunk in response.body_iterator:
        if isinstance(chunk, str):
            chunk = chunk.encode("utf-8")
        chunks.append(bytes(chunk))
    return b"".join(chunks)


def _rebuild_json_response(
    original: Response,
    data: Dict[str, Any],
) -> Response:
    headers = {
        key: value
        for key, value in original.headers.items()
        if key.lower() not in {"content-length", "content-type"}
    }
    return Response(
        content=json.dumps(
            jsonable_encoder(data),
            ensure_ascii=False,
        ).encode("utf-8"),
        status_code=original.status_code,
        headers=headers,
        media_type="application/json",
        background=getattr(original, "background", None),
    )


def _request_with_json_body(
    request: Request,
    payload: Dict[str, Any],
) -> Request:
    new_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    scope = dict(request.scope)
    headers = [
        (key, value)
        for key, value in scope.get("headers", [])
        if key.lower() != b"content-length"
    ]
    headers.append((b"content-length", str(len(new_body)).encode("ascii")))
    scope["headers"] = headers
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {
                "type": "http.request",
                "body": b"",
                "more_body": False,
            }
        sent = True
        return {
            "type": "http.request",
            "body": new_body,
            "more_body": False,
        }

    return Request(scope, receive)


def install_review_packaging_automation(app: FastAPI) -> None:
    if getattr(
        app.state,
        "review_packaging_automation_installed",
        False,
    ):
        return

    app.state.review_packaging_automation_installed = True
    AUTO_ROOT.mkdir(parents=True, exist_ok=True)

    @app.get("/api/graphic-window/automation/health")
    def automation_health():
        return {
            "ok": True,
            "version": VERSION,
            "mode": MODE,
            "auto_after_human_approval": True,
            "generates": [
                "three_cover_variants",
                "fact_checked_xiaohongshu_story",
            ],
            "manifest_root": str(AUTO_ROOT),
            "fal_called": False,
            "regenerate_video": False,
        }

    @app.get("/api/graphic-window/automation/{job_id}")
    def automation_status(job_id: str):
        manifest = _read_json(_manifest_path(job_id))
        if not manifest:
            raise HTTPException(
                status_code=404,
                detail="该任务还没有自动包装记录",
            )
        return _public_automation(manifest)

    @app.post("/api/graphic-window/automation/{job_id}/retry")
    async def automation_retry(
        job_id: str,
        payload: Dict[str, Any] = Body(default_factory=dict),
    ):
        existing = _read_json(_manifest_path(job_id))
        if not existing or existing.get("approved") is not True:
            raise HTTPException(
                status_code=409,
                detail="只有已经人工批准的任务才能重试自动包装",
            )

        merged = {
            **(existing.get("request_payload") or {}),
            **payload,
            "job_id": job_id,
        }
        return await _run_packaging(
            app,
            job_id,
            merged,
            force=True,
        )

    @app.middleware("http")
    async def review_auto_packaging_middleware(
        request: Request,
        call_next,
    ):
        if request.method.upper() != "POST":
            return await call_next(request)

        match = APPROVE_RE.match(request.url.path)
        if not match:
            return await call_next(request)

        job_id = match.group("job_id")

        try:
            original_body = await request.body()
            approve_payload = json.loads(
                original_body.decode("utf-8") or "{}"
            )
            if not isinstance(approve_payload, dict):
                approve_payload = {}
        except Exception:
            approve_payload = {}

        # 新版页面本身会传 generate_cover=false，避免旧审批接口重复出图。
        # 中间件不再替换 Request 对象，以兼容 Starlette BaseHTTPMiddleware。
        response = await call_next(request)
        body = await _read_response_body(response)

        try:
            data = json.loads(body.decode("utf-8") or "{}")
        except Exception:
            return Response(
                content=body,
                status_code=response.status_code,
                headers={
                    key: value
                    for key, value in response.headers.items()
                    if key.lower() != "content-length"
                },
                media_type=response.media_type,
                background=getattr(response, "background", None),
            )

        if not isinstance(data, dict):
            return _rebuild_json_response(response, {"result": data})

        review = (
            data.get("review")
            if isinstance(data.get("review"), dict)
            else data
        )

        if not _approved(review, response.status_code):
            return _rebuild_json_response(response, data)

        existing_cover = (
            data.get("cover_result")
            if isinstance(data.get("cover_result"), dict)
            else None
        )

        try:
            automation = await _run_packaging(
                app,
                job_id,
                approve_payload,
                existing_cover=existing_cover,
                force=bool(approve_payload.get("force_repackage", False)),
            )
        except Exception as exc:
            automation = {
                "ok": False,
                "status": "failed",
                "version": VERSION,
                "mode": MODE,
                "job_id": job_id,
                "cached": False,
                "cover_ok": False,
                "xhs_ok": False,
                "errors": [f"自动包装异常：{exc}"],
            }

        data["automation"] = automation

        if isinstance(automation.get("cover_result"), dict):
            data["cover_result"] = automation["cover_result"]

        if isinstance(automation.get("xhs_result"), dict):
            data["xhs_result"] = automation["xhs_result"]

        data["auto_packaging"] = {
            "trigger": "human_review_approved",
            "version": VERSION,
            "status": automation.get("status"),
            "cover_ok": automation.get("cover_ok"),
            "xhs_ok": automation.get("xhs_ok"),
            "cached": automation.get("cached"),
        }

        return _rebuild_json_response(response, data)
