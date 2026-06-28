import React, { useState, useEffect, useCallback } from 'react'
import { apiGet, apiPost } from '../../lib/api'
import type { LeadItem, LeadAnalyzeResult, Industry, LeadStatus } from '../../lib/types'

export function LeadsPage() {
  const [comment, setComment] = useState('')
  const [industry, setIndustry] = useState<Industry>('real_estate')
  const [result, setResult] = useState<LeadAnalyzeResult | null>(null)
  const [leads, setLeads] = useState<LeadItem[]>([])
  const [loading, setLoading] = useState(true)
  const [analyzing, setAnalyzing] = useState(false)
  const [error, setError] = useState('')
  const [statusMsg, setStatusMsg] = useState('')

  const loadLeads = useCallback(async () => {
    setLoading(true)
    try { const l = await apiGet<LeadItem[]>('/api/leads'); setLeads(l) } catch {}
    setLoading(false)
  }, [])

  useEffect(() => { loadLeads() }, [loadLeads])

  const handleAnalyze = async () => {
    if (!comment.trim()) return
    setAnalyzing(true); setError(''); setResult(null)
    try {
      const r = await apiPost<LeadAnalyzeResult>('/api/leads/analyze', { content: comment, industry, platform: 'douyin' })
      setResult(r); loadLeads()
    } catch (e: any) { setError(String(e)) }
    setAnalyzing(false)
  }

  const handleStatus = async (leadId: string, status: LeadStatus) => {
    setStatusMsg(`Updating ${leadId}...`)
    try { await apiPost('/api/leads/' + leadId, { status }) } catch {}
    setStatusMsg('')
    loadLeads()
  }

  if (loading) return <div className="card"><p>Loading leads...</p></div>

  return (
    <div>
      <div className="heroHeader" style={{ minHeight: 140 }}>
        <div>
          <span className="eyebrow">Lead Management</span>
          <h1 style={{ fontSize: 28 }}>Lead Inbox</h1>
          <p>Analyze comments and manage your lead pipeline</p>
        </div>
      </div>

      {error && <div className="card" style={{ marginTop: 16, border: '2px solid var(--red)' }}><p style={{ color: 'var(--red)' }}>{error}</p></div>}
      {statusMsg && <div className="card" style={{ marginTop: 8 }}><p style={{ color: 'var(--primary)' }}>{statusMsg}</p></div>}

      <div className="grid2" style={{ marginTop: 24 }}>
        {/* Analyze Form */}
        <div className="card">
          <h3>Analyze Comment</h3>
          <div style={{ marginBottom: 10 }}>
            <label style={{ fontWeight: 700, fontSize: 13 }}>Industry</label>
            <select value={industry} onChange={e => setIndustry(e.target.value as Industry)}
              style={{ width: '100%', padding: '10px 14px', borderRadius: 12, border: '1px solid var(--line)', fontSize: 14, marginTop: 4 }}>
              <option value="real_estate">Real Estate</option>
              <option value="foreign_trade">Foreign Trade</option>
            </select>
          </div>
          <textarea value={comment} onChange={e => setComment(e.target.value)} rows={3}
            placeholder="Paste comment: 这个房子多少钱，能贷款吗？"
            style={{ width: '100%', padding: 12, borderRadius: 12, border: '1px solid var(--line)', fontSize: 14, resize: 'vertical' }} />
          <button className="btn" onClick={handleAnalyze} disabled={analyzing || !comment.trim()} style={{ marginTop: 12 }}>
            {analyzing ? 'Analyzing...' : 'Analyze Intent'}
          </button>

          {result && (
            <div style={{ marginTop: 16, padding: 16, border: '1px solid var(--line)', borderRadius: 16, background: '#f8fafc' }}>
              <div className="grid2" style={{ marginBottom: 8 }}>
                <div><small style={{ color: 'var(--muted)' }}>Intent Level</small><br/><strong style={{ color: result.intent_level === 'high' ? 'var(--green)' : result.intent_level === 'medium' ? 'var(--orange)' : 'var(--muted)', fontSize: 20 }}>{result.intent_level}</strong></div>
                <div><small style={{ color: 'var(--muted)' }}>Type</small><br/><strong>{result.intent_type}</strong></div>
              </div>
              <div style={{ marginTop: 8 }}>
                <small style={{ color: 'var(--muted)' }}>Suggested Reply</small>
                <p style={{ margin: '4px 0', fontSize: 14 }}>{result.suggested_reply}</p>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: 'var(--muted)', marginTop: 8 }}>
                <span>Next: {result.next_action} | Confidence: {(result.confidence * 100).toFixed(0)}%</span>
                <button onClick={() => navigator.clipboard.writeText(result.suggested_reply)}
                  style={{ border: '1px solid var(--primary)', color: 'var(--primary)', background: '#fff', borderRadius: 8, padding: '4px 10px', cursor: 'pointer', fontSize: 12, fontWeight: 700 }}>
                  Copy Reply
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Leads Table */}
        <div className="card">
          <h3>Lead Inbox ({leads.length})</h3>
          {leads.length === 0 ? (
            <p style={{ color: 'var(--muted)', textAlign: 'center', padding: 40 }}>No leads yet. Analyze a comment above.</p>
          ) : (
            <div style={{ maxHeight: 500, overflow: 'auto' }}>
              {leads.map(lead => (
                <div key={lead.id} style={{ padding: 12, borderBottom: '1px solid var(--line)' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start' }}>
                    <strong style={{ fontSize: 13, flex: 1 }}>{lead.content.slice(0, 80)}{lead.content.length > 80 ? '...' : ''}</strong>
                    <span style={{
                      background: lead.intent_level === 'high' ? 'var(--green)' : lead.intent_level === 'medium' ? 'var(--orange)' : 'var(--muted)',
                      color: '#fff', borderRadius: 999, padding: '2px 10px', fontSize: 11, fontWeight: 800, marginLeft: 8
                    }}>{lead.intent_level}</span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6, fontSize: 12, color: 'var(--muted)' }}>
                    <span>{lead.intent_type} · {lead.platform} · {lead.created_at?.slice(0, 10)}</span>
                    <div style={{ display: 'flex', gap: 4 }}>
                      {(['replied', 'qualified', 'closed'] as LeadStatus[]).map(s => (
                        <button key={s} onClick={() => handleStatus(lead.id, s)}
                          style={{
                            border: lead.status === s ? '2px solid var(--primary)' : '1px solid var(--line)',
                            background: lead.status === s ? '#eff6ff' : '#fff',
                            borderRadius: 8, padding: '2px 8px', fontSize: 11, cursor: 'pointer', fontWeight: lead.status === s ? 800 : 500
                          }}>{s}</button>
                      ))}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
