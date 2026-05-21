from __future__ import annotations

import mimetypes
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import Settings, get_settings
from app.schemas import (
    AdAnalysisRequest,
    AdAnalysisResponse,
    AssetItem,
    ComposeRequest,
    ComposeResponse,
    CopyRequest,
    GeneratedCopy,
    KnowledgeCreate,
    KnowledgeItem,
    TTSRequest,
    TTSResponse,
)
from app.services.ad_analysis import analyze_ad
from app.services.deepseek import DeepSeekError, generate_copy, test_deepseek
from app.services.kb import KnowledgeBase
from app.services.tts import synthesize_tts
from app.services.video import IMAGE_EXTS, VIDEO_EXTS, compose_video

app = FastAPI(title="短视频 AI 自动化 Demo", version="0.1.0")

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_kb(settings: Settings = Depends(get_settings)) -> KnowledgeBase:
    return KnowledgeBase(settings.db_path)


def file_url(request: Request, name: str) -> str:
    return str(request.url_for("get_output_file", name=name))


def upload_url(request: Request, name: str) -> str:
    return str(request.url_for("get_upload_file", name=name))


def safe_output_path(settings: Settings, name: str) -> Path:
    candidate = (settings.outputs_dir / Path(name).name).resolve()
    if settings.outputs_dir.resolve() not in candidate.parents and candidate != settings.outputs_dir.resolve():
        raise HTTPException(status_code=400, detail="非法文件路径")
    if not candidate.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    return candidate


def safe_upload_path(settings: Settings, name: str) -> Path:
    candidate = (settings.uploads_dir / Path(name).name).resolve()
    if settings.uploads_dir.resolve() not in candidate.parents and candidate != settings.uploads_dir.resolve():
        raise HTTPException(status_code=400, detail="非法文件路径")
    if not candidate.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    return candidate


@app.get("/api/health")
def health(settings: Settings = Depends(get_settings)) -> dict:
    return {
        "ok": True,
        "deepseek_model": settings.deepseek_model,
        "tts_provider": settings.tts_provider,
        "data_dir": str(settings.data_dir),
        "time": datetime.now(timezone.utc).isoformat(),
    }




@app.post("/api/ai-test")
async def api_ai_test(payload: dict | None = None, settings: Settings = Depends(get_settings)) -> dict:
    api_key = ""
    if payload and isinstance(payload, dict):
        api_key = str(payload.get("api_key") or "")
    try:
        return await test_deepseek(settings, api_key_override=api_key)
    except DeepSeekError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/generate-copy", response_model=GeneratedCopy)
async def api_generate_copy(
    req: CopyRequest,
    settings: Settings = Depends(get_settings),
    kb: KnowledgeBase = Depends(get_kb),
) -> GeneratedCopy:
    knowledge = kb.search_texts(" ".join([req.topic, req.industry, req.selling_points]), limit=8)
    try:
        return await generate_copy(settings, req, knowledge)
    except DeepSeekError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/knowledge", response_model=List[KnowledgeItem])
def api_list_knowledge(kb: KnowledgeBase = Depends(get_kb)) -> List[KnowledgeItem]:
    return kb.list(limit=50)


@app.post("/api/knowledge", response_model=KnowledgeItem)
def api_add_knowledge(item: KnowledgeCreate, kb: KnowledgeBase = Depends(get_kb)) -> KnowledgeItem:
    return kb.add(item)


@app.post("/api/tts", response_model=TTSResponse)
async def api_tts(req: TTSRequest, request: Request, settings: Settings = Depends(get_settings)) -> TTSResponse:
    try:
        path, duration, warning = await synthesize_tts(settings, req.text, voice=req.voice, rate=req.rate)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return TTSResponse(
        file_url=file_url(request, path.name),
        file_name=path.name,
        duration_seconds=duration,
        warning=warning,
    )


