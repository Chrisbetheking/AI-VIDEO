from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict

import requests
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.config import get_settings
from app.services.memory import MemoryStore
from app.services.script_dedup_v10_40_8_36 import (
    VERSION as SCRIPT_DEDUP_VERSION,
    ScriptDedupEngine,
    build_rewrite_feedback,
    persist_script_record,
)

router = APIRouter(prefix="/api/video/full-ai/script-ai", tags=["full-ai-script-ai"])


class FullAIScriptPlanRequest(BaseModel):
    market: str = "马来西亚"
    platform: str = "douyin"
    topic: str = "马来西亚买房，别只看价格"
    duration_seconds: int = 28
    target_customer: str = "海外房产潜在客户"
    industry_notes: str = ""
    competitor_notes: str = ""
    lead_notes: str = ""
    style: str = "短、狠、直接、口语化、有转化"
    dry_run: bool = False
    dedup_enabled: bool = True
    dedup_auto_rewrite: bool = True
    dedup_max_rewrites: int = Field(default=2, ge=0, le=3)
    force_new_angle: bool = False
    requested_angle: str = ""
    requested_structure: str = ""
    save_history: bool = True


def _deepseek_config() -> Dict[str, Any]:
    return {
        "api_key": os.getenv("DEEPSEEK_API_KEY") or os.getenv("AI_VIDEO_DEEPSEEK_API_KEY") or "",
        "base_url": (os.getenv("DEEPSEEK_BASE_URL") or os.getenv("AI_VIDEO_DEEPSEEK_BASE_URL") or "https://api.deepseek.com").rstrip("/"),
        "model": os.getenv("DEEPSEEK_MODEL") or os.getenv("AI_VIDEO_DEEPSEEK_MODEL") or "deepseek-chat",
        "timeout": float(os.getenv("DEEPSEEK_TIMEOUT") or os.getenv("AI_VIDEO_DEEPSEEK_TIMEOUT") or 45),
    }


def _segment_count(duration: int) -> int:
    return max(3, min(18, round(duration / 4)))


def _fallback(req: FullAIScriptPlanRequest, brief: dict[str, Any]) -> Dict[str, Any]:
    n = _segment_count(req.duration_seconds)
    angle = str(brief.get("recommended_angle") or "数据核验")
    structure = str(brief.get("recommended_structure") or "一分钟审计")
    fallback_by_angle = {
        "持有成本": [
            f"买{req.market}房产，成交价只是第一张账单。",
            "物业费、税费、维修和空置期，才决定你每年真正要掏多少钱。",
            "把一次性费用和长期费用分开算，再看现金流能不能承受。",
            "资料不完整时不要猜数字，直接列出必须向顾问和律师核验的项目。",
            "先算持有成本，再谈这套房适不适合你。",
        ],
        "合同付款": [
            f"同一个{req.market}项目，付款节点不同，资金压力可能完全不同。",
            "先看定金、签约、施工和交付分别什么时候付款。",
            "再确认退款条件、违约责任和律师审查范围。",
            "看不懂的条款不要靠口头承诺，必须留书面证据。",
            "把付款计划发出来，比只问总价更有用。",
        ],
        "户型实用": [
            "样板间看起来大，不等于实际住起来顺手。",
            "先看动线、采光、收纳和家具摆放，再看宣传面积。",
            "自住要模拟一家人的日常，出租要模拟租客的真实使用。",
            "户型图和现场尺寸不一致时，以正式资料和实测为准。",
            "买房前，先把一天怎么住走一遍。",
        ],
        "客户案例": [
            "上周有位客户预算没问题，却差点选错了房。",
            "他一直比较总价，却没算通勤、持有成本和未来转售。",
            "我们把需求重新排了一遍，才发现真正优先的是家庭居住。",
            "案例不是让你照抄答案，而是看清自己的排序。",
            "先说你的真实需求，再谈项目。",
        ],
    }
    base = fallback_by_angle.get(angle) or [
        f"这次不聊{req.topic}的老套路，直接做一遍{structure}。",
        f"先把主问题锁定在{angle}，不要同时堆价格、区域和用途。",
        "每个判断都要对应一条可核验的信息，而不是销售话术。",
        "资料不足的地方明确标记待确认，不编造具体数字和项目。",
        "做完这一轮判断，再决定要不要继续看房。",
    ]
    while len(base) < n:
        base.insert(-1, "每个结论都要能追溯到正式资料或现场观察。")
    segments = base[:n]
    return {
        "ok": True,
        "provider": "local_fallback_v36",
        "title": req.topic,
        "hook": segments[0],
        "script": "\n".join(segments),
        "segments": [
            {
                "index": i + 1,
                "text": text,
                "duration": round(req.duration_seconds / len(segments), 1),
                "visual_type": "consultation" if i in {0, len(segments) - 1} else "document_check",
                "edit": "按语义切镜，不按固定秒数",
            }
            for i, text in enumerate(segments)
        ],
        "industry_angle": angle,
        "structure": structure,
        "cta": segments[-1],
        "visual_rules": {
            "aspect_ratio": "9:16",
            "no_ai_text": True,
            "generic_broll_only": True,
        },
    }


