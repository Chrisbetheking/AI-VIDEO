import React, { useMemo, useState } from 'react'
import { apiPost, csvRows, detailToText, generateLocalScript, projectWithScript, ProjectDraft, WorkspaceTab } from './aiVideoApi'

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
}

function localAnalyze(raw: string): Lead[] {
  const rows = csvRows(raw)
  const texts = rows.length
    ? rows.map((r) => r.comment_text || r.text || r.title || Object.values(r).join(' '))
    : raw.split(/\n+/).filter(Boolean)

  return texts.slice(0, 20).map((text) => {
    const score =
      20 +
      (/首付|预算|贷款|价格|买房/.test(text) ? 30 : 0) +
      (/投资|出租|租金|回报|转手/.test(text) ? 25 : 0) +
      (/私信|微信|联系|了解/.test(text) ? 30 : 0) +
      (/哪里|哪个|多少|吗|？|\?/.test(text) ? 12 : 0)
    const finalScore = Math.min(100, score)
    return {
      text,
      score: finalScore,
      priority: finalScore >= 75 ? 'A' : finalScore >= 55 ? 'B' : 'C',
      reply: '先别急着看项目，建议先确认预算、用途和目标区域。真实价格、户型和周边以官方资料为准。',
      report: finalScore >= 75,
    }
  })
}

export default function OpenClawWorkbench({ project, setProject, goTab }: Props) {
  const [raw, setRaw] = useState(
    'comment_author,comment_text,like_count,reply_count,video_title,platform,url\n用户A,马来西亚买房首付多少？哪个区域适合投资出租？,18,3,马来西亚买房避坑,douyin,https://example.com/video/1\n用户B,海外房产水很深怕踩坑，有没有靠谱核验清单？,9,1,海外房产避坑,douyin,https://example.com/video/2\n用户C,可以私信我吗？想了解预算和贷款。,5,2,第二家园,douyin,https://example.com/video/3',
  )
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [leads, setLeads] = useState<Lead[]>([])
  const [result, setResult] = useState<any>(null)

  const stats = useMemo(() => {
    const a = leads.filter((x) => x.priority === 'A').length
    const report = leads.filter((x) => x.report).length
    return { count: leads.length, a, report }
  }, [leads])

  async function analyze() {
    setBusy('analyze')
    setError('')
    const local = localAnalyze(raw)
    setLeads(local)

    try {
      const rows = csvRows(raw)
      const comments = rows.map((r) => ({
        text: r.comment_text || r.text || r.title || Object.values(r).join(' '),
        like_count: r.like_count || r.likes || 0,
        reply_count: r.reply_count || r.replies || 0,
        platform: r.platform || 'douyin',
        video_title: r.video_title || r.title || '',
        source_url: r.url || '',
      }))
      const data = await apiPost('/api/video/openclaw/llm-enhance/comments', {
        dry_run: true,
        max_llm_items: 5,
        min_score: 40,
        campaign_context: { market: project.market, platform: 'douyin' },
        comments,
      })
      setResult(data)
    } catch (err) {
      setResult({ ok: false, fallback: 'local_analyze', message: detailToText(err) })
    } finally {
      setBusy('')
    }
  }

  function toScript() {
    const top = leads[0]?.text || project.topic
    const script = generateLocalScript(top, project.market, project.targetDuration)
    setProject(projectWithScript({ ...project, topic: top, leads }, script, { title: top }))
    goTab('pureai')
  }

  return (
    <section className="aiw-card">
      <div className="aiw-hero">
        <div>
          <p className="aiw-eyebrow">OPENCLAW CAPTURE BOARD</p>
          <h2>获客截流承接看板</h2>
          <p>体现 OpenClaw 截到了什么流、哪些能回复、哪些需要人工上报，然后直接转文稿和视频。</p>
        </div>
        <span className="aiw-badge ok">不调用 fal.ai</span>
      </div>

      <div className="aiw-form two">
        <label>
          OpenClaw 评论 / CSV / JSON
          <textarea value={raw} onChange={(e) => setRaw(e.target.value)} />
        </label>
        <label>
          承接策略
          <textarea value={'A 级线索：人工优先处理\nB/C 级线索：生成公开回复草稿\n高频问题：转成下一条视频选题'} readOnly />
        </label>
      </div>

      <div className="aiw-actions">
        <button className="aiw-primary" onClick={analyze} disabled={!!busy}>{busy ? '分析中...' : '分析截流评论'}</button>
        <button className="aiw-purple" onClick={toScript} disabled={!leads.length}>把线索转成文稿/分镜</button>
        <button className="aiw-muted" onClick={() => goTab('pureai')}>去生成视频</button>
      </div>

      <div className="aiw-metrics">
        <div><b>{stats.count}</b><span>截流评论</span></div>
        <div><b>{stats.a}</b><span>A 级线索</span></div>
        <div><b>{stats.report}</b><span>需人工上报</span></div>
        <div><b>{result?.ok ? '已接后端' : '本地预判'}</b><span>分析模式</span></div>
      </div>

      {error && <div className="aiw-error">{error}</div>}

      <div className="aiw-twoCol">
        <div className="aiw-panel">
          <h3>截流线索</h3>
          <div className="aiw-segmentList">
            {leads.map((lead, index) => (
              <div className="aiw-segment" key={`${lead.text}-${index}`}>
                <b>{lead.priority} / {lead.score}</b>
                <p>{lead.text}</p>
                <span>{lead.report ? '需要人工上报' : '可生成公开回复'}</span>
              </div>
            ))}
          </div>
        </div>
        <div className="aiw-panel">
          <h3>回复建议</h3>
          <div className="aiw-segmentList">
            {leads.map((lead, index) => (
              <div className="aiw-segment" key={`${lead.reply}-${index}`}>
                <b>{lead.priority} 线索</b>
                <p>{lead.reply}</p>
              </div>
            ))}
          </div>
        </div>
      </div>

      {result && (
        <details className="aiw-json">
          <summary>后端分析结果</summary>
          <pre>{JSON.stringify(result, null, 2)}</pre>
        </details>
      )}
    </section>
  )
}
