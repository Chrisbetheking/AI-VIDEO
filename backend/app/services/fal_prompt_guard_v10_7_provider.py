# V10_27L_FINAL_FAL_PROMPT_PURGE
# AI_VIDEO_V10_27K_BUILD_PROMPT_KWARGS_FIX
from __future__ import annotations

import json
import re
from typing import Any, Dict

from fastapi import APIRouter, FastAPI

router = APIRouter(prefix="/api/video/fal-prompt-guard-v10-7", tags=["fal-prompt-guard-v10-7"])
_INSTALLED = False

# V10.7: block the exact failures seen in generated videos: repeated KLCC,
# storyboard/contact-sheet panels, paperwork/chart scenes, fake UI/text.
NEGATIVE_CORE = (
    "Petronas Twin Towers, KLCC Twin Towers, repeated Twin Towers skyline, same skyline, "
    "centered landmark tower, collage, split screen, multi panel, multi-panel, storyboard grid, "
    "contact sheet, picture in picture, frame within frame, black borders, white borders, poster layout, "
    "document layout, paper sheets, hands holding documents, financial report, chart, graph, calculator, table, "
    "readable text, fake text, logo, watermark, fake project name, exact price, exact ROI, beach, island, seaside, ocean"
)

KL_SINGLE_SCENES = [
    "single full-screen shot of a modern Kuala Lumpur condominium entrance and drop-off lobby, agent walking toward the entrance, no landmark towers",
    "single full-screen shot inside a modern luxury condo living room with sofa, warm daylight, floor-to-ceiling windows, no landmark tower",
    "single full-screen shot from a condo balcony with generic Kuala Lumpur residential skyline and greenery, no Petronas Twin Towers",
    "single full-screen shot of an elegant condominium lobby with security desk and resident lounge, premium residential feel",
    "single full-screen shot of high-rise condo swimming pool and landscaped facilities deck, residents lifestyle, no text",
    "single full-screen shot of a modern condo gym and wellness facility, clean premium residential lifestyle",
    "single full-screen shot of Mont Kiara residential community street with greenery, cafes and condominium surroundings, no famous landmark",
    "single full-screen shot of TRX or Bukit Bintang street-level urban lifestyle near premium residences, commute and cafes, no landmark skyline",
    "single full-screen shot of a real estate agent showing a client through an apartment living room and balcony, natural walkthrough",
    "single full-screen shot of modern condo kitchen, dining area and bedroom details, warm natural light, self-stay comfort",
]

BAD_VISUAL_WORDS = [
    "klcc", "twin towers", "petronas", "双子塔", "国油双峰塔",
    "collage", "split screen", "multi panel", "multi-panel", "storyboard", "contact sheet",
    "documents", "document", "paper", "papers", "checklist", "chart", "calculator", "report", "file", "文件", "资料", "报表", "计算器", "表格",
]


def _idx_from_prompt(prompt: str, default: int = 1) -> int:
    text = str(prompt or "")
    m = re.search(r"(?:shot|镜头)\s*(\d+)", text, flags=re.I)
    if m:
        try:
            return max(1, int(m.group(1)))
        except Exception:
            pass
    return default


def _bad_visual(text: str) -> bool:
    low = str(text or "").lower()
    return any(k.lower() in low for k in BAD_VISUAL_WORDS)


def _scene_for_index(index: int) -> str:
    return KL_SINGLE_SCENES[(max(1, int(index or 1)) - 1) % len(KL_SINGLE_SCENES)]


