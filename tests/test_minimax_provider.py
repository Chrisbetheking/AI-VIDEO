"""Smoke tests for MiniMax provider (disabled-by-default, no real API key needed)."""

from unittest.mock import patch, MagicMock

import pytest

from app.services.minimax_provider import (
    get_minimax_status,
    text_to_video,
    image_to_video,
    query_video_status,
    get_broll_prompts,
    MiniMaxVideoResult,
    MiniMaxStatus,
)


class FakeSettings:
    minimax_enabled: bool = False
    minimax_api_key: str = ''
    minimax_video_model: str = 'MiniMax-Hailuo-2.3'
    minimax_tts_model: str = ''


def test_status_disabled_without_key():
    s = FakeSettings()
    result = get_minimax_status(s)
    assert result.enabled == False
    assert "disabled" in result.message.lower() or "missing" in result.message.lower()


def test_status_enabled_with_key():
    s = FakeSettings()
    s.minimax_enabled = True
    s.minimax_api_key = "test-key-123"
    result = get_minimax_status(s)
    assert result.enabled == True
    assert result.video_model == "MiniMax-Hailuo-2.3"


def test_text_to_video_disabled():
    s = FakeSettings()
    import asyncio
    r = asyncio.run(text_to_video(s, prompt="test"))
    assert r.ok == False
    assert r.enabled == False
    assert "disabled" in r.message.lower()


def test_image_to_video_disabled():
    s = FakeSettings()
    import asyncio
    r = asyncio.run(image_to_video(s, image_url="https://example.com/img.jpg"))
    assert r.ok == False
    assert r.enabled == False


def test_query_status_disabled():
    s = FakeSettings()
    import asyncio
    r = asyncio.run(query_video_status(s, task_id="fake-task"))
    assert r.ok == False
    assert r.enabled == False


def test_get_broll_prompts_real_estate():
    prompts = get_broll_prompts("real_estate", count=2)
    assert len(prompts) == 2
    assert "KLCC" in prompts[0] or "Kuala Lumpur" in prompts[0] or "condominium" in prompts[0].lower()


def test_get_broll_prompts_foreign_trade():
    prompts = get_broll_prompts("foreign_trade", count=3)
    assert len(prompts) == 3
    assert any("factory" in p.lower() or "warehouse" in p.lower() for p in prompts)


def test_get_broll_prompts_unknown_falls_back():
    prompts = get_broll_prompts("nonexistent", count=1)
    assert len(prompts) == 1
    # Should return real_estate prompts as fallback


def test_result_dataclass_defaults():
    r = MiniMaxVideoResult()
    assert r.ok == False
    assert r.enabled == False
    assert r.status == "pending"
    assert r.video_url is None


def test_status_dataclass_defaults():
    s = MiniMaxStatus()
    assert s.enabled == False
    assert s.video_model == ""
    # Default dataclass has empty message; get_minimax_status fills it
    assert s.message == "" or "disabled" in s.message.lower() or "missing" in s.message.lower()
