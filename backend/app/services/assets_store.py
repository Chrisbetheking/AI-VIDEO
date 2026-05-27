from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.config import Settings
from app.services.memory import MemoryStore, MemoryWriteError


def manifest_path(settings: Settings) -> Path:
    return settings.data_dir / 'assets_manifest.json'


def read_manifest(settings: Settings) -> list[dict[str, Any]]:
    path = manifest_path(settings)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
    except Exception:
        pass
    return []


def write_manifest(settings: Settings, items: list[dict[str, Any]]) -> None:
    path = manifest_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(items[:3000], ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def _manifest_upsert(settings: Settings, item: dict[str, Any]) -> dict[str, Any]:
    items = read_manifest(settings)
    asset_id = str(item.get('id') or '')
    filename = str(item.get('filename') or '')
    replaced = False
    for idx, old in enumerate(items):
        if (asset_id and old.get('id') == asset_id) or (filename and old.get('filename') == filename):
            items[idx] = {**old, **item}
            replaced = True
            break
    if not replaced:
        items.insert(0, item)
    write_manifest(settings, items)
    return item


def upsert_asset(settings: Settings, item: dict[str, Any], memory: Optional[MemoryStore] = None, *, require_supabase: bool = False) -> dict[str, Any]:
    """Persist asset metadata.

    Enterprise source of truth is Supabase `assets`; manifest remains a local cache/dev fallback.
    """
    clean = dict(item)
    clean.setdefault('created_at', now_iso())
    clean.setdefault('updated_at', now_iso())
    clean.setdefault('deleted', False)
    if memory:
        try:
            saved = memory.upsert('assets', clean, on_conflict='id', require_supabase=require_supabase)
            # keep local cache for old code paths and faster local listing
            _manifest_upsert(settings, {**clean, **saved})
            return saved
        except MemoryWriteError:
            raise
        except Exception:
            if require_supabase:
                raise
    return _manifest_upsert(settings, clean)


def read_assets(settings: Settings, memory: Optional[MemoryStore] = None, limit: int = 500) -> list[dict[str, Any]]:
    if memory and memory.supabase_enabled:
        rows = memory.list('assets', limit=limit, include_deleted=False)
        if rows:
            return rows
    return read_manifest(settings)[:limit]


def remove_asset(settings: Settings, asset_id: str, memory: Optional[MemoryStore] = None, *, require_supabase: bool = False) -> list[dict[str, Any]]:
    items = read_manifest(settings)
    removed: list[dict[str, Any]] = []
    kept: list[dict[str, Any]] = []
    for item in items:
        if str(item.get('id')) == asset_id or Path(str(item.get('filename') or '')).stem == asset_id:
            removed.append(item)
        else:
            kept.append(item)
    if removed:
        write_manifest(settings, kept)

    if memory:
        try:
            row_candidates = removed or memory.list('assets', limit=5, extra_params={'or': f'(id.eq.{asset_id},filename.ilike.{asset_id}%)'})
            for row in row_candidates:
                row_id = str(row.get('id') or '')
                if row_id:
                    memory.update_by_id('assets', row_id, {'deleted': True}, require_supabase=require_supabase)
                    if not any(str(x.get('id') or '') == row_id for x in removed):
                        removed.append(row)
        except MemoryWriteError:
            raise
        except Exception:
            if require_supabase:
                raise
    return removed


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
