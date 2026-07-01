export const API_BASE = (import.meta.env.VITE_API_BASE || 'https://ai-video.47-76-143-158.sslip.io').replace(/\/$/, '')
export const TOKEN_KEY = 'ai_video_api_token'

export type WorkspaceTab = 'pureai' | 'collect' | 'leads' | 'digital'

export type ScriptSegment = {
  index: number
  text: string
  duration: number
  material: string
  edit: string
}

export type ProjectDraft = {
  market: string
  platform: string
  topic: string
  targetDuration: number
  materialSeconds: number
  aiShotSeconds: number
  allowFal: boolean
  script: string
  title: string
  segments: ScriptSegment[]
  timeline?: unknown
  leads?: unknown[]
  contentInsights?: unknown[]
  lastOutput?: unknown
  digitalHumanRole?: string
  digitalHumanMode?: string
}

export type VideoPlan = {
  duration: number
  material: number
  missingSeconds: number
  aiShots: number
  fullAiShots: number
  suggestedChars: number
  segmentCount: number
  avgSegmentSeconds: number
  shotSeconds: number
}

export function emptyProjectDraft(): ProjectDraft {
  return {
    market: '马来西亚',
    platform: 'douyin',
    topic: '马来西亚买房，别只看价格',
    targetDuration: 28,
    materialSeconds: 0,
    aiShotSeconds: 7,
    allowFal: true,
    script: '',
    title: '',
    segments: [],
  }
}

export function getStoredToken(): string {
  return (localStorage.getItem(TOKEN_KEY) || '').trim()
}

export function setStoredToken(token: string): string {
  const clean = String(token || '').trim()
  if (clean) localStorage.setItem(TOKEN_KEY, clean)
  return clean
}

export function clearStoredToken() {
  localStorage.removeItem(TOKEN_KEY)
}

export function maskToken(token: string): string {
  const t = String(token || '').trim()
  if (!t) return '未设置'
  if (t.length <= 10) return `${t.slice(0, 2)}****`
  return `${t.slice(0, 4)}****${t.slice(-4)}`
}

export function safeNumber(value: unknown, fallback = 0): number {
  const n = Number(value)
  return Number.isFinite(n) ? n : fallback
}

export function detailToText(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (value instanceof Error) return value.message
  if (typeof value === 'string') return value
  if (Array.isArray(value)) {
    return value.map((item) => {
      if (typeof item === 'string') return item
      const obj = item as Record<string, unknown>
      const loc = Array.isArray(obj.loc) ? obj.loc.join('.') : ''
      const msg = obj.msg || obj.message || obj.detail || JSON.stringify(obj)
      return loc ? `${loc}: ${String(msg)}` : String(msg)
    }).join('；')
  }
  if (typeof value === 'object') {
    const obj = value as Record<string, unknown>
    if (obj.message || obj.msg || obj.detail) return detailToText(obj.message || obj.msg || obj.detail)
    try { return JSON.stringify(value, null, 2) } catch { return String(value) }
  }
  return String(value)
}

async function parseResponse<T = unknown>(res: Response, url: string): Promise<T> {
  const contentType = res.headers.get('content-type') || ''
  let data: unknown = null
  let text = ''
  try {
    data = contentType.includes('application/json') ? await res.json() : null
    if (data === null) text = await res.text()
  } catch {}
  if (!res.ok) {
    const obj = data as { detail?: unknown; message?: unknown } | null
    const msg = detailToText(obj?.detail ?? obj?.message ?? data ?? text) || `${res.status} ${res.statusText}`
    throw new Error(`${msg}\n请求地址：${url}`)
  }
  if (data !== null) return data as T
  return ({ ok: true, raw: text } as T)
}

function authHeaders(extra?: HeadersInit): HeadersInit {
  const token = getStoredToken()
  return {
    ...(extra || {}),
    ...(token ? { 'X-AI-Video-Token': token } : {}),
  }
}

export async function apiGet<T = unknown>(path: string): Promise<T> {
  const url = `${API_BASE}${path}`
  const res = await fetch(url, { headers: authHeaders() })
  return parseResponse<T>(res, url)
}

export async function apiPost<T = unknown>(path: string, body: unknown, timeoutMs = 240000): Promise<T> {
  const url = `${API_BASE}${path}`
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), timeoutMs)
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(body),
      signal: controller.signal,
    })
    return parseResponse<T>(res, url)
  } catch (err: unknown) {
    const e = err as { name?: string; message?: string }
    if (e?.name === 'AbortError') throw new Error(`请求超时：${url}`)
    if (e?.message === 'Failed to fetch') throw new Error(`无法连接后端：${url}\n请检查 ECS 后端、Nginx、CORS 和 API_BASE。`)
    throw err
  } finally {
    window.clearTimeout(timer)
  }
}

export function splitCsvLine(line: string): string[] {
  const out: string[] = []
  let cur = ''
  let quoted = false
  for (let i = 0; i < line.length; i += 1) {
    const ch = line[i]
    if (ch === '"') {
      if (quoted && line[i + 1] === '"') { cur += '"'; i += 1 } else quoted = !quoted
    } else if (ch === ',' && !quoted) {
      out.push(cur.trim())
      cur = ''
    } else cur += ch
  }
  out.push(cur.trim())
  return out
}

export function csvRows(text: string): Record<string, string>[] {
  const lines = String(text || '').split(/\r?\n/).map((x) => x.trim()).filter(Boolean)
  if (lines.length < 2) return []
  const headers = splitCsvLine(lines[0]).map((x) => x.trim())
  return lines.slice(1).map((line) => {
    const cells = splitCsvLine(line)
    const row: Record<string, string> = {}
    headers.forEach((h, i) => { row[h] = cells[i] || '' })
    return row
  })
}

