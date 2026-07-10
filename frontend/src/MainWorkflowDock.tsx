import React, {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from 'react'

import './main-workflow-v10-40.css'

type JsonMap = Record<string, any>

const ACTIVE_JOB_KEY = 'ai_video_workflow_active_job_v10_40'
const PANEL_OPEN_KEY = 'ai_video_workflow_panel_open_v10_40'
const DRAFT_KEYS = [
  'ai_video_wizard_draft_v10_13',
  'ai_video_wizard_draft_v10_40',
  'ai_video_engineering_project_draft_v16',
  'ai_video_engineering_project_draft_v15',
]

const ACTION_TEXT: Record<string, string> = {
  wait_for_video: '视频正在生成',
  fix_video_job: '视频任务需要处理',
  run_review: '等待启动自动审片',
  wait_for_review: '自动审片进行中',
  human_review: '等待人工确认',
  return_to_edit: '已驳回，返回修改',
  backfill_packaging: '等待生成封面与图文',
  select_cover: '请选择主封面',
  build_final_delivery: '等待生成总交付包',
  ready_to_publish: '发布素材已齐全',
}

function safeParse(value: string | null): JsonMap {
  if (!value) return {}

  try {
    const parsed = JSON.parse(value)
    return parsed && typeof parsed === 'object'
      ? parsed
      : {}
  } catch {
    return {}
  }
}

function readCurrentJobId(): string {
  try {
    const active = String(
      window.localStorage.getItem(ACTIVE_JOB_KEY) || ''
    ).trim()

    if (active) return active

    for (const key of DRAFT_KEYS) {
      const draft = safeParse(
        window.localStorage.getItem(key)
      )
      const candidate = String(
        draft.jobId ||
        draft.job_id ||
        draft.job?.job_id ||
        ''
      ).trim()

      if (candidate) return candidate
    }

    const keys = Object.keys(window.localStorage)

    for (const key of keys) {
      if (
        !key.includes('wizard_draft') &&
        !key.includes('project_draft')
      ) {
        continue
      }

      const draft = safeParse(
        window.localStorage.getItem(key)
      )
      const candidate = String(
        draft.jobId ||
        draft.job_id ||
        draft.job?.job_id ||
        ''
      ).trim()

      if (candidate) return candidate
    }
  } catch {}

  return ''
}

async function requestJson(
  path: string,
  options: RequestInit = {},
  timeoutMs = 240000,
): Promise<JsonMap> {
  const controller = new AbortController()
  const timer = window.setTimeout(
    () => controller.abort(),
    timeoutMs,
  )

  try {
    const response = await fetch(path, {
      ...options,
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        ...(options.headers || {}),
      },
      signal: controller.signal,
    })

    const text = await response.text()
    let data: any = {}

    try {
      data = text ? JSON.parse(text) : {}
    } catch {
      data = {
        ok: false,
        detail: text || `HTTP ${response.status}`,
      }
    }

    if (!response.ok) {
      const detail =
        data?.detail?.detail ||
        data?.detail ||
        data?.message ||
        data?.error ||
        `HTTP ${response.status}`

      throw new Error(
        typeof detail === 'string'
          ? detail
          : JSON.stringify(detail)
      )
    }

    return data
  } finally {
    window.clearTimeout(timer)
  }
}

function asArray(value: any): any[] {
  return Array.isArray(value) ? value : []
}

function asObject(value: any): JsonMap {
  return value && typeof value === 'object'
    ? value
    : {}
}

function videoUrl(job: JsonMap): string {
  const result = asObject(job.result)
  const child = asObject(job.child_job)
  const childResult = asObject(child.result)

  const value =
    job.subtitled_video_url ||
    result.subtitled_video_url ||
    child.subtitled_video_url ||
    childResult.subtitled_video_url ||
    job.video_url ||
    job.output_url ||
    job.result_url ||
    job.url ||
    result.video_url ||
    result.output_url ||
    result.result_url ||
    child.video_url ||
    child.output_url ||
    child.result_url ||
    child.url ||
    childResult.video_url ||
    childResult.output_url ||
    childResult.result_url

  return typeof value === 'string' ? value : ''
}

