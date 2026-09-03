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

/* Seconds until `target`, ticking.
 *
 * `skew` is the server's clock minus this device's, measured when the server
 * last answered. A phone with a wrong clock is common and a countdown built on
 * it is wrong by exactly that much -- which for a code that starts at 14:00
 * means someone standing at a gate watching a timer that has already passed. */
function useCountdown(target, skew = 0) {
  const read = () => target - (Math.floor(Date.now() / 1000) + skew)
  const [left, setLeft] = useState(read)
  useEffect(() => {
    setLeft(read())
    const t = setInterval(() => setLeft(read()), 1000)
    return () => clearInterval(t)
  }, [target, skew])
  return left
}

function humanise(left) {
  const d = Math.floor(left / 86400)
  const h = Math.floor((left % 86400) / 3600)
  const m = Math.floor((left % 3600) / 60)
  const s = left % 60
  if (d > 0) return `${d}d ${h}h`
  if (h > 0) return `${h}h ${m}m`
  if (m > 0) return `${m}m ${s}s`
  return `${s}s`
}

const clock = (epoch) =>
  new Date(epoch * 1000).toLocaleString(undefined, {
    weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
  })

function Countdown({ until, skew }) {
  const left = useCountdown(until, skew)
  if (left <= 0) return <span>expired</span>
  return <span>{humanise(left)} left</span>
}

/* A credential that is real but not yet in its window.
 *
 * The visitor holds something valid, so there is nothing to type and no reason
 * to show the code box -- a link-only guest has no code to give it. They are
 * shown the wait instead, and the moment it reaches zero the credential is
 * tried again on its own, so nobody has to notice and tap. */
function ScheduledScreen({ status, skew, busy, onStart, onEnterCode, brand }) {
  const left = useCountdown(status.starts_at, skew)
  const fired = useRef(false)

  useEffect(() => {
    if (left > 0 || fired.current) return
    fired.current = true
    onStart()
  }, [left, onStart])

  return (
    <main className="mx-auto max-w-md px-6 min-h-full flex flex-col justify-center py-10 text-center">
      <BrandHeader {...brand} />
      <h1 className="text-3xl font-bold">{status.label || 'Guest access'}</h1>
      <p className="mt-2 text-base" style={{ color: 'var(--gp-muted)' }}>
        This code isn&rsquo;t active yet.
      </p>

      <p className="mt-10 text-5xl font-semibold tabular-nums" style={{ color: 'var(--gp-accent)' }}>
        {left > 0 ? humanise(left) : 'Starting…'}
      </p>
      <p className="mt-2 text-sm uppercase tracking-wider" style={{ color: 'var(--gp-muted)' }}>
        {left > 0 ? 'until it starts' : busy ? 'checking' : 'starting'}
      </p>

      <div
        className="mt-10 rounded-2xl p-4 text-sm"
        style={{ background: 'var(--gp-card)', border: '1px solid var(--gp-border)' }}
      >
        <p style={{ color: 'var(--gp-muted)' }}>Active from</p>
        <p className="mt-0.5 text-base font-medium">{clock(status.starts_at)}</p>
        <p className="mt-3" style={{ color: 'var(--gp-muted)' }}>Until</p>
        <p className="mt-0.5 text-base font-medium">{clock(status.expires_at)}</p>
      </div>

      <p className="mt-6 text-sm" style={{ color: 'var(--gp-muted)' }}>
        Keep this page open — it opens by itself when the time comes.
      </p>
      <EnterCodeInstead onClick={onEnterCode} />
    </main>
  )
}

/* An expired or cancelled credential.
 *
 * Same reasoning as the wait: whoever followed the link holds something real
 * and has nothing to type, so the code box is not an answer -- it is the
 * question restated. Telling them which of the two it is, and when it was
 * good, is what lets them say something useful to whoever sent it. */
