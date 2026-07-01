import React, { useEffect, useMemo, useState } from 'react'
import './video-creation-wizard.css'

type WizardStep = 1 | 2 | 3 | 4
type CityKey = 'kuala_lumpur' | 'penang' | 'johor' | 'langkawi' | 'sabah'
type ContentType = 'investment' | 'own_stay' | 'second_home' | 'rental' | 'education'
type MaterialStrategy = 'real_first' | 'ai_fill' | 'full_ai'

type ShotPlan = {
  index: number
  scene: string
  narration: string
  duration: number
}

type JobPayload = {
  ok?: boolean
  job_id?: string
  status?: string
  stage?: string
  progress?: number
  error?: string
  video_url?: string
  url?: string
  output_url?: string
  result_url?: string
  audio_duration_seconds?: number
  shot_count?: number
  city?: string
  script_text?: string
  child_job?: any
  result?: any
  [key: string]: any
}

const STEP_TITLES: Record<WizardStep, string> = {
  1: '搞定视频内容',
  2: '生成口播配音',
  3: '选择画面风格',
  4: '生成成片预览',
}

const STEP_SUBTITLES: Record<WizardStep, string> = {
  1: '输入主题、学习同行、生成选题和文案',
  2: '确认口播稿，设置音色，按配音时长规划后续视频',
  3: '锁定城市画面，规划镜头，选择素材策略和数字人',
  4: '一键生成，查看成片、时长、镜头和发布准备',
}

const CITY_PROFILES: Record<CityKey, {
  label: string
  shortLabel: string
  anchors: string[]
  scenes: string[]
}> = {
  kuala_lumpur: {
    label: '吉隆坡 / Kuala Lumpur',
    shortLabel: '吉隆坡',
    anchors: ['KLCC', 'TRX', 'Mont Kiara', '公寓阳台', '大堂', '泳池'],
    scenes: [
      'KLCC 双子塔天际线 + 高层公寓建立镜头',
      'TRX 金融区 + 高端住宅区位镜头',
      'Mont Kiara 高端公寓社区生活氛围',
      '公寓阳台看吉隆坡城市天际线',
      '现代公寓客厅 + 落地窗城市景观',
      '高端公寓大堂 / 泳池 / 健身房设施',
    ],
  },
  penang: {
    label: '槟城 / Penang',
    shortLabel: '槟城',
    anchors: ['Gurney Drive', '海景公寓', '养老生活', '滨海天际线', '阳台'],
    scenes: [
      '槟城滨海住宅天际线',
      '海景公寓阳台生活方式',
      '现代公寓室内 + 海景窗景',
      '养老和第二家园生活氛围',
    ],
  },
  johor: {
    label: '新山 / Johor Bahru',
    shortLabel: '新山',
    anchors: ['新山城市', 'Medini', '公寓社区', '通勤生活', '家庭自住'],
    scenes: [
      '新山城市住宅区位镜头',
      'Medini 现代公寓社区',
      '家庭自住公寓室内空间',
      '城市通勤和生活配套氛围',
    ],
  },
  langkawi: {
    label: '兰卡威 / Langkawi',
    shortLabel: '兰卡威',
    anchors: ['度假住宅', '岛屿生活', '泳池', '第二家园', '热带景观'],
    scenes: [
      '兰卡威度假型住宅和泳池',
      '热带绿植中的第二家园生活',
      '岛屿度假住宅生活方式',
      '度假社区公共空间',
    ],
  },
  sabah: {
    label: '沙巴 / Sabah',
    shortLabel: '沙巴',
    anchors: ['亚庇', '滨海住宅', '日落景观', '第二家园', '度假生活'],
    scenes: [
      '亚庇城市滨海住宅氛围',
      '沙巴日落景观和住宅生活方式',
      '滨海公寓阳台生活场景',
      '度假型社区配套镜头',
    ],
  },
}

const CONTENT_LABELS: Record<ContentType, string> = {
  investment: '投资配置',
  own_stay: '自住',
  second_home: '第二家园',
  rental: '出租收益',
  education: '教育规划',
}

