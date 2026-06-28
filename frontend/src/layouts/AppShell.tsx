import React, { useState, useEffect } from 'react'
import { Sidebar, NavId } from './Sidebar'
export type { NavId }
import { StatusDot } from '../components/ui/StatusDot'
import { getHealth } from '../lib/api'
import type { HealthStatus } from '../lib/types'

interface AppShellProps {
  active: NavId
  onNavigate: (id: NavId) => void
  children: React.ReactNode
}

export function AppShell({ active, onNavigate, children }: AppShellProps) {
  const [collapsed, setCollapsed] = useState(false)
  const [health, setHealth] = useState<HealthStatus | null>(null)

  useEffect(() => {
    getHealth().then(setHealth).catch(() => setHealth(null))
  }, [])

  return (
    <div className="min-h-screen bg-slate-950 text-slate-200">
      <Sidebar active={active} onNavigate={onNavigate} collapsed={collapsed} onToggle={() => setCollapsed(!collapsed)} />
      <div className={`transition-all duration-200 ${collapsed ? 'ml-16' : 'ml-56'}`}>
        <header className="h-14 border-b border-slate-800 flex items-center justify-between px-6 sticky top-0 bg-slate-950/90 backdrop-blur z-30">
          <h1 className="text-sm font-medium text-slate-300">
            {active === 'dashboard' && 'Dashboard'}
            {active === 'create-video' && 'Create Video'}
            {active === 'leads' && 'Leads'}
            {active === 'assets' && 'Assets'}
            {active === 'providers' && 'Providers'}
          </h1>
          <div className="flex items-center gap-4 text-xs text-slate-500">
            {health && (
              <>
                <span className="flex items-center gap-1.5">
                  <StatusDot status={health.status === 'ok' ? 'configured' : 'error'} />
                  API {health.status === 'ok' ? 'Online' : 'Offline'}
                </span>
                <span className="flex items-center gap-1.5">
                  <StatusDot status={health.minimax_enabled ? 'configured' : 'disabled'} />
                  MiniMax {health.minimax_enabled ? 'On' : 'Off'}
                </span>
              </>
            )}
          </div>
        </header>
        <main className="p-6">{children}</main>
      </div>
    </div>
  )
}
