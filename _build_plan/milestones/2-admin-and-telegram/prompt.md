# Milestone 2 — Admin panel and Telegram control

You are entering plan mode to plan and then build milestone 2 of this project.

## Context

- Read `@_build_plan/prd.html` for the full project context, scope, data model, and tech stack.
- Read `@docs/plans/gate-pin-addon.md` — the engineering plan this PRD was derived from. Where the PRD says *what*, that document says *why*, and it is the authority on the security-critical mechanisms.
- Read `@_build_plan/milestones/1-live-gate-access/milestone-log.md` to understand what has already been built, what was decided during implementation, and any deviations from the plan.

## Your task

1. Plan the implementation for **only** milestone 2 as defined in the PRD.
2. After I confirm the plan, build only what is in milestone 2's scope.
3. Verify your work against the "Done when" criteria for milestone 2 in the PRD.

Two constraints from the engineering plan that milestone 2 must not break — check them explicitly before you finish:

- **The camera proxy route lives under `/api/admin/*`.** nginx must never serve it on the public port. Camera streams are admin-only; putting one on the guest origin is out of scope by design, not by omission.
- **The guest bundle must still contain no service worker.** Milestone 2 makes the *admin* panel installable. If a shared Vite config or PWA plugin leaks a service worker into the guest build, that is a regression — a service worker that ships once persists on visitors' devices even after it is removed.

4. When complete, write a `milestone-log.md` in this folder (`_build_plan/milestones/2-admin-and-telegram/milestone-log.md`). Structure it as follows:
   - **Start with a `## What's new in the app` section at the very top.** A concise, human-readable bulleted list of the main user-facing features added in this milestone — written so a non-technical reviewer can see at a glance what to expect in the app now. Frame each bullet as a capability, not a technical artifact.
   - Then include the implementation detail sections below:
     - What was built (files created, models added, routes added, etc.)
     - Any decisions made during implementation that weren't pre-specified in the PRD
     - Anything a future session will need to know
     - Any deviations from the PRD or the engineering plan, and why

Ask me any clarifying questions using AskUserQuestion tool to lock in the implementation plan for this milestone.