@app.post("/api/assets", response_model=List[AssetItem])
async def api_upload_assets(
    request: Request,
    files: List[UploadFile] = File(...),
    settings: Settings = Depends(get_settings),
) -> List[AssetItem]:
    results: List[AssetItem] = []
    max_bytes = settings.max_upload_mb * 1024 * 1024
    allowed = IMAGE_EXTS | VIDEO_EXTS
    for file in files:
        original = file.filename or "asset"
        ext = Path(original).suffix.lower()
        if ext not in allowed:
            raise HTTPException(status_code=400, detail=f"不支持的文件类型：{original}")
        asset_id = uuid.uuid4().hex
        dest_name = f"{asset_id}{ext}"
        dest = settings.uploads_dir / dest_name
        total = 0
        with dest.open("wb") as buffer:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    dest.unlink(missing_ok=True)
                    raise HTTPException(status_code=413, detail=f"单次上传超过 {settings.max_upload_mb}MB")
                buffer.write(chunk)
        kind = "image" if ext in IMAGE_EXTS else "video"
        results.append(
            AssetItem(
                id=asset_id,
                filename=dest_name,
                original_name=original,
                kind=kind,
                url=upload_url(request, dest_name),
                size_bytes=total,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
        )
    return results


@app.get("/api/assets", response_model=List[AssetItem])
def api_list_assets(request: Request, settings: Settings = Depends(get_settings)) -> List[AssetItem]:
    items: List[AssetItem] = []
    for path in sorted(settings.uploads_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not path.is_file() or path.suffix.lower() not in (IMAGE_EXTS | VIDEO_EXTS):
            continue
        kind = "image" if path.suffix.lower() in IMAGE_EXTS else "video"
        stat = path.stat()
        items.append(
            AssetItem(
                id=path.stem,
                filename=path.name,
                original_name=path.name,
                kind=kind,
                url=upload_url(request, path.name),
                size_bytes=stat.st_size,
                created_at=datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            )
        )
    return items[:100]


@app.post("/api/compose-video", response_model=ComposeResponse)
async def api_compose_video(
    req: ComposeRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> ComposeResponse:
    asset_paths: List[Path] = []
    if req.asset_ids:
        for asset_id in req.asset_ids:
            matches = list(settings.uploads_dir.glob(f"{Path(asset_id).stem}.*"))
            if matches:
                asset_paths.append(matches[0])
    else:
        asset_paths = list(settings.uploads_dir.glob("*"))[:6]

    audio_path: Optional[Path] = None
    if req.audio_file_name:
        audio_path = safe_output_path(settings, req.audio_file_name)

    try:
        result = await compose_video(
            settings=settings,
            script=req.script,
            asset_paths=asset_paths,
            duration_seconds=req.duration_seconds,
            audio_path=audio_path,
            voice=req.voice,
            rate=req.rate,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return ComposeResponse(
        video_url=file_url(request, result.video_path.name),
        video_name=result.video_path.name,
        subtitle_url=file_url(request, result.subtitle_path.name) if result.subtitle_path else None,
        audio_url=file_url(request, result.audio_path.name) if result.audio_path else None,
        duration_seconds=result.duration_seconds,
        warnings=result.warnings,
    )


@app.post("/api/ad-analysis", response_model=AdAnalysisResponse)
def api_ad_analysis(req: AdAnalysisRequest) -> AdAnalysisResponse:
    return analyze_ad(req)


@app.get("/files/outputs/{name}")
def get_output_file(name: str, settings: Settings = Depends(get_settings)) -> FileResponse:
    path = safe_output_path(settings, name)
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type, filename=path.name)


@app.get("/files/uploads/{name}")
def get_upload_file(name: str, settings: Settings = Depends(get_settings)) -> FileResponse:
    path = safe_upload_path(settings, name)
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type, filename=path.name)


# 可选的单体部署支持：如果 static/index.html 存在，后端才托管前端 dist。
# Render 正式分离部署时，后端 Docker 镜像里通常没有前端 dist。
# 因此这里必须先判断 /app/static/assets 和 /app/static/index.html 是否存在，
# 否则 Starlette 会因为目录不存在直接启动失败。
static_dir = Path(settings.static_dir)
static_assets_dir = static_dir / "assets"
static_index = static_dir / "index.html"

if static_assets_dir.exists() and static_assets_dir.is_dir():
    app.mount("/assets", StaticFiles(directory=static_assets_dir), name="static-assets")

if static_index.exists() and static_index.is_file():

    @app.get("/{full_path:path}")
    def serve_spa(full_path: str) -> FileResponse:
        target = static_dir / full_path

        if full_path and target.exists() and target.is_file():
            return FileResponse(target)

        return FileResponse(static_index)

else:

    @app.get("/")
    def api_root() -> dict:
        return {
            "ok": True,
            "service": "AI-VIDEO API",
            "message": "Backend is running. Frontend should be deployed separately on Cloudflare Pages.",
            "health": "/api/health",
            "docs": "/docs",
        }
