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
const OPENCLAW_PROFILE_KEY = 'ai_video_openclaw_profile_v10408'
const OPENCLAW_RUN_CACHE_KEY = 'ai_video_openclaw_run_cache_v10408'

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

function loadProfile() {
  try {
    return localStorage.getItem(OPENCLAW_PROFILE_KEY) || 'company_main'
  } catch {
    return 'company_main'
  }
}

function loadRunCache(profile: string) {
  try {
    const raw = localStorage.getItem(OPENCLAW_RUN_CACHE_KEY)
    const parsed = raw ? JSON.parse(raw) : {}
    return parsed && typeof parsed === 'object' ? parsed[profile] || null : null
  } catch {
    return null
  }
}

function saveRunCache(profile: string, value: any) {
  try {
    const raw = localStorage.getItem(OPENCLAW_RUN_CACHE_KEY)
    const parsed = raw ? JSON.parse(raw) : {}
    const next = parsed && typeof parsed === 'object' ? parsed : {}
    next[profile] = value
    localStorage.setItem(OPENCLAW_RUN_CACHE_KEY, JSON.stringify(next))
    localStorage.setItem(OPENCLAW_PROFILE_KEY, profile)
  } catch {}
}

export default function OpenClawWorkbench({ project, setProject, goTab }: Props) {
  const [health, setHealth] = useState<any>(null)
  const [accountProfile, setAccountProfile] = useState(String(project.openclaw_account_profile || loadProfile()))
  const cachedRun = loadRunCache(String(project.openclaw_account_profile || loadProfile()))
  const [jobId, setJobId] = useState(String(project.openclaw_job_id || cachedRun?.job_id || ''))
  const [job, setJob] = useState<any>(project.openclaw_job || cachedRun || null)
  const [runHistory, setRunHistory] = useState<any[]>([])
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
  const backendOnline = health?.backend_online === true || online
  const progress = Number(job?.progress || job?.raw?.progress || 0)
  const runCounts = job?.counts && typeof job.counts === 'object' ? job.counts : {}
  const workerOnline = health?.worker_online === true
  const loginOk = health?.login_ok === true
  const taskQueued = /queued|pending|waiting/i.test(jobStatus)
  const taskRunning = /claimed|running|collect|crawl|processing|working/i.test(jobStatus)
  const readinessLabel = !backendOnline
    ? 'OpenClaw 后端离线'
    : !workerOnline
      ? '后端在线 · Worker 待领取'
      : !loginOk
        ? 'Worker 在线 · 抖音待登录'
        : 'OpenClaw 可采集'
  const readinessClass = backendOnline && workerOnline && loginOk
    ? 'aiw-badge ok'
    : backendOnline
      ? 'aiw-badge warn'
      : 'aiw-badge'
  const emptyLeadMessage = taskQueued
    ? '任务已经进入服务器队列，正在等待 ECS Worker 领取；当前 0 条结果不代表 OpenClaw 离线。'
    : taskRunning
      ? '任务正在执行，暂时还没有产出线索；页面会继续轮询并保留任务缓存。'
      : statusDone(jobStatus)
        ? '任务已经结束，但本次没有产出可用线索。'
        : !backendOnline
          ? 'OpenClaw 后端离线，目前无法查询任务和线索。'
          : !workerOnline
            ? '后端在线，但 ECS Worker 尚未在线或没有领取任务。'
            : !loginOk
              ? 'Worker 已在线，但抖音账号尚未完成登录。'
              : '当前账号还没有真实采集结果。'
  const stats = useMemo(() => ({
    total: leads.length,
    high: leads.filter((item) => Number(item.score || item.lead_score || 0) >= 70).length,
    current: leads.filter((item) => String(item.job_id || item.run_id || '') === jobId).length,
  }), [leads, jobId])

  async function restoreLatest(profile = accountProfile) {
    try {
      const data = await apiGet(`${API}/openclaw/latest?account_profile=${encodeURIComponent(profile)}`, 60000)
      const restored = data?.run
      if (restored?.job_id) {
        setJobId(String(restored.job_id))
        setJob(restored)
        saveRunCache(profile, restored)
        setProject({
          ...project,
          openclaw_account_profile: profile,
          openclaw_job_id: String(restored.job_id),
          openclaw_job: restored,
        })
      }
    } catch {
      const cached = loadRunCache(profile)
      if (cached?.job_id) {
        setJobId(String(cached.job_id))
        setJob(cached)
      }
    }
  }

  async function refreshRunHistory(profile = accountProfile) {
    try {
      const data = await apiGet(`${API}/openclaw/runs?account_profile=${encodeURIComponent(profile)}&limit=20`, 60000)
      setRunHistory(Array.isArray(data?.runs) ? data.runs : [])
    } catch {}
  }

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
      saveRunCache(accountProfile, data)
      setProject({ ...project, openclaw_account_profile: accountProfile, openclaw_job_id: targetJobId, openclaw_job: data })
      const state = String(data?.status || '')
      if (statusDone(state)) {
        setNotice('真实采集任务已完成，可以沉淀客户问题和刷新线索。')
        await refreshLeads()
        await refreshRunHistory(accountProfile)
      }
      if (statusFailed(state)) setError(`OpenClaw 任务失败：${state}`)
    } catch (err) {
      setError(detailToText(err))
    }
  }

  useEffect(() => {
    void refreshHealth()
    void refreshRunHistory(accountProfile)
    if (jobId) void poll(jobId)
    else void restoreLatest(accountProfile)
    return () => {
      if (polling.current) window.clearInterval(polling.current)
    }
  }, [])

  useEffect(() => {
    localStorage.setItem(OPENCLAW_PROFILE_KEY, accountProfile)
    const cached = loadRunCache(accountProfile)
    setJobId(String(cached?.job_id || ''))
    setJob(cached || null)
    setProject({ ...project, openclaw_account_profile: accountProfile })
    void restoreLatest(accountProfile)
    void refreshRunHistory(accountProfile)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accountProfile])

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
          account_profile: accountProfile,
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
      saveRunCache(accountProfile, data)
      setProject({
        ...project,
        topic: keyword || project.topic,
        openclaw_account_profile: accountProfile,
        openclaw_job_id: id,
        openclaw_job: data,
        openclaw_target_accounts: targets,
      })
      const queued = /queued|pending|waiting/i.test(String(data?.status || data?.stage || ''))
      setNotice(
        queued
          ? `任务已进入服务器队列并缓存到“${accountProfile}”，正在等待 ECS Worker 领取：${id}`
          : `真实采集任务已启动并缓存到“${accountProfile}”：${id}`,
      )
      await refreshRunHistory(accountProfile)
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
      const data = await apiPost(`${API}/openclaw/harvest/${encodeURIComponent(jobId)}`, { collection: 'lead' }, 240000)
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
        <span className={readinessClass}>
          {readinessLabel}
        </span>
      </div>

      <div className="aiw-metrics">
        <div><b>{progress || 0}%</b><span>任务进度</span></div>
        <div><b>{stats.current}</b><span>当前任务线索</span></div>
        <div><b>{stats.total}</b><span>历史线索</span></div>
        <div><b>{stats.high}</b><span>高意向</span></div>
      </div>

      <div className="aiw-panel aiw-accountIsolation">
        <div className="aiw-sectionTitleRow">
          <div><h3>工作账号隔离</h3><span>公司号、备用号和测试号分别保存任务、缓存、线索和沉淀记录；切换页面后任务不会消失。</span></div>
          <span className="aiw-statusBadge">{accountProfile}</span>
        </div>
        <div className="aiw-form two">
          <label>
            当前工作账号
            <select value={accountProfile} onChange={(event) => setAccountProfile(event.target.value)}>
              <option value="company_main">公司主号</option>
              <option value="company_backup">公司备用号</option>
              <option value="personal_test">个人测试号</option>
            </select>
          </label>
          <label>
            登录准备
            <div className="aiw-loginState">后端 {health?.backend_online ? '在线' : '离线'} · Worker {workerOnline ? '在线' : '待确认'} · 抖音登录 {loginOk ? '有效' : '明天登录后检查'}</div>
          </label>
        </div>
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
        <button className="aiw-primary" disabled={Boolean(busy) || !backendOnline} onClick={start}>{busy === '启动真实采集' ? busy : workerOnline ? '启动真实 OpenClaw 任务' : '加入服务器任务队列'}</button>
        <button className="aiw-muted" disabled={Boolean(busy) || !jobId} onClick={() => void poll()}>{jobId ? '刷新当前任务' : '没有任务 ID'}</button>
        <button className="aiw-purple" disabled={Boolean(busy) || !jobId || !statusDone(jobStatus)} onClick={harvest}>
          {statusDone(jobStatus) ? '沉淀到内容大脑' : '任务完成后可沉淀'}
        </button>
        <button className="aiw-muted" onClick={() => goTab('brain')}>去审核知识</button>
      </div>

      <div className="aiw-panel">
        <h3>当前真实任务</h3>
        <div className="aiw-statusRows">
          <div><span>job_id</span><b>{jobId || '-'}</b></div>
          <div><span>隔离账号</span><b>{accountProfile}</b></div>
          <div><span>状态</span><b>{jobStatus || '未启动'}</b></div>
          <div><span>当前阶段</span><b>{job?.stage || jobStatus || '-'}</b></div>
          <div><span>实际接口</span><b>{job?.endpoint || health?.endpoint || '-'}</b></div>
          <div><span>队列说明</span><b>{job?.response?.message || job?.message || (taskQueued ? '等待 ECS Worker 领取' : '-')}</b></div>
          <div><span>最近进度</span><b>{progress || 0}%</b></div>
          <div><span>已采集</span><b>{runCounts.accounts || 0} 账号 / {runCounts.videos || 0} 视频 / {runCounts.comments || 0} 评论 / {runCounts.leads || 0} 线索</b></div>
          <div><span>最后更新</span><b>{job?.updated_at ? new Date(Number(job.updated_at) * 1000).toLocaleString() : '-'}</b></div>
        </div>
      </div>

      <div className="aiw-panel">
        <div className="aiw-sectionTitleRow"><div><h3>账号任务缓存</h3><span>来自服务器持久化记录；换页面、刷新或换设备后仍能恢复。</span></div><button className="aiw-muted" onClick={() => void refreshRunHistory(accountProfile)}>刷新缓存</button></div>
        <div className="aiw-runHistory">
          {runHistory.slice(0, 8).map((item) => (
            <button key={item.job_id} className={String(item.job_id) === jobId ? 'active' : ''} onClick={() => { setJobId(String(item.job_id)); setJob(item); saveRunCache(accountProfile, item) }}>
              <b>{item.mission_type || 'comments'} · {item.progress || 0}%</b>
              <span>{item.status || item.stage || 'queued'}</span>
              <em>{String(item.job_id || '').slice(0, 24)}</em>
            </button>
          ))}
          {!runHistory.length && <div className="aiw-empty">当前账号还没有历史任务。</div>}
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
          {!leads.length && <div className="aiw-empty aiw-emptyTruth"><b>当前线索：0 条</b><span>{emptyLeadMessage}</span></div>}
        </div>
      </div>

      {notice && <div className="aiw-successPanel"><div><b>完成</b><span>{notice}</span></div></div>}
      {error && <div className="aiw-error">{error}</div>}
    </section>
  )
}
