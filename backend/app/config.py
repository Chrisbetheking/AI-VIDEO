from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    # AI 大脑：主模型用阿里百炼/Qwen，备用可用 Gemini，DeepSeek 保留兼容
    ai_provider: str = 'qwen'
    ai_text_model: str = 'qwen-max'
    ai_backup_provider: str = 'gemini'
    ai_backup_model: str = 'gemini-2.5-pro'

    # 阿里云百炼 / DashScope：Qwen 文案、分镜、AI 修改、Qwen-Image、ASR
    dashscope_api_key: str = ''
    dashscope_base_url: str = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
    qwen_model: str = 'qwen-max'
    asr_provider: str = 'volcengine'
    asr_model: str = 'doubao-record-file-recognition-2.0'
    image_provider: str = 'volcengine'
    image_model: str = 'doubao-seedream-5-0-260128'
    image_edit_model: str = 'doubao-seedream-5-0-260128'
    image_backup_provider: str = 'dashscope'
    image_backup_model: str = 'qwen-image'
    image_base_url: str = 'https://ark.cn-beijing.volces.com/api/v3'
    image_size: str = '2K'
    image_quality: str = 'high'
    volcengine_image_api_key: str = ''

    # Google Gemini：复杂分析/素材理解/备用强模型
    gemini_api_key: str = ''
    gemini_base_url: str = 'https://generativelanguage.googleapis.com/v1beta'
    gemini_model: str = 'gemini-2.5-pro'

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
    volcengine_tts_endpoint: str = 'https://openspeech.bytedance.com/api/v3/tts/unidirectional'
    volcengine_app_id: str = ''
    volcengine_access_token: str = ''
    # 声音复刻 ICL 2.0 字符版一般使用 volcano_icl + seed-icl-2.0；普通 TTS 音色可按控制台文档改回 volcano_tts。
    volcengine_cluster: str = 'volcano_icl'
    volcengine_resource_id: str = 'seed-icl-2.0'
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

    # 尽力视频采集：抖音分享口令/短链会先采公开视频，失败则降级为文案钩子采集
    enable_video_collector: bool = True
    enable_ytdlp_collector: bool = True
    collector_max_mb: int = 80
    collector_timeout_seconds: int = 180
    collector_user_agent: str = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'
    # 抖音采集增强：可上传/配置 Netscape cookies，解决 yt-dlp 提示 Fresh cookies needed
    # 推荐 Render Secret File 路径：/etc/secrets/douyin_cookies.txt
    collector_cookie_file: str = ''
    enable_collector_cookie_upload: bool = True
    collector_cookies_max_chars: int = 200000

    # 平台发布：先保留入口，等开放平台权限下来再接真实发布
    enable_platform_publish: bool = False


    # 后台自动采集/学习智能体：定时从竞品账号和种子链接里学习钩子结构，不照抄原文
    enable_auto_collector: bool = False
    auto_collector_interval_minutes: int = 720
    auto_collector_run_limit: int = 3
    auto_collector_seed_links: str = ''
    auto_collector_learn_goal: str = '学习同行博主的钩子公式、情绪推进、剪辑节奏和转化逻辑；只迁移方法，不模仿原文、不搬运素材。'
    auto_collector_cron_token: str = ''

    # 数字人：Render 默认只做静态头像预览；真实口型同步建议接 GPU Worker / API
    enable_digital_human: bool = True
    digital_human_engine: str = 'preview'
    digital_human_webhook_url: str = ''
    digital_human_webhook_token: str = ''
    digital_human_timeout_seconds: int = 900

    # 火山即梦 / OmniHuman 数字人 API（可选，正式口型同步用）
    # 一个火山账号 AK/SK 通常可调用已开通的多个即梦模型；调用时用 DIGITAL_HUMAN_ENGINE / 前端选择决定模型。
    jimeng_enabled: bool = False
    jimeng_access_key_id: str = ''
    jimeng_secret_access_key: str = ''
    jimeng_region: str = 'cn-north-1'
    jimeng_service: str = 'cv'
    jimeng_version: str = '2024-06-06'
    jimeng_endpoint: str = 'https://visual.volcengineapi.com'
    jimeng_poll_seconds: int = 8
    jimeng_max_wait_seconds: int = 900
    # 下面 action 名称以火山控制台 API Explorer 为准；我先按公开文档/接口名预置，可在环境变量覆盖。
    jimeng_omni15_submit_action: str = 'JimengRealmanAvatarPictureOmniV15SubmitTask'
    jimeng_omni15_get_action: str = 'JimengRealmanAvatarPictureOmniV15GetResult'
    jimeng_quick_submit_action: str = 'JimengRealmanAvatarPictureSubmitTask'
    jimeng_quick_get_action: str = 'JimengRealmanAvatarPictureGetResult'
    jimeng_video30_submit_action: str = 'JimengI2VFirstV30SubmitTask'
    jimeng_video30_get_action: str = 'JimengI2VFirstV30GetResult'
    # Render 免费实例不适合在 HTTP 请求里长时间等待数字人结果，默认只提交任务并返回 task_id。
    jimeng_wait_for_result: bool = False
    # 火山即梦 API 必填服务标识 req_key。不同 action 必须传对应 req_key。
    jimeng_omni15_req_key: str = 'jimeng_realman_avatar_picture_omni_v15'
    jimeng_quick_req_key: str = 'realman_avatar_picture_v2'
    jimeng_video30_req_key: str = 'jimeng_i2v_first_v30'


    # Supabase / AI 记忆库
    supabase_url: str = ''
    supabase_service_role_key: str = ''
    workspace_id: str = 'default'
    enable_learning_memory: bool = True
    industry_radar_auto_save: bool = True
    # 企业数据保护：开启后，核心表写 Supabase 失败会直接报错，不再悄悄降级成本地 JSON。
    core_storage_strict: bool = False
    # 企业素材保护：开启后，素材上传必须成功进入 R2，否则返回错误，避免本地临时文件丢失。
    require_r2_assets: bool = False

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

# Supabase / AI 记忆库：账号库、采集记录、行业档案、投流数据
# 不配置时自动降级为 Render 本地 JSON，适合调试；正式建议配置 Supabase。
