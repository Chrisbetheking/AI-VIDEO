from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from app.config import Settings


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


class MemoryStore:
    """AI 学习记忆层。

    正式：写入 Supabase REST。
    未配置 Supabase：写入 /app/data/memory.json，避免功能直接不可用。
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.workspace_id = settings.workspace_id or 'default'
        self.local_path = settings.data_dir / 'memory.json'

    @property
    def supabase_enabled(self) -> bool:
        return bool(self.settings.supabase_url and self.settings.supabase_service_role_key)

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
        return f"{self.settings.supabase_url.rstrip('/')}/rest/v1/{table}"

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

    def insert(self, table: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        item = _clean(payload)
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
                # Supabase 临时失败不阻断主流程，降级本地，同时记录错误。
                item['_memory_warning'] = f'Supabase 写入失败，已降级本地：{exc}'

        data = self._read_local()
        data.setdefault(table, []).insert(0, item)
        self._write_local(data)
        return item

    def list(self, table: str, limit: int = 50) -> List[Dict[str, Any]]:
        if self.supabase_enabled:
            try:
                params = {
                    'workspace_id': f'eq.{self.workspace_id}',
                    'order': 'created_at.desc',
                    'limit': str(limit),
                }
                with httpx.Client(timeout=20) as client:
                    res = client.get(self._url(table), headers=self._headers, params=params)
                    res.raise_for_status()
                    return res.json() if isinstance(res.json(), list) else []
            except Exception:
                pass
        data = self._read_local()
        return list(data.get(table, []))[:limit]

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
        return self.insert('script_versions', payload)

    def save_learning_event(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self.insert('learning_events', payload)

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
