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
