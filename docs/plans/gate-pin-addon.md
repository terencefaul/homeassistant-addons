# Gate PIN — a Home Assistant add-on for time-limited guest access to chosen entities

**Status:** planned, not built. Written 2026-08-27.
**Base studied:** `TekniskSupport/homeassistant-addons` @ `020d61c` (`limited-guest-access` v0.1.34).
All `file:line` references below are into that repository unless stated otherwise.

---

## Context

The want: a visitor arrives at the property, is given a short-lived credential, opens
`gate.terica.co.za`, and can operate a small set of entities I chose — nothing else — until the
credential expires. I request credentials from a Telegram bot.

`limited-guest-access` is the closest existing thing and is the starting reference. It is a
1,120-line PHP/nginx add-on that solves a *related* problem and gets several things right that
are worth copying, and several wrong that are worth not copying.

### What the base actually does

| Concern | How the base does it | Reference |
|---|---|---|
| Runtime | nginx + php-fpm 8.4 on Alpine; no application process at all | `Dockerfile`, `run.sh:17` |
| Storage | one flat JSON file per link, `/data/links/<id>.json` | `user/actions.php:5` |
| What is exposed | pre-authored **service calls** with frozen payloads — never entities | `user/actions.php:120-139` |
| Entity state | read-only, only to colour a dot on the button | `user/actions.php:167-177` |
| Guest auth | the secret URL, plus an optional bcrypt password | `admin/actions.php:59-61` |
| Link IDs | `mb_substr(md5(time()), 0, 6)` — time-seeded, therefore guessable | `admin/actions.php:177-185` |
| Expiry | per-action `valid_from` / `expiry_time`, parsed with `strtotime()` on local strings | `user/actions.php:81-97` |
| Single use | delete the action from the JSON file *after* firing it | `user/actions.php:109-118` |
| Admin auth | **none**; the panel is served on port 8899 with nothing in front of it | `default.conf` |
| HA access | `SUPERVISOR_TOKEN` against `http://supervisor/core/api/`, unscoped | `user/actions.php:131` |

`run.sh:17` is worth quoting in full, because it determines the framing decision:

```sh
while true; do sleep 1000; done
```

There is no long-lived process. php-fpm answers requests and nothing else runs. A Telegram bot
cannot be added to this container without introducing a daemon that does not currently exist.

### Three premises in the original brief, corrected

1. **"HACS or integration"** is not a pair. HACS distributes integrations, Lovelace cards and
   themes; it dropped add-on support years ago. Add-ons are distributed by pasting a repository
   URL into the Supervisor add-on store — exactly what this repo's `repository.json` and its
   README install instructions describe. Distribution therefore *follows from* the
   add-on-vs-integration decision and is not a separate choice.
2. **`gate.terica.co.za` cannot be created by this codebase.** The base only takes `external_url`
   as a display string used to render link text (`admin/actions.php:21`) and optionally reads
   `/ssl/*.pem` (`tls.conf`). DNS, a public route and a certificate are manual setup outside
   whatever we build. See *Manual setup outside the codebase*.
3. **"Make entities accessible"** is not what the base does. It exposes frozen service calls.
   Exposing an *entity*, with live state and a domain-appropriate control, is a materially
   different data model and a materially different security boundary. This plan does the latter.

### Deliberately out of scope

- **Any change to how HA itself is exposed.** Port 8123 stays exactly as private as it is today.
  This add-on's public surface is its own port, on its own container.
- **Guest accounts, or any notion of visitor identity.** A credential is a bearer token. There is
  no login, no profile, no history tied to a person.
- **Use counting.** Explicitly dropped — see the decisions table and Risk 1. Time is the only
  control.
- **Camera streams.** Read-only entity *state* is in; proxying an RTSP or MJPEG stream to a
  public endpoint is a different problem with a different threat model.
- **Scoping the Supervisor token.** Home Assistant provides no mechanism for it. See Risk 5.

### Decisions locked during planning

