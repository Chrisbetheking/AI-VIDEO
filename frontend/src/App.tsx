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
  TTSResponse,
  TTSVoice,
  VideoEditChatResponse,
  VoiceDirectorResponse,
  VoiceSegment,
  apiGet,
  apiPost,
  uploadAssets
} from './api'

type ModuleKey = 'dashboard' | 'strategy' | 'collector' | 'copy' | 'voice' | 'assets' | 'video' | 'subtitleCover' | 'publish'

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
  { key: 'dashboard', icon: '🏠', title: '总览', desc: '项目进度、联动关系、下一步动作', tag: '目录' },
  { key: 'strategy', icon: '🎯', title: '获客定位', desc: '目标客户画像、痛点、投流方向', tag: '获客' },
  { key: 'collector', icon: '🔎', title: '同行采集', desc: '抖音口令/视频/文案采集拆解', tag: '采集' },
  { key: 'copy', icon: '✍️', title: '文案工作台', desc: '黄金三秒、细改、违禁词检查', tag: '文案' },
  { key: 'voice', icon: '🎙️', title: '声音导演', desc: '克隆音色、分段情绪、语速停顿', tag: '配音' },
  { key: 'assets', icon: '🗂️', title: '素材工作台', desc: '素材库、采集视频库、素材匹配', tag: '素材' },
  { key: 'video', icon: '🎬', title: '视频工作台', desc: '分段衔接、转场、AI 插件深度剪辑', tag: '剪辑' },
  { key: 'subtitleCover', icon: '🅰️', title: '字幕封面', desc: '字幕重点字、封面样式、下载', tag: '视觉' },
  { key: 'publish', icon: '🚀', title: '发布投流', desc: '平台发布草稿、投流判断、数据建议', tag: '发布' }
]

