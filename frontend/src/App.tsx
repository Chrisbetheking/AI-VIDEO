import { useEffect, useMemo, useState, type ReactNode } from 'react'
import './styles.css'
import { API_BASE, apiDelete, apiGet, apiPost, uploadAssets } from './api'

type PageKey = 'home' | 'creator' | 'avatars' | 'subtitles' | 'assets' | 'radar' | 'openclaw' | 'publish' | 'settings'
type AssetKind = 'image' | 'video'

type AssetItem = {
  id: string
  filename: string
  original_name: string
  kind: AssetKind
  url: string
  size_bytes?: number
  created_at?: string
  folder?: string
}

type HeatItem = {
  id?: string
  title?: string
  account_name?: string
  platform?: string
  url?: string
  video_url?: string
  score?: number
  heat_score?: number
  decision?: string
  reason?: string
  like_count?: number
  comment_count?: number
  favorite_count?: number
  share_count?: number
  created_at?: string
}

type CollectorEvent = {
  id?: string
  stage?: string
  level?: string
  message?: string
  account_name?: string
  video_title?: string
  video_url?: string
  error_detail?: string
  created_at?: string
  progress?: Record<string, unknown>
}

type CollectorStatus = {
  ok?: boolean
  run?: Record<string, any>
  events?: CollectorEvent[]
  commands?: Record<string, any>[]
}

type GeneratedCopy = {
  title: string
  hook: string
  script: string
  description: string
  tags: string[]
  shots: string[]
  kb_refs?: string[]
}

type TTSResponse = {
  file_url: string
  file_name: string
  duration_seconds: number
  warning?: string
  segments?: { index: number; text: string; start: number; end: number; duration: number }[]
}

type ComposeResponse = {
  video_url: string
  video_name: string
  subtitle_url?: string
  audio_url?: string
  duration_seconds: number
  warnings?: string[]
}

type AvatarCard = {
  id: string
  name: string
  role: string
  scene: string
  badge: string
  color: string
  mode: 'ready' | 'local' | 'api' | 'manual'
}

type TemplateCard = {
  id: string
  title: string
  subtitle: string
  scene: string
  prompt: string
  type: string
  color: string
}

type SubtitleTemplate = {
  id: string
  name: string
  sample: string
  font: string
  position: string
  style: string
}

const navItems: { key: PageKey; icon: string; label: string; hint: string }[] = [
  { key: 'home', icon: '⌂', label: '首页', hint: '模板入口' },
  { key: 'creator', icon: '▣', label: '视频创作', hint: '脚本 / 素材 / 合成' },
  { key: 'avatars', icon: '人', label: '数字人库', hint: '真人模板 / 本地数字人' },
  { key: 'subtitles', icon: '字', label: '字幕模板', hint: '字幕预览' },
  { key: 'assets', icon: '素', label: '分镜素材', hint: '上传 / 管理素材' },
  { key: 'radar', icon: '雷', label: '采集雷达', hint: '同行热点 / Top5' },
  { key: 'openclaw', icon: '爪', label: 'OpenClaw 截流', hint: '设备自动化' },
  { key: 'publish', icon: '发', label: '发布账号', hint: '账号 / 发布队列' },
  { key: 'settings', icon: '设', label: '系统设置', hint: 'API / 本地 Worker' }
]

const templates: TemplateCard[] = [
  {
    id: 'malaysia_avatar',
    title: '房产顾问真人口播',
    subtitle: '适合海外置业、第二家园、客户答疑',
    scene: '数字人 + B-roll + 强字幕',
    prompt: '用房产顾问口吻讲清马来西亚买房、第二家园和客户顾虑，开头直接打痛点。',
    type: '口播模板',
    color: 'mint'
  },
  {
    id: 'study_abroad',
    title: '留学顾问知识讲解',
    subtitle: '适合留学、陪读、国际学校、就业规划',
    scene: '真人模板 + 资料截图 + 字幕高亮',
    prompt: '围绕马来西亚留学和国际学校，输出家长能听懂的避坑式讲解。',
    type: '知识模板',
    color: 'violet'
  },
  {
    id: 'project_broll',
    title: '楼盘项目分镜混剪',
    subtitle: '适合项目介绍、户型、地图、预算表',
    scene: '分段素材 + 图文窗口 + 配音',
    prompt: '把楼盘优势、预算、位置和客户疑虑拆成 6 段镜头，生成 35 秒成片脚本。',
    type: '混剪模板',
    color: 'blue'
  },
  {
    id: 'report_lead',
    title: '资料包引流短视频',
    subtitle: '适合报告、预算表、流程图、私信承接',
    scene: '封面大字 + 报告截图 + CTA',
    prompt: '用资料包做钩子，引导私信领取马来西亚买房预算表或第二家园清单。',
    type: '引流模板',
    color: 'orange'
  },
  {
    id: 'compare_city',
    title: '城市/区域对比视频',
    subtitle: '适合吉隆坡、新山、槟城、柔佛对比',
    scene: '地图 + 对比表 + 口播',
    prompt: '把不同城市的适合人群、预算、教育和生活成本讲清楚。',
    type: '对比模板',
    color: 'green'
  },
  {
    id: 'comment_reply',
    title: '评论区问题回复',
    subtitle: '适合把评论/私信变成内容',
    scene: '问题截图 + 顾问回复 + CTA',
    prompt: '选一个客户问题，用专业但不生硬的方式回复，并引导私信咨询。',
    type: '截流模板',
    color: 'dark'
  }
]

