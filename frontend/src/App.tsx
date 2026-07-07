import { useMemo, useState } from 'react'

type VoiceSegment = {
  text: string
  emotion: string
  speed_ratio: number
  volume_ratio: number
  pitch_ratio: number
  pause_after_ms: number
  emphasis: string
}

type Shot = {
  narration: string
  visual: string
  category: string
  duration: number
  motion: string
  transition: string
  prompt: string
}

type MaterialItem = {
  asset_id?: string
  id?: string
  original_name?: string
  filename?: string
  kind?: string
  category?: string
  url?: string
  file_url?: string
  created_at?: string
}

type StepKey = 1 | 2 | 3 | 4

const API_BASE = ''
const BACKEND_PUBLIC = 'https://ai-video.47-76-143-158.sslip.io'
const STORAGE_KEY = 'ai_video_old_ui_fixed_native_v1'

const DEFAULT_SEGMENTS: VoiceSegment[] = [
  { text: '先把口播稿粘到这里，系统会按句子拆分配音。', emotion: '自然可信', speed_ratio: 1, volume_ratio: 1, pitch_ratio: 1, pause_after_ms: 450, emphasis: '' },
]

const CATEGORIES = [
  '房产/楼盘素材', '生活配套', '交通出勤', '医疗/诊所/药房', '餐饮/食阁', '教育/学校',
  '户型/室内', '人物口播/数字人模板', '成交/带看/租客', '短视频教学/钩子', '报告/资料/截图'
]

const KIND_OPTIONS = [
  ['video', '视频素材'], ['image', '图片素材'], ['audio', '音频'], ['document', '资料/文档'], ['script', '脚本'], ['avatar_template', '真人/数字人模板'], ['raw_fal_clip', 'FAL 原片']
]

const emotions = ['自然可信', '朋友聊天', '专业冷静', '提醒警示', '紧张急迫', '坚定有力', '收尾号召']

function safeJson<T>(raw: string | null, fallback: T): T {
  try { return raw ? JSON.parse(raw) as T : fallback } catch { return fallback }
}

async function apiJson<T>(path: string, body?: unknown, method = 'POST'): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: body instanceof FormData ? undefined : { 'Content-Type': 'application/json' },
    body: body instanceof FormData ? body : body === undefined ? undefined : JSON.stringify(body),
  })
  const text = await res.text()
  let data: any
  try { data = text ? JSON.parse(text) : {} } catch { data = { raw: text } }
  if (!res.ok) throw new Error(data?.message || data?.error || data?.detail || `HTTP ${res.status}`)
  return data as T
}

function splitScript(script: string): VoiceSegment[] {
  const parts = script
    .replace(/\r/g, '')
    .split(/[。！？!?\n]+/)
    .map(s => s.trim())
    .filter(Boolean)
  return (parts.length ? parts : [script.trim()].filter(Boolean)).map(text => ({
    text,
    emotion: '自然可信',
    speed_ratio: 1,
    volume_ratio: 1,
    pitch_ratio: 1,
    pause_after_ms: 450,
    emphasis: '',
  }))
}

function buildShotsFromSegments(segments: VoiceSegment[]): Shot[] {
  const classify = (text: string) => {
    if (/餐|吃|食阁|咖啡|饭|餐饮|外卖/.test(text)) return ['餐饮/食阁', '餐厅、咖啡馆、食阁、外卖店和真实就餐环境']
    if (/交通|地铁|捷运|公交|通勤|主干道|车站/.test(text)) return ['交通出勤', 'MRT/LRT、公交站、主干道、通勤人流']
    if (/医疗|诊所|药房|看病|买药|医院/.test(text)) return ['医疗/诊所/药房', '社区诊所、药房、医疗配套入口']
    if (/学校|教育|国际学校|孩子|上学/.test(text)) return ['教育/学校', '学校周边、校车、家庭教育生活场景']
    if (/户型|采光|阳台|卧室|客厅|厨房|装修|空间/.test(text)) return ['户型/室内', '客厅、厨房、卧室、阳台、采光、空间动线']
    if (/投资|出租|租客|转售|回报|持有/.test(text)) return ['成交/带看/租客', '租客看房、成交咨询、社区人流、楼盘外立面']
    if (/超市|商场|生活|配套|便利|华人/.test(text)) return ['生活配套', '超市、便利店、商场、街区生活、药房餐饮']
    return ['房产/楼盘素材', '楼盘外立面、社区环境、真实街区、样板间过渡']
  }
  return segments.map((seg, i) => {
    const [category, visual] = classify(seg.text)
    const duration = Math.max(3, Math.min(8, Math.ceil(seg.text.length / 8)))
    return {
      narration: seg.text,
      visual,
      category,
      duration,
      motion: i % 2 === 0 ? '缓慢推进' : '平稳横移',
      transition: 'smooth dissolve',
      prompt: `${visual}，真实马来西亚城市生活纪录片质感，竖屏9:16，稳定镜头，无文字，无logo，无字幕，无可读招牌。对应口播：${seg.text}`
    }
  })
}

