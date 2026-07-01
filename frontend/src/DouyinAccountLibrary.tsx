import React, { useMemo, useState } from 'react'
import { apiGet, apiPost, apiPostFirst, copyJson } from './aiVideoApi'

type Mission = { id: string; type: string; status: string; message: string; payload: any }

const competitorTargets = `马来西亚买房,吉隆坡房产,海外房产投资,第二家园,海外买房避坑,马来西亚置业
竞品账号主页链接后续由 OpenClaw 自动扩展，不要手填假账号`
const trafficTargets = `短视频起号,爆款标题,评论区转化,房产获客,直播转化,私域承接
流量教学账号由 OpenClaw 自动扩展，只学习结构，不照搬内容`

function nowId(prefix: string) {
  return `${prefix}_${Date.now().toString(36)}_${Math.random().toString(16).slice(2, 8)}`
}

function parseKeywords(text: string) {
  return text.split(/[,，、\n\s]+/).map((x) => x.trim()).filter(Boolean).filter((x) => !x.includes('链接后续') && !x.includes('自动扩展'))
}

export default function DouyinAccountLibrary() {
  const [pool, setPool] = useState<'competitor' | 'traffic'>('competitor')
  const [market, setMarket] = useState('马来西亚')
  const [platform, setPlatform] = useState('douyin')
  const [keywordsText, setKeywordsText] = useState(competitorTargets)
  const [maxAccounts, setMaxAccounts] = useState(60)
  const [maxVideos, setMaxVideos] = useState(120)
  const [maxComments, setMaxComments] = useState(1000)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [missions, setMissions] = useState<Mission[]>([])
  const [result, setResult] = useState<any>(null)

  const keywords = useMemo(() => parseKeywords(keywordsText), [keywordsText])

  function switchPool(next: 'competitor' | 'traffic') {
    setPool(next)
    setKeywordsText(next === 'competitor' ? competitorTargets : trafficTargets)
  }

  async function dispatchMission() {
    setBusy('下发 OpenClaw 自动采集任务')
    setError('')
    const payload = {
      platform,
      market,
      mission_type: pool === 'competitor' ? 'douyin_competitor_discovery' : 'douyin_traffic_teaching_discovery',
      keywords,
      max_accounts: maxAccounts,
      max_videos: maxVideos,
      max_comments: maxComments,
      run_deepseek_after_submit: true,
      auto_build_timeline: true,
      message: pool === 'competitor'
        ? `抖音同行自动采集：按 ${keywords.length} 个关键词扩展账号、作品、评论，评分高的作为对标基础。`
        : `抖音流量教学自动采集：学习起号、标题、评论区转化方法论，不复制原文。`,
      raw: { source: 'frontend_douyin_collect_center_v5' },
    }
    try {
      let data: any
      try {
        data = await apiPostFirst(['/api/collector/commands/create', '/api/collector/commands', '/api/collector/command/create'], {
          mode: 'douyin_auto_collect',
          account: keywords.join(','),
          limit: Math.min(120, maxAccounts),
          headful: true,
          dry_run: false,
          message: payload.message,
          raw: payload,
        })
      } catch (e: any) {
        // 老后端没有命令接口时先落到本地任务看板，不再假装入库数量变多。
        data = { ok: true, provider: 'frontend_local_mission_fallback', warning: e?.message || String(e), payload }
      }
      const mission: Mission = { id: data?.command_id || data?.id || nowId('douyin_mission'), type: payload.mission_type, status: '已下发，等待 OpenClaw/采集器领取回传', message: payload.message, payload: data }
      setMissions((old) => [mission, ...old].slice(0, 20))
      setResult({ ok: true, mission, backend: data })
    } catch (e: any) {
      setError(e?.message || String(e))
    } finally {
      setBusy('')
    }
  }

  async function refreshBackend() {
    setBusy('刷新采集状态')
    setError('')
    try {
      let status: any = null
      try { status = await apiGet('/api/collector/status') } catch {}
      let accounts: any = null
      try { accounts = await apiGet('/api/collector/douyin/accounts/list?limit=50') } catch {}
      setResult({ ok: true, provider: 'douyin_collect_status_view', status, accounts })
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
          <p>DOUYIN AUTO COLLECT CENTER</p>
          <h2>抖音自动采集任务中心</h2>
          <span>这里不是让你手动填账号；这里负责给 OpenClaw/采集器下发任务：搜同行、扩账号、抓作品、抓评论、回传后自动分析。</span>
        </div>
        <b>主平台：抖音</b>
      </div>

      <div className="modeSwitch">
        <button className={pool === 'competitor' ? 'active red' : ''} onClick={() => switchPool('competitor')}>同行对标采集</button>
        <button className={pool === 'traffic' ? 'active' : ''} onClick={() => switchPool('traffic')}>流量教学采集</button>
      </div>

      <div className="inputGrid five">
        <label>市场<input value={market} onChange={(e) => setMarket(e.target.value)} /></label>
        <label>平台<input value={platform} onChange={(e) => setPlatform(e.target.value)} /></label>
        <label>账号上限<input type="number" value={maxAccounts} onChange={(e) => setMaxAccounts(Number(e.target.value || 60))} /></label>
        <label>作品上限<input type="number" value={maxVideos} onChange={(e) => setMaxVideos(Number(e.target.value || 120))} /></label>
        <label>评论上限<input type="number" value={maxComments} onChange={(e) => setMaxComments(Number(e.target.value || 1000))} /></label>
      </div>

      <label className="wideLabel">自动采集关键词 / 任务目标<textarea value={keywordsText} onChange={(e) => setKeywordsText(e.target.value)} /></label>

      <div className="buttonRow">
        <button className="red" onClick={dispatchMission} disabled={!!busy}>下发自动采集任务</button>
        <button onClick={refreshBackend} disabled={!!busy}>刷新回传状态</button>
      </div>

      <div className="statusBoard">
        <div className="statusTile"><b>{missions.length}</b><span>已下发任务</span></div>
        <div className="statusTile"><b>{keywords.length}</b><span>关键词</span></div>
        <div className="statusTile"><b>{maxAccounts}</b><span>目标账号上限</span></div>
        <div className="statusTile"><b>OpenClaw</b><span>等待采集器领取</span></div>
      </div>

      {missions.length > 0 && <div className="leadPipeline">{missions.map((m) => <div className="leadCard" key={m.id}><div className="leadTop"><b>{m.id}</b><span>{m.status}</span></div><p>{m.message}</p><p className="warnBox">采集器回传后，数量和线索才会增加；前端不再造假账号。</p></div>)}</div>}
      {busy && <div className="productNotice">处理中：{busy}</div>}
      {error && <div className="productError">错误：{error}</div>}
      {result && <details className="productJsonBox"><summary>任务 / 回传 JSON</summary><button className="productBtn" onClick={() => copyJson(result)}>复制 JSON</button><pre>{JSON.stringify(result, null, 2)}</pre></details>}
    </section>
  )
}