const badWords = ['最', '第一', '保证', '包赚', '稳赚', '绝对', '唯一', '国家级', '100%', '躺赚', '无风险']

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

  const [industry, setIndustry] = useState('企业服务')
  const [audience, setAudience] = useState('老板、企业负责人、需要获客的本地商家')
  const [sellingPoints, setSellingPoints] = useState('AI 自动生成文案、配音、剪辑、封面和平台发布草稿')
  const [style, setStyle] = useState('老板口播、真实可信、强转化、短平快')
  const [duration, setDuration] = useState(35)
  const [leadRegion, setLeadRegion] = useState('本地同城老板 / 企业客户')
  const [conversionGoal, setConversionGoal] = useState('私信咨询 / 留资 / 加微信')

  const [assets, setAssets] = useState<AssetItem[]>([])
  const [selectedMaterialIds, setSelectedMaterialIds] = useState<string[]>([])
  const [selectedReferenceAssetId, setSelectedReferenceAssetId] = useState('')
  const [sourceUrl, setSourceUrl] = useState('')
  const [manualText, setManualText] = useState('')
  const [extract, setExtract] = useState<InspirationExtractResponse | null>(null)

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

  const [segmentSeconds, setSegmentSeconds] = useState<Record<number, number>>({})
  const [segmentTransitions, setSegmentTransitions] = useState<Record<number, string>>({})
  const [subtitleSize, setSubtitleSize] = useState(58)
  const [subtitleColor, setSubtitleColor] = useState('#ffffff')
  const [subtitleHighlight, setSubtitleHighlight] = useState('客户,同行,投流,获客,成本')
  const [coverStyle, setCoverStyle] = useState('老板口播强钩子封面')

  const [video, setVideo] = useState<ComposeResponse | null>(null)
  const [cover, setCover] = useState<CoverResponse | null>(null)
  const [editInstruction, setEditInstruction] = useState('把开头节奏加快，保留重点字幕；转场更自然，并重新导出 9:16。')
  const [editChat, setEditChat] = useState<VideoEditChatResponse[]>([])
  const [ad, setAd] = useState<AdAnalysisResponse | null>(null)
  const [platform, setPlatform] = useState('douyin')
  const [publish, setPublish] = useState<PlatformPublishResponse | null>(null)

  const materialAssets = useMemo(() => assets.filter(a => !a.filename.startsWith('collected_')), [assets])
  const collectedVideos = useMemo(() => assets.filter(a => a.kind === 'video' && a.filename.startsWith('collected_')), [assets])
  const referenceText = useMemo(() => extract?.transcript || manualText || sourceUrl, [extract, manualText, sourceUrl])
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

  async function run<T>(label: string, fn: () => Promise<T>) {
    setBusy(label); setError('')
    try { return await fn() } catch (e: any) { setError(e.message || String(e)); throw e } finally { setBusy('') }
  }

  async function reloadAssets() {
    const list = await apiGet<AssetItem[]>('/api/assets')
    setAssets(Array.isArray(list) ? list : [])
  }

  useEffect(() => {
    apiGet('/api/health').then(setHealth).catch((e) => setError(e.message || 'API 未连接'))
    apiGet<TTSVoice[]>('/api/tts/voices').then(v => { const list = Array.isArray(v) ? v : []; setVoices(list); setVoice(list[0]?.id || '') }).catch(() => null)
    reloadAssets().catch(() => null)
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
    setActive('collector')
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
  }

  async function planEdit() {
    const res = await run('生成深度剪辑方案', () => apiPost<EditPlanResponse>('/api/edit-plan', {
      title: copy.title,
      script: currentScript,
      duration_seconds: duration,
      asset_summary: [...materialAssets, ...collectedVideos].map(a => `${a.kind}:${a.original_name}`).join('；')
    }))
    setEditPlan(res!)
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
    setActive('voice')
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
    setActive('video')
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
    { label: '同行采集', done: Boolean(extract), value: extract?.collector_status || extract?.status || '待采集' },
    { label: '文案钩子', done: Boolean(copy.hook), value: copy.title || '待生成' },
    { label: '声音分段', done: Boolean(audio), value: voiceSegments.length ? `${voiceSegments.length} 段 · ${selectedVoiceName}` : '待配音' },
    { label: '视频成品', done: Boolean(video?.video_url), value: video?.video_name || '待合成' },
    { label: '平台发布', done: Boolean(publish), value: publish?.status || '草稿预留' }
  ]

  return <div className="appShell">
    <aside className="studioNav">
      <div className="brandMark">
        <div className="logo">抖</div>
        <div><strong>AI抖音流量获客</strong><span>采集 · 创作 · 发布</span></div>
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
          <span className="eyebrow">短视频获客工作台</span>
          <h1>采集同行 → 定位客户 → 打磨文案 → 配音剪辑 → 发布复盘</h1>
          <p>把采集、文案、配音、素材、剪辑和发布拆开管理；每一步都能接着上一环继续做。</p>
        </div>
        <div className="scoreCard"><span>当前进度</span><strong>{leadScore}%</strong><small>{leadScore >= 80 ? '可以进入发布前检查' : '继续补齐内容和素材'}</small></div>
      </header>

      {error && <div className="globalError">{error}</div>}
      {busy && <div className="busy">正在执行：{busy}</div>}

      <section className="progressRail">
        {stageCards.map((s, idx) => <div key={s.label} className={`stage ${s.done ? 'done' : ''}`}>
          <span>{idx + 1}</span><strong>{s.label}</strong><em>{s.value}</em>
        </div>)}
      </section>

      {active === 'dashboard' && <section className="moduleGrid">
        {modules.filter(x => x.key !== 'dashboard').map(item => <button className="moduleCard" key={item.key} onClick={() => setActive(item.key)}>
          <span className="moduleIcon">{item.icon}</span>
          <strong>{item.title}</strong>
          <p>{item.desc}</p>
          <em>进入</em>
        </button>)}
      </section>}

      {active === 'strategy' && <section className="card modulePanel">
        <div className="sectionHeader"><div><h2>获客定位</h2><p>先定客户，再学同行。文案、投流、素材匹配都会读取这里的定位。</p></div><Button busy={busy === '投流分析' ? busy : ''} label="投流/获客方向分析" onClick={analyzeAd} kind="soft" /></div>
        <div className="grid2">
          <Field label="行业"><input value={industry} onChange={e => setIndustry(e.target.value)} /></Field>
          <Field label="目标客户"><input value={audience} onChange={e => setAudience(e.target.value)} /></Field>
          <Field label="获客地域 / 人群"><input value={leadRegion} onChange={e => setLeadRegion(e.target.value)} /></Field>
          <Field label="转化目标"><input value={conversionGoal} onChange={e => setConversionGoal(e.target.value)} /></Field>
        </div>
        <Field label="核心卖点"><textarea value={sellingPoints} onChange={e => setSellingPoints(e.target.value)} /></Field>
        <Field label="视频风格"><input value={style} onChange={e => setStyle(e.target.value)} /></Field>
        {ad && <div className="resultBox"><h3>{ad.decision}</h3><p>建议预算：{ad.suggested_budget} · 置信度：{Math.round(ad.confidence * 100)}%</p><div className="chips">{ad.target_audience?.map(x => <Pill key={x}>{x}</Pill>)}</div>{ad.optimization_tips?.map(x => <p key={x}>· {x}</p>)}</div>}
      </section>}

      {active === 'collector' && <section className="card modulePanel">
        <div className="sectionHeader"><div><h2>同行采集</h2><p>粘抖音整段分享口令；系统尽力采视频，失败也会拆标题、钩子、话题。</p></div><Button busy={busy === '采集/拆解同行内容' ? busy : ''} label="采集/拆解同行内容" onClick={collectCompetitor} /></div>
        <div className="grid2">
          <Field label="抖音分享口令 / 视频链接"><textarea value={sourceUrl} onChange={e => setSourceUrl(e.target.value)} placeholder="直接粘贴：1.58 ... https://v.douyin.com/... 复制此链接..." /></Field>
          <Field label="手动粘贴竞品文案 / 豆包 App 识别稿"><textarea value={manualText} onChange={e => setManualText(e.target.value)} placeholder="如果已经有真实口播稿，粘这里。" /></Field>
        </div>
        {extract && <div className="resultBox">
          <div className="resultTop"><Pill>{extract.status}</Pill><Pill tone="purple">{extract.collector_status || 'text'}</Pill>{extract.collected_video_url && <a href={extract.collected_video_url} target="_blank">打开采集视频</a>}</div>
          <h3>同行拆解结果</h3><p>{extract.summary}</p>
          <div className="splitGrid"><div><h4>黄金三秒/钩子</h4>{extract.hooks?.map(x => <p key={x}>· {x}</p>)}</div><div><h4>卖点/痛点</h4>{extract.selling_points?.map(x => <p key={x}>· {x}</p>)}</div><div><h4>结构</h4>{extract.structure?.map(x => <p key={x}>· {x}</p>)}</div></div>
          {extract.warnings?.map(w => <div className="warn" key={w}>{w}</div>)}
        </div>}
      </section>}

      {active === 'copy' && <section className="card modulePanel">
        <div className="sectionHeader"><div><h2>文案工作台</h2><p>目标客户 + 热门脚本结合；支持黄金三秒、细改、违禁词检查。</p></div></div>
        <div className="grid4"><Field label="视频时长"><input type="number" min={5} max={180} value={duration} onChange={e => setDuration(Number(e.target.value || 35))} /></Field><Field label="标题字数方向"><input value="短、狠、直给" readOnly /></Field><Field label="开头策略"><input value="痛点/反差/警告/结果" readOnly /></Field><Field label="当前风险"><input value={matchedBadWords.length ? `${matchedBadWords.length} 个敏感词` : '暂无明显风险'} readOnly /></Field></div>
        <div className="buttonRow"><Button busy={busy === '生成文案' ? busy : ''} label="直接生成文案" onClick={generateDirectCopy} kind="ghost" /><Button busy={busy === '原创改写' ? busy : ''} label="基于同行原创改写" onClick={rewrite} /><Button busy={busy === '文案细改' ? busy : ''} label="按要求细改文案" onClick={refineCopy} kind="soft" disabled={!currentScript} /></div>
        <div className="copyEditor"><Field label="标题"><input value={copy.title} onChange={e => setCopy({ ...copy, title: e.target.value })} /></Field><Field label="黄金三秒钩子"><textarea value={copy.hook} onChange={e => setCopy({ ...copy, hook: e.target.value })} /></Field><Field label="完整口播稿"><textarea className="scriptArea" value={copy.script} onChange={e => setCopy({ ...copy, script: e.target.value })} placeholder="这里可以精修口播稿；选中文本后点“加入分段”。" /></Field><Field label="发布简介"><textarea value={copy.description} onChange={e => setCopy({ ...copy, description: e.target.value })} /></Field><Field label="细改要求"><input value={refineInstruction} onChange={e => setRefineInstruction(e.target.value)} /></Field></div>
        <div className="chips">{matchedBadWords.length ? matchedBadWords.map(x => <Pill key={x} tone="red">风险词：{x}</Pill>) : <Pill tone="green">违禁词初筛通过</Pill>}</div>
      </section>}

      {active === 'voice' && <section className="card modulePanel">
        <div className="sectionHeader"><div><h2>声音导演</h2><p>克隆音色 + 分段情绪强化 + 语速停顿调节。分段可以自己添加。</p></div></div>
        <div className="grid4"><Field label="音色"><select value={voice} onChange={e => setVoice(e.target.value)}>{voices.map(v => <option key={v.id} value={v.id}>{v.name || v.id}</option>)}</select></Field><Field label="配音风格"><select value={voiceStyle} onChange={e => setVoiceStyle(e.target.value)}>{['老板压迫感','真实聊天感','短视频强钩子','销售转化感','案例讲述感','沉稳信任感'].map(x => <option key={x}>{x}</option>)}</select></Field><Field label="情绪强度"><select value={voiceIntensity} onChange={e => setVoiceIntensity(e.target.value)}>{['轻微','标准','强烈'].map(x => <option key={x}>{x}</option>)}</select></Field><div className="stackButtons"><Button busy={busy === '生成配音导演稿' ? busy : ''} label="生成配音导演稿" onClick={makeVoiceDirector} kind="ghost" disabled={!currentScript} /><Button busy={busy === '生成分段情绪配音' ? busy : ''} label="生成分段情绪配音" onClick={makeSegmentTTS} disabled={!currentScript} /></div></div>
        {voiceNotes.length > 0 && <div className="tips">{voiceNotes.map(x => <span key={x}>{x}</span>)}</div>}
        <div className="buttonRow"><button className="addSegment" onClick={addVoiceSegment}>+ 手动添加空白分段</button><button className="addSegment" onClick={addSelectedScriptAsSegment}>+ 把选中文案加入分段</button></div>
        <div className="segments">{voiceSegments.map((seg, i) => <div className="segmentCard" key={i}><div className="segmentHead"><strong>第 {i + 1} 段 · {segmentSeconds[i] || estimateSeconds(seg.text, seg.speed_ratio)} 秒</strong><div><button onClick={() => moveVoiceSegment(i, -1)}>↑</button><button onClick={() => moveVoiceSegment(i, 1)}>↓</button><button onClick={() => removeVoiceSegment(i)}>删除</button></div></div><textarea value={seg.text} onChange={e => updateVoiceSegment(i, { text: e.target.value })} /><div className="segmentGrid"><Field label="情绪"><input value={seg.emotion} onChange={e => updateVoiceSegment(i, { emotion: e.target.value })} /></Field><Field label={`语速 ${seg.speed_ratio}`}><input type="range" min="0.75" max="1.35" step="0.01" value={seg.speed_ratio} onChange={e => updateVoiceSegment(i, { speed_ratio: Number(e.target.value) })} /></Field><Field label={`音量 ${seg.volume_ratio}`}><input type="range" min="0.7" max="1.4" step="0.01" value={seg.volume_ratio} onChange={e => updateVoiceSegment(i, { volume_ratio: Number(e.target.value) })} /></Field><Field label={`停顿 ${seg.pause_after_ms}ms`}><input type="range" min="0" max="1500" step="50" value={seg.pause_after_ms} onChange={e => updateVoiceSegment(i, { pause_after_ms: Number(e.target.value) })} /></Field></div></div>)}</div>
        {audio && <div className="mediaBox"><audio controls src={audio.file_url} /><a href={audio.file_url} target="_blank">下载配音</a>{audio.warning && <div className="warn">{audio.warning}</div>}</div>}
      </section>}

      {active === 'assets' && <section className="card modulePanel">
        <div className="sectionHeader"><div><h2>素材工作台</h2><p>素材库和采集视频库分开管理；素材用于合成，采集视频用于学习。</p></div><input type="file" multiple accept="image/*,video/*" onChange={e => handleUpload(e.target.files)} /></div>
        <div className="grid2"><div><h3>素材库</h3><div className="assetList">{materialAssets.length === 0 && <Empty>还没有素材。</Empty>}{materialAssets.map(a => <label key={a.id} className="assetRow"><input type="checkbox" checked={selectedMaterialIds.includes(a.id)} onChange={() => toggleMaterial(a.id)} /><span>{a.kind === 'video' ? '🎬' : '🖼️'} {a.original_name}</span><em>{formatBytes(a.size_bytes)}</em></label>)}</div></div><div><h3>采集视频库</h3><div className="assetList">{collectedVideos.length === 0 && <Empty>暂时没有采集到视频。</Empty>}{collectedVideos.map(a => <button key={a.id} className={`assetButton ${selectedReferenceAssetId === a.id ? 'selected' : ''}`} onClick={() => setSelectedReferenceAssetId(a.id)}>🎯 {a.original_name}<em>{formatBytes(a.size_bytes)}</em></button>)}</div></div></div>
        <div className="resultBox"><h3>素材匹配建议</h3><p>优先把老板出镜、办公室、客户交流、产品细节、服务流程素材分别对应到口播分段。没有匹配素材时，先用采集视频的结构做 B-roll 参考，不直接照搬原画面。</p></div>
      </section>}

      {active === 'video' && <section className="card modulePanel">
        <div className="sectionHeader"><div><h2>视频工作台</h2><p>分段时长、转场、字幕和 AI 插件修改都在这里集中处理。</p></div><Button busy={busy === '合成视频并烧字幕' ? busy : ''} label="合成并下载 9:16 MP4" onClick={composeVideo} disabled={!currentScript} /></div>
        <div className="timelineEditor"><h3>分段时长 / 转场</h3>{voiceSegments.length === 0 && <Empty>先生成配音导演稿，或手动添加分段。</Empty>}{voiceSegments.map((seg, i) => <div className="timelineRow" key={i}><span>第{i + 1}段</span><input type="number" min="1" max="60" step="0.5" value={segmentSeconds[i] || estimateSeconds(seg.text, seg.speed_ratio)} onChange={e => setSegmentSeconds(prev => ({ ...prev, [i]: Number(e.target.value) }))} /><select value={segmentTransitions[i] || '叠化'} onChange={e => setSegmentTransitions(prev => ({ ...prev, [i]: e.target.value }))}><option>叠化</option><option>虚化</option><option>快切</option><option>推近</option><option>闪白</option></select><em>{seg.text.slice(0, 28)}...</em></div>)}</div>
        {video && <div className="videoGrid"><video controls src={video.video_url} /><div className="downloadPanel"><a className="download" href={video.video_url} target="_blank">下载视频 MP4</a>{video.subtitle_url && <a href={video.subtitle_url} target="_blank">下载字幕 SRT</a>}{video.audio_url && <a href={video.audio_url} target="_blank">下载音频</a>}{video.warnings?.map(w => <div className="warn" key={w}>{w}</div>)}</div></div>}
        <div className="editChatBox"><Field label="AI + 插件剪辑指令"><textarea value={editInstruction} onChange={e => setEditInstruction(e.target.value)} placeholder="例如：去掉开头2秒、整体加速1.1倍、重新加字幕、转成9:16。" /></Field><Button busy={busy === 'AI + 插件修改视频' ? busy : ''} label="AI + 插件修改视频" onClick={chatEditVideo} kind="ghost" disabled={!currentVideoName} />{editChat.map((msg, i) => <div className="chatMsg" key={i}><strong>AI：</strong>{msg.assistant_message}<p>{msg.summary}</p><div className="chips">{msg.actions?.map(x => <Pill key={x}>{x}</Pill>)}</div>{msg.new_video_url && <a href={msg.new_video_url} target="_blank">打开修改后视频</a>}{msg.warnings?.map(w => <div className="warn" key={w}>{w}</div>)}</div>)}</div>
      </section>}

      {active === 'subtitleCover' && <section className="card modulePanel">
        <div className="sectionHeader"><div><h2>字幕与封面</h2><p>字幕重点字放大，封面样式可选；后续可接 AI 图片生成封面。</p></div><Button busy={busy === '生成封面' ? busy : ''} label="生成封面" onClick={makeCover} /></div>
        <div className="grid4"><Field label="字幕字号"><input type="number" value={subtitleSize} onChange={e => setSubtitleSize(Number(e.target.value || 58))} /></Field><Field label="字幕颜色"><input type="color" value={subtitleColor} onChange={e => setSubtitleColor(e.target.value)} /></Field><Field label="重点词"><input value={subtitleHighlight} onChange={e => setSubtitleHighlight(e.target.value)} /></Field><Field label="封面样式"><select value={coverStyle} onChange={e => setCoverStyle(e.target.value)}><option>老板口播强钩子封面</option><option>痛点警告型封面</option><option>案例结果型封面</option><option>产品服务型封面</option><option>同城获客型封面</option></select></Field></div>
        {cover && <div className="coverPreview"><img src={cover.cover_url} /><div><h3>封面已生成</h3><p>{cover.prompt}</p><a className="download" href={cover.cover_url} target="_blank">下载封面</a></div></div>}
      </section>}

      {active === 'publish' && <section className="card modulePanel">
        <div className="sectionHeader"><div><h2>平台发布与投流</h2><p>发布入口先做草稿；等抖音/视频号开放平台权限下来再接真实发布。</p></div></div>
        <div className="buttonRow"><Button busy={busy === '投流分析' ? busy : ''} label="投流分析" onClick={analyzeAd} kind="ghost" /><select value={platform} onChange={e => setPlatform(e.target.value)}><option value="douyin">抖音</option><option value="shipinhao">视频号</option><option value="kuaishou">快手</option><option value="xiaohongshu">小红书</option></select><Button busy={busy === '生成平台发布草稿' ? busy : ''} label="生成平台发布草稿" onClick={platformPublish} /></div>
        <div className="grid2">{ad && <div className="miniResult"><h3>{ad.decision}</h3><p>预算：{ad.suggested_budget}</p>{ad.optimization_tips?.map(x => <p key={x}>· {x}</p>)}</div>}{publish && <div className="miniResult"><h3>{publish.platform}：{publish.status}</h3><p>{publish.message}</p>{publish.checklist?.map(x => <p key={x}>· {x}</p>)}</div>}</div>
      </section>}
    </main>
  </div>
}
