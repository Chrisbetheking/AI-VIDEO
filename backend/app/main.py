from __future__ import annotations

import mimetypes
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
    CopyRefineRequest,
    CoverRequest,
    CoverResponse,
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
    DigitalHumanCreateRequest,
    DigitalHumanCreateResponse,
    CompetitorVideoSave,
    MemoryContextResponse,
    MemoryEventInput,
    ScriptVersionSave,
)
from app.services.ad_analysis import analyze_ad
from app.services.cover import create_cover
from app.services.deepseek import DeepSeekError, generate_copy, generate_edit_plan, generate_growth_decision, generate_shooting_plan, generate_subtitle_emphasis, generate_trend_radar, generate_voice_director, refine_copy_with_instruction, rewrite_from_inspiration, test_deepseek, video_edit_chat_advice
from app.services.doubao import extract_with_doubao
from app.services.kb import KnowledgeBase
from app.services.memory import MemoryStore
from app.services.publisher import create_publish_package
from app.services.storage import maybe_upload_to_r2
from app.services.tts import get_tts_voices, synthesize_tts, synthesize_tts_segments
from app.services.video import IMAGE_EXTS, VIDEO_EXTS, compose_video
from app.services.video_edit import apply_video_edit
from app.services.digital_human import call_external_digital_human_worker, create_static_avatar_preview

app = FastAPI(title='AI-VIDEO 正式版 API', version='1.0.0')
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)


def get_kb(settings: Settings = Depends(get_settings)) -> KnowledgeBase:
    return KnowledgeBase(settings.db_path)


def get_memory(settings: Settings = Depends(get_settings)) -> MemoryStore:
    return MemoryStore(settings)


def file_url(request: Request, name: str, public_url: Optional[str] = None) -> str:
    return public_url or str(request.url_for('get_output_file', name=name))


def upload_url(request: Request, name: str, public_url: Optional[str] = None) -> str:
    return public_url or str(request.url_for('get_upload_file', name=name))


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


@app.get('/api/health')
def health(settings: Settings = Depends(get_settings)) -> dict:
    return {
        'ok': True,
        'deepseek_model': settings.deepseek_model,
        'ark_video_model': settings.ark_video_model,
        'tts_provider': settings.tts_provider,
        'r2_enabled': settings.r2_enabled,
        'memory_enabled': bool(settings.supabase_url and settings.supabase_service_role_key),
        'workspace_id': settings.workspace_id,
        'data_dir': str(settings.data_dir),
        'time': datetime.now(timezone.utc).isoformat(),
    }


@app.post('/api/ai-test')
async def api_ai_test(payload: dict | None = None, settings: Settings = Depends(get_settings)) -> dict:
    try:
        return await test_deepseek(settings, api_key_override=str((payload or {}).get('api_key') or ''))
    except DeepSeekError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get('/api/memory/context', response_model=MemoryContextResponse)
def api_memory_context(memory: MemoryStore = Depends(get_memory)) -> dict:
    return memory.context()


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
        path, duration, warning = await synthesize_tts_segments(settings, req.segments, voice=req.voice, overall_rate=req.overall_rate)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    public_url = maybe_upload_to_r2(settings, path, prefix='audio')
    return TTSResponse(file_url=file_url(request, path.name, public_url), file_name=path.name, duration_seconds=duration, warning=warning)


@app.get('/api/knowledge', response_model=List[KnowledgeItem])
def api_list_knowledge(kb: KnowledgeBase = Depends(get_kb)) -> List[KnowledgeItem]:
    return kb.list(limit=50)


@app.post('/api/knowledge', response_model=KnowledgeItem)
def api_add_knowledge(item: KnowledgeCreate, kb: KnowledgeBase = Depends(get_kb)) -> KnowledgeItem:
    return kb.add(item)