function reviewIssues(review: JsonMap): JsonMap[] {
  const doubao = asObject(
    review.doubao || review.ai_review
  )
  const sources = [
    review.issues,
    review.problems,
    doubao.issues,
    doubao.problems,
    doubao.findings,
  ]

  for (const source of sources) {
    const values = asArray(source)
    if (values.length) {
      return values.filter(
        (item) => item && typeof item === 'object'
      )
    }
  }

  const checks = asArray(
    asObject(review.mechanical).checks
  )

  return checks
    .filter((item) => item?.passed === false)
    .map((item) => ({
      severity: item.severity,
      description: item.detail || item.name,
      suggestion: '返回对应环节检查后重新生成。',
      source: 'mechanical',
    }))
}

function packagingResults(
  workflow: JsonMap,
): {
  cover: JsonMap
  xhs: JsonMap
} {
  const packaging = asObject(workflow.packaging)
  const automation = asObject(packaging.automation)
  const review = asObject(workflow.review)

  const directCover = asObject(
    packaging.cover_result
  )
  const automationCover = asObject(
    automation.cover_result
  )
  const reviewCover = asObject(
    review.cover_result
  )

  const directXhs = asObject(
    packaging.xhs_result
  )
  const automationXhs = asObject(
    automation.xhs_result
  )

  const cover = Object.keys(directCover).length
    ? directCover
    : Object.keys(automationCover).length
      ? automationCover
      : reviewCover

  const xhs = Object.keys(directXhs).length
    ? directXhs
    : automationXhs

  return {
    cover,
    xhs,
  }
}

function actionTarget(issue: JsonMap): 'script' | 'voice' | 'shot' {
  const text = [
    issue.type,
    issue.category,
    issue.description,
    issue.problem,
    issue.suggestion,
  ].join(' ')

  if (/配音|声音|语速|音量|停顿|口型|音频/.test(text)) {
    return 'voice'
  }

  if (/文案|口播|字幕|错字|脚本|事实|数字/.test(text)) {
    return 'script'
  }

  return 'shot'
}

function dispatchEdit(
  target: 'script' | 'voice' | 'shot',
  issue?: JsonMap,
) {
  window.dispatchEvent(
    new CustomEvent('ai-video-workflow-edit', {
      detail: {
        target,
        issue: issue || null,
      },
    })
  )
}

function stageClass(state: string): string {
  if (state === 'done') return 'mw-stage is-done'
  if (state === 'active') return 'mw-stage is-active'
  return 'mw-stage'
}

function scoreLabel(value: any): string {
  const score = Number(value)
  return Number.isFinite(score) && score > 0
    ? `${score} 分`
    : '未评分'
}

function formatTime(value: any): string {
  const numeric = Number(value)
  if (!numeric) return ''

  const date = new Date(
    numeric > 10_000_000_000
      ? numeric
      : numeric * 1000
  )

  return Number.isNaN(date.getTime())
    ? ''
    : date.toLocaleString()
}

