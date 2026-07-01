import React, { useEffect, useMemo, useState } from 'react'
import { apiGet, apiPost, csvRows, detailToText, generateLocalScript, projectWithScript, ProjectDraft, WorkspaceTab } from './aiVideoApi'

type Props = {
  project: ProjectDraft
  setProject: (p: ProjectDraft) => void
  goTab: (tab: WorkspaceTab) => void
}

type Lead = {
  text: string
  score: number
  priority: string
  reply: string
  report: boolean
  source?: string
  author?: string
  videoTitle?: string
  url?: string
  raw?: any
}

type RealSource = {
  endpoint: string
  ok: boolean
  count: number
  message: string
}

function normalizeText(value: unknown): string {
  if (value === null || value === undefined) return ''
  return String(value).trim()
}

function uniqueByText(items: Lead[]): Lead[] {
  const seen = new Set<string>()
  const out: Lead[] = []
  items.forEach((item) => {
    const key = item.text.replace(/\s+/g, '')
    if (!key || seen.has(key)) return
    seen.add(key)
    out.push(item)
  })
  return out
}

function scoreLead(text: string): Lead {
  const score =
    20 +
    (/首付|预算|贷款|价格|买房|多少|哪里|哪个|能买吗/.test(text) ? 35 : 0) +
    (/投资|出租|租金|回报|转手|流动性|区域|地段/.test(text) ? 25 : 0) +
    (/私信|微信|联系|了解|咨询|可以讲|华语/.test(text) ? 25 : 0) +
    (/避坑|怕坑|靠谱不|清单|核验/.test(text) ? 15 : 0)
  const finalScore = Math.min(100, score)
  const priority = finalScore >= 75 ? 'A' : finalScore >= 55 ? 'B' : 'C'
  return {
    text,
    score: finalScore,
    priority,
    report: priority === 'A',
    reply: priority === 'A'
      ? '先确认你的预算、用途和目标区域，再看具体项目。价格、户型和周边以官方资料为准，我可以先帮你做一版筛选清单。'
      : '可以先从预算、用途和城市区域开始判断，别只看价格。真实项目信息要回到官方资料核验。',
  }
}

function rowToLead(row: Record<string, any>, source: string): Lead | null {
  const text = normalizeText(
    row.comment_text || row.comment || row.text || row.content || row.message || row.title || row.desc || row.body,
  )
  if (!text) return null
  const base = scoreLead(text)
  const like = Number(row.like_count || row.likes || row.digg_count || 0)
  const reply = Number(row.reply_count || row.replies || 0)
  const score = Math.min(100, base.score + (like >= 10 ? 5 : 0) + (reply >= 2 ? 5 : 0))
  return {
    ...base,
    score,
    priority: score >= 75 ? 'A' : score >= 55 ? 'B' : 'C',
    report: score >= 75,
    source,
    author: normalizeText(row.comment_author || row.author || row.nickname || row.user || row.username),
    videoTitle: normalizeText(row.video_title || row.title || row.aweme_title),
    url: normalizeText(row.url || row.source_url || row.share_url || row.video_url),
    raw: row,
  }
}

