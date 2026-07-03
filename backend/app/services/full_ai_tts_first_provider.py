from __future__ import annotations

import json
import math
import re
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib import request as urlrequest

from fastapi import APIRouter, FastAPI
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
    count = max(1, min(18, count))
    if unit_count:
        # 单位太少时不要强行重复；单位太多时可合并。
        count = min(count, max(1, unit_count)) if unit_count <= 3 else count
    return count


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
    segments = _merge_units_to_count(units, desired)
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

        child_payload = dict(raw)
        child_payload.update(
            {
                "title": title,
                "topic": title,
                "script_text": script,
                # 核心：视频长度以真实 TTS 音频为准，不以用户选择的 15s/20s 死卡。
                "duration_seconds": round(audio_duration, 2),
                "target_duration_seconds": round(audio_duration, 2),
                "target_seconds": round(audio_duration, 2),
                "targetSeconds": round(audio_duration, 2),
                "targetDuration": round(audio_duration, 2),
                # 核心：把语义分镜直接交给后续 full-ai/fal/compose 链路。
                "shots": shots,
                "manual_shot_plan": shots,
                "shot_overrides": {str(s["index"]): s for s in shots},
                "semantic_shot_plan": semantic_plan,
                "max_shots": len(shots),
                "fal_fill_shots": len(shots),
                "width": int(raw.get("width") or 1080),
                "height": int(raw.get("height") or 1920),
                "fps": int(raw.get("fps") or 30),
                "city": city,
                "visual_prompt_version": "tts_first_semantic_storyboard_v2",
                "no_repeat_visuals": True,
                "sync_visual_to_narration": True,
                "avoid_indoor_when_narration_is_transport_or_amenities": True,
                "avoid_klcc_repetition": True,
            }
        )

        _jobs[job_id].update(
            {
                "shots": shots,
                "semantic_shot_plan": semantic_plan,
                "shot_count": len(shots),
                "progress": 65,
                "stage": "full_ai_start",
                "child_payload_preview": {
                    "duration_seconds": child_payload["duration_seconds"],
                    "shot_count": len(shots),
                    "city": city,
                    "first_prompt": shots[0]["prompt"][:260] if shots else "",
                    "semantic_plan": semantic_plan,
                },
                "updated_at": time.time(),
            }
        )

        child = _post_json("http://127.0.0.1:8000/api/video/full-ai/start", child_payload, timeout=120)
        child_job_id = child.get("job_id") or child.get("id") or child.get("data", {}).get("job_id")
        _jobs[job_id].update(
            {
                "ok": True,
                "stage": "delegated",
                "status": "running",
                "progress": 75,
                "child_job_id": child_job_id,
                "child_start_result": child,
                "updated_at": time.time(),
            }
        )
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
        "provider": "full_ai_tts_first_semantic_storyboard_v2",
        "logic": "script -> real TTS duration -> semantic storyboard -> narration-synced shots -> full-ai compose",
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
        "provider": "full_ai_tts_first_semantic_storyboard_v2",
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
