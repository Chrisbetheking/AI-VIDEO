export const API_BASE = 'https://ai-video.47-76-143-158.sslip.io'
export const TOKEN_KEY = 'ai_video_api_token'

export function getStoredToken(): string {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function setStoredToken(token: string) {
  const clean = token.trim()
  if (clean) localStorage.setItem(TOKEN_KEY, clean)
}

export function clearStoredToken() {
  localStorage.removeItem(TOKEN_KEY)
}

export function maskToken(token: string) {
  if (!token) return '未设置'
  if (token.length <= 10) return '已设置'
  return `${token.slice(0, 4)}****${token.slice(-4)}`
}

export async function apiRequest(path: string, options: RequestInit = {}) {
  const token = getStoredToken()
  const headers = new Headers(options.headers || {})
  if (!headers.has('Content-Type') && options.body) headers.set('Content-Type', 'application/json')
  if (token) headers.set('X-AI-Video-Token', token)

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers })
  const text = await res.text()
  let data: any = {}
  try {
    data = text ? JSON.parse(text) : {}
  } catch {
    data = { raw: text }
  }

  if (!res.ok) {
    const message = data?.detail || data?.message || data?.raw || `HTTP ${res.status}`
    throw new Error(String(message))
  }
  return data
}

export function apiGet(path: string) {
  return apiRequest(path)
}

export function apiPost(path: string, body: any) {
  return apiRequest(path, {
    method: 'POST',
    body: JSON.stringify(body || {}),
  })
}

export async function tryPost(paths: string[], body: any) {
  let lastError: unknown = null
  for (const path of paths) {
    try {
      const data = await apiPost(path, body)
      return { ok: true, path, data }
    } catch (err) {
      lastError = err
    }
  }
  throw lastError instanceof Error ? lastError : new Error(String(lastError || '请求失败'))
}
