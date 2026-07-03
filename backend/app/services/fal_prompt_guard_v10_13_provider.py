from __future__ import annotations

import json
from typing import Any, Dict
from fastapi import APIRouter, FastAPI

router = APIRouter(prefix="/api/video/fal-prompt-guard-v10-13", tags=["fal-prompt-guard-v10-13"])
_INSTALLED = False

NEGATIVE = (
    "collage, split screen, multi panel, multi-panel, panels, grid, storyboard, contact sheet, brochure, poster, magazine layout, "
    "multiple rooms, multiple photos, montage board, picture in picture, frame within frame, black border, white border, "
    "documents, papers, file folder, chart, graph, calculator, UI, screenshot, readable text, fake text, logo, watermark, "
    "Petronas Twin Towers, KLCC Twin Towers, landmark towers, repeated skyline, beach, ocean, island"
)

PROMPT = (
    "single uncut vertical 9:16 realistic phone video of one clean modern Kuala Lumpur condominium living room interior, "
    "one full-screen image only, one locked camera angle, slow subtle natural movement, warm daylight, premium but realistic, "
    "no people, no readable text, no skyline landmark, no project name. "
    "Absolutely no montage, no collage, no split screen, no panels, no grid, no brochure, no poster, no storyboard, no picture-in-picture. "
    "Only one normal interior background shot filling the whole screen."
)


def _rewrite_args(arguments: Any) -> Any:
    if not isinstance(arguments, dict):
        return arguments
    args: Dict[str, Any] = dict(arguments)
    args.pop("shots", None)
    args.pop("storyboard", None)
    args.pop("scenes", None)
    for k in ("prompt", "input_prompt", "text_prompt", "visual_prompt"):
        args[k] = PROMPT
    old_neg = str(args.get("negative_prompt") or "")
    args["negative_prompt"] = (old_neg + ", " + NEGATIVE).strip(", ") if old_neg else NEGATIVE
    args["aspect_ratio"] = "9:16"
    args["width"] = 1080
    args["height"] = 1920
    for k in ("duration", "duration_seconds", "video_duration"):
        if k in args:
            try:
                args[k] = min(float(args[k]), 5.0)
            except Exception:
                args[k] = 5.0
    args["prompt_optimizer"] = False
    try:
        print("V10_13_FAL_FINAL_ARGUMENTS=" + json.dumps(args, ensure_ascii=False)[:3000], flush=True)
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

        setattr(fal_client, "_ai_video_v10_13_prompt_guard", True)
        _INSTALLED = True
        print("V10_13_FAL_PROMPT_GUARD_INSTALLED", flush=True)
    except Exception as exc:
        print("V10_13_FAL_PROMPT_GUARD_INSTALL_FAILED", exc, flush=True)
    if app is not None:
        try:
            app.include_router(router)
        except Exception:
            pass


@router.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "provider": "fal_prompt_guard_v10_13",
        "installed": _INSTALLED,
        "one_visual_only": True,
        "fixed_single_interior_background": True,
        "no_people": True,
        "no_collage_split_screen": True,
        "no_multi_shots": True,
    }
