export function cn(...classes: (string | undefined | false | null)[]): string {
  return classes.filter(Boolean).join(' ')
}

export function intentLevelLabel(level: string): string {
  return level === 'high' ? 'High' : level === 'medium' ? 'Medium' : 'Low'
}

export function intentLevelColor(level: string): string {
  return level === 'high' ? '#16a34a' : level === 'medium' ? '#f59e0b' : '#6b7280'
}

export function statusBadgeColor(status: string): string {
  if (status === 'configured' || status === 'Ready') return '#16a34a'
  if (status === 'missing_key' || status === 'Missing Key') return '#ef4444'
  if (status === 'disabled' || status === 'Disabled') return '#6b7280'
  if (status === 'error' || status === 'Error') return '#ef4444'
  return '#6b7280'
}

export function formatDate(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

export function truncate(text: string, max: number): string {
  if (!text) return ''
  return text.length > max ? text.slice(0, max) + '...' : text
}

export function getApiBase(): string {
  return (window as any).__API_BASE || '/api'
}
