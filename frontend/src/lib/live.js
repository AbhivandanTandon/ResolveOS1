import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'

// One shared WebSocket for the whole app, reconnecting with backoff.
const listeners = new Set()
let socket = null
let status = 'connecting'
const statusListeners = new Set()

function setStatus(s) {
  status = s
  statusListeners.forEach((fn) => fn(s))
}

function connect(attempt = 0) {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  socket = new WebSocket(`${proto}://${location.host}/ws`)
  socket.onopen = () => setStatus('live')
  socket.onmessage = (e) => {
    let msg
    try { msg = JSON.parse(e.data) } catch { return }
    listeners.forEach((fn) => fn(msg))
  }
  socket.onclose = () => {
    setStatus('offline')
    setTimeout(() => connect(attempt + 1), Math.min(8000, 500 * 2 ** attempt))
  }
}

export function useLiveEvents(handler) {
  const ref = useRef(handler)
  ref.current = handler
  useEffect(() => {
    if (!socket) connect()
    const fn = (m) => ref.current(m)
    listeners.add(fn)
    return () => listeners.delete(fn)
  }, [])
}

export function useLiveStatus() {
  const [s, setS] = useState(status)
  useEffect(() => {
    if (!socket) connect()
    statusListeners.add(setS)
    return () => statusListeners.delete(setS)
  }, [])
  return s
}

/** Fetch JSON and refetch when the server reports a change. `match` filters which live events matter. */
export function useApi(path, { match = (m) => m.type === 'case.updated' || m.type === 'config.updated' } = {}) {
  const [state, setState] = useState({ data: null, error: null, loading: true })
  const timer = useRef(null)
  const load = useCallback(async () => {
    if (!path) return
    try {
      const data = await api(path)
      setState({ data, error: null, loading: false })
    } catch (error) {
      setState((s) => ({ ...s, error, loading: false }))
    }
  }, [path])
  useEffect(() => {
    setState((s) => ({ ...s, loading: true }))
    load()
  }, [load])
  useLiveEvents((m) => {
    if (!match(m)) return
    clearTimeout(timer.current)
    timer.current = setTimeout(load, 250)
  })
  return { ...state, reload: load, setData: (data) => setState({ data, error: null, loading: false }) }
}
