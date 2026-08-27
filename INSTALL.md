# Installing Gate PIN on Home Assistant

Two ways in. Start with the local folder — it needs no git remote, no decisions,
and it is the fastest way to find out whether the five things that can only be
tested on a real install actually work.

---

## Path A — local add-on folder (start here)

Supervisor picks up any add-on placed in `/addons` on the Home Assistant machine
and offers it under **Local add-ons**. Nothing is published, nothing is public.

**1. Get a way to write to `/addons`.** Any one of:

- **Samba share** add-on — mounts `\\homeassistant\addons` from your Mac's Finder
  (Go → Connect to Server → `smb://homeassistant.local`)
- **Advanced SSH & Web Terminal** add-on — then `scp` into it
- **Studio Code Server** add-on — edit in place

**2. Copy the add-on folder** — just `gate-pin/`, not the whole repo:

```bash
# with the Samba add-on mounted
cp -R gate-pin /Volumes/addons/gate-pin

# or over SSH
scp -r gate-pin root@homeassistant.local:/addons/
```

Do not copy `gate-pin/frontend/node_modules` or `gate-pin/frontend/dist` — they
are gitignored and the container builds them itself.

**3. Settings → Add-ons → Add-on store → ⋯ → Check for updates.**
Gate PIN appears under **Local add-ons**. Install it.

The first install **builds the image on your Home Assistant machine**, including
a Node stage that compiles the React bundles. See *Build time* below.

**4. Configure it** before starting — at minimum `external_base_url`.
Then start it, and the panel appears in the sidebar.

---

## Path B — a git repository

Once it works locally, a repository makes updates a click instead of a copy.

**1. Push this repo to GitHub.** `repository.json` at the root is what makes it
an add-on repository, and its `url` must match the real remote.

**2. Settings → Add-ons → Add-on store → ⋯ → Repositories**, paste the repo URL,
add. Gate PIN appears as its own card.

**3. Updates** are then: push a commit that bumps `version:` in
`gate-pin/config.yaml`, and Home Assistant offers the update.

**The repository must be reachable without credentials.** Supervisor clones it
anonymously — a private GitHub repo will fail to add. If you want it private,
stay on Path A.

---

## Build time, and whether your hardware can do it

Neither path pulls a prebuilt image. Supervisor runs `docker build` from
`gate-pin/Dockerfile` on the Home Assistant machine, and that includes:

- a Node stage: `npm install` (~200 packages) then two Vite builds
- a Python stage: `pip install` of FastAPI, Pydantic, httpx

| Hardware | Expectation |
|---|---|
| Intel/AMD mini PC, NUC, VM | 2–4 minutes. Fine. |
| Raspberry Pi 5, 8 GB | 5–10 minutes. Fine. |
| Raspberry Pi 4, 4 GB | 10–20 minutes. Works, but slow. |
| Raspberry Pi 3, or 2 GB or less | Likely to fail — the Node stage is the problem. |

You need roughly **1.5 GB of free disk** during the build.

If your hardware cannot do it, the answer is to build images in CI and publish
them, then point `config.yaml` at them with an `image:` key — installs become a
pull instead of a build. Ask and I will set that up.

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
