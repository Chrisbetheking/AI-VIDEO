import React, { useMemo, useState } from 'react'
import { apiPost, copyJson } from './aiVideoApi'

type ShotPlan = {
  index: number
  start: number
  end: number
  duration: number
  text: string
  source: string
  edit: string
}

function splitTextByCount(text: string, count: number) {
  const clean = text.replace(/\s+/g, ' ').trim()
  if (!clean) return []
  const size = Math.max(16, Math.ceil(clean.length / count))
  const out: string[] = []
  for (let i = 0; i < clean.length; i += size) out.push(clean.slice(i, i + size))
  return out.slice(0, count)
}

function buildScript(topic: string, market: string, targetChars: number) {
  const seed = topic.trim() || `${market}买房，不要只看价格`
  const lines = [
    `${seed}，先别急着做决定。`,
    '第一步先看预算和用途，别一上来只问价格。',
    '第二步看区域：自住、出租和未来转手，判断逻辑完全不一样。',
    '第三步核验真实资料：户型、价格、周边和交付信息都要以官方文件为准。',
    '想少踩坑，先把预算、目标城市和自住/投资用途说清楚。',
  ]
  let script = lines.join('\n')
  while (script.length < targetChars * 0.85) script += `\n${lines[(script.length + lines.length) % lines.length]}`
  return script.slice(0, Math.max(80, targetChars + 30))
}

