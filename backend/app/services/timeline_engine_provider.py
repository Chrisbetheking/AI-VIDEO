from __future__ import annotations

import json
import math
import re
import time
import uuid
from dataclasses import dataclass, asdict
from typing import Any


PUNCT_SPLIT_RE = re.compile(r"([。！？!?；;]|，|,|\n+)")
STRONG_WORDS = [
    "核心", "重点", "必须", "关键", "爆点", "优势", "稀缺", "立即", "现在",
    "important", "must", "key", "limited", "now", "exclusive", "premium"
]


@dataclass
class TimelineSegment:
    index: int
    text: str
    start: float
    end: float
    duration: float
    emotion: str = "neutral"
    emphasis: float = 1.0
    words_count: int = 0
    chars_count: int = 0
    subtitle_text: str = ""
    shot_hint: str = "normal"
    audio_ref: str | None = None
    subtitle_ref: str | None = None
    shot_ref: str | None = None


@dataclass
class Timeline:
    timeline_id: str
    status: str
    total_duration: float
    segment_count: int
    segments: list[TimelineSegment]
    message: str = "Timeline Engine v1 构建完成。"


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _is_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text or ""))


def _word_count(text: str) -> int:
    text = _clean_text(text)
    if not text:
        return 0

    if _is_cjk(text):
        cjk_chars = re.findall(r"[\u4e00-\u9fff]", text)
        latin_words = re.findall(r"[A-Za-z0-9]+", text)
        return len(cjk_chars) + len(latin_words)

    return len(re.findall(r"[A-Za-z0-9']+", text))


def _split_sentences(text: str) -> list[str]:
    text = _clean_text(text)
    if not text:
        return []

    parts = PUNCT_SPLIT_RE.split(text)
    chunks: list[str] = []
    current = ""

    for part in parts:
        if not part:
            continue

        current += part

        if re.match(r"^[。！？!?；;，,\n]+$", part):
            c = _clean_text(current)
            if c:
                chunks.append(c)
            current = ""

    tail = _clean_text(current)
    if tail:
        chunks.append(tail)

    if not chunks:
        chunks = [text]

    return chunks


def semantic_split(text: str, target_min_chars: int = 10, target_max_chars: int = 34) -> list[str]:
    raw = _split_sentences(text)

    segments: list[str] = []
    buf = ""

    for item in raw:
        item = _clean_text(item)
        if not item:
            continue

        candidate = _clean_text(f"{buf} {item}" if buf else item)

        if len(candidate) <= target_max_chars:
            buf = candidate
            continue

        if buf:
            segments.append(buf)
            buf = item
        else:
            if len(item) <= target_max_chars:
                segments.append(item)
            else:
                # 长句硬切，但尽量按短语长度切
                start = 0
                while start < len(item):
                    segments.append(item[start:start + target_max_chars])
                    start += target_max_chars
                buf = ""

    if buf:
        segments.append(buf)

    # 太短的尾段合并到上一段
    merged: list[str] = []
    for seg in segments:
        if merged and len(seg) < target_min_chars and len(merged[-1]) + len(seg) <= target_max_chars + 8:
            merged[-1] = _clean_text(merged[-1] + " " + seg)
        else:
            merged.append(seg)

    return merged


def detect_emotion(text: str) -> str:
    t = text.lower()

    if any(w in t for w in ["紧急", "立即", "马上", "now", "urgent"]):
        return "urgent"

    if any(w in t for w in ["豪华", "高级", "premium", "luxury", "exclusive"]):
        return "premium"

    if any(w in t for w in ["温馨", "舒适", "安心", "cozy", "safe"]):
        return "warm"

    if any(w in t for w in ["震撼", "惊喜", "爆", "wow", "amazing"]):
        return "excited"

    return "neutral"


def detect_emphasis(text: str) -> float:
    score = 1.0
    lower = text.lower()

    if any(w.lower() in lower for w in STRONG_WORDS):
        score += 0.25

    if any(p in text for p in ["！", "!", "？", "?"]):
        score += 0.15

    if len(text) <= 12:
        score += 0.05

    return round(min(score, 1.6), 2)


def estimate_duration(text: str, speech_rate_cps: float = 4.2, min_duration: float = 1.8, max_duration: float = 6.5) -> float:
    text = _clean_text(text)
    chars = len(text)
    words = _word_count(text)

    if _is_cjk(text):
        base = chars / max(1.0, speech_rate_cps)
    else:
        base = words / 2.4

    # 句末停顿
    pause = 0.25
    if any(text.endswith(p) for p in ["。", ".", "！", "!", "？", "?"]):
        pause = 0.42
    elif any(text.endswith(p) for p in ["，", ",", "；", ";"]):
        pause = 0.28

    emphasis = detect_emphasis(text)
    duration = (base + pause) * emphasis

    return round(max(min_duration, min(max_duration, duration)), 2)


