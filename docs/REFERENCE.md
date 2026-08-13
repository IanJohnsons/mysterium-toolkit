# Reference

Detail that does not belong in the README: ports, tuning, permissions, TLS, fleet
configuration, databases and the CLI. Start with the [README](../README.md) if you
are installing for the first time.

**Contents**

- [Install types in detail](#install-types-in-detail)
- [Fleet mode](#fleet-mode)
- [Tailscale](#tailscale)
- [TLS (HTTPS)](#tls-https)
- [Ports and firewall](#firewall)
- [Kernel tuning](#kernel-tuning)
- [Permissions and sudoers](#permissions)
- [Security and fail2ban](#security)
- [Databases and retention](#data-management)
- [Autostart](#autostart)
- [CLI](#cli-terminal-dashboard)
- [Reinstalling](#re-install-on-existing-machine)
- [Compatibility](#compatibility)

---

## Install types in detail

| Type | Installs | Use for |
|------|----------|---------|
| **Type 1 — Full** | Backend, web dashboard, CLI, kernel tuning, firewall | Your main node machine — full remote control from any device |
| **Type 2 — Fleet Master** | Full install plus guided nodes.json setup | Central machine managing multiple remote nodes |
| **Type 3 — Lightweight** | Backend only, no frontend, no Node.js | Remote node monitored by a fleet master |

### Type 1 — Full install

Everything runs on the node machine itself. The dashboard is served from this machine
on port 5000 and is reachable from any browser, locally or remotely. All control
actions — restart, settle, health fixes, payment config — run directly here.

### Type 2 — Fleet Master

The full toolkit plus fleet management. One dashboard shows every registered node.
For each remote node the master can read earnings, sessions, quality, traffic and
system health, and can restart it, trigger settlement, apply and persist health
fixes, read and write payment config, and manage its data retention.

All remote actions are proxied through the fleet master; a remote node's API key
stays on the server side and is never sent to the browser.

### Type 3 — Lightweight

Backend only. No dashboard, no Node.js, minimal memory. It serves `/peer/data` so a
fleet master can read everything from it. Monitoring and control happen on the master.

---

## What setup.sh installs

The installer walks through this itself and explains each step on screen. In short it
detects your node (and offers to install one if there is none), asks for the install
type, stops any running toolkit, looks for previous installations and offers to carry
their data across, installs system tools and Python packages, builds the frontend,
runs the setup wizard for your keys and preferences, applies kernel tuning and
firewall rules, installs the systemd service and sudoers entries, and optionally sets
up fail2ban and Tailscale.

System tools it installs when missing: `vnstat`, `ethtool`, `curl`, `iputils-ping`,
`sqlite3`, `miniupnpc`, `irqbalance`, `conntrack`, and `lm-sensors` on hardware that
reports temperatures.

## Fleet Mode

Each node runs its own toolkit backend. The fleet master reads data from each node over HTTP using its API key. Data is never mixed between nodes.

Run the master on the machine with a stable public address — usually a VPS. Nodes at home sit behind a router and a changing IP address, which makes them awkward to reach from outside.

**Transport security:** the master polls each node at the address in `toolkit_url`. When that address is `http://` and the traffic crosses the internet, the node's data and its API key are sent in clear text. Either enable [TLS](#tls-https), or place the fleet on a private network such as WireGuard or Tailscale.

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
      "url": "http://localhost:4050",
      "toolkit_url": "http://localhost:5000",
      "toolkit_api_key": "VPS_API_KEY_HERE"
    },
    {
      "id": "home",
      "label": "Home Node",
      "url": "http://YOUR_HOME_IP:4050",
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

If your **Mysterium node** runs in Docker (not the toolkit itself), the toolkit connects to it via TequilAPI. Use the official Mysterium Docker command:

```bash
docker run --cap-add NET_ADMIN -d -p 4449:4449 \
    --name myst --restart unless-stopped \
    -v myst-data:/var/lib/mysterium-node \
    mysteriumnetwork/myst:latest \
    service --agreed-terms-and-conditions
```

TequilAPI is on **port 4449**. The `-p 4449:4449` flag exposes it to the host — this is required. There is no separate port 4050 in a standard Docker install.

**Setup wizard:** run `python3 scripts/setup_wizard.py` (or re-run `setup.sh`). The wizard auto-detects running `myst` containers and reads the mapped port. When asked for the password, enter the password you set during the **Node UI onboarding** at `http://localhost:4449/ui` — this is not `mystberry`.

**What the toolkit reads from Docker nodes via TequilAPI (full support):**
- Earnings, sessions, session archive, node quality, services, settlement, MYST price

**What is not available when the node runs in Docker (expected behaviour, not a bug):**
- Live Connections counter and VPN Traffic card rely on network interface and process inspection on the host. When the node runs inside a container, these interfaces and the `myst` process are not visible from the host. The cards will show `0` or `N/A` — this is normal.
- System Health subsystems (conntrack, CPU governor, kernel tuning) apply to the host, not the container. They still run against the host system.
- Node restart via the dashboard requires the Docker socket to be accessible. If restart fails, run `docker restart myst` manually.

---

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
| `fail2ban-client` | Read jail status and apply live jail settings |
| `tee /etc/fail2ban/jail.local` | Write toolkit-managed jail block |
| `tee /etc/fail2ban/filter.d/*` | Write toolkit filter definitions |

To regenerate after an update: `./update.sh`

---

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

---

## Firewall

Detection priority:

```
firewalld → iptables (with active rules) → ufw → nftables → iptables-legacy
```

Based on active rules, not binary presence.

### Ports opened — Type 1 / Type 2 (local installs)

This table applies when the toolkit runs on the node machine (`toolkit_mode=local`). Remote / fleet-slave installs (`toolkit_mode=remote`) open **only** port 5000.

| Port | Protocol | Service |
|------|----------|---------|
| 5000 | TCP | Toolkit dashboard |
| 10000–60000 | UDP | Mysterium P2P / NAT hole punching. Setup reads `udp.ports` from the node's `config.toml` and opens that exact range; `10000:60000` is the node default and the fallback when no config is found. If you change `udp.ports`, re-run setup so the firewall follows — a node listening on ports the firewall blocks fails inbound connections silently |

**Not opened, by design:**

- **4050/tcp (TequilAPI)** — used by the toolkit on localhost only; never exposed to the network.
- **4449/tcp (Node UI)** — intentionally left closed to the internet for security. The Mysterium Node UI stays reachable on localhost and your LAN; open it yourself only if you knowingly want remote access to it.
- **1194 (OpenVPN) / 51820 (WireGuard)** — not used; Mysterium runs WireGuard over the UDP range above via NAT hole punching. The toolkit can remove these if an older install left them open (Security tab).

**One port the toolkit does not control:** the Mysterium node runs an SSDP service for local network discovery, and it binds to a random high TCP port chosen by the operating system — a different number after every restart. It serves a small device description so a Mysterium app on the same LAN can find the node. On a VPS it has no purpose; disable it with `--local-service-discovery=false` in the node's startup options if you would rather not have it listening. It is unrelated to earnings either way.

Note also that the node's own Web UI binds to localhost **and the machine's LAN address** when `ui.address` is left empty, which is the default. On a VPS that LAN address is the public IP, so port 4449 is listening publicly even though the firewall keeps it closed. Set `--ui.address=127.0.0.1` if you want it bound to loopback only.

> **Type 3:** firewall configuration is skipped — the node machine manages its own rules. Run setup on the node machine to apply them there.

Rules are persisted automatically:

- `iptables` → `/etc/iptables/rules.v4`; `netfilter-persistent` enabled if available
- `nftables` → written back to `/etc/nftables.conf`
- `firewalld` → `--permanent` on all rules, then `--reload`
- `ufw` → `ufw allow`; enabled automatically if inactive

---

---

## TLS (HTTPS)

By default the dashboard is served over plain HTTP. On a LAN, or through an SSH tunnel, that is fine. If you reach the dashboard over the internet, or run a fleet where the master polls nodes across the internet, that traffic — including your API key — travels in clear text.

Enable TLS during setup (step 12.55), or afterwards by editing `config/setup.json`:

```json
{
  "https_enabled": true,
  "tls_cert": "config/tls/cert.pem",
  "tls_key": "config/tls/key.pem"
}
```

Setup generates a self-signed certificate locally. No domain name, no Let's Encrypt, no certbot and no port 80 are required. Your browser will warn about the certificate the first time — that is expected for a self-signed certificate, and you can accept it permanently.

### Fleet over TLS

Copy each node's `config/tls/cert.pem` to the master and point that node's entry at it:

```json
{
  "id": "laptop",
  "toolkit_url": "https://home.example.com:5000",
  "toolkit_api_key": "...",
  "tls_cert": "config/tls/peers/laptop.pem"
}
```

This pins the connection to that one certificate, which is stronger than validating against a public certificate authority.

A mixed fleet is supported. Some nodes may use HTTPS while others stay on HTTP, and nothing needs to change for nodes you leave alone.

### Nodes whose IP address changes

A certificate is only valid for the names and addresses it was issued for. If a node sits behind a home connection and the provider changes the IP address — after an outage or a line reset, for example — the certificate no longer matches and the master can no longer reach that node. Note that this second part is already true without TLS: `nodes.json` holds the old address either way.

Two ways around it:

- Give the node a hostname that always points to it — a DNS record you control, or a dynamic DNS name — and enter it during setup. A certificate issued for a name keeps working when the address changes. This is the recommended option.
- Set `"tls_verify": false` for that node in `nodes.json`. Traffic stays encrypted but the certificate is no longer checked, which means a man-in-the-middle attack becomes possible. Use this only on a network you trust.

### Web server

From v1.4.0 the dashboard is served by [cheroot](https://cheroot.cherrypy.dev/), a small production WSGI server, instead of Flask's built-in development server. It is a single process with a thread pool, so memory use is essentially unchanged (about 1 MB more), and it keeps connections alive rather than closing them after every request. Without keep-alive, every request over HTTPS would pay for a fresh TLS handshake: opening the dashboard measured roughly 360 ms against 35 ms with keep-alive.

Thread count defaults to 30, or 10 when `pi_mode` is enabled. Override with `server_threads` in `config/setup.json` if you have reason to.

Cheroot is already a production server, so it does not need anything in front of it.
Note that `scripts/deploy_production.sh` still sets up nginx as a reverse proxy — that
dates from when Flask's development server was doing the serving, and running both means
two web servers doing the same job. Use it only if you specifically want nginx for
something else, such as a real certificate on a domain name.

---

---

## Adding Security After Install

Skipped fail2ban or Tailscale during setup? No need to reinstall. Run `./start.sh` and choose **option 9 — Security & Upgrades** at any time:

```bash
cd mysterium-toolkit
./start.sh
# → option 9: Security & Upgrades
```

| Option | What it does |
|--------|-------------|
| 1 | Install fail2ban and protect port 5000 against brute force |
| 2 | Install Tailscale — hides dashboard from internet |
| 3 | Reconfigure sudoers — fix sudo permission issues |

After installing fail2ban, configure it via the **🛡 Security** tab in the dashboard. After installing Tailscale, run `sudo tailscale up` and authenticate — your Tailscale IP then appears in the Security tab.

---

---

## Security

The **Security** tab (scroll down in the dashboard, or click the 🛡 Security link) covers three areas: fail2ban brute force protection, Tailscale VPN access, and UFW firewall rules.

### fail2ban

fail2ban protects port 5000 (toolkit dashboard) against brute force login attempts. The toolkit creates and manages one jail: `mysterium-dashboard`. This jail monitors login failures on port 5000 and bans IPs after repeated failures.

**What the toolkit manages:**
- Only the `mysterium-dashboard` jail — nothing else
- Written to `/etc/fail2ban/jail.local` inside a clearly marked toolkit block
- All other jails (sshd, nginx, etc.) are left completely untouched

**Toolkit managed toggle** — if you already use another tool (e.g. ServerGuardian) to manage fail2ban, disable the toggle in the Security tab. The toolkit then operates read-only: it shows fail2ban status but never writes to `jail.local`.

**Custom jails** — to add jails beyond what the toolkit manages, edit `/etc/fail2ban/jail.local` manually and add your jails **outside** the toolkit block:

```
# --- Mysterium Toolkit managed jails ---
[mysterium-dashboard]
...
# --- End Mysterium Toolkit ---

# Your custom jails go here — the toolkit never touches these:
[sshd]
enabled = true
port = ssh
maxretry = 5
bantime = 86400
```

Install fail2ban via the CLI menu → Security & Upgrades → option 1, or via `sudo apt install fail2ban`.

### Tailscale

Tailscale creates a private VPN network between your devices. With Tailscale active, the dashboard is reachable via your Tailscale IP (`100.x.x.x`) without exposing port 5000 to the internet.

Install via CLI menu → Security & Upgrades → option 2, or manually:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

After connecting, your Tailscale IP appears in the Security tab. Optionally block port 5000 from the public internet once Tailscale is working:

```bash
sudo ufw deny 5000
sudo ufw allow in on tailscale0
```

> ⚠ Only run these commands after confirming Tailscale works — the dashboard will only be reachable via Tailscale IP afterwards.

---

---

## Data Management

The **Data Management** card (below System Health) gives full control over all persistent storage.

### Databases

| Database | File | Records | Interval |
|----------|------|---------|----------|
| Earnings history | `backend/databases/earnings_history.db` | Daily snapshots | every 10 min |
| Earnings rollup | `backend/databases/earnings_rollup.db` | Permanent per-day lifetime totals (never pruned) | every 10 min |
| Traffic history | `backend/databases/traffic_history.db` | Monthly vnstat data | on import |
| Session archive | `backend/databases/sessions_history.db` | All sessions | at startup |
| Node quality | `backend/databases/quality_history.db` | Score, latency, bandwidth | every 10 min |
| System metrics | `backend/databases/system_metrics.db` | CPU, RAM, disk, temp | every 5 min |
| Service events | `backend/databases/service_events.db` | Start/stop events | on change |
| Uptime log | `config/uptime_log.json` | Poll cycles | every 10 min |

All history is kept **indefinitely by default** — nothing is ever deleted automatically unless you explicitly enable it. Pruning only starts for a data type once you set and save a retention window for it in the Data Manager panel; that save also sets the opt-in flag the daily prune checks for. Editing `config/setup.json` by hand does **not** enable pruning — use the dashboard.

Suggested retention windows shown in the Data Manager (pick any subset — types you don't set are kept forever):

| Database | Suggested retention |
|----------|-------------------|
| Earnings history | 365 days |
| Session archive | 90 days |
| Traffic history | 730 days |
| Node quality | 90 days |
| System metrics | 30 days |
| Service events | 30 days |
| Uptime log | 90 days |

Once saved via the dashboard, the daily prune deletes rows older than your chosen window for that type — every other type stays untouched forever. Changes take effect immediately, no restart needed.

---

---

## Compatibility

| | Details |
|-|---------|
| Python | 3.8 or newer |
| Node.js | 18 or newer (Type 1 / 2 only) |
| Architectures | x86_64 · amd64 · aarch64 / arm64 · armv7l / armhf |
| Distros | Debian · Ubuntu · Parrot OS · Fedora · Arch Linux · Alpine |
| Environments | Bare metal · Docker · LXC · Proxmox · KVM VPS · Raspberry Pi |
| Firewall | firewalld · ufw · nftables · iptables-nft · iptables-legacy |

**armv6 (Pi Zero, Pi 1)** has no Node.js 18 build, so there is no dashboard on those
boards. The installer says so and skips the step. Type 3 works — the node reports to a
fleet master that renders the screen.

**`provider_tunnel_ip` (node 1.39.0)** appears in the node's connection contract
(`tequilapi/contract/connection.go`), which describes an outgoing connection made by a
consumer. It is not present in the provider's sessions, node status or identity
endpoints, so on a machine that only provides service the field never has a value.
Nothing for the toolkit to read; recorded here so the question is not reopened.

### Node versions: apt and GitHub can disagree

The toolkit installs the Mysterium node through the project's own `install.sh`, which
picks its package source itself — the toolkit adds no repository of its own. That
source can lag behind the GitHub releases by days: node 1.39.2 was published on GitHub
while `apt` still offered 1.38.5, so `apt-get install --only-upgrade myst` reported
everything was current.

To install a newer release directly:

```bash
ARCH=$(dpkg --print-architecture)
curl -fsSL -o /tmp/myst.deb \
  "https://github.com/mysteriumnetwork/node/releases/download/<VERSION>/myst_linux_${ARCH}.deb"
sudo dpkg -i /tmp/myst.deb && sudo apt-get install -f -y && rm -f /tmp/myst.deb
myst --version
```

A later `apt upgrade` may put the repository version back once it catches up, which is
harmless. From node 1.39.0 onwards the package also installs `myst-updater.timer`,
which updates the node on its own six-hourly schedule. The dashboard shows whether it
is active, under the node version. Changing it is left to the operator, because the
file belongs to the node package and writing it would need a sudo right the toolkit has
no other use for:

```bash
sudo sed -i 's/^MYST_UPDATER_ENABLED=true/MYST_UPDATER_ENABLED=false/' /etc/default/myst-updater
```

Both switches matter: the systemd timer and that flag. An active timer with the flag
set to false does nothing, which is why the dashboard reads both.

**Raspberry Pi** is detected from `/proc/device-tree/model`. When found, the wizard
enables `pi_mode`: log level WARNING instead of INFO, to cut down on SD card writes,
and a web server thread pool of 10 instead of 30. Both can be changed afterwards in
`config/setup.json` or from the dashboard.

Note that `pi_mode` suppresses INFO logging, so routine confirmations do not appear in
`journalctl` on a Pi. Outcomes that changed data on disk are reported at WARNING for
that reason.

**EOL distributions** (Debian Buster and similar) can fail to install Node.js and
sqlite3 from their package manager. The installer falls back to a direct download from
nodejs.org and a Debian snapshot for sqlite3, matched to the detected architecture.

---

---

## CLI (Terminal Dashboard)

```bash
python cli/dashboard.py
python cli/dashboard.py --url http://remote-node:5000 --interval 10
```

Lightweight terminal UI using curses — no browser needed. Ideal for slow laptops or older Raspberry Pi devices. It reads the same backend `/metrics` API as the web dashboard, so its data is always in sync.

**Pages:** `1` Status (node info, resources, quality, **observed-active consumers with wallets, and tunnels with idle status**) · `2` Earnings (unsettled, net earned, fiat value, history chart)

The Status page shows the same observed-active consumers as the web UI — the real consumer wallets seen in the node's session log within the last 10 minutes — plus the live tunnels with their idle/transferring state. Mysterium never exposes live sessions over any API, so this is the honest, non-guessed view of who is currently using the node.

**Keys:** `Tab`/`1-2` page · `r` refresh · `t` theme · `T` test node · `h` health · `c` config · `w` restart node · `$` settle · `?` help · `q` quit · `+/-` adjust interval

---

---

## Re-install on existing machine

If you run `setup.sh` on a machine that already has a configured toolkit, it detects the existing `config/setup.json` and asks whether to keep it. Choosing yes skips the entire setup wizard — your settings are preserved and databases are migrated automatically.

---

---

## Autostart

Open `./start.sh` → option 8 — **Autostart on Boot** (Type 1/2) or option 6 (Type 3).

Installs a systemd service that starts automatically at boot, after the Mysterium node service, and restarts on crash. Works on laptops and headless VPS servers — no login required.

> **Type 3 (lightweight) nodes:** start the backend manually first via `./start.sh` → option 1 and verify it runs, then activate autostart via option 6. The systemd service needs the venv and config to exist before it can start at boot.

```bash
sudo systemctl status mysterium-toolkit
tail -f logs/backend.log
sudo journalctl -u mysterium-toolkit -f
```

The toolkit writes its own log to `logs/backend.log`, rotated at 10 MB with three
backups. That file is where the application's own messages go — database repairs,
fleet reloads, configuration warnings. `journalctl` shows what systemd captured
around the service, which on most installs is little more than sudo entries, so
start with the log file.

---