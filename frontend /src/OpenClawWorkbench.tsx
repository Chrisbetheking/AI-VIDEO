import React, { useMemo, useState } from 'react'
import { apiPost, copyJson, getApiToken, saveApiToken } from './aiVideoApi'
import './product-ux-fixes.css'

type JsonValue = any

type SegmentPlan = {
  index: number
  duration: number
  text: string
  materialSlot: string
  editHint: string
}

const defaultExport = 'author,title,likes,comments,shares,views,platform,url\nagent_a,马来西亚买房千万别只看价格，这三个区域最容易踩坑,1200,88,42,56000,douyin,https://example.com/v1\nagent_b,海外房产投资租金回报到底怎么算？很多人第一步就错了,850,66,25,43000,douyin,https://example.com/v2'

function shortJson(data: JsonValue): string {
  try { return JSON.stringify(data, null, 2) } catch { return String(data) }
}

function getLeads(data: JsonValue): any[] {
  return data?.analysis?.leads || data?.leads || data?.enhanced_leads || data?.rule_result?.leads || []
}

function getInsights(data: JsonValue): any[] {
  return data?.insights || data?.enhanced_insights || data?.analysis?.insights || []
}

function splitScriptByDuration(script: string, targetDuration: number, materialDurations: number[]): SegmentPlan[] {
  const clean = script.replace(/\s+/g, ' ').trim()
  const parts = clean
    .split(/[。！？!?；;]/)
    .map((x) => x.trim())
    .filter(Boolean)

  const desiredSegments = Math.max(3, Math.min(12, Math.round(targetDuration / 3.2)))
  const sourceParts = parts.length ? parts : [clean || '这里输入口播文案']
  const grouped: string[] = []

  sourceParts.forEach((part, i) => {
    const bucket = Math.min(desiredSegments - 1, Math.floor((i / sourceParts.length) * desiredSegments))
    grouped[bucket] = grouped[bucket] ? `${grouped[bucket]}。${part}` : part
  })

  while (grouped.length < desiredSegments) grouped.push('补充一个转场或承接句')

  const totalMaterial = materialDurations.reduce((a, b) => a + b, 0) || targetDuration
  return grouped.slice(0, desiredSegments).map((text, index) => {
    const material = materialDurations[index % Math.max(1, materialDurations.length)] || targetDuration / desiredSegments
    const weight = materialDurations.length ? material / totalMaterial : 1 / desiredSegments
    const duration = Math.max(2.2, Math.min(6.5, Number((targetDuration * weight).toFixed(2))))
    const editHint = duration > material ? '素材偏短：循环/慢放/补 B-roll' : duration < material * 0.65 ? '素材偏长：截取核心动作' : '素材匹配：轻剪即可'
    return { index: index + 1, duration, text, materialSlot: `素材${(index % Math.max(1, materialDurations.length)) + 1}`, editHint }
  })
}

function TokenInline() {
  const [token, setToken] = useState(getApiToken())
  return (
    <div className="tokenInline">
      <label className="productField">
        API Token（取消弹窗，改为这里保存；留空不会打扰你，但受保护接口会 401）
        <input className="productInput" value={token} onChange={(e) => setToken(e.target.value)} placeholder="粘贴一次即可，也可以留空" />
      </label>
      <button className="productBtn secondary" onClick={() => saveApiToken(token)}>保存 Token</button>
    </div>
  )
}

function LeadBoard({ result }: { result: JsonValue }) {
  const leads = getLeads(result)
  const aCount = leads.filter((x) => x.priority === 'A' || Number(x.lead_score || 0) >= 75).length
  const replyCount = leads.filter((x) => x.public_reply || x.reply_draft).length
  const humanCount = leads.filter((x) => x.priority === 'A' || /私信|联系|微信|预算|贷款/.test(x.original_text || x.text || '')).length
  return (
    <>
      <div className="statusBoard">
        <div className="statusTile"><b>{leads.length}</b><span>截到的评论流</span></div>
        <div className="statusTile"><b>{aCount}</b><span>A 级线索</span></div>
        <div className="statusTile"><b>{replyCount}</b><span>可回复草稿</span></div>
        <div className="statusTile"><b>{humanCount}</b><span>需人工上报</span></div>
      </div>
      <div className="leadDecisionGrid">
        {leads.slice(0, 9).map((lead, index) => {
          const text = lead.original_text || lead.text || ''
          const needHuman = lead.priority === 'A' || /私信|联系|微信|预算|贷款/.test(text)
          return (
            <div className="productCard" key={lead.lead_id || index}>
              <h3>{lead.priority || '线索'} / {lead.lead_score || lead.score || '-'} 分</h3>
              <p>{text}</p>
              <div className="productTagRow">
                <span className="productTag green">{lead.capture_angle || lead.buyer_stage || '待判断'}</span>
                <span className="productTag orange">{lead.public_reply || lead.reply_draft ? '已生成回复' : '待回复'}</span>
                {needHuman && <span className="productTag red">人工上报</span>}
              </div>
              {(lead.public_reply || lead.reply_draft) && <p><b>回复：</b>{lead.public_reply || lead.reply_draft}</p>}
              {lead.follow_up_question && <p><b>追问：</b>{lead.follow_up_question}</p>}
            </div>
          )
        })}
      </div>
    </>
  )
}

