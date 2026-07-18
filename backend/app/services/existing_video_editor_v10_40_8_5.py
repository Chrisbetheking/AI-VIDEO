from __future__ import annotations

import asyncio, hashlib, json, re, shutil, subprocess, threading, uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx
from fastapi import Depends, HTTPException, Request

from app.schemas import VoiceSegment
from app.services.storage import maybe_upload_to_r2
from app.services.subtitle_style_library_provider import burn_subtitles_with_style_and_upload
from app.services.tts import synthesize_tts_segments

VERSION = "10.40.8.5"
INSTALL_MARKER = "existing_video_smart_edit_v10_40_8_5"
_LOCK = threading.RLock()
_INSTALLED = False
_ACTIVE: set[str] = set()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _jobs_path(settings: Any) -> Path:
    return settings.data_dir / "existing_video_edit_jobs.json"


def _load_jobs(settings: Any) -> dict[str, dict[str, Any]]:
    p = _jobs_path(settings)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_jobs(settings: Any, jobs: dict[str, dict[str, Any]]) -> None:
    p = _jobs_path(settings)
    p.parent.mkdir(parents=True, exist_ok=True)
    t = p.with_suffix(".tmp")
    t.write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")
    t.replace(p)


def _update_job(settings: Any, job_id: str, **patch: Any) -> dict[str, Any]:
    with _LOCK:
        jobs = _load_jobs(settings)
        item = dict(jobs.get(job_id) or {"job_id": job_id, "version": VERSION})
        item.update(patch)
        item["updated_at"] = _now()
        jobs[job_id] = item
        _save_jobs(settings, jobs)
        return dict(item)


