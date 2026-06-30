from __future__ import annotations

import json
import os
import re
import urllib.request
import uuid
from typing import Any

from app.services.comment_lead_provider import analyze_comments
from app.services.openclaw_comment_adapter_provider import analyze_openclaw_comments
from app.services.openclaw_content_intel_provider import analyze_content


PROVIDER = "openclaw_llm_enhance_v1"


def _clean(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())


def _deepseek_config() -> dict[str, Any]:
    api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("AI_VIDEO_DEEPSEEK_API_KEY") or ""
    base_url = os.getenv("DEEPSEEK_BASE_URL") or os.getenv("AI_VIDEO_DEEPSEEK_BASE_URL") or "https://api.deepseek.com"
    model = os.getenv("DEEPSEEK_MODEL") or os.getenv("AI_VIDEO_DEEPSEEK_MODEL") or "deepseek-chat"
    timeout = float(os.getenv("DEEPSEEK_TIMEOUT_SECONDS") or os.getenv("AI_VIDEO_DEEPSEEK_TIMEOUT_SECONDS") or "45")

    return {
        "configured": bool(api_key),
        "base_url": base_url.rstrip("/"),
        "model": model,
        "timeout": timeout,
    }


def _extract_json(text: str) -> dict[str, Any]:
    text = _clean(text)

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

    return {
        "raw_text": text,
        "parse_warning": "DeepSeek 返回内容不是严格 JSON，已保留 raw_text。",
    }


def _call_deepseek_json(system_prompt: str, user_payload: dict[str, Any]) -> dict[str, Any]:
    api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("AI_VIDEO_DEEPSEEK_API_KEY") or ""
    cfg = _deepseek_config()

    if not api_key:
        raise ValueError("DEEPSEEK_API_KEY 未配置。请在 systemd 环境里配置后再把 dry_run=false。")

    url = f'{cfg["base_url"]}/chat/completions'

    body = {
        "model": cfg["model"],
        "temperature": 0.35,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": json.dumps(user_payload, ensure_ascii=False),
            },
        ],
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=cfg["timeout"]) as resp:
        raw = resp.read().decode("utf-8", errors="replace")

    data = json.loads(raw)
    content = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "")

    parsed = _extract_json(content)
    parsed["_llm_usage"] = data.get("usage") or {}
    parsed["_llm_model"] = cfg["model"]

    return parsed


def _dry_comment_enhance(lead: dict[str, Any], campaign_context: dict[str, Any]) -> dict[str, Any]:
    text = _clean(lead.get("text"))
    intents = lead.get("intents") or []

    market = _clean(campaign_context.get("market") or "马来西亚")

    if "contact_intent" in intents:
        reply = f"可以，我建议先看你的预算、用途和目标区域。{market}不同区域差异很大，你更偏自住还是投资？"
        stage = "hot_lead"
    elif "investment_intent" in intents:
        reply = "投资不能只看表面租金回报，还要看租客来源、空置风险和未来转手难度。你更关注稳定出租还是升值？"
        stage = "investment_research"
    elif "objection_or_pain" in intents:
        reply = "这个担心很正常。海外买房最怕只看宣传图，建议先核验开发商、产权、贷款条件和真实周边配套。你最担心哪一块？"
        stage = "risk_concern"
    else:
        reply = f"这个问题要结合预算、用途和区域看。{market}不同区域逻辑不一样，你是自住、投资还是资产配置？"
        stage = "early_interest"

    return {
        "lead_id": lead.get("lead_id"),
        "priority": lead.get("priority"),
        "lead_score": lead.get("lead_score"),
        "original_text": text,
        "buyer_stage": stage,
        "pain_point": _infer_pain_point(intents),
        "public_reply": reply,
        "private_followup": "可以先问对方预算、用途、目标区域、计划入手时间，不要直接硬推楼盘。",
        "follow_up_question": "你现在主要是自住、投资，还是给家人做资产配置？",
        "risk_note": "具体房源、价格、户型、周边配套必须以官方/真实资料为准。",
        "script_hook": lead.get("script_hook") or "评论区问得最多的问题，其实暴露了很多买房误区。",
        "llm_mode": "dry_run_rule_fallback",
    }


def _infer_pain_point(intents: list[str]) -> str:
    if "investment_intent" in intents:
        return "关注租金回报、出租稳定性和未来转手。"
    if "location_interest" in intents:
        return "纠结区域选择，不确定哪里适合自住或投资。"
    if "objection_or_pain" in intents:
        return "担心踩坑、风险、信息不透明。"
    if "contact_intent" in intents:
        return "已经有主动咨询意愿，需要人工筛选预算和用途。"
    return "泛兴趣，需要继续筛选真实需求。"


