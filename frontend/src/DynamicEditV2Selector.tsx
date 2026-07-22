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

const STORAGE_KEY = 'ai_video_dynamic_edit_v2_config_v10_40_8_13'

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
  { id: 'dynamic_white_yellow', label: '白字黄词精剪款', description: '参考口播精剪，白色大字 + 黄色重点词。', previewClass: 'white-yellow' },
  { id: 'dynamic_black_box', label: '黑底信息条', description: '半透明黑底，适合避坑、区域拆解和逻辑内容。', previewClass: 'black-box' },
  { id: 'dynamic_gold_property', label: '金色地产讲解', description: '金色重点 + 深色底，适合预算、资产和项目讲解。', previewClass: 'gold-property' },
  { id: 'dynamic_minimal_pro', label: '极简专业白字', description: '柔和描边，适合人物和高级感楼盘。', previewClass: 'minimal-pro' },
  { id: 'dynamic_red_hook', label: '红黄钩子重击', description: '疑问、风险和转折使用红黄重点。', previewClass: 'red-hook' },
  { id: 'dynamic_dual_line', label: '专业解释双行款', description: '较长专业句自然分两行，重点词单独高亮。', previewClass: 'dual-line' },
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
    const timer = window.setInterval(() => setPreviewPulse((value) => value + 1), 2600)
    return () => window.clearInterval(timer)
  }, [])

  const selectedSubtitle = useMemo(
    () => SUBTITLE_PRESETS.find((item) => item.id === config.subtitleStyle) || SUBTITLE_PRESETS[0],
    [config.subtitleStyle],
  )

  return (
    <section className="dynamic-edit-v2-shell" data-dynamic-edit-v2="true">
      <div className="dynamic-edit-v2-header">
        <div>
          <span className="dynamic-edit-v2-eyebrow">V10.40.8.13 · DYNAMIC TALKING-HEAD EDIT V2</span>
          <h4>剪辑引擎</h4>
          <p>原 A10-R4 完整保留；新版单独生成，可随时切回稳定版。</p>
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
          <span className="dynamic-edit-v2-engine-tag">Beta 新版</span>
          <strong>动态精剪 V2</strong>
          <small>钩子重击、轻推近、信息卡、数字强化、动态字幕和轻音效。</small>
          <span className="dynamic-edit-v2-check">{config.engine === 'dynamic_v2' ? '✓ 当前选择' : '选择新版'}</span>
        </button>
      </div>

      {config.engine === 'dynamic_v2' && (
        <div className="dynamic-edit-v2-settings">
          <div className="dynamic-edit-v2-preview" key={previewPulse}>
            <div className="dynamic-edit-v2-preview-person" />
            <div className="dynamic-edit-v2-preview-card">
              <span>区域选择</span>
              <b>先看用途</b>
            </div>
            <div className={`dynamic-edit-v2-preview-subtitle ${selectedSubtitle.previewClass}`}>
              吉隆坡买房 <em>先看区域和用途</em>
            </div>
            <i className="dynamic-edit-v2-preview-focus">重点</i>
          </div>

          <div className="dynamic-edit-v2-controls">
            <label>
              <span>动态效果强度</span>
              <select
                value={config.intensity}
                onChange={(event) => setConfig((current) => ({ ...current, intensity: event.target.value as DynamicEditIntensity }))}
              >
                <option value="restrained">克制 · 约 5 个主要效果 / 30 秒</option>
                <option value="balanced">标准 · 约 8 个主要效果 / 30 秒</option>
                <option value="strong">强节奏 · 约 11 个主要效果 / 30 秒</option>
              </select>
            </label>
            <div className="dynamic-edit-v2-rule-note">
              <b>安全规则</b>
              <span>不会每句都加动画；连续大效果自动间隔；新版失败不会覆盖原版。</span>
            </div>
          </div>

          <div className="dynamic-edit-v2-subtitle-heading">
            <div>
              <strong>动态字幕模板</strong>
              <span>已参考你提供视频里的白字黄词、红黄钩子、黑底信息条和专业双行字幕。</span>
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
                  吉隆坡买房<br /><em>先看区域和用途</em>
                </span>
                <small>{preset.description}</small>
              </button>
            ))}
          </div>

          <div className="dynamic-edit-v2-ab-note">
            <b>输出策略</b>
            <span>选择新版后，后端先生成 A10-R4 稳定底片，再生成动态精剪版；两条视频地址同时保留，方便 A/B 对比和回退。</span>
          </div>
        </div>
      )}
    </section>
  )
}
