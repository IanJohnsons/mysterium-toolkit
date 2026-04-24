#!/bin/bash

TOOLKIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$TOOLKIT_DIR"

# Root check — LXC containers and Docker run as root without sudo installed.
[ "$(id -u)" -eq 0 ] && SUDO="" || SUDO="sudo"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[96m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

# ── Portable process kill — pgrep -af is GNU only ────────────
_pkill_from_dir() {
    local pattern="$1" dir="$2"
    local pids
    if pgrep --help 2>&1 | grep -q -- "-a"; then
        pids=$(pgrep -af "$pattern" 2>/dev/null | grep "$dir" | awk '{print $1}' || true)
    else
        pids=$(ps aux 2>/dev/null | grep "$pattern" | grep "$dir" | grep -v grep | awk '{print $2}' || true)
    fi
    echo "$pids"
}

# PID files for tracking
BACKEND_PID_FILE="$TOOLKIT_DIR/logs/.backend.pid"
FRONTEND_PID_FILE="$TOOLKIT_DIR/logs/.frontend.pid"
BACKEND_LOG="$TOOLKIT_DIR/logs/backend.log"
FRONTEND_LOG="$TOOLKIT_DIR/logs/frontend.log"

mkdir -p "$TOOLKIT_DIR/logs"

if [ ! -d "venv" ]; then
    echo -e "${RED}✗ Setup not complete. Run: ./bin/setup.sh${NC}"
    exit 1
fi

source venv/bin/activate

# ============ FIRST-RUN DISCLAIMER ============
VERSION=$(cat "$TOOLKIT_DIR/VERSION" 2>/dev/null || echo "unknown")
AGREED_FILE="$TOOLKIT_DIR/config/.agreed"
AGREED_VERSION=""
[ -f "$AGREED_FILE" ] && AGREED_VERSION=$(grep '^version=' "$AGREED_FILE" 2>/dev/null | cut -d= -f2)
CURRENT_MAJOR=$(echo "$VERSION" | cut -d. -f1)
AGREED_MAJOR=$(echo "$AGREED_VERSION" | cut -d. -f1)

# Show disclaimer if: never agreed, OR agreed on a different major version
if [ ! -f "$AGREED_FILE" ] || [ "$AGREED_MAJOR" != "$CURRENT_MAJOR" ]; then
    clear
    echo -e "${CYAN}${BOLD}"
    printf "╔"; printf '═%.0s' $(seq 1 68); printf "╗\n"
    printf "║%*s%s%*s║\n" 14 "" "MYSTERIUM NODE TOOLKIT — DISCLAIMER" 19 ""
    printf "╚"; printf '═%.0s' $(seq 1 68); printf "╝\n"
    echo -e "${NC}"
    echo -e "  ${BOLD}Important — Please Read Before Using${NC}"
    echo
    echo "  This toolkit monitors and manages Mysterium Network VPN nodes."
    echo "  By using this software you acknowledge and agree to all of the"
    echo "  following:"
    echo
    echo -e "  ${YELLOW}1. EXIT NODE RESPONSIBILITY${NC}"
    echo "     As a node operator you provide exit bandwidth — other people's"
    echo "     internet traffic passes through your IP address. You are solely"
    echo "     responsible for understanding what this means legally in your"
    echo "     country or region. Mysterium Network and the toolkit author"
    echo "     (Ian Johnsons) cannot be held responsible for how consumers"
    echo "     use your node or for any consequences arising from that use."
    echo
    echo -e "  ${YELLOW}2. LOCAL LAW COMPLIANCE${NC}"
    echo "     Operating a VPN exit node may be subject to laws in your"
    echo "     jurisdiction regarding traffic routing, data retention, or"
    echo "     network services. It is your responsibility to verify that"
    echo "     running a node is legal where you are located."
    echo
    echo "  3. MYSTERIUM NETWORK TERMS"
    echo "     You have read and agree to the Mysterium Network Terms of"
    echo "     Service for node operators:"
    echo "     https://mysterium.network/terms-conditions"
    echo
    echo "  4. NO WARRANTY"
    echo "     This toolkit is provided \"as is\" without warranty of any kind."
    echo "     The author is not liable for any damages, losses, or service"
    echo "     interruptions arising from use of this software."
    echo
    echo "  5. LICENSE"
    echo "     CC BY-NC-SA 4.0 — free for personal and community use."
    echo "     Not for commercial use. Credit the author if redistributed."
    echo
    echo -e "  ${DIM}Author: Ian Johnsons  ·  Support: Mysterium Network Telegram${NC}"
    echo
    echo -e "  ${YELLOW}${BOLD}To continue, type exactly: I AGREE${NC}"
    echo
    while true; do
        read -p "  > " agreement
        if [ "$agreement" = "I AGREE" ]; then
            mkdir -p "$TOOLKIT_DIR/config"
            printf "version=%s\ndate=%s\n" "$VERSION" "$(date -Iseconds)" > "$AGREED_FILE"
            echo -e "  ${GREEN}✓ Agreement accepted. Welcome to the toolkit!${NC}"
            sleep 1
            break
        else
            echo -e "  ${RED}Please type exactly: I AGREE${NC}"
        fi
    done
fi

# ============ HELPER FUNCTIONS ============

# Detect own IP for network access URL
OWN_IP=$(python3 -c "import socket; s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.connect(('8.8.8.8',80)); print(s.getsockname()[0]); s.close()" 2>/dev/null || echo "localhost")
DASHBOARD_PORT=$(grep -oP '(?<=DASHBOARD_PORT=)\d+' "$TOOLKIT_DIR/.env" 2>/dev/null || echo "5000")

DASHBOARD_URL="http://localhost:${DASHBOARD_PORT}"
DASHBOARD_URL_NETWORK="http://${OWN_IP}:${DASHBOARD_PORT}"
PROD_MODE=false
[ -f "$TOOLKIT_DIR/dist/index.html" ] && PROD_MODE=true

open_browser() {
    # Try to open the dashboard in the default browser
    if command -v xdg-open &>/dev/null; then
        xdg-open "$DASHBOARD_URL" &>/dev/null &
    elif command -v sensible-browser &>/dev/null; then
        sensible-browser "$DASHBOARD_URL" &>/dev/null &
    elif command -v x-www-browser &>/dev/null; then
        x-www-browser "$DASHBOARD_URL" &>/dev/null &
    elif command -v gnome-open &>/dev/null; then
        gnome-open "$DASHBOARD_URL" &>/dev/null &
    elif command -v open &>/dev/null; then
        open "$DASHBOARD_URL" &>/dev/null &
    fi
}

is_backend_running() {
    # Check 1: PID file written by backend process itself
    if [ -f "$BACKEND_PID_FILE" ]; then
        local pid=$(cat "$BACKEND_PID_FILE" 2>/dev/null)
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            return 0
        fi
        rm -f "$BACKEND_PID_FILE"
    fi
    # Check 2: systemd service running (autostart mode — no PID file written by start.sh)
    if systemctl is-active --quiet mysterium-toolkit 2>/dev/null; then
        return 0
    fi
    return 1
}

is_frontend_running() {
    if [ -f "$FRONTEND_PID_FILE" ]; then
        local pid=$(cat "$FRONTEND_PID_FILE" 2>/dev/null)
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            return 0
        fi
        rm -f "$FRONTEND_PID_FILE"
    fi
    return 1
}

get_status_line() {
    local backend_status="${RED}Stopped${NC}"
    if is_backend_running; then
        if systemctl is-active --quiet mysterium-toolkit 2>/dev/null; then
            backend_status="${GREEN}Running${NC} ${DIM}(systemd)${NC}"
        else
            local pid=$(cat "$BACKEND_PID_FILE" 2>/dev/null)
            backend_status="${GREEN}Running${NC} ${DIM}(PID $pid)${NC}"
        fi
    fi
    echo -e "  Backend:  $backend_status"
    echo -e "  Dashboard: ${DASHBOARD_URL}"
    echo -e "  → Network: ${DASHBOARD_URL_NETWORK}"
}

start_backend() {
    if systemctl is-active --quiet mysterium-toolkit 2>/dev/null; then
        echo -e "  ${GREEN}✓ Backend already running via systemd (autostart)${NC}"
        echo -e "  ${DIM}  Use: sudo systemctl stop mysterium-toolkit  to stop it${NC}"
        echo -e "  ${DIM}  Logs: sudo journalctl -u mysterium-toolkit -f${NC}"
        return 0
    fi
    if is_backend_running; then
        echo -e "  ${YELLOW}⚠ Backend already running (PID $(cat "$BACKEND_PID_FILE"))${NC}"
        return 0
    fi

    # Resolve python binary — venv first, then python3, then python
    local PYTHON_BIN
    if [ -f "$TOOLKIT_DIR/venv/bin/python" ]; then
        PYTHON_BIN="$TOOLKIT_DIR/venv/bin/python"
    elif command -v python3 &>/dev/null; then
        PYTHON_BIN="python3"
        echo -e "  ${YELLOW}⚠ venv not found — using system python3${NC}"
    else
        PYTHON_BIN="python"
    fi

    echo -n "  Starting backend..."
    nohup "$PYTHON_BIN" backend/app.py > "$BACKEND_LOG" 2>&1 &
    local pid=$!
    echo "$pid" > "$BACKEND_PID_FILE"

    # Wait briefly and verify it started
    sleep 2
    if kill -0 "$pid" 2>/dev/null; then
        echo -e " ${GREEN}✓ Running (PID $pid)${NC}"
        echo -e "    Local:   ${DASHBOARD_URL}"
        echo -e "    Network: ${DASHBOARD_URL_NETWORK}"
        return 0
    else
        echo -e " ${RED}✗ Failed to start. Check: tail -f $BACKEND_LOG${NC}"
        rm -f "$BACKEND_PID_FILE"
        return 1
    fi
}

start_frontend() {
    if is_frontend_running; then
        echo -e "  ${YELLOW}⚠ Frontend already running (PID $(cat "$FRONTEND_PID_FILE"))${NC}"
        return 0
    fi

    # Auto-install node_modules if vite is missing (e.g. after unzip without running setup)
    if [ ! -f "$TOOLKIT_DIR/node_modules/.bin/vite" ]; then
        # Ensure logs dir exists before any redirect
        mkdir -p "$TOOLKIT_DIR/logs"
        # Check npm is available
        if ! command -v npm &>/dev/null; then
            echo -e "  ${RED}✗ npm not found. Install Node.js + npm first:${NC}"
            echo -e "  ${DIM}  sudo apt install nodejs npm${NC}"
            return 1
        fi
        echo -e "  ${YELLOW}⚠ node_modules missing — running npm install (this takes ~30s)...${NC}"
        cd "$TOOLKIT_DIR"
        npm install --legacy-peer-deps 2>&1 | tee -a "$FRONTEND_LOG"
        if [ ! -f "$TOOLKIT_DIR/node_modules/.bin/vite" ]; then
            echo -e "  ${RED}✗ npm install finished but vite still missing. Check log above.${NC}"
            return 1
        fi
        echo -e "  ${GREEN}✓ npm install complete${NC}"
    fi
    cd "$TOOLKIT_DIR"

    echo -n "  Starting frontend..."
    nohup npm start > "$FRONTEND_LOG" 2>&1 &
    local pid=$!
    echo "$pid" > "$FRONTEND_PID_FILE"

    # Wait for vite to start
    sleep 4
    if kill -0 "$pid" 2>/dev/null; then
        echo -e " ${GREEN}✓ Running on http://localhost:3000 (Vite dev — PID $pid)${NC}"
        return 0
    else
        echo -e " ${RED}✗ Failed to start. Check: tail -f $FRONTEND_LOG${NC}"
        rm -f "$FRONTEND_PID_FILE"
        return 1
    fi
}

stop_backend() {
    if is_backend_running; then
        local pid=$(cat "$BACKEND_PID_FILE")
        kill "$pid" 2>/dev/null
        sleep 1
        kill -9 "$pid" 2>/dev/null
        rm -f "$BACKEND_PID_FILE"
        echo -e "  ${GREEN}✓ Backend stopped${NC}"
    else
        # Only kill processes from THIS toolkit directory, never broad patterns
        local pids; pids=$(_pkill_from_dir "python.*backend/app.py" "$TOOLKIT_DIR")
        if [ -n "$pids" ]; then
            echo "$pids" | xargs kill 2>/dev/null || true
            sleep 1
            echo "$pids" | xargs kill -9 2>/dev/null || true
            echo -e "  ${GREEN}✓ Backend stopped (orphan process)${NC}"
        else
            echo -e "  ${DIM}· Backend was not running${NC}"
        fi
    fi
}

stop_frontend() {
    if is_frontend_running; then
        local pid=$(cat "$FRONTEND_PID_FILE")
        kill "$pid" 2>/dev/null
        sleep 1
        kill -9 "$pid" 2>/dev/null
        rm -f "$FRONTEND_PID_FILE"
        # Kill child vite processes — only those from this directory
        local vite_pids; vite_pids=$(_pkill_from_dir "vite" "$TOOLKIT_DIR")
        [ -n "$vite_pids" ] && echo "$vite_pids" | xargs kill 2>/dev/null || true
        echo -e "  ${GREEN}✓ Frontend stopped${NC}"
    else
        local vite_pids; vite_pids=$(_pkill_from_dir "vite" "$TOOLKIT_DIR")
        if [ -n "$vite_pids" ]; then
            echo "$vite_pids" | xargs kill 2>/dev/null || true
            sleep 1
            echo "$vite_pids" | xargs kill -9 2>/dev/null || true
            echo -e "  ${GREEN}✓ Frontend stopped (orphan process)${NC}"
        else
            echo -e "  ${DIM}· Frontend was not running${NC}"
        fi
    fi
}

# ============ MAIN MENU LOOP ============

while true; do
    VERSION=$(cat "$TOOLKIT_DIR/VERSION" 2>/dev/null || echo "?")
    clear

    # Dynamic banner — auto-fits content
    _banner() {
        local text="$1"
        local color="${2:-}"
        local len=${#text}
        local total=68
        if [ $((len + 8)) -gt $total ]; then
            total=$((len + 8))
        fi
        local pad=$(( (total - len) / 2 ))
        local rpad=$(( total - pad - len ))
        local border=""
        for ((i=0; i<total; i++)); do border+="═"; done
        if [ -n "$color" ]; then
            echo -e "${color}╔${border}╗${NC}"
            printf "${color}║%*s%s%*s║${NC}\n" $pad "" "$text" $rpad ""
            echo -e "${color}╚${border}╝${NC}"
        else
            echo "╔${border}╗"
            printf "║%*s%s%*s║\n" $pad "" "$text" $rpad ""
            echo "╚${border}╝"
        fi
    }

    _banner "Mysterium Node Monitoring Dashboard v${VERSION}"
    echo -e "  ${DIM}♥ Made by Ian Johnsons — with love for the Mysterium Network${NC}"
    echo
    echo -e "  ${BOLD}Current Status:${NC}"
    get_status_line
    if is_backend_running; then
        echo
        echo -e "  ${CYAN}${BOLD}→ Dashboard: ${DASHBOARD_URL}${NC}"
    fi
    echo
    echo "  What do you want to do?"
    echo
    echo "  1. Start Dashboard"
    echo "  2. Start Backend Only"
    echo "  3. Rebuild Frontend (after code update)"
    echo "  4. Start CLI Dashboard (Terminal UI)"
    echo "  5. Stop Everything"
    echo "  6. View Logs (live tail)"
    echo "  7. Maintenance (scan, cleanup, uninstall)"
    echo "  8. System Diagnostics"
    echo "  9. Autostart on Boot (enable/disable)"
    echo "  0. Exit"
    echo

    read -p "  Select (0-9): " choice

    case $choice in
        1)
            echo
            echo -e "  ${BOLD}Starting dashboard...${NC}"
            echo
            start_backend
            echo
            if is_backend_running; then
                _banner "Dashboard Running!" "$GREEN"
                echo
                echo -e "  Open: ${CYAN}${BOLD}${DASHBOARD_URL}${NC}"
                echo
                echo -e "  ${DIM}Opening browser...${NC}"
                open_browser
                echo
                echo -e "  ${DIM}Logs: logs/backend.log${NC}"
            fi
            echo
            echo "  Press Enter to return to menu..."
            read -r
            ;;

        2)
            echo
            if systemctl is-active --quiet mysterium-toolkit 2>/dev/null; then
                echo -e "  ${YELLOW}Backend is running via systemd service.${NC}"
                echo -e "  Restarting via systemd..."
                $SUDO systemctl restart mysterium-toolkit
                sleep 3
                if systemctl is-active --quiet mysterium-toolkit 2>/dev/null; then
                    echo -e "  ${GREEN}✓ Backend restarted via systemd${NC}"
                else
                    echo -e "  ${RED}✗ Restart failed — check: sudo journalctl -u mysterium-toolkit -n 20${NC}"
                fi
            else
                start_backend
            fi
            echo
            echo "  Press Enter to return to menu..."
            read -r
            ;;

        3)
            echo
            echo -e "  ${BOLD}Rebuilding frontend...${NC}"
            echo
            if ! command -v npm &>/dev/null; then
                echo -e "  ${RED}✗ npm not found. Install Node.js first.${NC}"
                echo -e "  ${DIM}  sudo apt install nodejs npm${NC}"
            elif ! command -v node &>/dev/null; then
                echo -e "  ${RED}✗ Node.js not found.${NC}"
            else
                cd "$TOOLKIT_DIR"
                # Stop service and backend BEFORE building to avoid conflicts
                echo -e "  Stopping backend before build..."
                if systemctl is-active --quiet mysterium-toolkit 2>/dev/null; then
                    $SUDO systemctl stop mysterium-toolkit 2>/dev/null || true
                    echo -e "  ${DIM}  Systemd service stopped${NC}"
                fi
                stop_backend
                sleep 2
                # Restore build config from .build/ if not present
                if [ ! -f "package.json" ] && [ -f ".build/package.json" ]; then
                    cp .build/package.json package.json
                    cp .build/vite.config.js vite.config.js 2>/dev/null || true
                    cp .build/postcss.config.js postcss.config.js 2>/dev/null || true
                    cp .build/tailwind.config.js tailwind.config.js 2>/dev/null || true
                    # Generate index.html with correct path (not from .build/ which may have wrong path)
                    cat > index.html << 'IDXEOF'
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>Mysterium Dashboard</title>
<script>
(function(){try{var t=localStorage.getItem('myst-theme')||'emerald';document.documentElement.setAttribute('data-theme',t);var b={'cyber':'#050e18','sunset':'#170c05','violet':'#0e0514','crimson':'#140205','matrix':'#000a00','phosphor':'#020800','ghost':'#080808','midnight':'#020414','steel':'#080808','military':'#060800'};if(b[t])document.body.style.background=b[t];}catch(e){}})()</script>
</head>
<body><div id="root"></div>
<script type="module" src="/frontend/main.jsx"></script>
</body>
</html>
IDXEOF
                fi
                echo -e "  Installing build tools..."
                npm install --legacy-peer-deps > /dev/null 2>&1

                # Remove stale dist/ — always build fresh
                rm -rf dist/

                echo -e "  Building..."
                BUILD_OUTPUT=$(npm run build 2>&1)
                BUILD_EXIT=$?

                if [ -f "dist/index.html" ]; then
                    if [ $BUILD_EXIT -ne 0 ]; then
                        echo -e "  ${YELLOW}⚠ Build completed with warnings (exit $BUILD_EXIT) — dist/ looks valid.${NC}"
                        echo "$BUILD_OUTPUT" | grep -iE "error|warn" | head -5 || true
                    else
                        echo -e "  ${GREEN}✓ Frontend rebuilt → dist/${NC}"
                    fi
                    echo -e "  Cleaning up build tools..."
                    rm -rf node_modules
                    rm -f vite.config.js postcss.config.js tailwind.config.js
                    rm -f package.json package-lock.json package-lock.json.bak index.html
                    echo -e "  ${GREEN}✓ Clean. Restarting backend...${NC}"
                    stop_backend
                    sleep 1
                    start_backend
                else
                    echo -e "  ${RED}✗ Build failed — dist/index.html not produced. Full output:${NC}"
                    echo "$BUILD_OUTPUT"
                    echo
                    echo -e "  ${YELLOW}node_modules kept for debugging. Fix the error above and try again.${NC}"
                fi
            fi
            echo
            echo "  Press Enter to return to menu..."
            read -r
            ;;

        4)
            echo
            echo -e "  ${BOLD}Starting CLI Dashboard...${NC}"
            echo
            # Start backend if not running
            if ! is_backend_running; then
                echo -e "  ${YELLOW}Backend not running — starting it first...${NC}"
                start_backend
                sleep 2
            fi
            if is_backend_running; then
                echo -e "  ${GREEN}✓ Backend ready — launching terminal UI${NC}"
                echo -e "  ${DIM}Press 'q' to exit CLI and return to menu${NC}"
                echo
                sleep 1
                # Use venv python, fall back to python3
            CLI_PY=""
            if [ -f "$TOOLKIT_DIR/venv/bin/python" ]; then
                CLI_PY="$TOOLKIT_DIR/venv/bin/python"
            else
                CLI_PY="$(command -v python3 || command -v python)"
            fi
            "$CLI_PY" "$TOOLKIT_DIR/cli/dashboard.py"
            else
                echo -e "  ${RED}✗ Backend failed to start. Cannot launch CLI.${NC}"
            fi
            echo
            echo "  Press Enter to return to menu..."
            read -r
            ;;

        5)
            echo
            echo -e "  ${BOLD}Stopping toolkit...${NC}"
            echo
            stop_backend
            echo
            echo -e "  ${GREEN}✓ Stopped.${NC}"
            echo
            echo "  Press Enter to return to menu..."
            read -r
            ;;

        6)
            echo
            echo -e "  ${BOLD}Which log to view?${NC}"
            echo
            echo "  1. Backend log"
            echo "  2. Frontend log"
            echo "  3. Both (interleaved)"
            echo "  4. Back to menu"
            echo
            read -p "  Select (1-4): " log_choice

            # Trap SIGINT (Ctrl+C) so it stops tail but returns to menu
            view_log() {
                trap '' INT   # Ignore SIGINT in parent
                "$@" &        # Run tail in background
                local tail_pid=$!
                trap "kill $tail_pid 2>/dev/null; wait $tail_pid 2>/dev/null" INT
                wait $tail_pid 2>/dev/null
                trap - INT    # Restore default
            }

            case $log_choice in
                1)
                    if [ -f "$BACKEND_LOG" ]; then
                        echo
                        echo -e "  ${DIM}Showing backend log (Ctrl+C to return to menu)${NC}"
                        echo
                        view_log tail -f "$BACKEND_LOG"
                    else
                        echo -e "  ${YELLOW}No backend log found${NC}"
                        sleep 2
                    fi
                    ;;
                2)
                    if [ -f "$FRONTEND_LOG" ]; then
                        echo
                        echo -e "  ${DIM}Showing frontend log (Ctrl+C to return to menu)${NC}"
                        echo
                        view_log tail -f "$FRONTEND_LOG"
                    else
                        echo -e "  ${YELLOW}No frontend log found${NC}"
                        sleep 2
                    fi
                    ;;
                3)
                    if [ -f "$BACKEND_LOG" ] || [ -f "$FRONTEND_LOG" ]; then
                        echo
                        echo -e "  ${DIM}Showing logs (Ctrl+C to return to menu)${NC}"
                        echo
                        view_log tail -f "$BACKEND_LOG" "$FRONTEND_LOG"
                    else
                        echo -e "  ${YELLOW}No log files found${NC}"
                        sleep 2
                    fi
                    ;;
                *)
                    ;;
            esac
            echo
            echo -e "  ${DIM}Returned to menu${NC}"
            sleep 1
            ;;

        7)
            echo
            echo -e "  ${CYAN}${BOLD}Maintenance${NC}"
            echo
            echo "  1. Scan for old toolkit installs"
            echo "  2. Clean runtime (venv, node_modules, logs)"
            echo "  3. Cleanup / Uninstall (full options)"
            echo "  4. Back to menu"
            echo
            read -p "  Select (1-4): " maint_choice
            case $maint_choice in
                1)
                    echo
                    "$TOOLKIT_DIR/venv/bin/python" scripts/env_scanner.py
                    ;;
                2|3)
                    echo
                    stop_backend
                    stop_frontend
                    if [ -f "$TOOLKIT_DIR/bin/cleanup.sh" ]; then
                        bash "$TOOLKIT_DIR/bin/cleanup.sh"
                    else
                        echo -e "  ${RED}Cleanup script not found.${NC}"
                    fi
                    ;;
                *)
                    ;;
            esac
            echo
            echo "  Press Enter to return to menu..."
            read -r
            ;;

        8)
            echo
            if [ -f "$TOOLKIT_DIR/bin/diagnose.sh" ]; then
                echo -e "  ${CYAN}${BOLD}System Diagnostics${NC}"
                echo -e "  ${DIM}Checks: thermal, memory, NIC, IRQ, conntrack, WireGuard, kernel${NC}"
                echo
                echo "  1. Run diagnostics (recommended)"
                echo "  2. Run with stress test (--stress)"
                echo "  3. Apply fixes for found issues (--fix)"
                echo "  4. Back to menu"
                echo
                read -p "  Select (1-4): " diag_choice
                case $diag_choice in
                    1)
                        $SUDO bash "$TOOLKIT_DIR/bin/diagnose.sh"
                        ;;
                    2)
                        echo -e "  ${YELLOW}⚠ Stress test will briefly increase system load${NC}"
                        read -p "  Continue? [y/N]: " stress_confirm
                        if [[ "$stress_confirm" =~ ^[Yy] ]]; then
                            $SUDO bash "$TOOLKIT_DIR/bin/diagnose.sh" --stress
                        fi
                        ;;
                    3)
                        echo -e "  ${DIM}Applying fixes — each one asks for confirmation${NC}"
                        echo
                        $SUDO bash "$TOOLKIT_DIR/bin/diagnose.sh" --fix
                        ;;
                    *)
                        ;;
                esac
            else
                echo -e "  ${RED}Diagnostic script not found at: $TOOLKIT_DIR/bin/diagnose.sh${NC}"
                echo -e "  ${DIM}Re-extract the toolkit to restore it.${NC}"
            fi
            echo
            echo "  Press Enter to return to menu..."
            read -r
            ;;


        9)
            echo
            echo -e "  ${CYAN}${BOLD}Autostart on Boot${NC}"
            echo
            _SERVICE_NAME="mysterium-toolkit"
            _SERVICE_FILE="/etc/systemd/system/${_SERVICE_NAME}.service"
            _VENV_PYTHON="$TOOLKIT_DIR/venv/bin/python"

            # Check current status — file check is more reliable than is-enabled
            # (some systemd versions return false for failed-but-enabled services)
            _svc_active=false
            if [ -f "/etc/systemd/system/${_SERVICE_NAME}.service" ] &&                systemctl is-enabled "$_SERVICE_NAME" 2>/dev/null | grep -qE '^(enabled|enabled-runtime)'; then
                _svc_active=true
            fi

            if [ "$_svc_active" = true ]; then
                echo -e "  ${GREEN}✓ Autostart is currently ENABLED${NC}"
                echo -e "  ${DIM}  Service: $_SERVICE_NAME${NC}"
                echo -e "  ${DIM}  The toolkit backend starts automatically at boot.${NC}"
                echo
                echo "  1. Disable autostart"
                echo "  2. Back to menu"
                echo
                read -p "  Select (1-2): " _auto_choice
                case "$_auto_choice" in
                    1)
                        $SUDO systemctl disable --now "$_SERVICE_NAME" 2>/dev/null || true
                        $SUDO rm -f "$_SERVICE_FILE"
                        $SUDO systemctl daemon-reload 2>/dev/null || true
                        echo -e "  ${GREEN}✓ Autostart disabled${NC}"
                        ;;
                    *)
                        ;;
                esac
            else
                echo -e "  ${YELLOW}Autostart is currently DISABLED${NC}"
                echo -e "  ${DIM}  The toolkit backend does NOT start automatically at boot.${NC}"
                echo
                echo "  1. Enable autostart (systemd service)"
                echo "  2. Back to menu"
                echo
                read -p "  Select (1-2): " _auto_choice
                case "$_auto_choice" in
                    1)
                        # Detect current user (even under sudo)
                        _REAL_USER="${SUDO_USER:-$USER}"
                        _REAL_HOME=$(getent passwd "$_REAL_USER" | cut -d: -f6)
                        mkdir -p "$TOOLKIT_DIR/logs"
                        # Ensure logs/ is owned by the real user, not root
                        # Without this, the systemd service (running as real user) can't write logs
                        chown -R "$_REAL_USER:$_REAL_USER" "$TOOLKIT_DIR/logs" 2>/dev/null || true

                        # Detect Mysterium node service name so toolkit starts after it
                        _MYST_SVC=""
                        for _svc in mysterium-node myst mysterium mysterium-node.service; do
                            if systemctl list-units --all --no-legend 2>/dev/null | grep -q "^.*${_svc}"; then
                                _MYST_SVC="$_svc"
                                break
                            fi
                        done
                        if [ -n "$_MYST_SVC" ]; then
                            _AFTER_DEPS="network-online.target $_MYST_SVC"
                            echo -e "  ${DIM}  Detected Mysterium service: $_MYST_SVC — toolkit will start after it${NC}"
                        else
                            _AFTER_DEPS="network-online.target"
                            echo -e "  ${DIM}  Mysterium node service not detected — using network-only dependency${NC}"
                        fi

                        # Write systemd unit file
                        $SUDO tee "$_SERVICE_FILE" > /dev/null << UNIT_EOF
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

                        $SUDO systemctl daemon-reload
                        $SUDO systemctl enable "$_SERVICE_NAME"
                        echo -e "  ${GREEN}✓ Autostart enabled — toolkit starts at every boot${NC}"
                        echo -e "  ${DIM}  Service: $_SERVICE_NAME${NC}"
                        echo
                        echo -e "  ${DIM}  Useful commands:${NC}"
                        echo -e "  ${DIM}    sudo systemctl status $_SERVICE_NAME${NC}"
                        echo -e "  ${DIM}    sudo systemctl stop $_SERVICE_NAME${NC}"
                        echo -e "  ${DIM}    sudo journalctl -u $_SERVICE_NAME -f${NC}"
                        echo
                        # Offer to start now
                        read -p "  Start the service now? [Y/n]: " _start_now
                        if [[ ! "$_start_now" =~ ^[Nn] ]]; then
                            # Stop ALL running backends — systemd service + any manual process
                            $SUDO systemctl stop mysterium-toolkit 2>/dev/null || true
                            stop_backend
                            # Kill anything still holding port 5000
                            _PORT_PID=$(lsof -ti :${DASHBOARD_PORT} 2>/dev/null || true)
                            [ -n "$_PORT_PID" ] && kill -9 "$_PORT_PID" 2>/dev/null || true
                            # Wait for port to be fully free
                            echo -e "  ${DIM}  Waiting for port to clear…${NC}"
                            sleep 5
                            _PORT_WAIT=0
                            while [ $_PORT_WAIT -lt 10 ]; do
                                lsof -ti :${DASHBOARD_PORT} >/dev/null 2>&1 || break
                                sleep 1; _PORT_WAIT=$((_PORT_WAIT+1))
                            done
                            $SUDO systemctl reset-failed "$_SERVICE_NAME" 2>/dev/null || true
                            $SUDO systemctl start "$_SERVICE_NAME"
                            # Wait up to 25 seconds — Python startup can be slow on laptops
                            echo -e "  ${DIM}  Starting service (may take up to 25s on first run)…${NC}"
                            _WAIT=0
                            while [ $_WAIT -lt 25 ]; do
                                sleep 1
                                _WAIT=$((_WAIT + 1))
                                if systemctl is-active --quiet "$_SERVICE_NAME"; then
                                    echo -e "  ${GREEN}✓ Service running${NC}"
                                    break
                                fi
                                # Still activating — keep waiting silently
                            done
                            if ! systemctl is-active --quiet "$_SERVICE_NAME"; then
                                # First-enable often fails due to a port/timing race.
                                # Reset failed state and retry once — second attempt always works.
                                echo -e "  ${YELLOW}⚠ First attempt failed — resetting and retrying…${NC}"
                                $SUDO systemctl reset-failed "$_SERVICE_NAME" 2>/dev/null || true
                                sleep 3
                                $SUDO systemctl start "$_SERVICE_NAME" 2>/dev/null || true
                                _RETRY=0
                                while [ $_RETRY -lt 20 ]; do
                                    sleep 1; _RETRY=$((_RETRY+1))
                                    if systemctl is-active --quiet "$_SERVICE_NAME"; then
                                        echo -e "  ${GREEN}✓ Service running${NC}"
                                        break
                                    fi
                                done
                                if ! systemctl is-active --quiet "$_SERVICE_NAME"; then
                                    echo -e "  ${YELLOW}⚠ Service not running. Check:${NC}"
                                    echo -e "  ${DIM}    sudo journalctl -u $_SERVICE_NAME -n 20${NC}"
                                fi
                            fi
                        fi
                        ;;
                    *)
                        ;;
                esac
            fi
            echo
            echo "  Press Enter to return to menu..."
            read -r
            ;;

        0)
            echo
            if is_backend_running; then
                echo -e "  ${YELLOW}⚠ Servers are still running in the background.${NC}"
                echo -e "  ${DIM}  They will keep running after you exit this menu.${NC}"
                echo -e "  ${DIM}  Use option 5 to stop them, or run: ./stop.sh${NC}"
                echo
                read -p "  Exit anyway? [Y/n]: " confirm
                if [[ "$confirm" =~ ^[Nn] ]]; then
                    continue
                fi
            fi
            echo
            echo -e "  ${GREEN}Thank you for using the Mysterium Node Toolkit!${NC}"
            echo -e "  ${DIM}Happy earning — Ian Johnsons ♥${NC}"
            echo
            exit 0
            ;;

        *)
            echo -e "  ${RED}Invalid choice${NC}"
            sleep 1
            ;;
    esac
done
