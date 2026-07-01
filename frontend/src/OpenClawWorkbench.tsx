import React, { useMemo, useState } from 'react'
import { apiPost, buildFullAiPayload, computeVideoPlan, csvRows, detailToText, generateLocalScript, ProjectDraft, projectWithScript, splitScriptToSegments, WorkspaceTab } from './aiVideoApi'

type Props = { project: ProjectDraft; setProject: (p: ProjectDraft) => void; goTab: (tab: WorkspaceTab) => void }

type CommentItem = { platform: string; author: string; text: string; like_count: number; reply_count: number; video_title: string; source_url: string }

const sample = `comment_author,comment_text,like_count,reply_count,video_title,platform,url
用户A,马来西亚买房首付多少？哪个区域适合投资出租？,18,3,马来西亚买房避坑,douyin,https://example.com/video/1
用户B,海外房产水很深怕踩坑，有没有靠谱核验清单？,9,1,海外房产避坑,douyin,https://example.com/video/2
用户C,可以私信我吗？想了解预算和贷款。,5,2,第二家园,douyin,https://example.com/video/3`

function normalizeComments(text: string, project: ProjectDraft): CommentItem[] {
  const rows = csvRows(text)
  if (rows.length) {
    return rows.map((r) => ({
      platform: r.platform || project.platform || 'douyin',
      author: r.comment_author || r.author || r.username || '',
      text: r.comment_text || r.text || r.comment || r.content || '',
      like_count: Number(r.like_count || r.likes || 0),
      reply_count: Number(r.reply_count || r.replies || 0),
      video_title: r.video_title || r.title || project.topic,
      source_url: r.url || r.source_url || '',
    })).filter((x) => x.text)
  }
  return text.split(/\r?\n/).map((x) => x.trim()).filter(Boolean).map((line) => ({ platform: project.platform || 'douyin', author: '', text: line, like_count: 0, reply_count: 0, video_title: project.topic, source_url: '' }))
}

function LeadList({ leads }: { leads: any[] }) {
  if (!leads.length) return <div className="ux-note">还没有截流结果。先分析评论流。</div>
  return <div className="ux-grid two">{leads.slice(0, 10).map((lead, i) => <div className="ux-panel" key={lead.lead_id || i}><b>{lead.priority || '线索'} / {lead.lead_score ?? lead.score ?? '-'}</b><span>{lead.capture_angle || lead.buyer_stage || '待判断'}</span><p>{lead.original_text || lead.text}</p><em>回复建议：{lead.public_reply || lead.reply_draft || '待生成'}</em><strong>{(lead.priority === 'A' || Number(lead.lead_score || 0) >= 75) ? '需要人工上报/优先跟进' : '可公开回复/沉淀选题'}</strong></div>)}</div>
}

