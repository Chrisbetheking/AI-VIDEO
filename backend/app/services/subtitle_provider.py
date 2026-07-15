from __future__ import annotations

import json
import mimetypes
import os
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse
import urllib.request

import requests

BASE_DIR = Path(os.getenv("AI_VIDEO_BACKEND_DIR", "/opt/ai-video/backend"))
SUBTITLE_DIR = BASE_DIR / "data" / "subtitles"
BURN_DIR = BASE_DIR / "data" / "subtitle-burns"
TEST_DIR = BASE_DIR / "data" / "subtitle-test"

PUNCT_RE = re.compile(r"[，。！？；：、,.!?;:（）()【】\[\]《》<>“”\"'‘’·…—～~|/\\]+")
SPACE_RE = re.compile(r"\s+")

DEFAULT_KEYWORDS = [
    "吉隆坡", "买房", "预算", "区域", "地段", "配套", "通勤", "出租", "租金", "回报",
    "自住", "投资", "商圈", "双子塔", "满家乐", "蕉赖", "海外投资者", "核心商圈",
    "生活圈", "成熟社区", "高预算", "中等预算", "低预算", "评论区", "长期价值",
]

STOP_WORDS = {
    "如果", "比如", "其实", "就是", "这个", "那个", "然后", "所以", "因为", "但是", "一定", "完全", "主要",
    "不同", "一直", "比较", "非常", "真的", "可以", "不能", "不要", "不是", "还是", "更要", "要看",
}


def _ensure_dirs() -> None:
    SUBTITLE_DIR.mkdir(parents=True, exist_ok=True)
    BURN_DIR.mkdir(parents=True, exist_ok=True)
    TEST_DIR.mkdir(parents=True, exist_ok=True)


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def ffprobe_available() -> bool:
    return shutil.which("ffprobe") is not None


def _run(cmd: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)


def get_media_duration_seconds(path: str | Path, default: float = 12.0) -> float:
    if not ffprobe_available():
        return default
    try:
        proc = _run([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path)
        ], timeout=30)
        if proc.returncode == 0:
            value = float((proc.stdout or "").strip())
            if value > 0:
                return value
    except Exception:
        pass
    return default


def _clean_text(text: Any, remove_punct: bool = False) -> str:
    text = str(text or "")
    text = re.sub(r"\\(?:N|n|r|t)", "，", text)
    text = text.replace("\r", "，").replace("\n", "，").replace("\t", " ")
    text = re.sub(r"[／/\\|｜]+", "，", text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    text = SPACE_RE.sub(" ", text.strip())
    text = re.sub(r"[，,]{2,}", "，", text)
    if remove_punct:
        text = PUNCT_RE.sub("", text)
        text = SPACE_RE.sub("", text).strip()
    return text


def _srt_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds or 0))
    ms = int(round((seconds - int(seconds)) * 1000))
    if ms >= 1000:
        seconds += 1
        ms = 0
    total = int(seconds)
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _ass_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds or 0))
    cs = int(round((seconds - int(seconds)) * 100))
    if cs >= 100:
        seconds += 1
        cs = 0
    total = int(seconds)
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def _normalize_time(value: Any, fallback: Optional[float] = None) -> Optional[float]:
    if value is None:
        return fallback
    try:
        num = float(value)
    except Exception:
        return fallback
    if num > 1000:
        num = num / 1000.0
    return max(0.0, num)


def _source_text_from_segment(item: dict[str, Any]) -> str:
    return _clean_text(
        item.get("text") or item.get("clean_subtitle") or item.get("subtitle") or item.get("copy")
        or item.get("content") or item.get("sentence") or item.get("line") or item.get("narration_segment")
        or item.get("narration") or ""
    )