export default function OpenClawWorkbench() {
  const [rawExport, setRawExport] = useState(defaultExport)
  const [market, setMarket] = useState('马来西亚')
  const [platform, setPlatform] = useState('douyin')
  const [targetDuration, setTargetDuration] = useState(28)
  const [materialDurationsText, setMaterialDurationsText] = useState('4.2,3.8,5.0,3.2,4.5')
  const [realDeepSeek, setRealDeepSeek] = useState(false)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [result, setResult] = useState<JsonValue>(null)
  const [copyText, setCopyText] = useState('第二家园，只看房价？那你已经输了。身份、教育、养老、资产，要一起盘算。我们用专业模型，先筛国家，再配项目。全程托管，直到海外置业落地。私信“规划”，开始你的定制方案。')
  const [segmentPlan, setSegmentPlan] = useState<SegmentPlan[]>([])

  const campaignContext = useMemo(() => ({ market, platform, audience: `准备在${market}买房或投资的人` }), [market, platform])
  const materialDurations = useMemo(() => materialDurationsText.split(/[，,\s]+/).map(Number).filter((x) => Number.isFinite(x) && x > 0), [materialDurationsText])
  const suggestedSegmentCount = Math.max(3, Math.min(12, Math.round(targetDuration / 3.2)))
  const suggestedWords = Math.round(targetDuration * 5.5)

  async function runAction(label: string, fn: () => Promise<any>) {
    setBusy(label)
    setError('')
    try {
      const data = await fn()
      setResult(data)
    } catch (e: any) {
      setError(e?.message || String(e))
    } finally {
      setBusy('')
    }
  }

  function buildLocalSegmentPlan() {
    const plan = splitScriptByDuration(copyText, targetDuration, materialDurations)
    setSegmentPlan(plan)
    setResult({ ok: true, provider: 'frontend_material_length_planner', targetDuration, suggestedSegmentCount, suggestedWords, materialDurations, segmentPlan: plan })
  }

  async function commentScore() {
    await runAction('评论线索评分', () => apiPost('/api/video/openclaw/comments/analyze', { raw_export: rawExport, campaign_context: campaignContext, save: true, max_items: 300 }))
  }

  async function commentLlm() {
    await runAction('DeepSeek 增强评论', () => apiPost('/api/video/openclaw/llm-enhance/comments', { raw_export: rawExport, campaign_context: campaignContext, min_score: 40, max_llm_items: realDeepSeek ? 20 : 5, dry_run: !realDeepSeek, save_rule_leads: true }))
  }

  async function contentAnalyze() {
    await runAction('内容结构分析', () => apiPost('/api/video/openclaw/content/analyze', { raw_export: rawExport, campaign_context: campaignContext, save: true, max_items: 300 }))
  }

  async function contentLlm() {
    await runAction('DeepSeek 改写选题', () => apiPost('/api/video/openclaw/llm-enhance/content', { raw_export: rawExport, campaign_context: campaignContext, min_score: 40, max_llm_items: realDeepSeek ? 20 : 5, dry_run: !realDeepSeek, save_rule_insights: true }))
  }

  async function timelinePlan() {
    await runAction('一键转 Timeline', () => apiPost('/api/video/openclaw/timeline/plan', { raw_export: rawExport, campaign_context: campaignContext, save_insight: true, target_duration: targetDuration, min_score: 0, max_items: 300, bgm_policy: { music_type: 'instrumental_only', default_bgm_volume: 0.12, ducking_when_voice: true }, quality_policy: { enabled: true, output_profile: 'vertical_720x1280', fps: 30 } }))
  }

  async function startVideoGeneration() {
    const ok = window.confirm('这个按钮会调用视频生成接口，可能消耗 fal.ai/视频生成额度。确定继续？')
    if (!ok) return
    await runAction('生成视频接口', () => apiPost('/api/video/full-ai/start', {
      title: `抖音获客视频-${market}`,
      script: copyText,
      target_duration: targetDuration,
      platform,
      market,
      shot_count: Math.min(3, Math.max(1, Math.round(targetDuration / 10))),
      style: 'douyin_real_estate_lead_generation',
      source: 'openclaw_workbench',
      material_timing_plan: segmentPlan,
    }))
  }

  const insights = getInsights(result)

  return (
    <section id="openclaw-workbench" className="productPatchPanel openclawWorkbench">
      <div className="productPatchHeader">
        <div>
          <p className="productEyebrow">DOUYIN / OPENCLAW / DEEPSEEK / TIMELINE</p>
          <h2>OpenClaw 截流工作台：采集流 → 回复判断 → 人工上报 → 视频生产</h2>
          <p>这里不再是一堆说明文字。它要体现截到了什么流、能不能自动回复、是否需要人工上报，并把文案按视频长度和素材长度拆成剪辑计划。</p>
        </div>
        <div className="productBadge">默认不调用 fal.ai</div>
      </div>

      <TokenInline />

      <div className="productGrid4">
        <label className="productField">市场<input className="productInput" value={market} onChange={(e) => setMarket(e.target.value)} /></label>
        <label className="productField">平台<input className="productInput" value={platform} onChange={(e) => setPlatform(e.target.value)} /></label>
        <label className="productField">视频长度（秒）<input className="productInput" type="number" value={targetDuration} onChange={(e) => setTargetDuration(Number(e.target.value || 28))} /></label>
        <label className="productField">真实 DeepSeek<select className="productSelect" value={realDeepSeek ? 'yes' : 'no'} onChange={(e) => setRealDeepSeek(e.target.value === 'yes')}><option value="no">否，先 dry_run</option><option value="yes">是，批量跑</option></select></label>
      </div>

      <div className="statusBoard">
        <div className="statusTile"><b>{suggestedSegmentCount}</b><span>建议口播段数</span></div>
        <div className="statusTile"><b>{suggestedWords}</b><span>建议中文字数</span></div>
        <div className="statusTile"><b>{materialDurations.length}</b><span>素材段</span></div>
        <div className="statusTile"><b>{realDeepSeek ? '开' : '关'}</b><span>DeepSeek 批量增强</span></div>
      </div>

      <label className="productField">抖音/OpenClaw 采集流（CSV / JSON / 评论 / 视频标题）<textarea className="productTextarea" value={rawExport} onChange={(e) => setRawExport(e.target.value)} /></label>

      <div className="productButtonRow">
        <button onClick={commentScore} disabled={!!busy}>截流评分</button>
        <button className="purple" onClick={commentLlm} disabled={!!busy}>DeepSeek 回复判断</button>
        <button className="secondary" onClick={contentAnalyze} disabled={!!busy}>内容结构分析</button>
        <button className="purple" onClick={contentLlm} disabled={!!busy}>DeepSeek 改写选题</button>
        <button className="green" onClick={timelinePlan} disabled={!!busy}>一键转 Timeline</button>
      </div>

      <div className="productCard" style={{ marginTop: 16 }}>
        <h3>文案数量 / 配音 / 剪辑自动分配</h3>
        <p>视频长度决定文案数量；素材长度决定每段文字的时间分配。这里先在前端做剪辑计划，后端 Render Executor 接上后直接执行。</p>
        <div className="productGrid2">
          <label className="productField">口播文案<textarea className="productTextarea" value={copyText} onChange={(e) => setCopyText(e.target.value)} /></label>
          <label className="productField">素材时长列表（秒，用逗号分隔）<textarea className="productTextarea" value={materialDurationsText} onChange={(e) => setMaterialDurationsText(e.target.value)} /></label>
        </div>
        <div className="productButtonRow">
          <button className="green" onClick={buildLocalSegmentPlan}>按素材长度自动拆配音/剪辑</button>
          <button className="red" onClick={startVideoGeneration}>直接调用生成视频接口</button>
        </div>
        {segmentPlan.length > 0 && <div className="productCardGrid">{segmentPlan.map((seg) => <div className="productCard" key={seg.index}><h3>第 {seg.index} 段 / {seg.duration}s</h3><p>{seg.text}</p><div className="productTagRow"><span>{seg.materialSlot}</span><span className="productTag orange">{seg.editHint}</span></div></div>)}</div>}
      </div>

      <div className="productWarn">字幕后端建议后续部署：faster-whisper / whisper.cpp 做识别与校准，ffmpeg + libass 做硬字幕烧录；已有时间轴时优先用 TTS 分段时间，不要重新猜。</div>

      {busy && <div className="productNotice">处理中：{busy}</div>}
      {error && <div className="productError">错误：{error}</div>}

      {result && getLeads(result).length > 0 && <LeadBoard result={result} />}

      {insights.length > 0 && <div className="productCardGrid">{insights.slice(0, 8).map((item, index) => <div className="productCard" key={index}><h3>{item.topic_angle || item.title || '内容方向'}</h3><p>{item.title}</p><p>{item.opening_hook || item.script_hook || item.timeline_text}</p><div className="productTagRow"><span>score {item.score || '-'}</span><span>{item.shot_hint || '待生成镜头'}</span></div></div>)}</div>}

      {result && <details className="productJsonBox"><summary>完整 JSON</summary><button className="productBtn secondary" onClick={() => copyJson(result)}>复制 JSON</button><pre>{shortJson(result)}</pre></details>}
    </section>
  )
}
