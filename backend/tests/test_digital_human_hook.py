"""Smoke tests for digital human hook_text and TTS segments compatibility."""

import pytest

from app.services.digital_human import extract_hook_text


def test_extract_hook_text_first_sentence():
    """Should extract only the first sentence, no punctuation, <=24 chars."""
    script = "来马来西亚买房，区域选错，几百万直接打水漂。今天就告诉你真相。"
    result = extract_hook_text(script, max_chars=24)
    # Should be first sentence without punctuation
    assert "来马来西亚买房" in result
    assert "区域选错" in result
    assert "今天就告诉你真相" not in result, f"Should not contain second sentence: {result}"
    assert len(result) <= 24, f"Should be <= 24 chars: {len(result)} '{result}'"
    # No punctuation
    for punct in ["，", "。", "！", "？", "、", "；", ":"]:
        assert punct not in result, f"Should not contain '{punct}': {result}"


def test_extract_hook_text_empty():
    assert extract_hook_text("") == ""
    assert extract_hook_text("   ") == ""


def test_extract_hook_text_short():
    result = extract_hook_text("海外买房必看", max_chars=24)
    assert result == "海外买房必看"


def test_extract_hook_text_english():
    script = "Buy Malaysia property now. Don't miss out on this opportunity."
    result = extract_hook_text(script, max_chars=24)
    assert "Buy Malaysia property" in result  # may be truncated at 24 chars
    assert "Don't miss out" not in result


def test_extract_hook_text_no_second_sentence():
    """Crucial: must never include the second sentence."""
    script = "KLCC核心区 vs TRX金融区，哪个更值得投资？今天就给你讲清楚。"
    result = extract_hook_text(script, max_chars=24)
    assert "今天就给你讲清楚" not in result, f"Second sentence leaked: {result}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
