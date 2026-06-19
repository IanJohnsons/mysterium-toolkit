# Changelog
All notable changes to Mysterium Node Toolkit are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## v1.2.29
- fix: database migration in `update.sh` now correctly migrates existing data from `config/` to `backend/databases/` — previous check skipped migration when empty placeholder files existed in `backend/databases/` (affects all users who updated to v1.2.28)
- fix: `data_manager.py` — `uptime_log.json` and `node_identity.txt` now correctly read from `config/` instead of `backend/databases/`; SQLite databases correctly use `backend/databases/`
- fix: README database paths corrected from `config/` to `backend/databases/`
- fix: README firewall table removed incorrect ports 1194 (OpenVPN) and 51820 (WireGuard) — Mysterium does not use these ports

## v1.2.28
- fix: all SQLite databases moved from `config/` to `backend/databases/` (correct location) [file:38]
- fix: `update.sh` auto-migrates existing `config/*.db` to `backend/databases/` on first run — no data loss [file:38]

## v1.2.27
- fix: `setup.sh` now downloads Node.js 18 binary directly when apt fails (Debian Buster/EOL systems) [file:38]
- fix: `setup.sh` detects and repairs broken npm (`TypeError: Class extends value`) [file:38]
- fix: Node.js minimum raised to v18 — Vite requires `crypto.getRandomValues` [file:38]
- fix: sqlite3 Buster fallback via `snapshot.debian.org` [file:38]
- fix: npm install log no longer uses `/tmp` — uses toolkit `logs/` directory [file:38]
- fix: `logs/` and `config/` chown after sudo install — prevents permission errors [file:38]
- fix: `nodes.json` template creation default changed to `N` — prevents ghost nodes in fleet UI [file:38]
- fix: backend skips template nodes with `REPLACE_WITH_NODE_IP` — never shown in fleet [file:38]
- fix: delete node immediately updates fleet UI state without waiting for metrics refresh [file:38]

## v1.2.26
- feat: setup wizard new entry question — node location instead of Easy/Custom [file:38]
- feat: fleet wizard added — guides Type 2 (fleet master) and Type 3 (lightweight backend) setup [file:38]
- feat: Easy mode now asks for Polygonscan API key [file:38]
- feat: Easy mode auto-detects Raspberry Pi — sets log level to WARNING automatically [file:38]
- feat: Easy mode wallet address explanation improved [file:38]
- feat: post-setup port reachability guide added to wizard [file:38]
- docs: README Step 8 wizard section fully rewritten to match new wizard flow [file:38]
- docs: Help section — log level and debug mode explanation added [file:38]

## v1.2.25
- fix: TequilAPI port corrected to 4050 throughout setup_wizard.py, app.py, README and Dashboard.jsx [file:38]
- fix: removed non-existent ports 14449/14050 from port scan [file:38]
- fix: nodes.json examples updated to use port 4050 (TequilAPI) instead of 4449 (Node UI) [file:38]
- fix: port scan now tries 4050 first (bare metal), then 4449 (Docker) [file:38]

## v1.2.24
- fix: Help section autostart option numbers corrected (8 for Type1/2, 6 for Type3) [file:38]
- fix: setup.sh Step 13 key tips corrected — option 8 autostart, option 9 security [file:38]
- docs: Help section now explains security can be added after install via option 9 [file:38]
- docs: README new section `Adding Security After Install` [file:38]

## v1.2.23
- fix: fail2ban start/stop use `fail2ban-client` instead of `systemctl` — fixes permission error on non-root installs [file:38]

## v1.2.22
- fix: SecurityPage settings routes (fail2ban managed toggle, install) use local backend URL instead of fleet proxy — fixes 403 FORBIDDEN in fleet context [file:38]

## v1.2.21
- fix: fail2ban managed toggle no longer resets every 5s — settings fetch split from firewallData useEffect [file:38]

