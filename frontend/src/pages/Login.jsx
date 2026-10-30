import { useEffect, useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import Icon from '../components/Icons'
import { Avatar, ErrorNote } from '../components/ui'
import { api } from '../api/client'
import { useAuth } from '../context/AppContext'

const ROLE_INFO = {
  operator: 'Investigates cases, rejects plans, requests evidence, approves actions that move no money.',
  approver: 'Approves or rejects actions, including those that move money.',
  compliance: 'Owns compliance holds. The only role that can act on them.',
  admin: 'Manages roles, safety policy and the kill switch.',
}

export default function Login() {
  const { user, login } = useAuth()
  const nav = useNavigate()
  const loc = useLocation()
  const [users, setUsers] = useState([])
  const [sel, setSel] = useState('anika.rao@example.com')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => { api('/api/auth/users').then(setUsers).catch(setError) }, [])
  if (user) return <Navigate to={loc.state?.from || '/'} replace />

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(sel)
      nav(loc.state?.from || '/', { replace: true })
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-dvh flex-col items-center px-4 py-12 sm:py-20">
      <span className="inline-flex size-14 items-center justify-center rounded-2xl bg-ink text-onink"><Icon name="logo" size={30} /></span>
      <h1 className="mt-6 text-center text-[40px] font-bold leading-tight tracking-[-0.02em] sm:text-[48px]">Sign in to ResolveOS</h1>
      <p className="mt-3 max-w-xl text-center text-[19px] text-mute text-balance">
        The payment-operations copilot that investigates, explains and only acts when it is safe.
      </p>
      <form onSubmit={submit} className="mt-10 w-full max-w-xl">
        <fieldset>
          <legend className="eyebrow mb-3">Choose a demo account</legend>
          <div className="grid gap-3 sm:grid-cols-2">
            {users.map((u) => (
              <label key={u.id} className={`card flex cursor-pointer flex-col gap-2 p-4 transition-colors ${sel === u.email ? 'border-ink' : 'hover:border-btnline'}`}>
                <input type="radio" name="user" value={u.email} checked={sel === u.email} onChange={() => setSel(u.email)} className="sr-only" />
                <div className="flex items-center gap-3">
                  <Avatar name={u.name} size={36} />
                  <div className="min-w-0"><div className="font-bold">{u.name}</div><div className="text-sm capitalize text-mute">{u.role}</div></div>
                  {sel === u.email && <Icon name="check" size={18} className="ml-auto text-ok" />}
                </div>
                <p className="text-[13px] leading-snug text-mute">{ROLE_INFO[u.role]}</p>
              </label>
            ))}
          </div>
        </fieldset>
        <div className="mt-4"><ErrorNote error={error} /></div>
        <button className="btn btn-primary mt-6 w-full" disabled={busy || !users.length}>{busy ? 'Signing in…' : 'Continue'}</button>
        <p className="mt-4 text-center text-[13px] text-mute">Mock sign-in for the demo. Roles are enforced on the server.</p>
      </form>
    </div>
  )
}
