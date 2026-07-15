from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

from app.services.memory import MemoryStore, MemoryWriteError, now_iso


TERMINAL_STAGES = {'run_finished', 'run_failed', 'cancelled'}


QUEUE_MIRROR_PATH = Path(
    os.getenv(
        'AI_VIDEO_COLLECTOR_QUEUE_MIRROR',
        '/opt/ai-video/backend/data/collector_commands_queue.json',
    )
)
WORKER_HEARTBEAT_PATH = Path(
    os.getenv(
        'AI_VIDEO_COLLECTOR_WORKER_HEARTBEAT',
        '/opt/ai-video/backend/data/collector_worker_heartbeat.json',
    )
)
_QUEUE_LOCK = threading.RLock()


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str),
        encoding='utf-8',
    )
    tmp.replace(path)


def _read_queue_mirror() -> list[dict[str, Any]]:
    with _QUEUE_LOCK:
        if not QUEUE_MIRROR_PATH.exists():
            return []
        try:
            data = json.loads(QUEUE_MIRROR_PATH.read_text(encoding='utf-8'))
            return data if isinstance(data, list) else []
        except Exception:
            return []


def _write_queue_mirror(rows: list[dict[str, Any]]) -> None:
    with _QUEUE_LOCK:
        _atomic_json(QUEUE_MIRROR_PATH, rows[-500:])


def _mirror_upsert(command: dict[str, Any]) -> dict[str, Any]:
    clean = _sanitize_payload(command)
    command_id = str(clean.get('id') or clean.get('command_id') or '')
    if not command_id:
        return clean
    rows = _read_queue_mirror()
    replaced = False
    for index, row in enumerate(rows):
        row_id = str(row.get('id') or row.get('command_id') or '')
        if row_id == command_id:
            rows[index] = {**row, **clean, 'id': command_id, 'command_id': command_id}
            replaced = True
            break
    if not replaced:
        rows.append({**clean, 'id': command_id, 'command_id': command_id})
    rows.sort(key=lambda item: str(item.get('created_at') or ''))
    _write_queue_mirror(rows)
    return clean


