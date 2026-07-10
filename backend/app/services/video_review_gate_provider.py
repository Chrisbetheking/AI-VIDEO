from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest

import httpx
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

BASE = Path("/opt/ai-video")
STORAGE = BASE / "storage"
JOB_ROOT = STORAGE / "v10_34" / "final_jobs"
REVIEW_ROOT = STORAGE / "v10_34" / "video_reviews"
REVIEW_ROOT.mkdir(parents=True, exist_ok=True)

PACKAGING_PATHS = {
    "/api/graphic-window/video-cover/generate",
    "/api/graphic-window/xiaohongshu/generate",
}

_REVIEW_LOCK = threading.RLock()
_AUTO_REVIEW_TASK: asyncio.Task | None = None


def _now() -> float:
    return time.time()


def _json_load(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _json_save_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _job_path(job_id: str) -> Path:
    return JOB_ROOT / f"{job_id}.json"


def _review_path(job_id: str) -> Path:
    return REVIEW_ROOT / f"{job_id}.json"


def _load_job(job_id: str) -> dict[str, Any]:
    path = _job_path(job_id)
    if path.exists():
        data = _json_load(path)
        if data:
            data.setdefault("job_id", job_id)
            data["_job_file"] = str(path)
            return data
    return {}


def _save_job(job_id: str, job: dict[str, Any]) -> None:
    path = _job_path(job_id)
    if not path.exists():
        return
    clean = {k: v for k, v in job.items() if not str(k).startswith("_")}
    _json_save_atomic(path, clean)


def _load_review(job_id: str) -> dict[str, Any]:
    path = _review_path(job_id)
    if not path.exists():
        return {
            "ok": False,
            "job_id": job_id,
            "status": "not_reviewed",
            "approved": False,
            "packaging_unlocked": False,
        }
    data = _json_load(path)
    data.setdefault("job_id", job_id)
    data.setdefault("approved", data.get("status") == "approved")
    data.setdefault("packaging_unlocked", data.get("status") == "approved")
    return data


def _save_review(job_id: str, report: dict[str, Any]) -> dict[str, Any]:
    report["job_id"] = job_id
    report["updated_at"] = _now()
    _json_save_atomic(_review_path(job_id), report)
    return report


def _is_completed(job: dict[str, Any]) -> bool:
    raw = f"{job.get('status', '')} {job.get('stage', '')}".lower()
    return any(x in raw for x in ("completed", "finished", "done", "success", "succeeded"))


def _latest_completed_job() -> dict[str, Any]:
    files = sorted(JOB_ROOT.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in files:
        data = _json_load(path)
        if data and _is_completed(data):
            data.setdefault("job_id", path.stem)
            data["_job_file"] = str(path)
            return data
    return {}


def _deep_values(obj: Any, wanted: set[str]) -> list[Any]:
    found: list[Any] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            if str(key).lower() in wanted:
                found.append(value)
            found.extend(_deep_values(value, wanted))
    elif isinstance(obj, list):
        for value in obj:
            found.extend(_deep_values(value, wanted))
    return found


def _first_text(obj: Any, keys: list[str]) -> str:
    values = _deep_values(obj, {x.lower() for x in keys})
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _job_script(job: dict[str, Any]) -> str:
    return _first_text(
        job,
        [
            "script_text",
            "script",
            "voiceover_script",
            "narration",
            "final_script",
            "tts_text",
        ],
    )[:12000]


def _job_title(job: dict[str, Any]) -> str:
    title = _first_text(job, ["topic", "title", "video_title"])
    return title or "AI 视频"


def _url_to_storage_path(url: str) -> Path | None:
    marker = "/storage/"
    if marker not in url:
        return None
    rel = url.split(marker, 1)[1].split("?", 1)[0].lstrip("/")
    path = STORAGE / rel
    return path if path.exists() else None


def _resolve_video(job: dict[str, Any]) -> tuple[Path | None, str]:
    url_keys = [
        "final_video_url",
        "video_url",
        "output_url",
        "public_url",
        "subtitled_video_url",
    ]
    path_keys = [
        "local_path",
        "final_local_path",
        "video_path",
        "output_path",
    ]

    local_candidates: list[Path] = []
    for raw in _deep_values(job, {x.lower() for x in path_keys}):
        if isinstance(raw, str) and raw.strip():
            p = Path(raw.strip())
            if p.exists() and p.suffix.lower() in {".mp4", ".mov", ".m4v", ".webm"}:
                local_candidates.append(p)

    public_url = ""
    for raw in _deep_values(job, {x.lower() for x in url_keys}):
        if not isinstance(raw, str) or not raw.strip():
            continue
        value = raw.strip()
        if value.startswith(("http://", "https://")):
            if not public_url:
                public_url = value
            mapped = _url_to_storage_path(value)
            if mapped:
                local_candidates.append(mapped)

    # Prefer final subtitled outputs over raw intermediary clips.
    def rank(path: Path) -> tuple[int, float]:
        low = str(path).lower()
        score = 0
        if "final" in low:
            score += 30
        if "subtitle" in low or "script_locked" in low or "asr_aligned" in low:
            score += 20
        if "clean_video" in low or "video_fit_audio_length" in low:
            score -= 15
        try:
            mtime = path.stat().st_mtime
        except Exception:
            mtime = 0.0
        return score, mtime

    local = max(local_candidates, key=rank) if local_candidates else None
    return local, public_url


def _run(cmd: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _parse_rate(value: str) -> float:
    try:
        if "/" in value:
            a, b = value.split("/", 1)
            return float(a) / max(float(b), 1e-9)
        return float(value)
    except Exception:
        return 0.0


def _probe_video(path: Path) -> dict[str, Any]:
    proc = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ],
        timeout=90,
    )
    if proc.returncode != 0:
        return {"ok": False, "error": proc.stderr[-1200:] or "ffprobe failed"}

    try:
        payload = json.loads(proc.stdout or "{}")
    except Exception as exc:
        return {"ok": False, "error": f"invalid ffprobe json: {exc}"}

    streams = payload.get("streams") or []
    fmt = payload.get("format") or {}
    video_stream = next((x for x in streams if x.get("codec_type") == "video"), {})
    audio_stream = next((x for x in streams if x.get("codec_type") == "audio"), {})

    try:
        duration = float(fmt.get("duration") or video_stream.get("duration") or 0)
    except Exception:
        duration = 0.0

    return {
        "ok": bool(video_stream),
        "duration_seconds": round(duration, 3),
        "width": int(video_stream.get("width") or 0),
        "height": int(video_stream.get("height") or 0),
        "fps": round(_parse_rate(str(video_stream.get("avg_frame_rate") or "0")), 3),
        "video_codec": str(video_stream.get("codec_name") or ""),
        "audio_codec": str(audio_stream.get("codec_name") or ""),
        "has_video": bool(video_stream),
        "has_audio": bool(audio_stream),
        "size_bytes": int(fmt.get("size") or path.stat().st_size),
        "format_name": str(fmt.get("format_name") or ""),
    }


def _url_check(url: str) -> dict[str, Any]:
    if not url:
        return {
            "ok": False,
            "status": 0,
            "content_type": "",
            "error": "missing public video url",
        }

    headers = {"User-Agent": "AI-VIDEO-ReviewGate/1.0"}
    req = urlrequest.Request(url, headers=headers, method="HEAD")
    try:
        with urlrequest.urlopen(req, timeout=25) as resp:
            ctype = str(resp.headers.get("Content-Type") or "").lower()
            return {
                "ok": "video/" in ctype or "application/octet-stream" in ctype,
                "status": int(getattr(resp, "status", 200)),
                "content_type": ctype,
                "content_length": str(resp.headers.get("Content-Length") or ""),
            }
    except urlerror.HTTPError as exc:
        if exc.code not in {403, 405}:
            return {
                "ok": False,
                "status": exc.code,
                "content_type": "",
                "error": str(exc),
            }
    except Exception as exc:
        return {
            "ok": False,
            "status": 0,
            "content_type": "",
            "error": str(exc),
        }

    # Some nginx/FastAPI routes reject HEAD. Retry with a one-byte range GET.
    try:
        get_req = urlrequest.Request(
            url,
            headers={**headers, "Range": "bytes=0-0"},
            method="GET",
        )
        with urlrequest.urlopen(get_req, timeout=25) as resp:
            ctype = str(resp.headers.get("Content-Type") or "").lower()
            return {
                "ok": "video/" in ctype or "application/octet-stream" in ctype,
                "status": int(getattr(resp, "status", 200)),
                "content_type": ctype,
                "content_length": str(resp.headers.get("Content-Length") or ""),
            }
    except Exception as exc:
        return {
            "ok": False,
            "status": 0,
            "content_type": "",
            "error": str(exc),
        }


def _detect_black_and_freeze(path: Path, duration: float) -> dict[str, Any]:
    # Review at most the first 90 seconds. Current production videos are short.
    sample = max(1.0, min(duration or 60.0, 90.0))
    proc = _run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-t",
            f"{sample:.3f}",
            "-i",
            str(path),
            "-vf",
            "blackdetect=d=0.60:pix_th=0.10,freezedetect=n=-55dB:d=2.0",
            "-an",
            "-f",
            "null",
            "-",
        ],
        timeout=150,
    )
    raw = (proc.stderr or "")[-30000:]
    black_ranges = []
    for start, end, dur in re.findall(
        r"black_start:([0-9.]+)\s+black_end:([0-9.]+)\s+black_duration:([0-9.]+)",
        raw,
    ):
        black_ranges.append(
            {
                "start": float(start),
                "end": float(end),
                "duration": float(dur),
            }
        )

    freeze_starts = [float(x) for x in re.findall(r"freeze_start:\s*([0-9.]+)", raw)]
    freeze_ends = [float(x) for x in re.findall(r"freeze_end:\s*([0-9.]+)", raw)]
    freeze_ranges = []
    for i, start in enumerate(freeze_starts):
        end = freeze_ends[i] if i < len(freeze_ends) else None
        freeze_ranges.append(
            {
                "start": start,
                "end": end,
                "duration": round(end - start, 3) if end is not None else None,
            }
        )
    return {
        "black_ranges": black_ranges[:20],
        "freeze_ranges": freeze_ranges[:20],
        "ffmpeg_returncode": proc.returncode,
    }