def _split_clauses(text: str, max_raw_chars: int = 24) -> list[str]:
    text = _clean_text(text)
    if not text:
        return []
    raw = [x.strip() for x in re.split(r"[。！？!?；;，,、\n]+", text) if x.strip()]
    if not raw:
        raw = [text]
    out: list[str] = []
    for part in raw:
        part = part.strip()
        if not part:
            continue
        if len(part) <= max_raw_chars:
            out.append(part)
        else:
            # Prefer splitting at short-video semantic words before hard length split.
            split_points = ["更要", "比如", "就不能", "也要", "则要", "低预算", "中等预算", "高预算", "评论区"]
            chunks = [part]
            for token in split_points:
                new_chunks: list[str] = []
                for c in chunks:
                    if len(c) > max_raw_chars and token in c and not c.startswith(token):
                        a, b = c.split(token, 1)
                        if a.strip():
                            new_chunks.append(a.strip())
                        if b.strip():
                            new_chunks.append((token + b).strip())
                    else:
                        new_chunks.append(c)
                chunks = new_chunks
            for c in chunks:
                if len(c) <= max_raw_chars:
                    out.append(c)
                else:
                    for i in range(0, len(c), max_raw_chars):
                        out.append(c[i:i + max_raw_chars])
    return out


def _local_concise(text: str, max_chars: int = 14) -> str:
    raw = _clean_text(text, remove_punct=True)
    if not raw:
        return ""

    replacements = [
        ("预算不同在吉隆坡选房的逻辑完全不一样", "预算不同区域不同"),
        ("在吉隆坡选房的逻辑完全不一样", "选房逻辑不同"),
        ("纯投资看出租回报", "投资看出租回报"),
        ("要盯紧核心商圈配套", "盯紧核心配套"),
        ("租金需求一直很活跃", "租金需求活跃"),
        ("如果带着自住需求", "自住需求"),
        ("不能只看投资回报", "别只看回报"),
        ("日常通勤和生活便利度", "通勤和便利度"),
        ("成熟社区", "成熟社区"),
        ("高预算买家", "高预算看国际区"),
        ("中等预算", "中预算平衡配套"),
        ("低预算", "低预算守住商圈"),
        ("商圈辐射范围内", "商圈辐射范围"),
        ("你是海外投资者还是自住需求买家", "你是投资还是自住"),
        ("主要想出租还是自住", "出租还是自住"),
        ("评论区告诉我", "评论区告诉我"),
    ]
    for src, dst in replacements:
        if src in raw:
            return dst[:max_chars]

    # Keep strongest phrase around keywords.
    for kw in DEFAULT_KEYWORDS:
        pos = raw.find(kw)
        if pos >= 0:
            start = max(0, pos - 4)
            end = min(len(raw), pos + len(kw) + 6)
            candidate = raw[start:end]
            candidate = re.sub(r"^(如果|比如|更要|主要|就是|因为|所以)", "", candidate)
            if 4 <= len(candidate) <= max_chars + 2:
                return candidate[:max_chars]

    for w in STOP_WORDS:
        raw = raw.replace(w, "")
    return raw[:max_chars]


def _extract_keywords(text: str, max_items: int = 2, explicit: Optional[list[str]] = None) -> list[str]:
    clean = _clean_text(text, remove_punct=True)
    found: list[str] = []
    for item in explicit or []:
        item = _clean_text(item, remove_punct=True)
        if item and item in clean and item not in found:
            found.append(item)
    for kw in DEFAULT_KEYWORDS:
        if kw in clean and kw not in found:
            found.append(kw)
    if not found:
        # fallback: choose 2-4 char meaningful chunks
        chunks = re.findall(r"[\u4e00-\u9fff]{2,6}", clean)
        for c in chunks:
            if c not in STOP_WORDS and len(c) >= 2 and c not in found:
                found.append(c)
            if len(found) >= max_items:
                break
    return found[:max_items]


def _weight(text: str) -> float:
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text or ""))
    ascii_words = len(re.findall(r"[A-Za-z0-9]+", text or ""))
    return max(1.0, cjk + ascii_words * 1.6)


