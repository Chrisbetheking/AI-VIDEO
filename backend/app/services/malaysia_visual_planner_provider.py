from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Tuple

from fastapi import APIRouter, FastAPI
from pydantic import BaseModel
from starlette.requests import Request

router = APIRouter(prefix="/api/video/malaysia-visual", tags=["malaysia-visual-planner"])

NEGATIVE = (
    "irrelevant close-up, irrelevant indoor scene, generic office meeting, random business conference, "
    "plain office room, abstract background, talking head interview, unrelated factory, "
    "text, subtitles, captions, readable words, logo, watermark, signboard, price tag, "
    "fake UI, poster, banner, floorplan text, black bars, letterbox, pillarbox, cartoon, anime, blurry"
)

# 这个 middleware 是第二道保险：即使下游 fal 接口只拿 prompt，仍然按口播语义改画面。
SCENES: Dict[str, Dict[str, Any]] = {
    "transport": {
        "label": "交通通勤",
        "visuals": [
            "MRT or LRT station entrance in Kuala Lumpur with commuters, no readable signs",
            "main road traffic beside modern Malaysian residential condominiums",
            "condo resident walking toward public transport station during morning commute",
        ],
        "must": "MRT/LRT station, bus stop, main road, commuters, traffic",
        "forbid": "living room, bedroom, balcony-only, pool-only",
    },
    "amenities": {
        "label": "生活配套",
        "visuals": [
            "neighborhood supermarket, convenience stores and restaurants near Malaysian condo, no readable signs",
            "shopping mall and food street around residential towers in Malaysia",
            "daily commercial street with grocery, cafe, pharmacy and residents walking",
        ],
        "must": "supermarket, mall, restaurants, convenience stores, pharmacy, daily life",
        "forbid": "empty indoor apartment, skyline-only, document close-up",
    },
    "medical": {
        "label": "医疗诊所",
        "visuals": [
            "neighborhood clinic and pharmacy street scene near Malaysian condo, no readable signs",
            "resident leaving condo by car for clinic visit, realistic daily inconvenience",
            "clean urban clinic street near residential towers, Malaysia lifestyle",
        ],
        "must": "clinic, pharmacy, car trip, medical access",
        "forbid": "luxury room, pool, KLCC-only",
    },
    "interior_layout": {
        "label": "户型室内",
        "visuals": [
            "modern Malaysian condo living room with natural daylight and floor-to-ceiling windows",
            "clean apartment kitchen and dining area, practical daily living layout",
            "bright bedroom and balcony connection in modern high-rise condominium",
        ],
        "must": "living room, kitchen, bedroom, balcony, daylight, layout",
        "forbid": "MRT, supermarket, clinic, unrelated street crowd",
    },
    "community": {
        "label": "小区社区",
        "visuals": [
            "condominium garden walkway with residents, premium community atmosphere",
            "condo lobby entrance with security and residents, property management feel",
            "children playground and landscaped facilities inside Malaysian condo community",
        ],
        "must": "garden, lobby, residents, security, playground, pool or gym",
        "forbid": "document close-up, skyline-only, traffic-only",
    },
    "investment": {
        "label": "投资出租",
        "visuals": [
            "rental viewing scene outside modern condo with agent and potential tenant, no logos",
            "busy residential district with high-rise condos and office commute crowd",
            "condo exterior near office district implying rental demand, no readable signs",
        ],
        "must": "rental demand, tenant, condo exterior, people flow, office district",
        "forbid": "calculator, fake ROI chart, document-only",
    },
    "risk_regret": {
        "label": "踩坑后悔",
        "visuals": [
            "buyer hesitating outside distant condo area with inconvenient surroundings",
            "resident waiting for ride-hailing outside condo because access is inconvenient",
            "long commute scene from residential tower to main road, realistic daily problem",
        ],
        "must": "inconvenience, hesitation, distant location, daily-life problem",
        "forbid": "perfect luxury brochure, happy pool-only, skyline-only",
    },
    "second_home_seaside": {
        "label": "海景第二家园",
        "visuals": [
            "Penang ocean-view condominium balcony with tropical daylight",
            "coastal residential walkway with palm trees and seaside condo lifestyle",
            "resort-style residential pool near the sea in Malaysia, premium realistic",
        ],
        "must": "sea view, tropical residential lifestyle, second-home atmosphere",
        "forbid": "Kuala Lumpur skyline unless narration mentions KL, inland traffic",
    },
    "city_location": {
        "label": "城市区域",
        "visuals": [
            "street-level Malaysian city residential district with modern high-rise condominiums",
            "premium condominium exterior beside active urban street in Kuala Lumpur",
            "TRX or Mont Kiara style urban district with residential towers and daily street life",
        ],
        "must": "city district, condo exterior, neighborhood context, street life",
        "forbid": "only indoor room, only documents, only calculator, repeated KLCC-only shot",
    },
}

