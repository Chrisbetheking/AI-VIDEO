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
  return (await res.text()) as T
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
