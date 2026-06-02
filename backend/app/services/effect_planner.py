from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

import httpx


@dataclass
class TimedSegment:
    index: int
    text: str
    start: float
    end: float


@dataclass
class StickerCue:
    text: str
    trigger: str
    start: float
    end: float
    x: int
    y: int
    tone: str = "soft"


DIRECTOR_RE = re.compile(
    r"[（(][^）)]*(?:显示|截图|镜头|画面|插入|切到|贴纸|素材|B[- ]?roll|预算表|地图|图示|字幕)[^）)]*[）)]",
    flags=re.IGNORECASE,
)
COMMAND_RE = re.compile(
    r"(?:显示|插入|切到|镜头给到|画面出现|字幕出现|叠加)(?:[^。！？!?；;\n]{0,40})(?:截图|画面|地图|预算表|清单|图示|贴纸)",
    flags=re.IGNORECASE,
)
URL_RE = re.compile(r"https?://\S+|www\.\S+", flags=re.IGNORECASE)
EMOJI_RE = re.compile(r"[\U0001F000-\U0001FAFF]", flags=re.UNICODE)


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\u3000", " ")).strip()


def clean_narration_text(text: str) -> str:
    """Remove director notes and placeholders that should never be spoken or burned into subtitles."""
    if not text:
        return ""
    text = URL_RE.sub("", text)
    text = DIRECTOR_RE.sub("", text)
    text = COMMAND_RE.sub("", text)
    cleaned_lines: List[str] = []
    for line in str(text).splitlines():
        s = line.strip()
        if not s:
            continue
        # Drop common storyboard labels, not narration.
        if re.match(r"^(镜头|画面|字幕|贴纸|音效|B[- ]?roll|素材|导演提示|备注)[:：]", s, flags=re.I):
            continue
        cleaned_lines.append(s)
    text = " ".join(cleaned_lines)
    # Remove leftover pure placeholder parentheses.
    text = re.sub(r"[（(]\s*[）)]", "", text)
    text = normalize_space(text)
    return text


def split_narration(text: str, max_chars: int = 24) -> List[str]:
    """Split narration into short TTS/subtitle segments. Keeps punctuation natural."""
    text = clean_narration_text(text)
    if not text:
        return []
    raw: List[str] = []
    for sentence in re.split(r"(?<=[。！？!?；;])", text):
        sentence = sentence.strip()
        if sentence:
            raw.append(sentence)
    if not raw:
        raw = [text]

    out: List[str] = []
    for sentence in raw:
        while len(sentence) > max_chars:
            cut = max(
                sentence.rfind("，", 0, max_chars),
                sentence.rfind(",", 0, max_chars),
                sentence.rfind("、", 0, max_chars),
                sentence.rfind(" ", 0, max_chars),
            )
            if cut <= 6:
                cut = max_chars
            part = sentence[:cut].strip(" ，,、")
            if part:
                out.append(part)
            sentence = sentence[cut:].strip(" ，,、")
        if sentence:
            out.append(sentence)
    return out


def remove_repeated_intro(segments: List[str]) -> List[str]:
    """Avoid digital-human intro sentence being repeated in later B-roll narration."""
    if len(segments) < 3:
        return segments
    first = re.sub(r"[，。！？!?,.\s]", "", segments[0])
    if len(first) < 6:
        return segments
    kept = [segments[0]]
    for i, seg in enumerate(segments[1:], start=1):
        compact = re.sub(r"[，。！？!?,.\s]", "", seg)
        # Only remove clear duplicates, not similar follow-up points.
        if i <= 3 and (compact == first or first in compact or compact in first):
            continue
        kept.append(seg)
    return kept


def wrap_cn(text: str, max_chars: int = 14) -> str:
    text = clean_narration_text(text)
    if len(text) <= max_chars:
        return text
    lines: List[str] = []
    rest = text
    while len(rest) > max_chars and len(lines) < 2:
        cut = max(rest.rfind("，", 0, max_chars), rest.rfind("、", 0, max_chars), rest.rfind(" ", 0, max_chars))
        if cut <= 4:
            cut = max_chars
        lines.append(rest[:cut].strip(" ，、"))
        rest = rest[cut:].strip(" ，、")
    if rest and len(lines) < 2:
        lines.append(rest)
    return r"\N".join(lines[:2])


ANCHORS = {
    "top_left": (150, 315),
    "top_right": (760, 315),
    "left_mid": (150, 610),
    "right_mid": (760, 610),
    "lower_left": (150, 960),
    "lower_right": (760, 960),
}

KEYWORD_STICKERS = [
    (r"别|不要|避坑|跟风|冲动|小心|风险|坑", "⚠️ 别冲动下定", "warning", "top_right"),
    (r"预算|钱|成本|费用|房价|租金|回报|贷款", "💸 预算先算清", "money", "right_mid"),
    (r"学校|教育|学费|国际学校|孩子", "🎒 学费先核实", "school", "left_mid"),
    (r"身份|签证|第二家园|MM2H|移民", "🏠 身份门槛要看清", "home", "top_left"),
    (r"医疗|养老|医院|保险", "🩺 医疗也要算", "health", "lower_right"),
    (r"区域|地段|交通|通勤|社区|配套", "📍 地段别只看热闹", "location", "lower_left"),
    (r"合同|产权|中介|开发商|定金", "📝 合同先查明", "legal", "right_mid"),
    (r"真实|实地|现场|亲自|踩盘", "👀 现场比宣传重要", "soft", "left_mid"),
]


def _valid_sticker_text(text: str) -> bool:
    if not text:
        return False
    if len(text) > 18:
        return False
    bad = "地图/预算表截图 显示截图 插入镜头 画面素材 B-roll".split()
    return not any(b in text for b in bad)


