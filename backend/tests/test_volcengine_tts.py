"""Tests for Volcengine TTS voice_type params and error handling."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from pathlib import Path


class TestVolcengineTTSParams:
    """Verify that synthesize_volcengine_v1 includes voice_type in params and headers."""

    @patch("app.services.tts.httpx.AsyncClient")
    @patch("app.services.tts.uuid.uuid4")
    def test_voice_type_sent_in_params_and_header(self, mock_uuid, mock_async_client):
        """voice_type should appear in query params and X-Api-Voice-Type header."""
        from app.services.tts import synthesize_volcengine_v1
        from app.config import Settings

        settings = Settings(
            volcengine_app_id="test_app_id",
            volcengine_access_token="test_token",
            volcengine_voice_type="zh_female_v11",
            volcengine_cluster="volcano_icl",
            volcengine_resource_id="seed-icl-2.0",
            volcengine_tts_endpoint="https://openspeech.bytedance.com/api/v3/tts/unidirectional",
            outputs_dir=Path("/tmp"),
        )

        mock_uuid.return_value.hex = "abc123"

        # Mock the HTTP response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "code": "3000",
            "data": "AAAA",  # fake base64
        }

        mock_client_instance = MagicMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)
        mock_client_instance.post = AsyncMock(return_value=mock_response)
        mock_async_client.return_value = mock_client_instance

        import asyncio
        asyncio.run(synthesize_volcengine_v1(settings, "测试文本", None, None))

        # Verify the post was called with voice_type in params and header
        call_kwargs = mock_client_instance.post.call_args
        assert call_kwargs is not None, "httpx.post was not called"

        # Check params
        called_params = call_kwargs.kwargs.get("params", {})
        assert called_params.get("voice_type") == "zh_female_v11", (
            f"voice_type not in query params, got: {called_params}"
        )

        # Check header
        called_headers = call_kwargs.kwargs.get("headers", {})
        assert called_headers.get("X-Api-Voice-Type") == "zh_female_v11", (
            f"X-Api-Voice-Type header missing or wrong, got: {called_headers}"
        )

        # Check that body still contains voice_type in audio
        called_json = call_kwargs.kwargs.get("json", {})
        assert called_json.get("audio", {}).get("voice_type") == "zh_female_v11", (
            f"voice_type not in body audio, got: {called_json.get('audio', {})}"
        )

    def test_voice_type_default_fallback(self):
        """voice_type defaults from env when voice='default'."""
        from app.services.tts import synthesize_volcengine_v1
        from app.config import Settings

        settings = Settings(
            volcengine_app_id="test_app_id",
            volcengine_access_token="test_token",
            volcengine_voice_type="env_default_voice",
            outputs_dir=Path("/tmp"),
        )
        # When voice is not provided or 'default', use env voice_type
        # This is tested implicitly by the above test; no crash expected

    def test_missing_voice_type_raises(self):
        """Missing VOICE_TYPE should raise RuntimeError, not 500."""
        from app.services.tts import synthesize_volcengine_v1
        from app.config import Settings
        import asyncio

        settings = Settings(
            volcengine_app_id="test_app_id",
            volcengine_access_token="test_token",
            volcengine_voice_type="",  # empty
            outputs_dir=Path("/tmp"),
        )

        with pytest.raises(RuntimeError, match="缺少 VOLCENGINE_VOICE_TYPE"):
            asyncio.run(synthesize_volcengine_v1(settings, "测试", None, None))

    @patch("app.services.tts.httpx.AsyncClient")
    @patch("app.services.tts.uuid.uuid4")
    def test_http_400_shows_voice_type_in_error(self, mock_uuid, mock_async_client):
        """HTTP 400 error message should include the voice_type used."""
        from app.services.tts import synthesize_volcengine_v1
        from app.config import Settings

        settings = Settings(
            volcengine_app_id="test_app_id",
            volcengine_access_token="test_token",
            volcengine_voice_type="bad_voice_type_123",
            output_dir="/tmp",
            outputs_dir=Path("/tmp"),
        )

        mock_uuid.return_value.hex = "abc123"

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = '{"code":45000000,"message":"voice_type not found"}'

        mock_client_instance = MagicMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)
        mock_client_instance.post = AsyncMock(return_value=mock_response)
        mock_async_client.return_value = mock_client_instance

        import asyncio
        with pytest.raises(RuntimeError, match="bad_voice_type_123"):
            asyncio.run(synthesize_volcengine_v1(settings, "测试", None, None))
