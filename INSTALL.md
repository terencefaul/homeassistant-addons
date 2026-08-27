# Installing Gate PIN on Home Assistant

Home Assistant OS on Proxmox, repository kept private. That combination means
the **local add-on folder** is the route: Supervisor clones add-on repositories
anonymously, so a private GitHub repo cannot be added to the store at all.

Nothing is published and no git remote is needed. Building on an x86 VM takes
2–4 minutes.

---

## Install

**1. Get write access to `/addons`.** Either:

- **Samba share** add-on — then in Finder, Go → Connect to Server →
  `smb://homeassistant.local`, and mount `addons`
- **Advanced SSH & Web Terminal** add-on — then deploy over SSH

**2. Deploy:**

```bash
./gate-pin/scripts/deploy.sh /Volumes/addons           # mounted Samba share
./gate-pin/scripts/deploy.sh root@homeassistant.local  # SSH add-on
```

It copies `gate-pin/` and nothing else — `node_modules` and `dist` are excluded,
because the container builds the frontend itself and host-built artefacts would
poison the image. About 620 KB goes across.

**3. Settings → Add-ons → Add-on store → ⋯ → Check for updates.**
Gate PIN appears under **Local add-ons**. Install it.

The first install runs `docker build` on the Proxmox VM: a Node stage compiling
the React bundles, then a Python stage. Two to four minutes, then mostly cached.

**4. Configure before starting.** At minimum `external_base_url` — the public URL
your tunnel will serve. Then start it; the panel appears in the sidebar.

## Updating

```bash
./gate-pin/scripts/deploy.sh /Volumes/addons
```

Then open the add-on in Home Assistant and click **Rebuild**. Bumping `version:`
in `gate-pin/config.yaml` also makes Home Assistant offer it as an update.

---

## If you later make the repository public

The add-on store route becomes available and updates become a click rather than
a deploy:

1. `repository.json` at the repo root is what makes it an add-on repository —
   set its `url` to the real remote first.
2. Settings → Add-ons → Add-on store → ⋯ → Repositories → paste the URL.
3. Push a commit that bumps `version:` and Home Assistant offers the update.

Before doing that, note the real hostname still appears in `docs/plans/` and
`_build_plan/` (the shipped add-on defaults were already neutralised). Worth
scrubbing, since a public repo stating that a particular hostname opens a gate
is a signpost.

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
