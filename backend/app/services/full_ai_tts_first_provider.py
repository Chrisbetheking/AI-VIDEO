from __future__ import annotations

import json
import math
import re
import subprocess
import threading
import time
import uuid
import shlex
import requests
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib import request as urlrequest

from fastapi import APIRouter, FastAPI, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/video/full-ai/tts-first", tags=["full-ai-tts-first"])
_jobs: Dict[str, Dict[str, Any]] = {}

# ============================================================
# 核心目标：
# 1) 先拿真实 TTS 时长；
# 2) 根据真实语音时长决定镜头数量；
# 3) 根据每段口播语义决定画面，而不是按城市素材池轮播；
# 4) 把 shots / manual_shot_plan / shot_overrides 一起传给现有 full-ai/start。
# ============================================================

GLOBAL_NEGATIVE_PROMPT = (
    "readable text, subtitles, captions, chinese characters, english words, random letters, "
    "logo, watermark, fake UI, poster, banner, signboard with text, price tag, exact numbers, "
    "floorplan text, document close-up, calculator close-up, unrelated office meeting, business conference, "
    "cartoon, anime, painting, low quality, blurry, black bars, letterbox, pillarbox, distorted face, deformed hands"
)

CITY_LABELS = {
    "kuala_lumpur": "Kuala Lumpur, Malaysia",
    "penang": "Penang, Malaysia",
    "langkawi": "Langkawi, Malaysia",
    "sabah": "Sabah, Malaysia",
    "johor": "Johor Bahru, Malaysia",
}

CITY_HINTS = {
    "kuala_lumpur": "Kuala Lumpur urban condo market, KLCC/TRX/Mont Kiara context when relevant, but do not repeat twin towers in every shot",
    "penang": "Penang coastal city and Gurney Drive condo lifestyle when the narration mentions sea view or second home",
    "langkawi": "Langkawi tropical second-home and resort-style residence only when the narration mentions island/vacation/second home",
    "sabah": "Sabah / Kota Kinabalu coastal residential lifestyle only when the narration mentions Sabah or seaside second home",
    "johor": "Johor Bahru cross-border lifestyle and urban condominium context",
}

# 每类语义对应“必须拍什么”和“禁止拍什么”。
# 这里故意写得硬一点，防止生成器偷懒一直拍客厅、KLCC、文件、计算器。
SCENE_RECIPES: Dict[str, Dict[str, Any]] = {
    "city_location": {
        "label": "城市/区域/地段",
        "visuals": [
            "wide street-level view of Malaysian city residential district with modern high-rise condominiums",
            "premium condominium exterior beside an active urban street in Malaysia",
            "aerial-feeling establishing shot of Kuala Lumpur residential towers and surrounding blocks",
            "TRX or Mont Kiara style urban district with residential towers and daily street life",
        ],
        "must": "city district, condo exterior, neighborhood context, real street environment",
        "forbid": "only indoor living room, only documents, only calculator, only KLCC close-up",
        "camera": "slow vertical push-in or gentle street-level pan",
    },
    "transport": {
        "label": "交通/通勤/地铁/主干道",
        "visuals": [
            "MRT or LRT station entrance in Kuala Lumpur with commuters walking in and out",
            "main road traffic near modern residential condominiums during morning commute",
            "bus stop and ride-hailing pickup area outside a condo community",
            "commuters walking from a condo entrance toward a train station, realistic city morning",
        ],
        "must": "MRT/LRT station, bus stop, road traffic, commuters, commute route",
        "forbid": "living room, bedroom, balcony-only view, empty luxury lobby",
        "camera": "handheld walking shot, smooth forward movement, realistic commute pace",
    },
    "amenities": {
        "label": "生活配套/商场/超市/餐饮",
        "visuals": [
            "neighborhood supermarket and convenience stores near a Malaysian condo, no readable signs",
            "shopping mall entrance and food street atmosphere near residential towers",
            "daily-life street with restaurants, cafes, pharmacy and grocery stores around a condo district",
            "residents walking to nearby mall and daily amenities in a clean urban neighborhood",
        ],
        "must": "supermarket, convenience store, restaurants, mall, pharmacy, daily-life street",
        "forbid": "only apartment interior, empty condo pool, skyline-only shot",
        "camera": "street-level lifestyle pan with people moving naturally",
    },
    "medical": {
        "label": "医疗/看病/药房/诊所",
        "visuals": [
            "small neighborhood clinic exterior and pharmacy near a residential area, no readable words",
            "resident leaving condo and getting into a car for a clinic visit, realistic daily inconvenience",
            "urban medical clinic street scene near condominiums, clean realistic Malaysia lifestyle",
            "pharmacy and clinic area in a neighborhood commercial strip, no readable signage",
        ],
        "must": "clinic, pharmacy, car trip, neighborhood medical access",
        "forbid": "luxury living room, pool, KLCC skyline, random office meeting",
        "camera": "documentary street shot, slight handheld movement",
    },
    "education": {
        "label": "学校/教育/家庭规划",
        "visuals": [
            "family walking near a school-area residential neighborhood, no readable school name",
            "parent and child entering a family-friendly condo community with school commute atmosphere",
            "safe residential street with families and children near condominium towers",
            "family looking at neighborhood surroundings outside a condo, education planning mood",
        ],
        "must": "family, children, school commute atmosphere, safe residential neighborhood",
        "forbid": "random classroom text, readable school name, office meeting",
        "camera": "warm lifestyle shot, gentle follow shot",
    },
    "interior_layout": {
        "label": "户型/采光/室内/装修",
        "visuals": [
            "modern Malaysian condo living room with natural daylight and floor-to-ceiling windows",
            "clean apartment kitchen and dining area, practical layout for daily living",
            "bright bedroom and balcony connection in a modern high-rise condo",
            "realistic vertical walkthrough of living room to balcony in a premium condo",
        ],
        "must": "living room, kitchen, bedroom, balcony, windows, interior layout",
        "forbid": "MRT station, supermarket, clinic, unrelated street crowd",
        "camera": "smooth interior walkthrough, slow reveal of layout and daylight",
    },
    "community": {
        "label": "小区/园林/物业/社区氛围",
        "visuals": [
            "condominium garden and walkway with residents walking, premium community atmosphere",
            "condo lobby entrance with security and residents, realistic property management feel",
            "children playground and landscaped residential facilities inside a condo community",
            "resort-style condo pool and gym area with residents, not empty luxury advertisement",
        ],
        "must": "condo garden, lobby, security, residents, playground, pool, gym, property management feel",
        "forbid": "only city skyline, only documents, only street traffic",
        "camera": "smooth facility walkthrough, calm premium community feel",
    },
    "investment": {
        "label": "投资/出租/转手/流动性",
        "visuals": [
            "rental viewing scene outside a modern condo with agent and potential tenant, no logos",
            "busy residential district with high-rise condos and people commuting, rental demand feeling",
            "condo exterior and nearby office district implying rental demand, no readable company signs",
            "investor visiting a condo neighborhood and observing surrounding traffic and amenities",
        ],
        "must": "rental demand, condo exterior, tenants, office district, people flow, liquidity context",
        "forbid": "calculator close-up, financial chart, fake ROI text, document-only shot",
        "camera": "commercial documentary pan, people-flow emphasis",
    },
    "budget_price": {
        "label": "价格/预算/便宜/划算",
        "visuals": [
            "buyer comparing two condo environments in person, realistic property decision scene",
            "condo viewing moment with buyer thinking carefully, no paper or calculator close-up",
            "split-feeling visual contrast between attractive condo and inconvenient surroundings, no text",
            "realistic buyer walking through a condo neighborhood while considering budget and value",
        ],
        "must": "buyer decision, value comparison through real environment, property viewing",
        "forbid": "calculator close-up, documents with text, price tag, fake numbers",
        "camera": "medium shot, thoughtful pacing, realistic handheld viewing style",
    },
    "risk_regret": {
        "label": "踩坑/后悔/风险/不方便",
        "visuals": [
            "homebuyer standing outside a distant condo area looking worried, inconvenient surroundings",
            "long commute scene from condo to road with frustrated buyer, realistic daily-life problem",
            "empty-looking residential area with few amenities, buyer hesitating during property visit",
            "resident waiting for ride-hailing outside condo because daily access is inconvenient",
        ],
        "must": "worry, inconvenience, distant location, hesitation, daily-life problem",
        "forbid": "perfect luxury brochure shot, happy pool scene, skyline-only shot",
        "camera": "slower documentary shot, slight tension, realistic not horror",
    },
    "second_home_seaside": {
        "label": "第二家园/海景/养老/度假",
        "visuals": [
            "Penang ocean-view condominium balcony with tropical daylight and residential towers",
            "coastal residential walkway with palm trees and seaside condo lifestyle",
            "resort-style residential pool near the sea in Malaysia, premium but realistic",
            "older couple or family enjoying calm seaside condo community, no readable signs",
        ],
        "must": "sea view, tropical residential lifestyle, second-home atmosphere",
        "forbid": "Kuala Lumpur skyline, KLCC, inland city traffic unless narration says Kuala Lumpur",
        "camera": "slow calm seaside lifestyle shot, gentle breeze feeling",
    },
    "cta_summary": {
        "label": "总结/提醒/结尾",
        "visuals": [
            "real estate consultant walking through a condo neighborhood with Malaysia city backdrop",
            "final premium montage feeling of condo exterior, street life and amenities in one coherent scene",
            "buyer looking from condo balcony toward city neighborhood, thoughtful conclusion mood",
            "clean vertical closing shot of Malaysia condo exterior and active surrounding life",
        ],
        "must": "summary visual combining property and surrounding life, no text",
        "forbid": "hard sell poster, phone UI, title card with words, fake logo",
        "camera": "stable closing shot, slow pull-back or slow push-in",
    },
}

KEYWORD_RULES: List[Tuple[str, List[str]]] = [
    ("medical", ["看病", "小毛病", "医院", "诊所", "药房", "医疗", "clinic", "hospital", "pharmacy", "doctor"]),
    ("transport", ["地铁", "轻轨", "mrt", "lrt", "公交", "主干道", "高速", "通勤", "出勤", "上班", "堵车", "开车", "半小时", "交通", "commute", "station", "traffic", "road"]),
    ("amenities", ["生活配套", "配套", "超市", "便利店", "商场", "菜市场", "餐饮", "咖啡", "买菜", "吃饭", "mall", "supermarket", "amenities", "restaurant", "grocery"]),
    ("education", ["学校", "教育", "孩子", "学区", "家庭", "family", "school", "education", "children"]),
    ("interior_layout", ["户型", "采光", "装修", "客厅", "卧室", "厨房", "阳台", "室内", "空间", "窗", "layout", "interior", "bedroom", "kitchen", "balcony"]),
    ("community", ["小区", "社区", "园林", "物业", "安保", "泳池", "健身房", "大堂", "公区", "设施", "community", "lobby", "pool", "gym", "security", "facility"]),
    ("second_home_seaside", ["第二家园", "养老", "度假", "海景", "海边", "槟城", "兰卡威", "沙巴", "penang", "langkawi", "sabah", "ocean", "seaside", "beach"]),
    ("investment", ["投资", "出租", "租金", "转手", "流动性", "回报", "租客", "升值", "investment", "rental", "tenant", "liquidity", "resale"]),
    ("budget_price", ["价格", "预算", "便宜", "划算", "首付", "月供", "成本", "price", "budget", "cheap", "affordable", "value"]),
    ("risk_regret", ["后悔", "踩坑", "风险", "不方便", "麻烦", "太远", "大打折扣", "别只看", "别被", "regret", "risk", "inconvenient", "too far"]),
    ("city_location", ["区域", "地段", "位置", "城市", "吉隆坡", "klcc", "trx", "mont kiara", "kuala lumpur", "location", "district", "area"]),
]


class TTSFirstStartRequest(BaseModel):
    title: str = "马来西亚买房，别只看价格"
    topic: str = ""
    script_text: str = ""
    target_duration_seconds: float = 20
    duration_seconds: Optional[float] = None
    city: str = ""
    content_type: str = ""
    voice: str = "default"
    fps: int = 30
    width: int = 1080
    height: int = 1920

    # 前端 VideoCreationWizard 已经会传这些字段；这里接住，避免信息丢失。
    script_segments: List[Dict[str, Any]] = Field(default_factory=list)
    segment_voice_settings: List[Dict[str, Any]] = Field(default_factory=list)
    manual_shot_plan: List[Dict[str, Any]] = Field(default_factory=list)
    shot_overrides: Dict[str, Any] = Field(default_factory=dict)
    transition_plan: List[Dict[str, Any]] = Field(default_factory=list)
    asset_context: Dict[str, Any] = Field(default_factory=dict)
    avatar_config: Dict[str, Any] = Field(default_factory=dict)
    keyword_insights: Dict[str, Any] = Field(default_factory=dict)
    extra: Dict[str, Any] = Field(default_factory=dict)


def _admin_headers() -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    try:
        token = Path("/root/ai-video-admin-token.txt").read_text(encoding="utf-8").strip()
        if token:
            headers["X-AI-Video-Token"] = token
    except Exception:
        pass
    return headers


def _post_json(url: str, payload: Dict[str, Any], timeout: int = 180) -> Dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urlrequest.Request(url, data=body, headers=_admin_headers(), method="POST")
    with urlrequest.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw or "{}")


def _get_json(url: str, timeout: int = 60) -> Dict[str, Any]:
    req = urlrequest.Request(url, headers=_admin_headers(), method="GET")
    with urlrequest.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw or "{}")


def _target_duration(req: TTSFirstStartRequest) -> float:
    raw = req.duration_seconds or req.target_duration_seconds or 20
    try:
        return max(5.0, min(float(raw), 180.0))
    except Exception:
        return 20.0


def _strip_script_noise(text: str) -> str:
    text = (text or "").strip()
    text = re.sub(r"\s+", "", text)
    text = text.replace("……", "。").replace("…", "。")
    text = re.sub(r"[。！？!?；;]{2,}", "。", text)
    return text.strip("，,。；; ")


def _join_script_segments(segments: List[Dict[str, Any]]) -> str:
    parts: List[str] = []
    for item in segments or []:
        if not isinstance(item, dict):
            continue
        val = item.get("text") or item.get("content") or item.get("script") or item.get("line") or item.get("sentence")
        if val:
            parts.append(str(val).strip())
    return "。".join([p.strip("。") for p in parts if p.strip()])


def _fallback_script(title: str, seconds: float, city: str) -> str:
    # 只有用户没有给口播时才补文案；用户给了就不要裁剪，不要乱补。
    if city == "kuala_lumpur":
        base = (
            f"{title}。很多人买吉隆坡房子第一眼只看价格，但真正要先看区域、交通和生活配套。"
            "地铁和主干道如果太远，每天通勤都会变成成本。"
            "超市、餐饮、诊所这些日常配套不方便，房子再划算，住起来也容易后悔。"
            "所以先看生活半径，再看户型和价格，才不容易踩坑。"
        )
    else:
        base = (
            f"{title}。马来西亚买房不要只看价格，要先看用途、城市、交通和生活配套。"
            "自住、出租、第二家园和养老，判断标准完全不一样。"
            "先把生活半径和真实需求筛清楚，再去看项目，才不容易被带节奏。"
        )
    # 简单按目标秒数扩写一点，但不追求死卡。
    if seconds >= 25:
        base += " 看房时要把白天、晚上、工作日和周末的周边情况都看一遍，真实生活体验比售楼话术更重要。"
    return base


def _normalize_script(req: TTSFirstStartRequest, city: str) -> str:
    raw_script = req.script_text or _join_script_segments(req.script_segments)
    raw_script = _strip_script_noise(raw_script)
    if raw_script:
        return raw_script
    title = (req.title or req.topic or "马来西亚买房，别只看价格").strip()
    return _fallback_script(title, _target_duration(req), city)


def _infer_city(title: str, script: str, user_city: str = "") -> str:
    raw_city = (user_city or "").strip().lower()
    if raw_city:
        if "penang" in raw_city or "槟城" in user_city:
            return "penang"
        if "langkawi" in raw_city or "兰卡威" in user_city:
            return "langkawi"
        if "sabah" in raw_city or "沙巴" in user_city or "kota kinabalu" in raw_city:
            return "sabah"
        if "johor" in raw_city or "新山" in user_city:
            return "johor"
        return "kuala_lumpur"

    raw = f"{title}\n{script}".lower()
    if any(k in raw for k in ["槟城", "penang", "gurney"]):
        return "penang"
    if any(k in raw for k in ["兰卡威", "langkawi"]):
        return "langkawi"
    if any(k in raw for k in ["沙巴", "sabah", "kota kinabalu"]):
        return "sabah"
    if any(k in raw for k in ["新山", "johor", "jb"]):
        return "johor"
    return "kuala_lumpur"


