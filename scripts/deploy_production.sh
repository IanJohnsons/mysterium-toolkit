#!/bin/bash
# Mysterium Node Toolkit — Production Deployment
# ================================================
# Sets up the toolkit as a production service on a VPS/server:
#   - Builds the frontend (Vite → static files)
#   - Creates a systemd service for the backend
#   - Configures nginx as reverse proxy (optional)
#   - Opens the required firewall port
#
# Usage:
#   bash scripts/deploy_production.sh
#   bash scripts/deploy_production.sh --port 8080 --no-nginx
#
# Author: Ian Johnsons
# License: CC BY-NC-SA 4.0

set -e

TOOLKIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$TOOLKIT_DIR"

VERSION=$(cat VERSION 2>/dev/null || echo "5.0.0")
SERVICE_NAME="mysterium-toolkit"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'
CYAN='\033[96m'; BOLD='\033[1m'; DIM='\033[2m'; NC='\033[0m'

ok()   { echo -e "  ${GREEN}✓${NC} $1"; }
warn() { echo -e "  ${YELLOW}⚠${NC} $1"; }
err()  { echo -e "  ${RED}✗${NC} $1"; }
info() { echo -e "  ${CYAN}·${NC} $1"; }

_box() {
    local t="$1" w=68
    echo "╔$(printf '═%.0s' $(seq 1 $w))╗"
    echo "║  $(printf "%-$((w-2))s" "$t")║"
    echo "╚$(printf '═%.0s' $(seq 1 $w))╝"
}

# ── Parse args ────────────────────────────────────────────────────────────────
SETUP_NGINX=true
CUSTOM_PORT=""
for arg in "$@"; do
    case "$arg" in
        --no-nginx)    SETUP_NGINX=false ;;
        --port=*)      CUSTOM_PORT="${arg#--port=}" ;;
        --port)        shift; CUSTOM_PORT="$1" ;;
    esac
done

# ── Checks ────────────────────────────────────────────────────────────────────
echo
_box "Mysterium Toolkit v${VERSION} — Production Deployment"
echo

# Must have venv
if [ ! -f "$TOOLKIT_DIR/venv/bin/activate" ]; then
    err "Virtual environment not found. Run setup first: ./bin/setup.sh"
    exit 1
fi

# Must have config
if [ ! -f "$TOOLKIT_DIR/config/setup.json" ]; then
    err "config/setup.json not found. Run setup first: ./bin/setup.sh"
    exit 1
fi