def shot_hint_for_segment(emotion: str, emphasis: float, duration: float) -> str:
    if emphasis >= 1.25:
        return "slow_emphasis"
    if emotion in {"urgent", "excited"}:
        return "fast_cut"
    if duration >= 5.0:
        return "slow_pan"
    return "normal"


def build_timeline(
    text: str,
    target_duration: float | None = None,
    speech_rate_cps: float = 4.2,
    min_segment_duration: float = 1.8,
    max_segment_duration: float = 6.5,
) -> dict[str, Any]:
    text = _clean_text(text)
    if not text:
        raise ValueError("text 不能为空")

    timeline_id = f"timeline_{uuid.uuid4().hex[:18]}"
    raw_segments = semantic_split(text)

    durations = [
        estimate_duration(
            seg,
            speech_rate_cps=speech_rate_cps,
            min_duration=min_segment_duration,
            max_duration=max_segment_duration,
        )
        for seg in raw_segments
    ]

    raw_total = sum(durations)

    if target_duration and target_duration > 0 and raw_total > 0:
        scale = float(target_duration) / raw_total
        durations = [
            round(max(min_segment_duration, min(max_segment_duration, d * scale)), 2)
            for d in durations
        ]

    current = 0.0
    segments: list[TimelineSegment] = []

    for i, seg in enumerate(raw_segments):
        duration = durations[i]
        start = round(current, 2)
        end = round(start + duration, 2)
        emotion = detect_emotion(seg)
        emphasis = detect_emphasis(seg)

        segments.append(
            TimelineSegment(
                index=i,
                text=seg,
                start=start,
                end=end,
                duration=duration,
                emotion=emotion,
                emphasis=emphasis,
                words_count=_word_count(seg),
                chars_count=len(seg),
                subtitle_text=seg,
                shot_hint=shot_hint_for_segment(emotion, emphasis, duration),
            )
        )

        current = end

    timeline = Timeline(
        timeline_id=timeline_id,
        status="done",
        total_duration=round(current, 2),
        segment_count=len(segments),
        segments=segments,
    )

    return {
        "ok": True,
        "provider": "timeline_engine_v1",
        "timeline_id": timeline.timeline_id,
        "status": timeline.status,
        "total_duration": timeline.total_duration,
        "segment_count": timeline.segment_count,
        "segments": [asdict(s) for s in timeline.segments],
        "srt_preview": build_srt_preview(timeline),
        "shot_plan": build_shot_plan(timeline),
        "message": timeline.message,
    }


def build_srt_preview(timeline: Timeline) -> str:
    lines: list[str] = []

    for seg in timeline.segments:
        lines.append(str(seg.index + 1))
        lines.append(f"{_srt_time(seg.start)} --> {_srt_time(seg.end)}")
        lines.append(seg.subtitle_text)
        lines.append("")

    return "\n".join(lines).strip()


def _srt_time(seconds: float) -> str:
    ms_total = int(round(seconds * 1000))
    h = ms_total // 3600000
    ms_total %= 3600000
    m = ms_total // 60000
    ms_total %= 60000
    s = ms_total // 1000
    ms = ms_total % 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_shot_plan(timeline: Timeline) -> list[dict[str, Any]]:
    return [
        {
            "index": seg.index,
            "start": seg.start,
            "end": seg.end,
            "duration": seg.duration,
            "text": seg.text,
            "shot_hint": seg.shot_hint,
            "emotion": seg.emotion,
            "emphasis": seg.emphasis,
        }
        for seg in timeline.segments
    ]


def health() -> dict[str, Any]:
    return {
        "ok": True,
        "provider": "timeline_engine_v1",
        "message": "Timeline Engine v1 可用：负责统一文本、字幕、语音、镜头的时间轴。",
        "features": [
            "semantic_split",
            "duration_estimation",
            "subtitle_time_preview",
            "shot_plan",
            "emotion_hint",
            "emphasis_hint",
        ],
    }


def self_test() -> dict[str, Any]:
    text = "AI视频正在改变内容生产。它能快速生成脚本、配音和镜头，同时也需要统一时间轴，才能保证声音、字幕和画面同步。"
    return build_timeline(text=text)
