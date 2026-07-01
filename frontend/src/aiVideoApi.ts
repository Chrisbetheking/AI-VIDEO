export const API_BASE = 'https://ai-video.47-76-143-158.sslip.io'
export const TOKEN_KEY = 'ai_video_api_token'

export function getApiToken(): string {
  const fromUrl = new URLSearchParams(window.location.search).get('token') || ''
  if (fromUrl.trim()) {
    localStorage.setItem(TOKEN_KEY, fromUrl.trim())
    return fromUrl.trim()
  }
  return (localStorage.getItem(TOKEN_KEY) || (import.meta as any).env?.VITE_AI_VIDEO_API_TOKEN || '').trim()
}

export function saveApiToken(token: string) {
  const value = token.trim()
  if (value) localStorage.setItem(TOKEN_KEY, value)
  else localStorage.removeItem(TOKEN_KEY)
}

function parseResponse(text: string) {
  try {
    return text ? JSON.parse(text) : {}
  } catch {
    return { raw: text }
  }
}

export async function apiGet(path: string): Promise<any> {
  const token = getApiToken()
  const headers: Record<string, string> = {}
  if (token) headers['X-AI-Video-Token'] = token
  const res = await fetch(`${API_BASE}${path}`, { headers })
  const data = parseResponse(await res.text())
  if (!res.ok) {
    if (res.status === 401) throw new Error('缺少或错误的 AI-VIDEO API Token：请在页面 Token 设置里保存后重试。')
    throw new Error(data?.detail || data?.message || `HTTP ${res.status}`)
  }
  return data
}

export async function apiPost(path: string, body: any): Promise<any> {
  const token = getApiToken()
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (token) headers['X-AI-Video-Token'] = token
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  })
  const data = parseResponse(await res.text())
  if (!res.ok) {
    if (res.status === 401) throw new Error('缺少或错误的 AI-VIDEO API Token：请在页面 Token 设置里保存后重试。')
    throw new Error(data?.detail || data?.message || `HTTP ${res.status}`)
  }
  return data
}

export function copyJson(data: any) {
  navigator.clipboard?.writeText(JSON.stringify(data, null, 2)).catch(() => {})
}