export default function PureAIVideoPath() {
  const [market, setMarket] = useState('马来西亚')
  const [platform, setPlatform] = useState('douyin')
  const [duration, setDuration] = useState(35)
  const [materialSeconds, setMaterialSeconds] = useState(18)
  const [singleClipSeconds, setSingleClipSeconds] = useState(6)
  const [topic, setTopic] = useState('第二家园怎么选？不要只看房价，要看身份、教育、养老和资产配置。')
  const [mode, setMode] = useState<'pure_ai' | 'material_plus_ai'>('pure_ai')
  const [scriptDraft, setScriptDraft] = useState('')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [result, setResult] = useState<any>(null)

  const plan = useMemo(() => {
    const seconds = Math.max(8, Math.min(180, Number(duration) || 35))
    const material = Math.max(0, Number(materialSeconds) || 0)
    const clip = Math.max(3, Math.min(10, Number(singleClipSeconds) || 6))
    const targetChars = Math.round(seconds * 4.2)
    const voiceSegments = Math.max(3, Math.min(30, Math.ceil(seconds / 4.5)))
    const draftText = scriptDraft || buildScript(topic, market, targetChars)
    const baseParts = splitTextByCount(draftText, voiceSegments)
    const shotCount = Math.max(1, Math.ceil(seconds / clip))
    const materialShotCount = Math.min(shotCount, Math.ceil(material / clip))
    const needFalSeconds = Math.max(0, seconds - material)
    const falShotCount = Math.ceil(needFalSeconds / clip)
    const shots: ShotPlan[] = []
    let cursor = 0

    for (let i = 0; i < shotCount; i += 1) {
      const shotDur = Math.min(clip, seconds - cursor)
      if (shotDur <= 0) break
      const isMaterial = mode === 'material_plus_ai' && i < materialShotCount
      shots.push({
        index: i + 1,
        start: Number(cursor.toFixed(2)),
        end: Number((cursor + shotDur).toFixed(2)),
        duration: Number(shotDur.toFixed(2)),
        text: baseParts[i % Math.max(1, baseParts.length)] || topic,
        source: mode === 'pure_ai' ? 'fal.ai 生成镜头' : isMaterial ? '已选素材自动剪辑' : 'fal.ai 补足镜头',
        edit:
          i === 0
            ? '强钩子快切 + 字幕加粗'
            : i === shotCount - 1
              ? '结尾收口，留私信/评论筛选问题'
              : '按语义切镜 + 轻推拉，风险点慢一点，结果点快一点',
      })
      cursor += shotDur
    }

    return {
      seconds,
      material,
      clip,
      targetChars,
      voiceSegments,
      shotCount,
      materialShotCount,
      needFalSeconds,
      falShotCount,
      shots,
      draftText,
    }
  }, [duration, materialSeconds, singleClipSeconds, topic, mode, scriptDraft, market])

  function generatePlanOnly() {
    const draft = buildScript(topic, market, plan.targetChars)
    setScriptDraft(draft)
    setError('')
    setResult({
      ok: true,
      provider: 'frontend_pure_ai_path_v2',
      message: '已按视频长度生成文稿、分镜、配音和剪辑分配。现在才可以生成完整 AI 视频。',
      mode,
      market,
      platform,
      topic,
      script: draft,
      plan: { ...plan, draftText: draft },
    })
  }

  async function generateVideo() {
    if (!scriptDraft.trim()) {
      setError('先生成文稿/分镜，再生成视频。不能跳过文稿直接调视频接口。')
      return
    }
    if (!window.confirm('确认调用生成视频接口？纯 AI 或补镜头会消耗 fal.ai/视频额度。')) return

    setBusy('生成视频')
    setError('')
    try {
      const aiShots = plan.shots
        .filter((x) => mode === 'pure_ai' || x.source.includes('fal.ai'))
        .slice(0, 3)
        .map((shot) => ({
          index: shot.index,
          duration: Math.max(3, Math.min(8, Math.round(shot.duration))),
          prompt: `${market}房产短视频B-roll，竖屏9:16，真实质感，镜头内容：${shot.text}。要求：不能编造具体楼盘、户型、价格和周边，通用城市/生活/看房氛围镜头。`,
          text: shot.text,
          shot_hint: shot.edit,
        }))

      if (!aiShots.length) {
        throw new Error('当前没有需要 AI 生成的镜头。素材足够时请走剪辑合成路径，不要调用 full-ai。')
      }

      const data = await apiPost('/api/video/full-ai/start', {
        shots: aiShots,
        copy: scriptDraft,
        script: scriptDraft,
        topic,
        market,
        platform,
        target_duration: plan.seconds,
        duration_seconds: plan.seconds,
        max_shots: aiShots.length,
        source: 'pure_ai_or_material_plus_ai_path',
        generation_mode: mode,
        material_seconds: plan.material,
        fal_fill_seconds: plan.needFalSeconds,
        shot_plan: plan.shots,
        safety_note: '真实房源、户型、价格和周边不允许 AI 编造；fal.ai 只补通用氛围/B-roll 镜头。',
      })
      setResult(data)
    } catch (e: any) {
      setError(e?.message || String(e))
    } finally {
      setBusy('')
    }
  }

  return (
    <section className="productUxPanel pureAiPanel">
      <div className="productUxHero">
        <div>
          <p className="productUxEyebrow">PURE AI VIDEO PATH</p>
          <h2>纯 AI 生成路径</h2>
          <p>先选主题和视频长度，生成文稿、分镜和剪辑分配；文稿生成后才能调用视频生成接口。</p>
        </div>
        <span className="productUxDangerPill">可能调用 fal.ai</span>
      </div>

      <div className="productUxTabs">
        <button className={mode === 'pure_ai' ? 'active' : ''} onClick={() => setMode('pure_ai')}>方案 A：纯 AI 生成</button>
        <button className={mode === 'material_plus_ai' ? 'active' : ''} onClick={() => setMode('material_plus_ai')}>方案 B：素材优先 + AI 补足</button>
      </div>

      <div className="productUxGrid4">
        <label>市场<input value={market} onChange={(e) => setMarket(e.target.value)} /></label>
        <label>平台<input value={platform} onChange={(e) => setPlatform(e.target.value)} /></label>
        <label>视频长度/秒<input type="number" value={duration} onChange={(e) => setDuration(Number(e.target.value || 35))} /></label>
        <label>单镜头建议/秒<input type="number" value={singleClipSeconds} onChange={(e) => setSingleClipSeconds(Number(e.target.value || 6))} /></label>
        <label>已选素材总时长/秒<input type="number" value={materialSeconds} onChange={(e) => setMaterialSeconds(Number(e.target.value || 0))} /></label>
        <label className="wide">主题 / 选题<input value={topic} onChange={(e) => setTopic(e.target.value)} /></label>
      </div>

      <div className="productUxMetricGrid">
        <div><b>{plan.targetChars}</b><span>建议文案字数</span></div>
        <div><b>{plan.voiceSegments}</b><span>口播段数</span></div>
        <div><b>{plan.needFalSeconds}s</b><span>素材缺口</span></div>
        <div><b>{mode === 'pure_ai' ? plan.shotCount : plan.falShotCount}</b><span>预计 AI 镜头</span></div>
      </div>

      <div className="productUxNotice">
        按 {plan.seconds}s 视频长度生成文稿；每段约 {Math.round(plan.seconds / plan.voiceSegments)}s。素材不足时才用 fal.ai 补通用氛围镜头。
      </div>

      <div className="productUxButtonRow">
        <button onClick={generatePlanOnly}>按视频长度生成文稿/分镜</button>
        <button className="danger" onClick={generateVideo} disabled={!scriptDraft.trim() || !!busy}>
          生成完整 AI 视频
        </button>
      </div>

      {busy && <div className="productUxLoading">处理中：{busy}</div>}
      {error && <div className="productUxError">{error}</div>}

      <div className="productUxTwoCols">
        <div className="productUxCard">
          <h3>文稿</h3>
          <pre>{scriptDraft || plan.draftText}</pre>
        </div>
        <div className="productUxCard">
          <h3>配音 / 剪辑分配</h3>
          {plan.shots.map((shot) => (
            <div className="productUxShot" key={shot.index}>
              <b>第{shot.index}段 · {shot.duration}s <em>{shot.source}</em></b>
              <p>{shot.text}</p>
              <span>{shot.edit}</span>
            </div>
          ))}
        </div>
      </div>

      {result && (
        <details className="productUxJsonBox" open>
          <summary>结果 <button onClick={() => copyJson(result)}>复制 JSON</button></summary>
          <pre>{JSON.stringify(result, null, 2)}</pre>
        </details>
      )}
    </section>
  )
}
