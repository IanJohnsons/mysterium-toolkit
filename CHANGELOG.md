# Changelog

All notable changes to Mysterium Node Toolkit are documented here.  
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---
## [1.2.13] - 2026-05-30
### Fixed
- **Port 4449 vs 4050 in PortReachability health check:** `system_health.py` was checking port 4449 (the NodeUI/MystNodes web interface) instead of port 4050 (TequilAPI — the actual API the toolkit communicates with). This caused false positives where the health check reported the API as reachable when in fact TequilAPI was down but the UI was still running. Fixed `TEQUILAPI_PORT = 4050` and updated the docstring.
- **Removed three deprecated delete endpoints:** `/earnings/snapshots/delete`, `/traffic/delete`, and `/sessions/delete` were leftover from before DataManager existed. They deleted data without syncing in-memory caches, without node_id filtering, and only covered 3 of 7 data types. All data management now goes through `/data/delete` (DataManager) which handles all 7 types, filters by node_id, and syncs EarningsDeltaTracker + SessionStore + tier caches automatically.
- **Incorrect success message after data delete:** DataManager showed "Restart the backend to clear in-memory caches" after a delete — but `/data/delete` already syncs all in-memory state immediately. Message corrected to reflect actual behavior.

---

## [1.2.12] - 2026-05-30
### Fixed
- **Manual and timer-based updates require password on Parrot OS (and any distro with `Defaults use_pty`):** Parrot OS enforces `Defaults use_pty` in `/etc/sudoers`, which requires sudo to allocate a pseudo-terminal even for NOPASSWD commands. When `update.sh` writes the sudoers file via a heredoc pipe (`printf | sudo tee`) or when the systemd auto-update timer runs without a TTY, sudo cannot allocate a PTY and falls back to prompting for a password. Fixed by adding `Defaults:$_REAL_USER !use_pty` as the first line of the generated `/etc/sudoers.d/mysterium-toolkit` file, overriding the global setting for the toolkit user only. Applied to `update.sh`, `setup.sh`, and `bin/setup.sh`.

---

## [1.2.11] - 2026-05-30
### Fixed
- **Auto-update timer not triggering on existing installs (laptop):** the timer service file was only written when it did not yet exist. If the toolkit was installed before the timer feature was added, the service file contained a stale `User`, `WorkingDirectory`, or `ExecStart` path and the timer fired but silently did nothing. Fixed: `update.sh` now always rewrites both the timer and service files on every run, ensuring the correct user and path are always current. The timer is only restarted if it was not already active.
- **Reverted: globe icon for wireguard sessions (v1.2.9/v1.2.10):** the `🌐` icon was based on the incorrect assumption that wireguard sessions never carry a `consumer_country`. In reality, `ConsumerCountry` is populated from the consumer's `LocationInfo` in the P2P session handshake and is available once the session is fully established. The `—` shown for active sessions is temporary. The revert restores the original `—` fallback.

---

## [1.2.10] - 2026-05-30
### Fixed
- **Globe icon missing in History and Consumers detail views:** the `🌐` icon for wireguard (Public) sessions without a country was only applied to 4 of 8 locations in v1.2.9. Fixed the remaining 4 placements: History tab mobile card, History tab desktop table, Consumers detail mobile view, Consumers detail desktop view. All session and consumer views now consistently show `🌐` for Public sessions instead of `—`.

---

## [1.2.9] - 2026-05-30
### Fixed
- **Probe detection falsely flagging wireguard (Public) consumers as network probes:** the `is_probe` heuristic (≥5 sessions, zero earnings, avg data <2 MB/session) incorrectly matched real Public consumers whose Hermes promises had not yet settled. Wireguard consumers always have `earnings=0` in the session DB until settlement completes, and `consumer_country` is always empty by design in the Mysterium node source (`SessionDTO` — the field is never populated for wireguard sessions). Fix: consumers with wireguard sessions totalling >50 MB are now explicitly excluded from probe detection regardless of earnings status.
- **UI: wireguard consumers shown as `—` in country column:** replaced the empty dash with a `🌐` globe icon (tooltip: "Public consumer — location not shared by design") in the Connections, History, and Consumers views. Probes retain the `🔧` icon. Consumers with a known country still show the flag.
- **Code comment: `noop` service incorrectly described:** `noop` uses `access_policies: []` (public, not mysterium-restricted). Comment corrected in `backend/app.py`.

