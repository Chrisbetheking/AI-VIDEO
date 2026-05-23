from __future__ import annotations

from pathlib import Path
from typing import Optional
from urllib.parse import quote

from app.config import Settings


def normalize_prefix(prefix: str) -> str:
    return (prefix or '').strip().strip('/')


def public_r2_url(settings: Settings, object_key: str) -> str:
    base = settings.r2_public_base_url.strip().rstrip('/')
    if not base:
        return ''
    # Keep slashes but encode spaces / chinese filenames safely.
    safe_key = '/'.join(quote(part) for part in object_key.strip('/').split('/'))
    return f'{base}/{safe_key}'


def _r2_client(settings: Settings):
    import boto3  # type: ignore
    from botocore.config import Config  # type: ignore

    endpoint = f'https://{settings.r2_account_id}.r2.cloudflarestorage.com'
    return boto3.client(
        's3',
        endpoint_url=endpoint,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        region_name='auto',
        config=Config(
            connect_timeout=8,
            read_timeout=12,
            retries={'max_attempts': 2, 'mode': 'standard'},
            signature_version='s3v4',
        ),
    )


def _content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == '.mp4':
        return 'video/mp4'
    if suffix == '.mov':
        return 'video/quicktime'
    if suffix == '.webm':
        return 'video/webm'
    if suffix == '.mp3':
        return 'audio/mpeg'
    if suffix == '.wav':
        return 'audio/wav'
    if suffix == '.m4a':
        return 'audio/mp4'
    if suffix in {'.jpg', '.jpeg'}:
        return 'image/jpeg'
    if suffix == '.png':
        return 'image/png'
    if suffix == '.webp':
        return 'image/webp'
    if suffix == '.zip':
        return 'application/zip'
    if suffix == '.srt':
        return 'application/x-subrip'
    return 'application/octet-stream'


def _write_storage_error(settings: Settings, message: str) -> None:
    try:
        data_dir = settings.data_dir
        p = data_dir / 'last_r2_error.txt'
        p.write_text(message[:3000], encoding='utf-8')
        print(f'[storage] {message}', flush=True)
    except Exception:
        pass


def read_last_storage_error(settings: Settings) -> str:
    try:
        p = settings.data_dir / 'last_r2_error.txt'
        return p.read_text(encoding='utf-8')[:3000] if p.exists() else ''
    except Exception:
        return ''


def maybe_upload_to_r2(settings: Settings, path: Path, prefix: str = 'outputs') -> Optional[str]:
    """Best-effort R2 upload.

    R2 misconfiguration must not break TTS / upload / compose. If upload fails,
    the app keeps using local Render URL and records diagnostics in APP_DATA_DIR.
    """
    if not settings.r2_enabled or not path.exists() or not path.is_file():
        return None
    try:
        client = _r2_client(settings)
        key = f'{normalize_prefix(prefix)}/{path.name}' if normalize_prefix(prefix) else path.name
        client.upload_file(
            str(path),
            settings.r2_bucket_name,
            key,
            ExtraArgs={'ContentType': _content_type(path)},
        )
        return public_r2_url(settings, key) or None
    except Exception as exc:
        _write_storage_error(settings, f'R2 upload failed for {path.name}: {type(exc).__name__}: {exc}')
        return None


def maybe_delete_from_r2(settings: Settings, object_keys: list[str]) -> list[str]:
    deleted: list[str] = []
    if not settings.r2_enabled or not object_keys:
        return deleted
    try:
        client = _r2_client(settings)
        for key in object_keys:
            key = key.strip().strip('/')
            if not key:
                continue
            try:
                client.delete_object(Bucket=settings.r2_bucket_name, Key=key)
                deleted.append(key)
            except Exception as exc:
                _write_storage_error(settings, f'R2 delete failed for {key}: {type(exc).__name__}: {exc}')
        return deleted
    except Exception as exc:
        _write_storage_error(settings, f'R2 delete setup failed: {type(exc).__name__}: {exc}')
        return deleted


def maybe_list_r2_objects(settings: Settings, prefix: str = 'uploads', limit: int = 300) -> list[dict]:
    """Best-effort list R2 objects with short timeouts.

    Used by material library after Render restarts. This function should never
    make /api/assets fail; every error is swallowed and exposed via diagnostics.
    """
    if not settings.r2_enabled:
        return []
    try:
        client = _r2_client(settings)
        items: list[dict] = []
        token = None
        normalized_prefix = normalize_prefix(prefix)
        prefix_value = f'{normalized_prefix}/' if normalized_prefix else ''
        while len(items) < limit:
            kwargs = {
                'Bucket': settings.r2_bucket_name,
                'Prefix': prefix_value,
                'MaxKeys': min(1000, max(1, limit - len(items))),
            }
            if token:
                kwargs['ContinuationToken'] = token
            resp = client.list_objects_v2(**kwargs)
            for obj in resp.get('Contents', []) or []:
                key = obj.get('Key')
                if not key or key.endswith('/'):
                    continue
                items.append({
                    'key': key,
                    'name': Path(key).name,
                    'url': public_r2_url(settings, key),
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
        _write_storage_error(settings, f'R2 list failed for prefix={prefix}: {type(exc).__name__}: {exc}')
        return []


def test_r2_connection(settings: Settings) -> dict:
    if not settings.r2_enabled:
        return {'ok': False, 'configured': False, 'message': 'R2 环境变量未配全。'}
    try:
        client = _r2_client(settings)
        resp = client.list_objects_v2(Bucket=settings.r2_bucket_name, MaxKeys=1)
        sample = ''
        for obj in resp.get('Contents', []) or []:
            sample = obj.get('Key') or ''
            break
        return {
            'ok': True,
            'configured': True,
            'bucket': settings.r2_bucket_name,
            'public_base_url': settings.r2_public_base_url,
            'sample_key': sample,
            'message': 'R2 API 可访问。若公开 URL 仍打不开，请启用 R2 公共开发 URL 或绑定自定义域。',
        }
    except Exception as exc:
        _write_storage_error(settings, f'R2 status check failed: {type(exc).__name__}: {exc}')
        return {
            'ok': False,
            'configured': True,
            'bucket': settings.r2_bucket_name,
            'public_base_url': settings.r2_public_base_url,
            'message': f'{type(exc).__name__}: {exc}',
        }
