import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import Icon from '../components/Icons'
import { SubNav } from '../components/Nav'
import { Avatar, ErrorNote, GateChecks, Loading, Modal, Money, Page, Risk, RouteChip, SectionTitle, StatusText } from '../components/ui'
import { api } from '../api/client'
import { useAuth, useToast } from '../context/AppContext'
import { useApi } from '../lib/live'
import { ROUTE, clock, riskLevel, timeAgo, titleCase } from '../lib/format'

const REASONS = ['Too risky', 'Wrong cause', 'Evidence is stale', 'Conflicts with policy', 'Needs more information', 'Other']

const KIND_LABEL = {
  event: 'Event', triage: 'Triage', evidence: 'Evidence', retrieval: 'Knowledge', diagnosis: 'Diagnosis', risk: 'Risk',
  gate: 'Safety gate', routing: 'Routing', decision: 'Human decision', execution: 'Execution', verification: 'Verification',
  invalidation: 'Invalidated', escalation: 'Escalation', security: 'Security', note: 'Note',
}

function NoteForm({ caseId, onAdded }) {
  const toast = useToast()
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const submit = async (e) => {
    e.preventDefault()
    if (!text.trim()) return
    setBusy(true)
    try {
      const ev = await api(`/api/cases/${caseId}/notes`, { method: 'POST', body: { text } })
      setText('')
      toast(ev.data?.security_flags?.length ? 'Note added. It contains instruction-like text, so the agent treats it strictly as data.' : 'Note added to the timeline.', 'success')
      onAdded()
    } catch (err) { toast(err.message, 'error') } finally { setBusy(false) }
  }
  return (
    <form onSubmit={submit} className="mb-4 flex flex-col gap-2 sm:flex-row">
      <label className="sr-only" htmlFor="case-note">Add a note</label>
      <input id="case-note" className="field flex-1" value={text} onChange={(e) => setText(e.target.value)} maxLength={2000}
        placeholder="Add a note for the team. The agent reads it as data, never as instructions." />
      <button className="btn" disabled={busy || !text.trim()}><Icon name="note" size={16} />Add note</button>
    </form>
  )
}

function age(s) {
  if (s < 60) return `${s}s old`
  if (s < 3600) return `${Math.round(s / 60)} min old`
  return `${Math.round(s / 3600)} h old`
}

export function RejectModal({ rec, caseInfo, onClose, onDone }) {
  const toast = useToast()
  const [reason, setReason] = useState('')
  const [note, setNote] = useState('')
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  const max = caseInfo.permissions?.max_rejections ?? 3
  const n = caseInfo.case.rejection_count + 1
  const submit = async () => {
    if (!reason) { setErr({ message: 'Choose a reason first.' }); return }
    setBusy(true)
    try {
      const d = await api(`/api/cases/${caseInfo.case.id}/recommendations/${rec.id}/reject`, { method: 'POST', body: { reason, note: note || null } })
      toast(n >= max ? `Rejected. ${caseInfo.case.id} escalated to ${caseInfo.case.owner}.` : 'Rejected. A safer alternative is ready.', 'success')
      onDone(d)
    } catch (e) {
      setErr(e)
      setBusy(false)
    }
  }
  return (
    <Modal title="Reject this plan" onClose={onClose}>
      <p className="text-mute">{rec.title} · {caseInfo.case.id} · <Money minor={caseInfo.case.amount_minor} currency={caseInfo.case.currency} /></p>
      <fieldset className="mt-6">
        <legend className="mb-3 font-bold">Why are you rejecting it?</legend>
        <div className="flex flex-wrap gap-2">
          {REASONS.map((r) => (
            <button key={r} type="button" aria-pressed={reason === r} onClick={() => { setReason(r); setErr(null) }}
              className={`h-10 rounded-full border-[1.5px] px-4 text-sm font-semibold ${reason === r ? 'border-ink text-ink' : 'border-btnline text-mute hover:text-ink'}`}>{r}</button>
          ))}
        </div>
      </fieldset>
      <label className="mt-6 block">
        <span className="mb-2 block font-bold">Add detail <span className="font-normal text-mute">(optional, shared with the agent as data)</span></span>
        <textarea className="field" rows={3} value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} />
      </label>
      <div className="mt-5 rounded-2xl bg-panel px-4 py-3 text-sm">
        {n >= max ? <b>This is rejection {n} of {max}. The case goes to {caseInfo.case.owner} and the agent stops proposing.</b>
          : <>The agent proposes a safer option using your reason. Rejection {n} of {max}; the {max === 3 ? 'third' : 'last'} sends the case to its owner.</>}
      </div>
      {err && <p role="alert" className="mt-3 text-sm font-semibold text-bad">{err.message}</p>}
      <div className="mt-6 flex flex-wrap justify-end gap-3">
        <button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" onClick={submit} disabled={busy}>{busy ? 'Rejecting…' : n >= max ? 'Reject and escalate' : 'Reject and get an alternative'}</button>
      </div>
    </Modal>
  )
}