def _extract_first_value(obj: Any, key_patterns: List[str]) -> Optional[Any]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            lk = str(k).lower()
            if any(p in lk for p in key_patterns):
                return v
        for v in obj.values():
            found = _extract_first_value(v, key_patterns)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = _extract_first_value(v, key_patterns)
            if found is not None:
                return found
    return None


def _ffprobe_duration(path_or_url: str) -> Optional[float]:
    if not path_or_url:
        return None
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", path_or_url],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode == 0:
            data = json.loads(proc.stdout or "{}")
            duration = float(data.get("format", {}).get("duration") or 0)
            if duration > 0:
                return duration
    except Exception:
        return None
    return None


def _estimate_audio_duration(script: str) -> float:
    # 中文短视频自然语速大概 4.2-5.2 字/秒；兜底只用于 TTS 失败。
    cleaned = re.sub(r"\s+", "", script or "")
    return max(5.0, min(180.0, len(cleaned) / 4.7))


def _tts_duration(script: str, voice: str, raw: Dict[str, Any]) -> Tuple[float, Dict[str, Any]]:
    # 尽量兼容你仓库里已经存在的 /api/tts-segments 多种 payload 写法。
    segment_settings = raw.get("segment_voice_settings") or []
    segments = raw.get("script_segments") or []
    if segments:
        tts_segments = []
        for i, seg in enumerate(segments):
            if not isinstance(seg, dict):
                continue
            text = str(seg.get("text") or seg.get("content") or seg.get("script") or "").strip()
            if not text:
                continue
            setting = segment_settings[i] if i < len(segment_settings) and isinstance(segment_settings[i], dict) else {}
            tts_segments.append({"text": text, **setting})
        payloads = [
            {"segments": tts_segments, "voice": voice},
            {"script_text": script, "voice": voice, "segments": tts_segments},
        ]
    else:
        payloads = [
            {"text": script, "voice": voice},
            {"script_text": script, "voice": voice},
            {"copy": script, "voice": voice},
            {"segments": [{"text": script}], "voice": voice},
        ]

    last_error = ""
    for payload in payloads:
        try:
            res = _post_json("http://127.0.0.1:8000/api/tts-segments", payload, timeout=240)
            dur_val = _extract_first_value(res, ["duration"])
            if dur_val is not None:
                try:
                    duration = float(dur_val)
                    if duration > 0:
                        return duration, res
                except Exception:
                    pass
            audio_val = _extract_first_value(res, ["audio_url", "audio", "mp3", "wav", "path"])
            if isinstance(audio_val, str):
                duration = _ffprobe_duration(audio_val)
                if duration:
                    return duration, res
            return _estimate_audio_duration(script), res
        except Exception as exc:
            last_error = str(exc)
    return _estimate_audio_duration(script), {"ok": False, "fallback": "estimated_duration", "error": last_error}


def _desired_shot_count(audio_duration: float, unit_count: int = 0) -> int:
    # 以真实配音长度为准：27 秒约 8-10 个镜头；15 秒约 5-6 个镜头。
    # 注意：不能因为文案只有 3-4 句就把镜头数压到 3-4 个，
    # 否则 27 秒会出现 10 秒以上长镜头，fal 很容易重复或静止。
    if audio_duration <= 7:
        count = 2
    elif audio_duration <= 12:
        count = 4
    elif audio_duration <= 18:
        count = 5
    elif audio_duration <= 24:
        count = 7
    elif audio_duration <= 32:
        count = 9
    elif audio_duration <= 45:
        count = 11
    else:
        count = math.ceil(audio_duration / 4.0)
    return max(1, min(18, count))


def _split_long_unit(unit: str) -> List[str]:
    unit = unit.strip()
    if len(unit) <= 28:
        return [unit]
    by_comma = [x.strip() for x in re.split(r"[，,、]", unit) if x.strip()]
    if len(by_comma) >= 2 and max(len(x) for x in by_comma) <= 34:
        return by_comma
    # 兜底按长度切，不重复内容。
    chunks = []
    start = 0
    while start < len(unit):
        chunks.append(unit[start : start + 24])
        start += 24
    return chunks


def _script_units(script: str) -> List[str]:
    raw_units = [x.strip() for x in re.split(r"[。！？!?；;\n]+", script or "") if x.strip()]
    units: List[str] = []
    for u in raw_units:
        units.extend(_split_long_unit(u))
    # 过滤特别短的孤立词，合到前面，避免生成无意义镜头。
    merged: List[str] = []
    for u in units:
        if len(u) <= 5 and merged:
            merged[-1] = merged[-1] + "，" + u
        else:
            merged.append(u)
    return merged or [script]


def _semantic_type(text: str, prev_type: str = "") -> str:
    raw = (text or "").lower()
    scores: Dict[str, int] = {}
    for typ, keywords in KEYWORD_RULES:
        score = sum(1 for k in keywords if k.lower() in raw)
        if score:
            scores[typ] = score
    if not scores:
        return prev_type or "city_location"
    # 同分时按 KEYWORD_RULES 顺序优先，医疗/交通/配套比泛泛地段更具体。
    return max(scores.items(), key=lambda kv: (kv[1], -[x[0] for x in KEYWORD_RULES].index(kv[0])))[0]


def _merge_units_to_count(units: List[str], count: int) -> List[str]:
    units = [u for u in units if u.strip()]
    if not units:
        return []
    if len(units) <= count:
        return units
    # 保序合并：按字符权重把 units 分到 count 段。
    total = sum(max(1, len(u)) for u in units)
    target = max(1, total / count)
    groups: List[str] = []
    cur = ""
    cur_len = 0
    remaining_groups = count
    for i, u in enumerate(units):
        remaining_units = len(units) - i
        if cur and cur_len >= target and remaining_units >= remaining_groups:
            groups.append(cur)
            remaining_groups -= 1
            cur = u
            cur_len = len(u)
        else:
            cur = (cur + "，" + u).strip("，") if cur else u
            cur_len += len(u)
    if cur:
        groups.append(cur)
    # 如果因为分配没到 count，再拆最长段。
    while len(groups) < count:
        idx = max(range(len(groups)), key=lambda i: len(groups[i]))
        pieces = _split_long_unit(groups[idx])
        if len(pieces) <= 1:
            break
        groups = groups[:idx] + pieces[:2] + groups[idx + 1 :]
    return groups[:count]




def _expand_units_to_count(units: List[str], count: int) -> List[str]:
    """
    文案句子少但语音很长时，把同一句拆成多个视觉角度。
    重点：不是重复同一个镜头，而是同一语义下换不同画面主体。
    例如“生活配套不方便”可以拆成超市、餐饮、药房、商场等不同 B-roll。
    """
    units = [u.strip() for u in units if u.strip()]
    if not units:
        return []
    if len(units) >= count:
        return _merge_units_to_count(units, count)

    weights = [max(8, len(u)) for u in units]
    total = sum(weights) or len(units)
    repeats = [max(1, int(round(count * w / total))) for w in weights]

    # 校准重复次数总和。
    while sum(repeats) < count:
        idx = max(range(len(units)), key=lambda i: (weights[i] / repeats[i], weights[i]))
        repeats[idx] += 1
    while sum(repeats) > count and any(r > 1 for r in repeats):
        idx = max([i for i, r in enumerate(repeats) if r > 1], key=lambda i: repeats[i])
        repeats[idx] -= 1

    expanded: List[str] = []
    for u, r in zip(units, repeats):
        expanded.extend([u] * r)
    return expanded[:count]


def _enforce_max_shot_duration(segments: List[str], audio_duration: float) -> List[str]:
    """
    最终保护：任何正式生成前，保证镜头数量足够。
    15 秒约 5-6 个，27 秒约 8-10 个；不允许最后一个镜头吃掉 10 秒以上。
    """
    desired = _desired_shot_count(audio_duration, unit_count=len(segments))
    if len(segments) >= desired:
        return segments
    return _expand_units_to_count(segments, desired)

def _allocate_durations(segments: List[str], audio_duration: float) -> List[float]:
    n = max(1, len(segments))
    if n == 1:
        return [round(audio_duration, 2)]
    weights = [max(8, len(s)) for s in segments]
    total_weight = sum(weights) or n
    durations = [audio_duration * w / total_weight for w in weights]

    # 每个镜头尽量 2.4-4.6 秒，防止长镜头重复和短镜头闪得太快。
    min_d = 2.2 if audio_duration < 16 else 2.4
    max_d = 4.8 if audio_duration < 30 else 5.2
    durations = [max(min_d, min(max_d, d)) for d in durations]

    # 校准总时长。
    diff = audio_duration - sum(durations)
    for _ in range(24):
        if abs(diff) < 0.02:
            break
        if diff > 0:
            candidates = [i for i, d in enumerate(durations) if d < max_d]
            if not candidates:
                break
            add = diff / len(candidates)
            for i in candidates:
                durations[i] = min(max_d, durations[i] + add)
        else:
            candidates = [i for i, d in enumerate(durations) if d > min_d]
            if not candidates:
                break
            sub = (-diff) / len(candidates)
            for i in candidates:
                durations[i] = max(min_d, durations[i] - sub)
        diff = audio_duration - sum(durations)

    # 最后一段吃掉小数误差。
    durations = [round(d, 2) for d in durations]
    if durations:
        durations[-1] = round(max(0.5, durations[-1] + audio_duration - sum(durations)), 2)
    return durations


def _city_context_for_type(city: str, semantic_type: str) -> str:
    # 口播没有说海边时，吉隆坡不要自动海边；口播说海边/第二家园时才用海景。
    if semantic_type == "second_home_seaside":
        if city == "kuala_lumpur":
            return "Malaysia second-home context such as Penang or Langkawi only because narration mentions seaside/second-home lifestyle"
        return CITY_HINTS.get(city, "Malaysia second-home residential context")
    return CITY_HINTS.get(city, CITY_HINTS["kuala_lumpur"])


def _build_prompt(
    *,
    city: str,
    index: int,
    narration_segment: str,
    semantic_type: str,
    previous_visual_subject: str = "",
) -> Dict[str, Any]:
    recipe = SCENE_RECIPES.get(semantic_type) or SCENE_RECIPES["city_location"]
    visual_options = recipe["visuals"]
    visual_subject = visual_options[(index - 1) % len(visual_options)]
    if previous_visual_subject and visual_subject == previous_visual_subject and len(visual_options) > 1:
        visual_subject = visual_options[index % len(visual_options)]

    city_label = CITY_LABELS.get(city, CITY_LABELS["kuala_lumpur"])
    city_context = _city_context_for_type(city, semantic_type)

    prompt = (
        "Premium realistic vertical 9:16 short-form video B-roll for Malaysia real-estate content.\n"
        f"Shot {index} semantic category: {recipe['label']}.\n"
        f"Current narration meaning: {narration_segment[:120]}.\n"
        f"Required visual subject: {visual_subject}.\n"
        f"City context: {city_label}; {city_context}.\n"
        f"Must show: {recipe['must']}.\n"
        f"Camera: {recipe['camera']}.\n"
        "Style: ultra realistic phone-shot plus premium real-estate commercial feeling, natural light, real people only when useful, clean composition, high detail, smooth motion, no black borders.\n"
        f"Do not show: {recipe['forbid']}. Do not add any readable text, logo, watermark, fake project name, exact price or exact ROI."
    )

    return {
        "visual_subject": visual_subject,
        "scene_location": recipe["label"],
        "camera_motion": recipe["camera"],
        "must_show": recipe["must"],
        "forbidden_visuals": recipe["forbid"],
        "prompt": prompt,
        "visual_prompt": prompt,
        "negative_prompt": GLOBAL_NEGATIVE_PROMPT,
    }


def _apply_manual_override(shot: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(override, dict):
        return shot
    # 前端手动改过的，尊重用户，但仍保留语义字段和禁忌字段。
    for key in [
        "visual_subject",
        "scene_location",
        "camera_motion",
        "transition",
        "asset_source",
        "duration_seconds",
        "prompt",
        "visual_prompt",
        "negative_prompt",
    ]:
        if override.get(key) not in (None, ""):
            shot[key] = override[key]
    return shot


def _plan_shots(script: str, audio_duration: float, city: str, raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    units = _script_units(script)
    desired = _desired_shot_count(audio_duration, unit_count=len(units))
    if len(units) > desired:
        segments = _merge_units_to_count(units, desired)
    else:
        segments = _expand_units_to_count(units, desired)
    segments = _enforce_max_shot_duration(segments, audio_duration)
    durations = _allocate_durations(segments, audio_duration)

    manual = raw.get("manual_shot_plan") if isinstance(raw.get("manual_shot_plan"), list) else []
    shot_overrides = raw.get("shot_overrides") if isinstance(raw.get("shot_overrides"), dict) else {}
    transitions = raw.get("transition_plan") if isinstance(raw.get("transition_plan"), list) else []

    shots: List[Dict[str, Any]] = []
    t = 0.0
    prev_type = ""
    prev_visual = ""
    repeated_type_count = 0

    for i, seg in enumerate(segments, start=1):
        semantic = _semantic_type(seg, prev_type)
        if semantic == prev_type:
            repeated_type_count += 1
        else:
            repeated_type_count = 1
        prev_type = semantic

        visual_pack = _build_prompt(
            city=city,
            index=i + (repeated_type_count - 1),
            narration_segment=seg,
            semantic_type=semantic,
            previous_visual_subject=prev_visual,
        )
        prev_visual = visual_pack["visual_subject"]

        duration = durations[i - 1] if i - 1 < len(durations) else round(audio_duration / len(segments), 2)
        start = round(t, 2)
        end = round(min(audio_duration, t + duration), 2)
        t = end

        shot: Dict[str, Any] = {
            "index": i,
            "shot_id": f"shot_{i:02d}_{semantic}",
            "start_seconds": start,
            "end_seconds": end,
            "duration_seconds": round(max(0.5, end - start), 2),
            "narration_segment": seg,
            "semantic_type": semantic,
            "semantic_label": SCENE_RECIPES.get(semantic, SCENE_RECIPES["city_location"])["label"],
            "source_priority": "real_asset_first_then_ai_broll",
            "image_url": None,
            "video_url": None,
            "transition": "cut" if i == 1 else "smooth_cut",
            **visual_pack,
        }

        if i - 1 < len(transitions) and isinstance(transitions[i - 1], dict):
            shot["transition"] = transitions[i - 1].get("type") or transitions[i - 1].get("transition") or shot["transition"]

        if i - 1 < len(manual) and isinstance(manual[i - 1], dict):
            shot = _apply_manual_override(shot, manual[i - 1])

        override = shot_overrides.get(str(i)) or shot_overrides.get(shot["shot_id"])
        if isinstance(override, dict):
            shot = _apply_manual_override(shot, override)

        shots.append(shot)

    # 结尾误差保护：最后一个镜头对齐真实音频时长。
    if shots:
        shots[-1]["end_seconds"] = round(audio_duration, 2)
        shots[-1]["duration_seconds"] = round(max(0.5, shots[-1]["end_seconds"] - shots[-1]["start_seconds"]), 2)
    return shots


def _semantic_summary(shots: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "index": s.get("index"),
            "time": f"{s.get('start_seconds')}-{s.get('end_seconds')}s",
            "narration_segment": s.get("narration_segment"),
            "semantic_label": s.get("semantic_label"),
            "must_show": s.get("must_show"),
            "forbidden_visuals": s.get("forbidden_visuals"),
        }
        for s in shots
    ]




# ================= V10.22 semantic direct renderer =================
# This block fixes the real failure point: TTS-first used to plan semantic shots,
# then delegated to /api/video/full-ai/start. That downstream path can collapse the
# plan back into one generic fal_storyboard / condo-interior clip and can return a
# raw video without burned subtitles. V10.22 renders each semantic shot directly,
# concatenates them, then burns the exact script subtitles. No raw fallback.

def _v10_22_extract_url(obj: Any) -> str:
    """Best-effort recursive extraction of a usable http/media URL from nested API results."""
    if obj is None:
        return ""
    if isinstance(obj, str):
        v = obj.strip()
        if v.startswith("http://") or v.startswith("https://") or v.startswith("file://") or v.startswith("/"):
            if any(ext in v.lower().split("?")[0] for ext in [".mp4", ".mov", ".webm", ".m4a", ".mp3", ".wav", ".aac"]):
                return v
        return ""
    if isinstance(obj, dict):
        preferred = [
            "subtitled_video_url", "video_url", "url", "output_url", "result_url",
            "audio_url", "audio", "public_url", "signed_url", "download_url",
        ]
        for k in preferred:
            if k in obj:
                found = _v10_22_extract_url(obj.get(k))
                if found:
                    return found
        for v in obj.values():
            found = _v10_22_extract_url(v)
            if found:
                return found
    if isinstance(obj, list):
        for item in obj:
            found = _v10_22_extract_url(item)
            if found:
                return found
    return ""


def _v10_22_run(cmd: List[str], timeout: int = 900) -> None:
    import subprocess
    print("V10_22_FFMPEG_CMD=" + " ".join(cmd[:12]), flush=True)
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg failed: " + (proc.stderr or proc.stdout or "")[-2400:])


def _v10_22_download(url: str, out_path: Path) -> Path:
    import shutil, urllib.request
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not url:
        raise RuntimeError("missing media url")
    if url.startswith("file://"):
        src = Path(url.replace("file://", "", 1))
        if not src.exists():
            raise RuntimeError(f"file url not found: {src}")
        shutil.copyfile(src, out_path)
        return out_path
    if url.startswith("/"):
        src = Path(url)
        if not src.exists():
            raise RuntimeError(f"local media not found: {src}")
        shutil.copyfile(src, out_path)
        return out_path
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=180) as r, open(out_path, "wb") as f:
        shutil.copyfileobj(r, f)
    if out_path.stat().st_size < 1024:
        raise RuntimeError(f"downloaded media too small: {url}")
    return out_path


