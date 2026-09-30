# Terica Home Assistant add-ons

A Home Assistant add-on repository, published at
https://github.com/terencefaul/homeassistant-addons

## Layout

Each add-on is a **top-level folder containing a `config.yaml`**. That folder is
the Docker build context Supervisor uses, so anything the `Dockerfile` copies
must live inside it. Nothing outside the folder is available at build time.

```
repository.json      names this repository to Home Assistant
README.md            landing page, lists the add-ons
scripts/             repo-level tooling; every script takes an add-on name
docs/plans/          design records, one per add-on -- durable
_build_plan/         PRD and milestone prompts -- temporary, see below
gate-pin/            an add-on
  DOCS.md            rendered by Supervisor as the add-on's Documentation tab
  README.md          the GitHub-facing view; not shown anywhere in Home Assistant
```

Operator-facing documentation belongs in the add-on's `DOCS.md`. That is the
only one users see from inside Home Assistant, at the moment they are looking
at the configuration screen.

Adding an add-on means adding one folder with a `config.yaml`. `scripts/` and
the CI workflow discover add-ons by globbing for it, so nothing at the root
needs editing.

Per-add-on tooling stays inside the add-on: `gate-pin/tests/`,
`gate-pin/scripts/smoke.sh` and `gate-pin/scripts/stub-supervisor.py` all test
that add-on specifically and are excluded from its image by `.dockerignore`.

A top-level folder **without** a `config.yaml` is not an add-on -- it is a
Home Assistant *integration* (`custom_components/<domain>/`) or other repo
tooling. Integrations have no Docker build context and are invisible to
`scripts/` and the add-on CI job (both glob for `config.yaml`).

Unlike an add-on, an integration meant for HACS distribution does **not**
live in this repo as a folder: HACS requires `custom_components/<domain>/`
at the installed repo's root, which a monorepo subfolder can't satisfy
without a synthetic mirror. Such integrations get their own repo instead.
See `whatsapp-waha-integration` below for the one built so far.

## Add-ons

### gate-pin

Time-limited guest access to chosen entities via a PIN or a tokenised link.

- `docs/plans/gate-pin-addon.md` -- the engineering plan. **Durable.** Carries
  the decisions table, the failure analysis, the rejected alternatives, and
  `file:line` references into the reference add-on
  (`TekniskSupport/homeassistant-addons` @ `020d61c`). This is the authority on
  *why*, and on the security-critical mechanisms.

Constraints in that plan which are easy to erode and must not be:

- `gate_pin/` imports nothing FastAPI-aware or Supervisor-aware. Enforced by
  `tests/test_portability.py`.
- The guest bundle ships **no service worker**. A separate Vite config, plus a
  build-output assertion. A service worker that ships once persists on visitors'
  devices even after it is removed -- it cannot be fixed forward.
- No `GET` route acts. `/` and `/g/<token>` are served as static files and never
  reach application code.
- `/api/admin/*` is unreachable on the public port, by nginx configuration
  rather than an application check.

## Integrations

### whatsapp-waha-integration

A Home Assistant custom integration (`custom_components/whatsapp_waha/`)
connecting to a self-hosted WAHA (WhatsApp HTTP API) server. Milestones 1
and 2 (connect/link/receive, send/pace/notify) were built here, then moved
out to its own repo, https://github.com/terencefaul/whatsapp-waha-integration,
so it can be installed via HACS -- see that repo for the code, tests,
`_build_plan/`, and its own copy of the engineering plan.

- `docs/plans/whatsapp-waha-integration.md` -- kept here as the historical
  record of the design decisions made while it was still developed in this
  monorepo (the scaffold defect list, webhook self-registration and
  send-queue designs, risks knowingly accepted). The live copy moved with
  the code; this one no longer gets updated.

## `_build_plan/`

The `_build_plan/` folder contains the initial PRD and per-milestone prompts
used to scaffold this codebase during its initial build-out phase. These files
are **temporary** -- documentation and guidance only. They are **not**
functional: no code, configuration, or runtime logic should import, reference,
or depend on anything inside `_build_plan/`.

Do not treat `_build_plan/` as long-living documentation. Once the initial
milestones are complete, this folder is expected to be deleted.

**Delete it when:** the five checks marked `NOT VERIFIABLE HERE` in
`_build_plan/milestones/1-live-gate-access/milestone-log.md` have been confirmed
on a real Home Assistant install. They are the only live content left in here;
everything else is history, and git preserves it either way. Until then those
five are the reason this folder still exists.

`docs/plans/` is **not** temporary and should outlive it.
