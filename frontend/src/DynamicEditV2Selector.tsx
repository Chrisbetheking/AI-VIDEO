import React, { useEffect, useMemo, useState } from 'react'
import './dynamic-edit-v2-v10-40-8-13.css'

export type DynamicEditEngine = 'classic_a10_r4' | 'dynamic_v2'
export type DynamicEditIntensity = 'restrained' | 'balanced' | 'strong'
export type DynamicSubtitleStyle =
  | 'dynamic_white_yellow'
  | 'dynamic_black_box'
  | 'dynamic_gold_property'
  | 'dynamic_minimal_pro'
  | 'dynamic_red_hook'
  | 'dynamic_dual_line'

type StoredConfig = {
  engine: DynamicEditEngine
  intensity: DynamicEditIntensity
  subtitleStyle: DynamicSubtitleStyle
}

const STORAGE_KEY = 'ai_video_dynamic_edit_v2_config_v10_40_8_14'

const DEFAULT_CONFIG: StoredConfig = {
  engine: 'classic_a10_r4',
  intensity: 'balanced',
  subtitleStyle: 'dynamic_white_yellow',
}

const SUBTITLE_PRESETS: Array<{
  id: DynamicSubtitleStyle
  label: string
  description: string
  previewClass: string
}> = [
  { id: 'dynamic_white_yellow', label: '白黄短句跳词', description: '3-8 字短句，白字黑描边，重点词亮黄。', previewClass: 'white-yellow' },
  { id: 'dynamic_black_box', label: '橙白视觉冲击', description: '取消黑底条，改为橙白短词和中心重击。', previewClass: 'orange-impact' },
  { id: 'dynamic_gold_property', label: '金白地产短句', description: '金色关键词配白字，适合区域、预算和资产内容。', previewClass: 'gold-property' },
  { id: 'dynamic_minimal_pro', label: '极简白字口播', description: '无底色短白字，轻描边，画面更干净。', previewClass: 'minimal-pro' },
  { id: 'dynamic_red_hook', label: '红黄疑问重击', description: '疑问、风险和数字使用红黄短词放大。', previewClass: 'red-hook' },
  { id: 'dynamic_dual_line', label: '清单节奏短句', description: '清单词逐条出现，不再显示长双行字幕。', previewClass: 'list-rhythm' },
]

const PREVIEW_BEATS = [
  { caption: '先看区域', focus: '区域', accent: '用途' },
  { caption: '别只看价格', focus: '价格', accent: '半径' },
  { caption: '真正需要的', focus: '需要', accent: '生活' },
  { caption: '生活半径', focus: '半径', accent: '配套' },
]

function loadConfig(): StoredConfig {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return DEFAULT_CONFIG
    const parsed = JSON.parse(raw)
    return {
      engine: parsed?.engine === 'dynamic_v2' ? 'dynamic_v2' : 'classic_a10_r4',
      intensity: ['restrained', 'balanced', 'strong'].includes(parsed?.intensity) ? parsed.intensity : 'balanced',
      subtitleStyle: SUBTITLE_PRESETS.some((item) => item.id === parsed?.subtitleStyle)
        ? parsed.subtitleStyle
        : 'dynamic_white_yellow',
    }
  } catch {
    return DEFAULT_CONFIG
  }
}

function saveConfig(config: StoredConfig) {
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(config))
  window.dispatchEvent(new CustomEvent('ai-video-dynamic-edit-v2-change', { detail: config }))
}

export function getDynamicEditV2Config(): StoredConfig {
  if (typeof window === 'undefined') return DEFAULT_CONFIG
  return loadConfig()
}

export function getDynamicEditV2StartEndpoint(): string {
  const config = getDynamicEditV2Config()
  if (config.engine !== 'dynamic_v2') return '/api/video/existing-edit/start'
  const query = new URLSearchParams({
    intensity: config.intensity,
    subtitle_style: config.subtitleStyle,
  })
  return `/api/video/existing-edit-v2/start?${query.toString()}`
}