---


## [1.2.8] - 2026-05-23
### Fixed
- **Sudoers: missing `ufw`, `iptables-nft`, `cpufreq scaling_governor` and `cpupower` on non-root installs:** on Type 1 (laptop/desktop) installs the sudoers NOPASSWD list was missing four commands used at runtime by the toolkit backend. `ufw` (firewall status polling every 2 minutes), `/usr/sbin/iptables-nft` (iptables backend detection), `/usr/bin/tee /sys/devices/system/cpu/*/cpufreq/scaling_governor` (CPU governor write), and `/usr/bin/cpupower` (frequency-set) all failed silently with "a password is required" in a non-interactive systemd context. Fixed in `setup.sh`, `bin/setup.sh`, and `update.sh` — the update.sh fix ensures all existing installs receive the corrected sudoers on their next update.

---

## [1.2.7] - 2026-05-23
### Fixed
- **Sudoers: missing `/usr/bin/systemctl` paths (Parrot OS / security-hardened distros):** sudoers only listed `/bin/systemctl` for all systemctl commands. On Parrot OS and other security-hardened Debian-based distros, `sudo` matches strictly on the resolved binary path. Since `/bin` is a symlink to `/usr/bin`, sudo resolves the real path to `/usr/bin/systemctl` and rejects the `/bin/systemctl` NOPASSWD rule — prompting for a password in a non-interactive context (systemd timer, auto-update) and causing the update to fail silently. Fixed by adding `/usr/bin/systemctl` variants for all existing `/bin/systemctl` entries in both `update.sh` and `bin/setup.sh` sudoers content.
- **Sudoers: `systemctl reset-failed mysterium-toolkit` not in NOPASSWD:** added to both `update.sh` and `bin/setup.sh` so the backend restart sequence in update.sh runs fully without a password prompt on any distro.
- **Sudoers: `systemctl restart mysterium-*` missing from `update.sh`:** was present in `bin/setup.sh` but not in `update.sh`. Added for consistency.

---

## [1.2.6] - 2026-05-22
### Fixed
- **Auto-update timer broken on all installs:** the wrapper script `/usr/local/bin/mysterium-toolkit-update-check.sh` was written with `<< 'WRAPPER_EOF'` (single-quoted heredoc) which blocked variable expansion at write time. `$TOOLKIT_DIR` was left as a literal undefined variable — at runtime it resolved to an empty string, making `exec "/update.sh"` fail silently. The auto-update timer never triggered an actual update. Fixed by switching to an unquoted heredoc with proper escaping of runtime variables (`\$CURRENT`, `\$LATEST`) while expanding `$TOOLKIT_DIR` at write time to the hardcoded install path.
- **Wrapper never repaired on existing installs:** the timer creation block was guarded by `if [ ! -f "$_TIMER_FILE" ]`, so a broken wrapper from an older install was never rewritten. Fixed by splitting wrapper rewrite (runs on every `update.sh` invocation) from timer/service creation (still first-time only). Existing installs with a broken wrapper will be fixed automatically on the first manual `./update.sh` run.
- **Security: `is_local_request()` trusted entire RFC1918 on VPS installs:** on a shared datacenter network (Hetzner, OVH, Contabo) other servers on the same `10.x` or `172.x` subnet bypassed dashboard authentication entirely. Fixed: when `toolkit_mode = 'remote'` (set automatically by the wizard for non-localhost installs including all VPS and Type 3 slaves), only `127.0.0.1` and `::1` are treated as trusted. RFC1918 still trusted on `toolkit_mode = 'local'` (home/LAN installs) — no behaviour change for those users.

---

