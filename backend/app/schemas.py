from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field


class CopyRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=500)
    industry: str = Field(default='', max_length=120)
    audience: str = Field(default='', max_length=200)
    selling_points: str = Field(default='', max_length=4000)
    style: str = Field(default='老板口播、真实、有信任感、短平快', max_length=200)
    duration_seconds: int = Field(default=35, ge=10, le=180)
    knowledge_examples: List[str] = Field(default_factory=list, max_length=20)
    api_key: Optional[str] = Field(default=None, repr=False)


class GeneratedCopy(BaseModel):
    title: str
    hook: str
    script: str
    description: str
    tags: List[str]
    shots: List[str]
    kb_refs: List[str] = Field(default_factory=list)


class KnowledgeCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    content: str = Field(..., min_length=1, max_length=5000)
    tags: List[str] = Field(default_factory=list)


class KnowledgeItem(BaseModel):
    id: int
    title: str
    content: str
    tags: List[str]
    created_at: str


class TTSVoice(BaseModel):
    id: str
    name: str
    provider: str = 'volcengine'
    language: str = 'zh-CN'
    note: str = ''


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)
    voice: Optional[str] = None
    rate: Optional[str] = None


class AudioSegmentTiming(BaseModel):
    index: int
    text: str
    start: float
    end: float
    duration: float


class TTSResponse(BaseModel):
    file_url: str
    file_name: str
    duration_seconds: float
    warning: Optional[str] = None
    segments: List[AudioSegmentTiming] = Field(default_factory=list)




class VoiceSegment(BaseModel):
    text: str = Field(..., min_length=1, max_length=800)
    emotion: str = Field(default='自然可信', max_length=80)
    speed_ratio: float = Field(default=1.0, ge=0.5, le=2.0)
    volume_ratio: float = Field(default=1.0, ge=0.2, le=3.0)
    pitch_ratio: float = Field(default=1.0, ge=0.5, le=2.0)
    pause_after_ms: int = Field(default=350, ge=0, le=3000)


class VoiceDirectorRequest(BaseModel):
    script: str = Field(..., min_length=1, max_length=12000)
    style: str = Field(default='老板压迫感', max_length=120)
    intensity: str = Field(default='标准', max_length=40)
    target_seconds: int = Field(default=35, ge=5, le=180)
    audience: str = Field(default='', max_length=200)
    selling_points: str = Field(default='', max_length=4000)


class VoiceDirectorResponse(BaseModel):
    style: str
    director_notes: List[str] = Field(default_factory=list)
    rewritten_script: str
    segments: List[VoiceSegment]


class TTSSegmentsRequest(BaseModel):
    segments: List[VoiceSegment] = Field(..., min_length=1, max_length=30)
    voice: Optional[str] = None
    overall_rate: Optional[str] = None


class AssetItem(BaseModel):
    id: str
    filename: str
    original_name: str
    kind: str
    url: str
    size_bytes: int
    created_at: str
    # 素材文件夹：self=自己拍的，provided=别人提供，image=图片素材，collected=采集视频，ai=AI生成图
    folder: str = 'self'
    source_type: str = 'upload'


class ComposeAssetClip(BaseModel):
    asset_id: str = Field(..., min_length=1, max_length=200)
    order: int = Field(default=0, ge=0, le=999)
    kind: str = Field(default='', max_length=20)
    image_seconds: float = Field(default=2.8, ge=0.0, le=20)
    video_start: float = Field(default=0.0, ge=0, le=7200)
    video_end: float = Field(default=0.0, ge=0, le=7200)


