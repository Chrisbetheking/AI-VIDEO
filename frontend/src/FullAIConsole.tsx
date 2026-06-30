import { useEffect, useMemo, useRef, useState } from 'react'

const API_BASE = (((import.meta as any).env?.VITE_API_BASE as string | undefined) || 'https://ai-video.47-76-143-158.sslip.io').replace(/\/$/, '')

type WorkMode = 'full-ai' | 'real-shot' | 'hybrid'

type FullAIJob = {
  ok?: boolean
  job_id?: string
  type?: string
  status?: string
  stage?: string
  message?: string
  video_url?: string
  audio_url?: string
  error?: string
  result?: {
    video_url?: string
    audio_url?: string
    video_urls?: string[]
  }
}

type ShotConfig = {
  shot_id: string
  prompt: string
}

const DEFAULT_SHOTS: ShotConfig[] = [
  {
    shot_id: 'shot_01',
    prompt:
      '9:16 vertical video, cinematic realistic Kuala Lumpur skyline at golden hour, luxury condo buildings, premium real estate advertisement style, smooth slow camera push in, no text, no logo, no watermark',
  },
  {
    shot_id: 'shot_02',
    prompt:
      '9:16 vertical video, realistic young Asian couple looking at a modern condo show unit, warm indoor lighting, real estate viewing scene, cinematic handheld motion, no text, no logo, no watermark',
  },
  {
    shot_id: 'shot_03',
    prompt:
      '9:16 vertical video, premium condominium lobby in Malaysia, marble floor, warm lighting, luxury property investment atmosphere, smooth camera movement, no text, no logo, no watermark',
  },
]

const COOLDOWN_KEY = 'ai_video_full_ai_cooldown_until_v1'
const LAST_PAYLOAD_HASH_KEY = 'ai_video_full_ai_last_payload_hash_v1'
const LAST_PAYLOAD_TIME_KEY = 'ai_video_full_ai_last_payload_time_v1'
const COOLDOWN_SECONDS = 60
const DUPLICATE_WINDOW_SECONDS = 120

