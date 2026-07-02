import React, { useEffect, useMemo, useState } from 'react'
import { apiGet, apiPost, csvRows, detailToText, generateLocalScript, projectWithScript, ProjectDraft, WorkspaceTab } from './aiVideoApi'

type Props = {
  project: ProjectDraft
  setProject: (p: ProjectDraft) => void
  goTab: (tab: WorkspaceTab) => void
}

type LeadStatus = '待人工处理' | '已标记可回复' | '已带入文案' | '暂不跟进'

type Lead = {
  text: string
  score: number
  priority: string
  reply: string
  report: boolean
  source?: string
  platform?: string
  author?: string
  accountName?: string
  accountId?: string
  accountUrl?: string
  profileUrl?: string
  videoTitle?: string
  videoUrl?: string
  commentId?: string
  contactHint?: string
  nextAction?: string
  status?: LeadStatus
  raw?: any
}



type BrainCandidate = {
  id: string
  title: string
  type: 'lead_question' | 'topic' | 'hook' | 'reply_template'
  source: string
  content: string
  tags: string[]
  score: number
  status: 'pending' | 'approved' | 'rejected'
  decisionReason: string
  createdAt: string
  raw?: any
}

const CONTENT_BRAIN_INBOX_KEY = 'ai_video_content_brain_inbox_v9'