class ComposeRequest(BaseModel):
    title: str = Field(default='', max_length=200)
    script: str = Field(..., min_length=1, max_length=5000)
    asset_ids: List[str] = Field(default_factory=list)
    asset_plan: List[ComposeAssetClip] = Field(default_factory=list)
    audio_file_name: Optional[str] = None
    duration_seconds: int = Field(default=35, ge=5, le=180)
    voice: Optional[str] = None
    rate: Optional[str] = None
    subtitle_size: int = Field(default=18, ge=12, le=36)
    subtitle_margin_v: int = Field(default=70, ge=20, le=320)
    subtitle_position: str = Field(default='bottom_safe', max_length=40)
    subtitle_style_preset: str = Field(default='douyin_boss', max_length=40)
    subtitle_keywords: str = Field(default='', max_length=500)
    subtitle_segments: List[AudioSegmentTiming] = Field(default_factory=list)


class ComposeResponse(BaseModel):
    video_url: str
    video_name: str
    subtitle_url: Optional[str] = None
    audio_url: Optional[str] = None
    duration_seconds: float
    warnings: List[str] = Field(default_factory=list)


class InspirationExtractRequest(BaseModel):
    asset_id: Optional[str] = None
    source_url: str = ''
    manual_text: str = ''


class InspirationExtractResponse(BaseModel):
    status: str
    source_name: str = ''
    transcript: str = ''
    summary: str = ''
    structure: List[str] = Field(default_factory=list)
    hooks: List[str] = Field(default_factory=list)
    selling_points: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    collected_asset_id: Optional[str] = None
    collected_video_name: Optional[str] = None
    collected_video_url: Optional[str] = None
    collector_status: str = ''


class RewriteFromInspirationRequest(BaseModel):
    reference_text: str = Field(..., min_length=1, max_length=12000)
    industry: str = Field(default='', max_length=120)
    audience: str = Field(default='', max_length=200)
    selling_points: str = Field(default='', max_length=4000)
    style: str = Field(default='老板口播、真实可信、强转化', max_length=200)
    duration_seconds: int = Field(default=35, ge=10, le=180)


class EditPlanRequest(BaseModel):
    title: str = ''
    script: str
    asset_summary: str = ''
    duration_seconds: int = Field(default=35, ge=5, le=180)


class EditPlanResponse(BaseModel):
    rhythm: str
    timeline: List[str]
    broll_keywords: List[str]
    subtitle_style: str
    music_style: str
    cover_ideas: List[str]
    warnings: List[str] = Field(default_factory=list)


class CoverRequest(BaseModel):
    title: str
    hook: str = ''
    subtitle: str = ''
    brand: str = ''
    source_asset_id: Optional[str] = None
    source_file_name: Optional[str] = None
    background_url: str = ''
    template: str = 'douyin'


class CoverResponse(BaseModel):
    cover_url: str
    cover_name: str
    prompt: str


class ImageGenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=4, max_length=2000)
    title: str = Field(default='', max_length=120)
    style: str = Field(default='精美商业短视频封面背景，真实感，高级质感', max_length=300)
    size: str = Field(default='2K', max_length=40)
    quality: str = Field(default='high', max_length=40)


class ImageGenerateResponse(BaseModel):
    image_url: str
    image_name: str
    prompt: str
    provider: str
    model: str
    warnings: List[str] = Field(default_factory=list)


class PublishPackageRequest(BaseModel):
    title: str
    description: str
    tags: List[str] = Field(default_factory=list)
    video_file_name: Optional[str] = None
    cover_file_name: Optional[str] = None


class PublishPackageResponse(BaseModel):
    package_url: str
    package_name: str
    status: str
    checklist: List[str]


class AdAnalysisRequest(BaseModel):
    title: str = ''
    script: str
    budget: float = Field(default=300, ge=0, le=100000)
    objective: str = Field(default='线索/咨询', max_length=100)
    industry: str = Field(default='', max_length=120)


class AdMetric(BaseModel):
    name: str
    value: str
    status: str


class AdAnalysisResponse(BaseModel):
    decision: str
    confidence: float
    suggested_budget: str
    target_audience: List[str]
    metrics: List[AdMetric]
    alerts: List[str]
    optimization_tips: List[str]
    next_actions: List[str]




class CollectorCookieStatus(BaseModel):
    enabled: bool
    cookie_upload_enabled: bool
    cookie_file: str
    cookie_exists: bool
    cookie_size_bytes: int
    hint: str


