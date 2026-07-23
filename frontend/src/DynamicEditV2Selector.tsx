import { ChangeEvent, useEffect, useMemo, useState } from 'react'
import './dynamic-edit-v2-v10-40-8-13.css'

export type DynamicEditEngine = 'classic_a10_r4' | 'dynamic_v2'
export type DynamicEditIntensity = 'restrained' | 'balanced' | 'strong'
export type DynamicCaptionMotion =
  | 'smart_mix' | 'pop_bounce' | 'slide_mix' | 'lift_fade' | 'elastic'
  | 'rotate_snap' | 'typewriter' | 'impact_cut' | 'clean_fade'
export type DynamicCaptionPosition = 'auto' | 'lower' | 'middle'
export type DynamicSfxLevel = 'off' | 'light' | 'balanced' | 'strong'
export type DynamicSfxPack = 'pro_short_video' | 'pro_clean_ui' | 'pro_cinematic_light'
export type DynamicStickerLevel = 'off' | 'light' | 'balanced' | 'rich'
export type DynamicStickerLayout = 'auto_safe' | 'top' | 'side'
export type DynamicStickerStyle = 'smart_mix' | 'icons' | 'doodles'

export interface StoredConfig {
  engine: DynamicEditEngine
  intensity: DynamicEditIntensity
  shotDirector: 'ai_auto'
  subtitleStyle: string
  captionSize: number
  captionMotion: DynamicCaptionMotion
  captionPosition: DynamicCaptionPosition
  sfxLevel: DynamicSfxLevel
  sfxPack: DynamicSfxPack
  stickerLevel: DynamicStickerLevel
  stickerLayout: DynamicStickerLayout
  stickerStyle: DynamicStickerStyle
}

const STORAGE_KEY = 'ai-video-semantic-editor-v28'
const DEFAULT_CONFIG: StoredConfig = {
  engine: 'dynamic_v2', intensity: 'balanced', shotDirector: 'ai_auto',
  subtitleStyle: 'dynamic_white_yellow', captionSize: 118, captionMotion: 'smart_mix', captionPosition: 'auto',
  sfxLevel: 'light', sfxPack: 'pro_short_video', stickerLevel: 'light', stickerLayout: 'auto_safe', stickerStyle: 'smart_mix',
}

const MOTIONS: Array<{id: DynamicCaptionMotion; label: string; sample: string}> = [
  {id:'smart_mix',label:'智能混合',sample:'区域 价格'},
  {id:'pop_bounce',label:'弹跳放大',sample:'真实用途'},
  {id:'slide_mix',label:'左右滑入',sample:'交通 半径'},
  {id:'lift_fade',label:'上浮淡入',sample:'生活配套'},
  {id:'elastic',label:'弹性回弹',sample:'租客来源'},
  {id:'rotate_snap',label:'轻旋归位',sample:'产权校验'},
  {id:'typewriter',label:'逐字扫入',sample:'退出路径'},
  {id:'impact_cut',label:'关键词重击',sample:'别踩坑'},
  {id:'clean_fade',label:'极简淡入',sample:'提前想清楚'},
]
const SUBTITLE_PRESETS = [
  {id:'dynamic_white_yellow',label:'抖音白黄大字',sample:'先看区域',previewClass:'white-yellow'},
  {id:'dynamic_orange_white',label:'橙白视觉冲击',sample:'真实价格',previewClass:'orange-impact'},
  {id:'property_gold',label:'金白地产讲解',sample:'生活半径',previewClass:'gold-property'},
  {id:'minimal_white',label:'极简专业白字',sample:'产权校验',previewClass:'minimal-white'},
  {id:'red_question',label:'红黄疑问重击',sample:'为什么',previewClass:'red-hook'},
  {id:'list_rhythm',label:'清单节奏短句',sample:'第一项',previewClass:'list-rhythm'},
]
const FONT_SIZES = [{label:'紧凑',value:94},{label:'标准',value:112},{label:'大字',value:128},{label:'超大',value:146}]

