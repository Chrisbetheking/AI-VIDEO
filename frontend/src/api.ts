const envApiBase = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '')
const isLocal = typeof window !== 'undefined' && /^(localhost|127\.0\.0\.1)$/i.test(window.location.hostname)
export const API_BASE = envApiBase || (isLocal ? 'http://localhost:8000' : '')

async function parseResponse<T>(res: Response, url: string): Promise<T> {
  const text = await res.text()
  let data: any = {}
  try { data = text ? JSON.parse(text) : {} } catch { data = { raw: text } }
  if (!res.ok) throw new Error(data?.detail || data?.error || data?.message || `HTTP ${res.status}: ${url}`)
  return data as T
}

export async function apiGet<T>(path: string): Promise<T> {
  const url = `${API_BASE}${path}`
  return parseResponse<T>(await fetch(url), url)
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const url = `${API_BASE}${path}`
  return parseResponse<T>(await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }), url)
}

export async function apiDelete<T>(path: string): Promise<T> {
  const url = `${API_BASE}${path}`
  return parseResponse<T>(await fetch(url, { method: 'DELETE' }), url)
}
