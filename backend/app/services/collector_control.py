from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from app.services.memory import MemoryStore, MemoryWriteError, now_iso


TERMINAL_STAGES = {'run_finished', 'run_failed', 'cancelled'}


def _token_ok(token: str) -> bool:
    expected = (os.getenv('HEAT_RADAR_INGEST_TOKEN') or '').strip()
    return bool(expected and token and token.strip() == expected)


def require_ingest_token(token: str) -> None:
    if not _token_ok(token):
        raise PermissionError('HEAT_RADAR_INGEST_TOKEN 不匹配。')


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _windows_safe_text(value: Any, limit: int = 600) -> str:
    text = '' if value is None else str(value)
    # Windows CMD often runs in GBK; emoji / variation selectors / some symbols can
    # crash local worker output. Keep Chinese, strip anything GBK cannot encode.
    text = ''.join(ch for ch in text if ord(ch) >= 32 or ch in '\r\n\t')
    text = text.encode('gbk', errors='ignore').decode('gbk', errors='ignore')
    text = ' '.join(text.replace('\r', ' ').replace('\n', ' ').replace('\t', ' ').split())
    # Avoid long encoded URLs or browserInfo dumps stretching the UI.
    text = re.sub(r'%7B[^\s]{80,}', '[encoded_payload]', text) if 're' in globals() else text
    text = re.sub(r'https?://\S{120,}', '[long_url]', text) if 're' in globals() else text
    return text[:limit]


def _sanitize_payload(value: Any, depth: int = 0) -> Any:
    if depth > 5:
        return _windows_safe_text(value, 240)
    if isinstance(value, str):
        return _windows_safe_text(value, 1200)
    if isinstance(value, list):
        return [_sanitize_payload(v, depth + 1) for v in value[:200]]
    if isinstance(value, dict):
        return {str(k): _sanitize_payload(v, depth + 1) for k, v in list(value.items())[:120]}
    return value


def create_collector_run(memory: MemoryStore, payload: dict[str, Any]) -> dict[str, Any]:
    payload = _sanitize_payload(payload)
    require_ingest_token(str(payload.get('token') or ''))
    run_id = str(payload.get('run_id') or f"collector_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}")
    item = {
        'id': run_id,
        'run_id': run_id,
        'status': 'running',
        'stage': payload.get('stage') or 'run_started',
        'message': payload.get('message') or '采集任务已启动',
        'current_account': payload.get('current_account') or '',
        'current_video': payload.get('current_video') or '',
        'total_accounts': _safe_int(payload.get('total_accounts'), 0),
        'completed_accounts': _safe_int(payload.get('completed_accounts'), 0),
        'success_videos': _safe_int(payload.get('success_videos'), 0),
        'failed_videos': _safe_int(payload.get('failed_videos'), 0),
        'mode': payload.get('mode') or 'ecs_worker',
        'dry_run': bool(payload.get('dry_run')),
        'command_id': payload.get('command_id') or '',
        'started_at': now_iso(),
        'finished_at': None,
        'last_error': '',
        'raw': payload.get('raw') or {},
    }
    try:
        return memory.upsert('collector_runs', item, on_conflict='run_id', require_supabase=True)
    except MemoryWriteError:
        raise


