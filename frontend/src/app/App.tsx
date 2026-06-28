import React, { useState, useEffect } from 'react'
import { AppShell, NavId } from '../layouts/AppShell'
import { DashboardPage } from '../features/dashboard/DashboardPage'
import { CreateVideoPage } from '../features/create-video/CreateVideoPage'
import { LeadsPage } from '../features/leads/LeadsPage'
import { AssetsPage } from '../features/assets/AssetsPage'
import { ProvidersPage } from '../features/providers/ProvidersPage'
import { apiGet } from '../lib/api'

const PAGES: Record<NavId, React.FC> = {
  dashboard: DashboardPage,
  'create-video': CreateVideoPage,
  leads: LeadsPage,
  assets: AssetsPage,
  providers: ProvidersPage,
}

export default function App() {
  const [active, setActive] = useState<NavId>('dashboard')
  const [health, setHealth] = useState<any>(null)
  const [minimax, setMinimax] = useState<any>(null)

  useEffect(() => {
    apiGet<any>('/api/health').then(setHealth).catch(() => {})
    apiGet<any>('/api/minimax/status').then(setMinimax).catch(() => {})
  }, [])

  const Page = PAGES[active]
  return (
    <AppShell active={active} onNav={setActive} health={health} minimax={minimax}>
      <Page />
    </AppShell>
  )
}