| Question | Decision | Why |
|---|---|---|
| Add-on, integration, or standalone? | **Add-on** | The public unauthenticated page must not execute inside the HA process. See *The one architectural problem*. Install is HA OS, so add-ons are available. |
| Fork the PHP base, or rewrite? | **Rewrite, base as reference** | A Telegram bot needs a persistent async process; php-fpm has none (`run.sh:17`). No composer, no tests, no build step in the base. |
| Distribution | **Add-on repository URL** | Follows from "add-on". HACS is not an option for add-ons. |
| Audience | **Mine now, publishable later** | Core logic goes in a Supervisor-agnostic Python package so an integration wrapper is later a packaging job, not a rewrite. |
| Database | **SQLite, WAL mode. No Postgres, no DSN option.** | Single writing process, a few dozen live grants, a few thousand audit rows a year. Postgres bundled means a second process and HA backing up a live data directory; Postgres external means an install dependency the add-on cannot declare, which breaks publishing. SQLite is also what HA's own recorder defaults to. |
| HTTP framework | **FastAPI + Pydantic** | Reversed from an earlier aiohttp decision. Pydantic `extra="forbid"` turns "no request field ever reaches the HA call" from review discipline into a type-level guarantee — see *The design*. Handlers stay thin so the later integration port is an afternoon. |
| Credential model | **One grant, two credentials: a 6-digit PIN and a 128-bit token** | They are the same *kind* of thing but sit at opposite ends of the entropy/delivery tradeoff. A PIN is typed, so it is capped at ~20 bits and survives only on rate limiting; a token is never typed, so it can be 128 bits and brute force stops being a threat model. Modelling them as one object would give the link the token's silent leak surface *and* the PIN's tiny keyspace. |
| PIN, token, or both? | **Chosen per grant at mint; default both** | The one-grant/many-credentials shape gives it for free, and it lets the live-PIN cap degrade to token-only instead of blocking. |
| Web server | **nginx. Caddy considered and rejected.** | Caddy's advantage was managing TLS modes without boot-time config rewriting (`run.sh:8-12` sed-patches nginx today). With Cloudflare terminating TLS the add-on has no TLS config at all, so that advantage evaporates — and nginx is the more conventional choice for an add-on others may read. Revisit if published to installers without a tunnel. |
| TLS | **Cloudflare Tunnel, terminated at the edge. No certs in the add-on.** | `terica.co.za` is already on Cloudflare, so this is the least work and the strongest posture: no inbound ports, origin unreachable directly. Also yields `CF-Connecting-IP`, which is unforgeable and replaces the `X-Forwarded-For` guesswork in §2. |
| PWA scope | **Guest: manifest, no service worker. Admin: full PWA.** | Offline is meaningless for a gate, and a service worker would give the public origin persistent code execution on every visitor's phone, outliving the credential. The admin page inverts every one of those. |
| Uses vs time | **Time window only. No use counting.** | User's call, and it deletes a lot of machinery: no `uses_spent`, no atomic decrement, no rowcount-as-authorisation, no refund-on-failure compensation. Cost recorded as Risk 1. |
| Collapse window on first use? | **No — the window is the window** | Predictable, and a visitor going out to the van and back doesn't risk locking themselves out. Cost folded into Risk 1. |
| Entity exposure | **Pick entities; UI renders a control per domain** | What was asked for, and far less admin work per grant than authoring actions. Requires a server-side domain→service allowlist. |
| Telegram bot role | **Admin-only, allowlisted by numeric chat ID; I forward the credential** | Simplest, and the visitor needs no Telegram account. |
| Appetite | **Everything in one pass** | User's call. The build sequence still names the step to validate before anything is built on top of it. |
| Credential storage form | **HMAC-SHA256(secret, credential)** — *assumed, not asked* | Must be indexable for lookup, so bcrypt is out. A bare hash of 6 digits is reversed instantly from a leaked DB; keyed HMAC is not, without the secret. |
| Frontend | **Vite + React 19 + Tailwind 4, two separate bundles** — *assumed, not asked* | Was in the brief, and owning the container makes it free. Two entry points so the public bundle contains no admin code or admin API shapes. |
| Config file format | **`config.yaml`** — *assumed, not asked* | Current add-on convention. The base's `config.json` still works but is the older form. |

---

## The one architectural problem to solve first

**An unauthenticated page that can operate a physical gate is about to be reachable from the
public internet. Where that page executes is the decision that constrains everything else.**

The reasons, in descending strength:

**1. Blast radius of a compromise.** In an add-on, the guest page is served by nginx in a
separate container, holding only a Supervisor-scoped token. Compromise it and the attacker gets
the entities that grant authorised. They do not get Home Assistant. In an integration, the same
page is `hass.http.register_view(..., requires_auth=False)` — served by HA's own aiohttp app,
inside the HA process, on port 8123, **same origin as `/auth/token` and the admin session
cookie**.

**2. The containment you would reach for does not hold.** The obvious integration answer is
"the reverse proxy only routes `gate.terica.co.za` → `/api/gate_pin/*`". But `requires_auth =
False` is a property of the *view*, not of the hostname. Anyone who learns HA's real address
reaches that same unauthenticated view directly and the proxy restriction is bypassed entirely.
With an add-on, the guest port is simply never published except through the tunnel.

**3. Process lifecycle.** An add-on's Telegram bot is a process that crashes and restarts on its
own. An integration's bot is an asyncio task on HA's event loop: a wedged long-poll degrades all
of HA, `python-telegram-bot` is pip-installed into the user's HA venv via `manifest.json`
requirements, and every HA restart restarts the bot.

**4. Admin authentication comes free.** Ingress puts the admin UI behind HA's own login at
`/api/hassio_ingress/<token>/`, with a sidebar panel, and no auth code is written. This is
precisely the base's worst flaw — `default.conf` serves the admin panel on 8899 with nothing in
front of it, protected only by the operator not exposing the port.

The two arguments *for* an integration are both about reach, not architecture: it runs on
Container/Core installs, and HACS is what most people already have. Neither applies to a private
deployment on HA OS. Both would apply if this were published, which is why the core logic is
kept Supervisor-agnostic.

```
  visitor                                  no inbound ports anywhere
     │ HTTPS                                          │
     ▼                                                ▼
  Cloudflare edge ◄──outbound tunnel── cloudflared ───┐
  (TLS terminated,                                    │ add-on network
   CF-Connecting-IP set)                              │ (8888 not on the host)
                      ┌─────────────────────────────  ▼ ──────┐
                      │ add-on container                     │
  gate.terica.co.za   │  nginx :8888  ─► guest bundle        │
                      │        │        proxies /api/guest/* │
                      │        │        ONLY                 │
                      │        └──► uvicorn 127.0.0.1:8080   │
                      │                 (FastAPI)            │
                      │  nginx :8099 ───┘  /api/admin/* too  │
  me ──HA login────►  │        admin bundle                  │
    (ingress)         │        never published in ports:     │
                      │                                      │
                      │  telegram poller ──► same asyncio    │
                      │  sqlite /data/gate-pin.db (WAL)      │
                      └──────────────┬───────────────────────┘
                                     │ SUPERVISOR_TOKEN
                                     ▼
                          http://supervisor/core/api/
                                     │
                              Home Assistant :8123
                              (never publicly exposed)
```

---

## The design

### Repository layout

