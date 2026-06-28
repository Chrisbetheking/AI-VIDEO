import React, { useEffect, useState } from 'react'
import { Card } from '../../components/ui/Card'
import { Badge } from '../../components/ui/Badge'
import { StatusDot } from '../../components/ui/StatusDot'
import { LoadingBlock } from '../../components/ui/LoadingBlock'
import { getHealth, getIndustryPacks, getMinimaxStatus, getLeads } from '../../lib/api'
import type { HealthStatus, IndustryPackSummary, MinimaxStatus, LeadItem } from '../../lib/types'
import { LayoutDashboard, Video, MessageSquare, Radio } from 'lucide-react'

export function DashboardPage() {
  const [health, setHealth] = useState<HealthStatus | null>(null)
  const [packs, setPacks] = useState<IndustryPackSummary[]>([])
  const [minimax, setMinimax] = useState<MinimaxStatus | null>(null)
  const [leads, setLeads] = useState<LeadItem[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      getHealth().catch(() => null),
      getIndustryPacks().catch(() => []),
      getMinimaxStatus().catch(() => null),
      getLeads().catch(() => []),
    ]).then(([h, p, m, l]) => {
      setHealth(h)
      setPacks(p)
      setMinimax(m)
      setLeads(l)
      setLoading(false)
    })
  }, [])

  if (loading) return <LoadingBlock text="Loading dashboard..." />

  const apiOnline = health?.status === 'ok'
  const highLeads = leads.filter(l => l.intent_level === 'high').length

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-white">Welcome back</h2>
        <p className="text-slate-400 mt-1">AI Video Growth Studio - Your content automation hub</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <Card>
          <div className="flex items-center justify-between">
            <div><p className="text-sm text-slate-400">API Status</p>
              <p className="text-2xl font-bold text-white mt-1">{apiOnline ? 'Online' : 'Offline'}</p>
            </div>
            <StatusDot status={apiOnline ? 'configured' : 'error'} />
          </div>
        </Card>
        <Card>
          <div className="flex items-center justify-between">
            <div><p className="text-sm text-slate-400">Industry Packs</p>
              <p className="text-2xl font-bold text-white mt-1">{packs.length}</p>
            </div>
            <LayoutDashboard size={24} className="text-blue-400" />
          </div>
        </Card>
        <Card>
          <div className="flex items-center justify-between">
            <div><p className="text-sm text-slate-400">High-Intent Leads</p>
              <p className="text-2xl font-bold text-white mt-1">{highLeads}</p>
            </div>
            <MessageSquare size={24} className="text-green-400" />
          </div>
        </Card>
        <Card>
          <div className="flex items-center justify-between">
            <div><p className="text-sm text-slate-400">MiniMax</p>
              <p className="text-2xl font-bold text-white mt-1">{minimax?.enabled ? 'On' : 'Off'}</p>
            </div>
            <StatusDot status={minimax?.enabled ? 'configured' : 'disabled'} />
          </div>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card title="Industry Packs" subtitle="Available content templates">
          <div className="space-y-3">
            {packs.map(p => (
              <div key={p.industry} className="flex items-center justify-between py-2 border-b border-slate-800 last:border-0">
                <div>
                  <span className="text-white font-medium">{p.industry === 'real_estate' ? 'Real Estate' : 'Foreign Trade'}</span>
                  <p className="text-xs text-slate-500 mt-0.5">{p.pain_points_count} pain points · {p.hook_templates_count} hooks · {p.cta_templates_count} CTAs</p>
                </div>
                <Badge variant="success">Active</Badge>
              </div>
            ))}
          </div>
        </Card>

        <Card title="Recent Leads" subtitle={`${leads.length} total`}>
          {leads.length === 0 ? (
            <p className="text-sm text-slate-500">No leads yet. Go to Leads to analyze comments.</p>
          ) : (
            <div className="space-y-2 max-h-64 overflow-y-auto">
              {leads.slice(0, 6).map(l => (
                <div key={l.id} className="flex items-center justify-between py-2 border-b border-slate-800 last:border-0">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-slate-300 truncate">{l.content}</p>
                    <p className="text-xs text-slate-500">{l.intent_type} · {l.platform}</p>
                  </div>
                  <Badge variant={l.intent_level === 'high' ? 'success' : l.intent_level === 'medium' ? 'warning' : 'neutral'}>
                    {l.intent_level}
                  </Badge>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      <Card title="Provider Status">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[
            { name: 'API', status: apiOnline ? 'configured' : 'error' as const, model: health?.version || '?' },
            { name: 'MiniMax', status: minimax?.enabled ? 'configured' as const : 'disabled' as const, model: minimax?.video_model || 'N/A' },
            { name: 'TTS', status: 'unknown' as const, model: 'Volcengine' },
            { name: 'Digital Human', status: 'unknown' as const, model: 'OmniHuman 1.5' },
          ].map(p => (
            <div key={p.name} className="flex items-center gap-3 p-3 bg-slate-800/50 rounded-lg">
              <StatusDot status={p.status} />
              <div>
                <p className="text-sm text-white font-medium">{p.name}</p>
                <p className="text-xs text-slate-500">{p.model}</p>
              </div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  )
}