const MATERIAL_LABELS: Record<MaterialStrategy, string> = {
  real_first: '真实素材优先',
  ai_fill: 'AI 补足',
  full_ai: '全 AI 生成',
}

function readLocalStorage(key: string): string {
  try {
    return window.localStorage.getItem(key) || ''
  } catch {
    return ''
  }
}

function saveLocalStorage(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value)
  } catch {
    // ignore
  }
}

function normalizeApiBase(value: string): string {
  const trimmed = String(value || '').trim().replace(/\/+$/, '')
  return trimmed || 'https://ai-video.47-76-143-158.sslip.io'
}

function getDefaultApiBase(): string {
  const local = readLocalStorage('AI_VIDEO_API_BASE') || readLocalStorage('ai_video_api_base')
  if (local) return normalizeApiBase(local)

  try {
    const envBase = (import.meta as any).env?.VITE_AI_VIDEO_API_BASE
    if (envBase) return normalizeApiBase(envBase)
  } catch {
    // ignore
  }

  return 'https://ai-video.47-76-143-158.sslip.io'
}

function getDefaultToken(): string {
  return (
    readLocalStorage('AI_VIDEO_TOKEN') ||
    readLocalStorage('ai_video_token') ||
    readLocalStorage('AI_VIDEO_ADMIN_TOKEN') ||
    readLocalStorage('token') ||
    ''
  )
}

function targetChars(duration: number): { min: number; max: number } {
  return {
    min: Math.max(40, Math.floor(duration * 4.3)),
    max: Math.max(60, Math.floor(duration * 5.3)),
  }
}

function generateScript(topic: string, city: CityKey, duration: number, contentType: ContentType): string {
  const profile = CITY_PROFILES[city]
  const label = CONTENT_LABELS[contentType]
  const title = topic.trim() || `${profile.shortLabel}买房，别只看价格`
  const { min, max } = targetChars(duration)

  let script = ''

  if (city === 'kuala_lumpur') {
    script = `${title}。很多人买马来西亚房产，第一眼只看价格，但在吉隆坡，真正要先看区域、用途和流动性。KLCC、TRX、Mont Kiara 这些位置，看的不是热闹，而是生活半径、出租需求和未来转手。`
    if (contentType === 'investment') {
      script += '如果是投资配置，先看租客是谁、通勤是否方便、周边配套是否成熟，再看价格是否合理。'
    } else if (contentType === 'own_stay') {
      script += '如果是自住，重点不是短期涨跌，而是生活便利、社区品质和长期居住舒适度。'
    } else if (contentType === 'education') {
      script += '如果考虑家庭和教育，要把通勤、社区、安全感和长期居住需求放在前面。'
    } else {
      script += '自住、出租、第二家园，判断标准完全不一样，先把需求筛清楚，再去看房才不会被带节奏。'
    }
  } else {
    script = `${title}。马来西亚买房不要只看价格，要先看城市、用途和生活方式。${profile.shortLabel}更适合${label}方向的人群，重点要看区域成熟度、生活配套、未来使用场景和转手流动性。`
    script += '先把预算、用途和持有周期想清楚，再去筛项目，才不会被表面卖点带偏。'
  }

  while (script.length < min) {
    if (city === 'kuala_lumpur') {
      script += ' 吉隆坡项目重点看区位价值、生活便利度、出租需求、社区品质和未来转手逻辑。'
    } else {
      script += ` ${profile.shortLabel}项目重点看生活方式、配套成熟度、长期使用场景和资产流动性。`
    }
  }

  if (script.length > max) {
    script = script.slice(0, max).replace(/[，,、\s]+$/g, '') + '。'
  }

  return script
}

function splitNarration(script: string, count: number): string[] {
  const chunks = script
    .split(/[。！？!?；;\n]+/)
    .map((item) => item.trim())
    .filter(Boolean)

  if (chunks.length === 0) return Array.from({ length: count }, () => script)

  const result = Array.from({ length: count }, () => '')
  chunks.forEach((chunk, index) => {
    const slot = index % count
    result[slot] = result[slot] ? `${result[slot]}。${chunk}` : chunk
  })

  return result.map((item, index) => item || chunks[Math.min(index, chunks.length - 1)])
}

