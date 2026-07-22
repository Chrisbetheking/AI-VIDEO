import React, { type ChangeEvent, useEffect, useMemo, useState } from 'react'
import './dynamic-edit-v2-v10-40-8-13.css'

export type DynamicEditEngine = 'classic_a10_r4' | 'dynamic_v2'
export type DynamicEditIntensity = 'restrained' | 'balanced' | 'strong'
export type DynamicVisualPace = 'calm' | 'balanced' | 'punchy'
export type DynamicSfxLevel = 'off' | 'light' | 'balanced' | 'strong'
export type DynamicStickerLevel = 'off' | 'light' | 'balanced' | 'rich'
export type DynamicCaptionMotion =
  | 'smart_mix' | 'pop_bounce' | 'slide_mix' | 'lift_fade'
  | 'elastic' | 'rotate_snap' | 'typewriter' | 'impact_cut' | 'clean_fade'
export type DynamicCaptionPosition = 'auto' | 'lower' | 'middle'
export type DynamicSfxPack = 'smart_mix' | 'soft_ui' | 'impact_mix'
export type DynamicStickerLayout = 'auto_safe' | 'top' | 'side'
export type DynamicStickerStyle = 'smart_mix' | 'icons' | 'doodles'
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
  visualPace: DynamicVisualPace
  subtitleStyle: DynamicSubtitleStyle
  captionSize: number
  captionMotion: DynamicCaptionMotion
  captionPosition: DynamicCaptionPosition
  sfxLevel: DynamicSfxLevel
  sfxPack: DynamicSfxPack
  stickerLevel: DynamicStickerLevel
  stickerLayout: DynamicStickerLayout
  stickerStyle: DynamicStickerStyle
}

const STORAGE_KEY = 'ai_video_dynamic_edit_v2_config_v10_40_8_16'
const DEFAULT_CONFIG: StoredConfig = {
  engine: 'classic_a10_r4',
  intensity: 'balanced',
  visualPace: 'balanced',
  subtitleStyle: 'dynamic_white_yellow',
  captionSize: 110,
  captionMotion: 'smart_mix',
  captionPosition: 'auto',
  sfxLevel: 'balanced',
  sfxPack: 'smart_mix',
  stickerLevel: 'balanced',
  stickerLayout: 'auto_safe',
  stickerStyle: 'smart_mix',
}

const SUBTITLE_PRESETS: Array<{ id: DynamicSubtitleStyle; label: string; sample: string; previewClass: string }> = [
  { id: 'dynamic_white_yellow', label: '白黄跳词', sample: '先看区域', previewClass: 'white-yellow' },
  { id: 'dynamic_black_box', label: '橙白冲击', sample: '别只看价格', previewClass: 'orange-impact' },
  { id: 'dynamic_gold_property', label: '金白地产', sample: '真实预算', previewClass: 'gold-property' },
  { id: 'dynamic_minimal_pro', label: '极简专业', sample: '生活半径', previewClass: 'minimal-pro' },
  { id: 'dynamic_red_hook', label: '红黄钩子', sample: '千万别踩坑', previewClass: 'red-hook' },
  { id: 'dynamic_dual_line', label: '清单节奏', sample: '第一看交通', previewClass: 'list-rhythm' },
]

const MOTIONS: Array<{ id: DynamicCaptionMotion; label: string }> = [
  { id: 'smart_mix', label: '智能混合（推荐）' },
  { id: 'pop_bounce', label: '弹跳放大' },
  { id: 'slide_mix', label: '左右滑入' },
  { id: 'lift_fade', label: '上浮淡入' },
  { id: 'elastic', label: '弹性回弹' },
  { id: 'rotate_snap', label: '轻旋归位' },
  { id: 'typewriter', label: '逐字扫入' },
  { id: 'impact_cut', label: '关键词重击' },
  { id: 'clean_fade', label: '极简淡入' },
]

const FONT_SIZES = [
  { value: 92, label: '紧凑' },
  { value: 110, label: '标准' },
  { value: 128, label: '大字' },
  { value: 146, label: '超大' },
]

function valid<T extends string>(value: unknown, options: readonly T[], fallback: T): T {
  return options.includes(value as T) ? value as T : fallback
}