def _check(name: str, passed: bool, severity: str, detail: str) -> dict[str, Any]:
    return {
        "name": name,
        "passed": bool(passed),
        "severity": severity,
        "detail": detail,
    }


def _expected_audio_duration(job: dict[str, Any]) -> float:
    values = _deep_values(
        job,
        {
            "audio_duration_seconds",
            "audio_duration",
            "tts_duration_seconds",
            "tts_duration",
        },
    )
    for value in values:
        try:
            number = float(value)
            if number > 0:
                return number
        except Exception:
            pass
    return 0.0


def _mechanical_review(job_id: str, job: dict[str, Any]) -> dict[str, Any]:
    local_path, public_url = _resolve_video(job)
    checks: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []

    if not local_path:
        checks.append(_check("local_video_exists", False, "critical", "找不到最终视频本地文件"))
        return {
            "passed": False,
            "score": 0,
            "local_path": "",
            "public_url": public_url,
            "probe": {},
            "url_check": _url_check(public_url),
            "checks": checks,
            "issues": [
                {
                    "type": "missing_video",
                    "severity": "critical",
                    "description": "找不到最终视频本地文件，无法进行机械质检",
                    "suggestion": "检查 job JSON 的 local_path/final_video_url 是否指向真实 MP4",
                }
            ],
        }

    probe = _probe_video(local_path)
    checks.append(
        _check(
            "local_video_exists",
            local_path.exists() and local_path.stat().st_size > 1024,
            "critical",
            str(local_path),
        )
    )
    checks.append(
        _check(
            "video_stream",
            bool(probe.get("has_video")),
            "critical",
            f"codec={probe.get('video_codec') or 'none'}",
        )
    )
    checks.append(
        _check(
            "audio_stream",
            bool(probe.get("has_audio")),
            "critical",
            f"codec={probe.get('audio_codec') or 'none'}",
        )
    )

    width = int(probe.get("width") or 0)
    height = int(probe.get("height") or 0)
    vertical = height > width and width >= 720 and height >= 1280
    checks.append(
        _check(
            "vertical_resolution",
            vertical,
            "high",
            f"{width}x{height}，要求竖屏且至少 720x1280",
        )
    )

    duration = float(probe.get("duration_seconds") or 0)
    checks.append(
        _check(
            "video_duration",
            duration >= 5,
            "critical",
            f"{duration:.3f}s",
        )
    )

    expected_audio = _expected_audio_duration(job)
    duration_delta = abs(duration - expected_audio) if expected_audio > 0 else None
    duration_match = duration_delta is None or duration_delta <= 1.0
    checks.append(
        _check(
            "audio_video_duration_match",
            duration_match,
            "critical" if duration_delta is not None and duration_delta > 2.0 else "high",
            (
                f"视频 {duration:.3f}s，配音 {expected_audio:.3f}s，误差 {duration_delta:.3f}s"
                if duration_delta is not None
                else "job 未记录配音时长，仅检查视频自身"
            ),
        )
    )

    url_result = _url_check(public_url)
    checks.append(
        _check(
            "public_url_is_video",
            bool(url_result.get("ok")),
            "critical",
            f"status={url_result.get('status')} content-type={url_result.get('content_type') or 'unknown'}",
        )
    )

    subtitle_source = str(
        job.get("subtitle_source")
        or (job.get("result") or {}).get("subtitle_source")
        or ""
    )
    source_locked = subtitle_source in {
        "original_tts_script_not_asr_text",
        "original_script",
        "script_locked",
    } or "script" in subtitle_source.lower()
    checks.append(
        _check(
            "subtitle_source_locked",
            source_locked,
            "medium",
            subtitle_source or "未记录 subtitle_source，需人工确认字幕是否来自原配音稿",
        )
    )

    artifact_scan = _detect_black_and_freeze(local_path, duration)
    black_total = sum(float(x.get("duration") or 0) for x in artifact_scan["black_ranges"])
    long_freezes = [
        x
        for x in artifact_scan["freeze_ranges"]
        if x.get("duration") is None or float(x.get("duration") or 0) >= 2.5
    ]
    checks.append(
        _check(
            "black_frame_scan",
            black_total <= 1.0,
            "high",
            f"累计黑帧 {black_total:.3f}s，区间 {artifact_scan['black_ranges'][:5]}",
        )
    )
    checks.append(
        _check(
            "freeze_scan",
            len(long_freezes) == 0,
            "medium",
            f"长静帧区间 {long_freezes[:5]}",
        )
    )

    for item in checks:
        if item["passed"]:
            continue
        issues.append(
            {
                "type": item["name"],
                "severity": item["severity"],
                "description": item["detail"],
                "suggestion": {
                    "audio_video_duration_match": "重新按准确配音时长拉伸或补齐视频，不重新调用 FAL",
                    "public_url_is_video": "修复 nginx /storage 映射，确保返回 video/mp4",
                    "subtitle_source_locked": "字幕文字锁定原配音稿，ASR 只提供时间轴",
                    "black_frame_scan": "检查拼接转场和空白片段",
                    "freeze_scan": "检查重复镜头或过长静止画面",
                }.get(item["name"], "修复该硬性检查后重新审查"),
            }
        )

    penalties = {
        "critical": 30,
        "high": 16,
        "medium": 7,
        "low": 3,
    }
    score = 100
    for item in checks:
        if not item["passed"]:
            score -= penalties.get(str(item["severity"]), 5)
    score = max(0, score)

    hard_failed = any(
        not item["passed"] and item["severity"] in {"critical", "high"}
        for item in checks
    )
    return {
        "passed": not hard_failed,
        "score": score,
        "local_path": str(local_path),
        "public_url": public_url,
        "probe": probe,
        "expected_audio_duration_seconds": expected_audio,
        "duration_delta_seconds": round(duration_delta, 3) if duration_delta is not None else None,
        "url_check": url_result,
        "artifact_scan": artifact_scan,
        "checks": checks,
        "issues": issues,
    }


