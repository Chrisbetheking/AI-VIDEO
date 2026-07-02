from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib import request as urlrequest

from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import JSONResponse


DATA_DIR = Path("/opt/ai-video/backend/data/final-postprocess")
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _admin_headers() -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    try:
        token = Path("/root/ai-video-admin-token.txt").read_text(encoding="utf-8").strip()
        if token:
            headers["X-AI-Video-Token"] = token
    except Exception:
        pass
    return headers


def _download(url: str, path: Path) -> bool:
    try:
        with urlrequest.urlopen(url, timeout=120) as r:
            path.write_bytes(r.read())
        return path.exists() and path.stat().st_size > 1024
    except Exception as exc:
        print("FINAL_POST_DOWNLOAD_FAILED", exc)
        return False


def _duration(path: Path) -> float:
    try:
        p = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        data = json.loads(p.stdout or "{}")
        return float(data.get("format", {}).get("duration") or 0)
    except Exception:
        return 0.0


def _split_script(script: str, count: int) -> List[str]:
    parts = [x.strip() for x in re.split(r"[。！？!?；;\n]+", script or "") if x.strip()]
    if not parts:
        return []
    if len(parts) >= count:
        return parts[:count]
    while len(parts) < count:
        parts.append(parts[-1])
    return parts


def _srt_time(t: float) -> str:
    t = max(0.0, float(t))
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int(round((t - int(t)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _write_srt(script: str, duration: float, srt_path: Path) -> bool:
    segments = _split_script(script, max(1, round(duration / 3.5)))
    if not segments:
        return False

    each = max(1.2, duration / len(segments))
    lines = []
    for i, text in enumerate(segments, start=1):
        start = (i - 1) * each
        end = min(duration + 0.2, i * each)
        lines.append(str(i))
        lines.append(f"{_srt_time(start)} --> {_srt_time(end)}")
        lines.append(text)
        lines.append("")

    srt_path.write_text("\n".join(lines), encoding="utf-8")
    return True


def _burn_subtitles_and_tail(input_video: Path, script_text: str, output_video: Path) -> bool:
    dur = _duration(input_video)
    if dur <= 0:
        return False

    # 多留 1.2 秒尾巴，避免最后一句像被切断
    target = dur + 1.2
    srt_path = output_video.with_suffix(".srt")
    has_srt = _write_srt(script_text, dur, srt_path)

    vf = [
        "scale=1080:1920:force_original_aspect_ratio=cover",
        "crop=1080:1920",
        "setsar=1",
    ]

    if has_srt:
        # 字幕样式：底部短视频常规安全区
        safe_srt = str(srt_path).replace(":", "\\:").replace("'", "\\'")
        vf.append(
            f"subtitles='{safe_srt}':force_style='FontName=Arial,FontSize=9,PrimaryColour=&H00FFFFFF,OutlineColour=&H80000000,BorderStyle=1,Outline=2,Shadow=1,Alignment=2,MarginV=140'"
        )

    vf_arg = ",".join(vf)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_video),
        "-filter_complex",
        f"[0:v]{vf_arg},tpad=stop_mode=clone:stop_duration=1.2[v];[0:a]apad=pad_dur=1.2,afade=t=out:st={max(0.1, dur-0.15):.2f}:d=1.1[a]",
        "-map", "[v]",
        "-map", "[a]",
        "-t", f"{target:.3f}",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-r", "30",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        str(output_video),
    ]

    p = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if p.returncode != 0:
        print("FINAL_POST_FFMPEG_FAILED", p.stderr[-2000:])
        return False

    return output_video.exists() and output_video.stat().st_size > 1024


def _find_video_url(obj: Any) -> str:
    if isinstance(obj, dict):
        for k in ("video_url", "output_url", "result_url", "url"):
            v = obj.get(k)
            if isinstance(v, str) and v.startswith("http"):
                return v
        for v in obj.values():
            found = _find_video_url(v)
            if found:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = _find_video_url(v)
            if found:
                return found
    return ""


def _extract_script(obj: Any) -> str:
    if isinstance(obj, dict):
        for k in ("script_text", "script", "copy", "text"):
            v = obj.get(k)
            if isinstance(v, str) and len(v.strip()) > 8:
                return v.strip()
        for v in obj.values():
            found = _extract_script(v)
            if found:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = _extract_script(v)
            if found:
                return found
    return ""


def install_full_ai_postprocess_guard(app: FastAPI) -> None:
    @app.middleware("http")
    async def postprocess_tts_first_job_response(request: Request, call_next):
        response = await call_next(request)

        # 只处理 tts-first job 查询结果；不影响生成接口
        if request.method.upper() != "GET" or "/api/video/full-ai/tts-first/job/" not in request.url.path:
            return response

        try:
            body = b""
            async for chunk in response.body_iterator:
                body += chunk

            data = json.loads(body.decode("utf-8") or "{}")

            status_text = f"{data.get('status','')} {data.get('stage','')} {data.get('child_job',{}).get('status','')} {data.get('child_job',{}).get('stage','')}".lower()
            if not any(x in status_text for x in ["completed", "success", "succeeded", "done", "finished"]):
                return JSONResponse(data, status_code=response.status_code, headers=dict(response.headers))

            video_url = _find_video_url(data)
            script_text = _extract_script(data)

            if not video_url or not script_text:
                return JSONResponse(data, status_code=response.status_code, headers=dict(response.headers))

            job_id = str(data.get("job_id") or request.url.path.rsplit("/", 1)[-1])
            final_path = DATA_DIR / f"{job_id}_subtitled_tail.mp4"

            if not final_path.exists():
                src_path = DATA_DIR / f"{job_id}_source.mp4"
                if _download(video_url, src_path):
                    ok = _burn_subtitles_and_tail(src_path, script_text, final_path)
                    print(f"FINAL_POSTPROCESS_SUBTITLE_TAIL job={job_id} ok={ok} source={video_url}")

            if final_path.exists():
                # 先返回本机可访问路径。R2 上传如果你已有统一 upload provider，下一步再接。
                data["postprocessed"] = True
                data["subtitle_burned"] = True
                data["tail_padding_seconds"] = 1.2
                data["local_video_path"] = str(final_path)
                data["final_video_url_note"] = "字幕尾巴版已在服务器生成；如需公网 URL，需要接入现有 R2/storage 上传函数。"
        except Exception as exc:
            print("FINAL_POSTPROCESS_GUARD_FAILED", exc)

        return JSONResponse(data, status_code=response.status_code, headers=dict(response.headers))
