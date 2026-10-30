import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { SubNav } from '../components/Nav'
import { Avatar, Empty, ErrorNote, GateChecks, Hero, Loading, Money, Page, Risk } from '../components/ui'
import { RejectModal } from './CaseWorkspace'
import { api } from '../api/client'
import { useAuth, useToast } from '../context/AppContext'
import { useApi } from '../lib/live'
import { ROUTE, timeAgo } from '../lib/format'

/** One review card. Loads the case detail so the plan, gate result and permissions come from the server. */
function ReviewCard({ id, selected, onSelect }) {
  const toast = useToast()
  const { data: d, setData } = useApi(`/api/cases/${id}`, { match: (m) => m.type === 'case.updated' && m.case_id === id })
  const [busy, setBusy] = useState(false)
  const [rejecting, setRejecting] = useState(false)
  const [open, setOpen] = useState(false)
  if (!d) return <div className="card h-48 pulse" />
  const c = d.case
  const top = d.recommendations.find((r) => r.status === 'proposed')
  if (!top || c.status !== 'awaiting_approval') return null
  const approve = async () => {
    setBusy(true)
    try {
      const nd = await api(`/api/cases/${id}/recommendations/${top.id}/approve`, { method: 'POST' })
      setData(nd)
      toast(`${id}: ran once, ${nd.case.status}.`, 'success')
    } catch (e) { toast(e.message, 'error') } finally { setBusy(false) }
  }
  return (
    <article onClick={onSelect} data-case={id}
      className={`card flex flex-col gap-4 p-5 transition-colors sm:p-6 ${selected ? 'border-ink' : ''}`} aria-current={selected || undefined}>
      <div className="flex flex-wrap items-center gap-3">
        <Avatar name={c.merchant} size={40} />
        <div className="min-w-0 flex-1"><div className="font-bold">{c.merchant}</div><div className="text-[13px] text-mute">{c.id} · {timeAgo(c.created_at)}</div></div>
        <Money minor={c.amount_minor} currency={c.currency} className="text-[22px]" />
      </div>
      <div>
        <div className="eyebrow">{c.issue}</div>
        <div className="mt-1 text-[19px] font-bold leading-snug">{top.title}</div>
        <p className="mt-1 text-sm text-mute">{top.description}</p>
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
        <Risk score={top.risk_score} />
        <span className="text-mute">{top.moves_money ? 'Moves money' : 'Moves no money'}</span>
        <span className="text-mute">Gate: <b className="text-ink">{ROUTE[top.gate_decision]}</b></span>
        <button className="link text-sm" onClick={(e) => { e.stopPropagation(); setOpen((v) => !v) }} aria-expanded={open}>{open ? 'Hide' : 'Show'} evidence</button>
      </div>
      {open && (
        <div className="grid gap-4 rounded-2xl bg-panel p-4 md:grid-cols-2">
          <div><div className="mb-2 text-sm font-bold">Safety gate</div><GateChecks checks={top.gate_checks} compact /></div>
          <ul className="flex flex-col gap-2 text-sm">
            {d.evidence.map((e) => <li key={e.id}><span className="text-mute">{e.label}:</span> <b>{e.summary}</b>{e.stale && <span className="text-warn"> (stale)</span>}</li>)}
          </ul>
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        <Link to={`/cases/${id}`} className="btn btn-sm">Open case</Link>
        <button className="btn btn-sm" disabled={!d.permissions.reject || busy} onClick={(e) => { e.stopPropagation(); setRejecting(true) }}>Reject</button>
        <button className="btn btn-sm btn-primary ml-auto sm:ml-0" disabled={!d.permissions.approve || busy} onClick={(e) => { e.stopPropagation(); approve() }}
          data-approve={id}>{busy ? 'Running…' : 'Approve'}</button>
      </div>
      {!d.permissions.approve && <p className="text-[12.5px] text-mute">Your role cannot approve this action{top.moves_money ? ' because it can move money' : ''}.</p>}
      {rejecting && <RejectModal rec={top} caseInfo={d} onClose={() => setRejecting(false)} onDone={(nd) => { setData(nd); setRejecting(false) }} />}
    </article>
  )
}

export default function ApprovalInbox() {
  const { user } = useAuth()
  const { data, error, loading } = useApi('/api/cases?status=awaiting_approval')
  const [sel, setSel] = useState(0)
  const list = data || []

  useEffect(() => {
    const onKey = (e) => {
      const tag = (e.target.tagName || '').toLowerCase()
      if (['input', 'textarea', 'select'].includes(tag) || e.metaKey || e.ctrlKey || document.querySelector('[role="dialog"]')) return
      if (e.key === 'j') setSel((s) => Math.min(list.length - 1, s + 1))
      if (e.key === 'k') setSel((s) => Math.max(0, s - 1))
      if (e.key === 'a') document.querySelector(`[data-approve="${list[sel]?.id}"]`)?.click()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [list, sel])
  useEffect(() => { document.querySelector(`[data-case="${list[sel]?.id}"]`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }) }, [sel])

  return (
    <>
      <SubNav title="Approvals" />
      <Hero title="Approval inbox" subtitle={`${list.length} waiting. Signed in as ${user.role}: the server checks every approval against your role and the safety gate.`} />
      <Page>
        <p className="mb-4 hidden text-center text-sm text-mute sm:block">Keyboard: <span className="kbd">J</span> / <span className="kbd">K</span> to move, <span className="kbd">A</span> to approve.</p>
        <ErrorNote error={error} />
        {loading && !data ? <Loading /> : !list.length ? <Empty title="You are all caught up">Nothing needs a decision right now.</Empty> : (
          <div className="mx-auto flex max-w-3xl flex-col gap-4">
            {list.map((c, i) => <ReviewCard key={c.id} id={c.id} selected={i === sel} onSelect={() => setSel(i)} />)}
          </div>
        )}
      </Page>
    </>
  )
}
