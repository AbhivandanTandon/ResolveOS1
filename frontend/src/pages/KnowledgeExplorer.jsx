import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import Icon from '../components/Icons'
import { SubNav } from '../components/Nav'
import { Empty, ErrorNote, Hero, Modal, Page } from '../components/ui'
import { api } from '../api/client'
import { useAuth, useToast } from '../context/AppContext'
import { titleCase } from '../lib/format'
import { useApi } from '../lib/live'

const TYPES = [['', 'All'], ['policy', 'Policies'], ['playbook', 'Playbooks'], ['runbook', 'Runbooks'], ['error_code', 'Error codes'], ['past_case', 'Past cases'], ['merchant_note', 'Merchant notes'], ['wikipedia', 'Background']]
const DOC_TYPES = TYPES.filter(([k]) => ['policy', 'runbook', 'error_code', 'past_case', 'merchant_note'].includes(k))

function AddDocument({ onClose, onAdded }) {
  const { user } = useAuth()
  const toast = useToast()
  const canTrust = ['admin', 'compliance'].includes(user.role)
  const [f, setF] = useState({ type: 'runbook', title: '', body: '', source: '', tags: '', trusted: false })
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  const set = (k) => (e) => setF({ ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })
  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    try {
      const doc = await api('/api/knowledge', { method: 'POST', body: { ...f, tags: f.tags.split(',').map((t) => t.trim()).filter(Boolean) } })
      toast(`${doc.doc_id} added${doc.trusted ? ' as trusted' : ' as untrusted'}.`, 'success')
      onAdded(doc)
    } catch (e2) { setErr(e2); setBusy(false) }
  }
  return (
    <Modal title="Add a document" onClose={onClose}>
      <p className="text-mute">New documents are searchable immediately. Text that looks like instructions is quarantined at retrieval time.</p>
      <form onSubmit={submit} className="mt-5 flex flex-col gap-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="flex flex-col gap-1.5"><span className="text-sm font-bold">Type</span>
            <select className="field" value={f.type} onChange={set('type')}>{DOC_TYPES.map(([k, l]) => <option key={k} value={k}>{l.replace(/s$/, '')}</option>)}</select></label>
          <label className="flex flex-col gap-1.5"><span className="text-sm font-bold">Source</span>
            <input className="field" required minLength={2} value={f.source} onChange={set('source')} placeholder="e.g. Ops wiki, Runbook RB-104" /></label>
        </div>
        <label className="flex flex-col gap-1.5"><span className="text-sm font-bold">Title</span>
          <input className="field" required minLength={3} value={f.title} onChange={set('title')} /></label>
        <label className="flex flex-col gap-1.5"><span className="text-sm font-bold">Body</span>
          <textarea className="field" required minLength={10} rows={5} value={f.body} onChange={set('body')} /></label>
        <label className="flex flex-col gap-1.5"><span className="text-sm font-bold">Tags <span className="font-normal text-mute">(comma-separated)</span></span>
          <input className="field" value={f.tags} onChange={set('tags')} placeholder="timeout, retry" /></label>
        <label className={`flex items-center gap-3 text-sm ${canTrust ? '' : 'opacity-60'}`}>
          <input type="checkbox" checked={f.trusted} onChange={set('trusted')} disabled={!canTrust} style={{ accentColor: 'var(--ink)' }} className="size-4" />
          Mark as trusted policy {canTrust ? '' : '(admin or compliance only)'}
        </label>
        {err && <p role="alert" className="text-sm font-semibold text-bad">{err.message}</p>}
        <div className="flex justify-end gap-3"><button type="button" className="btn" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={busy}>Add document</button></div>
      </form>
    </Modal>
  )
}

