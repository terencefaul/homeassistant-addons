# Milestone 1 — Live gate access

Built 2026-08-27. Milestones 1 and 2 were built in one session at the user's
instruction, so some files listed here also carry milestone 2 features; this
log covers what milestone 1 scoped.

## What's new in the app

- You can install the add-on from this repository and it appears in the Home
  Assistant sidebar, behind your existing HA login. There is no second password.
- You can mint a guest credential: pick a label, tick entities from a searchable
  list, choose how long it lasts, choose whether it starts now or later, pick a
  theme, and choose a PIN, a link, or both.
- Minting shows you the PIN and the link once, with a copy button and a plain
  warning that they will never be shown again.
- A visitor can open your public URL, type the PIN, and operate only the
  entities you chose — each with a live on/off or open/closed indicator and a
  button sized for a thumb.
- A link credential works by tapping it. The code is removed from the address
  bar the moment it has been used.
- The visitor is told exactly what went wrong: a wrong code, a code that has not
  started yet, an expired code, a cancelled code, and "the gate didn't respond"
  are five different messages, not one.
- Guessing wrong codes slows down and then locks out, and you get an alert.
- You can revoke a credential and it stops working instantly, even in a tab the
  visitor already has open.

## The six skeleton validations

The prompt required these before building. Results:

| # | Check | Result |
|---|---|---|
| 5 | `pydantic-core` installs from a musl wheel, not a Rust compile | **PASS, on all three architectures.** Verified by running `pip install --only-binary=:all: pydantic==2.*` on `python:3.12-alpine` under `linux/amd64`, `linux/arm64` and `linux/arm/v7`. All three resolved pydantic 2.13.4 / pydantic-core 2.46.4 from prebuilt wheels. **Risk 7 in the engineering plan is closed.** |
| — | HA base images exist at the pinned tags | **PASS.** `docker manifest inspect` confirms `{amd64,aarch64,armv7}-base-python:3.12-alpine3.20`. |
| — | The image builds end to end | **PASS.** Multi-stage build for `linux/arm64`. |
| 1 | Add-on appears from the repository URL and installs | **NOT VERIFIABLE HERE.** Needs a live HA OS instance. |
| 2 | Starts, and ingress authenticates the admin panel | **NOT VERIFIABLE HERE.** |
| 3 | Supervisor API answers with `SUPERVISOR_TOKEN` | **NOT VERIFIABLE HERE.** |
| 4 | `/data` survives an add-on restart | **NOT VERIFIABLE HERE.** |
| 6 | The container hostname resolves from another add-on | **NOT VERIFIABLE HERE.** Decides whether 8888 needs publishing at all. |

Five of the six need a running Home Assistant OS and must be checked on first
install. Number 5 was the one that could have changed the stack, and it passed,
so the stack in the PRD stands unchanged.

To settle 1–4 and 6, install the add-on and confirm: it appears in the store,
the sidebar panel loads, the Mint tab lists your real entities (that proves the
Supervisor API), a restart preserves any grant you minted, and `cloudflared` can
reach `http://<addon-hostname>:8888`.

## What was built

```
repository.json
gate-pin/
  config.yaml build.yaml Dockerfile run.sh requirements.txt
  README.md CHANGELOG.md .dockerignore
  nginx/nginx.conf  nginx/http.d/{guest,admin}.conf
  rootfs/app/gate_pin/     clock policy store credentials grants
                           ratelimit ha duration bot
  rootfs/app/addon/        options token session deps schemas
                           routes_guest routes_admin main
  frontend/                vite.guest.config.js  vite.admin.config.js
                           guest/  admin/
  tests/                   52 tests
```

**Data model** is as the PRD specifies: `grants`, `credentials`,
`grant_entities`, `presets`, `audit`, `settings`. Every timestamp is epoch
seconds UTC. `grants.valid_until` is `NOT NULL`, so a permanent credential
cannot be represented.

**Credentials** are stored only as `HMAC-SHA256(secret, credential)`. The secret
is generated on first run into `/data/secret.key`. No code path can recover a
plaintext credential, and `test_plaintext_credentials_are_never_stored` asserts
the raw bytes are absent from the database.

**Routes.** Guest: `POST /api/guest/redeem`, `POST /api/guest/act`,
`GET /api/guest/state`, `GET /api/guest/branding`, `GET /api/guest/logo`.
Admin: everything under `/api/admin/`.

## Decisions made during implementation

1. **The Telegram bot is written directly against the Bot API** rather than
   using `python-telegram-bot`, which the engineering plan named. It needs
   `getUpdates` and `sendMessage` and nothing else, and owning the poll loop is
   what makes the watchdog and the 409 single-instance case straightforward. It
   also keeps `gate_pin/bot.py` free of a framework with its own event-loop
   opinions, which matters for the portability rule.
2. **`GET /` and `GET /g/<token>` never reach application code at all.** nginx
   serves them as static files via `try_files`. This is stronger than the plan's
   "the GET handler must be inert", because there is no handler to make inert.
   `test_only_post_routes_exist_under_guest_api` asserts no acting GET route
   exists.
