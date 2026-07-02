from __future__ import annotations

import json
import os
import re
import urllib.request
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/video/wizard-ai", tags=["wizard-ai"])

BAD_WORDS = {
    "房产", "选题", "镜头", "客户问题", "市场知识", "回复模板", "马来西亚", "内容大脑",
    "类型", "模式", "风格", "OpenClaw", "openclaw", "先复述问题", "最后引导补充预算",
    "生活分享讲解模板", "禁用素材规则", "R2素材自动标签", "评论区答疑模板",
    "数字人模板", "成片沉淀", "高质量成片沉淀", "低质量成片标记", "字幕库", "字幕样式",
    "吉隆坡素材优先级", "再拆判断标准", "素材库", "生成视频", "逐句配音",
}

class KeywordRequest(BaseModel):
    topic: str = ""
    market: str = "马来西亚"
    city: str = "吉隆坡"
    content_type: str = "investment"
    script_mode: str = "professional"
    manual_keywords: str = ""
    competitor_source: str = ""
    content_brain_context: list[dict[str, Any]] = Field(default_factory=list)
    source_result: Any = None
    current_script: str = ""
    require_llm: bool = True


class TopicRequest(BaseModel):
    market: str = "马来西亚"
    city: str = "吉隆坡"
    current_topic: str = ""
    content_type: str = "investment"
    script_mode: str = "professional"
    manual_keywords: str = ""
    competitor_source: str = ""
    content_brain_context: list[dict[str, Any]] = Field(default_factory=list)
    source_result: Any = None
    require_llm: bool = True

class ScriptRequest(BaseModel):
    topic: str = ""
    market: str = "马来西亚"
    city: str = "吉隆坡"
    content_type: str = "investment"
    script_mode: str = "professional"
    target_duration_seconds: int = 30
    keywords: list[dict[str, Any]] = Field(default_factory=list)
    manual_keywords: str = ""
    competitor_source: str = ""
    content_brain_context: list[dict[str, Any]] = Field(default_factory=list)
    source_result: Any = None
    require_llm: bool = True

class VoiceRequest(BaseModel):
    script: str = ""
    script_mode: str = "professional"
    keywords: list[dict[str, Any]] = Field(default_factory=list)
    script_segments: list[dict[str, Any]] = Field(default_factory=list)
    require_llm: bool = True


def _clean(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())


def _deepseek_cfg() -> dict[str, Any]:
    api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("AI_VIDEO_DEEPSEEK_API_KEY") or ""
    base_url = os.getenv("DEEPSEEK_BASE_URL") or os.getenv("AI_VIDEO_DEEPSEEK_BASE_URL") or "https://api.deepseek.com"
    model = os.getenv("DEEPSEEK_MODEL") or os.getenv("AI_VIDEO_DEEPSEEK_MODEL") or "deepseek-chat"
    timeout = float(os.getenv("DEEPSEEK_TIMEOUT_SECONDS") or os.getenv("AI_VIDEO_DEEPSEEK_TIMEOUT_SECONDS") or "60")
    return {"configured": bool(api_key), "base_url": base_url.rstrip("/"), "model": model, "timeout": timeout, "api_key": api_key}


def _extract_json(text: str) -> dict[str, Any]:
    text = str(text or "").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        pass
    match = re.search(r"\{.*\}", text, flags=re.S)
    if match:
        try:
            return json.loads(match.group(0))
        except Exception:
            pass
    return {"raw_text": text, "parse_warning": "DeepSeek 返回不是严格 JSON，已保留 raw_text。"}


def _call_deepseek_json(system_prompt: str, user_payload: dict[str, Any], require_llm: bool = True) -> dict[str, Any]:
    cfg = _deepseek_cfg()
    if not cfg["api_key"]:
        if require_llm:
            raise HTTPException(status_code=503, detail="DeepSeek API key 未配置，不能假装 AI 秒生成。请先配置 DEEPSEEK_API_KEY / AI_VIDEO_DEEPSEEK_API_KEY。")
        return {"ok": False, "llm_mode": "not_configured"}

    body = {
        "model": cfg["model"],
        "temperature": 0.35,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
    }
    req = urllib.request.Request(
        f'{cfg["base_url"]}/chat/completions',
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f'Bearer {cfg["api_key"]}'},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=cfg["timeout"]) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"DeepSeek 调用失败：{type(exc).__name__}: {exc}")
    data = json.loads(raw)
    content = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
    parsed = _extract_json(content)
    parsed["_llm_model"] = cfg["model"]
    parsed["_llm_usage"] = data.get("usage") or {}
    parsed["llm_mode"] = "deepseek"
    return parsed