export default function KnowledgeExplorer() {
  const { user } = useAuth()
  const toast = useToast()
  const [params] = useSearchParams()
  const [q, setQ] = useState(params.get('q') || '')
  const [type, setType] = useState('')
  const [res, setRes] = useState([])
  const [error, setError] = useState(null)
  const [adding, setAdding] = useState(false)
  const [tick, setTick] = useState(0)
  const [background, setBackground] = useState(false)
  const { data: health } = useApi('/api/health', { match: () => false })

  useEffect(() => { if (params.get('q')) setQ(params.get('q')) }, [params])
  useEffect(() => {
    const t = setTimeout(() => {
      const p = new URLSearchParams({ q, k: '40' })
      if (type) p.set('type', type)
      if (background) p.set('include_background', 'true')
      api(`/api/knowledge/search?${p}`).then((r) => { setRes(r); setError(null) }).catch(setError)
    }, 180)
    return () => clearTimeout(t)
  }, [q, type, tick, background])

  const remove = async (doc) => {
    if (!window.confirm(`Remove ${doc.doc_id} from the knowledge base?`)) return
    try { await api(`/api/knowledge/${doc.doc_id}`, { method: 'DELETE' }); toast(`${doc.doc_id} removed.`); setTick((t) => t + 1) } catch (e) { toast(e.message, 'error') }
  }

  return (
    <>
      <SubNav title="Knowledge" action={<button className="btn btn-sm" onClick={() => setAdding(true)}><Icon name="plus" size={15} />Add document</button>} />
      <Hero title="Knowledge explorer" subtitle="Search the policies, runbooks, error codes and past cases the agent reads. Every result shows where it came from and how it was scored.">
        <label className="mx-auto flex h-14 max-w-xl items-center gap-3 rounded-full border border-line bg-card px-5 text-mute">
          <Icon name="search" size={20} />
          <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Try: retry after timeout, duplicate, sanctions"
            aria-label="Search knowledge" className="min-w-0 flex-1 bg-transparent text-[17px] text-ink outline-none placeholder:text-mute" />
        </label>
      </Hero>
      <Page>
        <div className="seg mb-3 justify-center" role="group" aria-label="Source type">
          {TYPES.map(([k, l]) => <button key={k} aria-pressed={type === k} onClick={() => setType(k)}>{l}</button>)}
        </div>
        <label className="mb-6 flex items-center justify-center gap-2 text-[13px] text-mute">
          <input type="checkbox" checked={background} onChange={(e) => setBackground(e.target.checked)} style={{ accentColor: 'var(--ink)' }} />
          Include background sources (Wikipedia) in “All”. The agent’s own searches never do.
        </label>
        <ErrorNote error={error} />
        {!res.length ? <Empty icon="search" title="No results">Try a broader search.</Empty> : (
          <div className="grid gap-4 md:grid-cols-2">
            {res.map((r) => (
              <article key={r.doc_id} className={`card flex flex-col gap-2 p-6 ${r.security_flags.length ? 'border-warn' : ''}`}>
                <div className="flex flex-wrap items-center justify-between gap-2 text-[12.5px] text-mute">
                  <span className="eyebrow">{titleCase(r.type)} · {r.doc_id}</span>
                  {r.score != null && (
                    <span title={r.dense_score != null ? 'Reciprocal-rank fusion of dense (BGE) and lexical (TF-IDF) rankings' : 'BM25, normalised to the best match'}>
                      {r.retrieval === 'hybrid' ? `RRF ${r.score.toFixed(2)} · dense ${r.dense_score.toFixed(2)} · lexical ${r.lexical_score.toFixed(2)}` : `BM25 ${r.score.toFixed(2)}`}
                    </span>
                  )}
                </div>
                <h3 className="text-[18px] font-bold leading-snug">{r.title}</h3>
                <p className="text-[14.5px] text-mute">{r.body}</p>
                <div className="mt-auto flex flex-wrap items-center gap-2 pt-2 text-[12.5px]">
                  <span className="text-mute">Source: {r.source_url ? <a className="underline" href={r.source_url} target="_blank" rel="noreferrer">{r.source}</a> : r.source}</span>
                  {r.retrieval === 'hybrid' && <span className="rounded-full border border-line px-2 py-0.5 font-semibold text-mute">Notebook KB</span>}
                  {!r.trusted && <span className="rounded-full border border-btnline px-2 py-0.5 font-semibold">Untrusted</span>}
                  {r.security_flags.length > 0 && <span className="inline-flex items-center gap-1 rounded-full border border-warn px-2 py-0.5 font-semibold text-warn"><Icon name="shield" size={13} />Quarantined: instruction-like text</span>}
                  {user.role === 'admin' && <button className="ml-auto inline-flex items-center gap-1 font-semibold text-mute hover:text-bad" onClick={() => remove(r)} aria-label={`Remove ${r.doc_id}`}><Icon name="trash" size={14} />Remove</button>}
                </div>
              </article>
            ))}
          </div>
        )}
        <p className="mt-6 text-center text-[13px] text-mute">
          {health?.ml?.ready
            ? `Searching ${health.ml.kb_chunks.toLocaleString()} notebook chunks with BGE + TF-IDF (reciprocal-rank fusion), fused with ResolveOS documents (BM25).`
            : 'Notebook knowledge base not loaded yet: searching ResolveOS documents with BM25 only.'}
        </p>
      </Page>
      {adding && <AddDocument onClose={() => setAdding(false)} onAdded={() => { setAdding(false); setTick((t) => t + 1) }} />}
    </>
  )
}