function ClosedScreen({ status, message, onEnterCode, brand }) {
  const revoked = status.outcome === 'revoked'
  return (
    <main className="mx-auto max-w-md px-6 min-h-full flex flex-col justify-center py-10 text-center">
      <BrandHeader {...brand} />
      <h1 className="text-3xl font-bold">{status.label || 'Guest access'}</h1>

      <p className="mt-8 text-2xl font-semibold" style={{ color: '#f87171' }}>
        {revoked ? 'Cancelled' : 'Expired'}
      </p>
      <p className="mt-2 text-base" style={{ color: 'var(--gp-muted)' }}>{message}</p>

      {/* A revoked grant's end time is the one it WOULD have had, so the
          server does not send it and there is nothing honest to show. */}
      {!revoked && status.expires_at && (
        <div
          className="mt-8 rounded-2xl p-4 text-sm"
          style={{ background: 'var(--gp-card)', border: '1px solid var(--gp-border)' }}
        >
          <p style={{ color: 'var(--gp-muted)' }}>Was active until</p>
          <p className="mt-0.5 text-base font-medium">{clock(status.expires_at)}</p>
        </div>
      )}

      <p className="mt-6 text-sm" style={{ color: 'var(--gp-muted)' }}>
        Ask whoever sent this for a new code.
      </p>
      <EnterCodeInstead onClick={onEnterCode} />
    </main>
  )
}

/* Always offered: a visitor may hold a PIN as well as the link they followed,
   and the takeover must never be a dead end. */
function EnterCodeInstead({ onClick }) {
  return (
    <button
      onClick={onClick}
      className="mt-8 mx-auto text-sm underline underline-offset-4"
      style={{ color: 'var(--gp-muted)' }}
    >
      Enter a code instead
    </button>
  )
}

export default function App() {
  const [phase, setPhase] = useState('entry') // entry | scheduled | closed | unlocked
  const [pin, setPin] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [grant, setGrant] = useState(null)
  const [pending, setPending] = useState(null)
  const [results, setResults] = useState({})
  const [accent, setAccent] = useState(null)
  const [hasLogo, setHasLogo] = useState(false)
  const [propertyName, setPropertyName] = useState('')
  const [status, setStatus] = useState(null)
  // The server's clock minus this device's, from the last answer it gave.
  const [skew, setSkew] = useState(0)
  // Kept only in memory, only to retry when the window opens -- it is the same
  // credential the visitor already holds, and it is never written anywhere.
  const waiting = useRef(null)
  const autoTried = useRef(false)

  useEffect(() => {
    document.documentElement.setAttribute(
      'data-theme', grant?.theme || status?.theme || 'dark',
    )
  }, [grant, status])

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

  const anchor = (serverNow) => {
    if (serverNow) setSkew(serverNow - Math.floor(Date.now() / 1000))
  }

  const submit = useCallback(async (credential) => {
    setBusy(true); setError(null)
    try {
      const data = await api.redeem(credential)
      anchor(data.now)
      setGrant(data)
      setStatus(null)
      waiting.current = null
      setPhase('unlocked')
      setPin('')
    } catch (e) {
      /* The credential resolved but cannot be used: too early, too late, or
         called off. Whoever followed a link has nothing to type, so the reason
         replaces the code box rather than sitting under it. */
      if (e.grantStatus) {
        anchor(e.grantStatus.now)
        waiting.current = e.grantStatus.outcome === 'scheduled' ? credential : null
        setStatus({ ...e.grantStatus, message: e.message })
        setPhase(e.grantStatus.outcome === 'scheduled' ? 'scheduled' : 'closed')
        setPin('')
        return
      }
      /* Nothing resolved -- a wrong code, or too many attempts. The message is
         all there is to say, and it belongs under the box they will retype in. */
      waiting.current = null
      setStatus(null)
      setPhase('entry')
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
        anchor(s.now)
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

  const brand = { logoSrc: '/api/guest/logo', hasLogo, propertyName }
  const enterCode = () => { setStatus(null); setPhase('entry'); setError(null) }

  if (phase === 'scheduled' && status) {
    return (
      <ScheduledScreen
        // Remounted on each fresh answer, so a retry that comes back "still
        // scheduled" re-arms rather than sitting at zero forever.
        key={status.now}
        status={status}
        skew={skew}
        busy={busy}
        brand={brand}
        onStart={() => waiting.current && submit(waiting.current)}
        onEnterCode={enterCode}
      />
    )
  }

  if (phase === 'closed' && status) {
    return (
      <ClosedScreen
        status={status}
        message={status.message}
        brand={brand}
        onEnterCode={enterCode}
      />
    )
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
            <Countdown until={grant.expires_at} skew={skew} />
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
