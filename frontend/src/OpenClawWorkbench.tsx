import React, { useMemo, useState } from 'react'
import { apiPost, errorText, normalizeCsvRows } from './aiVideoApi'

function lines(text: string) {
  return String(text || '').split(/\r?\n/).map((x) => x.trim()).filter(Boolean)
}

function commentsFromCsv(raw: string) {
  const rows = normalizeCsvRows(raw)
  if (rows.length) {
    return rows.map((r: any) => ({
      platform: r.platform || 'douyin',
      author: r.comment_author || r.author || r.user || '',
      text: r.comment_text || r.text || r.comment || r.content || r.title || '',
      like_count: Number(r.like_count || r.likes || 0) || 0,
      reply_count: Number(r.reply_count || r.replies || r.comments || 0) || 0,
      video_title: r.video_title || r.title || '',
      source_url: r.url || r.source_url || '',
    })).filter((x: any) => x.text)
  }
  return lines(raw).map((text, index) => ({ platform: 'douyin', author: `用户${index + 1}`, text }))
}

function contentRowsFromCsv(raw: string) {
  const rows = normalizeCsvRows(raw)
  if (rows.length) {
    return rows.map((r: any) => ({
      platform: r.platform || 'douyin',
      author: r.author || r.account || '',
      title: r.title || r.video_title || r.desc || '',
      desc: r.desc || r.description || r.title || '',
      like_count: Number(r.like_count || r.likes || 0) || 0,
      comment_count: Number(r.comment_count || r.comments || 0) || 0,
      share_count: Number(r.share_count || r.shares || 0) || 0,
      view_count: Number(r.view_count || r.views || 0) || 0,
      url: r.url || '',
    })).filter((x: any) => x.title || x.desc)
  }
  return []
}

function estimateChars(seconds: number) {
  return Math.round(Math.max(8, Math.min(180, seconds)) * 4.2)
}

function estimateSegments(seconds: number) {
  return Math.max(3, Math.ceil(Math.max(8, Math.min(180, seconds)) / 4))
}

