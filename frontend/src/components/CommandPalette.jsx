import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Icon from './Icons'
import { PAGES } from './Nav'
import { api } from '../api/client'
import { STATUS, money, titleCase } from '../lib/format'

/** ⌘K palette: jump to a page, open a case, or find a knowledge document. */
export default function CommandPalette({ open, onClose }) {
  const nav = useNavigate()
  const input = useRef(null)
  const [q, setQ] = useState('')
  const [cases, setCases] = useState([])
  const [docs, setDocs] = useState([])
  const [sel, setSel] = useState(0)

  useEffect(() => {
    if (!open) return
    setQ('')
    setSel(0)
    api('/api/cases?limit=500').then(setCases).catch(() => setCases([]))
    setTimeout(() => input.current?.focus(), 0)
  }, [open])

  useEffect(() => {
    if (!open || q.trim().length < 2) { setDocs([]); return }
    const t = setTimeout(() => api(`/api/knowledge/search?q=${encodeURIComponent(q)}&k=4`).then(setDocs).catch(() => setDocs([])), 160)
    return () => clearTimeout(t)
  }, [q, open])

  const items = useMemo(() => {
    const s = q.trim().toLowerCase()
    const pages = PAGES.filter((p) => !s || p.label.toLowerCase().includes(s))
      .map((p) => ({ key: `p${p.to}`, group: 'Pages', icon: p.icon, title: p.label, go: p.to }))
    const cs = cases.filter((c) => !s || `${c.id} ${c.merchant} ${c.issue} ${c.payment_id}`.toLowerCase().includes(s)).slice(0, s ? 8 : 5)
      .map((c) => ({ key: c.id, group: 'Cases', icon: 'doc', title: `${c.id} · ${c.merchant}`, sub: `${c.issue} · ${money(c.amount_minor, c.currency)} · ${STATUS[c.status] || c.status}`, go: `/cases/${c.id}` }))
    const ks = docs.map((d) => ({ key: d.doc_id, group: 'Knowledge', icon: 'knowledge', title: d.title, sub: `${titleCase(d.type)} · ${d.source}`, go: `/knowledge?q=${encodeURIComponent(d.title)}` }))
    return [...pages, ...cs, ...ks]
  }, [q, cases, docs])

  useEffect(() => { setSel((v) => Math.min(v, Math.max(0, items.length - 1))) }, [items.length])

  if (!open) return null
  const go = (it) => { onClose(); nav(it.go) }
  const onKey = (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setSel((v) => Math.min(items.length - 1, v + 1)) }
    if (e.key === 'ArrowUp') { e.preventDefault(); setSel((v) => Math.max(0, v - 1)) }
    if (e.key === 'Enter' && items[sel]) { e.preventDefault(); go(items[sel]) }
    if (e.key === 'Escape') onClose()
  }
  let lastGroup = null
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center px-4 pt-[12vh]" style={{ background: 'var(--scrim)' }}
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div role="dialog" aria-modal="true" aria-label="Search" className="fade-in w-full max-w-[620px] overflow-hidden rounded-[22px] border border-line bg-card shadow-2xl">
        <div className="flex items-center gap-3 border-b border-line px-5">
          <Icon name="search" size={19} className="text-mute" />
          <input ref={input} value={q} onChange={(e) => { setQ(e.target.value); setSel(0) }} onKeyDown={onKey}
            placeholder="Search cases, knowledge and pages" aria-label="Search" role="combobox" aria-expanded="true" aria-controls="palette-list"
            aria-activedescendant={items[sel] ? `pi-${items[sel].key}` : undefined}
            className="h-14 min-w-0 flex-1 bg-transparent text-[17px] text-ink outline-none placeholder:text-mute" />
          <span className="kbd">Esc</span>
        </div>
        <ul id="palette-list" role="listbox" className="max-h-[52vh] overflow-y-auto p-2">
          {!items.length && <li className="px-4 py-8 text-center text-mute">No matches.</li>}
          {items.map((it, i) => {
            const header = it.group !== lastGroup
            lastGroup = it.group
            return (
              <li key={it.key} role="presentation">
                {header && <div className="px-3 pb-1 pt-3 text-[11px] font-semibold uppercase tracking-[.06em] text-mute">{it.group}</div>}
                <div id={`pi-${it.key}`} role="option" aria-selected={i === sel} onMouseEnter={() => setSel(i)} onClick={() => go(it)}
                  className={`flex cursor-pointer items-center gap-3 rounded-xl px-3 py-2.5 ${i === sel ? 'bg-pill' : ''}`}>
                  <Icon name={it.icon} size={18} className="shrink-0 text-mute" />
                  <div className="min-w-0 flex-1"><div className="truncate font-semibold">{it.title}</div>{it.sub && <div className="truncate text-[12.5px] text-mute">{it.sub}</div>}</div>
                  {i === sel && <Icon name="enter" size={16} className="text-mute" />}
                </div>
              </li>
            )
          })}
        </ul>
      </div>
    </div>
  )
}
