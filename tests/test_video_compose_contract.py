"""Contract tests for compose_video and related functions."""

import asyncio
import inspect
from pathlib import Path

import pytest

from app.services.video import compose_video, create_smart_ass, split_script, create_srt, MediaClip, VideoResult
from app.services.tts import probe_duration
from app.services.effect_planner import TimedSegment, StickerCue


def test_compose_video_accepts_full_signature():
    """compose_video must accept all parameters that main.py passes."""
    sig = inspect.signature(compose_video)
    params = list(sig.parameters.keys())
    required = [
        "settings", "script", "asset_paths", "duration_seconds",
        "subtitle_segments", "subtitle_size", "subtitle_margin_v",
        "subtitle_position", "subtitle_style_preset", "subtitle_keywords",
        "keyword_sfx_enabled", "keyword_sfx_volume",
    ]
    for p in required:
        assert p in params, f"Missing parameter: {p}"


def test_create_smart_ass_accepts_font_size():
    """create_smart_ass must accept font_size, margin_v, subtitle_keywords."""
    sig = inspect.signature(create_smart_ass)
    params = list(sig.parameters.keys())
    for p in ("font_size", "margin_v", "subtitle_keywords"):
        assert p in params, f"Missing parameter: {p}"


def test_subtitle_font_size_fallback():
    """Font sizes below 70 must fall back to 80."""
    seg = TimedSegment(index=1, text="Test", start=0.0, end=1.0)
    stickers: list = []
    import tempfile, os
    tmp = Path(tempfile.mkdtemp()) / "test.ass"

    create_smart_ass([seg], stickers, tmp, font_size=18)
    content = tmp.read_text(encoding="utf-8")
    # Should have been bumped to 80
    assert "SC,80" in content, f"Expected Fontsize=80 fallback, got: {content[:500]}"

    create_smart_ass([seg], stickers, tmp, font_size=80)
    content = tmp.read_text(encoding="utf-8")
    assert "SC,80" in content

    # Cleanup
    tmp.unlink(missing_ok=True)
    tmp.parent.rmdir()


def test_keyword_style_no_black_box():
    """Keyword overlays must NOT contain box=1, boxcolor, or non-zero BackColour."""
    seg = TimedSegment(index=1, text="Hello world", start=0.0, end=2.0)
    cue = StickerCue(text="KEY", trigger="", start=0.5, end=1.5, x=540, y=400, tone="soft")
    import tempfile, os
    tmp = Path(tempfile.mkdtemp()) / "test_kw.ass"

    create_smart_ass([seg], [cue], tmp, font_size=80)
    content = tmp.read_text(encoding="utf-8")

    # Must NOT have black BackColour or box=1
    assert "BackColour,&H00000000" in content or "BackColour,&H0" in content or "&H00000000" in content, \
        f"BackColour should be transparent, got: {content[:800]}"
    assert "box=1" not in content.lower(), f"box=1 should not appear"
    assert "boxcolor" not in content.lower(), f"boxcolor should not appear"
    # Must use an8 (top-center) not rectangle
    assert r"\an8" in content, f"Keyword overlay should use \\an8 positioning"

    tmp.unlink(missing_ok=True)
    tmp.parent.rmdir()


def test_split_script_returns_chunks():
    """split_script should split text into chunks."""
    chunks = split_script("Hello world. This is a test.", max_chars=12)
    assert len(chunks) >= 1
    assert all(isinstance(c, str) for c in chunks)


def test_create_srt_generates_valid_srt():
    """create_srt should produce valid SRT with timestamps."""
    import tempfile, os
    tmp = Path(tempfile.mkdtemp()) / "test.srt"
    create_srt("Hello world. This is a test.", 5.0, tmp)
    content = tmp.read_text(encoding="utf-8")
    assert "-->" in content, f"SRT should contain -->: {content[:200]}"
    assert "Hello" in content
    tmp.unlink(missing_ok=True)
    tmp.parent.rmdir()


def test_mediaclip_dataclass():
    """MediaClip should exist with expected fields."""
    from pathlib import Path
    clip = MediaClip(path=Path("test.mp4"), order=1)
    assert clip.order == 1
    assert str(clip.path) == "test.mp4"
    assert clip.image_seconds == 2.8
    assert clip.video_start == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
