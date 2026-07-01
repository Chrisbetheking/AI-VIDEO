import React, { useMemo, useState } from 'react'
import { apiPost, errorText } from './aiVideoApi'

type CollectorMission = {
  id: string
  category: string
  keywords: string[]
  seedAccounts: string[]
  status: string
  createdAt: string
}

const competitorDefault = '马来西亚买房\n吉隆坡房产\n海外房产投资\n第二家园置业\n海外买房避坑'
const trafficDefault = '短视频起号\n爆款标题\n评论区转化\n房产获客\n抖音本地获客'

function lines(text: string) {
  return String(text || '').split(/\r?\n|,|，/).map((x) => x.trim()).filter(Boolean)
}

export default function DouyinAccountLibrary() {
  const [category, setCategory] = useState<'competitor' | 'traffic_teaching'>('competitor')
  const [market, setMarket] = useState('马来西亚')
  const [keywords, setKeywords] = useState(competitorDefault)
  const [seedAccounts, setSeedAccounts] = useState('')
  const [maxAccounts, setMaxAccounts] = useState(50)
  const [maxVideos, setMaxVideos] = useState(20)
  const [maxComments, setMaxComments] = useState(50)
  const [missions, setMissions] = useState<CollectorMission[]>([])
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [result, setResult] = useState<any>(null)

  const missionType = category === 'competitor' ? 'douyin_competitor_account_expand' : 'douyin_traffic_teaching_expand'
  const title = category === 'competitor' ? '同行对标自动采集' : '流量教学自动采集'
  const missionPayload = useMemo(() => ({
    platform: 'douyin',
    mission_type: missionType,
    category,
    market,
    keywords: lines(keywords),
    seed_accounts: lines(seedAccounts),
    max_accounts: Number(maxAccounts) || 50,
    max_videos_per_account: Number(maxVideos) || 20,
    max_comments_per_video: Number(maxComments) || 50,
    collector_instruction: category === 'competitor'
      ? '优先扩展房产同行账号，采集公开视频、标题、互动数据和评论区问题；高分账号作为对标基础，不复制素材和文案。'
      : '优先扩展短视频流量教学账号，采集标题结构、爆款开头、评论区转化方式和复盘方法；只学习方法论。',
  }), [category, market, keywords, seedAccounts, maxAccounts, maxVideos, maxComments, missionType])

  function switchCategory(next: 'competitor' | 'traffic_teaching') {
    setCategory(next)
    setKeywords(next === 'competitor' ? competitorDefault : trafficDefault)
    setSeedAccounts('')
    setResult(null)
    setError('')
  }

  async function createMission() {
    setBusy('mission')
    setError('')
    try {
      let data: any
      try {
        data = await apiPost('/api/collector/commands/create', {
          command_type: missionType,
          payload: missionPayload,
          source: 'frontend_douyin_automation',
        })
      } catch (firstError) {
        data = await apiPost('/api/collector/douyin/accounts/bulk-upsert', {
          accounts: lines(seedAccounts).map((name, index) => ({
            category,
            account_name: name || `${title}-${index + 1}`,
            douyin_id: '',
            niche: lines(keywords).join(' '),
            keywords: lines(keywords),
            notes: '前端下发采集目标；等待 OpenClaw/采集器替换为真实账号数据。',
            source: 'collector_mission_seed',
          })),
        })
      }
      const mission: CollectorMission = {
        id: data?.command_id || data?.id || data?.mission_id || `local_mission_${Date.now()}`,
        category,
        keywords: lines(keywords),
        seedAccounts: lines(seedAccounts),
        status: '已下发，等待 OpenClaw / 采集器领取回传',
        createdAt: new Date().toLocaleString(),
      }
      setMissions((prev) => [mission, ...prev].slice(0, 20))
      setResult(data)
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy('')
    }
  }

  return (
    <section className="uxPanel douyinCollectorPanel">
      <div className="uxHero">
        <div>
          <p className="uxEyebrow">DOUYIN AUTO COLLECTOR</p>
          <h2>抖音自动采集任务中心</h2>
          <p>这里不是手动存几个假账号，而是给 OpenClaw/采集器下发任务：自动扩展同行账号、流量教学账号、作品和评论区。</p>
        </div>
        <span className="uxRedBadge">主平台：抖音</span>
      </div>

      <div className="uxPresetRow">
        <button className={category === 'competitor' ? 'active red' : ''} onClick={() => switchCategory('competitor')}>同行对标采集</button>
        <button className={category === 'traffic_teaching' ? 'active' : ''} onClick={() => switchCategory('traffic_teaching')}>流量教学采集</button>
      </div>

      <div className="uxGrid four">
        <label>市场<input value={market} onChange={(e) => setMarket(e.target.value)} /></label>
        <label>账号上限<input type="number" value={maxAccounts} onChange={(e) => setMaxAccounts(Number(e.target.value || 50))} /></label>
        <label>每账号作品数<input type="number" value={maxVideos} onChange={(e) => setMaxVideos(Number(e.target.value || 20))} /></label>
        <label>每作品评论数<input type="number" value={maxComments} onChange={(e) => setMaxComments(Number(e.target.value || 50))} /></label>
      </div>

      <div className="uxTwoCol">
        <label className="uxCard">关键词池<textarea value={keywords} onChange={(e) => setKeywords(e.target.value)} /></label>
        <label className="uxCard">种子账号 / 抖音主页链接<textarea value={seedAccounts} onChange={(e) => setSeedAccounts(e.target.value)} placeholder="可空。采集器会先按关键词扩展账号；有已知同行号再填这里。" /></label>
      </div>

      <div className="uxNotice">
        {category === 'competitor'
          ? '同行账号：采集作品结构、标题、评论区需求和转化路径；高分账号作为对标基础，不复制素材。'
          : '流量教学账号：采集起号、爆款、评论区转化和复盘方法；只学习方法论，反哺我们的内容。'}
      </div>

      <div className="uxButtonRow">
        <button onClick={createMission} disabled={!!busy}>{busy ? '下发中...' : '下发自动采集任务'}</button>
      </div>

      {error && <div className="uxError">{error}</div>}

      <div className="uxStatGrid">
        <div><b>{missions.length}</b><span>已下发任务</span></div>
        <div><b>{lines(keywords).length}</b><span>关键词目标</span></div>
        <div><b>{lines(seedAccounts).length}</b><span>种子账号</span></div>
        <div><b>OpenClaw</b><span>等待采集器回传</span></div>
      </div>

      {missions.length > 0 && (
        <div className="uxCard">
          <h3>最近采集任务</h3>
          {missions.map((m) => (
            <div className="uxSegment" key={m.id}>
              <b>{m.id}</b>
              <p>{m.status}</p>
              <em>{m.category === 'competitor' ? '同行对标' : '流量教学'}｜{m.keywords.join('、')}</em>
              <span>{m.createdAt}</span>
            </div>
          ))}
        </div>
      )}

      {result && <pre className="uxJson">{JSON.stringify(result, null, 2)}</pre>}
    </section>
  )
}
