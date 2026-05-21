from __future__ import annotations

import asyncio
import html
import json
import os
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx

from app.config import Settings

VIDEO_EXTS = {'.mp4', '.mov', '.m4v', '.webm'}
URL_RE = re.compile(r'https?://[^\s，。！？!！；;]+', re.I)
META_VIDEO_RE = re.compile(r'<meta[^>]+(?:property|name)=["\'](?:og:video(?::url)?|twitter:player:stream)["\'][^>]+content=["\']([^"\']+)["\']', re.I)
VIDEO_SRC_RE = re.compile(r'<video[^>]+src=["\']([^"\']+)["\']', re.I)
MP4_RE = re.compile(r'https?:\\?/\\?/[^"\'<>\s]+?\.(?:mp4|mov|m4v|webm)(?:\?[^"\'<>\s]*)?', re.I)
TITLE_RE = re.compile(r'<title[^>]*>(.*?)</title>', re.I | re.S)
DESC_RE = re.compile(r'<meta[^>]+(?:name|property)=["\'](?:description|og:description)["\'][^>]+content=["\']([^"\']+)["\']', re.I | re.S)


@dataclass
class CollectedVideo:
    path: Path
    source_url: str
    final_url: str
    title: str = ''
    description: str = ''
    method: str = ''
    warnings: list[str] | None = None

    @property
    def asset_id(self) -> str:
        return self.path.stem


def extract_first_url(text: str) -> str:
    match = URL_RE.search(text or '')
    if not match:
        return ''
    return match.group(0).rstrip('，。!！;；')


def _is_probably_video_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    return any(path.endswith(ext) for ext in VIDEO_EXTS)


def _decode_js_url(value: str) -> str:
    value = html.unescape(value).strip()
    value = value.replace('\\/', '/')
    value = value.replace('\\u002F', '/').replace('\\u002f', '/')
    if value.startswith('//'):
        value = 'https:' + value
    return value


def _extract_page_title(text: str) -> str:
    match = TITLE_RE.search(text or '')
    if not match:
        return ''
    return re.sub(r'\s+', ' ', html.unescape(match.group(1))).strip()[:200]


def _extract_page_desc(text: str) -> str:
    match = DESC_RE.search(text or '')
    if not match:
        return ''
    return re.sub(r'\s+', ' ', html.unescape(match.group(1))).strip()[:800]


def _extract_candidate_video_urls(html_text: str) -> list[str]:
    candidates: list[str] = []
    for regex in (META_VIDEO_RE, VIDEO_SRC_RE, MP4_RE):
        for match in regex.findall(html_text or ''):
            value = _decode_js_url(match)
            if value.startswith('http') and value not in candidates:
                candidates.append(value)
    return candidates[:12]


def _safe_ext_from_url(url: str, fallback: str = '.mp4') -> str:
    ext = Path(urlparse(url).path).suffix.lower()
    return ext if ext in VIDEO_EXTS else fallback


def _check_size_limit(path: Path, max_mb: int) -> None:
    size_mb = path.stat().st_size / 1024 / 1024
    if size_mb > max_mb:
        path.unlink(missing_ok=True)
        raise RuntimeError(f'采集到的视频 {size_mb:.1f}MB，超过限制 {max_mb}MB。请换短视频或上传精简 MP4。')


async def _download_direct(settings: Settings, url: str, method: str, warnings: list[str]) -> Optional[CollectedVideo]:
    headers = {
        'User-Agent': settings.collector_user_agent,
        'Referer': 'https://www.douyin.com/',
        'Accept': '*/*',
    }
    timeout = httpx.Timeout(settings.collector_timeout_seconds, connect=20)
    ext = _safe_ext_from_url(url)
    dest = settings.uploads_dir / f'collected_{uuid.uuid4().hex}{ext}'
    max_bytes = settings.collector_max_mb * 1024 * 1024
    total = 0

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
        try:
            async with client.stream('GET', url) as resp:
                if resp.status_code >= 400:
                    warnings.append(f'公开视频下载失败：HTTP {resp.status_code}')
                    return None
                ctype = (resp.headers.get('content-type') or '').lower()
                if 'text/html' in ctype and not _is_probably_video_url(str(resp.url)):
                    warnings.append('采集到的是网页，不是视频文件。')
                    return None
                with dest.open('wb') as f:
                    async for chunk in resp.aiter_bytes(1024 * 1024):
                        if not chunk:
                            continue
                        total += len(chunk)
                        if total > max_bytes:
                            dest.unlink(missing_ok=True)
                            warnings.append(f'视频超过 {settings.collector_max_mb}MB，已停止采集。')
                            return None
                        f.write(chunk)
        except Exception as exc:
            dest.unlink(missing_ok=True)
            warnings.append(f'公开视频下载异常：{exc}')
            return None

    if not dest.exists() or dest.stat().st_size < 1024:
        dest.unlink(missing_ok=True)
        warnings.append('采集文件为空，已忽略。')
        return None

    _check_size_limit(dest, settings.collector_max_mb)
    return CollectedVideo(path=dest, source_url=url, final_url=url, method=method, warnings=warnings)


