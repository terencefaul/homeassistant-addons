# Milestone 1 — Live gate access

You are entering plan mode to plan and then build milestone 1 of this project.

## Context

- Read `@_build_plan/prd.html` for the full project context, scope, data model, and tech stack.
- Read `@docs/plans/gate-pin-addon.md` — the engineering plan this PRD was derived from. It carries the failure analysis, the `file:line` references into the reference add-on, and the reasoning behind each decision. Where the PRD says *what*, that document says *why*, and it is the authority on the security-critical mechanisms.
- This is milestone 1, so there is no prior milestone log to read.

## Before you build anything

The engineering plan flags six unknowns in the add-on skeleton that must be settled **before** anything is built on top of them. Resolve and report all six first, then continue:

1. The add-on appears from the repository URL and installs.
2. It starts, and ingress authenticates the admin panel.
3. The Supervisor API answers with `SUPERVISOR_TOKEN`.
4. `/data` survives an add-on restart.
5. `pydantic-core` installs from a prebuilt wheel rather than compiling Rust on the musl base image.
6. The add-on's container hostname is resolvable from another add-on — this decides whether port 8888 needs publishing on the host at all.

If any of these fails, stop and tell me before proceeding. Number 5 in particular may change the stack.

## Your task

1. Plan the implementation for **only** milestone 1 as defined in the PRD. Do not plan or build anything from milestone 2.
2. After I confirm the plan, build only what is in milestone 1's scope.
3. Verify your work against the "Done when" criteria for milestone 1 in the PRD, and against the failure-path verification steps in `docs/plans/gate-pin-addon.md`. The happy path passing is not sufficient — a `GET` must not act, a preview fetcher must not open the gate, and a forged real-IP header must not defeat the rate limiter.
4. When complete, write a `milestone-log.md` in this folder (`_build_plan/milestones/1-live-gate-access/milestone-log.md`). Structure it as follows:
   - **Start with a `## What's new in the app` section at the very top.** A concise, human-readable bulleted list of the main user-facing features added in this milestone — written so a non-technical reviewer can see at a glance what to expect in the app now. Frame each bullet as a capability, not a technical artifact.
   - Then include the implementation detail sections below for the next milestone's agent to reference:
     - What was built (files created, models added, routes added, etc.)
     - Any decisions made during implementation that weren't pre-specified in the PRD
     - Anything milestone 2 will need to know
     - Any deviations from the PRD or the engineering plan, and why

Ask me any clarifying questions using AskUserQuestion tool to lock in the implementation plan for this milestone.