function valid<T extends string>(value: unknown, options: readonly T[], fallback: T): T {
  return options.includes(value as T) ? value as T : fallback
}
function loadConfig(): StoredConfig {
  if (typeof window === 'undefined') return DEFAULT_CONFIG
  try {
    const parsed = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || '{}')
    return {
      engine: valid(parsed.engine,['classic_a10_r4','dynamic_v2'] as const,'dynamic_v2'),
      intensity: valid(parsed.intensity,['restrained','balanced','strong'] as const,'balanced'),
      shotDirector: 'ai_auto',
      subtitleStyle: valid(parsed.subtitleStyle,SUBTITLE_PRESETS.map(x=>x.id),'dynamic_white_yellow'),
      captionSize: Math.max(84,Math.min(160,Number(parsed.captionSize)||118)),
      captionMotion: valid(parsed.captionMotion,MOTIONS.map(x=>x.id),'smart_mix'),
      captionPosition: valid(parsed.captionPosition,['auto','lower','middle'] as const,'auto'),
      sfxLevel: valid(parsed.sfxLevel,['off','light','balanced','strong'] as const,'light'),
      sfxPack: valid(parsed.sfxPack,['pro_short_video','pro_clean_ui','pro_cinematic_light'] as const,'pro_short_video'),
      stickerLevel: valid(parsed.stickerLevel,['off','light','balanced','rich'] as const,'light'),
      stickerLayout: valid(parsed.stickerLayout,['auto_safe','top','side'] as const,'auto_safe'),
      stickerStyle: valid(parsed.stickerStyle,['smart_mix','icons','doodles'] as const,'smart_mix'),
    }
  } catch { return DEFAULT_CONFIG }
}
function saveConfig(config: StoredConfig) {
  window.localStorage.setItem(STORAGE_KEY,JSON.stringify(config))
  window.dispatchEvent(new CustomEvent('ai-video-dynamic-edit-v2-change',{detail:config}))
}
export function getDynamicEditV2Config(): StoredConfig { return typeof window==='undefined' ? DEFAULT_CONFIG : loadConfig() }
export function getDynamicEditV2StartEndpoint(): string {
  const c=getDynamicEditV2Config()
  if(c.engine!=='dynamic_v2') return '/api/video/existing-edit/start'
  const query=new URLSearchParams({
    intensity:c.intensity,shot_director:'ai_auto',subtitle_style:c.subtitleStyle,caption_size:String(c.captionSize),
    caption_motion:c.captionMotion,caption_position:c.captionPosition,sfx_level:c.sfxLevel,sfx_pack:c.sfxPack,
    sticker_level:c.stickerLevel,sticker_layout:c.stickerLayout,sticker_style:c.stickerStyle,
  })
  return `/api/video/existing-edit-v2/start?${query.toString()}`
}

function MiniPreview({motion, sample, styleClass}:{motion:DynamicCaptionMotion;sample:string;styleClass:string}) {
  return <div className={`v19-mini-preview v19-motion-${motion}`}>
    <div className="v19-preview-scene"><i/><i/><i/></div>
    <b className={`v19-preview-word ${styleClass}`}>{sample}</b>
    <span>{MOTIONS.find(x=>x.id===motion)?.label}</span>
  </div>
}

