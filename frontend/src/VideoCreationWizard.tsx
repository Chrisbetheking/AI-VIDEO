import React, { useEffect, useMemo, useRef, useState } from 'react'
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
type ScriptMode = 'lead' | 'professional' | 'life' | 'sales'

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

type SubtitleStyle = {
  id: string
  name: string
  description: string
  previewText?: string
  primary?: string
  background?: string
  accent?: string
  placement?: string
  font_size?: number
  outline?: number
  shadow?: number
  margin_v?: number
  border_style?: number
  max_chars?: number
  max_lines?: number
  ass_primary?: string
  ass_outline?: string
  ass_back?: string
  ass_prefix?: string
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

const WIZARD_DRAFT_KEY = 'ai_video_wizard_draft_v10_13'
const CLEAN_ONCE_KEY = 'ai_video_wizard_v10_10_cleaned_once'


function loadWizardDraft(): Record<string, any> {
  try {
    clearOldWizardDrafts()
    const raw = window.localStorage.getItem(WIZARD_DRAFT_KEY)
    const parsed = raw ? JSON.parse(raw) : {}
    if (!parsed || typeof parsed !== 'object') return {}
    if (draftLooksPolluted(parsed)) {
      window.localStorage.removeItem(WIZARD_DRAFT_KEY)
      return {}
    }
    return parsed
  } catch {
    return {}
  }
}

function saveWizardDraft(value: Record<string, any>) {
  try {
    window.localStorage.setItem(WIZARD_DRAFT_KEY, JSON.stringify(value))
  } catch {}
}


function forceCleanEntryOnce() {
  try {
    const params = new URLSearchParams(window.location.search || '')
    const force = params.get('force') || ''
    const reset = params.get('reset') === '1' || params.get('clean') === '1'
    if (!reset && !force.includes('v10-10')) return false
    if (!reset && window.localStorage.getItem(CLEAN_ONCE_KEY) === '1') return false
    ;[
      'ai_video_wizard_draft_v10_5', 'ai_video_wizard_draft_v10_6', 'ai_video_wizard_draft_v10_7',
      'ai_video_wizard_draft_v10_8', 'ai_video_wizard_draft_v10_9', 'ai_video_wizard_draft_v10_10', 'ai_video_wizard_draft_v10_12', WIZARD_DRAFT_KEY,
      'ai_video_engineering_project_draft_v16', 'ai_video_engineering_project_draft_v15',
    ].forEach((key) => window.localStorage.removeItem(key))
    window.localStorage.setItem(CLEAN_ONCE_KEY, '1')
    return true
  } catch { return false }
}

function clearOldWizardDrafts() {
  try {
    forceCleanEntryOnce()
    Object.keys(window.localStorage).forEach((key) => {
      if (key.startsWith('ai_video_wizard_draft_') && key !== WIZARD_DRAFT_KEY) window.localStorage.removeItem(key)
    })
  } catch {}
}

function draftLooksPolluted(draft: Record<string, any>) {
  const text = `${draft.manualKeywords || ''} ${draft.script || ''} ${JSON.stringify(draft.aiKeywordInsights || [])}`
  return /(62\.?|61\.?|评论区答疑模板|数字人模板|生活分享讲解模板|禁用素材规则|R2素材自动标签|OpenClaw|openclaw|内容大脑|这条视频要特别强调|高质量成片沉淀|低质量成片标记|类型：|模式：|用途：|风格：|来源状态|评论反向生成视频)/.test(text)
}

function contentBrainMatch(card: ContentBrainCard, topic: string, city: string, market: string) {
  if (!isVideoBrainCard(card)) return false
  const text = `${card.title || ''} ${card.content || ''} ${(card.tags || []).join(' ')}`.toLowerCase()
  const cityName = city === 'kuala_lumpur' ? '吉隆坡' : cityLabel(city).split('/')[0].trim()
  const keys = [topic, cityName, city]
    .flatMap((x) => splitKeywordCandidates(String(x || '')))
    .map((x) => x.toLowerCase())
    .filter((key) => key.length >= 2 && !['房产', '马来西亚', '选题', '客户问题'].includes(key))
  if (!keys.length) return true
  return keys.some((key) => text.includes(key))
}

const BAD_KEYWORDS = new Set([
  '房产', '选题', '镜头', '客户问题', '市场知识', '回复模板', '马来西亚', '内容大脑',
  '类型', '模式', '风格', 'OpenClaw', 'openclaw', '素材', '规则', '模板', 'AI关键词',
  '先复述问题', '最后引导补充预算', '生活分享讲解模板', '禁用素材规则', 'R2素材自动标签',
  '评论区答疑模板', '数字人模板', '成片沉淀', '低质量成片标记', '高质量成片沉淀', '高质量成片',
  '低质量成片', '吉隆坡素材优先级', '素材库', '字幕库', '字幕样式', '自动标签', '再拆判断标准', '用途', '适合', '评论反向生成视频', '类型：数字人模板', '专业型', '生活分享讲解模板',
])
const VIDEO_BRAIN_TYPES = new Set(['topic', 'hook', 'script', 'market_note', 'lead_question'])
const NON_VIDEO_BRAIN_TYPES = new Set(['reply_template', 'visual_rule'])

function normalizeKeywordValue(value: string) {
  return String(value || '')
    .replace(/\bOpenClaw\b/gi, ' ')
    .replace(/(?:类型|模式|用途|风格|结构|开头|评论引导|适合人群|目的|注意|来源状态|用户指定|评论反向生成视频)[：:][^，,。；;\n]*/g, ' ')
    .replace(/[：:，,。！？!?；;#*`\[\]()（）【】{}]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

function usefulKeyword(value: string) {
  const raw = String(value || '')
  const clean = normalizeKeywordValue(raw)
  if (!clean) return ''
  if (/^(?:ai_?kw|keyword|kw|region|area|audience|crowd|user|区域|人群|城市|标签)[_-]?\d+(?:[_-].*)?$/i.test(clean)) return ''
  if (/(?:internal|placeholder|占位|字段id|keyword_id)/i.test(clean)) return ''
  if (BAD_KEYWORDS.has(clean)) return ''
  if (clean.length < 2 || clean.length > 12) return ''
  if (/^[\d.]+$/.test(clean)) return ''
  if (/^\d+[\.、]\s*/.test(raw)) return ''
  if (/^(\d+|第\d+|NO\d+)$/i.test(clean)) return ''
  if (/^(类型|模式|适合|目的|结构|开头|评论|注意|镜头组合|话术|来源状态|用户指定|标签|规则)/.test(clean)) return ''
  if (/(模板|规则|自动|禁用|内容大脑|数字人|成片|沉淀|标记|答疑|讲解模板|素材优先级|素材自动|OpenClaw|openclaw)/.test(clean)) return ''
  if (/(房产顾问|客户问题|视频创作|生成视频|逐句配音|文案模式)/.test(clean)) return ''
  if (/https?:\/\//i.test(clean)) return ''
  return clean
}

function splitKeywordCandidates(value: string) {
  return String(value || '')
    .split(/[，,、\n\s/|]+/)
    .map(usefulKeyword)
    .filter(Boolean)
}

function cleanManualKeywordText(value: string) {
  const rawText = String(value || '')
  if (rawText.length > 50 && /(62\.?|61\.?|OpenClaw|openclaw|模板|规则|类型|模式|用途|来源状态|评论反向生成视频|内容大脑)/.test(rawText)) return ''
  const out: string[] = []
  const seen = new Set<string>()
  splitKeywordCandidates(value).forEach((kw) => {
    const key = kw.toLowerCase()
    if (seen.has(key)) return
    seen.add(key)
    out.push(kw)
  })
  return out.slice(0, 18).join('，')
}

function isVideoBrainCard(card: ContentBrainCard) {
  const t = String(card.type || '').trim()
  if (NON_VIDEO_BRAIN_TYPES.has(t)) return false
  if (VIDEO_BRAIN_TYPES.has(t)) return true
  const title = `${card.title || ''} ${card.content || ''}`
  if (/^\s*\d+[\.、]/.test(title)) return false
  if (/(回复话术|评论区答疑|私信|镜头规则|素材规则|字幕|数字人|成片沉淀|模板|规则|OpenClaw|openclaw|R2素材|禁用素材|质量标记)/.test(title)) return false
  return true
}

function compactBrainForWizard(cards: ContentBrainCard[]) {
  return cards.filter(isVideoBrainCard).slice(0, 10).map((card) => ({
    id: card.id,
    title: card.title,
    type: card.type,
    content: String(card.content || '').slice(0, 220),
    score: card.score || 0,
  }))
}

function contentBrainKeywords(cards: ContentBrainCard[]) {
  const out: string[] = []
  const seen = new Set<string>()
  cards.filter(isVideoBrainCard).forEach((card) => {
    const raw = [card.title || '', card.content || '']
    raw.flatMap(splitKeywordCandidates).forEach((kw) => {
      const key = kw.toLowerCase()
      if (seen.has(key)) return
      seen.add(key)
      out.push(kw)
    })
  })
  return out.slice(0, 10)
}

function scriptLooksPolluted(value: string) {
  const text = String(value || '')
  return /(62\.?|评论区答疑模板|数字人模板|生活分享讲解模板|禁用素材规则|R2素材自动标签|OpenClaw|内容大脑|这条视频要特别强调)/.test(text)
}

function normalizeKeywordInsight(item: any, index = 0): KeywordInsight | null {
  const value = usefulKeyword(String(item?.value || item?.keyword || item?.text || ''))
  if (!value) return null
  const priority = String(item?.priority || 'medium')
  return {
    id: String(item?.id || `ai_kw_${index + 1}_${value}`),
    category: String(item?.category || 'AI关键词').slice(0, 16),
    value,
    reason: String(item?.reason || 'DeepSeek 结合主题、内容大脑和业务目标筛选。').slice(0, 90),
    priority: priority === 'high' || priority === 'low' ? priority : 'medium',
  }
}

function mergeKeywordInsights(primary: KeywordInsight[], fallback: KeywordInsight[]) {
  const out: KeywordInsight[] = []
  const seen = new Set<string>()
  ;[...primary, ...fallback].forEach((item, index) => {
    const normalized = normalizeKeywordInsight(item, index)
    if (!normalized) return
    const key = normalized.value.toLowerCase()
    if (seen.has(key)) return
    seen.add(key)
    out.push(normalized)
  })
  return out.slice(0, 36)
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
  3: '默认生成 3 个同主题动态角度，不再九宫格；画面会轻微推拉和平移。',
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

const SCRIPT_LABELS: Record<ScriptMode, string> = {
  lead: '引流型：强钩子 + 评论互动',
  professional: '专业型：判断逻辑 + 信任建立',
  life: '生活日常：真实生活 + 轻松种草',
  sales: '成交承接：筛选问题 + 人工跟进',
}

const SUBTITLE_STYLE_FALLBACK: SubtitleStyle[] = [
  { id: 'douyin_pop', name: '抖音大字弹幕款', description: '大白字、粗黑描边、轻微弹入，短视频口播默认。', primary: '#ffffff', background: 'transparent', accent: '#fde047', placement: '中下方大字' },
  { id: 'douyin_yellow_pop', name: '抖音黄字重点款', description: '亮黄大字、黑描边，适合强钩子和避坑。', primary: '#ffe45c', background: 'transparent', accent: '#ffffff', placement: '中下方大字' },
  { id: 'douyin_black_bubble', name: '抖音黑底口播款', description: '黑底白字，画面复杂时最清楚。', primary: '#ffffff', background: 'rgba(0,0,0,0.62)', accent: '#fde047', placement: '底部黑条' },
  { id: 'real_estate_gold', name: '金色地产讲解', description: '适合专业讲房，黄底关键词感，手机端清晰。', primary: '#fff7cc', background: 'rgba(20, 16, 8, 0.72)', accent: '#f6c44f', placement: '底部双行' },
  { id: 'white_outline', name: '白字黑描边', description: '最稳妥，适合任何素材，不挡画面。', primary: '#ffffff', background: 'transparent', accent: '#111827', placement: '底部居中' },
  { id: 'black_bar', name: '黑底信息条', description: '信息密度高，适合专业拆解和避坑内容。', primary: '#ffffff', background: 'rgba(0,0,0,0.68)', accent: '#60a5fa', placement: '底部黑条', font_size: 94, outline: 1, margin_v: 130, max_chars: 17, max_lines: 1 },
  { id: 'clean_premium', name: '极简高级大字', description: '无底色大白字，适合高级感楼盘和人物画面。', primary: '#ffffff', background: 'transparent', accent: '#c4b5fd', placement: '中下方', font_size: 96, outline: 8, margin_v: 300, max_chars: 12, max_lines: 1 },
  { id: 'xiaohongshu_alert', name: '小红书醒目款', description: '高饱和黄白大字，适合避坑、预算和清单。', primary: '#ffffff', background: 'rgba(96,46,12,0.72)', accent: '#fde047', placement: '中下方', font_size: 118, outline: 6, margin_v: 315, max_chars: 10, max_lines: 1 },
  { id: 'professional_two_line', name: '专业解释双行款', description: '醒目但允许较长专业信息自然分两行。', primary: '#ffffff', background: 'rgba(15,23,42,0.72)', accent: '#60a5fa', placement: '底部双行', font_size: 88, outline: 3, margin_v: 250, max_chars: 16, max_lines: 2 },
]

const CITY_OPTIONS = [
  { key: 'kuala_lumpur', label: '吉隆坡 / Kuala Lumpur', anchors: ['TRX', 'Mont Kiara', '公寓客厅', '公寓阳台', '大堂', '泳池'] },
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

function assetHasEmbeddedText(asset: any) {
  const flags = [
    asset?.has_text,
    asset?.has_subtitle,
    asset?.embedded_subtitle,
    asset?.watermark_detected,
    asset?.ocr_detected,
  ]
  if (flags.some(Boolean)) return true

  const haystack = [
    asset?.name,
    asset?.filename,
    asset?.original_name,
    asset?.tags,
    asset?.labels,
    asset?.notes,
    asset?.ocr_text,
  ].flat().filter(Boolean).join(' ')

  return /(字幕|文案|贴字|水印|口播字|烧录字|caption|subtitle|watermark|ocr)/i.test(haystack)
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

function keywordTextForScript(keywords: KeywordInsight[]) {
  const picked = keywords
    .filter((item) => item.priority === 'high' || ['预算/价格', '区域', '人群', '用途', '风险判断'].includes(item.category))
    .map((item) => usefulKeyword(item.value))
    .filter(Boolean)
  return Array.from(new Set(picked)).slice(0, 7).join('、')
}

function generateScript(topic: string, city: string, duration: number, contentType: ContentType, keywords: KeywordInsight[], scriptMode: ScriptMode = 'professional') {
  const baseTopic = topic.trim() || DEFAULT_TOPIC
  const keywordText = keywordTextForScript(keywords)
  const isKl = city === 'kuala_lumpur'
  const cityName = isKl ? '吉隆坡' : cityLabel(city).split('/')[0].trim()
  const topicLine = baseTopic.replace(/[。！？!?]+$/g, '')
  const isLife = scriptMode === 'life'
  const isLead = scriptMode === 'lead'
  const isSales = scriptMode === 'sales'

  const hook = isLife
    ? `很多人想象中的${cityName}生活，和真正住下来感受到的并不一样。`
    : isLead
      ? `${topicLine}，这个问题很多人第一步就问错了。`
      : `${topicLine}，别先看表面的价格和宣传图。`

  let body = ''
  if (isLife) {
    body = `先看生活半径：吃饭、通勤、商场、华语环境和周末活动，决定你是不是真的住得舒服。再看预算，不同区域的日常成本差别很大。`
  } else if (isKl) {
    if (contentType === 'own_stay') {
      body = '如果是自住，重点不是短期涨跌，而是生活便利、社区品质、通勤距离和长期居住舒适度。'
    } else if (contentType === 'rental' || contentType === 'investment') {
      body = '如果是投资，先看租客从哪里来，再看通勤、商圈、公共设施和未来转手流动性。'
    } else if (contentType === 'education') {
      body = '如果考虑家庭和教育，要把通勤、社区安全感、中文生活环境和长期持有需求放在前面。'
    } else {
      body = '如果是第二家园，要先看生活便利、医疗、社区氛围和长期居住适应度，不要只看度假感。'
    }
    body += ' TRX、Mont Kiara、生活半径和社区品质只是判断区域的锚点，不代表每个项目都适合你。'
  } else {
    body = `${cityName}适合的人群和吉隆坡不一样，自住、投资、养老和第二家园的判断标准也不一样，要先把用途筛清楚。`
  }

  const logic = isSales
    ? '所以看房前先回答三个问题：预算多少、买来做什么、准备持有多久。答案不同，推荐区域和产品会完全不同。'
    : isLead
      ? '真正要看的不是哪个项目最火，而是哪一个区域和你的用途匹配。否则看了很多房，最后还是会被价格牵着走。'
      : '专业一点看，先判断区域成熟度，再判断真实需求，最后才比较价格、户型和配套。顺序错了，很容易买到不适合自己的房子。'

  const keyLine = keywordText ? `这条重点围绕：${keywordText}。` : ''
  const cta = isLife
    ? '你最关心这里的吃饭、语言，还是生活成本？评论区说一下。'
    : isSales
      ? '你是自住、投资还是出租？把预算和用途打出来，我按区域逻辑帮你拆。'
      : '你现在更关心预算、区域，还是未来出租和转手？评论区打出来。'

  return normalizeScriptLength([hook, body, logic, keyLine, cta].filter(Boolean).join(' '), duration, city)
}

function cleanSpeechArtifacts(value: string) {
  return String(value || '')
    .replace(/\\[nr]/g, ' ')
    .replace(/\r\n?/g, '\n')
    .replace(/[／/|｜]+/g, '，')
    .replace(/\\+/g, ' ')
    .replace(/[ \t]*\n+[ \t]*/g, '。')
    .replace(/\s+/g, ' ')
    .replace(/\s*([，。！？；：])\s*/g, '$1')
    .replace(/([，。！？；：])\1+/g, '$1')
    .replace(/^[，。；：\s]+|[，；：\s]+$/g, '')
    .trim()
}

function cleanSegmentText(value: string) {
  return cleanSpeechArtifacts(value)
    .replace(/^[。！？!?；;]+/g, '')
    .trim()
}

function joinSegmentTexts(values: string[]) {
  return values
    .map(cleanSegmentText)
    .filter(Boolean)
    .map((item) => /[。！？!?；;]$/.test(item) ? item : `${item}。`)
    .join('')
}

function splitScript(script: string): ScriptSegment[] {
  const normalized = cleanSpeechArtifacts(script)
  const parts = normalized.match(/[^。！？!?；;]+[。！？!?；;]?/g) || []

  return parts
    .map(cleanSegmentText)
    .filter(Boolean)
    .map((text, index) => ({
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
    const clean = usefulKeyword(value)
    if (!clean || seen.has(`${category}:${clean}`)) return
    seen.add(`${category}:${clean}`)
    items.push({ id: `${category}_${items.length + 1}`, category, value: clean, reason, priority })
  }

  ;(manual || '')
    .split(/[，,、\s]+/)
    .map(usefulKeyword)
    .filter(Boolean)
    .forEach((x) => add('手动关键词', x, '用户指定必须凸显', 'high'))

  const money = raw.match(/\d+(?:\.\d+)?\s*(?:万|百万|千万|亿|rm|RM|马币)/g) || []
  money.forEach((x) => add('预算/价格', x, '预算信息是评论截流和口播重音重点', 'high'))

  const rules: Array<[string, RegExp, string, KeywordInsight['priority']]> = [
    ['区域', /(吉隆坡|TRX|Mont\s*Kiara|Mont Kiara|槟城|Penang|新山|Johor|兰卡威|Langkawi|沙巴|Sabah)/gi, '区域决定画面锚点和客户判断', 'high'],
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

  return items.slice(0, 30)
}

function attachSegmentKeywords(segments: ScriptSegment[], keywords: KeywordInsight[]) {
  return segments.map((segment) => ({
    ...segment,
    keywords: keywords.filter((kw) => segment.text.toLowerCase().includes(kw.value.toLowerCase())).slice(0, 6),
  }))
}

function inferVoiceSetting(segment: ScriptSegment, index = 0, total = 1, scriptMode: ScriptMode = 'professional'): SegmentVoiceSetting {
  const text = String(segment.text || '')
  const hasHigh = segment.keywords.some((kw) => kw.priority === 'high')
  const isHook = index === 0 || /别|不是|很多人|第一步|最怕|错/.test(text)
  const isRisk = /坑|风险|担心|怕|不能|不要|忽略|转手|空置|亏|被骗/.test(text)
  const isLogic = /第一|第二|第三|先看|再看|最后|判断|重点/.test(text)
  const isCta = index >= total - 1 || /评论区|打出来|预算|你是|你更|私信|联系/.test(text)
  const isLife = scriptMode === 'life'

  let tone = isLife ? '自然平稳' : '专业可信'
  let emotion = isLife ? '温和引导' : '解释说明'
  let speed = 1
  let pitch = 1
  let volume = 1
  let pauseBefore = 60
  let pauseAfter = 160
  let note = 'AI 已根据句意自动判断语气、情绪、语速和停顿。'

  if (isHook) {
    tone = isLife ? '轻快种草' : '专业可信'
    emotion = '重点强调'
    speed = 0.93
    volume = 1.08
    pauseBefore = 80
    pauseAfter = 240
    note = '开头钩子：稍慢、稍重，先抓住注意力。'
  }
  if (isRisk) {
    tone = '风险提醒'
    emotion = '提醒避坑'
    speed = 0.9
    pitch = 0.98
    volume = 1.08
    pauseBefore = 120
    pauseAfter = 240
    note = '风险/避坑句：降低语速，关键词加重。'
  } else if (isLogic) {
    tone = '专业可信'
    emotion = '解释说明'
    speed = 0.95
    volume = hasHigh ? 1.06 : 1.02
    pauseBefore = hasHigh ? 100 : 60
    pauseAfter = 190
    note = '判断逻辑句：清晰、可信，方便观众听懂。'
  }
  if (isCta) {
    tone = '成交引导'
    emotion = '温和引导'
    speed = 0.98
    pitch = 1.02
    volume = 1.05
    pauseBefore = 120
    pauseAfter = 260
    note = '结尾承接句：自然追问，不要像硬广。'
  }
  if (hasHigh && !isRisk && !isHook && !isCta) {
    speed = Math.min(speed, 0.95)
    volume = Math.max(volume, 1.05)
  }

  return {
    speed,
    pitch,
    volume,
    emotion,
    tone,
    pauseBefore,
    pauseAfter,
    emphasis: segment.keywords.map((kw) => kw.value),
    note,
  }
}

function defaultVoiceSetting(segment: ScriptSegment): SegmentVoiceSetting {
  return inferVoiceSetting(segment, Math.max(0, segment.index - 1), 1, 'professional')
}

function cityScenes(city: string) {
  if (city === 'penang') return ['Gurney Drive 滨海住宅天际线', '槟城海景公寓阳台', '现代公寓室内面向海景', '养老第二家园生活方式']
  if (city === 'johor') return ['新山城市住宅区位', 'Medini 现代公寓社区', '家庭自住公寓室内', '城市通勤和生活配套']
  if (city === 'langkawi') return ['兰卡威度假型住宅和泳池', '热带绿植第二家园', '岛屿度假住宅生活方式', '度假社区公共空间']
  if (city === 'sabah') return ['亚庇城市滨海住宅', '沙巴日落住宅生活方式', '滨海公寓阳台', '度假社区配套镜头']
  return ['现代吉隆坡公寓入口和落客区：经纪人走向大堂，单一全屏镜头', '现代公寓客厅：落地窗、沙发、自然光，单一全屏镜头', '公寓阳台：普通吉隆坡住宅天际线和绿化，禁止双子塔主体', '公寓大堂：保安入口、会客区、品质感，单一全屏镜头', '公寓泳池和景观平台：社区设施和生活方式', '公寓健身房和公共设施：干净、高端、真实居住感', 'Mont Kiara 高端公寓社区：街区、咖啡和家庭生活', 'TRX / Bukit Bintang 街区生活半径：通勤、咖啡、城市街景，不拍地标天际线', '经纪人带看公寓：开门、看客厅、看阳台', '厨房、餐厅与卧室细节：体现自住舒适度']
}

function buildPrompt(city: string, scene: string, _narration: string, index = 1) {
  const klRule = city === 'kuala_lumpur'
    ? `Kuala Lumpur only. Shot ${index} must be ONE continuous full-screen video shot. Do NOT center KLCC or Petronas Twin Towers. Do NOT repeat the same skyline. Prefer condo interior, balcony generic city view, lobby, pool, gym, agent showing apartment, TRX or Bukit Bintang street-level context, Mont Kiara community, kitchen, bedroom or real residential details. Do not show beach, island, seaside, Langkawi, Sabah or Penang seaside.`
    : 'Use city-matched Malaysia real-estate visuals. Avoid fake project names, exact prices and exact ROI.'

  return `Premium 9:16 cinematic vertical video for Malaysia real-estate content.\nShot ${index} main scene: ${scene}.\n${klRule}\nVisual-only rule: never render narration, subtitles, captions, headlines, stickers, labels, UI, logos, watermarks, signs, letters, numbers or pseudo-text inside the generated image. The picture must contain zero readable or unreadable text. Single-scene rule: one full-screen continuous camera shot only, not a montage, not split screen and not a panel layout. Ultra realistic, natural lighting, clean composition, high detail, smooth camera movement, no black borders, no documents, no papers, no charts, no screenshots.`
}

function targetShotCount(duration: number) {
  return Math.max(4, Math.min(12, Math.ceil(Number(duration || 20) / 4)))
}

function generateShotPlan(segments: ScriptSegment[], duration: number, city: string, project: ProjectDraft): ShotPlan[] {
  const count = targetShotCount(duration)
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
      prompt: buildPrompt(city, scene, segment?.text || '', index + 1),
      avoid: city === 'kuala_lumpur'
        ? ['海边', '沙滩', '海岛', '分屏', '拼贴', '多宫格', '文件桌面', '纸张', '图表', '计算器', '乱码文字', '字幕', '标题', '水印', 'Logo', '贴纸', 'UI', '数字', '字母', '假价格']
        : ['分屏', '拼贴', '多宫格', '文件桌面', '纸张', '图表', '计算器', '乱码文字', '字幕', '标题', '水印', 'Logo', '贴纸', 'UI', '数字', '字母', '假价格', '假项目名'],
      assetIds,
    }
  })
}

function highlightText(text: string, keywords: KeywordInsight[]) {
  const cleanKeywords = keywords
    .map((item) => ({ ...item, value: usefulKeyword(item.value) }))
    .filter((item) => item.value)
    .sort((a, b) => b.value.length - a.value.length)
  if (!cleanKeywords.length) return [text]
  const escaped = cleanKeywords.map((item) => item.value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  const pattern = new RegExp(`(${escaped.join('|')})`, 'gi')
  const map = new Map(cleanKeywords.map((item) => [item.value.toLowerCase(), item]))
  return text.split(pattern).map((part, index) => {
    const keyword = map.get(part.toLowerCase())
    return keyword
      ? <mark className={`aiw-keywordMark ${keyword.priority}`} key={`${keyword.id}_${index}`}>{part}</mark>
      : part
  })
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

function jobFailed(job: JobPayload | null) {
  const values = [job?.status, job?.stage, job?.child_job?.status, job?.child_job?.stage]
    .map((value) => String(value || '').toLowerCase())
  return values.some((value) => /^(failed|error|cancelled|canceled|rejected)$/.test(value))
}

function jobActivelyGenerating(job: JobPayload | null) {
  const stage = `${job?.stage || ''} ${job?.child_job?.stage || ''}`.toLowerCase()
  return /(queued|generating|processing|rendering|composing|burn|uploading|fal_shot|tts|subtitle)/.test(stage)
}

function finalStatus(job: JobPayload | null) {
  if (jobFailed(job)) return true
  if (jobActivelyGenerating(job)) return false
  const values = [job?.status, job?.child_job?.status].map((value) => String(value || '').toLowerCase())
  return values.some((value) => /^(completed|succeeded|success|done|finished)$/.test(value))
}


function workflowActionText(action?: string) {
  const map: Record<string, string> = {
    wait_for_video: '等待成片',
    fix_video_job: '成片任务异常',
    run_review: '等待自动审片',
    wait_for_review: '机械质检 / 豆包审片中',
    human_review: '等待人工确认',
    return_to_edit: '审片未通过，返回修改',
    backfill_packaging: '等待生成封面和图文',
    select_cover: '请选择主封面',
    compose_cover_video: '等待封面合成最终视频',
    build_final_delivery: '等待生成最终总包',
    ready_to_publish: '发布素材已齐全',
  }
  return map[String(action || '')] || String(action || '成片后自动启动')
}

function workflowResultParts(workflow: Record<string, any> | null) {
  const packaging = workflow?.packaging && typeof workflow.packaging === 'object' ? workflow.packaging : {}
  const review = workflow?.review && typeof workflow.review === 'object' ? workflow.review : {}
  const automation = packaging?.automation && typeof packaging.automation === 'object' ? packaging.automation : {}
  const cover = packaging?.cover_result && typeof packaging.cover_result === 'object'
    ? packaging.cover_result
    : automation?.cover_result && typeof automation.cover_result === 'object'
      ? automation.cover_result
      : review?.cover_result && typeof review.cover_result === 'object'
        ? review.cover_result
        : {}
  const xhs = packaging?.xhs_result && typeof packaging.xhs_result === 'object'
    ? packaging.xhs_result
    : automation?.xhs_result && typeof automation.xhs_result === 'object'
      ? automation.xhs_result
      : {}
  return { packaging, review, cover, xhs }
}

export default function VideoCreationWizard({ project, setProject, goTab }: Props) {
  const initialDraft = useMemo(() => loadWizardDraft(), [])
  const [step, setStep] = useState<WizardStep>((Number(initialDraft.step || 1) as WizardStep) || 1)
  const [sourceMode, setSourceMode] = useState<SourceMode>((initialDraft.sourceMode || 'custom') as SourceMode)
  const [topic, setTopic] = useState(String(project.topic || initialDraft.topic || DEFAULT_TOPIC))
  const [market, setMarket] = useState(String(project.market || initialDraft.market || DEFAULT_MARKET))
  const [city, setCity] = useState(String(project.city || initialDraft.city || inferCity(`${project.topic || initialDraft.topic} ${project.script || initialDraft.script}`)))
  const [contentType, setContentType] = useState<ContentType>(String(project.contentType || initialDraft.contentType || 'investment') as ContentType)
  const [scriptMode, setScriptMode] = useState<ScriptMode>(String(project.scriptMode || project.script_mode || initialDraft.scriptMode || 'professional') as ScriptMode)
  const [targetDuration, setTargetDuration] = useState(Number(project.targetDuration || initialDraft.targetDuration || 30))
  const [competitorSource, setCompetitorSource] = useState(String(project.competitorSource || initialDraft.competitorSource || ''))
  const [manualKeywords, setManualKeywords] = useState('')
  const [manualKeywordDraft, setManualKeywordDraft] = useState('')
  const [script, setScript] = useState(() => { const raw = String(initialDraft.script || ''); return scriptLooksPolluted(raw) ? '' : raw })
  const [selectedSegmentId, setSelectedSegmentId] = useState(String(initialDraft.selectedSegmentId || 'seg_1'))
  const [voiceSettings, setVoiceSettings] = useState<Record<string, SegmentVoiceSetting>>((initialDraft.voiceSettings || project.segment_voice_settings || {}) as Record<string, SegmentVoiceSetting>)
  const [shotPlan, setShotPlan] = useState<ShotPlan[]>(Array.isArray(initialDraft.shotPlan) ? initialDraft.shotPlan : [])
  const [selectedShotId, setSelectedShotId] = useState(String(initialDraft.selectedShotId || 'shot_1'))
  const [jobId, setJobId] = useState(String(initialDraft.jobId || ''))
  const [job, setJob] = useState<JobPayload | null>((initialDraft.job || null) as JobPayload | null)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [sourceBusy, setSourceBusy] = useState('')
  const [sourceError, setSourceError] = useState('')
  const [sourceResult, setSourceResult] = useState<any>(initialDraft.sourceResult || null)
  const [remoteBrainCards, setRemoteBrainCards] = useState<ContentBrainCard[]>([])
  const [knowledgeContext, setKnowledgeContext] = useState<any>(null)
  const [selectedKnowledgeIds, setSelectedKnowledgeIds] = useState<string[]>(Array.isArray(project.selected_knowledge_card_ids) ? project.selected_knowledge_card_ids : [])
  const [assetGateResult, setAssetGateResult] = useState<any>(null)
  const [disabledKeywordValues, setDisabledKeywordValues] = useState<string[]>(Array.isArray(initialDraft.disabledKeywordValues) ? initialDraft.disabledKeywordValues : [])
  const [aiKeywordInsights, setAiKeywordInsights] = useState<KeywordInsight[]>([])
  const [aiBusy, setAiBusy] = useState('')
  const [aiStatus, setAiStatus] = useState(String(initialDraft.aiStatus || ''))
  const [buttonStatus, setButtonStatus] = useState(String(initialDraft.buttonStatus || ''))
  const [subtitleEnabled, setSubtitleEnabled] = useState(Boolean(initialDraft.subtitleEnabled ?? project.burn_subtitles ?? true))
  const [subtitleStyleId, setSubtitleStyleId] = useState(String(initialDraft.subtitleStyleId || project.subtitle_style_id || 'douyin_pop'))
  const [subtitleStyles, setSubtitleStyles] = useState<SubtitleStyle[]>(SUBTITLE_STYLE_FALLBACK)
  const [subtitleStyleOverrides, setSubtitleStyleOverrides] = useState<Record<string, number>>({
    ...(project.subtitle_style_overrides || {}),
    ...(initialDraft.subtitleStyleOverrides || {}),
  })
  const [generationStartedAt, setGenerationStartedAt] = useState(Number(initialDraft.generationStartedAt || 0))
  const [workflow, setWorkflow] = useState<Record<string, any> | null>((initialDraft.workflow || null) as Record<string, any> | null)
  const [workflowBusy, setWorkflowBusy] = useState('')
  const [workflowError, setWorkflowError] = useState('')
  const [voicePreviewBusy, setVoicePreviewBusy] = useState('')
  const [voicePreviewUrl, setVoicePreviewUrl] = useState('')
  const [voicePreviewError, setVoicePreviewError] = useState('')
  const [segmentEditDraft, setSegmentEditDraft] = useState('')
  const segmentEditorRef = useRef<HTMLTextAreaElement | null>(null)
  const reviewLaunchRef = useRef('')
  const pollFailureRef = useRef(0)
  const pollInFlightRef = useRef(false)

  const approvedBrainCards = useMemo(() => {
    const merged = [...remoteBrainCards]
    const seen = new Set<string>()
    return merged.filter((card) => {
      const key = String(card.id || `${card.title}|${card.content}`)
      if (seen.has(key)) return false
      seen.add(key)
      return contentBrainMatch(card, topic, city, market)
    }).slice(0, 12)
  }, [topic, city, market, remoteBrainCards])
  const videoBrainCards = useMemo(() => approvedBrainCards.filter(isVideoBrainCard), [approvedBrainCards])
  const nonVideoBrainCards = useMemo(() => approvedBrainCards.filter((card) => !isVideoBrainCard(card)), [approvedBrainCards])
  const brainKeywordText = useMemo(() => contentBrainKeywords(videoBrainCards).join('，'), [videoBrainCards])
  const cleanManualKeywords = useMemo(() => cleanManualKeywordText(manualKeywords), [manualKeywords])
  const localKeywordCandidates = useMemo(
    () => extractKeywords(`${topic}\n${script}\n${competitorSource}`, cleanManualKeywords),
    [topic, script, competitorSource, cleanManualKeywords]
  )
  const allKeywords = useMemo(
    () => mergeKeywordInsights(aiKeywordInsights, localKeywordCandidates),
    [aiKeywordInsights, localKeywordCandidates]
  )
  const keywords = useMemo(() => {
    const disabled = new Set(disabledKeywordValues.map((x) => x.toLowerCase()))
    return allKeywords.filter((kw) => !disabled.has(kw.value.toLowerCase()))
  }, [allKeywords, disabledKeywordValues])
  const segments = useMemo(() => attachSegmentKeywords(splitScript(script), keywords), [script, keywords])
  const selectedSegment = segments.find((segment) => segment.id === selectedSegmentId) || segments[0]
  const selectedSetting = selectedSegment ? (voiceSettings[selectedSegment.id] || inferVoiceSetting(selectedSegment, Math.max(0, selectedSegment.index - 1), segments.length, scriptMode)) : null
  const selectedShot = shotPlan.find((shot) => shot.id === selectedShotId) || shotPlan[0]
  const videoUrl = extractVideoUrl(job)
  const selectedSubtitleStyleBase = subtitleStyles.find((item) => item.id === subtitleStyleId) || subtitleStyles[0] || SUBTITLE_STYLE_FALLBACK[0]
  const selectedSubtitleStyle: SubtitleStyle = {
    ...selectedSubtitleStyleBase,
    ...subtitleStyleOverrides,
  }
  const selectedAssets = asArray(project.asset_context || project.selected_assets || project.r2_material_context)
  const avatarConfig = project.avatar_config || null
  const currentTaskLeads = asArray(project.current_task_leads).filter((item: any) => {
    const bound = String(item?.job_id || item?.run_id || item?.video_job_id || '')
    return !jobId || !bound || bound === jobId
  })
  const historicalLeads = asArray(project.historical_leads || project.leads)
  const leadCount = currentTaskLeads.length
  const workflowAction = String(workflow?.next_action || '')
  const visualIntegrity = workflow?.visual_integrity && typeof workflow.visual_integrity === 'object' ? workflow.visual_integrity : {}
  const workflowParts = workflowResultParts(workflow)
  const workflowReview = workflowParts.review
  const workflowPackaging = workflowParts.packaging
  const workflowCover = workflowParts.cover
  const workflowXhs = workflowParts.xhs
  const workflowCoverImages = asArray(workflowCover?.images)
  const workflowXhsImages = asArray(workflowXhs?.images)
  const workflowSelection = workflow?.selection && typeof workflow.selection === 'object' ? workflow.selection : {}
  const workflowCoverVideo =
    workflow?.cover_video && typeof workflow.cover_video === 'object'
      ? workflow.cover_video
      : workflowSelection?.cover_video && typeof workflowSelection.cover_video === 'object'
        ? workflowSelection.cover_video
        : {}
  const workflowDelivery = workflow?.delivery && typeof workflow.delivery === 'object' ? workflow.delivery : {}
  const finalPreviewUrl = String(
    workflowDelivery?.final_video_url ||
    workflowCoverVideo?.url ||
    videoUrl ||
    '',
  )

  useEffect(() => {
    setSegmentEditDraft(selectedSegment?.text || '')
  }, [selectedSegmentId, selectedSegment?.text])

  useEffect(() => {
    let alive = true
    apiGet(`/api/video/integration/knowledge/context?topic=${encodeURIComponent(topic)}&city=${encodeURIComponent(city)}&market=${encodeURIComponent(market)}&limit=30`, 60000)
      .then((res) => {
        if (!alive) return
        const list = Array.isArray(res?.cards) ? res.cards : []
        setKnowledgeContext(res)
        setRemoteBrainCards(list.map((item: any) => ({
          id: String(item.id || ''),
          title: String(item.title || ''),
          type: String(item.type || item.card_type || ''),
          source: String(item.source || 'integration_knowledge'),
          content: String(item.content || ''),
          tags: Array.isArray(item.tags) ? item.tags : [],
          score: Number(item.score || 0),
          status: String(item.status || 'approved'),
          usedCount: Number(item.usedCount || item.used_count || 0),
        })))
        if (!selectedKnowledgeIds.length && Array.isArray(res?.selected_ids)) {
          setSelectedKnowledgeIds(res.selected_ids.slice(0, 20).map(String))
        }
      })
      .catch(() => {
        if (alive) {
          setKnowledgeContext(null)
          setRemoteBrainCards([])
        }
      })
    return () => { alive = false }
  }, [topic, city, market])

  useEffect(() => {
    let alive = true
    apiGet('/api/video/subtitle-library/styles', 60000)
      .then((res) => {
        if (!alive) return
        const list = Array.isArray(res?.styles) ? res.styles : []
        if (list.length) {
          setSubtitleStyles(list)
          if (!list.some((item: SubtitleStyle) => item.id === subtitleStyleId)) {
            const fallbackId = String(res?.default_style_id || list[0]?.id || 'douyin_pop')
            setSubtitleStyleId(fallbackId)
            const fallback = list.find((item: SubtitleStyle) => item.id === fallbackId) || list[0]
            setSubtitleStyleOverrides({
              font_size: Number(fallback?.font_size || 104),
              outline: Number(fallback?.outline ?? 6),
              margin_v: Number(fallback?.margin_v || 280),
              max_chars: Number(fallback?.max_chars || 11),
              max_lines: Number(fallback?.max_lines || 1),
            })
          }
        }
      })
      .catch(() => {
        if (alive) setSubtitleStyles(SUBTITLE_STYLE_FALLBACK)
      })
    return () => { alive = false }
  }, [])

  useEffect(() => {
    clearOldWizardDrafts()
    const dirtyProjectText = `${project.manualKeywords || ''} ${project.manual_keywords || ''} ${project.script || ''} ${JSON.stringify(project.ai_keyword_insights || [])}`
    if (draftLooksPolluted({ manualKeywords: dirtyProjectText, script: String(project.script || ''), aiKeywordInsights: project.ai_keyword_insights || [] })) {
      setProject({ ...project, script: '', manualKeywords: '', manual_keywords: '', ai_keyword_insights: [], keyword_insights: [], segments: [], script_segments: [], segment_voice_settings: {}, manual_shot_plan: [], shot_overrides: [] })
      setManualKeywords('')
      setScript('')
      setAiKeywordInsights([])
      setShotPlan([])
      setVoiceSettings({})
      setAiStatus('已清空项目草稿里的脏数据：62、模板名、OpenClaw、内容大脑不会再进入文案。')
      saveWizardDraft({ step: 1 })
      return
    }
    const cleaned = cleanManualKeywordText(manualKeywords)
    let touched = false
    if (manualKeywords && cleaned !== manualKeywords) {
      setManualKeywords(cleaned)
      setAiKeywordInsights([])
      touched = true
    }
    if (scriptLooksPolluted(script)) {
      setScript('')
      setShotPlan([])
      setVoiceSettings({})
      touched = true
    }
    if (touched) {
      setAiStatus('已自动清空旧草稿污染：模板名、序号、OpenClaw、内容大脑等不会再进入文案。')
      saveWizardDraft({})
    } else if (!script) {
      setAiStatus('可以先点「AI 生成主题/关键词」，再调用 DeepSeek 生成文案。')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!segments.length) return
    setVoiceSettings((current) => {
      const next = { ...current }
      segments.forEach((segment, index) => {
        if (!next[segment.id]) next[segment.id] = inferVoiceSetting(segment, index, segments.length, scriptMode)
      })
      return next
    })
    if (!segments.find((segment) => segment.id === selectedSegmentId)) setSelectedSegmentId(segments[0].id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [segments.length, script, scriptMode])

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
    pollFailureRef.current = 0
    pollInFlightRef.current = false

    const queryCurrentJob = async () => {
      if (!alive || pollInFlightRef.current) return
      pollInFlightRef.current = true
      try {
        const data = await apiGet(`/api/video/full-ai/one-scene/job/${jobId}`, 180000)
        if (!alive) return
        if (String(data?.job_id || jobId) !== jobId) {
          throw new Error('后端返回了不同任务 ID，已阻止串任务。')
        }
        pollFailureRef.current = 0
        setJob(data)
        const hasVideo = Boolean(extractVideoUrl(data))
        if (hasVideo && finalStatus(data)) {
          setBusy('')
          setError('')
        } else if (!hasVideo && jobFailed(data)) {
          setBusy('')
          setError(`任务 ${jobId} 生成失败：${data?.message || data?.error?.detail || data?.status || '未知错误'}`)
        } else {
          // 只要任务仍在生成，单次网络抖动恢复后立即清除查询警告。
          setError((current) => current.startsWith('网络查询暂时失败') || current.startsWith('连续查询失败') ? '' : current)
        }
      } catch (err: any) {
        if (!alive) return
        pollFailureRef.current += 1
        const failures = pollFailureRef.current
        const detail = err?.message || String(err)
        // 查询接口偶发失败不等于生成任务失败；保持 busy 并继续轮询，绝不拿其他任务替代。
        if (failures < 5) {
          setError(`网络查询暂时失败（${failures}/5），正在自动重试。任务 ${jobId} 仍可能在后台生成：${detail}`)
        } else {
          setError(`连续查询失败 ${failures} 次，但系统不会停止或替换任务 ${jobId}。请保持页面打开，或稍后刷新继续恢复：${detail}`)
        }
      } finally {
        pollInFlightRef.current = false
      }
    }

    void queryCurrentJob()
    const timer = window.setInterval(() => void queryCurrentJob(), 5000)
    return () => {
      alive = false
      pollInFlightRef.current = false
      window.clearInterval(timer)
    }
  }, [jobId, busy])


  useEffect(() => {
    if (!jobId || !videoUrl || !finalStatus(job)) return
    let alive = true

    const loadWorkflow = async () => {
      try {
        let data = await apiGet(`/api/video/workflow/${encodeURIComponent(jobId)}`, 90000)
        if (!alive) return
        if (String(data?.job_id || '') !== jobId) {
          throw new Error('工作流返回了不同任务 ID，已阻止串任务。')
        }
        setWorkflow(data)
        setWorkflowError('')

        if (data?.next_action === 'run_review' && reviewLaunchRef.current !== jobId) {
          reviewLaunchRef.current = jobId
          setWorkflowBusy('自动审片')
          try {
            data = await apiPost(
              `/api/video/workflow/${encodeURIComponent(jobId)}/run-review`,
              { source: 'old_ui_v10_40_2_auto_review' },
              360000,
            )
            if (!alive) return
            setWorkflow(data)
          } finally {
            if (alive) setWorkflowBusy('')
          }
        }
      } catch (err: any) {
        if (!alive) return
        reviewLaunchRef.current = ''
        setWorkflowError(err?.message || String(err))
      }
    }

    void loadWorkflow()
    const timer = window.setInterval(
      () => void loadWorkflow(),
      workflow?.next_action === 'ready_to_publish' ? 20000 : 6000,
    )

    return () => {
      alive = false
      window.clearInterval(timer)
    }
  }, [jobId, videoUrl, job?.status, job?.stage, workflow?.next_action])


  useEffect(() => {
    saveWizardDraft({
      step,
      sourceMode,
      topic,
      market,
      city,
      contentType,
      scriptMode,
      targetDuration,
      competitorSource,
      manualKeywords: cleanManualKeywords,
      script,
      selectedSegmentId,
      voiceSettings,
      shotPlan,
      selectedShotId,
      jobId,
      job,
      sourceResult,
      disabledKeywordValues,
      aiKeywordInsights,
      aiStatus,
      buttonStatus,
      subtitleEnabled,
      subtitleStyleId,
      subtitleStyleOverrides,
      generationStartedAt,
      workflow,
      savedAt: new Date().toISOString(),
    })
  }, [step, sourceMode, topic, market, city, contentType, scriptMode, targetDuration, competitorSource, manualKeywords, script, selectedSegmentId, voiceSettings, shotPlan, selectedShotId, jobId, job, sourceResult, disabledKeywordValues, aiKeywordInsights, aiStatus, buttonStatus, subtitleEnabled, subtitleStyleId, subtitleStyleOverrides, generationStartedAt, workflow])



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
      await aiGenerateScriptAndVoice(null)
      return
    }

    if (!competitorSource.trim()) {
      setSourceError(sourceMode === 'account' ? '请先填写真实抖音主页、账号名或种子账号。' : '请先填写真实爆款视频链接。')
      return
    }

    setSourceBusy('检查 OpenClaw 并启动真实采集')
    const sourcePayload = {
      source: 'video_creation_wizard_v10_40_6',
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
      collect_accounts: true,
      collect_videos: true,
      collect_comments: true,
    }

    try {
      const health = await apiGet('/api/video/integration/openclaw/status', 60000)
      if (!health?.online) throw new Error('OpenClaw 离线，无法开始真实采集；系统不会再用“只保存账号”冒充采集成功。')
      const data = await apiPost('/api/video/integration/openclaw/start', sourcePayload, 240000)
      if (!data?.job_id) throw new Error('真实采集接口没有返回 job_id，已阻止假成功。')
      setSourceResult(data)
      setProject({
        ...project,
        market,
        topic,
        city,
        sourceMode,
        competitorSource,
        openclaw_job_id: String(data.job_id),
        openclaw_job: data,
        collector_source_result: data,
      })
      setSourceError('')
      setAiStatus(`真实采集任务 ${data.job_id} 已启动。文案先使用已批准知识，任务完成后可在 OpenClaw 页沉淀新问题。`)
      await aiGenerateScriptAndVoice(data)
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
      scriptMode,
      script_mode: scriptMode,
      targetDuration,
      script,
      manualKeywords: cleanManualKeywords,
      competitorSource,
      sourceMode,
      keyword_insights: keywords,
      ai_keyword_insights: aiKeywordInsights,
      burn_subtitles: subtitleEnabled,
      subtitle_required: subtitleEnabled,
      subtitle_style_id: subtitleStyleId || 'douyin_pop',
      subtitle_style: selectedSubtitleStyle,
      subtitle_style_overrides: subtitleStyleOverrides,
      ai_status: aiStatus,
      content_brain_context: videoBrainCards.filter((card) => !selectedKnowledgeIds.length || selectedKnowledgeIds.includes(String(card.id || ""))),
      selected_knowledge_card_ids: selectedKnowledgeIds,
      knowledge_source_counts: knowledgeContext?.counts || {},
      script_segments: segments,
      segment_voice_settings: voiceSettings,
      manual_shot_plan: shotPlan,
      shot_overrides: shotPlan,
      transition_plan: shotPlan.map((shot) => ({ index: shot.index, transition: shot.transition, camera: shot.camera })),
      workflow_job_id: jobId,
      workflow,
      ...extra,
    }
    setProject(next)
    return next
  }

  function noteButton(message: string) {
    setButtonStatus(`${new Date().toLocaleTimeString()} · ${message}`)
  }

  async function runWorkflowAction(
    name: string,
    path: string,
    payload: Record<string, any> = {},
    timeoutMs = 420000,
  ) {
    if (!jobId || workflowBusy) return
    setWorkflowBusy(name)
    setWorkflowError('')
    try {
      const data = await apiPost(path, payload, timeoutMs)
      if (String(data?.job_id || jobId) !== jobId) {
        throw new Error('工作流操作返回了不同任务 ID，已阻止串任务。')
      }
      setWorkflow(data)
      syncProject({ workflow_job_id: jobId, workflow: data })
    } catch (err: any) {
      setWorkflowError(err?.message || String(err))
    } finally {
      setWorkflowBusy('')
    }
  }

  async function recoverLatestDoneVideo(silent = false) {
    try {
      const data = await apiGet('/api/video/wizard-video/latest-done?limit=30&strict_one_scene=1', 60000)
      const found = data?.job || data?.latest || null
      const foundUrl = found?.video_url || found?.url || ''
      if (foundUrl) {
        const recovered = { ok: true, status: 'done', stage: 'recovered_from_recent_jobs', progress: 100, ...found, video_url: foundUrl }
        setJob(recovered)
        setJobId(String(found.job_id || jobId || 'recovered_latest'))
        setBusy('')
        setError('')
        if (!silent) noteButton('已从后端最近任务里找回成片。')
        return recovered
      }
    } catch (err) {
      try {
        const data = await apiGet('/api/video/jobs/recent?limit=30', 60000)
        const jobs = Array.isArray(data?.jobs) ? data.jobs : []
        const found = jobs.find((item: any) => item?.status === 'done' && item?.video_url && (String(item?.job_type || '').toLowerCase() === 'one_scene' || String(item?.job_id || '').startsWith('one_scene_') || item?.single_scene))
        if (found?.video_url) {
          const recovered = { ok: true, status: 'done', stage: 'recovered_from_jobs_recent', progress: 100, ...found }
          setJob(recovered)
          setJobId(String(found.job_id || jobId || 'recovered_latest'))
          setBusy('')
          setError('')
          if (!silent) noteButton('已从 jobs/recent 找回成片。')
          return recovered
        }
      } catch {}
    }
    if (!silent) setError('暂时没有找到已完成成片，可能还在 fal/合成/字幕烧录。')
    return null
  }

  function hardResetWizard() {
    try {
      Object.keys(window.localStorage).forEach((key) => {
        if (key.startsWith('ai_video_wizard_draft_') || key === 'ai_video_engineering_project_draft_v16' || key === 'ai_video_engineering_project_draft_v15') {
          window.localStorage.removeItem(key)
        }
      })
      window.localStorage.setItem(CLEAN_ONCE_KEY, '1')
    } catch {}
    setStep(1)
    setSourceMode('custom')
    setTopic(DEFAULT_TOPIC)
    setMarket(DEFAULT_MARKET)
    setCity('kuala_lumpur')
    setContentType('investment')
    setScriptMode('professional')
    setTargetDuration(15)
    setCompetitorSource('')
    setManualKeywords('')
    setManualKeywordDraft('')
    setScript('')
    setVoiceSettings({})
    setShotPlan([])
    setJobId('')
    setJob(null)
    setWorkflow(null)
    setWorkflowBusy('')
    setWorkflowError('')
    reviewLaunchRef.current = ''
    setSourceResult(null)
    setDisabledKeywordValues([])
    setAiKeywordInsights([])
    setError('')
    setSourceError('')
    setAiStatus('已清空旧草稿和脏关键词。请点「AI 生成主题/关键词」，再生成文案。')
    setButtonStatus('已重置入口；不会再恢复 62、模板名、OpenClaw 等旧数据。')
    setProject({ ...project, topic: DEFAULT_TOPIC, market: DEFAULT_MARKET, city: 'kuala_lumpur', contentType: 'investment', scriptMode: 'professional', targetDuration: 15, script: '', manualKeywords: '', manual_keywords: '', ai_keyword_insights: [], keyword_insights: [], segments: [], script_segments: [], segment_voice_settings: {}, manual_shot_plan: [], shot_overrides: [], job_id: '', lastOutput: null })
    saveWizardDraft({ step: 1 })
  }

  function openWorkspaceTab(tab: WorkspaceTab) {
    syncProject()
    noteButton(`已保存当前向导草稿，正在切到${tab}。回来会恢复进度。`)
    goTab(tab)
  }

  async function aiGenerateTopicAndKeywords() {
    setError('')
    setSourceError('')
    setAiBusy('DeepSeek 正在生成主题')
    setAiStatus('DeepSeek 正在结合市场、城市、内容方向和内容大脑生成主题与关键词。')
    try {
      const data = await apiPost('/api/video/wizard-ai/generate-topic', {
        market,
        city,
        current_topic: topic,
        content_type: contentType,
        script_mode: scriptMode,
        manual_keywords: cleanManualKeywords,
        competitor_source: competitorSource,
        content_brain_context: compactBrainForWizard(videoBrainCards.filter((card) => !selectedKnowledgeIds.length || selectedKnowledgeIds.includes(String(card.id || "")))),
        selected_knowledge_card_ids: selectedKnowledgeIds,
        knowledge_source_counts: knowledgeContext?.counts || {},
        source_result: sourceResult,
      }, 180000)
      const nextTopic = String(data?.topic || data?.title || topic || '').trim()
      const nextScriptMode = String(data?.script_mode || scriptMode) as ScriptMode
      const nextContentType = String(data?.content_type || contentType) as ContentType
      const nextManual = cleanManualKeywordText(Array.isArray(data?.keywords) ? data.keywords.map((x: any) => x?.value || x?.keyword || x).join('，') : String(data?.manual_keywords || cleanManualKeywords || ''))
      const nextInsights = Array.isArray(data?.keywords) ? data.keywords.map(normalizeKeywordInsight).filter(Boolean) as KeywordInsight[] : []
      if (nextTopic) setTopic(nextTopic)
      if (['lead','professional','life','sales'].includes(nextScriptMode)) setScriptMode(nextScriptMode)
      if (['investment','own_stay','second_home','rental','education'].includes(nextContentType)) setContentType(nextContentType)
      setManualKeywords(nextManual)
      setAiKeywordInsights(nextInsights)
      setDisabledKeywordValues([])
      setAiStatus(`DeepSeek 已生成主题与 ${nextInsights.length || splitKeywordCandidates(nextManual).length} 个干净关键词。`)
      syncProject({ topic: nextTopic, scriptMode: nextScriptMode, contentType: nextContentType, manualKeywords: nextManual, ai_keyword_insights: nextInsights, ai_status: 'DeepSeek 已生成主题与关键词' })
      return nextTopic
    } catch (err: any) {
      const msg = err?.message || String(err)
      setAiStatus(`DeepSeek 主题生成失败：${msg}`)
      setError(msg)
      throw err
    } finally {
      setAiBusy('')
    }
  }

  async function runFlowAction(action: 'topic' | 'script' | 'voice' | 'shots' | 'video' | 'collect') {
    setError('')
    setSourceError('')
    if (action === 'topic') {
      setStep(1)
      noteButton('开始调用 DeepSeek 生成/优化主题和关键词。')
      await aiGenerateTopicAndKeywords()
      return
    }
    if (action === 'collect') {
      noteButton(sourceMode === 'custom' ? '自定义主题不采集；需要采集请切到抖音主页或爆款链接。' : '正在下发真实采集任务。')
      await runSourceAction()
      return
    }
    if (action === 'script') {
      noteButton('开始调用 DeepSeek 生成文案和逐句配音。')
      await aiGenerateScriptAndVoice()
      setStep(2)
      return
    }
    if (action === 'voice') {
      if (!script.trim()) {
        noteButton('没有文案，先调用 DeepSeek 生成文案，再进入逐句配音。')
        await aiGenerateScriptAndVoice()
      } else {
        noteButton('开始调用 DeepSeek 判断逐句语气、情绪、音量和停顿。')
        await aiTuneVoiceAll()
      }
      setStep(2)
      return
    }
    if (action === 'shots') {
      if (!script.trim()) {
        setError('还没有口播文案，不能生成镜头。请先点「生成文案」。')
        noteButton('镜头按钮已拦截：没有文案不能假生成镜头。')
        setStep(1)
        return
      }
      const nextSegments = attachSegmentKeywords(splitScript(script), keywords)
      const nextShots = generateShotPlan(nextSegments, targetDuration, city, project)
      setShotPlan(nextShots)
      setSelectedShotId(nextShots[0]?.id || 'shot_1')
      noteButton(`已按真实口播重建 ${nextShots.length} 个镜头：已强制单一全屏镜头、混合室内/阳台/大堂/泳池/社区/带看，并禁用分屏拼贴和文件桌面。`)
      setStep(3)
      return
    }
    if (action === 'video') {
      if (!script.trim()) {
        setError('还没有 DeepSeek 文案，不能生成视频。')
        noteButton('生成视频已拦截：必须先有文案、逐句配音和镜头计划。')
        setStep(1)
        return
      }
      if (!shotPlan.length) {
        const nextSegments = attachSegmentKeywords(splitScript(script), keywords)
        const nextShots = generateShotPlan(nextSegments, targetDuration, city, project)
        setShotPlan(nextShots)
        noteButton(`没有镜头计划，已先补齐 ${nextShots.length} 个镜头；请确认后再生成视频。`)
        setStep(3)
        return
      }
      noteButton('开始调用 单场景动态 TTS-first：生成后会自动烧录字幕，并用任务恢复接口捞成片。')
      await startGenerate()
      return
    }
  }

  function normalizeBackendSegments(rawSegments: any[], nextScript: string, activeKeywords: KeywordInsight[]) {
    const base = Array.isArray(rawSegments) && rawSegments.length
      ? rawSegments.map((item: any, index: number) => ({
        id: String(item?.id || `seg_${index + 1}`),
        index: Number(item?.index || index + 1),
        text: String(item?.text || '').trim(),
        keywords: [],
      })).filter((item: ScriptSegment) => item.text)
      : splitScript(nextScript)
    return attachSegmentKeywords(base, activeKeywords)
  }

  function wizardAiPayload(sourceData: any = sourceResult) {
    return {
      topic,
      market,
      city: cityLabel(city),
      city_key: city,
      content_type: contentType,
      script_mode: scriptMode,
      target_duration_seconds: targetDuration,
      manual_keywords: cleanManualKeywords,
      competitor_source: competitorSource,
      content_brain_context: compactBrainForWizard(videoBrainCards.filter((card) => !selectedKnowledgeIds.length || selectedKnowledgeIds.includes(String(card.id || "")))),
        selected_knowledge_card_ids: selectedKnowledgeIds,
        knowledge_source_counts: knowledgeContext?.counts || {},
      ignored_brain_cards: nonVideoBrainCards.map((card) => ({ id: card.id, title: card.title, type: card.type })),
      source_result: sourceData,
      current_script: script,
      require_llm: true,
    }
  }

  async function aiAnalyzeKeywords() {
    setError('')
    setSourceError('')
    setAiBusy('DeepSeek 正在分析关键词')
    setAiStatus('正在调用 DeepSeek 结合主题、内容大脑、手动词和采集上下文筛选关键词...')
    try {
      const data = await apiPost('/api/video/wizard-ai/analyze-keywords', wizardAiPayload(), 180000)
      const next = Array.isArray(data?.keywords) ? data.keywords.map(normalizeKeywordInsight).filter(Boolean) as KeywordInsight[] : []
      if (!next.length) throw new Error('DeepSeek 没有返回有效关键词。')
      setAiKeywordInsights(next)
      setDisabledKeywordValues([])
      setAiStatus(`DeepSeek 已筛出 ${next.length} 个有效关键词，已过滤 62、模板名和泛词。`)
      setProject({ ...project, ai_keyword_insights: next, ai_status: `DeepSeek 已筛出 ${next.length} 个关键词` })
      return next
    } catch (err: any) {
      const msg = err?.message || String(err)
      setAiStatus(`DeepSeek 关键词分析失败：${msg}`)
      setError(msg)
      throw err
    } finally {
      setAiBusy('')
    }
  }

  async function aiTuneVoiceAll(nextScript = script, nextSegments = segments, activeKeywords = keywords) {
    setError('')
    setAiBusy('DeepSeek 正在判断语气情绪')
    setAiStatus('正在调用 DeepSeek 逐句判断语气、情绪、语速、音量和停顿...')
    try {
      const data = await apiPost('/api/video/wizard-ai/tune-voice', {
        script: nextScript,
        script_mode: scriptMode,
        keywords: activeKeywords,
        script_segments: nextSegments,
        require_llm: true,
      }, 180000)
      const nextSettings = data?.segment_voice_settings || {}
      if (!Object.keys(nextSettings).length) throw new Error('DeepSeek 没有返回逐句配音设置。')
      setVoiceSettings(nextSettings)
      setAiStatus(`DeepSeek 已完成 ${Object.keys(nextSettings).length} 句语气/情绪/停顿判断。`)
      setProject({ ...project, segment_voice_settings: nextSettings, script_segments: nextSegments, ai_status: 'DeepSeek 已完成逐句配音判断' })
      return nextSettings
    } catch (err: any) {
      const msg = err?.message || String(err)
      setAiStatus(`DeepSeek 逐句配音失败：${msg}`)
      setError(msg)
      throw err
    } finally {
      setAiBusy('')
    }
  }

  async function aiGenerateScriptAndVoice(sourceData: any = sourceResult) {
    setError('')
    setSourceError('')
    setAiBusy('DeepSeek 正在生成文案')
    setAiStatus('正在调用 DeepSeek 结合内容大脑、关键词和业务目标生成文案，不再本地秒出假文案...')
    try {
      let activeKeywords = keywords
      if (!aiKeywordInsights.length) {
        const keywordData = await apiPost('/api/video/wizard-ai/analyze-keywords', wizardAiPayload(sourceData), 180000)
        const nextAiKeywords = Array.isArray(keywordData?.keywords) ? keywordData.keywords.map(normalizeKeywordInsight).filter(Boolean) as KeywordInsight[] : []
        if (nextAiKeywords.length) {
          setAiKeywordInsights(nextAiKeywords)
          activeKeywords = mergeKeywordInsights(nextAiKeywords, localKeywordCandidates)
          setDisabledKeywordValues([])
        }
      }

      const data = await apiPost('/api/video/wizard-ai/generate-script', {
        ...wizardAiPayload(sourceData),
        keywords: activeKeywords,
      }, 240000)
      const nextScript = String(data?.script || '').trim()
      if (!nextScript) throw new Error('DeepSeek 没有返回有效文案。')
      const selectedKeywords = Array.isArray(data?.selected_keywords) ? data.selected_keywords.map(normalizeKeywordInsight).filter(Boolean) as KeywordInsight[] : []
      if (selectedKeywords.length) {
        activeKeywords = mergeKeywordInsights(selectedKeywords, activeKeywords)
        setAiKeywordInsights(activeKeywords)
      }
      const nextSegments = normalizeBackendSegments(data?.segments || [], nextScript, activeKeywords)
      const nextShots = generateShotPlan(nextSegments, targetDuration, city, project)
      setScript(nextScript)
      setShotPlan(nextShots)
      setSelectedSegmentId(nextSegments[0]?.id || 'seg_1')
      setSelectedShotId(nextShots[0]?.id || 'shot_1')
      setAiStatus(`DeepSeek 文案生成完成：${nextScript.length} 字，${nextSegments.length} 句；继续判断逐句配音。`)
      const nextVoiceSettings = await aiTuneVoiceAll(nextScript, nextSegments, activeKeywords)
      syncProject({ script: nextScript, segments: nextSegments, script_segments: nextSegments, segment_voice_settings: nextVoiceSettings, manual_shot_plan: nextShots, shot_overrides: nextShots, ai_keyword_insights: activeKeywords, ai_status: 'DeepSeek 文案与逐句配音已完成' })
      return nextScript
    } catch (err: any) {
      const msg = err?.message || String(err)
      setAiStatus(`DeepSeek 文案生成失败：${msg}`)
      setError(msg)
      throw err
    } finally {
      setAiBusy('')
    }
  }

  function rebuildScript() {
    const nextScript = generateScript(topic, city, targetDuration, contentType, keywords, scriptMode)
    setScript(nextScript)
    const nextSegments = attachSegmentKeywords(splitScript(nextScript), keywords)
    const nextShots = generateShotPlan(nextSegments, targetDuration, city, project)
    setShotPlan(nextShots)
    setSelectedSegmentId(nextSegments[0]?.id || 'seg_1')
    setSelectedShotId(nextShots[0]?.id || 'shot_1')
    setAiStatus('本地兜底文案已生成；正式使用请点 DeepSeek 生成。')
    syncProject({ script: nextScript, segments: nextSegments, manual_shot_plan: nextShots })
  }

  function updateSetting(patch: Partial<SegmentVoiceSetting>) {
    if (!selectedSegment) return
    const base = voiceSettings[selectedSegment.id] || inferVoiceSetting(selectedSegment, Math.max(0, selectedSegment.index - 1), segments.length, scriptMode)
    const next = { ...voiceSettings, [selectedSegment.id]: { ...base, ...patch } }
    setVoiceSettings(next)
    setProject({ ...project, segment_voice_settings: next })
  }

  function applyEditedSegments(nextTexts: string[], focusIndex: number) {
    const nextScript = joinSegmentTexts(nextTexts)
    const nextSegments = attachSegmentKeywords(splitScript(nextScript), keywords)
    const nextId = nextSegments[Math.max(0, Math.min(focusIndex, nextSegments.length - 1))]?.id || 'seg_1'
    const nextShots = shotPlan.map((shot, shotIndex) => {
      const segment = nextSegments[shotIndex % Math.max(nextSegments.length, 1)]
      if (!segment) return shot
      return {
        ...shot,
        narration: segment.text,
        prompt: buildPrompt(city, shot.scene, segment.text, shot.index),
      }
    })

    setScript(nextScript)
    setSelectedSegmentId(nextId)
    setSegmentEditDraft(nextSegments.find((item) => item.id === nextId)?.text || '')
    if (nextShots.length) setShotPlan(nextShots)
    setProject({
      ...project,
      script: nextScript,
      script_segments: nextSegments,
      segment_voice_settings: voiceSettings,
      manual_shot_plan: nextShots.length ? nextShots : shotPlan,
      shot_overrides: nextShots.length ? nextShots : shotPlan,
    })
    noteButton(`已保存第 ${focusIndex + 1} 句，并同步到口播、配音、镜头和字幕。`)
  }

  function saveSelectedSegment() {
    if (!selectedSegment) return
    const cleaned = cleanSegmentText(segmentEditDraft)
    if (!cleaned) {
      setVoicePreviewError('本句不能为空。')
      return
    }
    const nextTexts = segments.map((segment) =>
      segment.id === selectedSegment.id ? cleaned : segment.text,
    )
    applyEditedSegments(nextTexts, Math.max(0, selectedSegment.index - 1))
    setVoicePreviewError('')
  }

  function sanitizeWholeScript() {
    const cleaned = joinSegmentTexts(segments.map((segment) => segment.text))
    const nextSegments = splitScript(cleaned)
    applyEditedSegments(nextSegments.map((segment) => segment.text), Math.max(0, (selectedSegment?.index || 1) - 1))
    setAiStatus('已清理文案中的 /、\、|、\n 和多余换行；这些符号不会再进入配音或字幕。')
  }

  function markSelectedTextAsKeyword() {
    const editor = segmentEditorRef.current
    if (!editor || !selectedSegment) return
    const start = editor.selectionStart || 0
    const end = editor.selectionEnd || 0
    const selected = cleanSegmentText(segmentEditDraft.slice(start, end))
    const keyword = usefulKeyword(selected)

    if (!keyword) {
      setVoicePreviewError('请先在本句编辑框里划选 2–12 个有效文字；内部 ID 和占位符会被拦截。')
      editor.focus()
      return
    }

    const cleanedSentence = cleanSegmentText(segmentEditDraft)
    const nextTexts = segments.map((segment) => segment.id === selectedSegment.id ? cleanedSentence : segment.text)
    applyEditedSegments(nextTexts, Math.max(0, selectedSegment.index - 1))

    const nextInsight: KeywordInsight = {
      id: `user_kw_${Date.now()}_${keyword}`,
      value: keyword,
      category: '用户划词',
      reason: `第 ${selectedSegment.index} 句人工划选，必须同步到重音、字幕高亮和镜头语义。`,
      priority: 'high',
    }
    setAiKeywordInsights((current) => mergeKeywordInsights([nextInsight], current.filter((item) => item.value.toLowerCase() !== keyword.toLowerCase())))
    const merged = cleanManualKeywordText([keyword, cleanManualKeywords].filter(Boolean).join('，'))
    setManualKeywords(merged)
    setDisabledKeywordValues((current) => current.filter((item) => item.toLowerCase() !== keyword.toLowerCase()))
    setVoicePreviewError('')
    setAiStatus(`已保存本句并把“${keyword}”设为最高优先级关键词；句子高亮、配音重音、字幕和镜头会立即同步。`)
    noteButton(`第 ${selectedSegment.index} 句已保存并划词：${keyword}`)
  }

  function autoTuneVoiceAll() {
    void aiTuneVoiceAll()
  }

  function addManualKeyword() {
    const words = splitKeywordCandidates(manualKeywordDraft)
    if (!words.length) {
      setAiStatus('没有可加入的有效关键词；序号、模板名、OpenClaw、内容大脑等会被拦截。')
      return
    }
    const merged = cleanManualKeywordText([cleanManualKeywords, words.join('，')].filter(Boolean).join('，'))
    setManualKeywords(merged)
    setManualKeywordDraft('')
    setAiKeywordInsights([])
    setAiStatus('已加入干净手动关键词，请点 DeepSeek 分析关键词重新筛选。')
  }

  function toggleKeyword(value: string) {
    const clean = usefulKeyword(value)
    if (!clean) return
    setDisabledKeywordValues((current) => {
      const exists = current.some((item) => item.toLowerCase() === clean.toLowerCase())
      return exists ? current.filter((item) => item.toLowerCase() !== clean.toLowerCase()) : [...current, clean]
    })
  }

  function smartPickKeywords() {
    const keep = new Set(allKeywords.filter((kw) => kw.priority === 'high' || ['预算/价格', '区域', '人群', '用途', '风险判断'].includes(kw.category)).slice(0, 18).map((kw) => kw.value.toLowerCase()))
    setDisabledKeywordValues(allKeywords.filter((kw) => !keep.has(kw.value.toLowerCase())).map((kw) => kw.value))
  }

  function updateShot(id: string, patch: Partial<ShotPlan>) {
    const next = shotPlan.map((shot) => {
      if (shot.id !== id) return shot
      const merged = { ...shot, ...patch }
      if (patch.scene || patch.narration) merged.prompt = buildPrompt(city, merged.scene, merged.narration, merged.index)
      return merged
    })
    setShotPlan(next)
    setProject({ ...project, manual_shot_plan: next, shot_overrides: next })
  }

  async function auditSelectedAssets() {
    const candidates = selectedAssets.filter((asset: any) => !assetHasEmbeddedText(asset))
    if (!candidates.length) {
      const result = { ok: true, passed: [], quarantined: [], skipped: 0 }
      setAssetGateResult(result)
      return candidates
    }

    const reports = await Promise.all(candidates.map(async (asset: any) => {
      const value = String(asset?.local_path || asset?.path || asset?.url || asset?.preview_url || '')
      if (!value) return { asset, passed: false, reasons: ['素材没有可审计地址'] }
      try {
        const report = await apiPost('/api/video/integration/assets/gate', {
          path: value,
          url: value,
          sample_count: 12,
        }, 360000)
        return { asset, ...report }
      } catch (err: any) {
        return { asset, passed: false, reasons: [err?.message || String(err)] }
      }
    }))

    const passed = reports.filter((item: any) => item.passed === true).map((item: any) => item.asset)
    const quarantined = reports.filter((item: any) => item.passed !== true)
    const result = { ok: true, passed, quarantined, reports }
    setAssetGateResult(result)

    if (candidates.length && !passed.length) {
      throw new Error(`选择的 ${candidates.length} 个素材全部未通过净素材门禁。请到素材库更换无字幕、无水印、无头像的素材，或清空所选素材后使用 AI 干净镜头。`)
    }
    return passed
  }

  async function startGenerate() {
    setError('')
    setBusy('启动生成')
    setGenerationStartedAt(Date.now())
    setWorkflow(null)
    setWorkflowError('')
    setWorkflowBusy('')
    reviewLaunchRef.current = ''
    setStep(4)

    const cleanSegments = attachSegmentKeywords(
      splitScript(joinSegmentTexts(segments.map((segment) => segment.text))),
      keywords,
    )
    const cleanScript = joinSegmentTexts(cleanSegments.map((segment) => segment.text))
    let cleanAssets: any[] = []
    try {
      cleanAssets = await auditSelectedAssets()
    } catch (assetError: any) {
      setBusy('')
      setError(assetError?.message || String(assetError))
      return
    }
    const finalProject = syncProject({
      script: cleanScript,
      segments: cleanSegments,
      script_segments: cleanSegments,
      asset_context: cleanAssets,
      selected_assets: cleanAssets,
      r2_material_context: cleanAssets,
    })
    const requiredShotCount = targetShotCount(targetDuration)
    const baseShots = shotPlan.length
      ? shotPlan.map((shot, index) => {
          const segment = cleanSegments[index % Math.max(cleanSegments.length, 1)]
          return {
            ...shot,
            narration: cleanSegmentText(segment?.text || shot.narration),
            prompt: buildPrompt(city, shot.scene, '', shot.index),
            avoid: Array.from(new Set([
              ...shot.avoid,
              '字幕', '标题', '水印', '贴纸', 'Logo', 'UI', '字母', '数字', '乱码文字',
            ])),
          }
        })
      : []
    const generatedShots = generateShotPlan(cleanSegments, targetDuration, city, finalProject)
    const finalShots = Array.from({ length: requiredShotCount }, (_, index) => {
      const source = baseShots[index] || generatedShots[index]
      const segment = cleanSegments[index % Math.max(cleanSegments.length, 1)]
      return {
        ...source,
        id: source?.id || `shot_${index + 1}`,
        index: index + 1,
        narration: cleanSegmentText(segment?.text || source?.narration || ''),
        prompt: buildPrompt(city, source?.scene || generatedShots[index]?.scene || '', '', index + 1),
      }
    })
    const renderShotCount = requiredShotCount

    setScript(cleanScript)
    if (cleanAssets.length !== selectedAssets.length) {
      noteButton(`已自动排除 ${selectedAssets.length - cleanAssets.length} 个疑似带字幕/水印素材。`)
    }

    const payload = {
      title: topic,
      topic,
      market,
      city,
      content_type: contentType,
      script_mode: scriptMode,
      script_text: cleanScript,
      target_duration_seconds: targetDuration,
      duration_seconds: targetDuration,
      width: 1080,
      height: 1920,
      fps: 30,
      shots: finalShots.slice(0, renderShotCount).map((shot) => ({
        index: shot.index,
        prompt: buildPrompt(city, shot.scene, '', shot.index),
        visual_prompt: buildPrompt(city, shot.scene, '', shot.index),
        negative_prompt: 'text, subtitles, captions, title, headline, sticker, label, logo, watermark, sign, letters, numbers, pseudo text, gibberish text, UI, split screen, collage, black border',
        narration_segment: cleanSegmentText(shot.narration),
        duration_seconds: shot.duration,
        source: shot.source,
        asset_ids: shot.assetIds,
        reject_embedded_text: true,
      })),
      max_shots: renderShotCount,
      fal_fill_shots: renderShotCount,
      dynamic_shot_count: renderShotCount,
      min_unique_shots: Math.max(4, Math.min(renderShotCount, 8)),
      no_repeat_visuals: true,
      shot_duration_policy: 'follow_audio_duration_no_repeat',
      visual_policy: 'real_condo_tour_no_office_no_papers_no_text',
      visual_text_policy: 'zero_text_zero_caption_zero_watermark',
      reject_embedded_text_assets: true,
      source_caption_policy: 'reject_captioned_source',
      one_scene_mode: true,
      dynamic_single_scene: true,
      visual_mode: 'single_scene_dynamic',
      script_segments: cleanSegments,
      segment_voice_settings: voiceSettings,
      keyword_insights: keywords,
      ai_keyword_insights: aiKeywordInsights,
      burn_subtitles: subtitleEnabled,
      subtitle_required: subtitleEnabled,
      subtitle_style_id: subtitleStyleId || 'douyin_pop',
      subtitle_style: selectedSubtitleStyle,
      subtitle_style_overrides: subtitleStyleOverrides,
      subtitle_text_policy: 'clean_script_only_no_slash_no_literal_newline',
      subtitle_source: 'sanitized_script_segments',
      ai_status: aiStatus,
      content_brain_context: compactBrainForWizard(videoBrainCards.filter((card) => !selectedKnowledgeIds.length || selectedKnowledgeIds.includes(String(card.id || "")))),
      selected_knowledge_card_ids: selectedKnowledgeIds,
      knowledge_source_counts: knowledgeContext?.counts || {},
      knowledge_trace_required: true,
      manual_shot_plan: finalShots.slice(0, renderShotCount),
      shot_overrides: finalShots.slice(0, renderShotCount),
      transition_plan: finalShots.slice(0, renderShotCount).map((shot) => ({
        index: shot.index,
        camera: shot.camera,
        transition: shot.transition,
      })),
      asset_context: cleanAssets,
      selected_assets: cleanAssets,
      r2_material_context: cleanAssets,
      avatar_config: finalProject.avatar_config || avatarConfig,
      openclaw_lead_context: currentTaskLeads,
      openclaw_job_id: finalProject.openclaw_job_id || '',
      extra: {
        source: 'one_scene_condo_tour_douyin_subtitle_v10_17_clean_text',
        source_mode: sourceMode,
        competitor_source: competitorSource,
        content_type: contentType,
        script_mode: scriptMode,
        selected_assets: cleanAssets,
        excluded_captioned_asset_count: selectedAssets.length - cleanAssets.length,
        avatar_config: avatarConfig,
        lead_count: leadCount,
        content_brain_count: videoBrainCards.length,
        strict_visual_no_text: true,
        sanitized_script: true,
      },
    }

    try {
      const data = await apiPost('/api/video/full-ai/one-scene/start', payload, 240000)
      if (!data?.job_id) throw new Error('后端没有返回 job_id')
      setJob(data)
      setJobId(data.job_id)
      syncProject({
        currentJobId: String(data.job_id),
        job_id: String(data.job_id),
        workflow_job_id: String(data.job_id),
        full_ai_job_id: String(data.job_id),
        selected_knowledge_card_ids: selectedKnowledgeIds,
        asset_gate_result: assetGateResult,
      })
      selectedKnowledgeIds.forEach((id) => {
        void apiPost(`/api/video/integration/knowledge/cards/${encodeURIComponent(id)}/mark-used`, {}, 30000).catch(() => {})
      })
      setBusy('单场景动态生成中')
    } catch (err: any) {
      setBusy('')
      setError(err?.message || String(err))
    }
  }

  async function nextStep() {
    if (step === 1) {
      syncProject()
      if (!script.trim()) {
        noteButton('下一步不是空跳转：没有文案，先调用 DeepSeek 生成。')
        await aiGenerateScriptAndVoice()
      }
      setStep(2)
    } else if (step === 2) {
      syncProject()
      if (!segments.length) {
        setError('没有可配音的句子，请先生成或填写口播文案。')
        return
      }
      if (!Object.keys(voiceSettings || {}).length) {
        noteButton('没有逐句配音设置，先调用 DeepSeek 判断语气情绪。')
        await aiTuneVoiceAll()
      }
      if (!shotPlan.length) setShotPlan(generateShotPlan(segments, targetDuration, city, project))
      setStep(3)
    } else if (step === 3) {
      syncProject()
      if (!shotPlan.length) {
        const plan = generateShotPlan(segments, targetDuration, city, project)
        setShotPlan(plan)
        setSelectedShotId(plan[0]?.id || 'shot_1')
        noteButton(`已自动补齐 ${plan.length} 个镜头，请确认后再生成。`)
      }
      setStep(4)
    } else {
      await startGenerate()
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
                <div className="aiw-info">入口已改为 AI 驱动：先 AI 生成主题/关键词，再 DeepSeek 生成文案、配音和镜头。</div>
              </div>
            )}
          </div>

          <div className="aiw-actions aiw-actionChecklist">
            <button type="button" className="aiw-primary" onClick={() => void runFlowAction('topic')} disabled={!!aiBusy || !!sourceBusy}>{aiBusy === 'DeepSeek 正在生成主题' ? 'AI 正在生成主题...' : 'AI 生成主题/关键词'}</button>
            <button type="button" className="aiw-primary" onClick={() => void runFlowAction('script')} disabled={!!aiBusy || !!sourceBusy}>调用 DeepSeek 生成文案</button>
            <button type="button" className="aiw-muted" onClick={() => void runFlowAction('voice')} disabled={!!aiBusy}>AI 逐句配音</button>
            <button type="button" className="aiw-muted" onClick={() => void runFlowAction('video')} disabled={!!busy || !!aiBusy}>生成字幕视频</button>
            {sourceMode !== 'custom' && <button type="button" className="aiw-muted" onClick={() => void runFlowAction('collect')} disabled={!!sourceBusy || !!aiBusy}>真实采集</button>}
          </div>
          {buttonStatus && <div className="aiw-info">{buttonStatus}</div>}

          <div className="aiw-form two">
            <label>市场<input value={market} onChange={(e) => setMarket(e.target.value)} /></label>
            <label>城市<select value={city} onChange={(e) => setCity(e.target.value)}>{CITY_OPTIONS.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}</select></label>
            <label>主题/选题<input value={topic} onChange={(e) => setTopic(e.target.value)} placeholder={sourceMode === 'custom' ? '直接输入要生成的视频主题' : '采集结果会结合这个主题生成文案'} /></label>
            <label>目标时长<select value={targetDuration} onChange={(e) => setTargetDuration(Number(e.target.value))}><option value={15}>15 秒</option><option value={20}>20 秒</option><option value={30}>30 秒</option><option value={45}>45 秒</option><option value={60}>60 秒</option></select></label>
            <label>内容方向<select value={contentType} onChange={(e) => setContentType(e.target.value as ContentType)}>{Object.entries(CONTENT_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
            <label>文案模式<select value={scriptMode} onChange={(e) => setScriptMode(e.target.value as ScriptMode)}>{Object.entries(SCRIPT_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
            <label>来源状态<input readOnly value={sourceResult ? '已下发/已返回采集任务' : sourceMode === 'custom' ? '不采集，直接生成' : '等待下发真实采集'} /></label>
          </div>
          <div className="aiw-wideField aiw-manualKeywordBox">
            <label>可选：补充业务关键词</label>
            <div className="aiw-inlineAdd">
              <input value={manualKeywordDraft} onChange={(e) => setManualKeywordDraft(e.target.value)} onPaste={(e) => { const text = e.clipboardData.getData('text'); if (text.length > 40 || /(62\.?|OpenClaw|模板|规则|类型|模式|用途|内容大脑)/.test(text)) { e.preventDefault(); setAiStatus('已拦截整段粘贴。这里不能粘贴知识库，只能单独加业务短词。') } }} onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addManualKeyword() } }} placeholder="例如：150万、华语、出租、流动性；不要粘贴整段知识库" />
              <button className="aiw-muted" type="button" onClick={addManualKeyword}>加入关键词</button>
              <button className="aiw-muted" type="button" onClick={() => { setManualKeywords(''); setManualKeywordDraft(''); setAiKeywordInsights([]); setAiStatus('已清空手动关键词。') }}>清空关键词</button>
              <button className="aiw-danger" type="button" onClick={hardResetWizard}>清空旧草稿/重来</button>
            </div>
            {manualKeywords && <div className="aiw-chipRow">{splitKeywordCandidates(manualKeywords).map((kw) => <span className="aiw-keywordPill" key={kw}>{kw}</span>)}</div>}
            <p>默认不用手填。主题、关键词和文案都交给 DeepSeek；这里只能补充短业务词，不能再塞模板名和知识库长句。</p>
          </div>
          <div className="aiw-chipRow">
            {cityAnchors(city).map((item) => <span className="aiw-keywordPill" key={item}>{item}</span>)}
          </div>
          <div className="aiw-actions">
            <button type="button" className="aiw-primary" onClick={() => void runSourceAction()} disabled={!!sourceBusy || !!aiBusy}>{sourceBusy || aiBusy || (sourceMode === 'custom' ? '调用 DeepSeek 生成文案' : '下发采集后调用 DeepSeek 生成')}</button>
            <button className="aiw-muted" onClick={() => openWorkspaceTab('collect')}>去同行采集</button>
            <button className="aiw-muted" onClick={() => openWorkspaceTab('leads')}>去真实获客线索</button>
          </div>
          {sourceError && <div className="aiw-error">{sourceError}</div>}
          {sourceResult && <details className="aiw-json"><summary>真实采集/入库返回</summary><pre>{JSON.stringify(sourceResult, null, 2)}</pre></details>}
        </section>
        <aside className="aiw-stepCard aiw-resultPanel">
          <h3>关键词选择</h3>
          <p>点击关键词启用/禁用。只有已启用关键词会进入文案、逐句配音、镜头计划和 OpenClaw 承接。</p>
          <div className="aiw-actions">
            <button className="aiw-primary" type="button" onClick={() => void aiAnalyzeKeywords()} disabled={!!aiBusy}>{aiBusy === 'DeepSeek 正在分析关键词' ? 'DeepSeek 分析中...' : 'DeepSeek 分析关键词'}</button>
            <button className="aiw-muted" type="button" onClick={smartPickKeywords}>按高优先级筛选</button>
            <button className="aiw-muted" type="button" onClick={() => setDisabledKeywordValues([])}>全选关键词</button>
          </div>
          {aiStatus && <div className="aiw-info">{aiStatus}</div>}
          <div className="aiw-keywordGrid">
            {allKeywords.map((kw) => {
              const off = disabledKeywordValues.some((item) => item.toLowerCase() === kw.value.toLowerCase())
              return <button type="button" key={kw.id} className={`aiw-keywordCard ${kw.priority} ${off ? 'muted' : 'active'}`} onClick={() => toggleKeyword(kw.value)}><b>{kw.value}</b><span>{off ? '已关闭' : kw.category}</span><em>{kw.reason}</em></button>
            })}
          </div>
          <div className="aiw-info">已启用 {keywords.length} 个关键词；系统最多保留 36 个候选，建议启用 12～18 个，覆盖区域、预算、人群、用途、痛点、场景和承接动作。</div>
          <h4>内容大脑联动</h4>
          <div className="aiw-brainMiniPanel">
            <b>本次知识来源：Obsidian {knowledgeContext?.counts?.obsidian || 0} 条 · OpenClaw {knowledgeContext?.counts?.openclaw || 0} 条 · 同行 {knowledgeContext?.counts?.competitor || 0} 条 · 历史 {knowledgeContext?.counts?.history || 0} 条</b>
            <p>只有已批准且勾选的知识会进入 DeepSeek 文案上下文；每条来源可追踪，内部占位 ID 不会进入关键词。</p>
            <div className="aiw-knowledgeSourceGrid">{videoBrainCards.slice(0, 20).map((card) => (
              <label key={card.id || card.title} className={selectedKnowledgeIds.includes(String(card.id || "")) ? 'selected' : ''}>
                <input type="checkbox" checked={selectedKnowledgeIds.includes(String(card.id || ""))} onChange={() => setSelectedKnowledgeIds((current) => current.includes(String(card.id || "")) ? current.filter((id) => id !== String(card.id || "")) : [...current, String(card.id || "")].filter(Boolean).slice(0, 30))} />
                <span><b>{card.title || card.type}</b><em>{card.source}</em></span>
              </label>
            ))}</div>
            <div className="aiw-actions">
              <button className="aiw-muted" onClick={() => openWorkspaceTab('brain')}>去内容大脑</button>
              <button className="aiw-muted" onClick={() => void aiAnalyzeKeywords()}>让 DeepSeek 从知识库分析关键词</button>
            </div>
          </div>
          <h4>文案预览</h4>
          <div className="aiw-scriptPreview">{highlightText(script, keywords)}</div>
        </aside>
      </div>
    )
  }

  async function previewSelectedVoice() {
    if (!selectedSegment || !selectedSetting || voicePreviewBusy) return
    setVoicePreviewBusy('正在生成本句试听')
    setVoicePreviewError('')
    setVoicePreviewUrl('')
    try {
      const ratePercent = Math.round((Number(selectedSetting.speed || 1) - 1) * 100)
      const rate = `${ratePercent >= 0 ? '+' : ''}${ratePercent}%`
      const response = await apiPost('/api/tts', {
        text: cleanSegmentText(selectedSegment.text),
        voice:
          project.voice ||
          project.voice_id ||
          project.tts_voice ||
          '',
        rate,
        pitch: selectedSetting.pitch,
        volume: selectedSetting.volume,
        emotion: selectedSetting.emotion,
        tone: selectedSetting.tone,
        pause_before_ms: selectedSetting.pauseBefore,
        pause_after_ms: selectedSetting.pauseAfter,
        preview: true,
      }, 180000)
      const url = String(
        response?.file_url ||
        response?.audio_url ||
        response?.url ||
        '',
      )
      if (!url) throw new Error('试听接口没有返回音频地址。')
      setVoicePreviewUrl(url)
      noteButton(`已生成第 ${selectedSegment.index} 句原生配音试听。`)
    } catch (err: any) {
      setVoicePreviewError(err?.message || String(err))
    } finally {
      setVoicePreviewBusy('')
    }
  }

  function openGraphicWindow() {
    syncProject({ currentJobId: jobId, job_id: jobId, workflow_job_id: jobId })
    goTab('graphic')
  }

  function renderStepTwo() {
    const { min, max } = targetChars(targetDuration)
    const artifactFound = /\\[nr]|[／/|｜\\]|\r|\n/.test(script)
    const sentenceKeywords = selectedSegment?.keywords || []

    return (
      <div className="aiw-stepGrid three aiw-stepTwoGrid">
        <section className="aiw-stepCard aiw-scriptEditorCard">
          <div className="aiw-sectionTitleRow">
            <div>
              <h3>第二步：口播文案</h3>
              <span>建议 {min}-{max} 字，当前 {script.length} 字</span>
            </div>
            <span className={artifactFound ? 'aiw-statusBadge warning' : 'aiw-statusBadge success'}>
              {artifactFound ? '发现换行符号' : '文案干净'}
            </span>
          </div>

          <p>整段文案可以改；保存单句后会同步更新配音、镜头和字幕。</p>

          <div className="aiw-chipRow aiw-keywordToolbar">
            {keywords.slice(0, 20).map((kw) => (
              <button
                type="button"
                className="aiw-keywordPill"
                key={kw.id}
                title={`点击关闭：${kw.reason}`}
                onClick={() => toggleKeyword(kw.value)}
              >
                {kw.value}
              </button>
            ))}
          </div>

          <div className="aiw-actions">
            <button className="aiw-primary" type="button" disabled={!!aiBusy} onClick={() => void aiGenerateScriptAndVoice()}>
              {aiBusy || 'DeepSeek 重写文案并重调配音'}
            </button>
            <button className="aiw-muted" type="button" onClick={sanitizeWholeScript}>
              清理 / 和换行符
            </button>
            <button className="aiw-muted" type="button" onClick={() => setStep(1)}>
              回第一步选关键词
            </button>
          </div>

          <textarea
            className="aiw-scriptTextarea"
            value={script}
            onChange={(e) => setScript(e.target.value)}
            onBlur={() => {
              const cleaned = joinSegmentTexts(splitScript(script).map((item) => item.text))
              if (cleaned && cleaned !== script) setScript(cleaned)
            }}
          />

          <div className="aiw-editorFootnote">
            <span>自动拦截：/、\\、|、\\n、多余换行</span>
            <span>字幕只使用这份清理后的口播文案</span>
          </div>
        </section>

        <section className="aiw-stepCard aiw-segmentListCard">
          <div className="aiw-sectionTitleRow">
            <div>
              <h3>逐句配音与单句编辑</h3>
              <span>点击任意一句，右侧可直接改文字并划关键词</span>
            </div>
            <span className="aiw-statusBadge">{segments.length} 句</span>
          </div>

          <div className="aiw-actions">
            <button className="aiw-primary" type="button" disabled={!!aiBusy} onClick={autoTuneVoiceAll}>
              {aiBusy === 'DeepSeek 正在判断语气情绪' ? 'DeepSeek 判断中...' : 'DeepSeek 自动调好全部句子'}
            </button>
          </div>

          <div className="aiw-segmentPicker aiw-editableSegmentPicker">
            {segments.map((segment) => (
              <button
                key={segment.id}
                type="button"
                className={selectedSegment?.id === segment.id ? 'active' : ''}
                onClick={() => setSelectedSegmentId(segment.id)}
              >
                <span>{String(segment.index).padStart(2, '0')}</span>
                <b>{highlightText(segment.text, segment.keywords)}</b>
                <em>{segment.text.length} 字 · 点击编辑</em>
              </button>
            ))}
          </div>
        </section>

        <aside className="aiw-stepCard aiw-segmentEditorCard">
          <div className="aiw-sectionTitleRow">
            <div>
              <h3>{selectedSegment ? `第 ${selectedSegment.index} 句表达` : '选择一句'}</h3>
              <span>先改句子，再调语气；划选文字可直接标为关键词</span>
            </div>
          </div>

          {!selectedSegment || !selectedSetting ? (
            <div className="aiw-info">点击中间某一句后，才显示该句编辑和配音设置。</div>
          ) : (
            <div className="aiw-form one">
              <label className="aiw-sentenceEditorLabel">
                本句文字
                <textarea
                  ref={segmentEditorRef}
                  className="aiw-sentenceEditor"
                  value={segmentEditDraft}
                  onChange={(e) => setSegmentEditDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
                      e.preventDefault()
                      saveSelectedSegment()
                    }
                  }}
                />
              </label>
              <div className="aiw-richKeywordPreview">
                <b>关键词着色预览</b>
                <p>{highlightText(segmentEditDraft, keywords)}</p>
              </div>

              <div className="aiw-actions aiw-sentenceActions">
                <button className="aiw-primary" type="button" onClick={saveSelectedSegment}>
                  保存本句
                </button>
                <button className="aiw-purple" type="button" onClick={markSelectedTextAsKeyword}>
                  将选中文字标为关键词
                </button>
                <button className="aiw-muted" type="button" onClick={() => setSegmentEditDraft(cleanSegmentText(segmentEditDraft))}>
                  清理本句符号
                </button>
              </div>

              <div className="aiw-editorFootnote">
                <span>{segmentEditDraft.length} 字</span>
                <span>快捷保存：⌘/Ctrl + Enter</span>
              </div>

              <div className="aiw-sentenceKeywordBox">
                <b>本句关键词</b>
                <div className="aiw-chipRow">
                  {sentenceKeywords.length ? sentenceKeywords.map((kw) => (
                    <button
                      type="button"
                      className="aiw-keywordPill active"
                      key={kw.id}
                      title="点击关闭这个关键词"
                      onClick={() => toggleKeyword(kw.value)}
                    >
                      {kw.value}
                    </button>
                  )) : <span className="aiw-emptyHint">划选本句中的词，再点“标为关键词”</span>}
                </div>
              </div>

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
                <button className="aiw-muted" type="button" onClick={() => updateSetting(inferVoiceSetting(selectedSegment, Math.max(0, selectedSegment.index - 1), segments.length, scriptMode))}>AI 重置本句</button>
                <button className="aiw-primary" type="button" disabled={!!voicePreviewBusy} onClick={() => void previewSelectedVoice()}>{voicePreviewBusy || '试听本句配音'}</button>
              </div>

              {voicePreviewError && <div className="aiw-error">{voicePreviewError}</div>}
              {voicePreviewUrl && <audio src={voicePreviewUrl} controls style={{ width: '100%' }} />}
            </div>
          )}
        </aside>
      </div>
    )
  }

  function renderSubtitleLibrary() {
    const setOverride = (key: string, value: number) => {
      setSubtitleStyleOverrides((current) => ({ ...current, [key]: value }))
    }
    const selectPreset = (style: SubtitleStyle) => {
      setSubtitleStyleId(style.id)
      setSubtitleStyleOverrides({
        font_size: Number(style.font_size || 104),
        outline: Number(style.outline ?? 6),
        margin_v: Number(style.margin_v || 280),
        max_chars: Number(style.max_chars || 11),
        max_lines: Number(style.max_lines || 1),
      })
    }
    return (
      <div className="aiw-subtitleLibrary">
        <div className="aiw-inlineTitle"><b>字幕样式与真实输出参数</b><span>预设和自定义参数会直接传入后端 ASS 烧录，不再只是网页示意。</span></div>
        <label className="aiw-checkRow"><input type="checkbox" checked={subtitleEnabled} onChange={(e) => setSubtitleEnabled(e.target.checked)} /> 生成后自动烧录字幕</label>
        <div className="aiw-subtitlePresetGrid">
          {subtitleStyles.map((style) => (
            <button
              key={style.id}
              type="button"
              onClick={() => selectPreset(style)}
              className={subtitleStyleId === style.id ? 'active' : ''}
              style={{ textAlign: 'left', borderRadius: 14, padding: 10, border: subtitleStyleId === style.id ? '2px solid #7c3aed' : '1px solid #e5e7eb', background: '#fff' }}
            >
              <b>{style.name}</b>
              <div style={{ margin: '8px 0', minHeight: 66, borderRadius: 12, background: 'linear-gradient(135deg,#dbeafe,#f5d0fe)', display: 'flex', alignItems: 'end', justifyContent: 'center', padding: 8 }}>
                <span style={{ color: style.primary || '#fff', background: style.background || 'rgba(0,0,0,.65)', borderRadius: 8, padding: '5px 10px', fontWeight: 800, fontSize: `${Math.max(15, Math.min(24, Number(style.font_size || 100) / 5))}px`, textShadow: '0 1px 2px rgba(0,0,0,.7)', borderBottom: `3px solid ${style.accent || '#f59e0b'}` }}>吉隆坡买房 先看区域和用途</span>
              </div>
              <small>{style.description}</small>
            </button>
          ))}
        </div>

        <div className="aiw-panel aiw-subtitleControls">
          <h4>当前预设：{selectedSubtitleStyleBase.name}</h4>
          <div className="aiw-form two">
            <label>字号 {Number(selectedSubtitleStyle.font_size || 104)}
              <input type="range" min="72" max="150" step="2" value={Number(selectedSubtitleStyle.font_size || 104)} onChange={(e) => setOverride('font_size', Number(e.target.value))} />
            </label>
            <label>垂直位置 {Number(selectedSubtitleStyle.margin_v || 280)}
              <input type="range" min="120" max="520" step="10" value={Number(selectedSubtitleStyle.margin_v || 280)} onChange={(e) => setOverride('margin_v', Number(e.target.value))} />
            </label>
            <label>描边 {Number(selectedSubtitleStyle.outline ?? 6)}
              <input type="range" min="0" max="16" step="1" value={Number(selectedSubtitleStyle.outline ?? 6)} onChange={(e) => setOverride('outline', Number(e.target.value))} />
            </label>
            <label>每屏最多 {Number(selectedSubtitleStyle.max_chars || 11)} 字
              <input type="range" min="7" max="20" step="1" value={Number(selectedSubtitleStyle.max_chars || 11)} onChange={(e) => setOverride('max_chars', Number(e.target.value))} />
            </label>
            <label>行数
              <select value={Number(selectedSubtitleStyle.max_lines || 1)} onChange={(e) => setOverride('max_lines', Number(e.target.value))}>
                <option value={1}>单行醒目</option>
                <option value={2}>双行解释</option>
              </select>
            </label>
          </div>
          <div className="aiw-subtitleLivePreview">
            <span style={{ fontSize: `${Math.max(22, Math.min(44, Number(selectedSubtitleStyle.font_size || 104) / 3))}px`, color: selectedSubtitleStyle.primary || '#fff', background: selectedSubtitleStyle.background || 'rgba(0,0,0,.5)', WebkitTextStroke: `${Math.max(0, Number(selectedSubtitleStyle.outline || 0) / 5)}px #000` }}>
              预算不同 选房逻辑也不同
            </span>
          </div>
        </div>
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
            <button className="aiw-muted" onClick={() => openWorkspaceTab('assets')}>去素材库选择 R2/真实素材</button>
            <button className="aiw-muted" onClick={() => openWorkspaceTab('digital')}>去数字人库选谁出镜</button>
            <button type="button" className="aiw-primary" onClick={() => void runFlowAction('shots')}>按文案重建镜头</button>
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
          {renderSubtitleLibrary()}
          <h4>当前素材上下文</h4>
          <div className="aiw-miniList">{selectedAssets.slice(0, 6).map((asset: any, index) => <div key={asset.id || asset.url || index}>{asset.name || asset.original_name || asset.filename || asset.url}</div>)}</div>
        </aside>
      </div>
    )
  }

  function renderStepFour() {
    const reviewScore = Number(
      workflowReview?.overall_score || 0,
    )
    const mechanicalScore = Number(
      workflowReview?.mechanical?.score || 0,
    )
    const aiReviewScore = Number(
      workflowReview?.ai_review?.score ||
      workflowReview?.doubao?.score ||
      0,
    )
    const coverCount = Number(
      workflowPackaging?.cover_count ||
      workflowCover?.cover_count ||
      workflowCoverImages.length ||
      0,
    )
    const pageCount = Number(
      workflowPackaging?.page_count ||
      workflowXhs?.page_count ||
      workflowXhsImages.length ||
      0,
    )
    const selectedCoverIndex =
      workflowSelection?.index !== undefined
        ? Number(workflowSelection.index)
        : -1
    const selectedCover =
      workflowCoverImages[selectedCoverIndex] ||
      workflowCoverImages[0] ||
      null
    const coverVideoReady = Boolean(
      workflowCoverVideo?.url,
    )
    const workflowProgress = Math.min(
      100,
      Number(
        job?.progress ||
        (workflowAction === 'ready_to_publish'
          ? 100
          : coverVideoReady
            ? 94
            : coverCount && pageCount
              ? 84
              : reviewScore
                ? 72
                : busy
                  ? 55
                  : 0),
      ),
    )

    return (
      <div className="aiw-stepGrid aiw-stepFourGrid">
        <section className="aiw-stepCard aiw-stepFourPreviewCard">
          <div className="aiw-sectionTitleRow">
            <div>
              <h3>成片预览</h3>
              <span>
                {coverVideoReady
                  ? '最终版已加入 1 秒主封面'
                  : '先生成成片，再完成审片与封面'}
              </span>
            </div>
            {coverVideoReady && (
              <span className="aiw-statusBadge success">
                已含封面
              </span>
            )}
          </div>

          {finalPreviewUrl ? (
            <video
              className="aiw-previewVideo"
              src={finalPreviewUrl}
              controls
              playsInline
            />
          ) : (
            <div className="aiw-videoPlaceholder">
              <b>🎬</b>
              <span>生成后在这里预览 9:16 成片</span>
            </div>
          )}

          <div className="aiw-previewMeta">
            <div>
              <span>当前版本</span>
              <b>
                {coverVideoReady
                  ? '封面合成最终版'
                  : videoUrl
                    ? '审片原始成片'
                    : '尚未生成'}
              </b>
            </div>
            <div>
              <span>发布尺寸</span>
              <b>9:16 竖屏</b>
            </div>
          </div>

          <div className="aiw-actionGrid">
            <button
              type="button"
              className="aiw-danger"
              onClick={() => void runFlowAction('video')}
              disabled={Boolean(busy)}
            >
              {busy || (videoUrl ? '重新生成 AI 视频' : '生成完整 AI 视频')}
            </button>

            {finalPreviewUrl && (
              <a
                className="aiw-linkButton"
                href={finalPreviewUrl}
                target="_blank"
                rel="noreferrer"
              >
                打开当前成片
              </a>
            )}

            <button
              className="aiw-muted"
              type="button"
              onClick={() =>
                void recoverLatestDoneVideo(false)
              }
            >
              找回最新成片
            </button>
          </div>

          {job?.subtitle_error && (
            <div className="aiw-error">
              字幕烧录失败：{job.subtitle_error}
            </div>
          )}
          {error && (
            <div className="aiw-error">{error}</div>
          )}
        </section>

        <section className="aiw-stepCard aiw-stepFourStatusCard">
          <div className="aiw-sectionTitleRow">
            <div>
              <h3>任务与质量状态</h3>
              <span>
                视频、审片、包装和交付统一绑定当前任务
              </span>
            </div>
            <span className="aiw-statusBadge">
              {workflowProgress}%
            </span>
          </div>

          <div className="aiw-miniProgress">
            <span
              style={{
                width: `${workflowProgress}%`,
              }}
            />
          </div>

          <div className="aiw-workflowMetrics">
            <div>
              <b>{mechanicalScore || '-'}</b>
              <span>机械质检</span>
            </div>
            <div>
              <b>{aiReviewScore || '-'}</b>
              <span>豆包审片</span>
            </div>
            <div>
              <b>{reviewScore || '-'}</b>
              <span>综合评分</span>
            </div>
          </div>

          <div className="aiw-statusRows aiw-statusRowsCompact">
            <div>
              <span>任务 ID</span>
              <b title={jobId || ''}>{jobId || '-'}</b>
            </div>
            <div>
              <span>当前阶段</span>
              <b>
                {job?.stage ||
                job?.status ||
                'ready'}
              </b>
            </div>
            <div>
              <span>配音时长</span>
              <b>
                {job?.audio_duration_seconds
                  ? `${Number(
                      job.audio_duration_seconds,
                    ).toFixed(1)}s`
                  : '生成后读取'}
              </b>
            </div>
            <div>
              <span>镜头 / R2</span>
              <b>
                {job?.shot_count || 1} 个镜头 /{' '}
                {selectedAssets.length} 个素材
              </b>
            </div>
            <div>
              <span>字幕</span>
              <b>
                {subtitleEnabled
                  ? job?.subtitled_video_url
                    ? '已烧录'
                    : job?.stage === 'subtitle_burn'
                      ? '烧录中'
                      : selectedSubtitleStyle?.name
                  : '未启用'}
              </b>
            </div>
            <div>
              <span>画面净度</span>
              <b className={visualIntegrity?.passed === true ? 'aiw-textSuccess' : visualIntegrity?.passed === false ? 'aiw-textDanger' : ''}>
                {visualIntegrity?.passed === true
                  ? '通过：无素材字幕/水印/长重复'
                  : visualIntegrity?.passed === false
                    ? '未通过：已阻止发布'
                    : '审片时自动检测'}
              </b>
            </div>
            <div>
              <span>发布包装</span>
              <b>
                {coverCount || pageCount
                  ? `${coverCount} 套封面 / ${pageCount} 页图文`
                  : '审片通过后自动生成'}
              </b>
            </div>
            <div>
              <span>封面入片</span>
              <b>
                {coverVideoReady
                  ? '已合成到最终视频'
                  : '选择主封面后执行'}
              </b>
            </div>
            <div>
              <span>OpenClaw</span>
              <b>当前 {leadCount} 条 / 历史 {historicalLeads.length} 条</b>
            </div>
          </div>
        </section>

        <aside className="aiw-stepCard aiw-stepFourPublishCard">
          <div className="aiw-sectionTitleRow">
            <div>
              <h3>审片与发布交付</h3>
              <span>
                审片通过后完成封面、图文、封面入片和总包
              </span>
            </div>
            <span
              className={
                workflowAction === 'ready_to_publish'
                  ? 'aiw-statusBadge success'
                  : 'aiw-statusBadge'
              }
            >
              {workflowActionText(workflowAction)}
            </span>
          </div>

          {!jobId && (
            <div className="aiw-pipelineHint">
              <div>
                <b>1</b>
                <span>生成成片</span>
              </div>
              <div>
                <b>2</b>
                <span>自动审片</span>
              </div>
              <div>
                <b>3</b>
                <span>封面与图文</span>
              </div>
              <div>
                <b>4</b>
                <span>封面入片与总包</span>
              </div>
            </div>
          )}

          {jobId && videoUrl && (
            <>
              {workflowError && (
                <div className="aiw-error">
                  {workflowError}
                </div>
              )}
              {workflowReview?.summary && (
                <div className="aiw-info">
                  {workflowReview.summary}
                </div>
              )}
              {visualIntegrity?.passed === false && (
                <div className="aiw-error aiw-visualAuditFailure">
                  <b>画面完整性审计未通过，不能人工覆盖：</b>
                  <ul>{asArray(visualIntegrity?.reasons).map((reason: any, index: number) => <li key={`${reason}-${index}`}>{String(reason)}</li>)}</ul>
                  <span>请返回镜头和素材，替换带字幕、水印、头像或重复画面后重新生成。</span>
                </div>
              )}

              <div className="aiw-actions vertical aiw-workflowActions">
                {workflowAction === 'run_review' && (
                  <button
                    className="aiw-primary"
                    type="button"
                    disabled={Boolean(workflowBusy)}
                    onClick={() =>
                      void runWorkflowAction(
                        '启动自动审片',
                        `/api/video/workflow/${encodeURIComponent(
                          jobId,
                        )}/run-review`,
                        {
                          source:
                            'old_ui_v10_40_4_manual_review',
                        },
                        360000,
                      )
                    }
                  >
                    {workflowBusy ||
                      '启动机械质检 + 豆包审片'}
                  </button>
                )}

                {workflowAction === 'human_review' && (
                  <>
                    <button
                      className="aiw-primary"
                      type="button"
                      disabled={Boolean(workflowBusy)}
                      onClick={() =>
                        void runWorkflowAction(
                          '通过并生成发布素材',
                          `/api/video/workflow/${encodeURIComponent(
                            jobId,
                          )}/approve`,
                          {
                            reviewer: 'human_old_ui',
                            title: topic,
                            script_text: script,
                          },
                          420000,
                        )
                      }
                    >
                      {workflowBusy ||
                        '人工通过并生成封面 + 图文'}
                    </button>
                    <button
                      className="aiw-muted"
                      type="button"
                      disabled={Boolean(workflowBusy)}
                      onClick={() =>
                        void runWorkflowAction(
                          '覆盖审片误报',
                          `/api/video/workflow/${encodeURIComponent(
                            jobId,
                          )}/human-override`,
                          {
                            reviewer: 'human_old_ui',
                            decision: 'approved',
                            status: 'approved',
                            note:
                              '人工完整观看后确认自动审片提示为误报',
                            reason:
                              '人工完整观看后确认自动审片提示为误报',
                          },
                          420000,
                        )
                      }
                    >
                      确认误报并通过
                    </button>
                    <button
                      className="aiw-danger"
                      type="button"
                      disabled={Boolean(workflowBusy)}
                      onClick={() =>
                        void runWorkflowAction(
                          '人工驳回',
                          `/api/video/workflow/${encodeURIComponent(
                            jobId,
                          )}/reject`,
                          {
                            reviewer: 'human_old_ui',
                            reason:
                              '人工驳回，返回文案或镜头修改',
                          },
                          180000,
                        )
                      }
                    >
                      驳回并返回修改
                    </button>
                  </>
                )}

                {workflowAction === 'return_to_edit' && (
                  <>
                    <button
                      className="aiw-muted"
                      type="button"
                      onClick={() => setStep(2)}
                    >
                      返回文案 / 配音修改
                    </button>
                    <button
                      className="aiw-muted"
                      type="button"
                      onClick={() => setStep(3)}
                    >
                      返回镜头 / 素材修改
                    </button>
                    <button
                      className="aiw-primary"
                      type="button"
                      disabled={Boolean(workflowBusy)}
                      onClick={() =>
                        void runWorkflowAction(
                          '重新审片',
                          `/api/video/workflow/${encodeURIComponent(
                            jobId,
                          )}/run-review`,
                          {
                            force: true,
                            source:
                              'old_ui_retry_after_fix',
                          },
                          360000,
                        )
                      }
                    >
                      {workflowBusy || '修复后重新审片'}
                    </button>
                  </>
                )}

                {workflowAction === 'backfill_packaging' && (
                  <button
                    className="aiw-primary"
                    type="button"
                    disabled={Boolean(workflowBusy)}
                    onClick={() =>
                      void runWorkflowAction(
                        '补齐发布包装',
                        `/api/video/workflow/${encodeURIComponent(
                          jobId,
                        )}/backfill-packaging`,
                        {
                          title: topic,
                          script_text: script,
                        },
                        420000,
                      )
                    }
                  >
                    {workflowBusy ||
                      '生成 3 套封面 + 7 页图文'}
                  </button>
                )}
              </div>

              {workflowAction === 'select_cover' &&
                workflowCoverImages.length > 0 && (
                  <div className="aiw-coverSection">
                    <div className="aiw-subsectionTitle">
                      <b>选择主封面</b>
                      <span>
                        选中的封面将作为最终视频开场
                      </span>
                    </div>
                    <div className="aiw-coverChoiceGrid">
                      {workflowCoverImages
                        .slice(0, 3)
                        .map(
                          (
                            item: any,
                            index: number,
                          ) => (
                            <button
                              className={
                                selectedCoverIndex === index
                                  ? 'aiw-coverChoice selected'
                                  : 'aiw-coverChoice'
                              }
                              type="button"
                              key={item?.url || index}
                              disabled={Boolean(
                                workflowBusy,
                              )}
                              onClick={() =>
                                void runWorkflowAction(
                                  '选择主封面',
                                  `/api/video/workflow/${encodeURIComponent(
                                    jobId,
                                  )}/select-cover`,
                                  {
                                    index,
                                    url: item?.url,
                                    selected_by:
                                      'human_old_ui',
                                  },
                                  180000,
                                )
                              }
                            >
                              {item?.url && (
                                <img
                                  src={item.url}
                                  alt={`封面 ${index + 1}`}
                                />
                              )}
                              <span>
                                {selectedCoverIndex === index
                                  ? '已选'
                                  : `方案 ${index + 1}`}
                              </span>
                            </button>
                          ),
                        )}
                    </div>
                  </div>
                )}

              {workflowAction ===
                'compose_cover_video' && (
                <div className="aiw-coverComposeCard">
                  {selectedCover?.url && (
                    <img
                      src={selectedCover.url}
                      alt="已选择的主封面"
                    />
                  )}
                  <div>
                    <b>封面合成最终视频</b>
                    <p>
                      将主封面作为 1 秒开场，随后无缝接入当前成片；
                      最终总包同时保留原始视频。
                    </p>
                    <button
                      className="aiw-primary"
                      type="button"
                      disabled={Boolean(workflowBusy)}
                      onClick={() =>
                        void runWorkflowAction(
                          '封面合成最终视频',
                          `/api/video/workflow/${encodeURIComponent(
                            jobId,
                          )}/compose-cover-video`,
                          {
                            duration_seconds: 1.0,
                          },
                          900000,
                        )
                      }
                    >
                      {workflowBusy ||
                        '封面合成最终视频'}
                    </button>
                  </div>
                </div>
              )}

              {coverVideoReady && (
                <div className="aiw-successPanel">
                  <div>
                    <b>封面最终视频已生成</b>
                    <span>
                      主封面停留{' '}
                      {Number(
                        workflowCoverVideo?.cover_duration_seconds ||
                        1,
                      ).toFixed(1)}
                      秒，原视频同步保留。
                    </span>
                  </div>
                  <a
                    className="aiw-linkButton"
                    href={workflowCoverVideo.url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    预览封面最终视频
                  </a>
                </div>
              )}

              {workflowAction ===
                'build_final_delivery' && (
                <button
                  className="aiw-primary aiw-fullButton"
                  type="button"
                  disabled={Boolean(workflowBusy)}
                  onClick={() =>
                    void runWorkflowAction(
                      '生成最终总包',
                      `/api/video/workflow/${encodeURIComponent(
                        jobId,
                      )}/finalize`,
                      {},
                      420000,
                    )
                  }
                >
                  {workflowBusy || '生成最终发布总包'}
                </button>
              )}

              {workflowAction ===
                'ready_to_publish' && (
                <div className="aiw-successPanel">
                  <div>
                    <b>发布素材已经齐全</b>
                    <span>
                      最终视频已含封面，可直接下载总包发布。
                    </span>
                  </div>
                </div>
              )}

              <div className="aiw-deliveryLinkGrid">
                {workflowDelivery?.final_video_url && (
                  <a
                    className="aiw-linkButton"
                    href={
                      workflowDelivery.final_video_url
                    }
                    target="_blank"
                    rel="noreferrer"
                  >
                    下载封面最终视频
                  </a>
                )}
                {workflowDelivery?.download_zip_url && (
                  <a
                    className="aiw-linkButton"
                    href={
                      workflowDelivery.download_zip_url
                    }
                    target="_blank"
                    rel="noreferrer"
                  >
                    下载最终发布总包
                  </a>
                )}
                {workflowCover?.download_zip_url && (
                  <a
                    className="aiw-linkButton"
                    href={
                      workflowCover.download_zip_url
                    }
                    target="_blank"
                    rel="noreferrer"
                  >
                    下载 3 套封面
                  </a>
                )}
                {workflowXhs?.download_zip_url && (
                  <a
                    className="aiw-linkButton"
                    href={
                      workflowXhs.download_zip_url
                    }
                    target="_blank"
                    rel="noreferrer"
                  >
                    下载 7 页图文
                  </a>
                )}
              </div>

              {(coverCount > 0 || pageCount > 0) && (
                <div className="aiw-packageSummary">
                  <span>
                    <b>{coverCount}</b> 套封面
                  </span>
                  <span>
                    <b>{pageCount}</b> 页图文
                  </span>
                  <span>
                    <b>{coverVideoReady ? 1 : 0}</b>{' '}
                    个封面最终视频
                  </span>
                </div>
              )}
            </>
          )}

          <div className="aiw-finalOutputPanel">
            <div className="aiw-subsectionTitle">
              <b>最终视频产出</b>
              <span>这一部分永久显示，不再等到某个状态才突然出现</span>
            </div>
            <div className="aiw-finalOutputMatrix">
              <div className={videoUrl ? 'done' : ''}><span>原始成片</span><b>{videoUrl ? '已生成' : '待生成'}</b></div>
              <div className={visualIntegrity?.passed === true ? 'done' : visualIntegrity?.passed === false ? 'failed' : ''}><span>画面审计</span><b>{visualIntegrity?.passed === true ? '已通过' : visualIntegrity?.passed === false ? '未通过' : '待审片'}</b></div>
              <div className={workflowSelection?.index !== undefined ? 'done' : ''}><span>主封面</span><b>{workflowSelection?.index !== undefined ? `已选方案 ${Number(workflowSelection.index) + 1}` : '待选择'}</b></div>
              <div className={coverVideoReady ? 'done' : ''}><span>封面最终视频</span><b>{coverVideoReady ? '已完成' : '待合成'}</b></div>
              <div className={workflowDelivery?.download_zip_url ? 'done' : ''}><span>最终发布总包</span><b>{workflowDelivery?.download_zip_url ? '已完成' : '待生成'}</b></div>
            </div>
            <div className="aiw-actions aiw-finalOutputActions">
              <button className="aiw-primary" type="button" disabled={!jobId || workflowAction !== 'compose_cover_video' || Boolean(workflowBusy)} onClick={() => void runWorkflowAction('封面合成最终视频', `/api/video/workflow/${encodeURIComponent(jobId)}/compose-cover-video`, { duration_seconds: 1.0 }, 900000)}>
                {coverVideoReady ? '重新合成封面最终视频' : '封面合成最终视频'}
              </button>
              <button className="aiw-purple" type="button" disabled={!jobId || workflowAction !== 'build_final_delivery' || Boolean(workflowBusy)} onClick={() => void runWorkflowAction('生成最终总包', `/api/video/workflow/${encodeURIComponent(jobId)}/finalize`, {}, 420000)}>
                生成最终发布总包
              </button>
              {workflowDelivery?.final_video_url && <a className="aiw-linkButton" href={workflowDelivery.final_video_url} target="_blank" rel="noreferrer">下载最终视频</a>}
              {workflowDelivery?.download_zip_url && <a className="aiw-linkButton" href={workflowDelivery.download_zip_url} target="_blank" rel="noreferrer">下载最终总包</a>}
            </div>
          </div>

          <div className="aiw-quickLinks">
            <button
              className="aiw-purple"
              type="button"
              onClick={openGraphicWindow}
            >
              打开图文窗口
            </button>
            <button
              className="aiw-muted"
              onClick={() =>
                openWorkspaceTab('leads')
              }
            >
              OpenClaw 人工处理
            </button>
            <button
              className="aiw-muted"
              onClick={() =>
                openWorkspaceTab('collect')
              }
            >
              继续采集同行
            </button>
            <button
              className="aiw-muted"
              onClick={() =>
                openWorkspaceTab('assets')
              }
            >
              补充 R2 素材
            </button>
          </div>
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
          <p>不是旧的一页铺满，也不是假页面；这条链路接 V10.13 单场景动态 TTS-first、抖音大字字幕烧录、R2 素材、数字人素材和 OpenClaw。</p>
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
          <button type="button" className="aiw-muted" disabled={step === 1 || !!busy} onClick={() => setStep((Math.max(1, step - 1) as WizardStep))}>上一步</button>
          <button type="button" className="aiw-primary" disabled={!!busy && step === 4} onClick={() => void nextStep()}>{step === 4 ? (busy || '生成成片') : '下一步'}</button>
        </div>
      </footer>
    </section>
  )
}
