import React, { useEffect, useMemo, useRef, useState } from 'react'
import {
  apiGet,
  apiPost,
  detailToText,
  ProjectDraft,
  WorkspaceTab,
} from './aiVideoApi'

type Props = {
  project: ProjectDraft
  setProject: (project: ProjectDraft) => void
  goTab: (tab: WorkspaceTab) => void
}

const API = '/api/video/integration'

function rows(value: any): any[] {
  if (Array.isArray(value)) return value
  if (!value || typeof value !== 'object') return []
  for (const key of ['items', 'leads', 'comment_leads', 'rows', 'data', 'results']) {
    if (Array.isArray(value[key])) return value[key]
  }
  return []
}

function statusDone(value: string) {
  return /done|completed|success|finished/i.test(value)
}

function statusFailed(value: string) {
  return /fail|error|cancel|reject/i.test(value)
}

export default function OpenClawWorkbench({ project, setProject, goTab }: Props) {
  const [health, setHealth] = useState<any>(null)
  const [jobId, setJobId] = useState(String(project.openclaw_job_id || ''))
  const [job, setJob] = useState<any>(project.openclaw_job || null)
  const [keyword, setKeyword] = useState(String(project.topic || '吉隆坡买房'))
  const [targets, setTargets] = useState(String(project.openclaw_target_accounts || ''))
  const [mode, setMode] = useState<'accounts' | 'comments'>('comments')
  const [leads, setLeads] = useState<any[]>(Array.isArray(project.current_task_leads) ? project.current_task_leads : [])
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const polling = useRef<number | null>(null)

  const jobStatus = String(job?.status || job?.stage || '')
  const online = health?.online === true
  const progress = Number(job?.raw?.progress || job?.progress || 0)
  const stats = useMemo(() => ({
    total: leads.length,
    high: leads.filter((item) => Number(item.score || item.lead_score || 0) >= 70).length,
    current: leads.filter((item) => String(item.job_id || item.run_id || '') === jobId).length,
  }), [leads, jobId])

  async function refreshHealth() {
    setBusy('检查 OpenClaw')
    setError('')
    try {
      const data = await apiGet(`${API}/openclaw/status`, 60000)
      setHealth(data)
      return data
    } catch (err) {
      setError(detailToText(err))
      return null
    } finally {
      setBusy('')
    }
  }

  async function refreshLeads() {
    try {
      const data = await apiGet('/api/video/comment-leads/recent?limit=300', 90000)
      const next = rows(data)
      setLeads(next)
      setProject({
        ...project,
        current_task_leads: next.filter((item) => String(item.job_id || item.run_id || '') === jobId),
        historical_leads: next,
        openclaw_job_id: jobId,
        openclaw_job: job,
      })
    } catch {
      // Upstream lead endpoint is optional; job state remains available.
    }
  }

  async function poll(targetJobId = jobId) {
    if (!targetJobId) return
    try {
      const data = await apiGet(`${API}/openclaw/job/${encodeURIComponent(targetJobId)}`, 90000)
      setJob(data)
      setProject({ ...project, openclaw_job_id: targetJobId, openclaw_job: data })
      const state = String(data?.status || '')
      if (statusDone(state)) {
        setNotice('真实采集任务已完成，可以沉淀客户问题和刷新线索。')
        await refreshLeads()
      }
      if (statusFailed(state)) setError(`OpenClaw 任务失败：${state}`)
    } catch (err) {
      setError(detailToText(err))
    }
  }

  useEffect(() => {
    void refreshHealth()
    if (jobId) void poll(jobId)
    return () => {
      if (polling.current) window.clearInterval(polling.current)
    }
  }, [])

  useEffect(() => {
    if (polling.current) window.clearInterval(polling.current)
    if (!jobId || statusDone(jobStatus) || statusFailed(jobStatus)) return
    polling.current = window.setInterval(() => void poll(jobId), 6000)
    return () => {
      if (polling.current) window.clearInterval(polling.current)
    }
  }, [jobId, jobStatus])

  async function start() {
    setBusy('启动真实采集')
    setError('')
    setNotice('')
    try {
      const state = await apiGet(`${API}/openclaw/status`, 60000)
      setHealth(state)
      if (!state?.online) throw new Error('OpenClaw 离线，无法开始采集。请先启动 worker 并确认抖音账号登录。')
      const data = await apiPost(
        `${API}/openclaw/start`,
        {
          mission_type: mode === 'accounts' ? 'competitor' : 'comments',
          platform: 'douyin',
          market: project.market,
          keyword,
          keywords: [keyword, project.topic, project.market].filter(Boolean),
          seed_accounts: targets.split(/[，,\n]/).map((item) => item.trim()).filter(Boolean),
          max_accounts: mode === 'accounts' ? 30 : 10,
          max_videos_per_account: 12,
          max_comments_per_video: mode === 'comments' ? 100 : 30,
          collect_accounts: true,
          collect_videos: true,
          collect_comments: true,
        },
        240000,
      )
      const id = String(data?.job_id || '')
      if (!id) throw new Error('OpenClaw 没有返回真实 job_id，系统已阻止假成功。')
      setJobId(id)
      setJob(data)
      setProject({
        ...project,
        topic: keyword || project.topic,
        openclaw_job_id: id,
        openclaw_job: data,
        openclaw_target_accounts: targets,
      })
      setNotice(`真实采集任务已启动：${id}`)
    } catch (err) {
      setError(detailToText(err))
    } finally {
      setBusy('')
    }
  }

  async function harvest() {
    if (!jobId) {
      setError('没有真实 OpenClaw job_id。')
      return
    }
    setBusy('沉淀知识')
    setError('')
    try {
      const data = await apiPost(`${API}/openclaw/harvest/${encodeURIComponent(jobId)}`, {}, 240000)
      setNotice(`读取 ${data?.rows_read || 0} 条结果，新增 ${data?.added_to_brain || 0} 条知识候选。`)
      await refreshLeads()
    } catch (err) {
      setError(detailToText(err))
    } finally {
      setBusy('')
    }
  }

  function useLead(item: any) {
    const content = String(item.text || item.comment || item.question || item.content || '')
    setProject({
      ...project,
      topic: content.slice(0, 48) || project.topic,
      selected_openclaw_lead: item,
      selected_openclaw_job_id: jobId,
    })
    goTab('pureai')
  }

  return (
    <section className="aiw-card aiw-salesBoard">
      <div className="aiw-hero">
        <div>
          <p className="aiw-eyebrow">REAL OPENCLAW ORCHESTRATION</p>
          <h2>OpenClaw 截流工作台</h2>
          <p>先确认 worker 在线，再启动真实采集、轮询进度、沉淀客户问题。没有 job_id 就不会显示成功。</p>
        </div>
        <span className={online ? 'aiw-badge ok' : 'aiw-badge'}>
          {online ? 'OpenClaw 在线' : 'OpenClaw 离线'}
        </span>
      </div>

      <div className="aiw-metrics">
        <div><b>{progress || 0}%</b><span>任务进度</span></div>
        <div><b>{stats.current}</b><span>当前任务线索</span></div>
        <div><b>{stats.total}</b><span>历史线索</span></div>
        <div><b>{stats.high}</b><span>高意向</span></div>
      </div>

      <div className="aiw-form two">
        <label>
          采集关键词
          <input value={keyword} onChange={(event) => setKeyword(event.target.value)} />
        </label>
        <label>
          目标账号 / 主页链接
          <textarea value={targets} onChange={(event) => setTargets(event.target.value)} placeholder="每行一个账号或主页链接" />
        </label>
      </div>

      <div className="aiw-chipRow">
        <button className={mode === 'accounts' ? 'aiw-chip active' : 'aiw-chip'} onClick={() => setMode('accounts')}>同行账号采集</button>
        <button className={mode === 'comments' ? 'aiw-chip active' : 'aiw-chip'} onClick={() => setMode('comments')}>评论截流采集</button>
      </div>

      <div className="aiw-actions">
        <button className="aiw-muted" disabled={Boolean(busy)} onClick={refreshHealth}>{busy === '检查 OpenClaw' ? busy : '检查服务与登录状态'}</button>
        <button className="aiw-primary" disabled={Boolean(busy) || !online} onClick={start}>{busy === '启动真实采集' ? busy : '启动真实 OpenClaw 任务'}</button>
        <button className="aiw-muted" disabled={Boolean(busy) || !jobId} onClick={() => void poll()}>{jobId ? '刷新当前任务' : '没有任务 ID'}</button>
        <button className="aiw-purple" disabled={Boolean(busy) || !jobId} onClick={harvest}>沉淀到内容大脑</button>
        <button className="aiw-muted" onClick={() => goTab('brain')}>去审核知识</button>
      </div>

      <div className="aiw-panel">
        <h3>当前真实任务</h3>
        <div className="aiw-statusRows">
          <div><span>job_id</span><b>{jobId || '-'}</b></div>
          <div><span>状态</span><b>{jobStatus || '未启动'}</b></div>
          <div><span>实际接口</span><b>{job?.endpoint || health?.endpoint || '-'}</b></div>
          <div><span>最近进度</span><b>{progress || 0}%</b></div>
        </div>
      </div>

      <div className="aiw-panel">
        <h3>线索结果</h3>
        <div className="aiw-leadCards">
          {leads.slice(0, 30).map((item, index) => {
            const body = String(item.text || item.comment || item.question || item.content || '')
            const bound = String(item.job_id || item.run_id || '') === jobId
            return (
              <article className="aiw-leadCard" key={item.id || `${body}-${index}`}>
                <div className="aiw-leadHead"><b>{bound ? '当前任务' : '历史'} · {Number(item.score || item.lead_score || 0)}</b><span>{item.priority || item.grade || '待判断'}</span></div>
                <p>{body || '无正文'}</p>
                <div className="aiw-actions mini"><button onClick={() => useLead(item)}>转为生产选题</button></div>
              </article>
            )
          })}
          {!leads.length && <div className="aiw-empty">暂无真实采集结果。OpenClaw 离线时不会创建假任务。</div>}
        </div>
      </div>

      {notice && <div className="aiw-successPanel"><div><b>完成</b><span>{notice}</span></div></div>}
      {error && <div className="aiw-error">{error}</div>}
    </section>
  )
}
