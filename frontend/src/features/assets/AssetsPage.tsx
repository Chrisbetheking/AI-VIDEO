import React, { useState, useEffect } from 'react'
import { apiGet } from '../../lib/api'
import type { AssetItem } from '../../lib/types'

const FOLDER_LABELS: Record<string, string> = {
  all: 'All', self: 'Self-Shot', digital_human: 'Digital Human',
  provided: 'Provided', image: 'Images', collected: 'Collected', ai: 'AI Generated',
}

export function AssetsPage() {
  const [assets, setAssets] = useState<AssetItem[]>([])
  const [filter, setFilter] = useState('all')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    apiGet<AssetItem[]>('/api/assets?limit=160')
      .then(setAssets)
      .catch(e => setError(String(e)))
      .finally(() => setLoading(false))
  }, [])

  const folders = ['all', ...Array.from(new Set(assets.map(a => a.folder).filter(Boolean)))]
  const filtered = filter === 'all' ? assets : assets.filter(a => a.folder === filter)

  if (loading) return <div className="card"><p>Loading assets...</p></div>

  return (
    <div>
      <div className="heroHeader" style={{ minHeight: 120 }}>
        <div>
          <span className="eyebrow">Asset Library</span>
          <h1 style={{ fontSize: 28 }}>Assets</h1>
          <p>Manage your video, image, and B-roll materials</p>
        </div>
      </div>

      {error && <div className="card" style={{ marginTop: 16, border: '2px solid var(--red)' }}><p style={{ color: 'var(--red)' }}>{error}</p></div>}

      <div style={{ display: 'flex', gap: 8, margin: '16px 0', flexWrap: 'wrap' }}>
        {folders.map(f => (
          <button key={f} onClick={() => setFilter(f)}
            style={{
              padding: '6px 14px', borderRadius: 999, border: filter === f ? '2px solid var(--primary)' : '1px solid var(--line)',
              background: filter === f ? '#eff6ff' : '#fff', fontSize: 13, fontWeight: filter === f ? 800 : 500, cursor: 'pointer'
            }}>{FOLDER_LABELS[f] || f} ({f === 'all' ? assets.length : assets.filter(a => a.folder === f).length})
          </button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <div className="card" style={{ textAlign: 'center', padding: 60 }}>
          <p style={{ fontSize: 32, margin: 0 }}>📁</p>
          <h3>No assets</h3>
          <p style={{ color: 'var(--muted)' }}>Upload your first asset via the API or collector.</p>
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 16 }}>
          {filtered.map(a => (
            <div key={a.id} className="card" style={{ padding: 10 }}>
              {a.kind === 'video' ? (
                <video src={a.url} style={{ width: '100%', height: 140, objectFit: 'cover', borderRadius: 12, background: '#020617' }} controls preload="metadata" />
              ) : (
                <img src={a.url} style={{ width: '100%', height: 140, objectFit: 'cover', borderRadius: 12, background: '#f2f4f7' }} alt={a.original_name} />
              )}
              <p style={{ fontSize: 12, margin: '8px 0 4px', fontWeight: 700 }}>{a.original_name || a.filename}</p>
              <div style={{ display: 'flex', gap: 4 }}>
                <span style={{ background: 'var(--line)', borderRadius: 6, padding: '2px 8px', fontSize: 10 }}>{a.kind}</span>
                <span style={{ background: 'var(--line)', borderRadius: 6, padding: '2px 8px', fontSize: 10 }}>{FOLDER_LABELS[a.folder] || a.folder}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
