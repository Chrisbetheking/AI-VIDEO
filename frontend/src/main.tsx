import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import FullAIConsole from './FullAIConsole'
import './styles.css'

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <FullAIConsole />
      <App />
  </React.StrictMode>,
)
