import React, { useCallback, useEffect, useState } from 'react'
import * as api from './api.js'
import EntityControl from '../../shared/EntityControl.jsx'
import EntityPicker from './EntityPicker.jsx'
import { Button, Card, Field, input } from './ui.jsx'

const POLL_MS = 5000
const FRAME_MS = 1000

/* The owner's own control page.
 *
 * Behind ingress, which is what keeps a live camera feed off the public guest
 * origin -- the guest page deliberately never shows one. It is the first tab so
 * that installing the panel to a home screen opens straight into it.
 */
export default function ControlTab({ entities, setError }) {
  const [config, setConfig] = useState(null)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(null)
  const [pending, setPending] = useState(null)
  const [results, setResults] = useState({})
  const [frame, setFrame] = useState(0)

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
  useEffect(() => {
    if (editing || !config?.camera) return
    const t = setInterval(() => setFrame((n) => n + 1), FRAME_MS)
    return () => clearInterval(t)
  }, [editing, config?.camera])

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
      camera: config?.camera || '',
      entities: (config?.entities || []).map((e) => e.entity_id),
    })
    setEditing(true)
  }

  function move(index, delta) {
    const next = [...draft.entities]
    const target = index + delta
    if (target < 0 || target >= next.length) return
    ;[next[index], next[target]] = [next[target], next[index]]
    setDraft({ ...draft, entities: next })
  }

  async function save() {
    setError(null)
    try {
      await api.saveControl({ camera: draft.camera || null, entities: draft.entities })
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
          <Field label="Camera" hint="Shown above the controls. Admin only — never on the guest page.">
            <select
              className={input}
              value={draft.camera}
              onChange={(e) => setDraft({ ...draft, camera: e.target.value })}
            >
              <option value="">None</option>
              {cameras.map((c) => (
                <option key={c.entity_id} value={c.entity_id}>{c.name}</option>
              ))}
            </select>
          </Field>

          <Field label="Controls" hint="Tick to include. Order them below.">
            <EntityPicker
              entities={entities.filter((e) => e.actionable)}
              selected={draft.entities}
              onChange={(v) => setDraft({ ...draft, entities: v })}
            />
          </Field>

          {draft.entities.length > 1 && (
            <Field label="Order" hint="The one you use most goes first.">
              <div className="rounded-xl border border-zinc-800 divide-y divide-zinc-800">
                {draft.entities.map((eid, i) => (
                  <div key={eid} className="flex items-center gap-2 px-3 py-2">
                    <span className="flex-1 min-w-0 truncate text-sm">
                      {byId[eid]?.name || eid}
                    </span>
                    {/* Up/down rather than drag: drag is fiddly on a phone and
                        would need a library for no real gain. */}
                    <Button variant="ghost" className="px-3" disabled={i === 0}
                      onClick={() => move(i, -1)}>↑</Button>
                    <Button variant="ghost" className="px-3" disabled={i === draft.entities.length - 1}
                      onClick={() => move(i, 1)}>↓</Button>
                  </div>
                ))}
              </div>
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

  if (!config.entities.length && !config.camera) {
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
      {config.camera && (
        <img
          alt="Camera"
          className="w-full rounded-2xl bg-zinc-900 mb-4"
          src={`${api.cameraUrl(config.camera)}?t=${frame}`}
        />
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
