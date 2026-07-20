import React, { useEffect, useMemo, useRef, useState } from 'react'
import VideoCreationWizard from './VideoCreationWizard'
import DouyinAccountLibrary from './DouyinAccountLibrary'
import OpenClawWorkbench from './OpenClawWorkbench'
import ContentBrainWorkbench from './ContentBrainWorkbench'
import GraphicWindowWorkbench from './GraphicWindowWorkbench'
import './asset-library-v10-40-8-10.css'
import {
  emptyProjectDraft,
  getStoredToken,
  ProjectDraft,
  WorkspaceTab,
} from './aiVideoApi'
import { API_BASE, ZIP_UPLOAD_API_BASE, apiGet, apiPost, uploadAssets, uploadAssetZip, getAssetZipImportJob, listAssetZipImportJobs, deleteAsset, getAssetIntelligence, getAssetIntelligenceHealth, startAssetIntelligenceAnalysis, getAssetIntelligenceJob, updateAssetIntelligenceControl, updateAssetIntelligence, AssetItem, AssetZipImportJob, AssetIntelligence, AssetIntelligenceJob, AssetIntelligenceListResponse } from './api'

const DRAFT_KEY = 'ai_video_engineering_project_draft_v16'
const LEGACY_DRAFT_KEY = 'ai_video_engineering_project_draft_v15'
const SELECTED_ASSET_KEY = 'ai_video_selected_asset_ids_v16'
const SELECTED_AVATAR_KEY = 'ai_video_selected_avatar_asset_v16'

const ENTRY_CLEAN_KEY = 'ai_video_bridge_v10_10_cleaned_once'
const VIDEO_PROGRESS_RESET_GUARD_KEY = 'ai_video_video_progress_reset_guard_v10_40_8_6'

function entryShouldClean() {
  try {
    const params = new URLSearchParams(window.location.search || '')
    return params.get('reset') === 'workspace' || params.get('clean') === 'workspace'
  } catch {
    return false
  }
}

function draftIsPolluted(draft: any) {
  const text = `${draft?.manualKeywords || ''} ${draft?.manual_keywords || ''} ${draft?.script || ''} ${JSON.stringify(draft?.ai_keyword_insights || [])}`
  return /(62\.?|61\.?|OpenClaw|openclaw|评论区答疑模板|数字人模板|生活分享讲解模板|禁用素材规则|R2素材自动标签|内容大脑|类型：|模式：|用途：|评论反向生成视频|高质量成片沉淀|低质量成片标记)/.test(text)
}

function cleanProjectDraft(draft: ProjectDraft): ProjectDraft {
  const base = { ...emptyProjectDraft(), ...(draft || {}) } as ProjectDraft
  return {
    ...base,
    manualKeywords: String((base as any).manualKeywords || (base as any).manual_keywords || ''),
    manual_keywords: String((base as any).manual_keywords || (base as any).manualKeywords || ''),
    ai_keyword_insights: Array.isArray((base as any).ai_keyword_insights) ? (base as any).ai_keyword_insights : [],
    keyword_insights: Array.isArray((base as any).keyword_insights) ? (base as any).keyword_insights : [],
    script: String((base as any).script || ''),
    segments: Array.isArray((base as any).segments) ? (base as any).segments : [],
    script_segments: Array.isArray((base as any).script_segments) ? (base as any).script_segments : [],
    segment_voice_settings: (base as any).segment_voice_settings && typeof (base as any).segment_voice_settings === 'object' ? (base as any).segment_voice_settings : {},
    manual_shot_plan: Array.isArray((base as any).manual_shot_plan) ? (base as any).manual_shot_plan : [],
    shot_overrides: Array.isArray((base as any).shot_overrides) ? (base as any).shot_overrides : [],
  }
}

type AssetFolderKey = 'all' | 'self' | 'provided' | 'image' | 'collected' | 'ai'

type NavItem = {
  key: WorkspaceTab
  label: string
  desc: string
}

const NAV_ITEMS: NavItem[] = [
  { key: 'pureai', label: '视频创作', desc: '四步向导 · 文案/配音/镜头/成片' },
  { key: 'collect', label: '同行采集', desc: '账号库与爆款参考' },
  { key: 'assets', label: '素材库', desc: 'R2 / 自有素材' },
  { key: 'digital', label: '数字人库', desc: '选择照片/视频出镜' },
  { key: 'leads', label: '获客线索', desc: 'OpenClaw 截流待处理' },
  { key: 'brain', label: '内容大脑', desc: 'Obsidian / 选题知识库' },
  { key: 'graphic', label: '图文窗口', desc: '封面 / 图文 / 发布包装' },
  { key: 'settings', label: '设置', desc: '连接状态与清空' },
]

function loadDraft(): ProjectDraft {
  try {
    if (entryShouldClean()) {
      localStorage.removeItem(DRAFT_KEY)
      localStorage.removeItem(LEGACY_DRAFT_KEY)
            window.sessionStorage.removeItem(
        VIDEO_PROGRESS_RESET_GUARD_KEY,
      )

      const cleanUrl = new URL(window.location.href)
      cleanUrl.searchParams.delete('reset')
      cleanUrl.searchParams.delete('clean')
      cleanUrl.searchParams.delete('resetTs')
      window.history.replaceState(
        {},
        '',
        `${cleanUrl.pathname}${cleanUrl.search}${cleanUrl.hash}`,
      )

      return emptyProjectDraft()
    }
    const raw = localStorage.getItem(DRAFT_KEY) || localStorage.getItem(LEGACY_DRAFT_KEY)
    if (!raw) return emptyProjectDraft()
    const parsed = { ...emptyProjectDraft(), ...JSON.parse(raw) }
    return cleanProjectDraft(parsed)
  } catch {
    return emptyProjectDraft()
  }
}

function saveDraft(draft: ProjectDraft) {
  
  if (window.sessionStorage.getItem(VIDEO_PROGRESS_RESET_GUARD_KEY) === '1') return
try {
    const raw = localStorage.getItem(DRAFT_KEY)
    const previous = raw ? JSON.parse(raw) : {}
    const merged = cleanProjectDraft({ ...previous, ...draft } as ProjectDraft)
    localStorage.setItem(DRAFT_KEY, JSON.stringify(merged))
  } catch {
    localStorage.setItem(DRAFT_KEY, JSON.stringify(cleanProjectDraft(draft)))
  }
}

function tabFromHash(hash: string): WorkspaceTab | null {
  if (['#pure-ai-video', '#full-ai-video', '#one-click-video', '#video-create'].includes(hash)) return 'pureai'
  if (['#douyin-collector', '#douyin-account-library', '#competitor-collector'].includes(hash)) return 'collect'
  if (['#asset-library', '#materials', '#r2-assets'].includes(hash)) return 'assets'
  if (['#openclaw-capture', '#openclaw-workbench', '#lead-acquisition'].includes(hash)) return 'leads'
  if (['#content-brain', '#obsidian-brain', '#knowledge-brain'].includes(hash)) return 'brain'
  if (['#graphic-window', '#publish-package', '#xiaohongshu-package'].includes(hash)) return 'graphic'
  if (['#digital-human-safe', '#digital-human-workspace', '#digital-human-library'].includes(hash)) return 'digital'
  if (['#settings', '#system-settings'].includes(hash)) return 'settings'
  return null
}

function tabHash(tab: WorkspaceTab) {
  if (tab === 'pureai') return '#video-create'
  if (tab === 'collect') return '#douyin-collector'
  if (tab === 'assets') return '#asset-library'
  if (tab === 'leads') return '#openclaw-capture'
  if (tab === 'brain') return '#content-brain'
  if (tab === 'graphic') return '#graphic-window'
  if (tab === 'settings') return '#settings'
  return '#digital-human-library'
}

function tabTitle(tab: WorkspaceTab) {
  if (tab === 'pureai') return '视频创作中控'
  if (tab === 'collect') return '同行采集 / 抖音账号库'
  if (tab === 'assets') return 'R2 素材库'
  if (tab === 'leads') return 'OpenClaw 获客线索'
  if (tab === 'brain') return '内容大脑 / Obsidian 知识库'
  if (tab === 'graphic') return '图文窗口 / 发布包装'
  if (tab === 'settings') return '系统设置'
  return '数字人照片 / 出镜素材库'
}