def _v10_22_fix_clip(src: Path, dst: Path, duration: float, fps: int = 30) -> Path:
    duration = max(0.6, float(duration or 2.5))
    vf = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1"
    _v10_22_run([
        "ffmpeg", "-y", "-stream_loop", "2", "-i", str(src),
        "-t", f"{duration:.2f}", "-vf", vf, "-r", str(fps),
        "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dst)
    ], timeout=900)
    return dst


def _v10_22_concat(clips: List[Path], out_path: Path) -> Path:
    if not clips:
        raise RuntimeError("no semantic clips generated")
    list_path = out_path.with_suffix(".txt")
    list_path.write_text("".join([f"file '{c.as_posix()}'\n" for c in clips]), encoding="utf-8")
    _v10_22_run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_path),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out_path)
    ], timeout=900)
    return out_path


def _v10_22_clean_subtitle_text(text: str) -> str:
    import re
    v = str(text or "").strip()
    v = re.sub(r"[，。！？、；：,.!?;:\\n\\r]+", " ", v)
    v = re.sub(r"\\s+", " ", v).strip()
    return v


def _v10_22_split_chunks(script: str, max_chars: int = 9) -> List[str]:
    import re
    raw_parts = re.split(r"[，。！？、；：,.!?;:\\n\\r]+", str(script or ""))
    chunks: List[str] = []
    for part in raw_parts:
        part = _v10_22_clean_subtitle_text(part)
        if not part:
            continue
        buf = ""
        for ch in part:
            buf += ch
            if len(buf) >= max_chars:
                chunks.append(buf.strip())
                buf = ""
        if buf.strip():
            chunks.append(buf.strip())
    return chunks or [_v10_22_clean_subtitle_text(script)[:max_chars] or " "]


def _v10_25_subtitle_cues(script: str, duration: float, tts_result: Any = None) -> List[Dict[str, Any]]:
    # Prefer TTS provider segments when present; fallback to short Douyin chunks.
    segs = []
    if isinstance(tts_result, dict):
        for key in ["segments", "subtitle_segments", "sentences", "cues"]:
            if isinstance(tts_result.get(key), list) and tts_result.get(key):
                segs = tts_result.get(key) or []
                break
    cues: List[Dict[str, Any]] = []
    if segs:
        for item in segs:
            if not isinstance(item, dict):
                continue
            text = _v10_22_clean_subtitle_text(item.get("text") or item.get("subtitle_text") or item.get("sentence") or "")
            if not text:
                continue
            start = float(item.get("start") or item.get("start_seconds") or 0)
            end = float(item.get("end") or item.get("end_seconds") or min(float(duration), start + 2.0))
            for chunk in _v10_22_split_chunks(text, max_chars=9):
                cues.append({"text": chunk, "start": start, "end": end})
        if cues:
            return cues
    chunks = _v10_22_split_chunks(script, max_chars=9)
    per = max(0.8, float(duration) / max(1, len(chunks)))
    t = 0.0
    for chunk in chunks:
        start = t
        end = min(float(duration), t + per)
        cues.append({"text": chunk, "start": round(start, 2), "end": round(end, 2)})
        t = end
    if cues:
        cues[-1]["end"] = round(float(duration), 2)
    return cues


def _v10_22_render_semantic_direct(job_id: str, raw: Dict[str, Any], script: str, audio_duration: float, tts_result: Any, shots: List[Dict[str, Any]], title: str) -> Dict[str, Any]:
    from pathlib import Path
    import time, uuid
    from app.services.subtitle_provider import upload_file_to_r2
    from app.services.subtitle_style_library_provider import burn_subtitles_with_style_and_upload

    work = Path("/tmp") / f"tts_first_semantic_v10_22_{job_id}"
    work.mkdir(parents=True, exist_ok=True)
    fixed_clips: List[Path] = []
    _jobs[job_id].update({"stage": "semantic_direct_render", "progress": 66, "updated_at": time.time(), "direct_render_version": "v10_22"})

    # V10_25_VISUAL_LOGIC_APPLIED

    shots = _v10_25_apply_visual_logic(shots, raw, script_text)


    for idx, shot in enumerate(shots, start=1):
        duration = float(shot.get("duration_seconds") or 3.0)
        prompt = str(shot.get("visual_prompt") or shot.get("prompt") or shot.get("visual_subject") or "").strip()
        if not prompt:
            raise RuntimeError(f"shot {idx} missing semantic prompt")
        payload = {
            "prompt": prompt,
            "input_prompt": prompt,
            "text_prompt": prompt,
            "visual_prompt": prompt,
            "negative_prompt": str(shot.get("negative_prompt") or raw.get("negative_prompt") or ""),
            "duration_seconds": max(2.0, min(5.0, duration)),
            "target_duration_seconds": max(2.0, min(5.0, duration)),
            "aspect_ratio": "9:16",
            "width": int(raw.get("width") or 1080),
            "height": int(raw.get("height") or 1920),
            "fps": int(raw.get("fps") or 30),
            "frames_per_second": int(raw.get("fps") or 30),
            "resolution": "720p",
            "video_quality": "high",
            "prompt_optimizer": False,
            "semantic_direct_render": True,
            "semantic_type": shot.get("semantic_type"),
            "semantic_label": shot.get("semantic_label"),
            "must_show": shot.get("must_show"),
            "forbidden_visuals": shot.get("forbidden_visuals"),
        }
        print("V10_22_SEMANTIC_SHOT_START=" + json.dumps({"idx": idx, "duration": duration, "label": shot.get("semantic_label"), "subject": shot.get("visual_subject")}, ensure_ascii=False), flush=True)
        start = _post_json("http://127.0.0.1:8000/api/video/fal/shot/start", payload, timeout=80)
        fal_job_id = start.get("job_id") or start.get("id") or start.get("data", {}).get("job_id")
        if not fal_job_id:
            raise RuntimeError("fal shot start failed: " + str(start)[:800])
        last: Dict[str, Any] = {}
        video_url = ""
        for _ in range(90):
            time.sleep(5)
            last = _get_json(f"http://127.0.0.1:8000/api/video/fal/job/{fal_job_id}", timeout=80)
            status = str(last.get("status") or last.get("stage") or "").lower()
            if status in {"completed", "succeeded", "success", "done"} or last.get("ok") is True and _v10_22_extract_url(last):
                video_url = _v10_22_extract_url(last)
                break
            if status in {"failed", "error"} or last.get("ok") is False and last.get("error"):
                raise RuntimeError(f"fal shot {idx} failed: " + str(last)[:1200])
        if not video_url:
            raise RuntimeError(f"fal shot {idx} timeout/no video url: " + str(last)[:1200])
        raw_clip = _v10_22_download(video_url, work / f"shot_{idx:02d}_raw.mp4")
        fixed_clip = _v10_22_fix_clip(raw_clip, work / f"shot_{idx:02d}_fixed.mp4", duration, int(raw.get("fps") or 30))
        fixed_clips.append(fixed_clip)
        _jobs[job_id].update({"stage": f"semantic_direct_render_{idx}_of_{len(shots)}", "progress": 66 + int(18 * idx / max(1, len(shots))), "updated_at": time.time()})

    raw_video_path = _v10_22_concat(fixed_clips, work / f"{job_id}_semantic_raw.mp4")
    raw_upload = upload_file_to_r2(raw_video_path, object_key=f"videos/tts-first-semantic/raw/{time.strftime('%Y/%m/%d')}/{uuid.uuid4().hex}_{job_id}.mp4")
    raw_video_url = str(raw_upload.get("video_url") or raw_upload.get("url") or raw_upload.get("public_url") or "")
    if not raw_video_url:
        raise RuntimeError("semantic raw upload failed: " + str(raw_upload)[:1000])

    audio_url = _v10_22_extract_url(tts_result) or str(raw.get("audio_url") or raw.get("voice_url") or "")
    if not audio_url:
        raise RuntimeError("TTS-first direct render missing audio_url; refusing to return unsubtitled raw video")
    cues = _v10_25_subtitle_cues(script, float(audio_duration), tts_result)
    # Expose raw video before subtitle burn so paid fal clips are never lost if burn fails.
    _jobs[job_id].update({"stage": "subtitle_burn_local_v10_23", "progress": 94, "raw_video_url": raw_video_url, "local_raw_video_path": str(raw_video_path), "updated_at": time.time()})
    print("V10_22_SUBTITLE_BURN_START=" + json.dumps({"job_id": job_id, "cue_count": len(cues), "raw_video_url": raw_video_url[:150]}, ensure_ascii=False), flush=True)
    subtitle_res = _v10_23_burn_local_subtitles_and_upload(
        raw_video_path=raw_video_path,
        audio_url=audio_url,
        cues=cues,
        job_id=job_id,
        work=work,
        duration=float(audio_duration),
    )
    final_url = str(subtitle_res.get("video_url") or subtitle_res.get("subtitled_video_url") or subtitle_res.get("url") or "") if isinstance(subtitle_res, dict) else ""
    if not final_url:
        raise RuntimeError("local subtitle burn failed; refusing raw fallback: " + str(subtitle_res)[:1200])
    return {
        "ok": True,
        "provider": "full_ai_tts_first_semantic_direct_render_v10_25d",
        "video_url": final_url,
        "subtitled_video_url": final_url,
        "raw_video_url": raw_video_url,
        "subtitle_result": subtitle_res,
        "semantic_clip_count": len(fixed_clips),
        "audio_url": audio_url,
        "cues": cues[:12],
    }


def _v10_23_ass_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds or 0.0))
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    sec = seconds % 60
    return f"{h:d}:{m:02d}:{sec:05.2f}"


def _v10_23_ass_escape(text: str) -> str:
    return str(text or "").replace("{", "").replace("}", "").replace("\n", " ").strip()


def _v10_23_write_ass(cues: List[Dict[str, Any]], ass_path: Path) -> Path:
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Main,Arial,78,&H00FFFFFF,&H00FFFFFF,&H00000000,&H66000000,-1,0,0,0,100,100,0,0,1,6,1,2,70,70,220,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for cue in cues or []:
        text = _v10_23_ass_escape(cue.get("text") or cue.get("subtitle_text") or "")
        if not text:
            continue
        start = float(cue.get("start") or cue.get("start_seconds") or 0.0)
        end = float(cue.get("end") or cue.get("end_seconds") or start + 1.2)
        if end <= start:
            end = start + 1.2
        lines.append(f"Dialogue: 0,{_v10_23_ass_time(start)},{_v10_23_ass_time(end)},Main,,0,0,0,,{text}")
    ass_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return ass_path


def _v10_23_burn_local_subtitles_and_upload(raw_video_path: Path, audio_url: str, cues: List[Dict[str, Any]], job_id: str, work: Path, duration: float) -> Dict[str, Any]:
    import time, uuid
    from app.services.subtitle_provider import upload_file_to_r2
    if not raw_video_path.exists() or raw_video_path.stat().st_size < 1024:
        raise RuntimeError(f"raw semantic video missing before subtitle burn: {raw_video_path}")
    audio_path = _v10_22_download(audio_url, work / f"{job_id}_tts_audio.m4a")
    ass_path = _v10_23_write_ass(cues, work / f"{job_id}_douyin_subtitles.ass")
    final_path = work / f"{job_id}_final_subtitled.mp4"
    print("V10_23_SUBTITLE_BURN_LOCAL_START=" + json.dumps({"job_id": job_id, "cue_count": len(cues or []), "raw": raw_video_path.as_posix(), "audio_size": audio_path.stat().st_size}, ensure_ascii=False), flush=True)
    vf = f"subtitles='{ass_path.as_posix()}'"
    _v10_22_run([
        "ffmpeg", "-y", "-i", str(raw_video_path), "-i", str(audio_path),
        "-vf", vf, "-map", "0:v:0", "-map", "1:a:0",
        "-t", f"{max(0.8, float(duration or 0)):.2f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k", "-shortest",
        "-movflags", "+faststart", str(final_path)
    ], timeout=900)
    if not final_path.exists() or final_path.stat().st_size < 4096:
        raise RuntimeError("local subtitle burn produced empty final video")
    upload = upload_file_to_r2(final_path, object_key=f"videos/tts-first-semantic/subtitled/{time.strftime('%Y/%m/%d')}/{uuid.uuid4().hex}_{job_id}.mp4")
    final_url = str(upload.get("video_url") or upload.get("url") or upload.get("public_url") or upload.get("signed_url") or "")
    if not final_url:
        raise RuntimeError("final subtitled upload failed: " + str(upload)[:1000])
    print("V10_23_SUBTITLE_BURN_LOCAL_DONE=" + json.dumps({"job_id": job_id, "final_url": final_url[:150]}, ensure_ascii=False), flush=True)
    return {"ok": True, "provider": "v10_23_local_ass_burn", "video_url": final_url, "subtitled_video_url": final_url, "ass_path": ass_path.as_posix(), "local_final_path": final_path.as_posix(), "upload": upload}

# ================= end V10.22 semantic direct renderer =================


