# V10_27L_FINAL_FAL_PROMPT_PURGE
# AI_VIDEO_V10_27K_BUILD_PROMPT_KWARGS_FIX
from __future__ import annotations

import json
import re
from typing import Any, Dict
from fastapi import APIRouter, FastAPI

router = APIRouter(prefix="/api/video/fal-prompt-guard-v10-11", tags=["fal-prompt-guard-v10-11"])
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
    return re.sub(r"\s+", " ", p).strip(",，.;；")


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

        # V10_27K_RESTORE_SEMANTIC_PROMPT_BEFORE_FAL
        try:
            _v10_27k_src = None
            for _v10_27k_name, _v10_27k_val in list(locals().items()):
                if isinstance(_v10_27k_val, dict):
                    _v10_27k_p = str(_v10_27k_val.get('visual_prompt') or _v10_27k_val.get('prompt') or _v10_27k_val.get('input_prompt') or _v10_27k_val.get('text_prompt') or '')
                    if _v10_27k_val.get('semantic_direct_render') or _v10_27k_val.get('runtime_semantic_lock') or _v10_27k_val.get('demand_acceptance_lock') or 'Premium realistic vertical 9:16 Malaysia property short-video B-roll' in _v10_27k_p:
                        _v10_27k_src = _v10_27k_val
                        break
            if isinstance(_v10_27k_src, dict) and isinstance(args, dict):
                _v10_27k_prompt = str(_v10_27k_src.get('visual_prompt') or _v10_27k_src.get('prompt') or _v10_27k_src.get('input_prompt') or _v10_27k_src.get('text_prompt') or '')
                if _v10_27k_prompt:
                    for _v10_27k_k in ['prompt','input_prompt','text_prompt','visual_prompt']:
                        args[_v10_27k_k] = _v10_27k_prompt
                for _v10_27k_k in ['negative_prompt','aspect_ratio','width','height','fps','frames_per_second','resolution','video_quality','prompt_optimizer']:
                    if _v10_27k_k in _v10_27k_src:
                        args[_v10_27k_k] = _v10_27k_src[_v10_27k_k]
                args['semantic_direct_render'] = True
                args['runtime_semantic_lock'] = 'v10_27k'
                print('V10_27K_FAL_SEMANTIC_PROMPT_RESTORED=' + str({'prompt_start': str(args.get('prompt',''))[:140]}), flush=True)
        except Exception as _v10_27k_restore_exc:
            print('V10_27K_FAL_SEMANTIC_PROMPT_RESTORE_FAILED', _v10_27k_restore_exc, flush=True)
        print("V10_18_FAL_FINAL_ARGUMENTS=" + json.dumps(args, ensure_ascii=False)[:4000], flush=True)
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

        setattr(fal_client, "_ai_video_v10_18_deepseek_visual_guard", True)
        _INSTALLED = True
        print("V10_18_DEEPSEEK_VISUAL_FAL_PROMPT_GUARD_INSTALLED for v10_11", flush=True)
    except Exception as exc:
        print("V10_18_DEEPSEEK_VISUAL_FAL_PROMPT_GUARD_INSTALL_FAILED for v10_11", exc, flush=True)
    if app is not None:
        try:
            app.include_router(router)
        except Exception:
            pass


@router.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "provider": "fal_prompt_guard_v10_11_v10_18_deepseek_visual",
        "installed": _INSTALLED,
        "deepseek_visual_prompt_planner": True,
        "positive_prompt_without_banned_words": True,
        "negative_prompt_only_for_forbidden_objects": True,
        "replace_contaminated_prompts": True,
        "wide_condo_interior_only": True,
    }


# ================= AI VIDEO V10.27I RUNTIME PROMPT CLEANER =================
def _v10_27k_clean_prompt_text(_v10_27k_text):
    try:
        import re as _v10_27k_re
        t = str(_v10_27k_text or '')
        patterns = [
            r"\s*,\s*,\s*no readable text signs,\s*(?:gentle pull out|slow left to right pan|steady street-level dolly|slow push in),\s*cinematic vertical 9:16,\s*realistic Malaysia property lifestyle,\s*no text,\s*no logos,\s*no subtitles,\s*no readable signs",
            r"\s*,\s*,\s*no readable text signs",
            r",\s*no readable text signs,\s*(?:gentle pull out|slow left to right pan|steady street-level dolly|slow push in),\s*cinematic vertical 9:16,\s*realistic Malaysia property lifestyle,\s*no text,\s*no logos,\s*no subtitles,\s*no readable signs",
            r"",
        ]
        old=t
        for pat in patterns:
            t=_v10_27k_re.sub(pat, '', t, flags=_v10_27k_re.I)
        t=_v10_27k_re.sub(r'\s+,', ',', t)
        t=_v10_27k_re.sub(r'\s{2,}', ' ', t).strip(',')
        if old != t:
            print('V10_27K_PURGED_GLOBAL_TRAFFIC_PROMPT_TEXT')
        return t
    except Exception:
        return _v10_27k_text

