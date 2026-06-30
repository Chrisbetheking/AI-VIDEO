import React, { useMemo, useState } from 'react'

type JsonValue = any

const API_BASE = 'https://ai-video.47-76-143-158.sslip.io'
const TOKEN_KEY = 'ai_video_api_token'

function getToken(): string {
  const existing = localStorage.getItem(TOKEN_KEY)
  if (existing) return existing

  const input = window.prompt('请输入 AI-VIDEO API Token')
  if (!input) throw new Error('缺少 API Token')
  localStorage.setItem(TOKEN_KEY, input.trim())
  return input.trim()
}

async function postJson(path: string, body: JsonValue): Promise<JsonValue> {
  const token = getToken()
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-AI-Video-Token': token,
    },
    body: JSON.stringify(body),
  })

  const text = await res.text()
  let data: JsonValue

  try {
    data = text ? JSON.parse(text) : {}
  } catch {
    data = { raw: text }
  }

  if (!res.ok) {
    const message = data?.detail || data?.message || `HTTP ${res.status}`
    throw new Error(message)
  }

  return data
}

function shortJson(data: JsonValue): string {
  try {
    return JSON.stringify(data, null, 2)
  } catch {
    return String(data)
  }
}

function copyText(text: string) {
  navigator.clipboard?.writeText(text).catch(() => {})
}

function getLeads(data: JsonValue): any[] {
  return data?.analysis?.leads || data?.leads || data?.enhanced_leads || []
}

function getInsights(data: JsonValue): any[] {
  return data?.insights || data?.enhanced_insights || []
}

function ResultCard({ result }: { result: JsonValue }) {
  const leads = getLeads(result)
  const insights = getInsights(result)
  const timeline = result?.timeline
  const script = result?.script
  const raw = shortJson(result)

  return (
    <div className="openclawResult">
      <div className="openclawResultHeader">
        <div>
          <b>结果</b>
          <span>{result?.provider || result?.analysis?.provider || 'unknown'}</span>
        </div>
        <button className="openclawMiniButton" onClick={() => copyText(raw)}>
          复制 JSON
        </button>
      </div>

      {leads.length > 0 && (
        <div className="openclawCards">
          {leads.slice(0, 8).map((lead, index) => (
            <div className="openclawItem" key={`lead-${index}`}>
              <div className="openclawItemTop">
                <b>{lead.priority || '线索'}</b>
                <span>score {lead.lead_score || lead.score || '-'}</span>
                <span>{lead.buyer_stage || lead.capture_angle || ''}</span>
              </div>
              <p>{lead.original_text || lead.text}</p>
              {lead.public_reply || lead.reply_draft ? (
                <p className="openclawReply">回复：{lead.public_reply || lead.reply_draft}</p>
              ) : null}
              {lead.follow_up_question ? (
                <p className="openclawHint">追问：{lead.follow_up_question}</p>
              ) : null}
              {lead.script_hook ? (
                <p className="openclawHook">Hook：{lead.script_hook}</p>
              ) : null}
            </div>
          ))}
        </div>
      )}

      {insights.length > 0 && (
        <div className="openclawCards">
          {insights.slice(0, 8).map((item, index) => (
            <div className="openclawItem" key={`insight-${index}`}>
              <div className="openclawItemTop">
                <b>{item.priority || '选题'}</b>
                <span>score {item.score || '-'}</span>
                <span>{item.topic_angle || ''}</span>
              </div>
              <p>{item.title}</p>
              {item.opening_hook ? (
                <p className="openclawHook">Hook：{item.opening_hook}</p>
              ) : null}
              {item.timeline_text ? (
                <p className="openclawReply">脚本：{item.timeline_text}</p>
              ) : null}
              {item.shot_hint ? (
                <p className="openclawHint">shot_hint：{item.shot_hint}</p>
              ) : null}
            </div>
          ))}
        </div>
      )}

      {script && (
        <div className="openclawItem">
          <div className="openclawItemTop">
            <b>脚本 / Timeline 输入</b>
            <span>{script.topic_angle || ''}</span>
          </div>
          <p className="openclawHook">{script.script_hook}</p>
          <p>{script.script_text}</p>
        </div>
      )}

      {timeline && (
        <div className="openclawItem">
          <div className="openclawItemTop">
            <b>Timeline</b>
            <span>{timeline.segment_count || 0} 段</span>
            <span>{timeline.total_duration || '-'} 秒</span>
          </div>
          <pre className="openclawPre">{timeline.srt_preview || shortJson(timeline.segments || [])}</pre>
        </div>
      )}

      <details className="openclawJsonBox">
        <summary>查看完整 JSON</summary>
        <pre>{raw}</pre>
      </details>
    </div>
  )
}

