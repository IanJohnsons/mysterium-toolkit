#!/bin/bash
# Mysterium Node Toolkit — Update Script
# Pulls latest code, rebuilds frontend, restarts backend.
# Run from the toolkit directory: ./update.sh  (no sudo needed)
# On root installs (VPS) run as root: ./update.sh
# The script handles privileged commands internally via $SUDO.

set -e

TOOLKIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$TOOLKIT_DIR"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
DIM='\033[2m'
NC='\033[0m'
BOLD='\033[1m'

echo
echo -e "${BOLD}╔════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║   Mysterium Toolkit — Update               ║${NC}"
echo -e "${BOLD}╚════════════════════════════════════════════╝${NC}"
echo

# ── Determine sudo usage ──────────────────────────────────────────────────
# Run without outer sudo — script handles privileges internally via $SUDO.
# On root installs (VPS) SUDO is empty. On non-root installs SUDO=sudo.
[ "$(id -u)" -eq 0 ] && SUDO="" || SUDO="sudo"
_REAL_USER="${SUDO_USER:-$USER}"
_REAL_HOME=$(getent passwd "$_REAL_USER" | cut -d: -f6 2>/dev/null || echo "$HOME")

# ── Must run from a git repo ──────────────────────────────────────────────
if [ ! -d ".git" ]; then
    echo -e "${RED}✗ Not a git repository.${NC}"
    echo -e "  This script is for git-based installs only."
    echo -e "  Run: git clone https://github.com/IanJohnsons/mysterium-toolkit"
    exit 1
fi

# ── Backup config before git pull ────────────────────────────────────────────
_CONFIG_BACKUP=""
if [ -f "config/setup.json" ]; then
    _CONFIG_BACKUP=$(cat config/setup.json)
    echo -e "  ${DIM}Config backed up in memory before pull${NC}"
fi
_NODES_BACKUP=""
if [ -f "config/nodes.json" ]; then
    _NODES_BACKUP=$(cat config/nodes.json)
    echo -e "  ${DIM}Fleet nodes.json backed up in memory before pull${NC}"
fi

# ── Fix .git ownership if root-owned (caused by previous sudo git pull) ──
if [ -d ".git" ] && [ "$(stat -c '%U' .git/objects 2>/dev/null)" = "root" ] && [ -n "$_REAL_USER" ] && [ "$_REAL_USER" != "root" ]; then
    echo -e "  ${YELLOW}⚠ .git/objects owned by root — fixing ownership...${NC}"
    [ "$(stat -c '%U' ".git/objects" 2>/dev/null)" = "root" ] && $SUDO chown -R "$_REAL_USER:$_REAL_USER" ".git" 2>/dev/null || true
    echo -e "  ${GREEN}✓ .git ownership restored to $_REAL_USER${NC}"
fi

# ── Pull latest code ──────────────────────────────────────────────────────
echo -e "  Pulling latest code..."
if ! git pull; then
    echo -e "${RED}✗ git pull failed — check your network or repo access.${NC}"
    exit 1
fi
echo -e "  ${GREEN}✓ Code updated${NC}"
echo

# ── Restore config if git pull removed it ────────────────────────────────
if [ -n "$_CONFIG_BACKUP" ] && [ ! -f "config/setup.json" ]; then
    mkdir -p config
    echo "$_CONFIG_BACKUP" > config/setup.json
    echo -e "  ${GREEN}✓ config/setup.json restored after pull${NC}"
fi
if [ -n "$_NODES_BACKUP" ] && [ ! -f "config/nodes.json" ]; then
    mkdir -p config
    echo "$_NODES_BACKUP" > config/nodes.json
    echo -e "  ${GREEN}✓ config/nodes.json restored after pull${NC}"
fi

# ── Fix ownership on config/ — git pull runs as root and can make DB files root-owned ──
_REAL_USER="${SUDO_USER:-$USER}"
if [ "$_REAL_USER" != "root" ]; then
[ "$(stat -c '%U' "$TOOLKIT_DIR/config" 2>/dev/null)" = "root" ] && $SUDO chown -R "$_REAL_USER:$_REAL_USER" "$TOOLKIT_DIR/config/" 2>/dev/null || true
    echo -e "  ${GREEN}✓ config/ ownership corrected → $_REAL_USER${NC}"
fi

# ── Add data_retention defaults to setup.json if missing ─────────────────────
if [ -f "config/setup.json" ]; then
    python3 - << 'PYEOF'
import json, pathlib
cfg = pathlib.Path('config/setup.json')
try:
    d = json.loads(cfg.read_text())
    if 'data_retention' not in d:
        d['data_retention'] = {
            'earnings': 365, 'sessions': 90, 'traffic': 730,
            'quality': 90, 'system': 30, 'services': 30, 'uptime': 90,
        }
        cfg.write_text(json.dumps(d, indent=2))
        print('  ✓ data_retention defaults added to config/setup.json')