## v1.2.20
- docs: removed outdated sudo ./update.sh warning from README [file:38]
- docs: README menu tables updated with Security & Upgrades option [file:38]
- docs: README firewall table corrected (port 4050, not 4449) [file:38]
- docs: README new Security section — fail2ban, Tailscale, custom jails [file:38]
- docs: README permissions table updated with fail2ban entries [file:38]
- docs: Help section in dashboard — Security tab, Tailscale, Pi mode, CLI option 9 explained [file:38]

## v1.2.19
- fix: auto-update wrapper now uses `sudo -n` on non-root systems (fixes Parrot OS and other security-hardened distros) [file:38]
- fix: removed Add custom jail UI — toolkit only manages mysterium-dashboard jail; info hint added pointing to manual jail.local editing [file:38]
- fix: Tailscale card now shows actionable message when installed but not connected [file:38]
- feat: Tailscale card shows optional UFW commands to hide dashboard from internet when connected [file:38]

## v1.2.18
- fix: `_f2b_all_jails()` is_toolkit computed inside inner loop — prevents wrong toolkit label on external jails (sshd, nginx-botsearch etc.) [file:38]
- fix: fail2ban_get_jails now only returns toolkit-managed jails — external jails never shown in dashboard [file:38]
- fix: fail2ban managed toggle now renders correctly regardless of jail load state [file:38]
- fix: removed mention of specific tool names from fail2ban managed toggle description [file:38]

## v1.2.17
- fix: setup.sh Python check now detects pyenv shims under sudo (Raspberry Pi Buster + other EOL systems) [file:38]
- fix: fail2ban only creates `mysterium-dashboard` jail — SSH and other jails managed by other tools are never touched [file:38]
- fix: update.sh sudoers rewritten in multi-line heredoc format (fixes Parrot OS and other security-hardened distros) [file:38]
- feat: Tailscale detection in firewall data (installed/running/IP/peers) [file:38]
- feat: Tailscale status card in Security tab with install guide [file:38]
- feat: fail2ban managed toggle in Security tab (disable to prevent toolkit from writing jail.local) [file:38]
- feat: Security & Upgrades menu in CLI (option 9) — install fail2ban, Tailscale wizard, reconfigure sudoers [file:38]

## v1.2.16
- fix: auto-update service exit code 1 when up-to-date (add exit 0 to wrapper script) [file:38]
- fix: fleet Add Node input fields uneditable due to nested component definition causing remount on every render [file:38]

## v1.2.15
- Added Pi mode toggle for Raspberry Pi SD card protection [file:38]
- Added firewalld rule display for Fedora/RHEL/CentOS/Rocky Linux [file:38]

## v1.2.14
- Fixed probe detection incorrectly relaxed in v1.2.9 and restored original probe logic [file:38]

## v1.2.13
- Fixed port 4449 vs 4050 in PortReachability health check [file:38]
- Removed deprecated delete endpoints [file:38]
- Corrected incorrect success message after data delete [file:38]

## v1.2.12
- Fixed manual and timer-based updates requiring password on Parrot OS and other `use_pty` distros [file:38]

## v1.2.11
- Fixed auto-update timer not triggering on existing installs [file:38]
- Reverted globe icon behavior for wireguard sessions [file:38]

## v1.2.10
- Fixed globe icon missing in History and Consumers detail views [file:38]

## v1.2.9
- Fixed probe detection falsely flagging wireguard Public consumers as network probes [file:38]
- UI: wireguard consumers shown as globe icon instead of dash [file:38]
- Code comment corrected for noop service description [file:38]

## v1.2.8
- Fixed sudoers missing ufw, iptables-nft, cpufreq scaling governor, and cpupower on non-root installs [file:38]

## v1.2.7
- Fixed sudoers missing `/usr/bin/systemctl` paths on security-hardened distros [file:38]
- Added missing `systemctl reset-failed mysterium-toolkit` NOPASSWD [file:38]
- Added missing `systemctl restart mysterium-*` in `update.sh` [file:38]

