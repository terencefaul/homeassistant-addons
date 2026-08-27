/* Home Assistant ingress serves this panel under /api/hassio_ingress/<token>/,
   so every request must be RELATIVE. An absolute '/api/admin/...' would leave
   the ingress path and hit Home Assistant itself. */
const url = (path) => new URL(path.replace(/^\//, ''), document.baseURI).toString()

async function call(path, options = {}) {
  const res = await fetch(url(path), {
    credentials: 'same-origin',
    headers: options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' },
    ...options,
  })
  let body = null
  try { body = await res.json() } catch { /* some endpoints return no body */ }
  if (!res.ok) {
    const err = new Error((body && body.detail) || `Request failed (${res.status})`)
    err.status = res.status
    throw err
  }
  return body
}

const j = (method, path, payload) =>
  call(path, { method, body: payload === undefined ? undefined : JSON.stringify(payload) })

export const cameraUrl = (entityId) => url(`api/admin/camera/${entityId}/snapshot`)

export const getEntities = () => call('api/admin/entities')
export const getGrants = () => call('api/admin/grants')
export const mint = (payload) => j('POST', 'api/admin/mint', payload)
export const mintPreset = (payload) => j('POST', 'api/admin/mint-preset', payload)
export const revoke = (id) => j('POST', `api/admin/grants/${id}/revoke`)
export const extend = (id, additional_s) => j('POST', `api/admin/grants/${id}/extend`, { additional_s })
export const getPresets = () => call('api/admin/presets')
export const savePreset = (payload) => j('POST', 'api/admin/presets', payload)
export const deletePreset = (id) => j('DELETE', `api/admin/presets/${id}`)
export const getAudit = (params = {}) => {
  const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v))
  return call(`api/admin/audit?${q}`)
}
export const getBranding = () => call('api/admin/branding')
export const saveBranding = (payload) => j('POST', 'api/admin/branding', payload)
export const uploadLogo = (file) => {
  const fd = new FormData()
  fd.append('file', file)
  return call('api/admin/branding/logo', { method: 'POST', body: fd })
}
export const deleteLogo = () => j('DELETE', 'api/admin/branding/logo')
export const getHealth = () => call('api/admin/health')
