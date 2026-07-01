import React, { useMemo, useState } from 'react'
import { apiPost, safeJson } from './aiVideoApi'

type ActionKey = 'comments' | 'llm-comments' | 'content' | 'timeline' | 'video'

const defaultStream = `comment_author,comment_text,like_count,reply_count,video_title,platform,url
用户A,马来西亚买房首付多少？哪个区域适合投资出租？,18,3,马来西亚买房避坑,douyin,https://example.com/video/1
用户B,海外房产水很深怕踩坑，有没有靠谱核验清单？,9,1,海外房产避坑,douyin,https://example.com/video/2
用户C,可以私信我吗？想了解预算和贷款。,5,2,第二家园,douyin,https://example.com/video/3`

function estimateBySeconds(seconds: number) {
  const safe = Math.max(8, Math.min(180, Number(seconds) || 28))
  const chars = Math.round(safe * 4.2)
  const segments = Math.max(3, Math.ceil(safe / 4))
  return { seconds: safe, chars, segments }
}

function splitScriptByMaterial(text: string, totalSeconds: number, materialSeconds: number) {
  const estimate = estimateBySeconds(totalSeconds)
  const parts = text.split(/[。！？!?\n]/).map((x) => x.trim()).filter(Boolean)
  const count = Math.max(1, Math.min(estimate.segments, parts.length || estimate.segments))
  return Array.from({ length: count }).map((_, index) => {
    const sentence = parts[index] || `第 ${index + 1} 段口播内容待生成。`
    const duration = Math.round((totalSeconds / count) * 10) / 10
    const materialStart = Math.round(((index * duration) % Math.max(1, materialSeconds)) * 10) / 10
    const materialEnd = Math.round(Math.min(materialSeconds, materialStart + duration) * 10) / 10
    return { index: index + 1, text: sentence, duration, materialStart, materialEnd, edit: duration > 4.5 ? '中段切两刀，保留动作变化' : '单镜头轻推近，字幕跟口播' }
  })
}

function Stat({ value, label }: { value: string | number; label: string }) {
  return <div className="workspaceStat"><b>{value}</b><span>{label}</span></div>
}

