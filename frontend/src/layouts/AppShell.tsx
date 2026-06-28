import React from 'react'

export type NavId = 'dashboard' | 'create-video' | 'leads' | 'assets' | 'providers'

const NAV: { id: NavId; label: string; icon: string; emoji: string }[] = [
  { id: 'dashboard', label: 'Dashboard', icon: '📊', emoji: '' },
  { id: 'create-video', label: 'Create Video', icon: '🎬', emoji: 'AI' },
  { id: 'leads', label: 'Leads', icon: '💬', emoji: '' },
  { id: 'assets', label: 'Assets', icon: '📁', emoji: '' },
  { id: 'providers', label: 'Providers', icon: '⚙️', emoji: '' },
]

interface Props { active: NavId; onNav: (id: NavId) => void; health: any; minimax: any; children: React.ReactNode }

export function AppShell({ active, onNav, health, minimax, children }: Props) {
  return (
    <div className="appShell">
      <aside className="studioNav">
        <div className="brandMark">
          <div className="logo">AI</div>
          <div><strong>AI Growth Studio</strong><span>Video Production Hub</span></div>
        </div>
        <button className="startButton" onClick={() => onNav('create-video')}>+ New Video</button>
        <nav>
          {NAV.map(n => (
            <button key={n.id} className={active === n.id ? 'active' : ''} onClick={() => onNav(n.id)}>
              <span>{n.icon}</span>
              <b>{n.label}</b>
              {n.emoji && <em>{n.emoji}</em>}
            </button>
          ))}
        </nav>
        <div className="miniStatus">
          <span>System Status</span>
          <strong className={health?.status === 'ok' ? 'greenText' : 'redText'}>
            {health?.status === 'ok' ? 'Online' : 'Offline'}
          </strong>
          <small>MiniMax: {minimax?.enabled ? 'Enabled' : 'Disabled'}<br/>API: {health?.version || '?'}</small>
        </div>
      </aside>
      <main className="studioMain">{children}</main>
    </div>
  )
}
