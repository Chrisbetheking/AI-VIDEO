import React, { useEffect, useMemo, useState } from 'react'
import {
  clearStoredToken,
  emptyProjectDraft,
  getStoredToken,
  maskToken,
  ProjectDraft,
  setStoredToken,
} from './aiVideoApi'
import PureAIVideoPath from './PureAIVideoPath'
import DouyinAccountLibrary from './DouyinAccountLibrary'
import OpenClawWorkbench from './OpenClawWorkbench'

type WorkspaceTab = 'pure' | 'douyin' | 'openclaw' | 'digital'

const WORKSPACE_HASHES: Record<string, WorkspaceTab> = {
  '#ai-video-workspace': 'pure',
  '#pure-ai-video': 'pure',
  '#douyin-account-library': 'douyin',
  '#douyin-collector': 'douyin',
  '#openclaw-workbench': 'openclaw',
  '#openclaw-capture': 'openclaw',
  '#digital-human-workspace': 'digital',
}

function targetTabFromText(text: string): WorkspaceTab | null {
  const t = text.replace(/\s+/g, '')
  if (!t) return null

  if (
    t.includes('AI视频生产中心') ||
    t.includes('一键生成中心') ||
    t.includes('纯AI') ||
    t.includes('生成中心')
  ) {
    return 'pure'
  }

  if (
    t.includes('同行采集') ||
    t.includes('竞品账号库') ||
    t.includes('抖音账号库') ||
    t.includes('抖音采集')
  ) {
    return 'douyin'
  }

  if (t.includes('获客自动化') || t.includes('OpenClaw') || t.includes('获客承接')) {
    return 'openclaw'
  }

  if (t.includes('数字人')) {
    return 'digital'
  }

  return null
}

function shouldInterceptClick(target: HTMLElement): WorkspaceTab | null {
  const candidate = target.closest('button, a, [role="button"], .nav-item, .sidebar-item, li, div')
  if (!(candidate instanceof HTMLElement)) return null

  const rect = candidate.getBoundingClientRect()
  const looksLikeLeftNav = rect.left < 420 && rect.width < 420
  const isHashLink = candidate instanceof HTMLAnchorElement && candidate.hash in WORKSPACE_HASHES

  if (!looksLikeLeftNav && !isHashLink) return null

  const text = candidate.innerText || candidate.textContent || ''
  return targetTabFromText(text)
}

