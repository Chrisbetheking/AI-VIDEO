from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import threading
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Optional
from urllib.parse import quote

from fastapi import BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response

from app.services.assets_store import read_assets, upsert_asset
from app.services.memory import MemoryStore
from app.services.storage import maybe_upload_to_r2
from app.services.video import IMAGE_EXTS, VIDEO_EXTS

VERSION = "10.40.8.4.1"
INSTALL_MARKER = "asset_zip_import_v10_40_8_4_1_direct_upload"
TERMINAL_STATUSES = {"done", "failed", "cancelled"}
ALLOWED_EXTS = IMAGE_EXTS | VIDEO_EXTS
DEFAULT_MAX_ZIP_MB = 1024
DEFAULT_MAX_MEMBERS = 10000
DEFAULT_MAX_UNCOMPRESSED_MB = 8192
DEFAULT_MAX_FAILURES = 200

_LOCK = threading.RLock()
_INSTALLED = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)).strip())
    except Exception:
        value = default
    return max(minimum, min(maximum, value))



DEFAULT_DIRECT_UPLOAD_ORIGINS = {
    "https://ai-video-s5v.pages.dev",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
}


def _direct_upload_origins() -> set[str]:
    raw = os.getenv("ASSET_ZIP_CORS_ORIGINS", "").strip()
    if not raw:
        return set(DEFAULT_DIRECT_UPLOAD_ORIGINS)
    return {
        item.strip().rstrip("/")
        for item in raw.split(",")
        if item.strip()
    }


def _install_direct_upload_cors(app: Any) -> None:
    """Expose only the ZIP-import route to the Pages frontend.

    ZIP files bypass Cloudflare Pages and upload directly to the ECS HTTPS
    endpoint. Other APIs continue to use the existing same-origin /api proxy.
    """
    marker = "asset_zip_direct_upload_cors_v10_40_8_4_1"
    state = getattr(app, "state", None)
    if state is not None and getattr(state, marker, False):
        return

    allowed_origins = _direct_upload_origins()

    @app.middleware("http")
    async def _asset_zip_direct_upload_cors(request: Request, call_next: Any) -> Any:
        path = str(request.url.path or "")
        if not path.startswith("/api/assets/import-zip"):
            return await call_next(request)

        origin = str(request.headers.get("origin") or "").rstrip("/")
        allow_origin = ""
        if "*" in allowed_origins:
            allow_origin = "*"
        elif origin and origin in allowed_origins:
            allow_origin = origin

        if request.method.upper() == "OPTIONS":
            response: Any = Response(status_code=204)
        else:
            response = await call_next(request)

        if allow_origin:
            response.headers["Access-Control-Allow-Origin"] = allow_origin
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Accept,Content-Type,Origin"
            response.headers["Access-Control-Max-Age"] = "86400"
        return response

    if state is not None:
        setattr(state, marker, True)

def _jobs_path(settings: Any) -> Path:
    path = settings.data_dir / "asset_zip_import_jobs.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _digest_index_path(settings: Any) -> Path:
    path = settings.data_dir / "asset_sha256_index.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _load_jobs(settings: Any) -> dict[str, dict[str, Any]]:
    data = _read_json(_jobs_path(settings), {})
    return data if isinstance(data, dict) else {}


def _save_jobs(settings: Any, jobs: dict[str, dict[str, Any]]) -> None:
    ordered = sorted(
        jobs.items(),
        key=lambda item: str(item[1].get("created_at") or ""),
        reverse=True,
    )[:200]
    _atomic_write_json(_jobs_path(settings), dict(ordered))


def _public_job(job: dict[str, Any]) -> dict[str, Any]:
    clean = dict(job)
    clean.pop("zip_path", None)
    clean.pop("work_dir", None)
    return clean


def _get_job(settings: Any, job_id: str) -> Optional[dict[str, Any]]:
    with _LOCK:
        return _load_jobs(settings).get(job_id)