## v1.2.6
- Fixed broken auto-update timer wrapper script [file:38]
- Fixed wrapper never repaired on existing installs [file:38]
- Fixed `is_local_request()` trusting entire RFC1918 on VPS installs [file:38]

## v1.2.5
- Fixed Docker compatibility in README and setup wizard [file:38]
- Added Docker-aware service watchdog and live data fallbacks [file:38]
- Added Docker-specific restart hint and host note in system health [file:38]

## v1.2.4
- Fixed fail2ban jail edits not applying live [file:38]
- Changed auto-update timer from daily to hourly and version-check based [file:38]

## v1.2.3
- Fixed missing NOPASSWD commands for sudoers update flow [file:38]

## v1.2.2
- Fixed fail2ban config handling to use `/etc/fail2ban/jail.local` [file:38]
- Preserved user customizations outside toolkit-managed jail block [file:38]
- Updated sudoers paths to match jail.local usage [file:38]

## v1.2.1
- Fixed fail2ban jail edit fields disappearing after save [file:38]
- Fixed fail2ban health scan sudo fallback issues [file:38]
- Added auto-update re-exec when update content changes [file:38]
- Added auto-create of update timer when missing [file:38]

## v1.2.0
- Fixed fail2ban access for non-root installs [file:38]
- Added fail2ban firewall-type detection and broader distro support [file:38]
- Raised default bantime for sshd and dashboard jails [file:38]
- Improved Raspberry Pi install handling and Node.js version checks [file:38]

## v1.1.66
- Fixed multiple dashboard crashes from undefined values [file:38]
- Fixed Security routing and fail2ban/UFW form issues [file:38]

## v1.1.65
- Fixed fail2ban exception cascade [file:38]
- Fixed earnings chart undefined values [file:38]
- Added fail2ban-client and config paths to NOPASSWD [file:38]

## v1.1.64
- Rewrote fail2ban jails to use fail2ban-client as primary source [file:38]
- Added UFW edit support and restored firewall refresh [file:38]

## v1.1.63
- Added firewallData prop and corrected iptables field names [file:38]
- Added sudo fallback for fail2ban on non-root installs [file:38]
- Added `/firewall` to fleet proxy whitelist [file:38]

## v1.1.62
- Fixed SecurityPage open crash and iptables column names [file:38]
- Fixed fail2ban ping behavior on non-root installs [file:38]

## v1.1.61
- Added `/firewall` whitelist support for fleet nodes [file:38]
- Loaded UFW rules from firewallData [file:38]
- Allowed editing all jails and saved external jails as overrides [file:38]

## v1.1.60
- Complete Security page rewrite for fail2ban and UFW management [file:38]
- Added `/firewall/fail2ban/start`, `/stop`, and `/reload` endpoints [file:38]
- Added running-state-aware jail loading [file:38]

## v1.1.59
- Fixed blank dashboard crash caused by orphaned module-level lines [file:38]

## v1.1.58
- Added all new security endpoints to fleet proxy whitelist [file:38]
- Fixed dashboard crash caused by React default export issues [file:38]

## v1.1.57
- Removed duplicate components that caused dashboard crashes [file:38]
- Added security endpoints to fleet proxy whitelist [file:38]

## v1.1.56
- Firewall card fail2ban now shows only status and counts [file:38]
- Manage link now points to Security page [file:38]

## v1.1.55
- Added install fail2ban button in Security page [file:38]
- Added active bans and unban buttons [file:38]
- Added backend fail2ban install endpoint [file:38]
- Removed old Fail2banManager modal [file:38]

## v1.1.54
- Removed incorrect toolkit.conf restriction text [file:38]

## v1.1.53
- Replaced dynamic Tailwind classes with static conditionals [file:38]

## v1.1.52
- Added Security button in bottom nav bar [file:38]
- Added full fail2ban and UFW management to Security page [file:38]

