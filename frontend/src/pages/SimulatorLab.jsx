import { useState } from 'react'
import { Link } from 'react-router-dom'
import Icon from '../components/Icons'
import { SubNav } from '../components/Nav'
import { Hero, Page, SectionTitle } from '../components/ui'
import { api } from '../api/client'
import { useToast } from '../context/AppContext'
import { useApi, useLiveEvents } from '../lib/live'
import { clock } from '../lib/format'

const ICONS = { network_timeout: 'refresh', duplicate_event: 'doc', late_success: 'bolt', sanctions_hold: 'shield', processor_cutoff: 'audit', stale_evidence: 'alert',
  conflicting_state: 'block', returned_transfer: 'arrowLeft', chargeback_no_order: 'note', issuer_decline: 'lock' }

export default function SimulatorLab() {
  const toast = useToast()
  const { data: list } = useApi('/api/simulator/scenarios', { match: () => false })
  const [feed, setFeed] = useState([])
  const [busy, setBusy] = useState(null)

  useLiveEvents((m) => {
    if (m.type === 'audit') setFeed((f) => [{ ...m, key: `${m.at}-${f.length}` }, ...f].slice(0, 80))
    if (m.type === 'simulator.error') { toast(m.message, 'error'); setBusy(null) }
    if (m.type === 'case.updated') setBusy(null)
  })

  const run = async (key) => {
    setBusy(key)
    try { await api(`/api/simulator/scenarios/${key}`, { method: 'POST', body: {} }) } catch (e) { toast(e.message, 'error'); setBusy(null) }
  }

  return (
    <>
      <SubNav title="Simulator" links={[{ id: 'scenarios', label: 'Scenarios' }, { id: 'feed', label: 'Live feed' }]} />
      <Hero title="Simulator lab" subtitle="Inject a fault and watch the agent react in real time. Every payment here is synthetic: nothing touches a real processor." />
      <Page>
        <section aria-label="Scenarios">
          <SectionTitle id="scenarios">Scenarios</SectionTitle>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {(list || []).map((s) => (
              <button key={s.key} onClick={() => run(s.key)} disabled={!!busy}
                className="card group flex flex-col items-start gap-3 p-6 text-left transition-colors hover:border-ink disabled:opacity-60">
                <Icon name={ICONS[s.key] || 'play'} size={30} className="text-mute group-hover:text-ink" />
                <span className="text-[19px] font-bold">{s.name}</span>
                <span className="text-sm text-mute">{s.description}</span>
                <span className="mt-auto pt-2 text-sm font-semibold">{busy === s.key ? <span className="pulse">Running…</span> : <span className="chev">Run</span>}</span>
              </button>
            ))}
          </div>
          <p className="mt-4 text-sm text-mute">Late success targets the newest open network-timeout case. Run “Network timeout” first, or use the button on a case page.</p>
        </section>
        <section className="mt-14" aria-label="Live feed">
          <SectionTitle id="feed" aside={<button className="link text-sm" onClick={() => setFeed([])}>Clear</button>}>Live feed</SectionTitle>
          <div className="card p-6">
            {!feed.length ? <p className="text-mute">Choose a scenario. Each step of the agent’s work streams in here over the WebSocket.</p> : (
              <ol className="flex flex-col gap-3">
                {feed.map((f) => (
                  <li key={f.key} className="fade-in flex gap-4 text-sm">
                    <span className="w-20 shrink-0 text-[12.5px] text-mute">{clock(f.at)}</span>
                    <div className="min-w-0">
                      <div className="font-semibold">{f.actor}{f.case_id && <> · <Link className="underline" to={`/cases/${f.case_id}`}>{f.case_id}</Link></>}</div>
                      <div className="text-mute">{f.summary}</div>
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </div>
        </section>
      </Page>
    </>
  )
}