def _mirror_patch(command_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    rows = _read_queue_mirror()
    result: dict[str, Any] = {'id': command_id, 'command_id': command_id, **patch}
    found = False
    for index, row in enumerate(rows):
        row_id = str(row.get('id') or row.get('command_id') or '')
        if row_id == command_id:
            result = {**row, **patch, 'id': command_id, 'command_id': command_id}
            rows[index] = result
            found = True
            break
    if not found:
        rows.append(result)
    _write_queue_mirror(rows)
    return result


def _mirror_oldest_queued() -> dict[str, Any] | None:
    queued = [
        row for row in _read_queue_mirror()
        if str(row.get('status') or '').lower() == 'queued'
    ]
    queued.sort(key=lambda item: str(item.get('created_at') or ''))
    return queued[0] if queued else None


def _write_worker_heartbeat(command_id: str = '', result: str = 'poll') -> None:
    try:
        _atomic_json(
            WORKER_HEARTBEAT_PATH,
            {
                'ok': True,
                'worker': 'collector-command-worker',
                'last_seen': time.time(),
                'last_seen_iso': now_iso(),
                'command_id': command_id,
                'result': result,
            },
        )
    except Exception:
        pass


def collector_worker_heartbeat(max_age_seconds: int = 20) -> dict[str, Any]:
    if not WORKER_HEARTBEAT_PATH.exists():
        return {
            'ok': True,
            'online': False,
            'age_seconds': None,
            'path': str(WORKER_HEARTBEAT_PATH),
        }
    try:
        data = json.loads(WORKER_HEARTBEAT_PATH.read_text(encoding='utf-8'))
        age = max(0.0, time.time() - float(data.get('last_seen') or 0))
        return {
            'ok': True,
            'online': age <= max(5, int(max_age_seconds)),
            'age_seconds': round(age, 1),
            'path': str(WORKER_HEARTBEAT_PATH),
            **data,
        }
    except Exception as exc:
        return {
            'ok': False,
            'online': False,
            'error': str(exc),
            'path': str(WORKER_HEARTBEAT_PATH),
        }


def collector_queue_mirror_status(limit: int = 50) -> dict[str, Any]:
    rows = _read_queue_mirror()
    rows.sort(key=lambda item: str(item.get('updated_at') or item.get('created_at') or ''), reverse=True)
    return {
        'ok': True,
        'path': str(QUEUE_MIRROR_PATH),
        'heartbeat': collector_worker_heartbeat(),
        'commands': rows[:max(1, min(int(limit or 50), 200))],
        'total': len(rows),
    }


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
    command_id = f"cmd_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    limit = max(1, min(_safe_int(payload.get('limit'), 1), 120))
    raw = payload.get('raw') if isinstance(payload.get('raw'), dict) else {}
    command = {
        'id': command_id,
        'command_id': command_id,
        'status': 'queued',
        'limit': limit,
        'account': payload.get('account') or '',
        'dry_run': bool(payload.get('dry_run')),
        'headful': bool(payload.get('headful', True)),
        'no_delay': bool(payload.get('no_delay')) or limit <= 3,
        'mode': payload.get('mode') or 'manual',
        'message': payload.get('message') or f"等待 ECS Worker 领取命令：{limit} 个账号",
        'raw': raw,
    }
    saved = memory.insert('collector_commands', command, require_supabase=True)
    _mirror_upsert(saved)
    return saved


def next_collector_command(memory: MemoryStore, token: str) -> dict[str, Any]:
    require_ingest_token(token)
    _write_worker_heartbeat(result='poll')

    queued = memory.list(
        'collector_commands',
        limit=50,
        include_deleted=True,
        extra_params={'status': 'eq.queued', 'order': 'created_at.asc'},
    )
    cmd = queued[0] if queued else _mirror_oldest_queued()
    if not cmd:
        return {
            'ok': True,
            'command': None,
            'heartbeat': collector_worker_heartbeat(),
            'queue_source': 'empty',
        }

    command_id = str(cmd.get('id') or cmd.get('command_id') or '')
    patch = {
        'status': 'claimed',
        'claimed_at': now_iso(),
        'message': 'ECS Worker 已领取',
    }

    claimed: dict[str, Any]
    try:
        claimed = memory.update_by_id(
            'collector_commands',
            command_id,
            patch,
            require_supabase=True,
        )
        claimed = {**cmd, **claimed, **patch}
        queue_source = 'supabase'
    except Exception:
        # Supabase 查询/更新异常时仍使用服务器本地耐久镜像交付，
        # 避免 Worker 明明在线却永远拿不到 queued 命令。
        claimed = {**cmd, **patch}
        queue_source = 'local_mirror'

    _mirror_upsert(claimed)
    _write_worker_heartbeat(command_id=command_id, result='claimed')
    return {
        'ok': True,
        'command': _sanitize_payload(claimed),
        'heartbeat': collector_worker_heartbeat(),
        'queue_source': queue_source,
    }


def complete_collector_command(memory: MemoryStore, command_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    payload = _sanitize_payload(payload)
    require_ingest_token(str(payload.get('token') or ''))
    status = payload.get('status') or ('failed' if payload.get('error') else 'finished')
    patch = {
        'status': status,
        'finished_at': now_iso(),
        'message': payload.get('message') or '',
        'raw': payload.get('raw') or {},
    }
    try:
        saved = memory.update_by_id(
            'collector_commands',
            command_id,
            patch,
            require_supabase=True,
        )
        result = {**saved, **patch}
    except Exception:
        result = _mirror_patch(command_id, patch)
    _mirror_upsert(result)
    _write_worker_heartbeat(command_id=command_id, result=str(status))
    return result


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