const NB_LABEL = (s) => (s || '').toLowerCase().replace(/_/g, ' ')

/** Second opinions from the trained models. Advisory: the safety gate still decides. */
function ModelSignals({ diagnosis, top }) {
  const m = diagnosis?.ml || {}
  if (!m.triage && !m.action) return null
  const agrees = m.action && top && m.action.actions?.includes(top.action_type)
  return (
    <section className="card p-6" aria-label="Model second opinions">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-[17px] font-bold">Model second opinions</h2>
        <span className="text-[12.5px] text-mute">Trained models from the ML notebook · advisory only</span>
      </div>
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        {m.triage && (
          <div className="rounded-2xl bg-panel p-4">
            <div className="eyebrow">Triage · BGE + logistic regression</div>
            <div className="mt-1 text-[17px] font-bold capitalize">{NB_LABEL(m.triage.label)} <span className="text-sm font-medium text-mute">{Math.round(m.triage.p * 100)}%</span></div>
            <ul className="mt-2 flex flex-col gap-1">
              {m.triage.top.map((t) => (
                <li key={t.label} className="flex items-center gap-2 text-[12.5px] text-mute">
                  <span className="w-36 truncate capitalize">{NB_LABEL(t.label)}</span>
                  <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-card"><i className="block h-full rounded-full bg-ink" style={{ width: `${Math.round(t.p * 100)}%` }} /></span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {m.action && (
          <div className="rounded-2xl bg-panel p-4">
            <div className="eyebrow">Next action · LightGBM</div>
            <div className="mt-1 text-[17px] font-bold capitalize">{NB_LABEL(m.action.label)} <span className="text-sm font-medium text-mute">{Math.round(m.action.p * 100)}%</span></div>
            {top && (
              <p className={`mt-2 flex items-start gap-1.5 text-[13px] ${agrees ? 'text-okfg' : 'text-warn'}`}>
                <Icon name={agrees ? 'check' : 'alert'} size={15} className="mt-0.5 shrink-0" />
                {agrees ? 'Agrees with the recommended plan.' : `Differs from the recommended plan (${NB_LABEL(top.action_type)}).`}
              </p>
            )}
          </div>
        )}
      </div>
      {m.defaults_used?.length > 0 && <p className="mt-3 text-[12px] text-mute">Inputs ResolveOS does not track ({m.defaults_used.join(', ').replace(/_/g, ' ')}) used training-set medians.</p>}
    </section>
  )
}

function PlanCard({ rec, tag, primary }) {
  return (
    <article className={`card p-6 ${primary ? 'border-2 border-ink' : ''}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="eyebrow" style={primary ? { color: 'var(--ink)' } : undefined}>{tag}</span>
        <span className="flex items-center gap-2">
          <Risk score={rec.risk_score} />
          {rec.risk_detail?.probability != null && <span className="text-[12px] text-mute" title="Calibrated probability from the LightGBM risk model">p={rec.risk_detail.probability.toFixed(2)}</span>}
        </span>
      </div>
      <h3 className={`mt-2 font-bold tracking-tight ${primary ? 'text-[22px]' : 'text-[17px]'}`}>{rec.title}</h3>
      <p className="mt-2 text-[14.5px] text-mute">{rec.description}</p>
      {rec.rationale && primary && <p className="mt-2 text-[13.5px] text-mute">Why: {rec.rationale}</p>}
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[13px] text-mute">
        <span>{rec.moves_money ? 'Can move money' : 'Moves no money'}</span>
        <span>Gate: <b className="text-ink">{ROUTE[rec.gate_decision]}</b></span>
        {rec.idempotency_key && <span>Key <code className="text-ink">{rec.idempotency_key}</code></span>}
      </div>
      {primary && <div className="mt-4 rounded-2xl bg-panel p-4"><div className="mb-2 text-sm font-bold">Safety gate</div><GateChecks checks={rec.gate_checks} /></div>}
    </article>
  )
}

export default function CaseWorkspace() {
  const { id } = useParams()
  const { user } = useAuth()
  const toast = useToast()
  const { data: d, error, loading, setData, reload } = useApi(`/api/cases/${id}`, {
    match: (m) => (m.type === 'case.updated' && m.case_id === id) || m.type === 'config.updated',
  })
  const [rejecting, setRejecting] = useState(false)
  const [busy, setBusy] = useState(false)
  const [gateErr, setGateErr] = useState(null)

  const closed = d && ['resolved', 'escalated'].includes(d.case.status)
  const top = closed ? undefined : d?.recommendations.find((r) => r.status === 'proposed')

  const approve = useCallback(async (rec) => {
    setBusy(true)
    setGateErr(null)
    try {
      const nd = await api(`/api/cases/${id}/recommendations/${rec.id}/approve`, { method: 'POST' })
      setData(nd)
      const ex = nd.executions.at(-1)
      toast(ex?.verified ? `Ran once and verified: ${nd.case.id} is ${nd.case.status}.` : `Approved. ${nd.case.id} is ${nd.case.status}.`, 'success')
    } catch (e) {
      setGateErr(e)
      toast(e.message, 'error')
      reload()
    } finally {
      setBusy(false)
    }
  }, [id])

  const refresh = async () => {
    setBusy(true)
    try { setData(await api(`/api/cases/${id}/evidence/refresh`, { method: 'POST' })); toast('Fresh evidence gathered.', 'success') } catch (e) { toast(e.message, 'error') } finally { setBusy(false) }
  }
  const restart = async () => {
    setBusy(true)
    try { setData(await api(`/api/cases/${id}/investigate`, { method: 'POST' })); toast('Investigation restarted with fresh evidence.', 'success') } catch (e) { toast(e.message, 'error') } finally { setBusy(false) }
  }
  const lateSuccess = async () => {
    try { await api('/api/simulator/scenarios/late_success', { method: 'POST', body: { case_id: id } }); toast('Late success event sent. Watch the case update live.') } catch (e) { toast(e.message, 'error') }
  }

  useEffect(() => {
    const onKey = (e) => {
      const tag = (e.target.tagName || '').toLowerCase()
      if (['input', 'textarea', 'select'].includes(tag) || e.metaKey || e.ctrlKey || e.altKey || rejecting || !top || busy) return
      if (e.key === 'a' && d?.permissions.approve && d.case.route !== 'more_evidence') approve(top)
      if (e.key === 'r' && d?.permissions.reject) setRejecting(true)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [top, d, rejecting, busy, approve])

  if (loading && !d) return <Loading label="Loading case" />
  if (error && !d) return <Page><div className="pt-10"><ErrorNote error={error} /></div></Page>
  const c = d.case
  const alts = d.recommendations.filter((r) => r !== top && r.status === 'proposed')
  const blocked = d.recommendations.filter((r) => r.status === 'blocked')
  const rejected = d.history.filter((r) => r.status === 'rejected')
  const invalidated = d.history.filter((r) => r.status === 'invalidated')
  const prevRejected = rejected.at(-1)
  const lastExec = d.executions.at(-1)
  const evidenceMode = c.route === 'more_evidence' && top?.action_type === 'REFRESH_EVIDENCE'

  let barMsg
  if (d.permissions.kill_switch) barMsg = 'The kill switch is on. Nothing can be approved or run until an admin turns it off.'
  else if (c.status === 'awaiting_approval') barMsg = 'Nothing runs until a person approves. Approved actions run once, then the real state is re-read.'
  else if (evidenceMode) barMsg = 'Evidence is stale or conflicting, so no action is suggested yet.'
  else if (c.status === 'resolved') barMsg = lastExec?.verified ? `Resolved and verified: processor ${lastExec.verification.processor_status}, ledger ${lastExec.verification.ledger_status}.` : 'Resolved.'
  else if (c.status === 'escalated') barMsg = c.route === 'hard_block' ? 'Hard block: escalated to compliance. The agent cannot act on this payment.' : `Escalated to ${c.owner}.`
  else if (c.status === 'monitoring') barMsg = 'Watching for the processor’s final status. New events re-open the investigation automatically.'
  else if (c.status === 'blocked') barMsg = 'Blocked by the safety gate.'
  else barMsg = 'Investigating…'

  return (
    <>
      <SubNav title={`${c.id} · ${c.merchant}`} links={[
        { id: 'overview', label: 'Overview' }, { id: 'plan', label: 'Plan' }, { id: 'evidence', label: 'Evidence' }, { id: 'timeline', label: 'Timeline' },
      ]} />
      <Page wide>
        <div className="pt-6"><Link to="/" className="inline-flex items-center gap-1 text-sm font-semibold text-mute hover:text-ink"><Icon name="arrowLeft" size={16} />Command Center</Link></div>

        <header id="overview" className="card mt-4 flex scroll-mt-32 flex-wrap items-center gap-5 p-6">
          <Avatar name={c.merchant} size={56} />
          <div className="min-w-0 flex-[1_1_280px]">
            <h1 className="text-[26px] font-bold leading-tight tracking-tight sm:text-[30px]">{c.issue}</h1>
            <p className="mt-1 text-[14px] text-mute">{c.merchant} · {c.id} · {c.processor} · <code>{c.payment_id}</code> · opened {timeAgo(c.created_at)}{c.simulated && ' · simulated'}</p>
          </div>
          <div className="flex flex-wrap items-center gap-4">
            <Money minor={c.amount_minor} currency={c.currency} className="text-[28px]" />
            <Risk score={c.risk_score} /><RouteChip route={c.route} /><StatusText status={c.status} />
            {!closed && d.permissions.refresh_evidence && (
              <button className="btn btn-sm" onClick={restart} disabled={busy} title="Re-read every source and diagnose again">
                <Icon name="refresh" size={15} />Re-investigate
              </button>
            )}
          </div>
        </header>

        <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
          <div className="flex min-w-0 flex-col gap-6">
            {d.diagnosis && (
              <section className="card p-6" aria-label="Diagnosis">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <h2 className="text-[20px] font-bold">What happened</h2>
                  <span className="text-sm text-mute">Confidence {Math.round(d.diagnosis.confidence * 100)}% · {d.diagnosis.model}</span>
                </div>
                <p className="mt-3 text-[18px] leading-relaxed">{d.diagnosis.summary}</p>
                <p className="mt-2 text-[15px] text-mute">{d.diagnosis.detail}</p>
                {d.diagnosis.security_flags?.length > 0 && (
                  <div className="mt-4 flex items-start gap-2 rounded-2xl bg-panel px-4 py-3 text-sm">
                    <Icon name="shield" size={18} className="mt-0.5 shrink-0 text-warn" />
                    <span><b>Prompt-injection defense:</b> {d.diagnosis.security_flags.map((f) => f.doc_id || f.source).join(', ')} contained instruction-like text and {d.diagnosis.security_flags.length > 1 ? 'were' : 'was'} kept out of the model’s reasoning.</span>
                  </div>
                )}
              </section>
            )}

            <ModelSignals diagnosis={d.diagnosis} top={top} />

            <section id="plan" className="flex scroll-mt-32 flex-col gap-4" aria-label="Plan">
              {invalidated.length > 0 && (
                <div className="card border-warn p-5">
                  <h2 className="flex items-center gap-2 text-[17px] font-bold"><Icon name="refresh" size={18} className="text-warn" />Stale actions cancelled</h2>
                  <ul className="mt-2 flex flex-col gap-1.5 text-sm">
                    {invalidated.map((r) => <li key={r.id}><s className="text-mute">{r.title}</s> — {r.status_reason}</li>)}
                  </ul>
                </div>
              )}
              {top ? <PlanCard rec={top} primary tag={c.round > 1 && rejected.length ? `New plan · round ${c.round}` : 'Recommended'} />
                : !closed && blocked.length === 0 && <div className="card p-6 text-mute">No open plan.</div>}
              {gateErr?.detail?.checks && (
                <div role="alert" className="card border-bad p-5">
                  <div className="mb-2 font-bold text-bad">{gateErr.message}</div><GateChecks checks={gateErr.detail.checks} />
                </div>
              )}
              {blocked.length > 0 && (
                <div className="card border-bad p-6">
                  <span className="eyebrow" style={{ color: 'var(--bad)' }}>Hard-blocked by the safety gate</span>
                  {blocked.map((r) => (
                    <div key={r.id} className="mt-3"><div className="font-bold">{r.title}</div><div className="mt-2"><GateChecks checks={r.gate_checks.filter((x) => x.status !== 'ok')} compact /></div></div>
                  ))}
                </div>
              )}
              {prevRejected && top && (
                <div className="card p-6">
                  <h2 className="text-[17px] font-bold">What changed from the rejected plan</h2>
                  <dl className="mt-4 grid grid-cols-1 gap-x-4 gap-y-2 text-sm sm:grid-cols-[140px_minmax(0,1fr)_minmax(0,1fr)]">
                    {[['Action', prevRejected.title, top.title], ['Can move money', prevRejected.moves_money ? 'Yes' : 'No', top.moves_money ? 'Yes' : 'No'],
                      ['Risk', `${riskLevel(prevRejected.risk_score)} · ${prevRejected.risk_score}`, `${riskLevel(top.risk_score)} · ${top.risk_score}`],
                      ['Gate route', ROUTE[prevRejected.gate_decision], ROUTE[top.gate_decision]]].map(([k, a, b]) => (
                      <div key={k} className="contents"><dt className="text-mute">{k}</dt><dd className="text-mute line-through">{a}</dd><dd className="font-semibold text-okfg">{b}</dd></div>
                    ))}
                  </dl>
                </div>
              )}
              {alts.length > 0 && (
                <div className="grid gap-4 md:grid-cols-2">
                  {alts.map((r) => (
                    <div key={r.id} className="flex flex-col">
                      <PlanCard rec={r} tag={`Option ${r.rank}${r.moves_money ? '' : ' · moves no money'}`} />
                      {d.permissions.approve && !d.permissions.kill_switch && r.gate_decision !== 'hard_block' && c.route !== 'more_evidence' && (
                        <button className="link mt-2 self-start text-sm" onClick={() => approve(r)} disabled={busy}>Approve this option instead</button>
                      )}
                    </div>
                  ))}
                </div>
              )}
              {rejected.length > 0 && (
                <div className="card p-6">
                  <h2 className="text-[17px] font-bold">Rejection memory <span className="font-normal text-mute">· {c.rejection_count} of {d.permissions.max_rejections}</span></h2>
                  <ul className="mt-3 flex flex-col gap-2 text-sm">
                    {rejected.map((r) => {
                      const dec = d.decisions.find((x) => x.recommendation_id === r.id && x.decision === 'reject')
                      return <li key={r.id}><b className="text-bad">Rejected</b> {r.title} <span className="text-mute">· {dec?.reason}{dec?.note ? `: “${dec.note}”` : ''} · {dec?.user}</span></li>
                    })}
                  </ul>
                </div>
              )}
              {d.executions.length > 0 && (
                <div className="card p-6">
                  <h2 className="text-[17px] font-bold">Execution and verification</h2>
                  <ul className="mt-3 flex flex-col gap-3 text-sm">
                    {d.executions.map((x) => (
                      <li key={x.id} className="flex flex-wrap items-start gap-x-3 gap-y-1">
                        <Icon name={x.verified ? 'check' : x.status === 'blocked' ? 'block' : 'alert'} size={18} className={x.verified ? 'text-ok' : 'text-bad'} />
                        <div className="min-w-0 flex-1">
                          <b>{titleCase(x.result.outcome || x.status)}</b> <span className="text-mute">· by {x.executed_by} · {clock(x.started_at)} · key {x.idempotency_key}</span>
                          {x.verification?.processor_status && <div className="text-mute">Re-read: processor {x.verification.processor_status}, ledger {x.verification.ledger_status}, {x.verification.captures} capture(s){x.verification.note ? ` · ${x.verification.note}` : ''}</div>}
                        </div>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {c.exception_type === 'network_timeout' && !closed && (
                <div className="rounded-2xl border border-dashed border-btnline p-4 text-sm">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <span className="text-mute">Demo: have the processor report that this capture actually succeeded.</span>
                    <button className="btn btn-sm" onClick={lateSuccess}><Icon name="bolt" size={16} />Send late success event</button>
                  </div>
                </div>
              )}
            </section>
          </div>

          <aside id="evidence" className="flex scroll-mt-32 flex-col gap-6 xl:sticky xl:top-[124px] xl:self-start" aria-label="Evidence">
            <section className="card p-6">
              <h2 className="text-[20px] font-bold">Evidence</h2>
              <ul className="mt-4 flex flex-col">
                {d.evidence.map((e) => (
                  <li key={e.id} className="flex flex-col gap-0.5 border-b border-line2 py-3 first:pt-0 last:border-0 last:pb-0">
                    <div className="flex justify-between gap-2 text-[13px] text-mute">
                      <span>{e.label}</span>
                      <span className={e.stale ? 'font-semibold text-warn' : ''}>{e.stale ? `Stale · ${age(e.age_s)}` : clock(e.observed_at)}</span>
                    </div>
                    <b className="text-[15px]">{e.summary}</b>
                    {e.source_ref && <span className="truncate text-[12px] text-mute" title={e.source_ref}>{e.source_ref}</span>}
                  </li>
                ))}
              </ul>
            </section>
            {d.diagnosis?.retrieved?.length > 0 && (
              <section className="card p-6">
                <h2 className="text-[17px] font-bold">Knowledge used</h2>
                <ul className="mt-3 flex flex-col gap-3">
                  {d.diagnosis.retrieved.map((r) => (
                    <li key={r.doc_id} className="text-sm">
                      <div className="flex justify-between gap-2 text-[12.5px] text-mute"><span>{titleCase(r.type)} · {r.doc_id}</span><span title={r.dense_score != null ? `dense ${r.dense_score} · lexical ${r.lexical_score}` : undefined}>{r.retrieval} {r.score?.toFixed(2)}</span></div>
                      <div className="font-semibold">{r.title}</div>
                      <div className="text-[12px] text-mute">{r.source_url ? <a className="underline" href={r.source_url} target="_blank" rel="noreferrer">{r.source}</a> : r.source}</div>
                    </li>
                  ))}
                </ul>
                <Link to="/knowledge" className="link chev mt-4 inline-block text-sm">Knowledge Explorer</Link>
              </section>
            )}
          </aside>
        </div>

        <section className="mt-14" aria-label="Timeline">
          <SectionTitle id="timeline" aside={<Link to={`/audit/${c.id}`} className="link chev text-sm">Replay step by step</Link>}>Timeline</SectionTitle>
          <NoteForm caseId={c.id} onAdded={reload} />
          <ol className="card relative flex flex-col gap-0 p-6">
            {d.timeline.map((t, i) => (
              <li key={t.id} className="relative flex gap-4 pb-5 last:pb-0">
                {i < d.timeline.length - 1 && <span className="absolute left-[5px] top-4 h-full w-px bg-line" aria-hidden />}
                <span className={`relative mt-1.5 size-[11px] shrink-0 rounded-full ${['invalidation', 'security'].includes(t.kind) ? 'bg-warn' : t.kind === 'note' ? 'bg-okfg' : t.kind === 'verification' ? 'bg-ok' : t.kind === 'decision' ? 'bg-ink' : 'bg-btnline'}`} aria-hidden />
                <div className="min-w-0">
                  <div className="text-[12.5px] text-mute">{clock(t.created_at)} · {KIND_LABEL[t.kind] || t.kind} · {t.actor}{t.tool ? ` · ${t.tool}` : ''}</div>
                  <div className={t.kind === 'decision' || t.kind === 'verification' ? 'font-semibold' : t.kind === 'note' ? 'italic' : ''}>{t.kind === 'note' ? `“${t.summary}”` : t.summary}</div>
                </div>
              </li>
            ))}
          </ol>
        </section>
      </Page>

      <div className="glass sticky bottom-0 z-20 border-t border-line pb-[env(safe-area-inset-bottom)]">
        <div className="mx-auto flex max-w-[1280px] flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-6">
          <span className="text-[13.5px] text-mute">{barMsg}</span>
          <div className="flex flex-wrap gap-2">
            {evidenceMode && d.permissions.refresh_evidence && !d.permissions.kill_switch && (
              <button className="btn btn-primary" onClick={refresh} disabled={busy}><Icon name="refresh" size={17} />Refresh evidence</button>
            )}
            {top && !evidenceMode && (
              <>
                <button className="btn" onClick={() => setRejecting(true)} disabled={!d.permissions.reject || busy}>Reject<span className="kbd">R</span></button>
                <button className="btn btn-primary" onClick={() => approve(top)} disabled={!d.permissions.approve || busy}
                  title={d.permissions.approve ? '' : `Your role (${user.role}) cannot approve this action`}>
                  {busy ? 'Running…' : 'Approve plan'}<span className="kbd">A</span>
                </button>
              </>
            )}
          </div>
        </div>
      </div>
      {rejecting && top && <RejectModal rec={top} caseInfo={d} onClose={() => setRejecting(false)} onDone={(nd) => { setData(nd); setRejecting(false) }} />}
    </>
  )
}