function tabSubtitle(tab: WorkspaceTab) {
  if (tab === 'pureai') return '主题、文案、TTS-first 配音、镜头、R2 素材、数字人和 OpenClaw 线索统一流转。'
  if (tab === 'collect') return '复用原有 DouyinAccountLibrary，采集同行账号和爆款参考后带入视频创作。'
  if (tab === 'assets') return '复用后端 /api/assets 和 R2 存储，上传、预览、选择真实素材后同步到当前视频。'
  if (tab === 'leads') return '复用 OpenClaw 评论/CSV/JSON 分析链路，筛出目标客户、生成首条回复，等待人工处理。'
  if (tab === 'brain') return '把 OpenClaw 客户问题、同行采集、生成文案和 Obsidian Markdown 沉淀成可复用选题大脑。'
  if (tab === 'graphic') return '在左侧主界面内完成 3 套封面、7 页图文、发布文案和最终交付包装。'
  if (tab === 'settings') return '前台不展示后端 Token，只显示连接状态；支持一键清空本地草稿。'
  return '从已上传到素材库的照片/视频中选择谁出镜，绑定到当前视频，不再使用假卡片。'
}

function folderLabel(folder?: string, kind?: string) {
  if (folder === 'self') return '自己拍的素材'
  if (folder === 'provided') return '别人提供的素材'
  if (folder === 'image') return '图片素材'
  if (folder === 'collected') return '采集视频'
  if (folder === 'ai') return 'AI 生成图'
  return kind === 'video' ? '视频素材' : '图片素材'
}

