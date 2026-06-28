import React, { useState } from 'react'
import { LayoutDashboard, Video, MessageSquare, FolderOpen, Radio, Menu, X } from 'lucide-react'

const NAV_ITEMS = [
  { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { id: 'create-video', label: 'Create Video', icon: Video },
  { id: 'leads', label: 'Leads', icon: MessageSquare },
  { id: 'assets', label: 'Assets', icon: FolderOpen },
  { id: 'providers', label: 'Providers', icon: Radio },
] as const

export type NavId = typeof NAV_ITEMS[number]['id']

interface SidebarProps { active: NavId; onNavigate: (id: NavId) => void; collapsed: boolean; onToggle: () => void }

export function Sidebar({ active, onNavigate, collapsed, onToggle }: SidebarProps) {
  return (
    <aside className={`fixed left-0 top-0 h-full bg-slate-950 border-r border-slate-800 flex flex-col transition-all duration-200 z-40 ${collapsed ? 'w-16' : 'w-56'}`}>
      <div className="flex items-center justify-between h-14 px-4 border-b border-slate-800">
        {!collapsed && <span className="text-sm font-bold text-white tracking-wide">AI Growth Studio</span>}
        <button onClick={onToggle} className="text-slate-400 hover:text-white p-1">
          {collapsed ? <Menu size={18} /> : <X size={18} />}
        </button>
      </div>
      <nav className="flex-1 py-4 space-y-1 px-2">
        {NAV_ITEMS.map(item => (
          <button
            key={item.id}
            onClick={() => onNavigate(item.id)}
            className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
              active === item.id
                ? 'bg-blue-600/20 text-blue-400'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'
            }`}
          >
            <item.icon size={18} />
            {!collapsed && item.label}
          </button>
        ))}
      </nav>
      {!collapsed && (
        <div className="px-4 py-3 border-t border-slate-800 text-xs text-slate-500">
          AI Video Growth Studio v1.0
        </div>
      )}
    </aside>
  )
}
