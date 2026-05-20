from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"

    cors_origins: str = "*"
    app_data_dir: str = Field(default="./data")
    static_dir: str = Field(default="./static")

    tts_provider: str = "edge"
    tts_voice: str = "zh-CN-YunxiNeural"
    tts_rate: str = "+0%"
    allow_mock_tts: bool = True

    max_upload_mb: int = 300

    @property
    def data_dir(self) -> Path:
        path = Path(self.app_data_dir).resolve()
        path.mkdir(parents=True, exist_ok=True)
        (path / "uploads").mkdir(parents=True, exist_ok=True)
        (path / "outputs").mkdir(parents=True, exist_ok=True)
        (path / "tmp").mkdir(parents=True, exist_ok=True)
        return path

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def outputs_dir(self) -> Path:
        return self.data_dir / "outputs"

    @property
    def tmp_dir(self) -> Path:
        return self.data_dir / "tmp"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.sqlite3"

    @property
    def cors_list(self) -> List[str]:
        if not self.cors_origins or self.cors_origins.strip() == "*":
            return ["*"]
        return [x.strip() for x in self.cors_origins.split(",") if x.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
