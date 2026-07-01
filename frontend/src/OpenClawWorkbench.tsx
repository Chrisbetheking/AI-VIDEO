import React, { useMemo, useState } from 'react'
import { apiPost, tryPost } from './aiVideoApi'

function parseCsvComments(raw: string) {
  const lines = raw.trim().split('\n').map((x) => x.trim()).filter(Boolean)
  if (lines.length < 2) return []
  const headers = lines[0].split(',').map((x) => x.trim())
  return lines.slice(1).map((line) => {
    const parts = line.split(',')
    const obj: any = {}
    headers.forEach((h, i) => (obj[h] = parts[i]?.trim() || ''))
    return {
      author: obj.comment_author || obj.author || '',
      text: obj.comment_text || obj.text || obj.comment || obj.title || line,
      like_count: Number(obj.like_count || obj.likes || 0),
      reply_count: Number(obj.reply_count || obj.comments || 0),
      video_title: obj.video_title || obj.title || '',
      platform: obj.platform || 'douyin',
      source_url: obj.url || obj.source_url || '',
    }
  })
}

function estimateWords(seconds: number) {
  return Math.max(30, Math.round(seconds * 4.2))
}
function estimateSegments(seconds: number) {
  return Math.max(3, Math.ceil(seconds / 4.5))
}