export default function DynamicEditV2Selector() {
  const [config, setConfig] = useState<StoredConfig>(() => loadConfig())
  const [previewPulse, setPreviewPulse] = useState(0)

  useEffect(() => {
    saveConfig(config)
  }, [config])

  useEffect(() => {
    const timer = window.setInterval(() => setPreviewPulse((value) => value + 1), 1450)
    return () => window.clearInterval(timer)
  }, [])

  const selectedSubtitle = useMemo(
    () => SUBTITLE_PRESETS.find((item) => item.id === config.subtitleStyle) || SUBTITLE_PRESETS[0],
    [config.subtitleStyle],
  )
  const beat = PREVIEW_BEATS[previewPulse % PREVIEW_BEATS.length]

  return (
    <section className="dynamic-edit-v2-shell" data-dynamic-edit-v2="true">
      <div className="dynamic-edit-v2-header">
        <div>
          <span className="dynamic-edit-v2-eyebrow">V10.40.8.14 · REFERENCE KINETIC CAPTIONS</span>
          <h4>剪辑引擎</h4>
          <p>原 A10-R4 不动；新版按参考视频重做短句字幕、更多镜头和跳词节奏。</p>
        </div>
        <span className="dynamic-edit-v2-beta">双版本并存</span>
      </div>

      <div className="dynamic-edit-v2-engine-grid">
        <button
          type="button"
          className={`dynamic-edit-v2-engine ${config.engine === 'classic_a10_r4' ? 'selected' : ''}`}
          onClick={() => setConfig((current) => ({ ...current, engine: 'classic_a10_r4' }))}
        >
          <span className="dynamic-edit-v2-engine-tag">稳定正式版</span>
          <strong>A10-R4 稳定剪辑</strong>
          <small>语义配画、全片去重、结尾新画面、-16 LUFS。</small>
          <span className="dynamic-edit-v2-check">{config.engine === 'classic_a10_r4' ? '✓ 当前选择' : '选择稳定版'}</span>
        </button>

        <button
          type="button"
          className={`dynamic-edit-v2-engine dynamic ${config.engine === 'dynamic_v2' ? 'selected' : ''}`}
          onClick={() => setConfig((current) => ({ ...current, engine: 'dynamic_v2' }))}
        >
          <span className="dynamic-edit-v2-engine-tag">参考视频重做版</span>
          <strong>动态短句精剪</strong>
          <small>3-8 字字幕、更多镜头、无文本框、重点词弹入和轻推近。</small>
          <span className="dynamic-edit-v2-check">{config.engine === 'dynamic_v2' ? '✓ 当前选择' : '选择新版'}</span>
        </button>
      </div>

      {config.engine === 'dynamic_v2' && (
        <div className="dynamic-edit-v2-settings">
          <div className="dynamic-edit-v2-preview" key={previewPulse}>
            <div className="dynamic-edit-v2-preview-scene" />
            <span className="dynamic-edit-v2-preview-word word-main">{beat.focus}</span>
            <span className="dynamic-edit-v2-preview-word word-side">{beat.accent}</span>
            <div className={`dynamic-edit-v2-preview-subtitle ${selectedSubtitle.previewClass}`}>
              {beat.caption}
            </div>
            <div className="dynamic-edit-v2-preview-beats" aria-hidden="true">
              <i /><i /><i /><i />
            </div>
          </div>

          <div className="dynamic-edit-v2-controls">
            <label>
              <span>动态效果强度</span>
              <select
                value={config.intensity}
                onChange={(event) => setConfig((current) => ({ ...current, intensity: event.target.value as DynamicEditIntensity }))}
              >
                <option value="restrained">克制 · 短句字幕 + 约 7 个主要效果 / 30 秒</option>
                <option value="balanced">参考节奏 · 更多镜头 + 约 11 个主要效果 / 30 秒</option>
                <option value="strong">强节奏 · 密集短句 + 约 15 个主要效果 / 30 秒</option>
              </select>
            </label>
            <div className="dynamic-edit-v2-rule-note">
              <b>新版硬规则</b>
              <span>不显示大块文本框；字幕单屏 3-8 字；动态版使用更密的素材切片，稳定版不受影响。</span>
            </div>
          </div>

          <div className="dynamic-edit-v2-subtitle-heading">
            <div>
              <strong>短句动态字幕</strong>
              <span>参考视频的核心是短句、跳词、颜色重音和位置变化，不是给整句套黑框。</span>
            </div>
            <span>生成时自动烧录</span>
          </div>

          <div className="dynamic-edit-v2-subtitle-grid">
            {SUBTITLE_PRESETS.map((preset) => (
              <button
                type="button"
                key={preset.id}
                className={`dynamic-edit-v2-subtitle-card ${config.subtitleStyle === preset.id ? 'selected' : ''}`}
                onClick={() => setConfig((current) => ({ ...current, subtitleStyle: preset.id }))}
              >
                <strong>{preset.label}</strong>
                <span className={`dynamic-edit-v2-subtitle-sample ${preset.previewClass}`}>
                  先看<em>区域</em>
                </span>
                <small>{preset.description}</small>
              </button>
            ))}
          </div>

          <div className="dynamic-edit-v2-ab-note">
            <b>输出策略</b>
            <span>选择新版后，仍先保留 A10-R4 稳定底片，再生成动态短句版；两条地址同时保留，方便对比和回退。</span>
          </div>
        </div>
      )}
    </section>
  )
}
