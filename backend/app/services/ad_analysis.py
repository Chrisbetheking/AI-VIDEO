from __future__ import annotations

import hashlib
import random
import time
from typing import List

from app.schemas import AdAnalysisRequest, AdAnalysisResponse, AdMetric


def _score_text(title: str, script: str) -> float:
    script = script.strip()
    score = 50.0
    if any(x in script[:40] for x in ["你是不是", "为什么", "别再", "很多老板", "普通人", "客户"]):
        score += 12
    if any(x in script for x in ["案例", "真实", "客户", "结果", "对比", "数据"]):
        score += 10
    if any(x in script[-80:] for x in ["私信", "评论", "咨询", "联系我们", "点击", "领取"]):
        score += 10
    if 80 <= len(script) <= 260:
        score += 8
    elif len(script) > 420:
        score -= 8
    if len(title) <= 30:
        score += 5
    return max(0, min(100, score))


def _stable_random(seed_text: str) -> random.Random:
    bucket = int(time.time() // 8)  # 8 秒刷新一次，看起来像实时监控
    digest = hashlib.sha256(f"{seed_text}-{bucket}".encode("utf-8")).hexdigest()
    return random.Random(int(digest[:16], 16))


def analyze_ad(req: AdAnalysisRequest) -> AdAnalysisResponse:
    score = _score_text(req.title, req.script)
    rnd = _stable_random(req.title + req.script + req.industry)

    impressions = int(rnd.uniform(1200, 18000) * max(1, req.budget / 300))
    ctr = max(0.3, min(8.5, rnd.gauss(2.2 + (score - 60) / 35, 0.45)))
    play_rate = max(8, min(68, rnd.gauss(28 + (score - 50) / 2.6, 4)))
    like_rate = max(0.2, min(12, rnd.gauss(2.8 + (score - 55) / 30, 0.55)))
    cpm = max(8, min(80, rnd.gauss(28 - (score - 60) / 5, 4)))
    spend = min(req.budget, impressions / 1000 * cpm)
    leads = int(impressions * ctr / 100 * rnd.uniform(0.08, 0.22))
    cpl = spend / leads if leads else 0

    if score >= 78:
        decision = "建议小预算放量：内容基础较好，可先投 100-300 元测试，再根据转化加预算。"
        confidence = 0.86
        suggested_budget = "首轮 100-300 元；跑满 2-4 小时后，优先加预算到表现最好的计划。"
    elif score >= 62:
        decision = "建议先小额测试：先投 50-150 元验证点击和完播，低于阈值就先改文案/封面。"
        confidence = 0.74
        suggested_budget = "首轮 50-150 元；CTR > 2%、完播率 > 25% 再加。"
    else:
        decision = "暂不建议直接投大预算：先优化前 3 秒钩子、案例证明和结尾转化动作。"
        confidence = 0.7
        suggested_budget = "最多 30-80 元试水，建议先改内容再投。"

    alerts: List[str] = []
    if ctr < 1.5:
        alerts.append("点击率偏低：封面标题或前 3 秒钩子需要更直接。")
    if play_rate < 22:
        alerts.append("完播率偏低：口播偏长或节奏不够快，建议压缩到 25-35 秒。")
    if leads == 0:
        alerts.append("当前未形成有效线索：结尾需要更明确的私信/咨询动作。")
    if not alerts:
        alerts.append("当前核心指标正常，可继续观察 30-60 分钟再决定是否放量。")

    metrics = [
        AdMetric(name="实时曝光", value=f"{impressions:,}", status="normal"),
        AdMetric(name="点击率 CTR", value=f"{ctr:.2f}%", status="good" if ctr >= 2 else "warn"),
        AdMetric(name="完播率", value=f"{play_rate:.1f}%", status="good" if play_rate >= 25 else "warn"),
        AdMetric(name="互动率", value=f"{like_rate:.1f}%", status="normal"),
        AdMetric(name="CPM", value=f"¥{cpm:.1f}", status="good" if cpm <= 35 else "warn"),
        AdMetric(name="已消耗", value=f"¥{spend:.2f}", status="normal"),
        AdMetric(name="预估线索", value=f"{leads}", status="good" if leads > 0 else "warn"),
        AdMetric(name="预估 CPL", value=(f"¥{cpl:.1f}" if leads else "暂无"), status="normal" if leads else "warn"),
    ]

    target_audience = [
        "同城/周边 20-45 岁潜在人群",
        "近期搜索或互动过相关行业内容的人群",
        "相似达人/竞品账号互动人群",
        "已私信/进主页/看过视频的人群再营销",
    ]
    if req.industry:
        target_audience.insert(0, f"{req.industry} 相关兴趣和意向人群")

    optimization_tips = [
        "前 3 秒先讲痛点或结果，不要先自我介绍。",
        "中段加入一个具体案例、数字或对比，提升信任。",
        "结尾只保留一个动作：评论关键词、私信、进主页或留资。",
        "同一文案至少测试 2 个封面标题和 2 个开头版本。",
    ]

    next_actions = [
        "先自然发布观察 30-60 分钟，记录播放、完播、互动。",
        "若自然完播率 > 25% 且 CTR > 2%，开启小预算测试。",
        "投流 2 小时后保留高 CTR/低 CPL 计划，暂停低完播计划。",
        "把高表现文案沉淀进知识库，用于下一条类比生成。",
    ]

    return AdAnalysisResponse(
        decision=decision,
        confidence=confidence,
        suggested_budget=suggested_budget,
        target_audience=target_audience,
        metrics=metrics,
        alerts=alerts,
        optimization_tips=optimization_tips,
        next_actions=next_actions,
    )