```
ha_pin/
├── repository.json                 # add-on repo manifest — copy the base's shape
├── gate-pin/
│   ├── config.yaml                 # add-on manifest (was config.json in the base)
│   ├── build.yaml                  # base images per arch — the base has none, see ABSENCES
│   ├── Dockerfile
│   ├── run.sh                      # bashio entrypoint
│   ├── nginx/
│   │   ├── guest.conf              # :8888  public, proxies /api/guest/* only
│   │   └── admin.conf              # :8099  ingress only, never in config.yaml ports:
│   ├── CHANGELOG.md
│   ├── icon.png  logo.png
│   └── rootfs/app/
│       ├── gate_pin/               # PORTABLE CORE — no Supervisor imports
│       │   ├── store.py            # sqlite3: grants, credentials, audit
│       │   ├── grants.py           # mint / resolve / revoke
│       │   ├── policy.py           # domain → allowed services allowlist
│       │   ├── ha.py               # HA client behind an abstract token provider
│       │   ├── ratelimit.py        # per-IP backoff + global failure budget
│       │   └── bot.py              # telegram, framework-agnostic handlers
│       ├── addon/                  # SUPERVISOR GLUE — the only Supervisor-aware code
│       │   ├── main.py             # FastAPI app + bot task + watchdog
│       │   ├── routes_guest.py     # /api/guest/*
│       │   ├── routes_admin.py     # /api/admin/*
│       │   ├── schemas.py          # Pydantic models, all extra="forbid"
│       │   ├── token.py            # reads SUPERVISOR_TOKEN
│       │   └── options.py          # reads /data/options.json
│       └── tests/
└── frontend/
    ├── guest/                      # Vite entry 1 — public bundle, minimal
    └── admin/                      # Vite entry 2 — ingress-only bundle
```

The `gate_pin/` ↔ `addon/` split is the whole cost of "publishable later": `gate_pin` must never
import anything that assumes Supervisor, and `ha.py` takes a token *provider*, so an integration
wrapper supplies `hass`-derived credentials instead. Enforce with a test that greps for
`SUPERVISOR` and `fastapi` under `gate_pin/`.

### Data model

Precedent: none in the base worth copying — it has no schema, only ad-hoc JSON. This is new.

```sql
CREATE TABLE grants (
  id            TEXT PRIMARY KEY,          -- opaque, for logs and the admin UI
  label         TEXT,                      -- "plumber, Tuesday"
  created_at    INTEGER NOT NULL,          -- epoch seconds, UTC. always.
  valid_from    INTEGER NOT NULL,
  valid_until   INTEGER NOT NULL,          -- NOT NULL. a grant can never be permanent.
  revoked_at    INTEGER
);

CREATE TABLE credentials (
  hmac          BLOB PRIMARY KEY,          -- HMAC-SHA256(secret, credential)
  grant_id      TEXT NOT NULL REFERENCES grants(id) ON DELETE CASCADE,
  kind          TEXT NOT NULL CHECK (kind IN ('pin', 'token'))
);
CREATE INDEX credentials_grant ON credentials(grant_id);

CREATE TABLE grant_entities (              -- what this grant may touch
  grant_id      TEXT NOT NULL REFERENCES grants(id) ON DELETE CASCADE,
  entity_id     TEXT NOT NULL,
  PRIMARY KEY (grant_id, entity_id)
);

CREATE TABLE audit (                       -- every attempt, success or not
  ts            INTEGER NOT NULL,
  grant_id      TEXT,                      -- NULL for a failed redemption
  kind          TEXT,                      -- which credential was presented
  event         TEXT NOT NULL,             -- redeem_ok | redeem_fail | act | denied | act_failed
  entity_id     TEXT,
  service       TEXT,
  client_ip     TEXT,
  detail        TEXT
);
CREATE INDEX audit_ts ON audit(ts);
```

**The `credentials` table is the point of the two-credential decision.** One grant, one window,
one entity list, one revocation — reached by either a 6-digit PIN read over the phone or a
128-bit token sent on Telegram. Lookup is uniform: HMAC whatever was presented, find the row, get
the grant. Rate-limit policy is keyed on `kind`, because the two need wildly different treatment
(see *The part that quietly breaks* §2).

**Which credentials a grant gets is chosen at mint: PIN, token, or both.** The one-to-many shape
gives this for free — a grant simply has one credential row, or two. It also makes the live-PIN
cap (§3) degrade gracefully rather than blocking: at the cap you can still mint token-only grants,
which have no keyspace-decay property at any scale. Default is **both**, since the cap is
generous and having the fallback channel costs nothing until you need it.

`valid_until` is `NOT NULL` by design. With use counting dropped, a credential with no expiry
would be permanent, and a permanent bearer credential in a WhatsApp thread is the failure mode
this whole design exists to avoid.

Every timestamp is **epoch seconds in UTC**. The base stores locale-dependent strings and parses
them with `strtotime()` at read time (`user/actions.php:81-97`), against a timezone taken from
`$_SERVER["TZ"]` (`user/actions.php:16`) — so a container timezone change silently shifts every
expiry that was ever written. With time as the *only* control, that class of bug is no longer
cosmetic; see §4.

### API surface

| Route | Method | Auth | Notes |
|---|---|---|---|
| `GET /` | GET | none | Serves the guest bundle. **Inert.** |
| `GET /g/<token>` | GET | none | Serves the same bundle, token in path. **Inert.** |
| `POST /api/guest/redeem` | POST | credential in body | Returns entity list, sets session cookie. |
| `POST /api/guest/act` | POST | session cookie | Calls HA. |
| `GET /api/guest/state` | GET | session cookie | Polled; scoped to the grant's entities. |
| `/api/admin/*` | | ingress | Mint, list, revoke, audit, bot health. |

nginx on `:8888` proxies **only** `/api/guest/*` to uvicorn. The admin router is unreachable on
the public port because nginx never forwards its path prefix there — not because the application
checks something. As defence in depth the admin routes additionally require the `X-Ingress-Path`
header that HA's ingress proxy sets, but the nginx path restriction is the real control.

Every request body is a Pydantic model with `extra="forbid"`:

```python
class ActRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_id: str
    intent: Literal["open", "close", "stop", "on", "off", "unlock", "activate", "run"]
```