def _split_script(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if not text:
        return []
    parts = [x.strip(" ，,。！？!?；;") for x in re.split(r"(?<=[。！？!?；;])|\n+", text) if x.strip(" ，,。！？!?；;")]
    if len(parts) == 1 and len(parts[0]) > 32:
        raw = parts[0]
        parts = [raw[i:i+22] for i in range(0, len(raw), 22)]
    return parts[:30]


def _tokens(text: str) -> set[str]:
    text = str(text or "").lower()
    words = re.findall(r"[a-z0-9_]{2,}|[\u4e00-\u9fff]{2,}", text)
    zh = "".join(re.findall(r"[\u4e00-\u9fff]", text))
    words += [zh[i:i+2] for i in range(max(0, len(zh)-1))]
    stop = {"这个", "一个", "我们", "就是", "可以", "视频", "素材", "画面", "项目", "介绍", "相关"}
    return {w for w in words if w not in stop}


def _asset_text(asset: dict[str, Any]) -> str:
    intel = asset.get("asset_intelligence") or asset.get("intelligence") or {}
    fields = [asset.get("original_name"), asset.get("filename"), asset.get("ai_title"), asset.get("ai_description"),
              asset.get("ai_primary_category"), asset.get("ai_secondary_category"), intel.get("title"), intel.get("description"),
              intel.get("primary_category"), intel.get("secondary_category"), intel.get("location"), intel.get("scene"),
              " ".join(asset.get("ai_keywords") or []), " ".join(intel.get("keywords") or [])]
    return " ".join(str(x or "") for x in fields)


def _score(segment: str, asset: dict[str, Any], reuse: int) -> float:
    a = _tokens(segment)
    b = _tokens(_asset_text(asset))
    intel = asset.get("asset_intelligence") or asset.get("intelligence") or {}
    quality = float(asset.get("ai_quality_score") or intel.get("quality_score") or 60)
    clean = intel.get("cleanliness") or asset.get("ai_cleanliness") or {}
    clean_bonus = -100 if str(clean.get("status") or "").lower() == "failed" else 5
    return len(a & b) * 9 + sum(1 for token in a if token in _asset_text(asset).lower()) * 3 + quality / 20 + clean_bonus - reuse * 7


def _durations(parts: list[str], target: float) -> list[float]:
    target = max(len(parts) * 1.4, float(target or 15))
    weights = [max(4, len(re.sub(r"\s+", "", p))) for p in parts]
    total = sum(weights)
    values = [max(1.2, target * w / total) for w in weights]
    scale = target / sum(values)
    values = [max(1.0, v * scale) for v in values]
    values[-1] += target - sum(values)
    return [round(v, 3) for v in values]


def build_edit_plan(payload: dict[str, Any]) -> dict[str, Any]:
    script = str(payload.get("script_text") or payload.get("script") or "").strip()
    parts = [str(x.get("text") or "").strip() for x in (payload.get("script_segments") or []) if isinstance(x, dict) and str(x.get("text") or "").strip()] or _split_script(script)
    if not parts:
        raise ValueError("缺少口播文案，无法匹配现有视频")
    assets = [dict(x) for x in (payload.get("selected_assets") or payload.get("asset_context") or []) if isinstance(x, dict) and str(x.get("kind") or "").lower() == "video" and str(x.get("url") or x.get("r2_url") or "").strip()]
    if not assets:
        raise ValueError("没有选择视频素材。请先在素材库把视频带入当前视频")
    reuse: dict[str, int] = {}
    clips: list[dict[str, Any]] = []
    for idx, (part, duration) in enumerate(zip(parts, _durations(parts, float(payload.get("target_duration_seconds") or 30))), start=1):
        ranked = sorted(assets, key=lambda a: _score(part, a, reuse.get(str(a.get("id") or ""), 0)), reverse=True)
        chosen = ranked[0]
        aid = str(chosen.get("id") or chosen.get("filename") or idx)
        reuse[aid] = reuse.get(aid, 0) + 1
        intel = chosen.get("asset_intelligence") or chosen.get("intelligence") or {}
        title = str(chosen.get("ai_title") or intel.get("title") or chosen.get("original_name") or chosen.get("filename") or f"素材{idx}")
        desc = str(chosen.get("ai_description") or intel.get("description") or title)
        clips.append({"id": f"existing_clip_{idx}", "index": idx, "title": title, "scene": desc, "description": desc,
                      "narration": part, "duration": duration, "duration_seconds": duration, "source": "r2", "asset_id": aid,
                      "asset_ids": [aid], "asset_url": str(chosen.get("url") or chosen.get("r2_url") or ""),
                      "asset_name": str(chosen.get("original_name") or chosen.get("filename") or title), "start_time": 0.0,
                      "end_time": duration, "auto_start": True, "preserve_audio": str(payload.get("voice_mode") or "tts_with_ambient") != "tts_only",
                      "speed": 1.0, "transition": "轻柔淡化", "camera": "保留原片运镜",
                      "match_score": round(_score(part, chosen, max(0, reuse[aid]-1)), 2), "analysis_description": desc})
    return {"ok": True, "version": VERSION, "mode": "existing_edit", "fal_used": False,
            "message": f"已用 {len(assets)} 个现有视频匹配 {len(clips)} 个剪辑片段", "clips": clips,
            "selected_video_count": len(assets), "target_duration_seconds": round(sum(x["duration"] for x in clips), 3)}


def _run(cmd: list[str], timeout: int = 1800) -> subprocess.CompletedProcess[str]:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout or "命令执行失败")[-3000:])
    return p


def _probe(path: Path) -> dict[str, Any]:
    p = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height", "-of", "json", str(path)], 60)
    data = json.loads(p.stdout or "{}")
    streams = data.get("streams") or []
    video = next((x for x in streams if x.get("codec_type") == "video"), {})
    try: duration = float((data.get("format") or {}).get("duration") or 0)
    except Exception: duration = 0.0
    return {"duration": duration, "width": int(video.get("width") or 0), "height": int(video.get("height") or 0),
            "has_audio": any(x.get("codec_type") == "audio" for x in streams)}


async def _download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(timeout=httpx.Timeout(1800, connect=30), follow_redirects=True) as client:
        async with client.stream("GET", url) as r:
            r.raise_for_status()
            with dest.open("wb") as f:
                async for chunk in r.aiter_bytes(1024*1024):
                    if chunk: f.write(chunk)
    if dest.stat().st_size < 1024: raise RuntimeError(f"素材下载失败：{url}")
    return dest


def _size(ratio: str) -> tuple[int, int]:
    return (1920, 1080) if ratio == "16:9" else (1080, 1080) if ratio == "1:1" else (1080, 1920)


def _stable_start(asset_id: str, total: float, needed: float) -> float:
    available = max(0.0, total - needed - 0.15)
    if available <= 0.05: return 0.0
    seed = int(hashlib.sha256(asset_id.encode()).hexdigest()[:8], 16)
    return round((seed % 10000) / 10000 * available, 3)


