import { cn } from '../../lib/utils'
export function StatusDot({ status }: { status: string }) {
  const colors: Record<string, string> = {
    configured: 'bg-green-500', Ready: 'bg-green-500',
    missing_key: 'bg-red-500', 'Missing Key': 'bg-red-500',
    disabled: 'bg-slate-500', Disabled: 'bg-slate-500',
    error: 'bg-red-500', Error: 'bg-red-500',
    unknown: 'bg-slate-600',
  }
  return <span className={cn('inline-block w-2 h-2 rounded-full', colors[status] || 'bg-slate-600')} />
}
