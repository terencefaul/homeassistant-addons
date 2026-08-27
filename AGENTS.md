# Gate PIN

Published as a Home Assistant add-on repository at
https://github.com/terencefaul/homeassistant-addons

A Home Assistant add-on giving visitors time-limited access to chosen entities via a PIN or a tokenised link.

## Where the design lives

- `docs/plans/gate-pin-addon.md` — the engineering plan. Durable. Carries the decisions table, the failure analysis, the rejected alternatives, and `file:line` references into the reference add-on (`TekniskSupport/homeassistant-addons` @ `020d61c`). This is the authority on *why*, and on the security-critical mechanisms.
- `_build_plan/` — the PRD and milestone prompts. Temporary, see below.

## `_build_plan/`

The `_build_plan/` folder contains the initial PRD and per-milestone prompts used to scaffold this codebase during its initial build-out phase. These files are **temporary** — they exist for documentation and guidance only. They are **not** functional: no code, configuration, or runtime logic in this codebase should import, reference, or depend on anything inside `_build_plan/`.

Do not treat `_build_plan/` as long-living documentation for the codebase. The codebase will evolve past the assumptions and decisions captured here. Once the initial milestones are complete, this folder is expected to be deleted.

`docs/plans/gate-pin-addon.md` is **not** temporary and should outlive `_build_plan/`.
