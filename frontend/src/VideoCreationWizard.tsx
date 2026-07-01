import React, { useEffect, useMemo, useState } from 'react'
import './video-creation-wizard.css'

type WizardStep = 1 | 2 | 3 | 4
type SourceMode = 'account' | 'viral' | 'custom'
type CityKey = 'kuala_lumpur' | 'penang' | 'johor' | 'langkawi' | 'sabah'
type ContentType = 'investment' | 'own_stay' | 'second_home' | 'rental' | 'education'
type MaterialStrategy = 'real_first' | 'ai_fill' | 'full_ai'
type SourceType = 'real' | 'ai' | 'mixed'

type ExpressionSettings = {
  emotion: string
  tone: string
  speed: number
  pitch: number
  volume: number
  pauseAfter: number
  emphasis: string
  aiReason: string
  keywords: string[]
}

type ScriptSegment = {
  id: string
  index: number
  text: string
  startSec: number
  endSec: number
  expression: ExpressionSettings
}

type KeywordInsight = {
  keyword: string
  type: string
  reason: string
  priority: 'high' | 'medium' | 'low'
}

type ShotDraft = {
  id: string
  index: number
  scene: string
  prompt: string
  narration: string
  duration: number
  camera: string
  transition: string
  sourceType: SourceType
  keywords: string[]
  note: string
}

type JobPayload = {
  ok?: boolean
  job_id?: string
  status?: string
  stage?: string
  progress?: number
  error?: string
  video_url?: string
  url?: string
  output_url?: string
  result_url?: string
  audio_duration_seconds?: number
  shot_count?: number
  city?: string
  script_text?: string
  child_job?: any
  result?: any
  [key: string]: any
}

const STEP_TITLES: Record<WizardStep, string> = {
  1: '搞定视频内容',
  2: '生成口播配音',
  3: '选择画面风格',
  4: '生成成片预览',
}

const STEP_SUBTITLES: Record<WizardStep, string> = {
  1: '输入主题、学习同行、生成选题和文案',
  2: '确认口播稿；点击句子后单独调语速、语调、语气和重点',
  3: '锁定城市画面，手动修改每个镜头、转场、素材策略和数字人',
  4: '一键生成，查看成片、时长、镜头和发布准备',
}

const CITY_PROFILES: Record<CityKey, {
  label: string
  shortLabel: string
  anchors: string[]
  scenes: string[]
}> = {
  kuala_lumpur: {
    label: '吉隆坡 / Kuala Lumpur',
    shortLabel: '吉隆坡',
    anchors: ['KLCC', 'TRX', 'Mont Kiara', '公寓阳台', '大堂', '泳池'],
    scenes: [
      'KLCC 双子塔天际线 + 高层公寓建立镜头',
      'TRX 金融区 + 高端住宅区位镜头',
      'Mont Kiara 高端公寓社区生活氛围',
      '公寓阳台看吉隆坡城市天际线',
      '现代公寓客厅 + 落地窗城市景观',
      '高端公寓大堂 / 泳池 / 健身房设施',
    ],
  },
  penang: {
    label: '槟城 / Penang',
    shortLabel: '槟城',
    anchors: ['Gurney Drive', '海景公寓', '养老生活', '滨海天际线', '阳台'],
    scenes: [
      '槟城滨海住宅天际线',
      '海景公寓阳台生活方式',
      '现代公寓室内 + 海景窗景',
      '养老和第二家园生活氛围',
    ],
  },
  johor: {
    label: '新山 / Johor Bahru',
    shortLabel: '新山',
    anchors: ['新山城市', 'Medini', '公寓社区', '通勤生活', '家庭自住'],
    scenes: [
      '新山城市住宅区位镜头',
      'Medini 现代公寓社区',
      '家庭自住公寓室内空间',
      '城市通勤和生活配套氛围',
    ],
  },
  langkawi: {
    label: '兰卡威 / Langkawi',
    shortLabel: '兰卡威',
    anchors: ['度假住宅', '岛屿生活', '泳池', '第二家园', '热带景观'],
    scenes: [
      '兰卡威度假型住宅和泳池',
      '热带绿植中的第二家园生活',
      '岛屿度假住宅生活方式',
      '度假社区公共空间',
    ],
  },
  sabah: {
    label: '沙巴 / Sabah',
    shortLabel: '沙巴',
    anchors: ['亚庇', '滨海住宅', '日落景观', '第二家园', '度假生活'],
    scenes: [
      '亚庇城市滨海住宅氛围',
      '沙巴日落景观和住宅生活方式',
      '滨海公寓阳台生活场景',
      '度假型社区配套镜头',
    ],
  },
}

const CONTENT_LABELS: Record<ContentType, string> = {
  investment: '投资配置',
  own_stay: '自住',
  second_home: '第二家园',
  rental: '出租收益',
  education: '教育规划',
}

const MATERIAL_LABELS: Record<MaterialStrategy, string> = {
  real_first: '真实素材优先',
  ai_fill: 'AI 补足',
  full_ai: '全 AI 生成',
}

const CAMERA_OPTIONS = ['自然推进', '城市横移', '缓慢上摇', '稳定广角', '室内推近', '设施细节切入']
const TRANSITION_OPTIONS = ['自然过渡', '城市天际线衔接', '室外切室内', '室内切设施', '同色系淡入淡出', '关键词卡点']
const EMOTION_OPTIONS = ['自然平稳', '专业可信', '重点强调', '提问悬念', '亲和解释', '成交引导']
const TONE_OPTIONS = ['自然讲解', '专业判断', '可信背书', '轻快种草', '风险提醒', '结尾引导']

function readLocalStorage(key: string): string {
  try {
    return window.localStorage.getItem(key) || ''
  } catch {
    return ''
  }
}

function saveLocalStorage(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value)
  } catch {
    // ignore
  }
}

function normalizeApiBase(value: string): string {
  const trimmed = String(value || '').trim().replace(/\/+$/, '')
  return trimmed || 'https://ai-video.47-76-143-158.sslip.io'
}

function getDefaultApiBase(): string {
  const local = readLocalStorage('AI_VIDEO_API_BASE') || readLocalStorage('ai_video_api_base')
  if (local) return normalizeApiBase(local)

  try {
    const envBase = (import.meta as any).env?.VITE_AI_VIDEO_API_BASE
    if (envBase) return normalizeApiBase(envBase)
  } catch {
    // ignore
  }

  return 'https://ai-video.47-76-143-158.sslip.io'
}

function getDefaultToken(): string {
  return (
    readLocalStorage('AI_VIDEO_TOKEN') ||
    readLocalStorage('ai_video_token') ||
    readLocalStorage('AI_VIDEO_ADMIN_TOKEN') ||
    readLocalStorage('token') ||
    ''
  )
}

function hashString(input: string): string {
  let hash = 5381
  for (let i = 0; i < input.length; i += 1) {
    hash = ((hash << 5) + hash) + input.charCodeAt(i)
    hash &= 0xffffffff
  }
  return Math.abs(hash).toString(36)
}

function targetChars(duration: number): { min: number; max: number } {
  return {
    min: Math.max(40, Math.floor(duration * 4.3)),
    max: Math.max(60, Math.floor(duration * 5.3)),
  }
}

