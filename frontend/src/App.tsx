
import { useEffect, useMemo, useState } from 'react'

type StepKey = 1 | 2 | 3 | 4
type VoiceSegment = { text: string; emotion: string; speed_ratio: number; volume_ratio: number; pitch_ratio: number; pause_after_ms: number; emphasis: string }
type Shot = { narration: string; visual: string; category: string; duration: number; motion: string; transition: string; prompt: string; negative_prompt?: string; scene_type?: string }
type MaterialItem = { asset_id?: string; original_name?: string; filename?: string; kind?: string; category?: string; city?: string; district?: string; source?: string; reusable?: number; note?: string; file_url?: string; tags?: string[] }
type AccountItem = { account_id?: string; platform?: string; handle?: string; name?: string; url?: string; category?: string; value_level?: string; tags?: string[] }

const BACKEND_PUBLIC = 'https://ai-video.47-76-143-158.sslip.io'
const STORAGE_KEY = 'ai_video_v10_34_a_to_g_complete_v1'
const SAFE_TRANSITION = 'smooth_dissolve_no_flash'
const CATEGORIES = ['房产/楼盘素材','生活配套','交通出勤','医疗/诊所/药房','餐饮/食阁','教育/学校','户型/室内','成交/带看/租客','人物口播/数字人模板','报告/资料/截图']
const KIND_OPTIONS = [['video','视频素材'],['image','图片素材'],['audio','音频'],['document','资料/文档'],['script','脚本'],['avatar_template','真人/数字人模板'],['raw_fal_clip','FAL 原片']]
const EMOTIONS = ['自然可信','朋友聊天','专业冷静','提醒警示','紧张急迫','坚定有力','收尾号召']

function safeJson<T>(raw: string | null, fallback: T): T { try { return raw ? JSON.parse(raw) as T : fallback } catch { return fallback } }
function apiPrefix() {
  const env = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '')
  if (env) return env
  if (typeof window !== 'undefined') {
    const host = window.location.hostname
    if (host === 'localhost' || host === '127.0.0.1') return 'http://localhost:8000'
    if (host.endsWith('pages.dev')) return ''
  }
  return BACKEND_PUBLIC
}
async function apiJson<T>(path: string, body?: unknown, method = 'POST'): Promise<T> {
  const res = await fetch(`${apiPrefix()}${path}`, { method, headers: body instanceof FormData ? undefined : { 'Content-Type': 'application/json' }, body: body instanceof FormData ? body : body === undefined ? undefined : JSON.stringify(body) })
  const text = await res.text()
  let data: any
  try { data = text ? JSON.parse(text) : {} } catch { data = { raw: text } }
  if (!res.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : data?.message || data?.error || JSON.stringify(data?.detail || data).slice(0, 600) || `HTTP ${res.status}`)
  return data as T
}
function splitScript(script: string): VoiceSegment[] {
  const parts = script.replace(/\r/g, '').split(/[。！？!?\n]+/).map(s => s.trim()).filter(Boolean)
  return (parts.length ? parts : [script.trim()].filter(Boolean)).map(text => ({ text, emotion: '自然可信', speed_ratio: 1, volume_ratio: 1, pitch_ratio: 1, pause_after_ms: 450, emphasis: '' }))
}
function classify(text: string): [string, string, string] {
  if (/餐|吃|食阁|咖啡|饭|餐饮|外卖/.test(text)) return ['餐饮/食阁','餐厅、咖啡馆、食阁、外卖店和真实就餐环境','food']
  if (/交通|地铁|捷运|公交|通勤|主干道|车站|MRT|LRT/i.test(text)) return ['交通出勤','MRT/LRT、公交站、主干道、通勤人流','traffic']
  if (/医疗|诊所|药房|看病|买药|医院/.test(text)) return ['医疗/诊所/药房','社区诊所、药房、医疗配套入口','medical']
  if (/学校|教育|国际学校|孩子|上学/.test(text)) return ['教育/学校','学校周边、校车、家庭教育生活场景','education']
  if (/户型|采光|阳台|卧室|客厅|厨房|装修|空间/.test(text)) return ['户型/室内','客厅、厨房、卧室、阳台、采光、空间动线','interior']
  if (/投资|出租|租客|转售|回报|持有|成交|带看/.test(text)) return ['成交/带看/租客','租客看房、成交咨询、社区人流、楼盘外立面','deal']
  if (/超市|商场|生活|配套|便利|华人/.test(text)) return ['生活配套','超市、便利店、商场、街区生活、药房餐饮','life']
  return ['房产/楼盘素材','楼盘外立面、社区环境、真实街区、样板间过渡','property']
}
function buildShots(segments: VoiceSegment[]): Shot[] {
  return segments.map((seg, i) => { const [category, visual, scene_type] = classify(seg.text); const duration = Math.max(3, Math.min(6, Math.ceil(seg.text.length / 9))); return { narration: seg.text, visual, category, scene_type, duration, motion: i % 2 === 0 ? 'stable_slow_push_in' : 'stable_slow_pan', transition: SAFE_TRANSITION, negative_prompt: 'white flash, black flash, cut, hard cut, jump cut, smooth_cut, pull_out, strobe, flicker, wipe, glitch, watermark, readable text', prompt: `${visual}，真实马来西亚城市生活纪录片质感，竖屏9:16，稳定镜头，无字幕，无logo，无可读招牌。必须对应口播：${seg.text}。Transition lock: only smooth dissolve, no flash, no cut.` } })
}
function words(s: string) { return s.split(/[,，\s/|]+/).map(x => x.trim()).filter(Boolean) }