export function computeVideoPlan(targetDuration: number, materialSeconds: number, aiShotSeconds: number): VideoPlan {
  const duration = Math.max(8, Math.min(180, Math.round(safeNumber(targetDuration, 28))))
  const material = Math.max(0, Math.round(safeNumber(materialSeconds, 0)))
  const shotSeconds = Math.max(3, Math.min(12, Math.round(safeNumber(aiShotSeconds, 7))))
  const missingSeconds = Math.max(0, duration - material)
  const aiShots = missingSeconds > 0 ? Math.ceil(missingSeconds / shotSeconds) : 0
  const fullAiShots = Math.min(3, Math.max(1, aiShots || Math.ceil(duration / Math.max(shotSeconds, 8))))
  const suggestedChars = Math.max(36, Math.round(duration * 4.2))
  const segmentCount = Math.max(3, Math.ceil(duration / 4))
  const avgSegmentSeconds = Number((duration / segmentCount).toFixed(1))
  return { duration, material, missingSeconds, aiShots, fullAiShots, suggestedChars, segmentCount, avgSegmentSeconds, shotSeconds }
}

export function generateLocalScript(topic: string, market: string, duration: number): string {
  const plan = computeVideoPlan(duration, 0, 7)
  const lines = [
    `${topic}，先别急着做决定。`,
    `第一步先看预算和用途，别一上来只问价格。`,
    `第二步看区域：自住、出租和未来转手，判断逻辑完全不一样。`,
    `第三步核验真实资料：户型、价格、周边和交付信息都要以官方文件为准。`,
    `${market}不同城市和区域差异很大，不要只看宣传图。`,
    `想少踩坑，先把预算、目标城市和自住/投资用途说清楚。`,
  ]
  return lines.slice(0, Math.min(lines.length, plan.segmentCount)).join('\n')
}

export function splitScriptToSegments(script: string, duration: number, materialSeconds: number, aiShotSeconds: number): ScriptSegment[] {
  const plan = computeVideoPlan(duration, materialSeconds, aiShotSeconds)
  const rough = String(script || '').split(/[\n。！？!?]+/).map((x) => x.trim()).filter(Boolean)
  const fallback = generateLocalScript('马来西亚买房，别只看价格', '马来西亚', duration).split('\n')
  const lines = (rough.length ? rough : fallback).slice(0, plan.segmentCount)
  while (lines.length < plan.segmentCount) lines.push(lines[lines.length - 1] || '补充真实资料核验点。')
  let remainingMaterial = Math.max(0, materialSeconds)
  return lines.map((text, i) => {
    const durationForSegment = i === lines.length - 1
      ? Number(Math.max(1.8, plan.duration - plan.avgSegmentSeconds * (lines.length - 1)).toFixed(1))
      : plan.avgSegmentSeconds
    const useMaterial = remainingMaterial >= durationForSegment
    if (useMaterial) remainingMaterial -= durationForSegment
    return {
      index: i + 1,
      text,
      duration: durationForSegment,
      material: useMaterial ? `已选素材 ${i + 1}` : `fal.ai 补镜头 ${Math.min(3, (i % 3) + 1)}`,
      edit: i === 0 ? '强钩子快切 + 字幕加粗' : i === lines.length - 1 ? '结尾号召 + 评论区引导' : '按语义切镜 + 轻推拉',
    }
  })
}

export function projectWithScript(project: ProjectDraft, script: string): ProjectDraft {
  const plan = computeVideoPlan(project.targetDuration, project.materialSeconds, project.aiShotSeconds)
  return {
    ...project,
    script,
    title: project.title || project.topic,
    segments: splitScriptToSegments(script, plan.duration, plan.material, plan.shotSeconds),
  }
}

export function buildFullAiPayload(project: ProjectDraft) {
  const plan = computeVideoPlan(project.targetDuration, project.materialSeconds, project.aiShotSeconds)
  const script = project.script || generateLocalScript(project.topic, project.market, plan.duration)
  const segments = project.segments?.length ? project.segments : splitScriptToSegments(script, plan.duration, plan.material, plan.shotSeconds)
  const groupSize = Math.ceil(segments.length / plan.fullAiShots)
  const shots = Array.from({ length: plan.fullAiShots }).map((_, i) => {
    const group = segments.slice(i * groupSize, (i + 1) * groupSize)
    const text = group.map((s) => s.text).join(' ')
    return {
      index: i,
      duration: Math.max(3, Math.round(group.reduce((sum, s) => sum + Number(s.duration || 0), 0) || plan.shotSeconds)),
      prompt: `${project.market} 房产短视频通用氛围镜头：${text}。只生成城市、生活、看房、资料核验、商务沟通等通用画面，不编造真实楼盘、户型、价格、周边。`,
      text,
      shot_hint: i === 0 ? 'hook_atmosphere' : i === plan.fullAiShots - 1 ? 'cta_atmosphere' : 'explain_atmosphere',
    }
  })
  return {
    market: project.market,
    platform: project.platform,
    topic: project.topic,
    title: project.title || project.topic,
    target_duration: plan.duration,
    target_duration_seconds: plan.duration,
    duration_seconds: plan.duration,
    script_text: script,
    copy: script,
    segments,
    shots,
    allow_fal_fill: project.allowFal,
    fal_fill_shots: plan.fullAiShots,
    ai_shot_seconds: plan.shotSeconds,
    material_seconds: plan.material,
    mode: 'pure_ai_or_fal_fill',
  }
}
