from __future__ import annotations

import asyncio
import hashlib
import json
import mimetypes
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional
from urllib.parse import urlparse

from pydantic import BaseModel
from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
import httpx

from app.config import Settings, get_settings
from app.schemas import (
    AdAnalysisRequest,
    AdAnalysisResponse,
    AssetItem,
    ComposeRequest,
    ComposeResponse,
    CopyRequest,
    CopyRefineRequest,
    CoverRequest,
    CoverResponse,
    ImageGenerateRequest,
    ImageGenerateResponse,
    EditPlanRequest,
    EditPlanResponse,
    GeneratedCopy,
    GrowthDecisionResponse,
    GrowthDecisionRequest,
    SubtitleEmphasisResponse,
    SubtitleEmphasisRequest,
    ShootingPlanResponse,
    ShootingPlanRequest,
    TrendRadarResponse,
    TrendRadarRequest,
    InspirationExtractRequest,
    InspirationExtractResponse,
    KnowledgeCreate,
    KnowledgeItem,
    PlatformPublishRequest,
    PlatformPublishResponse,
    PublishPackageRequest,
    PublishPackageResponse,
    RewriteFromInspirationRequest,
    TTSRequest,
    TTSResponse,
    TTSVoice,
    TTSSegmentsRequest,
    VideoEditChatRequest,
    VideoEditChatResponse,
    VoiceDirectorRequest,
    VoiceDirectorResponse,
    CustomerProfileSave,
    CompetitorVideoSave,
    MemoryContextResponse,
    MemoryEventInput,
    CollectorCookieStatus,
    CollectorCookieUploadRequest,
    ScriptVersionSave,
    DigitalHumanCreateRequest,
    DigitalHumanCreateResponse,
    AutoCollectorRunRequest,
    AutoCollectorRunResponse,
    AutoCollectorStatusResponse,
    OneClickGenerateRequest,
    OneClickGenerateResponse,
    OneClickChatRequest,
    ModelStatusResponse,
    GraphicPostRequest,
    GraphicPostResponse,
    GraphicPostImage,
    LeadAcquisitionRequest,
    LeadAcquisitionPlanResponse,
    CompetitorAccount,
    HeatRadarAccountInput,
    HeatRadarRunRequest,
    HeatRadarRunResponse,
    HeatRadarRewriteRequest,
    HeatRadarRewriteResponse,
    HeatRadarOpenClawIngestRequest,
    HeatRadarOpenClawIngestResponse,
    HeatRadarAccountAuditRequest,
    HeatRadarAccountAuditResponse,
    HeatRadarVideoIntakeRequest,
    HeatRadarVideoIntakeResponse,
    JobCreateRequest,
    CollectorRunStartRequest,
    CollectorRunEventRequest,
    CollectorCommandCreateRequest,
    CollectorCommandCompleteRequest,
    CollectorStatusResponse,
    DigitalHumanProviderOption,
)
from app.services.ad_analysis import analyze_ad
from app.services.cover import create_cover
from app.services.image_generation import generate_image_to_file
from app.services.deepseek import DeepSeekError, generate_copy, generate_edit_plan, generate_growth_decision, generate_lead_acquisition_plan, generate_shooting_plan, generate_subtitle_emphasis, generate_trend_radar, generate_voice_director, refine_copy_with_instruction, rewrite_from_inspiration, test_deepseek, video_edit_chat_advice
from app.services.doubao import extract_with_doubao
from app.services.digital_human import call_external_digital_human_worker, call_fal_lipsync, query_fal_lipsync, call_jimeng_digital_human, query_jimeng_digital_human, create_photo_scene_avatar_image, create_static_avatar_preview, extract_hook_text
from app.services.collector import get_collector_cookie_status, save_collector_cookie_text
from app.services.kb import KnowledgeBase
from app.services.memory import MemoryStore, MemoryWriteError
from app.services.publisher import create_publish_package
from app.services.storage import maybe_upload_to_r2, maybe_delete_from_r2, maybe_list_r2_objects, read_last_storage_error, test_r2_connection
from app.services.tts import get_tts_voices, synthesize_tts, synthesize_tts_segments
from app.services.volcengine_voice_clone import get_voice_clone_status, upload_and_train_voice, save_voice_data, load_voice_data, load_voice_type
from app.services.assets_store import read_assets, upsert_asset, remove_asset, now_iso
from app.services.video import IMAGE_EXTS, VIDEO_EXTS, MediaClip, compose_video
from app.services.video_edit import apply_video_edit
from app.services.auto_collector import run_auto_collection
from app.services.one_click import generate_one_click, revise_one_click
from app.services.industry_packs import list_packs, get_pack, INDUSTRY_PACKS
from app.services.human_overlay import overlay_human_on_video, build_human_overlay_filter
from app.services.minimax_provider import get_minimax_status, text_to_video, image_to_video, query_video_status, get_broll_prompts
from app.services.reply_assistant import suggest_reply, store_lead, list_leads, get_lead, update_lead
from app.services.graphic_post import create_graphic_post
from app.services.heat_radar import run_public_heat_radar, generate_heat_radar_rewrite, ingest_openclaw_heat_radar, audit_heat_radar_accounts, analyze_heat_radar_video_intake
from app.services.collector_control import create_collector_run, append_collector_event, latest_collector_status, create_collector_command, next_collector_command, complete_collector_command, recommended_digital_human_providers
from app.services.jobs import create_job, get_job, list_jobs, update_job

app = FastAPI(title='AI-VIDEO 正式版 API', version='1.0.0')
settings = get_settings()
_auto_collector_task: asyncio.Task | None = None
_auto_agent_jobs: dict[str, dict] = {}



# ===== MVP: Industry Packs =====

@app.get("/api/industry-packs")
def api_industry_packs() -> list[dict]:
    """List available industry packs for the growth studio."""
    return list_packs()


@app.get("/api/industry-packs/{industry}")
def api_industry_pack_detail(industry: str):
    """Get a specific industry pack by name."""
    try:
        pack = get_pack(industry)
        return {
            "ok": True,
            "industry_name": pack.industry_name,
            "pain_points": pack.pain_points,
            "hook_templates": pack.hook_templates,
            "copy_templates": pack.copy_templates,
            "cta_templates": pack.cta_templates,
            "asset_keywords": pack.asset_keywords,
            "lead_keywords": pack.lead_keywords,
            "reply_templates": pack.reply_templates,
            "forbidden_words": pack.forbidden_words,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ===== MVP: Human Overlay =====

class HumanOverlayRequest(BaseModel):
    base_video_name: str = ""
    human_video_name: str = ""
    position: str = "right_bottom"
    scale_pct: str = "40%"
    take_first_seconds: float = 0.0
    keep_human_audio: bool = False


@app.post("/api/human-overlay/preview")
def api_human_overlay_preview(
    req: HumanOverlayRequest,
    settings: Settings = Depends(get_settings),
) -> dict:
    """Return the FFmpeg filter string for preview (no actual compose)."""
    filter_str = build_human_overlay_filter(
        scale_pct=req.scale_pct,
        position=req.position,
    )
    return {"ok": True, "filter": filter_str, "mode": "human_pip" if req.scale_pct in ("30%", "40%") else "human_intro"}


@app.post("/api/human-overlay/compose")
def api_human_overlay_compose(
    req: HumanOverlayRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> dict:
    """Compose human overlay onto base video."""
    base_video = find_media_file(settings, req.base_video_name) if req.base_video_name else None
    human_video = find_media_file(settings, req.human_video_name) if req.human_video_name else None

    if base_video is None:
        raise HTTPException(status_code=400, detail="Base video not found")
    if human_video is None:
        raise HTTPException(status_code=400, detail="Human video not found")

    output = settings.outputs_dir / f"human_overlay_{uuid.uuid4().hex}.mp4"
    result = overlay_human_on_video(
        base_video=base_video,
        human_video=human_video,
        output_path=output,
        position=req.position,
        scale_pct=req.scale_pct,
        take_first_seconds=req.take_first_seconds,
        keep_human_audio=req.keep_human_audio,
    )
    if not result.output_path or not result.output_path.exists():
        return {"ok": False, "error": "Overlay failed", "warnings": result.warnings, "mode": "none"}
    public_url = maybe_upload_to_r2(settings, result.output_path, prefix="videos")
    return {
        "ok": True,
        "video_url": file_url(request, result.output_path.name, public_url),
        "video_name": result.output_path.name,
        "mode": result.mode,
        "warnings": result.warnings,
    }


# ===== Experimental: MiniMax Provider =====

class MiniMaxTextToVideoRequest(BaseModel):
    prompt: str = ""
    negative_prompt: str = ""
    duration_seconds: int = 5
    resolution: str = "1080p"


class MiniMaxImageToVideoRequest(BaseModel):
    image_url: str = ""
    prompt: str = ""
    duration_seconds: int = 5


@app.post("/api/minimax/video/text-to-video")
async def api_minimax_text_to_video(
    req: MiniMaxTextToVideoRequest,
    settings: Settings = Depends(get_settings),
) -> dict:
    """Generate B-roll video from text prompt via MiniMax Hailuo."""
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt is required")
    result = await text_to_video(
        settings,
        prompt=req.prompt,
        negative_prompt=req.negative_prompt,
        duration_seconds=req.duration_seconds,
        resolution=req.resolution,
    )
    return {
        "ok": result.ok,
        "enabled": result.enabled,
        "task_id": result.task_id,
        "status": result.status,
        "video_url": result.video_url,
        "message": result.message,
    }


@app.post("/api/minimax/video/image-to-video")
async def api_minimax_image_to_video(
    req: MiniMaxImageToVideoRequest,
    settings: Settings = Depends(get_settings),
) -> dict:
    """Generate B-roll video from image via MiniMax Hailuo."""
    if not req.image_url.strip():
        raise HTTPException(status_code=400, detail="Image URL is required")
    result = await image_to_video(
        settings,
        image_url=req.image_url,
        prompt=req.prompt,
        duration_seconds=req.duration_seconds,
    )
    return {
        "ok": result.ok,
        "enabled": result.enabled,
        "task_id": result.task_id,
        "status": result.status,
        "video_url": result.video_url,
        "message": result.message,
    }


@app.get("/api/minimax/status")
def api_minimax_status(settings: Settings = Depends(get_settings)) -> dict:
    """Get MiniMax provider status and available B-roll prompts."""
    status = get_minimax_status(settings)
    broll_real_estate = get_broll_prompts("real_estate", count=2)
    broll_foreign_trade = get_broll_prompts("foreign_trade", count=2)
    return {
        "ok": True,
        "enabled": status.enabled,
        "video_model": status.video_model,
        "tts_model": status.tts_model,
        "message": status.message,
        "broll_prompts": {
            "real_estate": broll_real_estate,
            "foreign_trade": broll_foreign_trade,
        },
    }


# ===== Voice Clone V3 =====

@app.get("/api/volcengine/voice-clone/status")
def api_voice_clone_status(settings: Settings = Depends(get_settings)) -> dict:
    """Return Volcengine voice clone status."""
    status = get_voice_clone_status(settings)
    return {
        "ok": status.ok,
        "has_app_id": status.has_app_id,
        "has_access_token": status.has_access_token,
        "has_voice_type": status.has_voice_type,
        "voice_type_masked": status.voice_type_masked,
        "voice_name": status.voice_name,
        "cluster": status.cluster,
        "resource_id": status.resource_id,
        "created_at": status.created_at,
        "message": status.message,
    }


@app.post("/api/volcengine/voice-clone/upload")
async def api_voice_clone_upload(
    file: UploadFile = File(...),
    voice_name: str = Form(""),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Upload reference audio and train Volcengine voice clone V3."""
    filename = (file.filename or "reference.mp3").lower()
    if not any(filename.endswith(ext) for ext in (".mp3", ".wav", ".m4a", ".mpeg")):
        return {"ok": False, "message": "Unsupported audio format. Use mp3, wav, or m4a."}

    try:
        file_bytes = await file.read()
        if len(file_bytes) < 1024:
            return {"ok": False, "message": "Audio file too small (< 1KB)"}
        if len(file_bytes) > 20 * 1024 * 1024:
            return {"ok": False, "message": "Audio file too large (> 20MB)"}
    except Exception as exc:
        return {"ok": False, "message": f"Failed to read uploaded file: {exc}"}

    result = await upload_and_train_voice(settings, file_bytes, filename, voice_name=voice_name)
    if result.ok:
        save_voice_data(
            result.voice_type,
            voice_name=voice_name or result.voice_name,
            resource_id=getattr(settings, "volcengine_resource_id", "seed-icl-2.0") or "",
            cluster=getattr(settings, "volcengine_cluster", "volcano_icl") or "",
        )
    return {
        "ok": result.ok,
        "voice_type": result.voice_type,
        "voice_name": result.voice_name or voice_name,
        "message": result.message,
        "raw_preview": result.raw_preview,
    }



# ===== MVP: Lead Capture =====

class LeadAnalyzeRequest(BaseModel):
    industry: str = "real_estate"
    platform: str = "douyin"
    content: str = ""


class LeadUpdateRequest(BaseModel):
    status: Optional[str] = None


@app.post("/api/leads/analyze")
def api_leads_analyze(req: LeadAnalyzeRequest) -> dict:
    """Analyze a comment/message for lead intent."""
    suggestion = suggest_reply(content=req.content, industry=req.industry, platform=req.platform)
    record = store_lead(suggestion, req.content, req.industry, req.platform)
    return {
        "ok": True,
        "lead_id": record.id,
        "intent_level": suggestion.intent_level,
        "intent_type": suggestion.intent_type,
        "suggested_reply": suggestion.suggested_reply,
        "fallback_reply": suggestion.fallback_reply,
        "next_action": suggestion.next_action,
        "keywords_matched": suggestion.keywords_matched,
        "confidence": suggestion.confidence,
    }


@app.post("/api/leads/reply-suggestions")
def api_leads_reply_suggestions(req: LeadAnalyzeRequest) -> dict:
    """Get reply suggestions for a comment (without storing)."""
    suggestion = suggest_reply(content=req.content, industry=req.industry, platform=req.platform)
    return {
        "ok": True,
        "intent_level": suggestion.intent_level,
        "intent_type": suggestion.intent_type,
        "suggested_reply": suggestion.suggested_reply,
        "fallback_reply": suggestion.fallback_reply,
        "next_action": suggestion.next_action,
        "keywords_matched": suggestion.keywords_matched,
        "confidence": suggestion.confidence,
    }


@app.get("/api/leads")
def api_leads_list(industry: Optional[str] = None) -> list[dict]:
    """List captured leads, optionally filtered by industry."""
    leads = list_leads(industry=industry)
    return [
        {
            "id": r.id,
            "content": r.content,
            "industry": r.industry,
            "platform": r.platform,
            "intent_level": r.intent_level,
            "intent_type": r.intent_type,
            "suggested_reply": r.suggested_reply,
            "status": r.status,
            "created_at": r.created_at,
        }
        for r in leads
    ]


@app.patch("/api/leads/{lead_id}")
def api_leads_update(lead_id: str, req: LeadUpdateRequest) -> dict:
    """Update a lead's status."""
    record = update_lead(lead_id, status=req.status)
    if record is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    return {
        "ok": True,
        "id": record.id,
        "status": record.status,
    }




async def _auto_collector_loop() -> None:
    # Render 免费实例睡眠时不会运行；这个循环适合服务保持唤醒时自动采集。
    await asyncio.sleep(60)
    while True:
        try:
            current = get_settings()
            if current.enable_auto_collector:
                memory = MemoryStore(current)
                req = AutoCollectorRunRequest(
                    seed_links=current.auto_collector_seed_links,
                    include_account_urls=True,
                    limit=current.auto_collector_run_limit,
                    learn_goal=current.auto_collector_learn_goal,
                    token=current.auto_collector_cron_token,
                )
                await run_auto_collection(current, memory, req)
            await asyncio.sleep(max(15, int(current.auto_collector_interval_minutes) * 60))
        except Exception:
            await asyncio.sleep(300)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _trim_jobs(max_jobs: int = 80) -> None:
    if len(_auto_agent_jobs) <= max_jobs:
        return
    for job_id, _ in sorted(_auto_agent_jobs.items(), key=lambda kv: kv[1].get('created_at', ''))[: max(0, len(_auto_agent_jobs) - max_jobs)]:
        _auto_agent_jobs.pop(job_id, None)


async def _run_auto_collection_job(job_id: str, req_data: dict) -> None:
    """Run collection outside the HTTP request so cron-job.org's 30s limit is safe."""
    _auto_agent_jobs[job_id].update({'status': 'running', 'started_at': _utc_now(), 'message': '后台采集学习正在运行。'})
    current = get_settings()
    memory = MemoryStore(current)
    try:
        req = AutoCollectorRunRequest(**req_data)
        result = await run_auto_collection(current, memory, req)
        _auto_agent_jobs[job_id].update({
            'status': 'done',
            'finished_at': _utc_now(),
            'message': '后台采集学习已完成，结果已写入记忆库。',
            'result': result,
            'error': '',
        })
    except Exception as exc:
        _auto_agent_jobs[job_id].update({
            'status': 'failed',
            'finished_at': _utc_now(),
            'message': '后台采集学习失败。',
            'error': str(exc)[:1000],
        })


@app.on_event('startup')
async def _start_auto_collector() -> None:
    global _auto_collector_task
    if settings.enable_auto_collector and _auto_collector_task is None:
        _auto_collector_task = asyncio.create_task(_auto_collector_loop())

# CORS：Cloudflare Pages 与 Render 分离部署时必须允许跨域。
# 如果 CORS_ORIGINS=*，用 allow_origin_regex='.*' 回显 Origin，避免浏览器在某些请求上拦截。
_cors_all = (not settings.cors_origins) or settings.cors_origins.strip() == '*'
app.add_middleware(
    CORSMiddleware,
    allow_origins=[] if _cors_all else settings.cors_list,
    allow_origin_regex='.*' if _cors_all else None,
    allow_credentials=False,
    allow_methods=['*'],
    allow_headers=['*'],
    expose_headers=['*'],
)


def get_kb(settings: Settings = Depends(get_settings)) -> KnowledgeBase:
    return KnowledgeBase(settings.db_path)


def get_memory(settings: Settings = Depends(get_settings)) -> MemoryStore:
    return MemoryStore(settings)


def file_url(request: Request, name: str, public_url: Optional[str] = None) -> str:
    return public_url or str(request.url_for('get_output_file', name=name))


def upload_url(request: Request, name: str, public_url: Optional[str] = None) -> str:
    return public_url or str(request.url_for('get_upload_file', name=name))


def _looks_like_public_http_url(value: str) -> bool:
    return value.startswith('http://') or value.startswith('https://')


def _safe_suffix_from_url(url: str, default: str = '.mp4') -> str:
    try:
        suffix = Path(urlparse(url).path).suffix.lower()
    except Exception:
        suffix = ''
    known_exts = VIDEO_EXTS | IMAGE_EXTS | {'.mp3', '.wav', '.m4a', '.aac', '.ogg'}
    if suffix in known_exts:
        return suffix
    return default


def _safe_media_ext_from_name(name: str | None, default: str = '.mp4') -> str:
    try:
        suffix = Path(name or '').suffix.lower()
    except Exception:
        suffix = ''
    known_exts = VIDEO_EXTS | IMAGE_EXTS | {'.mp3', '.wav', '.m4a', '.aac', '.ogg'}
    return suffix if suffix in known_exts else default


def _compose_max_assets() -> int:
    """How many selected materials a single Render compose job may use.

    Older deployments sometimes had COMPOSE_MAX_ASSETS=2 for demos. Treat that
    as a legacy safety value unless COMPOSE_ALLOW_TINY_ASSETS=true is explicitly
    set, so user-selected timelines no longer silently collapse to two clips.
    """
    raw = os.getenv('COMPOSE_MAX_ASSETS', '12')
    try:
        value = int(raw)
    except Exception:
        value = 12
    allow_tiny = str(os.getenv('COMPOSE_ALLOW_TINY_ASSETS', '')).strip().lower() in {'1', 'true', 'yes', 'on'}
    # 之前服务器环境变量里常遗留 COMPOSE_MAX_ASSETS=4，导致用户明明选了多条素材也只合前 4 条。
    # 默认至少给 12 条；只有显式开启 COMPOSE_ALLOW_TINY_ASSETS=true 时才允许更小。
    if value < 12 and not allow_tiny:
        value = 12
    return max(1, min(12, value))


async def _download_remote_video_with_resume(
    settings: Settings,
    source_url: str,
    tmp: Path,
    *,
    max_bytes: int,
) -> int:
    """Download remote video with retries and HTTP Range resume.

    Some Jimeng/OmniHuman result URLs close the connection midway on Render,
    which surfaces as httpx.ReadError. Retrying from byte 0 often wastes the
    temporary URL window, so we keep the partial file and resume with Range.
    """
    base_headers = {
        'User-Agent': settings.collector_user_agent or 'Mozilla/5.0',
        'Accept': 'video/mp4,video/*,*/*;q=0.8',
        'Connection': 'keep-alive',
    }
    last_error: Exception | None = None
    expected_total: int | None = None

    for attempt in range(1, 7):
        downloaded = tmp.stat().st_size if tmp.exists() else 0
        if downloaded > max_bytes:
            raise RuntimeError(f'数字人视频超过 {settings.max_upload_mb}MB，已停止缓存。')

        headers = dict(base_headers)
        if downloaded > 0:
            headers['Range'] = f'bytes={downloaded}-'

        try:
            timeout = httpx.Timeout(connect=20.0, read=360.0, write=60.0, pool=60.0)
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
                async with client.stream('GET', source_url) as resp:
                    # If the server ignores Range and returns 200, restart cleanly.
                    if downloaded > 0 and resp.status_code == 200:
                        tmp.unlink(missing_ok=True)
                        downloaded = 0
                    elif resp.status_code == 416 and downloaded > 1024:
                        return downloaded

                    resp.raise_for_status()

                    content_range = resp.headers.get('content-range') or ''
                    if '/' in content_range:
                        try:
                            expected_total = int(content_range.rsplit('/', 1)[-1])
                        except Exception:
                            expected_total = None
                    elif resp.headers.get('content-length') and downloaded == 0:
                        try:
                            expected_total = int(resp.headers['content-length'])
                        except Exception:
                            expected_total = None

                    mode = 'ab' if tmp.exists() and downloaded > 0 and resp.status_code == 206 else 'wb'
                    with tmp.open(mode) as f:
                        async for chunk in resp.aiter_bytes(512 * 1024):
                            if not chunk:
                                continue
                            downloaded += len(chunk)
                            if downloaded > max_bytes:
                                raise RuntimeError(f'数字人视频超过 {settings.max_upload_mb}MB，已停止缓存。')
                            f.write(chunk)

                    if downloaded >= 1024 and (expected_total is None or downloaded >= expected_total):
                        return downloaded

        except Exception as exc:
            last_error = exc
            # Keep partial .download file for the next Range retry.
            if attempt < 6:
                await asyncio.sleep(min(12.0, 1.5 * attempt))
                continue
            break

    downloaded = tmp.stat().st_size if tmp.exists() else 0
    if downloaded >= 1024:
        return downloaded
    if last_error is not None:
        raise RuntimeError(f'{type(last_error).__name__}: {str(last_error) or "连接被远端中断"}') from last_error
    raise RuntimeError('下载到的视频文件过小，可能是火山临时 URL 已失效或返回了错误页。')


async def cache_remote_video_to_own_storage(
    settings: Settings,
    request: Request,
    source_url: str,
    *,
    job_id: str = '',
    prefix: str = 'digital-human/final',
) -> tuple[str, str, list[str]]:
    """Download a third-party generated video and return our own stable URL.

    Jimeng/OmniHuman can return temporary signed URLs or URLs that the browser
    cannot play directly because of CORS / anti-hotlinking. The backend usually
    can read the URL, so we cache it into Render's output directory and, when R2
    is configured, upload it to R2. The frontend then plays/downloads our URL.
    """
    warnings: list[str] = []
    if not source_url or not _looks_like_public_http_url(source_url):
        return source_url, '', warnings

    # If it is already our configured public R2 URL, do not download again.
    r2_base = settings.r2_public_base_url.strip().rstrip('/')
    if r2_base and source_url.startswith(r2_base + '/'):
        return source_url, Path(urlparse(source_url).path).name, warnings

    suffix = _safe_suffix_from_url(source_url)
    stable_id = ''.join(ch for ch in (job_id or '') if ch.isalnum() or ch in {'_', '-'})[:80]
    if not stable_id:
        stable_id = hashlib.sha256(source_url.encode('utf-8')).hexdigest()[:24]
    dest = settings.outputs_dir / f'digital_human_{stable_id}{suffix}'

    if not dest.exists() or dest.stat().st_size < 1024:
        tmp = settings.tmp_dir / f'{dest.name}.download'
        tmp.parent.mkdir(parents=True, exist_ok=True)
        max_bytes = max(50, settings.max_upload_mb) * 1024 * 1024
        try:
            downloaded = await _download_remote_video_with_resume(settings, source_url, tmp, max_bytes=max_bytes)
            if downloaded < 1024:
                raise RuntimeError('下载到的视频文件过小，可能是火山临时 URL 已失效或返回了错误页。')
            tmp.replace(dest)
        except Exception as exc:
            warnings.append(f'后端转存火山视频失败，暂时保留火山原始链接：{type(exc).__name__}: {str(exc)[:500]}')
            return source_url, '', warnings

    public_url = maybe_upload_to_r2(settings, dest, prefix=prefix)
    stable_url = file_url(request, dest.name, public_url)
    if public_url:
        warnings.append('已把火山数字人视频转存到 R2，播放和下载使用稳定地址。')
    else:
        warnings.append('已把火山数字人视频缓存到 Render 本地输出目录；如需长期稳定访问，请确认 R2 已接通。')
    return stable_url, dest.name, warnings


async def finalize_digital_human_video_url(
    settings: Settings,
    request: Request,
    result,
) -> tuple[str, str, list[str]]:
    """Return stable video_url/video_name/warnings for a DigitalHumanResult."""
    if not getattr(result, 'video_url', ''):
        return '', '', []
    return await cache_remote_video_to_own_storage(
        settings,
        request,
        result.video_url,
        job_id=getattr(result, 'job_id', '') or '',
    )


def _save_digital_human_asset(
    settings: Settings,
    memory: MemoryStore,
    *,
    video_name: str,
    video_url: str,
    engine: str,
    title: str = '',
) -> None:
    """Put generated digital-human video back into the asset library for later mixing."""
    safe_name = Path(video_name or '').name
    if not safe_name or not video_url:
        return
    r2_base = settings.r2_public_base_url.strip().rstrip('/')
    r2_url = video_url if (r2_base and video_url.startswith(r2_base + '/')) else ''
    r2_key = ''
    if r2_url:
        try:
            r2_key = urlparse(r2_url).path.strip('/')
        except Exception:
            r2_key = ''
    local_path = settings.outputs_dir / safe_name
    size_bytes = local_path.stat().st_size if local_path.exists() else 0
    asset_id = Path(safe_name).stem
    asset_payload = {
        'id': asset_id,
        'filename': safe_name,
        'original_name': title or f'数字人开场_{safe_name}',
        'kind': 'video',
        'url': video_url,
        'size_bytes': size_bytes,
        'created_at': now_iso(),
        'folder': 'digital_human',
        'source_type': 'digital_human_intro',
        'r2_url': r2_url,
        'r2_key': r2_key,
        'workspace_id': settings.workspace_id,
        'deleted': False,
        'engine': engine,
    }
    try:
        upsert_asset(settings, asset_payload, memory, require_supabase=False)
    except Exception:
        # Do not fail generation just because the asset index write failed.
        # Try manifest-only once more so Render/Supabase permission problems do not hide the generated clip.
        try:
            upsert_asset(settings, asset_payload, None, require_supabase=False)
        except Exception:
            pass


def safe_output_path(settings: Settings, name: str) -> Path:
    candidate = (settings.outputs_dir / Path(name).name).resolve()
    if settings.outputs_dir.resolve() not in candidate.parents and candidate != settings.outputs_dir.resolve():
        raise HTTPException(status_code=400, detail='非法文件路径')
    if not candidate.exists():
        raise HTTPException(status_code=404, detail='文件不存在')
    return candidate


def safe_upload_path(settings: Settings, name: str) -> Path:
    candidate = (settings.uploads_dir / Path(name).name).resolve()
    if settings.uploads_dir.resolve() not in candidate.parents and candidate != settings.uploads_dir.resolve():
        raise HTTPException(status_code=400, detail='非法文件路径')
    if not candidate.exists():
        raise HTTPException(status_code=404, detail='文件不存在')
    return candidate


def find_asset_path(settings: Settings, asset_id: str | None) -> Optional[Path]:
    if not asset_id:
        return None
    matches = list(settings.uploads_dir.glob(f'{Path(asset_id).stem}.*'))
    return matches[0] if matches else None


def find_media_file(settings: Settings, file_name: str | None) -> Optional[Path]:
    if not file_name:
        return None
    safe_name = Path(file_name).name
    for root in (settings.outputs_dir, settings.uploads_dir):
        candidate = (root / safe_name).resolve()
        if candidate.exists() and candidate.is_file():
            return candidate
    stem = Path(safe_name).stem
    for root in (settings.outputs_dir, settings.uploads_dir):
        matches = list(root.glob(f'{stem}.*'))
        if matches:
            return matches[0]
    return None



def _public_r2_url_by_key(settings: Settings, key: str) -> str:
    base = settings.r2_public_base_url.strip().rstrip('/')
    if not base or not key:
        return ''
    return f"{base}/{key.strip('/')}"


def _find_r2_public_url_by_name(settings: Settings, prefixes: list[str], name: str, limit: int = 500) -> str:
    """Find a public R2 URL by filename across possible prefixes.

    This fixes old Render-local URLs after instance restart/OOM. Instead of
    guessing only one prefix, list R2 and match the actual object name.
    """
    safe_name = Path(name).name
    if not safe_name or not settings.r2_public_base_url.strip():
        return ''
    for prefix in prefixes:
        try:
            for obj in maybe_list_r2_objects(settings, prefix=prefix, limit=limit):
                if Path(str(obj.get('name') or '')).name == safe_name:
                    url = str(obj.get('url') or '')
                    if url.startswith(('http://', 'https://')):
                        return url
        except Exception:
            continue
    return ''



def read_manifest(settings):
    """
    Read local/static asset manifest for compose-video.

    This function is intentionally defensive: compose-video should not crash
    just because a manifest file is missing or temporarily unreadable. It
    returns an empty list when no manifest exists.
    """
    import json
    from pathlib import Path

    candidate_paths = []

    for attr in (
        "ASSETS_MANIFEST_PATH",
        "assets_manifest_path",
        "MATERIALS_MANIFEST_PATH",
        "materials_manifest_path",
    ):
        value = getattr(settings, attr, None)
        if value:
            candidate_paths.append(str(value))

    candidate_paths.extend([
        "assets_manifest.json",
        "data/assets_manifest.json",
        "storage/assets_manifest.json",
        "materials_manifest.json",
        "data/materials_manifest.json",
        "/tmp/assets_manifest.json",
    ])

    seen_paths = set()
    for path_value in candidate_paths:
        if not path_value or path_value in seen_paths:
            continue
        seen_paths.add(path_value)
        try:
            path = Path(path_value)
            if not path.exists() or not path.is_file():
                continue

            data = json.loads(path.read_text(encoding="utf-8"))

            if isinstance(data, list):
                return data

            if isinstance(data, dict):
                for key in ("items", "assets", "files", "data", "materials"):
                    value = data.get(key)
                    if isinstance(value, list):
                        return value
                return [data]

        except Exception as exc:
            print(f"[compose] read_manifest failed: {path_value} {exc}")

    return []

def _asset_remote_url(settings: Settings, asset_id: str | None, filename: str | None = None) -> str:
    """Resolve an asset selected from the UI even when it only exists in R2."""
    safe_id = ''.join(ch for ch in (asset_id or '') if ch.isalnum() or ch in {'_', '-'})[:128]
    safe_name = Path(filename or '').name if filename else ''

    for raw in read_manifest(settings):
        raw_id = str(raw.get('id') or '')
        raw_name = Path(str(raw.get('filename') or '')).name
        if (safe_id and (raw_id == safe_id or Path(raw_name).stem == safe_id)) or (safe_name and raw_name == safe_name):
            for key in ['r2_url', 'url']:
                url = str(raw.get(key) or '')
                if url.startswith(('http://', 'https://')):
                    return url
            r2_key = str(raw.get('r2_key') or '').strip().strip('/')
            if r2_key:
                return _public_r2_url_by_key(settings, r2_key)

    if safe_name:
        url = _find_r2_public_url_by_name(settings, _upload_r2_prefix_candidates(safe_name), safe_name)
        if url:
            return url
    if safe_id:
        for prefix in ['uploads', 'digital-human/final', 'digital-human/preview', 'digital-human/photo-scene', 'digital-human/avatar', 'digital-human/driver']:
            for obj in maybe_list_r2_objects(settings, prefix=prefix, limit=500):
                name = Path(str(obj.get('name') or '')).name
                if Path(name).stem == safe_id:
                    url = str(obj.get('url') or '')
                    if url.startswith(('http://', 'https://')):
                        return url
    return ''


def _output_remote_url(settings: Settings, filename: str | None) -> str:
    safe_name = Path(filename or '').name
    if not safe_name:
        return ''
    return _find_r2_public_url_by_name(settings, _output_r2_prefix_candidates(safe_name), safe_name)


def _path_from_url_download_name(settings: Settings, url: str, fallback_ext: str = '.jpg') -> Path | None:
    """Only returns a local path if this URL has already been downloaded as output; remote download is done by callers when needed."""
    if not url:
        return None
    suffix = _safe_suffix_from_url(url, fallback_ext)
    name = hashlib.sha256(url.encode('utf-8')).hexdigest()[:24] + suffix
    path = settings.tmp_dir / name
    return path if path.exists() else None


async def _download_remote_media_for_compose(settings: Settings, url: str, fallback_ext: str = '.mp4') -> Optional[Path]:
    if not url or not url.startswith(('http://', 'https://')):
        return None
    suffix = _safe_suffix_from_url(url, fallback_ext)
    allowed_media_exts = IMAGE_EXTS | VIDEO_EXTS | {'.mp3', '.wav', '.m4a', '.aac', '.ogg'}
    if suffix not in allowed_media_exts:
        suffix = fallback_ext if fallback_ext in allowed_media_exts else '.mp4'
    dest = settings.tmp_dir / f'compose_asset_{hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]}{suffix}'
    if dest.exists() and dest.stat().st_size > 2048:
        return dest
    # Compose runs on a small Render instance. Keep a per-file limit, but do not
    # silently drop all R2-only material just because Render restarted.
    try:
        compose_remote_mb = int(os.getenv('COMPOSE_MAX_REMOTE_MB', '120'))
    except Exception:
        compose_remote_mb = 120
    max_bytes = max(8, min(max(8, settings.max_upload_mb), compose_remote_mb)) * 1024 * 1024
    try:
        headers = {'User-Agent': settings.collector_user_agent or 'Mozilla/5.0', 'Accept': '*/*'}
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=20.0, read=180.0, write=60.0, pool=60.0), follow_redirects=True, headers=headers) as client:
            async with client.stream('GET', url) as resp:
                resp.raise_for_status()
                total = 0
                with dest.open('wb') as f:
                    async for chunk in resp.aiter_bytes(512 * 1024):
                        if not chunk:
                            continue
                        total += len(chunk)
                        if total > max_bytes:
                            dest.unlink(missing_ok=True)
                            raise RuntimeError(f'远端素材超过 {compose_remote_mb}MB')
                        f.write(chunk)
        if dest.exists() and dest.stat().st_size > 2048:
            return dest
    except Exception:
        try:
            dest.unlink(missing_ok=True)
        except Exception:
            pass
    return None


async def _ensure_local_media_from_remote(
    settings: Settings,
    local: Optional[Path],
    remote_url: str,
    *,
    fallback_ext: str,
    warnings: list[str],
    label: str,
) -> Optional[Path]:
    """Return a local file path for preview/FFmpeg.

    Assets uploaded before a Render restart may exist only in R2. Static preview
    and FFmpeg need local files, so cache the remote R2 object into /tmp first.
    """
    if local is not None and local.exists() and local.is_file():
        return local
    if not remote_url:
        return local
    cached = await _download_remote_media_for_compose(settings, remote_url, fallback_ext=fallback_ext)
    if cached is not None:
        warnings.append(f'{label}只在 R2，已自动下载到 Render 临时目录后继续生成。')
    return cached


async def _resolve_compose_clip(settings: Settings, clip_req) -> Optional[MediaClip]:
    asset_id = str(getattr(clip_req, 'asset_id', '') or '').strip()
    kind_hint = str(getattr(clip_req, 'kind', '') or '').strip()
    local = find_asset_path(settings, asset_id)
    if local is None:
        remote = _asset_remote_url(settings, asset_id)
        direct_url = str(getattr(clip_req, 'url', '') or '').strip()
        if not remote and direct_url.startswith(('http://', 'https://')):
            remote = direct_url
        filename_hint = str(getattr(clip_req, 'filename', '') or asset_id or remote or '')
        fallback_ext = Path(filename_hint).suffix.lower() if Path(filename_hint).suffix.lower() in (IMAGE_EXTS | VIDEO_EXTS) else ('.jpg' if kind_hint == 'image' else '.mp4')
        local = await _download_remote_media_for_compose(settings, remote, fallback_ext=fallback_ext)
    if local is None:
        return None
    return MediaClip(
        path=local,
        kind=kind_hint or ('image' if local.suffix.lower() in IMAGE_EXTS else 'video'),
        image_seconds=float(getattr(clip_req, 'image_seconds', 2.8) or 2.8),
        video_start=float(getattr(clip_req, 'video_start', 0.0) or 0.0),
        video_end=float(getattr(clip_req, 'video_end', 0.0) or 0.0),
        order=int(getattr(clip_req, 'order', 0) or 0),
    )

@app.get('/api/health')
def health(settings: Settings = Depends(get_settings), memory: MemoryStore = Depends(get_memory)) -> dict:
    memory_status = memory.status()
    return {
        'ok': True,
        'deepseek_model': settings.deepseek_model,
        'ai_provider': settings.ai_provider,
        'ai_text_model': settings.ai_text_model,
        'ai_backup_provider': settings.ai_backup_provider,
        'ai_backup_model': settings.ai_backup_model,
        'asr_provider': settings.asr_provider,
        'asr_model': settings.asr_model,
        'image_provider': settings.image_provider,
        'image_model': settings.image_model,
        'ark_video_model': settings.ark_video_model,
        'tts_provider': settings.tts_provider,
        'r2_enabled': settings.r2_enabled,
        'require_r2_assets': settings.require_r2_assets,
        'memory_enabled': bool(settings.supabase_url and settings.supabase_service_role_key),
        'core_storage_strict': settings.core_storage_strict,
        'memory_status': memory_status,
        'digital_human_enabled': settings.enable_digital_human,
        'workspace_id': settings.workspace_id,
        'data_dir': str(settings.data_dir),
        'time': datetime.now(timezone.utc).isoformat(),
    }



@app.get('/api/jobs')
def api_jobs(limit: int = 50, memory: MemoryStore = Depends(get_memory)) -> list[dict]:
    return list_jobs(memory, limit=max(1, min(int(limit or 50), 100)))


@app.post('/api/jobs')
def api_create_job(req: JobCreateRequest, memory: MemoryStore = Depends(get_memory)) -> dict:
    return create_job(memory, req.type, req.input, title=req.title)


@app.get('/api/jobs/{job_id}')
def api_get_job(job_id: str, memory: MemoryStore = Depends(get_memory)) -> dict:
    job = get_job(memory, job_id)
    if not job:
        raise HTTPException(status_code=404, detail='任务不存在。')
    return job


@app.post('/api/jobs/{job_id}/update')
def api_update_job(job_id: str, payload: dict, memory: MemoryStore = Depends(get_memory)) -> dict:
    return update_job(
        memory,
        job_id,
        status=str(payload.get('status') or '') or None,
        progress=payload.get('progress'),
        output=payload.get('output') if isinstance(payload.get('output'), dict) else None,
        error=str(payload.get('error') or ''),
    )


@app.get('/api/collector/status', response_model=CollectorCookieStatus)
def api_collector_status(settings: Settings = Depends(get_settings)) -> dict:
    return get_collector_cookie_status(settings)


@app.post('/api/collector/cookies', response_model=CollectorCookieStatus)
def api_collector_upload_cookies(req: CollectorCookieUploadRequest, settings: Settings = Depends(get_settings)) -> dict:
    try:
        return save_collector_cookie_text(settings, req.cookie_text)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post('/api/ai-test')
async def api_ai_test(payload: dict | None = None, settings: Settings = Depends(get_settings)) -> dict:
    try:
        return await test_deepseek(settings, api_key_override=str((payload or {}).get('api_key') or ''))
    except DeepSeekError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc



@app.get('/api/model/status', response_model=ModelStatusResponse)
def api_model_status(settings: Settings = Depends(get_settings)) -> ModelStatusResponse:
    return ModelStatusResponse(
        ai_provider=settings.ai_provider,
        ai_text_model=settings.ai_text_model,
        ai_backup_provider=settings.ai_backup_provider,
        ai_backup_model=settings.ai_backup_model,
        qwen_configured=bool(settings.dashscope_api_key.strip()),
        gemini_configured=bool(settings.gemini_api_key.strip()),
        deepseek_configured=bool(settings.deepseek_api_key.strip()),
        asr_provider=settings.asr_provider,
        asr_model=settings.asr_model,
        image_provider=settings.image_provider,
        image_model=settings.image_model,
        image_edit_model=settings.image_edit_model,
    )


@app.post('/api/one-click/generate', response_model=OneClickGenerateResponse)
async def api_one_click_generate(req: OneClickGenerateRequest, settings: Settings = Depends(get_settings), memory: MemoryStore = Depends(get_memory)) -> OneClickGenerateResponse:
    ctx = memory.context()
    if ctx.get('learning_summary') and 'AI 记忆库上下文' not in req.reference_text:
        req.reference_text = (req.reference_text + '\n\nAI 记忆库上下文：\n' + ctx['learning_summary'][:5000]).strip()
    result = await generate_one_click(settings, req)
    memory.save_script_version({**result.copy.model_dump(), 'source': 'one_click_generate', 'raw': {'request': req.model_dump(), 'response': result.model_dump()}})
    memory.save_learning_event({'event_type': 'one_click_project', 'title': result.project_title, 'payload': result.model_dump()})
    return result


@app.post('/api/one-click/chat', response_model=OneClickGenerateResponse)
async def api_one_click_chat(req: OneClickChatRequest, settings: Settings = Depends(get_settings), memory: MemoryStore = Depends(get_memory)) -> OneClickGenerateResponse:
    result = await revise_one_click(settings, req.current, req.instruction, industry=req.industry, audience=req.audience, selling_points=req.selling_points)
    memory.save_script_version({**result.copy.model_dump(), 'source': 'one_click_chat', 'raw': {'instruction': req.instruction, 'response': result.model_dump()}})
    return result


@app.post('/api/lead-acquisition/plan', response_model=LeadAcquisitionPlanResponse)
async def api_lead_acquisition_plan(req: LeadAcquisitionRequest, settings: Settings = Depends(get_settings), memory: MemoryStore = Depends(get_memory)) -> LeadAcquisitionPlanResponse:
    ctx = memory.context()
    if ctx.get('learning_summary') and not req.existing_context:
        req.existing_context = str(ctx.get('learning_summary') or '')[:8000]
    result = await generate_lead_acquisition_plan(settings, req)
    memory.save_learning_event({'event_type': 'lead_acquisition_plan', 'title': req.industry or '获客自动化作战图', 'payload': result.model_dump()})
    return result


@app.get('/api/memory/context', response_model=MemoryContextResponse)
def api_memory_context(memory: MemoryStore = Depends(get_memory)) -> dict:
    return memory.context()



@app.get('/api/agent/status', response_model=AutoCollectorStatusResponse)
def api_agent_status(settings: Settings = Depends(get_settings), memory: MemoryStore = Depends(get_memory)) -> dict:
    events = [e for e in memory.list('learning_events', limit=80) if e.get('event_type') == 'auto_creator_learning'][:8]
    return {
        'enabled': settings.enable_auto_collector,
        'interval_minutes': settings.auto_collector_interval_minutes,
        'run_limit': settings.auto_collector_run_limit,
        'seed_links_configured': bool(settings.auto_collector_seed_links.strip()),
        'cron_token_enabled': bool(settings.auto_collector_cron_token.strip()),
        'memory_enabled': memory.supabase_enabled,
        'competitors_count': len(memory.list('competitor_accounts', limit=100)),
        'recent_learning_events': events,
        'recent_videos': memory.list('competitor_videos', limit=8),
    }


@app.post('/api/agent/start')
async def api_agent_start(req: AutoCollectorRunRequest, background_tasks: BackgroundTasks, settings: Settings = Depends(get_settings)) -> dict:
    if settings.auto_collector_cron_token and req.token != settings.auto_collector_cron_token:
        raise HTTPException(status_code=403, detail='AUTO_COLLECTOR_CRON_TOKEN 不正确。')
    _trim_jobs()
    job_id = uuid.uuid4().hex
    _auto_agent_jobs[job_id] = {
        'job_id': job_id,
        'status': 'queued',
        'created_at': _utc_now(),
        'started_at': '',
        'finished_at': '',
        'message': '任务已进入后台队列，cron 可以立即结束请求。',
        'result': None,
        'error': '',
    }
    background_tasks.add_task(_run_auto_collection_job, job_id, req.model_dump())
    return _auto_agent_jobs[job_id]


@app.get('/api/agent/job/{job_id}')
def api_agent_job(job_id: str) -> dict:
    item = _auto_agent_jobs.get(job_id)
    if not item:
        raise HTTPException(status_code=404, detail='任务不存在，可能服务重启后内存状态已清空；请查看 Supabase learning_events 中的结果。')
    return item


@app.get('/api/agent/jobs')
def api_agent_jobs() -> list[dict]:
    return sorted(_auto_agent_jobs.values(), key=lambda x: x.get('created_at', ''), reverse=True)[:30]


@app.post('/api/agent/run-now', response_model=AutoCollectorRunResponse)
async def api_agent_run_now(req: AutoCollectorRunRequest, settings: Settings = Depends(get_settings), memory: MemoryStore = Depends(get_memory)) -> dict:
    # 手动调试用：同步执行，适合在前端点按钮等待结果；cron-job.org 请用 /api/agent/start。
    if settings.auto_collector_cron_token and req.token != settings.auto_collector_cron_token:
        raise HTTPException(status_code=403, detail='AUTO_COLLECTOR_CRON_TOKEN 不正确。')
    return await run_auto_collection(settings, memory, req)


@app.get('/api/agent/hook-patterns')
def api_agent_hook_patterns(memory: MemoryStore = Depends(get_memory)) -> list[dict]:
    events = [e for e in memory.list('learning_events', limit=120) if e.get('event_type') == 'auto_creator_learning']
    out = []
    for event in events[:30]:
        payload = event.get('payload') or {}
        learning = payload.get('learning') or {}
        out.append({
            'id': event.get('id'),
            'created_at': event.get('created_at'),
            'summary': learning.get('summary', ''),
            'score': learning.get('score', 0),
            'creator_methods': learning.get('creator_methods', []),
            'hook_formulas': learning.get('hook_formulas', []),
            'transfer_rules': learning.get('transfer_rules', []),
            'next_collect_targets': learning.get('next_collect_targets', []),
            'warnings': payload.get('warnings', []),
        })
    return out


@app.post('/api/memory/customer-profile')
def api_memory_customer_profile(req: CustomerProfileSave, memory: MemoryStore = Depends(get_memory)) -> dict:
    item = req.model_dump()
    item['raw'] = req.model_dump()
    return memory.save_customer_profile(item)


@app.get('/api/memory/competitors')
def api_memory_competitors(memory: MemoryStore = Depends(get_memory)) -> list[dict]:
    return memory.list('competitor_accounts', limit=80)


@app.post('/api/memory/competitors')
def api_memory_add_competitor(req: CompetitorAccount, memory: MemoryStore = Depends(get_memory)) -> dict:
    item = req.model_dump()
    item['raw'] = req.model_dump()
    return memory.save_competitor(item)


@app.get('/api/memory/competitor-videos')
def api_memory_competitor_videos(memory: MemoryStore = Depends(get_memory)) -> list[dict]:
    return memory.list('competitor_videos', limit=80)


@app.post('/api/memory/competitor-videos')
def api_memory_add_competitor_video(req: CompetitorVideoSave, memory: MemoryStore = Depends(get_memory)) -> dict:
    item = req.model_dump()
    return memory.save_competitor_video(item)




@app.post('/api/memory/scripts')
def api_memory_script_version(req: ScriptVersionSave, memory: MemoryStore = Depends(get_memory)) -> dict:
    item = req.model_dump()
    return memory.save_script_version(item)

@app.post('/api/memory/events')
def api_memory_event(req: MemoryEventInput, memory: MemoryStore = Depends(get_memory)) -> dict:
    return memory.save_learning_event(req.model_dump())


@app.get('/api/heat-radar/accounts')
def api_heat_radar_accounts(memory: MemoryStore = Depends(get_memory)) -> list[dict]:
    # 新热度账号库优先；没有时兼容旧竞品账号库。
    items = memory.list('heat_radar_accounts', limit=120)
    deleted_ids = {str(x.get('account_id') or '') for x in memory.list('heat_radar_account_deletes', limit=300)}
    active = [x for x in items if str(x.get('id') or '') not in deleted_ids and not x.get('deleted')]
    if active:
        return active
    return memory.list('competitor_accounts', limit=80)


@app.post('/api/heat-radar/accounts')
def api_heat_radar_save_account(req: HeatRadarAccountInput, memory: MemoryStore = Depends(get_memory)) -> dict:
    item = req.model_dump()
    if not str(item.get('name') or '').strip() and not str(item.get('url') or '').strip():
        raise HTTPException(status_code=400, detail='请至少填写账号名称或主页/视频链接。')
    # 前端旧版本会传 heat_acc_xxx；如果 Supabase id 是 uuid 会写入失败，所以统一让后端/数据库生成 id。
    item.pop('id', None)
    if not item.get('created_at'):
        item.pop('created_at', None)
    item['raw'] = {'source': 'heat_radar_account_library'}
    try:
        saved = memory.insert('heat_radar_accounts', item, require_supabase=True)
    except MemoryWriteError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if saved.get('_memory_warning'):
        raise HTTPException(status_code=500, detail=saved['_memory_warning'])
    return saved


@app.delete('/api/heat-radar/accounts/{account_id}')
def api_heat_radar_delete_account(account_id: str, memory: MemoryStore = Depends(get_memory)) -> dict:
    try:
        # 优先软删真实账号记录；旧版本前端也兼容删除事件表过滤。
        memory.update_by_id('heat_radar_accounts', account_id, {'deleted': True}, require_supabase=True)
    except Exception:
        try:
            memory.insert('heat_radar_account_deletes', {'account_id': account_id, 'deleted': True}, require_supabase=True)
        except MemoryWriteError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {'ok': True, 'deleted': account_id}


@app.get('/api/heat-radar/items')
def api_heat_radar_items(memory: MemoryStore = Depends(get_memory)) -> list[dict]:
    return memory.list('heat_radar_items', limit=120)


@app.delete('/api/heat-radar/items/{item_id}')
def api_heat_radar_delete_item(item_id: str, memory: MemoryStore = Depends(get_memory)) -> dict:
    if not item_id:
        raise HTTPException(status_code=400, detail='缺少热点 ID。')
    try:
        # 软删除：保留审计记录，但不再被 /api/heat-radar/items 返回，也不进入 Top5。
        saved = memory.update_by_id('heat_radar_items', item_id, {'deleted': True}, require_supabase=True)
    except MemoryWriteError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f'删除热点失败：{exc}') from exc
    return {'ok': True, 'deleted': item_id, 'item': saved}

