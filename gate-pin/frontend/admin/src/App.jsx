import React, { useCallback, useEffect, useState } from 'react'
import * as api from './api.js'
import EntityPicker from './EntityPicker.jsx'
import { writeToClipboard } from './clipboard.js'
import QrCode from './QrCode.jsx'
import { Button, Card, Field, Pill, STATUS_TONE, clock, input, relative } from './ui.jsx'

const TABS = ['Mint', 'Grants', 'Presets', 'Cameras', 'Audit', 'Settings']
const DURATIONS = [
  ['15 min', 900], ['1 hour', 3600], ['4 hours', 14400], ['24 hours', 86400], ['7 days', 604800],
]
const THEMES = ['dark', 'light', 'contrast', 'warm']

function Banner({ error, onClose }) {
  if (!error) return null
  return (
    <div className="rounded-xl bg-red-500/10 border border-red-500/30 text-red-300 px-4 py-3 mb-4 flex gap-3">
      <span className="flex-1 text-sm">{error}</span>
      <button onClick={onClose} className="text-red-400">✕</button>
    </div>
  )
}

/* Shown exactly once. Nothing stores these and no endpoint can return them
   again -- there is deliberately no "show me the code again". */
function MintResult({ result, onDone }) {
  const [copied, setCopied] = useState('')

  /* navigator.clipboard exists only in a secure context. Home Assistant
     ingress is usually plain HTTP on a LAN hostname, so it is undefined here
     and the previous `navigator.clipboard?.writeText(...)` silently did
     nothing -- the button appeared to work and copied nothing. */
  const copy = async (text, what) => {
    const ok = await writeToClipboard(text)
    setCopied(ok ? what : `${what}-failed`)
    setTimeout(() => setCopied(''), ok ? 1500 : 4000)
  }
  return (
    <Card className="border-emerald-500/40">
      <div className="rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-200 px-4 py-3 text-sm mb-5">
        This is the only time these are shown. Nothing stores them — if you lose them, mint again.
      </div>
      <p className="text-sm text-zinc-400">{result.grant.label || 'Grant'} · <span className="font-mono">{result.grant.id}</span></p>
      <p className="text-sm text-zinc-500 mt-1">Until {clock(result.grant.valid_until)}</p>

      {result.pin && (
        <div className="mt-5">
          <p className="text-xs uppercase tracking-widest text-zinc-500 mb-2">PIN</p>
          <div className="flex items-center gap-3">
            <p className="font-mono text-4xl tracking-[0.3em] text-emerald-400">{result.pin}</p>
            <Button variant="ghost" onClick={() => copy(result.pin, 'pin')}>
              {copied === 'pin' ? 'Copied' : copied === 'pin-failed' ? 'Select it' : 'Copy'}
            </Button>
          </div>
        </div>
      )}

      {result.link && (
        <div className="mt-5">
          <p className="text-xs uppercase tracking-widest text-zinc-500 mb-2">Link</p>
          <div className="flex items-center gap-2">
            {/* An input rather than <code>: if copying fails the value can still
                be selected and copied by hand, which a <code> block makes
                awkward on a phone. */}
            <input
              readOnly
              value={result.link}
              onFocus={(e) => e.target.select()}
              onClick={(e) => e.target.select()}
              className="flex-1 min-w-0 rounded-lg bg-zinc-950 border border-zinc-800 px-3 py-2 text-xs font-mono text-zinc-200"
            />
            <Button variant="ghost" onClick={() => copy(result.link, 'link')}>
              {copied === 'link' ? 'Copied' : copied === 'link-failed' ? 'Select it' : 'Copy'}
            </Button>
          </div>
          {(copied === 'link-failed' || copied === 'pin-failed') && (
            <p className="mt-2 text-xs text-amber-300">
              Your browser blocks clipboard access over plain HTTP. Tap the field to
              select it, then copy.
            </p>
          )}
          <div className="mt-4 inline-block rounded-xl bg-white p-3">
            <QrCode value={result.link} size={176} alt="QR code for the guest link" />
          </div>
          <p className="mt-2 text-xs text-zinc-500">
            Hold this up for someone standing at the gate.
          </p>
        </div>
      )}

      <Button className="mt-6 w-full" onClick={onDone}>Done</Button>
    </Card>
  )
}