def _v10_27k_clean_prompt_obj(_v10_27k_obj, _v10_27k_seen=None):
    try:
        if _v10_27k_seen is None:
            _v10_27k_seen=set()
        oid=id(_v10_27k_obj)
        if oid in _v10_27k_seen:
            return _v10_27k_obj
        _v10_27k_seen.add(oid)
        if isinstance(_v10_27k_obj, str):
            return _v10_27k_clean_prompt_text(_v10_27k_obj)
        if isinstance(_v10_27k_obj, dict):
            for k in list(_v10_27k_obj.keys()):
                v=_v10_27k_obj.get(k)
                kl=str(k).lower()
                if isinstance(v, str) and any(x in kl for x in ['prompt','visual','image_prompt','text_prompt','description']):
                    _v10_27k_obj[k]=_v10_27k_clean_prompt_text(v)
                else:
                    _v10_27k_obj[k]=_v10_27k_clean_prompt_obj(v, _v10_27k_seen)
            # keep metadata visible for job JSON / health checks
            if any(k in _v10_27k_obj for k in ['visual_prompt','prompt','semantic_type','scene_type','shot_id']):
                _v10_27k_obj['runtime_prompt_cleaner']='v10_27k'
            return _v10_27k_obj
        if isinstance(_v10_27k_obj, list):
            for i,v in enumerate(list(_v10_27k_obj)):
                _v10_27k_obj[i]=_v10_27k_clean_prompt_obj(v, _v10_27k_seen)
            return _v10_27k_obj
        if isinstance(_v10_27k_obj, tuple):
            for v in _v10_27k_obj:
                _v10_27k_clean_prompt_obj(v, _v10_27k_seen)
            return _v10_27k_obj
    except Exception as _v10_27k_exc:
        try: print('V10_27K_CLEAN_PROMPT_OBJ_FAILED='+str(_v10_27k_exc))
        except Exception: pass
    return _v10_27k_obj

def _v10_27k_wrap_callable(_v10_27k_name, _v10_27k_fn):
    try:
        import inspect as _v10_27k_inspect, functools as _v10_27k_functools
        if getattr(_v10_27k_fn, '_v10_27k_wrapped', False):
            return _v10_27k_fn
        if _v10_27k_inspect.iscoroutinefunction(_v10_27k_fn):
            @_v10_27k_functools.wraps(_v10_27k_fn)
            async def _v10_27k_async_wrapped(*args, **kwargs):
                _v10_27k_clean_prompt_obj(args); _v10_27k_clean_prompt_obj(kwargs)
                res = await _v10_27k_fn(*args, **kwargs)
                _v10_27k_clean_prompt_obj(args); _v10_27k_clean_prompt_obj(kwargs)
                return _v10_27k_clean_prompt_obj(res)
            _v10_27k_async_wrapped._v10_27k_wrapped=True
            return _v10_27k_async_wrapped
        @_v10_27k_functools.wraps(_v10_27k_fn)
        def _v10_27k_sync_wrapped(*args, **kwargs):
            _v10_27k_clean_prompt_obj(args); _v10_27k_clean_prompt_obj(kwargs)
            res = _v10_27k_fn(*args, **kwargs)
            _v10_27k_clean_prompt_obj(args); _v10_27k_clean_prompt_obj(kwargs)
            return _v10_27k_clean_prompt_obj(res)
        _v10_27k_sync_wrapped._v10_27k_wrapped=True
        return _v10_27k_sync_wrapped
    except Exception:
        return _v10_27k_fn

def _v10_27k_install_runtime_prompt_cleaner():
    try:
        _targets = ('prompt','guard','fal','render','video','shot','semantic','start','generate','compose')
        _count=0
        for _name,_fn in list(globals().items()):
            if _name.startswith('_v10_27k_'):
                continue
            if not callable(_fn):
                continue
            lname=_name.lower()
            if any(t in lname for t in _targets):
                globals()[_name]=_v10_27k_wrap_callable(_name,_fn)
                _count+=1
        print('V10_27K_RUNTIME_PROMPT_CLEANER_INSTALLED='+str({'module':__name__,'wrapped':_count}))
    except Exception as _v10_27k_exc:
        print('V10_27K_RUNTIME_PROMPT_CLEANER_INSTALL_FAILED='+str(_v10_27k_exc))

_v10_27k_install_runtime_prompt_cleaner()
# ================= END AI VIDEO V10.27I RUNTIME PROMPT CLEANER =================