def _extract_json(text: str) -> Dict[str, Any]:
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise ValueError("DeepSeek 未返回 JSON")
    return json.loads(match.group(0))


def _call_deepseek(
    req: FullAIScriptPlanRequest,
    brief: dict[str, Any],
    rewrite_feedback: dict[str, Any] | None = None,
    *,
    attempt: int = 1,
) -> Dict[str, Any]:
    cfg = _deepseek_config()
    if not cfg["api_key"]:
        raise RuntimeError("DeepSeek API Key 未配置")

    seg_count = _segment_count(req.duration_seconds)
    system = """你是短视频获客编导，服务海外房产/本地生活线索转化。
必须输出严格 JSON，不要 Markdown。
原则：
1. 文案像真人口播，但不能反复套用“别只看价格→自住投资→租客来源→评论区留言”；
2. 每次生成都要参考历史查重冷却，不能只做同义词替换；
3. 不承诺收益率，不编造楼盘、户型、价格、学校、交通、周边；
4. 视频画面不让 AI 生成任何文字，字幕由后端烧录；
5. 镜头按语义密度规划，不使用固定 3 秒/4 秒机械切镜。"""

    user = f"""
市场：{req.market}
平台：{req.platform}
主题：{req.topic}
目标客户：{req.target_customer}
目标时长：{req.duration_seconds} 秒
建议段数：{seg_count}
风格：{req.style}

本次必须优先采用的新角度：{brief.get('recommended_angle')}
本次必须优先采用的新结构：{brief.get('recommended_structure')}
最近角度冷却：{json.dumps(brief.get('recent_angles') or [], ensure_ascii=False)}
最近结构冷却：{json.dumps(brief.get('recent_structures') or [], ensure_ascii=False)}
禁止复用句式：{json.dumps(brief.get('avoid_phrases') or [], ensure_ascii=False)}

行业爆点/学习笔记：
{req.industry_notes or "海外房产真实成本、流程、合同、户型、交付、物业、家庭需求与数据核验。"}

竞品打法：
{req.competitor_notes or "只借鉴信息密度，不复制同行标题、钩子、结构和CTA。"}

评论区/获客线索：
{req.lead_notes or "根据客户真实问题选择一个窄角度，不要把所有问题塞进一条视频。"}

第 {attempt} 次生成。上轮查重反馈：
{json.dumps(rewrite_feedback or {}, ensure_ascii=False)}

请输出 JSON：
{{
  "title": "标题",
  "hook": "前三秒钩子",
  "industry_angle": "本次唯一主角度",
  "structure": "采用的结构",
  "script": "完整口播，按换行分段",
  "segments": [{{"index": 1, "text": "口播段落", "duration": 4, "visual_type": "document_check", "edit": "剪辑建议"}}],
  "cta": "与历史不同的收尾引导",
  "risk_note": "合规提醒",
  "visual_rules": {{"aspect_ratio": "9:16", "no_ai_text": true, "generic_broll_only": true}}
}}
"""

    response = requests.post(
        f"{cfg['base_url']}/chat/completions",
        headers={"Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json"},
        json={
            "model": cfg["model"],
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": min(1.05, 0.76 + (attempt - 1) * 0.1),
            "response_format": {"type": "json_object"},
        },
        timeout=cfg["timeout"],
    )
    response.raise_for_status()
    data = response.json()
    parsed = _extract_json(data["choices"][0]["message"]["content"])
    parsed["ok"] = True
    parsed["provider"] = "deepseek_v36"
    parsed["_llm_model"] = cfg["model"]
    parsed["_usage"] = data.get("usage")
    return parsed


@router.get("/health")
def health():
    cfg = _deepseek_config()
    return {
        "ok": True,
        "provider": "full_ai_script_ai_v36",
        "script_dedup_version": SCRIPT_DEDUP_VERSION,
        "deepseek_configured": bool(cfg["api_key"]),
        "model": cfg["model"],
        "features": {
            "persistent_script_history": True,
            "automatic_similarity_rewrite": True,
            "angle_structure_cooldown": True,
            "hard_block_over_82": True,
        },
    }