def _sanitize_prompt(prompt: str, index: int = 1) -> str:
    prompt = str(prompt or "")
    index = max(1, int(index or 1))
    scene = _scene_for_index(index)

    # Do not trust upstream visual subject if it contains KLCC/paperwork/collage patterns.
    # Preserve only narration/business meaning by not copying the visual composition.
    if _bad_visual(prompt) or len(prompt.strip()) < 40:
        visual_subject = scene
    else:
        visual_subject = prompt[:700]

    return (
        "Premium 9:16 cinematic vertical video for Malaysia real-estate content. "
        f"Shot {index} must be ONE continuous full-screen video shot only. Visual subject: {visual_subject}. "
        "No collage. No split screen. No multi-panel layout. No storyboard grid. No contact sheet. No picture-in-picture. No borders. "
        "Do not show documents, paper sheets, charts, calculators, financial reports, readable words, screenshots, UI, maps, or fake text. "
        "For Kuala Lumpur, do NOT center KLCC or Petronas Twin Towers and do NOT repeat Twin Towers skyline. "
        "Use real-estate lifestyle visuals: condo interior, balcony generic city view, lobby, pool, gym, agent showing apartment, Mont Kiara community, TRX/Bukit Bintang street-level context, kitchen, dining room, bedroom. "
        "No beach or island for Kuala Lumpur. No fake project name, no exact price, no exact ROI, no exact school or transport claim. "
        "Ultra realistic, premium real estate commercial style, natural lighting, clean composition, high detail, smooth camera movement, mobile-first vertical framing."
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
                raw_prompt = item.get("prompt") or item.get("visual_prompt") or item.get("scene") or item.get("title") or ""
                item["scene"] = _scene_for_index(i) if _bad_visual(str(item.get("scene") or item.get("title") or raw_prompt)) else (item.get("scene") or item.get("title") or _scene_for_index(i))
                item["title"] = item.get("title") or item["scene"]
                item["prompt"] = _sanitize_prompt(str(raw_prompt), i)
                item["visual_prompt"] = item["prompt"]
                new_shots.append(item)
            else:
                new_shots.append(shot)
        args["shots"] = new_shots

    if isinstance(args.get("prompt"), str):
        idx = _idx_from_prompt(args.get("prompt") or "", 1)
        args["prompt"] = _sanitize_prompt(args.get("prompt") or "", idx)

    neg = str(args.get("negative_prompt") or "")
    if NEGATIVE_CORE.lower() not in neg.lower():
        args["negative_prompt"] = (neg + ", " + NEGATIVE_CORE).strip(", ")

    for k in ("aspect_ratio", "ratio"):
        if k in args:
            args[k] = "9:16"
    if "width" in args:
        args["width"] = 1080
    if "height" in args:
        args["height"] = 1920

    try:
        print("V10_7_FAL_FINAL_ARGUMENTS=" + json.dumps(args, ensure_ascii=False)[:3000], flush=True)
    except Exception:
        pass
    return args


def install_fal_prompt_guard_v10_7(app: FastAPI | None = None) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    try:
        import fal_client  # type: ignore
        try:
            import app.services.fal_video_provider as fvp  # type: ignore
        except Exception:
            fvp = None

        base_submit = getattr(fvp, "_orig_submit", None) or getattr(fal_client, "submit", None)
        base_run = getattr(fvp, "_orig_run", None) or getattr(fal_client, "run", None)
        base_subscribe = getattr(fvp, "_orig_subscribe", None) or getattr(fal_client, "subscribe", None)

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

        setattr(fal_client, "_ai_video_v10_7_prompt_guard", True)
        _INSTALLED = True
        print("V10_7_FAL_PROMPT_GUARD_INSTALLED", flush=True)
    except Exception as exc:
        print("V10_7_FAL_PROMPT_GUARD_INSTALL_FAILED", exc, flush=True)

    if app is not None:
        try:
            app.include_router(router)
        except Exception:
            pass


@router.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "provider": "fal_prompt_guard_v10_7",
        "installed": _INSTALLED,
        "klcc_strict_guard": True,
        "single_scene_only": True,
        "no_collage_split_screen": True,
        "no_documents_or_charts": True,
        "policy": "single full-screen real-estate scene, no repeated KLCC, no collage, no paperwork visuals",
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