def _build_raw_timed_units(text: str, segments: Optional[list[dict[str, Any]]], duration: float, max_chars: int) -> list[dict[str, Any]]:
    duration = max(1.0, float(duration or 12.0))
    sources: list[dict[str, Any]] = []

    for item in segments or []:
        if not isinstance(item, dict):
            continue
        stext = _source_text_from_segment(item)
        if not stext:
            continue
        start = _normalize_time(item.get("start") if item.get("start") is not None else item.get("start_time") if item.get("start_time") is not None else item.get("start_seconds"))
        end = _normalize_time(item.get("end") if item.get("end") is not None else item.get("end_time") if item.get("end_time") is not None else item.get("end_seconds"))
        explicit_kws = item.get("highlight_words") or item.get("highlight_keywords") or item.get("keywords") or []
        if not isinstance(explicit_kws, list):
            explicit_kws = []
        sources.append({"text": stext, "start": start, "end": end, "keywords": explicit_kws})

    if not sources:
        clauses = _split_clauses(text, max_raw_chars=max(20, max_chars + 8))
        sources = [{"text": c, "start": None, "end": None, "keywords": []} for c in clauses]

    # If source segments have no time, distribute by speech-length weight.
    if not any(s.get("start") is not None and s.get("end") is not None for s in sources):
        total_w = sum(_weight(s["text"]) for s in sources) or 1.0
        cursor = 0.0
        for s in sources:
            span = duration * (_weight(s["text"]) / total_w)
            span = max(1.2, span)
            s["start"] = cursor
            s["end"] = min(duration, cursor + span)
            cursor = s["end"]
        if sources:
            sources[-1]["end"] = duration

    units: list[dict[str, Any]] = []
    for s in sources:
        s_start = float(s.get("start") or 0.0)
        s_end = float(s.get("end") or min(duration, s_start + 2.5))
        if s_end <= s_start:
            s_end = min(duration, s_start + 2.5)
        clauses = _split_clauses(s["text"], max_raw_chars=max(18, max_chars + 6)) or [s["text"]]
        # Keep cues changing every 1.8-3.4 sec where possible.
        expanded: list[str] = []
        for c in clauses:
            c_clean = _clean_text(c, remove_punct=True)
            if len(c_clean) > max_chars + 4:
                for i in range(0, len(c_clean), max_chars + 2):
                    expanded.append(c_clean[i:i + max_chars + 2])
            else:
                expanded.append(c)
        clauses = [x for x in expanded if _clean_text(x, remove_punct=True)] or [s["text"]]
        total_w = sum(_weight(c) for c in clauses) or 1.0
        cur = s_start
        for c in clauses:
            span = (s_end - s_start) * (_weight(c) / total_w)
            span = max(1.2, min(3.4, span))
            end = min(s_end, cur + span)
            if end - cur < 0.75:
                end = min(s_end, cur + 0.75)
            units.append({
                "raw_text": c,
                "text": _local_concise(c, max_chars=max_chars),
                "start": round(cur, 2),
                "end": round(end, 2),
                "source_keywords": s.get("keywords") or [],
            })
            cur = end
        # no gap; next source starts at source boundary
    # Normalize sequential overlaps and cap.
    fixed: list[dict[str, Any]] = []
    last_end = 0.0
    for u in units:
        start = max(float(u["start"]), last_end)
        end = max(start + 0.75, float(u["end"]))
        if start >= duration:
            break
        end = min(duration, end)
        if end <= start:
            continue
        u["start"] = round(start, 2)
        u["end"] = round(end, 2)
        fixed.append(u)
        last_end = end
    if fixed:
        fixed[-1]["end"] = round(duration, 2)
    return fixed


def _extract_json(text: str) -> dict[str, Any]:
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return {}