def _normalize_clip(src: Path, dst: Path, *, start: float, duration: float, speed: float, width: int, height: int, keep_audio: bool) -> None:
    info = _probe(src); speed = max(.75, min(1.5, float(speed or 1))); duration = max(1.0, float(duration)); need = duration * speed
    start = max(0.0, min(start, max(0.0, float(info["duration"] or need)-need)))
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{start:.3f}", "-t", f"{need:.3f}", "-i", str(src),
           "-f", "lavfi", "-t", f"{duration:.3f}", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
    vf = f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1,fps=30,setpts=PTS/{speed:.5f},fade=t=in:st=0:d=0.12,fade=t=out:st={max(0,duration-.12):.3f}:d=0.12[v]"
    af = f"[0:a]atrim=0:{need:.3f},asetpts=N/SR/TB,atempo={speed:.5f},aresample=44100,volume=0.22[a]" if keep_audio and info["has_audio"] else "[1:a]anull[a]"
    cmd += ["-filter_complex", f"{vf};{af}", "-map", "[v]", "-map", "[a]", "-t", f"{duration:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2", "-movflags", "+faststart", str(dst)]
    _run(cmd)


def _concat(clips: list[Path], dst: Path) -> None:
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    for x in clips: cmd += ["-i", str(x)]
    refs = "".join(f"[{i}:v:0][{i}:a:0]" for i in range(len(clips)))
    cmd += ["-filter_complex", f"{refs}concat=n={len(clips)}:v=1:a=1[v][a]", "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(dst)]
    _run(cmd, 3600)


def _mix(base: Path, tts: Path | None, mode: str, dst: Path) -> None:
    if mode == "retain_original" or not tts:
        shutil.copy2(base, dst); return
    af = "[0:a]volume=0.16[amb];[1:a]volume=1,apad[voice];[amb][voice]amix=inputs=2:duration=first:normalize=0[a]" if mode == "tts_with_ambient" else "[1:a]volume=1,apad[a]"
    _run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(base), "-i", str(tts), "-filter_complex", af, "-map", "0:v:0", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(dst)])


def _url(settings: Any, path: Path, prefix: str) -> str:
    return maybe_upload_to_r2(settings, path, prefix=prefix) or f"/files/outputs/{path.name}"


def _voice_segments(payload: dict[str, Any], parts: list[str]) -> list[VoiceSegment]:
    raw = payload.get("script_segments") or []; settings_map = payload.get("segment_voice_settings") or {}; result = []
    for i, text in enumerate(parts, 1):
        item = raw[i-1] if i-1 < len(raw) and isinstance(raw[i-1], dict) else {}; v = settings_map.get(str(item.get("id") or f"seg_{i}")) or {}
        result.append(VoiceSegment(text=text, emotion=str(v.get("emotion") or "自然可信"), speed_ratio=float(v.get("speed") or v.get("speed_ratio") or 1), volume_ratio=float(v.get("volume") or v.get("volume_ratio") or 1), pitch_ratio=float(v.get("pitch") or v.get("pitch_ratio") or 1), pause_after_ms=int(v.get("pauseAfter") or v.get("pause_after_ms") or 220)))
    return result