def _dry_content_enhance(insight: dict[str, Any], campaign_context: dict[str, Any]) -> dict[str, Any]:
    market = _clean(campaign_context.get("market") or "马来西亚")
    title = _clean(insight.get("title"))
    angle = _clean(insight.get("topic_angle"))

    hook = insight.get("script_hook") or f"第一次看{market}房产，别急着问价格，先看这三个点。"

    outline = [
        "开头用一句反常识观点抓住注意力。",
        "指出普通买家最容易犯的判断错误。",
        "拆三个判断标准：区域、租金/自住需求、未来转手。",
        "最后用评论区问题做截流，不直接硬广。",
    ]

    return {
        "insight_id": insight.get("insight_id"),
        "priority": insight.get("priority"),
        "score": insight.get("score"),
        "title": title,
        "topic_angle": angle,
        "originality_angle": f"不照抄同行标题，而是从{angle or '买房决策'}切入，改成适合{market}房产获客的原创脚本。",
        "opening_hook": hook,
        "script_outline": outline,
        "timeline_text": " ".join([
            hook,
            "买海外房产不能只看价格和宣传图。",
            "第一，看区域真实需求，决定未来出租和生活便利。",
            "第二，看周边配套是不是已经成熟，不要只听未来规划。",
            "第三，看转手难度，很多人踩坑不是因为房子不好，而是买错了区域。",
            "你现在是自住还是投资？评论区打出来。",
        ]),
        "scene_notes": [
            "开头：城市/楼盘外观或看房动作。",
            "区域：地图、交通、商圈、学校等真实素材。",
            "风险：对比画面、慢镜头、重点字幕。",
            "结尾：评论区引导字幕。",
        ],
        "material_need": [
            "真实楼盘外观",
            "真实周边配套",
            "区域地图或通勤画面",
            "通用投资/生活方式 B-roll",
        ],
        "comment_capture": insight.get("comment_capture_angle") or "你现在是自住、投资还是资产配置？评论区打出来。",
        "shot_hint": insight.get("shot_hint") or "opening_hook",
        "llm_mode": "dry_run_rule_fallback",
    }


def _comment_system_prompt() -> str:
    return """
你是一个海外房产短视频评论区线索分析助手。
你只能分析用户公开评论，不能鼓励自动私信、骚扰、批量评论或绕平台风控。
请输出严格 JSON，不要 Markdown。

目标：
1. 判断评论是否是真实买房/投资线索。
2. 识别痛点：预算、区域、投资回报、贷款、怕踩坑、转手、租金。
3. 生成自然、克制、像真人的公开回复。
4. 生成人工跟进问题。
5. 给出可转成短视频脚本的 hook。

JSON 字段：
buyer_stage, pain_point, public_reply, private_followup, follow_up_question, risk_note, script_hook
要求：
- 不要承诺收益。
- 不要编造楼盘、价格、户型、周边。
- 回复不能像硬广。
- 公共回复要短，适合评论区。
""".strip()


def _content_system_prompt() -> str:
    return """
你是海外房产短视频选题和脚本策略助手。
输入是 OpenClaw 从同行视频/帖子导出的高分内容。
你不能照抄原文，要输出原创角度。
请输出严格 JSON，不要 Markdown。

目标：
1. 拆解爆点。
2. 改成原创短视频脚本方向。
3. 生成开头 hook。
4. 生成分段脚本大纲。
5. 生成镜头和素材需求。
6. 生成评论区截流问题。

JSON 字段：
originality_angle, opening_hook, script_outline, timeline_text, scene_notes, material_need, comment_capture, shot_hint
要求：
- 房产真实信息不能瞎编。
- 不要承诺投资收益。
- 适合中文口播短视频。
- 旁白要自然，便于后续 TTS。
""".strip()


def enhance_comments(
    comments: list[Any] | None = None,
    raw_export: Any = None,
    campaign_context: dict[str, Any] | None = None,
    min_score: int = 55,
    max_llm_items: int = 5,
    dry_run: bool = True,
    save_rule_leads: bool = False,
) -> dict[str, Any]:
    campaign_context = campaign_context or {}

    if raw_export is not None:
        rule_result = analyze_openclaw_comments(
            raw_export=raw_export,
            comments=comments or [],
            campaign_context=campaign_context,
            save=save_rule_leads,
            max_items=200,
        )
        leads = ((rule_result.get("analysis") or {}).get("leads") or [])
    else:
        rule_result = analyze_comments(
            comments=comments or [],
            campaign_context=campaign_context,
            save=save_rule_leads,
            max_items=200,
        )
        leads = rule_result.get("leads") or []

    selected = [
        x for x in leads
        if int(x.get("lead_score") or 0) >= int(min_score or 0)
    ][: max(1, min(int(max_llm_items or 5), 20))]

    enhanced = []
    for lead in selected:
        if dry_run:
            item = _dry_comment_enhance(lead, campaign_context)
        else:
            item = _call_deepseek_json(
                _comment_system_prompt(),
                {
                    "campaign_context": campaign_context,
                    "lead": lead,
                },
            )
            item.update(
                {
                    "lead_id": lead.get("lead_id"),
                    "priority": lead.get("priority"),
                    "lead_score": lead.get("lead_score"),
                    "original_text": lead.get("text"),
                    "llm_mode": "deepseek",
                }
            )

        enhanced.append(item)

    return {
        "ok": True,
        "provider": PROVIDER,
        "target": "comments",
        "dry_run": dry_run,
        "llm_provider": "deepseek",
        "llm_config": _deepseek_config(),
        "rule_lead_count": len(leads),
        "selected_count": len(selected),
        "min_score": min_score,
        "enhanced_leads": enhanced,
        "rule_result_summary": {
            "provider": rule_result.get("provider"),
            "status": rule_result.get("status"),
            "lead_count": rule_result.get("lead_count") or (rule_result.get("analysis") or {}).get("lead_count"),
            "a_priority_count": rule_result.get("a_priority_count") or (rule_result.get("analysis") or {}).get("a_priority_count"),
            "b_priority_count": rule_result.get("b_priority_count") or (rule_result.get("analysis") or {}).get("b_priority_count"),
        },
        "message": "评论区 DeepSeek 增强完成：规则先筛选，DeepSeek 只处理高分线索。dry_run=true 时不调用模型。",
    }


