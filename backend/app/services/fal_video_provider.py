from __future__ import annotations
# ===== FULL AI FAL 9X16 QUALITY PATCH =====
import os as _full_ai_os

FULL_AI_ASPECT_RATIO = _full_ai_os.getenv("FULL_AI_ASPECT_RATIO", "9:16")
FULL_AI_FAL_RESOLUTION = _full_ai_os.getenv("FULL_AI_FAL_RESOLUTION", "720p")
FULL_AI_FAL_QUALITY = _full_ai_os.getenv("FULL_AI_FAL_QUALITY", "high")

FULL_AI_NEGATIVE_PROMPT = (
    "text, subtitles, captions, words, letters, chinese characters, english words, "
    "logo, watermark, typography, signboard, price, numbers, UI, poster, banner, "
    "split screen, picture in picture, black bars, letterbox, pillarbox, low quality, blurry"
)

def _full_ai_scene_from_prompt(prompt: str) -> str:
    prompt = str(prompt or "")
    low = prompt.lower()

    if any(k in prompt for k in ["预算", "价格", "贷款", "首付"]) or any(k in low for k in ["budget", "price", "loan"]):
        return "hands reviewing property documents, calculator, notebook, clean office, realistic commercial b-roll"
    if any(k in prompt for k in ["区域", "城市", "吉隆坡", "马来西亚"]) or any(k in low for k in ["city", "kuala", "malaysia"]):
        return "modern Southeast Asian city street, condo exterior, skyline, tropical urban atmosphere, realistic"
    if any(k in prompt for k in ["出租", "投资", "租金", "回报"]) or any(k in low for k in ["rent", "investment"]):
        return "modern apartment exterior, rental lifestyle, city commute, premium residential atmosphere, realistic"
    if any(k in prompt for k in ["家庭", "养老", "教育", "孩子"]) or any(k in low for k in ["family", "education"]):
        return "family lifestyle in modern residential neighborhood, natural daylight, warm realistic atmosphere"
    return "real estate consultation, modern condo exterior, city lifestyle, property viewing mood, realistic"

def _full_ai_sanitize_prompt(prompt: str) -> str:
    scene = _full_ai_scene_from_prompt(prompt)
    return (
        "Vertical 9:16 full-screen short video B-roll, full frame composition. "
        "No black bars, no letterbox, no pillarbox. "
        "Realistic cinematic real-estate commercial style, natural camera movement, clean lighting. "
        f"Scene: {scene}. "
        "Absolutely no text, no subtitles, no captions, no logo, no watermark, no UI, "
        "no signboard, no readable words, no numbers, no price tags, no posters, no floating panels. "
        "Do not invent specific property name, project, floorplan, price, school, transport or ROI. "
        "Generic atmosphere only, suitable for Douyin/TikTok vertical video."
    )

def _full_ai_force_fal_args(args: dict) -> dict:
    args = dict(args or {})
    raw_prompt = args.get("prompt") or ""
    args["prompt"] = _full_ai_sanitize_prompt(raw_prompt)
    args["aspect_ratio"] = FULL_AI_ASPECT_RATIO
    args["resolution"] = args.get("resolution") or FULL_AI_FAL_RESOLUTION
    args["negative_prompt"] = (str(args.get("negative_prompt") or "") + ", " + FULL_AI_NEGATIVE_PROMPT).strip(", ")
    args["video_quality"] = args.get("video_quality") or FULL_AI_FAL_QUALITY
    args["video_write_mode"] = args.get("video_write_mode") or "balanced"
    return args

def _full_ai_subscribe_with_9x16_fallback(fal_client_module, model: str, arguments: dict, **kwargs):
    forced = _full_ai_force_fal_args(arguments)
    try:
        return fal_client_module.subscribe(model, arguments=forced, **kwargs)
    except Exception as exc:
        # 某些 fal 模型如果暂时不接受 aspect_ratio，就删除该字段重试；后续合成仍会强制 crop 到 9:16。
        text = str(exc).lower()
        if "aspect_ratio" in text or "extra" in text or "unexpected" in text or "422" in text:
            fallback = dict(forced)
            fallback.pop("aspect_ratio", None)
            return fal_client_module.subscribe(model, arguments=fallback, **kwargs)
        raise
# ===== /FULL AI FAL 9X16 QUALITY PATCH =====