except Exception as e:
    print(f'  ⚠ Could not migrate setup.json: {e}')
PYEOF
fi

# ── New version ───────────────────────────────────────────────────────────
NEW_VERSION=$(cat VERSION 2>/dev/null || echo "unknown")
echo -e "  Version: ${BOLD}v${NEW_VERSION}${NC}"
echo

# ── Check first-time setup has been done ─────────────────────────────────
if [ ! -f "config/setup.json" ]; then
    echo -e "${RED}✗ config/setup.json not found.${NC}"
    echo -e "  Run ${BOLD}sudo ./setup.sh${NC} first before using update.sh."
    exit 1
fi

# ── Update Python packages ────────────────────────────────────────────────
if [ -f "venv/bin/pip" ]; then
    echo -e "  Updating Python packages..."
    venv/bin/pip install --upgrade pip > /dev/null 2>&1
    venv/bin/pip install -r requirements.txt > /dev/null 2>&1
    echo -e "  ${GREEN}✓ Python packages updated${NC}"
else
    echo -e "  ${YELLOW}⚠ venv not found — run sudo ./setup.sh first${NC}"
    exit 1
fi

# ── Detect setup mode (skip frontend for Type 3) ─────────────────────────
SETUP_MODE=""
if [ -f "config/setup.json" ]; then
    SETUP_MODE=$(python3 -c "
import json, sys
try:
    d = json.load(open('config/setup.json'))
    print(d.get('setup_mode', ''))
except:
    print('')
" 2>/dev/null)
fi

# ── Rebuild frontend ──────────────────────────────────────────────────────
if [ "$SETUP_MODE" = "3" ]; then
    echo -e "  ${DIM}Lightweight mode — skipping frontend build${NC}"
elif command -v npm &>/dev/null && [ -d ".build" ]; then
    echo -e "  Rebuilding frontend..."
    cp .build/package.json .build/vite.config.js .build/postcss.config.js .build/tailwind.config.js .build/index.html . 2>/dev/null || true
    # Build to temp dir — only replace dist/ if build succeeds
    rm -rf dist_new/ 2>/dev/null || true
    # Disable set -e for npm — warnings produce non-zero exit but build can still succeed
    set +e
    npm install --legacy-peer-deps > /dev/null 2>&1
    BUILD_OUT=$(npm run build 2>&1)
    set -e
    if [ -f "dist/index.html" ] && echo "$BUILD_OUT" | grep -q "built in"; then
        # Build succeeded into dist/ — rename to dist_new and swap
        mv dist dist_new 2>/dev/null && rm -rf dist/ 2>/dev/null || true
        mv dist_new dist 2>/dev/null || true
        echo -e "  ${GREEN}✓ Frontend rebuilt${NC}"
    elif [ -f "dist/index.html" ]; then
        echo -e "  ${GREEN}✓ Frontend rebuilt${NC}"
    else
        echo -e "  ${YELLOW}⚠ Frontend build failed — keeping existing dist/${NC}"
        echo "$BUILD_OUT" | tail -5
    fi
    rm -f vite.config.js postcss.config.js tailwind.config.js package.json package-lock.json index.html
else
    echo -e "  ${YELLOW}⚠ npm not found — frontend not rebuilt${NC}"
fi

# ── Update systemd service path and sudoers ───────────────────────────────
_SERVICE_FILE="/etc/systemd/system/mysterium-toolkit.service"
if [ -f "$_SERVICE_FILE" ]; then
    echo -e "  Updating systemd service..."
    _REAL_USER="${SUDO_USER:-$USER}"
    _REAL_HOME=$(getent passwd "$_REAL_USER" | cut -d: -f6)
    _VENV_PYTHON="$TOOLKIT_DIR/venv/bin/python"
    mkdir -p "$TOOLKIT_DIR/logs"
[ "$(stat -c '%U' "$TOOLKIT_DIR/logs" 2>/dev/null)" = "root" ] && $SUDO chown -R "$_REAL_USER:$_REAL_USER" "$TOOLKIT_DIR/logs" 2>/dev/null || true

    _MYST_SVC=""
    for _svc in mysterium-node myst mysterium; do
        if systemctl list-units --all --no-legend 2>/dev/null | grep -q "^.*${_svc}"; then
            _MYST_SVC="$_svc"
            break
        fi
    done
    _AFTER_DEPS="network-online.target${_MYST_SVC:+ $_MYST_SVC}"

    $SUDO tee "$_SERVICE_FILE" > /dev/null << UNIT_EOF
[Unit]
Description=Mysterium Node Monitoring Toolkit
After=${_AFTER_DEPS}
Wants=network-online.target
StartLimitIntervalSec=0
StartLimitBurst=0

[Service]
Type=simple
User=$_REAL_USER
WorkingDirectory=$TOOLKIT_DIR
ExecStartPre=/bin/bash -c 'mkdir -p $TOOLKIT_DIR/logs && touch $TOOLKIT_DIR/logs/backend.log'
ExecStart=$_VENV_PYTHON backend/app.py
Restart=on-failure
RestartSec=10
StandardInput=null
StandardOutput=append:$TOOLKIT_DIR/logs/backend.log
StandardError=append:$TOOLKIT_DIR/logs/backend.log
Environment=HOME=$_REAL_HOME

[Install]
WantedBy=multi-user.target
UNIT_EOF
    $SUDO systemctl daemon-reload
    echo -e "  ${GREEN}✓ Systemd service updated${NC}"

    # Update sudoers — only write if content changed (avoids sudo password prompt when unchanged)
    _SUDOERS_FILE="/etc/sudoers.d/mysterium-toolkit"
    _SUDOERS_CONTENT="# Mysterium Toolkit — passwordless sudo for specific commands only
$_REAL_USER ALL=(ALL) NOPASSWD: $TOOLKIT_DIR/update.sh, /sbin/sysctl, /usr/sbin/sysctl, /usr/sbin/ethtool, /usr/sbin/conntrack, /usr/local/bin/mysterium-rps-watcher.sh, /usr/local/bin/mysterium-rps-setup.sh, /usr/bin/tee /etc/sysctl.d/*, /usr/bin/tee /etc/modules-load.d/*, /usr/bin/tee /sys/module/nf_conntrack/parameters/hashsize, /usr/bin/tee /usr/local/bin/*, /usr/bin/tee /etc/systemd/system/mysterium-*.service, /usr/bin/tee /etc/systemd/system/mysterium-*.timer, /usr/bin/tee /etc/mysterium-node/config.toml, /usr/bin/tee /etc/mysterium-node/config-mainnet.toml, /usr/bin/chmod +x /usr/local/bin/mysterium-*, /bin/systemctl start mysterium-*, /bin/systemctl stop mysterium-*, /bin/systemctl enable mysterium-*, /bin/systemctl disable mysterium-*, /bin/systemctl daemon-reload, /usr/sbin/iptables, /sbin/iptables, /usr/sbin/iptables-legacy, /sbin/iptables-legacy, /usr/sbin/ip6tables, /sbin/ip6tables, /usr/sbin/nft, /sbin/nft"
    _SUDOERS_CURRENT=""
    if [ -f "$_SUDOERS_FILE" ]; then
        _SUDOERS_CURRENT=$(cat "$_SUDOERS_FILE" 2>/dev/null || true)
    fi
    if [ "$_SUDOERS_CONTENT" != "$_SUDOERS_CURRENT" ]; then
        printf '%s\n' "$_SUDOERS_CONTENT" | $SUDO tee "$_SUDOERS_FILE" > /dev/null
        $SUDO chmod 440 "$_SUDOERS_FILE"
        echo -e "  ${GREEN}✓ Sudoers updated${NC}"
    else
        echo -e "  ${DIM}  Sudoers unchanged — skipped${NC}"
    fi
fi

# ── Restart backend ───────────────────────────────────────────────────────
echo
echo -e "  Restarting backend..."
$SUDO systemctl stop mysterium-toolkit 2>/dev/null || true
sleep 1
# Kill process on port 5000 by PID only — avoids self-matching with pkill -f
_pid_on_5000=$(ss -tlnp 2>/dev/null | grep ':5000 ' | grep -oP 'pid=\K[0-9]+' | head -1 || true)
if [ -n "$_pid_on_5000" ]; then
    kill -9 "$_pid_on_5000" 2>/dev/null || true
fi
sleep 2
# Wait until port 5000 is actually free (max 15s)
_port_wait=0
while ss -tlnp 2>/dev/null | grep -q ':5000 ' && [ $_port_wait -lt 15 ]; do
    sleep 1
    _port_wait=$((_port_wait + 1))
done
$SUDO systemctl reset-failed mysterium-toolkit 2>/dev/null || true
$SUDO systemctl start mysterium-toolkit
sleep 3
if systemctl is-active --quiet mysterium-toolkit 2>/dev/null; then
    echo -e "  ${GREEN}✓ Backend restarted via systemd${NC}"
else
    echo -e "  ${RED}✗ Backend failed to restart — check: journalctl -u mysterium-toolkit -n 20${NC}"
fi

echo
echo -e "${GREEN}✓ Update complete — v${NEW_VERSION}${NC}"
echo
