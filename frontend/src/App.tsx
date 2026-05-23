import { useEffect, useMemo, useState, type ReactNode } from 'react'
import './styles.css'
import {
  AdAnalysisResponse,
  AssetItem,
  ComposeResponse,
  CoverResponse,
  EditPlanResponse,
  GeneratedCopy,
  InspirationExtractResponse,
  PlatformPublishResponse,
  TrendRadarResponse,
  CompetitorAccount,
  ShootingPlanResponse,
  SubtitleEmphasisResponse,
  GrowthDecisionResponse,
  GrowthMetricInput,
  LeadAcquisitionPlanResponse,
  MemoryContextResponse,
  CollectorCookieStatus,
  DigitalHumanCreateResponse,
  AutoCollectorStatusResponse,
  AutoCollectorRunResponse,
  TTSResponse,
  TTSVoice,
  VideoEditChatResponse,
  VoiceDirectorResponse,
  VoiceSegment,
  apiGet,
  apiPost,
  getCollectorStatus,
  uploadCollectorCookies,
  uploadAssets
} from './api'

type ModuleKey = 'dashboard' | 'monitor' | 'lead' | 'collector' | 'copy' | 'voice' | 'digitalHuman' | 'assets' | 'video' | 'subtitleCover' | 'publish' | 'strategy' | 'competitor' | 'trend' | 'shooting' | 'growth'

function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return <label className="field"><span>{label}</span>{children}{hint && <em>{hint}</em>}</label>
}

function Button({ busy, label, onClick, kind = 'primary', disabled = false }: { busy?: string; label: string; onClick: () => void; kind?: 'primary' | 'ghost' | 'danger' | 'soft'; disabled?: boolean }) {
  return <button className={`btn ${kind}`} disabled={disabled || Boolean(busy)} onClick={onClick}>{busy || label}</button>
}

function Pill({ children, tone = 'blue' }: { children: ReactNode; tone?: 'blue' | 'green' | 'orange' | 'purple' | 'red' }) {
  return <span className={`pill ${tone}`}>{children}</span>
}

function Empty({ children }: { children: ReactNode }) { return <div className="empty">{children}</div> }

const emptyCopy: GeneratedCopy = { title: '', hook: '', script: '', description: '', tags: [], shots: [], kb_refs: [] }

const defaultSegment: VoiceSegment = {
  text: '这里输入新增口播分段。',
  emotion: '自然可信',
  speed_ratio: 1,
  volume_ratio: 1,
  pitch_ratio: 1,
  pause_after_ms: 450
}

const modules: { key: ModuleKey; icon: string; title: string; desc: string; tag: string }[] = [
  { key: 'dashboard', icon: '总', title: '流程总览', desc: '一条视频从采集到发布的主流程', tag: '总览' },
  { key: 'monitor', icon: '控', title: '运营中控台', desc: '总览进度、数据库、插件和待办', tag: '监控' },
  { key: 'lead', icon: '获', title: '获客自动化', desc: '截留、联动、监听、回复、私域承接', tag: '获客' },
  { key: 'collector', icon: '采', title: '1. 同行采集', desc: '采集同行视频、口令和钩子结构', tag: '采集' },
  { key: 'copy', icon: '文', title: '2. 文案生产', desc: '仿写改写、细改、入知识库', tag: '文案' },
  { key: 'voice', icon: '声', title: '3. 配音导演', desc: '克隆音色、分段情绪、语速停顿', tag: '配音' },
  { key: 'digitalHuman', icon: '人', title: '数字人', desc: '上传本人形象，生成老板口播片段', tag: '数字人' },
  { key: 'assets', icon: '素', title: '4. 素材选择', desc: '自有素材和采集视频分开管理', tag: '素材' },
  { key: 'video', icon: '剪', title: '5. 剪辑合成', desc: '分段衔接、转场、贴片、字幕', tag: '剪辑' },
  { key: 'subtitleCover', icon: '字', title: '6. 字幕封面', desc: '重点词高亮、封面样式、下载', tag: '视觉' },
  { key: 'publish', icon: '发', title: '7. 平台发布', desc: '发布草稿、平台适配、开放接口预留', tag: '发布' },
  { key: 'strategy', icon: '客', title: '客户定位', desc: '行业、目标客户、成交路径、老板人设', tag: '定位' },
  { key: 'competitor', icon: '竞', title: '竞品账号库', desc: '长期沉淀同行账号和爆款特征', tag: '账号' },
  { key: 'trend', icon: '雷', title: '行业爆点', desc: '选题雷达、热点关键词、拍摄方向', tag: '雷达' },
  { key: 'shooting', icon: '拍', title: '运营拍摄', desc: '拍摄任务单、提词器、B-roll 清单', tag: '拍摄' },
  { key: 'growth', icon: '投', title: '增长投流细节', desc: '流量数据、机器学习投流、优化动作', tag: '增长' }
]

const workflowSteps: { key: ModuleKey; step: string; title: string; desc: string; action: string }[] = [
  { key: 'collector', step: '01', title: '采集同行视频', desc: '上传参考视频，或粘贴抖音分享口令；先学习钩子、结构、话题和人群。', action: '去采集' },
  { key: 'copy', step: '02', title: '仿写改写', desc: '基于同行结构做原创改写，保留打法，不照抄原文。', action: '去仿写' },
  { key: 'copy', step: '03', title: '文案细改', desc: '细调黄金三秒、标题、口播稿、违禁词和发布简介。', action: '改文案' },
  { key: 'voice', step: '04', title: '配音分段', desc: '选择叔叔音色，分段控制情绪、语速、停顿和语气。', action: '去配音' },
  { key: 'digitalHuman', step: '04B', title: '数字人片段', desc: '可选：上传授权照片/视频，用配音生成老板数字人口播素材。', action: '做数字人' },
  { key: 'assets', step: '05', title: '选择视频素材', desc: '选择老板、办公室、产品、案例素材；采集视频只作为学习参考。', action: '选素材' },
  { key: 'video', step: '06', title: '剪辑与合成', desc: '每段匹配素材，设置叠化/虚化/快切/贴片/字幕，生成 MP4。', action: '去剪辑' },
  { key: 'publish', step: '07', title: '平台发布', desc: '生成平台发布草稿，后续接抖音、视频号、快手、小红书开放平台。', action: '去发布' }
]

const badWords = ['最', '第一', '保证', '包赚', '稳赚', '绝对', '唯一', '国家级', '100%', '躺赚', '无风险']

const pluginMatrix = [
  { name: '采集插件', desc: '抖音口令、短链、MP4、页面元信息尽力采集', status: 'collector' },
  { name: '自动学习智能体', desc: '后台读取竞品账号，学习钩子公式和视频打法，不照抄文案', status: 'agent' },
  { name: '文案智能体', desc: '读取行业档案、同行库、爆点雷达和知识库', status: 'deepseek' },
  { name: '声音导演', desc: '克隆音色、分段情绪、语速停顿、自动合并', status: 'tts' },
  { name: '剪辑插件', desc: 'FFmpeg 合成、转场、字幕、AI 指令重剪', status: 'ffmpeg' },
  { name: '数字人引擎', desc: '预览模式 + 外部 GPU/API 口型同步预留', status: 'digital-human' },
  { name: '记忆数据库', desc: 'Supabase 保存账号、采集、文案、投流复盘', status: 'supabase' },
  { name: '平台发布', desc: '抖音/视频号/快手/小红书开放平台预留', status: 'publish' }
]

function nextStepOf(active: ModuleKey): ModuleKey {
  const order: ModuleKey[] = ['collector','copy','voice','digitalHuman','assets','video','subtitleCover','publish']
  const idx = order.indexOf(active)
  return idx >= 0 && idx < order.length - 1 ? order[idx + 1] : active
}

function shortText(value: string, limit = 68) {
  const clean = (value || '').replace(/\s+/g, ' ').trim()
  return clean.length > limit ? clean.slice(0, limit) + '...' : clean
}

function estimateSeconds(text: string, speed = 1) {
  const chars = (text || '').replace(/\s/g, '').length
  return Math.max(1.5, Math.round((chars / 4.2 / Math.max(0.6, speed)) * 10) / 10)
}

function formatBytes(size: number) {
  if (!size) return '0B'
  if (size < 1024 * 1024) return `${Math.round(size / 1024)}KB`
  return `${(size / 1024 / 1024).toFixed(1)}MB`
}