class CollectorCookieUploadRequest(BaseModel):
    cookie_text: str = Field(..., min_length=20, max_length=200000)


class ApiError(BaseModel):
    detail: Any


class CopyRefineRequest(BaseModel):
    title: str = Field(default='', max_length=200)
    hook: str = Field(default='', max_length=1000)
    script: str = Field(..., min_length=1, max_length=12000)
    description: str = Field(default='', max_length=5000)
    tags: List[str] = Field(default_factory=list)
    shots: List[str] = Field(default_factory=list)
    instruction: str = Field(..., min_length=1, max_length=2000)
    industry: str = Field(default='', max_length=120)
    audience: str = Field(default='', max_length=200)
    selling_points: str = Field(default='', max_length=4000)


class VideoEditChatRequest(BaseModel):
    video_file_name: Optional[str] = None
    instruction: str = Field(..., min_length=1, max_length=2000)
    title: str = Field(default='', max_length=200)
    script: str = Field(default='', max_length=12000)
    asset_summary: str = Field(default='', max_length=2000)


class VideoEditChatResponse(BaseModel):
    assistant_message: str
    summary: str
    actions: List[str] = Field(default_factory=list)
    new_video_url: Optional[str] = None
    new_video_name: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)


class PlatformPublishRequest(BaseModel):
    platform: str = Field(default='douyin', max_length=80)
    title: str = Field(default='', max_length=200)
    description: str = Field(default='', max_length=5000)
    tags: List[str] = Field(default_factory=list)
    video_file_name: Optional[str] = None
    cover_file_name: Optional[str] = None


class PlatformPublishResponse(BaseModel):
    platform: str
    status: str
    message: str
    checklist: List[str] = Field(default_factory=list)



class TrendRadarRequest(BaseModel):
    industry: str = Field(default='', max_length=120)
    audience: str = Field(default='', max_length=200)
    region: str = Field(default='', max_length=160)
    keywords: List[str] = Field(default_factory=list, max_length=20)
    competitor_notes: str = Field(default='', max_length=5000)


class TrendItem(BaseModel):
    title: str
    reason: str
    heat: int = Field(default=60, ge=0, le=100)
    angle: str = ''
    suggested_hook: str = ''
    risk: str = ''


class TrendRadarResponse(BaseModel):
    summary: str
    hot_topics: List[TrendItem] = Field(default_factory=list)
    content_angles: List[str] = Field(default_factory=list)
    shooting_suggestions: List[str] = Field(default_factory=list)
    monitor_keywords: List[str] = Field(default_factory=list)
    next_actions: List[str] = Field(default_factory=list)


class CompetitorAccount(BaseModel):
    name: str = Field(default='', max_length=120)
    platform: str = Field(default='douyin', max_length=80)
    url: str = Field(default='', max_length=1000)
    positioning: str = Field(default='', max_length=500)
    notes: str = Field(default='', max_length=2000)


class ShootingPlanRequest(BaseModel):
    title: str = Field(default='', max_length=200)
    script: str = Field(default='', max_length=12000)
    industry: str = Field(default='', max_length=120)
    audience: str = Field(default='', max_length=200)
    selling_points: str = Field(default='', max_length=4000)
    available_assets: str = Field(default='', max_length=3000)
    duration_seconds: int = Field(default=35, ge=5, le=180)


class ShotTask(BaseModel):
    scene: str
    duration: str
    camera: str
    content: str
    props: str = ''
    priority: str = '必拍'


class ShootingPlanResponse(BaseModel):
    summary: str
    shot_tasks: List[ShotTask] = Field(default_factory=list)
    broll_list: List[str] = Field(default_factory=list)
    teleprompter: List[str] = Field(default_factory=list)
    checklist: List[str] = Field(default_factory=list)


