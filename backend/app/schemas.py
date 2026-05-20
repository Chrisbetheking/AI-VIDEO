from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class CopyRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=500)
    industry: str = Field(default="", max_length=120)
    audience: str = Field(default="", max_length=200)
    selling_points: str = Field(default="", max_length=1000)
    style: str = Field(default="老板口播、真实、有信任感、短平快", max_length=200)
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
    title: str = Field(default="", max_length=200)
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


class AdAnalysisRequest(BaseModel):
    title: str = ""
    script: str
    budget: float = Field(default=300, ge=0, le=100000)
    objective: str = Field(default="线索/咨询", max_length=100)
    industry: str = Field(default="", max_length=120)


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
