import React, { useEffect, useState } from 'react'
import { apiGet } from '../../lib/api'
import type { HealthStatus, MinimaxStatus } from '../../lib/types'

export function ProvidersPage() {
  const [health, setHealth] = useState<HealthStatus | null>(null)
  const [minimax, setMinimax] = useState<MinimaxStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    Promise.all([
      apiGet<HealthStatus>('/api/health').catch(e => { setError(String(e)); return null }),
      apiGet<MinimaxStatus>('/api/minimax/status').catch(() => null),
    ]).then(([h, m]) => { setHealth(h); setMinimax(m); setLoading(false) })
  }, [])

  if (loading) return <div className="card"><p>Loading providers...</p></div>

  const providers = [
    { n: 'API Backend', t: 'Core', s: health?.status === 'ok' ? 'configured' as const : 'error' as const, m: health?.version || '?', note: health?.status === 'ok' ? 'Online' : 'Offline' },
    { n: 'MiniMax / Hailuo', t: 'Video Gen', s: minimax?.enabled ? 'configured' as const : 'disabled' as const, m: minimax?.video_model || 'N/A', note: minimax?.message || '' },
    { n: 'Volcengine TTS', t: 'TTS', s: 'unknown' as const, m: 'Volcengine TTS', note: 'Check VOLCENGINE_* in .env' },
    { n: 'Qwen / DeepSeek', t: 'LLM', s: 'unknown' as const, m: 'qwen-max', note: 'Check AI_PROVIDER in .env' },
    { n: 'Digital Human', t: 'Avatar', s: 'unknown' as const, m: 'OmniHuman 1.5', note: 'Check ENABLE_DIGITAL_HUMAN' },
  ]

  const statusDot = (s: string) => ({
    width: 10, height: 10, borderRadius: 999, display: 'inline-block', marginRight: 10,
    background: s === 'configured' ? 'var(--green)' : s === 'error' ? 'var(--red)' : s === 'disabled' ? 'var(--muted)' : 'var(--orange)'
  })

  return (
    <div>
      <div className="heroHeader" style={{ minHeight: 120 }}>
        <div>
          <span className="eyebrow">Configuration</span>
          <h1 style={{ fontSize: 28 }}>Providers</h1>
          <p>Manage AI service integrations and API keys</p>
        </div>
      </div>

      {error && <div className="card" style={{ marginTop: 16, border: '2px solid var(--red)' }}><p style={{ color: 'var(--red)' }}>{error}</p></div>}

      <div className="card" style={{ marginTop: 24 }}>
        <h3>Provider Status</h3>
        <div style={{ display: 'grid', gap: 12 }}>
          {providers.map(p => (
            <div key={p.n} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 18px', border: '1px solid var(--line)', borderRadius: 16, background: '#fff' }}>
              <div style={{ display: 'flex', alignItems: 'center' }}>
                <span style={statusDot(p.s)} />
                <div>
                  <strong style={{ fontSize: 14 }}>{p.n}</strong>
                  <span style={{ marginLeft: 8, background: p.s === 'configured' ? '#ecfdf5' : p.s === 'error' ? '#fef2f2' : '#f8fafc', color: p.s === 'configured' ? 'var(--green)' : p.s === 'error' ? 'var(--red)' : 'var(--muted)', borderRadius: 999, padding: '2px 10px', fontSize: 11, fontWeight: 800 }}>
                    {p.s}
                  </span>
                </div>
              </div>
              <div style={{ textAlign: 'right' }}>
                <small style={{ color: 'var(--muted)', display: 'block' }}>Model: {p.m}</small>
                {p.note && <small style={{ color: 'var(--muted-2)', fontSize: 11 }}>{p.note}</small>}
              </div>
            </div>
          ))}
        </div>
      </div>

      {minimax?.broll_prompts && (
        <div className="card" style={{ marginTop: 24 }}>
          <h3>MiniMax B-Roll Prompts</h3>
          <div className="grid2">
            <div>
              <h4 style={{ color: 'var(--green)', marginBottom: 8 }}>Real Estate</h4>
              {minimax.broll_prompts.real_estate.map((p, i) => (
                <p key={i} style={{ fontSize: 12, background: '#f8fafc', padding: '6px 12px', borderRadius: 8, marginTop: 4 }}>{p}</p>
              ))}
            </div>
            <div>
              <h4 style={{ color: 'var(--primary)', marginBottom: 8 }}>Foreign Trade</h4>
              {minimax.broll_prompts.foreign_trade.map((p, i) => (
                <p key={i} style={{ fontSize: 12, background: '#f8fafc', padding: '6px 12px', borderRadius: 8, marginTop: 4 }}>{p}</p>
              ))}
            </div>
          </div>
        </div>
      )}

      <div className="card" style={{ marginTop: 24, background: '#fefce8' }}>
        <p style={{ fontSize: 13, color: 'var(--ink)' }}>
          <strong>Note:</strong> API keys are configured in <code>backend/.env</code> on your server.
          They are never exposed to the frontend. This page only shows configuration status.
        </p>
      </div>
    </div>
  )
}