function getCityTopicHint(city: CityKey): string {
  if (city === 'kuala_lumpur') return 'KLCC、TRX、Mont Kiara、城市通勤、公寓生活、出租需求'
  if (city === 'penang') return '槟城海景、养老生活、第二家园、生活方式'
  if (city === 'johor') return '新山通勤、家庭自住、Medini、生活配套'
  if (city === 'langkawi') return '兰卡威度假住宅、第二家园、热带生活方式'
  return '沙巴亚庇、滨海住宅、日落景观、度假生活'
}

function generateScript(topic: string, city: CityKey, duration: number, contentType: ContentType): string {
  const profile = CITY_PROFILES[city]
  const label = CONTENT_LABELS[contentType]
  const title = topic.trim() || `${profile.shortLabel}买房，别只看价格`
  const { min, max } = targetChars(duration)

  let script = ''

  if (city === 'kuala_lumpur') {
    script = `${title}。很多人买马来西亚房产，第一眼只看价格，但在吉隆坡，真正要先看区域、用途和流动性。KLCC、TRX、Mont Kiara 这些位置，看的不是热闹，而是生活半径、出租需求和未来转手。`
    if (contentType === 'investment') {
      script += '如果是投资配置，先看租客是谁、通勤是否方便、周边配套是否成熟，再看价格是否合理。'
    } else if (contentType === 'own_stay') {
      script += '如果是自住，重点不是短期涨跌，而是生活便利、社区品质和长期居住舒适度。'
    } else if (contentType === 'education') {
      script += '如果考虑家庭和教育，要把通勤、社区、安全感和长期居住需求放在前面。'
    } else {
      script += '自住、出租、第二家园，判断标准完全不一样，先把需求筛清楚，再去看房才不会被带节奏。'
    }
  } else {
    script = `${title}。马来西亚买房不要只看价格，要先看城市、用途和生活方式。${profile.shortLabel}更适合${label}方向的人群，重点要看区域成熟度、生活配套、未来使用场景和转手流动性。`
    script += '先把预算、用途和持有周期想清楚，再去筛项目，才不会被表面卖点带偏。'
  }

  while (script.length < min) {
    if (city === 'kuala_lumpur') {
      script += ' 吉隆坡项目重点看区位价值、生活便利度、出租需求、社区品质和未来转手逻辑。'
    } else {
      script += ` ${profile.shortLabel}项目重点看生活方式、配套成熟度、长期使用场景和资产流动性。`
    }
  }

  if (script.length > max) {
    script = script.slice(0, max).replace(/[，,、\s]+$/g, '') + '。'
  }

  return script
}

function splitNarration(script: string): string[] {
  const normalized = String(script || '').replace(/\s+/g, ' ').trim()
  const chunks = normalized
    .split(/[。！？!?；;\n]+/)
    .map((item) => item.trim())
    .filter(Boolean)

  return chunks.length ? chunks : normalized ? [normalized] : []
}

function planShotCount(duration: number): number {
  const base = Math.ceil(Math.max(1, duration) / 4.5)
  if (duration >= 16) return Math.max(4, base)
  return Math.max(1, base)
}

function detectKeywordInsights(script: string, city: CityKey, contentType: ContentType): KeywordInsight[] {
  const text = String(script || '')
  const result: KeywordInsight[] = []

  const add = (keyword: string, type: string, reason: string, priority: KeywordInsight['priority'] = 'medium') => {
    if (!keyword || result.some((item) => item.keyword === keyword)) return
    result.push({ keyword, type, reason, priority })
  }

  const priceMatches = text.match(/\d+(?:\.\d+)?\s*(?:万|百万|亿|RM|马币|人民币|块|元)/g) || []
  priceMatches.forEach((item) => add(item, '价格/预算', '数字信息要放慢并重读，避免用户听漏', 'high'))

  ;['KLCC', 'TRX', 'Mont Kiara', '吉隆坡', '新山', '槟城', '兰卡威', '沙巴', '亚庇'].forEach((word) => {
    if (text.includes(word)) add(word, '区域', '区域名决定画面锚点和专业感', word === CITY_PROFILES[city].shortLabel ? 'high' : 'medium')
  })

  ;['华人', '华语', '中文', '族群', '种族', '本地人', '外籍', '租客'].forEach((word) => {
    if (text.includes(word)) add(word, '人群/语言', '涉及人群判断，语气要亲和但不能绝对化', 'high')
  })

  ;['出租', '租金', '转手', '流动性', '投资', '收益', '回报', '自住', '教育', '养老', '第二家园'].forEach((word) => {
    if (text.includes(word)) add(word, '用途/收益', '这是买房决策核心，需要强调判断逻辑', 'high')
  })

  if (contentType === 'investment') add('投资配置', '内容方向', '强调区域、租客、流动性，不承诺具体 ROI', 'high')
  if (contentType === 'own_stay') add('自住体验', '内容方向', '强调生活半径、通勤、社区舒适度', 'medium')
  if (city === 'kuala_lumpur') add('城市房产', '画面规则', '吉隆坡默认不出海，画面锁定城市公寓和天际线', 'high')

  return result.slice(0, 12)
}

function analyzeExpression(text: string, index: number, total: number, keywordInsights: KeywordInsight[]): ExpressionSettings {
  const keywords = keywordInsights
    .filter((item) => text.includes(item.keyword) || item.keyword.includes('城市房产') || item.keyword.includes('投资配置'))
    .slice(0, 5)
    .map((item) => item.keyword)

  let emotion = '自然平稳'
  let tone = '自然讲解'
  let speed = 1
  let pitch = 1
  let volume = 1
  let pauseAfter = 0.15
  let emphasis = '平稳讲清楚，不夸张'
  let aiReason = '普通信息句，保持自然讲解即可'

  if (/\d+(?:\.\d+)?\s*(?:万|百万|亿|RM|马币|人民币|块|元)/.test(text)) {
    emotion = '重点强调'
    tone = '专业判断'
    speed = 0.92
    volume = 1.08
    pauseAfter = 0.3
    emphasis = '数字、价格、面积要重读，前后留停顿'
    aiReason = '识别到价格/预算/面积类数字，用户最容易在这里做判断'
  } else if (/[？?]/.test(text) || text.includes('为什么') || text.includes('是不是')) {
    emotion = '提问悬念'
    tone = '风险提醒'
    speed = 0.96
    pitch = 1.04
    pauseAfter = 0.28
    emphasis = '问题结尾微上扬，制造继续听的理由'
    aiReason = '这是钩子/提问句，适合制造悬念'
  } else if (/华人|华语|中文|族群|种族|本地人|外籍/.test(text)) {
    emotion = '亲和解释'
    tone = '可信背书'
    speed = 0.95
    volume = 1.02
    pauseAfter = 0.25
    emphasis = '涉及人群和语言环境，语气要客观、亲和、避免绝对化'
    aiReason = '识别到人群/语言相关信息，需要更谨慎地解释'
  } else if (/KLCC|TRX|Mont Kiara|区域|地段|流动性|出租|转手|投资|收益|租金/.test(text)) {
    emotion = '重点强调'
    tone = '专业判断'
    speed = 0.94
    volume = 1.05
    pauseAfter = 0.24
    emphasis = '区域、用途、流动性这些决策词要加重'
    aiReason = '这是房产判断的核心逻辑句，需要突出专业感'
  } else if (index === 0) {
    emotion = '提问悬念'
    tone = '自然讲解'
    speed = 1.02
    pitch = 1.03
    pauseAfter = 0.22
    emphasis = '开头要轻快一点，快速抓住注意力'
    aiReason = '第一句承担开场钩子作用'
  } else if (index === total - 1) {
    emotion = '成交引导'
    tone = '结尾引导'
    speed = 0.96
    volume = 1.05
    pauseAfter = 0.35
    emphasis = '结尾放慢一点，方便用户记住行动点'
    aiReason = '最后一句适合收束观点和引导私信/咨询'
  }

  return { emotion, tone, speed, pitch, volume, pauseAfter, emphasis, aiReason, keywords }
}