class SubtitleEmphasisRequest(BaseModel):
    script: str = Field(..., min_length=1, max_length=12000)
    style: str = Field(default='短视频强转化字幕', max_length=120)
    brand_color: str = Field(default='#2f6bff', max_length=40)


class SubtitleKeyword(BaseModel):
    word: str
    reason: str = ''
    effect: str = '放大高亮'


class SubtitleEmphasisResponse(BaseModel):
    template: str
    keywords: List[SubtitleKeyword] = Field(default_factory=list)
    srt_tips: List[str] = Field(default_factory=list)
    cover_text_options: List[str] = Field(default_factory=list)


class GrowthMetricInput(BaseModel):
    views: int = Field(default=0, ge=0)
    likes: int = Field(default=0, ge=0)
    comments: int = Field(default=0, ge=0)
    shares: int = Field(default=0, ge=0)
    follows: int = Field(default=0, ge=0)
    leads: int = Field(default=0, ge=0)
    completion_rate: float = Field(default=0, ge=0, le=100)
    spend: float = Field(default=0, ge=0, le=1000000)
    hours_after_publish: float = Field(default=3, ge=0, le=720)


class GrowthDecisionRequest(BaseModel):
    title: str = Field(default='', max_length=200)
    script: str = Field(default='', max_length=12000)
    industry: str = Field(default='', max_length=120)
    objective: str = Field(default='线索/咨询', max_length=120)
    metrics: GrowthMetricInput = Field(default_factory=GrowthMetricInput)


class GrowthDecisionResponse(BaseModel):
    score: int = Field(default=0, ge=0, le=100)
    decision: str
    reason: str
    recommended_budget: str
    actions: List[str] = Field(default_factory=list)
    alerts: List[str] = Field(default_factory=list)
    next_test: List[str] = Field(default_factory=list)


class CustomerProfileSave(BaseModel):
    industry: str = Field(default='', max_length=120)
    audience: str = Field(default='', max_length=2000)
    selling_points: str = Field(default='', max_length=2000)
    style: str = Field(default='', max_length=1000)
    lead_region: str = Field(default='', max_length=200)
    conversion_goal: str = Field(default='', max_length=200)
    trend_keywords: str = Field(default='', max_length=1000)
    # 行业获客档案扩展字段：用于长期复用到文案、图文、拍摄和私域承接。
    business_positioning: str = Field(default='', max_length=500)
    listening_keywords: str = Field(default='', max_length=3000)
    customer_segments: str = Field(default='', max_length=3000)
    private_domain_assets: str = Field(default='', max_length=3000)
    content_pillars: str = Field(default='', max_length=3000)
    shooting_brief: str = Field(default='', max_length=3000)
    report_delivery: str = Field(default='', max_length=1000)


class MemoryEventInput(BaseModel):
    event_type: str = Field(default='note', max_length=120)
    title: str = Field(default='', max_length=300)
    payload: dict = Field(default_factory=dict)


class CompetitorVideoSave(BaseModel):
    source_name: str = Field(default='', max_length=300)
    platform: str = Field(default='douyin', max_length=80)
    source_url: str = Field(default='', max_length=1200)
    manual_text: str = Field(default='', max_length=12000)
    transcript: str = Field(default='', max_length=20000)
    summary: str = Field(default='', max_length=5000)
    structure: List[str] = Field(default_factory=list)
    hooks: List[str] = Field(default_factory=list)
    selling_points: List[str] = Field(default_factory=list)
    status: str = Field(default='', max_length=120)
    collector_status: str = Field(default='', max_length=120)
    collected_video_url: str = Field(default='', max_length=1200)
    raw: dict = Field(default_factory=dict)


class MemoryContextResponse(BaseModel):
    workspace_id: str
    memory_enabled: bool
    storage: str
    profile: dict = Field(default_factory=dict)
    competitors: List[dict] = Field(default_factory=list)
    videos: List[dict] = Field(default_factory=list)
    trends: List[dict] = Field(default_factory=list)
    scripts: List[dict] = Field(default_factory=list)
    events: List[dict] = Field(default_factory=list)
    learning_summary: str = ''


