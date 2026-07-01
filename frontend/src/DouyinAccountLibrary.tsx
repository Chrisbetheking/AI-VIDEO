import React, { useMemo, useState } from 'react'
import { tryPost } from './aiVideoApi'

type Pool = 'competitor' | 'traffic_teaching'

const defaultCompetitors = '马来西亚房产,海外置业,第二家园,吉隆坡公寓,海外房产投资,租金,转手,贷款'
const defaultTraffic = '短视频起号,爆款标题,评论区转化,私域承接,房产获客,同城获客,直播转化'

export default function DouyinAccountLibrary() {
  const [pool, setPool] = useState<Pool>('competitor')
  const [market, setMarket] = useState('马来西亚')
  const [keywords, setKeywords] = useState(defaultCompetitors)
  const [seedAccounts, setSeedAccounts] = useState('')
  const [maxAccounts, setMaxAccounts] = useState(50)
  const [maxVideos, setMaxVideos] = useState(20)
  const [maxComments, setMaxComments] = useState(80)
  const [autoDeepSeek, setAutoDeepSeek] = useState(true)
  const [autoTimeline, setAutoTimeline] = useState(true)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [result, setResult] = useState<any>(null)

  const mission = useMemo(() => {
    const keywordList = keywords.split(/[，,\n]/).map((x) => x.trim()).filter(Boolean)
    const accountList = seedAccounts.split(/[，,\n]/).map((x) => x.trim()).filter(Boolean)
    return {
      platform: 'douyin',
      mission_type: pool === 'competitor' ? 'douyin_competitor_expand' : 'douyin_traffic_teaching_expand',
      category: pool,
      market,
      keywords: keywordList,
      seed_accounts: accountList,
      max_accounts: maxAccounts,
      max_videos_per_account: maxVideos,
      max_comments_per_video: maxComments,
      run_deepseek: autoDeepSeek,
      auto_timeline: autoTimeline,
      collector_instruction:
        pool === 'competitor'
          ? '自动扩展抖音房产同行账号：采集账号、作品、评论，评分高的进入对标基础。'
          : '自动扩展抖音短视频流量教学账号：采集账号、作品、标题结构和评论区转化方法，沉淀方法论。',
    }
  }, [pool, market, keywords, seedAccounts, maxAccounts, maxVideos, maxComments, autoDeepSeek, autoTimeline])

  function switchPool(next: Pool) {
    setPool(next)
    setKeywords(next === 'competitor' ? defaultCompetitors : defaultTraffic)
  }

  async function createMission() {
    setBusy('mission')
    setError('')
    try {
      const payload = {
        command: 'douyin_auto_collect',
        command_type: 'douyin_auto_collect',
        title: pool === 'competitor' ? '抖音同行自动采集' : '抖音流量教学自动采集',
        payload: mission,
        params: mission,
        dry_run: false,
      }
      const data = await tryPost([
        '/api/collector/commands/create',
        '/api/collector/commands/enqueue',
        '/api/collector/douyin/missions/create',
        '/api/collector/missions/create',
      ], payload)
      setResult({ ...data, mission })
    } catch (err: any) {
      setResult({ ok: false, local_preview: true, message: '后端采集任务创建接口还未统一，先保留任务载荷。下一步需要后端队列适配。', mission })
      setError(err?.message || String(err))
    } finally {
      setBusy('')
    }
  }

  return (
    <section className="uxPanelCard">
      <div className="uxHeroRow">
        <div>
          <p className="uxEyebrow">DOUYIN AUTO COLLECTOR</p>
          <h2>抖音自动采集任务中心</h2>
          <p>这里不是手动维护假账号，而是给 OpenClaw / 采集器下发任务：自动扩展同行、流量教学账号、作品和评论，回传后再评分、拆结构、生成脚本。</p>
        </div>
        <span className="uxBadge">主平台：抖音</span>
      </div>

      <div className="uxButtonRow">
        <button className={pool === 'competitor' ? 'active' : ''} onClick={() => switchPool('competitor')}>同行对标采集</button>
        <button className={pool === 'traffic_teaching' ? 'active' : ''} onClick={() => switchPool('traffic_teaching')}>流量教学采集</button>
      </div>

      <div className="uxGrid4">
        <label>市场<input value={market} onChange={(e) => setMarket(e.target.value)} /></label>
        <label>目标账号上限<input type="number" value={maxAccounts} onChange={(e) => setMaxAccounts(Number(e.target.value || 50))} /></label>
        <label>每号作品上限<input type="number" value={maxVideos} onChange={(e) => setMaxVideos(Number(e.target.value || 20))} /></label>
        <label>每条评论上限<input type="number" value={maxComments} onChange={(e) => setMaxComments(Number(e.target.value || 80))} /></label>
      </div>

      <div className="uxSplit">
        <label className="uxBox">采集关键词
          <textarea value={keywords} onChange={(e) => setKeywords(e.target.value)} />
        </label>
        <label className="uxBox">种子账号 / 主页链接，可留空让采集器自动扩展
          <textarea value={seedAccounts} onChange={(e) => setSeedAccounts(e.target.value)} placeholder="抖音号、主页链接、同行名，一行一个" />
        </label>
      </div>

      <div className="uxGrid4">
        <label className="uxCheck"><input type="checkbox" checked={autoDeepSeek} onChange={(e) => setAutoDeepSeek(e.target.checked)} />回传后自动 DeepSeek 学习</label>
        <label className="uxCheck"><input type="checkbox" checked={autoTimeline} onChange={(e) => setAutoTimeline(e.target.checked)} />高分内容自动转 Timeline</label>
      </div>

      <div className="uxButtonRow">
        <button onClick={createMission} disabled={!!busy}>下发自动采集任务</button>
      </div>
      {busy && <div className="uxNotice">正在下发：{busy}</div>}
      {error && <div className="uxError">后端暂未适配完整采集队列：{error}</div>}

      <div className="uxStatsRow">
        <div className="uxStat"><b>{mission.keywords.length}</b><span>关键词</span></div>
        <div className="uxStat"><b>{maxAccounts}</b><span>目标账号上限</span></div>
        <div className="uxStat"><b>{maxVideos}</b><span>每号作品</span></div>
        <div className="uxStat"><b>{maxComments}</b><span>每条评论</span></div>
      </div>

      <div className="uxNotice">采集器应该做：搜索关键词 → 扩展账号 → 抓作品标题/数据 → 抓评论 → 回传 → 自动评分/DeepSeek/Timeline。前端不再伪造账号数量。</div>
      {result && <pre className="uxJson">{JSON.stringify(result, null, 2)}</pre>}
    </section>
  )
}
