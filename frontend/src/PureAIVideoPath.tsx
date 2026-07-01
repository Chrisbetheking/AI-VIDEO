import React, { useMemo, useState } from 'react'
import { apiPost, tryPost } from './aiVideoApi'

function splitLines(text: string) {
  return text.split(/[\n。！？!?]+/).map((x) => x.trim()).filter(Boolean)
}

function estimateWords(seconds: number) {
  return Math.max(30, Math.round(seconds * 4.2))
}

function estimateSegments(seconds: number) {
  return Math.max(3, Math.ceil(seconds / 4.5))
}

function estimateShots(seconds: number, materialSeconds: number, shotSeconds: number) {
  const missing = Math.max(0, seconds - materialSeconds)
  return Math.ceil(missing / Math.max(3, shotSeconds || 5))
}

export default function PureAIVideoPath() {
  const [market, setMarket] = useState('马来西亚')
  const [topic, setTopic] = useState('马来西亚买房，别只看价格')
  const [targetSeconds, setTargetSeconds] = useState(28)
  const [selectedMaterialSeconds, setSelectedMaterialSeconds] = useState(0)
  const [singleMaterialSeconds, setSingleMaterialSeconds] = useState(7)
  const [needFal, setNeedFal] = useState(true)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [result, setResult] = useState<any>(null)

  const plan = useMemo(() => {
    const words = estimateWords(targetSeconds)
    const segments = estimateSegments(targetSeconds)
    const missingSeconds = Math.max(0, targetSeconds - selectedMaterialSeconds)
    const falShots = estimateShots(targetSeconds, selectedMaterialSeconds, singleMaterialSeconds)
    const segmentSeconds = Number((targetSeconds / segments).toFixed(1))
    return { words, segments, missingSeconds, falShots, segmentSeconds }
  }, [targetSeconds, selectedMaterialSeconds, singleMaterialSeconds])

  const generatedScript = useMemo(() => {
    const lines = [
      `${topic}，很多人第一步就错了。`,
      `先看预算和用途，再看区域，不要一上来只问价格。`,
      `自住看生活半径，投资看租客来源和未来转手。`,
      `项目、户型、价格和周边必须以官方资料为准。`,
      `想少踩坑，先把预算、城市和用途说清楚。`,
    ]
    return lines.slice(0, Math.max(3, Math.min(lines.length, plan.segments))).join('\n')
  }, [topic, plan.segments])

  const voicePlan = useMemo(() => {
    const lines = splitLines(generatedScript)
    return Array.from({ length: plan.segments }).map((_, index) => {
      const text = lines[index % lines.length] || topic
      return {
        index: index + 1,
        text,
        duration: plan.segmentSeconds,
        material: `素材/AI镜头 ${index + 1}`,
        edit: index === 0 ? '强钩子快切 + 字幕加粗' : index === plan.segments - 1 ? '收口停顿 + 引导评论/私信' : '按语义切镜 + 轻推拉',
      }
    })
  }, [generatedScript, plan.segments, plan.segmentSeconds, topic])

  async function generateCopyOnly() {
    setBusy('copy')
    setError('')
    try {
      const payload = {
        topic,
        market,
        duration_seconds: targetSeconds,
        target_words: plan.words,
        target_segments: plan.segments,
        material_seconds: selectedMaterialSeconds,
        mode: 'pure_ai_or_material_assisted',
      }
      const data = await tryPost([
        '/api/video/copy/generate',
        '/api/copy/generate',
        '/api/video/timeline/build',
      ], payload)
      setResult(data)
    } catch (err: any) {
      setResult({ ok: true, local_plan: true, message: '后端文案接口未适配，先使用前端估算方案。', script: generatedScript, voicePlan })
      setError(err?.message || '')
    } finally {
      setBusy('')
    }
  }

  async function startFullAi() {
    if (!needFal && plan.missingSeconds > 0) {
      setError('素材时长不够，但没有允许 fal.ai 补镜头。')
      return
    }
    if (!window.confirm(`确认生成视频？目标 ${targetSeconds}s，缺口 ${plan.missingSeconds}s，预计 fal.ai 补 ${plan.falShots} 个镜头。`)) return
    setBusy('full-ai')
    setError('')
    try {
      const payload = {
        topic,
        prompt: `${market}房产短视频：${topic}`,
        market,
        duration_seconds: targetSeconds,
        target_duration: targetSeconds,
        target_words: plan.words,
        max_shots: Math.max(1, plan.falShots || Math.ceil(targetSeconds / singleMaterialSeconds)),
        shots: Array.from({ length: Math.max(1, plan.falShots || Math.ceil(targetSeconds / singleMaterialSeconds)) }).map((_, i) => ({
          text: `${topic}，镜头 ${i + 1}`,
          duration: singleMaterialSeconds,
          prompt: `${market} real estate lifestyle b-roll, vertical short video, clean cinematic, no text, shot ${i + 1}`,
        })),
        copy: generatedScript,
        voice_segments: voicePlan,
        quality_policy: { enabled: true, output_profile: 'vertical_720x1280', fps: 30 },
        bgm_policy: { music_type: 'instrumental_only', default_bgm_volume: 0.1, ducking_when_voice: true },
      }
      const data = await apiPost('/api/video/full-ai/start', payload)
      setResult(data)
    } catch (err: any) {
      setError(err?.message || String(err))
    } finally {
      setBusy('')
    }
  }

  return (
    <section className="uxPanelCard">
      <div className="uxHeroRow">
        <div>
          <p className="uxEyebrow">PURE AI VIDEO PATH</p>
          <h2>纯 AI 生成 / 素材不足自动补镜头</h2>
          <p>先用视频长度决定文案字数和分段；素材不够时，用 fal.ai 补通用氛围镜头。真实房源、户型、价格和周边不允许 AI 编造。</p>
        </div>
        <span className="uxBadge danger">可能调用 fal.ai</span>
      </div>

      <div className="uxGrid4">
        <label>市场<input value={market} onChange={(e) => setMarket(e.target.value)} /></label>
        <label>主题<input value={topic} onChange={(e) => setTopic(e.target.value)} /></label>
        <label>目标视频长度/秒<input type="number" value={targetSeconds} onChange={(e) => setTargetSeconds(Number(e.target.value || 28))} /></label>
        <label>已选素材总时长/秒<input type="number" value={selectedMaterialSeconds} onChange={(e) => setSelectedMaterialSeconds(Number(e.target.value || 0))} /></label>
        <label>单个 AI 镜头秒数<input type="number" value={singleMaterialSeconds} onChange={(e) => setSingleMaterialSeconds(Number(e.target.value || 7))} /></label>
        <label className="uxCheck"><input type="checkbox" checked={needFal} onChange={(e) => setNeedFal(e.target.checked)} />素材不够时允许 fal.ai 补镜头</label>
      </div>

      <div className="uxStatsRow">
        <div className="uxStat"><b>{plan.words}</b><span>建议文案字数</span></div>
        <div className="uxStat"><b>{plan.segments}</b><span>口播段数</span></div>
        <div className="uxStat"><b>{plan.missingSeconds}s</b><span>素材缺口</span></div>
        <div className="uxStat"><b>{plan.falShots}</b><span>预计 AI 镜头</span></div>
      </div>

      <div className="uxButtonRow">
        <button onClick={generateCopyOnly} disabled={!!busy}>按时长生成文案计划</button>
        <button className="danger" onClick={startFullAi} disabled={!!busy}>直接生成纯 AI 视频</button>
      </div>
      {busy && <div className="uxNotice">处理中：{busy}</div>}
      {error && <div className="uxError">{error}</div>}

      <div className="uxSplit">
        <div className="uxBox">
          <h3>文案草稿</h3>
          <pre>{generatedScript}</pre>
        </div>
        <div className="uxBox">
          <h3>配音 / 剪辑分配</h3>
          {voicePlan.map((x) => (
            <div className="uxMiniRow" key={x.index}>
              <b>第{x.index}段 · {x.duration}s</b>
              <span>{x.material}</span>
              <p>{x.text}</p>
              <em>{x.edit}</em>
            </div>
          ))}
        </div>
      </div>
      {result && <pre className="uxJson">{JSON.stringify(result, null, 2)}</pre>}
    </section>
  )
}
