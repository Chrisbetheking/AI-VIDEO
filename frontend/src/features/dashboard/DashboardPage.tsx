import React, { useEffect, useState } from 'react'
import { apiGet, apiPost } from '../../lib/api'
import type { HealthStatus, IndustryPackSummary, MinimaxStatus, LeadItem, LeadAnalyzeResult } from '../../lib/types'

export function DashboardPage() {
  const [health, setHealth] = useState<HealthStatus | null>(null)
  const [packs, setPacks] = useState<IndustryPackSummary[]>([])
  const [minimax, setMinimax] = useState<MinimaxStatus | null>(null)
  const [leads, setLeads] = useState<LeadItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    Promise.all([
      apiGet<HealthStatus>('/api/health').catch(e => { setError(String(e)); return null }),
      apiGet<IndustryPackSummary[]>('/api/industry-packs').catch(() => [] as IndustryPackSummary[]),
      apiGet<MinimaxStatus>('/api/minimax/status').catch(() => null),
      apiGet<LeadItem[]>('/api/leads').catch(() => [] as LeadItem[]),
    ]).then(([h, p, m, l]) => {
      setHealth(h); setPacks(p); setMinimax(m); setLeads(l); setLoading(false)
    })
  }, [])

  if (loading) return <div className="card"><p>Loading dashboard...</p></div>

  const highLeads = leads.filter(l => l.intent_level === 'high').length
  const apiOnline = health?.status === 'ok'

  return (
    <div>
      <div className="heroHeader" style={{ minHeight: 190 }}>
        <div>
          <span className="eyebrow">AI Video Growth Studio</span>
          <h1 style={{ fontSize: 32 }}>Welcome back</h1>
          <p>Automate your video production pipeline. Create, analyze, and grow.</p>
        </div>
        <div className="scoreCard">
          <span>Videos Ready</span>
          <strong style={{ fontSize: 48 }}>0</strong>
          <small>Start composing →</small>
        </div>
      </div>

      {error && <div className="card" style={{ marginTop: 16, border: '2px solid var(--red)' }}><p style={{ color: 'var(--red)' }}>{error}</p></div>}

      <div className="grid4" style={{ marginTop: 24 }}>
        <div className="card"><span className="card-eyebrow">API Status</span><strong style={{ fontSize: 28 }} className={apiOnline ? 'greenText' : 'redText'}>{apiOnline ? 'Online' : 'Offline'}</strong></div>
        <div className="card"><span className="card-eyebrow">Industry Packs</span><strong style={{ fontSize: 28 }}>{packs.length}</strong></div>
        <div className="card"><span className="card-eyebrow">High-Intent Leads</span><strong style={{ fontSize: 28 }} className="greenText">{highLeads}</strong></div>
        <div className="card"><span className="card-eyebrow">MiniMax</span><strong style={{ fontSize: 28 }} className={minimax?.enabled ? 'greenText' : ''}>{minimax?.enabled ? 'On' : 'Off'}</strong></div>
      </div>

      <div className="grid2" style={{ marginTop: 24 }}>
        <div className="card">
          <h3>Industry Packs</h3>
          {packs.map(p => (
            <div key={p.industry} className="timelineRow" style={{ gridTemplateColumns: '1fr auto' }}>
              <div><strong>{p.industry === 'real_estate' ? 'Real Estate' : 'Foreign Trade'}</strong><br/><small>{p.pain_points_count} pain points · {p.hook_templates_count} hooks · {p.cta_templates_count} CTAs</small></div>
              <span style={{ background: 'var(--green)', color: '#fff', borderRadius: 999, padding: '2px 10px', fontSize: 11, fontWeight: 800 }}>Active</span>
            </div>
          ))}
        </div>

        <div className="card">
          <h3>Recent Leads</h3>
          {leads.length === 0 ? <p style={{ color: 'var(--muted)' }}>No leads yet. Go to Leads tab to analyze comments.</p> :
            leads.slice(0, 5).map(l => (
              <div key={l.id} className="timelineRow" style={{ gridTemplateColumns: '1fr auto' }}>
                <div><strong style={{ fontSize: 13 }}>{l.content.slice(0, 60)}{l.content.length > 60 ? '...' : ''}</strong><br/><small>{l.intent_type} · {l.platform}</small></div>
                <span style={{
                  background: l.intent_level === 'high' ? 'var(--green)' : l.intent_level === 'medium' ? 'var(--orange)' : 'var(--muted)',
                  color: '#fff', borderRadius: 999, padding: '2px 10px', fontSize: 11, fontWeight: 800
                }}>{l.intent_level}</span>
              </div>
            ))}
        </div>
      </div>

      <div className="card" style={{ marginTop: 24 }}>
        <h3>Provider Status</h3>
        <div className="grid4">
          {[
            { n: 'API', s: apiOnline ? 'configured' : 'error', m: health?.version || '?' },
            { n: 'MiniMax', s: minimax?.enabled ? 'configured' : 'disabled', m: minimax?.video_model || 'N/A' },
            { n: 'TTS', s: 'unknown', m: 'Volcengine' },
            { n: 'Digital Human', s: 'unknown', m: 'OmniHuman 1.5' },
          ].map(p => (
            <div key={p.n} style={{ padding: 12, border: '1px solid var(--line)', borderRadius: 16, background: '#fff' }}>
              <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 999, marginRight: 8, background: p.s === 'configured' ? 'var(--green)' : p.s === 'error' ? 'var(--red)' : 'var(--muted)' }} />
              <strong style={{ fontSize: 14 }}>{p.n}</strong>
              <br/><small style={{ color: 'var(--muted)' }}>{p.m}</small>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
