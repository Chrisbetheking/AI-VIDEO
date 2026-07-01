import React from 'react'
import ReactDOM from 'react-dom/client'
import './styles.css'
import VideoCreationWizard from './VideoCreationWizard'
import './video-creation-wizard.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <VideoCreationWizard />
  </React.StrictMode>,
)
