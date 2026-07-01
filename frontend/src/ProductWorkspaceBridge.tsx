import React, { useEffect, useMemo, useState } from 'react'
import PureAIVideoPath from './PureAIVideoPath'
import DouyinAccountLibrary from './DouyinAccountLibrary'
import OpenClawWorkbench from './OpenClawWorkbench'
import {
  clearStoredToken,
  emptyProjectDraft,
  getStoredToken,
  maskToken,
  ProjectDraft,
  setStoredToken,
  WorkspaceTab,
} from './aiVideoApi'

const DRAFT_KEY = 'ai_video_engineering_project_draft_v15'

function loadDraft(): ProjectDraft {
  try {
    const raw = localStorage.getItem(DRAFT_KEY)
    return raw ? { ...emptyProjectDraft(), ...JSON.parse(raw) } : emptyProjectDraft()
  } catch {
    return emptyProjectDraft()
  }
}

function saveDraft(draft: ProjectDraft) {
  localStorage.setItem(DRAFT_KEY, JSON.stringify(draft))
}

function tabFromHash(hash: string): WorkspaceTab | null {
  if (['#pure-ai-video', '#full-ai-video', '#one-click-video'].includes(hash)) return 'pureai'
  if (['#douyin-collector', '#douyin-account-library', '#competitor-collector'].includes(hash)) return 'collect'
  if (['#openclaw-capture', '#openclaw-workbench', '#lead-acquisition'].includes(hash)) return 'leads'
  if (['#digital-human-safe', '#digital-human-workspace'].includes(hash)) return 'digital'
  return null
}

function tabHash(tab: WorkspaceTab) {
  if (tab === 'pureai') return '#pure-ai-video'
  if (tab === 'collect') return '#douyin-collector'
  if (tab === 'leads') return '#openclaw-capture'
  return '#digital-human-workspace'
}

function tabTitle(tab: WorkspaceTab) {
  if (tab === 'pureai') return 'AI 自动生成中控'
  if (tab === 'collect') return '抖音自动采集中控'
  if (tab === 'leads') return 'OpenClaw 获客承接中控'
  return '数字人素材中控'
}

function matchTabFromText(text: string): WorkspaceTab | null {
  const t = text.replace(/\s+/g, '')
  if (t.includes('AI视频生产中心') || t.includes('一键生成中心') || t.includes('纯AI生成')) return 'pureai'
  if (t.includes('同行采集') || t.includes('竞品账号库') || t.includes('抖音账号库')) return 'collect'
  if (t.includes('获客自动化') || t.includes('OpenClaw') || t.includes('截流')) return 'leads'
  if (t.includes('数字人')) return 'digital'
  return null
}

function isLeftRailNode(el: HTMLElement) {
  const rect = el.getBoundingClientRect()
  return rect.left <= 430 && rect.width <= 460
}

function normalizeLeftRail() {
  const nodes = Array.from(document.querySelectorAll<HTMLElement>('button, a, li, div'))
  nodes.forEach((el) => {
    if (!isLeftRailNode(el)) return
    const text = (el.textContent || '').replace(/\s+/g, '')
    if (!text) return

    if (text.includes('行业爆点')) {
      const card = el.closest<HTMLElement>('li, button, a, .module-card, .nav-item, .sidebar-item, div')
      if (card && card !== document.body) card.dataset.aiVideoLegacyHidden = 'true'
    }

    const tab = matchTabFromText(text)
    if (tab) el.dataset.aiVideoBridgeEntry = tab
  })
}

function DigitalHumanPanel({
  project,
  setProject,
  goTab,
}: {
  project: ProjectDraft
  setProject: (p: ProjectDraft) => void
  goTab: (tab: WorkspaceTab) => void
}) {
  return (
    <section className="aiw-card">
      <div className="aiw-hero">
        <div>
          <p className="aiw-eyebrow">DIGITAL HUMAN / INTERNAL MATERIAL MODE</p>
          <h2>数字人内部素材路径</h2>
          <p>数字人作为内部素材片段使用：先有文稿和分镜，再生成或选择数字人口播片段，最后进入剪辑合成。</p>
        </div>
        <span className="aiw-badge ok">内部自用素材</span>
      </div>

      <div className="aiw-flow">
        <div>
          <b>1. 文稿前置</b>
          <span>{project.script ? '已有文稿' : '先去纯 AI 生成文稿'}</span>
        </div>
        <div>
          <b>2. 形象素材</b>
          <span>上传照片/口播视频，作为内部素材源</span>
        </div>
        <div>
          <b>3. 剪辑承接</b>
          <span>数字人片段进入素材序列，不单独孤立</span>
        </div>
      </div>

      <div className="aiw-form two">
        <label>
          数字人角色备注
          <input
            value={project.digitalHumanRole || ''}
            onChange={(e) => setProject({ ...project, digitalHumanRole: e.target.value })}
            placeholder="例如：房产顾问口播"
          />
        </label>
        <label>
          生成模式
          <select
            value={project.digitalHumanMode || 'internal_clip'}
            onChange={(e) => setProject({ ...project, digitalHumanMode: e.target.value })}
          >
            <option value="internal_clip">内部素材片段</option>
            <option value="placeholder">先生成占位片段</option>
            <option value="skip">本条视频不用数字人</option>
          </select>
        </label>
      </div>

      {!project.script && (
        <div className="aiw-info">没有文稿时不生成数字人片段。先到「纯 AI 生成」把文稿和分镜出来。</div>
      )}

      <div className="aiw-actions">
        <button className="aiw-primary" onClick={() => goTab('pureai')}>
          去生成文稿/分镜
        </button>
        <button className="aiw-muted" disabled={!project.script}>
          把数字人加入剪辑素材
        </button>
      </div>
    </section>
  )
}

