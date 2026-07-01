import React, { useMemo, useState } from 'react'
import { apiPost, copyJson, getApiToken, saveApiToken } from './aiVideoApi'

type JsonValue = any

function countLeads(data: JsonValue) {
  const leads = data?.analysis?.leads || data?.leads || data?.enhanced_leads || []
  return Array.isArray(leads) ? leads : []
}

function countInsights(data: JsonValue) {
  const insights = data?.insights || data?.enhanced_insights || []
  return Array.isArray(insights) ? insights : []
}

function TokenInline() {
  const [token, setToken] = useState(getApiToken())
  const [saved, setSaved] = useState(false)
  return (
    <div className="tokenInline">
      <label className="productField">
        AI-VIDEO API Token
        <input
          className="productInput"
          value={token}
          onChange={(e) => {
            setToken(e.target.value)
            setSaved(false)
          }}
          placeholder="粘贴 /root/ai-video-admin-token.txt 里的管理 Token"
        />
        <small>只存在浏览器 localStorage，不再弹系统输入框。</small>
      </label>
      <button className="productBtn" onClick={() => { saveApiToken(token); setSaved(true) }}>保存 Token</button>
      <button className="productBtn secondary" onClick={() => { saveApiToken(''); setToken(''); setSaved(false) }}>清空</button>
      {saved && <div className="productNotice">Token 已保存</div>}
    </div>
  )
}

function ResultBoard({ result }: { result: JsonValue }) {
  const leads = countLeads(result)
  const insights = countInsights(result)
  const timeline = result?.timeline
  const script = result?.script
  const raw = JSON.stringify(result, null, 2)
  const aLeads = leads.filter((x) => x.priority === 'A').length
  const needHuman = leads.filter((x) => x.priority === 'A' || String(x.suggested_action || '').includes('人工')).length

  return (
    <div>
      <div className="statusBoard">
        <div className="statusTile"><b>{leads.length}</b><span>截到评论线索</span></div>
        <div className="statusTile"><b>{aLeads}</b><span>A 级线索</span></div>
        <div className="statusTile"><b>{needHuman}</b><span>需人工上报</span></div>
        <div className="statusTile"><b>{insights.length}</b><span>内容结构样本</span></div>
      </div>

      {leads.length > 0 && (
        <div className="productCardGrid">
          {leads.slice(0, 6).map((lead, index) => (
            <div className="productCard" key={`lead-${index}`}>
              <h3>{lead.priority || '线索'} / score {lead.lead_score || lead.score || '-'}</h3>
              <p>{lead.original_text || lead.text}</p>
              <div className="productTagRow">
                <span>{lead.buyer_stage || lead.capture_angle || '待判断'}</span>
                <span className={lead.priority === 'A' ? 'productTag red' : 'productTag'}>{lead.priority === 'A' ? '人工上报' : '观察'}</span>
                <span className="productTag green">可回复草稿</span>
              </div>
              {(lead.public_reply || lead.reply_draft) && <p><b>回复草稿：</b>{lead.public_reply || lead.reply_draft}</p>}
              {lead.follow_up_question && <p><b>筛选追问：</b>{lead.follow_up_question}</p>}
              {lead.script_hook && <p><b>可转视频：</b>{lead.script_hook}</p>}
            </div>
          ))}
        </div>
      )}

      {insights.length > 0 && (
        <div className="productCardGrid">
          {insights.slice(0, 6).map((item, index) => (
            <div className="productCard" key={`insight-${index}`}>
              <h3>内容结构 #{index + 1}</h3>
              <p>{item.title || item.topic_angle || '未命名内容'}</p>
              {item.opening_hook && <p><b>开头结构：</b>{item.opening_hook}</p>}
              {item.timeline_text && <p><b>文案草稿：</b>{item.timeline_text}</p>}
              {item.shot_hint && <p><b>镜头建议：</b>{item.shot_hint}</p>}
            </div>
          ))}
        </div>
      )}

      {(script || timeline) && (
        <div className="productCard">
          <h3>Timeline / 生成视频前置结果</h3>
          {script?.script_hook && <p><b>Hook：</b>{script.script_hook}</p>}
          {script?.script_text && <p>{script.script_text}</p>}
          {timeline?.srt_preview && <pre>{timeline.srt_preview}</pre>}
        </div>
      )}

      <details className="productJsonBox">
        <summary>完整 JSON / 复制</summary>
        <button className="productBtn" onClick={() => copyJson(result)}>复制 JSON</button>
        <pre>{raw}</pre>
      </details>
    </div>
  )
}

