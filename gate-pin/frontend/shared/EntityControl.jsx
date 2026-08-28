import React from 'react'

/* Shared between the guest page and the owner's control page.
 *
 * PRESENTATIONAL ONLY. No API client, no admin logic, no dependencies beyond
 * React. The guest bundle is served from a public origin and every kilobyte is
 * paid for on one bar of signal at a gate, so anything imported here reaches
 * that bundle. tests/test_frontend_build.py asserts what must never appear in
 * it -- a service worker, the QR library -- and those assertions are the guard
 * on this boundary.
 *
 * Colours come from CSS custom properties so each page keeps its own theme:
 * the guest page themes per grant, the admin panel is always dark.
 */

export const INTENT_LABELS = {
  open: 'Open', close: 'Close', stop: 'Stop',
  on: 'On', off: 'Off', unlock: 'Unlock',
  activate: 'Activate', run: 'Run', press: 'Press',
}

const ON_STATES = new Set(['on', 'open', 'opening', 'unlocked'])

export function StateDot({ state }) {
  const lit = ON_STATES.has(state)
  return (
    <span
      className="inline-block w-2 h-2 rounded-full mr-2 align-middle"
      style={{ background: lit ? 'var(--gp-accent)' : 'var(--gp-muted)' }}
    />
  )
}

export default function EntityControl({ entity, onAct, pending, result, disabled }) {
  return (
    <div
      className="rounded-2xl p-4 mb-3"
      style={{ background: 'var(--gp-card)', border: '1px solid var(--gp-border)' }}
    >
      <div className="min-w-0">
        <p className="font-medium text-lg truncate">{entity.name}</p>
        {entity.state && (
          <p className="text-sm mt-0.5" style={{ color: 'var(--gp-muted)' }}>
            <StateDot state={entity.state} />
            {entity.state}
          </p>
        )}
      </div>

      {entity.actionable && (
        <div className="mt-4 flex flex-wrap gap-2">
          {entity.intents.map((intent) => {
            const busy = pending === `${entity.entity_id}:${intent}`
            return (
              <button
                key={intent}
                disabled={disabled || !!pending}
                onClick={() => onAct(entity.entity_id, intent)}
                /* Sized for a thumb, in the lower half of the card, because
                   this is used one-handed at a gate. */
                className="flex-1 min-w-[7rem] min-h-[3.5rem] rounded-xl text-lg font-semibold
                           disabled:opacity-50 active:scale-[0.98] transition"
                style={{
                  background: busy ? 'var(--gp-muted)' : 'var(--gp-accent)',
                  color: '#0b0b0d',
                }}
              >
                {busy ? 'Working…' : INTENT_LABELS[intent] || intent}
              </button>
            )
          })}
        </div>
      )}

      {result && (
        <p className="mt-3 text-sm" style={{ color: result.ok ? 'var(--gp-accent)' : '#f87171' }}>
          {result.message}
        </p>
      )}
    </div>
  )
}
