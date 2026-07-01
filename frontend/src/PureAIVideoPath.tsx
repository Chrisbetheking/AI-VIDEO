import React, { useMemo, useState } from 'react'
import {
  apiPost,
  buildFullAiPayload,
  computeVideoPlan,
  detailToText,
  generateLocalScript,
  ProjectDraft,
  splitScriptToSegments,
} from './aiVideoApi'

type WorkspaceTab = 'pureai' | 'collect' | 'leads' | 'digital'
type Props = { project: ProjectDraft; setProject: (p: ProjectDraft) => void; goTab: (tab: WorkspaceTab) => void }

const topics = [
  '马来西亚买房，别只看价格',
  '第二家园怎么选房不踩坑',
  '吉隆坡公寓投资出租逻辑',
  '海外房产预算、区域、用途三步判断',
  '养老度假家庭资产配置',
]

function ScriptPreview({ project }: { project: ProjectDraft }) {
  if (!project.script) return <div className="ux-info">还没有文稿。先按视频长度生成文稿和分镜，再生成视频。</div>
  return (
    <div className="ux-two-col">
      <div className="ux-panel">
        <h3>文稿</h3>
        <pre className="ux-script">{project.script}</pre>
      </div>
      <div className="ux-panel">
        <h3>配音 / 剪辑分配</h3>
        <div className="ux-segment-list">
          {project.segments.map((seg) => (
            <div className="ux-segment" key={seg.index}>
              <b>
                第{seg.index}段 · {seg.duration}s
              </b>
              <em>{seg.material}</em>
              <p>{seg.text}</p>
              <strong>{seg.edit}</strong>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

export default function PureAIVideoPath({ project, setProject, goTab }: Props) {
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [result, setResult] = useState<any>(null)

  const plan = useMemo(
    () => computeVideoPlan(project.targetDuration, project.materialSeconds, project.aiShotSeconds),
    [project.targetDuration, project.materialSeconds, project.aiShotSeconds],
  )
  const canGenerateVideo = Boolean(project.script && project.segments.length)

  function patch(next: Partial<ProjectDraft>) {
    setProject({ ...project, ...next })
  }

  function generateDraft() {
    setBusy('draft')
    setError('')
    try {
      const script = generateLocalScript(project.topic, project.market, plan.duration)
      const segments = splitScriptToSegments(script, plan.duration, plan.material, plan.shotSeconds)
      patch({ script, segments, title: project.topic, targetDuration: plan.duration })
      setResult({ ok: true, mode: 'local_draft', script, segments, plan })
    } catch (err) {
      setError(detailToText(err))
    } finally {
      setBusy('')
    }
  }

  async function generateVideo() {
    if (!canGenerateVideo) {
      setError('还没有文稿/分镜。先点击“按视频长度生成文稿/分镜”。')
      return
    }
    if (plan.missingSeconds > 0 && !project.allowFal) {
      setError(`素材还缺 ${plan.missingSeconds}s，但你关闭了 fal.ai 补镜头。请补素材或开启 fal.ai。`)
      return
    }

    const payload = buildFullAiPayload(project, plan)
    const shotCount = Array.isArray(payload.shots) ? payload.shots.length : 0
    const confirmText = plan.aiShotsRaw > plan.backendMaxShots
      ? `后端一次最多 ${plan.backendMaxShots} 个镜头。系统会把 ${plan.segmentCount} 段口播合并为 ${shotCount} 个 AI 镜头提交，口播/字幕仍按 ${plan.segmentCount} 段走。继续？`
      : plan.aiShotsRaw > 0
        ? `将调用视频生成接口，素材缺 ${plan.missingSeconds}s，预计补 ${shotCount} 个 AI 镜头。继续？`
        : '将调用视频生成接口。继续？'

    if (!window.confirm(confirmText)) return

    setBusy('video')
    setError('')
    try {
      const data = await apiPost('/api/video/full-ai/start', payload, 360000)
      setResult(data)
      patch({ lastOutput: data })
    } catch (err) {
      setError(detailToText(err))
    } finally {
      setBusy('')
    }
  }

  return (
    <section className="ux-workspace-section">
      <div className="ux-hero slim">
        <div>
          <p className="ux-eyebrow">PURE AI / SCRIPT FIRST / RENDER AFTER</p>
          <h2>纯 AI 生成路径</h2>
          <p>先确定主题和视频长度，再生成文稿、分镜、配音/剪辑分配；没有文稿不能生成视频。真实房源、户型、价格和周边不允许 AI 编造。</p>
        </div>
        <span className={plan.aiShotsRaw > 0 ? 'ux-badge red' : 'ux-badge green'}>
          {plan.aiShotsRaw > 0 ? '可能调用 fal.ai' : '素材够用'}
        </span>
      </div>

      <div className="ux-chip-row">
        {topics.map((x) => (
          <button key={x} className={project.topic === x ? 'active' : ''} onClick={() => patch({ topic: x })}>
            {x}
          </button>
        ))}
      </div>

      <div className="ux-form-grid four">
        <label>
          市场
          <input value={project.market} onChange={(e) => patch({ market: e.target.value })} />
        </label>
        <label>
          主题 / 选题
          <input value={project.topic} onChange={(e) => patch({ topic: e.target.value })} />
        </label>
        <label>
          目标视频长度/秒
          <input type="number" value={project.targetDuration} onChange={(e) => patch({ targetDuration: Number(e.target.value || 28) })} />
        </label>
        <label>
          已选素材总时长/秒
          <input type="number" value={project.materialSeconds} onChange={(e) => patch({ materialSeconds: Number(e.target.value || 0) })} />
        </label>
        <label>
          单个 AI 镜头秒数
          <input type="number" value={project.aiShotSeconds} onChange={(e) => patch({ aiShotSeconds: Number(e.target.value || 7) })} />
        </label>
        <label className="ux-check">
          <input type="checkbox" checked={project.allowFal} onChange={(e) => patch({ allowFal: e.target.checked })} />
          素材不足时允许 fal.ai 补通用氛围镜头
        </label>
      </div>

      <div className="ux-metrics four">
        <div>
          <b>{plan.suggestedChars}</b>
          <span>建议文案字数</span>
        </div>
        <div>
          <b>{plan.segmentCount}</b>
          <span>口播段数</span>
        </div>
        <div>
          <b>{plan.missingSeconds}s</b>
          <span>素材缺口</span>
        </div>
        <div>
          <b>{plan.aiShots}</b>
          <span>本次提交 AI 镜头</span>
        </div>
      </div>

      <div className="ux-info">
        按 {plan.duration}s 视频长度生成文稿；口播约 {plan.segmentCount} 段。后端 full-ai 单次最多 {plan.backendMaxShots} 个镜头，超过时会自动合并镜头提交，字幕/配音仍按口播分段。
      </div>

      <div className="ux-button-row">
        <button className="ux-primary" onClick={generateDraft} disabled={!!busy}>
          {busy === 'draft' ? '生成中...' : '按视频长度生成文稿/分镜'}
        </button>
        <button className="ux-danger" onClick={generateVideo} disabled={!canGenerateVideo || !!busy}>
          {busy === 'video' ? '提交中...' : '生成完整 AI 视频'}
        </button>
        <button className="ux-ghost" onClick={() => goTab('collect')}>
          先去抖音采集选题
        </button>
        <button className="ux-ghost" onClick={() => goTab('leads')}>
          先看获客线索
        </button>
      </div>

      {plan.willMergeShotsForBackend && (
        <div className="ux-warn">
          口播需要 {plan.segmentCount} 段，但 full-ai 后端单次限制 {plan.backendMaxShots} 个镜头。现在会合并为 {plan.aiShots} 个 shots，不会再提交 7 个 shots 去触发拦截。
        </div>
      )}

      {error && <div className="ux-error">{error}</div>}
      <ScriptPreview project={project} />
      {result && (
        <details className="ux-json">
          <summary>接口/生成结果</summary>
          <pre>{JSON.stringify(result, null, 2)}</pre>
        </details>
      )}
    </section>
  )
}