export default function App() {
  const [active, setActive] = useState<ModuleKey>('dashboard')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [health, setHealth] = useState<any>(null)

  const [industry, setIndustry] = useState('海外房产置业 · 第二家园')
  const [audience, setAudience] = useState('有海外置业、第二家园、子女教育、养老度假和资产配置需求的华人家庭与企业主')
  const [sellingPoints, setSellingPoints] = useState('海外第二家园规划、国家/城市筛选、项目匹配、置业流程、生活配套、长期服务和顾问式咨询')
  const [style, setStyle] = useState('专业可信、顾问式成交、真实案例、短视频强钩子')
  const [duration, setDuration] = useState(35)
  const [leadRegion, setLeadRegion] = useState('华人高净值家庭、企业主、留学家庭、养老度假人群、海外生活规划人群')
  const [conversionGoal, setConversionGoal] = useState('私信咨询 / 需求筛选 / 加微信进入私域 / 预约顾问沟通')
  const [trendKeywords, setTrendKeywords] = useState('海外房产,第二家园,海外置业,子女教育,养老度假,资产配置,海外生活')
  const [trendRadar, setTrendRadar] = useState<TrendRadarResponse | null>(null)
  const [competitors, setCompetitors] = useState<CompetitorAccount[]>([])
  const [competitorDraft, setCompetitorDraft] = useState<CompetitorAccount>({ name: '', platform: 'douyin', url: '', positioning: '', notes: '' })
  const [shootingPlan, setShootingPlan] = useState<ShootingPlanResponse | null>(null)
  const [subtitleAI, setSubtitleAI] = useState<SubtitleEmphasisResponse | null>(null)
  const [growthMetrics, setGrowthMetrics] = useState<GrowthMetricInput>({ views: 0, likes: 0, comments: 0, shares: 0, follows: 0, leads: 0, completion_rate: 0, spend: 0, hours_after_publish: 3 })
  const [growthDecision, setGrowthDecision] = useState<GrowthDecisionResponse | null>(null)
  const [memoryContext, setMemoryContext] = useState<MemoryContextResponse | null>(null)
  const [memoryStatus, setMemoryStatus] = useState('未同步')

  const [assets, setAssets] = useState<AssetItem[]>([])
  const [selectedMaterialIds, setSelectedMaterialIds] = useState<string[]>([])
  const [selectedReferenceAssetId, setSelectedReferenceAssetId] = useState('')
  const [sourceUrl, setSourceUrl] = useState('')
  const [manualText, setManualText] = useState('')
  const [extract, setExtract] = useState<InspirationExtractResponse | null>(null)
  const [collectorStatus, setCollectorStatus] = useState<CollectorCookieStatus | null>(null)
  const [collectorCookieText, setCollectorCookieText] = useState('')
  const [showCookiePanel, setShowCookiePanel] = useState(false)
  const [agentStatus, setAgentStatus] = useState<AutoCollectorStatusResponse | null>(null)
  const [agentResult, setAgentResult] = useState<AutoCollectorRunResponse | null>(null)
  const [agentSeedLinks, setAgentSeedLinks] = useState('')
  const [agentLearnGoal, setAgentLearnGoal] = useState('学习这个博主的视频办法：钩子公式、情绪推进、镜头节奏、转化逻辑。只迁移方法，不模仿具体文案、不搬运素材。')

  const [copy, setCopy] = useState<GeneratedCopy>(emptyCopy)
  const [refineInstruction, setRefineInstruction] = useState('把开头改得更有压迫感，语气更像老板提醒客户；减少书面词，保留短视频口语感。')
  const [editPlan, setEditPlan] = useState<EditPlanResponse | null>(null)

  const [voices, setVoices] = useState<TTSVoice[]>([])
  const [voice, setVoice] = useState('')
  const [voiceStyle, setVoiceStyle] = useState('老板压迫感')
  const [voiceIntensity, setVoiceIntensity] = useState('标准')
  const [voiceSegments, setVoiceSegments] = useState<VoiceSegment[]>([])
  const [voiceNotes, setVoiceNotes] = useState<string[]>([])
  const [audio, setAudio] = useState<TTSResponse | null>(null)

  const [digitalHumanEngine, setDigitalHumanEngine] = useState('auto')
  const [digitalHumanJimengModel, setDigitalHumanJimengModel] = useState('omnihuman15')
  const [digitalHumanAvatarId, setDigitalHumanAvatarId] = useState('')
  const [digitalHumanDriverId, setDigitalHumanDriverId] = useState('')
  const [digitalHumanConsent, setDigitalHumanConsent] = useState(false)
  const [digitalHuman, setDigitalHuman] = useState<DigitalHumanCreateResponse | null>(null)

  const [segmentSeconds, setSegmentSeconds] = useState<Record<number, number>>({})
  const [segmentTransitions, setSegmentTransitions] = useState<Record<number, string>>({})
  const [subtitleSize, setSubtitleSize] = useState(58)
  const [subtitleColor, setSubtitleColor] = useState('#ffffff')
  const [subtitleHighlight, setSubtitleHighlight] = useState('第二家园,海外置业,子女教育,养老度假,资产配置,私信咨询')
  const [coverStyle, setCoverStyle] = useState('海外第二家园强钩子封面')

  const [video, setVideo] = useState<ComposeResponse | null>(null)
  const [cover, setCover] = useState<CoverResponse | null>(null)
  const [editInstruction, setEditInstruction] = useState('把开头节奏加快，保留重点字幕；转场更自然，并重新导出 9:16。')
  const [editChat, setEditChat] = useState<VideoEditChatResponse[]>([])
  const [ad, setAd] = useState<AdAnalysisResponse | null>(null)
  const [platform, setPlatform] = useState('douyin')
  const [publish, setPublish] = useState<PlatformPublishResponse | null>(null)
  const [lastHandoff, setLastHandoff] = useState('系统会把上一模块结果自动带到下一模块。')
  const [autoAdvance, setAutoAdvance] = useState(true)
  const [knowledgeDialog, setKnowledgeDialog] = useState({ open: false, source: '', title: '', content: '', tags: '老板口播,获客,短视频' })

  const [leadPlan, setLeadPlan] = useState<LeadAcquisitionPlanResponse | null>(null)
  const [leadChannels, setLeadChannels] = useState<string[]>(['抖音截留获客', '博主联动流量', '采集目标客户', '自动监听', '自动回复', '目标用户导流私域'])
  const [leadFixedOptions, setLeadFixedOptions] = useState('子女教育家庭、企业主资产配置、养老度假、海外第二居所、华人家庭、目标国家/城市、预算区间')

  const materialAssets = useMemo(() => assets.filter(a => !a.filename.startsWith('collected_')), [assets])
  const collectedVideos = useMemo(() => assets.filter(a => a.kind === 'video' && a.filename.startsWith('collected_')), [assets])
  const referenceText = useMemo(() => extract?.transcript || manualText || sourceUrl, [extract, manualText, sourceUrl])
  const competitorNotes = useMemo(() => competitors.map(c => `${c.platform}｜${c.name}｜${c.positioning}｜${c.notes}`).join('\n'), [competitors])
  const learningSummary = memoryContext?.learning_summary || '保存客户定位、竞品账号和采集结果后，AI 会在文案、雷达、投流建议里自动读取。'
  const currentScript = copy.script || ''
  const currentVideoName = video?.video_name || extract?.collected_video_name || ''
  const selectedVoiceName = voices.find(v => v.id === voice)?.name || voice || '未选择音色'
  const matchedBadWords = useMemo(() => badWords.filter(w => `${copy.title}${copy.hook}${copy.script}${copy.description}`.includes(w)), [copy])
  const leadScore = useMemo(() => {
    let score = 35
    if (extract?.hooks?.length) score += 15
    if (copy.hook) score += 15
    if (voiceSegments.length) score += 10
    if (selectedMaterialIds.length) score += 10
    if (video?.video_url) score += 15
    return Math.min(100, score)
  }, [extract, copy.hook, voiceSegments.length, selectedMaterialIds.length, video])

  const pipelineTodos = useMemo(() => [
    { ok: Boolean(industry && audience), text: '保存客户定位，让 AI 记住行业和客户画像', go: 'strategy' as ModuleKey },
    { ok: Boolean(leadPlan), text: '生成获客自动化作战图，明确截留、监听和私域承接', go: 'lead' as ModuleKey },
    { ok: Boolean(extract || agentResult), text: '采集 1 条同行视频或口令，沉淀钩子结构', go: 'collector' as ModuleKey },
    { ok: Boolean(copy.script), text: '生成并细改口播文案，确认是否入知识库', go: 'copy' as ModuleKey },
    { ok: Boolean(audio), text: '生成分段情绪配音，确认语速和停顿', go: 'voice' as ModuleKey },
    { ok: selectedMaterialIds.length > 0, text: '选择自有素材，避免直接搬运采集视频', go: 'assets' as ModuleKey },
    { ok: Boolean(video?.video_url), text: '合成视频并下载检查音画字幕', go: 'video' as ModuleKey },
    { ok: Boolean(publish), text: '生成平台发布草稿，后续接开放平台', go: 'publish' as ModuleKey },
  ], [industry, audience, leadPlan, extract, copy.script, audio, selectedMaterialIds, video, publish])
  const nextTodo = pipelineTodos.find(x => !x.ok)

  function openKnowledgeSave(source: string, item: GeneratedCopy) {
    const content = [
      `标题：${item.title || ''}`,
      `黄金三秒：${item.hook || ''}`,
      `口播稿：\n${item.script || ''}`,
      `发布简介：\n${item.description || ''}`,
      `标签：${(item.tags || []).join(', ')}`,
    ].join('\n\n')
    setKnowledgeDialog({
      open: true,
      source,
      title: item.title || `${industry}短视频文案`,
      content,
      tags: ['老板口播', industry, '获客', ...(item.tags || [])].filter(Boolean).slice(0, 8).join(','),
    })
  }

  async function saveKnowledgeDialog() {
    const tags = knowledgeDialog.tags.split(/[,，\s]+/).map(x => x.trim()).filter(Boolean)
    await run('保存文案到知识库', async () => {
      await apiPost('/api/knowledge', { title: knowledgeDialog.title, content: knowledgeDialog.content, tags })
      await apiPost('/api/memory/scripts', {
        title: copy.title,
        hook: copy.hook,
        script: copy.script,
        description: copy.description,
        tags: copy.tags || tags,
        source: knowledgeDialog.source,
        raw: { content: knowledgeDialog.content, saved_from: 'knowledge_dialog' }
      }).catch(() => null)
    })
    setKnowledgeDialog({ open: false, source: '', title: '', content: '', tags: '老板口播,获客,短视频' })
    await reloadMemoryContext()
    setLastHandoff('文案已保存到知识库。后续文案生成、行业雷达和投流建议会优先读取这些样本。')
  }

  function skipKnowledgeDialog() {
    setKnowledgeDialog(prev => ({ ...prev, open: false }))
    setLastHandoff('文案未入知识库，但已经进入当前项目流程；可以继续配音分段。')
  }

  async function run<T>(label: string, fn: () => Promise<T>) {
    setBusy(label); setError('')
    try { return await fn() } catch (e: any) { setError(e.message || String(e)); throw e } finally { setBusy('') }
  }

  async function reloadMemoryContext(applyProfile = false) {
    const ctx = await apiGet<MemoryContextResponse>('/api/memory/context')
    setMemoryContext(ctx)
    setMemoryStatus(ctx.memory_enabled ? 'Supabase 已连接' : '本地记忆模式')
    const profile = ctx.profile || {}
    if (applyProfile && Object.keys(profile).length) {
      if (profile.industry) setIndustry(profile.industry)
      if (profile.audience) setAudience(profile.audience)
      if (profile.selling_points) setSellingPoints(profile.selling_points)
      if (profile.style) setStyle(profile.style)
      if (profile.lead_region) setLeadRegion(profile.lead_region)
      if (profile.conversion_goal) setConversionGoal(profile.conversion_goal)
      if (profile.trend_keywords) setTrendKeywords(profile.trend_keywords)
    }
    if (Array.isArray(ctx.competitors)) {
      setCompetitors(ctx.competitors.map((x: any) => ({
        name: x.name || '',
        platform: x.platform || 'douyin',
        url: x.url || '',
        positioning: x.positioning || '',
        notes: x.notes || ''
      })))
    }
    return ctx
  }

  async function saveCustomerProfile() {
    await run('保存行业档案', () => apiPost('/api/memory/customer-profile', {
      industry,
      audience,
      selling_points: sellingPoints,
      style,
      lead_region: leadRegion,
      conversion_goal: conversionGoal,
      trend_keywords: trendKeywords
    }))
    await reloadMemoryContext(true)
  }


  function toggleLeadChannel(name: string) {
    setLeadChannels(prev => prev.includes(name) ? prev.filter(x => x !== name) : [...prev, name])
  }

  async function makeLeadPlan() {
    const res = await run('生成获客自动化作战图', () => apiPost<LeadAcquisitionPlanResponse>('/api/lead-acquisition/plan', {
      industry,
      audience,
      selling_points: sellingPoints,
      style,
      lead_region: leadRegion,
      conversion_goal: conversionGoal,
      channels: leadChannels,
      fixed_options: leadFixedOptions,
      competitor_notes: competitorNotes,
      trend_keywords: trendKeywords,
      existing_context: memoryContext?.learning_summary || ''
    }))
    setLeadPlan(res!)
    setLastHandoff('获客自动化作战图已生成。同行采集、文案生产、自动监听和私域承接会读取这套策略。')
    setActive('lead')
    await reloadMemoryContext()
  }

  async function reloadAssets() {
    const list = await apiGet<AssetItem[]>('/api/assets')
    setAssets(Array.isArray(list) ? list : [])
  }

  async function reloadCollectorStatus() {
    const status = await getCollectorStatus()
    setCollectorStatus(status)
    return status
  }

  async function reloadAgentStatus() {
    const status = await apiGet<AutoCollectorStatusResponse>('/api/agent/status')
    setAgentStatus(status)
    return status
  }

  async function runAutoAgent() {
    const res = await run('自动采集/学习同行打法', () => apiPost<AutoCollectorRunResponse>('/api/agent/run-now', {
      seed_links: agentSeedLinks,
      include_account_urls: true,
      limit: 3,
      learn_goal: agentLearnGoal,
      token: ''
    }))
    setAgentResult(res!)
    await reloadMemoryContext()
    await reloadAgentStatus().catch(() => null)
    setLastHandoff('自动学习智能体已完成一轮：只沉淀钩子公式、情绪推进和视频打法，不照抄原文。')
  }

  async function saveCollectorCookies() {
    const status = await run('上传抖音 Cookies', () => uploadCollectorCookies(collectorCookieText))
    setCollectorStatus(status!)
    setCollectorCookieText('')
    setShowCookiePanel(false)
    setLastHandoff('抖音采集 Cookies 已更新。之后采集器会携带登录态，公开视频采集成功率会更高。')
  }

  useEffect(() => {
    apiGet('/api/health').then(setHealth).catch((e) => setError(e.message || 'API 未连接'))
    apiGet<TTSVoice[]>('/api/tts/voices').then(v => { const list = Array.isArray(v) ? v : []; setVoices(list); setVoice(list[0]?.id || '') }).catch(() => null)
    reloadAssets().catch(() => null)
    reloadCollectorStatus().catch(() => null)
    reloadAgentStatus().catch(() => null)
    reloadMemoryContext(true).catch(() => null)
  }, [])

  useEffect(() => {
    setSegmentSeconds(prev => {
      const next = { ...prev }
      voiceSegments.forEach((seg, idx) => {
        if (!next[idx]) next[idx] = estimateSeconds(seg.text, seg.speed_ratio)
      })
      return next
    })
  }, [voiceSegments])

  async function handleUpload(files: FileList | null) {
    if (!files?.length) return
    const res = await run('上传素材', () => uploadAssets(files))
    setAssets(prev => [...(res || []), ...prev])
    const ids = (res || []).filter(a => !a.filename.startsWith('collected_')).map(a => a.id)
    if (ids.length) setSelectedMaterialIds(prev => Array.from(new Set([...ids, ...prev])))
  }

  function toggleMaterial(id: string) {
    setSelectedMaterialIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id])
  }

  async function collectCompetitor() {
    const res = await run('采集/拆解同行内容', () => apiPost<InspirationExtractResponse>('/api/inspiration/extract', {
      asset_id: selectedReferenceAssetId || undefined,
      source_url: sourceUrl,
      manual_text: manualText
    }))
    setExtract(res!)
    if (res?.collected_asset_id) setSelectedReferenceAssetId(res.collected_asset_id)
    await reloadAssets()
    await reloadMemoryContext()
    setLastHandoff('同行采集结果已入库。下一步可以直接仿写改写，文案模块会自动读取这条采集内容。')
    if (autoAdvance) setActive('copy')
  }


  async function addCompetitor() {
    const draft = { ...competitorDraft, name: competitorDraft.name.trim(), url: competitorDraft.url.trim(), positioning: competitorDraft.positioning.trim(), notes: competitorDraft.notes.trim() }
    if (!draft.name && !draft.url && !draft.notes) return
    await run('保存竞品账号', () => apiPost('/api/memory/competitors', draft))
    await reloadMemoryContext()
    setCompetitorDraft({ name: '', platform: 'douyin', url: '', positioning: '', notes: '' })
  }

  async function makeTrendRadar() {
    const res = await run('生成行业爆点雷达', () => apiPost<TrendRadarResponse>('/api/trend-radar/auto', {
      industry,
      audience,
      region: leadRegion,
      keywords: trendKeywords.split(/[,，\s]+/).map(x => x.trim()).filter(Boolean),
      competitor_notes: `${competitorNotes}
${extract?.summary || ''}
${manualText || ''}`.trim()
    }))
    setTrendRadar(res!)
    await reloadMemoryContext()
    setLastHandoff('行业雷达已保存到数据库。文案生成会自动读取这些选题和关键词。')
    setActive('trend')
  }

  async function makeShootingPlan() {
    const res = await run('生成运营拍摄任务', () => apiPost<ShootingPlanResponse>('/api/shooting-plan', {
      title: copy.title,
      script: currentScript,
      industry,
      audience,
      selling_points: sellingPoints,
      available_assets: [...materialAssets, ...collectedVideos].map(a => `${a.kind}:${a.original_name}`).join('；'),
      duration_seconds: duration
    }))
    setShootingPlan(res!)
    setActive('shooting')
  }

  async function makeSubtitleAI() {
    const res = await run('智能字幕重点', () => apiPost<SubtitleEmphasisResponse>('/api/subtitle-emphasis', {
      script: currentScript || copy.hook || copy.title,
      style: '强转化短视频字幕，重点词放大，痛点词高亮',
      brand_color: subtitleColor
    }))
    setSubtitleAI(res!)
    if (res?.keywords?.length) setSubtitleHighlight(res.keywords.map(k => k.word).join(','))
    setActive('subtitleCover')
  }

  async function makeGrowthDecision() {
    const res = await run('机器学习投流判断', () => apiPost<GrowthDecisionResponse>('/api/growth-decision', {
      title: copy.title,
      script: currentScript,
      industry,
      objective: conversionGoal,
      metrics: growthMetrics
    }))
    setGrowthDecision(res!)
    setActive('growth')
  }

  async function generateDirectCopy() {
    const res = await run('生成文案', () => apiPost<GeneratedCopy>('/api/generate-copy', {
      topic: sellingPoints,
      industry,
      audience,
      selling_points: `${sellingPoints}\n获客地域/人群：${leadRegion}\n转化目标：${conversionGoal}`,
      style,
      duration_seconds: duration,
      knowledge_examples: manualText ? [manualText] : []
    }))
    setCopy(res!)
    openKnowledgeSave('直接生成文案', res!)
    setLastHandoff('新文案已生成。确认入知识库后，可以继续进入配音导演。')
    setActive('copy')
  }

  async function rewrite() {
    const res = await run('原创改写', () => apiPost<GeneratedCopy>('/api/rewrite-from-inspiration', {
      reference_text: referenceText || '请根据业务信息生成原创老板口播文案。',
      industry,
      audience,
      selling_points: `${sellingPoints}\n获客地域/人群：${leadRegion}\n转化目标：${conversionGoal}`,
      style,
      duration_seconds: duration
    }))
    setCopy(res!)
    openKnowledgeSave('同行仿写改写', res!)
    setLastHandoff('仿写改写已完成。系统已带入同行结构、客户定位和数据库记忆。')
    setActive('copy')
  }

  async function refineCopy() {
    const res = await run('文案细改', () => apiPost<GeneratedCopy>('/api/refine-copy', {
      ...copy,
      instruction: `${refineInstruction}\n重点规避这些词：${matchedBadWords.join('、') || '暂无'}`,
      industry,
      audience,
      selling_points: sellingPoints
    }))
    setCopy(res!)
    openKnowledgeSave('文案细改版本', res!)
    setLastHandoff('细改文案已更新。建议保存到知识库，再进入配音分段。')
  }

  async function planEdit() {
    const res = await run('生成深度剪辑方案', () => apiPost<EditPlanResponse>('/api/edit-plan', {
      title: copy.title,
      script: currentScript,
      duration_seconds: duration,
      asset_summary: [...materialAssets, ...collectedVideos].map(a => `${a.kind}:${a.original_name}`).join('；')
    }))
    setEditPlan(res!)
    setLastHandoff('剪辑方案已生成。视频合成模块会读取文案、素材和配音分段。')
    setActive('video')
  }

  async function makeVoiceDirector() {
    const res = await run('生成配音导演稿', () => apiPost<VoiceDirectorResponse>('/api/voice-director', {
      script: currentScript,
      style: voiceStyle,
      intensity: voiceIntensity,
      target_seconds: duration,
      audience,
      selling_points: sellingPoints
    }))
    const segments = Array.isArray(res!.segments) ? res!.segments : []
    setVoiceSegments(segments)
    setSegmentSeconds(Object.fromEntries(segments.map((seg, idx) => [idx, estimateSeconds(seg.text, seg.speed_ratio)])))
    setVoiceNotes(Array.isArray(res!.director_notes) ? res!.director_notes : [])
    setCopy(prev => ({ ...prev, script: res!.rewritten_script || prev.script }))
    setLastHandoff('配音分段已生成。下一步可以试听配音，或者直接选择素材进行合成。')
    setActive('voice')
  }

  function updateVoiceSegment(index: number, patch: Partial<VoiceSegment>) {
    setVoiceSegments(prev => prev.map((seg, i) => i === index ? { ...seg, ...patch } : seg))
  }

  function addVoiceSegment() {
    setVoiceSegments(prev => [...prev, { ...defaultSegment }])
    setSegmentSeconds(prev => ({ ...prev, [voiceSegments.length]: 4 }))
  }
  function addSelectedScriptAsSegment() {
    const chunk = (window.getSelection?.()?.toString() || '').trim()
    setVoiceSegments(prev => [...prev, { ...defaultSegment, text: chunk || '把这里替换成要加入的新口播。' }])
  }
  function removeVoiceSegment(index: number) { setVoiceSegments(prev => prev.filter((_, i) => i !== index)) }
  function moveVoiceSegment(index: number, dir: -1 | 1) {
    setVoiceSegments(prev => {
      const next = [...prev]
      const target = index + dir
      if (target < 0 || target >= next.length) return prev
      ;[next[index], next[target]] = [next[target], next[index]]
      return next
    })
  }

  async function makeSegmentTTS() {
    const segments = voiceSegments.length ? voiceSegments : [{ ...defaultSegment, text: currentScript || defaultSegment.text }]
    const res = await run('生成分段情绪配音', () => apiPost<TTSResponse>('/api/tts-segments', { segments, voice, overall_rate: '+0%' }))
    setAudio(res!)
    setLastHandoff('配音已生成。可以继续做数字人片段，或直接进入素材选择和剪辑合成。')
    if (autoAdvance) setActive('assets')
  }


  async function makeDigitalHuman() {
    if (!audio?.file_name) { setError('请先在配音导演里生成配音音频。'); setActive('voice'); return }
    if (!digitalHumanAvatarId) { setError('请先选择数字人形象素材：正脸照片、半身照片或本人视频。'); setActive('digitalHuman'); return }
    const res = await run('生成数字人片段', () => apiPost<DigitalHumanCreateResponse>('/api/digital-human/create', {
      avatar_asset_id: digitalHumanAvatarId,
      driver_video_asset_id: digitalHumanDriverId || undefined,
      audio_file_name: audio.file_name,
      title: copy.title,
      script: currentScript,
      engine: digitalHumanEngine,
      jimeng_model: digitalHumanJimengModel,
      consent_confirmed: digitalHumanConsent
    }))
    setDigitalHuman(res!)
    setLastHandoff('数字人片段已生成。可以把它作为素材进入素材选择和剪辑合成。')
    if (autoAdvance) setActive('assets')
  }

  async function composeVideo() {
    const ids = selectedMaterialIds.length ? selectedMaterialIds : materialAssets.slice(0, 8).map(a => a.id)
    const res = await run('合成视频并烧字幕', () => apiPost<ComposeResponse>('/api/compose-video', {
      title: copy.title,
      script: currentScript,
      asset_ids: ids,
      audio_file_name: audio?.file_name,
      duration_seconds: duration,
      voice,
      rate: '+0%'
    }))
    setVideo(res!)
    setLastHandoff('视频已合成。字幕封面和平台发布会自动读取这条成片。')
    if (autoAdvance) setActive('subtitleCover')
  }

  async function chatEditVideo() {
    const richInstruction = `${editInstruction}\n字幕样式：字号 ${subtitleSize}，颜色 ${subtitleColor}，重点词：${subtitleHighlight}\n分段时长：${voiceSegments.map((s, i) => `第${i + 1}段 ${segmentSeconds[i] || estimateSeconds(s.text, s.speed_ratio)}秒 ${segmentTransitions[i] || '叠化'}`).join('；')}`
    const res = await run('AI + 插件修改视频', () => apiPost<VideoEditChatResponse>('/api/video-edit-chat', {
      video_file_name: currentVideoName,
      instruction: richInstruction,
      title: copy.title,
      script: currentScript,
      asset_summary: [...materialAssets, ...collectedVideos].map(a => `${a.kind}:${a.original_name}`).join('；')
    }))
    setEditChat(prev => [res!, ...prev])
    if (res?.new_video_url && res?.new_video_name) {
      setVideo(prev => prev ? { ...prev, video_url: res.new_video_url!, video_name: res.new_video_name! } : { video_url: res.new_video_url!, video_name: res.new_video_name!, duration_seconds: duration, warnings: res.warnings || [] })
    }
    setActive('video')
  }

  async function makeCover() {
    const res = await run('生成封面', () => apiPost<CoverResponse>('/api/cover', {
      title: copy.title || '短视频封面',
      hook: copy.hook,
      subtitle: `${coverStyle} · ${copy.tags?.slice(0, 3).join(' · ')}`,
      brand: industry
    }))
    setCover(res!)
    setLastHandoff('封面已生成。平台发布模块会自动读取视频、封面、标题和简介。')
    setActive('subtitleCover')
  }

  async function analyzeAd() {
    const res = await run('投流分析', () => apiPost<AdAnalysisResponse>('/api/ad-analysis', {
      title: copy.title,
      script: currentScript,
      industry,
      budget: 300,
      objective: conversionGoal
    }))
    setAd(res!)
    setActive('publish')
  }

  async function platformPublish() {
    const res = await run('生成平台发布草稿', () => apiPost<PlatformPublishResponse>('/api/platform-publish', {
      platform,
      title: copy.title,
      description: copy.description,
      tags: copy.tags || [],
      video_file_name: video?.video_name,
      cover_file_name: cover?.cover_name
    }))
    setPublish(res!)
    setActive('publish')
  }

  const stageCards = [
    { label: '1 同行采集', done: Boolean(extract), value: extract?.collector_status || extract?.status || '待采集' },
    { label: '2 仿写改写', done: Boolean(copy.hook || copy.script), value: copy.title || '待生成' },
    { label: '3 配音分段', done: Boolean(audio), value: voiceSegments.length ? `${voiceSegments.length} 段 · ${selectedVoiceName}` : '待配音' },
    { label: '4 素材选择', done: selectedMaterialIds.length > 0, value: selectedMaterialIds.length ? `已选 ${selectedMaterialIds.length} 个素材` : '待选择' },
    { label: '5 剪辑合成', done: Boolean(video?.video_url), value: video?.video_name || '待合成' },
    { label: '6 字幕封面', done: Boolean(cover || subtitleAI), value: cover?.cover_name || (subtitleAI ? '重点字幕已生成' : '待处理') },
    { label: '7 平台发布', done: Boolean(publish), value: publish?.status || '草稿预留' }
  ]

  return <div className="appShell">
    <aside className="studioNav">
      <div className="brandMark">
        <div className="logo">AI</div>
        <div><strong>AI 视频增长中枢</strong><span>采集 · 创作 · 合成 · 转化</span></div>
      </div>
      <button className="startButton" onClick={() => setActive('dashboard')}>开始使用</button>
      <nav>
        {modules.map(item => <button key={item.key} className={active === item.key ? 'active' : ''} onClick={() => setActive(item.key)}>
          <span>{item.icon}</span><b>{item.title}</b><em>{item.tag}</em>
        </button>)}
      </nav>
      <div className="miniStatus"><span>API</span><strong className={health?.ok ? 'greenText' : 'redText'}>{health?.ok ? '已连接' : '未连接'}</strong><small>{health?.tts_provider || 'waiting'} · {health?.ark_video_model || '-'}</small></div>
    </aside>

    <main className="studioMain">
      <header className="heroHeader">
        <div>
          <span className="eyebrow">AI Growth Studio</span>
          <h1>从同行洞察到成片发布，一套闭环获客生产线</h1>
          <p>系统沉淀客户画像、竞品打法、文案资产和素材资产；每一步结果自动流转，减少重复操作，提升内容获客效率。</p>
        </div>
        <div className="scoreCard"><span>当前进度</span><strong>{leadScore}%</strong><small>{leadScore >= 80 ? '可以进入发布前检查' : '继续补齐内容和素材'}</small></div>
      </header>

      {error && <div className="globalError">{error}</div>}
      {busy && <div className="busy">正在执行：{busy}</div>}
      <div className="handoffBar">
        <div><strong>当前联动</strong><span>{lastHandoff}</span></div>
        <label><input type="checkbox" checked={autoAdvance} onChange={e => setAutoAdvance(e.target.checked)} /> 完成后自动切到下一步</label>
        {nextTodo && <button onClick={() => setActive(nextTodo.go)}>下一件事：{nextTodo.text}</button>}
      </div>

      {knowledgeDialog.open && <div className="modalMask">
        <div className="knowledgeModal">
          <div className="sectionHeader"><div><h2>是否放进知识库？</h2><p>保存后，后续文案、行业雷达、投流判断会自动读取这条样本。</p></div><button className="modalClose" onClick={skipKnowledgeDialog}>×</button></div>
          <Field label="知识标题"><input value={knowledgeDialog.title} onChange={e => setKnowledgeDialog({ ...knowledgeDialog, title: e.target.value })} /></Field>
          <Field label="标签"><input value={knowledgeDialog.tags} onChange={e => setKnowledgeDialog({ ...knowledgeDialog, tags: e.target.value })} /></Field>
          <Field label="入库内容"><textarea className="scriptArea" value={knowledgeDialog.content} onChange={e => setKnowledgeDialog({ ...knowledgeDialog, content: e.target.value })} /></Field>
          <div className="buttonRow"><Button busy={busy === '保存文案到知识库' ? busy : ''} label="保存到知识库" onClick={saveKnowledgeDialog} /><Button label="这次不保存，继续下一步" onClick={skipKnowledgeDialog} kind="ghost" /></div>
        </div>
      </div>}

      <section className="progressRail">
        {stageCards.map((s, idx) => <div key={s.label} className={`stage ${s.done ? 'done' : ''}`}>
          <span>{idx + 1}</span><strong>{s.label}</strong><em>{s.value}</em>
        </div>)}
      </section>

      {active === 'dashboard' && <section className="dashboardStack">
        <div className="workflowBoard">
          {workflowSteps.map((step, idx) => <button className="workflowCard" key={`${step.step}-${step.title}`} onClick={() => setActive(step.key)}>
            <span>{step.step}</span>
            <strong>{step.title}</strong>
            <p>{step.desc}</p>
            <em>{step.action}</em>
            {idx < workflowSteps.length - 1 && <b>→</b>}
          </button>)}
        </div>
        <div className="opsGrid">
          {modules.filter(x => ['monitor','lead','strategy','competitor','trend','shooting','growth'].includes(x.key)).map(item => <button className="moduleCard compact" key={item.key} onClick={() => setActive(item.key)}>
            <span className="moduleIcon">{item.icon}</span>
            <strong>{item.title}</strong>
            <p>{item.desc}</p>
            <em>进入</em>
          </button>)}
        </div>
      </section>}

      {active === 'monitor' && <section className="card modulePanel">
        <div className="sectionHeader"><div><h2>运营中控台</h2><p>这里是总览监控：看流程进度、数据库记忆、插件状态和下一步待办。详细数据和投流判断放在最后的增长模块。</p></div><div className="headerActions"><Button label="刷新数据库记忆" onClick={() => reloadMemoryContext(true)} kind="ghost" /><Button busy={busy === '生成行业爆点雷达' ? busy : ''} label="自动跑一次行业雷达" onClick={makeTrendRadar} kind="soft" /></div></div>
        <div className="monitorGrid">
          <div className="monitorCard"><span>流程完成度</span><strong>{leadScore}%</strong><p>{nextTodo ? nextTodo.text : '当前流程已基本闭环，可以进入发布和复盘。'}</p></div>
          <div className="monitorCard"><span>数据库记忆</span><strong>{memoryStatus}</strong><p>{memoryContext?.storage || '未连接'} · 账号 {(memoryContext?.competitors || []).length} · 采集 {(memoryContext?.videos || []).length} · 文案 {(memoryContext?.scripts || []).length}</p></div>
          <div className="monitorCard"><span>API 状态</span><strong>{health?.ok ? '在线' : '未连接'}</strong><p>{health?.tts_provider || '-'} · {health?.ark_video_model || '-'}</p></div>
        </div>
        <div className="pluginGrid">{pluginMatrix.map(p => <div className="pluginCard" key={p.name}><strong>{p.name}</strong><p>{p.desc}</p><em>{p.status}</em></div>)}</div>
        <div className="todoPanel"><h3>下一步待办</h3>{pipelineTodos.map(item => <button key={item.text} className={item.ok ? 'done' : ''} onClick={() => setActive(item.go)}><span>{item.ok ? '✓' : '•'}</span>{item.text}</button>)}</div>
        <div className="memoryBox"><strong>AI 学习摘要</strong><p>{learningSummary}</p></div>
      </section>}


      {active === 'lead' && <section className="card modulePanel leadPanel">
        <div className="sectionHeader"><div><h2>获客自动化</h2><p>围绕海外房产置业和第二家园，把同行流量打法转成可执行的截留、监听、回复和私域承接流程。</p></div><div className="headerActions"><Button busy={busy === '生成获客自动化作战图' ? busy : ''} label="生成获客作战图" onClick={makeLeadPlan} kind="soft" /><Button label="保存行业档案" onClick={saveCustomerProfile} kind="ghost" /></div></div>
        <div className="leadHero">
          <div><span>当前业务</span><strong>{industry}</strong><p>{audience}</p></div>
          <div><span>转化目标</span><strong>{conversionGoal}</strong><p>{leadRegion}</p></div>
        </div>
        <div className="leadChannelSelect">
          {['抖音截留获客','博主联动流量','采集目标客户','自动监听','自动回复','目标用户导流私域'].map(item => <button key={item} className={leadChannels.includes(item) ? 'selected' : ''} onClick={() => toggleLeadChannel(item)}>{item}</button>)}
        </div>
        <div className="grid2">
          <Field label="目标客户与固定选项"><textarea value={leadFixedOptions} onChange={e => setLeadFixedOptions(e.target.value)} /></Field>
          <Field label="监听关键词"><textarea value={trendKeywords} onChange={e => setTrendKeywords(e.target.value)} /></Field>
        </div>
        {!leadPlan && <div className="leadBlueprint">
          <div><b>截留</b><span>同行爆款 → 钩子公式 → 同主题不同角度视频</span></div>
          <div><b>监听</b><span>关键词、评论区问题、竞品更新自动沉淀</span></div>
          <div><b>承接</b><span>自动回复模板 → 私信筛选 → 微信私域标签</span></div>
          <div><b>复盘</b><span>播放、私信、留资、预约数据回流给下一条视频</span></div>
        </div>}
        {leadPlan && <div className="resultBox leadResult"><h3>{leadPlan.overview}</h3>
          <div className="chips">{leadPlan.audience_segments?.map(x => <Pill key={x} tone="purple">{x}</Pill>)}</div>
          <div className="leadPlaybookGrid">{leadPlan.channel_playbook?.map(item => <div className="leadPlaybook" key={item.channel}><strong>{item.channel}</strong><p>{item.goal}</p><h4>动作</h4>{item.actions?.map(x => <small key={x}>· {x}</small>)}<h4>自动化</h4>{item.automation?.map(x => <small key={x}>· {x}</small>)}<em>{item.success_metric}</em></div>)}</div>
          <div className="splitGrid"><div><h4>监听词</h4>{leadPlan.listening_keywords?.map(x => <p key={x}>· {x}</p>)}</div><div><h4>触发内容</h4>{leadPlan.content_triggers?.map(x => <p key={x}>· {x}</p>)}</div><div><h4>每日自动任务</h4>{leadPlan.daily_automation_tasks?.map(x => <p key={x}>· {x}</p>)}</div></div>
          <div className="splitGrid"><div><h4>自动回复</h4>{leadPlan.reply_templates?.map(x => <p key={x}>· {x}</p>)}</div><div><h4>私域承接</h4>{leadPlan.private_domain_sop?.map(x => <p key={x}>· {x}</p>)}</div><div><h4>下一步</h4>{leadPlan.next_actions?.map(x => <p key={x}>· {x}</p>)}</div></div>
        </div>}
      </section>}

      {active === 'strategy' && <section className="card modulePanel">
        <div className="sectionHeader"><div><h2>客户定位</h2><p>先把海外置业客户、第二家园需求和私域承接路径保存好，后续采集、文案、监听和投流都会自动读取。</p></div><div className="headerActions"><Button busy={busy === '保存行业档案' ? busy : ''} label="保存行业档案" onClick={saveCustomerProfile} kind="soft" /><Button busy={busy === '生成获客自动化作战图' ? busy : ''} label="生成获客作战图" onClick={makeLeadPlan} kind="ghost" /></div></div>
        <div className="grid2">
          <Field label="行业"><input value={industry} onChange={e => setIndustry(e.target.value)} /></Field>
          <Field label="目标客户"><input value={audience} onChange={e => setAudience(e.target.value)} /></Field>
          <Field label="获客地域 / 人群"><input value={leadRegion} onChange={e => setLeadRegion(e.target.value)} /></Field>
          <Field label="转化目标"><input value={conversionGoal} onChange={e => setConversionGoal(e.target.value)} /></Field>
        </div>
        <Field label="核心卖点"><textarea value={sellingPoints} onChange={e => setSellingPoints(e.target.value)} /></Field>
        <Field label="视频风格"><input value={style} onChange={e => setStyle(e.target.value)} /></Field>
        <div className="memoryBox"><strong>AI 学习状态：{memoryStatus}</strong><p>{learningSummary}</p><button onClick={() => reloadMemoryContext(true)}>刷新数据库记忆</button></div>
        {ad && <div className="resultBox"><h3>{ad.decision}</h3><p>建议预算：{ad.suggested_budget} · 置信度：{Math.round(ad.confidence * 100)}%</p><div className="chips">{ad.target_audience?.map(x => <Pill key={x}>{x}</Pill>)}</div>{ad.optimization_tips?.map(x => <p key={x}>· {x}</p>)}</div>}
      </section>}

      {active === 'trend' && <section className="card modulePanel">
        <div className="sectionHeader"><div><h2>行业爆点与选题雷达</h2><p>根据行业、目标客户、同行账号和采集内容，生成可拍选题、监控关键词和下一步动作。</p></div><Button busy={busy === '生成行业爆点雷达' ? busy : ''} label="自动采集/生成行业雷达" onClick={makeTrendRadar} /></div>
        <div className="grid2">
          <Field label="监控关键词"><input value={trendKeywords} onChange={e => setTrendKeywords(e.target.value)} placeholder="海外房产,第二家园,海外置业,子女教育,养老度假" /></Field>
          <Field label="同行备注汇总"><textarea value={`${competitorNotes}${extract?.summary ? '\n' + extract.summary : ''}`} readOnly placeholder="竞品账号库和同行采集结果会自动汇总到这里" /></Field>
        </div>
        {trendRadar ? <div className="resultBox"><h3>{trendRadar.summary}</h3><div className="trendGrid">{trendRadar.hot_topics?.map(item => <div className="trendCard" key={item.title}><div className="heat"><span>{item.heat}</span><em>热度</em></div><strong>{item.title}</strong><p>{item.reason}</p><small>角度：{item.angle}</small><small>钩子：{item.suggested_hook}</small>{item.risk && <div className="warn">{item.risk}</div>}</div>)}</div><div className="splitGrid"><div><h4>内容角度</h4>{trendRadar.content_angles?.map(x => <p key={x}>· {x}</p>)}</div><div><h4>拍摄建议</h4>{trendRadar.shooting_suggestions?.map(x => <p key={x}>· {x}</p>)}</div><div><h4>监控词</h4><div className="chips">{trendRadar.monitor_keywords?.map(x => <Pill key={x}>{x}</Pill>)}</div></div></div></div> : <Empty>保存客户定位、账号库和采集结果后，系统会自动读取数据库生成行业雷达。</Empty>}
      </section>}

      {active === 'competitor' && <section className="card modulePanel">
        <div className="sectionHeader"><div><h2>竞品账号库</h2><p>把同行账号、定位、爆款特点沉淀到数据库。行业雷达、仿写改写、投流决策都会读取这些信息。</p></div><div className="headerActions"><Button label="刷新账号库" onClick={() => reloadMemoryContext()} kind="ghost" /><Button busy={busy === '保存竞品账号' ? busy : ''} label="加入账号库" onClick={addCompetitor} kind="soft" /></div></div>
        <div className="grid4"><Field label="账号名称"><input value={competitorDraft.name} onChange={e => setCompetitorDraft({ ...competitorDraft, name: e.target.value })} placeholder="例如：天诺老吴" /></Field><Field label="平台"><select value={competitorDraft.platform} onChange={e => setCompetitorDraft({ ...competitorDraft, platform: e.target.value })}><option value="douyin">抖音</option><option value="shipinhao">视频号</option><option value="kuaishou">快手</option><option value="xiaohongshu">小红书</option></select></Field><Field label="主页/视频链接"><input value={competitorDraft.url} onChange={e => setCompetitorDraft({ ...competitorDraft, url: e.target.value })} placeholder="账号主页或爆款链接" /></Field><Field label="账号定位"><input value={competitorDraft.positioning} onChange={e => setCompetitorDraft({ ...competitorDraft, positioning: e.target.value })} placeholder="同城获客/投流/电商创业" /></Field></div>
        <Field label="爆款特点 / 观察备注"><textarea value={competitorDraft.notes} onChange={e => setCompetitorDraft({ ...competitorDraft, notes: e.target.value })} placeholder="常用钩子、客户痛点、封面风格、评论区反馈、发布时间等" /></Field>
        <div className="competitorList">{competitors.length === 0 && <Empty>还没有竞品账号。先加 3-5 个同行账号，系统会更懂行业。</Empty>}{competitors.map((c, i) => <div className="competitorCard" key={`${c.name}-${i}`}><div><strong>{c.name || '未命名账号'}</strong><Pill tone="purple">{c.platform}</Pill></div><p>{c.positioning || '未填写定位'}</p><small>{c.url}</small><em>{c.notes}</em><button onClick={() => setCompetitors(prev => prev.filter((_, idx) => idx !== i))}>删除</button></div>)}</div>
      </section>}

      {active === 'collector' && <section className="card modulePanel">
        <div className="sectionHeader"><div><h2>第一步：采集同行视频</h2><p>文件上传后先采集同行视频。可以上传 MP4，也可以粘抖音分享口令；采不到视频时先拆标题、钩子和话题。</p></div><Button busy={busy === '采集/拆解同行内容' ? busy : ''} label="采集同行视频/口令" onClick={collectCompetitor} /></div>
        <div className="grid2">
          <Field label="抖音分享口令 / 视频链接"><textarea value={sourceUrl} onChange={e => setSourceUrl(e.target.value)} placeholder="直接粘贴：1.58 ... https://v.douyin.com/... 复制此链接..." /></Field>
          <Field label="手动粘贴竞品文案 / 豆包 App 识别稿"><textarea value={manualText} onChange={e => setManualText(e.target.value)} placeholder="如果已经有真实口播稿，粘这里。" /></Field>
        </div>
        <div className="collectorAssist">
          <div>
            <strong>视频采集增强</strong>
            <p>{collectorStatus?.hint || '正在读取采集器状态...'}</p>
            <small>状态：{collectorStatus?.cookie_exists ? '已配置登录态 Cookies' : '未配置 Cookies'} · 采集器：{collectorStatus?.enabled ? '已启用' : '未启用'}</small>
          </div>
          <div className="buttonRow mini">
            <Button label="刷新采集状态" onClick={() => reloadCollectorStatus()} kind="ghost" />
            <Button label={showCookiePanel ? '收起 Cookies' : '上传 Cookies'} onClick={() => setShowCookiePanel(v => !v)} kind="soft" />
          </div>
        </div>
        <div className="agentPanel">
          <div className="sectionHeader compact"><div><h3>后台自动学习智能体</h3><p>它会读取竞品账号库和种子链接，尽力发现/采集新视频，然后只学习钩子公式、节奏和转化结构，不复制原文。</p></div><div className="buttonRow mini"><Button label="刷新智能体" onClick={() => reloadAgentStatus()} kind="ghost" /><Button busy={busy === '自动采集/学习同行打法' ? busy : ''} label="立即跑一轮" onClick={runAutoAgent} kind="soft" /></div></div>
          <div className="grid2">
            <Field label="种子链接（可选，一行一个）" hint="可以填某个博主的主页/爆款视频链接；空着时会自动读取竞品账号库 URL。"><textarea value={agentSeedLinks} onChange={e => setAgentSeedLinks(e.target.value)} placeholder="https://v.douyin.com/...
https://www.douyin.com/user/..." /></Field>
            <Field label="学习目标" hint="强调学习打法，不要复制文案。"><textarea value={agentLearnGoal} onChange={e => setAgentLearnGoal(e.target.value)} /></Field>
          </div>
          <div className="agentStats">
            <Pill tone={agentStatus?.enabled ? 'green' : 'orange'}>{agentStatus?.enabled ? '后台定时已启用' : '后台定时未启用'}</Pill>
            <Pill>竞品账号 {agentStatus?.competitors_count ?? competitors.length}</Pill>
            <Pill tone={agentStatus?.memory_enabled ? 'green' : 'orange'}>{agentStatus?.memory_enabled ? 'Supabase 记忆库' : '本地记忆'}</Pill>
            <Pill>每轮最多 {agentStatus?.run_limit ?? 3} 条</Pill>
          </div>
          {agentResult && <div className="resultBox"><h3>{agentResult.learning?.summary || '自动学习完成'}</h3><div className="splitGrid"><div><h4>学到的方法</h4>{(agentResult.learning?.creator_methods || []).map((x: string) => <p key={x}>· {x}</p>)}</div><div><h4>钩子公式</h4>{(agentResult.learning?.hook_formulas || []).map((x: any, i: number) => <p key={i}>· {x.name || '公式'}：{x.template || x.logic || JSON.stringify(x)}</p>)}</div><div><h4>迁移规则</h4>{(agentResult.learning?.transfer_rules || []).map((x: string) => <p key={x}>· {x}</p>)}</div></div>{agentResult.warnings?.slice(0, 6).map(w => <div className="warn" key={w}>{w}</div>)}</div>}
        </div>
        {showCookiePanel && <div className="cookiePanel">
          <h4>上传 douyin_cookies.txt</h4>
          <p>遇到 “Fresh cookies needed” 时，需要导出你自己浏览器里的抖音 cookies。只用于你的后端采集公开可访问内容，不会提交到前端展示。</p>
          <textarea value={collectorCookieText} onChange={e => setCollectorCookieText(e.target.value)} placeholder="# Netscape HTTP Cookie File\n.douyin.com\tTRUE\t/\tTRUE\t..." />
          <div className="buttonRow">
            <Button busy={busy === '上传抖音 Cookies' ? busy : ''} label="保存 Cookies 到后端" onClick={saveCollectorCookies} disabled={!collectorCookieText.trim()} />
            <Button label="取消" onClick={() => setShowCookiePanel(false)} kind="ghost" />
          </div>
        </div>}
        {extract && <div className="resultBox">
          <div className="resultTop"><Pill>{extract.status}</Pill><Pill tone="purple">{extract.collector_status || 'text'}</Pill>{extract.collected_video_url && <a href={extract.collected_video_url} target="_blank">打开采集视频</a>}</div>
          <h3>同行拆解结果</h3><p>{extract.summary}</p>
          <div className="splitGrid"><div><h4>黄金三秒/钩子</h4>{extract.hooks?.map(x => <p key={x}>· {x}</p>)}</div><div><h4>卖点/痛点</h4>{extract.selling_points?.map(x => <p key={x}>· {x}</p>)}</div><div><h4>结构</h4>{extract.structure?.map(x => <p key={x}>· {x}</p>)}</div></div>
          {extract.warnings?.map(w => <div className="warn" key={w}>{w}</div>)}
        </div>}
        <div className="memoryList"><h3>数据库已采集同行内容</h3>{(memoryContext?.videos || []).slice(0, 6).map((v: any) => <div className="memoryItem" key={v.id || v.created_at}><strong>{v.source_name || v.summary || '同行采集记录'}</strong><p>{v.summary || v.transcript || v.manual_text}</p><small>{v.status} · {v.collector_status} · {v.created_at}</small></div>)}{!(memoryContext?.videos || []).length && <Empty>还没有入库采集记录。每次采集会自动保存，后续 AI 会读取。</Empty>}</div>
        <div className="memoryList"><h3>自动学习到的博主打法</h3>{(memoryContext?.events || []).filter((e: any) => e.event_type === 'auto_creator_learning').slice(0, 5).map((e: any) => <div className="memoryItem" key={e.id || e.created_at}><strong>{e.payload?.learning?.summary || e.title || '自动学习记录'}</strong><p>{(e.payload?.learning?.creator_methods || []).slice(0, 3).join('；')}</p><small>只学习结构方法，不照抄文案 · {e.created_at}</small></div>)}{!(memoryContext?.events || []).filter((e: any) => e.event_type === 'auto_creator_learning').length && <Empty>自动智能体跑过后，会把钩子公式、情绪推进和迁移规则沉淀到这里。</Empty>}</div>
      </section>}

      {active === 'copy' && <section className="card modulePanel">
        <div className="sectionHeader"><div><h2>第二步：仿写改写 / 第三步：文案细改</h2><p>先学习同行视频的钩子和结构，再生成自己的原创文案。下面可以细改标题、开头、口播稿和发布简介。</p></div></div>
        <div className="grid4"><Field label="视频时长"><input type="number" min={5} max={180} value={duration} onChange={e => setDuration(Number(e.target.value || 35))} /></Field><Field label="标题字数方向"><input value="短、狠、直给" readOnly /></Field><Field label="开头策略"><input value="痛点/反差/警告/结果" readOnly /></Field><Field label="当前风险"><input value={matchedBadWords.length ? `${matchedBadWords.length} 个敏感词` : '暂无明显风险'} readOnly /></Field></div>
        <div className="buttonRow"><Button busy={busy === '原创改写' ? busy : ''} label="第二步：仿写改写" onClick={rewrite} /><Button busy={busy === '生成文案' ? busy : ''} label="直接生成新文案" onClick={generateDirectCopy} kind="ghost" /><Button busy={busy === '文案细改' ? busy : ''} label="细改/优化文案" onClick={refineCopy} kind="soft" disabled={!currentScript} /><Button label="把当前文案放进知识库" onClick={() => openKnowledgeSave('手动保存当前文案', copy)} kind="ghost" disabled={!currentScript} /><Button label="继续去配音分段" onClick={() => setActive('voice')} kind="soft" disabled={!currentScript} /></div>
        <div className="flowSource"><strong>自动带入来源</strong><span>客户定位：{industry} / {audience}</span><span>同行采集：{extract?.summary ? shortText(extract.summary) : '暂无'}</span><span>数据库记忆：{memoryContext?.memory_enabled ? 'Supabase 已启用' : '本地调试记忆'}</span></div>
        <div className="copyEditor"><Field label="标题"><input value={copy.title} onChange={e => setCopy({ ...copy, title: e.target.value })} /></Field><Field label="黄金三秒钩子"><textarea value={copy.hook} onChange={e => setCopy({ ...copy, hook: e.target.value })} /></Field><Field label="完整口播稿"><textarea className="scriptArea" value={copy.script} onChange={e => setCopy({ ...copy, script: e.target.value })} placeholder="这里可以精修口播稿；选中文本后点“加入分段”。" /></Field><Field label="发布简介"><textarea value={copy.description} onChange={e => setCopy({ ...copy, description: e.target.value })} /></Field><Field label="细改要求"><input value={refineInstruction} onChange={e => setRefineInstruction(e.target.value)} /></Field></div>
        <div className="chips">{matchedBadWords.length ? matchedBadWords.map(x => <Pill key={x} tone="red">风险词：{x}</Pill>) : <Pill tone="green">违禁词初筛通过</Pill>}</div>
      </section>}

      {active === 'voice' && <section className="card modulePanel">
        <div className="sectionHeader"><div><h2>第四步：配音导演</h2><p>选择克隆音色，把口播稿拆成多段。每段可以自己加文案、调情绪、语速、音量和停顿。</p></div></div>
        <div className="grid4"><Field label="音色"><select value={voice} onChange={e => setVoice(e.target.value)}>{voices.map(v => <option key={v.id} value={v.id}>{v.name || v.id}</option>)}</select></Field><Field label="配音风格"><select value={voiceStyle} onChange={e => setVoiceStyle(e.target.value)}>{['老板压迫感','真实聊天感','短视频强钩子','销售转化感','案例讲述感','沉稳信任感'].map(x => <option key={x}>{x}</option>)}</select></Field><Field label="情绪强度"><select value={voiceIntensity} onChange={e => setVoiceIntensity(e.target.value)}>{['轻微','标准','强烈'].map(x => <option key={x}>{x}</option>)}</select></Field><div className="stackButtons"><Button busy={busy === '生成配音导演稿' ? busy : ''} label="生成配音导演稿" onClick={makeVoiceDirector} kind="ghost" disabled={!currentScript} /><Button busy={busy === '生成分段情绪配音' ? busy : ''} label="生成分段情绪配音" onClick={makeSegmentTTS} disabled={!currentScript} /></div></div>
        {voiceNotes.length > 0 && <div className="tips">{voiceNotes.map(x => <span key={x}>{x}</span>)}</div>}
        <div className="buttonRow"><button className="addSegment" onClick={addVoiceSegment}>+ 手动添加空白分段</button><button className="addSegment" onClick={addSelectedScriptAsSegment}>+ 把选中文案加入分段</button></div>
        <div className="segments">{voiceSegments.map((seg, i) => <div className="segmentCard" key={i}><div className="segmentHead"><strong>第 {i + 1} 段 · {segmentSeconds[i] || estimateSeconds(seg.text, seg.speed_ratio)} 秒</strong><div><button onClick={() => moveVoiceSegment(i, -1)}>↑</button><button onClick={() => moveVoiceSegment(i, 1)}>↓</button><button onClick={() => removeVoiceSegment(i)}>删除</button></div></div><textarea value={seg.text} onChange={e => updateVoiceSegment(i, { text: e.target.value })} /><div className="segmentGrid"><Field label="情绪"><input value={seg.emotion} onChange={e => updateVoiceSegment(i, { emotion: e.target.value })} /></Field><Field label={`语速 ${seg.speed_ratio}`}><input type="range" min="0.75" max="1.35" step="0.01" value={seg.speed_ratio} onChange={e => updateVoiceSegment(i, { speed_ratio: Number(e.target.value) })} /></Field><Field label={`音量 ${seg.volume_ratio}`}><input type="range" min="0.7" max="1.4" step="0.01" value={seg.volume_ratio} onChange={e => updateVoiceSegment(i, { volume_ratio: Number(e.target.value) })} /></Field><Field label={`停顿 ${seg.pause_after_ms}ms`}><input type="range" min="0" max="1500" step="50" value={seg.pause_after_ms} onChange={e => updateVoiceSegment(i, { pause_after_ms: Number(e.target.value) })} /></Field></div></div>)}</div>
        {audio && <div className="mediaBox"><audio controls src={audio.file_url} /><a href={audio.file_url} target="_blank">下载配音</a>{audio.warning && <div className="warn">{audio.warning}</div>}</div>}
      </section>}

      {active === 'digitalHuman' && <section className="card modulePanel">
        <div className="sectionHeader"><div><h2>数字人工作台</h2><p>上传授权的本人照片或视频，用当前豆包配音生成老板数字人口播片段。未接 GPU/API 时会先生成静态头像预览。</p></div><Button busy={busy === '生成数字人片段' ? busy : ''} label="生成数字人片段" onClick={makeDigitalHuman} disabled={!audio?.file_name || !digitalHumanAvatarId || !digitalHumanConsent} /></div>
        <div className="grid3">
          <Field label="数字人形象素材" hint="建议上传本人授权的正脸/半身照片，或 5-15 秒自然说话视频。"><select value={digitalHumanAvatarId} onChange={e => setDigitalHumanAvatarId(e.target.value)}><option value="">选择已上传照片/视频</option>{assets.map(a => <option key={a.id} value={a.id}>{a.kind} · {a.original_name || a.filename}</option>)}</select></Field>
          <Field label="动作参考视频（可选）" hint="后续接 LivePortrait/MuseTalk 时可参考表情和头部动作。"><select value={digitalHumanDriverId} onChange={e => setDigitalHumanDriverId(e.target.value)}><option value="">不用动作参考</option>{assets.filter(a => a.kind === 'video').map(a => <option key={a.id} value={a.id}>{a.original_name || a.filename}</option>)}</select></Field>
          <Field label="数字人引擎" hint="可选火山即梦/OmniHuman，或使用上传素材直接合成。"><select value={digitalHumanEngine} onChange={e => setDigitalHumanEngine(e.target.value)}><option value="auto">自动</option><option value="preview">静态预览/素材合成</option><option value="jimeng">火山即梦/OmniHuman</option><option value="webhook">外部 Webhook/API</option><option value="sadtalker">SadTalker</option><option value="musetalk">MuseTalk</option><option value="wav2lip">Wav2Lip</option><option value="liveportrait">LivePortrait</option></select></Field>
          {digitalHumanEngine === 'jimeng' && <Field label="即梦模型" hint="模拟真人优先选 OmniHuman1.5；普通视频生成可用视频3.0。"><select value={digitalHumanJimengModel} onChange={e => setDigitalHumanJimengModel(e.target.value)}><option value="omnihuman15">OmniHuman1.5（单图+音频真人口播）</option><option value="quick">数字人快速模式</option><option value="video30">即梦视频生成3.0（图生视频）</option></select></Field>}
        </div>
        <label className="checkline"><input type="checkbox" checked={digitalHumanConsent} onChange={e => setDigitalHumanConsent(e.target.checked)} /> 我确认已获得本人形象和声音授权，仅用于合法商业内容。</label>
        <div className="infoGrid"><div><strong>当前输入</strong><p>形象素材：{digitalHumanAvatarId || '未选择'}<br />配音音频：{audio?.file_name || '未生成'}<br />脚本：{shortText(currentScript || '', 90) || '未生成'}</p></div><div><strong>接入建议</strong><p>需要真人口型同步时选择“火山即梦/OmniHuman”；不调用数字人时用“静态预览/素材合成”继续走上传素材合成流程。</p></div></div>
        {digitalHuman && <div className="resultBox"><h3>数字人结果</h3><p>{digitalHuman.message}</p>{digitalHuman.warnings?.map(w => <div className="warn" key={w}>{w}</div>)}{digitalHuman.video_url && <video controls src={digitalHuman.video_url} className="previewVideo" />}{digitalHuman.video_url && <a className="download" href={digitalHuman.video_url} target="_blank">下载/打开数字人片段</a>}</div>}
      </section>}

      {active === 'assets' && <section className="card modulePanel">
        <div className="sectionHeader"><div><h2>第五步：选择视频素材</h2><p>素材库是你自己的可用视频/图片，采集视频库只用于学习同行结构；合成时优先选自有素材。</p></div><input type="file" multiple accept="image/*,video/*" onChange={e => handleUpload(e.target.files)} /></div>
        <div className="grid2"><div><h3>素材库</h3><div className="assetList">{materialAssets.length === 0 && <Empty>还没有素材。</Empty>}{materialAssets.map(a => <label key={a.id} className="assetRow"><input type="checkbox" checked={selectedMaterialIds.includes(a.id)} onChange={() => toggleMaterial(a.id)} /><span>{a.kind === 'video' ? '🎬' : '🖼️'} {a.original_name}</span><em>{formatBytes(a.size_bytes)}</em></label>)}</div></div><div><h3>采集视频库</h3><div className="assetList">{collectedVideos.length === 0 && <Empty>暂时没有采集到视频。</Empty>}{collectedVideos.map(a => <button key={a.id} className={`assetButton ${selectedReferenceAssetId === a.id ? 'selected' : ''}`} onClick={() => setSelectedReferenceAssetId(a.id)}>🎯 {a.original_name}<em>{formatBytes(a.size_bytes)}</em></button>)}</div></div></div>
        <div className="resultBox"><h3>素材匹配建议</h3><p>优先把老板出镜、办公室、客户交流、产品细节、服务流程素材分别对应到口播分段。没有匹配素材时，先用采集视频的结构做 B-roll 参考，不直接照搬原画面。</p></div>
      </section>}

      {active === 'shooting' && <section className="card modulePanel">
        <div className="sectionHeader"><div><h2>运营拍摄任务</h2><p>把文案变成老板、员工能直接照着拍的镜头清单、B-roll 清单和提词器。</p></div><Button busy={busy === '生成运营拍摄任务' ? busy : ''} label="生成拍摄任务单" onClick={makeShootingPlan} disabled={!currentScript} /></div>
        {shootingPlan ? <div className="resultBox"><h3>{shootingPlan.summary}</h3><div className="shotTable">{shootingPlan.shot_tasks?.map((task, i) => <div className="shotRow" key={`${task.scene}-${i}`}><span>{task.priority}</span><strong>{task.scene}</strong><em>{task.duration}</em><p>{task.content}</p><small>{task.camera}</small><small>{task.props}</small></div>)}</div><div className="splitGrid"><div><h4>B-roll 补拍</h4>{shootingPlan.broll_list?.map(x => <p key={x}>· {x}</p>)}</div><div><h4>提词器短句</h4>{shootingPlan.teleprompter?.map(x => <p key={x}>· {x}</p>)}</div><div><h4>拍摄检查</h4>{shootingPlan.checklist?.map(x => <p key={x}>· {x}</p>)}</div></div></div> : <Empty>先生成文案，再生成拍摄任务单。</Empty>}
      </section>}

      {active === 'video' && <section className="card modulePanel">
        <div className="sectionHeader"><div><h2>第六步：剪辑、转场、贴片与合成</h2><p>给每段分配时长和转场，后续可接贴片、叠化、虚化、快切、重点字幕和 AI 指令重剪。</p></div><Button busy={busy === '合成视频并烧字幕' ? busy : ''} label="生成视频并下载 MP4" onClick={composeVideo} disabled={!currentScript} /></div>
        <div className="timelineEditor"><h3>分段时长 / 转场</h3>{voiceSegments.length === 0 && <Empty>先生成配音导演稿，或手动添加分段。</Empty>}{voiceSegments.map((seg, i) => <div className="timelineRow" key={i}><span>第{i + 1}段</span><input type="number" min="1" max="60" step="0.5" value={segmentSeconds[i] || estimateSeconds(seg.text, seg.speed_ratio)} onChange={e => setSegmentSeconds(prev => ({ ...prev, [i]: Number(e.target.value) }))} /><select value={segmentTransitions[i] || '叠化'} onChange={e => setSegmentTransitions(prev => ({ ...prev, [i]: e.target.value }))}><option>叠化</option><option>虚化</option><option>快切</option><option>推近</option><option>闪白</option></select><em>{seg.text.slice(0, 28)}...</em></div>)}</div>
        {video && <div className="videoGrid"><video controls src={video.video_url} /><div className="downloadPanel"><a className="download" href={video.video_url} target="_blank">下载视频 MP4</a>{video.subtitle_url && <a href={video.subtitle_url} target="_blank">下载字幕 SRT</a>}{video.audio_url && <a href={video.audio_url} target="_blank">下载音频</a>}{video.warnings?.map(w => <div className="warn" key={w}>{w}</div>)}</div></div>}
        <div className="editChatBox"><Field label="AI + 插件剪辑指令"><textarea value={editInstruction} onChange={e => setEditInstruction(e.target.value)} placeholder="例如：去掉开头2秒、整体加速1.1倍、重新加字幕、转成9:16。" /></Field><Button busy={busy === 'AI + 插件修改视频' ? busy : ''} label="AI + 插件修改视频" onClick={chatEditVideo} kind="ghost" disabled={!currentVideoName} />{editChat.map((msg, i) => <div className="chatMsg" key={i}><strong>AI：</strong>{msg.assistant_message}<p>{msg.summary}</p><div className="chips">{msg.actions?.map(x => <Pill key={x}>{x}</Pill>)}</div>{msg.new_video_url && <a href={msg.new_video_url} target="_blank">打开修改后视频</a>}{msg.warnings?.map(w => <div className="warn" key={w}>{w}</div>)}</div>)}</div>
      </section>}

      {active === 'subtitleCover' && <section className="card modulePanel">
        <div className="sectionHeader"><div><h2>字幕重点与封面</h2><p>自动识别重点词，生成放大、高亮、描边字幕方案，并输出封面样式。</p></div><div className="stackButtons"><Button busy={busy === '智能字幕重点' ? busy : ''} label="智能识别重点字幕" onClick={makeSubtitleAI} disabled={!currentScript} kind="ghost" /><Button busy={busy === '生成封面' ? busy : ''} label="生成封面" onClick={makeCover} /></div></div>
        <div className="grid4"><Field label="字幕字号"><input type="number" value={subtitleSize} onChange={e => setSubtitleSize(Number(e.target.value || 58))} /></Field><Field label="字幕颜色"><input type="color" value={subtitleColor} onChange={e => setSubtitleColor(e.target.value)} /></Field><Field label="重点词"><input value={subtitleHighlight} onChange={e => setSubtitleHighlight(e.target.value)} /></Field><Field label="封面样式"><select value={coverStyle} onChange={e => setCoverStyle(e.target.value)}><option>老板口播强钩子封面</option><option>痛点警告型封面</option><option>案例结果型封面</option><option>产品服务型封面</option><option>同城获客型封面</option></select></Field></div>
        {subtitleAI && <div className="resultBox"><h3>{subtitleAI.template}</h3><div className="chips">{subtitleAI.keywords?.map(k => <Pill key={k.word} tone="orange">{k.word} · {k.effect}</Pill>)}</div><div className="splitGrid"><div><h4>字幕建议</h4>{subtitleAI.srt_tips?.map(x => <p key={x}>· {x}</p>)}</div><div><h4>封面大字</h4>{subtitleAI.cover_text_options?.map(x => <p key={x}>· {x}</p>)}</div><div><h4>已写入重点词</h4><p>{subtitleHighlight}</p></div></div></div>}
        {cover && <div className="coverPreview"><img src={cover.cover_url} /><div><h3>封面已生成</h3><p>{cover.prompt}</p><a className="download" href={cover.cover_url} target="_blank">下载封面</a></div></div>}
      </section>}

      {active === 'growth' && <section className="card modulePanel">
        <div className="sectionHeader"><div><h2>流量监控与投流决策</h2><p>先手动录入发布后的核心数据，系统会用规则 + AI 判断是否加热、换封面、重剪或停投。</p></div><Button busy={busy === '机器学习投流判断' ? busy : ''} label="生成投流决策" onClick={makeGrowthDecision} kind="soft" /></div>
        <div className="metricGrid">
          <Field label="播放量"><input type="number" value={growthMetrics.views} onChange={e => setGrowthMetrics({ ...growthMetrics, views: Number(e.target.value || 0) })} /></Field>
          <Field label="点赞"><input type="number" value={growthMetrics.likes} onChange={e => setGrowthMetrics({ ...growthMetrics, likes: Number(e.target.value || 0) })} /></Field>
          <Field label="评论"><input type="number" value={growthMetrics.comments} onChange={e => setGrowthMetrics({ ...growthMetrics, comments: Number(e.target.value || 0) })} /></Field>
          <Field label="分享"><input type="number" value={growthMetrics.shares} onChange={e => setGrowthMetrics({ ...growthMetrics, shares: Number(e.target.value || 0) })} /></Field>
          <Field label="关注"><input type="number" value={growthMetrics.follows} onChange={e => setGrowthMetrics({ ...growthMetrics, follows: Number(e.target.value || 0) })} /></Field>
          <Field label="线索/私信"><input type="number" value={growthMetrics.leads} onChange={e => setGrowthMetrics({ ...growthMetrics, leads: Number(e.target.value || 0) })} /></Field>
          <Field label="完播率 %"><input type="number" value={growthMetrics.completion_rate} onChange={e => setGrowthMetrics({ ...growthMetrics, completion_rate: Number(e.target.value || 0) })} /></Field>
          <Field label="投流消耗"><input type="number" value={growthMetrics.spend} onChange={e => setGrowthMetrics({ ...growthMetrics, spend: Number(e.target.value || 0) })} /></Field>
          <Field label="发布后小时"><input type="number" value={growthMetrics.hours_after_publish} onChange={e => setGrowthMetrics({ ...growthMetrics, hours_after_publish: Number(e.target.value || 0) })} /></Field>
        </div>
        {growthDecision ? <div className="resultBox growthResult"><div className="scoreRing"><strong>{growthDecision.score}</strong><span>投流分</span></div><div><h3>{growthDecision.decision}</h3><p>{growthDecision.reason}</p><p>预算建议：{growthDecision.recommended_budget}</p><div className="splitGrid"><div><h4>动作</h4>{growthDecision.actions?.map(x => <p key={x}>· {x}</p>)}</div><div><h4>风险</h4>{growthDecision.alerts?.map(x => <p key={x}>· {x}</p>)}</div><div><h4>下一轮测试</h4>{growthDecision.next_test?.map(x => <p key={x}>· {x}</p>)}</div></div></div></div> : <Empty>发布后录入数据，系统会给投流/停投/重剪建议。</Empty>}
      </section>}

      {active === 'publish' && <section className="card modulePanel">
        <div className="sectionHeader"><div><h2>第七步：平台发布</h2><p>先生成抖音、视频号、快手、小红书发布草稿。开放平台权限下来后再接真实发布和数据回流。</p></div></div>
        <div className="buttonRow"><Button busy={busy === '投流分析' ? busy : ''} label="投流分析" onClick={analyzeAd} kind="ghost" /><select value={platform} onChange={e => setPlatform(e.target.value)}><option value="douyin">抖音</option><option value="shipinhao">视频号</option><option value="kuaishou">快手</option><option value="xiaohongshu">小红书</option></select><Button busy={busy === '生成平台发布草稿' ? busy : ''} label="生成平台发布草稿" onClick={platformPublish} /></div>
        <div className="grid2">{ad && <div className="miniResult"><h3>{ad.decision}</h3><p>预算：{ad.suggested_budget}</p>{ad.optimization_tips?.map(x => <p key={x}>· {x}</p>)}</div>}{publish && <div className="miniResult"><h3>{publish.platform}：{publish.status}</h3><p>{publish.message}</p>{publish.checklist?.map(x => <p key={x}>· {x}</p>)}</div>}</div>
      </section>}
    </main>
  </div>
}
