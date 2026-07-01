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

export default function PureAIVideoPath() {
  const [market, setMarket] = useState('马来西亚')
  const [platform, setPlatform] = useState('douyin')
  const [duration, setDuration] = useState(35)
  const [materialSeconds, setMaterialSeconds] = useState(18)
  const [singleClipSeconds, setSingleClipSeconds] = useState(6)
  const [topic, setTopic] = useState('第二家园怎么选？不要只看房价，要看身份、教育、养老和资产配置。')
  const [mode, setMode] = useState<'pure_ai' | 'material_plus_ai'>('pure_ai')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [result, setResult] = useState<any>(null)

  const plan = useMemo(() => {
    const seconds = Math.max(8, Math.min(180, Number(duration) || 35))
    const material = Math.max(0, Number(materialSeconds) || 0)
    const clip = Math.max(3, Math.min(10, Number(singleClipSeconds) || 6))
    const targetChars = Math.round(seconds * 4.2)
    const voiceSegments = Math.max(3, Math.min(30, Math.ceil(seconds / 4.5)))
    const baseParts = splitTextByCount(topic, voiceSegments)
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
        source: mode === 'pure_ai' ? 'fal.ai 生成镜头' : isMaterial ? '已选素材剪辑' : 'fal.ai 补足镜头',
        edit: i === 0 ? '强钩子，快切进入主题' : i === shotCount - 1 ? '结尾收口，留私信/评论筛选问题' : '按口播情绪切换，风险点慢一点，结果点快一点',
      })
      cursor += shotDur
    }
    return { seconds, material, clip, targetChars, voiceSegments, shotCount, materialShotCount, needFalSeconds, falShotCount, shots }
  }, [duration, materialSeconds, singleClipSeconds, topic, mode])

  async function generateVideo() {
    if (!window.confirm('确认调用生成视频接口？纯 AI 或补镜头会消耗 fal.ai/视频额度。')) return
    setBusy('生成视频')
    setError('')
    try {
      const prompt = `平台:${platform}\n市场:${market}\n模式:${mode}\n目标时长:${plan.seconds}秒\n文案目标:${plan.targetChars}字/${plan.voiceSegments}段\n主题:${topic}\n镜头计划:${plan.shots.map((x) => `${x.index}.${x.source}:${x.text}`).join('；')}`
      const data = await apiPost('/api/video/full-ai/start', {
        prompt,
        market,
        platform,
        target_duration: plan.seconds,
        duration_seconds: plan.seconds,
        max_shots: Math.min(3, Math.max(1, plan.falShotCount || plan.shotCount)),
        source: 'pure_ai_or_material_plus_ai_path',
        generation_mode: mode,
        material_seconds: plan.material,
        fal_fill_seconds: plan.needFalSeconds,
        shot_plan: plan.shots,
      })
      setResult(data)
    } catch (e: any) {
      setError(e?.message || String(e))
    } finally {
      setBusy('')
    }
  }

  async function savePlanOnly() {
    setResult({ ok: true, provider: 'frontend_pure_ai_path_v1', mode, market, platform, topic, plan })
  }

  return (
    <section className="workspacePanel">
      <div className="panelHero aiHero">
        <div>
          <p>PURE AI VIDEO PATH</p>
          <h2>纯 AI 生成 / 素材不够自动补镜头</h2>
          <span>你输入视频时长，系统按时长算文案字数、口播段数、素材是否够用；素材不够就用 fal.ai 补 B-roll。</span>
        </div>
        <b>两套方案已合并</b>
      </div>

      <div className="modeSwitch">
        <button className={mode === 'pure_ai' ? 'active' : ''} onClick={() => setMode('pure_ai')}>方案 A：纯 AI 生成</button>
        <button className={mode === 'material_plus_ai' ? 'active' : ''} onClick={() => setMode('material_plus_ai')}>方案 B：素材优先 + AI 补足</button>
      </div>

      <div className="inputGrid four">
        <label>市场<input value={market} onChange={(e) => setMarket(e.target.value)} /></label>
        <label>平台<input value={platform} onChange={(e) => setPlatform(e.target.value)} /></label>
        <label>视频长度/秒<input type="number" value={duration} onChange={(e) => setDuration(Number(e.target.value || 35))} /></label>
        <label>单镜头建议/秒<input type="number" value={singleClipSeconds} onChange={(e) => setSingleClipSeconds(Number(e.target.value || 6))} /></label>
      </div>
      <div className="inputGrid two">
        <label>已选素材总时长/秒<input type="number" value={materialSeconds} onChange={(e) => setMaterialSeconds(Number(e.target.value || 0))} /></label>
        <label>主题 / 文案方向<input value={topic} onChange={(e) => setTopic(e.target.value)} /></label>
      </div>

      <div className="estimateStrip">
        <b>{plan.seconds} 秒 ≈ {plan.targetChars} 字 / {plan.voiceSegments} 段口播 / {plan.shotCount} 个镜头</b>
        <span>{mode === 'pure_ai' ? `全部 ${plan.shotCount} 个镜头走 fal.ai。` : plan.needFalSeconds > 0 ? `素材缺 ${plan.needFalSeconds} 秒，需要 fal.ai 补 ${plan.falShotCount} 个镜头。` : '素材时长足够，优先自动剪辑，不必补 fal.ai。'}</span>
      </div>

      <div className="planGrid">
        {plan.shots.map((shot) => (
          <div className="planCard" key={shot.index}>
            <b>#{shot.index} {shot.start}s - {shot.end}s</b>
            <em>{shot.source}</em>
            <p>{shot.text}</p>
            <span>{shot.edit}</span>
          </div>
        ))}
      </div>

      <div className="buttonRow">
        <button onClick={savePlanOnly} disabled={!!busy}>只生成方案</button>
        <button className="red" onClick={generateVideo} disabled={!!busy}>直接生成视频</button>
      </div>
      {busy && <div className="productNotice">处理中：{busy}</div>}
      {error && <div className="productError">错误：{error}</div>}
      {result && <details className="productJsonBox" open><summary>结果</summary><button className="productBtn" onClick={() => copyJson(result)}>复制 JSON</button><pre>{JSON.stringify(result, null, 2)}</pre></details>}
    </section>
  )
}
