export const API_BASE = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '')

async function parseResponse<T>(res: Response): Promise<T> {
  const contentType = res.headers.get('content-type') || ''
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      if (contentType.includes('application/json')) {
        const data = await res.json()
        detail = data.detail || JSON.stringify(data)
      } else {
        detail = await res.text()
      }
    } catch {}
    throw new Error(detail)
  }
  if (contentType.includes('application/json')) return res.json() as Promise<T>
  const text = await res.text()
  throw new Error(`后端没有返回 JSON，请检查 VITE_API_BASE 是否指向 Render 后端。返回：${text.slice(0, 180)}`)
}

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`)
  return parseResponse<T>(res)
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  })
  return parseResponse<T>(res)
}

export async function uploadAssets(files: FileList): Promise<AssetItem[]> {
  const form = new FormData()
  Array.from(files).forEach(file => form.append('files', file))
  const res = await fetch(`${API_BASE}/api/assets`, { method: 'POST', body: form })
  return parseResponse<AssetItem[]>(res)
}

export interface GeneratedCopy {
  title: string
  hook: string
  script: string
  description: string
  tags: string[]
  shots: string[]
  kb_refs: string[]
}

export interface TTSVoice { id: string; name: string; provider: string; language: string; note?: string }
export interface TTSResponse { file_url: string; file_name: string; duration_seconds: number; warning?: string }
export interface AssetItem { id: string; filename: string; original_name: string; kind: 'image' | 'video'; url: string; size_bytes: number; created_at: string }
export interface ComposeResponse { video_url: string; video_name: string; subtitle_url?: string; audio_url?: string; duration_seconds: number; warnings: string[] }
export interface CoverResponse { cover_url: string; cover_name: string; prompt: string }
export interface PublishPackageResponse { package_url: string; package_name: string; status: string; checklist: string[] }

export interface InspirationExtractResponse {
  status: string
  source_name: string
  transcript: string
  summary: string
  structure: string[]
  hooks: string[]
  selling_points: string[]
  warnings: string[]
  collected_asset_id?: string
  collected_video_name?: string
  collected_video_url?: string
  collector_status?: string
}

export interface EditPlanResponse {
  rhythm: string
  timeline: string[]
  broll_keywords: string[]
  subtitle_style: string
  music_style: string
  cover_ideas: string[]
  warnings: string[]
}

export interface AdMetric { name: string; value: string; status: string }
export interface AdAnalysisResponse {
  decision: string
  confidence: number
  suggested_budget: string
  target_audience: string[]
  metrics: AdMetric[]
  alerts: string[]
  optimization_tips: string[]
  next_actions: string[]
}

export interface VoiceSegment {
  text: string
  emotion: string
  speed_ratio: number
  volume_ratio: number
  pitch_ratio: number
  pause_after_ms: number
}

export interface VoiceDirectorResponse {
  style: string
  director_notes: string[]
  rewritten_script: string
  segments: VoiceSegment[]
}

export interface VideoEditChatResponse {
  assistant_message: string
  summary: string
  actions: string[]
  new_video_url?: string
  new_video_name?: string
  warnings: string[]
}

export interface PlatformPublishResponse {
  platform: string
  status: string
  message: string
  checklist: string[]
}

export interface TrendItem {
  title: string
  reason: string
  heat: number
  angle: string
  suggested_hook: string
  risk: string
}
export interface TrendRadarResponse {
  summary: string
  hot_topics: TrendItem[]
  content_angles: string[]
  shooting_suggestions: string[]
  monitor_keywords: string[]
  next_actions: string[]
}

export interface CompetitorAccount {
  name: string
  platform: string
  url: string
  positioning: string
  notes: string
}

export interface ShotTask {
  scene: string
  duration: string
  camera: string
  content: string
  props: string
  priority: string
}
export interface ShootingPlanResponse {
  summary: string
  shot_tasks: ShotTask[]
  broll_list: string[]
  teleprompter: string[]
  checklist: string[]
}

export interface SubtitleKeyword {
  word: string
  reason: string
  effect: string
}
export interface SubtitleEmphasisResponse {
  template: string
  keywords: SubtitleKeyword[]
  srt_tips: string[]
  cover_text_options: string[]
}

export interface GrowthMetricInput {
  views: number
  likes: number
  comments: number
  shares: number
  follows: number
  leads: number
  completion_rate: number
  spend: number
  hours_after_publish: number
}
export interface GrowthDecisionResponse {
  score: number
  decision: string
  reason: string
  recommended_budget: string
  actions: string[]
  alerts: string[]
  next_test: string[]
}

export interface MemoryContextResponse {
  workspace_id: string
  memory_enabled: boolean
  storage: string
  profile: Record<string, any>
  competitors: any[]
  videos: any[]
  trends: any[]
  scripts: any[]
  events: any[]
  learning_summary: string
}

export interface CustomerProfileSave {
  industry: string
  audience: string
  selling_points: string
  style: string
  lead_region: string
  conversion_goal: string
  trend_keywords: string
}
