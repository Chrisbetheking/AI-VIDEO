from __future__ import annotations

import hashlib
import hmac
import json
import math
import mimetypes
import os
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.services.assets_store import now_iso, upsert_asset
from app.services.memory import MemoryStore
from app.services.storage import public_r2_url

VERSION = "10.40.8.11.1-r2-direct-upload-finalize-hotfix"
ROUTER_PREFIX = "/api/assets/direct-upload"
DEFAULT_PREFIX = "incoming/landscape"
DEFAULT_PART_SIZE = 64 * 1024 * 1024
SINGLE_UPLOAD_LIMIT = 96 * 1024 * 1024
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

router = APIRouter(prefix=ROUTER_PREFIX, tags=["R2 Direct Upload Queue"])
_STATE_LOCK = threading.RLock()
_REFRAME_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="direct-upload-reframe")
_REFRAME_WORKERS: set[str] = set()


class DirectFile(BaseModel):
    client_id: str = Field(min_length=1, max_length=160)
    name: str = Field(min_length=1, max_length=500)
    size: int = Field(ge=1, le=5 * 1024**4)
    type: str = Field(default="application/octet-stream", max_length=200)
    last_modified: int = Field(default=0, ge=0)
    relative_path: str = Field(default="", max_length=1200)


class CreateBatchRequest(BaseModel):
    files: list[DirectFile] = Field(min_length=1, max_length=500)
    output_prefix: str = DEFAULT_PREFIX
    folder: str = "self"
    usage_role: str = "content"
    auto_reframe: bool = True
    reframe_mode: Literal["smart_crop", "center_crop", "fit_blur"] = "smart_crop"


class SignPartsRequest(BaseModel):
    part_numbers: list[int] = Field(min_length=1, max_length=64)


class CompleteUploadRequest(BaseModel):
    parts: list[dict[str, Any]] = Field(default_factory=list, max_length=10000)