## [1.2.5] - 2026-05-21
### Fixed
- **Docker compatibility — README:** corrected the Docker command in the "Mysterium Node in Docker" section. Removed the incorrect `-p 4050:4050` flag (no such port in standard Docker installs). Documented that TequilAPI is on port 4449, that the Node UI password must be entered during wizard setup, and clarified which features are unavailable when the node runs in a container (Live Connections, VPN Traffic, process-based checks).
- **Docker compatibility — setup wizard:** Easy mode "node not found" hint now includes Docker-specific commands (`docker ps | grep myst`, `docker start myst`, port mapping reminder). Password prompt in Easy mode is now Docker-aware: when a `myst` container is detected the hint explicitly states the password was set during Node UI onboarding and is not `mystberry`. Advanced mode connection-failed hint corrected from port 4050 to 4449; added Docker port-mapping reminder.
- **Docker compatibility — ServiceWatchdog:** when `myst` process is not visible via psutil (node runs in a Docker container), the watchdog now checks `docker ps` before declaring the service critical. If a running `myst` container is found the status is reported as OK with label `Running in Docker (container_name)` instead of a false critical alarm.
- **Docker compatibility — Live Connections:** when psutil sees no VPN tunnel interfaces (Docker install), the connected-clients counter now falls back to active sessions from the TequilAPI sessions cache instead of forcing 0.
- **Docker compatibility — VPN Traffic:** when no VPN interfaces are visible via psutil and vnstat has no myst* data (Docker install), the bandwidth card now falls back to cumulative bytes from TequilAPI sessions. `data_source` is set to `sessions_api` so the frontend can label the data appropriately.
- **Docker compatibility — Node Restart:** when Docker CLI is not accessible (missing socket mount), the restart endpoint now returns a specific hint explaining how to mount `/var/run/docker.sock` and how to restart manually, instead of a generic sudo-permission error.
- **Docker compatibility — System Health:** the `/system-health` endpoint now includes a `docker_note` field when `RUNTIME_ENV` detects `docker_host`, informing the user that kernel tuning results reflect the host system, not the Mysterium container.

---

## [1.2.4] - 2026-05-20
### Fixed
- fail2ban jail edit: writing to `jail.local` was correct but `fail2ban-client reload` did not apply the new values to the running daemon for active jails. Added `_f2b_apply_live()` which calls `fail2ban-client set <jail> bantime/maxretry/findtime <val>` after every save — takes effect immediately without relying on reload. `jail.local` write + reload retained for persistence after restart.
- Auto-update timer: changed frequency from daily to hourly; timer now runs a version-check wrapper that fetches the latest VERSION from GitHub and only executes `update.sh` when `current != latest`. Removes unnecessary updates and catches new versions within the hour.

---

## [1.2.3] - 2026-05-19
### Fixed
- update.sh: `tee /etc/sudoers.d/mysterium-toolkit`, `chmod 440`, `visudo` and `rm` were not in NOPASSWD — causing a mandatory sudo password prompt every time `./update.sh` ran. When running non-interactively (fleet update button, systemd timer), the sudoers update was silently skipped because there is no TTY to type the password. This caused the sudoers to never update on non-root installs, and the version counter to fall behind. All four commands added to NOPASSWD in setup.sh (root + bin) and update.sh sudoers content.

---

## [1.2.2] - 2026-05-19
### Fixed
- fail2ban: removed self-invented `jail.d/mysterium-toolkit.conf` — writing `.conf` files to `jail.d/` is reserved for distribution packages. The toolkit now writes exclusively to `/etc/fail2ban/jail.local`, the official user-override file supported on all distros.
- fail2ban: toolkit-managed jails are isolated in a clearly marked block inside `jail.local` (`# --- Mysterium Toolkit managed jails ---` / `# --- End Mysterium Toolkit ---`). User content outside this block is never touched.
- fail2ban: `_f2b_write_toolkit_conf()` rewritten to read existing `jail.local`, update only the toolkit block, and write back — preserving all user customizations outside the block.
- fail2ban: `_f2b_all_jails()` `is_toolkit` detection now uses `_f2b_get_toolkit_jail_names()` which reads jail names from the toolkit block in `jail.local` — correct identification without relying on a fake conf file.
- fail2ban: `fail2ban_install()` route now writes to `jail.local` via `_f2b_write_toolkit_conf()` instead of hardcoded `jail.d/` path.
- setup.sh (root + bin): fail2ban step now appends the toolkit block to `jail.local`; old `jail.d/mysterium-toolkit.conf` is removed if present (migration).
- update.sh: migration step removes `jail.d/mysterium-toolkit.conf` on first run; sudoers NOPASSWD updated from `tee /etc/fail2ban/jail.d/*` to `tee /etc/fail2ban/jail.local`.
- sudoers (all): `tee /etc/fail2ban/jail.d/*` replaced by `tee /etc/fail2ban/jail.local` — more restrictive and correct.

