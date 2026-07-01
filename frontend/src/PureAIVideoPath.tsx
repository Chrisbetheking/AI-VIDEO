import React, { useMemo, useState } from 'react'
import { apiPost, errorText } from './aiVideoApi'

type Segment = {
  index: number
  seconds: number
  text: string
  visual: string
  edit: string
}

type DraftPlan = {
  title: string
  hook: string
  script: string
  segments: Segment[]
  storyboard: string[]
}

const topicPresets = [
  '马来西亚买房，别只看价格',
  '第二家园怎么选房不踩坑',
  '吉隆坡公寓投资出租逻辑',
  '海外房产预算、区域、用途三步判断',
  '养老度假家庭资产配置',
]

function clampNumber(value: number, min: number, max: number) {
  if (!Number.isFinite(value)) return min
  return Math.max(min, Math.min(max, value))
}

function estimateChars(seconds: number) {
  return Math.round(clampNumber(seconds, 8, 180) * 4.2)
}

function estimateSegments(seconds: number) {
  return Math.max(3, Math.ceil(clampNumber(seconds, 8, 180) / 4))
}

function splitScript(script: string, segmentCount: number, totalSeconds: number) {
  const clean = script.replace(/\s+/g, ' ').trim()
  const sentenceParts = clean.split(/(?<=[。！？!?])/).map((x) => x.trim()).filter(Boolean)
  const parts = sentenceParts.length >= segmentCount ? sentenceParts : clean.split(/[，,。！？!?]/).map((x) => x.trim()).filter(Boolean)
  const chunks: string[] = []
  const per = Math.max(1, Math.ceil(parts.length / segmentCount))
  for (let i = 0; i < segmentCount; i += 1) {
    const text = parts.slice(i * per, (i + 1) * per).join('，').replace(/[，,]$/, '')
    chunks.push(text || parts[i % Math.max(1, parts.length)] || clean)
  }
  const base = totalSeconds / segmentCount
  return chunks.map((text, index) => ({
    index: index + 1,
    seconds: Number(base.toFixed(1)),
    text,
    visual: index === 0 ? '强钩子开场，字幕加粗，快速给出痛点' : index === segmentCount - 1 ? '收口引导评论/私信，留筛选问题' : '资料画面 / 城市环境 / 户型或地图素材补充说明',
    edit: index % 2 === 0 ? '快切 + 轻推拉' : '叠化 + 重点字幕',
  }))
}

function buildDraft(theme: string, market: string, seconds: number): DraftPlan {
  const safeTheme = theme.trim() || `${market}买房，别只看价格`
  const segs = estimateSegments(seconds)
  const script = [
    `${safeTheme}，很多人第一步就错了。`,
    `先看预算和用途，再看区域，不要一上来只问价格。`,
    `自住看生活半径，投资看租客来源和未来转手。`,
    `项目、户型、价格和周边必须以官方资料为准。`,
    `想少踩坑，先把预算、城市和用途说清楚。`,
  ].join('')
  const segments = splitScript(script, segs, seconds)
  return {
    title: safeTheme,
    hook: `${market}买房别只问价格，真正决定结果的是预算、区域和用途。`,
    script,
    segments,
    storyboard: segments.map((s) => `第${s.index}镜：${s.visual}｜${s.edit}｜${s.seconds}s`),
  }
}

