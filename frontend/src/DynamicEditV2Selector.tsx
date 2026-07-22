import React, { type ChangeEvent, useEffect, useMemo, useState } from 'react'
import './dynamic-edit-v2-v10-40-8-13.css'

export type DynamicEditEngine = 'classic_a10_r4' | 'dynamic_v2'
export type DynamicEditIntensity = 'restrained' | 'balanced' | 'strong'
export type DynamicVisualPace = 'calm' | 'balanced' | 'punchy'
export type DynamicSfxLevel = 'off' | 'light' | 'balanced' | 'strong'
export type DynamicStickerLevel = 'off' | 'light' | 'balanced' | 'rich'
export type DynamicCaptionMotion = 'smart_mix' | 'pop_bounce' | 'slide_mix' | 'lift_fade' | 'elastic' | 'rotate_snap' | 'typewriter' | 'impact_cut' | 'clean_fade'
export type DynamicCaptionPosition = 'auto' | 'lower' | 'middle'
export type DynamicSfxPack = 'smart_mix' | 'soft_ui' | 'impact_mix'
export type DynamicStickerLayout = 'auto_safe' | 'top' | 'side'
export type DynamicStickerStyle = 'smart_mix' | 'icons' | 'doodles'
export type DynamicSubtitleStyle = 'dynamic_white_yellow' | 'dynamic_black_box' | 'dynamic_gold_property' | 'dynamic_minimal_pro' | 'dynamic_red_hook' | 'dynamic_dual_line'

type StoredConfig = {
  engine: DynamicEditEngine; intensity: DynamicEditIntensity; visualPace: DynamicVisualPace
  subtitleStyle: DynamicSubtitleStyle; captionSize: number; captionMotion: DynamicCaptionMotion
  captionPosition: DynamicCaptionPosition; sfxLevel: DynamicSfxLevel; sfxPack: DynamicSfxPack
  stickerLevel: DynamicStickerLevel; stickerLayout: DynamicStickerLayout; stickerStyle: DynamicStickerStyle
}

