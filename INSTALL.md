# Installing Gate PIN on Home Assistant

Published as an add-on repository at
**https://github.com/terencefaul/homeassistant-addons**

Home Assistant OS on Proxmox builds this in two to four minutes.

---

## Install

**1. Settings -> Add-ons -> Add-on store -> ... (top right) -> Repositories.**
Paste:

```
https://github.com/terencefaul/homeassistant-addons
```

Add, then close. A **Terica Home Assistant add-ons** section appears with a
**Gate PIN** card.

**2. Install it.** The first install runs `docker build` on the Proxmox VM: a
Node stage compiling the React bundles, then a Python stage. Two to four
minutes, then mostly cached.

**3. Configure before starting.** At minimum `external_base_url` — the public
URL your tunnel will serve. Then start it; the panel appears in the sidebar.

---

## Updating

From your working copy:

```bash
./scripts/release.sh gate-pin patch "What changed"
```

That bumps `version:` in `config.yaml`, writes a CHANGELOG entry, commits and
pushes. Home Assistant compares that version against the installed one, so the
bump *is* the update mechanism — nothing else is needed.

In Home Assistant: **Add-on store -> ... -> Check for updates**, and the Gate
PIN card offers an **Update** button.

`minor` and `major` work too, as does an explicit `0.3.0`.

---

## Working on it without releasing

For iterating, skip the repository entirely and push straight to `/addons`:

```bash
export HA_URL=http://homeassistant.local:8123
export HA_TOKEN=...    # Profile > Security > Long-lived access tokens

./scripts/deploy.sh gate-pin /Volumes/addons --rebuild
```

That copies the changed files and rebuilds and restarts the add-on through the
Home Assistant API, with nothing to click and no commit. It installs as a
**Local add-on**, separate from the store copy — run one or the other, not both.

Put those exports in a `.env`; it is gitignored, and the token is equivalent to
your Home Assistant login.

Requires the **Samba share** add-on (Finder -> Go -> Connect to Server ->
`smb://homeassistant.local`) or the **Advanced SSH & Web Terminal** add-on.

---


## Before you start it

Have these ready — the add-on starts without them, but the bot will not run and
nobody outside can reach the guest page.

| Needed | Where from |
|---|---|
| Telegram bot token | `@BotFather` → `/newbot` |
| Your numeric chat ID | `@userinfobot` |
| Cloudflare tunnel | Zero Trust → Tunnels → route your hostname to this add-on's `:8888` |
| `notify.*` service name | Developer Tools → Actions, search `notify.` |

---

## The five things to confirm on first install

These could not be tested anywhere else. If any fails, stop and say so.

1. **It appears and installs** — from Local add-ons, or from your repository URL.
2. **Ingress authenticates the panel** — the sidebar entry opens the admin UI,
   and it is behind your Home Assistant login.
3. **The Supervisor API answers** — the Mint tab lists your *real* entities. This
   one check proves the token, the network path and the permissions all work.
4. **`/data` survives a restart** — mint a grant, restart the add-on, and the
   grant is still in the Grants tab.
5. **cloudflared reaches the container without publishing port 8888** — leave the
   port unmapped in the add-on's Network settings and point the tunnel at the
   add-on's hostname. If that works, 8888 never binds on the host at all, which
   is what makes trusting `CF-Connecting-IP` safe.

Then three checks that need the tunnel live:

- **Send yourself the link over Telegram.** The gate must not open when the
  message preview loads.
- **From a machine on your LAN, `curl <ha-host>:8888`.** It must fail to
  connect. If it succeeds, the rate limiting is bypassable while still passing
  every test.
- **Mint a credential, change the container timezone, restart.** The expiry
  instant must not move.