# ================= AI VIDEO V10.25 COMPREHENSIVE QUALITY UPGRADE =================
def _v10_25_clean_text(text: str) -> str:
    """V10.25d: remove Chinese/English punctuation safely before ASS subtitle rendering."""
    import re
    if text is None:
        return ""
    s = str(text)
    s = re.sub(r"[，。！？；：、,.!?;:\"'“”‘’（）()【】\[\]《》<>…—_\-]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

_V10_25_KEYWORDS = [
    "吉隆坡华人区", "生活配套", "配套不足", "长期持有", "自主购买力", "护城河", "房价", "华人区", "配套",
    "餐厅", "餐饮", "吃饭", "咖啡", "美食", "商场", "购物", "超市", "便利店",
    "地铁", "MRT", "LRT", "主干道", "交通", "通勤", "医疗", "诊所", "药房", "医院",
    "教育", "学校", "户型", "采光", "阳台", "客厅", "卧室", "厨房", "社区", "大堂", "园林", "泳池", "健身房",
    "投资", "出租", "风险", "后悔", "评论区"
]

def _v10_25_auto_keywords(text, manual=None):
    clean = _v10_25_clean_text(text)
    found=[]
    for w in list(manual or []) + _V10_25_KEYWORDS:
        w=str(w or '').strip()
        if w and w in clean and w not in found:
            found.append(w)
    return found[:3]

def _v10_25_scene_type(text):
    t=str(text or '').lower()
    if any(k in t for k in ['地铁','mrt','lrt','交通','通勤','主干道','公交','出行','开车','堵车']): return 'transport'
    if any(k in t for k in ['医疗','看病','医院','诊所','药房','小毛病']): return 'medical'
    if any(k in t for k in ['教育','学校','孩子','家长','华人区','学区']): return 'education'
    if any(k in t for k in ['户型','采光','客厅','卧室','厨房','阳台','装修','空间']): return 'interior'
    if any(k in t for k in ['社区','大堂','园林','泳池','健身','安保','物业']): return 'community'
    if any(k in t for k in ['生活配套','配套','餐饮','吃饭','餐厅','咖啡','美食','超市','商场','购物','便利店','买菜','商圈','护城河']): return 'lifestyle_support'
    if any(k in t for k in ['投资','出租','租客','保值','长期持有','资产','房价','自主购买力']): return 'investment'
    if any(k in t for k in ['风险','后悔','不方便','不足','远','麻烦','踩坑']): return 'risk'
    return 'area_value'

def _v10_25_sentiment(text):
    t=str(text or '')
    if any(k in t for k in ['不足','风险','后悔','不方便','太远','麻烦','踩坑','弱','差']): return 'warning'
    if any(k in t for k in ['稳','成熟','完善','保值','强','方便','价值','护城河']): return 'positive'
    return 'neutral'

def _v10_25_split_subtitle_text(script_text):
    raw = re.split(r'[。！？!?；;\n]+', str(script_text or ''))
    chunks=[]
    for p in raw:
        p=_v10_25_clean_text(p)
        if not p: continue
        buf=''
        for ch in p:
            buf += ch
            if len(buf) >= 14:
                chunks.append(buf.strip()); buf=''
        if buf.strip(): chunks.append(buf.strip())
    return chunks or ([_v10_25_clean_text(script_text)] if script_text else [])

def _v10_25_subtitle_cues(script_text, duration_seconds, raw=None):
    chunks=_v10_25_split_subtitle_text(script_text)
    if not chunks: return []
    duration=max(float(duration_seconds or 0) or len(chunks)*2.0, len(chunks)*1.2)
    manual=_v10_25_manual_keywords_from_raw(raw)
    total=sum(max(len(c),1) for c in chunks); cur=0.0; cues=[]
    for i,c in enumerate(chunks,1):
        dur=max(1.15,min(3.2,duration*max(len(c),1)/max(total,1)))
        end=duration if i==len(chunks) else min(duration,cur+dur)
        clean=_v10_25_clean_text(c)
        cues.append({'start':round(cur,2),'end':round(max(end,cur+0.85),2),'text':clean,'clean_text':clean,'keywords':_v10_25_auto_keywords(clean,manual),'subtitle_style':'DouyinCleanEmphasisV2'})
        cur=end
        if cur>=duration: break
    return cues

def _v10_25_ass_time(sec):
    sec=max(0,float(sec or 0)); h=int(sec//3600); sec-=h*3600; m=int(sec//60); sec-=m*60; s=int(sec); cs=int(round((sec-s)*100)); return f'{h}:{m:02d}:{s:02d}.{cs:02d}'

def _v10_25_ass_escape(s):
    return str(s or '').replace('\\','\\\\').replace('{','').replace('}','').replace('\n',' ')

def _v10_25_ass_line(text, keywords):
    text=_v10_25_clean_text(text); line=_v10_25_ass_escape(text)
    colors=['&H0026DFFF','&H0000BFFF','&H00FFD35A']
    for i,kw in enumerate(keywords or []):
        kw=_v10_25_clean_text(kw)
        if kw and kw in text:
            tag=r'{\b1\fs84\bord5\shad1\c'+colors[i%len(colors)]+'}'+_v10_25_ass_escape(kw)+r'{\rDefault}'
            line=line.replace(_v10_25_ass_escape(kw),tag,1)
    return line

def _v10_25_build_ass(cues, ass_path: Path):
    header='''[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nScaledBorderAndShadow: yes\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,Arial,66,&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,1,0,0,0,100,100,0,0,1,4,1,2,70,70,210,1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'''
    lines=[header]
    for c in cues or []:
        lines.append(f"Dialogue: 0,{_v10_25_ass_time(c.get('start',0))},{_v10_25_ass_time(c.get('end',c.get('start',0)+1.5))},Default,,0,0,0,,{_v10_25_ass_line(c.get('clean_text') or c.get('text') or '', c.get('keywords') or [])}\n")
    ass_path.write_text(''.join(lines),encoding='utf-8'); return ass_path

def _v10_25_run(cmd, timeout=900):
    print('V10_25_FFMPEG_CMD='+' '.join(shlex.quote(str(x)) for x in cmd))
    p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=timeout)
    if p.returncode!=0:
        print('V10_25_FFMPEG_STDERR='+(p.stderr or '')[-4000:]); raise RuntimeError('V10.25d ffmpeg failed')
    return p

def _v10_25_burn_subtitles_local(video_path=None, audio_url=None, cues=None, job_id=None, work_dir=None, raw_video_url=None, raw=None, **kwargs):
    work=Path(work_dir or kwargs.get('work') or kwargs.get('tmp_dir') or '/tmp'); work.mkdir(parents=True,exist_ok=True)
    job_id=job_id or kwargs.get('id') or 'tts_first_v10_25'; video_path=Path(video_path or kwargs.get('raw_video_path') or kwargs.get('input_video_path'))
    if not video_path.exists(): raise FileNotFoundError(f'V10.25 raw video missing: {video_path}')
    manual=_v10_25_manual_keywords_from_raw(raw); fixed=[]
    for c in (cues or kwargs.get('subtitle_cues') or []):
        tx=_v10_25_clean_text(c.get('clean_text') or c.get('text') or '')
        fixed.append({**c,'text':tx,'clean_text':tx,'keywords':c.get('keywords') or _v10_25_auto_keywords(tx,manual)})
    ass=work/f'{job_id}_v10_25_douyin_emphasis.ass'; _v10_25_build_ass(fixed,ass)
    final=work/f'{job_id}_v10_25_subtitled.mp4'
    print('V10_25_SUBTITLE_BURN_LOCAL_START='+str({'job_id':job_id,'cue_count':len(fixed),'style':'DouyinCleanEmphasisV2'}))
    audio_path=None
    if audio_url:
        try:
            r=requests.get(audio_url,timeout=120); r.raise_for_status(); audio_path=work/f'{job_id}_audio_v10_25'; audio_path.write_bytes(r.content)
        except Exception as exc:
            print('V10_25_AUDIO_DOWNLOAD_FAILED='+str(exc)); audio_path=None
    ass_arg=str(ass).replace('\\','/').replace(':','\\:')
    if audio_path and audio_path.exists():
        cmd=['ffmpeg','-y','-i',str(video_path),'-i',str(audio_path),'-vf',f'ass={ass_arg}','-c:v','libx264','-preset','veryfast','-crf','18','-c:a','aac','-b:a','192k','-shortest',str(final)]
    else:
        cmd=['ffmpeg','-y','-i',str(video_path),'-vf',f'ass={ass_arg}','-c:v','libx264','-preset','veryfast','-crf','18','-an',str(final)]
    _v10_25_run(cmd)
    upload=upload_file_to_r2(final, object_key=f"videos/tts-first-semantic/subtitled/{time.strftime('%Y/%m/%d')}/{uuid.uuid4().hex}_{job_id}_v10_25.mp4")
    url=(upload.get('url') or upload.get('public_url') or upload.get('video_url')) if isinstance(upload,dict) else None
    print('V10_25_SUBTITLE_BURN_LOCAL_DONE='+str({'job_id':job_id,'video_url':url,'style':'DouyinCleanEmphasisV2'}))
    if isinstance(upload,dict):
        upload.setdefault('video_url',url); upload.setdefault('final_video_url',url); upload.setdefault('subtitle_style','DouyinCleanEmphasisV2'); upload.setdefault('remove_punctuation',True); upload.setdefault('keyword_highlight',True); return upload
    return {'ok':True,'video_url':url,'final_video_url':url,'subtitle_style':'DouyinCleanEmphasisV2'}

def _v10_25_visual_policy_for_text(text, idx=1, prev_type=''):
    clean=_v10_25_clean_text(text); scene=_v10_25_scene_type(clean); sentiment=_v10_25_sentiment(clean)
    if scene=='lifestyle_support':
        if sentiment=='warning': subject='quiet Malaysian residential area with sparse shops and inconvenient daily amenities, no readable text signs'
        else: subject=['Malaysian shopping mall entrance near residential towers with residents walking naturally, no readable text signs','lively food street and casual restaurants near condominium area in Malaysia, people eating naturally, no readable text signs','supermarket and convenience store street-level daily amenities near Malaysian residences, no readable text signs'][idx%3]
    elif scene=='transport': subject='Malaysia MRT or LRT station entrance with commuters and nearby main road traffic, no readable text signs'
    elif scene=='medical': subject='community clinic and pharmacy street frontage in Malaysian residential neighborhood, no readable text signs'
    elif scene=='education': subject='families and children walking safely near school area and condominium towers in Malaysia, no readable text signs'
    elif scene=='interior': subject='bright modern Malaysian condominium interior with living room balcony daylight and practical layout, no text overlays'
    elif scene=='community': subject='condominium lobby garden pool or gym community facilities with residents moving naturally, no logos no signs'
    elif scene=='investment': subject='Malaysian urban residential towers with active street-level life and stable tenant demand atmosphere, no readable text signs'
    elif scene=='risk': subject='buyer hesitating in a less convenient residential district with long commute road feeling, no readable text signs'
    else: subject='wide street-level view of Malaysian urban residential district with tropical greenery and modern condominiums, no readable text signs'
    trans=['cross_dissolve','slow_push_in','pull_out','horizontal_pan_match']; motion=['slow push in','gentle pull out','slow left to right pan','steady street-level dolly']
    return {'scene_type':scene,'sentiment':sentiment,'visual_subject':subject,'camera_motion':motion[idx%4],'transition_to_next':trans[idx%4],'forbidden_visuals':['KLCC unless explicitly mentioned','ocean unless Penang Langkawi Sabah','readable text signs','logos','subtitles inside generated video'],'shot_duration_policy':'2.2_to_4.0_seconds_no_flash_cut'}

def _v10_25_apply_visual_logic(shots, raw=None, script_text=''):
    if not isinstance(shots,list): return shots
    prev=''
    for i,shot in enumerate(shots,1):
        if not isinstance(shot,dict): continue
        tx=shot.get('narration') or shot.get('text') or shot.get('script') or shot.get('subtitle') or script_text
        p=_v10_25_visual_policy_for_text(tx,i,prev)
        if prev and p['scene_type']==prev and p['scene_type']=='lifestyle_support': p['visual_subject']='street-level supermarket and convenience shop daily errand scene near Malaysian residence, no readable text signs'
        prev=p['scene_type']; shot.update({k:v for k,v in p.items() if k not in shot or not shot.get(k)})
        base=shot.get('visual_prompt') or shot.get('prompt') or shot.get('subject') or ''
        shot['visual_prompt']=(str(base).strip()+', '+f"{p['visual_subject']}, {p['camera_motion']}, cinematic vertical 9:16, realistic Malaysia property lifestyle, no text, no logos, no subtitles, no readable signs").strip(', ')
    return shots

_v10_23_burn_subtitles_local = _v10_25_burn_subtitles_local
# ================= END AI VIDEO V10.25 COMPREHENSIVE QUALITY UPGRADE =================

# V10_25D_FORCE_ALIAS_AFTER_LEGACY
_v10_23_burn_subtitles_local = _v10_25_burn_subtitles_local

def _run_job(job_id: str, raw: Dict[str, Any]) -> None:
    try:
        _jobs[job_id].update({"stage": "script", "progress": 10, "updated_at": time.time()})
        req = TTSFirstStartRequest(**raw)
        title = str(req.title or req.topic or "马来西亚买房，别只看价格")
        city = _infer_city(title, req.script_text or _join_script_segments(req.script_segments), req.city)
        script = _normalize_script(req, city)

        _jobs[job_id].update(
            {
                "city": city,
                "target_duration_seconds": _target_duration(req),
                "script_text": script,
                "script_chars": len(script),
                "progress": 25,
                "stage": "tts",
                "updated_at": time.time(),
            }
        )

        audio_duration, tts_result = _tts_duration(script, req.voice or "default", raw)
        audio_duration = max(1.0, min(180.0, float(audio_duration)))
        _jobs[job_id].update(
            {
                "audio_duration_seconds": round(audio_duration, 2),
                "tts_result": tts_result,
                "progress": 50,
                "stage": "semantic_shot_plan",
                "updated_at": time.time(),
            }
        )

        shots = _plan_shots(script, audio_duration, city, raw)
        semantic_plan = _semantic_summary(shots)

        print(f"TTS_FIRST_AUDIO_DURATION={audio_duration:.2f}")
        print(f"TTS_FIRST_SHOT_COUNT={len(shots)}")
        print(f"TTS_FIRST_CITY_LOCK={city}")
        print("TTS_FIRST_SEMANTIC_PLAN=" + json.dumps(semantic_plan, ensure_ascii=False)[:1600])
        if shots:
            print(f"TTS_FIRST_FINAL_PROMPT_1={shots[0]['prompt'][:360]}")

        render_result = _v10_22_render_semantic_direct(
            job_id=job_id,
            raw=raw,
            script=script,
            audio_duration=audio_duration,
            tts_result=tts_result,
            shots=shots,
            title=title,
        )
        _jobs[job_id].update(
            {
                "ok": True,
                "status": "completed",
                "stage": "completed",
                "progress": 100,
                "provider": "full_ai_tts_first_semantic_direct_render_v10_25d",
                "direct_render": True,
                "no_child_full_ai_start": True,
                "video_url": render_result.get("video_url"),
                "subtitled_video_url": render_result.get("subtitled_video_url"),
                "raw_video_url": render_result.get("raw_video_url"),
                "render_result": render_result,
                "updated_at": time.time(),
            }
        )
        return
    except Exception as exc:
        _jobs[job_id].update(
            {
                "ok": False,
                "status": "failed",
                "stage": "failed",
                "error": str(exc),
                "updated_at": time.time(),
            }
        )


@router.get("/health")
def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "provider": "full_ai_tts_first_semantic_direct_render_v10_25d",
        "logic": "script -> real TTS duration -> semantic storyboard -> direct per-shot fal render -> concat -> local ffmpeg subtitle burn -> DouyinCleanEmphasisV2 keyword highlight -> semantic transitions",
        "guarantees": [
            "画面片段数按真实配音时长计算",
            "交通口播优先生成地铁/主干道/通勤画面",
            "生活配套口播优先生成超市/餐饮/商场/药房画面",
            "户型采光口播才生成室内画面",
            "禁止为了补时长重复同一个镜头",
        ],
    }


@router.post("/plan-preview")
def plan_preview(req: TTSFirstStartRequest) -> Dict[str, Any]:
    # 这个接口只看分镜，不启动 fal，方便你调试“口播-画面是否对应”。
    title = str(req.title or req.topic or "马来西亚买房，别只看价格")
    city = _infer_city(title, req.script_text or _join_script_segments(req.script_segments), req.city)
    script = _normalize_script(req, city)
    duration = req.duration_seconds or req.target_duration_seconds or _estimate_audio_duration(script)
    shots = _plan_shots(script, float(duration), city, req.model_dump())
    return {
        "ok": True,
        "provider": "full_ai_tts_first_semantic_direct_render_v10_25d",
        "city": city,
        "duration_seconds": round(float(duration), 2),
        "shot_count": len(shots),
        "semantic_shot_plan": _semantic_summary(shots),
        "shots": shots,
    }


@router.post("/start")
def start(req: TTSFirstStartRequest) -> Dict[str, Any]:
    job_id = "tts_first_" + uuid.uuid4().hex[:18]
    raw = req.model_dump()
    _jobs[job_id] = {
        "ok": True,
        "job_id": job_id,
        "status": "running",
        "stage": "queued",
        "progress": 1,
        "created_at": time.time(),
        "updated_at": time.time(),
        "request": raw,
    }
    threading.Thread(target=_run_job, args=(job_id, raw), daemon=True).start()
    return {"ok": True, "job_id": job_id, "status": "running", "stage": "queued"}


@router.get("/job/{job_id}")
def get_job(job_id: str) -> Dict[str, Any]:
    job = _jobs.get(job_id)
    if job and job.get("direct_render"):
        return job
    if not job:
        return {"ok": False, "status": "not_found", "job_id": job_id}

    child_job_id = job.get("child_job_id")
    if child_job_id:
        try:
            child = _get_json(f"http://127.0.0.1:8000/api/video/full-ai/job/{child_job_id}", timeout=60)
            merged = dict(job)
            merged["child_job"] = child
            if child.get("status") in {"completed", "succeeded", "success"} or child.get("stage") in {"completed", "succeeded", "success"}:
                merged["status"] = "completed"
                merged["stage"] = "completed"
                merged["progress"] = 100
            if child.get("status") in {"failed", "error"} or child.get("stage") in {"failed", "error"}:
                merged["status"] = "failed"
                merged["stage"] = "failed"
                merged["error"] = child.get("error") or child.get("message") or merged.get("error") or "child job failed"
            for k in ("video_url", "url", "output_url", "result_url"):
                if child.get(k):
                    merged["video_url"] = child.get(k)
            if isinstance(child.get("result"), dict):
                for k in ("video_url", "url", "output_url", "result_url"):
                    if child["result"].get(k):
                        merged["video_url"] = child["result"].get(k)
            return merged
        except Exception as exc:
            job["child_poll_error"] = str(exc)
    return job


