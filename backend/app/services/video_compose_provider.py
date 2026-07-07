# V10_27L_FINAL_FAL_PROMPT_PURGE
# AI_VIDEO_V10_27K_BUILD_PROMPT_KWARGS_FIX
from __future__ import annotations

import os
import time
import uuid
import json
import shutil
import mimetypes
import tempfile
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests


def make_compose_job_id(prefix: str = "compose") -> str:
    return prefix + "_" + uuid.uuid4().hex[:18]


def run_cmd(cmd: List[str]) -> None:
    cp = subprocess.run(cmd, text=True, capture_output=True)
    if cp.returncode != 0:
        raise RuntimeError(
            "Command failed:\n"
            + " ".join(cmd)
            + "\nSTDOUT:\n"
            + (cp.stdout or "")[-3000:]
            + "\nSTDERR:\n"
            + (cp.stderr or "")[-5000:]
        )


def download_file(url: str, out_path: Path) -> None:
    with requests.get(url, stream=True, timeout=180) as r:
        r.raise_for_status()
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)


def normalize_clip(input_path: Path, output_path: Path, width: int = 1080, height: int = 1920, fps: int = 30) -> None:
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
        f"setsar=1,fps={fps},format=yuv420p"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-vf", vf,
        "-an",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
        "-movflags", "+faststart",
        str(output_path),
    ]
    run_cmd(cmd)


def concat_clips(normalized_paths: List[Path], output_path: Path) -> None:
    list_file = output_path.parent / "concat_list.txt"

    with open(list_file, "w", encoding="utf-8") as f:
        for p in normalized_paths:
            f.write(f"file '{p.as_posix()}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(list_file),
        "-c", "copy",
        "-movflags", "+faststart",
        str(output_path),
    ]
    run_cmd(cmd)


def add_audio(video_path: Path, audio_url: str, output_path: Path) -> None:
    audio_path = video_path.parent / "voice_audio"
    download_file(audio_url, audio_path)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(audio_path),
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-shortest",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        str(output_path),
    ]
    run_cmd(cmd)


def r2_configured() -> bool:
    return bool(
        (os.getenv("R2_BUCKET") or os.getenv("R2_BUCKET_NAME") or os.getenv("CLOUDFLARE_R2_BUCKET"))
        and (os.getenv("R2_ACCESS_KEY_ID") or os.getenv("CLOUDFLARE_R2_ACCESS_KEY_ID") or os.getenv("AWS_ACCESS_KEY_ID"))
        and (os.getenv("R2_SECRET_ACCESS_KEY") or os.getenv("CLOUDFLARE_R2_SECRET_ACCESS_KEY") or os.getenv("AWS_SECRET_ACCESS_KEY"))
        and (
            os.getenv("R2_ENDPOINT_URL")
            or os.getenv("CLOUDFLARE_R2_ENDPOINT")
            or os.getenv("R2_ACCOUNT_ID")
            or os.getenv("CLOUDFLARE_ACCOUNT_ID")
        )
    )


def upload_to_r2(local_path: Path, key: str) -> Dict[str, Any]:
    import boto3

    bucket = os.getenv("R2_BUCKET") or os.getenv("R2_BUCKET_NAME") or os.getenv("CLOUDFLARE_R2_BUCKET")
    access_key = os.getenv("R2_ACCESS_KEY_ID") or os.getenv("CLOUDFLARE_R2_ACCESS_KEY_ID") or os.getenv("AWS_ACCESS_KEY_ID")
    secret_key = os.getenv("R2_SECRET_ACCESS_KEY") or os.getenv("CLOUDFLARE_R2_SECRET_ACCESS_KEY") or os.getenv("AWS_SECRET_ACCESS_KEY")

    endpoint = os.getenv("R2_ENDPOINT_URL") or os.getenv("CLOUDFLARE_R2_ENDPOINT")
    account_id = os.getenv("R2_ACCOUNT_ID") or os.getenv("CLOUDFLARE_ACCOUNT_ID")

    if not endpoint and account_id:
        endpoint = f"https://{account_id}.r2.cloudflarestorage.com"

    public_base = (
        os.getenv("R2_PUBLIC_BASE_URL")
        or os.getenv("R2_PUBLIC_BASE")
        or os.getenv("PUBLIC_R2_BASE_URL")
        or os.getenv("R2_PUBLIC_URL")
        or ""
    ).rstrip("/")

    if not all([bucket, access_key, secret_key, endpoint]):
        return {
            "ok": False,
            "uploaded": False,
            "error": "R2 env not fully configured",
            "local_path": str(local_path),
        }

    content_type = mimetypes.guess_type(str(local_path))[0] or "application/octet-stream"

    s3 = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
    )

    s3.upload_file(
        str(local_path),
        bucket,
        key,
        ExtraArgs={"ContentType": content_type},
    )

    public_url = f"{public_base}/{key}" if public_base else ""

    return {
        "ok": True,
        "uploaded": True,
        "bucket": bucket,
        "key": key,
        "public_url": public_url,
        "local_path": str(local_path),
    }