class ScriptVersionSave(BaseModel):
    title: str = Field(default='', max_length=300)
    hook: str = Field(default='', max_length=2000)
    script: str = Field(default='', max_length=20000)
    description: str = Field(default='', max_length=8000)
    tags: List[str] = Field(default_factory=list)
    source: str = Field(default='manual', max_length=120)
    raw: dict = Field(default_factory=dict)



class LeadAcquisitionRequest(BaseModel):
    industry: str = Field(default='', max_length=160)
    audience: str = Field(default='', max_length=2000)
    selling_points: str = Field(default='', max_length=6000)
    style: str = Field(default='', max_length=1000)
    lead_region: str = Field(default='', max_length=2000)
    conversion_goal: str = Field(default='', max_length=2000)
    channels: List[str] = Field(default_factory=list, max_length=20)
    data_sources: List[str] = Field(default_factory=list, max_length=20)
    competitor_accounts: List[str] = Field(default_factory=list, max_length=50)
    search_query_import: str = Field(default='', max_length=12000)
    fixed_options: str = Field(default='', max_length=3000)
    competitor_notes: str = Field(default='', max_length=6000)
    trend_keywords: str = Field(default='', max_length=6000)
    existing_context: str = Field(default='', max_length=16000)
    business_positioning: str = Field(default='', max_length=500)
    listening_keywords: str = Field(default='', max_length=3000)
    customer_segments: str = Field(default='', max_length=3000)
    private_domain_assets: str = Field(default='', max_length=3000)
    content_pillars: str = Field(default='', max_length=3000)
    shooting_brief: str = Field(default='', max_length=3000)
    report_delivery: str = Field(default='', max_length=1000)


class LeadChannelPlaybook(BaseModel):
    channel: str
    goal: str
    actions: List[str] = Field(default_factory=list)
    automation: List[str] = Field(default_factory=list)
    required_inputs: List[str] = Field(default_factory=list)
    success_metric: str = ''


class LeadDataSource(BaseModel):
    name: str
    status: str = ''
    purpose: str = ''
    required_fields: List[str] = Field(default_factory=list)
    next_step: str = ''


class LeadInterceptionOpportunity(BaseModel):
    score: int = Field(default=70, ge=0, le=100)
    source: str = ''
    keyword: str = ''
    intent: str = ''
    action: str = ''
    asset: str = ''


class LeadAcquisitionPlanResponse(BaseModel):
    overview: str
    audience_segments: List[str] = Field(default_factory=list)
    channel_playbook: List[LeadChannelPlaybook] = Field(default_factory=list)
    listening_keywords: List[str] = Field(default_factory=list)
    content_triggers: List[str] = Field(default_factory=list)
    reply_templates: List[str] = Field(default_factory=list)
    private_domain_sop: List[str] = Field(default_factory=list)
    daily_automation_tasks: List[str] = Field(default_factory=list)
    next_actions: List[str] = Field(default_factory=list)
    content_matrix: List[str] = Field(default_factory=list)
    lead_magnets: List[str] = Field(default_factory=list)
    shooting_prompts: List[str] = Field(default_factory=list)
    required_integrations: List[str] = Field(default_factory=list)
    data_sources: List[LeadDataSource] = Field(default_factory=list)
    interception_opportunities: List[LeadInterceptionOpportunity] = Field(default_factory=list)
    monitoring_sop: List[str] = Field(default_factory=list)
    compliance_notes: List[str] = Field(default_factory=list)


class DigitalHumanCreateRequest(BaseModel):
    avatar_asset_id: Optional[str] = None
    avatar_file_name: Optional[str] = None
    audio_file_name: str = Field(..., min_length=1, max_length=500)
    driver_video_asset_id: Optional[str] = None
    title: str = Field(default='', max_length=200)
    script: str = Field(default='', max_length=12000)
    engine: str = Field(default='auto', max_length=80)
    # 使用火山即梦/OmniHuman 时可选；不填则使用环境变量里的默认 action。
    jimeng_model: str = Field(default='omnihuman15', max_length=80)
    consent_confirmed: bool = False


