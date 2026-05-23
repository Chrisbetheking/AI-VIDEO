from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import Settings


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
    tmp.write_text(json.dumps(items[:1000], ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def upsert_asset(settings: Settings, item: dict[str, Any]) -> None:
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


def remove_asset(settings: Settings, asset_id: str) -> list[dict[str, Any]]:
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
    return removed


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
