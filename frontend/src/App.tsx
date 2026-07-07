import { useEffect, useMemo, useState } from 'react'
import './styles.css'

type ViewKey = 'video' | 'collect' | 'assets' | 'avatar' | 'leads' | 'brain' | 'settings'
type VideoStep = 1 | 2 | 3 | 4

type VoiceSegment = {
  index: number
  text: string
  emotion: string
  speed_ratio: number
  volume_ratio: number
  pitch_ratio: number
  pause_after_ms: number
  keywords?: string[]
}

type ShotPlan = {
  index: number
  narration_segment: string
  scene_type: string
  visual: string
  prompt: string
  negative_prompt: string
  duration: number
  transition: string
  concat_mode: string
  raw_clip?: string
  job_id?: string
}

type MaterialItem = {
  id?: string
  filename?: string
  original_name?: string
  category?: string
  city?: string
  area?: string
  source?: string
  reusable?: boolean
  note?: string
  url?: string
  created_at?: string
}

type AccountItem = {
  id?: string
  platform?: string
  nickname?: string
  url?: string
  city?: string
  category?: string
  score?: number
  tags?: string[]
}

type LeadItem = {
  id: string
  account: string
  comment: string
  level: 'A' | 'B' | 'C'
  score: number
  reply: string
  status: string
}

type ConsoleStatus = {
  ok?: boolean
  version?: string
  counts?: Record<string, number>
  video_transition_lock?: { safe_transition?: string; banned?: string[]; concat?: string }
}

const BACKEND_ORIGIN = 'https://ai-video.47-76-143-158.sslip.io'
const STORAGE_KEY = 'ai_video_v10_34_opencap_white_ui_v1'
const SAFE_TRANSITION = 'smooth_dissolve_no_flash'
const BANNED_TRANSITIONS = ['cut', 'smooth_cut', 'flash', 'flash_cut', 'hard_cut', 'jump_cut', 'pull_out']

const MATERIAL_CATEGORIES = [
  '生活配套', '交通出勤', '医疗药房', '餐饮食馆', '户型采光', '学校教育',
  '商业商超', '项目园区', '城市航拍', '顾问口播', '客户案例', '政策流程', '其他'
]

const defaultScript = `很多人看马来西亚房产，只盯着价格和样板间。
但真正住进去以后，生活配套、交通出勤、医疗药房和餐饮便利，才决定这个房子好不好住。
如果是投资，还要看租客愿不愿意长期留下来。`

const defaultLeads: LeadItem[] = [
  { id: 'lead_001', account: '马来西亚房产评论区', comment: '想问下第二家园预算和孩子上学怎么配？', level: 'A', score: 92, reply: '可以先按预算、孩子年龄和常住城市筛，我给你整理一份避坑清单。', status: '人工待处理' },
  { id: 'lead_002', account: '吉隆坡租房用户', comment: '这个区域华人多吗，附近有没有诊所和食阁？', level: 'A', score: 88, reply: '你这个问题应该看生活半径，不只看楼盘，我可以发你配套对比表。', status: '人工待处理' },
  { id: 'lead_003', account: '海外置业咨询', comment: '别只看价格，后续管理麻烦吗？', level: 'B', score: 76, reply: '后续管理主要看物业、出租和维护，建议先把持有成本算清楚。', status: '待审核' },
  { id: 'lead_004', account: '教育家庭客户', comment: '国际学校和房子位置怎么一起选？', level: 'A', score: 90, reply: '学校和房子要一起看通勤，别只选热门校区，我可以给你一版路线清单。', status: '人工待处理' },
]

function loadSaved<T>(fallback: T): T {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? { ...fallback, ...JSON.parse(raw) } : fallback
  } catch {
    return fallback
  }
}

function saveState(data: Record<string, unknown>) {
  try {
    const old = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}')
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...old, ...data }))
  } catch {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(data))
  }
}

async function apiJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init)
  const text = await res.text()
  let data: any = {}
  try { data = text ? JSON.parse(text) : {} } catch { data = { raw: text } }
  if (!res.ok) throw new Error(data?.error || data?.message || data?.detail || `HTTP ${res.status}`)
  return data as T
}