def _create_job(settings: Any, job: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        jobs = _load_jobs(settings)
        jobs[str(job["job_id"])] = job
        _save_jobs(settings, jobs)
    return job


def _update_job(settings: Any, job_id: str, **patch: Any) -> dict[str, Any]:
    with _LOCK:
        jobs = _load_jobs(settings)
        current = dict(jobs.get(job_id) or {"job_id": job_id})
        current.update(patch)
        current["updated_at"] = _now_iso()
        jobs[job_id] = current
        _save_jobs(settings, jobs)
        return current


def _load_digest_index(settings: Any) -> dict[str, dict[str, Any]]:
    data = _read_json(_digest_index_path(settings), {})
    return data if isinstance(data, dict) else {}


def _save_digest_index(settings: Any, index: dict[str, dict[str, Any]]) -> None:
    trimmed = dict(list(index.items())[-10000:])
    _atomic_write_json(_digest_index_path(settings), trimmed)


def _safe_folder(value: str, *, kind: str = "") -> str:
    raw = (value or "").strip().lower().replace(" ", "_").replace("-", "_")
    if raw in {"self", "own", "my", "mine", "shot", "拍摄", "自己拍的素材", "ziji"}:
        return "self"
    if raw in {"provided", "client", "other", "others", "别人提供的素材", "客户提供"}:
        return "provided"
    if raw in {"image", "images", "图片", "图片素材"}:
        return "image"
    if raw in {"collected", "crawler", "采集", "采集视频"}:
        return "collected"
    if raw in {"ai", "generated", "ai_image", "generated_image", "ai生成", "ai生成图"}:
        return "ai"
    return "image" if kind == "image" else "self"


def _safe_usage_role(value: str, *, folder: str = "", relative_path: str = "") -> str:
    raw = (value or "").strip().lower().replace(" ", "_").replace("-", "_")
    name = relative_path.lower()
    if raw in {"avatar", "person", "human", "portrait", "人物", "人物素材", "数字人", "口播"}:
        return "avatar"
    if folder == "digital_human" or any(token in name for token in ("avatar", "portrait", "person", "human", "真人", "人物", "数字人")):
        return "avatar"
    return "content"


def _source_type(folder: str) -> str:
    if folder == "collected":
        return "zip_collected"
    if folder == "ai":
        return "zip_ai_generated"
    if folder == "provided":
        return "zip_provided"
    if folder == "image":
        return "zip_image"
    return "zip_upload"


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (int(info.external_attr) >> 16) & 0xFFFF
    return stat.S_IFMT(mode) == stat.S_IFLNK


def _member_name(info: zipfile.ZipInfo) -> str:
    return str(info.filename or "").replace("\\", "/")


def _is_hidden_or_junk(parts: tuple[str, ...]) -> bool:
    lowered = {part.lower() for part in parts}
    if "__macosx" in lowered:
        return True
    return any(part.startswith(".") for part in parts)


def _validate_member_path(info: zipfile.ZipInfo) -> PurePosixPath:
    name = _member_name(info)
    if not name or len(name) > 1024:
        raise ValueError("压缩包内存在空路径或超长路径")
    if name.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", name):
        raise ValueError(f"压缩包包含绝对路径：{name[:180]}")
    path = PurePosixPath(name)
    if any(part in {"..", ""} for part in path.parts):
        raise ValueError(f"压缩包包含路径穿越：{name[:180]}")
    if _is_symlink(info):
        raise ValueError(f"压缩包包含软链接：{name[:180]}")
    return path


def inspect_zip_archive(zip_path: Path) -> dict[str, Any]:
    max_members = _env_int("ASSET_ZIP_MAX_MEMBERS", DEFAULT_MAX_MEMBERS, 1, 50000)
    max_total = _env_int("ASSET_ZIP_MAX_UNCOMPRESSED_MB", DEFAULT_MAX_UNCOMPRESSED_MB, 64, 51200) * 1024 * 1024
    with zipfile.ZipFile(zip_path, "r") as archive:
        infos = archive.infolist()
        if len(infos) > max_members:
            raise ValueError(f"压缩包文件数量超过限制：{len(infos)} > {max_members}")
        total_uncompressed = 0
        media_count = 0
        ignored_count = 0
        for info in infos:
            path = _validate_member_path(info)
            if info.is_dir():
                continue
            total_uncompressed += int(info.file_size or 0)
            if total_uncompressed > max_total:
                raise ValueError("压缩包解压后总体积超过安全限制")
            compressed = max(1, int(info.compress_size or 0))
            ratio = float(info.file_size or 0) / compressed
            if int(info.file_size or 0) > 50 * 1024 * 1024 and ratio > 300:
                raise ValueError(f"疑似压缩炸弹：{str(path)[:180]}")
            if _is_hidden_or_junk(path.parts):
                ignored_count += 1
                continue
            if path.suffix.lower() in ALLOWED_EXTS:
                media_count += 1
            else:
                ignored_count += 1
        if media_count <= 0:
            raise ValueError("压缩包中没有可导入的图片或视频")
        return {
            "members": len(infos),
            "media_count": media_count,
            "ignored_count": ignored_count,
            "total_uncompressed_bytes": total_uncompressed,
        }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _validate_image(path: Path) -> dict[str, Any]:
    from PIL import Image

    with Image.open(path) as image:
        image.verify()
    with Image.open(path) as image:
        width, height = image.size
        if width <= 0 or height <= 0:
            raise ValueError("图片尺寸无效")
        return {"width": int(width), "height": int(height), "duration": 0.0}


def _validate_video(path: Path) -> dict[str, Any]:
    command = [
        "ffprobe", "-v", "error",
        "-show_entries", "stream=codec_type,width,height:format=duration",
        "-of", "json", str(path),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=45, check=True)
    except FileNotFoundError as exc:
        raise ValueError("服务器未安装 ffprobe，无法验证视频") from exc
    except subprocess.TimeoutExpired as exc:
        raise ValueError("视频验证超时") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "ffprobe 验证失败").strip()[:300]
        raise ValueError(detail) from exc
    try:
        data = json.loads(result.stdout or "{}")
    except Exception as exc:
        raise ValueError("视频探测结果无法解析") from exc
    video_stream = next((stream for stream in data.get("streams", []) if stream.get("codec_type") == "video"), None)
    if not video_stream:
        raise ValueError("文件没有有效视频流")
    try:
        duration = max(0.0, float((data.get("format") or {}).get("duration") or 0))
    except Exception:
        duration = 0.0
    return {
        "width": int(video_stream.get("width") or 0),
        "height": int(video_stream.get("height") or 0),
        "duration": duration,
    }