function pushOpenClawToBrainInbox(leads: Lead[], project: ProjectDraft) {
  try {
    const qualified = leads
      .filter((lead) => lead.text && (lead.priority === 'A' || lead.priority === 'B' || Number(lead.score || 0) >= 55))
      .slice(0, 80)
      .map((lead) => {
        const tags = [project.market, project.topic, lead.priority, lead.accountName, lead.author, 'OpenClaw', '客户问题']
          .filter(Boolean)
          .map((x) => String(x))
        return {
          id: `openclaw_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`,
          title: lead.text.slice(0, 36),
          type: 'lead_question' as const,
          source: 'openclaw_sales_capture',
          content: lead.text,
          tags,
          score: Number(lead.score || 60),
          status: 'pending' as const,
          decisionReason: lead.priority === 'A'
            ? 'A 级真实客户问题，建议沉淀进内容大脑。'
            : 'B 级线索，可作为选题/FAQ 候选，等待人工判断。',
          createdAt: new Date().toLocaleString(),
          raw: lead,
        }
      })

    if (!qualified.length) return
    const oldRaw = window.localStorage.getItem(CONTENT_BRAIN_INBOX_KEY)
    const oldItems = oldRaw ? JSON.parse(oldRaw) : []
    const merged = [...qualified, ...(Array.isArray(oldItems) ? oldItems : [])]
    const seen = new Set<string>()
    const deduped = merged.filter((item: BrainCandidate) => {
      const key = `${item.type}|${item.title}|${String(item.content || '').slice(0, 80)}`.replace(/\s+/g, '').toLowerCase()
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
    window.localStorage.setItem(CONTENT_BRAIN_INBOX_KEY, JSON.stringify(deduped.slice(0, 300)))
  } catch {
    // 内容大脑同步失败不影响 OpenClaw 主流程
  }
}

type RealSource = {
  endpoint: string
  ok: boolean
  count: number
  message: string
}

type SalesStage = {
  key: string
  label: string
  hint: string
  done: boolean
  active: boolean
}

function normalizeText(value: unknown): string {
  if (value === null || value === undefined) return ''
  return String(value).trim()
}

function splitLines(value: string): string[] {
  return normalizeText(value)
    .split(/[\n，,]+/)
    .map((x) => x.trim())
    .filter(Boolean)
}

function compactKey(value: string): string {
  return normalizeText(value).replace(/\s+/g, '').toLowerCase()
}

function uniqueByIdentity(items: Lead[]): Lead[] {
  const seen = new Set<string>()
  const out: Lead[] = []
  items.forEach((item) => {
    const key = compactKey(`${item.accountName || item.author || ''}|${item.text}`)
    if (!key || seen.has(key)) return
    seen.add(key)
    out.push(item)
  })
  return out
}

function firstValue(row: Record<string, any>, keys: string[]): string {
  for (const key of keys) {
    const value = normalizeText(row?.[key])
    if (value) return value
  }
  return ''
}

function scoreLead(text: string): Lead {
  const score =
    20 +
    (/首付|预算|贷款|价格|买房|多少|哪里|哪个|能买吗|总价|万|马币|RM/i.test(text) ? 35 : 0) +
    (/投资|出租|租金|回报|转手|流动性|区域|地段|升值|空置/i.test(text) ? 25 : 0) +
    (/私信|微信|联系|了解|咨询|可以讲|华语|华人|中文/i.test(text) ? 25 : 0) +
    (/避坑|怕坑|靠谱不|清单|核验|真的假的|安全吗/i.test(text) ? 15 : 0)
  const finalScore = Math.min(100, score)
  const priority = finalScore >= 75 ? 'A' : finalScore >= 55 ? 'B' : 'C'
  return {
    text,
    score: finalScore,
    priority,
    report: priority === 'A',
    status: priority === 'A' ? '待人工处理' : '已标记可回复',
    nextAction: priority === 'A' ? '人工确认预算、用途、城市和联系方式' : '可先公开回复，再观察是否继续追问',
    reply: priority === 'A'
      ? '先别急着看项目，我建议先确认你的预算、用途和目标区域。你是偏自住、出租，还是资产配置？我可以先按你的情况帮你做一版筛选。'
      : '可以先从预算、用途和城市区域开始判断，别只看价格。真实价格、户型和周边以官方资料为准。',
  }
}

function rowToLead(row: Record<string, any>, source: string): Lead | null {
  const text = firstValue(row, ['comment_text', 'comment', 'text', 'content', 'message', 'body', 'desc', 'title'])
  if (!text) return null

  const base = scoreLead(text)
  const like = Number(row.like_count || row.likes || row.digg_count || row.like || 0)
  const replyCount = Number(row.reply_count || row.replies || row.reply || 0)
  const score = Math.min(100, base.score + (like >= 10 ? 5 : 0) + (replyCount >= 2 ? 5 : 0))
  const priority = score >= 75 ? 'A' : score >= 55 ? 'B' : 'C'
  const author = firstValue(row, ['comment_author', 'author', 'nickname', 'user', 'username', 'user_name', 'display_name'])
  const accountName = firstValue(row, ['account_name', 'account', 'video_author', 'video_account', 'aweme_author', 'douyin_account', 'sec_uid', 'uid']) || author
  const accountUrl = firstValue(row, ['account_url', 'homepage', 'profile_url', 'author_url', 'user_url'])
  const videoUrl = firstValue(row, ['url', 'source_url', 'share_url', 'video_url', 'aweme_url'])

  return {
    ...base,
    score,
    priority,
    report: score >= 75,
    status: score >= 75 ? '待人工处理' : '已标记可回复',
    source,
    platform: firstValue(row, ['platform']) || 'douyin',
    author,
    accountName,
    accountId: firstValue(row, ['account_id', 'uid', 'sec_uid', 'user_id', 'author_id']),
    accountUrl,
    profileUrl: accountUrl,
    videoTitle: firstValue(row, ['video_title', 'title', 'aweme_title']),
    videoUrl,
    commentId: firstValue(row, ['comment_id', 'cid', 'id']),
    contactHint: accountUrl || accountName || author || '缺少账号信息，请回采集源补齐',
    nextAction: score >= 75 ? '人工从账号主页/评论源进入处理，不自动私信' : '可作为公开回复或下一条视频选题',
    raw: row,
  }
}

function recursiveExtractRows(value: any, source: string, depth = 0): Lead[] {
  if (depth > 6 || value === null || value === undefined) return []

  if (typeof value === 'string') {
    if (value.includes('\n') && value.includes(',')) {
      return csvRows(value).map((row) => rowToLead(row, source)).filter(Boolean) as Lead[]
    }
    return value.length >= 4 ? [{ ...scoreLead(value), source }] : []
  }

  if (Array.isArray(value)) return value.flatMap((item) => recursiveExtractRows(item, source, depth + 1))

  if (typeof value === 'object') {
    const direct = rowToLead(value, source)
    const children: Lead[] = []
    ;['comments', 'items', 'data', 'rows', 'results', 'leads', 'records', 'videos', 'messages', 'events', 'latest', 'comment_leads'].forEach((key) => {
      if (value[key] !== undefined) children.push(...recursiveExtractRows(value[key], `${source}.${key}`, depth + 1))
    })
    return direct ? [direct, ...children] : children
  }

  return []
}

function parseManualInput(raw: string): Lead[] {
  const trimmed = raw.trim()
  if (!trimmed) return []
  if ((trimmed.startsWith('{') && trimmed.endsWith('}')) || (trimmed.startsWith('[') && trimmed.endsWith(']'))) {
    try {
      return recursiveExtractRows(JSON.parse(trimmed), 'manual_json')
    } catch {
      // fall through
    }
  }
  const rows = csvRows(trimmed)
  if (rows.length) return rows.map((row) => rowToLead(row, 'manual_csv')).filter(Boolean) as Lead[]
  return trimmed.split(/\n+/).map((x) => x.trim()).filter(Boolean).map((text) => ({ ...scoreLead(text), source: 'manual_text' }))
}

function backendLeadToLocal(item: any, source: string): Lead | null {
  const text = normalizeText(item?.text || item?.comment_text || item?.original_text || item?.content || item?.message)
  if (!text) return null
  const rowLead = rowToLead(item, source)
  const base = rowLead || scoreLead(text)
  const score = Number(item?.score || item?.lead_score || item?.priority_score || base.score)
  const priority = normalizeText(item?.priority || item?.level || (score >= 75 ? 'A' : score >= 55 ? 'B' : 'C'))
  return {
    ...base,
    text,
    score,
    priority,
    report: Boolean(item?.report ?? item?.needs_human ?? item?.manual_review ?? priority === 'A'),
    status: item?.status || (priority === 'A' ? '待人工处理' : '已标记可回复'),
    reply: normalizeText(item?.reply || item?.suggested_reply || item?.first_message || base.reply),
    source,
    raw: item,
  }
}

export default function OpenClawWorkbench({ project, setProject, goTab }: Props) {
  const [manualRaw, setManualRaw] = useState('')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [leads, setLeads] = useState<Lead[]>([])
  const [result, setResult] = useState<any>(null)
  const [sources, setSources] = useState<RealSource[]>([])
  const [lastLoadedAt, setLastLoadedAt] = useState('')
  const [collectKeyword, setCollectKeyword] = useState(project.topic || '马来西亚吉隆坡买房')
  const [targetAccounts, setTargetAccounts] = useState(normalizeText((project as any).openclaw_target_accounts || ''))

  const stats = useMemo(() => {
    const a = leads.filter((x) => x.priority === 'A').length
    const report = leads.filter((x) => x.report || x.status === '待人工处理').length
    const withIdentity = leads.filter((x) => x.author || x.accountName || x.accountUrl || x.videoUrl).length
    return { count: leads.length, a, report, withIdentity }
  }, [leads])

  const stages: SalesStage[] = useMemo(() => {
    const hasSource = sources.length > 0
    const hasCollected = leads.length > 0
    const hasIdentity = stats.withIdentity > 0
    const hasAnalyzed = Boolean(result) || leads.some((x) => x.reply)
    const hasQueue = stats.report > 0
    const hasHandoff = Boolean((project as any).openclaw_sales_queue?.length || hasQueue)
    return [
      { key: 'source', label: '1 读取采集源', hint: 'OpenClaw / Collector / comment-leads', done: hasSource, active: busy === 'loading-real-openclaw' },
      { key: 'collect', label: '2 采集评论', hint: '账号/视频评论进入系统', done: hasCollected, active: busy === 'collect' },
      { key: 'identity', label: '3 补齐账号', hint: '账号名、主页、视频链接', done: hasIdentity, active: false },
      { key: 'analyze', label: '4 AI 评分', hint: 'A/B/C 线索和意向', done: hasAnalyzed, active: busy === 'analyze' },
      { key: 'queue', label: '5 人工队列', hint: '高意向客户待处理', done: hasQueue, active: false },
      { key: 'handoff', label: '6 转文案/跟进', hint: 'sales 继续承接', done: hasHandoff, active: false },
    ]
  }, [busy, leads, project, result, sources.length, stats.report, stats.withIdentity])

  const progress = Math.round((stages.filter((x) => x.done).length / stages.length) * 100)
  const hasRealSource = sources.some((item) => item.ok && item.count > 0)
  const accountLines = splitLines(targetAccounts)

  function updateLeads(nextLeads: Lead[], extra: Record<string, any> = {}) {
    const unique = uniqueByIdentity(nextLeads).slice(0, 300)
    setLeads(unique)
    pushOpenClawToBrainInbox(unique, project)
    setProject({
      ...project,
      leads: unique,
      openclaw_sales_queue: unique.filter((lead) => lead.report || lead.priority === 'A'),
      openclaw_target_accounts: targetAccounts,
      ...extra,
    })
  }

  async function loadRealOpenClawData() {
    setBusy('loading-real-openclaw')
    setError('')
    setResult(null)
    const nextSources: RealSource[] = []
    const found: Lead[] = []
    const endpoints = [
      '/api/video/comment-leads/recent',
      '/api/collector/runs/latest',
      '/api/openclaw/export.csv',
      '/api/openclaw/videos',
      '/api/openclaw/accounts',
    ]

    for (const endpoint of endpoints) {
      try {
        const data = await apiGet(endpoint, 60000)
        const leadsFromEndpoint = recursiveExtractRows(data?.raw || data, endpoint)
          .map((item) => backendLeadToLocal(item.raw || item, endpoint) || item)
          .filter(Boolean) as Lead[]
        found.push(...leadsFromEndpoint)
        nextSources.push({ endpoint, ok: true, count: leadsFromEndpoint.length, message: leadsFromEndpoint.length ? '读取到真实记录' : '接口可用但暂无可分析评论' })
      } catch (err) {
        nextSources.push({ endpoint, ok: false, count: 0, message: detailToText(err).split('\n')[0] || '不可用' })
      }
    }

    setSources(nextSources)
    setLastLoadedAt(new Date().toLocaleString())
    updateLeads(found, { openclaw_sources: nextSources, openclaw_loaded_at: new Date().toISOString() })
    setBusy('')

    if (!found.length) setError('暂无真实 OpenClaw/采集结果。请先录入账号或爆款链接并下发采集任务；人工导入真实 CSV/JSON 也可以。')
  }

  useEffect(() => {
    loadRealOpenClawData()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function createCollectTask(mode: 'accounts' | 'comments' = 'comments') {
    setBusy('collect')
    setError('')
    const accounts = accountLines
    const payload = {
      source: 'frontend_openclaw_sales_board',
      platform: 'douyin',
      mission_type: mode === 'accounts' ? 'accounts' : 'comments',
      keyword: collectKeyword,
      keywords: splitLines(collectKeyword),
      accounts,
      target_accounts: accounts,
      target: mode === 'accounts' ? 'accounts_videos_comments' : 'comments',
      max_videos: mode === 'accounts' ? 12 : 5,
      max_comments: mode === 'accounts' ? 120 : 80,
      run_openclaw_analysis: true,
      payload: {
        keyword: collectKeyword,
        accounts,
        target: mode === 'accounts' ? 'accounts_videos_comments' : 'comments',
        max_videos: mode === 'accounts' ? 12 : 5,
        max_comments: mode === 'accounts' ? 120 : 80,
        run_openclaw_analysis: true,
      },
    }

    if (mode === 'accounts' && !accounts.length) {
      setBusy('')
      setError('请先录入至少一个真实账号名、主页链接或账号备注。否则采集回来也找不到人。')
      return
    }

    try {
      let data: any
      try {
        data = await apiPost('/api/collector/commands', { type: mode === 'accounts' ? 'openclaw_collect_accounts' : 'openclaw_collect_comments', ...payload }, 120000)
      } catch {
        try {
          data = await apiPost('/api/collector/commands/create', payload, 120000)
        } catch {
          data = await apiPost('/api/collector/douyin/accounts/bulk-upsert', {
            accounts: (accounts.length ? accounts : splitLines(collectKeyword)).map((name: string) => ({
              category: mode === 'accounts' ? 'openclaw_target_account' : 'openclaw_comment_target',
              account_name: name,
              niche: collectKeyword,
              source: 'frontend_openclaw_sales_board',
            })),
          }, 120000)
        }
      }
      setResult(data)
      setProject({ ...project, last_openclaw_collect_command: data, topic: collectKeyword || project.topic, openclaw_target_accounts: targetAccounts })
      setError('采集任务已下发。稍等几十秒后点“刷新真实采集结果”，看到账号名/评论后再分析。')
    } catch (err) {
      setError(detailToText(err))
    } finally {
      setBusy('')
    }
  }

  async function analyze() {
    setBusy('analyze')
    setError('')
    const manualLeads = parseManualInput(manualRaw)
    const baseLeads = manualLeads.length ? manualLeads : leads
    if (!baseLeads.length) {
      setBusy('')
      setError('没有可分析的真实评论。请先采集、刷新，或粘贴 OpenClaw 导出的真实 CSV/JSON。')
      return
    }

    updateLeads(baseLeads)

    try {
      const comments = baseLeads.map((lead) => ({
        text: lead.text,
        like_count: lead.raw?.like_count || lead.raw?.likes || 0,
        reply_count: lead.raw?.reply_count || lead.raw?.replies || 0,
        platform: lead.platform || lead.raw?.platform || 'douyin',
        author: lead.author,
        account_name: lead.accountName,
        account_url: lead.accountUrl || lead.profileUrl,
        video_title: lead.videoTitle || lead.raw?.video_title || lead.raw?.title || '',
        source_url: lead.videoUrl || lead.raw?.source_url || lead.raw?.url || '',
      }))
      const data = await apiPost('/api/video/openclaw/llm-enhance/comments', {
        dry_run: false,
        max_llm_items: Math.min(30, comments.length),
        min_score: 40,
        campaign_context: {
          market: project.market,
          platform: 'douyin',
          source: manualLeads.length ? 'manual_import' : 'real_openclaw_collector',
          topic: project.topic,
          target_accounts: accountLines,
          sales_mode: 'human_review_first',
        },
        comments,
      }, 180000)
      setResult(data)
      const backendCandidates = recursiveExtractRows(data, 'llm_enhance_result')
      const merged = uniqueByIdentity([
        ...backendCandidates.map((item) => backendLeadToLocal(item.raw || item, 'llm_enhance_result') || item),
        ...baseLeads,
      ]).slice(0, 300)
      updateLeads(merged, { openclaw_analysis_result: data })
    } catch (err) {
      const fallback = baseLeads.map((lead) => ({ ...lead, ...scoreLead(lead.text), source: lead.source || 'local_fallback' }))
      setResult({ ok: false, fallback: 'local_analyze_after_backend_failed', message: detailToText(err) })
      updateLeads(fallback)
    } finally {
      setBusy('')
    }
  }

  function updateLeadStatus(index: number, status: LeadStatus) {
    const next = leads.map((lead, i) => i === index ? { ...lead, status, report: status === '待人工处理' || status === '已标记可回复' } : lead)
    updateLeads(next)
  }

  function toScript(lead?: Lead) {
    const top = lead?.text || leads.find((item) => item.priority === 'A')?.text || leads[0]?.text || project.topic
    const script = generateLocalScript(top, project.market, project.targetDuration)
    updateLeadStatus(Math.max(0, leads.findIndex((x) => x.text === top)), '已带入文案')
    setProject(projectWithScript({ ...project, topic: top, leads, openclaw_target_accounts: targetAccounts }, script, { title: top }))
    goTab('pureai')
  }

  const topQueue = leads.filter((lead) => lead.report || lead.priority === 'A')

  return (
    <section className="aiw-card aiw-real-openclaw aiw-salesBoard">
      <div className="aiw-hero">
        <div>
          <p className="aiw-eyebrow">OPENCLAW SALES CAPTURE</p>
          <h2>OpenClaw 销售截流台</h2>
          <p>像销售一样先找人：账号/主页 → 评论采集 → AI 评分 → 首条回复建议 → 人工处理。没有真实采集结果时不展示假线索。</p>
        </div>
        <span className={hasRealSource ? 'aiw-badge ok' : 'aiw-badge warn'}>{hasRealSource ? '已读取真实采集' : '等待真实采集'}</span>
      </div>

      <div className="aiw-salesProgress">
        <div className="aiw-salesProgressTop">
          <b>OpenClaw 执行进度</b>
          <span>{progress}%</span>
        </div>
        <div className="aiw-progressTrack"><i style={{ width: `${progress}%` }} /></div>
        <div className="aiw-salesSteps">
          {stages.map((stage) => (
            <div key={stage.key} className={`${stage.done ? 'done' : ''} ${stage.active ? 'active' : ''}`}>
              <b>{stage.label}</b>
              <span>{stage.hint}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="aiw-form two">
        <label>
          采集关键词 / 主攻方向
          <input value={collectKeyword} onChange={(e) => setCollectKeyword(e.target.value)} placeholder="例如：吉隆坡买房 / 马来西亚房产预算" />
        </label>
        <label>
          目标账号 / 主页 / 达人名称，一行一个
          <textarea value={targetAccounts} onChange={(e) => setTargetAccounts(e.target.value)} placeholder="例如：@某地产顾问\nhttps://www.douyin.com/user/...\n吉隆坡房产同行主页" />
        </label>
        <label>
          手动导入真实 CSV / JSON / 评论，一行一个；可留空
          <textarea value={manualRaw} onChange={(e) => setManualRaw(e.target.value)} placeholder="没有采集结果时，可以粘贴 OpenClaw 导出的真实 CSV/JSON；不要填假数据。" />
        </label>
        <label>
          承接规则
          <textarea readOnly value={'A 级线索：进入人工待处理\nB 级线索：生成公开回复建议\nC 级线索：沉淀为视频选题\n系统只生成建议，不自动私信、不自动骚扰。'} />
        </label>
      </div>

      <div className="aiw-actions">
        <button className="aiw-primary" onClick={loadRealOpenClawData} disabled={!!busy}>{busy === 'loading-real-openclaw' ? '刷新中...' : '刷新真实采集结果'}</button>
        <button className="aiw-purple" onClick={() => createCollectTask('accounts')} disabled={!!busy}>{busy === 'collect' ? '下发中...' : '下发账号采集'}</button>
        <button className="aiw-purple" onClick={() => createCollectTask('comments')} disabled={!!busy}>{busy === 'collect' ? '下发中...' : '下发评论采集'}</button>
        <button className="aiw-primary" onClick={analyze} disabled={!!busy}>{busy === 'analyze' ? '分析中...' : 'AI 评分并生成回复'}</button>
        <button className="aiw-muted" onClick={() => goTab('collect')}>去同行采集</button>
          <button className="aiw-muted" onClick={() => goTab('brain')}>去内容大脑审核</button>
      </div>

      {error && <div className="aiw-error">{error}</div>}

      <div className="aiw-metrics">
        <div><b>{stats.count}</b><span>真实/导入评论</span></div>
        <div><b>{stats.withIdentity}</b><span>带账号信息</span></div>
        <div><b>{stats.a}</b><span>A 级线索</span></div>
        <div><b>{stats.report}</b><span>人工待处理</span></div>
        <div><b>{lastLoadedAt || '-'}</b><span>最近刷新</span></div>
      </div>

      <div className="aiw-twoCol">
        <div className="aiw-panel">
          <h3>人工待处理队列</h3>
          <div className="aiw-leadCards">
            {topQueue.map((lead, index) => (
              <article className="aiw-leadCard" key={`${lead.text}-${index}`}>
                <div className="aiw-leadHead">
                  <b>{lead.priority} / {lead.score}</b>
                  <span>{lead.status || '待人工处理'}</span>
                </div>
                <p>{lead.text}</p>
                <div className="aiw-leadMeta">
                  <span>账号：{lead.accountName || lead.author || '缺少账号名'}</span>
                  <span>平台：{lead.platform || 'douyin'}</span>
                  <span>来源：{lead.source || '-'}</span>
                  {lead.videoTitle && <span>视频：{lead.videoTitle}</span>}
                  {(lead.accountUrl || lead.videoUrl) && <a href={lead.accountUrl || lead.videoUrl} target="_blank" rel="noreferrer">打开账号/来源</a>}
                </div>
                <div className="aiw-replyBox"><b>首条回复建议</b><span>{lead.reply}</span></div>
                <div className="aiw-actions mini">
                  <button onClick={() => updateLeadStatus(leads.indexOf(lead), '待人工处理')}>待处理</button>
                  <button onClick={() => updateLeadStatus(leads.indexOf(lead), '已标记可回复')}>可回复</button>
                  <button onClick={() => toScript(lead)}>转视频选题</button>
                  <button onClick={() => updateLeadStatus(leads.indexOf(lead), '暂不跟进')}>暂不跟</button>
                </div>
              </article>
            ))}
            {!topQueue.length && <div className="aiw-empty">暂无 A 级线索。先录入账号并采集评论，或导入真实 OpenClaw CSV/JSON。</div>}
          </div>
        </div>

        <div className="aiw-panel">
          <h3>采集来源状态</h3>
          <div className="aiw-segmentList compact">
            {sources.map((source) => (
              <div className="aiw-segment" key={source.endpoint}>
                <b>{source.ok ? '可用' : '不可用'} · {source.count} 条</b>
                <p>{source.endpoint}</p>
                <span>{source.message}</span>
              </div>
            ))}
            {!sources.length && <div className="aiw-empty">正在检查真实 OpenClaw / Collector 数据。</div>}
          </div>
          <h3>全部线索</h3>
          <div className="aiw-segmentList compact">
            {leads.map((lead, index) => (
              <div className="aiw-segment" key={`${lead.text}-${index}`}>
                <b>{lead.priority} / {lead.score} · {lead.accountName || lead.author || '未识别账号'}</b>
                <p>{lead.text}</p>
                <span>{lead.status || (lead.report ? '进入人工待处理' : '可公开回复/选题')}{lead.videoTitle ? ` · ${lead.videoTitle}` : ''}</span>
              </div>
            ))}
            {!leads.length && <div className="aiw-empty">暂无真实评论。点击“下发账号采集/评论采集”或去“同行采集”获取数据。</div>}
          </div>
        </div>
      </div>

      {result && (
        <details className="aiw-json">
          <summary>后端返回 / 采集任务结果</summary>
          <pre>{JSON.stringify(result, null, 2)}</pre>
        </details>
      )}
    </section>
  )
}
