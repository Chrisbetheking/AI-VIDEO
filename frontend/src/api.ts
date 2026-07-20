const envApiBase = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '')
const isLocal = typeof window !== 'undefined' && /^(localhost|127\.0\.0\.1)$/i.test(window.location.hostname)

// V10.40.8.10.4: production frontend talks to ECS HTTPS API
export const DEFAULT_PRODUCTION_API_BASE = 'https://ai-video.47-76-143-158.sslip.io'
export const API_BASE = isLocal
  ? (envApiBase || 'http://localhost:8000')
  : (envApiBase || DEFAULT_PRODUCTION_API_BASE)

const envZipUploadBase = (import.meta.env.VITE_ZIP_UPLOAD_API_BASE || '').replace(/\/$/, '')
export const ZIP_UPLOAD_API_BASE = isLocal
  ? API_BASE
  : (envZipUploadBase || API_BASE || DEFAULT_PRODUCTION_API_BASE)

function withTimeout(ms = 90000) {
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), ms)
  return { controller, timer }
}

function formatApiDetail(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'string') return value
  if (Array.isArray(value)) {
    return value.map((item: any) => {
      if (typeof item === 'string') return item
      const loc = Array.isArray(item?.loc) ? item.loc.join('.') : ''
      const msg = item?.msg || item?.message || JSON.stringify(item)
      return loc ? `${loc}: ${msg}` : String(msg)
    }).join('；')
  }
  if (typeof value === 'object') {
    const obj: any = value
    if (obj.message || obj.msg) return String(obj.message || obj.msg)
    try { return JSON.stringify(value, null, 2) } catch { return String(value) }
  }
  return String(value)
}

async function parseResponse<T>(res: Response, url: string): Promise<T> {
  const contentType = res.headers.get('content-type') || ''
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      if (contentType.includes('application/json')) {
        const data = await res.json()
        detail = formatApiDetail((data as any).detail ?? data) || detail
      } else {
        detail = await res.text()
      }
    } catch {}
    throw new Error(`${detail}\n请求地址：${url}`)
  }
  if (contentType.includes('application/json')) return res.json() as Promise<T>
  const text = await res.text()
  throw new Error(`后端没有返回 JSON，请检查 Cloudflare 的 VITE_API_BASE 是否指向 ECS 后端。\n请求地址：${url}\n返回：${text.slice(0, 220)}`)
}

