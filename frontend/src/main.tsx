import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './styles.css'
import './product-ux-fixes.css'
import ProductWorkspaceBridge from './ProductWorkspaceBridge'

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
    <ProductWorkspaceBridge />
  </React.StrictMode>,
)
