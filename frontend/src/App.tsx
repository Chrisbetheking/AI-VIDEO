import { Component, useEffect, useMemo, useState, type ErrorInfo, type ReactNode } from 'react'
import './styles.css'
import {
  AdAnalysisResponse,
  AssetItem,
  ComposeResponse,
  CoverResponse,
  ImageGenerateResponse,
  GraphicPostResponse,
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
  OneClickGenerateResponse,
  ModelStatusResponse,
  TTSResponse,
  TTSVoice,
  VideoEditChatResponse,
  VoiceDirectorResponse,
  VoiceSegment,
  apiGet,
  apiPost,
  getCollectorStatus,
  uploadCollectorCookies,
  uploadAssets,
  deleteAsset
} from './api'

type ModuleKey = 'dashboard' | 'monitor' | 'lead' | 'oneClick' | 'collector' | 'copy' | 'voice' | 'digitalHuman' | 'assets' | 'video' | 'subtitleCover' | 'publish' | 'strategy' | 'competitor' | 'trend' | 'shooting' | 'growth'
type AssetClipSetting = { order: number; image_seconds: number; video_start: number; video_end: number }

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


class AppErrorBoundary extends Component<{ children: ReactNode }, { error: string }> {
  state = { error: '' }
  static getDerivedStateFromError(error: unknown) {
    return { error: error instanceof Error ? error.message : String(error) }
  }
  componentDidCatch(error: unknown, info: ErrorInfo) {
    console.error('[AI-VIDEO] 前端渲染异常', error, info)
  }
  render() {
    if (!this.state.error) return this.props.children
    return <div className="fatalFallback">
      <h1>页面渲染异常，已拦截白屏</h1>
      <p>这通常是旧素材字段缺失或浏览器缓存了旧版本导致。先点下面按钮清理本地临时状态，然后刷新。</p>
      <pre>{this.state.error}</pre>
      <div className="buttonRow">
        <button className="btn primary" onClick={() => window.location.reload()}>刷新页面</button>
        <button className="btn soft" onClick={() => { window.localStorage.removeItem('ai_video_current_digital_human_task_v1'); window.location.href = '/' }}>清理当前任务并回首页</button>
      </div>
    </div>
  }
}

function safeText(value: unknown, fallback = '') {
  if (value === null || value === undefined) return fallback
  const text = String(value).trim()
  return text || fallback
}

function safeNumber(value: unknown, fallback = 0) {
  const n = Number(value)
  return Number.isFinite(n) ? n : fallback
}

function safeProjectDuration(...values: unknown[]) {
  for (const value of values) {
    const n = safeNumber(value, 0)
    if (n > 0) return Math.round(Math.min(180, Math.max(5, n)))
  }
  return 12
}

function normalizeAsset(raw: any, index = 0): AssetItem {
  const filename = safeText(raw?.filename, safeText(raw?.file_name, safeText(raw?.name, safeText(raw?.original_name, `asset_${index}`))))
  const originalName = safeText(raw?.original_name, filename)
  const url = safeText(raw?.url, safeText(raw?.file_url, safeText(raw?.public_url, '')))
  const lower = `${filename} ${url}`.toLowerCase()
  const kind = raw?.kind === 'video' || /\.(mp4|mov|webm|m4v)(\?|$)/i.test(lower) ? 'video' : 'image'
  return {
    id: safeText(raw?.id, filename || `asset_${index}`),
    filename,
    original_name: originalName,
    kind,
    url,
    size_bytes: Number(raw?.size_bytes || raw?.size || 0) || 0,
    created_at: safeText(raw?.created_at, new Date().toISOString())
  }
}

const emptyCopy: GeneratedCopy = { title: '', hook: '', script: '', description: '', tags: [], shots: [], kb_refs: [] }
const DIGITAL_HUMAN_TASK_KEY = 'ai_video_current_digital_human_task_v1'
const emotionOptions = ['自然可信', '提醒警示', '紧张急迫', '坚定有力', '朋友聊天', '专业冷静', '惊讶反问', '收尾号召']

function getDigitalHumanTaskModel(task: DigitalHumanCreateResponse | null, fallback: string) {
  const engine = String(task?.engine || '')
  const match = engine.match(/^jimeng:([a-zA-Z0-9_-]+)/)
  return match?.[1] || fallback || 'omnihuman15'
}


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
  { key: 'oneClick', icon: '生', title: '一键生成中心', desc: '在一个窗口完成文案、配音分段、字幕、图文和发布草稿', tag: '一键' },
  { key: 'assets', icon: '素', title: '1. 素材选择', desc: '先选/上传素材，确定图片停留和视频截取区间', tag: '素材' },
  { key: 'copy', icon: '文', title: '2. 文案生产', desc: '根据素材和客户目标生成口播文案', tag: '文案' },
  { key: 'voice', icon: '声', title: '3. 配音导演', desc: '克隆音色、分段情绪、语速停顿', tag: '配音' },
  { key: 'digitalHuman', icon: '人', title: '4. 数字人', desc: '上传本人形象，生成老板口播片段', tag: '数字人' },
  { key: 'video', icon: '剪', title: '5. 剪辑合成', desc: '素材顺序、截取区间、字幕烧录和导出', tag: '剪辑' },
  { key: 'collector', icon: '采', title: '同行采集', desc: '可选：采集同行视频、口令和钩子结构', tag: '采集' },
  { key: 'subtitleCover', icon: '视', title: '6. 字幕 / 封面 / 图文', desc: '抖音风字幕、素材截图封面、AI 图文素材', tag: '视觉' },
  { key: 'publish', icon: '发', title: '7. 平台发布', desc: '发布草稿、平台适配、开放接口预留', tag: '发布' },
  { key: 'strategy', icon: '客', title: '客户定位', desc: '行业、目标客户、成交路径、老板人设', tag: '定位' },
  { key: 'competitor', icon: '竞', title: '竞品账号库', desc: '长期沉淀同行账号和爆款特征', tag: '账号' },
  { key: 'trend', icon: '雷', title: '行业爆点', desc: '选题雷达、热点关键词、拍摄方向', tag: '雷达' },
  { key: 'shooting', icon: '拍', title: '运营拍摄', desc: '拍摄任务单、提词器、B-roll 清单', tag: '拍摄' },
  { key: 'growth', icon: '投', title: '增长投流细节', desc: '流量数据、机器学习投流、优化动作', tag: '增长' }
]

