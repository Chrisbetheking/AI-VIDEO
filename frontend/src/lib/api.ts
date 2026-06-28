import type {
  HealthStatus, IndustryPackSummary, LeadItem, LeadAnalyzeResult,
  MinimaxStatus, AssetItem, Industry, HumanMode,
} from './types'

const API_BASE = (window as any).__API_BASE || '/api'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const url = `${API_BASE}${path}`
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  })
  if (!res.ok) {
    const text = await res.text().catch(() => 'Unknown error')
    throw new Error(`API ${res.status}: ${text.slice(0, 500)}`)
  }
  return res.json()
}

export async function getHealth(): Promise<HealthStatus> {
  return request<HealthStatus>('/health')
}

export async function getIndustryPacks(): Promise<IndustryPackSummary[]> {
  return request<IndustryPackSummary[]>('/industry-packs')
}

export async function analyzeLead(content: string, industry: Industry, platform = 'douyin'): Promise<LeadAnalyzeResult> {
  return request<LeadAnalyzeResult>('/leads/analyze', {
    method: 'POST',
    body: JSON.stringify({ content, industry, platform }),
  })
}

export async function getLeads(industry?: string): Promise<LeadItem[]> {
  const qs = industry ? `?industry=${encodeURIComponent(industry)}` : ''
  return request<LeadItem[]>(`/leads${qs}`)
}

export async function updateLead(leadId: string, status: string): Promise<{ ok: boolean }> {
  return request(`/leads/${leadId}`, {
    method: 'PATCH',
    body: JSON.stringify({ status }),
  })
}

export async function getMinimaxStatus(): Promise<MinimaxStatus> {
  return request<MinimaxStatus>('/minimax/status')
}

export async function minimaxTextToVideo(prompt: string, duration = 5): Promise<any> {
  return request('/minimax/video/text-to-video', {
    method: 'POST',
    body: JSON.stringify({ prompt, duration_seconds: duration }),
  })
}

export async function getAssets(): Promise<AssetItem[]> {
  return request<AssetItem[]>('/assets')
}

export async function uploadAsset(file: File, folder = 'self'): Promise<any> {
  const form = new FormData()
  form.append('file', file)
  form.append('folder', folder)
  const url = `${API_BASE}/assets`
  const res = await fetch(url, { method: 'POST', body: form })
  if (!res.ok) throw new Error(`Upload failed: ${res.status}`)
  return res.json()
}

export async function generateCopy(payload: Record<string, any>): Promise<any> {
  return request('/generate-copy', { method: 'POST', body: JSON.stringify(payload) })
}

export async function composeVideo(payload: Record<string, any>): Promise<any> {
  return request('/compose-video', { method: 'POST', body: JSON.stringify(payload) })
}

export async function getTtsProviders(): Promise<any[]> {
  try {
    return await request<any[]>('/tts/providers')
  } catch {
    return []
  }
}

export async function getDigitalHumanProviders(): Promise<any[]> {
  try {
    return await request<any[]>('/digital-human/providers')
  } catch {
    return []
  }
}