This is why FastAPI replaced aiohttp. "No field from the request body ever reaches the HA call"
was going to be a hand-written rule that someone erodes in six months; as a Pydantic model it is
a type-level guarantee that fails loudly at the boundary.

The session cookie is an HMAC-signed token carrying `grant_id`, expiring at the grant's
`valid_until`, `HttpOnly; Secure; SameSite=Strict; Path=/`. Its only job is to avoid re-presenting
the credential for each tap. `/api/guest/act` re-reads the grant and re-checks the window and
`revoked_at` on **every** call rather than trusting the cookie — revocation must be immediate.

### The domain → service allowlist

`policy.py` holds a hard-coded map. **The client never names a service.** It posts
`{entity_id, intent}` and the server resolves:

```python
POLICY = {
  "cover":  {"open": "open_cover", "close": "close_cover", "stop": "stop_cover"},
  "lock":   {"open": "unlock"},                  # deliberately no "lock" — see below
  "light":  {"on": "turn_on", "off": "turn_off"},
  "switch": {"on": "turn_on", "off": "turn_off"},
  "scene":  {"activate": "turn_on"},
  "script": {"run": "turn_on"},
}
READ_ONLY_DOMAINS = {"binary_sensor", "sensor", "person", "device_tracker"}
```

Three checks before any call, in this order, all server-side:

1. `entity_id` ∈ **this grant's** `grant_entities` — not merely "some grant's".
2. `entity_id`'s domain ∈ `POLICY`, and `intent` ∈ `POLICY[domain]`.
3. The service payload is constructed server-side as `{"entity_id": entity_id}` and nothing
   else.

Check 1 is the one the base got wrong once and had to fix. `CHANGELOG.md` records it:

> ## [0.1.33] - 2024-03-28
> ### bugfix
> - Fixed security issue, where a user could get access to a link not authenticated to, if
>   authenticated to another link

