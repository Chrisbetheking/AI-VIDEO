import React, { useMemo, useState } from 'react'
import { apiGet, apiPost, detailToText, ProjectDraft } from './aiVideoApi'

type WorkspaceTab = 'pureai' | 'collect' | 'leads' | 'digital'

type Props = {
  project: ProjectDraft
  setProject: (p: ProjectDraft) => void
  goTab: (tab: WorkspaceTab) => void
}

type Mission = {
  type: 'competitor' | 'traffic_teaching' | 'comments'
  keywords: string
  seedAccounts: string
  maxAccounts: number
  maxVideos: number
  maxComments: number
  runDeepSeek: boolean
  autoTimeline: boolean
}

function defaultMission(): Mission {
  return {
    type: 'competitor',
    keywords: '马来西亚买房, 吉隆坡房产, 海外房产投资, 第二家园, 海外置业',
    seedAccounts: '马来西亚房产同行, 海外置业同行, 吉隆坡公寓投资号',
    maxAccounts: 30,
    maxVideos: 20,
    maxComments: 50,
    runDeepSeek: true,
    autoTimeline: true,
  }
}

function missionTitle(type: Mission['type']) {
  if (type === 'competitor') return '同行对标采集'
  if (type === 'traffic_teaching') return '流量教学采集'
  return '评论区截流采集'
}