@app.post('/api/assets', response_model=List[AssetItem])
async def api_upload_assets(request: Request, files: List[UploadFile] = File(...), settings: Settings = Depends(get_settings)) -> List[AssetItem]:
    results: List[AssetItem] = []
    max_bytes = settings.max_upload_mb * 1024 * 1024
    allowed = IMAGE_EXTS | VIDEO_EXTS
    for file in files:
        original = file.filename or 'asset'
        ext = Path(original).suffix.lower()
        if ext not in allowed:
            raise HTTPException(status_code=400, detail=f'不支持的文件类型：{original}')
        asset_id = uuid.uuid4().hex
        dest_name = f'{asset_id}{ext}'
        dest = settings.uploads_dir / dest_name
        total = 0
        with dest.open('wb') as buffer:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    dest.unlink(missing_ok=True)
                    raise HTTPException(status_code=413, detail=f'单次上传超过 {settings.max_upload_mb}MB')
                buffer.write(chunk)
        kind = 'image' if ext in IMAGE_EXTS else 'video'
        public_url = maybe_upload_to_r2(settings, dest, prefix='uploads')
        results.append(AssetItem(id=asset_id, filename=dest_name, original_name=original, kind=kind, url=upload_url(request, dest_name, public_url), size_bytes=total, created_at=datetime.now(timezone.utc).isoformat()))
    return results


