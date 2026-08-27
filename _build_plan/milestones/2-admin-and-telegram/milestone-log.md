# Milestone 2 — Admin panel and Telegram control

Built 2026-08-27, in the same session as milestone 1 at the user's instruction.

## What's new in the app

- **Saved presets.** Name a set of entities, a duration, a theme and which
  credentials to issue. Minting a grant for a regular visitor is then one tap in
  the panel, or `/new plumber` from your phone.
- **Grant management.** Every live and scheduled grant with what it allows, a
  countdown, and which credentials it carries. Extend a live one by an hour or
  four, or revoke it. Finished grants stay visible below.
- **The live-PIN count against its cap**, with a note explaining why the number
  matters — guessing succeeds against *any* live PIN, so the effective keyspace
  shrinks as the count grows.
- **Audit log.** Everything that happened, filterable: actions, unlocks, wrong
  codes, refusals, gate-didn't-answer, lockouts. Wrong codes appear with no
  grant attached, because by definition they belong to nobody.
- **Camera streams.** A Stream button under each camera entity shows a live view
  inside the admin panel, refreshed once a second.
- **Branding.** Upload a logo and pick an accent colour; both appear on guest
  pages. Set the theme new grants start with.
- **Health.** Whether Home Assistant is reachable, whether the Telegram bot is
  running, whether PIN entry is currently locked out, and your live settings.
- **Telegram bot.** `/new`, `/list`, `/revoke`, `/extend`, `/presets`, `/help`.
  The PIN and the link arrive as **separate messages**, so forwarding the link
  to a visitor does not also forward the PIN.
- **Alerts** to your Home Assistant app when someone starts guessing codes or
  the bot stops responding.
- **The admin panel installs to your phone's home screen** and opens without
  browser chrome.

## The two regression guards the prompt required

| Guard | Status |
|---|---|
| The camera route lives under `/api/admin/*` and is never served publicly | **HELD.** `routes_admin.py` mounts it under the admin router; nginx on 8888 proxies only `/api/guest/`. `test_camera_snapshot_is_admin_only` asserts 200 via ingress and 404 from a public caller. |
| The guest bundle still ships no service worker | **HELD.** Separate `vite.guest.config.js` with no PWA plugin. Built output: guest has `index.html` + CSS + JS only; admin has `sw.js` + `workbox-*.js`. Four tests in `test_frontend_build.py` assert both halves. |

## What was built

- `addon/routes_admin.py` — entities, mint, mint-preset, grants, revoke, extend,
  presets CRUD, audit, camera snapshot, branding, logo upload, health.
- `gate_pin/bot.py` — Telegram poller and commands, framework-agnostic.
- `gate_pin/duration.py` — shared `2h` / `30m` / `1d` parsing.
- `addon/main.py` — lifespan wiring, bot supervisor task, audit prune task.
- `frontend/admin/` — six tabs (Mint, Grants, Presets, Cameras, Audit,
  Settings), `EntityPicker`, shared UI primitives, PWA config.

## Decisions made during implementation

1. **Camera "streaming" is snapshot polling at ~1 fps**, not a proxied MJPEG or
   HLS stream. Proxying a long-lived video stream through nginx and ingress is
   considerably more fragile, and one frame a second answers the actual question
   ("who is at the gate"). The endpoint sends `Cache-Control: no-store`.
2. **Alerts fall back to a persistent notification** when `notify_service` is
   not configured, so a lockout is never silent just because that option is
   blank.
3. **The lockout alert fires once per cooldown**, not once per failed attempt —
   otherwise an attack becomes its own notification flood.
4. **Extend is offered only on active grants** in the UI, and the API returns
   409 with "Mint a new one" for anything else. Reviving an expired grant would
   mean a code still sitting in someone's messages silently starts working.
5. **Audit rows are pruned on a 6-hourly task** using `audit_retention_days`.
6. **The bot supervisor announces a crash once**, then keeps restarting every 10
   seconds without re-announcing, so a persistent outage does not spam you.

## Deviations

- None outstanding. The QR code carried over from milestone 1 is now real and
  scannable; see that log.
- `python-telegram-bot` was not used; the bot talks to the Bot API directly. See
  milestone 1's log for the reasoning.

## Defects found and fixed

- **The bot watchdog could never fire.** `_supervise_bot` alerted only when
  `bot.run()` returned, but that coroutine handles its own errors and retries
  forever, so it never returns — a wedged bot would have stayed completely
  silent, which is the exact failure the plan says must be visible. Replaced
  with `_watch_bot_heartbeat`, which watches the `last_ok` timestamp, fires once
  per outage, and announces recovery. See milestone 1's log for the full list.

## Verification run

52 tests pass (`python3 -m pytest gate-pin/tests -q`). They cover the failure
paths rather than the happy path: a preview fetcher cannot act, extra body
fields are rejected at the boundary, a session cannot reach another grant's
entity, revocation takes effect in an open session, a dead gate reports
differently from a wrong code, IP rotation still trips the global budget, a PIN
lockout never blocks link credentials, and the guest bundle contains no service
worker.

**Not covered by automated tests, and needing a live install:** everything
requiring Home Assistant OS (ingress auth, Supervisor API, `/data` persistence,
add-on networking), the real Cloudflare header path, and the Telegram bot
against the real API.
