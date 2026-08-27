# Changelog

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