def compose_video_urls(
    video_urls: List[str],
    title: str = "full_ai_video",
    audio_url: Optional[str] = None,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
    upload: bool = True,
    folder: str = "videos/full-ai",
) -> Dict[str, Any]:
    if not video_urls:
        raise ValueError("video_urls is empty")

    started = time.time()
    safe_id = uuid.uuid4().hex[:12]
    workdir = Path(tempfile.mkdtemp(prefix=f"compose_{safe_id}_"))

    raw_paths: List[Path] = []
    norm_paths: List[Path] = []

    try:
        for idx, url in enumerate(video_urls, start=1):
            raw = workdir / f"raw_{idx:02d}.mp4"
            norm = workdir / f"norm_{idx:02d}.mp4"

            download_file(url, raw)
            normalize_clip(raw, norm, width=width, height=height, fps=fps)

            raw_paths.append(raw)
            norm_paths.append(norm)

        stitched = workdir / "stitched_no_audio.mp4"
        concat_clips(norm_paths, stitched)

        final_path = stitched
        if audio_url:
            final_path = workdir / "final_with_audio.mp4"
            add_audio(stitched, audio_url, final_path)

        result: Dict[str, Any] = {
            "ok": True,
            "title": title,
            "clip_count": len(video_urls),
            "width": width,
            "height": height,
            "fps": fps,
            "audio_attached": bool(audio_url),
            "local_path": str(final_path),
            "file_size": final_path.stat().st_size,
            "elapsed_seconds": round(time.time() - started, 2),
        }

        if upload:
            key = f"{folder.strip('/')}/full_ai_{time.strftime('%Y%m%d_%H%M%S')}_{safe_id}.mp4"
            result["r2"] = upload_to_r2(final_path, key)

        return result

    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "workdir": str(workdir),
            "video_urls": video_urls,
        }


# ================= AI VIDEO V10.27I RUNTIME PROMPT CLEANER =================
def _v10_27k_clean_prompt_text(_v10_27k_text):
    try:
        import re as _v10_27k_re
        t = str(_v10_27k_text or '')
        patterns = [
            r"\s*,\s*,\s*no readable text signs,\s*(?:gentle pull out|slow left to right pan|steady street-level dolly|slow push in),\s*cinematic vertical 9:16,\s*realistic Malaysia property lifestyle,\s*no text,\s*no logos,\s*no subtitles,\s*no readable signs",
            r"\s*,\s*,\s*no readable text signs",
            r",\s*no readable text signs,\s*(?:gentle pull out|slow left to right pan|steady street-level dolly|slow push in),\s*cinematic vertical 9:16,\s*realistic Malaysia property lifestyle,\s*no text,\s*no logos,\s*no subtitles,\s*no readable signs",
            r"",
        ]
        old=t
        for pat in patterns:
            t=_v10_27k_re.sub(pat, '', t, flags=_v10_27k_re.I)
        t=_v10_27k_re.sub(r'\s+,', ',', t)
        t=_v10_27k_re.sub(r'\s{2,}', ' ', t).strip(',')
        if old != t:
            print('V10_27K_PURGED_GLOBAL_TRAFFIC_PROMPT_TEXT')
        return t
    except Exception:
        return _v10_27k_text

