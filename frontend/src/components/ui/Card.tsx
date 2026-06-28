import React from 'react'
import { cn } from '../../lib/utils'

interface CardProps { children: React.ReactNode; className?: string; title?: string; subtitle?: string }
export function Card({ children, className, title, subtitle }: CardProps) {
  return (
    <div className={cn('bg-slate-900 border border-slate-800 rounded-xl p-6', className)}>
      {title && <h3 className="text-lg font-semibold text-white mb-1">{title}</h3>}
      {subtitle && <p className="text-sm text-slate-400 mb-4">{subtitle}</p>}
      {children}
    </div>
  )
}
