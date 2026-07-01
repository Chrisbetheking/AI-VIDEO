import React from 'react'
import { createRoot } from 'react-dom/client'
import ProductWorkspaceBridge from './ProductWorkspaceBridge'
import './styles.css'
import './product-ux-fixes.css'

const root = document.getElementById('root')
if (!root) {
  throw new Error('Root element #root not found')
}

createRoot(root).render(
  <React.StrictMode>
    <ProductWorkspaceBridge />
  </React.StrictMode>,
)