async function safeFetch<T>(url: string, init?: RequestInit, timeoutMs = 240000): Promise<T> {
  const { controller, timer } = withTimeout(timeoutMs)
  try {
    const res = await fetch(url, { ...init, signal: controller.signal })
    return parseResponse<T>(res, url)
  } catch (err: any) {
    if (err?.name === 'AbortError') {
      throw new Error(`请求超时：${url}\nECS 后端接口耗时过长，可能是视频合成、采集或 AI 接口正在执行。`)
    }
    const msg = err?.message || String(err)
    if (msg === 'Failed to fetch') {
      throw new Error(`无法连接后端：${url}\n请先打开 ${API_BASE || window.location.origin}/api/health，确认返回 ok；如果仍失败，请检查 ECS 后端服务和 Nginx。`)
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
  const timeoutMs = path.includes('compose-video') ? 360000 : 240000
  return safeFetch<T>(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  }, timeoutMs)
}

export async function uploadAssets(files: FileList, folder = 'self'): Promise<AssetItem[]> {
  const form = new FormData()
  form.append('folder', folder)
  Array.from(files).forEach(file => form.append('files', file))
  const url = `${API_BASE}/api/assets`
  return safeFetch<AssetItem[]>(url, { method: 'POST', body: form }, 180000)
}

export interface AssetZipImportSummary {
  imported: number
  duplicates: number
  ignored: number
  failed: number
  images: number
  videos: number
  total_media: number
}

export interface AssetZipImportFailure {
  file: string
  reason: string
}

export interface AssetZipImportJob {
  job_id: string
  version: string
  status: 'queued' | 'running' | 'done' | 'failed' | 'cancelled' | string
  stage: string
  progress: number
  message: string
  current_file?: string
  zip_name: string
  zip_size_bytes: number
  folder: string
  usage_role: string
  processed?: number
  summary: AssetZipImportSummary
  failures: AssetZipImportFailure[]
  imported_assets: AssetItem[]
  error?: string
  created_at: string
  updated_at: string
  finished_at?: string
}

export interface AssetZipUploadProgress {
  loaded: number
  total: number
  percent: number
}

function parseZipUploadError(xhr: XMLHttpRequest, url: string): string {
  const responseText = String(xhr.responseText || '')
  let detail = ''
  try {
    const data = JSON.parse(responseText)
    detail = formatApiDetail(data?.detail ?? data)
  } catch {
    // Do not dump Cloudflare/Nginx HTML into the UI.
    if (responseText && !/<html[\s>]/i.test(responseText)) detail = responseText.slice(0, 500)
  }

  if (xhr.status === 413) {
    return `ZIP 压缩包超过上传通道允许大小。当前请求已经走 ECS 直传；请检查 ECS Nginx 的 client_max_body_size。`
  }
  if (xhr.status === 0) {
    return `ZIP 直传连接失败：${url}\n请检查 ECS HTTPS、CORS 和 Nginx。`
  }
  return `${detail || `${xhr.status} ${xhr.statusText}`}\nZIP 直传地址：${url}`
}

export async function uploadAssetZip(
  file: File,
  folder = 'self',
  usageRole = 'content',
  onProgress?: (progress: AssetZipUploadProgress) => void,
): Promise<AssetZipImportJob> {
  const form = new FormData()
  form.append('file', file)
  form.append('folder', folder)
  form.append('usage_role', usageRole)
  const url = `${ZIP_UPLOAD_API_BASE}/api/assets/import-zip`

  return new Promise<AssetZipImportJob>((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', url, true)
    xhr.timeout = 0

    xhr.upload.onprogress = (event) => {
      const total = event.lengthComputable ? event.total : file.size
      const loaded = Math.min(event.loaded, total || event.loaded)
      const percent = total > 0 ? Math.max(0, Math.min(100, Math.round((loaded / total) * 100))) : 0
      onProgress?.({ loaded, total, percent })
    }

    xhr.onerror = () => reject(new Error(parseZipUploadError(xhr, url)))
    xhr.onabort = () => reject(new Error('ZIP 上传已取消'))
    xhr.onload = () => {
      if (xhr.status < 200 || xhr.status >= 300) {
        reject(new Error(parseZipUploadError(xhr, url)))
        return
      }
      try {
        const data = JSON.parse(String(xhr.responseText || '{}'))
        onProgress?.({ loaded: file.size, total: file.size, percent: 100 })
        resolve(data as AssetZipImportJob)
      } catch {
        reject(new Error(`ECS ZIP 直传接口没有返回 JSON。\nZIP 直传地址：${url}`))
      }
    }

    xhr.send(form)
  })
}

export async function getAssetZipImportJob(jobId: string): Promise<AssetZipImportJob> {
  return apiGet<AssetZipImportJob>(`/api/assets/import-zip/jobs/${encodeURIComponent(jobId)}`)
}

export async function listAssetZipImportJobs(limit = 10): Promise<{ok: boolean; version: string; jobs: AssetZipImportJob[]; total: number}> {
  return apiGet(`/api/assets/import-zip/jobs?limit=${Math.max(1, Math.min(limit, 100))}`)
}

export async function deleteAsset(assetId: string): Promise<{ok: boolean; deleted: string[]; warnings: string[]}> {
  const url = `${API_BASE}/api/assets/${encodeURIComponent(assetId)}`
  return safeFetch<{ok: boolean; deleted: string[]; warnings: string[]}>(url, { method: 'DELETE' })
}


export async function getAssetIntelligence(limit = 3000): Promise<AssetIntelligenceListResponse> {
  return apiGet<AssetIntelligenceListResponse>(`/api/assets/intelligence?limit=${Math.max(1, Math.min(limit, 5000))}`)
}

export async function getAssetIntelligenceHealth(): Promise<any> {
  return apiGet('/api/assets/intelligence/health')
}

export async function startAssetIntelligenceAnalysis(options: {
  asset_ids?: string[]
  force?: boolean
  limit?: number
  include_avatar_assets?: boolean
} = {}): Promise<AssetIntelligenceJob | {ok: boolean; status: string; message: string}> {
  return apiPost('/api/assets/intelligence/analyze', options)
}

export async function getAssetIntelligenceJob(jobId: string): Promise<AssetIntelligenceJob> {
  return apiGet<AssetIntelligenceJob>(`/api/assets/intelligence/jobs/${encodeURIComponent(jobId)}`)
}

export async function updateAssetIntelligenceControl(patch: Partial<AssetIntelligenceControl>): Promise<{ok: boolean; version: string; control: AssetIntelligenceControl}> {
  return apiPost('/api/assets/intelligence/control', patch)
}

export async function updateAssetIntelligence(assetId: string, patch: Partial<AssetIntelligence>): Promise<{ok: boolean; version: string; item: AssetIntelligence}> {
  const url = `${API_BASE}/api/assets/intelligence/${encodeURIComponent(assetId)}`
  return safeFetch(url, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  })
}

