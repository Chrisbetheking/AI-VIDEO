import React, { useEffect, useMemo, useState } from 'react'
import { apiGet, apiPost, copyJson, getApiToken, saveApiToken } from './aiVideoApi'

type Category = 'competitor' | 'traffic_teaching'

const competitorSeed = `马来西亚房产同行A,malaysia_house_a,,马来西亚房产 买房 投资 吉隆坡,马来西亚买房|吉隆坡房产|海外房产投资,采集器后续替换成真实账号
海外置业同行B,oversea_property_b,,海外置业 第二家园 子女教育,海外置业|第二家园|子女教育,采集器后续替换成真实账号
吉隆坡公寓同行C,kl_condo_c,,吉隆坡公寓 投资 出租,吉隆坡公寓|投资出租|租金,采集器后续替换成真实账号`

const trafficSeed = `短视频起号教学A,traffic_start_a,,短视频起号 爆款标题 评论区转化,短视频起号|爆款标题|评论区转化,学习结构不照搬
房产获客教学B,traffic_lead_b,,房产获客 私域承接 直播转化,房产获客|私域承接|直播转化,学习转化链路
抖音运营教学C,traffic_ops_c,,抖音运营 选题 复盘 数据分析,抖音运营|选题复盘|数据分析,学习方法论`

function TokenInline() {
  const [token, setToken] = useState(getApiToken())
  const [saved, setSaved] = useState(false)
  return (
    <div className="tokenInline">
      <label className="productField">
        AI-VIDEO API Token
        <input className="productInput" value={token} onChange={(e) => { setToken(e.target.value); setSaved(false) }} placeholder="粘贴管理 Token" />
        <small>不会再弹浏览器输入框。</small>
      </label>
      <button className="productBtn" onClick={() => { saveApiToken(token); setSaved(true) }}>保存 Token</button>
      <button className="productBtn secondary" onClick={() => { saveApiToken(''); setToken(''); setSaved(false) }}>清空</button>
      {saved && <div className="productNotice">Token 已保存</div>}
    </div>
  )
}

function parseBulk(text: string, category: Category): any[] {
  const raw = text.trim()
  if (!raw) return []
  try {
    const parsed = JSON.parse(raw)
    if (Array.isArray(parsed)) return parsed.map((x) => ({ ...x, category: x.category || category }))
    if (Array.isArray(parsed.accounts)) return parsed.accounts.map((x: any) => ({ ...x, category: x.category || category }))
  } catch {}
  return raw.split('\n').map((line) => line.trim()).filter(Boolean).map((line) => {
    const parts = line.split(',').map((x) => x.trim())
    return {
      category,
      account_name: parts[0] || '',
      douyin_id: parts[1] || '',
      profile_url: parts[2] || '',
      niche: parts[3] || '',
      keywords: parts[4] ? parts[4].split(/[|，、\s]+/).filter(Boolean) : [],
      notes: parts[5] || '',
      source: 'frontend_target_pool',
      metrics: { followers: 0, avg_likes: 0, avg_comments: 0, avg_collects: 0 },
    }
  })
}