The cause was a session key shared across links; the fix (`93f50d8`, *"added hash to the
authentiated session variable"*) namespaced it per link (`user/actions.php:29`). Our session
cookie carries `grant_id` and every authorisation check is scoped by it — the same lesson applied
structurally rather than as a patch.

`lock` has no "lock" intent on purpose: a guest who can *lock* a door can lock someone out. Only
`unlock` is offered. This is the kind of asymmetry the base's free-form service picker cannot
express.

### Frontend

Two Vite entry points, two builds, two nginx roots. The guest bundle must not contain admin code,
admin route strings, or any entity list but the redeemed grant's.

Everything is self-hosted. The base loads Google Fonts via `@import` in the guest page
(`user/index.php:30`) and jQuery from `code.jquery.com` in the admin page (`admin/index.php`).
On a public page that is both a supply-chain dependency and a **referrer leak**: with a token in
the URL, the request to Google carries it in the `Referer` header.

Required on every `:8888` response: `Referrer-Policy: no-referrer`. On load of `/g/<token>`, the
bundle POSTs the token, then immediately `history.replaceState(null, '', '/')` so the credential
leaves the address bar, history and any subsequent referrer.

Guest page states: credential entry (or auto-submit from `/g/<token>`) → invalid, with backoff →
entity list with live state → tap → confirmation, **or a distinct "the gate did not respond"
state**. That distinction is a correctness requirement, not a nicety: without it, every failure
mode in this document presents to the visitor as "wrong code," which is what makes them expensive
to diagnose.

Live state via a poll on `/api/guest/state` every few seconds. Not a websocket — the connection
is public, and long-lived connections are a cheaper DoS than polls.

#### Mobile-first, and how far the PWA goes

The guest page is used one-handed, at a gate, on whatever signal reaches the driveway. That is a
set of hard requirements, not a styling preference:

- Bundle small enough to load on bad mobile data — budget it and fail the build if exceeded.
- Tap targets sized for a thumb, reachable in the lower half of the screen.
- Every action has an explicit **pending** state and a visible timeout. The gate is precisely
  where signal is worst; a tap that appears to do nothing is what makes someone tap eight times.
- Legible in direct sun and at night: high contrast, no thin grey-on-grey.

**The guest page gets a manifest and no service worker.** Icon, theme colour, `display:
standalone`, viewport — so it feels like an app if someone adds it to the home screen — but
nothing that persists. Reasons, in order:

1. **Offline is meaningless here.** Opening a gate requires the network by definition; there is
   nothing useful to serve from a cache.
2. **A service worker gives this public origin persistent code execution on every visitor's
   phone**, outliving the credential that got them there. On the one surface whose entire design
   goal is a small blast radius, that is the wrong direction.
3. A visitor using this once will not install it, so the install prompt is noise.

**The admin page gets the full PWA** — service worker, offline shell, installable. The calculus
inverts: it is used repeatedly by one known person, it sits behind ingress rather than on a public
origin, and having it on the home screen is genuinely useful.

Enforce the asymmetry in the build: the guest Vite config must not include the PWA/service-worker
plugin at all. A single shared config with a flag is how a service worker eventually ships to the
public origin by accident.

### The Telegram bot

`bot.py` under `gate_pin/`, framework-agnostic handlers; `addon/main.py` owns the poller task.

- Allowlist is a **list of numeric chat IDs** in add-on options. Never `@usernames` — Telegram
  usernames can be released and re-registered by someone else.
- Updates from a non-allowlisted chat are dropped without a reply. Do not answer "you are not
  authorised"; that confirms the bot exists.
- Commands: `/new <duration> <entity…> [--pin-only|--token-only]`, `/list`, `/revoke <id>`.
- `/new` defaults to both credentials — the PIN to read out, and the `/g/<token>` link to
  forward. One grant, two ways to deliver it; the flags narrow it to one.
- Each is sent in its **own message**, so forwarding the link does not also forward the PIN.
- A watchdog restarts the poller on failure and writes a heartbeat the admin UI reads. A silently
  dead bot is discovered when someone is standing at the gate; it must be visible.

### nginx, and why not Caddy

Caddy was considered and rejected. Its advantage here would have been managing TLS *modes*
without boot-time config rewriting — the base currently sed-patches its own nginx config at
startup based on an option flag (`run.sh:8-12`):

```sh
sed -i 's/  listen 8888 default_server;/  include \/etc\/nginx\/snippets\/tls.conf;/g' \
    /etc/nginx/http.d/default.conf
```

With Cloudflare terminating TLS, **the add-on has no TLS configuration at all** — nginx serves
plain HTTP and the tunnel does the rest. That removes the entire problem Caddy would have solved,
and nginx is the more conventional choice for an add-on others may read. *Revisit if published:*
an installer without a tunnel needs real TLS modes, and that is the point at which Caddy earns
its place.

```
# guest.conf
server {
  listen 8888 default_server;
  root /app/www/guest;
  add_header Referrer-Policy "no-referrer" always;
  real_ip_header CF-Connecting-IP;         # see "quietly breaks" §2
  set_real_ip_from <cloudflared address>;
  location /api/guest/ { proxy_pass http://127.0.0.1:8080; }   # and nothing else
  location / { try_files $uri /index.html; }
}

# admin.conf — NOT in config.yaml's ports:; reachable only via ingress
server { listen 8099; root /app/www/admin; location /api/ { proxy_pass http://127.0.0.1:8080; } }
```

**Preferred: publish no host ports at all.** The base publishes both:

```json
"ports": { "8888/tcp": 8888, "8899/tcp": 8899 }
```

Add-ons share a Docker network and are addressable by container hostname, so if `cloudflared`
runs as an add-on on the same machine it can target `http://<gate-pin-hostname>:8888` **without
8888 ever being bound on the host**. That is strictly better than publishing it and relying on
the firewall: an unpublished port cannot be reached from the LAN at all, which is exactly the
precondition that §2's `CF-Connecting-IP` trust depends on.

The exact hostname format is version-dependent — **resolve it empirically in build step 1**, and
fall back to publishing `8888/tcp` if cloudflared runs elsewhere (a separate host, a router, a
VM). Either way `config.yaml` never publishes 8899 or 8099; ingress reaches the admin block
internally.

---

## The part that quietly breaks

Ordered by consequence. Dropping use counting removed two entries from this list (the concurrent
double-spend and its refund-on-failure follow-on) and made two of the survivors more important,
because time and rate limiting are now the *only* controls.

### 1. A GET that acts

**The trap.** The token link `gate.terica.co.za/g/kJ8xQ2mNp4vR7wZ1` will be sent over Telegram.
**Telegram fetches URLs in messages to build link previews.** So do WhatsApp, iMessage, Slack and
most mail clients. If a GET can open the gate, your gate opens the moment you send the link.

**What the wrong version looks like when it fails.** The gate opens with nobody there. You will
not connect it to the message you sent thirty seconds earlier. It looks like a hardware fault, or
a ghost, or someone in the driveway.

The base is vulnerable to exactly this: `user/actions.php:43-55` performs the service call
directly from `$_GET['action']` inside the constructor.

**The fix.**
- `GET /` and `GET /g/<token>` serve a bundle and touch no state.
- Redemption is `POST /api/guest/redeem`; acting is `POST /api/guest/act`. Both require a body a
  preview fetcher will not send.
- A preview fetcher that *did* somehow redeem gets a session cookie it never uses. Harmless, now
  that redemption spends nothing.

**Constraint this creates, to be commented in the code.** The GET handlers must stay side-effect
free forever. "Log the visit here" is an obvious and wrong future change — put the reason at the
handler, not in this document only.

### 2. Rate limiting behind the tunnel

Now the **sole** defence for the PIN path, since use counting is gone.

**The trap.** A 6-digit PIN is a 1,000,000-key space. Behind Cloudflare Tunnel or any reverse
proxy, `REMOTE_ADDR` is the *tunnel's* address — identical for every visitor.

**What the wrong version looks like.** Two shapes, both misleading. Key on `REMOTE_ADDR` and one
attacker locks out every legitimate visitor — reported to you as "the gate page stopped working."
Trust `X-Forwarded-For` unconditionally and an attacker sets a fresh value per request, so the
limiter never fires. Crucially, **the second one tests as working**: you try wrong codes from your
phone, you get blocked, you conclude rate limiting works. It does not.

**The fix.** Because `terica.co.za` is on Cloudflare and the tunnel is the *only* route to the
origin, the reliable source is **`CF-Connecting-IP`**, which Cloudflare injects and which a client
cannot forge — Cloudflare overwrites whatever the client sent. Use it in preference to
`X-Forwarded-For`.

- nginx `real_ip_header CF-Connecting-IP`, with `set_real_ip_from` pinned to cloudflared's address.
- **This is safe only for as long as port 8888 is unreachable except through cloudflared.** The
  moment anyone exposes 8888 on the LAN "just to test", forging `CF-Connecting-IP` becomes
  trivial and every limiter silently stops working. That coupling is invisible in the nginx
  config, so it gets a comment there and a line in `docs/security.md`. This is the same failure
  shape as §5 and the two should be verified together.
- Reject any request arriving on 8888 without a `CF-Connecting-IP` header — under the intended
  topology there is no legitimate such request, and it converts the misconfiguration above from
  silent to loud.
- Two independent limiters: per-client-IP exponential backoff, **and** a global failure budget,
  because IP rotation defeats the first.
- Tripping the global budget sends a Telegram alert and refuses PIN redemptions for a cooldown.
  Failing closed for a few minutes is correct; the alternative is a silently open gate.
- **Policy differs by credential kind.** The token path needs only DoS-level limiting — at 128
  bits, guessing is not a threat model. The PIN path carries the strict budget. This is the
  practical payoff of the two-credential decision: the strict limits do not degrade the
  experience of the channel you use most.

### 3. PIN keyspace decay as live grants accumulate

**The trap.** Rate-limit budgets are usually sized against "one million possible PINs." But an
attacker guessing against *any* live PIN succeeds on a hit against any of them. Fifty live
PIN-bearing grants means the effective keyspace is 1,000,000 / 50 = 20,000.

**What the wrong version looks like.** Nothing, for a long time. The system is measurably safe on
day one with three live grants, and quietly unsafe a year later with sixty, having changed no
code. Nobody re-derives the arithmetic.

**The fix.**
- A hard cap on concurrent live PIN-bearing grants, default 20, enforced at mint. Past the cap,
  mint token-only grants — which have no such property at any scale.
- Size the global failure budget against the *effective* keyspace, not the nominal one. At 20 live
  PINs the effective space is 50,000; a budget of 20 failures/hour before cooldown gives an
  expected 2,500 hours to a hit. Write that arithmetic into a comment beside the constant so the
  next person changing it knows what they are trading.
- Surface "live PIN grants: 17 / 20" in the admin UI, so the cap is visible before it is hit.

### 4. Time is now the only control

**The trap.** With use counting dropped, `valid_until` is the entire security model for a grant.
"Valid 2 hours" is entered by me in my timezone, stored by a container with its own `TZ`, checked
against `time()`, and rendered on a visitor's phone in a third.

**What the wrong version looks like.** Credentials expire an hour early or late, but only after a
DST transition, and only for some grants. It presents as intermittent flakiness months after the
bug was written — and an hour *late* means a live credential you believe is dead.

**The fix.** Epoch seconds, UTC, everywhere in the store and on the wire. The admin UI converts
for display only. `valid_until` is computed as `now + duration` at mint time, never parsed from a
wall-clock string. No `strtotime()` equivalent anywhere in the codebase — contrast
`user/actions.php:81-97`. A test that mints, changes `TZ`, restarts, and asserts the expiry
instant is unchanged.

### 5. Admin surface leaking onto the public port

**The trap.** One container serves both the public guest page and the ingress admin panel. A wrong
`listen` directive, a `default_server` on the wrong block, an extra `location` proxying `/api/` on
:8888, or an extra entry under `ports:` publishes the admin API to the internet.

**What the wrong version looks like.** Nothing. Everything works. The admin API is also reachable
at `gate.terica.co.za/api/admin/…` and you have no reason to check. The base ships with both ports
published (`config.json`) and an admin panel with no authentication whatsoever (`default.conf`) —
safe only because most users never forward 8899.

**The fix.** `config.yaml` publishes `8888/tcp` and nothing else. The `:8888` block proxies
`/api/guest/` and no other prefix. `default_server` on 8888 points at the guest root. Admin routes
additionally require the ingress header. A verification step asserts this from off-host after any
nginx change.

---

## Risks, and what mitigates them

1. **A credential is a bearer token, works for its whole window, and will be forwarded.** With use
   counting dropped and no first-use collapse, a credential shared in a family group chat works
   for everyone who has it until it expires. *Mitigated only by:* short windows, an audit row per
   action, and `/revoke`. **Knowingly accepted** — both the use cap and the first-use collapse
   were considered and declined in favour of predictability. The practical consequence is that
   default windows should be minutes, not hours, and the mint form should make short the easy
   choice.

2. **The token link puts a credential in a URL.** History, screenshots, referrers, CDN access
   logs. *Mitigated:* `Referrer-Policy: no-referrer`, zero third-party assets, `replaceState`
   immediately after redemption. Accepted residual: a screenshot of the address bar still leaks
   it — but for a token this is a *deliberate* trade, because 128 bits removes the guessing risk
   that a short URL-borne credential would otherwise carry.

3. **Brute force against the 6-digit PIN.** *Mitigated:* per-IP backoff, global failure budget
   sized against effective keyspace, live-PIN cap, Telegram alert, cooldown. See §2 and §3.
   Accepted: an attacker rotating IPs faster than the global budget refills forces a denial of
   service on the PIN path. Failing closed is the deliberate choice, and the token path is
   unaffected.

4. **The tunnel or HA is down and nobody can get in.** *Not mitigated in software.* Keep a
   physical key or keypad. Stated here so it is a decision rather than a discovery.

5. **`SUPERVISOR_TOKEN` grants the full HA API and cannot be scoped.** `homeassistant_api: true`
   is all-or-nothing — the base uses the same token for `services/*` and `states` alike
   (`user/actions.php:131`, `admin/actions.php:192`). *Mitigated in-process only:* the token lives
   in `addon/token.py`, the guest request path never sees it, and `ha.py` accepts only
   `(grant_id, entity_id, intent)` and resolves everything itself. **Accepted risk:** remote code
   execution in the guest path reaches the whole HA API. This is the largest accepted risk in the
   design and the reason the add-on-over-integration decision went the way it did — the token is
   at least a boundary, rather than being inside HA already.

6. **The Telegram bot dies silently.** Long-poll wedge, network partition, or a 409 from Telegram
   because two pollers run after a restart. *Mitigated:* watchdog with restart, heartbeat surfaced
   in the admin UI, single-instance guard on startup.

7. **`pydantic-core` is Rust, and HA base images are musl/Alpine.** Prebuilt musl wheels for
   `armv7` have historically been patchy; if absent, the Docker build compiles Rust and goes from
   two minutes to twenty. Irrelevant on amd64/aarch64 today, bites on the day this is published.
   *Mitigated:* verified in build step 1, while the image is still trivial to change. Fallback is
   pinning to `linux/amd64` + `aarch64` only, or dropping to plain dataclass validation in
   `schemas.py` — the handlers are thin enough that this is contained.

8. **SQLite corruption on unclean shutdown.** *Mitigated:* WAL mode, single writer process, and
   `/data` is inside HA's own backups. Accepted: no replication. Note this is *better* than the
   bundled-Postgres alternative, where HA's backup would be snapshotting a live data directory.

---

## Build sequence

**Step 1 is the one to validate before anything is built on top of it.**

1. **Skeleton add-on that installs, starts, and reaches HA.** `config.yaml`, `build.yaml`,
   `Dockerfile`, `run.sh`, FastAPI on 127.0.0.1:8080, one route listing entities via
   `SUPERVISOR_TOKEN`, ingress serving a placeholder admin page. **Validate here:** the add-on
   appears from the repo URL, starts, ingress authenticates, the Supervisor API answers, `/data`
   survives a restart, **`pydantic-core` installs from a wheel rather than compiling** (Risk 7),
   **and the add-on's container hostname is resolvable from another add-on** — which decides
   whether 8888 needs publishing at all. Everything downstream assumes all seven. Discovering any
   of them after the frontend exists costs the frontend.
2. **Store and policy.** Schema, migrations, `grants.py` mint/resolve/revoke, `policy.py`,
   `ratelimit.py`. Unit-tested with no HTTP and no HA.
3. **Guest API.** `redeem`, `act`, `state`, session cookie, Pydantic schemas, both limiters with
   per-kind policy. Tested against the store directly before any UI exists.
4. **nginx split and port hygiene.** Both server blocks, the `/api/guest/` path restriction,
   `real_ip_header CF-Connecting-IP`, and publishing no host port if step 1 showed the add-on
   network works. Verify externally before the public route is live.
5. **Guest frontend.** Vite bundle: credential entry, `/g/<token>` auto-submit + `replaceState`,
   entity list, domain controls, live state poll, the distinct gate-did-not-answer state.
   Mobile-first, manifest only — the service-worker plugin must not be in this Vite config.
6. **Admin frontend.** Entity picker, mint form with duration presets and PIN/token/both
   selection, live-grant list with revoke, live-PIN-count indicator, audit log view, bot
   heartbeat. Full PWA here.
7. **Telegram bot.** Chat-ID allowlist, `/new` `/list` `/revoke` with credential-kind flags,
   separate messages per credential, watchdog, alert on global rate-limit trip.
8. **Public exposure.** Tunnel, real-IP configuration, Cloudflare WAF rules, end-to-end from a
   phone on mobile data — not from the LAN, which would not exercise the tunnel path at all.

---

## Verification

Happy paths are the easy half. These are the ones that matter.

1. **A preview fetcher cannot act.** `curl -A "TelegramBot (like TwitterBot)"
   'https://gate.terica.co.za/g/<token>'`, then assert no `act` row in the audit table and no HA
   call. Repeat by sending a real Telegram message to a test chat and watching the gate.
2. **Both credentials resolve to one grant, and revocation kills both.** Mint, redeem with the
   PIN, confirm; revoke; assert the token is now refused too, and that a *held session cookie*
   from before the revocation is also refused on the next `act`.
3. **Real-IP spoofing.** Through the tunnel, send 200 wrong PINs each carrying a distinct forged
   `CF-Connecting-IP` and `X-Forwarded-For`. Assert Cloudflare overwrote the former, the per-IP
   limiter is not fooled, the global budget trips, and a Telegram alert fires.
3b. **The precondition holds.** From a LAN machine, `curl <ha-host>:8888` must fail to connect.
   This is what makes trusting `CF-Connecting-IP` safe; if 8888 is ever reachable directly, test 3
   passes while the limiters are bypassable. Pair this with test 11 — they fail together.
4. **Rate-limit policy differs by kind.** Assert that exhausting the PIN budget does **not** block
   token redemptions, and that the token path has only DoS-level limiting.
5. **Live-PIN cap is enforced.** Mint up to the cap, assert the next PIN-bearing mint is refused
   with a message naming the cap, and that a token-only mint still succeeds.
6. **Cross-grant authorisation.** Mint grant A for `cover.driveway` and grant B for `light.porch`.
   Redeem A, then `act` naming `light.porch`. Assert 403 and an audit row `denied`. This is the
   0.1.33 bug class; it gets a permanent regression test.
7. **Service injection.** With a valid session, post extra fields (`service`, `service_data`,
   an `entity_id` array, a `lock.lock` intent). Assert Pydantic rejects each at the boundary and
   no HA call is made.
8. **Expiry across a timezone change.** Mint valid 30 minutes. Change the container `TZ` and
   restart. Assert the expiry *instant* is unchanged — not the rendered string.
9. **Expiry is enforced server-side.** Redeem, hold the session, wait past `valid_until`, act.
   Assert refusal. Then repeat with the client clock set wrong, to prove nothing is trusted from
   the browser.
10. **The gate-did-not-answer state is distinct.** Point `ha.py` at a dead socket, act, and assert
    the guest sees a different message from an invalid credential, and an audit row `act_failed`.
11. **Admin API is not publicly reachable.** From off-host: `curl gate.terica.co.za/api/admin/…`
    must 404 at nginx, and `:8899`/`:8099` must fail to connect. Re-run after any nginx change.
12. **Bot death is visible.** Kill the poller task. Assert the admin UI shows the bot down within
    a minute and the add-on does not exit.
13. **Restart durability.** Restart mid-window. Assert grants, credentials and audit rows survive
    and in-flight sessions are re-validated rather than silently honoured.
14. **Credential-kind selection.** Mint token-only and assert no PIN exists for that grant and no
    PIN can redeem it; mint PIN-only and assert the same in reverse. Assert a token-only mint does
    not consume a live-PIN slot.
15. **No service worker on the public origin.** Load the guest page and assert
    `navigator.serviceWorker.getRegistrations()` is empty, and that the built guest bundle
    contains no `sw.js` / workbox artefacts. This is a build-output assertion, not a runtime one —
    it must fail the build, because a service worker that ships once persists on devices.

---

## Manual setup outside the codebase

Ordering matters where noted.

1. **Telegram bot.** `@BotFather` → `/newbot`, keep the token. Then `@userinfobot` for your
   **numeric** chat ID. Both go into add-on options. *Before step 5* — the add-on starts without
   them but the bot will not run.
2. **Cloudflare Tunnel.** `terica.co.za` is already on Cloudflare, so this is a Zero Trust →
   Tunnels entry, or the `cloudflared` HA add-on. Route `gate.terica.co.za` → the gate-pin
   add-on's `:8888` **only**. Do not add a route for 8899 or 8099. No port forwarding, and no
   DNS record to create by hand — the tunnel writes its own CNAME.
3. **Real-IP configuration.** Once the tunnel runs, set `set_real_ip_from` to cloudflared's
   address and `real_ip_header CF-Connecting-IP`. *After step 2 — the value is not knowable
   before.* Verify via a log line showing a real visitor IP, not the tunnel's. **Rate limiting is
   wrong until this is done**, and wrong in the direction that tests as working (§2).
4. **Confirm 8888 is not reachable off the tunnel.** From another machine on the LAN,
   `curl <ha-host>:8888` must fail to connect. If cloudflared runs as an add-on this should hold
   with no host port published at all. This is the precondition that makes trusting
   `CF-Connecting-IP` safe — if it does not hold, §2's limiters are bypassable.
5. **Add-on repository.** Settings → Add-ons → ⋯ → Repositories → paste this repo's URL, install,
   configure. Same flow the base's README describes.
6. **Cloudflare-side hardening (optional, free tier).** A WAF rule restricting `gate.terica.co.za`
   to ZA traffic shrinks the attack surface for a physical gate considerably, and one free
   rate-limiting rule adds a layer in front of the add-on's own. *Do not enable Bot Fight Mode* —
   it will challenge legitimate visitors on a page that must work first try.
7. **No certificate to manage.** Cloudflare terminates TLS. Nothing in `/ssl/` is read and
   `config.yaml` maps no `ssl` volume — deliberately unlike the base, whose `tls.conf` and
   `activate_tls` option exist only to serve TLS directly.
8. **Physical fallback.** Confirm a key or keypad exists before relying on this. See Risk 4.

---

## Absences found while studying the base

Design-relevant things that are *not* there, each checked:

- **No long-lived process.** `run.sh:17` is `while true; do sleep 1000; done`. There is nowhere to
  put a Telegram poller in the base's architecture.
- **No dependency manager.** No `composer.json` anywhere; every dependency is an `apk add` line in
  the `Dockerfile`.
- **No tests, no CI.** No `.github/`, no test runner, no test files. 16 files total.
- **No `build.yaml`.** The `Dockerfile` takes `ARG BUILD_FROM` and relies on Supervisor's default
  base image per architecture. Pinning a Python base image is on us — and Risk 7 makes it matter.
- **No database.** Storage is `glob('/data/links/*.json')` (`admin/actions.php:30`) and whole-file
  `file_put_contents`. No locking primitive exists in the codebase to copy.
- **No admin authentication of any kind.** Not weak — absent. `default.conf`'s 8899 block has no
  auth directive and `admin/index.php` has no session check.
- **No rate limiting.** No nginx `limit_req`, no application counter, nothing on the password form
  at `user/index.php:131-137`.
- **No CSRF protection.** Admin mutations are `GET ?action=deleteLink&id=…` (`admin/actions.php:69`).
- **No request validation.** `$_POST['dynamic_field']` is iterated straight into the stored service
  payload (`admin/actions.php:105-107`).
- **No entity concept.** Searched: `entity_id` appears only as a free-text field inside
  `service_call_data`. There is no model of "an entity this link may touch".

Design properties of *this* plan that are enforced by absence, and are easy to erode:

- **Nothing on the guest request path ever holds `SUPERVISOR_TOKEN`.** Enforced by keeping it in
  `addon/token.py` and passing a provider into `ha.py`. A future "just import the client here"
  quietly destroys this.
- **`gate_pin/` imports nothing Supervisor-aware and nothing FastAPI-aware.** Enforced by a grep
  test. This is the entire cost of the later integration.
- **No GET handler writes.** Enforced by a comment and a test.
- **No credential is ever stored in a form that can be read back.** Only HMACs are persisted; the
  PIN and token exist in plaintext exactly once, in the mint response. There is deliberately no
  "show me the code again" feature — re-mint instead.
- **`grants.valid_until` is NOT NULL.** A permanent credential cannot be represented.
- **No service worker is ever registered on the public origin.** Enforced by the guest Vite config
  not containing the plugin, plus a build-output assertion. A service worker that ships once
  persists on visitors' devices whether or not the next deploy removes it, so this is one of the
  few properties here that cannot be fixed forward.
- **No TLS material is read or stored by the add-on.** `config.yaml` maps no `ssl` volume — unlike
  the base, whose `activate_tls` option and `tls.conf` exist to serve TLS directly. Cloudflare
  terminates; the add-on speaks plain HTTP and can only be reached through the tunnel.

---

## Documentation to produce when this is built

- `gate-pin/README.md` — install, options, and the tunnel setup. The base's README is the shape to
  match: what it is, how to use it, install instructions.
- `gate-pin/CHANGELOG.md` — the base keeps a strict `## [x.y.z] - date` + `### feature|bugfix`
  format going back to 0.0.1. Match it; the add-on store renders it.
- `docs/security.md` — the threat model, the accepted risks above, the two-credential rationale,
  and the reasoning behind add-on-over-integration. This is the document that stops someone
  "simplifying" the port split, the GET-is-inert rule, or the live-PIN cap.
- `repository.json` — name, url, maintainer. Copy the base's shape exactly.
