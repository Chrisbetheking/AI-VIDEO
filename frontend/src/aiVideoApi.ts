const envApiBase = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '')
const defaultApiBase = 'https://ai-video.47-76-143-158.sslip.io'
const isLocal =
  typeof window !== 'undefined' && /^(localhost|127\.0\.0\.1)$/i.test(window.location.hostname)

export const API_BASE = envApiBase || (isLocal ? 'http://localhost:8000' : defaultApiBase)
export const TOKEN_KEY = 'ai_video_api_token'
export const BACKEND_MAX_FULL_AI_SHOTS = 50

export type WorkspaceTab = 'pureai' | 'collect' | 'assets' | 'digital' | 'leads' | 'settings'

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
  digitalHumanRole?: string
  digitalHumanMode?: string
  [key: string]: any
}

export type VideoPlan = {
  duration: number
  material: number
  missingSeconds: number
  aiShotsRaw: number
  aiShots: number
  backendMaxShots: number
  suggestedChars: number
  segmentCount: number
  avgSegmentSeconds: number
  shotSeconds: number
  willMergeShotsForBackend: boolean
}

export type GenerationProgress = {
  jobId?: string
  status: string
  percent: number
  message: string
  videoUrl?: string
  raw?: any
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
  if (value instanceof Error) return value.message
  if (Array.isArray(value)) {
    return value
      .map((item: any) => {
        if (typeof item === 'string') return item
        const loc = Array.isArray(item?.loc) ? item.loc.join('.') : ''
        const msg = item?.msg || item?.message || item?.detail || JSON.stringify(item)
        return loc ? `${loc}: ${msg}` : String(msg)
      })
      .join('；')
  }
  if (typeof value === 'object') {
    const obj: any = value
    if (obj.message || obj.msg || obj.detail) return detailToText(obj.message || obj.msg || obj.detail)
    try {
      return JSON.stringify(value, null, 2)
    } catch {
      return String(value)
    }
  }
  return String(value)
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

export async function apiGet(path: string, timeoutMs = 120000): Promise<any> {
  const url = `${API_BASE}${path}`
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), timeoutMs)
  try {
    const res = await fetch(url, { headers: authHeaders(), signal: controller.signal })
    return parseResponse(res, url)
  } catch (err: any) {
    if (err?.name === 'AbortError') throw new Error(`请求超时：${url}`)
    if (err?.message === 'Failed to fetch') {
      throw new Error(`无法连接后端：${url}\n请检查 ECS 后端、Nginx、CORS 和 API_BASE。`)
    }
    throw err
  } finally {
    window.clearTimeout(timer)
  }
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
      throw new Error(`无法连接后端：${url}\n请检查 ECS 后端、Nginx、CORS 和 API_BASE。`)
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
    leads: [],
    contentInsights: [],
  }
}

export function computeVideoPlan(
  targetDuration: number,
  materialSeconds: number,
  aiShotSeconds: number,
): VideoPlan {
  const duration = Math.max(8, Math.min(180, Math.round(Number(targetDuration || 28))))
  const material = Math.max(0, Math.round(Number(materialSeconds || 0)))
  const shotSeconds = Math.max(3, Math.min(12, Math.round(Number(aiShotSeconds || 7))))
  const missingSeconds = Math.max(0, duration - material)
  const aiShotsRaw = missingSeconds > 0 ? Math.ceil(missingSeconds / shotSeconds) : 0
  const aiShots = Math.min(BACKEND_MAX_FULL_AI_SHOTS, aiShotsRaw)
  const suggestedChars = Math.max(36, Math.round(duration * 4.2))
  const segmentCount = Math.max(3, Math.ceil(duration / 3.8))
  const avgSegmentSeconds = Math.max(2.2, Number((duration / segmentCount).toFixed(1)))

  return {
    duration,
    material,
    missingSeconds,
    aiShotsRaw,
    aiShots,
    backendMaxShots: BACKEND_MAX_FULL_AI_SHOTS,
    suggestedChars,
    segmentCount,
    avgSegmentSeconds,
    shotSeconds,
    willMergeShotsForBackend: aiShotsRaw > BACKEND_MAX_FULL_AI_SHOTS,
  }
}

