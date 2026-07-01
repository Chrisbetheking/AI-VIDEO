import React, { useMemo, useState } from 'react'
import { apiGet, apiPost, safeJson } from './aiVideoApi'

type TargetPool = 'competitor' | 'traffic_teaching'

type TargetRow = {
  category: TargetPool
  account_name: string
  douyin_id?: string
  profile_url?: string
  niche?: string
  keywords?: string[]
  notes?: string
  source?: string
  metrics?: Record<string, number>
}

const competitorSeed = `马来西亚房产同行A,malaysia_house_a,,马来西亚房产 买房 投资 吉隆坡,马来西亚买房|吉隆坡房产|海外房产投资,采集器后续替换成真实账号
海外置业同行B,oversea_property_b,,海外置业 第二家园 子女教育,海外置业|第二家园|子女教育,采集器后续替换成真实账号
吉隆坡公寓同行C,kl_condo_c,,吉隆坡公寓 投资 出租,吉隆坡公寓|投资出租|租金,采集器后续替换成真实账号`

const trafficSeed = `短视频流量教学A,traffic_teacher_a,,短视频起号 爆款标题 评论区转化,起号|爆款标题|评论区转化,学习结构不抄内容
房产短视频教学B,realestate_content_b,,房产短视频 口播 留资,房产获客|口播脚本|私域承接,学习打法不抄文案
直播转化教学C,live_convert_c,,直播转化 私信成交,直播转化|私信筛选|留资路径,学习转化链路`

function parseTargetText(text: string, category: TargetPool): TargetRow[] {
  const raw = text.trim()
  if (!raw) return []

  try {
    const parsed = JSON.parse(raw)
    const list = Array.isArray(parsed) ? parsed : parsed.accounts || parsed.targets || []
    if (Array.isArray(list)) return list.map((x: any) => ({ ...x, category: x.category || category, source: x.source || 'frontend_target_pool' }))
  } catch {}

  return raw.split('\n').map((line) => line.trim()).filter(Boolean).map((line) => {
    const parts = line.split(',').map((x) => x.trim())
    const keywords = parts[4] ? parts[4].split(/[|，、\s]+/).filter(Boolean) : []
    return {
      category,
      account_name: parts[0] || '待采集账号',
      douyin_id: parts[1] || '',
      profile_url: parts[2] || '',
      niche: parts[3] || '',
      keywords,
      notes: parts[5] || '',
      source: 'frontend_target_pool',
      metrics: {
        followers: 0,
        avg_likes: 0,
        avg_comments: 0,
        avg_collects: 0,
      },
    }
  })
}

function Stat({ value, label }: { value: string | number; label: string }) {
  return <div className="workspaceStat"><b>{value}</b><span>{label}</span></div>
}