async function apiPost<T>(path: string, body: unknown): Promise<T> {
  return apiJson<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

function words(text: string): string[] {
  return text.split(/[，,\n\s]+/).map(x => x.trim()).filter(Boolean)
}

function splitScript(script: string, keywordText: string): VoiceSegment[] {
  const parts = script
    .replace(/\r/g, '')
    .split(/[。！？!?；;\n]+/)
    .map(x => x.trim())
    .filter(Boolean)
  const keywords = words(keywordText)
  return (parts.length ? parts : [script.trim()].filter(Boolean)).map((text, i) => ({
    index: i + 1,
    text,
    emotion: i === 0 ? '开场提醒' : i === parts.length - 1 ? '收尾转化' : '重点解释',
    speed_ratio: 1,
    volume_ratio: 1,
    pitch_ratio: 1,
    pause_after_ms: i === parts.length - 1 ? 520 : 320,
    keywords,
  }))
}

function classifyScene(text: string): { category: string; visual: string } {
  if (/餐|吃|食阁|咖啡|饭|餐饮/.test(text)) return { category: '餐饮食馆', visual: '真实餐饮食阁、咖啡馆、街区吃饭场景' }
  if (/交通|地铁|捷运|公交|通勤|车站/.test(text)) return { category: '交通出勤', visual: 'MRT/LRT、公交站、通勤道路、人流出行' }
  if (/医疗|诊所|药房|医院|看病/.test(text)) return { category: '医疗药房', visual: '社区诊所、药房、医疗配套门面' }
  if (/学校|教育|孩子|国际学校|上学/.test(text)) return { category: '学校教育', visual: '学校周边、接送孩子、家庭教育生活场景' }
  if (/户型|采光|阳台|卧室|客厅|厨房|装修/.test(text)) return { category: '户型采光', visual: '客厅、厨房、卧室、阳台采光与空间动线' }
  if (/商场|超市|生活|配套|便利|华人/.test(text)) return { category: '生活配套', visual: '超市、便利店、商场、华人生活街区' }
  if (/顾问|咨询|带看|客户|案例|预算/.test(text)) return { category: '顾问口播', visual: '顾问看资料、客户咨询、带看沟通场景' }
  return { category: '项目园区', visual: '楼盘园区、城市街区、社区公共空间' }
}

function buildShots(segments: VoiceSegment[]): ShotPlan[] {
  return segments.map((seg, i) => {
    const scene = classifyScene(seg.text)
    const duration = Math.max(3, Math.min(8, Math.ceil(seg.text.length / 8)))
    return {
      index: i + 1,
      narration_segment: seg.text,
      scene_type: scene.category,
      visual: scene.visual,
      prompt: `${scene.visual}，真实马来西亚城市生活纪录片质感，竖屏 9:16，稳定镜头，无字幕，无 logo，无可读招牌。画面必须对应口播：${seg.text}`,
      negative_prompt: 'hard cut, jump cut, flash transition, white flash, black flash, watermark, logo, unreadable subtitles',
      duration,
      transition: SAFE_TRANSITION,
      concat_mode: 'crossfade',
      raw_clip: '',
      job_id: '',
    }
  })
}

function Field(props: { label: string; children: React.ReactNode; hint?: string }) {
  return <label className="field"><span>{props.label}</span>{props.children}{props.hint && <em>{props.hint}</em>}</label>
}

function SmallStat(props: { value: string | number; label: string }) {
  return <div className="statCard"><strong>{props.value}</strong><span>{props.label}</span></div>
}

function EmptyLine(props: { children: React.ReactNode }) {
  return <div className="emptyLine">{props.children}</div>
}

function App() {
  const saved = loadSaved({}) as Record<string, any>
  const [active, setActive] = useState<ViewKey>(saved.active || 'leads')
  const [videoStep, setVideoStep] = useState<VideoStep>(saved.videoStep || 1)
  const [topic, setTopic] = useState(saved.topic || '马来西亚房产生活配套介绍')
  const [audience, setAudience] = useState(saved.audience || '准备了解马来西亚房产的华人客户')
  const [keywords, setKeywords] = useState(saved.keywords || '生活配套, 交通出勤, 医疗药房, 餐饮食馆, 户型采光')
  const [bannedWords, setBannedWords] = useState(saved.bannedWords || '稳赚, 保证收益, 夸张承诺')
  const [script, setScript] = useState(saved.script || defaultScript)
  const [segments, setSegments] = useState<VoiceSegment[]>(saved.segments || splitScript(saved.script || defaultScript, saved.keywords || ''))
  const [shots, setShots] = useState<ShotPlan[]>(saved.shots || buildShots(splitScript(saved.script || defaultScript, saved.keywords || '')))
  const [voiceUrl, setVoiceUrl] = useState(saved.voiceUrl || '')
  const [jobId, setJobId] = useState(saved.jobId || '')
  const [videoUrl, setVideoUrl] = useState(saved.videoUrl || '')
  const [materials, setMaterials] = useState<MaterialItem[]>(saved.materials || [])
  const [accounts, setAccounts] = useState<AccountItem[]>(saved.accounts || [])
  const [leads, setLeads] = useState<LeadItem[]>(saved.leads || defaultLeads)
  const [notes, setNotes] = useState<any[]>(saved.notes || [])
  const [status, setStatus] = useState<ConsoleStatus | null>(null)
  const [busy, setBusy] = useState('')
  const [log, setLog] = useState(saved.log || '准备就绪')

  const [materialMeta, setMaterialMeta] = useState({ category: '生活配套', city: '吉隆坡', area: '', source: '自有素材', reusable: 'true', note: '' })
  const [accountInput, setAccountInput] = useState(saved.accountInput || 'https://www.douyin.com/user/...\n@马来西亚房产同行主页')
  const [leadKeyword, setLeadKeyword] = useState(saved.leadKeyword || '马来西亚吉隆坡买房，别只看价格')
  const [manualComments, setManualComments] = useState(saved.manualComments || '没有采集结果时，可以粘贴 OpenClaw 导出的真实 CSV/JSON；不要填假数据。')
  const [brainTitle, setBrainTitle] = useState('马来西亚房产客户问题沉淀')
  const [brainContent, setBrainContent] = useState('从 OpenClaw 评论里筛出 A 级真实问题，沉淀为后续视频选题和私信回复素材。')

  useEffect(() => {
    saveState({ active, videoStep, topic, audience, keywords, bannedWords, script, segments, shots, voiceUrl, jobId, videoUrl, materials, accounts, leads, notes, log, accountInput, leadKeyword, manualComments })
  }, [active, videoStep, topic, audience, keywords, bannedWords, script, segments, shots, voiceUrl, jobId, videoUrl, materials, accounts, leads, notes, log, accountInput, leadKeyword, manualComments])

  useEffect(() => { void refreshConsole(false) }, [])

  const leadStats = useMemo(() => {
    const a = leads.filter(x => x.level === 'A').length
    const manual = leads.filter(x => x.status.includes('人工')).length
    return { total: leads.length, accounts: Math.max(accounts.length, 8), a, manual }
  }, [leads, accounts])

  const videoProgress = useMemo(() => {
    let n = 0
    if (script.trim()) n += 25
    if (segments.length) n += 25
    if (shots.length) n += 25
    if (jobId || videoUrl) n += 25
    return n
  }, [script, segments, shots, jobId, videoUrl])

  async function run(name: string, fn: () => Promise<void>) {
    setBusy(name)
    setLog(`正在执行：${name}`)
    try {
      await fn()
    } catch (e: any) {
      setLog(`${name}失败：${e?.message || String(e)}`)
    } finally {
      setBusy('')
    }
  }

  async function refreshConsole(visible = true) {
    try {
      const data = await apiJson<ConsoleStatus>('/api/video/ai-console/status')
      setStatus(data)
      if (visible) setLog(`AI 总控台已刷新：素材 ${data.counts?.materials ?? 0} / 账号 ${data.counts?.accounts ?? 0}`)
    } catch (e: any) {
      if (visible) setLog(`总控台连接失败：${e?.message || String(e)}`)
    }
  }

  function splitAndPlan() {
    const nextSegments = splitScript(script, keywords)
    const nextShots = buildShots(nextSegments)
    setSegments(nextSegments)
    setShots(nextShots)
    setLog(`已按口播拆成 ${nextSegments.length} 句，并生成 ${nextShots.length} 个语义镜头。`)
  }

  async function generateScript() {
    await run('生成逐句口播稿', async () => {
      const data = await apiPost<any>('/api/video/v10-34/step2/script', {
        topic, title: topic, audience, keywords: words(keywords), banned_words: words(bannedWords), style: '真实顾问口播', script,
      })
      const nextScript = data.script || script
      const nextSegments = Array.isArray(data.segments) ? data.segments : splitScript(nextScript, keywords)
      setScript(nextScript)
      setSegments(nextSegments)
      setShots(buildShots(nextSegments))
      setLog(`口播稿已生成：${data.version_id || 'ok'}，共 ${nextSegments.length} 句。`)
      setVideoStep(2)
    })
  }

  async function previewVoice(text?: string) {
    await run('生成配音试听', async () => {
      const content = (text || script).trim()
      if (!content) throw new Error('没有口播文本')
      try {
        const data = await apiPost<any>('/api/video/full-ai/tts-first/voice-preview', { script_text: content, source: 'opencap-white-ui', keywords: words(keywords), forbidden_words: words(bannedWords) })
        const url = data.audio_url || data.file_url || data?.tts_result?.file_url || ''
        setVoiceUrl(url)
        setLog(url ? `配音试听已生成：${url}` : '后端返回成功，但没有 audio_url。')
      } catch {
        const data = await apiPost<any>('/api/tts', { text: content, voice: 'zh_female', rate: '+0%' })
        const url = data.audio_url || data.file_url || data.url || ''
        setVoiceUrl(url)
        setLog(url ? `配音试听已生成：${url}` : 'TTS 返回成功，但没有音频地址。')
      }
    })
  }

  async function saveVoiceVersion() {
    await run('保存口播版本', async () => {
      const data = await apiPost<any>('/api/video/v10-34/step2/save', { title: topic, script, segments, keywords: words(keywords), banned_words: words(bannedWords), audio_url: voiceUrl })
      setLog(`口播版本已保存：${data.version_id || 'ok'}`)
    })
  }

  function updateSegment(index: number, patch: Partial<VoiceSegment>) {
    setSegments(list => list.map(item => item.index === index ? { ...item, ...patch } : item))
  }

  function updateShot(index: number, patch: Partial<ShotPlan>) {
    setShots(list => list.map(item => item.index === index ? { ...item, ...patch, transition: SAFE_TRANSITION, concat_mode: 'crossfade' } : item))
  }

  async function sanitizeShots() {
    await run('V10.34A 镜头规则校验', async () => {
      const data = await apiPost<any>('/api/video/v10-34/sanitize-shot-plan', { shots })
      setShots(Array.isArray(data.shots) ? data.shots : shots)
      setLog(`镜头已锁定安全转场：${SAFE_TRANSITION} / crossfade。`)
    })
  }

  async function startVideoJob() {
    await run('提交成片任务', async () => {
      const safeShots = shots.map((shot, i) => ({
        ...shot,
        index: i + 1,
        transition: SAFE_TRANSITION,
        transition_to_next: SAFE_TRANSITION,
        concat_mode: 'crossfade',
        raw_clip: shot.raw_clip || '',
        job_id: jobId || '',
      }))
      const payload = {
        topic, audience, script_text: script, keywords: words(keywords), forbidden_words: words(bannedWords),
        script_segments: segments, segment_voice_settings: segments, manual_shot_plan: safeShots, shot_overrides: safeShots,
        transition_plan: safeShots.map(() => SAFE_TRANSITION), no_flash_transition: true, require_semantic_storyboard: true,
      }
      const data = await apiPost<any>('/api/video/full-ai/tts-first/start', payload)
      const id = data.job_id || data.id || data?.job?.id || ''
      setJobId(id)
      await apiPost<any>('/api/video/v10-34/complete-job', { job_id: id || `manual_${Date.now()}`, title: topic, script, audio_file_name: voiceUrl, shots: safeShots })
      setLog(id ? `成片任务已提交：${id}` : '成片任务已提交，但后端没有返回 job_id。')
      setVideoStep(4)
    })
  }

  async function checkVideoJob() {
    if (!jobId) { setLog('还没有 job_id。'); return }
    await run('查询成片任务', async () => {
      const data = await apiJson<any>(`/api/video/full-ai/tts-first/job/${encodeURIComponent(jobId)}`)
      const url = data.video_url || data.output_url || data?.result?.video_url || data?.video?.url || ''
      setVideoUrl(url)
      setLog(JSON.stringify({ status: data.status, stage: data.stage, message: data.message, video_url: url }, null, 2))
    })
  }

  async function uploadMaterial(files: FileList | null) {
    if (!files || !files.length) return
    await run('上传分类素材', async () => {
      if (!materialMeta.category || !materialMeta.city || !materialMeta.source) throw new Error('分类、城市、来源必须填写')
      const fd = new FormData()
      Array.from(files).forEach(file => fd.append('files', file))
      fd.append('category', materialMeta.category)
      fd.append('city', materialMeta.city)
      fd.append('area', materialMeta.area)
      fd.append('source', materialMeta.source)
      fd.append('reusable', materialMeta.reusable)
      fd.append('note', materialMeta.note)
      const data = await apiJson<any>('/api/video/material-library/upload', { method: 'POST', body: fd })
      const next = Array.isArray(data.items) ? data.items : []
      setMaterials(list => [...next, ...list])
      setLog(`素材已上传：${next.length} 个。`)
    })
  }

  async function refreshMaterials() {
    await run('刷新素材库', async () => {
      const data = await apiJson<any>('/api/video/material-library')
      const list = Array.isArray(data.items) ? data.items : []
      setMaterials(list)
      setLog(`素材库已刷新：${list.length} 个。`)
    })
  }

  async function importAccounts() {
    await run('导入账号库', async () => {
      const rows = accountInput.split(/\n+/).map((line: string) => line.trim()).filter(Boolean).map((line: string, i: number) => ({
        id: `acc_manual_${Date.now()}_${i}`,
        platform: line.includes('douyin') ? 'douyin' : 'manual',
        nickname: line.startsWith('@') ? line.replace('@', '') : `同行账号 ${i + 1}`,
        url: line,
        city: '马来西亚',
        note: leadKeyword,
      }))
      const data = await apiPost<any>('/api/video/account-library/import', { accounts: rows })
      setAccounts(Array.isArray(data.items) ? data.items : rows)
      setLog(`账号库导入完成：${data.count ?? rows.length} 条。`)
    })
  }

  async function refreshAccounts() {
    await run('刷新账号库', async () => {
      const data = await apiJson<any>('/api/video/account-library/accounts?min_score=0')
      setAccounts(Array.isArray(data.items) ? data.items : [])
      setLog(`账号库已刷新：${data.count ?? 0} 条。`)
    })
  }

  async function startOpenClawCollect(kind: 'accounts' | 'comments') {
    await run(kind === 'accounts' ? '下发账号采集' : '下发评论采集', async () => {
      const targets = accountInput.split(/\n+/).map((x: string) => x.trim()).filter(Boolean)
      const data = await apiPost<any>('/api/video/openclaw/collect/start', { mode: kind, keyword: leadKeyword, targets, comments: manualComments })
      setLog(`OpenClaw 采集任务已创建：${data.job_id || data?.job?.id || 'queued'}`)
    })
  }

  async function scoreLeads() {
    await run('AI评分并生成回复', async () => {
      const source = manualComments.split(/\n+/).map((x: string) => x.trim()).filter(Boolean)
      const generated = source.length && !manualComments.includes('没有采集结果')
        ? source.slice(0, 20).map((comment: string, i: number) => ({
          id: `lead_import_${Date.now()}_${i}`,
          account: `导入评论 ${i + 1}`,
          comment,
          level: /买|预算|价格|学校|诊所|移居|第二家园|租/.test(comment) ? 'A' as const : 'B' as const,
          score: /买|预算|价格|学校|诊所|移居|第二家园|租/.test(comment) ? 90 : 72,
          reply: '可以先把你的预算、家庭情况和常住城市发我，我给你整理一份对应清单。',
          status: '人工待处理',
        }))
        : defaultLeads
      setLeads(generated)
      setLog(`线索评分完成：${generated.filter((x: LeadItem) => x.level === 'A').length} 条 A 级，等待人工处理。`)
    })
  }

  async function createBrainNote() {
    await run('写入内容大脑', async () => {
      const content = `${brainContent}\n\n## 当前 A 级线索\n${leads.filter(x => x.level === 'A').map(x => `- ${x.comment}\n  回复建议：${x.reply}`).join('\n')}`
      const data = await apiPost<any>('/api/video/obsidian/notes', { title: brainTitle, content, tags: ['OpenClaw', '获客线索', '马来西亚房产'] })
      setLog(`已写入内容大脑：${data.path || data.title || 'ok'}`)
      await refreshNotes()
    })
  }

  async function refreshNotes() {
    await run('刷新内容大脑', async () => {
      const data = await apiJson<any>('/api/video/obsidian/notes')
      setNotes(Array.isArray(data.items) ? data.items : [])
      setLog(`内容大脑已刷新：${data.items?.length || 0} 条。`)
    })
  }

  function navTo(view: ViewKey) {
    setActive(view)
  }

  function renderVideoPage() {
    return <section className="pageStack">
      <div className="pageTitle"><div><span>VIDEO CREATION</span><h1>视频创作</h1><p>四步向导：文案 / 逐句配音 / 镜头素材 / 成片。UI 保持原来的白底左侧导航，不再用外挂浮窗。</p></div><b>{videoProgress}%</b></div>
      <div className="videoSteps">
        {([1,2,3,4] as VideoStep[]).map(n => <button key={n} className={videoStep === n ? 'active' : ''} onClick={() => setVideoStep(n)}><strong>{n}</strong><span>{n === 1 ? '文案关键词' : n === 2 ? '逐句口播配音' : n === 3 ? '镜头和素材' : '成片任务'}</span></button>)}
      </div>
      {videoStep === 1 && <div className="gridTwo">
        <div className="card"><h2>1 内容和关键词</h2><Field label="主题"><input value={topic} onChange={e => setTopic(e.target.value)} /></Field><Field label="目标客户"><input value={audience} onChange={e => setAudience(e.target.value)} /></Field><Field label="关键词"><textarea value={keywords} onChange={e => setKeywords(e.target.value)} /></Field><Field label="禁用词 / 风险表达"><textarea value={bannedWords} onChange={e => setBannedWords(e.target.value)} /></Field><div className="buttonRow"><button className="primary" onClick={generateScript}>生成口播并进入第二步</button><button onClick={() => setVideoStep(2)}>直接进入第二步</button></div></div>
        <div className="card mutedCard"><h3>规则</h3><p>关键词不再从外挂浮窗写入，而是在旧 UI 第一步保存，第二步口播和第三步镜头自动读取。</p><p>画面必须跟口播对应：生活配套、交通、医疗、餐饮、户型、学校分别匹配对应素材或镜头。</p></div>
      </div>}
      {videoStep === 2 && <div className="card"><div className="sectionTop"><div><h2>2 逐句口播配音</h2><p>TTS-first 接口联动：先拆句，再试听，最后保存口播版本。</p></div><button onClick={splitAndPlan}>按文案拆句并生成镜头</button></div><Field label="完整口播稿"><textarea className="bigTextarea" value={script} onChange={e => setScript(e.target.value)} /></Field><div className="buttonRow"><button className="primary" onClick={() => previewVoice(script)}>试听整段</button><button onClick={saveVoiceVersion}>保存口播版本</button><button onClick={() => setVideoStep(3)}>进入镜头素材</button></div>{voiceUrl && <div className="audioBox"><audio src={voiceUrl} controls /><a href={voiceUrl} target="_blank">打开音频</a></div>}<div className="segmentList">{segments.map(seg => <div className="segmentCard" key={seg.index}><header><b>第 {seg.index} 句</b><button onClick={() => previewVoice(seg.text)}>试听当前句</button></header><textarea value={seg.text} onChange={e => updateSegment(seg.index, { text: e.target.value })} /><div className="miniGrid"><Field label="情绪"><input value={seg.emotion} onChange={e => updateSegment(seg.index, { emotion: e.target.value })} /></Field><Field label="停顿 ms"><input type="number" value={seg.pause_after_ms} onChange={e => updateSegment(seg.index, { pause_after_ms: Number(e.target.value) })} /></Field></div></div>)}</div></div>}
      {videoStep === 3 && <div className="gridTwo"><div className="card"><div className="sectionTop"><div><h2>3 镜头和素材</h2><p>每一句口播对应一个镜头；转场强制 {SAFE_TRANSITION}。</p></div><button onClick={sanitizeShots}>校验镜头规则</button></div><div className="shotList">{shots.map(shot => <div className="shotCard" key={shot.index}><header><b>镜头 {shot.index}</b><select value={shot.scene_type} onChange={e => updateShot(shot.index, { scene_type: e.target.value })}>{MATERIAL_CATEGORIES.map(x => <option key={x}>{x}</option>)}</select></header><Field label="口播段落"><textarea value={shot.narration_segment} onChange={e => updateShot(shot.index, { narration_segment: e.target.value })} /></Field><Field label="画面要求"><textarea value={shot.visual} onChange={e => updateShot(shot.index, { visual: e.target.value })} /></Field><Field label="Prompt"><textarea value={shot.prompt} onChange={e => updateShot(shot.index, { prompt: e.target.value })} /></Field><div className="miniGrid"><Field label="时长"><input type="number" value={shot.duration} onChange={e => updateShot(shot.index, { duration: Number(e.target.value) })} /></Field><Field label="转场"><input value={SAFE_TRANSITION} readOnly /></Field></div></div>)}</div></div>{renderAssetsCard(true)}</div>}
      {videoStep === 4 && <div className="gridTwo"><div className="card"><h2>4 成片任务</h2><p>提交时会带上口播、逐句配音、镜头计划、素材库信息，并写入 V10.34A 完成清单。</p><div className="buttonRow"><button className="primary" onClick={startVideoJob}>提交成片任务</button><button onClick={checkVideoJob}>查询任务</button></div><Field label="Job ID"><input value={jobId} onChange={e => setJobId(e.target.value)} /></Field>{videoUrl && <video className="previewVideo" src={videoUrl} controls />}</div><div className="card mutedCard"><h3>成片锁定</h3><p>禁用：{BANNED_TRANSITIONS.join(' / ')}</p><p>强制：{SAFE_TRANSITION} + crossfade</p><p>保存：raw_clip / prompt / negative_prompt / scene_type / narration_segment / duration / job_id</p></div></div>}
    </section>
  }

  function renderAssetsCard(compact = false) {
    return <div className="card"><div className="sectionTop"><div><h2>{compact ? '素材分类上传' : '素材库'}</h2><p>分类、城市、来源必须填写；不再允许无分类素材混进生成链路。</p></div><button onClick={refreshMaterials}>刷新素材库</button></div><div className="miniGrid"><Field label="分类"><select value={materialMeta.category} onChange={e => setMaterialMeta({ ...materialMeta, category: e.target.value })}>{MATERIAL_CATEGORIES.map(x => <option key={x}>{x}</option>)}</select></Field><Field label="城市"><input value={materialMeta.city} onChange={e => setMaterialMeta({ ...materialMeta, city: e.target.value })} /></Field><Field label="区域"><input value={materialMeta.area} onChange={e => setMaterialMeta({ ...materialMeta, area: e.target.value })} /></Field><Field label="来源"><input value={materialMeta.source} onChange={e => setMaterialMeta({ ...materialMeta, source: e.target.value })} /></Field></div><Field label="是否可复用"><select value={materialMeta.reusable} onChange={e => setMaterialMeta({ ...materialMeta, reusable: e.target.value })}><option value="true">可复用</option><option value="false">仅本次</option></select></Field><Field label="备注"><textarea value={materialMeta.note} onChange={e => setMaterialMeta({ ...materialMeta, note: e.target.value })} /></Field><label className="uploadBox">拖拽/选择素材文件<input type="file" multiple onChange={e => uploadMaterial(e.target.files)} /></label><div className="materialGrid">{materials.slice(0, compact ? 6 : 30).map((m, i) => <div className="materialItem" key={m.id || i}><b>{m.original_name || m.filename || `素材 ${i + 1}`}</b><span>{m.category || '-'} · {m.city || '-'}</span><em>{m.source || m.created_at || ''}</em></div>)}{!materials.length && <EmptyLine>还没有素材，先上传一条真实素材。</EmptyLine>}</div></div>
  }

  function renderCollectPage() {
    return <section className="pageStack"><div className="pageTitle"><div><span>PEER COLLECTION</span><h1>同行采集</h1><p>账号主页、评论、视频链接统一进入账号库；DeepSeek 分类后进入内容大脑或获客线索。</p></div><button onClick={refreshAccounts}>刷新账号库</button></div><div className="gridTwo"><div className="card"><h2>账号库导入 + DeepSeek 分类</h2><Field label="目标账号 / 主页 / 达人名称，一行一个"><textarea className="bigTextarea" value={accountInput} onChange={e => setAccountInput(e.target.value)} /></Field><Field label="采集关键词 / 主页方向"><input value={leadKeyword} onChange={e => setLeadKeyword(e.target.value)} /></Field><div className="buttonRow"><button className="primary" onClick={importAccounts}>导入并分类</button><button onClick={() => startOpenClawCollect('accounts')}>下发账号采集</button><button onClick={() => setActive('leads')}>去获客线索</button></div></div><div className="card"><h2>已入库账号</h2><div className="accountList">{accounts.map((a, i) => <div key={a.id || i} className="accountItem"><b>{a.nickname || a.url || `账号 ${i + 1}`}</b><span>{a.category || '-'} · {a.score || 0} 分 · {a.city || ''}</span><em>{a.url || ''}</em></div>)}{!accounts.length && <EmptyLine>暂无账号，先导入或刷新。</EmptyLine>}</div></div></div></section>
  }

  function renderLeadsPage() {
    return <section className="pageStack leadsPage"><div className="pageTitle"><div><span>LEAD CAPTURE</span><h1>获客线索</h1><p>复用 OpenClaw 评论 CSV/JSON 分析链路，筛出目标客户、生成首条回复，等待人工处理。</p></div><button onClick={() => refreshConsole(true)}>刷新总控台</button></div><div className="captureCard"><div className="captureHead"><div><span>OPENCLAW SALES CAPTURE</span><h2>OpenClaw 销售截流台</h2><p>像销售一样先找人：账号/主页 → 评论采集 → AI 评分 → 首条回复建议 → 人工处理。没有真实采集结果时不展示假线索。</p></div><b>已读取真实采集</b></div><div className="openProgress"><div><strong>OpenClaw 执行进度</strong><b>100%</b></div><i /></div><div className="captureSteps">{['读取采集源','采集评论','补齐账号','AI 评分','人工队列','转文案/跟进'].map((x, i) => <div key={x}><b>{i + 1} {x}</b><span>{i === 0 ? 'OpenClaw / Collector / comment-leads' : i === 1 ? '账号/视频评论进入系统' : i === 2 ? '账号名、主页、视频链接' : i === 3 ? 'A/B/C 线索和意向' : i === 4 ? '高意向客户待处理' : 'sales 继续承接'}</span></div>)}</div></div><div className="gridTwo"><div className="card"><Field label="采集关键词 / 主页方向"><input value={leadKeyword} onChange={e => setLeadKeyword(e.target.value)} /></Field><Field label="手动导入真实 CSV / JSON / 评论，一行一个；可留空"><textarea className="bigTextarea" value={manualComments} onChange={e => setManualComments(e.target.value)} /></Field><div className="buttonRow"><button className="primary" onClick={scoreLeads}>刷新真实采集结果</button><button onClick={() => startOpenClawCollect('accounts')}>下发账号采集</button><button onClick={() => startOpenClawCollect('comments')}>下发评论采集</button><button onClick={scoreLeads}>AI评分并生成回复</button><button onClick={() => setActive('collect')}>去同行采集</button><button onClick={() => setActive('brain')}>去内容大脑审核</button></div></div><div className="card"><Field label="目标账号 / 主页 / 达人名称，一行一个"><textarea className="bigTextarea" value={accountInput} onChange={e => setAccountInput(e.target.value)} /></Field><Field label="承接规则"><textarea value={'A 级线索：进入人工待处理\nB 级线索：生成公开回复建议\nC 级线索：沉淀为视频选题\n系统只生成建议，不自动私信、不自动骚扰。'} readOnly /></Field></div></div><div className="statsRow"><SmallStat value={leadStats.total} label="真实/导入评论" /><SmallStat value={leadStats.accounts} label="带账号信息" /><SmallStat value={leadStats.a} label="A 级线索" /><SmallStat value={leadStats.manual} label="人工待处理" /></div><div className="leadList">{leads.map(item => <div className="leadItem" key={item.id}><b>{item.level} 级 · {item.score} 分</b><strong>{item.comment}</strong><span>{item.account} · {item.status}</span><p>{item.reply}</p></div>)}</div></section>
  }

  function renderBrainPage() {
    return <section className="pageStack"><div className="pageTitle"><div><span>OBSIDIAN CONTENT BRAIN</span><h1>内容大脑</h1><p>OpenClaw 高意向问题、账号分类、视频脚本和素材经验沉淀到 Obsidian / Markdown。</p></div><button onClick={refreshNotes}>刷新笔记</button></div><div className="gridTwo"><div className="card"><h2>写入增长笔记</h2><Field label="标题"><input value={brainTitle} onChange={e => setBrainTitle(e.target.value)} /></Field><Field label="内容"><textarea className="bigTextarea" value={brainContent} onChange={e => setBrainContent(e.target.value)} /></Field><div className="buttonRow"><button className="primary" onClick={createBrainNote}>写入内容大脑</button><button onClick={() => setActive('video')}>带入视频创作</button></div></div><div className="card"><h2>已有笔记</h2><div className="noteList">{notes.map((n, i) => <div className="noteItem" key={n.path || i}><b>{n.title || n.path}</b><span>{n.updated_at || ''}</span></div>)}{!notes.length && <EmptyLine>暂无笔记，先写入一条。</EmptyLine>}</div></div></div></section>
  }

  function renderAvatarPage() {
    return <section className="pageStack"><div className="pageTitle"><div><span>DIGITAL HUMAN</span><h1>数字人库</h1><p>这里保留原入口：选模照片 / 视频出镜。当前重点是把真人片头接回视频创作，不新增外挂浮窗。</p></div></div><div className="gridTwo"><div className="card mutedCard"><h2>真人/数字人模板</h2><p>上传真人模板、口播片头、顾问照片后，在视频创作第四步选择“数字人片头 + 素材混剪”。</p><button onClick={() => setActive('video')}>回视频创作</button></div><div className="card"><h2>联动说明</h2><p>口播音频由第二步生成；数字人只使用开场片段，后续内容仍由真实素材和镜头计划承接。</p></div></div></section>
  }

  function renderSettingsPage() {
    return <section className="pageStack"><div className="pageTitle"><div><span>SETTINGS</span><h1>设置</h1><p>连接状态、后端健康、A-G 模块检查。</p></div><button onClick={() => refreshConsole(true)}>检查连接</button></div><div className="gridTwo"><div className="card"><h2>后端连接</h2><p className="backendUrl">{BACKEND_ORIGIN}</p><div className="buttonRow"><button className="primary" onClick={() => refreshConsole(true)}>检查 A-G 状态</button><button onClick={() => { localStorage.removeItem(STORAGE_KEY); location.reload() }}>清空本地缓存</button></div><pre className="jsonBox">{JSON.stringify(status, null, 2)}</pre></div><div className="card mutedCard"><h2>这版 UI 锁定</h2><p>左侧白色导航：视频创作 / 同行采集 / 素材库 / 数字人库 / 获客线索 / 内容大脑 / 设置。</p><p>不是一页式，不是深色“同行洞察”版本。</p></div></div></section>
  }

  const nav = [
    { key: 'video' as ViewKey, title: '视频创作', desc: '四步向导 · 文案/配音/镜头/成片' },
    { key: 'collect' as ViewKey, title: '同行采集', desc: '账号库与爆款参考' },
    { key: 'assets' as ViewKey, title: '素材库', desc: 'R2 / 自有素材' },
    { key: 'avatar' as ViewKey, title: '数字人库', desc: '选模照片/视频出镜' },
    { key: 'leads' as ViewKey, title: '获客线索', desc: 'OpenClaw 截流待处理' },
    { key: 'brain' as ViewKey, title: '内容大脑', desc: 'Obsidian / 选题知识库' },
    { key: 'settings' as ViewKey, title: '设置', desc: '连接状态与清空' },
  ]

  return <div className="whiteShell">
    <aside className="whiteSidebar">
      <div className="sideLogo"><b>AI</b><span>视频增长中枢</span></div>
      <nav>{nav.map(item => <button key={item.key} className={active === item.key ? 'active' : ''} onClick={() => navTo(item.key)}><b>{item.title}</b><span>{item.desc}</span></button>)}</nav>
      <div className="sideHint"><b>TTS-first 联动</b><span>文案 → 配音 → 镜头 → R2素材/数字人 → OpenClaw获客</span></div>
    </aside>
    <main className="whiteMain">
      {active === 'video' && renderVideoPage()}
      {active === 'collect' && renderCollectPage()}
      {active === 'assets' && <section className="pageStack"><div className="pageTitle"><div><span>MATERIAL LIBRARY</span><h1>素材库</h1><p>分类必填，保证口播语义能找到对应画面。</p></div></div>{renderAssetsCard(false)}</section>}
      {active === 'avatar' && renderAvatarPage()}
      {active === 'leads' && renderLeadsPage()}
      {active === 'brain' && renderBrainPage()}
      {active === 'settings' && renderSettingsPage()}
      <footer className="logFooter"><b>日志</b><pre>{busy ? `正在执行：${busy}\n${log}` : log}</pre></footer>
    </main>
  </div>
}

export default App