function loadConfig(): StoredConfig {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return DEFAULT_CONFIG
    const p = JSON.parse(raw)
    return {
      engine: p?.engine === 'dynamic_v2' ? 'dynamic_v2' : 'classic_a10_r4',
      intensity: valid(p?.intensity, ['restrained', 'balanced', 'strong'] as const, 'balanced'),
      visualPace: valid(p?.visualPace, ['calm', 'balanced', 'punchy'] as const, 'balanced'),
      subtitleStyle: valid(p?.subtitleStyle, SUBTITLE_PRESETS.map((x) => x.id), 'dynamic_white_yellow'),
      captionSize: Math.max(84, Math.min(160, Number(p?.captionSize) || 110)),
      captionMotion: valid(p?.captionMotion, MOTIONS.map((x) => x.id), 'smart_mix'),
      captionPosition: valid(p?.captionPosition, ['auto', 'lower', 'middle'] as const, 'auto'),
      sfxLevel: valid(p?.sfxLevel, ['off', 'light', 'balanced', 'strong'] as const, 'balanced'),
      sfxPack: valid(p?.sfxPack, ['smart_mix', 'soft_ui', 'impact_mix'] as const, 'smart_mix'),
      stickerLevel: valid(p?.stickerLevel, ['off', 'light', 'balanced', 'rich'] as const, 'balanced'),
      stickerLayout: valid(p?.stickerLayout, ['auto_safe', 'top', 'side'] as const, 'auto_safe'),
      stickerStyle: valid(p?.stickerStyle, ['smart_mix', 'icons', 'doodles'] as const, 'smart_mix'),
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
  const c = getDynamicEditV2Config()
  if (c.engine !== 'dynamic_v2') return '/api/video/existing-edit/start'
  const query = new URLSearchParams({
    intensity: c.intensity,
    visual_pace: c.visualPace,
    subtitle_style: c.subtitleStyle,
    caption_size: String(c.captionSize),
    caption_motion: c.captionMotion,
    caption_position: c.captionPosition,
    sfx_level: c.sfxLevel,
    sfx_pack: c.sfxPack,
    sticker_level: c.stickerLevel,
    sticker_layout: c.stickerLayout,
    sticker_style: c.stickerStyle,
  })
  return `/api/video/existing-edit-v2/start?${query.toString()}`
}

export default function DynamicEditV2Selector() {
  const [config, setConfig] = useState<StoredConfig>(() => loadConfig())
  const [tab, setTab] = useState<'basic' | 'captions' | 'sound' | 'advanced'>('basic')
  const [preview, setPreview] = useState(0)

  useEffect(() => saveConfig(config), [config])
  useEffect(() => {
    const timer = window.setInterval(() => setPreview((x) => x + 1), 1900)
    return () => window.clearInterval(timer)
  }, [])

  const selectedStyle = useMemo(
    () => SUBTITLE_PRESETS.find((item) => item.id === config.subtitleStyle) || SUBTITLE_PRESETS[0],
    [config.subtitleStyle],
  )
  const previewWords = ['先看区域', '别只看价格', '真实租客', '生活半径']
  const previewWord = previewWords[preview % previewWords.length]

  return (
    <section className="dynamic-edit-v2-shell v16" data-dynamic-edit-v2="true" data-placement="step3-top">
      <div className="dynamic-edit-v2-header">
        <div>
          <span className="dynamic-edit-v2-eyebrow">V10.40.8.16 · BALANCED EDITING STUDIO</span>
          <h4>剪辑引擎与动效</h4>
          <p>放在“编辑镜头和素材”顶部：先定镜头节奏，再定字幕、音效和贴纸。</p>
        </div>
        <span className="dynamic-edit-v2-beta">A10-R4 保留</span>
      </div>

      <div className="dynamic-edit-v2-engine-grid compact">
        <button type="button" className={`dynamic-edit-v2-engine ${config.engine === 'classic_a10_r4' ? 'selected' : ''}`}
          onClick={() => setConfig((c) => ({ ...c, engine: 'classic_a10_r4' }))}>
          <span className="dynamic-edit-v2-engine-tag">正式稳定版</span>
          <strong>A10-R4 稳定剪辑</strong>
          <small>原逻辑完全保留。</small>
        </button>
        <button type="button" className={`dynamic-edit-v2-engine dynamic ${config.engine === 'dynamic_v2' ? 'selected' : ''}`}
          onClick={() => setConfig((c) => ({ ...c, engine: 'dynamic_v2' }))}>
          <span className="dynamic-edit-v2-engine-tag">可调增强版</span>
          <strong>均衡动态精剪</strong>
          <small>镜头降速，字幕动效与切镜解耦。</small>
        </button>
      </div>

      {config.engine === 'dynamic_v2' && (
        <div className="dynamic-edit-v2-settings">
          <div className="dynamic-edit-v2-toolbar">
            {[
              ['basic', '基础节奏'],
              ['captions', '字幕字体'],
              ['sound', '音效贴纸'],
              ['advanced', '高级规则'],
            ].map(([id, label]) => (
              <button key={id} type="button" className={tab === id ? 'selected' : ''}
                onClick={() => setTab(id as typeof tab)}>{label}</button>
            ))}
          </div>

          <div className="dynamic-edit-v2-studio-grid">
            <div className={`dynamic-edit-v2-mini-preview motion-${config.captionMotion}`} key={`${preview}-${config.captionMotion}`}>
              <div className="preview-building" />
              <span className={`preview-caption ${selectedStyle.previewClass}`} style={{ fontSize: `${Math.round(config.captionSize * 0.30)}px` }}>
                {previewWord}
              </span>
              {config.stickerLevel !== 'off' && <span className="preview-doodle">↗</span>}
              {config.sfxLevel !== 'off' && <span className="preview-wave"><i/><i/><i/><i/></span>}
              <small>{config.visualPace === 'calm' ? '约 3.2 秒/镜头' : config.visualPace === 'punchy' ? '约 2.1 秒/镜头' : '约 2.55 秒/镜头'}</small>
            </div>

            <div className="dynamic-edit-v2-panel">
              {tab === 'basic' && (
                <div className="control-grid">
                  <label><span>镜头节奏</span><select value={config.visualPace}
                    onChange={(e: ChangeEvent<HTMLSelectElement>) => setConfig((c) => ({ ...c, visualPace: e.target.value as DynamicVisualPace }))}>
                    <option value="calm">舒缓讲解 · 约 3.2 秒/镜头</option>
                    <option value="balanced">均衡精剪 · 约 2.55 秒/镜头（推荐）</option>
                    <option value="punchy">紧凑口播 · 约 2.1 秒/镜头</option>
                  </select></label>
                  <label><span>主要动效密度</span><select value={config.intensity}
                    onChange={(e: ChangeEvent<HTMLSelectElement>) => setConfig((c) => ({ ...c, intensity: e.target.value as DynamicEditIntensity }))}>
                    <option value="restrained">克制 · 约 5 次/30 秒</option>
                    <option value="balanced">均衡 · 约 7 次/30 秒</option>
                    <option value="strong">加强 · 约 10 次/30 秒</option>
                  </select></label>
                  <div className="rule-card"><b>镜头与字幕分开控制</b><span>字幕可以动，但不会每次字幕动画都切镜头。</span></div>
                </div>
              )}

              {tab === 'captions' && (
                <>
                  <div className="font-size-row">
                    <div><b>字体大小</b><span>{config.captionSize}px</span></div>
                    <input type="range" min="84" max="160" step="2" value={config.captionSize}
                      onChange={(e) => setConfig((c) => ({ ...c, captionSize: Number(e.target.value) }))}/>
                    <div className="font-buttons">
                      {FONT_SIZES.map((item) => <button key={item.value} type="button"
                        className={config.captionSize === item.value ? 'selected' : ''}
                        onClick={() => setConfig((c) => ({ ...c, captionSize: item.value }))}>{item.label}</button>)}
                    </div>
                  </div>
                  <div className="control-grid">
                    <label><span>字幕动效模板</span><select value={config.captionMotion}
                      onChange={(e: ChangeEvent<HTMLSelectElement>) => setConfig((c) => ({ ...c, captionMotion: e.target.value as DynamicCaptionMotion }))}>
                      {MOTIONS.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
                    </select></label>
                    <label><span>字幕位置</span><select value={config.captionPosition}
                      onChange={(e: ChangeEvent<HTMLSelectElement>) => setConfig((c) => ({ ...c, captionPosition: e.target.value as DynamicCaptionPosition }))}>
                      <option value="auto">智能避让（推荐）</option><option value="lower">底部安全区</option><option value="middle">中部强调区</option>
                    </select></label>
                  </div>
                  <div className="dynamic-edit-v2-subtitle-grid compact">
                    {SUBTITLE_PRESETS.map((preset) => (
                      <button type="button" key={preset.id}
                        className={`dynamic-edit-v2-subtitle-card ${config.subtitleStyle === preset.id ? 'selected' : ''}`}
                        onClick={() => setConfig((c) => ({ ...c, subtitleStyle: preset.id }))}>
                        <strong>{preset.label}</strong><span className={`dynamic-edit-v2-subtitle-sample ${preset.previewClass}`}>{preset.sample}</span>
                      </button>
                    ))}
                  </div>
                </>
              )}

              {tab === 'sound' && (
                <div className="control-grid">
                  <label><span>音效音量</span><select value={config.sfxLevel}
                    onChange={(e: ChangeEvent<HTMLSelectElement>) => setConfig((c) => ({ ...c, sfxLevel: e.target.value as DynamicSfxLevel }))}>
                    <option value="off">关闭</option><option value="light">轻柔 · 约 3 次/30 秒</option>
                    <option value="balanced">均衡 · 约 5 次/30 秒（推荐）</option><option value="strong">明显 · 约 7 次/30 秒</option>
                  </select></label>
                  <label><span>音效组合</span><select value={config.sfxPack}
                    onChange={(e: ChangeEvent<HTMLSelectElement>) => setConfig((c) => ({ ...c, sfxPack: e.target.value as DynamicSfxPack }))}>
                    <option value="smart_mix">语义智能混合</option><option value="soft_ui">轻柔 UI 音</option><option value="impact_mix">钩子重击混合</option>
                  </select></label>
                  <label><span>贴纸密度</span><select value={config.stickerLevel}
                    onChange={(e: ChangeEvent<HTMLSelectElement>) => setConfig((c) => ({ ...c, stickerLevel: e.target.value as DynamicStickerLevel }))}>
                    <option value="off">关闭</option><option value="light">少量 · 约 2 个/30 秒</option>
                    <option value="balanced">均衡 · 约 3 个/30 秒（推荐）</option><option value="rich">丰富 · 约 5 个/30 秒</option>
                  </select></label>
                  <label><span>贴纸风格</span><select value={config.stickerStyle}
                    onChange={(e: ChangeEvent<HTMLSelectElement>) => setConfig((c) => ({ ...c, stickerStyle: e.target.value as DynamicStickerStyle }))}>
                    <option value="smart_mix">图标 + 手绘混合</option><option value="icons">主题图标</option><option value="doodles">手绘线条</option>
                  </select></label>
                  <label><span>贴纸位置</span><select value={config.stickerLayout}
                    onChange={(e: ChangeEvent<HTMLSelectElement>) => setConfig((c) => ({ ...c, stickerLayout: e.target.value as DynamicStickerLayout }))}>
                    <option value="auto_safe">自动安全区</option><option value="top">只放上方两角</option><option value="side">只放左右侧边</option>
                  </select></label>
                  <div className="rule-card"><b>位置硬规则</b><span>贴纸不进入画面中央，不进入底部字幕区，同一侧不会连续出现。</span></div>
                </div>
              )}

              {tab === 'advanced' && (
                <div className="advanced-rules">
                  <article><b>声音</b><span>26 个不同音效，限制最短间隔与峰值，默认音量约为 V15 的三分之一。</span></article>
                  <article><b>贴纸</b><span>23 个主题图标 + 12 个原创透明手绘贴纸，仅在语义节点出现。</span></article>
                  <article><b>镜头</b><span>默认约 2.55 秒/镜头；41 秒视频约 16 个片段，而不是 21 个以上。</span></article>
                  <article><b>字幕</b><span>9 套动效模板，字体 84–160 可调，不使用黑底文本框。</span></article>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </section>
  )
}
