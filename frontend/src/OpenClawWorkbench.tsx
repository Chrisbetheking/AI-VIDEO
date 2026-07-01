import React, { useMemo, useState } from 'react'
import { apiPost, copyJson } from './aiVideoApi'

type JsonValue = any

function asLeads(data: JsonValue) {
  const leads = data?.analysis?.leads || data?.leads || data?.enhanced_leads || []
  return Array.isArray(leads) ? leads : []
}

function asInsights(data: JsonValue) {
  const insights = data?.insights || data?.enhanced_insights || []
  return Array.isArray(insights) ? insights : []
}

function ResultBoard({ result }: { result: JsonValue }) {
  const leads = asLeads(result)
  const insights = asInsights(result)
  const timeline = result?.timeline
  const script = result?.script
  const aLeads = leads.filter((x) => x.priority === 'A').length
  const needHuman = leads.filter((x) => x.priority === 'A' || String(x.suggested_action || '').includes('人工')).length

  return (
    <div className="resultBoard">
      <div className="statusBoard">
        <div className="statusTile"><b>{leads.length}</b><span>截流评论</span></div>
        <div className="statusTile"><b>{aLeads}</b><span>A 级线索</span></div>
        <div className="statusTile"><b>{needHuman}</b><span>需人工上报</span></div>
        <div className="statusTile"><b>{insights.length}</b><span>内容结构</span></div>
      </div>

      {leads.length > 0 && <div className="leadPipeline">{leads.slice(0, 10).map((lead, index) => <div className="leadCard" key={lead.lead_id || index}><div className="leadTop"><b>{lead.priority || '线索'} / score {lead.lead_score || lead.score || '-'}</b><span>{lead.priority === 'A' ? '人工上报' : '自动观察'}</span></div><p>{lead.original_text || lead.text}</p><div className="leadStatusRow"><em>状态：{lead.capture_angle || lead.buyer_stage || '待判断'}</em><em>动作：{lead.priority === 'A' ? '人工确认后回复/私域承接' : '沉淀为选题素材'}</em></div>{(lead.public_reply || lead.reply_draft) && <p className="replyBox">回复草稿：{lead.public_reply || lead.reply_draft}</p>}{lead.script_hook && <p className="hookBox">可转视频：{lead.script_hook}</p>}</div>)}</div>}
      {insights.length > 0 && <div className="productCardGrid">{insights.slice(0, 6).map((item: any, index: number) => <div className="productCard" key={index}><h3>内容结构 #{index + 1}</h3><p>{item.title || item.topic_angle || '未命名内容'}</p>{item.opening_hook && <p className="hookBox">开头结构：{item.opening_hook}</p>}{item.timeline_text && <p>{item.timeline_text}</p>}</div>)}</div>}
      {(script || timeline) && <div className="productCard wide"><h3>Timeline / 生成视频前置结果</h3>{script?.script_hook && <p className="hookBox">Hook：{script.script_hook}</p>}{script?.script_text && <p>{script.script_text}</p>}{timeline?.srt_preview && <pre className="miniPre">{timeline.srt_preview}</pre>}</div>}
      <details className="productJsonBox"><summary>完整 JSON / 复制</summary><button className="productBtn" onClick={() => copyJson(result)}>复制 JSON</button><pre>{JSON.stringify(result, null, 2)}</pre></details>
    </div>
  )
}

export default function OpenClawWorkbench() {
  const [rawExport, setRawExport] = useState('comment_author,comment_text,like_count,reply_count,video_title,platform,url\n用户A,马来西亚买房首付多少？哪个区域适合投资出租？,18,3,马来西亚买房避坑,douyin,https://example.com/video/1\n用户B,海外房产水很深怕踩坑，有没有靠谱核验清单？,9,1,海外房产避坑,douyin,https://example.com/video/2\n用户C,可以私信我吗？想了解预算和贷款。,5,2,第二家园,douyin,https://example.com/video/3')
  const [market, setMarket] = useState('马来西亚')
  const [platform, setPlatform] = useState('douyin')
  const [targetDuration, setTargetDuration] = useState(35)
  const [materialDuration, setMaterialDuration] = useState(18)
  const [realDeepSeek, setRealDeepSeek] = useState(false)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [result, setResult] = useState<JsonValue>(null)

  const estimated = useMemo(() => {
    const seconds = Math.max(8, Number(targetDuration) || 35)
    const material = Math.max(0, Number(materialDuration) || 0)
    const chars = Math.round(seconds * 4.2)
    const segments = Math.max(3, Math.min(30, Math.ceil(seconds / 4.5)))
    const clipCount = Math.max(1, Math.ceil(seconds / 6))
    const falFillSeconds = Math.max(0, seconds - material)
    return { seconds, material, chars, segments, clipCount, falFillSeconds, needFal: falFillSeconds > 0 }
  }, [targetDuration, materialDuration])

  const campaignContext = useMemo(() => ({ market, platform, audience: `准备在${market}买房或投资的人`, target_duration: targetDuration, target_chars: estimated.chars, target_segments: estimated.segments }), [market, platform, targetDuration, estimated.chars, estimated.segments])

  async function runAction(action: string) {
    setBusy(action)
    setError('')
    try {
      let data: JsonValue
      if (action === 'comment-adapter') {
        data = await apiPost('/api/video/openclaw/comments/analyze', { raw_export: rawExport, campaign_context: campaignContext, save: true, max_items: 500 })
      } else if (action === 'comment-llm') {
        data = await apiPost('/api/video/openclaw/llm-enhance/comments', { raw_export: rawExport, campaign_context: campaignContext, min_score: 40, max_llm_items: realDeepSeek ? 30 : 8, dry_run: !realDeepSeek, save_rule_leads: true })
      } else if (action === 'content-intel') {
        data = await apiPost('/api/video/openclaw/content/analyze', { raw_export: rawExport, campaign_context: campaignContext, save: true, max_items: 500 })
      } else if (action === 'timeline-plan') {
        data = await apiPost('/api/video/openclaw/timeline/plan', { raw_export: rawExport, campaign_context: campaignContext, save_insight: true, target_duration: targetDuration, target_chars: estimated.chars, target_segments: estimated.segments, min_score: 0, max_items: 500, render_hint: { selected_material_seconds: materialDuration, fal_fill_seconds: estimated.falFillSeconds, use_fal_if_material_insufficient: estimated.needFal, edit_strategy: '按素材时长切分；强线索问题快切；信任/风险证明慢一点；结尾留私信筛选。' }, bgm_policy: { music_type: 'instrumental_only', default_bgm_volume: 0.12, ducking_when_voice: true }, quality_policy: { enabled: true, output_profile: 'vertical_720x1280', fps: 30 } })
      } else if (action === 'generate-video') {
        if (!window.confirm(`确认生成视频？目标 ${estimated.seconds} 秒。${estimated.needFal ? `素材缺 ${estimated.falFillSeconds} 秒，将用 fal.ai 补镜头。` : '素材够用，优先剪辑。'}`)) return
        const prompt = result?.script?.script_text || result?.script?.script_hook || rawExport.slice(0, 1200)
        data = await apiPost('/api/video/full-ai/start', { prompt, market, platform, target_duration: targetDuration, duration_seconds: targetDuration, max_shots: Math.min(3, Math.max(1, estimated.clipCount)), source: 'openclaw_capture_board', use_fal_if_material_insufficient: estimated.needFal, fal_fill_seconds: estimated.falFillSeconds })
      } else throw new Error('未知操作')
      setResult(data)
    } catch (e: any) {
      setError(e?.message || String(e))
    } finally {
      setBusy('')
    }
  }

  return (
    <section className="workspacePanel">
      <div className="panelHero greenHero"><div><p>OPENCLAW CAPTURE BOARD</p><h2>OpenClaw 获客截流看板</h2><span>体现 OpenClaw 截到了什么流、哪些可回复、哪些要人工上报、哪些能转视频。</span></div><b>不调用 fal.ai</b></div>
      <div className="inputGrid four"><label>市场<input value={market} onChange={(e) => setMarket(e.target.value)} /></label><label>平台<input value={platform} onChange={(e) => setPlatform(e.target.value)} /></label><label>视频长度/秒<input type="number" value={targetDuration} onChange={(e) => setTargetDuration(Number(e.target.value || 35))} /></label><label>已选素材总时长/秒<input type="number" value={materialDuration} onChange={(e) => setMaterialDuration(Number(e.target.value || 0))} /></label></div>
      <div className="estimateStrip"><b>{estimated.seconds} 秒 ≈ {estimated.chars} 字 / {estimated.segments} 段口播</b><span>{estimated.needFal ? `素材不够：缺 ${estimated.falFillSeconds} 秒，生成视频时用 fal.ai 补镜头。` : '素材够用：优先按素材长度自动剪辑。'}</span><label><input type="checkbox" checked={realDeepSeek} onChange={(e) => setRealDeepSeek(e.target.checked)} />真实调用 DeepSeek</label></div>
      <textarea className="captureTextArea" value={rawExport} onChange={(e) => setRawExport(e.target.value)} />
      <div className="buttonRow"><button onClick={() => runAction('comment-adapter')} disabled={!!busy}>分析截流评论</button><button className="purple" onClick={() => runAction('comment-llm')} disabled={!!busy}>生成回复/上报建议</button><button onClick={() => runAction('content-intel')} disabled={!!busy}>内容结构分析</button><button className="green" onClick={() => runAction('timeline-plan')} disabled={!!busy}>生成 Timeline</button><button className="red" onClick={() => runAction('generate-video')} disabled={!!busy}>直接生成视频</button></div>
      {busy && <div className="productNotice">处理中：{busy}</div>}{error && <div className="productError">错误：{error}</div>}{result && <ResultBoard result={result} />}
    </section>
  )
}
