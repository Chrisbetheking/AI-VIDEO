import React, { useMemo, useState } from 'react'
import { apiGet, apiPost, detailToText, ProjectDraft, WorkspaceTab } from './aiVideoApi'

type Props = { project: ProjectDraft; setProject: (p: ProjectDraft) => void; goTab: (tab: WorkspaceTab) => void }

type MissionMode = 'competitor' | 'traffic_teaching' | 'comment_capture'

export default function DouyinAccountLibrary({ project, setProject, goTab }: Props) {
  const [mode, setMode] = useState<MissionMode>('competitor')
  const [keywords, setKeywords] = useState('马来西亚买房,第二家园,吉隆坡公寓,海外房产投资')
  const [seedAccounts, setSeedAccounts] = useState('马来西亚房产同行A\n海外置业同行B\n吉隆坡公寓同行C')
  const [maxAccounts, setMaxAccounts] = useState(30)
  const [maxVideos, setMaxVideos] = useState(20)
  const [maxComments, setMaxComments] = useState(50)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [result, setResult] = useState<any>(null)
  const actionLabel = useMemo(() => mode === 'competitor' ? '同行对标采集' : mode === 'traffic_teaching' ? '流量教学采集' : '评论区截流采集', [mode])

  async function createMission() {
    setBusy('mission'); setError('')
    const payload = { platform: 'douyin', mission_type: mode, market: project.market, keywords: keywords.split(/[,，\n]/).map((x) => x.trim()).filter(Boolean), seed_accounts: seedAccounts.split(/\n/).map((x) => x.trim()).filter(Boolean), limits: { accounts: maxAccounts, videos_per_account: maxVideos, comments_per_video: maxComments }, run_deepseek: false, auto_timeline: true, target: mode === 'traffic_teaching' ? '学习方法论' : mode === 'comment_capture' ? '截流评论与线索' : '同行对标与选题拆解' }
    try {
      let data: any
      try { data = await apiPost('/api/collector/commands/create', { type: 'douyin_collect', payload }) } catch (err) { data = { ok: false, mode: 'local_mission_draft', message: '后端采集任务队列未启用，已生成本地任务草稿。', backend_error: detailToText(err), payload } }
      setResult(data)
      setProject({ ...project, platform: 'douyin', topic: payload.keywords[0] || project.topic, lastOutput: data })
    } catch (err) { setError(detailToText(err)) } finally { setBusy('') }
  }

  async function checkQueue() {
    setBusy('queue'); setError('')
    try { const data = await apiGet('/api/collector/commands/next?token=frontend_preview'); setResult(data) } catch (err) { setResult({ ok: false, message: '采集器领取接口可能需要专用 token，这是正常的。', detail: detailToText(err) }) } finally { setBusy('') }
  }

  return (
    <section className="ux-card">
      <div className="ux-hero"><div><p className="ux-eyebrow">DOUYIN AUTO COLLECTOR</p><h2>抖音自动采集任务中心</h2><p>这里不是手动放假账号，而是给 OpenClaw/采集器下发任务：采同行、采流量教学、采评论流，回传后进入分析链路。</p></div><span className="ux-badge red">主平台：抖音</span></div>
      <div className="ux-topic-row"><button className={mode === 'competitor' ? 'active' : ''} onClick={() => setMode('competitor')}>同行对标采集</button><button className={mode === 'traffic_teaching' ? 'active' : ''} onClick={() => setMode('traffic_teaching')}>流量教学采集</button><button className={mode === 'comment_capture' ? 'active' : ''} onClick={() => setMode('comment_capture')}>评论区截流采集</button></div>
      <div className="ux-grid four"><label>市场<input value={project.market} onChange={(e) => setProject({ ...project, market: e.target.value })} /></label><label>账号上限<input type="number" value={maxAccounts} onChange={(e) => setMaxAccounts(Number(e.target.value || 30))} /></label><label>每号作品上限<input type="number" value={maxVideos} onChange={(e) => setMaxVideos(Number(e.target.value || 20))} /></label><label>每作品评论上限<input type="number" value={maxComments} onChange={(e) => setMaxComments(Number(e.target.value || 50))} /></label></div>
      <div className="ux-grid two"><label>关键词池<textarea value={keywords} onChange={(e) => setKeywords(e.target.value)} /></label><label>种子账号 / 主页 / 备注<textarea value={seedAccounts} onChange={(e) => setSeedAccounts(e.target.value)} /></label></div>
      <div className="ux-note">当前任务：{actionLabel}。任务会给采集器用，前端不会直接抓抖音；采集器回传后再自动进入 OpenClaw 分析、DeepSeek 和文稿生成。</div>
      <div className="ux-button-row"><button className="ux-primary" onClick={createMission} disabled={!!busy}>{busy === 'mission' ? '下发中...' : '下发自动采集任务'}</button><button className="ux-ghost" onClick={checkQueue} disabled={!!busy}>检查采集器队列</button><button className="ux-purple" onClick={() => goTab('leads')}>去获客承接</button><button className="ux-ghost" onClick={() => goTab('pureai')}>去生成文稿</button></div>
      {error && <div className="ux-error">{error}</div>}
      <div className="ux-metrics four"><div><b>{maxAccounts}</b><span>目标账号</span></div><div><b>{maxVideos}</b><span>每号作品</span></div><div><b>{maxComments}</b><span>每作品评论</span></div><div><b>OpenClaw</b><span>采集器回传</span></div></div>
      {result && <details className="ux-json" open><summary>任务结果</summary><pre>{JSON.stringify(result, null, 2)}</pre></details>}
    </section>
  )
}
