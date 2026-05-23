const envApiBase = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '')
const defaultRenderApi = 'https://ai-video-u8jd.onrender.com'
const isLocal = typeof window !== 'undefined' && /^(localhost|127\.0\.0\.1)$/i.test(window.location.hostname)

// Cloudflare Pages 如果忘记配置 VITE_API_BASE，默认会请求当前 pages.dev 的 /api，
// 这就是素材库/配音常见 Failed to fetch 的来源。这里加一个生产兜底。
export const API_BASE = envApiBase || (isLocal ? 'http://localhost:8000' : defaultRenderApi)

function withTimeout(ms = 90000) {
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), ms)
  return { controller, timer }
}

async function parseResponse<T>(res: Response, url: string): Promise<T> {
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
    throw new Error(`${detail}\n请求地址：${url}`)
  }
  if (contentType.includes('application/json')) return res.json() as Promise<T>
  const text = await res.text()
  throw new Error(`后端没有返回 JSON，请检查 Cloudflare 的 VITE_API_BASE 是否指向 Render 后端。\n请求地址：${url}\n返回：${text.slice(0, 220)}`)
}

async function safeFetch<T>(url: string, init?: RequestInit, timeoutMs = 90000): Promise<T> {
  const { controller, timer } = withTimeout(timeoutMs)
  try {
    const res = await fetch(url, { ...init, signal: controller.signal })
    return parseResponse<T>(res, url)
  } catch (err: any) {
    if (err?.name === 'AbortError') {
      throw new Error(`请求超时：${url}\nRender 免费实例可能冷启动、内存爆掉或接口耗时过长。`)
    }
    const msg = err?.message || String(err)
    if (msg === 'Failed to fetch') {
      throw new Error(`无法连接后端：${url}\n请检查 Render 服务是否正常、Cloudflare VITE_API_BASE 是否为 ${defaultRenderApi}、CORS_ORIGINS 是否允许当前前端域名。`)
    }
    throw err
  } finally {
    window.clearTimeout(timer)
  }
}

export async function apiGet<T>(path: string): Promise<T> {
  const url = `${API_BASE}${path}`
  return safeFetch<T>(url)
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const url = `${API_BASE}${path}`
  return safeFetch<T>(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  })
}

export async function uploadAssets(files: FileList): Promise<AssetItem[]> {
  const form = new FormData()
  Array.from(files).forEach(file => form.append('files', file))
  const url = `${API_BASE}/api/assets`
  return safeFetch<AssetItem[]>(url, { method: 'POST', body: form }, 180000)
}

export async function deleteAsset(assetId: string): Promise<{ok: boolean; deleted: string[]; warnings: string[]}> {
  const url = `${API_BASE}/api/assets/${encodeURIComponent(assetId)}`
  return safeFetch<{ok: boolean; deleted: string[]; warnings: string[]}>(url, { method: 'DELETE' })
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


export interface CollectorCookieStatus {
  enabled: boolean
  cookie_upload_enabled: boolean
  cookie_file: string
  cookie_exists: boolean
  cookie_size_bytes: number
  hint: string
}

export async function getCollectorStatus(): Promise<CollectorCookieStatus> {
  return apiGet<CollectorCookieStatus>('/api/collector/status')
}

export async function uploadCollectorCookies(cookie_text: string): Promise<CollectorCookieStatus> {
  return apiPost<CollectorCookieStatus>('/api/collector/cookies', { cookie_text })
}
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


export interface LeadChannelPlaybook {
  channel: string
  goal: string
  actions: string[]
  automation: string[]
  required_inputs: string[]
  success_metric: string
}

export interface LeadAcquisitionPlanResponse {
  overview: string
  audience_segments: string[]
  channel_playbook: LeadChannelPlaybook[]
  listening_keywords: string[]
  content_triggers: string[]
  reply_templates: string[]
  private_domain_sop: string[]
  daily_automation_tasks: string[]
  next_actions: string[]
}

export interface DigitalHumanCreateRequest {
  avatar_asset_id?: string
  avatar_file_name?: string
  audio_file_name: string
  driver_video_asset_id?: string
  title?: string
  script?: string
  engine?: string
  jimeng_model?: string
  consent_confirmed: boolean
}

export interface DigitalHumanCreateResponse {
  status: string
  engine: string
  message: string
  video_url?: string
  video_name?: string
  job_id?: string
  warnings: string[]
  raw?: Record<string, any>
}

export interface AutoCollectorStatusResponse {
  enabled: boolean
  interval_minutes: number
  run_limit: number
  seed_links_configured: boolean
  cron_token_enabled: boolean
  memory_enabled: boolean
  competitors_count: number
  recent_learning_events: any[]
  recent_videos: any[]
}

export interface AutoCollectorRunResponse {
  ok: boolean
  mode: string
  sources_count: number
  discovered_count: number
  collected_count: number
  saved_event_id?: string
  learning: any
  warnings: string[]
}
