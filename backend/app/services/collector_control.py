from __future__ import annotations

import os
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


def create_collector_run(memory: MemoryStore, payload: dict[str, Any]) -> dict[str, Any]:
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
    require_ingest_token(str(payload.get('token') or ''))
    command_id = f"cmd_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    command = {
        'id': command_id,
        'command_id': command_id,
        'status': 'queued',
        'limit': max(1, min(_safe_int(payload.get('limit'), 1), 120)),
        'account': payload.get('account') or '',
        'dry_run': bool(payload.get('dry_run')),
        'headful': bool(payload.get('headful', True)),
        'no_delay': bool(payload.get('no_delay')),
        'mode': payload.get('mode') or 'manual',
        'message': payload.get('message') or '等待 ECS Worker 领取命令',
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
    return {'ok': True, 'command': claimed}


def complete_collector_command(memory: MemoryStore, command_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    require_ingest_token(str(payload.get('token') or ''))
    status = payload.get('status') or ('failed' if payload.get('error') else 'finished')
    return memory.update_by_id('collector_commands', command_id, {'status': status, 'finished_at': now_iso(), 'message': payload.get('message') or '', 'raw': payload.get('raw') or {}}, require_supabase=True)


def recommended_digital_human_providers() -> list[dict[str, Any]]:
    return [
        {
            'id': 'baidu_xiling_photo',
            'name': '百度曦灵照片数字人',
            'priority': 1,
            'stage': '现在优先试',
            'cost_note': '照片数字人定制服务包公开价约 20 元/次；适合低成本验证，不先压阿里训练费用。',
            'best_for': '照片形象 + 文本/音频驱动口播，先跑通脚本到数字人视频闭环。',
            'integration': '先做 Webhook/API 适配层；拿到百度控制台 API 后填 BAIDU_XILING_API_KEY/APP_ID。',
            'risk': '具体视频生成时长、高清、并发另计，正式前先用 1-2 条样片验收。',
            'enabled': True,
        },
        {
            'id': 'tencent_ivh_photo',
            'name': '腾讯云智能数智人 2D 小样本照片',
            'priority': 2,
            'stage': '备用测试',
            'cost_note': '公开价格页显示 2D 小样本照片形象约 19.9 元/个，但视频播报/小时包另计。',
            'best_for': '低成本照片形象测试；后面企业版再比较清晰度、口型和资源包。',
            'integration': '保留 provider=tencent_ivh；拿 SecretId/SecretKey 后接入。',
            'risk': '视频时长包和并发可能比单个形象贵，先不要大量采购。',
            'enabled': True,
        },
        {
            'id': 'heygen_api',
            'name': 'HeyGen API',
            'priority': 3,
            'stage': '海外备用',
            'cost_note': 'API Pay-as-you-go 可小额充值起步，适合外贸/英文场景；国内访问和合规需测试。',
            'best_for': '快速 API 化、英文口播和海外营销素材。',
            'integration': '保留 HEYGEN_API_KEY；先做外部 Webhook 调用。',
            'risk': '中文口型/国内访问速度/出海账号合规需要实测。',
            'enabled': False,
        },
        {
            'id': 'local_musetalk_liveportrait',
            'name': '本地 MuseTalk / LivePortrait',
            'priority': 4,
            'stage': '后期设备部署',
            'cost_note': '不用按条付费，但需要后期 GPU 设备；适合他们买设备后长期跑。',
            'best_for': '已有真人底片视频 + TTS 配音，做口型同步和头像动效。',
            'integration': '主站只发任务，本地 GPU Worker 拉 R2 素材，处理完再回传。',
            'risk': '首期不要做，避免被环境/GPU 卡住今天演示。',
            'enabled': False,
        },
    ]
