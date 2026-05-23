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
