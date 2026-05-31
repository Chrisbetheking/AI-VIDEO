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
  HeatRadarRunResponse,
  HeatRadarRewriteResponse,
  HeatRadarAccountAuditResponse,
  OneClickGenerateResponse,
  ModelStatusResponse,
  TTSResponse,
  TTSVoice,
  VideoEditChatResponse,
  VoiceDirectorResponse,
  VoiceSegment,
  API_BASE,
  apiGet,
  apiPost,
  apiDelete,
  getCollectorStatus,
  uploadCollectorCookies,
  uploadAssets,
  deleteAsset,
  listJobs,
  JobItem
} from './api'

type ModuleKey = 'dashboard' | 'monitor' | 'lead' | 'oneClick' | 'collector' | 'copy' | 'voice' | 'digitalHuman' | 'assets' | 'video' | 'subtitleCover' | 'publish' | 'strategy' | 'competitor' | 'trend' | 'shooting' | 'growth'
type AssetClipSetting = { order: number; image_seconds: number; video_start: number; video_end: number }
type AssetFolderKey = 'all' | 'self' | 'provided' | 'image' | 'collected' | 'ai'

type LeadMagnetReport = {
  id: string
  title: string
  keyword: string
  subtitle: string
  audience: string
  promise: string
  outline: string[]
  landingTitle: string
  landingSubtitle: string
  cta: string
  replyScript: string
  shootingIdea: string
}


type HeatRadarAccount = {
  id: string
  name: string
  platform: string
  url: string
  tags: string
  notes: string
  pinned: boolean
  created_at: string
}

type HeatRadarSnapshot = {
  id: string
  date: string
  account_id: string
  account_name: string
  platform: string
  topic: string
  signal: string
  score: number
  intent: string
  source_url: string
  recommended_action: string
  lead_magnet: string
  buyer_dimensions?: string[]
  reason?: string
  decision?: string
}


type CollectorProgressEvent = {
  id?: string
  run_id?: string
  stage?: string
  level?: string
  message?: string
  account_name?: string
  account_url?: string
  video_title?: string
  video_url?: string
  error_detail?: string
  created_at?: string
  progress?: Record<string, any>
  raw?: Record<string, any>
}

type CollectorProgressState = {
  ok: boolean
  run: Record<string, any>
  events: CollectorProgressEvent[]
  commands: Record<string, any>[]
}

type DigitalHumanProviderOption = {
  id: string
  name: string
  priority: number
  stage: string
  cost_note: string
  best_for: string
  integration: string
  risk: string
  enabled: boolean
}

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


function ReportPreview({ reports, activeIndex, onSelect, onCopy, onUse, copyStatus, radarGroups, shootingTasks }: {
  reports: LeadMagnetReport[]
  activeIndex: number
  onSelect: (index: number) => void
  onCopy: () => void
  onUse: (report?: LeadMagnetReport) => void
  copyStatus: string
  radarGroups: { highIntent: string[]; contentHooks: string[]; broadTraffic: string[] }
  shootingTasks: { title: string; hook: string; shots: string[]; cta: string }[]
}) {
  const report = reports[Math.min(activeIndex, Math.max(0, reports.length - 1))]
  if (!report) return <div className="reportWorkbench"><Empty>先在行业档案里配置私域资料包，比如《避坑报告》《预算测算表》《择校清单》。</Empty></div>
  return <div className="reportWorkbench">
    <div className="reportHead">
      <div>
        <span>网页资料包 / 获客报告</span>
        <h3>微信未接入也能先演示承接链路</h3>
        <p>把报告做成网页预览页，视频/图文结尾引导私信关键词；后续接微信时直接把这里的报告换成自动发送。</p>
      </div>
      <div className="reportActions">
        <button className="btn ghost" onClick={onCopy}>{copyStatus || '复制报告页文案'}</button>
        <button className="btn primary" onClick={() => onUse(report)}>用这个报告生成内容</button>
      </div>
    </div>
    <div className="reportGrid">
      <div className="reportList">
        {reports.map((item, index) => <button key={item.id} className={index === activeIndex ? 'active' : ''} onClick={() => onSelect(index)}>
          <b>{item.title}</b>
          <span>私信关键词：{item.keyword}</span>
        </button>)}
      </div>
      <div className="reportLandingMock">
        <div className="mockTop"><span>网页报告预览</span><em>未接微信时临时承接</em></div>
        <h2>{report.landingTitle}</h2>
        <p>{report.landingSubtitle}</p>
        <div className="reportOutline">{report.outline.map((x, i) => <div key={x}><strong>{i + 1}</strong><span>{x}</span></div>)}</div>
        <div className="reportCta"><b>{report.cta}</b><small>{report.replyScript}</small></div>
      </div>
      <div className="advisorCards">
        <div><h4>关键词雷达</h4><p><b>高意向：</b>{radarGroups.highIntent.join(' / ') || '暂无'}</p><p><b>内容钩子：</b>{radarGroups.contentHooks.join(' / ') || '暂无'}</p><p><b>泛流量：</b>{radarGroups.broadTraffic.join(' / ') || '暂无'}</p></div>
        <div><h4>今天拍什么</h4>{shootingTasks.slice(0, 3).map(task => <p key={task.title}>· {task.title}<br /><small>{task.hook}</small></p>)}</div>
        <div><h4>拍摄提示</h4><p>{report.shootingIdea}</p></div>
      </div>
    </div>
  </div>
}


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

function formatCollectorEventLine(ev: CollectorProgressEvent, index = 0) {
  const stage = safeText(ev.stage, 'event').toUpperCase()
  const title = safeText(ev.video_title || ev.message || ev.account_name, '-')
  const account = safeText(ev.account_name, '')
  const detail = safeText(ev.error_detail || ev.message || ev.video_url || ev.created_at, '')
  const response = (ev.raw as any)?.response || {}
  const review = response?.review || (ev.raw as any)?.review || {}
  const decision = safeText(review?.decision || response?.decision, '')
  const score = review?.score ?? response?.score
  const reason = safeText(review?.reason || response?.reason || response?.summary, '')
  const warnings = Array.isArray(response?.warnings) ? response.warnings.filter(Boolean).slice(0, 2).join('；') : ''
  const prefix = `${index + 1}. ${stage}`
  if (ev.level === 'error') return `${prefix}｜失败：${title}｜${detail}`
  if (stage.includes('VIDEO_ANALYZED') || stage.includes('VIDEO_SELECTED') || stage.includes('VIDEO_ARCHIVED')) {
    const verdict = decision ? `${decision}${score !== undefined && score !== null ? ` / ${score}分` : ''}` : '已返回分析'
    return `${prefix}｜${account ? account + '｜' : ''}${title}｜${verdict}${reason ? `｜原因：${reason}` : ''}${warnings ? `｜提醒：${warnings}` : ''}`
  }
  if (stage.includes('VIDEOS_FOUND')) return `${prefix}｜${detail || title}`
  if (stage.includes('ACCOUNT')) return `${prefix}｜${account || title}｜${detail}`
  if (stage.includes('DELAY')) return `${prefix}｜${detail || title}`
  if (stage.includes('RUN_FINISHED')) return `${prefix}｜本轮完成｜${detail || title}`
  return `${prefix}｜${account ? account + '｜' : ''}${title}${detail && detail !== title ? `｜${detail}` : ''}`
}

function safeProjectDuration(...values: unknown[]) {
  for (const value of values) {
    const n = safeNumber(value, 0)
    if (n > 0) return Math.round(Math.min(180, Math.max(5, n)))
  }
  return 12
}


function loadLocalJson<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(key)
    if (!raw) return fallback
    const parsed = JSON.parse(raw)
    return parsed ?? fallback
  } catch {
    return fallback
  }
}

function makeId(prefix = 'id') {
  return `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`
}

function todayKey() {
  return new Date().toISOString().slice(0, 10)
}

function limitText(value: string, limit = 980) {
  const clean = safeText(value).replace(/\s+/g, ' ').trim()
  return clean.length > limit ? clean.slice(0, limit - 1) + '…' : clean
}


function normalizeAssetFolder(raw: any, kind?: string, filename?: string): AssetFolderKey {
  const value = safeText(raw).toLowerCase().replace(/[-\s]/g, '_')
  const name = safeText(filename).toLowerCase()
  if (['self', 'own', 'shot', 'my', 'mine', '自己拍的素材'].includes(value)) return 'self'
  if (['provided', 'client', 'other', 'others', '别人提供的素材', '客户提供'].includes(value)) return 'provided'
  if (['image', 'images', '图片', '图片素材'].includes(value)) return 'image'
  if (['collected', 'crawler', '采集', '采集视频'].includes(value) || name.startsWith('collected_')) return 'collected'
  if (['ai', 'generated', 'ai_image', 'ai生成图'].includes(value) || name.startsWith('ai_image_') || name.startsWith('graphic_') || name.startsWith('cover_')) return 'ai'
  if (kind === 'image') return 'image'
  return 'self'
}

function assetFolderLabel(folder: string | undefined, kind?: string) {
  const f = normalizeAssetFolder(folder, kind)
  return f === 'self' ? '自己拍的素材' : f === 'provided' ? '别人提供的素材' : f === 'image' ? '图片素材' : f === 'collected' ? '采集视频' : f === 'ai' ? 'AI生成图' : '素材'
}

function imagePromptForVisualOnly(prompt: string) {
  return safeText(prompt)
    .replace(/不要有?文字|不要加文字|不要中文|不要英文|无文字|没有文字|不带文字|no text|without text|no words/gi, '')
    .replace(/\s+/g, ' ')
    .trim()
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
    created_at: safeText(raw?.created_at, new Date().toISOString()),
    folder: normalizeAssetFolder(raw?.folder, kind, filename),
    source_type: safeText(raw?.source_type, '')
  }
}

const emptyCopy: GeneratedCopy = { title: '', hook: '', script: '', description: '', tags: [], shots: [], kb_refs: [] }

const malaysiaProfilePreset = {
  industry: '马来西亚房产置业 · 第二家园 · 国际学校',
  businessPositioning: '中国人在马来西亚房产置业，重点围绕第二家园身份、海外资产配置、国际学校和长期生活规划。',
  audience: '有海外置业、第二家园身份、子女教育、养老度假和资产配置需求的华人家庭与企业主',
  leadRegion: '中国各城市华人高净值家庭、企业主、留学家庭、养老度假人群、海外生活规划人群',
  conversionGoal: '评论关键词 / 私信咨询 / 加微信领取报告 / 需求筛选 / 预约顾问沟通',
  sellingPoints: '马来西亚第二家园规划、国家/城市筛选、项目匹配、置业流程、国际学校选择、生活配套、长期服务和顾问式咨询',
  style: '专业可信、顾问式成交、真实案例、强钩子、适合抖音/小红书图文引流',
  trendKeywords: '马来西亚海外置业,马来西亚房产,马来西亚第二家园,马来西亚国际学校,马来西亚 A-Level,马来西亚 IB,海外房产置业,海外资产配置,马来西亚线下说明会,置业推荐会',
  customerSegments: `1. 有海外资产配置需求的高净值家庭
2. 想给孩子规划国际学校/A-Level/IB 的家庭
3. 想办理马来西亚第二家园身份的人群
4. 想养老、度假或长期居住的家庭
5. 对国内资产压力、教育焦虑、身份规划敏感的人群`,
  privateDomainAssets: `《马来西亚第二家园避坑报告》
《马来西亚国际学校择校清单》
《海外置业预算测算表》
《马来西亚买房完整流程图》
《线下说明会/置业推荐会名额》`,
  contentPillars: `避坑类：海外买房最容易踩的 3 个坑
教育类：马来西亚国际学校到底适合什么家庭
身份类：第二家园身份适合哪些人
预算类：几百万预算怎么配置马来西亚房产
流程类：中国人买马来西亚房产完整流程
信任类：线下说明会、客户案例、顾问答疑`,
  shootingBrief: '提供拍摄方案和提示词：顾问正面口播、项目/泳池/社区 B-roll、国际学校画面、地图/预算表/报告截图、结尾引导私信领取资料。封面大字优先突出“避坑、预算、第二家园、国际学校”。',
  reportDelivery: '报告放微信：评论区留关键词或私信“报告/预算/身份/学校”，自动回复筛选问题后引导加微信领取。'
}
const DIGITAL_HUMAN_TASK_KEY = 'ai_video_current_digital_human_task_v1'
const emotionOptions = ['自然可信', '提醒警示', '紧张急迫', '坚定有力', '朋友聊天', '专业冷静', '惊讶反问', '收尾号召']

function getDigitalHumanTaskModel(task: DigitalHumanCreateResponse | null, fallback: string) {
  const engine = String(task?.engine || '')
  const jobId = String(task?.job_id || '')
  const rawModel = String((task?.raw as any)?.model || (task?.raw as any)?.endpoint || '')

  // fal 任务的 job_id 会是 fal:<request_id>，engine 通常是 fal:fal-ai/sync-lipsync。
  // 之前这里只解析 jimeng，导致 fal 异步任务展示时误用 fallback=omnihuman15。
  if (jobId.startsWith('fal:') || engine.startsWith('fal:') || engine.includes('sync-lipsync') || rawModel.includes('sync-lipsync')) {
    return engine.startsWith('fal:') ? engine.replace(/^fal:/, '') : (rawModel || 'fal-ai/sync-lipsync')
  }

  const jimengMatch = engine.match(/^jimeng:([a-zA-Z0-9_-]+)/)
  if (jimengMatch?.[1]) return jimengMatch[1]

  return fallback || 'omnihuman15'
}

function getDigitalHumanTaskProvider(task: DigitalHumanCreateResponse | null, fallback: string) {
  const model = getDigitalHumanTaskModel(task, fallback)
  if (model.includes('sync-lipsync') || String(task?.job_id || '').startsWith('fal:') || String(task?.engine || '').startsWith('fal:')) {
    return `fal.ai / ${model}`
  }
  if (String(task?.engine || '').startsWith('jimeng:') || ['omnihuman15', 'quick', 'video30'].includes(model)) {
    return `火山即梦 / ${model}`
  }
  return model
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
  { key: 'dashboard', icon: '总', title: '工作台总览', desc: '看今天采集、待产出和投流复盘', tag: '总览' },
  { key: 'lead', icon: '雷', title: '热度雷达', desc: '今日 Top5、视频分析、导入入口和 AI 改写', tag: '雷达' },
  { key: 'competitor', icon: '账', title: '账号库', desc: '固定监控博主；点开账号再看对应热点', tag: '账号' },
  { key: 'copy', icon: '文', title: '文案生产', desc: '先仿写，再出标题、钩子和完整视频脚本', tag: '文案' },
  { key: 'shooting', icon: '拍', title: '脚本 / 拍摄', desc: '上传资料或脚本，生成拍摄任务、提词器和 B-roll 清单', tag: '脚本' },
  { key: 'assets', icon: '素', title: '素材选择', desc: '选择数字人、自拍素材、采集视频或图文素材', tag: '素材' },
  { key: 'digitalHuman', icon: '人', title: '数字人开场', desc: '真人模板口型同步，生成 5-15 秒开场片段并回存素材库', tag: '数字人' },
  { key: 'voice', icon: '声', title: '配音导演', desc: '克隆音色、分段情绪、语速停顿', tag: '配音' },
  { key: 'video', icon: '剪', title: '成片合成', desc: '素材顺序、截取区间、字幕烧录和导出', tag: '成片' },
  { key: 'subtitleCover', icon: '图', title: '图文窗口', desc: '图文引流包、封面、字幕重点单独处理', tag: '图文' },
  { key: 'growth', icon: '投', title: '流量监控', desc: '手动录入数据，AI 判断投多少、投多久、是否继续投', tag: '投流' },
  { key: 'collector', icon: '采', title: '实时日志', desc: '查看 ECS 采集、AI 判断、入库和报错日志', tag: '日志' },
  { key: 'strategy', icon: '档', title: '获客档案', desc: '业务定位、关键词、客群、资料包和承接钩子', tag: '档案' },
  { key: 'monitor', icon: '控', title: '系统状态', desc: 'API、Supabase、R2、任务队列和诊断', tag: '状态' },
  { key: 'oneClick', icon: '旧', title: '旧版一键生成', desc: '保留旧接口，默认不在主流程展示', tag: '隐藏' },
  { key: 'publish', icon: '发', title: '平台发布', desc: '发布草稿、平台适配、开放接口预留', tag: '发布' },
  { key: 'trend', icon: '爆', title: '行业爆点', desc: '旧版行业爆点页，主流程已并入热度雷达', tag: '隐藏' }
]

