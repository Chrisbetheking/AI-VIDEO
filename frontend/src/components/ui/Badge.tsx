import { cn } from '../../lib/utils'

interface BadgeProps { children: React.ReactNode; variant?: 'success' | 'warning' | 'danger' | 'neutral'; className?: string }
export function Badge({ children, variant = 'neutral', className }: BadgeProps) {
  const colors: Record<string, string> = {
    success: 'bg-green-900/50 text-green-400 border-green-800',
    warning: 'bg-yellow-900/50 text-yellow-400 border-yellow-800',
    danger: 'bg-red-900/50 text-red-400 border-red-800',
    neutral: 'bg-slate-800 text-slate-300 border-slate-700',
  }
  return <span className={cn('inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium border', colors[variant], className)}>{children}</span>
}
