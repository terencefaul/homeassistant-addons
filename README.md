# Terica Home Assistant add-ons

A Home Assistant add-on repository.

## Installing

Settings → Add-ons → Add-on store → ⋯ → **Repositories**, then paste:

```
https://github.com/terencefaul/homeassistant-addons
```

The add-ons below then appear in the store.

## Add-ons

### [Gate PIN](gate-pin/) — time-limited guest access to chosen entities

Give a visitor a short-lived credential — a 6-digit PIN you can read over the
phone, or a link you send them — that operates only the entities you chose, only
for as long as you allow. Mint and revoke from a Telegram bot or from a panel in
the Home Assistant sidebar; the visitor gets a mobile page and access to nothing
else.

Built for a driveway gate, but nothing in it is gate-specific: covers, locks,
lights, switches, scenes and scripts are all supported.

[Documentation →](gate-pin/DOCS.md) · [Overview and development →](gate-pin/README.md)

## Repository layout

Each add-on is a top-level folder, and that folder is the Docker build context
Supervisor uses — anything the `Dockerfile` copies must live inside it.

```
repository.json         names this repository to Home Assistant
scripts/                repo-level tooling, takes an add-on name
  deploy.sh             copy an add-on to /addons and rebuild it
  release.sh            bump an add-on's version, changelog, commit, push
docs/plans/             design records, one per add-on
gate-pin/               an add-on: config.yaml, Dockerfile, and its build context
```

Adding another add-on means adding one folder with a `config.yaml`. The scripts
and the CI workflow discover it automatically; nothing at the root needs editing.

## Development

```bash
cd gate-pin/frontend && npm install && npm run build
cd .. && python3 -m pytest tests -q     # 58 tests
./scripts/smoke.sh                       # 32 end-to-end assertions in a container
./scripts/dev-run.sh                     # run it locally, no Home Assistant needed
```

## Licence

MIT.
