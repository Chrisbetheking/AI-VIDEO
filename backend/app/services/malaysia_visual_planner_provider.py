from __future__ import annotations

import json
from typing import Any, Dict, List

from fastapi import APIRouter, FastAPI
from pydantic import BaseModel
from starlette.requests import Request

router = APIRouter(prefix="/api/video/malaysia-visual", tags=["malaysia-visual-planner"])

NEGATIVE = (
    "irrelevant close-up, irrelevant close-up, irrelevant close-up, irrelevant indoor scene, generic office meeting, random business conference, unrelated corporate people, "
    "plain office room, abstract background, talking head interview, unrelated factory, "
    "text, subtitles, captions, readable words, logo, watermark, signboard, price tag, "
    "fake UI, poster, banner, floorplan text, black bars, letterbox, pillarbox, cartoon, anime, blurry"
)

KL_ANCHORS = [
    "KLCC Twin Towers skyline",
    "Petronas Twin Towers visible in the distance",
    "TRX financial district",
    "Mont Kiara luxury condominium area",
    "premium Kuala Lumpur high-rise condominium exterior",
    "floor-to-ceiling window apartment interior",
    "city-view balcony",
    "modern condo lobby",
    "infinity pool with Kuala Lumpur skyline",
    "night skyline of Kuala Lumpur",
]

SEA_ANCHORS = [
    "Penang seaside condominium",
    "Gurney Drive coastal skyline",
    "ocean-view balcony",
    "modern apartment interior facing the sea",
    "beachfront lifestyle",
    "Langkawi tropical beach villa",
    "Sabah sunset ocean view",
    "resort-style pool and tropical landscape",
]

FAMILY_ANCHORS = [
    "family-friendly condominium community",
    "modern apartment living room",
    "condo children playground",
    "Mont Kiara residential lifestyle",
    "nearby mall and daily amenities",
    "safe residential neighborhood amenities",
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

def _scene_type(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ["海边", "海景", "第二家园", "养老", "度假", "penang", "槟城", "seaside", "ocean", "beach", "langkawi", "sabah"]):
        return "second_home_seaside"
    if any(k in t for k in ["家庭", "孩子", "教育", "学校", "自住", "family", "school", "own stay"]):
        return "family_own_stay"
    if any(k in t for k in ["出租", "租金", "回报", "转手", "投资", "rental", "roi", "investment"]):
        return "investment"
    return "kuala_lumpur_location"

def _anchors_for(text: str, index: int) -> List[str]:
    typ = _scene_type(text)

    if typ == "second_home_seaside":
        base = SEA_ANCHORS
    elif typ == "family_own_stay":
        base = FAMILY_ANCHORS + KL_ANCHORS
    else:
        base = KL_ANCHORS

    anchors = [
        base[(index - 1) % len(base)],
        base[(index + 1) % len(base)],
        base[(index + 3) % len(base)],
    ]

    # 兜底永远保留马来西亚房产语义，不让它跑成普通办公室。
    if not any("KLCC" in x or "Twin Towers" in x or "Petronas" in x for x in anchors):
        anchors.append("KLCC Twin Towers skyline")
    if typ == "second_home_seaside":
        anchors.append("Penang seaside condominium and ocean-view balcony")
    if typ == "family_own_stay":
        anchors.append("Mont Kiara family-friendly condominium lifestyle")

    return anchors


def build_prompt(raw_prompt: str, topic: str = "", index: int = 1) -> str:
    text = f"{topic}\n{raw_prompt}"
    typ = _scene_type(text)

    kl_scenes = [
        "KLCC Twin Towers skyline with luxury high-rise condominium in the foreground",
        "Kuala Lumpur city-view condo balcony overlooking the Petronas Twin Towers",
        "modern luxury condo living room with floor-to-ceiling windows and KLCC skyline outside",
        "premium condominium lobby in Kuala Lumpur, elegant residential atmosphere",
        "infinity pool on a high-rise condo rooftop with Kuala Lumpur skyline",
        "TRX financial district and luxury residential towers, cinematic city lifestyle",
        "Mont Kiara upscale condominium neighborhood, premium family living atmosphere",
        "night skyline of Kuala Lumpur with high-rise residential towers and city lights",
    ]

    sea_scenes = [
        "Penang ocean-view condominium balcony with elegant seaside lifestyle",
        "Gurney Drive coastal skyline with modern residential tower atmosphere",
        "Langkawi tropical villa and resort-style residential pool",
        "Sabah sunset ocean view with premium seaside apartment atmosphere",
        "modern apartment interior facing the sea, warm tropical daylight",
        "coastal residential pool with palm trees and premium Malaysia lifestyle",
    ]

    family_scenes = [
        "Mont Kiara family-friendly condominium community with premium residential facilities",
        "modern condo living room for family own-stay lifestyle in Kuala Lumpur",
        "safe upscale residential neighborhood with condo amenities and greenery",
        "family-oriented high-rise condominium facilities in Kuala Lumpur",
    ]

    if typ == "second_home_seaside":
        scene = sea_scenes[(index - 1) % len(sea_scenes)]
        extra = "seaside second-home lifestyle, ocean view, tropical Malaysia atmosphere"
    elif typ == "family_own_stay":
        scene = family_scenes[(index - 1) % len(family_scenes)]
        extra = "family own-stay, education planning, comfortable long-term living"
    else:
        scene = kl_scenes[(index - 1) % len(kl_scenes)]
        extra = "Kuala Lumpur property investment, location value, premium condo lifestyle"

    return (
        "Premium 9:16 cinematic vertical video for Malaysia real-estate content.\n"
        f"Main scene: {scene}.\n"
        f"Theme: {extra}.\n"
        "The frame must be dominated by Malaysia property visuals: skyline, condominium exterior, balcony view, "
        "apartment interior, lobby, pool, or residential lifestyle.\n"
        "Ultra realistic, premium real estate commercial style, natural lighting, clean composition, high detail, "
        "smooth camera movement, mobile-first vertical framing, no black borders.\n"
        "No readable text, no logo, no watermark, no fake project name, no exact price, no exact ROI, no exact school name.\n"
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
    return {"ok": True, "provider": "malaysia_visual_planner_direct_v1", "shots": planned}

@router.get("/health")
def health():
    return {
        "ok": True,
        "provider": "malaysia_visual_planner_direct_v1",
        "anchors": ["KLCC Twin Towers", "TRX", "Mont Kiara", "Penang seaside", "Langkawi", "Sabah"],
    }

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
        response.headers["x-ai-video-visual-planner"] = "malaysia-direct-v1"
        return response
