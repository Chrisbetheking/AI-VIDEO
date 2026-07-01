from __future__ import annotations

import json
import math
from copy import deepcopy
from typing import Any, Dict, List

from fastapi import FastAPI
from starlette.requests import Request


SCENES = [
    "KLCC Twin Towers skyline with luxury high-rise condominium in the foreground, Kuala Lumpur premium real estate commercial, vertical 9:16 cinematic video",
    "Kuala Lumpur city-view luxury condo balcony overlooking the Petronas Twin Towers, premium Malaysia property lifestyle, vertical 9:16",
    "modern luxury condo living room with floor-to-ceiling windows and KLCC skyline outside, high-end real estate commercial, vertical 9:16",
    "premium condominium lobby in Kuala Lumpur, elegant residential atmosphere, luxury property marketing video, vertical 9:16",
    "infinity pool on a high-rise condo rooftop with Kuala Lumpur skyline and residential towers, premium Malaysia condo lifestyle, vertical 9:16",
    "TRX financial district and luxury residential towers in Kuala Lumpur, cinematic city lifestyle, vertical 9:16",
    "Mont Kiara upscale condominium neighborhood, family-friendly premium residential lifestyle, vertical 9:16",
    "Penang ocean-view condominium balcony with elegant seaside second-home lifestyle, Malaysia real estate commercial, vertical 9:16",
]


def _target_seconds(data: Dict[str, Any]) -> int:
    for k in ("duration_seconds", "target_seconds", "targetSeconds", "duration", "targetDuration"):
        try:
            v = int(float(data.get(k) or 0))
            if v > 0:
                return v
        except Exception:
            pass
    return 20


def _target_script_chars(seconds: int) -> int:
    # 中文口播粗略 4.5~5 字/秒，20 秒约 90~100 字
    return max(60, int(seconds * 4.8))


def _normalize_script(text: str, title: str, seconds: int) -> str:
    text = (text or "").strip()
    title = (title or "马来西亚买房，别只看价格").strip()

    if not text:
        text = (
            f"{title}。很多人买房第一眼只看价格，但在马来西亚，真正要先看的是区域、用途和流动性。"
            "如果你是自住、出租、第二家园或者家庭配置，判断标准完全不一样。"
            "先把需求和预算筛清楚，再去看吉隆坡、槟城或海边项目，才不会被带节奏。"
        )

    target = _target_script_chars(seconds)

    if len(text) < int(target * 0.75):
        text += (
            " 吉隆坡要重点看 KLCC、TRX、Mont Kiara 这类城市核心区的生活和出租逻辑。"
            "如果是第二家园和养老，再去考虑槟城、兰卡威、沙巴这些海边生活方式。"
        )

    if len(text) > int(target * 1.35):
        text = text[: int(target * 1.25)].rstrip("，。 ") + "。"

    return text


def _scene_prompt(index: int) -> str:
    scene = SCENES[(index - 1) % len(SCENES)]
    return (
        scene
        + ". Ultra realistic, premium real estate commercial style, natural lighting, clean composition, high detail, smooth camera movement. "
        + "No readable text, no logo, no watermark, no fake project name, no exact price, no exact ROI, no exact school name, no black borders."
    )


def _rewrite_full_ai_request(data: Dict[str, Any]) -> Dict[str, Any]:
    target = _target_seconds(data)
    required = max(4 if target >= 20 else 1, math.ceil(target / 5.0))

    title = str(data.get("title") or data.get("topic") or "马来西亚买房，别只看价格")
    data["script_text"] = _normalize_script(str(data.get("script_text") or ""), title, target)

    shots: List[Dict[str, Any]] = []
    for i in range(1, required + 1):
        shots.append({
            "prompt": _scene_prompt(i),
            "image_url": None,
            "shot_id": None,
            "duration_seconds": round(target / required, 2),
        })

    data["shots"] = shots
    data["duration_seconds"] = target
    data["target_seconds"] = target
    data["targetDuration"] = target
    data["width"] = 1080
    data["height"] = 1920
    data["fps"] = int(data.get("fps") or 30)
    data["max_shots"] = required
    data["fal_fill_shots"] = required
    data["visual_prompt_version"] = "malaysia_final_guard_v1"

    print(
        f"FULL_AI_FINAL_GUARD_APPLIED target={target} shots={required} "
        f"script_chars={len(data['script_text'])} first_prompt={shots[0]['prompt'][:180]}"
    )
    return data


def install_full_ai_final_guard(app: FastAPI) -> None:
    @app.middleware("http")
    async def full_ai_final_guard_middleware(request: Request, call_next):
        if request.method.upper() != "POST" or request.url.path != "/api/video/full-ai/start":
            return await call_next(request)

        body = await request.body()
        try:
            data = json.loads(body.decode("utf-8") or "{}")
            if isinstance(data, dict):
                data = _rewrite_full_ai_request(data)
                new_body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            else:
                new_body = body
        except Exception as exc:
            print("FULL_AI_FINAL_GUARD_FAILED", exc)
            return await call_next(request)

        async def receive():
            return {"type": "http.request", "body": new_body, "more_body": False}

        scope = dict(request.scope)
        headers = [(k, v) for k, v in scope.get("headers", []) if k.lower() != b"content-length"]
        headers.append((b"content-length", str(len(new_body)).encode()))
        scope["headers"] = headers

        response = await call_next(Request(scope, receive))
        response.headers["x-ai-video-final-guard"] = "malaysia-final-v1"
        return response