def _validate_media(path: Path, kind: str) -> dict[str, Any]:
    return _validate_image(path) if kind == "image" else _validate_video(path)


def _raw_dict(asset: dict[str, Any]) -> dict[str, Any]:
    value = asset.get("raw")
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _find_duplicate(
    *,
    sha256: str,
    size_bytes: int,
    digest_index: dict[str, dict[str, Any]],
    existing_assets: list[dict[str, Any]],
    settings: Any,
    checked_local_ids: set[str],
) -> Optional[dict[str, Any]]:
    indexed = digest_index.get(sha256)
    if isinstance(indexed, dict):
        return indexed

    for asset in existing_assets:
        raw = _raw_dict(asset)
        old_hash = str(raw.get("sha256") or asset.get("sha256") or "")
        if old_hash:
            digest_index.setdefault(old_hash, {
                "asset_id": str(asset.get("id") or ""),
                "filename": str(asset.get("filename") or ""),
                "size_bytes": int(asset.get("size_bytes") or 0),
            })
            if old_hash == sha256:
                return digest_index[old_hash]

    for asset in existing_assets:
        if int(asset.get("size_bytes") or 0) != size_bytes:
            continue
        asset_id = str(asset.get("id") or "")
        if not asset_id or asset_id in checked_local_ids:
            continue
        checked_local_ids.add(asset_id)
        filename = Path(str(asset.get("filename") or "")).name
        local_path = settings.uploads_dir / filename
        if not local_path.exists() or not local_path.is_file():
            continue
        try:
            old_hash = _sha256_file(local_path)
        except Exception:
            continue
        digest_index[old_hash] = {
            "asset_id": asset_id,
            "filename": filename,
            "size_bytes": int(asset.get("size_bytes") or 0),
        }
        if old_hash == sha256:
            return digest_index[old_hash]
    return None