class DigitalHumanCreateResponse(BaseModel):
    status: str
    engine: str
    message: str
    video_url: Optional[str] = None
    video_name: Optional[str] = None
    job_id: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)
    raw: dict = Field(default_factory=dict)


class AutoCollectorRunRequest(BaseModel):
    seed_links: str = Field(default='', max_length=12000)
    include_account_urls: bool = True
    limit: int = Field(default=3, ge=1, le=8)
    learn_goal: str = Field(default='学习同行博主的钩子公式、情绪推进、剪辑节奏和转化逻辑；只迁移方法，不模仿原文、不搬运素材。', max_length=1000)
    token: str = Field(default='', max_length=300)


class AutoCollectorStatusResponse(BaseModel):
    enabled: bool
    interval_minutes: int
    run_limit: int
    seed_links_configured: bool
    cron_token_enabled: bool
    memory_enabled: bool
    competitors_count: int
    recent_learning_events: List[dict] = Field(default_factory=list)
    recent_videos: List[dict] = Field(default_factory=list)


class AutoCollectorRunResponse(BaseModel):
    ok: bool
    mode: str
    sources_count: int
    discovered_count: int
    collected_count: int
    saved_event_id: Optional[str] = None
    learning: dict = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)


class OneClickGenerateRequest(BaseModel):
    industry: str = Field(default='', max_length=160)
    audience: str = Field(default='', max_length=2000)
    selling_points: str = Field(default='', max_length=6000)
    style: str = Field(default='老板口播、真实可信、抖音强钩子', max_length=300)
    duration_seconds: int = Field(default=35, ge=10, le=180)
    goal: str = Field(default='私信咨询 / 加微信 / 留资', max_length=200)
    output_type: str = Field(default='digital_human', max_length=80)
    material_mode: str = Field(default='selected_assets', max_length=80)
    selected_asset_names: List[str] = Field(default_factory=list, max_length=50)
    reference_text: str = Field(default='', max_length=12000)
    instruction: str = Field(default='', max_length=3000)


class OneClickGenerateResponse(BaseModel):
    project_title: str
    summary: str
    copy: GeneratedCopy
    voice_director: VoiceDirectorResponse
    shooting_plan: ShootingPlanResponse
    edit_plan: EditPlanResponse
    subtitle: SubtitleEmphasisResponse
    image_prompts: List[str] = Field(default_factory=list)
    publish_title: str = ''
    publish_description: str = ''
    next_actions: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    raw: dict = Field(default_factory=dict)


class OneClickChatRequest(BaseModel):
    instruction: str = Field(..., min_length=1, max_length=3000)
    current: OneClickGenerateResponse
    industry: str = Field(default='', max_length=160)
    audience: str = Field(default='', max_length=2000)
    selling_points: str = Field(default='', max_length=6000)




class GraphicPostImage(BaseModel):
    image_url: str
    image_name: str
    title: str
    caption: str
    role: str


class GraphicPostRequest(BaseModel):
    title: str = Field(default='', max_length=120)
    hook: str = Field(default='', max_length=300)
    script: str = Field(default='', max_length=12000)
    industry: str = Field(default='', max_length=160)
    audience: str = Field(default='', max_length=2000)
    selling_points: str = Field(default='', max_length=6000)
    style: str = Field(default='精美商业感、抖音图文、小红书收藏感', max_length=500)
    platform: str = Field(default='xiaohongshu', max_length=40)
    slide_count: int = Field(default=5, ge=3, le=8)
    cta: str = Field(default='想要完整清单，私信发你。', max_length=300)
    background_mode: str = Field(default='asset', max_length=40)
    source_asset_id: Optional[str] = None
    background_url: str = Field(default='', max_length=1500)
    image_prompt: str = Field(default='', max_length=3000)


