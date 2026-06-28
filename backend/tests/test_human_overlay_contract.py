"""Contract tests for human overlay service."""

import inspect
from pathlib import Path

import pytest

from app.services.human_overlay import (
    overlay_human_on_video,
    build_human_overlay_filter,
    chromakey_filter,
    HumanOverlayResult,
    HUMAN_POSITIONS,
    HUMAN_SCALES,
)


def test_human_overlay_no_video_does_not_crash():
    """When no human video exists, should return base video gracefully."""
    result = overlay_human_on_video(
        base_video=Path("test_base.mp4"),
        human_video=Path("nonexistent.mp4"),
        output_path=Path("out.mp4"),
    )
    assert result.mode == "none"
    assert len(result.warnings) >= 1
    assert "No human video" in result.warnings[0]


def test_chromakey_filter_contains_chromakey():
    """The generated filter must contain chromakey for green screen."""
    f = chromakey_filter()
    assert "chromakey" in f


def test_build_filter_contains_overlay():
    """The filter built by build_human_overlay_filter must contain overlay."""
    f = build_human_overlay_filter(scale_pct="40%", position="right_bottom")
    assert "overlay" in f
    assert "chromakey" in f
    assert "scale" in f


def test_positions_have_valid_syntax():
    """All position templates must be valid FFmpeg overlay expressions."""
    for name, expr in HUMAN_POSITIONS.items():
        assert "W" in expr or "w" in expr or "H" in expr or "h" in expr
        assert "H" in expr or "h" in expr


def test_scales_have_reasonable_values():
    """Scale factors must be between 0.1 and 1.0."""
    for pct, factor in HUMAN_SCALES.items():
        assert 0.1 <= factor <= 1.0, f"{pct} -> {factor} out of range"


def test_result_dataclass_fields():
    """HumanOverlayResult must have expected fields."""
    result = HumanOverlayResult(output_path=None, mode="none")
    assert result.mode == "none"
    assert result.warnings == []
    assert result.output_path is None