function planShotCount(duration: number): number {
  const base = Math.ceil(Math.max(1, duration) / 4.5)
  if (duration >= 16) return Math.max(4, base)
  return Math.max(1, base)
}

function buildShotPlan(script: string, city: CityKey, duration: number): ShotPlan[] {
  const count = planShotCount(duration)
  const profile = CITY_PROFILES[city]
  const segments = splitNarration(script, count)
  const eachDuration = Math.round((duration / count) * 10) / 10

  return Array.from({ length: count }, (_, index) => ({
    index: index + 1,
    scene: profile.scenes[index % profile.scenes.length],
    narration: segments[index] || '',
    duration: eachDuration,
  }))
}

function extractVideoUrl(job: JobPayload | null): string {
  if (!job) return ''

  const direct =
    job.video_url ||
    job.output_url ||
    job.result_url ||
    job.url ||
    job.result?.video_url ||
    job.result?.output_url ||
    job.result?.result_url ||
    job.child_job?.video_url ||
    job.child_job?.output_url ||
    job.child_job?.result_url ||
    job.child_job?.url ||
    job.child_job?.result?.video_url ||
    job.child_job?.result?.output_url ||
    job.child_job?.result?.result_url

  return typeof direct === 'string' ? direct : ''
}

function isFinalStatus(job: JobPayload | null): boolean {
  if (!job) return false
  const text = `${job.status || ''} ${job.stage || ''} ${job.child_job?.status || ''} ${job.child_job?.stage || ''}`.toLowerCase()
  return ['completed', 'succeeded', 'success', 'done', 'finished'].some((key) => text.includes(key))
}

function isFailedStatus(job: JobPayload | null): boolean {
  if (!job) return false
  const text = `${job.status || ''} ${job.stage || ''} ${job.child_job?.status || ''} ${job.child_job?.stage || ''}`.toLowerCase()
  return ['failed', 'error', 'cancelled'].some((key) => text.includes(key))
}

function authHeaders(token: string): HeadersInit {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }

  const clean = token.trim()
  if (clean) {
    headers['X-AI-Video-Token'] = clean
    headers.Authorization = `Bearer ${clean}`
  }

  return headers
}