function pick<T>(items: T[], seed: number, offset = 0): T {
  return items[Math.abs(seed + offset) % items.length]
}

function makeSeed(topic: string, market: string, duration: number, nonce?: number) {
  const base = `${topic}|${market}|${duration}|${nonce ?? Date.now()}|${Math.random()}`
  let hash = 0
  for (let i = 0; i < base.length; i += 1) hash = (hash * 31 + base.charCodeAt(i)) | 0
  return Math.abs(hash)
}

export function generateLocalScript(
  topic: string,
  market: string,
  duration: number,
  nonce?: number,
): string {
  const plan = computeVideoPlan(duration, 0, 7)
  const seed = makeSeed(topic, market, duration, nonce)

  const openings = [
    `${topic}，别先急着问价格，第一步先判断你买它到底解决什么问题。`,
    `很多人看${market}房产，一上来就看价格，其实这一步最容易错。`,
    `${topic}这件事，真正拉开差距的不是谁先下手，而是谁先把逻辑想清楚。`,
    `如果你准备看${market}房产，先别被样板间和宣传图带着走。`,
    `今天不讲鸡血，直接讲${topic}最容易踩的判断误区。`,
  ]

  const points = [
    `先看预算和用途：自住、出租、第二居所和家庭配置，判断标准完全不一样。`,
    `再看区域和人群：谁会住、谁会租、未来谁来接手，这比单看总价更重要。`,
    `第三看资料真实性：户型、价格、交付、周边和管理费，都要回到官方文件核验。`,
    `别只问“值不值”，先问“适不适合我现在的用途和现金流”。`,
    `如果是投资，要把租客来源、空置风险和转手难度放在一起看。`,
    `如果是家庭配置，要把教育、养老、通勤和长期生活半径放在一起算。`,
    `同样预算，买错区域，后面的出租和转手都会很被动。`,
    `同样项目，买错户型，现金流和流动性也可能完全不一样。`,
    `真正靠谱的判断，不靠一句“推荐”，而是靠预算、用途、城市和退出路径。`,
  ]

  const endings = [
    `想少踩坑，先把预算、目标城市和自住/投资用途讲清楚，再去匹配项目。`,
    `评论区留下你的预算和用途，我按自住、投资、家庭配置三个方向帮你拆。`,
    `别急着定项目，先把需求筛清楚，后面看房才不会被带节奏。`,
    `真实房源、户型、价格和周边信息，最终都以官方资料和实地核验为准。`,
  ]

  const shuffledPoints = Array.from({ length: points.length }, (_, i) => pick(points, seed, i * 3 + 2))
  const uniquePoints = Array.from(new Set(shuffledPoints))
  const neededMiddle = Math.max(1, plan.segmentCount - 2)
  const lines = [pick(openings, seed, 1), ...uniquePoints.slice(0, neededMiddle), pick(endings, seed, 99)]
  return lines.slice(0, plan.segmentCount).join('\n')
}

