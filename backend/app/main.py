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
from app.services.digital_human import call_external_digital_human_worker, call_fal_lipsync, query_fal_lipsync, call_jimeng_digital_human, query_jimeng_digital_human, create_static_avatar_preview
from app.services.collector import get_collector_cookie_status, save_collector_cookie_text
from app.services.kb import KnowledgeBase
from app.services.memory import MemoryStore, MemoryWriteError
from app.services.publisher import create_publish_package
from app.services.storage import maybe_upload_to_r2, maybe_delete_from_r2, maybe_list_r2_objects, read_last_storage_error, test_r2_connection
from app.services.tts import get_tts_voices, synthesize_tts, synthesize_tts_segments
from app.services.assets_store import read_assets, upsert_asset, remove_asset, now_iso
from app.services.video import IMAGE_EXTS, VIDEO_EXTS, MediaClip, compose_video
from app.services.video_edit import apply_video_edit
from app.services.auto_collector import run_auto_collection
from app.services.one_click import generate_one_click, revise_one_click
from app.services.graphic_post import create_graphic_post
from app.services.heat_radar import run_public_heat_radar, generate_heat_radar_rewrite, ingest_openclaw_heat_radar, audit_heat_radar_accounts, analyze_heat_radar_video_intake
from app.services.collector_control import create_collector_run, append_collector_event, latest_collector_status, create_collector_command, next_collector_command, complete_collector_command, recommended_digital_human_providers
from app.services.jobs import create_job, get_job, list_jobs, update_job

app = FastAPI(title='AI-VIDEO 正式版 API', version='1.0.0')
settings = get_settings()
_auto_collector_task: asyncio.Task | None = None
_auto_agent_jobs: dict[str, dict] = {}


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
    raw = os.getenv('COMPOSE_MAX_ASSETS', '8')
    try:
        value = int(raw)
    except Exception:
        value = 8
    allow_tiny = str(os.getenv('COMPOSE_ALLOW_TINY_ASSETS', '')).strip().lower() in {'1', 'true', 'yes', 'on'}
    if value < 3 and not allow_tiny:
        value = 8
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
        'folder': 'self',
        'source_type': 'digital_human_intro',
        'r2_url': r2_url,
        'r2_key': r2_key,
        'workspace_id': settings.workspace_id,
        'deleted': False,
        'engine': engine,
    }
    try:
        upsert_asset(settings, asset_payload, memory, require_supabase=settings.core_storage_strict)
    except Exception:
        # Do not fail generation just because the asset index write failed.
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
        for prefix in ['uploads', 'digital-human/avatar', 'digital-human/driver']:
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
        fallback_ext = '.jpg' if kind_hint == 'image' else '.mp4'
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
        path, duration, warning, timings = await synthesize_tts_segments(settings, req.segments, voice=req.voice, overall_rate=req.overall_rate)
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
    if name.startswith('collected_'):
        return 'collected'
    if name.startswith(('ai_image_', 'graphic_', 'cover_')):
        return 'ai'
    if kind == 'image':
        return 'image'
    return 'self'


def _asset_source_type(folder: str, filename: str = '') -> str:
    if folder == 'collected':
        return 'collected'
    if folder == 'ai' or (filename or '').startswith(('ai_image_', 'graphic_', 'cover_')):
        return 'ai_generated'
    if folder == 'provided':
        return 'provided'
    return 'upload'


@app.post('/api/assets', response_model=List[AssetItem])
async def api_upload_assets(request: Request, files: List[UploadFile] = File(...), folder: str = Form('self'), settings: Settings = Depends(get_settings), memory: MemoryStore = Depends(get_memory)) -> List[AssetItem]:
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
            'r2_url': public_url or '',
            'r2_key': f'uploads/{dest_name}' if public_url else '',
            'deleted': False,
        }
        try:
            saved_asset = upsert_asset(settings, asset_payload, memory, require_supabase=settings.core_storage_strict)
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
    limit: int = 200,
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
            ))

    # 3) R2 fallback after Render restart/OOM. Short timeouts in storage.py prevent hanging.
    if include_r2:
        per_prefix_limit = max(20, min(int(limit or 200), 200))
        for prefix in ['uploads', 'digital-human/avatar', 'digital-human/driver']:
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
                ))

    items.sort(key=lambda it: it.created_at, reverse=True)
    return items[:max(1, min(limit, 500))]


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
            pre_warnings.append(f'本次后端最多合成前 {compose_max_assets} 个素材；如需更多，可把 COMPOSE_MAX_ASSETS 调到 12 内，并建议改由 ECS/Worker 合成。')
        for clip_req in sorted_plan[:compose_max_assets]:
            clip = await _resolve_compose_clip(settings, clip_req)
            if clip:
                media_clips.append(clip)
            else:
                missing_asset_ids.append(str(clip_req.asset_id))
    elif req.asset_ids:
        compose_max_assets = _compose_max_assets()
        if len(req.asset_ids) > compose_max_assets:
            pre_warnings.append(f'本次后端最多合成前 {compose_max_assets} 个素材；如需更多，可把 COMPOSE_MAX_ASSETS 调到 12 内，并建议改由 ECS/Worker 合成。')
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
            asset_paths=media_clips,
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
    try:
        if engine in {'jimeng', 'jimeng_omni15', 'omnihuman15', 'omnihuman', 'volcengine_avatar', 'volcengine_jimeng'}:
            result = await call_jimeng_digital_human(
                settings,
                avatar_path=avatar_path,
                audio_path=audio_path,
                avatar_url=avatar_url_value,
                audio_url=audio_url_value,
                driver_video_url=driver_url_value,
                script=req.script,
                title=req.title,
                model=req.jimeng_model or 'omnihuman15',
            )
            stable_video_url, stable_video_name, cache_warnings = await finalize_digital_human_video_url(settings, request, result)
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
        if final_url and final_name and str(result.engine or '').startswith('fal:'):
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
