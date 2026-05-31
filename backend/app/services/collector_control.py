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
    return {'ok': True, 'command': claimed}


def complete_collector_command(memory: MemoryStore, command_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    require_ingest_token(str(payload.get('token') or ''))
    status = payload.get('status') or ('failed' if payload.get('error') else 'finished')
    return memory.update_by_id('collector_commands', command_id, {'status': status, 'finished_at': now_iso(), 'message': payload.get('message') or '', 'raw': payload.get('raw') or {}}, require_supabase=True)


def recommended_digital_human_providers() -> list[dict[str, Any]]:
    return [
        {
            'id': 'preview_no_avatar',
            'name': '先不训练：静态图文/素材口播',
            'priority': 1,
            'stage': '今天默认',
            'cost_note': '0 训练费；先用脚本 + 配音 + 素材/封面图合成一条完整视频，避免卡在数字人开户和训练。',
            'best_for': '今天完整跑通：采集 → 豆包分析 → 文案脚本 → 配音 → 图文/素材成片。',
            'integration': '系统内部直接走现有素材合成/配音流程，不依赖第三方数字人。',
            'risk': '不是数字人口型同步，但最稳、最快、无训练成本。',
            'enabled': True,
        },
        {
            'id': 'fal_lipsync',
            'name': 'fal.ai 真人模板口型同步',
            'priority': 2,
            'stage': '当前推荐',
            'cost_note': '按秒/分钟计费；用 5-20 秒真人模板视频 + 配音生成真实口播开场。',
            'best_for': '房产顾问/叔叔真人模板：不训练、不克隆，只替换嘴型，真实感明显好于照片说话。',
            'integration': '填 FAL_KEY；上传真人模板 MP4，选择配音后直接生成数字人开场片段。',
            'risk': '模板视频必须授权，且需要公网可访问；建议先用 10-15 秒短片测试。',
            'enabled': True,
        },
        {
            'id': 'heygen_api',
            'name': 'HeyGen API 公共/模板 Avatar',
            'priority': 3,
            'stage': '商业备用',
            'cost_note': '按量/小额充值测试，不先做专属克隆；只用官方公共 Avatar 或模板 Avatar。',
            'best_for': '快速 API 化测试脚本口播，不压训练费。',
            'integration': '填 HEYGEN_API_KEY；先接公共 Avatar 生成，后期再考虑克隆。',
            'risk': '海外服务，中文口型、国内访问速度和合规需要实测。',
            'enabled': False,
        },
        {
            'id': 'did_api',
            'name': 'D-ID API 公共/Presenter 模式',
            'priority': 4,
            'stage': '无训练费备用',
            'cost_note': '优先用 Trial/公共 Presenter，不做 Custom Avatar 训练。',
            'best_for': '用现成 Presenter/照片驱动快速验证数字人口播。',
            'integration': '填 DID_API_KEY；先接 talks / presenters 类接口。',
            'risk': '额度、清晰度、中文口型要实测；不要开高价套餐。',
            'enabled': False,
        },
        {
            'id': 'akool_talking_photo',
            'name': 'AKOOL Talking Photo / Talking Avatar',
            'priority': 5,
            'stage': '海外备用',
            'cost_note': '优先用公开 Avatar/Talking Photo API，不做专属形象训练。',
            'best_for': '照片说话、短口播测试。',
            'integration': '填 AKOOL_API_KEY；先接 talking photo/talking avatar。',
            'risk': '海外服务，费用按 credits/秒或套餐变化，先小样测试。',
            'enabled': False,
        },
        {
            'id': 'local_musetalk_liveportrait',
            'name': '本地 MuseTalk / LivePortrait',
            'priority': 6,
            'stage': '后期设备部署',
            'cost_note': '无平台训练费；需要后期 GPU 设备。',
            'best_for': '他们买设备后，用固定真人底片视频 + 配音做口型同步。',
            'integration': '主站发任务，本地 GPU Worker 拉 R2 素材，处理完回传。',
            'risk': '今天不要做，避免 GPU/环境卡住演示。',
            'enabled': False,
        },
    ]