## v1.1.51
- Collapsed firewall card sections by default [file:38]
- Added manage panel behavior for fail2ban [file:38]

## v1.1.50
- Added fail2ban manager modal [file:38]
- Changed UFW rules to be collapsed by default [file:38]

## v1.1.49
- Added fail2ban status in firewall card [file:38]
- Added `/firewall/fail2ban/unban` endpoint [file:38]
- Added optional fail2ban install step in setup scripts [file:38]

## v1.1.48
- Fixed consumer ID copy scrolling issue [file:38]
- Moved network probes to top of consumer list [file:38]

## v1.1.47
- Fixed consumer ID copy focus scrolling issue [file:38]

## v1.1.46
- Fixed update.sh being killed by the service cgroup during update [file:38]

## v1.1.45
- Fixed consumer ID copy helper reference errors [file:38]

## v1.1.44
- Added SIGTERM handler so systemd does not restart during updates [file:38]
- Fixed backend restart/update race conditions [file:38]

## v1.1.43
- Fixed consumer ID copy remount issues from inline component definitions [file:38]

## v1.1.42
- Fixed update restart race condition [file:38]

## v1.1.41
- Replaced `grep -oP` with portable `awk` for PID extraction [file:38]

## v1.1.40
- Restored consumer ID popup copy behavior [file:38]
- Fixed `toFixed()` crashes on undefined values [file:38]

## v1.1.39
- Restored full consumer ID display [file:38]

## v1.1.38
- Fixed build-to-temp update flow [file:38]
- Removed `pkill -f` self-matching issue [file:38]
- Added verified mode warning [file:38]

## v1.1.37
- Removed `ExecStartPre pkill` self-kill issue [file:38]

## v1.1.36
- Fixed `ExecStartPre` heredoc command substitution issue [file:38]

## v1.1.35
- Added fallback for writing wireguard config on non-root installs [file:38]
- Added config files to NOPASSWD [file:38]

## v1.1.34
- Added `ExecStartPre` to ensure port 5000 is free before start [file:38]

## v1.1.33
- Killed process on port 5000 by PID [file:38]

## v1.1.32
- Waited for port 5000 to become free before starting [file:38]

## v1.1.31
- Killed leftover process on port 5000 after stop [file:38]

## v1.1.30
- Added Network Rewards section to Settle History [file:38]
- Added rewards transaction data to settle history response [file:38]

## v1.1.29
- Restart flow now uses systemd stop+start [file:38]
- Added `systemctl reset-failed` before start [file:38]
- Moved `StartLimitIntervalSec` and `StartLimitBurst` to `[Unit]` [file:38]
- Switched service file write to `$SUDO tee` [file:38]

## v1.1.28
- Fixed wireguard mode read/write handling [file:38]
- Fixed `toFixed()` on undefined session earnings [file:38]
- Changed license to AGPL-3.0 [file:38]

## v1.1.27
- Added update-in-progress screen [file:38]

## v1.1.26
- Moved system update logs out of `/tmp` [file:38]
- Auto-cleaned stale `/tmp` logs [file:38]
- Updated update status to read only `logs/update.log` [file:38]

## v1.1.25
- Replaced `systemctl restart` with `stop` + `start` [file:38]

## v1.1.24
- Skipped sudoers updates when unchanged [file:38]

## v1.1.23
- Added earnings efficiency breakdown by service type [file:38]
- Added configured node price legend [file:38]
- Merged `quic_scraping` into `scraping` [file:38]

## v1.1.22
- Fixed JSX syntax error in help section [file:38]

## v1.1.21
- Made `chown` commands conditional [file:38]

## v1.1.20
- Added CLI and help improvements [file:38]
- Added fleet Add Node URL auto-complete [file:38]
- Improved README and update documentation [file:38]

