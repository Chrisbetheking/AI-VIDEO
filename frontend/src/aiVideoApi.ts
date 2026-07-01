export const API_BASE = 'https://ai-video.47-76-143-158.sslip.io'
export const TOKEN_KEY = 'ai_video_api_token'

export function getToken(): string {
  return (window.localStorage.getItem(TOKEN_KEY) || '').trim()
}

export function saveToken(token: string) {
  const value = (token || '').trim()
  if (value) window.localStorage.setItem(TOKEN_KEY, value)
}

export function clearToken() {
  window.localStorage.removeItem(TOKEN_KEY)
}

export function maskToken(token = getToken()) {
  if (!token) return '未设置'
  if (token.length <= 8) return '已设置'
  return `${token.slice(0, 4)}****${token.slice(-4)}`
}

export function errorText(error: unknown): string {
  if (!error) return '未知错误'
  if (typeof error === 'string') return error
  if (error instanceof Error) return error.message || '请求失败'
  try {
    const anyError: any = error
    if (anyError?.detail) {
      if (typeof anyError.detail === 'string') return anyError.detail
      return JSON.stringify(anyError.detail, null, 2)
    }
    if (anyError?.message) return String(anyError.message)
    return JSON.stringify(anyError, null, 2)
  } catch {
    return String(error)
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
    const message = data?.detail || data?.message || data?.error || `HTTP ${res.status}`
    throw new Error(typeof message === 'string' ? message : JSON.stringify(message))
  }
  return data
}

export async function apiGet(path: string, token = getToken()) {
  const headers: Record<string, string> = {}
  if (token) headers['X-AI-Video-Token'] = token
  const res = await fetch(`${API_BASE}${path}`, { headers })
  return parseResponse(res)
}

export async function apiPost(path: string, body: any, token = getToken()) {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (token) headers['X-AI-Video-Token'] = token
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body || {}),
  })
  return parseResponse(res)
}

export function normalizeCsvRows(text: string) {
  const rows = String(text || '').split(/\r?\n/).map((x) => x.trim()).filter(Boolean)
  if (!rows.length) return []
  const header = rows[0].split(',').map((x) => x.trim())
  return rows.slice(1).map((line) => {
    const cols = line.split(',').map((x) => x.trim())
    const item: Record<string, string> = {}
    header.forEach((key, index) => { item[key] = cols[index] || '' })
    return item
  })
}