export async function searchAssetIntelligence(query: string, limit = 30): Promise<{ok: boolean; version: string; query: string; items: AssetIntelligence[]}> {
  return apiGet(`/api/assets/intelligence/search?q=${encodeURIComponent(query)}&limit=${Math.max(1, Math.min(limit, 100))}`)
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
export interface AudioSegmentTiming { index: number; text: string; start: number; end: number; duration: number }
export interface TTSResponse { file_url: string; file_name: string; duration_seconds: number; warning?: string; segments?: AudioSegmentTiming[] }
export interface AssetCleanliness {
  status: 'passed' | 'failed' | 'uncertain' | string
  watermark?: boolean
  subtitle?: boolean
  qr_code?: boolean
  large_face?: boolean
  advertising_text?: boolean
  blur?: boolean
  too_dark?: boolean
  severe_shake?: boolean
  reasons?: string[]
}

export interface AssetIntelligence {
  asset_id: string
  filename?: string
  original_name?: string
  kind?: 'image' | 'video' | string
  analysis_status: 'pending' | 'processing' | 'completed' | 'failed' | 'need_config' | 'manual' | string
  title?: string
  description?: string
  primary_category?: string
  secondary_category?: string
  location?: string
  scene?: string
  subjects?: string[]
  camera_motion?: string
  orientation?: string
  keywords?: string[]
  cleanliness?: AssetCleanliness
  quality_score?: number
  recommended_topics?: string[]
  visible_text?: string[]
  confidence?: number
  technical?: { width?: number; height?: number; duration?: number; frame_count?: number }
  provider?: string
  model?: string
  error?: string
  updated_at?: string
}

export interface AssetIntelligenceJob {
  job_id: string
  version: string
  status: 'queued' | 'running' | 'done' | 'failed' | 'cancelled' | string
  stage: string
  progress: number
  message?: string
  current_asset_id?: string
  current_file?: string
  processed?: number
  summary?: { success: number; failed: number; skipped: number; total: number }
  error?: string
  source?: string
  created_at?: string
  updated_at?: string
  finished_at?: string
  reused?: boolean
}

export interface AssetIntelligenceControl {
  auto_enabled: boolean
  auto_batch_size: number
  poll_seconds: number
  include_avatar_assets: boolean
  updated_at?: string
}

export interface AssetIntelligenceListResponse {
  ok: boolean
  version: string
  items: AssetIntelligence[]
  summary: Record<string, number>
  control: AssetIntelligenceControl
  active_job?: AssetIntelligenceJob | null
  categories: string[]
}

export interface AssetItem { id: string; filename: string; original_name: string; kind: 'image' | 'video'; url: string; size_bytes: number; created_at: string; folder?: string; source_type?: string; intelligence?: AssetIntelligence }


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
export interface ImageGenerateResponse { image_url: string; image_name: string; prompt: string; provider: string; model: string; warnings: string[] }

export interface GraphicPostImage { image_url: string; image_name: string; title: string; caption: string; role: string }
export interface GraphicPostResponse {
  package_title: string
  platform: string
  images: GraphicPostImage[]
  publish_title: string
  publish_description: string
  checklist: string[]
  warnings: string[]
}

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

export interface OneClickGenerateRequest {
  industry: string
  audience: string
  selling_points: string
  style: string
  duration_seconds: number
  goal: string
  output_type: string
  material_mode: string
  selected_asset_names: string[]
  reference_text: string
  instruction: string
}

export interface OneClickGenerateResponse {
  project_title: string
  summary: string
  copy: GeneratedCopy
  voice_director: VoiceDirectorResponse
  shooting_plan: ShootingPlanResponse
  edit_plan: EditPlanResponse
  subtitle: SubtitleEmphasisResponse
  image_prompts: string[]
  publish_title: string
  publish_description: string
  next_actions: string[]
  warnings: string[]
  raw?: Record<string, any>
}

export interface ModelStatusResponse {
  ai_provider: string
  ai_text_model: string
  ai_backup_provider: string
  ai_backup_model: string
  qwen_configured: boolean
  gemini_configured: boolean
  deepseek_configured: boolean
  asr_provider: string
  asr_model: string
  image_provider: string
  image_model: string
  image_edit_model: string
}