KEYWORDS: List[Tuple[str, List[str]]] = [
    ("medical", ["看病", "小毛病", "医院", "诊所", "药房", "医疗", "clinic", "hospital", "pharmacy"]),
    ("transport", ["地铁", "轻轨", "mrt", "lrt", "公交", "主干道", "通勤", "出勤", "上班", "堵车", "开车", "半小时", "交通", "station", "traffic", "road"]),
    ("amenities", ["生活配套", "配套", "超市", "便利店", "商场", "菜市场", "餐饮", "买菜", "吃饭", "mall", "supermarket", "restaurant", "grocery"]),
    ("interior_layout", ["户型", "采光", "装修", "客厅", "卧室", "厨房", "阳台", "室内", "空间", "窗", "layout", "interior", "bedroom", "kitchen", "balcony"]),
    ("community", ["小区", "社区", "园林", "物业", "安保", "泳池", "健身房", "大堂", "设施", "community", "lobby", "pool", "gym"]),
    ("second_home_seaside", ["第二家园", "养老", "度假", "海景", "海边", "槟城", "兰卡威", "沙巴", "penang", "langkawi", "sabah", "ocean", "seaside", "beach"]),
    ("investment", ["投资", "出租", "租金", "转手", "流动性", "回报", "租客", "investment", "rental", "tenant", "liquidity"]),
    ("risk_regret", ["后悔", "踩坑", "风险", "不方便", "麻烦", "太远", "大打折扣", "别只看", "regret", "risk", "inconvenient"]),
    ("city_location", ["区域", "地段", "位置", "城市", "吉隆坡", "klcc", "trx", "mont kiara", "kuala lumpur", "location", "district"]),
]


class MalaysiaVisualPlanRequest(BaseModel):
    topic: str = "马来西亚吉隆坡买房，别只看价格"
    script_text: str = ""
    shots: List[Dict[str, Any]] = []


