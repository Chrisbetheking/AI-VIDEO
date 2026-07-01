import React, { useEffect, useMemo, useState } from 'react'

type ModuleKey = 'video' | 'assets' | 'avatars' | 'leads' | 'settings'
type WizardStep = 1 | 2 | 3 | 4
type SourceMode = 'account' | 'viral' | 'custom'
type CityKey = 'kuala_lumpur' | 'penang' | 'johor' | 'langkawi' | 'sabah'
type ContentType = 'investment' | 'own_stay' | 'second_home' | 'rental' | 'education'
type MaterialStrategy = 'real_first' | 'r2_first' | 'ai_fill' | 'full_ai'
type MaterialSource = 'r2' | 'real' | 'ai' | 'mixed'
type LeadStatus = 'pending_human' | 'qualified' | 'not_fit' | 'topic_seed'

type KeywordInsight = {
  id: string
  category: string
  value: string
  reason: string
  priority: 'high' | 'medium' | 'low'
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
  source: MaterialSource
  camera: string
  transition: string
  prompt: string
  avoid: string[]
  assetIds: string[]
}

type AssetItem = {
  id: string
  name: string
  url: string
  source: 'r2' | 'account' | 'viral' | 'upload' | 'manual'
  city: CityKey
  tags: string[]
  kind: 'video' | 'image' | 'account' | 'link'
}

type AvatarItem = {
  id: string
  name: string
  role: string
  photoUrl: string
  tags: string[]
  enabled: boolean
}

type LeadItem = {
  id: string
  source: string
  text: string
  intent: string
  score: number
  reason: string
  firstMessage: string
  status: LeadStatus
  createdAt: string
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
  child_job?: Record<string, any>
  result?: Record<string, any>
  [key: string]: any
}

const STATE_KEY = 'AI_VIDEO_CONSOLE_V4_STATE'
const TOKEN_KEYS = ['AI_VIDEO_TOKEN', 'ai_video_token', 'AI_VIDEO_ADMIN_TOKEN', 'token']

const MODULE_LABELS: Record<ModuleKey, string> = {
  video: '视频创作',
  assets: '素材库',
  avatars: '数字人库',
  leads: '获客线索',
  settings: '设置',
}

const STEP_TITLES: Record<WizardStep, string> = {
  1: '搞定内容与关键词',
  2: '逐句配音表达',
  3: '镜头和素材联动',
  4: '成片与获客承接',
}

const SOURCE_LABELS: Record<SourceMode, string> = {
  account: '抖音主页',
  viral: '爆款链接',
  custom: '自定义主题',
}

