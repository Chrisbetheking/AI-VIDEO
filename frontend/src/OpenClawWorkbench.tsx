import React, { useMemo, useState } from 'react'
import {
  apiPost,
  csvRows,
  detailToText,
  generateLocalScript,
  ProjectDraft,
  projectWithScript,
  splitScriptToSegments,
} from './aiVideoApi'

type WorkspaceTab = 'pure' | 'douyin' | 'openclaw' | 'digital'

type Props = {
  project: ProjectDraft
  setProject: (next: ProjectDraft) => void
  goTab?: (next: WorkspaceTab) => void
}

function extractLeads(data: any): any[] {
  const leads = data?.analysis?.leads || data?.leads || data?.enhanced_leads || data?.rule_result?.leads || []
  return Array.isArray(leads) ? leads : []
}

function extractInsights(data: any): any[] {
  const insights = data?.insights || data?.enhanced_insights || data?.content_insights || []
  return Array.isArray(insights) ? insights : []
}

const defaultCapture = `comment_author,comment_text,like_count,reply_count,video_title,platform,url
用户A,马来西亚买房首付多少？哪个区域适合投资出租？,18,3,马来西亚买房避坑,douyin,https://example.com/video/1
用户B,海外房产水很深很踩坑，有没有靠谱核验清单？,9,1,海外房产避坑,douyin,https://example.com/video/2
用户C,可以私信我吗？想了解预算和贷款。,5,2,第二家园,douyin,https://example.com/video/3`

