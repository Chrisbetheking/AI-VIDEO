"""Smoke tests for lead scoring."""

import pytest
from app.services.lead_scoring import score_lead, ScoredLead


def test_real_estate_price_intent_high():
    result = score_lead("这个房子多少钱，能贷款吗？", industry="real_estate")
    assert result.intent_level == "high"
    assert result.intent_type in ("price", "loan")
    assert len(result.keywords_matched) >= 2
    assert result.confidence > 0.3


def test_foreign_trade_quote_intent_high():
    result = score_lead("Price? MOQ? Can you send catalog?", industry="foreign_trade")
    assert result.intent_level == "high"
    assert result.intent_type in ("price", "catalog", "moq")
    assert len(result.keywords_matched) >= 3


def test_foreign_trade_catalog_intent():
    result = score_lead("Send me catalog and price please", industry="foreign_trade")
    assert result.intent_level in ("medium", "high")
    assert result.intent_type in ("catalog", "price")


def test_low_intent_generic_comment():
    result = score_lead("Nice video!", industry="real_estate")
    assert result.intent_level == "low"
    assert result.intent_type == "general"


def test_empty_comment():
    result = score_lead("", industry="real_estate")
    assert result.intent_level == "low"
    assert result.intent_type == "general"


def test_contact_intent_high():
    result = score_lead("怎么联系你？加我微信", industry="real_estate")
    assert result.intent_level == "high"
    assert result.intent_type == "contact"


def test_oem_intent():
    result = score_lead("Do you support OEM and custom logo?", industry="foreign_trade")
    assert result.intent_level in ("medium", "high")
    assert result.intent_type == "oem"