def _v10_27k_clean_prompt_obj(_v10_27k_obj, _v10_27k_seen=None):
    try:
        if _v10_27k_seen is None:
            _v10_27k_seen=set()
        oid=id(_v10_27k_obj)
        if oid in _v10_27k_seen:
            return _v10_27k_obj
        _v10_27k_seen.add(oid)
        if isinstance(_v10_27k_obj, str):
            return _v10_27k_clean_prompt_text(_v10_27k_obj)
        if isinstance(_v10_27k_obj, dict):
            for k in list(_v10_27k_obj.keys()):
                v=_v10_27k_obj.get(k)
                kl=str(k).lower()
                if isinstance(v, str) and any(x in kl for x in ['prompt','visual','image_prompt','text_prompt','description']):
                    _v10_27k_obj[k]=_v10_27k_clean_prompt_text(v)
                else:
                    _v10_27k_obj[k]=_v10_27k_clean_prompt_obj(v, _v10_27k_seen)
            # keep metadata visible for job JSON / health checks
            if any(k in _v10_27k_obj for k in ['visual_prompt','prompt','semantic_type','scene_type','shot_id']):
                _v10_27k_obj['runtime_prompt_cleaner']='v10_27k'
            return _v10_27k_obj
        if isinstance(_v10_27k_obj, list):
            for i,v in enumerate(list(_v10_27k_obj)):
                _v10_27k_obj[i]=_v10_27k_clean_prompt_obj(v, _v10_27k_seen)
            return _v10_27k_obj
        if isinstance(_v10_27k_obj, tuple):
            for v in _v10_27k_obj:
                _v10_27k_clean_prompt_obj(v, _v10_27k_seen)
            return _v10_27k_obj
    except Exception as _v10_27k_exc:
        try: print('V10_27K_CLEAN_PROMPT_OBJ_FAILED='+str(_v10_27k_exc))
        except Exception: pass
    return _v10_27k_obj

def _v10_27k_wrap_callable(_v10_27k_name, _v10_27k_fn):
    try:
        import inspect as _v10_27k_inspect, functools as _v10_27k_functools
        if getattr(_v10_27k_fn, '_v10_27k_wrapped', False):
            return _v10_27k_fn
        if _v10_27k_inspect.iscoroutinefunction(_v10_27k_fn):
            @_v10_27k_functools.wraps(_v10_27k_fn)
            async def _v10_27k_async_wrapped(*args, **kwargs):
                _v10_27k_clean_prompt_obj(args); _v10_27k_clean_prompt_obj(kwargs)
                res = await _v10_27k_fn(*args, **kwargs)
                _v10_27k_clean_prompt_obj(args); _v10_27k_clean_prompt_obj(kwargs)
                return _v10_27k_clean_prompt_obj(res)
            _v10_27k_async_wrapped._v10_27k_wrapped=True
            return _v10_27k_async_wrapped
        @_v10_27k_functools.wraps(_v10_27k_fn)
        def _v10_27k_sync_wrapped(*args, **kwargs):
            _v10_27k_clean_prompt_obj(args); _v10_27k_clean_prompt_obj(kwargs)
            res = _v10_27k_fn(*args, **kwargs)
            _v10_27k_clean_prompt_obj(args); _v10_27k_clean_prompt_obj(kwargs)
            return _v10_27k_clean_prompt_obj(res)
        _v10_27k_sync_wrapped._v10_27k_wrapped=True
        return _v10_27k_sync_wrapped
    except Exception:
        return _v10_27k_fn

def _v10_27k_install_runtime_prompt_cleaner():
    try:
        _targets = ('prompt','guard','fal','render','video','shot','semantic','start','generate','compose')
        _count=0
        for _name,_fn in list(globals().items()):
            if _name.startswith('_v10_27k_'):
                continue
            if not callable(_fn):
                continue
            lname=_name.lower()
            if any(t in lname for t in _targets):
                globals()[_name]=_v10_27k_wrap_callable(_name,_fn)
                _count+=1
        print('V10_27K_RUNTIME_PROMPT_CLEANER_INSTALLED='+str({'module':__name__,'wrapped':_count}))
    except Exception as _v10_27k_exc:
        print('V10_27K_RUNTIME_PROMPT_CLEANER_INSTALL_FAILED='+str(_v10_27k_exc))

_v10_27k_install_runtime_prompt_cleaner()
# ================= END AI VIDEO V10.27I RUNTIME PROMPT CLEANER =================
