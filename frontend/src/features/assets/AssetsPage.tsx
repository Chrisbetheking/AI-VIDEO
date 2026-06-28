import React, { useState, useEffect } from 'react'
import { Card } from '../../components/ui/Card'
import { Badge } from '../../components/ui/Badge'
import { EmptyState } from '../../components/ui/EmptyState'
import { LoadingBlock } from '../../components/ui/LoadingBlock'
import { getAssets } from '../../lib/api'
import type { AssetItem } from '../../lib/types'
import { Image, Video, Upload } from 'lucide-react'

const FOLDER_LABELS: Record<string, string> = {
  all: 'All', self: 'Self-Shot', digital_human: 'Digital Human', provided: 'Provided', image: 'Images', collected: 'Collected', ai: 'AI Generated',
}

export function AssetsPage() {
  const [assets, setAssets] = useState<AssetItem[]>([])
  const [filter, setFilter] = useState('all')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getAssets().then(setAssets).catch(() => setAssets([])).finally(() => setLoading(false))
  }, [])

  const folders = ['all', ...new Set(assets.map(a => a.folder).filter(Boolean))]

  if (loading) return <LoadingBlock text="Loading assets..." />

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-white">Assets</h2>
        <p className="text-slate-400 mt-1">Manage your video, image, and B-roll materials</p>
      </div>

      <div className="flex gap-2 flex-wrap">
        {folders.map(f => (
          <button key={f} onClick={() => setFilter(f)}
            className={`px-3 py-1.5 rounded-full text-xs font-medium ${filter === f ? 'bg-blue-600 text-white' : 'bg-slate-800 text-slate-400 hover:text-white'}`}>
            {FOLDER_LABELS[f] || f}
          </button>
        ))}
      </div>

      {assets.length === 0 ? (
        <EmptyState icon={<Upload size={32} />} title="No assets yet" description="Upload your first asset to get started" />
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
          {(filter === 'all' ? assets : assets.filter(a => a.folder === filter)).map(a => (
            <Card key={a.id} className="p-3">
              {a.kind === 'video' ? (
                <video src={a.url} className="w-full h-32 object-cover rounded-lg mb-2 bg-slate-800" controls preload="metadata" playsInline />
              ) : (
                <img src={a.url} className="w-full h-32 object-cover rounded-lg mb-2 bg-slate-800" alt={a.original_name} />
              )}
              <p className="text-xs text-slate-300 truncate">{a.original_name || a.filename}</p>
              <div className="flex items-center gap-1 mt-1">
                <Badge variant="neutral">{a.kind}</Badge>
                <Badge variant="neutral">{FOLDER_LABELS[a.folder] || a.folder}</Badge>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
