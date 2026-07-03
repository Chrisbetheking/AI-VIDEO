from __future__ import annotations

import json
import re
from typing import Any, Dict
from fastapi import APIRouter, FastAPI

router = APIRouter(prefix="/api/video/fal-prompt-guard-v10-13", tags=["fal-prompt-guard-v10-13"])
_INSTALLED = False

BANNED_VISUAL_NEGATIVE = (
    "office desk, desk, paperwork, papers, document, documents, floorplan, floor plan, blueprint, brochure, booklet, contract, "
    "calculator, pen, pencil, hand, hands, fingers, person, people, human, meeting, consultant, agent at desk, business meeting, "
    "chart, graph, tablet UI, computer screen, laptop, phone screen, readable text, fake text, labels, logo, watermark, "
    "collage, split screen, grid, multi panel, storyboard, poster, magazine layout, slideshow, picture in picture, black border, white border, "
    "Petronas Twin Towers, KLCC, landmark towers, beach, ocean, island"
)

BANNED_IN_POSITIVE = [
    "no people", "no hands", "no desk", "no office", "no paperwork", "no floorplan", "no blueprint", "no brochure", "no calculator",
    "without people", "without hands", "avoid papers", "avoid floorplan", "不要", "禁止", "不能", "没有人",
    "documents", "document", "papers", "paper", "floorplan", "floor plan", "blueprint", "calculator", "office desk", "office table", "meeting room",
    "hand", "hands", "fingers", "pen", "pencil", "chart", "graph", "brochure", "contract", "business meeting", "consultant", "person", "people",
    "laptop", "phone screen", "tablet", "computer", "klcc", "petronas", "beach", "ocean", "collage", "split screen", "grid"
]

DEFAULT_INTERIOR_PROMPT = (
    "vertical 9:16 realistic smartphone property viewing video, AI_VIDEO_V10_18_VISUAL_CONTRACT, "
    "wide room-level shot inside a clean modern furnished Kuala Lumpur high-rise condominium apartment interior, "
    "living room with sofa, rug, TV feature wall, curtains, wooden floor, ceiling lights and floor-to-ceiling windows, "
    "standing eye-level gimbal camera, slow forward walkthrough from doorway into the living room, premium natural daylight, full-screen architectural footage"
)


def _clean_positive(prompt: str) -> str:
    p = re.sub(r"\s+", " ", str(prompt or "").strip())
    p = re.sub(r"(?i)\b(no|without|avoid)\s+[^,.，。;；]{1,80}[,.，。;；]?", " ", p)
    return re.sub(r"\s+", " ", p).strip(" ,，.;；")


def _contaminated(prompt: str) -> bool:
    low = str(prompt or "").lower()
    if len(low.strip()) < 40:
        return True
    return any(x in low for x in BANNED_IN_POSITIVE)


def _rewrite_args(arguments: Any) -> Any:
    if not isinstance(arguments, dict):
        return arguments
    args: Dict[str, Any] = dict(arguments)
    args.pop("shots", None)
    args.pop("storyboard", None)
    args.pop("scenes", None)
    for k in ("prompt", "input_prompt", "text_prompt", "visual_prompt"):
        current = _clean_positive(str(args.get(k) or ""))
        # If the prompt has any forbidden object words, replace it completely.
        # Forbidden objects live only in negative_prompt, never in positive prompt.
        if _contaminated(current):
            current = DEFAULT_INTERIOR_PROMPT
        args[k] = current
    old_neg = str(args.get("negative_prompt") or "")
    args["negative_prompt"] = (old_neg + ", " + BANNED_VISUAL_NEGATIVE).strip(", ") if old_neg else BANNED_VISUAL_NEGATIVE
    args["aspect_ratio"] = "9:16"
    args["width"] = 1080
    args["height"] = 1920
    for k in ("duration", "duration_seconds", "video_duration"):
        if k in args:
            try:
                args[k] = min(float(args[k]), 6.0)
            except Exception:
                args[k] = 5.0
    args["prompt_optimizer"] = False
    try:
        print("V10_18_FAL_FINAL_ARGUMENTS=" + json.dumps(args, ensure_ascii=False)[:4000], flush=True)
    except Exception:
        pass
    return args


def install_fal_prompt_guard_v10_13(app: FastAPI | None = None) -> None:
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

        setattr(fal_client, "_ai_video_v10_18_deepseek_visual_guard", True)
        _INSTALLED = True
        print("V10_18_DEEPSEEK_VISUAL_FAL_PROMPT_GUARD_INSTALLED for v10_13", flush=True)
    except Exception as exc:
        print("V10_18_DEEPSEEK_VISUAL_FAL_PROMPT_GUARD_INSTALL_FAILED for v10_13", exc, flush=True)
    if app is not None:
        try:
            app.include_router(router)
        except Exception:
            pass


@router.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "provider": "fal_prompt_guard_v10_13_v10_18_deepseek_visual",
        "installed": _INSTALLED,
        "deepseek_visual_prompt_planner": True,
        "positive_prompt_without_banned_words": True,
        "negative_prompt_only_for_forbidden_objects": True,
        "replace_contaminated_prompts": True,
        "wide_condo_interior_only": True,
    }
