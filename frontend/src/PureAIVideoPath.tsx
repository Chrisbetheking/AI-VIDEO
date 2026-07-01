import React, { useMemo, useState } from 'react'
import {
  apiPost,
  buildFullAiPayload,
  computeVideoPlan,
  detailToText,
  generateLocalScript,
  projectWithScript,
  ProjectDraft,
  splitScriptToSegments,
} from './aiVideoApi'

type WorkspaceTab = 'pure' | 'douyin' | 'openclaw' | 'digital'

type Props = {
  project: ProjectDraft
  setProject: (next: ProjectDraft) => void
  goTab?: (next: WorkspaceTab) => void
}

const topics = [
  '马来西亚买房，别只看价格',
  '第二家园怎么选房不踩坑',
  '吉隆坡公寓投资出租逻辑',
  '海外房产预算、区域、用途三步判断',
  '养老度假家庭资产配置',
]

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
    setError('')
  }

  function generateScript() {
    const script = generateLocalScript(project.topic, project.market, plan.duration)
    const next = projectWithScript({ ...project, targetDuration: plan.duration }, script)
    setProject(next)
    setResult({
      ok: true,
      provider: 'frontend_local_script_plan',
      message: '已按视频长度生成文稿、分镜和配音/剪辑分配。',
      plan,
      project: next,
    })
    setError('')
  }

  async function generateVideo() {
    if (!canGenerateVideo) {
      setError('请先生成文稿和分镜，再生成视频。')
      return
    }

    if (!window.confirm('这一步会调用视频生成接口，可能消耗 fal.ai / TTS / R2 额度。确认继续？')) return

    setBusy('generate-video')
    setError('')

    try {
      const payload = buildFullAiPayload(project)
      const data = await apiPost('/api/video/full-ai/start', payload, 240000)
      setResult(data)
      patch({ lastOutput: data })
    } catch (err: any) {
      setError(detailToText(err?.message || err))
    } finally {
      setBusy('')
    }
  }

  const previewSegments = project.segments.length
    ? project.segments
    : splitScriptToSegments(project.script, plan.duration, project.materialSeconds, project.aiShotSeconds)

  return (
    <section className="productPanel">
      <div className="productHero">
        <div>
          <p className="productEyebrow">PURE AI VIDEO PATH</p>
          <h2>纯 AI 生成路径</h2>
          <p>
            先选主题和视频长度，生成文稿、分镜和剪辑分配；文稿生成后才能调用视频生成接口。真实房源、户型、价格和周边不允许 AI 编造。
          </p>
        </div>
        <span className="productBadge danger">可能调用 fal.ai</span>
      </div>

      <div className="topicRow">
        {topics.map((item) => (
          <button
            type="button"
            key={item}
            className={project.topic === item ? 'active' : ''}
            onClick={() => patch({ topic: item })}
          >
            {item}
          </button>
        ))}
      </div>

      <div className="productFormGrid">
        <label>
          市场
          <input value={project.market} onChange={(event) => patch({ market: event.target.value })} />
        </label>
        <label>
          主题 / 选题
          <input value={project.topic} onChange={(event) => patch({ topic: event.target.value })} />
        </label>
        <label>
          目标视频长度/秒
          <input
            type="number"
            value={project.targetDuration}
            onChange={(event) => patch({ targetDuration: Number(event.target.value || 28) })}
          />
        </label>
        <label>
          已选素材总时长/秒
          <input
            type="number"
            value={project.materialSeconds}
            onChange={(event) => patch({ materialSeconds: Number(event.target.value || 0) })}
          />
        </label>
        <label>
          单个 AI 镜头秒数
          <input
            type="number"
            value={project.aiShotSeconds}
            onChange={(event) => patch({ aiShotSeconds: Number(event.target.value || 7) })}
          />
        </label>
        <label className="checkLabel">
          <input
            type="checkbox"
            checked={project.allowFal}
            onChange={(event) => patch({ allowFal: event.target.checked })}
          />
          素材不足时允许 fal.ai 补通用氛围镜头
        </label>
      </div>

      <div className="productGrid four">
        <div className="metricCard">
          <b>{plan.suggestedChars}</b>
          <span>建议文案字数</span>
        </div>
        <div className="metricCard">
          <b>{plan.segmentCount}</b>
          <span>口播段数</span>
        </div>
        <div className="metricCard">
          <b>{plan.missingSeconds}s</b>
          <span>素材缺口</span>
        </div>
        <div className="metricCard">
          <b>{plan.aiShots}</b>
          <span>预计 AI 镜头</span>
        </div>
      </div>

      <div className="productNotice">
        按 {plan.duration}s 视频长度生成文稿；每段约 {plan.avgSegmentSeconds}s。配音、字幕和剪辑会按分段走，不再让生成视频绕过文稿。
      </div>

      <div className="productButtonRow">
        <button type="button" onClick={generateScript}>
          按视频长度生成文稿/分镜
        </button>
        <button type="button" className="red" disabled={!canGenerateVideo || !!busy} onClick={generateVideo}>
          生成完整 AI 视频
        </button>
        <button type="button" className="ghost" onClick={() => goTab?.('douyin')}>
          先去抖音采集选题
        </button>
        <button type="button" className="ghost" onClick={() => goTab?.('openclaw')}>
          先看获客线索
        </button>
      </div>

      {error && <div className="productError">{error}</div>}
      {busy && <div className="productNotice">处理中：{busy}</div>}

      <div className="twoCol">
        <div className="resultCard">
          <h3>文稿</h3>
          {project.script ? <pre>{project.script}</pre> : <p>先生成文稿，生成视频按钮才可用。</p>}
        </div>
        <div className="resultCard">
          <h3>配音 / 剪辑分配</h3>
          {previewSegments.map((segment) => (
            <div className="segmentCard" key={segment.index}>
              <b>
                第{segment.index}段 · {segment.duration}s
              </b>
              <span>{segment.material}</span>
              <p>{segment.text}</p>
              <em>{segment.edit}</em>
            </div>
          ))}
        </div>
      </div>

      {result && (
        <details className="resultJson">
          <summary>查看接口结果</summary>
          <pre>{JSON.stringify(result, null, 2)}</pre>
        </details>
      )}
    </section>
  )
}