export default function OpenClawWorkbench() {
  const [market, setMarket] = useState('马来西亚')
  const [platform, setPlatform] = useState('douyin')
  const [targetSeconds, setTargetSeconds] = useState(28)
  const [materialSeconds, setMaterialSeconds] = useState(8)
  const [realDeepSeek, setRealDeepSeek] = useState(false)
  const [streamText, setStreamText] = useState(defaultStream)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [result, setResult] = useState<any>(null)
  const [lastLeads, setLastLeads] = useState<any[]>([])

  const estimate = useMemo(() => estimateBySeconds(targetSeconds), [targetSeconds])
  const editPlan = useMemo(() => splitScriptByMaterial('第二家园，只看房价？那你已经输了。身份、教育、养老、资产，要一起盘算。我们用专业模型，先筛国家，再配项目。全程托管，直到海外置业落地。私信“规划”，开始你的定制方案。', targetSeconds, materialSeconds), [targetSeconds, materialSeconds])

  const context = useMemo(() => ({ market, platform, audience: '海外置业/第二家园/子女教育/养老度假/资产配置人群' }), [market, platform])

  async function run(action: ActionKey) {
    setBusy(action)
    setError('')
    try {
      let data: any
      if (action === 'comments') {
        data = await apiPost('/api/video/openclaw/comments/analyze', { raw_export: streamText, campaign_context: context, save: true, max_items: 300 })
        setLastLeads(data?.analysis?.leads || data?.leads || [])
      } else if (action === 'llm-comments') {
        data = await apiPost('/api/video/openclaw/llm-enhance/comments', { raw_export: streamText, campaign_context: context, min_score: 35, max_llm_items: realDeepSeek ? 10 : 20, dry_run: !realDeepSeek, save_rule_leads: true })
        setLastLeads(data?.enhanced_leads || [])
      } else if (action === 'content') {
        data = await apiPost('/api/video/openclaw/content/analyze', { raw_export: streamText, campaign_context: context, save: true, max_items: 300 })
      } else if (action === 'timeline') {
        data = await apiPost('/api/video/openclaw/timeline/plan', { raw_export: streamText, campaign_context: context, save_insight: true, target_duration: targetSeconds, min_score: 0, max_items: 300 })
      } else {
        if (!window.confirm('这一步会直接调用现有视频生成接口，可能产生视频生成费用。继续吗？')) return
        data = await apiPost('/api/video/full-ai/start', { title: `${market}获客短视频`, prompt: streamText.slice(0, 900), target_duration: targetSeconds, shots: editPlan.map((x) => ({ text: x.text, duration: x.duration, shot_hint: x.edit })) })
      }
      setResult(data)
    } catch (e: any) {
      setError(e?.message || String(e))
    } finally {
      setBusy('')
    }
  }

  const leadRows = lastLeads.length ? lastLeads : [
    { priority: 'A', lead_score: 100, original_text: '马来西亚买房首付多少？哪个区域适合投资出租？', public_reply: '先看预算、用途和区域。你更关注稳定出租还是未来转手？', risk_note: '需人工确认后回复' },
    { priority: 'A', lead_score: 79, original_text: '可以私信我吗？想了解预算和贷款。', public_reply: '可以，先说预算、用途和目标区域，我帮你拆自住/投资路径。', risk_note: '建议人工上报' },
  ]

  return (
    <section className="workspacePanel openclawPanel">
      <div className="panelHero compact green">
        <div>
          <p>OPENCLAW CAPTURE BOARD</p>
          <h3>获客截流看板</h3>
          <span>这里要体现 OpenClaw 截到了什么流、哪些可回复、哪些需要人工上报，而不是一堆空文字。</span>
        </div>
        <em>不调用 fal.ai</em>
      </div>

      <div className="workspaceFormGrid four">
        <label>市场<input value={market} onChange={(e) => setMarket(e.target.value)} /></label>
        <label>平台<input value={platform} onChange={(e) => setPlatform(e.target.value)} /></label>
        <label>视频长度/秒<input type="number" value={targetSeconds} onChange={(e) => setTargetSeconds(Number(e.target.value || 28))} /></label>
        <label>单素材时长/秒<input type="number" value={materialSeconds} onChange={(e) => setMaterialSeconds(Number(e.target.value || 8))} /></label>
      </div>

      <div className="copyEstimate">
        <b>文案长度建议：约 {estimate.chars} 字 / {estimate.segments} 段口播</b>
        <span>按视频长度动态决定文案数量，后面配音和剪辑按素材时长拆分。</span>
        <label><input type="checkbox" checked={realDeepSeek} onChange={(e) => setRealDeepSeek(e.target.checked)} /> 真实调用 DeepSeek</label>
      </div>

      <textarea className="workspaceTextarea medium" value={streamText} onChange={(e) => setStreamText(e.target.value)} />

      <div className="workspaceActions">
        <button onClick={() => run('comments')}>分析截流评论</button>
        <button className="purple" onClick={() => run('llm-comments')}>生成回复/上报建议</button>
        <button onClick={() => run('content')}>内容结构分析</button>
        <button className="green" onClick={() => run('timeline')}>生成 Timeline</button>
        <button className="red" onClick={() => run('video')}>直接生成视频</button>
      </div>

      {busy && <div className="workspaceNotice">处理中：{busy}</div>}
      {error && <div className="workspaceError">错误：{error}</div>}

      <div className="workspaceStats">
        <Stat value={leadRows.length} label="截流评论" />
        <Stat value={leadRows.filter((x) => x.priority === 'A' || Number(x.lead_score || 0) >= 75).length} label="A 级线索" />
        <Stat value={leadRows.filter((x) => String(x.risk_note || x.suggested_action || '').includes('人工')).length || 1} label="需人工上报" />
        <Stat value={realDeepSeek ? '真实' : 'dry-run'} label="DeepSeek 模式" />
      </div>

      <div className="leadBoard">
        {leadRows.slice(0, 8).map((lead, index) => (
          <article className="leadCard" key={lead.lead_id || index}>
            <div><b>{lead.priority || '线索'}</b><span>{lead.lead_score || lead.score || '-'}</span></div>
            <p>{lead.original_text || lead.text || lead.comment_text}</p>
            <strong>建议回复：{lead.public_reply || lead.reply_draft || '等待 DeepSeek/规则生成'}</strong>
            <em>{lead.risk_note || lead.suggested_action || '需要人工确认后执行'}</em>
          </article>
        ))}
      </div>

      <div className="resultBoard">
        <h4>按素材长度自动分配剪辑</h4>
        {editPlan.map((x) => (
          <p key={x.index}>第{x.index}段：{x.duration}s｜素材 {x.materialStart}s - {x.materialEnd}s｜{x.edit}｜{x.text}</p>
        ))}
      </div>

      {result && <details className="workspaceJson"><summary>完整 JSON</summary><pre>{safeJson(result)}</pre></details>}
    </section>
  )
}