def _copy_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo, target: Path, max_bytes: int) -> tuple[int, str]:
    total = 0
    digest = hashlib.sha256()
    target.parent.mkdir(parents=True, exist_ok=True)
    with archive.open(info, "r") as source, target.open("wb") as output:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise ValueError(f"单个素材超过 {max_bytes // 1024 // 1024}MB")
            output.write(chunk)
            digest.update(chunk)
    return total, digest.hexdigest()


def _process_zip_job(settings: Any, job_id: str, zip_path: Path, base_url: str, folder: str, usage_role: str) -> None:
    work_dir = zip_path.parent
    failures: list[dict[str, str]] = []
    imported_assets: list[dict[str, Any]] = []
    summary = {
        "imported": 0,
        "duplicates": 0,
        "ignored": 0,
        "failed": 0,
        "images": 0,
        "videos": 0,
        "total_media": 0,
    }
    try:
        inspection = inspect_zip_archive(zip_path)
        summary["total_media"] = int(inspection["media_count"])
        summary["ignored"] = int(inspection["ignored_count"])
        _update_job(
            settings,
            job_id,
            status="running",
            stage="scanning",
            progress=6,
            message=f"安全扫描完成，发现 {summary['total_media']} 个图片/视频",
            summary=summary,
            inspection=inspection,
        )

        memory = MemoryStore(settings)
        try:
            existing_assets = [dict(item) for item in read_assets(settings, memory, limit=3000)]
        except Exception:
            existing_assets = [dict(item) for item in read_assets(settings, None, limit=3000)]
        digest_index = _load_digest_index(settings)
        checked_local_ids: set[str] = set()
        processed = 0
        max_single_bytes = max(1, int(settings.max_upload_mb)) * 1024 * 1024
        failure_limit = _env_int("ASSET_ZIP_MAX_FAILURES", DEFAULT_MAX_FAILURES, 10, 1000)

        with zipfile.ZipFile(zip_path, "r") as archive:
            media_infos: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
            for info in archive.infolist():
                path = _validate_member_path(info)
                if info.is_dir() or _is_hidden_or_junk(path.parts):
                    continue
                if path.suffix.lower() in ALLOWED_EXTS:
                    media_infos.append((info, path))

            for info, relative in media_infos:
                processed += 1
                relative_text = str(relative)
                progress = min(94, 8 + int((processed - 1) / max(1, len(media_infos)) * 85))
                _update_job(
                    settings,
                    job_id,
                    status="running",
                    stage="importing",
                    progress=progress,
                    current_file=relative_text,
                    processed=processed - 1,
                    message=f"正在导入 {processed}/{len(media_infos)}：{relative.name}",
                    summary=summary,
                )

                temp_path = work_dir / "members" / f"{uuid.uuid4().hex}{relative.suffix.lower()}"
                dest: Optional[Path] = None
                try:
                    total, digest = _copy_member(archive, info, temp_path, max_single_bytes)
                    kind = "image" if relative.suffix.lower() in IMAGE_EXTS else "video"
                    media_meta = _validate_media(temp_path, kind)
                    duplicate = _find_duplicate(
                        sha256=digest,
                        size_bytes=total,
                        digest_index=digest_index,
                        existing_assets=existing_assets,
                        settings=settings,
                        checked_local_ids=checked_local_ids,
                    )
                    if duplicate:
                        summary["duplicates"] += 1
                        continue

                    asset_id = uuid.uuid4().hex
                    dest_name = f"{asset_id}{relative.suffix.lower()}"
                    dest = settings.uploads_dir / dest_name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    temp_path.replace(dest)

                    item_folder = _safe_folder(folder, kind=kind)
                    item_usage_role = _safe_usage_role(usage_role, folder=item_folder, relative_path=relative_text)
                    public_url = maybe_upload_to_r2(settings, dest, prefix="uploads")
                    if settings.require_r2_assets and not public_url:
                        raise ValueError("R2 上传失败，已阻止只保存到服务器临时盘")
                    local_url = f"{base_url.rstrip('/')}/files/uploads/{quote(dest_name)}"
                    url = public_url or local_url
                    created_at = _now_iso()
                    payload = {
                        "id": asset_id,
                        "filename": dest_name,
                        "original_name": relative.name,
                        "kind": kind,
                        "url": url,
                        "r2_url": public_url or "",
                        "r2_key": f"uploads/{dest_name}" if public_url else "",
                        "size_bytes": total,
                        "duration": float(media_meta.get("duration") or 0),
                        "width": int(media_meta.get("width") or 0),
                        "height": int(media_meta.get("height") or 0),
                        "folder": item_folder,
                        "source_type": _source_type(item_folder),
                        "usage_role": item_usage_role,
                        "workspace_id": str(getattr(settings, "workspace_id", "") or "default"),
                        "deleted": False,
                        "created_at": created_at,
                        "updated_at": created_at,
                        "raw": {
                            "source": INSTALL_MARKER,
                            "sha256": digest,
                            "zip_name": str((_get_job(settings, job_id) or {}).get("zip_name") or zip_path.name),
                            "zip_relative_path": relative_text,
                            "import_batch_id": job_id,
                            "original_extension": relative.suffix.lower(),
                        },
                    }
                    saved = upsert_asset(settings, payload, memory, require_supabase=False)
                    item = {
                        "id": str(saved.get("id") or asset_id),
                        "filename": dest_name,
                        "original_name": relative.name,
                        "kind": kind,
                        "url": url,
                        "size_bytes": total,
                        "created_at": str(saved.get("created_at") or created_at),
                        "folder": item_folder,
                        "source_type": _source_type(item_folder),
                        "usage_role": item_usage_role,
                        "r2_url": public_url or "",
                        "r2_key": f"uploads/{dest_name}" if public_url else "",
                        "workspace_id": str(saved.get("workspace_id") or getattr(settings, "workspace_id", "") or "default"),
                    }
                    imported_assets.append(item)
                    existing_assets.append({**payload, **saved})
                    digest_index[digest] = {
                        "asset_id": item["id"],
                        "filename": dest_name,
                        "size_bytes": total,
                    }
                    summary["imported"] += 1
                    summary["images" if kind == "image" else "videos"] += 1
                except Exception as exc:
                    summary["failed"] += 1
                    if len(failures) < failure_limit:
                        failures.append({"file": relative_text, "reason": str(exc)[:500]})
                    if dest is not None:
                        dest.unlink(missing_ok=True)
                finally:
                    temp_path.unlink(missing_ok=True)

                _save_digest_index(settings, digest_index)
                _update_job(
                    settings,
                    job_id,
                    status="running",
                    stage="importing",
                    progress=min(95, 8 + int(processed / max(1, len(media_infos)) * 86)),
                    current_file=relative_text,
                    processed=processed,
                    summary=summary,
                    failures=failures,
                    imported_assets=imported_assets[-500:],
                )

        _update_job(
            settings,
            job_id,
            status="done",
            stage="finished",
            progress=100,
            current_file="",
            processed=processed,
            message=f"导入完成：成功 {summary['imported']}，重复 {summary['duplicates']}，忽略 {summary['ignored']}，失败 {summary['failed']}",
            summary=summary,
            failures=failures,
            imported_assets=imported_assets[-500:],
            finished_at=_now_iso(),
        )
    except Exception as exc:
        _update_job(
            settings,
            job_id,
            status="failed",
            stage="failed",
            progress=100,
            message="压缩包导入失败",
            error=str(exc)[:1000],
            summary=summary,
            failures=failures,
            imported_assets=imported_assets[-500:],
            finished_at=_now_iso(),
        )
    finally:
        try:
            shutil.rmtree(work_dir, ignore_errors=True)
        except Exception:
            pass


