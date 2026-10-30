const LOCALE = { USD: 'en-US', EUR: 'en-IE', GBP: 'en-GB', INR: 'en-IN' }

export function money(minor, currency) {
  try {
    return new Intl.NumberFormat(LOCALE[currency] || 'en-US', { style: 'currency', currency }).format(minor / 100)
  } catch {
    return `${currency} ${(minor / 100).toFixed(2)}`
  }
}

export const parseUtc = (s) => (s ? new Date(s) : null)

export function timeAgo(s, now = Date.now()) {
  const d = parseUtc(s)
  if (!d) return ''
  const sec = Math.max(0, Math.round((now - d.getTime()) / 1000))
  if (sec < 45) return 'just now'
  if (sec < 3600) return `${Math.round(sec / 60)} min ago`
  if (sec < 86400) return `${Math.round(sec / 3600)} h ago`
  return d.toLocaleDateString()
}

export function clock(s) {
  const d = parseUtc(s)
  return d ? d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', second: '2-digit' }) : ''
}

export function duration(sec) {
  if (sec == null) return '—'
  if (sec < 60) return `${Math.round(sec)}s`
  const m = Math.floor(sec / 60)
  return `${m}m ${Math.round(sec % 60)}s`
}

export function riskLevel(score) {
  if (score == null) return 'Unknown'
  return score < 35 ? 'Low' : score < 75 ? 'Medium' : 'High'
}

export const ROUTE = {
  auto_run: 'Auto-run',
  human_approval: 'Human approval',
  more_evidence: 'More evidence',
  hard_block: 'Hard block',
}

export const STATUS = {
  investigating: 'Investigating',
  awaiting_approval: 'Awaiting approval',
  needs_evidence: 'Needs evidence',
  blocked: 'Blocked',
  executing: 'Running',
  monitoring: 'Monitoring',
  resolved: 'Resolved',
  escalated: 'Escalated',
}

export const initials = (name) => name.split(/\s+/).map((w) => w[0]).slice(0, 2).join('').toUpperCase()

export const titleCase = (s) => (s || '').replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase())