def _deepseek_subtitle_director(raw_units: list[dict[str, Any]], max_chars: int) -> Optional[list[dict[str, Any]]]:
    api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("AI_VIDEO_DEEPSEEK_API_KEY") or ""
    if not api_key or os.getenv("AI_VIDEO_DISABLE_DEEPSEEK_SUBTITLE", "0") == "1":
        return None
    base_url = (os.getenv("DEEPSEEK_BASE_URL") or os.getenv("AI_VIDEO_DEEPSEEK_BASE_URL") or "https://api.deepseek.com").rstrip("/")
    model = os.getenv("DEEPSEEK_MODEL") or os.getenv("AI_VIDEO_DEEPSEEK_MODEL") or "deepseek-chat"
    timeout = float(os.getenv("AI_VIDEO_DEEPSEEK_TIMEOUT_SECONDS") or os.getenv("DEEPSEEK_TIMEOUT_SECONDS") or "45")
    system = f"""你是抖音短视频字幕导演。只输出严格 JSON。\n规则：\n1 删除所有标点符号\n2 不照搬口播原句 要压缩成短视频字幕\n3 每条字幕最多 {max_chars} 个中文字\n4 不改变原意 不编造楼盘价格收益\n5 每条给 1 到 2 个 highlight_words 这些词需要放大变色\n6 字幕要像房产顾问短视频 直接 有节奏\n输出格式：{{"cues":[{{"index":1,"text":"字幕","highlight_words":["关键词"]}}]}}"""
    payload = {
        "max_chars": max_chars,
        "items": [
            {"index": i + 1, "raw_text": u.get("raw_text") or u.get("text") or "", "fallback_text": u.get("text") or ""}
            for i, u in enumerate(raw_units[:80])
        ],
    }
    body = {
        "model": model,
        "temperature": 0.25,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
    }
    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace") or "{}")
        content = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
        parsed = _extract_json(content)
        cues = parsed.get("cues") if isinstance(parsed, dict) else None
        if not isinstance(cues, list):
            return None
        out: list[dict[str, Any]] = []
        for c in cues:
            if not isinstance(c, dict):
                continue
            text = _clean_text(c.get("text") or "", remove_punct=True)[:max_chars]
            kws = c.get("highlight_words") or c.get("keywords") or []
            if not isinstance(kws, list):
                kws = []
            if text:
                out.append({"text": text, "highlight_words": [_clean_text(x, remove_punct=True) for x in kws if _clean_text(x, remove_punct=True)]})
        return out or None
    except Exception as exc:
        print("AI_VIDEO_SUBTITLE_DIRECTOR_DEEPSEEK_FALLBACK=" + str(exc)[:300], flush=True)
        return None


def director_cues(
    text: str = "",
    segments: Optional[list[dict[str, Any]]] = None,
    duration: float = 12.0,
    max_chars: int = 14,
) -> list[dict[str, Any]]:
    duration = max(1.0, float(duration or 12.0))
    max_chars = max(8, min(int(max_chars or 14), 18))
    raw_units = _build_raw_timed_units(text=text or "", segments=segments, duration=duration, max_chars=max_chars)
    if not raw_units:
        raise ValueError("没有可生成字幕的文本或 segments")

    directed = _deepseek_subtitle_director(raw_units, max_chars=max_chars)

    cues: list[dict[str, Any]] = []
    for i, unit in enumerate(raw_units):
        if directed and i < len(directed):
            d = directed[i]
            cue_text = _clean_text(d.get("text") or unit.get("text"), remove_punct=True)[:max_chars]
            kws = d.get("highlight_words") or []
        else:
            cue_text = _clean_text(unit.get("text") or _local_concise(unit.get("raw_text") or "", max_chars=max_chars), remove_punct=True)[:max_chars]
            kws = _extract_keywords(cue_text + (unit.get("raw_text") or ""), explicit=unit.get("source_keywords") or [])
        if not cue_text:
            continue
        kws = [kw for kw in _extract_keywords(cue_text + "".join(kws), explicit=kws) if kw and kw in cue_text]
        if not kws:
            kws = _extract_keywords(cue_text, max_items=1)
        cues.append({
            "index": len(cues) + 1,
            "start": float(unit["start"]),
            "end": float(unit["end"]),
            "text": cue_text,
            "highlight_words": kws[:2],
            "raw_text": unit.get("raw_text") or "",
        })
    return cues