import os
import time
import uuid
import traceback
from typing import Any, Dict, Optional

import fal_client

QUICK_T2V = os.getenv("FAL_QUICK_T2V_MODEL", "fal-ai/wan/v2.2-a14b/text-to-video/turbo")
STANDARD_T2V = os.getenv("FAL_STANDARD_T2V_MODEL", "fal-ai/wan/v2.2-a14b/text-to-video")
QUICK_I2V = os.getenv("FAL_QUICK_I2V_MODEL", "fal-ai/wan/v2.2-a14b/image-to-video/turbo")
STANDARD_I2V = os.getenv("FAL_STANDARD_I2V_MODEL", "fal-ai/wan/v2.2-a14b/image-to-video")

NO_TEXT_NEGATIVE_PROMPT = (
    "text, subtitles, captions, words, letters, chinese characters, english words, "
    "logo, watermark, typography, signboard, price, numbers, UI, poster, banner, "
    "split screen, picture in picture, black bars, letterbox, pillarbox, low quality, blurry"
)


def fal_ready() -> bool:
    return bool(os.getenv("FAL_KEY"))


def pick_model(mode: str, image_url: Optional[str]) -> str:
    mode = (mode or "quick").lower().strip()
    if image_url:
        if mode in {"standard", "high", "quality"}:
            return STANDARD_I2V
        return QUICK_I2V
    if mode in {"standard", "high", "quality"}:
        return STANDARD_T2V
    return QUICK_T2V


def _visual_category(raw: str) -> str:
    raw = str(raw or "")
    low = raw.lower()

    if any(k in raw for k in ["预算", "价格", "贷款", "首付"]) or any(k in low for k in ["budget", "price", "loan"]):
        return "hands reviewing property documents, calculator, notebook, clean office, realistic"
    if any(k in raw for k in ["区域", "城市", "吉隆坡", "马来西亚"]) or any(k in low for k in ["city", "kuala", "malaysia"]):
        return "modern Southeast Asian city street, condo exterior, skyline, tropical urban atmosphere, realistic"
    if any(k in raw for k in ["出租", "投资", "租金", "回报"]) or any(k in low for k in ["rent", "investment"]):
        return "modern apartment exterior, rental lifestyle, city commute, premium residential atmosphere, realistic"
    if any(k in raw for k in ["家庭", "养老", "教育", "孩子"]) or any(k in low for k in ["family", "education"]):
        return "family lifestyle in modern residential neighborhood, natural daylight, warm realistic atmosphere"

    return "real estate consultation, modern condo exterior, city lifestyle, property viewing mood, realistic"


def sanitize_fal_visual_prompt(prompt: str) -> str:
    """Do not feed narration/title to the video model.

    fal.ai should create only clean B-roll. All subtitles/titles are burned by our backend later.
    """
    scene = _visual_category(prompt)
    return (
        "Vertical 9:16 full-screen short video B-roll. "
        "Full frame composition, no black bars, no letterbox, no pillarbox. "
        "Realistic cinematic real-estate commercial style, natural camera movement, clean lighting. "
        f"Scene: {scene}. "
        "Absolutely no text, no subtitles, no captions, no logo, no watermark, no UI, no signboard, "
        "no readable words, no numbers, no price tags, no posters, no floating panels. "
        "Do not invent specific property name, project, floorplan, price, school, transport or ROI. "
        "Generic atmosphere only, suitable for Douyin/TikTok vertical video."
    )


def merge_negative_prompt(value: str = "") -> str:
    value = str(value or "").strip()
    if not value:
        return NO_TEXT_NEGATIVE_PROMPT
    if "text" in value.lower() and "black bars" in value.lower():
        return value
    return value + ", " + NO_TEXT_NEGATIVE_PROMPT


def extract_video_url(data: Any) -> Optional[str]:
    if isinstance(data, dict):
        if isinstance(data.get("video"), dict) and data["video"].get("url"):
            return data["video"]["url"]
        if isinstance(data.get("videos"), list) and data["videos"]:
            first = data["videos"][0]
            if isinstance(first, dict) and first.get("url"):
                return first["url"]
        if data.get("url") and isinstance(data.get("url"), str):
            return data["url"]
        for v in data.values():
            found = extract_video_url(v)
            if found:
                return found
    if isinstance(data, list):
        for item in data:
            found = extract_video_url(item)
            if found:
                return found
    return None