@app.get('/api/assets', response_model=List[AssetItem])
def api_list_assets(request: Request, settings: Settings = Depends(get_settings)) -> List[AssetItem]:
    items: List[AssetItem] = []
    for path in sorted(settings.uploads_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not path.is_file() or path.suffix.lower() not in (IMAGE_EXTS | VIDEO_EXTS):
            continue
        kind = 'image' if path.suffix.lower() in IMAGE_EXTS else 'video'
        stat = path.stat()
        items.append(AssetItem(id=path.stem, filename=path.name, original_name=path.name, kind=kind, url=upload_url(request, path.name), size_bytes=stat.st_size, created_at=datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()))
    return items[:100]


@app.get('/api/collected-videos', response_model=List[AssetItem])
def api_list_collected_videos(request: Request, settings: Settings = Depends(get_settings)) -> List[AssetItem]:
    items = api_list_assets(request, settings)
    return [item for item in items if item.kind == 'video' and item.filename.startswith('collected_')][:100]


@app.post('/api/compose-video', response_model=ComposeResponse)
async def api_compose_video(req: ComposeRequest, request: Request, settings: Settings = Depends(get_settings)) -> ComposeResponse:
    asset_paths: List[Path] = []
    if req.asset_ids:
        for asset_id in req.asset_ids:
            path = find_asset_path(settings, asset_id)
            if path:
                asset_paths.append(path)
    else:
        asset_paths = list(settings.uploads_dir.glob('*'))[:6]
    audio_path: Optional[Path] = safe_output_path(settings, req.audio_file_name) if req.audio_file_name else None
    try:
        result = await compose_video(settings=settings, script=req.script, asset_paths=asset_paths, duration_seconds=req.duration_seconds, audio_path=audio_path, voice=req.voice, rate=req.rate)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    video_public = maybe_upload_to_r2(settings, result.video_path, prefix='videos')
    subtitle_public = maybe_upload_to_r2(settings, result.subtitle_path, prefix='subtitles') if result.subtitle_path else None
    audio_public = maybe_upload_to_r2(settings, result.audio_path, prefix='audio') if result.audio_path else None
    return ComposeResponse(
        video_url=file_url(request, result.video_path.name, video_public),
        video_name=result.video_path.name,
        subtitle_url=file_url(request, result.subtitle_path.name, subtitle_public) if result.subtitle_path else None,
        audio_url=file_url(request, result.audio_path.name, audio_public) if result.audio_path else None,
        duration_seconds=result.duration_seconds,
        warnings=result.warnings,
    )


@app.post('/api/cover', response_model=CoverResponse)
def api_cover(req: CoverRequest, request: Request, settings: Settings = Depends(get_settings)) -> CoverResponse:
    try:
        path, prompt = create_cover(settings, req.title, hook=req.hook, subtitle=req.subtitle, brand=req.brand)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    public_url = maybe_upload_to_r2(settings, path, prefix='covers')
    return CoverResponse(cover_url=file_url(request, path.name, public_url), cover_name=path.name, prompt=prompt)



@app.post('/api/digital-human/create', response_model=DigitalHumanCreateResponse)
async def api_digital_human_create(req: DigitalHumanCreateRequest, request: Request, settings: Settings = Depends(get_settings), memory: MemoryStore = Depends(get_memory)) -> DigitalHumanCreateResponse:
    if not settings.enable_digital_human:
        raise HTTPException(status_code=400, detail='数字人功能未启用。')
    if not req.consent_confirmed:
        raise HTTPException(status_code=400, detail='请先确认已获得本人形象和声音授权。')

    avatar_path = find_asset_path(settings, req.avatar_asset_id) or find_media_file(settings, req.avatar_file_name)
    audio_path = find_media_file(settings, req.audio_file_name)
    driver_video_path = find_asset_path(settings, req.driver_video_asset_id)

    if avatar_path is None:
        raise HTTPException(status_code=400, detail='请先上传或选择数字人形象素材：正脸照片、半身照片或一段本人视频。')
    if audio_path is None:
        raise HTTPException(status_code=400, detail='请先生成或选择配音音频。')

    engine = (req.engine or 'auto').strip().lower()
    if engine == 'auto':
        engine = settings.digital_human_engine.strip().lower() or 'preview'

    avatar_public = maybe_upload_to_r2(settings, avatar_path, prefix='digital-human/avatar')
    audio_public = maybe_upload_to_r2(settings, audio_path, prefix='digital-human/audio')
    driver_public = maybe_upload_to_r2(settings, driver_video_path, prefix='digital-human/driver') if driver_video_path else None
    avatar_url_value = upload_url(request, avatar_path.name, avatar_public)
    audio_url_value = file_url(request, audio_path.name, audio_public)
    driver_url_value = upload_url(request, driver_video_path.name, driver_public) if driver_video_path else ''

    warnings: List[str] = []
    try:
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
            memory.save_learning_event({'event_type': 'digital_human', 'title': req.title or '数字人任务', 'payload': {'engine': result.engine, 'status': result.status, 'video_url': result.video_url, 'job_id': result.job_id}})
            return DigitalHumanCreateResponse(status=result.status, engine=result.engine, message=result.message, video_url=result.video_url, job_id=result.job_id, warnings=result.warnings or [], raw=result.raw or {})

        # 没有 GPU worker 时，先生成静态头像视频预览，不伪装成真实口型数字人。
        preview = create_static_avatar_preview(settings, avatar_path, audio_path, title=req.title)
        public_url = maybe_upload_to_r2(settings, preview, prefix='digital-human/preview')
        warnings.append('当前未配置真实数字人 GPU 引擎，已生成静态头像预览视频。要真实口型同步，请配置 DIGITAL_HUMAN_WEBHOOK_URL。')
        warnings.append('推荐引擎：SadTalker 单图口播、MuseTalk 高质量口型、Wav2Lip 视频口型同步、LivePortrait 表情驱动。')
        memory.save_learning_event({'event_type': 'digital_human_preview', 'title': req.title or '数字人预览', 'payload': {'engine': engine, 'file_name': preview.name}})
        return DigitalHumanCreateResponse(status='preview_ready', engine='preview', message='已生成数字人静态预览视频。', video_url=file_url(request, preview.name, public_url), video_name=preview.name, warnings=warnings)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

@app.post('/api/publish-package', response_model=PublishPackageResponse)
def api_publish_package(req: PublishPackageRequest, request: Request, settings: Settings = Depends(get_settings)) -> PublishPackageResponse:
    video_path = safe_output_path(settings, req.video_file_name) if req.video_file_name else None
    cover_path = safe_output_path(settings, req.cover_file_name) if req.cover_file_name else None
    path, checklist = create_publish_package(settings, req.title, req.description, req.tags, video_path, cover_path)
    public_url = maybe_upload_to_r2(settings, path, prefix='packages')
    return PublishPackageResponse(package_url=file_url(request, path.name, public_url), package_name=path.name, status='manual_publish_ready', checklist=checklist)


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


@app.get('/files/outputs/{name}')
def get_output_file(name: str, settings: Settings = Depends(get_settings)) -> FileResponse:
    path = safe_output_path(settings, name)
    media_type = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
    return FileResponse(path, media_type=media_type, filename=path.name)


@app.get('/files/uploads/{name}')
def get_upload_file(name: str, settings: Settings = Depends(get_settings)) -> FileResponse:
    path = safe_upload_path(settings, name)
    media_type = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
    return FileResponse(path, media_type=media_type, filename=path.name)


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