function recursiveExtractRows(value: any, source: string, depth = 0): Lead[] {
  if (depth > 5 || value === null || value === undefined) return []

  if (typeof value === 'string') {
    if (value.includes('\n') && value.includes(',')) {
      return csvRows(value).map((row) => rowToLead(row, source)).filter(Boolean) as Lead[]
    }
    return value.length >= 4 ? [scoreLead(value)] : []
  }

  if (Array.isArray(value)) {
    return value.flatMap((item) => recursiveExtractRows(item, source, depth + 1))
  }

  if (typeof value === 'object') {
    const direct = rowToLead(value, source)
    const children: Lead[] = []
    ;['comments', 'items', 'data', 'rows', 'results', 'leads', 'records', 'videos', 'messages', 'events'].forEach((key) => {
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
      // fall through to CSV/text
    }
  }

  const rows = csvRows(trimmed)
  if (rows.length) return rows.map((row) => rowToLead(row, 'manual_csv')).filter(Boolean) as Lead[]

  return trimmed
    .split(/\n+/)
    .map((x) => x.trim())
    .filter(Boolean)
    .map((text) => ({ ...scoreLead(text), source: 'manual_text' }))
}

function backendLeadToLocal(item: any, source: string): Lead | null {
  const text = normalizeText(item?.text || item?.comment_text || item?.original_text || item?.content || item?.message)
  if (!text) return null
  const base = scoreLead(text)
  const score = Number(item?.score || item?.lead_score || item?.priority_score || base.score)
  const priority = normalizeText(item?.priority || item?.level || (score >= 75 ? 'A' : score >= 55 ? 'B' : 'C'))
  return {
    ...base,
    text,
    score,
    priority,
    report: Boolean(item?.report ?? item?.needs_human ?? item?.manual_review ?? priority === 'A'),
    reply: normalizeText(item?.reply || item?.suggested_reply || item?.first_message || base.reply),
    source,
    author: normalizeText(item?.author || item?.nickname || item?.username),
    videoTitle: normalizeText(item?.video_title || item?.title),
    url: normalizeText(item?.source_url || item?.url || item?.video_url),
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

  const stats = useMemo(() => {
    const a = leads.filter((x) => x.priority === 'A').length
    const report = leads.filter((x) => x.report).length
    return { count: leads.length, a, report }
  }, [leads])

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
      '/api/video/openclaw/comments/self-test',
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

    const unique = uniqueByText(found).slice(0, 200)
    setSources(nextSources)
    setLeads(unique)
    setLastLoadedAt(new Date().toLocaleString())
    setProject({ ...project, leads: unique, openclaw_sources: nextSources, openclaw_loaded_at: new Date().toISOString() })
    setBusy('')

    if (!unique.length) {
      setError('暂无真实 OpenClaw/采集结果。请先去“同行采集”下发采集任务，或在左侧粘贴真实 CSV/JSON 后分析。')
    }
  }

  useEffect(() => {
    loadRealOpenClawData()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function createCollectTask() {
    setBusy('collect')
    setError('')
    const payload = {
      source: 'frontend_openclaw_capture_board',
      platform: 'douyin',
      mission_type: 'comments',
      keyword: collectKeyword,
      keywords: collectKeyword.split(/[，,\n]/).map((x) => x.trim()).filter(Boolean),
      target: 'comments',
      max_videos: 5,
      max_comments: 80,
      run_openclaw_analysis: true,
      payload: {
        keyword: collectKeyword,
        target: 'comments',
        max_videos: 5,
        max_comments: 80,
        run_openclaw_analysis: true,
      },
    }

    try {
      let data: any
      try {
        data = await apiPost('/api/collector/commands', { type: 'openclaw_collect_comments', ...payload }, 120000)
      } catch {
        try {
          data = await apiPost('/api/collector/commands/create', payload, 120000)
        } catch {
          data = await apiPost('/api/collector/douyin/accounts/bulk-upsert', {
            accounts: payload.keywords.map((name: string) => ({
              category: 'openclaw_comment_target',
              account_name: name,
              niche: collectKeyword,
              source: 'frontend_openclaw_capture',
            })),
          }, 120000)
        }
      }
      setResult(data)
      setProject({ ...project, last_openclaw_collect_command: data, topic: collectKeyword || project.topic })
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
      setError('没有可分析的真实评论。请先点击“刷新真实采集结果”，或去同行采集下发任务，或粘贴真实 CSV/JSON。')
      return
    }

    setLeads(baseLeads)

    try {
      const comments = baseLeads.map((lead) => ({
        text: lead.text,
        like_count: lead.raw?.like_count || lead.raw?.likes || 0,
        reply_count: lead.raw?.reply_count || lead.raw?.replies || 0,
        platform: lead.raw?.platform || 'douyin',
        video_title: lead.videoTitle || lead.raw?.video_title || lead.raw?.title || '',
        source_url: lead.url || lead.raw?.source_url || lead.raw?.url || '',
      }))
      const data = await apiPost('/api/video/openclaw/llm-enhance/comments', {
        dry_run: false,
        max_llm_items: Math.min(20, comments.length),
        min_score: 40,
        campaign_context: {
          market: project.market,
          platform: 'douyin',
          source: manualLeads.length ? 'manual_import' : 'real_openclaw_collector',
          topic: project.topic,
        },
        comments,
      }, 180000)
      setResult(data)
      const backendCandidates = recursiveExtractRows(data, 'llm_enhance_result')
      const merged = uniqueByText([
        ...backendCandidates.map((item) => backendLeadToLocal(item.raw || item, 'llm_enhance_result') || item),
        ...baseLeads,
      ]).slice(0, 200)
      setLeads(merged)
      setProject({ ...project, leads: merged, openclaw_analysis_result: data })
    } catch (err) {
      const fallback = baseLeads.map((lead) => ({ ...lead, ...scoreLead(lead.text), source: lead.source || 'local_fallback' }))
      setLeads(fallback)
      setResult({ ok: false, fallback: 'local_analyze_after_backend_failed', message: detailToText(err) })
      setProject({ ...project, leads: fallback })
    } finally {
      setBusy('')
    }
  }

  function toScript() {
    const top = leads.find((lead) => lead.priority === 'A')?.text || leads[0]?.text || project.topic
    const script = generateLocalScript(top, project.market, project.targetDuration)
    setProject(projectWithScript({ ...project, topic: top, leads }, script, { title: top }))
    goTab('pureai')
  }

  const hasRealSource = sources.some((item) => item.ok && item.count > 0)

  return (
    <section className="aiw-card aiw-real-openclaw">
      <div className="aiw-hero">
        <div>
          <p className="aiw-eyebrow">OPENCLAW REAL CAPTURE</p>
          <h2>真实获客截流看板</h2>
          <p>默认读取 OpenClaw / Collector / comment-leads 的真实结果；没有结果就提示先采集，不再预置假评论。</p>
        </div>
        <span className={hasRealSource ? 'aiw-badge ok' : 'aiw-badge warn'}>{hasRealSource ? '已读取真实采集' : '等待真实采集'}</span>
      </div>

      <div className="aiw-form two">
        <label>
          采集关键词 / 主页备注
          <input value={collectKeyword} onChange={(e) => setCollectKeyword(e.target.value)} placeholder="例如：马来西亚吉隆坡买房 / 某个同行主页" />
        </label>
        <label>
          手动导入真实 CSV / JSON / 评论，一行一个；可留空
          <textarea value={manualRaw} onChange={(e) => setManualRaw(e.target.value)} placeholder="这里不再放假数据。没有真实采集结果时，可以粘贴 OpenClaw 导出的 CSV/JSON。" />
        </label>
      </div>

      <div className="aiw-actions">
        <button className="aiw-primary" onClick={loadRealOpenClawData} disabled={!!busy}>{busy === 'loading-real-openclaw' ? '刷新中...' : '刷新真实采集结果'}</button>
        <button className="aiw-purple" onClick={createCollectTask} disabled={!!busy}>{busy === 'collect' ? '下发中...' : '下发评论采集任务'}</button>
        <button className="aiw-primary" onClick={analyze} disabled={!!busy}>{busy === 'analyze' ? '分析中...' : '分析真实线索'}</button>
        <button className="aiw-purple" onClick={toScript} disabled={!leads.length}>把 A/B 线索转成文稿</button>
        <button className="aiw-muted" onClick={() => goTab('collect')}>去同行采集</button>
      </div>

      {error && <div className="aiw-error">{error}</div>}

      <div className="aiw-metrics">
        <div><b>{stats.count}</b><span>真实/导入评论</span></div>
        <div><b>{stats.a}</b><span>A 级线索</span></div>
        <div><b>{stats.report}</b><span>人工待处理</span></div>
        <div><b>{lastLoadedAt || '-'}</b><span>最近刷新</span></div>
      </div>

      <div className="aiw-twoCol">
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
        </div>
        <div className="aiw-panel">
          <h3>人工待处理队列</h3>
          <div className="aiw-segmentList compact">
            {leads.filter((lead) => lead.report || lead.priority === 'A').map((lead, index) => (
              <div className="aiw-segment" key={`${lead.text}-${index}`}>
                <b>{lead.priority} / {lead.score}</b>
                <p>{lead.text}</p>
                <span>{lead.author ? `用户：${lead.author} · ` : ''}{lead.source || 'openclaw'}</span>
              </div>
            ))}
            {!leads.filter((lead) => lead.report || lead.priority === 'A').length && <div className="aiw-empty">暂无 A 级线索。先采集或导入真实评论后再分析。</div>}
          </div>
        </div>
      </div>

      <div className="aiw-twoCol">
        <div className="aiw-panel">
          <h3>全部线索</h3>
          <div className="aiw-segmentList">
            {leads.map((lead, index) => (
              <div className="aiw-segment" key={`${lead.text}-${index}`}>
                <b>{lead.priority} / {lead.score}</b>
                <p>{lead.text}</p>
                <span>{lead.report ? '进入人工待处理' : '可作为公开回复/选题'}{lead.videoTitle ? ` · ${lead.videoTitle}` : ''}</span>
              </div>
            ))}
            {!leads.length && <div className="aiw-empty">暂无真实评论。点击“下发评论采集任务”或去“同行采集”获取数据。</div>}
          </div>
        </div>
        <div className="aiw-panel">
          <h3>首条回复建议</h3>
          <div className="aiw-segmentList">
            {leads.map((lead, index) => (
              <div className="aiw-segment" key={`${lead.reply}-${index}`}>
                <b>{lead.priority} 线索</b>
                <p>{lead.reply}</p>
              </div>
            ))}
            {!leads.length && <div className="aiw-empty">分析后这里显示首条公开回复/人工跟进建议，不自动私信。</div>}
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