const avatars: AvatarCard[] = [
  { id: 'advisor_female', name: '女顾问模板', role: '专业可信', scene: '房产讲解 / 留学答疑', badge: '系统模板', color: 'rose', mode: 'ready' },
  { id: 'advisor_male', name: '男顾问模板', role: '老板口播', scene: '避坑提醒 / 项目讲解', badge: '系统模板', color: 'navy', mode: 'ready' },
  { id: 'talking_photo', name: '照片口播', role: '上传照片后驱动', scene: '后期接 LivePortrait / SadTalker', badge: '本地预留', color: 'mint', mode: 'local' },
  { id: 'musetalk', name: '真人底片改口型', role: '固定真人视频 + 新配音', scene: '后期接 MuseTalk', badge: '本地 GPU', color: 'violet', mode: 'local' },
  { id: 'public_avatar', name: '公共 Avatar API', role: '无训练费测试', scene: 'HeyGen / D-ID / AKOOL 备用', badge: 'API 备用', color: 'blue', mode: 'api' }
]

const subtitleTemplates: SubtitleTemplate[] = [
  { id: 'douyin_yellow', name: '抖音大黄字', sample: '几百万预算怎么选马来西亚房产？', font: '粗体 / 描边', position: '中下', style: '强钩子、适合口播' },
  { id: 'clean_white', name: '白字黑边', sample: '第二家园不是所有家庭都适合', font: '简洁 / 高可读', position: '底部安全区', style: '专业讲解' },
  { id: 'report_highlight', name: '报告重点字幕', sample: '私信领取预算测算表', font: '关键词高亮', position: '画面中心', style: '资料包引流' },
  { id: 'split_screen', name: '图文窗口字幕', sample: '左边讲流程，右边放资料表', font: '双行重点', position: '左右分屏', style: '图文混剪' }
]

const quickPlan = [
  { title: '1 选数字人/真人模板', desc: '先定人设：顾问、老板、留学老师或照片口播。' },
  { title: '2 选字幕模板', desc: '预览大黄字、白字黑边、报告引流字幕。' },
  { title: '3 上传分段素材', desc: '项目、学校、地图、预算表、生活 B-roll 分段放入。' },
  { title: '4 生成脚本/分镜', desc: '从热度雷达或手写主题生成标题、钩子、分镜。' },
  { title: '5 预览并合成', desc: '看字幕和画面结构，再 TTS + FFmpeg 合成。' },
  { title: '6 发布/截流', desc: '后期交给 OpenClaw 做发布、监听和截流。' }
]

const defaultCopy: GeneratedCopy = {
  title: '马来西亚买房前，先搞清这 3 个问题',
  hook: '不是所有海外房产都适合你，尤其是第一次看马来西亚房产的家庭。',
  script: '如果你正在考虑马来西亚买房，先别急着看价格。第一，要先判断你是为了自住、陪读、养老还是资产配置。第二，要看城市，不同城市的预算、生活方式和出租逻辑完全不一样。第三，要看后续承接，比如身份、学校、医疗和长期居住成本。你可以先把预算、家庭阶段和目标城市整理出来，再决定看哪类项目。想要一份马来西亚买房预算测算表，可以私信我。',
  description: '马来西亚买房前先判断目的、城市和预算，别只看价格。',
  tags: ['马来西亚房产', '第二家园', '海外置业'],
  shots: ['顾问正面口播', '地图/城市画面', '预算表截图', '楼盘/社区 B-roll', '结尾私信 CTA']
}

