import React, { useEffect, useMemo, useState } from 'react'

type ModuleKey = 'video' | 'assets' | 'avatars' | 'leads' | 'settings'
type WizardStep = 1 | 2 | 3 | 4
type SourceMode = 'douyin_home' | 'hot_link' | 'custom_topic'
type CityKey = 'kuala_lumpur' | 'penang' | 'johor' | 'langkawi' | 'sabah'
type ContentType = 'investment' | 'own_stay' | 'second_home' | 'rental' | 'education'
type MaterialStrategy = 'real_first' | 'ai_fill' | 'full_ai'
type MaterialSource = 'real' | 'ai' | 'mixed'
type CameraMove = 'push_in' | 'pan' | 'tilt' | 'static' | 'orbit'
type TransitionMode = 'natural' | 'match_cut' | 'keyword_cut' | 'city_to_interior' | 'soft_fade'

type KeywordInsight = {
  category: string
  label: string
  value: string
  reason: string
  priority: number
}

type SegmentVoiceSetting = {
  speed: number
  pitch: number
  volume: number
  emotion: string
  tone: string
  pauseBefore: number
  pauseAfter: number
  emphasis: string[]
  note: string
}

type ScriptSegment = {
  id: string
  index: number
  text: string
  keywords: KeywordInsight[]
}

type ShotPlan = {
  id: string
  index: number
  title: string
  scene: string
  narration: string
  duration: number
  materialSource: MaterialSource
  cameraMove: CameraMove
  transition: TransitionMode
  prompt: string
  negativeRules: string[]
}

type AssetItem = {
  id: string
  name: string
  type: 'account' | 'link' | 'material'
  url: string
  city: CityKey
  tags: string[]
  status: 'ready' | 'learning' | 'draft'
}

type AvatarItem = {
  id: string
  name: string
  role: string
  style: string
  enabled: boolean
}

type LeadItem = {
  id: string
  source: string
  text: string
  intent: string
  score: number
  reply: string
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
  child_job?: Record<string, any>
  result?: Record<string, any>
  [key: string]: any
}

const STORAGE_KEY = 'AI_VIDEO_CONSOLE_V3_STATE'

const MODULE_LABELS: Record<ModuleKey, string> = {
  video: '视频创作',
  assets: '账号素材',
  avatars: '数字人库',
  leads: '获客线索',
  settings: '设置',
}

const STEP_TITLES: Record<WizardStep, string> = {
  1: '搞定视频内容',
  2: '生成口播配音',
  3: '选择画面风格',
  4: '生成成片预览',
}

const SOURCE_LABELS: Record<SourceMode, string> = {
  douyin_home: '抖音主页',
  hot_link: '爆款链接',
  custom_topic: '自定义主题',
}