function App() {
  const saved = safeJson<any>(localStorage.getItem(STORAGE_KEY), {})
  const [step, setStep] = useState<StepKey>(saved.step || 1)
  const [tab, setTab] = useState(saved.tab || 'main')
  const [topic, setTopic] = useState(saved.topic || '马来西亚房产生活配套介绍')
  const [audience, setAudience] = useState(saved.audience || '准备了解马来西亚房产的华人客户')
  const [keywords, setKeywords] = useState(saved.keywords || '生活配套, 交通出勤, 医疗药房, 餐饮食阁, 户型采光')
  const [forbiddenWords, setForbiddenWords] = useState(saved.forbiddenWords || '稳赚, 保证收益, 夸张承诺, 最低价')
  const [script, setScript] = useState(saved.script || '很多人看马来西亚房产，只盯着价格。\n但真正住进去以后，生活配套、交通出勤、医疗药房和餐饮便利，才决定这个房子好不好住。\n如果是投资，还要看租客愿不愿意长期留下来。')
  const [segments, setSegments] = useState<VoiceSegment[]>(saved.segments || splitScript(saved.script || ''))
  const [shots, setShots] = useState<Shot[]>(saved.shots || buildShots(saved.segments || splitScript(saved.script || '')))
  const [voiceUrl, setVoiceUrl] = useState(saved.voiceUrl || '')
  const [voiceDuration, setVoiceDuration] = useState<number>(saved.voiceDuration || 0)
  const [materials, setMaterials] = useState<MaterialItem[]>(saved.materials || [])
  const [accounts, setAccounts] = useState<AccountItem[]>(saved.accounts || [])
  const [uploadKind, setUploadKind] = useState('video')
  const [uploadCategory, setUploadCategory] = useState('房产/楼盘素材')
  const [uploadCity, setUploadCity] = useState(saved.uploadCity || 'Kuala Lumpur')
  const [uploadDistrict, setUploadDistrict] = useState(saved.uploadDistrict || '')
  const [uploadSource, setUploadSource] = useState(saved.uploadSource || '本地上传')
  const [uploadReusable, setUploadReusable] = useState(true)
  const [uploadTags, setUploadTags] = useState('')
  const [uploadNote, setUploadNote] = useState('')
  const [jobId, setJobId] = useState(saved.jobId || '')
  const [videoUrl, setVideoUrl] = useState(saved.videoUrl || '')
  const [accountText, setAccountText] = useState(saved.accountText || 'platform,handle,name,url,city,industry,follower_count\ndouyin,example,示例账号,https://example.com,Kuala Lumpur,real_estate,10000')
  const [openclawUrl, setOpenclawUrl] = useState(saved.openclawUrl || '')
  const [obsidianTitle, setObsidianTitle] = useState(saved.obsidianTitle || '马来西亚房产内容复盘')
  const [log, setLog] = useState('准备就绪')
  const [busy, setBusy] = useState('')
  const totalDuration = useMemo(() => shots.reduce((a, b) => a + Number(b.duration || 0), 0), [shots])
  const persist = (patch: Record<string, unknown> = {}) => localStorage.setItem(STORAGE_KEY, JSON.stringify({ step, tab, topic, audience, keywords, forbiddenWords, script, segments, shots, voiceUrl, voiceDuration, materials, accounts, uploadCity, uploadDistrict, uploadSource, jobId, videoUrl, accountText, openclawUrl, obsidianTitle, ...patch }))
  useEffect(() => { persist() }, [])
  function setStepAndSave(next: StepKey) { setStep(next); persist({ step: next }) }
  function resetFromScript() { const nextSeg = splitScript(script); const nextShots = buildShots(nextSeg); setSegments(nextSeg); setShots(nextShots); setLog(`已按口播拆成 ${nextSeg.length} 句，并生成对应镜头。`); persist({ segments: nextSeg, shots: nextShots }) }
  function updateSegment(i: number, patch: Partial<VoiceSegment>) { const next = segments.map((s, idx) => idx === i ? { ...s, ...patch } : s); setSegments(next); persist({ segments: next }) }
  function updateShot(i: number, patch: Partial<Shot>) { const next = shots.map((s, idx) => idx === i ? { ...s, ...patch, transition: patch.transition || s.transition || SAFE_TRANSITION } : s); setShots(next); persist({ shots: next }) }
  async function run<T>(name: string, fn: () => Promise<T>) { setBusy(name); try { const data = await fn(); setLog(typeof data === 'string' ? data : JSON.stringify(data, null, 2).slice(0, 5000)); return data } catch (e: any) { setLog(`${name}失败：${e.message}`) } finally { setBusy('') } }
  async function health() { await run('健康检查', () => apiJson('/api/video/v10-34/health', undefined, 'GET')) }
  async function saveScript() { await run('保存口播版本', () => apiJson('/api/video/full-ai/tts-first/script-version', { script_text: script, keywords: words(keywords), forbidden_words: words(forbiddenWords), voice: { segments }, note: 'v10.34 old ui native' })) }
  async function previewVoice(text: string) { const data: any = await run('生成配音试听', () => apiJson('/api/video/full-ai/tts-first/voice-preview', { script_text: text, pace: 'normal', keywords: words(keywords), forbidden_words: words(forbiddenWords), source: 'v10.34-old-ui-native' })) as any; const url = data?.audio_url || data?.file_url || data?.tts_result?.file_url || ''; setVoiceUrl(url); setVoiceDuration(Number(data?.audio_duration || data?.duration_seconds || 0)); persist({ voiceUrl: url, voiceDuration: Number(data?.audio_duration || 0) }) }
  async function planPreview() { const data: any = await run('生成镜头预览', () => apiJson('/api/video/v10-34/plan-preview', { script_text: script, manual_shot_plan: shots, keywords: words(keywords), forbidden_words: words(forbiddenWords), audio_duration: voiceDuration })) as any; if (data?.shots) { const next = data.shots.map((s: any) => ({ narration: s.narration_segment || s.clean_subtitle || '', visual: s.visual_subject || '', category: s.category || '', scene_type: s.scene_type || '', duration: Number(s.duration_seconds || 3), motion: s.motion || 'stable', transition: s.transition || SAFE_TRANSITION, prompt: s.visual_prompt || s.prompt || '', negative_prompt: s.negative_prompt || '' })); setShots(next); persist({ shots: next }) } }
  async function uploadMaterial(file: File | null) { if (!file) return; if (!uploadKind || !uploadCategory) { setLog('必须选择素材类型和分类。'); return } const fd = new FormData(); fd.append('file', file); fd.append('kind', uploadKind); fd.append('category', uploadCategory); fd.append('city', uploadCity); fd.append('district', uploadDistrict); fd.append('source', uploadSource); fd.append('reusable', String(uploadReusable)); fd.append('tags', uploadTags); fd.append('note', uploadNote); const data: any = await run('上传素材', () => apiJson('/api/video/material-library/upload', fd)); const item = data?.item || data; const next = [item, ...materials]; setMaterials(next); persist({ materials: next }) }
  async function refreshMaterials() { const data: any = await run('读取素材库', () => apiJson('/api/video/material-library', undefined, 'GET')) as any; const list = Array.isArray(data?.items) ? data.items : []; setMaterials(list); persist({ materials: list }) }
  async function importAccounts() { const data: any = await run('导入账号库并分类', () => apiJson('/api/video/accounts/import', { accounts: accountText })) as any; setAccounts(data?.items || []); persist({ accounts: data?.items || [] }) }
  async function refreshAccounts() { const data: any = await run('读取账号库', () => apiJson('/api/video/accounts', undefined, 'GET')) as any; setAccounts(data?.items || []); persist({ accounts: data?.items || [] }) }
  async function openclawCapture() { await run('OpenClaw采集', () => apiJson('/api/openclaw/capture', { url: openclawUrl, mode: 'competitor_capture', keywords: words(keywords), source: 'v10.34-ui' })) }
  async function saveObsidian() { await run('写入Obsidian', () => apiJson('/api/obsidian/note', { title: obsidianTitle, category: 'AI-VIDEO', tags: ['ai-video','v10.34', ...words(keywords).slice(0, 5)], content: `主题：${topic}\n\n口播：\n${script}\n\n镜头：\n${shots.map((s, i) => `${i + 1}. ${s.category} - ${s.visual}`).join('\n')}` })) }
  async function aiBrief() { await run('AI总控台', () => apiJson('/api/ai-control/brief', undefined, 'GET')) }
  async function startVideo() { const data: any = await run('提交生成任务', () => apiJson('/api/video/v10-34/start', { topic, audience, script_text: script, keywords: words(keywords), forbidden_words: words(forbiddenWords), script_segments: segments.map((s, i) => ({ index: i + 1, text: s.text })), segment_voice_settings: segments, manual_shot_plan: shots, shot_overrides: shots, asset_context: materials, transition_plan: shots.map(() => SAFE_TRANSITION), require_semantic_storyboard: true, require_subtitles: true, no_flash_transition: true, duration_seconds: voiceDuration, delegate_to_existing: true })); const id = data?.job_id || ''; setJobId(id); persist({ jobId: id }) }
  async function pollJob() { if (!jobId) { setLog('没有 job_id。'); return } const data: any = await run('查询任务', () => apiJson(`/api/video/v10-34/job/${encodeURIComponent(jobId)}`, undefined, 'GET')) as any; const url = data?.result_json?.final_video_url || data?.result_json?.delegated_result?.subtitled_video_url || data?.result_json?.delegated_result?.video_url || ''; setVideoUrl(url); persist({ videoUrl: url }) }
  async function approveFinal() { await run('保存最终成片资产', () => apiJson('/api/video/v10-34/approve-final', { job_id: jobId, final_video_url: videoUrl, note: 'human approved from v10.34 old ui' })) }

  return <main className="appShell">
    <section className="hero"><div><span className="eyebrow">AI-VIDEO · V10.34 A-G 完整 GitHub 结构版</span><h1>一页式智能视频增长工作台</h1><p>保留以前四步 UI：确定内容和关键词 → 逐句口播配音 → 编辑镜头和素材 → 生成成片。功能写进原生页面，不再使用外挂浮窗。</p></div><div className="statusBox"><b>后端</b><span>{apiPrefix()}</span><button onClick={health}>检查 V10.34 后端</button><button onClick={aiBrief}>AI 总控台概览</button></div></section>
    <nav className="topTabs"><button className={tab==='main'?'active':''} onClick={() => { setTab('main'); persist({tab:'main'}) }}>四步生成</button><button className={tab==='assets'?'active':''} onClick={() => { setTab('assets'); persist({tab:'assets'}) }}>素材库 V10.34C</button><button className={tab==='accounts'?'active':''} onClick={() => { setTab('accounts'); persist({tab:'accounts'}) }}>账号库 V10.34D</button><button className={tab==='openclaw'?'active':''} onClick={() => { setTab('openclaw'); persist({tab:'openclaw'}) }}>OpenClaw V10.34E</button><button className={tab==='obsidian'?'active':''} onClick={() => { setTab('obsidian'); persist({tab:'obsidian'}) }}>Obsidian V10.34F</button></nav>
    {tab === 'main' && <><nav className="stepNav">{[1,2,3,4].map(n => <button key={n} className={step===n?'active':''} onClick={() => setStepAndSave(n as StepKey)}><strong>{n}</strong><span>{n===1?'确定内容和关键词':n===2?'逐句口播配音':n===3?'编辑镜头和素材':'生成成片'}</span></button>)}</nav>
      {step === 1 && <section className="panel grid2"><div className="card"><h2>第一步：内容和关键词</h2><label>主题<input value={topic} onChange={e=>setTopic(e.target.value)} onBlur={()=>persist()} /></label><label>目标客户<input value={audience} onChange={e=>setAudience(e.target.value)} onBlur={()=>persist()} /></label><label>必须覆盖关键词<textarea value={keywords} onChange={e=>setKeywords(e.target.value)} onBlur={()=>persist()} /></label><label>禁用词 / 风险表达<textarea value={forbiddenWords} onChange={e=>setForbiddenWords(e.target.value)} onBlur={()=>persist()} /></label><button className="primary" onClick={()=>setStepAndSave(2)}>进入口播配音</button></div><div className="card softCard"><h3>语义画面规则</h3><p>说到生活配套就拍生活配套；交通出勤就拍交通；医疗药房、餐饮食阁、户型室内、成交租客都必须对应画面。</p><p>后端会强制禁止 cut / smooth_cut / flash / pull_out，并统一为 {SAFE_TRANSITION}。</p></div></section>}
      {step === 2 && <section className="panel"><div className="card"><div className="sectionHead"><div><h2>第二步：逐句口播配音</h2><p>改完口播后拆句，再试听整段或单句。</p></div><button onClick={resetFromScript}>按文案拆句并生成镜头</button></div><textarea className="scriptEditor" value={script} onChange={e=>setScript(e.target.value)} onBlur={()=>persist()} /><div className="buttonRow"><button className="primary" onClick={()=>previewVoice(script)} disabled={!!busy}>试听整段口播</button><button onClick={saveScript} disabled={!!busy}>保存口播版本</button><button onClick={()=>setStepAndSave(3)}>进入镜头素材</button></div>{voiceUrl && <div className="mediaBox"><audio controls src={voiceUrl}/><span>时长：{voiceDuration ? voiceDuration.toFixed(2) : '-'} 秒</span></div>}</div><div className="segments">{segments.map((seg,i)=><article className="segment" key={i}><header><b>第 {i+1} 句</b><button onClick={()=>previewVoice(seg.text)}>试听当前句</button></header><textarea value={seg.text} onChange={e=>updateSegment(i,{text:e.target.value})}/><div className="grid4 compact"><label>情绪<select value={seg.emotion} onChange={e=>updateSegment(i,{emotion:e.target.value})}>{EMOTIONS.map(x=><option key={x}>{x}</option>)}</select></label><label>语速 {seg.speed_ratio.toFixed(2)}x<input type="range" min="0.7" max="1.5" step="0.01" value={seg.speed_ratio} onChange={e=>updateSegment(i,{speed_ratio:Number(e.target.value)})}/></label><label>音量 {seg.volume_ratio.toFixed(2)}x<input type="range" min="0.5" max="1.8" step="0.01" value={seg.volume_ratio} onChange={e=>updateSegment(i,{volume_ratio:Number(e.target.value)})}/></label><label>停顿 {seg.pause_after_ms}ms<input type="range" min="0" max="1800" step="50" value={seg.pause_after_ms} onChange={e=>updateSegment(i,{pause_after_ms:Number(e.target.value)})}/></label></div><label>重读词<input value={seg.emphasis} onChange={e=>updateSegment(i,{emphasis:e.target.value})}/></label></article>)}</div></section>}
      {step === 3 && <section className="panel grid2"><div className="card"><div className="sectionHead"><div><h2>第三步：镜头和素材</h2><p>每句口播对应镜头；禁止无关画面和重复拉长。</p></div><div className="buttonRow"><button onClick={()=>{const next=buildShots(segments);setShots(next);persist({shots:next})}}>按口播重建</button><button onClick={planPreview}>后端验收预览</button></div></div><div className="shotList">{shots.map((shot,i)=><article className="shot" key={i}><header><b>镜头 {i+1}</b><select value={shot.category} onChange={e=>updateShot(i,{category:e.target.value})}>{CATEGORIES.map(x=><option key={x}>{x}</option>)}</select></header><label>口播<textarea value={shot.narration} onChange={e=>updateShot(i,{narration:e.target.value})}/></label><label>画面<textarea value={shot.visual} onChange={e=>updateShot(i,{visual:e.target.value})}/></label><div className="grid3 compact"><label>时长<input type="number" min="2" max="8" value={shot.duration} onChange={e=>updateShot(i,{duration:Number(e.target.value)})}/></label><label>运镜<input value={shot.motion} onChange={e=>updateShot(i,{motion:e.target.value})}/></label><label>转场<input value={SAFE_TRANSITION} readOnly /></label></div><label>AI Prompt<textarea value={shot.prompt} onChange={e=>updateShot(i,{prompt:e.target.value})}/></label><label>Negative Prompt<textarea value={shot.negative_prompt || ''} onChange={e=>updateShot(i,{negative_prompt:e.target.value})}/></label></article>)}</div></div><MaterialCard {...{uploadKind,setUploadKind,uploadCategory,setUploadCategory,uploadCity,setUploadCity,uploadDistrict,setUploadDistrict,uploadSource,setUploadSource,uploadReusable,setUploadReusable,uploadTags,setUploadTags,uploadNote,setUploadNote,uploadMaterial,refreshMaterials,materials,goNext:()=>setStepAndSave(4)}} /></section>}
      {step === 4 && <section className="panel grid2"><div className="card"><h2>第四步：生成成片</h2><p>总镜头时长约 {totalDuration.toFixed(1)} 秒。生成时传口播、逐句配音、镜头、素材库和强制转场规则。</p><div className="buttonRow"><button className="primary" onClick={startVideo} disabled={!!busy}>提交生成任务</button><button onClick={pollJob} disabled={!!busy || !jobId}>查询任务</button><button onClick={approveFinal} disabled={!jobId || !videoUrl}>保存最终成片资产</button></div><label>Job ID<input value={jobId} onChange={e=>setJobId(e.target.value)}/></label>{videoUrl && <div className="videoBox"><video controls src={videoUrl}/><a href={videoUrl} target="_blank">下载视频</a></div>}</div><div className="card softCard"><h3>V10.34A 成片规则</h3><p>禁止 cut / smooth_cut / flash / pull_out；强制 {SAFE_TRANSITION}；后端保存每个 FAL shot 的 prompt、negative_prompt、scene_type、narration_segment、duration、job_id。</p><p>completed 状态会被拦截：没有最终视频 URL 或关键元数据时，不允许假完成。</p></div></section>}
    </>}
    {tab === 'assets' && <section className="panel grid2"><MaterialCard {...{uploadKind,setUploadKind,uploadCategory,setUploadCategory,uploadCity,setUploadCity,uploadDistrict,setUploadDistrict,uploadSource,setUploadSource,uploadReusable,setUploadReusable,uploadTags,setUploadTags,uploadNote,setUploadNote,uploadMaterial,refreshMaterials,materials,goNext:()=>setTab('main')}} /><div className="card"><h2>素材库要求</h2><p>类型、分类必须选择；城市、区域、来源、是否复用、备注都会入库。素材会参与镜头匹配。</p></div></section>}
    {tab === 'accounts' && <section className="panel grid2"><div className="card"><h2>账号库导入 + DeepSeek 分类</h2><label>CSV / 每行URL / JSON<textarea className="scriptEditor" value={accountText} onChange={e=>setAccountText(e.target.value)} onBlur={()=>persist({accountText})}/></label><div className="buttonRow"><button className="primary" onClick={importAccounts}>导入并分类</button><button onClick={refreshAccounts}>刷新账号库</button></div></div><div className="card"><h3>账号列表</h3><div className="materialList">{accounts.map((a,i)=><div className="material" key={a.account_id || i}><b>{a.name || a.handle || a.url}</b><span>{a.platform || '-'} · {a.category || '-'} · {a.value_level || '-'}</span></div>)}</div></div></section>}
    {tab === 'openclaw' && <section className="panel grid2"><div className="card"><h2>OpenClaw 真采集入口</h2><p>后端如果配置 OPENCLAW_CAPTURE_URL，会直接调用；没配置时会存任务，给 OpenClaw Agent 拉取执行。</p><label>采集目标 URL / 账号<input value={openclawUrl} onChange={e=>setOpenclawUrl(e.target.value)} onBlur={()=>persist({openclawUrl})}/></label><button className="primary" onClick={openclawCapture}>提交采集任务</button></div><div className="card softCard"><h3>采集用途</h3><p>竞品账号、爆款标题、评论线索、素材线索可以进入账号库、素材库和 Obsidian。</p></div></section>}
    {tab === 'obsidian' && <section className="panel grid2"><div className="card"><h2>Obsidian 生长</h2><label>笔记标题<input value={obsidianTitle} onChange={e=>setObsidianTitle(e.target.value)} onBlur={()=>persist({obsidianTitle})}/></label><button className="primary" onClick={saveObsidian}>把当前内容写入 Obsidian</button></div><div className="card softCard"><h3>沉淀内容</h3><p>主题、口播、镜头、素材、账号分类、AI 总控台建议都会变成 Markdown 笔记。</p></div></section>}
    <section className="logPanel"><b>日志 / 返回结果</b><pre>{busy ? `${busy}中...\n\n${log}` : log}</pre></section>
  </main>
}

