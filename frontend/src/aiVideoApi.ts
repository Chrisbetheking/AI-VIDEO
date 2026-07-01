const envApiBase = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '')
const defaultApiBase = 'https://ai-video.47-76-143-158.sslip.io'
const isLocal =
  typeof window !== 'undefined' &&
  /^(localhost|127\.0\.0\.1)$/i.test(window.location.hostname)

export const API_BASE = envApiBase || (isLocal ? 'http://localhost:8000' : defaultApiBase)
export const TOKEN_KEY = 'ai_video_api_token'

export type JsonObject = Record<string, any>

export type ProjectSegment = {
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
  segments: ProjectSegment[]
  timeline?: any
  leads?: any[]
  contentInsights?: any[]
  lastOutput?: any
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

export function clearStoredToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

/* 兼容旧文件名，避免局部上传后构建炸掉 */
export const getApiToken = getStoredToken
export const saveApiToken = setStoredToken

export function maskToken(token: string): string {
  const t = String(token || '').trim()
  if (!t) return '未设置'
  if (t.length <= 10) return `${t.slice(0, 2)}****`
  return `${t.slice(0, 4)}****${t.slice(-4)}`
}

export function safeText(value: unknown, fallback = ''): string {
  if (value === null || value === undefined) return fallback
  const text = String(value).trim()
  return text || fallback
}

export function safeNumber(value: unknown, fallback = 0): number {
  const n = Number(value)
  return Number.isFinite(n) ? n : fallback
}

export function detailToText(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'string') return value

  if (Array.isArray(value)) {
    return value
      .map((item: any) => {
        if (typeof item === 'string') return item
        const loc = Array.isArray(item?.loc) ? item.loc.join('.') : ''
        const msg = item?.msg || item?.message || item?.detail || safeStringify(item)
        return loc ? `${loc}: ${msg}` : String(msg)
      })
      .join('；')
  }

  if (typeof value === 'object') {
    const obj: any = value
    if (obj.message || obj.msg || obj.detail) {
      return detailToText(obj.message || obj.msg || obj.detail)
    }
    return safeStringify(value)
  }

  return String(value)
}

function safeStringify(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

export function copyJson(value: unknown): void {
  const text = typeof value === 'string' ? value : safeStringify(value)
  navigator.clipboard?.writeText(text).catch(() => {})
}

async function parseResponse(res: Response, url: string): Promise<any> {
  const contentType = res.headers.get('content-type') || ''
  let data: any = null
  let text = ''

  try {
    if (contentType.includes('application/json')) data = await res.json()
    else text = await res.text()
  } catch {}

  if (!res.ok) {
    const detail = detailToText(data?.detail ?? data ?? text) || `${res.status} ${res.statusText}`
    throw new Error(`${detail}\n请求地址：${url}`)
  }

  if (data !== null) return data
  if (text) return { ok: true, raw: text }
  return { ok: true }
}

function authHeaders(extra?: HeadersInit): HeadersInit {
  const token = getStoredToken()
  return {
    ...(extra || {}),
    ...(token ? { 'X-AI-Video-Token': token } : {}),
  }
}

export async function apiGet(path: string): Promise<any> {
  const url = `${API_BASE}${path}`
  const res = await fetch(url, { headers: authHeaders() })
  return parseResponse(res, url)
}

export async function apiPost(path: string, body: unknown, timeoutMs = 240000): Promise<any> {
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
    return parseResponse(res, url)
  } catch (err: any) {
    if (err?.name === 'AbortError') throw new Error(`请求超时：${url}`)
    if (err?.message === 'Failed to fetch') {
      throw new Error(`无法连接后端：${url}\n请检查 ECS 后端、Nginx 和 API_BASE。`)
    }
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
      if (quoted && line[i + 1] === '"') {
        cur += '"'
        i += 1
      } else {
        quoted = !quoted
      }
    } else if (ch === ',' && !quoted) {
      out.push(cur.trim())
      cur = ''
    } else {
      cur += ch
    }
  }

  out.push(cur.trim())
  return out
}

export function csvRows(text: string): Record<string, string>[] {
  const lines = String(text || '')
    .split(/\r?\n/)
    .map((x) => x.trim())
    .filter(Boolean)

  if (lines.length < 2) return []

  const headers = splitCsvLine(lines[0]).map((x) => x.trim())
  return lines.slice(1).map((line) => {
    const cells = splitCsvLine(line)
    const row: Record<string, string> = {}
    headers.forEach((h, i) => {
      row[h] = cells[i] || ''
    })
    return row
  })
}

