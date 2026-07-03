from __future__ import annotations

import json
from typing import Any, Dict
from fastapi import APIRouter, FastAPI

router = APIRouter(prefix="/api/video/fal-prompt-guard-v10-15", tags=["fal-prompt-guard-v10-15"])
_INSTALLED = False

NEGATIVE = (
    "collage, split screen, multi panel, multi-panel, panels, grid, storyboard, contact sheet, brochure, poster, magazine layout, "
    "montage board, picture in picture, frame within frame, black border, white border, static slideshow, single still image, "
    "people, human, hands, fingers, pen, pencil, documents, papers, file folder, floorplan, floor plan, blueprint, office desk, office table, meeting room, chart, graph, calculator, UI, screenshot, readable text, fake text, logo, watermark, "
    "Petronas Twin Towers, KLCC Twin Towers, landmark towers, repeated skyline, beach, ocean, island"
)

APPEND_GUARD = (
    " Full-screen vertical 9:16 realistic phone video. One normal camera view per clip with natural camera motion. "
    "No collage, no split screen, no grid, no poster, no brochure, no storyboard, no picture-in-picture. "
    "No readable text, no fake labels, no logo, no watermark, no people, no hands, no papers, no floorplans, no office table, no documents, no charts, no calculator. "
    "Do not show KLCC or Petronas Twin Towers."
)

DEFAULT_PROMPT = (
    "vertical 9:16 realistic smartphone video of a bright furnished Kuala Lumpur condominium living room interior property tour, no people no hands no documents, slow natural camera movement, "
    "premium but realistic, full-screen single camera view, no readable text, no people"
)


def _rewrite_args(arguments: Any) -> Any:
    if not isinstance(arguments, dict):
        return arguments
    args: Dict[str, Any] = dict(arguments)
    # Do not force a fixed living-room prompt anymore. Preserve the caller's scene prompt and only append safety constraints.
    args.pop("shots", None)
    args.pop("storyboard", None)
    args.pop("scenes", None)
    for k in ("prompt", "input_prompt", "text_prompt", "visual_prompt"):
        current = str(args.get(k) or "").strip()
        if not current:
            current = DEFAULT_PROMPT
        if "no collage" not in current.lower():
            current = current.rstrip(" .") + "." + APPEND_GUARD
        args[k] = current
    old_neg = str(args.get("negative_prompt") or "")
    args["negative_prompt"] = (old_neg + ", " + NEGATIVE).strip(", ") if old_neg else NEGATIVE
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
        print("V10_15_FAL_FINAL_ARGUMENTS=" + json.dumps(args, ensure_ascii=False)[:3000], flush=True)
    except Exception:
        pass
    return args


def install_fal_prompt_guard_v10_15(app: FastAPI | None = None) -> None:
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

        setattr(fal_client, "_ai_video_v10_15_prompt_guard", True)
        _INSTALLED = True
        print("V10_15_FAL_PROMPT_GUARD_INSTALLED", flush=True)
    except Exception as exc:
        print("V10_15_FAL_PROMPT_GUARD_INSTALL_FAILED", exc, flush=True)
    if app is not None:
        try:
            app.include_router(router)
        except Exception:
            pass


@router.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "provider": "fal_prompt_guard_v10_15",
        "installed": _INSTALLED,
        "preserve_scene_prompt": True,
        "dynamic_single_scene": True,
        "no_fixed_static_prompt": True,
        "no_collage_split_screen": True,
        "no_readable_text": True,
        "no_office_papers_floorplans": True,
        "force_condo_tour_visuals": True,
    }
