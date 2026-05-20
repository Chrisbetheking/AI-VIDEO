import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { Activity, Bot, CheckCircle2, Clapperboard, Cloud, Database, Download, Loader2, Megaphone, Mic2, Play, Upload, Wand2 } from 'lucide-react'
import { apiGet, apiPost, uploadAssets, API_BASE, type AdAnalysisResponse, type AssetItem, type ComposeResponse, type GeneratedCopy, type KnowledgeItem, type TTSResponse } from './api'

type StepKey = 'copy' | 'tts' | 'video' | 'ad'

interface FormState {
  apiKey: string
  topic: string
  industry: string
  audience: string
  sellingPoints: string
  style: string
  duration: number
  voice: string
  budget: number
}

const defaultForm: FormState = {
  apiKey: '',
  topic: '老板口播介绍公司服务，突出真实案例和可咨询转化',
  industry: '企业服务',
  audience: '本地企业老板、个体工商户、想做短视频获客的人',
  sellingPoints: '自动生成文案、AI配音、素材自动剪辑、实时投流分析、节省人工时间',
  style: '老板口播、真实、有信任感、短平快、强转化',
  duration: 35,
  voice: 'zh-CN-YunxiNeural',
  budget: 300,
}

const steps: Array<{ key: StepKey; label: string; desc: string; icon: ReactNode }> = [
  { key: 'copy', label: '文案', desc: 'DeepSeek 生成', icon: <Bot size={18} /> },
  { key: 'tts', label: '配音', desc: '云端 TTS', icon: <Mic2 size={18} /> },
  { key: 'video', label: '成片', desc: 'FFmpeg 合成', icon: <Clapperboard size={18} /> },
  { key: 'ad', label: '投流', desc: '实时分析', icon: <Megaphone size={18} /> },
]

function cx(...classes: Array<string | false | undefined>) {
  return classes.filter(Boolean).join(' ')
}

function fullUrl(url?: string) {
  if (!url) return ''
  if (url.startsWith('http')) return url
  return `${API_BASE}${url}`
}

function Card(props: { title: string; icon?: ReactNode; children: ReactNode; right?: ReactNode }) {
  return (
    <section className="card">
      <div className="cardHeader">
        <div className="cardTitle">
          {props.icon}
          <span>{props.title}</span>
        </div>
        {props.right}
      </div>
      {props.children}
    </section>
  )
}

function Field(props: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="field">
      <span>{props.label}</span>
      {props.children}
      {props.hint && <small>{props.hint}</small>}
    </label>
  )
}

