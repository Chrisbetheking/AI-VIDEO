from __future__ import annotations

from pathlib import Path
from typing import Optional

from app.config import Settings


def public_r2_url(settings: Settings, object_key: str) -> str:
    base = settings.r2_public_base_url.strip().rstrip('/')
    if base:
        return f'{base}/{object_key}'
    return ''


def maybe_upload_to_r2(settings: Settings, path: Path, prefix: str = 'outputs') -> Optional[str]:
    if not settings.r2_enabled or not path.exists():
        return None
    try:
        import boto3  # type: ignore
    except Exception:
        return None
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
    if path.suffix.lower() == '.mp4':
        content_type = 'video/mp4'
    elif path.suffix.lower() == '.mp3':
        content_type = 'audio/mpeg'
    elif path.suffix.lower() == '.wav':
        content_type = 'audio/wav'
    elif path.suffix.lower() == '.png':
        content_type = 'image/png'
    elif path.suffix.lower() == '.zip':
        content_type = 'application/zip'
    client.upload_file(str(path), settings.r2_bucket_name, key, ExtraArgs={'ContentType': content_type})
    return public_r2_url(settings, key) or None
