import { useEffect, useMemo, useState } from 'react'
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
  CollectorStatus,
  apiGet,
  apiPost,
  uploadAssets,
  uploadCollectorCookies
} from './api'

function Field({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return <label className="field"><span>{label}</span>{children}{hint && <em>{hint}</em>}</label>
}

function Button({ busy, label, onClick, kind = 'primary', disabled = false }: { busy?: string; label: string; onClick: () => void; kind?: 'primary' | 'ghost' | 'danger'; disabled?: boolean }) {
  return <button className={`btn ${kind}`} disabled={disabled || Boolean(busy)} onClick={onClick}>{busy || label}</button>
}

function Pill({ children }: { children: React.ReactNode }) { return <span className="pill">{children}</span> }

const emptyCopy: GeneratedCopy = { title: '', hook: '', script: '', description: '', tags: [], shots: [], kb_refs: [] }

const defaultSegment: VoiceSegment = {
  text: '这里输入新增口播分段。',
  emotion: '自然可信',
  speed_ratio: 1,
  volume_ratio: 1,
  pitch_ratio: 1,
  pause_after_ms: 450
}

export default function App() {
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [health, setHealth] = useState<any>(null)
  const [collectorStatus, setCollectorStatus] = useState<CollectorStatus | null>(null)

  const [industry, setIndustry] = useState('企业服务')
  const [audience, setAudience] = useState('老板、企业负责人、需要获客的本地商家')
  const [sellingPoints, setSellingPoints] = useState('AI 自动生成文案、配音、剪辑、封面和平台发布草稿')
  const [style, setStyle] = useState('老板口播、真实可信、强转化、短平快')
  const [duration, setDuration] = useState(35)

  const [assets, setAssets] = useState<AssetItem[]>([])
  const [selectedMaterialIds, setSelectedMaterialIds] = useState<string[]>([])
  const [selectedReferenceAssetId, setSelectedReferenceAssetId] = useState('')
  const [sourceUrl, setSourceUrl] = useState('')
  const [manualText, setManualText] = useState('')
  const [extract, setExtract] = useState<InspirationExtractResponse | null>(null)

  const [copy, setCopy] = useState<GeneratedCopy>(emptyCopy)
  const [refineInstruction, setRefineInstruction] = useState('把开头改得更有压迫感，语气更像老板提醒客户。')
  const [editPlan, setEditPlan] = useState<EditPlanResponse | null>(null)

  const [voices, setVoices] = useState<TTSVoice[]>([])
  const [voice, setVoice] = useState('')
  const [voiceStyle, setVoiceStyle] = useState('老板压迫感')
  const [voiceIntensity, setVoiceIntensity] = useState('标准')
  const [voiceSegments, setVoiceSegments] = useState<VoiceSegment[]>([])
  const [voiceNotes, setVoiceNotes] = useState<string[]>([])
  const [audio, setAudio] = useState<TTSResponse | null>(null)

  const [video, setVideo] = useState<ComposeResponse | null>(null)
  const [cover, setCover] = useState<CoverResponse | null>(null)
  const [editInstruction, setEditInstruction] = useState('给视频重新加字幕，并按 9:16 竖屏重新导出。')
  const [editChat, setEditChat] = useState<VideoEditChatResponse[]>([])
  const [ad, setAd] = useState<AdAnalysisResponse | null>(null)
  const [platform, setPlatform] = useState('douyin')
  const [publish, setPublish] = useState<PlatformPublishResponse | null>(null)

  const materialAssets = useMemo(() => assets.filter(a => !a.filename.startsWith('collected_')), [assets])
  const collectedVideos = useMemo(() => assets.filter(a => a.kind === 'video' && a.filename.startsWith('collected_')), [assets])
  const referenceText = useMemo(() => extract?.transcript || manualText || sourceUrl, [extract, manualText, sourceUrl])
  const currentScript = copy.script || ''
  const currentVideoName = video?.video_name || extract?.collected_video_name || ''

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
    apiGet<CollectorStatus>('/api/collector/status').then(setCollectorStatus).catch(() => null)
    apiGet<TTSVoice[]>('/api/tts/voices').then(v => { const list = Array.isArray(v) ? v : []; setVoices(list); setVoice(list[0]?.id || '') }).catch(() => null)
    reloadAssets().catch(() => null)
  }, [])

  async function handleUpload(files: FileList | null) {
    if (!files?.length) return
    const res = await run('上传素材', () => uploadAssets(files))
    setAssets(prev => [...(res || []), ...prev])
    const ids = (res || []).filter(a => !a.filename.startsWith('collected_')).map(a => a.id)
    if (ids.length) setSelectedMaterialIds(prev => Array.from(new Set([...ids, ...prev])))
  }

  async function handleCookieUpload(files: FileList | null) {
    const file = files?.[0]
    if (!file) return
    const res = await run('上传采集凭证', () => uploadCollectorCookies(file))
    setCollectorStatus(res!)
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
  }

  async function generateDirectCopy() {
    const res = await run('生成文案', () => apiPost<GeneratedCopy>('/api/generate-copy', {
      topic: sellingPoints,
      industry,
      audience,
      selling_points: sellingPoints,
      style,
      duration_seconds: duration,
      knowledge_examples: manualText ? [manualText] : []
    }))
    setCopy(res!)
  }

  async function rewrite() {
    const res = await run('原创改写', () => apiPost<GeneratedCopy>('/api/rewrite-from-inspiration', {
      reference_text: referenceText || '请根据业务信息生成原创老板口播文案。',
      industry,
      audience,
      selling_points: sellingPoints,
      style,
      duration_seconds: duration
    }))
    setCopy(res!)
  }

  async function refineCopy() {
    const res = await run('文案细改', () => apiPost<GeneratedCopy>('/api/refine-copy', {
      ...copy,
      instruction: refineInstruction,
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
    setVoiceSegments(Array.isArray(res!.segments) ? res!.segments : [])
    setVoiceNotes(Array.isArray(res!.director_notes) ? res!.director_notes : [])
    setCopy(prev => ({ ...prev, script: res!.rewritten_script || prev.script }))
  }

  function updateVoiceSegment(index: number, patch: Partial<VoiceSegment>) {
    setVoiceSegments(prev => prev.map((seg, i) => i === index ? { ...seg, ...patch } : seg))
  }

  function addVoiceSegment() { setVoiceSegments(prev => [...prev, { ...defaultSegment }]) }
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
  }

  async function chatEditVideo() {
    const res = await run('AI + 插件修改视频', () => apiPost<VideoEditChatResponse>('/api/video-edit-chat', {
      video_file_name: currentVideoName,
      instruction: editInstruction,
      title: copy.title,
      script: currentScript,
      asset_summary: [...materialAssets, ...collectedVideos].map(a => `${a.kind}:${a.original_name}`).join('；')
    }))
    setEditChat(prev => [res!, ...prev])
    if (res?.new_video_url && res?.new_video_name) {
      setVideo(prev => prev ? { ...prev, video_url: res.new_video_url!, video_name: res.new_video_name! } : { video_url: res.new_video_url!, video_name: res.new_video_name!, duration_seconds: duration, warnings: res.warnings || [] })
    }
  }

  async function makeCover() {
    const res = await run('生成封面', () => apiPost<CoverResponse>('/api/cover', {
      title: copy.title || '短视频封面',
      hook: copy.hook,
      subtitle: copy.tags?.slice(0, 3).join(' · '),
      brand: industry
    }))
    setCover(res!)
  }

  async function analyzeAd() {
    const res = await run('投流分析', () => apiPost<AdAnalysisResponse>('/api/ad-analysis', {
      title: copy.title,
      script: currentScript,
      industry,
      budget: 300,
      objective: '线索/咨询'
    }))
    setAd(res!)
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
  }

  return <div className="appShell">
    <header className="topbar">
      <div>
        <div className="eyebrow">AI-VIDEO Studio</div>
        <h1>同行采集 · 文案细改 · 情绪配音 · 深度剪辑</h1>
      </div>
      <div className={`status ${health?.ok ? 'ok' : 'bad'}`}>{health?.ok ? 'API 已连接' : 'API 未连接'}</div>
    </header>

    {error && <div className="globalError">{error}</div>}
    {busy && <div className="busy">正在执行：{busy}</div>}

    <main className="workspace">
      <aside className="sidebar">
        <section className="card compact">
          <h2>素材库</h2>
          <p>这里放自己要用来合成视频的图片/视频。</p>
          <input type="file" multiple accept="image/*,video/*" onChange={e => handleUpload(e.target.files)} />
          <div className="assetList">
            {materialAssets.length === 0 && <div className="empty">还没有素材。</div>}
            {materialAssets.map(a => <label key={a.id} className="assetRow">
              <input type="checkbox" checked={selectedMaterialIds.includes(a.id)} onChange={() => toggleMaterial(a.id)} />
              <span>{a.kind === 'video' ? '🎬' : '🖼️'} {a.original_name}</span>
            </label>)}
          </div>
        </section>

        <section className="card compact">
          <h2>采集视频库</h2>
          <p>先用开源采集器提取视频，成功后再交给 AI 识别拆解；失败则保留文案钩子。</p>
          <div className="collectorBox">
            <div className="collectorLine"><span>插件</span><b>{collectorStatus?.ytdlp_enabled ? 'yt-dlp 已启用' : '未启用'}</b></div>
            <div className="collectorLine"><span>登录凭证</span><b>{collectorStatus?.has_cookies ? 'cookies.txt 已上传' : '未上传'}</b></div>
            <input type="file" accept=".txt,text/plain" onChange={e => handleCookieUpload(e.target.files)} />
            <p className="smallHint">如果出现 Fresh cookies needed，就上传自己浏览器导出的 cookies.txt 后重试。只用于自己可正常访问的公开视频。</p>
          </div>
          <div className="assetList">
            {collectedVideos.length === 0 && <div className="empty">暂时没有采集到视频。</div>}
            {collectedVideos.map(a => <button key={a.id} className={`assetButton ${selectedReferenceAssetId === a.id ? 'selected' : ''}`} onClick={() => setSelectedReferenceAssetId(a.id)}>
              🎯 {a.original_name}
            </button>)}
          </div>
        </section>
      </aside>

      <section className="mainColumn">
        <section className="card heroCard">
          <div className="sectionHeader">
            <div><h2>1. 同行采集</h2><p>粘抖音整段分享口令；系统会尽力采视频，失败也会拆标题、钩子、话题。</p></div>
            <Button busy={busy === '采集/拆解同行内容' ? busy : ''} label="采集/拆解同行内容" onClick={collectCompetitor} />
          </div>
          <div className="grid2">
            <Field label="抖音分享口令 / 视频链接">
              <textarea value={sourceUrl} onChange={e => setSourceUrl(e.target.value)} placeholder="直接粘贴：1.58 ... https://v.douyin.com/... 复制此链接..." />
            </Field>
            <Field label="手动粘贴竞品文案 / 豆包 App 识别稿">
              <textarea value={manualText} onChange={e => setManualText(e.target.value)} placeholder="如果已经有口播稿，粘这里。" />
            </Field>
          </div>
          {extract && <div className="resultBox">
            <div className="resultTop"><Pill>{extract.status}</Pill><Pill>{extract.collector_status || 'text'}</Pill>{extract.collected_video_url && <a href={extract.collected_video_url} target="_blank">打开采集视频</a>}</div>
            <h3>拆解结果</h3>
            <p>{extract.summary}</p>
            <div className="chips">{extract.hooks?.map(x => <Pill key={x}>{x}</Pill>)}</div>
            {extract.warnings?.map(w => <div className="warn" key={w}>{w}</div>)}
          </div>}
        </section>

        <section className="card">
          <div className="sectionHeader"><div><h2>2. 文案工作台</h2><p>可以直接生成，也可以基于同行结构原创改写，再做细改。</p></div></div>
          <div className="grid4">
            <Field label="行业"><input value={industry} onChange={e => setIndustry(e.target.value)} /></Field>
            <Field label="目标客户"><input value={audience} onChange={e => setAudience(e.target.value)} /></Field>
            <Field label="视频时长"><input type="number" min={5} max={180} value={duration} onChange={e => setDuration(Number(e.target.value || 35))} /></Field>
            <Field label="风格"><input value={style} onChange={e => setStyle(e.target.value)} /></Field>
          </div>
          <Field label="核心卖点"><textarea value={sellingPoints} onChange={e => setSellingPoints(e.target.value)} /></Field>
          <div className="buttonRow">
            <Button busy={busy === '生成文案' ? busy : ''} label="直接生成文案" onClick={generateDirectCopy} kind="ghost" />
            <Button busy={busy === '原创改写' ? busy : ''} label="基于同行原创改写" onClick={rewrite} />
            <Button busy={busy === '生成深度剪辑方案' ? busy : ''} label="生成剪辑方案" onClick={planEdit} kind="ghost" />
          </div>
          <div className="copyEditor">
            <Field label="标题"><input value={copy.title} onChange={e => setCopy({ ...copy, title: e.target.value })} /></Field>
            <Field label="开头钩子"><textarea value={copy.hook} onChange={e => setCopy({ ...copy, hook: e.target.value })} /></Field>
            <Field label="完整口播稿"><textarea className="scriptArea" value={copy.script} onChange={e => setCopy({ ...copy, script: e.target.value })} /></Field>
            <Field label="发布简介"><textarea value={copy.description} onChange={e => setCopy({ ...copy, description: e.target.value })} /></Field>
            <Field label="细改要求"><input value={refineInstruction} onChange={e => setRefineInstruction(e.target.value)} placeholder="例如：更像老板说话，减少书面词，前3秒更狠。" /></Field>
            <Button busy={busy === '文案细改' ? busy : ''} label="按要求细改文案" onClick={refineCopy} kind="ghost" disabled={!currentScript} />
          </div>
          {editPlan && <div className="resultBox"><h3>深度剪辑方案</h3><p>{editPlan.rhythm}</p><ul>{editPlan.timeline?.map(x => <li key={x}>{x}</li>)}</ul><div className="chips">{editPlan.broll_keywords?.map(x => <Pill key={x}>{x}</Pill>)}</div></div>}
        </section>

        <section className="card">
          <div className="sectionHeader"><div><h2>3. 配音导演与分段调速</h2><p>分段可以自己加、删、改。每段单独控制语速、音量、音高和停顿。</p></div></div>
          <div className="grid4">
            <Field label="音色"><select value={voice} onChange={e => setVoice(e.target.value)}>{voices.map(v => <option key={v.id} value={v.id}>{v.name || v.id}</option>)}</select></Field>
            <Field label="配音风格"><select value={voiceStyle} onChange={e => setVoiceStyle(e.target.value)}>{['老板压迫感','真实聊天感','短视频强钩子','销售转化感','案例讲述感','沉稳信任感'].map(x => <option key={x}>{x}</option>)}</select></Field>
            <Field label="情绪强度"><select value={voiceIntensity} onChange={e => setVoiceIntensity(e.target.value)}>{['轻微','标准','强烈'].map(x => <option key={x}>{x}</option>)}</select></Field>
            <div className="stackButtons"><Button busy={busy === '生成配音导演稿' ? busy : ''} label="生成配音导演稿" onClick={makeVoiceDirector} kind="ghost" disabled={!currentScript} /><Button busy={busy === '生成分段情绪配音' ? busy : ''} label="生成分段情绪配音" onClick={makeSegmentTTS} disabled={!currentScript} /></div>
          </div>
          {voiceNotes.length > 0 && <div className="tips">{voiceNotes.map(x => <span key={x}>{x}</span>)}</div>}
          <div className="segments">
            {voiceSegments.map((seg, i) => <div className="segmentCard" key={i}>
              <div className="segmentHead"><strong>第 {i + 1} 段</strong><div><button onClick={() => moveVoiceSegment(i, -1)}>↑</button><button onClick={() => moveVoiceSegment(i, 1)}>↓</button><button onClick={() => removeVoiceSegment(i)}>删除</button></div></div>
              <textarea value={seg.text} onChange={e => updateVoiceSegment(i, { text: e.target.value })} />
              <div className="segmentGrid">
                <Field label="情绪"><input value={seg.emotion} onChange={e => updateVoiceSegment(i, { emotion: e.target.value })} /></Field>
                <Field label={`语速 ${seg.speed_ratio}`}><input type="range" min="0.75" max="1.35" step="0.01" value={seg.speed_ratio} onChange={e => updateVoiceSegment(i, { speed_ratio: Number(e.target.value) })} /></Field>
                <Field label={`音量 ${seg.volume_ratio}`}><input type="range" min="0.7" max="1.4" step="0.01" value={seg.volume_ratio} onChange={e => updateVoiceSegment(i, { volume_ratio: Number(e.target.value) })} /></Field>
                <Field label={`停顿 ${seg.pause_after_ms}ms`}><input type="range" min="0" max="1500" step="50" value={seg.pause_after_ms} onChange={e => updateVoiceSegment(i, { pause_after_ms: Number(e.target.value) })} /></Field>
              </div>
            </div>)}
          </div>
          <button className="addSegment" onClick={addVoiceSegment}>+ 手动添加分段</button>
          {audio && <div className="mediaBox"><audio controls src={audio.file_url} /><a href={audio.file_url} target="_blank">下载配音</a>{audio.warning && <div className="warn">{audio.warning}</div>}</div>}
        </section>

        <section className="card">
          <div className="sectionHeader"><div><h2>4. 视频合成与 AI 深度剪辑</h2><p>合成视频会自动烧字幕。生成后可以和 AI 对话，用插件继续裁剪、调速、加字幕。</p></div><Button busy={busy === '合成视频并烧字幕' ? busy : ''} label="合成 9:16 视频" onClick={composeVideo} disabled={!currentScript} /></div>
          {video && <div className="videoGrid"><video controls src={video.video_url} /><div className="downloadPanel"><a className="download" href={video.video_url} target="_blank">下载视频 MP4</a>{video.subtitle_url && <a href={video.subtitle_url} target="_blank">下载字幕 SRT</a>}{video.audio_url && <a href={video.audio_url} target="_blank">下载音频</a>}{video.warnings?.map(w => <div className="warn" key={w}>{w}</div>)}</div></div>}
          <div className="editChatBox">
            <Field label="和 AI 说你想怎么改视频"><textarea value={editInstruction} onChange={e => setEditInstruction(e.target.value)} placeholder="例如：去掉开头2秒、整体加速1.1倍、重新加字幕、转成9:16。" /></Field>
            <Button busy={busy === 'AI + 插件修改视频' ? busy : ''} label="AI + 插件修改视频" onClick={chatEditVideo} kind="ghost" disabled={!currentVideoName} />
            {editChat.map((msg, i) => <div className="chatMsg" key={i}><strong>AI：</strong>{msg.assistant_message}<p>{msg.summary}</p><div className="chips">{msg.actions?.map(x => <Pill key={x}>{x}</Pill>)}</div>{msg.new_video_url && <a href={msg.new_video_url} target="_blank">打开修改后视频</a>}{msg.warnings?.map(w => <div className="warn" key={w}>{w}</div>)}</div>)}
          </div>
        </section>

        <section className="card finalCard">
          <div className="sectionHeader"><div><h2>5. 封面、投流、平台发布</h2><p>平台发布入口先保留；等抖音/视频号开放平台权限下来再接真实发布。</p></div></div>
          <div className="buttonRow">
            <Button busy={busy === '生成封面' ? busy : ''} label="生成封面" onClick={makeCover} kind="ghost" />
            <Button busy={busy === '投流分析' ? busy : ''} label="投流分析" onClick={analyzeAd} kind="ghost" />
            <select value={platform} onChange={e => setPlatform(e.target.value)}><option value="douyin">抖音</option><option value="shipinhao">视频号</option><option value="kuaishou">快手</option><option value="xiaohongshu">小红书</option></select>
            <Button busy={busy === '生成平台发布草稿' ? busy : ''} label="生成平台发布草稿" onClick={platformPublish} />
          </div>
          <div className="grid3">
            {cover && <div className="miniResult"><img src={cover.cover_url} /><a href={cover.cover_url} target="_blank">下载封面</a></div>}
            {ad && <div className="miniResult"><h3>{ad.decision}</h3><p>预算：{ad.suggested_budget}</p>{ad.optimization_tips?.map(x => <p key={x}>· {x}</p>)}</div>}
            {publish && <div className="miniResult"><h3>{publish.platform}：{publish.status}</h3><p>{publish.message}</p>{publish.checklist?.map(x => <p key={x}>· {x}</p>)}</div>}
          </div>
        </section>
      </section>
    </main>
  </div>
}
