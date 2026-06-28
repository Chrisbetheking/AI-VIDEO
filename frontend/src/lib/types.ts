export type Industry = 'real_estate' | 'foreign_trade'
export type HumanMode = 'none' | 'digital_human' | 'human_intro' | 'human_pip'
export type LeadStatus = 'new' | 'replied' | 'added_wechat' | 'qualified' | 'closed'
export type IntentLevel = 'low' | 'medium' | 'high'

export interface HealthStatus {
  status: string; version: string
  minimax_enabled: boolean; minimax_video_model: string
}
export interface IndustryPackSummary {
  industry: string; pain_points_count: number
  hook_templates_count: number; cta_templates_count: number
}
export interface LeadItem {
  id: string; content: string; industry: string; platform: string
  intent_level: IntentLevel; intent_type: string
  suggested_reply: string; status: LeadStatus; created_at: string
}
export interface LeadAnalyzeResult {
  ok: boolean; lead_id?: string; intent_level: IntentLevel
  intent_type: string; suggested_reply: string; fallback_reply: string
  next_action: string; keywords_matched: string[]; confidence: number
}
export interface MinimaxStatus {
  ok: boolean; enabled: boolean; video_model: string; tts_model: string
  message: string; broll_prompts: { real_estate: string[]; foreign_trade: string[] }
}
export interface AssetItem {
  id: string; filename: string; original_name: string; kind: string
  url: string; size_bytes: number; created_at: string; folder: string; source_type: string
}
export interface ProviderInfo {
  name: string; type: 'tts' | 'llm' | 'video_gen' | 'digital_human'
  status: 'configured' | 'missing_key' | 'disabled' | 'error' | 'unknown'
  model: string; note?: string
}

export function intentLabel(l: string) { return l === 'high' ? 'High' : l === 'medium' ? 'Medium' : 'Low' }
export function intentColor(l: string) { return l === 'high' ? 'var(--green)' : l === 'medium' ? 'var(--orange)' : 'var(--muted)' }
export function formatDate(iso: string) { if (!iso) return ''; return new Date(iso).toLocaleDateString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) }
export function truncate(t: string, n: number) { return t && t.length > n ? t.slice(0, n) + '...' : t || '' }
