"""Smoke tests for industry packs."""

import pytest
from app.services.industry_packs import get_pack, list_packs, INDUSTRY_PACKS


def test_list_packs_returns_both():
    packs = list_packs()
    industries = [p["industry"] for p in packs]
    assert "real_estate" in industries
    assert "foreign_trade" in industries


def test_get_real_estate_pack():
    pack = get_pack("real_estate")
    assert pack.industry_name == "real_estate"
    assert len(pack.pain_points) >= 3
    assert len(pack.hook_templates) >= 2
    assert len(pack.reply_templates) >= 3
    assert "KLCC" in pack.asset_keywords or any("KLCC" in kw for kw in pack.asset_keywords)


def test_get_foreign_trade_pack():
    pack = get_pack("foreign_trade")
    assert pack.industry_name == "foreign_trade"
    assert len(pack.lead_keywords) >= 3
    assert "MOQ" in pack.lead_keywords or any("MOQ" in kw for kw in pack.lead_keywords)
    assert "price" in pack.reply_templates


def test_get_unknown_industry_raises():
    with pytest.raises(ValueError, match="Unknown industry"):
        get_pack("nonexistent")


def test_packs_have_forbidden_words():
    for name in INDUSTRY_PACKS:
        pack = INDUSTRY_PACKS[name]
        assert len(pack.forbidden_words) > 0, f"{name} missing forbidden_words"