export default function ProductWorkspaceBridge() {
  const initialTab = tabFromHash(window.location.hash) || 'pureai'
  const [panel, setPanel] = useState<'closed' | 'open'>(() => (tabFromHash(window.location.hash) ? 'open' : 'closed'))
  const [tab, setTab] = useState<WorkspaceTab>(initialTab)
  const [project, setProjectState] = useState<ProjectDraft>(loadDraft)
  const [token, setToken] = useState(getStoredToken())
  const [showToken, setShowToken] = useState(false)

  const tokenLabel = useMemo(() => maskToken(token), [token])

  function setProject(next: ProjectDraft) {
    setProjectState(next)
    saveDraft(next)
  }

  function open(next: WorkspaceTab) {
    setTab(next)
    setPanel('open')
    const hash = tabHash(next)
    if (window.location.hash !== hash) window.history.replaceState(null, '', hash)
  }

  function close() {
    setPanel('closed')
    if (window.location.hash) window.history.replaceState(null, '', window.location.pathname)
  }

  useEffect(() => {
    normalizeLeftRail()
    const timer = window.setInterval(normalizeLeftRail, 1200)
    return () => window.clearInterval(timer)
  }, [])

  useEffect(() => {
    const onHash = () => {
      const next = tabFromHash(window.location.hash)
      if (next) open(next)
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  useEffect(() => {
    const onEsc = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close()
    }
    window.addEventListener('keydown', onEsc)
    return () => window.removeEventListener('keydown', onEsc)
  }, [])

  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null
      if (!target || event.clientX > 430) return

      const candidate = target.closest<HTMLElement>(
        '[data-ai-video-bridge-entry], button, a, [role="button"], li, .module-card, .nav-item, .sidebar-item',
      )
      if (!candidate || !isLeftRailNode(candidate)) return

      const explicit = candidate.dataset.aiVideoBridgeEntry as WorkspaceTab | undefined
      const next = explicit || matchTabFromText(candidate.textContent || '')
      if (!next) return

      event.preventDefault()
      event.stopPropagation()
      open(next)
    }

    document.addEventListener('click', onClick, true)
    return () => document.removeEventListener('click', onClick, true)
  }, [])

  if (panel === 'closed') return null

  return (
    <div className="aiw-overlay" role="dialog" aria-modal="true">
      <div className="aiw-shell">
        <header className="aiw-header">
          <div>
            <p>AI-VIDEO 工程化工作台</p>
            <h1>{tabTitle(tab)}</h1>
          </div>
          <div className="aiw-tabs">
            <button className={tab === 'pureai' ? 'active' : ''} onClick={() => open('pureai')}>
              纯 AI / 生成
            </button>
            <button className={tab === 'collect' ? 'active' : ''} onClick={() => open('collect')}>
              抖音采集
            </button>
            <button className={tab === 'leads' ? 'active' : ''} onClick={() => open('leads')}>
              获客承接
            </button>
            <button className={tab === 'digital' ? 'active' : ''} onClick={() => open('digital')}>
              数字人
            </button>
            <div className="aiw-token">
              <button onClick={() => setShowToken((v) => !v)}>Token：{tokenLabel}</button>
              {showToken && (
                <div className="aiw-tokenDrop">
                  <label>
                    AI-VIDEO API Token
                    <input value={token} onChange={(e) => setToken(e.target.value)} placeholder="粘贴后台 Token" />
                  </label>
                  <div className="aiw-tokenActions">
                    <button
                      onClick={() => {
                        setStoredToken(token)
                        setToken(getStoredToken())
                        setShowToken(false)
                      }}
                    >
                      保存
                    </button>
                    <button
                      onClick={() => {
                        clearStoredToken()
                        setToken('')
                      }}
                    >
                      清空
                    </button>
                  </div>
                </div>
              )}
            </div>
            <button className="aiw-close" onClick={close}>
              关闭
            </button>
          </div>
        </header>

        <main className="aiw-body">
          {tab === 'pureai' && <PureAIVideoPath project={project} setProject={setProject} goTab={open} />}
          {tab === 'collect' && <DouyinAccountLibrary project={project} setProject={setProject} goTab={open} />}
          {tab === 'leads' && <OpenClawWorkbench project={project} setProject={setProject} goTab={open} />}
          {tab === 'digital' && <DigitalHumanPanel project={project} setProject={setProject} goTab={open} />}
        </main>
      </div>
    </div>
  )
}