const workflowSteps: { key: ModuleKey; step: string; title: string; desc: string; action: string }[] = [
  { key: 'oneClick', step: '00', title: '一键生成中心', desc: '一个窗口统筹，但第一步仍然先确认素材，避免后面只有文字稿。', action: '开始' },
  { key: 'assets', step: '01', title: '选择素材', desc: '先上传/选择视频和图片，排好出现顺序，图片停留和视频截取都在这里调。', action: '选素材' },
  { key: 'copy', step: '02', title: '文案生产', desc: '根据已选素材、行业、客户和转化目标生成短视频口播稿。', action: '写文案' },
  { key: 'voice', step: '03', title: '配音分段', desc: '分段控制情绪、语速、音量和停顿，并生成真实时间轴。', action: '去配音' },
  { key: 'digitalHuman', step: '04', title: '数字人片段', desc: '可选：用配音生成老板数字人口播素材，或者跳过直接素材混剪。', action: '做数字人' },
  { key: 'video', step: '05', title: '剪辑合成', desc: '按素材顺序和配音时长自动铺满，字幕直接在剪辑页调整。', action: '去剪辑' },
  { key: 'subtitleCover', step: '06', title: '字幕/封面/图文', desc: '生成视频封面和图文引流包，字幕也可在剪辑页直接处理。', action: '做包装' },
  { key: 'publish', step: '07', title: '平台发布', desc: '自动继承视频、封面、标题、简介和话题，生成发布草稿。', action: '去发布' }
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
  const order: ModuleKey[] = ['oneClick','assets','copy','voice','digitalHuman','video','subtitleCover','publish']
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

function readMediaDuration(event: any, fallback = 0) {
  const el = event?.currentTarget || event?.target
  const value = Number(el?.duration)
  return Number.isFinite(value) && value > 0 ? value : fallback
}

function AppInner() {
  const [active, setActive] = useState<ModuleKey>('dashboard')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [health, setHealth] = useState<any>(null)
  const [modelStatus, setModelStatus] = useState<ModelStatusResponse | null>(null)
  const [contentNavOpen, setContentNavOpen] = useState(true)

  const [industry, setIndustry] = useState('海外房产置业 · 第二家园')
  const [audience, setAudience] = useState('有海外置业、第二家园、子女教育、养老度假和资产配置需求的华人家庭与企业主')
  const [sellingPoints, setSellingPoints] = useState('海外第二家园规划、国家/城市筛选、项目匹配、置业流程、生活配套、长期服务和顾问式咨询')
  const [style, setStyle] = useState('专业可信、顾问式成交、真实案例、短视频强钩子')
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
  const [assetClipSettings, setAssetClipSettings] = useState<Record<string, AssetClipSetting>>({})
  const [assetDurations, setAssetDurations] = useState<Record<string, number>>({})
  const [selectedReferenceAssetId, setSelectedReferenceAssetId] = useState('')
  const [assetSearch, setAssetSearch] = useState('')
  const [assetKindFilter, setAssetKindFilter] = useState<'all' | 'image' | 'video'>('all')
  const [assetTimeFilter, setAssetTimeFilter] = useState<'all' | 'today' | '7d' | '30d'>('all')
  const [assetSort, setAssetSort] = useState<'new' | 'old' | 'size_desc' | 'size_asc' | 'name'>('new')
  const [isDraggingAssets, setIsDraggingAssets] = useState(false)
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
  const [oneClick, setOneClick] = useState<OneClickGenerateResponse | null>(null)
  const [oneClickInstruction, setOneClickInstruction] = useState('生成一条适合老板数字人口播的获客短视频，开头要强，字幕要有抖音口播感，结尾引导私信。')
  const [oneClickChatInput, setOneClickChatInput] = useState('把开头改得更像老板提醒客户，减少书面词，字幕重点更强。')
  const [oneClickOutputType, setOneClickOutputType] = useState('digital_human')
  const [oneClickMaterialMode, setOneClickMaterialMode] = useState('selected_assets')
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
  const [digitalHumanPollCount, setDigitalHumanPollCount] = useState(0)
  const [digitalHumanLastChecked, setDigitalHumanLastChecked] = useState('')

  const [segmentSeconds, setSegmentSeconds] = useState<Record<number, number>>({})
  const [segmentTransitions, setSegmentTransitions] = useState<Record<number, string>>({})
  const [subtitleSize, setSubtitleSize] = useState(18)
  const [subtitleMarginV, setSubtitleMarginV] = useState(70)
  const [subtitlePosition, setSubtitlePosition] = useState<'bottom_safe' | 'middle_low' | 'center'>('bottom_safe')
  const [subtitleColor, setSubtitleColor] = useState('#ffffff')
  const [subtitleHighlight, setSubtitleHighlight] = useState('第二家园,海外置业,子女教育,养老度假,资产配置,私信咨询')
  const [coverStyle, setCoverStyle] = useState('海外第二家园强钩子封面')

  const [video, setVideo] = useState<ComposeResponse | null>(null)
  const [cover, setCover] = useState<CoverResponse | null>(null)
  const [generatedImage, setGeneratedImage] = useState<ImageGenerateResponse | null>(null)
  const [graphicPost, setGraphicPost] = useState<GraphicPostResponse | null>(null)
  const [graphicPlatform, setGraphicPlatform] = useState('xiaohongshu')
  const [graphicSlideCount, setGraphicSlideCount] = useState(5)
  const [graphicBackgroundMode, setGraphicBackgroundMode] = useState<'asset' | 'ai' | 'generated' | 'clean'>('asset')
  const [coverSourceMode, setCoverSourceMode] = useState<'asset' | 'digitalHuman' | 'aiImage' | 'clean'>('asset')
  const [coverSourceAssetId, setCoverSourceAssetId] = useState('')
  const [imagePrompt, setImagePrompt] = useState('高端海外第二家园置业场景，阳光、现代住宅、商务顾问感，适合作为短视频封面背景，不要文字')
  const [digitalHumanVersion, setDigitalHumanVersion] = useState(() => Number(window.localStorage.getItem('ai_video_digital_human_version_v1') || '1'))
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

  const materialAssets = useMemo(() => assets.map((a, i) => normalizeAsset(a, i)).filter(a => Boolean(a.id && a.url) && !safeText(a.filename).startsWith('collected_')), [assets])
  const collectedVideos = useMemo(() => assets.map((a, i) => normalizeAsset(a, i)).filter(a => Boolean(a.id && a.url) && a.kind === 'video' && safeText(a.filename).startsWith('collected_')), [assets])
  const filteredMaterialAssets = useMemo(() => {
    const now = Date.now()
    const maxAge = assetTimeFilter === 'today' ? 24 * 3600 * 1000 : assetTimeFilter === '7d' ? 7 * 24 * 3600 * 1000 : assetTimeFilter === '30d' ? 30 * 24 * 3600 * 1000 : 0
    const q = assetSearch.trim().toLowerCase()
    const list = materialAssets.filter(a => {
      if (assetKindFilter !== 'all' && a.kind !== assetKindFilter) return false
      if (q && !`${a.original_name} ${a.filename} ${a.kind}`.toLowerCase().includes(q)) return false
      if (maxAge) {
        const t = new Date(a.created_at).getTime()
        if (!Number.isFinite(t) || now - t > maxAge) return false
      }
      return true
    })
    return [...list].sort((a, b) => {
      if (assetSort === 'old') return new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
      if (assetSort === 'size_desc') return (b.size_bytes || 0) - (a.size_bytes || 0)
      if (assetSort === 'size_asc') return (a.size_bytes || 0) - (b.size_bytes || 0)
      if (assetSort === 'name') return safeText(a.original_name, a.filename).localeCompare(safeText(b.original_name, b.filename), 'zh-Hans-CN')
      return new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    })
  }, [materialAssets, assetKindFilter, assetSearch, assetSort, assetTimeFilter])
  const selectedMaterialAssets = useMemo(() => selectedMaterialIds
    .map(id => materialAssets.find(a => a.id === id))
    .filter((a): a is AssetItem => Boolean(a && a.id && a.url))
    .map((a, i) => normalizeAsset(a, i)), [materialAssets, selectedMaterialIds])
  const referenceText = useMemo(() => extract?.transcript || manualText || sourceUrl, [extract, manualText, sourceUrl])
  const competitorNotes = useMemo(() => competitors.map(c => `${c.platform}｜${c.name}｜${c.positioning}｜${c.notes}`).join('\n'), [competitors])
  const learningSummary = memoryContext?.learning_summary || '保存客户定位、竞品账号和采集结果后，AI 会在文案、雷达、投流建议里自动读取。'
  const currentScript = copy.script || ''
  const currentVideoName = video?.video_name || extract?.collected_video_name || ''
  const selectedVoiceName = voices.find(v => v.id === voice)?.name || voice || '未选择音色'
  const matchedBadWords = useMemo(() => badWords.filter(w => `${copy.title}${copy.hook}${copy.script}${copy.description}`.includes(w)), [copy])

  const selectedAssetEstimatedSeconds = useMemo(() => {
    if (!selectedMaterialAssets.length) return 0
    return Math.round(selectedMaterialAssets.reduce((total, asset, index) => {
      const cfg = getClipSetting(asset, index)
      if (asset.kind === 'image') return total + Math.max(0.8, cfg.image_seconds || 2.8)
      const maxDur = Math.max(1, assetDurations[asset.id] || 60)
      const start = Math.max(0, Math.min(cfg.video_start || 0, maxDur - 0.3))
      const end = cfg.video_end && cfg.video_end > start ? Math.min(cfg.video_end, maxDur) : Math.min(maxDur, start + 3.2)
      return total + Math.max(0.6, end - start)
    }, 0) * 10) / 10
  }, [selectedMaterialAssets, assetClipSettings, assetDurations])
  const voiceEstimatedSeconds = useMemo(() => {
    if (!voiceSegments.length) return 0
    return Math.round(voiceSegments.reduce((total, seg, index) => {
      const measured = audio?.segments?.[index]?.duration || segmentSeconds[index]
      const spoken = measured || estimateSeconds(seg.text, seg.speed_ratio)
      return total + spoken + Math.max(0, seg.pause_after_ms || 0) / 1000
    }, 0) * 10) / 10
  }, [voiceSegments, audio?.segments, segmentSeconds])
  const autoProjectSeconds = useMemo(() => {
    const base = audio?.duration_seconds || voiceEstimatedSeconds || selectedAssetEstimatedSeconds || 35
    return Math.round(Math.min(180, Math.max(10, base)))
  }, [audio?.duration_seconds, voiceEstimatedSeconds, selectedAssetEstimatedSeconds])

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


  function applyOneClickResult(result: OneClickGenerateResponse) {
    setOneClick(result)
    setCopy(result.copy || emptyCopy)
    setVoiceSegments(result.voice_director?.segments || [])
    setVoiceNotes(result.voice_director?.director_notes || [])
    setEditPlan(result.edit_plan || null)
    setShootingPlan(result.shooting_plan || null)
    setSubtitleAI(result.subtitle || null)
    const firstCover = result.subtitle?.cover_text_options?.[0] || result.project_title || result.copy?.title || coverStyle
    setCoverStyle(firstCover)
    const keywords = result.subtitle?.keywords?.map(k => k.word).filter(Boolean).join(',')
    if (keywords) setSubtitleHighlight(keywords)
    setLastHandoff('一键生成方案已同步到文案、配音、拍摄、剪辑、字幕和发布草稿。你可以在这个窗口继续让 AI 修改，也可以进入单独步骤精修。')
  }

  async function runOneClickGenerate() {
    const selectedNames = selectedMaterialAssets.map(a => a.original_name || a.filename)
    const res = await run('一键生成完整方案', () => apiPost<OneClickGenerateResponse>('/api/one-click/generate', {
      industry,
      audience,
      selling_points: sellingPoints,
      style,
      duration_seconds: autoProjectSeconds,
      goal: conversionGoal,
      output_type: oneClickOutputType,
      material_mode: oneClickMaterialMode,
      selected_asset_names: selectedNames,
      reference_text: referenceText,
      instruction: oneClickInstruction,
    }))
    applyOneClickResult(res!)
    setActive('oneClick')
  }

  async function runOneClickChat() {
    if (!oneClick) { setError('请先生成一键方案，再让 AI 修改。'); return }
    const res = await run('AI 修改一键方案', () => apiPost<OneClickGenerateResponse>('/api/one-click/chat', {
      instruction: oneClickChatInput,
      current: oneClick,
      industry,
      audience,
      selling_points: sellingPoints,
    }))
    applyOneClickResult(res!)
    setActive('oneClick')
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
    setAssets(Array.isArray(list) ? list.map((item, index) => normalizeAsset(item, index)).filter(item => item.id && item.url) : [])
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
    apiGet<ModelStatusResponse>('/api/model/status').then(setModelStatus).catch(() => null)
    apiGet<TTSVoice[]>('/api/tts/voices').then(v => { const list = Array.isArray(v) ? v : []; setVoices(list); setVoice(list[0]?.id || '') }).catch(() => null)
    reloadAssets().catch(() => null)
    reloadCollectorStatus().catch(() => null)
    reloadAgentStatus().catch(() => null)
    reloadMemoryContext(true).catch(() => null)
  }, [])

  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(DIGITAL_HUMAN_TASK_KEY)
      if (!saved) return
      const parsed = JSON.parse(saved) as DigitalHumanCreateResponse
      if (parsed?.job_id) {
        setDigitalHuman(parsed)
        setDigitalHumanLastChecked('已恢复上次任务')
      }
    } catch {
      window.localStorage.removeItem(DIGITAL_HUMAN_TASK_KEY)
    }
  }, [])

  useEffect(() => {
    try { window.localStorage.setItem('ai_video_digital_human_version_v1', String(digitalHumanVersion || 1)) } catch {}
  }, [digitalHumanVersion])

  useEffect(() => {
    try {
      if (digitalHuman?.job_id) {
        window.localStorage.setItem(DIGITAL_HUMAN_TASK_KEY, JSON.stringify(digitalHuman))
      } else if (!digitalHuman) {
        window.localStorage.removeItem(DIGITAL_HUMAN_TASK_KEY)
      }
    } catch {
      // Ignore localStorage quota / privacy-mode errors.
    }
  }, [digitalHuman])

  useEffect(() => {
    setSegmentSeconds(prev => {
      const next = { ...prev }
      voiceSegments.forEach((seg, idx) => {
        if (!next[idx]) next[idx] = estimateSeconds(seg.text, seg.speed_ratio)
      })
      return next
    })
  }, [voiceSegments])

  useEffect(() => {
    const status = String(digitalHuman?.status || '').toLowerCase()
    const shouldPoll = active === 'digitalHuman'
      && Boolean(digitalHuman?.job_id)
      && !digitalHuman?.video_url
      && ['running', 'submitted', 'queued', 'queueing', 'pending', 'processing', '10000', ''].includes(status)
    if (!shouldPoll) return
    const timer = window.setInterval(() => {
      checkDigitalHumanStatus(true).catch(() => null)
    }, 20000)
    return () => window.clearInterval(timer)
  }, [active, digitalHuman?.job_id, digitalHuman?.video_url, digitalHuman?.status, digitalHuman?.engine, digitalHumanJimengModel])

  async function handleUpload(files: FileList | null) {
    if (!files?.length) return
    const res = await run('上传素材', () => uploadAssets(files))
    setAssets(prev => [...(res || []), ...prev])
    const ids = (res || []).filter(a => !a.filename.startsWith('collected_')).map(a => a.id)
    if (ids.length) setSelectedMaterialIds(prev => Array.from(new Set([...ids, ...prev])))
  }

  function defaultClipSetting(asset: AssetItem, order: number): AssetClipSetting {
    return { order, image_seconds: asset.kind === 'image' ? 2.8 : 3, video_start: 0, video_end: 0 }
  }

  function getClipSetting(asset: AssetItem, index: number): AssetClipSetting {
    const safeAsset = asset || ({ id: `missing_${index}`, kind: 'image' } as AssetItem)
    const stored = assetClipSettings[safeAsset.id] || {}
    const fallback = defaultClipSetting(safeAsset, index)
    return {
      order: Number.isFinite(Number((stored as any).order)) ? Number((stored as any).order) : fallback.order,
      image_seconds: Number.isFinite(Number((stored as any).image_seconds)) && Number((stored as any).image_seconds) > 0 ? Number((stored as any).image_seconds) : fallback.image_seconds,
      video_start: Number.isFinite(Number((stored as any).video_start)) ? Math.max(0, Number((stored as any).video_start)) : fallback.video_start,
      video_end: Number.isFinite(Number((stored as any).video_end)) ? Math.max(0, Number((stored as any).video_end)) : fallback.video_end,
    }
  }

  function updateClipSetting(id: string, patch: Partial<AssetClipSetting>) {
    setAssetClipSettings(prev => ({ ...prev, [id]: { ...(prev[id] || { order: selectedMaterialIds.indexOf(id), image_seconds: 2.8, video_start: 0, video_end: 0 }), ...patch } }))
  }

  function toggleMaterial(id: string) {
    setSelectedMaterialIds(prev => {
      if (prev.includes(id)) return prev.filter(x => x !== id)
      const next = [...prev, id]
      const asset = materialAssets.find(a => a.id === id)
      if (asset) setAssetClipSettings(current => ({ ...current, [id]: current[id] || defaultClipSetting(asset, next.length - 1) }))
      return next
    })
  }

  function moveSelectedMaterial(index: number, dir: -1 | 1) {
    setSelectedMaterialIds(prev => {
      const target = index + dir
      if (target < 0 || target >= prev.length) return prev
      const next = [...prev]
      ;[next[index], next[target]] = [next[target], next[index]]
      setAssetClipSettings(current => {
        const copy = { ...current }
        next.forEach((id, order) => { copy[id] = { ...(copy[id] || { image_seconds: 2.8, video_start: 0, video_end: 0, order }), order } })
        return copy
      })
      return next
    })
  }

  function applyVoicePreset(index: number, preset: 'urgent' | 'calm' | 'emphasis' | 'cta') {
    const presetMap = {
      urgent: { emotion: '紧张急迫', speed_ratio: 1.22, volume_ratio: 1.35, pause_after_ms: 220 },
      calm: { emotion: '专业冷静', speed_ratio: 0.92, volume_ratio: 1.0, pause_after_ms: 650 },
      emphasis: { emotion: '坚定有力', speed_ratio: 1.06, volume_ratio: 1.55, pause_after_ms: 420 },
      cta: { emotion: '收尾号召', speed_ratio: 1.12, volume_ratio: 1.45, pause_after_ms: 260 },
    } as const
    updateVoiceSegment(index, presetMap[preset])
  }

  async function removeAsset(asset: AssetItem) {
    const name = asset.original_name || asset.filename
    if (!confirm(`确认删除素材「${name}」？这会从素材库移除，已选剪辑也会同步取消。`)) return
    await run('删除素材', () => deleteAsset(asset.id))
    setAssets(prev => prev.filter(a => a.id !== asset.id))
    setSelectedMaterialIds(prev => prev.filter(id => id !== asset.id))
    if (selectedReferenceAssetId === asset.id) setSelectedReferenceAssetId('')
    if (digitalHumanAvatarId === asset.id) setDigitalHumanAvatarId('')
    if (digitalHumanDriverId === asset.id) setDigitalHumanDriverId('')
  }

  function onAssetDragOver(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault()
    setIsDraggingAssets(true)
  }

  function onAssetDragLeave(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault()
    if (e.currentTarget.contains(e.relatedTarget as Node | null)) return
    setIsDraggingAssets(false)
  }

  async function onAssetDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault()
    setIsDraggingAssets(false)
    await handleUpload(e.dataTransfer.files)
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
      duration_seconds: autoProjectSeconds
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
      duration_seconds: autoProjectSeconds,
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
      duration_seconds: autoProjectSeconds
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
      duration_seconds: autoProjectSeconds,
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
      target_seconds: autoProjectSeconds,
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
    const currentStatus = String(digitalHuman?.status || '').toLowerCase()
    const hasRunningJimengTask = Boolean(digitalHuman?.job_id && !digitalHuman?.video_url && !['failed', 'error', 'done'].includes(currentStatus))
    if (hasRunningJimengTask) {
      setError('已有火山即梦数字人任务正在生成中，不要重复提交。火山当前并发额度通常是 1 个任务；请直接查询当前任务结果，或等任务结束后再新建。')
      await checkDigitalHumanStatus(false)
      return
    }
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
    setDigitalHumanVersion(prev => digitalHuman?.job_id || digitalHuman?.video_url ? prev + 1 : prev)
    setDigitalHumanPollCount(0)
    setDigitalHumanLastChecked(new Date().toLocaleTimeString())
    if (res?.video_url) {
      setLastHandoff('数字人片段已生成。可以把它作为素材进入素材选择和剪辑合成。')
      if (autoAdvance) setActive('assets')
    } else {
      setLastHandoff('火山即梦任务已提交。不要重复提交；系统会自动查询，通常需要 5-30 分钟。')
    }
  }

  function clearDigitalHumanTask() {
    setDigitalHuman(null)
    setDigitalHumanPollCount(0)
    setDigitalHumanLastChecked('')
    try { window.localStorage.removeItem(DIGITAL_HUMAN_TASK_KEY) } catch {}
    setLastHandoff('已清除当前数字人任务。可以重新提交一个新的 OmniHuman1.5 任务。')
  }

  async function checkDigitalHumanStatus(silent = false) {
    if (!digitalHuman?.job_id) { if (!silent) setError('当前没有可查询的数字人 task_id。'); return }
    const taskModel = getDigitalHumanTaskModel(digitalHuman, digitalHumanJimengModel)
    const url = `/api/digital-human/status/${encodeURIComponent(digitalHuman.job_id || '')}?model=${encodeURIComponent(taskModel)}`
    const fetchStatus = () => apiGet<DigitalHumanCreateResponse>(url)
    let res: DigitalHumanCreateResponse | undefined
    if (silent) {
      try { res = await fetchStatus() } catch { return }
    } else {
      res = await run('查询数字人结果', fetchStatus)
    }
    if (!res) return
    setDigitalHuman(res)
    setDigitalHumanLastChecked(new Date().toLocaleTimeString())
    setDigitalHumanPollCount(prev => prev + 1)
    if (res.video_url) {
      setLastHandoff('数字人片段已生成。可以把它作为素材进入素材选择和剪辑合成。')
    } else if (String(res.status || '').toLowerCase() === 'failed') {
      setLastHandoff('当前数字人任务不可继续查询。请查看火山原始返回，必要时清除当前任务后重新提交。')
    } else {
      setLastHandoff('火山即梦仍在生成或排队中。系统会每 20 秒自动查询一次，也可以手动点击查询。')
    }
  }

  async function composeVideo() {
    if (!currentScript.trim()) {
      setError('请先生成或填写文案，再合成视频。')
      return
    }
    const chosen = (selectedMaterialAssets.length ? selectedMaterialAssets : materialAssets.slice(0, 6))
      .map((asset, index) => normalizeAsset(asset, index))
      .filter(asset => Boolean(asset.id && asset.url))
    if (!chosen.length) {
      setError('请先在素材选择页上传或选择至少 1 个图片/视频素材。')
      setActive('assets')
      return
    }
    const assetPlan = chosen.map((asset, index) => {
      const cfg = getClipSetting(asset, index)
      const imageSeconds = safeNumber(cfg.image_seconds, 2.8)
      const start = Math.max(0, safeNumber(cfg.video_start, 0))
      const rawEnd = safeNumber(cfg.video_end, 0)
      return {
        asset_id: String(asset.id),
        order: index,
        kind: asset.kind === 'video' ? 'video' : 'image',
        image_seconds: asset.kind === 'image' ? Math.min(20, Math.max(0.8, imageSeconds)) : 0,
        video_start: asset.kind === 'video' ? start : 0,
        video_end: asset.kind === 'video' && rawEnd > start ? rawEnd : 0,
      }
    })
    const safeSubtitleSegments = Array.isArray(audio?.segments) ? audio.segments.map((seg: any, index: number) => ({
      index: Number.isFinite(Number(seg?.index)) ? Number(seg.index) : index,
      text: safeText(seg?.text, ''),
      start: Math.max(0, safeNumber(seg?.start, 0)),
      end: Math.max(0, safeNumber(seg?.end, safeNumber(seg?.start, 0) + safeNumber(seg?.duration, 0))),
      duration: Math.max(0, safeNumber(seg?.duration, safeNumber(seg?.end, 0) - safeNumber(seg?.start, 0))),
    })).filter((seg: any) => seg.text && seg.end > seg.start) : []
    const durationSeconds = safeProjectDuration(audio?.duration_seconds, selectedAssetEstimatedSeconds, voiceEstimatedSeconds, autoProjectSeconds)
    const res = await run('合成视频并烧字幕', () => apiPost<ComposeResponse>('/api/compose-video', {
      title: safeText(copy.title, '短视频'),
      script: currentScript.trim(),
      asset_ids: chosen.map(a => String(a.id)),
      asset_plan: assetPlan,
      audio_file_name: audio?.file_name || undefined,
      duration_seconds: durationSeconds,
      voice,
      rate: '+0%',
      subtitle_size: subtitleSize,
      subtitle_margin_v: subtitleMarginV,
      subtitle_position: subtitlePosition,
      subtitle_segments: safeSubtitleSegments
    }))
    setVideo(res!)
    setLastHandoff('视频已合成。字幕已按配音分段时间轴烧录；封面和平台发布会自动读取这条成片。')
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
      setVideo(prev => prev ? { ...prev, video_url: res.new_video_url!, video_name: res.new_video_name! } : { video_url: res.new_video_url!, video_name: res.new_video_name!, duration_seconds: autoProjectSeconds, warnings: res.warnings || [] })
    }
    setActive('video')
  }

  async function makeAiImage() {
    const res = await run('AI 生成精美背景图', () => apiPost<ImageGenerateResponse>('/api/image/generate', {
      prompt: imagePrompt,
      title: copy.title || industry,
      style: '精美商业短视频素材，真实感，高级质感，适合做抖音/小红书封面背景，不直接生成文字',
      size: '2K',
      quality: 'high'
    }))
    setGeneratedImage(res!)
    setCoverSourceMode('aiImage')
    setLastHandoff('AI 背景图已生成。现在可以用它叠加大标题生成封面，也可以只作为图文素材使用。')
    setActive('subtitleCover')
  }


  async function makeGraphicPost() {
    const fallbackAsset = coverSourceAssetId || selectedMaterialIds.find(id => assets.find(a => a.id === id)?.kind === 'image') || materialAssets.find(a => a.kind === 'image')?.id || ''
    const payload: any = {
      title: copy.title || industry || '图文引流包',
      hook: copy.hook || '先收藏，这几件事一定要弄懂。',
      script: currentScript || copy.description || sellingPoints,
      industry,
      audience,
      selling_points: sellingPoints,
      style: `${style}；图文引流，不是封面；要像小红书/抖音收藏图文，精美、真实、强转化`,
      platform: graphicPlatform,
      slide_count: graphicSlideCount,
      cta: conversionGoal || '想要完整清单，私信发你。',
      background_mode: graphicBackgroundMode,
      image_prompt: imagePrompt
    }
    if (graphicBackgroundMode === 'asset' && fallbackAsset) payload.source_asset_id = fallbackAsset
    if (graphicBackgroundMode === 'generated' && generatedImage?.image_url) payload.background_url = generatedImage.image_url
    const res = await run('生成图文引流包', () => apiPost<GraphicPostResponse>('/api/graphic-post/generate', payload))
    setGraphicPost(res!)
    setLastHandoff('图文引流包已生成：这是给小红书/抖音图文/朋友圈引流用的，不是视频封面。')
    setActive('subtitleCover')
  }

  async function makeCover() {
    const fallbackAsset = coverSourceAssetId || selectedMaterialIds[0] || materialAssets.find(a => a.kind === 'image')?.id || materialAssets[0]?.id || ''
    const payload: any = {
      title: copy.title || '短视频封面',
      hook: copy.hook,
      subtitle: `${coverStyle} · ${copy.tags?.slice(0, 3).join(' · ')}`,
      brand: industry,
      template: 'douyin'
    }
    if (coverSourceMode === 'asset' && fallbackAsset) payload.source_asset_id = fallbackAsset
    if (coverSourceMode === 'digitalHuman' && digitalHuman?.video_name) payload.source_file_name = digitalHuman.video_name
    if (coverSourceMode === 'aiImage' && generatedImage?.image_url) payload.background_url = generatedImage.image_url
    const res = await run('生成封面', () => apiPost<CoverResponse>('/api/cover', payload))
    setCover(res!)
    setLastHandoff('封面已生成：真实素材/AI背景 + 抖音大标题模板。平台发布模块会自动读取视频、封面、标题和简介。')
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
    { label: '1 素材选择', done: selectedMaterialIds.length > 0, value: selectedMaterialIds.length ? `已选 ${selectedMaterialIds.length} 个素材` : '先选素材' },
    { label: '2 文案生产', done: Boolean(copy.hook || copy.script), value: copy.title || '待生成' },
    { label: '3 配音分段', done: Boolean(audio), value: voiceSegments.length ? `${voiceSegments.length} 段 · ${selectedVoiceName}` : '待配音' },
    { label: '4 数字人', done: Boolean(digitalHuman?.video_url), value: digitalHuman?.video_url ? `数字人 #${digitalHumanVersion}` : '可选' },
    { label: '5 剪辑合成', done: Boolean(video?.video_url), value: video?.video_name || '待合成' },
    { label: '6 字幕/封面/图文', done: Boolean(cover || subtitleAI || generatedImage || graphicPost), value: graphicPost ? `${graphicPost.images.length}张图文` : cover?.cover_name || generatedImage?.image_name || (subtitleAI ? '重点字幕已生成' : '待处理') },
    { label: '7 平台发布', done: Boolean(publish), value: publish?.status || '草稿预留' }
  ]

  const digitalHumanStatus = String(digitalHuman?.status || '').toLowerCase()
  const hasRunningDigitalHumanTask = Boolean(digitalHuman?.job_id && !digitalHuman?.video_url && !['failed', 'error', 'done'].includes(digitalHumanStatus))
  const digitalHumanPrimaryLabel = hasRunningDigitalHumanTask ? '查询当前数字人任务' : '生成数字人片段'
  const contentNavKeys: ModuleKey[] = ['oneClick','assets','copy','voice','digitalHuman','video','subtitleCover','publish','collector']

  return <div className="appShell">
    <aside className="studioNav">
      <div className="brandMark">
        <div className="logo">AI</div>
        <div><strong>AI 视频增长中枢</strong><span>采集 · 创作 · 合成 · 转化</span></div>
      </div>
      <button className="startButton" onClick={() => setActive('dashboard')}>开始使用</button>
      <nav>
        {modules.filter(item => ['dashboard','monitor','lead'].includes(item.key)).map(item => <button key={item.key} className={active === item.key ? 'active' : ''} onClick={() => setActive(item.key)}>
          <span>{item.icon}</span><b>{item.title}</b><em>{item.tag}</em>
        </button>)}
        <button className={contentNavOpen ? 'groupHeader open' : 'groupHeader'} onClick={() => setContentNavOpen(!contentNavOpen)}>
          <span>生</span><b>内容生产</b><em>{contentNavOpen ? '收起' : '展开'}</em>
        </button>
        {contentNavOpen && contentNavKeys.map(key => modules.find(item => item.key === key)).filter(Boolean).map(item => <button key={item!.key} className={`subNav ${active === item!.key ? 'active' : ''}`} onClick={() => setActive(item!.key)}>
          <span>{item!.icon}</span><b>{item!.title}</b><em>{item!.tag}</em>
        </button>)}
        {modules.filter(item => ['strategy','competitor','trend','shooting','growth'].includes(item.key)).map(item => <button key={item.key} className={active === item.key ? 'active' : ''} onClick={() => setActive(item.key)}>
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

      {active === 'oneClick' && <section className="card modulePanel oneClickPanel">
        <div className="sectionHeader"><div><h2>一键生成中心</h2><p>不跳步骤，也能在一个窗口里生成和修改完整项目；同步后仍可去文案、配音、数字人、素材、剪辑等单独步骤精修。</p></div><Button busy={busy === '一键生成完整方案' ? busy : ''} label="一键生成方案" onClick={runOneClickGenerate} /></div>
        <div className="oneClickIntro">
          <strong>推荐顺序</strong>
          <span>先选/上传素材 → 填行业和目标客户 → 一键生成文案、配音分段、剪辑和图文方案。没有素材时也能先出方案，但演示建议先选素材。</span>
        </div>
        <div className="materialFirstPanel">
          <div>
            <strong>第一步：选择素材</strong>
            <p>{selectedMaterialAssets.length ? `已选 ${selectedMaterialAssets.length} 个素材，顺序会直接同步到剪辑。` : '还没选素材。演示时请先选素材，后面文案和剪辑会围绕素材生成。'}</p>
            {selectedMaterialAssets.length > 0 && <small>{selectedMaterialAssets.map((a, i) => `${i + 1}.${a.original_name || a.filename}`).slice(0, 5).join(' → ')}{selectedMaterialAssets.length > 5 ? '…' : ''}</small>}
          </div>
          <button className="btn soft" onClick={() => setActive('assets')}>{selectedMaterialAssets.length ? '调整素材顺序/截取' : '去选择素材'}</button>
        </div>
        <div className="grid2">
          <Field label="行业/产品"><input value={industry} onChange={e => setIndustry(e.target.value)} /></Field>
          <Field label="转化目标"><input value={conversionGoal} onChange={e => setConversionGoal(e.target.value)} /></Field>
          <Field label="目标客户"><input value={audience} onChange={e => setAudience(e.target.value)} /></Field>
          <Field label="核心卖点"><textarea value={sellingPoints} onChange={e => setSellingPoints(e.target.value)} /></Field>
        </div>
        <div className="grid3">
          <Field label="输出类型"><select value={oneClickOutputType} onChange={e => setOneClickOutputType(e.target.value)}><option value="digital_human">数字人口播</option><option value="mixed_video">素材混剪</option><option value="image_text">图文引流包</option><option value="all">视频 + 图文都要</option></select></Field>
          <Field label="素材方式"><select value={oneClickMaterialMode} onChange={e => setOneClickMaterialMode(e.target.value)}><option value="selected_assets">使用已选素材</option><option value="digital_human_only">只做数字人</option><option value="ai_image">AI 生成图文素材</option><option value="manual_later">先出方案，素材后补</option></select></Field>
          <div className="autoDurationCard"><span>生成长度</span><strong>自动跟随素材/配音</strong><em>{selectedMaterialAssets.length ? `已按 ${selectedMaterialAssets.length} 个素材顺序计算，不用手填。` : '配音生成后自动校准，不再手填秒数。'}</em></div>
        </div>
        <div className="grid2">
          <Field label="风格要求"><textarea value={style} onChange={e => setStyle(e.target.value)} /></Field>
          <Field label="一键生成要求"><textarea value={oneClickInstruction} onChange={e => setOneClickInstruction(e.target.value)} /></Field>
        </div>
        <div className="infoGrid">
          <div><strong>素材状态</strong><p>{selectedMaterialAssets.length ? selectedMaterialAssets.map((a, i) => `${i + 1}.${a.original_name || a.filename}`).join('、') : '暂无。可以先出方案；若要素材混剪，建议先去素材选择页排好顺序。'}<br />素材估算：{selectedAssetEstimatedSeconds || 0} 秒</p></div>
          <div><strong>模型框架</strong><p>主模型：{modelStatus?.ai_provider || health?.ai_provider || 'qwen'} / {modelStatus?.ai_text_model || health?.ai_text_model || '-'}<br />备用：{modelStatus?.ai_backup_provider || health?.ai_backup_provider || 'gemini'} / {modelStatus?.ai_backup_model || health?.ai_backup_model || '-'}</p></div>
          <div><strong>字幕/图文</strong><p>ASR：{modelStatus?.asr_provider || health?.asr_provider || '-'} / {modelStatus?.asr_model || health?.asr_model || '-'}<br />图片：{modelStatus?.image_provider || health?.image_provider || '-'} / {modelStatus?.image_model || health?.image_model || '-'}</p></div>
        </div>
        {oneClick && <div className="oneClickResult">
          <div className="resultBox"><h3>{oneClick.project_title}</h3><p>{oneClick.summary}</p><div className="buttonRow"><button className="btn soft" onClick={() => applyOneClickResult(oneClick)}>重新同步到步骤</button><button className="btn ghost" onClick={() => setActive('copy')}>去文案细改</button><button className="btn ghost" onClick={() => setActive('voice')}>去配音</button><button className="btn ghost" onClick={() => setActive(oneClickOutputType === 'mixed_video' ? 'assets' : 'digitalHuman')}>{oneClickOutputType === 'mixed_video' ? '去素材混剪' : '去数字人'}</button></div>{oneClick.warnings?.map(w => <div className="warn" key={w}>{w}</div>)}</div>
          <div className="grid2">
            <div className="miniResult"><h3>文案</h3><strong>{oneClick.copy.title}</strong><p>{oneClick.copy.hook}</p><pre>{oneClick.copy.script}</pre><div className="chips">{oneClick.copy.tags?.map(x => <Pill key={x}>{x}</Pill>)}</div></div>
            <div className="miniResult"><h3>配音分段</h3>{oneClick.voice_director?.segments?.map((seg, i) => <p key={`${seg.text}-${i}`}>第{i + 1}段：{seg.emotion} · {seg.text}</p>)}</div>
            <div className="miniResult"><h3>剪辑/拍摄</h3><p>{oneClick.edit_plan?.rhythm}</p>{oneClick.edit_plan?.timeline?.map(x => <p key={x}>· {x}</p>)}<h4>B-roll</h4>{oneClick.shooting_plan?.broll_list?.map(x => <Pill key={x} tone="purple">{x}</Pill>)}</div>
            <div className="miniResult"><h3>字幕/图文/发布</h3><p>{oneClick.subtitle?.template}</p><div className="chips">{oneClick.subtitle?.keywords?.map(k => <Pill key={k.word} tone="orange">{k.word} · {k.effect}</Pill>)}</div><h4>图文提示词</h4>{oneClick.image_prompts?.map(x => <p key={x}>· {x}</p>)}<h4>发布文案</h4><p>{oneClick.publish_description}</p></div>
          </div>
          <div className="editChatBox"><Field label="继续让 AI 修改当前完整方案"><textarea value={oneClickChatInput} onChange={e => setOneClickChatInput(e.target.value)} placeholder="例如：开头再狠一点；改成小红书图文；字幕关键词更强；结尾改成评论区留1。" /></Field><Button busy={busy === 'AI 修改一键方案' ? busy : ''} label="AI 修改并自动同步" onClick={runOneClickChat} kind="soft" /></div>
        </div>}
        {!oneClick && <Empty>填写行业、客户和目标后，点“一键生成方案”。生成后可在这里继续对话修改，也会自动同步到后续步骤。</Empty>}
      </section>}

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
        <div className="sectionHeader"><div><h2>第二步：文案生产</h2><p>文案不再手填时长，系统会按已选素材和最终配音自动决定长度。这里专注改标题、开头、口播稿和发布简介。</p></div></div>
        <div className="grid4"><Field label="素材状态"><input value={selectedMaterialIds.length ? `已选 ${selectedMaterialIds.length} 个素材` : '未选素材，建议先去素材选择'} readOnly /></Field><Field label="标题字数方向"><input value="短、狠、直给" readOnly /></Field><Field label="开头策略"><input value="痛点/反差/警告/结果" readOnly /></Field><Field label="当前风险"><input value={matchedBadWords.length ? `${matchedBadWords.length} 个敏感词` : '暂无明显风险'} readOnly /></Field></div>
        <div className="buttonRow"><Button busy={busy === '原创改写' ? busy : ''} label="第二步：仿写改写" onClick={rewrite} /><Button busy={busy === '生成文案' ? busy : ''} label="直接生成新文案" onClick={generateDirectCopy} kind="ghost" /><Button busy={busy === '文案细改' ? busy : ''} label="细改/优化文案" onClick={refineCopy} kind="soft" disabled={!currentScript} /><Button label="把当前文案放进知识库" onClick={() => openKnowledgeSave('手动保存当前文案', copy)} kind="ghost" disabled={!currentScript} /><Button label="继续去配音分段" onClick={() => setActive('voice')} kind="soft" disabled={!currentScript} /></div>
        <div className="flowSource"><strong>自动带入来源</strong><span>客户定位：{industry} / {audience}</span><span>同行采集：{extract?.summary ? shortText(extract.summary) : '暂无'}</span><span>数据库记忆：{memoryContext?.memory_enabled ? 'Supabase 已启用' : '本地调试记忆'}</span></div>
        <div className="copyEditor"><Field label="标题"><input value={copy.title} onChange={e => setCopy({ ...copy, title: e.target.value })} /></Field><Field label="黄金三秒钩子"><textarea value={copy.hook} onChange={e => setCopy({ ...copy, hook: e.target.value })} /></Field><Field label="完整口播稿"><textarea className="scriptArea" value={copy.script} onChange={e => setCopy({ ...copy, script: e.target.value })} placeholder="这里可以精修口播稿；选中文本后点“加入分段”。" /></Field><Field label="发布简介"><textarea value={copy.description} onChange={e => setCopy({ ...copy, description: e.target.value })} /></Field><Field label="细改要求"><input value={refineInstruction} onChange={e => setRefineInstruction(e.target.value)} /></Field></div>
        <div className="chips">{matchedBadWords.length ? matchedBadWords.map(x => <Pill key={x} tone="red">风险词：{x}</Pill>) : <Pill tone="green">违禁词初筛通过</Pill>}</div>
      </section>}

      {active === 'voice' && <section className="card modulePanel">
        <div className="sectionHeader"><div><h2>第四步：配音导演</h2><p>情绪改成纯中文选项；语速、音量范围加大。调完以后必须重新生成配音，剪辑会用配音时间轴自动对齐字幕。</p></div></div>
        <div className="grid4"><Field label="音色"><select value={voice} onChange={e => setVoice(e.target.value)}>{voices.map(v => <option key={v.id} value={v.id}>{v.name || v.id}</option>)}</select></Field><Field label="配音风格"><select value={voiceStyle} onChange={e => setVoiceStyle(e.target.value)}>{['老板压迫感','真实聊天感','短视频强钩子','销售转化感','案例讲述感','沉稳信任感'].map(x => <option key={x}>{x}</option>)}</select></Field><Field label="情绪强度"><select value={voiceIntensity} onChange={e => setVoiceIntensity(e.target.value)}>{['轻微','标准','强烈'].map(x => <option key={x}>{x}</option>)}</select></Field><div className="stackButtons"><Button busy={busy === '生成配音导演稿' ? busy : ''} label="生成配音导演稿" onClick={makeVoiceDirector} kind="ghost" disabled={!currentScript} /><Button busy={busy === '生成分段情绪配音' ? busy : ''} label="重新生成配音并校准时间轴" onClick={makeSegmentTTS} disabled={!currentScript} /></div></div>
        {voiceNotes.length > 0 && <div className="tips">{voiceNotes.map(x => <span key={x}>{x}</span>)}</div>}
        <div className="hintBox">说明：豆包音色对不同 voice_type 的“情绪词”支持不完全一致，真正生效的是语速/音量/停顿参数；本版把范围加大，并把字幕对齐改为读取配音实际分段时间。</div>
        <div className="buttonRow"><button className="addSegment" onClick={addVoiceSegment}>+ 手动添加空白分段</button><button className="addSegment" onClick={addSelectedScriptAsSegment}>+ 把选中文案加入分段</button></div>
        <div className="segments">{voiceSegments.map((seg, i) => <div className="segmentCard" key={i}><div className="segmentHead"><strong>第 {i + 1} 段 · {audio?.segments?.[i]?.duration?.toFixed?.(1) || segmentSeconds[i] || estimateSeconds(seg.text, seg.speed_ratio)} 秒</strong><div><button onClick={() => moveVoiceSegment(i, -1)}>↑</button><button onClick={() => moveVoiceSegment(i, 1)}>↓</button><button onClick={() => removeVoiceSegment(i)}>删除</button></div></div><textarea value={seg.text} onChange={e => updateVoiceSegment(i, { text: e.target.value })} /><div className="presetRow"><button onClick={() => applyVoicePreset(i, 'urgent')}>急迫提醒</button><button onClick={() => applyVoicePreset(i, 'emphasis')}>重点加重</button><button onClick={() => applyVoicePreset(i, 'calm')}>冷静信任</button><button onClick={() => applyVoicePreset(i, 'cta')}>结尾号召</button></div><div className="segmentGrid"><Field label="情绪"><select value={seg.emotion} onChange={e => updateVoiceSegment(i, { emotion: e.target.value })}>{emotionOptions.map(x => <option key={x}>{x}</option>)}</select></Field><Field label={`语速 ${seg.speed_ratio.toFixed(2)}x`}><input type="range" min="0.65" max="1.55" step="0.01" value={seg.speed_ratio} onChange={e => updateVoiceSegment(i, { speed_ratio: Number(e.target.value) })} /></Field><Field label={`音量 ${seg.volume_ratio.toFixed(2)}x`}><input type="range" min="0.45" max="2.2" step="0.01" value={seg.volume_ratio} onChange={e => updateVoiceSegment(i, { volume_ratio: Number(e.target.value) })} /></Field><Field label={`停顿 ${seg.pause_after_ms}ms`}><input type="range" min="0" max="2200" step="50" value={seg.pause_after_ms} onChange={e => updateVoiceSegment(i, { pause_after_ms: Number(e.target.value) })} /></Field></div></div>)}</div>
        {audio && <div className="mediaBox"><audio controls src={audio.file_url} /><a href={audio.file_url} target="_blank">下载配音</a><Pill tone="green">已生成 {audio.segments?.length || voiceSegments.length} 段时间轴</Pill>{audio.warning && <div className="warn">{audio.warning}</div>}</div>}
      </section>}

      {active === 'digitalHuman' && <section className="card modulePanel">
        <div className="sectionHeader"><div><h2>数字人工作台</h2><p>每次生成都会有版本号，方便区分文案/配音修改后的不同数字人片段。旧素材只在 R2 时，也会尽量直接用 R2 链接提交。</p></div><Button busy={busy === '生成数字人片段' || busy === '查询数字人结果' ? busy : ''} label={digitalHumanPrimaryLabel} onClick={hasRunningDigitalHumanTask ? () => checkDigitalHumanStatus(false) : makeDigitalHuman} disabled={!hasRunningDigitalHumanTask && (!audio?.file_name || !digitalHumanAvatarId || !digitalHumanConsent)} /></div>
        <div className="grid3">
          <Field label="数字人形象素材" hint="建议上传本人授权的正脸/半身照片，或 5-15 秒自然说话视频。"><select value={digitalHumanAvatarId} onChange={e => setDigitalHumanAvatarId(e.target.value)}><option value="">选择已上传照片/视频</option>{assets.map(a => <option key={a.id} value={a.id}>{a.kind} · {a.original_name || a.filename}</option>)}</select></Field>
          <Field label="动作参考视频（可选）" hint="后续接 LivePortrait/MuseTalk 时可参考表情和头部动作。"><select value={digitalHumanDriverId} onChange={e => setDigitalHumanDriverId(e.target.value)}><option value="">不用动作参考</option>{assets.filter(a => a.kind === 'video').map(a => <option key={a.id} value={a.id}>{a.original_name || a.filename}</option>)}</select></Field>
          <Field label="数字人引擎" hint="可选火山即梦/OmniHuman，或使用上传素材直接合成。"><select value={digitalHumanEngine} onChange={e => setDigitalHumanEngine(e.target.value)}><option value="auto">自动</option><option value="preview">静态预览/素材合成</option><option value="jimeng">火山即梦/OmniHuman</option><option value="webhook">外部 Webhook/API</option><option value="sadtalker">SadTalker</option><option value="musetalk">MuseTalk</option><option value="wav2lip">Wav2Lip</option><option value="liveportrait">LivePortrait</option></select></Field>
          {digitalHumanEngine === 'jimeng' && <Field label="即梦模型" hint="模拟真人优先选 OmniHuman1.5；普通视频生成可用视频3.0。"><select value={digitalHumanJimengModel} onChange={e => setDigitalHumanJimengModel(e.target.value)}><option value="omnihuman15">OmniHuman1.5（单图+音频真人口播）</option><option value="quick">数字人快速模式</option><option value="video30">即梦视频生成3.0（图生视频）</option></select></Field>}
        </div>
        <label className="checkline"><input type="checkbox" checked={digitalHumanConsent} onChange={e => setDigitalHumanConsent(e.target.checked)} /> 我确认已获得本人形象和声音授权，仅用于合法商业内容。</label>
        <div className="infoGrid"><div><strong>当前输入</strong><p>数字人版本：#{digitalHumanVersion}<br />形象素材：{digitalHumanAvatarId || '未选择'}<br />配音音频：{audio?.file_name || '未生成'}<br />脚本：{shortText(currentScript || '', 90) || '未生成'}</p></div><div><strong>接入建议</strong><p>需要真人口型同步时选择“火山即梦/OmniHuman”；旧素材如果存在 R2，刷新素材库后也能选择使用。</p></div></div>
        {hasRunningDigitalHumanTask && <div className="warn strongWarn">已有任务正在火山侧排队/生成中。请不要再次点击提交，否则会触发 429 并发限制；等待当前任务完成或点击“查询当前数字人任务”。</div>}
        {digitalHuman && <div className="resultBox"><h3>数字人 #{digitalHumanVersion} 结果</h3><p>{digitalHuman.message}</p><div className="resultMeta"><Pill tone={digitalHuman.video_url ? 'green' : digitalHuman.status === 'failed' ? 'red' : 'orange'}>状态：{digitalHuman.status || 'running'}</Pill>{digitalHumanLastChecked && <Pill tone="blue">最近查询：{digitalHumanLastChecked}</Pill>}{digitalHumanPollCount > 0 && <Pill tone="purple">已查询 {digitalHumanPollCount} 次</Pill>}</div>{digitalHuman.job_id && <p className="muted">任务 ID：{digitalHuman.job_id}<br />查询模型：{getDigitalHumanTaskModel(digitalHuman, digitalHumanJimengModel)}</p>}{digitalHuman.job_id && !digitalHuman.video_url && <div className="warn">OmniHuman1.5 是排队生成任务，不是实时接口。系统会每 20 秒自动查一次；如果超过 20-30 分钟仍无结果，请去火山控制台 / API Explorer 用这个 task_id 查询任务详情。</div>}{digitalHuman.warnings?.map(w => <div className="warn" key={w}>{w}</div>)}{digitalHuman.job_id && !digitalHuman.video_url && <div className="buttonRow"><button className="btn soft" onClick={() => checkDigitalHumanStatus(false)} disabled={busy === '查询数字人结果'}>{busy === '查询数字人结果' ? '查询中…' : '立即查询数字人结果'}</button><button className="btn ghost danger" onClick={clearDigitalHumanTask}>清除当前任务</button></div>}{digitalHuman.raw && <details className="rawBox"><summary>查看火山原始返回</summary><pre>{JSON.stringify(digitalHuman.raw, null, 2).slice(0, 2600)}</pre></details>}{digitalHuman.video_url && <video controls src={digitalHuman.video_url} className="previewVideo" />}{digitalHuman.video_url && <a className="download" href={digitalHuman.video_url} target="_blank">下载/打开数字人 #{digitalHumanVersion} 片段</a>}</div>}
      </section>}

      {active === 'assets' && <section className="card modulePanel">
        <div className="sectionHeader"><div><h2>第一步：素材选择与截取</h2><p>先选素材，再生成文案。图片可设置停留秒数，视频可预览并截取开始/结束时间；素材顺序会直接同步到剪辑。</p></div></div>
        <div className={`uploadDrop ${isDraggingAssets ? 'dragging' : ''} ${busy === '上传素材' ? 'uploading' : ''}`} onDragOver={onAssetDragOver} onDragLeave={onAssetDragLeave} onDrop={onAssetDrop} aria-busy={busy === '上传素材'}>
          <div className="uploadIcon">↑</div>
          <div className="uploadCopy">
            <strong>{busy === '上传素材' ? '正在上传到素材库…' : '拖入图片 / 视频，或点击选择文件'}</strong>
            <span>支持 JPG、PNG、WEBP、MP4、MOV，多选上传后会自动进入 R2，并默认加入本次素材顺序。</span>
            <div className="uploadHints"><em>图片：可设置停留秒数</em><em>视频：可预览并截取片段</em><em>顺序：下方可拖前/上移下移</em></div>
          </div>
          <label className={`uploadPick ${busy === '上传素材' ? 'disabled' : ''}`}>
            选择文件
            <input type="file" multiple accept="image/*,video/*" onChange={e => { handleUpload(e.target.files); e.currentTarget.value = '' }} disabled={busy === '上传素材'} />
          </label>
        </div>
        <div className="assetToolbar">
          <input placeholder="搜索文件名" value={assetSearch} onChange={e => setAssetSearch(e.target.value)} />
          <select value={assetKindFilter} onChange={e => setAssetKindFilter(e.target.value as any)}><option value="all">全部类型</option><option value="video">只看视频</option><option value="image">只看图片</option></select>
          <select value={assetTimeFilter} onChange={e => setAssetTimeFilter(e.target.value as any)}><option value="all">全部时间</option><option value="today">今天上传</option><option value="7d">近 7 天</option><option value="30d">近 30 天</option></select>
          <select value={assetSort} onChange={e => setAssetSort(e.target.value as any)}><option value="new">最新优先</option><option value="old">最早优先</option><option value="size_desc">文件从大到小</option><option value="size_asc">文件从小到大</option><option value="name">名称排序</option></select>
          <button className="btn ghost" onClick={() => { setAssetSearch(''); setAssetKindFilter('all'); setAssetTimeFilter('all'); setAssetSort('new') }}>重置</button>
        </div>
        <div className="assetStats"><Pill tone="blue">自有素材 {materialAssets.length}</Pill><Pill tone="green">已选 {selectedMaterialIds.length}</Pill><Pill tone="purple">采集视频 {collectedVideos.length}</Pill>{selectedMaterialAssets.length > 0 && <span>已选顺序：{selectedMaterialAssets.map(a => a.original_name || a.filename).slice(0, 4).join(' → ')}{selectedMaterialAssets.length > 4 ? ` 等 ${selectedMaterialAssets.length} 个` : ''}</span>}</div>
        <div className="grid2 assetGridWrap"><div><h3>自有素材库</h3><div className="assetCards">{filteredMaterialAssets.length === 0 && <Empty>没有匹配的素材。可以拖动上传或调整筛选条件。</Empty>}{filteredMaterialAssets.map(a => <div key={a.id} className={`assetCard ${selectedMaterialIds.includes(a.id) ? 'selected' : ''}`}><button className="assetPreview" onClick={() => window.open(a.url, '_blank')}>{a.kind === 'video' ? <video src={a.url} muted onLoadedMetadata={e => setAssetDurations(prev => ({ ...prev, [a.id]: readMediaDuration(e, 0) }))} /> : <img src={a.url} alt={a.original_name || a.filename} />}</button><div className="assetMeta"><strong title={a.original_name || a.filename}>{a.original_name || a.filename}</strong><span>{a.kind === 'video' ? '视频' : '图片'} · {formatBytes(a.size_bytes)} · {new Date(a.created_at).toLocaleDateString()}</span></div><div className="assetActions"><button className={selectedMaterialIds.includes(a.id) ? 'mini active' : 'mini'} onClick={() => toggleMaterial(a.id)}>{selectedMaterialIds.includes(a.id) ? '已选' : '选择'}</button><a className="mini" href={a.url} target="_blank">预览</a><button className="mini danger" onClick={() => removeAsset(a)}>删除</button></div></div>)}</div></div><div><h3>采集视频库</h3><div className="assetList">{collectedVideos.length === 0 && <Empty>暂时没有采集到视频。</Empty>}{collectedVideos.map(a => <div key={a.id} className={`assetRow collected ${selectedReferenceAssetId === a.id ? 'selected' : ''}`}><button onClick={() => setSelectedReferenceAssetId(a.id)}>作为参考</button><span>{a.original_name || a.filename}</span><em>{formatBytes(a.size_bytes)}</em><button className="mini danger" onClick={() => removeAsset(a)}>删除</button></div>)}</div></div></div>
        <div className="selectedTimeline"><h3>已选素材顺序 / 截取设置</h3>{selectedMaterialAssets.length === 0 && <Empty>先选择素材。剪辑会按照这里的顺序出现，不会再因为多段素材丢失而只剩纯文字背景。</Empty>}{selectedMaterialAssets.map((asset, index) => { const cfg = getClipSetting(asset, index); const maxDur = Math.max(1, assetDurations[asset.id] || 60); return <div key={asset.id} className="selectedClip"><div className="clipPreview">{asset.kind === 'video' ? <video controls src={asset.url} onLoadedMetadata={e => setAssetDurations(prev => ({ ...prev, [asset.id]: readMediaDuration(e, prev[asset.id] || 0) }))} /> : <img src={asset.url} />}</div><div className="clipControls"><div className="segmentHead"><strong>{index + 1}. {asset.original_name || asset.filename}</strong><div><button onClick={() => moveSelectedMaterial(index, -1)}>↑</button><button onClick={() => moveSelectedMaterial(index, 1)}>↓</button><button onClick={() => toggleMaterial(asset.id)}>移除</button></div></div>{asset.kind === 'image' ? <Field label={`图片停留 ${cfg.image_seconds.toFixed(1)} 秒`}><input type="range" min="0.8" max="8" step="0.1" value={cfg.image_seconds} onChange={e => updateClipSetting(asset.id, { image_seconds: Number(e.target.value) })} /></Field> : <div className="trimGrid"><Field label={`开始 ${cfg.video_start.toFixed(1)}s`}><input type="range" min="0" max={maxDur} step="0.1" value={cfg.video_start} onChange={e => updateClipSetting(asset.id, { video_start: Math.min(Number(e.target.value), cfg.video_end && cfg.video_end > 0 ? cfg.video_end - 0.3 : maxDur) })} /></Field><Field label={`结束 ${cfg.video_end ? cfg.video_end.toFixed(1) : '自动'}s`}><input type="range" min="0" max={maxDur} step="0.1" value={cfg.video_end || Math.min(maxDur, cfg.video_start + 3)} onChange={e => updateClipSetting(asset.id, { video_end: Number(e.target.value) })} /></Field><span>截取约 {Math.max(0.5, (cfg.video_end || Math.min(maxDur, cfg.video_start + 3)) - cfg.video_start).toFixed(1)} 秒</span></div>}<small>顺序会同步到剪辑合成；如果 R2 旧素材本地丢失，后端会先下载再合成。</small></div></div>})}</div>
        <div className="resultBox"><h3>素材匹配建议</h3><p>图片：每张建议 2-4 秒；视频：每段截 2-5 秒。人物口播主体在画面中间时，字幕建议放底部安全区，避免挡脸。</p></div>
      </section>}

      {active === 'shooting' && <section className="card modulePanel">
        <div className="sectionHeader"><div><h2>运营拍摄任务</h2><p>把文案变成老板、员工能直接照着拍的镜头清单、B-roll 清单和提词器。</p></div><Button busy={busy === '生成运营拍摄任务' ? busy : ''} label="生成拍摄任务单" onClick={makeShootingPlan} disabled={!currentScript} /></div>
        {shootingPlan ? <div className="resultBox"><h3>{shootingPlan.summary}</h3><div className="shotTable">{shootingPlan.shot_tasks?.map((task, i) => <div className="shotRow" key={`${task.scene}-${i}`}><span>{task.priority}</span><strong>{task.scene}</strong><em>{task.duration}</em><p>{task.content}</p><small>{task.camera}</small><small>{task.props}</small></div>)}</div><div className="splitGrid"><div><h4>B-roll 补拍</h4>{shootingPlan.broll_list?.map(x => <p key={x}>· {x}</p>)}</div><div><h4>提词器短句</h4>{shootingPlan.teleprompter?.map(x => <p key={x}>· {x}</p>)}</div><div><h4>拍摄检查</h4>{shootingPlan.checklist?.map(x => <p key={x}>· {x}</p>)}</div></div></div> : <Empty>先生成文案，再生成拍摄任务单。</Empty>}
      </section>}

      {active === 'video' && <section className="card modulePanel">
        <div className="sectionHeader"><div><h2>第六步：剪辑合成 / 字幕烧录</h2><p>这里直接调字幕位置和素材顺序。时长跟配音走，素材按已选顺序自动铺满；字幕优先使用配音分段时间轴，减少音画不同步。</p></div><Button busy={busy === '合成视频并烧字幕' ? busy : ''} label="生成视频并下载 MP4" onClick={composeVideo} disabled={!currentScript} /></div>
        <div className="grid4"><Field label="字幕字号"><input type="number" min="12" max="36" value={subtitleSize} onChange={e => setSubtitleSize(Number(e.target.value || 18))} /></Field><Field label="字幕位置"><select value={subtitlePosition} onChange={e => setSubtitlePosition(e.target.value as any)}><option value="bottom_safe">底部安全区，不挡脸</option><option value="middle_low">中下方，大字口播</option><option value="center">居中强调，慎用</option></select></Field><Field label={`离底部 ${subtitleMarginV}px`}><input type="range" min="20" max="260" step="5" value={subtitleMarginV} onChange={e => setSubtitleMarginV(Number(e.target.value))} /></Field><Field label="字幕颜色"><input type="color" value={subtitleColor} onChange={e => setSubtitleColor(e.target.value)} /></Field></div>
        <div className="hintBox">字幕对齐规则：优先用“重新生成配音并校准时间轴”得到的分段时间；没有时间轴时才按文案长度估算。演示前建议先重新生成配音一次。</div>
        <div className="timelineEditor"><h3>配音分段 / 转场参考</h3>{voiceSegments.length === 0 && <Empty>先生成配音导演稿，或手动添加分段。</Empty>}{voiceSegments.map((seg, i) => <div className="timelineRow" key={i}><span>第{i + 1}段</span><input type="number" min="1" max="60" step="0.5" value={audio?.segments?.[i]?.duration || segmentSeconds[i] || estimateSeconds(seg.text, seg.speed_ratio)} onChange={e => setSegmentSeconds(prev => ({ ...prev, [i]: Number(e.target.value) }))} /><select value={segmentTransitions[i] || '叠化'} onChange={e => setSegmentTransitions(prev => ({ ...prev, [i]: e.target.value }))}><option>叠化</option><option>虚化</option><option>快切</option><option>推近</option><option>闪白</option></select><em>{seg.text.slice(0, 28)}...</em></div>)}</div>
        <div className="selectedTimeline compact"><h3>本次合成素材顺序</h3>{selectedMaterialAssets.length === 0 ? <Empty>未选择素材，会自动使用前几个素材；建议先去素材选择页确认顺序和截取区间。</Empty> : selectedMaterialAssets.map((asset, index) => { const cfg = getClipSetting(asset, index); return <div key={asset.id} className="assetRow"><span>{index + 1}</span><strong>{asset.original_name || asset.filename}</strong><em>{asset.kind === 'image' ? `${cfg.image_seconds.toFixed(1)}秒` : `${cfg.video_start.toFixed(1)}-${cfg.video_end ? cfg.video_end.toFixed(1) : '自动'}秒`}</em><button className="mini" onClick={() => setActive('assets')}>调整</button></div>})}</div>
        {video && <div className="videoGrid"><video controls src={video.video_url} /><div className="downloadPanel"><a className="download" href={video.video_url} target="_blank">下载视频 MP4</a>{video.subtitle_url && <a href={video.subtitle_url} target="_blank">下载字幕 SRT</a>}{video.audio_url && <a href={video.audio_url} target="_blank">下载音频</a>}{video.warnings?.map(w => <div className="warn" key={w}>{w}</div>)}</div></div>}
        <div className="editChatBox"><Field label="AI + 插件剪辑指令"><textarea value={editInstruction} onChange={e => setEditInstruction(e.target.value)} placeholder="例如：去掉开头2秒、整体加速1.1倍、重新加字幕、转成9:16。" /></Field><Button busy={busy === 'AI + 插件修改视频' ? busy : ''} label="AI + 插件修改视频" onClick={chatEditVideo} kind="ghost" disabled={!currentVideoName} />{editChat.map((msg, i) => <div className="chatMsg" key={i}><strong>AI：</strong>{msg.assistant_message}<p>{msg.summary}</p><div className="chips">{msg.actions?.map(x => <Pill key={x}>{x}</Pill>)}</div>{msg.new_video_url && <a href={msg.new_video_url} target="_blank">打开修改后视频</a>}{msg.warnings?.map(w => <div className="warn" key={w}>{w}</div>)}</div>)}</div>
      </section>}

      {active === 'subtitleCover' && <section className="card modulePanel visualPanel">
        <div className="sectionHeader"><div><h2>第六步：字幕 / 封面 / 图文引流</h2><p>这里分清楚：封面负责视频点击；图文引流负责小红书/抖音图文/朋友圈获客，可以直接生成 3-8 张收藏型图文。</p></div><div className="stackButtons"><Button busy={busy === '智能字幕重点' ? busy : ''} label="智能识别重点字幕" onClick={makeSubtitleAI} disabled={!currentScript} kind="ghost" /><Button busy={busy === '生成图文引流包' ? busy : ''} label="生成图文引流包" onClick={makeGraphicPost} /></div></div>
        <div className="visualTabs"><span>字幕</span><span>封面</span><span>图文素材</span></div>
        <div className="grid4"><Field label="字幕字号"><input type="number" value={subtitleSize} onChange={e => setSubtitleSize(Number(e.target.value || 58))} /></Field><Field label="字幕颜色"><input type="color" value={subtitleColor} onChange={e => setSubtitleColor(e.target.value)} /></Field><Field label="重点词"><input value={subtitleHighlight} onChange={e => setSubtitleHighlight(e.target.value)} /></Field><Field label="封面大标题"><input value={copy.title || coverStyle} onChange={e => setCopy({ ...copy, title: e.target.value })} placeholder="例如：海外买房避坑指南" /></Field></div>
        <div className="coverBuilder">
          <div>
            <h3>封面生成方式</h3>
            <div className="coverModeGrid">
              {[['asset','从素材截一张图'],['digitalHuman','从数字人视频截帧'],['aiImage','AI 精美背景图'],['clean','无素材纯标题']].map(([value,label]) => <button key={value} className={coverSourceMode === value ? 'selected' : ''} onClick={() => setCoverSourceMode(value as any)}>{label}</button>)}
            </div>
            {coverSourceMode === 'asset' && <Field label="选择封面素材" hint="建议选真实人物/项目环境/客户场景图，不要用纯卡片。"><select value={coverSourceAssetId} onChange={e => setCoverSourceAssetId(e.target.value)}><option value="">自动用已选素材第一张</option>{materialAssets.map(a => <option key={a.id} value={a.id}>{a.kind} · {a.original_name || a.filename}</option>)}</select></Field>}
            {coverSourceMode === 'digitalHuman' && <div className="hintBox">会优先用当前数字人视频截帧。当前数字人：{digitalHuman?.video_name || digitalHuman?.job_id || '暂无'}</div>}
            {coverSourceMode === 'aiImage' && <div className="aiImageBox"><Field label="Seedream 图片提示词"><textarea value={imagePrompt} onChange={e => setImagePrompt(e.target.value)} /></Field><Button busy={busy === 'AI 生成精美背景图' ? busy : ''} label="AI 生成精美背景图" onClick={makeAiImage} kind="soft" /></div>}
            <div className="buttonRow"><Button busy={busy === '生成封面' ? busy : ''} label="生成：素材截图 + 大标题封面" onClick={makeCover} /><Button label="去平台发布" onClick={() => setActive('publish')} kind="ghost" /></div>
          </div>
          <div className="coverPreviewStack">
            {generatedImage && <div className="coverPreview compact"><img src={generatedImage.image_url} /><div><h3>AI 背景图已生成</h3><p>{generatedImage.model}</p><a className="download" href={generatedImage.image_url} target="_blank">打开图片</a>{generatedImage.warnings?.map(w => <div className="warn" key={w}>{w}</div>)}</div></div>}
            {cover ? <div className="coverPreview"><img src={cover.cover_url} /><div><h3>封面已生成</h3><p>{cover.prompt}</p><a className="download" href={cover.cover_url} target="_blank">下载封面</a></div></div> : <Empty>封面建议：真实画面做底，大标题 6-12 字，副标题一行即可。不要再用手机壳/PPT 卡片。</Empty>}
          </div>
        </div>
        <div className="graphicPostPanel">
          <div className="sectionHeader mini"><div><h3>图文引流包</h3><p>这个不是封面，是给小红书、抖音图文、朋友圈发出去引流用的多张图。首图强钩子，中间讲重点，最后引导私信。</p></div><Button busy={busy === '生成图文引流包' ? busy : ''} label="生成 3-8 张图文" onClick={makeGraphicPost} kind="soft" /></div>
          <div className="grid4"><Field label="发布平台"><select value={graphicPlatform} onChange={e => setGraphicPlatform(e.target.value)}><option value="xiaohongshu">小红书 / 收藏图文</option><option value="douyin">抖音图文 9:16</option><option value="wechat">朋友圈 / 视频号图文</option></select></Field><Field label="图片张数"><input type="number" min="3" max="8" value={graphicSlideCount} onChange={e => setGraphicSlideCount(Number(e.target.value || 5))} /></Field><Field label="背景来源"><select value={graphicBackgroundMode} onChange={e => setGraphicBackgroundMode(e.target.value as any)}><option value="asset">用素材/旧 R2 图片</option><option value="ai">Seedream 生成精美背景</option><option value="generated">使用上方已生成 AI 图</option><option value="clean">系统高级背景</option></select></Field><Field label="素材图"><select value={coverSourceAssetId} onChange={e => setCoverSourceAssetId(e.target.value)}><option value="">自动选一张图片素材</option>{materialAssets.filter(a => a.kind === 'image').map(a => <option key={a.id} value={a.id}>{a.original_name || a.filename}</option>)}</select></Field></div>
          <Field label="图文背景提示词" hint="如果选择 Seedream 生成背景，这里用来生成精美行业视觉；文字由系统叠加，避免 AI 乱写中文。"><textarea value={imagePrompt} onChange={e => setImagePrompt(e.target.value)} /></Field>
          {graphicPost ? <div className="graphicPreview"><div className="miniResult"><h3>{graphicPost.package_title}</h3><p>{graphicPost.publish_description}</p>{graphicPost.checklist?.map(x => <p key={x}>· {x}</p>)}{graphicPost.warnings?.map(w => <div className="warn" key={w}>{w}</div>)}</div><div className="graphicGrid">{graphicPost.images.map((img, i) => <a key={img.image_name} href={img.image_url} target="_blank" className="graphicCard"><img src={img.image_url} /><strong>{i + 1}. {img.role}</strong><span>{img.title}</span></a>)}</div></div> : <Empty>图文引流建议：不要做成视频封面；要做成“首图吸引 + 多页干货 + 结尾私信”的收藏型图片包。</Empty>}
        </div>

        {subtitleAI && <div className="resultBox"><h3>{subtitleAI.template}</h3><div className="chips">{subtitleAI.keywords?.map(k => <Pill key={k.word} tone="orange">{k.word} · {k.effect}</Pill>)}</div><div className="splitGrid"><div><h4>字幕建议</h4>{subtitleAI.srt_tips?.map(x => <p key={x}>· {x}</p>)}</div><div><h4>封面大字</h4>{subtitleAI.cover_text_options?.map(x => <p key={x}>· {x}</p>)}</div><div><h4>已写入重点词</h4><p>{subtitleHighlight}</p></div></div></div>}
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

export default function App() {
  return <AppErrorBoundary><AppInner /></AppErrorBoundary>
}