function simpleHash(input: string) {
  let hash = 0
  for (let i = 0; i < input.length; i += 1) {
    hash = (hash << 5) - hash + input.charCodeAt(i)
    hash |= 0
  }
  return String(hash)
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })

  const text = await res.text()
  let data: unknown = null

  try {
    data = text ? JSON.parse(text) : null
  } catch {
    throw new Error(text || `HTTP ${res.status}`)
  }

  if (!res.ok) {
    throw new Error(JSON.stringify(data))
  }

  return data as T
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`)
  const text = await res.text()
  let data: unknown = null

  try {
    data = text ? JSON.parse(text) : null
  } catch {
    throw new Error(text || `HTTP ${res.status}`)
  }

  if (!res.ok) {
    throw new Error(JSON.stringify(data))
  }

  return data as T
}

export default function FullAIConsole() {
  const [mode, setMode] = useState<WorkMode>('full-ai')
  const [title, setTitle] = useState('马来西亚买房避坑全AI视频')
  const [scriptText, setScriptText] = useState(
    '来马来西亚买房，千万别只看价格。真正要看的是地段、租金回报，还有未来转手难度。很多人踩坑，不是因为房子不好，而是买错了区域。'
  )
  const [shotCount, setShotCount] = useState(1)
  const [shots, setShots] = useState<ShotConfig[]>(DEFAULT_SHOTS)
  const [busy, setBusy] = useState(false)
  const [job, setJob] = useState<FullAIJob | null>(null)
  const [error, setError] = useState('')
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [riskChecked, setRiskChecked] = useState(false)
  const [cooldownLeft, setCooldownLeft] = useState(0)

  const timerRef = useRef<number | null>(null)
  const cooldownTimerRef = useRef<number | null>(null)

  const payload = useMemo(() => {
    return {
      title: title.trim(),
      script_text: scriptText.trim(),
      mode: 'quick',
      resolution: '720p',
      num_frames: 81,
      frames_per_second: 16,
      max_shots: shotCount,
      voice: 'default',
      overall_rate: '0%',
      shots: shots.slice(0, shotCount).map((shot, index) => ({
        shot_id: shot.shot_id || `shot_${String(index + 1).padStart(2, '0')}`,
        prompt: shot.prompt.trim(),
      })),
    }
  }, [title, scriptText, shotCount, shots])

  const estimatedCostLevel = shotCount === 1 ? '低成本测试' : shotCount === 2 ? '中等成本' : '较高成本小样'

  useEffect(() => {
    function updateCooldown() {
      const until = Number(window.localStorage.getItem(COOLDOWN_KEY) || 0)
      const left = Math.max(0, Math.ceil((until - Date.now()) / 1000))
      setCooldownLeft(left)
    }

    updateCooldown()
    cooldownTimerRef.current = window.setInterval(updateCooldown, 1000)

    return () => {
      if (timerRef.current) {
        window.clearInterval(timerRef.current)
      }
      if (cooldownTimerRef.current) {
        window.clearInterval(cooldownTimerRef.current)
      }
    }
  }, [])

  function updateShot(index: number, value: string) {
    setShots(prev => prev.map((item, i) => (i === index ? { ...item, prompt: value } : item)))
  }

  function validateBeforeConfirm() {
    if (busy) {
      setError('已有任务正在生成，请等待当前任务完成。')
      return false
    }

    if (cooldownLeft > 0) {
      setError(`刚刚已经提交过生成任务，请 ${cooldownLeft} 秒后再试，避免重复烧费用。`)
      return false
    }

    if (!payload.title) {
      setError('请先填写视频标题。')
      return false
    }

    if (!payload.script_text || payload.script_text.length < 8) {
      setError('口播文案太短，请至少写一句完整内容。')
      return false
    }

    const emptyShot = payload.shots.find(shot => !shot.prompt || shot.prompt.length < 12)
    if (emptyShot) {
      setError('镜头 Prompt 太短，请补充完整画面描述。')
      return false
    }

    return true
  }

  function openConfirmDialog() {
    setError('')

    if (!validateBeforeConfirm()) {
      return
    }

    setRiskChecked(false)
    setConfirmOpen(true)
  }

  async function pollJob(jobId: string) {
    if (timerRef.current) {
      window.clearInterval(timerRef.current)
    }

    timerRef.current = window.setInterval(async () => {
      try {
        const data = await getJson<FullAIJob>(`/api/video/full-ai/job/${jobId}`)
        setJob(data)

        if (data.status === 'done' || data.status === 'failed') {
          setBusy(false)

          if (timerRef.current) {
            window.clearInterval(timerRef.current)
            timerRef.current = null
          }
        }
      } catch (e) {
        setBusy(false)
        setError(e instanceof Error ? e.message : String(e))

        if (timerRef.current) {
          window.clearInterval(timerRef.current)
          timerRef.current = null
        }
      }
    }, 5000)
  }

  async function confirmAndStartFullAI() {
    if (!riskChecked) {
      setError('请先勾选费用确认，避免误触发 fal.ai 生成费用。')
      return
    }

    const payloadText = JSON.stringify(payload)
    const payloadHash = simpleHash(payloadText)
    const lastHash = window.localStorage.getItem(LAST_PAYLOAD_HASH_KEY)
    const lastTime = Number(window.localStorage.getItem(LAST_PAYLOAD_TIME_KEY) || 0)
    const duplicateWindowMs = DUPLICATE_WINDOW_SECONDS * 1000

    if (lastHash === payloadHash && Date.now() - lastTime < duplicateWindowMs) {
      const ok = window.confirm('检测到你刚刚提交过完全相同的生成内容。继续提交可能重复产生费用，确定还要再次生成吗？')
      if (!ok) {
        return
      }
    }

    setConfirmOpen(false)
    setError('')
    setBusy(true)
    setJob(null)

    window.localStorage.setItem(COOLDOWN_KEY, String(Date.now() + COOLDOWN_SECONDS * 1000))
    window.localStorage.setItem(LAST_PAYLOAD_HASH_KEY, payloadHash)
    window.localStorage.setItem(LAST_PAYLOAD_TIME_KEY, String(Date.now()))

    try {
      const data = await postJson<FullAIJob>('/api/video/full-ai/start', payload)
      setJob(data)

      if (!data.job_id) {
        throw new Error('后端没有返回 job_id')
      }

      await pollJob(data.job_id)
    } catch (e) {
      setBusy(false)
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const finalVideoUrl = job?.video_url || job?.result?.video_url || ''
  const finalAudioUrl = job?.audio_url || job?.result?.audio_url || ''
  const isDone = job?.status === 'done'
  const isFailed = job?.status === 'failed'

  return (
    <section className="fullAiConsole">
      <div className="fullAiHeader">
        <div>
          <span className="fullAiEyebrow">AI 视频生产中心</span>
          <h1>全 AI / 实拍处理 / 混合成片</h1>
          <p>
            这里是新版入口。全 AI 走 fal.ai 分镜视频 + 字节 TTS + ffmpeg 合成；实拍和混合成片先保留入口，后面继续接上传、剪辑和素材库。
          </p>
        </div>
        <div className="fullAiStatusCard">
          <span>后端链路</span>
          <strong>已打通 /api/video/full-ai/start</strong>
        </div>
      </div>

      <div className="fullAiSafetyPanel">
        <strong>费用保护已开启</strong>
        <span>点击生成前会二次确认；提交后 {COOLDOWN_SECONDS} 秒内不能再次提交；相同内容 {DUPLICATE_WINDOW_SECONDS} 秒内会提示重复风险。</span>
      </div>

      <div className="fullAiTabs">
        <button className={mode === 'full-ai' ? 'active' : ''} onClick={() => setMode('full-ai')}>
          全 AI 生成视频
        </button>
        <button className={mode === 'real-shot' ? 'active' : ''} onClick={() => setMode('real-shot')}>
          实拍视频处理
        </button>
        <button className={mode === 'hybrid' ? 'active' : ''} onClick={() => setMode('hybrid')}>
          混合成片
        </button>
      </div>

      {mode === 'full-ai' && (
        <div className="fullAiGrid">
          <div className="fullAiCard">
            <div className="fullAiCardTitle">
              <h2>全 AI 生成视频</h2>
              <span>会调用 fal.ai，确认后才会产生生成费用</span>
            </div>

            <label>
              视频标题
              <input value={title} onChange={e => setTitle(e.target.value)} />
            </label>

            <label>
              口播文案
              <textarea value={scriptText} onChange={e => setScriptText(e.target.value)} rows={4} />
            </label>

            <label>
              生成镜头数量
              <select value={shotCount} onChange={e => setShotCount(Number(e.target.value))}>
                <option value={1}>1 个镜头，低成本测试</option>
                <option value={2}>2 个镜头</option>
                <option value={3}>3 个镜头，完整小样</option>
              </select>
            </label>

            <div className="fullAiCostHint">
              当前选择：{shotCount} 个镜头，{estimatedCostLevel}。建议测试阶段只用 1 个镜头。
            </div>

            {shots.slice(0, shotCount).map((shot, index) => (
              <label key={shot.shot_id}>
                镜头 {index + 1} Prompt
                <textarea value={shot.prompt} onChange={e => updateShot(index, e.target.value)} rows={3} />
              </label>
            ))}

            <button className="fullAiPrimaryButton" onClick={openConfirmDialog} disabled={busy || cooldownLeft > 0}>
              {busy ? '正在生成，请勿重复点击...' : cooldownLeft > 0 ? `${cooldownLeft} 秒后可再次生成` : '开始生成全 AI 带口播视频'}
            </button>

            <p className="fullAiSmallNote">按钮不会直接生成，会先弹出费用确认窗口。</p>

            {error && <div className="fullAiError">{error}</div>}
          </div>

          <div className="fullAiCard fullAiResultCard">
            <div className="fullAiCardTitle">
              <h2>任务结果</h2>
              <span>{job?.job_id || '还没有任务'}</span>
            </div>

            <div className="fullAiProgress">
              <p>
                状态：<strong className={isFailed ? 'bad' : isDone ? 'good' : ''}>{job?.status || '-'}</strong>
              </p>
              <p>阶段：{job?.stage || '-'}</p>
              <p>消息：{job?.message || '-'}</p>
            </div>

            {finalVideoUrl && (
              <div className="fullAiPreview">
                <video src={finalVideoUrl} controls playsInline />
                <a href={finalVideoUrl} target="_blank" rel="noreferrer">
                  打开最终视频
                </a>
              </div>
            )}

            {finalAudioUrl && (
              <a className="fullAiLink" href={finalAudioUrl} target="_blank" rel="noreferrer">
                打开口播音频
              </a>
            )}

            {job && (
              <pre className="fullAiJson">
                {JSON.stringify(
                  {
                    job_id: job.job_id,
                    status: job.status,
                    stage: job.stage,
                    video_url: finalVideoUrl,
                    audio_url: finalAudioUrl,
                    error: job.error,
                  },
                  null,
                  2
                )}
              </pre>
            )}
          </div>
        </div>
      )}

      {mode === 'real-shot' && (
        <div className="fullAiPlaceholder">
          <h2>实拍视频处理</h2>
          <p>这里后面接：上传自拍视频/房产视频 → 自动字幕 → 标题封面 → 剪废话/空白/口误 → 多版本短视频。</p>
          <p>这条线不要删，你叔他们以后拍真实楼盘、样板间、门店口播，都走这里。</p>
        </div>
      )}

      {mode === 'hybrid' && (
        <div className="fullAiPlaceholder">
          <h2>混合成片</h2>
          <p>这里后面接：实拍/图片素材 + AI 补开头、转场、氛围镜头 + 字节 TTS + 字幕合成。</p>
          <p>适合具体楼盘：真实素材为主，AI 只补泛化镜头，避免虚假宣传风险。</p>
        </div>
      )}

      {confirmOpen && (
        <div className="fullAiModalMask" role="dialog" aria-modal="true">
          <div className="fullAiModal">
            <h2>确认生成全 AI 视频？</h2>
            <p>
              这次会真实调用 fal.ai 视频生成、TTS 和合成链路，可能产生接口费用。当前设置为 <strong>{shotCount}</strong> 个镜头，
              建议测试阶段优先使用 1 个镜头。
            </p>

            <ul>
              <li>请确认不是误点。</li>
              <li>请确认当前文案和 Prompt 已经检查过。</li>
              <li>提交后按钮会进入冷却，避免重复烧费用。</li>
            </ul>

            <label className="fullAiConfirmCheck">
              <input type="checkbox" checked={riskChecked} onChange={e => setRiskChecked(e.target.checked)} />
              我确认本次生成会产生调用成本，并且不是重复误点。
            </label>

            <div className="fullAiModalActions">
              <button className="fullAiCancelButton" onClick={() => setConfirmOpen(false)}>
                取消
              </button>
              <button className="fullAiDangerButton" onClick={confirmAndStartFullAI} disabled={!riskChecked}>
                确认生成
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  )
}
