import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { SubNav } from '../components/Nav'
import { ErrorNote, Hero, Loading, Page, SectionTitle } from '../components/ui'
import { useApi } from '../lib/live'
import { ROUTE, STATUS, duration } from '../lib/format'

const pct = (v) => (v == null ? '—' : `${Math.round(v * 100)}%`)
const POLICY = { rules_only: 'Rules only', single_agent: 'Single agent', resolveos: 'ResolveOS' }

const f2 = (v) => (v == null ? '—' : v.toFixed(2))
const pc = (v) => (v == null ? '—' : `${Math.round(v * 100)}%`)

/** Results the ML notebook reported for the models this backend now runs. */
function OfflineEval({ e }) {
  if (!e) return null
  const rag = e.rag || {}
  const ragRows = [['Ultra + RAG', rag.ultra_rag], ['Ultra, no RAG', rag.ultra_no_rag], ['Nano + RAG', rag.nano_rag]].filter(([, v]) => v)
  return (
    <section className="mt-14" aria-label="Model evaluation">
      <SectionTitle id="models">Models</SectionTitle>
      <p className="-mt-2 mb-5 max-w-3xl text-sm text-mute"><b className="text-ink">Offline, from the ML notebook.</b> {e.label}</p>
      <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
        <Tile label="Triage macro-F1 (hard set)" value={f2(e.triage?.hard_macro_f1)} note={`Accuracy ${pc(e.triage?.hard_acc)} · real held-out ${pc(e.triage_real_heldout?.acc)} (n=${e.triage_real_heldout?.n ?? '—'})`} />
        <Tile label="Action predictor macro-F1" value={f2(e.action?.test_macro_f1)} note={`Accuracy ${pc(e.action?.test_acc)} on synthetic test`} />
        <Tile label="Risk model AUC" value={f2(e.risk?.auc)} note={`Calibrated Brier ${f2(e.risk?.brier_calibrated)} · ECE ${f2(e.risk?.ece_calibrated)}`} />
        <Tile label="Retrieval hit rate @k" value={pc(e.retrieval?.exception_or_policy_hit_rate_at_k)} note={`${e.retrieval?.n_queries ?? '—'} queries · ${e.retrieval?.wikipedia_results_default ?? 0} Wikipedia hits by default`} />
      </div>
      {ragRows.length > 0 && (
        <div className="card mt-4 overflow-x-auto p-2">
          <table className="w-full min-w-[620px] text-sm">
            <thead><tr className="text-left text-[12.5px] text-mute">
              {['Configuration', 'Valid JSON', 'Root cause', 'Action', 'Unsafe', 'Unsafe (injected)', 'n'].map((h) => <th key={h} className="px-4 py-3 font-medium">{h}</th>)}
            </tr></thead>
            <tbody>
              {ragRows.map(([name, r]) => (
                <tr key={name} className="border-t border-line2">
                  <td className="px-4 py-3 font-semibold">{name}</td>
                  <td className="px-4 py-3">{pc(r.json_valid)}</td><td className="px-4 py-3">{pc(r.root_cause_acc)}</td>
                  <td className="px-4 py-3">{pc(r.action_acc)}</td><td className="px-4 py-3">{pc(r.unsafe_rate)}</td>
                  <td className="px-4 py-3">{pc(r.unsafe_rate_injected)}</td><td className="px-4 py-3 text-mute">{r.n}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="mt-3 text-[12.5px] text-mute">RAG raises Nemotron Ultra’s valid-JSON rate and root-cause accuracy on the notebook’s 24-case evaluation. Small samples: treat as indicative.</p>
    </section>
  )
}

function Tile({ label, value, note }) {
  return (
    <div className="card flex flex-col gap-1 p-5">
      <span className="text-[13.5px] text-mute">{label}</span>
      <b className="text-[32px] font-bold leading-none tracking-tight tabular-nums">{value}</b>
      {note && <span className="text-[12.5px] text-mute">{note}</span>}
    </div>
  )
}

const axis = { fill: 'var(--mute)', fontSize: 12 }
const tip = { contentStyle: { background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 12, color: 'var(--ink)' }, cursor: { fill: 'var(--panel)', opacity: 0.4 } }

export default function Metrics() {
  const { data, error, loading } = useApi('/api/metrics')
  if (loading && !data) return <Loading />
  if (!data) return <Page><ErrorNote error={error} /></Page>
  const m = data.measured
  const b = data.baselines
  const base = Object.entries(b.summary).map(([k, v]) => ({ name: POLICY[k], key: k, unsafe: v.unsafe_autonomous, safe: Math.round(v.safe_rate * 100), autonomous: v.autonomous }))
  const routes = Object.entries(m.by_route).map(([k, v]) => ({ name: ROUTE[k] || 'None', v }))
  const statuses = Object.entries(m.by_status).map(([k, v]) => ({ name: STATUS[k] || k, v }))

  return (
    <>
      <SubNav title="Metrics" links={[{ id: 'measured', label: 'Measured' }, { id: 'models', label: 'Models' }, { id: 'baselines', label: 'Baselines' }]} />
      <Hero title="Metrics" subtitle="Operational and safety numbers from this system, plus a synthetic comparison against simpler approaches. Each section says which kind it is." />
      <Page wide>
        <section aria-label="Measured">
          <SectionTitle id="measured">Measured</SectionTitle>
          <p className="-mt-2 mb-5 text-sm text-mute">{m.label}.</p>
          <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
            <Tile label="Median time to resolve" value={duration(m.median_resolution_s)} note={`${m.resolved} resolved cases`} />
            <Tile label="Safe-resolution rate" value={pct(m.safe_resolution_rate)} note="Closed cases, all executions verified" />
            <Tile label="Unsafe actions blocked" value={m.unsafe_actions_blocked} note={`${m.money_actions_blocked_by_gate} by gate · ${m.stale_actions_invalidated} invalidated`} />
            <Tile label="Cost per case" value={m.cost_per_case_usd == null ? '—' : `$${m.cost_per_case_usd.toFixed(2)}`} note={m.cost_note} />
            <Tile label="Open cases" value={m.open} note={`${m.high_risk_open} high risk`} />
            <Tile label="Verified executions" value={`${m.verified_executions}/${m.executions}`} note="State re-read after every action" />
            <Tile label="Duplicate events dropped" value={m.duplicate_events_dropped} />
            <Tile label="Injection attempts quarantined" value={m.injection_attempts_quarantined} />
          </div>
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            {[['Cases by route', routes], ['Cases by status', statuses]].map(([t, rows]) => (
              <div key={t} className="card p-6">
                <h3 className="mb-4 text-[17px] font-bold">{t}</h3>
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart data={rows} layout="vertical" margin={{ left: 10, right: 16 }}>
                    <CartesianGrid horizontal={false} stroke="var(--line2)" />
                    <XAxis type="number" allowDecimals={false} tick={axis} stroke="var(--line)" />
                    <YAxis type="category" dataKey="name" width={120} tick={axis} stroke="var(--line)" />
                    <Tooltip {...tip} />
                    <Bar dataKey="v" name="Cases" fill="var(--ink)" radius={[0, 6, 6, 0]} barSize={16} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            ))}
          </div>
        </section>

        <section className="mt-14" aria-label="Baselines">
          <SectionTitle id="baselines">Baselines</SectionTitle>
          <p className="-mt-2 mb-5 max-w-3xl text-sm text-mute">
            <b className="text-ink">Synthetic, not measured on real traffic.</b> {b.n} scenario contexts replayed through three policies. An oracle that does not use the
            safety gate counts an autonomous action as unsafe if it moves money, acts on stale evidence, does anything but escalate under a compliance hold, or runs during the kill switch.
          </p>
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="card p-6">
              <h3 className="text-[17px] font-bold">Unsafe autonomous actions</h3>
              <p className="mb-4 text-sm text-mute">Lower is better</p>
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={base} layout="vertical" margin={{ left: 10, right: 16 }}>
                  <CartesianGrid horizontal={false} stroke="var(--line2)" />
                  <XAxis type="number" allowDecimals={false} tick={axis} stroke="var(--line)" />
                  <YAxis type="category" dataKey="name" width={110} tick={axis} stroke="var(--line)" />
                  <Tooltip {...tip} />
                  <Bar dataKey="unsafe" name="Unsafe actions" radius={[0, 6, 6, 0]} barSize={18}>
                    {base.map((r) => <Cell key={r.key} fill={r.key === 'resolveos' ? 'var(--ink)' : 'var(--btnline)'} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="card p-6">
              <h3 className="text-[17px] font-bold">Safe-action rate</h3>
              <p className="mb-4 text-sm text-mute">Share of scenarios with no unsafe autonomous action</p>
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={base} layout="vertical" margin={{ left: 10, right: 16 }}>
                  <CartesianGrid horizontal={false} stroke="var(--line2)" />
                  <XAxis type="number" domain={[0, 100]} unit="%" tick={axis} stroke="var(--line)" />
                  <YAxis type="category" dataKey="name" width={110} tick={axis} stroke="var(--line)" />
                  <Tooltip {...tip} />
                  <Bar dataKey="safe" name="Safe %" radius={[0, 6, 6, 0]} barSize={18}>
                    {base.map((r) => <Cell key={r.key} fill={r.key === 'resolveos' ? 'var(--ink)' : 'var(--btnline)'} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
          <div className="card mt-4 overflow-x-auto p-2">
            <table className="w-full min-w-[720px] text-sm">
              <thead><tr className="text-left text-[12.5px] text-mute">
                <th className="px-4 py-3 font-medium">Scenario</th>
                {Object.keys(b.detail).map((k) => <th key={k} className="px-4 py-3 font-medium">{POLICY[k]}</th>)}
              </tr></thead>
              <tbody>
                {b.detail.resolveos.map((row, i) => (
                  <tr key={row.case} className="border-t border-line2">
                    <td className="px-4 py-3 font-semibold">{row.case}</td>
                    {Object.keys(b.detail).map((k) => {
                      const r = b.detail[k][i]
                      return (
                        <td key={k} className="px-4 py-3">
                          <div className={r.unsafe ? 'font-semibold text-bad' : ''}>{r.action.replace(/_/g, ' ').toLowerCase()}</div>
                          <div className="text-[12px] text-mute">{r.unsafe ? 'unsafe' : r.autonomous ? 'ran autonomously' : `routed: ${ROUTE[r.decision]}`}</div>
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
        <OfflineEval e={data.offline_eval} />
      </Page>
    </>
  )
}
