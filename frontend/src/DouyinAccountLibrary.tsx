import React, { useState } from 'react'
import { apiPost, detailToText, ProjectDraft, WorkspaceTab } from './aiVideoApi'

type Props = {
  project: ProjectDraft
  setProject: (p: ProjectDraft) => void
  goTab: (tab: WorkspaceTab) => void
}

export default function DouyinAccountLibrary({ project, setProject, goTab }: Props) {
  const [mode, setMode] = useState<'competitor' | 'traffic' | 'comments'>('competitor')
  const [keywords, setKeywords] = useState('马来西亚买房,海外房产,吉隆坡公寓,第二家园,海外置业')
  const [accounts, setAccounts] = useState('马来西亚房产同行A,海外置业同行B,吉隆坡公寓同行C')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [result, setResult] = useState<any>(null)

  function syncToProject() {
    const firstKeyword = keywords.split(/[,，\n]/).map((x) => x.trim()).filter(Boolean)[0]
    if (firstKeyword) setProject({ ...project, topic: firstKeyword, contentInsights: [{ topic: firstKeyword, source: 'douyin_collect_task' }] })
    goTab('pureai')
  }

  async function createMission() {
    setBusy('mission')
    setError('')
    setResult(null)

    const payload = {
      source: 'frontend_douyin_collector',
      platform: 'douyin',
      mission_type: mode,
      market: project.market,
      keywords: keywords.split(/[,，\n]/).map((x) => x.trim()).filter(Boolean),
      seed_accounts: accounts.split(/[,，\n]/).map((x) => x.trim()).filter(Boolean),
      max_accounts: mode === 'traffic' ? 30 : 50,
      max_videos_per_account: 20,
      max_comments_per_video: mode === 'comments' ? 80 : 30,
      run_openclaw_analysis: true,
      run_deepseek: false,
      auto_timeline: true,
    }

    try {
      let data: any
      try {
        data = await apiPost('/api/collector/commands/create', payload, 120000)
      } catch (firstErr) {
        data = await apiPost('/api/collector/douyin/accounts/bulk-upsert', {
          accounts: payload.seed_accounts.map((name: string) => ({
            category: mode === 'traffic' ? 'traffic_teaching' : 'competitor',
            account_name: name,
            niche: keywords,
            source: 'frontend_collect_target',
          })),
        }, 120000)
      }

      setResult(data)
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
          <p>这里不是手动维护假账号，而是下发任务给 OpenClaw / 采集器：采同行、采流量教学、采评论区，再回传进后端分析链路。</p>
        </div>
        <span className="aiw-badge ok">主平台：抖音</span>
      </div>

      <div className="aiw-chipRow">
        <button className={mode === 'competitor' ? 'aiw-chip active' : 'aiw-chip'} onClick={() => setMode('competitor')}>同行对标采集</button>
        <button className={mode === 'traffic' ? 'aiw-chip active' : 'aiw-chip'} onClick={() => setMode('traffic')}>流量教学采集</button>
        <button className={mode === 'comments' ? 'aiw-chip active' : 'aiw-chip'} onClick={() => setMode('comments')}>评论截流采集</button>
      </div>

      <div className="aiw-form two">
        <label>
          关键词池
          <textarea value={keywords} onChange={(e) => setKeywords(e.target.value)} />
        </label>
        <label>
          种子账号 / 主页备注
          <textarea value={accounts} onChange={(e) => setAccounts(e.target.value)} />
        </label>
      </div>

      <div className="aiw-actions">
        <button className="aiw-primary" onClick={createMission} disabled={!!busy}>{busy ? '下发中...' : '下发自动采集任务'}</button>
        <button className="aiw-purple" onClick={syncToProject}>把关键词送去生成文稿</button>
        <button className="aiw-muted" onClick={() => goTab('leads')}>去看获客承接</button>
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
