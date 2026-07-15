import React, { useEffect, useMemo, useState } from 'react'
import {
  apiGet,
  apiPost,
  detailToText,
  ProjectDraft,
  WorkspaceTab,
} from './aiVideoApi'

type Props = {
  project: ProjectDraft
  setProject: (p: ProjectDraft) => void
  goTab: (tab: WorkspaceTab) => void
}

type Mode = 'competitor' | 'traffic' | 'comments'

function toList(value: any, keys: string[] = []): any[] {
  if (Array.isArray(value)) return value
  if (!value || typeof value !== 'object') return []
  for (const key of keys) {
    if (Array.isArray(value[key])) return value[key]
  }
  return []
}

function text(value: any): string {
  return String(value ?? '').trim()
}

function splitInput(value: string): string[] {
  return value
    .split(/[,，\n]+/)
    .map((item) => item.trim())
    .filter(Boolean)
}

export default function DouyinAccountLibrary({
  project,
  setProject,
  goTab,
}: Props) {
  const [mode, setMode] = useState<Mode>('competitor')
  const [keywords, setKeywords] = useState(
    '马来西亚买房,海外房产,吉隆坡公寓,第二家园,海外置业',
  )
  const [seedAccounts, setSeedAccounts] = useState(
    '马来西亚房产同行A,海外置业同行B,吉隆坡公寓同行C',
  )
  const [accountName, setAccountName] = useState('')
  const [accountUrl, setAccountUrl] = useState('')
  const [videoUrl, setVideoUrl] = useState('')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [result, setResult] = useState<any>(null)
  const [heatAccounts, setHeatAccounts] = useState<any[]>([])
  const [heatItems, setHeatItems] = useState<any[]>([])
  const [selectedItem, setSelectedItem] = useState<any>(null)
  const [rewrite, setRewrite] = useState<any>(null)
  const [accountReviews, setAccountReviews] = useState<any[]>([])
  const [accountAudit, setAccountAudit] = useState<any>(null)

  const topItems = useMemo(
    () =>
      [...heatItems]
        .sort(
          (a, b) =>
            Number(
              b?.business_score ??
                b?.score ??
                b?.heat_score ??
                0,
            ) -
            Number(
              a?.business_score ??
                a?.score ??
                a?.heat_score ??
                0,
            ),
        )
        .slice(0, 8),
    [heatItems],
  )

  async function refreshHeatRadar() {
    setBusy('刷新热度雷达')
    setError('')
    try {
      const [accountData, itemData, reviewData] =
        await Promise.all([
          apiGet('/api/heat-radar/accounts').catch(() => []),
          apiGet('/api/heat-radar/items').catch(() => []),
          apiGet('/api/heat-radar/account-reviews').catch(() => []),
        ])
      setHeatAccounts(
        toList(accountData, [
          'accounts',
          'items',
          'data',
          'results',
        ]),
      )
      setHeatItems(
        toList(itemData, [
          'items',
          'snapshots',
          'data',
          'results',
        ]),
      )
      setAccountReviews(
        toList(reviewData, [
          'reviews',
          'items',
          'data',
          'results',
        ]),
      )
    } catch (err) {
      setError(detailToText(err))
    } finally {
      setBusy('')
    }
  }

  useEffect(() => {
    void refreshHeatRadar()
  }, [])

  function syncToProject(item?: any) {
    const topic =
      text(item?.topic || item?.title || item?.keyword) ||
      splitInput(keywords)[0]
    if (!topic) return

    const nextInsights = [
      {
        topic,
        source: item
          ? 'heat_radar_selected'
          : 'douyin_collect_task',
        intent: text(item?.intent),
        action: text(
          item?.recommended_action ||
            item?.next_action,
        ),
        lead_magnet: text(item?.lead_magnet),
      },
    ]

    setProject({
      ...project,
      topic,
      manualKeywords: splitInput(keywords).join(','),
      manual_keywords: splitInput(keywords).join(','),
      contentInsights: nextInsights,
      heat_radar_context: item || null,
    })
    goTab('pureai')
  }

  async function createMission() {
    setBusy('检查并启动真实采集')
    setError('')
    setResult(null)

    const payload = {
      source: 'frontend_douyin_collector_v10_40_6',
      platform: 'douyin',
      mission_type: mode,
      market: project.market,
      keyword: splitInput(keywords)[0] || project.topic,
      keywords: splitInput(keywords),
      seed_accounts: splitInput(seedAccounts),
      max_accounts: mode === 'traffic' ? 30 : 50,
      max_videos_per_account: 20,
      max_comments_per_video: mode === 'comments' ? 80 : 30,
      collect_accounts: true,
      collect_videos: true,
      collect_comments: true,
      run_deepseek: true,
    }

    try {
      const health = await apiGet('/api/video/integration/openclaw/status', 60000)
      if (!health?.online) {
        throw new Error('OpenClaw 离线，无法开始采集。已阻止“只保存账号却显示采集成功”的假任务。')
      }
      const data = await apiPost(
        '/api/video/integration/openclaw/start',
        payload,
        240000,
      )
      if (!data?.job_id) {
        throw new Error('真实采集接口没有返回 job_id，系统已阻止假成功。')
      }
      setResult(data)
      setProject({
        ...project,
        openclaw_job_id: String(data.job_id),
        openclaw_job: data,
        openclaw_target_accounts: seedAccounts,
      })
    } catch (err) {
      setError(detailToText(err))
    } finally {
      setBusy('')
    }
  }

  async function saveHeatAccount() {
    if (!accountName && !accountUrl) {
      setError('请填写账号名称或主页链接。')
      return
    }
    setBusy('保存账号')
    setError('')
    try {
      const data = await apiPost(
        '/api/heat-radar/accounts',
        {
          name: accountName || accountUrl,
          account_name: accountName || accountUrl,
          platform: 'douyin',
          url: accountUrl,
          account_url: accountUrl,
          positioning: splitInput(keywords).join(' / '),
          notes: `由旧版 UI 功能合并入口添加；模式：${mode}`,
          enabled: true,
        },
        120000,
      )
      setResult(data)
      setAccountName('')
      setAccountUrl('')
      await refreshHeatRadar()
    } catch (err) {
      setError(detailToText(err))
    } finally {
      setBusy('')
    }
  }

  async function runPublicCrawler() {
    setBusy('采集真实热度')
    setError('')
    try {
      const data = await apiPost(
        '/api/heat-radar/run-public-crawl',
        {
          account:
            accountName ||
            heatAccounts[0]?.name ||
            heatAccounts[0]?.account_name ||
            '',
          account_url:
            accountUrl ||
            heatAccounts[0]?.url ||
            heatAccounts[0]?.account_url ||
            '',
          limit: 1,
          keywords: splitInput(keywords),
          platform: 'douyin',
          headful: true,
          no_delay: true,
        },
        360000,
      )
      setResult(data)
      await refreshHeatRadar()
    } catch (err) {
      setError(detailToText(err))
    } finally {
      setBusy('')
    }
  }

  async function analyzeVideo() {
    if (!videoUrl.trim()) {
      setError('请粘贴具体视频或笔记链接。')
      return
    }
    setBusy('分析具体内容')
    setError('')
    try {
      const data = await apiPost(
        '/api/heat-radar/video-intake',
        {
          url: videoUrl.trim(),
          source_url: videoUrl.trim(),
          platform: 'douyin',
          market: project.market,
          keywords: splitInput(keywords),
        },
        240000,
      )
      setResult(data)
      await refreshHeatRadar()
    } catch (err) {
      setError(detailToText(err))
    } finally {
      setBusy('')
    }
  }

  async function auditAccounts() {
    setBusy('审计账号价值')
    setError('')
    try {
      const data = await apiPost(
        '/api/heat-radar/accounts/audit-staleness',
        {
          accounts: heatAccounts,
          keywords: splitInput(keywords),
          include_saved_accounts: true,
          max_stale_days: 90,
        },
        240000,
      )
      setAccountAudit(data)
      setResult(data)
      await refreshHeatRadar()
    } catch (err) {
      setError(detailToText(err))
    } finally {
      setBusy('')
    }
  }

  async function rewriteHeatItem(item: any) {
    setSelectedItem(item)
    setBusy('AI 原创改写')
    setError('')
    setRewrite(null)
    try {
      const data = await apiPost(
        '/api/heat-radar/rewrite',
        {
          item_id: item?.id,
          source_topic:
            item?.topic ||
            item?.title ||
            item?.keyword,
          source_text:
            item?.content ||
            item?.signal ||
            item?.summary,
          target_market: project.market,
          target_audience:
            project.targetAudience ||
            project.audience ||
            '海外置业意向客户',
          keywords: splitInput(keywords),
          no_copy: true,
        },
        240000,
      )
      setRewrite(data)
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
          <p className="aiw-eyebrow">
            DOUYIN COLLECTOR / HEAT RADAR
          </p>
          <h2>同行采集与热度雷达</h2>
          <p>
            保留原来的采集任务入口，并合并账号库、真实热度采集、
            具体视频分析和 AI 原创改写。
          </p>
        </div>
        <span className="aiw-badge ok">
          真实接口已联动
        </span>
      </div>

      <div className="aiw-chipRow">
        <button
          className={
            mode === 'competitor'
              ? 'aiw-chip active'
              : 'aiw-chip'
          }
          onClick={() => setMode('competitor')}
        >
          同行对标采集
        </button>
        <button
          className={
            mode === 'traffic'
              ? 'aiw-chip active'
              : 'aiw-chip'
          }
          onClick={() => setMode('traffic')}
        >
          流量教学采集
        </button>
        <button
          className={
            mode === 'comments'
              ? 'aiw-chip active'
              : 'aiw-chip'
          }
          onClick={() => setMode('comments')}
        >
          评论线索采集
        </button>
      </div>

      <div className="aiw-form two">
        <label>
          关键词池
          <textarea
            value={keywords}
            onChange={(event) =>
              setKeywords(event.target.value)
            }
          />
        </label>
        <label>
          种子账号 / 主页备注
          <textarea
            value={seedAccounts}
            onChange={(event) =>
              setSeedAccounts(event.target.value)
            }
          />
        </label>
      </div>

      <div className="aiw-actions">
        <button
          className="aiw-primary"
          onClick={createMission}
          disabled={Boolean(busy)}
        >
          {busy === '下发采集任务'
            ? '下发中...'
            : '下发自动采集任务'}
        </button>
        <button
          className="aiw-muted"
          onClick={refreshHeatRadar}
          disabled={Boolean(busy)}
        >
          刷新账号与热度
        </button>
        <button
          className="aiw-muted"
          onClick={() => void auditAccounts()}
          disabled={Boolean(busy)}
        >
          生成账号清理建议
        </button>
        <button
          className="aiw-purple"
          onClick={() => syncToProject()}
        >
          把关键词送去生成文稿
        </button>
      </div>

      <div className="aiw-metrics">
        <div><b>{heatAccounts.length}</b><span>当前加载账号</span></div>
        <div><b>{heatItems.length}</b><span>当前加载热度</span></div>
        <div><b>{accountReviews.length}</b><span>当前加载审查</span></div>
        <div><b>{Number(accountAudit?.archive?.length || 0)}</b><span>建议暂停账号</span></div>
      </div>

      <div className="aiw-twoCol">
        <div className="aiw-panel">
          <h3>固定账号库</h3>
          <div className="aiw-form two">
            <label>
              账号名称
              <input
                value={accountName}
                onChange={(event) =>
                  setAccountName(event.target.value)
                }
                placeholder="例如：吉隆坡房产顾问"
              />
            </label>
            <label>
              主页链接
              <input
                value={accountUrl}
                onChange={(event) =>
                  setAccountUrl(event.target.value)
                }
                placeholder="抖音主页或视频链接"
              />
            </label>
          </div>
          <div className="aiw-actions">
            <button
              className="aiw-muted"
              onClick={saveHeatAccount}
              disabled={Boolean(busy)}
            >
              保存到账号库
            </button>
            <button
              className="aiw-primary"
              onClick={runPublicCrawler}
              disabled={Boolean(busy)}
            >
              采集一个真实账号
            </button>
          </div>
          <div className="aiw-miniList">
            {heatAccounts.length === 0 && (
              <div>当前还没有已保存账号。</div>
            )}
            {heatAccounts.slice(0, 12).map(
              (account, index) => (
                <div
                  key={
                    account?.id ||
                    account?.url ||
                    index
                  }
                >
                  <b>
                    {text(
                      account?.name ||
                        account?.account_name,
                    ) || `账号 ${index + 1}`}
                  </b>
                  <span>
                    {text(
                      account?.platform ||
                        account?.account_url ||
                        account?.url,
                    )}
                  </span>
                </div>
              ),
            )}
          </div>
        </div>

        <div className="aiw-panel">
          <h3>具体视频 / 笔记分析</h3>
          <label>
            链接
            <input
              value={videoUrl}
              onChange={(event) =>
                setVideoUrl(event.target.value)
              }
              placeholder="粘贴具体视频或笔记链接"
            />
          </label>
          <div className="aiw-actions">
            <button
              className="aiw-primary"
              onClick={analyzeVideo}
              disabled={Boolean(busy)}
            >
              分析并进入热度池
            </button>
            <button
              className="aiw-muted"
              onClick={() => goTab('leads')}
            >
              去看获客承接
            </button>
          </div>
        </div>
      </div>

      <div className="aiw-panel">
        <h3>今日高价值内容</h3>
        <div className="aiw-assetGrid aiw-heatGrid">
          {topItems.length === 0 && (
            <div className="aiw-info">
              还没有真实热度内容。先保存账号并采集，
              或粘贴具体视频链接。
            </div>
          )}
          {topItems.map((item, index) => {
            const score = Number(
              item?.business_score ??
                item?.score ??
                item?.heat_score ??
                0,
            )
            const title =
              text(
                item?.topic ||
                  item?.title ||
                  item?.keyword,
              ) || `热度内容 ${index + 1}`
            return (
              <div
                className={
                  selectedItem === item
                    ? 'aiw-assetCard aiw-heatCard selected'
                    : 'aiw-assetCard aiw-heatCard'
                }
                key={
                  item?.id ||
                  `${title}-${index}`
                }
              >
                <strong>{title}</strong>
                <span>
                  业务评分 {score || '-'} ·{' '}
                  {text(item?.intent) || '待判断意图'}
                </span>
                <p className="aiw-heatSummary">
                  {text(
                    item?.signal ||
                      item?.summary ||
                      item?.recommended_action,
                  ) || '等待 AI 进一步分析。'}
                </p>
                <div className="aiw-actions vertical">
                  <button
                    className="aiw-purple"
                    onClick={() => syncToProject(item)}
                  >
                    带入四步视频创作
                  </button>
                  <button
                    className="aiw-muted"
                    onClick={() =>
                      void rewriteHeatItem(item)
                    }
                    disabled={Boolean(busy)}
                  >
                    AI 原创改写
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {busy && (
        <div className="aiw-info">{busy}…</div>
      )}
      {error && (
        <div className="aiw-error">{error}</div>
      )}
      {accountAudit && (
        <details className="aiw-json" open>
          <summary>账号价值审计 / 清理建议</summary>
          <pre>{JSON.stringify(accountAudit, null, 2)}</pre>
        </details>
      )}
      {rewrite && (
        <details className="aiw-json" open>
          <summary>AI 原创改写结果</summary>
          <pre>
            {JSON.stringify(rewrite, null, 2)}
          </pre>
        </details>
      )}
      {result && (
        <details className="aiw-json">
          <summary>采集 / 入库原始结果</summary>
          <pre>
            {JSON.stringify(result, null, 2)}
          </pre>
        </details>
      )}
    </section>
  )
}