export default function OpenClawWorkbench({ project, setProject, goTab }: Props) {
  const [raw, setRaw] = useState(sample)
  const [runDeepSeek, setRunDeepSeek] = useState(false)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [result, setResult] = useState<any>(null)
  const comments = useMemo(() => normalizeComments(raw, project), [raw, project])
  const plan = useMemo(() => computeVideoPlan(project.targetDuration, project.materialSeconds, project.aiShotSeconds), [project.targetDuration, project.materialSeconds, project.aiShotSeconds])
  const leads = (result?.enhanced_leads || result?.leads || result?.analysis?.leads || project.leads || []) as any[]
  const aCount = leads.filter((x) => x.priority === 'A' || Number(x.lead_score || x.score || 0) >= 75).length
  const reportCount = leads.filter((x) => x.priority === 'A' || String(x.capture_angle || '').includes('主动联系')).length
  function patch(next: Partial<ProjectDraft>) { setProject({ ...project, ...next }) }

  async function analyzeComments() {
    setBusy('comments'); setError('')
    try {
      const body = { comments, raw_export: raw, campaign_context: { market: project.market, platform: project.platform, video_title: project.topic }, min_score: 40, max_llm_items: runDeepSeek ? 10 : 5, dry_run: !runDeepSeek, save: true }
      let data: any
      try { data = await apiPost(runDeepSeek ? '/api/video/openclaw/llm-enhance/comments' : '/api/video/comment-leads/analyze', body) } catch { data = await apiPost('/api/video/comment-leads/analyze', { comments, campaign_context: body.campaign_context, save: true }) }
      const nextLeads = data.enhanced_leads || data.leads || data.analysis?.leads || []
      const top = nextLeads[0]
      patch({ leads: nextLeads, topic: top?.script_hook || top?.capture_angle || project.topic, lastOutput: data })
      setResult(data)
    } catch (err) { setError(detailToText(err)) } finally { setBusy('') }
  }

  function buildScriptFromLeads() {
    const top = leads[0]
    const topic = top?.script_hook || project.topic
    const script = top ? [top.script_hook || `${project.market}买房，别只看表面。`, top.reply_draft || top.public_reply || '先看预算、用途和区域，别一上来只问价格。', '真实房源、户型、价格和周边，都必须以官方资料为准。', '想少踩坑，先把预算、目标城市和自住/投资用途说清楚。'].join('\n') : generateLocalScript(project.topic, project.market, plan.duration)
    const nextProject = projectWithScript({ ...project, title: topic, topic }, script)
    setProject(nextProject)
    setResult({ ok: true, mode: 'lead_to_script', topic, script, segments: nextProject.segments })
  }

  async function buildTimeline() {
    const script = project.script || generateLocalScript(project.topic, project.market, plan.duration)
    const segments = project.segments?.length ? project.segments : splitScriptToSegments(script, plan.duration, project.materialSeconds, project.aiShotSeconds)
    setBusy('timeline'); setError('')
    try {
      let data: any
      try { data = await apiPost('/api/video/timeline/build', { text: script, script_text: script, target_duration: plan.duration, platform: project.platform, market: project.market }) } catch (err) { data = { ok: true, mode: 'local_timeline_fallback', segments, backend_error: detailToText(err) } }
      patch({ script, segments, timeline: data, lastOutput: data })
      setResult(data)
    } catch (err) { setError(detailToText(err)) } finally { setBusy('') }
  }

  async function generateVideo() {
    if (!project.script || !project.segments?.length) { setError('没有文稿/分镜，不能生成视频。先点“生成文稿/上报建议”或“生成 Timeline”。'); return }
    if (!window.confirm('将调用完整视频生成接口。确认继续？')) return
    setBusy('video'); setError('')
    try { const data = await apiPost('/api/video/full-ai/start', buildFullAiPayload(project), 360000); patch({ lastOutput: data }); setResult(data) } catch (err) { setError(detailToText(err)) } finally { setBusy('') }
  }

  return (
    <section className="ux-card">
      <div className="ux-hero"><div><p className="ux-eyebrow">OPENCLAW CAPTURE / LEAD BOARD</p><h2>OpenClaw 获客截流看板</h2><p>这里显示 OpenClaw/采集器截到什么流、哪些可回复、哪些需要人工上报，并把线索推进文稿、Timeline 和视频生产。</p></div><span className="ux-badge green">不调用 fal.ai</span></div>
      <div className="ux-grid four"><label>市场<input value={project.market} onChange={(e) => patch({ market: e.target.value })} /></label><label>平台<input value={project.platform} onChange={(e) => patch({ platform: e.target.value })} /></label><label>视频长度/秒<input type="number" value={project.targetDuration} onChange={(e) => patch({ targetDuration: Number(e.target.value || 28) })} /></label><label className="ux-check"><input type="checkbox" checked={runDeepSeek} onChange={(e) => setRunDeepSeek(e.target.checked)} />真实调用 DeepSeek</label></div>
      <div className="ux-note">文案建议：约 {plan.suggestedChars} 字 / {plan.segmentCount} 段口播。截流结果会转成文稿、Timeline、回复建议和人工上报项。</div>
      <textarea className="ux-textarea" value={raw} onChange={(e) => setRaw(e.target.value)} />
      <div className="ux-button-row"><button className="ux-primary" onClick={analyzeComments} disabled={!!busy}>{busy === 'comments' ? '分析中...' : '分析截流评论'}</button><button className="ux-purple" onClick={buildScriptFromLeads}>生成文稿/上报建议</button><button className="ux-ghost" onClick={buildTimeline} disabled={!!busy}>{busy === 'timeline' ? '生成中...' : '生成 Timeline'}</button><button className="ux-danger" onClick={generateVideo} disabled={!project.script || !!busy}>{busy === 'video' ? '提交中...' : '生成完整视频'}</button><button className="ux-ghost" onClick={() => goTab('pureai')}>去纯 AI 路径</button></div>
      <div className="ux-metrics four"><div><b>{comments.length}</b><span>截流评论</span></div><div><b>{aCount}</b><span>A 级线索</span></div><div><b>{reportCount}</b><span>需人工上报</span></div><div><b>{runDeepSeek ? 'real' : 'dry-run'}</b><span>DeepSeek 模式</span></div></div>
      {error && <div className="ux-error">{error}</div>}
      <LeadList leads={leads} />
      {project.script && <div className="ux-panel"><h3>已进入生产链路的文稿</h3><pre className="ux-script">{project.script}</pre></div>}
      {result && <details className="ux-json"><summary>完整结果</summary><pre>{JSON.stringify(result, null, 2)}</pre></details>}
    </section>
  )
}