---

## [1.2.1] - 2026-05-19
### Fixed
- fail2ban jail edit: port/logpath/filter disappeared after save — secondary pass in `_f2b_all_jails()` only set `is_toolkit` flag but never restored these fields from `mysterium-toolkit.conf` back into the active jail object
- fail2ban health scan: `fail2ban-client status` called without sudo after successful ping — working prefix now stored and reused for all subsequent fail2ban calls in the health scan; fixes "0 jails" in system health card on non-root systems
- fail2ban_get_jails: per-jail status now tries `sudo -n` fallback; `File list` (logpath), `Journal matches` (systemd backend), `Currently failed` and `Total failed` are now parsed from status output
- fail2ban jail UI: logpath field now shows "systemd journal (geen bestand nodig)" and is locked when `backend_type = systemd`; shows detected file path for file-backend jails
- fail2ban jail edit: logpath field now shows per-jail-type placeholder hints (sshd, nginx, recidive, apache)
- fail2ban jail list: currently failing and total failed count now shown per jail
- update.sh: now detects if its own content changed after `git pull` and re-execs with the new version — fixes silent skipping of update.sh improvements on running updates
- update.sh: auto-update systemd timer (`mysterium-toolkit-update.timer`) now created automatically on first `./update.sh` run if missing

---

## [1.2.0] - 2026-05-19
### Fixed
- Laptop/desktop jails empty in Security Settings: `fail2ban-client` was not in sudoers NOPASSWD — toolkit backend could not access the fail2ban socket without a password. Added `fail2ban-client` (all common paths) and `tee /etc/fail2ban/jail.d/*` + `tee /etc/fail2ban/filter.d/*` to `setup.sh` sudoers block.
- fail2ban install (dashboard + setup.sh): jail config now detects system firewall type — writes `banaction = nftables` on nftables-only systems and `backend = systemd` on systems without rsyslog. Fixes fail2ban on Parrot OS, Debian Bookworm, and Raspberry Pi OS Bookworm out of the box.
- fail2ban install: default bantime raised from 1h to 24h for sshd and dashboard jails.
- Raspberry Pi setup: `lm-sensors` install now skipped on ARM architectures — sysfs thermal fallback handles temperature on Pi hardware; lm-sensors is unavailable on ARM and caused confusing install output.
- Raspberry Pi setup: `setup.sh` now checks Node.js version after install and exits with a clear error if version < 16, with a fix command shown. Previously setup continued silently with v12, failing later during Vite build with a cryptic error.
- Raspberry Pi setup: architecture detection (`uname -m`) added for Node.js install — on `armv6l` (Pi Zero / Pi 1) NodeSource is unavailable; script warns and falls back to apt with a note about backend-only mode.

---

## [1.1.66] - 2026-05-19
### Fixed
- Dashboard crash: `c.earnings_myst` undefined on fleet nodes — fleet country_breakdown used `total_earnings` key instead of `earnings_myst`; no frontend fallback guard (Bug 17)
- Dashboard crash: `t.value.toFixed(0)` on temperature sensor entries with null/undefined value — added `?? 0` guard in all four render locations (Bug 18)
- Dashboard crash: `eff/GB` called `.toFixed()` on undefined `earnings_myst` — added `|| 0` guard (Bug 19)
- Security routing: `loadJails()` empty `[]` deps — SecurityPage never reloaded jails or UFW on node switch; dep changed to `[backendUrl]` (Bugs 1+2)
- fail2ban ✕ button: shown on external jails instead of toolkit-managed ones — condition was `!is_toolkit`, now `is_toolkit` (Bug 3)
- fail2ban Remove in edit form: shown for all jails — now guarded with `jail.is_toolkit` (Bug 5)
- fail2ban bantime/findtime: min hardcoded to 60, blocking permanent ban (−1) — mins changed; `parseInt||min` replaced with `isNaN` guard (Bugs 6+7)
- fail2ban edit form: port, logpath, filter fields missing — all three added (Bug 8)
- fail2ban add form: no enabled toggle — checkbox added (Bug 9)
- fail2ban add form: empty filter field caused jail load failure — backend defaults filter to jail name (Bug 10)
- fail2ban bans: IP list capped at 20 with no indicator — cap raised to 50, UI shows truncation count (Bug 11)
- UFW delete: sent `"22/tcp ALLOW"` (tokens reversed) — backend requires `"allow 22/tcp"`; fixed in ✕ button and edit-save flow (Bugs 13+14)
- UFW edit parse: `parts[0]` as port broke `Anywhere DENY IN x.x.x.x/24` and `(v6)` rules — parser rewritten with `isFromRule` detection (Bug 12)
- UFW add form: no From IP/CIDR field — added for subnet block rules (Bug 15)
- UFW backend: regex blocked `from IP` syntax — updated for both add and delete routes (Bug 16)
- fmtTime: negative bantime showed as negative seconds — now shows `perm` for values < 0