export function splitScriptToSegments(
  script: string,
  duration: number,
  materialSeconds: number,
  aiShotSeconds: number,
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
    picked.push(lines[picked.length % lines.length] || '补充一个真实资料核验点')
  }

  let remainingMaterial = Math.max(0, materialSeconds)

  return picked.map((text, i) => {
    const rawDuration =
      i === picked.length - 1 ? plan.duration - plan.avgSegmentSeconds * (picked.length - 1) : plan.avgSegmentSeconds
    const segDuration = Math.max(1.8, Number(rawDuration.toFixed(1)))
    const useMaterial = remainingMaterial >= segDuration
    if (useMaterial) remainingMaterial -= segDuration

    return {
      index: i + 1,
      text,
      duration: segDuration,
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

export function projectWithScript(
  project: ProjectDraft,
  script: string,
  options: Partial<ProjectDraft> = {},
): ProjectDraft {
  const targetDuration = safeNumber(options.targetDuration ?? project.targetDuration, project.targetDuration)
  const materialSeconds = safeNumber(options.materialSeconds ?? project.materialSeconds, project.materialSeconds)
  const aiShotSeconds = safeNumber(options.aiShotSeconds ?? project.aiShotSeconds, project.aiShotSeconds)
  const segments = splitScriptToSegments(script, targetDuration, materialSeconds, aiShotSeconds)

  return {
    ...project,
    ...options,
    script,
    segments,
    title: safeText(options.title ?? project.title, project.topic),
    targetDuration,
    materialSeconds,
    aiShotSeconds,
  }
}

function groupSegmentsForShots(segments: ProjectSegment[], maxShots = BACKEND_MAX_FULL_AI_SHOTS) {
  const safeSegments = segments.length ? segments : splitScriptToSegments('', 28, 0, 7)
  const shotCount = Math.max(1, Math.min(maxShots, safeSegments.length))
  const groups: ProjectSegment[][] = Array.from({ length: shotCount }, () => [])

  safeSegments.forEach((seg, index) => {
    const groupIndex = Math.min(shotCount - 1, Math.floor((index * shotCount) / safeSegments.length))
    groups[groupIndex].push(seg)
  })

  return groups.filter((g) => g.length)
}

export function buildFullAiPayload(
  project: ProjectDraft,
  plan = computeVideoPlan(project.targetDuration, project.materialSeconds, project.aiShotSeconds),
) {
  const script = safeText(project.script, generateLocalScript(project.topic, project.market, plan.duration))
  const segments =
    project.segments?.length
      ? project.segments
      : splitScriptToSegments(script, plan.duration, project.materialSeconds, project.aiShotSeconds)

  const maxShots = Math.max(1, Math.min(BACKEND_MAX_FULL_AI_SHOTS, plan.aiShotsRaw || segments.length))
  const groups = groupSegmentsForShots(segments, maxShots)
  const shotDuration = Math.max(3, Number((plan.duration / groups.length).toFixed(1)))

  const shots = groups.map((group, index) => {
    const text = group.map((seg) => seg.text).join('，')
    return {
      index: index + 1,
      duration: shotDuration,
      seconds: shotDuration,
      text,
      narration: text,
      prompt: [
        `竖屏短视频通用氛围镜头，第 ${index + 1} 段。`,
        `主题：${project.topic}。`,
        `画面只表现通用房产咨询、城市生活、资料核验氛围，不出现任何文字。`,
        '画面要求：竖屏9:16、铺满画面、现代、干净、真实感、可用于房产知识类短视频。no text, no subtitles, no captions, no logo, no watermark.',
        '禁止：不要出现任何文字、字幕、logo、水印、UI、招牌、价格、楼盘名；不要编造具体楼盘、户型、价格、学校、交通、周边、收益率。',
        '只生成竖屏 9:16 通用城市/生活/看房/资料核验氛围镜头，画面必须铺满竖屏，不要黑边。',
      ].join('\n'),
      shot_hint: index === 0 ? 'hook_city_lifestyle' : index === groups.length - 1 ? 'call_to_action' : 'explain_detail',
      source_segments: group.map((seg) => seg.index),
    }
  })

  return {
    market: project.market,
    platform: project.platform,
    topic: project.topic,
    title: project.title || project.topic,
    prompt: `${project.topic}\n${script}`,
    copy: script,
    script_text: script,
    target_duration: plan.duration,
    target_duration_seconds: plan.duration,
    duration_seconds: plan.duration,
    material_seconds: plan.material,
    ai_shot_seconds: plan.shotSeconds,
    allow_fal_fill: project.allowFal,
    fal_fill_shots_requested: plan.aiShotsRaw,
    fal_fill_shots: Math.max(4, Number(shots.length || 0)),
    backend_max_shots: plan.backendMaxShots,
    merged_for_backend: plan.willMergeShotsForBackend,
    segments,
    shots,
    shot_plan: shots,
    mode: 'pure_ai_or_fal_fill_script_first',
    truth_rules: {
      no_fake_property: true,
      no_fake_floorplan: true,
      no_fake_price: true,
      no_fake_surroundings: true,
      generic_atmosphere_only_for_ai_shots: true,
    },
  }
}

export function extractJobId(data: any): string {
  return safeText(
    data?.job_id ||
      data?.id ||
      data?.full_ai_job_id ||
      data?.job?.job_id ||
      data?.job?.id ||
      data?.data?.job_id ||
      data?.result?.job_id,
  )
}

export function extractVideoUrl(data: any): string {
  if (!data) return ''
  const candidates = [
    data.video_url,
    data.output_url,
    data.final_video_url,
    data.r2_url,
    data.public_url,
    data.url,
    data.download_url,
    data.result?.video_url,
    data.result?.output_url,
    data.result?.final_video_url,
    data.result?.r2_url,
    data.result?.public_url,
    data.data?.video_url,
    data.data?.output_url,
    data.job?.video_url,
    data.job?.output_url,
  ]

  for (const value of candidates) {
    const text = safeText(value)
    if (/^https?:\/\//i.test(text)) return text
  }

  return ''
}

export function progressFromJob(data: any, fallbackJobId = ''): GenerationProgress {
  const status = safeText(data?.status || data?.state || data?.job?.status || data?.result?.status, 'running').toLowerCase()
  const videoUrl = extractVideoUrl(data)
  const jobId = extractJobId(data) || fallbackJobId

  if (videoUrl || ['done', 'success', 'completed', 'finished'].includes(status)) {
    return { jobId, status: status || 'done', percent: 100, message: '成片已生成，可以预览。', videoUrl, raw: data }
  }

  if (['failed', 'error', 'canceled', 'cancelled'].includes(status)) {
    return { jobId, status, percent: 100, message: '生成失败，请查看错误信息。', raw: data }
  }

  const step = safeText(data?.step || data?.stage || data?.current_step || data?.message || data?.job?.step)
  let percent = 25
  if (/fal|shot|镜头|storyboard/i.test(step)) percent = 45
  if (/tts|voice|audio|配音/i.test(step)) percent = 62
  if (/compose|render|合成|剪辑/i.test(step)) percent = 78
  if (/upload|r2|字幕|subtitle/i.test(step)) percent = 88
  if (typeof data?.progress === 'number') percent = Math.max(percent, Math.min(98, Math.round(data.progress)))

  return {
    jobId,
    status: status || 'running',
    percent,
    message: step || '任务已提交，正在生成视频。',
    raw: data,
  }
}

export async function pollFullAiJob(
  jobId: string,
  onProgress: (progress: GenerationProgress) => void,
  options: { intervalMs?: number; maxAttempts?: number } = {},
) {
  const intervalMs = options.intervalMs ?? 3500
  const maxAttempts = options.maxAttempts ?? 180

  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    await new Promise((resolve) => window.setTimeout(resolve, intervalMs))
    const data = await apiGet(`/api/video/full-ai/tts-first/job/${encodeURIComponent(jobId)}`, 60000)
    const progress = progressFromJob(data, jobId)
    onProgress(progress)

    if (progress.videoUrl || ['done', 'success', 'completed', 'finished', 'failed', 'error'].includes(progress.status)) {
      return data
    }
  }

  throw new Error('轮询超时：任务可能还在后台生成，请稍后到任务历史查看。')
}


export async function generateAIScriptPlan(project: ProjectDraft, dryRun = false): Promise<any> {
  return apiPost('/api/video/full-ai/script-ai/plan', {
    market: project.market,
    platform: project.platform || 'douyin',
    topic: project.topic,
    duration_seconds: project.targetDuration,
    target_customer: project.targetCustomer || '海外房产潜在客户',
    industry_notes: [
      '海外房产避坑',
      '预算、区域、用途三步判断',
      '首付、贷款、租客来源',
      '家庭资产配置、第二家园、养老度假',
      ...(project.contentInsights || []).map((x: any) => x?.topic || x?.script_hook || JSON.stringify(x)).slice(0, 8),
    ].join('\n'),
    competitor_notes: [
      '同行高分账号拆解：痛点标题、反差开头、评论区承接、私域引导',
      ...(project.competitorNotes ? [project.competitorNotes] : []),
    ].join('\n'),
    lead_notes: [
      ...(project.leads || []).map((x: any) => x?.text || x?.original_text || x?.script_hook || JSON.stringify(x)).slice(0, 8),
    ].join('\n'),
    style: '短、狠、直接、口语化、有转化、适合抖音',
    dry_run: dryRun,
  }, 180000)
}

export function projectFromAIScriptPlan(project: ProjectDraft, data: any): ProjectDraft {
  const script = safeText(data?.script, generateLocalScript(project.topic, project.market, project.targetDuration))
  const rawSegments = Array.isArray(data?.segments) ? data.segments : []

  const fallbackSegments = splitScriptToSegments(script, project.targetDuration, project.materialSeconds, project.aiShotSeconds)
  const segments = rawSegments.length
    ? rawSegments.map((seg: any, i: number) => ({
        index: i + 1,
        text: safeText(seg.text, fallbackSegments[i]?.text || ''),
        duration: safeNumber(seg.duration, fallbackSegments[i]?.duration || 3.8),
        material: fallbackSegments[i]?.material || `fal.ai 补镜头 ${i + 1}`,
        edit: safeText(seg.edit, fallbackSegments[i]?.edit || '按语义切镜'),
      }))
    : fallbackSegments

  return {
    ...project,
    title: safeText(data?.title, project.topic),
    script,
    segments,
    industryAngle: safeText(data?.industry_angle, project.industryAngle),
    hook: safeText(data?.hook, project.hook),
    cta: safeText(data?.cta, project.cta),
    riskNote: safeText(data?.risk_note, project.riskNote),
    scriptProvider: data?.provider || 'unknown',
  }
}


export function normalizeAiShotCountByDuration(inputShots: any[], targetSeconds: number, materialSeconds = 0) {
  const shots = Array.isArray(inputShots) ? [...inputShots] : []
  const missingSeconds = Math.max(0, Number(targetSeconds || 0) - Number(materialSeconds || 0))

  // fal 一条 AI 视频通常按 5 秒左右规划；20s 至少 4 镜头
  const required = Math.max(1, Math.ceil(missingSeconds / 5))

  // 20 秒以上不要低于 4 个镜头，避免 3 镜头硬撑 20 秒导致画面重复/不搭
  const minShots = Number(targetSeconds || 0) >= 20 ? 4 : required
  const finalCount = Math.max(required, minShots)

  if (shots.length === 0) {
    for (let i = 0; i < finalCount; i += 1) {
      shots.push({
        prompt: `Malaysia real estate cinematic shot ${i + 1}, Kuala Lumpur condo, KLCC skyline, premium 9:16 vertical video`,
      })
    }
    return shots
  }

  while (shots.length < finalCount) {
    const base = shots[shots.length % Math.max(1, inputShots.length)] || shots[shots.length - 1] || {}
    shots.push({
      ...base,
      prompt:
        typeof base.prompt === 'string'
          ? `${base.prompt}\nAdditional Malaysia real estate visual angle ${shots.length + 1}: KLCC skyline, luxury condo balcony, apartment interior, lobby, pool, or city skyline.`
          : `Malaysia real estate cinematic shot ${shots.length + 1}, KLCC skyline, luxury condominium, 9:16 vertical video`,
    })
  }

  return shots
}

