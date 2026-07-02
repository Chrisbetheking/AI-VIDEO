from __future__ import annotations

import json
import re
from typing import Any, Dict

from fastapi import APIRouter, FastAPI

router = APIRouter(prefix="/api/video/fal-prompt-guard-v10-11", tags=["fal-prompt-guard-v10-11"])
_INSTALLED = False

# V10.11: stop asking the video model for "real estate content" or "storyboard".
# Those words caused brochure/contact-sheet/multi-panel output in the user's actual generations.
# Every fal call is rewritten into a concrete single-camera phone-video scene.
KL_SCENES = [
    "a real handheld vertical phone video walking into a modern Kuala Lumpur condominium lobby, one camera take, agent opens the glass door",
    "a real handheld vertical phone video slowly moving through a modern condo living room with sofa and floor to ceiling window, one camera take",
    "a real handheld vertical phone video standing on a condo balcony looking at ordinary Kuala Lumpur residential buildings and greenery, no landmark towers",
    "a real handheld vertical phone video panning across a quiet condominium swimming pool deck with plants and lounge chairs, one camera take",
    "a real handheld vertical phone video inside a clean condo gym with treadmills and city light through windows, one camera take",
    "a real handheld vertical phone video of a real estate agent showing a client the apartment kitchen and dining area, natural walkthrough",
    "a real handheld vertical phone video of a bedroom and wardrobe detail in a modern apartment, warm daylight, one camera take",
    "a real handheld vertical phone video of Mont Kiara residential street life with condo entrance, trees and cafe frontage, one camera take",
    "a real handheld vertical phone video of TRX or Bukit Bintang street-level living radius with sidewalks, cafes and residential context, no skyline montage",
]

NEGATIVE = (
    "collage, split screen, multi panel, multi-panel, panels, grid, storyboard, contact sheet, brochure, poster, magazine layout, "
    "picture in picture, frame within frame, multiple photos, mosaic, montage board, comparison chart, UI, screenshot, "
    "document, paperwork, paper sheets, report, graph, chart, calculator, table, file folder, readable text, fake text, gibberish text, "
    "logo, watermark, caption overlay, black border, white border, Petronas Twin Towers, KLCC Twin Towers, repeated skyline, beach, ocean, island"
)

BAD_WORDS = [
    "klcc", "petronas", "twin towers", "双子塔", "国油", "collage", "split screen", "multi-panel", "multi panel", "storyboard",
    "contact sheet", "brochure", "poster", "magazine", "document", "paper", "chart", "calculator", "report", "ui", "screenshot",
    "real-estate content", "real estate content", "content", "narration meaning", "shot plan", "visual diversity", "commercial style",
]


def _idx_from_text(text: str, default: int = 1) -> int:
    m = re.search(r"(?:shot|镜头)\s*(\d+)", str(text or ""), flags=re.I)
    if m:
        try:
            return max(1, int(m.group(1)))
        except Exception:
            return default
    return default


def _scene(index: int) -> str:
    return KL_SCENES[(max(1, int(index or 1)) - 1) % len(KL_SCENES)]


def _is_bad(text: str) -> bool:
    low = str(text or "").lower()
    return any(w.lower() in low for w in BAD_WORDS)


def _single_scene_prompt(index: int, original: str = "") -> str:
    # Do not preserve original visual phrasing; it has repeatedly caused collages.
    scene = _scene(index)
    return (
        f"{scene}. "
        "Vertical 9:16 realistic phone video, one continuous camera take, full screen single scene only. "
        "No editing, no montage, no collage, no panels, no grid, no brochure, no poster, no documents, no charts, no calculator, no readable text. "
        "Natural lighting, realistic Malaysian condominium environment, smooth slow camera movement, clean residential atmosphere. "
        "Do not show KLCC, Petronas Twin Towers, beach, island, ocean, fake project name, exact price or ROI."
    )