function TokenPill() {
  const [token, setToken] = useState(getStoredToken())
  const [open, setOpen] = useState(false)

  function save() {
    const clean = setStoredToken(token)
    setToken(clean)
    setOpen(false)
  }

  function clear() {
    clearStoredToken()
    setToken('')
  }

  return (
    <div className="workspaceToken">
      <button type="button" onClick={() => setOpen((x) => !x)}>
        Token：{maskToken(token)}
      </button>
      {open && (
        <div className="workspaceTokenPanel">
          <label>
            AI-VIDEO API Token
            <input
              value={token}
              onChange={(event) => setToken(event.target.value)}
              placeholder="粘贴 /root/ai-video-admin-token.txt 里的管理 Token"
            />
          </label>
          <p>只保存在当前浏览器 localStorage，不再弹系统输入框。</p>
          <div>
            <button type="button" onClick={save}>
              保存
            </button>
            <button type="button" onClick={clear}>
              清空
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

function DigitalHumanInternalPanel({
  project,
  setProject,
  goTab,
}: {
  project: ProjectDraft
  setProject: (next: ProjectDraft) => void
  goTab: (next: WorkspaceTab) => void
}) {
  const canContinue = Boolean(project.script && project.segments.length)

  return (
    <section className="productPanel">
      <div className="productHero">
        <div>
          <p className="productEyebrow">DIGITAL HUMAN INTERNAL MODE</p>
          <h2>数字人内部素材工作台</h2>
          <p>
            这里按内部自用素材处理：先有文稿和分镜，再生成数字人口播片段，最后进入剪辑合成。不是空白页，也不再阻断式弹授权。
          </p>
        </div>
        <span className="productBadge">内部自用</span>
      </div>

      <div className="productGrid four">
        <div className="metricCard">
          <b>{project.script ? '已生成' : '未生成'}</b>
          <span>文稿状态</span>
        </div>
        <div className="metricCard">
          <b>{project.segments.length}</b>
          <span>口播分段</span>
        </div>
        <div className="metricCard">
          <b>{project.targetDuration}s</b>
          <span>目标长度</span>
        </div>
        <div className="metricCard">
          <b>{canContinue ? '可进入' : '先文稿'}</b>
          <span>下一步</span>
        </div>
      </div>

      <div className="productButtonRow">
        <button type="button" onClick={() => goTab('pure')}>
          去生成文稿/分镜
        </button>
        <button type="button" className="green" disabled={!canContinue}>
          生成数字人口播片段
        </button>
      </div>

      {project.script && (
        <div className="resultCard">
          <h3>当前文稿</h3>
          <pre>{project.script}</pre>
        </div>
      )}

      <div className="productNotice">
        数字人这一步暂时先作为内部素材节点：输出片段后进入“配音/剪辑/字幕”链路，不单独跳出成片。
      </div>
    </section>
  )
}

export default function ProductWorkspaceBridge() {
  const [open, setOpen] = useState(false)
  const [tab, setTab] = useState<WorkspaceTab>('pure')
  const [project, setProjectState] = useState<ProjectDraft>(() => {
    try {
      const raw = localStorage.getItem('ai_video_project_draft')
      return raw ? { ...emptyProjectDraft(), ...JSON.parse(raw) } : emptyProjectDraft()
    } catch {
      return emptyProjectDraft()
    }
  })

  const title = useMemo(() => {
    if (tab === 'pure') return 'AI 自动生成中控'
    if (tab === 'douyin') return '抖音自动采集任务中心'
    if (tab === 'openclaw') return 'OpenClaw 获客承接'
    return '数字人内部素材'
  }, [tab])

  function setProject(next: ProjectDraft) {
    setProjectState(next)
    localStorage.setItem('ai_video_project_draft', JSON.stringify(next))
  }

  function openTab(next: WorkspaceTab) {
    setTab(next)
    setOpen(true)
  }

  useEffect(() => {
    const hashTab = WORKSPACE_HASHES[window.location.hash]
    if (hashTab) openTab(hashTab)

    const onHash = () => {
      const next = WORKSPACE_HASHES[window.location.hash]
      if (next) openTab(next)
    }

    const onClick = (event: MouseEvent) => {
      const target = event.target
      if (!(target instanceof HTMLElement)) return

      const next = shouldInterceptClick(target)
      if (!next) return

      event.preventDefault()
      event.stopPropagation()
      openTab(next)
    }

    window.addEventListener('hashchange', onHash)
    document.addEventListener('click', onClick, true)

    return () => {
      window.removeEventListener('hashchange', onHash)
      document.removeEventListener('click', onClick, true)
    }
  }, [])

  if (!open) return null

  return (
    <div className="workspaceOverlay" role="dialog" aria-modal="true">
      <div className="workspaceShell">
        <header className="workspaceHeader">
          <div>
            <p>AI-VIDEO 工程化工作台</p>
            <h1>{title}</h1>
          </div>
          <div className="workspaceTabs">
            <button type="button" className={tab === 'pure' ? 'active' : ''} onClick={() => setTab('pure')}>
              纯 AI / 生成
            </button>
            <button type="button" className={tab === 'douyin' ? 'active' : ''} onClick={() => setTab('douyin')}>
              抖音采集
            </button>
            <button type="button" className={tab === 'openclaw' ? 'active' : ''} onClick={() => setTab('openclaw')}>
              获客承接
            </button>
            <button type="button" className={tab === 'digital' ? 'active' : ''} onClick={() => setTab('digital')}>
              数字人
            </button>
            <TokenPill />
            <button type="button" className="ghost" onClick={() => setOpen(false)}>
              关闭
            </button>
          </div>
        </header>

        <main className="workspaceBody">
          {tab === 'pure' && <PureAIVideoPath project={project} setProject={setProject} goTab={openTab} />}
          {tab === 'douyin' && <DouyinAccountLibrary project={project} setProject={setProject} goTab={openTab} />}
          {tab === 'openclaw' && <OpenClawWorkbench project={project} setProject={setProject} goTab={openTab} />}
          {tab === 'digital' && <DigitalHumanInternalPanel project={project} setProject={setProject} goTab={openTab} />}
        </main>
      </div>
    </div>
  )
}
