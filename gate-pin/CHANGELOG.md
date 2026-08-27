# Changelog

## [0.2.2] - 2026-08-28
- Document the telegram_chat_ids list syntax

## [0.2.1] - 2026-08-28
- Show the tunnel URL first in Settings

## [0.2.0] - 2026-08-28
- Show the Cloudflare Tunnel service URL in the admin panel, with a copy button

## [0.1.3] - 2026-08-28
- Document routing a second hostname on an existing Cloudflare tunnel

## [0.1.2] - 2026-08-28
- Document the Cloudflare Tunnel requirement and how to verify it

## [0.1.1] - 2026-08-27
- Fix guest page assets failing to load from a /g/<token> link, and the Copy button silently doing nothing over plain HTTP

## [0.1.0] - 2026-08-27
### Added
- Time-limited guest access to chosen Home Assistant entities
- One grant, two credentials: a 6-digit PIN and a 192-bit link token, each
  rate-limited according to its own entropy
- Mobile-first guest page with per-grant theming, logo and accent colour
- Admin panel through ingress: mint, presets, grant management with extend and
  revoke, audit log, camera streams, branding, health
- Telegram bot: `/new`, `/list`, `/revoke`, `/extend`, `/presets`
- Alerts to a Home Assistant `notify.*` service on lockout and bot failure
- Admin panel installable as a PWA. The guest page deliberately is not.
- Scannable QR code on the mint screen, generated in the browser and
  verified at build time by decoding it back