export default function MainWorkflowDock() {
  const [jobId, setJobId] = useState(
    () => readCurrentJobId()
  )
  const [manualJobId, setManualJobId] = useState(jobId)
  const [workflow, setWorkflow] = useState<JsonMap>({})
  const [open, setOpen] = useState(
    () => window.localStorage.getItem(PANEL_OPEN_KEY) !== '0'
  )
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [lastRefresh, setLastRefresh] = useState(0)

  const refresh = useCallback(async (
    silent = false,
    explicitJobId = '',
  ) => {
    const target = String(
      explicitJobId || jobId || readCurrentJobId()
    ).trim()

    if (!target) {
      setWorkflow({})
      return
    }

    if (!silent) setBusy('refresh')

    try {
      const data = await requestJson(
        `/api/video/workflow/${encodeURIComponent(target)}`,
        {},
        90000,
      )

      if (
        data.job_id &&
        String(data.job_id) !== target
      ) {
        throw new Error(
          '后端返回了不同任务 ID，已阻止串任务。'
        )
      }

      setWorkflow(data)
      setJobId(target)
      setManualJobId(target)
      setError('')
      setLastRefresh(Date.now())

      window.localStorage.setItem(
        ACTIVE_JOB_KEY,
        target,
      )
      window.localStorage.setItem(
        `ai_video_workflow_v10_40_1_${target}`,
        JSON.stringify(data),
      )
    } catch (err: any) {
      if (!silent) {
        setError(
          err?.message || String(err)
        )
      }
    } finally {
      if (!silent) setBusy('')
    }
  }, [jobId])

  const runAction = useCallback(async (
    name: string,
    path: string,
    payload: JsonMap = {},
  ) => {
    if (!jobId || busy) return

    setBusy(name)
    setError('')

    try {
      const data = await requestJson(
        path,
        {
          method: 'POST',
          body: JSON.stringify(payload),
        },
        420000,
      )
      setWorkflow(data)
      setLastRefresh(Date.now())

      window.localStorage.setItem(
        `ai_video_workflow_v10_40_1_${jobId}`,
        JSON.stringify(data),
      )
    } catch (err: any) {
      setError(
        err?.message || String(err)
      )
    } finally {
      setBusy('')
    }
  }, [jobId, busy])

  useEffect(() => {
    const discover = () => {
      const next = readCurrentJobId()

      if (next && next !== jobId) {
        setJobId(next)
        setManualJobId(next)
        setWorkflow({})
        setOpen(true)
      }
    }

    const acceptWorkflowJob = (event: Event) => {
      const detail = (
        event as CustomEvent<{
          job_id?: string
        }>
      ).detail || {}
      const next = String(
        detail.job_id || readCurrentJobId()
      ).trim()

      if (!next) return

      setJobId(next)
      setManualJobId(next)
      setWorkflow({})
      setOpen(true)
    }

    const openWorkflow = () => {
      setOpen(true)
      discover()
    }

    const timer = window.setInterval(
      discover,
      2000,
    )
    window.addEventListener(
      'storage',
      discover,
    )
    window.addEventListener(
      'ai-video-workflow-job',
      acceptWorkflowJob as EventListener,
    )
    window.addEventListener(
      'ai-video-workflow-open',
      openWorkflow,
    )

    return () => {
      window.clearInterval(timer)
      window.removeEventListener(
        'storage',
        discover,
      )
      window.removeEventListener(
        'ai-video-workflow-job',
        acceptWorkflowJob as EventListener,
      )
      window.removeEventListener(
        'ai-video-workflow-open',
        openWorkflow,
      )
    }
  }, [jobId])

  useEffect(() => {
    window.localStorage.setItem(
      PANEL_OPEN_KEY,
      open ? '1' : '0',
    )
  }, [open])

  useEffect(() => {
    if (!jobId) return

    let alive = true

    const load = async () => {
      if (!alive) return
      await refresh(true)
    }

    load()

    const nextAction = String(
      workflow.next_action || ''
    )
    const interval = nextAction === 'ready_to_publish'
      ? 20000
      : 6000

    const timer = window.setInterval(
      load,
      interval,
    )

    return () => {
      alive = false
      window.clearInterval(timer)
    }
  }, [
    jobId,
    workflow.next_action,
    refresh,
  ])

  const job = asObject(workflow.job)
  const review = asObject(workflow.review)
  const gate = asObject(workflow.gate)
  const selection = asObject(workflow.selection)
  const delivery = asObject(workflow.delivery)
  const stages = asArray(workflow.stages)
  const issues = useMemo(
    () => reviewIssues(review),
    [review],
  )
  const results = useMemo(
    () => packagingResults(workflow),
    [workflow],
  )
  const covers = asArray(results.cover.images)
  const xhsPages = asArray(results.xhs.images)
  const currentVideoUrl = videoUrl(job)
  const nextAction = String(
    workflow.next_action || 'wait_for_video'
  )
  const activeStage = Number(
    workflow.stage_index || 1
  )

  function bindManualJob() {
    const target = manualJobId.trim()
    if (!target) return

    window.localStorage.setItem(
      ACTIVE_JOB_KEY,
      target,
    )
    setJobId(target)
    setWorkflow({})
    refresh(false, target)
  }

  function isSelectedCover(
    item: JsonMap,
    index: number,
  ): boolean {
    if (
      selection.url &&
      item.url === selection.url
    ) {
      return true
    }

    return Number(selection.index) === index
  }

  const actionArea = (() => {
    if (!jobId) {
      return (
        <div className="mw-empty">
          主界面还没有统一任务。点击“生成视频并下载 MP4”后会自动登记并启动审片，也可以绑定历史任务 ID。
        </div>
      )
    }

    if (nextAction === 'wait_for_video') {
      return (
        <div className="mw-notice">
          视频仍在生成，当前只查询这个任务，不会使用“最近任务”替代。
        </div>
      )
    }

    if (nextAction === 'fix_video_job') {
      return (
        <div className="mw-action-row">
          <button
            className="mw-btn danger"
            onClick={() => dispatchEdit('shot')}
          >
            返回镜头与素材修改
          </button>
        </div>
      )
    }

    if (nextAction === 'run_review') {
      return (
        <div className="mw-action-row">
          <button
            className="mw-btn primary"
            disabled={Boolean(busy)}
            onClick={() => runAction(
              'review',
              `/api/video/workflow/${encodeURIComponent(jobId)}/run-review`,
              {},
            )}
          >
            {busy === 'review'
              ? '正在审片…'
              : '启动机械质检 + 豆包审片'}
          </button>
        </div>
      )
    }

    if (nextAction === 'wait_for_review') {
      return (
        <div className="mw-notice">
          自动审片进行中，结果完成后会在这里显示问题和时间段。
        </div>
      )
    }

    if (nextAction === 'return_to_edit') {
      return (
        <div className="mw-action-stack">
          <button
            className="mw-btn danger"
            onClick={() => dispatchEdit('shot')}
          >
            返回镜头与素材修复
          </button>
          <button
            className="mw-btn"
            onClick={() => dispatchEdit('script')}
          >
            返回文案与字幕修复
          </button>
          <button
            className="mw-btn primary"
            disabled={Boolean(busy)}
            onClick={() => runAction(
              'review',
              `/api/video/workflow/${encodeURIComponent(jobId)}/run-review`,
              {
                force: true,
                source: 'human_retry_after_fix',
              },
            )}
          >
            {busy === 'review'
              ? '正在重新审片…'
              : '修复后重新审片'}
          </button>
        </div>
      )
    }

    if (nextAction === 'human_review') {
      return (
        <div className="mw-action-stack">
          <button
            className="mw-btn primary"
            disabled={Boolean(busy)}
            onClick={() => runAction(
              'approve',
              `/api/video/workflow/${encodeURIComponent(jobId)}/approve`,
              {
                title:
                  job?.request?.title ||
                  job?.request?.topic ||
                  '',
                script_text:
                  job?.request?.script_text ||
                  '',
                reviewer: 'human_main_interface',
              },
            )}
          >
            {busy === 'approve'
              ? '通过并生成发布素材…'
              : '人工通过并自动生成封面 + 图文'}
          </button>

          <button
            className="mw-btn"
            disabled={Boolean(busy)}
            onClick={() => runAction(
              'override',
              `/api/video/workflow/${encodeURIComponent(jobId)}/human-override`,
              {
                decision: 'approved',
                status: 'approved',
                note:
                  '人工完整观看后确认自动审片提示为误报',
                reason:
                  '人工完整观看后确认自动审片提示为误报',
              },
            )}
          >
            {busy === 'override'
              ? '正在覆盖误报…'
              : '确认误报并通过'}
          </button>

          <button
            className="mw-btn danger"
            disabled={Boolean(busy)}
            onClick={() => runAction(
              'reject',
              `/api/video/workflow/${encodeURIComponent(jobId)}/reject`,
              {
                reason:
                  '主界面人工驳回，返回文案或镜头修改',
              },
            )}
          >
            驳回并返回修改
          </button>
        </div>
      )
    }

    if (nextAction === 'backfill_packaging') {
      return (
        <div className="mw-action-row">
          <button
            className="mw-btn primary"
            disabled={Boolean(busy)}
            onClick={() => runAction(
              'backfill',
              `/api/video/workflow/${encodeURIComponent(jobId)}/backfill-packaging`,
              {
                title:
                  job?.request?.title ||
                  job?.request?.topic ||
                  '',
                script_text:
                  job?.request?.script_text ||
                  '',
              },
            )}
          >
            {busy === 'backfill'
              ? '正在补齐 3 + 7 素材…'
              : '补齐 3 套封面 + 7 页图文'}
          </button>
        </div>
      )
    }

    if (nextAction === 'select_cover') {
      return (
        <div className="mw-notice">
          点击下面任意封面设为主封面，再生成最终交付包。
        </div>
      )
    }

    if (nextAction === 'build_final_delivery') {
      return (
        <div className="mw-action-row">
          <button
            className="mw-btn primary"
            disabled={Boolean(busy)}
            onClick={() => runAction(
              'finalize',
              `/api/video/workflow/${encodeURIComponent(jobId)}/finalize`,
              {},
            )}
          >
            {busy === 'finalize'
              ? '正在打包最终交付物…'
              : '生成视频 + 封面 + 图文总交付包'}
          </button>
        </div>
      )
    }

    if (nextAction === 'ready_to_publish') {
      return (
        <div className="mw-ready">
          <strong>发布素材已经齐全</strong>
          <span>
            视频、主封面、全部封面、7 页图文、发布文案、审片报告和事实链已关联到同一个任务。
          </span>
          {delivery.download_zip_url && (
            <a
              className="mw-btn primary"
              href={delivery.download_zip_url}
              target="_blank"
              rel="noreferrer"
            >
              下载最终总交付包
            </a>
          )}
        </div>
      )
    }

    return null
  })()

  if (!open) {
    return (
      <button
        className="mw-collapsed"
        onClick={() => setOpen(true)}
        title="打开 AI 视频完整工作流"
      >
        <span className="mw-collapsed-dot" />
        工作流 {activeStage}/6
      </button>
    )
  }

  return (
    <aside className="mw-dock" aria-label="AI 视频完整工作流">
      <header className="mw-header">
        <div>
          <span className="mw-kicker">V10.40.1 真实主界面联动</span>
          <h2>完整发布工作流</h2>
        </div>
        <div className="mw-header-actions">
          <button
            className="mw-icon-btn"
            onClick={() => refresh(false)}
            disabled={busy === 'refresh'}
            title="刷新"
          >
            ↻
          </button>
          <button
            className="mw-icon-btn"
            onClick={() => setOpen(false)}
            title="收起"
          >
            —
          </button>
        </div>
      </header>

      <div className="mw-bind">
        <input
          value={manualJobId}
          onChange={(event: { target: { value: string } }) => setManualJobId(event.target.value)}
          placeholder="当前 job_id"
          spellCheck={false}
        />
        <button onClick={bindManualJob}>
          绑定
        </button>
      </div>

      <div className="mw-job-meta">
        <span>
          {jobId
            ? `任务：${jobId}`
            : '尚未绑定任务'}
        </span>
        <span>
          {ACTION_TEXT[nextAction] || nextAction}
        </span>
      </div>

      <div className="mw-stages">
        {(stages.length ? stages : [
          { index: 1, label: '内容来源', state: 'pending' },
          { index: 2, label: '文案与声音', state: 'pending' },
          { index: 3, label: '镜头与素材', state: 'pending' },
          { index: 4, label: '成片与审查', state: 'pending' },
          { index: 5, label: '封面与图文', state: 'pending' },
          { index: 6, label: '发布与交付', state: 'pending' },
        ]).map((stage) => (
          <div
            className={stageClass(stage.state)}
            key={stage.index}
          >
            <span>{stage.index}</span>
            <small>{stage.label}</small>
          </div>
        ))}
      </div>

      <div className="mw-body">
        {error && (
          <div className="mw-error">{error}</div>
        )}

        {currentVideoUrl && (
          <section className="mw-section">
            <div className="mw-section-title">
              <strong>成片</strong>
              <span>
                {job.status || '已生成'} · {job.progress ?? 100}%
              </span>
            </div>
            <video
              className="mw-video"
              src={currentVideoUrl}
              controls
              playsInline
              preload="metadata"
            />
          </section>
        )}

        {Object.keys(review).length > 0 && (
          <section className="mw-section">
            <div className="mw-section-title">
              <strong>审片结果</strong>
              <span>
                综合 {scoreLabel(review.overall_score)}
              </span>
            </div>

            <div className="mw-score-grid">
              <div>
                <span>机械质检</span>
                <b>
                  {scoreLabel(
                    asObject(review.mechanical).score
                  )}
                </b>
              </div>
              <div>
                <span>豆包审片</span>
                <b>
                  {scoreLabel(
                    asObject(
                      review.doubao || review.ai_review
                    ).score
                  )}
                </b>
              </div>
              <div>
                <span>人工状态</span>
                <b>{review.status || '待确认'}</b>
              </div>
            </div>

            {review.summary && (
              <p className="mw-summary">
                {review.summary}
              </p>
            )}

            {issues.length > 0 && (
              <div className="mw-issues">
                {issues.slice(0, 8).map((issue, index) => {
                  const target = actionTarget(issue)
                  const title =
                    issue.description ||
                    issue.problem ||
                    issue.detail ||
                    issue.type ||
                    `问题 ${index + 1}`

                  return (
                    <article
                      className="mw-issue"
                      key={`${index}-${title}`}
                    >
                      <div className="mw-issue-top">
                        <span>
                          {issue.severity || '提醒'}
                        </span>
                        <small>
                          {issue.time_range ||
                           issue.timestamp ||
                           issue.start_time ||
                           (
                             issue.start !== undefined
                               ? `${issue.start}s–${issue.end ?? '?'}s`
                               : ''
                           )}
                        </small>
                      </div>
                      <p>{title}</p>
                      {issue.suggestion && (
                        <small>{issue.suggestion}</small>
                      )}
                      <button
                        onClick={() => dispatchEdit(
                          target,
                          issue,
                        )}
                      >
                        返回
                        {target === 'script'
                          ? '文案'
                          : target === 'voice'
                            ? '配音'
                            : '镜头'}
                        修改
                      </button>
                    </article>
                  )
                })}
              </div>
            )}
          </section>
        )}

        {actionArea}

        {covers.length > 0 && (
          <section className="mw-section">
            <div className="mw-section-title">
              <strong>3 套视频封面</strong>
              <span>
                {selection.url
                  ? '已选择主封面'
                  : '点击选择主封面'}
              </span>
            </div>

            <div className="mw-cover-grid">
              {covers.map((item, index) => (
                <button
                  className={
                    isSelectedCover(item, index)
                      ? 'mw-cover is-selected'
                      : 'mw-cover'
                  }
                  key={item.url || index}
                  disabled={Boolean(busy)}
                  onClick={() => runAction(
                    'select-cover',
                    `/api/video/workflow/${encodeURIComponent(jobId)}/select-cover`,
                    {
                      index,
                      url: item.url,
                    },
                  )}
                >
                  <img
                    src={item.url}
                    alt={item.title || `封面 ${index + 1}`}
                    loading="lazy"
                  />
                  <span>
                    {isSelectedCover(item, index)
                      ? '主封面'
                      : `方案 ${index + 1}`}
                  </span>
                </button>
              ))}
            </div>

            {results.cover.download_zip_url && (
              <a
                className="mw-text-link"
                href={results.cover.download_zip_url}
                target="_blank"
                rel="noreferrer"
              >
                下载 3 套封面包
              </a>
            )}
          </section>
        )}

        {xhsPages.length > 0 && (
          <section className="mw-section">
            <div className="mw-section-title">
              <strong>小红书 7 页图文</strong>
              <span>{xhsPages.length} 页</span>
            </div>

            <div className="mw-xhs-strip">
              {xhsPages.map((item, index) => (
                <a
                  href={item.url}
                  target="_blank"
                  rel="noreferrer"
                  key={item.url || index}
                >
                  <img
                    src={item.url}
                    alt={item.title || `图文 ${index + 1}`}
                    loading="lazy"
                  />
                  <span>{index + 1}</span>
                </a>
              ))}
            </div>

            <div className="mw-link-row">
              {results.xhs.download_zip_url && (
                <a
                  className="mw-text-link"
                  href={results.xhs.download_zip_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  下载图文包
                </a>
              )}

              {results.xhs.content_trace_url && (
                <a
                  className="mw-text-link"
                  href={results.xhs.content_trace_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  查看事实链
                </a>
              )}
            </div>
          </section>
        )}

        {delivery.download_zip_url && (
          <section className="mw-section mw-delivery-card">
            <div className="mw-section-title">
              <strong>最终交付包</strong>
              <span>
                {formatTime(delivery.created_at)}
              </span>
            </div>
            <p>
              已包含最终视频、主封面、全部封面、7 页图文、发布文案、审片报告和工作流清单。
            </p>
            <a
              className="mw-btn primary"
              href={delivery.download_zip_url}
              target="_blank"
              rel="noreferrer"
            >
              下载最终总包
            </a>
          </section>
        )}
      </div>

      <footer className="mw-footer">
        <span>
          严格绑定 job_id，不使用最近任务替代
        </span>
        <span>
          {lastRefresh
            ? `更新 ${new Date(lastRefresh).toLocaleTimeString()}`
            : '等待数据'}
        </span>
      </footer>
    </aside>
  )
}
