import React, { useMemo, useState } from 'react'
import {
  apiPost,
  buildFullAiPayload,
  computeVideoPlan,
  detailToText,
  extractJobId,
  extractVideoUrl,
  generateLocalScript,
  generateAIScriptPlan,
  projectFromAIScriptPlan,
  pollFullAiJob,
  progressFromJob,
  ProjectDraft,
  splitScriptToSegments,
  WorkspaceTab,
} from './aiVideoApi'

type Props = {
  project: ProjectDraft
  setProject: (p: ProjectDraft) => void
  goTab: (tab: WorkspaceTab) => void
}

const topics = [
  '马来西亚买房，别只看价格',
  '第二家园怎么选房不踩坑',
  '吉隆坡公寓投资出租逻辑',
  '海外房产预算、区域、用途三步判断',
  '养老度假家庭资产配置',
]

function findVideoUrl(data: any) {
  return extractVideoUrl(data)
}

function ScriptPreview({ project }: { project: ProjectDraft }) {
  if (!project.script) {
    return <div className="aiw-info">还没有文稿。先按视频长度生成文稿和分镜，再生成视频。</div>
  }

  return (
    <div className="aiw-twoCol">
      <div className="aiw-panel">
        <h3>文稿</h3>
        <pre className="aiw-scriptBox">{project.script}</pre>
      </div>
      <div className="aiw-panel">
        <h3>配音 / 剪辑分配</h3>
        <div className="aiw-segmentList">
          {project.segments.map((seg) => (
            <div className="aiw-segment" key={seg.index}>
              <b>
                第{seg.index}段 · {seg.duration}s
              </b>
              <em>{seg.material}</em>
              <p>{seg.text}</p>
              <span>{seg.edit}</span>
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
  const [progress, setProgress] = useState<any>(null)

  const plan = useMemo(
    () => computeVideoPlan(project.targetDuration, project.materialSeconds, project.aiShotSeconds),
    [project.targetDuration, project.materialSeconds, project.aiShotSeconds],
  )

  const canGenerateVideo = Boolean(project.script && project.segments.length && !busy)
  const videoUrl = findVideoUrl(progress?.raw) || findVideoUrl(result) || findVideoUrl(project.lastOutput)

  function patch(next: Partial<ProjectDraft>) {
    setProject({ ...project, ...next })
  }

  async function generateDraft() {
    setBusy('draft')
    setError('')
    setProgress(null)

    try {
      setProgress({ status: 'script_ai', percent: 18, message: '正在结合行业爆点、同行打法和线索生成文稿...' })

      let nextProject: ProjectDraft
      let data: any = null

      try {
        data = await generateAIScriptPlan(project, false)
        nextProject = projectFromAIScriptPlan(project, data)
      } catch (aiErr) {
        const nonce = Date.now() + Math.round(Math.random() * 100000)
        const script = generateLocalScript(project.topic, project.market, plan.duration, nonce)
        const segments = splitScriptToSegments(script, plan.duration, plan.material, plan.shotSeconds)

        nextProject = {
          ...project,
          script,
          segments,
          title: project.topic,
          targetDuration: plan.duration,
          scriptProvider: 'local_fallback_after_frontend_error',
        }
        data = { ok: false, provider: 'local_fallback_after_frontend_error', error: detailToText(aiErr), script, segments, plan }
      }

      setProject(nextProject)
      setResult(data)
      setProgress({ status: 'script_ready', percent: 35, message: '文稿和分镜已生成，可以进入视频生成。' })
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

    const confirmText =
      plan.aiShotsRaw > 0
        ? `将调用视频生成接口。目标 ${plan.duration}s，素材缺 ${plan.missingSeconds}s，本次提交 ${shotCount} 个 AI 镜头。继续？`
        : '将调用视频生成接口。素材已够用，继续？'

    if (!window.confirm(confirmText)) return

    setBusy('video')
    setError('')
    setProgress({ status: 'submitting', percent: 8, message: '正在提交生成任务...' })

    try {
      const data = await apiPost('/api/video/full-ai/start', payload, 360000)
      const jobId = extractJobId(data)
      const firstProgress = progressFromJob(data, jobId)
      setResult(data)
      setProgress({ ...firstProgress, percent: Math.max(12, firstProgress.percent) })
      patch({ lastOutput: data })

      if (firstProgress.videoUrl) {
        setBusy('')
        return
      }

      if (!jobId) {
        setProgress({
          status: 'submitted',
          percent: 35,
          message: '任务已提交，但后端没有返回 job_id。请到任务历史查看。',
          raw: data,
        })
        setBusy('')
        return
      }

      const finalData = await pollFullAiJob(jobId, (next) => {
        setProgress(next)
      })

      setResult(finalData)
      setProgress(progressFromJob(finalData, jobId))
      patch({ lastOutput: finalData })
    } catch (err) {
      setError(detailToText(err))
      setProgress((old: any) => ({
        ...(old || {}),
        status: 'failed',
        percent: 100,
        message: '生成失败。',
      }))
    } finally {
      setBusy('')
    }
  }

  return (
    <section className="aiw-card">
      <div className="aiw-hero">
        <div>
          <p className="aiw-eyebrow">PURE AI / SCRIPT FIRST / RENDER AFTER</p>
          <h2>纯 AI 生成路径</h2>
          <p>
            先确定主题和视频长度，再生成文稿、分镜、配音/剪辑分配；没有文稿不能生成视频。真实房源、户型、价格和周边不允许 AI 编造。
          </p>
        </div>
        <span className={plan.aiShotsRaw > 0 ? 'aiw-badge danger' : 'aiw-badge ok'}>
          {plan.aiShotsRaw > 0 ? '素材不足会补 AI 镜头' : '素材够用'}
        </span>
      </div>

      <div className="aiw-chipRow">
        {topics.map((x) => (
          <button
            key={x}
            className={project.topic === x ? 'aiw-chip active' : 'aiw-chip'}
            onClick={() => patch({ topic: x })}
          >
            {x}
          </button>
        ))}
      </div>

      <div className="aiw-form four">
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
          <input
            type="number"
            min={8}
            value={project.targetDuration}
            onChange={(e) => patch({ targetDuration: Number(e.target.value || 28) })}
          />
        </label>
        <label>
          已选素材总时长/秒
          <input
            type="number"
            min={0}
            value={project.materialSeconds}
            onChange={(e) => patch({ materialSeconds: Number(e.target.value || 0) })}
          />
        </label>
        <label>
          单个 AI 镜头秒数
          <input
            type="number"
            min={3}
            value={project.aiShotSeconds}
            onChange={(e) => patch({ aiShotSeconds: Number(e.target.value || 7) })}
          />
        </label>
        <label className="aiw-check">
          <input type="checkbox" checked={project.allowFal} onChange={(e) => patch({ allowFal: e.target.checked })} />
          素材不足时允许 fal.ai 补通用氛围镜头
        </label>
      </div>

      <div className="aiw-metrics">
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

      <div className="aiw-info">
        按 {plan.duration}s 视频长度生成文稿；每段约 {plan.avgSegmentSeconds}s。点“生成文稿”会优先调用 DeepSeek，结合行业爆点、同行打法和获客线索生成，不再固定同一套文案。
      </div>

      <div className="aiw-actions">
        <button className="aiw-primary" onClick={generateDraft} disabled={!!busy}>
          {busy === 'draft' ? '生成中...' : '按视频长度生成文稿/分镜'}
        </button>
        <button className="aiw-danger" onClick={generateVideo} disabled={!canGenerateVideo}>
          {busy === 'video' ? '生成中...' : '生成完整 AI 视频'}
        </button>
        <button className="aiw-muted" onClick={() => goTab('collect')}>
          先去抖音采集选题
        </button>
        <button className="aiw-muted" onClick={() => goTab('leads')}>
          先看获客线索
        </button>
      </div>

      {progress && (
        <div className="aiw-progressCard">
          <div className="aiw-progressTop">
            <b>{progress.message || '生成中...'}</b>
            <span>{progress.percent || 0}%</span>
          </div>
          <div className="aiw-progressTrack">
            <div className="aiw-progressFill" style={{ width: `${Math.max(2, Math.min(100, progress.percent || 0))}%` }} />
          </div>
          <p>
            {progress.jobId ? `任务 ID：${progress.jobId}` : '正在等待后端返回任务编号'}
            {progress.status ? ` / 状态：${progress.status}` : ''}
          </p>
        </div>
      )}

      {error && <div className="aiw-error">{error}</div>}

      {videoUrl && (
        <div className="aiw-panel">
          <h3>成片预览</h3>
          <video className="aiw-video" src={videoUrl} controls playsInline />
          <div className="aiw-actions">
            <a className="aiw-linkButton" href={videoUrl} target="_blank" rel="noreferrer">
              打开成片链接
            </a>
          </div>
        </div>
      )}

      <ScriptPreview project={project} />

      {result && (
        <details className="aiw-json">
          <summary>接口/生成结果</summary>
          <pre>{JSON.stringify(result, null, 2)}</pre>
        </details>
      )}
    </section>
  )
}
