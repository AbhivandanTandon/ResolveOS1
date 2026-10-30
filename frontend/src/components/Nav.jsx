import { useEffect, useState } from 'react'
import { Link, NavLink, useLocation } from 'react-router-dom'
import Icon from './Icons'
import { Avatar } from './ui'
import { useAuth } from '../context/AppContext'
import { useApi, useLiveStatus } from '../lib/live'

export const NAV_GROUPS = [
  {
    label: 'Operations',
    items: [
      { to: '/', label: 'Command Center', icon: 'command', end: true },
      { to: '/inbox', label: 'Approvals', icon: 'inbox', badge: 'inbox' },
      { to: '/simulator', label: 'Simulator Lab', icon: 'simulator' },
    ],
  },
  {
    label: 'Intelligence',
    items: [
      { to: '/knowledge', label: 'Knowledge', icon: 'knowledge' },
      { to: '/metrics', label: 'Metrics', icon: 'metrics' },
    ],
  },
  {
    label: 'Governance',
    items: [
      { to: '/audit', label: 'Audit & Replay', icon: 'audit' },
      { to: '/admin', label: 'Admin', icon: 'admin' },
    ],
  },
]
export const PAGES = NAV_GROUPS.flatMap((g) => g.items)

function effectiveTheme() {
  const t = document.documentElement.getAttribute('data-theme')
  if (t) return t
  return window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
}