def segments_to_cues(segments: list[dict[str, Any]], duration: float = 12.0) -> list[dict[str, Any]]:
    return director_cues(text="", segments=segments or [], duration=duration, max_chars=14)


def text_to_cues(text: str, duration: float = 12.0, max_chars: int = 14) -> list[dict[str, Any]]:
    return director_cues(text=text, segments=None, duration=duration, max_chars=max_chars)


def cues_to_srt(cues: list[dict[str, Any]]) -> str:
    blocks = []
    for idx, cue in enumerate(cues, start=1):
        start = _srt_time(float(cue.get("start", 0)))
        end = _srt_time(float(cue.get("end", 0)))
        text = _clean_text(str(cue.get("text", "")), remove_punct=True)
        blocks.append(f"{idx}\n{start} --> {end}\n{text}")
    return "\n\n".join(blocks).strip() + "\n"


def _ass_escape(text: str) -> str:
    return str(text or "").replace("\\", "\\\\").replace("{", "").replace("}", "")


def _wrap_for_ass(text: str) -> str:
    text = _clean_text(text, remove_punct=True)
    if len(text) <= 8:
        return text
    if len(text) <= 14:
        mid = len(text) // 2
        return text[:mid] + "\\N" + text[mid:]
    return text[:7] + "\\N" + text[7:14]


def _highlight_ass(text: str, keywords: list[str]) -> str:
    wrapped = _wrap_for_ass(text)
    escaped = _ass_escape(wrapped)
    # highlight longest words first to avoid nested replacement
    kws = sorted([_clean_text(k, remove_punct=True) for k in keywords or [] if _clean_text(k, remove_punct=True)], key=len, reverse=True)
    for kw in kws[:2]:
        if not kw:
            continue
        kw_e = _ass_escape(kw)
        if kw_e not in escaped:
            continue
        # Yellow-orange, bigger, bold. Reset to Main style after keyword.
        escaped = escaped.replace(kw_e, r"{\1c&H00D7FF&\fs82\b1}" + kw_e + r"{\rMain}", 1)
    return escaped