def _normalize_keyword(value: Any) -> str:
    raw = str(value or "")
    clean = re.sub(r"[：:，,。！？!?；;#*`\[\]()（）【】{}]", " ", raw)
    clean = re.sub(r"\s+", " ", clean).strip()
    clean = re.sub(r"^(类型|模式|目的|结构|开头|评论|注意|镜头组合|话术|标签|规则|用户指定)\s*", "", clean).strip()
    if not clean:
        return ""
    if clean in BAD_WORDS:
        return ""
    if len(clean) < 2 or len(clean) > 12:
        return ""
    if re.fullmatch(r"[\d.]+", clean):
        return ""
    if re.match(r"^\d+[\.、]?", raw):
        return ""
    if re.search(r"(模板|规则|标签|素材|自动|禁用|OpenClaw|openclaw|内容大脑|数字人|成片|沉淀|标记|答疑|讲解模板|素材优先级)", clean):
        return ""
    if re.search(r"(房产顾问|客户问题|视频创作|生成视频|逐句配音|文案模式)", clean):
        return ""
    if re.search(r"https?://", clean, flags=re.I):
        return ""
    return clean


def _compact_brain_context(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    allowed = {"topic", "hook", "script", "market_note", "lead_question"}
    out: list[dict[str, Any]] = []
    for item in items[:30]:
        if not isinstance(item, dict):
            continue
        card_type = str(item.get("type") or item.get("card_type") or "")
        title = _clean(item.get("title"))
        content = _clean(item.get("content"))
        if card_type and card_type not in allowed:
            continue
        if re.search(r"(回复话术|评论区答疑|私信|镜头规则|素材规则|字幕|数字人|成片沉淀|模板|规则)", f"{title} {content}"):
            continue
        if title or content:
            out.append({"title": title[:60], "type": card_type or "market_note", "content": content[:220], "score": item.get("score") or 0})
    return out[:10]

def _sanitize_keywords(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            item = {"value": item}
        value = _normalize_keyword(item.get("value") or item.get("keyword") or item.get("text"))
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        priority = str(item.get("priority") or "medium").lower()
        if priority not in {"high", "medium", "low"}:
            priority = "medium"
        out.append({
            "id": str(item.get("id") or f"ai_kw_{len(out)+1}"),
            "category": _clean(item.get("category") or "AI关键词")[:16] or "AI关键词",
            "value": value,
            "reason": _clean(item.get("reason") or "DeepSeek 结合主题和内容大脑筛选。")[:80],
            "priority": priority,
        })
    return out[:18]


def _fallback_segments(script: str) -> list[dict[str, Any]]:
    parts = [p.strip() for p in re.split(r"[。！？!?；;\n]+", script or "") if p.strip()]
    return [{"id": f"seg_{i+1}", "index": i + 1, "text": p} for i, p in enumerate(parts)]


def _fallback_voice(segments: list[dict[str, Any]], script_mode: str) -> dict[str, Any]:
    settings: dict[str, Any] = {}
    notes = []
    for i, seg in enumerate(segments):
        text = _clean(seg.get("text"))
        is_hook = i == 0 or bool(re.search(r"别|不是|很多人|第一步|最怕|错", text))
        is_risk = bool(re.search(r"坑|风险|担心|怕|不能|不要|忽略|转手|空置|亏|被骗", text))
        is_cta = i == len(segments) - 1 or bool(re.search(r"评论区|打出来|预算|你是|你更|私信|联系", text))
        setting = {
            "speed": 0.93 if is_hook or is_risk else 0.98,
            "pitch": 0.98 if is_risk else 1.0,
            "volume": 1.08 if is_hook or is_risk else 1.03,
            "emotion": "重点强调" if is_hook else "提醒避坑" if is_risk else "温和引导" if is_cta else "解释说明",
            "tone": "专业可信" if not is_cta else "成交引导",
            "pauseBefore": 100 if is_hook or is_risk or is_cta else 60,
            "pauseAfter": 240 if is_hook or is_risk or is_cta else 180,
            "emphasis": [],
            "note": "规则兜底：DeepSeek 不可用时根据句意粗略判断。",
        }
        settings[str(seg.get("id") or f"seg_{i+1}")] = setting
        notes.append({"index": i + 1, "reason": setting["note"]})
    return {"segment_voice_settings": settings, "analysis_notes": notes, "llm_mode": "rule_fallback"}


@router.get("/health")
def health() -> dict[str, Any]:
    cfg = _deepseek_cfg()
    return {"ok": True, "provider": "wizard_ai_deepseek_v1", "deepseek_configured": cfg["configured"], "model": cfg["model"], "base_url": cfg["base_url"]}


@router.post("/generate-topic")
def generate_topic(req: TopicRequest) -> dict[str, Any]:
    system = """
你是 AI-VIDEO 的海外房产短视频选题导演。请基于市场、城市、内容方向、已有主题和内容大脑，生成一个可直接拍摄的中文短视频主题，并筛选干净关键词。
输出严格 JSON：{topic, title, content_type, script_mode, keywords:[{category,value,reason,priority}], angle, notes:[]}
要求：
- topic 必须是自然中文选题，不要包含模板名、编号、OpenClaw、内容大脑、镜头、选题、规则、数字人模板等系统词。
- keywords 只能是业务短词：预算、区域、人群、用途、痛点、风险、生活场景、评论区截流点。
- 禁止输出纯数字、62、风格、类型、模式、评论区答疑模板、生活分享讲解模板、R2素材自动标签。
- 不要编造楼盘、价格、收益、ROI、学校、官方信息。
- 吉隆坡内容不要写海边、沙滩、海岛。
""".strip()
    payload = req.model_dump(exclude={"require_llm"})
    payload["manual_keywords"] = "、".join([x["value"] for x in _sanitize_keywords([{"value": x} for x in re.split(r"[，,、\s]+", req.manual_keywords or "")])])
    payload["content_brain_context"] = _compact_brain_context(req.content_brain_context)
    data = _call_deepseek_json(system, payload, require_llm=req.require_llm)
    topic = _clean(data.get("topic") or data.get("title") or req.current_topic)
    if not topic or re.search(r"(模板|OpenClaw|内容大脑|数字人|评论区答疑|R2素材|62\.?|规则)", topic):
        raise HTTPException(status_code=502, detail="DeepSeek 返回的主题为空或仍含系统脏词，已阻止写入。")
    ct = _clean(data.get("content_type") or req.content_type)
    sm = _clean(data.get("script_mode") or req.script_mode)
    if ct not in {"investment", "own_stay", "second_home", "rental", "education"}:
        ct = req.content_type
    if sm not in {"lead", "professional", "life", "sales"}:
        sm = req.script_mode
    return {
        "ok": True,
        "topic": topic[:80],
        "title": _clean(data.get("title") or topic)[:80],
        "content_type": ct,
        "script_mode": sm,
        "keywords": _sanitize_keywords(data.get("keywords")),
        "angle": _clean(data.get("angle") or ""),
        "notes": data.get("notes") or [],
        "llm_mode": data.get("llm_mode"),
        "model": data.get("_llm_model"),
        "usage": data.get("_llm_usage"),
    }

@router.post("/analyze-keywords")
def analyze_keywords(req: KeywordRequest) -> dict[str, Any]:
    system = """
你是 AI-VIDEO 的短视频内容策略分析器。你必须真的分析输入，不要把数据库标签原样塞进结果。输入里的 content_brain_context 可能混有模板、回复、镜头规则，必须只抽业务短词。
输出严格 JSON：{keywords:[{category,value,reason,priority}], analysis_notes:string[]}
规则：
- 关键词必须是业务可用短词，不要出现纯数字、序号、模板名、规则名、OpenClaw、内容大脑、镜头、房产、选题、客户问题、评论区答疑模板、数字人模板、成片沉淀等泛词。
- 优先筛：预算、城市/区域、人群、用途、痛点、风险、生活场景、评论区截流点。
- 每个 value 2-14 个字符；priority 只能 high/medium/low。
- 不要编造项目名、价格、收益、ROI。
""".strip()
    payload = req.model_dump(exclude={"require_llm"})
    payload["manual_keywords"] = "、".join([x["value"] for x in _sanitize_keywords([{"value": x} for x in re.split(r"[，,、\s]+", req.manual_keywords or "")])])
    payload["content_brain_context"] = _compact_brain_context(req.content_brain_context)
    data = _call_deepseek_json(system, payload, require_llm=req.require_llm)
    keywords = _sanitize_keywords(data.get("keywords"))
    return {"ok": True, "keywords": keywords, "analysis_notes": data.get("analysis_notes") or [], "llm_mode": data.get("llm_mode"), "model": data.get("_llm_model"), "usage": data.get("_llm_usage")}


@router.post("/generate-script")
def generate_script(req: ScriptRequest) -> dict[str, Any]:
    target_chars_min = max(55, int(req.target_duration_seconds or 30) * 4)
    target_chars_max = max(80, int(req.target_duration_seconds or 30) * 6)
    system = f"""
你是海外房产短视频中文口播编导，必须调用真实输入进行创作。
输出严格 JSON：{{"title":"", "script":"", "segments":[{{"index":1,"text":""}}], "selected_keywords":[], "content_plan":[], "risk_notes":[]}}
要求：
- 口播中文自然，像真人顾问，不要像拼标签；禁止把关键词列表、模板名、卡片编号直接念出来。
- 目标长度 {target_chars_min}-{target_chars_max} 个中文字符左右。
- 结构：开头钩子 → 判断逻辑 → 专业/生活拆解 → 评论区承接。
- 根据 script_mode 区分：lead 引流，professional 专业，life 生活日常，sales 成交承接。
- 必须过滤无意义词：纯数字、62、风格、模板、OpenClaw、内容大脑、镜头、房产、选题、评论区答疑模板、数字人模板、成片沉淀。
- 不能编造具体楼盘、户型、价格、收益、学校、ROI、官方信息。
- 吉隆坡内容不能乱写海边/沙滩/岛屿。
""".strip()
    payload = req.model_dump(exclude={"require_llm"})
    payload["manual_keywords"] = "、".join([x["value"] for x in _sanitize_keywords([{"value": x} for x in re.split(r"[，,、\s]+", req.manual_keywords or "")])])
    payload["content_brain_context"] = _compact_brain_context(req.content_brain_context)
    payload["keywords"] = _sanitize_keywords(req.keywords)
    data = _call_deepseek_json(system, payload, require_llm=req.require_llm)
    script = _clean(data.get("script"))
    if not script:
        raise HTTPException(status_code=502, detail="DeepSeek 没有返回 script，已阻止假生成。")
    segments = data.get("segments") if isinstance(data.get("segments"), list) else _fallback_segments(script)
    clean_segments = []
    for idx, seg in enumerate(segments, start=1):
        if not isinstance(seg, dict):
            seg = {"text": str(seg)}
        text = _clean(seg.get("text"))
        if text:
            clean_segments.append({"id": str(seg.get("id") or f"seg_{idx}"), "index": int(seg.get("index") or idx), "text": text})
    return {
        "ok": True,
        "title": _clean(data.get("title")) or req.topic,
        "script": script,
        "segments": clean_segments or _fallback_segments(script),
        "selected_keywords": _sanitize_keywords(data.get("selected_keywords")),
        "content_plan": data.get("content_plan") or [],
        "risk_notes": data.get("risk_notes") or [],
        "llm_mode": data.get("llm_mode"),
        "model": data.get("_llm_model"),
        "usage": data.get("_llm_usage"),
    }


@router.post("/tune-voice")
def tune_voice(req: VoiceRequest) -> dict[str, Any]:
    segments = req.script_segments or _fallback_segments(req.script)
    system = """
你是短视频 TTS 声音导演。根据每句文本判断语气、情绪、停顿和重音。
输出严格 JSON：{segment_voice_settings:{seg_id:{speed,pitch,volume,emotion,tone,pauseBefore,pauseAfter,emphasis,note}}, analysis_notes:[]}
字段要求：speed/pitch/volume 为 0.75-1.3 数字；pauseBefore/pauseAfter 为毫秒整数；emotion/tone 用中文短语。
规则：开头钩子稍慢加重；风险避坑句更慢更稳；专业解释句清晰可信；评论区承接句温和引导。
不要改变文案，不要生成视频，不要编造事实。
""".strip()
    payload = req.model_dump(exclude={"require_llm"})
    data = _call_deepseek_json(system, payload, require_llm=req.require_llm)
    settings = data.get("segment_voice_settings") if isinstance(data.get("segment_voice_settings"), dict) else {}
    if not settings:
        settings = _fallback_voice(segments, req.script_mode).get("segment_voice_settings", {})
    normalized: dict[str, Any] = {}
    for i, seg in enumerate(segments):
        seg_id = str(seg.get("id") or f"seg_{i+1}")
        raw = settings.get(seg_id) or settings.get(str(i + 1)) or settings.get(f"seg_{i+1}") or {}
        if not isinstance(raw, dict):
            raw = {}
        normalized[seg_id] = {
            "speed": max(0.75, min(float(raw.get("speed") or 1.0), 1.3)),
            "pitch": max(0.75, min(float(raw.get("pitch") or 1.0), 1.3)),
            "volume": max(0.7, min(float(raw.get("volume") or 1.0), 1.3)),
            "emotion": _clean(raw.get("emotion") or "解释说明"),
            "tone": _clean(raw.get("tone") or "专业可信"),
            "pauseBefore": int(raw.get("pauseBefore") or raw.get("pause_before") or 80),
            "pauseAfter": int(raw.get("pauseAfter") or raw.get("pause_after") or 180),
            "emphasis": raw.get("emphasis") if isinstance(raw.get("emphasis"), list) else [],
            "note": _clean(raw.get("note") or "DeepSeek 已根据句意自动判断。"),
        }
    return {"ok": True, "segment_voice_settings": normalized, "analysis_notes": data.get("analysis_notes") or [], "llm_mode": data.get("llm_mode"), "model": data.get("_llm_model"), "usage": data.get("_llm_usage")}


def install_wizard_ai(app: FastAPI) -> None:
    app.include_router(router)