export function ThemeToggle() {
  const [theme, setTheme] = useState(effectiveTheme)
  const flip = () => {
    const next = theme === 'dark' ? 'light' : 'dark'
    document.documentElement.setAttribute('data-theme', next)
    try { localStorage.setItem('ros-theme', next) } catch { /* ignore */ }
    setTheme(next)
  }
  return (
    <button onClick={flip} className="inline-flex size-9 items-center justify-center rounded-full text-nav hover:bg-pill hover:text-ink"
      aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`} title="Theme">
      <Icon name={theme === 'dark' ? 'sun' : 'moon'} size={18} />
    </button>
  )
}

function KillPill() {
  const { data } = useApi('/api/admin/config', { match: (m) => m.type === 'config.updated' })
  const on = data?.kill_switch
  return (
    <Link to="/admin#kill-switch" className={`inline-flex h-8 items-center gap-2 whitespace-nowrap rounded-full border px-3 text-[12.5px] font-semibold ${on ? 'border-bad text-bad' : 'border-line text-nav hover:text-ink'}`}
      aria-label={on ? 'Kill switch is on. Agent paused. Open Admin.' : 'Agent active. Kill switch off. Open Admin.'}>
      <i className={`size-2 rounded-full ${on ? 'bg-bad' : 'bg-ok'}`} aria-hidden />
      <span className="hidden sm:inline">{on ? 'Agent paused' : 'Agent active'}</span>
    </Link>
  )
}

/** Vertical navigation. `collapsed` shows an icon rail; `onNavigate` closes the mobile drawer. */
export function Sidebar({ collapsed = false, onToggle, onNavigate, awaiting = 0 }) {
  const { user, logout } = useAuth()
  const loc = useLocation()
  const isActive = (to, end) => (end ? loc.pathname === to || (to === '/' && loc.pathname.startsWith('/cases')) : loc.pathname.startsWith(to))
  return (
    <div className="flex h-full flex-col gap-1 px-3 py-4">
      <div className={`mb-4 flex items-center ${collapsed ? 'justify-center' : 'justify-between px-2'}`}>
        <Link to="/" onClick={onNavigate} className="flex items-center gap-2.5 text-[17px] font-bold tracking-tight" aria-label="ResolveOS home">
          <span className="inline-flex size-8 items-center justify-center rounded-[10px] bg-ink text-onink"><Icon name="logo" size={17} /></span>
          {!collapsed && 'ResolveOS'}
        </Link>
      </div>
      <nav aria-label="Primary" className="flex flex-1 flex-col gap-5 overflow-y-auto">
        {NAV_GROUPS.map((g) => (
          <div key={g.label}>
            {!collapsed ? <div className="mb-1 px-3 text-[11px] font-semibold uppercase tracking-[.06em] text-mute">{g.label}</div>
              : <div className="mx-auto mb-2 h-px w-8 bg-line" aria-hidden />}
            <ul className="flex flex-col gap-0.5">
              {g.items.map((p) => {
                const active = isActive(p.to, p.end)
                const count = p.badge === 'inbox' ? awaiting : 0
                return (
                  <li key={p.to}>
                    <NavLink to={p.to} end={p.end} onClick={onNavigate} title={collapsed ? p.label : undefined}
                      aria-current={active ? 'page' : undefined}
                      className={`relative flex items-center gap-3 rounded-xl text-[14.5px] transition-colors ${collapsed ? 'justify-center px-0 py-2.5' : 'px-3 py-2'} ${active ? 'bg-pill font-semibold text-ink' : 'font-medium text-nav hover:bg-panel/60 hover:text-ink'}`}>
                      <Icon name={p.icon} size={19} className={active ? 'text-ink' : 'text-mute'} />
                      {!collapsed && <span className="flex-1 truncate">{p.label}</span>}
                      {count > 0 && (collapsed
                        ? <span className="absolute right-2 top-1.5 size-2 rounded-full bg-ink" aria-label={`${count} waiting`} />
                        : <span className="rounded-full bg-ink px-1.5 text-[11px] font-bold leading-[18px] text-onink">{count}</span>)}
                    </NavLink>
                  </li>
                )
              })}
            </ul>
          </div>
        ))}
      </nav>
      <div className={`mt-2 border-t border-line pt-3 ${collapsed ? 'flex flex-col items-center gap-2' : ''}`}>
        {collapsed ? (
          <button onClick={logout} title={`${user.name} · Sign out`} className="rounded-full p-0.5 hover:bg-pill"><Avatar name={user.name} size={34} /></button>
        ) : (
          <div className="flex items-center gap-3 rounded-xl px-2 py-1.5">
            <Avatar name={user.name} size={36} />
            <div className="min-w-0 flex-1"><div className="truncate text-[14px] font-bold">{user.name}</div><div className="text-[12.5px] capitalize text-mute">{user.role}</div></div>
            <button onClick={logout} className="rounded-full px-2.5 py-1 text-[12.5px] font-semibold text-mute hover:bg-pill hover:text-ink">Sign out</button>
          </div>
        )}
        {onToggle && (
          <button onClick={onToggle} className={`mt-2 flex items-center gap-2 rounded-xl text-[12.5px] font-semibold text-mute hover:bg-panel/60 hover:text-ink ${collapsed ? 'justify-center p-2' : 'w-full px-3 py-2'}`}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'} title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}>
            <Icon name={collapsed ? 'chevron' : 'arrowLeft'} size={16} />{!collapsed && 'Collapse'}
          </button>
        )}
      </div>
    </div>
  )
}

export function TopBar({ onMenu, onSearch, notify, onToggleNotify }) {
  const live = useLiveStatus()
  return (
    <header className="glass sticky top-0 z-30 border-b border-line">
      <div className="flex h-[52px] items-center gap-2 px-4 sm:px-6">
        <button className="inline-flex size-9 items-center justify-center rounded-full hover:bg-pill lg:hidden" onClick={onMenu} aria-label="Open navigation">
          <Icon name="menu" size={20} />
        </button>
        <Link to="/" className="flex items-center gap-2 font-bold lg:hidden" aria-label="ResolveOS home">
          <span className="inline-flex size-7 items-center justify-center rounded-lg bg-ink text-onink"><Icon name="logo" size={15} /></span>
          <span className="hidden sm:inline">ResolveOS</span>
        </Link>
        <button onClick={onSearch} className="ml-auto flex h-9 min-w-0 items-center gap-2 rounded-full border border-line bg-card px-3.5 text-[13.5px] text-mute hover:border-btnline lg:ml-0 lg:w-80"
          aria-label="Search cases, knowledge and pages">
          <Icon name="search" size={16} /><span className="hidden truncate sm:inline">Search cases, knowledge, pages</span>
          <span className="kbd ml-auto hidden lg:inline">⌘K</span>
        </button>
        <div className="flex items-center gap-1.5 lg:ml-auto">
          <span className="hidden items-center gap-1.5 px-2 text-[12px] font-medium text-mute md:inline-flex" title={`Live updates: ${live}`}>
            <i className={`size-1.5 rounded-full ${live === 'live' ? 'bg-ok' : 'pulse bg-warn'}`} aria-hidden />{live === 'live' ? 'Live' : 'Reconnecting'}
          </span>
          <button onClick={onToggleNotify} className={`inline-flex size-9 items-center justify-center rounded-full hover:bg-pill ${notify ? 'text-ink' : 'text-mute'}`}
            aria-pressed={notify} aria-label={notify ? 'Approval alerts on' : 'Approval alerts off'} title={notify ? 'Approval alerts on' : 'Turn on approval alerts'}>
            <Icon name={notify ? 'bell' : 'bellOff'} size={18} />
          </button>
          <ThemeToggle />
          <KillPill />
        </div>
      </div>
    </header>
  )
}

/** Apple-style local navigation: page title on the left, in-page sections on the right. */
export function SubNav({ title, links = [], action }) {
  const [active, setActive] = useState(links[0]?.id)
  useEffect(() => {
    if (!links.length) return
    const els = links.map((l) => document.getElementById(l.id)).filter(Boolean)
    const io = new IntersectionObserver((entries) => {
      const vis = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)
      if (vis[0]) setActive(vis[0].target.id)
    }, { rootMargin: '-120px 0px -55% 0px' })
    els.forEach((el) => io.observe(el))
    return () => io.disconnect()
  }, [links.map((l) => l.id).join()])
  return (
    <div className="glass sticky top-[52px] z-20 border-b border-line">
      <div className="mx-auto flex h-[52px] max-w-[1280px] items-center gap-4 px-4 sm:px-6">
        <div className="min-w-0 truncate text-[19px] font-bold tracking-tight sm:text-[21px]">{title}</div>
        <div className="ml-auto flex min-w-0 items-center gap-1 overflow-x-auto">
          {links.map((l) => (
            <a key={l.id} href={`#${l.id}`} onClick={(e) => { e.preventDefault(); document.getElementById(l.id)?.scrollIntoView({ behavior: 'smooth', block: 'start' }); setActive(l.id) }}
              className={`hidden whitespace-nowrap rounded-full px-3 py-1 text-[12.5px] font-medium sm:inline-block ${active === l.id ? 'bg-pill text-ink' : 'text-mute hover:text-ink'}`}>
              {l.label}
            </a>
          ))}
          {action}
        </div>
      </div>
    </div>
  )
}
