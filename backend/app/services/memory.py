from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx

from app.config import Settings


CORE_TABLES = {
    'customer_profiles',
    'competitor_accounts',
    'competitor_videos',
    'trend_radar_records',
    # script_versions 是文案历史，不能因为 Supabase 字段/缓存问题阻断文案生成。
    'learning_events',
    'heat_radar_accounts',
    'heat_radar_account_deletes',
    'heat_radar_items',
    'heat_daily_top3',
    'heat_radar_account_reviews',
    'assets',
    'jobs',
    'operation_logs',
    'collector_runs',
    'collector_events',
    'collector_commands',
    'digital_human_provider_configs',
}


class MemoryWriteError(RuntimeError):
    """Raised when enterprise/core data must be persisted but storage failed."""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(obj: Any) -> Any:
    try:
        if hasattr(obj, 'model_dump'):
            return obj.model_dump()
        if isinstance(obj, dict):
            return {k: _clean(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_clean(x) for x in obj]
        return obj
    except Exception:
        return obj


def _strip_none(obj: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in obj.items() if v is not None}


class MemoryStore:
    """Workspace data store.

    Enterprise rule:
    - Supabase is the source of truth for core business tables.
    - local JSON is only a development fallback.
    - endpoints can call `require_supabase=True` to avoid silent data loss.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.workspace_id = settings.workspace_id or 'default'
        self.local_path = settings.data_dir / 'memory.json'

    @property
    def supabase_enabled(self) -> bool:
        return bool(self.settings.supabase_url and self.settings.supabase_service_role_key)

    @property
    def core_storage_strict(self) -> bool:
        return bool(getattr(self.settings, 'core_storage_strict', False))

    @property
    def _headers(self) -> Dict[str, str]:
        key = self.settings.supabase_service_role_key
        return {
            'apikey': key,
            'Authorization': f'Bearer {key}',
            'Content-Type': 'application/json',
            'Prefer': 'return=representation',
        }

    def _url(self, table: str) -> str:
        return f"{self.settings.supabase_url.rstrip('/')}/rest/v1/{quote(table, safe='')}"

    def _read_local(self) -> Dict[str, List[Dict[str, Any]]]:
        if not self.local_path.exists():
            return {}
        try:
            return json.loads(self.local_path.read_text(encoding='utf-8'))
        except Exception:
            return {}

    def _write_local(self, data: Dict[str, List[Dict[str, Any]]]) -> None:
        self.local_path.parent.mkdir(parents=True, exist_ok=True)
        self.local_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

    def _must_persist(self, table: str, require_supabase: bool = False) -> bool:
        return bool(require_supabase or (self.core_storage_strict and table in CORE_TABLES))

    def status(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            'workspace_id': self.workspace_id,
            'supabase_enabled': self.supabase_enabled,
            'core_storage_strict': self.core_storage_strict,
            'storage': 'supabase' if self.supabase_enabled else 'local-json',
            'ok': False,
            'message': '',
        }
        if not self.supabase_enabled:
            out['ok'] = not self.core_storage_strict
            out['message'] = '数据服务未配置，请检查 Supabase 环境变量。' if self.core_storage_strict else '开发模式：本地 JSON。'
            return out
        try:
            with httpx.Client(timeout=10) as client:
                res = client.get(
                    self._url('operation_logs'),
                    headers=self._headers,
                    params={'select': 'id', 'limit': '1'},
                )
                # 404 usually means SQL not run. Auth/network errors also surface here.
                res.raise_for_status()
            out['ok'] = True
            out['message'] = 'Supabase 可访问。'
        except Exception as exc:
            out['message'] = f'Supabase 检查失败：{type(exc).__name__}: {exc}'
        return out

    def insert(self, table: str, payload: Dict[str, Any], *, require_supabase: bool = False, add_id: bool = True) -> Dict[str, Any]:
        item = _strip_none(_clean(payload))
        if add_id:
            item.setdefault('id', str(uuid.uuid4()))
        item.setdefault('workspace_id', self.workspace_id)
        item.setdefault('created_at', now_iso())
        item.setdefault('updated_at', now_iso())

        if self.supabase_enabled:
            try:
                with httpx.Client(timeout=20) as client:
                    res = client.post(self._url(table), headers=self._headers, json=item)
                    res.raise_for_status()
                    data = res.json()
                    return data[0] if isinstance(data, list) and data else item
            except Exception as exc:
                message = f'Supabase 写入 {table} 失败：{type(exc).__name__}: {exc}'
                if self._must_persist(table, require_supabase=require_supabase):
                    raise MemoryWriteError(message) from exc
                item['_memory_warning'] = message
        elif self._must_persist(table, require_supabase=require_supabase):
            raise MemoryWriteError(f'Supabase 未配置，无法保存核心表 {table}。')

        data = self._read_local()
        data.setdefault(table, []).insert(0, item)
        self._write_local(data)
        return item

    def upsert(self, table: str, payload: Dict[str, Any], *, on_conflict: str = 'id', require_supabase: bool = False) -> Dict[str, Any]:
        item = _strip_none(_clean(payload))
        item.setdefault('id', str(uuid.uuid4()))
        item.setdefault('workspace_id', self.workspace_id)
        item.setdefault('created_at', now_iso())
        item.setdefault('updated_at', now_iso())

        if self.supabase_enabled:
            try:
                headers = {**self._headers, 'Prefer': 'resolution=merge-duplicates,return=representation'}
                with httpx.Client(timeout=20) as client:
                    res = client.post(self._url(table), headers=headers, params={'on_conflict': on_conflict}, json=item)
                    res.raise_for_status()
                    data = res.json()
                    return data[0] if isinstance(data, list) and data else item
            except Exception as exc:
                message = f'Supabase upsert {table} 失败：{type(exc).__name__}: {exc}'
                if self._must_persist(table, require_supabase=require_supabase):
                    raise MemoryWriteError(message) from exc
                item['_memory_warning'] = message
        elif self._must_persist(table, require_supabase=require_supabase):
            raise MemoryWriteError(f'Supabase 未配置，无法保存核心表 {table}。')

        data = self._read_local()
        rows = data.setdefault(table, [])
        key = str(item.get(on_conflict) or item.get('id') or '')
        for idx, row in enumerate(rows):
            if key and str(row.get(on_conflict) or row.get('id') or '') == key:
                rows[idx] = {**row, **item}
                self._write_local(data)
                return rows[idx]
        rows.insert(0, item)
        self._write_local(data)
        return item

    def update_by_id(self, table: str, item_id: str, patch: Dict[str, Any], *, require_supabase: bool = False) -> Dict[str, Any]:
        clean_patch = _strip_none(_clean(patch))
        clean_patch['updated_at'] = now_iso()
        if self.supabase_enabled:
            try:
                with httpx.Client(timeout=20) as client:
                    res = client.patch(
                        self._url(table),
                        headers=self._headers,
                        params={'id': f'eq.{item_id}', 'workspace_id': f'eq.{self.workspace_id}'},
                        json=clean_patch,
                    )
                    res.raise_for_status()
                    data = res.json()
                    return data[0] if isinstance(data, list) and data else {'id': item_id, **clean_patch}
            except Exception as exc:
                message = f'Supabase 更新 {table} 失败：{type(exc).__name__}: {exc}'
                if self._must_persist(table, require_supabase=require_supabase):
                    raise MemoryWriteError(message) from exc
                clean_patch['_memory_warning'] = message
        elif self._must_persist(table, require_supabase=require_supabase):
            raise MemoryWriteError(f'Supabase 未配置，无法更新核心表 {table}。')

        data = self._read_local()
        rows = data.setdefault(table, [])
        for idx, row in enumerate(rows):
            if str(row.get('id') or '') == str(item_id):
                rows[idx] = {**row, **clean_patch}
                self._write_local(data)
                return rows[idx]
        item = {'id': item_id, 'workspace_id': self.workspace_id, **clean_patch}
        rows.insert(0, item)
        self._write_local(data)
        return item

    def delete_by_id(self, table: str, item_id: str, *, require_supabase: bool = False) -> bool:
        if self.supabase_enabled:
            try:
                with httpx.Client(timeout=20) as client:
                    res = client.delete(
                        self._url(table),
                        headers=self._headers,
                        params={'id': f'eq.{item_id}', 'workspace_id': f'eq.{self.workspace_id}'},
                    )
                    res.raise_for_status()
                return True
            except Exception as exc:
                message = f'Supabase 删除 {table} 失败：{type(exc).__name__}: {exc}'
                if self._must_persist(table, require_supabase=require_supabase):
                    raise MemoryWriteError(message) from exc
        elif self._must_persist(table, require_supabase=require_supabase):
            raise MemoryWriteError(f'Supabase 未配置，无法删除核心表 {table}。')

        data = self._read_local()
        rows = data.get(table, [])
        kept = [x for x in rows if str(x.get('id') or '') != str(item_id)]
        data[table] = kept
        self._write_local(data)
        return len(kept) != len(rows)

    def list(self, table: str, limit: int = 50, *, include_deleted: bool = False, extra_params: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
        if self.supabase_enabled:
            try:
                params: dict[str, str] = {
                    'workspace_id': f'eq.{self.workspace_id}',
                    'order': 'created_at.desc',
                    'limit': str(limit),
                }
                if not include_deleted:
                    params['deleted'] = 'is.false'
                if extra_params:
                    params.update(extra_params)
                with httpx.Client(timeout=20) as client:
                    res = client.get(self._url(table), headers=self._headers, params=params)
                    # Some old tables do not have deleted column. Retry without it.
                    if res.status_code in {400, 404} and 'deleted' in params:
                        params.pop('deleted', None)
                        res = client.get(self._url(table), headers=self._headers, params=params)
                    res.raise_for_status()
                    data = res.json()
                    return data if isinstance(data, list) else []
            except Exception:
                if self.core_storage_strict and table in CORE_TABLES:
                    return []
        data = self._read_local()
        rows = list(data.get(table, []))
        if not include_deleted:
            rows = [x for x in rows if not x.get('deleted')]
        return rows[:limit]

    def latest(self, table: str) -> Optional[Dict[str, Any]]:
        items = self.list(table, limit=1)
        return items[0] if items else None

    def save_customer_profile(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self.insert('customer_profiles', payload)

    def save_competitor(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self.insert('competitor_accounts', payload)

    def save_competitor_video(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self.insert('competitor_videos', payload)

    def save_trend_radar(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self.insert('trend_radar_records', payload)

    def save_script_version(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        # 文案历史只作为审计/回看，不允许因为 Supabase 400/字段缓存/RLS 问题阻断主流程。
        # 如果 Supabase 写入失败，insert 会自动降级写本地 memory.json；再失败也只返回 warning。
        try:
            return self.insert('script_versions', payload, require_supabase=False)
        except Exception as exc:
            return {
                'ok': False,
                '_memory_warning': f'script_versions 保存失败但已放行文案生成：{type(exc).__name__}: {exc}',
                **(_strip_none(_clean(payload)) if isinstance(payload, dict) else {}),
            }

    def save_learning_event(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self.insert('learning_events', payload)

    def log_operation(self, event_type: str, title: str, payload: Dict[str, Any] | None = None, level: str = 'info') -> Dict[str, Any]:
        try:
            return self.insert('operation_logs', {
                'event_type': event_type,
                'title': title,
                'level': level,
                'payload': payload or {},
            })
        except Exception:
            return {'ok': False, 'event_type': event_type, 'title': title}

    def context(self) -> Dict[str, Any]:
        profile = self.latest('customer_profiles') or {}
        competitors = self.list('competitor_accounts', limit=30)
        videos = self.list('competitor_videos', limit=30)
        trends = self.list('trend_radar_records', limit=10)
        scripts = self.list('script_versions', limit=10)
        events = self.list('learning_events', limit=20)
        summary = build_learning_summary(profile, competitors, videos, trends, scripts)
        return {
            'workspace_id': self.workspace_id,
            'memory_enabled': self.supabase_enabled,
            'storage': 'supabase' if self.supabase_enabled else 'local-json',
            'profile': profile,
            'competitors': competitors,
            'videos': videos,
            'trends': trends,
            'scripts': scripts,
            'events': events,
            'learning_summary': summary,
        }


def build_learning_summary(profile: Dict[str, Any], competitors: List[Dict[str, Any]], videos: List[Dict[str, Any]], trends: List[Dict[str, Any]], scripts: List[Dict[str, Any]]) -> str:
    parts: List[str] = []
    if profile:
        parts.append(
            f"行业：{profile.get('industry','')}；目标客户：{profile.get('audience','')}；核心卖点：{profile.get('selling_points','')}；转化目标：{profile.get('conversion_goal','')}。"
        )
    if competitors:
        lines = []
        for c in competitors[:8]:
            lines.append(f"{c.get('platform','')}｜{c.get('name','')}｜{c.get('positioning','')}｜{c.get('notes','')}")
        parts.append('竞品账号：' + '\n'.join(lines))
    if videos:
        lines = []
        for v in videos[:8]:
            hook = ','.join(v.get('hooks') or []) if isinstance(v.get('hooks'), list) else str(v.get('hooks') or '')
            lines.append(f"{v.get('source_name','同行视频')}｜{v.get('summary','')}｜钩子：{hook}")
        parts.append('同行采集：' + '\n'.join(lines))
    if trends:
        t = trends[0]
        parts.append(f"最近行业雷达：{t.get('summary','')}；关键词：{','.join(t.get('monitor_keywords') or []) if isinstance(t.get('monitor_keywords'), list) else t.get('monitor_keywords','')}")
    if scripts:
        s = scripts[0]
        parts.append(f"最近采用文案：{s.get('title','')}；开头：{s.get('hook','')}")
    return '\n\n'.join([x for x in parts if x.strip()])
