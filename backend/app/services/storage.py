from __future__ import annotations

from pathlib import Path
from typing import Optional
import os

from app.config import Settings


def public_r2_url(settings: Settings, object_key: str) -> str:
    base = settings.r2_public_base_url.strip().rstrip('/')
    if base:
        return f'{base}/{object_key}'
    return ''


def maybe_upload_to_r2(settings: Settings, path: Path, prefix: str = 'outputs') -> Optional[str]:
    """Best-effort R2 upload.

    Important: R2 misconfiguration must not break core functions such as TTS.
    If upload fails, keep using the local Render file URL and write a small diagnostic
    file under APP_DATA_DIR so Render logs / user testing can still continue.
    """
    if not settings.r2_enabled or not path.exists():
        return None
    try:
        import boto3  # type: ignore
    except Exception as exc:
        _write_storage_error(settings, f'boto3 import failed: {exc}')
        return None

    try:
        endpoint = f'https://{settings.r2_account_id}.r2.cloudflarestorage.com'
        client = boto3.client(
            's3',
            endpoint_url=endpoint,
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key,
            region_name='auto',
        )
        key = f'{prefix.strip("/")}/{path.name}'
        content_type = 'application/octet-stream'
        suffix = path.suffix.lower()
        if suffix == '.mp4':
            content_type = 'video/mp4'
        elif suffix == '.mp3':
            content_type = 'audio/mpeg'
        elif suffix == '.wav':
            content_type = 'audio/wav'
        elif suffix in {'.jpg', '.jpeg'}:
            content_type = 'image/jpeg'
        elif suffix == '.png':
            content_type = 'image/png'
        elif suffix == '.webp':
            content_type = 'image/webp'
        elif suffix == '.zip':
            content_type = 'application/zip'
        client.upload_file(str(path), settings.r2_bucket_name, key, ExtraArgs={'ContentType': content_type})
        return public_r2_url(settings, key) or None
    except Exception as exc:
        _write_storage_error(settings, f'R2 upload failed for {path.name}: {type(exc).__name__}: {exc}')
        return None


def _write_storage_error(settings: Settings, message: str) -> None:
    try:
        data_dir = settings.data_dir
        p = data_dir / 'last_r2_error.txt'
        p.write_text(message[:2000], encoding='utf-8')
        print(f'[storage] {message}', flush=True)
    except Exception:
        pass


def maybe_delete_from_r2(settings: Settings, object_keys: list[str]) -> list[str]:
    """Best-effort R2 delete for online asset management."""
    deleted: list[str] = []
    if not settings.r2_enabled or not object_keys:
        return deleted
    try:
        import boto3  # type: ignore
    except Exception as exc:
        _write_storage_error(settings, f'boto3 import failed while deleting: {exc}')
        return deleted
    try:
        endpoint = f'https://{settings.r2_account_id}.r2.cloudflarestorage.com'
        client = boto3.client(
            's3',
            endpoint_url=endpoint,
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key,
            region_name='auto',
        )
        for key in object_keys:
            try:
                client.delete_object(Bucket=settings.r2_bucket_name, Key=key)
                deleted.append(key)
            except Exception as exc:
                _write_storage_error(settings, f'R2 delete failed for {key}: {type(exc).__name__}: {exc}')
        return deleted
    except Exception as exc:
        _write_storage_error(settings, f'R2 delete setup failed: {type(exc).__name__}: {exc}')
        return deleted


def maybe_list_r2_objects(settings: Settings, prefix: str = 'uploads', limit: int = 500) -> list[dict]:
    """Best-effort list R2 objects so material library still works after Render restarts."""
    if not settings.r2_enabled:
        return []
    try:
        import boto3  # type: ignore
    except Exception as exc:
        _write_storage_error(settings, f'boto3 import failed while listing: {exc}')
        return []
    try:
        endpoint = f'https://{settings.r2_account_id}.r2.cloudflarestorage.com'
        client = boto3.client(
            's3',
            endpoint_url=endpoint,
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key,
            region_name='auto',
        )
        items: list[dict] = []
        token = None
        while len(items) < limit:
            kwargs = {'Bucket': settings.r2_bucket_name, 'Prefix': prefix.strip('/') + '/', 'MaxKeys': min(1000, limit - len(items))}
            if token:
                kwargs['ContinuationToken'] = token
            resp = client.list_objects_v2(**kwargs)
            for obj in resp.get('Contents', []) or []:
                key = obj.get('Key')
                if not key or key.endswith('/'):
                    continue
                url = public_r2_url(settings, key)
                items.append({
                    'key': key,
                    'name': Path(key).name,
                    'url': url,
                    'size': int(obj.get('Size') or 0),
                    'last_modified': obj.get('LastModified'),
                })
                if len(items) >= limit:
                    break
            if not resp.get('IsTruncated') or len(items) >= limit:
                break
            token = resp.get('NextContinuationToken')
        return items
    except Exception as exc:
        _write_storage_error(settings, f'R2 list failed: {type(exc).__name__}: {exc}')
        return []
