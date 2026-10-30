import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { api, getToken, setToken } from '../api/client'

const AuthCtx = createContext(null)
const ToastCtx = createContext(() => {})

export function AppProvider({ children }) {
  const [user, setUser] = useState(null)
  const [ready, setReady] = useState(false)
  const [toast, setToastState] = useState(null)
  const timer = useRef(null)

  useEffect(() => {
    if (!getToken()) { setReady(true); return }
    api('/api/auth/me').then(setUser).catch(() => setToken(null)).finally(() => setReady(true))
  }, [])

  useEffect(() => {
    const onUnauth = () => { setToken(null); setUser(null) }
    window.addEventListener('ros:unauthorized', onUnauth)
    return () => window.removeEventListener('ros:unauthorized', onUnauth)
  }, [])

  const login = useCallback(async (email) => {
    const r = await api('/api/auth/login', { method: 'POST', body: { email } })
    setToken(r.token)
    setUser(r.user)
    return r.user
  }, [])

  const logout = useCallback(() => { setToken(null); setUser(null) }, [])

  const showToast = useCallback((message, tone = 'info') => {
    clearTimeout(timer.current)
    setToastState({ message, tone, id: Date.now() })
    timer.current = setTimeout(() => setToastState(null), 3600)
  }, [])

  return (
    <AuthCtx.Provider value={{ user, ready, login, logout }}>
      <ToastCtx.Provider value={showToast}>
        {children}
        <div role="status" aria-live="polite" className="fixed z-50 left-1/2 -translate-x-1/2 bottom-[calc(20px+env(safe-area-inset-bottom))] w-max max-w-[calc(100vw-32px)]">
          {toast && (
            <div key={toast.id} className="fade-in flex items-center gap-3 rounded-full bg-ink text-onink px-5 py-3 text-sm font-semibold shadow-2xl">
              {toast.tone === 'error' && <span className="size-2 rounded-full bg-bad" aria-hidden />}
              {toast.tone === 'success' && <span className="size-2 rounded-full bg-ok" aria-hidden />}
              <span>{toast.message}</span>
            </div>
          )}
        </div>
      </ToastCtx.Provider>
    </AuthCtx.Provider>
  )
}

export const useAuth = () => useContext(AuthCtx)
export const useToast = () => useContext(ToastCtx)