async def _save_uploaded_zip(file: UploadFile, destination: Path, max_bytes: int) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    try:
        with destination.open("wb") as output:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise HTTPException(status_code=413, detail=f"ZIP 超过 {max_bytes // 1024 // 1024}MB")
                output.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        try:
            await file.close()
        except Exception:
            pass
    return total


def install_asset_zip_import(app: Any, get_settings: Callable[..., Any]) -> None:
    global _INSTALLED
    _install_direct_upload_cors(app)
    if _INSTALLED:
        return
    if any(getattr(route, "path", "") == "/api/assets/import-zip/health" for route in getattr(app, "routes", [])):
        _INSTALLED = True
        return

    @app.get("/api/assets/import-zip/health")
    def asset_zip_import_health() -> dict[str, Any]:
        return {
            "ok": True,
            "version": VERSION,
            "mode": INSTALL_MARKER,
            "allowed_image_exts": sorted(IMAGE_EXTS),
            "allowed_video_exts": sorted(VIDEO_EXTS),
            "background_jobs": True,
            "safe_extract": True,
            "sha256_dedup": True,
            "direct_upload": True,
            "direct_upload_cors": True,
            "direct_upload_origins": sorted(_direct_upload_origins()),
            "streaming_upload": True,
        }

    @app.post("/api/assets/import-zip")
    async def asset_zip_import_start(
        request: Request,
        background_tasks: BackgroundTasks,
        file: UploadFile = File(...),
        folder: str = Form("self"),
        usage_role: str = Form("content"),
        settings: Any = Depends(get_settings),
    ) -> dict[str, Any]:
        original_name = Path(file.filename or "assets.zip").name
        if Path(original_name).suffix.lower() != ".zip":
            raise HTTPException(status_code=400, detail="这里只支持 ZIP 压缩包")
        max_zip_bytes = _env_int("ASSET_ZIP_MAX_MB", DEFAULT_MAX_ZIP_MB, 16, 10240) * 1024 * 1024
        job_id = f"asset_zip_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        work_dir = settings.tmp_dir / "asset_zip_import" / job_id
        zip_path = work_dir / "source.zip"
        size_bytes = await _save_uploaded_zip(file, zip_path, max_zip_bytes)
        try:
            inspection = inspect_zip_archive(zip_path)
        except (zipfile.BadZipFile, ValueError) as exc:
            shutil.rmtree(work_dir, ignore_errors=True)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            shutil.rmtree(work_dir, ignore_errors=True)
            raise HTTPException(status_code=400, detail=f"ZIP 检查失败：{exc}") from exc

        job = {
            "job_id": job_id,
            "version": VERSION,
            "status": "queued",
            "stage": "queued",
            "progress": 1,
            "message": "ZIP 已上传，等待后台解压导入",
            "zip_name": original_name,
            "zip_size_bytes": size_bytes,
            "folder": _safe_folder(folder),
            "usage_role": _safe_usage_role(usage_role),
            "inspection": inspection,
            "summary": {
                "imported": 0,
                "duplicates": 0,
                "ignored": int(inspection.get("ignored_count") or 0),
                "failed": 0,
                "images": 0,
                "videos": 0,
                "total_media": int(inspection.get("media_count") or 0),
            },
            "failures": [],
            "imported_assets": [],
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "zip_path": str(zip_path),
            "work_dir": str(work_dir),
        }
        _create_job(settings, job)
        background_tasks.add_task(
            _process_zip_job,
            settings,
            job_id,
            zip_path,
            str(request.base_url).rstrip("/"),
            folder,
            usage_role,
        )
        return _public_job(job)

    @app.get("/api/assets/import-zip/jobs/{job_id}")
    def asset_zip_import_job(job_id: str, settings: Any = Depends(get_settings)) -> dict[str, Any]:
        safe_id = re.sub(r"[^A-Za-z0-9_-]", "", job_id)[:160]
        job = _get_job(settings, safe_id)
        if not job:
            raise HTTPException(status_code=404, detail="ZIP 导入任务不存在")
        return _public_job(job)

    @app.get("/api/assets/import-zip/jobs")
    def asset_zip_import_jobs(limit: int = 20, settings: Any = Depends(get_settings)) -> dict[str, Any]:
        jobs = list(_load_jobs(settings).values())
        jobs.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        return {
            "ok": True,
            "version": VERSION,
            "jobs": [_public_job(job) for job in jobs[: max(1, min(int(limit or 20), 100))]],
            "total": len(jobs),
        }

    _INSTALLED = True
