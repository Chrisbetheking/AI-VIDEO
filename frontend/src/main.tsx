import React from 'react'
import App from './App'
import './styles.css'
import OpenClawWorkbench from './OpenClawWorkbench'
import { createRoot } from 'react-dom/client'

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)


// ===== OPENCLAW WORKBENCH FRONTEND HOTFIX =====
const openClawWorkbenchRootId = 'openclaw-workbench-root'
if (!document.getElementById(openClawWorkbenchRootId)) {
  const openClawWorkbenchRoot = document.createElement('div')
  openClawWorkbenchRoot.id = openClawWorkbenchRootId
  document.body.appendChild(openClawWorkbenchRoot)
  createRoot(openClawWorkbenchRoot).render(
    <React.StrictMode>
      <OpenClawWorkbench />
    </React.StrictMode>,
  )
}
// ===== /OPENCLAW WORKBENCH FRONTEND HOTFIX =====

