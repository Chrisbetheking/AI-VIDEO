export const API_BASE = 'https://ai-video.47-76-143-158.sslip.io'
export const TOKEN_KEY = 'ai_video_api_token'

export function getAiVideoToken(): string {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function saveAiVideoToken(token: string) {
  const value = String(token || '').trim()
  if (value) localStorage.setItem(TOKEN_KEY, value)
  window.dispatchEvent(new Event('ai-video-token-updated'))
}

export function clearAiVideoToken() {
  localStorage.removeItem(TOKEN_KEY)
  window.dispatchEvent(new Event('ai-video-token-updated'))
}

export function maskToken(token: string) {
  if (!token) return '未设置'
  if (token.length <= 10) return '已设置'
  return `${token.slice(0, 4)}****${token.slice(-4)}`
}

function requireToken() {
  const token = getAiVideoToken()
  if (!token) throw new Error('缺少 AI-VIDEO API Token。请先在右上角 Token 里保存。')
  return token
}

export async function apiGet(path: string): Promise<any> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'X-AI-Video-Token': requireToken() },
  })
  const text = await res.text()
  let data: any = {}
  try { data = text ? JSON.parse(text) : {} } catch { data = { raw: text } }
  if (!res.ok) throw new Error(data?.detail || data?.message || `HTTP ${res.status}`)
  return data
}

export async function apiPost(path: string, body: any): Promise<any> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-AI-Video-Token': requireToken(),
    },
    body: JSON.stringify(body || {}),
  })
  const text = await res.text()
  let data: any = {}
  try { data = text ? JSON.parse(text) : {} } catch { data = { raw: text } }
  if (!res.ok) throw new Error(data?.detail || data?.message || `HTTP ${res.status}`)
  return data
}

export async function apiPostFirst(paths: string[], body: any): Promise<any> {
  let last: unknown = null
  for (const path of paths) {
    try {
      return await apiPost(path, body)
    } catch (e: any) {
      last = e
      const msg = String(e?.message || e || '')
      if (!msg.includes('404') && !msg.includes('Not Found') && !msg.includes('405')) throw e
    }
  }
  throw last instanceof Error ? last : new Error(String(last || '所有接口都不可用'))
}

export function copyJson(data: any) {
  navigator.clipboard?.writeText(JSON.stringify(data, null, 2)).catch(() => {})
}