export default function DouyinAccountLibrary() {
  const [category, setCategory] = useState<Category>('competitor')
  const [bulkText, setBulkText] = useState(competitorSeed)
  const [minScore, setMinScore] = useState(0)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [accounts, setAccounts] = useState<any[]>([])
  const [result, setResult] = useState<any>(null)

  const title = useMemo(() => category === 'competitor' ? '同行账号目标池' : '流量教学目标池', [category])
  const description = category === 'competitor'
    ? '同行号负责对标：评分高的账号用于拆标题、拆评论、拆转化路径，生成我们自己的内容。'
    : '流量教学号负责学习：起号、标题、开头、评论区转化、私域承接，只学习结构不复制内容。'

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
      const data = await apiPost('/api/collector/douyin/accounts/bulk-upsert', { accounts: parseBulk(bulkText, category) })
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
      const data = await apiPost('/api/collector/douyin/accounts/learn-traffic', { dry_run: true, min_score: Math.max(0, minScore), limit: 30 })
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
      const data = await apiPost('/api/collector/douyin/accounts/benchmark-competitors', { min_score: Math.max(0, minScore), limit: 30 })
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

  function switchCategory(next: Category) {
    setCategory(next)
    setBulkText(next === 'competitor' ? competitorSeed : trafficSeed)
  }

  useEffect(() => { refresh().catch(() => {}) }, [category])

  return (
    <section className="productPatchPanel douyinAccountLibrary">
      <div className="productPatchHeader">
        <div>
          <p className="productEyebrow">DOUYIN ACCOUNT LIBRARY</p>
          <h2>抖音账号目标池</h2>
          <p>{description}</p>
        </div>
        <div className="productBadge red">主平台：抖音</div>
      </div>

      <TokenInline />

      <div className="productButtonRow">
        <button className={category === 'competitor' ? 'red' : 'secondary'} onClick={() => switchCategory('competitor')}>同行目标池</button>
        <button className={category === 'traffic_teaching' ? 'purple' : 'secondary'} onClick={() => switchCategory('traffic_teaching')}>流量教学目标池</button>
        <button onClick={refresh} disabled={!!busy}>刷新</button>
        <button className="green" onClick={seedTargets} disabled={!!busy}>生成采集目标</button>
      </div>

      <div className="productGrid3">
        <label className="productField">当前池<input className="productInput" value={title} readOnly /></label>
        <label className="productField">最低分<input className="productInput" type="number" value={minScore} onChange={(e) => setMinScore(Number(e.target.value || 0))} /></label>
        <label className="productField">目标数量<input className="productInput" value={`${parseBulk(bulkText, category).length} 条待保存`} readOnly /></label>
      </div>

      <textarea className="productTextarea" value={bulkText} onChange={(e) => setBulkText(e.target.value)} placeholder="账号名,抖音号,主页链接,领域,关键词用|分隔,备注" />

      <div className="productButtonRow">
        <button onClick={saveBulk} disabled={!!busy}>保存到{title}</button>
        <button className="red" onClick={benchmarkCompetitors} disabled={!!busy}>高分同行作为对标基础</button>
        <button className="purple" onClick={learnTraffic} disabled={!!busy}>学习流量教学方法论</button>
      </div>

      {busy && <div className="productNotice">处理中：{busy}</div>}
      {error && <div className="productError">错误：{error}</div>}

      <div className="statusBoard">
        <div className="statusTile"><b>{accounts.length}</b><span>账号库记录</span></div>
        <div className="statusTile"><b>{accounts.filter((x) => x.score >= 70).length}</b><span>高分账号</span></div>
        <div className="statusTile"><b>{category === 'competitor' ? '对标' : '学习'}</b><span>当前动作</span></div>
        <div className="statusTile"><b>OpenClaw</b><span>后续采集器回传</span></div>
      </div>

      <div className="productCardGrid">
        {accounts.map((acc) => (
          <div className="productCard" key={acc.id}>
            <h3>{acc.account_name || acc.douyin_id || '未命名账号'} / {acc.score}</h3>
            <p>{acc.category === 'competitor' ? '同行账号' : '流量教学账号'} / {acc.niche}</p>
            <p>抖音号：{acc.douyin_id || '-'}</p>
            <div className="productTagRow">
              {(acc.tags || []).map((tag: string) => <span key={tag}>{tag}</span>)}
              {(acc.keywords || []).slice(0, 5).map((tag: string) => <span key={tag} className="productTag orange">{tag}</span>)}
            </div>
          </div>
        ))}
      </div>

      {result?.hook_patterns && (
        <div className="productCard">
          <h3>流量教学学习结果</h3>
          <p>{result.summary}</p>
          <div className="productGrid2">
            <div><b>Hook 结构</b><ul>{result.hook_patterns.map((x: string) => <li key={x}>{x}</li>)}</ul></div>
            <div><b>执行动作</b><ul>{result.action_items.map((x: string) => <li key={x}>{x}</li>)}</ul></div>
          </div>
        </div>
      )}

      {result?.benchmarks && (
        <div className="productCard">
          <h3>高分同行对标结果</h3>
          {result.benchmarks.map((x: any) => (
            <p key={x.account_id}><b>{x.account_name}</b> / score {x.score}：{x.our_action}</p>
          ))}
        </div>
      )}

      {result && (
        <details className="productJsonBox">
          <summary>完整 JSON / 复制</summary>
          <button className="productBtn" onClick={() => copyJson(result)}>复制 JSON</button>
          <pre>{JSON.stringify(result, null, 2)}</pre>
        </details>
      )}
    </section>
  )
}