function formatBytes(value?: number) {
  const n = Number(value || 0)
  if (!n) return '-'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

function assetToContext(asset: AssetItem) {
  return {
    id: asset.id,
    asset_id: asset.id,
    name: asset.original_name || asset.filename,
    original_name: asset.original_name,
    filename: asset.filename,
    kind: asset.kind,
    url: asset.url,
    r2_url: asset.url,
    folder: asset.folder,
    source_type: asset.source_type || 'asset_library',
    selection_source: 'manual',
    selected_by: 'human',
    locked: true,
    duration: Number((asset as any).duration || (asset as any).duration_seconds || 0),
  }
}

function loadSelectedAssetIds(): string[] {
  try {
    const raw = localStorage.getItem(SELECTED_ASSET_KEY)
    const parsed = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? parsed.filter(Boolean) : []
  } catch {
    return []
  }
}

function saveSelectedAssetIds(ids: string[]) {
  localStorage.setItem(SELECTED_ASSET_KEY, JSON.stringify(ids))
}

function useAssets() {
  const [assets, setAssets] = useState<AssetItem[]>([])
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [intelligenceState, setIntelligenceState] = useState<AssetIntelligenceListResponse | null>(null)

  async function refresh(showBusy = true) {
    if (showBusy) setBusy('加载素材')
    setError('')
    try {
      const [assetData, intelligenceData] = await Promise.all([
        apiGet<AssetItem[]>('/api/assets?limit=300&include_r2=true'),
        getAssetIntelligence(3000).catch(() => null),
      ])
      const list = Array.isArray(assetData) ? assetData : []
      const intelligenceMap = new Map<string, AssetIntelligence>()
      if (intelligenceData?.items) {
        intelligenceData.items.forEach((item) => {
          if (item.asset_id) intelligenceMap.set(item.asset_id, item)
          if (item.filename) intelligenceMap.set(item.filename, item)
        })
        setIntelligenceState(intelligenceData)
      }
      setAssets(list.map((asset) => ({
        ...asset,
        intelligence: intelligenceMap.get(asset.id) || intelligenceMap.get(asset.filename),
      })))
    } catch (err: any) {
      setError(err?.message || String(err))
    } finally {
      if (showBusy) setBusy('')
    }
  }

  useEffect(() => {
    refresh()
  }, [])

  return { assets, setAssets, busy, setBusy, error, setError, refresh, intelligenceState, setIntelligenceState }
}


// V10_40_8_10_ASSET_LIBRARY_LANDSCAPE_PIPELINE

type AssetKindFilter = 'all' | 'video' | 'image'
type AssetRatioFilter = 'all' | 'landscape' | 'portrait' | 'square' | 'other' | 'unknown'
type AssetSceneFilter = 'all' | 'interior' | 'architecture' | 'street' | 'nature' | 'people' | 'food' | 'commercial' | 'map' | 'other'

const ASSET_SCENE_OPTIONS: Array<{ value: AssetSceneFilter; label: string }> = [
  { value: 'all', label: '全部场景' },
  { value: 'interior', label: '室内 / 户型' },
  { value: 'architecture', label: '建筑 / 楼盘' },
  { value: 'street', label: '街景 / 交通' },
  { value: 'nature', label: '自然 / 景色' },
  { value: 'people', label: '人物 / 生活' },
  { value: 'food', label: '餐饮 / 食物' },
  { value: 'commercial', label: '商业 / 配套' },
  { value: 'map', label: '地图 / 资料' },
  { value: 'other', label: '其他' },
]

function assetDimensions(asset: AssetItem): { width: number; height: number } {
  const raw = (asset as any)?.raw || {}
  const intelligence = (asset as any)?.intelligence || {}
  const width = Number((asset as any)?.width || raw?.width || intelligence?.width || intelligence?.media?.width || 0)
  const height = Number((asset as any)?.height || raw?.height || intelligence?.height || intelligence?.media?.height || 0)
  return { width, height }
}

function assetRatioGroup(asset: AssetItem): AssetRatioFilter {
  const { width, height } = assetDimensions(asset)
  if (!width || !height) {
    const source = `${(asset as any)?.r2_key || ''} ${asset.url || ''} ${asset.filename || ''}`.toLowerCase()
    if (source.includes('vertical-9x16')) return 'portrait'
    return 'unknown'
  }
  const ratio = width / height
  if (ratio >= 1.35) return 'landscape'
  if (ratio <= 0.80) return 'portrait'
  if (ratio >= 0.90 && ratio <= 1.10) return 'square'
  return 'other'
}

function assetRatioLabel(asset: AssetItem): string {
  const group = assetRatioGroup(asset)
  const { width, height } = assetDimensions(asset)
  const size = width && height ? `${width}×${height} · ` : ''
  if (group === 'landscape') return `${size}横屏`
  if (group === 'portrait') return `${size}竖屏`
  if (group === 'square') return `${size}方形`
  if (group === 'unknown') return '尺寸待识别'
  return `${size}其他比例`
}

function assetSceneGroup(asset: AssetItem): AssetSceneFilter {
  const intelligence: any = (asset as any)?.intelligence || {}
  const text = [
    asset.original_name,
    asset.filename,
    asset.folder,
    intelligence.title,
    intelligence.description,
    intelligence.primary_category,
    intelligence.secondary_category,
    ...(Array.isArray(intelligence.keywords) ? intelligence.keywords : []),
  ].filter(Boolean).join(' ').toLowerCase()

  if (/(餐饮|餐厅|食物|食品|美食|咖啡|甜品|小吃|food|restaurant|cafe)/i.test(text)) return 'food'
  if (/(室内|户型|客厅|卧室|厨房|卫生间|样板间|公寓内部|interior|living room|bedroom)/i.test(text)) return 'interior'
  if (/(楼盘|建筑|外观|大楼|公寓|酒店|写字楼|地标|building|architecture|facade)/i.test(text)) return 'architecture'
  if (/(街道|道路|交通|地铁|轻轨|公交|车流|通勤|street|road|traffic|metro|train)/i.test(text)) return 'street'
  if (/(自然|景观|风景|公园|海景|山景|湖景|绿地|天空|日落|nature|scenery|park|ocean|mountain)/i.test(text)) return 'nature'
  if (/(人物|家庭|生活|客户|顾问|儿童|老人|情侣|人群|people|person|family|lifestyle)/i.test(text)) return 'people'
  if (/(商业|商场|购物|超市|学校|教育|医疗|医院|配套|娱乐|mall|school|hospital|commercial)/i.test(text)) return 'commercial'
  if (/(地图|资料|表格|平面图|区位|路线|报告|截图|map|document|chart|floor plan)/i.test(text)) return 'map'
  return 'other'
}

function terminalJobStatus(value: unknown): boolean {
  return ['done', 'completed', 'partial', 'failed', 'cancelled'].includes(String(value || '').toLowerCase())
}

function LandscapeZipWorkbench({ onImported }: { onImported: () => void }) {
  const [mode, setMode] = useState<'smart_crop' | 'fit_blur'>('smart_crop')
  const [zipJob, setZipJob] = useState<any>(null)
  const [reframeJob, setReframeJob] = useState<any>(null)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const startedReframeRef = useRef('')
  const refreshedRef = useRef('')

  const zipStatus = String(zipJob?.status || '').toLowerCase()
  const reframeStatus = String(reframeJob?.status || '').toLowerCase()
  const zipActive = Boolean(zipJob && !terminalJobStatus(zipStatus))
  const reframeActive = Boolean(reframeJob && !terminalJobStatus(reframeStatus))
  const active = busy || zipActive || reframeActive

  async function uploadLandscapeZip(file: File | null) {
    if (!file) return
    setBusy(true)
    setError('')
    setUploadProgress(0)
    setZipJob(null)
    setReframeJob(null)
    startedReframeRef.current = ''
    refreshedRef.current = ''
    try {
      const next = await uploadAssetZip(file, 'self', 'content', (progress) => setUploadProgress(progress.percent))
      setZipJob(next)
    } catch (err: any) {
      let recovered: AssetZipImportJob | null = null
      try {
        await new Promise((resolve) => window.setTimeout(resolve, 900))
        const recent = await listAssetZipImportJobs(8)
        recovered = (Array.isArray(recent?.jobs) ? recent.jobs : []).find((item) => {
          const sameName = String(item?.zip_name || '') === file.name
          const status = String(item?.status || '').toLowerCase()
          const updatedAt = Date.parse(String(item?.updated_at || item?.created_at || ''))
          const recentEnough = Number.isFinite(updatedAt) ? Date.now() - updatedAt < 20 * 60 * 1000 : true
          return sameName && recentEnough && !['failed', 'cancelled'].includes(status)
        }) || null
      } catch {
        recovered = null
      }
      if (recovered) setZipJob(recovered)
      else setError(err?.message || String(err))
    } finally {
      setBusy(false)
      setUploadProgress(0)
    }
  }

  useEffect(() => {
    const jobId = zipJob?.job_id
    if (!jobId || terminalJobStatus(zipJob?.status)) return
    let cancelled = false
    const poll = async () => {
      try {
        const next = await getAssetZipImportJob(jobId)
        if (!cancelled) setZipJob(next)
      } catch (err: any) {
        if (!cancelled) setError(err?.message || String(err))
      }
    }
    void poll()
    const timer = window.setInterval(() => void poll(), 1600)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [zipJob?.job_id, zipJob?.status])

  useEffect(() => {
    if (!zipJob?.job_id || zipStatus !== 'done') return
    if (startedReframeRef.current === zipJob.job_id) return
    startedReframeRef.current = zipJob.job_id

    const imported = Array.isArray(zipJob?.imported_assets) ? zipJob.imported_assets : []
    const objectKeys = Array.from(new Set(imported
      .filter((item: any) => String(item?.kind || '').toLowerCase() === 'video')
      .map((item: any) => String(item?.r2_key || item?.object_key || item?.key || (item?.filename ? `uploads/${item.filename}` : '')).trim())
      .filter(Boolean)))

    if (!objectKeys.length) {
      setError('这个 ZIP 没有新导入的视频，或视频已被 SHA256 去重。普通照片仍会留在素材库。')
      void onImported()
      return
    }

    void apiPost<any>('/api/assets/r2-reframe/jobs', {
      object_keys: objectKeys,
      output_prefix: 'vertical-9x16',
      mode,
      force: false,
      skip_non_landscape: true,
      register_assets: true,
      delete_local_after_upload: true,
      sample_count: 12,
      max_input_mb: 1200,
      reserve_free_mb: 1536,
      crf: 21,
      preset: 'veryfast',
    }).then((next) => {
      setReframeJob(next?.job || next)
      setError('')
    }).catch((err: any) => setError(err?.message || String(err)))
  }, [zipJob?.job_id, zipStatus, mode, onImported])

  useEffect(() => {
    const jobId = reframeJob?.id || reframeJob?.job_id
    if (!jobId || terminalJobStatus(reframeJob?.status)) return
    let cancelled = false
    const poll = async () => {
      try {
        const next: any = await apiGet(`/api/assets/r2-reframe/jobs/${encodeURIComponent(String(jobId))}`)
        if (!cancelled) setReframeJob(next?.job || next)
      } catch (err: any) {
        if (!cancelled) setError(err?.message || String(err))
      }
    }
    void poll()
    const timer = window.setInterval(() => void poll(), 2500)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [reframeJob?.id, reframeJob?.job_id, reframeJob?.status])

  useEffect(() => {
    const jobId = String(reframeJob?.id || reframeJob?.job_id || '')
    if (!jobId || !terminalJobStatus(reframeJob?.status) || refreshedRef.current === jobId) return
    refreshedRef.current = jobId
    void onImported()
  }, [reframeJob?.id, reframeJob?.job_id, reframeJob?.status, onImported])

  const stage = reframeJob ? 4 : zipJob ? (zipStatus === 'done' ? 3 : 2) : busy ? 1 : 0
  const progress = reframeJob
    ? Math.round(Number(reframeJob?.progress || 0))
    : zipJob
      ? Math.round(Number(zipJob?.progress || 0))
      : uploadProgress
  const resultCount = Array.isArray(reframeJob?.results) ? reframeJob.results.length : Number(reframeJob?.completed_count || 0)
  const failedCount = Array.isArray(reframeJob?.failures) ? reframeJob.failures.length : Number(reframeJob?.failed_count || 0)

  return (
    <section className="aiw-landscapeWorkbench">
      <div className="aiw-landscapeWorkbenchTop">
        <div>
          <p className="aiw-eyebrow">LANDSCAPE ZIP → R2 → SMART 9:16</p>
          <h3>16:9 横屏素材专区</h3>
          <p>上传横屏视频 ZIP 后，系统自动导入 R2、筛出横屏视频、放大保留主要景物并生成新的 9:16 素材。原始横屏永远保留。</p>
        </div>
        <span className="aiw-landscapeBadge">单任务顺序处理 · 低磁盘模式</span>
      </div>

      <div className="aiw-landscapeFlow">
        <span className={stage >= 1 ? 'active' : ''}>1. ZIP 直传</span>
        <span className={stage >= 2 ? 'active' : ''}>2. 导入 R2</span>
        <span className={stage >= 3 ? 'active' : ''}>3. 识别横屏</span>
        <span className={stage >= 4 ? 'active' : ''}>4. 生成 9:16</span>
      </div>

      <div className="aiw-landscapeControls">
        <label>
          素材类型
          <select value="video" disabled>
            <option value="video">横屏视频 ZIP</option>
          </select>
        </label>
        <label>
          转竖方式
          <select value={mode} onChange={(event) => setMode(event.target.value as 'smart_crop' | 'fit_blur')} disabled={active}>
            <option value="smart_crop">智能放大裁切 · 保留主体和主要景色</option>
            <option value="fit_blur">完整画面保全 · 模糊背景托底</option>
          </select>
        </label>
        <label className={`aiw-landscapeUploadButton ${active ? 'busy' : ''}`}>
          {busy ? `ZIP 上传 ${uploadProgress}%` : reframeActive ? `正在转竖 ${progress}%` : zipActive ? `正在导入 ${progress}%` : '上传横屏 ZIP'}
          <input
            type="file"
            accept=".zip,application/zip,application/x-zip-compressed"
            disabled={active}
            onChange={(event) => {
              void uploadLandscapeZip(event.currentTarget.files?.[0] || null)
              event.currentTarget.value = ''
            }}
          />
        </label>
      </div>

      {(zipJob || reframeJob || error) && <div className="aiw-landscapeProgressCard">
        <div className="aiw-landscapeProgressTop">
          <div>
            <strong>{reframeJob?.message || zipJob?.message || '等待处理'}</strong>
            <span>{reframeJob?.current_key || reframeJob?.current_file || zipJob?.current_file || zipJob?.zip_name || ''}</span>
          </div>
          <b>{Math.max(0, Math.min(100, progress))}%</b>
        </div>
        <div className="aiw-progressTrack"><i style={{ width: `${Math.max(0, Math.min(100, progress))}%` }} /></div>
        <div className="aiw-landscapeResultStats">
          <span><b>{zipJob?.summary?.videos || 0}</b>导入视频</span>
          <span><b>{zipJob?.summary?.images || 0}</b>导入照片</span>
          <span><b>{resultCount}</b>转竖完成/跳过</span>
          <span><b>{failedCount}</b>处理失败</span>
        </div>
        {error && <div className="aiw-error">{error}</div>}
      </div>}
    </section>
  )
}

function AssetLibraryPanel({ project, setProject, goTab }: { project: ProjectDraft; setProject: (p: ProjectDraft) => void; goTab: (tab: WorkspaceTab) => void }) {
  const { assets, setAssets, busy, setBusy, error, setError, refresh, intelligenceState, setIntelligenceState } = useAssets()
  const [selectedIds, setSelectedIds] = useState<string[]>(loadSelectedAssetIds)
  const [folder, setFolder] = useState<AssetFolderKey>('all')
  const [uploadFolder, setUploadFolder] = useState<'self' | 'provided' | 'image' | 'collected' | 'ai'>('self')
  const [query, setQuery] = useState('')
  const [zipJob, setZipJob] = useState<AssetZipImportJob | null>(null)
  const [zipUploading, setZipUploading] = useState(false)
  const [zipUploadProgress, setZipUploadProgress] = useState(0)
  const [zipError, setZipError] = useState('')
  const [aiJob, setAiJob] = useState<AssetIntelligenceJob | null>(null)
  const [aiBusy, setAiBusy] = useState('')
  const [aiError, setAiError] = useState('')
  const [aiHealth, setAiHealth] = useState<any>(null)
  const [kindFilter, setKindFilter] = useState<AssetKindFilter>('all')
  const [ratioFilter, setRatioFilter] = useState<AssetRatioFilter>('all')
  const [sceneFilter, setSceneFilter] = useState<AssetSceneFilter>('all')
  const [categoryFilter, setCategoryFilter] = useState('all')
  const [analysisFilter, setAnalysisFilter] = useState('all')
  const [cleanFilter, setCleanFilter] = useState('all')
  const zipFinishedRef = useRef('')

  const selectedAssets = assets.filter((asset) => selectedIds.includes(asset.id))
  const filtered = assets.filter((asset) => {
    const f = (asset.folder || '').toLowerCase()
    const intelligence = asset.intelligence
    const text = `${asset.original_name || ''} ${asset.filename || ''} ${asset.url || ''} ${asset.folder || ''} ${intelligence?.title || ''} ${intelligence?.description || ''} ${intelligence?.primary_category || ''} ${intelligence?.secondary_category || ''} ${(intelligence?.keywords || []).join(' ')}`.toLowerCase()
    if (folder !== 'all' && f !== folder) return false
    if (kindFilter !== 'all' && asset.kind !== kindFilter) return false
    if (ratioFilter !== 'all' && assetRatioGroup(asset) !== ratioFilter) return false
    if (sceneFilter !== 'all' && assetSceneGroup(asset) !== sceneFilter) return false
    if (categoryFilter !== 'all' && intelligence?.primary_category !== categoryFilter) return false
    if (analysisFilter !== 'all' && String(intelligence?.analysis_status || 'pending') !== analysisFilter) return false
    if (cleanFilter !== 'all' && String(intelligence?.cleanliness?.status || 'uncertain') !== cleanFilter) return false
    if (query.trim() && !text.includes(query.trim().toLowerCase())) return false
    return true
  })
  const intelligenceSummary = intelligenceState?.summary || {}
  const intelligenceCategories = intelligenceState?.categories || []
  const autoEnabled = Boolean(intelligenceState?.control?.auto_enabled)

  function syncSelection(ids: string[], list = assets) {
    const unique = Array.from(new Set(ids.filter(Boolean)))
    setSelectedIds(unique)
    saveSelectedAssetIds(unique)
    const chosen = list.filter((asset) => unique.includes(asset.id))
    const context = chosen.map(assetToContext)
    setProject({
      ...project,
      selectedMaterialIds: unique,
      selected_assets: context,
      asset_context: context,
      r2_material_context: context,
      materialSeconds: Math.max(project.materialSeconds || 0, context.length * 4),
    })
  }

  async function handleUpload(files: FileList | null) {
    if (!files || files.length === 0) return
    setBusy('上传素材')
    setError('')
    try {
      const uploaded = await uploadAssets(files, uploadFolder)
      const merged = [...uploaded, ...assets]
      setAssets(merged)
      syncSelection([...selectedIds, ...uploaded.map((item) => item.id)], merged)
    } catch (err: any) {
      setError(err?.message || String(err))
    } finally {
      setBusy('')
    }
  }

  async function handleZipUpload(file: File | null) {
    if (!file) return
    setZipUploading(true)
    setZipUploadProgress(0)
    setZipError('')
    setError('')
    try {
      const job = await uploadAssetZip(file, uploadFolder, 'content', (progress) => {
        setZipUploadProgress(progress.percent)
      })
      zipFinishedRef.current = ''
      setZipJob(job)
      setZipError('')
    } catch (err: any) {
      // 大 ZIP 偶尔会在浏览器端丢失最终响应，但服务器已经接收并开始处理。
      // 先核对最近任务，匹配到同名 ZIP 就恢复真实任务，避免出现“导入成功 + 红色连接失败”。
      let recovered: AssetZipImportJob | null = null
      try {
        await new Promise((resolve) => window.setTimeout(resolve, 900))
        const recent = await listAssetZipImportJobs(5)
        recovered = (Array.isArray(recent?.jobs) ? recent.jobs : []).find((item) => {
          const sameName = String(item?.zip_name || '') === file.name
          const status = String(item?.status || '').toLowerCase()
          const updatedAt = Date.parse(String(item?.updated_at || item?.created_at || ''))
          const recentEnough = Number.isFinite(updatedAt) ? Date.now() - updatedAt < 15 * 60 * 1000 : true
          return sameName && recentEnough && !['failed', 'cancelled'].includes(status)
        }) || null
      } catch {
        recovered = null
      }

      if (recovered) {
        zipFinishedRef.current = ''
        setZipJob(recovered)
        setZipError('')
      } else {
        setZipError(err?.message || String(err))
      }
    } finally {
      setZipUploading(false)
      setZipUploadProgress(0)
    }
  }

  useEffect(() => {
    listAssetZipImportJobs(1)
      .then((result) => {
        const latest = Array.isArray(result?.jobs) ? result.jobs[0] : null
        if (latest) {
          setZipJob(latest)
          if (String(latest.status || '').toLowerCase() === 'done') setZipError('')
        }
      })
      .catch(() => null)
  }, [])

  useEffect(() => {
    const jobId = zipJob?.job_id
    if (!jobId || ['done', 'failed', 'cancelled'].includes(String(zipJob?.status || '').toLowerCase())) return
    let cancelled = false
    const poll = async () => {
      try {
        const next = await getAssetZipImportJob(jobId)
        if (cancelled) return
        setZipJob(next)
        if (next.status === 'done' && zipFinishedRef.current !== next.job_id) {
          zipFinishedRef.current = next.job_id
          setZipError('')
          setError('')
          await refresh()
        }
      } catch (err: any) {
        if (!cancelled) setZipError(err?.message || String(err))
      }
    }
    void poll()
    const timer = window.setInterval(() => void poll(), 1600)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [zipJob?.job_id, zipJob?.status])

  async function refreshIntelligence() {
    try {
      const state = await getAssetIntelligence(3000)
      setIntelligenceState(state)
      setAiJob(state.active_job || null)
      const map = new Map<string, AssetIntelligence>()
      state.items.forEach((item) => {
        if (item.asset_id) map.set(item.asset_id, item)
        if (item.filename) map.set(item.filename, item)
      })
      setAssets((current) => current.map((asset) => ({
        ...asset,
        intelligence: map.get(asset.id) || map.get(asset.filename),
      })))
    } catch (err: any) {
      setAiError(err?.message || String(err))
    }
  }

  async function startIntelligence(assetIds: string[] = [], force = false) {
    setAiBusy(force ? '重新分析' : '分析未处理')
    setAiError('')
    try {
      const result: any = await startAssetIntelligenceAnalysis({
        asset_ids: assetIds,
        force,
        limit: assetIds.length || 300,
      })
      if (result?.job_id) setAiJob(result)
      await refreshIntelligence()
    } catch (err: any) {
      setAiError(err?.message || String(err))
    } finally {
      setAiBusy('')
    }
  }

  async function toggleAutoAnalysis() {
    setAiBusy('更新自动分析')
    setAiError('')
    try {
      const result = await updateAssetIntelligenceControl({ auto_enabled: !autoEnabled })
      setIntelligenceState((current) => current ? { ...current, control: result.control } : current)
      await refreshIntelligence()
    } catch (err: any) {
      setAiError(err?.message || String(err))
    } finally {
      setAiBusy('')
    }
  }

  async function editIntelligence(asset: AssetItem) {
    const current = asset.intelligence
    const title = window.prompt('素材标题', current?.title || asset.original_name || asset.filename)
    if (title === null) return
    const description = window.prompt('素材描述', current?.description || '')
    if (description === null) return
    const category = window.prompt(`一级分类（可选：${intelligenceCategories.join('、')}）`, current?.primary_category || '其他')
    if (category === null) return
    const keywords = window.prompt('关键词，用逗号分隔', (current?.keywords || []).join('，'))
    if (keywords === null) return
    setAiBusy('保存人工修改')
    setAiError('')
    try {
      await updateAssetIntelligence(asset.id, {
        title,
        description,
        primary_category: category,
        keywords: keywords.split(/[,，、;；]+/).map((item) => item.trim()).filter(Boolean),
      })
      await refreshIntelligence()
    } catch (err: any) {
      setAiError(err?.message || String(err))
    } finally {
      setAiBusy('')
    }
  }

  useEffect(() => {
    getAssetIntelligenceHealth().then(setAiHealth).catch(() => null)
  }, [])

  useEffect(() => {
    let cancelled = false
    const poll = async () => {
      if (cancelled) return
      await refreshIntelligence()
    }
    const active = aiJob && !['done', 'failed', 'cancelled'].includes(String(aiJob.status || '').toLowerCase())
    const timer = window.setInterval(() => void poll(), active || autoEnabled ? 5000 : 20000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [aiJob?.job_id, aiJob?.status, autoEnabled])

  async function removeAsset(asset: AssetItem) {
    if (!window.confirm(`确认删除素材「${asset.original_name || asset.filename}」？`)) return
    setBusy('删除素材')
    setError('')
    try {
      await deleteAsset(asset.id)
      const nextAssets = assets.filter((item) => item.id !== asset.id)
      setAssets(nextAssets)
      syncSelection(selectedIds.filter((id) => id !== asset.id), nextAssets)
    } catch (err: any) {
      setError(err?.message || String(err))
    } finally {
      setBusy('')
    }
  }

  return (
    <section className="aiw-card aiw-native-panel">
      <div className="aiw-hero">
        <div>
          <p className="aiw-eyebrow">R2 ASSET LIBRARY / ORIGINAL BACKEND</p>
          <h2>素材库</h2>
          <p>素材按“视频 / 照片 → 画面比例 → 内容场景”管理；横屏 ZIP 可直接进入自动转竖流程，生成后仍回到 R2 素材库。</p>
        </div>
        <span className="aiw-badge ok">R2 已连接 · 横转竖已接入</span>
      </div>

      <LandscapeZipWorkbench onImported={() => void refresh(true)} />

      <div className="aiw-assetFilterShell">
        <div className="aiw-assetFilterTitle">
          <strong>快速筛选</strong>
          <span>先选视频/照片，再看尺寸和场景，不再把分类堆满页面。</span>
        </div>
        <div className="aiw-quickFilterGrid">
          <label>
            类型
            <select value={kindFilter} onChange={(event) => setKindFilter(event.target.value as AssetKindFilter)}>
              <option value="all">全部素材</option>
              <option value="video">视频</option>
              <option value="image">照片</option>
            </select>
          </label>
          <label>
            画面比例
            <select value={ratioFilter} onChange={(event) => setRatioFilter(event.target.value as AssetRatioFilter)}>
              <option value="all">全部比例</option>
              <option value="landscape">横屏 / 16:9</option>
              <option value="portrait">竖屏 / 9:16</option>
              <option value="square">方形 / 1:1</option>
              <option value="other">其他比例</option>
              <option value="unknown">尺寸待识别</option>
            </select>
          </label>
          <label>
            内容场景
            <select value={sceneFilter} onChange={(event) => setSceneFilter(event.target.value as AssetSceneFilter)}>
              {ASSET_SCENE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
          </label>
          <label>
            搜索
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="景色 / 食物 / 室内 / KLCC" />
          </label>
        </div>
        <div className="aiw-assetQuickCounts">
          <span>{assets.filter((item) => item.kind === 'video').length} 视频</span>
          <span>{assets.filter((item) => item.kind === 'image').length} 照片</span>
          <span>{assets.filter((item) => assetRatioGroup(item) === 'landscape').length} 横屏</span>
          <span>{assets.filter((item) => assetRatioGroup(item) === 'portrait').length} 竖屏</span>
          <span>{filtered.length} 当前结果</span>
        </div>
      </div>

      <details className="aiw-assetAdvanced">
        <summary>常规上传与高级筛选</summary>
        <div className="aiw-assetAdvancedBody">
      <div className="aiw-form four">
        <label>
          上传到文件夹
          <select value={uploadFolder} onChange={(e) => setUploadFolder(e.target.value as any)}>
            <option value="self">自己拍的素材</option>
            <option value="provided">别人提供的素材</option>
            <option value="image">图片素材</option>
            <option value="collected">采集视频</option>
            <option value="ai">AI 生成图</option>
          </select>
        </label>
        <label>
          筛选文件夹
          <select value={folder} onChange={(e) => setFolder(e.target.value as AssetFolderKey)}>
            <option value="all">全部素材</option>
            <option value="self">自己拍的素材</option>
            <option value="provided">别人提供的素材</option>
            <option value="image">图片素材</option>
            <option value="collected">采集视频</option>
            <option value="ai">AI 生成图</option>
          </select>
        </label>
        <label>
          搜索
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="KLCC / 户型 / 大堂 / 人物" />
        </label>
        <label>
          连接状态
          <input value={`ECS API ${API_BASE} · ZIP 直传 ${ZIP_UPLOAD_API_BASE} · ${busy || 'ready'}`} readOnly />
        </label>
      </div>

      <div className="aiw-form three aiw-intelligenceFilters">
        <label>
          AI 分类
          <select value={categoryFilter} onChange={(e) => setCategoryFilter(e.target.value)}>
            <option value="all">全部分类</option>
            {intelligenceCategories.map((category) => <option key={category} value={category}>{category}</option>)}
          </select>
        </label>
        <label>
          分析状态
          <select value={analysisFilter} onChange={(e) => setAnalysisFilter(e.target.value)}>
            <option value="all">全部状态</option>
            <option value="pending">待分析</option>
            <option value="processing">分析中</option>
            <option value="completed">分析完成</option>
            <option value="manual">人工修改</option>
            <option value="failed">分析失败</option>
            <option value="need_config">待配置豆包</option>
          </select>
        </label>
        <label>
          净素材状态
          <select value={cleanFilter} onChange={(e) => setCleanFilter(e.target.value)}>
            <option value="all">全部净素材状态</option>
            <option value="passed">通过</option>
            <option value="uncertain">待确认</option>
            <option value="failed">不通过</option>
          </select>
        </label>
      </div>

      <div className="aiw-actions">
        <label className="aiw-primary aiw-uploadButton">
          {busy === '上传素材' ? '上传中...' : '上传图片 / 视频'}
          <input type="file" multiple accept="image/*,video/*" onChange={(e) => { handleUpload(e.target.files); e.currentTarget.value = '' }} />
        </label>
        <label className="aiw-muted aiw-uploadButton aiw-zipUploadButton">
          {zipUploading ? `ZIP 直传 ${zipUploadProgress}%` : zipJob && !['done', 'failed', 'cancelled'].includes(String(zipJob.status).toLowerCase()) ? `ZIP 导入 ${Math.round(Number(zipJob.progress || 0))}%` : '上传 ZIP 自动解压'}
          <input type="file" accept=".zip,application/zip,application/x-zip-compressed" disabled={zipUploading || Boolean(zipJob && !['done', 'failed', 'cancelled'].includes(String(zipJob.status).toLowerCase()))} onChange={(e) => { handleZipUpload(e.target.files?.[0] || null); e.currentTarget.value = '' }} />
        </label>
        <button className="aiw-muted" onClick={() => { void refresh(true) }} disabled={!!busy}>{busy === '加载素材' ? '刷新中...' : '刷新素材'}</button>
        <button className="aiw-purple" onClick={() => goTab('pureai')} disabled={!selectedIds.length}>带入视频创作</button>
      </div>
        </div>
      </details>

      {zipJob && <div className={`aiw-zipImportCard ${String(zipJob.status || '').toLowerCase()}`}>
        <div className="aiw-zipImportTop">
          <div>
            <strong>{zipJob.zip_name || '素材压缩包'}</strong>
            <span>{zipJob.message || '等待导入'}{zipJob.current_file ? ` · ${zipJob.current_file}` : ''}</span>
          </div>
          <b>{Math.max(0, Math.min(100, Math.round(Number(zipJob.progress || 0))))}%</b>
        </div>
        <div className="aiw-progressTrack"><i style={{ width: `${Math.max(0, Math.min(100, Number(zipJob.progress || 0)))}%` }} /></div>
        <div className="aiw-zipStats">
          <span><b>{zipJob.summary?.imported || 0}</b>成功导入</span>
          <span><b>{zipJob.summary?.duplicates || 0}</b>重复跳过</span>
          <span><b>{zipJob.summary?.ignored || 0}</b>格式忽略</span>
          <span><b>{zipJob.summary?.failed || 0}</b>处理失败</span>
          <span><b>{zipJob.summary?.images || 0}</b>图片</span>
          <span><b>{zipJob.summary?.videos || 0}</b>视频</span>
        </div>
        {zipJob.error && <div className="aiw-error">{zipJob.error}</div>}
        {zipJob.failures?.length > 0 && <details className="aiw-zipFailures"><summary>查看失败文件（{zipJob.failures.length}）</summary>{zipJob.failures.slice(0, 50).map((item, index) => <p key={`${item.file}-${index}`}><b>{item.file}</b><span>{item.reason}</span></p>)}</details>}
        <div className="aiw-zipImportFoot">
          <span>ZIP 经 ECS HTTPS 直传，绕过 Cloudflare 请求体限制；导入结束后自动删除临时文件，素材按 SHA256 去重。</span>
          {['done', 'failed', 'cancelled'].includes(String(zipJob.status || '').toLowerCase()) && <button className="aiw-muted" onClick={() => { setZipJob(null); setZipError('') }}>关闭报告</button>}
        </div>
      </div>}

      <details className="aiw-assetIntelligencePanel aiw-collapsiblePanel">
        <summary>AI 自动理解（可选）</summary>
        <div className="aiw-collapsibleBody">
        <div className="aiw-assetIntelligenceHeader">
          <div>
            <p className="aiw-eyebrow">DOUBAO ASSET UNDERSTANDING</p>
            <h3>豆包素材理解与智能分类</h3>
            <p>图片直接理解；视频自动抽取 3-5 张关键帧。后台写入标题、描述、分类、关键词、质量和净素材结果。</p>
          </div>
          <span className={`aiw-badge ${aiHealth?.configured ? 'ok' : ''}`}>{aiHealth?.configured ? `豆包已配置 · ${aiHealth?.model || ''}` : '等待 ARK 配置'}</span>
        </div>
        <div className="aiw-intelligenceMetrics">
          <span><b>{intelligenceSummary.completed || 0}</b>分析完成</span>
          <span><b>{intelligenceSummary.pending || 0}</b>待分析</span>
          <span><b>{intelligenceSummary.processing || 0}</b>分析中</span>
          <span><b>{intelligenceSummary.failed || 0}</b>分析失败</span>
          <span><b>{intelligenceSummary.clean_passed || 0}</b>净素材通过</span>
          <span><b>{intelligenceSummary.clean_failed || 0}</b>明确不通过</span>
        </div>
        {aiJob && <div className={`aiw-aiJob ${String(aiJob.status || '').toLowerCase()}`}>
          <div><b>{aiJob.message || '豆包正在分析素材'}</b><span>{aiJob.current_file || ''}</span></div>
          <strong>{Math.round(Number(aiJob.progress || 0))}%</strong>
          <div className="aiw-progressTrack"><i style={{ width: `${Math.max(0, Math.min(100, Number(aiJob.progress || 0)))}%` }} /></div>
        </div>}
        <div className="aiw-actions">
          <button className="aiw-purple" disabled={!!aiBusy || Boolean(aiJob && !['done', 'failed', 'cancelled'].includes(String(aiJob.status || '').toLowerCase()))} onClick={() => startIntelligence([], false)}>{aiBusy === '分析未处理' ? '正在启动...' : '豆包分析未处理素材'}</button>
          <button className="aiw-muted" disabled={!!aiBusy} onClick={toggleAutoAnalysis}>{autoEnabled ? '暂停后台自动分析' : '开启后台自动分析'}</button>
          <button className="aiw-muted" disabled={selectedIds.length === 0 || !!aiBusy} onClick={() => startIntelligence(selectedIds, true)}>重新分析本次已选</button>
          <button className="aiw-muted" disabled={!!aiBusy} onClick={refreshIntelligence}>刷新分析结果</button>
        </div>
        {aiError && <div className="aiw-error">{aiError}</div>}
        </div>
      </details>

      <div className="aiw-metrics">
        <div><b>{assets.length}</b><span>素材总数</span></div>
        <div><b>{selectedIds.length}</b><span>本次已选</span></div>
        <div><b>{selectedAssets.filter((a) => a.kind === 'video').length}</b><span>视频素材</span></div>
        <div><b>{selectedAssets.filter((a) => a.kind === 'image').length}</b><span>图片素材</span></div>
      </div>

      {zipError && <div className="aiw-error aiw-zipTransportError">{zipError}</div>}
      {error && <div className="aiw-error">{error}</div>}

      <div className="aiw-twoCol">
        <div className="aiw-panel">
          <h3>R2 / 素材列表</h3>
          <div className="aiw-assetGrid">
            {filtered.length === 0 && <div className="aiw-info">还没有素材，或者当前筛选条件没有匹配。</div>}
            {filtered.map((asset) => {
              const selected = selectedIds.includes(asset.id)
              return (
                <div className={selected ? 'aiw-assetCard selected' : 'aiw-assetCard'} key={asset.id}>
                  <button className="aiw-assetPreview" onClick={() => window.open(asset.url, '_blank')}>
                    {asset.kind === 'video' ? <video src={asset.url} muted /> : <img src={asset.url} alt={asset.original_name || asset.filename} />}
                  </button>
                  <strong title={asset.intelligence?.title || asset.original_name || asset.filename}>{asset.intelligence?.title || asset.original_name || asset.filename}</strong>
                  <span className="aiw-assetOriginalName">{asset.original_name || asset.filename}</span>
                  <span>{folderLabel(asset.folder, asset.kind)} · {asset.kind === 'video' ? '视频' : '照片'} · {formatBytes(asset.size_bytes)}</span>
            <em className={`aiw-ratioBadge ${assetRatioGroup(asset)}`}>{assetRatioLabel(asset)}</em>
                  <div className="aiw-intelligenceChips">
                    <em className={`status ${asset.intelligence?.analysis_status || 'pending'}`}>{asset.intelligence?.analysis_status === 'completed' ? '已分析' : asset.intelligence?.analysis_status === 'processing' ? '分析中' : asset.intelligence?.analysis_status === 'manual' ? '人工修改' : asset.intelligence?.analysis_status === 'failed' ? '分析失败' : asset.intelligence?.analysis_status === 'need_config' ? '待配置' : '待分析'}</em>
                    {asset.intelligence?.primary_category && <em>{asset.intelligence.primary_category}</em>}
                    {asset.intelligence?.secondary_category && <em>{asset.intelligence.secondary_category}</em>}
                    {asset.intelligence?.quality_score !== undefined && <em>质量 {asset.intelligence.quality_score}</em>}
                    {asset.intelligence?.cleanliness?.status && <em className={`clean ${asset.intelligence.cleanliness.status}`}>{asset.intelligence.cleanliness.status === 'passed' ? '净素材通过' : asset.intelligence.cleanliness.status === 'failed' ? '净素材不通过' : '待确认'}</em>}
                  </div>
                  {asset.intelligence?.description && <p className="aiw-assetDescription">{asset.intelligence.description}</p>}
                  {asset.intelligence?.keywords?.length ? <div className="aiw-assetKeywords">{asset.intelligence.keywords.slice(0, 6).map((item) => <i key={item}>{item}</i>)}</div> : null}
                  {asset.intelligence?.error && <small className="aiw-assetAiError">{asset.intelligence.error}</small>}
                  <div className="aiw-actions small aiw-assetCardActions">
                    <button className={selected ? 'aiw-purple' : 'aiw-muted'} onClick={() => syncSelection(selected ? selectedIds.filter((id) => id !== asset.id) : [...selectedIds, asset.id])}>{selected ? '已带入' : '带入视频'}</button>
                    <a className="aiw-linkButton" href={asset.url} target="_blank" rel="noreferrer">预览</a>
                    <button className="aiw-muted" onClick={() => startIntelligence([asset.id], true)}>AI分析</button>
                    <button className="aiw-muted" onClick={() => editIntelligence(asset)}>编辑</button>
                    <button className="aiw-danger" onClick={() => removeAsset(asset)}>删除</button>
                  </div>
                </div>
              )
            })}
          </div>
        </div>

        <div className="aiw-panel aiw-selectedAssetsPanel">
          <div className="aiw-selectedAssetsHeader">
            <div>
              <h3>本次已选素材</h3>
              <p className="aiw-mutedText">直接查看实际图片或视频。移出只影响本次视频；删除会从素材库和 R2 记录中删除。</p>
            </div>
            <button
              className="aiw-muted"
              disabled={selectedAssets.length === 0}
              onClick={() => syncSelection([])}
            >
              全部移出本次视频
            </button>
          </div>

          <div className="aiw-selectedAssetGrid">
            {selectedAssets.length === 0 && <div className="aiw-info">还没选择素材。可以先上传，或从左边素材卡片点击“带入视频”。</div>}
            {selectedAssets.map((asset, index) => (
              <article className="aiw-selectedAssetCard" key={asset.id}>
                <div className="aiw-selectedAssetMedia">
                  <span className="aiw-selectedAssetIndex">{index + 1}</span>
                  <span className={`aiw-selectedAssetKind ${asset.kind}`}>{asset.kind === 'video' ? '视频' : '图片'}</span>
                  {asset.kind === 'video'
                    ? <video src={asset.url} controls muted playsInline preload="metadata" />
                    : <a href={asset.url} target="_blank" rel="noreferrer"><img src={asset.url} alt={asset.original_name || asset.filename} loading="lazy" /></a>}
                </div>
                <div className="aiw-selectedAssetBody">
                  <strong title={asset.intelligence?.title || asset.original_name || asset.filename}>{asset.intelligence?.title || asset.original_name || asset.filename}</strong>
                  <span>{folderLabel(asset.folder, asset.kind)} · {assetRatioLabel(asset)} · {formatBytes(asset.size_bytes)}</span>
                  {asset.intelligence?.description && <p className="aiw-selectedAssetDescription">{asset.intelligence.description}</p>}
                  {asset.intelligence?.primary_category && <div className="aiw-intelligenceChips"><em>{asset.intelligence.primary_category}</em>{asset.intelligence.secondary_category && <em>{asset.intelligence.secondary_category}</em>}</div>}
                  <div className="aiw-actions small aiw-selectedAssetActions">
                    <button
                      className="aiw-muted"
                      onClick={() => syncSelection(selectedIds.filter((id) => id !== asset.id))}
                    >
                      移出本次视频
                    </button>
                    <button className="aiw-danger" onClick={() => removeAsset(asset)}>
                      删除素材库
                    </button>
                  </div>
                </div>
              </article>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}

function DigitalHumanLibraryPanel({ project, setProject, goTab }: { project: ProjectDraft; setProject: (p: ProjectDraft) => void; goTab: (tab: WorkspaceTab) => void }) {
  const { assets, busy, error, refresh } = useAssets()
  const imageAssets = assets.filter((asset) => asset.kind === 'image')
  const videoAssets = assets.filter((asset) => asset.kind === 'video')
  const [avatarId, setAvatarId] = useState(() => localStorage.getItem(SELECTED_AVATAR_KEY) || String(project.digitalHumanAvatarId || ''))
  const [drivingId, setDrivingId] = useState(String(project.digitalHumanDrivingVideoId || ''))
  const [role, setRole] = useState(String(project.digitalHumanRole || '地产顾问'))
  const [providers, setProviders] = useState<any[]>([])
  const [providerStatus, setProviderStatus] = useState<any>(null)
  const [providerBusy, setProviderBusy] = useState('')
  const [providerError, setProviderError] = useState('')
  const selectedAvatar = assets.find((asset) => asset.id === avatarId)
  const selectedDriving = assets.find((asset) => asset.id === drivingId)

  function applyAvatar(nextAvatarId = avatarId, nextDrivingId = drivingId) {
    const avatar = assets.find((asset) => asset.id === nextAvatarId)
    const driving = assets.find((asset) => asset.id === nextDrivingId)
    if (nextAvatarId) localStorage.setItem(SELECTED_AVATAR_KEY, nextAvatarId)
    setProject({
      ...project,
      digitalHumanRole: role,
      digitalHumanMode: avatar ? 'asset_selected' : 'skip',
      digitalHumanAvatarId: avatar?.id || '',
      digitalHumanAvatarUrl: avatar?.url || '',
      digitalHumanDrivingVideoId: driving?.id || '',
      digitalHumanDrivingVideoUrl: driving?.url || '',
      avatar_config: {
        enabled: Boolean(avatar),
        role,
        avatar_asset: avatar ? assetToContext(avatar) : null,
        driving_video_asset: driving ? assetToContext(driving) : null,
        source: 'original_assets_library',
      },
    })
  }

  async function refreshProviders() {
    setProviderBusy('检查数字人引擎')
    setProviderError('')
    try {
      const [providerData, statusData] = await Promise.all([
        apiGet<any>('/api/digital-human/providers').catch(() => []),
        project.digitalHumanJobId
          ? apiGet<any>(`/api/digital-human/status/${encodeURIComponent(String(project.digitalHumanJobId))}`).catch(() => null)
          : Promise.resolve(null),
      ])
      const list = Array.isArray(providerData)
        ? providerData
        : Array.isArray(providerData?.providers)
          ? providerData.providers
          : Array.isArray(providerData?.items)
            ? providerData.items
            : []
      setProviders(list)
      setProviderStatus(statusData)
    } catch (err: any) {
      setProviderError(err?.message || String(err))
    } finally {
      setProviderBusy('')
    }
  }

  useEffect(() => {
    if (assets.length) applyAvatar(avatarId, drivingId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assets.length])

  useEffect(() => {
    void refreshProviders()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project.digitalHumanJobId])

  return (
    <section className="aiw-card aiw-native-panel">
      <div className="aiw-hero">
        <div>
          <p className="aiw-eyebrow">DIGITAL HUMAN / ASSET BASED</p>
          <h2>数字人库</h2>
          <p>数字人不再是假卡片。这里直接从 R2 素材库里选已上传的照片/视频，决定谁出镜，并绑定到当前视频。</p>
        </div>
        <span className="aiw-badge ok">已接原素材库 + 引擎状态</span>
      </div>

      <div className="aiw-form four">
        <label>
          角色备注
          <input value={role} onChange={(e) => setRole(e.target.value)} placeholder="例如：房产顾问 / 老板 / 置业讲解员" />
        </label>
        <label>
          数字人照片/形象
          <select value={avatarId} onChange={(e) => { setAvatarId(e.target.value); applyAvatar(e.target.value, drivingId) }}>
            <option value="">不启用数字人</option>
            {imageAssets.map((asset) => <option key={asset.id} value={asset.id}>{asset.original_name || asset.filename}</option>)}
            {videoAssets.map((asset) => <option key={asset.id} value={asset.id}>视频形象 · {asset.original_name || asset.filename}</option>)}
          </select>
        </label>
        <label>
          动作/参考视频，可选
          <select value={drivingId} onChange={(e) => { setDrivingId(e.target.value); applyAvatar(avatarId, e.target.value) }}>
            <option value="">不使用动作参考</option>
            {videoAssets.map((asset) => <option key={asset.id} value={asset.id}>{asset.original_name || asset.filename}</option>)}
          </select>
        </label>
        <label>
          素材状态
          <input value={`${assets.length} 个素材 · ${busy || 'ready'}`} readOnly />
        </label>
      </div>

      <div className="aiw-form two">
        <label>
          可用数字人引擎
          <input
            value={
              providers.length
                ? providers.map((item: any) => String(item?.name || item?.label || item?.id || item?.provider || '')).filter(Boolean).join(' / ')
                : providerBusy || '等待后端返回'
            }
            readOnly
          />
        </label>
        <label>
          当前数字人任务
          <input
            value={
              providerStatus?.status ||
              providerStatus?.stage ||
              (project.digitalHumanJobId ? `任务 ${project.digitalHumanJobId}` : '尚未生成')
            }
            readOnly
          />
        </label>
      </div>

      <div className="aiw-actions">
        <button className="aiw-muted" onClick={() => { void refresh(true) }}>刷新素材库</button>
        <button className="aiw-muted" onClick={() => void refreshProviders()} disabled={!!providerBusy}>{providerBusy || '刷新引擎状态'}</button>
        <button className="aiw-purple" onClick={() => { applyAvatar(); goTab('pureai') }} disabled={!selectedAvatar}>用于当前视频</button>
        <button className="aiw-muted" onClick={() => goTab('assets')}>先去上传照片/视频</button>
      </div>

      {error && <div className="aiw-error">{error}</div>}
      {providerError && <div className="aiw-error">{providerError}</div>}

      <div className="aiw-twoCol">
        <div className="aiw-panel">
          <h3>当前出镜人</h3>
          {!selectedAvatar && <div className="aiw-info">还没有选择数字人照片/视频。请先在素材库上传照片，或从下方列表选择。</div>}
          {selectedAvatar && (
            <div className="aiw-avatarPreview">
              {selectedAvatar.kind === 'video' ? <video src={selectedAvatar.url} controls /> : <img src={selectedAvatar.url} alt={selectedAvatar.original_name || selectedAvatar.filename} />}
              <strong>{selectedAvatar.original_name || selectedAvatar.filename}</strong>
              <span>{role} · 已写入 avatar_config</span>
            </div>
          )}
          {selectedDriving && <div className="aiw-info">动作参考视频：{selectedDriving.original_name || selectedDriving.filename}</div>}
        </div>

        <div className="aiw-panel">
          <h3>可选照片 / 视频</h3>
          <div className="aiw-assetGrid compact">
            {assets.length === 0 && <div className="aiw-info">素材库暂无照片或视频。先去“素材库”上传。</div>}
            {assets.slice(0, 18).map((asset) => (
              <div className={asset.id === avatarId ? 'aiw-assetCard selected' : 'aiw-assetCard'} key={asset.id}>
                <button className="aiw-assetPreview" onClick={() => { setAvatarId(asset.id); applyAvatar(asset.id, drivingId) }}>
                  {asset.kind === 'video' ? <video src={asset.url} muted /> : <img src={asset.url} alt={asset.original_name || asset.filename} />}
                </button>
                <strong>{asset.original_name || asset.filename}</strong>
                <span>{asset.kind} · {folderLabel(asset.folder, asset.kind)}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}

function SettingsPanel({ project, setProject }: { project: ProjectDraft; setProject: (p: ProjectDraft) => void }) {
  const [health, setHealth] = useState<any>(null)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const tokenReady = Boolean(getStoredToken())

  async function checkHealth() {
    setBusy('检查连接')
    setError('')
    try {
      const data = await apiGet<any>('/api/video/production/health')
      setHealth(data)
    } catch (err: any) {
      setError(err?.message || String(err))
    } finally {
      setBusy('')
    }
  }

  function clearLocalData() {
    if (!window.confirm('确认清空本地草稿、选中素材、数字人选择和本地 Token？这不会删除 R2 和后端素材。')) return
    Object.keys(localStorage).forEach((key) => {
      if (key.startsWith('ai_video') || key.includes('AI_VIDEO')) localStorage.removeItem(key)
    })
    setProject(emptyProjectDraft())
    setHealth(null)
  }

  useEffect(() => {
    checkHealth()
  }, [])

  return (
    <section className="aiw-card aiw-native-panel">
      <div className="aiw-hero">
        <div>
          <p className="aiw-eyebrow">SETTINGS / SAFE FRONTEND</p>
          <h2>设置</h2>
          <p>前台不再展示后端 Token 输入框。这里只显示连接状态和默认策略，避免客户误操作密钥。</p>
        </div>
        <span className={health?.ok ? 'aiw-badge ok' : 'aiw-badge danger'}>{health?.ok ? '后端已连接' : '待检查'}</span>
      </div>

      <div className="aiw-form two">
        <label>
          后端地址
          <input value={API_BASE} readOnly />
        </label>
        <label>
          认证状态
          <input value={tokenReady ? '已在本地静默保存，不在页面展示' : '未检测到本地 Token；公开接口可用，受保护接口需运维预置'} readOnly />
        </label>
        <label>
          当前主题
          <input value={project.topic} onChange={(e) => setProject({ ...project, topic: e.target.value })} />
        </label>
        <label>
          默认市场
          <input value={project.market} onChange={(e) => setProject({ ...project, market: e.target.value })} />
        </label>
      </div>

      <div className="aiw-actions">
        <button className="aiw-primary" onClick={checkHealth} disabled={!!busy}>{busy || '重新检查后端'}</button>
        <button className="aiw-danger" onClick={clearLocalData}>一键清空本地数据</button>
      </div>

      {error && <div className="aiw-error">{error}</div>}
      <details className="aiw-json" open>
        <summary>连接检查结果</summary>
        <pre>{JSON.stringify(health || { ok: false, status: 'not_checked' }, null, 2)}</pre>
      </details>
    </section>
  )
}

export default function ProductWorkspaceBridge() {
  const initialTab = tabFromHash(window.location.hash) || 'pureai'
  const [tab, setTab] = useState<WorkspaceTab>(initialTab)
  const [project, setProjectState] = useState<ProjectDraft>(loadDraft)
  const [notice, setNotice] = useState('')

  function setProject(next: ProjectDraft) {
    setProjectState(next)
    saveDraft(next)
  }

  function open(next: WorkspaceTab) {
    setTab(next)
    const hash = tabHash(next)
    if (window.location.hash !== hash) window.history.replaceState(null, '', hash)
  }

  useEffect(() => {
    const onHash = () => {
      const next = tabFromHash(window.location.hash)
      if (next) setTab(next)
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  useEffect(() => {
    setNotice('')
  }, [tab])

  function renderBody() {
    if (tab === 'pureai') return <VideoCreationWizard project={project} setProject={setProject} goTab={open} />
    if (tab === 'collect') return <DouyinAccountLibrary project={project} setProject={setProject} goTab={open} />
    if (tab === 'assets') return <AssetLibraryPanel project={project} setProject={setProject} goTab={open} />
    if (tab === 'digital') return <DigitalHumanLibraryPanel project={project} setProject={setProject} goTab={open} />
    if (tab === 'leads') return <OpenClawWorkbench project={project} setProject={setProject} goTab={open} />
    if (tab === 'brain') return <ContentBrainWorkbench project={project} setProject={setProject} goTab={open} />
    if (tab === 'graphic') return <GraphicWindowWorkbench project={project} goTab={open} />
    return <SettingsPanel project={project} setProject={setProject} />
  }

  return (
    <div className="aiw-consoleRoot">
      <aside className="aiw-sideNav">
        <div className="aiw-brand">
          <strong>AI-VIDEO</strong>
          <span>房产短视频增长中控</span>
        </div>
        <nav>
          {NAV_ITEMS.map((item) => (
            <button key={item.key} className={tab === item.key ? 'active' : ''} onClick={() => open(item.key)}>
              <strong>{item.label}</strong>
              <span>{item.desc}</span>
            </button>
          ))}
        </nav>
        <div className="aiw-sideCard">
          <b>TTS-first 联动</b>
          <span>文案 → 配音 → 镜头 → R2素材/数字人 → OpenClaw获客</span>
        </div>
      </aside>

      <main className="aiw-consoleMain">
        {notice && <div className="aiw-topNotice"><span>{notice}</span><button onClick={() => setNotice('')}>×</button></div>}
        <header className="aiw-consoleHeader">
          <div>
            <p>AI-VIDEO 中控</p>
            <h1>{tabTitle(tab)}</h1>
            <span>{tabSubtitle(tab)}</span>
          </div>
          <div className="aiw-consoleStatus">
            <b>{getStoredToken() ? '已连接' : '公开模式'}</b>
            <span>{API_BASE.replace(/^https?:\/\//, '')}</span>
          </div>
        </header>
        <div className="aiw-consoleBody">{renderBody()}</div>
      </main>
    </div>
  )
}

// V10.40.8.5.2 TTS ASSET AUTOFILL
