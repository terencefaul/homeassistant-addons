import React, { useCallback, useEffect, useState } from 'react'
import * as api from './api.js'
import EntityControl from '../../shared/EntityControl.jsx'
import { Button, Card, Field, Pill, input } from './ui.jsx'

const POLL_MS = 5000
const FRAME_MS = 1000

/* The owner's own control page.
 *
 * Behind ingress, which is what keeps a live camera feed off the public guest
 * origin -- the guest page deliberately never shows one. It is the first tab so
 * that installing the panel to a home screen opens straight into it.
 *
 * The page is ONE ordered list of blocks rather than cameras-then-controls, so
 * a camera can sit directly above the gate it looks at. Consecutive cameras
 * still group into a grid, so "two cameras then two gates" looks the way it did
 * before without being the only arrangement available.
 */

function groupRuns(items) {
  const runs = []
  for (const item of items) {
    const last = runs[runs.length - 1]
    if (last && last.type === 'camera' && item.type === 'camera') last.items.push(item)
    else runs.push({ type: item.type, items: [item] })
  }
  return runs
}

function CameraRun({ run, frame, expanded, onExpand }) {
  const shown = expanded ? run.items.filter((c) => c.entity_id === expanded) : run.items
  const grid = run.items.length > 1 && !expanded
  return (
    <div className={`mb-3 grid gap-3 ${grid ? 'grid-cols-1 sm:grid-cols-2' : 'grid-cols-1'}`}>
      {shown.map((cam) => (
        <figure key={cam.entity_id} className="m-0">
          {/* Tap to fill the width. On a phone the grid is tight, and the one
              worth a proper look is usually the one something is happening on. */}
          <img
            alt={cam.name}
            onClick={() => onExpand(expanded ? null : cam.entity_id)}
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
  )
}

function Editor({ draft, setDraft, entities, onSave, onCancel }) {
  const cameras = entities.filter((e) => e.domain === 'camera')
  const controls = entities.filter((e) => e.actionable)
  const chosen = new Set(draft.map((i) => `${i.type}:${i.entity_id}`))

  const add = (type, entity_id) => setDraft([...draft, { type, entity_id }])
  const remove = (index) => setDraft(draft.filter((_, i) => i !== index))
  const move = (index, delta) => {
    const next = [...draft]
    const to = index + delta
    if (to < 0 || to >= next.length) return
    ;[next[index], next[to]] = [next[to], next[index]]
    setDraft(next)
  }

  const byId = Object.fromEntries(entities.map((e) => [e.entity_id, e]))
  const label = (item) => byId[item.entity_id]?.name || item.entity_id

  return (
    <Card>
      <Field label="Your page, top to bottom" hint="Put a camera directly above the gate it looks at.">
        {draft.length === 0 ? (
          <p className="text-sm text-zinc-500">Nothing yet. Add a camera or a control below.</p>
        ) : (
          <div className="rounded-xl border border-zinc-800 divide-y divide-zinc-800">
            {draft.map((item, i) => (
              <div key={`${item.type}:${item.entity_id}:${i}`} className="flex items-center gap-2 px-3 py-2">
                <Pill tone={item.type === 'camera' ? 'amber' : 'green'}>
                  {item.type === 'camera' ? 'camera' : 'control'}
                </Pill>
                <span className="flex-1 min-w-0 truncate text-sm">{label(item)}</span>
                {/* Up/down rather than drag: drag is fiddly on a phone and would
                    need a library for no real gain. */}
                <Button variant="ghost" className="px-3" disabled={i === 0}
                  onClick={() => move(i, -1)}>↑</Button>
                <Button variant="ghost" className="px-3" disabled={i === draft.length - 1}
                  onClick={() => move(i, 1)}>↓</Button>
                <Button variant="danger" className="px-3" onClick={() => remove(i)}>✕</Button>
              </div>
            ))}
          </div>
        )}
      </Field>

      <Field label="Add a camera">
        <select className={input} value=""
          onChange={(e) => e.target.value && add('camera', e.target.value)}>
          <option value="">Choose…</option>
          {cameras.map((c) => (
            <option key={c.entity_id} value={c.entity_id}
              disabled={chosen.has(`camera:${c.entity_id}`)}>
              {c.name}{chosen.has(`camera:${c.entity_id}`) ? ' — already added' : ''}
            </option>
          ))}
        </select>
      </Field>

      <Field label="Add a control">
        <select className={input} value=""
          onChange={(e) => e.target.value && add('control', e.target.value)}>
          <option value="">Choose…</option>
          {controls.map((c) => (
            <option key={c.entity_id} value={c.entity_id}
              disabled={chosen.has(`control:${c.entity_id}`)}>
              {c.name}{chosen.has(`control:${c.entity_id}`) ? ' — already added' : ''}
            </option>
          ))}
        </select>
      </Field>

      <div className="flex gap-2">
        <Button onClick={onSave}>Save</Button>
        <Button variant="ghost" onClick={onCancel}>Cancel</Button>
      </div>
    </Card>
  )
}

export default function ControlTab({ entities, setError }) {
  const [items, setItems] = useState(null)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState([])
  const [pending, setPending] = useState(null)
  const [results, setResults] = useState({})
  const [frame, setFrame] = useState(0)
  const [expanded, setExpanded] = useState(null)

  const load = useCallback(async () => {
    try { setItems((await api.getControl()).items) } catch (e) { setError(e.message) }
  }, [setError])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    if (editing) return
    const t = setInterval(load, POLL_MS)
    return () => clearInterval(t)
  }, [editing, load])

  // One timer for every camera, so adding another does not multiply the work.
  const cameraCount = (items || []).filter((i) => i.type === 'camera').length
  useEffect(() => {
    if (editing || !cameraCount) return
    const t = setInterval(() => setFrame((n) => n + 1), FRAME_MS)
    return () => clearInterval(t)
  }, [editing, cameraCount])

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

  async function save() {
    setError(null)
    try {
      await api.saveControl({ items: draft })
      setEditing(false)
      await load()
    } catch (e) { setError(e.message) }
  }

  if (!items) return <p className="text-zinc-500">Loading…</p>

  if (editing) {
    return (
      <Editor
        draft={draft}
        setDraft={setDraft}
        entities={entities}
        onSave={save}
        onCancel={() => setEditing(false)}
      />
    )
  }

  const startEditing = () => {
    setDraft(items.map((i) => ({ type: i.type, entity_id: i.entity_id })))
    setEditing(true)
  }

  if (!items.length) {
    return (
      <Card>
        <p className="text-zinc-300 font-medium">Nothing set up yet</p>
        <p className="text-sm text-zinc-500 mt-2">
          Build the page top to bottom — a camera, the gate it looks at, then the
          next. It is yours only; it is not what a guest sees.
        </p>
        <Button className="mt-4" onClick={startEditing}>Set it up</Button>
      </Card>
    )
  }

  return (
    <div>
      {groupRuns(items).map((run, i) =>
        run.type === 'camera' ? (
          <CameraRun key={`cams-${i}`} run={run} frame={frame}
            expanded={expanded} onExpand={setExpanded} />
        ) : (
          run.items.map((e) => (
            <EntityControl
              key={e.entity_id}
              entity={e}
              onAct={act}
              pending={pending}
              result={results[e.entity_id]}
              disabled={e.missing}
            />
          ))
        ),
      )}

      {items.some((i) => i.missing) && (
        <p className="text-xs text-amber-300 mb-4">
          Greyed-out blocks are entities Home Assistant no longer reports.
        </p>
      )}

      <Button variant="ghost" onClick={startEditing}>Edit this page</Button>
    </div>
  )
}
