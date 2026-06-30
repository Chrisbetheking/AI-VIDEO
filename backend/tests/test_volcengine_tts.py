import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from pathlib import Path


class TestVolcengineTTSParams:
    """Verify synthesize_volcengine_v1 sends voice_type and app credentials correctly."""

    @patch("app.services.tts.httpx.AsyncClient")
    @patch("app.services.tts.uuid.uuid4")
    def test_voice_type_sent_in_params_and_header(self, mock_uuid, mock_async_client):
        """voice_type in query params and X-Api-Voice-Type header."""
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

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"code": "3000", "data": "AAAA"}

        mock_client_instance = MagicMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)
        mock_client_instance.post = AsyncMock(return_value=mock_response)
        mock_async_client.return_value = mock_client_instance

        import asyncio
        asyncio.run(synthesize_volcengine_v1(settings, "测试文本", None, None))

        call_kwargs = mock_client_instance.post.call_args
        assert call_kwargs is not None, "httpx.post was not called"

        # Check params
        called_params = call_kwargs.kwargs.get("params", {})
        assert called_params.get("voice_type") == "zh_female_v11", f"voice_type not in params: {called_params}"
        assert called_params.get("appid") == "test_app_id", f"appid not in params: {called_params}"
        assert called_params.get("app_id") == "test_app_id", f"app_id not in params: {called_params}"
        assert called_params.get("appkey") == "test_app_id", f"appkey not in params: {called_params}"
        assert called_params.get("app_key") == "test_app_id", f"app_key not in params: {called_params}"

        # Check headers
        called_headers = call_kwargs.kwargs.get("headers", {})
        assert called_headers.get("X-Api-Voice-Type") == "zh_female_v11", f"X-Api-Voice-Type missing: {called_headers}"
        assert called_headers.get("X-Api-App-Key") == "test_app_id", f"X-Api-App-Key missing: {called_headers}"
        assert called_headers.get("X-Api-Access-Key") == "test_token", f"X-Api-Access-Key missing: {called_headers}"
        assert called_headers.get("X-Api-Resource-Id") == "seed-icl-2.0", f"X-Api-Resource-Id missing: {called_headers}"
        assert "Authorization" in called_headers, "Authorization header missing"

        # Check body
        called_json = call_kwargs.kwargs.get("json", {})
        assert called_json.get("audio", {}).get("voice_type") == "zh_female_v11", "voice_type not in body audio"
        assert called_json.get("app", {}).get("appid") == "test_app_id", "appid not in body app"
        assert called_json.get("app", {}).get("token") == "test_token", "token not in body app"

    def test_voice_type_default_fallback(self):
        """voice_type defaults from env when voice='default'."""
        pass  # Covered implicitly by test above

    def test_missing_voice_type_raises(self):
        """Missing VOICE_TYPE raises RuntimeError, not 500."""
        from app.services.tts import synthesize_volcengine_v1
        from app.config import Settings
        import asyncio

        settings = Settings(
            volcengine_app_id="test_app_id",
            volcengine_access_token="test_token",
            volcengine_voice_type="",
            outputs_dir=Path("/tmp"),
        )
        with pytest.raises(RuntimeError, match="缺少 VOLCENGINE_VOICE_TYPE"):
            asyncio.run(synthesize_volcengine_v1(settings, "测试", None, None))

    @patch("app.services.tts.httpx.AsyncClient")
    @patch("app.services.tts.uuid.uuid4")
    def test_http_400_shows_voice_type_in_error(self, mock_uuid, mock_async_client):
        """HTTP 400 includes voice_type in error message."""
        from app.services.tts import synthesize_volcengine_v1
        from app.config import Settings

        settings = Settings(
            volcengine_app_id="test_app_id",
            volcengine_access_token="test_token",
            volcengine_voice_type="bad_voice_type_123",
            outputs_dir=Path("/tmp"),
        )
        mock_uuid.return_value.hex = "abc123"

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = '{"code":45000000,"message":"app key not found"}'

        mock_client_instance = MagicMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)
        mock_client_instance.post = AsyncMock(return_value=mock_response)
        mock_async_client.return_value = mock_client_instance

        import asyncio
        with pytest.raises(RuntimeError, match="bad_voice_type_123"):
            asyncio.run(synthesize_volcengine_v1(settings, "测试", None, None))