function App() {
  const saved = safeJson<any>(localStorage.getItem(STORAGE_KEY), {})
  const [step, setStep] = useState<StepKey>(saved.step || 1)
  const [topic, setTopic] = useState(saved.topic || '马来西亚房产生活配套介绍')
  const [audience, setAudience] = useState(saved.audience || '准备了解马来西亚房产的华人客户')
  const [keywords, setKeywords] = useState(saved.keywords || '生活配套, 交通出勤, 医疗药房, 餐饮食阁, 户型采光')
  const [forbiddenWords, setForbiddenWords] = useState(saved.forbiddenWords || '稳赚, 保证收益, 夸张承诺')
  const [script, setScript] = useState(saved.script || '很多人看马来西亚房产，只盯着价格。\n但真正住进去以后，生活配套、交通出勤、医疗药房和餐饮便利，才决定这个房子好不好住。\n如果是投资，还要看租客愿不愿意长期留下来。')
  const [segments, setSegments] = useState<VoiceSegment[]>(saved.segments || splitScript(saved.script || ''))
  const [shots, setShots] = useState<Shot[]>(saved.shots || buildShotsFromSegments(saved.segments || DEFAULT_SEGMENTS))
  const [voiceUrl, setVoiceUrl] = useState(saved.voiceUrl || '')
  const [voiceDuration, setVoiceDuration] = useState<number>(saved.voiceDuration || 0)
  const [log, setLog] = useState('准备就绪')
  const [busy, setBusy] = useState('')
  const [materials, setMaterials] = useState<MaterialItem[]>(saved.materials || [])
  const [uploadKind, setUploadKind] = useState('video')
  const [uploadCategory, setUploadCategory] = useState('房产/楼盘素材')
  const [uploadTags, setUploadTags] = useState('')
  const [jobId, setJobId] = useState(saved.jobId || '')
  const [videoUrl, setVideoUrl] = useState(saved.videoUrl || '')

  const totalDuration = useMemo(() => shots.reduce((a, b) => a + Number(b.duration || 0), 0), [shots])

  function persist(next: Record<string, unknown> = {}) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      step, topic, audience, keywords, forbiddenWords, script, segments, shots, voiceUrl, voiceDuration, materials, jobId, videoUrl, ...next
    }))
  }

  function go(next: StepKey) { setStep(next); persist({ step: next }) }

  function resetFromScript() {
    const nextSegments = splitScript(script)
    const nextShots = buildShotsFromSegments(nextSegments)
    setSegments(nextSegments)
    setShots(nextShots)
    setLog(`已按口播拆成 ${nextSegments.length} 句，并生成对应镜头。`)
    persist({ segments: nextSegments, shots: nextShots })
  }

  async function saveScriptVersion() {
    setBusy('保存口播版本')
    try {
      const data = await apiJson<any>('/api/video/full-ai/tts-first/script-version', {
        script_text: script,
        keywords: keywords.split(/[,，\s]+/).filter(Boolean),
        forbidden_words: forbiddenWords.split(/[,，\s]+/).filter(Boolean),
        voice: { segments },
        note: 'old-ui-native-step2'
      })
      setLog(`口播版本已保存：${data.version_id || 'ok'}`)
    } catch (e: any) { setLog(`保存失败：${e.message}`) }
    finally { setBusy('') }
  }

  async function previewVoice(text: string) {
    if (!text.trim()) { setLog('没有口播文本，不能试听。'); return }
    setBusy('生成配音试听')
    try {
      const data = await apiJson<any>('/api/video/full-ai/tts-first/voice-preview', {
        script_text: text,
        pace: 'normal',
        keywords: keywords.split(/[,，\s]+/).filter(Boolean),
        forbidden_words: forbiddenWords.split(/[,，\s]+/).filter(Boolean),
        source: 'github_old_ui_native'
      })
      const url = data.audio_url || data.file_url || data?.tts_result?.file_url || ''
      setVoiceUrl(url)
      setVoiceDuration(Number(data.audio_duration || data.duration_seconds || data?.tts_result?.duration_seconds || 0))
      setLog(url ? `试听已生成：${Number(data.audio_duration || 0).toFixed(2)} 秒` : '后端返回成功，但没有 audio_url')
      persist({ voiceUrl: url, voiceDuration: Number(data.audio_duration || 0) })
    } catch (e: any) { setLog(`试听失败：${e.message}`) }
    finally { setBusy('') }
  }

  async function uploadMaterial(file: File | null) {
    if (!file) return
    if (!uploadKind || !uploadCategory) { setLog('必须选择素材类型和分类。'); return }
    setBusy('上传素材')
    try {
      const fd = new FormData()
      fd.append('file', file)
      fd.append('kind', uploadKind)
      fd.append('category', uploadCategory)
      fd.append('tags', uploadTags)
      fd.append('source', 'github_old_ui_upload')
      const data = await apiJson<any>('/api/video/material-library/upload', fd)
      const item = data.item || data.asset || data
      const next = [item, ...materials]
      setMaterials(next)
      setLog(`素材已上传：${item.original_name || item.filename || file.name}`)
      persist({ materials: next })
    } catch (e: any) { setLog(`素材上传失败：${e.message}`) }
    finally { setBusy('') }
  }

  async function refreshMaterials() {
    setBusy('读取素材库')
    try {
      const data = await apiJson<any>('/api/video/material-library', undefined, 'GET')
      const list = Array.isArray(data.items) ? data.items : Array.isArray(data) ? data : []
      setMaterials(list)
      setLog(`素材库读取成功：${list.length} 个素材`)
      persist({ materials: list })
    } catch (e: any) { setLog(`读取素材库失败：${e.message}`) }
    finally { setBusy('') }
  }

  async function startVideo() {
    setBusy('提交生成任务')
    try {
      const payload = {
        topic,
        audience,
        script_text: script,
        keywords: keywords.split(/[,，\s]+/).filter(Boolean),
        forbidden_words: forbiddenWords.split(/[,，\s]+/).filter(Boolean),
        script_segments: segments.map((s, i) => ({ index: i + 1, text: s.text })),
        segment_voice_settings: segments,
        manual_shot_plan: shots,
        shot_overrides: shots,
        asset_context: materials,
        transition_plan: shots.map(s => s.transition),
        require_semantic_storyboard: true,
        require_subtitles: true,
        no_flash_transition: true,
      }
      const data = await apiJson<any>('/api/video/full-ai/tts-first/start', payload)
      const id = data.job_id || data.id || ''
      setJobId(id)
      setLog(id ? `任务已提交：${id}` : JSON.stringify(data).slice(0, 500))
      persist({ jobId: id })
    } catch (e: any) { setLog(`提交失败：${e.message}`) }
    finally { setBusy('') }
  }

  async function pollJob() {
    if (!jobId) { setLog('没有 job_id。'); return }
    setBusy('查询任务')
    try {
      const data = await apiJson<any>(`/api/video/full-ai/tts-first/job/${encodeURIComponent(jobId)}`, undefined, 'GET')
      const url = data.video_url || data.result?.video_url || data.output_url || ''
      setVideoUrl(url)
      setLog(JSON.stringify({ status: data.status, stage: data.stage, message: data.message, video_url: url }, null, 2))
      persist({ videoUrl: url })
    } catch (e: any) { setLog(`查询失败：${e.message}`) }
    finally { setBusy('') }
  }

  function updateSegment(i: number, patch: Partial<VoiceSegment>) {
    const next = segments.map((s, idx) => idx === i ? { ...s, ...patch } : s)
    setSegments(next)
    persist({ segments: next })
  }

  function updateShot(i: number, patch: Partial<Shot>) {
    const next = shots.map((s, idx) => idx === i ? { ...s, ...patch } : s)
    setShots(next)
    persist({ shots: next })
  }

  return <main className="appShell">
    <section className="hero">
      <div>
        <span className="eyebrow">AI-VIDEO · GitHub 结构版</span>
        <h1>一页式智能视频增长工作台</h1>
        <p>保留原来的四步 UI，把口播、逐句配音、镜头素材和成片任务放回原生页面，不再使用外挂浮窗。</p>
      </div>
      <div className="statusBox">
        <b>后端</b>
        <span>{BACKEND_PUBLIC}</span>
        <button onClick={async () => {
          try { const h = await apiJson<any>('/api/video/full-ai/tts-first/health', undefined, 'GET'); setLog(JSON.stringify(h, null, 2)) }
          catch (e: any) { setLog(`健康检查失败：${e.message}`) }
        }}>检查连接</button>
      </div>
    </section>

    <nav className="stepNav">
      {[1, 2, 3, 4].map(n => <button key={n} className={step === n ? 'active' : ''} onClick={() => go(n as StepKey)}>
        <strong>{n}</strong>
        <span>{n === 1 ? '确定内容和关键词' : n === 2 ? '逐句口播配音' : n === 3 ? '编辑镜头和素材' : '生成成片和承接线索'}</span>
      </button>)}
    </nav>

    {step === 1 && <section className="panel grid2">
      <div className="card">
        <h2>第一步：内容和关键词</h2>
        <label>主题<input value={topic} onChange={e => setTopic(e.target.value)} onBlur={() => persist()} /></label>
        <label>目标客户<input value={audience} onChange={e => setAudience(e.target.value)} onBlur={() => persist()} /></label>
        <label>必须覆盖的关键词<textarea value={keywords} onChange={e => setKeywords(e.target.value)} onBlur={() => persist()} /></label>
        <label>禁用词 / 风险表达<textarea value={forbiddenWords} onChange={e => setForbiddenWords(e.target.value)} onBlur={() => persist()} /></label>
        <button className="primary" onClick={() => go(2)}>进入口播配音</button>
      </div>
      <div className="card softCard">
        <h3>规则</h3>
        <p>关键词只在第二步以后参与口播和镜头，不再用外挂浮窗写入。</p>
        <p>画面必须跟口播语义对应：生活配套、交通、医疗、餐饮、户型、投资分别匹配对应素材或镜头。</p>
      </div>
    </section>}

    {step === 2 && <section className="panel">
      <div className="card">
        <div className="sectionHead"><div><h2>第二步：口播文案</h2><p>改完口播后，先拆句，再试听整段。</p></div><button onClick={resetFromScript}>按文案拆句并生成镜头</button></div>
        <textarea className="scriptEditor" value={script} onChange={e => setScript(e.target.value)} onBlur={() => persist()} />
        <div className="buttonRow">
          <button className="primary" onClick={() => previewVoice(script)} disabled={!!busy}>{busy === '生成配音试听' ? busy : '试听整段口播'}</button>
          <button onClick={saveScriptVersion} disabled={!!busy}>{busy === '保存口播版本' ? busy : '保存口播版本'}</button>
          <button onClick={() => go(3)}>进入镜头素材</button>
        </div>
        {voiceUrl && <div className="mediaBox"><audio controls src={voiceUrl} /><span>时长：{voiceDuration ? voiceDuration.toFixed(2) : '-'} 秒</span></div>}
      </div>
      <div className="segments">
        {segments.map((seg, i) => <article className="segment" key={`${i}-${seg.text.slice(0, 8)}`}>
          <header><b>第 {i + 1} 句</b><button onClick={() => previewVoice(seg.text)}>试听当前句</button></header>
          <textarea value={seg.text} onChange={e => updateSegment(i, { text: e.target.value })} />
          <div className="grid4 compact">
            <label>情绪<select value={seg.emotion} onChange={e => updateSegment(i, { emotion: e.target.value })}>{emotions.map(x => <option key={x}>{x}</option>)}</select></label>
            <label>语速 {seg.speed_ratio.toFixed(2)}x<input type="range" min="0.7" max="1.5" step="0.01" value={seg.speed_ratio} onChange={e => updateSegment(i, { speed_ratio: Number(e.target.value) })} /></label>
            <label>音量 {seg.volume_ratio.toFixed(2)}x<input type="range" min="0.5" max="1.8" step="0.01" value={seg.volume_ratio} onChange={e => updateSegment(i, { volume_ratio: Number(e.target.value) })} /></label>
            <label>句后停顿 {seg.pause_after_ms}ms<input type="range" min="0" max="1800" step="50" value={seg.pause_after_ms} onChange={e => updateSegment(i, { pause_after_ms: Number(e.target.value) })} /></label>
          </div>
          <label>重读词<input value={seg.emphasis} onChange={e => updateSegment(i, { emphasis: e.target.value })} placeholder="费用, 配套, 交通" /></label>
        </article>)}
      </div>
    </section>}

    {step === 3 && <section className="panel grid2">
      <div className="card">
        <div className="sectionHead"><div><h2>第三步：镜头和素材</h2><p>每句口播对应一个镜头，不能随机跑画面。</p></div><button onClick={() => { const next = buildShotsFromSegments(segments); setShots(next); persist({ shots: next }); }}>按口播重建镜头</button></div>
        <div className="shotList">{shots.map((shot, i) => <article className="shot" key={i}>
          <header><b>镜头 {i + 1}</b><select value={shot.category} onChange={e => updateShot(i, { category: e.target.value })}>{CATEGORIES.map(x => <option key={x}>{x}</option>)}</select></header>
          <label>口播<textarea value={shot.narration} onChange={e => updateShot(i, { narration: e.target.value })} /></label>
          <label>画面<textarea value={shot.visual} onChange={e => updateShot(i, { visual: e.target.value })} /></label>
          <div className="grid3 compact"><label>时长<input type="number" min="2" max="12" value={shot.duration} onChange={e => updateShot(i, { duration: Number(e.target.value) })} /></label><label>运镜<input value={shot.motion} onChange={e => updateShot(i, { motion: e.target.value })} /></label><label>转场<input value={shot.transition} onChange={e => updateShot(i, { transition: e.target.value })} /></label></div>
          <label>AI Prompt<textarea value={shot.prompt} onChange={e => updateShot(i, { prompt: e.target.value })} /></label>
        </article>)}</div>
      </div>
      <div className="card">
        <h2>素材上传 / 必选分类</h2>
        <div className="grid2 compact"><label>素材类型<select value={uploadKind} onChange={e => setUploadKind(e.target.value)}>{KIND_OPTIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label><label>分类<select value={uploadCategory} onChange={e => setUploadCategory(e.target.value)}>{CATEGORIES.map(x => <option key={x}>{x}</option>)}</select></label></div>
        <label>标签<input value={uploadTags} onChange={e => setUploadTags(e.target.value)} placeholder="楼盘, 生活, 交通" /></label>
        <label className="dropBox">拖拽或选择文件<input type="file" onChange={e => uploadMaterial(e.target.files?.[0] || null)} /></label>
        <div className="buttonRow"><button onClick={refreshMaterials}>刷新素材库</button><button onClick={() => go(4)}>进入生成</button></div>
        <div className="materialList">{materials.map((m, i) => <div className="material" key={m.asset_id || m.id || i}><b>{m.original_name || m.filename || `素材 ${i + 1}`}</b><span>{m.kind || '-'} · {m.category || '-'}</span></div>)}</div>
      </div>
    </section>}

    {step === 4 && <section className="panel grid2">
      <div className="card">
        <h2>第四步：生成成片</h2>
        <p>总镜头时长约 {totalDuration.toFixed(1)} 秒；生成时会把口播、逐句配音设置、镜头计划、素材分类一起传给后端。</p>
        <div className="buttonRow"><button className="primary" onClick={startVideo} disabled={!!busy}>{busy === '提交生成任务' ? busy : '提交生成任务'}</button><button onClick={pollJob} disabled={!!busy || !jobId}>{busy === '查询任务' ? busy : '查询任务'}</button></div>
        <label>Job ID<input value={jobId} onChange={e => setJobId(e.target.value)} /></label>
        {videoUrl && <div className="videoBox"><video controls src={videoUrl} /><a href={videoUrl} target="_blank">下载视频</a></div>}
      </div>
      <div className="card softCard"><h3>上线检查</h3><p>没有浮窗、没有 raw 原片外挂、没有右下角成片保存外挂。</p><p>/api 通过 frontend/functions/api/[[path]].js 代理到阿里云后端。</p></div>
    </section>}

    <section className="logPanel"><b>日志</b><pre>{log}</pre></section>
  </main>
}

export default App
