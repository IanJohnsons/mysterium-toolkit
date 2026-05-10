# Mysterium Node Toolkit

![Version](https://img.shields.io/badge/version-1.1.26-brightgreen) ![License](https://img.shields.io/badge/license-CC%20BY--NC--SA%204.0-blue) ![Platform](https://img.shields.io/badge/platform-Linux-lightgrey) ![Python](https://img.shields.io/badge/python-3.8%2B-blue)

A professional monitoring and management dashboard for [Mysterium Network](https://mysterium.network) VPN node operators. Runs fully local on your node machine — no cloud account, no third-party service, no data leaving your server.

**Author:** Ian Johnsons — [github.com/IanJohnsons](https://github.com/IanJohnsons)  
**License:** CC BY-NC-SA 4.0 — free for personal and community use, not for commercial use, credit the author if redistributed  
**Community:** Mysterium Network Telegram

---

> **⚠ One-time fix required if you previously ran `sudo ./update.sh`**  
> Running update with outer sudo causes `.git/objects` to become root-owned, breaking future `git pull` calls.  
> Run this once to fix it:
> ```bash
> sudo chown -R $USER:$USER ~/mysterium-toolkit
> ```
> After v1.1.18, `./update.sh` (without sudo) handles all privileges internally. The fleet update button works automatically going forward.

---

## Install

```bash
git clone https://github.com/IanJohnsons/mysterium-toolkit
cd mysterium-toolkit
sudo ./setup.sh
```

`setup.sh` is fully interactive. Follow the prompts from start to finish.

> Always clone to a fixed directory name without a version number. The autostart systemd service points to the directory path — if the path changes, autostart breaks.

---

## What setup.sh does — full walkthrough

---

### Step 0 — Node detection

The toolkit needs a running Mysterium node to monitor. This is the first thing setup.sh checks. `node_install_guide.py` takes over and looks four ways:

1. systemd service `mysterium-node` — active status
2. Docker container named `myst` — running state
3. Process list — `myst` binary
4. TequilAPI responding on `localhost:4449`

**Node found** — prints `✓ Mysterium node detected` and hands control back to setup.sh.

**No node found** — shows:

```
⚠ No local Mysterium node detected on this machine.

  Choose how to continue:
    1. Remote mode  — my node runs on ANOTHER machine (enter its IP in the next step)
    2. Fleet mode   — I manage multiple remote nodes via nodes.json
    3. Install node — install a Mysterium node on THIS machine first
    4. Exit
```

Choosing **option 3** hands control to `node_installer.py`, which installs the node completely. Only after the node is installed and running does control return to setup.sh. Options 1 and 2 continue without a local node — the toolkit can monitor a node running on another machine once the backend is running and the node IP is entered in the setup wizard.

---

### Step 0 — Node installer

> Only reached if you had no node and chose option 3 above. If your node was already detected, this section is skipped entirely.

`node_installer.py` takes over, detects your OS and package manager, and shows the available install methods with the recommended option for your distro listed first:

```
ℹ Detected OS: [your distro]
ℹ Package manager: [apt/dnf/pacman/apk]
```

```
1. APT install       (recommended for Debian / Ubuntu / Parrot / Kali)
2. DNF/YUM install   (recommended for Fedora / RHEL / Rocky / Alma)
3. AUR install       (recommended for Arch / Manjaro / EndeavourOS)
4. Docker install    — works on any Linux
5. Manual .deb       — specific version, auto-fetched from GitHub
6. Official script   — curl | bash
0. Cancel
```

On Alpine, Docker is the only option — Mysterium provides no APK package.

---

#### APT install — Debian / Ubuntu / Parrot / Kali

```
· Detected: [distro name]
· The installer will run automatically. This may take 1-3 minutes.
  Continue? [Y/n]:
```

Runs the official Mysterium install script:

```bash
curl -sSf https://raw.githubusercontent.com/mysteriumnetwork/node/master/install.sh | bash
```

---

#### Docker install — any distro including Proxmox / LXC / KVM / Alpine

```
· Docker found: [version]

· This will create a Docker container named 'myst' with:
    · Port 4449 mapped (TequilAPI)
    · Volume 'myst-data' for persistent storage
    · NET_ADMIN capability (required for WireGuard)

  Continue? [Y/n]:
```

If Docker is not installed, the installer installs Docker Engine automatically first. Then runs:

```bash
docker run --cap-add NET_ADMIN -d --name myst --restart=unless-stopped \
    -p 4449:4449 \
    -v myst-data:/var/lib/mysterium-node \
    mysteriumnetwork/myst:latest \
    service --agreed-terms-and-conditions
```

On success:

```
✓ Container is running!
· TequilAPI available at: http://localhost:4449
```

> **Proxmox / LXC containers:** enable `NET_ADMIN` before running. In the Proxmox web UI go to container → Options → Features → enable nesting. In the LXC config add `lxc.cap.keep: net_admin`. Without this, WireGuard tunnel creation fails.

---

#### AUR install — Arch / Manjaro / EndeavourOS

Checks for `yay` or `paru`. If found, installs `mysterium-node` from AUR. If neither is found, falls back to Docker automatically.

---

#### DNF / YUM install — Fedora / RHEL / Rocky / AlmaLinux

Runs the official Mysterium install script. If it fails, asks you to paste a direct RPM download URL from the [GitHub releases page](https://github.com/mysteriumnetwork/node/releases).

---

#### Official script — universal

```bash
curl -sSf https://raw.githubusercontent.com/mysteriumnetwork/node/master/install.sh | sudo bash
```

---

#### Manual .deb

Auto-fetches the latest release from GitHub with architecture detection (amd64, arm64, armhf) and asks you to confirm. You can also paste a direct URL or a local file path.

---

#### After install — set node password

Immediately after a successful install, `node_installer.py` sets the TequilAPI password:

```
Set Node Password
· Setting TequilAPI password via myst config set...

  Choose a TequilAPI password (press Enter to use default 'mystberry'):
```

Runs `myst config set tequilapi.auth.password YOUR_PASSWORD`, then restarts the node. On success:

```
✓ Password set successfully.
· Restarting node to apply password...
✓ Node restarted with new password.
· Remember this password — you need it in the toolkit setup wizard.
```

If the automatic method fails, the manual fallback is shown:

```
· Set it manually: myst config set tequilapi.auth.password YOUR_PASSWORD
· Then restart:    sudo systemctl restart mysterium-node
```

---

#### After password — start all services

`node_installer.py` starts all Mysterium services automatically:

- Waits for TequilAPI to be ready (up to 10 retries)
- Authenticates and reads your node identity
- Starts: `wireguard`, `dvpn`, `data_transfer`, `scraping`, `noop`, `monitoring`
- Persists active services via `myst config set active-services`

```
· Starting all Mysterium services...
· Identity: 0x...
✓ wireguard started
✓ dvpn started
✓ data_transfer started
· noop — skipped or already running
· monitoring — skipped or already running
✓ Services persisted: wireguard,dvpn,data_transfer
```

---

#### After services — complete registration in the browser

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
IMPORTANT: Complete your node setup in the browser:

  1. Open http://YOUR_SERVER_IP:4449/ui
     (replace YOUR_SERVER_IP with this machine's IP)

  2. Log in and accept the Terms & Conditions
  3. Claim your node on mystnodes.com:
     Settings → MMN API Key → paste your key
  4. Set your payout wallet (beneficiary address)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

· Then return here and continue the toolkit setup wizard.
```

> **When creating your mystnodes.com account — use email + password, not Google login.** Google login does not let you change your password or recover your account.

`node_installer.py` finishes and **hands control back to setup.sh**.

---

### Choose install type

Back in setup.sh, now that the node is running:

```
1. Full install        — Node on this machine. Full dashboard, CLI, all features.
                         Default. Use this for your main node machine.

2. Fleet master        — Central dashboard to monitor multiple remote nodes.
                         Installs full toolkit. Helps configure nodes.json after setup.

3. Lightweight backend — Backend only, no browser dashboard.
                         For remote nodes monitored by a fleet master.
                         No Node.js/npm needed. Minimal resources. Serves /peer/data.

Select (1-3) [default: 1]:
```

---

### Pre-flight checks

- Detects your package manager: apt · dnf · yum · pacman · apk
- Checks Python 3.8+ — exits with install instructions if missing or too old
- Checks pip — installs it if missing
- Lists optional tools already present: vnstat, ethtool, ufw, docker, node, npm
- Warns if Node.js/npm not found (web dashboard won't work without it — CLI still works)

---

### Step 0.5 — Stop running toolkit service

If a `mysterium-toolkit` systemd service is already active, it is stopped and disabled before continuing.

---

### Step 1 — Kill old processes

Kills any leftover `app.py`, `vite`, and `npm start` processes from previous toolkit installs.

---

### Step 2 — Scan for previous toolkit installations

`env_scanner.py` scans the machine for any earlier toolkit directories.

---

### Step 2.5 — Data migration

- Removes empty database placeholders that may have shipped in the release zip (these would block migration)
- `migrate_data.py` scans for a previous install and reports what it found
- If found: offers to copy earnings history, uptime log, and node config
- After copying: offers to remove old installs to reclaim disk space

---

### Step 3 — Check existing setup

If a `venv/` and `.env` already exist in the directory, setup asks:

```
1. Update existing setup (keep config)
2. Fresh install (delete everything)
3. Exit
```

Choosing 1 updates Python packages and rebuilds the frontend, then jumps straight to the firewall step.

---

### Step 4 — Install system tools

The following are installed automatically if missing:

| Tool | Purpose |
|------|---------|
| `vnstat` | Network traffic tracking |
| `ethtool` | NIC interrupt coalescing and checksum |
| `curl` | API calls and health checks |
| `iputils` (ping) | Port reachability checks |
| `lm-sensors` | CPU temperature monitoring |
| `sqlite3` | Database CLI for diagnostics |
| `irqbalance` | CPU load balancing across cores |
| `conntrack` | Connection tracking table reads |
| `nodejs` / `npm` | Frontend build — Type 1 / 2 only |

A udev rule is written to `/etc/udev/rules.d/99-myst-vnstat.rules` so every `myst*` tunnel interface is automatically registered with vnstat the moment Mysterium creates it — even before the toolkit runs.

vnstat day retention is set to 1095 days (3 years) in `/etc/vnstat.conf`.

---

### Step 5 — Create Python virtual environment

Creates `venv/` — an isolated Python environment. All toolkit packages are installed here, separate from your system Python.

---

### Step 6 — Install Python packages

Installs all dependencies from `requirements.txt` into `venv/`.

---

### Step 7 — Build frontend

Types 1 and 2 only. Copies build config from `.build/`, runs `npm install` and `npm run build`, produces `dist/`, then removes `node_modules` (~88 MB freed). Skipped entirely for Type 3.

---

### Step 7.5 — Detect existing configuration

If `config/setup.json` already exists and is valid, the setup wizard is skipped entirely. `.env` is reconstructed automatically from the existing config. Your dashboard password, API key, node password, and all settings are preserved — no action needed.

---

### Step 8 — Setup wizard

Connects the dashboard to your node and sets up authentication. Two modes:

```
1. Easy   — node on this machine, auto-detects port and config
2. Custom — node on another machine, different IP, or manual settings
```

#### Easy mode

- Scans port 4449 for a running node
- If found: confirms port and node version automatically
- Asks for your Node UI password:

```
· Your node's TequilAPI is on port [port].
  Enter the password you set in the Node UI (http://localhost:4449).
  If you never set one, try leaving it blank or use 'mystberry'.

  Node UI password (press Enter if none):
```

- Dashboard port: 5000 by default, auto-suggests alternative if 5000 is in use
- Timezone: auto-detected from system
- Optionally asks for your Polygon wallet address (0x...)

#### Custom mode

**Step 1 — Node location**

```
1. This computer (localhost)
2. Another computer on my network (LAN) — enter IP
3. A remote server (VPS/Cloud) — enter IP or domain
```

**Step 1b — Docker auto-detection**

If localhost is selected, the wizard scans running Docker containers for a `myst` image. If found, the port is read automatically:

```
✓ Docker container detected: myst
✓   Mapped TequilAPI port: 4449
    We'll use this port automatically.
```

**Step 2 — TequilAPI port**

Default 4449. The wizard warns: *"PORT is a NUMBER, not an API key string!"*

**Step 3 — TequilAPI authentication**

```
TequilAPI Authentication — this is your Node UI password.

Where to find your password:
  Open http://localhost:4449/ui in your browser.
  The password was shown ONCE when you first set up your node.
  It looks like: xK9#mP2$vL7@nQ4w  (random, unique per install)

  NOT 'mystberry' — that is an old default newer nodes no longer use.
  If you forgot your password, reset it with:
    sudo myst account --config-dir=/etc/mysterium-node reset-password

The username is always: myst
```

**Step 4 — Connection test**

Tests the connection live. If it fails, shows exactly what went wrong and lets you retry or continue anyway.

**Step 5 — Dashboard port**

Default 5000.

**Step 5.5 — Timezone**

Auto-detected from system. Used for daily/monthly resets in earnings and traffic tracking. Change later in `config/setup.json`.

**Step 6 — Dashboard authentication**

```
1. API Key (recommended) — paste a secret key in the login screen
2. Username + Password   — classic login, username is always: admin
3. No auth               — local network only, NOT recommended
```

For **API Key** — the wizard generates a key if you leave the field blank, then shows:

```
============================================================
  IMPORTANT — SAVE YOUR API KEY
============================================================

  API Key: <your-key-here>

  COPY/PASTE this key in the login screen — never type it.
  Typing causes typos (i vs l, 5 vs 2, 0 vs O, etc).
  Store it in a password manager or secure note now.
  Find it later in: .env  and  config/setup.json
============================================================

  Press Enter to continue...
```

The wizard does not continue until you press Enter.

For **Username + Password** — generates a password if you leave it blank:

```
============================================================
  IMPORTANT — SAVE YOUR CREDENTIALS
============================================================

  Username : admin
  Password : <your-password-here>

  The login screen asks for these credentials.
  Find them later in: .env  and  config/setup.json
============================================================

  Press Enter to continue...
```

**Optional extras:**

- Polygon wallet address (auto-detected from settlement history if skipped)
- Polygonscan API key — free at etherscan.io → My Account → API Keys. Without it: wallet balance updates once/hour. With it: real-time.
- Log level: INFO (default) / WARNING / DEBUG

After saving, the wizard shows credentials one final time and waits for a second *"Press Enter once you have saved..."* before continuing.

---

### Step 8.5 — Fleet master configuration (Type 2 only)

Creates a `config/nodes.json` template and explains each field.

---

### Step 11 — Kernel tuning

Skipped in remote mode and for Type 3. Skipped if passwordless sudo is not available — shown with the manual command to apply later. Detects VPS/VM automatically. See [Kernel Tuning](#kernel-tuning).

---

### Step 11.5 — Firewall

Skipped for Type 3. See [Firewall](#firewall).

---

### Step 12 — Systemd service and sudoers

Creates or updates `/etc/systemd/system/mysterium-toolkit.service` and writes `/etc/sudoers.d/mysterium-toolkit`.

---

### Step 13 — Done

Prints your dashboard URL and opens `start.sh` automatically:

```
✓ Dashboard:  http://YOUR_IP:5000
✓ Config:     config/setup.json
```

**Type 1 / Type 2 (full / fleet master):**

| Option | Action |
|--------|--------|
| 1 | Start Dashboard |
| 2 | Stop Everything |
| 3 | View Logs |
| 4 | CLI Dashboard (Terminal UI) |
| 5 | Rebuild Frontend |
| 6 | System Diagnostics |
| 7 | Maintenance — scan, cleanup, uninstall |
| 8 | Autostart on Boot — enable/disable |
| 0 | Exit |

**Type 3 (lightweight backend):**

| Option | Action |
|--------|--------|
| 1 | Start Backend |
| 2 | Stop Backend |
| 3 | View Logs |
| 4 | System Diagnostics |
| 5 | Maintenance — scan, cleanup, uninstall |
| 6 | Autostart on Boot — enable/disable |
| 0 | Exit |

---

## After setup

```bash
# Open the control menu — start, stop, autostart and more
./start.sh

# Stop the toolkit
./stop.sh
```

Open the dashboard: `http://localhost:5000`  
From your phone or any device on your network or the internet: `http://YOUR_MACHINE_IP:5000`

---

## Update

```bash
cd mysterium-toolkit
./update.sh
```

No `sudo` needed — the script handles privileges internally via `$SUDO`. Pulls the latest code, rebuilds the frontend, updates packages and sudoers, restarts the backend. `config/setup.json` and `config/nodes.json` are backed up before the pull and restored automatically. Your dashboard password, API key, node password, and all settings survive the update — no re-configuration needed.

**Fleet update button** — in the fleet dashboard each node card shows an ↑ Update button when a new version is available. Updates all nodes in parallel without SSH access needed.

---

## CLI (Terminal Dashboard)

```bash
python cli/dashboard.py
python cli/dashboard.py --url http://remote-node:5000 --interval 10
```

Lightweight terminal UI using curses — no browser needed.

**Pages:** `1` Status (node info, resources, quality) · `2` Earnings (unsettled, net earned, fiat value, history chart)

**Keys:** `Tab`/`1-2` page · `r` refresh · `t` theme · `T` test node · `h` health · `c` config · `w` restart node · `$` settle · `?` help · `q` quit · `+/-` adjust interval

---

## Re-install on existing machine

If you run `setup.sh` on a machine that already has a configured toolkit, it detects the existing `config/setup.json` and asks whether to keep it. Choosing yes skips the entire setup wizard — your settings are preserved and databases are migrated automatically.

---

## What It Does

The dashboard runs in your browser — on the same machine, on your phone, or from anywhere in the world as long as port 5000 is reachable. Every action below is available remotely from any device with a browser.

### Earnings

- **Unsettled MYST** — live balance not yet moved on-chain
- **Lifetime gross** — all-time cumulative earnings before Hermes fee
- **Settled balance** — MYST ready to withdraw from the payment channel
- **Daily / Weekly / Monthly delta** — computed from SQLite snapshots taken every 10 minutes. Shows *BUILDING* until enough history exists
- **Live MYST price** — EUR and USD conversion via CoinPaprika + Frankfurter ECB. Both free, no account, no API key required
- **Earnings history chart** — Daily / Weekly / Monthly / All tabs, auto-scales to your history length
- **Selective data cleanup** — delete earnings snapshots by date range, two-click confirmation

### Session archive

Every session is saved to SQLite with token values frozen the moment the session ends — before Mysterium zeroes them after settlement. The archive survives node restarts, re-installs, and settlements. View full history, filter by country, service type, or date.

### Node quality

- Discovery quality score, latency, and bandwidth from the Mysterium Discovery API
- Uptime 24h and 30d — tracked locally, independent of the Discovery API
- Packet loss percentage, connected percentage
- Expandable sparkline — quality score, latency, and bandwidth over 7 / 30 / 90 / 365 days / All

### Session analytics

- Active tunnels — live consumer connections with identity and service type. Mysterium network quality monitoring bots are automatically detected and labelled with 🔧, separated from paying consumers in the Consumers tab
- Consumer breakdown by country and service type
- Full session history with duration, data transferred, earnings per session, and **MYST/GB efficiency** per session (shown for sessions >1 MB to avoid misleading values on tiny sessions)
- **Service Split Over Time** — stacked bar chart of daily earnings by service type (7d / 30d / 90d / 1y / All). Reveals trends in scraping vs VPN vs Public traffic over time
- **Earnings Efficiency** — MYST per GB transferred as a daily timeseries. Detects when your node forwards more data but earns less per byte

### Public service mode (wireguard)

The **Public** service (wireguard) has three configurable modes — controlled via the Running Services card:

| Mode | Who can connect | Node config flag |
|---|---|---|
| **Open** | Everyone — including Mysterium Dark, 3rd party apps | `wireguard.access-policies = ""` |
| **Verified** | Mysterium-registered consumers only (on-chain identity + MYST stake) | `wireguard.access-policies = "mysterium"` |
| **Off** | No new connections. Existing WireGuard tunnels persist until natural disconnect | service stopped |

> **Note:** Individual consumer blocking is not possible at the Mysterium node API level. The Verified mode is the narrowest filter available — it restricts to the Mysterium identity network. Consumer payments are enforced automatically by Hermes (off-chain promise signing) — consumers without funded channels are rejected before any data flows.

### Service types (Mysterium node core)

| API type | Dashboard label | Access policy |
|---|---|---|
| `wireguard` | Public | configurable (see above) |
| `dvpn` | VPN | mysterium |
| `scraping` + `quic_scraping` | B2B Data Scraping | mysterium |
| `data_transfer` | B2B VPN and data transfer | mysterium |
| `monitoring` | Monitoring (internal) | node-managed |

### On-chain wallet

- Live MYST balance on Polygon via Polygonscan
- Full settlement history
- Beneficiary (payout) address display

### Data traffic

VPN traffic vs total NIC traffic vs overhead — Today / 7d / 30d / 90d / 1y / All, backed by vnstat. Separate per-interface tracking for `myst*` tunnel interfaces via udev auto-registration.

### Node control

All node control actions are authenticated and available remotely from any browser:

- **Restart node** — tries systemctl → service → Docker → TequilAPI stop/start in sequence. Works on bare metal, VM, and Docker installs without any manual SSH
- **Settle MYST on-chain** — triggers settlement via TequilAPI transactor. Fetches identity and hermes_id automatically, handles all endpoint variants across node versions
- **Payment config tuner** — read and write all 7 payment configuration keys live via `myst config set`, without editing config files manually:

| Key | Default | Description |
|-----|---------|-------------|
| `payments.zero-stake-unsettled-amount` | 5.0 MYST | Auto-settle threshold (zero-stake) |
| `payments.unsettled-max-amount` | 10.0 MYST | Maximum unsettled before forced settlement |
| `payments.min_promise_amount` | 0.05 MYST | Minimum promise value to accept a session |
| `payments.provider.invoice-frequency` | 60s | How often to send payment invoices during a session |
| `pingpong.balance-check-interval` | 90s | Consumer balance poll interval |
| `pingpong.promise-wait-timeout` | 180s | How long to wait for a consumer promise |
| `payments.settle.min-amount` | 1.0 MYST | Minimum balance required for manual settlement |

Two built-in presets: **Node Defaults** and **High Load** (optimised for 50+ concurrent sessions — raises thresholds and intervals to reduce rate limiting).

### System health

13 subsystems monitored continuously. Every fix can be applied with one click and locked to survive reboots — from anywhere, including your phone:

| Subsystem | Checks | Fix action |
|-----------|--------|------------|
| Connection Tracking | Table fill %, auto-scales with tunnels | Expand to load-appropriate tier |
| CPU Load Balancing | irqbalance and RPS | Install irqbalance, set RPS to all cores |
| Mysterium Service | Node process and systemd / Docker status | Restart node |
| Kernel Network Tuning | 12 sysctl parameters | Apply safe network buffer values |
| NIC Interrupt Coalescing | rx-usecs, adaptive-rx | Set rx-usecs=250µs |
| NIC Checksum Offload | rx_csum_offload_errors | Disable faulty RX checksum |
| Firewall Backend | iptables-legacy vs nftables conflict | Switch iptables alternative |
| Port Reachability | TequilAPI and service ports | Restart node if unreachable |
| Stale Processes | Orphaned toolkit PIDs | Terminate stale processes |
| Auto-RPS Watcher | systemd timer for VPN interface tuning | Install watcher timer |
| Swap / Memory | Swap size and swappiness | Create 4 GB swapfile |
| CPU Governor | Per-core governor, auto-adjusts with load | Applied automatically |
| BBR Congestion Control | tcp_congestion_control | Enable BBR and fq |

**Fix & Lock** — apply a fix and persist it so it survives the next reboot. **Unlock** — remove the persisted setting and revert to system defaults.

The health panel automatically detects your hardware profile at startup and adjusts its checks accordingly — you only see warnings that are relevant to your setup.

| Profile | Detected by | Behaviour |
|---|---|---|
| **Laptop** | `/sys/class/power_supply/BAT*` | CPU governor warnings suppressed — OS manages governor for battery/thermal |
| **VM / VPS** | `systemd-detect-virt` | CPU governor and bare-metal NIC checks skipped — hypervisor manages these |
| **LXC / Container** | `systemd-detect-virt`, cgroup | Kernel sysctl tuning checks skipped — host controls these values |
| **Raspberry Pi** | `/proc/device-tree/model` | ARM-aware checks, Pi-specific false positives removed |
| **High RAM (8+ GB)** | `psutil` | Missing swap downgraded from critical to warning |
| **Bare-metal server** | None of the above | All checks active — full optimisation recommended |

### System metrics history

CPU%, RAM%, disk%, and CPU temperature as sparklines over 1 / 3 / 7 / 14 / 30 days. Sampled every 5 minutes. Loads on demand — no background requests until expanded.

### Adaptive subsystems

Two subsystems adjust automatically every 10 minutes with no manual action:

**CPU Governor** — scales with active session count:

| Sessions | Governor | Effect |
|----------|----------|--------|
| 0 | `powersave` | Minimum frequency — CPU stays cool |
| 1–5 | `schedutil` | Kernel-managed — ramps instantly under load |
| 6+ | `performance` | Maximum throughput |

**Connection Tracking** — scales with active VPN tunnels:

| Tunnels | conntrack max |
|---------|--------------|
| 0–4 | 128,000 |
| 5–19 | 256,000 |
| 20+ | 512,000 |

### Data Management

Full control over all 7 persistent databases from the dashboard. Delete by type, by date range, or clear all. Two-click confirmation on all destructive actions. Automatic daily pruning within configured retention windows.

### Themes

11 built-in themes: Emerald · Cyber · Sunset · Violet · Crimson · Matrix · Phosphor · Ghost · Midnight · Steel · Military

---

## Installation Types

| Type | Installs | Use for |
|------|----------|---------|
| **Type 1 — Full** | Backend, web dashboard, CLI, kernel tuning, firewall | Your main node machine — full remote control from any device |
| **Type 2 — Fleet Master** | Full install + all Type 1 features + guided nodes.json setup | Central machine managing and controlling multiple remote nodes |
| **Type 3 — Lightweight** | Backend only, no frontend, no Node.js | Remote node monitored and controlled by a fleet master |

### Type 1 — Full install

Everything runs on the node machine itself. The web dashboard is served directly from this machine on port 5000. Access it from your phone, laptop, or any browser — locally or remotely. All node control actions (restart, settle, health fixes, payment config) run directly on this machine.

### Type 2 — Fleet Master

Installs the full toolkit plus fleet management. The central dashboard shows all registered remote nodes in a single view. For each remote node the fleet master can:

- View all earnings, sessions, quality, traffic, and system health data
- Restart the remote node
- Trigger settlement on the remote node
- Apply and persist system health fixes on the remote node
- Read and write payment config on the remote node
- View earnings chart, traffic history, and session archive from the remote node
- Manage data retention on the remote node

All remote control actions are proxied through the fleet master — the remote node's API key never leaves the server side.

### Type 3 — Lightweight

Backend only — no web dashboard, no Node.js required. Minimal resource usage. Runs on the remote node machine and serves `/peer/data` so the fleet master can read all metrics from it. All monitoring and control is handled by the fleet master.

---

## Autostart

Open `./start.sh` → option 8 — **Autostart on Boot** (Type 1/2) or option 6 (Type 3).

Installs a systemd service that starts automatically at boot, after the Mysterium node service, and restarts on crash. Works on laptops and headless VPS servers — no login required.

> **Type 3 (lightweight) nodes:** start the backend manually first via `./start.sh` → option 1 and verify it runs, then activate autostart via option 6. The systemd service needs the venv and config to exist before it can start at boot.

```bash
sudo systemctl status mysterium-toolkit
sudo journalctl -u mysterium-toolkit -f
```

---

## Fleet Mode

Each node runs its own toolkit backend. The fleet master reads data from each node over HTTP using its API key. Data is never mixed between nodes.

### Setup

1. Install the toolkit on each node — Type 1 for full local access, Type 3 for lightweight remote-only
2. Find each node's API key in `config/setup.json` → `dashboard_api_key`
3. Ensure port 5000 is reachable from the fleet master (port forward if behind NAT)
4. Create `config/nodes.json` on the fleet master machine:

```json
{
  "nodes": [
    {
      "id": "vps",
      "label": "My VPS Node",
      "url": "http://localhost:4449",
      "toolkit_url": "http://localhost:5000",
      "toolkit_api_key": "VPS_API_KEY_HERE"
    },
    {
      "id": "home",
      "label": "Home Node",
      "url": "http://YOUR_HOME_IP:4449",
      "toolkit_url": "http://YOUR_HOME_IP:5000",
      "toolkit_api_key": "HOME_API_KEY_HERE"
    }
  ]
}
```

Hot-reload: edit `nodes.json` while running — changes apply within 30 seconds.

### Fleet Update Manager

The fleet dashboard shows a version badge per node and an **↑ Update** button when a newer version is available on GitHub. Clicking it triggers a remote update on that node. An **↑ Update All** button updates all nodes in parallel.

How the update works per install type:

| Install type | Detection | Update method |
|---|---|---|
| Root (VPS, bare metal) | `getuid() == 0` | Full `update.sh` — pip deps, npm build, service restart |
| Non-root systemd (desktop, Pi) | systemd present | `git pull` + `systemctl stop` + `systemctl start` |
| Docker | `/.dockerenv` present | `git pull` + process exit → container restarts automatically |

**Docker requirement:** the container must be started with `--restart=always` or `--restart=unless-stopped` so it restarts automatically after the process exits during update.

**Note:** `./update.sh` handles everything — git pull, pip deps, frontend build, service restart. No outer sudo needed. The script uses `$SUDO` internally for privileged commands. On root installs (VPS) simply run `./update.sh` as root.

### Advanced: Mass Update via Ansible

For operators running 10+ nodes, [Ansible](https://www.ansible.com) provides a powerful alternative to the fleet update button — works even when the toolkit is down, scales to 100+ nodes, gives per-node terminal logs.

> Credit: this approach was suggested by a Mysterium community member. Thanks for sharing operational knowledge.

**Install Ansible:**
```bash
pip install ansible
# or: sudo apt install ansible
```

**`ansible.cfg`** (in your working directory):
```ini
[defaults]
remote_user = root
inventory = nodes.txt
host_key_checking = False
```

**`nodes.txt`** — one IP per line:
```
203.0.113.10
203.0.113.20
192.168.1.50
```

**Update all nodes:**
```bash
# SSH key (recommended)
ansible all --private-key ~/.ssh/id_rsa -m shell -a "bash ~/mysterium-toolkit/update.sh"

# SSH + sudo password prompt
ansible all -k -K -m shell -a "bash ~/mysterium-toolkit/update.sh"
```

**Mixed installs** (different users/paths per node) — use host variables in `nodes.txt`:
```ini
[vps]
203.0.113.10 ansible_user=root toolkit_path=/root/mysterium-toolkit

[desktop]
203.0.113.20 ansible_user=user toolkit_path=/home/user/mysterium-toolkit
```
Then: `ansible all -m shell -a "bash {{ toolkit_path }}/update.sh"`

### Mysterium Node in Docker — Reading Stats

If your **Mysterium node** runs in Docker (not the toolkit), the toolkit can still read all stats as long as the container exposes the correct ports:

```bash
docker run --cap-add NET_ADMIN -d --name myst --restart=unless-stopped \
    -p 4449:4449 \
    -p 4050:4050 \
    -v myst-data:/var/lib/mysterium-node \
    mysteriumnetwork/myst:latest \
    service --agreed-terms-and-conditions
```

The toolkit then connects to `localhost:4449` (MystNodes UI) and `localhost:4050` (TequilAPI) as normal. No special configuration needed — the setup wizard auto-detects Docker containers named `myst` and reads the port automatically.

---

## Permissions

The backend always runs as your normal user, never as root. During setup, `setup.sh` writes `/etc/sudoers.d/mysterium-toolkit` with narrow passwordless rules. These never expire.

| Command | Purpose |
|---------|---------|
| `sysctl` | Apply kernel network parameters live |
| `ethtool` | NIC interrupt coalescing and checksum offload |
| `conntrack` | Read connection tracking table |
| `tee /etc/sysctl.d/*` | Persist kernel parameters to survive reboot |
| `tee /etc/modules-load.d/*` | Persist kernel module loading at boot |
| `tee /sys/module/nf_conntrack/parameters/hashsize` | Set conntrack hash size |
| `tee /usr/local/bin/*` | Write RPS and governor boot scripts |
| `tee /etc/systemd/system/mysterium-*.service` | Write systemd service units |
| `tee /etc/systemd/system/mysterium-*.timer` | Write systemd timer units |
| `chmod +x /usr/local/bin/mysterium-*` | Make boot scripts executable |
| `systemctl start/stop/enable/disable mysterium-*` | Node and toolkit service management |
| `systemctl daemon-reload` | Reload systemd after unit changes |
| `iptables` / `ip6tables` / `nft` | Read and manage firewall rules |

To regenerate after an update: `./update.sh`

---

## Kernel Tuning

Applied automatically during setup when the node runs on the same machine. Skipped in remote mode and Type 3. Persisted to `/etc/sysctl.d/99-mysterium-node.conf`.

| Parameter | Value | Effect |
|-----------|-------|--------|
| `net.ipv4.ip_forward` | 1 | Required for VPN traffic forwarding |
| `net.core.rmem_max` | 134217728 | 128 MB receive buffer |
| `net.core.wmem_max` | 134217728 | 128 MB send buffer |
| `net.ipv4.tcp_rmem` | 4096 87380 134217728 | TCP receive buffer range |
| `net.ipv4.tcp_wmem` | 4096 65536 134217728 | TCP send buffer range |
| `net.ipv4.tcp_congestion_control` | bbr | BBR congestion control |
| `net.core.default_qdisc` | fq | Fair queuing — required for BBR |
| `net.netfilter.nf_conntrack_max` | 524288 | Connection tracking capacity |
| `vm.swappiness` | 60 | Balanced swap usage |

`tcp_bbr` loaded at boot via `/etc/modules-load.d/tcp_bbr.conf`.

### VPS / virtual machine detection

Detected via `systemd-detect-virt` and `hypervisor` flag in `/proc/cpuinfo`. On a VPS: CPU governor and IRQ tuning are skipped — these require bare-metal CPU frequency scaling access. All network tuning applies on both bare metal and VPS.

Apply later via System Health → Fix All, or manually:

```bash
sudo python3 scripts/system_health.py --health-fix --health-persist
```

---

## Firewall

Detection priority:

```
firewalld → iptables (with active rules) → ufw → nftables → iptables-legacy
```

Based on active rules, not binary presence.

### Ports opened — Type 1 / Type 2

| Port | Protocol | Service |
|------|----------|---------|
| 5000 | TCP | Toolkit dashboard |
| 4449 | TCP | TequilAPI / Node UI |
| 1194 | UDP | OpenVPN UDP |
| 1194 | TCP | OpenVPN TCP |
| 51820 | UDP | WireGuard |
| 10000–65000 | UDP | P2P / NAT hole punching |

> **Type 3:** firewall configuration is skipped — the node machine manages its own rules. Run setup on the node machine to apply them there.

Rules are persisted automatically:

- `iptables` → `/etc/iptables/rules.v4`; `netfilter-persistent` enabled if available
- `nftables` → written back to `/etc/nftables.conf`
- `firewalld` → `--permanent` on all rules, then `--reload`
- `ufw` → `ufw allow`; enabled automatically if inactive

---

## Data Management

The **Data Management** card (below System Health) gives full control over all persistent storage.

### Databases

| Database | File | Records | Interval |
|----------|------|---------|----------|
| Earnings history | `config/earnings_history.db` | Daily snapshots | every 10 min |
| Traffic history | `config/traffic_history.db` | Monthly vnstat data | on import |
| Session archive | `config/sessions_history.db` | All sessions | at startup |
| Node quality | `config/quality_history.db` | Score, latency, bandwidth | every 10 min |
| System metrics | `config/system_metrics.db` | CPU, RAM, disk, temp | every 5 min |
| Service events | `config/service_events.db` | Start/stop events | on change |
| Uptime log | `config/uptime_log.json` | Poll cycles | every 10 min |

Default retention windows — pruned once per calendar day:

| Database | Default retention |
|----------|-------------------|
| Earnings history | 365 days |
| Session archive | 90 days |
| Traffic history | 730 days |
| Node quality | 90 days |
| System metrics | 30 days |
| Service events | 30 days |
| Uptime log | 90 days |

Override in `config/setup.json`:

```json
"data_retention": { "earnings": 730, "sessions": 180, "quality": 60 }
```

Only the keys you specify are overridden. Changes via the dashboard take effect immediately. After manual edits to `config/setup.json`, restart the backend to apply.

---

## Compatibility

| | Details |
|-|---------|
| Python | 3.8 or newer |
| Node.js | 18 or newer (Type 1 / 2 only) |
| Distros | Debian · Ubuntu · Parrot OS · Fedora · Arch Linux · Alpine |
| Environments | Bare metal · Docker · LXC · Proxmox · KVM VPS |
| Firewall | firewalld · ufw · nftables · iptables-nft · iptables-legacy |

---

## Built With

| Project | Author | License |
|---------|--------|---------|
| [Flask](https://flask.palletsprojects.com) | Pallets Projects | BSD-3 |
| [React](https://react.dev) | Meta / React contributors | MIT |
| [Tailwind CSS](https://tailwindcss.com) | Tailwind Labs | MIT |
| [Vite](https://vitejs.dev) | Evan You / Vite contributors | MIT |
| [psutil](https://github.com/giampaolo/psutil) | Giampaolo Rodolà | BSD-3 |
| [SQLite](https://sqlite.org) | D. Richard Hipp | Public Domain |
| [vnstat](https://humdi.net/vnstat) | Teemu Toivola | GPL-2 |
| [Lucide Icons](https://lucide.dev) | Lucide contributors | ISC |
| [requests](https://requests.readthedocs.io) | Kenneth Reitz | Apache-2 |
| [CoinPaprika API](https://api.coinpaprika.com) | CoinPaprika | Free, no key |
| [Frankfurter](https://www.frankfurter.app) | Frankfurter (ECB rates) | Free, no key |

---

## Support the Project

If the Mysterium Node Toolkit saves you time or helps you earn more MYST, consider a donation:

**MYST — Polygon network**  
`0x032aA9dBAAa65035BF1e3965f1FdB1C82Af6819A`

More wallet options coming in future releases.

---

## License

[CC BY-NC-SA 4.0](LICENSE) — Free for personal and community use. Not for commercial use. Credit the author if redistributed or modified.
