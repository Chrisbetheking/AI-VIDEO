import React, { useEffect, useMemo, useState } from 'react'
import VideoCreationWizard from './VideoCreationWizard'
import DouyinAccountLibrary from './DouyinAccountLibrary'
import OpenClawWorkbench from './OpenClawWorkbench'
import ContentBrainWorkbench from './ContentBrainWorkbench'
import {
  emptyProjectDraft,
  getStoredToken,
  ProjectDraft,
  WorkspaceTab,
} from './aiVideoApi'
import { API_BASE, apiGet, uploadAssets, deleteAsset, AssetItem } from './api'

const DRAFT_KEY = 'ai_video_engineering_project_draft_v16'
const LEGACY_DRAFT_KEY = 'ai_video_engineering_project_draft_v15'
const SELECTED_ASSET_KEY = 'ai_video_selected_asset_ids_v16'
const SELECTED_AVATAR_KEY = 'ai_video_selected_avatar_asset_v16'

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
  { key: 'settings', label: '设置', desc: '连接状态与清空' },
]

function loadDraft(): ProjectDraft {
  try {
    const raw = localStorage.getItem(DRAFT_KEY) || localStorage.getItem(LEGACY_DRAFT_KEY)
    return raw ? { ...emptyProjectDraft(), ...JSON.parse(raw) } : emptyProjectDraft()
  } catch {
    return emptyProjectDraft()
  }
}

function saveDraft(draft: ProjectDraft) {
  localStorage.setItem(DRAFT_KEY, JSON.stringify(draft))
}

function tabFromHash(hash: string): WorkspaceTab | null {
  if (['#pure-ai-video', '#full-ai-video', '#one-click-video', '#video-create'].includes(hash)) return 'pureai'
  if (['#douyin-collector', '#douyin-account-library', '#competitor-collector'].includes(hash)) return 'collect'
  if (['#asset-library', '#materials', '#r2-assets'].includes(hash)) return 'assets'
  if (['#openclaw-capture', '#openclaw-workbench', '#lead-acquisition'].includes(hash)) return 'leads'
  if (['#content-brain', '#obsidian-brain', '#knowledge-brain'].includes(hash)) return 'brain'
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
  if (tab === 'settings') return '#settings'
  return '#digital-human-library'
}

function tabTitle(tab: WorkspaceTab) {
  if (tab === 'pureai') return '视频创作中控'
  if (tab === 'collect') return '同行采集 / 抖音账号库'
  if (tab === 'assets') return 'R2 素材库'
  if (tab === 'leads') return 'OpenClaw 获客线索'
  if (tab === 'brain') return '内容大脑 / Obsidian 知识库'
  if (tab === 'settings') return '系统设置'
  return '数字人照片 / 出镜素材库'
}

function tabSubtitle(tab: WorkspaceTab) {
  if (tab === 'pureai') return '主题、文案、TTS-first 配音、镜头、R2 素材、数字人和 OpenClaw 线索统一流转。'
  if (tab === 'collect') return '复用原有 DouyinAccountLibrary，采集同行账号和爆款参考后带入视频创作。'
  if (tab === 'assets') return '复用后端 /api/assets 和 R2 存储，上传、预览、选择真实素材后同步到当前视频。'
  if (tab === 'leads') return '复用 OpenClaw 评论/CSV/JSON 分析链路，筛出目标客户、生成首条回复，等待人工处理。'
  if (tab === 'brain') return '把 OpenClaw 客户问题、同行采集、生成文案和 Obsidian Markdown 沉淀成可复用选题大脑。'
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
    name: asset.original_name || asset.filename,
    filename: asset.filename,
    kind: asset.kind,
    url: asset.url,
    r2_url: asset.url,
    folder: asset.folder,
    source_type: asset.source_type || 'asset_library',
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

  async function refresh() {
    setBusy('加载素材')
    setError('')
    try {
      const data = await apiGet<AssetItem[]>('/api/assets')
      setAssets(Array.isArray(data) ? data : [])
    } catch (err: any) {
      setError(err?.message || String(err))
    } finally {
      setBusy('')
    }
  }

  useEffect(() => {
    refresh()
  }, [])

  return { assets, setAssets, busy, setBusy, error, setError, refresh }
}