## v1.1.19
- Fixed root-owned `.git/objects` after sudo update [file:38]
- Added urgent notice for previous sudo update users [file:38]

## v1.1.18
- Removed outer sudo requirement from update.sh [file:38]
- Updated fleet update button to run full update flow [file:38]
- Fixed build file copy and node_modules handling [file:38]

## v1.1.17
- fix: `mystPrice` ReferenceError in fleet bar — undefined variable crash on load
- fix: `update.sh` no longer exits on frontend build failure — backend always restarts even when build fails

## v1.1.16
- feat: GitHub Actions CI workflow added
- docs: CHANGELOG added to repo

## v1.1.15
- Added net earned and fleet bar summaries [file:38]
- Added Ansible mass update section [file:38]
- Fixed unsettled display logic and Hermes channel row [file:38]

## v1.1.14
- Added fleet aggregate bars for MYST and fiat values [file:38]
- Fixed confusing unsettled fallback behavior [file:38]

## v1.1.13
- Added Docker support for fleet update [file:38]
- Documented fleet update manager and Docker stats [file:38]

## v1.1.12
- Fixed fleet update on non-root installs [file:38]

## v1.1.11
- Fixed orphaned visible text in Data Management panel [file:38]

## v1.1.10
- Fixed fleet update on non-root installs to use stop/start flow [file:38]

## v1.1.9
- Fixed firewall panel JSX bracket error [file:38]

## v1.1.8
- Fixed orphaned visible text in mobile view [file:38]
- Hid redundant fleet card label at 100% uptime [file:38]

## v1.1.7
- Fixed firewall panel JSX closing bracket error [file:38]

## v1.1.6
- Added inline firewall panel [file:38]
- Added legacy port detection and removal [file:38]
- Reduced version check cache time [file:38]

## v1.1.5
- Added Open/Verified/Off selector for public service [file:38]
- Fixed deprecated ports and port labels [file:38]

## v1.1.4
- Added tunnel counter tooltip and firewall help text [file:38]
- Fixed firewall cleanup chain handling [file:38]

## v1.1.3
- Reverted broken `get_sessions` behavior from v1.1.2 [file:38]
- Added isolated `/sessions/live` endpoint [file:38]

## v1.1.2
- Attempted realtime active session fetch, later reverted [file:38]

## v1.1.1
- Fixed update endpoint SSH key detection and HOME handling [file:38]
- Added update status endpoint [file:38]

## v1.1.0
- Added public service 3-mode selector [file:38]
- Added sessions pagination support [file:38]
- Added default TequilAPI credentials hint [file:38]
- Added config verification after active-services write [file:38]
- Added earnings sanity checks [file:38]
- Added docs for new features [file:38]

## v1.0.30
- Fixed chart colors to use inline hex [file:38]

## v1.0.29
- Added Fleet Update Manager [file:38]
- Added node offline warning [file:38]
- Added reliable analytics bar colors [file:38]

## v1.0.28
- Fixed systemd service `StartLimitIntervalSec` placement [file:38]
- Fixed myst service detection [file:38]

## v1.0.27
- Fixed wireguard active-services handling [file:38]
- Fixed monitoring/noop service toggle blocking [file:38]
- Fixed TequilAPI error logging [file:38]

## v1.0.26
- Fixed access_policies handling in start_service and metrics refresh [file:38]

## v1.0.25
- Changed default chart period from 90d to 30d [file:38]

## v1.0.24
- Changed transfer chart color to indigo [file:38]

## v1.0.23
- Merged quic_scraping into scraping [file:38]

## v1.0.22
- Fixed ghost deduplication and consumer counter [file:38]

## v1.0.21
- Fixed active-services config and TequilAPI port auto-correction [file:38]

## v1.0.20
- Fixed fleet routing and merged QUIC Scraping into B2B Data Scraping [file:38]

