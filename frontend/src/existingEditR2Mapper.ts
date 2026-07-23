export type ExistingR2Shot = {
  id: string
  index: number
  title: string
  scene: string
  narration: string
  duration: number
  source: 'r2'
  camera: string
  transition: string
  prompt: string
  avoid: string[]
  assetIds: string[]
  assetId: string
  assetUrl: string
  assetName: string
  startTime: number
  endTime: number
  preserveAudio: boolean
  speed: number
  matchScore: number
  analysisDescription: string
  autoStart: boolean
  beatReason?: string
  cadenceMode?: string
  historyUseCount?: number
  recent3UseCount?: number
  recent10UseCount?: number
  selectionReason?: string
  speedReason?: string
  segmentSelectionReason?: string
  semanticScore?: number
}

function textValue(...values: unknown[]): string {
  for (const value of values) {
    const text = String(value ?? '').trim()
    if (text) return text
  }
  return ''
}

function numberValue(fallback: number, ...values: unknown[]): number {
  for (const value of values) {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return fallback
}

export function mapExistingR2ClipsToShots(
  clips: unknown,
  segmentTexts: string[] = [],
): ExistingR2Shot[] {
  if (!Array.isArray(clips) || clips.length === 0) {
    throw new Error('后端没有返回任何 R2 视频切片。')
  }
  const normalizedSegments = Array.isArray(segmentTexts)
    ? segmentTexts.map((value) => String(value || ''))
    : []

  const mapped = clips.map((rawClip, index) => {
    const clip = rawClip && typeof rawClip === 'object'
      ? (rawClip as Record<string, any>)
      : {}
    const nestedAsset = clip.asset && typeof clip.asset === 'object'
      ? (clip.asset as Record<string, any>)
      : {}
    const source = textValue(clip.source).toLowerCase()
    const assetUrl = textValue(
      clip.asset_url,
      clip.assetUrl,
      clip.url,
      clip.r2_url,
      nestedAsset.url,
    )
    if (source !== 'r2') {
      throw new Error(`第 ${index + 1} 个片段来源不是 R2：${source || '空'}`)
    }
    if (!assetUrl) {
      throw new Error(`第 ${index + 1} 个 R2 片段缺少真实视频 URL。`)
    }

    const assetId = textValue(
      clip.asset_id,
      clip.assetId,
      clip.id,
      nestedAsset.id,
      `r2_asset_${index + 1}`,
    )
    const startTime = Math.max(
      0,
      numberValue(0, clip.start_time, clip.startTime, clip.clip_start, clip.source_start),
    )
    const explicitEnd = numberValue(
      Number.NaN,
      clip.end_time,
      clip.endTime,
      clip.clip_end,
      clip.source_end,
    )
    const explicitDuration = numberValue(
      Number.NaN,
      clip.duration,
      clip.duration_seconds,
      clip.timeline_duration,
    )
    const duration = Math.max(
      0.1,
      Number.isFinite(explicitDuration)
        ? explicitDuration
        : Number.isFinite(explicitEnd)
          ? explicitEnd - startTime
          : 4,
    )
    const endTime = Math.max(
      startTime + 0.1,
      Number.isFinite(explicitEnd) ? explicitEnd : startTime + duration,
    )
    const narration = textValue(
      clip.narration,
      clip.text,
      clip.voice_text,
      clip.script_text,
      normalizedSegments[index % Math.max(normalizedSegments.length, 1)],
    )
    const scene = textValue(
      clip.scene,
      clip.title,
      clip.shot_title,
      clip.match_reason,
      clip.analysis_description,
      `R2 自动匹配片段 ${index + 1}`,
    )
    const selectionReason = textValue(
      clip.selection_reason,
      clip.selectionReason,
      clip.match_reason,
    )
    const speedReason = textValue(clip.speed_reason, clip.speedReason)
    const segmentSelectionReason = textValue(
      clip.segment_selection_reason,
      clip.segmentSelectionReason,
    )
    const beatReason = textValue(clip.beat_reason, clip.beatReason)
    const analysisDescription = [
      textValue(clip.analysis_description, clip.match_reason, clip.reason),
      selectionReason,
      speedReason,
      segmentSelectionReason,
    ].filter(Boolean).join('；') || '后端已按口播语义从 R2 素材库自动匹配。'

    return {
      id: textValue(
        clip.clip_id,
        clip.shot_id,
        `r2_shot_${index + 1}_${assetId}`,
      ),
      index: index + 1,
      title: scene,
      scene,
      narration,
      duration: Math.round(duration * 1000) / 1000,
      source: 'r2' as const,
      camera: textValue(clip.camera, clip.motion, clip.camera_motion, '原片切片'),
      transition: textValue(
        clip.transition,
        index === 0 ? '开场建立' : '自然衔接',
      ),
      prompt: '',
      avoid: [],
      assetIds: [assetId],
      assetId,
      assetUrl,
      assetName: textValue(
        clip.asset_name,
        clip.name,
        clip.filename,
        nestedAsset.name,
        assetId,
      ),
      startTime,
      endTime,
      preserveAudio: Boolean(
        clip.preserve_audio ?? clip.keep_audio ?? clip.retain_audio ?? true,
      ),
      speed: Math.max(0.1, numberValue(1, clip.speed, clip.playback_speed)),
      matchScore: numberValue(
        0,
        clip.semantic_score,
        clip.match_score,
        clip.score,
      ),
      analysisDescription,
      autoStart: Boolean(clip.auto_start ?? clip.autoStart ?? true),
      beatReason,
      cadenceMode: textValue(clip.cadence_mode, clip.cadenceMode),
      historyUseCount: numberValue(0, clip.history_use_count, clip.historyUseCount),
      recent3UseCount: numberValue(0, clip.recent_3_use_count, clip.recent3UseCount),
      recent10UseCount: numberValue(0, clip.recent_10_use_count, clip.recent10UseCount),
      selectionReason,
      speedReason,
      segmentSelectionReason,
      semanticScore: numberValue(0, clip.semantic_score, clip.semanticScore),
    }
  })

  if (mapped.some((shot) => shot.source !== 'r2' || !shot.assetUrl || !shot.assetId)) {
    throw new Error('R2 映射校验失败：页面镜头缺少素材 ID 或视频 URL。')
  }
  return mapped
}