def _settings_value(name: str, default: str = "") -> str:
    env_value = os.getenv(name, "").strip()
    if env_value:
        return env_value
    try:
        from app.config import Settings

        settings = Settings()
        attr = name.lower()
        value = getattr(settings, attr, "")
        resolved = str(value or "").strip()
        return resolved or default
    except Exception:
        return default


def _to_data_url(path: Path, max_mb: int = 28) -> str:
    size_mb = path.stat().st_size / 1024 / 1024
    if size_mb > max_mb:
        raise RuntimeError(f"视频 {size_mb:.1f}MB，超过内嵌上限 {max_mb}MB")
    mime = "video/webm" if path.suffix.lower() == ".webm" else "video/mp4"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def _json_from_model_text(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?", "", text, flags=re.I).strip()
    text = re.sub(r"```$", "", text).strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except Exception:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            raise
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else {}


async def _doubao_review(
    job: dict[str, Any],
    mechanical: dict[str, Any],
) -> dict[str, Any]:
    api_key = _settings_value("ARK_API_KEY")
    model = _settings_value("ARK_VIDEO_MODEL", "doubao-seed-2-0-lite")
    base_url = _settings_value(
        "ARK_BASE_URL",
        "https://ark.cn-beijing.volces.com/api/v3",
    ).rstrip("/")

    if not api_key or not model:
        return {
            "available": False,
            "passed": None,
            "score": None,
            "model": model,
            "error": "未配置 ARK_API_KEY 或 ARK_VIDEO_MODEL",
            "issues": [],
        }

    local_path = Path(str(mechanical.get("local_path") or ""))
    public_url = str(mechanical.get("public_url") or "")
    video_ref = public_url if mechanical.get("url_check", {}).get("ok") else ""
    if not video_ref and local_path.exists():
        try:
            video_ref = _to_data_url(local_path)
        except Exception as exc:
            return {
                "available": False,
                "passed": None,
                "score": None,
                "model": model,
                "error": f"没有可供豆包读取的视频 URL，且本地内嵌失败：{exc}",
                "issues": [],
            }

    script = _job_script(job)
    shot_context = job.get("shots") or job.get("shot_plan") or []
    if isinstance(shot_context, list):
        shot_context = shot_context[:30]

    prompt = f"""
你是短视频成片质量审查员。请观看完整视频，并对照原始配音稿和镜头计划审查。
这是质量审查，不是内容改写。必须如实标记时间段，不能为了通过而放宽标准。

原始配音稿：
{script or "job 未记录原始配音稿，请重点审查画面、字幕和音频"}

镜头计划摘要：
{json.dumps(shot_context, ensure_ascii=False)[:5000]}

机械检查摘要：
{json.dumps(mechanical.get("checks") or [], ensure_ascii=False)[:5000]}

重点检查：
1. 画面是否逐段对应当时正在说的内容，例如说生活配套时不能一直是泛城市航拍；
2. 字幕是否为简体中文，是否有错字、繁体、乱码、抽象符号，是否明显提前或滞后；
3. 是否存在镜头疯狂重复、过长静止、黑帧、跳帧、画面拼贴或错误文字；
4. 节奏是否自然，画面是否覆盖完整配音；
5. 是否出现不真实地标、错误区域、无关场景；
6. 是否已经达到可以进入“封面合成”的标准。

只输出 JSON，不要 Markdown。结构必须是：
{{
  "passed": true,
  "score": 0到100,
  "summary": "一句话结论",
  "checks": {{
    "visual_script_match": 0到100,
    "subtitle_accuracy": 0到100,
    "subtitle_timing": 0到100,
    "shot_variety": 0到100,
    "technical_quality": 0到100,
    "pacing": 0到100
  }},
  "issues": [
    {{
      "type": "visual_mismatch|subtitle_error|subtitle_timing|repetition|black_frame|artifact|pacing|wrong_location|other",
      "start": 0.0,
      "end": 0.0,
      "severity": "critical|high|medium|low",
      "description": "具体问题",
      "suggestion": "具体修复方法",
      "requires_new_fal": false
    }}
  ]
}}
""".strip()

    content = [
        {"type": "text", "text": prompt},
        {"type": "video_url", "video_url": {"url": video_ref}},
    ]
    body = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0.1,
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=240) as client:
            response = await client.post(
                base_url + "/chat/completions",
                headers=headers,
                json=body,
            )
    except httpx.HTTPError as exc:
        return {
            "available": False,
            "passed": None,
            "score": None,
            "model": model,
            "error": f"豆包视频理解请求失败：{exc}",
            "issues": [],
        }

    if response.status_code >= 400:
        return {
            "available": False,
            "passed": None,
            "score": None,
            "model": model,
            "error": f"豆包返回 {response.status_code}：{response.text[:1000]}",
            "issues": [],
        }

    try:
        payload = response.json()
        text = payload.get("choices", [{}])[0].get("message", {}).get("content", "")
        result = _json_from_model_text(str(text))
    except Exception as exc:
        return {
            "available": False,
            "passed": None,
            "score": None,
            "model": model,
            "error": f"豆包审查结果不是有效 JSON：{exc}",
            "issues": [],
        }

    issues = result.get("issues") if isinstance(result.get("issues"), list) else []
    normalized_issues = []
    for issue in issues[:50]:
        if not isinstance(issue, dict):
            continue
        normalized_issues.append(
            {
                "type": str(issue.get("type") or "other"),
                "start": float(issue.get("start") or 0),
                "end": float(issue.get("end") or 0),
                "severity": str(issue.get("severity") or "medium"),
                "description": str(issue.get("description") or "").strip(),
                "suggestion": str(issue.get("suggestion") or "").strip(),
                "requires_new_fal": bool(issue.get("requires_new_fal", False)),
            }
        )

    try:
        score = max(0, min(100, int(float(result.get("score") or 0))))
    except Exception:
        score = 0
    passed = bool(result.get("passed")) and score >= 75
    if any(x["severity"] in {"critical", "high"} for x in normalized_issues):
        passed = False

    return {
        "available": True,
        "passed": passed,
        "score": score,
        "model": model,
        "summary": str(result.get("summary") or "").strip(),
        "checks": result.get("checks") if isinstance(result.get("checks"), dict) else {},
        "issues": normalized_issues,
        "raw_usage": payload.get("usage") if isinstance(payload, dict) else None,
        "error": "",
    }


