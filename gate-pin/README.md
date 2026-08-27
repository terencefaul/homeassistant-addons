# Gate PIN

Give a visitor a short-lived credential — a 6-digit PIN you can read over the
phone, or a link you send them — that operates only the entities you chose,
only for as long as you allow.

## What it does

Mint a grant from the Home Assistant sidebar panel or from Telegram. The
visitor opens your public URL, presents the PIN or taps the link, and sees only
the entities on that grant, with live state and one tap each. When the window
closes, both credentials die. Revoke early and they die immediately, including
in a tab that is already open.

## Install

1. Settings → Add-ons → ⋯ → Repositories → add this repository's URL.
2. Install **Gate PIN**, then open its Configuration tab.
3. Set `external_base_url` to the public URL you will use.
4. Start it. The panel appears in the sidebar.

## Making it reachable

The add-on serves plain HTTP on port 8888 and holds no certificates. Put
Cloudflare Tunnel in front of it:

1. In Cloudflare Zero Trust, create a tunnel and route your hostname to this
   add-on's `:8888`. **Do not route 8099.**
2. Leave `8888/tcp` unmapped in the add-on's Network settings when `cloudflared`
   runs as an add-on on the same machine — it reaches this container over the
   add-on network, and the port never binds on the host at all.
3. Set `trusted_proxy_cidr` to the range `cloudflared` connects from.

`require_cf_header` (on by default) refuses any request to the guest port that
did not arrive with Cloudflare's `CF-Connecting-IP` header. Under the intended
topology there is no legitimate request without it, so this turns "someone
exposed 8888 on the LAN" from a silent failure into a loud one — which matters,
because a forgeable client address makes every rate limit stop working while
still appearing to work under test.

## Telegram

Get a bot token from `@BotFather` and your **numeric** chat ID from
`@userinfobot`. Put both in the add-on options. Chat IDs, never `@usernames`: a
username can be released and re-registered by somebody else.

```
/new 2h cover.driveway          mint a grant
/new plumber                    mint from a preset
/new 2h cover.driveway --token-only
/list                           live grants
/revoke <id>                    kill a grant now
/extend <id> 1h                 push out a live grant
```

The PIN and the link arrive as separate messages, so forwarding the link to a
visitor does not also forward the PIN.

## Options

| Option | Meaning |
|---|---|
| `external_base_url` | Public URL, used to build link credentials |
| `telegram_bot_token` | From `@BotFather`. Empty disables the bot. |
| `telegram_chat_ids` | Numeric chat IDs allowed to command the bot |
| `notify_service` | e.g. `notify.mobile_app_phone`, for alerts |
| `pin_length` | 6–10. Longer is safer and harder to read out. |
| `max_live_pin_grants` | Cap on concurrent live PIN grants |
| `trusted_proxy_cidr` | Where `cloudflared` connects from |
| `audit_retention_days` | How long activity is kept |
| `require_cf_header` | Refuse guest requests without `CF-Connecting-IP` |

## Things worth knowing

- **Credentials are shown once.** Only a keyed hash is stored, so no screen and
  no endpoint can show a code again. Lose it and re-mint.
- **A credential is a bearer token.** It works for anyone holding it until it
  expires. Keep windows short; revoke when the visit is over.
- **The live PIN cap exists for a reason.** Guessing succeeds against *any*
  live PIN, so the effective keyspace shrinks as the number of live PIN grants
  grows. At the cap, mint link-only grants — a 192-bit token has no such
  property at any scale.
- **A tunnel or Home Assistant outage means nobody gets in.** Keep a physical
  key.

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
cd .. && python3 -m pytest tests -q

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