const CITY_PROFILES: Record<CityKey, { label: string; shortLabel: string; anchors: string[]; scenes: string[]; banned: string[] }> = {
  kuala_lumpur: {
    label: '吉隆坡 / Kuala Lumpur',
    shortLabel: '吉隆坡',
    anchors: ['KLCC', 'TRX', 'Mont Kiara', '公寓阳台', '大堂', '泳池', '城市夜景'],
    scenes: [
      'KLCC 双子塔天际线 + 高层公寓建立镜头',
      'TRX 金融区 + 高端住宅区位镜头',
      'Mont Kiara 高端公寓社区生活氛围',
      '公寓阳台看吉隆坡城市天际线',
      '现代公寓客厅 + 落地窗城市景观',
      '高端公寓大堂 / 泳池 / 健身房设施',
      '吉隆坡夜景 + 高层住宅灯光氛围',
    ],
    banned: ['海边', '沙滩', '海景度假', '兰卡威', '沙巴海景', '槟城海景', '文件桌面', '计算器', '乱码文字'],
  },
  penang: {
    label: '槟城 / Penang',
    shortLabel: '槟城',
    anchors: ['Gurney Drive', '海景公寓', '养老生活', '滨海天际线', '阳台'],
    scenes: ['槟城滨海住宅天际线', '海景公寓阳台生活方式', '现代公寓室内 + 海景窗景', '养老和第二家园生活氛围'],
    banned: ['吉隆坡冒充', '假项目名', '精确 ROI', '乱码文字', '文件桌面'],
  },
  johor: {
    label: '新山 / Johor Bahru',
    shortLabel: '新山',
    anchors: ['新山城市', 'Medini', '公寓社区', '通勤生活', '家庭自住'],
    scenes: ['新山城市住宅区位镜头', 'Medini 现代公寓社区', '家庭自住公寓室内空间', '城市通勤和生活配套氛围'],
    banned: ['海岛度假感', '假学校名', '假价格牌', '乱码文字', '文件桌面'],
  },
  langkawi: {
    label: '兰卡威 / Langkawi',
    shortLabel: '兰卡威',
    anchors: ['度假住宅', '岛屿生活', '泳池', '第二家园', '热带景观'],
    scenes: ['兰卡威度假型住宅和泳池', '热带绿植中的第二家园生活', '岛屿度假住宅生活方式', '度假社区公共空间'],
    banned: ['吉隆坡城市金融区', '假项目名', '精确 ROI', '乱码文字', '文件桌面'],
  },
  sabah: {
    label: '沙巴 / Sabah',
    shortLabel: '沙巴',
    anchors: ['亚庇', '滨海住宅', '日落景观', '第二家园', '度假生活'],
    scenes: ['亚庇城市滨海住宅氛围', '沙巴日落景观和住宅生活方式', '滨海公寓阳台生活场景', '度假型社区配套镜头'],
    banned: ['KLCC 冒充', '假项目名', '精确 ROI', '乱码文字', '文件桌面'],
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

const CAMERA_LABELS: Record<CameraMove, string> = {
  push_in: '缓慢推进',
  pan: '横向平移',
  tilt: '上下摇镜',
  static: '稳定定镜',
  orbit: '轻微环绕',
}

const TRANSITION_LABELS: Record<TransitionMode, string> = {
  natural: '自然过渡',
  match_cut: '动作衔接',
  keyword_cut: '关键词卡点',
  city_to_interior: '城市切室内',
  soft_fade: '柔和淡入淡出',
}

function safeRead(key: string): string {
  try {
    return window.localStorage.getItem(key) || ''
  } catch {
    return ''
  }
}

function safeWrite(key: string, value: string) {
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

function defaultApiBase(): string {
  const local = safeRead('AI_VIDEO_API_BASE') || safeRead('ai_video_api_base')
  if (local) return normalizeApiBase(local)
  const envValue = (import.meta as any).env?.VITE_AI_VIDEO_API_BASE
  return normalizeApiBase(envValue || 'https://ai-video.47-76-143-158.sslip.io')
}

function defaultToken(): string {
  return safeRead('AI_VIDEO_TOKEN') || safeRead('ai_video_token') || safeRead('AI_VIDEO_ADMIN_TOKEN') || ''
}

function stableId(text: string): string {
  let hash = 2166136261
  for (let i = 0; i < text.length; i += 1) {
    hash ^= text.charCodeAt(i)
    hash += (hash << 1) + (hash << 4) + (hash << 7) + (hash << 8) + (hash << 24)
  }
  return Math.abs(hash >>> 0).toString(36)
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value))
}

function targetChars(duration: number): { min: number; max: number } {
  return { min: Math.max(40, Math.floor(duration * 4.3)), max: Math.max(60, Math.floor(duration * 5.3)) }
}

function splitSentences(script: string): string[] {
  return script
    .split(/[。！？!?；;\n]+/)
    .map((item) => item.trim())
    .filter(Boolean)
}

function generateScript(topic: string, city: CityKey, duration: number, contentType: ContentType, manualKeywords: string[]): string {
  const profile = CITY_PROFILES[city]
  const title = topic.trim() || `${profile.shortLabel}买房，别只看价格`
  const { min, max } = targetChars(duration)
  const keywords = manualKeywords.length ? `重点看${manualKeywords.join('、')}。` : ''
  let script = ''

  if (city === 'kuala_lumpur') {
    script = `${title}。很多人买马来西亚房产，第一眼只看价格，但在吉隆坡，真正要先看区域、用途和流动性。KLCC、TRX、Mont Kiara 这些位置，看的不是热闹，而是生活半径、出租需求和未来转手。${keywords}`
    if (contentType === 'investment') script += '如果是投资配置，先看租客是谁、通勤是否方便、周边配套是否成熟，再看价格是否合理。'
    if (contentType === 'own_stay') script += '如果是自住，重点不是短期涨跌，而是生活便利、社区品质和长期居住舒适度。'
    if (contentType === 'education') script += '如果考虑家庭和教育，要把通勤、社区、安全感和长期居住需求放在前面。'
    if (contentType === 'rental') script += '如果看出租，重点是目标租客、通勤半径、交付品质和后续管理。'
    if (contentType === 'second_home') script += '如果是第二家园，要把生活方式、医疗、交通和长期持有体验放在前面。'
  } else {
    script = `${title}。马来西亚买房不要只看价格，要先看城市、用途和生活方式。${profile.shortLabel}更适合${CONTENT_LABELS[contentType]}方向的人群，重点要看区域成熟度、生活配套、未来使用场景和转手流动性。${keywords}先把预算、用途和持有周期想清楚，再去筛项目。`
  }

  while (script.length < min) {
    script += city === 'kuala_lumpur'
      ? ' 吉隆坡项目重点看区位价值、生活便利度、出租需求、社区品质和未来转手逻辑。'
      : ` ${profile.shortLabel}项目重点看生活方式、配套成熟度、长期使用场景和资产流动性。`
  }

  if (script.length > max) script = script.slice(0, max).replace(/[，,、\s]+$/g, '') + '。'
  return script
}

function extractKeywords(text: string, city: CityKey, manualKeywords: string[]): KeywordInsight[] {
  const raw = `${text} ${manualKeywords.join(' ')}`
  const list: KeywordInsight[] = []
  const push = (category: string, label: string, value: string, reason: string, priority = 2) => {
    if (!value) return
    const key = `${category}:${value}`.toLowerCase()
    if (list.some((item) => `${item.category}:${item.value}`.toLowerCase() === key)) return
    list.push({ category, label, value, reason, priority })
  }

  const moneyMatches = raw.match(/(?:\d+(?:\.\d+)?\s*(?:万|百万|亿|马币|人民币|RM|rm))|(?:RM\s*\d+(?:\.\d+)?)/g) || []
  moneyMatches.forEach((value) => push('预算', '价格/预算', value, '涉及价格或预算，口播需要放慢并强调'))

  ;['KLCC', 'TRX', 'Mont Kiara', '吉隆坡', 'Kuala Lumpur', '槟城', 'Penang', '新山', 'Johor', '兰卡威', 'Langkawi', '沙巴', 'Sabah'].forEach((word) => {
    if (raw.toLowerCase().includes(word.toLowerCase())) push('区域', '城市/区域', word, '区域是房产内容核心判断点', 3)
  })

  ;['华人', '华语', '中文', '英语', '马来语', '家庭', '养老', '留学', '新加坡', '租客'].forEach((word) => {
    if (raw.includes(word)) push('人群', '目标人群', word, '影响语气、语言表达和画面选择', 3)
  })

  ;['出租', '流动性', '转手', '自住', '投资', '第二家园', '教育', '通勤', '配套', '大平层', '精装', '低总价', '租金'].forEach((word) => {
    if (raw.includes(word)) push('卖点', '卖点/判断标准', word, '需要在文案和镜头中凸显', 2)
  })

  ;['别只看', '避坑', '风险', '误区', '不要', '谨慎', '亏', '假'].forEach((word) => {
    if (raw.includes(word)) push('风控', '风险提醒', word, '适合用专业可信语气，避免夸大承诺', 2)
  })

  manualKeywords.forEach((word) => push('自定义', '手动关键词', word, '用户指定要凸显', 3))
  CITY_PROFILES[city].anchors.forEach((word) => push('画面锚点', '视觉关键词', word, '用于镜头规划和画面锁定', 1))

  return list.sort((a, b) => b.priority - a.priority)
}

function segmentId(text: string, index: number): string {
  return `seg_${index}_${stableId(text)}`
}

function buildSegments(script: string, insights: KeywordInsight[]): ScriptSegment[] {
  return splitSentences(script).map((text, index) => ({
    id: segmentId(text, index),
    index: index + 1,
    text,
    keywords: insights.filter((item) => text.toLowerCase().includes(item.value.toLowerCase())).slice(0, 6),
  }))
}

function defaultVoiceSetting(segment: ScriptSegment): SegmentVoiceSetting {
  const hasBudget = segment.keywords.some((item) => item.category === '预算')
  const hasRisk = segment.keywords.some((item) => item.category === '风控')
  const hasCrowd = segment.keywords.some((item) => item.category === '人群')
  return {
    speed: hasBudget || hasRisk ? 0.92 : 1,
    pitch: 1,
    volume: 1,
    emotion: hasRisk ? '专业提醒' : hasCrowd ? '亲和可信' : '自然平稳',
    tone: hasBudget ? '重点强调' : hasRisk ? '谨慎专业' : '专业可信',
    pauseBefore: hasBudget ? 0.2 : 0,
    pauseAfter: hasBudget || hasRisk ? 0.35 : 0.15,
    emphasis: segment.keywords.map((item) => item.value).slice(0, 3),
    note: hasBudget ? '价格预算处放慢，突出但不要夸大' : '',
  }
}

function planShotCount(duration: number): number {
  const base = Math.ceil(Math.max(1, duration) / 4.5)
  return duration >= 16 ? Math.max(4, base) : Math.max(1, base)
}

function buildShotPlan(script: string, city: CityKey, duration: number, materialStrategy: MaterialStrategy): ShotPlan[] {
  const count = planShotCount(duration)
  const scenes = CITY_PROFILES[city].scenes
  const segments = splitSentences(script)
  const eachDuration = Math.round((duration / count) * 10) / 10
  const source: MaterialSource = materialStrategy === 'real_first' ? 'mixed' : materialStrategy === 'full_ai' ? 'ai' : 'mixed'

  return Array.from({ length: count }, (_, index) => {
    const narration = segments[index % Math.max(1, segments.length)] || script
    const scene = scenes[index % scenes.length]
    return {
      id: `shot_${index + 1}_${stableId(scene + narration)}`,
      index: index + 1,
      title: scene,
      scene,
      narration,
      duration: eachDuration,
      materialSource: source,
      cameraMove: index % 3 === 0 ? 'push_in' : index % 3 === 1 ? 'pan' : 'static',
      transition: index === 0 ? 'natural' : index % 2 === 0 ? 'city_to_interior' : 'keyword_cut',
      prompt: `Premium 9:16 Malaysia real-estate video. Main scene: ${scene}. Narration meaning: ${narration}. Ultra realistic, clean premium commercial, natural light, no fake project name, no price board, no readable text.`,
      negativeRules: CITY_PROFILES[city].banned,
    }
  })
}

function updateShotIndexes(shots: ShotPlan[]): ShotPlan[] {
  return shots.map((shot, idx) => ({ ...shot, index: idx + 1 }))
}

function authHeaders(token: string): HeadersInit {
  const clean = token.trim()
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (clean) {
    headers['X-AI-Video-Token'] = clean
    headers.Authorization = `Bearer ${clean}`
  }
  return headers
}

function extractVideoUrl(job: JobPayload | null): string {
  if (!job) return ''
  const urls = [
    job.video_url,
    job.output_url,
    job.result_url,
    job.url,
    job.result?.video_url,
    job.result?.output_url,
    job.result?.result_url,
    job.child_job?.video_url,
    job.child_job?.output_url,
    job.child_job?.result_url,
    job.child_job?.url,
    job.child_job?.result?.video_url,
    job.child_job?.result?.output_url,
    job.child_job?.result?.result_url,
  ]
  return String(urls.find((item) => typeof item === 'string' && item) || '')
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

function maskToken(token: string): string {
  const clean = token.trim()
  if (!clean) return '未设置'
  if (clean.length < 10) return '已设置'
  return `${clean.slice(0, 4)}****${clean.slice(-4)}`
}

function restoreState() {
  try {
    const raw = safeRead(STORAGE_KEY)
    return raw ? JSON.parse(raw) : {}
  } catch {
    return {}
  }
}

function renderHighlightedText(text: string, insights: KeywordInsight[]) {
  const keys = insights.map((item) => item.value).filter((item) => item.length >= 2).slice(0, 18)
  if (!keys.length) return text
  const pattern = new RegExp(`(${keys.map((key) => key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`, 'gi')
  return text.split(pattern).map((part, index) => {
    const hit = keys.some((key) => key.toLowerCase() === part.toLowerCase())
    return hit ? <mark key={`${part}-${index}`}>{part}</mark> : <React.Fragment key={`${part}-${index}`}>{part}</React.Fragment>
  })
}

export default function VideoCreationWizard() {
  const restored = useMemo(() => restoreState(), [])
  const [activeModule, setActiveModule] = useState<ModuleKey>(restored.activeModule || 'video')
  const [step, setStep] = useState<WizardStep>(restored.step || 1)
  const [sourceMode, setSourceMode] = useState<SourceMode>(restored.sourceMode || 'douyin_home')
  const [apiBase, setApiBase] = useState(defaultApiBase)
  const [token, setToken] = useState(defaultToken)

  const [topic, setTopic] = useState(restored.topic || '马来西亚吉隆坡买房，别只看价格')
  const [sourceUrl, setSourceUrl] = useState(restored.sourceUrl || '')
  const [targetDuration, setTargetDuration] = useState<number>(restored.targetDuration || 20)
  const [city, setCity] = useState<CityKey>(restored.city || 'kuala_lumpur')
  const [contentType, setContentType] = useState<ContentType>(restored.contentType || 'investment')
  const [manualKeywordInput, setManualKeywordInput] = useState('')
  const [manualKeywords, setManualKeywords] = useState<string[]>(restored.manualKeywords || ['流动性', '出租需求'])

  const [script, setScript] = useState(restored.script || '')
  const [activeSegmentId, setActiveSegmentId] = useState<string>('')
  const [segmentSettings, setSegmentSettings] = useState<Record<string, SegmentVoiceSetting>>(restored.segmentSettings || {})

  const [materialStrategy, setMaterialStrategy] = useState<MaterialStrategy>(restored.materialStrategy || 'ai_fill')
  const [useAvatar, setUseAvatar] = useState(Boolean(restored.useAvatar))
  const [avatarName, setAvatarName] = useState(restored.avatarName || '地产顾问')
  const [shots, setShots] = useState<ShotPlan[]>(restored.shots || [])
  const [activeShotId, setActiveShotId] = useState<string>('')

  const [assets, setAssets] = useState<AssetItem[]>(restored.assets || [
    { id: 'asset_kl_1', name: '吉隆坡房产同行主页', type: 'account', url: '', city: 'kuala_lumpur', tags: ['KLCC', '投资', '华语'], status: 'draft' },
    { id: 'asset_link_1', name: '爆款视频链接样例', type: 'link', url: '', city: 'kuala_lumpur', tags: ['避坑', '预算'], status: 'draft' },
  ])
  const [avatars, setAvatars] = useState<AvatarItem[]>(restored.avatars || [
    { id: 'avatar_consultant', name: '地产顾问', role: '海外置业讲解', style: '专业可信', enabled: true },
    { id: 'avatar_growth', name: '增长顾问', role: '获客转化', style: '干练直接', enabled: false },
  ])
  const [leads, setLeads] = useState<LeadItem[]>(restored.leads || [])
  const [leadDraft, setLeadDraft] = useState('吉隆坡 150 万预算能买哪里？华人多吗，可以讲华语吗？')

  const [jobId, setJobId] = useState('')
  const [job, setJob] = useState<JobPayload | null>(null)
  const [isGenerating, setIsGenerating] = useState(false)
  const [error, setError] = useState('')

  const effectiveScript = useMemo(() => script.trim() || generateScript(topic, city, targetDuration, contentType, manualKeywords), [script, topic, city, targetDuration, contentType, manualKeywords])
  const insights = useMemo(() => extractKeywords(`${topic}。${effectiveScript}`, city, manualKeywords), [topic, effectiveScript, city, manualKeywords])
  const segments = useMemo(() => buildSegments(effectiveScript, insights), [effectiveScript, insights])
  const selectedSegment = segments.find((item) => item.id === activeSegmentId) || null
  const currentProfile = CITY_PROFILES[city]
  const displayedShots = shots.length ? shots : buildShotPlan(effectiveScript, city, Number(job?.audio_duration_seconds || targetDuration), materialStrategy)
  const selectedShot = displayedShots.find((item) => item.id === activeShotId) || displayedShots[0] || null
  const videoUrl = extractVideoUrl(job)
  const audioDuration = Number(job?.audio_duration_seconds || 0)

  useEffect(() => {
    const state = { activeModule, step, sourceMode, topic, sourceUrl, targetDuration, city, contentType, manualKeywords, script, segmentSettings, materialStrategy, useAvatar, avatarName, shots, assets, avatars, leads }
    safeWrite(STORAGE_KEY, JSON.stringify(state))
  }, [activeModule, step, sourceMode, topic, sourceUrl, targetDuration, city, contentType, manualKeywords, script, segmentSettings, materialStrategy, useAvatar, avatarName, shots, assets, avatars, leads])

  useEffect(() => { safeWrite('AI_VIDEO_API_BASE', apiBase) }, [apiBase])
  useEffect(() => { if (token.trim()) safeWrite('AI_VIDEO_TOKEN', token.trim()) }, [token])

  useEffect(() => {
    if (!jobId || !isGenerating) return
    let alive = true
    async function poll() {
      try {
        const response = await fetch(`${normalizeApiBase(apiBase)}/api/video/full-ai/tts-first/job/${jobId}`, { headers: authHeaders(token) })
        const data = (await response.json()) as JobPayload
        if (!alive) return
        setJob(data)
        if (isFinalStatus(data) || isFailedStatus(data)) setIsGenerating(false)
      } catch (err) {
        if (!alive) return
        setError(err instanceof Error ? err.message : '轮询任务失败')
      }
    }
    poll()
    const timer = window.setInterval(poll, 3000)
    return () => { alive = false; window.clearInterval(timer) }
  }, [apiBase, token, jobId, isGenerating])

  function addManualKeyword() {
    const value = manualKeywordInput.trim()
    if (!value) return
    setManualKeywords((items) => Array.from(new Set([...items, value])))
    setManualKeywordInput('')
  }

  function applyGeneratedScript() {
    const nextScript = generateScript(topic, city, targetDuration, contentType, manualKeywords)
    setScript(nextScript)
    const nextInsights = extractKeywords(`${topic}。${nextScript}`, city, manualKeywords)
    const nextSegments = buildSegments(nextScript, nextInsights)
    const nextSettings: Record<string, SegmentVoiceSetting> = { ...segmentSettings }
    nextSegments.forEach((segment) => { nextSettings[segment.id] = nextSettings[segment.id] || defaultVoiceSetting(segment) })
    setSegmentSettings(nextSettings)
    setShots(buildShotPlan(nextScript, city, targetDuration, materialStrategy))
  }

  function ensureSegmentSettings() {
    const nextSettings: Record<string, SegmentVoiceSetting> = { ...segmentSettings }
    segments.forEach((segment) => { nextSettings[segment.id] = nextSettings[segment.id] || defaultVoiceSetting(segment) })
    setSegmentSettings(nextSettings)
  }

  function updateSelectedSegment(patch: Partial<SegmentVoiceSetting>) {
    if (!selectedSegment) return
    const current = segmentSettings[selectedSegment.id] || defaultVoiceSetting(selectedSegment)
    setSegmentSettings({ ...segmentSettings, [selectedSegment.id]: { ...current, ...patch } })
  }

  function regenerateShots() {
    const nextShots = buildShotPlan(effectiveScript, city, Number(job?.audio_duration_seconds || targetDuration), materialStrategy)
    setShots(nextShots)
    setActiveShotId(nextShots[0]?.id || '')
  }

  function updateShot(id: string, patch: Partial<ShotPlan>) {
    setShots((items) => updateShotIndexes((items.length ? items : displayedShots).map((shot) => shot.id === id ? { ...shot, ...patch } : shot)))
  }

  function addShot() {
    const base = selectedShot || displayedShots[displayedShots.length - 1]
    const next: ShotPlan = {
      ...(base || buildShotPlan(effectiveScript, city, targetDuration, materialStrategy)[0]),
      id: `shot_new_${Date.now()}`,
      title: '新增镜头：请填写画面主体',
      scene: '自定义画面主体',
      narration: '',
      duration: 4,
    }
    setShots((items) => updateShotIndexes([...(items.length ? items : displayedShots), next]))
    setActiveShotId(next.id)
  }

  function duplicateShot(id: string) {
    const list = shots.length ? shots : displayedShots
    const index = list.findIndex((shot) => shot.id === id)
    if (index < 0) return
    const copy = { ...list[index], id: `shot_copy_${Date.now()}`, title: `${list[index].title} 副本` }
    setShots(updateShotIndexes([...list.slice(0, index + 1), copy, ...list.slice(index + 1)]))
    setActiveShotId(copy.id)
  }

  function deleteShot(id: string) {
    const list = (shots.length ? shots : displayedShots).filter((shot) => shot.id !== id)
    setShots(updateShotIndexes(list))
    setActiveShotId(list[0]?.id || '')
  }

  function goNext() {
    if (activeModule !== 'video') { setActiveModule('video'); return }
    if (step === 1) {
      applyGeneratedScript()
      setStep(2)
      return
    }
    if (step === 2) {
      ensureSegmentSettings()
      if (!activeSegmentId && segments[0]) setActiveSegmentId(segments[0].id)
      setStep(3)
      return
    }
    if (step === 3) {
      if (!shots.length) regenerateShots()
      setStep(4)
      return
    }
    startGenerate()
  }

  function goPrev() { setStep((current) => clamp(current - 1, 1, 4) as WizardStep) }

  async function startGenerate() {
    setError('')
    setIsGenerating(true)
    setJob(null)
    setJobId('')
    const finalShots = shots.length ? shots : displayedShots
    const finalSettings: Record<string, SegmentVoiceSetting> = { ...segmentSettings }
    segments.forEach((segment) => { finalSettings[segment.id] = finalSettings[segment.id] || defaultVoiceSetting(segment) })

    const payload = {
      title: topic,
      topic,
      script_text: effectiveScript,
      target_duration_seconds: targetDuration,
      duration_seconds: targetDuration,
      city,
      content_type: contentType,
      voice: 'default',
      width: 1080,
      height: 1920,
      fps: 30,
      script_segments: segments.map((segment) => ({ ...segment, voice_setting: finalSettings[segment.id] })),
      segment_voice_settings: finalSettings,
      keyword_insights: insights,
      manual_shot_plan: finalShots,
      shot_overrides: finalShots,
      transition_plan: finalShots.map((shot, index) => ({ from: index, to: index + 1, transition: shot.transition, label: TRANSITION_LABELS[shot.transition] })).slice(1),
      asset_context: { source_mode: sourceMode, source_url: sourceUrl, material_strategy: materialStrategy, assets: assets.filter((asset) => asset.status !== 'draft') },
      avatar_config: { enabled: useAvatar, avatar_name: useAvatar ? avatarName : '', avatars },
      extra: {
        source: 'ai_video_console_v3',
        purpose: 'real_estate_lead_generation',
        linked_modules: ['content', 'tts', 'shots', 'assets', 'avatars', 'leads'],
        city_banned_visuals: CITY_PROFILES[city].banned,
      },
    }

    try {
      const response = await fetch(`${normalizeApiBase(apiBase)}/api/video/full-ai/tts-first/start`, {
        method: 'POST',
        headers: authHeaders(token),
        body: JSON.stringify(payload),
      })
      const data = (await response.json()) as JobPayload
      if (!response.ok || data.ok === false) throw new Error(data.error || `生成接口失败：HTTP ${response.status}`)
      if (!data.job_id) throw new Error('后端没有返回 job_id')
      setJob(data)
      setJobId(data.job_id)
    } catch (err) {
      setIsGenerating(false)
      setError(err instanceof Error ? err.message : '生成失败')
    }
  }

  function useAssetForVideo(asset: AssetItem) {
    setSourceMode(asset.type === 'link' ? 'hot_link' : 'douyin_home')
    setSourceUrl(asset.url)
    setCity(asset.city)
    setManualKeywords((items) => Array.from(new Set([...items, ...asset.tags])))
    setActiveModule('video')
    setStep(1)
  }

  function analyzeLead() {
    const text = leadDraft.trim()
    if (!text) return
    const leadInsights = extractKeywords(text, city, [])
    const score = Math.min(100, 40 + leadInsights.length * 12 + (text.includes('预算') || /\d+/.test(text) ? 18 : 0))
    const intent = score >= 75 ? '强意向' : score >= 55 ? '中意向' : '待培育'
    const reply = `可以的，我先按你的预算和用途帮你筛。${text.includes('华语') || text.includes('华人') ? '如果你更关注华语生活圈，可以优先看 Mont Kiara、KLCC 周边和成熟社区。' : '如果是吉隆坡，建议先看 KLCC、TRX、Mont Kiara 的生活半径和出租需求。'}你更偏自住还是投资出租？`
    const item: LeadItem = { id: `lead_${Date.now()}`, source: '手动输入', text, intent, score, reply }
    setLeads((items) => [item, ...items])
  }

  function renderKeywordPanel() {
    const groups = ['预算', '区域', '人群', '卖点', '风控', '画面锚点', '自定义']
    return (
      <div className="vcw-keyword-panel">
        <div className="vcw-panel-title">AI 关键词洞察</div>
        <div className="vcw-keyword-input">
          <input value={manualKeywordInput} onChange={(event) => setManualKeywordInput(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') addManualKeyword() }} placeholder="手动补充要凸显的词，比如华语、150万、大平层" />
          <button onClick={addManualKeyword}>添加</button>
        </div>
        {groups.map((group) => {
          const items = insights.filter((item) => item.category === group)
          if (!items.length) return null
          return <div key={group} className="vcw-keyword-group"><span>{group}</span><div>{items.map((item) => <button key={`${item.category}-${item.value}`} title={item.reason} onClick={() => setManualKeywords((old) => Array.from(new Set([...old, item.value])))}>{item.value}</button>)}</div></div>
        })}
      </div>
    )
  }

  function renderStepOne() {
    return (
      <div className="vcw-step-grid wide-main">
        <section className="vcw-card">
          <div className="vcw-section-head"><h2>内容来源</h2><p>选择输入方式，系统会把主题、同行和关键词联动到文案、配音和镜头。</p></div>
          <div className="vcw-source-tabs">
            {(Object.keys(SOURCE_LABELS) as SourceMode[]).map((mode) => <button key={mode} className={sourceMode === mode ? 'active' : ''} onClick={() => setSourceMode(mode)}>{SOURCE_LABELS[mode]}</button>)}
          </div>

          {sourceMode !== 'custom_topic' && <label className="vcw-field"><span>{sourceMode === 'douyin_home' ? '同行主页链接' : '爆款视频链接'}</span><input value={sourceUrl} onChange={(event) => setSourceUrl(event.target.value)} placeholder="粘贴抖音 / Instagram / TikTok 链接" /></label>}
          <label className="vcw-field"><span>视频主题</span><input value={topic} onChange={(event) => setTopic(event.target.value)} placeholder="例如：马来西亚吉隆坡买房，别只看价格" /></label>
          <div className="vcw-grid-3">
            <label className="vcw-field"><span>预计视频长度</span><select value={targetDuration} onChange={(event) => setTargetDuration(Number(event.target.value))}><option value={15}>15 秒</option><option value={20}>20 秒</option><option value={30}>30 秒</option><option value={45}>45 秒</option><option value={60}>60 秒</option></select></label>
            <label className="vcw-field"><span>城市锁定</span><select value={city} onChange={(event) => setCity(event.target.value as CityKey)}>{(Object.keys(CITY_PROFILES) as CityKey[]).map((key) => <option key={key} value={key}>{CITY_PROFILES[key].label}</option>)}</select></label>
            <label className="vcw-field"><span>内容方向</span><select value={contentType} onChange={(event) => setContentType(event.target.value as ContentType)}>{(Object.keys(CONTENT_LABELS) as ContentType[]).map((key) => <option key={key} value={key}>{CONTENT_LABELS[key]}</option>)}</select></label>
          </div>
          <div className="vcw-action-row"><button className="vcw-primary" onClick={applyGeneratedScript}>大脑生成文案</button><button className="vcw-secondary" onClick={() => setScript('')}>清空重来</button></div>
        </section>
        {renderKeywordPanel()}
      </div>
    )
  }

  function renderStepTwo() {
    const { min, max } = targetChars(targetDuration)
    return (
      <div className="vcw-step-grid three-cols">
        <section className="vcw-card"><div className="vcw-section-head"><h2>口播文案</h2><p>建议字数：{min}-{max}，当前字数：{effectiveScript.length}</p></div><textarea className="vcw-script-box" value={script || effectiveScript} onChange={(event) => setScript(event.target.value)} /></section>
        <section className="vcw-card"><div className="vcw-section-head"><h2>逐句配音</h2><p>点某一句，才展示该句的速度、语调、语气、停顿。</p></div><div className="vcw-segment-list">{segments.map((segment) => <button key={segment.id} className={activeSegmentId === segment.id ? 'active' : ''} onClick={() => { setActiveSegmentId(segment.id); setSegmentSettings((old) => ({ ...old, [segment.id]: old[segment.id] || defaultVoiceSetting(segment) })) }}><b>{String(segment.index).padStart(2, '0')}</b><span>{renderHighlightedText(segment.text, segment.keywords)}</span></button>)}</div></section>
        <section className="vcw-card">{selectedSegment ? <SegmentEditor segment={selectedSegment} value={segmentSettings[selectedSegment.id] || defaultVoiceSetting(selectedSegment)} onChange={updateSelectedSegment} /> : <div className="vcw-empty-select"><strong>选择一句口播</strong><span>选择后才显示这句的语速、语调、语气、停顿和重点词。</span></div>}</section>
      </div>
    )
  }

  function renderStepThree() {
    return (
      <div className="vcw-step-grid three-cols">
        <section className="vcw-card"><div className="vcw-section-head"><h2>画面策略</h2><p>镜头可手动改，最终会和前端 payload 一起传给后端。</p></div><label className="vcw-field"><span>素材策略</span><select value={materialStrategy} onChange={(event) => setMaterialStrategy(event.target.value as MaterialStrategy)}>{(Object.keys(MATERIAL_LABELS) as MaterialStrategy[]).map((key) => <option key={key} value={key}>{MATERIAL_LABELS[key]}</option>)}</select></label><div className="vcw-lock-card"><strong>城市锁定：{currentProfile.label}</strong><div className="vcw-chip-row">{currentProfile.anchors.map((item) => <span className="vcw-chip purple" key={item}>{item}</span>)}</div><small>禁用：{currentProfile.banned.join(' / ')}</small></div><label className="vcw-switch"><input type="checkbox" checked={useAvatar} onChange={(event) => setUseAvatar(event.target.checked)} />启用数字人讲解</label>{useAvatar && <label className="vcw-field"><span>数字人</span><select value={avatarName} onChange={(event) => setAvatarName(event.target.value)}>{avatars.map((item) => <option key={item.id} value={item.name}>{item.name} · {item.style}</option>)}</select></label>}<div className="vcw-action-row"><button className="vcw-secondary" onClick={regenerateShots}>按当前文案重排镜头</button><button className="vcw-secondary" onClick={addShot}>新增镜头</button></div></section>
        <section className="vcw-card"><div className="vcw-section-head"><h2>镜头列表</h2><p>点击镜头后可改画面、时长、运镜和转场。</p></div><div className="vcw-shot-list">{displayedShots.map((shot) => <button key={shot.id} className={activeShotId === shot.id ? 'active' : ''} onClick={() => setActiveShotId(shot.id)}><b>{String(shot.index).padStart(2, '0')}</b><span><strong>{shot.title}</strong><em>{shot.duration}s · {TRANSITION_LABELS[shot.transition]}</em></span></button>)}</div></section>
        <section className="vcw-card">{selectedShot ? <ShotEditor shot={selectedShot} onChange={(patch) => updateShot(selectedShot.id, patch)} onDuplicate={() => duplicateShot(selectedShot.id)} onDelete={() => deleteShot(selectedShot.id)} /> : <div className="vcw-empty-select"><strong>暂无镜头</strong><span>点击新增镜头或按文案重排。</span></div>}</section>
      </div>
    )
  }

  function renderStepFour() {
    return (
      <div className="vcw-step-grid three-cols">
        <section className="vcw-card"><div className="vcw-section-head"><h2>成片预览</h2><p>最终视频时长跟随真实配音。</p></div>{videoUrl ? <video className="vcw-video" src={videoUrl} controls playsInline /> : <div className="vcw-video-placeholder"><div>🎬</div><strong>{isGenerating ? '正在生成成片' : '点击生成后在这里预览'}</strong><span>先生成配音，再按真实时长生成画面和合成。</span></div>}<div className="vcw-action-row"><button className="vcw-primary" disabled={isGenerating} onClick={startGenerate}>{isGenerating ? '生成中...' : '开始生成成片'}</button>{videoUrl && <a className="vcw-secondary link" href={videoUrl} target="_blank" rel="noreferrer">打开成片链接</a>}</div>{error && <div className="vcw-error">{error}</div>}</section>
        <section className="vcw-card"><div className="vcw-section-head"><h2>生成状态</h2><p>联动链路：内容 → 逐句配音 → 镜头 → 素材/数字人 → 成片。</p></div><div className="vcw-status-list"><Row label="任务" value={jobId || '-'} /><Row label="阶段" value={job?.stage || job?.status || (isGenerating ? 'running' : 'ready')} /><Row label="配音实际" value={audioDuration ? `${audioDuration.toFixed(1)}s` : '生成后读取'} /><Row label="镜头数量" value={`${Number(job?.shot_count || displayedShots.length)} 个`} /><Row label="城市锁定" value={currentProfile.shortLabel} /></div><div className="vcw-mini-progress"><span style={{ width: `${Math.min(100, Number(job?.progress || (isGenerating ? 62 : 0)))}%` }} /></div>{isFailedStatus(job) && <div className="vcw-error">{job?.error || job?.child_job?.error || '生成失败，请检查后端日志'}</div>}</section>
        <section className="vcw-card"><div className="vcw-section-head"><h2>发布准备</h2><p>成片后可接入评论获客和发布文案。</p></div><div className="vcw-summary-grid"><strong>{audioDuration ? `${audioDuration.toFixed(1)}s` : `${targetDuration}s`}</strong><small>视频时长</small><strong>{displayedShots.length}</strong><small>镜头数量</small><strong>1080×1920</strong><small>竖屏规格</small><strong>{insights.length}</strong><small>关键词</small></div><button className="vcw-secondary full" onClick={() => { setActiveModule('leads'); setLeadDraft(`我想了解${topic}，预算和区域怎么选？`) }}>带入获客承接</button></section>
      </div>
    )
  }

  function renderWizardStep() {
    if (step === 1) return renderStepOne()
    if (step === 2) return renderStepTwo()
    if (step === 3) return renderStepThree()
    return renderStepFour()
  }

  function renderRightPreview() {
    return (
      <aside className="vcw-preview-panel"><h3>生成结果预览</h3>{step === 1 && <><PreviewBlock title="提取主题"><strong>{topic}</strong></PreviewBlock><PreviewBlock title="推荐文案"><p>{renderHighlightedText(effectiveScript, insights)}</p></PreviewBlock></>}{step === 2 && <PreviewBlock title="口播分段"><div className="vcw-preview-list">{segments.map((segment) => <div key={segment.id}><b>{String(segment.index).padStart(2, '0')}</b><span>{renderHighlightedText(segment.text, segment.keywords)}</span></div>)}</div></PreviewBlock>}{step === 3 && <PreviewBlock title="镜头结果"><div className="vcw-preview-list">{displayedShots.map((shot) => <div key={shot.id}><b>{String(shot.index).padStart(2, '0')}</b><span>{shot.title}</span></div>)}</div></PreviewBlock>}{step === 4 && <PreviewBlock title="成片信息"><div className="vcw-summary-grid"><strong>{audioDuration ? `${audioDuration.toFixed(1)}s` : `${targetDuration}s`}</strong><small>视频时长</small><strong>{displayedShots.length}</strong><small>镜头数量</small><strong>1080×1920</strong><small>竖屏规格</small></div></PreviewBlock>}</aside>
    )
  }

  function renderVideoModule() {
    return (
      <><header className="vcw-page-header"><div><div className="vcw-eyebrow">第 {step} 步 / 共 4 步</div><h1>第{step}步：{STEP_TITLES[step]}</h1><p>一页式创作：内容、配音、镜头、素材、数字人、获客全部联动。</p></div><div className="vcw-token-card"><span>Token</span><strong>{maskToken(token)}</strong></div></header><div className="vcw-content"><main className="vcw-workspace">{renderWizardStep()}</main>{renderRightPreview()}</div><footer className="vcw-footer"><div><span>创作进度</span><strong>{step}/4</strong><i><em style={{ width: `${(step / 4) * 100}%` }} /></i></div><nav><button className="vcw-secondary big" disabled={step === 1 || isGenerating} onClick={goPrev}>上一步</button><button className="vcw-primary big" disabled={isGenerating && step === 4} onClick={goNext}>{step === 4 ? (isGenerating ? '生成中...' : '生成成片') : '下一步'}</button></nav></footer></>
    )
  }

  function renderAssetsModule() {
    return <ModulePage title="账号素材" desc="同行主页、爆款链接和真实素材，能一键带入视频创作。"><div className="vcw-module-grid"><section className="vcw-card"><h2>素材录入</h2><AssetForm onAdd={(asset) => setAssets((items) => [asset, ...items])} defaultCity={city} /></section><section className="vcw-card"><h2>已保存素材</h2><div className="vcw-asset-list">{assets.map((asset) => <div className="vcw-asset-item" key={asset.id}><strong>{asset.name}</strong><span>{asset.type} · {CITY_PROFILES[asset.city].shortLabel} · {asset.tags.join(' / ') || '未打标'}</span><div><button onClick={() => useAssetForVideo(asset)}>带入视频创作</button><button onClick={() => setAssets((items) => items.filter((item) => item.id !== asset.id))}>删除</button></div></div>)}</div></section></div></ModulePage>
  }

  function renderAvatarsModule() {
    return <ModulePage title="数字人库" desc="数字人不强制使用，但可和口播配音、镜头策略联动。"><div className="vcw-module-grid">{avatars.map((avatar) => <section className="vcw-card vcw-avatar-card" key={avatar.id}><div className="vcw-avatar-face">{avatar.name.slice(0, 1)}</div><h2>{avatar.name}</h2><p>{avatar.role} · {avatar.style}</p><label className="vcw-switch"><input type="checkbox" checked={avatar.enabled} onChange={(event) => setAvatars((items) => items.map((item) => item.id === avatar.id ? { ...item, enabled: event.target.checked } : item))} />启用</label><button className="vcw-secondary" onClick={() => { setUseAvatar(true); setAvatarName(avatar.name); setActiveModule('video'); setStep(3) }}>用于当前视频</button></section>)}</div></ModulePage>
  }

  function renderLeadsModule() {
    return <ModulePage title="获客线索" desc="把评论、私信和咨询问题转成意向评分与回复建议。"><div className="vcw-module-grid"><section className="vcw-card"><h2>评论/私信分析</h2><textarea className="vcw-script-box small" value={leadDraft} onChange={(event) => setLeadDraft(event.target.value)} /><button className="vcw-primary" onClick={analyzeLead}>分析线索</button></section><section className="vcw-card"><h2>线索结果</h2><div className="vcw-lead-list">{leads.map((lead) => <div className="vcw-lead-item" key={lead.id}><strong>{lead.intent} · {lead.score} 分</strong><p>{lead.text}</p><span>{lead.reply}</span><button onClick={() => { setTopic(lead.text); setActiveModule('video'); setStep(1) }}>作为选题生成视频</button></div>)}</div></section></div></ModulePage>
  }

  function renderSettingsModule() {
    return <ModulePage title="设置" desc="统一管理后端地址、Token 和默认策略。"><div className="vcw-module-grid"><section className="vcw-card"><h2>接口设置</h2><label className="vcw-field"><span>后端地址</span><input value={apiBase} onChange={(event) => setApiBase(event.target.value)} /></label><label className="vcw-field"><span>Token</span><input value={token} onChange={(event) => setToken(event.target.value)} placeholder="粘贴后台 Token" type="password" /></label><button className="vcw-secondary" onClick={() => { safeWrite('AI_VIDEO_API_BASE', apiBase); safeWrite('AI_VIDEO_TOKEN', token) }}>保存设置</button></section><section className="vcw-card"><h2>默认偏好</h2><label className="vcw-field"><span>默认城市</span><select value={city} onChange={(event) => setCity(event.target.value as CityKey)}>{(Object.keys(CITY_PROFILES) as CityKey[]).map((key) => <option key={key} value={key}>{CITY_PROFILES[key].label}</option>)}</select></label><label className="vcw-field"><span>默认素材策略</span><select value={materialStrategy} onChange={(event) => setMaterialStrategy(event.target.value as MaterialStrategy)}>{(Object.keys(MATERIAL_LABELS) as MaterialStrategy[]).map((key) => <option key={key} value={key}>{MATERIAL_LABELS[key]}</option>)}</select></label></section></div></ModulePage>
  }

  function renderActiveModule() {
    if (activeModule === 'assets') return renderAssetsModule()
    if (activeModule === 'avatars') return renderAvatarsModule()
    if (activeModule === 'leads') return renderLeadsModule()
    if (activeModule === 'settings') return renderSettingsModule()
    return renderVideoModule()
  }

  return (
    <div className="vcw-console"><aside className="vcw-sidebar"><div className="vcw-brand"><strong>AI-VIDEO</strong><span>智能增长工作台</span></div><nav className="vcw-side-nav">{(Object.keys(MODULE_LABELS) as ModuleKey[]).map((key) => <button key={key} className={activeModule === key ? 'active' : ''} onClick={() => setActiveModule(key)}>{MODULE_LABELS[key]}</button>)}</nav><div className="vcw-mode-card"><strong>创作模式</strong><span>TTS-first</span><small>先配音，再按真实时长生成画面。所有模块联动到视频创作。</small></div></aside><section className="vcw-body">{renderActiveModule()}</section></div>
  )
}

function Row({ label, value }: { label: string; value: string }) { return <div><span>{label}</span><strong>{value}</strong></div> }
function PreviewBlock({ title, children }: { title: string; children: React.ReactNode }) { return <section className="vcw-preview-block"><span>{title}</span>{children}</section> }
function ModulePage({ title, desc, children }: { title: string; desc: string; children: React.ReactNode }) { return <><header className="vcw-page-header"><div><div className="vcw-eyebrow">AI-VIDEO 中控</div><h1>{title}</h1><p>{desc}</p></div></header>{children}</> }

function SegmentEditor({ segment, value, onChange }: { segment: ScriptSegment; value: SegmentVoiceSetting; onChange: (patch: Partial<SegmentVoiceSetting>) => void }) {
  const toggleEmphasis = (word: string) => {
    const exists = value.emphasis.includes(word)
    onChange({ emphasis: exists ? value.emphasis.filter((item) => item !== word) : [...value.emphasis, word] })
  }
  return <div className="vcw-segment-editor"><div className="vcw-section-head"><h2>第 {segment.index} 句表达</h2><p>{segment.text}</p></div><label className="vcw-field"><span>语气</span><select value={value.tone} onChange={(event) => onChange({ tone: event.target.value })}><option>专业可信</option><option>重点强调</option><option>谨慎专业</option><option>亲和可信</option><option>成交引导</option></select></label><label className="vcw-field"><span>情绪</span><select value={value.emotion} onChange={(event) => onChange({ emotion: event.target.value })}><option>自然平稳</option><option>专业提醒</option><option>惊喜</option><option>亲和可信</option><option>紧迫感</option></select></label><Slider label="语速" value={value.speed} min={0.75} max={1.25} step={0.05} onChange={(speed) => onChange({ speed })} /><Slider label="语调" value={value.pitch} min={0.8} max={1.2} step={0.05} onChange={(pitch) => onChange({ pitch })} /><Slider label="音量" value={value.volume} min={0.6} max={1.3} step={0.05} onChange={(volume) => onChange({ volume })} /><div className="vcw-grid-2"><label className="vcw-field"><span>句前停顿</span><input type="number" value={value.pauseBefore} min={0} max={2} step={0.1} onChange={(event) => onChange({ pauseBefore: Number(event.target.value) })} /></label><label className="vcw-field"><span>句后停顿</span><input type="number" value={value.pauseAfter} min={0} max={2} step={0.1} onChange={(event) => onChange({ pauseAfter: Number(event.target.value) })} /></label></div><div className="vcw-keyword-group"><span>本句重点词</span><div>{segment.keywords.length ? segment.keywords.map((item) => <button key={item.value} className={value.emphasis.includes(item.value) ? 'active' : ''} onClick={() => toggleEmphasis(item.value)}>{item.value}</button>) : <em>AI 暂未识别重点词，可在第一步手动添加。</em>}</div></div><label className="vcw-field"><span>表达备注</span><textarea value={value.note} onChange={(event) => onChange({ note: event.target.value })} placeholder="例如：150万、大平层、华语这些词要放慢强调" /></label></div>
}

function Slider({ label, value, min, max, step, onChange }: { label: string; value: number; min: number; max: number; step: number; onChange: (value: number) => void }) {
  return <label className="vcw-slider"><span>{label} {value.toFixed(2)}</span><input type="range" value={value} min={min} max={max} step={step} onChange={(event) => onChange(Number(event.target.value))} /></label>
}

function ShotEditor({ shot, onChange, onDuplicate, onDelete }: { shot: ShotPlan; onChange: (patch: Partial<ShotPlan>) => void; onDuplicate: () => void; onDelete: () => void }) {
  return <div className="vcw-shot-editor"><div className="vcw-section-head"><h2>镜头 {shot.index} 编辑</h2><p>可手动改画面主体、口播、时长、素材来源、运镜、转场和 Prompt。</p></div><label className="vcw-field"><span>镜头标题</span><input value={shot.title} onChange={(event) => onChange({ title: event.target.value })} /></label><label className="vcw-field"><span>画面主体</span><input value={shot.scene} onChange={(event) => onChange({ scene: event.target.value })} /></label><label className="vcw-field"><span>对应口播</span><textarea value={shot.narration} onChange={(event) => onChange({ narration: event.target.value })} /></label><div className="vcw-grid-2"><label className="vcw-field"><span>时长</span><input type="number" value={shot.duration} min={1} max={12} step={0.1} onChange={(event) => onChange({ duration: Number(event.target.value) })} /></label><label className="vcw-field"><span>素材来源</span><select value={shot.materialSource} onChange={(event) => onChange({ materialSource: event.target.value as MaterialSource })}><option value="real">真实素材</option><option value="ai">AI 生成</option><option value="mixed">混合</option></select></label></div><div className="vcw-grid-2"><label className="vcw-field"><span>运镜</span><select value={shot.cameraMove} onChange={(event) => onChange({ cameraMove: event.target.value as CameraMove })}>{(Object.keys(CAMERA_LABELS) as CameraMove[]).map((key) => <option key={key} value={key}>{CAMERA_LABELS[key]}</option>)}</select></label><label className="vcw-field"><span>转场</span><select value={shot.transition} onChange={(event) => onChange({ transition: event.target.value as TransitionMode })}>{(Object.keys(TRANSITION_LABELS) as TransitionMode[]).map((key) => <option key={key} value={key}>{TRANSITION_LABELS[key]}</option>)}</select></label></div><label className="vcw-field"><span>AI Prompt</span><textarea value={shot.prompt} onChange={(event) => onChange({ prompt: event.target.value })} /></label><div className="vcw-negative-box"><span>禁用画面</span>{shot.negativeRules.map((item) => <b key={item}>{item}</b>)}</div><div className="vcw-action-row"><button className="vcw-secondary" onClick={onDuplicate}>复制镜头</button><button className="vcw-danger" onClick={onDelete}>删除镜头</button></div></div>
}

function AssetForm({ onAdd, defaultCity }: { onAdd: (asset: AssetItem) => void; defaultCity: CityKey }) {
  const [name, setName] = useState('')
  const [url, setUrl] = useState('')
  const [type, setType] = useState<AssetItem['type']>('account')
  const [city, setCity] = useState<CityKey>(defaultCity)
  const [tags, setTags] = useState('')
  return <div><label className="vcw-field"><span>名称</span><input value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：KL 房产同行主页" /></label><label className="vcw-field"><span>链接</span><input value={url} onChange={(event) => setUrl(event.target.value)} placeholder="主页 / 爆款视频 / 素材链接" /></label><div className="vcw-grid-2"><label className="vcw-field"><span>类型</span><select value={type} onChange={(event) => setType(event.target.value as AssetItem['type'])}><option value="account">账号主页</option><option value="link">爆款链接</option><option value="material">真实素材</option></select></label><label className="vcw-field"><span>城市</span><select value={city} onChange={(event) => setCity(event.target.value as CityKey)}>{(Object.keys(CITY_PROFILES) as CityKey[]).map((key) => <option key={key} value={key}>{CITY_PROFILES[key].shortLabel}</option>)}</select></label></div><label className="vcw-field"><span>标签</span><input value={tags} onChange={(event) => setTags(event.target.value)} placeholder="用逗号分隔，比如 KLCC,华语,投资" /></label><button className="vcw-primary" onClick={() => { if (!name.trim()) return; onAdd({ id: `asset_${Date.now()}`, name, url, type, city, tags: tags.split(/[,，]/).map((item) => item.trim()).filter(Boolean), status: 'ready' }); setName(''); setUrl(''); setTags('') }}>保存素材</button></div>
}