async def _run_review(job_id: str, force_ai: bool = True) -> dict[str, Any]:
    with _REVIEW_LOCK:
        existing = _load_review(job_id)
        if existing.get("status") == "reviewing":
            return existing
        _save_review(
            job_id,
            {
                "ok": True,
                "job_id": job_id,
                "status": "reviewing",
                "approved": False,
                "packaging_unlocked": False,
                "started_at": _now(),
            },
        )

    job = _load_job(job_id)
    if not job:
        return _save_review(
            job_id,
            {
                "ok": False,
                "status": "review_error",
                "approved": False,
                "packaging_unlocked": False,
                "error": "job not found",
            },
        )

    mechanical = await asyncio.to_thread(_mechanical_review, job_id, job)
    ai_result: dict[str, Any]
    if force_ai:
        ai_result = await _doubao_review(job, mechanical)
    else:
        ai_result = {
            "available": False,
            "passed": None,
            "score": None,
            "model": "",
            "error": "本次仅执行机械检查",
            "issues": [],
        }

    machine_passed = bool(mechanical.get("passed"))
    ai_available = bool(ai_result.get("available"))
    ai_passed = ai_result.get("passed") is True

    if not machine_passed:
        status = "review_failed"
    elif ai_available and not ai_passed:
        status = "review_failed"
    else:
        # Even when all automatic checks pass, human approval is mandatory.
        status = "review_pending_human"

    machine_score = int(mechanical.get("score") or 0)
    ai_score = ai_result.get("score")
    overall = machine_score
    if isinstance(ai_score, (int, float)):
        overall = round(machine_score * 0.45 + float(ai_score) * 0.55)

    issues = list(mechanical.get("issues") or []) + list(ai_result.get("issues") or [])
    report = {
        "ok": True,
        "job_id": job_id,
        "status": status,
        "approved": False,
        "packaging_unlocked": False,
        "overall_score": overall,
        "summary": (
            "自动检查通过，等待人工确认后生成封面"
            if status == "review_pending_human"
            else "自动检查发现问题，先修复视频再进入封面合成"
        ),
        "mechanical": mechanical,
        "ai_review": ai_result,
        "issues": issues,
        "started_at": existing.get("started_at") or _now(),
        "completed_at": _now(),
    }
    _save_review(job_id, report)

    job["review_status"] = status
    job["review_score"] = overall
    job["review_report_path"] = str(_review_path(job_id))
    job["packaging_unlocked"] = False
    _save_job(job_id, job)
    return report


