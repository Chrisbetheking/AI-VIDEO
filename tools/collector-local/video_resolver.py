from __future__ import annotations


def _force_safe_console() -> None:
    import os as _os
    import sys as _sys
    _os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
    for _stream in (_sys.stdout, _sys.stderr):
        try:
            _stream.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass

_force_safe_console()

import asyncio
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm"}


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name, str(default)).strip().lower()
    return value in {"1", "true", "yes", "y", "on"}


def _first_nonempty(*values: Any) -> str:
    for v in values:
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return ""


def _is_video_like(url: str) -> bool:
    if not url:
        return False
    path = urlparse(url).path.lower()
    return any(path.endswith(ext) for ext in VIDEO_EXTS) or "mime_type=video" in url.lower()


def _pick_direct_url_from_info(info: dict[str, Any]) -> str:
    """Pick a playable direct media URL from yt-dlp metadata when available."""
    if not isinstance(info, dict):
        return ""
    # Sometimes top-level url is already a media URL.
    url = str(info.get("url") or "")
    if url and (url.startswith("http") and (_is_video_like(url) or info.get("ext") in {"mp4", "webm", "mov", "m4v"})):
        return url
    formats = info.get("formats") or []
    if not isinstance(formats, list):
        return ""
    candidates: list[dict[str, Any]] = []
    for f in formats:
        if not isinstance(f, dict):
            continue
        fu = str(f.get("url") or "")
        if not fu.startswith("http"):
            continue
        vcodec = str(f.get("vcodec") or "")
        acodec = str(f.get("acodec") or "")
        ext = str(f.get("ext") or "")
        if ext not in {"mp4", "webm", "mov", "m4v"} and not _is_video_like(fu):
            continue
        # Prefer progressive mp4 or best height.
        score = 0
        if ext == "mp4":
            score += 50
        if vcodec and vcodec != "none":
            score += 30
        if acodec and acodec != "none":
            score += 15
        try:
            score += min(int(f.get("height") or 0), 2160) // 20
        except Exception:
            pass
        f = dict(f)
        f["_score"] = score
        candidates.append(f)
    candidates.sort(key=lambda x: x.get("_score", 0), reverse=True)
    return str(candidates[0].get("url") or "") if candidates else ""


def _ytdlp_extract_sync(video_url: str, cookie_path: str) -> dict[str, Any]:
    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--dump-single-json",
        "--no-playlist",
        "--skip-download",
        "--no-warnings",
        "--socket-timeout",
        os.getenv("VIDEO_DOWNLOAD_TIMEOUT", "120"),
    ]
    if cookie_path and Path(cookie_path).exists() and Path(cookie_path).stat().st_size > 20:
        cmd += ["--cookies", cookie_path]
    cmd.append(video_url)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=int(os.getenv("VIDEO_DOWNLOAD_TIMEOUT", "120")) + 30)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "yt-dlp 解析失败")[-1200:])
    return json.loads(proc.stdout)


async def resolve_by_ytdlp(video_url: str) -> dict[str, Any]:
    if not _env_bool("YT_DLP_ENABLED", True):
        return {"ok": False, "method": "yt_dlp", "error": "YT_DLP_ENABLED=false"}
    cookie_path = os.getenv("YT_DLP_COOKIES_PATH", "douyin_cookies.txt")
    try:
        info = await asyncio.to_thread(_ytdlp_extract_sync, video_url, cookie_path)
        direct_url = _pick_direct_url_from_info(info)
        title = _first_nonempty(info.get("title"), info.get("fulltitle"), info.get("description"))[:180]
        return {
            "ok": bool(direct_url),
            "method": "yt_dlp",
            "resolved_video_url": direct_url,
            "title": title,
            "webpage_url": info.get("webpage_url") or video_url,
            "raw_status": "direct_url_found" if direct_url else "metadata_only",
            "error": "" if direct_url else "yt-dlp 未返回可下载直连地址",
        }
    except Exception as exc:
        return {"ok": False, "method": "yt_dlp", "error": str(exc)[:1000]}


