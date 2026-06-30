"""Tests for Volcengine voice clone V3."""
import pytest
from pathlib import Path


class TestVoiceCloneStatus:
    def test_status_no_json_no_env(self, tmp_path, monkeypatch):
        """Returns has_voice_type=false when nothing configured."""
        from app.services.volcengine_voice_clone import get_voice_clone_status
        from app.config import Settings
        import app.services.volcengine_voice_clone as vc

        monkeypatch.setattr(vc, "VOICE_JSON_PATH", tmp_path / "nonexistent.json")

        settings = Settings(
            volcengine_app_id="test_app",
            volcengine_access_token="test_token",
            volcengine_voice_type="",
            outputs_dir=Path("/tmp"),
        )
        status = get_voice_clone_status(settings)
        assert status.ok is True
        assert status.has_app_id is True
        assert status.has_access_token is True
        assert status.has_voice_type is False
        assert status.voice_type_masked == ""

    def test_status_with_saved_voice(self, tmp_path, monkeypatch):
        """Loads voice_type from saved JSON."""
        from app.services.volcengine_voice_clone import (
            get_voice_clone_status, save_voice_data, load_voice_type
        )
        from app.config import Settings
        import app.services.volcengine_voice_clone as vc

        monkeypatch.setattr(vc, "VOICE_JSON_PATH", tmp_path / "volcengine_voice.json")

        save_voice_data("S_test123", voice_name="uncle_voice")
        assert load_voice_type() == "S_test123"

        settings = Settings(
            volcengine_app_id="test_app",
            volcengine_access_token="test_token",
            volcengine_voice_type="",
            outputs_dir=Path("/tmp"),
        )
        status = get_voice_clone_status(settings)
        assert status.has_voice_type is True
        assert "***" in status.voice_type_masked

    def test_load_empty_when_no_file(self, tmp_path, monkeypatch):
        """load_voice_type returns empty string when no file."""
        from app.services.volcengine_voice_clone import load_voice_type, load_voice_data
        import app.services.volcengine_voice_clone as vc

        monkeypatch.setattr(vc, "VOICE_JSON_PATH", tmp_path / "nonexistent.json")
        assert load_voice_type() == ""
        assert load_voice_data() == {}

    def test_tts_uses_saved_voice_type(self, tmp_path, monkeypatch):
        """synthesize_volcengine_v1 loads voice_type from saved JSON when env is empty."""
        from app.services.volcengine_voice_clone import save_voice_data
        from app.config import Settings
        import app.services.volcengine_voice_clone as vc

        monkeypatch.setattr(vc, "VOICE_JSON_PATH", tmp_path / "volcengine_voice.json")
        save_voice_data("S_saved_voice_xyz", voice_name="test")

        settings = Settings(
            volcengine_app_id="test_app",
            volcengine_access_token="test_token",
            volcengine_voice_type="",  # empty env
            volcengine_cluster="volcano_icl",
            volcengine_resource_id="seed-icl-2.0",
            outputs_dir=Path("/tmp"),
        )
        # When env voice_type is empty, should fall back to saved
        from app.services.volcengine_voice_clone import load_voice_type
        assert load_voice_type() == "S_saved_voice_xyz"

    def test_mismatch_error_message_clear(self):
        """Verify the resource mismatch error message."""
        from app.services.volcengine_voice_clone import VoiceCloneResult
        r = VoiceCloneResult(
            ok=False,
            message="当前声音不属于 seed-icl-2.0 资源，请使用豆包声音复刻 V3 训练出的字符版/ICL 兼容音色。",
        )
        assert "seed-icl-2.0" in r.message
        assert "声音复刻" in r.message
