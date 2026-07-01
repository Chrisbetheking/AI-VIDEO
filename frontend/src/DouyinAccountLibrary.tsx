import React, { useMemo, useState } from 'react'
import { apiGet, apiPost, copyJson } from './aiVideoApi'

type Category = 'competitor' | 'traffic_teaching'

type Mission = {
  id: string
  category: Category
  status: string
  targets: number
  keywords: string[]
  message: string
}

const competitorSeed = `马来西亚房产同行A,malaysia_house_a,,马来西亚房产 买房 投资 吉隆坡,马来西亚买房|吉隆坡房产|海外房产投资,采集器后续替换成真实账号
海外置业同行B,oversea_property_b,,海外置业 第二家园 子女教育,海外置业|第二家园|子女教育,采集器后续替换成真实账号
吉隆坡公寓同行C,kl_condo_c,,吉隆坡公寓 投资 出租,吉隆坡公寓|投资出租|租金,采集器后续替换成真实账号
马来西亚第二家园同行D,mm2h_agent_d,,第二家园 子女教育 养老资产配置,第二家园|子女教育|养老,采集器后续替换成真实账号
海外房产避坑同行E,oversea_risk_e,,海外买房避坑 开发商 交付风险,海外买房避坑|开发商|交付,采集器后续替换成真实账号`

const trafficSeed = `短视频起号教学A,traffic_start_a,,短视频起号 爆款标题 评论区转化,短视频起号|爆款标题|评论区转化,学习结构不照搬
房产获客教学B,traffic_lead_b,,房产获客 私域承接 直播转化,房产获客|私域承接|直播转化,学习转化链路
抖音运营教学C,traffic_ops_c,,抖音运营 选题 复盘 数据分析,抖音运营|选题复盘|数据分析,学习方法论
评论区成交教学D,comment_convert_d,,评论区成交 私信筛选 线索承接,评论区成交|私信筛选|线索承接,学习承接逻辑
直播转化教学E,live_convert_e,,直播间转化 短视频引流 留资,直播转化|短视频引流|留资,学习打法`

function parseBulk(text: string, category: Category): any[] {
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
        source: 'douyin_auto_collect_target',
        metrics: { followers: 0, avg_likes: 0, avg_comments: 0, avg_collects: 0 },
      }
    })
}

function missionId() {
  return `douyin_collect_${Date.now().toString(36)}_${Math.random().toString(16).slice(2, 8)}`
}

