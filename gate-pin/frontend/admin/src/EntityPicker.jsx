import React, { useMemo, useState } from 'react'
import { Pill, input } from './ui.jsx'

export default function EntityPicker({ entities, selected, onChange }) {
  const [q, setQ] = useState('')
  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase()
    if (!needle) return entities
    return entities.filter(
      (e) => e.name.toLowerCase().includes(needle) || e.entity_id.toLowerCase().includes(needle),
    )
  }, [entities, q])

  const toggle = (id) =>
    onChange(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id])

  return (
    <div>
      <input
        className={input}
        placeholder="Search entities…"
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />
      {selected.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mt-3">
          {selected.map((id) => (
            <button key={id} onClick={() => toggle(id)} className="text-xs">
              <Pill tone="green">{id} ✕</Pill>
            </button>
          ))}
        </div>
      )}
      <div className="mt-3 max-h-64 overflow-y-auto rounded-xl border border-zinc-800 divide-y divide-zinc-800">
        {filtered.length === 0 && <p className="p-4 text-sm text-zinc-500">Nothing matches.</p>}
        {filtered.map((e) => (
          <label
            key={e.entity_id}
            className="flex items-center gap-3 px-3 py-2.5 cursor-pointer hover:bg-zinc-800/50"
          >
            <input
              type="checkbox"
              checked={selected.includes(e.entity_id)}
              onChange={() => toggle(e.entity_id)}
              className="w-4 h-4 accent-emerald-500"
            />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm">{e.name}</span>
              <span className="block truncate text-xs text-zinc-500 font-mono">{e.entity_id}</span>
            </span>
            {e.admin_only && <Pill tone="amber">admin only</Pill>}
            {!e.actionable && !e.admin_only && <Pill>read only</Pill>}
          </label>
        ))}
      </div>
    </div>
  )
}