def _txt(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    return json.dumps(v, ensure_ascii=False)


def _semantic(text: str) -> str:
    raw = (text or "").lower()
    for typ, keys in KEYWORDS:
        if any(k.lower() in raw for k in keys):
            return typ
    return "city_location"


def build_prompt(raw_prompt: str, topic: str = "", index: int = 1, narration: str = "") -> str:
    text = f"{topic}\n{raw_prompt}\n{narration}"
    typ = _semantic(text)
    recipe = SCENES[typ]
    scene = recipe["visuals"][(index - 1) % len(recipe["visuals"])]
    return (
        "Premium realistic vertical 9:16 B-roll for Malaysia real-estate short video.\n"
        f"Semantic category: {recipe['label']}.\n"
        f"Narration meaning to match: {(narration or raw_prompt)[:120]}.\n"
        f"Required visual subject: {scene}.\n"
        f"Must show: {recipe['must']}.\n"
        f"Do not show: {recipe['forbid']}.\n"
        "Ultra realistic, mobile-first vertical framing, natural light, smooth camera motion, clean composition.\n"
        "No readable text, no logo, no watermark, no fake project name, no exact price, no exact ROI, no black borders."
    )


def rewrite_fal_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return data
    topic = _txt(data.get("title") or data.get("topic") or data.get("script_text") or data.get("prompt"))
    shots = data.get("shots") or data.get("manual_shot_plan")
    if isinstance(shots, list):
        for i, shot in enumerate(shots, start=1):
            if not isinstance(shot, dict):
                continue
            narration = _txt(shot.get("narration_segment") or shot.get("script") or shot.get("text") or "")
            # 如果上游已经是 semantic_storyboard_v2，则只补 negative，不再乱改人工 prompt。
            already_semantic = str(data.get("visual_prompt_version") or "").startswith("tts_first_semantic")
            if already_semantic and shot.get("visual_prompt"):
                shot.setdefault("prompt", shot.get("visual_prompt"))
                shot.setdefault("negative_prompt", NEGATIVE)
                continue
            raw = _txt(shot.get("prompt") or shot.get("visual_prompt") or narration or topic)
            prompt = build_prompt(raw, topic, i, narration=narration)
            shot["prompt"] = prompt
            shot["visual_prompt"] = prompt
            shot["negative_prompt"] = NEGATIVE
    if isinstance(data.get("prompt"), str):
        data["prompt"] = build_prompt(data["prompt"], topic, 1, narration=_txt(data.get("script_text")))
    if "aspect_ratio" in data:
        data["aspect_ratio"] = "9:16"
    if "width" in data:
        data["width"] = 1080
    if "height" in data:
        data["height"] = 1920
    data["negative_prompt"] = data.get("negative_prompt") or NEGATIVE
    return data


def make_plan(req: MalaysiaVisualPlanRequest) -> Dict[str, Any]:
    shots = req.shots or [{"narration_segment": x.strip()} for x in re.split(r"[。！？!?；;\n]+", req.script_text) if x.strip()]
    if not shots:
        shots = [{"narration_segment": req.topic}]
    planned = []
    for i, shot in enumerate(shots, start=1):
        raw = _txt(shot.get("prompt") or shot.get("visual_prompt") or shot.get("narration_segment") or req.topic)
        narration = _txt(shot.get("narration_segment") or raw)
        prompt = build_prompt(raw, f"{req.topic}\n{req.script_text}", i, narration=narration)
        planned.append({"index": i, "semantic_type": _semantic(narration or raw), "narration_segment": narration, "prompt": prompt})
    return {"ok": True, "provider": "malaysia_visual_planner_semantic_v2", "shots": planned}


@router.get("/health")
def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "provider": "malaysia_visual_planner_semantic_v2",
        "logic": "rewrite fal prompts by narration semantic category instead of city-anchor loop",
    }


@router.get("/self-test")
def self_test() -> Dict[str, Any]:
    return make_plan(
        MalaysiaVisualPlanRequest(
            topic="马来西亚吉隆坡买房，别只看价格",
            script_text="生活配套不方便会后悔。离地铁和主干道太远每天通勤很麻烦。看个小毛病都要开车。户型采光也要看。",
        )
    )


@router.post("/plan")
def plan(req: MalaysiaVisualPlanRequest) -> Dict[str, Any]:
    return make_plan(req)


def install_malaysia_visual_planner(app: FastAPI) -> None:
    app.include_router(router)

    @app.middleware("http")
    async def malaysia_visual_planner_middleware(request: Request, call_next):
        if request.method.upper() != "POST" or request.url.path not in {
            "/api/video/fal/storyboard/start",
            "/api/video/fal/shot/start",
        }:
            return await call_next(request)

        body = await request.body()
        try:
            data = json.loads(body.decode("utf-8") or "{}")
            new_body = json.dumps(rewrite_fal_payload(data), ensure_ascii=False).encode("utf-8")
        except Exception:
            return await call_next(request)

        async def receive():
            return {"type": "http.request", "body": new_body, "more_body": False}

        scope = dict(request.scope)
        headers = [(k, v) for k, v in scope.get("headers", []) if k.lower() != b"content-length"]
        headers.append((b"content-length", str(len(new_body)).encode()))
        scope["headers"] = headers
        response = await call_next(Request(scope, receive))
        response.headers["x-ai-video-visual-planner"] = "malaysia-semantic-v2"
        return response
