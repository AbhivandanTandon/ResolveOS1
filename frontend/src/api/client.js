const TOKEN_KEY = 'ros-token'

export function getToken() {
  try { return localStorage.getItem(TOKEN_KEY) } catch { return null }
}
export function setToken(t) {
  try { t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY) } catch { /* private mode */ }
}

export class ApiError extends Error {
  constructor(status, code, message, detail) {
    super(message)
    this.status = status
    this.code = code
    this.detail = detail
  }
}

export async function api(path, { method = 'GET', body } = {}) {
  const headers = { Accept: 'application/json' }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  let res
  try {
    res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) })
  } catch {
    throw new ApiError(0, 'NETWORK', 'Cannot reach the ResolveOS API. Is the backend running on port 8000?')
  }
  const data = res.status === 204 ? null : await res.json().catch(() => null)
  if (!res.ok) {
    const e = data?.error || {}
    if (res.status === 401) window.dispatchEvent(new Event('ros:unauthorized'))
    throw new ApiError(res.status, e.code || 'ERROR', e.message || `Request failed (${res.status})`, e)
  }
  return data
}

/** Download an authenticated file (e.g. an audit export) without putting the token in a URL. */
export async function download(path, filename) {
  const res = await fetch(path, { headers: { Authorization: `Bearer ${getToken()}` } })
  if (!res.ok) {
    const e = (await res.json().catch(() => null))?.error || {}
    throw new ApiError(res.status, e.code || 'ERROR', e.message || `Download failed (${res.status})`, e)
  }
  const url = URL.createObjectURL(await res.blob())
  const a = Object.assign(document.createElement('a'), { href: url, download: filename })
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
