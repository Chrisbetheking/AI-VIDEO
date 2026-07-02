import React, { useEffect, useMemo, useState } from 'react'
import {
  apiGet,
  apiPost,
  ProjectDraft,
  WorkspaceTab,
} from './aiVideoApi'

type WizardStep = 1 | 2 | 3 | 4
type SourceMode = 'account' | 'viral' | 'custom'
type MaterialSource = 'r2' | 'real' | 'ai' | 'mixed'
type ContentType = 'investment' | 'own_stay' | 'second_home' | 'rental' | 'education'

type KeywordInsight = {
  id: string
  category: string
  value: string
  reason: string
  priority: 'high' | 'medium' | 'low'
}

type ScriptSegment = {
  id: string
  index: number
  text: string
  keywords: KeywordInsight[]
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


type ContentBrainCard = {
  id?: string
  title?: string
  type?: string
  source?: string
  content?: string
  tags?: string[]
  score?: number
  status?: string
  usedCount?: number
}

const CONTENT_BRAIN_KEY = 'ai_video_content_brain_cards_v9'

function loadApprovedContentBrainCards(): ContentBrainCard[] {
  try {
    const raw = window.localStorage.getItem(CONTENT_BRAIN_KEY)
    const parsed = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? parsed.filter((card) => card && card.status === 'approved') : []
  } catch {
    return []
  }
}

function contentBrainMatch(card: ContentBrainCard, topic: string, city: string, market: string) {
  const text = `${card.title || ''} ${card.content || ''} ${(card.tags || []).join(' ')}`.toLowerCase()
  const keys = [topic, city, market, '马来西亚', '吉隆坡', '房产']
    .map((x) => String(x || '').toLowerCase())
    .filter(Boolean)
  return keys.some((key) => key.length >= 2 && text.includes(key))
}

function contentBrainKeywords(cards: ContentBrainCard[]) {
  return Array.from(new Set(cards.flatMap((card) => Array.isArray(card.tags) ? card.tags : []).filter(Boolean))).slice(0, 18)
}

type Props = {
  project: ProjectDraft
  setProject: (project: ProjectDraft) => void
  goTab: (tab: WorkspaceTab) => void
}

const STEP_TITLES: Record<WizardStep, string> = {
  1: '确定内容和关键词',
  2: '逐句口播配音',
  3: '编辑镜头和素材',
  4: '生成成片和承接线索',
}

const STEP_DESC: Record<WizardStep, string> = {
  1: '主题、同行来源、目标时长、城市和关键词先确定。',
  2: '保留逐句调语速、语调、语气、音量和停顿；不点句子不展开。',
  3: '每个镜头都能手改，绑定 R2 素材和数字人配置。',
  4: '调用原有 TTS-first 后端，成片后继续接 OpenClaw 人工待处理。',
}

const SOURCE_LABELS: Record<SourceMode, string> = {
  account: '抖音主页',
  viral: '爆款链接',
  custom: '自定义主题',
}

const CONTENT_LABELS: Record<ContentType, string> = {
  investment: '投资配置',
  own_stay: '自住',
  second_home: '第二家园',
  rental: '出租收益',
  education: '教育规划',
}

const CITY_OPTIONS = [
  { key: 'kuala_lumpur', label: '吉隆坡 / Kuala Lumpur', anchors: ['KLCC', 'TRX', 'Mont Kiara', '公寓阳台', '大堂', '泳池'] },
  { key: 'penang', label: '槟城 / Penang', anchors: ['Gurney Drive', '海景公寓', '养老生活', '滨海天际线'] },
  { key: 'johor', label: '新山 / Johor Bahru', anchors: ['新山城市', 'Medini', '家庭自住', '通勤生活'] },
  { key: 'langkawi', label: '兰卡威 / Langkawi', anchors: ['度假住宅', '岛屿生活', '泳池', '第二家园'] },
  { key: 'sabah', label: '沙巴 / Sabah', anchors: ['亚庇', '滨海住宅', '日落景观', '第二家园'] },
]

const DEFAULT_TOPIC = '马来西亚吉隆坡买房，别只看价格'
const DEFAULT_MARKET = '马来西亚'

function asArray<T = any>(value: any): T[] {
  return Array.isArray(value) ? value.filter(Boolean) : []
}

function uid(prefix: string, index: number) {
  return `${prefix}_${index}_${Math.random().toString(16).slice(2, 8)}`
}

function inferCity(text: string): string {
  const raw = String(text || '').toLowerCase()
  if (raw.includes('槟城') || raw.includes('penang')) return 'penang'
  if (raw.includes('新山') || raw.includes('johor')) return 'johor'
  if (raw.includes('兰卡威') || raw.includes('langkawi')) return 'langkawi'
  if (raw.includes('沙巴') || raw.includes('sabah') || raw.includes('亚庇')) return 'sabah'
  return 'kuala_lumpur'
}

function cityLabel(city: string) {
  return CITY_OPTIONS.find((x) => x.key === city)?.label || CITY_OPTIONS[0].label
}

function cityAnchors(city: string) {
  return CITY_OPTIONS.find((x) => x.key === city)?.anchors || CITY_OPTIONS[0].anchors
}

function targetChars(duration: number) {
  return {
    min: Math.max(45, Math.floor(Number(duration || 20) * 4.3)),
    max: Math.max(60, Math.floor(Number(duration || 20) * 5.3)),
  }
}

function normalizeScriptLength(script: string, duration: number, city: string) {
  const { min, max } = targetChars(duration)
  let next = script.trim()
  while (next.length < min) {
    if (city === 'kuala_lumpur') {
      next += ' 吉隆坡要重点看区域成熟度、出租需求、生活半径和未来转手流动性。'
    } else {
      next += ' 不同城市适合不同用途，先判断预算、生活方式和长期持有逻辑。'
    }
  }
  if (next.length > max) next = next.slice(0, max).replace(/[，,、\s]+$/g, '') + '。'
  return next
}

function generateScript(topic: string, city: string, duration: number, contentType: ContentType, keywords: KeywordInsight[]) {
  const baseTopic = topic.trim() || DEFAULT_TOPIC
  const keywordText = keywords.map((item) => item.value).filter(Boolean).slice(0, 8).join('、')
  let script = ''

  if (city === 'kuala_lumpur') {
    script = `${baseTopic}。很多人买马来西亚房产，第一眼只看价格，但在吉隆坡，真正要先看区域、用途和流动性。KLCC、TRX、Mont Kiara 这些位置，看的不是热闹，而是生活半径、出租需求和未来转手。`
    if (contentType === 'investment') script += '如果是投资配置，先看租客是谁、通勤是否方便、周边配套是否成熟，再看价格是否合理。'
    else if (contentType === 'own_stay') script += '如果是自住，重点不是短期涨跌，而是生活便利、社区品质和长期居住舒适度。'
    else if (contentType === 'education') script += '如果考虑家庭和教育，要把通勤、社区、安全感和长期居住需求放在前面。'
    else script += '自住、出租、第二家园，判断标准完全不一样，先把需求筛清楚，再去看房才不会被带节奏。'
  } else {
    script = `${baseTopic}。马来西亚买房不要只看价格，要先看城市、用途和生活方式。${cityLabel(city)}适合的人群不同，投资、自住、第二家园和养老的判断标准也不一样。`
  }

  if (keywordText) script += ` 这条视频要特别强调：${keywordText}。`
  return normalizeScriptLength(script, duration, city)
}

function splitScript(script: string): ScriptSegment[] {
  const parts = String(script || '')
    .split(/[。！？!?；;\n]+/)
    .map((item) => item.trim())
    .filter(Boolean)

  return parts.map((text, index) => ({
    id: `seg_${index + 1}`,
    index: index + 1,
    text,
    keywords: [],
  }))
}

function extractKeywords(text: string, manual = ''): KeywordInsight[] {
  const raw = `${text}\n${manual}`
  const items: KeywordInsight[] = []
  const seen = new Set<string>()

  function add(category: string, value: string, reason: string, priority: KeywordInsight['priority'] = 'medium') {
    const clean = value.trim()
    if (!clean || seen.has(`${category}:${clean}`)) return
    seen.add(`${category}:${clean}`)
    items.push({ id: `${category}_${items.length + 1}`, category, value: clean, reason, priority })
  }

  ;(manual || '')
    .split(/[，,、\s]+/)
    .map((x) => x.trim())
    .filter(Boolean)
    .forEach((x) => add('手动关键词', x, '用户指定必须凸显', 'high'))

  const money = raw.match(/\d+(?:\.\d+)?\s*(?:万|百万|千万|亿|rm|RM|马币)/g) || []
  money.forEach((x) => add('预算/价格', x, '预算信息是评论截流和口播重音重点', 'high'))

  const rules: Array<[string, RegExp, string, KeywordInsight['priority']]> = [
    ['区域', /(吉隆坡|KLCC|TRX|Mont\s*Kiara|Mont Kiara|槟城|Penang|新山|Johor|兰卡威|Langkawi|沙巴|Sabah)/gi, '区域决定画面锚点和客户判断', 'high'],
    ['人群', /(华人|华语|家庭|孩子|留学|陪读|退休|养老|新加坡|外派|租客)/gi, '人群决定语气和初步回复话术', 'high'],
    ['用途', /(自住|投资|出租|第二家园|养老|度假|资产配置|教育|转手)/gi, '用途决定内容结构和镜头重点', 'high'],
    ['卖点', /(大平层|公寓|condo|大堂|泳池|阳台|学区|商圈|地铁|交通|生活半径|配套)/gi, '卖点用于镜头和关键词高亮', 'medium'],
    ['风险判断', /(预算|流动性|回报|ROI|转手|空置|管理费|税费|避坑|亏|坑)/gi, '风险词适合做钩子和获客筛选', 'medium'],
  ]

  rules.forEach(([category, regex, reason, priority]) => {
    const matches = raw.match(regex) || []
    matches.forEach((x) => add(category, x, reason, priority))
  })

  if (items.length === 0) {
    add('默认核心', '区域', '用于判断城市和素材方向', 'high')
    add('默认核心', '预算', '用于筛选客户意向', 'medium')
    add('默认核心', '用途', '用于区分自住、出租和投资', 'medium')
  }

  return items.slice(0, 18)
}

function attachSegmentKeywords(segments: ScriptSegment[], keywords: KeywordInsight[]) {
  return segments.map((segment) => ({
    ...segment,
    keywords: keywords.filter((kw) => segment.text.toLowerCase().includes(kw.value.toLowerCase())).slice(0, 6),
  }))
}

function defaultVoiceSetting(segment: ScriptSegment): SegmentVoiceSetting {
  const hasHigh = segment.keywords.some((kw) => kw.priority === 'high')
  return {
    speed: hasHigh ? 0.95 : 1,
    pitch: 1,
    volume: hasHigh ? 1.05 : 1,
    emotion: hasHigh ? '重点强调' : '自然平稳',
    tone: hasHigh ? '专业可信' : '清晰讲解',
    pauseBefore: hasHigh ? 120 : 0,
    pauseAfter: 180,
    emphasis: segment.keywords.map((kw) => kw.value),
    note: hasHigh ? '这一句包含核心判断，语速稍慢，关键词加重。' : '',
  }
}

function cityScenes(city: string) {
  if (city === 'penang') return ['Gurney Drive 滨海住宅天际线', '槟城海景公寓阳台', '现代公寓室内面向海景', '养老第二家园生活方式']
  if (city === 'johor') return ['新山城市住宅区位', 'Medini 现代公寓社区', '家庭自住公寓室内', '城市通勤和生活配套']
  if (city === 'langkawi') return ['兰卡威度假型住宅和泳池', '热带绿植第二家园', '岛屿度假住宅生活方式', '度假社区公共空间']
  if (city === 'sabah') return ['亚庇城市滨海住宅', '沙巴日落住宅生活方式', '滨海公寓阳台', '度假社区配套镜头']
  return ['KLCC 双子塔天际线 + 高层公寓', 'TRX 金融区 + 高端住宅区位', 'Mont Kiara 高端公寓社区', '公寓阳台看吉隆坡城市天际线', '现代公寓客厅 + 落地窗城市景观', '高端公寓大堂 / 泳池 / 健身房']
}

function buildPrompt(city: string, scene: string, narration: string) {
  const klRule = city === 'kuala_lumpur'
    ? 'Kuala Lumpur only: KLCC Twin Towers, TRX, Mont Kiara, luxury condo balcony, apartment interior, lobby, pool, city skyline. Do not show beach, island, seaside, Langkawi, Sabah, Penang seaside.'
    : 'Use city-matched Malaysia real estate visuals. Avoid fake project names, exact prices, exact ROI and unreadable text.'

  return `Premium 9:16 cinematic vertical video for Malaysia real-estate content.\nMain scene: ${scene}.\nNarration meaning: ${narration.slice(0, 80)}.\n${klRule}\nUltra realistic, premium real estate commercial style, natural lighting, clean composition, high detail, smooth camera movement. No readable text, no logo, no watermark, no fake project name, no exact price, no black borders.`
}

function generateShotPlan(segments: ScriptSegment[], duration: number, city: string, project: ProjectDraft): ShotPlan[] {
  const count = Math.max(4, Math.ceil(Number(duration || 20) / 4.5))
  const scenes = cityScenes(city)
  const each = Math.round((Number(duration || 20) / count) * 10) / 10
  const assetIds = asArray(project.selectedMaterialIds)

  return Array.from({ length: count }, (_, index) => {
    const segment = segments[index % Math.max(segments.length, 1)]
    const scene = scenes[index % scenes.length]
    return {
      id: `shot_${index + 1}`,
      index: index + 1,
      title: scene,
      scene,
      narration: segment?.text || '',
      duration: each,
      source: assetIds.length ? 'mixed' : 'ai',
      camera: index % 2 === 0 ? '慢推进' : '横移展示',
      transition: index === 0 ? '开场建立' : '自然衔接',
      prompt: buildPrompt(city, scene, segment?.text || ''),
      avoid: city === 'kuala_lumpur'
        ? ['海边', '沙滩', '海岛', '文件桌面', '计算器', '乱码文字', '假价格']
        : ['文件桌面', '计算器', '乱码文字', '假价格', '假项目名'],
      assetIds,
    }
  })
}

function highlightText(text: string, keywords: KeywordInsight[]) {
  let nodes: React.ReactNode[] = [text]
  keywords.slice(0, 8).forEach((kw) => {
    const next: React.ReactNode[] = []
    nodes.forEach((node) => {
      if (typeof node !== 'string') {
        next.push(node)
        return
      }
      const idx = node.toLowerCase().indexOf(kw.value.toLowerCase())
      if (idx < 0) {
        next.push(node)
        return
      }
      next.push(node.slice(0, idx))
      next.push(<mark key={`${kw.id}_${idx}`}>{node.slice(idx, idx + kw.value.length)}</mark>)
      next.push(node.slice(idx + kw.value.length))
    })
    nodes = next
  })
  return nodes
}

function extractVideoUrl(job: JobPayload | null): string {
  if (!job) return ''
  const direct =
    job.video_url || job.output_url || job.result_url || job.url ||
    job.result?.video_url || job.result?.output_url || job.result?.result_url ||
    job.child_job?.video_url || job.child_job?.output_url || job.child_job?.result_url || job.child_job?.url ||
    job.child_job?.result?.video_url || job.child_job?.result?.output_url || job.child_job?.result?.result_url
  return typeof direct === 'string' ? direct : ''
}

function finalStatus(job: JobPayload | null) {
  const text = `${job?.status || ''} ${job?.stage || ''} ${job?.child_job?.status || ''} ${job?.child_job?.stage || ''}`.toLowerCase()
  return ['completed', 'succeeded', 'success', 'done', 'finished', 'failed', 'error'].some((x) => text.includes(x))
}

export default function VideoCreationWizard({ project, setProject, goTab }: Props) {
  const [step, setStep] = useState<WizardStep>(1)
  const [sourceMode, setSourceMode] = useState<SourceMode>('custom')
  const [topic, setTopic] = useState(project.topic || DEFAULT_TOPIC)
  const [market, setMarket] = useState(project.market || DEFAULT_MARKET)
  const [city, setCity] = useState(String(project.city || inferCity(`${project.topic} ${project.script}`)))
  const [contentType, setContentType] = useState<ContentType>(String(project.contentType || 'investment') as ContentType)
  const [targetDuration, setTargetDuration] = useState(Number(project.targetDuration || 20))
  const [competitorSource, setCompetitorSource] = useState(String(project.competitorSource || ''))
  const [manualKeywords, setManualKeywords] = useState(String(project.manualKeywords || ''))
  const [script, setScript] = useState(String(project.script || ''))
  const [selectedSegmentId, setSelectedSegmentId] = useState('seg_1')
  const [voiceSettings, setVoiceSettings] = useState<Record<string, SegmentVoiceSetting>>({})
  const [shotPlan, setShotPlan] = useState<ShotPlan[]>([])
  const [selectedShotId, setSelectedShotId] = useState('shot_1')
  const [jobId, setJobId] = useState('')
  const [job, setJob] = useState<JobPayload | null>(null)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [sourceBusy, setSourceBusy] = useState('')
  const [sourceError, setSourceError] = useState('')
  const [sourceResult, setSourceResult] = useState<any>(null)

  const approvedBrainCards = useMemo(() => loadApprovedContentBrainCards().filter((card) => contentBrainMatch(card, topic, city, market)).slice(0, 12), [topic, city, market])
  const brainKeywordText = useMemo(() => contentBrainKeywords(approvedBrainCards).join('，'), [approvedBrainCards])
  const keywords = useMemo(
    () => extractKeywords(
      `${topic}\n${script}\n${competitorSource}\n${approvedBrainCards.map((card) => `${card.title || ''} ${card.content || ''} ${(card.tags || []).join(' ')}`).join('\n')}`,
      [manualKeywords, brainKeywordText].filter(Boolean).join('，')
    ),
    [topic, script, competitorSource, manualKeywords, brainKeywordText, approvedBrainCards]
  )
  const segments = useMemo(() => attachSegmentKeywords(splitScript(script || generateScript(topic, city, targetDuration, contentType, keywords)), keywords), [script, topic, city, targetDuration, contentType, keywords])
  const selectedSegment = segments.find((segment) => segment.id === selectedSegmentId) || segments[0]
  const selectedSetting = selectedSegment ? (voiceSettings[selectedSegment.id] || defaultVoiceSetting(selectedSegment)) : null
  const selectedShot = shotPlan.find((shot) => shot.id === selectedShotId) || shotPlan[0]
  const videoUrl = extractVideoUrl(job)
  const selectedAssets = asArray(project.asset_context || project.selected_assets || project.r2_material_context)
  const avatarConfig = project.avatar_config || null
  const leadCount = asArray(project.leads).length

  useEffect(() => {
    if (!script) {
      const generated = generateScript(topic, city, targetDuration, contentType, keywords)
      setScript(generated)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!segments.length) return
    setVoiceSettings((current) => {
      const next = { ...current }
      segments.forEach((segment) => {
        if (!next[segment.id]) next[segment.id] = defaultVoiceSetting(segment)
      })
      return next
    })
    if (!segments.find((segment) => segment.id === selectedSegmentId)) setSelectedSegmentId(segments[0].id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [segments.length, script])

  useEffect(() => {
    if (!shotPlan.length && segments.length) {
      const plan = generateShotPlan(segments, targetDuration, city, project)
      setShotPlan(plan)
      setSelectedShotId(plan[0]?.id || 'shot_1')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [segments.length])

  useEffect(() => {
    if (!jobId || !busy) return
    let alive = true
    const timer = window.setInterval(async () => {
      try {
        const data = await apiGet(`/api/video/full-ai/tts-first/job/${jobId}`, 120000)
        if (!alive) return
        setJob(data)
        if (finalStatus(data)) setBusy('')
      } catch (err: any) {
        if (!alive) return
        setError(err?.message || String(err))
      }
    }, 3000)
    return () => {
      alive = false
      window.clearInterval(timer)
    }
  }, [jobId, busy])


  function applySourceMode(nextMode: SourceMode) {
    setSourceMode(nextMode)
    setSourceError('')
    setSourceResult(null)
    if (nextMode === 'account' && !competitorSource.trim()) {
      setCompetitorSource(project.competitorSource || '')
    }
    if (nextMode === 'viral' && !competitorSource.trim()) {
      setCompetitorSource(project.viralLink || project.competitorSource || '')
    }
  }

  function sourceHelpText() {
    if (sourceMode === 'account') return '输入真实抖音主页、账号名或种子账号。系统会下发采集任务，拿到评论/视频结果后再带入文案和 OpenClaw。'
    if (sourceMode === 'viral') return '输入真实爆款视频链接。系统优先拉取该视频评论和内容信息，用于选题、文案和截流。'
    return '不调用采集，直接按你输入的主题、城市、关键词生成文案。'
  }

  async function runSourceAction() {
    setSourceError('')
    setSourceResult(null)

    if (sourceMode === 'custom') {
      rebuildScript()
      return
    }

    if (!competitorSource.trim()) {
      setSourceError(sourceMode === 'account' ? '请先填写真实抖音主页、账号名或种子账号。' : '请先填写真实爆款视频链接。')
      return
    }

    setSourceBusy(sourceMode === 'account' ? 'account_collect' : 'viral_collect')
    const sourcePayload = {
      source: 'video_creation_wizard_source_step',
      platform: 'douyin',
      mission_type: sourceMode === 'account' ? 'competitor' : 'comments',
      market,
      keyword: competitorSource,
      keywords: [competitorSource, topic, market].filter(Boolean),
      seed_accounts: sourceMode === 'account' ? competitorSource.split(/[，,\n]/).map((x) => x.trim()).filter(Boolean) : [],
      video_urls: sourceMode === 'viral' ? competitorSource.split(/[，,\n]/).map((x) => x.trim()).filter(Boolean) : [],
      max_accounts: sourceMode === 'account' ? 20 : 5,
      max_videos_per_account: sourceMode === 'account' ? 12 : 3,
      max_comments_per_video: 80,
      run_openclaw_analysis: true,
      auto_timeline: true,
      payload: {
        source_mode: sourceMode,
        target: sourceMode === 'account' ? 'account_videos_comments' : 'viral_video_comments',
        competitor_source: competitorSource,
        topic,
        market,
        run_openclaw_analysis: true,
      },
    }

    try {
      let data: any
      try {
        data = await apiPost('/api/collector/commands', { type: sourceMode === 'account' ? 'douyin_account_collect' : 'openclaw_collect_comments', ...sourcePayload }, 120000)
      } catch {
        try {
          data = await apiPost('/api/collector/commands/create', sourcePayload, 120000)
        } catch {
          data = await apiPost('/api/collector/douyin/accounts/bulk-upsert', {
            accounts: (sourcePayload.seed_accounts.length ? sourcePayload.seed_accounts : sourcePayload.keywords).map((name: string) => ({
              category: sourceMode === 'account' ? 'competitor' : 'viral_video',
              account_name: name,
              url: sourceMode === 'viral' ? competitorSource : '',
              niche: topic || market,
              source: 'video_creation_wizard_source_step',
            })),
          }, 120000)
        }
      }

      setSourceResult(data)
      const sourceNote = sourceMode === 'account'
        ? `基于同行主页/账号「${competitorSource}」采集后生成：${topic}`
        : `基于爆款链接「${competitorSource}」评论和内容生成：${topic}`
      setProject({
        ...project,
        market,
        topic,
        city,
        sourceMode,
        competitorSource,
        collector_source_result: data,
        contentInsights: [...asArray(project.contentInsights), { source_mode: sourceMode, source: competitorSource, result: data, note: sourceNote }],
      })
      rebuildScript()
    } catch (err: any) {
      setSourceError(err?.message || String(err))
    } finally {
      setSourceBusy('')
    }
  }

  function syncProject(extra: Record<string, any> = {}) {
    const next: ProjectDraft = {
      ...project,
      market,
      topic,
      title: topic,
      city,
      contentType,
      targetDuration,
      script,
      manualKeywords,
      competitorSource,
      sourceMode,
      keyword_insights: keywords,
      content_brain_context: approvedBrainCards,
      script_segments: segments,
      segment_voice_settings: voiceSettings,
      manual_shot_plan: shotPlan,
      shot_overrides: shotPlan,
      transition_plan: shotPlan.map((shot) => ({ index: shot.index, transition: shot.transition, camera: shot.camera })),
      ...extra,
    }
    setProject(next)
    return next
  }

  function rebuildScript() {
    const nextScript = generateScript(topic, city, targetDuration, contentType, keywords)
    setScript(nextScript)
    const nextSegments = attachSegmentKeywords(splitScript(nextScript), extractKeywords(`${topic}\n${nextScript}\n${competitorSource}`, manualKeywords))
    const nextShots = generateShotPlan(nextSegments, targetDuration, city, project)
    setShotPlan(nextShots)
    setSelectedSegmentId(nextSegments[0]?.id || 'seg_1')
    setSelectedShotId(nextShots[0]?.id || 'shot_1')
    syncProject({ script: nextScript, segments: nextSegments, manual_shot_plan: nextShots })
  }

  function updateSetting(patch: Partial<SegmentVoiceSetting>) {
    if (!selectedSegment) return
    const base = voiceSettings[selectedSegment.id] || defaultVoiceSetting(selectedSegment)
    const next = { ...voiceSettings, [selectedSegment.id]: { ...base, ...patch } }
    setVoiceSettings(next)
    setProject({ ...project, segment_voice_settings: next })
  }

  function updateShot(id: string, patch: Partial<ShotPlan>) {
    const next = shotPlan.map((shot) => {
      if (shot.id !== id) return shot
      const merged = { ...shot, ...patch }
      if (patch.scene || patch.narration) merged.prompt = buildPrompt(city, merged.scene, merged.narration)
      return merged
    })
    setShotPlan(next)
    setProject({ ...project, manual_shot_plan: next, shot_overrides: next })
  }

  async function startGenerate() {
    setError('')
    setBusy('启动生成')
    setStep(4)
    const finalProject = syncProject()
    const finalShots = shotPlan.length ? shotPlan : generateShotPlan(segments, targetDuration, city, finalProject)

    const payload = {
      title: topic,
      topic,
      market,
      city,
      content_type: contentType,
      script_text: script,
      target_duration_seconds: targetDuration,
      duration_seconds: targetDuration,
      width: 1080,
      height: 1920,
      fps: 30,
      shots: finalShots.map((shot) => ({
        index: shot.index,
        prompt: shot.prompt,
        visual_prompt: shot.prompt,
        narration_segment: shot.narration,
        duration_seconds: shot.duration,
        source: shot.source,
        asset_ids: shot.assetIds,
      })),
      max_shots: finalShots.length,
      fal_fill_shots: finalShots.length,
      script_segments: segments,
      segment_voice_settings: voiceSettings,
      keyword_insights: keywords,
      content_brain_context: approvedBrainCards,
      manual_shot_plan: finalShots,
      shot_overrides: finalShots,
      transition_plan: finalShots.map((shot) => ({ index: shot.index, camera: shot.camera, transition: shot.transition })),
      asset_context: finalProject.asset_context || selectedAssets,
      selected_assets: finalProject.selected_assets || selectedAssets,
      r2_material_context: finalProject.r2_material_context || selectedAssets,
      avatar_config: finalProject.avatar_config || avatarConfig,
      openclaw_lead_context: finalProject.leads || [],
      extra: {
        source: 'original_backend_step_wizard_v6',
        source_mode: sourceMode,
        competitor_source: competitorSource,
        content_type: contentType,
        selected_assets: selectedAssets,
        avatar_config: avatarConfig,
        lead_count: leadCount,
        content_brain_count: approvedBrainCards.length,
      },
    }

    try {
      const data = await apiPost('/api/video/full-ai/tts-first/start', payload, 240000)
      if (!data?.job_id) throw new Error('后端没有返回 job_id')
      setJob(data)
      setJobId(data.job_id)
      setBusy('生成中')
    } catch (err: any) {
      setBusy('')
      setError(err?.message || String(err))
    }
  }

  function nextStep() {
    if (step === 1) {
      syncProject()
      setStep(2)
    } else if (step === 2) {
      syncProject()
      if (!shotPlan.length) setShotPlan(generateShotPlan(segments, targetDuration, city, project))
      setStep(3)
    } else if (step === 3) {
      syncProject()
      setStep(4)
    } else {
      startGenerate()
    }
  }

  function renderStepOne() {
    return (
      <div className="aiw-stepGrid two">
        <section className="aiw-stepCard">
          <h3>第一步：搞定内容</h3>
          <p>先选真实来源：抖音主页会下发账号采集，爆款链接会下发评论采集，自定义主题不调用采集。</p>
          <div className="aiw-stepTabs aiw-realSourceTabs">
            {(Object.keys(SOURCE_LABELS) as SourceMode[]).map((key) => (
              <button key={key} className={sourceMode === key ? 'active' : ''} onClick={() => applySourceMode(key)} type="button">
                <b>{SOURCE_LABELS[key]}</b>
                <span>{key === 'account' ? '真实账号/主页采集' : key === 'viral' ? '真实视频评论采集' : '直接写主题'}</span>
              </button>
            ))}
          </div>

          <div className={`aiw-sourceModePanel aiw-sourceModePanel-${sourceMode}`}>
            <b>{SOURCE_LABELS[sourceMode]}模式</b>
            <p>{sourceHelpText()}</p>
            {sourceMode === 'account' && (
              <div className="aiw-modeRealBox">
                <h4>录入真实账号，OpenClaw 才能找到人</h4>
                <p>一行一个抖音主页、账号名、达人备注。系统会把这些账号写进采集任务，后面线索卡片会显示账号名/主页/来源。</p>
                <label>真实抖音主页 / 账号名 / 种子账号
                  <textarea value={competitorSource} onChange={(e) => setCompetitorSource(e.target.value)} placeholder={'例如：@吉隆坡房产顾问\nhttps://www.douyin.com/user/...\n马来西亚买房同行主页'} />
                </label>
                <div className="aiw-sourceChecklist"><span>① 下发账号采集</span><span>② 拉视频和评论</span><span>③ OpenClaw 评分</span><span>④ 带回文案/线索</span></div>
              </div>
            )}
            {sourceMode === 'viral' && (
              <div className="aiw-modeRealBox">
                <h4>录入真实爆款视频链接，优先拉评论截流</h4>
                <p>适合看到同行某条视频评论区很热，直接抓这条视频下的评论来找预算、区域、华语、出租等意向客户。</p>
                <label>真实爆款视频链接 / 评论来源
                  <textarea value={competitorSource} onChange={(e) => setCompetitorSource(e.target.value)} placeholder={'例如：https://www.douyin.com/video/...\nhttps://www.tiktok.com/@.../video/...'} />
                </label>
                <div className="aiw-sourceChecklist"><span>① 下发评论采集</span><span>② 提取高意向问题</span><span>③ 生成首条回复</span><span>④ 反推视频选题</span></div>
              </div>
            )}
            {sourceMode === 'custom' && (
              <div className="aiw-modeRealBox">
                <h4>不采集，直接按主题生成</h4>
                <p>适合你已经确定选题，只需要文案、逐句配音、镜头计划和成片。不会调用 OpenClaw 采集。</p>
                <div className="aiw-sourceChecklist"><span>① 写主题</span><span>② 生成文案</span><span>③ 逐句配音</span><span>④ 生成视频</span></div>
              </div>
            )}
          </div>

          <div className="aiw-form two">
            <label>市场<input value={market} onChange={(e) => setMarket(e.target.value)} /></label>
            <label>城市<select value={city} onChange={(e) => setCity(e.target.value)}>{CITY_OPTIONS.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}</select></label>
            <label>主题/选题<input value={topic} onChange={(e) => setTopic(e.target.value)} placeholder={sourceMode === 'custom' ? '直接输入要生成的视频主题' : '采集结果会结合这个主题生成文案'} /></label>
            <label>目标时长<select value={targetDuration} onChange={(e) => setTargetDuration(Number(e.target.value))}><option value={15}>15 秒</option><option value={20}>20 秒</option><option value={30}>30 秒</option><option value={45}>45 秒</option><option value={60}>60 秒</option></select></label>
            <label>内容方向<select value={contentType} onChange={(e) => setContentType(e.target.value as ContentType)}>{Object.entries(CONTENT_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
            <label>来源状态<input readOnly value={sourceResult ? '已下发/已返回采集任务' : sourceMode === 'custom' ? '不采集，直接生成' : '等待下发真实采集'} /></label>
          </div>
          <label className="aiw-wideField">手动凸显关键词<textarea value={manualKeywords} onChange={(e) => setManualKeywords(e.target.value)} placeholder="例如：150万、华语、华人多、大平层、出租、流动性" /></label>
          <div className="aiw-chipRow">
            {cityAnchors(city).map((item) => <span className="aiw-keywordPill" key={item}>{item}</span>)}
          </div>
          <div className="aiw-actions">
            <button className="aiw-primary" onClick={runSourceAction} disabled={!!sourceBusy}>{sourceBusy ? '处理中...' : sourceMode === 'custom' ? '按当前设置生成文案' : '下发真实采集并生成文案'}</button>
            <button className="aiw-muted" onClick={() => goTab('collect')}>去同行采集</button>
            <button className="aiw-muted" onClick={() => goTab('leads')}>去真实获客线索</button>
          </div>
          {sourceError && <div className="aiw-error">{sourceError}</div>}
          {sourceResult && <details className="aiw-json"><summary>真实采集/入库返回</summary><pre>{JSON.stringify(sourceResult, null, 2)}</pre></details>}
        </section>
        <aside className="aiw-stepCard aiw-resultPanel">
          <h3>关键词洞察</h3>
          <p>这些词会传给配音、镜头计划和 OpenClaw 承接。</p>
          <div className="aiw-keywordGrid">
            {keywords.map((kw) => <div key={kw.id} className={`aiw-keywordCard ${kw.priority}`}><b>{kw.value}</b><span>{kw.category}</span><em>{kw.reason}</em></div>)}
          </div>
          <h4>内容大脑联动</h4>
          <div className="aiw-brainMiniPanel">
            <b>已匹配 {approvedBrainCards.length} 条知识</b>
            <p>会一起传给文案、关键词、镜头和 OpenClaw 承接；不是所有生成内容都自动入库，需在内容大脑里审核。</p>
            <div className="aiw-chipRow">{approvedBrainCards.slice(0, 8).map((card) => <span className="aiw-keywordPill" key={card.id || card.title}>{card.title || card.type}</span>)}</div>
            <div className="aiw-actions">
              <button className="aiw-muted" onClick={() => goTab('brain')}>去内容大脑</button>
              <button className="aiw-muted" onClick={() => setManualKeywords([manualKeywords, brainKeywordText].filter(Boolean).join('，'))}>把知识库关键词带入</button>
            </div>
          </div>
          <h4>文案预览</h4>
          <div className="aiw-scriptPreview">{highlightText(script, keywords)}</div>
        </aside>
      </div>
    )
  }

  function renderStepTwo() {
    const { min, max } = targetChars(targetDuration)
    return (
      <div className="aiw-stepGrid three">
        <section className="aiw-stepCard">
          <h3>第二步：口播文案</h3>
          <p>建议 {min}-{max} 字，当前 {script.length} 字。可以手动改文案。</p>
          <textarea className="aiw-scriptTextarea" value={script} onChange={(e) => setScript(e.target.value)} />
        </section>
        <section className="aiw-stepCard">
          <h3>逐句配音</h3>
          <p>点某一句，右侧才显示该句的速度、语调、语气和停顿。</p>
          <div className="aiw-segmentPicker">
            {segments.map((segment) => (
              <button key={segment.id} className={selectedSegment?.id === segment.id ? 'active' : ''} onClick={() => setSelectedSegmentId(segment.id)}>
                <span>{String(segment.index).padStart(2, '0')}</span>
                <b>{highlightText(segment.text, segment.keywords)}</b>
              </button>
            ))}
          </div>
        </section>
        <aside className="aiw-stepCard">
          <h3>{selectedSegment ? `第 ${selectedSegment.index} 句表达` : '选择一句'}</h3>
          {!selectedSegment || !selectedSetting ? <div className="aiw-info">点击中间某一句后，才显示该句设置。</div> : (
            <div className="aiw-form one">
              <label>语气<select value={selectedSetting.tone} onChange={(e) => updateSetting({ tone: e.target.value })}><option>专业可信</option><option>自然平稳</option><option>轻快种草</option><option>成交引导</option><option>风险提醒</option></select></label>
              <label>情绪<select value={selectedSetting.emotion} onChange={(e) => updateSetting({ emotion: e.target.value })}><option>重点强调</option><option>自然平稳</option><option>解释说明</option><option>提醒避坑</option><option>温和引导</option></select></label>
              <label>语速 {selectedSetting.speed.toFixed(2)}<input type="range" min="0.75" max="1.25" step="0.05" value={selectedSetting.speed} onChange={(e) => updateSetting({ speed: Number(e.target.value) })} /></label>
              <label>语调 {selectedSetting.pitch.toFixed(2)}<input type="range" min="0.75" max="1.25" step="0.05" value={selectedSetting.pitch} onChange={(e) => updateSetting({ pitch: Number(e.target.value) })} /></label>
              <label>音量 {selectedSetting.volume.toFixed(2)}<input type="range" min="0.7" max="1.3" step="0.05" value={selectedSetting.volume} onChange={(e) => updateSetting({ volume: Number(e.target.value) })} /></label>
              <label>句前停顿 ms<input type="number" value={selectedSetting.pauseBefore} onChange={(e) => updateSetting({ pauseBefore: Number(e.target.value) })} /></label>
              <label>句后停顿 ms<input type="number" value={selectedSetting.pauseAfter} onChange={(e) => updateSetting({ pauseAfter: Number(e.target.value) })} /></label>
              <label>备注<textarea value={selectedSetting.note} onChange={(e) => updateSetting({ note: e.target.value })} /></label>
              <div className="aiw-actions vertical">
                <button className="aiw-muted" type="button" onClick={() => {
                  const next: Record<string, SegmentVoiceSetting> = {}
                  segments.forEach((segment) => { next[segment.id] = { ...selectedSetting } })
                  setVoiceSettings(next)
                  setProject({ ...project, segment_voice_settings: next })
                }}>应用到全部句子</button>
                <button className="aiw-muted" type="button" onClick={() => window.localStorage.setItem('ai_video_voice_template_professional_v9', JSON.stringify(selectedSetting))}>保存为专业讲房模板</button>
                <button className="aiw-muted" type="button" onClick={() => updateSetting(defaultVoiceSetting(selectedSegment))}>重置本句</button>
              </div>
            </div>
          )}
        </aside>
      </div>
    )
  }

  function renderStepThree() {
    return (
      <div className="aiw-stepGrid three">
        <section className="aiw-stepCard">
          <h3>镜头计划</h3>
          <p>每个镜头都能自己上手改。已选 R2 素材：{selectedAssets.length} 个；数字人：{avatarConfig?.enabled ? '已启用' : '未启用'}。</p>
          <div className="aiw-actions">
            <button className="aiw-muted" onClick={() => goTab('assets')}>去素材库选择 R2/真实素材</button>
            <button className="aiw-muted" onClick={() => goTab('digital')}>去数字人库选谁出镜</button>
            <button className="aiw-primary" onClick={() => setShotPlan(generateShotPlan(segments, targetDuration, city, project))}>按文案重建镜头</button>
          </div>
          <div className="aiw-shotPicker">
            {shotPlan.map((shot) => (
              <button key={shot.id} className={selectedShot?.id === shot.id ? 'active' : ''} onClick={() => setSelectedShotId(shot.id)}>
                <span>{String(shot.index).padStart(2, '0')}</span>
                <b>{shot.title}</b>
                <em>{shot.duration}s · {shot.source}</em>
              </button>
            ))}
          </div>
        </section>
        <section className="aiw-stepCard aiw-shotEditor">
          <h3>{selectedShot ? `第 ${selectedShot.index} 镜头` : '选择镜头'}</h3>
          {!selectedShot ? <div className="aiw-info">请选择一个镜头。</div> : (
            <div className="aiw-form one">
              <label>镜头标题<input value={selectedShot.title} onChange={(e) => updateShot(selectedShot.id, { title: e.target.value })} /></label>
              <label>画面主体<textarea value={selectedShot.scene} onChange={(e) => updateShot(selectedShot.id, { scene: e.target.value, title: e.target.value })} /></label>
              <label>对应口播<textarea value={selectedShot.narration} onChange={(e) => updateShot(selectedShot.id, { narration: e.target.value })} /></label>
              <label>时长秒<input type="number" value={selectedShot.duration} onChange={(e) => updateShot(selectedShot.id, { duration: Number(e.target.value) })} /></label>
              <label>素材来源<select value={selectedShot.source} onChange={(e) => updateShot(selectedShot.id, { source: e.target.value as MaterialSource })}><option value="r2">R2 素材</option><option value="real">真实素材</option><option value="ai">AI 补足</option><option value="mixed">混合</option></select></label>
              <label>运镜<input value={selectedShot.camera} onChange={(e) => updateShot(selectedShot.id, { camera: e.target.value })} /></label>
              <label>转场<input value={selectedShot.transition} onChange={(e) => updateShot(selectedShot.id, { transition: e.target.value })} /></label>
            </div>
          )}
        </section>
        <aside className="aiw-stepCard">
          <h3>Prompt / 禁用画面</h3>
          {selectedShot && <>
            <textarea className="aiw-promptBox" value={selectedShot.prompt} onChange={(e) => updateShot(selectedShot.id, { prompt: e.target.value })} />
            <div className="aiw-chipRow">{selectedShot.avoid.map((item) => <span className="aiw-badPill" key={item}>{item}</span>)}</div>
          </>}
          <h4>当前素材上下文</h4>
          <div className="aiw-miniList">{selectedAssets.slice(0, 6).map((asset: any, index) => <div key={asset.id || asset.url || index}>{asset.name || asset.original_name || asset.filename || asset.url}</div>)}</div>
        </aside>
      </div>
    )
  }

  function renderStepFour() {
    return (
      <div className="aiw-stepGrid three">
        <section className="aiw-stepCard">
          <h3>成片预览</h3>
          {videoUrl ? <video className="aiw-previewVideo" src={videoUrl} controls /> : <div className="aiw-videoPlaceholder"><b>🎬</b><span>点击生成后在这里预览</span></div>}
          <div className="aiw-actions"><button className="aiw-danger" onClick={startGenerate} disabled={!!busy}>{busy || '生成完整 AI 视频'}</button>{videoUrl && <a className="aiw-linkButton" href={videoUrl} target="_blank" rel="noreferrer">打开成片</a>}</div>
          {error && <div className="aiw-error">{error}</div>}
        </section>
        <section className="aiw-stepCard">
          <h3>生成状态</h3>
          <div className="aiw-statusRows"><div><span>任务</span><b>{jobId || '-'}</b></div><div><span>阶段</span><b>{job?.stage || job?.status || 'ready'}</b></div><div><span>配音实际</span><b>{job?.audio_duration_seconds ? `${Number(job.audio_duration_seconds).toFixed(1)}s` : '生成后读取'}</b></div><div><span>镜头数</span><b>{job?.shot_count || shotPlan.length}</b></div><div><span>R2 素材</span><b>{selectedAssets.length}</b></div><div><span>OpenClaw 线索</span><b>{leadCount}</b></div></div>
          <div className="aiw-miniProgress"><span style={{ width: `${Math.min(100, Number(job?.progress || (busy ? 65 : 0)))}%` }} /></div>
        </section>
        <aside className="aiw-stepCard">
          <h3>发布 / 获客承接</h3>
          <p>成片后不要自动私信。OpenClaw 负责评论区找目标客户、AI 评分、生成第一条初步消息，收集到人工待处理。</p>
          <div className="aiw-actions vertical"><button className="aiw-muted" onClick={() => goTab('leads')}>去 OpenClaw 人工处理</button><button className="aiw-muted" onClick={() => goTab('collect')}>继续采集同行</button><button className="aiw-muted" onClick={() => goTab('assets')}>补充 R2 素材</button></div>
        </aside>
      </div>
    )
  }

  return (
    <section className="aiw-card aiw-native-panel aiw-stepWizard">
      <div className="aiw-hero aiw-stepHero">
        <div>
          <p className="aiw-eyebrow">STEP BY STEP / ORIGINAL BACKEND LINKED</p>
          <h2>四步视频创作向导</h2>
          <p>不是旧的一页铺满，也不是假页面；这条链路接原来的 TTS-first、R2 素材、数字人素材和 OpenClaw。</p>
        </div>
        <span className="aiw-badge ok">第 {step} 步 / 共 4 步</span>
      </div>

      <div className="aiw-stepNav">
        {([1, 2, 3, 4] as WizardStep[]).map((item) => (
          <button key={item} className={step === item ? 'active' : step > item ? 'done' : ''} onClick={() => setStep(item)}>
            <b>{item}</b><span>{STEP_TITLES[item]}</span><em>{STEP_DESC[item]}</em>
          </button>
        ))}
      </div>

      <div className="aiw-stepBody">
        {step === 1 && renderStepOne()}
        {step === 2 && renderStepTwo()}
        {step === 3 && renderStepThree()}
        {step === 4 && renderStepFour()}
      </div>

      <footer className="aiw-stepFooter">
        <div><span>创作进度</span><b>{step}/4</b><i><strong style={{ width: `${(step / 4) * 100}%` }} /></i></div>
        <div className="aiw-actions">
          <button className="aiw-muted" disabled={step === 1 || !!busy} onClick={() => setStep((Math.max(1, step - 1) as WizardStep))}>上一步</button>
          <button className="aiw-primary" disabled={!!busy && step === 4} onClick={nextStep}>{step === 4 ? (busy || '生成成片') : '下一步'}</button>
        </div>
      </footer>
    </section>
  )
}
