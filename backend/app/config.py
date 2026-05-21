from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    # DeepSeek：文案改写 / 标题 / 钩子 / 剪辑方案
    deepseek_api_key: str = ''
    deepseek_base_url: str = 'https://api.deepseek.com'
    deepseek_model: str = 'deepseek-chat'

    # 火山方舟 / 豆包：视频理解，推荐填控制台里创建的接入点 ID 或模型 ID
    ark_api_key: str = ''
    ark_base_url: str = 'https://ark.cn-beijing.volces.com/api/v3'
    ark_video_model: str = 'doubao-seed-2-0-lite'

    # 豆包语音 / 火山语音合成
    # 正式部署建议：TTS_PROVIDER=volcengine
    tts_provider: str = 'volcengine'
    tts_voice: str = 'default'
    tts_rate: str = '+0%'
    tts_voices_json: str = ''
    volcengine_tts_endpoint: str = 'https://openspeech.bytedance.com/api/v1/tts'
    volcengine_app_id: str = ''
    volcengine_access_token: str = ''
    volcengine_cluster: str = 'volcano_tts'
    volcengine_voice_type: str = ''
    volcengine_uid: str = 'ai-video-user'

    # 兼容本地 Demo；Render/Linux 上不要依赖 sapi
    allow_mock_tts: bool = False

    # Web / 文件 / 部署
    cors_origins: str = '*'
    app_data_dir: str = Field(default='./data')
    static_dir: str = Field(default='./static')
    max_upload_mb: int = 300

    # Cloudflare R2，可选但推荐正式版开启
    r2_account_id: str = ''
    r2_access_key_id: str = ''
    r2_secret_access_key: str = ''
    r2_bucket_name: str = ''
    r2_public_base_url: str = ''

    # 预留：抖音开放平台，第一版先生成发布包，暂不自动发布
    douyin_client_key: str = ''
    douyin_client_secret: str = ''
    douyin_redirect_uri: str = ''

    @property
    def data_dir(self) -> Path:
        path = Path(self.app_data_dir).resolve()
        path.mkdir(parents=True, exist_ok=True)
        (path / 'uploads').mkdir(parents=True, exist_ok=True)
        (path / 'outputs').mkdir(parents=True, exist_ok=True)
        (path / 'tmp').mkdir(parents=True, exist_ok=True)
        return path

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / 'uploads'

    @property
    def outputs_dir(self) -> Path:
        return self.data_dir / 'outputs'

    @property
    def tmp_dir(self) -> Path:
        return self.data_dir / 'tmp'

    @property
    def db_path(self) -> Path:
        return self.data_dir / 'app.sqlite3'

    @property
    def cors_list(self) -> List[str]:
        if not self.cors_origins or self.cors_origins.strip() == '*':
            return ['*']
        return [x.strip() for x in self.cors_origins.split(',') if x.strip()]

    @property
    def r2_enabled(self) -> bool:
        return all([
            self.r2_account_id.strip(),
            self.r2_access_key_id.strip(),
            self.r2_secret_access_key.strip(),
            self.r2_bucket_name.strip(),
        ])


@lru_cache
def get_settings() -> Settings:
    return Settings()
