import React, { useState, useEffect, useCallback } from 'react'
import { Card } from '../../components/ui/Card'
import { Button } from '../../components/ui/Button'
import { Badge } from '../../components/ui/Badge'
import { EmptyState } from '../../components/ui/EmptyState'
import { LoadingBlock } from '../../components/ui/LoadingBlock'
import type { LeadItem, LeadAnalyzeResult, Industry, LeadStatus } from '../../lib/types'
import { analyzeLead, getLeads, updateLead } from '../../lib/api'
import { intentLevelColor, formatDate, truncate } from '../../lib/utils'
import { MessageSquare, Copy, RefreshCw, CheckCircle, XCircle, Clock } from 'lucide-react'

const STATUS_ICONS: Record<string, React.ReactNode> = {
  new: <Clock size={14} />,
  replied: <CheckCircle size={14} />,
  added_wechat: <CheckCircle size={14} />,
  qualified: <CheckCircle size={14} />,
  closed: <XCircle size={14} />,
}

export function LeadsPage() {
  const [comment, setComment] = useState('')
  const [industry, setIndustry] = useState<Industry>('real_estate')
  const [result, setResult] = useState<LeadAnalyzeResult | null>(null)
  const [leads, setLeads] = useState<LeadItem[]>([])
  const [loading, setLoading] = useState(false)
  const [analyzing, setAnalyzing] = useState(false)
  const [error, setError] = useState('')

  const loadLeads = useCallback(async () => {
    setLoading(true)
    try { setLeads(await getLeads()) } catch { /* ok */ }
    setLoading(false)
  }, [])

  useEffect(() => { loadLeads() }, [loadLeads])

  const handleAnalyze = async () => {
    if (!comment.trim()) return
    setAnalyzing(true); setError('')
    try {
      const r = await analyzeLead(comment, industry)
      setResult(r); setComment(''); loadLeads()
    } catch (e: any) { setError(e.message || 'Analysis failed') }
    setAnalyzing(false)
  }

  const handleStatusChange = async (leadId: string, status: LeadStatus) => {
    await updateLead(leadId, status).catch(() => {})
    loadLeads()
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-white">Leads</h2>
        <p className="text-slate-400 mt-1">Analyze comments and manage your lead pipeline</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Analyze Form */}
        <Card title="Analyze Comment" subtitle="Paste a comment to detect intent">
          <div className="space-y-4">
            <div>
              <label className="block text-sm text-slate-400 mb-1">Industry</label>
              <select value={industry} onChange={e => setIndustry(e.target.value as Industry)}
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white">
                <option value="real_estate">Real Estate</option>
                <option value="foreign_trade">Foreign Trade</option>
              </select>
            </div>
            <div>
              <label className="block text-sm text-slate-400 mb-1">Comment</label>
              <textarea value={comment} onChange={e => setComment(e.target.value)} rows={3}
                placeholder="e.g. 这个房子多少钱，能贷款吗？"
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500" />
            </div>
            <Button onClick={handleAnalyze} disabled={analyzing || !comment.trim()}>
              <MessageSquare size={16} className="mr-2" /> Analyze
            </Button>
            {error && <p className="text-red-400 text-sm">{error}</p>}
          </div>

          {result && (
            <div className="mt-4 p-4 bg-slate-800 rounded-lg space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-sm text-slate-400">Intent</span>
                <Badge variant={result.intent_level === 'high' ? 'success' : result.intent_level === 'medium' ? 'warning' : 'neutral'}>
                  {result.intent_level} · {result.intent_type}
                </Badge>
              </div>
              <div>
                <span className="text-sm text-slate-400">Suggested Reply</span>
                <p className="text-white mt-1">{result.suggested_reply}</p>
              </div>
              <div className="flex items-center justify-between text-xs text-slate-500">
                <span>Next: {result.next_action} | Confidence: {(result.confidence * 100).toFixed(0)}%</span>
                <button onClick={() => navigator.clipboard.writeText(result.suggested_reply)}
                  className="flex items-center gap-1 text-blue-400 hover:text-blue-300">
                  <Copy size={12} /> Copy
                </button>
              </div>
            </div>
          )}
        </Card>

        {/* Leads Table */}
        <Card title={`Lead Inbox (${leads.length})`} subtitle="Manage captured leads">
          {loading ? <LoadingBlock text="Loading leads..." /> :
           leads.length === 0 ? <EmptyState icon="📭" title="No leads yet" description="Analyze a comment to get started" /> :
           <div className="space-y-2 max-h-96 overflow-y-auto">
            {leads.map(lead => (
              <div key={lead.id} className="p-3 bg-slate-800 rounded-lg">
                <div className="flex items-start justify-between mb-2">
                  <p className="text-sm text-slate-200 flex-1 min-w-0">{truncate(lead.content, 80)}</p>
                  <Badge variant={lead.intent_level === 'high' ? 'success' : lead.intent_level === 'medium' ? 'warning' : 'neutral'}>
                    {lead.intent_level}
                  </Badge>
                </div>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 text-xs">
                    <span style={{ color: intentLevelColor(lead.intent_level) }}>{lead.intent_type}</span>
                    <span className="text-slate-600">·</span>
                    <span className="text-slate-500">{formatDate(lead.created_at)}</span>
                  </div>
                  <div className="flex items-center gap-1">
                    {(['replied', 'qualified', 'closed'] as LeadStatus[]).map(s => (
                      <button key={s} onClick={() => handleStatusChange(lead.id, s)}
                        className={`p-1 rounded ${lead.status === s ? 'bg-green-900/50 text-green-400' : 'text-slate-600 hover:text-slate-400'}`}
                        title={s}>
                        {STATUS_ICONS[s]}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            ))}
          </div>}
        </Card>
      </div>
    </div>
  )
}
