import React, { useEffect, useMemo, useState } from 'react'
import { ProjectDraft, WorkspaceTab, projectWithScript, generateLocalScript, apiGet, apiPost } from './aiVideoApi'

type Props = {
  project: ProjectDraft
  setProject: (p: ProjectDraft) => void
  goTab: (tab: WorkspaceTab) => void
}

type BrainStatus = 'pending' | 'approved' | 'rejected'
type BrainType = 'lead_question' | 'topic' | 'hook' | 'script' | 'visual_rule' | 'market_note' | 'reply_template'

type BrainCard = {
  id: string
  title: string
  type: BrainType
  source: string
  content: string
  tags: string[]
  score: number
  status: BrainStatus
  decisionReason: string
  createdAt: string
  updatedAt?: string
  usedCount?: number
  raw?: any
}

const BRAIN_KEY = 'ai_video_content_brain_cards_v9'
const BRAIN_INBOX_KEY = 'ai_video_content_brain_inbox_v9'

const TYPE_LABELS: Record<BrainType, string> = {
  lead_question: '客户问题',
  topic: '选题',
  hook: '开头钩子',
  script: '口播文案',
  visual_rule: '画面规则',
  market_note: '市场知识',
  reply_template: '回复模板',
}

function nowText() {
  return new Date().toLocaleString()
}

function uid(prefix = 'brain') {
  return `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`
}

function safeParse<T>(raw: string | null, fallback: T): T {
  try {
    if (!raw) return fallback
    const parsed = JSON.parse(raw)
    return parsed || fallback
  } catch {
    return fallback
  }
}

function loadCards(): BrainCard[] {
  return safeParse<BrainCard[]>(localStorage.getItem(BRAIN_KEY), [])
}

function saveCards(cards: BrainCard[]) {
  localStorage.setItem(BRAIN_KEY, JSON.stringify(cards.slice(0, 500)))
}

function loadInbox(): BrainCard[] {
  return safeParse<BrainCard[]>(localStorage.getItem(BRAIN_INBOX_KEY), [])
}

function saveInbox(cards: BrainCard[]) {
  localStorage.setItem(BRAIN_INBOX_KEY, JSON.stringify(cards.slice(0, 300)))
}