export default function DynamicEditV2Selector({shotCount=0}:{shotCount?:number}) {
  const [config,setConfig]=useState<StoredConfig>(()=>loadConfig())
  const [tab,setTab]=useState<'director'|'captions'|'sound'|'rules'>('director')
  useEffect(()=>saveConfig(config),[config])
  const style=useMemo(()=>SUBTITLE_PRESETS.find(x=>x.id===config.subtitleStyle)||SUBTITLE_PRESETS[0],[config.subtitleStyle])
  const motion=useMemo(()=>MOTIONS.find(x=>x.id===config.captionMotion)||MOTIONS[0],[config.captionMotion])

  return <section className="dynamic-edit-v2-shell v19" data-dynamic-edit-v2="true" data-placement="shot-plan-section">
    <div className="v19-topline">
      <div className="v19-title"><span>V10.40.8.28 · SEMANTIC EDITOR</span><h4>AI 教学口播精剪</h4><p>真实 TTS 决定最终时长；DeepSeek 只决定语义镜头、对比卡、流程卡、风险提醒、清单、CTA 和声音触发，不使用固定秒数裁剪。</p></div>
      <div className="v19-shot-status"><strong>{shotCount}</strong><span>上一页镜头</span></div>
    </div>

    <div className="v19-engine-row">
      <button type="button" className={config.engine==='classic_a10_r4'?'selected':''} onClick={()=>setConfig(c=>({...c,engine:'classic_a10_r4'}))}>
        <em>稳定版</em><strong>A10-R4</strong><small>保持原逻辑，不做 AI 动态包装。</small>
      </button>
      <button type="button" className={config.engine==='dynamic_v2'?'selected':''} onClick={()=>setConfig(c=>({...c,engine:'dynamic_v2'}))}>
        <em>推荐</em><strong>AI 语义精剪</strong><small>普通语句少切镜；商场、学校、医院等并列实体逐项切镜。</small>
      </button>
    </div>

    {config.engine==='dynamic_v2' && <div className="v19-workbench">
      <nav className="v19-tabs">{([['director','AI 镜头导演'],['captions','字幕模板'],['sound','专业音效 / 贴纸'],['rules','验收规则']] as const).map(([id,label])=><button key={id} type="button" className={tab===id?'selected':''} onClick={()=>setTab(id)}>{label}</button>)}</nav>

      {tab==='director' && <div className="v19-compact-grid">
        <article className="v19-ai-card primary"><div><b>DeepSeek 自动判断镜头边界</b><span>读取完整口播、TTS 时间、上一页镜头和 R2 素材描述后输出剪辑节拍。</span></div><i>AI 自动</i></article>
        <article className="v19-rule"><b>常规解释</b><span>一个意思保持一个主镜头，字幕变动不触发切镜。</span></article>
        <article className="v19-rule"><b>并列实体</b><span>商场 / 学校 / 医院 / 地铁等，一个实体对应一个镜头。</span></article>
        <article className="v19-rule"><b>素材优先级</b><span>优先用上一页选定素材；缺 URL 时按素材 ID、文件名回查 R2。</span></article>
        <label className="v19-field"><span>画面动效密度</span><select value={config.intensity} onChange={(e:ChangeEvent<HTMLSelectElement>)=>setConfig(c=>({...c,intensity:e.target.value as DynamicEditIntensity}))}><option value="restrained">克制</option><option value="balanced">均衡（推荐）</option><option value="strong">加强</option></select></label>
      </div>}

      {tab==='captions' && <div className="v19-caption-layout">
        <MiniPreview motion={config.captionMotion} sample={motion.sample} styleClass={style.previewClass}/>
        <div className="v19-caption-controls">
          <div className="v19-font-row"><label><span>字号</span><strong>{config.captionSize}px</strong></label><input type="range" min="84" max="160" step="2" value={config.captionSize} onChange={(e:ChangeEvent<HTMLInputElement>)=>setConfig(c=>({...c,captionSize:Number(e.target.value)}))}/><div>{FONT_SIZES.map(x=><button key={x.value} type="button" className={config.captionSize===x.value?'selected':''} onClick={()=>setConfig(c=>({...c,captionSize:x.value}))}>{x.label}</button>)}</div></div>
          <div className="v19-two-fields"><label className="v19-field"><span>字幕动效</span><select value={config.captionMotion} onChange={(e:ChangeEvent<HTMLSelectElement>)=>setConfig(c=>({...c,captionMotion:e.target.value as DynamicCaptionMotion}))}>{MOTIONS.map(x=><option key={x.id} value={x.id}>{x.label}</option>)}</select></label><label className="v19-field"><span>字幕位置</span><select value={config.captionPosition} onChange={(e:ChangeEvent<HTMLSelectElement>)=>setConfig(c=>({...c,captionPosition:e.target.value as DynamicCaptionPosition}))}><option value="auto">智能避让</option><option value="lower">底部安全区</option><option value="middle">中部强调区</option></select></label></div>
          <div className="v19-style-row">{SUBTITLE_PRESETS.map(p=><button type="button" key={p.id} className={config.subtitleStyle===p.id?'selected':''} onClick={()=>setConfig(c=>({...c,subtitleStyle:p.id}))}><span className={p.previewClass}>{p.sample}</span><small>{p.label}</small></button>)}</div>
        </div>
      </div>}

      {tab==='sound' && <div className="v19-compact-grid">
        <article className="v19-ai-card primary"><div><b>官方许可专业音效库</b><span>按钩子、对比、流程、风险、证据和 CTA 分配不同声音；记录来源与许可证，不使用旧版自制垃圾 WAV。</span></div><i>PRO</i></article>
        <label className="v19-field"><span>音效强度</span><select value={config.sfxLevel} onChange={(e:ChangeEvent<HTMLSelectElement>)=>setConfig(c=>({...c,sfxLevel:e.target.value as DynamicSfxLevel}))}><option value="off">关闭</option><option value="light">专业轻量（推荐）</option><option value="balanced">专业标准</option><option value="strong">专业强化</option></select></label>
        <label className="v19-field"><span>音效风格</span><select value={config.sfxPack} onChange={(e:ChangeEvent<HTMLSelectElement>)=>setConfig(c=>({...c,sfxPack:e.target.value as DynamicSfxPack}))}><option value="pro_short_video">短视频通用</option><option value="pro_clean_ui">干净 UI / Pop</option><option value="pro_cinematic_light">轻电影感</option></select></label>
        <label className="v19-field"><span>教学组件密度</span><select value={config.stickerLevel} onChange={(e:ChangeEvent<HTMLSelectElement>)=>setConfig(c=>({...c,stickerLevel:e.target.value as DynamicStickerLevel}))}><option value="off">关闭</option><option value="light">少量（推荐）</option><option value="balanced">均衡</option><option value="rich">丰富</option></select></label>
        <label className="v19-field"><span>教学组件风格</span><select value={config.stickerStyle} onChange={(e:ChangeEvent<HTMLSelectElement>)=>setConfig(c=>({...c,stickerStyle:e.target.value as DynamicStickerStyle}))}><option value="smart_mix">语义信息卡（推荐）</option><option value="icons">极简图标卡</option><option value="doodles">轻量标注线</option></select></label>
        <label className="v19-field"><span>教学组件位置</span><select value={config.stickerLayout} onChange={(e:ChangeEvent<HTMLSelectElement>)=>setConfig(c=>({...c,stickerLayout:e.target.value as DynamicStickerLayout}))}><option value="auto_safe">自动安全区</option><option value="top">上方两角</option><option value="side">左右侧边</option></select></label>
      </div>}

      {tab==='rules' && <div className="v19-rule-grid"><article><b>镜头时长</b><span>来自口播时间和 AI beat，不再读人工“舒缓 / 均衡 / 紧凑”秒数。</span></article><article><b>素材一致性</b><span>上一页镜头作为优先素材池，缺 URL 自动回查 R2，不再出现 1 镜头 / 0 素材。</span></article><article><b>重复控制</b><span>同任务唯一素材优先，跨任务读取使用记录后降权。</span></article><article><b>音效规则</b><span>同音效不连续；普通段落至少间隔 4 秒，实体清单只在开头做一次轻提示。</span></article><article><b>字幕完整性</b><span>字幕动效和切镜解耦，完整词组不拆散。</span></article><article><b>音画收口</b><span>最终时长以音轨为准，尾部差值超过 0.25 秒直接失败。</span></article></div>}
    </div>}
  </section>
}