---

## [1.1.65] - 2026-05-18
### Fixed
- fail2ban jails: fixed exception cascade — jail list and settings fetch now have separate error handling so a settings error no longer wipes the entire jail list
- Dashboard crash: fixed toFixed() on undefined values in earnings chart
- Sudoers: added fail2ban-client and fail2ban config paths to NOPASSWD — fixes jail access on non-root installs (laptop)

---

## [1.1.64] - 2026-05-17
### Fixed
- fail2ban jails: rewritten to use fail2ban-client as primary source — works on all distros (Debian, Ubuntu, RHEL, CentOS, Fedora, Arch). Gets live maxretry/bantime/findtime per jail via fail2ban-client get
- Security page: UFW rules now have edit button (✎) — opens inline form to change action/port/protocol
- Security page: loadUfw function restored for refresh after edit
- No duplicate components, no orphan code

---

## [1.1.63] - 2026-05-17
### Fixed
- SecurityPage: firewallData prop added to function signature
- iptables: field names corrected (target/proto/src/dst/details)
- fail2ban: ping uses sudo -n fallback for non-root installs
- Fleet proxy: /firewall added to whitelist

---

## [1.1.62] - 2026-05-17
### Fixed
- SecurityPage: firewallData prop added to function signature — fixes ReferenceError crash on open
- iptables: field names corrected (target/proto/src/dst/details) — columns now show correctly
- fail2ban: ping uses sudo -n fallback for non-root installs — fixes "stopped" on laptop

---

## [1.1.61] - 2026-05-17
### Fixed
- Fleet proxy: added /firewall to whitelist — UFW rules now load correctly for fleet nodes
- Security page: UFW rules loaded from firewallData prop instead of extra fetch
- Security page: all jails editable — external jails get saved as override to mysterium-toolkit.conf
- Firewall card: "+X more" banned IPs is now a toggle button to show/hide all IPs

---

## [1.1.60] - 2026-05-17
### Changed
- Security page: complete rewrite — full fail2ban management (start/stop, jails list, edit/add/delete per jail, unban IPs, install button), UFW rules (add/delete)
- Security page: jails loaded from config files regardless of fail2ban running state
- Firewall card: fail2ban shows status + banned IPs only, all management via 🛡 Security → button
- 🛡 Security → button scrolls to Security section automatically
### Added
- Backend: /firewall/fail2ban/start and /firewall/fail2ban/stop endpoints
- Backend: /firewall/fail2ban/reload endpoint
- Backend: jails endpoint returns running state and only fetches live ban data when running

---

## [1.1.59] - 2026-05-17
### Fixed
- Root cause fix: removed 123 orphan lines (duplicate FirewallSection x2, UpdateWaiter x2, and remnants of old Fail2banManager) that were at module level — minifier combined them with component definitions causing useState to execute outside React render context → blank dashboard crash

---

## [1.1.58] - 2026-05-17
### Fixed
- Fleet proxy whitelist: added all new security endpoints
- Removed duplicate components causing dashboard crash
- Fixed critical crash: React.useState replaced with named import useState throughout SecurityPage and FirewallSection — React default export was null at bundle initialization causing blank dashboard

