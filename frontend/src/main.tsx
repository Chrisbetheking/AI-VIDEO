import React from 'react'
import { createRoot } from 'react-dom/client'
import VideoCreationWizard from './VideoCreationWizard'
import './styles.css'
import './video-creation-wizard.css'

const root = document.getElementById('root')

if (!root) {
  throw new Error('Root element #root not found')
}

createRoot(root).render(
  <React.StrictMode>
    <VideoCreationWizard />
  </React.StrictMode>,
)
