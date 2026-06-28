"""Lead scoring for AI Video Growth Studio MVP.

Simple keyword + rule-based intent scoring. No LLM required for V1.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional


INTENT_LEVELS = ["low", "medium", "high"]


@dataclass
class ScoredLead:
    intent_level: str  # low, medium, high
    intent_type: str   # price, catalog, contact, general, etc.
    confidence: float  # 0.0 - 1.0
    keywords_matched: List[str] = field(default_factory=list)
    raw_content: str = ""


# High-intent patterns per industry
REAL_ESTATE_PATTERNS: Dict[str, List[str]] = {
    "price": ["多少钱", "价格", "报价", "多少钱一平", "首付", "月供", "总价", "预算"],
    "loan": ["能贷款", "贷款", "按揭", "外国人能买", "外国人可以买"],
    "catalog": ["有资料", "发我", "看看", "房源", "项目", "楼盘"],
    "contact": ["怎么联系", "微信", "WhatsApp", "电话", "加我", "私信"],
    "visit": ["能看房", "实地", "视频看房", "样子"],
    "timeline": ["什么时候交房", "多久", "什么时候", "进度"],
}

FOREIGN_TRADE_PATTERNS: Dict[str, List[str]] = {
    "price": ["price", "how much", "cost", "quote", "pricing", "多少钱"],
    "catalog": ["catalog", "brochure", "product list", "catalogue"],
    "sample": ["sample", "样品", "样板"],
    "moq": ["MOQ", "minimum order", "min order", "起订量"],
    "shipping": ["shipping", "delivery", "freight", "物流", "发货"],
    "contact": ["contact", "WhatsApp", "微信", "email", "DM"],
    "oem": ["OEM", "ODM", "custom logo", "customize", "贴牌"],
    "lead_time": ["lead time", "production time", "交货期"],
}


def _normalize(text: str) -> str:
    return text.lower().strip()


def score_lead(
    content: str,
    industry: str = "real_estate",
) -> ScoredLead:
    """Score a lead comment based on keyword matching.

    Args:
        content: The comment/message text.
        industry: real_estate or foreign_trade.

    Returns:
        ScoredLead with intent_level, intent_type, and matched keywords.
    """
    patterns = REAL_ESTATE_PATTERNS if industry == "real_estate" else FOREIGN_TRADE_PATTERNS
    normalized = _normalize(content)

    matched_types: Dict[str, int] = {}
    all_matched: List[str] = []

    for intent_type, keywords in patterns.items():
        count = 0
        for kw in keywords:
            if _normalize(kw) in normalized:
                count += 1
                all_matched.append(kw)
        if count > 0:
            matched_types[intent_type] = count

    if not matched_types:
        return ScoredLead(
            intent_level="low",
            intent_type="general",
            confidence=0.1,
            keywords_matched=[],
            raw_content=content,
        )

    # Determine primary intent type (most keywords matched)
    primary_type = max(matched_types, key=matched_types.get)
    primary_count = matched_types[primary_type]
    total_matches = sum(matched_types.values())

    # Confidence from match density
    confidence = min(0.95, primary_count / max(len(patterns[primary_type]), 1) * 0.8 + total_matches * 0.05)

    # Intent level
    if "price" in primary_type or "contact" in primary_type or total_matches >= 3:
        intent_level = "high"
    elif total_matches >= 2:
        intent_level = "medium"
    else:
        intent_level = "low"

    return ScoredLead(
        intent_level=intent_level,
        intent_type=primary_type,
        confidence=round(confidence, 2),
        keywords_matched=all_matched,
        raw_content=content,
    )