async def _resolve_page_and_meta(settings: Settings, source_url: str, warnings: list[str]) -> tuple[str, str, str, list[str]]:
    headers = {
        'User-Agent': settings.collector_user_agent,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    }
    timeout = httpx.Timeout(settings.collector_timeout_seconds, connect=20)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
        try:
            resp = await client.get(source_url)
        except Exception as exc:
            warnings.append(f'短链解析失败：{exc}')
            return source_url, '', '', []

    final_url = str(resp.url)
    ctype = (resp.headers.get('content-type') or '').lower()
    if resp.status_code >= 400:
        warnings.append(f'短链解析返回 HTTP {resp.status_code}')
        return final_url, '', '', []

    if 'video' in ctype or _is_probably_video_url(final_url):
        return final_url, '', '', [final_url]

    text = resp.text or ''
    title = _extract_page_title(text)
    desc = _extract_page_desc(text)
    candidates = _extract_candidate_video_urls(text)
    if candidates:
        warnings.append('已从公开页面 metadata 中发现候选视频地址。')
    else:
        warnings.append('公开页面没有暴露直连视频地址，将尝试备用采集器/文案采集。')
    return final_url, title, desc, candidates


def _find_downloaded_file(before: set[Path], output_dir: Path) -> Optional[Path]:
    after = {p for p in output_dir.glob('collected_*') if p.is_file()}
    new_files = sorted(after - before, key=lambda p: p.stat().st_mtime, reverse=True)
    for path in new_files:
        if path.suffix.lower() in VIDEO_EXTS and path.stat().st_size > 1024:
            return path
    return None


def _collect_with_ytdlp(settings: Settings, source_url: str, warnings: list[str]) -> Optional[CollectedVideo]:
    if not settings.enable_ytdlp_collector:
        warnings.append('未启用 ENABLE_YTDLP_COLLECTOR，跳过备用视频采集器。')
        return None

    try:
        import yt_dlp  # type: ignore
    except Exception as exc:
        warnings.append(f'备用视频采集器未安装：{exc}')
        return None

    before = {p for p in settings.uploads_dir.glob('collected_*') if p.is_file()}
    outtmpl = str(settings.uploads_dir / f'collected_{uuid.uuid4().hex}.%(ext)s')
    max_bytes = settings.collector_max_mb * 1024 * 1024
    warnings.append('正在尝试备用视频采集器；若平台限制、登录校验或无公开视频文件，会自动降级为文案采集。')

    def progress_hook(d: dict) -> None:
        if d.get('status') == 'downloading':
            downloaded = int(d.get('downloaded_bytes') or 0)
            if downloaded > max_bytes:
                raise RuntimeError(f'视频超过 {settings.collector_max_mb}MB，停止采集。')

    opts = {
        'outtmpl': outtmpl,
        'format': 'bv*[ext=mp4]+ba/b[ext=mp4]/best',
        'merge_output_format': 'mp4',
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'socket_timeout': settings.collector_timeout_seconds,
        'retries': 1,
        'fragment_retries': 1,
        'progress_hooks': [progress_hook],
        'http_headers': {'User-Agent': settings.collector_user_agent, 'Referer': 'https://www.douyin.com/'},
    }

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(source_url, download=True)
    except Exception as exc:
        warnings.append(f'备用视频采集失败：{str(exc)[:300]}')
        return None

    path = None
    requested = (info or {}).get('requested_downloads') or []
    if requested:
        fp = requested[0].get('filepath')
        if fp and Path(fp).exists():
            path = Path(fp)
    if path is None:
        path = _find_downloaded_file(before, settings.uploads_dir)
    if path is None:
        warnings.append('备用视频采集完成但未找到本地视频文件。')
        return None

    try:
        _check_size_limit(path, settings.collector_max_mb)
    except Exception as exc:
        warnings.append(str(exc))
        return None

    title = str((info or {}).get('title') or '')[:200]
    desc = str((info or {}).get('description') or '')[:1000]
    return CollectedVideo(path=path, source_url=source_url, final_url=str((info or {}).get('webpage_url') or source_url), title=title, description=desc, method='ytdlp', warnings=warnings)


async def collect_public_video_best_effort(settings: Settings, source_url: str) -> tuple[Optional[CollectedVideo], list[str]]:
    warnings: list[str] = []
    source_url = extract_first_url(source_url) or source_url.strip()
    if not source_url:
        return None, ['没有检测到视频链接。']
    if not settings.enable_video_collector:
        return None, ['未启用 ENABLE_VIDEO_COLLECTOR，跳过视频采集。']

    if _is_probably_video_url(source_url):
        collected = await _download_direct(settings, source_url, 'direct_video_url', warnings)
        return collected, warnings

    final_url, title, desc, candidates = await _resolve_page_and_meta(settings, source_url, warnings)
    for candidate in candidates:
        collected = await _download_direct(settings, candidate, 'page_metadata', warnings)
        if collected:
            collected.final_url = final_url
            collected.title = title
            collected.description = desc
            return collected, warnings

    collected = await asyncio.to_thread(_collect_with_ytdlp, settings, source_url, warnings)
    if collected:
        if not collected.title:
            collected.title = title
        if not collected.description:
            collected.description = desc
        collected.final_url = final_url or collected.final_url
        return collected, warnings

    warnings.append('未能拿到视频文件：已保留分享文案/标题用于同行钩子采集。')
    return None, warnings
