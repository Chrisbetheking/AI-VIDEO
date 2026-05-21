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
  PublishPackageResponse,
  TTSResponse,
  TTSVoice,
  apiGet,
  apiPost,
  uploadAssets
} from './api'

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="field"><span>{label}</span>{children}</label>
}

function Alert({ text }: { text?: string }) {
  if (!text) return null
  return <div className="alert">{text}</div>
}

export default function App() {
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [health, setHealth] = useState<any>(null)

  const [industry, setIndustry] = useState('企业服务')
  const [audience, setAudience] = useState('老板、企业负责人、需要获客的本地商家')
  const [sellingPoints, setSellingPoints] = useState('AI 自动生成文案、配音、剪辑、封面和发布包，降低短视频生产成本')
  const [style, setStyle] = useState('老板口播、真实可信、强转化、短平快')
  const [duration, setDuration] = useState(35)

  const [assets, setAssets] = useState<AssetItem[]>([])
  const [selectedAssetId, setSelectedAssetId] = useState('')
  const [sourceUrl, setSourceUrl] = useState('')
  const [manualText, setManualText] = useState('')
  const [extract, setExtract] = useState<InspirationExtractResponse | null>(null)

  const [copy, setCopy] = useState<GeneratedCopy | null>(null)
  const [editPlan, setEditPlan] = useState<EditPlanResponse | null>(null)
  const [voices, setVoices] = useState<TTSVoice[]>([])
  const [voice, setVoice] = useState('')
  const [audio, setAudio] = useState<TTSResponse | null>(null)
  const [video, setVideo] = useState<ComposeResponse | null>(null)
  const [cover, setCover] = useState<CoverResponse | null>(null)
  const [publishPackage, setPublishPackage] = useState<PublishPackageResponse | null>(null)
  const [ad, setAd] = useState<AdAnalysisResponse | null>(null)

  const referenceText = useMemo(() => extract?.transcript || manualText, [extract, manualText])

  const safeTags = Array.isArray(copy?.tags) ? copy!.tags : []
  const safeShots = Array.isArray(copy?.shots) ? copy!.shots : []
  const safeExtractWarnings = Array.isArray(extract?.warnings) ? extract!.warnings : []
  const safeTimeline = Array.isArray(editPlan?.timeline) ? editPlan!.timeline : []
  const safeBroll = Array.isArray(editPlan?.broll_keywords) ? editPlan!.broll_keywords : []
  const safeTips = Array.isArray(ad?.optimization_tips) ? ad!.optimization_tips : []
  const safeChecklist = Array.isArray(publishPackage?.checklist) ? publishPackage!.checklist : []

  async function run<T>(label: string, fn: () => Promise<T>) {
    setBusy(label); setError('')
    try { return await fn() } catch (e: any) { setError(e.message || String(e)); throw e } finally { setBusy('') }
  }

  useEffect(() => {
    apiGet('/api/health').then(setHealth).catch(() => null)
    apiGet<TTSVoice[]>('/api/tts/voices').then(v => { const list = Array.isArray(v) ? v : []; setVoices(list); setVoice(list[0]?.id || '') }).catch(() => null)
    apiGet<AssetItem[]>('/api/assets').then(v => setAssets(Array.isArray(v) ? v : [])).catch(() => null)
  }, [])

  async function handleUpload(files: FileList | null) {
    if (!files?.length) return
    const res = await run('上传素材', () => uploadAssets(files))
    setAssets(prev => [...res!, ...prev])
    if (!selectedAssetId && res?.[0]) setSelectedAssetId(res[0].id)
  }

  async function extractVideo() {
    const res = await run('同行采集与豆包拆解', () => apiPost<InspirationExtractResponse>('/api/inspiration/extract', {
      asset_id: selectedAssetId || undefined,
      source_url: sourceUrl,
      manual_text: manualText
    }))
    setExtract(res!)
  }

  async function rewrite() {
    const res = await run('DeepSeek 原创改写', () => apiPost<GeneratedCopy>('/api/rewrite-from-inspiration', {
      reference_text: referenceText || '请根据业务信息生成原创老板口播文案。',
      industry,
      audience,
      selling_points: sellingPoints,
      style,
      duration_seconds: duration
    }))
    setCopy(res!)
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

  async function planEdit() {
    if (!copy) return
    const res = await run('生成深度剪辑方案', () => apiPost<EditPlanResponse>('/api/edit-plan', {
      title: copy.title,
      script: copy.script,
      duration_seconds: duration,
      asset_summary: assets.map(a => `${a.kind}:${a.original_name}`).join('；')
    }))
    setEditPlan(res!)
  }

  async function makeTTS() {
    if (!copy) return
    const res = await run('生成豆包配音', () => apiPost<TTSResponse>('/api/tts', { text: copy.script, voice, rate: '+0%' }))
    setAudio(res!)
  }

  async function compose() {
    if (!copy) return
    const res = await run('合成 9:16 视频', () => apiPost<ComposeResponse>('/api/compose-video', {
      title: copy.title,
      script: copy.script,
      asset_ids: assets.slice(0, 8).map(a => a.id),
      audio_file_name: audio?.file_name,
      duration_seconds: duration,
      voice
    }))
    setVideo(res!)
  }

  async function makeCover() {
    if (!copy) return
    const res = await run('生成封面', () => apiPost<CoverResponse>('/api/cover', {
      title: copy.title,
      hook: copy.hook,
      subtitle: sellingPoints,
      brand: industry
    }))
    setCover(res!)
  }

  async function makePackage() {
    if (!copy) return
    const res = await run('生成发布包', () => apiPost<PublishPackageResponse>('/api/publish-package', {
      title: copy.title,
      description: copy.description,
      tags: copy.tags,
      video_file_name: video?.video_name,
      cover_file_name: cover?.cover_name
    }))
    setPublishPackage(res!)
  }

  async function analyzeAd() {
    if (!copy) return
    const res = await run('投流分析', () => apiPost<AdAnalysisResponse>('/api/ad-analysis', {
      title: copy.title,
      script: copy.script,
      industry,
      budget: 300,
      objective: '线索/咨询'
    }))
    setAd(res!)
  }

  return <main>
    <header className="hero">
      <div><p className="eyebrow">AI-VIDEO 正式版</p><h1>竞品拆解 → 原创文案 → 豆包配音 → 剪辑封面 → 发布包</h1></div>
      <div className="status"><b>API</b><span>{health?.ok ? '已连接' : '未连接'}</span><small>{health?.tts_provider || ''} · {health?.ark_video_model || ''}</small></div>
    </header>

    <Alert text={busy ? `处理中：${busy}...` : ''} />
    <Alert text={error} />

    <section className="grid two">
      <div className="card">
        <h2>1. 业务信息</h2>
        <Field label="行业"><input value={industry} onChange={e => setIndustry(e.target.value)} /></Field>
        <Field label="目标客户"><input value={audience} onChange={e => setAudience(e.target.value)} /></Field>
        <Field label="核心卖点"><textarea value={sellingPoints} onChange={e => setSellingPoints(e.target.value)} /></Field>
        <Field label="风格"><input value={style} onChange={e => setStyle(e.target.value)} /></Field>
        <Field label="视频时长"><input type="number" value={duration} onChange={e => setDuration(Number(e.target.value || 35))} /></Field>
      </div>

      <div className="card">
        <h2>2. 同行采集 / 竞品拆解</h2>
        <Field label="上传参考视频或素材"><input type="file" multiple accept="video/*,image/*" onChange={e => handleUpload(e.target.files)} /></Field>
        <Field label="选择参考视频"><select value={selectedAssetId} onChange={e => setSelectedAssetId(e.target.value)}><option value="">不选择</option>{assets.map(a => <option key={a.id} value={a.id}>{a.kind} · {a.original_name}</option>)}</select></Field>
        <Field label="抖音分享口令 / 视频 URL（可选）"><input value={sourceUrl} onChange={e => setSourceUrl(e.target.value)} placeholder="可直接粘贴抖音复制链接整段；系统会自动提取链接和钩子文案" /></Field>
        <Field label="手动粘贴竞品文案（可选）"><textarea value={manualText} onChange={e => setManualText(e.target.value)} placeholder="只有文案时粘这里；抖音分享整段也可以粘到上面的口令框" /></Field>
        <button onClick={extractVideo}>采集/拆解同行内容</button>
      </div>
    </section>

    {extract && <section className="card"><h2>提取结果</h2><p><b>状态：</b>{extract.status}</p><p>{extract.summary}</p><pre>{extract.transcript || '暂无 transcript'}</pre><p className="small-note">提示：抖音分享口令会优先提取其中的标题、话题和短链；若要分析画面节奏，请上传下载后的 MP4。</p>{safeExtractWarnings.map(w => <Alert key={w} text={w} />)}</section>}

    <section className="card">
      <h2>3. 文案生成与原创改写</h2>
      <div className="actions"><button onClick={generateDirectCopy}>直接生成文案</button><button onClick={rewrite}>基于参考原创改写</button><button onClick={planEdit} disabled={!copy}>生成深度剪辑方案</button></div>
      {copy && <div className="result"><h3>{copy.title}</h3><p className="hook">{copy.hook}</p><textarea value={copy.script} onChange={e => setCopy({ ...copy, script: e.target.value })} /><p>{copy.description}</p><div className="chips">{safeTags.map(t => <span key={t}>#{t}</span>)}</div><details><summary>镜头建议</summary><ul>{safeShots.map(s => <li key={s}>{s}</li>)}</ul></details></div>}
    </section>

    {editPlan && <section className="card"><h2>4. 深度剪辑方案</h2><p>{editPlan.rhythm}</p><ul>{safeTimeline.map(x => <li key={x}>{x}</li>)}</ul><div className="chips">{safeBroll.map(x => <span key={x}>{x}</span>)}</div><p><b>字幕：</b>{editPlan.subtitle_style}</p><p><b>音乐：</b>{editPlan.music_style}</p></section>}

    <section className="grid two">
      <div className="card">
        <h2>5. 豆包配音</h2>
        <Field label="云端音色"><select value={voice} onChange={e => setVoice(e.target.value)}>{voices.map(v => <option key={v.id} value={v.id}>{v.name} · {v.id}</option>)}</select></Field>
        <button onClick={makeTTS} disabled={!copy}>生成配音</button>
        {audio && <><audio controls src={audio.file_url} /><p>{audio.duration_seconds.toFixed(1)} 秒</p><Alert text={audio.warning} /></>}
      </div>

      <div className="card">
        <h2>6. 视频合成与封面</h2>
        <div className="actions"><button onClick={compose} disabled={!copy}>合成 9:16 MP4</button><button onClick={makeCover} disabled={!copy}>生成封面</button></div>
        {video && <video controls src={video.video_url} />}
        {cover && <img className="cover" src={cover.cover_url} />}
      </div>
    </section>

    <section className="grid two">
      <div className="card"><h2>7. 投流分析</h2><button onClick={analyzeAd} disabled={!copy}>刷新投流分析</button>{ad && <div><h3>{ad.decision} · 置信度 {(ad.confidence * 100).toFixed(0)}%</h3><p>{ad.suggested_budget}</p><ul>{safeTips.map(t => <li key={t}>{t}</li>)}</ul></div>}</div>
      <div className="card"><h2>8. 发布包</h2><button onClick={makePackage} disabled={!copy}>生成发布包 ZIP</button>{publishPackage && <div><a className="download" href={publishPackage.package_url}>下载发布包</a><ul>{safeChecklist.map(i => <li key={i}>{i}</li>)}</ul></div>}</div>
    </section>
  </main>
}
