import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import FullAIConsole from './FullAIConsole'
import DouyinAccountLibrary from './DouyinAccountLibrary'
import OpenClawWorkbench from './OpenClawWorkbench'
import './styles.css'

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
    <DouyinAccountLibrary />
    <OpenClawWorkbench />
    <FullAIConsole />
  </React.StrictMode>,
)