def build_arguments(
    prompt: str,
    mode: str = "quick",
    image_url: Optional[str] = None,
    resolution: str = "720p",
    num_frames: int = 81,
    frames_per_second: int = 16,
    negative_prompt: str = "",
    video_quality: str = "high",
    video_write_mode: str = "balanced",
) -> Dict[str, Any]:
    args: Dict[str, Any] = {
        "prompt": sanitize_fal_visual_prompt(prompt),
        "negative_prompt": merge_negative_prompt(negative_prompt),
        "resolution": resolution or "720p",
        "num_frames": int(num_frames),
        "frames_per_second": int(frames_per_second),
        "video_quality": video_quality,
        "video_write_mode": video_write_mode,
    }

    if image_url:
        args["image_url"] = image_url

    return args


def generate_fal_video(
    prompt: str,
    mode: str = "quick",
    image_url: Optional[str] = None,
    resolution: str = "720p",
    num_frames: int = 81,
    frames_per_second: int = 16,
    negative_prompt: str = "",
    video_quality: str = "high",
    video_write_mode: str = "balanced",
) -> Dict[str, Any]:
    if not fal_ready():
        raise RuntimeError("FAL_KEY is not configured")

    model = pick_model(mode=mode, image_url=image_url)
    args = build_arguments(
        prompt=prompt,
        mode=mode,
        image_url=image_url,
        resolution=resolution,
        num_frames=num_frames,
        frames_per_second=frames_per_second,
        negative_prompt=negative_prompt,
        video_quality=video_quality,
        video_write_mode=video_write_mode,
    )

    started_at = time.time()
    result = _full_ai_subscribe_with_9x16_fallback(fal_client, model, args,
        with_logs=True,
    )
    video_url = extract_video_url(result)

    return {
        "ok": True,
        "provider": "fal",
        "model": model,
        "mode": mode,
        "image_mode": bool(image_url),
        "video_url": video_url,
        "raw_result": result,
        "sanitized_prompt": args.get("prompt"),
        "negative_prompt": args.get("negative_prompt"),
        "elapsed_seconds": round(time.time() - started_at, 2),
    }


def safe_error(e: Exception) -> Dict[str, Any]:
    return {
        "ok": False,
        "error": str(e),
        "traceback_tail": traceback.format_exc()[-4000:],
    }


def make_job_id(prefix: str = "fal_video") -> str:
    return prefix + "_" + uuid.uuid4().hex[:18]



# ===== HARD OVERRIDE MALAYSIA REAL ESTATE FAL PROMPTS =====


