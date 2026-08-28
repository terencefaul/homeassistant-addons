import React, { useCallback, useEffect, useRef, useState } from 'react'
import * as api from './api.js'
import EntityControl from '../../shared/EntityControl.jsx'
import BrandHeader from '../../shared/BrandHeader.jsx'

const POLL_MS = 5000

/* Read a link token out of the path, then remove it from the address bar.
   The credential travelled in a URL, so it is in history, in any Referer the
   page might send, and in a screenshot of the address bar. Stripping it the
   moment it has been used is the one part of that we control. */
function takeTokenFromUrl() {
  const m = window.location.pathname.match(/^\/g\/([A-Za-z0-9_-]{16,})\/?$/)
  if (!m) return null
  window.history.replaceState(null, '', '/')
  return m[1]
}

function Countdown({ until }) {
  const [left, setLeft] = useState(() => until - Math.floor(Date.now() / 1000))
  useEffect(() => {
    const t = setInterval(() => setLeft(until - Math.floor(Date.now() / 1000)), 1000)
    return () => clearInterval(t)
  }, [until])
  if (left <= 0) return <span>expired</span>
  const h = Math.floor(left / 3600)
  const m = Math.floor((left % 3600) / 60)
  const s = left % 60
  return <span>{h > 0 ? `${h}h ${m}m` : m > 0 ? `${m}m ${s}s` : `${s}s`} left</span>
}

export default function App() {
  const [phase, setPhase] = useState('entry') // entry | unlocked
  const [pin, setPin] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [grant, setGrant] = useState(null)
  const [pending, setPending] = useState(null)
  const [results, setResults] = useState({})
  const [accent, setAccent] = useState(null)
  const [hasLogo, setHasLogo] = useState(false)
  const [propertyName, setPropertyName] = useState('')
  const autoTried = useRef(false)

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', grant?.theme || 'dark')
  }, [grant])

  useEffect(() => {
    if (accent) document.documentElement.style.setProperty('--gp-accent', accent)
  }, [accent])

  useEffect(() => {
    api.branding()
      .then((b) => {
        setAccent(b.accent)
        setHasLogo(b.has_logo)
        setPropertyName(b.property_name || '')
      })
      .catch(() => {})
  }, [])

  const submit = useCallback(async (credential) => {
    setBusy(true); setError(null)
    try {
      const data = await api.redeem(credential)
      setGrant(data)
      setPhase('unlocked')
      setPin('')
    } catch (e) {
      /* Every outcome has its own message from the server -- wrong code, not
         active yet, expired, cancelled, too many attempts. Collapsing them
         into one is what makes a fault here impossible to diagnose. */
      setError(e.retryAfter ? `${e.message} (${e.retryAfter}s)` : e.message)
    } finally {
      setBusy(false)
    }
  }, [])

  useEffect(() => {
    if (autoTried.current) return
    autoTried.current = true
    const token = takeTokenFromUrl()
    if (token) submit(token)
  }, [submit])

  useEffect(() => {
    if (phase !== 'unlocked') return
    const t = setInterval(async () => {
      try {
        const s = await api.state()
        setGrant((g) => ({ ...g, ...s }))
      } catch (e) {
        if (e.status === 401) { setPhase('entry'); setGrant(null); setError(e.message) }
      }
    }, POLL_MS)
    return () => clearInterval(t)
  }, [phase])

  async function onAct(entityId, intent) {
    const key = `${entityId}:${intent}`
    setPending(key)
    setResults((r) => ({ ...r, [entityId]: null }))
    /* An explicit timeout. The gate is exactly where the signal is worst, and
       a tap that appears to do nothing is what makes someone tap eight times. */
    const timer = setTimeout(() => {
      setResults((r) => ({ ...r, [entityId]: { ok: false, message: 'Still trying…' } }))
    }, 6000)
    try {
      await api.act(entityId, intent)
      setResults((r) => ({ ...r, [entityId]: { ok: true, message: 'Done' } }))
      const s = await api.state().catch(() => null)
      if (s) setGrant((g) => ({ ...g, ...s }))
    } catch (e) {
      if (e.status === 401) {
        setPhase('entry'); setGrant(null); setError(e.message)
      } else {
        setResults((r) => ({ ...r, [entityId]: { ok: false, message: e.message } }))
      }
    } finally {
      clearTimeout(timer)
      setPending(null)
    }
  }

  if (phase === 'unlocked' && grant) {
    return (
      <main className="mx-auto max-w-md px-4 py-6">
        <BrandHeader
          logoSrc="/api/guest/logo"
          hasLogo={hasLogo}
          propertyName={propertyName}
          compact
        />
        <header className="mb-5">
          <h1 className="text-2xl font-bold">{grant.label || 'Welcome'}</h1>
          <p className="text-sm mt-1" style={{ color: 'var(--gp-muted)' }}>
            <Countdown until={grant.expires_at} />
          </p>
        </header>
        {grant.entities?.length ? (
          grant.entities.map((e) => (
            <EntityControl
              key={e.entity_id}
              entity={e}
              onAct={onAct}
              pending={pending}
              result={results[e.entity_id]}
            />
          ))
        ) : (
          <p style={{ color: 'var(--gp-muted)' }}>Nothing to show.</p>
        )}
      </main>
    )
  }

  return (
    <main className="mx-auto max-w-md px-6 min-h-full flex flex-col justify-center py-10">
      <BrandHeader logoSrc="/api/guest/logo" hasLogo={hasLogo} propertyName={propertyName} />
      <h1 className="text-3xl font-bold text-center">Enter your code</h1>
      <form
        className="mt-8"
        onSubmit={(e) => { e.preventDefault(); if (pin.trim()) submit(pin.trim()) }}
      >
        <input
          value={pin}
          onChange={(e) => setPin(e.target.value.replace(/\D/g, ''))}
          inputMode="numeric"
          autoComplete="one-time-code"
          pattern="[0-9]*"
          placeholder="000000"
          autoFocus
          className="w-full text-center text-4xl tracking-[0.35em] font-mono rounded-2xl py-5 outline-none"
          style={{
            background: 'var(--gp-card)',
            color: 'var(--gp-fg)',
            border: '2px solid var(--gp-border)',
          }}
        />
        <button
          type="submit"
          disabled={busy || !pin.trim()}
          className="mt-4 w-full min-h-[3.75rem] rounded-2xl text-xl font-semibold disabled:opacity-50 active:scale-[0.99] transition"
          style={{ background: 'var(--gp-accent)', color: '#0b0b0d' }}
        >
          {busy ? 'Checking…' : 'Unlock'}
        </button>
      </form>
      {error && (
        <p className="mt-5 text-center text-base" style={{ color: '#f87171' }}>
          {error}
        </p>
      )}
    </main>
  )
}