const STORAGE_KEY = 'ai_video_dynamic_edit_v2_config_v10_40_8_18'
const DEFAULT_CONFIG: StoredConfig = {
  engine: 'classic_a10_r4', intensity: 'balanced', visualPace: 'balanced',
  subtitleStyle: 'dynamic_white_yellow', captionSize: 118, captionMotion: 'smart_mix',
  captionPosition: 'auto', sfxLevel: 'light', sfxPack: 'smart_mix', stickerLevel: 'light',
  stickerLayout: 'auto_safe', stickerStyle: 'smart_mix',
}
const SUBTITLE_PRESETS: Array<{id: DynamicSubtitleStyle; label: string; sample: string; previewClass: string}> = [
  {id:'dynamic_white_yellow',label:'白黄跳词',sample:'先看区域',previewClass:'white-yellow'},
  {id:'dynamic_black_box',label:'橙白冲击',sample:'别只看价格',previewClass:'orange-impact'},
  {id:'dynamic_gold_property',label:'金白地产',sample:'真实预算',previewClass:'gold-property'},
  {id:'dynamic_minimal_pro',label:'极简专业',sample:'生活半径',previewClass:'minimal-pro'},
  {id:'dynamic_red_hook',label:'红黄钩子',sample:'千万别踩坑',previewClass:'red-hook'},
  {id:'dynamic_dual_line',label:'清单节奏',sample:'第一看交通',previewClass:'list-rhythm'},
]
const MOTIONS: Array<{id: DynamicCaptionMotion; label: string; sample: string}> = [
  {id:'smart_mix',label:'智能混合',sample:'先看区域'}, {id:'pop_bounce',label:'弹跳放大',sample:'真实价格'},
  {id:'slide_mix',label:'左右滑入',sample:'交通半径'}, {id:'lift_fade',label:'上浮淡入',sample:'生活配套'},
  {id:'elastic',label:'弹性回弹',sample:'租客来源'}, {id:'rotate_snap',label:'轻旋归位',sample:'产权校验'},
  {id:'typewriter',label:'逐字扫入',sample:'退出路径'}, {id:'impact_cut',label:'关键词重击',sample:'别踩坑'},
  {id:'clean_fade',label:'极简淡入',sample:'提前想清楚'},
]
const FONT_SIZES = [{value:96,label:'紧凑'},{value:118,label:'标准'},{value:132,label:'大字'},{value:148,label:'超大'}]
function valid<T extends string>(value: unknown, options: readonly T[], fallback: T): T { return options.includes(value as T) ? value as T : fallback }
function loadConfig(): StoredConfig {
  try {
    const raw=window.localStorage.getItem(STORAGE_KEY); if(!raw) return DEFAULT_CONFIG; const p=JSON.parse(raw)
    return {engine:p?.engine==='dynamic_v2'?'dynamic_v2':'classic_a10_r4',intensity:valid(p?.intensity,['restrained','balanced','strong'] as const,'balanced'),visualPace:valid(p?.visualPace,['calm','balanced','punchy'] as const,'balanced'),subtitleStyle:valid(p?.subtitleStyle,SUBTITLE_PRESETS.map(x=>x.id),'dynamic_white_yellow'),captionSize:Math.max(84,Math.min(160,Number(p?.captionSize)||118)),captionMotion:valid(p?.captionMotion,MOTIONS.map(x=>x.id),'smart_mix'),captionPosition:valid(p?.captionPosition,['auto','lower','middle'] as const,'auto'),sfxLevel:valid(p?.sfxLevel,['off','light','balanced','strong'] as const,'light'),sfxPack:valid(p?.sfxPack,['smart_mix','soft_ui','impact_mix'] as const,'smart_mix'),stickerLevel:valid(p?.stickerLevel,['off','light','balanced','rich'] as const,'light'),stickerLayout:valid(p?.stickerLayout,['auto_safe','top','side'] as const,'auto_safe'),stickerStyle:valid(p?.stickerStyle,['smart_mix','icons','doodles'] as const,'smart_mix')}
  } catch { return DEFAULT_CONFIG }
}
function saveConfig(config: StoredConfig){window.localStorage.setItem(STORAGE_KEY,JSON.stringify(config));window.dispatchEvent(new CustomEvent('ai-video-dynamic-edit-v2-change',{detail:config}))}
export function getDynamicEditV2Config(): StoredConfig { return typeof window==='undefined'?DEFAULT_CONFIG:loadConfig() }
export function getDynamicEditV2StartEndpoint(): string {
  const c=getDynamicEditV2Config(); if(c.engine!=='dynamic_v2') return '/api/video/existing-edit/start'
  const query=new URLSearchParams({intensity:c.intensity,visual_pace:c.visualPace,subtitle_style:c.subtitleStyle,caption_size:String(c.captionSize),caption_motion:c.captionMotion,caption_position:c.captionPosition,sfx_level:c.sfxLevel,sfx_pack:c.sfxPack,sticker_level:c.stickerLevel,sticker_layout:c.stickerLayout,sticker_style:c.stickerStyle})
  return `/api/video/existing-edit-v2/start?${query.toString()}`
}

function MotionPreview({motion, sample, styleClass, size}:{motion:DynamicCaptionMotion;sample:string;styleClass:string;size:number}){
  const chars=[...sample]
  return <div className={`v17-motion-stage v17-motion-${motion}`} data-motion={motion}>
    <div className="v17-scene"><i/><i/><i/></div>
    {motion==='smart_mix' && <><b className={`v17-word mix-a ${styleClass}`}>先看</b><b className={`v17-word mix-b ${styleClass}`}>区域</b><em>智能轮换</em></>}
    {motion==='slide_mix' && <><b className={`v17-word slide-left ${styleClass}`}>交通</b><b className={`v17-word slide-right ${styleClass}`}>生活半径</b></>}
    {motion==='typewriter' && <b className={`v17-word typewriter ${styleClass}`}>{chars.map((c,i)=><span key={i} style={{animationDelay:`${i*80}ms`}}>{c}</span>)}</b>}
    {motion==='impact_cut' && <><span className="v17-impact-rays"/><b className={`v17-word impact ${styleClass}`}>{sample}</b></>}
    {!['smart_mix','slide_mix','typewriter','impact_cut'].includes(motion) && <b className={`v17-word ${motion} ${styleClass}`} style={{fontSize:`${Math.max(30,Math.round(size*.34))}px`}}>{sample}</b>}
    <small>{MOTIONS.find(x=>x.id===motion)?.label}</small>
  </div>
}