@router.post("/plan")
def plan(req: FullAIScriptPlanRequest):
    started = time.time()
    settings = get_settings()
    memory = MemoryStore(settings)
    dedup = ScriptDedupEngine(settings)
    dedup.backfill_from_memory(memory)
    brief = dedup.generation_brief(
        topic=req.topic,
        requested_angle=req.requested_angle,
        requested_structure=req.requested_structure,
        force_new_angle=req.force_new_angle,
    )

    if req.dry_run:
        out = _fallback(req, brief)
        report = dedup.analyze(
            script=str(out.get("script") or ""),
            topic=req.topic,
            title=str(out.get("title") or ""),
            hook=str(out.get("hook") or ""),
            cta=str(out.get("cta") or ""),
        )
        out.update({"dry_run": True, "dedup_report": report, "dedup_brief": brief})
        out["elapsed_seconds"] = round(time.time() - started, 2)
        return out

    attempts: list[dict[str, Any]] = []
    max_attempts = 1 + (int(req.dedup_max_rewrites) if req.dedup_enabled and req.dedup_auto_rewrite else 0)
    out: dict[str, Any] = {}
    report: dict[str, Any] = {}
    feedback: dict[str, Any] | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            out = _call_deepseek(req, brief, feedback, attempt=attempt)
        except Exception as exc:
            out = _fallback(req, brief)
            out["provider"] = "local_fallback_after_deepseek_error_v36"
            out["deepseek_error"] = str(exc)
        script = str(out.get("script") or "").strip()
        segments = out.get("segments") if isinstance(out.get("segments"), list) else []
        hook = str(out.get("hook") or (segments[0].get("text") if segments and isinstance(segments[0], dict) else ""))
        cta = str(out.get("cta") or (segments[-1].get("text") if segments and isinstance(segments[-1], dict) else ""))
        report = dedup.analyze(
            script=script,
            topic=req.topic,
            title=str(out.get("title") or req.topic),
            hook=hook,
            cta=cta,
        ) if req.dedup_enabled else {"decision": "pass", "rewrite_required": False, "originality_score": 100, "similarity_score": 0}
        if not report.get("rewrite_required"):
            break
        feedback = build_rewrite_feedback(report, brief)
        attempts.append({"attempt": attempt, "decision": report.get("decision"), "similarity_score": report.get("similarity_score"), "rewrite_feedback": feedback})
        if req.save_history:
            persist_script_record(settings, memory, {
                "title": out.get("title") or req.topic,
                "topic": req.topic,
                "hook": hook,
                "script": script,
                "cta": cta,
                "source": "full_ai_script_rejected_attempt",
                "status": "rejected_similarity",
                "force_new_record": True,
                "metadata": {"attempt": attempt},
            }, report=report)

    if report.get("rewrite_required"):
        # Do not silently feed a duplicated or synonym-rewritten script into TTS/video. Return a
        # structured blocked result so the frontend can keep the user in script step.
        return {
            "ok": False,
            "provider": out.get("provider") or "full_ai_script_ai_v36",
            "status": "blocked_by_script_dedup",
            "message": "文案与历史内容仍然相似，自动换角度后未达到通过线。",
            "script": "",
            "segments": [],
            "dedup_report": report,
            "dedup_attempts": attempts,
            "dedup_brief": brief,
            "elapsed_seconds": round(time.time() - started, 2),
        }

    out["dedup_report"] = report
    out["dedup_attempts"] = attempts
    out["dedup_brief"] = brief
    out["script_dedup_version"] = SCRIPT_DEDUP_VERSION
    if req.save_history:
        out["script_history_record"] = persist_script_record(settings, memory, {
            "title": out.get("title") or req.topic,
            "topic": req.topic,
            "hook": out.get("hook") or "",
            "script": out.get("script") or "",
            "cta": out.get("cta") or "",
            "angle": out.get("industry_angle") or report.get("angle") or brief.get("recommended_angle"),
            "structure": out.get("structure") or report.get("structure") or brief.get("recommended_structure"),
            "source": "full_ai_script_plan",
            "status": "generated_warn" if report.get("decision") in {"warn", "rewrite"} else "generated_pass",
            "metadata": {"attempts": attempts, "brief": brief},
        }, report=report)
    out["elapsed_seconds"] = round(time.time() - started, 2)
    return out
