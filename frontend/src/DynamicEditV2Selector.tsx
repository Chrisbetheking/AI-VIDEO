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
  subtitleStyle: 'dynamic_white_yellow', captionSize: 132, captionMotion: 'smart_mix', captionPosition: 'auto',
  sfxLevel: 'light', sfxPack: 'pro_short_video', stickerLevel: 'balanced', stickerLayout: 'auto_safe', stickerStyle: 'icons',
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
const FONT_SIZES = [{label:'标准大字',value:120},{label:'推荐',value:132},{label:'冲击大字',value:148},{label:'超大',value:166}]

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
      captionSize: Math.max(116,Math.min(176,Number(parsed.captionSize)||132)),
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
      <div className="v19-title"><span>V10.40.8.32 · KINETIC TYPE + MOTION ACCENTS</span><h4>AI 教学口播精剪</h4><p>默认使用更大的主字幕；关键词按真实发音时间独立弹出放大。贴纸改为参考视频式箭头、圈选、下划线和互动标注，不再使用小线稿图标或大文本框。</p></div>
      <div className="v19-shot-status"><strong>{shotCount}</strong><span>上一页镜头</span></div>
    </div>

    <div className="v19-engine-row">
      <button type="button" className={config.engine==='classic_a10_r4'?'selected':''} onClick={()=>setConfig(c=>({...c,engine:'classic_a10_r4'}))}>
        <em>稳定版</em><strong>A10-R4</strong><small>保持原逻辑，不做 AI 动态包装。</small>
      </button>
      <button type="button" className={config.engine==='dynamic_v2'?'selected':''} onClick={()=>setConfig(c=>({...c,engine:'dynamic_v2'}))}>
        <em>推荐</em><strong>AI 语义精剪</strong><small>长句不乱切；咖啡厅、商场、学校、医院等具体地点逐项快切。</small>
      </button>
    </div>

    {config.engine==='dynamic_v2' && <div className="v19-workbench">
      <nav className="v19-tabs">{([['director','AI 镜头导演'],['captions','字幕模板'],['sound','专业音效 / 贴纸'],['rules','验收规则']] as const).map(([id,label])=><button key={id} type="button" className={tab===id?'selected':''} onClick={()=>setTab(id)}>{label}</button>)}</nav>

      {tab==='director' && <div className="v19-compact-grid">
        <article className="v19-ai-card primary"><div><b>DeepSeek 自动判断镜头边界</b><span>读取完整口播、TTS 时间、上一页镜头和 R2 素材描述后输出剪辑节拍。</span></div><i>AI 自动</i></article>
        <article className="v19-rule"><b>常规解释</b><span>完整长句和同一意思保持 5–11 秒主镜头，逗号和字幕变化都不触发切镜。</span></article>
        <article className="v19-rule"><b>并列实体</b><span>咖啡厅 / 商场 / 学校 / 医院 / 地铁等，按口播出现顺序一个地点对应一个相邻小镜头。</span></article>
        <article className="v19-rule"><b>素材优先级</b><span>全库检索 300+ 素材；最近三条优先换新，旧素材明显更契合时允许复用。</span></article>
        <label className="v19-field"><span>画面动效密度</span><select value={config.intensity} onChange={(e:ChangeEvent<HTMLSelectElement>)=>setConfig(c=>({...c,intensity:e.target.value as DynamicEditIntensity}))}><option value="restrained">克制</option><option value="balanced">均衡（推荐）</option><option value="strong">加强</option></select></label>
      </div>}

      {tab==='captions' && <div className="v19-caption-layout">
        <MiniPreview motion={config.captionMotion} sample={motion.sample} styleClass={style.previewClass}/>
        <div className="v19-caption-controls">
          <div className="v19-font-row"><label><span>字号</span><strong>{config.captionSize}px</strong></label><input type="range" min="116" max="176" step="2" value={config.captionSize} onChange={(e:ChangeEvent<HTMLInputElement>)=>setConfig(c=>({...c,captionSize:Number(e.target.value)}))}/><div>{FONT_SIZES.map(x=><button key={x.value} type="button" className={config.captionSize===x.value?'selected':''} onClick={()=>setConfig(c=>({...c,captionSize:x.value}))}>{x.label}</button>)}</div></div>
          <div className="v19-two-fields"><label className="v19-field"><span>字幕动效</span><select value={config.captionMotion} onChange={(e:ChangeEvent<HTMLSelectElement>)=>setConfig(c=>({...c,captionMotion:e.target.value as DynamicCaptionMotion}))}>{MOTIONS.map(x=><option key={x.id} value={x.id}>{x.label}</option>)}</select></label><label className="v19-field"><span>字幕位置</span><select value={config.captionPosition} onChange={(e:ChangeEvent<HTMLSelectElement>)=>setConfig(c=>({...c,captionPosition:e.target.value as DynamicCaptionPosition}))}><option value="auto">智能避让</option><option value="lower">底部安全区</option><option value="middle">中部强调区</option></select></label></div>
          <div className="v19-style-row">{SUBTITLE_PRESETS.map(p=><button type="button" key={p.id} className={config.subtitleStyle===p.id?'selected':''} onClick={()=>setConfig(c=>({...c,subtitleStyle:p.id}))}><span className={p.previewClass}>{p.sample}</span><small>{p.label}</small></button>)}</div>
        </div>
      </div>}

      {tab==='sound' && <div className="v19-compact-grid">
        <article className="v19-ai-card primary"><div><b>官方许可专业音效库</b><span>按钩子、对比、流程、风险、证据和 CTA 分配不同声音；记录来源与许可证，不使用旧版自制垃圾 WAV。</span></div><i>PRO</i></article>
        <label className="v19-field"><span>音效强度</span><select value={config.sfxLevel} onChange={(e:ChangeEvent<HTMLSelectElement>)=>setConfig(c=>({...c,sfxLevel:e.target.value as DynamicSfxLevel}))}><option value="off">关闭</option><option value="light">专业轻量（推荐）</option><option value="balanced">专业标准</option><option value="strong">专业强化</option></select></label>
        <label className="v19-field"><span>音效风格</span><select value={config.sfxPack} onChange={(e:ChangeEvent<HTMLSelectElement>)=>setConfig(c=>({...c,sfxPack:e.target.value as DynamicSfxPack}))}><option value="pro_short_video">短视频通用</option><option value="pro_clean_ui">干净 UI / Pop</option><option value="pro_cinematic_light">轻电影感</option></select></label>
        <label className="v19-field"><span>动态标注密度</span><select value={config.stickerLevel} onChange={(e:ChangeEvent<HTMLSelectElement>)=>setConfig(c=>({...c,stickerLevel:e.target.value as DynamicStickerLevel}))}><option value="off">关闭</option><option value="light">少量（推荐）</option><option value="balanced">均衡</option><option value="rich">丰富</option></select></label>
        <label className="v19-field"><span>贴纸风格</span><select value={config.stickerStyle} onChange={(e:ChangeEvent<HTMLSelectElement>)=>setConfig(c=>({...c,stickerStyle:e.target.value as DynamicStickerStyle}))}><option value="icons">参考视频动态标注（推荐）</option><option value="smart_mix">极简功能点缀</option><option value="doodles">手写圈选与箭头</option></select></label>
        <label className="v19-field"><span>贴纸位置</span><select value={config.stickerLayout} onChange={(e:ChangeEvent<HTMLSelectElement>)=>setConfig(c=>({...c,stickerLayout:e.target.value as DynamicStickerLayout}))}><option value="auto_safe">自动安全区</option><option value="top">上方两角</option><option value="side">左右侧边</option></select></label>
      </div>}

      {tab==='rules' && <div className="v19-rule-grid"><article><b>长句稳镜</b><span>同一意思不按逗号乱切；相邻镜头禁止复用同一素材或同类城市地标画面。</span></article><article><b>地点快切</b><span>咖啡厅、商场、学校等并列小场景按出现顺序逐项切换，不把普通长句拆碎。</span></article><article><b>素材记忆</b><span>记录素材、源片段、语义角色和速度；最近三条优先换新，高匹配旧素材允许复用。</span></article><article><b>慢镜加速</b><span>缓慢航拍、慢推和静态镜头自动使用约 1.10–1.20 倍速度；合同和文字特写保持原速。</span></article><article><b>连续配音</b><span>普通解释尽量一次连续合成，只在真实 CTA 或明确长停顿处分组，避免 0.4 秒以上硬拼接。</span></article><article><b>收尾结构</b><span>长结尾按风险提醒、互动问题、评论 CTA 拆成不同画面，禁止单一双子塔空镜拖满。</span></article><article><b>参考字效</b><span>主字幕默认不少于 116px；关键词按真实发音时间单独弹到 148%，并配合圈选、箭头、下划线等动态标注。旧 Emoji、小线稿图标和大文本框全部禁用。</span></article></div>}
    </div>}
  </section>
}