## v1.0.19
- feat: adaptive CLI start menu per install type (Type 1/2/3 tonen andere opties)
- feat: detect and separate Mysterium network probes in Consumers tab with probe indicator
- fix: missing `fmtType` in 5 mobile views
- fix: `duration_secs` added to live sessions for working Duration sort
- fix: reset archive offset on fleet node switch
- fix: deduplicate ghost reconnect sessions per consumer/service-type pair
- fix: `_run` input_data encoding bug
- fix: `cpu_governor` persist via tee + systemd service
- fix: replace `sudo bash` with `sudo tee` for all health fix file writes
- fix: expand sudoers with missing sysctl/modules-load.d/chmod paths
- fix: `fmtType` applied to ServiceSplitChart legend and SVG tooltips
- fix: sync `_DEFAULT_RETENTION` with actual setup defaults
- docs: README menu option numbers corrected per install type

## v1.0.18
- fix: phantom active sessions from stale WireGuard interfaces
- fix: History tab showing wrong node archive in fleet mode

## v1.0.17
- feat: context-aware health profiling (Laptop, VM/VPS, LXC, Raspberry Pi, Bare metal, Alpine)
- fix: quieter toast notifications

## v1.0.16
- fix: `TOOLKIT_DIR` path bug in root `setup.sh`
- fix: NodeSource Node.js 20 install updated
- fix: `fmtType` missing in mobile views
- fix: Network Quality card display
- docs: Ubuntu and Pi OS compatibility noted in README

## v1.0.15
- feat: uniform 7d/30d/90d/1y/All period selectors across all charts
- feat: data retention raised to 365 days default
- feat: new analytics charts (service split, earnings efficiency)
- fix: auto-detect OS timezone, persist to `setup.json`
- fix: earnings chart daily bucketing to local time
- fix: service-split and earnings-efficiency endpoints use raw tokens/bytes columns

## v1.0.14
- fix: service-split and earnings-efficiency endpoints: `SessionDB.init()` and local timezone bucketing

## v1.0.13
- fix: auto-detect OS timezone and persist to `setup.json`
- feat: fleet uptime/efficiency, MYST/GB per session, service split chart, earnings efficiency chart
- fix: dynamic retention-aware period selectors and All button for quality/system history
- fix: service stop stale UUID and scraping/quic_scraping functional link

## v1.0.12
- fix: sudo LXC/root compatibility
- fix: venv pre-install check
- fix: Node.js false positive version detection
- fix: README port references corrected

## v1.0.11
- fix: earnings UTC timezone handling
- fix: rate-limit snapshot
- fix: system health inline expand
- fix: logs position
- fix: `fetchArchive` fleet routing
- fix: QUIC label display

## v1.0.10
- feat: node update badge in dashboard
- feat: editable data retention per node
- feat: `data_retention` added to `setup.json`

## v1.0.9
- fix: fleet routing fix for quality/metrics history
- fix: quality/metrics history reload on node switch
- fix: duplicate data management card removed

## v1.0.7
- feat: extended system metrics (tunnels, speed, latency, temperatures)
- fix: update badge visible in fleet overview
- fix: metrics reading from correct cache tier
- fix: system metrics DB writing speed/latency/tunnels from wrong cache tier

## v1.0.4
- feat: update check badge
- feat: extended system metrics (tunnels, speed, latency, temperatures)
- fix: config ownership after sudo operations

## v1.0.3
- Fixed SessionDB migration issue with missing provider_id [file:38]

## v1.0.2
- Fixed chown on config after sudo operations [file:38]

## v1.0.1
- Initial post-launch bug fixes [file:38]

## v1.0.0
- Initial public release [file:38]
- Flask/React monitoring dashboard for Mysterium VPN node operators [file:38]
- Earnings tracking, session analytics, node quality monitoring [file:38]
- Fleet mode for multi-node monitoring [file:38]
- System health panel with adaptive CPU/conntrack tuning [file:38]
- 11 themes, autostart, remote node restart/settle/payment configuration [file:38]