@app.get('/api/heat-radar/daily-top3')
def api_heat_radar_daily_top3(memory: MemoryStore = Depends(get_memory)) -> list[dict]:
    return memory.list('heat_daily_top3', limit=30)


@app.get('/api/heat-radar/account-reviews')
def api_heat_radar_account_reviews(memory: MemoryStore = Depends(get_memory)) -> list[dict]:
    return memory.list('heat_radar_account_reviews', limit=120)

@app.post('/api/collector/runs/start')
def api_collector_run_start(req: CollectorRunStartRequest, memory: MemoryStore = Depends(get_memory)) -> dict:
    try:
        return create_collector_run(memory, req.model_dump())
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except MemoryWriteError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post('/api/collector/runs/{run_id}/event')
def api_collector_run_event(run_id: str, req: CollectorRunEventRequest, memory: MemoryStore = Depends(get_memory)) -> dict:
    try:
        return append_collector_event(memory, run_id, req.model_dump())
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except MemoryWriteError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get('/api/collector/runs/latest', response_model=CollectorStatusResponse)
def api_collector_latest(events_limit: int = 30, memory: MemoryStore = Depends(get_memory)) -> CollectorStatusResponse:
    return CollectorStatusResponse(**latest_collector_status(memory, events_limit=events_limit))


@app.post('/api/collector/commands')
def api_collector_command_create(req: CollectorCommandCreateRequest, memory: MemoryStore = Depends(get_memory)) -> dict:
    try:
        return create_collector_command(memory, req.model_dump())
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except MemoryWriteError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get('/api/collector/commands/next')
def api_collector_command_next(token: str = '', memory: MemoryStore = Depends(get_memory)) -> dict:
    try:
        return next_collector_command(memory, token)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except MemoryWriteError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post('/api/collector/commands/{command_id}/complete')
def api_collector_command_complete(command_id: str, req: CollectorCommandCompleteRequest, memory: MemoryStore = Depends(get_memory)) -> dict:
    try:
        return complete_collector_command(memory, command_id, req.model_dump())
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except MemoryWriteError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get('/api/digital-human/providers', response_model=list[DigitalHumanProviderOption])
def api_digital_human_providers() -> list[DigitalHumanProviderOption]:
    return [DigitalHumanProviderOption(**x) for x in recommended_digital_human_providers()]



@app.post('/api/heat-radar/run-public-crawl')
async def api_heat_radar_run_public_crawl(req: HeatRadarRunRequest, settings: Settings = Depends(get_settings), memory: MemoryStore = Depends(get_memory)) -> dict:
    cron_token = os.getenv('HEAT_RADAR_CRON_TOKEN', '').strip()
    if cron_token and req.token != cron_token:
        raise HTTPException(status_code=403, detail='HEAT_RADAR_CRON_TOKEN 不匹配。')
    try:
        return await run_public_heat_radar(settings, memory, req)
    except Exception as exc:
        # 热度雷达不能因为公开平台限制/数据源错误把整个后端打 500。
        return {
            'ok': False,
            'source_mode': 'safe_error_fallback',
            'accounts_count': 0,
            'collected_count': 0,
            'saved_count': 0,
            'top_items': [],
            'analysis': {
                'summary': '热度雷达进入错误兜底：没有生成假数据，请补具体视频/笔记链接或查看后端日志。',
                'content_angles': [],
                'customer_intents': [],
                'lead_magnets': [],
                'reply_hooks': [],
                'next_actions': ['补具体视频/笔记链接', '在账号备注里粘贴标题 + 链接 + 点赞/评论/收藏/分享', '后续接第三方/官方数据源'],
            },
            'warnings': [f'热度雷达接口兜底：{str(exc)[:300]}'],
            'next_actions': ['补具体视频/笔记链接', '查看 Render 最新 Logs'],
            'top_mode': 'error_fallback',
            'fallback_used': True,
        }






@app.post('/api/heat-radar/openclaw/ingest', response_model=HeatRadarOpenClawIngestResponse)
async def api_heat_radar_openclaw_ingest(req: HeatRadarOpenClawIngestRequest, settings: Settings = Depends(get_settings), memory: MemoryStore = Depends(get_memory)) -> HeatRadarOpenClawIngestResponse:
    try:
        result = await ingest_openclaw_heat_radar(settings, memory, req)
        return HeatRadarOpenClawIngestResponse(**result)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        # 外部采集器接入不能把服务打挂；返回结构化错误，方便 OpenClaw 重试。
        return HeatRadarOpenClawIngestResponse(
            ok=False,
            source_name=req.source_name or 'openclaw',
            run_id=req.run_id or '',
            received_accounts=len(req.accounts or []),
            received_items=len(req.items or []),
            warnings=[f'OpenClaw 入库失败：{str(exc)[:300]}'],
            next_actions=['检查 JSON 字段是否包含账号、链接、标题、发布时间和互动数', '查看 Render Logs', '必要时降低单次推送数量'],
        )


@app.post('/api/heat-radar/accounts/audit-staleness', response_model=HeatRadarAccountAuditResponse)
async def api_heat_radar_account_audit(req: HeatRadarAccountAuditRequest, settings: Settings = Depends(get_settings), memory: MemoryStore = Depends(get_memory)) -> HeatRadarAccountAuditResponse:
    try:
        result = await audit_heat_radar_accounts(settings, memory, req)
        return HeatRadarAccountAuditResponse(**result)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        return HeatRadarAccountAuditResponse(ok=False, warnings=[f'账号价值审计失败：{str(exc)[:300]}'], next_actions=['确认账号库不为空', '先完成一次自动采集', '查看 Render Logs'])


@app.post('/api/heat-radar/video-intake', response_model=HeatRadarVideoIntakeResponse)
async def api_heat_radar_video_intake(req: HeatRadarVideoIntakeRequest, settings: Settings = Depends(get_settings), memory: MemoryStore = Depends(get_memory)) -> HeatRadarVideoIntakeResponse:
    try:
        result = await analyze_heat_radar_video_intake(settings, memory, req)
        return HeatRadarVideoIntakeResponse(**result)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        return HeatRadarVideoIntakeResponse(ok=False, warnings=[f'视频入库/分析失败：{str(exc)[:300]}'], next_actions=['确认视频链接可公开访问', '检查 R2/豆包视频理解配置', '查看 Render Logs'])


