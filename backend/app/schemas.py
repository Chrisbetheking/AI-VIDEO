from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field


class CopyRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=500)
    industry: str = Field(default='', max_length=120)
    audience: str = Field(default='', max_length=200)
    selling_points: str = Field(default='', max_length=1000)
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


class TTSResponse(BaseModel):
    file_url: str
    file_name: str
    duration_seconds: float
    warning: Optional[str] = None




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
    selling_points: str = Field(default='', max_length=1000)


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


class ComposeRequest(BaseModel):
    title: str = Field(default='', max_length=200)
    script: str = Field(..., min_length=1, max_length=5000)
    asset_ids: List[str] = Field(default_factory=list)
    audio_file_name: Optional[str] = None
    duration_seconds: int = Field(default=35, ge=5, le=180)
    voice: Optional[str] = None
    rate: Optional[str] = None


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
    selling_points: str = Field(default='', max_length=1000)
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


class CoverResponse(BaseModel):
    cover_url: str
    cover_name: str
    prompt: str


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
    selling_points: str = Field(default='', max_length=1000)


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
    selling_points: str = Field(default='', max_length=1000)
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