function MintTab({ entities, presets, onMinted, setError }) {
  const [label, setLabel] = useState('')
  const [selected, setSelected] = useState([])
  const [duration, setDuration] = useState(3600)
  const [startsIn, setStartsIn] = useState(0)
  const [theme, setTheme] = useState('dark')
  const [kinds, setKinds] = useState(['pin', 'token'])
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)

  const toggleKind = (k) =>
    setKinds(kinds.includes(k) ? kinds.filter((x) => x !== k) : [...kinds, k])

  async function submit(payload, fn) {
    setBusy(true); setError(null)
    try {
      setResult(await fn(payload))
      onMinted()
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  if (result) return <MintResult result={result} onDone={() => { setResult(null); setSelected([]); setLabel('') }} />

  return (
    <div className="space-y-4">
      {presets.length > 0 && (
        <Card>
          <p className="text-sm font-medium text-zinc-300 mb-3">Mint from a preset</p>
          <div className="flex flex-wrap gap-2">
            {presets.map((p) => (
              <Button
                key={p.id}
                variant="ghost"
                disabled={busy}
                onClick={() => submit({ preset_id: p.id, starts_in_s: 0 }, api.mintPreset)}
              >
                {p.name} · {relative(p.duration_s)}
              </Button>
            ))}
          </div>
        </Card>
      )}

      <Card>
        <Field label="Label" hint="Who it's for, in your words.">
          <input className={input} value={label} onChange={(e) => setLabel(e.target.value)} placeholder="plumber, Tuesday" />
        </Field>

        <Field label="Entities">
          <EntityPicker entities={entities} selected={selected} onChange={setSelected} />
        </Field>

        <Field label="Valid for">
          <div className="flex flex-wrap gap-2">
            {DURATIONS.map(([name, secs]) => (
              <Button key={secs} variant={duration === secs ? 'primary' : 'ghost'} onClick={() => setDuration(secs)}>
                {name}
              </Button>
            ))}
          </div>
        </Field>

        <Field label="Starts" hint="A scheduled code exists now but will not work until it starts — and says so rather than reading as invalid.">
          <select className={input} value={startsIn} onChange={(e) => setStartsIn(Number(e.target.value))}>
            <option value={0}>Immediately</option>
            <option value={3600}>In 1 hour</option>
            <option value={28800}>In 8 hours</option>
            <option value={86400}>Tomorrow</option>
          </select>
        </Field>

        <Field label="Credentials">
          <div className="flex gap-2">
            <Button variant={kinds.includes('pin') ? 'primary' : 'ghost'} onClick={() => toggleKind('pin')}>PIN</Button>
            <Button variant={kinds.includes('token') ? 'primary' : 'ghost'} onClick={() => toggleKind('token')}>Link</Button>
          </div>
        </Field>

        <Field label="Guest page theme">
          <select className={input} value={theme} onChange={(e) => setTheme(e.target.value)}>
            {THEMES.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </Field>

        <Button
          className="w-full mt-2"
          disabled={busy || !selected.length || !kinds.length}
          onClick={() => submit(
            { label, entities: selected, duration_s: duration, starts_in_s: startsIn, theme, kinds },
            api.mint,
          )}
        >
          {busy ? 'Minting…' : 'Mint credential'}
        </Button>
      </Card>
    </div>
  )
}

function GrantsTab({ data, reload, setError }) {
  const [busy, setBusy] = useState(null)
  if (!data) return <p className="text-zinc-500">Loading…</p>
  const now = data.now

  async function run(id, fn) {
    setBusy(id); setError(null)
    try { await fn() ; reload() } catch (e) { setError(e.message) } finally { setBusy(null) }
  }

  const live = data.grants.filter((g) => ['active', 'scheduled'].includes(g.status))
  const done = data.grants.filter((g) => !['active', 'scheduled'].includes(g.status))

  const row = (g) => (
    <Card key={g.id} className="mb-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-medium truncate">{g.label || 'Unlabelled'}</p>
          <p className="text-xs text-zinc-500 font-mono mt-0.5">{g.id}</p>
        </div>
        <Pill tone={STATUS_TONE[g.status]}>{g.status}</Pill>
      </div>
      <p className="text-sm text-zinc-400 mt-3 break-words">{g.entities.join(', ')}</p>
      <p className="text-sm text-zinc-500 mt-1">
        {g.status === 'scheduled'
          ? `Starts in ${relative(g.valid_from - now)} · ${clock(g.valid_from)}`
          : g.status === 'active'
            ? `${relative(g.valid_until - now)} left · until ${clock(g.valid_until)}`
            : clock(g.valid_until)}
        {' · '}{g.kinds.join(' + ') || 'no credentials'}
      </p>
      {['active', 'scheduled'].includes(g.status) && (
        <div className="flex flex-wrap gap-2 mt-4">
          {g.status === 'active' && (
            <>
              <Button variant="ghost" disabled={busy === g.id} onClick={() => run(g.id, () => api.extend(g.id, 3600))}>+1 hour</Button>
              <Button variant="ghost" disabled={busy === g.id} onClick={() => run(g.id, () => api.extend(g.id, 14400))}>+4 hours</Button>
            </>
          )}
          <Button variant="danger" disabled={busy === g.id} onClick={() => run(g.id, () => api.revoke(g.id))}>Revoke</Button>
        </div>
      )}
    </Card>
  )

  return (
    <div>
      <Card className="mb-4">
        <p className="text-sm text-zinc-400">
          Live PIN grants <span className="text-zinc-100 font-medium">{data.live_pin_grants} / {data.pin_cap}</span>
        </p>
        <p className="text-xs text-zinc-500 mt-1.5">
          PIN guessing succeeds against any live PIN, so the effective keyspace shrinks as this
          number grows. At the cap, mint link-only grants — they have no such property.
        </p>
      </Card>
      {live.length ? live.map(row) : <p className="text-zinc-500 mb-6">No live grants.</p>}
      {done.length > 0 && (
        <>
          <h3 className="text-xs uppercase tracking-widest text-zinc-500 mt-8 mb-3">Finished</h3>
          {done.slice(0, 20).map(row)}
        </>
      )}
    </div>
  )
}

function PresetsTab({ entities, presets, reload, setError }) {
  const [draft, setDraft] = useState(null)
  const blank = { name: '', entities: [], duration_s: 3600, theme: 'dark', kinds: ['pin', 'token'] }

  async function save() {
    setError(null)
    try { await api.savePreset(draft); setDraft(null); reload() } catch (e) { setError(e.message) }
  }

  return (
    <div>
      {presets.map((p) => (
        <Card key={p.id} className="mb-3">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="font-medium">{p.name}</p>
              <p className="text-sm text-zinc-400 mt-1 break-words">{p.entities.join(', ')}</p>
              <p className="text-sm text-zinc-500 mt-1">{relative(p.duration_s)} · {p.kinds.join(' + ')} · {p.theme}</p>
            </div>
          </div>
          <div className="flex gap-2 mt-4">
            <Button variant="ghost" onClick={() => setDraft(p)}>Edit</Button>
            <Button variant="danger" onClick={async () => {
              try { await api.deletePreset(p.id); reload() } catch (e) { setError(e.message) }
            }}>Delete</Button>
          </div>
        </Card>
      ))}

      {draft ? (
        <Card>
          <Field label="Name" hint="Also the Telegram command: /new plumber">
            <input className={input} value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
          </Field>
          <Field label="Entities">
            <EntityPicker entities={entities} selected={draft.entities} onChange={(v) => setDraft({ ...draft, entities: v })} />
          </Field>
          <Field label="Valid for">
            <div className="flex flex-wrap gap-2">
              {DURATIONS.map(([name, secs]) => (
                <Button key={secs} variant={draft.duration_s === secs ? 'primary' : 'ghost'} onClick={() => setDraft({ ...draft, duration_s: secs })}>{name}</Button>
              ))}
            </div>
          </Field>
          <div className="flex gap-2">
            <Button onClick={save} disabled={!draft.name || !draft.entities.length}>Save preset</Button>
            <Button variant="ghost" onClick={() => setDraft(null)}>Cancel</Button>
          </div>
        </Card>
      ) : (
        <Button onClick={() => setDraft(blank)}>New preset</Button>
      )}
    </div>
  )
}

function CamerasTab({ entities }) {
  const cameras = entities.filter((e) => e.domain === 'camera')
  const [tick, setTick] = useState(0)
  const [openId, setOpenId] = useState(null)

  useEffect(() => {
    if (!openId) return
    const t = setInterval(() => setTick((n) => n + 1), 1000)
    return () => clearInterval(t)
  }, [openId])

  if (!cameras.length) return <p className="text-zinc-500">No camera entities found.</p>

  return (
    <div>
      <Card className="mb-4">
        <p className="text-xs text-zinc-500">
          Proxied through the add-on and served only under the ingress-authenticated admin path.
          Cameras are never rendered on the public guest page.
        </p>
      </Card>
      {cameras.map((c) => (
        <Card key={c.entity_id} className="mb-3">
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <p className="font-medium truncate">{c.name}</p>
              <p className="text-xs text-zinc-500 font-mono">{c.entity_id}</p>
            </div>
            <Button variant="ghost" onClick={() => setOpenId(openId === c.entity_id ? null : c.entity_id)}>
              {openId === c.entity_id ? 'Stop' : 'Stream'}
            </Button>
          </div>
          {openId === c.entity_id && (
            <img
              alt={c.name}
              className="mt-4 w-full rounded-xl bg-zinc-950"
              src={`${api.cameraUrl(c.entity_id)}?t=${tick}`}
            />
          )}
        </Card>
      ))}
    </div>
  )
}

const EVENT_TONE = {
  act: 'green', redeem_ok: 'green', mint: 'zinc', extend: 'zinc',
  redeem_fail: 'amber', denied: 'red', act_failed: 'red', lockout: 'red', revoke: 'amber',
}

function AuditTab({ setError }) {
  const [entries, setEntries] = useState(null)
  const [event, setEvent] = useState('')

  const load = useCallback(async () => {
    try { setEntries((await api.getAudit({ event })).entries) } catch (e) { setError(e.message) }
  }, [event, setError])

  useEffect(() => { load() }, [load])

  return (
    <div>
      <select className={`${input} mb-4`} value={event} onChange={(e) => setEvent(e.target.value)}>
        <option value="">Everything</option>
        <option value="act">Actions</option>
        <option value="redeem_ok">Successful unlocks</option>
        <option value="redeem_fail">Wrong codes</option>
        <option value="denied">Refused</option>
        <option value="act_failed">Gate didn't answer</option>
        <option value="lockout">Lockouts</option>
      </select>
      {entries === null && <p className="text-zinc-500">Loading…</p>}
      {entries?.length === 0 && <p className="text-zinc-500">Nothing recorded yet.</p>}
      <div className="divide-y divide-zinc-800 rounded-2xl border border-zinc-800 overflow-hidden">
        {entries?.map((e) => (
          <div key={e.id} className="p-3.5 bg-zinc-900">
            <div className="flex items-center gap-2 flex-wrap">
              <Pill tone={EVENT_TONE[e.event] || 'zinc'}>{e.event}</Pill>
              <span className="text-xs text-zinc-500">{clock(e.ts)}</span>
              {e.kind && <span className="text-xs text-zinc-500">via {e.kind}</span>}
            </div>
            <p className="text-sm mt-1.5">
              {/* An entry with no grant is a wrong code -- by definition it
                  belongs to nobody, and those are the rows that matter most. */}
              {e.grant_label || (e.grant_id ? e.grant_id : <span className="text-zinc-500">no grant</span>)}
              {e.entity_id && <span className="text-zinc-400"> · {e.entity_id}</span>}
              {e.service && <span className="text-zinc-500"> · {e.service}</span>}
            </p>
            {(e.client_ip || e.detail) && (
              <p className="text-xs text-zinc-500 mt-1 break-words">
                {e.client_ip}{e.client_ip && e.detail ? ' · ' : ''}{e.detail}
              </p>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

function SettingsTab({ setError }) {
  const [branding, setBranding] = useState(null)
  const [health, setHealth] = useState(null)
  const [copiedOrigin, setCopiedOrigin] = useState('')

  const load = useCallback(async () => {
    try {
      setBranding(await api.getBranding())
      setHealth(await api.getHealth())
    } catch (e) { setError(e.message) }
  }, [setError])

  useEffect(() => { load() }, [load])
  if (!branding || !health) return <p className="text-zinc-500">Loading…</p>

  const bot = health.telegram || {}
  const rl = health.rate_limiter || {}

  return (
    <div className="space-y-4">
      <Card className="border-emerald-500/30">
        <h3 className="font-medium mb-1">Point your tunnel here</h3>
        <p className="text-xs text-zinc-500 mb-4">
          Supervisor assigns this hostname and it is not guessable. Use it as the
          service URL for the public hostname on your Cloudflare Tunnel.
        </p>
        <div className="flex items-center gap-2">
          <input
            readOnly
            value={health.tunnel_origin?.url || ''}
            onFocus={(e) => e.target.select()}
            onClick={(e) => e.target.select()}
            className="flex-1 min-w-0 rounded-lg bg-zinc-950 border border-zinc-800 px-3 py-2 text-sm font-mono text-emerald-300"
          />
          <Button variant="ghost" onClick={async () => {
            const ok = await writeToClipboard(health.tunnel_origin?.url || '')
            setCopiedOrigin(ok ? 'Copied' : 'Select it')
            setTimeout(() => setCopiedOrigin(''), ok ? 1500 : 4000)
          }}>
            {copiedOrigin || 'Copy'}
          </Button>
        </div>
        <p className="text-xs text-zinc-500 mt-3">
          Do not route port 8099 — that is this panel, and Home Assistant already
          protects it. Leave 8888 unmapped in Network settings so it never binds
          on the host.
        </p>
      </Card>

      <Card>
        <h3 className="font-medium mb-4">Branding</h3>
        <Field label="Accent colour">
          <div className="flex gap-3 items-center">
            <input type="color" className="w-14 h-11 rounded-lg bg-zinc-950 border border-zinc-700"
              value={branding.accent} onChange={(e) => setBranding({ ...branding, accent: e.target.value })} />
            <code className="text-sm text-zinc-400">{branding.accent}</code>
          </div>
        </Field>
        <Field label="Default theme">
          <select className={input} value={branding.default_theme}
            onChange={(e) => setBranding({ ...branding, default_theme: e.target.value })}>
            {THEMES.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </Field>
        <Field label="Logo" hint="Served by the add-on itself, never hotlinked — an outside asset request would carry a link token out in the Referer header.">
          <input type="file" accept="image/png,image/jpeg,image/svg+xml,image/webp"
            onChange={async (e) => {
              const f = e.target.files?.[0]
              if (!f) return
              try { await api.uploadLogo(f); load() } catch (err) { setError(err.message) }
            }} />
          {branding.logo && (
            <Button variant="danger" className="mt-3"
              onClick={async () => { try { await api.deleteLogo(); load() } catch (e) { setError(e.message) } }}>
              Remove logo
            </Button>
          )}
        </Field>
        <Button onClick={async () => {
          try { await api.saveBranding({ accent: branding.accent, default_theme: branding.default_theme }) }
          catch (e) { setError(e.message) }
        }}>Save branding</Button>
      </Card>

      <Card>
        <h3 className="font-medium mb-4">Health</h3>
        <div className="space-y-3 text-sm">
          <div className="flex justify-between gap-3">
            <span className="text-zinc-400">Home Assistant</span>
            <Pill tone={health.home_assistant.ok ? 'green' : 'red'}>
              {health.home_assistant.ok ? 'reachable' : 'unreachable'}
            </Pill>
          </div>
          <div className="flex justify-between gap-3">
            <span className="text-zinc-400">Telegram bot</span>
            <Pill tone={!bot.configured ? 'zinc' : bot.running ? 'green' : 'red'}>
              {!bot.configured ? 'not configured' : bot.running ? 'running' : 'stopped'}
            </Pill>
          </div>
          {bot.last_error && <p className="text-xs text-red-300">{bot.last_error}</p>}
          <div className="flex justify-between gap-3">
            <span className="text-zinc-400">PIN entry</span>
            <Pill tone={rl.locked_out ? 'red' : 'green'}>
              {rl.locked_out ? 'locked out' : 'open'}
            </Pill>
          </div>
          <p className="text-xs text-zinc-500">
            {rl.pin_failures_in_window} wrong PINs in the last hour, budget {rl.pin_failure_budget}.
            A lockout never affects link credentials.
          </p>
        </div>
      </Card>

      <Card>
        <h3 className="font-medium mb-3">Configuration</h3>
        <dl className="text-sm space-y-2">
          {Object.entries(health.options).map(([k, v]) => (
            <div key={k} className="flex justify-between gap-3">
              <dt className="text-zinc-400">{k.replace(/_/g, ' ')}</dt>
              <dd className="text-zinc-200 font-mono text-xs text-right break-all">{String(v)}</dd>
            </div>
          ))}
        </dl>
        <p className="text-xs text-zinc-500 mt-3">Change these in the add-on's own configuration screen.</p>
      </Card>
    </div>
  )
}

export default function App() {
  const [tab, setTab] = useState('Mint')
  const [entities, setEntities] = useState([])
  const [presets, setPresets] = useState([])
  const [grants, setGrants] = useState(null)
  const [error, setError] = useState(null)

  const reload = useCallback(async () => {
    try {
      const [e, p, g] = await Promise.all([api.getEntities(), api.getPresets(), api.getGrants()])
      setEntities(e.entities); setPresets(p.presets); setGrants(g)
    } catch (err) { setError(err.message) }
  }, [])

  useEffect(() => { reload() }, [reload])

  return (
    <div className="mx-auto max-w-2xl px-4 py-5">
      <header className="mb-5">
        <h1 className="text-2xl font-bold">Gate PIN</h1>
      </header>

      <nav className="flex gap-1.5 overflow-x-auto mb-5 pb-1">
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`rounded-xl px-3.5 min-h-[2.5rem] text-sm font-medium whitespace-nowrap transition ${
              tab === t ? 'bg-zinc-100 text-zinc-900' : 'bg-zinc-800 text-zinc-300'
            }`}
          >
            {t}
          </button>
        ))}
      </nav>

      <Banner error={error} onClose={() => setError(null)} />

      {tab === 'Mint' && <MintTab entities={entities} presets={presets} onMinted={reload} setError={setError} />}
      {tab === 'Grants' && <GrantsTab data={grants} reload={reload} setError={setError} />}
      {tab === 'Presets' && <PresetsTab entities={entities} presets={presets} reload={reload} setError={setError} />}
      {tab === 'Cameras' && <CamerasTab entities={entities} />}
      {tab === 'Audit' && <AuditTab setError={setError} />}
      {tab === 'Settings' && <SettingsTab setError={setError} />}
    </div>
  )
}
