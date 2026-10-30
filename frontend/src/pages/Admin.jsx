import { useEffect, useState } from 'react'
import Icon from '../components/Icons'
import { SubNav } from '../components/Nav'
import { Avatar, ErrorNote, Hero, Loading, Modal, Page, SectionTitle } from '../components/ui'
import { api } from '../api/client'
import { useAuth, useToast } from '../context/AppContext'
import { useApi } from '../lib/live'

function KillSwitch({ cfg, isAdmin, onChange }) {
  const toast = useToast()
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  const [err, setErr] = useState(null)
  const on = cfg.kill_switch
  const word = on ? 'RESUME' : 'PAUSE'
  const submit = async () => {
    try {
      onChange(await api('/api/admin/kill-switch', { method: 'POST', body: { enabled: !on, confirm: text } }))
      toast(on ? 'Agent resumed.' : 'Agent paused. No action can run.', on ? 'success' : 'error')
      setOpen(false)
    } catch (e) { setErr(e) }
  }
  return (
    <section id="kill-switch" className={`card scroll-mt-32 p-6 ${on ? 'border-bad' : ''}`}>
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="max-w-xl">
          <h2 className="flex items-center gap-2 text-[22px] font-bold"><Icon name="power" size={22} className={on ? 'text-bad' : 'text-ok'} />Kill switch is {on ? 'on' : 'off'}</h2>
          <p className="mt-1 text-mute">{on ? 'The agent is paused. Nothing can be approved, auto-run or executed. People can still view cases.' : 'Turning it on stops every automatic action and every approval across all cases until it is turned off.'}</p>
        </div>
        <button className={`btn ${on ? 'btn-primary' : 'btn-danger'}`} disabled={!isAdmin} onClick={() => { setText(''); setErr(null); setOpen(true) }}>
          {on ? 'Turn the agent back on' : 'Pause the agent'}
        </button>
      </div>
      {!isAdmin && <p className="mt-3 text-sm text-mute">Only admins can change the kill switch.</p>}
      {open && (
        <Modal title={on ? 'Turn the agent back on?' : 'Pause the agent?'} onClose={() => setOpen(false)}>
          <p className="text-mute">{on ? 'Automatic actions and approvals resume immediately.' : 'Every suggestion and action stops for all cases. Pending approvals cannot be granted while it is on.'}</p>
          <label className="mt-5 block"><span className="mb-2 block font-bold">Type {word} to confirm</span>
            <input className="field" value={text} onChange={(e) => setText(e.target.value)} autoComplete="off" /></label>
          {err && <p className="mt-3 text-sm font-semibold text-bad">{err.message}</p>}
          <div className="mt-6 flex justify-end gap-3">
            <button className="btn" onClick={() => setOpen(false)}>Cancel</button>
            <button className={`btn ${on ? 'btn-primary' : 'btn-danger'}`} disabled={text !== word} onClick={submit}>{on ? 'Resume' : 'Pause the agent'}</button>
          </div>
        </Modal>
      )}
    </section>
  )
}

