import React, { useEffect, useState } from 'react'
import DouyinAccountLibrary from './DouyinAccountLibrary'
import OpenClawWorkbench from './OpenClawWorkbench'
import { clearAiVideoToken, getAiVideoToken, maskToken, saveAiVideoToken } from './aiVideoApi'

type Workspace = 'douyin' | 'openclaw' | null

function findTextTarget(node: EventTarget | null): HTMLElement | null {
  let current = node as HTMLElement | null
  for (let i = 0; current && i < 8; i += 1) {
    if (current.dataset?.aiWorkspace) return null
    const text = (current.textContent || '').replace(/\s+/g, '')
    if (text) {
      if (text.includes('抖音账号库') || text.includes('竞品账号库') || text.includes('同行采集')) return current
      if (text.includes('OpenClaw') || text.includes('获客自动化')) return current
    }
    current = current.parentElement
  }
  return null
}

export default function ProductWorkspaceBridge() {
  const [active, setActive] = useState<Workspace>(null)
  const [token, setToken] = useState(getAiVideoToken())
  const [editingToken, setEditingToken] = useState(false)
  const [draftToken, setDraftToken] = useState('')

  useEffect(() => {
    const onToken = () => setToken(getAiVideoToken())
    window.addEventListener('ai-video-token-updated', onToken as EventListener)
    return () => window.removeEventListener('ai-video-token-updated', onToken as EventListener)
  }, [])

  useEffect(() => {
    function onClick(event: MouseEvent) {
      if (active) return
      const target = findTextTarget(event.target)
      if (!target) return
      const text = (target.textContent || '').replace(/\s+/g, '')
      if (text.includes('抖音账号库') || text.includes('竞品账号库') || text.includes('同行采集')) {
        event.preventDefault()
        event.stopPropagation()
        setActive('douyin')
        return
      }
      if (text.includes('OpenClaw') || text.includes('获客自动化')) {
        event.preventDefault()
        event.stopPropagation()
        setActive('openclaw')
      }
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
    <div className="workspaceOverlay" data-ai-workspace="true">
      <div className="workspaceShell">
        <header className="workspaceHeader">
          <div>
            <p>AI-VIDEO 自动化工作台</p>
            <h2>{active === 'douyin' ? '抖音账号目标池' : 'OpenClaw 获客截流面板'}</h2>
          </div>
          <div className="workspaceHeaderActions">
            <button className={active === 'douyin' ? 'active' : ''} onClick={() => setActive('douyin')}>抖音账号库</button>
            <button className={active === 'openclaw' ? 'active' : ''} onClick={() => setActive('openclaw')}>OpenClaw 截流</button>
            <button onClick={() => setEditingToken((x) => !x)}>Token：{maskToken(token)}</button>
            <button className="ghost" onClick={() => setActive(null)}>关闭</button>
          </div>
        </header>

        {editingToken && (
          <section className="workspaceTokenBox">
            <label>
              AI-VIDEO API Token
              <input
                type="password"
                autoComplete="off"
                placeholder={token ? '已保存，重新输入可覆盖' : '粘贴 /root/ai-video-admin-token.txt 里的 Token'}
                value={draftToken}
                onChange={(e) => setDraftToken(e.target.value)}
              />
            </label>
            <button onClick={() => { saveAiVideoToken(draftToken); setDraftToken(''); setToken(getAiVideoToken()); setEditingToken(false) }}>保存</button>
            <button className="ghost" onClick={() => { clearAiVideoToken(); setToken(''); setDraftToken('') }}>清空</button>
          </section>
        )}

        <main className="workspaceBody">
          {active === 'douyin' ? <DouyinAccountLibrary /> : <OpenClawWorkbench />}
        </main>
      </div>
    </div>
  )
}
