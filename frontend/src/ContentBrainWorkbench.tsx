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
  setProject: (project: ProjectDraft) => void
  goTab: (tab: WorkspaceTab) => void
}

type BrainCard = {
  id: string
  title: string
  type: string
  lane: string
  source: string
  source_ref?: string
  content: string
  tags?: string[]
  score?: number
  status: 'pending' | 'approved' | 'rejected'
  decision_reason?: string
  used_count?: number
}

const API = '/api/video/integration'

function list(value: any): BrainCard[] {
  return Array.isArray(value?.cards) ? value.cards : []
}

export default function ContentBrainWorkbench({
  project,
  setProject,
  goTab,
}: Props) {
  const [cards, setCards] = useState<BrainCard[]>([])
  const [statusFilter, setStatusFilter] = useState('pending')
  const [lane, setLane] = useState('all')
  const [markdown, setMarkdown] = useState('')
  const [vaultPath, setVaultPath] = useState('')
  const [obsidian, setObsidian] = useState<any>(null)
  const [migration, setMigration] = useState<any>(null)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const visible = useMemo(
    () =>
      cards.filter(
        (card) =>
          (statusFilter === 'all' || card.status === statusFilter) &&
          (lane === 'all' || card.lane === lane),
      ),
    [cards, statusFilter, lane],
  )

  const counts = useMemo(() => ({
    pending: cards.filter((card) => card.status === 'pending').length,
    approved: cards.filter((card) => card.status === 'approved').length,
    rejected: cards.filter((card) => card.status === 'rejected').length,
    obsidian: cards.filter((card) => card.source === 'obsidian_vault').length,
    openclaw: cards.filter((card) => card.source === 'openclaw').length,
  }), [cards])

  async function refresh() {
    setBusy('刷新内容大脑')
    setError('')
    try {
      const [cardData, obsidianData, migrationData] = await Promise.all([
        apiGet(`${API}/knowledge/cards?status=all&limit=2000`, 90000),
        apiGet(`${API}/obsidian/status`, 60000),
        apiGet(`${API}/migration/status`, 60000),
      ])
      setCards(list(cardData))
      setObsidian(obsidianData)
      setMigration(migrationData?.report || migrationData)
      if (obsidianData?.vault) setVaultPath(String(obsidianData.vault))
    } catch (err) {
      setError(detailToText(err))
    } finally {
      setBusy('')
    }
  }

  useEffect(() => {
    void refresh()
  }, [])

  async function migrateLegacy() {
    setBusy('迁移旧内容大脑')
    setError('')
    try {
      const data = await apiPost(`${API}/migration/run`, { force: true, sync_vault: true }, 360000)
      setMigration(data)
      setNotice(`迁移完成：旧数据库 ${data?.old_sqlite_rows || 0} 条，Vault ${data?.vault_markdown_files || 0} 个 Markdown，新增 ${data?.added || 0} 条。`)
      await refresh()
    } catch (err) {
      setError(detailToText(err))
    } finally {
      setBusy('')
    }
  }

  async function configureVault() {
    if (!vaultPath.trim()) {
      setError('请填写服务器上的 Obsidian Vault 绝对路径。')
      return
    }
    setBusy('配置 Vault')
    setError('')
    try {
      await apiPost(`${API}/obsidian/config`, { vault_path: vaultPath.trim() }, 90000)
      setNotice('Obsidian Vault 已配置。')
      await refresh()
    } catch (err) {
      setError(detailToText(err))
    } finally {
      setBusy('')
    }
  }

  async function syncVault() {
    setBusy('同步 Obsidian')
    setError('')
    try {
      const data = await apiPost(
        `${API}/obsidian/sync`,
        { git_pull: true, max_files: 500 },
        360000,
      )
      setNotice(`同步完成：扫描 ${data?.files_scanned || 0} 个文件，新增 ${data?.added || 0} 条知识。`)
      await refresh()
    } catch (err) {
      setError(detailToText(err))
    } finally {
      setBusy('')
    }
  }

  async function importMarkdown() {
    if (!markdown.trim()) {
      setError('请先粘贴 Markdown 内容。')
      return
    }
    setBusy('导入 Markdown')
    setError('')
    try {
      const data = await apiPost(
        `${API}/knowledge/import-markdown`,
        {
          markdown,
          source: 'manual_obsidian_markdown',
          source_ref: 'content_brain_workbench',
        },
        180000,
      )
      setMarkdown('')
      setNotice(`已新增 ${data?.added || 0} 条待审核知识。`)
      await refresh()
    } catch (err) {
      setError(detailToText(err))
    } finally {
      setBusy('')
    }
  }

  async function decide(card: BrainCard, status: BrainCard['status']) {
    setBusy(`处理 ${card.title}`)
    setError('')
    try {
      await apiPost(
        `${API}/knowledge/cards/${encodeURIComponent(card.id)}/decision`,
        { status, reason: `内容大脑人工设置为 ${status}` },
        60000,
      )
      await refresh()
    } catch (err) {
      setError(detailToText(err))
    } finally {
      setBusy('')
    }
  }

  async function harvestOpenClaw() {
    const jobId = String(project.openclaw_job_id || project.openclaw_run_id || '')
    if (!jobId) {
      setError('当前没有 OpenClaw 真实任务 ID。请先到“获客线索”启动采集。')
      return
    }
    setBusy('沉淀 OpenClaw 知识')
    setError('')
    try {
      const data = await apiPost(`${API}/openclaw/harvest/${encodeURIComponent(jobId)}`, {}, 240000)
      setNotice(`读取 ${data?.rows_read || 0} 条结果，新增 ${data?.added_to_brain || 0} 条知识候选。`)
      await refresh()
    } catch (err) {
      setError(detailToText(err))
    } finally {
      setBusy('')
    }
  }

  async function writeBack() {
    setBusy('写回 Obsidian')
    setError('')
    try {
      const data = await apiPost(
        `${API}/obsidian/writeback`,
        { folder: 'AI-VIDEO-Content-Brain', limit: 500 },
        240000,
      )
      setNotice(`已向 Obsidian 写回 ${data?.written || 0} 条批准知识。`)
    } catch (err) {
      setError(detailToText(err))
    } finally {
      setBusy('')
    }
  }

  function useForVideo(card: BrainCard) {
    const current = Array.isArray(project.selected_knowledge_card_ids)
      ? project.selected_knowledge_card_ids
      : []
    const ids = Array.from(new Set([card.id, ...current])).slice(0, 20)
    setProject({
      ...project,
      topic: project.topic || card.title,
      selected_knowledge_card_ids: ids,
      selected_knowledge_cards: [card, ...(project.selected_knowledge_cards || [])].slice(0, 20),
      knowledge_context_updated_at: new Date().toISOString(),
    })
    void apiPost(`${API}/knowledge/cards/${encodeURIComponent(card.id)}/mark-used`, {}, 30000).catch(() => {})
    goTab('pureai')
  }

  return (
    <section className="aiw-card aiw-brainWorkbench">
      <div className="aiw-hero">
        <div>
          <p className="aiw-eyebrow">OBSIDIAN × OPENCLAW × PRODUCTION COPY</p>
          <h2>内容大脑闭环</h2>
          <p>唯一数据源是后端知识库。Obsidian、OpenClaw 客户问题、同行热度和生产文案在这里审核后再进入下一条视频。</p>
        </div>
        <span className={obsidian?.configured ? 'aiw-badge ok' : 'aiw-badge'}>
          {obsidian?.configured ? 'Vault 已连接' : 'Vault 未配置'}
        </span>
      </div>

      <div className="aiw-metrics">
        <div><b>{counts.pending}</b><span>待审核</span></div>
        <div><b>{counts.approved}</b><span>已批准</span></div>
        <div><b>{counts.obsidian}</b><span>Obsidian</span></div>
        <div><b>{counts.openclaw}</b><span>OpenClaw</span></div>
      </div>

      <div className="aiw-info aiw-migrationBanner">
        <div>
          <b>旧知识迁移</b>
          <span>旧 SQLite：{migration?.old_sqlite_rows ?? migration?.legacy_sqlite_rows ?? 0} 条 · 已发现 Vault：{migration?.vault || obsidian?.vault || '等待发现'} · 新知识库共 {cards.length} 条</span>
        </div>
        <button className="aiw-primary" disabled={Boolean(busy)} onClick={() => void migrateLegacy()}>{busy === '迁移旧内容大脑' ? busy : '一键迁移旧内容和 Vault'}</button>
      </div>

      <div className="aiw-twoCol">
        <div className="aiw-panel">
          <h3>Obsidian Vault 自动同步</h3>
          <label>
            服务器 Vault 路径
            <input
              value={vaultPath}
              onChange={(event) => setVaultPath(event.target.value)}
              placeholder="/opt/obsidian-vault 或 Git 仓库目录"
            />
          </label>
          <div className="aiw-actions">
            <button className="aiw-muted" disabled={Boolean(busy)} onClick={configureVault}>保存路径</button>
            <button className="aiw-primary" disabled={Boolean(busy) || !obsidian?.configured} onClick={syncVault}>Git Pull + 增量同步</button>
            <button className="aiw-purple" disabled={Boolean(busy) || !obsidian?.configured} onClick={writeBack}>批准知识写回 Vault</button>
          </div>
          <div className="aiw-info">
            当前：{obsidian?.vault || '未配置'} · Markdown {obsidian?.markdown_files || 0} 个 · Git {obsidian?.git ? '已识别' : '未识别'}
          </div>
        </div>

        <div className="aiw-panel">
          <h3>手动导入与 OpenClaw 沉淀</h3>
          <textarea
            className="aiw-brainMarkdown"
            value={markdown}
            onChange={(event) => setMarkdown(event.target.value)}
            placeholder={'粘贴 Markdown / Obsidian 笔记\n# 客户常问问题\n- 150 万预算能买吗？'}
          />
          <div className="aiw-actions">
            <button className="aiw-primary" disabled={Boolean(busy)} onClick={importMarkdown}>导入待审核</button>
            <button className="aiw-purple" disabled={Boolean(busy)} onClick={harvestOpenClaw}>从真实 OpenClaw 任务沉淀</button>
            <button className="aiw-muted" onClick={() => goTab('leads')}>去启动 OpenClaw</button>
          </div>
        </div>
      </div>

      <div className="aiw-panel">
        <div className="aiw-sectionTitleRow">
          <div><h3>后端知识卡</h3><span>批准后才会进入生产文案；拒绝项不会参与生成。</span></div>
          <button className="aiw-muted" disabled={Boolean(busy)} onClick={refresh}>{busy || '刷新'}</button>
        </div>
        <div className="aiw-chipRow">
          {[
            ['pending', '待审核'],
            ['approved', '已批准'],
            ['rejected', '已拒绝'],
            ['all', '全部状态'],
          ].map(([value, label]) => (
            <button key={value} className={statusFilter === value ? 'aiw-chip active' : 'aiw-chip'} onClick={() => setStatusFilter(value)}>{label}</button>
          ))}
          <span className="aiw-filterDivider">分区</span>
          {[
            ['all', '全部分区'],
            ['video', '视频知识'],
            ['reply', '回复话术'],
            ['visual', '画面规则'],
          ].map(([value, label]) => (
            <button key={`lane-${value}`} className={lane === value ? 'aiw-chip active' : 'aiw-chip'} onClick={() => setLane(value)}>{label}</button>
          ))}
        </div>
        <div className="aiw-brainGrid">
          {visible.map((card) => (
            <article className="aiw-brainCard" key={card.id}>
              <div className="aiw-leadHead"><b>{card.title}</b><span>{card.status}</span></div>
              <p>{card.content}</p>
              <div className="aiw-leadMeta">
                <span>来源：{card.source}</span>
                <span>分区：{card.lane}</span>
                <span>评分：{card.score || 0}</span>
              </div>
              <div className="aiw-actions mini">
                {card.status !== 'approved' && <button onClick={() => decide(card, 'approved')}>批准</button>}
                {card.status !== 'rejected' && <button onClick={() => decide(card, 'rejected')}>拒绝</button>}
                {card.status === 'approved' && <button onClick={() => useForVideo(card)}>用于生产文案</button>}
              </div>
            </article>
          ))}
          {!visible.length && <div className="aiw-empty">当前筛选下暂无知识卡。</div>}
        </div>
      </div>

      {notice && <div className="aiw-successPanel"><div><b>完成</b><span>{notice}</span></div></div>}
      {error && <div className="aiw-error">{error}</div>}
    </section>
  )
}