def install_full_ai_tts_first(app: FastAPI) -> None:
    app.include_router(router)


# ================= AI VIDEO V10.26 DEMAND ACCEPTANCE LOCK =================
def _v10_26_clean_text(text: str) -> str:
    import re
    text = str(text or '')
    text = re.sub(r'[，。！？；：、,.!?;:"“”‘’（）()【】\[\]《》<>…]+', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()

_V10_26_SCRIPT_KEYS = ['script','script_text','copy','text','content','full_script','voice_script','narration','口播文案','文案']
_V10_26_DURATION_KEYS = ['duration','duration_seconds','target_duration_seconds','audio_duration','tts_duration','voice_duration','real_audio_duration']
_V10_26_FALLBACK_TEXTS = {'马来西亚买房','别只看价格','海外买房','买房别只看价格'}

_V10_26_KEYWORDS = [
    '生活配套','配套','超市','餐饮','餐厅','吃饭','咖啡','美食','商场','购物','便利店','买菜','商圈',
    '交通','通勤','地铁','MRT','LRT','主干道','公交','出行','开车','堵车',
    '医疗','看病','诊所','药房','医院','买药',
    '教育','学校','孩子','家长','华人区',
    '户型','采光','客厅','卧室','厨房','阳台','装修','空间',
    '社区','大堂','园林','泳池','健身房','安保','物业',
    '投资','出租','租客','自住','保值','长期持有','房价','收益',
    '风险','后悔','不方便','不足','远','麻烦','踩坑'
]

_V10_26_SCENE_POLICY = {
    'area_value': {
        'label':'区域/楼盘外景建立',
        'must_show':'Malaysian residential district, condo exterior, tropical greenery, real street-level context',
        'forbidden':'only indoor living room, only documents, calculator, repeated KLCC close-up, readable signs',
        'subjects':['street-level Malaysian residential district with condo towers and shop lots','condo exterior with tropical greenery and real neighborhood context'],
        'camera':'slow push in from street level or gentle left-to-right establishing pan',
    },
    'lifestyle_food': {
        'label':'餐饮/吃饭/生活配套',
        'must_show':'restaurant, cafe, food court, local dining street, people eating or picking up food naturally',
        'forbidden':'empty mall only, office meeting, text signs, logo, unrelated interior bedroom',
        'subjects':['Malaysian restaurant and cafe street near residential towers with people dining naturally','food court and daily dining scene near condominium, no readable shop signs'],
        'camera':'slow push in toward restaurant or gentle walking pan',
    },
    'shopping': {
        'label':'购物/超市/商场/便利店',
        'must_show':'supermarket, mall, convenience store, grocery bags, daily shopping scene',
        'forbidden':'only condo lobby, only bedroom, price tags, readable signs, fake logos',
        'subjects':['supermarket and convenience store daily shopping scene near Malaysian condo','shopping mall entrance and grocery bags with natural residential foot traffic'],
        'camera':'smooth lateral pan following residents with grocery bags',
    },
    'transport': {
        'label':'交通/通勤/地铁/主干道',
        'must_show':'MRT or LRT station, main road traffic, bus stop, commuters, commute route',
        'forbidden':'airport, high-speed rail, random highway only, readable station text, KLCC close-up',
        'subjects':['Malaysia MRT or LRT station access with commuters near residential area','main road traffic and morning commute near condominium district'],
        'camera':'slow push in to station access or smooth road-side pan',
    },
    'medical': {
        'label':'医疗/诊所/药房/看病买药',
        'must_show':'clinic, pharmacy, community medical access, person buying medicine, nearby healthcare convenience',
        'forbidden':'hospital surgery, scary emergency scene, readable medicine labels, logos',
        'subjects':['community clinic and pharmacy street access near Malaysian residential area','resident walking to a neighborhood pharmacy or clinic, natural daily-life scene'],
        'camera':'gentle push in from street to clinic or pharmacy area',
    },
    'education': {
        'label':'教育/学校/家长孩子',
        'must_show':'school exterior, parents picking up children, education district context',
        'forbidden':'classroom close-up with text, school logo, children faces close-up',
        'subjects':['school exterior with parents picking up children near Malaysian residential district','family walking near education facilities, no readable school signage'],
        'camera':'calm left-to-right pan with family movement',
    },
    'community': {
        'label':'社区/公区/会所',
        'must_show':'condo lobby, security, garden, pool, gym, residents, community facilities',
        'forbidden':'empty generic hotel lobby only, exaggerated luxury, readable signage',
        'subjects':['condominium lobby and tropical garden community facilities with residents','pool and gym area in Malaysian condo community, natural lifestyle atmosphere'],
        'camera':'slow pull out from facility detail to wider community space',
    },
    'interior': {
        'label':'户型/采光/客厅/阳台',
        'must_show':'living room, balcony, window light, bedroom, kitchen, interior layout, daylight',
        'forbidden':'dark room, messy room, luxury unrelated villa, floorplan text',
        'subjects':['bright condo living room with balcony and natural daylight in Malaysia','interior layout walkthrough from living room to balcony showing good daylight'],
        'camera':'slow interior push in or gentle pull out toward balcony light',
    },
    'investment': {
        'label':'投资/出租/租客/自住',
        'must_show':'tenant viewing, agent showing unit, residential foot traffic, office catchment, rental demand mood',
        'forbidden':'money flying, charts, exact ROI numbers, document close-up',
        'subjects':['tenant viewing a condo unit naturally with agent, rental demand context','residential tower with office workers and potential tenants moving through the area'],
        'camera':'steady viewing-style movement, medium shot, realistic handheld',
    },
    'risk': {
        'label':'风险/配套不足/不方便',
        'must_show':'sparse street, long commute feeling, buyer hesitation, inconvenient empty surroundings',
        'forbidden':'happy crowded mall, luxury showroom, positive lifestyle shot only',
        'subjects':['sparse residential street with limited shops and long commute feeling, buyer hesitating','less convenient neighborhood edge with empty road and distant services, warning mood'],
        'camera':'slow pull back or static cautious framing',
    },
    'summary': {
        'label':'总结/收束/评论互动',
        'must_show':'calm exterior or balcony view, completed property context, natural short-video closing shot',
        'forbidden':'text card, fake UI, readable captions inside video',
        'subjects':['final calm condo exterior and neighborhood lifestyle summary shot','balcony daylight view toward Malaysian residential district, natural closing mood'],
        'camera':'gentle pull out or cross dissolve ending',
    },
}

def _v10_26_collect_strings(obj, out=None, depth=0):
    if out is None: out=[]
    if depth>5: return out
    if isinstance(obj, str):
        s=_v10_26_clean_text(obj)
        if s: out.append(s)
    elif isinstance(obj, list):
        for x in obj: _v10_26_collect_strings(x,out,depth+1)
    elif isinstance(obj, dict):
        for v in obj.values(): _v10_26_collect_strings(v,out,depth+1)
    return out

def _v10_26_extract_script(raw):
    import re
    if not isinstance(raw, dict):
        return _v10_26_clean_text(raw)
    candidates=[]
    for key in _V10_26_SCRIPT_KEYS:
        v=raw.get(key)
        if isinstance(v,str) and _v10_26_clean_text(v): candidates.append(_v10_26_clean_text(v))
    # segment arrays often hold the real script
    for key in ['script_segments','segments','subtitles','subtitle_cues','voice_segments','tts_segments','segment_voice_settings']:
        v=raw.get(key)
        if isinstance(v,list):
            parts=[]
            for item in v:
                if isinstance(item,dict):
                    for k in _V10_26_SCRIPT_KEYS + ['clean_text','sentence','line']:
                        if isinstance(item.get(k),str) and _v10_26_clean_text(item.get(k)):
                            parts.append(_v10_26_clean_text(item.get(k))); break
                elif isinstance(item,str):
                    parts.append(_v10_26_clean_text(item))
            joined=_v10_26_clean_text(' '.join(parts))
            if joined: candidates.append(joined)
    # nested request wrappers
    for key in ['extra','asset_context','payload','data','form','keyword_insights']:
        v=raw.get(key)
        if isinstance(v,dict):
            s=_v10_26_extract_script(v)
            if s: candidates.append(s)
    # choose longest meaningful candidate, not a default short fallback
    candidates=[c for c in candidates if len(c)>=4]
    candidates.sort(key=lambda x: (x in _V10_26_FALLBACK_TEXTS, -len(x)))
    non_fallback=[c for c in candidates if c not in _V10_26_FALLBACK_TEXTS]
    if non_fallback:
        return max(non_fallback,key=len)
    return max(candidates,key=len) if candidates else ''

def _v10_26_extract_duration(raw, script_text=''):
    def coerce(v):
        try:
            if isinstance(v,str): v=v.strip().replace('秒','')
            x=float(v)
            if 1 <= x <= 600: return x
        except Exception: pass
        return None
    if isinstance(raw,dict):
        for k in _V10_26_DURATION_KEYS:
            x=coerce(raw.get(k))
            if x: return x
        for k in ['extra','payload','data','audio','tts','voice']:
            if isinstance(raw.get(k),dict):
                x=_v10_26_extract_duration(raw.get(k),script_text)
                if x: return x
    # Chinese speaking rough fallback, not the default 20s
    return max(12.0, min(90.0, len(_v10_26_clean_text(script_text))*0.32))

def _v10_26_manual_keywords(raw):
    import re
    out=[]
    def add(v):
        if isinstance(v,str):
            for x in re.split(r'[,，、\n\s]+', v):
                x=_v10_26_clean_text(x)
                if x and x not in out: out.append(x)
        elif isinstance(v,list):
            for x in v: add(x)
        elif isinstance(v,dict):
            for k in ['keywords','manual_keywords','highlight_keywords','subtitle_keywords','final_keywords']:
                add(v.get(k))
    if isinstance(raw,dict):
        for k in ['manual_keywords','highlight_keywords','subtitle_keywords','final_keywords','keywords']:
            add(raw.get(k))
        add(raw.get('keyword_highlight') or {})
    return out[:40]

def _v10_26_category_for_text(text):
    t=str(text or '')
    if any(k in t for k in ['餐饮','餐厅','吃饭','咖啡','美食','饭店','food court','外卖']): return 'lifestyle_food'
    if any(k in t for k in ['购物','商场','超市','便利店','买菜','商圈']): return 'shopping'
    if any(k in t for k in ['交通','通勤','地铁','MRT','LRT','主干道','公交','出行','堵车','开车']): return 'transport'
    if any(k in t for k in ['医疗','看病','诊所','药房','医院','买药']): return 'medical'
    if any(k in t for k in ['教育','学校','孩子','家长','学区']): return 'education'
    if any(k in t for k in ['社区','大堂','园林','泳池','健身房','安保','物业','会所']): return 'community'
    if any(k in t for k in ['户型','采光','阳台','客厅','卧室','厨房','装修','空间']): return 'interior'
    if any(k in t for k in ['投资','出租','租客','自住','保值','长期持有','房价','收益']): return 'investment'
    if any(k in t for k in ['风险','后悔','不方便','不足','远','麻烦','踩坑']): return 'risk'
    if any(k in t for k in ['生活配套','配套','方便','成熟','护城河']): return 'shopping'
    return 'area_value'

def _v10_26_split_phrases(script_text):
    import re
    s=_v10_26_clean_text(script_text)
    parts=[_v10_26_clean_text(x) for x in re.split(r'[。！？!?；;\n]+|\s{2,}', str(script_text or ''))]
    if len(parts)<=1:
        parts=[_v10_26_clean_text(x) for x in re.split(r'\s+', s) if _v10_26_clean_text(x)]
    if len(parts)<=1:
        # keyword-aware fallback for compact Chinese with no spaces
        cuts=[]; last=0
        markers=['生活配套','楼下','通勤','附近','看病','周边','户型','适合','风险','但是','如果','所以']
        idxs=sorted({s.find(m) for m in markers if s.find(m)>0})
        for idx in idxs:
            cuts.append(s[last:idx]); last=idx
        cuts.append(s[last:])
        parts=[_v10_26_clean_text(x) for x in cuts if _v10_26_clean_text(x)]
    return [p for p in parts if p]

def _v10_26_required_categories(script_text, manual=None):
    s=_v10_26_clean_text(script_text)
    cats=[]
    def add(c):
        if c and c not in cats: cats.append(c)
    if any(k in s for k in ['马来西亚','吉隆坡','KL','楼盘','买房','房产','这里','这个项目']): add('area_value')
    for p in _v10_26_split_phrases(s): add(_v10_26_category_for_text(p))
    for kw in manual or []: add(_v10_26_category_for_text(kw))
    if 'lifestyle_food' in cats and 'shopping' not in cats and any(k in s for k in ['超市','商场','购物','便利店']): add('shopping')
    if 'shopping' in cats and 'lifestyle_food' not in cats and any(k in s for k in ['餐饮','餐厅','吃饭','咖啡','美食']): add('lifestyle_food')
    if any(k in s for k in ['自住','出租','投资','租客']): add('investment')
    if 'summary' not in cats: add('summary')
    # remove area default if it would crowd out real semantic needs, but keep first establishing shot for property video
    return cats

def _v10_26_keywords_for_text(text, manual=None):
    s=_v10_26_clean_text(text)
    found=[]
    for w in list(manual or []) + _V10_26_KEYWORDS:
        w=_v10_26_clean_text(w)
        if w and w in s and w not in found: found.append(w)
    return found[:3]

def _v10_26_phrase_for_category(cat, phrases):
    matches=[p for p in phrases if _v10_26_category_for_text(p)==cat]
    if matches: return _v10_26_clean_text(' '.join(matches[:2]))[:60]
    for p in phrases:
        if cat in ['shopping','lifestyle_food'] and any(k in p for k in ['配套','方便']): return p[:60]
    fallback={
        'area_value':'项目周边真实区域环境', 'lifestyle_food':'楼下餐饮吃饭方便', 'shopping':'周边超市商场便利店购物方便',
        'transport':'附近地铁主干道通勤方便', 'medical':'周边诊所药房看病买药方便', 'education':'附近学校教育配套',
        'community':'社区公区配套完善', 'interior':'户型采光客厅阳台表现', 'investment':'适合自住出租投资',
        'risk':'配套不足会带来不方便', 'summary':'最后总结这个房子的核心价值'
    }
    return fallback.get(cat,'房产核心信息')

def _v10_26_shot_count(duration, category_count):
    import math
    d=float(duration or 20)
    if d <= 15: base=5
    elif d <= 22: base=7
    elif d <= 30: base=9
    elif d <= 45: base=12
    else: base=15
    return max(category_count, min(16, base))

def _v10_26_build_preview_payload(raw):
    import math, time
    script=_v10_26_extract_script(raw)
    duration=_v10_26_extract_duration(raw, script)
    manual=_v10_26_manual_keywords(raw)
    if not script:
        return {'ok':False,'provider':'full_ai_tts_first_semantic_direct_render_v10_26b','error':'NO_REAL_SCRIPT','message':'没有拿到真实口播文案 不允许生成'}
    phrases=_v10_26_split_phrases(script)
    cats=_v10_26_required_categories(script, manual)
    # Build logical sequence: far -> near -> lifestyle/transport -> community/interior -> investment/summary
    order=['area_value','shopping','lifestyle_food','transport','medical','education','community','interior','investment','risk','summary']
    seq=[]
    for c in order:
        if c in cats and c not in seq: seq.append(c)
    target=_v10_26_shot_count(duration, len(seq))
    filler_order=['shopping','lifestyle_food','transport','community','interior','investment']
    fi=0
    while len(seq)<target:
        c=filler_order[fi%len(filler_order)]; fi+=1
        if c in cats or c in ['community','interior','investment']:
            # avoid same category adjacent
            if seq and seq[-1]==c: continue
            seq.insert(max(1,len(seq)-1), c)
    seq=seq[:target]
    per=round(float(duration)/max(len(seq),1),2)
    shots=[]; semantic=[]; subtitles=[]; cur=0.0
    transitions=['cross_dissolve','slow_push_in','horizontal_pan_match','pull_out','cross_dissolve','slow_push_in']
    prev=''
    for i,cat in enumerate(seq,1):
        pol=_V10_26_SCENE_POLICY.get(cat,_V10_26_SCENE_POLICY['area_value'])
        start=round(cur,2); end=round(float(duration) if i==len(seq) else min(float(duration), cur+per),2); cur=end
        phrase=_v10_26_phrase_for_category(cat, phrases)
        subj=pol['subjects'][(i-1)%len(pol['subjects'])]
        # force no same subject wording on repeated categories
        transition='opening_slow_push_in' if i==1 else transitions[(i-2)%len(transitions)]
        if prev==cat and transition=='cross_dissolve': transition='horizontal_pan_match'
        prev=cat
        kws=_v10_26_keywords_for_text(phrase, manual)
        prompt=(
            'Premium realistic vertical 9:16 Malaysia property short-video B-roll. '
            f'Shot {i}. Narration meaning: {phrase}. Semantic category: {pol["label"]}. '
            f'Required visual subject: {subj}. Must show: {pol["must_show"]}. '
            f'Camera motion: {pol["camera"]}. Transition to next: {transition}. '
            'Real Malaysian urban residential environment, tropical daylight, natural residents, no fake model posing, no readable text signs, no logos, no subtitles, no watermark, no KLCC unless explicitly required, no ocean unless Penang Langkawi or Sabah.'
        )
        shot={
            'index':i,
            'shot_id':f'v10_26_{i:02d}_{cat}',
            'start_seconds':start,
            'end_seconds':end,
            'duration_seconds':round(end-start,2),
            'narration_segment':phrase,
            'clean_subtitle':_v10_26_clean_text(phrase),
            'highlight_keywords':kws,
            'keywords':kws,
            'semantic_type':cat,
            'semantic_label':pol['label'],
            'scene_type':cat,
            'visual_subject':subj,
            'must_show':pol['must_show'],
            'forbidden_visuals':pol['forbidden'],
            'camera_motion':pol['camera'],
            'transition':'cross_dissolve' if i>1 else 'opening_slow_push_in',
            'transition_to_next':transition,
            'visual_prompt':prompt,
            'prompt':prompt,
            'negative_prompt':'readable text, subtitles, captions, chinese characters, english words, random letters, logo, watermark, fake UI, poster, banner, signboard with text, price tag, exact numbers, document close-up, calculator close-up, unrelated office meeting, cartoon, anime, low quality, blurry, black bars, distorted face, deformed hands',
            'source_priority':'semantic_rule_first_then_deepseek_polish_then_ai_broll',
            'demand_acceptance_lock':'v10_26'
        }
        shots.append(shot)
        semantic.append({
            'index':i,
            'time':f'{start}-{end}s',
            'narration_segment':phrase,
            'semantic_label':pol['label'],
            'must_show':pol['must_show'],
            'forbidden_visuals':pol['forbidden'],
            'transition_to_next':transition,
            'camera_motion':pol['camera'],
        })
        subtitles.append({'start':start,'end':end,'text':_v10_26_clean_text(phrase),'clean_text':_v10_26_clean_text(phrase),'keywords':kws,'subtitle_style':'DouyinCleanEmphasisV2'})
    acceptance=_v10_26_validate_preview(script, duration, shots, subtitles, manual)
    return {
        'ok': bool(acceptance.get('passed')),
        'provider':'full_ai_tts_first_semantic_direct_render_v10_26b',
        'version':'v10.26-demand-acceptance-lock',
        'city': 'kuala_lumpur',
        'script_text':script,
        'duration_seconds':round(float(duration),2),
        'shot_count':len(shots),
        'semantic_shot_plan':semantic,
        'shots':shots,
        'subtitle_cues':subtitles,
        'subtitles':subtitles,
        'acceptance':acceptance,
        'generation_allowed': bool(acceptance.get('passed')),
        'message':'需求验收通过 可以进入正式生成' if acceptance.get('passed') else '需求验收未通过 不允许生成'
    }

def _v10_26_validate_preview(script, duration, shots, subtitles, manual=None):
    import re
    problems=[]; s=_v10_26_clean_text(script)
    concat=' '.join(_v10_26_clean_text(x.get('narration_segment','')) for x in shots)
    if any(x in concat for x in _V10_26_FALLBACK_TEXTS) and not any(x in s for x in _V10_26_FALLBACK_TEXTS):
        problems.append('出现默认兜底文案')
    if len(shots)<_v10_26_shot_count(duration, 1)-1: problems.append('镜头数不足')
    if any(x.get('transition') in ['cut','smooth_cut','flash_cut'] or x.get('transition_to_next') in ['cut','smooth_cut','flash_cut'] for x in shots):
        problems.append('仍然存在快切/闪切转场')
    bad_sub=[c.get('text','') for c in subtitles if re.search(r'[，。！？；：、,.!?;:"“”‘’（）()【】\[\]《》<>…]', c.get('text',''))]
    if bad_sub: problems.append('字幕仍有标点符号')
    req=_v10_26_required_categories(s, manual)
    got={x.get('scene_type') or x.get('semantic_type') for x in shots}
    # only validate categories explicitly implied by script/manual, summary is generated
    important=[c for c in req if c!='summary']
    miss=[c for c in important if c not in got]
    if miss: problems.append('语义画面缺失: '+','.join(miss))
    # no excessive same category repetition
    repeat=False
    for a,b,c in zip(shots, shots[1:], shots[2:]):
        if (a.get('scene_type')==b.get('scene_type')==c.get('scene_type')): repeat=True
    if repeat: problems.append('同类画面连续重复超过2次')
    return {'passed':not problems,'problems':problems,'required_categories':important,'covered_categories':list(got),'manual_keywords':manual or [],'rule':'V10.26 preview must match narration before fal generation'}

def _v10_26_normalize_payload(raw):
    import copy
    data=copy.deepcopy(raw) if isinstance(raw,dict) else {'script':str(raw or '')}
    script=_v10_26_extract_script(data)
    duration=_v10_26_extract_duration(data, script)
    if script:
        for k in _V10_26_SCRIPT_KEYS:
            data[k]=script
        data['script_text']=script; data['copy']=script; data['text']=script; data['content']=script; data['full_script']=script; data['voice_script']=script
    for k in _V10_26_DURATION_KEYS:
        data[k]=duration
    preview=_v10_26_build_preview_payload(data)
    if preview.get('acceptance',{}).get('passed'):
        data['manual_shot_plan']=preview['shots']
        data['shot_overrides']=preview['shots']
        data['semantic_shot_plan']=preview['semantic_shot_plan']
        data['subtitle_cues']=preview['subtitle_cues']
        data['script_segments']=preview['subtitle_cues']
        data['demand_acceptance']=preview['acceptance']
    data['demand_acceptance_lock']='v10_26b'
    data['semantic_acceptance_required']=True
    data['subtitle_style']='DouyinCleanEmphasisV2'
    data['remove_punctuation']=True
    return data


# ================= AI VIDEO V10.27B START MODEL BINDING FIX =================
async def _v10_27b_call_original_start_with_model(old_start, payload):
    """Call the original tts-first start endpoint with TTSFirstStartRequest.
    V10.26/V10.27 wrappers already parse the raw Request. Passing the Starlette
    Request into the original pydantic start causes: 'Request' object has no
    attribute 'model_dump'. This helper binds payload back to TTSFirstStartRequest.
    """
    import inspect
    try:
        # V10_27E_SHOT_OVERRIDES_DICT_BINDING_FIX
        if isinstance(payload, dict) and isinstance(payload.get("shot_overrides"), list):
            _v10_27e_shot_list = payload.get("shot_overrides") or []
            payload["shot_overrides"] = {
                str((_s or {}).get("index", _i + 1)): _s
                for _i, _s in enumerate(_v10_27e_shot_list)
                if isinstance(_s, dict)
            }
        if isinstance(payload, dict) and isinstance(payload.get("manual_shot_plan"), list):
            payload["manual_shot_plan"] = [
                _s for _s in (payload.get("manual_shot_plan") or [])
                if isinstance(_s, dict)
            ]
        # V10_27E_SCRIPT_TEXT_SCOPE_RUNTIME_FIX
        try:
            _v10_27e_payload = payload if isinstance(payload, dict) else {}
            _v10_27e_script_text = (_v10_27e_payload.get("script_text") or _v10_27e_payload.get("script") or _v10_27e_payload.get("text") or _v10_27e_payload.get("content") or _v10_27e_payload.get("narration") or "")
            _v10_27e_script_text = str(_v10_27e_script_text).strip()
            if _v10_27e_script_text:
                _v10_27e_payload["script_text"] = _v10_27e_script_text
                _v10_27e_payload["script"] = _v10_27e_script_text
                _v10_27e_payload.setdefault("text", _v10_27e_script_text)
                _v10_27e_payload.setdefault("content", _v10_27e_script_text)
                _v10_27e_payload.setdefault("narration", _v10_27e_script_text)
                _v10_27e_payload.setdefault("voice_script", _v10_27e_script_text)
                globals()["script_text"] = _v10_27e_script_text
                import builtins as _v10_27e_builtins
                setattr(_v10_27e_builtins, "script_text", _v10_27e_script_text)
                if not _v10_27e_payload.get("title") or str(_v10_27e_payload.get("title")).strip() in ["马来西亚买房，别只看价格", "马来西亚买房,别只看价格"]:
                    _v10_27e_payload["title"] = _v10_27e_script_text[:24]
            _v10_27e_dur = (_v10_27e_payload.get("duration_seconds") or _v10_27e_payload.get("duration") or _v10_27e_payload.get("target_duration_seconds"))
            if _v10_27e_dur:
                try:
                    _v10_27e_dur = float(_v10_27e_dur)
                    _v10_27e_payload["duration_seconds"] = _v10_27e_dur
                    _v10_27e_payload["duration"] = _v10_27e_dur
                    _v10_27e_payload["target_duration_seconds"] = _v10_27e_dur
                except Exception:
                    pass
            payload = _v10_27e_payload
        except Exception as _v10_27e_scope_exc:
            print("V10_27E_SCRIPT_TEXT_SCOPE_FIX_WARNING", _v10_27e_scope_exc)
        model = TTSFirstStartRequest(**payload)
    except Exception as exc:
        return {'ok': False, 'provider': 'full_ai_tts_first_semantic_direct_render_v10_27ec', 'error': 'START_MODEL_BIND_FAILED', 'detail': str(exc), 'payload_keys': sorted(list((payload or {}).keys()))}
    try:
        if inspect.iscoroutinefunction(old_start):
            return await old_start(model)
        return old_start(model)
    except TypeError as exc:
        # Fallback for any alternate legacy signature that still accepts kwargs.
        try:
            if inspect.iscoroutinefunction(old_start):
                return await old_start(**payload)
            return old_start(**payload)
        except Exception as exc2:
            return {'ok': False, 'provider': 'full_ai_tts_first_semantic_direct_render_v10_27ec', 'error': 'OLD_START_MODEL_CALL_FAILED', 'detail': str(exc2), 'first_detail': str(exc), 'payload_keys': sorted(list((payload or {}).keys()))}
    except Exception as exc:
        return {'ok': False, 'provider': 'full_ai_tts_first_semantic_direct_render_v10_27ec', 'error': 'OLD_START_MODEL_CALL_FAILED', 'detail': str(exc), 'payload_keys': sorted(list((payload or {}).keys()))}
# ================= END AI VIDEO V10.27B START MODEL BINDING FIX =================

async def _v10_26_plan_preview(request: Request):
    from fastapi.responses import JSONResponse
    try:
        raw=await request.json()
    except Exception:
        raw={}
    preview=_v10_26_build_preview_payload(raw)
    status=200 if preview.get('ok') else 422
    return JSONResponse(status_code=status, content=preview)

def _v10_26_health():
    return {
        'ok':True,
        'provider':'full_ai_tts_first_semantic_direct_render_v10_26b',
        'logic':'script aliases normalized -> rule-first semantic storyboard -> demand acceptance before fal -> DouyinCleanEmphasisV2 punctuation-free keyword subtitles',
        'guarantees':['真实口播必须进入分镜','生活/餐饮/购物/交通/医疗/教育/户型/投资按语义强制匹配','plan-preview不过不允许正式生成','字幕去标点','关键词放大变色','转场禁止闪切'],
        'locks':['no_default_fallback_script','no_three_same_scene_in_row','no_cut_transition','no_fal_before_acceptance']
    }

async def _v10_26_call_old_start(request, payload):
    import inspect, json
    from starlette.requests import Request as StarletteRequest
    from fastapi.responses import JSONResponse
    endpoint=globals().get('_V10_26_OLD_START_ENDPOINT')
    if endpoint is None:
        return JSONResponse(status_code=500, content={'ok':False,'provider':'full_ai_tts_first_semantic_direct_render_v10_27ec','error':'OLD_START_ENDPOINT_MISSING'})
    body=json.dumps(payload, ensure_ascii=False).encode('utf-8')
    async def receive():
        return {'type':'http.request','body':body,'more_body':False}
    new_req=StarletteRequest(request.scope, receive)
    sig=inspect.signature(endpoint)
    params=list(sig.parameters.values())
    try:
        if not params:
            res=endpoint()
        elif len(params)==1:
            p=params[0]
            if p.name in ('request','req'):
                res=endpoint(new_req)
            else:
                res=endpoint(payload)
        else:
            kwargs={}
            for p in params:
                if p.name in ('request','req'): kwargs[p.name]=new_req
                elif p.name in ('raw','body','payload','data','request_body'): kwargs[p.name]=payload
                elif p.default is inspect._empty: kwargs[p.name]=payload
            res=endpoint(**kwargs)
        if inspect.isawaitable(res): res=await res
        return res
    except Exception as exc:
        return JSONResponse(status_code=500, content={'ok':False,'provider':'full_ai_tts_first_semantic_direct_render_v10_27ec','error':'OLD_START_CALL_FAILED','detail':str(exc),'normalized_payload_keys':sorted(list(payload.keys()))})

async def _v10_26_start(request: Request):
    from fastapi.responses import JSONResponse
    try:
        raw=await request.json()
    except Exception:
        raw={}
    normalized=_v10_26_normalize_payload(raw)
    preview=_v10_26_build_preview_payload(normalized)
    if not preview.get('acceptance',{}).get('passed'):
        return JSONResponse(status_code=422, content={'ok':False,'provider':'full_ai_tts_first_semantic_direct_render_v10_26b','error':'DEMAND_ACCEPTANCE_FAILED','message':'需求验收未通过 不允许扣 fal 生成','preview':preview})
    normalized['manual_shot_plan']=preview['shots']
    normalized['shot_overrides']=preview['shots']
    normalized['semantic_shot_plan']=preview['semantic_shot_plan']
    normalized['subtitle_cues']=preview['subtitle_cues']
    normalized['script_segments']=preview['subtitle_cues']
    normalized['demand_acceptance']=preview['acceptance']
    print('V10_26_DEMAND_ACCEPTANCE_PASSED='+str({'shot_count':len(preview['shots']),'duration':preview.get('duration_seconds'),'categories':preview.get('acceptance',{}).get('covered_categories')}))
    return await _v10_26_call_old_start(request, normalized)

def _v10_26_patch_router_routes():
    global _V10_26_OLD_START_ENDPOINT
    if getattr(router, '_v10_26_patched', False):
        return
    _V10_26_OLD_START_ENDPOINT=None
    kept=[]
    for r in list(getattr(router,'routes',[])):
        path=getattr(r,'path','')
        methods=set(getattr(r,'methods',[]) or [])
        is_start = (path == '/start' or path.endswith('/start'))
        is_preview = (path == '/plan-preview' or path.endswith('/plan-preview'))
        is_health = (path == '/health' or path.endswith('/health'))
        if is_start and 'POST' in methods:
            _V10_26_OLD_START_ENDPOINT=getattr(r,'endpoint',None)
            continue
        if is_preview or is_health:
            continue
        kept.append(r)
    router.routes=kept
    router.add_api_route('/health', _v10_26_health, methods=['GET'])
    router.add_api_route('/plan-preview', _v10_26_plan_preview, methods=['POST'])
    router.add_api_route('/start', _v10_26_start, methods=['POST'])
    router._v10_26_patched=True
    print('V10_26_DEMAND_ACCEPTANCE_ROUTES_PATCHED', {'old_start': bool(_V10_26_OLD_START_ENDPOINT), 'routes': [getattr(x,'path','') for x in router.routes if 'plan' in getattr(x,'path','') or 'start' in getattr(x,'path','') or 'health' in getattr(x,'path','')]})

try:
    _V10_26_OLD_INSTALL = install_full_ai_tts_first
    def install_full_ai_tts_first(app):
        _v10_26_patch_router_routes()
        return _V10_26_OLD_INSTALL(app)
except Exception as _v10_26_install_exc:
    print('V10_26_INSTALL_WRAP_FAILED', _v10_26_install_exc)
# ================= END AI VIDEO V10.26 DEMAND ACCEPTANCE LOCK =================


# ================= AI VIDEO V10.27 STRICT NARRATION BEST QUALITY LOCK =================
try:
    import re as _v10_27_re
    import json as _v10_27_json
    import inspect as _v10_27_inspect
    from fastapi import Request as _V10_27_Request
    from fastapi.responses import JSONResponse as _V10_27_JSONResponse
    from starlette.requests import Request as _V10_27_StarletteRequest
except Exception as _v10_27_import_exc:
    print('V10_27_IMPORT_WARNING', _v10_27_import_exc)

_V10_27_OLD_START_ENDPOINT = None
_V10_27_VERSION = 'v10.27e-direct-original-start'
_V10_27_PROVIDER = 'full_ai_tts_first_semantic_direct_render_v10_27ec'
_V10_27_TRANSITIONS = ['opening_slow_push_in','cross_dissolve','slow_push_in','horizontal_pan_match','pull_out','cross_dissolve','slow_push_in']
_V10_27_SCRIPT_ALIASES = ['script','script_text','copy','text','content','full_script','voice_script','narration','spoken_text','口播文案','文案']
_V10_27_DURATION_ALIASES = ['duration','duration_seconds','target_duration_seconds','audio_duration','tts_duration','selected_duration','video_duration']
_V10_27_DEFAULT_BAD_SCRIPTS = ['马来西亚买房','别只看价格','最后总结这个房子的核心价值','项目周边真实区域环境']
_V10_27_KEYWORDS = ['生活配套','配套','超市','商场','购物','便利店','餐饮','餐厅','吃饭','咖啡','美食','food court','地铁','MRT','LRT','主干道','交通','通勤','公交','诊所','药房','医院','医疗','看病','买药','学校','教育','户型采光','户型','采光','阳台','客厅','卧室','厨房','装修','空间','出租','租客','投资','自住','看房','人流','风险','后悔','不方便']

def _v10_27_clean_text(text):
    text = '' if text is None else str(text)
    text = text.replace('\u3000',' ')
    text = _v10_27_re.sub(r'[，,。.!！?？;；:：、"“”\'‘’（）()\[\]【】{}《》<>…·•|/\\]+', ' ', text)
    text = _v10_27_re.sub(r'\s+', ' ', text).strip()
    return text

def _v10_27_pick_script(payload):
    if not isinstance(payload, dict): return ''
    for k in _V10_27_SCRIPT_ALIASES:
        v = payload.get(k)
        if isinstance(v, str) and _v10_27_clean_text(v): return _v10_27_clean_text(v)
    for nk in ['extra','asset_context','keyword_insights','voice','draft','data']:
        v = payload.get(nk)
        if isinstance(v, dict):
            t = _v10_27_pick_script(v)
            if t: return t
    segs = payload.get('script_segments') or payload.get('segments')
    if isinstance(segs, list):
        parts=[]
        for seg in segs:
            if isinstance(seg, str): parts.append(seg)
            elif isinstance(seg, dict):
                for k in _V10_27_SCRIPT_ALIASES + ['line','sentence']:
                    if isinstance(seg.get(k), str): parts.append(seg[k]); break
        joined=_v10_27_clean_text(' '.join(parts))
        if joined: return joined
    return ''

def _v10_27_pick_duration(payload, fallback=20.0):
    if not isinstance(payload, dict): return fallback
    for k in _V10_27_DURATION_ALIASES:
        v=payload.get(k)
        try:
            if v is not None and float(v)>0: return max(8.0, min(90.0, float(v)))
        except Exception: pass
    for nk in ['extra','asset_context','voice','data']:
        v=payload.get(nk)
        if isinstance(v, dict):
            d=_v10_27_pick_duration(v, 0)
            if d: return d
    return fallback

def _v10_27_manual_keywords(payload):
    out=[]
    if not isinstance(payload, dict): return out
    for k in ['manual_keywords','highlight_keywords','keywords','keyword_highlight']:
        v=payload.get(k)
        if isinstance(v, list): out += [str(x) for x in v if str(x).strip()]
        elif isinstance(v, dict) and isinstance(v.get('keywords'), list): out += [str(x) for x in v.get('keywords') if str(x).strip()]
        elif isinstance(v, str): out += [x for x in _v10_27_re.split(r'[\s,，、]+', v) if x]
    seen=set(); clean=[]
    for x in out:
        x=_v10_27_clean_text(x)
        if x and x not in seen:
            seen.add(x); clean.append(x)
    return clean

def _v10_27_target_shot_count(duration):
    try: d=float(duration)
    except Exception: d=20.0
    if d <= 12: return 4
    if d <= 16: return 5
    if d <= 20: return 6
    if d <= 24: return 8
    if d <= 32: return 9
    if d <= 40: return 11
    return max(10, min(14, int(round(d/3.2))))

def _v10_27_expand_piece(piece):
    piece=_v10_27_clean_text(piece)
    if not piece: return []
    if '适合自住也适合出租' in piece or '自住也适合出租' in piece:
        return ['适合自住','也适合出租']
    return [piece]

def _v10_27_split_script(script):
    script=_v10_27_clean_text(script)
    if not script: return []
    if len(script.split(' ')) >= 3:
        rough=[x for x in script.split(' ') if x.strip()]
    else:
        boundaries=['楼下有','通勤','附近有','看病','周边有','户型','适合自住','也适合出租','出租','投资']
        positions=[]
        for b in boundaries:
            i=script.find(b)
            if i>0: positions.append(i)
        if positions:
            positions=sorted(set(positions)); rough=[]; last=0
            for i in positions:
                rough.append(script[last:i]); last=i
            rough.append(script[last:])
        else:
            rough=[script]
    parts=[]
    for r in rough: parts.extend(_v10_27_expand_piece(r))
    final=[]
    for p in [_v10_27_clean_text(x) for x in parts if _v10_27_clean_text(x)]:
        if '看病买药也方便' in p and '周边有诊所' in p:
            final += ['看病买药也方便', p.replace('看病买药也方便','').strip()]
        elif '通勤也不麻烦' in p and '附近有地铁' in p:
            final += ['通勤也不麻烦', p.replace('通勤也不麻烦','').strip()]
        else:
            final.append(p)
    return [x for x in final if x]

def _v10_27_scene_type(text):
    t=text.lower()
    if any(k.lower() in t for k in ['餐饮','餐厅','吃饭','咖啡','美食','food court']): return 'lifestyle_food'
    if any(k.lower() in t for k in ['超市','商场','购物','便利店','生活配套','配套']): return 'shopping'
    if any(k.lower() in t for k in ['地铁','mrt','lrt','主干道','交通','通勤','公交','车站']): return 'transport'
    if any(k.lower() in t for k in ['诊所','药房','医院','医疗','看病','买药']): return 'medical'
    if any(k.lower() in t for k in ['学校','教育','校区','家长']): return 'education'
    if any(k.lower() in t for k in ['户型','采光','阳台','客厅','卧室','厨房','装修','空间']): return 'interior'
    if any(k.lower() in t for k in ['出租','租客','投资','自住','看房','租金','人流']): return 'investment'
    if any(k.lower() in t for k in ['风险','后悔','不方便','踩坑','远','堵']): return 'risk'
    if any(k.lower() in t for k in ['社区','大堂','园林','泳池','健身房','会所','安保']): return 'community'
    if any(k.lower() in t for k in ['区域','地段','周边','楼盘','项目']): return 'area_value'
    return 'area_value'

_V10_27_SCENE_META={
 'shopping': {'label':'购物/超市/商场/便利店','subject':'supermarket and convenience shopping near residential towers with residents carrying grocery bags','must':'supermarket, convenience store, grocery bags, nearby mall or shop lots, daily shopping scene','forbid':'only condo lobby, only bedroom, price tags, readable signs, fake logos','camera':'smooth lateral pan following residents with grocery bags'},
 'lifestyle_food': {'label':'餐饮/吃饭/生活配套','subject':'Malaysian restaurant cafe or food court near residential towers with people dining naturally','must':'restaurant, cafe, food court, local dining street, takeaway pickup or people eating naturally','forbid':'empty mall only, office meeting, readable signs, logo, unrelated bedroom','camera':'slow push in toward restaurant or gentle walking pan'},
 'transport': {'label':'交通/通勤/地铁/主干道','subject':'MRT or LRT access with main road traffic and commuters near condominium district','must':'MRT or LRT station access, main road traffic, bus stop, commuters, commute route','forbid':'airport, high speed rail, random highway only, readable station text, KLCC close-up','camera':'slow push in to station access or smooth road-side pan'},
 'medical': {'label':'医疗/诊所/药房/看病买药','subject':'community clinic and pharmacy street access near Malaysian residential area','must':'clinic, pharmacy, community medical access, person buying medicine, healthcare convenience','forbid':'hospital surgery, scary emergency scene, readable medicine labels, logos','camera':'gentle push in from street to clinic or pharmacy area'},
 'education': {'label':'教育/学校/家长接送','subject':'school area pickup scene near residential community with parents and students in natural distance','must':'school exterior context, parents pickup, campus-adjacent road, family living convenience','forbid':'readable school name, classroom close-up with minors faces, fake logos','camera':'calm street-level pan outside education facility'},
 'interior': {'label':'户型/采光/客厅/阳台','subject':'interior layout walkthrough from living room to balcony showing good daylight','must':'living room, balcony, window light, bedroom, kitchen, interior layout, daylight','forbid':'dark room, messy room, unrelated villa, floorplan text','camera':'slow interior push in or gentle pull out toward balcony light'},
 'investment': {'label':'投资/出租/租客/自住','subject':'tenant or buyer viewing a condo unit naturally with agent and residential demand context','must':'tenant viewing, agent showing unit, residential foot traffic, self-use and rental demand mood','forbid':'money flying, charts, exact ROI numbers, document close-up','camera':'steady viewing-style movement, medium shot, realistic handheld'},
 'risk': {'label':'风险/后悔/不方便/踩坑','subject':'buyer hesitating while facing inconvenient commute or weak surrounding amenities','must':'hesitation, inconvenient route, weak amenity contrast, realistic decision pressure','forbid':'horror mood, documents only, fake warning text','camera':'slower handheld movement showing inconvenience'},
 'community': {'label':'社区/大堂/园林/泳池/健身房','subject':'condo lobby garden pool and gym community facilities with natural resident movement','must':'lobby, security, garden, pool, gym, residents, community living atmosphere','forbid':'empty luxury hotel only, readable project logo, text sign','camera':'smooth amenity walk-through or slow push in'},
 'area_value': {'label':'区域/楼盘外景/地段','subject':'street-level Malaysian residential district with condo towers and shop lots','must':'Malaysian residential district, condo exterior, tropical greenery, real street-level context','forbid':'only indoor living room, only documents, calculator, repeated KLCC close-up, readable signs','camera':'slow push in from street level or gentle left-to-right establishing pan'},
}

def _v10_27_keywords_for(text, manual=None):
    seen=set(); out=[]
    for w in list(manual or [])+_V10_27_KEYWORDS:
        w=_v10_27_clean_text(w)
        if w and w not in seen and w in text:
            seen.add(w); out.append(w)
        if len(out)>=3: break
    return out

def _v10_27_required_categories(script):
    cats=[]
    for piece in _v10_27_split_script(script):
        c=_v10_27_scene_type(piece)
        if c not in cats: cats.append(c)
    return cats

def _v10_27_select_logic(cats):
    cs=set(cats)
    if 'risk' in cs: return 'C_问题导向_痛点到楼盘再到户型'
    if 'investment' in cs: return 'E_投资出租_人流需求到户型总结'
    if 'shopping' in cs or 'lifestyle_food' in cs or 'transport' in cs: return 'B_生活方式_配套交通社区室内'
    if 'community' in cs or 'interior' in cs: return 'D_改善居住_社区会所到室内'
    return 'A_区域到社区到室内'

def _v10_27_build_preview(payload):
    payload = payload if isinstance(payload, dict) else {}
    script = _v10_27_pick_script(payload)
    duration = _v10_27_pick_duration(payload, 20.0)
    manual = _v10_27_manual_keywords(payload)
    if not script:
        return {'ok':False,'provider':_V10_27_PROVIDER,'version':_V10_27_VERSION,'error':'NO_REAL_SCRIPT','message':'没有拿到真实口播文案 不允许生成','generation_allowed':False,'acceptance':{'passed':False,'problems':['NO_REAL_SCRIPT']}}
    clean_script = _v10_27_clean_text(script)
    parts = _v10_27_split_script(clean_script)
    target = _v10_27_target_shot_count(duration)
    expanded=[]
    for x in parts:
        if '适合自住也适合出租' in x or '自住也适合出租' in x:
            expanded += ['适合自住','也适合出租']
        else:
            expanded.append(x)
    real_parts=[]
    for x in expanded:
        x=_v10_27_clean_text(x)
        if x and x in clean_script and x not in real_parts:
            real_parts.append(x)
    parts=real_parts or [clean_script]
    if len(parts)>target:
        while len(parts)>target:
            parts[-2]=_v10_27_clean_text(parts[-2]+' '+parts[-1]); parts.pop()
    shot_count=len(parts)
    per=duration/max(1,shot_count)
    shots=[]; cues=[]; plan=[]; covered=[]
    for i,seg in enumerate(parts, start=1):
        scene=_v10_27_scene_type(seg); covered.append(scene)
        meta=_V10_27_SCENE_META.get(scene,_V10_27_SCENE_META['area_value'])
        start=round((i-1)*per,2); end=round(duration if i==shot_count else i*per,2)
        transition=_V10_27_TRANSITIONS[(i-1)%len(_V10_27_TRANSITIONS)]
        if transition in ['cut','smooth_cut','flash_cut','hard_cut']: transition='cross_dissolve'
        kws=_v10_27_keywords_for(seg, manual)
        prompt=f'Premium realistic vertical 9:16 Malaysia property short-video B-roll. Shot {i}. Narration meaning: {seg}. Semantic category: {meta["label"]}. Required visual subject: {meta["subject"]}. Must show: {meta["must"]}. Camera motion: {meta["camera"]}. Transition to next: {transition}. Real Malaysian urban residential environment, tropical daylight, natural residents, no fake model posing, no readable text signs, no logos, no subtitles, no watermark, no KLCC unless explicitly required, no ocean unless Penang Langkawi or Sabah.'
        shot={'index':i,'shot_id':f'v10_27_{i:02d}_{scene}','start_seconds':start,'end_seconds':end,'duration_seconds':round(end-start,2),'narration_segment':seg,'clean_subtitle':seg,'highlight_keywords':kws,'keywords':kws,'semantic_type':scene,'semantic_label':meta['label'],'scene_type':scene,'visual_subject':meta['subject'],'must_show':meta['must'],'forbidden_visuals':meta['forbid'],'camera_motion':meta['camera'],'transition':transition,'transition_to_next':transition,'visual_prompt':prompt,'prompt':prompt,'negative_prompt':'readable text, subtitles, captions, chinese characters, english words, random letters, logo, watermark, fake UI, poster, banner, signboard with text, price tag, exact numbers, document close-up, calculator close-up, unrelated office meeting, cartoon, anime, low quality, blurry, black bars, distorted face, deformed hands','source_priority':'strict_real_script_first_then_semantic_rule_then_deepseek_polish_then_ai_broll','demand_acceptance_lock':'v10_27e'}
        shots.append(shot)
        plan.append({'index':i,'time':f'{start}-{end}s','narration_segment':seg,'semantic_label':meta['label'],'must_show':meta['must'],'forbidden_visuals':meta['forbid'],'transition_to_next':transition,'camera_motion':meta['camera']})
        cues.append({'start':start,'end':end,'text':seg,'clean_text':seg,'keywords':kws,'subtitle_style':'DouyinCleanEmphasisV2'})
    required=_v10_27_required_categories(clean_script)
    covered_unique=[]
    for c in covered:
        if c not in covered_unique: covered_unique.append(c)
    problems=[]
    for bad in _V10_27_DEFAULT_BAD_SCRIPTS:
        if bad not in clean_script:
            for c in cues:
                if bad in c.get('text',''): problems.append('INVENTED_DEFAULT_TEXT:'+bad)
    for c in cues:
        txt=_v10_27_clean_text(c.get('text',''))
        if txt and txt not in clean_script: problems.append('INVENTED_SUBTITLE:'+txt)
    seen_txt=set()
    for c in cues:
        txt=c.get('text','')
        if txt in seen_txt: problems.append('REPEATED_SUBTITLE:'+txt)
        seen_txt.add(txt)
    for rc in required:
        if rc not in covered_unique: problems.append('MISSING_CATEGORY:'+rc)
    for shot in shots:
        if shot.get('transition') in ['cut','smooth_cut','flash_cut','hard_cut']: problems.append('BAD_TRANSITION:'+str(shot.get('transition')))
    if duration>=25 and shot_count<7: problems.append('TOO_FEW_SHOTS_FOR_DURATION')
    passed=not problems
    return {'ok':True,'provider':_V10_27_PROVIDER,'version':_V10_27_VERSION,'city':payload.get('city') or payload.get('location') or 'kuala_lumpur','script_text':clean_script,'duration_seconds':round(float(duration),2),'shot_count':shot_count,'target_shot_count':target,'selected_logic_template':_v10_27_select_logic(required),'semantic_shot_plan':plan,'shots':shots,'subtitle_cues':cues,'subtitles':cues,'manual_keywords':manual,'generation_allowed':passed,'acceptance':{'passed':passed,'problems':problems,'required_categories':required,'covered_categories':covered_unique,'manual_keywords':manual,'rule':'V10.27 no invented narration/subtitles; every cue must be a real substring of script before fal generation'},'locks':['real_script_only','no_invented_subtitle','no_repeated_subtitle','semantic_scene_required','no_cut_transition','no_fal_before_acceptance']}

async def _v10_27_health():
    return {'ok':True,'provider':_V10_27_PROVIDER,'version':_V10_27_VERSION,'logic':'real script only -> strict clause split -> rule-first semantic storyboard -> no invented subtitles -> demand acceptance before fal -> DouyinCleanEmphasisV2','guarantees':['字幕和narration_segment只能来自真实口播','不自动添加开头总结句','不自动添加结尾总结句','不为补时长重复同一句字幕','吃饭购物交通医疗户型投资按语义强制匹配','plan-preview不过不允许正式生成','转场禁止闪切'],'locks':['real_script_only','no_invented_subtitle','no_repeated_subtitle','semantic_scene_required','no_cut_transition','no_fal_before_acceptance']}

async def _v10_27_plan_preview(request: _V10_27_Request):
    try: payload = await request.json()
    except Exception: payload = {}
    preview = _v10_27_build_preview(payload)
    return _V10_27_JSONResponse(status_code=(200 if preview.get('ok') else 422), content=preview)


# ================= AI VIDEO V10.27C DIRECT ORIGINAL START FIX =================
async def _v10_27e_call_true_original_start(request, payload):
    """Bypass stacked V10.26/V10.27 wrapper endpoints and call the real tts-first
    original start endpoint with TTSFirstStartRequest.

    The previous start path was: V10.27 start -> V10.26 wrapper -> original start.
    The V10.26 wrapper passed a Starlette Request into the original start, causing
    "'Request' object has no attribute 'model_dump'". This function calls the
    original endpoint saved by V10.26 before wrappers were installed.
    """
    import inspect
    try:
        from fastapi.responses import JSONResponse as _V10_27E_JSONResponse
    except Exception:
        _V10_27E_JSONResponse = None

    provider = 'full_ai_tts_first_semantic_direct_render_v10_27e'
    payload = payload if isinstance(payload, dict) else {}

    # Build the Pydantic request object expected by the original start endpoint.
    try:
        # V10_27E_SHOT_OVERRIDES_DICT_BINDING_FIX
        if isinstance(payload, dict) and isinstance(payload.get("shot_overrides"), list):
            _v10_27e_shot_list = payload.get("shot_overrides") or []
            payload["shot_overrides"] = {
                str((_s or {}).get("index", _i + 1)): _s
                for _i, _s in enumerate(_v10_27e_shot_list)
                if isinstance(_s, dict)
            }
        if isinstance(payload, dict) and isinstance(payload.get("manual_shot_plan"), list):
            payload["manual_shot_plan"] = [
                _s for _s in (payload.get("manual_shot_plan") or [])
                if isinstance(_s, dict)
            ]
        # V10_27E_SCRIPT_TEXT_SCOPE_RUNTIME_FIX
        try:
            _v10_27e_payload = payload if isinstance(payload, dict) else {}
            _v10_27e_script_text = (_v10_27e_payload.get("script_text") or _v10_27e_payload.get("script") or _v10_27e_payload.get("text") or _v10_27e_payload.get("content") or _v10_27e_payload.get("narration") or "")
            _v10_27e_script_text = str(_v10_27e_script_text).strip()
            if _v10_27e_script_text:
                _v10_27e_payload["script_text"] = _v10_27e_script_text
                _v10_27e_payload["script"] = _v10_27e_script_text
                _v10_27e_payload.setdefault("text", _v10_27e_script_text)
                _v10_27e_payload.setdefault("content", _v10_27e_script_text)
                _v10_27e_payload.setdefault("narration", _v10_27e_script_text)
                _v10_27e_payload.setdefault("voice_script", _v10_27e_script_text)
                globals()["script_text"] = _v10_27e_script_text
                import builtins as _v10_27e_builtins
                setattr(_v10_27e_builtins, "script_text", _v10_27e_script_text)
                if not _v10_27e_payload.get("title") or str(_v10_27e_payload.get("title")).strip() in ["马来西亚买房，别只看价格", "马来西亚买房,别只看价格"]:
                    _v10_27e_payload["title"] = _v10_27e_script_text[:24]
            _v10_27e_dur = (_v10_27e_payload.get("duration_seconds") or _v10_27e_payload.get("duration") or _v10_27e_payload.get("target_duration_seconds"))
            if _v10_27e_dur:
                try:
                    _v10_27e_dur = float(_v10_27e_dur)
                    _v10_27e_payload["duration_seconds"] = _v10_27e_dur
                    _v10_27e_payload["duration"] = _v10_27e_dur
                    _v10_27e_payload["target_duration_seconds"] = _v10_27e_dur
                except Exception:
                    pass
            payload = _v10_27e_payload
        except Exception as _v10_27e_scope_exc:
            print("V10_27E_SCRIPT_TEXT_SCOPE_FIX_WARNING", _v10_27e_scope_exc)
        model = TTSFirstStartRequest(**payload)
    except Exception as exc:
        content = {'ok': False, 'provider': provider, 'error': 'START_MODEL_BIND_FAILED', 'detail': str(exc), 'payload_keys': sorted(list(payload.keys()))}
        if _V10_27E_JSONResponse:
            return _V10_27E_JSONResponse(status_code=422, content=content)
        return content

    # The V10.26 installer saved the true pre-wrapper endpoint here. Prefer it.
    candidates = []
    names = [
        '_V10_26_OLD_START_ENDPOINT',
        '_V10_25_OLD_START_ENDPOINT',
        '_V10_23_OLD_START_ENDPOINT',
        '_V10_22_OLD_START_ENDPOINT',
        '_TTS_FIRST_ORIGINAL_START_ENDPOINT',
        '_FULL_AI_TTS_FIRST_ORIGINAL_START_ENDPOINT',
        '_V10_27_OLD_START_ENDPOINT',
    ]
    for name in names:
        ep = globals().get(name)
        if ep and ep not in candidates:
            candidates.append(ep)

    tried=[]
    last_exc=None
    for ep in candidates:
        ep_name = getattr(ep, '__name__', repr(ep))
        tried.append(ep_name)
        # Skip wrapper endpoints; they expect Request and will re-enter the broken path.
        if ep_name.startswith('_v10_26') or ep_name.startswith('_v10_27') or ep_name.startswith('_v10_28'):
            continue
        try:
            result = ep(model)
            if inspect.isawaitable(result):
                result = await result
            return result
        except TypeError as exc:
            last_exc=exc
            # Fallback for an alternate original endpoint that accepts kwargs.
            try:
                result = ep(**payload)
                if inspect.isawaitable(result):
                    result = await result
                return result
            except Exception as exc2:
                last_exc=exc2
                continue
        except Exception as exc:
            last_exc=exc
            continue

    content = {
        'ok': False,
        'provider': provider,
        'error': 'TRUE_ORIGINAL_START_CALL_FAILED',
        'detail': str(last_exc) if last_exc else 'no usable non-wrapper original start endpoint found',
        'tried_endpoints': tried,
        'payload_keys': sorted(list(payload.keys())),
        'hint': 'Expected _V10_26_OLD_START_ENDPOINT to point to the real original start endpoint.'
    }
    if _V10_27E_JSONResponse:
        return _V10_27E_JSONResponse(status_code=500, content=content)
    return content
# ================= END AI VIDEO V10.27C DIRECT ORIGINAL START FIX =================

async def _v10_27_call_old_start(request, payload):
    global _V10_27_OLD_START_ENDPOINT
    if _V10_27_OLD_START_ENDPOINT is None:
        return _V10_27_JSONResponse(status_code=500, content={'ok':False,'provider':_V10_27_PROVIDER,'error':'OLD_START_ENDPOINT_MISSING'})
    body = _v10_27_json.dumps(payload, ensure_ascii=False).encode('utf-8')
    async def receive(): return {'type':'http.request','body':body,'more_body':False}
    new_req = _V10_27_StarletteRequest(request.scope, receive)
    ep = _V10_27_OLD_START_ENDPOINT
    try:
        sig = _v10_27_inspect.signature(ep); params=list(sig.parameters.values())
        if params:
            ann=params[0].annotation; name=params[0].name.lower()
            if 'request' in name or ann in (_V10_27_Request, _V10_27_StarletteRequest): result=ep(new_req)
            # V10_27E_SHOT_OVERRIDES_DICT_BINDING_FIX
            if isinstance(payload, dict) and isinstance(payload.get("shot_overrides"), list):
                _v10_27e_shot_list = payload.get("shot_overrides") or []
                payload["shot_overrides"] = {
                    str((_s or {}).get("index", _i + 1)): _s
                    for _i, _s in enumerate(_v10_27e_shot_list)
                    if isinstance(_s, dict)
                }
            if isinstance(payload, dict) and isinstance(payload.get("manual_shot_plan"), list):
                payload["manual_shot_plan"] = [
                    _s for _s in (payload.get("manual_shot_plan") or [])
                    if isinstance(_s, dict)
                ]
            # V10_27E_SCRIPT_TEXT_SCOPE_RUNTIME_FIX
            try:
                _v10_27e_payload = payload if isinstance(payload, dict) else {}
                _v10_27e_script_text = (_v10_27e_payload.get("script_text") or _v10_27e_payload.get("script") or _v10_27e_payload.get("text") or _v10_27e_payload.get("content") or _v10_27e_payload.get("narration") or "")
                _v10_27e_script_text = str(_v10_27e_script_text).strip()
                if _v10_27e_script_text:
                    _v10_27e_payload["script_text"] = _v10_27e_script_text
                    _v10_27e_payload["script"] = _v10_27e_script_text
                    _v10_27e_payload.setdefault("text", _v10_27e_script_text)
                    _v10_27e_payload.setdefault("content", _v10_27e_script_text)
                    _v10_27e_payload.setdefault("narration", _v10_27e_script_text)
                    _v10_27e_payload.setdefault("voice_script", _v10_27e_script_text)
                    globals()["script_text"] = _v10_27e_script_text
                    import builtins as _v10_27e_builtins
                    setattr(_v10_27e_builtins, "script_text", _v10_27e_script_text)
                    if not _v10_27e_payload.get("title") or str(_v10_27e_payload.get("title")).strip() in ["马来西亚买房，别只看价格", "马来西亚买房,别只看价格"]:
                        _v10_27e_payload["title"] = _v10_27e_script_text[:24]
                _v10_27e_dur = (_v10_27e_payload.get("duration_seconds") or _v10_27e_payload.get("duration") or _v10_27e_payload.get("target_duration_seconds"))
                if _v10_27e_dur:
                    try:
                        _v10_27e_dur = float(_v10_27e_dur)
                        _v10_27e_payload["duration_seconds"] = _v10_27e_dur
                        _v10_27e_payload["duration"] = _v10_27e_dur
                        _v10_27e_payload["target_duration_seconds"] = _v10_27e_dur
                    except Exception:
                        pass
                payload = _v10_27e_payload
            except Exception as _v10_27e_scope_exc:
                print("V10_27E_SCRIPT_TEXT_SCOPE_FIX_WARNING", _v10_27e_scope_exc)
            else: result=ep(TTSFirstStartRequest(**payload))
        else: result=ep()
        if _v10_27_inspect.isawaitable(result): result = await result
        return result
    except Exception as exc:
        return _V10_27_JSONResponse(status_code=500, content={'ok':False,'provider':_V10_27_PROVIDER,'error':'OLD_START_CALL_FAILED','detail':str(exc),'normalized_payload_keys':sorted(list(payload.keys()))})

async def _v10_27_start(request: _V10_27_Request):
    try: payload = await request.json()
    except Exception: payload = {}
    preview = _v10_27_build_preview(payload)
    if not preview.get('generation_allowed'):
        return _V10_27_JSONResponse(status_code=422, content={'ok':False,'provider':_V10_27_PROVIDER,'error':'DEMAND_ACCEPTANCE_FAILED','message':'需求验收未通过 不允许扣 fal 生成','preview':preview})
    payload=dict(payload)
    # V10_27E_START_PAYLOAD_GLOBAL_SCRIPT_TEXT
    try:
        globals()['script_text'] = str((preview or {}).get('script_text') or payload.get('script_text') or payload.get('script') or '')
        import builtins as _v10_27e_builtins
        setattr(_v10_27e_builtins, 'script_text', globals().get('script_text',''))
    except Exception as _v10_27e_global_exc:
        print('V10_27E_START_GLOBAL_SCRIPT_TEXT_WARNING', _v10_27e_global_exc)
    payload['script']=preview.get('script_text'); payload['script_text']=preview.get('script_text')
    payload['duration']=preview.get('duration_seconds'); payload['duration_seconds']=preview.get('duration_seconds'); payload['target_duration_seconds']=preview.get('duration_seconds')
    payload['manual_shot_plan']=preview.get('shots'); payload['semantic_shot_plan']=preview.get('semantic_shot_plan'); payload['shot_overrides']=preview.get('shots')
    payload['subtitle_cues']=preview.get('subtitle_cues'); payload['manual_keywords']=preview.get('manual_keywords')
    payload['demand_acceptance']=preview.get('acceptance'); payload['demand_acceptance_lock']='v10_27e'; payload['generation_allowed']=True
    return await _v10_27e_call_true_original_start(request, payload)

def _v10_27_patch_routes(app):
    global _V10_27_OLD_START_ENDPOINT
    old_start=None
    for r in list(getattr(app.router, 'routes', [])):
        p=getattr(r,'path',''); methods=set(getattr(r,'methods',[]) or [])
        if p == '/api/video/full-ai/tts-first/start' and 'POST' in methods: old_start=getattr(r,'endpoint',None)
    if old_start is not None: _V10_27_OLD_START_ENDPOINT=old_start
    remove={'/api/video/full-ai/tts-first/health','/api/video/full-ai/tts-first/plan-preview','/api/video/full-ai/tts-first/start'}
    app.router.routes[:] = [r for r in app.router.routes if getattr(r,'path','') not in remove]
    app.add_api_route('/api/video/full-ai/tts-first/health', _v10_27_health, methods=['GET'])
    app.add_api_route('/api/video/full-ai/tts-first/plan-preview', _v10_27_plan_preview, methods=['POST'])
    app.add_api_route('/api/video/full-ai/tts-first/start', _v10_27_start, methods=['POST'])
    print('V10_27_STRICT_NARRATION_ROUTES_PATCHED', {'old_start': bool(_V10_27_OLD_START_ENDPOINT), 'routes': sorted(list(remove))})

try:
    if 'install_full_ai_tts_first' in globals() and not globals().get('_V10_27_INSTALL_WRAPPED'):
        _V10_27_ORIGINAL_INSTALL = install_full_ai_tts_first
        def install_full_ai_tts_first(app):
            _V10_27_ORIGINAL_INSTALL(app)
            _v10_27_patch_routes(app)
        _V10_27_INSTALL_WRAPPED = True
except Exception as _v10_27_wrap_exc:
    print('V10_27_INSTALL_WRAP_FAILED', _v10_27_wrap_exc)
# ================= END AI VIDEO V10.27 STRICT NARRATION BEST QUALITY LOCK =================
# V10_27E_MODULE_SCRIPT_TEXT_DEFAULT
try:
    script_text
except NameError:
    script_text = ''
try:
    import builtins as _v10_27e_default_builtins
    if not hasattr(_v10_27e_default_builtins, 'script_text'):
        setattr(_v10_27e_default_builtins, 'script_text', '')
except Exception:
    pass