function Policy({ cfg, actions, isAdmin, onChange }) {
  const toast = useToast()
  const [form, setForm] = useState(cfg)
  const [err, setErr] = useState(null)
  useEffect(() => setForm(cfg), [cfg])
  const eligible = actions.filter((a) => a.auto_run_eligible && !a.moves_money)
  const save = async () => {
    try {
      const body = { evidence_max_age_s: +form.evidence_max_age_s, risk_auto_max: +form.risk_auto_max, max_retries: +form.max_retries,
        max_rejections: +form.max_rejections, auto_run_allowlist: form.auto_run_allowlist }
      onChange(await api('/api/admin/config', { method: 'PUT', body }))
      setErr(null)
      toast('Safety policy saved.', 'success')
    } catch (e) { setErr(e) }
  }
  const num = (k, label, hint) => (
    <label className="flex flex-col gap-1.5">
      <span className="text-sm font-bold">{label}</span>
      <input type="number" className="field" value={form[k]} disabled={!isAdmin} onChange={(e) => setForm({ ...form, [k]: e.target.value })} />
      <span className="text-[12.5px] text-mute">{hint}</span>
    </label>
  )
  return (
    <section className="card p-6">
      <div className="grid gap-5 sm:grid-cols-2">
        {num('evidence_max_age_s', 'Evidence freshness (seconds)', 'Older processor or ledger data cannot authorize actions.')}
        {num('risk_auto_max', 'Auto-run risk limit', 'Highest risk score allowed to run without a person.')}
        {num('max_retries', 'Retry budget', 'Retries allowed per payment.')}
        {num('max_rejections', 'Rejections before escalation', 'The case goes to its owner after this many.')}
      </div>
      <fieldset className="mt-6">
        <legend className="mb-2 text-sm font-bold">Auto-run allowlist</legend>
        <p className="mb-3 text-[12.5px] text-mute">Only actions that move no money are eligible. The gate still checks evidence, holds and the kill switch.</p>
        <div className="flex flex-wrap gap-2">
          {eligible.map((a) => {
            const onList = form.auto_run_allowlist.includes(a.type)
            return (
              <button key={a.type} type="button" aria-pressed={onList} disabled={!isAdmin}
                onClick={() => setForm({ ...form, auto_run_allowlist: onList ? form.auto_run_allowlist.filter((x) => x !== a.type) : [...form.auto_run_allowlist, a.type] })}
                className={`h-9 rounded-full border-[1.5px] px-3.5 text-[13px] font-semibold ${onList ? 'border-ink text-ink' : 'border-btnline text-mute'}`}>
                {onList && '✓ '}{a.label}
              </button>
            )
          })}
        </div>
      </fieldset>
      <div className="mt-4"><ErrorNote error={err} /></div>
      {isAdmin && <button className="btn btn-primary mt-6" onClick={save}>Save policy</button>}
      <div className="mt-6 rounded-2xl bg-panel p-4 text-sm">
        <b>Model:</b> {cfg.llm.enabled ? `NVIDIA API (${cfg.llm.models.ultra}, ${cfg.llm.models.super})` : 'No NVIDIA_API_KEY set, so the deterministic fallback diagnoser is used and labelled in every diagnosis.'}
      </div>
    </section>
  )
}

const ROLES = ['operator', 'approver', 'compliance', 'admin']
const cap = (r) => r[0].toUpperCase() + r.slice(1)

function Roles({ me }) {
  const toast = useToast()
  const { data: users, error, setData, reload } = useApi('/api/admin/users/all', { match: () => false })
  const [f, setF] = useState({ name: '', email: '', role: 'operator' })
  const [busy, setBusy] = useState(false)
  const replace = (nu) => setData(users.map((x) => (x.id === nu.id ? nu : x)))
  const setRole = async (u, role) => {
    try { replace(await api(`/api/admin/users/${u.id}/role`, { method: 'PUT', body: { role } })); toast(`${u.name} is now ${role}.`, 'success') } catch (e) { toast(e.message, 'error'); reload() }
  }
  const setActive = async (u, active) => {
    try { replace(await api(`/api/admin/users/${u.id}/active`, { method: 'PUT', body: { active } })); toast(`${u.name} ${active ? 'activated' : 'deactivated'}.`) } catch (e) { toast(e.message, 'error') }
  }
  const create = async (e) => {
    e.preventDefault()
    setBusy(true)
    try {
      const nu = await api('/api/admin/users', { method: 'POST', body: f })
      setData([...(users || []), nu])
      setF({ name: '', email: '', role: 'operator' })
      toast(`${nu.name} added as ${nu.role}.`, 'success')
    } catch (err) { toast(err.message, 'error') } finally { setBusy(false) }
  }
  if (error) return <ErrorNote error={error} />
  return (
    <>
      <ul className="card divide-y divide-line2 px-5">
        {(users || []).map((u) => (
          <li key={u.id} className={`flex flex-wrap items-center gap-3 py-4 ${u.active ? '' : 'opacity-60'}`}>
            <Avatar name={u.name} size={38} />
            <div className="min-w-0 flex-1">
              <div className="font-bold">{u.name}{u.id === me.id && <span className="font-normal text-mute"> (you)</span>}{!u.active && <span className="ml-2 text-[12px] font-semibold text-bad">Inactive</span>}</div>
              <div className="text-sm text-mute">{u.email}</div>
            </div>
            <label className="sr-only" htmlFor={`role-${u.id}`}>Role for {u.name}</label>
            <select id={`role-${u.id}`} className="field !w-auto !py-2" value={u.role} onChange={(e) => setRole(u, e.target.value)} disabled={!u.active}>
              {ROLES.map((r) => <option key={r} value={r}>{cap(r)}</option>)}
            </select>
            {u.id !== me.id && <button className="btn btn-sm" onClick={() => setActive(u, !u.active)}>{u.active ? 'Deactivate' : 'Activate'}</button>}
          </li>
        ))}
      </ul>
      <form onSubmit={create} className="card mt-4 grid gap-3 p-5 sm:grid-cols-[1fr_1fr_auto_auto] sm:items-end">
        <label className="flex flex-col gap-1.5"><span className="text-sm font-bold">Name</span><input className="field" required minLength={2} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></label>
        <label className="flex flex-col gap-1.5"><span className="text-sm font-bold">Email</span><input className="field" type="email" required value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></label>
        <label className="flex flex-col gap-1.5"><span className="text-sm font-bold">Role</span>
          <select className="field" value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}>{ROLES.map((r) => <option key={r} value={r}>{cap(r)}</option>)}</select></label>
        <button className="btn btn-primary" disabled={busy}><Icon name="plus" size={16} />Add user</button>
      </form>
    </>
  )
}

