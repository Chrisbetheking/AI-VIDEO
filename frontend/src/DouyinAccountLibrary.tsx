import React, { useMemo, useState } from 'react'
import { apiGet, apiPost, copyJson, getApiToken, saveApiToken } from './aiVideoApi'
import './product-ux-fixes.css'

type Category = 'competitor' | 'traffic_teaching'

const competitorSeed = [
  '马来西亚房产同行-待采集,douyin_target_001,,马来西亚房产 买房 投资,马来西亚买房|吉隆坡房产|海外房产投资,采集器根据关键词替换为真实账号',
  '吉隆坡公寓同行-待采集,douyin_target_002,,吉隆坡公寓 租金 转手,吉隆坡公寓|租金回报|海外置业,采集器根据关键词替换为真实账号',
  '海外置业顾问-待采集,douyin_target_003,,海外置业 预算 贷款,海外买房|贷款|首付,采集器根据关键词替换为真实账号',
  '第二家园同行-待采集,douyin_target_004,,马来西亚第二家园 教育 养老,第二家园|子女教育|养老度假,采集器根据关键词替换为真实账号',
  '海外资产配置同行-待采集,douyin_target_005,,资产配置 海外生活 企业主,资产配置|海外生活|企业主,采集器根据关键词替换为真实账号',
].join('\n')

const trafficSeed = [
  '短视频起号教学-待采集,douyin_traffic_001,,短视频起号 爆款标题,短视频起号|爆款标题|抖音运营,学习标题结构和开头钩子',
  '评论区转化教学-待采集,douyin_traffic_002,,评论区转化 私域承接,评论区转化|私域|获客,学习评论区承接方法',
  '本地获客教学-待采集,douyin_traffic_003,,本地获客 短视频成交,本地获客|同城流量|私信转化,学习获客漏斗',
  '口播脚本教学-待采集,douyin_traffic_004,,口播脚本 开头完播,口播脚本|完播率|停留,学习脚本节奏',
  '直播转化教学-待采集,douyin_traffic_005,,直播转化 留资 私域,直播转化|留资|微信承接,学习承接链路',
].join('\n')

function parseBulk(text: string, category: Category): any[] {
  const raw = text.trim()
  if (!raw) return []
  try {
    const parsed = JSON.parse(raw)
    const arr = Array.isArray(parsed) ? parsed : parsed.accounts
    if (Array.isArray(arr)) return arr.map((x: any) => ({ ...x, category: x.category || category }))
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
      source: 'frontend_bulk_seed_or_collector',
    }
  })
}

function TokenInline() {
  const [token, setToken] = useState(getApiToken())
  return (
    <div className="tokenInline">
      <label className="productField">
        API Token（不再弹窗，留空则只看页面，受保护按钮会返回 401）
        <input className="productInput" value={token} onChange={(e) => setToken(e.target.value)} placeholder="粘贴一次即可，也可以留空" />
        <small>之前那个浏览器弹窗已经取消，改成这里手动保存。</small>
      </label>
      <button className="productBtn secondary" onClick={() => saveApiToken(token)}>保存 Token</button>
    </div>
  )
}

