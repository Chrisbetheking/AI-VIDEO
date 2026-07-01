import React, { useEffect, useState } from 'react'
import DouyinAccountLibrary from './DouyinAccountLibrary'
import OpenClawWorkbench from './OpenClawWorkbench'
import { clearAiVideoToken, getAiVideoToken, maskToken, saveAiVideoToken } from './aiVideoApi'

type Workspace = 'douyin' | 'openclaw' | null

type ResolvedClick = {
  workspace: Exclude<Workspace, null>
  element: HTMLElement
}

function normalizeText(text: string) {
  return text.replace(/\s+/g, '')
}

function resolveWorkspaceClick(target: EventTarget | null): ResolvedClick | null {
  let current = target as HTMLElement | null

  for (let i = 0; current && i < 7; i += 1) {
    if (current.closest('[data-ai-workspace-modal="true"]')) return null

    const rect = current.getBoundingClientRect()
    const text = normalizeText(current.textContent || '')
    const looksLikeLeftNav = rect.left >= 0 && rect.left < 430 && rect.width > 80 && rect.width < 430 && rect.height > 28 && rect.height < 110

    if (looksLikeLeftNav) {
      if (
        text === '竞品账号库账号' ||
        text === '竞品账号库' ||
        text === '同行采集采集' ||
        text === '同行采集' ||
        text === '抖音账号库' ||
        text.includes('竞品账号库')
      ) {
        return { workspace: 'douyin', element: current }
      }

      if (
        text === '获客自动化获客' ||
        text === '获客自动化' ||
        text === 'OpenClaw工作台' ||
        text === 'OpenClaw截流' ||
        text.includes('获客自动化')
      ) {
        return { workspace: 'openclaw', element: current }
      }
    }

    current = current.parentElement
  }

  return null
}

function TokenPanel() {
  const [token, setToken] = useState(getAiVideoToken())
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')

  useEffect(() => {
    const onToken = () => setToken(getAiVideoToken())
    window.addEventListener('ai-video-token-updated', onToken as EventListener)
    return () => window.removeEventListener('ai-video-token-updated', onToken as EventListener)
  }, [])

  return (
    <div className="workspaceTokenBox">
      <button className="workspaceTopBtn" onClick={() => setEditing((x) => !x)}>
        Token：{maskToken(token)}
      </button>
      {editing && (
        <div className="workspaceTokenDrop">
          <label>AI-VIDEO API Token</label>
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="粘贴 /root/ai-video-admin-token.txt 里的管理 Token"
          />
          <div className="workspaceTokenActions">
            <button
              onClick={() => {
                saveAiVideoToken(draft)
                setDraft('')
                setEditing(false)
              }}
            >
              保存
            </button>
            <button
              onClick={() => {
                clearAiVideoToken()
                setDraft('')
              }}
            >
              清空
            </button>
          </div>
          <p>不会再弹浏览器输入框，只保存在当前浏览器。</p>
        </div>
      )}
    </div>
  )
}

export default function ProductWorkspaceBridge() {
  const [active, setActive] = useState<Workspace>(null)

  useEffect(() => {
    function onClick(event: MouseEvent) {
      if (active) return
      const resolved = resolveWorkspaceClick(event.target)
      if (!resolved) return
      event.preventDefault()
      event.stopPropagation()
      setActive(resolved.workspace)
    }

    document.addEventListener('click', onClick, true)
    return () => document.removeEventListener('click', onClick, true)
  }, [active])

  useEffect(() => {
    if (!active) return
    const oldOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setActive(null)
    }
    window.addEventListener('keydown', onKey)
    return () => {
      document.body.style.overflow = oldOverflow
      window.removeEventListener('keydown', onKey)
    }
  }, [active])

  if (!active) return null

  return (
    <div className="workspaceOverlay" data-ai-workspace-modal="true">
      <div className="workspaceShell">
        <header className="workspaceHeader">
          <div>
            <p>AI-VIDEO 自动化工作台</p>
            <h1>{active === 'douyin' ? '抖音自动采集任务中心' : 'OpenClaw 获客截流面板'}</h1>
          </div>
          <div className="workspaceHeaderActions">
            <button className={active === 'douyin' ? 'workspaceTopBtn active' : 'workspaceTopBtn'} onClick={() => setActive('douyin')}>
              抖音采集
            </button>
            <button className={active === 'openclaw' ? 'workspaceTopBtn active' : 'workspaceTopBtn'} onClick={() => setActive('openclaw')}>
              OpenClaw 截流
            </button>
            <TokenPanel />
            <button className="workspaceCloseBtn" onClick={() => setActive(null)}>
              关闭
            </button>
          </div>
        </header>
        <main className="workspaceBody">{active === 'douyin' ? <DouyinAccountLibrary /> : <OpenClawWorkbench />}</main>
      </div>
    </div>
  )
}
