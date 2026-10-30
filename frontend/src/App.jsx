import { Suspense, lazy, useEffect, useRef, useState } from 'react'
import { Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom'
import CommandPalette from './components/CommandPalette'
import { Sidebar, TopBar } from './components/Nav'
import { Loading } from './components/ui'
import { useAuth, useToast } from './context/AppContext'
import { useApi } from './lib/live'
import Login from './pages/Login'

const CommandCenter = lazy(() => import('./pages/CommandCenter'))
const CaseWorkspace = lazy(() => import('./pages/CaseWorkspace'))
const ApprovalInbox = lazy(() => import('./pages/ApprovalInbox'))
const SimulatorLab = lazy(() => import('./pages/SimulatorLab'))
const KnowledgeExplorer = lazy(() => import('./pages/KnowledgeExplorer'))
const Metrics = lazy(() => import('./pages/Metrics'))
const AuditReplay = lazy(() => import('./pages/AuditReplay'))
const Admin = lazy(() => import('./pages/Admin'))

const read = (k, d) => { try { return localStorage.getItem(k) ?? d } catch { return d } }
const write = (k, v) => { try { localStorage.setItem(k, v) } catch { /* private mode */ } }

/** Toast (and a browser notification when allowed) whenever a new case starts waiting for approval. */
function useApprovalAlerts(waiting, enabled) {
  const toast = useToast()
  const seen = useRef(null)
  useEffect(() => {
    if (!waiting) return
    const ids = new Set(waiting.map((c) => c.id))
    if (seen.current) {
      const fresh = waiting.filter((c) => !seen.current.has(c.id))
      if (fresh.length) {
        const c = fresh[0]
        const msg = fresh.length > 1 ? `${fresh.length} new cases need approval` : `${c.id} · ${c.merchant} needs approval`
        toast(msg)
        if (enabled && 'Notification' in window && Notification.permission === 'granted' && document.hidden) {
          try { new Notification('ResolveOS', { body: msg, tag: c.id }) } catch { /* unsupported */ }
        }
      }
    }
    seen.current = ids
  }, [waiting])
}

function Shell() {
  const { user, ready } = useAuth()
  const toast = useToast()
  const loc = useLocation()
  const [collapsed, setCollapsed] = useState(() => read('ros-sidebar', 'open') === 'collapsed')
  const [drawer, setDrawer] = useState(false)
  const [palette, setPalette] = useState(false)
  const [notify, setNotify] = useState(() => read('ros-notify', 'off') === 'on')
  const { data: waiting } = useApi(user ? '/api/cases?status=awaiting_approval' : null)
  useApprovalAlerts(waiting, notify)

  useEffect(() => { if (!loc.hash) window.scrollTo(0, 0); setDrawer(false) }, [loc.pathname, loc.hash])
  useEffect(() => {
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setPalette((v) => !v) }
      if (e.key === 'Escape') setDrawer(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const toggleNotify = async () => {
    if (notify) { setNotify(false); write('ros-notify', 'off'); toast('Approval alerts off'); return }
    if ('Notification' in window && Notification.permission === 'default') await Notification.requestPermission()
    setNotify(true)
    write('ros-notify', 'on')
    toast('Notification' in window && Notification.permission === 'granted'
      ? 'Approval alerts on, including when this tab is in the background'
      : 'Approval alerts on in this tab (browser notifications are blocked)')
  }
  const toggleCollapsed = () => setCollapsed((v) => { write('ros-sidebar', v ? 'open' : 'collapsed'); return !v })

  if (!ready) return <Loading />
  if (!user) return <Navigate to="/login" replace state={{ from: loc.pathname }} />
  const n = waiting?.length || 0

  return (
    <div className="flex min-h-dvh">
      <aside aria-label="Sidebar" className={`sticky top-0 hidden h-dvh shrink-0 border-r border-line bg-side transition-[width] duration-200 lg:block ${collapsed ? 'w-[76px]' : 'w-[260px]'}`}>
        <Sidebar collapsed={collapsed} onToggle={toggleCollapsed} awaiting={n} />
      </aside>
      {drawer && (
        <div className="fixed inset-0 z-40 lg:hidden" style={{ background: 'var(--scrim)' }} onMouseDown={(e) => e.target === e.currentTarget && setDrawer(false)}>
          <aside aria-label="Sidebar" className="fade-in h-full w-[280px] max-w-[85vw] border-r border-line bg-side pb-[env(safe-area-inset-bottom)]">
            <Sidebar onNavigate={() => setDrawer(false)} awaiting={n} />
          </aside>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar onMenu={() => setDrawer(true)} onSearch={() => setPalette(true)} notify={notify} onToggleNotify={toggleNotify} />
        <div className="flex-1">
          <Suspense fallback={<Loading />}><Outlet /></Suspense>
        </div>
        <footer className="border-t border-line px-4 py-6 text-[12px] text-mute sm:px-6">
          ResolveOS demo. Every payment, processor and ledger shown here is simulated; no real money moves.
        </footer>
      </div>
      <CommandPalette open={palette} onClose={() => setPalette(false)} />
    </div>
  )
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<Shell />}>
        <Route index element={<CommandCenter />} />
        <Route path="cases/:id" element={<CaseWorkspace />} />
        <Route path="inbox" element={<ApprovalInbox />} />
        <Route path="simulator" element={<SimulatorLab />} />
        <Route path="knowledge" element={<KnowledgeExplorer />} />
        <Route path="metrics" element={<Metrics />} />
        <Route path="audit" element={<AuditReplay />} />
        <Route path="audit/:id" element={<AuditReplay />} />
        <Route path="admin" element={<Admin />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