function formatCount(n: unknown) {
  const value = Number(n || 0)
  if (!Number.isFinite(value) || value <= 0) return '0'
  if (value >= 10000) return `${(value / 10000).toFixed(1).replace('.0', '')}w`
  return String(value)
}

function pickUrl(item: HeatItem) {
  return item.video_url || item.url || ''
}

function stageLabel(stage?: string) {
  const map: Record<string, string> = {
    run_started: '任务启动',
    account_started: '开始账号',
    profile_loaded: '主页加载',
    videos_found: '发现视频',
    video_submitting: '提交分析',
    video_analyzed: 'AI 已判断',
    account_finished: '账号完成',
    delay: '限速等待',
    run_finished: '任务完成',
    run_failed: '任务失败'
  }
  return map[String(stage || '').toLowerCase()] || (stage || '日志')
}

function App() {
  const [active, setActive] = useState<PageKey>('home')
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem('aivideo_sidebar_collapsed') === '1')
  const [busy, setBusy] = useState('')
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [health, setHealth] = useState<Record<string, any> | null>(null)
  const [assets, setAssets] = useState<AssetItem[]>([])
  const [selectedAssetIds, setSelectedAssetIds] = useState<string[]>([])
  const [heatItems, setHeatItems] = useState<HeatItem[]>([])
  const [collector, setCollector] = useState<CollectorStatus | null>(null)
  const [copy, setCopy] = useState<GeneratedCopy>(defaultCopy)
  const [manualTopic, setManualTopic] = useState('马来西亚买房预算怎么判断？')
  const [selectedTemplate, setSelectedTemplate] = useState(templates[0].id)
  const [selectedAvatar, setSelectedAvatar] = useState(avatars[0].id)
  const [selectedSubtitle, setSelectedSubtitle] = useState(subtitleTemplates[0].id)
  const [collectorLimit, setCollectorLimit] = useState(1)
  const [limitPerAccount, setLimitPerAccount] = useState(1)
  const [quickMode, setQuickMode] = useState(true)
  const [tts, setTts] = useState<TTSResponse | null>(null)
  const [video, setVideo] = useState<ComposeResponse | null>(null)
  const [assetDrag, setAssetDrag] = useState(false)
  const [subtitleKeywords, setSubtitleKeywords] = useState('马来西亚,第二家园,预算,国际学校,私信')

  const template = templates.find(x => x.id === selectedTemplate) || templates[0]
  const avatar = avatars.find(x => x.id === selectedAvatar) || avatars[0]
  const subtitle = subtitleTemplates.find(x => x.id === selectedSubtitle) || subtitleTemplates[0]
  const selectedAssets = assets.filter(x => selectedAssetIds.includes(x.id))
  const hotItems = useMemo(() => heatItems.slice(0, 5), [heatItems])
  const events = collector?.events || []

  useEffect(() => {
    localStorage.setItem('aivideo_sidebar_collapsed', collapsed ? '1' : '0')
  }, [collapsed])

  useEffect(() => {
    refreshAll()
    const timer = window.setInterval(() => refreshCollector(false), 3500)
    return () => window.clearInterval(timer)
  }, [])

  async function run<T>(label: string, fn: () => Promise<T>): Promise<T | null> {
    setBusy(label)
    setError('')
    setNotice('')
    try {
      const res = await fn()
      setNotice(`${label}完成`)
      return res
    } catch (err: any) {
      const msg = err?.message || String(err)
      setError(msg)
      return null
    } finally {
      setBusy('')
    }
  }

  async function refreshAll() {
    await Promise.allSettled([loadHealth(), loadAssets(), loadHeatItems(), refreshCollector(false)])
  }

  async function loadHealth() {
    try { setHealth(await apiGet<Record<string, any>>('/api/health')) } catch {}
  }

  async function loadAssets() {
    try { setAssets(await apiGet<AssetItem[]>('/api/assets')) } catch {}
  }

  async function loadHeatItems() {
    try {
      const items = await apiGet<HeatItem[]>('/api/heat-radar/items')
      setHeatItems((items || []).filter(x => !String((x as any).deleted).includes('true')))
    } catch {}
  }

  async function refreshCollector(showError = true) {
    try { setCollector(await apiGet<CollectorStatus>('/api/collector/runs/latest?events_limit=50')) }
    catch (err: any) { if (showError) setError(err?.message || String(err)) }
  }

  async function handleUpload(files: FileList | null) {
    if (!files?.length) return
    const uploaded = await run('上传分段素材', () => uploadAssets(files, 'self'))
    if (uploaded) {
      setAssets(prev => [...uploaded, ...prev])
      setSelectedAssetIds(prev => Array.from(new Set([...uploaded.map(x => x.id), ...prev])))
      setActive('creator')
    }
  }

  function toggleAsset(id: string) {
    setSelectedAssetIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id])
  }

  async function removeAsset(id: string) {
    const ok = window.confirm('确定删除这个素材吗？')
    if (!ok) return
    const res = await run('删除素材', () => apiDelete<{ ok: boolean }>(`/api/assets/${encodeURIComponent(id)}`))
    if (res) {
      setAssets(prev => prev.filter(x => x.id !== id))
      setSelectedAssetIds(prev => prev.filter(x => x !== id))
    }
  }

  async function generateCopy() {
    const res = await run('生成脚本', () => apiPost<GeneratedCopy>('/api/generate-copy', {
      topic: manualTopic || template.prompt,
      industry: '马来西亚房产 / 留学 / 海外置业',
      audience: '想了解马来西亚买房、第二家园、陪读、留学和海外资产配置的华人家庭',
      selling_points: '预算测算、城市对比、第二家园身份、国际学校、生活成本、真实客户顾虑',
      style: `${template.type}，${avatar.role}，${subtitle.style}，口语化，强钩子，不夸大承诺`,
      duration_seconds: 35
    }))
    if (res) setCopy(res)
  }

  async function useHeatItem(item: HeatItem) {
    const title = item.title || '热点视频'
    setManualTopic(title)
    setCopy(prev => ({
      ...prev,
      title,
      hook: item.reason || prev.hook,
      description: `参考账号：${item.account_name || ''}。互动：赞${formatCount(item.like_count)} / 评${formatCount(item.comment_count)} / 藏${formatCount(item.favorite_count)} / 分享${formatCount(item.share_count)}`,
      tags: ['马来西亚房产', '海外置业', '第二家园']
    }))
    setActive('creator')
  }

  async function synthesizeVoice() {
    const res = await run('生成配音', () => apiPost<TTSResponse>('/api/tts', {
      text: copy.script,
      rate: '1.0'
    }))
    if (res) setTts(res)
  }

  async function composeVideo() {
    const assetPlan = selectedAssets.map((asset, index) => ({
      asset_id: asset.id,
      order: index,
      kind: asset.kind,
      image_seconds: 3.5,
      video_start: 0,
      video_end: 0
    }))
    const res = await run('合成视频', () => apiPost<ComposeResponse>('/api/compose-video', {
      title: copy.title,
      script: copy.script,
      asset_ids: selectedAssetIds,
      asset_plan: assetPlan,
      audio_file_name: tts?.file_name || undefined,
      duration_seconds: 35,
      subtitle_size: 22,
      subtitle_margin_v: 86,
      subtitle_position: 'bottom_safe',
      subtitle_style_preset: selectedSubtitle,
      subtitle_keywords: subtitleKeywords,
      subtitle_segments: tts?.segments || []
    }))
    if (res) setVideo(res)
  }

  async function createCollectorCommand() {
    const res = await run('下发采集命令', () => apiPost<Record<string, any>>('/api/collector/commands', {
      limit: collectorLimit,
      limit_per_account: limitPerAccount,
      headful: true,
      dry_run: false,
      no_delay: quickMode,
      mode: quickMode ? 'quick_demo' : 'safe_daily',
      message: `网页下发：采集 ${collectorLimit} 个账号，每个账号 ${limitPerAccount} 条视频`,
      raw: { source: 'jimeng_style_creator_ui', limit_per_account: limitPerAccount }
    }))
    if (res) {
      await refreshCollector(false)
      setNotice(`已创建采集命令：${res.command_id || res.id || 'queued'}。ECS 运行 command_worker.py 后会自动领取。`)
      setActive('radar')
    }
  }

  async function deleteHeatItem(item: HeatItem) {
    if (!item.id) return
    if (!window.confirm('确定从热度雷达删除这条吗？')) return
    const res = await run('删除热点', () => apiDelete<{ ok: boolean }>(`/api/heat-radar/items/${encodeURIComponent(item.id || '')}`))
    if (res) setHeatItems(prev => prev.filter(x => x.id !== item.id))
  }

  function renderNav() {
    return <aside className={`side ${collapsed ? 'collapsed' : ''}`}>
      <div className="brand">
        <div className="brandLogo">AI</div>
        {!collapsed && <div><strong>AI 视频创作中枢</strong><span>采集 · 数字人 · 成片 · 截流</span></div>}
      </div>
      <button className="collapseBtn" onClick={() => setCollapsed(!collapsed)} title={collapsed ? '展开菜单' : '折叠菜单'}>{collapsed ? '›' : '‹'}</button>
      <nav className="navList">
        {navItems.map(item => <button key={item.key} className={active === item.key ? 'active' : ''} onClick={() => setActive(item.key)} title={collapsed ? item.label : ''}>
          <span>{item.icon}</span>
          {!collapsed && <><b>{item.label}</b><em>{item.hint}</em></>}
        </button>)}
      </nav>
      {!collapsed && <div className="navStatus">
        <span>API</span>
        <strong className={health?.ok ? 'ok' : 'warn'}>{health?.ok ? '已连接' : '待连接'}</strong>
        <small>{health?.workspace_id || 'workspace'} · {API_BASE.replace(/^https?:\/\//, '')}</small>
      </div>}
    </aside>
  }

  function renderHome() {
    return <>
      <section className="hero jimengHero">
        <div>
          <span className="eyebrow">AI CREATOR STUDIO</span>
          <h1>像即梦一样选模板、做数字人、上传素材、自动合成视频</h1>
          <p>热度雷达只负责找选题；真正主流程改成“视频创作工作台”：真人/数字人模板、字幕预览、分段素材、脚本、合成、发布。</p>
          <div className="heroActions">
            <button className="primary" onClick={() => setActive('creator')}>立即创作</button>
            <button className="ghost" onClick={() => setActive('radar')}>先看热度雷达</button>
          </div>
        </div>
        <div className="phonePreview heroPhone">
          <div className="phoneScreen demoGradient">
            <div className="avatarSilhouette">AI</div>
            <div className="captionBig">马来西亚买房<br />先看这 3 点</div>
            <div className="captionSmall">数字人 + B-roll + 字幕模板</div>
          </div>
        </div>
      </section>

      <section className="sectionHead">
        <div><h2>系统模板</h2><p>主入口改成视频模板库，少一点后台感，多一点创作工具感。</p></div>
        <button className="soft" onClick={() => setActive('creator')}>进入工作台</button>
      </section>
      <div className="templateGrid">
        {templates.map(t => <button key={t.id} className={`templateCard ${t.color}`} onClick={() => { setSelectedTemplate(t.id); setManualTopic(t.prompt); setActive('creator') }}>
          <div className="templatePoster">
            <span>{t.type}</span>
            <strong>{t.title}</strong>
            <em>{t.scene}</em>
          </div>
          <div className="templateMeta"><b>{t.title}</b><small>{t.subtitle}</small></div>
        </button>)}
      </div>

      <section className="sectionHead"><div><h2>完整链路</h2><p>从热点到成片，后期再由 OpenClaw 发布和截流。</p></div></section>
      <div className="quickPlan">
        {quickPlan.map((step, index) => <div key={step.title}><span>{index + 1}</span><b>{step.title}</b><p>{step.desc}</p></div>)}
      </div>
    </>
  }

  function renderCreator() {
    return <>
      <section className="creatorShell">
        <div className="creatorMain">
          <div className="sectionHead compact"><div><h2>视频创作工作台</h2><p>选择模板 → 选数字人 → 选字幕 → 上传分段素材 → 生成脚本 → 合成视频。</p></div><Pill>当前：{template.title}</Pill></div>

          <div className="stepStrip">
            {['数字人', '字幕', '素材', '脚本', '预览', '合成'].map((x, i) => <button key={x} className={i < 3 ? 'done' : ''}><span>{i + 1}</span>{x}</button>)}
          </div>

          <div className="creatorBlock">
            <h3>1. 选择数字人 / 真人模板</h3>
            <div className="miniCardGrid">
              {avatars.map(item => <button key={item.id} className={selectedAvatar === item.id ? 'miniCard active' : 'miniCard'} onClick={() => setSelectedAvatar(item.id)}>
                <span className={`avatarBubble ${item.color}`}>{item.name.slice(0, 1)}</span>
                <b>{item.name}</b><small>{item.scene}</small><em>{item.badge}</em>
              </button>)}
            </div>
          </div>

          <div className="creatorBlock">
            <h3>2. 选择字幕模板</h3>
            <div className="subtitleCards">
              {subtitleTemplates.map(item => <button key={item.id} className={selectedSubtitle === item.id ? 'subtitleCard active' : 'subtitleCard'} onClick={() => setSelectedSubtitle(item.id)}>
                <div className={`subtitlePreview ${item.id}`}><strong>{item.sample}</strong></div>
                <b>{item.name}</b><small>{item.style}</small>
              </button>)}
            </div>
          </div>

          <div className="creatorBlock">
            <div className="blockTop"><h3>3. 上传分段素材</h3><label className="uploadBtn">上传图片/视频<input type="file" multiple accept="image/*,video/*" onChange={e => handleUpload(e.target.files)} /></label></div>
            <div
              className={`dropZone ${assetDrag ? 'dragging' : ''}`}
              onDragOver={e => { e.preventDefault(); setAssetDrag(true) }}
              onDragLeave={() => setAssetDrag(false)}
              onDrop={e => { e.preventDefault(); setAssetDrag(false); handleUpload(e.dataTransfer.files) }}
            >
              <strong>拖动上传分段素材</strong>
              <span>项目视频、学校画面、地图、预算表、报告截图、B-roll 都放这里。</span>
            </div>
            <div className="assetTimeline">
              {selectedAssets.length ? selectedAssets.map((asset, index) => <div key={asset.id} className="timelineClip">
                <span>{index + 1}</span>
                <b>{asset.original_name || asset.filename}</b>
                <small>{asset.kind === 'video' ? '视频段' : '图片段'} · 约 {asset.kind === 'video' ? '自动截取' : '3.5'} 秒</small>
              </div>) : <div className="emptyInline">还没选择素材。可上传素材，或去“分镜素材”页选择已有素材。</div>}
            </div>
          </div>

          <div className="creatorBlock twoCol">
            <div>
              <h3>4. 脚本生成</h3>
              <label className="field"><span>主题 / 热点 / 客户问题</span><input value={manualTopic} onChange={e => setManualTopic(e.target.value)} /></label>
              <label className="field"><span>字幕关键词</span><input value={subtitleKeywords} onChange={e => setSubtitleKeywords(e.target.value)} /></label>
              <div className="buttonRow"><button className="primary" onClick={generateCopy} disabled={!!busy}>{busy === '生成脚本' ? busy : '生成脚本'}</button><button className="ghost" onClick={() => setActive('radar')}>从热度雷达选题</button></div>
            </div>
            <div className="scriptBox">
              <input value={copy.title} onChange={e => setCopy({ ...copy, title: e.target.value })} />
              <textarea value={copy.script} onChange={e => setCopy({ ...copy, script: e.target.value })} />
            </div>
          </div>

          <div className="creatorBlock">
            <h3>5. 配音与合成</h3>
            <div className="buttonRow">
              <button className="soft" onClick={synthesizeVoice} disabled={!!busy}>{busy === '生成配音' ? busy : '生成配音'}</button>
              <button className="primary" onClick={composeVideo} disabled={!!busy || !selectedAssetIds.length}>{busy === '合成视频' ? busy : '合成视频'}</button>
              {video?.video_url && <a className="primary linkBtn" href={video.video_url} target="_blank">打开成片</a>}
            </div>
            {tts?.file_url && <audio controls src={tts.file_url} />}
            {video?.warnings?.length ? <div className="warningList">{video.warnings.map(x => <p key={x}>· {x}</p>)}</div> : null}
          </div>
        </div>

        <aside className="previewPanel">
          <h3>实时预览</h3>
          <div className="phonePreview">
            <div className={`phoneScreen ${template.color}`}>
              <div className="avatarName">{avatar.name}</div>
              <div className="subtitleMock"><strong>{subtitle.sample}</strong></div>
              <div className="scriptPreview">{copy.hook}</div>
            </div>
          </div>
          <div className="previewInfo">
            <b>{copy.title}</b>
            <p>模板：{template.title}</p>
            <p>字幕：{subtitle.name}</p>
            <p>素材：{selectedAssets.length} 段</p>
            <p>配音：{tts ? `${Math.round(tts.duration_seconds)} 秒` : '未生成'}</p>
          </div>
        </aside>
      </section>
    </>
  }

  function renderAvatars() {
    return <>
      <section className="sectionHead"><div><h2>数字人库</h2><p>今天先做“模板选择 + 本地 Worker 预留”，后期接 MuseTalk / LivePortrait / 真实设备。</p></div><button className="soft" onClick={() => setActive('creator')}>去创作</button></section>
      <div className="avatarGrid">
        {avatars.map(item => <button key={item.id} className={selectedAvatar === item.id ? 'avatarCard active' : 'avatarCard'} onClick={() => { setSelectedAvatar(item.id); setActive('creator') }}>
          <div className={`avatarPoster ${item.color}`}><span>{item.badge}</span><strong>{item.name}</strong><em>{item.role}</em></div>
          <b>{item.name}</b><p>{item.scene}</p><small>{item.mode === 'local' ? '后期本地 GPU 生成' : item.mode === 'api' ? '无训练费 API 备用' : '今天可用于预览'}</small>
        </button>)}
      </div>
    </>
  }

  function renderSubtitles() {
    return <>
      <section className="sectionHead"><div><h2>字幕模板</h2><p>做成类似即梦的字幕预览卡片，先选风格再合成。</p></div></section>
      <div className="subtitleTemplateGrid">
        {subtitleTemplates.map(item => <button key={item.id} className={selectedSubtitle === item.id ? 'bigSubtitle active' : 'bigSubtitle'} onClick={() => { setSelectedSubtitle(item.id); setActive('creator') }}>
          <div className={`subtitleCanvas ${item.id}`}><strong>{item.sample}</strong><span>{item.position}</span></div>
          <b>{item.name}</b><p>{item.font} · {item.style}</p>
        </button>)}
      </div>
    </>
  }

  function renderAssets() {
    return <>
      <section className="sectionHead"><div><h2>分镜素材</h2><p>素材按“分段素材”管理：项目、学校、地图、资料、生活 B-roll，供成片工作台选择。</p></div><label className="uploadBtn">上传素材<input type="file" multiple accept="image/*,video/*" onChange={e => handleUpload(e.target.files)} /></label></section>
      <div className="assetGrid">
        {assets.map(asset => <div key={asset.id} className={`assetCard ${selectedAssetIds.includes(asset.id) ? 'active' : ''}`}>
          <button className="assetThumb" onClick={() => toggleAsset(asset.id)}>
            {asset.kind === 'image' ? <img src={asset.url} alt="" /> : <video src={asset.url} muted />}
            <span>{asset.kind === 'video' ? '视频' : '图片'}</span>
          </button>
          <b>{asset.original_name || asset.filename}</b>
          <div className="assetActions"><button onClick={() => toggleAsset(asset.id)}>{selectedAssetIds.includes(asset.id) ? '已选' : '选择'}</button><button onClick={() => removeAsset(asset.id)}>删除</button></div>
        </div>)}
        {!assets.length && <div className="emptyCard">还没有素材，先上传项目视频、图片、地图或报告截图。</div>}
      </div>
    </>
  }

  function renderRadar() {
    const run = collector?.run || {}
    return <>
      <section className="radarTop">
        <div><h2>采集雷达</h2><p>雷达只是选题来源，入选热点可以一键送到视频创作工作台。</p></div>
        <div className="collectorControls">
          <label><span>账号数</span><input type="number" min={1} max={120} value={collectorLimit} onChange={e => setCollectorLimit(Math.max(1, Number(e.target.value) || 1))} /></label>
          <label><span>每账号视频</span><input type="number" min={1} max={6} value={limitPerAccount} onChange={e => setLimitPerAccount(Math.max(1, Math.min(6, Number(e.target.value) || 1)))} /></label>
          <label className="switch"><input type="checkbox" checked={quickMode} onChange={e => setQuickMode(e.target.checked)} />快速模式</label>
          <button className="primary" onClick={createCollectorCommand} disabled={!!busy}>{busy === '下发采集命令' ? busy : '下发采集'}</button>
        </div>
      </section>
      <div className="collectorReport">
        <div className="reportSummary">
          <div><span>当前状态</span><strong>{run.status || '等待任务'}</strong><small>{run.stage ? stageLabel(run.stage) : 'ECS 运行 command_worker.py 后会领取命令'}</small></div>
          <div><span>账号进度</span><strong>{run.completed_accounts || 0}/{run.total_accounts || collectorLimit}</strong><small>{run.current_account || '暂无账号'}</small></div>
          <div><span>视频结果</span><strong>{run.success_videos || 0}</strong><small>失败 {run.failed_videos || 0}</small></div>
        </div>
        <div className="eventStream">
          {events.length ? events.map((event, index) => <div key={`${event.id || index}`} className={`eventLine ${event.level || ''}`}>
            <span>{stageLabel(event.stage)}</span>
            <b>{event.message || event.video_title || event.account_name || '采集日志'}</b>
            <small>{event.video_title || event.account_name || event.error_detail || event.created_at}</small>
          </div>) : <div className="emptyInline">暂无采集报告。点击“下发采集”，并确保 ECS 正在运行 command_worker.py。</div>}
        </div>
      </div>
      <section className="sectionHead"><div><h2>今日重点 Top5</h2><p>只保留马来西亚/海外置业方向，国内房产和不相关内容直接过滤。</p></div><button className="soft" onClick={loadHeatItems}>刷新</button></section>
      <div className="heatList">
        {hotItems.length ? hotItems.map((item, index) => <div className="heatCard" key={item.id || index}>
          <span className="rank">{index + 1}</span>
          <div><b>{item.title || '未命名热点'}</b><p>{item.account_name || '未知账号'} · {item.decision || '待判断'} · {item.score ?? item.heat_score ?? 0} 分</p><small>{item.reason || `真实采集：赞${formatCount(item.like_count)} / 评${formatCount(item.comment_count)} / 藏${formatCount(item.favorite_count)} / 分享${formatCount(item.share_count)}`}</small></div>
          <div className="cardBtns"><button onClick={() => useHeatItem(item)}>送入创作</button>{pickUrl(item) && <a href={pickUrl(item)} target="_blank">原链接</a>}<button onClick={() => deleteHeatItem(item)}>删除</button></div>
        </div>) : <div className="emptyCard">暂无真实热点。可以手动导入视频，或让云 Worker 推送数据。</div>}
      </div>
    </>
  }

  function renderOpenClaw() {
    return <>
      <section className="sectionHead"><div><h2>OpenClaw 截流中控</h2><p>后期截流不是爬虫，而是设备自动化：手机/模拟器执行、截图回传、AI 判断线索。</p></div></section>
      <div className="opsGrid">
        <div><h3>设备执行层</h3><p>真实安卓手机优先，模拟器只做测试。OpenClaw 负责打开平台、搜索关键词、看评论/私信、截图回传。</p></div>
        <div><h3>AI 判断层</h3><p>截图/评论/私信进入线索池，AI 判断客户意图、预算、地区、紧急程度。</p></div>
        <div><h3>风控策略</h3><p>第一版只生成回复建议，人工确认发送；稳定后低风险问题再自动回复。</p></div>
        <div><h3>设备 Worker</h3><p>主网站下发任务，本地设备 Worker 领取，失败原因和截图回传到中控台。</p></div>
      </div>
    </>
  }

  function renderPublish() {
    return <>
      <section className="sectionHead"><div><h2>发布账号</h2><p>发布暂时作为预留页。后期由 OpenClaw 真实设备发布，避免爬虫接口风险。</p></div></section>
      <div className="opsGrid"><div><h3>发布队列</h3><p>成片完成后进入发布队列：抖音、小红书、Facebook、TikTok 等平台分账号发布。</p></div><div><h3>人工接管</h3><p>高价值账号动作先人工确认，避免频率过高或话术不合适。</p></div></div>
    </>
  }

  function renderSettings() {
    return <>
      <section className="sectionHead"><div><h2>系统设置</h2><p>本地后端、GPU Worker、OpenClaw 设备层都在这里做状态预留。</p></div><button className="soft" onClick={refreshAll}>刷新状态</button></section>
      <div className="settingsGrid">
        <div><span>API 地址</span><b>{API_BASE}</b><small>{health?.ok ? '后端已连接' : '后端待连接或冷启动'}</small></div>
        <div><span>数据库</span><b>{health?.memory_enabled ? 'Supabase / PostgreSQL 已启用' : '未启用'}</b><small>{health?.memory_status?.mode || 'memory status'}</small></div>
        <div><span>对象存储</span><b>{health?.r2_enabled ? 'R2 已启用' : '本地/临时存储'}</b><small>后期可切 MinIO / NAS</small></div>
        <div><span>本地 Worker</span><b>GPU / OpenClaw 预留</b><small>后期买设备后迁移重任务</small></div>
      </div>
    </>
  }

  function renderMain() {
    if (active === 'creator') return renderCreator()
    if (active === 'avatars') return renderAvatars()
    if (active === 'subtitles') return renderSubtitles()
    if (active === 'assets') return renderAssets()
    if (active === 'radar') return renderRadar()
    if (active === 'openclaw') return renderOpenClaw()
    if (active === 'publish') return renderPublish()
    if (active === 'settings') return renderSettings()
    return renderHome()
  }

  return <div className="app">
    {renderNav()}
    <main className="main">
      {notice && <div className="toast ok">{notice}</div>}
      {error && <div className="toast error">{error}</div>}
      {busy && <div className="toast busy">正在执行：{busy}</div>}
      {renderMain()}
    </main>
  </div>
}

function Pill({ children }: { children: ReactNode }) {
  return <span className="pill">{children}</span>
}

export default App