function splitTags(value: string): string[] {
  return String(value || '')
    .split(/[，,\n#\s]+/)
    .map((x) => x.trim())
    .filter(Boolean)
    .slice(0, 12)
}

function normalizeMarkdownToCards(markdown: string, source = 'obsidian_markdown'): BrainCard[] {
  const text = String(markdown || '').trim()
  if (!text) return []

  const blocks = text
    .split(/\n(?=#{1,3}\s)|\n---+\n|\n\n+/)
    .map((x) => x.trim())
    .filter((x) => x.length > 10)

  return blocks.slice(0, 60).map((block) => {
    const titleMatch = block.match(/^#{1,4}\s+(.+)$/m)
    const title = titleMatch?.[1]?.trim() || block.slice(0, 26).replace(/\n/g, ' ')
    const lower = block.toLowerCase()
    let type: BrainType = 'market_note'
    if (/评论|私信|客户|预算|能买吗|华语|华人|咨询/.test(block)) type = 'lead_question'
    if (/选题|主题|标题|话题/.test(block)) type = 'topic'
    if (/hook|开头|钩子|前三秒/.test(lower)) type = 'hook'
    if (/镜头|画面|素材|b-roll|室内|阳台|大堂|泳池/.test(lower)) type = 'visual_rule'
    if (/回复|私信|评论区/.test(block)) type = 'reply_template'

    return {
      id: uid('md'),
      title,
      type,
      source,
      content: block.replace(/^#{1,4}\s+/gm, '').trim(),
      tags: splitTags(`${title} 马来西亚 吉隆坡 房产`),
      score: type === 'lead_question' || type === 'hook' ? 82 : 70,
      status: 'pending',
      decisionReason: 'Markdown/Obsidian 导入，等待人工确认是否进入内容大脑。',
      createdAt: nowText(),
    }
  })
}

function makeCardsFromProject(project: ProjectDraft): BrainCard[] {
  const cards: BrainCard[] = []
  const topic = String(project.topic || project.title || '').trim()
  const script = String(project.script || '').trim()
  const tags = splitTags(`${project.market || ''} ${project.city || ''} ${topic} ${project.manualKeywords || ''}`)

  if (topic) {
    cards.push({
      id: uid('topic'),
      title: topic,
      type: 'topic',
      source: 'current_video_project',
      content: `当前视频选题：${topic}\n市场：${project.market || '马来西亚'}\n城市：${project.city || '吉隆坡'}\n适合继续发散成系列内容。`,
      tags,
      score: 76,
      status: 'pending',
      decisionReason: '当前视频选题，建议先确认是否值得做成系列。',
      createdAt: nowText(),
      raw: { topic, market: project.market, city: project.city },
    })
  }

  if (script.length > 20) {
    cards.push({
      id: uid('script'),
      title: `${topic || '当前视频'}口播稿`,
      type: 'script',
      source: 'current_video_script',
      content: script,
      tags,
      score: 68,
      status: 'pending',
      decisionReason: '生成稿不一定都要入库；建议只保留高转化或结构好的版本。',
      createdAt: nowText(),
      raw: { script },
    })
  }

  const leads = Array.isArray(project.leads) ? project.leads : []
  leads.slice(0, 30).forEach((lead: any) => {
    const text = String(lead.text || lead.comment || lead.message || '').trim()
    if (!text) return
    const score = Number(lead.score || 60)
    const priority = String(lead.priority || '')
    cards.push({
      id: uid('lead'),
      title: text.slice(0, 32),
      type: 'lead_question',
      source: 'openclaw_lead_context',
      content: text,
      tags: splitTags(`${tags.join(' ')} ${lead.accountName || ''} ${lead.author || ''} ${lead.priority || ''}`),
      score,
      status: score >= 70 || priority === 'A' ? 'pending' : 'rejected',
      decisionReason: score >= 70 || priority === 'A' ? 'A/B 线索问题，建议沉淀为客户问题库。' : '低意向或信息不足，默认不入库。',
      createdAt: nowText(),
      raw: lead,
    })
  })

  return cards
}

function dedupe(cards: BrainCard[]): BrainCard[] {
  const seen = new Set<string>()
  const out: BrainCard[] = []
  cards.forEach((card) => {
    const key = `${card.type}|${card.title}|${card.content.slice(0, 80)}`.replace(/\s+/g, '').toLowerCase()
    if (seen.has(key)) return
    seen.add(key)
    out.push(card)
  })
  return out
}

function cardToMarkdown(card: BrainCard) {
  return [
    `# ${card.title}`,
    '',
    `- 类型：${TYPE_LABELS[card.type]}`,
    `- 来源：${card.source}`,
    `- 分数：${card.score}`,
    `- 状态：${card.status}`,
    `- 标签：${card.tags.join(', ')}`,
    `- 判断：${card.decisionReason}`,
    '',
    card.content,
    '',
  ].join('\n')
}

function downloadMarkdown(cards: BrainCard[]) {
  const body = cards.map(cardToMarkdown).join('\n---\n')
  const blob = new Blob([body], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `ai-video-content-brain-${Date.now()}.md`
  a.click()
  URL.revokeObjectURL(url)
}

export default function ContentBrainWorkbench({ project, setProject, goTab }: Props) {
  const [cards, setCards] = useState<BrainCard[]>(() => loadCards())
  const [inbox, setInbox] = useState<BrainCard[]>(() => loadInbox())
  const [markdown, setMarkdown] = useState('')
  const [manualTitle, setManualTitle] = useState('')
  const [manualContent, setManualContent] = useState('')
  const [manualTags, setManualTags] = useState('马来西亚,吉隆坡,房产')
  const [filter, setFilter] = useState<'all' | BrainStatus>('approved')
  const [typeFilter, setTypeFilter] = useState<'all' | BrainType>('all')
  const [backendStatus, setBackendStatus] = useState('正在连接后端内容大脑')
  const [backendBusy, setBackendBusy] = useState('')
  const [backendError, setBackendError] = useState('')

  useEffect(() => saveCards(cards), [cards])
  useEffect(() => saveInbox(inbox), [inbox])

  const approved = cards.filter((card) => card.status === 'approved')
  const pending = [...inbox, ...cards.filter((card) => card.status === 'pending')]
  const filteredCards = cards.filter((card) => {
    if (filter !== 'all' && card.status !== filter) return false
    if (typeFilter !== 'all' && card.type !== typeFilter) return false
    return true
  })


  function normalizeServerCards(data: any): BrainCard[] {
    const list = Array.isArray(data?.cards) ? data.cards : Array.isArray(data) ? data : []
    return list.map((item: any) => ({
      id: String(item.id || uid('srv')),
      title: String(item.title || item.content || '未命名知识'),
      type: (item.type || item.card_type || 'market_note') as BrainType,
      source: String(item.source || 'backend_content_brain'),
      content: String(item.content || item.title || ''),
      tags: Array.isArray(item.tags) ? item.tags : splitTags(item.tags || ''),
      score: Number(item.score || 70),
      status: (item.status || 'pending') as BrainStatus,
      decisionReason: String(item.decisionReason || item.decision_reason || '后端内容大脑同步。'),
      createdAt: String(item.createdAt || item.created_at || nowText()),
      updatedAt: item.updatedAt || item.updated_at,
      usedCount: Number(item.usedCount || item.used_count || 0),
      raw: item.raw || item,
    })).filter((card: BrainCard) => card.content || card.title)
  }

  async function refreshBackendBrain() {
    setBackendBusy('refresh')
    setBackendError('')
    try {
      const [approvedRes, pendingRes] = await Promise.all([
        apiGet('/api/video/content-brain/cards?status=approved&limit=300'),
        apiGet('/api/video/content-brain/cards?status=pending&limit=300'),
      ])
      const approvedCards = normalizeServerCards(approvedRes)
      const pendingCards = normalizeServerCards(pendingRes)
      setCards((current) => dedupe([...approvedCards, ...current]))
      setInbox((current) => dedupe([...pendingCards, ...current]))
      setBackendStatus(`已连接后端内容大脑：已批准 ${approvedCards.length} 条，待审核 ${pendingCards.length} 条`)
    } catch (err: any) {
      setBackendStatus('后端内容大脑未连接，继续使用浏览器本地草稿')
      setBackendError(err?.message || '无法连接后端内容大脑')
    } finally {
      setBackendBusy('')
    }
  }

  useEffect(() => {
    refreshBackendBrain()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function setCardStatus(card: BrainCard, status: BrainStatus, reason?: string) {
    const nextCard = { ...card, status, decisionReason: reason || card.decisionReason, updatedAt: nowText() }
    setInbox((current) => current.filter((item) => item.id !== card.id))
    setCards((current) => dedupe([nextCard, ...current.filter((item) => item.id !== card.id)]))
    try {
      const path = status === 'approved' ? '/api/video/content-brain/approve' : status === 'rejected' ? '/api/video/content-brain/reject' : ''
      if (path && card.id) await apiPost(path, { id: card.id, reason: reason || nextCard.decisionReason }, 60000)
    } catch (err: any) {
      setBackendError(err?.message || '后端状态同步失败，本地已先更新')
    }
  }

  async function importMarkdown() {
    const next = normalizeMarkdownToCards(markdown)
    if (!next.length) return
    setInbox((current) => dedupe([...next, ...current]))
    try {
      const res = await apiPost('/api/video/content-brain/import-markdown', { markdown, source: 'obsidian_markdown', status: 'pending' }, 120000)
      const serverCards = normalizeServerCards(res)
      if (serverCards.length) setInbox((current) => dedupe([...serverCards, ...current]))
      setBackendStatus(`Markdown 已同步到后端待审核：${serverCards.length || next.length} 条`)
    } catch (err: any) {
      setBackendError(err?.message || 'Markdown 后端导入失败，本地已保留')
    }
    setMarkdown('')
  }

  function importCurrentProject() {
    const next = makeCardsFromProject(project)
    if (!next.length) return
    setInbox((current) => dedupe([...next, ...current]))
  }

  async function addManualCard() {
    if (!manualTitle.trim() && !manualContent.trim()) return
    const card: BrainCard = {
      id: uid('manual'),
      title: manualTitle.trim() || manualContent.slice(0, 24),
      type: 'market_note',
      source: 'manual_input',
      content: manualContent.trim() || manualTitle.trim(),
      tags: splitTags(manualTags),
      score: 72,
      status: 'approved',
      decisionReason: '人工手动录入，默认进入内容大脑。',
      createdAt: nowText(),
    }
    setCards((current) => dedupe([card, ...current]))
    try {
      const res = await apiPost('/api/video/content-brain/cards', card, 60000)
      const saved = normalizeServerCards(res?.card ? { cards: [res.card] } : res)
      if (saved.length) setCards((current) => dedupe([...saved, ...current.filter((item) => item.id !== card.id)]))
    } catch (err: any) {
      setBackendError(err?.message || '手动知识后端保存失败，本地已保留')
    }
    setManualTitle('')
    setManualContent('')
  }

  async function useCardForVideo(card: BrainCard) {
    const script = generateLocalScript(card.title, project.market || '马来西亚', project.targetDuration || 20)
    const nextProject = projectWithScript({ ...project, topic: card.title, content_brain_context: [card], manualKeywords: card.tags.join('，') }, script, { title: card.title })
    setProject(nextProject)
    setCards((current) => current.map((item) => item.id === card.id ? { ...item, usedCount: Number(item.usedCount || 0) + 1, updatedAt: nowText() } : item))
    try { if (card.id) await apiPost(`/api/video/content-brain/mark-used/${card.id}`, {}, 30000) } catch {}
    goTab('pureai')
  }


  async function linkOpenClawLeads() {
    setBackendBusy('openclaw')
    setBackendError('')
    try {
      const res = await apiPost('/api/video/content-brain/link-openclaw-leads', { limit: 120, min_score: 55, status: 'pending' }, 120000)
      const next = normalizeServerCards(res)
      setInbox((current) => dedupe([...next, ...current]))
      setBackendStatus(`已从 OpenClaw 线索同步 ${next.length} 条待审核客户问题`)
    } catch (err: any) {
      setBackendError(err?.message || 'OpenClaw 线索同步失败')
    } finally {
      setBackendBusy('')
    }
  }

  async function exportBackendMarkdown() {
    try {
      const res = await apiPost('/api/video/content-brain/export-obsidian', { status: 'approved' }, 120000)
      if (res?.markdown) {
        const blob = new Blob([res.markdown], { type: 'text/markdown;charset=utf-8' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `ai-video-content-brain-${Date.now()}.md`
        a.click()
        URL.revokeObjectURL(url)
      } else {
        downloadMarkdown(cards.filter((card) => card.status === 'approved'))
      }
    } catch {
      downloadMarkdown(cards.filter((card) => card.status === 'approved'))
    }
  }

  function clearRejected() {
    setCards((current) => current.filter((card) => card.status !== 'rejected'))
  }

  function clearAllBrain() {
    if (!window.confirm('确认清空内容大脑和待审核？不会删除 R2/后端数据。')) return
    setCards([])
    setInbox([])
  }

  return (
    <section className="aiw-card aiw-contentBrain">
      <div className="aiw-hero">
        <div>
          <p className="aiw-eyebrow">CONTENT BRAIN / OBSIDIAN READY</p>
          <h2>内容大脑</h2>
          <p>把 OpenClaw 客户问题、同行采集、已生成文案和 Obsidian/Markdown 笔记沉淀成知识库；先审核，再进入视频创作。</p>
        </div>
        <span className="aiw-badge ok">已批准 {approved.length} 条 · 待审核 {pending.length} 条</span>
      </div>

      <div className="aiw-statusLine"><b>{backendStatus}</b>{backendBusy && <span>处理中：{backendBusy}</span>}{backendError && <em>{backendError}</em>}<button className="aiw-muted small" onClick={refreshBackendBrain}>刷新后端内容大脑</button></div>

      <div className="aiw-brainLoop">
        <div><b>1 OpenClaw</b><span>真实评论 / 线索问题</span></div>
        <div><b>2 判断入库</b><span>A/B线索、可复用问题、好钩子</span></div>
        <div><b>3 内容大脑</b><span>主题、钩子、客户问题、画面规则</span></div>
        <div><b>4 视频创作</b><span>反哺文案、关键词、镜头和 CTA</span></div>
      </div>

      <div className="aiw-stepGrid two">
        <section className="aiw-stepCard">
          <h3>导入 / 反哺</h3>
          <p>第一版先支持粘贴 Markdown/Obsidian 笔记；后续再接服务器 vault 路径或 Git 同步。</p>
          <textarea className="aiw-brainMarkdown" value={markdown} onChange={(e) => setMarkdown(e.target.value)} placeholder={'粘贴 Obsidian Markdown，例如：\n# 吉隆坡华人客户常问问题\n- 150万预算能买吗？\n- 哪些区域更适合出租？\n- 可以讲华语吗？'} />
          <div className="aiw-actions">
            <button className="aiw-primary" onClick={importMarkdown}>导入 Markdown 到待审核</button>
            <button className="aiw-muted" onClick={importCurrentProject}>从当前视频/线索生成待审核</button>
            <button className="aiw-muted" onClick={linkOpenClawLeads}>{backendBusy === 'openclaw' ? '同步中...' : '从 OpenClaw 线索同步'}</button>
            <button className="aiw-muted" onClick={() => goTab('leads')}>去 OpenClaw 找客户问题</button>
          </div>

          <div className="aiw-brainManual">
            <h4>手动新增一条知识</h4>
            <label>标题<input value={manualTitle} onChange={(e) => setManualTitle(e.target.value)} placeholder="例如：吉隆坡华语客户沟通点" /></label>
            <label>内容<textarea value={manualContent} onChange={(e) => setManualContent(e.target.value)} placeholder="写下客户问题、选题角度、画面规则或回复模板" /></label>
            <label>标签<input value={manualTags} onChange={(e) => setManualTags(e.target.value)} /></label>
            <button className="aiw-muted" onClick={addManualCard}>直接加入内容大脑</button>
          </div>
        </section>

        <section className="aiw-stepCard">
          <h3>待审核：该不该放进去？</h3>
          <p>不是所有生成内容都值得入库。只保留真实问题、高频问题、好钩子、可复用画面规则和高转化文案。</p>
          <div className="aiw-brainInbox">
            {pending.slice(0, 12).map((card) => (
              <article className="aiw-brainCard pending" key={card.id}>
                <div><b>{card.title}</b><span>{TYPE_LABELS[card.type]} · {card.source} · {card.score}</span></div>
                <p>{card.content.slice(0, 180)}</p>
                <em>{card.decisionReason}</em>
                <div className="aiw-chipRow">{card.tags.slice(0, 8).map((tag) => <span className="aiw-keywordPill" key={tag}>{tag}</span>)}</div>
                <div className="aiw-actions">
                  <button className="aiw-primary" onClick={() => setCardStatus(card, 'approved', '人工确认：值得进入内容大脑。')}>放进去</button>
                  <button className="aiw-muted" onClick={() => setCardStatus(card, 'rejected', '人工确认：暂不沉淀。')}>不放</button>
                  <button className="aiw-muted" onClick={() => useCardForVideo(card)}>直接做视频</button>
                </div>
              </article>
            ))}
            {!pending.length && <div className="aiw-empty">暂无待审核。可以从 OpenClaw、当前视频或 Markdown 导入。</div>}
          </div>
        </section>
      </div>

      <section className="aiw-stepCard">
        <div className="aiw-brainToolbar">
          <h3>知识库</h3>
          <div className="aiw-actions">
            <select value={filter} onChange={(e) => setFilter(e.target.value as any)}><option value="approved">已批准</option><option value="pending">待审核</option><option value="rejected">已拒绝</option><option value="all">全部</option></select>
            <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value as any)}><option value="all">全部类型</option>{Object.entries(TYPE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
            <button className="aiw-muted" onClick={exportBackendMarkdown}>导出 Obsidian Markdown</button>
            <button className="aiw-muted" onClick={clearRejected}>清理已拒绝</button>
            <button className="aiw-danger small" onClick={clearAllBrain}>清空内容大脑</button>
          </div>
        </div>

        <div className="aiw-brainGrid">
          {filteredCards.map((card) => (
            <article className={`aiw-brainCard ${card.status}`} key={card.id}>
              <div><b>{card.title}</b><span>{TYPE_LABELS[card.type]} · {card.source} · 用过 {card.usedCount || 0} 次</span></div>
              <p>{card.content.slice(0, 220)}</p>
              <div className="aiw-chipRow">{card.tags.slice(0, 8).map((tag) => <span className="aiw-keywordPill" key={tag}>{tag}</span>)}</div>
              <div className="aiw-actions">
                <button className="aiw-muted" onClick={() => useCardForVideo(card)}>带入视频创作</button>
                {card.status !== 'approved' && <button className="aiw-primary" onClick={() => setCardStatus(card, 'approved')}>批准</button>}
                {card.status !== 'rejected' && <button className="aiw-muted" onClick={() => setCardStatus(card, 'rejected')}>拒绝</button>}
              </div>
            </article>
          ))}
          {!filteredCards.length && <div className="aiw-empty">这个筛选下暂无内容。</div>}
        </div>
      </section>
    </section>
  )
}
