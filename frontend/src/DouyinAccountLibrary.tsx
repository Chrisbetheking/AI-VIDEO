import React, { useEffect, useMemo, useState } from 'react'
import { apiGet, apiPost, detailToText, ProjectDraft, WorkspaceTab } from './aiVideoApi'

type Props = {
  project: ProjectDraft
  setProject: (p: ProjectDraft) => void
  goTab: (tab: WorkspaceTab) => void
}

type AccountItem = {
  id?: string
  name?: string
  raw_text?: string
  url?: string
  category?: string
  region?: string
  score?: number
  need_manual?: boolean | number
  updated_at?: string
}

export default function DouyinAccountLibrary({ project, setProject, goTab }: Props) {
  const [mode, setMode] = useState<'competitor' | 'traffic' | 'comments'>('competitor')
  const [keywords, setKeywords] = useState('马来西亚买房,海外房产,吉隆坡公寓,第二家园,海外置业')
  const [accounts, setAccounts] = useState('马来西亚房产同行A,海外置业同行B,吉隆坡公寓同行C')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [result, setResult] = useState<any>(null)
  const [library, setLibrary] = useState<AccountItem[]>([])
  const [computerUseStatus, setComputerUseStatus] = useState<any>(null)

  const categoryStats = useMemo(() => {
    const map = new Map<string, number>()
    library.forEach((item) => map.set(item.category || '待人工确认', (map.get(item.category || '待人工确认') || 0) + 1))
    return Array.from(map.entries()).sort((a, b) => b[1] - a[1])
  }, [library])

  function syncToProject() {
    const firstKeyword = keywords.split(/[,，\n]/).map((x) => x.trim()).filter(Boolean)[0]
    const usableAccounts = library.filter((item) => item.url || item.name).slice(0, 30)
    if (firstKeyword) setProject({
      ...project,
      topic: firstKeyword,
      contentInsights: [{ topic: firstKeyword, source: 'douyin_collect_task' }],
      douyin_account_library: usableAccounts,
      competitorNotes: usableAccounts.map((item) => `${item.name || item.raw_text} ${item.category || ''} ${item.region || ''} ${item.url || ''}`).join('\n'),
    })
    goTab('pureai')
  }

  async function refreshLibrary() {
    setBusy('library')
    setError('')
    try {
      const data = await apiGet('/api/video/account-library/list?limit=500', 60000)
      setLibrary(Array.isArray(data?.items) ? data.items : [])
      const status = await apiGet('/api/collector/computer-use/status', 60000).catch((err) => ({ ok: false, error: detailToText(err) }))
      setComputerUseStatus(status)
    } catch (err) {
      setError(detailToText(err))
    } finally {
      setBusy('')
    }
  }

  useEffect(() => {
    refreshLibrary()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function importAndClassifyAccounts() {
    setBusy('import')
    setError('')
    setResult(null)
    try {
      const imported = await apiPost('/api/video/account-library/import', { raw_text: accounts }, 120000)
      const classified = await apiPost('/api/video/account-library/classify', { limit: 500 }, 120000)
      const list = await apiGet('/api/video/account-library/list?limit=500', 60000)
      setLibrary(Array.isArray(list?.items) ? list.items : [])
      setResult({ imported, classified, list })
    } catch (err) {
      setError(detailToText(err))
    } finally {
      setBusy('')
    }
  }

  async function createMission() {
    setBusy('mission')
    setError('')
    setResult(null)

    const payload = {
      source: 'frontend_douyin_collector_computeruse',
      platform: 'douyin',
      mission_type: mode,
      market: project.market,
      keywords: keywords.split(/[,，\n]/).map((x) => x.trim()).filter(Boolean),
      seed_accounts: accounts.split(/[,，\n]/).map((x) => x.trim()).filter(Boolean),
      account_library_ids: library.map((x) => x.id).filter(Boolean),
      computer_use: true,
      collector_mode: 'computer_use',
      max_accounts: mode === 'traffic' ? 30 : 50,
      max_videos_per_account: 20,
      max_comments_per_video: mode === 'comments' ? 80 : 30,
      run_openclaw_analysis: true,
      run_deepseek: true,
      auto_timeline: true,
    }

    try {
      let data: any
      try {
        data = await apiPost('/api/collector/computer-use/start', payload, 120000)
      } catch (firstErr) {
        // 如果 computer-use 缺 token / worker，后端会明确返回缺项；这里不做假成功，只把账号先写入库。
        const db = await apiPost('/api/video/account-library/import', { raw_text: payload.seed_accounts.join('\n') }, 120000)
        throw new Error(`${detailToText(firstErr)}\n账号已写入账号库，但 ComputerUse 没启动成功：${JSON.stringify(db)}`)
      }
      setResult(data)
      refreshLibrary()
    } catch (err) {
      setError(detailToText(err))
    } finally {
      setBusy('')
    }
  }

  return (
    <section className="aiw-card">
      <div className="aiw-hero">
        <div>
          <p className="aiw-eyebrow">DOUYIN AUTO COLLECTOR</p>
          <h2>抖音自动采集任务中心</h2>
          <p>这里下发任务给 OpenClaw ComputerUse / 采集器：采同行、采流量教学、采评论区，再回传进后端分析链路。缺 Cookie/token/worker 时不允许假成功。</p>
        </div>
        <span className="aiw-badge ok">主平台：抖音</span>
      </div>

      <div className="aiw-chipRow">
        <button className={mode === 'competitor' ? 'aiw-chip active' : 'aiw-chip'} onClick={() => setMode('competitor')}>同行对标采集</button>
        <button className={mode === 'traffic' ? 'aiw-chip active' : 'aiw-chip'} onClick={() => setMode('traffic')}>流量教学采集</button>
        <button className={mode === 'comments' ? 'aiw-chip active' : 'aiw-chip'} onClick={() => setMode('comments')}>评论截流采集</button>
      </div>

      <div className="aiw-metrics">
        <div><b>{library.length}</b><span>SQLite 账号库</span></div>
        <div><b>{library.filter((x) => x.need_manual).length}</b><span>待人工确认</span></div>
        <div><b>{computerUseStatus?.ready ? 'READY' : '缺项'}</b><span>ComputerUse</span></div>
        <div><b>{categoryStats[0]?.[0] || '-'}</b><span>主分类</span></div>
      </div>

      {computerUseStatus && <div className={computerUseStatus.ready ? 'aiw-info' : 'aiw-error'}>
        ComputerUse：{computerUseStatus.ready ? '可启动' : `缺少 ${Array.isArray(computerUseStatus.missing) ? computerUseStatus.missing.join('、') : (computerUseStatus.error || '配置')}`}；模式：{computerUseStatus.mode || 'computer_use'}
      </div>}

      <div className="aiw-form two">
        <label>
          关键词池
          <textarea value={keywords} onChange={(e) => setKeywords(e.target.value)} />
        </label>
        <label>
          种子账号 / 主页备注
          <textarea value={accounts} onChange={(e) => setAccounts(e.target.value)} placeholder="一行一个账号名、主页链接或备注；导入后会进入 SQLite 账号库并分类" />
        </label>
      </div>

      <div className="aiw-actions">
        <button className="aiw-muted" onClick={refreshLibrary} disabled={!!busy}>{busy === 'library' ? '刷新中...' : '刷新账号库'}</button>
        <button className="aiw-purple" onClick={importAndClassifyAccounts} disabled={!!busy}>{busy === 'import' ? '导入中...' : '导入 SQLite + DeepSeek/规则分类'}</button>
        <button className="aiw-primary" onClick={createMission} disabled={!!busy}>{busy === 'mission' ? '下发中...' : '下发 ComputerUse 采集任务'}</button>
        <button className="aiw-purple" onClick={syncToProject}>把账号库送去生成文稿</button>
        <button className="aiw-muted" onClick={() => goTab('leads')}>去看获客承接</button>
      </div>

      {categoryStats.length > 0 && <div className="aiw-chipRow">{categoryStats.map(([cat, count]) => <span className="aiw-keywordPill" key={cat}>{cat} {count}</span>)}</div>}

      <div className="aiw-accountTable">
        <div className="aiw-accountHead"><b>真实账号库</b><span>分类会带入视频创作和 OpenClaw 采集</span></div>
        {library.length === 0 ? <div className="aiw-empty">还没有账号。先粘贴账号/主页链接，点击“导入 SQLite + DeepSeek/规则分类”。</div> : library.slice(0, 80).map((item) => (
          <div className="aiw-accountRow" key={item.id || item.raw_text}>
            <strong>{item.name || item.raw_text || '未命名账号'}</strong>
            <span>{item.category || '待分类'} · {item.region || '未识别区域'} · {item.score || 0}分</span>
            {item.url ? <a href={item.url} target="_blank" rel="noreferrer">打开主页</a> : <em>缺主页链接</em>}
            {item.need_manual ? <b>待人工确认</b> : <small>可用</small>}
          </div>
        ))}
      </div>

      {error && <div className="aiw-error">{error}</div>}
      {result && (
        <details className="aiw-json" open>
          <summary>采集任务 / 入库结果</summary>
          <pre>{JSON.stringify(result, null, 2)}</pre>
        </details>
      )}
    </section>
  )
}