export default function OpenClawWorkbench() {
  const [market, setMarket] = useState('马来西亚')
  const [platform, setPlatform] = useState('douyin')
  const [targetSeconds, setTargetSeconds] = useState(28)
  const [materialSeconds, setMaterialSeconds] = useState(8)
  const [realDeepSeek, setRealDeepSeek] = useState(false)
  const [raw, setRaw] = useState('comment_author,comment_text,like_count,reply_count,video_title,platform,url\n用户A,马来西亚买房首付多少？哪个区域适合投资出租？,18,3,马来西亚买房避坑,douyin,https://example.com/video/1\n用户B,海外房产水很深怕踩坑，有没有靠谱核验清单？,9,1,海外房产避坑,douyin,https://example.com/video/2\n用户C,可以私信我吗？想了解预算和贷款。,5,2,第二家园,douyin,https://example.com/video/3')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [result, setResult] = useState<any>(null)

  const comments = useMemo(() => parseCsvComments(raw), [raw])
  const wordCount = estimateWords(targetSeconds)
  const segments = estimateSegments(targetSeconds)
  const materialGap = Math.max(0, targetSeconds - materialSeconds)
  const aiShots = Math.ceil(materialGap / 7)

  const campaign_context = useMemo(() => ({ market, platform, source: 'openclaw_douyin_capture' }), [market, platform])

  const leadSummary = useMemo(() => {
    const leads = result?.data?.leads || result?.leads || result?.data?.enhanced_leads || result?.enhanced_leads || []
    const a = leads.filter((x: any) => x.priority === 'A' || Number(x.lead_score || 0) >= 75)
    const report = leads.filter((x: any) => String(x.capture_angle || '').includes('主动') || Number(x.lead_score || 0) >= 70)
    return { leads, a, report }
  }, [result])

  async function analyzeLeads() {
    setBusy('analyze')
    setError('')
    try {
      const data = await apiPost('/api/video/comment-leads/analyze', {
        comments,
        campaign_context,
        save: true,
      })
      setResult(data)
    } catch (err: any) {
      setError(err?.message || String(err))
    } finally {
      setBusy('')
    }
  }

  async function enhanceReplies() {
    setBusy('deepseek')
    setError('')
    try {
      const data = await apiPost('/api/video/openclaw/llm-enhance/comments', {
        comments,
        campaign_context,
        dry_run: !realDeepSeek,
        min_score: 40,
        max_llm_items: realDeepSeek ? 5 : 10,
      })
      setResult(data)
    } catch (err: any) {
      setError(err?.message || String(err))
    } finally {
      setBusy('')
    }
  }

  async function makeTimeline() {
    setBusy('timeline')
    setError('')
    try {
      const data = await tryPost([
        '/api/video/openclaw/timeline/plan',
        '/api/video/timeline/build',
      ], {
        raw_export: raw,
        comments,
        campaign_context,
        target_duration: targetSeconds,
        duration_seconds: targetSeconds,
        target_words: wordCount,
        target_segments: segments,
        selected_material_seconds: materialSeconds,
        material_gap_seconds: materialGap,
        ai_fill_shots: aiShots,
        platform,
      })
      setResult(data)
    } catch (err: any) {
      setError(err?.message || String(err))
    } finally {
      setBusy('')
    }
  }

  async function startVideo() {
    if (!window.confirm(`确认调用视频生成？目标 ${targetSeconds}s，素材缺口 ${materialGap}s，预计 AI 补 ${aiShots} 个镜头。`)) return
    setBusy('full-ai')
    setError('')
    try {
      const hook = leadSummary.leads?.[0]?.script_hook || '马来西亚买房，别只看价格。'
      const data = await apiPost('/api/video/full-ai/start', {
        topic: hook,
        prompt: `${market}房产短视频，抖音竖屏，${hook}`,
        market,
        platform,
        duration_seconds: targetSeconds,
        target_duration: targetSeconds,
        max_shots: Math.max(1, aiShots || Math.ceil(targetSeconds / 7)),
        copy: hook,
        comments,
        campaign_context,
      })
      setResult(data)
    } catch (err: any) {
      setError(err?.message || String(err))
    } finally {
      setBusy('')
    }
  }

  return (
    <section className="uxPanelCard">
      <div className="uxHeroRow">
        <div>
          <p className="uxEyebrow">OPENCLAW CAPTURE BOARD</p>
          <h2>OpenClaw 获客截流看板</h2>
          <p>体现 OpenClaw 截到了什么流、哪些可回复、哪些要人工上报，再按视频长度生成文案和 Timeline。</p>
        </div>
        <span className="uxBadge">不调用 fal.ai</span>
      </div>

      <div className="uxGrid4">
        <label>市场<input value={market} onChange={(e) => setMarket(e.target.value)} /></label>
        <label>平台<input value={platform} onChange={(e) => setPlatform(e.target.value)} /></label>
        <label>目标视频长度/秒<input type="number" value={targetSeconds} onChange={(e) => setTargetSeconds(Number(e.target.value || 28))} /></label>
        <label>已选素材总时长/秒<input type="number" value={materialSeconds} onChange={(e) => setMaterialSeconds(Number(e.target.value || 0))} /></label>
      </div>

      <div className="uxNotice">
        文案长度建议：约 {wordCount} 字 / {segments} 段口播。素材缺口：{materialGap}s，若直接生成视频预计补 {aiShots} 个 AI 镜头。
        <label className="uxInlineCheck"><input type="checkbox" checked={realDeepSeek} onChange={(e) => setRealDeepSeek(e.target.checked)} />真实调用 DeepSeek</label>
      </div>

      <textarea className="uxBigText" value={raw} onChange={(e) => setRaw(e.target.value)} />
      <div className="uxButtonRow">
        <button onClick={analyzeLeads} disabled={!!busy}>分析截流评论</button>
        <button onClick={enhanceReplies} disabled={!!busy}>生成回复/上报建议</button>
        <button onClick={makeTimeline} disabled={!!busy}>按时长生成 Timeline</button>
        <button className="danger" onClick={startVideo} disabled={!!busy}>直接生成视频</button>
      </div>
      {busy && <div className="uxNotice">处理中：{busy}</div>}
      {error && <div className="uxError">{error}</div>}

      <div className="uxStatsRow">
        <div className="uxStat"><b>{comments.length}</b><span>截流评论</span></div>
        <div className="uxStat"><b>{leadSummary.a.length}</b><span>A 级线索</span></div>
        <div className="uxStat"><b>{leadSummary.report.length}</b><span>需人工上报</span></div>
        <div className="uxStat"><b>{realDeepSeek ? 'real' : 'dry-run'}</b><span>DeepSeek 模式</span></div>
      </div>

      {leadSummary.leads.length > 0 && (
        <div className="uxCards">
          {leadSummary.leads.slice(0, 8).map((lead: any, i: number) => (
            <div className="uxLeadCard" key={lead.lead_id || i}>
              <div><b>{lead.priority || '线索'} · {lead.lead_score || '-'}</b><span>{lead.capture_angle || lead.buyer_stage || ''}</span></div>
              <p>{lead.original_text || lead.text}</p>
              <em>{lead.reply_draft || lead.public_reply || '等待生成回复建议'}</em>
              <strong>{Number(lead.lead_score || 0) >= 70 ? '需要人工上报/优先承接' : '可公开回复或沉淀选题'}</strong>
            </div>
          ))}
        </div>
      )}

      {result && <pre className="uxJson">{JSON.stringify(result, null, 2)}</pre>}
    </section>
  )
}
