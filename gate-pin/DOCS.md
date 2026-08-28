# Gate PIN

Give a visitor a short-lived credential — a 6-digit PIN you can read over the
phone, or a link you send them — that operates only the entities you chose, only
for as long as you allow.

## Setting it up

Do these in order. The add-on will start without any of them, but the bot will
not run and nobody outside your network can reach the guest page.

### 1. Telegram (optional, but it is how you will actually use this)

1. Message `@BotFather`, send `/newbot`, follow the prompts, keep the token.
2. Message `@userinfobot`. It replies with your **numeric** chat ID.
3. Put both in the configuration below.

Chat IDs, never `@usernames`: a username can be released and re-registered by
somebody else, which would hand your gate to a stranger.

### 2. A public route

This add-on serves plain HTTP on port 8888 and holds no certificates. It expects
**Cloudflare Tunnel** in front of it — and that is not merely a convenience.

The rate limiting is the only thing between a 6-digit PIN and your gate, and it
depends on the visitor's address being unforgeable. That holds because the
origin cannot be reached except through the thing that sets the header. A tunnel
opens no inbound port, so there is no way around it. A port-forwarded reverse
proxy leaves your address reachable directly, and an attacker who finds it can
bypass the proxy and forge the header — while every test you run still passes.

1. Install the **cloudflared** add-on.
2. In **Cloudflare Zero Trust → Networks → Tunnels**, create a tunnel and put
   its token into that add-on.
3. Point a hostname at **this add-on's port 8888**. One tunnel serves as many
   hostnames as you like, so an existing tunnel that already exposes Home
   Assistant needs no second tunnel — just another route.

   Using the community `cloudflared` add-on, that is its `additional_hosts`
   option:

   ```yaml
   external_hostname: ha.example.com          # Home Assistant itself, if you expose it
   additional_hosts:
     - hostname: gate.example.com
       service: http://<gate-pin-hostname>:8888
   ```

   Or, if you manage routes in the Cloudflare dashboard, add a public hostname
   with service type HTTP and URL `http://<gate-pin-hostname>:8888`.

   `<gate-pin-hostname>` is assigned by Supervisor. **This add-on's panel prints
   the exact URL for you** — open it and look at **Settings → Point your tunnel
   here**, which has a copy button. It is not guessable, so do not invent it.

   **Do not route 8099** — that is the admin panel, and Home Assistant already
   protects it through ingress. Routing it would put your admin interface on the
   public internet with no authentication in front of it.

4. Cloudflare creates a **proxied CNAME** for the hostname. If an A record for
   that name already exists, delete it first — it will otherwise keep answering
   and the tunnel will appear not to work.
5. Leave `8888/tcp` **unmapped** in this add-on's Network settings.
   `cloudflared` reaches this container over the add-on network, so the port
   never binds on the host at all — which is the precondition that makes
   trusting `CF-Connecting-IP` safe.
6. Set `trusted_proxy_cidr` to the range `cloudflared` connects from.

**Think twice before restricting the guest hostname by country, and do not
enable Bot Fight Mode on it.** Both look like cheap hardening and both lock out
real visitors: plenty of people run a VPN on their phone permanently, and their
traffic arrives from another country and from a datacentre address. The failure
is opaque — a Cloudflare block page, not your gate page — so the visitor has no
idea what to do. The defences that matter here are the 192-bit link token, the
rate limiting and the short window, and none of them care where the request came
from.

**Do not put Cloudflare Access in front of the guest hostname.** It would demand
a login before a visitor ever sees the PIN box, which defeats the point. Access
on your other hostnames is fine — just not this one.

**Checking it worked.** `curl -sI https://your-hostname/` should return
`Referrer-Policy: no-referrer`. That header is set by this add-on's nginx and
nothing else, so it is proof the request reached the add-on rather than your
router, an old DNS record, or another proxy.

**The chat IDs are a list.** A bare number is rejected with *"Invalid list for
option 'telegram_chat_ids'"*. In YAML mode:

```yaml
telegram_bot_token: "1234567890:AA..."
telegram_chat_ids:
  - 1590213344
```