export function computeVideoPlan(targetDuration: number, materialSeconds = 0, aiShotSeconds = 7) {
  const duration = Math.max(8, Math.min(180, Math.round(Number(targetDuration || 28))))
  const material = Math.max(0, Math.round(Number(materialSeconds || 0)))
  const shotSeconds = Math.max(3, Math.min(12, Math.round(Number(aiShotSeconds || 7))))
  const missingSeconds = Math.max(0, duration - material)
  const aiShots = missingSeconds > 0 ? Math.ceil(missingSeconds / shotSeconds) : 0
  const suggestedChars = Math.max(36, Math.round(duration * 4.2))
  const segmentCount = Math.max(3, Math.ceil(duration / 4))
  const avgSegmentSeconds = Number((duration / segmentCount).toFixed(1))

  return {
    duration,
    material,
    missingSeconds,
    aiShots,
    suggestedChars,
    segmentCount,
    avgSegmentSeconds,
    shotSeconds,
  }
}

export function generateLocalScript(topic: string, market = '马来西亚', duration = 28): string {
  const plan = computeVideoPlan(duration, 0, 7)
  const base = [
    `${topic}，先别急着做决定。`,
    `第一步先看预算和用途，别一上来只问价格。`,
    `第二步看区域：自住、出租和未来转手，判断逻辑完全不一样。`,
    `第三步核验真实资料：户型、价格、周边和交付信息都要以官方文件为准。`,
    `想少踩坑，先把预算、目标城市和自住/投资用途说清楚。`,
    `真实房源、户型、价格和周边信息，以项目官方资料和实地核验为准。`,
  ]
  const lines = base.slice(0, Math.max(3, Math.min(base.length, plan.segmentCount)))
  return lines.join('\n')
}

export function splitScriptToSegments(
  script: string,
  duration = 28,
  materialSeconds = 0,
  aiShotSeconds = 7,
): ProjectSegment[] {
  const plan = computeVideoPlan(duration, materialSeconds, aiShotSeconds)
  const rough = String(script || '')
    .split(/[\n。！？!?]+/)
    .map((x) => x.trim())
    .filter(Boolean)

  const fallback = generateLocalScript('马来西亚买房，别只看价格', '马来西亚', duration).split('\n')
  const lines = rough.length ? rough : fallback
  const picked = lines.slice(0, plan.segmentCount)

  while (picked.length < plan.segmentCount) {
    picked.push(lines[lines.length - 1] || '补充一个真实资料核验点。')
  }

  let remainingMaterial = Math.max(0, materialSeconds)

  return picked.map((text, i) => {
    const segDuration =
      i === picked.length - 1
        ? Math.max(1.8, Number((plan.duration - plan.avgSegmentSeconds * (picked.length - 1)).toFixed(1)))
        : plan.avgSegmentSeconds

    const useMaterial = remainingMaterial >= segDuration
    if (useMaterial) remainingMaterial -= segDuration

    return {
      index: i + 1,
      text,
      duration: Math.max(1.8, segDuration),
      material: useMaterial ? `已选素材 ${i + 1}` : `fal.ai 补镜头 ${i + 1}`,
      edit:
        i === 0
          ? '强钩子快切 + 字幕加粗'
          : i === picked.length - 1
            ? '结尾号召 + 评论区引导'
            : '按语义切镜 + 轻推拉',
    }
  })
}

export function projectWithScript(project: ProjectDraft, script: string): ProjectDraft {
  const segments = splitScriptToSegments(
    script,
    project.targetDuration,
    project.materialSeconds,
    project.aiShotSeconds,
  )

  return {
    ...project,
    script,
    title: project.topic,
    segments,
  }
}

export function buildFullAiPayload(project: ProjectDraft) {
  const plan = computeVideoPlan(project.targetDuration, project.materialSeconds, project.aiShotSeconds)
  const script = project.script || generateLocalScript(project.topic, project.market, plan.duration)
  const segments = project.segments.length
    ? project.segments
    : splitScriptToSegments(script, plan.duration, project.materialSeconds, project.aiShotSeconds)

  const shots = segments.map((seg) => ({
    index: seg.index,
    prompt: `${project.market} 房产短视频通用氛围镜头：${seg.text}。注意不能编造具体楼盘、户型、价格和周边配套。`,
    text: seg.text,
    duration: seg.duration,
    duration_seconds: seg.duration,
    shot_hint: seg.edit,
    source: seg.material.includes('fal.ai') ? 'fal_ai_fill' : 'user_material',
  }))

  return {
    title: project.title || project.topic,
    prompt: script,
    copy: script,
    market: project.market,
    platform: project.platform,
    target_duration: plan.duration,
    target_duration_seconds: plan.duration,
    max_shots: Math.max(1, Math.min(6, plan.aiShots || shots.length)),
    allow_fal: project.allowFal,
    source: 'frontend_engineering_workspace',
    shots,
    segments,
    timeline: {
      total_duration: plan.duration,
      segment_count: segments.length,
      segments,
    },
  }
}