def _cues(parts: list[str], clips: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out=[]; cursor=0.0
    for i,text in enumerate(parts):
        d=float(clips[i].get("duration") or 2); out.append({"index":i+1,"text":text,"start":round(cursor,3),"end":round(cursor+d,3),"duration":round(d,3)}); cursor+=d
    return out


async def _render(settings: Any, job_id: str, payload: dict[str, Any]) -> None:
    work = settings.tmp_dir / "existing_video_edit" / job_id; work.mkdir(parents=True, exist_ok=True)
    try:
        plan = payload.get("edit_plan") if isinstance(payload.get("edit_plan"), dict) and payload["edit_plan"].get("clips") else build_edit_plan(payload)
        clips = [dict(x) for x in plan["clips"]]; parts=[str(x.get("narration") or "").strip() for x in clips]
        mode=str(payload.get("voice_mode") or "tts_with_ambient"); tts=None; warning=None
        _update_job(settings, job_id, status="running", stage="tts", progress=5, message="正在生成配音")
        if mode != "retain_original":
            tts, audio_duration, warning, timings = await synthesize_tts_segments(settings, _voice_segments(payload, parts), voice=str(payload.get("voice") or "") or None, overall_rate=str(payload.get("overall_rate") or "") or None)
            target=float(audio_duration)
        else:
            target=sum(float(x.get("duration") or 2) for x in clips); timings=_cues(parts, clips)
        original=max(.001,sum(float(x.get("duration") or 2) for x in clips)); factor=target/original
        for x in clips: x["duration"]=round(max(1,float(x.get("duration") or 2)*factor),3)
        clips[-1]["duration"] += target-sum(float(x["duration"]) for x in clips)
        if mode == "retain_original": timings=_cues(parts, clips)
        width,height=_size(str(payload.get("output_ratio") or "9:16")); cache={}; normalized=[]
        for pos,clip in enumerate(clips,1):
            _update_job(settings, job_id, stage="clip_render", progress=10+int((pos-1)/len(clips)*55), current_clip=pos, current_file=clip.get("asset_name"), message=f"正在剪辑 {pos}/{len(clips)}")
            url=str(clip.get("asset_url") or ""); key=hashlib.sha256(url.encode()).hexdigest()[:16]
            if url not in cache:
                suffix=Path(url.split("?",1)[0]).suffix or ".mp4"; cache[url]=await _download(url, work/"sources"/f"{key}{suffix}")
            src=cache[url]; info=_probe(src); d=float(clip["duration"]); speed=float(clip.get("speed") or 1); needed=d*speed
            start=_stable_start(str(clip.get("asset_id") or key), float(info["duration"] or needed), needed) if clip.get("auto_start",True) or float(clip.get("start_time") or 0)<=0 else float(clip.get("start_time") or 0)
            dst=work/"clips"/f"{pos:03d}.mp4"; dst.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(_normalize_clip, src, dst, start=start, duration=d, speed=speed, width=width, height=height, keep_audio=mode in {"retain_original","tts_with_ambient"} and clip.get("preserve_audio",True))
            clip["actual_start_time"]=start; clip["actual_end_time"]=round(start+needed,3); normalized.append(dst)
        _update_job(settings, job_id, stage="concat", progress=70, message="正在合并片段")
        base=settings.outputs_dir/f"{job_id}_clips.mp4"; await asyncio.to_thread(_concat, normalized, base)
        mixed=settings.outputs_dir/f"{job_id}_mixed.mp4"; _update_job(settings, job_id, stage="audio_mix", progress=80, message="正在混音"); await asyncio.to_thread(_mix, base, tts, mode, mixed)
        raw_url=_url(settings,mixed,"videos/existing-edit/raw"); audio_url=_url(settings,tts,"audio/existing-edit") if tts else ""; final_url=raw_url; subtitle_result=None
        if bool(payload.get("burn_subtitles",True)):
            _update_job(settings, job_id, stage="subtitle_burn", progress=90, message="正在烧录字幕")
            keywords=[str(x.get("value") or "") for x in (payload.get("keyword_insights") or []) if isinstance(x,dict) and x.get("value")]
            subtitle_result=await asyncio.to_thread(burn_subtitles_with_style_and_upload, video_path=str(mixed), text=str(payload.get("script_text") or ""), segments=timings, duration=target, style_id=str(payload.get("subtitle_style_id") or "douyin_pop"), keywords=keywords, prefix=f"{job_id}_subtitle", object_key=f"videos/existing-edit/subtitled/{datetime.now().strftime('%Y/%m/%d')}/{job_id}.mp4", subtitle_style=payload.get("subtitle_style") if isinstance(payload.get("subtitle_style"), dict) else None)
            final_url=str(subtitle_result.get("video_url") or subtitle_result.get("url") or raw_url)
        _update_job(settings, job_id, status="done", stage="finished", progress=100, message=f"现有视频智能剪辑完成：{len(clips)} 个片段，未调用 FAL", video_url=final_url, output_url=final_url, raw_video_url=raw_url, no_subtitle_video_url=raw_url, audio_url=audio_url, subtitled_video_url=final_url if subtitle_result else "", audio_duration_seconds=round(target,3), duration_seconds=round(sum(float(x["duration"]) for x in clips),3), shot_count=len(clips), clips=clips, edit_plan={**plan,"clips":clips}, timings=timings, tts_warning=warning, fal_used=False, billing_guard="existing_edit_no_fal", finished_at=_now())
    except Exception as exc:
        _update_job(settings, job_id, status="failed", stage="failed", progress=100, error=str(exc)[:3000], message=f"现有视频剪辑失败：{exc}", fal_used=False, finished_at=_now())
    finally:
        with _LOCK: _ACTIVE.discard(job_id)


def _thread(settings: Any, job_id: str, payload: dict[str, Any]) -> None:
    asyncio.run(_render(settings, job_id, payload))


def _start(settings: Any, payload: dict[str, Any]) -> dict[str, Any]:
    plan=payload.get("edit_plan") if isinstance(payload.get("edit_plan"),dict) and payload["edit_plan"].get("clips") else build_edit_plan(payload); payload={**payload,"edit_plan":plan}
    job_id=f"existing_edit_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"; job={"job_id":job_id,"job_type":"existing_video_edit","version":VERSION,"status":"queued","stage":"queued","progress":0,"message":"等待 ECS 后端剪辑现有视频","mode":"existing_edit","fal_used":False,"billing_guard":"existing_edit_no_fal","edit_plan":plan,"created_at":_now(),"updated_at":_now()}
    with _LOCK:
        jobs=_load_jobs(settings); jobs[job_id]=job; _save_jobs(settings,jobs); _ACTIVE.add(job_id)
    threading.Thread(target=_thread,args=(settings,job_id,dict(payload)),daemon=True,name=f"existing-edit-{job_id[-8:]}").start(); return job


def _repair(settings: Any) -> None:
    jobs=_load_jobs(settings); changed=False
    for item in jobs.values():
        if str(item.get("status") or "") in {"queued","running"}: item.update(status="failed",stage="recovered_after_restart",progress=100,error="后端重启导致剪辑中断，请重新发起；不会调用 FAL",finished_at=_now(),updated_at=_now()); changed=True
    if changed: _save_jobs(settings,jobs)


def install_existing_video_editor(app: Any, get_settings: Callable[..., Any]) -> None:
    global _INSTALLED
    if _INSTALLED or any(getattr(r,"path","")=="/api/video/existing-edit/health" for r in getattr(app,"routes",[])): _INSTALLED=True; return
    _repair(get_settings())
    @app.get("/api/video/existing-edit/health")
    def health(settings: Any=Depends(get_settings)):
        jobs=_load_jobs(settings); return {"ok":True,"version":VERSION,"mode":INSTALL_MARKER,"ffmpeg":bool(shutil.which("ffmpeg")),"ffprobe":bool(shutil.which("ffprobe")),"tts_provider":str(getattr(settings,"tts_provider","")),"r2_enabled":bool(getattr(settings,"r2_enabled",False)),"fal_used":False,"running_jobs":sum(1 for x in jobs.values() if x.get("status") in {"queued","running"}),"features":{"semantic_asset_match":True,"video_clip_trim":True,"vertical_crop":True,"tts":True,"ambient_mix":True,"subtitle_burn":True,"job_persistence":True}}
    @app.post("/api/video/existing-edit/plan")
    async def plan(request:Request):
        try:return build_edit_plan(await request.json())
        except ValueError as exc:raise HTTPException(status_code=400,detail=str(exc))
    @app.post("/api/video/existing-edit/start")
    async def start(request:Request,settings:Any=Depends(get_settings)):
        try:return _start(settings,await request.json())
        except ValueError as exc:raise HTTPException(status_code=400,detail=str(exc))
    @app.get("/api/video/existing-edit/jobs/latest")
    def latest(done_only:bool=False,settings:Any=Depends(get_settings)):
        items=list(_load_jobs(settings).values()); items=[x for x in items if not done_only or x.get("status")=="done"]; items.sort(key=lambda x:str(x.get("updated_at") or x.get("created_at") or ""),reverse=True); return {"ok":True,"version":VERSION,"job":items[0] if items else None}
    @app.get("/api/video/existing-edit/jobs")
    def jobs(limit:int=30,settings:Any=Depends(get_settings)):
        items=sorted(_load_jobs(settings).values(),key=lambda x:str(x.get("updated_at") or x.get("created_at") or ""),reverse=True); return {"ok":True,"version":VERSION,"jobs":items[:max(1,min(limit,100))]}
    @app.get("/api/video/existing-edit/jobs/{job_id}")
    def job(job_id:str,settings:Any=Depends(get_settings)):
        item=_load_jobs(settings).get(job_id)
        if not item:raise HTTPException(status_code=404,detail="现有视频剪辑任务不存在")
        return item
    _INSTALLED=True