def cues_to_ass(cues: list[dict[str, Any]], width: int = 1080, height: int = 1920) -> str:
    font_main = os.getenv("AI_VIDEO_SUBTITLE_FONT", "Noto Sans CJK SC")
    font_size = int(os.getenv("AI_VIDEO_SUBTITLE_FONT_SIZE", "104"))
    margin_v = int(os.getenv("AI_VIDEO_SUBTITLE_MARGIN_V", "270"))
    y = max(120, height - margin_v)
    x = width // 2
    header = f"""[Script Info]
ScriptType: v4.00+
WrapStyle: 2
ScaledBorderAndShadow: yes
PlayResX: {width}
PlayResY: {height}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,{font_main},{font_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H99000000,1,0,0,0,100,100,0,0,1,5,2,2,70,70,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events: list[str] = []
    for cue in cues:
        start = _ass_time(float(cue.get("start") or 0))
        end = _ass_time(float(cue.get("end") or 0))
        text = _highlight_ass(str(cue.get("text") or ""), cue.get("highlight_words") or [])
        line = rf"{{\fad(80,80)\an2\pos({x},{y})}}" + text
        events.append(f"Dialogue: 0,{start},{end},Main,,0,0,0,,{line}")
    return header + "\n".join(events) + "\n"


def make_srt(text: str = "", segments: Optional[list[dict[str, Any]]] = None, duration: float = 12.0, max_chars: int = 14, prefix: str = "subtitle") -> dict[str, Any]:
    _ensure_dirs()
    cues = director_cues(text=text, segments=segments, duration=duration, max_chars=max_chars)
    srt_text = cues_to_srt(cues)
    safe_prefix = re.sub(r"[^a-zA-Z0-9_-]+", "_", prefix or "subtitle").strip("_") or "subtitle"
    filename = f"{safe_prefix}_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.srt"
    path = SUBTITLE_DIR / filename
    path.write_text(srt_text, encoding="utf-8")
    ass_path = path.with_suffix(".ass")
    ass_text = cues_to_ass(cues)
    ass_path.write_text(ass_text, encoding="utf-8")
    return {"ok": True, "cues": cues, "srt_text": srt_text, "srt_path": str(path), "ass_path": str(ass_path), "filename": filename, "mode": "ai_subtitle_director_ass"}


def _download_to_tmp(url: str) -> Path:
    _ensure_dirs()
    parsed = urlparse(url)
    suffix = Path(parsed.path).suffix or ".mp4"
    target = TEST_DIR / f"input_{uuid.uuid4().hex[:12]}{suffix}"
    with requests.get(url, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        with target.open("wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
    return target


def _ffmpeg_subtitle_path(path: Path) -> str:
    value = str(path)
    value = value.replace("\\", "\\\\")
    value = value.replace(":", "\\:")
    value = value.replace("'", "\\'")
    return value


def burn_subtitles(video_url: str = "", video_path: str = "", text: str = "", segments: Optional[list[dict[str, Any]]] = None, duration: Optional[float] = None, max_chars: int = 14, prefix: str = "subtitle_burn") -> dict[str, Any]:
    _ensure_dirs()
    if not ffmpeg_available():
        raise RuntimeError("ffmpeg 不可用，无法烧录字幕")
    if video_url:
        input_path = _download_to_tmp(video_url)
    elif video_path:
        input_path = Path(video_path)
    else:
        raise ValueError("必须提供 video_url 或 video_path")
    if not input_path.exists():
        raise FileNotFoundError(f"视频文件不存在: {input_path}")

    media_duration = float(duration or get_media_duration_seconds(input_path, default=12.0))
    subtitle_result = make_srt(text=text, segments=segments, duration=media_duration, max_chars=max_chars, prefix=prefix)
    safe_prefix = re.sub(r"[^a-zA-Z0-9_-]+", "_", prefix or "subtitle_burn").strip("_") or "subtitle_burn"
    output_path = BURN_DIR / f"{safe_prefix}_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.mp4"
    ass_path = Path(subtitle_result["ass_path"])
    subtitle_filter = f"ass='{_ffmpeg_subtitle_path(ass_path)}'"
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(input_path),
        "-vf", subtitle_filter,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
        "-c:a", "copy", "-movflags", "+faststart", str(output_path),
    ]
    proc = _run(cmd, timeout=900)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or "ffmpeg subtitle burn failed")
    return {
        "ok": True,
        "input_path": str(input_path),
        "output_path": str(output_path),
        "srt_path": subtitle_result["srt_path"],
        "ass_path": subtitle_result["ass_path"],
        "duration": media_duration,
        "srt_text": subtitle_result["srt_text"],
        "cues": subtitle_result["cues"],
        "subtitle_mode": "ai_director_ass_keywords",
    }


def create_self_test_video() -> Path:
    _ensure_dirs()
    if not ffmpeg_available():
        raise RuntimeError("ffmpeg 不可用，无法创建测试视频")
    output = TEST_DIR / f"subtitle_self_test_{uuid.uuid4().hex[:8]}.mp4"
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=c=black:s=720x1280:d=5",
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(output),
    ]
    proc = _run(cmd, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or "ffmpeg self test video failed")
    return output


def health() -> dict[str, Any]:
    _ensure_dirs()
    return {"ok": True, "ffmpeg": ffmpeg_available(), "ffprobe": ffprobe_available(), "subtitle_dir": str(SUBTITLE_DIR), "burn_dir": str(BURN_DIR), "mode": "ai_subtitle_director_ass_keywords"}


def _first_env(*names: str) -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value.strip()
    return ""


def _r2_config() -> dict[str, str]:
    bucket = _first_env("R2_BUCKET", "R2_BUCKET_NAME", "CLOUDFLARE_R2_BUCKET")
    access_key = _first_env("R2_ACCESS_KEY_ID", "CLOUDFLARE_R2_ACCESS_KEY_ID", "AWS_ACCESS_KEY_ID")
    secret_key = _first_env("R2_SECRET_ACCESS_KEY", "CLOUDFLARE_R2_SECRET_ACCESS_KEY", "AWS_SECRET_ACCESS_KEY")
    endpoint = _first_env("R2_ENDPOINT_URL", "CLOUDFLARE_R2_ENDPOINT")
    account_id = _first_env("R2_ACCOUNT_ID", "CLOUDFLARE_ACCOUNT_ID")
    public_base = _first_env("R2_PUBLIC_BASE_URL", "R2_PUBLIC_BASE", "PUBLIC_R2_BASE_URL", "R2_PUBLIC_URL")
    if not endpoint and account_id:
        endpoint = f"https://{account_id}.r2.cloudflarestorage.com"
    return {"bucket": bucket, "access_key": access_key, "secret_key": secret_key, "endpoint": endpoint, "public_base": public_base.rstrip("/")}


def r2_upload_available() -> bool:
    cfg = _r2_config()
    return bool(cfg["bucket"] and cfg["access_key"] and cfg["secret_key"] and cfg["endpoint"] and cfg["public_base"])


def upload_file_to_r2(local_path: str | Path, object_key: str = "") -> dict[str, Any]:
    path = Path(local_path)
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")
    cfg = _r2_config()
    missing = [name for name, value in cfg.items() if name != "public_base" and not value]
    if not cfg["public_base"]:
        missing.append("public_base")
    if missing:
        raise RuntimeError(f"R2 配置不完整，缺少: {', '.join(missing)}")
    import boto3
    from botocore.config import Config
    if not object_key:
        object_key = f"videos/subtitled/{time.strftime('%Y/%m/%d')}/{uuid.uuid4().hex}_{path.name}"
    content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    client = boto3.client(
        "s3", endpoint_url=cfg["endpoint"], aws_access_key_id=cfg["access_key"], aws_secret_access_key=cfg["secret_key"], region_name="auto", config=Config(signature_version="s3v4")
    )
    client.upload_file(str(path), cfg["bucket"], object_key, ExtraArgs={"ContentType": content_type})
    url = f"{cfg['public_base']}/{object_key}"
    return {"ok": True, "uploaded": True, "bucket": cfg["bucket"], "object_key": object_key, "url": url, "content_type": content_type, "size": path.stat().st_size}


def burn_subtitles_and_upload(video_url: str = "", video_path: str = "", text: str = "", segments: Optional[list[dict[str, Any]]] = None, duration: Optional[float] = None, max_chars: int = 14, prefix: str = "subtitle_burn_upload", object_key: str = "") -> dict[str, Any]:
    burn_result = burn_subtitles(video_url=video_url, video_path=video_path, text=text, segments=segments, duration=duration, max_chars=max_chars, prefix=prefix)
    upload_result = upload_file_to_r2(burn_result["output_path"], object_key=object_key)
    return {"ok": True, "video_url": upload_result["url"], "url": upload_result["url"], "r2": upload_result, "burn": burn_result, "message": "AI导演字幕版视频已烧录并上传到 R2"}


def create_self_test_burn_upload() -> dict[str, Any]:
    video_path = create_self_test_video()
    return burn_subtitles_and_upload(video_path=str(video_path), text="吉隆坡买房不要只看价格 先看预算 区域 配套和通勤", duration=5.0, max_chars=14, prefix="subtitle_burn_upload_self_test")


def upload_health() -> dict[str, Any]:
    base = health()
    cfg = _r2_config()
    base.update({"r2_configured": r2_upload_available(), "r2_bucket": cfg["bucket"], "r2_endpoint_configured": bool(cfg["endpoint"]), "r2_public_base_configured": bool(cfg["public_base"])})
    return base
