import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './styles.css'

class ErrorBoundary extends React.Component<{ children: React.ReactNode }, { error?: Error }> {
  constructor(props: { children: React.ReactNode }) {
    super(props)
    this.state = {}
  }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  render() {
    if (this.state.error) {
      return (
        <main>
          <section className="card">
            <h1>前端加载出错</h1>
            <p>请检查 Cloudflare Pages 的 VITE_API_BASE 是否指向 Render 后端地址。</p>
            <pre>{this.state.error.message}</pre>
          </section>
        </main>
      )
    }
    return this.props.children
  }
}

const root = document.getElementById('root')

if (!root) {
  document.body.innerHTML = '<main><section class="card"><h1>页面 root 节点不存在</h1></section></main>'
} else {
  createRoot(root).render(
    <React.StrictMode>
      <ErrorBoundary>
        <App />
      </ErrorBoundary>
    </React.StrictMode>,
  )
}
