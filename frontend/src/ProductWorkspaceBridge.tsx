import React, { useEffect, useMemo, useState } from 'react'
import DouyinAccountLibrary from './DouyinAccountLibrary'
import OpenClawWorkbench from './OpenClawWorkbench'
import PureAIVideoPath from './PureAIVideoPath'
import { getStoredToken, setStoredToken, clearStoredToken, maskToken } from './aiVideoApi'

type PanelKey = 'none' | 'douyin' | 'openclaw' | 'pureai' | 'digitalHuman'

const HASH_TO_PANEL: Record<string, PanelKey> = {
  '#douyin-account-library': 'douyin',
  '#douyin-collector': 'douyin',
  '#openclaw-workbench': 'openclaw',
  '#openclaw-capture': 'openclaw',
  '#pure-ai-video': 'pureai',
  '#full-ai-video': 'pureai',
  '#digital-human-safe': 'digitalHuman',
}

function matchPanelFromText(text: string): PanelKey {
  const t = text.replace(/\s+/g, '')
  if (t.includes('竞品账号库') || t.includes('同行采集') || t.includes('抖音账号库')) return 'douyin'
  if (t.includes('获客自动化') || t.includes('OpenClaw') || t.includes('截流')) return 'openclaw'
  if (t.includes('AI视频生产中心') || t.includes('一键生成中心') || t.includes('纯AI生成')) return 'pureai'
  if (t.includes('数字人')) return 'digitalHuman'
  return 'none'
}

function InternalDigitalHumanPanel() {
  return (
    <section className="uxPanelCard">
      <div className="uxHeroRow">
        <div>
          <p className="uxEyebrow">DIGITAL HUMAN / INTERNAL MODE</p>
          <h2>数字人内部素材工作台</h2>
          <p>这里改成自用素材逻辑，不再拿“本人授权”做阻断。上传形象素材、配音脚本后，系统优先走内部数字人片段；如果当前后端数字人接口异常，先不让页面白屏。</p>
        </div>
        <span className="uxBadge">内部自用</span>
      </div>
      <div className="uxGrid3">
        <div className="uxStat"><b>1</b><span>选择形象素材</span><p>上传照片/口播视频，作为内部素材。</p></div>
        <div className="uxStat"><b>2</b><span>绑定配音分段</span><p>按文案段落生成数字人口播。</p></div>
        <div className="uxStat"><b>3</b><span>进入剪辑合成</span><p>数字人片段作为素材进入合成。</p></div>
      </div>
      <div className="uxNotice">当前先接管白屏入口。后续要做后端数字人真实任务状态、失败重试和素材版本管理。</div>
    </section>
  )
}

function panelTitle(panel: PanelKey) {
  if (panel === 'douyin') return '抖音自动采集任务中心'
  if (panel === 'openclaw') return 'OpenClaw 获客截流面板'
  if (panel === 'pureai') return '纯 AI 视频生成路径'
  if (panel === 'digitalHuman') return '数字人内部素材工作台'
  return ''
}

export default function ProductWorkspaceBridge() {
  const [panel, setPanel] = useState<PanelKey>(() => HASH_TO_PANEL[window.location.hash] || 'none')
  const [token, setToken] = useState(getStoredToken())
  const [showToken, setShowToken] = useState(false)

  const headerToken = useMemo(() => maskToken(token), [token])

  function openPanel(next: PanelKey) {
    if (next === 'none') return
    setPanel(next)
    const hash = next === 'douyin' ? '#douyin-collector' : next === 'openclaw' ? '#openclaw-capture' : next === 'pureai' ? '#pure-ai-video' : '#digital-human-safe'
    if (window.location.hash !== hash) window.history.replaceState(null, '', hash)
  }

  function closePanel() {
    setPanel('none')
    if (window.location.hash) window.history.replaceState(null, '', window.location.pathname)
  }

  useEffect(() => {
    const onHash = () => {
      const next = HASH_TO_PANEL[window.location.hash] || 'none'
      setPanel(next)
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null
      if (!target) return

      const interactive = target.closest('button, a, [role="button"], .module-card, .nav-item, .sidebar-item, li, div') as HTMLElement | null
      if (!interactive) return

      // 只拦截左侧栏点击：防止点主内容区任何窗口都跳弹层。
      if (event.clientX > 420) return

      const text = (interactive.textContent || '').trim()
      const next = matchPanelFromText(text)
      if (next === 'none') return

      event.preventDefault()
      event.stopPropagation()
      openPanel(next)
    }

    document.addEventListener('click', onClick, true)
    return () => document.removeEventListener('click', onClick, true)
  }, [])

  useEffect(() => {
    const tick = () => setToken(getStoredToken())
    window.addEventListener('storage', tick)
    return () => window.removeEventListener('storage', tick)
  }, [])

  if (panel === 'none') return null

  return (
    <div className="uxOverlay" role="dialog" aria-modal="true">
      <div className="uxModal">
        <header className="uxModalHeader">
          <div>
            <p>AI-VIDEO 自动化工作台</p>
            <h1>{panelTitle(panel)}</h1>
          </div>
          <div className="uxHeaderActions">
            <button className={panel === 'pureai' ? 'active' : ''} onClick={() => openPanel('pureai')}>纯 AI 生成</button>
            <button className={panel === 'douyin' ? 'active' : ''} onClick={() => openPanel('douyin')}>抖音采集</button>
            <button className={panel === 'openclaw' ? 'active' : ''} onClick={() => openPanel('openclaw')}>OpenClaw 截流</button>
            <button className={panel === 'digitalHuman' ? 'active' : ''} onClick={() => openPanel('digitalHuman')}>数字人</button>
            <button onClick={() => setShowToken((v) => !v)}>Token：{headerToken}</button>
            <button className="close" onClick={closePanel}>关闭</button>
          </div>
        </header>

        {showToken && (
          <div className="uxTokenBar">
            <label>
              AI-VIDEO API Token
              <input
                type="password"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                placeholder="粘贴 /root/ai-video-admin-token.txt 里的后台 Token"
              />
            </label>
            <button onClick={() => { setStoredToken(token); setToken(getStoredToken()); setShowToken(false) }}>保存 Token</button>
            <button className="ghost" onClick={() => { clearStoredToken(); setToken('') }}>清空</button>
          </div>
        )}

        <main className="uxModalBody">
          {panel === 'pureai' && <PureAIVideoPath />}
          {panel === 'douyin' && <DouyinAccountLibrary />}
          {panel === 'openclaw' && <OpenClawWorkbench />}
          {panel === 'digitalHuman' && <InternalDigitalHumanPanel />}
        </main>
      </div>
    </div>
  )
}