export default function DouyinAccountLibrary() {
  const [category, setCategory] = useState<Category>('competitor')
  const [bulkText, setBulkText] = useState(competitorSeed)
  const [minScore, setMinScore] = useState(40)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [accounts, setAccounts] = useState<any[]>([])
  const [result, setResult] = useState<any>(null)

  const title = useMemo(() => category === 'competitor' ? '同行账号库' : '流量教学账号库', [category])

  function switchCategory(next: Category) {
    setCategory(next)
    setBulkText(next === 'competitor' ? competitorSeed : trafficSeed)
    setResult(null)
    setAccounts([])
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

  async function refresh() {
    const data = await run('刷新账号库', () => apiGet(`/api/collector/douyin/accounts/list?category=${category}&min_score=${minScore}&limit=100`))
    if (data) setAccounts(data.accounts || [])
  }

  async function saveBulk() {
    await run('保存账号', async () => {
      const data = await apiPost('/api/collector/douyin/accounts/bulk-upsert', { accounts: parseBulk(bulkText, category) })
      const list = await apiGet(`/api/collector/douyin/accounts/list?category=${category}&min_score=0&limit=100`)
      setAccounts(list.accounts || [])
      return data
    })
  }

  async function benchmarkCompetitors() {
    await run('筛选同行', () => apiPost('/api/collector/douyin/accounts/benchmark-competitors', { min_score: minScore, limit: 30 }))
  }

  async function learnTraffic() {
    await run('学习流量打法', () => apiPost('/api/collector/douyin/accounts/learn-traffic', { dry_run: true, min_score: minScore, limit: 30 }))
  }

  async function seedTargets() {
    await run('生成采集目标', () => apiGet('/api/collector/douyin/accounts/seed-targets?market=马来西亚'))
  }

  const competitorCount = accounts.filter((x) => x.category === 'competitor').length
  const trafficCount = accounts.filter((x) => x.category === 'traffic_teaching').length
  const highScoreCount = accounts.filter((x) => Number(x.score || 0) >= 60).length

  return (
    <section id="douyin-account-library" className="productPatchPanel douyinAccountLibrary">
      <div className="productPatchHeader">
        <div>
          <p className="productEyebrow">DOUYIN ACCOUNT LIBRARY</p>
          <h2>抖音账号库：同行对标 / 流量教学分开管理</h2>
          <p>不要再只放一个示例号。这里先放采集目标池，后续采集器回传真账号；同行高分号做对标基础，流量教学号只学打法。</p>
        </div>
        <div className="productBadge">主平台：抖音</div>
      </div>

      <TokenInline />

      <div className="statusBoard">
        <div className="statusTile"><b>{competitorCount}</b><span>同行账号</span></div>
        <div className="statusTile"><b>{trafficCount}</b><span>流量教学账号</span></div>
        <div className="statusTile"><b>{highScoreCount}</b><span>可对标高分账号</span></div>
        <div className="statusTile"><b>{minScore}</b><span>当前筛选分</span></div>
      </div>

      <div className="productButtonRow">
        <button className={category === 'competitor' ? 'red' : 'secondary'} onClick={() => switchCategory('competitor')}>同行账号库</button>
        <button className={category === 'traffic_teaching' ? 'purple' : 'secondary'} onClick={() => switchCategory('traffic_teaching')}>流量教学账号库</button>
        <button className="secondary" onClick={refresh} disabled={!!busy}>刷新</button>
        <button className="green" onClick={seedTargets} disabled={!!busy}>生成采集目标</button>
      </div>

      <div className="productGrid2">
        <label className="productField">最低分<input className="productInput" type="number" value={minScore} onChange={(e) => setMinScore(Number(e.target.value || 0))} /></label>
        <label className="productField">当前分类<input className="productInput" value={title} readOnly /></label>
      </div>

      <label className="productField" style={{ marginTop: 14 }}>
        批量导入/采集目标池（账号名, 抖音号, 主页链接, 领域, 关键词, 备注）
        <textarea className="productTextarea" value={bulkText} onChange={(e) => setBulkText(e.target.value)} />
      </label>

      <div className="productButtonRow">
        <button onClick={saveBulk} disabled={!!busy}>保存到{title}</button>
        <button className="red" onClick={benchmarkCompetitors} disabled={!!busy}>高分同行作为对标基础</button>
        <button className="purple" onClick={learnTraffic} disabled={!!busy}>学习流量教学方法论</button>
      </div>

      {busy && <div className="productNotice">处理中：{busy}</div>}
      {error && <div className="productError">错误：{error}</div>}

      <div className="productCardGrid">
        {accounts.map((acc) => (
          <div className="productCard" key={acc.id}>
            <h3>{acc.account_name || acc.douyin_id || '未命名账号'} <span className="productTag red">{acc.score}</span></h3>
            <p>{acc.category === 'competitor' ? '同行账号' : '流量教学账号'} / {acc.niche || '未标注领域'}</p>
            <p>抖音号：{acc.douyin_id || '-'}</p>
            <p>关键词：{(acc.keywords || []).join('、') || '-'}</p>
            <div className="productTagRow">{(acc.tags || []).map((tag: string) => <span key={tag}>{tag}</span>)}</div>
          </div>
        ))}
      </div>

      {result?.hook_patterns && <div className="productCard" style={{ marginTop: 14 }}>
        <h3>流量教学学习结果</h3>
        <p>{result.summary}</p>
        <div className="productGrid2">
          <div><b>Hook 结构</b><ul>{result.hook_patterns.map((x: string) => <li key={x}>{x}</li>)}</ul></div>
          <div><b>执行动作</b><ul>{result.action_items.map((x: string) => <li key={x}>{x}</li>)}</ul></div>
        </div>
      </div>}

      {result?.benchmarks && <div className="productCard" style={{ marginTop: 14 }}>
        <h3>高分同行对标结果</h3>
        {result.benchmarks.map((x: any) => <p key={x.account_id}><b>{x.account_name}</b> / score {x.score}：{x.our_action}</p>)}
      </div>}

      {result && <details className="productJsonBox"><summary>完整 JSON</summary><button className="productBtn secondary" onClick={() => copyJson(result)}>复制 JSON</button><pre>{JSON.stringify(result, null, 2)}</pre></details>}
    </section>
  )
}