async def resolve_by_cobalt(video_url: str) -> dict[str, Any]:
    api = (os.getenv("COBALT_API_URL") or "").strip().rstrip("/")
    if not api:
        return {"ok": False, "method": "cobalt", "error": "COBALT_API_URL 未配置"}
    # Cobalt API 一般是 POST /，自建实例更稳定；公共实例常有防护，不建议生产依赖。
    try:
        async with httpx.AsyncClient(timeout=int(os.getenv("VIDEO_DOWNLOAD_TIMEOUT", "120"))) as client:
            resp = await client.post(
                api,
                json={"url": video_url, "downloadMode": "auto", "videoQuality": "1080"},
                headers={"Accept": "application/json", "Content-Type": "application/json"},
            )
            data = resp.json() if resp.headers.get("content-type", "").lower().startswith("application/json") else {"text": resp.text[:500]}
            if resp.status_code >= 400:
                return {"ok": False, "method": "cobalt", "error": f"HTTP {resp.status_code}: {str(data)[:500]}"}
            direct_url = str(data.get("url") or data.get("videoUrl") or data.get("downloadUrl") or "")
            status = str(data.get("status") or "")
            if direct_url.startswith("http"):
                return {"ok": True, "method": "cobalt", "resolved_video_url": direct_url, "raw_status": status, "error": ""}
            return {"ok": False, "method": "cobalt", "error": f"未返回下载 URL：{str(data)[:500]}"}
    except Exception as exc:
        return {"ok": False, "method": "cobalt", "error": str(exc)[:1000]}


async def resolve_one_video(video: dict[str, Any], page: Any | None = None) -> dict[str, Any]:
    """Resolve a video item through multiple layers.

    返回结果只给后端更多选择：resolved_video_url 可以是临时直连地址，后端仍会下载/上传/分析。
    """
    original_url = _first_nonempty(video.get("video_url"), video.get("url"))
    if not original_url:
        video.update({"analysis_mode": "text_fallback", "video_download_status": "no_url", "video_download_error": "没有视频链接"})
        return video

    chain = [x.strip().lower() for x in os.getenv("VIDEO_RESOLVE_CHAIN", "yt_dlp,cobalt,text").split(",") if x.strip()]
    errors: list[str] = []

    # 1. If crawler already found a direct play URL from page/API, use it first.
    direct = _first_nonempty(video.get("video_play_url"), video.get("direct_video_url"), video.get("resolved_video_url"))
    if direct:
        video.update({
            "resolved_video_url": direct,
            "download_method": "page_network",
            "video_download_status": "resolved",
            "analysis_mode": "video",
        })
        return video

    for method in chain:
        if method in {"playwright", "network", "page"}:
            # 当前 collector.py 已经做了页面/network 元数据解析，这里只保留扩展位。
            continue
        if method in {"yt_dlp", "ytdlp"}:
            res = await resolve_by_ytdlp(original_url)
        elif method == "cobalt":
            res = await resolve_by_cobalt(original_url)
        elif method == "text":
            break
        else:
            continue
        if res.get("ok") and res.get("resolved_video_url"):
            if res.get("title") and not video.get("video_title"):
                video["video_title"] = res.get("title")
            video.update({
                "resolved_video_url": res.get("resolved_video_url"),
                "download_method": res.get("method"),
                "video_download_status": "resolved",
                "video_download_error": "",
                "analysis_mode": "video",
            })
            return video
        errors.append(f"{res.get('method')}: {res.get('error')}")

    video.update({
        "resolved_video_url": "",
        "download_method": "text_fallback",
        "video_download_status": "text_fallback",
        "video_download_error": " | ".join(errors)[-1500:],
        "analysis_mode": "text_fallback",
    })
    return video


async def resolve_videos_for_items(videos: list[dict[str, Any]], page: Any | None = None) -> list[dict[str, Any]]:
    if os.getenv("VIDEO_RESOLVE_MODE", "auto").lower() in {"off", "false", "0"}:
        return videos
    resolved: list[dict[str, Any]] = []
    total = len(videos)
    for idx, item in enumerate(videos, start=1):
        title = _first_nonempty(item.get("video_title"), item.get("title"), item.get("video_url"))
        print(f"[{idx}/{total}] 解析视频下载源：{title[:80]}")
        resolved_item = await resolve_one_video(dict(item), page=page)
        status = resolved_item.get("video_download_status")
        method = resolved_item.get("download_method")
        err = resolved_item.get("video_download_error")
        if status == "resolved":
            print(f"  视频源解析成功：{method}")
        else:
            print(f"  视频源解析失败/降级：{status} {str(err or '')[:120]}")
        resolved.append(resolved_item)
    return resolved
