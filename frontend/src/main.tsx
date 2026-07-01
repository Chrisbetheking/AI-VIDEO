import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './styles.css'
import './product-ux-fixes.css'
import DouyinAccountLibrary from './DouyinAccountLibrary'
import OpenClawWorkbench from './OpenClawWorkbench'

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)

function mountExtraPanel(id: string, Component: React.ComponentType) {
  if (document.getElementById(id)) return
  const el = document.createElement('div')
  el.id = id
  el.className = 'productExtraPanelRoot'
  document.body.appendChild(el)
  createRoot(el).render(
    <React.StrictMode>
      <Component />
    </React.StrictMode>,
  )
}

mountExtraPanel('douyin-account-library-root', DouyinAccountLibrary)
mountExtraPanel('openclaw-workbench-root', OpenClawWorkbench)
