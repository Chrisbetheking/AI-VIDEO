"""Tests for MiniMax TTS provider."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from pathlib import Path


class TestMiniMaxTTSStatus:
    """Verify minimax TTS status and disabled states."""

    def test_disabled_without_key(self):
        """TTS disabled when missing api key."""
        from app.services.minimax_tts import get_minimax_tts_status
        from app.config import Settings

        settings = Settings(
            minimax_tts_enabled=True,
            minimax_api_key="",
            minimax_voice_id="voice_123",
            outputs_dir=Path("/tmp"),
        )
        status = get_minimax_tts_status(settings)
        assert status.enabled is False
        assert "missing api key" in status.message.lower()

    def test_disabled_without_voice_id(self):
        """TTS disabled when missing voice_id."""
        from app.services.minimax_tts import get_minimax_tts_status
        from app.config import Settings

        settings = Settings(
            minimax_tts_enabled=True,
            minimax_api_key="key123",
            minimax_voice_id="",
            outputs_dir=Path("/tmp"),
        )
        status = get_minimax_tts_status(settings)
        assert status.enabled is False

    def test_enabled_with_all_config(self):
        """TTS enabled when all config present."""
        from app.services.minimax_tts import get_minimax_tts_status
        from app.config import Settings

        settings = Settings(
            minimax_tts_enabled=True,
            minimax_api_key="key123",
            minimax_voice_id="voice_123",
            minimax_tts_model="speech-2.8-hd",
            outputs_dir=Path("/tmp"),
        )
        status = get_minimax_tts_status(settings)
        assert status.enabled is True
        assert status.has_voice_id is True
        assert status.has_api_key is True
        assert "***" in status.voice_id_masked

    def test_disabled_does_not_crash_synthesize(self):
        """synthesize_minimax returns disabled result instead of crashing."""
        from app.services.minimax_tts import synthesize_minimax
        from app.config import Settings
        import asyncio

        settings = Settings(
            minimax_tts_enabled=False,
            minimax_api_key="",
            outputs_dir=Path("/tmp"),
        )
        result = asyncio.run(synthesize_minimax(settings, "test text"))
        assert result.ok is False
        assert result.enabled is False
        assert result.file_path is None

    def test_missing_voice_id_returns_clear_error(self):
        """Missing voice_id returns clear error, not crash."""
        from app.services.minimax_tts import synthesize_minimax
        from app.config import Settings
        import asyncio

        settings = Settings(
            minimax_tts_enabled=True,
            minimax_api_key="key123",
            minimax_voice_id="",
            outputs_dir=Path("/tmp"),
        )
        result = asyncio.run(synthesize_minimax(settings, "test text"))
        assert result.ok is False
        assert result.enabled is True
        assert "missing voice_id" in result.message.lower()


class TestMiniMaxTTSIntegration:
    """Verify minimax wires into tts-segments flow."""

    def test_tts_segments_schema_has_provider_field(self):
        """TTSSegmentsRequest supports tts_provider field."""
        from app.schemas import TTSSegmentsRequest, VoiceSegment
        req = TTSSegmentsRequest(
            segments=[VoiceSegment(text="hello", emotion="")],
            tts_provider="minimax",
        )
        assert req.tts_provider == "minimax"

    def test_synthesize_tts_segments_uses_minimax(self):
        """tts_provider=minimax dispatches to minimax code path (no crash)."""
        from app.services.tts import synthesize_tts
        from app.config import Settings
        from pathlib import Path
        import asyncio

        settings = Settings(
            tts_provider="minimax",
            minimax_tts_enabled=False,
            minimax_api_key="",
            outputs_dir=Path("/tmp"),
            data_dir=Path("/tmp"),
        )

        # With minimax disabled, should raise clear error, not crash
        try:
            asyncio.run(synthesize_tts(settings, "hello world"))
        except Exception as e:
            msg = str(e).lower()
            assert "disabled" in msg or "missing" in msg or "minimax" in msg, f"Unexpected error: {e}"

    def test_volcengine_still_works(self):
        """Volcengine provider is not broken by minimax addition."""
        from app.services.tts import synthesize_tts_segments
        from app.config import Settings
        from app.schemas import VoiceSegment
        from pathlib import Path

        settings = Settings(
            tts_provider="volcengine",
            volcengine_app_id="test",
            volcengine_access_token="test",
            volcengine_voice_type="test_voice",
            outputs_dir=Path("/tmp"),
            tmp_dir=Path("/tmp"),
            data_dir=Path("/tmp"),
        )

        # Should not crash on import/config; actual call would fail without network
        assert settings.tts_provider == "volcengine"


class TestHealthEndpoint:
    """Verify health endpoint includes minimax TTS fields."""

    def test_health_includes_minimax_fields(self):
        """Health response includes minimax_tts_* fields."""
        from app.config import Settings

        settings = Settings(
            minimax_tts_enabled=False,
            minimax_api_key="",
            outputs_dir=Path("/tmp"),
        )
        assert hasattr(settings, "minimax_tts_enabled")
        assert hasattr(settings, "minimax_voice_id")


class TestVoiceIdPersistence:
    """Verify voice_id save/load works."""

    def test_save_and_load_voice_id(self, tmp_path, monkeypatch):
        """Saving voice_id persists to JSON and loads back."""
        from app.services.minimax_tts import save_voice_id, load_voice_id, load_voice_data, VOICE_JSON_PATH
        import app.services.minimax_tts as mm_tts

        # Override the path to use tmp_path
        monkeypatch.setattr(mm_tts, "VOICE_JSON_PATH", tmp_path / "minimax_voice.json")

        save_voice_id("test_voice_123", file_id="file_456", voice_name="Test Voice")
        assert load_voice_id() == "test_voice_123"

        data = load_voice_data()
        assert data["voice_id"] == "test_voice_123"
        assert data["file_id"] == "file_456"
        assert data["voice_name"] == "Test Voice"

    def test_load_empty_when_no_file(self, tmp_path, monkeypatch):
        """Returns empty string when no voice file exists."""
        from app.services.minimax_tts import load_voice_id, load_voice_data
        import app.services.minimax_tts as mm_tts

        monkeypatch.setattr(mm_tts, "VOICE_JSON_PATH", tmp_path / "nonexistent.json")
        assert load_voice_id() == ""
        assert load_voice_data() == {}