export default function DouyinAccountLibrary() {
  const [pool, setPool] = useState<TargetPool>('competitor')
  const [targetText, setTargetText] = useState(competitorSeed)
  const [minScore, setMinScore] = useState(40)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [result, setResult] = useState<any>(null)
  const [accounts, setAccounts] = useState<any[]>([])

  const parsedTargets = useMemo(() => parseTargetText(targetText, pool), [targetText, pool])
  const poolTitle = pool === 'competitor' ? '同行目标池' : '流量教学目标池'

  function switchPool(next: TargetPool) {
    setPool(next)
    setResult(null)
    setError('')
    setTargetText(next === 'competitor' ? competitorSeed : trafficSeed)
  }

  async function run(name: string, fn: () => Promise<any>) {
    setBusy(name)
    setError('')
    try {
      const data = await fn()
      setResult(data)
      return data
    } catch (e: any) {
      setError(e?.message || String(e))
      return null
    } finally {
      setBusy('')
    }
  }

  async function saveTargets() {
    const data = await run('保存目标池', () => apiPost('/api/collector/douyin/accounts/bulk-upsert', { accounts: parsedTargets }))
    if (data) refreshList()
  }

  async function refreshList() {
    const data = await run('刷新账号库', () => apiGet(`/api/collector/douyin/accounts/list?category=${pool}&min_score=${minScore}&limit=80`))
    if (data?.accounts) setAccounts(data.accounts)
  }

  async function makeCollectionTargets() {
    const data = await run('生成采集目标', () => apiGet('/api/collector/douyin/accounts/seed-targets?market=马来西亚'))
    if (data?.targets) {
      const keywords = pool === 'competitor' ? data.targets.competitor_keywords : data.targets.traffic_teaching_keywords
      const lines = (keywords || []).map((k: string, i: number) => `${pool === 'competitor' ? '待采集同行' : '待采集流量教学'}${i + 1},,,${k},${k}|抖音|评论区,OpenClaw/采集器按关键词扩展真实账号`)
      setTargetText(lines.join('\n'))
    }
  }

  async function benchmarkCompetitors() {
    await run('高分同行对标', () => apiPost('/api/collector/douyin/accounts/benchmark-competitors', { min_score: minScore, limit: 30 }))
  }

  async function learnTraffic() {
    await run('学习流量方法论', () => apiPost('/api/collector/douyin/accounts/learn-traffic', { dry_run: true, min_score: minScore, limit: 30 }))
  }

  return (
    <section className="workspacePanel douyinPanel">
      <div className="panelHero compact">
        <div>
          <p>DOUYIN ACCOUNT TARGET POOL</p>
          <h3>抖音账号目标池</h3>
          <span>这里不是放一个假账号，而是给 OpenClaw/采集器下发目标：同行负责对标，流量教学负责学习方法论。</span>
        </div>
        <em>主平台：抖音</em>
      </div>

      <div className="workspaceTabs">
        <button className={pool === 'competitor' ? 'active red' : ''} onClick={() => switchPool('competitor')}>同行目标池</button>
        <button className={pool === 'traffic_teaching' ? 'active dark' : ''} onClick={() => switchPool('traffic_teaching')}>流量教学目标池</button>
        <button onClick={makeCollectionTargets}>生成采集目标</button>
      </div>

      <div className="workspaceFormGrid three">
        <label>当前池<input value={poolTitle} readOnly /></label>
        <label>最低分<input type="number" value={minScore} onChange={(e) => setMinScore(Number(e.target.value || 0))} /></label>
        <label>目标数量<input value={`${parsedTargets.length} 条待保存`} readOnly /></label>
      </div>

      <textarea className="workspaceTextarea medium" value={targetText} onChange={(e) => setTargetText(e.target.value)} />

      <div className="workspaceActions">
        <button onClick={saveTargets}>保存到{poolTitle}</button>
        <button className="red" onClick={benchmarkCompetitors}>高分同行作为对标基础</button>
        <button className="purple" onClick={learnTraffic}>学习流量教学方法论</button>
        <button className="ghost" onClick={refreshList}>刷新列表</button>
      </div>

      {busy && <div className="workspaceNotice">处理中：{busy}</div>}
      {error && <div className="workspaceError">错误：{error}</div>}

      <div className="workspaceStats">
        <Stat value={accounts.length} label="已入库账号" />
        <Stat value={accounts.filter((x) => Number(x.score || 0) >= 60).length} label="高分账号" />
        <Stat value={pool === 'competitor' ? '对标' : '学习'} label="当前动作" />
        <Stat value="OpenClaw" label="后续采集器回传" />
      </div>

      <div className="accountCards">
        {accounts.slice(0, 12).map((acc) => (
          <article key={acc.id || acc.account_name} className="accountCard">
            <b>{acc.account_name || acc.douyin_id || '待采集账号'}</b>
            <span>{acc.score || 0}</span>
            <p>{acc.category === 'competitor' ? '同行账号' : '流量教学账号'} / {acc.niche || '等待采集器补齐领域'}</p>
            <small>{(acc.keywords || []).join('、') || '关键词待补充'}</small>
          </article>
        ))}
      </div>

      {result?.benchmarks && (
        <div className="resultBoard">
          <h4>高分同行对标动作</h4>
          {result.benchmarks.map((x: any) => <p key={x.account_id}><b>{x.account_name}</b>：{x.our_action}</p>)}
        </div>
      )}

      {result?.hook_patterns && (
        <div className="resultBoard">
          <h4>流量教学学习结果</h4>
          <p>{result.summary}</p>
          {(result.hook_patterns || []).map((x: string) => <p key={x}>• {x}</p>)}
        </div>
      )}

      {result && <details className="workspaceJson"><summary>完整 JSON</summary><pre>{safeJson(result)}</pre></details>}
    </section>
  )
}
