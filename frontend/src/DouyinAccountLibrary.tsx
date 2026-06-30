import React, { useEffect, useMemo, useState } from 'react'

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

async function apiGet(path: string): Promise<JsonValue> {
  const token = getToken()
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'X-AI-Video-Token': token },
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data?.detail || data?.message || `HTTP ${res.status}`)
  return data
}

async function apiPost(path: string, body: JsonValue): Promise<JsonValue> {
  const token = getToken()
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-AI-Video-Token': token,
    },
    body: JSON.stringify(body),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data?.detail || data?.message || `HTTP ${res.status}`)
  return data
}

function parseBulk(text: string, category: string): any[] {
  const raw = text.trim()
  if (!raw) return []

  try {
    const parsed = JSON.parse(raw)
    if (Array.isArray(parsed)) return parsed.map((x) => ({ ...x, category: x.category || category }))
    if (Array.isArray(parsed.accounts)) return parsed.accounts.map((x: any) => ({ ...x, category: x.category || category }))
  } catch {}

  return raw
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const parts = line.split(',').map((x) => x.trim())
      return {
        category,
        account_name: parts[0] || '',
        douyin_id: parts[1] || '',
        profile_url: parts[2] || '',
        niche: parts[3] || '',
        keywords: parts[4] ? parts[4].split(/[|，、\s]+/).filter(Boolean) : [],
        notes: parts[5] || '',
        source: 'frontend_bulk',
      }
    })
}

function JsonBox({ data }: { data: any }) {
  if (!data) return null
  return (
    <details className="douyinJsonBox">
      <summary>完整 JSON</summary>
      <pre>{JSON.stringify(data, null, 2)}</pre>
    </details>
  )
}

