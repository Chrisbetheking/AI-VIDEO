import React from 'react'
import App from './App'
import './styles.css'
import DouyinAccountLibrary from './DouyinAccountLibrary'
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


// ===== DOUYIN ACCOUNT LIBRARY FRONTEND HOTFIX =====
const douyinAccountLibraryRootId = 'douyin-account-library-root'
if (!document.getElementById(douyinAccountLibraryRootId)) {
  const douyinAccountLibraryRoot = document.createElement('div')
  douyinAccountLibraryRoot.id = douyinAccountLibraryRootId
  document.body.appendChild(douyinAccountLibraryRoot)
  createRoot(douyinAccountLibraryRoot).render(
    <React.StrictMode>
      <DouyinAccountLibrary />
    </React.StrictMode>,
  )
}
// ===== /DOUYIN ACCOUNT LIBRARY FRONTEND HOTFIX =====