export default function OpenClawWorkbench() {
  const [market, setMarket] = useState('马来西亚')
  const [platform, setPlatform] = useState('douyin')
  const [targetSeconds, setTargetSeconds] = useState(28)
  const [materialSeconds, setMaterialSeconds] = useState(0)
  const [realDeepSeek, setRealDeepSeek] = useState(false)
  const [raw, setRaw] = useState('comment_author,comment_text,like_count,reply_count,video_title,platform,url\n用户A,马来西亚买房首付多少？哪个区域适合投资出租？,18,3,马来西亚买房避坑,douyin,https://example.com/video/1\n用户B,海外房产水很深怕踩坑，有没有靠谱核验清单？,9,1,海外房产避坑,douyin,https://example.com/video/2\n用户C,可以私信我吗？想了解预算和贷款。,5,2,第二家园,douyin,https://example.com/video/3')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [leadResult, setLeadResult] = useState<any>(null)
  const [contentResult, setContentResult] = useState<any>(null)
  const [timelineResult, setTimelineResult] = useState<any>(null)
  const [videoResult, setVideoResult] = useState<any>(null)

  const comments = useMemo(() => commentsFromCsv(raw), [raw])
  const contents = useMemo(() => contentRowsFromCsv(raw), [raw])
  const aLeads = (leadResult?.enhanced_leads || leadResult?.leads || []).filter((x: any) => x.priority === 'A')
  const reportLeads = (leadResult?.enhanced_leads || leadResult?.leads || []).filter((x: any) => x.priority === 'A' || x.lead_score >= 70)
  const charAdvice = estimateChars(Number(targetSeconds) || 28)
  const segmentAdvice = estimateSegments(Number(targetSeconds) || 28)

  const campaignContext = {
    market,
    platform,
    audience: `准备在${market}买房、置业或投资的人`,
  }

  async function analyzeLeads() {
    setBusy('leads')
    setError('')
    try {
      const data = await apiPost('/api/video/openclaw/llm-enhance/comments', {
        comments,
        campaign_context: campaignContext,
        min_score: 35,
        max_llm_items: realDeepSeek ? 6 : 10,
        dry_run: !realDeepSeek,
        save_rule_leads: true,
      })
      setLeadResult(data)
    } catch (e) {
      try {
        const data = await apiPost('/api/video/comment-leads/analyze', {
          comments,
          campaign_context: campaignContext,
          save: true,
        })
        setLeadResult(data)
      } catch (e2) {
        setError(errorText(e2))
      }
    } finally {
      setBusy('')
    }
  }

  async function analyzeContent() {
    setBusy('content')
    setError('')
    try {
      const data = await apiPost('/api/video/openclaw/llm-enhance/content', {
        items: contents,
        raw_export: raw,
        campaign_context: campaignContext,
        min_score: 30,
        max_llm_items: realDeepSeek ? 5 : 8,
        dry_run: !realDeepSeek,
        save_rule_insights: true,
      })
      setContentResult(data)
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy('')
    }
  }

  async function generateTimeline() {
    setBusy('timeline')
    setError('')
    try {
      const data = await apiPost('/api/video/openclaw/timeline/plan', {
        raw_export: raw,
        campaign_context: campaignContext,
        target_duration: Number(targetSeconds) || 28,
        selected_material_seconds: Number(materialSeconds) || 0,
        min_score: 0,
        max_items: 300,
        save_insight: true,
        quality_policy: { enabled: true, output_profile: 'vertical_720x1280', fps: 30 },
        bgm_policy: { music_type: 'instrumental_only', default_bgm_volume: 0.12, ducking_when_voice: true },
      })
      setTimelineResult(data)
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy('')
    }
  }

  async function generateVideo() {
    if (!timelineResult) {
      setError('先生成 Timeline / 文稿，再生成视频。')
      return
    }
    const ok = window.confirm('确认调用生成视频接口？这一步可能产生 fal.ai / TTS / 合成费用。')
    if (!ok) return
    setBusy('video')
    setError('')
    try {
      const script = timelineResult?.script?.script_text || timelineResult?.timeline?.script_text || timelineResult?.script_text || ''
      const data = await apiPost('/api/video/full-ai/start', {
        market,
        platform,
        topic: timelineResult?.script?.topic_angle || `${market}房产短视频`,
        script,
        target_duration: Number(targetSeconds) || 28,
        source: 'openclaw_capture_board',
        openclaw_result: { leadResult, contentResult, timelineResult },
      })
      setVideoResult(data)
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy('')
    }
  }

  const resultLeads = leadResult?.enhanced_leads || leadResult?.leads || []

  return (
    <section className="uxPanel openclawCapturePanel">
      <div className="uxHero">
        <div>
          <p className="uxEyebrow">OPENCLAW CAPTURE BOARD</p>
          <h2>OpenClaw 获客截流看板</h2>
          <p>体现截到了什么流、是否可回复、是否需要人工上报；生成视频前必须先得到文稿/Timeline。</p>
        </div>
        <span className="uxGreenBadge">不调用 fal.ai</span>
      </div>

      <div className="uxGrid four">
        <label>市场<input value={market} onChange={(e) => setMarket(e.target.value)} /></label>
        <label>平台<input value={platform} onChange={(e) => setPlatform(e.target.value)} /></label>
        <label>目标视频长度/秒<input type="number" value={targetSeconds} onChange={(e) => setTargetSeconds(Number(e.target.value || 28))} /></label>
        <label>已选素材时长/秒<input type="number" value={materialSeconds} onChange={(e) => setMaterialSeconds(Number(e.target.value || 0))} /></label>
      </div>

      <div className="uxNotice">
        <b>文案长度建议：约 {charAdvice} 字 / {segmentAdvice} 段口播。</b>
        <span> 先分析截流，再生成 Timeline，最后才能生成视频。</span>
        <label className="uxInlineCheck"><input type="checkbox" checked={realDeepSeek} onChange={(e) => setRealDeepSeek(e.target.checked)} />真实调用 DeepSeek</label>
      </div>

      <textarea className="uxBigText" value={raw} onChange={(e) => setRaw(e.target.value)} />

      <div className="uxButtonRow">
        <button onClick={analyzeLeads} disabled={!!busy}>{busy === 'leads' ? '分析中...' : '分析截流评论'}</button>
        <button onClick={analyzeContent} disabled={!!busy}>内容结构分析</button>
        <button onClick={generateTimeline} disabled={!!busy}>生成文稿 / Timeline</button>
        <button className="danger" onClick={generateVideo} disabled={!timelineResult || !!busy}>生成视频</button>
      </div>

      {error && <div className="uxError">{error}</div>}

      <div className="uxStatGrid">
        <div><b>{comments.length}</b><span>截流评论</span></div>
        <div><b>{aLeads.length}</b><span>A 级线索</span></div>
        <div><b>{reportLeads.length}</b><span>需人工上报</span></div>
        <div><b>{realDeepSeek ? 'real' : 'dry-run'}</b><span>DeepSeek 模式</span></div>
      </div>

      {resultLeads.length > 0 && (
        <div className="uxCard">
          <h3>截流处理队列</h3>
          {resultLeads.slice(0, 8).map((lead: any, index: number) => (
            <div className="uxLead" key={lead.lead_id || index}>
              <div><b>{lead.priority || '线索'} / {lead.lead_score || '-'}</b><span>{lead.capture_angle || lead.buyer_stage || '待判断'}</span></div>
              <p>{lead.original_text || lead.text}</p>
              <em>{lead.public_reply || lead.reply_draft || '等待生成回复建议'}</em>
              <strong>{lead.priority === 'A' || lead.lead_score >= 70 ? '需要人工上报 / 可优先回复' : '进入观察池'}</strong>
            </div>
          ))}
        </div>
      )}

      {timelineResult && <pre className="uxJson">{JSON.stringify(timelineResult, null, 2)}</pre>}
      {videoResult && <pre className="uxJson">{JSON.stringify(videoResult, null, 2)}</pre>}
    </section>
  )
}