---

## [1.1.57] - 2026-05-17
### Fixed
- Removed duplicate FirewallSection and UpdateWaiter components that caused dashboard to crash after update
- Fleet proxy whitelist: added all new security endpoints (fail2ban/jails, fail2ban/unban, fail2ban/reload, fail2ban/install, ufw/add, ufw/delete)

---

## [1.1.56] - 2026-05-17
### Fixed
- Firewall card: fail2ban shows status only (running/stopped + counts) — no jail details. "🛡 Manage →" links to Security page.

---

## [1.1.55] - 2026-05-17
### Added
- Security page: Install fail2ban button when not installed — no setup.sh needed
- Security page: active bans + unban buttons visible per jail
- Backend: /system/fail2ban/install endpoint
- Backend: /firewall/fail2ban/jails now includes active ban count and banned IPs
### Fixed
- Fail2banManager modal component fully removed — Security page is now the only fail2ban management interface

---

## [1.1.54] - 2026-05-17
### Fixed
- Security page: removed incorrect text about toolkit.conf restriction — all official fail2ban jails are shown and editable

---

## [1.1.53] - 2026-05-17
### Fixed
- FirewallSection badge: replaced dynamic Tailwind classes with static conditionals — dynamic classes are not included in production builds

---

## [1.1.52] - 2026-05-17
### Added
- Security button in bottom nav bar — opens full Security Settings page below (same pattern as Logs/Help)
- Security page: fail2ban jail management (view all jails, edit toolkit jails, add custom jail) + UFW rule management (add/delete rules)
### Changed
- Firewall card fail2ban section: monitoring only (status, jail counts, active bans)
- fail2ban management removed from firewall card inline — moved to Security page

---

## [1.1.51] - 2026-05-17
### Changed
- Firewall card: 3 collapsed sections (iptables ▶, UFW ▶, fail2ban ▶) — nothing open by default
- fail2ban section: status + jail list + "Manage fail2ban →" button
- fail2ban management opens as a panel in the same page using existing activePanel system, not a modal

---

## [1.1.50] - 2026-05-17
### Added
- fail2ban Manager modal — edit jail settings (maxretry, bantime, findtime), add custom jails, enable/disable jails. Accessible via ⚙ Manage button in firewall card.
- Read-only view of jails managed by external configs — no conflicts with other tools
- Only writes to /etc/fail2ban/jail.d/mysterium-toolkit.conf, never touches jail.local
### Changed
- UFW rules collapsed by default — shows first 5 rules with "show all" toggle to avoid scrolling past 84 rules

---

## [1.1.49] - 2026-05-17
### Added
- Firewall card: fail2ban sectie — toont installed/running status, actieve jails, banned IPs per jail met unban knop
- Backend: fail2ban status in /metrics firewall data, nieuw /firewall/fail2ban/unban endpoint
- setup.sh + bin/setup.sh: optionele stap 12.5 — fail2ban installeren met sshd, mysterium-dashboard en recidive jails. Schrijft enkel naar jail.d/mysterium-toolkit.conf, conflicteert nooit met bestaande fail2ban configuratie

---

## [1.1.48] - 2026-05-10
### Fixed
- Consumer ID copy: textarea positioned at top:0 opacity:0 in viewport — prevents browser from scrolling page when focusing copy element
- Network probes moved to top of consumer list — easier to find and copy

---

## [1.1.47] - 2026-05-10
### Fixed
- Consumer ID copy: added `preventScroll: true` to textarea focus call — browser was scrolling page to top when focusing the temporary copy element

---

## [1.1.46] - 2026-05-10
### Fixed
- `system/update`: spawn update.sh via `systemd-run --scope` so it runs in its own cgroup, separate from the mysterium-toolkit service cgroup. Previously, update.sh inherited the service cgroup and was killed by `systemctl stop mysterium-toolkit` (KillMode=control-group default), causing the log to stop at "Restarting backend..." every other update. This is the definitive fix for the alternating update failure pattern.

---

## [1.1.45] - 2026-05-10
### Fixed
- Consumer ID copy: `countryFlag` and `formatDataSize` moved to module level alongside ConsumerCard/ConsumerRow — fixes ReferenceError when opening Consumers tab