export default function DouyinAccountLibrary() {
  const [category, setCategory] = useState<'competitor' | 'traffic_teaching'>('competitor')
  const [bulkText, setBulkText] = useState(
    '示例马来西亚房产同行,demo_competitor,,马来西亚房产 买房 投资,马来西亚买房|吉隆坡房产,先放示例，后面由采集器扩展真实账号'
  )
  const [minScore, setMinScore] = useState(40)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [accounts, setAccounts] = useState<any[]>([])
  const [result, setResult] = useState<any>(null)

  const title = useMemo(() => {
    return category === 'competitor' ? '同行账号库' : '流量教学账号库'
  }, [category])

  async function refresh() {
    setBusy('refresh')
    setError('')
    try {
      const data = await apiGet(`/api/collector/douyin/accounts/list?category=${category}&min_score=${minScore}&limit=100`)
      setAccounts(data.accounts || [])
      setResult(data)
    } catch (e: any) {
      setError(e?.message || String(e))
    } finally {
      setBusy('')
    }
  }

  async function saveBulk() {
    setBusy('bulk')
    setError('')
    try {
      const parsed = parseBulk(bulkText, category)
      const data = await apiPost('/api/collector/douyin/accounts/bulk-upsert', { accounts: parsed })
      setResult(data)
      await refresh()
    } catch (e: any) {
      setError(e?.message || String(e))
    } finally {
      setBusy('')
    }
  }

  async function learnTraffic() {
    setBusy('learn')
    setError('')
    try {
      const data = await apiPost('/api/collector/douyin/accounts/learn-traffic', {
        dry_run: true,
        min_score: minScore,
        limit: 30,
      })
      setResult(data)
    } catch (e: any) {
      setError(e?.message || String(e))
    } finally {
      setBusy('')
    }
  }

  async function benchmarkCompetitors() {
    setBusy('benchmark')
    setError('')
    try {
      const data = await apiPost('/api/collector/douyin/accounts/benchmark-competitors', {
        min_score: minScore,
        limit: 30,
      })
      setResult(data)
    } catch (e: any) {
      setError(e?.message || String(e))
    } finally {
      setBusy('')
    }
  }

  async function seedTargets() {
    setBusy('seed-targets')
    setError('')
    try {
      const data = await apiGet('/api/collector/douyin/accounts/seed-targets?market=马来西亚')
      setResult(data)
    } catch (e: any) {
      setError(e?.message || String(e))
    } finally {
      setBusy('')
    }
  }

  useEffect(() => {
    refresh().catch(() => {})
  }, [category])

  return (
    <>
      <nav className="douyinSideDock">
        <a href="#douyin-account-library">抖音账号库</a>
        <a href="#openclaw-workbench-root">OpenClaw 工作台</a>
      </nav>

      <section id="douyin-account-library" className="douyinAccountLibrary">
        <div className="douyinTitleRow">
          <div>
            <p className="douyinEyebrow">DOUYIN ACCOUNT LIBRARY</p>
            <h2>抖音账号库 / 同行对标 / 流量学习</h2>
            <p>
              同行账号和短视频流量教学账号分开管理：同行高分账号做对标基础，流量教学账号沉淀方法论，再反哺我们的脚本和 Timeline。
            </p>
          </div>
          <div className="douyinBadge">主平台：抖音</div>
        </div>

        <div className="douyinTabs">
          <button className={category === 'competitor' ? 'active' : ''} onClick={() => setCategory('competitor')}>
            同行账号库
          </button>
          <button className={category === 'traffic_teaching' ? 'active' : ''} onClick={() => setCategory('traffic_teaching')}>
            流量教学账号库
          </button>
        </div>

        <div className="douyinControlRow">
          <label>
            当前分类
            <input value={title} readOnly />
          </label>
          <label>
            最低分
            <input type="number" value={minScore} onChange={(e) => setMinScore(Number(e.target.value || 0))} />
          </label>
          <button onClick={refresh} disabled={!!busy}>刷新账号库</button>
          <button onClick={seedTargets} disabled={!!busy}>生成采集目标</button>
        </div>

        <textarea
          className="douyinBulkText"
          value={bulkText}
          onChange={(e) => setBulkText(e.target.value)}
          placeholder="批量导入：账号名,抖音号,主页链接,领域,关键词用|分隔,备注"
        />

        <div className="douyinButtonRow">
          <button onClick={saveBulk} disabled={!!busy}>保存到{title}</button>
          <button onClick={benchmarkCompetitors} disabled={!!busy}>筛选高分同行作为对标基础</button>
          <button onClick={learnTraffic} disabled={!!busy}>学习流量教学方法论</button>
        </div>

        {busy && <div className="douyinLoading">处理中：{busy}</div>}
        {error && <div className="douyinError">错误：{error}</div>}

        <div className="douyinAccountGrid">
          {accounts.map((acc) => (
            <div className="douyinAccountCard" key={acc.id}>
              <div className="douyinAccountTop">
                <b>{acc.account_name || acc.douyin_id || '未命名账号'}</b>
                <span>{acc.score}</span>
              </div>
              <p>{acc.category === 'competitor' ? '同行账号' : '流量教学账号'} / {acc.niche}</p>
              <p>抖音号：{acc.douyin_id || '-'}</p>
              <p>关键词：{(acc.keywords || []).join('、') || '-'}</p>
              <div className="douyinTags">
                {(acc.tags || []).map((tag: string) => <em key={tag}>{tag}</em>)}
              </div>
            </div>
          ))}
        </div>

        {result?.hook_patterns && (
          <div className="douyinLearningBox">
            <h3>流量教学学习结果</h3>
            <p>{result.summary}</p>
            <b>Hook 结构</b>
            <ul>{result.hook_patterns.map((x: string) => <li key={x}>{x}</li>)}</ul>
            <b>执行动作</b>
            <ul>{result.action_items.map((x: string) => <li key={x}>{x}</li>)}</ul>
          </div>
        )}

        {result?.benchmarks && (
          <div className="douyinLearningBox">
            <h3>高分同行对标结果</h3>
            {result.benchmarks.map((x: any) => (
              <div className="douyinBenchmark" key={x.account_id}>
                <b>{x.account_name}</b>
                <span>score {x.score}</span>
                <p>{x.our_action}</p>
              </div>
            ))}
          </div>
        )}

        <JsonBox data={result} />
      </section>
    </>
  )
}