const CITY_PROFILES: Record<CityKey, { label: string; short: string; anchors: string[]; scenes: string[]; banned: string[] }> = {
  kuala_lumpur: {
    label: '吉隆坡 / Kuala Lumpur',
    short: '吉隆坡',
    anchors: ['KLCC', 'TRX', 'Mont Kiara', '公寓阳台', '大堂', '泳池', '城市夜景'],
    scenes: [
      'KLCC 双子塔天际线 + 高层公寓建立镜头',
      'TRX 金融区 + 高端住宅区位镜头',
      'Mont Kiara 高端公寓社区生活氛围',
      '公寓阳台看吉隆坡城市天际线',
      '现代公寓客厅 + 落地窗城市景观',
      '高端公寓大堂 / 泳池 / 健身房设施',
    ],
    banned: ['海边', '沙滩', '海岛', '兰卡威', '沙巴海景', '槟城海景', '文件桌面', '计算器', '乱码文字'],
  },
  penang: {
    label: '槟城 / Penang',
    short: '槟城',
    anchors: ['Gurney Drive', '海景公寓', '养老生活', '滨海天际线', '阳台'],
    scenes: ['槟城滨海住宅天际线', '海景公寓阳台生活方式', '现代公寓室内 + 海景窗景', '养老和第二家园生活氛围'],
    banned: ['假项目名', '精确 ROI', '乱码文字', '文件桌面'],
  },
  johor: {
    label: '新山 / Johor Bahru',
    short: '新山',
    anchors: ['新山城市', 'Medini', '公寓社区', '通勤生活', '家庭自住'],
    scenes: ['新山城市住宅区位镜头', 'Medini 现代公寓社区', '家庭自住公寓室内空间', '城市通勤和生活配套氛围'],
    banned: ['海岛度假感', '假学校名', '假价格牌', '乱码文字', '文件桌面'],
  },
  langkawi: {
    label: '兰卡威 / Langkawi',
    short: '兰卡威',
    anchors: ['度假住宅', '岛屿生活', '泳池', '第二家园', '热带景观'],
    scenes: ['兰卡威度假型住宅和泳池', '热带绿植中的第二家园生活', '岛屿度假住宅生活方式', '度假社区公共空间'],
    banned: ['吉隆坡金融区冒充', '假项目名', '精确 ROI', '乱码文字', '文件桌面'],
  },
  sabah: {
    label: '沙巴 / Sabah',
    short: '沙巴',
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
  r2_first: 'R2 素材优先',
  ai_fill: 'AI 补足',
  full_ai: '全 AI 生成',
}

const DEFAULT_ASSETS: AssetItem[] = [
  { id: 'asset_kl_account', name: '吉隆坡房产同行主页', url: '', source: 'account', city: 'kuala_lumpur', tags: ['KLCC', '投资', '华语'], kind: 'account' },
  { id: 'asset_viral_sample', name: '爆款视频链接样例', url: '', source: 'viral', city: 'kuala_lumpur', tags: ['避坑', '预算'], kind: 'link' },
]

const DEFAULT_AVATARS: AvatarItem[] = [
  { id: 'avatar_property_advisor', name: '地产顾问', role: '海外置业讲解 · 专业可信', photoUrl: '', tags: ['华语', '专业', '置业'], enabled: true },
  { id: 'avatar_growth_advisor', name: '增长顾问', role: '获客转化 · 干练直接', photoUrl: '', tags: ['获客', '转化'], enabled: false },
]

function safeRead(key: string): string {
  try { return window.localStorage.getItem(key) || '' } catch { return '' }
}

function safeWrite(key: string, value: string) {
  try { window.localStorage.setItem(key, value) } catch { /* noop */ }
}

function safeRemove(key: string) {
  try { window.localStorage.removeItem(key) } catch { /* noop */ }
}

function parseState(): Record<string, any> {
  try {
    const raw = safeRead(STATE_KEY)
    return raw ? JSON.parse(raw) : {}
  } catch {
    return {}
  }
}

function defaultApiBase(): string {
  const local = safeRead('AI_VIDEO_API_BASE') || safeRead('ai_video_api_base')
  const envValue = (import.meta as any).env?.VITE_AI_VIDEO_API_BASE
  return String(local || envValue || 'https://ai-video.47-76-143-158.sslip.io').trim().replace(/\/+$/, '')
}

function hiddenAuthToken(): string {
  for (const key of TOKEN_KEYS) {
    const val = safeRead(key)
    if (val) return val
  }
  return String((import.meta as any).env?.VITE_AI_VIDEO_TOKEN || '')
}

function authHeaders(): HeadersInit {
  const token = hiddenAuthToken().trim()
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (token) {
    headers['X-AI-Video-Token'] = token
    headers.Authorization = `Bearer ${token}`
  }
  return headers
}

function uid(prefix: string): string {
  return `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`
}

function stableId(text: string): string {
  let hash = 2166136261
  for (let i = 0; i < text.length; i += 1) {
    hash ^= text.charCodeAt(i)
    hash += (hash << 1) + (hash << 4) + (hash << 7) + (hash << 8) + (hash << 24)
  }
  return Math.abs(hash >>> 0).toString(36)
}

function targetChars(duration: number): { min: number; max: number } {
  return { min: Math.max(40, Math.floor(duration * 4.3)), max: Math.max(60, Math.floor(duration * 5.3)) }
}

function splitSentences(script: string): string[] {
  return String(script || '')
    .replace(/\s+/g, ' ')
    .split(/[。！？!?；;\n]+/)
    .map((item) => item.trim())
    .filter(Boolean)
}

function buildScript(topic: string, city: CityKey, duration: number, contentType: ContentType, manualKeywords: string[]): string {
  const profile = CITY_PROFILES[city]
  const title = topic.trim() || `${profile.short}买房，别只看价格`
  const keywordSentence = manualKeywords.length ? `这条内容重点讲${manualKeywords.join('、')}。` : ''
  const { min, max } = targetChars(duration)
  let script = ''

  if (city === 'kuala_lumpur') {
    script = `${title}。很多人买马来西亚房产，第一眼只看价格，但在吉隆坡，真正要先看区域、用途和流动性。KLCC、TRX、Mont Kiara 这些位置，看的不是热闹，而是生活半径、出租需求和未来转手。${keywordSentence}`
    if (contentType === 'investment') script += '如果是投资配置，先看租客是谁、通勤是否方便、周边配套是否成熟，再看价格是否合理。'
    if (contentType === 'own_stay') script += '如果是自住，重点不是短期涨跌，而是生活便利、社区品质和长期居住舒适度。'
    if (contentType === 'second_home') script += '如果是第二家园，要看医疗、交通、生活便利度和长期持有体验。'
    if (contentType === 'rental') script += '如果看出租，重点是目标租客、通勤半径、交付品质和后续管理。'
    if (contentType === 'education') script += '如果考虑家庭和教育，要把通勤、社区、安全感和长期居住需求放在前面。'
  } else {
    script = `${title}。马来西亚买房不要只看价格，要先看城市、用途和生活方式。${profile.short}更适合${CONTENT_LABELS[contentType]}方向的人群，重点要看区域成熟度、生活配套、未来使用场景和转手流动性。${keywordSentence}先把预算、用途和持有周期想清楚，再去筛项目。`
  }

  while (script.length < min) {
    script += city === 'kuala_lumpur'
      ? ' 吉隆坡项目重点看区位价值、生活便利度、出租需求、社区品质和未来转手逻辑。'
      : ` ${profile.short}项目重点看生活方式、配套成熟度、长期使用场景和资产流动性。`
  }
  if (script.length > max) script = script.slice(0, max).replace(/[，,、\s]+$/g, '') + '。'
  return script
}

function addInsight(list: KeywordInsight[], category: string, value: string, reason: string, priority: KeywordInsight['priority'] = 'medium') {
  const clean = value.trim()
  if (!clean) return
  const id = `${category}:${clean}`.toLowerCase()
  if (list.some((item) => item.id.toLowerCase() === id)) return
  list.push({ id, category, value: clean, reason, priority })
}

function detectInsights(script: string, city: CityKey, manualKeywords: string[]): KeywordInsight[] {
  const raw = `${script} ${manualKeywords.join(' ')}`
  const list: KeywordInsight[] = []
  const money = raw.match(/(?:\d+(?:\.\d+)?\s*(?:万|百万|亿|马币|人民币|RM|rm|㎡|平|大平层))|(?:RM\s*\d+(?:\.\d+)?)/g) || []
  money.forEach((item) => addInsight(list, '预算/面积', item, '数字类信息要放慢，适合做字幕和口播重点', 'high'))
  ;['KLCC', 'TRX', 'Mont Kiara', '吉隆坡', 'Kuala Lumpur', '槟城', 'Penang', '新山', 'Johor', '兰卡威', 'Langkawi', '沙巴', 'Sabah'].forEach((word) => {
    if (raw.toLowerCase().includes(word.toLowerCase())) addInsight(list, '区域', word, '区域决定素材、镜头和专业判断', 'high')
  })
  ;['华人', '华语', '中文', '英语', '马来语', '本地人', '外籍', '租客', '家庭', '养老', '留学'].forEach((word) => {
    if (raw.includes(word)) addInsight(list, '人群/语言', word, '涉及人群和语言环境，表达要客观、亲和、不能绝对化', 'high')
  })
  ;['出租', '流动性', '转手', '自住', '投资', '第二家园', '教育', '通勤', '配套', '精装', '低总价', '租金', '生活半径'].forEach((word) => {
    if (raw.includes(word)) addInsight(list, '卖点/判断', word, '这是房产决策关键词，画面和语气都要凸显', 'medium')
  })
  ;['避坑', '风险', '误区', '别只看', '不要', '谨慎', '亏'].forEach((word) => {
    if (raw.includes(word)) addInsight(list, '风险提醒', word, '适合用专业可信语气，避免夸大承诺', 'medium')
  })
  CITY_PROFILES[city].anchors.forEach((word) => addInsight(list, '画面锚点', word, '用于镜头规划、R2 素材匹配和 AI 画面约束', 'low'))
  manualKeywords.forEach((word) => addInsight(list, '手动指定', word, '用户指定要凸显，优先进入口播和镜头', 'high'))
  return list.sort((a, b) => priorityScore(b.priority) - priorityScore(a.priority)).slice(0, 18)
}

function priorityScore(priority: KeywordInsight['priority']): number {
  if (priority === 'high') return 3
  if (priority === 'medium') return 2
  return 1
}

function buildSegments(script: string, insights: KeywordInsight[]): ScriptSegment[] {
  return splitSentences(script).map((text, index) => ({
    id: `seg_${index}_${stableId(text)}`,
    index: index + 1,
    text,
    keywords: insights.filter((item) => text.toLowerCase().includes(item.value.toLowerCase())).slice(0, 8),
  }))
}

function defaultVoice(segment: ScriptSegment): SegmentVoiceSetting {
  const hasMoney = segment.keywords.some((item) => item.category === '预算/面积')
  const hasRisk = segment.keywords.some((item) => item.category === '风险提醒')
  const hasPeople = segment.keywords.some((item) => item.category === '人群/语言')
  return {
    speed: hasMoney || hasRisk ? 0.92 : 1,
    pitch: hasPeople ? 1.02 : 1,
    volume: hasMoney ? 1.08 : 1,
    emotion: hasRisk ? '谨慎提醒' : hasPeople ? '亲和解释' : '自然平稳',
    tone: hasMoney ? '重点强调' : hasRisk ? '专业判断' : '专业可信',
    pauseBefore: hasMoney ? 0.2 : 0,
    pauseAfter: hasMoney || hasRisk ? 0.35 : 0.15,
    emphasis: segment.keywords.slice(0, 4).map((item) => item.value),
    note: hasMoney ? '数字、预算、面积放慢并加停顿。' : hasPeople ? '涉及人群语言，保持客观亲和。' : '',
  }
}

function planShotCount(duration: number): number {
  const count = Math.ceil(Math.max(1, duration) / 4.5)
  return duration >= 16 ? Math.max(4, count) : Math.max(1, count)
}

function pickAssetsForShot(assets: AssetItem[], city: CityKey, text: string): string[] {
  const lower = text.toLowerCase()
  return assets
    .filter((asset) => asset.city === city || asset.tags.some((tag) => lower.includes(tag.toLowerCase())))
    .slice(0, 3)
    .map((asset) => asset.id)
}

function buildShots(script: string, city: CityKey, duration: number, materialStrategy: MaterialStrategy, assets: AssetItem[]): ShotPlan[] {
  const sentences = splitSentences(script)
  const count = planShotCount(duration)
  const each = Math.round((duration / count) * 10) / 10
  const scenes = CITY_PROFILES[city].scenes
  const defaultSource: MaterialSource = materialStrategy === 'full_ai' ? 'ai' : materialStrategy === 'r2_first' ? 'r2' : materialStrategy === 'real_first' ? 'real' : 'mixed'
  return Array.from({ length: count }, (_, index) => {
    const narration = sentences[index % Math.max(1, sentences.length)] || script
    const scene = scenes[index % scenes.length]
    const assetIds = pickAssetsForShot(assets, city, `${scene} ${narration}`)
    const source = assetIds.length && materialStrategy !== 'full_ai' ? 'r2' : defaultSource
    return {
      id: `shot_${index}_${stableId(scene + narration)}`,
      index: index + 1,
      title: scene,
      scene,
      narration,
      duration: each,
      source,
      camera: index % 3 === 0 ? '缓慢推进' : index % 3 === 1 ? '横向平移' : '稳定定镜',
      transition: index === 0 ? '自然过渡' : index % 2 === 0 ? '室外切室内' : '关键词卡点',
      prompt: makePrompt(city, scene, narration),
      avoid: CITY_PROFILES[city].banned,
      assetIds,
    }
  })
}

function makePrompt(city: CityKey, scene: string, narration: string): string {
  const rule = city === 'kuala_lumpur'
    ? 'Kuala Lumpur city real-estate visuals only: KLCC, TRX, Mont Kiara, city skyline, condo balcony, condo interior, lobby, pool. No seaside, no island, no beach.'
    : `Malaysia real-estate visuals for ${CITY_PROFILES[city].label}.`
  return `Premium 9:16 cinematic vertical video for Malaysia real estate. Main scene: ${scene}. Narration meaning: ${narration}. ${rule} Ultra realistic commercial style, natural light, clean composition, smooth camera movement. No readable text, no logo, no watermark, no fake project name, no exact price, no exact ROI, no black borders.`
}

function updateShotIndexes(shots: ShotPlan[]): ShotPlan[] {
  return shots.map((shot, index) => ({ ...shot, index: index + 1 }))
}

function highlight(text: string, insights: KeywordInsight[]): any {
  const keys = insights.map((item) => item.value).filter((item) => item.length >= 2).slice(0, 24)
  if (!keys.length) return text
  const escaped = keys.map((key) => key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  const pattern = new RegExp(`(${escaped.join('|')})`, 'gi')
  return text.split(pattern).map((part, index) => {
    const hit = keys.some((key) => key.toLowerCase() === part.toLowerCase())
    return hit ? <mark key={`${part}-${index}`}>{part}</mark> : <React.Fragment key={`${part}-${index}`}>{part}</React.Fragment>
  })
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
    job.child_job?.url,
    job.child_job?.result?.video_url,
    job.child_job?.result?.output_url,
    job.child_job?.result?.result_url,
  ]
  return String(urls.find((item) => typeof item === 'string' && item) || '')
}

function isFinal(job: JobPayload | null): boolean {
  if (!job) return false
  const text = `${job.status || ''} ${job.stage || ''} ${job.child_job?.status || ''} ${job.child_job?.stage || ''}`.toLowerCase()
  return ['completed', 'succeeded', 'success', 'done', 'finished'].some((key) => text.includes(key))
}

function isFailed(job: JobPayload | null): boolean {
  if (!job) return false
  const text = `${job.status || ''} ${job.stage || ''} ${job.child_job?.status || ''} ${job.child_job?.stage || ''}`.toLowerCase()
  return ['failed', 'error', 'cancelled'].some((key) => text.includes(key))
}

function scoreLead(text: string): LeadItem {
  const lower = text.toLowerCase()
  let score = 35
  const reasons: string[] = []
  if (/预算|多少|价格|万|rm|马币|买哪里|能买吗/.test(lower)) { score += 25; reasons.push('明确预算或购买咨询') }
  if (/华人|华语|中文|语言|讲华语/.test(lower)) { score += 15; reasons.push('关心语言和人群环境') }
  if (/出租|租金|投资|收益|回报|流动性|转手/.test(lower)) { score += 20; reasons.push('有投资/出租/流动性意图') }
  if (/看房|资料|户型|项目|位置|区域|预约/.test(lower)) { score += 15; reasons.push('接近看房或资料需求') }
  score = Math.min(98, score)
  const intent = score >= 75 ? '高意向' : score >= 55 ? '中意向' : '低意向'
  const firstMessage = score >= 55
    ? '可以的，我先按你的预算和用途帮你筛一下区域。你更偏自住、出租，还是第二家园？'
    : '这个问题要结合预算、用途和城市来看。你现在主要关注自住、投资还是出租？'
  return {
    id: uid('lead'),
    source: 'OpenClaw 评论截流',
    text,
    intent,
    score,
    reason: reasons.length ? reasons.join('；') : '信息不足，需要人工进一步确认',
    firstMessage,
    status: score >= 55 ? 'pending_human' : 'not_fit',
    createdAt: new Date().toLocaleString(),
  }
}

export default function VideoCreationWizard() {
  const restored = useMemo(() => parseState(), [])
  const [activeModule, setActiveModule] = useState<ModuleKey>(restored.activeModule || 'video')
  const [step, setStep] = useState<WizardStep>(restored.step || 1)
  const [sourceMode, setSourceMode] = useState<SourceMode>(restored.sourceMode || 'account')
  const [apiBase, setApiBase] = useState(defaultApiBase)
  const [topic, setTopic] = useState(restored.topic || '马来西亚吉隆坡买房，别只看价格')
  const [sourceUrl, setSourceUrl] = useState(restored.sourceUrl || '')
  const [targetDuration, setTargetDuration] = useState<number>(restored.targetDuration || 20)
  const [city, setCity] = useState<CityKey>(restored.city || 'kuala_lumpur')
  const [contentType, setContentType] = useState<ContentType>(restored.contentType || 'investment')
  const [materialStrategy, setMaterialStrategy] = useState<MaterialStrategy>(restored.materialStrategy || 'r2_first')
  const [script, setScript] = useState(restored.script || '')
  const [manualKeywordText, setManualKeywordText] = useState('')
  const [manualKeywords, setManualKeywords] = useState<string[]>(restored.manualKeywords || ['华语', '出租需求'])
  const [segmentSettings, setSegmentSettings] = useState<Record<string, SegmentVoiceSetting>>(restored.segmentSettings || {})
  const [selectedSegmentId, setSelectedSegmentId] = useState<string>('')
  const [shots, setShots] = useState<ShotPlan[]>(restored.shots || [])
  const [selectedShotId, setSelectedShotId] = useState<string>('')
  const [assets, setAssets] = useState<AssetItem[]>(restored.assets || DEFAULT_ASSETS)
  const [selectedAssetIds, setSelectedAssetIds] = useState<string[]>(restored.selectedAssetIds || [])
  const [r2BaseUrl, setR2BaseUrl] = useState(restored.r2BaseUrl || '')
  const [r2UrlInput, setR2UrlInput] = useState('')
  const [avatars, setAvatars] = useState<AvatarItem[]>(restored.avatars || DEFAULT_AVATARS)
  const [selectedAvatarId, setSelectedAvatarId] = useState<string>(restored.selectedAvatarId || '')
  const [leadInput, setLeadInput] = useState('吉隆坡 150 万预算能买哪里？华人多吗，可以讲华语吗？')
  const [leads, setLeads] = useState<LeadItem[]>(restored.leads || [])
  const [jobId, setJobId] = useState('')
  const [job, setJob] = useState<JobPayload | null>(null)
  const [isGenerating, setIsGenerating] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const effectiveScript = useMemo(() => script.trim() || buildScript(topic, city, targetDuration, contentType, manualKeywords), [script, topic, city, targetDuration, contentType, manualKeywords])
  const insights = useMemo(() => detectInsights(effectiveScript, city, manualKeywords), [effectiveScript, city, manualKeywords])
  const segments = useMemo(() => buildSegments(effectiveScript, insights), [effectiveScript, insights])
  const plannedShots = useMemo(() => shots.length ? updateShotIndexes(shots) : buildShots(effectiveScript, city, targetDuration, materialStrategy, assets), [shots, effectiveScript, city, targetDuration, materialStrategy, assets])
  const selectedSegment = segments.find((item) => item.id === selectedSegmentId) || null
  const selectedShot = plannedShots.find((item) => item.id === selectedShotId) || plannedShots[0] || null
  const selectedAvatar = avatars.find((item) => item.id === selectedAvatarId) || null
  const selectedAssets = assets.filter((asset) => selectedAssetIds.includes(asset.id))
  const videoUrl = extractVideoUrl(job)
  const audioDuration = Number(job?.audio_duration_seconds || 0)

  useEffect(() => {
    const state = {
      activeModule, step, sourceMode, topic, sourceUrl, targetDuration, city, contentType, materialStrategy,
      script, manualKeywords, segmentSettings, shots: plannedShots, selectedAssetIds, r2BaseUrl, avatars,
      selectedAvatarId, leads, assets,
    }
    safeWrite(STATE_KEY, JSON.stringify(state))
  }, [activeModule, step, sourceMode, topic, sourceUrl, targetDuration, city, contentType, materialStrategy, script, manualKeywords, segmentSettings, plannedShots, selectedAssetIds, r2BaseUrl, avatars, selectedAvatarId, leads, assets])

  useEffect(() => { safeWrite('AI_VIDEO_API_BASE', apiBase) }, [apiBase])

  useEffect(() => {
    if (!jobId || !isGenerating) return
    let alive = true
    async function poll() {
      try {
        const response = await fetch(`${apiBase}/api/video/full-ai/tts-first/job/${jobId}`, { headers: authHeaders() })
        const data = await response.json() as JobPayload
        if (!alive) return
        setJob(data)
        if (isFinal(data) || isFailed(data)) setIsGenerating(false)
      } catch (err) {
        if (!alive) return
        setError(err instanceof Error ? err.message : '轮询任务失败')
      }
    }
    poll()
    const timer = window.setInterval(poll, 3000)
    return () => { alive = false; window.clearInterval(timer) }
  }, [apiBase, jobId, isGenerating])

  function setAutoScript() {
    const next = buildScript(topic, city, targetDuration, contentType, manualKeywords)
    setScript(next)
    setShots(buildShots(next, city, targetDuration, materialStrategy, assets))
    setNotice('已按当前主题、城市、关键词重写文案和镜头计划。')
  }

  function addKeyword() {
    const parts = manualKeywordText.split(/[,，\n]/).map((item) => item.trim()).filter(Boolean)
    if (!parts.length) return
    setManualKeywords((prev) => Array.from(new Set([...prev, ...parts])))
    setManualKeywordText('')
  }

  function updateSegmentSetting(segmentId: string, patch: Partial<SegmentVoiceSetting>) {
    const segment = segments.find((item) => item.id === segmentId)
    if (!segment) return
    const base = segmentSettings[segmentId] || defaultVoice(segment)
    setSegmentSettings((prev) => ({ ...prev, [segmentId]: { ...base, ...patch } }))
  }

  function updateShot(shotId: string, patch: Partial<ShotPlan>) {
    const base = plannedShots.map((shot) => shot.id === shotId ? { ...shot, ...patch } : shot)
    setShots(updateShotIndexes(base))
  }

  function duplicateShot(shotId: string) {
    const target = plannedShots.find((shot) => shot.id === shotId)
    if (!target) return
    const copy = { ...target, id: uid('shot'), title: `${target.title}（复制）` }
    const index = plannedShots.findIndex((shot) => shot.id === shotId)
    const next = [...plannedShots.slice(0, index + 1), copy, ...plannedShots.slice(index + 1)]
    setShots(updateShotIndexes(next))
    setSelectedShotId(copy.id)
  }

  function deleteShot(shotId: string) {
    const next = plannedShots.filter((shot) => shot.id !== shotId)
    setShots(updateShotIndexes(next.length ? next : buildShots(effectiveScript, city, targetDuration, materialStrategy, assets)))
    setSelectedShotId('')
  }

  function importR2Urls() {
    const urls = r2UrlInput.split(/\n+/).map((item) => item.trim()).filter(Boolean)
    if (!urls.length) return
    const next = urls.map((url, index): AssetItem => ({
      id: uid('r2'),
      name: url.split('/').pop() || `R2 素材 ${index + 1}`,
      url: r2BaseUrl && !url.startsWith('http') ? `${r2BaseUrl.replace(/\/+$/, '')}/${url.replace(/^\/+/, '')}` : url,
      source: 'r2',
      city,
      tags: CITY_PROFILES[city].anchors.slice(0, 3),
      kind: /\.(png|jpg|jpeg|webp)$/i.test(url) ? 'image' : 'video',
    }))
    setAssets((prev) => [...next, ...prev])
    setSelectedAssetIds((prev) => Array.from(new Set([...prev, ...next.map((item) => item.id)])))
    setR2UrlInput('')
    setMaterialStrategy('r2_first')
    setNotice('R2 素材已导入，并会优先带入当前视频。')
  }

  function addAvatar(avatar: AvatarItem) {
    setAvatars((prev) => [avatar, ...prev])
    setSelectedAvatarId(avatar.id)
    setNotice('数字人照片已加入，并选为当前出镜人。')
  }

  async function analyzeLeadsWithOpenClaw() {
    setError('')
    const lines = leadInput.split(/\n+/).map((item) => item.trim()).filter(Boolean)
    if (!lines.length) return
    try {
      const response = await fetch(`${apiBase}/api/video/openclaw/comments/analyze`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ comments: lines, source: 'frontend_openclaw_leads_v4', market: 'malaysia_real_estate' }),
      })
      const data = await response.json()
      const payload = Array.isArray(data?.leads) ? data.leads : Array.isArray(data?.results) ? data.results : []
      if (payload.length) {
        const mapped = payload.map((item: any): LeadItem => ({
          id: uid('lead'),
          source: 'OpenClaw 评论截流',
          text: String(item.text || item.comment || item.content || ''),
          intent: String(item.intent || item.intent_level || '待判断'),
          score: Number(item.score || item.lead_score || 60),
          reason: String(item.reason || item.summary || 'OpenClaw 已识别为潜在线索'),
          firstMessage: String(item.reply || item.first_message || '可以的，我先按你的预算和用途帮你筛一下区域。你更偏自住、出租，还是第二家园？'),
          status: 'pending_human',
          createdAt: new Date().toLocaleString(),
        })).filter((item: LeadItem) => item.text)
        setLeads((prev) => [...mapped, ...prev])
        return
      }
    } catch {
      // fallback below
    }
    const fallback = lines.map(scoreLead)
    setLeads((prev) => [...fallback, ...prev])
    setNotice('OpenClaw 接口不可用时已用前端规则兜底分析，线索仍会进入人工待处理。')
  }

  function clearAllLocalData() {
    if (!window.confirm('确认一键清空本地预置数据、草稿、素材、数字人和线索吗？不会删除后端/R2真实文件。')) return
    safeRemove(STATE_KEY)
    safeRemove('AI_VIDEO_API_BASE')
    safeRemove('ai_video_api_base')
    TOKEN_KEYS.forEach(safeRemove)
    setActiveModule('video')
    setStep(1)
    setSourceMode('account')
    setApiBase(defaultApiBase())
    setTopic('马来西亚吉隆坡买房，别只看价格')
    setSourceUrl('')
    setTargetDuration(20)
    setCity('kuala_lumpur')
    setContentType('investment')
    setMaterialStrategy('r2_first')
    setScript('')
    setManualKeywords([])
    setSegmentSettings({})
    setSelectedSegmentId('')
    setShots([])
    setSelectedShotId('')
    setAssets([])
    setSelectedAssetIds([])
    setR2BaseUrl('')
    setR2UrlInput('')
    setAvatars([])
    setSelectedAvatarId('')
    setLeadInput('')
    setLeads([])
    setJobId('')
    setJob(null)
    setError('')
    setNotice('已清空本地数据。')
  }

  async function startGenerate() {
    setStep(4)
    setError('')
    setNotice('')
    setIsGenerating(true)
    setJob(null)
    setJobId('')

    const segmentPayload = segments.map((segment) => ({
      ...segment,
      voice: segmentSettings[segment.id] || defaultVoice(segment),
    }))

    const payload = {
      title: topic,
      topic,
      script_text: effectiveScript,
      target_duration_seconds: targetDuration,
      duration_seconds: targetDuration,
      city,
      content_type: contentType,
      width: 1080,
      height: 1920,
      fps: 30,
      extra: {
        source: 'ai_video_console_v4_workspace',
        source_mode: sourceMode,
        source_url: sourceUrl,
        material_strategy: materialStrategy,
        keyword_insights: insights,
        manual_keywords: manualKeywords,
        script_segments: segmentPayload,
        segment_voice_settings: segmentPayload.reduce<Record<string, SegmentVoiceSetting>>((acc, item) => { acc[item.id] = item.voice; return acc }, {}),
        manual_shot_plan: plannedShots,
        shot_overrides: plannedShots,
        transition_plan: plannedShots.map((shot) => ({ index: shot.index, transition: shot.transition, camera: shot.camera })),
        asset_context: selectedAssets,
        r2_material_context: selectedAssets.filter((asset) => asset.source === 'r2'),
        avatar_config: selectedAvatar ? { enabled: true, ...selectedAvatar } : { enabled: false },
        openclaw_leads: leads.filter((lead) => lead.status === 'pending_human' || lead.status === 'qualified'),
        safety_policy: {
          no_hallucinated_project: true,
          no_exact_price_roi_school_floorplan: true,
          city_visual_lock: city,
          banned_visuals: CITY_PROFILES[city].banned,
        },
      },
    }

    try {
      const response = await fetch(`${apiBase}/api/video/full-ai/tts-first/start`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify(payload),
      })
      const data = await response.json() as JobPayload
      if (!response.ok || data.ok === false) throw new Error(data.error || `生成失败：HTTP ${response.status}`)
      if (!data.job_id) throw new Error('后端没有返回 job_id')
      setJob(data)
      setJobId(data.job_id)
    } catch (err) {
      setError(err instanceof Error ? err.message : '生成失败')
      setIsGenerating(false)
    }
  }

  function nextStep() {
    if (step === 1) {
      if (!script.trim()) setAutoScript()
      setStep(2)
      return
    }
    if (step === 2) { setStep(3); return }
    if (step === 3) { setStep(4); return }
    startGenerate()
  }

  function previousStep() {
    setStep((prev) => Math.max(1, prev - 1) as WizardStep)
  }

  function renderVideoStepOne() {
    const { min, max } = targetChars(targetDuration)
    return (
      <div className="vcw-step-grid step-one">
        <section className="vcw-card vcw-card-main">
          <div className="vcw-section-head"><h2>内容来源</h2><p>先确定主题、对标来源、关键词和目标时长。</p></div>
          <div className="vcw-tabs">
            {(Object.keys(SOURCE_LABELS) as SourceMode[]).map((key) => (
              <button key={key} type="button" className={sourceMode === key ? 'active' : ''} onClick={() => setSourceMode(key)}>{SOURCE_LABELS[key]}</button>
            ))}
          </div>
          <label className="vcw-field"><span>视频主题</span><input value={topic} onChange={(event) => setTopic(event.target.value)} placeholder="例如：吉隆坡 150 万预算，华语环境怎么选" /></label>
          <label className="vcw-field"><span>{sourceMode === 'account' ? '同行主页' : sourceMode === 'viral' ? '爆款链接' : '补充说明'}，可不填</span><input value={sourceUrl} onChange={(event) => setSourceUrl(event.target.value)} placeholder="抖音 / TikTok / Instagram / R2素材 / 其他链接" /></label>
          <div className="vcw-grid-3">
            <label className="vcw-field"><span>预计长度</span><select value={targetDuration} onChange={(event) => setTargetDuration(Number(event.target.value))}><option value={15}>15 秒</option><option value={20}>20 秒</option><option value={30}>30 秒</option><option value={45}>45 秒</option><option value={60}>60 秒</option></select></label>
            <label className="vcw-field"><span>城市锁定</span><select value={city} onChange={(event) => { setCity(event.target.value as CityKey); setShots([]) }}>{(Object.keys(CITY_PROFILES) as CityKey[]).map((key) => <option key={key} value={key}>{CITY_PROFILES[key].label}</option>)}</select></label>
            <label className="vcw-field"><span>内容方向</span><select value={contentType} onChange={(event) => setContentType(event.target.value as ContentType)}>{(Object.keys(CONTENT_LABELS) as ContentType[]).map((key) => <option key={key} value={key}>{CONTENT_LABELS[key]}</option>)}</select></label>
          </div>
          <div className="vcw-keyword-input-row">
            <label className="vcw-field"><span>手动凸显关键词</span><input value={manualKeywordText} onChange={(event) => setManualKeywordText(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') { event.preventDefault(); addKeyword() } }} placeholder="例如：150万, 大平层, 华语, 出租需求" /></label>
            <button type="button" className="vcw-secondary" onClick={addKeyword}>加入关键词</button>
          </div>
          <div className="vcw-chip-row">{manualKeywords.map((word) => <button key={word} type="button" className="vcw-chip removable" onClick={() => setManualKeywords((prev) => prev.filter((item) => item !== word))}>{word} ×</button>)}</div>
          <div className="vcw-action-row"><button className="vcw-primary" onClick={setAutoScript}>大脑生成文案</button><button className="vcw-secondary" onClick={() => { setScript(''); setShots([]) }}>清空文案</button></div>
        </section>
        <section className="vcw-card"><div className="vcw-section-head"><h2>关键词洞察</h2><p>关键词会联动口播、字幕、镜头、R2素材和获客判断。</p></div><div className="vcw-insight-list">{insights.map((item) => <div key={item.id} className={`vcw-insight ${item.priority}`}><b>{item.value}</b><span>{item.category}</span><p>{item.reason}</p></div>)}</div></section>
        <section className="vcw-card"><div className="vcw-section-head"><h2>生成预览</h2><p>建议字数 {min}-{max}，当前 {effectiveScript.length}</p></div><div className="vcw-copy-preview">{highlight(effectiveScript, insights)}</div><div className="vcw-mini-note">{CITY_PROFILES[city].short}画面锚点：{CITY_PROFILES[city].anchors.join(' / ')}</div></section>
      </div>
    )
  }

  function renderVideoStepTwo() {
    return (
      <div className="vcw-step-grid step-two">
        <section className="vcw-card"><div className="vcw-section-head"><h2>口播文案</h2><p>可整体修改，修改后会重新识别关键词和分句。</p></div><textarea className="vcw-script-area" value={effectiveScript} onChange={(event) => { setScript(event.target.value); setShots([]) }} /></section>
        <section className="vcw-card"><div className="vcw-section-head"><h2>逐句配音</h2><p>点某一句，才展示该句的速度、语调、语气、停顿。</p></div><div className="vcw-segment-list">{segments.map((segment) => <button key={segment.id} type="button" className={selectedSegmentId === segment.id ? 'active' : ''} onClick={() => setSelectedSegmentId(segment.id)}><em>{String(segment.index).padStart(2, '0')}</em><span>{highlight(segment.text, insights)}</span></button>)}</div></section>
        <section className="vcw-card detail-card">{selectedSegment ? <SegmentEditor segment={selectedSegment} value={segmentSettings[selectedSegment.id] || defaultVoice(selectedSegment)} onChange={(patch) => updateSegmentSetting(selectedSegment.id, patch)} onSave={() => { safeWrite(`AI_VIDEO_SEGMENT_${selectedSegment.id}`, JSON.stringify(segmentSettings[selectedSegment.id] || defaultVoice(selectedSegment))); setNotice('已保存当前句表达设置。') }} /> : <EmptyState title="未选择句子" desc="点击左侧某一句后，这里才显示该句的语速、语调、语气、停顿和重点词。" />}</section>
      </div>
    )
  }

  function renderVideoStepThree() {
    return (
      <div className="vcw-step-grid step-three">
        <section className="vcw-card"><div className="vcw-section-head"><h2>素材与出镜</h2><p>R2 素材、真实素材和数字人会带入最终 payload。</p></div><label className="vcw-field"><span>素材策略</span><select value={materialStrategy} onChange={(event) => { setMaterialStrategy(event.target.value as MaterialStrategy); setShots([]) }}>{(Object.keys(MATERIAL_LABELS) as MaterialStrategy[]).map((key) => <option key={key} value={key}>{MATERIAL_LABELS[key]}</option>)}</select></label><div className="vcw-chip-panel"><strong>城市锁定：{CITY_PROFILES[city].label}</strong><div className="vcw-chip-row">{CITY_PROFILES[city].anchors.map((anchor) => <span className="vcw-chip" key={anchor}>{anchor}</span>)}</div></div><div className="vcw-mini-list"><h3>已选素材</h3>{selectedAssets.length ? selectedAssets.map((asset) => <p key={asset.id}>{asset.name} · {asset.source}</p>) : <p>还没选素材，可到“素材库”导入 R2 或点击下方进入。</p>}<button className="vcw-secondary" onClick={() => setActiveModule('assets')}>去素材库</button></div><div className="vcw-mini-list"><h3>出镜数字人</h3>{selectedAvatar ? <p>{selectedAvatar.name} · {selectedAvatar.role}</p> : <p>默认不启用数字人，可到“数字人库”选择照片。</p>}<button className="vcw-secondary" onClick={() => setActiveModule('avatars')}>去数字人库</button></div><button className="vcw-primary full" onClick={() => { setShots(buildShots(effectiveScript, city, targetDuration, materialStrategy, assets)); setNotice('镜头计划已按当前文案、素材和城市重新生成。') }}>重新规划镜头</button></section>
        <section className="vcw-card"><div className="vcw-section-head"><h2>镜头列表</h2><p>点击镜头后右侧可改画面、时长、Prompt、转场。</p></div><div className="vcw-shot-list">{plannedShots.map((shot) => <button key={shot.id} type="button" className={selectedShot?.id === shot.id ? 'active' : ''} onClick={() => setSelectedShotId(shot.id)}><em>{String(shot.index).padStart(2, '0')}</em><strong>{shot.title}</strong><span>{shot.duration}s · {shot.source} · {shot.transition}</span></button>)}</div><button className="vcw-secondary full" onClick={() => { const newShot = { ...plannedShots[plannedShots.length - 1], id: uid('shot'), title: '新增镜头', index: plannedShots.length + 1 }; setShots(updateShotIndexes([...plannedShots, newShot])); setSelectedShotId(newShot.id) }}>新增镜头</button></section>
        <section className="vcw-card detail-card">{selectedShot ? <ShotEditor shot={selectedShot} assets={assets} onChange={(patch) => updateShot(selectedShot.id, patch)} onDuplicate={() => duplicateShot(selectedShot.id)} onDelete={() => deleteShot(selectedShot.id)} /> : <EmptyState title="未选择镜头" desc="选择一个镜头后可手动修改画面主体、口播、素材来源、运镜、转场和 Prompt。" />}</section>
      </div>
    )
  }

  function renderVideoStepFour() {
    const pendingLeads = leads.filter((lead) => lead.status === 'pending_human' || lead.status === 'qualified')
    return (
      <div className="vcw-step-grid step-four">
        <section className="vcw-card"><div className="vcw-section-head"><h2>成片预览</h2><p>先配音，再按真实时长生成画面和合成。</p></div>{videoUrl ? <video className="vcw-video" src={videoUrl} controls playsInline /> : <div className="vcw-video-placeholder"><div>🎬</div><strong>{isGenerating ? '正在生成成片' : '点击生成后在这里预览'}</strong><span>最终时长跟随真实配音，画面使用镜头计划和素材上下文。</span></div>}<button className="vcw-primary full" disabled={isGenerating} onClick={startGenerate}>{isGenerating ? '生成中...' : '开始生成成片'}</button>{videoUrl && <a className="vcw-secondary link full" href={videoUrl} target="_blank" rel="noreferrer">打开成片链接</a>}</section>
        <section className="vcw-card"><div className="vcw-section-head"><h2>生成状态</h2><p>联动链路：文案 → 逐句配音 → 镜头 → R2/数字人 → 成片。</p></div><div className="vcw-status-list"><Row label="任务" value={jobId || '-'} /><Row label="阶段" value={job?.stage || job?.status || (isGenerating ? 'running' : 'ready')} /><Row label="配音实际" value={audioDuration ? `${audioDuration.toFixed(1)}s` : '生成后读取'} /><Row label="镜头数量" value={`${Number(job?.shot_count || plannedShots.length)} 个`} /><Row label="素材上下文" value={`${selectedAssets.length} 个`} /><Row label="城市锁定" value={CITY_PROFILES[city].short} /></div><div className="vcw-progress"><i style={{ width: `${Math.min(100, Number(job?.progress || (isGenerating ? 55 : 0)))}%` }} /></div>{error && <div className="vcw-error">{error}</div>}{isFailed(job) && <div className="vcw-error">{job?.error || job?.child_job?.error || '生成失败，请查看后端日志。'}</div>}</section>
        <section className="vcw-card"><div className="vcw-section-head"><h2>发布与获客</h2><p>成片后接 OpenClaw 评论截流，合适线索只收集，等待人工处理。</p></div><div className="vcw-publish-grid"><b>{targetDuration}s</b><span>预计时长</span><b>{plannedShots.length}</b><span>镜头</span><b>{insights.length}</b><span>关键词</span><b>{pendingLeads.length}</b><span>待跟进</span></div><button className="vcw-secondary full" onClick={() => setActiveModule('leads')}>去获客线索处理</button></section>
      </div>
    )
  }

  function renderVideoModule() {
    return <ModulePage title={`第${step}步：${STEP_TITLES[step]}`} desc="内容、关键词、配音、镜头、R2 素材、数字人和 OpenClaw 获客统一联动。"><div className="vcw-stepper">{([1, 2, 3, 4] as WizardStep[]).map((n) => <button key={n} className={step === n ? 'active' : step > n ? 'done' : ''} onClick={() => setStep(n)}>{n}. {STEP_TITLES[n]}</button>)}</div>{step === 1 && renderVideoStepOne()}{step === 2 && renderVideoStepTwo()}{step === 3 && renderVideoStepThree()}{step === 4 && renderVideoStepFour()}<footer className="vcw-footer"><div><span>创作进度</span><strong>{step}/4</strong><i><em style={{ width: `${(step / 4) * 100}%` }} /></i></div><nav><button className="vcw-secondary big" disabled={step === 1 || isGenerating} onClick={previousStep}>上一步</button><button className="vcw-primary big" disabled={isGenerating && step === 4} onClick={nextStep}>{step === 4 ? (isGenerating ? '生成中...' : '生成成片') : '下一步'}</button></nav></footer></ModulePage>
  }

  function renderAssetsModule() {
    return <ModulePage title="素材库" desc="R2 真实素材、同行主页和爆款链接都从这里进入视频创作。"><div className="vcw-module-grid"><section className="vcw-card"><div className="vcw-section-head"><h2>R2 素材导入</h2><p>把 R2 公开 URL 或对象路径粘贴进来，一行一个。导入后可直接绑定到镜头。</p></div><label className="vcw-field"><span>R2 公共前缀，可不填</span><input value={r2BaseUrl} onChange={(event) => setR2BaseUrl(event.target.value)} placeholder="https://xxx.r2.dev/videos/" /></label><label className="vcw-field"><span>R2 文件 URL / 对象路径</span><textarea value={r2UrlInput} onChange={(event) => setR2UrlInput(event.target.value)} placeholder="klcc/shot1.mp4\nhttps://xxx.r2.dev/condo-lobby.mp4" /></label><button className="vcw-primary" onClick={importR2Urls}>导入 R2 素材并带入视频</button><AssetQuickForm city={city} onAdd={(asset) => setAssets((prev) => [asset, ...prev])} /></section><section className="vcw-card"><div className="vcw-section-head"><h2>已保存素材</h2><p>选择素材后，会进入成片 payload 的 asset_context / r2_material_context。</p></div><div className="vcw-asset-list">{assets.map((asset) => <div key={asset.id} className={selectedAssetIds.includes(asset.id) ? 'selected' : ''}><strong>{asset.name}</strong><span>{asset.source} · {CITY_PROFILES[asset.city].short} · {asset.tags.join(' / ') || '未打标签'}</span><small>{asset.url || '无链接'}</small><nav><button onClick={() => setSelectedAssetIds((prev) => prev.includes(asset.id) ? prev.filter((id) => id !== asset.id) : [...prev, asset.id])}>{selectedAssetIds.includes(asset.id) ? '取消带入' : '带入视频'}</button><button onClick={() => setAssets((prev) => prev.filter((item) => item.id !== asset.id))}>删除</button></nav></div>)}</div></section></div></ModulePage>
  }

  function renderAvatarsModule() {
    return <ModulePage title="数字人库" desc="数字人就是几张授权照片/形象卡，选择谁出镜，再和口播配音、镜头策略联动。"><div className="vcw-module-grid"><AvatarForm onAdd={addAvatar} /><section className="vcw-card"><div className="vcw-section-head"><h2>出镜人选择</h2><p>不开启也可以，房产内容默认以素材画面为主。</p></div><div className="vcw-avatar-grid">{avatars.map((avatar) => <div key={avatar.id} className={selectedAvatarId === avatar.id ? 'active' : ''}><div className="vcw-avatar-photo">{avatar.photoUrl ? <img src={avatar.photoUrl} alt={avatar.name} /> : <span>{avatar.name.slice(0, 1)}</span>}</div><strong>{avatar.name}</strong><p>{avatar.role}</p><small>{avatar.tags.join(' / ')}</small><nav><button onClick={() => setSelectedAvatarId(selectedAvatarId === avatar.id ? '' : avatar.id)}>{selectedAvatarId === avatar.id ? '取消出镜' : '用于当前视频'}</button><button onClick={() => setAvatars((prev) => prev.filter((item) => item.id !== avatar.id))}>删除</button></nav></div>)}</div></section></div></ModulePage>
  }

  function renderLeadsModule() {
    return <ModulePage title="获客线索" desc="OpenClaw 截流：从评论/私信里找目标客户，AI 评分，生成初步回复，收集后等待人工处理。"><div className="vcw-module-grid"><section className="vcw-card"><div className="vcw-section-head"><h2>OpenClaw 评论截流</h2><p>粘贴评论或私信，一行一个。系统会判断是否适合跟进，不自动私信。</p></div><label className="vcw-field"><span>评论 / 私信</span><textarea value={leadInput} onChange={(event) => setLeadInput(event.target.value)} placeholder="吉隆坡 150 万预算能买哪里？华人多吗，可以讲华语吗？" /></label><button className="vcw-primary" onClick={analyzeLeadsWithOpenClaw}>OpenClaw 分析线索</button></section><section className="vcw-card"><div className="vcw-section-head"><h2>人工待处理</h2><p>合适线索只进入待处理队列，由人工决定是否回复。</p></div><div className="vcw-lead-list">{leads.map((lead) => <div key={lead.id}><strong>{lead.intent} · {lead.score} 分</strong><p>{lead.text}</p><span>{lead.reason}</span><blockquote>{lead.firstMessage}</blockquote><nav><button onClick={() => { setTopic(lead.text); setActiveModule('video'); setStep(1); setManualKeywords((prev) => Array.from(new Set([...prev, '预算', '华语', '出租需求']))) }}>作为选题</button><button onClick={() => setLeads((prev) => prev.map((item) => item.id === lead.id ? { ...item, status: 'qualified' } : item))}>标记合适</button><button onClick={() => setLeads((prev) => prev.filter((item) => item.id !== lead.id))}>删除</button></nav></div>)}</div></section></div></ModulePage>
  }

  function renderSettingsModule() {
    return <ModulePage title="设置" desc="前台不再展示后台口令。鉴权建议放到 Pages 环境变量、后端会话或本机静默配置。"><div className="vcw-module-grid"><section className="vcw-card"><div className="vcw-section-head"><h2>接口与默认策略</h2><p>这里不再出现后台口令输入框，避免交付给客户时暴露敏感信息。</p></div><label className="vcw-field"><span>后端地址</span><input value={apiBase} onChange={(event) => setApiBase(event.target.value.replace(/\/+$/, ''))} /></label><label className="vcw-field"><span>默认城市</span><select value={city} onChange={(event) => setCity(event.target.value as CityKey)}>{(Object.keys(CITY_PROFILES) as CityKey[]).map((key) => <option key={key} value={key}>{CITY_PROFILES[key].label}</option>)}</select></label><label className="vcw-field"><span>默认素材策略</span><select value={materialStrategy} onChange={(event) => setMaterialStrategy(event.target.value as MaterialStrategy)}>{(Object.keys(MATERIAL_LABELS) as MaterialStrategy[]).map((key) => <option key={key} value={key}>{MATERIAL_LABELS[key]}</option>)}</select></label><button className="vcw-secondary" onClick={() => { safeWrite('AI_VIDEO_API_BASE', apiBase); setNotice('设置已保存。') }}>保存设置</button></section><section className="vcw-card danger-zone"><div className="vcw-section-head"><h2>数据清理</h2><p>用于清理预载样例、草稿、素材、数字人、线索和本地凭据。不会删除 R2 或后端文件。</p></div><button className="vcw-danger" onClick={clearAllLocalData}>一键清空本地数据</button></section></div></ModulePage>
  }

  function renderActiveModule() {
    if (activeModule === 'assets') return renderAssetsModule()
    if (activeModule === 'avatars') return renderAvatarsModule()
    if (activeModule === 'leads') return renderLeadsModule()
    if (activeModule === 'settings') return renderSettingsModule()
    return renderVideoModule()
  }

  return (
    <div className="vcw-console">
      <aside className="vcw-sidebar"><div className="vcw-brand"><strong>AI-VIDEO</strong><span>房产短视频增长中控</span></div><nav className="vcw-side-nav">{(Object.keys(MODULE_LABELS) as ModuleKey[]).map((key) => <button key={key} className={activeModule === key ? 'active' : ''} onClick={() => setActiveModule(key)}>{MODULE_LABELS[key]}</button>)}</nav><div className="vcw-mode-card"><strong>TTS-first 联动</strong><span>文案 → 配音 → 镜头 → R2素材/数字人 → OpenClaw获客</span></div><button className="vcw-clear-small" onClick={clearAllLocalData}>清空本地数据</button></aside>
      <main className="vcw-body">{notice && <div className="vcw-notice"><span>{notice}</span><button onClick={() => setNotice('')}>×</button></div>}{renderActiveModule()}</main>
    </div>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return <div><span>{label}</span><strong>{value}</strong></div>
}

function ModulePage({ title, desc, children }: { title: string; desc: string; children?: any }) {
  return <><header className="vcw-page-header"><div><div className="vcw-eyebrow">AI-VIDEO 中控</div><h1>{title}</h1><p>{desc}</p></div></header>{children}</>
}

function EmptyState({ title, desc }: { title: string; desc: string }) {
  return <div className="vcw-empty"><strong>{title}</strong><p>{desc}</p></div>
}

function SegmentEditor({ segment, value, onChange, onSave }: { segment: ScriptSegment; value: SegmentVoiceSetting; onChange: (patch: Partial<SegmentVoiceSetting>) => void; onSave: () => void }) {
  const toggle = (word: string) => {
    onChange({ emphasis: value.emphasis.includes(word) ? value.emphasis.filter((item) => item !== word) : [...value.emphasis, word] })
  }
  return <div className="vcw-detail-editor"><div className="vcw-section-head"><h2>第 {segment.index} 句表达</h2><p>{segment.text}</p></div><div className="vcw-grid-2"><label className="vcw-field"><span>语气</span><select value={value.tone} onChange={(event) => onChange({ tone: event.target.value })}><option>专业可信</option><option>重点强调</option><option>谨慎专业</option><option>亲和可信</option><option>成交引导</option></select></label><label className="vcw-field"><span>情绪</span><select value={value.emotion} onChange={(event) => onChange({ emotion: event.target.value })}><option>自然平稳</option><option>谨慎提醒</option><option>亲和解释</option><option>专业判断</option><option>轻快种草</option></select></label></div><Slider label="语速" value={value.speed} min={0.75} max={1.25} step={0.05} onChange={(speed) => onChange({ speed })} /><Slider label="语调" value={value.pitch} min={0.8} max={1.2} step={0.05} onChange={(pitch) => onChange({ pitch })} /><Slider label="音量" value={value.volume} min={0.6} max={1.3} step={0.05} onChange={(volume) => onChange({ volume })} /><div className="vcw-grid-2"><label className="vcw-field"><span>句前停顿</span><input type="number" value={value.pauseBefore} min={0} max={2} step={0.1} onChange={(event) => onChange({ pauseBefore: Number(event.target.value) })} /></label><label className="vcw-field"><span>句后停顿</span><input type="number" value={value.pauseAfter} min={0} max={2} step={0.1} onChange={(event) => onChange({ pauseAfter: Number(event.target.value) })} /></label></div><div className="vcw-keyword-group"><span>重点词</span><div>{segment.keywords.length ? segment.keywords.map((item) => <button key={item.id} className={value.emphasis.includes(item.value) ? 'active' : ''} onClick={() => toggle(item.value)}>{item.value}</button>) : <em>这一句暂无重点词，可在第一步手动添加。</em>}</div></div><label className="vcw-field"><span>备注</span><textarea value={value.note} onChange={(event) => onChange({ note: event.target.value })} placeholder="例如：150万、大平层、华语这些词要放慢强调" /></label><button className="vcw-secondary" onClick={onSave}>保存当前句设置</button></div>
}

function Slider({ label, value, min, max, step, onChange }: { label: string; value: number; min: number; max: number; step: number; onChange: (value: number) => void }) {
  return <label className="vcw-slider"><span>{label} {value.toFixed(2)}</span><input type="range" value={value} min={min} max={max} step={step} onChange={(event) => onChange(Number(event.target.value))} /></label>
}

function ShotEditor({ shot, assets, onChange, onDuplicate, onDelete }: { shot: ShotPlan; assets: AssetItem[]; onChange: (patch: Partial<ShotPlan>) => void; onDuplicate: () => void; onDelete: () => void }) {
  const toggleAsset = (assetId: string) => {
    onChange({ assetIds: shot.assetIds.includes(assetId) ? shot.assetIds.filter((id) => id !== assetId) : [...shot.assetIds, assetId] })
  }
  return <div className="vcw-detail-editor"><div className="vcw-section-head"><h2>镜头 {shot.index} 编辑</h2><p>手动控制画面主体、口播、时长、素材、运镜、转场和 Prompt。</p></div><label className="vcw-field"><span>镜头标题</span><input value={shot.title} onChange={(event) => onChange({ title: event.target.value })} /></label><label className="vcw-field"><span>画面主体</span><input value={shot.scene} onChange={(event) => onChange({ scene: event.target.value })} /></label><label className="vcw-field"><span>对应口播</span><textarea value={shot.narration} onChange={(event) => onChange({ narration: event.target.value })} /></label><div className="vcw-grid-2"><label className="vcw-field"><span>时长</span><input type="number" value={shot.duration} min={1} max={12} step={0.1} onChange={(event) => onChange({ duration: Number(event.target.value) })} /></label><label className="vcw-field"><span>素材来源</span><select value={shot.source} onChange={(event) => onChange({ source: event.target.value as MaterialSource })}><option value="r2">R2素材</option><option value="real">真实素材</option><option value="ai">AI生成</option><option value="mixed">混合</option></select></label></div><div className="vcw-grid-2"><label className="vcw-field"><span>运镜</span><input value={shot.camera} onChange={(event) => onChange({ camera: event.target.value })} /></label><label className="vcw-field"><span>转场</span><input value={shot.transition} onChange={(event) => onChange({ transition: event.target.value })} /></label></div><div className="vcw-keyword-group"><span>绑定素材</span><div>{assets.length ? assets.slice(0, 12).map((asset) => <button key={asset.id} className={shot.assetIds.includes(asset.id) ? 'active' : ''} onClick={() => toggleAsset(asset.id)}>{asset.name}</button>) : <em>素材库暂无素材。</em>}</div></div><label className="vcw-field"><span>AI Prompt</span><textarea value={shot.prompt} onChange={(event) => onChange({ prompt: event.target.value })} /></label><div className="vcw-negative-box"><span>禁用画面</span>{shot.avoid.map((item) => <b key={item}>{item}</b>)}</div><div className="vcw-action-row"><button className="vcw-secondary" onClick={onDuplicate}>复制镜头</button><button className="vcw-danger" onClick={onDelete}>删除镜头</button></div></div>
}

function AssetQuickForm({ city, onAdd }: { city: CityKey; onAdd: (asset: AssetItem) => void }) {
  const [name, setName] = useState('')
  const [url, setUrl] = useState('')
  const [tags, setTags] = useState('')
  return <div className="vcw-inline-form"><h3>手动加素材/账号</h3><label className="vcw-field"><span>名称</span><input value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：KLCC公寓阳台实拍" /></label><label className="vcw-field"><span>链接</span><input value={url} onChange={(event) => setUrl(event.target.value)} placeholder="R2 / 主页 / 爆款链接" /></label><label className="vcw-field"><span>标签</span><input value={tags} onChange={(event) => setTags(event.target.value)} placeholder="KLCC,华语,投资" /></label><button className="vcw-secondary" onClick={() => { if (!name.trim()) return; onAdd({ id: uid('asset'), name, url, source: 'manual', city, tags: tags.split(/[,，]/).map((item) => item.trim()).filter(Boolean), kind: url.match(/\.(mp4|mov|webm)$/i) ? 'video' : 'link' }); setName(''); setUrl(''); setTags('') }}>保存素材</button></div>
}

function AvatarForm({ onAdd }: { onAdd: (avatar: AvatarItem) => void }) {
  const [name, setName] = useState('')
  const [role, setRole] = useState('海外置业讲解 · 专业可信')
  const [photoUrl, setPhotoUrl] = useState('')
  const [tags, setTags] = useState('华语,专业')
  return <section className="vcw-card"><div className="vcw-section-head"><h2>新增数字人照片</h2><p>这里放几张授权照片或形象图，用于选择谁出镜。</p></div><label className="vcw-field"><span>名称</span><input value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：Linda 房产顾问" /></label><label className="vcw-field"><span>角色说明</span><input value={role} onChange={(event) => setRole(event.target.value)} /></label><label className="vcw-field"><span>照片 URL / R2 图片链接</span><input value={photoUrl} onChange={(event) => setPhotoUrl(event.target.value)} placeholder="https://.../avatar.jpg" /></label><label className="vcw-field"><span>标签</span><input value={tags} onChange={(event) => setTags(event.target.value)} /></label><button className="vcw-primary" onClick={() => { if (!name.trim()) return; onAdd({ id: uid('avatar'), name, role, photoUrl, tags: tags.split(/[,，]/).map((item) => item.trim()).filter(Boolean), enabled: true }); setName(''); setPhotoUrl('') }}>保存并用于当前视频</button></section>
}