def _hard_malaysia_real_estate_prompt(index: int = 1, narration: str = "") -> str:
    """
    KL 房产短视频不要每个镜头都拍双子塔。
    镜头序列按真实卖房逻辑走：
    城市建立信任 -> 房内 -> 阳台 -> 配套 -> 看房/咨询 -> 社区 -> 夜景收尾。
    """
    text = (narration or "").lower()

    # 如果文案明确说海边/槟城/兰卡威/沙巴，才允许海边；否则马来西亚房产默认吉隆坡城市房产
    seaside_words = ["海边", "海景", "槟城", "penang", "兰卡威", "langkawi", "沙巴", "sabah", "ocean", "seaside", "beach"]
    is_seaside = any(w in text for w in seaside_words)

    kl_sales_scenes = [
        # 1 城市信任，只出现一次，不要全片都是它
        "Kuala Lumpur premium real estate establishing shot, modern high-rise residential towers near KLCC skyline, city atmosphere, not a fake project, vertical 9:16",

        # 2 房内
        "modern Kuala Lumpur condominium living room interior, floor-to-ceiling windows, warm daylight, premium but realistic apartment design, vertical 9:16",

        # 3 阳台
        "city-view condo balcony in Kuala Lumpur, buyer standing near balcony railing, skyline in the distance, premium residential lifestyle, vertical 9:16",

        # 4 卧室 / 家庭
        "comfortable master bedroom inside a Kuala Lumpur condominium, clean interior, natural light, family own-stay atmosphere, vertical 9:16",

        # 5 厨房 / 餐厅
        "modern condo kitchen and dining area, clean fittings, practical home living detail, Malaysia urban apartment interior, vertical 9:16",

        # 6 大堂
        "premium condominium lobby in Kuala Lumpur, reception area, elegant residential entrance, no readable signage, vertical 9:16",

        # 7 泳池
        "high-rise condominium swimming pool and lounge deck in Kuala Lumpur, residential amenity lifestyle, vertical 9:16",

        # 8 健身房 / 配套
        "condominium gym and lifestyle facilities, modern residential amenities, clean premium property atmosphere, vertical 9:16",

        # 9 看房
        "real estate agent showing a Kuala Lumpur apartment interior to a buyer, natural viewing scene, no readable documents, vertical 9:16",

        # 10 社区 / 周边
        "upscale Kuala Lumpur residential neighborhood, condo exterior, greenery, driveway, security entrance, urban living environment, vertical 9:16",

        # 11 TRX / Mont Kiara 作为区域锚点
        "TRX and Mont Kiara inspired Kuala Lumpur premium residential district atmosphere, high-rise condos and city lifestyle, vertical 9:16",

        # 12 收尾
        "Kuala Lumpur night skyline with modern residential towers, premium real estate closing shot, vertical 9:16",
    ]

    seaside_scenes = [
        "Penang ocean-view condominium balcony, realistic seaside second-home lifestyle, vertical 9:16",
        "modern Penang apartment interior facing the sea, warm daylight, premium residential lifestyle, vertical 9:16",
        "Langkawi resort-style residential pool and tropical greenery, second-home lifestyle, vertical 9:16",
        "Sabah coastal residential tower with sunset marina atmosphere, vertical 9:16",
    ]

    scenes = seaside_scenes if is_seaside else kl_sales_scenes
    scene = scenes[(int(index) - 1) % len(scenes)]

    return (
        scene
        + ". Ultra realistic, premium real estate commercial style, natural lighting, clean composition, high detail, smooth camera movement. "
        + "The main subject must be real estate selling visuals, not only landmark scenery. "
        + "Use interiors, balcony, lobby, pool, amenities, viewing scenes, neighborhood and city context. "
        + "No readable text, no logo, no watermark, no fake project name, no exact price, no exact ROI, no exact school name, no fake floorplan, no black borders."
    )

def _hard_rewrite_fal_arguments_for_malaysia(arguments):
    try:
        if not isinstance(arguments, dict):
            return arguments

        # 单镜头
        if isinstance(arguments.get("prompt"), str):
            arguments["prompt"] = _hard_malaysia_real_estate_prompt(1, str(arguments.get("prompt") or arguments.get("script_text") or ""))

        # 多镜头 storyboard
        shots = arguments.get("shots")
        if isinstance(shots, list):
            for i, shot in enumerate(shots, start=1):
                if isinstance(shot, dict):
                    shot["prompt"] = _hard_malaysia_real_estate_prompt(i, str(shot.get("narration_segment") or shot.get("script") or shot.get("text") or shot.get("prompt") or ""))

        # 常见比例字段
        for k in ("aspect_ratio", "ratio"):
            if k in arguments:
                arguments[k] = "9:16"
        if "width" in arguments:
            arguments["width"] = 1080
        if "height" in arguments:
            arguments["height"] = 1920

        # 打日志，后面我们直接看最终到底喂给 fal 什么
        try:
            import json
            print("MALAYSIA_FAL_FINAL_ARGUMENTS=" + json.dumps(arguments, ensure_ascii=False)[:3000])
        except Exception:
            pass

    except Exception as exc:
        print("MALAYSIA_FAL_HARD_REWRITE_FAILED", exc)

    return arguments


