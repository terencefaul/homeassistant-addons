# Gate PIN

Time-limited guest access to chosen Home Assistant entities, via a 6-digit PIN
you can read over the phone or a link you send. Both resolve to one grant with
one window, one entity list and one revocation.

**Installing and configuring it: [DOCS.md](DOCS.md)** — the same text Home
Assistant shows in the add-on's Documentation tab.

## What it does

- Mint a credential for chosen entities, for a set window, starting now or later
- Choose a PIN, a link, or both. The result screen shows them once, with a QR
- A mobile-first guest page: live entity state, one large button each
- Saved presets, so `/new plumber` is the whole command
- Telegram bot to mint, list, extend and revoke from your phone
- Audit log of every redemption, action, refusal and wrong code
- Rate limiting, a live-PIN cap, and a lockout that alerts you
- Camera streams in the admin panel — never on the public guest page

## Running it locally

You do not need Home Assistant to use this. `scripts/dev-run.sh` starts the real
container against a stubbed Supervisor API, so you get the same nginx, the same
port split and the same application:

```
cd gate-pin
./scripts/dev-run.sh          # build and start
./scripts/dev-run.sh stop     # tear down
```

Then open the **admin panel at http://127.0.0.1:8099/** and the **guest page at
http://127.0.0.1:8888/**. Mint a credential in the admin panel and use it on the
guest page. The stub entities -- a driveway gate, a porch light, a front door
lock, a camera -- really do change state when you operate them.

Two things differ from a real install, deliberately:

- `require_cf_header` is off, because there is no Cloudflare in front of you. On
  a real install it stays **on**.
- The admin panel is reachable directly on 8099. On a real install that port is
  published nowhere and only Home Assistant ingress can reach it.

## Testing

```
# unit and API tests -- 58 of them, covering failure paths
cd gate-pin/frontend && npm install && npm run build
python3 -m pytest tests -q

# end-to-end against a real container: port split, headers, startup ordering,
# mint-then-redeem-then-act, revocation, rate limiting
./scripts/smoke.sh
```

Some things can only be checked on a real Home Assistant OS install: that the
add-on appears from the repository URL, that ingress authenticates the panel,
that the Supervisor API answers, that `/data` survives a restart, and whether
`cloudflared` can reach this container without publishing port 8888 at all.

Three checks are worth doing by hand once the tunnel is live:

1. **Send yourself a link over Telegram** and confirm the gate does not open
   when the preview loads.
2. **From a LAN machine, `curl <ha-host>:8888`** -- it must fail to connect.
   That is the precondition that makes trusting `CF-Connecting-IP` safe.
3. **Mint a credential, change the container timezone, restart**, and confirm
   the expiry instant did not move.

The design record, including the failure analysis behind these choices, is in
`docs/plans/gate-pin-addon.md`.