def enhance_content(
    raw_export: Any = None,
    items: list[Any] | None = None,
    campaign_context: dict[str, Any] | None = None,
    min_score: int = 55,
    max_llm_items: int = 5,
    dry_run: bool = True,
    save_rule_insights: bool = False,
) -> dict[str, Any]:
    campaign_context = campaign_context or {}

    rule_result = analyze_content(
        raw_export=raw_export,
        items=items or [],
        campaign_context=campaign_context,
        save=save_rule_insights,
        max_items=300,
    )

    insights = rule_result.get("insights") or []
    selected = [
        x for x in insights
        if int(x.get("score") or 0) >= int(min_score or 0)
    ][: max(1, min(int(max_llm_items or 5), 20))]

    enhanced = []
    for insight in selected:
        if dry_run:
            item = _dry_content_enhance(insight, campaign_context)
        else:
            item = _call_deepseek_json(
                _content_system_prompt(),
                {
                    "campaign_context": campaign_context,
                    "insight": insight,
                },
            )
            item.update(
                {
                    "insight_id": insight.get("insight_id"),
                    "priority": insight.get("priority"),
                    "score": insight.get("score"),
                    "title": insight.get("title"),
                    "topic_angle": insight.get("topic_angle"),
                    "llm_mode": "deepseek",
                }
            )

        enhanced.append(item)

    return {
        "ok": True,
        "provider": PROVIDER,
        "target": "content",
        "dry_run": dry_run,
        "llm_provider": "deepseek",
        "llm_config": _deepseek_config(),
        "rule_insight_count": len(insights),
        "selected_count": len(selected),
        "min_score": min_score,
        "enhanced_insights": enhanced,
        "rule_result_summary": {
            "provider": rule_result.get("provider"),
            "status": rule_result.get("status"),
            "count": rule_result.get("count"),
            "a_priority_count": rule_result.get("a_priority_count"),
            "b_priority_count": rule_result.get("b_priority_count"),
        },
        "message": "OpenClaw 内容 DeepSeek 增强完成：规则先筛选，DeepSeek 只处理高分选题。dry_run=true 时不调用模型。",
    }


def health() -> dict[str, Any]:
    cfg = _deepseek_config()
    return {
        "ok": True,
        "provider": PROVIDER,
        "llm_provider": "deepseek",
        "deepseek_configured": cfg["configured"],
        "deepseek_base_url": cfg["base_url"],
        "deepseek_model": cfg["model"],
        "message": "OpenClaw LLM Enhance 可用：默认接 DeepSeek。dry_run=true 不调用模型；dry_run=false 才会真实调用 DeepSeek。",
        "features": [
            "rule_first_llm_second",
            "comment_lead_enhance",
            "content_topic_enhance",
            "deepseek_openai_compatible_chat_completions",
            "no_auto_scrape_no_auto_dm_no_auto_comment",
        ],
    }


def self_test() -> dict[str, Any]:
    content_csv = """author,title,likes,comments,shares,views,platform,url
agent_a,马来西亚买房千万别只看价格，这三个区域最容易踩坑,1200,88,42,56000,tiktok,https://example.com/v1
agent_b,海外房产投资租金回报到底怎么算？很多人第一步就错了,850,66,25,43000,tiktok,https://example.com/v2
"""

    comment_items = [
        {
            "platform": "tiktok",
            "author": "lead_a",
            "text": "马来西亚买房首付大概要多少？哪个区域比较适合投资出租？",
            "like_count": 18,
            "reply_count": 3,
        },
        {
            "platform": "tiktok",
            "author": "lead_b",
            "text": "可以私信我吗？想了解预算和贷款。",
            "like_count": 5,
            "reply_count": 2,
        },
    ]

    return {
        "ok": True,
        "provider": PROVIDER,
        "comments_test": enhance_comments(
            comments=comment_items,
            campaign_context={"market": "马来西亚", "platform": "tiktok"},
            dry_run=True,
            min_score=40,
        ),
        "content_test": enhance_content(
            raw_export=content_csv,
            campaign_context={"market": "马来西亚", "platform": "tiktok"},
            dry_run=True,
            min_score=40,
        ),
    }