export default function DynamicEditV2Selector({shotCount=0}:{shotCount?:number}){
  const [config,setConfig]=useState<StoredConfig>(()=>loadConfig()); const [tab,setTab]=useState<'basic'|'captions'|'sound'|'advanced'>('basic')
  useEffect(()=>saveConfig(config),[config])
  const style=useMemo(()=>SUBTITLE_PRESETS.find(x=>x.id===config.subtitleStyle)||SUBTITLE_PRESETS[0],[config.subtitleStyle])
  const motion=useMemo(()=>MOTIONS.find(x=>x.id===config.captionMotion)||MOTIONS[0],[config.captionMotion])
  return <section className="dynamic-edit-v2-shell v17" data-dynamic-edit-v2="true" data-placement="shot-plan-section">
    <div className="dynamic-edit-v2-header"><div><span className="dynamic-edit-v2-eyebrow">V10.40.8.18 · CLEAN SEMANTIC DIRECTOR</span><h4>剪辑引擎与动效</h4><p>只在“素材剪辑计划”出现；优先按上一页镜头顺序合成，没有锁定镜头时才做语义选材。</p></div><span className="dynamic-edit-v2-beta">{shotCount > 0 ? `已读取 ${shotCount} 个镜头` : '自动读取上一页镜头'}</span></div>
    <div className="dynamic-edit-v2-engine-grid compact">
      <button type="button" className={`dynamic-edit-v2-engine ${config.engine==='classic_a10_r4'?'selected':''}`} onClick={()=>setConfig(c=>({...c,engine:'classic_a10_r4'}))}><span className="dynamic-edit-v2-engine-tag">正式稳定版</span><strong>A10-R4 稳定剪辑</strong><small>完全保留原版。</small></button>
      <button type="button" className={`dynamic-edit-v2-engine dynamic ${config.engine==='dynamic_v2'?'selected':''}`} onClick={()=>setConfig(c=>({...c,engine:'dynamic_v2'}))}><span className="dynamic-edit-v2-engine-tag">镜头计划锁定版</span><strong>语义动态精剪</strong><small>语义变化才切镜；记录素材使用，减少跨任务重复。</small></button>
    </div>
    {config.engine==='dynamic_v2' && <div className="dynamic-edit-v2-settings">
      <div className="dynamic-edit-v2-toolbar">{([['basic','镜头规则'],['captions','字幕字体'],['sound','音效贴纸'],['advanced','验收规则']] as const).map(([id,label])=><button key={id} type="button" className={tab===id?'selected':''} onClick={()=>setTab(id)}>{label}</button>)}</div>
      <div className="dynamic-edit-v2-studio-grid"><MotionPreview motion={config.captionMotion} sample={motion.sample} styleClass={style.previewClass} size={config.captionSize}/><div className="dynamic-edit-v2-panel">
        {tab==='basic' && <div className="control-grid"><label><span>镜头切换规则</span><select value={config.visualPace} onChange={(e:ChangeEvent<HTMLSelectElement>)=>setConfig(c=>({...c,visualPace:e.target.value as DynamicVisualPace}))}><option value="calm">语义舒缓 · 约 2.8–5.0 秒</option><option value="balanced">语义均衡 · 约 2.2–4.2 秒（推荐）</option><option value="punchy">语义紧凑 · 约 1.8–3.5 秒</option></select></label><label><span>主要动效密度</span><select value={config.intensity} onChange={(e:ChangeEvent<HTMLSelectElement>)=>setConfig(c=>({...c,intensity:e.target.value as DynamicEditIntensity}))}><option value="restrained">克制</option><option value="balanced">均衡</option><option value="strong">加强</option></select></label><div className="rule-card"><b>不跟字幕碎片切镜</b><span>同一语义继续用当前素材；出现转折、对象变化、清单下一项或证据画面时才换。</span></div><div className="rule-card"><b>上一页镜头为准</b><span>{shotCount>0?`将按 ${shotCount} 个镜头的顺序、素材、起止点合成。`:'未检测到锁定镜头时，后端才会使用跨任务去重的语义自动选材。'}</span></div></div>}
        {tab==='captions' && <><div className="font-size-row"><div><b>字体大小</b><span>{config.captionSize}px</span></div><input type="range" min="84" max="160" step="2" value={config.captionSize} onChange={e=>setConfig(c=>({...c,captionSize:Number(e.target.value)}))}/><div className="font-buttons">{FONT_SIZES.map(x=><button key={x.value} type="button" className={config.captionSize===x.value?'selected':''} onClick={()=>setConfig(c=>({...c,captionSize:x.value}))}>{x.label}</button>)}</div></div><div className="control-grid"><label><span>字幕动效模板</span><select value={config.captionMotion} onChange={(e:ChangeEvent<HTMLSelectElement>)=>setConfig(c=>({...c,captionMotion:e.target.value as DynamicCaptionMotion}))}>{MOTIONS.map(x=><option key={x.id} value={x.id}>{x.label} · {x.sample}</option>)}</select></label><label><span>字幕位置</span><select value={config.captionPosition} onChange={(e:ChangeEvent<HTMLSelectElement>)=>setConfig(c=>({...c,captionPosition:e.target.value as DynamicCaptionPosition}))}><option value="auto">智能避让</option><option value="lower">底部安全区</option><option value="middle">中部强调区</option></select></label></div><div className="v17-motion-picker">{MOTIONS.map(x=><button key={x.id} type="button" className={config.captionMotion===x.id?'selected':''} onClick={()=>setConfig(c=>({...c,captionMotion:x.id}))}><span className={`motion-chip ${x.id}`}>{x.sample}</span><small>{x.label}</small></button>)}</div><div className="dynamic-edit-v2-subtitle-grid compact">{SUBTITLE_PRESETS.map(p=><button type="button" key={p.id} className={`dynamic-edit-v2-subtitle-card ${config.subtitleStyle===p.id?'selected':''}`} onClick={()=>setConfig(c=>({...c,subtitleStyle:p.id}))}><strong>{p.label}</strong><span className={`dynamic-edit-v2-subtitle-sample ${p.previewClass}`}>{p.sample}</span></button>)}</div></>}
        {tab==='sound' && <div className="control-grid"><label><span>音效音量</span><select value={config.sfxLevel} onChange={(e:ChangeEvent<HTMLSelectElement>)=>setConfig(c=>({...c,sfxLevel:e.target.value as DynamicSfxLevel}))}><option value="off">关闭</option><option value="light">轻柔（推荐）</option><option value="balanced">均衡</option><option value="strong">明显</option></select></label><label><span>音效组合</span><select value={config.sfxPack} onChange={(e:ChangeEvent<HTMLSelectElement>)=>setConfig(c=>({...c,sfxPack:e.target.value as DynamicSfxPack}))}><option value="smart_mix">语义智能混合</option><option value="soft_ui">轻柔 UI 音</option><option value="impact_mix">钩子重击混合</option></select></label><label><span>贴纸密度</span><select value={config.stickerLevel} onChange={(e:ChangeEvent<HTMLSelectElement>)=>setConfig(c=>({...c,stickerLevel:e.target.value as DynamicStickerLevel}))}><option value="off">关闭</option><option value="light">少量（推荐）</option><option value="balanced">均衡</option><option value="rich">丰富</option></select></label><label><span>贴纸风格</span><select value={config.stickerStyle} onChange={(e:ChangeEvent<HTMLSelectElement>)=>setConfig(c=>({...c,stickerStyle:e.target.value as DynamicStickerStyle}))}><option value="smart_mix">图标 + 手绘</option><option value="icons">主题图标</option><option value="doodles">手绘线条</option></select></label><label><span>贴纸位置</span><select value={config.stickerLayout} onChange={(e:ChangeEvent<HTMLSelectElement>)=>setConfig(c=>({...c,stickerLayout:e.target.value as DynamicStickerLayout}))}><option value="auto_safe">自动安全区</option><option value="top">上方两角</option><option value="side">左右侧边</option></select></label><div className="rule-card"><b>默认改为轻柔</b><span>音效不超过语音；尾部按音轨时长收口，不再出现最后几秒突然无声。</span></div></div>}
        {tab==='advanced' && <div className="advanced-rules"><article><b>镜头计划</b><span>锁定上一页素材 URL、顺序、起止点、速度与环境声。</span></article><article><b>素材记录器</b><span>跨任务记录最近使用素材；唯一素材用完前不重复。</span></article><article><b>字幕分词</b><span>保护“第一眼、生活半径、产权校验、退出路径”等完整词组。</span></article><article><b>音画尾部</b><span>最终视频按配音时长 + 0.12 秒结束，音画差控制在 0.25 秒内。</span></article></div>}
      </div></div>
    </div>}
  </section>
}