try:
    import fal_client as _ai_video_fal_client_for_patch

    if not getattr(_ai_video_fal_client_for_patch, "_malaysia_prompt_hard_patched", False):
        if hasattr(_ai_video_fal_client_for_patch, "submit"):
            _orig_submit = _ai_video_fal_client_for_patch.submit

            def _malaysia_submit_patch(*args, **kwargs):
                if "arguments" in kwargs:
                    kwargs["arguments"] = _hard_rewrite_fal_arguments_for_malaysia(kwargs.get("arguments"))
                elif len(args) >= 2 and isinstance(args[1], dict):
                    args = list(args)
                    args[1] = _hard_rewrite_fal_arguments_for_malaysia(args[1])
                    args = tuple(args)
                return _orig_submit(*args, **kwargs)

            _ai_video_fal_client_for_patch.submit = _malaysia_submit_patch

        if hasattr(_ai_video_fal_client_for_patch, "run"):
            _orig_run = _ai_video_fal_client_for_patch.run

            def _malaysia_run_patch(*args, **kwargs):
                if "arguments" in kwargs:
                    kwargs["arguments"] = _hard_rewrite_fal_arguments_for_malaysia(kwargs.get("arguments"))
                elif len(args) >= 2 and isinstance(args[1], dict):
                    args = list(args)
                    args[1] = _hard_rewrite_fal_arguments_for_malaysia(args[1])
                    args = tuple(args)
                return _orig_run(*args, **kwargs)

            _ai_video_fal_client_for_patch.run = _malaysia_run_patch

        _ai_video_fal_client_for_patch._malaysia_prompt_hard_patched = True
        print("MALAYSIA_FAL_HARD_PROMPT_PATCH_INSTALLED")
except Exception as _fal_patch_exc:
    print("MALAYSIA_FAL_HARD_PROMPT_PATCH_LOAD_FAILED", _fal_patch_exc)
# ===== /HARD OVERRIDE MALAYSIA REAL ESTATE FAL PROMPTS =====




# ===== FAL SUBSCRIBE MALAYSIA HARD PATCH =====
try:
    import fal_client as _fal_subscribe_patch_client

    if not getattr(_fal_subscribe_patch_client, "_malaysia_subscribe_patched", False):
        def _mscene(i: int = 1) -> str:
            scenes = [
                "KLCC Twin Towers skyline with luxury high-rise condominium in the foreground, Kuala Lumpur premium real estate commercial, vertical 9:16 cinematic video",
                "Kuala Lumpur city-view luxury condo balcony overlooking the Petronas Twin Towers, premium Malaysia property lifestyle, vertical 9:16",
                "modern luxury condo living room with floor-to-ceiling windows and KLCC skyline outside, high-end real estate commercial, vertical 9:16",
                "premium condominium lobby in Kuala Lumpur, elegant residential atmosphere, luxury property marketing video, vertical 9:16",
                "infinity pool on a high-rise condo rooftop with Kuala Lumpur skyline and residential towers, premium Malaysia condo lifestyle, vertical 9:16",
            ]
            return scenes[(int(i) - 1) % len(scenes)] + ". No readable text, no logo, no watermark, no fake price, no black borders."

        def _rewrite_args(arguments):
            try:
                if isinstance(arguments, dict):
                    if isinstance(arguments.get("prompt"), str):
                        arguments["prompt"] = _mscene(1)
                    if isinstance(arguments.get("shots"), list):
                        for i, shot in enumerate(arguments["shots"], start=1):
                            if isinstance(shot, dict):
                                shot["prompt"] = _mscene(i)
                    if "aspect_ratio" in arguments:
                        arguments["aspect_ratio"] = "9:16"
                    if "width" in arguments:
                        arguments["width"] = 1080
                    if "height" in arguments:
                        arguments["height"] = 1920
                    import json
                    print("MALAYSIA_FAL_FINAL_ARGUMENTS=" + json.dumps(arguments, ensure_ascii=False)[:3000])
            except Exception as exc:
                print("MALAYSIA_FAL_SUBSCRIBE_REWRITE_FAILED", exc)
            return arguments

        if hasattr(_fal_subscribe_patch_client, "subscribe"):
            _orig_subscribe = _fal_subscribe_patch_client.subscribe

            def _patched_subscribe(*args, **kwargs):
                if "arguments" in kwargs:
                    kwargs["arguments"] = _rewrite_args(kwargs.get("arguments"))
                elif len(args) >= 2 and isinstance(args[1], dict):
                    args = list(args)
                    args[1] = _rewrite_args(args[1])
                    args = tuple(args)
                return _orig_subscribe(*args, **kwargs)

            _fal_subscribe_patch_client.subscribe = _patched_subscribe

        _fal_subscribe_patch_client._malaysia_subscribe_patched = True
        print("MALAYSIA_FAL_SUBSCRIBE_PATCH_INSTALLED")
except Exception as _fal_subscribe_patch_exc:
    print("MALAYSIA_FAL_SUBSCRIBE_PATCH_LOAD_FAILED", _fal_subscribe_patch_exc)
# ===== /FAL SUBSCRIBE MALAYSIA HARD PATCH =====

