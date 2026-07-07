from __future__ import annotations

import asyncio
import shutil

import pytest

from app.config import Settings
from app.services.video import compose_video


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_compose_video_without_assets(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ALLOW_MOCK_TTS", "true")
    monkeypatch.setenv("TTS_PROVIDER", "mock")
    settings = Settings(app_data_dir=str(tmp_path), tts_provider="mock", allow_mock_tts=True)
    result = asyncio.run(compose_video(settings, "这是一条测试口播，用来确认视频合成可以跑通。", [], 5))
    assert result.video_path.exists()
    assert result.video_path.stat().st_size > 1000
    assert result.subtitle_path and result.subtitle_path.exists()
