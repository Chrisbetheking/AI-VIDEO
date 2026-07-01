from __future__ import annotations

import json
from typing import Any, Dict, List

from fastapi import APIRouter, FastAPI
from pydantic import BaseModel
from starlette.requests import Request

router = APIRouter(prefix="/api/video/malaysia-visual", tags=["malaysia-visual-planner"])

NEGATIVE = (
    "generic office meeting, random business conference, unrelated corporate people, "
    "plain office room, abstract background, talking head interview, unrelated factory, "
    "text, subtitles, captions, readable words, logo, watermark, signboard, price tag, "
    "fake UI, poster, banner, floorplan text, black bars, low quality, cartoon, anime, blurry"
)

CITY_ANCHORS = {
    "kuala_lumpur": [
        "KLCC Twin Towers skyline",
        "Petronas Twin Towers visible in the distance",
        "TRX financial district",
        "Mont Kiara luxury condominium area",
        "premium high-rise condominium exterior",
        "floor-to-ceiling window apartment interior",
        "city-view balcony",
        "modern condo lobby",
        "infinity pool with Kuala Lumpur skyline",
        "night skyline of Kuala Lumpur",
    ],
    "penang": [
        "Penang seaside condominium",
        "Gurney Drive coastal skyline",
        "ocean-view balcony",
        "modern apartment interior facing the sea",
        "beachfront lifestyle",
        "coastal swimming pool",
        "sunset over the ocean",
    ],
    "johor": [
        "Johor Bahru waterfront condominium",
        "modern high-rise apartment near city center",
        "cross-border lifestyle atmosphere",
        "family-oriented condo facilities",
        "shopping mall and city commute mood",
    ],
    "langkawi": [
        "Langkawi resort villa",
        "tropical beach villa",
        "oceanfront balcony",
        "island resort pool",
        "palm trees and sunset beach",
    ],
    "sabah": [
        "Kota Kinabalu seaside apartment",
        "Sabah sunset ocean view",
        "marina lifestyle",
        "sea-view balcony",
        "resort-style pool and tropical landscape",
    ],
}

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

def infer_city(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ["海边", "海景", "第二家园", "养老", "度假", "penang", "槟城", "seaside", "ocean", "beach"]):
        return "penang"
    if any(k in t for k in ["新山", "johor", "jb"]):
        return "johor"
    if any(k in t for k in ["兰卡威", "langkawi"]):
        return "langkawi"
    if any(k in t for k in ["沙巴", "sabah", "kota kinabalu"]):
        return "sabah"
    return "kuala_lumpur"

def infer_type(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ["出租", "租金", "回报", "转手", "投资", "rental", "roi", "investment"]):
        return "investment"
    if any(k in t for k in ["海边", "海景", "第二家园", "养老", "度假", "retirement", "second home"]):
        return "second_home"
    if any(k in t for k in ["家庭", "孩子", "教育", "学校", "自住", "family", "school"]):
        return "family"
    if any(k in t for k in ["预算", "价格", "首付", "贷款", "budget", "price"]):
        return "budget"
    return "location"

def pick_anchors(city: str, content_type: str, index: int) -> List[str]:
    base = CITY_ANCHORS.get(city) or CITY_ANCHORS["kuala_lumpur"]
    anchors = [
        base[(index - 1) % len(base)],
        base[(index + 1) % len(base)],
        base[(index + 3) % len(base)],
    ]
    if content_type == "investment":
        anchors.append("premium condo lobby, swimming pool and high-rise facilities")
    elif content_type == "second_home":
        anchors.append("seaside lifestyle, ocean-view balcony, resort-style pool")
    elif content_type == "family":
        anchors.append("family-friendly condo community, living room and neighborhood amenities")
    elif content_type == "budget":
        anchors.append("buyer reviewing generic property documents, no readable text")
    else:
        anchors.append("clear Malaysia city location and real-estate context")
    return anchors

def build_prompt(raw_prompt: str, topic: str = "", index: int = 1) -> str:
    text = f"{raw_prompt}\n{topic}"
    city = infer_city(text)
    content_type = infer_type(text)
    anchors = pick_anchors(city, content_type, index)

    return (
        "Create a premium 9:16 cinematic vertical video shot for Malaysia real-estate content.\n"
        f"Location: {city.replace('_', ' ').title()}, Malaysia.\n"
        f"Content type: {content_type}.\n"
        f"Visual anchors: {', '.join(anchors)}.\n"
        "Scene: luxury condominium exterior, city-view balcony, modern apartment interior, condo lobby, "
        "swimming pool, skyline, seaside lifestyle, or residential amenities depending on the script.\n"
        "Style: ultra realistic, premium, polished, high-end real estate commercial, natural lighting, "
        "clean composition, cinematic movement, mobile-first vertical framing.\n"
        "Truth rule: do not invent specific project name, exact price, exact ROI, exact school name, exact floorplan, "
        "or official surrounding data. Use generic Malaysia real-estate atmosphere only.\n"
        f"Avoid: {NEGATIVE}.\n"
    )

def rewrite_fal_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return data

    topic = _txt(data.get("title") or data.get("topic") or data.get("script_text") or data.get("prompt"))

    shots = data.get("shots")
    if isinstance(shots, list):
        for i, shot in enumerate(shots, start=1):
            if isinstance(shot, dict):
                raw = _txt(shot.get("prompt") or topic)
                shot["prompt"] = build_prompt(raw, topic, i)

    if isinstance(data.get("prompt"), str):
        data["prompt"] = build_prompt(data["prompt"], topic, 1)

    if "aspect_ratio" in data:
        data["aspect_ratio"] = "9:16"
    if "width" in data:
        data["width"] = 1080
    if "height" in data:
        data["height"] = 1920

    return data

def make_plan(req: MalaysiaVisualPlanRequest):
    shots = req.shots or [
        {"prompt": "吉隆坡买房，先看地段和出租"},
        {"prompt": "第二家园和海边生活方式"},
        {"prompt": "家庭自住和教育配套"},
    ]
    planned = []
    for i, shot in enumerate(shots, start=1):
        raw = _txt(shot.get("prompt") or req.topic)
        prompt = build_prompt(raw, f"{req.topic}\n{req.script_text}", i)
        planned.append({"index": i, "prompt": prompt})
    return {"ok": True, "provider": "malaysia_visual_planner_miniv1", "shots": planned}

@router.get("/health")
def health():
    return {"ok": True, "provider": "malaysia_visual_planner_miniv1", "cities": list(CITY_ANCHORS.keys())}

@router.get("/self-test")
def self_test():
    return make_plan(MalaysiaVisualPlanRequest(
        topic="马来西亚吉隆坡买房，别只看价格",
        script_text="KLCC、TRX、Mont Kiara、出租、第二家园、海边、家庭自住。"
    ))

@router.post("/plan")
def plan(req: MalaysiaVisualPlanRequest):
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
        response.headers["x-ai-video-visual-planner"] = "malaysia-miniv1"
        return response
