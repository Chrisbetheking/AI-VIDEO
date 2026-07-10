import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import MainWorkflowDock from './MainWorkflowDock'
// AI_VIDEO_V10_40_1_REAL_MAIN_DOCK
import './styles.css'

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
    <MainWorkflowDock />
  </React.StrictMode>,
)