class GraphicPostResponse(BaseModel):
    package_title: str
    platform: str
    images: List[GraphicPostImage] = Field(default_factory=list)
    publish_title: str = ''
    publish_description: str = ''
    checklist: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class ModelStatusResponse(BaseModel):
    ai_provider: str
    ai_text_model: str
    ai_backup_provider: str
    ai_backup_model: str
    qwen_configured: bool
    gemini_configured: bool
    deepseek_configured: bool
    asr_provider: str
    asr_model: str
    image_provider: str
    image_model: str
    image_edit_model: str


class HeatRadarAccountInput(BaseModel):
    id: str = ''
    name: str = ''
    platform: str = '抖音'
    url: str = ''
    tags: str = ''
    notes: str = ''
    pinned: bool = False
    created_at: str = ''


class HeatRadarRunRequest(BaseModel):
    accounts: List[HeatRadarAccountInput] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    limit_per_account: int = Field(default=3, ge=1, le=6)
    include_saved_accounts: bool = True
    save_to_memory: bool = True
    token: str = ''


class HeatRadarItem(BaseModel):
    id: str = ''
    date: str = ''
    platform: str = ''
    account_id: str = ''
    account_name: str = ''
    title: str = ''
    description: str = ''
    url: str = ''
    published_at: str = ''
    collected_at: str = ''
    like_count: int = 0
    comment_count: int = 0
    favorite_count: int = 0
    share_count: int = 0
    view_count: int = 0
    heat_score: int = 0
    keyword: str = ''
    tags: List[str] = Field(default_factory=list)
    thumbnail_url: str = ''
    source_mode: str = ''
    warnings: List[str] = Field(default_factory=list)
    raw: Dict[str, Any] = Field(default_factory=dict)




class HeatRadarRewriteRequest(BaseModel):
    heat_items: List[Dict[str, Any]] = Field(default_factory=list, max_length=10)
    industry: str = Field(default='', max_length=160)
    audience: str = Field(default='', max_length=2000)
    selling_points: str = Field(default='', max_length=6000)
    conversion_goal: str = Field(default='私信咨询 / 领取资料包 / 加微信顾问沟通', max_length=1000)
    lead_magnet: str = Field(default='', max_length=500)
    style: str = Field(default='老板口播、真实可信、强钩子、强转化', max_length=300)
    target_duration_seconds: int = Field(default=35, ge=10, le=180)
    platform: str = Field(default='douyin', max_length=80)


class HeatRadarRewriteVariant(BaseModel):
    source_topic: str = ''
    target_audience: str = ''
    customer_intent: str = ''
    content_goal: str = ''
    conversion_goal: str = ''
    lead_magnet: str = ''
    title: str = ''
    hook: str = ''
    script: str = ''
    caption: str = ''
    tags: List[str] = Field(default_factory=list)
    shots: List[str] = Field(default_factory=list)
    imitation_notes: List[str] = Field(default_factory=list)
    differentiation: List[str] = Field(default_factory=list)
    risk_notes: List[str] = Field(default_factory=list)
    source_evidence: List[str] = Field(default_factory=list)
    adaptation_map: List[str] = Field(default_factory=list)


class HeatRadarRewriteResponse(BaseModel):
    overview: str = ''
    chosen_target: str = ''
    target_reason: str = ''
    content_objective: str = ''
    primary_intent: str = ''
    lead_magnet: str = ''
    rewrite_strategy: List[str] = Field(default_factory=list)
    source_evidence: List[str] = Field(default_factory=list)
    variants: List[HeatRadarRewriteVariant] = Field(default_factory=list)
    publish_checklist: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)

class HeatRadarRunResponse(BaseModel):
    ok: bool = True
    source_mode: str = ''
    top_mode: str = ''
    fallback_used: bool = False
    accounts_count: int = 0
    collected_count: int = 0
    saved_count: int = 0
    top_items: List[Dict[str, Any]] = Field(default_factory=list)
    analysis: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    next_actions: List[str] = Field(default_factory=list)