Note the `- ` and the indent. In the visual editor, use the **＋** to add an
entry. It is a list so you can let more than one person mint.

**If you ever paste a token somewhere it should not be**, `@BotFather` →
`/revoke` issues a new one. The old token does not let anyone mint — that needs
a chat ID on the allowlist — but it does let them send messages as your bot and
seize the polling slot, which breaks minting.

### 3. Configure and start

Set `external_base_url` to the public URL from step 2 — it is what link
credentials are built from. Then start the add-on; the panel appears in your
sidebar.

## Configuration

| Option | Default | What it does |
|---|---|---|
| `external_base_url` | `https://gate.example.com` | Your public URL. Link credentials are built from it, so a wrong value produces links that go nowhere. |
| `telegram_bot_token` | empty | From `@BotFather`. Empty disables the bot entirely. |
| `telegram_chat_ids` | empty | Numeric chat IDs allowed to command the bot. **A list, even for one person** — see below. Anything else is ignored silently. |
| `notify_service` | empty | e.g. `notify.mobile_app_your_phone`. Where lockout and bot-failure alerts go. Falls back to a persistent notification. |
| `pin_length` | `6` | 6–10 digits. Longer is safer and harder to read out over a phone. |
| `max_live_pin_grants` | `20` | Cap on concurrent live PIN grants. See *Why the PIN cap exists*. |
| `trusted_proxy_cidr` | `172.30.32.0/23` | Where your tunnel connects from. Rate limiting is wrong until this is right. |
| `audit_retention_days` | `90` | How long activity is kept before pruning. |
| `require_cf_header` | `true` | Refuse guest requests that did not arrive with Cloudflare's `CF-Connecting-IP`. Leave this on. |
| `picker_domains` | cover, switch, light, lock, scene, script, camera | Which domains the entity picker offers. A convenience that cuts the noise — it does **not** narrow what a grant may reach, which the server-side policy still governs. |

## Your own control page

The panel opens on **Control**: your camera above the controls you use most, with
the same large buttons a visitor gets. It is yours — reached through Home
Assistant, not through the public hostname — which is why it can show a camera
when the guest page never does.

Tap **Edit this page** to choose cameras and controls, and order each list with
the ↑ ↓ buttons. The first control is the one you reach for most.

With more than one camera they sit in a grid, two across on a wider screen. Tap
any of them to fill the width, and tap again to go back — on a phone the grid is
tight, and the one you want a proper look at is usually the one something is
happening on.

Because Control is the first tab, installing the panel to your home screen opens
straight into it.

## Branding

**Settings → Branding.** Set a **property name** and upload a **logo**, and both
appear in the header of the guest page, so a visitor sees whose gate they are at
rather than a generic tool.

The accent colour applies to every button on the guest page. The default theme is
what new grants start with — you can still override it per grant when minting.

Logos are PNG, JPEG, SVG or WebP up to 2 MB, served by the add-on itself. They
are never hotlinked: a request to an outside host from the guest page would carry
the link token out in the `Referer` header.

## Using it

**From the panel.** Mint gives you a label, a searchable entity picker, duration
presets, an optional later start, a theme, and a choice of PIN, link, or both.
The result screen shows the PIN, the link, and a scannable QR — **once**.

**From Telegram.** Send `/menu` and you get a button per saved preset — one tap
mints. Typing entity ids one-handed at a gate is the interface this replaces, so
**create your presets first** in the panel; the menu is built from them.

The reply carries **+1 hour** and **Revoke** buttons for that grant. `/list`
gives **New link**, **New PIN** and **Revoke** per live grant, so you can
re-send a credential from your phone without opening the panel.

Typed commands still work, and are better when you want something ad hoc:

```
/menu                           buttons for your presets
/new 2h cover.driveway          mint a grant
/new plumber                    mint from a saved preset
/new 2h cover.driveway --token-only
/list                           live grants
/revoke <id>                    kill a grant now
/extend <id> 1h                 push out a live grant
```

The PIN and the link arrive as **separate messages**, so forwarding the link to
a visitor does not also forward the PIN.

