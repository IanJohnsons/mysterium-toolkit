# Changelog

All notable changes to Mysterium Node Toolkit are documented here.  
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [1.1.19] - 2026-05-10
### Fixed
- `update.sh` auto-detects root-owned `.git/objects` and fixes ownership before `git pull` — protects users who previously ran `sudo ./update.sh`
### Added
- README urgent notice: one-time fix command for users who previously ran `sudo ./update.sh`

---


### Fixed
- `update.sh` no longer requires outer sudo — runs as current user, uses `$SUDO` internally for privileged commands. `git pull` now runs as the real user with their SSH key (fixes SSH permission denied on laptop/desktop installs)
- Fleet update button now calls `./update.sh` for all install types — includes frontend rebuild, pip deps, and service restart (was: git pull + systemctl stop/start only, no frontend rebuild)
- `update.sh` copies `.build/index.html` correctly instead of hardcoded heredoc
- `update.sh` no longer deletes `node_modules` before build — preserves existing install, only removes `dist/`. Full reinstall only when needed

---

## [1.1.15] - 2026-05-09
### Added
- **StatusCard**: Net Earned row (Lifetime × 0.80) alongside Lifetime Gross — users can verify the 20% Hermes fee is exact
- **Fleet bar**: Net lifetime, Gross (pre-fee), In-system MYST (unsettled + Hermes channel), live USD/EUR fiat value
- **README**: Ansible mass update section for 10+ node operators with full setup instructions
- **README**: Credit to community member who suggested the Ansible approach

### Fixed
- `displayUnsettled` fallback logic — unsettled now always shows the real TequilAPI value; session_total fallback only appears as a secondary label when TequilAPI is settling
- Hermes Channel row restored to proper position in StatusCard grid
- Earnings help text updated to explain all new readings and fee verification

---

## [1.1.14] - 2026-05-09
### Added
- Fleet aggregate bar: In-system MYST (unsettled + Hermes channel balance)
- Fleet aggregate bar: Net lifetime (Lifetime × 0.80 after 20% Hermes fee)
- Fleet aggregate bar: Live USD/EUR fiat value of unsettled MYST

### Fixed
- `displayUnsettled` — removed confusing session_total fallback that showed a different value when unsettled was 0

---

## [1.1.13] - 2026-05-09
### Added
- Docker support for fleet update: detects `/.dockerenv`, does `git pull` + `kill PID` → container restarts via `--restart=always`
- Fleet Update Manager and Docker node stats documented in README

---

## [1.1.12] - 2026-05-09
### Fixed
- Fleet update on non-root installs: use `systemctl stop` + `systemctl start` instead of `systemctl restart` — `restart` was not in NOPASSWD sudoers

---

## [1.1.11] - 2026-05-09
### Fixed
- Second orphaned `)}` rendering as visible text near Data Management panel

---

## [1.1.10] - 2026-05-09
### Fixed
- Fleet update on non-root installs: now uses `git pull` + `sudo systemctl stop` + `sudo systemctl start` — works without needing `sudo ./update.sh` in sudoers first
- VPS (root) still uses full `update.sh` for pip deps and frontend rebuild

---

## [1.1.9] - 2026-05-09
### Fixed
- Missing closing bracket `)}` in firewall panel JSX causing build failure

---

## [1.1.8] - 2026-05-09
### Fixed
- Orphaned `)}` rendering as visible text in mobile view near Data Management
- Fleet card eff label hidden when uptime is 100% (was showing same value as Today earnings — redundant)

---

## [1.1.7] - 2026-05-09
### Fixed
- JSX syntax error in firewall panel closing bracket causing `npm run build` failure

---

## [1.1.6] - 2026-05-09
### Added
- Firewall panel: inline expand (same pattern as System Health) — no longer renders at bottom of page
- Legacy port detection: dashboard warns if ports 1194 (OpenVPN) or 51820 (WireGuard standard) are explicitly open
- Legacy port removal button: one-click removal via `/firewall/remove-legacy-ports` endpoint

### Fixed
- Version check cache reduced from 1 hour to 5 minutes — update button appears within 5 minutes of a new release

---

## [1.1.5] - 2026-05-09
### Added
- **Public service 3-mode selector**: Open / Verified / Off replaces the on/off toggle
  - Open: `wireguard.access-policies = ""` — all consumers including Mysterium Dark
  - Verified: `wireguard.access-policies = "mysterium"` — Mysterium network consumers only
  - Off: wireguard service stopped
  - Mode change restarts the wireguard service so access_policies take effect immediately
- Mobile-responsive: buttons wrap to next line on narrow screens

### Fixed
- Setup.sh: removed incorrect ports 1194/TCP, 1194/UDP (OpenVPN deprecated), 51820/UDP (not used by Mysterium)
- Setup.sh: corrected UDP range from 10000-65000 to 10000-60000 (Mysterium node default)
- Port 4449 label corrected: "MystNodes UI" (was incorrectly labeled "TequilAPI")

