import React, { useEffect, useMemo, useRef, useState } from 'react'
import { apiGet, apiPost } from './api'
import './r2-direct-upload-queue-v10-40-8-11.css'

type QueueStatus =
  | 'waiting'
  | 'preparing'
  | 'uploading'
  | 'paused'
  | 'completed'
  | 'failed'
  | 'cancelled'

type QueueItem = {
  localId: string
  serverId: string
  file: File
  relativePath: string
  status: QueueStatus
  progress: number
  uploadedBytes: number
  speed: number
  etaSeconds: number
  error: string
  objectKey: string
  uploadType: string
  attempt: number
}

type ServerFile = {
  id: string
  client_id: string
  name: string
  relative_path?: string
  size: number
  status: string
  object_key: string
  upload_type?: string
  error?: string
}

type ServerBatch = {
  id: string
  status: string
  message?: string
  files: ServerFile[]
  summary?: Record<string, number>
  reframe_job_id?: string
  reframe_job?: any
}

const STORAGE_KEY = 'ai_video_r2_direct_upload_queue_v10_40_8_11'
const FILE_CONCURRENCY = 2
const MAX_RETRIES = 5

function formatBytes(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '0 B'
  if (value < 1024) return `${Math.round(value)} B`
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KB`
  if (value < 1024 ** 3) return `${(value / 1024 ** 2).toFixed(1)} MB`
  return `${(value / 1024 ** 3).toFixed(2)} GB`
}

function formatEta(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return '-'
  if (seconds < 60) return `${Math.ceil(seconds)} 秒`
  if (seconds < 3600) return `${Math.ceil(seconds / 60)} 分钟`
  return `${(seconds / 3600).toFixed(1)} 小时`
}

function simpleHash(value: string): string {
  let hash = 2166136261
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  return (hash >>> 0).toString(16).padStart(8, '0')
}

function makeLocalId(file: File): string {
  const relativePath = (file as any).webkitRelativePath || ''
  return simpleHash(`${relativePath}|${file.name}|${file.size}|${file.lastModified}`)
}

function isSupported(file: File): boolean {
  return /\.(mp4|mov|m4v|mkv|webm|avi|jpg|jpeg|png|webp|bmp)$/i.test(file.name)
}

function statusLabel(status: QueueStatus): string {
  const map: Record<QueueStatus, string> = {
    waiting: '等待上传',
    preparing: '准备直传',
    uploading: '正在上传',
    paused: '已暂停',
    completed: '上传完成',
    failed: '上传失败',
    cancelled: '已取消',
  }
  return map[status]
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

async function xhrPut(
  url: string,
  blob: Blob,
  contentType: string,
  signal: AbortSignal,
  onProgress: (loaded: number) => void,
): Promise<string> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    const abort = () => xhr.abort()
    signal.addEventListener('abort', abort, { once: true })
    xhr.open('PUT', url, true)
    xhr.timeout = 0
    if (contentType) xhr.setRequestHeader('Content-Type', contentType)
    xhr.upload.onprogress = (event) => onProgress(event.loaded)
    xhr.onerror = () => reject(new Error('R2 直传网络错误'))
    xhr.onabort = () => reject(new DOMException('Upload aborted', 'AbortError'))
    xhr.onload = () => {
      signal.removeEventListener('abort', abort)
      if (xhr.status < 200 || xhr.status >= 300) {
        reject(new Error(`R2 返回 ${xhr.status} ${xhr.statusText}`))
        return
      }
      const etag = xhr.getResponseHeader('ETag') || xhr.getResponseHeader('etag') || ''
      resolve(etag)
    }
    xhr.send(blob)
  })
}

async function withRetry<T>(task: (attempt: number) => Promise<T>): Promise<T> {
  let lastError: unknown
  for (let attempt = 1; attempt <= MAX_RETRIES; attempt += 1) {
    try {
      return await task(attempt)
    } catch (error: any) {
      lastError = error
      if (error?.name === 'AbortError') throw error
      if (attempt < MAX_RETRIES) await sleep(Math.min(8000, 700 * 2 ** (attempt - 1)))
    }
  }
  throw lastError instanceof Error ? lastError : new Error(String(lastError || '上传失败'))
}

export default function R2DirectUploadQueue({ onCompleted }: { onCompleted: () => void }) {
  const [items, setItems] = useState<QueueItem[]>([])
  const [batch, setBatch] = useState<ServerBatch | null>(null)
  const [mode, setMode] = useState<'smart_crop' | 'fit_blur'>('smart_crop')
  const [running, setRunning] = useState(false)
  const [paused, setPaused] = useState(false)
  const [message, setMessage] = useState('选择多个视频或整个文件夹，系统会自动排队直传 R2。')
  const [error, setError] = useState('')
  const [healthOk, setHealthOk] = useState(false)
  const abortControllers = useRef(new Map<string, AbortController>())
  const itemsRef = useRef<QueueItem[]>([])
  const pausedRef = useRef(false)
  const runningRef = useRef(false)
  const finalizeStartedRef = useRef(false)

  useEffect(() => {
    itemsRef.current = items
  }, [items])
  useEffect(() => {
    pausedRef.current = paused
  }, [paused])
  useEffect(() => {
    runningRef.current = running
  }, [running])

  useEffect(() => {
    apiGet('/api/assets/direct-upload/health')
      .then((data: any) => {
        setHealthOk(Boolean(data?.ok && data?.r2_enabled))
        if (!data?.r2_enabled) setError('R2 未配置，无法使用大文件直传队列。')
      })
      .catch((nextError: any) => setError(nextError?.message || String(nextError)))
  }, [])

  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY)
      const saved = raw ? JSON.parse(raw) : null
      if (saved?.batchId) {
        apiGet(`/api/assets/direct-upload/batches/${encodeURIComponent(saved.batchId)}`)
          .then((data: any) => {
            if (data?.batch) {
              setBatch(data.batch)
              setMessage('已恢复上一批服务器记录；重新选择原文件夹会自动跳过已上传项。')
            }
          })
          .catch(() => undefined)
      }
    } catch {
      // Ignore corrupt local state.
    }
  }, [])

  useEffect(() => {
    if (!batch?.id) return
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ batchId: batch.id, updatedAt: Date.now(), mode }),
    )
  }, [batch?.id, mode])

  const patchItem = (localId: string, patch: Partial<QueueItem>) => {
    setItems((current) =>
      current.map((item) => (item.localId === localId ? { ...item, ...patch } : item)),
    )
  }

  const addFiles = (fileList: FileList | null) => {
    if (!fileList) return
    const incoming = Array.from(fileList).filter(isSupported)
    if (!incoming.length) {
      setError('没有选中支持的视频或照片。')
      return
    }
    if (incoming.length > 500) {
      setError('单批最多 500 个文件，请分两批选择。')
      return
    }
    const seen = new Set<string>()
    const next: QueueItem[] = []
    for (const file of incoming) {
      const localId = makeLocalId(file)
      if (seen.has(localId)) continue
      seen.add(localId)
      next.push({
        localId,
        serverId: '',
        file,
        relativePath: (file as any).webkitRelativePath || '',
        status: 'waiting',
        progress: 0,
        uploadedBytes: 0,
        speed: 0,
        etaSeconds: 0,
        error: '',
        objectKey: '',
        uploadType: '',
        attempt: 0,
      })
    }
    setItems(next)
    setBatch(null)
    setRunning(false)
    setPaused(false)
    finalizeStartedRef.current = false
    setError('')
    setMessage(`已建立 ${next.length} 条本地队列，点击“开始上传并自动转竖”。`)
  }

  const createServerBatch = async (): Promise<ServerBatch> => {
    const payload = {
      files: itemsRef.current.map((item) => ({
        client_id: item.localId,
        name: item.file.name,
        size: item.file.size,
        type: item.file.type || 'application/octet-stream',
        last_modified: item.file.lastModified,
        relative_path: item.relativePath,
      })),
      output_prefix: 'incoming/landscape',
      folder: 'self',
      usage_role: 'content',
      auto_reframe: true,
      reframe_mode: mode,
    }
    const response: any = await apiPost('/api/assets/direct-upload/batches', payload)
    const created: ServerBatch = response?.batch
    if (!created?.id) throw new Error('后端没有返回上传批次 ID')
    const byClient = new Map(created.files.map((file) => [file.client_id, file]))
    const mappedItems = itemsRef.current.map((item) => {
      const server = byClient.get(item.localId)
      return server
        ? {
            ...item,
            serverId: server.id,
            objectKey: server.object_key,
            status: (server.status === 'completed' ? 'completed' : item.status) as QueueStatus,
            progress: server.status === 'completed' ? 100 : item.progress,
            uploadedBytes: server.status === 'completed' ? item.file.size : item.uploadedBytes,
          }
        : item
    })
    itemsRef.current = mappedItems
    setItems(mappedItems)
    setBatch(created)
    return created
  }

  const uploadOne = async (localId: string, batchId: string) => {
    const current = itemsRef.current.find((item) => item.localId === localId)
    if (!current || current.status === 'completed' || current.status === 'cancelled') return
    const controller = new AbortController()
    abortControllers.current.set(localId, controller)
    const startedAt = Date.now()
    let lastTime = startedAt
    let lastBytes = current.uploadedBytes
    const updateProgress = (loadedBytes: number) => {
      const now = Date.now()
      const elapsed = Math.max(0.2, (now - lastTime) / 1000)
      const speed = Math.max(0, (loadedBytes - lastBytes) / elapsed)
      const remaining = Math.max(0, current.file.size - loadedBytes)
      patchItem(localId, {
        status: 'uploading',
        uploadedBytes: loadedBytes,
        progress: Math.min(99, Math.round((loadedBytes / current.file.size) * 100)),
        speed,
        etaSeconds: speed > 0 ? remaining / speed : 0,
      })
      lastTime = now
      lastBytes = loadedBytes
    }
    try {
      patchItem(localId, { status: 'preparing', error: '' })
      const prepared: any = await apiPost(
        `/api/assets/direct-upload/batches/${encodeURIComponent(batchId)}/files/${encodeURIComponent(current.serverId)}/prepare`,
        {},
      )
      if (prepared?.mode === 'existing') {
        patchItem(localId, {
          status: 'completed',
          progress: 100,
          uploadedBytes: current.file.size,
          speed: 0,
          etaSeconds: 0,
          uploadType: 'existing',
        })
        return
      }
      if (prepared?.mode === 'single') {
        patchItem(localId, { uploadType: 'single', status: 'uploading' })
        await withRetry(async (attempt) => {
          patchItem(localId, { attempt })
          return xhrPut(
            prepared.url,
            current.file,
            current.file.type || 'application/octet-stream',
            controller.signal,
            (loaded) => updateProgress(loaded),
          )
        })
        await apiPost(
          `/api/assets/direct-upload/batches/${encodeURIComponent(batchId)}/files/${encodeURIComponent(current.serverId)}/complete`,
          { parts: [] },
        )
      } else if (prepared?.mode === 'multipart') {
        const partSize = Number(prepared.part_size)
        const partCount = Number(prepared.part_count)
        patchItem(localId, { uploadType: 'multipart', status: 'uploading' })
        const existingResponse: any = await apiGet(
          `/api/assets/direct-upload/batches/${encodeURIComponent(batchId)}/files/${encodeURIComponent(current.serverId)}/parts`,
        )
        const parts = new Map<number, string>()
        for (const part of existingResponse?.parts || []) {
          parts.set(Number(part.part_number), String(part.etag || ''))
        }
        let completedBytes = 0
        for (const partNumber of parts.keys()) {
          const start = (partNumber - 1) * partSize
          completedBytes += Math.min(partSize, current.file.size - start)
        }
        updateProgress(completedBytes)
        for (let partNumber = 1; partNumber <= partCount; partNumber += 1) {
          if (controller.signal.aborted) throw new DOMException('Upload aborted', 'AbortError')
          while (pausedRef.current) await sleep(300)
          if (parts.has(partNumber)) continue
          const signResponse: any = await apiPost(
            `/api/assets/direct-upload/batches/${encodeURIComponent(batchId)}/files/${encodeURIComponent(current.serverId)}/parts/sign`,
            { part_numbers: [partNumber] },
          )
          const signedUrl = String(signResponse?.parts?.[0]?.url || '')
          if (!signedUrl) throw new Error(`第 ${partNumber} 片没有签名地址`)
          const start = (partNumber - 1) * partSize
          const end = Math.min(current.file.size, start + partSize)
          const blob = current.file.slice(start, end)
          const etag = await withRetry(async (attempt) => {
            patchItem(localId, { attempt })
            return xhrPut(
              signedUrl,
              blob,
              current.file.type || 'application/octet-stream',
              controller.signal,
              (partLoaded) => updateProgress(completedBytes + partLoaded),
            )
          })
          if (!etag) throw new Error(`第 ${partNumber} 片未返回 ETag，请检查 R2 CORS`)
          parts.set(partNumber, etag)
          completedBytes += blob.size
          updateProgress(completedBytes)
        }
        await apiPost(
          `/api/assets/direct-upload/batches/${encodeURIComponent(batchId)}/files/${encodeURIComponent(current.serverId)}/complete`,
          {
            parts: Array.from(parts.entries())
              .sort((left, right) => left[0] - right[0])
              .map(([part_number, etag]) => ({ part_number, etag })),
          },
        )
      } else {
        throw new Error('后端返回了未知上传模式')
      }
      patchItem(localId, {
        status: 'completed',
        progress: 100,
        uploadedBytes: current.file.size,
        speed: 0,
        etaSeconds: 0,
        error: '',
      })
    } catch (nextError: any) {
      if (nextError?.name === 'AbortError') {
        patchItem(localId, { status: pausedRef.current ? 'paused' : 'cancelled', speed: 0 })
        return
      }
      const text = nextError?.message || String(nextError)
      patchItem(localId, { status: 'failed', error: text, speed: 0 })
      try {
        await apiPost(
          `/api/assets/direct-upload/batches/${encodeURIComponent(batchId)}/files/${encodeURIComponent(current.serverId)}/fail`,
          { error: text },
        )
      } catch {
        // Preserve original upload error.
      }
    } finally {
      abortControllers.current.delete(localId)
    }
  }

  const runWorkers = async (batchId: string) => {
    const worker = async () => {
      while (runningRef.current) {
        if (pausedRef.current) {
          await sleep(300)
          continue
        }
        const next = itemsRef.current.find((item) =>
          item.status === 'waiting',
        )
        if (!next) return
        // Reserve synchronously before the second worker scans the same queue.
        patchItem(next.localId, { status: 'preparing', error: '' })
        itemsRef.current = itemsRef.current.map((item) =>
          item.localId === next.localId ? { ...item, status: 'preparing', error: '' } : item,
        )
        await uploadOne(next.localId, batchId)
      }
    }
    await Promise.all(Array.from({ length: FILE_CONCURRENCY }, () => worker()))
  }

  const finalize = async (batchId: string) => {
    if (finalizeStartedRef.current) return
    finalizeStartedRef.current = true
    setMessage('全部上传项已处理，正在提交自动转竖队列。')
    try {
      const response: any = await apiPost(
        `/api/assets/direct-upload/batches/${encodeURIComponent(batchId)}/finalize`,
        { auto_reframe: true, reframe_mode: mode },
      )
      setBatch(response?.batch || null)
      const failed = itemsRef.current.filter((item) => item.status === 'failed').length
      if (failed > 0) {
        setMessage(`有 ${failed} 条失败，其余素材已保留；点击“仅重试失败项”。`)
      } else {
        setMessage('原始素材已全部进入 R2，横屏视频正在后台按顺序转成 9:16。')
      }
      onCompleted()
    } catch (nextError: any) {
      finalizeStartedRef.current = false
      setError(nextError?.message || String(nextError))
    }
  }

  const start = async () => {
    if (!itemsRef.current.length || runningRef.current) return
    if (!healthOk) {
      setError('R2 直传服务尚未就绪。')
      return
    }
    setError('')
    setPaused(false)
    pausedRef.current = false
    setRunning(true)
    runningRef.current = true
    finalizeStartedRef.current = false
    try {
      let currentBatch = batch
      if (!currentBatch?.id) currentBatch = await createServerBatch()
      setMessage(`正在以 ${FILE_CONCURRENCY} 条并发上传，其余素材自动排队。`)
      await runWorkers(currentBatch.id)
      runningRef.current = false
      setRunning(false)
      await finalize(currentBatch.id)
    } catch (nextError: any) {
      runningRef.current = false
      setRunning(false)
      setError(nextError?.message || String(nextError))
    }
  }

  const pauseAll = () => {
    setPaused(true)
    pausedRef.current = true
    setMessage('队列已暂停；当前正在上传的一片完成后停止，已完成的 R2 分片不会丢失。')
  }

  const resumeAll = () => {
    setPaused(false)
    pausedRef.current = false
    setItems((current) =>
      current.map((item) =>
        item.status === 'paused' ? { ...item, status: 'waiting', error: '' } : item,
      ),
    )
    setMessage('正在恢复上传队列。')
    if (!runningRef.current) void start()
  }

  const retryFailed = () => {
    setItems((current) =>
      current.map((item) =>
        item.status === 'failed'
          ? { ...item, status: 'waiting', error: '', attempt: 0 }
          : item,
      ),
    )
    finalizeStartedRef.current = false
    window.setTimeout(() => void start(), 0)
  }

  const cancelAll = () => {
    runningRef.current = false
    setRunning(false)
    setPaused(false)
    pausedRef.current = false
    for (const controller of abortControllers.current.values()) controller.abort()
    setItems((current) =>
      current.map((item) =>
        ['completed', 'cancelled'].includes(item.status)
          ? item
          : { ...item, status: 'cancelled', speed: 0 },
      ),
    )
    setMessage('已取消未完成上传；R2 中已成功的文件仍然保留。')
  }

  const clearCompleted = () => {
    setItems((current) => current.filter((item) => item.status !== 'completed'))
  }

  useEffect(() => {
    if (!batch?.id || !['waiting_reframe', 'reframing'].includes(String(batch.status))) return
    let cancelled = false
    const poll = async () => {
      try {
        const response: any = await apiGet(
          `/api/assets/direct-upload/batches/${encodeURIComponent(batch.id)}`,
        )
        if (!cancelled && response?.batch) {
          setBatch(response.batch)
          const reframe = response.batch.reframe_job
          if (reframe) {
            const status = String(reframe.status || '')
            const progress = Math.round(Number(reframe.progress || 0))
            setMessage(`横转竖：${status} ${progress}% · ${reframe.message || ''}`)
            if (['completed', 'done', 'partial', 'failed', 'cancelled'].includes(status)) {
              onCompleted()
            }
          }
        }
      } catch {
        // Polling is best effort; upload results are already safe in R2.
      }
    }
    void poll()
    const timer = window.setInterval(() => void poll(), 3500)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [batch?.id, batch?.status, onCompleted])

  const totals = useMemo(() => {
    const totalBytes = items.reduce((sum, item) => sum + item.file.size, 0)
    const uploadedBytes = items.reduce((sum, item) => sum + item.uploadedBytes, 0)
    return {
      total: items.length,
      completed: items.filter((item) => item.status === 'completed').length,
      failed: items.filter((item) => item.status === 'failed').length,
      waiting: items.filter((item) => ['waiting', 'preparing', 'paused'].includes(item.status)).length,
      totalBytes,
      uploadedBytes,
      progress: totalBytes > 0 ? Math.round((uploadedBytes / totalBytes) * 100) : 0,
    }
  }, [items])

  return (
    <section className="r2q-shell">
      <div className="r2q-head">
        <div>
          <div className="r2q-kicker">R2 DIRECT UPLOAD QUEUE · V10.40.8.11</div>
          <h3>大文件自动排队上传</h3>
          <p>一次选择 100 个视频也会逐条排队；视频数据直接进入 R2，不经过 ECS 磁盘。</p>
        </div>
        <span className={`r2q-health ${healthOk ? 'ok' : 'bad'}`}>
          {healthOk ? 'R2 直传已就绪' : '正在检查 R2'}
        </span>
      </div>

      <div className="r2q-actions">
        <label className="r2q-pick primary">
          选择多个视频/照片
          <input
            type="file"
            multiple
            accept="video/*,image/*,.mov,.mkv,.webm"
            onChange={(event: React.ChangeEvent<HTMLInputElement>) => {
              addFiles(event.currentTarget.files)
              event.currentTarget.value = ''
            }}
          />
        </label>
        <label className="r2q-pick">
          选择整个文件夹
          <input
            type="file"
            multiple
            accept="video/*,image/*,.mov,.mkv,.webm"
            {...({ webkitdirectory: '', directory: '' } as any)}
            onChange={(event: React.ChangeEvent<HTMLInputElement>) => {
              addFiles(event.currentTarget.files)
              event.currentTarget.value = ''
            }}
          />
        </label>
        <select value={mode} onChange={(event: React.ChangeEvent<HTMLSelectElement>) => setMode(event.target.value as any)} disabled={running}>
          <option value="smart_crop">智能放大裁切 · 保留主体景色</option>
          <option value="fit_blur">完整画面保全 · 模糊背景</option>
        </select>
        <button className="r2q-start" type="button" onClick={() => void start()} disabled={!items.length || running || !healthOk}>
          {running ? '队列上传中' : '开始上传并自动转竖'}
        </button>
      </div>

      <div className="r2q-controlRow">
        <button type="button" onClick={pauseAll} disabled={!running || paused}>暂停全部</button>
        <button type="button" onClick={resumeAll} disabled={!paused}>继续上传</button>
        <button type="button" onClick={retryFailed} disabled={!totals.failed || running}>仅重试失败项</button>
        <button type="button" onClick={cancelAll} disabled={!running && !paused}>取消未完成</button>
        <button type="button" onClick={clearCompleted} disabled={!totals.completed || running}>清理已完成</button>
      </div>

      <div className="r2q-summary">
        <div><b>{totals.total}</b><span>队列总数</span></div>
        <div><b>{totals.completed}</b><span>上传完成</span></div>
        <div><b>{totals.waiting}</b><span>等待/暂停</span></div>
        <div><b>{totals.failed}</b><span>失败</span></div>
        <div><b>{totals.progress}%</b><span>{formatBytes(totals.uploadedBytes)} / {formatBytes(totals.totalBytes)}</span></div>
      </div>
      <div className="r2q-overall"><i style={{ width: `${totals.progress}%` }} /></div>
      <div className="r2q-message">{message}</div>
      {error && <div className="r2q-error">{error}</div>}

      {items.length > 0 && (
        <div className="r2q-list">
          {items.map((item) => (
            <article className={`r2q-item ${item.status}`} key={item.localId}>
              <div className="r2q-file">
                <strong title={item.relativePath || item.file.name}>{item.relativePath || item.file.name}</strong>
                <span>{formatBytes(item.file.size)} · {item.uploadType || (item.file.type.startsWith('video/') ? '视频' : '照片')}</span>
              </div>
              <div className="r2q-itemProgress"><i style={{ width: `${item.progress}%` }} /></div>
              <div className="r2q-metrics">
                <span>{item.progress}%</span>
                <span>{statusLabel(item.status)}</span>
                <span>{item.speed > 0 ? `${formatBytes(item.speed)}/s` : '-'}</span>
                <span>剩余 {formatEta(item.etaSeconds)}</span>
              </div>
              {item.error && <div className="r2q-itemError">{item.error}</div>}
            </article>
          ))}
        </div>
      )}

      {batch?.reframe_job && (
        <div className="r2q-reframe">
          <strong>自动转竖任务</strong>
          <span>{String(batch.reframe_job.status || '')}</span>
          <span>{Math.round(Number(batch.reframe_job.progress || 0))}%</span>
          <span>{batch.reframe_job.message || ''}</span>
        </div>
      )}
    </section>
  )
}