export default function PureAIVideoPath() {
  const [market, setMarket] = useState('马来西亚')
  const [theme, setTheme] = useState('马来西亚买房，别只看价格')
  const [targetSeconds, setTargetSeconds] = useState(28)
  const [materialSeconds, setMaterialSeconds] = useState(0)
  const [aiShotSeconds, setAiShotSeconds] = useState(7)
  const [allowFal, setAllowFal] = useState(true)
  const [draft, setDraft] = useState<DraftPlan | null>(null)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [result, setResult] = useState<any>(null)

  const safeTarget = clampNumber(Number(targetSeconds), 8, 180)
  const safeMaterial = clampNumber(Number(materialSeconds), 0, 999)
  const gapSeconds = Math.max(0, Math.ceil(safeTarget - safeMaterial))
  const requiredAiShots = gapSeconds > 0 ? Math.ceil(gapSeconds / clampNumber(Number(aiShotSeconds), 3, 12)) : 0
  const chars = estimateChars(safeTarget)
  const segments = estimateSegments(safeTarget)
  const canGenerateVideo = Boolean(draft?.script?.trim())

  const materialAdvice = useMemo(() => {
    if (gapSeconds <= 0) return '素材够用：优先用真实/已有素材剪辑。'
    if (!allowFal) return `素材缺 ${gapSeconds}s：当前未允许 fal.ai 补镜头，建议先补素材。`
    return `素材缺 ${gapSeconds}s：预计用 fal.ai 补 ${requiredAiShots} 个通用氛围镜头。`
  }, [gapSeconds, allowFal, requiredAiShots])

  function generateDraft() {
    setError('')
    setResult(null)
    const next = buildDraft(theme, market, safeTarget)
    setDraft(next)
  }

  async function generateVideo() {
    if (!draft) {
      setError('先生成文稿和分镜，再生成视频。')
      return
    }
    const ok = window.confirm('确认调用生成视频接口？这一步可能调用 fal.ai / TTS / 合成接口并产生费用。')
    if (!ok) return
    setBusy('video')
    setError('')
    try {
      const data = await apiPost('/api/video/full-ai/start', {
        market,
        topic: draft.title,
        title: draft.title,
        prompt: draft.hook,
        script: draft.script,
        target_duration: safeTarget,
        target_seconds: safeTarget,
        max_shots: Math.max(1, requiredAiShots || segments),
        allow_fal_supplement: allowFal && gapSeconds > 0,
        shots: draft.segments.map((s) => ({
          index: s.index,
          duration: s.seconds,
          text: s.text,
          prompt: `${market}房产短视频通用氛围镜头，真实感，竖屏，${s.visual}，不要出现具体楼盘价格户型和虚构周边`,
          edit: s.edit,
        })),
        safety_policy: {
          no_fake_property_facts: true,
          use_official_material_for_property_floorplan_surroundings: true,
        },
      })
      setResult(data)
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy('')
    }
  }

  return (
    <section className="uxPanel pureAiPanel">
      <div className="uxHero">
        <div>
          <p className="uxEyebrow">PURE AI VIDEO PATH</p>
          <h2>纯 AI 生成路径</h2>
          <p>先选主题和视频长度，生成文稿、分镜和剪辑分配；文稿生成后才能调用视频生成接口。真实房源、户型、价格、周边不允许 AI 编造。</p>
        </div>
        <span className="uxDangerBadge">可能调用 fal.ai</span>
      </div>

      <div className="uxPresetRow">
        {topicPresets.map((x) => (
          <button key={x} type="button" className={theme === x ? 'active' : ''} onClick={() => setTheme(x)}>{x}</button>
        ))}
      </div>

      <div className="uxGrid four">
        <label>市场<input value={market} onChange={(e) => setMarket(e.target.value)} /></label>
        <label>主题 / 选题<input value={theme} onChange={(e) => setTheme(e.target.value)} placeholder="输入要生成的视频主题" /></label>
        <label>目标视频长度/秒<input type="number" min={8} max={180} value={targetSeconds} onChange={(e) => setTargetSeconds(Number(e.target.value || 28))} /></label>
        <label>已选素材总时长/秒<input type="number" min={0} value={materialSeconds} onChange={(e) => setMaterialSeconds(Number(e.target.value || 0))} /></label>
        <label>单个 AI 镜头秒数<input type="number" min={3} max={12} value={aiShotSeconds} onChange={(e) => setAiShotSeconds(Number(e.target.value || 7))} /></label>
        <label className="uxCheck"><input type="checkbox" checked={allowFal} onChange={(e) => setAllowFal(e.target.checked)} />素材不足允许 fal.ai 补镜头</label>
      </div>

      <div className="uxStatGrid">
        <div><b>{chars}</b><span>建议文案字数</span></div>
        <div><b>{segments}</b><span>口播段数</span></div>
        <div><b>{gapSeconds}s</b><span>素材缺口</span></div>
        <div><b>{requiredAiShots}</b><span>预计 AI 镜头</span></div>
      </div>

      <div className="uxNotice">{materialAdvice}</div>

      <div className="uxButtonRow">
        <button onClick={generateDraft}>按主题和时长生成文稿/分镜</button>
        <button className="danger" onClick={generateVideo} disabled={!canGenerateVideo || !!busy}>{busy === 'video' ? '生成中...' : '生成完整 AI 视频'}</button>
      </div>

      {error && <div className="uxError">{error}</div>}

      {draft && (
        <div className="uxTwoCol">
          <div className="uxCard">
            <h3>文稿草稿</h3>
            <label>标题<input value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} /></label>
            <label>黄金三秒钩子<textarea value={draft.hook} onChange={(e) => setDraft({ ...draft, hook: e.target.value })} /></label>
            <label>完整口播稿<textarea value={draft.script} onChange={(e) => setDraft({ ...draft, script: e.target.value, segments: splitScript(e.target.value, segments, safeTarget) })} /></label>
          </div>
          <div className="uxCard">
            <h3>配音 / 剪辑分配</h3>
            {draft.segments.map((s) => (
              <div className="uxSegment" key={s.index}>
                <b>第{s.index}段 · {s.seconds}s</b>
                <p>{s.text}</p>
                <em>{s.visual}</em>
                <span>{s.edit}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {result && <pre className="uxJson">{JSON.stringify(result, null, 2)}</pre>}
    </section>
  )
}