function getSavedExpressionMap(scriptKey: string): Record<string, ExpressionSettings> {
  try {
    const raw = readLocalStorage(scriptKey)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as Record<string, ExpressionSettings>
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

function buildScriptSegments(
  script: string,
  duration: number,
  keywordInsights: KeywordInsight[],
  overrides: Record<string, ExpressionSettings>,
  scriptKey: string,
): ScriptSegment[] {
  const lines = splitNarration(script)
  const totalChars = Math.max(1, lines.reduce((sum, item) => sum + Math.max(1, item.length), 0))
  const saved = getSavedExpressionMap(scriptKey)
  let cursor = 0

  return lines.map((text, index) => {
    const segDuration = Math.max(1.2, Math.round((duration * (Math.max(1, text.length) / totalChars)) * 10) / 10)
    const startSec = Math.round(cursor * 10) / 10
    cursor += segDuration
    const endSec = Math.round(cursor * 10) / 10
    const id = `${index + 1}_${hashString(text)}`
    const auto = analyzeExpression(text, index, lines.length, keywordInsights)

    return {
      id,
      index: index + 1,
      text,
      startSec,
      endSec,
      expression: overrides[id] || saved[id] || auto,
    }
  })
}

function makeShotPrompt(city: CityKey, scene: string, narration: string, camera: string, transition: string): string {
  const cityLabel = CITY_PROFILES[city].label
  const cityRule = city === 'kuala_lumpur'
    ? 'Kuala Lumpur city real-estate visuals only: KLCC, TRX, Mont Kiara, city skyline, condo balcony, interior, lobby, pool. No seaside, no island, no beach.'
    : `Malaysia real-estate visuals for ${cityLabel}. Match the city lifestyle and avoid unrelated locations.`

  return [
    'Premium 9:16 cinematic vertical video for Malaysia real-estate content.',
    `Main scene: ${scene}.`,
    `Narration meaning: ${narration.slice(0, 100)}.`,
    `Camera movement: ${camera}.`,
    `Transition intent: ${transition}.`,
    cityRule,
    'Ultra realistic, premium real estate commercial style, natural lighting, clean composition, high detail, smooth movement.',
    'No readable text, no logo, no watermark, no fake project name, no exact price, no exact ROI, no exact school name, no black borders.',
  ].join('\n')
}

function splitForShots(script: string, count: number): string[] {
  const lines = splitNarration(script)
  if (!lines.length) return Array.from({ length: count }, () => script)

  const result = Array.from({ length: count }, () => '')
  lines.forEach((line, index) => {
    const slot = index % count
    result[slot] = result[slot] ? `${result[slot]}。${line}` : line
  })
  return result.map((item, index) => item || lines[Math.min(index, lines.length - 1)])
}

function buildShotDrafts(script: string, city: CityKey, duration: number, materialStrategy: MaterialStrategy): ShotDraft[] {
  const count = planShotCount(duration)
  const profile = CITY_PROFILES[city]
  const narrations = splitForShots(script, count)
  const eachDuration = Math.round((duration / count) * 10) / 10
  const sourceType: SourceType = materialStrategy === 'real_first' ? 'mixed' : materialStrategy === 'full_ai' ? 'ai' : 'mixed'

  return Array.from({ length: count }, (_, index) => {
    const scene = profile.scenes[index % profile.scenes.length]
    const camera = CAMERA_OPTIONS[index % CAMERA_OPTIONS.length]
    const transition = TRANSITION_OPTIONS[index % TRANSITION_OPTIONS.length]
    const narration = narrations[index] || ''

    return {
      id: `${index + 1}_${hashString(scene + narration)}`,
      index: index + 1,
      scene,
      prompt: makeShotPrompt(city, scene, narration, camera, transition),
      narration,
      duration: eachDuration,
      camera,
      transition,
      sourceType,
      keywords: detectKeywordInsights(narration, city, 'investment').slice(0, 4).map((item) => item.keyword),
      note: '可手动修改镜头主体、运镜、转场和素材来源',
    }
  })
}

function buildTransitionPlan(shots: ShotDraft[]) {
  return shots.map((shot, index) => ({
    index: shot.index,
    from_scene: index === 0 ? '开场' : shots[index - 1].scene,
    to_scene: shot.scene,
    transition: shot.transition,
    camera: shot.camera,
    reason: index === 0 ? '建立主题和城市定位' : '保持画面自然衔接，避免硬切',
  }))
}

function extractVideoUrl(job: JobPayload | null): string {
  if (!job) return ''

  const direct =
    job.video_url ||
    job.output_url ||
    job.result_url ||
    job.url ||
    job.result?.video_url ||
    job.result?.output_url ||
    job.result?.result_url ||
    job.child_job?.video_url ||
    job.child_job?.output_url ||
    job.child_job?.result_url ||
    job.child_job?.url ||
    job.child_job?.result?.video_url ||
    job.child_job?.result?.output_url ||
    job.child_job?.result?.result_url

  return typeof direct === 'string' ? direct : ''
}

function isFinalStatus(job: JobPayload | null): boolean {
  if (!job) return false
  const text = `${job.status || ''} ${job.stage || ''} ${job.child_job?.status || ''} ${job.child_job?.stage || ''}`.toLowerCase()
  return ['completed', 'succeeded', 'success', 'done', 'finished'].some((key) => text.includes(key))
}

function isFailedStatus(job: JobPayload | null): boolean {
  if (!job) return false
  const text = `${job.status || ''} ${job.stage || ''} ${job.child_job?.status || ''} ${job.child_job?.stage || ''}`.toLowerCase()
  return ['failed', 'error', 'cancelled'].some((key) => text.includes(key))
}

function authHeaders(token: string): HeadersInit {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }

  const clean = token.trim()
  if (clean) {
    headers['X-AI-Video-Token'] = clean
    headers.Authorization = `Bearer ${clean}`
  }

  return headers
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

function formatTimeRange(segment: ScriptSegment): string {
  return `${segment.startSec.toFixed(1)}s - ${segment.endSec.toFixed(1)}s`
}

function getSourcePlaceholder(sourceMode: SourceMode): string {
  if (sourceMode === 'account') return '粘贴抖音 / Instagram / TikTok 主页链接'
  if (sourceMode === 'viral') return '粘贴同行爆款视频链接'
  return '可填写补充要求，比如：偏投资、偏自住、偏第二家园'
}

function getSourceLabel(sourceMode: SourceMode): string {
  if (sourceMode === 'account') return '同行主页，可不填'
  if (sourceMode === 'viral') return '爆款链接，可不填'
  return '自定义要求，可不填'
}

export default function VideoCreationWizard() {
  const [step, setStep] = useState<WizardStep>(1)
  const [sourceMode, setSourceMode] = useState<SourceMode>('account')
  const [apiBase, setApiBase] = useState(getDefaultApiBase)
  const [token, setToken] = useState(getDefaultToken)

  const [topic, setTopic] = useState('马来西亚吉隆坡买房，别只看价格')
  const [sourceInput, setSourceInput] = useState('')
  const [targetDuration, setTargetDuration] = useState(20)
  const [city, setCity] = useState<CityKey>('kuala_lumpur')
  const [contentType, setContentType] = useState<ContentType>('investment')

  const [script, setScript] = useState('')
  const [voice, setVoice] = useState('default')
  const [voiceStyle, setVoiceStyle] = useState('专业可信')
  const [speechSpeed, setSpeechSpeed] = useState(1)
  const [selectedSegmentId, setSelectedSegmentId] = useState('')
  const [segmentOverrides, setSegmentOverrides] = useState<Record<string, ExpressionSettings>>({})
  const [saveHint, setSaveHint] = useState('')

  const [materialStrategy, setMaterialStrategy] = useState<MaterialStrategy>('ai_fill')
  const [useAvatar, setUseAvatar] = useState(false)
  const [avatarName, setAvatarName] = useState('默认数字人')
  const [subtitleStyle, setSubtitleStyle] = useState('重点词高亮')
  const [bgmStyle, setBgmStyle] = useState('低音量商务氛围')
  const [coverTitle, setCoverTitle] = useState('')
  const [ctaText, setCtaText] = useState('想了解适合你的马来西亚房产配置，可以私信我。')
  const [shotDrafts, setShotDrafts] = useState<ShotDraft[]>([])
  const [selectedShotId, setSelectedShotId] = useState('')
  const [shotsDirty, setShotsDirty] = useState(false)

  const [jobId, setJobId] = useState('')
  const [job, setJob] = useState<JobPayload | null>(null)
  const [isGenerating, setIsGenerating] = useState(false)
  const [error, setError] = useState('')

  const effectiveScript = useMemo(() => {
    return script.trim() || generateScript(topic, city, targetDuration, contentType)
  }, [script, topic, city, targetDuration, contentType])

  const scriptKey = useMemo(() => {
    return `AI_VIDEO_EXPRESSION_${hashString(effectiveScript)}`
  }, [effectiveScript])

  const keywordInsights = useMemo(() => {
    return detectKeywordInsights(effectiveScript, city, contentType)
  }, [effectiveScript, city, contentType])

  const scriptSegments = useMemo(() => {
    return buildScriptSegments(effectiveScript, targetDuration, keywordInsights, segmentOverrides, scriptKey)
  }, [effectiveScript, targetDuration, keywordInsights, segmentOverrides, scriptKey])

  const selectedSegment = useMemo(() => {
    return scriptSegments.find((item) => item.id === selectedSegmentId) || null
  }, [scriptSegments, selectedSegmentId])

  const selectedShot = useMemo(() => {
    return shotDrafts.find((item) => item.id === selectedShotId) || null
  }, [shotDrafts, selectedShotId])

  const videoUrl = extractVideoUrl(job)
  const audioDuration = Number(job?.audio_duration_seconds || 0)
  const currentProfile = CITY_PROFILES[city]
  const transitionPlan = useMemo(() => buildTransitionPlan(shotDrafts), [shotDrafts])

  useEffect(() => {
    saveLocalStorage('AI_VIDEO_API_BASE', apiBase)
  }, [apiBase])

  useEffect(() => {
    if (token.trim()) saveLocalStorage('AI_VIDEO_TOKEN', token.trim())
  }, [token])

  useEffect(() => {
    if (!selectedSegmentId && scriptSegments[0]) {
      setSelectedSegmentId(scriptSegments[0].id)
    }
  }, [scriptSegments, selectedSegmentId])

  useEffect(() => {
    if (shotsDirty) return
    const next = buildShotDrafts(effectiveScript, city, audioDuration || targetDuration, materialStrategy)
    setShotDrafts(next)
    setSelectedShotId((current) => current || next[0]?.id || '')
  }, [effectiveScript, city, targetDuration, materialStrategy, audioDuration, shotsDirty])

  useEffect(() => {
    if (!jobId || !isGenerating) return

    let alive = true

    async function poll() {
      try {
        const response = await fetch(`${normalizeApiBase(apiBase)}/api/video/full-ai/tts-first/job/${jobId}`, {
          headers: authHeaders(token),
        })
        const data = (await response.json()) as JobPayload
        if (!alive) return

        setJob(data)

        if (isFinalStatus(data) || isFailedStatus(data)) {
          setIsGenerating(false)
        }
      } catch (err) {
        if (!alive) return
        setError(err instanceof Error ? err.message : '轮询任务失败')
      }
    }

    poll()
    const timer = window.setInterval(poll, 3000)

    return () => {
      alive = false
      window.clearInterval(timer)
    }
  }, [apiBase, token, jobId, isGenerating])

  function goNext() {
    if (step === 1) {
      if (!script.trim()) {
        setScript(generateScript(topic, city, targetDuration, contentType))
      }
      setStep(2)
      return
    }

    if (step === 2) {
      setStep(3)
      return
    }

    if (step === 3) {
      setStep(4)
      return
    }

    startGenerate()
  }

  function goPrev() {
    setStep((current) => Math.max(1, current - 1) as WizardStep)
  }

  function regenerateScript() {
    setScript(generateScript(topic, city, targetDuration, contentType))
    setSegmentOverrides({})
    setSaveHint('')
    setShotsDirty(false)
  }

  function updateSelectedExpression(patch: Partial<ExpressionSettings>) {
    if (!selectedSegment) return
    const next = { ...selectedSegment.expression, ...patch }
    setSegmentOverrides((current) => ({ ...current, [selectedSegment.id]: next }))
  }

  function aiRecommendSelectedExpression() {
    if (!selectedSegment) return
    const next = analyzeExpression(selectedSegment.text, selectedSegment.index - 1, scriptSegments.length, keywordInsights)
    setSegmentOverrides((current) => ({ ...current, [selectedSegment.id]: next }))
  }

  function saveExpressionSettings() {
    const map: Record<string, ExpressionSettings> = {}
    scriptSegments.forEach((segment) => {
      map[segment.id] = segment.expression
    })
    saveLocalStorage(scriptKey, JSON.stringify(map))
    setSaveHint('已按当前文案保存每句表达参数')
    window.setTimeout(() => setSaveHint(''), 2200)
  }

  function updateShotDraft(shotId: string, patch: Partial<ShotDraft>) {
    setShotsDirty(true)
    setShotDrafts((current) => current.map((shot) => {
      if (shot.id !== shotId) return shot
      const next = { ...shot, ...patch }
      if (patch.scene || patch.narration || patch.camera || patch.transition) {
        next.prompt = makeShotPrompt(city, next.scene, next.narration, next.camera, next.transition)
      }
      return next
    }))
  }

  function resetShotPlan() {
    const next = buildShotDrafts(effectiveScript, city, audioDuration || targetDuration, materialStrategy)
    setShotDrafts(next)
    setSelectedShotId(next[0]?.id || '')
    setShotsDirty(false)
  }

  async function startGenerate() {
    setError('')
    setStep(4)
    setIsGenerating(true)
    setJob(null)
    setJobId('')

    const segmentPayload = scriptSegments.map((segment) => ({
      index: segment.index,
      text: segment.text,
      start_sec: segment.startSec,
      end_sec: segment.endSec,
      expression: segment.expression,
    }))

    const shotPayload = shotDrafts.map((shot) => ({
      index: shot.index,
      prompt: shot.prompt,
      visual_prompt: shot.prompt,
      scene: shot.scene,
      narration_segment: shot.narration,
      duration_seconds: shot.duration,
      camera: shot.camera,
      transition: shot.transition,
      source_type: shot.sourceType,
      keywords: shot.keywords,
      note: shot.note,
      image_url: null,
      shot_id: null,
    }))

    const payload = {
      title: topic,
      topic,
      script_text: effectiveScript,
      target_duration_seconds: targetDuration,
      duration_seconds: targetDuration,
      city,
      content_type: contentType,
      voice,
      width: 1080,
      height: 1920,
      fps: 30,
      // 兼容后端未来直接读取 shots；当前 tts-first 主要读取 extra。
      shots: shotPayload,
      extra: {
        source: 'video_creation_wizard_v2',
        source_mode: sourceMode,
        source_input: sourceInput,
        material_strategy: materialStrategy,
        use_avatar: useAvatar,
        avatar_name: useAvatar ? avatarName : '',
        voice_style: voiceStyle,
        speech_speed: speechSpeed,
        subtitle_style: subtitleStyle,
        bgm_style: bgmStyle,
        cover_title: coverTitle || topic,
        cta_text: ctaText,
        keyword_insights: keywordInsights,
        script_segments: segmentPayload,
        segment_voice_settings: segmentPayload,
        manual_shot_plan: shotPayload,
        shot_overrides: shotPayload,
        transition_plan: transitionPlan,
        keyword_strategy: {
          highlight_priority: 'price_region_people_usage',
          note: '价格/区域/人群/用途类关键词前端已标注，后端可用于 TTS 表达、字幕高亮、镜头匹配和转场衔接。',
        },
        ui_step_flow: 'content_script_expression_visual_render',
      },
    }

    try {
      const response = await fetch(`${normalizeApiBase(apiBase)}/api/video/full-ai/tts-first/start`, {
        method: 'POST',
        headers: authHeaders(token),
        body: JSON.stringify(payload),
      })

      const data = (await response.json()) as JobPayload

      if (!response.ok || data.ok === false) {
        throw new Error(data.error || `生成接口失败：HTTP ${response.status}`)
      }

      if (!data.job_id) {
        throw new Error('后端没有返回 job_id')
      }

      setJob(data)
      setJobId(data.job_id)
    } catch (err) {
      setIsGenerating(false)
      setError(err instanceof Error ? err.message : '生成失败')
    }
  }

  function renderStepOne() {
    return (
      <div className="vcw-card-stack">
        <div className="vcw-card">
          <div className="vcw-section-title">内容来源</div>
          <div className="vcw-source-tabs" role="tablist" aria-label="内容来源">
            <button
              type="button"
              className={`vcw-source-tab ${sourceMode === 'account' ? 'active' : ''}`}
              onClick={() => setSourceMode('account')}
            >
              抖音主页
            </button>
            <button
              type="button"
              className={`vcw-source-tab ${sourceMode === 'viral' ? 'active' : ''}`}
              onClick={() => setSourceMode('viral')}
            >
              爆款链接
            </button>
            <button
              type="button"
              className={`vcw-source-tab ${sourceMode === 'custom' ? 'active' : ''}`}
              onClick={() => setSourceMode('custom')}
            >
              自定义主题
            </button>
          </div>

          <label className="vcw-field">
            <span>视频主题</span>
            <input
              value={topic}
              onChange={(event) => setTopic(event.target.value)}
              placeholder="例如：马来西亚吉隆坡买房，别只看价格"
            />
          </label>

          <label className="vcw-field">
            <span>{getSourceLabel(sourceMode)}</span>
            {sourceMode === 'custom' ? (
              <textarea
                className="vcw-small-textarea"
                value={sourceInput}
                onChange={(event) => setSourceInput(event.target.value)}
                placeholder={getSourcePlaceholder(sourceMode)}
              />
            ) : (
              <input
                value={sourceInput}
                onChange={(event) => setSourceInput(event.target.value)}
                placeholder={getSourcePlaceholder(sourceMode)}
              />
            )}
          </label>

          <div className="vcw-grid-3">
            <label className="vcw-field">
              <span>预计视频长度</span>
              <select value={targetDuration} onChange={(event) => setTargetDuration(Number(event.target.value))}>
                <option value={15}>15 秒</option>
                <option value={20}>20 秒</option>
                <option value={30}>30 秒</option>
                <option value={45}>45 秒</option>
                <option value={60}>60 秒</option>
              </select>
            </label>

            <label className="vcw-field">
              <span>城市锁定</span>
              <select value={city} onChange={(event) => setCity(event.target.value as CityKey)}>
                {Object.entries(CITY_PROFILES).map(([key, item]) => (
                  <option key={key} value={key}>
                    {item.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="vcw-field">
              <span>内容方向</span>
              <select value={contentType} onChange={(event) => setContentType(event.target.value as ContentType)}>
                {Object.entries(CONTENT_LABELS).map(([key, label]) => (
                  <option key={key} value={key}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div className="vcw-action-row">
            <button type="button" className="vcw-primary" onClick={regenerateScript}>
              大脑生成文案
            </button>
            <button type="button" className="vcw-secondary" onClick={() => setScript('')}>
              清空重写
            </button>
          </div>
        </div>

        <div className="vcw-card">
          <div className="vcw-section-title">关键词与系统理解</div>
          <div className="vcw-chip-row">
            <span className="vcw-chip">目标 {targetDuration}s</span>
            <span className="vcw-chip">{currentProfile.shortLabel}</span>
            <span className="vcw-chip">{CONTENT_LABELS[contentType]}</span>
            <span className="vcw-chip">预计 {planShotCount(targetDuration)} 个镜头</span>
          </div>

          <div className="vcw-keyword-grid">
            {keywordInsights.map((item) => (
              <div key={`${item.keyword}-${item.type}`} className={`vcw-keyword-card ${item.priority}`}>
                <strong>{item.keyword}</strong>
                <span>{item.type}</span>
                <p>{item.reason}</p>
              </div>
            ))}
          </div>

          <div className="vcw-hint">
            吉隆坡默认只走城市房产画面：KLCC / TRX / Mont Kiara / 公寓阳台 / 大堂 / 泳池。关键词会同步传给后端，用于配音表达、字幕高亮、镜头规划和转场衔接。
          </div>
        </div>
      </div>
    )
  }

  function renderSegmentExpressionPanel() {
    if (!selectedSegment) {
      return (
        <div className="vcw-empty-state">
          <strong>点击左侧任意一句文案</strong>
          <span>点中后才会展示该句的语速、语调、语气、重点和停顿设置。</span>
        </div>
      )
    }

    return (
      <div className="vcw-expression-panel">
        <div className="vcw-selected-line-head">
          <span>{String(selectedSegment.index).padStart(2, '0')}</span>
          <strong>{selectedSegment.text}</strong>
        </div>

        <div className="vcw-expression-ai">
          <b>AI 判断</b>
          <p>{selectedSegment.expression.aiReason}</p>
          <div className="vcw-chip-row">
            {selectedSegment.expression.keywords.map((keyword) => (
              <span key={keyword} className="vcw-chip purple">{keyword}</span>
            ))}
          </div>
        </div>

        <div className="vcw-grid-2">
          <label className="vcw-field">
            <span>语气</span>
            <select
              value={selectedSegment.expression.emotion}
              onChange={(event) => updateSelectedExpression({ emotion: event.target.value })}
            >
              {EMOTION_OPTIONS.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>

          <label className="vcw-field">
            <span>语调</span>
            <select
              value={selectedSegment.expression.tone}
              onChange={(event) => updateSelectedExpression({ tone: event.target.value })}
            >
              {TONE_OPTIONS.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>
        </div>

        <label className="vcw-field vcw-range-field">
          <span>语速 {selectedSegment.expression.speed.toFixed(2)}</span>
          <input
            type="range"
            min="0.75"
            max="1.25"
            step="0.01"
            value={selectedSegment.expression.speed}
            onChange={(event) => updateSelectedExpression({ speed: Number(event.target.value) })}
          />
        </label>

        <label className="vcw-field vcw-range-field">
          <span>音高 / 语调强弱 {selectedSegment.expression.pitch.toFixed(2)}</span>
          <input
            type="range"
            min="0.85"
            max="1.18"
            step="0.01"
            value={selectedSegment.expression.pitch}
            onChange={(event) => updateSelectedExpression({ pitch: Number(event.target.value) })}
          />
        </label>

        <label className="vcw-field vcw-range-field">
          <span>音量 {selectedSegment.expression.volume.toFixed(2)}</span>
          <input
            type="range"
            min="0.8"
            max="1.25"
            step="0.01"
            value={selectedSegment.expression.volume}
            onChange={(event) => updateSelectedExpression({ volume: Number(event.target.value) })}
          />
        </label>

        <label className="vcw-field vcw-range-field">
          <span>句后停顿 {selectedSegment.expression.pauseAfter.toFixed(2)}s</span>
          <input
            type="range"
            min="0"
            max="0.8"
            step="0.05"
            value={selectedSegment.expression.pauseAfter}
            onChange={(event) => updateSelectedExpression({ pauseAfter: Number(event.target.value) })}
          />
        </label>

        <label className="vcw-field">
          <span>表达重点</span>
          <textarea
            className="vcw-small-textarea"
            value={selectedSegment.expression.emphasis}
            onChange={(event) => updateSelectedExpression({ emphasis: event.target.value })}
          />
        </label>

        <div className="vcw-action-row">
          <button type="button" className="vcw-secondary" onClick={aiRecommendSelectedExpression}>AI 重新判断该句</button>
          <button type="button" className="vcw-primary" onClick={saveExpressionSettings}>保存表达参数</button>
        </div>
        {saveHint && <div className="vcw-save-hint">{saveHint}</div>}
      </div>
    )
  }

  function renderStepTwo() {
    const { min, max } = targetChars(targetDuration)
    return (
      <div className="vcw-card-stack">
        <div className="vcw-two-column wide-left">
          <div className="vcw-card">
            <div className="vcw-section-title">口播文案</div>
            <div className="vcw-script-toolbar">
              <span>建议字数：{min}-{max}</span>
              <span>当前字数：{effectiveScript.length}</span>
            </div>
            <textarea
              className="vcw-script-box"
              value={script || effectiveScript}
              onChange={(event) => {
                setScript(event.target.value)
                setSegmentOverrides({})
                setShotsDirty(false)
              }}
            />

            <div className="vcw-section-subtitle">逐句表达，不点句子不展开设置</div>
            <div className="vcw-segment-list">
              {scriptSegments.map((segment) => (
                <button
                  type="button"
                  key={segment.id}
                  className={`vcw-segment-item ${selectedSegmentId === segment.id ? 'active' : ''}`}
                  onClick={() => setSelectedSegmentId(segment.id)}
                >
                  <em>{String(segment.index).padStart(2, '0')}</em>
                  <strong>{segment.text}</strong>
                  <span>{formatTimeRange(segment)} · {segment.expression.emotion} · {segment.expression.speed.toFixed(2)}x</span>
                </button>
              ))}
            </div>
          </div>

          <div className="vcw-card">
            <div className="vcw-section-title">单句配音设置</div>
            <div className="vcw-global-voice-box">
              <label className="vcw-field">
                <span>全局音色</span>
                <select value={voice} onChange={(event) => setVoice(event.target.value)}>
                  <option value="default">默认音色</option>
                  <option value="male_warm">男声 / 稳重</option>
                  <option value="female_clear">女声 / 清晰</option>
                  <option value="business">商务讲解</option>
                </select>
              </label>

              <label className="vcw-field">
                <span>全局情绪</span>
                <select value={voiceStyle} onChange={(event) => setVoiceStyle(event.target.value)}>
                  <option value="自然平稳">自然平稳</option>
                  <option value="专业可信">专业可信</option>
                  <option value="轻快种草">轻快种草</option>
                  <option value="成交引导">成交引导</option>
                </select>
              </label>

              <label className="vcw-field vcw-range-field">
                <span>整体语速 {speechSpeed.toFixed(1)}</span>
                <input
                  type="range"
                  min="0.8"
                  max="1.2"
                  step="0.1"
                  value={speechSpeed}
                  onChange={(event) => setSpeechSpeed(Number(event.target.value))}
                />
              </label>
            </div>

            {renderSegmentExpressionPanel()}
          </div>
        </div>
      </div>
    )
  }

  function renderStepThree() {
    return (
      <div className="vcw-card-stack">
        <div className="vcw-three-column">
          <div className="vcw-card">
            <div className="vcw-section-title">画面策略</div>
            <label className="vcw-field">
              <span>素材策略</span>
              <select
                value={materialStrategy}
                onChange={(event) => {
                  setMaterialStrategy(event.target.value as MaterialStrategy)
                  setShotsDirty(false)
                }}
              >
                {Object.entries(MATERIAL_LABELS).map(([key, label]) => (
                  <option key={key} value={key}>{label}</option>
                ))}
              </select>
            </label>

            <div className="vcw-anchor-box">
              <div className="vcw-anchor-title">城市锁定：{currentProfile.label}</div>
              <div className="vcw-chip-row">
                {currentProfile.anchors.map((anchor) => (
                  <span key={anchor} className="vcw-chip purple">{anchor}</span>
                ))}
              </div>
              <p>{getCityTopicHint(city)}</p>
            </div>

            <label className="vcw-switch">
              <input
                type="checkbox"
                checked={useAvatar}
                onChange={(event) => setUseAvatar(event.target.checked)}
              />
              <span>启用数字人讲解</span>
            </label>

            {useAvatar && (
              <label className="vcw-field">
                <span>数字人</span>
                <select value={avatarName} onChange={(event) => setAvatarName(event.target.value)}>
                  <option value="默认数字人">默认数字人</option>
                  <option value="地产顾问">地产顾问</option>
                  <option value="海外置业讲解员">海外置业讲解员</option>
                </select>
              </label>
            )}

            <div className="vcw-section-subtitle">更多定制</div>
            <label className="vcw-field">
              <span>字幕风格</span>
              <select value={subtitleStyle} onChange={(event) => setSubtitleStyle(event.target.value)}>
                <option value="重点词高亮">重点词高亮</option>
                <option value="干净白字">干净白字</option>
                <option value="房产商务风">房产商务风</option>
                <option value="短视频大字卡点">短视频大字卡点</option>
              </select>
            </label>

            <label className="vcw-field">
              <span>BGM</span>
              <select value={bgmStyle} onChange={(event) => setBgmStyle(event.target.value)}>
                <option value="低音量商务氛围">低音量商务氛围</option>
                <option value="轻快城市感">轻快城市感</option>
                <option value="高级楼盘质感">高级楼盘质感</option>
                <option value="无 BGM，只保留人声">无 BGM，只保留人声</option>
              </select>
            </label>
          </div>

          <div className="vcw-card">
            <div className="vcw-section-title">镜头规划，可手动改</div>
            <div className="vcw-shot-tools">
              <button type="button" className="vcw-secondary" onClick={resetShotPlan}>按文案重排镜头</button>
              <button
                type="button"
                className="vcw-secondary"
                onClick={() => {
                  setShotsDirty(true)
                  setShotDrafts((current) => {
                    const index = current.length + 1
                    const scene = `${currentProfile.shortLabel}补充镜头 ${index}`
                    const narration = '补充说明镜头'
                    const camera = '自然推进'
                    const transition = '自然过渡'
                    return [
                      ...current,
                      {
                        id: `${index}_${Date.now()}`,
                        index,
                        scene,
                        prompt: makeShotPrompt(city, scene, narration, camera, transition),
                        narration,
                        duration: 4,
                        camera,
                        transition,
                        sourceType: 'ai',
                        keywords: [],
                        note: '手动新增镜头',
                      },
                    ]
                  })
                }}
              >
                加一个镜头
              </button>
            </div>

            <div className="vcw-shot-list compact">
              {shotDrafts.map((shot) => (
                <button
                  key={shot.id}
                  type="button"
                  className={`vcw-shot-item editable ${selectedShotId === shot.id ? 'active' : ''}`}
                  onClick={() => setSelectedShotId(shot.id)}
                >
                  <div className="vcw-shot-index">{String(shot.index).padStart(2, '0')}</div>
                  <div>
                    <strong>{shot.scene}</strong>
                    <span>{shot.duration}s · {shot.camera} · {shot.transition}</span>
                  </div>
                </button>
              ))}
            </div>
          </div>

          <div className="vcw-card">
            <div className="vcw-section-title">镜头编辑</div>
            {selectedShot ? (
              <div className="vcw-shot-editor">
                <label className="vcw-field">
                  <span>镜头主体</span>
                  <input
                    value={selectedShot.scene}
                    onChange={(event) => updateShotDraft(selectedShot.id, { scene: event.target.value })}
                  />
                </label>

                <label className="vcw-field">
                  <span>对应口播</span>
                  <textarea
                    className="vcw-small-textarea"
                    value={selectedShot.narration}
                    onChange={(event) => updateShotDraft(selectedShot.id, { narration: event.target.value })}
                  />
                </label>

                <div className="vcw-grid-2">
                  <label className="vcw-field">
                    <span>镜头时长</span>
                    <input
                      type="number"
                      min="1"
                      max="12"
                      step="0.5"
                      value={selectedShot.duration}
                      onChange={(event) => updateShotDraft(selectedShot.id, { duration: clamp(Number(event.target.value), 1, 12) })}
                    />
                  </label>

                  <label className="vcw-field">
                    <span>素材来源</span>
                    <select
                      value={selectedShot.sourceType}
                      onChange={(event) => updateShotDraft(selectedShot.id, { sourceType: event.target.value as SourceType })}
                    >
                      <option value="mixed">真实优先 + AI 补</option>
                      <option value="real">只用真实素材</option>
                      <option value="ai">AI 生成</option>
                    </select>
                  </label>
                </div>

                <div className="vcw-grid-2">
                  <label className="vcw-field">
                    <span>运镜</span>
                    <select
                      value={selectedShot.camera}
                      onChange={(event) => updateShotDraft(selectedShot.id, { camera: event.target.value })}
                    >
                      {CAMERA_OPTIONS.map((item) => <option key={item} value={item}>{item}</option>)}
                    </select>
                  </label>

                  <label className="vcw-field">
                    <span>转场</span>
                    <select
                      value={selectedShot.transition}
                      onChange={(event) => updateShotDraft(selectedShot.id, { transition: event.target.value })}
                    >
                      {TRANSITION_OPTIONS.map((item) => <option key={item} value={item}>{item}</option>)}
                    </select>
                  </label>
                </div>

                <label className="vcw-field">
                  <span>高级 Prompt，可手动微调</span>
                  <textarea
                    className="vcw-prompt-box"
                    value={selectedShot.prompt}
                    onChange={(event) => updateShotDraft(selectedShot.id, { prompt: event.target.value })}
                  />
                </label>
              </div>
            ) : (
              <div className="vcw-empty-state">
                <strong>点击中间任意镜头</strong>
                <span>点中后可改镜头主体、时长、运镜、转场和 prompt。</span>
              </div>
            )}
          </div>
        </div>
      </div>
    )
  }

  function renderStepFour() {
    return (
      <div className="vcw-card-stack">
        <div className="vcw-two-column">
          <div className="vcw-card vcw-preview-card">
            <div className="vcw-section-title">成片预览</div>

            {videoUrl ? (
              <video className="vcw-video" src={videoUrl} controls playsInline />
            ) : (
              <div className="vcw-video-placeholder">
                <div className="vcw-video-icon">🎬</div>
                <strong>{isGenerating ? '正在生成成片' : '点击生成后在这里预览'}</strong>
                <span>系统会先生成配音，再按配音真实时长生成画面和合成。每句表达参数、关键词、镜头编辑和转场计划会同步传给后端。</span>
              </div>
            )}

            {error && <div className="vcw-error">{error}</div>}

            <div className="vcw-action-row">
              <button type="button" className="vcw-primary" disabled={isGenerating} onClick={startGenerate}>
                {isGenerating ? '生成中...' : '开始生成成片'}
              </button>
              {videoUrl && (
                <a className="vcw-secondary link" href={videoUrl} target="_blank" rel="noreferrer">
                  打开成片链接
                </a>
              )}
            </div>
          </div>

          <div className="vcw-card">
            <div className="vcw-section-title">生成状态</div>
            <div className="vcw-status-list">
              <div><span>任务</span><strong>{jobId || '-'}</strong></div>
              <div><span>阶段</span><strong>{job?.stage || job?.status || (isGenerating ? 'running' : 'ready')}</strong></div>
              <div><span>配音实际</span><strong>{audioDuration ? `${audioDuration.toFixed(1)}s` : '生成后读取'}</strong></div>
              <div><span>镜头数量</span><strong>{Number(job?.shot_count || shotDrafts.length)} 个</strong></div>
              <div><span>城市锁定</span><strong>{currentProfile.shortLabel}</strong></div>
              <div><span>表达参数</span><strong>{scriptSegments.length} 句</strong></div>
            </div>

            <div className="vcw-mini-progress">
              <span style={{ width: `${Math.min(100, Number(job?.progress || (isGenerating ? 65 : 0)))}%` }} />
            </div>

            <label className="vcw-field vcw-top-gap">
              <span>封面标题</span>
              <input value={coverTitle} onChange={(event) => setCoverTitle(event.target.value)} placeholder={topic} />
            </label>

            <label className="vcw-field">
              <span>结尾 CTA</span>
              <textarea className="vcw-small-textarea" value={ctaText} onChange={(event) => setCtaText(event.target.value)} />
            </label>

            {isFailedStatus(job) && (
              <div className="vcw-error">{job?.error || job?.child_job?.error || '生成失败，请检查后端日志'}</div>
            )}
          </div>
        </div>
      </div>
    )
  }

  function renderMainStep() {
    if (step === 1) return renderStepOne()
    if (step === 2) return renderStepTwo()
    if (step === 3) return renderStepThree()
    return renderStepFour()
  }

  function renderRightPanel() {
    return (
      <aside className="vcw-side-panel">
        <div className="vcw-result-title">生成结果预览</div>

        {step === 1 && (
          <>
            <div className="vcw-result-block">
              <span>提取主题</span>
              <strong>{topic || '等待输入主题'}</strong>
            </div>
            <div className="vcw-result-block">
              <span>推荐文案</span>
              <p>{effectiveScript}</p>
            </div>
            <div className="vcw-result-block">
              <span>关键词凸显</span>
              <div className="vcw-mini-keywords">
                {keywordInsights.slice(0, 8).map((item) => <b key={item.keyword}>{item.keyword}</b>)}
              </div>
            </div>
          </>
        )}

        {step === 2 && (
          <>
            <div className="vcw-result-block">
              <span>口播分段</span>
              <div className="vcw-line-list">
                {scriptSegments.map((segment) => (
                  <button
                    type="button"
                    key={segment.id}
                    className={selectedSegmentId === segment.id ? 'active' : ''}
                    onClick={() => setSelectedSegmentId(segment.id)}
                  >
                    <em>{String(segment.index).padStart(2, '0')}</em>
                    <strong>{segment.text}</strong>
                  </button>
                ))}
              </div>
            </div>
            {selectedSegment && (
              <div className="vcw-result-block">
                <span>当前句表达</span>
                <p>{selectedSegment.expression.emotion} / {selectedSegment.expression.tone} / {selectedSegment.expression.speed.toFixed(2)}x</p>
              </div>
            )}
          </>
        )}

        {step === 3 && (
          <>
            <div className="vcw-result-block">
              <span>镜头结果</span>
              <div className="vcw-line-list">
                {shotDrafts.map((shot) => (
                  <button
                    type="button"
                    key={shot.id}
                    className={selectedShotId === shot.id ? 'active' : ''}
                    onClick={() => setSelectedShotId(shot.id)}
                  >
                    <em>{String(shot.index).padStart(2, '0')}</em>
                    <strong>{shot.scene}</strong>
                  </button>
                ))}
              </div>
            </div>
            <div className="vcw-result-block">
              <span>转场衔接</span>
              <p>{transitionPlan.slice(0, 3).map((item) => `${item.index}. ${item.transition}`).join(' / ')}</p>
            </div>
          </>
        )}

        {step === 4 && (
          <>
            <div className="vcw-result-block">
              <span>成片信息</span>
              <div className="vcw-summary-grid">
                <strong>{audioDuration ? `${audioDuration.toFixed(1)}s` : `${targetDuration}s`}</strong>
                <small>视频时长</small>
                <strong>{Number(job?.shot_count || shotDrafts.length)}</strong>
                <small>镜头数量</small>
                <strong>{scriptSegments.length}</strong>
                <small>表达句数</small>
                <strong>1080×1920</strong>
                <small>竖屏规格</small>
              </div>
            </div>
            <div className="vcw-result-block">
              <span>发布准备</span>
              <p>成片后可导出视频、复制发布文案，并接入评论获客承接。</p>
            </div>
          </>
        )}
      </aside>
    )
  }

  return (
    <div className="vcw-shell">
      <aside className="vcw-rail">
        <div className="vcw-logo">AI-VIDEO</div>
        <div className="vcw-logo-sub">智能增长工作台</div>

        <nav className="vcw-nav">
          <button type="button" className="active">视频创作</button>
          <button type="button">账号素材</button>
          <button type="button">数字人库</button>
          <button type="button">获客线索</button>
          <button type="button">设置</button>
        </nav>

        <div className="vcw-rail-card">
          <strong>创作模式</strong>
          <span>TTS-first</span>
          <small>先配音，再按真实时长生成画面。逐句表达和镜头设置会随 payload 传给后端。</small>
        </div>
      </aside>

      <main className="vcw-main">
        <header className="vcw-header">
          <div>
            <div className="vcw-eyebrow">第 {step} 步 / 共 4 步</div>
            <h1>{`第${step}步：${STEP_TITLES[step]}`}</h1>
            <p>{STEP_SUBTITLES[step]}</p>
          </div>

          <div className="vcw-api-box">
            <label>
              <span>后端地址</span>
              <input value={apiBase} onChange={(event) => setApiBase(event.target.value)} />
            </label>
            <label>
              <span>Token</span>
              <input
                value={token}
                onChange={(event) => setToken(event.target.value)}
                placeholder="可粘贴后台 Token"
                type="password"
              />
            </label>
          </div>
        </header>

        <div className="vcw-content">
          <section className="vcw-workspace">{renderMainStep()}</section>
          {renderRightPanel()}
        </div>
      </main>

      <footer className="vcw-footer">
        <div className="vcw-footer-progress">
          <span>创作进度</span>
          <strong>{step}/4</strong>
          <div className="vcw-progress-track"><i style={{ width: `${(step / 4) * 100}%` }} /></div>
        </div>

        <div className="vcw-footer-actions">
          <button type="button" className="vcw-secondary big" disabled={step === 1 || isGenerating} onClick={goPrev}>上一步</button>
          <button type="button" className="vcw-primary big" disabled={isGenerating && step === 4} onClick={goNext}>
            {step === 4 ? (isGenerating ? '生成中...' : '生成成片') : '下一步'}
          </button>
        </div>
      </footer>
    </div>
  )
}