export default function App() {
  const [form, setForm] = useState<FormState>(defaultForm)
  const [copy, setCopy] = useState<GeneratedCopy | null>(null)
  const [assets, setAssets] = useState<AssetItem[]>([])
  const [selectedAssetIds, setSelectedAssetIds] = useState<string[]>([])
  const [knowledge, setKnowledge] = useState<KnowledgeItem[]>([])
  const [kbTitle, setKbTitle] = useState('老板口播参考')
  const [kbContent, setKbContent] = useState('')
  const [tts, setTts] = useState<TTSResponse | null>(null)
  const [video, setVideo] = useState<ComposeResponse | null>(null)
  const [analysis, setAnalysis] = useState<AdAnalysisResponse | null>(null)
  const [busy, setBusy] = useState<string>('')
  const [logs, setLogs] = useState<string[]>([])
  const [autoRefresh, setAutoRefresh] = useState(true)

  const script = copy?.script || ''
  const completed = useMemo(() => ({ copy: !!copy, tts: !!tts, video: !!video, ad: !!analysis }), [copy, tts, video, analysis])

  function log(message: string) {
    const now = new Date().toLocaleTimeString()
    setLogs(prev => [`[${now}] ${message}`, ...prev].slice(0, 12))
  }

  function update<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm(prev => ({ ...prev, [key]: value }))
  }

  async function refreshAssets() {
    try {
      const data = await apiGet<AssetItem[]>('/api/assets')
      setAssets(data)
    } catch (err) {
      log(`素材列表读取失败：${String(err)}`)
    }
  }

  async function refreshKnowledge() {
    try {
      const data = await apiGet<KnowledgeItem[]>('/api/knowledge')
      setKnowledge(data)
    } catch (err) {
      log(`知识库读取失败：${String(err)}`)
    }
  }

  useEffect(() => {
    refreshAssets()
    refreshKnowledge()
  }, [])

  useEffect(() => {
    if (!autoRefresh || !copy) return
    const timer = window.setInterval(() => {
      runAdAnalysis(false).catch(() => undefined)
    }, 8000)
    return () => window.clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoRefresh, copy, form.budget])

  async function addKnowledge() {
    if (!kbContent.trim()) return
    setBusy('knowledge')
    try {
      const item = await apiPost<KnowledgeItem>('/api/knowledge', {
        title: kbTitle || '未命名文案',
        content: kbContent,
        tags: ['参考文案']
      })
      setKnowledge(prev => [item, ...prev])
      setKbContent('')
      log('已加入文案知识库，可用于类比生成。')
    } catch (err) {
      alert(`添加知识库失败：${String(err)}`)
    } finally {
      setBusy('')
    }
  }

  async function handleUpload(files: FileList | null) {
    if (!files?.length) return
    setBusy('upload')
    try {
      const uploaded = await uploadAssets(files)
      setAssets(prev => [...uploaded, ...prev])
      setSelectedAssetIds(prev => [...uploaded.map(x => x.id), ...prev])
      log(`已上传 ${uploaded.length} 个素材。`)
    } catch (err) {
      alert(`上传失败：${String(err)}`)
    } finally {
      setBusy('')
    }
  }

  async function generateCopy() {
    setBusy('copy')
    try {
      log('开始调用 DeepSeek 生成文案...')
      const result = await apiPost<GeneratedCopy>('/api/generate-copy', {
        topic: form.topic,
        industry: form.industry,
        audience: form.audience,
        selling_points: form.sellingPoints,
        style: form.style,
        duration_seconds: form.duration,
        api_key: form.apiKey || undefined,
      })
      setCopy(result)
      setTts(null)
      setVideo(null)
      setAnalysis(null)
      log('文案生成完成。')
    } catch (err) {
      alert(`文案生成失败：${String(err)}`)
      log(`文案生成失败：${String(err)}`)
    } finally {
      setBusy('')
    }
  }

  async function generateTts() {
    if (!copy?.script) return alert('请先生成或填写文案')
    setBusy('tts')
    try {
      log('开始生成云端配音...')
      const result = await apiPost<TTSResponse>('/api/tts', {
        text: copy.script,
        voice: form.voice,
        rate: '+0%'
      })
      setTts(result)
      if (result.warning) log(result.warning)
      log('配音生成完成。')
    } catch (err) {
      alert(`配音失败：${String(err)}`)
      log(`配音失败：${String(err)}`)
    } finally {
      setBusy('')
    }
  }

  async function composeVideo() {
    if (!copy?.script) return alert('请先生成或填写文案')
    setBusy('video')
    try {
      log('开始合成 9:16 视频...')
      const result = await apiPost<ComposeResponse>('/api/compose-video', {
        title: copy.title,
        script: copy.script,
        asset_ids: selectedAssetIds,
        audio_file_name: tts?.file_name,
        duration_seconds: form.duration,
        voice: form.voice,
        rate: '+0%'
      })
      setVideo(result)
      result.warnings.forEach(log)
      log('视频合成完成。')
    } catch (err) {
      alert(`视频合成失败：${String(err)}`)
      log(`视频合成失败：${String(err)}`)
    } finally {
      setBusy('')
    }
  }

  async function runAdAnalysis(showLog = true) {
    if (!copy?.script) return
    if (showLog) {
      setBusy('ad')
      log('刷新投流分析数据...')
    }
    try {
      const result = await apiPost<AdAnalysisResponse>('/api/ad-analysis', {
        title: copy.title,
        script: copy.script,
        budget: form.budget,
        objective: '线索/咨询',
        industry: form.industry
      })
      setAnalysis(result)
      if (showLog) log('投流分析已更新。')
    } catch (err) {
      if (showLog) alert(`投流分析失败：${String(err)}`)
    } finally {
      if (showLog) setBusy('')
    }
  }

  async function oneClick() {
    await generateCopy()
  }

  async function continueAfterCopy() {
    await generateTts()
    await composeVideo()
    await runAdAnalysis(true)
  }

  function toggleAsset(id: string) {
    setSelectedAssetIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id])
  }

  return (
    <div className="app">
      <header className="hero">
        <div>
          <div className="badge"><Cloud size={16} /> DeepSeek + 云端 TTS + FFmpeg · 9:16</div>
          <h1>短视频 AI 自动化 Web Demo</h1>
          <p>文案知识库、AI 配音、自动剪辑、成片输出、抖音投流分析，一套流程给老板现场演示。</p>
        </div>
        <div className="heroActions">
          <button className="primary" onClick={oneClick} disabled={!!busy}>
            {busy === 'copy' ? <Loader2 className="spin" size={18} /> : <Wand2 size={18} />} 生成文案
          </button>
          <button className="secondary" onClick={continueAfterCopy} disabled={!!busy || !copy}>
            {busy && busy !== 'copy' ? <Loader2 className="spin" size={18} /> : <Play size={18} />} 继续生成配音+视频+投流
          </button>
        </div>
      </header>

      <div className="stepper">
        {steps.map(step => (
          <div key={step.key} className={cx('step', completed[step.key] && 'done')}>
            <div className="stepIcon">{completed[step.key] ? <CheckCircle2 size={18} /> : step.icon}</div>
            <div><b>{step.label}</b><small>{step.desc}</small></div>
          </div>
        ))}
      </div>

      <main className="grid">
        <div className="left">
          <Card title="1. 基础设置" icon={<Wand2 size={18} />}>
            <div className="twoCols">
              <Field label="DeepSeek API Key（可选）" hint="正式部署建议写在后端 .env，这里只为现场临时测试。">
                <input type="password" placeholder="sk-...（后端已配置可不填）" value={form.apiKey} onChange={e => update('apiKey', e.target.value)} />
              </Field>
              <Field label="视频时长">
                <input type="number" min={10} max={180} value={form.duration} onChange={e => update('duration', Number(e.target.value))} />
              </Field>
            </div>
            <Field label="主题">
              <textarea rows={2} value={form.topic} onChange={e => update('topic', e.target.value)} />
            </Field>
            <div className="twoCols">
              <Field label="行业">
                <input value={form.industry} onChange={e => update('industry', e.target.value)} />
              </Field>
              <Field label="目标人群">
                <input value={form.audience} onChange={e => update('audience', e.target.value)} />
              </Field>
            </div>
            <Field label="核心卖点">
              <textarea rows={3} value={form.sellingPoints} onChange={e => update('sellingPoints', e.target.value)} />
            </Field>
            <Field label="文案风格">
              <input value={form.style} onChange={e => update('style', e.target.value)} />
            </Field>
            <div className="actions">
              <button className="primary" onClick={generateCopy} disabled={!!busy}>{busy === 'copy' ? <Loader2 className="spin" size={18} /> : <Bot size={18} />} 生成/重写文案</button>
              <button className="secondary" onClick={() => setCopy({
                title: 'AI短视频系统怎么帮老板省时间',
                hook: '老板们，别再一条视频一条视频手工剪了。',
                script: '老板们，别再一条视频一条视频手工剪了。现在这套系统可以先根据你的行业和案例自动生成口播文案，再用云端配音生成声音，然后自动匹配素材、加字幕、合成九比十六的视频。发布后还可以看完播率、点击率和转化数据，判断这条视频到底要不要投流。你只需要补充真实案例和素材，剩下的流程都可以自动跑起来。想先看你的行业适不适合，可以直接私信我。',
                description: '一套适合老板演示的 AI 短视频自动化流程。',
                tags: ['AI短视频', '自动剪辑', '老板口播', '抖音投流'],
                shots: ['老板正面口播', '系统界面录屏', '素材自动合成', '投流数据面板'],
                kb_refs: ['默认演示文案']
              })}>使用演示文案</button>
            </div>
          </Card>

          <Card title="2. 文案知识库" icon={<Database size={18} />} right={<span className="pill">{knowledge.length} 条</span>}>
            <Field label="参考文案标题">
              <input value={kbTitle} onChange={e => setKbTitle(e.target.value)} />
            </Field>
            <Field label="粘贴历史爆款/老板常用文案">
              <textarea rows={5} placeholder="把他们之前写过的文案、标题、口播稿粘进来。生成时会类比风格，但不会照抄。" value={kbContent} onChange={e => setKbContent(e.target.value)} />
            </Field>
            <div className="actions">
              <button className="secondary" onClick={addKnowledge} disabled={!!busy || !kbContent.trim()}>{busy === 'knowledge' ? <Loader2 className="spin" size={18} /> : <Database size={18} />} 加入知识库</button>
              <button className="ghost" onClick={refreshKnowledge}>刷新</button>
            </div>
            <div className="kbList">
              {knowledge.slice(0, 4).map(item => <div className="kbItem" key={item.id}><b>{item.title}</b><p>{item.content.slice(0, 90)}...</p></div>)}
            </div>
          </Card>

          <Card title="3. 素材管理" icon={<Upload size={18} />} right={<span className="pill">已选 {selectedAssetIds.length}</span>}>
            <div className="uploadBox">
              <input type="file" accept="image/*,video/*" multiple onChange={e => handleUpload(e.target.files)} />
              <Upload size={22} />
              <span>上传图片/视频素材（产品、环境、老板出镜、案例）</span>
            </div>
            <div className="assetGrid">
              {assets.map(asset => (
                <button key={asset.id} className={cx('asset', selectedAssetIds.includes(asset.id) && 'selected')} onClick={() => toggleAsset(asset.id)}>
                  {asset.kind === 'image' ? <img src={fullUrl(asset.url)} /> : <video src={fullUrl(asset.url)} muted />}
                  <span>{asset.kind === 'image' ? '图片' : '视频'} · {Math.round(asset.size_bytes / 1024)}KB</span>
                </button>
              ))}
              {!assets.length && <div className="empty">不上传也能生成默认背景视频，方便先演示流程。</div>}
            </div>
          </Card>
        </div>

        <div className="right">
          <Card title="生成文案" icon={<Bot size={18} />}>
            {copy ? (
              <div className="copyBox">
                <Field label="标题">
                  <input value={copy.title} onChange={e => setCopy({ ...copy, title: e.target.value })} />
                </Field>
                <Field label="前 3 秒钩子">
                  <input value={copy.hook} onChange={e => setCopy({ ...copy, hook: e.target.value })} />
                </Field>
                <Field label="口播稿（可编辑后再配音/合成）">
                  <textarea rows={10} value={copy.script} onChange={e => setCopy({ ...copy, script: e.target.value })} />
                </Field>
                <div className="tagRow">{copy.tags.map(tag => <span key={tag}>#{tag}</span>)}</div>
                <details>
                  <summary>镜头建议</summary>
                  <ol>{copy.shots.map((shot, idx) => <li key={idx}>{shot}</li>)}</ol>
                </details>
              </div>
            ) : <div className="empty tall">点击“生成文案”后，这里会出现标题、口播稿、简介和镜头建议。</div>}
          </Card>

          <Card title="云端配音" icon={<Mic2 size={18} />} right={tts && <span className="pill">{tts.duration_seconds.toFixed(1)} 秒</span>}>
            <div className="twoCols">
              <Field label="声音">
                <select value={form.voice} onChange={e => update('voice', e.target.value)}>
                  <option value="zh-CN-YunxiNeural">中文男声 Yunxi</option>
                  <option value="zh-CN-YunjianNeural">中文男声 Yunjian</option>
                  <option value="zh-CN-XiaoxiaoNeural">中文女声 Xiaoxiao</option>
                  <option value="zh-CN-XiaoyiNeural">中文女声 Xiaoyi</option>
                </select>
              </Field>
              <div className="field buttonField"><button className="secondary" onClick={generateTts} disabled={!!busy || !script}>{busy === 'tts' ? <Loader2 className="spin" size={18} /> : <Mic2 size={18} />} 生成配音</button></div>
            </div>
            {tts?.file_url && <audio controls src={fullUrl(tts.file_url)} className="audio" />}
            {tts?.warning && <p className="warn">{tts.warning}</p>}
          </Card>

          <Card title="视频合成与预览" icon={<Clapperboard size={18} />}>
            <div className="actions">
              <button className="primary" onClick={composeVideo} disabled={!!busy || !script}>{busy === 'video' ? <Loader2 className="spin" size={18} /> : <Clapperboard size={18} />} 合成 9:16 MP4</button>
              {video?.video_url && <a className="secondary linkBtn" href={fullUrl(video.video_url)} download><Download size={18} /> 下载 MP4</a>}
            </div>
            {video?.video_url ? (
              <div className="videoWrap">
                <video controls src={fullUrl(video.video_url)} />
                <small>时长：{video.duration_seconds.toFixed(1)} 秒</small>
              </div>
            ) : <div className="empty tall">合成后这里可直接播放成片。</div>}
            {!!video?.warnings.length && <div className="warnList">{video.warnings.map((w, i) => <p key={i}>{w}</p>)}</div>}
          </Card>

          <Card title="抖音投流分析 / 实时监控" icon={<Activity size={18} />} right={<label className="switch"><input type="checkbox" checked={autoRefresh} onChange={e => setAutoRefresh(e.target.checked)} />实时刷新</label>}>
            <div className="twoCols">
              <Field label="测试预算（元）">
                <input type="number" value={form.budget} onChange={e => update('budget', Number(e.target.value))} />
              </Field>
              <div className="field buttonField"><button className="secondary" onClick={() => runAdAnalysis(true)} disabled={!!busy || !script}>{busy === 'ad' ? <Loader2 className="spin" size={18} /> : <Megaphone size={18} />} 刷新分析</button></div>
            </div>
            {analysis ? (
              <div className="analysis">
                <div className="decision"><b>{analysis.decision}</b><span>置信度 {(analysis.confidence * 100).toFixed(0)}%</span></div>
                <p>{analysis.suggested_budget}</p>
                <div className="metrics">
                  {analysis.metrics.map(m => <div className={cx('metric', m.status)} key={m.name}><span>{m.name}</span><b>{m.value}</b></div>)}
                </div>
                <div className="alertBox">
                  {analysis.alerts.map((a, i) => <p key={i}>⚠ {a}</p>)}
                </div>
                <details open>
                  <summary>优化建议</summary>
                  <ul>{analysis.optimization_tips.map((x, i) => <li key={i}>{x}</li>)}</ul>
                </details>
                <details>
                  <summary>下一步动作</summary>
                  <ol>{analysis.next_actions.map((x, i) => <li key={i}>{x}</li>)}</ol>
                </details>
              </div>
            ) : <div className="empty tall">生成文案后可刷新投流分析；现在是模拟监控，正式版可接真实抖音/巨量数据。</div>}
          </Card>

          <Card title="运行日志" icon={<Activity size={18} />}>
            <div className="logs">
              {logs.map((line, idx) => <div key={idx}>{line}</div>)}
              {!logs.length && <div className="empty">暂无日志</div>}
            </div>
          </Card>
        </div>
      </main>
    </div>
  )
}
