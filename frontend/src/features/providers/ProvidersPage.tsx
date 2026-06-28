import React, { useEffect, useState } from 'react'
import { Card } from '../../components/ui/Card'
import { Badge } from '../../components/ui/Badge'
import { StatusDot } from '../../components/ui/StatusDot'
import { LoadingBlock } from '../../components/ui/LoadingBlock'
import { getHealth, getMinimaxStatus } from '../../lib/api'
import type { HealthStatus, MinimaxStatus, ProviderInfo, ProviderStatus } from '../../lib/types'
import { Radio, Brain, Video, User, Key, CheckCircle, XCircle } from 'lucide-react'

export function ProvidersPage() {
  const [health, setHealth] = useState<HealthStatus | null>(null)
  const [minimax, setMinimax] = useState<MinimaxStatus | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      getHealth().catch(() => null),
      getMinimaxStatus().catch(() => null),
    ]).then(([h, m]) => { setHealth(h); setMinimax(m); setLoading(false) })
  }, [])

  const providers: ProviderInfo[] = [
    { name: 'Volcengine TTS', type: 'tts', status: 'unknown', model: 'Volcengine TTS', note: 'Check .env VOLCENGINE_*' },
    { name: 'MiniMax / Hailuo', type: 'video_gen', status: minimax?.enabled ? 'configured' : 'disabled', model: minimax?.video_model || 'MiniMax-Hailuo-2.3', note: minimax?.message },
    { name: 'Qwen / DeepSeek', type: 'llm', status: 'unknown', model: 'qwen-max', note: 'Check AI_PROVIDER in .env' },
    { name: 'Digital Human', type: 'digital_human', status: 'unknown', model: 'OmniHuman 1.5', note: 'Check ENABLE_DIGITAL_HUMAN' },
  ]

  if (loading) return <LoadingBlock text="Loading provider status..." />

  return (
    <div className="space-y-6 max-w-3xl mx-auto">
      <div>
        <h2 className="text-2xl font-bold text-white">Providers</h2>
        <p className="text-slate-400 mt-1">Manage AI service integrations</p>
      </div>

      <div className="grid grid-cols-1 gap-4">
        {providers.map(p => (
          <Card key={p.name}>
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-3">
                <div className={`p-2 rounded-lg ${p.type === 'tts' ? 'bg-purple-900/30' : p.type === 'llm' ? 'bg-blue-900/30' : p.type === 'video_gen' ? 'bg-green-900/30' : 'bg-orange-900/30'}`}>
                  {p.type === 'tts' ? <Radio size={20} className="text-purple-400" /> :
                   p.type === 'llm' ? <Brain size={20} className="text-blue-400" /> :
                   p.type === 'video_gen' ? <Video size={20} className="text-green-400" /> :
                   <User size={20} className="text-orange-400" />}
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="text-white font-medium">{p.name}</h3>
                    <Badge variant={p.status === 'configured' ? 'success' : p.status === 'disabled' ? 'neutral' : 'warning'}>
                      {p.status}
                    </Badge>
                  </div>
                  <p className="text-sm text-slate-500 mt-0.5">Model: {p.model}</p>
                </div>
              </div>
              <StatusDot status={p.status} />
            </div>
            {p.note && <p className="text-xs text-slate-500 mt-3 pl-11">{p.note}</p>}
          </Card>
        ))}
      </div>

      {minimax?.broll_prompts && (
        <Card title="MiniMax B-Roll Prompts" subtitle="Pre-built prompts for AI video generation">
          <div className="space-y-4">
            <div>
              <h4 className="text-sm font-medium text-green-400 mb-2">Real Estate</h4>
              <div className="space-y-1">
                {minimax.broll_prompts.real_estate.map((p, i) => (
                  <p key={i} className="text-xs text-slate-400 bg-slate-800 rounded px-3 py-1.5">{p}</p>
                ))}
              </div>
            </div>
            <div>
              <h4 className="text-sm font-medium text-blue-400 mb-2">Foreign Trade</h4>
              <div className="space-y-1">
                {minimax.broll_prompts.foreign_trade.map((p, i) => (
                  <p key={i} className="text-xs text-slate-400 bg-slate-800 rounded px-3 py-1.5">{p}</p>
                ))}
              </div>
            </div>
          </div>
        </Card>
      )}

      <Card title="Configuration">
        <div className="space-y-2 text-sm text-slate-400">
          <p>Provider API keys are configured in <code className="bg-slate-800 px-1.5 py-0.5 rounded text-xs">backend/.env</code> on your server.</p>
          <p>API keys are <strong>never</strong> exposed to the frontend. This page only shows configuration status.</p>
        </div>
      </Card>
    </div>
  )
}