function SystemStatus() {
  const { data } = useApi('/api/health', { match: () => false })
  if (!data) return null
  const mlState = data.ml?.state === 'ready' ? `ready (${data.ml.kb_chunks.toLocaleString()} KB chunks, loaded in ${data.ml.load_seconds}s)`
    : data.ml?.state === 'loading' ? 'loading…' : `unavailable${data.ml?.error ? `: ${data.ml.error}` : ''}`
  const rows = [['Database', data.database], ['Live updates', data.live_updates], ['Diagnosis model', data.llm], ['ML / RAG stack', mlState],
    ['Risk scorer', data.risk_scorer], ['Retrieval', data.retrieval], ['Payments', 'simulated']]
  return (
    <dl className="card grid grid-cols-2 gap-x-6 gap-y-3 p-6 sm:grid-cols-3">
      {rows.map(([k, v]) => <div key={k}><dt className="text-[12.5px] text-mute">{k}</dt><dd className="font-semibold">{v}</dd></div>)}
    </dl>
  )
}

export default function Admin() {
  const { user } = useAuth()
  const isAdmin = user.role === 'admin'
  const { data: cfg, setData } = useApi('/api/admin/config', { match: (m) => m.type === 'config.updated' })
  const { data: actions } = useApi('/api/actions', { match: () => false })
  if (!cfg || !actions) return <Loading />
  return (
    <>
      <SubNav title="Admin" links={[{ id: 'kill-switch', label: 'Kill switch' }, { id: 'policy', label: 'Safety policy' }, { id: 'roles', label: 'Users' }, { id: 'system', label: 'System' }]} />
      <Hero title="Admin" subtitle={isAdmin ? 'Safety policy, roles and the kill switch. Every change is written to the audit trail.' : 'Read-only view. Sign in as an admin to change settings.'} />
      <Page>
        <KillSwitch cfg={cfg} isAdmin={isAdmin} onChange={setData} />
        <div className="mt-14"><SectionTitle id="policy">Safety policy</SectionTitle><Policy cfg={cfg} actions={actions} isAdmin={isAdmin} onChange={setData} /></div>
        {isAdmin && <div className="mt-14"><SectionTitle id="roles">Users and roles</SectionTitle><Roles me={user} /></div>}
        <div className="mt-14"><SectionTitle id="system">System status</SectionTitle><SystemStatus /></div>
      </Page>
    </>
  )
}