@app.post('/api/heat-radar/rewrite', response_model=HeatRadarRewriteResponse)
async def api_heat_radar_rewrite(req: HeatRadarRewriteRequest, settings: Settings = Depends(get_settings), memory: MemoryStore = Depends(get_memory)) -> HeatRadarRewriteResponse:
    result = await generate_heat_radar_rewrite(settings, req)
    try:
        memory.save_script_version({
            'title': result.get('variants', [{}])[0].get('title', '热度雷达仿写方案') if isinstance(result, dict) else '热度雷达仿写方案',
            'hook': result.get('variants', [{}])[0].get('hook', '') if isinstance(result, dict) else '',
            'script': result.get('variants', [{}])[0].get('script', '') if isinstance(result, dict) else '',
            'description': result.get('variants', [{}])[0].get('caption', '') if isinstance(result, dict) else '',
            'tags': result.get('variants', [{}])[0].get('tags', []) if isinstance(result, dict) else [],
            'source': 'heat_radar_rewrite',
            'raw': {'request': req.model_dump(), 'response': result},
        })
    except Exception:
        pass
    return HeatRadarRewriteResponse(**result)

@app.post('/api/generate-copy', response_model=GeneratedCopy)
async def api_generate_copy(req: CopyRequest, settings: Settings = Depends(get_settings), kb: KnowledgeBase = Depends(get_kb), memory: MemoryStore = Depends(get_memory)) -> GeneratedCopy:
    knowledge = kb.search_texts(' '.join([req.topic, req.industry, req.selling_points]), limit=8)
    ctx = memory.context()
    if ctx.get('learning_summary'):
        knowledge.insert(0, 'AI 记忆库上下文：\n' + ctx['learning_summary'])
    try:
        result = await generate_copy(settings, req, knowledge)
        memory.save_script_version({**result.model_dump(), 'source': 'generate_copy', 'raw': {'request': req.model_dump(), 'learning_context': ctx.get('learning_summary','')[:4000]}})
        return result
    except DeepSeekError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post('/api/inspiration/extract', response_model=InspirationExtractResponse)
async def api_extract_inspiration(req: InspirationExtractRequest, settings: Settings = Depends(get_settings), memory: MemoryStore = Depends(get_memory)) -> InspirationExtractResponse:
    video_path = find_asset_path(settings, req.asset_id)
    try:
        result = await extract_with_doubao(settings, video_path, source_url=req.source_url, manual_text=req.manual_text)
        memory.save_competitor_video({
            'source_name': result.source_name,
            'platform': 'douyin' if 'douyin' in (req.source_url or '').lower() else 'unknown',
            'source_url': req.source_url,
            'manual_text': req.manual_text,
            'transcript': result.transcript,
            'summary': result.summary,
            'structure': result.structure,
            'hooks': result.hooks,
            'selling_points': result.selling_points,
            'status': result.status,
            'collector_status': result.collector_status,
            'collected_video_url': result.collected_video_url or '',
            'raw': result.model_dump(),
        })
        return result
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post('/api/rewrite-from-inspiration', response_model=GeneratedCopy)
async def api_rewrite_from_inspiration(req: RewriteFromInspirationRequest, settings: Settings = Depends(get_settings), memory: MemoryStore = Depends(get_memory)) -> GeneratedCopy:
    try:
        ctx = memory.context()
        if ctx.get('learning_summary') and 'AI 记忆库上下文' not in req.reference_text:
            req.reference_text = req.reference_text + '\n\nAI 记忆库上下文：\n' + ctx['learning_summary'][:5000]
        result = await rewrite_from_inspiration(settings, req)
        memory.save_script_version({**result.model_dump(), 'source': 'rewrite_from_inspiration', 'raw': {'request': req.model_dump()}})
        return result
    except DeepSeekError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post('/api/refine-copy', response_model=GeneratedCopy)
async def api_refine_copy(req: CopyRefineRequest, settings: Settings = Depends(get_settings)) -> GeneratedCopy:
    try:
        return await refine_copy_with_instruction(settings, req)
    except DeepSeekError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post('/api/video-edit-chat', response_model=VideoEditChatResponse)
async def api_video_edit_chat(req: VideoEditChatRequest, request: Request, settings: Settings = Depends(get_settings)) -> VideoEditChatResponse:
    source_video = find_media_file(settings, req.video_file_name)
    ai = await video_edit_chat_advice(settings, req.instruction, title=req.title, script=req.script, asset_summary=req.asset_summary)
    warnings: List[str] = list(ai.get('warnings') or [])
    actions: List[str] = list(ai.get('actions') or [])
    new_video_url: Optional[str] = None
    new_video_name: Optional[str] = None

    if source_video is None:
        warnings.append('没有找到可修改的视频。请先合成视频，或选择已采集/上传的视频。')
    else:
        edit_result = apply_video_edit(settings, source_video, req.instruction, script=req.script)
        actions.extend(edit_result.actions)
        warnings.extend(edit_result.warnings)
        if edit_result.output_path:
            public_url = maybe_upload_to_r2(settings, edit_result.output_path, prefix='edited-videos')
            new_video_url = file_url(request, edit_result.output_path.name, public_url)
            new_video_name = edit_result.output_path.name

    return VideoEditChatResponse(
        assistant_message=str(ai.get('assistant_message') or '已收到修改要求。'),
        summary=str(ai.get('summary') or '已生成修改建议。'),
        actions=actions[:20],
        new_video_url=new_video_url,
        new_video_name=new_video_name,
        warnings=warnings[:20],
    )


@app.post('/api/edit-plan', response_model=EditPlanResponse)
async def api_edit_plan(req: EditPlanRequest, settings: Settings = Depends(get_settings)) -> EditPlanResponse:
    try:
        return await generate_edit_plan(settings, req)
    except DeepSeekError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post('/api/voice-director', response_model=VoiceDirectorResponse)
async def api_voice_director(req: VoiceDirectorRequest, settings: Settings = Depends(get_settings)) -> VoiceDirectorResponse:
    try:
        return await generate_voice_director(settings, req)
    except DeepSeekError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get('/api/tts/voices', response_model=List[TTSVoice])
def api_tts_voices(settings: Settings = Depends(get_settings)) -> List[TTSVoice]:
    return get_tts_voices(settings)


@app.post('/api/tts', response_model=TTSResponse)
async def api_tts(req: TTSRequest, request: Request, settings: Settings = Depends(get_settings)) -> TTSResponse:
    try:
        path, duration, warning = await synthesize_tts(settings, req.text, voice=req.voice, rate=req.rate)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    public_url = maybe_upload_to_r2(settings, path, prefix='audio')
    return TTSResponse(file_url=file_url(request, path.name, public_url), file_name=path.name, duration_seconds=duration, warning=warning)


@app.post('/api/tts-segments', response_model=TTSResponse)
async def api_tts_segments(req: TTSSegmentsRequest, request: Request, settings: Settings = Depends(get_settings)) -> TTSResponse:
    try:
        # Support both {"text": "..."} and {"segments": [...]} inputs
        segments = req.segments
        if (not segments or len(segments) == 0) and hasattr(req, 'text') and getattr(req, 'text', None):
            # Auto-wrap plain text into segments for backward compatibility
            from app.schemas import VoiceSegment
            segments = [VoiceSegment(text=str(getattr(req, 'text', '')), emotion='', speed_ratio=1.0, volume_ratio=1.0, pitch_ratio=1.0, pause_after_ms=350)]
        if not segments:
            # Try script/copy fallback fields
            fallback_text = ''
            for field in ('script', 'copy', 'text'):
                val = getattr(req, field, None)
                if val and str(val).strip():
                    fallback_text = str(val).strip()
                    break
            if fallback_text:
                from app.schemas import VoiceSegment
                segments = [VoiceSegment(text=fallback_text, emotion='', speed_ratio=1.0, volume_ratio=1.0, pitch_ratio=1.0, pause_after_ms=350)]
            else:
                raise HTTPException(status_code=422, detail='Missing segments or text field')
        path, duration, warning, timings = await synthesize_tts_segments(settings, segments, voice=req.voice, overall_rate=req.overall_rate)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    public_url = maybe_upload_to_r2(settings, path, prefix='audio')
    return TTSResponse(file_url=file_url(request, path.name, public_url), file_name=path.name, duration_seconds=duration, warning=warning, segments=timings)




@app.get('/api/storage/status')
def storage_status(settings: Settings = Depends(get_settings)) -> dict:
    r2_check = test_r2_connection(settings)
    last_error = read_last_storage_error(settings)
    return {
        'ok': True,
        'uploads_dir': str(settings.uploads_dir),
        'outputs_dir': str(settings.outputs_dir),
        'r2_enabled': settings.r2_enabled,
        'r2_bucket_name': settings.r2_bucket_name,
        'r2_public_base_url': settings.r2_public_base_url,
        'r2_check': r2_check,
        'last_r2_error': last_error,
        'max_upload_mb': settings.max_upload_mb,
    }


@app.get('/api/knowledge', response_model=List[KnowledgeItem])
def api_list_knowledge(kb: KnowledgeBase = Depends(get_kb)) -> List[KnowledgeItem]:
    return kb.list(limit=50)


@app.post('/api/knowledge', response_model=KnowledgeItem)
def api_add_knowledge(item: KnowledgeCreate, kb: KnowledgeBase = Depends(get_kb)) -> KnowledgeItem:
    return kb.add(item)




def _normalize_asset_folder(value: str, *, kind: str = '', filename: str = '') -> str:
    raw = (value or '').strip().lower().replace(' ', '_').replace('-', '_')
    name = (filename or '').lower()
    if raw in {'self', 'own', 'my', 'mine', 'shot', '拍摄', '自己拍的素材', 'ziji'}:
        return 'self'
    if raw in {'provided', 'client', 'other', 'others', '别人提供的素材', '客户提供', 'provided_by_client'}:
        return 'provided'
    if raw in {'image', 'images', '图片', '图片素材'}:
        return 'image'
    if raw in {'collected', 'crawler', '采集', '采集视频'}:
        return 'collected'
    if raw in {'ai', 'generated', 'ai_image', 'generated_image', 'ai生成', 'ai生成图'}:
        return 'ai'
    if raw in {'digital_human', 'digitalhuman', 'digital_human_intro', '数字人', '数字人片段'} or name.startswith(('digital_human_', 'digital-human')) or '/digital-human/' in name:
        return 'digital_human'
    if name.startswith('collected_'):
        return 'collected'
    if name.startswith(('ai_image_', 'graphic_', 'cover_')):
        return 'ai'
    if name.startswith(('digital_human_', 'digital-human')) or 'digital-human/' in name:
        return 'digital_human'
    if kind == 'image':
        return 'image'
    return 'self'


def _normalize_asset_usage_role(value: str, *, kind: str = '', filename: str = '', folder: str = '') -> str:
    raw = (value or '').strip().lower().replace(' ', '_').replace('-', '_')
    name = (filename or '').lower()
    folder = (folder or '').lower()
    if raw in {'avatar', 'person', 'human', 'portrait', '人物', '人物素材', '数字人', '口播'}:
        return 'avatar'
    if folder == 'digital_human':
        return 'avatar'
    if name.startswith(('digital_human_', 'digital-human')) or any(x in name for x in ['avatar', 'portrait', 'person', 'human', '口播', '真人', '数字人']):
        return 'avatar'
    return 'content'


def _asset_source_type(folder: str, filename: str = '') -> str:
    name = (filename or '').lower()
    if folder == 'digital_human' or name.startswith(('digital_human_', 'digital-human')) or 'digital-human/' in name:
        return 'digital_human_intro'
    if folder == 'collected':
        return 'collected'
    if folder == 'ai' or name.startswith(('ai_image_', 'graphic_', 'cover_')):
        return 'ai_generated'
    if folder == 'provided':
        return 'provided'
    return 'upload'


@app.post('/api/assets', response_model=List[AssetItem])
async def api_upload_assets(request: Request, files: List[UploadFile] = File(...), folder: str = Form('self'), usage_role: str = Form('content'), settings: Settings = Depends(get_settings), memory: MemoryStore = Depends(get_memory)) -> List[AssetItem]:
    """Upload material assets.

    Fixes two common production problems:
    1) R2 upload failure no longer makes the whole upload fail.
    2) A manifest is kept so the material library does not guess R2 URLs for files
       that never reached R2.
    """
    results: List[AssetItem] = []
    max_bytes = settings.max_upload_mb * 1024 * 1024
    allowed = IMAGE_EXTS | VIDEO_EXTS
    if not files:
        raise HTTPException(status_code=400, detail='没有收到上传文件。')

    for file in files:
        original = file.filename or 'asset'
        ext = Path(original).suffix.lower()
        if ext not in allowed:
            raise HTTPException(status_code=400, detail=f'不支持的文件类型：{original}')
        asset_id = uuid.uuid4().hex
        dest_name = f'{asset_id}{ext}'
        dest = settings.uploads_dir / dest_name
        total = 0
        try:
            with dest.open('wb') as buffer:
                while True:
                    chunk = await file.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        dest.unlink(missing_ok=True)
                        raise HTTPException(status_code=413, detail=f'单个素材超过 {settings.max_upload_mb}MB；请压缩后再上传，或升级后端实例。')
                    buffer.write(chunk)
        finally:
            try:
                await file.close()
            except Exception:
                pass

        kind = 'image' if ext in IMAGE_EXTS else 'video'
        item_folder = _normalize_asset_folder(folder, kind=kind, filename=original)
        item_usage_role = _normalize_asset_usage_role(usage_role, kind=kind, filename=original, folder=item_folder)
        created_at = now_iso()
        public_url = maybe_upload_to_r2(settings, dest, prefix='uploads')
        if settings.require_r2_assets and not public_url:
            dest.unlink(missing_ok=True)
            raise HTTPException(status_code=502, detail='R2 上传失败，已阻止只保存到 Render 临时盘。请检查 R2 环境变量和公开域名。')
        url = upload_url(request, dest_name, public_url)
        asset_payload = {
            'id': asset_id,
            'filename': dest_name,
            'original_name': original,
            'kind': kind,
            'url': url,
            'size_bytes': total,
            'created_at': created_at,
            'folder': item_folder,
            'source_type': _asset_source_type(item_folder, original),
            'usage_role': item_usage_role,
            'r2_url': public_url or '',
            'r2_key': f'uploads/{dest_name}' if public_url else '',
            'deleted': False,
        }
        try:
            saved_asset = upsert_asset(settings, asset_payload, memory, require_supabase=False)
        except MemoryWriteError as exc:
            dest.unlink(missing_ok=True)
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        item = AssetItem(
            id=str(saved_asset.get('id') or asset_id),
            filename=dest_name,
            original_name=original,
            kind=kind,
            url=url,
            size_bytes=total,
            created_at=str(saved_asset.get('created_at') or created_at),
            folder=item_folder,
            source_type=_asset_source_type(item_folder, original),
            usage_role=item_usage_role,
            r2_url=public_url or '',
            r2_key=f'uploads/{dest_name}' if public_url else '',
            workspace_id=str(saved_asset.get('workspace_id') or settings.workspace_id or ''),
        )
        results.append(item)
    return results


