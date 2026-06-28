import React, { useState, useEffect } from 'react'
import { apiGet, apiPost } from '../../lib/api'
import type { Industry, HumanMode } from '../../lib/types'

export function CreateVideoPage() {
  const [industry, setIndustry] = useState<Industry>('real_estate')
  const [script, setScript] = useState('')
  const [prompt, setPrompt] = useState('')
  const [subtitleSize, setSubtitleSize] = useState(80)
  const [subtitleHighlight, setSubtitleHighlight] = useState('')
  const [voice, setVoice] = useState('default')
  const [humanMode, setHumanMode] = useState<HumanMode>('none')
  const [composing, setComposing] = useState(false)
  const [result, setResult] = useState<any>(null)
  const [error, setError] = useState('')
  const [minimaxStatus, setMinimaxStatus] = useState<any>(null)
  const [packs, setPacks] = useState<any[]>([])

  useEffect(() => {
    apiGet<any>('/api/minimax/status').then(setMinimaxStatus).catch(() => {})
    apiGet<any[]>('/api/industry-packs').then(setPacks).catch(() => {})
  }, [])

  const handleGenerate = async () => {
    if (!prompt.trim()) return
    setError('')
    try {
      const res = await apiPost<any>('/api/generate-copy', { topic: prompt, industry, style: '老板口播、真实、有信任感', duration_seconds: 35 })
      setScript(res.script || res.copy?.script || JSON.stringify(res))
    } catch (e: any) { setError(String(e)) }
  }

  const handleCompose = async () => {
    if (!script.trim()) return
    setComposing(true); setError('')
    try {
      const res = await apiPost<any>('/api/compose-video', {
        script, title: prompt, duration_seconds: 35, voice,
        subtitle_size: subtitleSize, subtitle_keywords: subtitleHighlight,
        asset_plan: [], asset_ids: [],
      })
      setResult(res)
    } catch (e: any) { setError(String(e)) }
    setComposing(false)
  }

  const handleMinimaxBroll = async () => {
    if (!minimaxStatus?.enabled) return
    setError('')
    try {
      const prompts = minimaxStatus.broll_prompts?.[industry] || ['cinematic drone shot']
      const res = await apiPost<any>('/api/minimax/video/text-to-video', { prompt: prompts[0], duration_seconds: 5 })
      setResult({ ...result, minimax_broll: res })
    } catch (e: any) { setError(String(e)) }
  }

  return (
    <div>
      <div className="heroHeader" style={{ minHeight: 140 }}>
        <div>
          <span className="eyebrow">Create Video</span>
          <h1 style={{ fontSize: 28 }}>New Production</h1>
          <p>Industry → Script → Voice → Human → B-Roll → Compose</p>
        </div>
      </div>

      {error && <div className="card" style={{ marginTop: 16, border: '2px solid var(--red)' }}><p style={{ color: 'var(--red)' }}>{error}</p></div>}

      <div className="workflowBoard" style={{ marginTop: 24 }}>
        {/* Step 1: Industry */}
        <div className="card">
          <h3>1. Industry</h3>
          <div className="grid2" style={{ gap: 10 }}>
            {(['real_estate', 'foreign_trade'] as Industry[]).map(ind => (
              <button key={ind} onClick={() => setIndustry(ind)}
                style={{ padding: 16, borderRadius: 16, border: industry === ind ? '2px solid var(--primary)' : '1px solid var(--line)', background: industry === ind ? '#eff6ff' : '#fff', textAlign: 'left', cursor: 'pointer' }}>
                <strong>{ind === 'real_estate' ? 'Real Estate' : 'Foreign Trade'}</strong>
                <br/><small style={{ color: 'var(--muted)' }}>{ind === 'real_estate' ? 'Property, investment' : 'Factory, wholesale'}</small>
              </button>
            ))}
          </div>
          <div style={{ marginTop: 12 }}>
            <label style={{ fontWeight: 700, fontSize: 13 }}>Topic</label>
            <input value={prompt} onChange={e => setPrompt(e.target.value)} placeholder="e.g. 马来西亚吉隆坡投资对比"
              style={{ width: '100%', marginTop: 6, padding: '10px 14px', borderRadius: 12, border: '1px solid var(--line)', fontSize: 14 }} />
          </div>
          <button className="btn" onClick={handleGenerate} disabled={!prompt.trim()} style={{ marginTop: 12 }}>
            Generate Script
          </button>
        </div>

        {/* Step 2: Script */}
        <div className="card">
          <h3>2. Script & Subtitles</h3>
          <textarea value={script} onChange={e => setScript(e.target.value)} rows={5}
            placeholder="Your video narration script..." style={{ width: '100%', padding: 12, borderRadius: 12, border: '1px solid var(--line)', fontSize: 14, resize: 'vertical' }} />
          <div className="grid2" style={{ marginTop: 10, gap: 10 }}>
            <div><label style={{ fontWeight: 700, fontSize: 12 }}>Subtitle Size</label>
              <input type="number" value={subtitleSize} onChange={e => setSubtitleSize(Number(e.target.value))} min={48} max={120}
                style={{ width: '100%', padding: '8px 12px', borderRadius: 10, border: '1px solid var(--line)' }} /></div>
            <div><label style={{ fontWeight: 700, fontSize: 12 }}>Keywords</label>
              <input value={subtitleHighlight} onChange={e => setSubtitleHighlight(e.target.value)} placeholder="AI, area, price"
                style={{ width: '100%', padding: '8px 12px', borderRadius: 10, border: '1px solid var(--line)' }} /></div>
          </div>
          <button className="btn" onClick={handleCompose} disabled={composing || !script.trim()} style={{ marginTop: 12, background: 'var(--primary-2)' }}>
            {composing ? 'Composing...' : 'Compose Video'}
          </button>
        </div>

        {/* Step 3: Voice / TTS */}
        <div className="card">
          <h3>3. Voice</h3>
          <select value={voice} onChange={e => setVoice(e.target.value)}
            style={{ width: '100%', padding: '10px 14px', borderRadius: 12, border: '1px solid var(--line)', fontSize: 14 }}>
            <option value="default">Volcengine TTS (Default)</option>
            <option value="mock">Mock / Testing</option>
          </select>
          <div className="card" style={{ marginTop: 12, background: '#f8fafc' }}>
            <h3>4. Human Mode</h3>
            <div className="grid2" style={{ gap: 8 }}>
              {(['none', 'digital_human', 'human_intro', 'human_pip'] as HumanMode[]).map(m => (
                <button key={m} onClick={() => setHumanMode(m)}
                  style={{ padding: 10, borderRadius: 12, border: humanMode === m ? '2px solid var(--primary-2)' : '1px solid var(--line)', background: humanMode === m ? '#f5f3ff' : '#fff', cursor: 'pointer', fontSize: 13 }}>
                  {m === 'none' ? 'No Human' : m === 'digital_human' ? 'Digital Human' : m === 'human_intro' ? 'Human Intro' : 'Human PIP'}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Step 4: MiniMax B-Roll */}
        <div className="card">
          <h3>5. B-Roll (MiniMax)</h3>
          <p style={{ fontSize: 13, color: minimaxStatus?.enabled ? 'var(--green)' : 'var(--muted)' }}>
            {minimaxStatus?.enabled ? `MiniMax enabled (${minimaxStatus.video_model})` : 'MiniMax disabled — set MINIMAX_API_KEY in .env'}
          </p>
          {minimaxStatus?.enabled && minimaxStatus.broll_prompts && (
            <div style={{ marginTop: 8 }}>
              <small style={{ color: 'var(--muted)' }}>B-Roll Prompts ({industry}):</small>
              {(minimaxStatus.broll_prompts[industry] || []).slice(0, 2).map((p: string, i: number) => (
                <p key={i} style={{ fontSize: 12, color: 'var(--ink)', background: '#f8fafc', padding: '6px 10px', borderRadius: 8, marginTop: 4 }}>{p}</p>
              ))}
              <button className="btn" onClick={handleMinimaxBroll} style={{ marginTop: 8, background: 'var(--cyan)' }}>
                Generate B-Roll
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Result */}
      {result && (
        <div className="card" style={{ marginTop: 24 }}>
          <h3>Result</h3>
          {result.video_url ? (
            <div className="videoGrid">
              <video src={result.video_url} controls className="previewVideo" />
              <div className="downloadPanel">
                <a href={result.video_url} className="download" target="_blank" rel="noreferrer">Download Video</a>
                <p><strong>Duration:</strong> {result.duration_seconds?.toFixed(1)}s</p>
                {result.warnings?.map((w: string, i: number) => <small key={i} style={{ color: 'var(--orange)' }}>{w}</small>)}
              </div>
            </div>
          ) : (
            <pre style={{ fontSize: 12, color: 'var(--muted)', maxHeight: 200, overflow: 'auto' }}>{JSON.stringify(result, null, 2)}</pre>
          )}
        </div>
      )}
    </div>
  )
}
