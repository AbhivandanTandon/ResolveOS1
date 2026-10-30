import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import Icon from '../components/Icons'
import { SubNav } from '../components/Nav'
import { Empty, Hero, Loading, Money, Page, SectionTitle } from '../components/ui'
import { download } from '../api/client'
import { useAuth, useToast } from '../context/AppContext'
import { useApi } from '../lib/live'
import { clock } from '../lib/format'

const KINDS = ['', 'event', 'decision', 'gate', 'execution', 'verification', 'invalidation', 'security', 'admin', 'knowledge', 'auth', 'simulator']

function GlobalLog() {
  const [kind, setKind] = useState('')
  const { data } = useApi(`/api/audit?limit=150${kind ? `&kind=${kind}` : ''}`, { match: (m) => m.type === 'audit' })
  return (
    <section className="mt-14" aria-label="System log">
      <SectionTitle id="log" aside={
        <select className="field !w-auto !py-2" value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Filter by kind">
          {KINDS.map((k) => <option key={k} value={k}>{k ? STAGE[k] || k[0].toUpperCase() + k.slice(1) : 'All kinds'}</option>)}
        </select>}>System log</SectionTitle>
      <ol className="card divide-y divide-line2 px-2">
        {(data || []).map((s) => (
          <li key={s.id} className="flex flex-wrap gap-x-4 gap-y-0.5 px-3 py-2.5 text-sm">
            <span className="w-24 shrink-0 text-[12.5px] text-mute">{clock(s.created_at)}</span>
            <span className="w-24 shrink-0 font-semibold">{s.case_id ? <Link className="underline" to={`/audit/${s.case_id}`}>{s.case_id}</Link> : <span className="text-mute">system</span>}</span>
            <span className="w-32 shrink-0 text-mute">{STAGE[s.kind] || s.kind}</span>
            <span className="min-w-0 flex-1"><span className="text-mute">{s.actor}:</span> {s.summary}</span>
          </li>
        ))}
        {data && !data.length && <li className="px-3 py-6 text-center text-mute">No entries.</li>}
      </ol>
    </section>
  )
}

const STAGE = {
  event: 'Incoming event', triage: 'Triage', evidence: 'Evidence', retrieval: 'Knowledge retrieval', diagnosis: 'Model decision',
  risk: 'Risk score', gate: 'Safety gate', routing: 'Routing', decision: 'Human decision', execution: 'Execution',
  verification: 'Verification', invalidation: 'Invalidation', escalation: 'Escalation', security: 'Security',
  note: 'Note', admin: 'Admin', knowledge: 'Knowledge base', auth: 'Sign-in', simulator: 'Simulator',
}