---

## [1.1.44] - 2026-05-10
### Fixed
- Backend: SIGTERM handler added — exits with code 0 so systemd `Restart=on-failure` does NOT trigger during updates. This is the definitive fix for the backend not restarting after fleet update.

---

## [1.1.43] - 2026-05-10
### Fixed
- Consumer ID copy in all sections including Network probes: moved ConsumerCard and ConsumerRow to module level — inline component definitions caused React to remount on every render, resetting the popup open state immediately

---

## [1.1.42] - 2026-05-10
### Fixed
- `update.sh`: fixed restart race condition — backend exits with code 1 on SIGTERM triggering Restart=on-failure after 10s. Update now detects and stops any auto-restart before starting the new version.

---

## [1.1.41] - 2026-05-10
### Fixed
- `update.sh`: replaced `grep -oP` with portable `awk` for PID extraction from ss output — grep PCRE not available on all Debian systems causing port 5000 kill to silently fail

---

## [1.1.40] - 2026-05-10
### Fixed
- Consumer ID popup modal restored — copy works over HTTP via execCommand fallback
- toFixed() crash fix for cpu_temp, earnings efficiency and other fields with undefined values

---

## [1.1.39] - 2026-05-10
### Fixed
- Consumer ID display restored to full address — removed truncation and modal popup that was added without request. Click address to copy directly, no modal.

---

## [1.1.38] - 2026-05-10
### Fixed
- `update.sh`: build to temp, only replace dist/ if build succeeds — existing dist/ kept intact on build failure
- `update.sh`: removed `pkill -f` — uses PID-only kill from ss output to avoid self-matching
### Added
- Verified mode warning: explains monitoring agents are blocked and quality metrics will show 0%

---

## [1.1.37] - 2026-05-10
### Fixed
- Removed `ExecStartPre pkill` from service file — pkill matched its own bash process (command line contained backend/app.py as argument) causing SIGKILL on itself and service start failure

---

## [1.1.36] - 2026-05-10
### Fixed
- Service file ExecStartPre: removed ss/pid parsing that caused bash to execute commands during heredoc expansion — replaced with simple `pkill -9 -f backend/app.py` which is safe in unquoted heredoc

---