def _packaging_allowed(job_id: str) -> tuple[bool, dict[str, Any]]:
    report = _load_review(job_id)
    allowed = (
        report.get("status") == "approved"
        and bool(report.get("approved"))
        and bool(report.get("packaging_unlocked"))
    )
    return allowed, report


async def _post_local_json(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    token = ""
    try:
        token = Path("/root/ai-video-admin-token.txt").read_text(encoding="utf-8").strip()
    except Exception:
        pass
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-AI-Video-Token"] = token
    async with httpx.AsyncClient(timeout=180) as client:
        response = await client.post(
            "http://127.0.0.1:8000" + path,
            json=payload,
            headers=headers,
        )
    try:
        data = response.json()
    except Exception:
        data = {"raw": response.text}
    if response.status_code >= 400:
        raise RuntimeError(
            f"封面接口返回 {response.status_code}：{json.dumps(data, ensure_ascii=False)[:1200]}"
        )
    return data if isinstance(data, dict) else {"data": data}


class PackagingApprovalMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or scope.get("path") not in PACKAGING_PATHS:
            await self.app(scope, receive, send)
            return

        require_gate = os.getenv("AI_VIDEO_REQUIRE_REVIEW_APPROVAL", "true").lower() not in {
            "0",
            "false",
            "no",
        }
        if not require_gate:
            await self.app(scope, receive, send)
            return

        body_parts = []
        more = True
        while more:
            message = await receive()
            body_parts.append(message.get("body", b""))
            more = bool(message.get("more_body", False))
        body = b"".join(body_parts)

        try:
            payload = json.loads(body.decode("utf-8") or "{}")
            if not isinstance(payload, dict):
                payload = {}
        except Exception:
            payload = {}

        job_id = str(payload.get("job_id") or "").strip()
        allowed, report = _packaging_allowed(job_id)
        if not job_id or not allowed:
            response = JSONResponse(
                status_code=409,
                content={
                    "ok": False,
                    "error": "video_review_required",
                    "message": "视频尚未人工通过审查，封面和小红书图文已锁定。",
                    "job_id": job_id,
                    "review_status": report.get("status") or "not_reviewed",
                    "review_url": f"/api/video/review/{job_id}" if job_id else "",
                    "next_action": (
                        "先运行自动审查，再人工点击“通过并生成封面”"
                    ),
                },
            )
            await response(scope, receive, send)
            return

        sent = False

        async def receive_again():
            nonlocal sent
            if sent:
                return {"type": "http.request", "body": b"", "more_body": False}
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        await self.app(scope, receive_again, send)


async def _auto_review_loop() -> None:
    interval = max(
        30,
        int(os.getenv("AI_VIDEO_AUTO_REVIEW_INTERVAL_SECONDS", "60") or 60),
    )
    enabled = os.getenv("AI_VIDEO_AUTO_REVIEW_ON_COMPLETE", "true").lower() not in {
        "0",
        "false",
        "no",
    }
    if not enabled:
        return

    while True:
        try:
            job = _latest_completed_job()
            job_id = str(job.get("job_id") or "").strip()
            if job_id:
                report = _load_review(job_id)
                if report.get("status") == "not_reviewed":
                    await _run_review(job_id, force_ai=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print("VIDEO_REVIEW_AUTO_LOOP_ERROR", repr(exc), flush=True)
        await asyncio.sleep(interval)


def install_video_review_gate_provider(app: FastAPI) -> None:
    if getattr(app.state, "video_review_gate_installed", False):
        return
    app.state.video_review_gate_installed = True
    app.add_middleware(PackagingApprovalMiddleware)

    @app.get("/api/video/review/health")
    def review_health():
        return {
            "ok": True,
            "provider": "video_review_gate_provider",
            "version": "v1.0",
            "review_root": str(REVIEW_ROOT),
            "packaging_requires_approval": os.getenv(
                "AI_VIDEO_REQUIRE_REVIEW_APPROVAL",
                "true",
            ),
            "auto_review_on_complete": os.getenv(
                "AI_VIDEO_AUTO_REVIEW_ON_COMPLETE",
                "true",
            ),
            "ark_model": _settings_value("ARK_VIDEO_MODEL", "doubao-seed-2-0-lite"),
            "ark_configured": bool(_settings_value("ARK_API_KEY")),
        }

    @app.get("/api/video/review/latest")
    def latest_review():
        job = _latest_completed_job()
        job_id = str(job.get("job_id") or "").strip()
        if not job_id:
            return {
                "ok": False,
                "status": "not_found",
                "message": "没有找到已完成视频",
            }
        return {
            "ok": True,
            "job_id": job_id,
            "title": _job_title(job),
            "review": _load_review(job_id),
        }

    @app.get("/api/video/review/{job_id}")
    def get_review(job_id: str):
        return _load_review(job_id)

    @app.get("/api/video/review/{job_id}/gate")
    def get_gate(job_id: str):
        allowed, report = _packaging_allowed(job_id)
        return {
            "ok": True,
            "job_id": job_id,
            "allowed": allowed,
            "review_status": report.get("status"),
            "approved": bool(report.get("approved")),
            "packaging_unlocked": bool(report.get("packaging_unlocked")),
            "overall_score": report.get("overall_score"),
        }

    @app.post("/api/video/review/{job_id}/run")
    async def run_review(
        job_id: str,
        payload: dict[str, Any] = Body(default_factory=dict),
    ):
        force_ai = bool(payload.get("force_ai", True))
        force = bool(payload.get("force", False))
        existing = _load_review(job_id)
        if (
            not force
            and existing.get("status")
            in {"review_pending_human", "review_failed", "approved", "rejected"}
        ):
            return existing
        return await _run_review(job_id, force_ai=force_ai)

    @app.post("/api/video/review/{job_id}/approve")
    async def approve_review(
        job_id: str,
        payload: dict[str, Any] = Body(default_factory=dict),
    ):
        report = _load_review(job_id)
        if report.get("status") in {"not_reviewed", "reviewing", "review_error"}:
            raise HTTPException(status_code=409, detail="请先完成自动审查")

        force = bool(payload.get("force", False))
        machine_passed = bool((report.get("mechanical") or {}).get("passed"))
        ai = report.get("ai_review") or {}
        ai_hard_failed = bool(ai.get("available")) and ai.get("passed") is False

        if not force and (not machine_passed or ai_hard_failed):
            raise HTTPException(
                status_code=409,
                detail="自动审查仍有高风险问题。修复后重新审查，或由管理员明确 force=true。",
            )

        job = _load_job(job_id)
        reviewer = str(payload.get("reviewer") or "human").strip()
        note = str(payload.get("note") or "").strip()

        report.update(
            {
                "ok": True,
                "status": "approved",
                "approved": True,
                "packaging_unlocked": True,
                "reviewer": reviewer,
                "approval_note": note,
                "approved_at": _now(),
            }
        )
        _save_review(job_id, report)

        if job:
            job["review_status"] = "approved"
            job["review_approved_at"] = report["approved_at"]
            job["reviewer"] = reviewer
            job["packaging_unlocked"] = True
            _save_job(job_id, job)

        cover_result = None
        cover_error = ""
        if bool(payload.get("generate_cover", True)):
            cover_payload = {
                "job_id": job_id,
                "title": str(payload.get("title") or _job_title(job)),
                "script_text": _job_script(job),
                "keywords": payload.get("keywords") or [],
                "platform": str(payload.get("platform") or "douyin"),
                "style": str(payload.get("style") or "专业顾问"),
                "slide_count": 7,
                "cta": str(payload.get("cta") or ""),
                "use_video_frame": True,
            }
            try:
                cover_result = await _post_local_json(
                    "/api/graphic-window/video-cover/generate",
                    cover_payload,
                )
                report["cover_result"] = cover_result
                report["cover_generated_at"] = _now()
                _save_review(job_id, report)
            except Exception as exc:
                cover_error = str(exc)
                report["cover_error"] = cover_error
                _save_review(job_id, report)

        return {
            "ok": True,
            "job_id": job_id,
            "status": "approved",
            "approved": True,
            "packaging_unlocked": True,
            "message": (
                "视频已通过人工审查，封面已生成"
                if cover_result
                else "视频已通过人工审查，封面生成未执行或失败"
            ),
            "cover_result": cover_result,
            "cover_error": cover_error,
            "review": report,
        }

    @app.post("/api/video/review/{job_id}/reject")
    def reject_review(
        job_id: str,
        payload: dict[str, Any] = Body(default_factory=dict),
    ):
        report = _load_review(job_id)
        reason = str(payload.get("reason") or "人工退回修改").strip()
        reviewer = str(payload.get("reviewer") or "human").strip()
        report.update(
            {
                "ok": True,
                "status": "rejected",
                "approved": False,
                "packaging_unlocked": False,
                "rejected_at": _now(),
                "rejection_reason": reason,
                "reviewer": reviewer,
            }
        )
        _save_review(job_id, report)

        job = _load_job(job_id)
        if job:
            job["review_status"] = "rejected"
            job["review_rejection_reason"] = reason
            job["packaging_unlocked"] = False
            _save_job(job_id, job)
        return report

    @app.on_event("startup")
    async def start_video_review_worker():
        global _AUTO_REVIEW_TASK
        if _AUTO_REVIEW_TASK is None or _AUTO_REVIEW_TASK.done():
            _AUTO_REVIEW_TASK = asyncio.create_task(_auto_review_loop())

    @app.on_event("shutdown")
    async def stop_video_review_worker():
        global _AUTO_REVIEW_TASK
        if _AUTO_REVIEW_TASK and not _AUTO_REVIEW_TASK.done():
            _AUTO_REVIEW_TASK.cancel()
            try:
                await _AUTO_REVIEW_TASK
            except asyncio.CancelledError:
                pass
            _AUTO_REVIEW_TASK = None
