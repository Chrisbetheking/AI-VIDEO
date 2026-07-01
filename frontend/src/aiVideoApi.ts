export const API_BASE = 'https://ai-video.47-76-143-158.sslip.io'
export const TOKEN_KEY = 'ai_video_api_token'

export function getApiToken(): string {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function saveApiToken(token: string) {
  const value = String(token || '').trim()
  if (value) localStorage.setItem(TOKEN_KEY, value)
  else localStorage.removeItem(TOKEN_KEY)
  window.dispatchEvent(new CustomEvent('ai-video-token-updated'))
}

export function clearApiToken() {
  saveApiToken('')
}

export const getAiVideoToken = getApiToken
export const saveAiVideoToken = saveApiToken
export const clearAiVideoToken = clearApiToken

export function maskToken(token?: string) {
  const value = String(token || getApiToken() || '').trim()
  if (!value) return '未设置'
  if (value.length <= 10) return '已设置'
  return `${value.slice(0, 4)}****${value.slice(-4)}`
}

function authHeaders(extra?: Record<string, string>) {
  const token = getApiToken()
  return {
    ...(extra || {}),
    ...(token ? { 'X-AI-Video-Token': token } : {}),
  }
}

async function parseResponse(res: Response) {
  const text = await res.text()
  let data: any = {}
  try {
    data = text ? JSON.parse(text) : {}
  } catch {
    data = { raw: text }
  }
  if (!res.ok) {
    throw new Error(data?.detail || data?.message || data?.status || `HTTP ${res.status}`)
  }
  return data
}

export async function apiGet(path: string) {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: authHeaders(),
  })
  return parseResponse(res)
}

export async function apiPost(path: string, body: any) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(body || {}),
  })
  return parseResponse(res)
}

export function copyJson(data: any) {
  const text = typeof data === 'string' ? data : JSON.stringify(data, null, 2)
  navigator.clipboard?.writeText(text).catch(() => undefined)
}