export default function VideoCreationWizard() {
  const [step, setStep] = useState<WizardStep>(1)
  const [apiBase, setApiBase] = useState(getDefaultApiBase)
  const [token, setToken] = useState(getDefaultToken)

  const [topic, setTopic] = useState('马来西亚吉隆坡买房，别只看价格')
  const [competitorUrl, setCompetitorUrl] = useState('')
  const [targetDuration, setTargetDuration] = useState(20)
  const [city, setCity] = useState<CityKey>('kuala_lumpur')
  const [contentType, setContentType] = useState<ContentType>('investment')

  const [script, setScript] = useState('')
  const [voice, setVoice] = useState('default')
  const [voiceStyle, setVoiceStyle] = useState('自然平稳')
  const [speechSpeed, setSpeechSpeed] = useState(1)

  const [materialStrategy, setMaterialStrategy] = useState<MaterialStrategy>('ai_fill')
  const [useAvatar, setUseAvatar] = useState(false)
  const [avatarName, setAvatarName] = useState('默认数字人')

  const [jobId, setJobId] = useState('')
  const [job, setJob] = useState<JobPayload | null>(null)
  const [isGenerating, setIsGenerating] = useState(false)
  const [error, setError] = useState('')

  const effectiveScript = useMemo(() => {
    return script.trim() || generateScript(topic, city, targetDuration, contentType)
  }, [script, topic, city, targetDuration, contentType])

  const shotPlan = useMemo(() => {
    const duration = Number(job?.audio_duration_seconds || targetDuration)
    return buildShotPlan(effectiveScript, city, duration)
  }, [effectiveScript, city, targetDuration, job?.audio_duration_seconds])

  const videoUrl = extractVideoUrl(job)
  const audioDuration = Number(job?.audio_duration_seconds || 0)
  const currentProfile = CITY_PROFILES[city]

  useEffect(() => {
    saveLocalStorage('AI_VIDEO_API_BASE', apiBase)
  }, [apiBase])

  useEffect(() => {
    if (token.trim()) saveLocalStorage('AI_VIDEO_TOKEN', token.trim())
  }, [token])

  useEffect(() => {
    if (!jobId || !isGenerating) return

    let alive = true

    async function poll() {
      try {
        const response = await fetch(`${normalizeApiBase(apiBase)}/api/video/full-ai/tts-first/job/${jobId}`, {
          headers: authHeaders(token),
        })
        const data = (await response.json()) as JobPayload
        if (!alive) return

        setJob(data)

        if (isFinalStatus(data) || isFailedStatus(data)) {
          setIsGenerating(false)
        }
      } catch (err) {
        if (!alive) return
        setError(err instanceof Error ? err.message : '轮询任务失败')
      }
    }

    poll()
    const timer = window.setInterval(poll, 3000)

    return () => {
      alive = false
      window.clearInterval(timer)
    }
  }, [apiBase, token, jobId, isGenerating])

  function goNext() {
    if (step === 1) {
      if (!script.trim()) {
        setScript(generateScript(topic, city, targetDuration, contentType))
      }
      setStep(2)
      return
    }

    if (step === 2) {
      if (!script.trim()) {
        setScript(generateScript(topic, city, targetDuration, contentType))
      }
      setStep(3)
      return
    }

    if (step === 3) {
      setStep(4)
      return
    }

    startGenerate()
  }

  function goPrev() {
    setStep((current) => Math.max(1, current - 1) as WizardStep)
  }

  async function startGenerate() {
    setError('')
    setStep(4)
    setIsGenerating(true)
    setJob(null)
    setJobId('')

    const payload = {
      title: topic,
      topic,
      script_text: effectiveScript,
      target_duration_seconds: targetDuration,
      duration_seconds: targetDuration,
      city,
      content_type: contentType,
      voice,
      width: 1080,
      height: 1920,
      fps: 30,
      extra: {
        source: 'video_creation_wizard_v1',
        competitor_url: competitorUrl,
        material_strategy: materialStrategy,
        use_avatar: useAvatar,
        avatar_name: useAvatar ? avatarName : '',
        voice_style: voiceStyle,
        speech_speed: speechSpeed,
        ui_step_flow: 'content_script_visual_render',
      },
    }

    try {
      const response = await fetch(`${normalizeApiBase(apiBase)}/api/video/full-ai/tts-first/start`, {
        method: 'POST',
        headers: authHeaders(token),
        body: JSON.stringify(payload),
      })

      const data = (await response.json()) as JobPayload

      if (!response.ok || data.ok === false) {
        throw new Error(data.error || `生成接口失败：HTTP ${response.status}`)
      }

      if (!data.job_id) {
        throw new Error('后端没有返回 job_id')
      }

      setJob(data)
      setJobId(data.job_id)
    } catch (err) {
      setIsGenerating(false)
      setError(err instanceof Error ? err.message : '生成失败')
    }
  }

  function renderStepOne() {
    return (
      <div className="vcw-card-stack">
        <div className="vcw-card">
          <div className="vcw-section-title">内容来源</div>
          <div className="vcw-source-tabs">
            <button className="vcw-source-tab active">抖音主页</button>
            <button className="vcw-source-tab">爆款链接</button>
            <button className="vcw-source-tab">自定义主题</button>
          </div>

          <label className="vcw-field">
            <span>视频主题</span>
            <input
              value={topic}
              onChange={(event) => setTopic(event.target.value)}
              placeholder="例如：马来西亚吉隆坡买房，别只看价格"
            />
          </label>

          <label className="vcw-field">
            <span>同行主页 / 爆款链接，可不填</span>
            <input
              value={competitorUrl}
              onChange={(event) => setCompetitorUrl(event.target.value)}
              placeholder="粘贴抖音 / Instagram / TikTok 链接"
            />
          </label>

          <div className="vcw-grid-3">
            <label className="vcw-field">
              <span>预计视频长度</span>
              <select value={targetDuration} onChange={(event) => setTargetDuration(Number(event.target.value))}>
                <option value={15}>15 秒</option>
                <option value={20}>20 秒</option>
                <option value={30}>30 秒</option>
                <option value={45}>45 秒</option>
                <option value={60}>60 秒</option>
              </select>
            </label>

            <label className="vcw-field">
              <span>城市锁定</span>
              <select value={city} onChange={(event) => setCity(event.target.value as CityKey)}>
                {Object.entries(CITY_PROFILES).map(([key, item]) => (
                  <option key={key} value={key}>
                    {item.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="vcw-field">
              <span>内容方向</span>
              <select value={contentType} onChange={(event) => setContentType(event.target.value as ContentType)}>
                {Object.entries(CONTENT_LABELS).map(([key, label]) => (
                  <option key={key} value={key}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div className="vcw-action-row">
            <button
              className="vcw-primary"
              onClick={() => setScript(generateScript(topic, city, targetDuration, contentType))}
            >
              大脑生成文案
            </button>
            <button className="vcw-secondary" onClick={() => setScript('')}>
              重新生成
            </button>
          </div>
        </div>

        <div className="vcw-card">
          <div className="vcw-section-title">系统理解</div>
          <div className="vcw-chip-row">
            <span className="vcw-chip">目标 {targetDuration}s</span>
            <span className="vcw-chip">{currentProfile.shortLabel}</span>
            <span className="vcw-chip">{CONTENT_LABELS[contentType]}</span>
            <span className="vcw-chip">预计 {planShotCount(targetDuration)} 个镜头</span>
          </div>
          <div className="vcw-hint">
            吉隆坡默认只走城市房产画面：KLCC / TRX / Mont Kiara / 公寓阳台 / 大堂 / 泳池。
          </div>
        </div>
      </div>
    )
  }

  function renderStepTwo() {
    const { min, max } = targetChars(targetDuration)
    return (
      <div className="vcw-card-stack">
        <div className="vcw-two-column">
          <div className="vcw-card">
            <div className="vcw-section-title">口播文案</div>
            <div className="vcw-script-toolbar">
              <span>建议字数：{min}-{max}</span>
              <span>当前字数：{effectiveScript.length}</span>
            </div>
            <textarea
              className="vcw-script-box"
              value={script || effectiveScript}
              onChange={(event) => setScript(event.target.value)}
            />
          </div>

          <div className="vcw-card">
            <div className="vcw-section-title">配音设置</div>
            <label className="vcw-field">
              <span>音色</span>
              <select value={voice} onChange={(event) => setVoice(event.target.value)}>
                <option value="default">默认音色</option>
                <option value="male_warm">男声 / 稳重</option>
                <option value="female_clear">女声 / 清晰</option>
                <option value="business">商务讲解</option>
              </select>
            </label>

            <label className="vcw-field">
              <span>情绪</span>
              <select value={voiceStyle} onChange={(event) => setVoiceStyle(event.target.value)}>
                <option value="自然平稳">自然平稳</option>
                <option value="专业可信">专业可信</option>
                <option value="轻快种草">轻快种草</option>
                <option value="成交引导">成交引导</option>
              </select>
            </label>

            <label className="vcw-field">
              <span>语速 {speechSpeed.toFixed(1)}</span>
              <input
                type="range"
                min="0.8"
                max="1.2"
                step="0.1"
                value={speechSpeed}
                onChange={(event) => setSpeechSpeed(Number(event.target.value))}
              />
            </label>

            <div className="vcw-audio-preview">
              <div className="vcw-play-dot">▶</div>
              <div>
                <strong>下一步后系统会先生成配音</strong>
                <span>最终视频时长跟随真实配音时长</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    )
  }

  function renderStepThree() {
    return (
      <div className="vcw-card-stack">
        <div className="vcw-two-column">
          <div className="vcw-card">
            <div className="vcw-section-title">画面策略</div>
            <label className="vcw-field">
              <span>素材策略</span>
              <select
                value={materialStrategy}
                onChange={(event) => setMaterialStrategy(event.target.value as MaterialStrategy)}
              >
                {Object.entries(MATERIAL_LABELS).map(([key, label]) => (
                  <option key={key} value={key}>
                    {label}
                  </option>
                ))}
              </select>
            </label>

            <div className="vcw-anchor-box">
              <div className="vcw-anchor-title">城市锁定：{currentProfile.label}</div>
              <div className="vcw-chip-row">
                {currentProfile.anchors.map((anchor) => (
                  <span key={anchor} className="vcw-chip purple">
                    {anchor}
                  </span>
                ))}
              </div>
            </div>

            <label className="vcw-switch">
              <input
                type="checkbox"
                checked={useAvatar}
                onChange={(event) => setUseAvatar(event.target.checked)}
              />
              <span>启用数字人讲解</span>
            </label>

            {useAvatar && (
              <label className="vcw-field">
                <span>数字人</span>
                <select value={avatarName} onChange={(event) => setAvatarName(event.target.value)}>
                  <option value="默认数字人">默认数字人</option>
                  <option value="地产顾问">地产顾问</option>
                  <option value="海外置业讲解员">海外置业讲解员</option>
                </select>
              </label>
            )}
          </div>

          <div className="vcw-card">
            <div className="vcw-section-title">镜头规划</div>
            <div className="vcw-shot-list compact">
              {shotPlan.map((shot) => (
                <div key={shot.index} className="vcw-shot-item">
                  <div className="vcw-shot-index">{String(shot.index).padStart(2, '0')}</div>
                  <div>
                    <strong>{shot.scene}</strong>
                    <span>{shot.duration}s · {shot.narration.slice(0, 42)}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    )
  }

  function renderStepFour() {
    return (
      <div className="vcw-card-stack">
        <div className="vcw-two-column">
          <div className="vcw-card vcw-preview-card">
            <div className="vcw-section-title">成片预览</div>

            {videoUrl ? (
              <video className="vcw-video" src={videoUrl} controls playsInline />
            ) : (
              <div className="vcw-video-placeholder">
                <div className="vcw-video-icon">🎬</div>
                <strong>{isGenerating ? '正在生成成片' : '点击生成后在这里预览'}</strong>
                <span>系统会先生成配音，再按配音真实时长生成画面和合成</span>
              </div>
            )}

            {error && <div className="vcw-error">{error}</div>}

            <div className="vcw-action-row">
              <button className="vcw-primary" disabled={isGenerating} onClick={startGenerate}>
                {isGenerating ? '生成中...' : '开始生成成片'}
              </button>
              {videoUrl && (
                <a className="vcw-secondary link" href={videoUrl} target="_blank" rel="noreferrer">
                  打开成片链接
                </a>
              )}
            </div>
          </div>

          <div className="vcw-card">
            <div className="vcw-section-title">生成状态</div>
            <div className="vcw-status-list">
              <div>
                <span>任务</span>
                <strong>{jobId || '-'}</strong>
              </div>
              <div>
                <span>阶段</span>
                <strong>{job?.stage || job?.status || (isGenerating ? 'running' : 'ready')}</strong>
              </div>
              <div>
                <span>配音实际</span>
                <strong>{audioDuration ? `${audioDuration.toFixed(1)}s` : '生成后读取'}</strong>
              </div>
              <div>
                <span>镜头数量</span>
                <strong>{Number(job?.shot_count || shotPlan.length)} 个</strong>
              </div>
              <div>
                <span>城市锁定</span>
                <strong>{currentProfile.shortLabel}</strong>
              </div>
            </div>

            <div className="vcw-mini-progress">
              <span style={{ width: `${Math.min(100, Number(job?.progress || (isGenerating ? 65 : 0)))}%` }} />
            </div>

            {isFailedStatus(job) && (
              <div className="vcw-error">
                {job?.error || job?.child_job?.error || '生成失败，请检查后端日志'}
              </div>
            )}
          </div>
        </div>
      </div>
    )
  }

  function renderMainStep() {
    if (step === 1) return renderStepOne()
    if (step === 2) return renderStepTwo()
    if (step === 3) return renderStepThree()
    return renderStepFour()
  }

  function renderRightPanel() {
    return (
      <aside className="vcw-side-panel">
        <div className="vcw-result-title">生成结果预览</div>

        {step === 1 && (
          <>
            <div className="vcw-result-block">
              <span>提取主题</span>
              <strong>{topic || '等待输入主题'}</strong>
            </div>
            <div className="vcw-result-block">
              <span>推荐文案</span>
              <p>{effectiveScript}</p>
            </div>
          </>
        )}

        {step === 2 && (
          <>
            <div className="vcw-result-block">
              <span>口播分段</span>
              <div className="vcw-line-list">
                {splitNarration(effectiveScript, Math.min(8, shotPlan.length)).map((line, index) => (
                  <div key={`${line}-${index}`}>
                    <em>{String(index + 1).padStart(2, '0')}</em>
                    <strong>{line}</strong>
                  </div>
                ))}
              </div>
            </div>
          </>
        )}

        {step === 3 && (
          <div className="vcw-result-block">
            <span>镜头结果</span>
            <div className="vcw-line-list">
              {shotPlan.map((shot) => (
                <div key={shot.index}>
                  <em>{String(shot.index).padStart(2, '0')}</em>
                  <strong>{shot.scene}</strong>
                </div>
              ))}
            </div>
          </div>
        )}

        {step === 4 && (
          <>
            <div className="vcw-result-block">
              <span>成片信息</span>
              <div className="vcw-summary-grid">
                <strong>{audioDuration ? `${audioDuration.toFixed(1)}s` : `${targetDuration}s`}</strong>
                <small>视频时长</small>
                <strong>{Number(job?.shot_count || shotPlan.length)}</strong>
                <small>镜头数量</small>
                <strong>1080×1920</strong>
                <small>竖屏规格</small>
              </div>
            </div>
            <div className="vcw-result-block">
              <span>发布准备</span>
              <p>成片后可导出视频、复制发布文案，并接入评论获客承接。</p>
            </div>
          </>
        )}
      </aside>
    )
  }

  return (
    <div className="vcw-shell">
      <aside className="vcw-rail">
        <div className="vcw-logo">AI-VIDEO</div>
        <div className="vcw-logo-sub">智能增长工作台</div>

        <nav className="vcw-nav">
          <button className="active">视频创作</button>
          <button>账号素材</button>
          <button>数字人库</button>
          <button>获客线索</button>
          <button>设置</button>
        </nav>

        <div className="vcw-rail-card">
          <strong>创作模式</strong>
          <span>TTS-first</span>
          <small>先配音，再按真实时长生成画面</small>
        </div>
      </aside>

      <main className="vcw-main">
        <header className="vcw-header">
          <div>
            <div className="vcw-eyebrow">第 {step} 步 / 共 4 步</div>
            <h1>{`第${step}步：${STEP_TITLES[step]}`}</h1>
            <p>{STEP_SUBTITLES[step]}</p>
          </div>

          <div className="vcw-api-box">
            <label>
              <span>后端地址</span>
              <input value={apiBase} onChange={(event) => setApiBase(event.target.value)} />
            </label>
            <label>
              <span>Token</span>
              <input
                value={token}
                onChange={(event) => setToken(event.target.value)}
                placeholder="可粘贴后台 Token"
                type="password"
              />
            </label>
          </div>
        </header>

        <div className="vcw-content">
          <section className="vcw-workspace">{renderMainStep()}</section>
          {renderRightPanel()}
        </div>
      </main>

      <footer className="vcw-footer">
        <div className="vcw-footer-progress">
          <span>创作进度</span>
          <strong>{step}/4</strong>
          <div className="vcw-progress-track">
            <i style={{ width: `${(step / 4) * 100}%` }} />
          </div>
        </div>

        <div className="vcw-footer-actions">
          <button className="vcw-secondary big" disabled={step === 1 || isGenerating} onClick={goPrev}>
            上一步
          </button>
          <button className="vcw-primary big" disabled={isGenerating && step === 4} onClick={goNext}>
            {step === 4 ? (isGenerating ? '生成中...' : '生成成片') : '下一步'}
          </button>
        </div>
      </footer>
    </div>
  )
}