---

## [1.1.4] - 2026-05-08
### Added
- Tunnel counter tooltip explaining WireGuard zombie interfaces (kernel interfaces persist after unclean disconnect — expected behavior)
- Firewall help text: accurate description of Mysterium iptables structure (MYST NAT chain, per-session FORWARD rules)

### Fixed
- `firewall/cleanup`: no longer creates custom `MYSTERIUM-FORWARD` chain — deduplicates FORWARD rules in-place
- `firewall/cleanup`: detects and migrates existing `MYSTERIUM-FORWARD` chain (created by older toolkit versions) back to correct structure
- `_setup_mysterium_forward_chain`: removed custom chain creation, replaced with safe in-place dedup

---

## [1.1.3] - 2026-05-07
### Fixed
- Reverted broken `get_sessions` from v1.1.2 that caused Node Analytics to go blank and active consumers to show 0
- Added isolated `/sessions/live` endpoint for realtime active session data — does not affect main metrics pipeline

---

## [1.1.2] - 2026-05-07
### Fixed *(reverted in 1.1.3)*
- Attempted realtime active session fetch via direct TequilAPI call — broke session ordering and ghost detection

---

## [1.1.1] - 2026-05-06
### Fixed
- `system/update` endpoint: proper SSH key detection (`github_key`, `id_ed25519`, `id_rsa`)
- `system/update`: correct `HOME` environment variable for subprocess
- `system/update`: output logged to `/tmp/mysterium-toolkit-update.log`
- Added `/system/update/status` endpoint to read update log
- Version check cache: 1 hour (reduced to 5 min in v1.1.6)

---

## [1.1.0] - 2026-05-05
### Added
- **Public service 3-mode selector** (initial implementation, refined in v1.1.5)
- Sessions pagination support
- TequilAPI default credentials hint in setup wizard
- Config update verification after active-services write
- Earnings sanity check via `/node/provider/service-earnings`
- Help/readme/wizard documentation for all new features
- Earnings efficiency label changed from `MYST/GB` to `eff/GB` with two-component pricing note

---

## [1.0.30] - 2026-05-04
### Fixed
- Chart legend and analytics bar colors use inline hex (`style={{color: hex}}`) instead of Tailwind CDN classes — fixes color mismatch on systems where CDN Tailwind doesn't load extended palette

---

## [1.0.29] - 2026-05-03
### Added
- Fleet Update Manager: per-node update button and Update All button
- Node quality card offline warning when discovery monitoring unavailable
- Analytics bar colors use hex for reliability

---

## [1.0.28] - 2026-05-02
### Fixed
- systemd service file: `StartLimitIntervalSec` moved to `[Unit]` section
- `myst` service detection fix

---

## [1.0.27] - 2026-05-01
### Fixed
- `wireguard` excluded from `active-services` config (node-managed)
- `monitoring`/`noop` service types blocked from toggle
- TequilAPI errors logged properly

---

## [1.0.26] - 2026-04-30
### Fixed
- `access_policies` removed from `start_service` payload (node reads from config, not per-request)
- Metrics refresh after service toggle

---

## [1.0.25] - 2026-04-29
### Fixed
- ServiceSplitChart and EarningsEfficiencyChart default period changed from 90d to 30d

---

## [1.0.24] - 2026-04-28
### Fixed
- Data transfer chart color changed to indigo `rgb(99,102,241)`

---

## [1.0.23] - 2026-04-27
### Fixed
- `quic_scraping` merged into `scraping` across all analytics, charts, labels, and fmtType

---

## [1.0.22] - 2026-04-26
### Fixed
- Ghost deduplication allows parallel B2B scraping sessions
- Active tab consumer counter corrected

---

## [1.0.21] - 2026-04-25
### Fixed
- Active-services config updated on service toggle
- Port 4449→4050 auto-correction in `nodes.json` for TequilAPI
- Setup.sh template fix

---

## [1.0.20] - 2026-04-24
### Fixed
- Service toggle fleet routing: `backendUrlRef` replaced with `getNodeAwareUrl()` to prevent node identity failures
- QUIC Scraping merged into B2B Data Scraping row

---

## [1.0.3] - 2026-04-15
### Fixed
- SessionDB migration no longer gets stuck on databases missing the `provider_id` column

---

## [1.0.2] - 2026-04-10
### Fixed
- `chown config/` added to `update.sh` and `setup.sh` after sudo operations to prevent root-owned `earnings_history.db`

---

## [1.0.1] - 2026-04-05
### Fixed
- Initial post-launch bug fixes

---

## [1.0.0] - 2026-04-01
### Added
- Initial public release
- Flask/React monitoring dashboard for Mysterium VPN node operators
- Earnings tracking, session analytics, node quality monitoring
- Fleet mode for multi-node monitoring
- System health panel with adaptive CPU/conntrack tuning
- 11 themes, autostart, remote node restart/settle/payment configuration