export default function OpenClawWorkbench({ project, setProject, goTab }: Props) {
  const [rawExport, setRawExport] = useState(defaultCapture)
  const [realDeepSeek, setRealDeepSeek] = useState(false)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [result, setResult] = useState<any>(null)

  const rows = useMemo(() => csvRows(rawExport), [rawExport])
  const leads = extractLeads(result)
  const insights = extractInsights(result)
  const aLeads = leads.filter((lead) => lead.priority === 'A').length
  const needHuman = leads.filter(
    (lead) => lead.priority === 'A' || String(lead.suggested_action || '').includes('人工'),
  ).length

  async function analyzeComments(useDeepSeek: boolean) {
    setBusy(useDeepSeek ? 'deepseek-comment' : 'comment-score')
    setError('')

    try {
      const comments = rows.length
        ? rows.map((row) => ({
            platform: row.platform || project.platform,
            author: row.comment_author || row.author || '',
            text: row.comment_text || row.text || row.title || '',
            like_count: row.like_count || row.likes || 0,
            reply_count: row.reply_count || row.comments || 0,
            video_title: row.video_title || row.title || '',
            source_url: row.url || '',
          }))
        : rawExport
            .split(/\n/)
            .map((text) => text.trim())
            .filter(Boolean)

      const path = useDeepSeek ? '/api/video/openclaw/llm-enhance/comments' : '/api/video/comment-leads/analyze'
      const payload = useDeepSeek
        ? {
            comments,
            campaign_context: {
              market: project.market,
              platform: project.platform,
              target_duration: project.targetDuration,
            },
            min_score: 40,
            max_llm_items: realDeepSeek ? 10 : 5,
            dry_run: !realDeepSeek,
            save_rule_leads: true,
          }
        : {
            comments,
            campaign_context: {
              market: project.market,
              platform: project.platform,
              target_duration: project.targetDuration,
            },
            save: true,
            max_items: 300,
          }

      const data = await apiPost(path, payload)
      setResult(data)
      const nextLeads = extractLeads(data)
      setProject({ ...project, leads: nextLeads, lastOutput: data })
    } catch (err: any) {
      setError(detailToText(err?.message || err))
    } finally {
      setBusy('')
    }
  }

  function toScript() {
    const topLead = leads[0]
    const hook =
      topLead?.script_hook ||
      topLead?.public_reply ||
      topLead?.reply_draft ||
      `${project.market}买房，先别急着只问价格。`

    const topic = topLead?.script_hook || project.topic
    const base = generateLocalScript(topic, project.market, project.targetDuration)
    const script = `${hook}\n${base}`
    const next = projectWithScript({ ...project, topic, script }, script)
    setProject({
      ...next,
      leads,
      contentInsights: insights,
    })
    goTab?.('pure')
  }

  async function timelinePlan() {
    setBusy('timeline-plan')
    setError('')

    try {
      const segments = project.script
        ? splitScriptToSegments(project.script, project.targetDuration, project.materialSeconds, project.aiShotSeconds)
        : splitScriptToSegments(generateLocalScript(project.topic, project.market, project.targetDuration), project.targetDuration, project.materialSeconds, project.aiShotSeconds)

      const data = await apiPost('/api/video/timeline/render-plan', {
        segments: segments.map((seg) => ({
          index: seg.index - 1,
          start: Number(((seg.index - 1) * seg.duration).toFixed(2)),
          end: Number((seg.index * seg.duration).toFixed(2)),
          duration: seg.duration,
          text: seg.text,
          shot_hint: seg.edit,
        })),
        materials: [],
        audio_url: '',
        fit_mode: 'loop',
        material_strategy: 'round_robin',
        output_profile: 'vertical_720x1280',
        burn_subtitle: true,
      })

      setResult(data)
      setProject({ ...project, timeline: data, lastOutput: data })
    } catch (err: any) {
      setError(detailToText(err?.message || err))
    } finally {
      setBusy('')
    }
  }

  return (
    <section className="productPanel">
      <div className="productHero">
        <div>
          <p className="productEyebrow">OPENCLAW CAPTURE BOARD</p>
          <h2>获客承接看板</h2>
          <p>体现 OpenClaw 截到了什么流、哪些能回复、哪些要人工上报，能直接转文稿和 Timeline。</p>
        </div>
        <span className="productBadge">不调用 fal.ai</span>
      </div>

      <div className="productFormGrid">
        <label>
          市场
          <input value={project.market} onChange={(event) => setProject({ ...project, market: event.target.value })} />
        </label>
        <label>
          平台
          <input value={project.platform} onChange={(event) => setProject({ ...project, platform: event.target.value })} />
        </label>
        <label>
          目标视频长度/秒
          <input
            type="number"
            value={project.targetDuration}
            onChange={(event) => setProject({ ...project, targetDuration: Number(event.target.value || 28) })}
          />
        </label>
        <label className="checkLabel">
          <input type="checkbox" checked={realDeepSeek} onChange={(event) => setRealDeepSeek(event.target.checked)} />
          真实调用 DeepSeek
        </label>
      </div>

      <div className="productGrid four">
        <div className="metricCard">
          <b>{rows.length}</b>
          <span>导入评论流</span>
        </div>
        <div className="metricCard">
          <b>{aLeads}</b>
          <span>A 级线索</span>
        </div>
        <div className="metricCard">
          <b>{needHuman}</b>
          <span>需人工上报</span>
        </div>
        <div className="metricCard">
          <b>{realDeepSeek ? 'real' : 'dry-run'}</b>
          <span>DeepSeek 模式</span>
        </div>
      </div>

      <textarea
        className="productTextarea"
        value={rawExport}
        onChange={(event) => setRawExport(event.target.value)}
        placeholder="粘贴 OpenClaw / 抖音采集器回传的评论 CSV、JSON 或文本"
      />

      <div className="productButtonRow">
        <button type="button" onClick={() => analyzeComments(false)} disabled={!!busy}>
          分析截流评论
        </button>
        <button type="button" className="purple" onClick={() => analyzeComments(true)} disabled={!!busy}>
          生成回复/上报建议
        </button>
        <button type="button" className="green" onClick={toScript} disabled={!leads.length}>
          转成文稿/分镜
        </button>
        <button type="button" className="ghost" onClick={timelinePlan} disabled={!!busy}>
          生成 Timeline 计划
        </button>
      </div>

      {busy && <div className="productNotice">处理中：{busy}</div>}
      {error && <div className="productError">{error}</div>}

      {leads.length > 0 && (
        <div className="resultGrid">
          {leads.slice(0, 8).map((lead, index) => (
            <div className="resultCard" key={`${lead.lead_id || index}`}>
              <h3>
                {lead.priority || '线索'} / score {lead.lead_score || lead.score || '-'}
              </h3>
              <p>{lead.original_text || lead.text}</p>
              <p>
                <b>动作：</b>
                {lead.priority === 'A' ? '人工上报 + 优先回复' : '观察 / 内容灵感'}
              </p>
              {(lead.public_reply || lead.reply_draft) && (
                <p>
                  <b>回复：</b>
                  {lead.public_reply || lead.reply_draft}
                </p>
              )}
              {lead.script_hook && (
                <p>
                  <b>可转视频：</b>
                  {lead.script_hook}
                </p>
              )}
            </div>
          ))}
        </div>
      )}

      {result && (
        <details className="resultJson">
          <summary>完整结果</summary>
          <pre>{JSON.stringify(result, null, 2)}</pre>
        </details>
      )}
    </section>
  )
}
