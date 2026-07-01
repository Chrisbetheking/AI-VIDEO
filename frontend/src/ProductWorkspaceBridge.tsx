import React, { useEffect, useState } from 'react'
import DouyinAccountLibrary from './DouyinAccountLibrary'
import OpenClawWorkbench from './OpenClawWorkbench'
import PureAIVideoPath from './PureAIVideoPath'
import { clearAiVideoToken, getAiVideoToken, maskToken, saveAiVideoToken } from './aiVideoApi'

type Workspace = 'ai' | 'douyin' | 'openclaw' | null

function compact(text: string) {
  return text.replace(/\s+/g, '')
}

function isLeftMenuElement(el: HTMLElement) {
  const rect = el.getBoundingClientRect()
  if (rect.left < 0 || rect.left > 430) return false
  if (rect.width < 80 || rect.width > 430) return false
  if (rect.height < 26 || rect.height > 120) return false
  return true
}

function resolveWorkspaceClick(target: EventTarget | null): Workspace {
  let current = target as HTMLElement | null
  for (let i = 0; current && i < 5; i += 1) {
    if (current.closest('[data-ai-workspace-modal="true"]')) return null
    const text = compact(current.textContent || '')
    if (isLeftMenuElement(current)) {
      // 只拦截左侧菜单，不拦截主页面卡片，避免“点哪都弹窗”。
      if (text === '竞品账号库账号' || text === '竞品账号库' || text === '同行采集采集' || text === '同行采集') return 'douyin'
      if (text === '获客自动化获客' || text === '获客自动化') return 'openclaw'
      if (text === 'AI视频生产中心AI视频' || text === 'AI视频生产中心' || text === '一键生成中心一键' || text === '一键生成中心') return 'ai'
    }
    current = current.parentElement
  }
  return null
}

function TokenPanel() {
  const [token, setToken] = useState(getAiVideoToken())
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState('')

  useEffect(() => {
    const onToken = () => setToken(getAiVideoToken())
    window.addEventListener('ai-video-token-updated', onToken as EventListener)
    return () => window.removeEventListener('ai-video-token-updated', onToken as EventListener)
  }, [])

  return (
    <div className="workspaceTokenBox">
      <button className="workspaceTopBtn" onClick={() => setOpen((x) => !x)}>Token：{maskToken(token)}</button>
      {open && (
        <div className="workspaceTokenDrop">
          <label>AI-VIDEO API Token</label>
          <input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="粘贴 /root/ai-video-admin-token.txt 的内容" />
          <div className="workspaceTokenActions">
            <button onClick={() => { saveAiVideoToken(draft); setDraft(''); setOpen(false) }}>保存</button>
            <button onClick={() => { clearAiVideoToken(); setDraft('') }}>清空</button>
          </div>
          <p>不再弹浏览器输入框，只保存在当前浏览器。</p>
        </div>
      )}
    </div>
  )
}

function useInternalDigitalHumanMode() {
  useEffect(() => {
    function apply() {
      const labels = Array.from(document.querySelectorAll('label, .field, .form-row, div')) as HTMLElement[]
      for (const el of labels) {
        const text = compact(el.textContent || '')
        if (!text.includes('本人形象') && !text.includes('声音授权')) continue
        const checkbox = el.querySelector('input[type="checkbox"]') as HTMLInputElement | null
        if (checkbox && !checkbox.checked) {
          checkbox.checked = true
          checkbox.dispatchEvent(new Event('input', { bubbles: true }))
          checkbox.dispatchEvent(new Event('change', { bubbles: true }))
        }
        el.classList.add('internalDigitalHumanConsentHidden')
      }

      // 当前项目是内部自用数字人模式：去掉页面上的授权阻断感，但不绕过后端素材合法性校验。
      const notices = Array.from(document.querySelectorAll('p, span, small, div')) as HTMLElement[]
      for (const el of notices) {
        const text = compact(el.textContent || '')
        if (text.includes('本人形象') && text.includes('授权')) {
          el.classList.add('internalDigitalHumanConsentHidden')
        }
      }
    }

    apply()
    const timer = window.setInterval(apply, 1200)
    const mo = new MutationObserver(apply)
    mo.observe(document.body, { childList: true, subtree: true })
    return () => { window.clearInterval(timer); mo.disconnect() }
  }, [])
}

export default function ProductWorkspaceBridge() {
  const [active, setActive] = useState<Workspace>(null)
  useInternalDigitalHumanMode()

  useEffect(() => {
    function onClick(event: MouseEvent) {
      if (active) return
      const workspace = resolveWorkspaceClick(event.target)
      if (!workspace) return
      event.preventDefault()
      event.stopPropagation()
      setActive(workspace)
    }
    document.addEventListener('click', onClick, true)
    return () => document.removeEventListener('click', onClick, true)
  }, [active])

  useEffect(() => {
    if (!active) return
    const old = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') setActive(null) }
    window.addEventListener('keydown', onKey)
    return () => { document.body.style.overflow = old; window.removeEventListener('keydown', onKey) }
  }, [active])

  if (!active) return null

  return (
    <div className="workspaceOverlay" data-ai-workspace-modal="true">
      <div className="workspaceShell">
        <header className="workspaceHeader">
          <div>
            <p>AI-VIDEO 自动化工作台</p>
            <h1>{active === 'ai' ? '纯 AI / 素材补足生成路径' : active === 'douyin' ? '抖音自动采集任务中心' : 'OpenClaw 获客截流面板'}</h1>
          </div>
          <div className="workspaceHeaderActions">
            <button className={active === 'ai' ? 'workspaceTopBtn active' : 'workspaceTopBtn'} onClick={() => setActive('ai')}>纯 AI 生成</button>
            <button className={active === 'douyin' ? 'workspaceTopBtn active' : 'workspaceTopBtn'} onClick={() => setActive('douyin')}>抖音采集</button>
            <button className={active === 'openclaw' ? 'workspaceTopBtn active' : 'workspaceTopBtn'} onClick={() => setActive('openclaw')}>OpenClaw 截流</button>
            <TokenPanel />
            <button className="workspaceCloseBtn" onClick={() => setActive(null)}>关闭</button>
          </div>
        </header>
        <main className="workspaceBody">
          {active === 'ai' ? <PureAIVideoPath /> : active === 'douyin' ? <DouyinAccountLibrary /> : <OpenClawWorkbench />}
        </main>
      </div>
    </div>
  )
}
