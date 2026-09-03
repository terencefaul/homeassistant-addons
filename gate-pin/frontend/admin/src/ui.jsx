import React from 'react'

export const Card = ({ children, className = '' }) => (
  <div className={`rounded-2xl bg-zinc-900 border border-zinc-800 p-5 ${className}`}>{children}</div>
)

export const Button = ({ variant = 'primary', className = '', ...props }) => {
  const styles = {
    primary: 'bg-emerald-500 text-zinc-950 hover:bg-emerald-400',
    ghost: 'bg-zinc-800 text-zinc-100 hover:bg-zinc-700',
    danger: 'bg-red-500/15 text-red-300 hover:bg-red-500/25 border border-red-500/30',
  }[variant]
  return (
    <button
      {...props}
      className={`rounded-xl px-4 min-h-[2.75rem] font-medium transition disabled:opacity-40 active:scale-[0.98] ${styles} ${className}`}
    />
  )
}

export const Field = ({ label, hint, children }) => (
  <label className="block mb-4">
    <span className="block text-sm font-medium text-zinc-300 mb-1.5">{label}</span>
    {children}
    {hint && <span className="block text-xs text-zinc-500 mt-1.5">{hint}</span>}
  </label>
)

export const input =
  'w-full rounded-xl bg-zinc-950 border border-zinc-700 px-3 py-2.5 text-zinc-100 outline-none focus:border-emerald-500'

export const THEMES = ['dark', 'light', 'contrast', 'warm']

/** The PIN / link choice. Shared by the Mint form and the preset editor so the
 *  two cannot drift -- a preset that mints something the Mint tab cannot is a
 *  bug nobody would think to look for. */
export const KindPicker = ({ value, onChange }) => {
  const toggle = (k) =>
    onChange(value.includes(k) ? value.filter((x) => x !== k) : [...value, k])
  return (
    <div className="flex gap-2">
      <Button variant={value.includes('pin') ? 'primary' : 'ghost'} onClick={() => toggle('pin')}>PIN</Button>
      <Button variant={value.includes('token') ? 'primary' : 'ghost'} onClick={() => toggle('token')}>Link</Button>
    </div>
  )
}

/** 'pin' and 'token' are what the API calls them; PIN and link are what the
 *  buttons, the guest page and Telegram call them. Read-only summaries use
 *  this so the panel does not speak both languages at once. */
export const kindsLabel = (kinds) =>
  kinds.map((k) => (k === 'pin' ? 'PIN' : 'link')).join(' + ')

/* Up/down rather than drag, matching the control page editor: drag is fiddly on
 * a phone and would need a library for no real gain. */
export const MoveButtons = ({ onUp, onDown, atTop, atBottom, disabled }) => (
  <div className="flex gap-1">
    <Button variant="ghost" className="px-3" disabled={disabled || atTop}
      title="Move up" onClick={onUp}>↑</Button>
    <Button variant="ghost" className="px-3" disabled={disabled || atBottom}
      title="Move down" onClick={onDown}>↓</Button>
  </div>
)

export const ThemeSelect = ({ value, onChange }) => (
  <select className={input} value={value} onChange={(e) => onChange(e.target.value)}>
    {THEMES.map((t) => <option key={t} value={t}>{t}</option>)}
  </select>
)

export const Pill = ({ tone = 'zinc', children }) => {
  const tones = {
    zinc: 'bg-zinc-800 text-zinc-300',
    green: 'bg-emerald-500/15 text-emerald-300',
    amber: 'bg-amber-500/15 text-amber-300',
    red: 'bg-red-500/15 text-red-300',
  }
  return <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${tones[tone]}`}>{children}</span>
}

export const STATUS_TONE = { active: 'green', scheduled: 'amber', expired: 'zinc', revoked: 'red' }

export function relative(seconds) {
  if (seconds <= 0) return 'now'
  const d = Math.floor(seconds / 86400)
  const h = Math.floor((seconds % 86400) / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (d) return `${d}d ${h}h`
  if (h) return `${h}h ${m}m`
  return `${m}m`
}

export const clock = (epoch) =>
  new Date(epoch * 1000).toLocaleString(undefined, {
    weekday: 'short', hour: '2-digit', minute: '2-digit', day: 'numeric', month: 'short',
  })
