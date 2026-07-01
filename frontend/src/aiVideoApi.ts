export const AI_VIDEO_API_BASE = 'https://ai-video.47-76-143-158.sslip.io'
export const AI_VIDEO_TOKEN_KEY = 'ai_video_api_token'

export function getAiVideoToken(): string {
  return window.localStorage.getItem(AI_VIDEO_TOKEN_KEY) || ''
}

export function saveAiVideoToken(token: string) {
  const next = token.trim()
  if (!next) return
  window.localStorage.setItem(AI_VIDEO_TOKEN_KEY, next)
  window.dispatchEvent(new CustomEvent('ai-video-token-updated'))
}

export function clearAiVideoToken() {
  window.localStorage.removeItem(AI_VIDEO_TOKEN_KEY)
  window.dispatchEvent(new CustomEvent('ai-video-token-updated'))
}

export function maskToken(token: string) {
  if (!token) return '未设置'
  if (token.length <= 10) return '已设置'
  return `${token.slice(0, 4)}****${token.slice(-4)}`
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

export async function apiGet(path: string, requireToken = true): Promise<any> {
  const token = getAiVideoToken()
  if (requireToken && !token) throw new Error('缺少 AI-VIDEO API Token。请在右上角“设置 Token”里保存。')

  const headers: Record<string, string> = {}
  if (token) headers['X-AI-Video-Token'] = token

  const res = await fetch(`${AI_VIDEO_API_BASE}${path}`, { headers })
  return parseResponse(res)
}

export async function apiPost(path: string, body: any, requireToken = true): Promise<any> {
  const token = getAiVideoToken()
  if (requireToken && !token) throw new Error('缺少 AI-VIDEO API Token。请在右上角“设置 Token”里保存。')

  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (token) headers['X-AI-Video-Token'] = token

  const res = await fetch(`${AI_VIDEO_API_BASE}${path}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  })
  return parseResponse(res)
}

export function safeJson(data: any) {
  try {
    return JSON.stringify(data, null, 2)
  } catch {
    return String(data)
  }
}