function AssetLibraryPanel({ project, setProject, goTab }: { project: ProjectDraft; setProject: (p: ProjectDraft) => void; goTab: (tab: WorkspaceTab) => void }) {
  const { assets, setAssets, busy, setBusy, error, setError, refresh } = useAssets()
  const [selectedIds, setSelectedIds] = useState<string[]>(loadSelectedAssetIds)
  const [folder, setFolder] = useState<AssetFolderKey>('all')
  const [uploadFolder, setUploadFolder] = useState<'self' | 'provided' | 'image' | 'collected' | 'ai'>('self')
  const [query, setQuery] = useState('')

  const selectedAssets = assets.filter((asset) => selectedIds.includes(asset.id))
  const filtered = assets.filter((asset) => {
    const f = (asset.folder || '').toLowerCase()
    const text = `${asset.original_name || ''} ${asset.filename || ''} ${asset.url || ''} ${asset.folder || ''}`.toLowerCase()
    if (folder !== 'all' && f !== folder) return false
    if (query.trim() && !text.includes(query.trim().toLowerCase())) return false
    return true
  })

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
          <p>这里直接走你原来的 /api/assets 和 R2 存储。上传或选择素材后，会写入当前视频的 asset_context / r2_material_context。</p>
        </div>
        <span className="aiw-badge ok">已接原后端素材库</span>
      </div>

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
          <input value={`${API_BASE} · ${busy || 'ready'}`} readOnly />
        </label>
      </div>

      <div className="aiw-actions">
        <label className="aiw-primary aiw-uploadButton">
          {busy === '上传素材' ? '上传中...' : '上传到 R2 素材库'}
          <input type="file" multiple accept="image/*,video/*" onChange={(e) => { handleUpload(e.target.files); e.currentTarget.value = '' }} />
        </label>
        <button className="aiw-muted" onClick={refresh} disabled={!!busy}>{busy === '加载素材' ? '刷新中...' : '刷新素材'}</button>
        <button className="aiw-purple" onClick={() => goTab('pureai')} disabled={!selectedIds.length}>带入视频创作</button>
      </div>

      <div className="aiw-metrics">
        <div><b>{assets.length}</b><span>素材总数</span></div>
        <div><b>{selectedIds.length}</b><span>本次已选</span></div>
        <div><b>{selectedAssets.filter((a) => a.kind === 'video').length}</b><span>视频素材</span></div>
        <div><b>{selectedAssets.filter((a) => a.kind === 'image').length}</b><span>图片素材</span></div>
      </div>

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
                  <strong title={asset.original_name || asset.filename}>{asset.original_name || asset.filename}</strong>
                  <span>{folderLabel(asset.folder, asset.kind)} · {asset.kind} · {formatBytes(asset.size_bytes)}</span>
                  <div className="aiw-actions small">
                    <button className={selected ? 'aiw-purple' : 'aiw-muted'} onClick={() => syncSelection(selected ? selectedIds.filter((id) => id !== asset.id) : [...selectedIds, asset.id])}>{selected ? '已带入' : '带入视频'}</button>
                    <a className="aiw-linkButton" href={asset.url} target="_blank" rel="noreferrer">预览</a>
                    <button className="aiw-danger" onClick={() => removeAsset(asset)}>删除</button>
                  </div>
                </div>
              )
            })}
          </div>
        </div>

        <div className="aiw-panel">
          <h3>本次视频素材上下文</h3>
          <p className="aiw-mutedText">这些会进入项目草稿，并传给视频生成链路做真实素材优先、R2 素材引用和镜头绑定。</p>
          <div className="aiw-segmentList">
            {selectedAssets.length === 0 && <div className="aiw-info">还没选择素材。可以先上传，或从左边素材卡片点击“带入视频”。</div>}
            {selectedAssets.map((asset, index) => (
              <div className="aiw-segment" key={asset.id}>
                <b>{index + 1}. {asset.original_name || asset.filename}</b>
                <em>{folderLabel(asset.folder, asset.kind)} · {asset.kind}</em>
                <p>{asset.url}</p>
                <span>已写入 asset_context / r2_material_context</span>
              </div>
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

  useEffect(() => {
    if (assets.length) applyAvatar(avatarId, drivingId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assets.length])

  return (
    <section className="aiw-card aiw-native-panel">
      <div className="aiw-hero">
        <div>
          <p className="aiw-eyebrow">DIGITAL HUMAN / ASSET BASED</p>
          <h2>数字人库</h2>
          <p>数字人不再是假卡片。这里直接从 R2 素材库里选已上传的照片/视频，决定谁出镜，并绑定到当前视频。</p>
        </div>
        <span className="aiw-badge ok">已接原素材库</span>
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

      <div className="aiw-actions">
        <button className="aiw-muted" onClick={refresh}>刷新素材库</button>
        <button className="aiw-purple" onClick={() => { applyAvatar(); goTab('pureai') }} disabled={!selectedAvatar}>用于当前视频</button>
        <button className="aiw-muted" onClick={() => goTab('assets')}>先去上传照片/视频</button>
      </div>

      {error && <div className="aiw-error">{error}</div>}

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
