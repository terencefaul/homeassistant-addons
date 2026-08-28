import React, { useCallback, useEffect, useState } from 'react'
import * as api from './api.js'
import EntityControl from '../../shared/EntityControl.jsx'
import EntityPicker from './EntityPicker.jsx'
import { Button, Card, Field } from './ui.jsx'

const POLL_MS = 5000
const FRAME_MS = 1000

/* The owner's own control page.
 *
 * Behind ingress, which is what keeps a live camera feed off the public guest
 * origin -- the guest page deliberately never shows one. It is the first tab so
 * that installing the panel to a home screen opens straight into it.
 */
function Reorder({ ids, byId, onMove }) {
  return (
    <div className="rounded-xl border border-zinc-800 divide-y divide-zinc-800">
      {ids.map((id, i) => (
        <div key={id} className="flex items-center gap-2 px-3 py-2">
          <span className="flex-1 min-w-0 truncate text-sm">{byId[id]?.name || id}</span>
          {/* Up/down rather than drag: drag is fiddly on a phone and would need
              a library for no real gain. */}
          <Button variant="ghost" className="px-3" disabled={i === 0}
            onClick={() => onMove(i, -1)}>↑</Button>
          <Button variant="ghost" className="px-3" disabled={i === ids.length - 1}
            onClick={() => onMove(i, 1)}>↓</Button>
        </div>
      ))}
    </div>
  )
}

export default function ControlTab({ entities, setError }) {
  const [config, setConfig] = useState(null)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(null)
  const [pending, setPending] = useState(null)
  const [results, setResults] = useState({})
  const [frame, setFrame] = useState(0)
  const [expanded, setExpanded] = useState(null)

  const load = useCallback(async () => {
    try { setConfig(await api.getControl()) } catch (e) { setError(e.message) }
  }, [setError])

  useEffect(() => { load() }, [load])

  // Live state, same cadence as the guest page.
  useEffect(() => {
    if (editing) return
    const t = setInterval(load, POLL_MS)
    return () => clearInterval(t)
  }, [editing, load])

  // Snapshot polling rather than a proxied video stream: one frame a second
  // answers "who is at the gate" and survives two proxies, which MJPEG does not.
  // One timer for all cameras, so adding a second does not double the work.
  useEffect(() => {
    if (editing || !config?.cameras?.length) return
    const t = setInterval(() => setFrame((n) => n + 1), FRAME_MS)
    return () => clearInterval(t)
  }, [editing, config?.cameras?.length])

  async function act(entityId, intent) {
    setPending(`${entityId}:${intent}`)
    setResults((r) => ({ ...r, [entityId]: null }))
    try {
      await api.ownerAct(entityId, intent)
      setResults((r) => ({ ...r, [entityId]: { ok: true, message: 'Done' } }))
      await load()
    } catch (e) {
      setResults((r) => ({ ...r, [entityId]: { ok: false, message: e.message } }))
    } finally {
      setPending(null)
    }
  }

  function startEditing() {
    setDraft({
      cameras: (config?.cameras || []).map((c) => c.entity_id),
      entities: (config?.entities || []).map((e) => e.entity_id),
    })
    setEditing(true)
  }

  function move(key, index, delta) {
    const next = [...draft[key]]
    const target = index + delta
    if (target < 0 || target >= next.length) return
    ;[next[index], next[target]] = [next[target], next[index]]
    setDraft({ ...draft, [key]: next })
  }

  async function save() {
    setError(null)
    try {
      await api.saveControl({ cameras: draft.cameras, entities: draft.entities })
      setEditing(false)
      await load()
    } catch (e) { setError(e.message) }
  }

  if (!config) return <p className="text-zinc-500">Loading…</p>

  if (editing) {
    const cameras = entities.filter((e) => e.domain === 'camera')
    const byId = Object.fromEntries(entities.map((e) => [e.entity_id, e]))
    return (
      <div className="space-y-4">
        <Card>
          <Field label="Cameras" hint="Shown above the controls, in this order. Admin only — never on the guest page.">
            <EntityPicker
              entities={cameras}
              selected={draft.cameras}
              onChange={(v) => setDraft({ ...draft, cameras: v })}
            />
          </Field>

          {draft.cameras.length > 1 && (
            <Field label="Camera order">
              <Reorder
                ids={draft.cameras}
                byId={byId}
                onMove={(i, d) => move('cameras', i, d)}
              />
            </Field>
          )}

          <Field label="Controls" hint="Tick to include. Order them below.">
            <EntityPicker
              entities={entities.filter((e) => e.actionable)}
              selected={draft.entities}
              onChange={(v) => setDraft({ ...draft, entities: v })}
            />
          </Field>

          {draft.entities.length > 1 && (
            <Field label="Control order" hint="The one you use most goes first.">
              <Reorder
                ids={draft.entities}
                byId={byId}
                onMove={(i, d) => move('entities', i, d)}
              />
            </Field>
          )}

          <div className="flex gap-2">
            <Button onClick={save}>Save</Button>
            <Button variant="ghost" onClick={() => setEditing(false)}>Cancel</Button>
          </div>
        </Card>
      </div>
    )
  }

  if (!config.entities.length && !config.cameras.length) {
    return (
      <Card>
        <p className="text-zinc-300 font-medium">Nothing set up yet</p>
        <p className="text-sm text-zinc-500 mt-2">
          Choose a camera and the controls you want on this page. It is yours only —
          it is not what a guest sees.
        </p>
        <Button className="mt-4" onClick={startEditing}>Set it up</Button>
      </Card>
    )
  }

  return (
    <div>
      {config.cameras.length > 0 && (
        <div className={`mb-4 grid gap-3 ${
          config.cameras.length > 1 && !expanded ? 'grid-cols-1 sm:grid-cols-2' : 'grid-cols-1'
        }`}>
          {(expanded ? config.cameras.filter((c) => c.entity_id === expanded) : config.cameras)
            .map((cam) => (
              <figure key={cam.entity_id} className="m-0">
                {/* Tap to fill the width. With two or more cameras the grid is
                    tight on a phone, and the one you want a proper look at is
                    usually the one something is happening on. */}
                <img
                  alt={cam.name}
                  onClick={() => setExpanded(expanded ? null : cam.entity_id)}
                  className="w-full rounded-2xl bg-zinc-900 cursor-pointer"
                  src={`${api.cameraUrl(cam.entity_id)}?t=${frame}`}
                />
                <figcaption className="mt-1.5 text-xs text-zinc-500 flex items-center gap-2">
                  <span className="truncate">{cam.name}</span>
                  {cam.missing && <span className="text-amber-300">not reported by Home Assistant</span>}
                  {expanded === cam.entity_id && <span className="ml-auto">tap to show all</span>}
                </figcaption>
              </figure>
            ))}
        </div>
      )}

      {config.entities.map((e) => (
        <EntityControl
          key={e.entity_id}
          entity={e}
          onAct={act}
          pending={pending}
          result={results[e.entity_id]}
          disabled={e.missing}
        />
      ))}

      {config.entities.some((e) => e.missing) && (
        <p className="text-xs text-amber-300 mb-4">
          Greyed-out controls are entities Home Assistant no longer reports.
        </p>
      )}

      <Button variant="ghost" onClick={startEditing}>Edit this page</Button>
    </div>
  )
}
