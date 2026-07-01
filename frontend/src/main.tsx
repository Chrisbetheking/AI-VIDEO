import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import ProductWorkspaceBridge from './ProductWorkspaceBridge'
import './styles.css'
import './product-ux-fixes.css'

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
    <ProductWorkspaceBridge />
  </React.StrictMode>,
)