## [1.1.35] - 2026-05-10
### Fixed
- Wireguard mode write: when `myst config set` fails (non-root daemon can't write system config), falls back to writing `/etc/mysterium-node/config.toml` directly via `sudo tee` — fixes verified mode not persisting on laptop/desktop installs
- Sudoers: added `tee /etc/mysterium-node/config.toml` and `config-mainnet.toml` to NOPASSWD

---

## [1.1.34] - 2026-05-10
### Fixed
- Service file: added `ExecStartPre` that kills any process on port 5000 before starting — systemd itself guarantees port is free, regardless of what update.sh does. Definitive fix for "Address already in use" after update.

---

## [1.1.33] - 2026-05-10
### Fixed
- `update.sh`: kill process on port 5000 by PID (from ss output) with SIGKILL — previous approach missed processes started outside systemd

---

## [1.1.32] - 2026-05-10
### Fixed
- `update.sh`: wait for port 5000 to actually be free before starting (max 15s loop using `ss`) — fixes "Address already in use" crash when old process hasn't fully stopped

---

## [1.1.31] - 2026-05-10
### Fixed
- `update.sh`: kill leftover process on port 5000 after systemctl stop — prevents "Address already in use" crash when old process hasn't fully stopped yet

---

## [1.1.30] - 2026-05-10
### Added
- Settle History: **Network Rewards** section — incoming MYST transfers not from Hermes (MystNodes monthly rewards, referrals, other sources) detected from Polygon transaction history. Accurate even when wallet is empty. Shows per-transaction with date, amount, sender and Polygonscan link.
- Backend: `rewards_txs` and `total_rewards` added to `/settle/history` response — filters on known Hermes contract addresses (chain 1 + chain 2)

---

## [1.1.29] - 2026-05-10
### Fixed
- `update.sh`: restart always uses systemd stop+start — removed nohup fallback that started service outside systemd causing it not to restart on next update
- `update.sh`: `systemctl reset-failed` added before start to clear rate-limit state
- Service file: `StartLimitIntervalSec=0` and `StartLimitBurst=0` moved to `[Unit]` section — fixes systemd warning and eliminates restart rate limiting
- `update.sh`: `sudo tee` → `$SUDO tee` for service file write

---

## [1.1.28] - 2026-05-10
### Fixed
- Wireguard mode read: config response uses nested `data.wireguard.access-policies` — was reading flat key, always returned empty → always showed Open
- Wireguard mode write: POST /config returns 404 for nested keys — now uses `myst config set wireguard.access-policies` CLI subprocess
- TypeError: toFixed() on undefined — all session earnings_myst and total_earnings calls now null-protected
### Changed
- License changed from CC BY-NC-SA 4.0 to AGPL-3.0 — correct open source software license that prevents commercial use and requires modifications to be open source

---

## [1.1.27] - 2026-05-10
### Added
- Update-in-progress screen: when backend is unreachable during an update, dashboard shows "Update in progress…" with spinner and auto-retry every 10 seconds instead of a generic error. Page reloads automatically when backend comes back.

---

## [1.1.26] - 2026-05-10
### Fixed
- `system/update`: update log moved from `/tmp/mysterium-toolkit-update.log` to `logs/update.log` — `/tmp/` files become root-owned when toolkit runs as root, causing Permission denied for all 32+ users who may have this issue
- `system/update`: stale `/tmp/` log files from older versions are automatically cleaned up on update
- `system/update/status`: reads from `logs/update.log` only — no more stale `/tmp/` log confusion

---

## [1.1.25] - 2026-05-10
### Fixed
- `update.sh`: replaced `systemctl restart` with `systemctl stop` + `systemctl start` — `restart` was not in NOPASSWD sudoers, causing sudo password prompt during fleet update

---

## [1.1.24] - 2026-05-10
### Fixed
- `update.sh`: sudoers update skipped when content unchanged — no more sudo password prompt on regular updates. Only asks when sudoers actually needs changing (first run after install or config change).

---

## [1.1.23] - 2026-05-10
### Added
- Earnings Efficiency chart split by service type — separate MYST/GB line per service (Public/VPN/B2B Scraping/B2B Data) with matching colors
- Configured node price shown in legend per service type (cfg: X.XXX MYST/GB) from /services endpoint — shows actual demand/supply price set by Mysterium algorithm
- quic_scraping merged into scraping in efficiency data
### Changed
- Combined average moved to secondary position — per-service breakdown is now primary view

---

## [1.1.22] - 2026-05-10
### Fixed
- JSX syntax error in help section — CLI paragraph was outside a div, causing frontend build failure on all systems

---

## [1.1.21] - 2026-05-10
### Fixed
- `update.sh`: chown commands are now conditional — only run if files are root-owned. Fixes fleet update button hanging waiting for sudo password on non-root installs.

---

## [1.1.20] - 2026-05-10
### Added
- **CLI**: Net Earned row (Lifetime × 0.80) in earnings page
- **CLI**: Live MYST fiat price (EUR/USD) in earnings page — fetched from backend `/myst-price`, refreshed every 5 minutes
- **CLI**: `fmt_svc()` helper maps service types to display labels (quic_scraping → B2B Scraping, wireguard → Public, etc.)
- **Fleet Add Node**: URL auto-complete — bare IP auto-gets `http://` prefix and `:5000` port on blur
- **Help section**: Updating the Toolkit section explaining fleet update button and `./update.sh`
- **Help section**: Fleet Add Node button documented (no manual nodes.json editing needed)
- **Help section**: CLI page 2 description updated with net earned and fiat price
- **README**: CLI section with usage, pages and key bindings
- **README**: Update section clarifies no sudo needed, fleet update button documented

### Fixed
- README: `sudo ./stop.sh` → `./stop.sh`

---

## [1.1.19] - 2026-05-10
### Fixed
- `update.sh` auto-detects root-owned `.git/objects` and fixes ownership before `git pull` — protects users who previously ran `sudo ./update.sh`
### Added
- README urgent notice: one-time fix command for users who previously ran `sudo ./update.sh`

---

## [1.1.18] - 2026-05-10
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
