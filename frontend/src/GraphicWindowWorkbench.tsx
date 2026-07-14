import React, { useMemo } from 'react'
import { ProjectDraft, WorkspaceTab } from './aiVideoApi'

type Props = {
  project: ProjectDraft
  goTab: (tab: WorkspaceTab) => void
}

export default function GraphicWindowWorkbench({ project, goTab }: Props) {
  const jobId = String(
    project.currentJobId ||
    project.job_id ||
    project.full_ai_job_id ||
    '',
  )
  const src = useMemo(() => {
    const url = new URL('/graphic-window/', window.location.origin)
    url.searchParams.set('embedded', '1')
    url.searchParams.set('source', 'left_navigation')
    if (jobId) url.searchParams.set('job_id', jobId)
    return url.toString()
  }, [jobId])

  return (
    <section className="aiw-card aiw-graphicWorkbench">
      <div className="aiw-hero">
        <div>
          <p className="aiw-eyebrow">GRAPHIC / PUBLISH PACKAGE</p>
          <h2>图文窗口</h2>
          <p>在当前主界面内完成 3 套封面、7 页小红书图文、发布文案和最终交付包装。</p>
        </div>
        <span className={jobId ? 'aiw-badge ok' : 'aiw-badge'}>
          {jobId ? `当前任务 ${jobId}` : '等待视频任务'}
        </span>
      </div>
      {!jobId && (
        <div className="aiw-info">
          先在“视频创作”生成成片。任务生成后这里会自动绑定同一个 job_id，不会使用其他历史任务替代。
        </div>
      )}
      <div className="aiw-actions">
        <button className="aiw-muted" onClick={() => goTab('pureai')}>返回视频创作</button>
      </div>
      <iframe
        key={src}
        className="aiw-graphicFrame"
        src={src}
        title="图文窗口"
        allow="clipboard-read; clipboard-write; fullscreen"
      />
    </section>
  )
}
