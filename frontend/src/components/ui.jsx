import { useEffect, useRef } from 'react'
import Icon from './Icons'
import { ROUTE, STATUS, initials, money, riskLevel } from '../lib/format'

export function Money({ minor, currency, className = '' }) {
  return <span className={`money ${className}`}>{money(minor, currency)}</span>
}

const RISK_DOT = { Low: 'bg-ok', Medium: 'bg-warn', High: 'bg-bad', Unknown: 'bg-btnline' }
export function Risk({ score, className = '' }) {
  const l = riskLevel(score)
  return (
    <span className={`inline-flex items-center gap-2 whitespace-nowrap text-[13.5px] font-semibold ${className}`}>
      <i className={`size-2.5 rounded-full ${RISK_DOT[l]}`} aria-hidden />
      {l}{score != null && <span className="text-mute font-medium">· {score}</span>}
    </span>
  )
}

export function RouteChip({ route }) {
  if (!route) return <span className="text-mute text-sm">—</span>
  const cls = {
    human_approval: 'border-ink',
    auto_run: 'border-btnline text-mute',
    more_evidence: 'border-btnline border-dashed',
    hard_block: 'border-bad text-bad',
  }[route]
  return <span className={`inline-block whitespace-nowrap rounded-full border-[1.5px] px-2.5 py-0.5 text-[12.5px] font-semibold ${cls}`}>{ROUTE[route]}</span>
}

export function StatusText({ status }) {
  const tone = { resolved: 'text-ok', blocked: 'text-bad', escalated: 'text-warn' }[status] || ''
  return (
    <span className={`inline-flex items-center gap-1.5 whitespace-nowrap text-sm font-medium ${tone}`}>
      {(status === 'investigating' || status === 'executing') && <i className="pulse size-1.5 rounded-full bg-ink" aria-hidden />}
      {STATUS[status] || status}
    </span>
  )
}

export function Avatar({ name, size = 38 }) {
  return (
    <span className="inline-flex shrink-0 items-center justify-center rounded-full bg-panel font-bold text-ink"
      style={{ width: size, height: size, fontSize: size * 0.34 }} aria-hidden>
      {initials(name)}
    </span>
  )
}

const GATE_ICON = { ok: ['check', 'text-ok'], warn: ['alert', 'text-warn'], block: ['block', 'text-bad'] }
export function GateChecks({ checks, compact = false }) {
  return (
    <ul className={`flex flex-col ${compact ? 'gap-1.5' : 'gap-2'}`}>
      {checks.map((c, i) => {
        const [icon, color] = GATE_ICON[c.status]
        return (
          <li key={i} className="flex items-start gap-2.5 text-sm">
            <Icon name={icon} size={17} className={`mt-0.5 shrink-0 ${color}`} />
            <span className={c.status === 'ok' ? '' : 'font-semibold'}>{c.message}</span>
          </li>
        )
      })}
    </ul>
  )
}

export function Hero({ eyebrow, title, subtitle, children }) {
  return (
    <section className="fade-in mx-auto max-w-3xl px-4 pt-14 pb-10 text-center sm:pt-20">
      {eyebrow && <div className="mb-3 text-[15px] font-semibold text-mute">{eyebrow}</div>}
      <h1 className="text-[40px] font-bold leading-[1.08] tracking-[-0.02em] text-balance sm:text-[56px]">{title}</h1>
      {subtitle && <p className="mx-auto mt-4 max-w-2xl text-[19px] leading-relaxed text-mute text-balance sm:text-[21px]">{subtitle}</p>}
      {children && <div className="mt-8">{children}</div>}
    </section>
  )
}

export function Page({ children, wide = false }) {
  return <main className={`mx-auto w-full px-4 pb-24 sm:px-6 ${wide ? 'max-w-[1280px]' : 'max-w-[1080px]'}`}>{children}</main>
}

export function SectionTitle({ children, aside, id }) {
  return (
    <div id={id} className="mb-4 flex scroll-mt-32 flex-wrap items-end justify-between gap-3">
      <h2 className="text-[24px] font-bold tracking-[-0.01em] sm:text-[28px]">{children}</h2>
      {aside}
    </div>
  )
}

export function Modal({ title, onClose, children, labelledBy = 'modal-title' }) {
  const ref = useRef(null)
  useEffect(() => {
    const prev = document.activeElement
    ref.current?.querySelector('button, textarea, input, select')?.focus()
    const onKey = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => { window.removeEventListener('keydown', onKey); prev?.focus?.() }
  }, [onClose])
  return (
    <div className="fixed inset-0 z-40 flex items-end justify-center overflow-y-auto p-0 sm:items-center sm:p-4" style={{ background: 'var(--scrim)' }}
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={ref} role="dialog" aria-modal="true" aria-labelledby={labelledBy}
        className="fade-in w-full max-w-[600px] rounded-t-[28px] border border-line bg-card p-6 pb-[calc(24px+env(safe-area-inset-bottom))] sm:rounded-[28px] sm:p-8">
        {title && <h2 id={labelledBy} className="mb-1 text-[24px] font-bold tracking-tight">{title}</h2>}
        {children}
      </div>
    </div>
  )
}

export function Empty({ icon = 'check', title, children }) {
  return (
    <div className="card flex flex-col items-center gap-2 px-6 py-14 text-center">
      <Icon name={icon} size={32} className="text-mute" />
      <div className="text-lg font-bold">{title}</div>
      {children && <div className="max-w-md text-mute">{children}</div>}
    </div>
  )
}

export function ErrorNote({ error }) {
  if (!error) return null
  return <div role="alert" className="card border-bad px-5 py-4 text-sm font-semibold text-bad">{error.message}</div>
}

export function Loading({ label = 'Loading' }) {
  return <div className="pulse py-16 text-center text-mute" role="status">{label}…</div>
}