export default function OpenClawWorkbench() {
  const [rawExport, setRawExport] = useState(
    'author,title,likes,comments,shares,views,platform,url\\nagent_a,马来西亚买房千万别只看价格，这三个区域最容易踩坑,1200,88,42,56000,douyin,https://example.com/v1\\nagent_b,海外房产投资租金回报到底怎么算？很多人第一步就错了,850,66,25,43000,douyin,https://example.com/v2'
  )
  const [market, setMarket] = useState('马来西亚')
  const [platform, setPlatform] = useState('douyin')
  const [targetDuration, setTargetDuration] = useState(28)
  const [realDeepSeek, setRealDeepSeek] = useState(false)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [result, setResult] = useState<JsonValue>(null)

  const campaignContext = useMemo(
    () => ({
      market,
      platform,
      audience: `准备在${market}买房或投资的人`,
    }),
    [market, platform]
  )

  async function runAction(action: string) {
    setBusy(action)
    setError('')
    setResult(null)

    try {
      let data: JsonValue

      if (action === 'comment-adapter') {
        data = await postJson('/api/video/openclaw/comments/analyze', {
          raw_export: rawExport,
          campaign_context: campaignContext,
          save: true,
          max_items: 200,
        })
      } else if (action === 'comment-llm') {
        data = await postJson('/api/video/openclaw/llm-enhance/comments', {
          raw_export: rawExport,
          campaign_context: campaignContext,
          min_score: 40,
          max_llm_items: realDeepSeek ? 1 : 5,
          dry_run: !realDeepSeek,
          save_rule_leads: true,
        })
      } else if (action === 'content-intel') {
        data = await postJson('/api/video/openclaw/content/analyze', {
          raw_export: rawExport,
          campaign_context: campaignContext,
          save: true,
          max_items: 300,
        })
      } else if (action === 'content-llm') {
        data = await postJson('/api/video/openclaw/llm-enhance/content', {
          raw_export: rawExport,
          campaign_context: campaignContext,
          min_score: 40,
          max_llm_items: realDeepSeek ? 1 : 5,
          dry_run: !realDeepSeek,
          save_rule_insights: true,
        })
      } else if (action === 'timeline-plan') {
        data = await postJson('/api/video/openclaw/timeline/plan', {
          raw_export: rawExport,
          campaign_context: campaignContext,
          save_insight: true,
          target_duration: targetDuration,
          min_score: 0,
          max_items: 300,
          bgm_policy: {
            music_type: 'instrumental_only',
            default_bgm_volume: 0.12,
            ducking_when_voice: true,
          },
          quality_policy: {
            enabled: true,
            output_profile: 'vertical_720x1280',
            fps: 30,
          },
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
    <section className="openclawWorkbench">
      <div className="openclawTitleRow">
        <div>
          <p className="openclawEyebrow">抖音 / OpenClaw / DeepSeek / Timeline</p>
          <h2>OpenClaw 获客与选题工作台</h2>
          <p>
            粘贴抖音/OpenClaw 导出的评论、视频标题、CSV 或 JSON，直接分析线索、拆爆点、DeepSeek 增强、转 Timeline。
          </p>
        </div>
        <div className="openclawBadge">不调用 fal.ai</div>
      </div>

      <div className="openclawGrid">
        <label>
          市场
          <input value={market} onChange={(e) => setMarket(e.target.value)} />
        </label>
        <label>
          平台
          <input value={platform} onChange={(e) => setPlatform(e.target.value)} />
        </label>
        <label>
          Timeline 目标时长
          <input
            type="number"
            value={targetDuration}
            onChange={(e) => setTargetDuration(Number(e.target.value || 28))}
          />
        </label>
        <label className="openclawCheckbox">
          <input
            type="checkbox"
            checked={realDeepSeek}
            onChange={(e) => setRealDeepSeek(e.target.checked)}
          />
          真实调用 DeepSeek
        </label>
      </div>

      <textarea
        className="openclawTextarea"
        value={rawExport}
        onChange={(e) => setRawExport(e.target.value)}
        placeholder="粘贴 OpenClaw 导出的 CSV / JSON / 评论文本"
      />

      <div className="openclawButtonRow">
        <button disabled={!!busy} onClick={() => runAction('comment-adapter')}>
          评论线索评分
        </button>
        <button disabled={!!busy} onClick={() => runAction('comment-llm')}>
          DeepSeek 增强评论
        </button>
        <button disabled={!!busy} onClick={() => runAction('content-intel')}>
          同行内容拆解
        </button>
        <button disabled={!!busy} onClick={() => runAction('content-llm')}>
          DeepSeek 增强选题
        </button>
        <button disabled={!!busy} onClick={() => runAction('timeline-plan')}>
          一键转 Timeline
        </button>
      </div>

      {realDeepSeek && (
        <div className="openclawWarning">
          已开启真实 DeepSeek。为了省余额，前端默认每次只增强 1 条高分内容。
        </div>
      )}

      {busy && <div className="openclawLoading">处理中：{busy}</div>}
      {error && <div className="openclawError">错误：{error}</div>}
      {result && <ResultCard result={result} />}
    </section>
  )
}
