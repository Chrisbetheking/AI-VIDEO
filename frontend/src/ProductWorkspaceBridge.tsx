import React, { useEffect, useMemo, useState } from 'react'
import PureAIVideoPath from './PureAIVideoPath'
import DouyinAccountLibrary from './DouyinAccountLibrary'
import OpenClawWorkbench from './OpenClawWorkbench'
import { clearToken, getToken, maskToken, saveToken } from './aiVideoApi'

type Mode = 'none' | 'pure' | 'collector' | 'capture' | 'digital'

function targetModeFromText(text: string): Mode {
  const t = text.replace(/\s+/g, '')
  if (/(AI视频生产中心|一键生成中心|纯AI|AI视频)/.test(t)) return 'pure'
  if (/(同行采集|竞品账号库|行业爆点|抖音账号库)/.test(t)) return 'collector'
  if (/(获客自动化|OpenClaw|截流)/.test(t)) return 'capture'
  if (/(数字人)/.test(t)) return 'digital'
  return 'none'
}

function nearestSmallMenuText(target: HTMLElement | null) {
  if (!target) return ''
  if (['INPUT', 'TEXTAREA', 'SELECT', 'OPTION'].includes(target.tagName)) return ''
  let el: HTMLElement | null = target
  for (let i = 0; i < 6 && el; i += 1) {
    const txt = (el.textContent || '').replace(/\s+/g, ' ').trim()
    if (txt && txt.length <= 80) return txt
    el = el.parentElement
  }
  return ''
}

function DigitalHumanInternalPanel() {
  const [script, setScript] = useState('这是内部自用数字人口播片段，用来承接前面生成的文稿。')
  const seconds = Math.max(5, Math.ceil(script.length / 4.2))
  return (
    <section className="uxPanel digitalInternalPanel">
      <div className="uxHero">
        <div>
          <p className="uxEyebrow">DIGITAL HUMAN INTERNAL</p>
          <h2>数字人内部素材工作台</h2>
          <p>按内部自用素材处理，不再用“本人授权”作为阻断流程。这里负责把已生成文稿切成数字人口播片段，后续接数字人接口。</p>
        </div>
        <span className="uxGreenBadge">内部自用</span>
      </div>
      <div className="uxTwoCol">
        <label className="uxCard">数字人口播文稿<textarea value={script} onChange={(e) => setScript(e.target.value)} /></label>
        <div className="uxCard">
          <h3>生成建议</h3>
          <p>预计口播时长：{seconds}s</p>
          <p>建议：先用纯 AI / OpenClaw 面板生成文稿，再复制到这里生成数字人片段。</p>
          <p>素材来源：内部自用形象素材 / 已上传照片视频 / 已生成数字人片段。</p>
        </div>
      </div>
      <div className="uxNotice">后端数字人接口当前仍按已有能力调用。下一步应把这里接入数字人生成接口并把产物自动回填素材库。</div>
    </section>
  )
}

function modeTitle(mode: Mode) {
  if (mode === 'pure') return 'AI 自动生成中控'
  if (mode === 'collector') return '抖音自动采集'
  if (mode === 'capture') return 'OpenClaw 获客截流'
  if (mode === 'digital') return '数字人内部素材'
  return 'AI-VIDEO 自动化工作台'
}

export default function ProductWorkspaceBridge() {
  const [mode, setMode] = useState<Mode>('none')
  const [tokenBox, setTokenBox] = useState(false)
  const [tokenInput, setTokenInput] = useState(getToken())

  useEffect(() => {
    function applyHashMode() {
      const hash = window.location.hash || ''
      if (hash.includes('douyin-account-library')) setMode('collector')
      if (hash.includes('openclaw-workbench')) setMode('capture')
      if (hash.includes('pure-ai-video')) setMode('pure')
      if (hash.includes('digital-human')) setMode('digital')
    }
    applyHashMode()
    window.addEventListener('hashchange', applyHashMode)
    return () => window.removeEventListener('hashchange', applyHashMode)
  }, [])

  useEffect(() => {
    function onClick(event: MouseEvent) {
      const target = event.target as HTMLElement | null
      const text = nearestSmallMenuText(target)
      const next = targetModeFromText(text)
      if (next === 'none') return
      event.preventDefault()
      event.stopPropagation()
      setMode(next)
    }
    document.addEventListener('click', onClick, true)
    return () => document.removeEventListener('click', onClick, true)
  }, [])

  useEffect(() => {
    document.body.classList.toggle('uxModalOpen', mode !== 'none')
  }, [mode])

  const content = useMemo(() => {
    if (mode === 'pure') return <PureAIVideoPath />
    if (mode === 'collector') return <DouyinAccountLibrary />
    if (mode === 'capture') return <OpenClawWorkbench />
    if (mode === 'digital') return <DigitalHumanInternalPanel />
    return null
  }, [mode])

  if (mode === 'none') return null

  return (
    <div className="uxOverlay" role="dialog" aria-modal="true">
      <div className="uxShell">
        <header className="uxShellHeader">
          <div>
            <p>AI-VIDEO 自动化工作台</p>
            <h1>{modeTitle(mode)}</h1>
          </div>
          <div className="uxTopActions">
            <button className={mode === 'pure' ? 'active' : ''} onClick={() => setMode('pure')}>纯 AI 生成</button>
            <button className={mode === 'collector' ? 'active' : ''} onClick={() => setMode('collector')}>抖音采集</button>
            <button className={mode === 'capture' ? 'active' : ''} onClick={() => setMode('capture')}>OpenClaw 截流</button>
            <button className={mode === 'digital' ? 'active' : ''} onClick={() => setMode('digital')}>数字人</button>
            <button onClick={() => setTokenBox((v) => !v)}>Token：{maskToken()}</button>
            <button className="ghost" onClick={() => { setMode('none'); if (window.location.hash) window.history.replaceState(null, '', window.location.pathname) }}>关闭</button>
          </div>
        </header>

        {tokenBox && (
          <div className="uxTokenPanel">
            <label>AI-VIDEO API Token<input value={tokenInput} onChange={(e) => setTokenInput(e.target.value)} placeholder="粘贴 /root/ai-video-admin-token.txt 的内容" /></label>
            <button onClick={() => { saveToken(tokenInput); setTokenBox(false) }}>保存 Token</button>
            <button className="ghost" onClick={() => { clearToken(); setTokenInput('') }}>清空</button>
          </div>
        )}

        <main className="uxShellMain">{content}</main>
      </div>
    </div>
  )
}