function MaterialCard(props: any) {
  const { uploadKind,setUploadKind,uploadCategory,setUploadCategory,uploadCity,setUploadCity,uploadDistrict,setUploadDistrict,uploadSource,setUploadSource,uploadReusable,setUploadReusable,uploadTags,setUploadTags,uploadNote,setUploadNote,uploadMaterial,refreshMaterials,materials,goNext } = props
  return <div className="card"><h2>素材上传 / 必选分类</h2><div className="grid2 compact"><label>素材类型<select value={uploadKind} onChange={(e:any)=>setUploadKind(e.target.value)}>{KIND_OPTIONS.map(([v,l])=><option key={v} value={v}>{l}</option>)}</select></label><label>分类<select value={uploadCategory} onChange={(e:any)=>setUploadCategory(e.target.value)}>{CATEGORIES.map(x=><option key={x}>{x}</option>)}</select></label></div><div className="grid3 compact"><label>城市<input value={uploadCity} onChange={(e:any)=>setUploadCity(e.target.value)}/></label><label>区域<input value={uploadDistrict} onChange={(e:any)=>setUploadDistrict(e.target.value)}/></label><label>来源<input value={uploadSource} onChange={(e:any)=>setUploadSource(e.target.value)}/></label></div><label>是否可复用<select value={uploadReusable?'yes':'no'} onChange={(e:any)=>setUploadReusable(e.target.value==='yes')}><option value="yes">可复用</option><option value="no">不可复用</option></select></label><label>标签<input value={uploadTags} onChange={(e:any)=>setUploadTags(e.target.value)} placeholder="楼盘, 生活, 交通" /></label><label>备注<textarea value={uploadNote} onChange={(e:any)=>setUploadNote(e.target.value)} /></label><label className="dropBox">拖拽或选择文件<input type="file" onChange={(e:any)=>uploadMaterial(e.target.files?.[0] || null)} /></label><div className="buttonRow"><button onClick={refreshMaterials}>刷新素材库</button><button onClick={goNext}>返回/下一步</button></div><div className="materialList">{materials.map((m:MaterialItem,i:number)=><div className="material" key={m.asset_id || i}><b>{m.original_name || m.filename || `素材 ${i+1}`}</b><span>{m.kind || '-'} · {m.category || '-'} · {m.city || ''}{m.district ? '/' + m.district : ''}</span></div>)}</div></div>
}

export default App
