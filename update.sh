#!/bin/bash
# Mysterium Node Toolkit — Update Script
# Pulls latest code, rebuilds frontend, restarts backend.
# Run from the toolkit directory: sudo ./update.sh

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

# ── Must run as root (sudo) ───────────────────────────────────────────────
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}✗ This script must be run with sudo.${NC}"
    echo -e "  Run: ${BOLD}sudo ./update.sh${NC}"
    exit 1
fi

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
    cp .build/package.json .build/vite.config.js .build/postcss.config.js .build/tailwind.config.js . 2>/dev/null || true
    cat > index.html << 'HTMLEOF'
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>Mysterium Dashboard</title></head>
<body><div id="root"></div><script type="module" src="/frontend/main.jsx"></script></body>
</html>
HTMLEOF
    # Remove stale dist/ and node_modules before building fresh
    rm -rf dist/ node_modules 2>/dev/null || true
    # Disable set -e for npm — warnings produce non-zero exit but build can still succeed
    set +e
    npm install --legacy-peer-deps > /dev/null 2>&1
    BUILD_OUT=$(npm run build 2>&1)
    set -e
    if [ -f "dist/index.html" ]; then
        echo -e "  ${GREEN}✓ Frontend rebuilt${NC}"
    else
        echo -e "  ${RED}✗ Frontend build failed${NC}"
        echo "$BUILD_OUT" | tail -10
        rm -f vite.config.js postcss.config.js tailwind.config.js package.json package-lock.json index.html
        exit 1
    fi
    rm -rf node_modules
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
    chown -R "$_REAL_USER:$_REAL_USER" "$TOOLKIT_DIR/logs" 2>/dev/null || true

    _MYST_SVC=""
    for _svc in mysterium-node myst mysterium; do
        if systemctl list-units --all --no-legend 2>/dev/null | grep -q "^.*${_svc}"; then
            _MYST_SVC="$_svc"
            break
        fi
    done
    _AFTER_DEPS="network-online.target${_MYST_SVC:+ $_MYST_SVC}"

    sudo tee "$_SERVICE_FILE" > /dev/null << UNIT_EOF
[Unit]
Description=Mysterium Node Monitoring Toolkit
After=${_AFTER_DEPS}
Wants=network-online.target

[Service]
Type=simple
User=$_REAL_USER
WorkingDirectory=$TOOLKIT_DIR
ExecStartPre=/bin/bash -c 'mkdir -p $TOOLKIT_DIR/logs && touch $TOOLKIT_DIR/logs/backend.log'
ExecStart=$_VENV_PYTHON backend/app.py
Restart=on-failure
RestartSec=10
StartLimitIntervalSec=0
StandardInput=null
StandardOutput=append:$TOOLKIT_DIR/logs/backend.log
StandardError=append:$TOOLKIT_DIR/logs/backend.log
Environment=HOME=$_REAL_HOME

[Install]
WantedBy=multi-user.target
UNIT_EOF
    sudo systemctl daemon-reload
    echo -e "  ${GREEN}✓ Systemd service updated${NC}"

    # Update sudoers
    _SUDOERS_FILE="/etc/sudoers.d/mysterium-toolkit"
    sudo tee "$_SUDOERS_FILE" > /dev/null << SUDOERS_EOF
# Mysterium Toolkit — passwordless sudo for specific commands only
$_REAL_USER ALL=(ALL) NOPASSWD: /sbin/sysctl, /usr/sbin/ethtool, /usr/sbin/conntrack, /usr/local/bin/mysterium-rps-watcher.sh, /usr/local/bin/mysterium-rps-setup.sh, /usr/bin/tee /etc/sysctl.d/*, /usr/bin/tee /usr/local/bin/*, /usr/bin/tee /etc/systemd/system/mysterium-*.service, /usr/bin/tee /etc/systemd/system/mysterium-*.timer, /bin/systemctl start mysterium-*, /bin/systemctl stop mysterium-*, /bin/systemctl enable mysterium-*, /bin/systemctl disable mysterium-*, /bin/systemctl daemon-reload, /usr/sbin/iptables, /sbin/iptables, /usr/sbin/iptables-legacy, /sbin/iptables-legacy, /usr/sbin/ip6tables, /sbin/ip6tables, /usr/sbin/nft, /sbin/nft
SUDOERS_EOF
    sudo chmod 440 "$_SUDOERS_FILE"
    echo -e "  ${GREEN}✓ Sudoers updated${NC}"
fi

# ── Restart backend ───────────────────────────────────────────────────────
echo
echo -e "  Restarting backend..."
if systemctl is-active --quiet mysterium-toolkit 2>/dev/null; then
    sudo systemctl restart mysterium-toolkit
    sleep 3
    if systemctl is-active --quiet mysterium-toolkit 2>/dev/null; then
        echo -e "  ${GREEN}✓ Backend restarted via systemd${NC}"
    else
        echo -e "  ${RED}✗ Backend failed to restart — check: sudo journalctl -u mysterium-toolkit -n 20${NC}"
    fi
else
    pkill -f "backend/app.py" 2>/dev/null || true
    sleep 1
    nohup venv/bin/python backend/app.py > logs/backend.log 2>&1 &
    sleep 3
    if pgrep -f "backend/app.py" > /dev/null; then
        echo -e "  ${GREEN}✓ Backend started${NC}"
    else
        echo -e "  ${RED}✗ Backend failed to start — check logs/backend.log${NC}"
    fi
fi

echo
echo -e "${GREEN}✓ Update complete — v${NEW_VERSION}${NC}"
echo