def _find_segment_for_trigger(trigger: str, segments: List[TimedSegment]) -> Optional[TimedSegment]:
    trigger = (trigger or "").strip()
    if not trigger:
        return None
    for seg in segments:
        if trigger in seg.text:
            return seg
    # Fuzzy keyword fallback.
    for seg in segments:
        if any(ch in seg.text for ch in trigger[:4]):
            return seg
    return None


def _fallback_stickers(segments: List[TimedSegment], max_stickers: int = 6) -> List[StickerCue]:
    cues: List[StickerCue] = []
    used_seg: set[int] = set()
    used_text: set[str] = set()
    anchor_cycle = ["top_right", "left_mid", "right_mid", "top_left", "lower_right", "lower_left"]
    anchor_i = 0

    for seg in segments:
        if seg.end <= 0.4:
            continue
        for pattern, text, tone, anchor in KEYWORD_STICKERS:
            if re.search(pattern, seg.text, flags=re.I) and text not in used_text and seg.index not in used_seg:
                # Keep stickers subtle: do not cover mouth/center subtitle area.
                chosen = anchor or anchor_cycle[anchor_i % len(anchor_cycle)]
                x, y = ANCHORS.get(chosen, ANCHORS[anchor_cycle[anchor_i % len(anchor_cycle)]])
                start = max(seg.start + 0.12, 0.25)
                end = min(seg.end, start + 1.55)
                if end - start < 0.65:
                    end = min(seg.end + 0.4, start + 1.2)
                cues.append(StickerCue(text=text, trigger=pattern, start=start, end=end, x=x, y=y, tone=tone))
                used_text.add(text)
                used_seg.add(seg.index)
                anchor_i += 1
                break
        if len(cues) >= max_stickers:
            break
    return cues


async def _ai_plan_raw(settings: Any, title: str, script: str, segments: List[TimedSegment]) -> Optional[List[Dict[str, Any]]]:
    """Ask the text model for sticker ideas. Fails closed to heuristic planner."""
    if os.getenv("ENABLE_AI_STICKERS", "true").lower() in {"0", "false", "no", "off"}:
        return None
    api_key = (getattr(settings, "deepseek_api_key", "") or os.getenv("DEEPSEEK_API_KEY", "")).strip()
    base_url = (getattr(settings, "deepseek_base_url", "") or os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")).rstrip("/")
    model = (getattr(settings, "deepseek_model", "") or os.getenv("DEEPSEEK_MODEL", "deepseek-chat")).strip()
    if not api_key:
        return None

    seg_lines = "\n".join(f"{s.index}. {s.start:.1f}-{s.end:.1f}s｜{s.text}" for s in segments[:18])
    prompt = f"""
你是短视频后期包装导演。根据口播内容，挑选少量轻量贴纸提示，风格参考抖音信息类视频：若隐若现、轻微弹出、不能遮脸、不能遮嘴、不能挡主字幕。

要求：
1. 只输出 JSON，不要 Markdown。
2. 最多 6 个贴纸，宁少勿多。
3. 贴纸必须来自真实口播关键词，不能编造地图、预算表截图、人物、足球、明星、车辆等无关元素。
4. 贴纸文字 4-12 个中文，口语化，适合地产/教育/身份规划短视频。
5. anchor 只能是 top_left/top_right/left_mid/right_mid/lower_left/lower_right。
6. tone 只能是 warning/money/school/home/location/legal/soft。

标题：{title or '未填写'}
完整口播：{script}
分段时间：
{seg_lines}

输出格式：
{{"stickers":[{{"segment_index":1,"trigger":"预算","text":"预算先算清","tone":"money","anchor":"right_mid"}}]}}
""".strip()
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你只输出严格 JSON。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.35,
        "stream": False,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            resp = await client.post(f"{base_url}/chat/completions", headers=headers, json=body)
        if resp.status_code >= 400:
            return None
        content = resp.json()["choices"][0]["message"]["content"]
        data = json.loads(re.search(r"\{.*\}", content, flags=re.S).group(0) if not content.strip().startswith("{") else content)
        stickers = data.get("stickers")
        return stickers if isinstance(stickers, list) else None
    except Exception:
        return None


async def plan_stickers(settings: Any, title: str, script: str, segments: List[TimedSegment], max_stickers: int = 6) -> List[StickerCue]:
    raw = await _ai_plan_raw(settings, title, script, segments)
    cues: List[StickerCue] = []
    used: set[str] = set()
    if raw:
        for item in raw:
            if not isinstance(item, dict):
                continue
            text = normalize_space(str(item.get("text") or ""))
            trigger = normalize_space(str(item.get("trigger") or ""))
            tone = normalize_space(str(item.get("tone") or "soft"))
            anchor = normalize_space(str(item.get("anchor") or "right_mid"))
            if not _valid_sticker_text(text) or text in used:
                continue
            seg: Optional[TimedSegment] = None
            try:
                idx = int(item.get("segment_index") or 0)
                seg = next((s for s in segments if s.index == idx), None)
            except Exception:
                seg = None
            if seg is None:
                seg = _find_segment_for_trigger(trigger, segments)
            if seg is None:
                continue
            x, y = ANCHORS.get(anchor, ANCHORS["right_mid"])
            start = max(seg.start + 0.12, 0.25)
            end = min(seg.end, start + 1.55)
            if end - start < 0.65:
                end = min(seg.end + 0.4, start + 1.2)
            cues.append(StickerCue(text=text, trigger=trigger, start=start, end=end, x=x, y=y, tone=tone))
            used.add(text)
            if len(cues) >= max_stickers:
                break
    if cues:
        return cues
    return _fallback_stickers(segments, max_stickers=max_stickers)