const workflowSteps: { key: ModuleKey; step: string; title: string; desc: string; action: string }[] = [
  { key: 'copy', step: '01', title: '数字人开场稿', desc: '先做 5-15 秒真人模板口播稿，不必等整条片文案。', action: '写开场' },
  { key: 'voice', step: '02', title: '开场配音', desc: '把开场稿生成真实配音，供 fal 口型同步。', action: '配音' },
  { key: 'digitalHuman', step: '03', title: '数字人开场', desc: '真人模板视频 + 配音，生成开场片段并自动入素材库。', action: '生成数字人' },
  { key: 'assets', step: '04', title: '楼盘/风光素材', desc: '选择楼盘、马来西亚风光、配套和教育医疗素材，调整顺序和时长。', action: '选素材' },
  { key: 'copy', step: '05', title: '按素材补全旁白', desc: '读取已选素材总时长，再生成完整旁白稿和字幕逻辑。', action: '补全脚本' },
  { key: 'video', step: '06', title: '合成成片', desc: '数字人开场 + B-roll 素材 + 配音字幕，导出 9:16 MP4。', action: '合成' },
  { key: 'growth', step: '07', title: '流量监控', desc: '录入发布数据，AI 判断投多少、投多久、是否继续投。', action: '投流' }
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

const realDataConnectors = [
  {
    name: '百度搜索 / 百度营销',
    status: '推荐优先接',
    purpose: '拿搜索词、关键词规划、广告线索和高意向查询词',
    fields: ['BAIDU_MARKETING_APP_ID', 'BAIDU_MARKETING_SECRET', 'BAIDU_MARKETING_ACCESS_TOKEN'],
    note: '适合抓“买房条件/流程/税费/MM2H/城市区域”等主动搜索需求。'
  },
  {
    name: '巨量引擎 / 抖音搜索',
    status: '第二优先',
    purpose: '拿抖音搜索、广告报表、线索表单、关键词和内容热度',
    fields: ['OCEANENGINE_APP_ID', 'OCEANENGINE_SECRET', 'OCEANENGINE_ACCESS_TOKEN'],
    note: '适合发现抖音里正在被搜索和评论的问题，用来做截流内容。'
  },
  {
    name: '抖音开放平台',
    status: '可接入',
    purpose: '关键词视频搜索、授权账号评论、视频评论管理和回复',
    fields: ['DOUYIN_CLIENT_KEY', 'DOUYIN_CLIENT_SECRET', 'DOUYIN_ACCESS_TOKEN'],
    note: '官方能力更适合管理自己授权账号和合规获取评论；竞品全量采集需要谨慎。'
  },
  {
    name: '小红书数据源',
    status: '建议第三方/人工导入',
    purpose: '笔记标题、评论问题、收藏转发趋势和图文选题',
    fields: ['XHS_DATA_PROVIDER_KEY 或 CSV 导入'],
    note: '小红书公开 API 能力有限，先做链接/CSV/表格导入，再考虑合规数据服务商。'
  },
  {
    name: '企业微信 / SCRM',
    status: '微信未接入前先网页模拟',
    purpose: '报告领取、客户标签、私信筛选、顾问跟进和转化复盘',
    fields: ['WECHAT_CORP_ID', 'WECHAT_AGENT_ID', 'WECHAT_SECRET'],
    note: '微信生态更适合承接和培育，不建议当海外房产直接买量主入口。'
  }
]

const interceptionOpportunityFallback = [
  { score: 92, source: '百度搜索', keyword: '马来西亚买房税费怎么算', intent: '税费测算 / 交易前教育', action: '做税费计算器落地页 + 领取税费测算表', asset: '《马来西亚买房税费测算表》' },
  { score: 88, source: '抖音搜索/评论', keyword: '马来西亚第二家园一定要买房吗', intent: '身份规划 / MM2H', action: '做 30 秒问答视频 + 评论关键词“身份”', asset: '《MM2H 与购房要求对照表》' },
  { score: 86, source: '小红书图文', keyword: 'Mont Kiara 国际学校附近公寓', intent: '教育家庭 / 城市筛选', action: '做 5 页图文包 + 私信“学校”领取清单', asset: '《马来西亚国际学校择校清单》' },
  { score: 84, source: '竞品评论区', keyword: '吉隆坡和新山哪里更值得买', intent: '城市比较 / 项目筛选', action: '做对比内容 + 领取城市对比表', asset: '《吉隆坡 vs 新山选盘表》' },
  { score: 81, source: '百度长尾词', keyword: '中国人可以买马来西亚房产吗', intent: '资格判断 / 初筛', action: '做 FAQ 落地页 + 顾问筛选表单', asset: '《马来西亚买房资格清单》' }
]

const heatRadarSeedKeywords = [
  '马来西亚房产', '马来西亚买房', '马来西亚投资房产', '大马房产', '马来西亚第二家园', 'MM2H',
  '吉隆坡房产', '新山房产', '槟城房产', '马来西亚国际学校', '马来西亚买房税费', '马来西亚买房流程',
  'Mont Kiara 国际学校附近公寓', '新山 RTS 附近房产', '吉隆坡和新山哪里更值得买', '中国人可以买马来西亚房产吗'
]

const heatRadarDataLoop = [
  '每日固定查看竞品账号和关键词热度，不再叫“截流”，改成“热度雷达”',
  '每个竞品账号只保留当日热度前 3 条内容/话题，避免信息太乱',
  'AI 只负责分析热度、客户意图、可承接资料包和下一步动作',
  '账号库长期固定，可添加、删除、置顶，后续接 API 后自动采集',
  '当前没接三方 API 时先用手动导入/链接记录；上线后存 Supabase，素材和截图存 R2'
]

const heatRadarFallbackSnapshots: HeatRadarSnapshot[] = [
  { id: 'seed_tax', date: todayKey(), account_id: 'seed', account_name: '行业热词', platform: '百度/巨量/小红书', topic: '马来西亚买房税费怎么算', signal: '交易前教育词，适合税费测算表承接', score: 94, intent: '税费/预算测算', source_url: '', recommended_action: '做税费测算落地页和 30 秒问答视频', lead_magnet: '《马来西亚买房税费测算表》' },
  { id: 'seed_mm2h', date: todayKey(), account_id: 'seed', account_name: '行业热词', platform: '抖音/百度', topic: '马来西亚第二家园一定要买房吗', signal: '身份规划与购房门槛强相关', score: 92, intent: 'MM2H/身份规划', source_url: '', recommended_action: '做 MM2H 类别对照图文和私信关键词“身份”', lead_magnet: '《MM2H 与购房要求对照表》' },
  { id: 'seed_mk', date: todayKey(), account_id: 'seed', account_name: '行业热词', platform: '小红书/抖音', topic: 'Mont Kiara 国际学校附近公寓', signal: '教育家庭高意向场景', score: 89, intent: '子女教育/区域选盘', source_url: '', recommended_action: '做国际学校周边选盘图文包', lead_magnet: '《马来西亚国际学校择校清单》' }
]

function asOpportunityList(plan: LeadAcquisitionPlanResponse | null) {
  const fromPlan = (plan as any)?.interception_opportunities
  if (Array.isArray(fromPlan) && fromPlan.length) return fromPlan
  return interceptionOpportunityFallback
}

function nextStepOf(active: ModuleKey): ModuleKey {
  const order: ModuleKey[] = ['oneClick','assets','copy','voice','digitalHuman','video','subtitleCover','publish']
  const idx = order.indexOf(active)
  return idx >= 0 && idx < order.length - 1 ? order[idx + 1] : active
}

function shortText(value: string, limit = 68) {
  const clean = (value || '').replace(/\s+/g, ' ').trim()
  return clean.length > limit ? clean.slice(0, limit) + '...' : clean
}

function heatEvidenceLine(item: HeatRadarSnapshot) {
  const pieces = [item.platform, item.account_name, item.topic, item.signal].filter(Boolean)
  return pieces.join('｜')
}

function hasRealHeatSignal(item: HeatRadarSnapshot) {
  const text = `${item.source_url || ''} ${item.signal || ''} ${item.topic || ''}`
  return Boolean(item.source_url) || /(赞|评|评论|藏|收藏|分享|转发|播放|浏览)\s*\d/i.test(text)
}

type HeatAccountGroup = {
  key: string
  name: string
  platform: string
  account?: HeatRadarAccount
  items: HeatRadarSnapshot[]
  bestScore: number
}

function groupHeatSnapshotsByAccount(items: HeatRadarSnapshot[], accounts: HeatRadarAccount[]): HeatAccountGroup[] {
  const accountById = new Map(accounts.map(acc => [String(acc.id || acc.name || acc.url), acc]))
  const groups = new Map<string, HeatAccountGroup>()
  for (const item of items) {
    const matched = accountById.get(String(item.account_id || ''))
    const key = String(item.account_id || matched?.id || item.account_name || item.source_url || item.id || 'unknown')
    const name = String(matched?.name || item.account_name || '未命名博主')
    const platform = String(matched?.platform || item.platform || '平台')
    if (!groups.has(key)) groups.set(key, { key, name, platform, account: matched, items: [], bestScore: 0 })
    const group = groups.get(key)!
    group.items.push(item)
    group.bestScore = Math.max(group.bestScore, Number(item.score || 0))
  }
  const pinnedOrder = new Map(accounts.map((acc, idx) => [String(acc.id || acc.name || acc.url), idx]))
  return Array.from(groups.values()).sort((a, b) => {
    const ap = a.account?.pinned ? 0 : 1
    const bp = b.account?.pinned ? 0 : 1
    if (ap !== bp) return ap - bp
    const ao = pinnedOrder.get(a.key) ?? 999
    const bo = pinnedOrder.get(b.key) ?? 999
    if (ao !== bo) return ao - bo
    return b.bestScore - a.bestScore
  }).map(group => ({ ...group, items: [...group.items].sort((a, b) => Number(b.score || 0) - Number(a.score || 0)) }))
}

function heatStageLabel(count: number, hasRewrite: boolean) {
  if (hasRewrite) return 'AI 已完成目标和改写'
  if (count > 0) return '已进入热点改写池'
  return '等待真实采集'
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

function splitProfileLines(value: string, fallback: string[] = []) {
  const items = safeText(value).split(/[\n,，;；]+/).map(x => x.replace(/^[-·\d.、\s]+/, '').trim()).filter(Boolean)
  return items.length ? items : fallback
}


function cleanReportTitle(value: string) {
  return safeText(value).replace(/[《》]/g, '').replace(/报告|清单|表|流程图/g, '').trim()
}

function buildLeadMagnetReports(params: {
  privateDomainAssets: string
  businessPositioning: string
  industry: string
  audience: string
  trendKeywords: string
  customerSegments: string
  reportDelivery: string
}): LeadMagnetReport[] {
  const assetNames = splitProfileLines(params.privateDomainAssets, [
    '马来西亚第二家园避坑报告',
    '马来西亚国际学校择校清单',
    '海外置业预算测算表',
    '马来西亚买房完整流程图',
    '线下说明会名额'
  ]).slice(0, 6)
  const keywords = splitProfileLines(params.trendKeywords, ['第二家园', '海外置业', '国际学校', '预算测算', '避坑'])
  const segments = splitProfileLines(params.customerSegments, [params.audience || '目标客户'])
  const baseIndustry = params.businessPositioning || params.industry || '行业获客'
  return assetNames.map((name, index) => {
    const clean = cleanReportTitle(name) || `资料包 ${index + 1}`
    const keyword = keywords[index % keywords.length] || clean
    const segment = segments[index % segments.length] || params.audience || '目标客户'
    const ctaWord = keyword.includes('预算') ? '预算' : keyword.includes('学校') ? '学校' : keyword.includes('身份') || keyword.includes('第二家园') ? '身份' : '报告'
    return {
      id: `report_${index}`,
      title: name,
      keyword: ctaWord,
      subtitle: `${clean}｜先收藏，咨询前直接对照。`,
      audience: segment,
      promise: `用一份网页资料先筛出真正有需求的人，再引导私信/微信领取完整版本。`,
      outline: [
        `适合谁：${segment}`,
        `先看什么：${keyword} 相关条件、预算和风险`,
        `避开什么：只看价格、不看身份/教育/长期规划`,
        `怎么判断：用 3 个问题筛选真实需求`,
        `下一步：私信“${ctaWord}”领取完整清单`
      ],
      landingTitle: clean.length > 18 ? clean : `${clean}｜领取前先看这 5 点`,
      landingSubtitle: `${baseIndustry}，先用网页版资料承接线索，微信未接入时也能演示完整获客链路。`,
      cta: `评论区或私信发送「${ctaWord}」，领取完整资料并做需求筛选。`,
      replyScript: `收到，我先把《${clean}》网页版发你。你更关注【身份/教育/预算/项目】哪一块？我按你的情况发对应清单。`,
      shootingIdea: `拍摄一条“领取${clean}前先看这 3 点”的口播，画面用报告预览页 + 房产/学校/顾问素材，结尾引导私信“${ctaWord}”。`
    }
  })
}

function buildReportLandingCopy(report: LeadMagnetReport | undefined) {
  if (!report) return ''
  return [
    report.landingTitle,
    report.landingSubtitle,
    '',
    '页面结构：',
    ...report.outline.map((x, i) => `${i + 1}. ${x}`),
    '',
    `CTA：${report.cta}`,
    `私信回复：${report.replyScript}`
  ].join('\n')
}


async function copyTextToClipboard(text: string) {
  try {
    await navigator.clipboard?.writeText(text)
    return true
  } catch {
    const el = document.createElement('textarea')
    el.value = text
    document.body.appendChild(el)
    el.select()
    document.execCommand('copy')
    document.body.removeChild(el)
    return true
  }
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
  const [jobs, setJobs] = useState<JobItem[]>([])
  const [contentNavOpen, setContentNavOpen] = useState(true)
  const [navCollapsed, setNavCollapsed] = useState(false)
  const [navMobileOpen, setNavMobileOpen] = useState(false)

  const [industry, setIndustry] = useState(malaysiaProfilePreset.industry)
  const [audience, setAudience] = useState(malaysiaProfilePreset.audience)
  const [sellingPoints, setSellingPoints] = useState(malaysiaProfilePreset.sellingPoints)
  const [style, setStyle] = useState(malaysiaProfilePreset.style)
  const [leadRegion, setLeadRegion] = useState(malaysiaProfilePreset.leadRegion)
  const [conversionGoal, setConversionGoal] = useState(malaysiaProfilePreset.conversionGoal)
  const [trendKeywords, setTrendKeywords] = useState(malaysiaProfilePreset.trendKeywords)
  const [businessPositioning, setBusinessPositioning] = useState(malaysiaProfilePreset.businessPositioning)
  const [customerSegments, setCustomerSegments] = useState(malaysiaProfilePreset.customerSegments)
  const [privateDomainAssets, setPrivateDomainAssets] = useState(malaysiaProfilePreset.privateDomainAssets)
  const [contentPillars, setContentPillars] = useState(malaysiaProfilePreset.contentPillars)
  const [shootingBrief, setShootingBrief] = useState(malaysiaProfilePreset.shootingBrief)
  const [reportDelivery, setReportDelivery] = useState(malaysiaProfilePreset.reportDelivery)
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
  const [assetFolderFilter, setAssetFolderFilter] = useState<AssetFolderKey>('all')
  const [assetUploadFolder, setAssetUploadFolder] = useState<AssetFolderKey>('self')
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

  const [digitalHumanEngine, setDigitalHumanEngine] = useState('fal_lipsync')
  const [digitalHumanJimengModel, setDigitalHumanJimengModel] = useState('omnihuman15')
  const [digitalHumanAvatarId, setDigitalHumanAvatarId] = useState('')
  const [digitalHumanDriverId, setDigitalHumanDriverId] = useState('')
  const [digitalHumanConsent, setDigitalHumanConsent] = useState(false)
  const [digitalHuman, setDigitalHuman] = useState<DigitalHumanCreateResponse | null>(null)
  const [digitalHumanPollCount, setDigitalHumanPollCount] = useState(0)
  const [digitalHumanLastChecked, setDigitalHumanLastChecked] = useState('')

  const [segmentSeconds, setSegmentSeconds] = useState<Record<number, number>>({})
  const [segmentTransitions, setSegmentTransitions] = useState<Record<number, string>>({})
  const [subtitleSize, setSubtitleSize] = useState(20)
  const [subtitleMarginV, setSubtitleMarginV] = useState(86)
  const [subtitlePosition, setSubtitlePosition] = useState<'bottom_safe' | 'middle_low' | 'center'>('bottom_safe')
  const [subtitlePreset, setSubtitlePreset] = useState<'douyin_boss' | 'knowledge_highlight' | 'clean_trust' | 'cta_pop'>('douyin_boss')
  const subtitleColor = subtitlePreset === 'clean_trust' ? '#ffffff' : subtitlePreset === 'cta_pop' ? '#FFD84D' : '#ffffff'
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
  const [imagePrompt, setImagePrompt] = useState('高端海外第二家园置业场景，阳光、现代住宅、商务顾问感，干净留白，适合作为短视频封面和图文背景')
  const [digitalHumanVersion, setDigitalHumanVersion] = useState(() => Number(window.localStorage.getItem('ai_video_digital_human_version_v1') || '1'))
  const [editInstruction, setEditInstruction] = useState('把开头节奏加快，保留重点字幕；转场更自然，并重新导出 9:16。')
  const [editChat, setEditChat] = useState<VideoEditChatResponse[]>([])
  const [ad, setAd] = useState<AdAnalysisResponse | null>(null)
  const [platform, setPlatform] = useState('douyin')
  const [publish, setPublish] = useState<PlatformPublishResponse | null>(null)
  const [lastHandoff, setLastHandoff] = useState('新流程：先生成数字人开场，再选楼盘/风光素材，最后按素材时长补全旁白并合成成片。')
  const [knowledgeDialog, setKnowledgeDialog] = useState({ open: false, source: '', title: '', content: '', tags: '老板口播,获客,短视频' })

  const [leadPlan, setLeadPlan] = useState<LeadAcquisitionPlanResponse | null>(null)
  const [leadChannels, setLeadChannels] = useState<string[]>(['百度搜索关键词', '巨量搜索/抖音搜索', '抖音视频评论', '小红书笔记评论', '竞品账号监控', '微信/企微私域承接'])
  const [leadFixedOptions, setLeadFixedOptions] = useState('子女教育家庭、企业主资产配置、养老度假、海外第二居所、华人家庭、马来西亚城市、预算区间、国际学校、第二家园身份')
  const [heatAccounts, setHeatAccounts] = useState<HeatRadarAccount[]>([])
  const [heatSnapshots, setHeatSnapshots] = useState<HeatRadarSnapshot[]>(() => loadLocalJson('ai_video_heat_snapshots_v1', [] as HeatRadarSnapshot[]))
  const [heatDraft, setHeatDraft] = useState<HeatRadarAccount>({ id: '', name: '', platform: '抖音', url: '', tags: '马来西亚房产,第二家园,海外置业', notes: '', pinned: true, created_at: '' })
  const [manualHeatText, setManualHeatText] = useState('')
  const [heatCrawlerResult, setHeatCrawlerResult] = useState<HeatRadarRunResponse | null>(null)
  const [heatRewrite, setHeatRewrite] = useState<HeatRadarRewriteResponse | null>(null)
  const [heatCrawlerLimit, setHeatCrawlerLimit] = useState(3)
  const [videoIntakeUrl, setVideoIntakeUrl] = useState('')
  const [videoIntakeResult, setVideoIntakeResult] = useState<any>(null)
  const [expandedHeatGroups, setExpandedHeatGroups] = useState<Record<string, boolean>>({})
  const [heatAccountAudit, setHeatAccountAudit] = useState<HeatRadarAccountAuditResponse | null>(null)
  const [heatAutomationToken, setHeatAutomationToken] = useState(() => window.localStorage.getItem('heatRadarIngestToken') || '')
  const [heatAccountSearch, setHeatAccountSearch] = useState('')
  const [heatPlatformFilter, setHeatPlatformFilter] = useState('all')
  const [expandedHeatAccounts, setExpandedHeatAccounts] = useState<Record<string, boolean>>({})
  const [heatAccountReviews, setHeatAccountReviews] = useState<any[]>([])
  const [activeReportIndex, setActiveReportIndex] = useState(0)
  const [reportCopyStatus, setReportCopyStatus] = useState('')

  const [ecsCollectorCount, setEcsCollectorCount] = useState('1')
  const [ecsCollectorTime, setEcsCollectorTime] = useState('02:00')
  const [ecsCollectorAccount, setEcsCollectorAccount] = useState('')
  const [ecsDryRunMode, setEcsDryRunMode] = useState(false)
  const [ecsNoDelayMode, setEcsNoDelayMode] = useState(true)
  const [collectorProgress, setCollectorProgress] = useState<CollectorProgressState | null>(null)
  const [digitalHumanProviders, setDigitalHumanProviders] = useState<DigitalHumanProviderOption[]>([])

  const ecsLimit = Math.max(1, Number(ecsCollectorCount) || 1)
  const ecsDailyCommand = `powershell -ExecutionPolicy Bypass -File .\install_daily_task.ps1 -Time "${ecsCollectorTime || '02:00'}" -Limit ${ecsLimit}`
  const ecsNoDelayArg = ecsNoDelayMode ? ' --no-delay' : ''
  const ecsRunCommand = ecsCollectorAccount.trim()
    ? `python run_all.py --headful --account "${ecsCollectorAccount.trim()}" --limit 1 --no-delay`
    : `python run_all.py --headful --limit ${ecsLimit}${ecsNoDelayArg}`
  const ecsDryRunCommand = ecsCollectorAccount.trim()
    ? `python run_all.py --headful --dry-run --account "${ecsCollectorAccount.trim()}" --limit 1 --no-delay`
    : `python run_all.py --headful --dry-run --limit ${ecsLimit}${ecsNoDelayArg}`

  const collectorEventsForReport = useMemo(() => (collectorProgress?.events || []).slice(0, 18), [collectorProgress])
  const latestCollectorEvent = collectorEventsForReport[0]
  const collectorReportLine = useMemo(() => {
    const events = collectorEventsForReport
    if (!events.length) return '等待采集报告：网页下发命令后，ECS 会实时回传打开账号、提取视频、提交分析、入选/未入选原因。'
    return formatCollectorEventLine(events[0], 0)
  }, [collectorEventsForReport])

  const materialAssets = useMemo(() => assets.map((a, i) => normalizeAsset(a, i)).filter(a => Boolean(a.id && a.url) && !safeText(a.filename).startsWith('collected_')), [assets])
  const collectedVideos = useMemo(() => assets.map((a, i) => normalizeAsset(a, i)).filter(a => Boolean(a.id && a.url) && a.kind === 'video' && safeText(a.filename).startsWith('collected_')), [assets])
  const filteredMaterialAssets = useMemo(() => {
    const now = Date.now()
    const maxAge = assetTimeFilter === 'today' ? 24 * 3600 * 1000 : assetTimeFilter === '7d' ? 7 * 24 * 3600 * 1000 : assetTimeFilter === '30d' ? 30 * 24 * 3600 * 1000 : 0
    const q = assetSearch.trim().toLowerCase()
    const list = materialAssets.filter(a => {
      if (assetKindFilter !== 'all' && a.kind !== assetKindFilter) return false
      if (assetFolderFilter !== 'all' && normalizeAssetFolder((a as any).folder, a.kind, a.filename) !== assetFolderFilter) return false
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
  }, [materialAssets, assetKindFilter, assetFolderFilter, assetSearch, assetSort, assetTimeFilter])
  const selectedMaterialAssets = useMemo(() => selectedMaterialIds
    .map(id => materialAssets.find(a => a.id === id))
    .filter((a): a is AssetItem => Boolean(a && a.id && a.url))
    .map((a, i) => normalizeAsset(a, i)), [materialAssets, selectedMaterialIds])
  useEffect(() => { window.localStorage.setItem('ai_video_heat_snapshots_v1', JSON.stringify(heatSnapshots.slice(0, 200))) }, [heatSnapshots])
  const pinnedHeatAccounts = useMemo(() => heatAccounts.filter(x => x.pinned).concat(heatAccounts.filter(x => !x.pinned)), [heatAccounts])
  const filteredHeatAccounts = useMemo(() => {
    const q = heatAccountSearch.trim().toLowerCase()
    return pinnedHeatAccounts.filter(acc => {
      if (heatPlatformFilter !== 'all' && acc.platform !== heatPlatformFilter) return false
      if (!q) return true
      return `${acc.name} ${acc.url} ${acc.tags} ${acc.notes}`.toLowerCase().includes(q)
    })
  }, [pinnedHeatAccounts, heatAccountSearch, heatPlatformFilter])
  const todayHeatSnapshots = useMemo(() => {
    const today = todayKey()
    const realList = heatSnapshots.filter(x => {
      const id = String(x.id || '')
      const signal = String(x.signal || '')
      const topic = String(x.topic || '')
      return !id.startsWith('seed_') && !signal.includes('本地关键词模拟') && !topic.includes('本地关键词模拟')
    })
    const todayList = realList.filter(x => x.date === today)
    const source = todayList.length ? todayList : realList
    // Top5 是“可跟进候选池”，不是只看点赞；按 AI 分数优先，再看真实互动。
    return [...source].sort((a, b) => Number(b.score || 0) - Number(a.score || 0)).slice(0, 5)
  }, [heatSnapshots])

  const primaryHeat = todayHeatSnapshots[0] || null
  const realHeatCount = todayHeatSnapshots.filter(hasRealHeatSignal).length
  const heatAccountGroups = useMemo(() => groupHeatSnapshotsByAccount(todayHeatSnapshots, pinnedHeatAccounts), [todayHeatSnapshots, pinnedHeatAccounts])
  const heatSourceLines = useMemo(() => todayHeatSnapshots.map(heatEvidenceLine).filter(Boolean), [todayHeatSnapshots])
  const heatWorkbenchStatus = heatStageLabel(todayHeatSnapshots.length, Boolean(heatRewrite))
  const referenceText = useMemo(() => extract?.transcript || manualText || sourceUrl, [extract, manualText, sourceUrl])
  const competitorNotes = useMemo(() => competitors.map(c => `${c.platform}｜${c.name}｜${c.positioning}｜${c.notes}`).join('\n'), [competitors])
  const profileContext = useMemo(() => [
    `业务定位：${businessPositioning || industry}`,
    `客户分层：${customerSegments}`,
    `监听关键词：${trendKeywords}`,
    `私域承接物：${privateDomainAssets}`,
    `内容栏目：${contentPillars}`,
    `承接方式：${reportDelivery}`,
    `内容栏目：${contentPillars}`,
    `拍摄口播要求（仅用于内容生产，不用于截流雷达）：${shootingBrief}`,
  ].filter(Boolean).join('\n'), [businessPositioning, industry, customerSegments, trendKeywords, privateDomainAssets, contentPillars, shootingBrief, reportDelivery])
  const leadMagnetReports = useMemo(() => buildLeadMagnetReports({ privateDomainAssets, businessPositioning, industry, audience, trendKeywords, customerSegments, reportDelivery }), [privateDomainAssets, businessPositioning, industry, audience, trendKeywords, customerSegments, reportDelivery])
  const activeReport = leadMagnetReports[Math.min(activeReportIndex, Math.max(0, leadMagnetReports.length - 1))]
  const reportLandingCopy = useMemo(() => buildReportLandingCopy(activeReport), [activeReport])
  const radarKeywordGroups = useMemo(() => {
    const keywords = splitProfileLines(trendKeywords, ['海外置业', '第二家园', '国际学校', '预算', '避坑'])
    return {
      highIntent: keywords.filter(x => /预算|条件|流程|申请|推荐|说明会|咨询|办理/.test(x)).slice(0, 6),
      contentHooks: keywords.filter(x => /避坑|坑|真相|费用|适合|对比|不要|后悔/.test(x)).slice(0, 6),
      broadTraffic: keywords.filter(x => !/预算|条件|流程|申请|推荐|说明会|咨询|办理|避坑|坑|真相|费用|适合|对比|不要|后悔/.test(x)).slice(0, 8),
    }
  }, [trendKeywords])
  const shootingTaskSeeds = useMemo(() => {
    const pillars = splitProfileLines(contentPillars, ['避坑类', '预算类', '流程类'])
    const reports = leadMagnetReports.length ? leadMagnetReports : []
    return pillars.slice(0, 4).map((pillar, index) => {
      const report = reports[index % Math.max(1, reports.length)]
      return {
        title: `${pillar.replace(/：.*$/, '')}｜${report?.landingTitle || '先讲一个客户最容易忽略的问题'}`,
        hook: report ? `先别急着咨询，${report.title.replace(/[《》]/g, '')}里这 3 点先看懂。` : '客户最常踩的坑，其实不是预算，而是顺序错了。',
        shots: ['顾问正面口播', '素材/B-roll 快切', '资料包网页预览', '结尾私信关键词 CTA'],
        cta: report?.cta || '私信“报告”领取完整资料。'
      }
    })
  }, [contentPillars, leadMagnetReports])
  const sellingPointsWithProfile = useMemo(() => `${sellingPoints}\n\n【行业获客档案】\n${profileContext}\n\n【网页资料包/报告承接】\n${reportLandingCopy}`.trim(), [sellingPoints, profileContext, reportLandingCopy])
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

  const selectedAssetScriptContext = useMemo(() => {
    const chosen = selectedMaterialAssets.length ? selectedMaterialAssets : materialAssets.slice(0, 6)
    return chosen.map((asset, index) => {
      const cfg = getClipSetting(asset, index)
      const seconds = asset.kind === 'image'
        ? Math.max(0.8, safeNumber(cfg.image_seconds, 2.8))
        : Math.max(0.8, (cfg.video_end && cfg.video_end > cfg.video_start ? cfg.video_end - cfg.video_start : 3.2))
      return `${index + 1}. ${asset.kind === 'video' ? '视频' : '图片'}｜${asset.original_name || asset.filename}｜约 ${Math.round(seconds * 10) / 10} 秒`
    }).join('\n')
  }, [selectedMaterialAssets, materialAssets, assetClipSettings])

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
      selling_points: sellingPointsWithProfile,
      style,
      duration_seconds: autoProjectSeconds,
      goal: conversionGoal,
      output_type: oneClickOutputType,
      material_mode: oneClickMaterialMode,
      selected_asset_names: selectedNames,
      reference_text: referenceText,
      instruction: `${oneClickInstruction}\n\n请严格读取行业获客档案：\n${profileContext}`,
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
      selling_points: sellingPointsWithProfile,
    }))
    applyOneClickResult(res!)
    setActive('oneClick')
  }

  function applyMalaysiaPreset() {
    setIndustry(malaysiaProfilePreset.industry)
    setBusinessPositioning(malaysiaProfilePreset.businessPositioning)
    setAudience(malaysiaProfilePreset.audience)
    setLeadRegion(malaysiaProfilePreset.leadRegion)
    setConversionGoal(malaysiaProfilePreset.conversionGoal)
    setSellingPoints(malaysiaProfilePreset.sellingPoints)
    setStyle(malaysiaProfilePreset.style)
    setTrendKeywords(malaysiaProfilePreset.trendKeywords)
    setCustomerSegments(malaysiaProfilePreset.customerSegments)
    setPrivateDomainAssets(malaysiaProfilePreset.privateDomainAssets)
    setContentPillars(malaysiaProfilePreset.contentPillars)
    setShootingBrief(malaysiaProfilePreset.shootingBrief)
    setReportDelivery(malaysiaProfilePreset.reportDelivery)
    setLeadFixedOptions('子女教育家庭、企业主资产配置、养老度假、海外第二居所、华人家庭、马来西亚城市、预算区间、国际学校、第二家园身份')
    setLastHandoff('已套用“马来西亚房产 / 第二家园”行业获客档案。后续一键生成、文案、图文、拍摄和私域回复都会读取这套档案。')
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
      if (profile.business_positioning) setBusinessPositioning(profile.business_positioning)
      if (profile.customer_segments) setCustomerSegments(profile.customer_segments)
      if (profile.private_domain_assets) setPrivateDomainAssets(profile.private_domain_assets)
      if (profile.content_pillars) setContentPillars(profile.content_pillars)
      if (profile.shooting_brief) setShootingBrief(profile.shooting_brief)
      if (profile.report_delivery) setReportDelivery(profile.report_delivery)
      if (profile.listening_keywords && !profile.trend_keywords) setTrendKeywords(profile.listening_keywords)
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
      trend_keywords: trendKeywords,
      business_positioning: businessPositioning,
      listening_keywords: trendKeywords,
      customer_segments: customerSegments,
      private_domain_assets: privateDomainAssets,
      content_pillars: contentPillars,
      shooting_brief: shootingBrief,
      report_delivery: reportDelivery
    }))
    await reloadMemoryContext(true)
  }


  function toggleLeadChannel(name: string) {
    setLeadChannels(prev => prev.includes(name) ? prev.filter(x => x !== name) : [...prev, name])
  }

  async function makeLeadPlan() {
    const res = await run('生成热度雷达方案', () => apiPost<LeadAcquisitionPlanResponse>('/api/lead-acquisition/plan', {
      industry,
      audience,
      selling_points: limitText(sellingPointsWithProfile, 1200),
      style,
      lead_region: leadRegion,
      conversion_goal: conversionGoal,
      channels: leadChannels,
      data_sources: realDataConnectors.map(x => x.name),
      competitor_accounts: competitors.map(c => `${c.platform}:${c.name}:${c.url}`),
      fixed_options: leadFixedOptions,
      competitor_notes: competitorNotes,
      trend_keywords: trendKeywords,
      business_positioning: businessPositioning,
      listening_keywords: trendKeywords,
      customer_segments: customerSegments,
      private_domain_assets: privateDomainAssets,
      content_pillars: contentPillars,
      shooting_brief: shootingBrief,
      report_delivery: reportDelivery,
      existing_context: `${memoryContext?.learning_summary || ''}\n\n${profileContext}\n\n当前热度雷达内容：${todayHeatSnapshots.map(x => `${x.platform}/${x.account_name}/${x.topic}/${x.signal}`).join('；')}`.trim()
    }))
    setLeadPlan(res!)
    setLastHandoff('热度雷达方案已生成。后续可把高热话题同步到文案、图文、报告承接和发布草稿。')
    setActive('lead')
    await reloadMemoryContext()
  }


  function heatItemToSnapshot(item: any, index = 0): HeatRadarSnapshot {
    const topic = String(item?.title || item?.topic || '未命名热度内容').trim()
    const review = item?.raw?.ai_review || item?.raw?.review || {}
    // 优先显示 AI 业务评分，避免把点赞/评论累加的热度分误当成业务价值分。
    const score = Number(review?.score ?? item?.score ?? 0)
    const decision = String(review?.decision || item?.decision || '').trim()
    const reason = String(review?.reason || item?.reason || '').trim()
    const dimsRaw = review?.buyer_dimensions || review?.dimension_labels || item?.buyer_dimensions || []
    const buyerDimensions = Array.isArray(dimsRaw) ? dimsRaw.map((x: any) => typeof x === 'string' ? x : String(x?.label || x?.key || '')).filter(Boolean).slice(0, 4) : []
    const nextAction = String(review?.next_action || item?.recommended_action || '把这个热度话题转成原创口播/图文，并用资料包承接。')
    return {
      id: String(item?.id || `heat_${Date.now()}_${index}`),
      date: String(item?.date || todayKey()),
      account_id: String(item?.account_id || ''),
      account_name: String(item?.account_name || '公开来源'),
      platform: String(item?.platform || '公开平台'),
      topic,
      signal: `${String(item?.date_basis || '').includes('recent') ? '最近留存' : '真实采集'}：赞${Number(item?.like_count || 0)} / 评${Number(item?.comment_count || 0)} / 藏${Number(item?.favorite_count || 0)} / 分享${Number(item?.share_count || 0)}`,
      score,
      intent: String(item?.intent || (decision ? `AI判断：${decision} / ${score}${buyerDimensions.length ? `｜${buyerDimensions.join(' / ')}` : ''}${reason ? `｜${reason}` : ''}` : (item?.matched_keywords?.length ? `匹配关键词：${item.matched_keywords.join('、')}` : '待 AI 判断客户意图'))),
      source_url: String(item?.url || item?.source_url || ''),
      recommended_action: nextAction,
      lead_magnet: String(item?.lead_magnet || activeReport?.title || '网页资料包'),
      buyer_dimensions: buyerDimensions,
      reason,
      decision
    }
  }

  async function addHeatAccount() {
    const draft = {
      ...heatDraft,
      name: heatDraft.name.trim(),
      url: heatDraft.url.trim(),
      tags: heatDraft.tags.trim(),
      notes: heatDraft.notes.trim(),
      created_at: heatDraft.created_at || new Date().toISOString()
    }
    if (!draft.name && !draft.url) {
      setLastHandoff('请至少填写账号名称或主页/视频链接。')
      return
    }
    try {
      await run('保存热度账号', () => apiPost('/api/heat-radar/accounts', draft))
      await reloadHeatRadarData()
      setHeatDraft({ id: '', name: '', platform: '抖音', url: '', tags: '马来西亚房产,第二家园,海外置业', notes: '', pinned: true, created_at: '' })
      setLastHandoff('博主已保存到账号库。')
    } catch (err: any) {
      setLastHandoff(`保存失败：${err?.message || err}`)
      throw err
    }
  }

  function toggleHeatAccount(id: string) {
    setHeatAccounts(prev => prev.map(x => x.id === id ? { ...x, pinned: !x.pinned } : x))
    setLastHandoff('置顶状态仅临时调整显示顺序；要永久保存请重新保存账号或后续接更新接口。')
  }

  async function removeHeatAccount(id: string) {
    try {
      await run('删除热度账号', () => apiDelete(`/api/heat-radar/accounts/${encodeURIComponent(id)}`))
      await reloadHeatRadarData()
      setLastHandoff('已从账号库移除。')
    } catch (err: any) {
      setLastHandoff(`删除失败：${err?.message || err}`)
      throw err
    }
  }

  async function removeHeatItem(id: string) {
    if (!id) return
    const snapshotBefore = heatSnapshots
    setHeatSnapshots(prev => prev.filter(x => String(x.id) !== String(id)))
    try {
      await run('删除热度热点', () => apiDelete(`/api/heat-radar/items/${encodeURIComponent(id)}`))
      await reloadHeatRadarData()
      setLastHandoff('已从热度雷达删除，不会再进入 Top5。')
    } catch (err: any) {
      setHeatSnapshots(snapshotBefore)
      setLastHandoff(`删除热点失败：${err?.message || err}`)
      throw err
    }
  }

  function importManualHeatData() {
    const lines = manualHeatText.split(/\n+/).map(x => x.trim()).filter(Boolean)
    if (!lines.length) return
    const snapshots = lines.slice(0, 20).map((line, idx): HeatRadarSnapshot => ({
      id: `manual_heat_${Date.now()}_${idx}`,
      date: todayKey(),
      account_id: 'manual',
      account_name: '手动导入',
      platform: '人工采集',
      topic: line.slice(0, 120),
      signal: '人工导入的真实观察内容，等待 AI 分析。',
      score: 70 + Math.max(0, 20 - idx),
      intent: '待判断：税费/流程/城市/身份/教育/预算',
      source_url: '',
      recommended_action: '把这条内容作为选题参考，生成原创口播或图文。',
      lead_magnet: activeReport?.title || '网页资料包'
    }))
    setHeatSnapshots(prev => [...snapshots, ...prev].slice(0, 200))
    setManualHeatText('')
    setLastHandoff('手动热度数据已导入今日热度池。')
  }

  function generateDailyHeatRadar() {
    const cleaned = heatSnapshots.filter(x => !String(x.id || '').startsWith('seed_') && !String(x.signal || '').includes('本地关键词模拟'))
    setHeatSnapshots(cleaned)
    setLastHandoff('已清理本地演示/模拟热度数据。热度雷达只显示自动采集、历史留存或手动导入的真实内容。')
  }

  function pickNextHeatAccountForCrawl() {
    const candidates = heatAccounts.filter(acc => String(acc.url || acc.notes || '').trim())
    if (!candidates.length) return null
    const key = 'ai_video_heat_crawl_cursor_v1'
    const raw = Number(window.localStorage.getItem(key) || '0')
    const index = Number.isFinite(raw) ? Math.max(0, raw) % candidates.length : 0
    const selected = candidates[index]
    window.localStorage.setItem(key, String((index + 1) % candidates.length))
    return selected
  }

  async function runPublicHeatCrawler() {
    const gapKey = 'ai_video_heat_crawl_last_run_at_v1'
    const minGapSeconds = 60
    const lastRun = Number(window.localStorage.getItem(gapKey) || '0')
    const elapsed = (Date.now() - lastRun) / 1000
    if (lastRun && elapsed < minGapSeconds) {
      setLastHandoff(`请稍等 ${Math.ceil(minGapSeconds - elapsed)} 秒再采集下一个账号，避免连续请求过快。`)
      return
    }

    const selectedAccount = pickNextHeatAccountForCrawl()
    if (!selectedAccount) {
      setLastHandoff('请先在账号库添加至少 1 个带主页/视频链接的账号。')
      return
    }

    window.localStorage.setItem(gapKey, String(Date.now()))
    setLastHandoff(`本轮只采集 1 个账号：${selectedAccount.name || selectedAccount.url || '未命名账号'}。`)

    const keywords = Array.from(new Set([...heatRadarSeedKeywords, ...trendKeywords.split(/[,，#\n\s]+/).map(x => x.trim()).filter(Boolean)])).slice(0, 60)
    const res = await run('单账号采集真实热度', () => apiPost<HeatRadarRunResponse>('/api/heat-radar/run-public-crawl', {
      accounts: [selectedAccount],
      keywords,
      limit_per_account: heatCrawlerLimit,
      include_saved_accounts: false,
      save_to_memory: true,
      token: ''
    }))
    setHeatCrawlerResult(res!)
    const snapshots = (res?.top_items || []).map((item, idx) => heatItemToSnapshot(item, idx))
    // 有真实/留存结果才替换看板；没有结果时保留当前看板，避免点一次按钮以后页面变空。
    if (snapshots.length) {
      setHeatSnapshots(snapshots)
    } else {
      setHeatSnapshots(prev => prev.filter(x => !String(x.id || '').startsWith('seed_') && !String(x.signal || '').includes('本地关键词模拟')))
    }
    const topMode = String((res as any)?.top_mode || '')
    const fallbackUsed = Boolean((res as any)?.fallback_used) || topMode === 'recent_top_fallback'
    if (fallbackUsed) {
      setLastHandoff(`本轮账号：${selectedAccount.name || selectedAccount.url || '未命名账号'}。没有采集到新内容，已展示最近留存的 ${snapshots.length || 0} 条内容。`)
    } else if (res?.collected_count) {
      setLastHandoff(`本轮只采集 1 个账号：${selectedAccount.name || selectedAccount.url || '未命名账号'}，采到 ${res.collected_count} 条真实内容。`)
    } else {
      setLastHandoff(`本轮只采集 1 个账号：${selectedAccount.name || selectedAccount.url || '未命名账号'}。没有采到新内容；可补具体视频链接或在备注里粘贴真实数据。`)
    }
  }




  async function auditHeatAccountValue() {
    const keywords = Array.from(new Set([...heatRadarSeedKeywords, ...trendKeywords.split(/[,，#\n\s]+/).map(x => x.trim()).filter(Boolean)])).slice(0, 80)
    const res = await run('审计博主价值', () => apiPost<HeatRadarAccountAuditResponse>('/api/heat-radar/accounts/audit-staleness', {
      accounts: heatAccounts,
      keywords,
      include_saved_accounts: true,
      max_stale_days: 90,
      token: heatAutomationToken
    }))
    setHeatAccountAudit(res!)
    setLastHandoff(`已审计 ${res?.reviewed_count || 0} 个博主：保留 ${res?.keep?.length || 0}，观察 ${res?.watch?.length || 0}，建议暂停 ${res?.archive?.length || 0}。`)
  }


  function cleanupCandidateReviews() {
    return ((heatAccountAudit?.archive || []) as any[]).filter(Boolean)
  }

  function findHeatAccountForReview(review: any) {
    const reviewUrl = String(review?.account_url || review?.url || '').trim().toLowerCase()
    const reviewName = String(review?.account_name || review?.name || '').trim().toLowerCase()
    return heatAccounts.find(acc => {
      const accUrl = String(acc.url || '').trim().toLowerCase()
      const accName = String(acc.name || '').trim().toLowerCase()
      return Boolean(reviewUrl && accUrl && (accUrl === reviewUrl || accUrl.includes(reviewUrl) || reviewUrl.includes(accUrl))) || Boolean(reviewName && accName && accName === reviewName)
    })
  }

  async function removeSuggestedHeatAccount(review: any) {
    const acc = findHeatAccountForReview(review)
    if (!acc?.id) {
      setLastHandoff(`没有在账号库找到「${review?.account_name || '未命名账号'}」的可删除记录；可能已经删除或 URL 不一致。`)
      return
    }
    if (!confirm(`确认删除账号「${acc.name || review?.account_name || '未命名账号'}」？删除后 ECS 后续不会再采这个账号。`)) return
    await removeHeatAccount(acc.id)
    setHeatAccountAudit(prev => prev ? { ...prev, archive: (prev.archive || []).filter((x: any) => x !== review) } : prev)
  }

  async function removeAllSuggestedHeatAccounts() {
    const candidates = cleanupCandidateReviews()
    const matched = candidates.map(r => ({ review: r, account: findHeatAccountForReview(r) })).filter(x => x.account?.id)
    if (!matched.length) {
      setLastHandoff('当前没有可直接删除的建议账号。可以先点“生成清理建议”。')
      return
    }
    if (!confirm(`确认批量删除 ${matched.length} 个建议删除账号？建议只在确认这些账号长期无价值后操作。`)) return
    await run('批量删除建议账号', async () => {
      for (const item of matched) {
        await apiDelete(`/api/heat-radar/accounts/${encodeURIComponent(String(item.account!.id))}`)
      }
    })
    await reloadHeatRadarData()
    setHeatAccountAudit(prev => prev ? { ...prev, archive: [] } : prev)
    setLastHandoff(`已删除 ${matched.length} 个建议删除账号。`)
  }

  async function copyOpenClawExample() {
    const example = {
      token: heatAutomationToken || '如果 Render 设置了 HEAT_RADAR_INGEST_TOKEN，这里填同一个 token',
      source_name: 'openclaw',
      run_id: `openclaw_${todayKey()}`,
      keywords: heatRadarSeedKeywords.slice(0, 8),
      auto_add_accounts: true,
      auto_accept_min_score: 72,
      max_stale_days: 90,
      accounts: [{
        name: 'Justin陈皆廷',
        platform: '抖音',
        url: 'https://www.douyin.com/user/xxx',
        tags: ['马来西亚房产', '第二家园'],
        last_post_at: new Date().toISOString(),
        recent_items: [{
          title: '马来西亚买房税费怎么算',
          url: 'https://www.douyin.com/video/xxx',
          published_at: new Date().toISOString(),
          like_count: 1762,
          comment_count: 80,
          favorite_count: 261,
          share_count: 580
        }]
      }],
      items: []
    }
    await copyTextToClipboard(JSON.stringify(example, null, 2))
    setLastHandoff('已复制 OpenClaw 接入 JSON 示例。让采集器每天 POST 到热度雷达入库接口即可。')
  }

  function applyHeatRewriteVariant(variant: any) {
    if (!variant) return
    setCopy({
      title: String(variant.title || ''),
      hook: String(variant.hook || ''),
      script: String(variant.script || ''),
      description: String(variant.caption || ''),
      tags: Array.isArray(variant.tags) ? variant.tags : [],
      shots: Array.isArray(variant.shots) ? variant.shots : [],
      kb_refs: ['热度雷达改写']
    })
    if (variant.target_audience) setAudience(String(variant.target_audience))
    if (variant.conversion_goal) setConversionGoal(String(variant.conversion_goal))
    if (variant.lead_magnet) {
      setOneClickInstruction(`基于热度雷达选题「${variant.source_topic || variant.title}」生成原创获客短视频。目标客户：${variant.target_audience || audience}。承接资料包：${variant.lead_magnet}。不能照抄竞品，只迁移结构，结尾引导私信领取资料。`)
    }
    setLastHandoff('已把热度雷达仿写稿同步到文案，并确定了目标客户和承接资料包。')
    setActive('copy')
  }

  async function makeHeatRewritePlan() {
    const heatItems = todayHeatSnapshots.slice(0, 3)
    if (!heatItems.length) {
      setLastHandoff('当前没有可用于仿写的热度内容。先采集真实热度，或导入具体视频/笔记链接。')
      return
    }
    const res = await run('AI 仿写热度内容', () => apiPost<HeatRadarRewriteResponse>('/api/heat-radar/rewrite', {
      heat_items: heatItems.map(x => ({
        topic: x.topic,
        platform: x.platform,
        account_name: x.account_name,
        signal: x.signal,
        score: x.score,
        intent: x.intent,
        source_url: x.source_url,
        recommended_action: x.recommended_action,
        lead_magnet: x.lead_magnet
      })),
      industry,
      audience,
      selling_points: limitText(sellingPointsWithProfile, 1800),
      conversion_goal: conversionGoal,
      lead_magnet: activeReport?.title || privateDomainAssets.split(/\n+/)[0] || '网页资料包',
      style,
      target_duration_seconds: 35,
      platform: 'douyin'
    }))
    setHeatRewrite(res!)
    const first = res?.variants?.[0]
    if (first?.target_audience) setAudience(first.target_audience)
    if (first?.conversion_goal) setConversionGoal(first.conversion_goal)
    setLastHandoff('AI 已读取当前热度雷达，完成目标人群判断、原创仿写方案和资料包承接建议。')
  }

  async function copyActiveReportLanding() {
    if (!activeReport) return
    await copyTextToClipboard(reportLandingCopy)
    setReportCopyStatus('已复制网页报告文案/私信话术')
    setTimeout(() => setReportCopyStatus(''), 1800)
  }

  function useReportForContent(report = activeReport) {
    if (!report) return
    setConversionGoal(`私信「${report.keyword}」领取${report.title} / 需求筛选 / 加微信顾问沟通`)
    setOneClickInstruction(`围绕《${report.title}》生成一条获客短视频：开头指出客户常见误区，中间给 3 个判断点，结尾引导私信“${report.keyword}”领取网页报告。字幕要强钩子，不要太书面。`)
    setCoverStyle(report.landingTitle)
    setSubtitleHighlight([report.keyword, '报告', '预算', '避坑', '私信'].filter(Boolean).join(','))
    setLastHandoff(`已把「${report.title}」设为当前转化资料包。一键生成、文案、图文和发布草稿会围绕这个报告承接。`)
    setActive('oneClick')
  }

  function expandKeywordsFromProfile() {
    const seed = splitProfileLines(trendKeywords, ['马来西亚房产', '第二家园', '国际学校'])
    const expanded = Array.from(new Set([
      ...seed,
      ...seed.flatMap(k => [`${k} 条件`, `${k} 费用`, `${k} 流程`, `${k} 避坑`, `${k} 适合谁`, `${k} 预算`, `${k} 线下说明会`]),
      '马来西亚海外置业靠谱吗', '中国人买马来西亚房产流程', '马来西亚第二家园申请条件', '马来西亚国际学校费用', '海外资产配置避坑', '养老度假海外第二居所'
    ])).slice(0, 42)
    setTrendKeywords(expanded.join('，'))
    setLastHandoff('关键词雷达已按“高意向/内容钩子/泛流量”自动扩展，可继续生成获客作战图或今日拍摄任务。')
  }

  async function reloadJobs() {
    const list = await listJobs(20)
    setJobs(Array.isArray(list) ? list : [])
  }

  async function reloadAssets() {
    const list = await apiGet<AssetItem[]>('/api/assets')
    const normalized = Array.isArray(list) ? list.map((item, index) => normalizeAsset(item, index)).filter(item => item.id && item.url) : []
    setAssets(normalized)
    return normalized
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

  async function reloadHeatRadarData() {
    const [accounts, items, reviews] = await Promise.all([
      apiGet<any[]>('/api/heat-radar/accounts').catch(() => []),
      apiGet<any[]>('/api/heat-radar/items').catch(() => []),
      apiGet<any[]>('/api/heat-radar/account-reviews').catch(() => [])
    ])
    if (Array.isArray(accounts)) {
      setHeatAccounts(accounts.map((x: any) => ({
        id: String(x.id || `heat_acc_${Date.now()}_${Math.random()}`),
        name: String(x.name || x.account_name || '未命名账号'),
        platform: String(x.platform || '抖音'),
        url: String(x.url || x.account_url || ''),
        tags: Array.isArray(x.tags) ? x.tags.join(',') : String(x.tags || x.positioning || ''),
        notes: String(x.notes || x.reason || ''),
        pinned: Boolean(x.pinned ?? true),
        created_at: String(x.created_at || '')
      })))
    }
    if (Array.isArray(reviews)) setHeatAccountReviews(reviews)
    if (Array.isArray(items)) {
      const snapshots = items
        .filter((item: any) => !item?.deleted && !String(item?.source_mode || '').match(/seed|demo|local/i))
        .filter((item: any) => {
          const review = item?.raw?.ai_review || item?.raw?.review || {}
          const decision = String(review?.decision || item?.decision || '').toLowerCase()
          const score = Number(review?.score ?? item?.score ?? item?.heat_score ?? 0)
          // Top5 展示 accept/watch/高分候选；archive/reject 仍保留在滚动报告和审核记录里解释原因，不进入 Top5。
          if (decision === 'archive' || decision === 'reject') return score >= 58
          return decision === 'accept' || decision === 'watch' || score >= 45
        })
        .sort((a: any, b: any) => Number((b?.raw?.ai_review || b?.raw?.review || {})?.score ?? b?.score ?? b?.heat_score ?? 0) - Number((a?.raw?.ai_review || a?.raw?.review || {})?.score ?? a?.score ?? a?.heat_score ?? 0))
        .slice(0, 80)
        .map((item, idx) => heatItemToSnapshot(item, idx))
      setHeatSnapshots(prev => {
        // 后端热度项以 Supabase 为准；只保留手动导入内容，避免软删后旧 state 又被合并回来。
        const manual = prev.filter(x => String(x.id || '').startsWith('manual_heat_'))
        const seen = new Set(snapshots.map(x => x.id))
        return [...snapshots, ...manual.filter(x => !seen.has(x.id))].slice(0, 200)
      })
    }
  }


  async function reloadCollectorProgress() {
    const status = await apiGet<CollectorProgressState>('/api/collector/runs/latest?events_limit=40').catch(() => null)
    if (status) setCollectorProgress(status)
    return status
  }

  async function reloadDigitalHumanProviders() {
    const list = await apiGet<DigitalHumanProviderOption[]>('/api/digital-human/providers').catch(() => [])
    setDigitalHumanProviders(Array.isArray(list) ? list : [])
  }

  async function createEcsCollectorCommand() {
    const token = heatAutomationToken.trim()
    if (token) window.localStorage.setItem('heatRadarIngestToken', token)
    const limit = Math.max(1, Math.min(120, Number(ecsCollectorCount) || 1))
    const command = await run('创建 ECS 采集命令', () => apiPost<any>('/api/collector/commands', {
      token,
      limit,
      account: ecsCollectorAccount.trim(),
      dry_run: ecsDryRunMode,
      headful: true,
      no_delay: ecsNoDelayMode || limit <= 1,
      mode: ecsDryRunMode ? 'dry_run' : 'manual',
      message: `网页触发采集：${ecsCollectorAccount.trim() || '账号库顺序'} / ${limit} 个账号${ecsNoDelayMode || limit <= 1 ? ' / 快速模式不等待' : ' / 正常限速'}`
    }))
    setLastHandoff(`已创建采集命令：${command?.command_id || command?.id || 'queued'}。ECS 上运行 command_worker.py 后会自动领取。`)
    await reloadCollectorProgress()
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
    reloadJobs().catch(() => null)
    reloadMemoryContext(true).catch(() => null)
    reloadHeatRadarData().catch(() => null)
    reloadCollectorProgress().catch(() => null)
    reloadDigitalHumanProviders().catch(() => null)
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
    if (active !== 'lead' && active !== 'collector') return
    reloadCollectorProgress().catch(() => null)
    const timer = window.setInterval(() => reloadCollectorProgress().catch(() => null), 3000)
    return () => window.clearInterval(timer)
  }, [active])

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
    const res = await run('上传素材', () => uploadAssets(files, assetUploadFolder === 'all' ? 'self' : assetUploadFolder))
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

  async function handleShootingScriptFiles(files: FileList | null) {
    if (!files || files.length === 0) return
    const list = Array.from(files)
    try {
      await run('上传脚本资料', () => uploadAssets(files, 'provided'))
      const textFile = list.find(file => /\.(txt|md|srt|csv)$/i.test(file.name))
      if (textFile) {
        const text = (await textFile.text()).slice(0, 6000)
        setCopy(prev => ({
          ...prev,
          script: prev.script || text,
          hook: prev.hook || text.split(/\n+/).map(x => x.trim()).filter(Boolean)[0]?.slice(0, 120) || prev.hook,
        }))
        setManualText(prev => `${prev ? prev + '\n\n' : ''}[脚本资料：${textFile.name}]\n${text.slice(0, 2500)}`)
      }
      await reloadAssets()
      setLastHandoff(`已上传 ${list.length} 个脚本/资料文件。TXT/MD/SRT 会自动写入文案区；PDF/Word 先入素材库，后续可由 AI 按文件内容解析。`)
    } catch (err: any) {
      setError(`脚本资料上传失败：${err?.message || err}`)
    }
  }

  async function analyzeHeatVideoIntake() {
    const url = videoIntakeUrl.trim() || primaryHeat?.source_url || ''
    if (!url) { setError('请先粘贴一个具体视频/笔记链接，或选择一条已采集热点。'); return }
    const res = await run('下载并分析视频', () => apiPost<any>('/api/heat-radar/video-intake', {
      token: heatAutomationToken,
      account_name: primaryHeat?.account_name || heatDraft.name || '',
      account_url: heatDraft.url || '',
      platform: primaryHeat?.platform || heatDraft.platform || '抖音',
      video_url: url,
      title: primaryHeat?.topic || copy.title || '',
      tags: heatRadarSeedKeywords.slice(0, 12),
      notes: '页面手动触发：下载视频后交给视频理解模型，再做账号价值判断',
      auto_save_review: true
    }))
    setVideoIntakeResult(res || null)
    await reloadHeatRadarData()
    setLastHandoff('视频已进入下载/理解/审核流程。若平台限制下载，会保留链接和标题并给出规则评分。')
  }

  async function makeShootingPlan() {
    const res = await run('生成运营拍摄任务', () => apiPost<ShootingPlanResponse>('/api/shooting-plan', {
      title: copy.title,
      script: currentScript,
      industry,
      audience,
      selling_points: sellingPointsWithProfile,
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
      selling_points: limitText(`${sellingPointsWithProfile}\n获客地域/人群：${leadRegion}\n转化目标：${conversionGoal}`, 950),
      style,
      duration_seconds: autoProjectSeconds,
      knowledge_examples: manualText ? [manualText] : []
    }))
    setCopy(res!)
    openKnowledgeSave('直接生成文案', res!)
    setLastHandoff('新文案已生成。确认入知识库后，可以继续进入配音导演。')
    setActive('copy')
  }

  async function generateDigitalHumanIntroCopy() {
    const introSeconds = Math.min(18, Math.max(8, Math.round(selectedAssetEstimatedSeconds ? Math.min(selectedAssetEstimatedSeconds * 0.28, 15) : 12)))
    const res = await run('生成数字人开场稿', () => apiPost<GeneratedCopy>('/api/generate-copy', {
      topic: `生成 ${introSeconds} 秒数字人真人开场口播：先用强痛点/反差吸引，再自然引出马来西亚房产/第二家园/国际学校/楼盘介绍，结尾接“后面给你看项目和周边环境”。`,
      industry,
      audience,
      selling_points: limitText(`${sellingPointsWithProfile}

【数字人开场规则】只写 5-15 秒开场；像真人顾问对镜头说话；不要写完整长视频；不要夸张承诺；最后一句自然切到楼盘/风光素材。`, 1100),
      style: `${style}，真人顾问口播，短句，像叔叔/房产顾问面对客户讲话。`,
      duration_seconds: introSeconds,
      knowledge_examples: [manualText, heatRewrite?.variants?.[0]?.script || '', referenceText || ''].filter(Boolean).slice(0, 3)
    }))
    setCopy(res!)
    const scriptLines = [res?.hook, res?.script].filter(Boolean).join('\n').split(/\n+/).map(x => x.trim()).filter(Boolean).slice(0, 4)
    setVoiceSegments(scriptLines.length ? scriptLines.map(text => ({ ...defaultSegment, text, emotion: '自然可信', speed_ratio: 1.06, pause_after_ms: 260 })) : [])
    setLastHandoff('数字人开场稿已生成。下一步先生成配音，再到“数字人开场”用 fal 真人模板口型同步。')
    setActive('voice')
  }

  async function generateScriptFromSelectedAssets() {
    const targetSeconds = safeProjectDuration(selectedAssetEstimatedSeconds || 45)
    const res = await run('按素材时长生成旁白稿', () => apiPost<GeneratedCopy>('/api/generate-copy', {
      topic: `根据已选楼盘/风光/B-roll 素材，生成约 ${targetSeconds} 秒完整旁白稿：前面接数字人开场，后面按素材顺序介绍项目、生活、配套、教育和私信转化。`,
      industry,
      audience,
      selling_points: limitText(`${sellingPointsWithProfile}

【已选素材顺序和时长】
${selectedAssetScriptContext || '暂无素材，请按马来西亚楼盘、风光、配套、教育医疗的顺序生成通用旁白。'}

【写法要求】按素材画面顺序写旁白；不要照抄同行；不要承诺收益；每 1-2 句适合一段字幕；结尾引导私信领取资料。`, 1600),
      style: `${style}，房产顾问旁白，口语化，画面转场自然。`,
      duration_seconds: targetSeconds,
      knowledge_examples: [copy.script, manualText, heatRewrite?.variants?.[0]?.script || ''].filter(Boolean).slice(0, 3)
    }))
    setCopy(res!)
    setVoiceSegments((res?.script || '').split(/\n+/).map(x => x.trim()).filter(Boolean).slice(0, 10).map(text => ({ ...defaultSegment, text })))
    setLastHandoff('已按素材总时长生成完整旁白稿。现在去配音导演生成最终旁白，再合成数字人开场 + 素材混剪。')
    setActive('voice')
  }

  async function rewrite() {
    const res = await run('原创改写', () => apiPost<GeneratedCopy>('/api/rewrite-from-inspiration', {
      reference_text: referenceText || '请根据业务信息生成原创老板口播文案。',
      industry,
      audience,
      selling_points: limitText(`${sellingPointsWithProfile}\n获客地域/人群：${leadRegion}\n转化目标：${conversionGoal}`, 950),
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
      selling_points: sellingPointsWithProfile
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
      selling_points: sellingPointsWithProfile
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
  }


  async function makeDigitalHuman() {
    const currentStatus = String(digitalHuman?.status || '').toLowerCase()
    const hasRunningJimengTask = Boolean(digitalHuman?.job_id && !digitalHuman?.video_url && !['failed', 'error', 'done'].includes(currentStatus))
    if (hasRunningJimengTask) {
      setError('已有数字人任务正在生成中，不要重复提交。请直接查询当前任务结果，或等任务结束后再新建。')
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
      const refreshed = await reloadAssets().catch(() => [] as AssetItem[])
      const newIntro = (refreshed || []).find(a => a.filename === res.video_name || a.url === res.video_url || a.source_type === 'digital_human_intro')
      if (newIntro?.id) setSelectedMaterialIds(prev => prev.includes(newIntro.id) ? prev : [newIntro.id, ...prev])
      setLastHandoff('数字人片段已生成并保存到素材库，并已自动放到素材顺序最前面。接下来选择楼盘/风光素材，再按素材时长补全旁白。')
    } else {
      setLastHandoff('fal 数字人任务已提交。不要重复提交；系统会自动查询，完成后会自动回存素材库。')
    }
  }

  function clearDigitalHumanTask() {
    setDigitalHuman(null)
    setDigitalHumanPollCount(0)
    setDigitalHumanLastChecked('')
    try { window.localStorage.removeItem(DIGITAL_HUMAN_TASK_KEY) } catch {}
    setLastHandoff('已清除当前数字人任务。可以重新提交一个新的 fal 真人模板口型同步任务。')
  }

  async function checkDigitalHumanStatus(silent = false) {
    if (!digitalHuman?.job_id) { if (!silent) setError('当前没有可查询的数字人 task_id。'); return }
    const taskModel = getDigitalHumanTaskModel(digitalHuman, digitalHumanJimengModel)
    const isFalTask = String(digitalHuman.job_id || '').startsWith('fal:') || String(digitalHuman.engine || '').startsWith('fal:') || taskModel.includes('sync-lipsync')
    const raw: any = digitalHuman.raw || {}
    const endpoint = String(raw.endpoint || raw.model || (taskModel.includes('sync-lipsync') ? taskModel : '') || '').replace(/^fal:/, '')
    const fetchStatus = () => isFalTask
      ? apiPost<DigitalHumanCreateResponse>('/api/digital-human/status', {
          job_id: digitalHuman.job_id,
          model: 'fal_lipsync',
          endpoint: endpoint || 'fal-ai/sync-lipsync',
          status_url: raw.status_url || '',
          response_url: raw.response_url || '',
          raw,
        })
      : apiGet<DigitalHumanCreateResponse>(`/api/digital-human/status/${encodeURIComponent(digitalHuman.job_id || '')}?model=${encodeURIComponent(taskModel)}`)
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
      const refreshed = await reloadAssets().catch(() => [] as AssetItem[])
      const newIntro = (refreshed || []).find(a => a.filename === res.video_name || a.url === res.video_url || a.source_type === 'digital_human_intro')
      if (newIntro?.id) setSelectedMaterialIds(prev => prev.includes(newIntro.id) ? prev : [newIntro.id, ...prev])
      setLastHandoff('数字人片段已生成并保存到素材库，并已自动放到素材顺序最前面。接下来选择楼盘/风光素材，再按素材时长补全旁白。')
    } else if (String(res.status || '').toLowerCase() === 'failed') {
      setLastHandoff('当前数字人任务不可继续查询。请查看火山原始返回，必要时清除当前任务后重新提交。')
    } else {
      setLastHandoff('数字人仍在生成或排队中。系统会每 20 秒自动查询一次，也可以手动点击查询。')
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
        image_seconds: Math.min(20, Math.max(0.8, imageSeconds)),
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
      subtitle_style_preset: subtitlePreset,
      subtitle_keywords: subtitleHighlight,
      subtitle_segments: safeSubtitleSegments
    }))
    setVideo(res!)
    setLastHandoff('视频已出片。已把配音和字幕压到画面上，先预览一遍再决定是否调字幕位置。')
  }

  async function chatEditVideo() {
    const richInstruction = `${editInstruction}\n字幕模板：${subtitlePreset}，字号 ${subtitleSize}，重点词：${subtitleHighlight}\n处理顺序：先按素材生成画面底片，再叠加配音和字幕，不把配音分段绑定到单个视频片段。`
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
      prompt: imagePromptForVisualOnly(imagePrompt),
      title: copy.title || industry,
      style: '精美商业短视频素材，真实感，高级质感，适合做抖音/小红书封面和图文背景，保留干净留白，标题后期叠加',
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
      script: currentScript || copy.description || sellingPointsWithProfile,
      industry,
      audience,
      selling_points: sellingPointsWithProfile,
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

  const stageCards: Array<{ key: ModuleKey; label: string; done: boolean; value: string }> = [
    { key: 'copy', label: '1 文案生产', done: Boolean(copy.hook || copy.script), value: copy.title || '先出标题/脚本' },
    { key: 'shooting', label: '2 脚本/拍摄', done: Boolean(shootingPlan), value: shootingPlan?.summary || '上传脚本或生成任务单' },
    { key: 'digitalHuman', label: '3 数字人开场', done: Boolean(digitalHuman?.video_url), value: digitalHuman?.video_url ? '开场已生成' : (digitalHumanAvatarId ? '已选模板' : '待选真人模板') },
    { key: 'voice', label: '4 配音分段', done: Boolean(audio), value: voiceSegments.length ? `${voiceSegments.length} 段 · ${selectedVoiceName}` : '待配音' },
    { key: 'video', label: '5 成片合成', done: Boolean(video?.video_url), value: video?.video_name || '待合成' },
    { key: 'subtitleCover', label: '6 图文窗口', done: Boolean(cover || subtitleAI || generatedImage || graphicPost), value: graphicPost ? `${graphicPost.images.length}张图文` : cover?.cover_name || generatedImage?.image_name || (subtitleAI ? '重点字幕已生成' : '待处理') },
    { key: 'growth', label: '7 流量监控', done: Boolean(growthDecision), value: growthDecision?.decision || '待复盘' }
  ]

  const digitalHumanStatus = String(digitalHuman?.status || '').toLowerCase()
  const hasRunningDigitalHumanTask = Boolean(digitalHuman?.job_id && !digitalHuman?.video_url && !['failed', 'error', 'done'].includes(digitalHumanStatus))
  const digitalHumanPrimaryLabel = hasRunningDigitalHumanTask ? '查询当前数字人任务' : '生成数字人片段'
  const contentNavKeys: ModuleKey[] = ['copy','voice','digitalHuman','assets','video','subtitleCover','growth','collector']

  useEffect(() => {
    setNavMobileOpen(false)
  }, [active])

  useEffect(() => {
    if (typeof window === 'undefined') return
    const syncLayout = () => {
      if (window.innerWidth > 1100) setNavMobileOpen(false)
      if (window.innerWidth <= 1280) setNavCollapsed(false)
    }
    syncLayout()
    window.addEventListener('resize', syncLayout)
    return () => window.removeEventListener('resize', syncLayout)
  }, [])

  return <div className={`appShell responsiveShell ${navCollapsed ? 'navCollapsed' : ''} ${navMobileOpen ? 'navMobileOpen' : ''}`}>
    {navMobileOpen && <button className="navBackdrop" aria-label="关闭菜单" onClick={() => setNavMobileOpen(false)} />}
    <aside className={`studioNav responsiveNav ${navCollapsed ? 'collapsed' : ''}`}>
      <div className="navTopRow">
        <div className="brandMark">
          <div className="logo">AI</div>
          <div><strong>AI 视频增长中枢</strong><span>采集 · 创作 · 合成 · 转化</span></div>
        </div>
        <button className="navIconBtn desktopOnly" onClick={() => setNavCollapsed(v => !v)} title={navCollapsed ? '展开左侧菜单' : '收起左侧菜单'}>{navCollapsed ? '»' : '«'}</button>
      </div>
      <button className="startButton" onClick={() => setActive('dashboard')}>开始使用</button>
      <nav>
        {modules.filter(item => ['dashboard','lead','competitor'].includes(item.key)).map(item => <button key={item.key} className={active === item.key ? 'active' : ''} onClick={() => setActive(item.key)}>
          <span>{item.icon}</span><b>{item.title}</b><em>{item.tag}</em>
        </button>)}
        <button className={contentNavOpen ? 'groupHeader open' : 'groupHeader'} onClick={() => setContentNavOpen(!contentNavOpen)}>
          <span>生</span><b>内容生产</b><em>{contentNavOpen ? '收起' : '展开'}</em>
        </button>
        {contentNavOpen && contentNavKeys.map(key => modules.find(item => item.key === key)).filter(Boolean).map(item => <button key={item!.key} className={`subNav ${active === item!.key ? 'active' : ''}`} onClick={() => setActive(item!.key)}>
          <span>{item!.icon}</span><b>{item!.title}</b><em>{item!.tag}</em>
        </button>)}
        {modules.filter(item => ['strategy','collector','monitor'].includes(item.key)).map(item => <button key={item.key} className={active === item.key ? 'active' : ''} onClick={() => setActive(item.key)}>
          <span>{item.icon}</span><b>{item.title}</b><em>{item.tag}</em>
        </button>)}
      </nav>
      <div className="miniStatus"><span>API</span><strong className={health?.ok ? 'greenText' : 'redText'}>{health?.ok ? '已连接' : '未连接'}</strong><small>{health?.tts_provider || 'waiting'} · {health?.ark_video_model || '-'}</small></div>
    </aside>

    <main className="studioMain">
      <header className="heroHeader">
        <div>
          <div className="heroToolbar">
            <button className="navIconBtn mobileOnly" onClick={() => setNavMobileOpen(true)} aria-label="打开菜单">☰</button>
            <span className="eyebrow">AI Growth Studio</span>
          </div>
          <h1>同行洞察、脚本生产、素材成片一体化</h1>
          <p>先看真实热点，再做脚本、素材、数字人或真人拍摄，最后复盘投流。</p>
        </div>
        <div className="scoreCard"><span>当前进度</span><strong>{leadScore}%</strong><small>{leadScore >= 80 ? '可以进入发布前检查' : '继续补齐内容和素材'}</small></div>
      </header>

      {error && <div className="globalError">{error}</div>}
      {busy && <div className="busy">正在执行：{busy}</div>}
      <div className="handoffBar">
        <div><strong>当前状态</strong><span>{lastHandoff}</span></div>
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
        {stageCards.map((s, idx) => <button key={s.label} className={`stage ${s.done ? 'done' : ''} ${active === s.key ? 'active' : ''}`} onClick={() => setActive(s.key)}>
          <span>{idx + 1}</span><strong>{s.label}</strong><em>{s.value}</em>
        </button>)}
      </section>

      {active === 'oneClick' && <section className="card modulePanel oneClickPanel">
        <div className="sectionHeader"><div><h2>一键生成中心</h2><p>想快就一键出方案；想细调就进文案、配音、素材、剪辑单独改。</p></div><Button busy={busy === '一键生成完整方案' ? busy : ''} label="一键生成方案" onClick={runOneClickGenerate} /></div>
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
          {modules.filter(x => ['lead','competitor','copy','shooting','assets','subtitleCover','growth','collector'].includes(x.key)).map(item => <button className="moduleCard compact" key={item.key} onClick={() => setActive(item.key)}>
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
          <div className="monitorCard"><span>企业存储</span><strong>{health?.memory_status?.ok ? 'Supabase 正常' : (health?.memory_enabled ? 'Supabase 异常' : '未接 Supabase')}</strong><p>{health?.workspace_id || 'default'} · 严格模式 {health?.core_storage_strict ? '开' : '关'} · {health?.memory_status?.message || ''}</p></div>
          <div className="monitorCard"><span>R2 素材</span><strong>{health?.r2_enabled ? '已配置' : '未配置'}</strong><p>素材强制 R2：{health?.require_r2_assets ? '开' : '关'}。正式使用建议开启。</p></div>
          <div className="monitorCard"><span>任务队列</span><strong>{jobs.filter(j => j.status === 'running' || j.status === 'queued').length} 个进行中</strong><p>最近任务 {jobs.length} 条。长任务后续统一走 jobs。</p></div>
        </div>
        <div className="pluginGrid">{pluginMatrix.map(p => <div className="pluginCard" key={p.name}><strong>{p.name}</strong><p>{p.desc}</p><em>{p.status}</em></div>)}</div>
        <div className="todoPanel"><h3>下一步待办</h3>{pipelineTodos.map(item => <button key={item.text} className={item.ok ? 'done' : ''} onClick={() => setActive(item.go)}><span>{item.ok ? '✓' : '•'}</span>{item.text}</button>)}</div>
        <div className="memoryBox"><strong>AI 学习摘要</strong><p>{learningSummary}</p></div>
      </section>}


      {active === 'lead' && <section className="card modulePanel leadRadarPanel heatRadarPanel heatRadarV3">
        <div className="radarHeaderV3">
          <div>
            <Pill tone="green">Heat Radar</Pill>
            <h2>热度雷达 · 今日重点 Top5</h2>
            <p>这里不展开每个博主的全部内容，只展示今日/最近最值得跟进的 5 条真实热点。账号详情和对应历史热点放到「账号库」里点开查看。</p>
          </div>
          <div className="heatHeroActions">
            <Button busy={busy === '单账号采集真实热度' ? busy : ''} label="尝试云端采集" onClick={runPublicHeatCrawler} kind="ghost" />
            <Button busy={busy === 'AI 仿写热度内容' ? busy : ''} label="AI 读 Top5 并改写" onClick={makeHeatRewritePlan} kind="primary" disabled={!todayHeatSnapshots.length} />
          </div>
        </div>

        <div className="radarMetricStrip">
          <div><span>热点池</span><strong>{todayHeatSnapshots.length}</strong><em>今日/最近入库</em></div>
          <div><span>真实指标</span><strong>{realHeatCount}</strong><em>含点赞/评论/收藏/分享</em></div>
          <div><span>账号库</span><strong>{heatAccounts.length}</strong><em>{health?.workspace_id || 'default'}</em></div>
          <div><span>AI 状态</span><strong>{heatRewrite ? '已改写' : '待分析'}</strong><em>{heatWorkbenchStatus}</em></div>
        </div>
        <div className="ecsCollectorPanel liveCollectorPanel">
          <div className="ecsCollectorHead">
            <div>
              <Pill tone="green">ECS Worker</Pill>
              <h3>采集任务进度</h3>
              <p>网页负责下发采集命令、看进度和错误；ECS 负责打开抖音、提取视频，再提交主网站豆包分析并汇总到热度雷达。</p>
            </div>
            <div className="ecsStatusMini">
              <span>账号库 {heatAccounts.length}</span>
              <span>{collectorProgress?.run?.status || '等待任务'}</span>
            </div>
          </div>
          <div className="ecsControlGrid">
            <Field label="本次采集账号数"><input type="number" min="1" max="120" value={ecsCollectorCount} onChange={e => setEcsCollectorCount(e.target.value)} /></Field>
            <Field label="每日自动时间"><input value={ecsCollectorTime} onChange={e => setEcsCollectorTime(e.target.value)} placeholder="02:00" /></Field>
            <Field label="单独跑某个账号，可选"><input value={ecsCollectorAccount} onChange={e => setEcsCollectorAccount(e.target.value)} placeholder="例如：房产马来小哥" /></Field>
            <label className="checkline compact"><input type="checkbox" checked={ecsDryRunMode} onChange={e => setEcsDryRunMode(e.target.checked)} /> 仅测试，不上传</label>
            <label className="checkline compact"><input type="checkbox" checked={ecsNoDelayMode} onChange={e => setEcsNoDelayMode(e.target.checked)} /> 快速模式：账号间不等待</label>
          </div>
          <div className="buttonRow">
            <Button busy={busy === '创建 ECS 采集命令' ? busy : ''} label="网页下发采集命令" onClick={createEcsCollectorCommand} kind="primary" />
            <Button label="刷新进度" onClick={() => reloadCollectorProgress()} kind="ghost" />
            <button className="btn ghost" onClick={() => navigator.clipboard?.writeText(ecsRunCommand)}>复制手动命令</button>
          </div>
          <div className="collectorTickerBox">
            <div className="collectorTickerLabel">滚动报告</div>
            <div className="collectorTickerTrack"><span>{collectorReportLine}</span></div>
          </div>
          <div className="collectorLiveGrid">
            <div className="collectorRunCard">
              <span>当前任务</span>
              <strong>{collectorProgress?.run?.stage || '未开始'}</strong>
              <p>{collectorProgress?.run?.message || 'ECS 上运行 command_worker.py 后，可从这里点按钮触发采集。'}</p>
              <div className="collectorStats"><b>{Number(collectorProgress?.run?.completed_accounts || 0)} / {Number(collectorProgress?.run?.total_accounts || 0)}</b><em>账号进度</em></div>
              {collectorProgress?.run?.last_error && <div className="warn compactWarn">{collectorProgress.run.last_error}</div>}
            </div>
            <div className="collectorRunCard">
              <span>视频结果</span>
              <strong>{Number(collectorProgress?.run?.success_videos || 0)} 成功 / {Number(collectorProgress?.run?.failed_videos || 0)} 失败</strong>
              <p>当前账号：{collectorProgress?.run?.current_account || '暂无'}<br />当前视频：{collectorProgress?.run?.current_video || '暂无'}</p>
            </div>
          </div>
          <div className="collectorEventList compactReport onePreviewReport">
            {latestCollectorEvent ? <div className={`collectorEvent ${latestCollectorEvent.level === 'error' ? 'error' : ''}`}>
              <span>{latestCollectorEvent.stage || 'event'}</span>
              <strong>{formatCollectorEventLine(latestCollectorEvent, 0)}</strong>
              <small>{latestCollectorEvent.video_url || latestCollectorEvent.account_url || latestCollectorEvent.created_at}</small>
            </div> : <Empty>暂无采集事件。先在 ECS 启动命令监听，或手动运行一次采集。</Empty>}
            {collectorEventsForReport.length > 1 && <details className="collectorHistoryDetails">
              <summary>展开完整采集报告（{collectorEventsForReport.length} 条）</summary>
              {collectorEventsForReport.slice(1, 18).map((ev, idx) => <div className={`collectorEvent ${ev.level === 'error' ? 'error' : ''}`} key={ev.id || `${ev.stage}-${idx}`}>
                <span>{ev.stage || 'event'}</span>
                <strong>{formatCollectorEventLine(ev, idx + 1)}</strong>
                <small>{ev.video_url || ev.account_url || ev.created_at}</small>
              </div>)}
            </details>}
          </div>
          <details className="ecsCommandDetails">
            <summary>手动命令 / 自动化设置</summary>
            <div className="ecsCommandGrid">
              <div><strong>先测试不上传</strong><code>{ecsDryRunCommand}</code><button onClick={() => navigator.clipboard?.writeText(ecsDryRunCommand)}>复制</button></div>
              <div><strong>正式跑并上传</strong><code>{ecsRunCommand}</code><button onClick={() => navigator.clipboard?.writeText(ecsRunCommand)}>复制</button></div>
              <div><strong>设置每日自动跑</strong><code>{ecsDailyCommand}</code><button onClick={() => navigator.clipboard?.writeText(ecsDailyCommand)}>复制</button></div>
              <div><strong>网页按钮触发前提</strong><code>python command_worker.py</code><button onClick={() => navigator.clipboard?.writeText('python command_worker.py')}>复制</button></div>
            </div>
          </details>
        </div>

        <div className="accountCleanupPanel">
          <div className="cleanupHead">
            <div>
              <Pill tone="orange">账号清理建议</Pill>
              <h3>建议删除 / 暂停采集账号</h3>
              <p>AI 会按最近采集结果、成交顾虑价值和内容垂直度判断账号；只把长期无价值账号列为建议删除，不会自动删。</p>
            </div>
            <div className="buttonRow mini">
              <Button busy={busy === '审计博主价值' ? busy : ''} label="生成清理建议" onClick={auditHeatAccountValue} kind="ghost" />
              <button className="btn dangerGhost" onClick={removeAllSuggestedHeatAccounts}>批量删除建议项</button>
            </div>
          </div>
          {heatAccountAudit ? <>
            <div className="cleanupStats">
              <span>保留 <b>{heatAccountAudit.keep?.length || 0}</b></span>
              <span>观察 <b>{heatAccountAudit.watch?.length || 0}</b></span>
              <span>建议删除 <b>{cleanupCandidateReviews().length}</b></span>
            </div>
            {cleanupCandidateReviews().length === 0 ? <Empty>暂无建议删除账号。watch 账号先保留观察，避免误删。</Empty> : <div className="cleanupList">
              {cleanupCandidateReviews().slice(0, 1).map((r: any, idx: number) => {
                const matched = findHeatAccountForReview(r)
                return <div className="cleanupItem" key={`${r.account_url || r.account_name || idx}`}>
                  <div><strong>{r.account_name || matched?.name || '未命名账号'}</strong><p>{r.reason || r.next_action || '近期内容没有明显成交价值，建议暂停或删除。'}</p><small>{r.account_url || matched?.url || '无链接'}</small></div>
                  <div className="cleanupScore"><b>{Number(r.score || 0)}</b><em>{r.decision || 'archive'}</em></div>
                  <button className="btn dangerGhost" onClick={() => removeSuggestedHeatAccount(r)}>{matched ? '删除账号' : '未匹配'}</button>
                </div>
              })}
              {cleanupCandidateReviews().length > 1 && <details className="cleanupMore"><summary>展开剩余 {cleanupCandidateReviews().length - 1} 个建议</summary>
                {cleanupCandidateReviews().slice(1).map((r: any, idx: number) => {
                  const matched = findHeatAccountForReview(r)
                  return <div className="cleanupItem compact" key={`${r.account_url || r.account_name || idx}-more`}>
                    <div><strong>{r.account_name || matched?.name || '未命名账号'}</strong><p>{r.reason || r.next_action || '建议暂停采集。'}</p></div>
                    <div className="cleanupScore"><b>{Number(r.score || 0)}</b><em>{r.decision || 'archive'}</em></div>
                    <button className="btn dangerGhost" onClick={() => removeSuggestedHeatAccount(r)}>{matched ? '删除账号' : '未匹配'}</button>
                  </div>
                })}
              </details>}
            </div>}
          </> : <Empty>还没生成清理建议。先让采集跑一轮，再点“生成清理建议”。</Empty>}
        </div>

        <div className="radarWorkbenchGrid">
          <div className="radarTopPanel">
            <div className="miniHeader">
              <div><h3>今日重点 Top5</h3><p>按 AI 分数、客户顾虑价值和真实互动排序；archive/reject 不进这里，原因放在滚动报告。</p></div>
              <Pill tone="blue">只看重点</Pill>
            </div>
            <div className="radarTopList">
              {todayHeatSnapshots.length === 0 && <Empty>暂无入选候选。上方滚动报告会说明每条视频为什么没入选；也可以降低阈值或换更垂直的马来西亚账号。</Empty>}
              {todayHeatSnapshots.slice(0, 1).map((item, index) => <article className="radarTopItem" key={item.id}>
                <div className="radarRank">{index + 1}</div>
                <div className="radarTopBody">
                  <div className="timelineMeta"><span>{item.platform || '平台'}</span><span>{item.account_name || '未命名账号'}</span><strong>{item.score || 0} 分</strong></div>
                  <h4>{item.topic || '未命名热点'}</h4>
                  {!!item.buyer_dimensions?.length && <div className="dimensionChips">{item.buyer_dimensions.map(dim => <em key={dim}>{dim}</em>)}</div>}
                  <p>{item.intent || item.recommended_action || '等待 AI 判断客户意图。'}</p>
                  <em>{item.signal || '暂无真实互动指标'}</em>
                  <div className="timelineActions compactActions">
                    {item.source_url && <a href={item.source_url} target="_blank" rel="noreferrer">打开原链接</a>}
                    <button onClick={() => { setVideoIntakeUrl(item.source_url || ''); setLastHandoff('已选中这条热点，可在下方继续做视频理解或 AI 改写。') }}>选中分析</button>
                    <button onClick={makeHeatRewritePlan}>基于 Top5 改写</button>
                    <button className="dangerTextBtn" onClick={() => removeHeatItem(item.id)}>删除热点</button>
                  </div>
                </div>
              </article> )}
              {todayHeatSnapshots.length > 1 && <details className="topMoreDetails">
                <summary>展开剩余 {todayHeatSnapshots.length - 1} 条候选</summary>
                {todayHeatSnapshots.slice(1).map((item, restIndex) => { const index = restIndex + 1; return <article className="radarTopItem" key={item.id}>
                <div className="radarRank">{index + 1}</div>
                <div className="radarTopBody">
                  <div className="timelineMeta"><span>{item.platform || '平台'}</span><span>{item.account_name || '未命名账号'}</span><strong>{item.score || 0} 分</strong></div>
                  <h4>{item.topic || '未命名热点'}</h4>
                  {!!item.buyer_dimensions?.length && <div className="dimensionChips">{item.buyer_dimensions.map(dim => <em key={dim}>{dim}</em>)}</div>}
                  <p>{item.intent || item.recommended_action || '等待 AI 判断客户意图。'}</p>
                  <em>{item.signal || '暂无真实互动指标'}</em>
                  <div className="timelineActions compactActions">
                    {item.source_url && <a href={item.source_url} target="_blank" rel="noreferrer">打开原链接</a>}
                    <button onClick={() => { setVideoIntakeUrl(item.source_url || ''); setLastHandoff('已选中这条热点，可在下方继续做视频理解或 AI 改写。') }}>选中分析</button>
                    <button onClick={makeHeatRewritePlan}>基于 Top5 改写</button>
                    <button className="dangerTextBtn" onClick={() => removeHeatItem(item.id)}>删除热点</button>
                  </div>
                </div>
              </article> })}
              </details>}
            </div>
          </div>

          <div className="radarRewriteDock">
            <div className="miniHeader"><div><h3>AI 热点改写</h3><p>读取 Top5 的标题、账号、链接和互动信号，先判断客户意图，再生成原创角度和脚本。</p></div><Pill tone="purple">热点 → 脚本</Pill></div>
            {!heatRewrite && <div className="rewriteEmptyState compact"><strong>等待 AI 改写</strong><p>{heatSourceLines.length ? `已锁定热点依据：${shortText(heatSourceLines[0], 96)}` : '有真实热点后，点“AI 读 Top5 并改写”。'}</p><Button busy={busy === 'AI 仿写热度内容' ? busy : ''} label="AI 拆解 Top5" onClick={makeHeatRewritePlan} kind="primary" disabled={!todayHeatSnapshots.length} /></div>}
            {heatRewrite && <div className="heatRewriteV2 compactRewrite">
              <div className="targetStrip compact"><div><span>目标人群</span><strong>{heatRewrite.chosen_target}</strong><p>{heatRewrite.target_reason}</p></div><div><span>内容目标</span><strong>{heatRewrite.content_objective}</strong><p>{heatRewrite.primary_intent}</p></div><div><span>承接资料</span><strong>{heatRewrite.lead_magnet}</strong><p>{heatRewrite.rewrite_strategy?.slice(0, 2).join(' / ')}</p></div></div>
              <div className="rewriteVariantGrid v2">{heatRewrite.variants?.slice(0, 3).map((v, i) => <div className="rewriteVariantCard" key={`${v.title}-${i}`}>
                <Pill tone={i === 0 ? 'green' : 'purple'}>{i === 0 ? '推荐主推' : `备选 ${i + 1}`}</Pill>
                <strong>{v.title}</strong><p>{v.hook}</p><small>来源：{v.source_topic}</small><div className="scriptPreview">{v.script}</div>
                <div className="miniActions"><button onClick={() => applyHeatRewriteVariant(v)}>同步到文案</button><button onClick={() => { applyHeatRewriteVariant(v); setActive('copy') }}>进入文案生产</button></div>
              </div>)}</div>
            </div>}
          </div>
        </div>

        <details className="radarIngestDock">
          <summary><strong>采集 / 视频分析 / 备用导入</strong><span>原「采集接入」已合并到雷达；云 Worker、OpenClaw、手动真实数据都从这里进入。</span></summary>
          <div className="radarIngestGrid">
            <div className="heatPanel videoIngestMini">
              <div className="miniHeader"><div><h3>具体视频分析</h3><p>粘贴具体视频/笔记链接，后端下载后交给视频理解模型；如果平台限制下载，也会保留标题和链接入库。</p></div></div>
              <input value={videoIntakeUrl} onChange={e => setVideoIntakeUrl(e.target.value)} placeholder="粘贴具体视频/笔记链接；也可以先点上方某条热点的“选中分析”" />
              <div className="buttonRow"><Button busy={busy === '下载并分析视频' ? busy : ''} label="下载并分析视频" onClick={analyzeHeatVideoIntake} kind="soft" />{videoIntakeResult && <Pill tone={videoIntakeResult.r2_video_url ? 'green' : 'orange'}>{videoIntakeResult.review?.decision || '待审核'} · {videoIntakeResult.review?.score || 0}分</Pill>}</div>
            </div>
            <div className="heatPanel">
              <div className="miniHeader"><div><h3>备用导入</h3><p>采集器暂不可用时，粘贴真实标题、链接和互动指标，先跑 AI 判断和改写流程。</p></div><Pill tone="orange">备用</Pill></div>
              <Field label="粘贴竞品内容 / 评论 / 热词"><textarea value={manualHeatText} onChange={e => setManualHeatText(e.target.value)} placeholder="一行一条：标题 + 链接 + 赞/评论/收藏/分享" /></Field>
              <div className="buttonRow"><button className="btn soft" onClick={importManualHeatData}>导入真实数据</button><button className="btn ghost" onClick={generateDailyHeatRadar}>清理演示缓存</button></div>
            </div>
            <div className="heatPanel openClawMini">
              <div className="miniHeader"><div><h3>OpenClaw / 云 Worker</h3><p>外部采集器每天把结果 POST 到这里。网站只负责入库、评分、R2 留存和 AI 改写。</p></div><Pill tone="purple">接口</Pill></div>
              <div className="endpointBox"><span>POST</span><code>{API_BASE}/api/heat-radar/openclaw/ingest</code></div>
              <Field label="接口 Token，可选"><input value={heatAutomationToken} onChange={e => setHeatAutomationToken(e.target.value)} placeholder="网页下发采集可留空；ECS 上传仍由后端校验" /></Field>
              <div className="buttonRow"><button className="btn soft" onClick={copyOpenClawExample}>复制 JSON 示例</button><button className="btn ghost" onClick={auditHeatAccountValue}>审计账号价值</button></div>
            </div>
          </div>
        </details>

        {heatCrawlerResult && <div className="resultBox heatCrawlerResult slim"><h3>{heatCrawlerResult.analysis?.summary || '真实热度采集完成'}</h3><div className="splitGrid"><div><h4>跟进选题</h4>{(heatCrawlerResult.analysis?.content_angles || []).map((x: string) => <p key={x}>· {x}</p>)}</div><div><h4>客户意图</h4>{(heatCrawlerResult.analysis?.customer_intents || []).map((x: string) => <p key={x}>· {x}</p>)}</div><div><h4>资料承接</h4>{(heatCrawlerResult.analysis?.lead_magnets || []).map((x: string) => <p key={x}>· {x}</p>)}</div></div>{heatCrawlerResult.warnings?.slice(0, 3).map(w => <div className="warn compactWarn" key={w}>{w}</div>)}</div>}
      </section>}

      {active === 'strategy' && <section className="card modulePanel industryProfilePanel">
        <div className="sectionHeader"><div><h2>行业获客档案</h2><p>把业务定位、监听词、目标客群、资料包和承接钩子沉淀成长期档案。后面截流雷达、文案、图文、剪辑、私信回复都会自动读取。</p></div><div className="headerActions"><Button label="套用马来西亚房产模板" onClick={applyMalaysiaPreset} kind="ghost" /><Button busy={busy === '保存行业档案' ? busy : ''} label="保存行业档案" onClick={saveCustomerProfile} kind="soft" /><Button busy={busy === '生成获客自动化作战图' ? busy : ''} label="生成获客作战图" onClick={makeLeadPlan} kind="primary" /></div></div>
        <div className="profileHero">
          <div><span>业务定位</span><strong>{businessPositioning || industry}</strong><p>{conversionGoal}</p></div>
          <div><span>私域承接</span><strong>{reportDelivery}</strong><p>{privateDomainAssets.split(/\n+/)[0] || '资料包/报告/清单'}</p></div>
        </div>
        <div className="profileGrid">
          <Field label="行业/赛道"><input value={industry} onChange={e => setIndustry(e.target.value)} /></Field>
          <Field label="业务定位"><input value={businessPositioning} onChange={e => setBusinessPositioning(e.target.value)} placeholder="例如：中国人在马来西亚房产置业" /></Field>
          <Field label="目标客户"><textarea value={audience} onChange={e => setAudience(e.target.value)} /></Field>
          <Field label="获客地域 / 人群"><textarea value={leadRegion} onChange={e => setLeadRegion(e.target.value)} /></Field>
          <Field label="转化目标"><input value={conversionGoal} onChange={e => setConversionGoal(e.target.value)} /></Field>
          <Field label="内容风格"><input value={style} onChange={e => setStyle(e.target.value)} /></Field>
        </div>
        <div className="profileSection"><h3>监听词与客户分层</h3><div className="grid2"><Field label="监听关键词库" hint="用逗号或换行分隔，同行采集、雷达和选题会读取。"><textarea value={trendKeywords} onChange={e => setTrendKeywords(e.target.value)} /></Field><Field label="目标客户分层" hint="把不同人群拆开，生成内容时会按人群出不同钩子。"><textarea value={customerSegments} onChange={e => setCustomerSegments(e.target.value)} /></Field></div></div>
        <div className="profileSection"><h3>私域承接与内容栏目</h3><div className="grid2"><Field label="私域承接物 / 报告清单"><textarea value={privateDomainAssets} onChange={e => setPrivateDomainAssets(e.target.value)} /></Field><Field label="内容栏目 / 选题方向"><textarea value={contentPillars} onChange={e => setContentPillars(e.target.value)} /></Field></div></div>
        <div className="profileSection"><h3>内容承接规则</h3><Field label="口播/拍摄风格要求（给内容生产用）"><textarea value={shootingBrief} onChange={e => setShootingBrief(e.target.value)} /></Field><Field label="报告/微信承接方式"><input value={reportDelivery} onChange={e => setReportDelivery(e.target.value)} /></Field></div>
        <div className="profileQuickActions">
          <button onClick={() => setActive('copy')}>用档案生成视频脚本</button>
          <button onClick={generateDirectCopy}>生成短视频文案</button>
          <button onClick={makeGraphicPost}>生成图文引流包</button>
          <button onClick={makeShootingPlan}>生成拍摄方案</button>
        </div>
        <div className="memoryBox"><strong>AI 学习状态：{memoryStatus}</strong><p>{learningSummary}</p><button onClick={() => reloadMemoryContext(true)}>刷新数据库记忆</button></div>
        {ad && <div className="resultBox"><h3>{ad.decision}</h3><p>建议预算：{ad.suggested_budget} · 置信度：{Math.round(ad.confidence * 100)}%</p><div className="chips">{ad.target_audience?.map(x => <Pill key={x}>{x}</Pill>)}</div>{ad.optimization_tips?.map(x => <p key={x}>· {x}</p>)}</div>}
      </section>}

      {active === 'trend' && <section className="card modulePanel">
        <div className="sectionHeader"><div><h2>行业爆点与截流雷达</h2><p>根据搜索词、评论、同行账号和采集内容，生成可截流的机会、监控关键词和下一步动作。</p></div><Button busy={busy === '生成行业爆点雷达' ? busy : ''} label="自动采集/生成行业雷达" onClick={makeTrendRadar} /></div>
        <div className="grid2">
          <Field label="监控关键词"><input value={trendKeywords} onChange={e => setTrendKeywords(e.target.value)} placeholder="海外房产,第二家园,海外置业,子女教育,养老度假" /></Field>
          <Field label="同行备注汇总"><textarea value={`${competitorNotes}${extract?.summary ? '\n' + extract.summary : ''}`} readOnly placeholder="竞品账号库和同行采集结果会自动汇总到这里" /></Field>
        </div>
        {trendRadar ? <div className="resultBox"><h3>{trendRadar.summary}</h3><div className="trendGrid">{trendRadar.hot_topics?.map(item => <div className="trendCard" key={item.title}><div className="heat"><span>{item.heat}</span><em>热度</em></div><strong>{item.title}</strong><p>{item.reason}</p><small>角度：{item.angle}</small><small>钩子：{item.suggested_hook}</small>{item.risk && <div className="warn">{item.risk}</div>}</div>)}</div><div className="splitGrid"><div><h4>内容角度</h4>{trendRadar.content_angles?.map(x => <p key={x}>· {x}</p>)}</div><div><h4>拍摄建议</h4>{trendRadar.shooting_suggestions?.map(x => <p key={x}>· {x}</p>)}</div><div><h4>监控词</h4><div className="chips">{trendRadar.monitor_keywords?.map(x => <Pill key={x}>{x}</Pill>)}</div></div></div></div> : <Empty>保存客户定位、账号库和采集结果后，系统会自动读取数据库生成行业雷达。</Empty>}
      </section>}

      {active === 'competitor' && <section className="card modulePanel accountLibraryPanel">
        <div className="sectionHeader"><div><h2>账号库</h2><p>固定监控的博主/同行账号单独管理。热度雷达只看采集结果，这里只管账号、平台、标签和采集备注。</p></div><div className="headerActions"><Button label="刷新账号库" onClick={() => reloadHeatRadarData()} kind="ghost" /><Button busy={busy === '保存热度账号' ? busy : ''} label="保存账号" onClick={addHeatAccount} kind="soft" /></div></div>
        <div className="accountLibraryGrid">
          <div className="accountEditorCard">
            <div className="grid2"><Field label="账号名称"><input value={heatDraft.name} onChange={e => setHeatDraft({ ...heatDraft, name: e.target.value })} placeholder="例如：Justin陈皆廷" /></Field><Field label="平台"><select value={heatDraft.platform} onChange={e => setHeatDraft({ ...heatDraft, platform: e.target.value })}><option>抖音</option><option>小红书</option><option>视频号</option><option>快手</option><option>其他</option></select></Field></div>
            <Field label="主页/视频链接"><input value={heatDraft.url} onChange={e => setHeatDraft({ ...heatDraft, url: e.target.value })} placeholder="账号主页或重点视频链接" /></Field>
            <Field label="监控标签"><input value={heatDraft.tags} onChange={e => setHeatDraft({ ...heatDraft, tags: e.target.value })} placeholder="马来西亚房产,第二家园,生活方式" /></Field>
            <Field label="备注 / 采集策略"><textarea value={heatDraft.notes} onChange={e => setHeatDraft({ ...heatDraft, notes: e.target.value })} placeholder="例如：优先看置顶视频、近 3 天视频；生活类内容也可作为买房客户顾虑素材。" /></Field>
            <div className="syncStatusBar"><span>API：{API_BASE}</span><span>Supabase：{health?.memory_enabled ? '已连接' : '未连接'}</span><span>Workspace：{health?.workspace_id || 'default'}</span><span>R2：{health?.r2_enabled ? '已连接' : '未连接'}</span></div>
          </div>
          <div className="accountListCard">
            <div className="heatAccountFilters"><input value={heatAccountSearch} onChange={e => setHeatAccountSearch(e.target.value)} placeholder="搜索账号名 / 标签 / 链接" /><select value={heatPlatformFilter} onChange={e => setHeatPlatformFilter(e.target.value)}><option value="all">全部平台</option><option value="抖音">抖音</option><option value="小红书">小红书</option><option value="视频号">视频号</option><option value="快手">快手</option><option value="其他">其他</option></select></div>
            <div className="heatAccountList compact">{filteredHeatAccounts.length === 0 && <Empty>暂无账号。先在左侧添加账号，保存后会进入统一账号库。</Empty>}{filteredHeatAccounts.map(acc => { const open = Boolean(expandedHeatAccounts[acc.id]); const relatedHeat = heatSnapshots.filter(item => { const a = `${item.account_id || ''} ${item.account_name || ''}`.toLowerCase(); const n = `${acc.id || ''} ${acc.name || ''}`.toLowerCase(); return Boolean(acc.name && a.includes(acc.name.toLowerCase())) || Boolean(acc.id && a.includes(acc.id.toLowerCase())) || Boolean(acc.url && String(item.source_url || '').includes(acc.url)); }).slice(0, 8); return <div className="heatAccountRow" key={acc.id}><button className="heatAccountRowHead" onClick={() => setExpandedHeatAccounts(prev => ({ ...prev, [acc.id]: !open }))}><strong>{acc.name || '未命名账号'}</strong><span>{acc.platform}</span><em>{acc.tags || '未设置标签'}</em><small>{relatedHeat.length ? `${relatedHeat.length} 条热点` : '无热点'}</small><b>{open ? '收起' : '展开'}</b></button>{open && <div className="heatAccountRowBody"><p>{acc.notes || '暂无备注'}</p><small>{acc.url || '未填链接'}</small><div className="accountHeatMiniList">{relatedHeat.length === 0 ? <Empty>这个账号还没有对应热点；采集完成后会显示在这里。</Empty> : relatedHeat.map((item, idx) => <div className="accountHeatMini" key={item.id}><span>{idx + 1}</span><div><strong>{item.topic}</strong><p>{item.signal || item.intent}</p></div><em>{item.score || 0}分</em></div>)}</div><div className="miniActions"><button onClick={() => { setVideoIntakeUrl(acc.url); setActive('lead') }}>去雷达分析</button><button onClick={() => toggleHeatAccount(acc.id)}>{acc.pinned ? '取消置顶' : '置顶'}</button><button onClick={() => removeHeatAccount(acc.id)}>删除</button></div></div>}</div> })}</div>
          </div>
        </div>
      </section>}

      {active === 'collector' && <section className="card modulePanel">
        <div className="sectionHeader"><div><h2>实时采集 Log</h2><p>这里不再做“状态卡片”，直接显示 ECS command_worker 回传的采集、AI 判断、入库和报错日志。状态统计已并入热度雷达。</p></div><div className="headerActions"><Button label="刷新日志" onClick={() => reloadCollectorProgress()} kind="ghost" /><Button busy={busy === '采集/拆解同行内容' ? busy : ''} label="手动采集链接" onClick={collectCompetitor} kind="soft" /></div></div>
        <div className="grid2">
          <Field label="抖音分享口令 / 视频链接"><textarea value={sourceUrl} onChange={e => setSourceUrl(e.target.value)} placeholder="直接粘贴：1.58 ... https://v.douyin.com/... 复制此链接..." /></Field>
          <Field label="手动粘贴竞品文案 / 豆包 App 识别稿"><textarea value={manualText} onChange={e => setManualText(e.target.value)} placeholder="如果已经有真实口播稿，粘这里。" /></Field>
        </div>
        <div className="collectorTerminal">
          <div className="collectorTerminalHead">
            <span>RUN</span><strong>{collectorProgress?.run?.status || 'waiting'}</strong><em>{collectorProgress?.run?.run_id || '暂无 run_id'}</em>
          </div>
          <div className="collectorTerminalBody">
            {collectorEventsForReport.length === 0 ? <pre>[waiting] 暂无实时日志。ECS Worker 领取命令后会回传：打开账号、抓取视频、AI 判断、入库、失败原因。</pre> : collectorEventsForReport.map((ev, index) => <pre key={ev.id || `${ev.created_at}_${index}`} className={ev.level === 'error' ? 'error' : ''}>[{safeText(ev.created_at, '--').slice(11, 19) || '--'}] {formatCollectorEventLine(ev, index)}</pre>)}
          </div>
          <div className="collectorTerminalFoot"><span>{collectorReportLine}</span><button onClick={() => reloadCollectorProgress()}>刷新</button><button onClick={() => setShowCookiePanel(v => !v)}>{showCookiePanel ? '收起 Cookies' : 'Cookies'}</button></div>
        </div>
        <details className="collectorTools" open={false}>
          <summary>展开：手动采集链接 / 自动学习设置</summary>
          <div className="agentPanel compactTools">
            <div className="sectionHeader compact"><div><h3>自动学习同行打法</h3><p>读取账号库和链接，沉淀钩子、节奏和承接方式，不复制原文。</p></div><div className="buttonRow mini"><Button label="刷新智能体" onClick={() => reloadAgentStatus()} kind="ghost" /><Button busy={busy === '自动采集/学习同行打法' ? busy : ''} label="立即跑一轮" onClick={runAutoAgent} kind="soft" /></div></div>
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
        </details>
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

      {active === 'copy' && <section className="card modulePanel copyFirstPanel">
        <div className="sectionHeader"><div><h2>第一步：数字人开场 / 完整旁白</h2><p>先做 5-15 秒数字人开场稿；数字人生成并入素材库后，再按楼盘/风光素材总时长补全完整旁白。</p></div><div className="headerActions"><Button busy={busy === '生成数字人开场稿' ? busy : ''} label="生成数字人开场稿" onClick={generateDigitalHumanIntroCopy} kind="primary" /><Button busy={busy === '按素材时长生成旁白稿' ? busy : ''} label="按素材时长补全旁白" onClick={generateScriptFromSelectedAssets} kind="soft" /></div></div>
        <div className="productionRouteGrid">
          {[
            ['digital_human','数字人开场','先生成 5-15 秒真人模板口播，自动入素材库做片头'],
            ['mixed_assets','素材混剪','楼盘/马来西亚风光/周边配套按时长生成旁白'],
            ['self_shoot','真人拍摄','自己拍摄时生成提词器、镜头和补拍清单'],
            ['graphic_post','图文引流','适合小红书/朋友圈收藏型内容']
          ].map(([value,title,desc]) => <button key={value} className={oneClickOutputType === value ? 'selected' : ''} onClick={() => setOneClickOutputType(value)}><strong>{title}</strong><span>{desc}</span></button>)}
        </div>
        <div className="grid4"><Field label="当前生产方式"><input value={oneClickOutputType === 'digital_human' ? '数字人开场' : oneClickOutputType === 'self_shoot' ? '真人拍摄' : oneClickOutputType === 'graphic_post' ? '图文' : '素材混剪'} readOnly /></Field><Field label="素材总时长"><input value={selectedAssetEstimatedSeconds ? `约 ${selectedAssetEstimatedSeconds} 秒 / ${selectedMaterialIds.length} 个素材` : '未选素材，可后面再选'} readOnly /></Field><Field label="开头策略"><input value="痛点/反差/警告/结果" readOnly /></Field><Field label="当前风险"><input value={matchedBadWords.length ? `${matchedBadWords.length} 个敏感词` : '暂无明显风险'} readOnly /></Field></div>
        <div className="buttonRow"><Button busy={busy === '生成数字人开场稿' ? busy : ''} label="数字人开场稿" onClick={generateDigitalHumanIntroCopy} kind="primary" /><Button busy={busy === '按素材时长生成旁白稿' ? busy : ''} label="按素材时长补全旁白" onClick={generateScriptFromSelectedAssets} kind="soft" /><Button busy={busy === '原创改写' ? busy : ''} label="同行仿写改写" onClick={rewrite} kind="ghost" /><Button busy={busy === '文案细改' ? busy : ''} label="AI 细改" onClick={refineCopy} disabled={!currentScript} kind="ghost" /><Button label="加入配音分段" onClick={() => { setVoiceSegments(currentScript.split(/\n+/).map(x => x.trim()).filter(Boolean).slice(0, 10).map(text => ({ ...defaultSegment, text }))); setActive('voice') }} kind="ghost" /></div>
        <div className="flowSource"><strong>当前参考</strong><span>{industry} · {audience}</span><span>热点/同行：{extract?.summary ? shortText(extract.summary) : '暂无'}</span><span>记忆库：{memoryContext?.memory_enabled ? '已连接' : '本地模式'}</span></div>
        <div className="copyEditor"><Field label="标题"><input value={copy.title} onChange={e => setCopy({ ...copy, title: e.target.value })} /></Field><Field label="黄金三秒钩子"><textarea value={copy.hook} onChange={e => setCopy({ ...copy, hook: e.target.value })} /></Field><Field label="完整视频脚本"><textarea className="scriptArea" value={copy.script} onChange={e => setCopy({ ...copy, script: e.target.value })} placeholder="这里精修完整脚本；可以来自热度仿写、PDF资料、拍摄稿或手动输入。" /></Field><Field label="发布简介"><textarea value={copy.description} onChange={e => setCopy({ ...copy, description: e.target.value })} /></Field><Field label="细改要求"><input value={refineInstruction} onChange={e => setRefineInstruction(e.target.value)} /></Field></div>
        <div className="chips">{matchedBadWords.length ? matchedBadWords.map(x => <Pill key={x} tone="red">风险词：{x}</Pill>) : <Pill tone="green">违禁词初筛通过</Pill>}</div>
      </section>}

      {active === 'voice' && <section className="card modulePanel">
        <div className="sectionHeader"><div><h2>第四步：配音导演</h2><p>把口播拆成几段，调整语速、停顿和重点。生成后剪辑会按真实音频时长对齐字幕。</p></div></div>
        <div className="grid4"><Field label="音色"><select value={voice} onChange={e => setVoice(e.target.value)}>{voices.map(v => <option key={v.id} value={v.id}>{v.name || v.id}</option>)}</select></Field><Field label="配音风格"><select value={voiceStyle} onChange={e => setVoiceStyle(e.target.value)}>{['老板压迫感','真实聊天感','短视频强钩子','销售转化感','案例讲述感','沉稳信任感'].map(x => <option key={x}>{x}</option>)}</select></Field><Field label="情绪强度"><select value={voiceIntensity} onChange={e => setVoiceIntensity(e.target.value)}>{['轻微','标准','强烈'].map(x => <option key={x}>{x}</option>)}</select></Field><div className="stackButtons"><Button busy={busy === '生成配音导演稿' ? busy : ''} label="生成配音导演稿" onClick={makeVoiceDirector} kind="ghost" disabled={!currentScript} /><Button busy={busy === '生成分段情绪配音' ? busy : ''} label="重新生成配音并校准时间轴" onClick={makeSegmentTTS} disabled={!currentScript} /></div></div>
        {voiceNotes.length > 0 && <div className="tips">{voiceNotes.map(x => <span key={x}>{x}</span>)}</div>}
        <div className="hintBox">提示：想要更像真人口播，优先调语速、停顿和重点句；情绪只是辅助。</div>
        <div className="buttonRow"><button className="addSegment" onClick={addVoiceSegment}>+ 手动添加空白分段</button><button className="addSegment" onClick={addSelectedScriptAsSegment}>+ 把选中文案加入分段</button></div>
        <div className="segments">{voiceSegments.map((seg, i) => <div className="segmentCard" key={i}><div className="segmentHead"><strong>第 {i + 1} 段 · {audio?.segments?.[i]?.duration?.toFixed?.(1) || segmentSeconds[i] || estimateSeconds(seg.text, seg.speed_ratio)} 秒</strong><div><button onClick={() => moveVoiceSegment(i, -1)}>↑</button><button onClick={() => moveVoiceSegment(i, 1)}>↓</button><button onClick={() => removeVoiceSegment(i)}>删除</button></div></div><textarea value={seg.text} onChange={e => updateVoiceSegment(i, { text: e.target.value })} /><div className="presetRow"><button onClick={() => applyVoicePreset(i, 'urgent')}>急迫提醒</button><button onClick={() => applyVoicePreset(i, 'emphasis')}>重点加重</button><button onClick={() => applyVoicePreset(i, 'calm')}>冷静信任</button><button onClick={() => applyVoicePreset(i, 'cta')}>结尾号召</button></div><div className="segmentGrid"><Field label="情绪"><select value={seg.emotion} onChange={e => updateVoiceSegment(i, { emotion: e.target.value })}>{emotionOptions.map(x => <option key={x}>{x}</option>)}</select></Field><Field label={`语速 ${seg.speed_ratio.toFixed(2)}x`}><input type="range" min="0.65" max="1.55" step="0.01" value={seg.speed_ratio} onChange={e => updateVoiceSegment(i, { speed_ratio: Number(e.target.value) })} /></Field><Field label={`音量 ${seg.volume_ratio.toFixed(2)}x`}><input type="range" min="0.45" max="2.2" step="0.01" value={seg.volume_ratio} onChange={e => updateVoiceSegment(i, { volume_ratio: Number(e.target.value) })} /></Field><Field label={`停顿 ${seg.pause_after_ms}ms`}><input type="range" min="0" max="2200" step="50" value={seg.pause_after_ms} onChange={e => updateVoiceSegment(i, { pause_after_ms: Number(e.target.value) })} /></Field></div></div>)}</div>
        {audio && <div className="mediaBox"><audio controls src={audio.file_url} /><a href={audio.file_url} target="_blank">下载配音</a><Pill tone="green">已生成 {audio.segments?.length || voiceSegments.length} 段时间轴</Pill>{audio.warning && <div className="warn">{audio.warning}</div>}</div>}
      </section>}

      {active === 'digitalHuman' && <section className="card modulePanel">
        <div className="sectionHeader"><div><h2>第三步：数字人开场</h2><p>用 fal.ai：真人模板视频 + 配音音频 → 口型同步开场片段。生成后自动保存到素材库并放到素材顺序最前。</p></div><Button busy={busy === '生成数字人片段' || busy === '查询数字人结果' ? busy : ''} label={digitalHumanPrimaryLabel} onClick={hasRunningDigitalHumanTask ? () => checkDigitalHumanStatus(false) : makeDigitalHuman} disabled={!hasRunningDigitalHumanTask && (!audio?.file_name || !digitalHumanAvatarId || !digitalHumanConsent)} /></div>
        <div className="grid3">
          <Field label="数字人形象素材" hint="fal 推荐上传本人授权的 5-20 秒正面半身说话视频；静态预览可用照片。"><select value={digitalHumanAvatarId} onChange={e => setDigitalHumanAvatarId(e.target.value)}><option value="">选择已上传照片/视频</option>{assets.map(a => <option key={a.id} value={a.id}>{a.kind} · {a.original_name || a.filename}</option>)}</select></Field>
          <Field label="动作参考视频（可选）" hint="fal 当前不需要；后期 MuseTalk/LivePortrait 才用。"><select value={digitalHumanDriverId} onChange={e => setDigitalHumanDriverId(e.target.value)}><option value="">不用动作参考</option>{assets.filter(a => a.kind === 'video').map(a => <option key={a.id} value={a.id}>{a.original_name || a.filename}</option>)}</select></Field>
          <Field label="数字人引擎" hint="去掉冗余平台，默认只保留真正已接入/可兜底的路线。"><select value={digitalHumanEngine} onChange={e => setDigitalHumanEngine(e.target.value)}><option value="fal_lipsync">推荐：fal.ai 真人模板口型同步</option><option value="preview">免费兜底：静态预览/素材口播</option><option value="webhook">外部 GPU Worker/API</option><option value="jimeng">火山即梦/OmniHuman（备用）</option></select></Field>
          {digitalHumanEngine === 'jimeng' && <Field label="即梦模型" hint="模拟真人优先选 OmniHuman1.5；普通视频生成可用视频3.0。"><select value={digitalHumanJimengModel} onChange={e => setDigitalHumanJimengModel(e.target.value)}><option value="omnihuman15">OmniHuman1.5（单图+音频真人口播）</option><option value="quick">数字人快速模式</option><option value="video30">即梦视频生成3.0（图生视频）</option></select></Field>}
        </div>
        <label className="checkline"><input type="checkbox" checked={digitalHumanConsent} onChange={e => setDigitalHumanConsent(e.target.checked)} /> 我确认已获得本人形象和声音授权，仅用于合法商业内容。</label>

        <div className="digitalHumanLeanGuide">
          <div><strong>推荐模板</strong><p>上传 5-20 秒正面半身真人视频，人物看镜头、光线稳定、少转头。原视频说什么不重要，fal 会用新配音同步嘴型。</p></div>
          <div><strong>当前输入</strong><p>版本：#{digitalHumanVersion}<br />模板：{digitalHumanAvatarId || '未选择'}<br />配音：{audio?.file_name || '未生成'}<br />开场稿：{shortText(currentScript || '', 90) || '未生成'}</p></div>
          <div><strong>生成后动作</strong><p>成功后自动入素材库，并自动放到素材顺序第 1 个；后面继续添加楼盘、风光、学校、配套 B-roll。</p></div>
        </div>
        {hasRunningDigitalHumanTask && <div className="warn strongWarn">已有数字人任务正在排队/生成中。请不要再次点击提交；等待当前任务完成或点击“查询当前数字人任务”。</div>}
        {digitalHuman && <div className="resultBox"><h3>数字人 #{digitalHumanVersion} 结果</h3><p>{digitalHuman.message}</p><div className="resultMeta"><Pill tone={digitalHuman.video_url ? 'green' : digitalHuman.status === 'failed' ? 'red' : 'orange'}>状态：{digitalHuman.status || 'running'}</Pill>{digitalHumanLastChecked && <Pill tone="blue">最近查询：{digitalHumanLastChecked}</Pill>}{digitalHumanPollCount > 0 && <Pill tone="purple">已查询 {digitalHumanPollCount} 次</Pill>}</div>{digitalHuman.job_id && <p className="muted">任务 ID：{digitalHuman.job_id}<br />查询引擎：{getDigitalHumanTaskProvider(digitalHuman, digitalHumanJimengModel)}</p>}{digitalHuman.job_id && !digitalHuman.video_url && <div className="warn">数字人生成是异步任务。系统会每 20 秒自动查一次；fal 通常较快，如果长时间没有结果，请查看 Render Logs 或 fal 后台任务。</div>}{digitalHuman.warnings?.map(w => <div className="warn" key={w}>{w}</div>)}{digitalHuman.job_id && !digitalHuman.video_url && <div className="buttonRow"><button className="btn soft" onClick={() => checkDigitalHumanStatus(false)} disabled={busy === '查询数字人结果'}>{busy === '查询数字人结果' ? '查询中…' : '立即查询数字人结果'}</button><button className="btn ghost danger" onClick={clearDigitalHumanTask}>清除当前任务</button></div>}{digitalHuman.raw && <details className="rawBox"><summary>查看原始返回</summary><pre>{JSON.stringify(digitalHuman.raw, null, 2).slice(0, 2600)}</pre></details>}{digitalHuman.video_url && <video controls src={digitalHuman.video_url} className="previewVideo" />}{digitalHuman.video_url && <a className="download" href={digitalHuman.video_url} target="_blank">下载/打开数字人 #{digitalHumanVersion} 片段</a>}</div>}
      </section>}

      {active === 'assets' && <section className="card modulePanel">
        <div className="sectionHeader"><div><h2>第四步：素材选择与截取</h2><p>数字人开场会自动排在最前；这里继续选择楼盘、马来西亚风光、周边配套、学校和生活素材，再按总时长补全旁白。</p></div><Button busy={busy === '按素材时长生成旁白稿' ? busy : ''} label="按素材时长生成旁白" onClick={generateScriptFromSelectedAssets} kind="soft" /></div>
        <div className={`uploadDrop ${isDraggingAssets ? 'dragging' : ''} ${busy === '上传素材' ? 'uploading' : ''}`} onDragOver={onAssetDragOver} onDragLeave={onAssetDragLeave} onDrop={onAssetDrop} aria-busy={busy === '上传素材'}>
          <div className="uploadIcon">↑</div>
          <div className="uploadCopy">
            <strong>{busy === '上传素材' ? '正在上传到素材库…' : '拖入图片 / 视频，或点击选择文件'}</strong>
            <span>支持 JPG、PNG、WEBP、MP4、MOV，多选上传后会自动进入 R2，并默认加入本次素材顺序。</span>
            <div className="uploadHints"><em>图片：可设置停留秒数</em><em>视频：可预览并截取片段</em><em>顺序：下方可拖前/上移下移</em></div>
          </div>
          <div className="uploadSide">
            <select value={assetUploadFolder} onChange={e => setAssetUploadFolder(e.target.value as AssetFolderKey)} disabled={busy === '上传素材'}>
              <option value="self">自己拍的素材</option>
              <option value="provided">别人提供的素材</option>
              <option value="image">图片素材</option>
            </select>
            <label className={`uploadPick ${busy === '上传素材' ? 'disabled' : ''}`}>
              选择文件
              <input type="file" multiple accept="image/*,video/*" onChange={e => { handleUpload(e.target.files); e.currentTarget.value = '' }} disabled={busy === '上传素材'} />
            </label>
          </div>
        </div>
        <div className="assetToolbar">
          <input placeholder="搜索文件名" value={assetSearch} onChange={e => setAssetSearch(e.target.value)} />
          <select value={assetKindFilter} onChange={e => setAssetKindFilter(e.target.value as any)}><option value="all">全部类型</option><option value="video">只看视频</option><option value="image">只看图片</option></select>
          <select value={assetFolderFilter} onChange={e => setAssetFolderFilter(e.target.value as AssetFolderKey)}><option value="all">全部文件夹</option><option value="self">自己拍的素材</option><option value="provided">别人提供的素材</option><option value="image">图片素材</option><option value="collected">采集视频</option><option value="ai">AI生成图</option></select>
          <select value={assetTimeFilter} onChange={e => setAssetTimeFilter(e.target.value as any)}><option value="all">全部时间</option><option value="today">今天上传</option><option value="7d">近 7 天</option><option value="30d">近 30 天</option></select>
          <select value={assetSort} onChange={e => setAssetSort(e.target.value as any)}><option value="new">最新优先</option><option value="old">最早优先</option><option value="size_desc">文件从大到小</option><option value="size_asc">文件从小到大</option><option value="name">名称排序</option></select>
          <button className="btn ghost" onClick={() => { setAssetSearch(''); setAssetKindFilter('all'); setAssetFolderFilter('all'); setAssetTimeFilter('all'); setAssetSort('new') }}>重置</button>
        </div>
        <div className="assetStats"><Pill tone="blue">自有素材 {materialAssets.length}</Pill><Pill tone="green">已选 {selectedMaterialIds.length}</Pill><Pill tone="purple">采集视频 {collectedVideos.length}</Pill>{selectedMaterialAssets.length > 0 && <span>已选顺序：{selectedMaterialAssets.map(a => a.original_name || a.filename).slice(0, 4).join(' → ')}{selectedMaterialAssets.length > 4 ? ` 等 ${selectedMaterialAssets.length} 个` : ''}</span>}</div>
        <div className="assetFolderTabs">{[
          ['all','全部素材'], ['self','自己拍的'], ['provided','别人提供'], ['image','图片素材'], ['collected','采集视频'], ['ai','AI生成图']
        ].map(([key,label]) => <button key={key} className={assetFolderFilter === key ? 'active' : ''} onClick={() => setAssetFolderFilter(key as AssetFolderKey)}>{label}</button>)}</div>

        <div className="grid2 assetGridWrap"><div><h3>自有素材库</h3><div className="assetCards">{filteredMaterialAssets.length === 0 && <Empty>没有匹配的素材。可以拖动上传或调整筛选条件。</Empty>}{filteredMaterialAssets.map(a => <div key={a.id} className={`assetCard ${selectedMaterialIds.includes(a.id) ? 'selected' : ''}`}><button className="assetPreview" onClick={() => window.open(a.url, '_blank')}>{a.kind === 'video' ? <video src={a.url} muted onLoadedMetadata={e => setAssetDurations(prev => ({ ...prev, [a.id]: readMediaDuration(e, 0) }))} /> : <img src={a.url} alt={a.original_name || a.filename} />}</button><div className="assetMeta"><strong title={a.original_name || a.filename}>{a.original_name || a.filename}</strong><span>{assetFolderLabel((a as any).folder, a.kind)} · {a.kind === 'video' ? '视频' : '图片'} · {formatBytes(a.size_bytes)} · {new Date(a.created_at).toLocaleDateString()}</span></div><div className="assetActions"><button className={selectedMaterialIds.includes(a.id) ? 'mini active' : 'mini'} onClick={() => toggleMaterial(a.id)}>{selectedMaterialIds.includes(a.id) ? '已选' : '选择'}</button><a className="mini" href={a.url} target="_blank">预览</a><button className="mini danger" onClick={() => removeAsset(a)}>删除</button></div></div>)}</div></div><div><h3>采集视频库</h3><div className="assetList">{collectedVideos.length === 0 && <Empty>暂时没有采集到视频。</Empty>}{collectedVideos.map(a => <div key={a.id} className={`assetRow collected ${selectedReferenceAssetId === a.id ? 'selected' : ''}`}><button onClick={() => setSelectedReferenceAssetId(a.id)}>作为参考</button><span>{a.original_name || a.filename}</span><em>{formatBytes(a.size_bytes)}</em><button className="mini danger" onClick={() => removeAsset(a)}>删除</button></div>)}</div></div></div>
        <div className="selectedTimeline"><h3>已选素材顺序 / 截取设置</h3>{selectedMaterialAssets.length === 0 && <Empty>先选择素材。剪辑会按照这里的顺序出现，不会再因为多段素材丢失而只剩纯文字背景。</Empty>}{selectedMaterialAssets.map((asset, index) => { const cfg = getClipSetting(asset, index); const maxDur = Math.max(1, assetDurations[asset.id] || 60); return <div key={asset.id} className="selectedClip"><div className="clipPreview">{asset.kind === 'video' ? <video controls src={asset.url} onLoadedMetadata={e => setAssetDurations(prev => ({ ...prev, [asset.id]: readMediaDuration(e, prev[asset.id] || 0) }))} /> : <img src={asset.url} />}</div><div className="clipControls"><div className="segmentHead"><strong>{index + 1}. {asset.original_name || asset.filename}</strong><div><button onClick={() => moveSelectedMaterial(index, -1)}>↑</button><button onClick={() => moveSelectedMaterial(index, 1)}>↓</button><button onClick={() => toggleMaterial(asset.id)}>移除</button></div></div>{asset.kind === 'image' ? <Field label={`图片停留 ${cfg.image_seconds.toFixed(1)} 秒`}><input type="range" min="0.8" max="8" step="0.1" value={cfg.image_seconds} onChange={e => updateClipSetting(asset.id, { image_seconds: Number(e.target.value) })} /></Field> : <div className="trimGrid"><Field label={`开始 ${cfg.video_start.toFixed(1)}s`}><input type="range" min="0" max={maxDur} step="0.1" value={cfg.video_start} onChange={e => updateClipSetting(asset.id, { video_start: Math.min(Number(e.target.value), cfg.video_end && cfg.video_end > 0 ? cfg.video_end - 0.3 : maxDur) })} /></Field><Field label={`结束 ${cfg.video_end ? cfg.video_end.toFixed(1) : '自动'}s`}><input type="range" min="0" max={maxDur} step="0.1" value={cfg.video_end || Math.min(maxDur, cfg.video_start + 3)} onChange={e => updateClipSetting(asset.id, { video_end: Number(e.target.value) })} /></Field><span>截取约 {Math.max(0.5, (cfg.video_end || Math.min(maxDur, cfg.video_start + 3)) - cfg.video_start).toFixed(1)} 秒</span></div>}<small>顺序会同步到剪辑合成；如果 R2 旧素材本地丢失，后端会先下载再合成。</small></div></div>})}</div>
        <div className="resultBox"><h3>素材匹配建议</h3><p>图片：每张建议 2-4 秒；视频：每段截 2-5 秒。人物口播主体在画面中间时，字幕建议放底部安全区，避免挡脸。</p></div>
      </section>}

      {active === 'shooting' && <section className="card modulePanel shootingScriptPanel">
        <div className="sectionHeader"><div><h2>第二步：脚本 / 拍摄工作台</h2><p>这里处理“上传脚本/资料 → AI 解析 → 生成拍摄任务、提词器、B-roll 和素材需求”。用户可选数字人，也可自己拍摄。</p></div><Button busy={busy === '生成运营拍摄任务' ? busy : ''} label="分析脚本并生成拍摄清单" onClick={makeShootingPlan} disabled={!currentScript} /></div>
        <div className="scriptDropZone" onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); handleShootingScriptFiles(e.dataTransfer.files) }}>
          <input id="shooting-script-upload" type="file" multiple accept=".pdf,.doc,.docx,.txt,.md,.srt,.csv,video/*,image/*" onChange={e => handleShootingScriptFiles(e.target.files)} />
          <label htmlFor="shooting-script-upload"><strong>拖动上传脚本 / PDF / 拍摄素材</strong><span>TXT/MD/SRT 会自动写入文案区；PDF/Word 先进入素材库，后续可由 AI 解析或作为拍摄资料。</span></label>
        </div>
        <div className="productionRouteGrid compact">
          {[['digital_human','用数字人出镜'],['self_shoot','自己拍摄'],['mixed_assets','素材混剪'],['graphic_post','图文窗口']].map(([value,label]) => <button key={value} className={oneClickOutputType === value ? 'selected' : ''} onClick={() => setOneClickOutputType(value)}>{label}</button>)}
        </div>
        {shootingPlan ? <div className="resultBox"><h3>{shootingPlan.summary}</h3><div className="shotTable">{shootingPlan.shot_tasks?.map((task, i) => <div className="shotRow" key={`${task.scene}-${i}`}><span>{task.priority}</span><strong>{task.scene}</strong><em>{task.duration}</em><p>{task.content}</p><small>{task.camera}</small><small>{task.props}</small></div>)}</div><div className="splitGrid"><div><h4>B-roll 补拍</h4>{shootingPlan.broll_list?.map(x => <p key={x}>· {x}</p>)}</div><div><h4>提词器短句</h4>{shootingPlan.teleprompter?.map(x => <p key={x}>· {x}</p>)}</div><div><h4>拍摄检查</h4>{shootingPlan.checklist?.map(x => <p key={x}>· {x}</p>)}</div></div></div> : <Empty>先在文案生产里生成/粘贴脚本，或把脚本文件拖到上方上传区。</Empty>}
      </section>}

      {active === 'video' && <section className="card modulePanel">
        <div className="sectionHeader"><div><h2>第六步：数字人开场 + 素材混剪</h2><p>按素材顺序生成画面底片，再叠加最终配音和字幕。没写完整旁白时，先按素材总时长自动补全。</p></div><div className="headerActions"><Button busy={busy === '按素材时长生成旁白稿' ? busy : ''} label="按素材时长补全旁白" onClick={generateScriptFromSelectedAssets} kind="soft" /><Button busy={busy === '合成视频并烧字幕' ? busy : ''} label="生成视频并下载 MP4" onClick={composeVideo} disabled={!currentScript} /></div></div>
        <div className="subtitlePresetGrid">
          {[
            ['douyin_boss','老板口播大字','白字黑描边 + 痛点词亮黄/红，适合强转化口播'],
            ['knowledge_highlight','知识科普高亮','双行字幕 + 关键词放大，适合解释流程/费用'],
            ['clean_trust','干净可信','克制白字 + 深色底描边，适合房产/教育信任感'],
            ['cta_pop','结尾强 CTA','亮色重点词 + 结尾放大，适合私信/领取资料']
          ].map(([value,title,desc]) => <button key={value} className={subtitlePreset === value ? 'selected' : ''} onClick={() => setSubtitlePreset(value as any)}><strong>{title}</strong><span>{desc}</span></button>)}
        </div>
        <div className="grid3"><Field label="字幕字号"><input type="number" min="16" max="34" value={subtitleSize} onChange={e => setSubtitleSize(Number(e.target.value || 20))} /></Field><Field label="字幕位置"><select value={subtitlePosition} onChange={e => setSubtitlePosition(e.target.value as any)}><option value="bottom_safe">底部安全区，不挡脸</option><option value="middle_low">中下方，大字口播</option><option value="center">居中强调，慎用</option></select></Field><Field label={`离底部 ${subtitleMarginV}px`}><input type="range" min="40" max="260" step="5" value={subtitleMarginV} onChange={e => setSubtitleMarginV(Number(e.target.value))} /></Field></div>
        <div className="smartSubtitleBox"><div><strong>智能重点词</strong><p>{subtitleHighlight || '系统会从文案里识别费用、避坑、身份、学校、私信等转化词，自动放大或高亮。'}</p></div><Button busy={busy === '智能字幕重点' ? busy : ''} label="AI 识别重点词" onClick={makeSubtitleAI} disabled={!currentScript} kind="soft" /></div>
        <div className="hintBox">对齐逻辑：以最终配音真实时长为准；先生成画面，再叠加配音与字幕。后半段会自动提前补偿，避免越往后越慢。</div>
        <div className="selectedTimeline compact"><h3>本次合成素材顺序</h3>{selectedMaterialAssets.length === 0 ? <Empty>未选择素材，会自动使用前几个素材；建议先去素材选择页确认顺序和截取区间。</Empty> : selectedMaterialAssets.map((asset, index) => { const cfg = getClipSetting(asset, index); return <div key={asset.id} className="assetRow"><span>{index + 1}</span><strong>{asset.original_name || asset.filename}</strong><em>{asset.kind === 'image' ? `${cfg.image_seconds.toFixed(1)}秒` : `${cfg.video_start.toFixed(1)}-${cfg.video_end ? cfg.video_end.toFixed(1) : '自动'}秒`}</em><button className="mini" onClick={() => setActive('assets')}>调整</button></div>})}</div>
        {video && <div className="videoGrid"><video controls src={video.video_url} /><div className="downloadPanel"><a className="download" href={video.video_url} target="_blank">下载视频 MP4</a>{video.subtitle_url && <a href={video.subtitle_url} target="_blank">下载字幕 SRT</a>}{video.audio_url && <a href={video.audio_url} target="_blank">下载音频</a>}{video.warnings?.map(w => <div className="warn" key={w}>{w}</div>)}</div></div>}
        <div className="editChatBox"><Field label="AI + 插件剪辑指令"><textarea value={editInstruction} onChange={e => setEditInstruction(e.target.value)} placeholder="例如：去掉开头2秒、整体加速1.1倍、重新加字幕、转成9:16。" /></Field><Button busy={busy === 'AI + 插件修改视频' ? busy : ''} label="AI + 插件修改视频" onClick={chatEditVideo} kind="ghost" disabled={!currentVideoName} />{editChat.map((msg, i) => <div className="chatMsg" key={i}><strong>AI：</strong>{msg.assistant_message}<p>{msg.summary}</p><div className="chips">{msg.actions?.map(x => <Pill key={x}>{x}</Pill>)}</div>{msg.new_video_url && <a href={msg.new_video_url} target="_blank">打开修改后视频</a>}{msg.warnings?.map(w => <div className="warn" key={w}>{w}</div>)}</div>)}</div>
      </section>}

      {active === 'subtitleCover' && <section className="card modulePanel visualPanel">
        <div className="sectionHeader"><div><h2>第六步：字幕 / 封面 / 图文引流</h2><p>封面负责点击，图文负责收藏和私信。文字由系统叠加，图片只做背景，避免 AI 把提示词画进图里。</p></div><div className="stackButtons"><Button busy={busy === '智能字幕重点' ? busy : ''} label="智能识别重点字幕" onClick={makeSubtitleAI} disabled={!currentScript} kind="ghost" /><Button busy={busy === '生成图文引流包' ? busy : ''} label="生成图文引流包" onClick={makeGraphicPost} /></div></div>
        <div className="visualTabs"><span>字幕</span><span>封面</span><span>图文素材</span></div>
        <div className="grid4"><Field label="字幕模板"><select value={subtitlePreset} onChange={e => setSubtitlePreset(e.target.value as any)}><option value="douyin_boss">老板口播大字</option><option value="knowledge_highlight">知识科普高亮</option><option value="clean_trust">干净可信</option><option value="cta_pop">结尾强 CTA</option></select></Field><Field label="字幕字号"><input type="number" min="16" max="34" value={subtitleSize} onChange={e => setSubtitleSize(Number(e.target.value || 20))} /></Field><Field label="重点词"><input value={subtitleHighlight} onChange={e => setSubtitleHighlight(e.target.value)} placeholder="AI 可自动识别，也可补充关键词" /></Field><Field label="封面大标题"><input value={copy.title || coverStyle} onChange={e => setCopy({ ...copy, title: e.target.value })} placeholder="例如：海外买房避坑指南" /></Field></div>
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
