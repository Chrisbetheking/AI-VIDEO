import React, { useMemo, useState } from 'react'
import { apiPost, buildFullAiPayload, computeVideoPlan, detailToText, generateLocalScript, ProjectDraft, splitScriptToSegments, WorkspaceTab } from './aiVideoApi'

type Props = { project: ProjectDraft; setProject: (p: ProjectDraft) => void; goTab: (tab: WorkspaceTab) => void }

const topics = ['马来西亚买房，别只看价格', '第二家园怎么选房不踩坑', '吉隆坡公寓投资出租逻辑', '海外房产预算、区域、用途三步判断', '养老度假家庭资产配置']

function ScriptPreview({ project }: { project: ProjectDraft }) {
  if (!project.script) return <div className="ux-note">还没有文稿。先按视频长度生成文稿和分镜，再生成视频。</div>
  return (
    <div className="ux-grid two">
      <div className="ux-panel"><h3>文稿</h3><pre className="ux-script">{project.script}</pre></div>
      <div className="ux-panel"><h3>配音 / 剪辑分配</h3>{project.segments.map((seg) => <div className="ux-segment" key={seg.index}><b>第{seg.index}段 · {seg.duration}s</b><span>{seg.material}</span><p>{seg.text}</p><em>{seg.edit}</em></div>)}</div>
    </div>
  )
}

export default function PureAIVideoPath({ project, setProject, goTab }: Props) {
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [result, setResult] = useState<unknown>(null)
  const plan = useMemo(() => computeVideoPlan(project.targetDuration, project.materialSeconds, project.aiShotSeconds), [project.targetDuration, project.materialSeconds, project.aiShotSeconds])
  const canGenerateVideo = Boolean(project.script && project.segments.length)
  function patch(next: Partial<ProjectDraft>) { setProject({ ...project, ...next }) }

  function generateDraft() {
    setBusy('draft'); setError('')
    try {
      const script = generateLocalScript(project.topic, project.market, plan.duration)
      const segments = splitScriptToSegments(script, plan.duration, plan.material, plan.shotSeconds)
      patch({ script, segments, title: project.topic, targetDuration: plan.duration })
      setResult({ ok: true, mode: 'local_draft', script, segments, plan })
    } catch (err) { setError(detailToText(err)) } finally { setBusy('') }
  }

  async function generateVideo() {
    if (!canGenerateVideo) { setError('还没有文稿/分镜。先点击“按视频长度生成文稿/分镜”。'); return }
    if (plan.missingSeconds > 0 && !project.allowFal) { setError(`素材还缺 ${plan.missingSeconds}s，但你关闭了 fal.ai 补镜头。请补素材或开启 fal.ai。`); return }
    const ok = window.confirm(`将调用完整视频生成接口。本次口播 ${project.segments.length} 段，提交给 full-ai 的 AI 镜头最多 ${plan.fullAiShots} 个。继续？`)
    if (!ok) return
    setBusy('video'); setError('')
    try {
      const payload = buildFullAiPayload(project)
      const data = await apiPost('/api/video/full-ai/start', payload, 360000)
      setResult(data); patch({ lastOutput: data })
    } catch (err) { setError(detailToText(err)) } finally { setBusy('') }
  }

  return (
    <section className="ux-card">
      <div className="ux-hero"><div><p className="ux-eyebrow">PURE AI / SCRIPT FIRST / RENDER AFTER</p><h2>纯 AI 生成路径</h2><p>先确定主题和视频长度，再生成文稿、分镜、配音/剪辑分配；没有文稿不能生成视频。真实房源、户型、价格和周边不允许 AI 编造。</p></div><span className={plan.aiShots > 0 ? 'ux-badge red' : 'ux-badge green'}>{plan.aiShots > 0 ? '素材不足会补 AI 镜头' : '素材时长够用'}</span></div>
      <div className="ux-topic-row">{topics.map((x) => <button key={x} className={project.topic === x ? 'active' : ''} onClick={() => patch({ topic: x })}>{x}</button>)}</div>
      <div className="ux-grid four"><label>市场<input value={project.market} onChange={(e) => patch({ market: e.target.value })} /></label><label>主题 / 选题<input value={project.topic} onChange={(e) => patch({ topic: e.target.value })} /></label><label>目标视频长度/秒<input type="number" value={project.targetDuration} onChange={(e) => patch({ targetDuration: Number(e.target.value || 28) })} /></label><label>已选素材总时长/秒<input type="number" value={project.materialSeconds} onChange={(e) => patch({ materialSeconds: Number(e.target.value || 0) })} /></label><label>单个 AI 镜头秒数<input type="number" value={project.aiShotSeconds} onChange={(e) => patch({ aiShotSeconds: Number(e.target.value || 7) })} /></label><label className="ux-check"><input type="checkbox" checked={project.allowFal} onChange={(e) => patch({ allowFal: e.target.checked })} />素材不足允许 fal.ai 补镜头</label></div>
      <div className="ux-metrics four"><div><b>{plan.suggestedChars}</b><span>建议文案字数</span></div><div><b>{plan.segmentCount}</b><span>口播段数</span></div><div><b>{plan.missingSeconds}s</b><span>素材缺口</span></div><div><b>{plan.fullAiShots}</b><span>本次提交 AI 镜头</span></div></div>
      <div className="ux-note">按 {plan.duration}s 视频长度生成文稿；每段约 {plan.avgSegmentSeconds}s。生成视频会把口播段合并为最多 3 个 shots，避免触发后端费用保护。</div>
      <div className="ux-button-row"><button className="ux-primary" onClick={generateDraft} disabled={!!busy}>{busy === 'draft' ? '生成中...' : '按视频长度生成文稿/分镜'}</button><button className="ux-danger" onClick={generateVideo} disabled={!canGenerateVideo || !!busy}>{busy === 'video' ? '提交中...' : '生成完整 AI 视频'}</button><button className="ux-ghost" onClick={() => goTab('collect')}>先去抖音采集选题</button><button className="ux-ghost" onClick={() => goTab('leads')}>先看获客线索</button></div>
      {error && <div className="ux-error">{error}</div>}
      <ScriptPreview project={project} />
      {result ? <details className="ux-json"><summary>完整结果</summary><pre>{JSON.stringify(result, null, 2)}</pre></details> : null}
    </section>
  )
}
