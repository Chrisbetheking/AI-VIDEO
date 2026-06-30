from __future__ import annotations

import uuid
from typing import Any

from app.services.openclaw_content_intel_provider import analyze_content
from app.services.timeline_engine_provider import build_timeline


DEFAULT_BGM_POLICY = {
    "enabled": True,
    "music_type": "instrumental_only",
    "avoid": [
        "明显人声",
        "歌词密集",
        "音量过大",
        "强鼓点压过旁白",
        "版权不明音乐",
    ],
    "preferred": [
        "轻氛围",
        "轻节奏",
        "无歌词",
        "低存在感",
        "适合房地产/生活方式",
    ],
    "voice_first": True,
    "default_bgm_volume": 0.12,
    "ducking_when_voice": True,
    "ducked_bgm_volume": 0.06,
    "note": "旁白永远优先，BGM 只做氛围，不允许抢人声。",
}


DEFAULT_QUALITY_POLICY = {
    "enabled": True,
    "output_profile": "vertical_720x1280",
    "fps": 30,
    "enhance_steps": [
        "统一分辨率",
        "统一帧率",
        "轻度锐化",
        "轻度降噪",
        "亮度/对比度微调",
        "避免过度磨皮或失真",
    ],
    "real_estate_truth_rule": "楼盘、户型、周边真实画面不能被 AI 改到失真，只允许轻度画质增强。",
}


def _clean_text(text: Any) -> str:
    return " ".join(str(text or "").strip().split())


def _choose_best_insight(insights: list[dict[str, Any]], min_score: int = 0) -> dict[str, Any]:
    candidates = [x for x in insights if int(x.get("score") or 0) >= min_score]
    if not candidates:
        candidates = insights

    if not candidates:
        raise ValueError("没有可用 insight。请先传入 OpenClaw 内容数据。")

    candidates.sort(key=lambda x: int(x.get("score") or 0), reverse=True)
    return candidates[0]


def _script_from_insight(insight: dict[str, Any], campaign_context: dict[str, Any] | None = None) -> dict[str, Any]:
    campaign_context = campaign_context or {}

    market = _clean_text(campaign_context.get("market") or "马来西亚")
    project = _clean_text(campaign_context.get("project") or "")
    audience = _clean_text(campaign_context.get("audience") or "准备买海外房产的人")

    title = _clean_text(insight.get("title"))
    angle = _clean_text(insight.get("topic_angle"))
    hook = _clean_text(insight.get("script_hook"))
    capture = _clean_text(insight.get("comment_capture_angle"))

    if not hook:
        hook = "第一次买海外房产，别急着问价格，先把这三个问题想清楚。"

    project_line = f"如果你正在看 {project}，" if project else f"如果你正在看{market}房产，"

    body_parts = [
        hook,
        f"{project_line}不要只看宣传图和总价。",
        "第一，看这个区域真实租客是谁，决定出租稳定性。",
        "第二，看周边配套是不是已经成熟，不要只听未来规划。",
        "第三，看未来转手难度，很多人踩坑不是房子不好，而是买错了区域。",
        capture or "你现在是自住、投资还是资产配置？评论区打出来。",
    ]

    script_text = " ".join(x for x in body_parts if x)

    return {
        "title": title or hook,
        "audience": audience,
        "market": market,
        "project": project,
        "topic_angle": angle,
        "script_hook": hook,
        "comment_capture_angle": capture,
        "script_text": script_text,
        "structure": [
            {"part": "opening_hook", "text": hook},
            {"part": "problem", "text": f"{project_line}不要只看宣传图和总价。"},
            {"part": "point_1", "text": "第一，看这个区域真实租客是谁，决定出租稳定性。"},
            {"part": "point_2", "text": "第二，看周边配套是不是已经成熟，不要只听未来规划。"},
            {"part": "point_3", "text": "第三，看未来转手难度，很多人踩坑不是房子不好，而是买错了区域。"},
            {"part": "comment_capture", "text": capture or "你现在是自住、投资还是资产配置？评论区打出来。"},
        ],
    }