# Read dashboard port from config
DASH_PORT=$(python3 -c "
import json, pathlib
cfg = pathlib.Path('config/setup.json')
if cfg.exists():
    d = json.loads(cfg.read_text())
    print(d.get('dashboard_port', 5000))
else:
    print(5000)
" 2>/dev/null || echo "5000")

[ -n "$CUSTOM_PORT" ] && DASH_PORT="$CUSTOM_PORT"
PYTHON_BIN="$TOOLKIT_DIR/venv/bin/python3"

echo "  Dashboard port : $DASH_PORT"
echo "  Toolkit dir    : $TOOLKIT_DIR"
echo "  Service name   : $SERVICE_NAME"
echo "  Nginx setup    : $SETUP_NGINX"
echo

# ── Step 1: Build frontend ─────────────────────────────────────────────────────
echo "Step 1: Building frontend (Vite → static files)..."
if command -v npm >/dev/null 2>&1; then
    cd "$TOOLKIT_DIR"
    # Ensure node_modules are installed
    if [ ! -d "node_modules" ]; then
        npm install --legacy-peer-deps --silent
    fi
    npm run build 2>&1 | tail -5
    if [ -d "dist" ]; then
        ok "Frontend built → dist/"
    else
        warn "Build may have failed — check npm output above"
    fi
else
    warn "npm not found — frontend will run in dev mode (Vite)"
    warn "Install Node.js for production mode"
fi
echo

# ── Step 2: Systemd service ────────────────────────────────────────────────────
echo "Step 2: Creating systemd service..."

# Detect current user (for the service)
RUN_USER="${SUDO_USER:-$(whoami)}"
if [ "$RUN_USER" = "root" ]; then
    RUN_USER="root"
fi

cat > /tmp/${SERVICE_NAME}.service << EOF
[Unit]
Description=Mysterium Node Toolkit Dashboard v${VERSION}
Documentation=https://docs.mysterium.network
After=network.target mysterium-node.service
Wants=mysterium-node.service

[Service]
Type=simple
User=${RUN_USER}
WorkingDirectory=${TOOLKIT_DIR}
Environment=PYTHONUNBUFFERED=1
Environment=FLASK_ENV=production
ExecStart=${PYTHON_BIN} backend/app.py
Restart=always
RestartSec=5
StandardOutput=append:${TOOLKIT_DIR}/logs/backend.log
StandardError=append:${TOOLKIT_DIR}/logs/backend.log

# Security hardening
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

# Create logs dir
mkdir -p "$TOOLKIT_DIR/logs"

if [ "$(id -u)" = "0" ]; then
    cp /tmp/${SERVICE_NAME}.service "$SERVICE_FILE"
    systemctl daemon-reload
    systemctl enable "$SERVICE_NAME"
    systemctl restart "$SERVICE_NAME"
    sleep 2
    if systemctl is-active "$SERVICE_NAME" >/dev/null 2>&1; then
        ok "Service '${SERVICE_NAME}' is running"
        ok "Auto-start on boot enabled"
    else
        warn "Service created but not yet running"
        warn "Check: sudo journalctl -u ${SERVICE_NAME} -n 20"
    fi
else
    # Not root — copy with sudo
    sudo cp /tmp/${SERVICE_NAME}.service "$SERVICE_FILE"
    sudo systemctl daemon-reload
    sudo systemctl enable "$SERVICE_NAME"
    sudo systemctl restart "$SERVICE_NAME"
    sleep 2
    if systemctl is-active "$SERVICE_NAME" >/dev/null 2>&1; then
        ok "Service '${SERVICE_NAME}' is running"
        ok "Auto-start on boot enabled"
    else
        warn "Service created but not running — check logs"
    fi
fi
echo

# ── Step 3: Nginx reverse proxy ────────────────────────────────────────────────
if [ "$SETUP_NGINX" = "true" ]; then
    echo "Step 3: Configuring nginx..."
    if ! command -v nginx >/dev/null 2>&1; then
        info "nginx not installed — installing..."
        if command -v apt-get >/dev/null 2>&1; then
            sudo apt-get install -y -qq nginx >/dev/null 2>&1
        elif command -v dnf >/dev/null 2>&1; then
            sudo dnf install -y nginx >/dev/null 2>&1
        fi
    fi

    if command -v nginx >/dev/null 2>&1; then
        NGINX_CONF="/etc/nginx/sites-available/${SERVICE_NAME}"
        NGINX_LINK="/etc/nginx/sites-enabled/${SERVICE_NAME}"

        cat > /tmp/${SERVICE_NAME}.nginx << EOF
# Mysterium Node Toolkit — nginx reverse proxy
# Generated by deploy_production.sh
server {
    listen 80;
    listen [::]:80;
    server_name _;

    # Serve Vite build (if available) from dist/
    root ${TOOLKIT_DIR}/dist;
    index index.html;

    # API requests → Flask backend
    location / {
        # Try static file first, fall back to Flask
        try_files \$uri \$uri/ @flask;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:${DASH_PORT}/;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 30;
        proxy_connect_timeout 10;
    }

    location @flask {
        proxy_pass http://127.0.0.1:${DASH_PORT};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 30;
        proxy_connect_timeout 10;
    }

    # WebSocket support (for live updates)
    location /ws {
        proxy_pass http://127.0.0.1:${DASH_PORT};
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    # Security headers
    add_header X-Frame-Options DENY;
    add_header X-Content-Type-Options nosniff;
    add_header Referrer-Policy strict-origin-when-cross-origin;

    access_log /var/log/nginx/${SERVICE_NAME}.access.log;
    error_log  /var/log/nginx/${SERVICE_NAME}.error.log;
}
EOF

        sudo cp /tmp/${SERVICE_NAME}.nginx "$NGINX_CONF"
        sudo ln -sf "$NGINX_CONF" "$NGINX_LINK" 2>/dev/null || true
        # Remove default site if it exists
        sudo rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true
        if sudo nginx -t 2>/dev/null; then
            sudo systemctl enable nginx 2>/dev/null || true
            sudo systemctl reload nginx
            ok "nginx configured and reloaded"
            ok "Dashboard available at: http://$(curl -s ifconfig.me 2>/dev/null || echo 'YOUR-SERVER-IP')/"
        else
            warn "nginx config test failed — check /tmp/${SERVICE_NAME}.nginx"
        fi
    else
        warn "Could not install nginx — toolkit accessible directly on port $DASH_PORT"
    fi
else
    echo "Step 3: nginx — skipped (--no-nginx)"
fi
echo

# ── Step 4: Firewall ────────────────────────────────────────────────────────────
echo "Step 4: Firewall..."
if command -v ufw >/dev/null 2>&1; then
    sudo ufw allow 80/tcp   comment 'Mysterium Toolkit (nginx)' 2>/dev/null || true
    sudo ufw allow "${DASH_PORT}/tcp" comment 'Mysterium Toolkit (direct)' 2>/dev/null || true
    ok "ufw rules added for port 80 and $DASH_PORT"
elif command -v firewall-cmd >/dev/null 2>&1; then
    sudo firewall-cmd --permanent --add-port=80/tcp 2>/dev/null || true
    sudo firewall-cmd --permanent --add-port="${DASH_PORT}/tcp" 2>/dev/null || true
    sudo firewall-cmd --reload 2>/dev/null || true
    ok "firewalld rules added"
else
    warn "No firewall manager found (ufw/firewalld)"
    warn "Manually open port 80 and $DASH_PORT in your Hetzner firewall panel"
fi
echo

# ── Summary ─────────────────────────────────────────────────────────────────────
_box "Deployment Complete"
echo
PUBLIC_IP=$(curl -s --max-time 4 ifconfig.me 2>/dev/null || curl -s --max-time 4 api.ipify.org 2>/dev/null || echo "YOUR-SERVER-IP")

echo -e "  ${BOLD}Access your dashboard:${NC}"
if [ "$SETUP_NGINX" = "true" ] && command -v nginx >/dev/null 2>&1; then
    echo -e "  ${GREEN}  http://${PUBLIC_IP}/${NC}           (via nginx, port 80)"
fi
echo -e "  ${CYAN}  http://${PUBLIC_IP}:${DASH_PORT}/${NC}  (direct Flask)"
echo
echo -e "  ${BOLD}Manage the service:${NC}"
echo -e "  ${DIM}  Status:   sudo systemctl status ${SERVICE_NAME}${NC}"
echo -e "  ${DIM}  Logs:     sudo journalctl -u ${SERVICE_NAME} -f${NC}"
echo -e "  ${DIM}  Restart:  sudo systemctl restart ${SERVICE_NAME}${NC}"
echo -e "  ${DIM}  Stop:     sudo systemctl stop ${SERVICE_NAME}${NC}"
echo
echo -e "  ${BOLD}Hetzner firewall reminder:${NC}"
echo -e "  ${YELLOW}  Open port 80 (HTTP) in your Hetzner Cloud firewall rules${NC}"
echo -e "  ${DIM}  Hetzner console → Security → Firewalls → Add rule → TCP 80${NC}"
echo