def _rewrite_args(arguments: Any) -> Any:
    if not isinstance(arguments, dict):
        return arguments
    args: Dict[str, Any] = dict(arguments)

    if isinstance(args.get("shots"), list):
        new_shots = []
        for i, shot in enumerate(args.get("shots") or [], start=1):
            if isinstance(shot, dict):
                item = dict(shot)
                prompt = _single_scene_prompt(i, str(item.get("prompt") or item.get("visual_prompt") or item.get("scene") or item.get("title") or ""))
                item["title"] = _scene(i)
                item["scene"] = _scene(i)
                item["prompt"] = prompt
                item["visual_prompt"] = prompt
                item["duration_seconds"] = min(float(item.get("duration_seconds") or item.get("duration") or 4.0), 5.0)
                new_shots.append(item)
            else:
                new_shots.append(shot)
        args["shots"] = new_shots

    for k in ("prompt", "input_prompt", "text_prompt"):
        if isinstance(args.get(k), str):
            args[k] = _single_scene_prompt(_idx_from_text(args.get(k) or "", 1), args.get(k) or "")

    # Some fal models honor negative_prompt; harmless for those that don't.
    old_neg = str(args.get("negative_prompt") or "")
    args["negative_prompt"] = (old_neg + ", " + NEGATIVE).strip(", ") if old_neg else NEGATIVE
    args["aspect_ratio"] = "9:16"
    args["width"] = 1080
    args["height"] = 1920
    # Keep individual generations short; long text-to-video prompts are where brochure/collage appears.
    for k in ("duration", "duration_seconds", "video_duration"):
        if k in args:
            try:
                args[k] = min(float(args[k]), 5.0)
            except Exception:
                args[k] = 4.0
    try:
        args["prompt_optimizer"] = False
    except Exception:
        pass
    try:
        print("V10_11_FAL_FINAL_ARGUMENTS=" + json.dumps(args, ensure_ascii=False)[:3000], flush=True)
    except Exception:
        pass
    return args


def install_fal_prompt_guard_v10_11(app: FastAPI | None = None) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    try:
        import fal_client  # type: ignore
        try:
            import app.services.fal_video_provider as fvp  # type: ignore
        except Exception:
            fvp = None

        base_submit = getattr(fvp, "_orig_submit", None) or getattr(fal_client, "_orig_submit", None) or getattr(fal_client, "submit", None)
        base_run = getattr(fvp, "_orig_run", None) or getattr(fal_client, "_orig_run", None) or getattr(fal_client, "run", None)
        base_subscribe = getattr(fvp, "_orig_subscribe", None) or getattr(fal_client, "_orig_subscribe", None) or getattr(fal_client, "subscribe", None)

        if base_submit:
            def guarded_submit(*args, **kwargs):
                if "arguments" in kwargs:
                    kwargs["arguments"] = _rewrite_args(kwargs.get("arguments"))
                elif len(args) >= 2 and isinstance(args[1], dict):
                    args = list(args); args[1] = _rewrite_args(args[1]); args = tuple(args)
                return base_submit(*args, **kwargs)
            fal_client.submit = guarded_submit

        if base_run:
            def guarded_run(*args, **kwargs):
                if "arguments" in kwargs:
                    kwargs["arguments"] = _rewrite_args(kwargs.get("arguments"))
                elif len(args) >= 2 and isinstance(args[1], dict):
                    args = list(args); args[1] = _rewrite_args(args[1]); args = tuple(args)
                return base_run(*args, **kwargs)
            fal_client.run = guarded_run

        if base_subscribe:
            def guarded_subscribe(*args, **kwargs):
                if "arguments" in kwargs:
                    kwargs["arguments"] = _rewrite_args(kwargs.get("arguments"))
                elif len(args) >= 2 and isinstance(args[1], dict):
                    args = list(args); args[1] = _rewrite_args(args[1]); args = tuple(args)
                return base_subscribe(*args, **kwargs)
            fal_client.subscribe = guarded_subscribe

        setattr(fal_client, "_ai_video_v10_11_prompt_guard", True)
        _INSTALLED = True
        print("V10_11_FAL_PROMPT_GUARD_INSTALLED", flush=True)
    except Exception as exc:
        print("V10_11_FAL_PROMPT_GUARD_INSTALL_FAILED", exc, flush=True)

    if app is not None:
        try:
            app.include_router(router)
        except Exception:
            pass


@router.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "provider": "fal_prompt_guard_v10_11",
        "installed": _INSTALLED,
        "single_camera_take": True,
        "no_collage_split_screen": True,
        "no_brochure_or_storyboard_words": True,
        "no_documents_or_charts": True,
        "klcc_removed_from_default_kl": True,
    }