export default function AuditReplay() {
  const { id } = useParams()
  const nav = useNavigate()
  const { user } = useAuth()
  const toast = useToast()
  const canExport = ['approver', 'compliance', 'admin'].includes(user.role)
  const exportAs = async (fmt, scope) => {
    try { await download(`/api/audit/export?format=${fmt}${scope ? `&case_id=${scope}` : ''}`, `resolveos-audit-${scope || 'all'}.${fmt}`) } catch (e) { toast(e.message, 'error') }
  }
  const { data: cases } = useApi('/api/cases')
  const caseId = id || cases?.[0]?.id
  const { data: steps, loading } = useApi(caseId ? `/api/cases/${caseId}/replay` : null, {
    match: (m) => m.type === 'case.updated' && m.case_id === caseId,
  })
  const [i, setI] = useState(0)
  const [playing, setPlaying] = useState(false)
  const c = cases?.find((x) => x.id === caseId)

  useEffect(() => { setI(0); setPlaying(false) }, [caseId])
  useEffect(() => {
    if (!playing || !steps) return
    if (i >= steps.length - 1) { setPlaying(false); return }
    const t = setTimeout(() => setI((v) => v + 1), 900)
    return () => clearTimeout(t)
  }, [playing, i, steps])
  const step = steps?.[Math.min(i, (steps?.length || 1) - 1)]
  const data = useMemo(() => (step ? JSON.stringify(step.data, null, 2) : ''), [step])

  return (
    <>
      <SubNav title="Audit" links={[{ id: 'replay', label: 'Replay' }, { id: 'steps', label: 'All steps' }, { id: 'log', label: 'System log' }]}
        action={canExport && <button className="btn btn-sm" onClick={() => exportAs('csv')}><Icon name="download" size={15} />Export all</button>} />
      <Hero title="Audit and replay" subtitle="Step through exactly what happened on a case: events, evidence, model output, safety-gate decisions, people, and verification." />
      <Page wide>
        <div className="mb-6 flex flex-wrap items-center gap-3">
          <label className="text-sm font-semibold" htmlFor="case-pick">Case</label>
          <select id="case-pick" className="field !w-auto max-w-full !py-2" value={caseId || ''} onChange={(e) => nav(`/audit/${e.target.value}`)}>
            {(cases || []).map((x) => <option key={x.id} value={x.id}>{x.id} · {x.merchant} · {x.issue}</option>)}
          </select>
          {c && <span className="text-sm text-mute"><Money minor={c.amount_minor} currency={c.currency} /> · <Link className="underline" to={`/cases/${c.id}`}>Open case</Link></span>}
          {c && canExport && (
            <span className="ml-auto flex gap-2">
              <button className="btn btn-sm" onClick={() => exportAs('csv', c.id)}><Icon name="download" size={15} />CSV</button>
              <button className="btn btn-sm" onClick={() => exportAs('json', c.id)}><Icon name="download" size={15} />JSON</button>
            </span>
          )}
        </div>
        {loading && !steps ? <Loading /> : !steps?.length ? <Empty icon="audit" title="No audit events yet" /> : (
          <>
            <section id="replay" className="card scroll-mt-32 p-6" aria-label="Replay">
              <div className="flex flex-wrap items-center gap-4">
                <button className="btn btn-primary btn-sm" onClick={() => { if (i >= steps.length - 1) setI(0); setPlaying((p) => !p) }}>
                  <Icon name={playing ? 'close' : 'play'} size={15} />{playing ? 'Pause' : 'Play'}
                </button>
                <label className="text-sm text-mute" htmlFor="scrub">Step {i + 1} of {steps.length}</label>
                <input id="scrub" type="range" min={0} max={steps.length - 1} value={i} onChange={(e) => { setPlaying(false); setI(+e.target.value) }}
                  className="min-w-[160px] flex-1" style={{ accentColor: 'var(--ink)' }} />
              </div>
              <div key={step.id} className="fade-in mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
                <div>
                  <div className="eyebrow">{STAGE[step.kind] || step.kind}</div>
                  <h2 className="mt-1 text-[22px] font-bold leading-snug">{step.summary}</h2>
                  <dl className="mt-4 grid grid-cols-[80px_1fr] gap-y-1.5 text-sm">
                    <dt className="text-mute">Time</dt><dd className="font-semibold">{clock(step.created_at)}</dd>
                    <dt className="text-mute">Actor</dt><dd className="font-semibold">{step.actor}</dd>
                    <dt className="text-mute">Tool</dt><dd className="font-semibold">{step.tool || '—'}</dd>
                  </dl>
                </div>
                <pre className="max-h-72 overflow-auto rounded-2xl bg-panel p-4 text-[12px] leading-relaxed">{data}</pre>
              </div>
            </section>
            <section className="mt-10" aria-label="All steps">
              <SectionTitle id="steps">All steps</SectionTitle>
              <ol className="card divide-y divide-line2 px-2">
                {steps.map((s, k) => (
                  <li key={s.id}>
                    <button onClick={() => { setPlaying(false); setI(k); document.getElementById('replay')?.scrollIntoView({ behavior: 'smooth' }) }}
                      aria-current={k === i ? 'step' : undefined}
                      className={`flex w-full gap-4 px-3 py-2.5 text-left text-sm ${k === i ? 'font-bold text-ink' : k > i ? 'text-mute' : ''}`}>
                      <span className="w-24 shrink-0 text-[12.5px] text-mute">{clock(s.created_at)}</span>
                      <span className="w-32 shrink-0 text-mute">{STAGE[s.kind] || s.kind}</span>
                      <span className="min-w-0">{s.summary}</span>
                    </button>
                  </li>
                ))}
              </ol>
            </section>
          </>
        )}
        <GlobalLog />
      </Page>
    </>
  )
}