def append_collector_event(memory: MemoryStore, run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    payload = _sanitize_payload(payload)
    token = str(payload.get('token') or '')
    if token:
        require_ingest_token(token)
    stage = str(payload.get('stage') or 'event')
    level = str(payload.get('level') or ('error' if 'error' in stage or stage == 'run_failed' else 'info'))
    event = {
        'run_id': run_id,
        'stage': stage,
        'level': level,
        'message': payload.get('message') or '',
        'account_name': payload.get('account_name') or '',
        'account_url': payload.get('account_url') or '',
        'video_title': payload.get('video_title') or '',
        'video_url': payload.get('video_url') or '',
        'progress': payload.get('progress') or {},
        'error_detail': payload.get('error_detail') or '',
        'raw': payload.get('raw') or {},
    }
    saved_event = memory.insert('collector_events', event, require_supabase=True)

    patch: dict[str, Any] = {
        'stage': stage,
        'message': event['message'],
        'current_account': event['account_name'],
        'current_video': event['video_title'] or event['video_url'],
    }
    progress = event.get('progress') or {}
    for key in ['total_accounts', 'completed_accounts', 'success_videos', 'failed_videos']:
        if key in progress:
            patch[key] = _safe_int(progress.get(key), 0)
    if level == 'error':
        patch['last_error'] = event['error_detail'] or event['message']
    if stage in TERMINAL_STAGES:
        patch['status'] = 'failed' if stage == 'run_failed' else 'finished'
        patch['finished_at'] = now_iso()
    else:
        patch['status'] = 'running'
    try:
        memory.update_by_id('collector_runs', run_id, patch, require_supabase=True)
    except Exception:
        pass
    return saved_event


def latest_collector_status(memory: MemoryStore, events_limit: int = 30) -> dict[str, Any]:
    runs = memory.list('collector_runs', limit=10, include_deleted=True)
    run = runs[0] if runs else {}
    events: list[dict[str, Any]] = []
    if run.get('run_id'):
        events = memory.list('collector_events', limit=max(1, min(events_limit, 100)), include_deleted=True, extra_params={'run_id': f"eq.{run.get('run_id')}", 'order': 'created_at.desc'})
    commands = memory.list('collector_commands', limit=10, include_deleted=True)
    return {'ok': True, 'run': run, 'events': events, 'commands': commands}


def create_collector_command(memory: MemoryStore, payload: dict[str, Any]) -> dict[str, Any]:
    payload = _sanitize_payload(payload)
    # 前端只负责下发命令；真正执行、上报和上传仍由 ECS Worker 使用 HEAT_RADAR_INGEST_TOKEN 校验。
    # 这样网页不会因为浏览器本地没有 token 而误报，ECS 侧安全校验不变。
    command_id = f"cmd_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    command = {
        'id': command_id,
        'command_id': command_id,
        'status': 'queued',
        'limit': max(1, min(_safe_int(payload.get('limit'), 1), 120)),
        'account': payload.get('account') or '',
        'dry_run': bool(payload.get('dry_run')),
        'headful': bool(payload.get('headful', True)),
        'no_delay': bool(payload.get('no_delay')) or max(1, min(_safe_int(payload.get('limit'), 1), 120)) <= 3,
        'mode': payload.get('mode') or 'manual',
        'message': payload.get('message') or f"等待 ECS Worker 领取命令：{max(1, min(_safe_int(payload.get('limit'), 1), 120))} 个账号",
        'raw': payload.get('raw') or {},
    }
    return memory.insert('collector_commands', command, require_supabase=True)


def next_collector_command(memory: MemoryStore, token: str) -> dict[str, Any]:
    require_ingest_token(token)
    queued = memory.list('collector_commands', limit=20, include_deleted=True, extra_params={'status': 'eq.queued', 'order': 'created_at.asc'})
    if not queued:
        return {'ok': True, 'command': None}
    cmd = queued[0]
    claimed = memory.update_by_id('collector_commands', str(cmd.get('id') or cmd.get('command_id')), {'status': 'claimed', 'claimed_at': now_iso(), 'message': 'ECS Worker 已领取'}, require_supabase=True)
    return {'ok': True, 'command': _sanitize_payload(claimed)}


def complete_collector_command(memory: MemoryStore, command_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    payload = _sanitize_payload(payload)
    require_ingest_token(str(payload.get('token') or ''))
    status = payload.get('status') or ('failed' if payload.get('error') else 'finished')
    return memory.update_by_id('collector_commands', command_id, {'status': status, 'finished_at': now_iso(), 'message': payload.get('message') or '', 'raw': payload.get('raw') or {}}, require_supabase=True)


def recommended_digital_human_providers() -> list[dict[str, Any]]:
    # Keep the UI focused on routes that are actually useful in this project today.
    # Other commercial APIs can still be wired later through DIGITAL_HUMAN_WEBHOOK_URL.
    return [
        {
            'id': 'fal_lipsync',
            'name': 'fal.ai 真人模板口型同步',
            'priority': 1,
            'stage': '当前默认',
            'cost_note': '按秒/分钟计费；用 5-20 秒真人模板视频 + 配音生成真实口播开场。',
            'best_for': '房产顾问/叔叔真人模板：不训练、不克隆，只替换嘴型，真实感明显好于照片说话。',
            'integration': '填 FAL_KEY；上传真人模板 MP4，选择配音后直接生成数字人开场片段。',
            'risk': '模板视频必须授权，且需要公网可访问；建议先用 10-15 秒短片测试。',
            'enabled': True,
        },
        {
            'id': 'preview',
            'name': '免费兜底：静态素材口播',
            'priority': 2,
            'stage': '兜底',
            'cost_note': '0 训练费；用照片/视频底片 + 配音合成预览，确保流程不断。',
            'best_for': 'fal 余额不足、模板素材不合格或演示时快速出片。',
            'integration': '系统内部 FFmpeg 生成，不依赖第三方数字人。',
            'risk': '不是口型同步，但稳定、免费。',
            'enabled': True,
        },
        {
            'id': 'webhook',
            'name': '外部 GPU Worker/API',
            'priority': 3,
            'stage': '后期扩展',
            'cost_note': '自有 GPU 或第三方服务；主站只负责任务分发和回传。',
            'best_for': '后期接 MuseTalk / LatentSync / 自建 Wav2Lip。',
            'integration': '配置 DIGITAL_HUMAN_WEBHOOK_URL。',
            'risk': '今天不作为主路线，避免环境复杂。',
            'enabled': False,
        },
    ]
