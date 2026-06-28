import React, { useState } from 'react'
import { AppShell, NavId } from '../layouts/AppShell'
import { DashboardPage } from '../features/dashboard/DashboardPage'
import { CreateVideoPage } from '../features/create-video/CreateVideoPage'
import { LeadsPage } from '../features/leads/LeadsPage'
import { AssetsPage } from '../features/assets/AssetsPage'
import { ProvidersPage } from '../features/providers/ProvidersPage'

const PAGES: Record<NavId, React.FC> = {
  dashboard: DashboardPage,
  'create-video': CreateVideoPage,
  leads: LeadsPage,
  assets: AssetsPage,
  providers: ProvidersPage,
}

export default function App() {
  const [active, setActive] = useState<NavId>('dashboard')
  const Page = PAGES[active]
  return (
    <AppShell active={active} onNavigate={setActive}>
      <Page />
    </AppShell>
  )
}
