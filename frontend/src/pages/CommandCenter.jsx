import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import Icon from '../components/Icons'
import { Avatar, Empty, ErrorNote, Hero, Loading, Money, Page, Risk, RouteChip, SectionTitle, StatusText } from '../components/ui'
import { SubNav } from '../components/Nav'
import { useAuth, useToast } from '../context/AppContext'
import { useApi, useLiveEvents } from '../lib/live'
import { timeAgo } from '../lib/format'

const FILTERS = [
  ['all', 'All'],
  ['needs', 'Needs approval'],
  ['evidence', 'More evidence'],
  ['blocked', 'Blocked'],
  ['closed', 'Closed'],
]

function greeting() {
  const h = new Date().getHours()
  return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening'
}

export default function CommandCenter() {
  const { user } = useAuth()
  const toast = useToast()
  const nav = useNavigate()
  const { data: cases, error, loading } = useApi('/api/cases')
  const { data: cfg } = useApi('/api/admin/config', { match: (m) => m.type === 'config.updated' })
  const [q, setQ] = useState('')
  const [filter, setFilter] = useState('all')
  const [recent, setRecent] = useState([])
  const searchRef = useRef(null)

  useLiveEvents((m) => {
    if (m.type === 'audit' && m.case_id && ['event', 'routing', 'verification', 'invalidation', 'escalation'].includes(m.kind)) {
      setRecent((r) => [{ ...m, key: `${m.at}${m.summary}` }, ...r].slice(0, 6))
    }
  })
  useEffect(() => {
    const onKey = (e) => {
      const tag = (e.target.tagName || '').toLowerCase()
      if (e.key === '/' && !['input', 'textarea', 'select'].includes(tag)) { e.preventDefault(); searchRef.current?.focus() }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const prev = useRef(null)
  useEffect(() => {
    if (!cases) return
    if (prev.current && cases.length > prev.current) toast(`${cases.length - prev.current} new case${cases.length - prev.current > 1 ? 's' : ''} arrived`)
    prev.current = cases.length
  }, [cases?.length])

  const rows = useMemo(() => (cases || []).filter((c) => {
    const s = q.trim().toLowerCase()
    if (s && !`${c.id} ${c.merchant} ${c.issue} ${c.payment_id}`.toLowerCase().includes(s)) return false
    if (filter === 'needs') return c.status === 'awaiting_approval'
    if (filter === 'evidence') return c.route === 'more_evidence' || c.status === 'needs_evidence'
    if (filter === 'blocked') return c.route === 'hard_block'
    if (filter === 'closed') return ['resolved', 'escalated'].includes(c.status)
    return true
  }), [cases, q, filter])

  if (loading && !cases) return <Loading />
  const all = cases || []
  const open = all.filter((c) => !['resolved', 'escalated'].includes(c.status))
  const waiting = all.filter((c) => c.status === 'awaiting_approval')
  const high = open.filter((c) => (c.risk_score ?? 0) >= 75)
  const resolved = all.filter((c) => c.status === 'resolved')

  const kpis = [
    { icon: 'inbox', label: 'Open cases', value: open.length, note: 'Not yet resolved' },
    { icon: 'person', label: 'Pending approvals', value: waiting.length, note: 'A person decides these' },
    { icon: 'shield', label: 'High-risk open', value: high.length, note: 'Risk 75 or more' },
    { icon: 'check', label: 'Resolved', value: resolved.length, note: 'Verified against state' },
  ]

  return (
    <>
      <SubNav title="Command Center" links={[{ id: 'overview', label: 'Overview' }, { id: 'cases', label: 'Cases' }, { id: 'activity', label: 'Activity' }]} />
      <div id="overview" className="scroll-mt-28">
        <Hero eyebrow={`${greeting()}, ${user.name.split(' ')[0]}`}
          title={waiting.length ? `${waiting.length} payment${waiting.length > 1 ? 's need' : ' needs'} a decision` : 'Nothing is waiting on you'}
          subtitle="ResolveOS investigates every failed, pending or held payment, gathers evidence and only acts when the safety gate allows it.">
          <div className="flex flex-wrap items-center justify-center gap-3">
            <Link to="/inbox" className="btn btn-primary">Review approvals</Link>
            <Link to="/simulator" className="btn">Run a scenario</Link>
          </div>
        </Hero>
      </div>
      <Page wide>
        {cfg?.kill_switch && (
          <div role="alert" className="card mb-6 flex flex-wrap items-center justify-between gap-3 border-bad px-5 py-4">
            <span className="flex items-center gap-2 font-semibold text-bad"><Icon name="power" size={18} />Kill switch is on. No action can run until an admin turns it off.</span>
            <Link to="/admin#kill-switch" className="link">Open Admin</Link>
          </div>
        )}
        <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
          {kpis.map((k) => (
            <div key={k.label} className="card flex flex-col gap-1 p-5">
              <Icon name={k.icon} size={26} className="mb-2 text-mute" />
              <span className="text-[13.5px] text-mute">{k.label}</span>
              <b className="text-[34px] font-bold leading-none tracking-tight tabular-nums">{k.value}</b>
              <span className="text-[12.5px] text-mute">{k.note}</span>
            </div>
          ))}
        </div>

        <section className="mt-14" aria-label="Cases">
          <SectionTitle id="cases" aside={
            <label className="flex h-11 w-full max-w-sm items-center gap-2 rounded-full border border-line bg-card px-4 text-mute sm:w-80">
              <Icon name="search" size={17} />
              <input ref={searchRef} type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search cases, merchants, IDs"
                aria-label="Search cases" className="min-w-0 flex-1 bg-transparent text-[14.5px] text-ink outline-none placeholder:text-mute" />
              <span className="kbd hidden sm:inline">/</span>
            </label>
          }>Cases</SectionTitle>
          <div className="seg mb-4" role="group" aria-label="Filter cases">
            {FILTERS.map(([k, l]) => <button key={k} aria-pressed={filter === k} onClick={() => setFilter(k)}>{l}</button>)}
          </div>
          <ErrorNote error={error} />
          {!rows.length ? <Empty icon="search" title="No cases match">Try another filter, or run a scenario in the Simulator.</Empty> : (
            <>
              <div className="card hidden overflow-x-auto xl:block">
                <table className="w-full min-w-[860px] border-collapse text-sm">
                  <thead>
                    <tr className="text-left text-[12.5px] text-mute">
                      <th className="px-5 py-3 font-medium">Payment</th><th className="px-3 py-3 font-medium">Issue</th>
                      <th className="px-3 py-3 text-right font-medium">Amount</th><th className="px-3 py-3 font-medium">Risk</th>
                      <th className="px-3 py-3 font-medium">Route</th><th className="px-5 py-3 font-medium">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((c) => (
                      <tr key={c.id} tabIndex={0} onClick={() => nav(`/cases/${c.id}`)} onKeyDown={(e) => e.key === 'Enter' && nav(`/cases/${c.id}`)}
                        className="cursor-pointer border-t border-line2 hover:bg-panel/40 focus:bg-panel/40" aria-label={`Open ${c.id}`}>
                        <td className="px-5 py-3.5">
                          <div className="flex items-center gap-3"><Avatar name={c.merchant} size={36} />
                            <div><div className="font-bold">{c.merchant}</div><div className="text-[13px] text-mute">{c.id} · {timeAgo(c.created_at)}</div></div></div>
                        </td>
                        <td className="px-3 py-3.5">{c.issue}</td>
                        <td className="px-3 py-3.5 text-right"><Money minor={c.amount_minor} currency={c.currency} /></td>
                        <td className="px-3 py-3.5"><Risk score={c.risk_score} /></td>
                        <td className="px-3 py-3.5"><RouteChip route={c.route} /></td>
                        <td className="px-5 py-3.5"><StatusText status={c.status} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <ul className="grid gap-3 md:grid-cols-2 xl:hidden">
                {rows.map((c) => (
                  <li key={c.id}>
                    <Link to={`/cases/${c.id}`} className="card flex flex-col gap-3 p-4">
                      <div className="flex items-center gap-3"><Avatar name={c.merchant} size={34} />
                        <div className="min-w-0 flex-1"><div className="truncate font-bold">{c.merchant}</div><div className="text-[13px] text-mute">{c.id}</div></div>
                        <Money minor={c.amount_minor} currency={c.currency} /></div>
                      <div className="text-[14.5px]">{c.issue}</div>
                      <div className="flex flex-wrap items-center gap-3"><Risk score={c.risk_score} /><RouteChip route={c.route} /><StatusText status={c.status} /></div>
                    </Link>
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>

        <section className="mt-14" aria-label="Recent activity">
          <SectionTitle id="activity">Live activity</SectionTitle>
          <div className="card p-5">
            {!recent.length ? <p className="text-mute">Updates appear here as they happen. Try the Simulator.</p> : (
              <ul className="flex flex-col gap-3">
                {recent.map((r) => (
                  <li key={r.key} className="fade-in flex gap-4 text-sm">
                    <Link to={`/cases/${r.case_id}`} className="w-24 shrink-0 font-semibold">{r.case_id}</Link>
                    <span className="text-mute">{r.summary}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>
      </Page>
    </>
  )
}