class FinalizeBatchRequest(BaseModel):
    auto_reframe: bool | None = None
    reframe_mode: Literal["smart_crop", "center_crop", "fit_blur"] | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _state_file(settings: Settings) -> Path:
    path = settings.data_dir / "r2-direct-upload-queue-v10-40-8-11" / "batches.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load_batches(settings: Settings) -> dict[str, dict[str, Any]]:
    path = _state_file(settings)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _save_batches(settings: Settings, batches: dict[str, dict[str, Any]]) -> None:
    # Keep the newest 120 batches. Large file lists are still tiny compared with video data.
    if len(batches) > 120:
        newest = sorted(
            batches.items(),
            key=lambda item: str(item[1].get("updated_at") or item[1].get("created_at") or ""),
            reverse=True,
        )[:120]
        batches = dict(newest)
    path = _state_file(settings)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(batches, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _mutate_batch(settings: Settings, batch_id: str, mutator) -> dict[str, Any]:
    with _STATE_LOCK:
        batches = _load_batches(settings)
        batch = batches.get(batch_id)
        if not batch:
            raise HTTPException(status_code=404, detail="上传批次不存在")
        mutator(batch)
        batch["updated_at"] = _utc_now()
        batches[batch_id] = batch
        _save_batches(settings, batches)
        return batch


def _get_batch(settings: Settings, batch_id: str) -> dict[str, Any]:
    with _STATE_LOCK:
        batch = _load_batches(settings).get(batch_id)
        if not batch:
            raise HTTPException(status_code=404, detail="上传批次不存在")
        return batch


def _find_file(batch: dict[str, Any], file_id: str) -> dict[str, Any]:
    for item in batch.get("files", []):
        if str(item.get("id")) == file_id:
            return item
    raise HTTPException(status_code=404, detail="上传文件不存在")


def _safe_name(name: str) -> str:
    value = Path(name.replace("\\", "/")).name.strip()
    stem = re.sub(r"[^0-9A-Za-z._\-\u4e00-\u9fff]+", "_", value)
    stem = stem.strip("._") or "material"
    if len(stem) > 180:
        suffix = Path(stem).suffix[:16]
        stem = stem[: max(20, 180 - len(suffix))] + suffix
    return stem


def _normalize_prefix(value: str) -> str:
    cleaned = re.sub(r"/+", "/", str(value or "").strip().strip("/"))
    if not cleaned:
        return DEFAULT_PREFIX
    if ".." in cleaned.split("/"):
        raise HTTPException(status_code=400, detail="非法 R2 路径")
    return cleaned[:240]


def _file_kind(name: str, content_type: str) -> str:
    suffix = Path(name).suffix.lower()
    if suffix in VIDEO_EXTENSIONS or content_type.startswith("video/"):
        return "video"
    if suffix in IMAGE_EXTENSIONS or content_type.startswith("image/"):
        return "image"
    raise HTTPException(status_code=400, detail=f"不支持的素材格式：{suffix or content_type}")


def _fingerprint(file: DirectFile) -> str:
    raw = "|".join(
        [
            file.client_id,
            file.relative_path,
            file.name,
            str(file.size),
            str(file.last_modified),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()


def _r2_client(settings: Settings):
    if not settings.r2_enabled:
        raise HTTPException(status_code=503, detail="R2 环境变量未配置完整")
    import boto3  # type: ignore
    from botocore.config import Config  # type: ignore

    endpoint = f"https://{settings.r2_account_id}.r2.cloudflarestorage.com"
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        region_name="auto",
        config=Config(
            signature_version="s3v4",
            connect_timeout=15,
            read_timeout=45,
            retries={"max_attempts": 4, "mode": "standard"},
        ),
    )


def _origin_allowed(request: Request) -> None:
    host = request.client.host if request.client else ""
    if host in {"127.0.0.1", "::1", "localhost"}:
        return
    origin = (request.headers.get("origin") or "").strip().lower()
    if not origin:
        raise HTTPException(status_code=403, detail="浏览器请求缺少 Origin")
    defaults = {
        "https://ai-video-s5v.pages.dev",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    }
    configured = {
        value.strip().lower().rstrip("/")
        for value in os.getenv("DIRECT_UPLOAD_ALLOWED_ORIGINS", "").split(",")
        if value.strip()
    }
    allowed = defaults | configured
    if origin in allowed:
        return
    if origin.startswith("https://") and origin.endswith(".ai-video-s5v.pages.dev"):
        return
    raise HTTPException(status_code=403, detail=f"当前页面来源未获授权：{origin}")


def _require_local(request: Request) -> None:
    host = request.client.host if request.client else ""
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise HTTPException(status_code=403, detail="该维护接口仅允许服务器本机调用")


def _head_matches(client, settings: Settings, key: str, size: int) -> dict[str, Any] | None:
    try:
        head = client.head_object(Bucket=settings.r2_bucket_name, Key=key)
    except Exception as exc:
        code = str(getattr(exc, "response", {}).get("Error", {}).get("Code", ""))
        if code in {"404", "NoSuchKey", "NotFound"} or "404" in str(exc):
            return None
        return None
    actual = int(head.get("ContentLength") or 0)
    return head if actual == int(size) else None


def _asset_payload(settings: Settings, file_item: dict[str, Any]) -> dict[str, Any]:
    key = str(file_item["object_key"])
    filename = Path(key).name
    return {
        "id": str(file_item.get("asset_id") or Path(filename).stem),
        "filename": filename,
        "original_name": str(file_item.get("name") or filename),
        "kind": str(file_item.get("kind") or "video"),
        "url": public_r2_url(settings, key),
        "r2_url": public_r2_url(settings, key),
        "r2_key": key,
        "size_bytes": int(file_item.get("size") or 0),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "folder": str(file_item.get("folder") or "self"),
        "source_type": "r2_direct_upload_queue_v10_40_8_11",
        "usage_role": str(file_item.get("usage_role") or "content"),
        "workspace_id": settings.workspace_id,
        "upload_batch_id": str(file_item.get("batch_id") or ""),
        "direct_upload": True,
    }


def _register_asset(
    settings: Settings,
    file_item: dict[str, Any],
) -> dict[str, Any]:
    """
    R2 上传完成不能因为素材数据库暂时写入失败而返回 500。

    处理顺序：
    1. 优先写 Supabase/Memory；
    2. 数据表不接受扩展字段时，使用兼容字段写入；
    3. Supabase 临时不可用时，回退本地 manifest；
    4. 即使素材登记暂时失败，也保留 R2 上传完成状态。
    """
    payload = _asset_payload(settings, file_item)

    # 这两个字段用于本地任务追踪，但旧 Supabase assets 表
    # 未必已经有对应列，不能让未知字段阻断上传完成。
    database_payload = dict(payload)
    database_payload.pop("upload_batch_id", None)
    database_payload.pop("direct_upload", None)

    saved: dict[str, Any] = {}
    warnings: list[str] = []

    try:
        memory = MemoryStore(settings)
        result = upsert_asset(
            settings,
            database_payload,
            memory,
            require_supabase=False,
        )
        if isinstance(result, dict):
            saved = result
    except Exception as exc:
        warning = f"supabase:{type(exc).__name__}:{exc}"[:1000]
        warnings.append(warning)
        print(
            f"[r2-direct-upload] asset register fallback: {warning}",
            flush=True,
        )

        try:
            result = upsert_asset(
                settings,
                payload,
                None,
                require_supabase=False,
            )
            if isinstance(result, dict):
                saved = result
        except Exception as fallback_exc:
            fallback_warning = (
                f"manifest:{type(fallback_exc).__name__}:{fallback_exc}"
            )[:1000]
            warnings.append(fallback_warning)
            print(
                "[r2-direct-upload] local asset register deferred: "
                f"{fallback_warning}",
                flush=True,
            )

            # 文件已经成功进入 R2。素材索引可稍后补偿，
            # 绝不能把完成接口重新变成 500。
            saved = dict(payload)

    merged = {**payload, **saved}

    file_item["asset_id"] = str(
        merged.get("id") or payload["id"]
    )
    file_item["asset_url"] = str(
        merged.get("url") or payload["url"]
    )

    if warnings:
        file_item["asset_register_warning"] = " | ".join(warnings)[:1800]
        file_item["asset_registration_deferred"] = not bool(saved)
    else:
        file_item.pop("asset_register_warning", None)
        file_item.pop("asset_registration_deferred", None)

    return merged


def _summary(batch: dict[str, Any]) -> dict[str, int]:
    files = batch.get("files", [])
    statuses = [str(item.get("status") or "") for item in files]
    return {
        "total": len(files),
        "waiting": sum(value in {"waiting", "prepared", "uploading"} for value in statuses),
        "completed": sum(value == "completed" for value in statuses),
        "failed": sum(value == "failed" for value in statuses),
        "cancelled": sum(value == "cancelled" for value in statuses),
        "videos": sum(str(item.get("kind")) == "video" for item in files),
        "images": sum(str(item.get("kind")) == "image" for item in files),
    }


def _public_batch(batch: dict[str, Any], settings: Settings) -> dict[str, Any]:
    result = json.loads(json.dumps(batch))
    result["summary"] = _summary(batch)
    job_id = str(batch.get("reframe_job_id") or "")
    if job_id:
        try:
            from app.services.r2_smart_vertical_reframe_v10_40_8_9 import _get_job

            result["reframe_job"] = _get_job(settings, job_id)
        except Exception:
            result["reframe_job"] = None
    return result


def _start_reframe_once(settings: Settings, batch_id: str) -> dict[str, Any] | None:
    batch = _get_batch(settings, batch_id)
    if batch.get("reframe_job_id"):
        return batch
    keys = [
        str(item.get("object_key") or "")
        for item in batch.get("files", [])
        if item.get("status") == "completed" and item.get("kind") == "video"
    ]
    keys = list(dict.fromkeys(value for value in keys if value))
    if not keys or not bool(batch.get("auto_reframe", True)):
        return _mutate_batch(
            settings,
            batch_id,
            lambda item: item.update(
                {
                    "status": "completed",
                    "message": "素材上传完成，无需启动横转竖。",
                }
            ),
        )
    try:
        from app.services.r2_smart_vertical_reframe_v10_40_8_9 import (
            ReframeJobRequest,
            create_job,
        )

        response = create_job(
            ReframeJobRequest(
                object_keys=keys,
                output_prefix="vertical-9x16",
                mode=str(batch.get("reframe_mode") or "smart_crop"),
                force=False,
                skip_non_landscape=True,
                register_assets=True,
                delete_local_after_upload=True,
                sample_count=12,
                max_input_mb=5000,
                reserve_free_mb=1536,
                crf=21,
                preset="veryfast",
            ),
            _auth=None,
            settings=settings,
        )
        job = response.get("job") if isinstance(response, dict) else response
        job_id = str((job or {}).get("id") or (job or {}).get("job_id") or "")
        if not job_id:
            raise RuntimeError("横转竖接口未返回 job_id")
        return _mutate_batch(
            settings,
            batch_id,
            lambda item: item.update(
                {
                    "status": "reframing",
                    "message": "原始素材已全部进入 R2，正在按顺序生成 9:16。",
                    "reframe_job_id": job_id,
                    "reframe_started_at": _utc_now(),
                    "reframe_error": "",
                }
            ),
        )
    except HTTPException as exc:
        if exc.status_code not in {409, 423, 429, 503}:
            raise
        _mutate_batch(
            settings,
            batch_id,
            lambda item: item.update(
                {
                    "status": "waiting_reframe",
                    "message": "横转竖处理器正忙，本批次已自动排队。",
                    "reframe_error": str(exc.detail),
                }
            ),
        )
        return None


def _reframe_waiter(settings: Settings, batch_id: str) -> None:
    try:
        deadline = time.time() + 12 * 60 * 60
        while time.time() < deadline:
            batch = _get_batch(settings, batch_id)
            if batch.get("reframe_job_id") or batch.get("status") in {"cancelled", "failed"}:
                return
            try:
                started = _start_reframe_once(settings, batch_id)
                if started and started.get("reframe_job_id"):
                    return
            except Exception as exc:
                _mutate_batch(
                    settings,
                    batch_id,
                    lambda item: item.update(
                        {
                            "status": "waiting_reframe",
                            "message": "横转竖任务等待重试。",
                            "reframe_error": str(exc)[:1000],
                        }
                    ),
                )
            time.sleep(12)
    finally:
        with _STATE_LOCK:
            _REFRAME_WORKERS.discard(batch_id)


def _ensure_reframe_waiter(settings: Settings, batch_id: str) -> None:
    with _STATE_LOCK:
        if batch_id in _REFRAME_WORKERS:
            return
        _REFRAME_WORKERS.add(batch_id)
    _REFRAME_EXECUTOR.submit(_reframe_waiter, settings, batch_id)


@router.get("/health")
def health(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    return {
        "ok": True,
        "version": VERSION,
        "mode": "browser_multipart_direct_to_r2_then_auto_reframe",
        "r2_enabled": settings.r2_enabled,
        "bucket": settings.r2_bucket_name if settings.r2_enabled else "",
        "single_upload_limit_mb": SINGLE_UPLOAD_LIMIT // 1024 // 1024,
        "multipart_part_size_mb": DEFAULT_PART_SIZE // 1024 // 1024,
        "max_files_per_batch": 500,
        "features": {
            "browser_direct_to_r2": True,
            "multipart_large_file": True,
            "two_file_frontend_queue": True,
            "pause_resume": True,
            "retry_failed": True,
            "server_side_part_resume": True,
            "deterministic_dedup_key": True,
            "auto_asset_register": True,
            "auto_vertical_reframe": True,
            "ecs_never_receives_video_body": True,
        },
    }


@router.post("/configure-cors")
def configure_cors(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    _require_local(request)
    client = _r2_client(settings)
    # Presigned object keys remain the authorization boundary. CORS only lets the browser
    # send PUT requests and read the ETag needed to finish multipart uploads.
    rules = [
        {
            "AllowedOrigins": ["*"],
            "AllowedMethods": ["GET", "PUT", "HEAD"],
            "AllowedHeaders": ["*"],
            "ExposeHeaders": ["ETag", "Content-Length", "Content-Type"],
            "MaxAgeSeconds": 3600,
        }
    ]
    client.put_bucket_cors(
        Bucket=settings.r2_bucket_name,
        CORSConfiguration={"CORSRules": rules},
    )
    return {"ok": True, "version": VERSION, "bucket": settings.r2_bucket_name, "rules": rules}


@router.post("/batches")
def create_batch(
    payload: CreateBatchRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    _origin_allowed(request)
    if not settings.r2_enabled:
        raise HTTPException(status_code=503, detail="R2 尚未配置")
    prefix = _normalize_prefix(payload.output_prefix)
    batch_id = uuid.uuid4().hex
    files: list[dict[str, Any]] = []
    seen: set[str] = set()
    for file in payload.files:
        kind = _file_kind(file.name, file.type)
        fingerprint = _fingerprint(file)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        safe = _safe_name(file.name)
        key = f"{prefix}/{fingerprint[:2]}/{fingerprint}_{safe}"
        files.append(
            {
                "id": fingerprint[:24],
                "client_id": file.client_id,
                "name": file.name,
                "relative_path": file.relative_path,
                "size": file.size,
                "type": file.type or mimetypes.guess_type(file.name)[0] or "application/octet-stream",
                "last_modified": file.last_modified,
                "kind": kind,
                "fingerprint": fingerprint,
                "object_key": key,
                "status": "waiting",
                "message": "等待上传",
                "upload_type": "",
                "upload_id": "",
                "part_size": DEFAULT_PART_SIZE,
                "part_count": math.ceil(file.size / DEFAULT_PART_SIZE),
                "parts": {},
                "error": "",
                "folder": payload.folder,
                "usage_role": payload.usage_role,
                "batch_id": batch_id,
            }
        )
    if not files:
        raise HTTPException(status_code=400, detail="没有可上传的视频或照片")
    batch = {
        "id": batch_id,
        "version": VERSION,
        "status": "waiting",
        "message": f"已建立 {len(files)} 条素材上传队列",
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
        "output_prefix": prefix,
        "folder": payload.folder,
        "usage_role": payload.usage_role,
        "auto_reframe": payload.auto_reframe,
        "reframe_mode": payload.reframe_mode,
        "reframe_job_id": "",
        "reframe_error": "",
        "files": files,
    }
    with _STATE_LOCK:
        batches = _load_batches(settings)
        batches[batch_id] = batch
        _save_batches(settings, batches)
    return {"ok": True, "batch": _public_batch(batch, settings)}


@router.get("/batches/{batch_id}")
def get_batch(
    batch_id: str,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    _origin_allowed(request)
    batch = _get_batch(settings, batch_id)
    if batch.get("status") == "waiting_reframe" and not batch.get("reframe_job_id"):
        _ensure_reframe_waiter(settings, batch_id)
    return {"ok": True, "batch": _public_batch(batch, settings)}


@router.post("/batches/{batch_id}/files/{file_id}/prepare")
def prepare_file(
    batch_id: str,
    file_id: str,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    _origin_allowed(request)
    client = _r2_client(settings)
    batch = _get_batch(settings, batch_id)
    file_item = _find_file(batch, file_id)
    key = str(file_item["object_key"])
    size = int(file_item["size"])
    existing = _head_matches(client, settings, key, size)
    if existing is not None:
        def mark_existing(item: dict[str, Any]) -> None:
            target = _find_file(item, file_id)
            target.update(
                {
                    "status": "completed",
                    "message": "R2 已存在同一素材，自动跳过上传",
                    "upload_type": "existing",
                    "uploaded_at": _utc_now(),
                    "error": "",
                }
            )
            _register_asset(settings, target)
            item["status"] = "uploading"

        next_batch = _mutate_batch(settings, batch_id, mark_existing)
        return {
            "ok": True,
            "mode": "existing",
            "file": _find_file(next_batch, file_id),
        }
    if size <= SINGLE_UPLOAD_LIMIT:
        url = client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": settings.r2_bucket_name,
                "Key": key,
                "ContentType": str(file_item.get("type") or "application/octet-stream"),
            },
            ExpiresIn=6 * 60 * 60,
        )

        def mark_single(item: dict[str, Any]) -> None:
            target = _find_file(item, file_id)
            target.update(
                {
                    "status": "prepared",
                    "message": "已获得 R2 直传地址",
                    "upload_type": "single",
                    "error": "",
                }
            )
            item["status"] = "uploading"

        next_batch = _mutate_batch(settings, batch_id, mark_single)
        return {
            "ok": True,
            "mode": "single",
            "url": url,
            "expires_in": 21600,
            "file": _find_file(next_batch, file_id),
        }
    upload_id = str(file_item.get("upload_id") or "")
    if not upload_id:
        response = client.create_multipart_upload(
            Bucket=settings.r2_bucket_name,
            Key=key,
            ContentType=str(file_item.get("type") or "application/octet-stream"),
        )
        upload_id = str(response["UploadId"])

    def mark_multipart(item: dict[str, Any]) -> None:
        target = _find_file(item, file_id)
        target.update(
            {
                "status": "prepared",
                "message": "大文件已进入 R2 分片上传",
                "upload_type": "multipart",
                "upload_id": upload_id,
                "part_size": DEFAULT_PART_SIZE,
                "part_count": math.ceil(size / DEFAULT_PART_SIZE),
                "error": "",
            }
        )
        item["status"] = "uploading"

    next_batch = _mutate_batch(settings, batch_id, mark_multipart)
    return {
        "ok": True,
        "mode": "multipart",
        "upload_id": upload_id,
        "part_size": DEFAULT_PART_SIZE,
        "part_count": math.ceil(size / DEFAULT_PART_SIZE),
        "file": _find_file(next_batch, file_id),
    }


@router.get("/batches/{batch_id}/files/{file_id}/parts")
def list_uploaded_parts(
    batch_id: str,
    file_id: str,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    _origin_allowed(request)
    client = _r2_client(settings)
    batch = _get_batch(settings, batch_id)
    file_item = _find_file(batch, file_id)
    upload_id = str(file_item.get("upload_id") or "")
    if not upload_id:
        return {"ok": True, "parts": []}
    parts: list[dict[str, Any]] = []
    marker: int | None = None
    while True:
        kwargs: dict[str, Any] = {
            "Bucket": settings.r2_bucket_name,
            "Key": file_item["object_key"],
            "UploadId": upload_id,
            "MaxParts": 1000,
        }
        if marker:
            kwargs["PartNumberMarker"] = marker
        response = client.list_parts(**kwargs)
        for part in response.get("Parts", []) or []:
            parts.append(
                {
                    "part_number": int(part["PartNumber"]),
                    "etag": str(part["ETag"]),
                    "size": int(part.get("Size") or 0),
                }
            )
        if not response.get("IsTruncated"):
            break
        marker = int(response.get("NextPartNumberMarker") or 0)
        if not marker:
            break

    def remember(item: dict[str, Any]) -> None:
        target = _find_file(item, file_id)
        target["parts"] = {str(part["part_number"]): part["etag"] for part in parts}

    _mutate_batch(settings, batch_id, remember)
    return {"ok": True, "parts": parts}


@router.post("/batches/{batch_id}/files/{file_id}/parts/sign")
def sign_parts(
    batch_id: str,
    file_id: str,
    payload: SignPartsRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    _origin_allowed(request)
    client = _r2_client(settings)
    batch = _get_batch(settings, batch_id)
    file_item = _find_file(batch, file_id)
    upload_id = str(file_item.get("upload_id") or "")
    part_count = int(file_item.get("part_count") or 0)
    if not upload_id:
        raise HTTPException(status_code=409, detail="请先调用 prepare 创建 multipart upload")
    numbers = sorted(set(int(value) for value in payload.part_numbers))
    if not numbers or any(value < 1 or value > part_count for value in numbers):
        raise HTTPException(status_code=400, detail="分片编号超出范围")
    urls = [
        {
            "part_number": number,
            "url": client.generate_presigned_url(
                "upload_part",
                Params={
                    "Bucket": settings.r2_bucket_name,
                    "Key": file_item["object_key"],
                    "UploadId": upload_id,
                    "PartNumber": number,
                },
                ExpiresIn=6 * 60 * 60,
            ),
        }
        for number in numbers
    ]
    return {"ok": True, "upload_id": upload_id, "parts": urls}


@router.post("/batches/{batch_id}/files/{file_id}/complete")
def complete_file(
    batch_id: str,
    file_id: str,
    payload: CompleteUploadRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    _origin_allowed(request)
    client = _r2_client(settings)
    batch = _get_batch(settings, batch_id)
    file_item = _find_file(batch, file_id)
    key = str(file_item["object_key"])
    size = int(file_item["size"])
    existing = _head_matches(client, settings, key, size)
    if existing is None and file_item.get("upload_type") == "multipart":
        upload_id = str(file_item.get("upload_id") or "")
        if not upload_id:
            raise HTTPException(status_code=409, detail="multipart upload_id 缺失")
        clean_parts = []
        for part in payload.parts:
            number = int(part.get("part_number") or part.get("PartNumber") or 0)
            etag = str(part.get("etag") or part.get("ETag") or "").strip()
            if number > 0 and etag:
                clean_parts.append({"PartNumber": number, "ETag": etag})
        clean_parts.sort(key=lambda item: item["PartNumber"])
        expected = int(file_item.get("part_count") or 0)
        if len(clean_parts) != expected:
            raise HTTPException(
                status_code=409,
                detail=f"分片不完整：收到 {len(clean_parts)}，期望 {expected}",
            )
        client.complete_multipart_upload(
            Bucket=settings.r2_bucket_name,
            Key=key,
            UploadId=upload_id,
            MultipartUpload={"Parts": clean_parts},
        )
        existing = _head_matches(client, settings, key, size)
    if existing is None:
        raise HTTPException(status_code=409, detail="R2 尚未确认完整文件，请重试当前文件")

    def mark_complete(item: dict[str, Any]) -> None:
        target = _find_file(item, file_id)
        target.update(
            {
                "status": "completed",
                "message": "上传完成并已登记素材库",
                "uploaded_at": _utc_now(),
                "error": "",
            }
        )
        if payload.parts:
            target["parts"] = {
                str(int(part.get("part_number") or part.get("PartNumber") or 0)): str(
                    part.get("etag") or part.get("ETag") or ""
                )
                for part in payload.parts
                if int(part.get("part_number") or part.get("PartNumber") or 0) > 0
            }
        _register_asset(settings, target)
        summary = _summary(item)
        item["status"] = "uploaded" if summary["completed"] == summary["total"] else "uploading"
        item["message"] = (
            "全部原始素材已进入 R2，准备启动横转竖。"
            if summary["completed"] == summary["total"]
            else f"已上传 {summary['completed']}/{summary['total']} 条素材"
        )

    next_batch = _mutate_batch(settings, batch_id, mark_complete)
    return {"ok": True, "file": _find_file(next_batch, file_id), "batch": _public_batch(next_batch, settings)}


@router.post("/batches/{batch_id}/files/{file_id}/fail")
def mark_file_failed(
    batch_id: str,
    file_id: str,
    payload: dict[str, Any],
    request: Request,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    _origin_allowed(request)
    message = str(payload.get("error") or "上传失败")[:1200]

    def mark(item: dict[str, Any]) -> None:
        target = _find_file(item, file_id)
        target.update({"status": "failed", "message": "上传失败，可单独重试", "error": message})
        item["status"] = "partial"
        item["message"] = "部分素材上传失败，其余队列不受影响。"

    batch = _mutate_batch(settings, batch_id, mark)
    return {"ok": True, "batch": _public_batch(batch, settings)}


@router.post("/batches/{batch_id}/files/{file_id}/abort")
def abort_file(
    batch_id: str,
    file_id: str,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    _origin_allowed(request)
    client = _r2_client(settings)
    batch = _get_batch(settings, batch_id)
    file_item = _find_file(batch, file_id)
    upload_id = str(file_item.get("upload_id") or "")
    if upload_id:
        try:
            client.abort_multipart_upload(
                Bucket=settings.r2_bucket_name,
                Key=file_item["object_key"],
                UploadId=upload_id,
            )
        except Exception:
            pass

    def mark(item: dict[str, Any]) -> None:
        target = _find_file(item, file_id)
        target.update(
            {
                "status": "cancelled",
                "message": "已取消",
                "upload_id": "",
                "parts": {},
            }
        )

    next_batch = _mutate_batch(settings, batch_id, mark)
    return {"ok": True, "file": _find_file(next_batch, file_id)}


@router.post("/batches/{batch_id}/finalize")
def finalize_batch(
    batch_id: str,
    payload: FinalizeBatchRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    _origin_allowed(request)

    def update_options(item: dict[str, Any]) -> None:
        if payload.auto_reframe is not None:
            item["auto_reframe"] = payload.auto_reframe
        if payload.reframe_mode is not None:
            item["reframe_mode"] = payload.reframe_mode
        summary = _summary(item)
        if summary["waiting"] > 0:
            raise HTTPException(status_code=409, detail="仍有素材未完成上传")
        if summary["failed"] > 0:
            item["status"] = "partial"
            item["message"] = "上传队列存在失败项；可重试失败项后再次完成批次。"
        else:
            item["status"] = "waiting_reframe" if item.get("auto_reframe", True) else "completed"
            item["message"] = "上传完成，已进入自动转竖队列。"

    batch = _mutate_batch(settings, batch_id, update_options)
    if batch.get("status") == "partial":
        return {"ok": True, "batch": _public_batch(batch, settings)}
    if not batch.get("auto_reframe", True):
        return {"ok": True, "batch": _public_batch(batch, settings)}
    try:
        started = _start_reframe_once(settings, batch_id)
        if started and started.get("reframe_job_id"):
            batch = started
        else:
            _ensure_reframe_waiter(settings, batch_id)
            batch = _get_batch(settings, batch_id)
    except Exception as exc:
        _mutate_batch(
            settings,
            batch_id,
            lambda item: item.update(
                {
                    "status": "waiting_reframe",
                    "message": "上传已完成，横转竖任务正在自动排队。",
                    "reframe_error": str(exc)[:1000],
                }
            ),
        )
        _ensure_reframe_waiter(settings, batch_id)
        batch = _get_batch(settings, batch_id)
    return {"ok": True, "batch": _public_batch(batch, settings)}
