from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict, List

import requests
from fastapi import APIRouter
from pydantic import BaseModel, Field

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


def _deepseek_config() -> Dict[str, Any]:
    return {
        "api_key": os.getenv("DEEPSEEK_API_KEY") or os.getenv("AI_VIDEO_DEEPSEEK_API_KEY") or "",
        "base_url": (os.getenv("DEEPSEEK_BASE_URL") or os.getenv("AI_VIDEO_DEEPSEEK_BASE_URL") or "https://api.deepseek.com").rstrip("/"),
        "model": os.getenv("DEEPSEEK_MODEL") or os.getenv("AI_VIDEO_DEEPSEEK_MODEL") or "deepseek-chat",
        "timeout": float(os.getenv("DEEPSEEK_TIMEOUT") or os.getenv("AI_VIDEO_DEEPSEEK_TIMEOUT") or 45),
    }


def _segment_count(duration: int) -> int:
    return max(3, min(18, round(duration / 4)))


def _fallback(req: FullAIScriptPlanRequest) -> Dict[str, Any]:
    n = _segment_count(req.duration_seconds)
    base = [
        f"{req.topic}，别一上来就只问价格。",
        "先看预算和用途，自住、出租、第二居所，判断标准完全不一样。",
        "再看区域和租客来源，别被单一项目话术带着走。",
        "户型、价格、交付和周边，最终都要回到官方资料和实地核验。",
        "想少踩坑，先把预算、城市和用途讲清楚，再匹配项目。",
    ]
    while len(base) < n:
        base.insert(-1, "同样预算，买错区域，后面的出租和转手都会很被动。")
    segments = base[:n]
    return {
        "ok": True,
        "provider": "local_fallback",
        "title": req.topic,
        "hook": segments[0],
        "script": "\n".join(segments),
        "segments": [
            {
                "index": i + 1,
                "text": text,
                "duration": round(req.duration_seconds / len(segments), 1),
                "visual_type": "generic_real_estate_broll",
                "edit": "快切+字幕加粗" if i == 0 else "按语义切镜",
            }
            for i, text in enumerate(segments)
        ],
        "industry_angle": "预算/区域/用途/核验",
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

    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        raise ValueError("DeepSeek 未返回 JSON")
    return json.loads(m.group(0))


def _call_deepseek(req: FullAIScriptPlanRequest) -> Dict[str, Any]:
    cfg = _deepseek_config()
    if not cfg["api_key"]:
        raise RuntimeError("DeepSeek API Key 未配置")

    seg_count = _segment_count(req.duration_seconds)

    system = """你是短视频获客编导，服务海外房产/本地生活线索转化。
必须输出严格 JSON，不要 Markdown。
原则：
1. 文案短、狠、直接、像抖音口播；
2. 结合行业爆点、竞品打法、评论区问题和客户转化；
3. 不承诺收益率，不编造楼盘、户型、价格、学校、交通、周边；
4. 视频画面不让 AI 生成任何文字，字幕由后端烧录；
5. 输出适合 9:16 短视频的分段文稿和镜头建议。"""

    user = f"""
市场：{req.market}
平台：{req.platform}
主题：{req.topic}
目标客户：{req.target_customer}
目标时长：{req.duration_seconds} 秒
建议段数：{seg_count}
风格：{req.style}

行业爆点/学习笔记：
{req.industry_notes or "海外房产避坑、预算、区域、用途、租客来源、核验资料、家庭资产配置、第二家园。"}

竞品打法：
{req.competitor_notes or "同行常用痛点标题、反差开头、评论区预算/区域/首付问题承接。"}

评论区/获客线索：
{req.lead_notes or "首付多少、哪个区域适合出租、预算怎么判断、能否私信咨询。"}

请输出 JSON：
{{
  "title": "标题",
  "hook": "前三秒钩子",
  "industry_angle": "行业爆点角度",
  "script": "完整口播，按换行分段",
  "segments": [
    {{
      "index": 1,
      "text": "口播段落",
      "duration": 4,
      "visual_type": "generic_city_broll / document_check / condo_exterior / lifestyle / consultation",
      "edit": "剪辑建议"
    }}
  ],
  "cta": "收尾引导",
  "risk_note": "合规提醒",
  "visual_rules": {{
    "aspect_ratio": "9:16",
    "no_ai_text": true,
    "generic_broll_only": true
  }}
}}
"""

    res = requests.post(
        f"{cfg['base_url']}/chat/completions",
        headers={
            "Authorization": f"Bearer {cfg['api_key']}",
            "Content-Type": "application/json",
        },
        json={
            "model": cfg["model"],
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.82,
            "response_format": {"type": "json_object"},
        },
        timeout=cfg["timeout"],
    )

    res.raise_for_status()
    data = res.json()
    content = data["choices"][0]["message"]["content"]
    parsed = _extract_json(content)

    parsed["ok"] = True
    parsed["provider"] = "deepseek"
    parsed["_llm_model"] = cfg["model"]
    parsed["_usage"] = data.get("usage")
    return parsed


@router.get("/health")
def health():
    cfg = _deepseek_config()
    return {
        "ok": True,
        "provider": "full_ai_script_ai_v1",
        "deepseek_configured": bool(cfg["api_key"]),
        "model": cfg["model"],
    }


@router.post("/plan")
def plan(req: FullAIScriptPlanRequest):
    started = time.time()

    if req.dry_run:
        out = _fallback(req)
        out["dry_run"] = True
        out["elapsed_seconds"] = round(time.time() - started, 2)
        return out

    try:
        out = _call_deepseek(req)
    except Exception as exc:
        out = _fallback(req)
        out["provider"] = "local_fallback_after_deepseek_error"
        out["deepseek_error"] = str(exc)

    out["elapsed_seconds"] = round(time.time() - started, 2)
    return out