3. **`require_cf_header` is a new option, defaulting on.** The plan said trust
   `CF-Connecting-IP` because Cloudflare overwrites it. That holds only while
   8888 is unreachable except through the tunnel — so the app now *refuses* any
   guest request lacking the header (HTTP 421), turning that misconfiguration
   from silent into loud.
4. **`ports: {8888/tcp: null}`** — declared but unmapped by default, so the port
   does not bind on the host when `cloudflared` runs as an add-on. Publishing it
   is an explicit choice for people whose tunnel lives elsewhere.
5. **`--only-binary=:all:` in the Dockerfile.** Encodes the wheel check above:
   if a musl wheel ever disappears the build fails loudly instead of quietly
   compiling Rust.
6. **The real-IP nginx snippet is generated at boot** from the
   `trusted_proxy_cidr` option into `/etc/nginx/real_ip.conf`. Deliberately a
   generated include rather than the reference add-on's approach of `sed`-ing
   its own checked-in config (`run.sh:8-12`).
7. **Session cookies are `Secure`**, so tests run against `https://testserver`.
8. **`camera` is selectable but never guest-visible.** `is_selectable` allows
   attaching one to a grant so the admin panel can stream it;
   `is_guest_visible` filters it out of every guest response.

## Deviations from the PRD or the plan

- The bot framework, as in (1) above.
- The QR code on the mint screen is currently a placeholder SVG showing the link
  as text, not a scannable QR. Rendering a real one needs a QR library and none
  was added. **This is the one PRD item not fully delivered.** The link is still
  copyable and the placeholder is legible, but it will not scan. Adding
  `qrcode-generator` or similar to the admin bundle would finish it.

## Defects found and fixed during verification

Three were found by review and one by running the container. Recording them
because each is a shape that will recur.

1. **`/api/guest/logo` had an unannotated `request` parameter**, so FastAPI
   would have treated it as a query parameter instead of injecting the request.
   Missed because the test suite builds its own app from the routers and never
   imported `addon/main.py`. Fixed, and `tests/test_app_wiring.py` now imports
   the real app and builds its OpenAPI schema, which forces every handler
   argument to resolve.

2. **An unknown credential was always charged to the PIN rate-limit budget.**
   That let someone grind random *tokens* to exhaust the PIN budget and lock out
   PIN entry for real visitors — a denial of service against the channel with no
   alternative. Unknown credentials are now charged to the budget they look
   like: all-digits and 6–10 long counts as a PIN, anything else as a token.

3. **The bot watchdog could never fire.** `_supervise_bot` alerted when
   `bot.run()` returned, but `run()` handles its own errors and retries forever,
   so it never returns. A wedged bot would have stayed silent — exactly the
   failure the plan says must be visible. Replaced with `_watch_bot_heartbeat`,
   which watches the `last_ok` timestamp, alerts once per outage, and announces
   recovery.

4. **`/api/admin/*` answered 200 on the public port.** Found by running the
   container, not by reading the config. No data leaked — nginx's SPA fallback
   was serving the guest `index.html` — but a 200 on an admin path reads as
   "exposed" to anyone auditing it, and would have masked a future edit that
   genuinely did start proxying `/api/` there. `guest.conf` now has an explicit
   `location /api/ { return 404; }`; longest-prefix matching keeps
   `/api/guest/` working.

5. **nginx started before the application**, leaving a few seconds after every
   restart where the guest page loads and every action returns 502 — which reads
   to a visitor as "the gate is broken". `run.sh` now starts the app, waits for
   it to listen, and only then starts nginx; it exits with the app so Supervisor
   restarts the add-on rather than leaving nginx serving a page whose API is
   gone.

## Container smoke test

Built for `linux/arm64` and run with a stub `/data`. Results:

| Check | Result |
|---|---|
| `GET /` and `GET /g/<token>` serve the guest page | 200 |
| `Referrer-Policy: no-referrer`, CSP, `X-Frame-Options: DENY` present | yes |
| `/api/admin/*` on the public port | 404 |
| `/api/admin/grants` on the ingress port | 200 |
| Guest API without `CF-Connecting-IP` | 421 |
| Guest API with a wrong code | 401, "That code isn't recognised." |
| Guest API with an injected `service` field | 422 |
| Mint through ingress, then redeem that PIN on the public port | 200 |

## What milestone 2 needs to know

- `Deps` in `addon/deps.py` is the single runtime container; add new state there.
- `gate_pin/` must not import FastAPI, uvicorn, `SUPERVISOR_TOKEN` or `addon`.
  `tests/test_portability.py` enforces this and will fail the suite.
- The admin frontend must use **relative** URLs (`api/admin/...`), because
  ingress serves the panel under `/api/hassio_ingress/<token>/`. An absolute
  path leaves the ingress prefix and hits Home Assistant itself.
