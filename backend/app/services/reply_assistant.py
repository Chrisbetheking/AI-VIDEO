"""Reply assistant for AI Video Growth Studio MVP.

Suggests reply text based on lead scoring + industry pack templates.
No auto-send. Human confirmation required.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

from app.services.industry_packs import get_pack
from app.services.lead_scoring import score_lead, ScoredLead


@dataclass
class ReplySuggestion:
    ok: bool = True
    intent_level: str = "low"
    intent_type: str = "general"
    suggested_reply: str = ""
    fallback_reply: str = ""
    next_action: str = "none"
    keywords_matched: List[str] = field(default_factory=list)
    confidence: float = 0.0


def suggest_reply(
    content: str,
    industry: str = "real_estate",
    platform: str = "douyin",
) -> ReplySuggestion:
    """Analyze a lead comment and suggest a reply.

    Args:
        content: The comment/message text.
        industry: real_estate or foreign_trade.
        platform: douyin, tiktok, etc. (reserved for future).

    Returns:
        ReplySuggestion with intent and suggested reply text.
    """
    # Score the lead
    scored = score_lead(content, industry)

    # Get industry pack for templates
    try:
        pack = get_pack(industry)
    except ValueError:
        pack = get_pack("real_estate")

    # Pick a reply template
    templates = pack.reply_templates
    reply = templates.get(scored.intent_type, templates.get("general", "感谢关注！想了解更多吗？"))

    # Fill in keyword placeholders
    if "{keyword}" in reply and scored.keywords_matched:
        reply = reply.replace("{keyword}", scored.keywords_matched[0])

    # Fallback reply
    fallback = templates.get("general", "Thank you for your interest!")

    # Determine next action
    next_action = "ask_contact" if scored.intent_level == "high" else "send_info" if scored.intent_level == "medium" else "none"

    return ReplySuggestion(
        ok=True,
        intent_level=scored.intent_level,
        intent_type=scored.intent_type,
        suggested_reply=reply,
        fallback_reply=fallback,
        next_action=next_action,
        keywords_matched=scored.keywords_matched,
        confidence=scored.confidence,
    )


@dataclass
class LeadRecord:
    id: str
    content: str
    industry: str
    platform: str
    intent_level: str
    intent_type: str
    suggested_reply: str
    status: str = "new"  # new, reviewed, contacted, closed
    created_at: str = ""


# Simple in-memory store for MVP (no database)
_LEADS_STORE: List[LeadRecord] = []


def store_lead(suggestion: ReplySuggestion, content: str, industry: str, platform: str) -> LeadRecord:
    import uuid
    from datetime import datetime, timezone
    record = LeadRecord(
        id=uuid.uuid4().hex[:12],
        content=content,
        industry=industry,
        platform=platform,
        intent_level=suggestion.intent_level,
        intent_type=suggestion.intent_type,
        suggested_reply=suggestion.suggested_reply,
        status="new",
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    _LEADS_STORE.append(record)
    return record


def list_leads(industry: Optional[str] = None) -> List[LeadRecord]:
    if industry:
        return [r for r in _LEADS_STORE if r.industry == industry]
    return list(_LEADS_STORE)


def get_lead(lead_id: str) -> Optional[LeadRecord]:
    for r in _LEADS_STORE:
        if r.id == lead_id:
            return r
    return None


def update_lead(lead_id: str, **kwargs) -> Optional[LeadRecord]:
    record = get_lead(lead_id)
    if record is None:
        return None
    for key, value in kwargs.items():
        if hasattr(record, key):
            setattr(record, key, value)
    return record