export default function OpenClawWorkbench() {
  const [rawExport, setRawExport] = useState(
    'author,title,likes,comments,shares,views,platform,url\nagent_a,马来西亚买房千万别只看价格，这三个区域最容易踩坑,1200,88,42,56000,douyin,https://example.com/v1\nagent_b,海外房产投资租金回报到底怎么算？很多人第一步就错了,850,66,25,43000,douyin,https://example.com/v2\nlead_a,马来西亚买房首付多少？哪个区适合投资出租？,18,3,0,0,douyin,https://example.com/comment/1'
  )
  const [market, setMarket] = useState('马来西亚')
  const [platform, setPlatform] = useState('douyin')
  const [targetDuration, setTargetDuration] = useState(28)
  const [realDeepSeek, setRealDeepSeek] = useState(false)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [result, setResult] = useState<JsonValue>(null)

  const estimated = useMemo(() => {
    const seconds = Math.max(8, Number(targetDuration) || 28)
    const chars = Math.round(seconds * 4.2)
    const segments = Math.max(3, Math.min(12, Math.ceil(seconds / 5)))
    return { chars, segments, seconds }
  }, [targetDuration])

  const campaignContext = useMemo(
    () => ({ market, platform, audience: `准备在${market}买房或投资的人`, target_duration: targetDuration }),
    [market, platform, targetDuration]
  )

  async function runAction(action: string) {
    setBusy(action)
    setError('')
    try {
      let data: JsonValue
      if (action === 'comment-adapter') {
        data = await apiPost('/api/video/openclaw/comments/analyze', { raw_export: rawExport, campaign_context: campaignContext, save: true, max_items: 200 })
      } else if (action === 'comment-llm') {
        data = await apiPost('/api/video/openclaw/llm-enhance/comments', { raw_export: rawExport, campaign_context: campaignContext, min_score: 40, max_llm_items: realDeepSeek ? 8 : 5, dry_run: !realDeepSeek, save_rule_leads: true })
      } else if (action === 'content-intel') {
        data = await apiPost('/api/video/openclaw/content/analyze', { raw_export: rawExport, campaign_context: campaignContext, save: true, max_items: 300 })
      } else if (action === 'content-llm') {
        data = await apiPost('/api/video/openclaw/llm-enhance/content', { raw_export: rawExport, campaign_context: campaignContext, min_score: 40, max_llm_items: realDeepSeek ? 8 : 5, dry_run: !realDeepSeek, save_rule_insights: true })
      } else if (action === 'timeline-plan') {
        data = await apiPost('/api/video/openclaw/timeline/plan', {
          raw_export: rawExport,
          campaign_context: campaignContext,
          save_insight: true,
          target_duration: targetDuration,
          target_chars: estimated.chars,
          target_segments: estimated.segments,
          min_score: 0,
          max_items: 300,
          bgm_policy: { music_type: 'instrumental_only', default_bgm_volume: 0.12, ducking_when_voice: true },
          quality_policy: { enabled: true, output_profile: 'vertical_720x1280', fps: 30 },
        })
      } else if (action === 'generate-video') {
        if (!window.confirm('这一步会调用生成视频接口，可能消耗视频额度。确认继续？')) return
        const prompt = result?.script?.script_text || result?.script?.script_hook || rawExport.slice(0, 800)
        data = await apiPost('/api/video/full-ai/start', {
          prompt,
          market,
          platform,
          target_duration: targetDuration,
          max_shots: 3,
          source: 'openclaw_workbench',
        })
      } else {
        throw new Error('未知操作')
      }
      setResult(data)
    } catch (e: any) {
      setError(e?.message || String(e))
    } finally {
      setBusy('')
    }
  }

  return (
    <section className="productPatchPanel openclawWorkbench">
      <div className="productPatchHeader">
        <div>
          <p className="productEyebrow">抖音 / OpenClaw / DeepSeek / Timeline</p>
          <h2>OpenClaw 获客截流工作台</h2>
          <p>重点看截到了什么流、是否可回复、是否需要人工上报、能不能转成下一条视频。不是纯文字说明页。</p>
        </div>
        <div className="productBadge">不调用 fal.ai，除非点生成视频</div>
      </div>

      <TokenInline />

      <div className="productGrid4">
        <label className="productField">市场<input className="productInput" value={market} onChange={(e) => setMarket(e.target.value)} /></label>
        <label className="productField">平台<input className="productInput" value={platform} onChange={(e) => setPlatform(e.target.value)} /></label>
        <label className="productField">视频长度 / 秒<input className="productInput" type="number" value={targetDuration} onChange={(e) => setTargetDuration(Number(e.target.value || 28))} /></label>
        <label className="productField">DeepSeek<input type="checkbox" checked={realDeepSeek} onChange={(e) => setRealDeepSeek(e.target.checked)} /> 真实调用</label>
      </div>

      <div className="pipelineStrip">
        <div><b>文案量</b><span>{estimated.chars} 字左右</span></div>
        <div><b>分段</b><span>{estimated.segments} 段口播</span></div>
        <div><b>采集流</b><span>评论 / 标题 / 链接</span></div>
        <div><b>承接</b><span>回复草稿 / 人工上报</span></div>
        <div><b>下一步</b><span>Timeline / 视频生成</span></div>
      </div>

      <textarea className="productTextarea" value={rawExport} onChange={(e) => setRawExport(e.target.value)} placeholder="粘贴抖音/OpenClaw 导出的 CSV、JSON、评论流" />

      <div className="productButtonRow">
        <button disabled={!!busy} onClick={() => runAction('comment-adapter')}>截流评分</button>
        <button className="purple" disabled={!!busy} onClick={() => runAction('comment-llm')}>DeepSeek 回复/上报判断</button>
        <button disabled={!!busy} onClick={() => runAction('content-intel')}>内容结构分析</button>
        <button className="purple" disabled={!!busy} onClick={() => runAction('content-llm')}>DeepSeek 改写选题</button>
        <button className="green" disabled={!!busy} onClick={() => runAction('timeline-plan')}>转 Timeline</button>
        <button className="red" disabled={!!busy || !result} onClick={() => runAction('generate-video')}>直接生成视频</button>
      </div>

      {realDeepSeek && <div className="productWarn">已开启真实 DeepSeek：会消耗余额，但不会调用 fal.ai。</div>}
      {busy && <div className="productNotice">处理中：{busy}</div>}
      {error && <div className="productError">错误：{error}</div>}
      {result && <ResultBoard result={result} />}
    </section>
  )
}
