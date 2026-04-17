# Mysterium Node Toolkit

![Version](https://img.shields.io/badge/version-1.0.0-brightgreen) ![License](https://img.shields.io/badge/license-CC%20BY--NC--SA%204.0-blue) ![Platform](https://img.shields.io/badge/platform-Linux-lightgrey) ![Python](https://img.shields.io/badge/python-3.8%2B-blue)

A professional monitoring and management dashboard for [Mysterium Network](https://mysterium.network) VPN node operators. Runs fully local on your node machine — no cloud account, no third-party service, no data leaving your server.

**Author:** Ian Johnsons — [github.com/IanJohnsons](https://github.com/IanJohnsons)  
**License:** CC BY-NC-SA 4.0 — free for personal and community use, not for commercial use, credit the author if redistributed  
**Community:** Mysterium Network Telegram

---

## Install

```bash
git clone https://github.com/IanJohnsons/mysterium-toolkit
cd mysterium-toolkit
sudo ./setup.sh
```

Open the dashboard in your browser: `http://localhost:5000`  
From your phone or any device on your network: `http://YOUR_MACHINE_IP:5000`

```bash
# Open the control menu — start, stop, autostart and more
./start.sh

# Stop the toolkit
sudo ./stop.sh
```

> Always clone to a fixed directory name without a version number. The autostart systemd service points to the directory path — if the path changes, autostart breaks.

### Update

```bash
cd mysterium-toolkit
sudo ./update.sh
```

Pulls the latest code, rebuilds the frontend, updates packages and sudoers, restarts the backend. Databases and config are never touched.

`config/setup.json` and `config/nodes.json` are backed up before the pull and restored automatically if the pull would remove them.

### Re-install on existing machine

If you run `setup.sh` on a machine that already has a configured toolkit, it detects the existing `config/setup.json` and asks whether to keep it. Choosing yes skips the entire setup wizard — your node password, API key, port and fleet settings are preserved. Previous databases and `nodes.json` are migrated automatically.

---

## What It Does

- **Earnings tracking** — unsettled MYST, lifetime gross, settled balance, daily / weekly / monthly delta from SQLite snapshots every 10 minutes
- **Live MYST price** — EUR and USD conversion next to your earnings via CoinPaprika + Frankfurter ECB. Both free, no account, no API key
- **Earnings history chart** — Daily / Weekly / Monthly / All tabs, auto-scales to history length, selective data cleanup built in
- **Session archive** — every session saved to SQLite with token values frozen before Mysterium zeroes them at settlement
- **Node quality** — Discovery quality score, latency, bandwidth, uptime 24h / 30d, packet loss, connected %
- **Session analytics** — full session history, active tunnels, consumer breakdown by country and service type
- **On-chain wallet** — live MYST balance on Polygon via Polygonscan, settlement history, beneficiary address
- **Data traffic** — VPN vs NIC vs overhead, Today / Month / 3 Months / Year / All Time, backed by vnstat
- **Node control** — restart node, settle MYST on-chain, payment config tuner
- **System health** — 13 subsystems, one-click Fix & Lock, survives reboots
- **Adaptive CPU governor** — switches powersave / schedutil / performance automatically based on active session count
- **Adaptive conntrack** — connection tracking scales with tunnel count: 128K / 256K / 512K
- **Fleet monitor** — manage multiple nodes from one central dashboard, data fully isolated per node
- **Autostart** — systemd service, starts after the Mysterium node, restarts on crash
- **Firewall management** — detect type, apply correct rules, clean duplicate FORWARD rules
- **11 themes** — Emerald, Cyber, Sunset, Violet, Crimson, Matrix, Phosphor, Ghost, Midnight, Steel, Military

---

## Installation Types

| Type | Installs | Use for |
|------|----------|---------|
| **Type 1 — Full** | Backend, web dashboard, CLI, kernel tuning, firewall | Your main node machine |
| **Type 2 — Fleet Master** | Full install + guided nodes.json setup | Central machine managing multiple nodes |
| **Type 3 — Lightweight** | Backend only, no frontend, no Node.js | Remote nodes monitored by a fleet master |

---

## Autostart

Open `./start.sh` → option 9 — **Autostart on Boot**.

Installs a systemd service that starts automatically at boot, after the Mysterium node service, and restarts on crash. Works on laptops and headless VPS servers — no login required.

> **Type 3 (lightweight) nodes:** start the backend manually first (`./start.sh` → option 1), then activate autostart via option 9. Activating autostart before the backend is running will fail on this node type.

```bash
sudo systemctl status mysterium-toolkit
sudo journalctl -u mysterium-toolkit -f
```

---

## Permissions

The backend always runs as your normal user, never as root. During setup, `setup.sh` writes `/etc/sudoers.d/mysterium-toolkit` with narrow passwordless rules for specific commands only. These rules never expire — health fixes and governor adjustments work permanently without any sudo timeout.

| Command | Purpose |
|---------|---------|
| `sysctl` | Kernel network tuning |
| `ethtool` | NIC coalescing and checksum |
| `modprobe` | Load kernel modules (tcp_bbr, nf_conntrack) |
| `bash` | Write config to /etc/sysctl.d/, /usr/local/bin/, /etc/systemd/ |
| `systemctl restart mysterium-*` | Node restart from health panel |
| `cpupower frequency-set` | Adaptive CPU governor |
| `iptables` / `nft` | Read firewall rules |
| `fallocate` / `mkswap` / `swapon` | Create swapfile |

To regenerate after an update: `sudo ./update.sh`

---

## Adaptive Subsystems

Two subsystems adjust automatically every 10 minutes with no manual action needed:

**CPU Governor** — scales with active sessions:

| Sessions | Governor | Effect |
|----------|----------|--------|
| 0 | `powersave` | Minimum frequency — CPU stays cool |
| 1–5 | `schedutil` | Kernel-managed — ramps instantly under load |
| 6+ | `performance` | Maximum throughput |

**Connection Tracking** — scales with VPN tunnels:

| Tunnels | conntrack max |
|---------|--------------|
| 0–4 | 128,000 |
| 5–19 | 256,000 |
| 20+ | 512,000 |

---

## Fleet Mode

Each node runs its own toolkit backend. The central dashboard reads data from each node over HTTP using its API key. Data is never mixed between nodes.

### Setup

1. Install the toolkit on each node (Type 1 or Type 3)
2. Find each node's API key in `config/setup.json` → `dashboard_api_key`
3. Ensure port 5000 is reachable from the central machine (port forward if behind NAT)
4. Create `config/nodes.json` on the central machine:

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

---

## Earnings

| Field | Source | Description |
|-------|--------|-------------|
| Unsettled | TequilAPI `earnings_tokens` | Earned, not yet settled on-chain |
| Lifetime Gross | TequilAPI `earnings_total_tokens` | All-time cumulative, before Hermes fee |
| Hermes Channel | TequilAPI `balance_tokens` | Ready to withdraw — 0.0000 means already settled |
| Daily / Weekly / Monthly | SQLite snapshots every 10 min | Shows BUILDING until enough history exists |
| Quality history chart | Sparkline inside Node Quality card | Score, latency, bandwidth — 7 to 90 day windows |
| System metrics history | CPU, RAM, disk, temp sparklines | 5 min interval — 1 to 30 day windows |
| Data Management panel | Storage overview for all 7 databases | Delete by type or age, two-click confirm |
| ≈ €X.XX / $X.XX | CoinPaprika + Frankfurter ECB | Fiat value at current MYST token price — no key needed |

### Data Management

The **Data Management** card (below System Health) gives you full control over all persistent storage.

#### Databases

| Database | File | Records | Interval |
|----------|------|---------|----------|
| Earnings history | `config/earnings_history.db` | Daily snapshots | every 10 min |
| Traffic history | `config/traffic_history.db` | Monthly vnstat data | on import |
| Session archive | `config/sessions_history.db` | All sessions | at startup |
| Node quality | `config/quality_history.db` | Score, latency, bandwidth | every 10 min |
| System metrics | `config/system_metrics.db` | CPU, RAM, disk, temp | every 5 min |
| Service events | `config/service_events.db` | Start/stop events | on change |
| Uptime log | `config/uptime_log.json` | Poll cycles | every 10 min |

All databases are pruned automatically once per calendar day. Default retention windows:

| Database | Default retention |
|----------|-------------------|
| Earnings history | 365 days |
| Session archive | 90 days |
| Traffic history | 730 days |
| Node quality | 90 days |
| System metrics | 30 days |
| Service events | 30 days |
| Uptime log | 90 days |

Override any window in `config/setup.json` under the key `data_retention`:

```json
"data_retention": { "earnings": 730, "sessions": 180, "quality": 60 }
```

Only the keys you specify are overridden — the rest keep their defaults. Restart the backend after editing.

Use the Data Management panel to manually delete data outside the normal retention cycle. Two-click confirmation required.

#### Quality History & System Metrics Charts

The **Node Quality** card has an expandable sparkline at the bottom showing quality score, latency, and bandwidth over 7 / 14 / 30 / 90 days.

The **System Metrics History** card (above System Health) shows CPU%, RAM%, disk%, and CPU temperature as sparklines over 1 / 3 / 7 / 14 / 30 days. Both charts load on demand — no background requests until expanded.



## System Health

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

---

## Compatibility

| | Details |
|-|---------|
| Python | 3.8 or newer |
| Node.js | 18 or newer (Type 1 / 2 only, for frontend build) |
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