export default function DouyinAccountLibrary({ project, setProject, goTab }: Props) {
  const [mission, setMission] = useState<Mission>(defaultMission())
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [result, setResult] = useState<any>(null)
  const [localMissions, setLocalMissions] = useState<any[]>(() => {
    try { return JSON.parse(localStorage.getItem('ai_video_douyin_missions_v8') || '[]') } catch { return [] }
  })

  const missionPreview = useMemo(() => {
    return {
      platform: 'douyin',
      mission_type: mission.type,
      mission_title: missionTitle(mission.type),
      market: project.market,
      keywords: mission.keywords.split(/[,，、\n]+/).map(x => x.trim()).filter(Boolean),
      seed_accounts: mission.seedAccounts.split(/[,，、\n]+/).map(x => x.trim()).filter(Boolean),
      limits: {
        max_accounts: mission.maxAccounts,
        max_videos_per_account: mission.maxVideos,
        max_comments_per_video: mission.maxComments,
      },
      run_deepseek: mission.runDeepSeek,
      auto_timeline: mission.autoTimeline,
      instruction: 'OpenClaw/采集器领取任务后，自动采集公开视频、账号、标题、评论和互动数据，回传后进入线索评分、内容结构分析和 Timeline。',
    }
  }, [mission, project.market])

  function patch(next: Partial<Mission>) {
    setMission({ ...mission, ...next })
  }

  function saveLocalMission(payload: any) {
    const next = [{ ...payload, local_id: `mission_${Date.now()}`, status: 'queued_local', created_at: new Date().toISOString() }, ...localMissions].slice(0, 20)
    setLocalMissions(next)
    localStorage.setItem('ai_video_douyin_missions_v8', JSON.stringify(next))
  }

  async function createMission() {
    setBusy('mission')
    setError('')
    const payload = {
      command_type: 'douyin_collect_and_analyze',
      payload: missionPreview,
      priority: mission.type === 'comments' ? 'high' : 'normal',
      source: 'frontend_engineering_workspace_v8',
    }
    try {
      let data: any
      try {
        data = await apiPost('/api/collector/commands/create', payload)
      } catch (err) {
        saveLocalMission(payload)
        data = {
          ok: true,
          mode: 'local_queue_fallback',
          message: '后端 collector command 创建接口暂不可用，本次已保存为本地采集任务草稿。下一步要补后端任务队列接口。',
          queued_payload: payload,
          backend_error: detailToText(err),
        }
      }
      setResult(data)
    } catch (err) {
      setError(detailToText(err))
    } finally {
      setBusy('')
    }
  }

  async function seedBackendTargets() {
    setBusy('seed')
    setError('')
    try {
      const data = await apiGet(`/api/collector/douyin/accounts/seed-targets?market=${encodeURIComponent(project.market)}`)
      setResult(data)
    } catch (err) {
      setError(detailToText(err))
    } finally {
      setBusy('')
    }
  }

  function useForProject() {
    const first = missionPreview.keywords[0] || project.topic
    setProject({ ...project, topic: first, platform: 'douyin', lastOutput: missionPreview })
    goTab('pureai')
  }

  return (
    <section className="ux-card">
      <div className="ux-card-hero">
        <p className="ux-eyebrow">DOUYIN AUTO COLLECTOR / REAL TASK FIRST</p>
        <h2>抖音自动采集任务中心</h2>
        <p>这里不是手动存几个假账号，而是给 OpenClaw / 采集器下发任务：找同行、找流量教学号、抓作品、抓评论，回传后自动进入分析链路。</p>
        <span className="ux-badge blue">主平台：抖音</span>
      </div>

      <div className="ux-topic-row">
        <button className={mission.type === 'competitor' ? 'active' : ''} onClick={() => patch({ type: 'competitor', keywords: '马来西亚买房, 吉隆坡房产, 海外房产投资, 第二家园, 海外置业', seedAccounts: '马来西亚房产同行, 海外置业同行, 吉隆坡公寓投资号' })}>同行对标采集</button>
        <button className={mission.type === 'traffic_teaching' ? 'active' : ''} onClick={() => patch({ type: 'traffic_teaching', keywords: '短视频起号, 抖音流量, 爆款标题, 评论区转化, 直播转化', seedAccounts: '短视频流量教学号, 起号教学号, 爆款文案教学号' })}>流量教学采集</button>
        <button className={mission.type === 'comments' ? 'active' : ''} onClick={() => patch({ type: 'comments', keywords: '马来西亚买房首付, 海外房产避坑, 吉隆坡公寓出租, 第二家园申请', seedAccounts: '高评论房产视频, 同行热视频, 目标客户评论区' })}>评论区截流采集</button>
      </div>

      <div className="ux-form-grid two">
        <label>采集关键词
          <textarea value={mission.keywords} onChange={(e) => patch({ keywords: e.target.value })} />
        </label>
        <label>种子账号 / 搜索入口
          <textarea value={mission.seedAccounts} onChange={(e) => patch({ seedAccounts: e.target.value })} />
        </label>
      </div>

      <div className="ux-form-grid four">
        <label>账号上限
          <input type="number" min={1} value={mission.maxAccounts} onChange={(e) => patch({ maxAccounts: Number(e.target.value || 30) })} />
        </label>
        <label>每号作品上限
          <input type="number" min={1} value={mission.maxVideos} onChange={(e) => patch({ maxVideos: Number(e.target.value || 20) })} />
        </label>
        <label>每条评论上限
          <input type="number" min={0} value={mission.maxComments} onChange={(e) => patch({ maxComments: Number(e.target.value || 50) })} />
        </label>
        <label className="ux-check">
          <input type="checkbox" checked={mission.runDeepSeek} onChange={(e) => patch({ runDeepSeek: e.target.checked })} />
          回传后自动 DeepSeek 分析
        </label>
      </div>

      <div className="ux-metrics four">
        <div><b>{mission.maxAccounts}</b><span>账号目标</span></div>
        <div><b>{mission.maxAccounts * mission.maxVideos}</b><span>作品目标</span></div>
        <div><b>{mission.maxAccounts * mission.maxVideos * mission.maxComments}</b><span>评论目标上限</span></div>
        <div><b>{localMissions.length}</b><span>本地待下发草稿</span></div>
      </div>

      <div className="ux-info">采集器要回传字段：账号、抖音号、主页链接、视频标题、描述、点赞/评论/收藏/转发、评论文本、评论点赞、回复数、视频链接。回传后再进 OpenClaw 截流和纯 AI 生成。</div>

      <div className="ux-button-row">
        <button className="ux-primary" onClick={createMission} disabled={!!busy}>{busy === 'mission' ? '下发中...' : '下发自动采集任务'}</button>
        <button className="ux-ghost" onClick={seedBackendTargets} disabled={!!busy}>读取后端推荐目标</button>
        <button className="ux-ghost" onClick={useForProject}>用关键词进入生成路径</button>
        <button className="ux-ghost" onClick={() => goTab('leads')}>去看截流承接</button>
      </div>

      {error && <div className="ux-error">{error}</div>}
      <div className="ux-two-col">
        <div className="ux-panel">
          <h3>任务预览</h3>
          <pre className="ux-script">{JSON.stringify(missionPreview, null, 2)}</pre>
        </div>
        <div className="ux-panel">
          <h3>工程化联动</h3>
          <div className="ux-segment-list">
            <div className="ux-segment"><b>采集</b><p>OpenClaw/采集器领取任务。</p><em>不是让老板手动搜索。</em></div>
            <div className="ux-segment"><b>分析</b><p>回传后自动做线索评分、内容结构分析、DeepSeek 增强。</p><em>高分同行作为对标，不照搬。</em></div>
            <div className="ux-segment"><b>生产</b><p>高分选题进入纯 AI 文稿/分镜，再生成视频。</p><em>没有文稿不能生成视频。</em></div>
          </div>
        </div>
      </div>
      {result && <details className="ux-json"><summary>任务结果</summary><pre>{JSON.stringify(result, null, 2)}</pre></details>}
    </section>
  )
}
