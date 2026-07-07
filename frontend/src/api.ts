const envApiBase = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '')
const isLocal = typeof window !== 'undefined' && /^(localhost|127\.0\.0\.1)$/i.test(window.location.hostname)

export const API_BASE = envApiBase || (isLocal ? 'http://localhost:8000' : '')

export type AssetKind = 'image' | 'video' | 'audio' | 'file' | string

export type AssetItem = {
  id: string
  filename: string
  original_name?: string
  kind: AssetKind
  url: string
  folder?: string
  source_type?: string
  usage_role?: string
  size_bytes?: number
  created_at?: string
  mime_type?: string
  r2_url?: string
  local_url?: string
  duration?: number
  width?: number
  height?: number
  [key: string]: unknown
}

async function parseResponse<T>(res: Response, url: string): Promise<T> {
  const text = await res.text()
  let data: any = {}
  try {
    data = text ? JSON.parse(text) : {}
  } catch {
    data = { raw: text }
  }
  if (!res.ok) {
    throw new Error(data?.detail || data?.error || data?.message || `HTTP ${res.status}: ${url}`)
  }
  return data as T
}

function joinUrl(path: string): string {
  if (/^https?:\/\//i.test(path)) return path
  if (!path.startsWith('/')) return `${API_BASE}/${path}`
  return `${API_BASE}${path}`
}

export async function apiGet<T = any>(path: string): Promise<T> {
  const url = joinUrl(path)
  return parseResponse<T>(await fetch(url), url)
}

export async function apiPost<T = any>(path: string, body?: unknown): Promise<T> {
  const url = joinUrl(path)
  return parseResponse<T>(
    await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body ?? {}),
    }),
    url,
  )
}

export async function apiDelete<T = any>(path: string): Promise<T> {
  const url = joinUrl(path)
  return parseResponse<T>(await fetch(url, { method: 'DELETE' }), url)
}

export async function uploadAssets(
  files: FileList | File[] | null,
  folder: string = 'self',
  usageRole: string = 'content',
): Promise<AssetItem[]> {
  const list = Array.from(files || [])
  if (!list.length) return []

  const form = new FormData()
  list.forEach((file) => form.append('files', file))
  form.append('folder', folder)
  form.append('usage_role', usageRole)

  const url = joinUrl('/api/assets')
  return parseResponse<AssetItem[]>(
    await fetch(url, {
      method: 'POST',
      body: form,
    }),
    url,
  )
}

export async function deleteAsset(assetId: string): Promise<{ ok?: boolean; deleted?: string[]; [key: string]: unknown }> {
  if (!assetId) return { ok: false, deleted: [] }
  return apiDelete(`/api/assets/${encodeURIComponent(assetId)}`)
}

export default {
  API_BASE,
  apiGet,
  apiPost,
  apiDelete,
  uploadAssets,
  deleteAsset,
}