def _shot_brief_from_timeline(timeline: dict[str, Any], insight: dict[str, Any]) -> list[dict[str, Any]]:
    segments = timeline.get("segments") or []
    base_shot_hint = insight.get("shot_hint") or "opening_hook"

    out: list[dict[str, Any]] = []
    for seg in segments:
        index = int(seg.get("index") or 0)
        text = seg.get("text") or ""

        if index == 0:
            shot_type = "opening_hook"
            material_need = "强钩子画面：城市/楼盘外观/人物看房动作"
        elif "第一" in text:
            shot_type = "tenant_or_location"
            material_need = "区域配套、租客生活场景、交通/商圈"
        elif "第二" in text:
            shot_type = "surrounding_facilities"
            material_need = "学校、商场、交通、实景周边"
        elif "第三" in text:
            shot_type = "risk_or_resale"
            material_need = "对比画面、地图、真实楼盘细节"
        else:
            shot_type = base_shot_hint
            material_need = "与文案语义匹配的真实素材或低风险通用素材"

        out.append(
            {
                "segment_index": index,
                "start": seg.get("start"),
                "end": seg.get("end"),
                "duration": seg.get("duration"),
                "text": text,
                "shot_type": shot_type,
                "material_need": material_need,
                "source_rule": "真实楼盘/户型/周边必须使用真实素材；AI 只允许补充通用氛围镜头。",
            }
        )

    return out


def build_openclaw_timeline_plan(
    raw_export: Any = None,
    items: list[Any] | None = None,
    campaign_context: dict[str, Any] | None = None,
    save_insight: bool = False,
    target_duration: float | None = 28,
    min_score: int = 0,
    max_items: int = 300,
    bgm_policy: dict[str, Any] | None = None,
    quality_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    campaign_context = campaign_context or {}

    content_result = analyze_content(
        raw_export=raw_export,
        items=items or [],
        campaign_context=campaign_context,
        save=save_insight,
        max_items=max_items,
    )

    insights = content_result.get("insights") or []
    best = _choose_best_insight(insights, min_score=min_score)

    script = _script_from_insight(best, campaign_context=campaign_context)

    timeline = build_timeline(
        text=script["script_text"],
        target_duration=target_duration,
        speech_rate_cps=4.2,
        min_segment_duration=2.2,
        max_segment_duration=6.5,
    )

    shot_brief = _shot_brief_from_timeline(timeline, best)

    final_bgm_policy = dict(DEFAULT_BGM_POLICY)
    if bgm_policy:
        final_bgm_policy.update(bgm_policy)

    final_quality_policy = dict(DEFAULT_QUALITY_POLICY)
    if quality_policy:
        final_quality_policy.update(quality_policy)

    bridge_id = f"openclaw_timeline_{uuid.uuid4().hex[:18]}"

    return {
        "ok": True,
        "provider": "openclaw_to_timeline_bridge_v1",
        "bridge_id": bridge_id,
        "status": "planned",
        "dry_run": True,
        "selected_insight": {
            "title": best.get("title"),
            "score": best.get("score"),
            "priority": best.get("priority"),
            "topic_angle": best.get("topic_angle"),
            "content_type": best.get("content_type"),
            "tags": best.get("tags"),
            "shot_hint": best.get("shot_hint"),
            "source_url": best.get("source_url"),
        },
        "script": script,
        "timeline": timeline,
        "shot_brief": shot_brief,
        "bgm_policy": final_bgm_policy,
        "quality_policy": final_quality_policy,
        "next_payloads": {
            "tts_align": {
                "endpoint": "/api/video/timeline/tts-align",
                "payload": {
                    "text": script["script_text"],
                    "target_duration": target_duration,
                    "dry_run": True,
                },
            },
            "render_plan": {
                "endpoint": "/api/video/timeline/render-plan",
                "payload_note": "真实 TTS 返回 segments/audio_url 后，再填入 render-plan。",
            },
        },
        "message": "OpenClaw 高分选题已转成脚本、Timeline、镜头需求、BGM 规则和画质增强规则。未调用 TTS、未调用 fal.ai、未合成视频。",
    }


def health() -> dict[str, Any]:
    return {
        "ok": True,
        "provider": "openclaw_to_timeline_bridge_v1",
        "message": "OpenClaw → Timeline 桥接可用：把同行内容洞察转成脚本、时间轴、镜头需求、BGM 规则和画质规则。",
        "features": [
            "select_best_openclaw_insight",
            "script_generation",
            "timeline_generation",
            "shot_brief",
            "bgm_policy",
            "quality_policy",
            "no_fal_no_tts_no_render_by_default",
        ],
    }


def self_test() -> dict[str, Any]:
    csv_text = """author,title,likes,comments,shares,views,platform,url
agent_a,马来西亚买房千万别只看价格，这三个区域最容易踩坑,1200,88,42,56000,tiktok,https://example.com/v1
agent_b,海外房产投资租金回报到底怎么算？很多人第一步就错了,850,66,25,43000,tiktok,https://example.com/v2
"""
    return build_openclaw_timeline_plan(
        raw_export=csv_text,
        campaign_context={
            "market": "马来西亚",
            "platform": "tiktok",
            "audience": "准备在马来西亚买房或投资的人",
        },
        save_insight=False,
        target_duration=28,
    )
