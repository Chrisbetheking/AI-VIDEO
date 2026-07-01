import React, { useMemo, useState } from 'react'
import { apiPost, detailToText, ProjectDraft } from './aiVideoApi'

type WorkspaceTab = 'pure' | 'douyin' | 'openclaw' | 'digital'
type MissionType = 'competitor' | 'traffic_teaching' | 'comment_capture'

type Props = {
  project: ProjectDraft
  setProject: (next: ProjectDraft) => void
  goTab?: (next: WorkspaceTab) => void
}

const defaultKeywords = {
  competitor: '马来西亚买房,吉隆坡房产,海外房产投资,第二家园,海外置业',
  traffic_teaching: '短视频起号,房产获客,评论区转化,爆款标题,抖音运营',
  comment_capture: '马来西亚买房首付,海外房产避坑,吉隆坡公寓出租,第二家园申请',
}

export default function DouyinAccountLibrary({ project, setProject, goTab }: Props) {
  const [missionType, setMissionType] = useState<MissionType>('competitor')
  const [keywords, setKeywords] = useState(defaultKeywords.competitor)
  const [seedAccounts, setSeedAccounts] = useState('马来西亚房产同行A\n海外置业同行B\n吉隆坡公寓同行C')
  const [maxAccounts, setMaxAccounts] = useState(30)
  const [maxVideos, setMaxVideos] = useState(20)
  const [maxComments, setMaxComments] = useState(80)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [result, setResult] = useState<any>(null)

  const missionLabel = useMemo(() => {
    if (missionType === 'competitor') return '同行对标采集'
    if (missionType === 'traffic_teaching') return '流量教学采集'
    return '评论区截流采集'
  }, [missionType])

  function switchType(next: MissionType) {
    setMissionType(next)
    setKeywords(defaultKeywords[next])
  }

  function applyToProject() {
    const firstKeyword = keywords.split(/[,，\n]/).map((x) => x.trim()).filter(Boolean)[0] || project.topic
    setProject({
      ...project,
      topic: firstKeyword,
      platform: 'douyin',
      contentInsights: [
        ...(project.contentInsights || []),
        {
          source: 'douyin_collection_target',
          mission_type: missionType,
          keywords,
          seed_accounts: seedAccounts,
        },
      ],
    })
    goTab?.('pure')
  }

  async function createMission() {
    setBusy('create-mission')
    setError('')

    const payload = {
      platform: 'douyin',
      mission_type: missionType,
      title: missionLabel,
      target: {
        market: project.market,
        keywords: keywords.split(/[,，\n]/).map((x) => x.trim()).filter(Boolean),
        seed_accounts: seedAccounts.split(/\n/).map((x) => x.trim()).filter(Boolean),
        max_accounts: maxAccounts,
        max_videos_per_account: maxVideos,
        max_comments_per_video: maxComments,
      },
      auto_analysis: {
        openclaw: true,
        deepseek: false,
        create_timeline: true,
      },
    }

    try {
      const data = await apiPost('/api/collector/commands/create', payload)
      setResult(data)
    } catch (err: any) {
      setError(
        `${detailToText(err?.message || err)}\n后端采集任务队列如果未启用，需要补 /api/collector/commands/create。`,
      )
    } finally {
      setBusy('')
    }
  }

  return (
    <section className="productPanel">
      <div className="productHero">
        <div>
          <p className="productEyebrow">DOUYIN AUTO COLLECTOR</p>
          <h2>抖音自动采集任务中心</h2>
          <p>
            这里不是手动维护假账号，而是给 OpenClaw / 采集器下发目标：同行账号、流量教学账号、评论区截流。回传后进入分析、文稿和 Timeline。
          </p>
        </div>
        <span className="productBadge">主平台：抖音</span>
      </div>

      <div className="topicRow">
        <button type="button" className={missionType === 'competitor' ? 'active' : ''} onClick={() => switchType('competitor')}>
          同行对标采集
        </button>
        <button
          type="button"
          className={missionType === 'traffic_teaching' ? 'active' : ''}
          onClick={() => switchType('traffic_teaching')}
        >
          流量教学采集
        </button>
        <button
          type="button"
          className={missionType === 'comment_capture' ? 'active' : ''}
          onClick={() => switchType('comment_capture')}
        >
          评论区截流采集
        </button>
      </div>

      <div className="productFormGrid">
        <label>
          关键词
          <textarea value={keywords} onChange={(event) => setKeywords(event.target.value)} />
        </label>
        <label>
          种子账号 / 主页链接
          <textarea value={seedAccounts} onChange={(event) => setSeedAccounts(event.target.value)} />
        </label>
        <label>
          账号上限
          <input type="number" value={maxAccounts} onChange={(event) => setMaxAccounts(Number(event.target.value || 30))} />
        </label>
        <label>
          每账号作品上限
          <input type="number" value={maxVideos} onChange={(event) => setMaxVideos(Number(event.target.value || 20))} />
        </label>
        <label>
          每作品评论上限
          <input type="number" value={maxComments} onChange={(event) => setMaxComments(Number(event.target.value || 80))} />
        </label>
      </div>

      <div className="productButtonRow">
        <button type="button" onClick={createMission} disabled={!!busy}>
          下发自动采集任务
        </button>
        <button type="button" className="green" onClick={applyToProject}>
          先用这些关键词生成文稿
        </button>
        <button type="button" className="ghost" onClick={() => goTab?.('openclaw')}>
          看获客承接
        </button>
      </div>

      <div className="productGrid four">
        <div className="metricCard">
          <b>{maxAccounts}</b>
          <span>目标账号</span>
        </div>
        <div className="metricCard">
          <b>{maxVideos}</b>
          <span>单账号作品</span>
        </div>
        <div className="metricCard">
          <b>{maxComments}</b>
          <span>单作品评论</span>
        </div>
        <div className="metricCard">
          <b>{missionLabel}</b>
          <span>当前任务</span>
        </div>
      </div>

      {busy && <div className="productNotice">处理中：{busy}</div>}
      {error && <div className="productError">{error}</div>}

      {result && (
        <details className="resultJson" open>
          <summary>采集任务结果</summary>
          <pre>{JSON.stringify(result, null, 2)}</pre>
        </details>
      )}
    </section>
  )
}