**What the visitor sees.** Your public URL, a box for the code — or, from a
link, no typing at all. Then only the entities on that grant, with live state
and one large button each. When the window closes, both credentials stop working.

## Things worth understanding

**Credentials are shown once.** Only a keyed hash is stored, so no screen and no
endpoint can show a code again — not even to you. This is deliberate.

To send one again, use **New PIN** or **New link** on the grant in the Grants
tab. That issues a fresh key to the *same* grant: same window, same entities,
still one revocation. The previous key of that kind stops working, which is the
safer default — you are re-issuing because the first one did not arrive, and a
credential that went astray should not stay live.

**A credential is a bearer token.** It works for anyone holding it until it
expires. There is no use counting — time is the only control. Keep windows
short, and revoke when the visit is over.

**Why the PIN cap exists.** Someone guessing PINs succeeds against *any* live
PIN, so the effective keyspace is `10^length ÷ live PIN grants`. At six digits
with twenty live grants that is 50,000, not a million. The panel shows the count
so you can see it. At the cap, mint **link-only** grants — a link token is 192
bits and has no such property at any scale.

**A lockout never affects links.** Repeated wrong PINs lock PIN entry for a
cooldown and alert you. Link credentials keep working throughout, so you can
still let someone in during an attack.

**Cameras are admin-only.** You can attach a camera to a grant and stream it in
the panel, but it is never rendered on the public guest page.

**If the tunnel or Home Assistant is down, nobody gets in.** Keep a physical key.

## Putting the panel on your phone

The admin panel is a progressive web app, so it installs to a home screen. There
is nothing to enable — it is built in.

- **iPhone:** open Home Assistant in Safari, go to the Gate PIN panel, then
  Share → **Add to Home Screen**.
- **Android:** Chrome menu → **Install app**.

Two honest caveats. The panel lives behind Home Assistant ingress, so it needs
an authenticated Home Assistant session in that browser — if you are logged out,
you get Home Assistant's login screen. And the ingress path can change, which
would leave the installed icon pointing somewhere stale; re-add it if that
happens.

For day-to-day use the Telegram bot is the better phone interface, which is why
`/menu` exists. The panel is where you set things up.

## Checking the install

Five things can only be confirmed on a real install:

1. The add-on installs and starts.
2. The sidebar panel opens and is behind your Home Assistant login.
3. **The Mint tab lists your real entities.** This one check proves the
   Supervisor token, the network path and the permissions all work.
4. A grant you minted survives an add-on restart.
5. `cloudflared` reaches the container with `8888/tcp` left unmapped.

Then three worth doing once the tunnel is live:

- **Send yourself a link over Telegram.** The gate must not open when the
  message preview loads.
- **From a machine on your LAN, `curl <ha-host>:8888`.** It must fail to
  connect. That is the precondition that makes trusting `CF-Connecting-IP` safe.
- **Mint a credential, change the container timezone, restart.** The expiry
  instant must not move.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Guest page loads, every action fails | Home Assistant unreachable. Check **Settings → Health** in the panel. |
| "This endpoint is only reachable through the configured tunnel" | The request did not arrive with `CF-Connecting-IP`. You are hitting it directly rather than through the tunnel. |
| Links point at the wrong host | `external_base_url` is wrong. It does not change existing grants — re-mint. |
| Bot shows as stopped in Health | Token wrong, or a second copy of the add-on is polling the same token. Telegram refuses both. |
| Everyone gets rate-limited at once | `trusted_proxy_cidr` is wrong, so every visitor shares the tunnel's address. |
| A code "isn't recognised" that should work | Check the audit log. A scheduled grant says *isn't active yet*; an expired one says *expired*. Those are different messages on purpose. |
| A new version is published but no Update button appears | Supervisor caches its clone of the repository. **Add-on store → ⋮ → Check for updates**. If it still does not appear, the add-on may have been installed from `/addons` rather than the repository — those are different add-ons to Supervisor and a local one never shows updates. |

## Reporting problems

https://github.com/terencefaul/homeassistant-addons/issues
