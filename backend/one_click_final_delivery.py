#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parent
BASE = os.getenv("AI_VIDEO_INTERNAL_BASE", "http://127.0.0.1:8000")
OUTDIR = BACKEND / "data" / "outputs"
OUTDIR.mkdir(parents=True, exist_ok=True)

def log(msg):
    print(msg, flush=True)

def post_json(path, payload, timeout=180):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        BASE + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))

def get_json(path, params=None, timeout=180):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))

def find_media_name(obj, exts):
    if isinstance(obj, dict):
        for k in ["file_name", "audio_file_name", "video_name", "name", "filename"]:
            v = obj.get(k)
            if isinstance(v, str) and v.lower().endswith(exts):
                return Path(v).name
        for v in obj.values():
            got = find_media_name(v, exts)
            if got:
                return got
    if isinstance(obj, list):
        for v in obj:
            got = find_media_name(v, exts)
            if got:
                return got
    if isinstance(obj, str) and obj.lower().endswith(exts):
        return Path(urllib.parse.urlparse(obj).path).name
    return ""

def download_if_needed(url, name_hint="source.mp4"):
    name = Path(urllib.parse.urlparse(url).path).name or name_hint
    dest = OUTDIR / name
    if dest.exists() and dest.stat().st_size > 1024:
        return dest
    log(f"下载视频到本地：{dest}")
    urllib.request.urlretrieve(url, dest)
    return dest

def run(cmd, timeout=900):
    log("RUN: " + " ".join(map(str, cmd)))
    p = subprocess.run(cmd, cwd=str(BACKEND), text=True, capture_output=True, timeout=timeout)
    if p.stdout:
        print(p.stdout, flush=True)
    if p.stderr:
        print(p.stderr, flush=True)
    if p.returncode != 0:
        raise RuntimeError(f"命令失败：{cmd}")
    return p

def upload_r2(video_path, cover_path):
    sys.path.insert(0, str(BACKEND))
    from app.config import get_settings
    from app.services.storage import maybe_upload_to_r2

    s = get_settings()
    video_url = maybe_upload_to_r2(s, video_path, prefix="videos/final-delivery")
    cover_url = maybe_upload_to_r2(s, cover_path, prefix="covers/final-delivery") if cover_path.exists() else ""
    return video_url or "", cover_url or ""

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", default="AI-VIDEO 正式交付视频")
    ap.add_argument("--text", default="")
    ap.add_argument("--avatar", default="avatar_template.mp4")
    ap.add_argument("--voice", default="default")
    ap.add_argument("--rate", default="0%")
    args = ap.parse_args()

    script = args.text.strip() or "来马来西亚买房，最怕的不是价格高，而是区域选错。同样是吉隆坡，有的地方租客稳定、转手容易；有的地方看起来便宜，后期却很难出租。真正稳的房子，不是销售说出来的，是市场长期验证出来的。"

    log("===== 1. TTS 配音 =====")
    tts = post_json("/api/tts", {"text": script, "voice": args.voice, "rate": args.rate})
    print(json.dumps(tts, ensure_ascii=False, indent=2), flush=True)
    audio_name = find_media_name(tts, (".mp3", ".wav", ".m4a"))
    if not audio_name:
        # 兜底找最新音频
        files = []
        for root in [BACKEND / "data" / "outputs", BACKEND / "outputs", BACKEND / "uploads"]:
            if root.exists():
                files += list(root.rglob("*.mp3")) + list(root.rglob("*.wav")) + list(root.rglob("*.m4a"))
        if files:
            audio_name = sorted(files)[-1].name
    if not audio_name:
        raise RuntimeError("没有拿到音频文件名")

    log(f"AUDIO_NAME={audio_name}")

    log("===== 2. fal.ai 数字人口播 =====")
    create = post_json("/api/digital-human/create", {
        "avatar_file_name": args.avatar,
        "audio_file_name": audio_name,
        "title": args.title,
        "script": script,
        "engine": "fal_lipsync",
        "consent_confirmed": True,
    }, timeout=300)
    print(json.dumps(create, ensure_ascii=False, indent=2), flush=True)

    video_url = create.get("video_url") or ""
    video_name = create.get("video_name") or find_media_name(create, (".mp4", ".mov", ".webm"))
    job_id = create.get("job_id") or ""

    if not video_url and job_id:
        log(f"===== 3. 轮询数字人任务：{job_id} =====")
        for i in range(1, 41):
            log(f"check {i}/40")
            status = get_json("/api/digital-human/status", {"job_id": job_id, "model": "fal_lipsync"}, timeout=180)
            print(json.dumps(status, ensure_ascii=False, indent=2), flush=True)
            video_url = status.get("video_url") or ""
            video_name = status.get("video_name") or find_media_name(status, (".mp4", ".mov", ".webm"))
            if video_url:
                break
            time.sleep(15)

    if not video_url:
        raise RuntimeError("数字人没有返回 video_url")

    log("===== 4. 准备本地源视频 =====")
    local_video = None
    if video_name:
        for root in [BACKEND / "data" / "outputs", BACKEND / "outputs"]:
            p = root / Path(video_name).name
            if p.exists() and p.stat().st_size > 1024:
                local_video = p
                break
    if local_video is None:
        local_video = download_if_needed(video_url, video_name or "digital_human_source.mp4")
    log(f"LOCAL_VIDEO={local_video}")

    log("===== 5. 生成 9:16 平台正式版 + 封面 =====")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    final_video = OUTDIR / f"final_delivery_{ts}.mp4"
    final_cover = OUTDIR / f"final_cover_{ts}.jpg"

    run([
        "ffmpeg", "-y", "-i", str(local_video),
        "-filter_complex",
        "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=24:1[bg];[0:v]scale=1080:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2[v]",
        "-map", "[v]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "160k",
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
        "-movflags", "+faststart",
        "-shortest", str(final_video)
    ])

    run(["ffmpeg", "-y", "-ss", "00:00:01", "-i", str(final_video), "-frames:v", "1", str(final_cover)])

    log("===== 6. 上传 R2 =====")
    final_video_url, final_cover_url = upload_r2(final_video, final_cover)

    result = {
        "ok": True,
        "title": args.title,
        "video_url": final_video_url,
        "cover_url": final_cover_url,
        "local_video": str(final_video),
        "local_cover": str(final_cover),
        "source_digital_human_url": video_url,
        "audio_name": audio_name,
    }
    print("FINAL_RESULT::" + json.dumps(result, ensure_ascii=False), flush=True)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        err = {"ok": False, "error": str(e)}
        print("FINAL_RESULT::" + json.dumps(err, ensure_ascii=False), flush=True)
        raise
