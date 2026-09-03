const BASE = '/api/guest'

async function call(path, options = {}) {
  const res = await fetch(BASE + path, {
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  let body = null
  try { body = await res.json() } catch { /* empty body is fine */ }
  if (!res.ok) {
    const err = new Error((body && body.detail) || 'Something went wrong.')
    err.status = res.status
    err.retryAfter = Number(res.headers.get('Retry-After') || 0)
    // A credential that RESOLVED comes back with why it cannot be used and,
    // where it helps, the window it applies to -- so the page can explain
    // rather than just refuse. Absent for a code that resolved to nothing.
    err.grantStatus = (body && body.status) || null
    throw err
  }
  return body
}

export const redeem = (credential) =>
  call('/redeem', { method: 'POST', body: JSON.stringify({ credential }) })

export const act = (entity_id, intent) =>
  call('/act', { method: 'POST', body: JSON.stringify({ entity_id, intent }) })

export const state = () => call('/state')
export const branding = () => call('/branding')