@app.get('/api/assets', response_model=List[AssetItem])
def api_list_assets(
    request: Request,
    kind: Optional[str] = None,
    q: str = '',
    limit: int = 120,
    include_r2: bool = True,
    settings: Settings = Depends(get_settings),
    memory: MemoryStore = Depends(get_memory),
) -> List[AssetItem]:
    """List material assets.

    The endpoint must always return JSON. R2 is best-effort; if R2 is broken,
    the frontend still receives local/manifest assets and diagnostics are in
    /api/storage/status.
    """
    items: List[AssetItem] = []
    seen: set[str] = set()
    allowed_kinds = {'image', 'video'}
    kind_filter = kind if kind in allowed_kinds else None
    query = (q or '').strip().lower()

    def add_item(item: AssetItem) -> None:
        if item.filename in seen:
            return
        if kind_filter and item.kind != kind_filter:
            return
        searchable = f'{item.original_name} {item.filename} {item.kind}'.lower()
        if query and query not in searchable:
            return
        seen.add(item.filename)
        items.append(item)

    # 1) Prefer Supabase assets table; manifest remains local/dev cache.
    for raw in read_assets(settings, memory, limit=max(1, min(limit, 500))):
        try:
            filename = Path(str(raw.get('filename') or '')).name
            if not filename:
                continue
            ext = Path(filename).suffix.lower()
            if ext not in (IMAGE_EXTS | VIDEO_EXTS):
                continue
            local_path = settings.uploads_dir / filename
            url = str(raw.get('r2_url') or raw.get('url') or '')
            # If manifest only has an old local URL and the file is gone, skip it unless R2 URL exists.
            if (not url or '/files/uploads/' in url) and local_path.exists():
                url = upload_url(request, filename)
            elif (not url or '/files/uploads/' in url) and not local_path.exists():
                continue
            add_item(AssetItem(
                id=str(raw.get('id') or Path(filename).stem),
                filename=filename,
                original_name=str(raw.get('original_name') or filename),
                kind=str(raw.get('kind') or ('image' if ext in IMAGE_EXTS else 'video')),
                url=url,
                size_bytes=int(raw.get('size_bytes') or (local_path.stat().st_size if local_path.exists() else 0)),
                created_at=str(raw.get('created_at') or now_iso()),
                folder=_normalize_asset_folder(str(raw.get('folder') or ''), kind=str(raw.get('kind') or ('image' if ext in IMAGE_EXTS else 'video')), filename=filename),
                source_type=str(raw.get('source_type') or _asset_source_type(_normalize_asset_folder(str(raw.get('folder') or ''), kind=str(raw.get('kind') or ('image' if ext in IMAGE_EXTS else 'video')), filename=filename), filename)),
                usage_role=str(raw.get('usage_role') or _normalize_asset_usage_role('', kind=str(raw.get('kind') or ('image' if ext in IMAGE_EXTS else 'video')), filename=filename, folder=_normalize_asset_folder(str(raw.get('folder') or ''), kind=str(raw.get('kind') or ('image' if ext in IMAGE_EXTS else 'video')), filename=filename))),
            ))
        except Exception:
            continue

    # 2) Local files not in manifest. Do not guess R2 URLs here; use local URL.
    if settings.uploads_dir.exists():
        for path in sorted(settings.uploads_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if not path.is_file() or path.suffix.lower() not in (IMAGE_EXTS | VIDEO_EXTS):
                continue
            item_kind = 'image' if path.suffix.lower() in IMAGE_EXTS else 'video'
            stat = path.stat()
            add_item(AssetItem(
                id=path.stem,
                filename=path.name,
                original_name=path.name,
                kind=item_kind,
                url=upload_url(request, path.name),
                size_bytes=stat.st_size,
                created_at=datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                folder=_normalize_asset_folder('', kind=item_kind, filename=path.name),
                source_type=_asset_source_type(_normalize_asset_folder('', kind=item_kind, filename=path.name), path.name),
                usage_role=_normalize_asset_usage_role('', kind=item_kind, filename=path.name, folder=_normalize_asset_folder('', kind=item_kind, filename=path.name)),
            ))

    # 3) R2 fallback after Render restart/OOM. Short timeouts in storage.py prevent hanging.
    if include_r2:
        per_prefix_limit = max(20, min(int(limit or 200), 200))
        for prefix in ['uploads', 'digital-human/final', 'digital-human/preview', 'digital-human/photo-scene', 'digital-human/avatar', 'digital-human/driver']:
            for obj in maybe_list_r2_objects(settings, prefix=prefix, limit=per_prefix_limit):
                name = obj.get('name') or ''
                ext = Path(name).suffix.lower()
                if ext not in (IMAGE_EXTS | VIDEO_EXTS):
                    continue
                item_kind = 'image' if ext in IMAGE_EXTS else 'video'
                lm = obj.get('last_modified')
                if hasattr(lm, 'isoformat'):
                    created_at = lm.astimezone(timezone.utc).isoformat()
                else:
                    created_at = now_iso()
                add_item(AssetItem(
                    id=Path(name).stem,
                    filename=name,
                    original_name=name,
                    kind=item_kind,
                    url=obj.get('url') or upload_url(request, name),
                    size_bytes=int(obj.get('size') or 0),
                    created_at=created_at,
                    folder=_normalize_asset_folder('', kind=item_kind, filename=name),
                    source_type=_asset_source_type(_normalize_asset_folder('', kind=item_kind, filename=name), name),
                    usage_role=_normalize_asset_usage_role('', kind=item_kind, filename=name, folder=_normalize_asset_folder('', kind=item_kind, filename=name)),
                ))

    items.sort(key=lambda it: it.created_at, reverse=True)
    return items[:max(1, min(limit, 300))]


@app.delete('/api/assets/{asset_id}')
def api_delete_asset(asset_id: str, settings: Settings = Depends(get_settings), memory: MemoryStore = Depends(get_memory)) -> dict:
    safe_id = ''.join(ch for ch in asset_id if ch.isalnum() or ch in {'_', '-'})[:128]
    if not safe_id:
        raise HTTPException(status_code=400, detail='素材 ID 无效')
    deleted: list[str] = []
    warnings: list[str] = []

    try:
        removed_manifest = remove_asset(settings, safe_id, memory, require_supabase=settings.core_storage_strict)
    except MemoryWriteError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    filenames: set[str] = set()
    object_keys: set[str] = set()
    for item in removed_manifest:
        filename = Path(str(item.get('filename') or '')).name
        if filename:
            filenames.add(filename)
        key = str(item.get('r2_key') or '').strip().strip('/')
        if key:
            object_keys.add(key)

    # Fall back to all possible extensions if the user deletes a R2-discovered item.
    for ext in IMAGE_EXTS | VIDEO_EXTS:
        filenames.add(f'{safe_id}{ext}')

    for filename in filenames:
        path = settings.uploads_dir / filename
        if path.exists() and path.is_file():
            try:
                path.unlink()
                deleted.append(path.name)
            except Exception as exc:
                warnings.append(f'本地文件删除失败：{path.name}：{exc}')
        for prefix in _upload_r2_prefix_candidates(filename):
            object_keys.add(f'{prefix.strip("/")}/{filename}')

    r2_deleted = maybe_delete_from_r2(settings, sorted(object_keys))
    deleted.extend(r2_deleted)

    if not deleted and not removed_manifest:
        raise HTTPException(status_code=404, detail='素材不存在，可能已经删除或只存在于旧临时目录。')
    return {'ok': True, 'deleted': deleted, 'warnings': warnings}


@app.get('/api/collected-videos', response_model=List[AssetItem])
def api_list_collected_videos(request: Request, settings: Settings = Depends(get_settings), memory: MemoryStore = Depends(get_memory)) -> List[AssetItem]:
    items = api_list_assets(request=request, settings=settings, memory=memory)
    return [item for item in items if item.kind == 'video' and item.filename.startswith('collected_')][:100]


@app.post('/api/compose-video', response_model=ComposeResponse)
async def api_compose_video(req: ComposeRequest, request: Request, settings: Settings = Depends(get_settings)) -> ComposeResponse:
    """Compose the final video with ordered material clips and safer subtitles.

    Fixes:
    - R2-only old materials are downloaded back to Render before FFmpeg.
    - Selected material order, image duration, and video trim ranges are respected.
    - Final duration follows the generated audio, so subtitles do not drift away from speech.
    """
    pre_warnings: list[str] = []
    media_clips: List[MediaClip] = []
    missing_asset_ids: list[str] = []

    if req.asset_plan:
        compose_max_assets = _compose_max_assets()
        sorted_plan = sorted(req.asset_plan, key=lambda x: x.order)
        if len(sorted_plan) > compose_max_assets:
            pre_warnings.append(f'本次后端最多合成前 {compose_max_assets} 个素材；如需更多，建议改由 ECS/Worker 合成，或提高服务器配置。')
        for clip_req in sorted_plan[:compose_max_assets]:
            clip = await _resolve_compose_clip(settings, clip_req)
            if clip:
                media_clips.append(clip)
            else:
                missing_asset_ids.append(str(clip_req.asset_id))
    elif req.asset_ids:
        compose_max_assets = _compose_max_assets()
        if len(req.asset_ids) > compose_max_assets:
            pre_warnings.append(f'本次后端最多合成前 {compose_max_assets} 个素材；如需更多，建议改由 ECS/Worker 合成，或提高服务器配置。')
        for order, asset_id in enumerate(req.asset_ids[:compose_max_assets]):
            class _Tmp:
                pass
            tmp = _Tmp()
            tmp.asset_id = str(asset_id)
            tmp.order = order
            tmp.kind = ''
            tmp.image_seconds = 2.8
            tmp.video_start = 0.0
            tmp.video_end = 0.0
            clip = await _resolve_compose_clip(settings, tmp)
            if clip:
                media_clips.append(clip)
            else:
                missing_asset_ids.append(str(asset_id))
        if missing_asset_ids:
            pre_warnings.append('部分素材只存在于旧临时目录或 R2 远端不可访问，已自动跳过；可在素材页重新上传或检查 R2 公开访问。')
    else:
        media_clips = [MediaClip(path=p, order=i) for i, p in enumerate(settings.uploads_dir.glob('*')) if p.is_file()][:6]

    audio_path: Optional[Path] = None
    if req.audio_file_name:
        audio_path = find_media_file(settings, req.audio_file_name)
        if audio_path is None:
            remote_audio = _output_remote_url(settings, req.audio_file_name)
            downloaded = await _download_remote_media_for_compose(settings, remote_audio, fallback_ext=Path(req.audio_file_name).suffix or '.mp3')
            if downloaded:
                audio_path = downloaded
            else:
                pre_warnings.append(f'配音文件 {Path(req.audio_file_name).name} 不在当前 Render 本地磁盘，已根据当前文案自动重新生成配音。')

    try:
        result = await compose_video(
            settings=settings,
            script=req.script,
            asset_paths=[getattr(c, "path", c) for c in media_clips],
            duration_seconds=req.duration_seconds,
            audio_path=audio_path,
            voice=req.voice,
            rate=req.rate,
            subtitle_segments=[x.model_dump() for x in req.subtitle_segments],
            subtitle_size=req.subtitle_size,
            subtitle_margin_v=req.subtitle_margin_v,
            subtitle_position=req.subtitle_position,
            subtitle_style_preset=req.subtitle_style_preset,
            subtitle_keywords=req.subtitle_keywords,
            keyword_sfx_enabled=req.keyword_sfx_enabled,
            keyword_sfx_volume=req.keyword_sfx_volume,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f'视频合成失败：{str(exc)[:1800]}') from exc

    video_public = maybe_upload_to_r2(settings, result.video_path, prefix='videos')
    subtitle_public = maybe_upload_to_r2(settings, result.subtitle_path, prefix='subtitles') if result.subtitle_path else None
    audio_public = maybe_upload_to_r2(settings, result.audio_path, prefix='audio') if result.audio_path else None
    return ComposeResponse(
        video_url=file_url(request, result.video_path.name, video_public),
        video_name=result.video_path.name,
        subtitle_url=file_url(request, result.subtitle_path.name, subtitle_public) if result.subtitle_path else None,
        audio_url=file_url(request, result.audio_path.name, audio_public) if result.audio_path else None,
        duration_seconds=result.duration_seconds,
        warnings=[*pre_warnings, *result.warnings],
    )




async def _download_remote_image_for_cover(settings: Settings, url: str) -> Optional[Path]:
    if not url or not url.startswith(('http://', 'https://')):
        return None
    suffix = _safe_suffix_from_url(url, '.jpg')
    if suffix not in {'.jpg', '.jpeg', '.png', '.webp'}:
        suffix = '.jpg'
    dest = settings.tmp_dir / f'cover_bg_{hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]}{suffix}'
    if dest.exists() and dest.stat().st_size > 1024:
        return dest
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            if len(resp.content) < 1024:
                return None
            dest.write_bytes(resp.content)
            return dest
    except Exception:
        return None


def _cover_source_local_path(settings: Settings, req: CoverRequest) -> Optional[Path]:
    if req.source_asset_id:
        path = find_asset_path(settings, req.source_asset_id)
        if path:
            return path
    if req.source_file_name:
        path = find_media_file(settings, req.source_file_name)
        if path:
            return path
    return None
@app.post('/api/cover', response_model=CoverResponse)
async def api_cover(req: CoverRequest, request: Request, settings: Settings = Depends(get_settings)) -> CoverResponse:
    try:
        source_path = _cover_source_local_path(settings, req)
        if source_path is None and req.background_url:
            source_path = await _download_remote_image_for_cover(settings, req.background_url)
        path, prompt = create_cover(
            settings,
            req.title,
            hook=req.hook,
            subtitle=req.subtitle,
            brand=req.brand,
            source_path=source_path,
            template=req.template or 'douyin',
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    public_url = maybe_upload_to_r2(settings, path, prefix='covers')
    return CoverResponse(cover_url=file_url(request, path.name, public_url), cover_name=path.name, prompt=prompt)


@app.post('/api/image/generate', response_model=ImageGenerateResponse)
async def api_image_generate(req: ImageGenerateRequest, request: Request, settings: Settings = Depends(get_settings)) -> ImageGenerateResponse:
    final_prompt = f"{req.prompt}\n风格要求：{req.style}\n用途：作为图文引流或视频封面的纯视觉背景，保留干净留白，标题文案由系统后期叠加。"
    try:
        path, source_url, warnings = await generate_image_to_file(settings, final_prompt, size=req.size or settings.image_size, quality=req.quality or settings.image_quality)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    public_url = maybe_upload_to_r2(settings, path, prefix='generated-images')
    return ImageGenerateResponse(
        image_url=file_url(request, path.name, public_url),
        image_name=path.name,
        prompt=final_prompt,
        provider=settings.image_provider,
        model=settings.image_model,
        warnings=[*warnings, '图片已下载到后端并尝试转存 R2。' if public_url else '图片已生成到 Render 本地；如需长期保存请确认 R2 正常。'],
    )




@app.post('/api/graphic-post/generate', response_model=GraphicPostResponse)
async def api_graphic_post_generate(req: GraphicPostRequest, request: Request, settings: Settings = Depends(get_settings)) -> GraphicPostResponse:
    """Generate a real lead-generation graphic post package, not just a video cover.

    It creates 3-8 vertical images suitable for Xiaohongshu / Douyin image posts / WeChat Moments.
    Background can come from selected material, an existing generated image, or Seedream AI image generation.
    """
    warnings: list[str] = []
    source_path: Optional[Path] = None
    mode = (req.background_mode or 'asset').strip().lower()

    if mode in {'asset', 'material', 'selected_asset'} and req.source_asset_id:
        source_path = find_asset_path(settings, req.source_asset_id)
        if source_path is None:
            remote = _asset_remote_url(settings, req.source_asset_id)
            if remote:
                source_path = await _download_remote_image_for_cover(settings, remote)
            if source_path is None:
                warnings.append('选中的素材当前只存在远端或不是图片，图文包已使用系统背景。')

    if source_path is None and req.background_url:
        source_path = await _download_remote_image_for_cover(settings, req.background_url)
        if source_path is None:
            warnings.append('背景图下载失败，已使用系统背景。')

    if source_path is None and mode in {'ai', 'ai_image', 'seedream'}:
        prompt = req.image_prompt.strip() or f"{req.industry or req.title}，商业引流图文背景，真实高级，适合小红书和抖音图文，画面精美，干净留白，后期叠加标题"
        try:
            source_path, _source_url, ai_warnings = await generate_image_to_file(settings, prompt, size=settings.image_size, quality=settings.image_quality)
            warnings.extend(ai_warnings)
            maybe_upload_to_r2(settings, source_path, prefix='graphic-backgrounds')
        except Exception as exc:
            warnings.append(f'AI 背景图生成失败，已使用系统背景：{str(exc)[:300]}')

    title = req.title or req.industry or '图文引流包'
    hook = req.hook or '先收藏，这几件事一定要弄懂。'
    try:
        slides = create_graphic_post(
            settings,
            title=title,
            hook=hook,
            script=req.script,
            selling_points=req.selling_points,
            cta=req.cta,
            platform=req.platform,
            slide_count=req.slide_count,
            source_path=source_path,
            style=req.style,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f'图文引流包生成失败：{str(exc)[:1200]}') from exc

    images: list[GraphicPostImage] = []
    for slide in slides:
        public_url = maybe_upload_to_r2(settings, slide.path, prefix='graphic-posts')
        images.append(GraphicPostImage(
            image_url=file_url(request, slide.path.name, public_url),
            image_name=slide.path.name,
            title=slide.title,
            caption=slide.caption,
            role=slide.role,
        ))

    tags = ' '.join([f'#{x.strip()}' for x in [req.industry, '图文引流', '避坑指南'] if x.strip()])
    description = f"{hook}\n\n{req.cta or '想要完整清单，私信发你。'}\n{tags}".strip()
    return GraphicPostResponse(
        package_title=title,
        platform=req.platform,
        images=images,
        publish_title=title,
        publish_description=description,
        checklist=[
            '首图只放一个强标题，负责让人停下来。',
            '中间每页只讲一个重点，负责收藏和转发。',
            '最后一页必须有私信/评论/领取清单的动作。',
            '发布时优先选择小红书图文、抖音图文或朋友圈九宫格。',
        ],
        warnings=warnings,
    )


@app.post('/api/publish-package', response_model=PublishPackageResponse)
def api_publish_package(req: PublishPackageRequest, request: Request, settings: Settings = Depends(get_settings)) -> PublishPackageResponse:
    video_path = safe_output_path(settings, req.video_file_name) if req.video_file_name else None
    cover_path = safe_output_path(settings, req.cover_file_name) if req.cover_file_name else None
    path, checklist = create_publish_package(settings, req.title, req.description, req.tags, video_path, cover_path)
    public_url = maybe_upload_to_r2(settings, path, prefix='packages')
    return PublishPackageResponse(package_url=file_url(request, path.name, public_url), package_name=path.name, status='manual_publish_ready', checklist=checklist)




@app.post('/api/digital-human/create', response_model=DigitalHumanCreateResponse)
async def api_digital_human_create(
    req: DigitalHumanCreateRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
    memory: MemoryStore = Depends(get_memory),
) -> DigitalHumanCreateResponse:
    if not settings.enable_digital_human:
        raise HTTPException(status_code=400, detail='数字人功能未启用。')
    if not req.consent_confirmed:
        raise HTTPException(status_code=400, detail='请先确认已获得本人形象和声音授权。')

    avatar_path = find_asset_path(settings, req.avatar_asset_id) or find_media_file(settings, req.avatar_file_name)
    audio_path = find_media_file(settings, req.audio_file_name)
    driver_video_path = find_asset_path(settings, req.driver_video_asset_id)

    # Render 免费实例重启后，本地 /app/data 可能丢失，但老素材已经在 R2。
    # 这里允许直接用 R2 公网 URL 提交给火山 OmniHuman，而不是强制要求本地文件存在。
    avatar_remote_url = _asset_remote_url(settings, req.avatar_asset_id, req.avatar_file_name) if avatar_path is None else ''
    audio_remote_url = _output_remote_url(settings, req.audio_file_name) if audio_path is None else ''
    driver_remote_url = _asset_remote_url(settings, req.driver_video_asset_id, None) if driver_video_path is None and req.driver_video_asset_id else ''

    if avatar_path is None and not avatar_remote_url:
        raise HTTPException(status_code=400, detail='请先上传或选择数字人形象素材：正脸照片、半身照片或一段本人视频。旧素材如果只在 R2，请确认 R2 公共访问已开启并刷新素材库。')
    if audio_path is None and not audio_remote_url:
        raise HTTPException(status_code=400, detail='请先生成或选择配音音频。旧音频如果只在 R2，请确认 R2 公共访问已开启。')

    engine = (req.engine or 'auto').strip().lower()
    if engine == 'auto':
        engine = settings.digital_human_engine.strip().lower() or 'preview'

    avatar_public = maybe_upload_to_r2(settings, avatar_path, prefix='digital-human/avatar') if avatar_path else avatar_remote_url
    audio_public = maybe_upload_to_r2(settings, audio_path, prefix='digital-human/audio') if audio_path else audio_remote_url
    driver_public = maybe_upload_to_r2(settings, driver_video_path, prefix='digital-human/driver') if driver_video_path else driver_remote_url
    avatar_url_value = upload_url(request, avatar_path.name, avatar_public) if avatar_path else avatar_public
    audio_url_value = file_url(request, audio_path.name, audio_public) if audio_path else audio_public
    driver_url_value = upload_url(request, driver_video_path.name, driver_public) if driver_video_path else driver_public

    warnings: List[str] = []
    # Extract hook_text for digital human: only first sentence, 18-24 chars max.
    hook_text = extract_hook_text(req.script, max_chars=24) if req.script else ""
    hook_title = req.title or hook_text or ""
    try:
        if engine in {'jimeng', 'jimeng_omni15', 'omnihuman15', 'omnihuman', 'volcengine_avatar', 'volcengine_jimeng'}:
            result = await call_jimeng_digital_human(
                settings,
                avatar_path=avatar_path,
                audio_path=audio_path,
                avatar_url=avatar_url_value,
                audio_url=audio_url_value,
                driver_video_url=driver_url_value,
                script=hook_text or req.script,
                title=hook_title,
                model=req.jimeng_model or 'omnihuman15',
            )
            stable_video_url, stable_video_name, cache_warnings = await finalize_digital_human_video_url(settings, request, result)
            if hook_text:
                warnings.append(f'已提取口播钩子文案：{hook_text}')
            memory.save_learning_event({
                'event_type': 'digital_human_jimeng',
                'title': req.title or '火山即梦数字人任务',
                'payload': {
                    'engine': result.engine,
                    'status': result.status,
                    'video_url': stable_video_url or result.video_url,
                    'source_video_url': result.video_url,
                    'job_id': result.job_id,
                },
            })
            raw = result.raw or {}
            if stable_video_url and stable_video_url != result.video_url:
                raw = {**raw, '_cached_video_url': stable_video_url, '_source_video_url': result.video_url}
            return DigitalHumanCreateResponse(
                status=result.status,
                engine=result.engine,
                message=result.message,
                video_url=stable_video_url or result.video_url,
                video_name=stable_video_name or None,
                job_id=result.job_id,
                warnings=[*(result.warnings or []), *cache_warnings],
                raw=raw,
            )

        if engine in {'fal_lipsync', 'fal', 'sync_lipsync', 'fal-ai/sync-lipsync'}:
            # fal.ai sync-lipsync is video-to-video. It needs a real presenter/template MP4, not a still photo.
            avatar_ext = ''
            if avatar_path:
                avatar_ext = avatar_path.suffix.lower()
            else:
                avatar_ext = _safe_suffix_from_url(avatar_url_value, '')
            if avatar_ext in IMAGE_EXTS:
                raise HTTPException(status_code=400, detail='fal.ai 真人模板口型同步需要 5-20 秒本人授权 MP4 视频；你当前选择的是图片。图片口播请先用静态预览/SadTalker，真人感方案请上传顾问正面半身说话视频。')
            result = await call_fal_lipsync(
                settings,
                video_url=avatar_url_value,
                audio_url=audio_url_value,
                script=req.script,
                title=req.title,
            )
            stable_video_url, stable_video_name, cache_warnings = await finalize_digital_human_video_url(settings, request, result)
            final_url = stable_video_url or result.video_url
            final_name = stable_video_name or None
            if final_url and final_name:
                _save_digital_human_asset(settings, memory, video_name=final_name, video_url=final_url, engine=result.engine, title=req.title or '数字人开场片段')
            memory.save_learning_event({
                'event_type': 'digital_human_fal_lipsync',
                'title': req.title or 'fal.ai 真人模板口型同步',
                'payload': {
                    'engine': result.engine,
                    'status': result.status,
                    'video_url': final_url,
                    'source_video_url': result.video_url,
                    'job_id': result.job_id,
                },
            })
            raw = result.raw or {}
            if stable_video_url and stable_video_url != result.video_url:
                raw = {**raw, '_cached_video_url': stable_video_url, '_source_video_url': result.video_url}
            return DigitalHumanCreateResponse(
                status=result.status,
                engine=result.engine,
                message=result.message,
                video_url=final_url,
                video_name=final_name,
                job_id=result.job_id,
                warnings=[*(result.warnings or []), *cache_warnings, '已自动保存到素材库，可在素材选择/成片合成里继续使用。'] if final_url else [*(result.warnings or []), *cache_warnings],
                raw=raw,
            )

        if engine in {'photo_scene', 'photo_scene_preview', 'scene_photo', 'photo_avatar'}:
            # 照片场景数字人 MVP：本人授权照片 + 第 1 段配音 -> 场景片头视频。
            # 这不是完整的真人口型同步；它把照片稳定放入楼道/样板间/园林等场景，适合作为 5-8 秒片头。
            avatar_path = await _ensure_local_media_from_remote(
                settings,
                avatar_path,
                avatar_remote_url,
                fallback_ext=_safe_media_ext_from_name(req.avatar_file_name, '.jpg'),
                warnings=warnings,
                label='照片场景数字人头像',
            )
            audio_path = await _ensure_local_media_from_remote(
                settings,
                audio_path,
                audio_remote_url,
                fallback_ext=_safe_media_ext_from_name(req.audio_file_name, '.mp3'),
                warnings=warnings,
                label='数字人开场音频',
            )
            if avatar_path is None or audio_path is None:
                raise HTTPException(status_code=400, detail='照片场景数字人需要本人照片和第 1 段开场音频；请确认素材在本地或 R2 可访问。')
            avatar_ext = avatar_path.suffix.lower()
            if avatar_ext not in IMAGE_EXTS:
                raise HTTPException(status_code=400, detail='照片场景数字人请上传 JPG/PNG/WebP 本人授权照片；真人模板视频请改选 fal.ai 口型同步。')

            scene_label = (req.scene_template or '样板间客厅讲解').strip()
            scene_prompt = (req.scene_prompt or '').strip() or f"马来西亚房产顾问站在{scene_label}，真实楼盘场景，现代住宅，高级自然光，竖屏短视频背景，干净可信，不要文字，不要水印"
            background_path = None
            try:
                background_path, _bg_source, bg_warnings = await generate_image_to_file(settings, scene_prompt, size=settings.image_size, quality=settings.image_quality)
                warnings.extend([f'场景背景：{w}' for w in (bg_warnings or [])])
            except Exception as exc:
                warnings.append(f'AI 场景背景生成失败，已使用本地稳定场景底图：{str(exc)[:160]}')

            scene_image = create_photo_scene_avatar_image(settings, avatar_path, title=req.title, scene=scene_label, background_path=background_path)
            public_scene = maybe_upload_to_r2(settings, scene_image, prefix='digital-human/photo-scene')
            preview = create_static_avatar_preview(settings, scene_image, audio_path, title=req.title)
            public_url = maybe_upload_to_r2(settings, preview, prefix='digital-human/final')
            final_url = file_url(request, preview.name, public_url)
            _save_digital_human_asset(settings, memory, video_name=preview.name, video_url=final_url, engine='photo_scene', title=req.title or '照片场景数字人片头')
            memory.save_learning_event({
                'event_type': 'digital_human_photo_scene',
                'title': req.title or '照片场景数字人片头',
                'payload': {
                    'engine': 'photo_scene',
                    'scene_template': scene_label,
                    'scene_prompt': scene_prompt,
                    'scene_image_url': file_url(request, scene_image.name, public_scene),
                    'video_url': final_url,
                },
            })
            return DigitalHumanCreateResponse(
                status='done',
                engine='photo_scene',
                message='已生成照片场景数字人片头，并自动保存到素材库。',
                video_url=final_url,
                video_name=preview.name,
                warnings=[*warnings, '当前照片场景模式为稳定 MVP：会生成场景片头并配音，但不是完整真人口型同步。要更强嘴型可后续接 LivePortrait/SadTalker/MuseTalk Worker。'],
                raw={'scene_template': scene_label, 'scene_prompt': scene_prompt, 'scene_image_name': scene_image.name},
            )

        if engine in {'webhook', 'sadtalker', 'wav2lip', 'musetalk', 'liveportrait'} and settings.digital_human_webhook_url:
            result = await call_external_digital_human_worker(
                settings,
                avatar_url=avatar_url_value,
                audio_url=audio_url_value,
                driver_video_url=driver_url_value,
                script=req.script,
                title=req.title,
                engine=engine,
            )
            stable_video_url, stable_video_name, cache_warnings = await finalize_digital_human_video_url(settings, request, result)
            memory.save_learning_event({
                'event_type': 'digital_human',
                'title': req.title or '数字人任务',
                'payload': {
                    'engine': result.engine,
                    'status': result.status,
                    'video_url': stable_video_url or result.video_url,
                    'source_video_url': result.video_url,
                    'job_id': result.job_id,
                },
            })
            raw = result.raw or {}
            if stable_video_url and stable_video_url != result.video_url:
                raw = {**raw, '_cached_video_url': stable_video_url, '_source_video_url': result.video_url}
            return DigitalHumanCreateResponse(
                status=result.status,
                engine=result.engine,
                message=result.message,
                video_url=stable_video_url or result.video_url,
                video_name=stable_video_name or None,
                job_id=result.job_id,
                warnings=[*(result.warnings or []), *cache_warnings],
                raw=raw,
            )

        # Static preview / no-training fallback needs local files for FFmpeg.
        # If the selected avatar/audio only exists in R2, cache it back to /tmp automatically.
        avatar_path = await _ensure_local_media_from_remote(
            settings,
            avatar_path,
            avatar_remote_url,
            fallback_ext=_safe_media_ext_from_name(req.avatar_file_name, '.jpg'),
            warnings=warnings,
            label='数字人形象素材',
        )
        audio_path = await _ensure_local_media_from_remote(
            settings,
            audio_path,
            audio_remote_url,
            fallback_ext=_safe_media_ext_from_name(req.audio_file_name, '.mp3'),
            warnings=warnings,
            label='配音音频',
        )
        if avatar_path is None or audio_path is None:
            raise HTTPException(status_code=400, detail='静态预览无法读取素材：本地文件不存在，且 R2 自动回源下载失败。请确认 R2 公共访问已开启，或重新上传素材/重新生成配音。')
        preview = create_static_avatar_preview(settings, avatar_path, audio_path, title=req.title)
        public_url = maybe_upload_to_r2(settings, preview, prefix='digital-human/preview')
        warnings.append('当前未配置真实数字人 GPU/API 引擎，已生成静态头像预览视频。要真实口型同步，请配置 DIGITAL_HUMAN_WEBHOOK_URL。')
        warnings.append('推荐引擎：火山虚拟数字人 / HeyGen API / SadTalker / MuseTalk / Wav2Lip / LivePortrait。')
        memory.save_learning_event({
            'event_type': 'digital_human_preview',
            'title': req.title or '数字人预览',
            'payload': {'engine': engine, 'file_name': preview.name},
        })
        return DigitalHumanCreateResponse(
            status='preview_ready',
            engine='preview',
            message='已生成数字人静态预览视频。',
            video_url=file_url(request, preview.name, public_url),
            video_name=preview.name,
            warnings=warnings,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


async def _digital_human_status_response(
    *,
    job_id: str,
    request: Request,
    model: str,
    settings: Settings,
    status_url: str = '',
    response_url: str = '',
    endpoint: str = '',
) -> DigitalHumanCreateResponse:
    if not settings.enable_digital_human:
        raise HTTPException(status_code=400, detail='数字人功能未启用。')
    job_id = (job_id or '').strip()
    model = (model or '').strip()
    try:
        if job_id.startswith('fal:') or model.startswith('fal') or 'sync-lipsync' in model or status_url or response_url:
            fal_request_id = job_id.split(':', 1)[1] if job_id.startswith('fal:') else job_id
            result = await query_fal_lipsync(
                settings,
                request_id=fal_request_id,
                status_url=status_url,
                response_url=response_url,
                endpoint=endpoint or (model if 'sync-lipsync' in model else ''),
            )
        else:
            result = await query_jimeng_digital_human(settings, task_id=job_id, model=model or 'omnihuman15')
        stable_video_url, stable_video_name, cache_warnings = await finalize_digital_human_video_url(settings, request, result)
        final_url = stable_video_url or result.video_url
        final_name = stable_video_name or None
        if final_url and final_name:
            try:
                _save_digital_human_asset(settings, get_memory(settings), video_name=final_name, video_url=final_url, engine=result.engine, title='数字人开场片段')
            except Exception:
                pass
        raw = result.raw or {}
        if stable_video_url and stable_video_url != result.video_url:
            raw = {**raw, '_cached_video_url': stable_video_url, '_source_video_url': result.video_url}
        return DigitalHumanCreateResponse(
            status=result.status,
            engine=result.engine,
            message=result.message,
            video_url=final_url,
            video_name=final_name,
            job_id=result.job_id,
            warnings=[*(result.warnings or []), *cache_warnings],
            raw=raw,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get('/api/digital-human/status', response_model=DigitalHumanCreateResponse)
async def api_digital_human_status_query(
    request: Request,
    job_id: str,
    model: str = 'fal_lipsync',
    status_url: str = '',
    response_url: str = '',
    endpoint: str = '',
    settings: Settings = Depends(get_settings),
) -> DigitalHumanCreateResponse:
    return await _digital_human_status_response(
        job_id=job_id, request=request, model=model, settings=settings,
        status_url=status_url, response_url=response_url, endpoint=endpoint,
    )


@app.post('/api/digital-human/status', response_model=DigitalHumanCreateResponse)
async def api_digital_human_status_post(
    payload: dict[str, Any],
    request: Request,
    settings: Settings = Depends(get_settings),
) -> DigitalHumanCreateResponse:
    raw = payload.get('raw') if isinstance(payload.get('raw'), dict) else {}
    return await _digital_human_status_response(
        job_id=str(payload.get('job_id') or ''),
        request=request,
        model=str(payload.get('model') or raw.get('endpoint') or raw.get('model') or 'fal_lipsync'),
        settings=settings,
        status_url=str(payload.get('status_url') or raw.get('status_url') or ''),
        response_url=str(payload.get('response_url') or raw.get('response_url') or ''),
        endpoint=str(payload.get('endpoint') or raw.get('endpoint') or raw.get('model') or ''),
    )


@app.get('/api/digital-human/status/{job_id:path}', response_model=DigitalHumanCreateResponse)
async def api_digital_human_status(
    job_id: str,
    request: Request,
    model: str = 'omnihuman15',
    settings: Settings = Depends(get_settings),
) -> DigitalHumanCreateResponse:
    return await _digital_human_status_response(job_id=job_id, request=request, model=model, settings=settings)


@app.post('/api/platform-publish', response_model=PlatformPublishResponse)
def api_platform_publish(req: PlatformPublishRequest, settings: Settings = Depends(get_settings)) -> PlatformPublishResponse:
    platform_map = {
        'douyin': '抖音',
        'shipinhao': '视频号',
        'kuaishou': '快手',
        'xiaohongshu': '小红书',
    }
    platform_name = platform_map.get(req.platform, req.platform)
    checklist = [
        '当前版本先保留平台发布入口，不自动发布。',
        '等开放平台应用审核通过后，接入 OAuth 授权、视频上传、发布状态查询。',
        '发布前请确认视频、封面、配音、素材均已授权。',
        '建议先下载视频和封面，人工发布测试转化数据。',
    ]
    if not settings.enable_platform_publish:
        return PlatformPublishResponse(platform=platform_name, status='pending_open_platform', message=f'{platform_name} 自动发布接口未启用：等待开放平台权限申请通过。', checklist=checklist)
    return PlatformPublishResponse(platform=platform_name, status='not_implemented', message=f'{platform_name} 自动发布权限已开启，但当前适配器尚未配置。', checklist=checklist)


@app.post('/api/ad-analysis', response_model=AdAnalysisResponse)
def api_ad_analysis(req: AdAnalysisRequest) -> AdAnalysisResponse:
    return analyze_ad(req)


@app.post('/api/trend-radar', response_model=TrendRadarResponse)
async def api_trend_radar(req: TrendRadarRequest, settings: Settings = Depends(get_settings), memory: MemoryStore = Depends(get_memory)) -> TrendRadarResponse:
    try:
        ctx = memory.context()
        if ctx.get('learning_summary'):
            req.competitor_notes = (req.competitor_notes + '\n\n数据库已沉淀上下文：\n' + ctx['learning_summary'][:6000]).strip()
        result = await generate_trend_radar(settings, req)
        if settings.industry_radar_auto_save:
            memory.save_trend_radar({
                'industry': req.industry,
                'audience': req.audience,
                'region': req.region,
                'keywords': req.keywords,
                **result.model_dump(),
                'raw': {'request': req.model_dump(), 'response': result.model_dump()},
            })
        return result
    except DeepSeekError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc




@app.post('/api/trend-radar/auto', response_model=TrendRadarResponse)
async def api_trend_radar_auto(req: TrendRadarRequest, settings: Settings = Depends(get_settings), memory: MemoryStore = Depends(get_memory)) -> TrendRadarResponse:
    ctx = memory.context()
    profile = ctx.get('profile') or {}
    if not req.industry:
        req.industry = profile.get('industry', '')
    if not req.audience:
        req.audience = profile.get('audience', '')
    if not req.region:
        req.region = profile.get('lead_region', '')
    if not req.keywords:
        raw = profile.get('trend_keywords', '') or '获客,投流,同城,客户转化,短视频获客'
        req.keywords = [x.strip() for x in raw.replace('，', ',').split(',') if x.strip()]
    req.competitor_notes = (req.competitor_notes + '\n\n自动读取数据库上下文：\n' + (ctx.get('learning_summary') or '')[:7000]).strip()
    result = await generate_trend_radar(settings, req)
    memory.save_trend_radar({
        'industry': req.industry,
        'audience': req.audience,
        'region': req.region,
        'keywords': req.keywords,
        **result.model_dump(),
        'raw': {'mode': 'auto', 'request': req.model_dump(), 'context': ctx},
    })
    memory.save_learning_event({'event_type': 'auto_trend_radar', 'title': '自动生成行业爆点雷达', 'payload': result.model_dump()})
    return result


@app.post('/api/shooting-plan', response_model=ShootingPlanResponse)
async def api_shooting_plan(req: ShootingPlanRequest, settings: Settings = Depends(get_settings)) -> ShootingPlanResponse:
    try:
        return await generate_shooting_plan(settings, req)
    except DeepSeekError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post('/api/subtitle-emphasis', response_model=SubtitleEmphasisResponse)
async def api_subtitle_emphasis(req: SubtitleEmphasisRequest, settings: Settings = Depends(get_settings)) -> SubtitleEmphasisResponse:
    try:
        return await generate_subtitle_emphasis(settings, req)
    except DeepSeekError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post('/api/growth-decision', response_model=GrowthDecisionResponse)
async def api_growth_decision(req: GrowthDecisionRequest, settings: Settings = Depends(get_settings)) -> GrowthDecisionResponse:
    try:
        return await generate_growth_decision(settings, req)
    except DeepSeekError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def _safe_public_r2_url(settings: Settings, prefix: str, name: str) -> str:
    base = settings.r2_public_base_url.strip().rstrip('/')
    if not base:
        return ''
    clean_prefix = prefix.strip('/')
    return f"{base}/{clean_prefix}/{Path(name).name}"


def _output_r2_prefix_candidates(name: str) -> list[str]:
    safe_name = Path(name).name
    lower = safe_name.lower()
    if lower.startswith('tts') or lower.endswith(('.mp3', '.wav', '.m4a', '.aac')):
        return ['audio', 'digital-human/audio', 'outputs']
    if lower.endswith('.mp4'):
        return ['digital-human/final', 'videos', 'digital-human/preview', 'digital-human/result', 'outputs']
    if lower.endswith(('.srt', '.ass', '.vtt')):
        return ['subtitles', 'outputs']
    if lower.endswith(('.jpg', '.jpeg', '.png', '.webp')):
        return ['covers', 'generated-images', 'outputs']
    if lower.endswith('.zip'):
        return ['packages', 'outputs']
    return ['outputs']


def _upload_r2_prefix_candidates(name: str) -> list[str]:
    safe_name = Path(name).name
    lower = safe_name.lower()
    if lower.endswith(('.jpg', '.jpeg', '.png', '.webp')):
        return ['uploads', 'digital-human/avatar']
    if lower.endswith(('.mp4', '.mov', '.webm', '.mkv')):
        return ['uploads', 'digital-human/driver']
    return ['uploads']


@app.get('/files/outputs/{name}')
def get_output_file(name: str, settings: Settings = Depends(get_settings)):
    safe_name = Path(name).name
    path = (settings.outputs_dir / safe_name).resolve()
    if settings.outputs_dir.resolve() in path.parents and path.exists() and path.is_file():
        media_type = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
        return FileResponse(path, media_type=media_type, filename=path.name)
    # Render 免费实例重启/OOM 后，本地临时文件可能丢失；如果 R2 已开启，直接跳到可能的长期存储地址。
    # 这样旧的 audio/video URL 不会立刻变成 404，本地文件丢失时仍优先尝试 R2。
    if settings.r2_public_base_url.strip():
        url = _find_r2_public_url_by_name(settings, _output_r2_prefix_candidates(safe_name), safe_name) or _safe_public_r2_url(settings, _output_r2_prefix_candidates(safe_name)[0], safe_name)
        if url:
            return RedirectResponse(url=url, status_code=302)
    raise HTTPException(status_code=404, detail='文件不存在：本地临时文件可能因 Render 重启/OOM 被清理。请确认 R2 已成功上传，或重新生成该音频/视频。')


@app.get('/files/uploads/{name}')
def get_upload_file(name: str, settings: Settings = Depends(get_settings)):
    safe_name = Path(name).name
    path = (settings.uploads_dir / safe_name).resolve()
    if settings.uploads_dir.resolve() in path.parents and path.exists() and path.is_file():
        media_type = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
        return FileResponse(path, media_type=media_type, filename=path.name)
    if settings.r2_public_base_url.strip():
        url = _find_r2_public_url_by_name(settings, _upload_r2_prefix_candidates(safe_name), safe_name) or _safe_public_r2_url(settings, _upload_r2_prefix_candidates(safe_name)[0], safe_name)
        if url:
            return RedirectResponse(url=url, status_code=302)
    raise HTTPException(status_code=404, detail='上传素材文件不存在：本地临时文件可能因 Render 重启/OOM 被清理。请确认 R2 已成功上传，或重新上传素材。')


# 可选单体部署支持：只有当前端 dist 真的存在时，才托管静态文件。
# 前后端分离部署到 Render + Cloudflare Pages 时，Render 镜像通常没有 /app/static/assets。
# 如果不判断，Starlette 会因为目录不存在导致后端启动失败。
static_dir = Path(settings.static_dir)
static_assets_dir = static_dir / 'assets'
static_index = static_dir / 'index.html'

if static_assets_dir.exists() and static_assets_dir.is_dir():
    app.mount('/assets', StaticFiles(directory=static_assets_dir), name='static-assets')

if static_index.exists() and static_index.is_file():

    @app.get('/{full_path:path}')
    def serve_spa(full_path: str) -> FileResponse:
        target = static_dir / full_path
        if full_path and target.exists() and target.is_file():
            return FileResponse(target)
        return FileResponse(static_index)

else:

    @app.get('/')
    def api_root() -> dict:
        return {
            'ok': True,
            'service': 'AI-VIDEO API',
            'message': 'Backend is running. Frontend should be deployed separately on Cloudflare Pages.',
            'health': '/api/health',
            'docs': '/docs',
        }


# ===== ONE CLICK FINAL DELIVERY HOTFIX =====
_one_click_final_jobs = {}

@app.post('/api/one-click/final-delivery/start')
async def api_one_click_final_delivery_start(payload: dict | None = None, background_tasks: BackgroundTasks = None) -> dict:
    import uuid
    import subprocess
    import sys
    import json
    from pathlib import Path
    from datetime import datetime, timezone

    payload = payload or {}
    job_id = uuid.uuid4().hex
    _one_click_final_jobs[job_id] = {
        'job_id': job_id,
        'status': 'queued',
        'created_at': datetime.now(timezone.utc).isoformat(),
        'message': '任务已进入队列',
        'result': None,
        'error': '',
        'log_tail': '',
    }

    def _run():
        script = Path('/opt/ai-video/backend/one_click_final_delivery.py')
        text = str(payload.get('text') or '').strip()
        title = str(payload.get('title') or 'AI-VIDEO 正式交付视频').strip()
        avatar = str(payload.get('avatar_file_name') or 'avatar_template.mp4').strip()

        _one_click_final_jobs[job_id].update({
            'status': 'running',
            'message': '正在生成 TTS、数字人、9:16 视频和封面',
        })

        cmd = [sys.executable, str(script), '--title', title, '--avatar', avatar]
        if text:
            cmd += ['--text', text]

        try:
            proc = subprocess.run(
                cmd,
                cwd='/opt/ai-video/backend',
                text=True,
                capture_output=True,
                timeout=1200,
            )
            raw = (proc.stdout or '') + '\n' + (proc.stderr or '')
            result = None
            for line in reversed(raw.splitlines()):
                if line.startswith('FINAL_RESULT::'):
                    result = json.loads(line.replace('FINAL_RESULT::', '', 1))
                    break

            if proc.returncode == 0 and result and result.get('ok'):
                _one_click_final_jobs[job_id].update({
                    'status': 'done',
                    'message': '正式交付视频已生成',
                    'result': result,
                    'error': '',
                    'log_tail': raw[-6000:],
                })
            else:
                _one_click_final_jobs[job_id].update({
                    'status': 'failed',
                    'message': '生成失败',
                    'result': result,
                    'error': (result or {}).get('error') or raw[-1000:],
                    'log_tail': raw[-6000:],
                })
        except Exception as exc:
            _one_click_final_jobs[job_id].update({
                'status': 'failed',
                'message': '生成异常',
                'error': str(exc),
            })

    background_tasks.add_task(_run)
    return _one_click_final_jobs[job_id]

@app.get('/api/one-click/final-delivery/job/{job_id}')
def api_one_click_final_delivery_job(job_id: str) -> dict:
    item = _one_click_final_jobs.get(job_id)
    if not item:
        raise HTTPException(status_code=404, detail='任务不存在')
    return item

@app.get('/one-click-final')
def api_one_click_final_delivery_page():
    from fastapi.responses import HTMLResponse
    return HTMLResponse("""
<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>AI-VIDEO 一键正式出片</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif;background:#0f172a;color:#e5e7eb;margin:0;padding:32px}
.wrap{max-width:980px;margin:0 auto}
.card{background:#111827;border:1px solid #334155;border-radius:18px;padding:24px;box-shadow:0 12px 32px rgba(0,0,0,.28)}
h1{margin-top:0;font-size:28px}
label{display:block;margin:14px 0 8px;color:#cbd5e1}
input,textarea{width:100%;box-sizing:border-box;border-radius:12px;border:1px solid #475569;background:#020617;color:#e5e7eb;padding:14px;font-size:15px}
textarea{min-height:160px}
button{margin-top:18px;background:#22c55e;color:#052e16;border:0;border-radius:12px;padding:14px 22px;font-weight:800;font-size:16px;cursor:pointer}
button:disabled{opacity:.6;cursor:not-allowed}
pre{white-space:pre-wrap;background:#020617;border-radius:12px;padding:16px;border:1px solid #334155;max-height:360px;overflow:auto}
a{color:#93c5fd;word-break:break-all}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:16px}
video,img{width:100%;border-radius:12px;border:1px solid #334155;background:#020617}
.badge{display:inline-block;background:#1e293b;border:1px solid #475569;border-radius:999px;padding:6px 10px;color:#cbd5e1}
</style>
</head>
<body>
<div class="wrap">
  <div class="card">
    <h1>AI-VIDEO 一键正式出片</h1>
    <p><span class="badge">脚本 → TTS → 数字人 → 9:16包装 → 封面 → R2链接</span></p>

    <label>标题</label>
    <input id="title" value="马来西亚房产避坑正式样片" />

    <label>口播文案</label>
    <textarea id="text">来马来西亚买房，最怕的不是价格高，而是区域选错。同样是吉隆坡，有的地方租客稳定、转手容易；有的地方看起来便宜，后期却很难出租。如果你是为了孩子教育、第二家园、资产配置，第一步不是看样板间，而是先看区域、交通、学校和真实租售数据。真正稳的房子，不是销售说出来的，是市场长期验证出来的。</textarea>

    <button id="btn" onclick="start()">一键生成正式交付版</button>

    <h3>状态</h3>
    <pre id="status">等待开始</pre>

    <div id="result"></div>
  </div>
</div>

<script>
let timer=null;
async function start(){
  const btn=document.getElementById('btn');
  btn.disabled=true;
  document.getElementById('result').innerHTML='';
  document.getElementById('status').textContent='正在提交任务...';

  const res=await fetch('/api/one-click/final-delivery/start',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({
      title:document.getElementById('title').value,
      text:document.getElementById('text').value,
      avatar_file_name:'avatar_template.mp4'
    })
  });
  const job=await res.json();
  document.getElementById('status').textContent=JSON.stringify(job,null,2);
  poll(job.job_id);
}
async function poll(jobId){
  clearInterval(timer);
  timer=setInterval(async()=>{
    const res=await fetch('/api/one-click/final-delivery/job/'+jobId);
    const job=await res.json();
    document.getElementById('status').textContent=JSON.stringify(job,null,2);
    if(job.status==='done'){
      clearInterval(timer);
      document.getElementById('btn').disabled=false;
      const r=job.result || {};
      document.getElementById('result').innerHTML =
        '<h3>生成完成</h3>' +
        '<p>视频：<a target="_blank" href="'+r.video_url+'">'+r.video_url+'</a></p>' +
        '<p>封面：<a target="_blank" href="'+r.cover_url+'">'+r.cover_url+'</a></p>' +
        '<div class="grid"><div><video controls src="'+r.video_url+'"></video></div><div><img src="'+r.cover_url+'"/></div></div>';
    }
    if(job.status==='failed'){
      clearInterval(timer);
      document.getElementById('btn').disabled=false;
    }
  },3000);
}
</script>
</body>
</html>
    """)


# ===== ONE CLICK FINAL DELIVERY PAGE API ALIAS =====
@app.get('/api/one-click/final-delivery/page')
def api_one_click_final_delivery_page_api_alias():
    return api_one_click_final_delivery_page()

# ===== OPENCLAW PUBLIC API PROXY HOTFIX =====
# Public /api/openclaw/* -> local OpenClaw fallback worker on 127.0.0.1:8093
import urllib.request as _openclaw_urlreq
import urllib.error as _openclaw_urlerr
from fastapi import Request as _OpenClawRequest
from fastapi.responses import Response as _OpenClawResponse

def _openclaw_proxy_response(method: str, path: str, body: bytes | None = None, query: str = ""):
    path = (path or "health").lstrip("/")
    url = f"http://127.0.0.1:8093/api/openclaw/{path}"
    if query:
        url += "?" + query

    headers = {"Content-Type": "application/json"}
    req = _openclaw_urlreq.Request(
        url,
        data=body if body else None,
        headers=headers,
        method=method.upper(),
    )

    try:
        with _openclaw_urlreq.urlopen(req, timeout=120) as r:
            raw = r.read()
            content_type = r.headers.get("Content-Type") or "application/json; charset=utf-8"
            return _OpenClawResponse(
                content=raw,
                status_code=r.status,
                media_type=content_type.split(";")[0],
            )
    except _openclaw_urlerr.HTTPError as e:
        raw = e.read()
        content_type = e.headers.get("Content-Type") or "application/json; charset=utf-8"
        return _OpenClawResponse(
            content=raw,
            status_code=e.code,
            media_type=content_type.split(";")[0],
        )
    except Exception as e:
        raw = ('{"ok": false, "error": "openclaw proxy failed", "detail": ' + repr(str(e)) + '}').encode("utf-8")
        return _OpenClawResponse(
            content=raw,
            status_code=502,
            media_type="application/json",
        )

@app.get("/api/openclaw")
def api_openclaw_root_proxy():
    return _openclaw_proxy_response("GET", "health")

@app.get("/api/openclaw/")
def api_openclaw_root_slash_proxy():
    return _openclaw_proxy_response("GET", "health")

@app.get("/api/openclaw/health")
def api_openclaw_health_proxy():
    return _openclaw_proxy_response("GET", "health")

@app.api_route("/api/openclaw/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def api_openclaw_proxy(path: str, request: _OpenClawRequest):
    body = await request.body()
    return _openclaw_proxy_response(
        request.method,
        path,
        body if body else None,
        request.url.query,
    )
# ===== /OPENCLAW PUBLIC API PROXY HOTFIX =====


# ===== OPENCLAW DASHBOARD HOTFIX =====
import json as _oc_dash_json
import csv as _oc_dash_csv
import io as _oc_dash_io
import urllib.request as _oc_dash_urlreq
from fastapi.responses import HTMLResponse as _OpenClawHTMLResponse
from fastapi.responses import Response as _OpenClawCSVResponse

def _oc_dash_get_json(path: str):
    url = "http://127.0.0.1:8093" + path
    try:
        with _oc_dash_urlreq.urlopen(url, timeout=20) as r:
            return _oc_dash_json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/openclaw-dashboard", response_class=_OpenClawHTMLResponse)
def openclaw_dashboard_page():
    html = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>AI-VIDEO OpenClaw 采集面板</title>
  <style>
    body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,"Microsoft YaHei",sans-serif;background:#f6f7fb;margin:0;color:#111827;}
    header{background:#111827;color:white;padding:22px 28px;}
    h1{margin:0;font-size:24px;}
    .sub{opacity:.78;margin-top:6px;font-size:14px;}
    main{padding:22px;max-width:1180px;margin:0 auto;}
    .grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:18px;}
    .card{background:white;border-radius:14px;padding:16px;box-shadow:0 8px 22px rgba(15,23,42,.06);}
    .num{font-size:30px;font-weight:750;margin-top:8px;}
    .muted{color:#6b7280;font-size:13px;}
    button,a.btn{border:0;background:#111827;color:white;border-radius:10px;padding:10px 14px;cursor:pointer;text-decoration:none;display:inline-block;margin-right:8px;}
    button.secondary{background:#374151;}
    table{width:100%;border-collapse:collapse;background:white;border-radius:14px;overflow:hidden;box-shadow:0 8px 22px rgba(15,23,42,.06);}
    th,td{padding:11px 12px;border-bottom:1px solid #e5e7eb;text-align:left;font-size:13px;vertical-align:top;}
    th{background:#f3f4f6;color:#374151;}
    tr:hover{background:#fafafa;}
    .section{margin-top:22px;}
    .pill{display:inline-block;padding:3px 8px;border-radius:999px;background:#eef2ff;color:#3730a3;font-size:12px;}
    .score{font-weight:700;color:#047857;}
    code{background:#f3f4f6;padding:2px 5px;border-radius:5px;}
    @media(max-width:800px){.grid{grid-template-columns:1fr;} main{padding:14px;} table{font-size:12px;}}
  </style>
</head>
<body>
<header>
  <h1>AI-VIDEO OpenClaw 采集面板</h1>
  <div class="sub">只做采集与候选池沉淀，不自动出片，不消耗数字人额度。</div>
</header>
<main>
  <div class="grid">
    <div class="card"><div class="muted">OpenClaw 状态</div><div class="num" id="status">...</div></div>
    <div class="card"><div class="muted">账号候选</div><div class="num" id="accountCount">0</div></div>
    <div class="card"><div class="muted">视频候选</div><div class="num" id="videoCount">0</div></div>
  </div>

  <div class="card">
    <button onclick="loadAll()">刷新</button>
    <button class="secondary" onclick="triggerDryRun()">手动采集一次 dry-run</button>
    <a class="btn" href="/api/openclaw/export.csv" target="_blank">导出 CSV</a>
    <span class="muted">建议每天看这里：账号池、视频池、分数、来源。</span>
  </div>

  <div class="section">
    <h2>账号候选</h2>
    <table>
      <thead><tr><th>账号</th><th>分数</th><th>来源</th><th>链接</th><th>采集时间</th></tr></thead>
      <tbody id="accountsBody"></tbody>
    </table>
  </div>

  <div class="section">
    <h2>视频候选</h2>
    <table>
      <thead><tr><th>视频</th><th>账号</th><th>分数</th><th>来源</th><th>链接</th><th>采集时间</th></tr></thead>
      <tbody id="videosBody"></tbody>
    </table>
  </div>
</main>

<script>
async function j(url, opts){ const r = await fetch(url, opts || {}); return await r.json(); }

function esc(s){ return String(s || "").replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m])); }

async function loadAll(){
  const h = await j('/api/openclaw/health');
  const a = await j('/api/openclaw/accounts');
  const v = await j('/api/openclaw/videos');

  document.getElementById('status').textContent = h.ok ? 'running' : 'error';
  document.getElementById('accountCount').textContent = (a.accounts || []).length;
  document.getElementById('videoCount').textContent = (v.videos || []).length;

  document.getElementById('accountsBody').innerHTML = (a.accounts || []).map(x => `
    <tr>
      <td>${esc(x.account_name || '未命名账号')}</td>
      <td class="score">${esc(x.score || '')}</td>
      <td><span class="pill">${esc(x.source || x.keyword || '')}</span></td>
      <td><a href="${esc(x.account_url)}" target="_blank">打开</a><br><code>${esc(x.account_url)}</code></td>
      <td>${esc(x.collected_at || '')}</td>
    </tr>
  `).join('');

  document.getElementById('videosBody').innerHTML = (v.videos || []).map(x => `
    <tr>
      <td>${esc(x.video_title || '未命名视频')}</td>
      <td>${esc(x.account_name || '')}</td>
      <td class="score">${esc(x.score || '')}</td>
      <td><span class="pill">${esc(x.source || x.keyword || '')}</span></td>
      <td><a href="${esc(x.video_url)}" target="_blank">打开</a><br><code>${esc(x.video_url)}</code></td>
      <td>${esc(x.collected_at || '')}</td>
    </tr>
  `).join('');
}

async function triggerDryRun(){
  const body = {
    dry_run: true,
    force_openclaw: true,
    title: 'OpenClaw 面板手动采集',
    keywords: ['马来西亚房产','吉隆坡房产','MM2H','马来西亚买房','马来西亚第二家园','海外置业 马来西亚']
  };
  const r = await j('/api/openclaw/fallback/run', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify(body)
  });
  alert('已提交：' + JSON.stringify(r, null, 2));
  setTimeout(loadAll, 90000);
}

loadAll();
</script>
</body>
</html>
"""
    return html

@app.get("/api/openclaw/export.csv")
def openclaw_export_csv():
    accounts = (_oc_dash_get_json("/api/openclaw/accounts").get("accounts") or [])
    videos = (_oc_dash_get_json("/api/openclaw/videos").get("videos") or [])

    out = _oc_dash_io.StringIO()
    w = _oc_dash_csv.writer(out)
    w.writerow(["type", "name_or_title", "account_name", "score", "source", "url", "account_url", "collected_at"])

    for a in accounts:
        w.writerow([
            "account",
            a.get("account_name", ""),
            a.get("account_name", ""),
            a.get("score", ""),
            a.get("source", "") or a.get("keyword", ""),
            a.get("account_url", ""),
            a.get("account_url", ""),
            a.get("collected_at", ""),
        ])

    for v in videos:
        w.writerow([
            "video",
            v.get("video_title", ""),
            v.get("account_name", ""),
            v.get("score", ""),
            v.get("source", "") or v.get("keyword", ""),
            v.get("video_url", ""),
            v.get("account_url", ""),
            v.get("collected_at", ""),
        ])

    return _OpenClawCSVResponse(
        content=out.getvalue().encode("utf-8-sig"),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=openclaw_candidates.csv"}
    )
# ===== /OPENCLAW DASHBOARD HOTFIX =====


# ===== OPENCLAW DISCOVERY API HOTFIX =====
import subprocess as _oc_disc_subprocess
import threading as _oc_disc_threading
import uuid as _oc_disc_uuid
import time as _oc_disc_time
import json as _oc_disc_json

_openclaw_discovery_jobs = {}

def _run_openclaw_discovery_job(job_id: str):
    job = _openclaw_discovery_jobs[job_id]
    job["status"] = "running"
    job["stage"] = "discovering"
    job["updated_at"] = _oc_disc_time.time()

    script = "/opt/openclaw-worker/openclaw_account_discovery.py"
    py = "/opt/openclaw-worker/.venv/bin/python"

    try:
        cp = _oc_disc_subprocess.run(
            [py, script],
            text=True,
            capture_output=True,
            timeout=1200,
        )

        stdout = cp.stdout or ""
        stderr = cp.stderr or ""

        result = None
        for line in stdout.splitlines():
            if line.startswith("DISCOVERY_RESULT::"):
                try:
                    result = _oc_disc_json.loads(line.split("DISCOVERY_RESULT::", 1)[1])
                except Exception:
                    result = None

        job["status"] = "done" if cp.returncode == 0 else "failed"
        job["stage"] = "finished" if cp.returncode == 0 else "failed"
        job["returncode"] = cp.returncode
        job["result"] = result or {}
        job["stdout_tail"] = stdout[-5000:]
        job["stderr_tail"] = stderr[-5000:]
        job["updated_at"] = _oc_disc_time.time()

    except Exception as e:
        job["status"] = "failed"
        job["stage"] = "exception"
        job["error"] = str(e)
        job["updated_at"] = _oc_disc_time.time()

@app.post("/api/openclaw/discovery/start")
def api_openclaw_discovery_start():
    job_id = "openclaw_discovery_" + _oc_disc_uuid.uuid4().hex[:16]
    now_ts = _oc_disc_time.time()

    _openclaw_discovery_jobs[job_id] = {
        "ok": True,
        "job_id": job_id,
        "status": "queued",
        "stage": "queued",
        "message": "OpenClaw 自动账号发现任务已入队",
        "created_at": now_ts,
        "updated_at": now_ts,
        "result": None,
        "error": "",
    }

    t = _oc_disc_threading.Thread(
        target=_run_openclaw_discovery_job,
        args=(job_id,),
        daemon=True,
    )
    t.start()

    return _openclaw_discovery_jobs[job_id]

@app.get("/api/openclaw/discovery/job/{job_id}")
def api_openclaw_discovery_job(job_id: str):
    job = _openclaw_discovery_jobs.get(job_id)
    if not job:
        return {
            "ok": False,
            "job_id": job_id,
            "status": "not_found",
            "message": "任务不存在，可能后端重启后内存记录已清空",
        }
    return job
# ===== /OPENCLAW DISCOVERY API HOTFIX =====


# ===== FAL VIDEO API HOTFIX =====
import threading as _fal_threading
import time as _fal_time
from typing import Optional as _FalOptional, List as _FalList
from pydantic import BaseModel as _FalBaseModel, Field as _FalField

from app.services.fal_video_provider import (
    fal_ready as _fal_ready,
    generate_fal_video as _generate_fal_video,
    safe_error as _fal_safe_error,
    make_job_id as _fal_make_job_id,
)

_fal_video_jobs = {}


class _FalShotRequest(_FalBaseModel):
    prompt: str = _FalField(..., min_length=3)
    mode: str = "quick"
    image_url: _FalOptional[str] = None
    resolution: str = "720p"
    num_frames: int = 81
    frames_per_second: int = 16
    negative_prompt: str = ""
    video_quality: str = "high"
    video_write_mode: str = "balanced"


class _FalStoryboardShot(_FalBaseModel):
    shot_id: _FalOptional[str] = None
    prompt: str
    image_url: _FalOptional[str] = None
    duration_hint: _FalOptional[float] = None


class _FalStoryboardRequest(_FalBaseModel):
    title: str = "全 AI 视频"
    mode: str = "quick"
    shots: _FalList[_FalStoryboardShot]
    resolution: str = "720p"
    num_frames: int = 81
    frames_per_second: int = 16
    negative_prompt: str = "low quality, blurry, watermark, text logo, distorted hands, distorted face"
    video_quality: str = "high"
    video_write_mode: str = "balanced"
    max_shots: int = 8


def _run_fal_shot_job(job_id: str, req: _FalShotRequest):
    job = _fal_video_jobs[job_id]
    job["status"] = "running"
    job["updated_at"] = _fal_time.time()

    try:
        result = _generate_fal_video(
            prompt=req.prompt,
            mode=req.mode,
            image_url=req.image_url,
            resolution=req.resolution,
            num_frames=req.num_frames,
            frames_per_second=req.frames_per_second,
            negative_prompt=req.negative_prompt,
            video_quality=req.video_quality,
            video_write_mode=req.video_write_mode,
        )
        job["status"] = "done"
        job["result"] = result
        job["video_url"] = result.get("video_url")
    except Exception as e:
        job["status"] = "failed"
        job["result"] = _fal_safe_error(e)

    job["updated_at"] = _fal_time.time()


def _run_fal_storyboard_job(job_id: str, req: _FalStoryboardRequest):
    job = _fal_video_jobs[job_id]
    job["status"] = "running"
    job["stage"] = "generating_shots"
    job["updated_at"] = _fal_time.time()

    outputs = []
    shots = req.shots[: max(1, min(req.max_shots, 12))]

    try:
        for idx, shot in enumerate(shots, start=1):
            job["current_shot"] = idx
            job["total_shots"] = len(shots)
            job["message"] = f"正在生成第 {idx}/{len(shots)} 个 AI 视频镜头"
            job["updated_at"] = _fal_time.time()

            result = _generate_fal_video(
                prompt=shot.prompt,
                mode=req.mode,
                image_url=shot.image_url,
                resolution=req.resolution,
                num_frames=req.num_frames,
                frames_per_second=req.frames_per_second,
                negative_prompt=req.negative_prompt,
                video_quality=req.video_quality,
                video_write_mode=req.video_write_mode,
            )

            outputs.append({
                "shot_id": shot.shot_id or f"shot_{idx:02d}",
                "prompt": shot.prompt,
                "image_url": shot.image_url,
                "video_url": result.get("video_url"),
                "result": result,
            })

        job["status"] = "done"
        job["stage"] = "shots_done"
        job["result"] = {
            "ok": True,
            "title": req.title,
            "provider": "fal",
            "mode": req.mode,
            "shots": outputs,
            "next_step": "compose_with_volc_tts_and_ffmpeg",
        }

    except Exception as e:
        job["status"] = "failed"
        job["stage"] = "failed"
        job["result"] = _fal_safe_error(e)
        job["partial_outputs"] = outputs

    job["updated_at"] = _fal_time.time()


@app.get("/api/video/fal/health")
def api_video_fal_health():
    return {
        "ok": True,
        "provider": "fal",
        "configured": _fal_ready(),
        "message": "FAL_KEY 已配置" if _fal_ready() else "FAL_KEY 未配置",
    }


@app.post("/api/video/fal/shot/start")
def api_video_fal_shot_start(req: _FalShotRequest):
    job_id = _fal_make_job_id("fal_shot")
    now = _fal_time.time()

    _fal_video_jobs[job_id] = {
        "ok": True,
        "job_id": job_id,
        "type": "fal_shot",
        "status": "queued",
        "created_at": now,
        "updated_at": now,
        "request": req.model_dump(),
    }

    t = _fal_threading.Thread(target=_run_fal_shot_job, args=(job_id, req), daemon=True)
    t.start()

    return _fal_video_jobs[job_id]


@app.post("/api/video/fal/storyboard/start")
def api_video_fal_storyboard_start(req: _FalStoryboardRequest):
    job_id = _fal_make_job_id("fal_storyboard")
    now = _fal_time.time()

    _fal_video_jobs[job_id] = {
        "ok": True,
        "job_id": job_id,
        "type": "fal_storyboard",
        "status": "queued",
        "stage": "queued",
        "created_at": now,
        "updated_at": now,
        "request": req.model_dump(),
    }

    t = _fal_threading.Thread(target=_run_fal_storyboard_job, args=(job_id, req), daemon=True)
    t.start()

    return _fal_video_jobs[job_id]


@app.get("/api/video/fal/job/{job_id}")
def api_video_fal_job(job_id: str):
    job = _fal_video_jobs.get(job_id)
    if not job:
        return {
            "ok": False,
            "job_id": job_id,
            "status": "not_found",
            "message": "任务不存在，后端重启后内存任务会清空",
        }
    return job
# ===== /FAL VIDEO API HOTFIX =====


# ===== VIDEO COMPOSE API HOTFIX =====
import threading as _compose_threading
import time as _compose_time
from typing import List as _ComposeList, Optional as _ComposeOptional
from pydantic import BaseModel as _ComposeBaseModel, Field as _ComposeField

from app.services.video_compose_provider import (
    compose_video_urls as _compose_video_urls,
    make_compose_job_id as _make_compose_job_id,
    r2_configured as _r2_configured,
)

_compose_jobs = {}


class _ComposeUrlsRequest(_ComposeBaseModel):
    title: str = "全 AI 视频"
    video_urls: _ComposeList[str] = _ComposeField(..., min_length=1)
    audio_url: _ComposeOptional[str] = None
    width: int = 1080
    height: int = 1920
    fps: int = 30
    upload: bool = True
    folder: str = "videos/full-ai"


def _run_compose_job(job_id: str, req: _ComposeUrlsRequest):
    job = _compose_jobs[job_id]
    job["status"] = "running"
    job["stage"] = "composing"
    job["updated_at"] = _compose_time.time()

    try:
        result = _compose_video_urls(
            video_urls=req.video_urls,
            title=req.title,
            audio_url=req.audio_url,
            width=req.width,
            height=req.height,
            fps=req.fps,
            upload=req.upload,
            folder=req.folder,
        )
        job["status"] = "done" if result.get("ok") else "failed"
        job["stage"] = "finished" if result.get("ok") else "failed"
        job["result"] = result
        job["video_url"] = ((result.get("r2") or {}).get("public_url") or "")
        job["local_path"] = result.get("local_path")
    except Exception as e:
        job["status"] = "failed"
        job["stage"] = "exception"
        job["result"] = {"ok": False, "error": str(e)}

    job["updated_at"] = _compose_time.time()


def _start_compose_job(req: _ComposeUrlsRequest):
    job_id = _make_compose_job_id("compose_video")
    now = _compose_time.time()

    _compose_jobs[job_id] = {
        "ok": True,
        "job_id": job_id,
        "type": "compose_video",
        "status": "queued",
        "stage": "queued",
        "created_at": now,
        "updated_at": now,
        "request": req.model_dump(),
    }

    t = _compose_threading.Thread(target=_run_compose_job, args=(job_id, req), daemon=True)
    t.start()
    return _compose_jobs[job_id]


@app.get("/api/video/compose/health")
def api_video_compose_health():
    return {
        "ok": True,
        "ffmpeg": True,
        "r2_configured": _r2_configured(),
        "message": "视频拼接服务可用",
    }


@app.post("/api/video/compose/urls/start")
def api_video_compose_urls_start(req: _ComposeUrlsRequest):
    return _start_compose_job(req)


@app.post("/api/video/compose/fal-storyboard/start/{fal_job_id}")
def api_video_compose_fal_storyboard_start(fal_job_id: str):
    fal_jobs = globals().get("_fal_video_jobs", {})
    fal_job = fal_jobs.get(fal_job_id)

    if not fal_job:
        return {
            "ok": False,
            "status": "not_found",
            "message": "fal 分镜任务不存在，可能后端重启导致内存任务清空",
            "fal_job_id": fal_job_id,
        }

    if fal_job.get("status") != "done":
        return {
            "ok": False,
            "status": "not_ready",
            "message": "fal 分镜任务还没完成",
            "fal_job_id": fal_job_id,
            "fal_status": fal_job.get("status"),
        }

    shots = ((fal_job.get("result") or {}).get("shots") or [])
    video_urls = [s.get("video_url") for s in shots if s.get("video_url")]

    if not video_urls:
        return {
            "ok": False,
            "status": "empty",
            "message": "没有可拼接的视频 URL",
            "fal_job_id": fal_job_id,
        }

    req = _ComposeUrlsRequest(
        title=((fal_job.get("result") or {}).get("title") or "fal 全 AI 视频"),
        video_urls=video_urls,
        width=1080,
        height=1920,
        fps=30,
        upload=True,
        folder="videos/full-ai",
    )

    return _start_compose_job(req)


@app.get("/api/video/compose/job/{job_id}")
def api_video_compose_job(job_id: str):
    job = _compose_jobs.get(job_id)
    if not job:
        return {
            "ok": False,
            "job_id": job_id,
            "status": "not_found",
            "message": "任务不存在，后端重启后内存任务会清空",
        }
    return job
# ===== /VIDEO COMPOSE API HOTFIX =====


# ===== FULL AI VIDEO PIPELINE API HOTFIX =====
import threading as _full_ai_threading
import time as _full_ai_time
import uuid as _full_ai_uuid
import requests as _full_ai_requests
from typing import List as _FullAIList, Optional as _FullAIOptional
from pydantic import BaseModel as _FullAIBaseModel, Field as _FullAIField

_full_ai_jobs = {}


class _FullAIShot(_FullAIBaseModel):
    shot_id: _FullAIOptional[str] = None
    prompt: str
    image_url: _FullAIOptional[str] = None


class _FullAIVideoRequest(_FullAIBaseModel):
    title: str = "全 AI 视频"
    script_text: str = _FullAIField(..., min_length=3)
    shots: _FullAIList[_FullAIShot] = _FullAIField(..., min_length=1)
    mode: str = "quick"
    resolution: str = "720p"
    num_frames: int = 81
    frames_per_second: int = 16
    max_shots: int = 6
    voice: str = "default"
    overall_rate: str = "0%"
    width: int = 1080
    height: int = 1920
    fps: int = 30
    folder: str = "videos/full-ai-one-click"


def _full_ai_job_id() -> str:
    return "full_ai_" + _full_ai_uuid.uuid4().hex[:18]


def _full_ai_base_url() -> str:
    return "http://127.0.0.1:8000"


def _full_ai_get_json(path: str, timeout: int = 60):
    r = _full_ai_requests.get(_full_ai_base_url() + path, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _full_ai_post_json(path: str, payload: dict, timeout: int = 300):
    r = _full_ai_requests.post(_full_ai_base_url() + path, json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _poll_full_ai_job(job_id: str, path_template: str, timeout_seconds: int = 1800, interval: int = 5):
    deadline = _full_ai_time.time() + timeout_seconds
    last = None

    while _full_ai_time.time() < deadline:
        last = _full_ai_get_json(path_template.format(job_id=job_id), timeout=60)
        status = last.get("status")

        if status in {"done", "failed"}:
            return last

        _full_ai_time.sleep(interval)

    return {
        "ok": False,
        "status": "timeout",
        "job_id": job_id,
        "last": last,
    }


def _run_full_ai_pipeline(job_id: str, req: _FullAIVideoRequest):
    job = _full_ai_jobs[job_id]
    job["status"] = "running"
    job["stage"] = "fal_storyboard"
    job["message"] = "正在生成 fal.ai 分镜视频"
    job["updated_at"] = _full_ai_time.time()

    try:
        # FULL_AI_SANITIZE_SHOTS_BEFORE_FAL
        try:
            _topic_for_visual = str(locals().get("title") or locals().get("topic") or "")
            _shots_for_visual = locals().get("shots") or []
            for _i, _shot in enumerate(_shots_for_visual, start=1):
                if isinstance(_shot, dict):
                    _shot["prompt"] = _ai_video_visual_prompt(_shot.get("prompt", ""), _topic_for_visual, _i)
                    _shot["negative_prompt"] = AI_VIDEO_NEGATIVE_PROMPT
        except Exception as _quality_exc:
            print("FULL_AI_SANITIZE_SHOTS_BEFORE_FAL_FAILED", _quality_exc)
        storyboard_payload = {
            "title": req.title,
            "mode": req.mode,
            "resolution": req.resolution,
            "num_frames": req.num_frames,
            "frames_per_second": req.frames_per_second,
            "max_shots": req.max_shots,
            "shots": [x.model_dump() for x in req.shots[: max(1, min(req.max_shots, 12))]],
        }

        storyboard_start = _full_ai_post_json("/api/video/fal/storyboard/start", storyboard_payload, timeout=60)
        fal_job_id = storyboard_start.get("job_id")
        job["fal_job_id"] = fal_job_id
        job["fal_start"] = storyboard_start
        job["updated_at"] = _full_ai_time.time()

        if not fal_job_id:
            raise RuntimeError("fal storyboard start failed: missing job_id")

        fal_result = _poll_full_ai_job(
            fal_job_id,
            "/api/video/fal/job/{job_id}",
            timeout_seconds=1800,
            interval=5,
        )

        job["fal_result"] = fal_result
        job["updated_at"] = _full_ai_time.time()

        if fal_result.get("status") != "done":
            raise RuntimeError("fal storyboard failed or timeout: " + str(fal_result)[:1000])

        shots = ((fal_result.get("result") or {}).get("shots") or [])
        video_urls = [x.get("video_url") for x in shots if x.get("video_url")]

        if not video_urls:
            raise RuntimeError("fal storyboard done but no video_urls")

        job["stage"] = "tts"
        job["message"] = "正在生成字节 TTS 口播"
        job["video_urls"] = video_urls
        job["updated_at"] = _full_ai_time.time()

        tts_payload = {
            "text": req.script_text,
            "voice": req.voice,
            "overall_rate": req.overall_rate,
        }
        tts_result = _full_ai_post_json("/api/tts-segments", tts_payload, timeout=300)
        audio_url = tts_result.get("file_url") or tts_result.get("audio_url") or tts_result.get("url") or ""

        job["tts_result"] = tts_result
        job["audio_url"] = audio_url
        job["updated_at"] = _full_ai_time.time()

        if not audio_url:
            raise RuntimeError("tts generated but no audio_url/file_url")

        job["stage"] = "compose"
        job["message"] = "正在合成完整带口播视频"
        job["updated_at"] = _full_ai_time.time()

        compose_payload = {
            "title": req.title,
            "video_urls": video_urls,
            "audio_url": audio_url,
            "width": req.width,
            "height": req.height,
            "fps": req.fps,
            "upload": True,
            "folder": req.folder,
        }

        compose_start = _full_ai_post_json("/api/video/compose/urls/start", compose_payload, timeout=60)
        compose_job_id = compose_start.get("job_id")

        job["compose_job_id"] = compose_job_id
        job["compose_start"] = compose_start
        job["updated_at"] = _full_ai_time.time()

        if not compose_job_id:
            raise RuntimeError("compose start failed: missing job_id")

        compose_result = _poll_full_ai_job(
            compose_job_id,
            "/api/video/compose/job/{job_id}",
            timeout_seconds=900,
            interval=3,
        )

        job["compose_result"] = compose_result
        job["updated_at"] = _full_ai_time.time()

        if compose_result.get("status") != "done":
            raise RuntimeError("compose failed or timeout: " + str(compose_result)[:1000])

        final_url = compose_result.get("video_url") or ((compose_result.get("result") or {}).get("r2") or {}).get("public_url") or ""

        job["status"] = "done"
        job["stage"] = "finished"
        job["message"] = "全 AI 带口播视频生成完成"
        job["video_url"] = final_url
        job["result"] = {
            "ok": True,
            "title": req.title,
            "video_url": final_url,
            "audio_url": audio_url,
            "fal_job_id": fal_job_id,
            "compose_job_id": compose_job_id,
            "video_urls": video_urls,
            "tts": tts_result,
            "compose": compose_result,
        }

    except Exception as e:
        job["status"] = "failed"
        job["stage"] = "failed"
        job["message"] = "全 AI 视频生成失败"
        job["error"] = str(e)

    job["updated_at"] = _full_ai_time.time()


@app.post("/api/video/full-ai/start")
def api_video_full_ai_start(req: _FullAIVideoRequest):
    job_id = _full_ai_job_id()
    now = _full_ai_time.time()

    _full_ai_jobs[job_id] = {
        "ok": True,
        "job_id": job_id,
        "type": "full_ai_video",
        "status": "queued",
        "stage": "queued",
        "message": "任务已创建",
        "created_at": now,
        "updated_at": now,
        "request": req.model_dump(),
    }

    t = _full_ai_threading.Thread(target=_run_full_ai_pipeline, args=(job_id, req), daemon=True)
    t.start()

    return _full_ai_jobs[job_id]


@app.get("/api/video/full-ai/job/{job_id}")
def api_video_full_ai_job(job_id: str):
    job = _full_ai_jobs.get(job_id)
    if not job:
        return {
            "ok": False,
            "job_id": job_id,
            "status": "not_found",
            "message": "任务不存在，后端重启后内存任务会清空",
        }
    return job
# ===== /FULL AI VIDEO PIPELINE API HOTFIX =====


# ===== FULL AI COST GUARD MIDDLEWARE HOTFIX =====
import hashlib as _full_ai_guard_hashlib
import json as _full_ai_guard_json
import os as _full_ai_guard_os
import time as _full_ai_guard_time
from starlette.requests import Request as _FullAIGuardRequest
from starlette.responses import JSONResponse as _FullAIGuardJSONResponse

_full_ai_submit_guard = {}

_FULL_AI_DUPLICATE_WINDOW_SECONDS = int(_full_ai_guard_os.getenv("FULL_AI_DUPLICATE_WINDOW_SECONDS", "120"))
_FULL_AI_IP_COOLDOWN_SECONDS = int(_full_ai_guard_os.getenv("FULL_AI_IP_COOLDOWN_SECONDS", "45"))
_FULL_AI_MAX_SHOTS = int(_full_ai_guard_os.getenv("FULL_AI_MAX_SHOTS", "50"))


def _full_ai_guard_client_key(request: _FullAIGuardRequest) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip() or "unknown"
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _full_ai_guard_payload_hash(data) -> str:
    raw = _full_ai_guard_json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return _full_ai_guard_hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _full_ai_guard_cleanup(now: float) -> None:
    ttl = max(_FULL_AI_DUPLICATE_WINDOW_SECONDS, _FULL_AI_IP_COOLDOWN_SECONDS) * 4
    old_keys = []
    for k, v in list(_full_ai_submit_guard.items()):
        if now - float(v.get("time", 0)) > ttl:
            old_keys.append(k)
    for k in old_keys:
        _full_ai_submit_guard.pop(k, None)


@app.middleware("http")
async def _full_ai_cost_guard_middleware(request: _FullAIGuardRequest, call_next):
    if request.method.upper() != "POST" or request.url.path != "/api/video/full-ai/start":
        return await call_next(request)

    body = await request.body()

    try:
        data = _full_ai_guard_json.loads(body.decode("utf-8") or "{}")
    except Exception:
        return _FullAIGuardJSONResponse(
            {
                "ok": False,
                "status": "bad_request",
                "message": "请求体不是合法 JSON，已拦截，未触发视频生成。",
            },
            status_code=400,
        )

    now = _full_ai_guard_time.time()
    _full_ai_guard_cleanup(now)

    client_key = _full_ai_guard_client_key(request)
    payload_hash = _full_ai_guard_payload_hash(data)

    shots = data.get("shots") or []
    try:
        requested_max_shots = int(data.get("max_shots") or len(shots) or 1)
    except Exception:
        requested_max_shots = len(shots) or 1

    effective_shots = max(requested_max_shots, len(shots))

    if effective_shots > _FULL_AI_MAX_SHOTS:
        return _FullAIGuardJSONResponse(
            {
                "ok": False,
                "status": "blocked_by_cost_guard",
                "message": f"本次请求镜头数为 {effective_shots}，超过后端限制 {_FULL_AI_MAX_SHOTS}，已拦截，未触发 fal.ai。",
                "max_shots_allowed": _FULL_AI_MAX_SHOTS,
            },
            status_code=400,
        )

    ip_key = f"ip:{client_key}"
    duplicate_key = f"payload:{client_key}:{payload_hash}"

    last_ip = _full_ai_submit_guard.get(ip_key)
    if last_ip and now - float(last_ip.get("time", 0)) < _FULL_AI_IP_COOLDOWN_SECONDS:
        wait = int(_FULL_AI_IP_COOLDOWN_SECONDS - (now - float(last_ip.get("time", 0))))
        return _FullAIGuardJSONResponse(
            {
                "ok": False,
                "status": "cooldown",
                "message": f"后端冷却保护中，请 {max(wait, 1)} 秒后再提交，避免重复生成费用。",
                "retry_after_seconds": max(wait, 1),
            },
            status_code=429,
        )

    last_duplicate = _full_ai_submit_guard.get(duplicate_key)
    if last_duplicate and now - float(last_duplicate.get("time", 0)) < _FULL_AI_DUPLICATE_WINDOW_SECONDS:
        wait = int(_FULL_AI_DUPLICATE_WINDOW_SECONDS - (now - float(last_duplicate.get("time", 0))))
        return _FullAIGuardJSONResponse(
            {
                "ok": False,
                "status": "duplicate_blocked",
                "message": f"检测到 { _FULL_AI_DUPLICATE_WINDOW_SECONDS } 秒内提交过完全相同内容，已拦截，避免重复烧费用。",
                "retry_after_seconds": max(wait, 1),
            },
            status_code=409,
        )

    _full_ai_submit_guard[ip_key] = {"time": now}
    _full_ai_submit_guard[duplicate_key] = {"time": now}

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    guarded_request = _FullAIGuardRequest(request.scope, receive)
    response = await call_next(guarded_request)

    if response.status_code >= 400:
        _full_ai_submit_guard.pop(ip_key, None)
        _full_ai_submit_guard.pop(duplicate_key, None)

    return response
# ===== /FULL AI COST GUARD MIDDLEWARE HOTFIX =====


# ===== VIDEO JOB PERSISTENCE HOTFIX =====
import json as _job_persist_json
from starlette.responses import Response as _JobPersistResponse
from starlette.responses import JSONResponse as _JobPersistJSONResponse
from app.services.job_persistence_provider import (
    get_job as _job_persist_get_job,
    health as _job_persist_health,
    infer_job_type as _job_persist_infer_job_type,
    list_recent_jobs as _job_persist_list_recent_jobs,
    save_job_response as _job_persist_save_job_response,
)


def _job_persist_is_interested_path(path: str) -> bool:
    return (
        path == "/api/video/full-ai/start"
        or path.startswith("/api/video/full-ai/job/")
        or path.startswith("/api/video/fal/job/")
        or path.startswith("/api/video/compose/job/")
    )


def _job_persist_extract_job_id(path: str, data) -> str:
    if isinstance(data, dict):
        for key in ("job_id", "id"):
            value = data.get(key)
            if isinstance(value, str) and value:
                return value

    parts = [x for x in path.split("/") if x]
    return parts[-1] if parts else ""


def _job_persist_is_not_found(data, status_code: int) -> bool:
    if status_code == 404:
        return True
    if not isinstance(data, dict):
        return False

    status = str(data.get("status") or "").lower()
    message = str(data.get("message") or "").lower()
    error = str(data.get("error") or "").lower()

    return (
        status in {"not_found", "missing", "not found"}
        or "not_found" in message
        or "not found" in message
        or "not_found" in error
        or "not found" in error
    )


@app.middleware("http")
async def _video_job_persistence_middleware(request, call_next):
    path = request.url.path

    if not _job_persist_is_interested_path(path):
        return await call_next(request)

    response = await call_next(request)

    body = b""
    async for chunk in response.body_iterator:
        body += chunk

    headers = {
        k: v
        for k, v in response.headers.items()
        if k.lower() not in {"content-length", "content-encoding"}
    }

    data = None
    try:
        data = _job_persist_json.loads(body.decode("utf-8") or "{}")
    except Exception:
        data = None

    job_id = _job_persist_extract_job_id(path, data)
    job_type = _job_persist_infer_job_type(path, job_id)

    if request.method.upper() == "GET" and job_id and _job_persist_is_not_found(data, response.status_code):
        restored = _job_persist_get_job(job_id)
        if restored:
            return _JobPersistJSONResponse(restored)

    if isinstance(data, dict) and job_id and not _job_persist_is_not_found(data, response.status_code):
        try:
            _job_persist_save_job_response(
                job_id=job_id,
                job_type=job_type,
                response_data=data,
                source_path=path,
            )
        except Exception as exc:
            print(f"[job-persistence] save failed for {job_id}: {exc}")

    return _JobPersistResponse(
        content=body,
        status_code=response.status_code,
        headers=headers,
        media_type=response.media_type,
    )


@app.get("/api/video/jobs/persistence/health")
async def _video_job_persistence_health():
    return _job_persist_health()


@app.get("/api/video/jobs/recent")
async def _video_job_persistence_recent(limit: int = 20):
    return {
        "ok": True,
        "jobs": _job_persist_list_recent_jobs(limit),
    }
# ===== /VIDEO JOB PERSISTENCE HOTFIX =====


# ===== VIDEO SUBTITLE API HOTFIX =====
from typing import Any as _SubtitleAny, Optional as _SubtitleOptional
from pydantic import BaseModel as _SubtitleBaseModel
from app.services.subtitle_provider import (
    burn_subtitles as _subtitle_burn_subtitles,
    create_self_test_video as _subtitle_create_self_test_video,
    health as _subtitle_health,
    make_srt as _subtitle_make_srt,
)


class _SubtitleSrtRequest(_SubtitleBaseModel):
    text: str = ""
    segments: list[dict[str, _SubtitleAny]] | None = None
    duration: float = 12.0
    max_chars: int = 18
    prefix: str = "subtitle"


class _SubtitleBurnRequest(_SubtitleBaseModel):
    video_url: str = ""
    video_path: str = ""
    text: str = ""
    segments: list[dict[str, _SubtitleAny]] | None = None
    duration: _SubtitleOptional[float] = None
    max_chars: int = 18
    prefix: str = "subtitle_burn"


@app.get("/api/video/subtitle/health")
async def _video_subtitle_health():
    return _subtitle_health()


@app.post("/api/video/subtitle/srt")
async def _video_subtitle_srt(req: _SubtitleSrtRequest):
    return _subtitle_make_srt(
        text=req.text,
        segments=req.segments,
        duration=req.duration,
        max_chars=req.max_chars,
        prefix=req.prefix,
    )


@app.post("/api/video/subtitle/burn")
async def _video_subtitle_burn(req: _SubtitleBurnRequest):
    return _subtitle_burn_subtitles(
        video_url=req.video_url,
        video_path=req.video_path,
        text=req.text,
        segments=req.segments,
        duration=req.duration,
        max_chars=req.max_chars,
        prefix=req.prefix,
    )


@app.get("/api/video/subtitle/self-test")
async def _video_subtitle_self_test():
    video_path = _subtitle_create_self_test_video()
    return _subtitle_burn_subtitles(
        video_path=str(video_path),
        text="这是字幕烧录自测。不调用 fal.ai，也不会产生生成费用。",
        duration=5.0,
        max_chars=16,
        prefix="subtitle_self_test",
    )
# ===== /VIDEO SUBTITLE API HOTFIX =====


# ===== VIDEO SUBTITLE BURN UPLOAD API HOTFIX =====
from app.services.subtitle_provider import (
    burn_subtitles_and_upload as _subtitle_burn_subtitles_and_upload,
    create_self_test_burn_upload as _subtitle_create_self_test_burn_upload,
    upload_health as _subtitle_upload_health,
)


class _SubtitleBurnUploadRequest(_SubtitleBaseModel):
    video_url: str = ""
    video_path: str = ""
    text: str = ""
    segments: list[dict[str, _SubtitleAny]] | None = None
    duration: _SubtitleOptional[float] = None
    max_chars: int = 18
    prefix: str = "subtitle_burn_upload"
    object_key: str = ""


@app.get("/api/video/subtitle/upload-health")
async def _video_subtitle_upload_health():
    return _subtitle_upload_health()


@app.post("/api/video/subtitle/burn-upload")
async def _video_subtitle_burn_upload(req: _SubtitleBurnUploadRequest):
    return _subtitle_burn_subtitles_and_upload(
        video_url=req.video_url,
        video_path=req.video_path,
        text=req.text,
        segments=req.segments,
        duration=req.duration,
        max_chars=req.max_chars,
        prefix=req.prefix,
        object_key=req.object_key,
    )


@app.get("/api/video/subtitle/burn-upload-self-test")
async def _video_subtitle_burn_upload_self_test():
    return _subtitle_create_self_test_burn_upload()
# ===== /VIDEO SUBTITLE BURN UPLOAD API HOTFIX =====


# ===== FULL AI SUBTITLE BRIDGE HOTFIX =====
import time as _full_ai_subtitle_time
from typing import Any as _FullAISubtitleAny
from pydantic import BaseModel as _FullAISubtitleBaseModel
from starlette.responses import JSONResponse as _FullAISubtitleJSONResponse
from app.services.subtitle_provider import (
    burn_subtitles_and_upload as _full_ai_subtitle_burn_upload,
    upload_health as _full_ai_subtitle_upload_health,
)

try:
    from app.services.job_persistence_provider import (
        get_job as _full_ai_subtitle_get_persisted_job,
        save_job_response as _full_ai_subtitle_save_job_response,
    )
except Exception:
    _full_ai_subtitle_get_persisted_job = None
    _full_ai_subtitle_save_job_response = None


class _FullAISubtitleBridgeRequest(_FullAISubtitleBaseModel):
    video_url: str = ""
    text: str = ""
    segments: list[dict[str, _FullAISubtitleAny]] | None = None
    duration: float | None = None
    max_chars: int = 18
    prefix: str = "full_ai_subtitled"
    object_key: str = ""
    dry_run: bool = False


def _full_ai_subtitle_memory_job(job_id: str):
    try:
        jobs = globals().get("_full_ai_jobs")
        if isinstance(jobs, dict):
            return jobs.get(job_id)
    except Exception:
        pass
    return None


def _full_ai_subtitle_find_job(job_id: str):
    job = _full_ai_subtitle_memory_job(job_id)
    if job:
        return job

    if _full_ai_subtitle_get_persisted_job:
        try:
            return _full_ai_subtitle_get_persisted_job(job_id)
        except Exception:
            return None

    return None


def _full_ai_subtitle_extract_video_url(job) -> str:
    if not isinstance(job, dict):
        return ""

    result = job.get("result") if isinstance(job.get("result"), dict) else {}

    return (
        job.get("subtitled_video_url")
        or job.get("video_url")
        or job.get("final_video_url")
        or result.get("video_url")
        or result.get("final_video_url")
        or ""
    )


def _full_ai_subtitle_extract_text(job) -> str:
    if not isinstance(job, dict):
        return ""

    result = job.get("result") if isinstance(job.get("result"), dict) else {}
    request = job.get("request") if isinstance(job.get("request"), dict) else {}
    payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}

    return (
        job.get("script_text")
        or job.get("text")
        or job.get("copy")
        or request.get("script_text")
        or request.get("text")
        or payload.get("script_text")
        or payload.get("text")
        or result.get("script_text")
        or result.get("text")
        or ""
    )


@app.get("/api/video/full-ai/subtitle-bridge/health")
async def _full_ai_subtitle_bridge_health():
    data = _full_ai_subtitle_upload_health()
    data.update(
        {
            "bridge": True,
            "endpoint": "/api/video/full-ai/subtitle-bridge/{job_id}",
            "message": "full-ai 字幕桥接接口可用",
        }
    )
    return data


@app.post("/api/video/full-ai/subtitle-bridge/{job_id}")
async def _full_ai_subtitle_bridge(job_id: str, req: _FullAISubtitleBridgeRequest):
    job = _full_ai_subtitle_find_job(job_id)

    video_url = (req.video_url or _full_ai_subtitle_extract_video_url(job) or "").strip()
    text = (req.text or _full_ai_subtitle_extract_text(job) or "").strip()
    segments = req.segments or None

    if not video_url:
        return _FullAISubtitleJSONResponse(
            {
                "ok": False,
                "status": "missing_video_url",
                "message": "没有找到可烧录字幕的视频 URL。请传 video_url，或确认 full-ai job 已完成并有 video_url。",
                "job_id": job_id,
            },
            status_code=400,
        )

    if not text and not segments:
        return _FullAISubtitleJSONResponse(
            {
                "ok": False,
                "status": "missing_subtitle_text",
                "message": "没有找到字幕文本。请传 text，或传 segments。",
                "job_id": job_id,
                "video_url": video_url,
            },
            status_code=400,
        )

    subtitled_job_id = f"{job_id}_subtitled_{int(_full_ai_subtitle_time.time())}"

    if req.dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "job_id": job_id,
            "subtitled_job_id": subtitled_job_id,
            "video_url": video_url,
            "text_length": len(text),
            "segments_count": len(segments or []),
            "message": "dry_run 已通过：真实执行时会下载 video_url、烧录字幕、上传 R2，不会调用 fal.ai。",
        }

    result = _full_ai_subtitle_burn_upload(
        video_url=video_url,
        text=text,
        segments=segments,
        duration=req.duration,
        max_chars=req.max_chars,
        prefix=req.prefix or "full_ai_subtitled",
        object_key=req.object_key,
    )

    response_data = {
        "ok": True,
        "job_id": subtitled_job_id,
        "original_job_id": job_id,
        "type": "full_ai_subtitle",
        "status": "done",
        "stage": "subtitle_burn_uploaded",
        "message": "full-ai 字幕版视频已生成并上传 R2",
        "video_url": result.get("video_url") or result.get("url"),
        "result": result,
    }

    try:
        memory_jobs = globals().get("_full_ai_jobs")
        if isinstance(memory_jobs, dict) and isinstance(job, dict):
            job["subtitled_video_url"] = response_data["video_url"]
            job["subtitled_job_id"] = subtitled_job_id
            memory_jobs[job_id] = job
    except Exception:
        pass

    if _full_ai_subtitle_save_job_response:
        try:
            _full_ai_subtitle_save_job_response(
                job_id=subtitled_job_id,
                job_type="full_ai_subtitle",
                response_data=response_data,
                source_path=f"/api/video/full-ai/subtitle-bridge/{job_id}",
            )
        except Exception as exc:
            print(f"[full-ai-subtitle-bridge] persist failed: {exc}")

    return response_data
# ===== /FULL AI SUBTITLE BRIDGE HOTFIX =====


# ===== REAL SHOT VIDEO API HOTFIX =====
from pathlib import Path as _RealShotPath
from typing import Any as _RealShotAny
from fastapi import UploadFile as _RealShotUploadFile, File as _RealShotFile, Form as _RealShotForm
from pydantic import BaseModel as _RealShotBaseModel
from app.services.real_shot_provider import (
    UPLOAD_DIR as _real_shot_upload_dir,
    create_self_test_video as _real_shot_create_self_test_video,
    health as _real_shot_health,
    make_job_id as _real_shot_make_job_id,
    probe_video as _real_shot_probe_video,
    process_real_shot as _real_shot_process_real_shot,
    sanitize_filename as _real_shot_sanitize_filename,
)

try:
    from app.services.job_persistence_provider import save_job_response as _real_shot_save_job_response
except Exception:
    _real_shot_save_job_response = None


class _RealShotProcessRequest(_RealShotBaseModel):
    video_path: str = ""
    video_url: str = ""
    text: str = ""
    segments: list[dict[str, _RealShotAny]] | None = None
    burn_subtitle: bool = False
    upload_r2: bool = False
    dry_run: bool = True
    max_chars: int = 18
    prefix: str = "real_shot"


@app.get("/api/video/real-shot/health")
async def _video_real_shot_health():
    return _real_shot_health()


@app.post("/api/video/real-shot/upload")
async def _video_real_shot_upload(
    file: _RealShotUploadFile = _RealShotFile(...),
    source: str = _RealShotForm("upload"),
):
    safe_name = _real_shot_sanitize_filename(file.filename or "real_shot_upload.mp4")
    job_id = _real_shot_make_job_id("real_shot_upload")
    target = _RealShotPath(_real_shot_upload_dir) / f"{job_id}_{safe_name}"

    target.parent.mkdir(parents=True, exist_ok=True)

    size = 0
    with target.open("wb") as f:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            f.write(chunk)

    metadata = _real_shot_probe_video(target)

    response_data = {
        "ok": True,
        "job_id": job_id,
        "type": "real_shot_upload",
        "status": "done",
        "stage": "uploaded",
        "message": "实拍视频已上传到服务器，未调用 fal.ai。",
        "source": source,
        "filename": safe_name,
        "video_path": str(target),
        "size": size,
        "metadata": metadata,
    }

    if _real_shot_save_job_response:
        try:
            _real_shot_save_job_response(
                job_id=job_id,
                job_type="real_shot_upload",
                response_data=response_data,
                source_path="/api/video/real-shot/upload",
            )
        except Exception as exc:
            print(f"[real-shot] persist upload failed: {exc}")

    return response_data


@app.post("/api/video/real-shot/process")
async def _video_real_shot_process(req: _RealShotProcessRequest):
    response_data = _real_shot_process_real_shot(
        video_path=req.video_path,
        video_url=req.video_url,
        text=req.text,
        segments=req.segments,
        burn_subtitle=req.burn_subtitle,
        upload_r2=req.upload_r2,
        dry_run=req.dry_run,
        max_chars=req.max_chars,
        prefix=req.prefix,
    )

    if _real_shot_save_job_response:
        try:
            _real_shot_save_job_response(
                job_id=response_data.get("job_id", ""),
                job_type="real_shot",
                response_data=response_data,
                source_path="/api/video/real-shot/process",
            )
        except Exception as exc:
            print(f"[real-shot] persist process failed: {exc}")

    return response_data


@app.get("/api/video/real-shot/self-test")
async def _video_real_shot_self_test(dry_run: bool = True):
    video_path = _real_shot_create_self_test_video()

    return _real_shot_process_real_shot(
        video_path=str(video_path),
        text="这是实拍视频处理自测。不调用 fal.ai。",
        burn_subtitle=False,
        upload_r2=False,
        dry_run=dry_run,
        max_chars=16,
        prefix="real_shot_self_test",
    )
# ===== /REAL SHOT VIDEO API HOTFIX =====


# ===== HYBRID VIDEO API HOTFIX =====
from pydantic import BaseModel as _HybridBaseModel
from app.services.hybrid_video_provider import (
    create_test_video as _hybrid_create_test_video,
    health as _hybrid_health,
    process_hybrid_video as _hybrid_process_video,
)

try:
    from app.services.job_persistence_provider import save_job_response as _hybrid_save_job_response
except Exception:
    _hybrid_save_job_response = None


class _HybridProcessRequest(_HybridBaseModel):
    real_video_path: str = ""
    real_video_url: str = ""
    ai_video_paths: list[str] | None = None
    ai_video_urls: list[str] | None = None
    order: str = "ai_first"
    text: str = ""
    burn_subtitle: bool = False
    upload_r2: bool = False
    dry_run: bool = True
    max_chars: int = 18
    prefix: str = "hybrid"


@app.get("/api/video/hybrid/health")
async def _video_hybrid_health():
    return _hybrid_health()


@app.post("/api/video/hybrid/process")
async def _video_hybrid_process(req: _HybridProcessRequest):
    response_data = _hybrid_process_video(
        real_video_path=req.real_video_path,
        real_video_url=req.real_video_url,
        ai_video_paths=req.ai_video_paths,
        ai_video_urls=req.ai_video_urls,
        order=req.order,
        text=req.text,
        burn_subtitle=req.burn_subtitle,
        upload_r2=req.upload_r2,
        dry_run=req.dry_run,
        max_chars=req.max_chars,
        prefix=req.prefix,
    )

    if _hybrid_save_job_response:
        try:
            _hybrid_save_job_response(
                job_id=response_data.get("job_id", ""),
                job_type="hybrid",
                response_data=response_data,
                source_path="/api/video/hybrid/process",
            )
        except Exception as exc:
            print(f"[hybrid] persist failed: {exc}")

    return response_data


@app.get("/api/video/hybrid/self-test")
async def _video_hybrid_self_test(dry_run: bool = True):
    real_path = _hybrid_create_test_video(label="REAL_SHOT", color="green", duration=3.0)
    ai_path = _hybrid_create_test_video(label="AI_OPENING", color="blue", duration=2.0)

    return _hybrid_process_video(
        real_video_path=str(real_path),
        ai_video_paths=[str(ai_path)],
        order="ai_first",
        text="这是混合成片自测。AI 镜头只作为开头，实拍素材为主。",
        burn_subtitle=False,
        upload_r2=False,
        dry_run=dry_run,
        max_chars=16,
        prefix="hybrid_self_test",
    )
# ===== /HYBRID VIDEO API HOTFIX =====


# ===== RUNTIME SAFETY API HOTFIX =====
from starlette.responses import JSONResponse as _RuntimeSafetyJSONResponse
from app.services.runtime_safety_provider import (
    cleanup_runtime_files as _runtime_cleanup_files,
    health as _runtime_safety_health,
    is_upload_too_large as _runtime_is_upload_too_large,
)


def _runtime_safety_is_upload_path(path: str) -> bool:
    return path in {
        "/api/video/real-shot/upload",
    }


@app.middleware("http")
async def _runtime_safety_upload_limit_middleware(request, call_next):
    try:
        if request.method.upper() == "POST" and _runtime_safety_is_upload_path(str(request.url.path)):
            too_large, size, max_bytes = _runtime_is_upload_too_large(request.headers.get("content-length"))

            if too_large:
                return _RuntimeSafetyJSONResponse(
                    {
                        "ok": False,
                        "status": "upload_too_large",
                        "message": "上传文件过大，已被后端拦截，未写入磁盘。",
                        "content_length": size,
                        "max_upload_bytes": max_bytes,
                        "max_upload_mb": int(max_bytes / 1024 / 1024),
                    },
                    status_code=413,
                )
    except Exception as exc:
        print(f"[runtime-safety] upload limit middleware failed open: {exc}")

    return await call_next(request)


@app.get("/api/video/runtime-safety/health")
async def _video_runtime_safety_health():
    return _runtime_safety_health()


@app.post("/api/video/runtime-safety/cleanup")
async def _video_runtime_safety_cleanup(
    max_age_hours: float = 24.0,
    dry_run: bool = True,
    max_delete_files: int = 200,
):
    return _runtime_cleanup_files(
        max_age_hours=max_age_hours,
        dry_run=dry_run,
        max_delete_files=max_delete_files,
    )
# ===== /RUNTIME SAFETY API HOTFIX =====


# ===== PRODUCTION HARDENING API HOTFIX =====
from starlette.responses import JSONResponse as _ProductionJSONResponse
from app.services.api_guard_provider import (
    check_request as _api_guard_check_request,
    security_status as _api_guard_security_status,
)
from app.services.production_health_provider import (
    health as _production_health,
)


@app.middleware("http")
async def _production_api_guard_middleware(request, call_next):
    try:
        headers = dict(request.headers)
        client_ip = request.client.host if request.client else ""
        blocked = _api_guard_check_request(
            method=request.method,
            path=str(request.url.path),
            headers=headers,
            client_ip=client_ip,
        )

        if blocked:
            return _ProductionJSONResponse(
                blocked.get("body", {"ok": False, "status": "blocked"}),
                status_code=int(blocked.get("status_code", 403)),
            )
    except Exception as exc:
        print(f"[production-hardening] api guard failed open: {exc}")

    return await call_next(request)


@app.get("/api/video/production/health")
async def _video_production_health():
    return _production_health()


@app.get("/api/video/production/security")
async def _video_production_security():
    return _api_guard_security_status()
# ===== /PRODUCTION HARDENING API HOTFIX =====


# ===== WATERMARK CHECK API HOTFIX =====
from pydantic import BaseModel as _WatermarkBaseModel
from app.services.watermark_provider import (
    check_watermark as _watermark_check,
    create_self_test_video as _watermark_create_self_test_video,
    health as _watermark_health,
)

try:
    from app.services.job_persistence_provider import save_job_response as _watermark_save_job_response
except Exception:
    _watermark_save_job_response = None


class _WatermarkCheckRequest(_WatermarkBaseModel):
    video_path: str = ""
    video_url: str = ""
    sample_count: int = 6
    prefix: str = "watermark"


@app.get("/api/video/watermark/health")
async def _video_watermark_health():
    return _watermark_health()


@app.post("/api/video/watermark/check")
async def _video_watermark_check(req: _WatermarkCheckRequest):
    response_data = _watermark_check(
        video_path=req.video_path,
        video_url=req.video_url,
        sample_count=req.sample_count,
        prefix=req.prefix,
    )

    if _watermark_save_job_response:
        try:
            _watermark_save_job_response(
                job_id=response_data.get("job_id", ""),
                job_type="watermark_check",
                response_data=response_data,
                source_path="/api/video/watermark/check",
            )
        except Exception as exc:
            print(f"[watermark] persist failed: {exc}")

    return response_data


@app.get("/api/video/watermark/self-test")
async def _video_watermark_self_test(with_logo: bool = True):
    video_path = _watermark_create_self_test_video(with_logo=with_logo)

    return _watermark_check(
        video_path=str(video_path),
        sample_count=5,
        prefix="watermark_self_test",
    )
# ===== /WATERMARK CHECK API HOTFIX =====


# ===== TIMELINE ENGINE V1 API HOTFIX =====
from pydantic import BaseModel as _TimelineBaseModel
from app.services.timeline_engine_provider import (
    build_timeline as _timeline_build,
    health as _timeline_health,
    self_test as _timeline_self_test,
)

try:
    from app.services.job_persistence_provider import save_job_response as _timeline_save_job_response
except Exception:
    _timeline_save_job_response = None


class _TimelineBuildRequest(_TimelineBaseModel):
    text: str
    target_duration: float | None = None
    speech_rate_cps: float = 4.2
    min_segment_duration: float = 1.8
    max_segment_duration: float = 6.5


@app.get("/api/video/timeline/health")
async def _video_timeline_health():
    return _timeline_health()


@app.post("/api/video/timeline/build")
async def _video_timeline_build(req: _TimelineBuildRequest):
    response_data = _timeline_build(
        text=req.text,
        target_duration=req.target_duration,
        speech_rate_cps=req.speech_rate_cps,
        min_segment_duration=req.min_segment_duration,
        max_segment_duration=req.max_segment_duration,
    )

    if _timeline_save_job_response:
        try:
            _timeline_save_job_response(
                job_id=response_data.get("timeline_id", ""),
                job_type="timeline",
                response_data=response_data,
                source_path="/api/video/timeline/build",
            )
        except Exception as exc:
            print(f"[timeline] persist failed: {exc}")

    return response_data


@app.get("/api/video/timeline/self-test")
async def _video_timeline_self_test():
    return _timeline_self_test()
# ===== /TIMELINE ENGINE V1 API HOTFIX =====


# ===== TIMELINE TTS ALIGN API HOTFIX =====
from pydantic import BaseModel as _TimelineTTSBaseModel
import asyncio as _timeline_tts_asyncio
from app.services.timeline_tts_align_provider import (
    build_tts_aligned_timeline as _timeline_tts_align_build,
    health as _timeline_tts_align_health,
    self_test as _timeline_tts_align_self_test,
)

try:
    from app.services.job_persistence_provider import save_job_response as _timeline_tts_save_job_response
except Exception:
    _timeline_tts_save_job_response = None


class _TimelineTTSAlignRequest(_TimelineTTSBaseModel):
    text: str
    voice: str = "default"
    overall_rate: str = "0%"
    tts_provider: str | None = None
    target_duration: float | None = None
    dry_run: bool = True
    speech_rate_cps: float = 4.2
    min_segment_duration: float = 1.8
    max_segment_duration: float = 6.5


@app.get("/api/video/timeline/tts-align/health")
async def _video_timeline_tts_align_health():
    return _timeline_tts_align_health()


@app.post("/api/video/timeline/tts-align")
async def _video_timeline_tts_align(req: _TimelineTTSAlignRequest):
    # 真实 TTS 会在 provider 内部通过本机 HTTP 调 /api/tts-segments。
    # 这里必须放到线程里，否则同步 urllib 会阻塞当前 uvicorn event loop，导致本机自调用卡死/空响应。
    response_data = await _timeline_tts_asyncio.to_thread(
        _timeline_tts_align_build,
        text=req.text,
        voice=req.voice,
        overall_rate=req.overall_rate,
        tts_provider=req.tts_provider,
        target_duration=req.target_duration,
        dry_run=req.dry_run,
        speech_rate_cps=req.speech_rate_cps,
        min_segment_duration=req.min_segment_duration,
        max_segment_duration=req.max_segment_duration,
    )

    if _timeline_tts_save_job_response:
        try:
            _timeline_tts_save_job_response(
                job_id=response_data.get("align_id", ""),
                job_type="timeline_tts_align",
                response_data=response_data,
                source_path="/api/video/timeline/tts-align",
            )
        except Exception as exc:
            print(f"[timeline-tts-align] persist failed: {exc}")

    return response_data


@app.get("/api/video/timeline/tts-align/self-test")
async def _video_timeline_tts_align_self_test(dry_run: bool = True):
    return _timeline_tts_align_self_test(dry_run=dry_run)
# ===== /TIMELINE TTS ALIGN API HOTFIX =====


# ===== TIMELINE RENDER PLAN API HOTFIX =====
from pydantic import BaseModel as _TimelineRenderBaseModel
from fastapi import HTTPException as _TimelineRenderHTTPException
from app.services.timeline_render_plan_provider import (
    build_render_plan as _timeline_render_plan_build,
    health as _timeline_render_plan_health,
    self_test as _timeline_render_plan_self_test,
)

try:
    from app.services.job_persistence_provider import save_job_response as _timeline_render_save_job_response
except Exception:
    _timeline_render_save_job_response = None


class _TimelineRenderPlanRequest(_TimelineRenderBaseModel):
    segments: list[dict]
    materials: list[dict]
    audio_url: str = ""
    fit_mode: str = "loop"
    material_strategy: str = "round_robin"
    output_profile: str = "vertical_720x1280"
    burn_subtitle: bool = True


@app.get("/api/video/timeline/render-plan/health")
async def _video_timeline_render_plan_health():
    return _timeline_render_plan_health()


@app.post("/api/video/timeline/render-plan")
async def _video_timeline_render_plan(req: _TimelineRenderPlanRequest):
    try:
        response_data = _timeline_render_plan_build(
            segments=req.segments,
            materials=req.materials,
            audio_url=req.audio_url,
            fit_mode=req.fit_mode,
            material_strategy=req.material_strategy,
            output_profile=req.output_profile,
            burn_subtitle=req.burn_subtitle,
        )
    except ValueError as exc:
        raise _TimelineRenderHTTPException(status_code=400, detail=str(exc))

    if _timeline_render_save_job_response:
        try:
            _timeline_render_save_job_response(
                job_id=response_data.get("render_id", ""),
                job_type="timeline_render_plan",
                response_data=response_data,
                source_path="/api/video/timeline/render-plan",
            )
        except Exception as exc:
            print(f"[timeline-render-plan] persist failed: {exc}")

    return response_data


@app.get("/api/video/timeline/render-plan/self-test")
async def _video_timeline_render_plan_self_test():
    return _timeline_render_plan_self_test()
# ===== /TIMELINE RENDER PLAN API HOTFIX =====


# ===== COMMENT LEAD ENGINE API HOTFIX =====
from fastapi import HTTPException as _CommentLeadHTTPException
from pydantic import BaseModel as _CommentLeadBaseModel
from app.services.comment_lead_provider import (
    analyze_comments as _comment_lead_analyze,
    health as _comment_lead_health,
    recent_leads as _comment_lead_recent,
    self_test as _comment_lead_self_test,
)


class _CommentLeadAnalyzeRequest(_CommentLeadBaseModel):
    comments: list
    campaign_context: dict = {}
    save: bool = True
    max_items: int = 200


@app.get("/api/video/comment-leads/health")
async def _video_comment_leads_health():
    return _comment_lead_health()


@app.post("/api/video/comment-leads/analyze")
async def _video_comment_leads_analyze(req: _CommentLeadAnalyzeRequest):
    try:
        return _comment_lead_analyze(
            comments=req.comments,
            campaign_context=req.campaign_context,
            save=req.save,
            max_items=req.max_items,
        )
    except ValueError as exc:
        raise _CommentLeadHTTPException(status_code=400, detail=str(exc))


@app.get("/api/video/comment-leads/recent")
async def _video_comment_leads_recent(limit: int = 50):
    return _comment_lead_recent(limit=limit)


@app.get("/api/video/comment-leads/self-test")
async def _video_comment_leads_self_test():
    return _comment_lead_self_test()
# ===== /COMMENT LEAD ENGINE API HOTFIX =====


# ===== OPENCLAW COMMENT ADAPTER API HOTFIX =====
from fastapi import HTTPException as _OpenClawHTTPException
from pydantic import BaseModel as _OpenClawBaseModel, Field as _OpenClawField
from app.services.openclaw_comment_adapter_provider import (
    analyze_openclaw_comments as _openclaw_comment_analyze,
    health as _openclaw_comment_health,
    self_test as _openclaw_comment_self_test,
)


class _OpenClawCommentAnalyzeRequest(_OpenClawBaseModel):
    raw_export: object | None = None
    comments: list = _OpenClawField(default_factory=list)
    campaign_context: dict = _OpenClawField(default_factory=dict)
    default_platform: str = ""
    save: bool = True
    max_items: int = 500


@app.get("/api/video/openclaw/comments/health")
async def _video_openclaw_comments_health():
    return _openclaw_comment_health()


@app.post("/api/video/openclaw/comments/analyze")
async def _video_openclaw_comments_analyze(req: _OpenClawCommentAnalyzeRequest):
    try:
        return _openclaw_comment_analyze(
            raw_export=req.raw_export,
            comments=req.comments,
            campaign_context=req.campaign_context,
            default_platform=req.default_platform,
            save=req.save,
            max_items=req.max_items,
        )
    except ValueError as exc:
        raise _OpenClawHTTPException(status_code=400, detail=str(exc))


@app.get("/api/video/openclaw/comments/self-test")
async def _video_openclaw_comments_self_test():
    return _openclaw_comment_self_test()
# ===== /OPENCLAW COMMENT ADAPTER API HOTFIX =====


# ===== OPENCLAW CONTENT INTEL API HOTFIX =====
from fastapi import HTTPException as _OpenClawContentHTTPException
from pydantic import BaseModel as _OpenClawContentBaseModel, Field as _OpenClawContentField
from app.services.openclaw_content_intel_provider import (
    analyze_content as _openclaw_content_analyze,
    health as _openclaw_content_health,
    self_test as _openclaw_content_self_test,
)


class _OpenClawContentAnalyzeRequest(_OpenClawContentBaseModel):
    raw_export: object | None = None
    items: list = _OpenClawContentField(default_factory=list)
    campaign_context: dict = _OpenClawContentField(default_factory=dict)
    save: bool = True
    max_items: int = 300


@app.get("/api/video/openclaw/content/health")
async def _video_openclaw_content_health():
    return _openclaw_content_health()


@app.post("/api/video/openclaw/content/analyze")
async def _video_openclaw_content_analyze(req: _OpenClawContentAnalyzeRequest):
    try:
        return _openclaw_content_analyze(
            raw_export=req.raw_export,
            items=req.items,
            campaign_context=req.campaign_context,
            save=req.save,
            max_items=req.max_items,
        )
    except ValueError as exc:
        raise _OpenClawContentHTTPException(status_code=400, detail=str(exc))


@app.get("/api/video/openclaw/content/self-test")
async def _video_openclaw_content_self_test():
    return _openclaw_content_self_test()
# ===== /OPENCLAW CONTENT INTEL API HOTFIX =====


# ===== OPENCLAW TO TIMELINE API HOTFIX =====
from fastapi import HTTPException as _OpenClawTimelineHTTPException
from pydantic import BaseModel as _OpenClawTimelineBaseModel, Field as _OpenClawTimelineField
from app.services.openclaw_to_timeline_provider import (
    build_openclaw_timeline_plan as _openclaw_timeline_plan,
    health as _openclaw_timeline_health,
    self_test as _openclaw_timeline_self_test,
)


class _OpenClawTimelinePlanRequest(_OpenClawTimelineBaseModel):
    raw_export: object | None = None
    items: list = _OpenClawTimelineField(default_factory=list)
    campaign_context: dict = _OpenClawTimelineField(default_factory=dict)
    save_insight: bool = False
    target_duration: float | None = 28
    min_score: int = 0
    max_items: int = 300
    bgm_policy: dict = _OpenClawTimelineField(default_factory=dict)
    quality_policy: dict = _OpenClawTimelineField(default_factory=dict)


@app.get("/api/video/openclaw/timeline/health")
async def _video_openclaw_timeline_health():
    return _openclaw_timeline_health()


@app.post("/api/video/openclaw/timeline/plan")
async def _video_openclaw_timeline_plan(req: _OpenClawTimelinePlanRequest):
    try:
        return _openclaw_timeline_plan(
            raw_export=req.raw_export,
            items=req.items,
            campaign_context=req.campaign_context,
            save_insight=req.save_insight,
            target_duration=req.target_duration,
            min_score=req.min_score,
            max_items=req.max_items,
            bgm_policy=req.bgm_policy,
            quality_policy=req.quality_policy,
        )
    except ValueError as exc:
        raise _OpenClawTimelineHTTPException(status_code=400, detail=str(exc))


@app.get("/api/video/openclaw/timeline/self-test")
async def _video_openclaw_timeline_self_test():
    return _openclaw_timeline_self_test()
# ===== /OPENCLAW TO TIMELINE API HOTFIX =====


# ===== OPENCLAW LLM ENHANCE API HOTFIX =====
import asyncio as _OpenClawLLMAsyncio
from fastapi import HTTPException as _OpenClawLLMHTTPException
from pydantic import BaseModel as _OpenClawLLMBaseModel, Field as _OpenClawLLMField
from app.services.openclaw_llm_enhance_provider import (
    enhance_comments as _openclaw_llm_enhance_comments,
    enhance_content as _openclaw_llm_enhance_content,
    health as _openclaw_llm_enhance_health,
    self_test as _openclaw_llm_enhance_self_test,
)


class _OpenClawLLMCommentsRequest(_OpenClawLLMBaseModel):
    comments: list = _OpenClawLLMField(default_factory=list)
    raw_export: object | None = None
    campaign_context: dict = _OpenClawLLMField(default_factory=dict)
    min_score: int = 55
    max_llm_items: int = 5
    dry_run: bool = True
    save_rule_leads: bool = False


class _OpenClawLLMContentRequest(_OpenClawLLMBaseModel):
    raw_export: object | None = None
    items: list = _OpenClawLLMField(default_factory=list)
    campaign_context: dict = _OpenClawLLMField(default_factory=dict)
    min_score: int = 55
    max_llm_items: int = 5
    dry_run: bool = True
    save_rule_insights: bool = False


@app.get("/api/video/openclaw/llm-enhance/health")
async def _video_openclaw_llm_enhance_health():
    return _openclaw_llm_enhance_health()


@app.post("/api/video/openclaw/llm-enhance/comments")
async def _video_openclaw_llm_enhance_comments(req: _OpenClawLLMCommentsRequest):
    try:
        return await _OpenClawLLMAsyncio.to_thread(
            _openclaw_llm_enhance_comments,
            comments=req.comments,
            raw_export=req.raw_export,
            campaign_context=req.campaign_context,
            min_score=req.min_score,
            max_llm_items=req.max_llm_items,
            dry_run=req.dry_run,
            save_rule_leads=req.save_rule_leads,
        )
    except ValueError as exc:
        raise _OpenClawLLMHTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise _OpenClawLLMHTTPException(status_code=502, detail=f"openclaw llm comments enhance failed: {exc}")


@app.post("/api/video/openclaw/llm-enhance/content")
async def _video_openclaw_llm_enhance_content(req: _OpenClawLLMContentRequest):
    try:
        return await _OpenClawLLMAsyncio.to_thread(
            _openclaw_llm_enhance_content,
            raw_export=req.raw_export,
            items=req.items,
            campaign_context=req.campaign_context,
            min_score=req.min_score,
            max_llm_items=req.max_llm_items,
            dry_run=req.dry_run,
            save_rule_insights=req.save_rule_insights,
        )
    except ValueError as exc:
        raise _OpenClawLLMHTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise _OpenClawLLMHTTPException(status_code=502, detail=f"openclaw llm content enhance failed: {exc}")


@app.get("/api/video/openclaw/llm-enhance/self-test")
async def _video_openclaw_llm_enhance_self_test():
    return _openclaw_llm_enhance_self_test()
# ===== /OPENCLAW LLM ENHANCE API HOTFIX =====


# ===== NOTIFICATION CENTER API HOTFIX =====
import asyncio as _NotifyAsyncio
from fastapi import HTTPException as _NotifyHTTPException
from pydantic import BaseModel as _NotifyBaseModel, Field as _NotifyField
from app.services.notification_provider import (
    health as _notify_health,
    self_test as _notify_self_test,
    send_message as _notify_send_message,
    send_openclaw_lead as _notify_openclaw_lead,
    send_video_job as _notify_video_job,
)


class _NotifySendRequest(_NotifyBaseModel):
    title: str = "AI-VIDEO 通知"
    message: str
    level: str = "info"
    channels: list[str] = _NotifyField(default_factory=list)
    dry_run: bool = False
    metadata: dict = _NotifyField(default_factory=dict)


class _NotifyOpenClawLeadRequest(_NotifyBaseModel):
    lead: dict
    channels: list[str] = _NotifyField(default_factory=list)
    dry_run: bool = False


class _NotifyVideoJobRequest(_NotifyBaseModel):
    job: dict
    channels: list[str] = _NotifyField(default_factory=list)
    dry_run: bool = False


@app.get("/api/notify/health")
async def _api_notify_health():
    return _notify_health()


@app.post("/api/notify/send")
async def _api_notify_send(req: _NotifySendRequest):
    try:
        return await _NotifyAsyncio.to_thread(
            _notify_send_message,
            title=req.title,
            message=req.message,
            level=req.level,
            channels=req.channels or None,
            dry_run=req.dry_run,
            metadata=req.metadata,
        )
    except Exception as exc:
        raise _NotifyHTTPException(status_code=502, detail=f"notify send failed: {exc}")


@app.post("/api/notify/openclaw-lead")
async def _api_notify_openclaw_lead(req: _NotifyOpenClawLeadRequest):
    try:
        return await _NotifyAsyncio.to_thread(
            _notify_openclaw_lead,
            lead=req.lead,
            channels=req.channels or None,
            dry_run=req.dry_run,
        )
    except Exception as exc:
        raise _NotifyHTTPException(status_code=502, detail=f"notify lead failed: {exc}")


@app.post("/api/notify/video-job")
async def _api_notify_video_job(req: _NotifyVideoJobRequest):
    try:
        return await _NotifyAsyncio.to_thread(
            _notify_video_job,
            job=req.job,
            channels=req.channels or None,
            dry_run=req.dry_run,
        )
    except Exception as exc:
        raise _NotifyHTTPException(status_code=502, detail=f"notify video job failed: {exc}")


@app.get("/api/notify/self-test")
async def _api_notify_self_test(dry_run: bool = True):
    return _notify_self_test(dry_run=dry_run)
# ===== /NOTIFICATION CENTER API HOTFIX =====


# ===== DOUYIN ACCOUNT LIBRARY API HOTFIX =====
import asyncio as _DouyinAccountAsyncio
from fastapi import HTTPException as _DouyinAccountHTTPException
from pydantic import BaseModel as _DouyinAccountBaseModel, Field as _DouyinAccountField
from app.services.douyin_account_library_provider import (
    health as _douyin_account_health,
    self_test as _douyin_account_self_test,
    upsert_account as _douyin_account_upsert,
    bulk_upsert_accounts as _douyin_account_bulk_upsert,
    list_accounts as _douyin_account_list,
    traffic_learning as _douyin_account_traffic_learning,
    competitor_benchmarks as _douyin_account_competitor_benchmarks,
    seed_mission_targets as _douyin_account_seed_targets,
)


class _DouyinAccountUpsertRequest(_DouyinAccountBaseModel):
    account: dict


class _DouyinAccountBulkRequest(_DouyinAccountBaseModel):
    accounts: list = _DouyinAccountField(default_factory=list)


class _DouyinAccountTrafficLearnRequest(_DouyinAccountBaseModel):
    dry_run: bool = True
    min_score: int = 50
    limit: int = 30


class _DouyinAccountBenchmarkRequest(_DouyinAccountBaseModel):
    min_score: int = 60
    limit: int = 30


@app.get("/api/collector/douyin/accounts/health")
async def _api_douyin_accounts_health():
    return _douyin_account_health()


@app.post("/api/collector/douyin/accounts/upsert")
async def _api_douyin_accounts_upsert(req: _DouyinAccountUpsertRequest):
    try:
        return await _DouyinAccountAsyncio.to_thread(_douyin_account_upsert, req.account)
    except ValueError as exc:
        raise _DouyinAccountHTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise _DouyinAccountHTTPException(status_code=502, detail=f"douyin account upsert failed: {exc}")


@app.post("/api/collector/douyin/accounts/bulk-upsert")
async def _api_douyin_accounts_bulk_upsert(req: _DouyinAccountBulkRequest):
    try:
        return await _DouyinAccountAsyncio.to_thread(_douyin_account_bulk_upsert, req.accounts)
    except ValueError as exc:
        raise _DouyinAccountHTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise _DouyinAccountHTTPException(status_code=502, detail=f"douyin account bulk upsert failed: {exc}")


@app.get("/api/collector/douyin/accounts/list")
async def _api_douyin_accounts_list(category: str | None = None, min_score: int = 0, limit: int = 100):
    return _douyin_account_list(category=category, min_score=min_score, limit=limit)


@app.post("/api/collector/douyin/accounts/learn-traffic")
async def _api_douyin_accounts_learn_traffic(req: _DouyinAccountTrafficLearnRequest):
    return await _DouyinAccountAsyncio.to_thread(
        _douyin_account_traffic_learning,
        dry_run=req.dry_run,
        min_score=req.min_score,
        limit=req.limit,
    )


@app.post("/api/collector/douyin/accounts/benchmark-competitors")
async def _api_douyin_accounts_benchmark_competitors(req: _DouyinAccountBenchmarkRequest):
    return await _DouyinAccountAsyncio.to_thread(
        _douyin_account_competitor_benchmarks,
        min_score=req.min_score,
        limit=req.limit,
    )


@app.get("/api/collector/douyin/accounts/seed-targets")
async def _api_douyin_accounts_seed_targets(market: str = "马来西亚"):
    return _douyin_account_seed_targets(market=market)


@app.get("/api/collector/douyin/accounts/self-test")
async def _api_douyin_accounts_self_test():
    return _douyin_account_self_test()
# ===== /DOUYIN ACCOUNT LIBRARY API HOTFIX =====


# ===== FRONTEND CORS HOTFIX =====
try:
    from fastapi.middleware.cors import CORSMiddleware as _FrontendCORSMiddleware

    if not getattr(app.state, "ai_video_frontend_cors_hotfix", False):
        app.add_middleware(
            _FrontendCORSMiddleware,
            allow_origins=[
                "https://ai-video-s5v.pages.dev",
                "http://localhost:5173",
                "http://127.0.0.1:5173",
            ],
            allow_credentials=False,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["*"],
            expose_headers=["*"],
            max_age=86400,
        )
        app.state.ai_video_frontend_cors_hotfix = True
except Exception as _cors_exc:
    print("FRONTEND_CORS_HOTFIX_FAILED", _cors_exc)
# ===== /FRONTEND CORS HOTFIX =====


# ===== FULL AI VISUAL QUALITY HOTFIX =====
AI_VIDEO_VERTICAL_QUALITY_RULE = """
Vertical 9:16 short video, full-screen composition, no black bars.
Realistic clean real-estate/lifestyle B-roll.
No text, no subtitles, no captions, no Chinese characters, no English words,
no logo, no watermark, no UI, no signs, no price tag, no floorplan text.
Do not invent specific property, project name, price, school, transport or ROI.
Only generic atmosphere: city street, condo exterior, hands checking documents,
consultation scene, lifestyle, skyline, neutral office, property viewing mood.
"""

AI_VIDEO_NEGATIVE_PROMPT = (
    "text, subtitles, captions, words, letters, chinese characters, english words, "
    "logo, watermark, typography, signboard, price, numbers, UI, poster, banner, "
    "deformed hands, distorted face, extra fingers, low quality, blurry"
)

def _ai_video_visual_prompt(prompt: str = "", topic: str = "", index: int = 1) -> str:
    # 不把口播文案喂给视频模型，避免模型把文案画成乱码。
    base = str(prompt or "")
    topic = str(topic or "")

    visual_seed = "real estate consultation, city lifestyle, property documents, modern condo atmosphere"
    if "区域" in base or "city" in base.lower():
        visual_seed = "modern Southeast Asian city skyline, street, condo exterior, lifestyle atmosphere"
    elif "预算" in base or "价格" in base or "price" in base.lower():
        visual_seed = "hands reviewing property documents and calculator, clean office, realistic"
    elif "出租" in base or "投资" in base or "rent" in base.lower():
        visual_seed = "apartment exterior, rental lifestyle scene, city commute, realistic"
    elif "家庭" in base or "养老" in base:
        visual_seed = "family lifestyle, clean residential neighborhood, warm realistic atmosphere"

    return (
        f"{AI_VIDEO_VERTICAL_QUALITY_RULE}\n"
        f"Shot {index}: {visual_seed}.\n"
        f"Topic mood: {topic[:80]}.\n"
        f"Camera: vertical 9:16, medium shot, slow push-in, clean lighting, realistic, cinematic.\n"
        f"Negative prompt: {AI_VIDEO_NEGATIVE_PROMPT}"
    )
# ===== /FULL AI VISUAL QUALITY HOTFIX =====


# ===== FULL AI SCRIPT AI PROVIDER HOTFIX =====
try:
    from app.services.full_ai_script_ai_provider import router as full_ai_script_ai_router
    app.include_router(full_ai_script_ai_router)
except Exception as _full_ai_script_ai_exc:
    print("FULL_AI_SCRIPT_AI_PROVIDER_LOAD_FAILED", _full_ai_script_ai_exc)
# ===== /FULL AI SCRIPT AI PROVIDER HOTFIX =====


# ===== MALAYSIA REAL ESTATE VISUAL PLANNER =====
try:
    from app.services.malaysia_visual_planner_provider import install_malaysia_visual_planner
    install_malaysia_visual_planner(app)
except Exception as _malaysia_visual_exc:
    print("MALAYSIA_VISUAL_PLANNER_LOAD_FAILED", _malaysia_visual_exc)
# ===== /MALAYSIA REAL ESTATE VISUAL PLANNER =====


# ===== FULL AI FINAL GUARD PATCH =====
try:
    from app.services.full_ai_final_guard_provider import install_full_ai_final_guard
    install_full_ai_final_guard(app)
except Exception as _full_ai_final_guard_exc:
    print("FULL_AI_FINAL_GUARD_LOAD_FAILED", _full_ai_final_guard_exc)
# ===== /FULL AI FINAL GUARD PATCH =====



# ===== FULL AI TTS FIRST PIPELINE =====
try:
    from app.services.full_ai_tts_first_provider import install_full_ai_tts_first
    install_full_ai_tts_first(app)
except Exception as _full_ai_tts_first_exc:
    print("FULL_AI_TTS_FIRST_LOAD_FAILED", _full_ai_tts_first_exc)
# ===== /FULL AI TTS FIRST PIPELINE =====



# ===== FULL AI POSTPROCESS SUBTITLE TAIL GUARD =====
try:
    from app.services.full_ai_postprocess_guard_provider import install_full_ai_postprocess_guard
    install_full_ai_postprocess_guard(app)
except Exception as _full_ai_postprocess_guard_exc:
    print("FULL_AI_POSTPROCESS_GUARD_LOAD_FAILED", _full_ai_postprocess_guard_exc)
# ===== /FULL AI POSTPROCESS SUBTITLE TAIL GUARD =====



# ===== CONTENT BRAIN BACKEND PROVIDER =====
try:
    from app.services.content_brain_provider import install_content_brain
    install_content_brain(app)
except Exception as _content_brain_exc:
    print("CONTENT_BRAIN_PROVIDER_LOAD_FAILED", _content_brain_exc)
# ===== /CONTENT BRAIN BACKEND PROVIDER =====



# ===== WIZARD AI DEEPSEEK PROVIDER =====
try:
    from app.services.wizard_ai_provider import install_wizard_ai
    install_wizard_ai(app)
except Exception as _wizard_ai_exc:
    print("WIZARD_AI_PROVIDER_LOAD_FAILED", _wizard_ai_exc)
# ===== /WIZARD AI DEEPSEEK PROVIDER =====
# ===== VIDEO WIZARD V10.5 RECOVERY SUBTITLE DIVERSITY =====
try:
    from app.services.subtitle_style_library_provider import install_subtitle_style_library
    install_subtitle_style_library(app)
    print("OK_SUBTITLE_STYLE_LIBRARY_REGISTERED", flush=True)
except Exception as exc:
    print(f"WARN_SUBTITLE_STYLE_LIBRARY_REGISTER_FAILED: {exc}", flush=True)

try:
    from app.services.wizard_video_recovery_provider import install_wizard_video_recovery
    install_wizard_video_recovery(app)
    print("OK_WIZARD_VIDEO_RECOVERY_REGISTERED", flush=True)
except Exception as exc:
    print(f"WARN_WIZARD_VIDEO_RECOVERY_REGISTER_FAILED: {exc}", flush=True)

try:
    from app.services.full_ai_tts_first_v2_provider import install_full_ai_tts_first_v2
    install_full_ai_tts_first_v2(app)
    print("OK_FULL_AI_TTS_FIRST_V2_REGISTERED", flush=True)
except Exception as exc:
    print(f"WARN_FULL_AI_TTS_FIRST_V2_REGISTER_FAILED: {exc}", flush=True)
# ===== /VIDEO WIZARD V10.5 RECOVERY SUBTITLE DIVERSITY =====


# ===== FAL_PROMPT_GUARD_V10_6 =====
try:
    from app.services.fal_prompt_guard_v10_6_provider import install_fal_prompt_guard_v10_6
    install_fal_prompt_guard_v10_6(app)
except Exception as exc:
    print("FAL_PROMPT_GUARD_V10_6_LOAD_FAILED", exc)
# ===== /FAL_PROMPT_GUARD_V10_6 =====

# ===== FAL_PROMPT_GUARD_V10_7 =====
try:
    from app.services.fal_prompt_guard_v10_7_provider import install_fal_prompt_guard_v10_7
    install_fal_prompt_guard_v10_7(app)
except Exception as exc:
    print("FAL_PROMPT_GUARD_V10_7_LOAD_FAILED", exc)
# ===== /FAL_PROMPT_GUARD_V10_7 =====

# ===== VIDEO_RECOVERY_SUBTITLE_DIVERSITY_V10_7_COMPAT =====
try:
    from app.services.subtitle_style_library_provider import install_subtitle_style_library
    install_subtitle_style_library(app)
except Exception as exc:
    print("SUBTITLE_STYLE_LIBRARY_V10_7_LOAD_FAILED", exc)
try:
    from app.services.wizard_video_recovery_provider import install_wizard_video_recovery
    install_wizard_video_recovery(app)
except Exception as exc:
    print("WIZARD_VIDEO_RECOVERY_V10_7_LOAD_FAILED", exc)
try:
    from app.services.full_ai_tts_first_v2_provider import install_full_ai_tts_first_v2
    install_full_ai_tts_first_v2(app)
except Exception as exc:
    print("FULL_AI_TTS_FIRST_V2_V10_7_LOAD_FAILED", exc)
# ===== /VIDEO_RECOVERY_SUBTITLE_DIVERSITY_V10_7_COMPAT =====

# ===== FAL_PROMPT_GUARD_V10_12 =====
try:
    from app.services.fal_prompt_guard_v10_12_provider import install_fal_prompt_guard_v10_12
    install_fal_prompt_guard_v10_12(app)
except Exception as exc:
    print("FAL_PROMPT_GUARD_V10_12_LOAD_FAILED", exc)
# ===== /FAL_PROMPT_GUARD_V10_12 =====

# ===== ONE_SCENE_VIDEO_PIPELINE_V10_12 =====
try:
    from app.services.full_ai_one_scene_provider import install_full_ai_one_scene
    install_full_ai_one_scene(app)
except Exception as exc:
    print("FULL_AI_ONE_SCENE_LOAD_FAILED", exc)
try:
    from app.services.wizard_video_recovery_provider import install_wizard_video_recovery
    install_wizard_video_recovery(app)
except Exception as exc:
    print("WIZARD_VIDEO_RECOVERY_V10_12_LOAD_FAILED", exc)
# ===== /ONE_SCENE_VIDEO_PIPELINE_V10_12 =====

# ===== FAL_PROMPT_GUARD_V10_13 =====
try:
    from app.services.fal_prompt_guard_v10_13_provider import install_fal_prompt_guard_v10_13
    install_fal_prompt_guard_v10_13(app)
except Exception as exc:
    print("FAL_PROMPT_GUARD_V10_13_LOAD_FAILED", exc)
# ===== /FAL_PROMPT_GUARD_V10_13 =====

# ===== SUBTITLE_STYLE_LIBRARY_V10_13 =====
try:
    from app.services.subtitle_style_library_provider import install_subtitle_style_library
    install_subtitle_style_library(app)
except Exception as exc:
    print("SUBTITLE_STYLE_LIBRARY_V10_13_LOAD_FAILED", exc)
# ===== /SUBTITLE_STYLE_LIBRARY_V10_13 =====

# ===== FAL_PROMPT_GUARD_V10_15 =====
try:
    from app.services.fal_prompt_guard_v10_15_provider import install_fal_prompt_guard_v10_15
    install_fal_prompt_guard_v10_15(app)
except Exception as exc:
    print("FAL_PROMPT_GUARD_V10_15_LOAD_FAILED", exc)
# ===== /FAL_PROMPT_GUARD_V10_15 =====

# ===== FAL_PROMPT_GUARD_V10_16 =====
try:
    from app.services.fal_prompt_guard_v10_16_provider import install_fal_prompt_guard_v10_16
    install_fal_prompt_guard_v10_16(app)
except Exception as exc:
    print("FAL_PROMPT_GUARD_V10_16_LOAD_FAILED", exc)
# ===== /FAL_PROMPT_GUARD_V10_16 =====

# ===== FAL_PROMPT_GUARD_V10_17 =====
try:
    from app.services.fal_prompt_guard_v10_17_provider import install_fal_prompt_guard_v10_17
    install_fal_prompt_guard_v10_17(app)
except Exception as exc:
    print("FAL_PROMPT_GUARD_V10_17_LOAD_FAILED", exc)
# ===== /FAL_PROMPT_GUARD_V10_17 =====

# ===== FAL_PROMPT_GUARD_V10_18 =====
try:
    from app.services.fal_prompt_guard_v10_18_provider import install_fal_prompt_guard_v10_18
    install_fal_prompt_guard_v10_18(app)
except Exception as exc:
    print("FAL_PROMPT_GUARD_V10_18_LOAD_FAILED", exc)
# ===== /FAL_PROMPT_GUARD_V10_18 =====

# AI_VIDEO_V10_19_ROUTE_LOCK_START
try:
    from app.services.full_ai_route_lock_provider import install_full_ai_route_lock
    install_full_ai_route_lock(app)
except Exception as _ai_video_route_lock_exc:
    print("V10_19_ROUTE_LOCK_LOAD_FAILED", _ai_video_route_lock_exc)
# AI_VIDEO_V10_19_ROUTE_LOCK_END

# V10_28_REVIEW_RAW_ASSET_WORKFLOW
# Manual review workflow for generated videos:
# - completed generation enters pending/manual review on the frontend
# - approved assets save RAW video before burnt subtitles
# - future slicing uses local raw_no_subtitle.mp4 only and never calls FAL
try:
    import json as _v10_28_json
    import os as _v10_28_os
    import re as _v10_28_re
    import shutil as _v10_28_shutil
    import subprocess as _v10_28_subprocess
    import time as _v10_28_time
    import uuid as _v10_28_uuid
    import urllib.request as _v10_28_urllib_request
    from pathlib import Path as _V1028Path
    from typing import Any as _V1028Any, Dict as _V1028Dict, List as _V1028List, Optional as _V1028Optional

    from fastapi import HTTPException as _V1028HTTPException
    from fastapi.responses import FileResponse as _V1028FileResponse
    from pydantic import BaseModel as _V1028BaseModel

    _V1028_STORAGE_ROOT = _V1028Path(_v10_28_os.environ.get("AI_VIDEO_STORAGE_ROOT", "/opt/ai-video/storage"))
    _V1028_APPROVED_ROOT = _V1028_STORAGE_ROOT / "approved_raw_assets"
    _V1028_REJECTED_ROOT = _V1028_STORAGE_ROOT / "rejected_raw_assets"
    _V1028_SLICE_ROOT = _V1028_STORAGE_ROOT / "asset_slices"

    def _v10_28_safe_asset_id(value: str) -> str:
        value = str(value or "").strip()
        value = _v10_28_re.sub(r"[^A-Za-z0-9_.-]+", "_", value)
        value = value.strip("._-")
        return value[:120] or ("asset_" + _v10_28_uuid.uuid4().hex[:16])

    def _v10_28_json_load(path: _V1028Path) -> _V1028Dict[str, _V1028Any]:
        try:
            if path.exists() and path.stat().st_size > 0:
                return _v10_28_json.loads(path.read_text())
        except Exception:
            return {}
        return {}

    def _v10_28_find_nested_url(data: _V1028Any, key: str) -> _V1028Optional[str]:
        if isinstance(data, dict):
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
            for child in data.values():
                got = _v10_28_find_nested_url(child, key)
                if got:
                    return got
        elif isinstance(data, list):
            for child in data:
                got = _v10_28_find_nested_url(child, key)
                if got:
                    return got
        return None

    def _v10_28_get_job_payload(job_id: str) -> _V1028Dict[str, _V1028Any]:
        job_id = _v10_28_safe_asset_id(job_id)
        candidates = [
            _V1028Path(f"/tmp/{job_id}_final_success.json"),
            _V1028Path(f"/tmp/{job_id}_final.json"),
            _V1028Path(f"/tmp/{job_id}_check.json"),
        ]
        for c in candidates:
            payload = _v10_28_json_load(c)
            if payload:
                return payload
        # Best-effort fallback: query the local backend. This endpoint is sync; keep timeout short.
        try:
            with _v10_28_urllib_request.urlopen(
                f"http://127.0.0.1:8000/api/video/full-ai/tts-first/job/{job_id}",
                timeout=15,
            ) as r:
                if getattr(r, "status", 200) == 200:
                    return _v10_28_json.loads(r.read().decode("utf-8"))
        except Exception:
            return {}
        return {}

    def _v10_28_download_or_copy(src: str, dst: _V1028Path) -> None:
        src = str(src or "").strip()
        if not src:
            raise ValueError("EMPTY_RAW_VIDEO_URL")
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.startswith("file://"):
            local = _V1028Path(src[7:])
            if not local.exists():
                raise FileNotFoundError(str(local))
            _v10_28_shutil.copy2(local, dst)
            return
        if src.startswith("/"):
            local = _V1028Path(src)
            if not local.exists():
                raise FileNotFoundError(str(local))
            _v10_28_shutil.copy2(local, dst)
            return
        req = _v10_28_urllib_request.Request(src, headers={"User-Agent": "ai-video-v10.28-raw-asset-saver"})
        with _v10_28_urllib_request.urlopen(req, timeout=180) as r, open(dst, "wb") as f:
            _v10_28_shutil.copyfileobj(r, f)
        if not dst.exists() or dst.stat().st_size < 1024:
            raise ValueError("DOWNLOADED_RAW_VIDEO_TOO_SMALL")

    def _v10_28_ffprobe(path: _V1028Path) -> _V1028Dict[str, _V1028Any]:
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-show_entries", "stream=width,height,r_frame_rate",
            "-of", "json",
            str(path),
        ]
        try:
            out = _v10_28_subprocess.check_output(cmd, text=True, stderr=_v10_28_subprocess.STDOUT, timeout=30)
            return _v10_28_json.loads(out or "{}")
        except Exception as exc:
            return {"ffprobe_error": repr(exc)}

    class V1028ApproveRawRequest(_V1028BaseModel):
        job_id: _V1028Optional[str] = None
        asset_id: _V1028Optional[str] = None
        raw_video_url: _V1028Optional[str] = None
        subtitled_video_url: _V1028Optional[str] = None
        video_url: _V1028Optional[str] = None
        script_text: _V1028Optional[str] = None
        quality_note: _V1028Optional[str] = None
        approved_by: _V1028Optional[str] = None
        job_result: _V1028Optional[_V1028Dict[str, _V1028Any]] = None

    class V1028RejectRawRequest(_V1028BaseModel):
        job_id: str
        reason: _V1028Optional[str] = None
        raw_video_url: _V1028Optional[str] = None
        subtitled_video_url: _V1028Optional[str] = None
        rejected_by: _V1028Optional[str] = None
        job_result: _V1028Optional[_V1028Dict[str, _V1028Any]] = None

    class V1028SliceRequest(_V1028BaseModel):
        start_seconds: float = 0.0
        end_seconds: _V1028Optional[float] = None
        duration_seconds: _V1028Optional[float] = None
        filename: _V1028Optional[str] = None
        note: _V1028Optional[str] = None

    @app.post("/api/video/assets/approve-raw")
    def v10_28_approve_raw_asset(req: V1028ApproveRawRequest):
        job_payload = req.job_result or {}
        if not job_payload and req.job_id:
            job_payload = _v10_28_get_job_payload(req.job_id)

        raw_url = (
            req.raw_video_url
            or _v10_28_find_nested_url(job_payload, "raw_video_url")
        )
        subtitled_url = (
            req.subtitled_video_url
            or req.video_url
            or _v10_28_find_nested_url(job_payload, "subtitled_video_url")
            or _v10_28_find_nested_url(job_payload, "video_url")
        )
        job_id = req.job_id or str(job_payload.get("job_id") or job_payload.get("id") or "")
        asset_id = _v10_28_safe_asset_id(req.asset_id or job_id or ("asset_" + _v10_28_uuid.uuid4().hex[:16]))

        if not raw_url:
            raise _V1028HTTPException(status_code=400, detail="RAW_VIDEO_URL_REQUIRED_OR_JOB_RESULT_MISSING")

        asset_dir = _V1028_APPROVED_ROOT / asset_id
        raw_path = asset_dir / "raw_no_subtitle.mp4"
        meta_path = asset_dir / "asset_meta.json"
        asset_dir.mkdir(parents=True, exist_ok=True)

        try:
            _v10_28_download_or_copy(raw_url, raw_path)
        except Exception as exc:
            raise _V1028HTTPException(status_code=502, detail=f"RAW_VIDEO_SAVE_FAILED: {exc!r}")

        probe = _v10_28_ffprobe(raw_path)
        script_text = req.script_text or _v10_28_find_nested_url(job_payload.get("request") or {}, "script_text") or ((job_payload.get("request") or {}).get("script_text") if isinstance(job_payload.get("request"), dict) else None)
        meta = {
            "asset_id": asset_id,
            "status": "approved_raw_saved",
            "source_job_id": job_id,
            "approved_at": int(_v10_28_time.time()),
            "approved_by": req.approved_by,
            "quality_note": req.quality_note,
            "raw_video_url": raw_url,
            "subtitled_video_url": subtitled_url,
            "video_url": subtitled_url,
            "raw_video_path": str(raw_path),
            "script_text": script_text,
            "ffprobe": probe,
            "cost_policy": "future_slice_reuses_raw_no_subtitle_mp4_no_fal",
            "must_not_use_for_slice": ["video_url", "subtitled_video_url"],
            "slice_source": "raw_no_subtitle.mp4",
        }
        meta_path.write_text(_v10_28_json.dumps(meta, ensure_ascii=False, indent=2))
        return {"ok": True, "asset": meta}

    @app.post("/api/video/assets/reject")
    def v10_28_reject_raw_asset(req: V1028RejectRawRequest):
        asset_id = _v10_28_safe_asset_id(req.job_id)
        out = _V1028_REJECTED_ROOT / asset_id
        out.mkdir(parents=True, exist_ok=True)
        meta = {
            "asset_id": asset_id,
            "status": "rejected",
            "source_job_id": req.job_id,
            "rejected_at": int(_v10_28_time.time()),
            "rejected_by": req.rejected_by,
            "reason": req.reason,
            "raw_video_url": req.raw_video_url or _v10_28_find_nested_url(req.job_result or {}, "raw_video_url"),
            "subtitled_video_url": req.subtitled_video_url or _v10_28_find_nested_url(req.job_result or {}, "subtitled_video_url"),
            "cost_policy": "rejected_assets_are_not_saved_for_reuse",
        }
        (out / "reject_meta.json").write_text(_v10_28_json.dumps(meta, ensure_ascii=False, indent=2))
        return {"ok": True, "asset": meta}

    @app.get("/api/video/assets")
    def v10_28_list_raw_assets():
        assets = []
        _V1028_APPROVED_ROOT.mkdir(parents=True, exist_ok=True)
        for meta_path in sorted(_V1028_APPROVED_ROOT.glob("*/asset_meta.json"), key=lambda x: x.stat().st_mtime, reverse=True):
            meta = _v10_28_json_load(meta_path)
            if meta:
                assets.append(meta)
        return {"ok": True, "count": len(assets), "assets": assets}

    @app.get("/api/video/assets/{asset_id}")
    def v10_28_get_raw_asset(asset_id: str):
        asset_id = _v10_28_safe_asset_id(asset_id)
        meta_path = _V1028_APPROVED_ROOT / asset_id / "asset_meta.json"
        meta = _v10_28_json_load(meta_path)
        if not meta:
            raise _V1028HTTPException(status_code=404, detail="ASSET_NOT_FOUND")
        return {"ok": True, "asset": meta}

    @app.post("/api/video/assets/{asset_id}/slice")
    def v10_28_slice_raw_asset(asset_id: str, req: V1028SliceRequest):
        asset_id = _v10_28_safe_asset_id(asset_id)
        meta_path = _V1028_APPROVED_ROOT / asset_id / "asset_meta.json"
        meta = _v10_28_json_load(meta_path)
        if not meta:
            raise _V1028HTTPException(status_code=404, detail="ASSET_NOT_FOUND")
        raw_path = _V1028Path(meta.get("raw_video_path") or (_V1028_APPROVED_ROOT / asset_id / "raw_no_subtitle.mp4"))
        if not raw_path.exists():
            raise _V1028HTTPException(status_code=404, detail="RAW_NO_SUBTITLE_FILE_NOT_FOUND")

        start = max(0.0, float(req.start_seconds or 0.0))
        if req.duration_seconds is not None:
            duration = float(req.duration_seconds)
        elif req.end_seconds is not None:
            duration = float(req.end_seconds) - start
        else:
            duration = 5.0
        if duration <= 0:
            raise _V1028HTTPException(status_code=400, detail="SLICE_DURATION_MUST_BE_POSITIVE")
        duration = min(duration, 120.0)

        out_dir = _V1028_SLICE_ROOT / asset_id
        out_dir.mkdir(parents=True, exist_ok=True)
        filename = req.filename or f"slice_{int(start*1000)}_{int((start+duration)*1000)}_{_v10_28_uuid.uuid4().hex[:8]}.mp4"
        filename = _v10_28_safe_asset_id(filename)
        if not filename.endswith(".mp4"):
            filename += ".mp4"
        out_path = out_dir / filename

        cmd = [
            "ffmpeg", "-y",
            "-ss", f"{start:.3f}",
            "-i", str(raw_path),
            "-t", f"{duration:.3f}",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "20",
            "-c:a", "aac",
            "-movflags", "+faststart",
            str(out_path),
        ]
        try:
            proc = _v10_28_subprocess.run(cmd, stdout=_v10_28_subprocess.PIPE, stderr=_v10_28_subprocess.PIPE, text=True, timeout=300)
        except Exception as exc:
            raise _V1028HTTPException(status_code=500, detail=f"SLICE_FFMPEG_FAILED: {exc!r}")
        if proc.returncode != 0 or not out_path.exists():
            raise _V1028HTTPException(status_code=500, detail=("SLICE_FFMPEG_FAILED: " + (proc.stderr or "")[-2000:]))

        slice_meta = {
            "asset_id": asset_id,
            "slice_id": filename,
            "status": "completed",
            "created_at": int(_v10_28_time.time()),
            "source_raw_video_path": str(raw_path),
            "output_path": str(out_path),
            "download_url": f"/api/video/assets/{asset_id}/slices/{filename}",
            "start_seconds": start,
            "duration_seconds": duration,
            "end_seconds": start + duration,
            "uses_fal": False,
            "note": req.note,
        }
        (out_dir / (filename + ".json")).write_text(_v10_28_json.dumps(slice_meta, ensure_ascii=False, indent=2))
        return {"ok": True, "slice": slice_meta}

    @app.get("/api/video/assets/{asset_id}/slices/{filename}")
    def v10_28_get_raw_asset_slice(asset_id: str, filename: str):
        asset_id = _v10_28_safe_asset_id(asset_id)
        filename = _v10_28_safe_asset_id(filename)
        path = _V1028_SLICE_ROOT / asset_id / filename
        if not path.exists():
            raise _V1028HTTPException(status_code=404, detail="SLICE_NOT_FOUND")
        return _V1028FileResponse(str(path), media_type="video/mp4", filename=filename)

    print("V10_28_REVIEW_RAW_ASSET_WORKFLOW_INSTALLED")
except Exception as _v10_28_exc:
    print("V10_28_REVIEW_RAW_ASSET_WORKFLOW_INSTALL_FAILED=" + repr(_v10_28_exc))



# === V10.34 A-G original UI complete extension ===
try:
    from app.services.v10_34_complete_provider import install_v10_34_complete as _install_v10_34_complete
    _install_v10_34_complete(app)
except Exception as _v10_34_complete_exc:
    print('V10_34_A_TO_G_ORIGINAL_UI_INSTALL_FAILED', _v10_34_complete_exc, flush=True)

# ===== AI_VIDEO_GRAPHIC_WINDOW_REPO_SYNC_V1_START =====
try:
    from app.services.graphic_window_provider import install_graphic_window_provider
    install_graphic_window_provider(app)
except Exception as exc:
    print("AI_VIDEO_GRAPHIC_WINDOW_INSTALL_FAILED", repr(exc), flush=True)
# ===== AI_VIDEO_GRAPHIC_WINDOW_REPO_SYNC_V1_END =====

# ===== AI_VIDEO_REVIEW_GATE_V1_START =====
try:
    from app.services.video_review_gate_provider import install_video_review_gate_provider
    install_video_review_gate_provider(app)
except Exception as exc:
    print("AI_VIDEO_REVIEW_GATE_INSTALL_FAILED", repr(exc), flush=True)
# ===== AI_VIDEO_REVIEW_GATE_V1_END =====