export default function DouyinAccountLibrary() {
  const [category, setCategory] = useState<Category>('competitor')
  const [bulkText, setBulkText] = useState(competitorSeed)
  const [market, setMarket] = useState('马来西亚')
  const [keywordText, setKeywordText] = useState('马来西亚买房,吉隆坡房产,海外房产投资,第二家园,海外买房避坑')
  const [maxVideos, setMaxVideos] = useState(50)
  const [maxComments, setMaxComments] = useState(500)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [accounts, setAccounts] = useState<any[]>([])
  const [missions, setMissions] = useState<Mission[]>([])
  const [result, setResult] = useState<any>(null)

  const targetAccounts = useMemo(() => parseBulk(bulkText, category), [bulkText, category])
  const keywords = useMemo(() => keywordText.split(/[,，、\s]+/).map((x) => x.trim()).filter(Boolean), [keywordText])

  function switchCategory(next: Category) {
    setCategory(next)
    setBulkText(next === 'competitor' ? competitorSeed : trafficSeed)
  }

  async function refresh() {
    setBusy('刷新账号库')
    setError('')
    try {
      const data = await apiGet(`/api/collector/douyin/accounts/list?category=${category}&min_score=0&limit=200`)
      setAccounts(data.accounts || [])
      setResult(data)
    } catch (e: any) {
      setError(e?.message || String(e))
    } finally {
      setBusy('')
    }
  }

  async function saveTargets() {
    setBusy('保存采集目标')
    setError('')
    try {
      const data = await apiPost('/api/collector/douyin/accounts/bulk-upsert', { accounts: targetAccounts })
      setResult(data)
      await refresh()
    } catch (e: any) {
      setError(e?.message || String(e))
    } finally {
      setBusy('')
    }
  }

  async function createCollectMission() {
    setBusy('下发采集任务')
    setError('')
    try {
      let seed: any = null
      try {
        seed = await apiGet(`/api/collector/douyin/accounts/seed-targets?market=${encodeURIComponent(market)}`)
      } catch {}

      const saved = await apiPost('/api/collector/douyin/accounts/bulk-upsert', { accounts: targetAccounts })
      const mission: Mission = {
        id: missionId(),
        category,
        status: '等待 OpenClaw / 采集器领取并回传',
        targets: targetAccounts.length,
        keywords,
        message:
          category === 'competitor'
            ? `已下发同行采集任务：${targetAccounts.length} 个账号目标，关键词 ${keywords.length} 个，建议抓 ${maxVideos} 条视频 / ${maxComments} 条评论。`
            : `已下发流量教学采集任务：${targetAccounts.length} 个教学目标，学习标题/开头/转化结构，不复制内容。`,
      }
      setMissions((old) => [mission, ...old].slice(0, 12))
      setResult({ ok: true, provider: 'frontend_douyin_collect_mission_v1', mission, saved, seed })
    } catch (e: any) {
      setError(e?.message || String(e))
    } finally {
      setBusy('')
    }
  }

  async function benchmarkOrLearn() {
    setBusy(category === 'competitor' ? '筛选高分同行' : '学习流量打法')
    setError('')
    try {
      const data =
        category === 'competitor'
          ? await apiPost('/api/collector/douyin/accounts/benchmark-competitors', { min_score: 0, limit: 50 })
          : await apiPost('/api/collector/douyin/accounts/learn-traffic', { dry_run: true, min_score: 0, limit: 50 })
      setResult(data)
    } catch (e: any) {
      setError(e?.message || String(e))
    } finally {
      setBusy('')
    }
  }

  return (
    <section className="workspacePanel">
      <div className="panelHero redHero">
        <div>
          <p>DOUYIN AUTO COLLECTOR</p>
          <h2>抖音自动采集任务中心</h2>
          <span>这里不是假账号展示页，而是给 OpenClaw / 采集器下发任务：找同行、找教学号、抓视频、抓评论、回传后自动评分。</span>
        </div>
        <b>主平台：抖音</b>
      </div>

      <div className="tabRow">
        <button className={category === 'competitor' ? 'active red' : ''} onClick={() => switchCategory('competitor')}>
          同行采集任务
        </button>
        <button className={category === 'traffic_teaching' ? 'active purple' : ''} onClick={() => switchCategory('traffic_teaching')}>
          流量教学采集任务
        </button>
      </div>

      <div className="inputGrid four">
        <label>
          市场
          <input value={market} onChange={(e) => setMarket(e.target.value)} />
        </label>
        <label>
          本轮视频数
          <input type="number" value={maxVideos} onChange={(e) => setMaxVideos(Number(e.target.value || 50))} />
        </label>
        <label>
          本轮评论数
          <input type="number" value={maxComments} onChange={(e) => setMaxComments(Number(e.target.value || 500))} />
        </label>
        <label>
          当前模式
          <input readOnly value={category === 'competitor' ? '同行对标' : '学习流量打法'} />
        </label>
      </div>

      <label className="stackLabel">
        自动采集关键词
        <input value={keywordText} onChange={(e) => setKeywordText(e.target.value)} />
      </label>

      <label className="stackLabel">
        账号/目标池，采集器后面会用真实账号替换这些种子
        <textarea value={bulkText} onChange={(e) => setBulkText(e.target.value)} />
      </label>

      <div className="buttonRow">
        <button onClick={createCollectMission} disabled={!!busy}>下发自动采集任务</button>
        <button className="soft" onClick={saveTargets} disabled={!!busy}>只保存目标池</button>
        <button className={category === 'competitor' ? 'red' : 'purple'} onClick={benchmarkOrLearn} disabled={!!busy}>
          {category === 'competitor' ? '高分同行作为对标基础' : '学习流量教学方法论'}
        </button>
        <button className="ghost" onClick={refresh} disabled={!!busy}>刷新回传结果</button>
      </div>

      {busy && <div className="productNotice">处理中：{busy}</div>}
      {error && <div className="productError">错误：{error}</div>}

      <div className="statusBoard">
        <div className="statusTile"><b>{missions.length}</b><span>已下发任务</span></div>
        <div className="statusTile"><b>{targetAccounts.length}</b><span>账号目标</span></div>
        <div className="statusTile"><b>{keywords.length}</b><span>关键词</span></div>
        <div className="statusTile"><b>{accounts.length}</b><span>已回传入库</span></div>
      </div>

      <div className="productCardGrid">
        {missions.map((m) => (
          <div className="productCard" key={m.id}>
            <h3>{m.category === 'competitor' ? '同行采集' : '流量学习'} / {m.id}</h3>
            <p>{m.message}</p>
            <div className="productTagRow">
              <span>{m.status}</span>
              {m.keywords.slice(0, 6).map((k) => <span className="productTag orange" key={k}>{k}</span>)}
            </div>
          </div>
        ))}

        {accounts.slice(0, 12).map((acc) => (
          <div className="productCard" key={acc.id}>
            <h3>{acc.account_name || acc.douyin_id || '回传账号'} / {acc.score}</h3>
            <p>{acc.category === 'competitor' ? '同行账号' : '流量教学账号'} / {acc.niche || '待采集器补全'}</p>
            <p>抖音号：{acc.douyin_id || '-'}</p>
            <div className="productTagRow">
              {(acc.tags || []).map((tag: string) => <span key={tag}>{tag}</span>)}
              {(acc.keywords || []).slice(0, 5).map((tag: string) => <span key={tag} className="productTag orange">{tag}</span>)}
            </div>
          </div>
        ))}
      </div>

      {result?.hook_patterns && (
        <div className="productCard wide">
          <h3>流量教学学习结果</h3>
          <p>{result.summary}</p>
          <div className="productGrid2">
            <div><b>Hook 结构</b><ul>{result.hook_patterns.map((x: string) => <li key={x}>{x}</li>)}</ul></div>
            <div><b>执行动作</b><ul>{result.action_items.map((x: string) => <li key={x}>{x}</li>)}</ul></div>
          </div>
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
