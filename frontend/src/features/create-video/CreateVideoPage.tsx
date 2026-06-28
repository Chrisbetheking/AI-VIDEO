import React, { useState } from 'react'
import { Card } from '../../components/ui/Card'
import { Button } from '../../components/ui/Button'
import { Badge } from '../../components/ui/Badge'
import { EmptyState } from '../../components/ui/EmptyState'
import { LoadingBlock } from '../../components/ui/LoadingBlock'
import type { Industry, HumanMode } from '../../lib/types'
import { generateCopy, composeVideo, getIndustryPacks } from '../../lib/api'
import { Video, Sparkles, Radio, User, Image } from 'lucide-react'

const STEPS = ['Industry', 'Script', 'Voice', 'Human', 'B-Roll', 'Compose'] as const

export function CreateVideoPage() {
  const [step, setStep] = useState(0)
  const [industry, setIndustry] = useState<Industry>('real_estate')
  const [script, setScript] = useState('')
  const [voice, setVoice] = useState('volcengine')
  const [humanMode, setHumanMode] = useState<HumanMode>('none')
  const [brollMode, setBrollMode] = useState<'upload' | 'minimax' | 'existing'>('existing')
  const [prompt, setPrompt] = useState('')
  const [generating, setGenerating] = useState(false)
  const [result, setResult] = useState<any>(null)
  const [error, setError] = useState('')

  const handleGenerateScript = async () => {
    setGenerating(true)
    setError('')
    try {
      const res = await generateCopy({ topic: prompt, industry, style: '老板口播、真实、有信任感' })
      setScript(res.script || res.copy?.script || JSON.stringify(res))
      setStep(1)
    } catch (e: any) {
      setError(e.message || 'Failed to generate script')
    } finally {
      setGenerating(false)
    }
  }

  const handleCompose = async () => {
    setGenerating(true)
    setError('')
    try {
      const res = await composeVideo({ script, industry, subtitle_size: 80 })
      setResult(res)
      setStep(5)
    } catch (e: any) {
      setError(e.message || 'Compose failed')
    } finally {
      setGenerating(false)
    }
  }

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-white">Create Video</h2>
        <p className="text-slate-400 mt-1">Step-by-step video production workflow</p>
      </div>

      {/* Stepper */}
      <div className="flex items-center gap-2 overflow-x-auto pb-2">
        {STEPS.map((s, i) => (
          <React.Fragment key={s}>
            <button
              onClick={() => setStep(i)}
              className={`flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium whitespace-nowrap transition-colors ${
                i === step ? 'bg-blue-600 text-white' : i < step ? 'bg-green-900/50 text-green-400' : 'bg-slate-800 text-slate-500'
              }`}
            >
              {i < step ? '✓' : i + 1} {s}
            </button>
            {i < STEPS.length - 1 && <span className="text-slate-700">→</span>}
          </React.Fragment>
        ))}
      </div>

      {/* Step 0: Industry */}
      {step === 0 && (
        <Card title="Step 1: Choose Industry" subtitle="Select the content vertical for your video">
          <div className="grid grid-cols-2 gap-4">
            {(['real_estate', 'foreign_trade'] as Industry[]).map(ind => (
              <button
                key={ind}
                onClick={() => setIndustry(ind)}
                className={`p-6 rounded-xl border-2 text-left transition-all ${
                  industry === ind ? 'border-blue-500 bg-blue-500/10' : 'border-slate-700 hover:border-slate-600'
                }`}
              >
                <h3 className="text-lg font-semibold text-white mb-1">{ind === 'real_estate' ? 'Real Estate' : 'Foreign Trade'}</h3>
                <p className="text-sm text-slate-400">{ind === 'real_estate' ? 'Property, investment, lifestyle' : 'Factory, wholesale, B2B'}</p>
              </button>
            ))}
          </div>
          <div className="mt-4">
            <label className="block text-sm text-slate-400 mb-2">What topic do you want to cover?</label>
            <textarea
              value={prompt}
              onChange={e => setPrompt(e.target.value)}
              placeholder="e.g. 马来西亚吉隆坡 vs 槟城投资对比"
              rows={2}
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-4 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-blue-500"
            />
          </div>
          <div className="mt-4 flex gap-3">
            <Button onClick={handleGenerateScript} disabled={generating || !prompt.trim()}>
              <Sparkles size={16} className="mr-2" /> Generate Script
            </Button>
          </div>
          {error && <p className="text-red-400 text-sm mt-3">{error}</p>}
        </Card>
      )}

      {/* Step 1: Script */}
      {step === 1 && (
        <Card title="Step 2: Script" subtitle="Review and edit the generated script">
          <textarea
            value={script}
            onChange={e => setScript(e.target.value)}
            rows={6}
            className="w-full bg-slate-800 border border-slate-700 rounded-lg px-4 py-3 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-blue-500"
          />
          <div className="mt-4 flex gap-3">
            <Button onClick={() => setStep(2)} disabled={!script.trim()}>Next: Voice</Button>
            <Button variant="ghost" onClick={() => setStep(0)}>Back</Button>
          </div>
        </Card>
      )}

      {/* Step 2: Voice */}
      {step === 2 && (
        <Card title="Step 3: TTS Provider" subtitle="Choose voice synthesis provider">
          <div className="grid grid-cols-2 gap-4">
            {[
              { id: 'volcengine', name: 'Volcengine TTS', desc: 'Cloud Chinese TTS' },
              { id: 'mock', name: 'Mock (Testing)', desc: 'Silent audio for testing' },
            ].map(v => (
              <button
                key={v.id}
                onClick={() => setVoice(v.id)}
                className={`p-4 rounded-xl border-2 text-left ${voice === v.id ? 'border-blue-500 bg-blue-500/10' : 'border-slate-700'}`}
              >
                <div className="flex items-center gap-2 mb-1"><Radio size={16} className="text-blue-400" /><span className="text-white font-medium">{v.name}</span></div>
                <p className="text-xs text-slate-500">{v.desc}</p>
              </button>
            ))}
          </div>
          <div className="mt-4 flex gap-3">
            <Button onClick={() => setStep(3)}>Next: Human Mode</Button>
            <Button variant="ghost" onClick={() => setStep(1)}>Back</Button>
          </div>
        </Card>
      )}

      {/* Step 3: Human */}
      {step === 3 && (
        <Card title="Step 4: Human Mode" subtitle="Choose presenter mode for the video">
          <div className="grid grid-cols-2 gap-4">
            {([
              { id: 'none', name: 'No Human', desc: 'Pure B-roll + subtitles' },
              { id: 'digital_human', name: 'Digital Human', desc: 'AI avatar intro' },
              { id: 'human_intro', name: 'Human Intro', desc: 'Green screen person intro' },
              { id: 'human_pip', name: 'Human PIP', desc: 'Picture-in-picture overlay' },
            ] as { id: HumanMode; name: string; desc: string }[]).map(h => (
              <button
                key={h.id}
                onClick={() => setHumanMode(h.id)}
                className={`p-4 rounded-xl border-2 text-left ${humanMode === h.id ? 'border-blue-500 bg-blue-500/10' : 'border-slate-700'}`}
              >
                <div className="flex items-center gap-2 mb-1"><User size={16} className="text-purple-400" /><span className="text-white font-medium">{h.name}</span></div>
                <p className="text-xs text-slate-500">{h.desc}</p>
              </button>
            ))}
          </div>
          <div className="mt-4 flex gap-3">
            <Button onClick={() => setStep(4)}>Next: B-Roll</Button>
            <Button variant="ghost" onClick={() => setStep(2)}>Back</Button>
          </div>
        </Card>
      )}

      {/* Step 4: B-Roll */}
      {step === 4 && (
        <Card title="Step 5: B-Roll" subtitle="Choose background footage source">
          <div className="grid grid-cols-3 gap-4">
            {[
              { id: 'existing', name: 'Existing', desc: 'Use uploaded assets' },
              { id: 'upload', name: 'Upload', desc: 'Upload new footage' },
              { id: 'minimax', name: 'MiniMax AI', desc: 'Generate with AI' },
            ].map(b => (
              <button
                key={b.id}
                onClick={() => setBrollMode(b.id as any)}
                className={`p-4 rounded-xl border-2 text-center ${brollMode === b.id ? 'border-blue-500 bg-blue-500/10' : 'border-slate-700'}`}
              >
                <Image size={20} className="mx-auto mb-2 text-blue-400" />
                <p className="text-white font-medium text-sm">{b.name}</p>
                <p className="text-xs text-slate-500 mt-1">{b.desc}</p>
              </button>
            ))}
          </div>
          {brollMode === 'minimax' && (
            <div className="mt-4 p-4 bg-slate-800 rounded-lg">
              <p className="text-sm text-yellow-400">MiniMax integration available. Go to Providers page to enable.</p>
            </div>
          )}
          <div className="mt-4 flex gap-3">
            <Button onClick={handleCompose} disabled={generating}>
              <Video size={16} className="mr-2" /> Compose Video
            </Button>
            <Button variant="ghost" onClick={() => setStep(3)}>Back</Button>
          </div>
        </Card>
      )}

      {/* Step 5: Result */}
      {step === 5 && (
        <Card title="Video Ready">
          {result ? (
            <div className="space-y-4">
              <p className="text-green-400">Video composed successfully!</p>
              {result.video_url && (
                <a href={result.video_url} target="_blank" className="text-blue-400 underline text-sm" rel="noreferrer">
                  Open video: {result.video_name || 'output.mp4'}
                </a>
              )}
              <pre className="text-xs text-slate-400 bg-slate-800 p-3 rounded overflow-auto max-h-48">{JSON.stringify(result, null, 2)}</pre>
            </div>
          ) : (
            <EmptyState icon="🎬" title="No result yet" description="Compose a video to see the result here." />
          )}
          <div className="mt-4">
            <Button variant="ghost" onClick={() => { setStep(0); setResult(null); setScript(''); setPrompt('') }}>Start New Video</Button>
          </div>
        </Card>
      )}

      {generating && <LoadingBlock text="Processing..." />}
    </div>
  )
}
