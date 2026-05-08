#!/bin/bash
# Intentionally NO set -e — each step handles its own errors

TOOLKIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$TOOLKIT_DIR"

# Root check — LXC containers and Docker run as root without sudo installed.
# $SUDO is empty when already root, 'sudo' otherwise.
[ "$(id -u)" -eq 0 ] && SUDO="" || SUDO="sudo"

# Read version
VERSION=$(cat VERSION 2>/dev/null || echo "unknown")
DASHBOARD_PORT=$(python3 -c "
import json, pathlib, os
cfg = pathlib.Path('config/setup.json')
if cfg.exists():
    d = json.loads(cfg.read_text())
    print(d.get('dashboard_port', 5000))
else:
    print(os.environ.get('DASHBOARD_PORT', 5000))
" 2>/dev/null || echo "5000")

# Box drawing helper
_box_line() {
    local text="$1" color="${2:-}"
    local box_inner=68
    local padded
    padded=$(printf "%-${box_inner}s" "   $text")
    if [ -n "$color" ]; then
        echo -e "${color}║${padded}║\033[0m"
    else
        echo "║${padded}║"
    fi
}
_box_top() { local b=""; for((i=0;i<68;i++)); do b+="═"; done; echo "╔${b}╗"; }
_box_bot() { local b=""; for((i=0;i<68;i++)); do b+="═"; done; echo "╚${b}╝"; }

_box_top
_box_line "Mysterium Node Monitoring Dashboard v${VERSION}"
_box_line "Setup"
_box_bot
echo

# Disclaimer is shown by start.sh (full version with I AGREE prompt).
# setup.sh does not duplicate it — .agreed is written by start.sh on first run.

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[96m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

# ============ SETUP MODE SELECTION ============
echo -e "  ${BOLD}Choose installation type:${NC}"
echo
echo -e "  ${CYAN}1. Full install${NC}        — Node on this machine. Full dashboard, CLI, all features."
echo -e "                        ${DIM}Default. Use this for your main node machine.${NC}"
echo
echo -e "  ${CYAN}2. Fleet master${NC}        — Central dashboard to monitor multiple remote nodes."
echo -e "                        ${DIM}Installs full toolkit. Helps configure nodes.json after setup.${NC}"
echo
echo -e "  ${CYAN}3. Lightweight backend${NC} — Backend only, no browser dashboard."
echo -e "                        ${DIM}For remote nodes monitored by a fleet master.${NC}"
echo -e "                        ${DIM}No Node.js/npm needed. Minimal resources. Serves /peer/data.${NC}"
echo
read -p "  Select (1-3) [default: 1]: " SETUP_MODE_INPUT
case "${SETUP_MODE_INPUT:-1}" in
    2) SETUP_MODE=2 ;;
    3) SETUP_MODE=3 ;;
    *) SETUP_MODE=1 ;;
esac

case $SETUP_MODE in
    1) echo -e "  ${GREEN}✓ Full install${NC}" ;;
    2) echo -e "  ${GREEN}✓ Fleet master${NC}" ;;
    3) echo -e "  ${GREEN}✓ Lightweight backend${NC}" ;;
esac
echo


# ── Detect package manager once ──────────────────────────────
PKG_MGR=""
command -v apt-get >/dev/null 2>&1 && PKG_MGR="apt"
command -v dnf     >/dev/null 2>&1 && [ -z "$PKG_MGR" ] && PKG_MGR="dnf"
command -v yum     >/dev/null 2>&1 && [ -z "$PKG_MGR" ] && PKG_MGR="yum"
command -v pacman  >/dev/null 2>&1 && [ -z "$PKG_MGR" ] && PKG_MGR="pacman"
command -v apk     >/dev/null 2>&1 && [ -z "$PKG_MGR" ] && PKG_MGR="apk"

# ── Portable process kill — pgrep -af is GNU only ────────────
_pkill_toolkit() {
    local pattern="$1"
    local pids
    # Kill ALL matching processes — not just from current dir (catches old installs too)
    if pgrep --help 2>&1 | grep -q -- "-a"; then
        pids=$(pgrep -af "$pattern" 2>/dev/null | grep -v grep | awk '{print $1}' || true)
    else
        pids=$(ps aux 2>/dev/null | grep "$pattern" | grep -v grep | awk '{print $2}' || true)
    fi
    [ -n "$pids" ] && echo "$pids" | xargs kill -9 2>/dev/null || true
}

# ── Install helper — all major distros + Alpine ──────────────
pkg_install() {
    local tool="$1" apt_p="$2" dnf_p="$3" pac_p="${4:-$3}" apk_p="${5:-$2}"
    if command -v "$tool" >/dev/null 2>&1; then
        echo -e "  ${GREEN}✓ ${tool}${NC}"; return 0
    fi
    echo -e "  ${YELLOW}⚠ ${tool} not found — installing...${NC}"
    case "$PKG_MGR" in
        apt)    $SUDO apt-get install -y -qq "$apt_p" >/dev/null 2>&1 || true ;;
        dnf)    $SUDO dnf install -y -q   "$dnf_p"  >/dev/null 2>&1 || true ;;
        yum)    $SUDO yum install -y -q   "$dnf_p"  >/dev/null 2>&1 || true ;;
        pacman) $SUDO pacman -S --noconfirm "$pac_p" >/dev/null 2>&1 || true ;;
        apk)    apk add "$apk_p"                   >/dev/null 2>&1 || true ;;
        *)      echo -e "  ${YELLOW}⚠ No supported package manager — install ${tool} manually${NC}"; return 0 ;;
    esac
    command -v "$tool" >/dev/null 2>&1 \
        && echo -e "  ${GREEN}✓ ${tool} installed${NC}" \
        || echo -e "  ${YELLOW}⚠ Could not install ${tool} — some features may be limited${NC}"
}
# ============ PRE-FLIGHT: PYTHON VERSION CHECK ============
echo "Pre-flight checks..."
PYTHON_CMD=""
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
elif command -v python &> /dev/null; then
    PYTHON_CMD="python"
fi

if [ -z "$PYTHON_CMD" ]; then
    echo -e "${RED}✗ Python 3 not found. Install python3 (3.8+) first.${NC}"
    echo "  Debian/Ubuntu: sudo apt install python3 python3-pip python3-venv"
    echo "  Fedora/RHEL:   sudo dnf install python3 python3-pip"
    echo "  Arch:          sudo pacman -S python python-pip"
    echo "  Alpine:        apk add python3 py3-pip"
    exit 1
fi

PY_VER=$($PYTHON_CMD -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null)
PY_MAJOR=$($PYTHON_CMD -c 'import sys; print(sys.version_info.major)' 2>/dev/null || echo 0)
PY_MINOR=$($PYTHON_CMD -c 'import sys; print(sys.version_info.minor)' 2>/dev/null || echo 0)

if [ "$PY_MAJOR" -lt 3 ] || ([ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 8 ]); then
    echo -e "${RED}✗ Python $PY_VER found but 3.8+ required.${NC}"
    echo "  Upgrade: sudo apt install python3 (or use pyenv)"
    exit 1
fi
echo -e "${GREEN}✓ Python $PY_VER${NC}"

# Check pip
if ! $PYTHON_CMD -m pip --version &> /dev/null; then
    echo -e "${YELLOW}⚠ pip not found. Installing...${NC}"
    if command -v apt &> /dev/null; then
        $SUDO apt install -y python3-pip python3-venv 2>/dev/null || true
    elif command -v dnf &> /dev/null; then
        $SUDO dnf install -y python3-pip 2>/dev/null || true
    elif command -v pacman &> /dev/null; then
        $SUDO pacman -S --noconfirm python-pip 2>/dev/null || true
    elif command -v apk &> /dev/null; then
        apk add py3-pip 2>/dev/null || true
    fi
fi

# Check optional tools
echo -n "  Optional tools: "
OPTIONALS=""
command -v vnstat &> /dev/null && OPTIONALS+="vnstat " || true
command -v ethtool &> /dev/null && OPTIONALS+="ethtool " || true
command -v ufw &> /dev/null && OPTIONALS+="ufw " || true
command -v docker &> /dev/null && OPTIONALS+="docker " || true
command -v node &> /dev/null && OPTIONALS+="node " || true
command -v npm &> /dev/null && OPTIONALS+="npm " || true
echo -e "${CYAN}${OPTIONALS:-none}${NC}"

# Check node/npm for webdash
if ! command -v node &> /dev/null || ! command -v npm &> /dev/null; then
    echo -e "${YELLOW}⚠ Node.js/npm not found — web dashboard won't work (CLI still works).${NC}"
    echo "  Install: https://nodejs.org/ or: sudo apt install nodejs npm"
fi
echo

# ============ STEP 0: MYSTERIUM NODE DETECTION ============
echo "Detecting Mysterium node..."
if [ -f "$TOOLKIT_DIR/scripts/node_install_guide.py" ]; then
    if ! $PYTHON_CMD "$TOOLKIT_DIR/scripts/node_install_guide.py"; then
        echo
        echo -e "${YELLOW}⚠ No local Mysterium node detected on this machine.${NC}"
        echo
        echo "  This is expected if you are running the toolkit on a:"
        echo "    • Server / VPS (without a local node)"
        echo "    • Management machine monitoring a remote node"
        echo "    • Second PC pointing at your node machine"
        echo
        echo "  Choose how to continue:"
        echo "    1. Remote mode  — my node runs on ANOTHER machine (enter its IP in the next step)"
        echo "    2. Fleet mode   — I manage multiple remote nodes via nodes.json"
        echo "    3. Install node — install a Mysterium node on THIS machine first"
        echo "    4. Exit"
        echo
        read -p "  Select (1-4): " node_choice
        case "${node_choice:-4}" in
            1)
                echo -e "  ${CYAN}Remote mode — you will enter your node's IP in the setup wizard.${NC}"
                echo
                ;;
            2)
                echo -e "  ${CYAN}Fleet mode — add your nodes to config/nodes.json after setup.${NC}"
                echo
                ;;
            3)
                if [ -f "$TOOLKIT_DIR/scripts/node_installer.py" ]; then
                    $PYTHON_CMD "$TOOLKIT_DIR/scripts/node_installer.py" --install
                else
                    echo -e "  ${RED}✗ node_installer.py not found${NC}"
                    exit 1
                fi
                ;;
            *)
                echo -e "  ${DIM}Exiting. Install a Mysterium node or re-run with remote mode.${NC}"
                echo -e "  ${DIM}Docs: https://docs.mysterium.network/node-runners/${NC}"
                exit 1
                ;;
        esac
    fi
    echo
else
    echo -e "${DIM}  (node_install_guide.py not found — skipping detection)${NC}"
    echo
fi

# ============ STEP 0.5: STOP RUNNING SERVICE IF ACTIVE ============
_TOOLKIT_SVC="mysterium-toolkit"
if systemctl is-active --quiet "$_TOOLKIT_SVC" 2>/dev/null; then
    echo -e "${YELLOW}⚠ Toolkit service is currently running — stopping before install...${NC}"
    $SUDO systemctl stop "$_TOOLKIT_SVC" 2>/dev/null || true
    $SUDO systemctl disable "$_TOOLKIT_SVC" 2>/dev/null || true
    echo -e "  ${GREEN}✓ Service stopped and disabled — will be re-registered at the end${NC}"
    echo
fi

# ============ STEP 1: KILL OLD PROCESSES ============
echo "Step 1: Checking for old processes..."
_pkill_toolkit "python.*backend/app.py"
_pkill_toolkit "vite"
_pkill_toolkit "npm.*start"
sleep 1
echo -e "${GREEN}✓ Old processes cleaned${NC}"
echo

# ============ STEP 2: SCAN FOR PREVIOUS INSTALLATIONS ============
echo "Step 2: Scanning for previous toolkit installations..."
echo
if [ -f "$TOOLKIT_DIR/scripts/env_scanner.py" ]; then
    # Use system python (not venv) since venv may not exist yet
    SCAN_PYTHON=""
    if command -v python3 &> /dev/null; then
        SCAN_PYTHON="python3"
    elif command -v python &> /dev/null; then
        SCAN_PYTHON="python"
    fi

    if [ -n "$SCAN_PYTHON" ]; then
        $SCAN_PYTHON "$TOOLKIT_DIR/scripts/env_scanner.py" --auto || true
        echo
    else
        echo -e "${YELLOW}⚠ Python not available yet — skipping environment scan${NC}"
        echo
    fi
else
    echo -e "${YELLOW}⚠ Scanner script not found — skipping${NC}"
    echo
fi

# ============ STEP 2.5: DATA MIGRATION ============
# Auto-detect previous install and offer to copy tracked data.
echo "Step 2.5: Checking for tracked data from previous installs..."

# Safety: remove any empty DB placeholder that may have shipped in the release zip.
# An empty earnings_history.db blocks migration because migrate_data.py sees the file
# exists and skips the copy — even though it contains no data.
_MIGRATE_PYTHON=""
if command -v python3 &> /dev/null; then _MIGRATE_PYTHON="python3"
elif command -v python &> /dev/null; then _MIGRATE_PYTHON="python"; fi
if [ -n "$_MIGRATE_PYTHON" ]; then
    for _db_file in "config/earnings_history.db" "config/sessions_history.db" "config/traffic_history.db"; do
        _db_path="$TOOLKIT_DIR/$_db_file"
        if [ -f "$_db_path" ]; then
            _row_count=$($_MIGRATE_PYTHON -c "import sqlite3,sys
try:
    c=sqlite3.connect('$_db_path',timeout=5)
    t=[r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    print(sum(c.execute(f'SELECT COUNT(*) FROM {x}').fetchone()[0] for x in t) if t else 0)
    c.close()
except Exception:
    print(-1)" 2>/dev/null || echo "-1")
            if [ "$_row_count" = "0" ]; then
                rm -f "$_db_path"
                echo -e "  ${DIM}Removed empty DB placeholder: $_db_file${NC}"
            fi
        fi
    done
fi

MIGRATE_SCRIPT="$TOOLKIT_DIR/scripts/migrate_data.py"
MIGRATE_PYTHON=""
if command -v python3 &> /dev/null; then MIGRATE_PYTHON="python3"
elif command -v python &> /dev/null; then MIGRATE_PYTHON="python"; fi

if [ -f "$MIGRATE_SCRIPT" ] && [ -n "$MIGRATE_PYTHON" ]; then
    # Run auto-scan and capture whether a previous install was found
    PREV_INSTALL=$($MIGRATE_PYTHON "$MIGRATE_SCRIPT" --scan-only --dest "$TOOLKIT_DIR" 2>/dev/null)

    if [ -n "$PREV_INSTALL" ]; then
        echo
        echo -e "  ${CYAN}Previous install found: ${PREV_INSTALL}${NC}"
        echo -e "  ${DIM}(earnings history, uptime log, node config)${NC}"
        echo
        read -p "  Copy tracked data from previous install? [Y/n]: " migrate_choice
        case "$migrate_choice" in
            [nN]|[nN][oO])
                echo -e "  ${DIM}Skipped.${NC}"
                ;;
            *)
                $MIGRATE_PYTHON "$MIGRATE_SCRIPT" --auto --dest "$TOOLKIT_DIR" || true
                echo -e "  ${GREEN}✓ Data copied.${NC}"
                ;;
        esac
    else
        # No previous install found — but check if data already exists in this install
        DB_FILE="$TOOLKIT_DIR/config/earnings_history.db"
        JSON_FILE="$TOOLKIT_DIR/config/earnings_history.json"
        if [ -f "$DB_FILE" ] || [ -f "$JSON_FILE" ]; then
            SNAP_COUNT=$($MIGRATE_PYTHON "$MIGRATE_SCRIPT" --count-snapshots --dest "$TOOLKIT_DIR" 2>/dev/null || echo "0")
            echo -e "  ${GREEN}✓ Data already present in this install ($SNAP_COUNT snapshots — earnings history intact)${NC}"
        else
            echo -e "${DIM}  No previous install found — starting fresh.${NC}"
        fi
    fi

    # Offer to remove old toolkit installations to reclaim disk space
    OLD_INSTALLS=$($MIGRATE_PYTHON "$MIGRATE_SCRIPT" --list-old --dest "$TOOLKIT_DIR" 2>/dev/null)
    if [ -n "$OLD_INSTALLS" ]; then
        echo
        echo -e "  ${YELLOW}Old toolkit installations found:${NC}"
        echo "$OLD_INSTALLS" | while IFS= read -r line; do
            echo -e "    ${DIM}$line${NC}"
        done
        echo
        read -p "  Remove old installations to reclaim disk space? [y/N]: " cleanup_choice
        case "$cleanup_choice" in
            [yY]|[yY][eE][sS])
                $MIGRATE_PYTHON "$MIGRATE_SCRIPT" --remove-old --dest "$TOOLKIT_DIR" || true
                echo -e "  ${GREEN}✓ Old installations removed.${NC}"
                ;;
            *)
                echo -e "  ${DIM}Skipped — old installs kept.${NC}"
                ;;
        esac
    fi
else
    echo -e "${YELLOW}⚠ Migration script not found — skipping${NC}"
fi
echo

# ============ STEP 3: CHECK EXISTING SETUP ============
if [ -d "venv" ] && [ -f ".env" ]; then
    echo "Step 3: Existing setup detected in current directory."
    echo "Options:"
    echo "  1. Update existing setup (keep config)"
    echo "  2. Fresh install (delete everything)"
    echo "  3. Exit"
    echo
    read -p "Select (1-3): " choice
    
    case $choice in
        1)
            echo "Updating existing setup..."
            source venv/bin/activate
            pip install --upgrade pip > /dev/null 2>&1
            pip install -r requirements.txt
            echo -e "  ${GREEN}✓ Python packages updated${NC}"

            # Rebuild frontend if not Type 3
            if [ "$SETUP_MODE" != "3" ] && command -v npm &>/dev/null && [ -d ".build" ]; then
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
                npm install --legacy-peer-deps > /dev/null 2>&1
                BUILD_OUT=$(npm run build 2>&1)
                if [ -f "dist/index.html" ]; then
                    echo -e "  ${GREEN}✓ Frontend rebuilt → dist/${NC}"
                else
                    echo -e "  ${YELLOW}⚠ Frontend build failed — keeping previous dist/${NC}"
                    echo "$BUILD_OUT" | tail -5
                fi
                rm -rf node_modules
                rm -f vite.config.js postcss.config.js tailwind.config.js package.json package-lock.json index.html
            fi

            echo -e "${GREEN}✓ Update complete${NC}"
            echo
            echo "Step 11.5: Configuring firewall..."
            _apply_firewall_rules
            echo
            echo "Step 12: Opening menu..."
            sleep 1
            "$TOOLKIT_DIR/bin/start.sh"
            exit 0
            ;;
        2)
            echo -e "${YELLOW}Removing old setup...${NC}"
            rm -rf venv node_modules dist/ .env config/setup.json 2>/dev/null || true
            sleep 1
            ;;
        3)
            exit 0
            ;;
    esac
fi

echo

# ============ STEP 4: CHECK REQUIREMENTS ============
echo "Step 4: Checking requirements..."

# System dependencies needed by health tools and monitoring
echo "  Checking system tools..."

# pkg_install is defined above (supports apt/dnf/yum/pacman/apk)
pkg_install "vnstat" "vnstat" "vnstat" "vnstat" "vnstat"

# Install udev rule so myst* tunnel interfaces are automatically registered
# with vnstat the moment Mysterium creates them — even before the toolkit runs.
UDEV_RULE='/etc/udev/rules.d/99-myst-vnstat.rules'
UDEV_CONTENT='ACTION=="add", SUBSYSTEM=="net", KERNEL=="myst*", RUN+="/usr/bin/vnstat --add -i %k"'
if [ -f "$UDEV_RULE" ] && grep -qF "$UDEV_CONTENT" "$UDEV_RULE" 2>/dev/null; then
    echo -e "  ${GREEN}✓ udev rule for myst* vnstat tracking (already installed)${NC}"
else
    if echo "$UDEV_CONTENT" | $SUDO tee "$UDEV_RULE" > /dev/null 2>&1; then
        $SUDO udevadm control --reload-rules 2>/dev/null || true
        echo -e "  ${GREEN}✓ udev rule installed: myst* interfaces auto-registered with vnstat${NC}"
    else
        echo -e "  ${YELLOW}⚠ Could not install udev rule — myst* vnstat tracking via toolkit fallback only${NC}"
    fi
fi

pkg_install "ethtool" "ethtool" "ethtool" "ethtool" "ethtool"
pkg_install "curl" "curl" "curl" "curl" "curl"
pkg_install "ping" "iputils-ping" "iputils" "iputils" "iputils"
pkg_install "sensors" "lm-sensors" "lm_sensors" "lm_sensors" "lm_sensors"
pkg_install "sqlite3" "sqlite3" "sqlite" "sqlite" "sqlite"

# irqbalance is a service, check differently
if command -v irqbalance &> /dev/null || systemctl is-active irqbalance &> /dev/null 2>&1; then
    echo -e "  ${GREEN}✓ irqbalance${NC}"
else
    echo -e "  ${YELLOW}⚠ irqbalance not found — installing...${NC}"
    case "$PKG_MGR" in
        apt)    $SUDO apt-get install -y -qq irqbalance >/dev/null 2>&1 || true ;;
        dnf|yum) $SUDO dnf install -y irqbalance >/dev/null 2>&1 || true ;;
        pacman) $SUDO pacman -S --noconfirm irqbalance >/dev/null 2>&1 || true ;;
        apk)    apk add irqbalance >/dev/null 2>&1 || true ;;
    esac
    command -v irqbalance >/dev/null 2>&1 && echo -e "  ${GREEN}✓ irqbalance installed${NC}" || echo -e "  ${YELLOW}⚠ irqbalance install failed (non-fatal)${NC}"
fi

# conntrack
if command -v conntrack &> /dev/null; then
    echo -e "  ${GREEN}✓ conntrack${NC}"
else
    echo -e "  ${YELLOW}⚠ conntrack not found — installing...${NC}"
    case "$PKG_MGR" in
        apt)    $SUDO apt-get install -y -qq conntrack >/dev/null 2>&1 || true ;;
        dnf|yum) $SUDO dnf install -y conntrack-tools >/dev/null 2>&1 || true ;;
        pacman) $SUDO pacman -S --noconfirm conntrack-tools >/dev/null 2>&1 || true ;;
        apk)    apk add conntrack-tools >/dev/null 2>&1 || true ;;
    esac
    command -v conntrack >/dev/null 2>&1 && echo -e "  ${GREEN}✓ conntrack installed${NC}" || echo -e "  ${YELLOW}⚠ conntrack install failed (non-fatal)${NC}"
fi

echo ""

# Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}✗ Python 3 required${NC}"
    exit 1
fi
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
echo -e "${GREEN}✓ Python: $PYTHON_VERSION${NC}"

if ! command -v node &> /dev/null; then
    echo -e "${YELLOW}Installing Node.js...${NC}"
    case "$PKG_MGR" in
        apt)
            # Use NodeSource for Node.js 20 — plain apt gives outdated versions on
            # Ubuntu, Raspberry Pi OS, and other Debian-based distros (arm64 included).
            _NODE_INSTALLED=false
            if command -v curl &>/dev/null; then
                echo -e "  ${DIM}Fetching NodeSource setup script (Node.js 20)...${NC}"
                if curl -fsSL https://deb.nodesource.com/setup_20.x | $SUDO bash - >/dev/null 2>&1; then
                    $SUDO apt-get install -y -qq nodejs >/dev/null 2>&1 && _NODE_INSTALLED=true || true
                fi
            fi
            # Fallback to plain apt if NodeSource failed
            if [ "$_NODE_INSTALLED" = "false" ]; then
                echo -e "  ${YELLOW}⚠ NodeSource failed — falling back to apt (may give older version)${NC}"
                $SUDO apt-get update -qq >/dev/null 2>&1
                $SUDO apt-get install -y -qq nodejs npm >/dev/null 2>&1 || true
            fi
            ;;
        dnf|yum) $SUDO dnf install -y nodejs npm >/dev/null 2>&1 || true ;;
        pacman) $SUDO pacman -S --noconfirm nodejs npm >/dev/null 2>&1 || true ;;
        apk)    apk add nodejs npm >/dev/null 2>&1 || true ;;
    esac
fi
if command -v node &>/dev/null; then
    echo -e "${GREEN}✓ Node.js: $(node --version)${NC}"
else
    echo -e "${YELLOW}⚠ Node.js not found — web dashboard unavailable (CLI still works).${NC}"
    echo -e "  Install manually: ${YELLOW}apt install nodejs npm${NC}  then re-run setup."
fi
echo

# ============ STEP 5: CREATE VENV ============
echo "Step 5: Creating virtual environment..."
# Ensure python3-venv is available before attempting venv creation.
# On Debian/Ubuntu the package is version-specific (python3.11-venv etc.).
if ! python3 -m venv --help >/dev/null 2>&1; then
    PY_MINOR_VER=$(python3 -c "import sys; print(sys.version_info.minor)" 2>/dev/null || echo "")
    if [ -n "$PY_MINOR_VER" ] && command -v apt-get &>/dev/null; then
        echo -e "  ${YELLOW}⚠ python3-venv not available — installing python3.${PY_MINOR_VER}-venv...${NC}"
        $SUDO apt-get install -y "python3.${PY_MINOR_VER}-venv" python3-venv 2>/dev/null || \
        $SUDO apt-get install -y python3-venv 2>/dev/null || true
    fi
fi
if python3 -m venv "$TOOLKIT_DIR/venv"; then
    echo -e "${GREEN}✓ Venv created${NC}"
else
    PY_MINOR_VER=$(python3 -c "import sys; print(sys.version_info.minor)" 2>/dev/null || echo "x")
    echo -e "${RED}✗ Venv creation failed.${NC}"
    echo -e "  Run: ${YELLOW}apt install python3.${PY_MINOR_VER}-venv${NC}  then re-run setup."
    exit 1
fi
echo

# ============ STEP 6: INSTALL PYTHON PACKAGES ============
echo "Step 6: Installing Python packages..."
VENV_PIP="$TOOLKIT_DIR/venv/bin/pip"
VENV_PYTHON="$TOOLKIT_DIR/venv/bin/python"
if [ ! -f "$VENV_PIP" ]; then
    echo -e "  ${YELLOW}⚠ venv pip not found — recreating venv${NC}"
    rm -rf "$TOOLKIT_DIR/venv"
    python3 -m venv "$TOOLKIT_DIR/venv"
fi
"$VENV_PIP" install --upgrade pip setuptools wheel > /dev/null 2>&1
if "$VENV_PIP" install -r requirements.txt; then
    echo -e "${GREEN}✓ Python packages installed${NC}"
else
    echo -e "${RED}✗ pip install failed — check internet connection and try again${NC}"
    exit 1
fi
echo

# ============ STEP 7: INSTALL FRONTEND ============
echo "Step 7: Building frontend for production..."
mkdir -p logs config
# Fix ownership so the real user (not root) can write to logs/ and config/
# This prevents DB files from becoming root-owned when setup runs as sudo
_SETUP_REAL_USER="${SUDO_USER:-$USER}"
if [ "$_SETUP_REAL_USER" != "root" ]; then
    chown -R "$_SETUP_REAL_USER:$_SETUP_REAL_USER" logs/ 2>/dev/null || true
    chown -R "$_SETUP_REAL_USER:$_SETUP_REAL_USER" config/ 2>/dev/null || true
fi

# Modus 3: lightweight backend — no frontend needed
if [ "$SETUP_MODE" = "3" ]; then
    echo -e "  ${DIM}Lightweight mode — skipping frontend build (backend-only install)${NC}"
    echo -e "  ${DIM}The /peer/data endpoint will be available for fleet masters to read.${NC}"
    echo
else

# Copy build config files from .build/ to root (needed by npm/vite)
if [ -d ".build" ]; then
    cp .build/package.json .build/vite.config.js .build/postcss.config.js .build/tailwind.config.js . 2>/dev/null || true
    # Use the correct index.html that points to frontend/main.jsx
    cat > index.html << 'HTMLEOF'
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>Mysterium Dashboard</title></head>
<body><div id="root"></div><script type="module" src="/frontend/main.jsx"></script></body>
</html>
HTMLEOF
fi

# Install packages needed for the build
echo -e "  Installing npm packages..."
if ! npm install --legacy-peer-deps > /tmp/npm_install_$$.log 2>&1; then
    echo -e "  ${RED}✗ npm install failed. Build log:${NC}"
    cat /tmp/npm_install_$$.log | tail -20
    rm -f /tmp/npm_install_$$.log
    exit 1
fi
rm -f /tmp/npm_install_$$.log
echo -e "  ${GREEN}✓ npm packages installed${NC}"

# Remove any stale dist/ only — node_modules must stay for the build
rm -rf dist/ 2>/dev/null || true

echo -e "  Building React app..."
BUILD_LOG=$(npm run build 2>&1)
BUILD_EXIT=$?

# Primary check: did vite produce dist/index.html?
# vite can exit non-zero on warnings but still produce a valid build.
# We treat a present dist/index.html as success regardless of exit code,
# but show warnings if exit code was non-zero.
if [ -f "dist/index.html" ]; then
    if [ $BUILD_EXIT -ne 0 ]; then
        echo -e "  ${YELLOW}⚠ Build completed with warnings (exit $BUILD_EXIT) — dist/ looks valid, continuing.${NC}"
        echo "$BUILD_LOG" | grep -iE "error|warn" | head -10 || true
    else
        echo -e "  ${GREEN}✓ Frontend built → dist/${NC}"
    fi
else
    echo -e "  ${RED}✗ Frontend build failed — dist/index.html not produced. Full build log:${NC}"
    echo "$BUILD_LOG"
    echo
    echo -e "  ${RED}Setup cannot continue without a working frontend build.${NC}"
    echo -e "  ${YELLOW}Common causes:${NC}"
    echo -e "  ${DIM}  • Node.js version too old (need 16+): node --version${NC}"
    echo -e "  ${DIM}  • Missing system dependency: check errors above${NC}"
    echo -e "  ${DIM}  • Syntax error in Dashboard.jsx: check the build output${NC}"
    echo
    rm -rf node_modules
    rm -f vite.config.js postcss.config.js tailwind.config.js
    rm -f package.json package-lock.json index.html
    exit 1
fi

# Clean up build tools (node_modules etc. not needed at runtime)
echo -e "  Cleaning up build tools (node_modules, vite config)..."
rm -rf node_modules
rm -f vite.config.js postcss.config.js tailwind.config.js
rm -f package.json package-lock.json package-lock.json.bak
rm -f index.html
echo -e "  ${GREEN}✓ Build tools removed — dist/ is all Flask needs${NC}"
echo -e "  ${DIM}  Freed: ~88MB node_modules${NC}"
echo -e "  ${GREEN}✓ Frontend ready${NC}"
echo
fi  # end modus 1/2 frontend build block

# ============ STEP 7.5: DETECT EXISTING CONFIGURATION ============
_SKIP_WIZARD=false
if [ -f "$TOOLKIT_DIR/config/setup.json" ]; then
    _CFG_VALID=$("$TOOLKIT_DIR/venv/bin/python" - << 'PYEOF'
import json, pathlib, sys
cfg = pathlib.Path('config/setup.json')
try:
    d = json.loads(cfg.read_text())
    ok = bool(d.get('node_host') and (d.get('dashboard_api_key') or d.get('dashboard_username') or d.get('dashboard_password')))
    print('yes' if ok else 'no')
except Exception:
    print('no')
PYEOF
    )
    if [ "$_CFG_VALID" = "yes" ]; then
        echo
        echo -e "  ${CYAN}Existing configuration found in config/setup.json${NC}"
        read -p "  Keep existing configuration and skip setup wizard? [Y/n]: " _keep_cfg
        case "${_keep_cfg:-Y}" in
            [nN]|[nN][oO])
                echo -e "  ${DIM}Running fresh setup wizard...${NC}"
                ;;
            *)
                echo -e "  Reconstructing .env from existing configuration..."
                "$TOOLKIT_DIR/venv/bin/python" - << 'PYEOF'
import json, pathlib
cfg = pathlib.Path('config/setup.json')
d = json.loads(cfg.read_text())
auth = d.get('dashboard_auth_method', '')
env = (
    "# Mysterium Node API Configuration\n"
    f"MYSTERIUM_NODE_API=http://{d.get('node_host','localhost')}:{d.get('node_port',4050)}\n"
    f"MYSTERIUM_NODE_USERNAME={d.get('node_username','')}\n"
    f"MYSTERIUM_NODE_PASSWORD={d.get('node_password','')}\n\n"
    f"# Dashboard API Server\n"
    f"DASHBOARD_PORT={d.get('dashboard_port',5000)}\n\n"
    f"# Dashboard Authentication\n"
)
if auth == 'apikey':
    env += f"DASHBOARD_API_KEY={d.get('dashboard_api_key','')}\n"
elif auth == 'userpass':
    env += f"DASHBOARD_USERNAME={d.get('dashboard_username','admin')}\nDASHBOARD_PASSWORD={d.get('dashboard_password','')}\n"
else:
    env += "ALLOW_NO_AUTH=true\n"
env += f"\n# Monitoring Configuration\nDEBUG={'true' if d.get('debug') else 'false'}\nLOG_LEVEL={d.get('log_level','INFO')}\n"
pathlib.Path('.env').write_text(env)
print('  .env reconstructed')
PYEOF
                echo -e "  ${GREEN}✓ Configuration kept — setup wizard skipped${NC}"
                echo
                _SKIP_WIZARD=true
                ;;
        esac
        echo
    fi
fi

# ============ STEP 8: RUN SETUP WIZARD ============
if [ "$_SKIP_WIZARD" = "false" ]; then
echo "Step 8: Running setup wizard..."
echo
TOOLKIT_SETUP_MODE=$SETUP_MODE "$TOOLKIT_DIR/venv/bin/python" scripts/setup_wizard.py
if [ $? -ne 0 ]; then
    echo -e "${RED}✗ Setup wizard failed${NC}"
    exit 1
fi
echo
echo -e "${GREEN}✓ Setup complete!${NC}"
echo
echo -e "${DIM}Tip: the CLI dashboard adapts to your terminal width.${NC}"
echo -e "${DIM}     At 120+ columns it shows full consumer IDs — resize your${NC}"
echo -e "${DIM}     terminal window before launching for the best experience.${NC}"
echo
fi  # end _SKIP_WIZARD

# ============ STEP 8.5: FLEET MASTER CONFIGURATION (modus 2 only) ============
if [ "$SETUP_MODE" = "2" ]; then
    echo "Step 8.5: Fleet master configuration..."
    echo
    echo -e "  ${CYAN}${BOLD}Fleet mode lets you monitor multiple nodes from this dashboard.${NC}"
    echo -e "  ${DIM}  Each node needs its own toolkit backend running.${NC}"
    echo -e "  ${DIM}  This machine will read data from each node via /peer/data.${NC}"
    echo
    NODES_JSON="$TOOLKIT_DIR/config/nodes.json"
    if [ -f "$NODES_JSON" ]; then
        echo -e "  ${GREEN}✓ nodes.json already exists — keeping existing config${NC}"
        echo -e "  ${DIM}  Edit $NODES_JSON to add or remove nodes.${NC}"
    else
        echo -e "  ${YELLOW}No nodes.json found. Create one now?${NC}"
        echo
        echo "  Each node entry needs:"
        echo -e "  ${DIM}  id          — unique name (no spaces), e.g. vps-de${NC}"
        echo -e "  ${DIM}  label       — display name, e.g. VPS Germany${NC}"
        echo -e "  ${DIM}  url         — TequilAPI address, e.g. http://host:4050${NC}"
        echo -e "  ${DIM}  toolkit_url — toolkit backend, e.g. http://host:5000${NC}"
        echo -e "  ${DIM}  toolkit_api_key — dashboard_api_key from that node's setup.json${NC}"
        echo
        read -p "  Create a nodes.json template now? [Y/n]: " fleet_create
        case "${fleet_create:-Y}" in
            [nN]|[nN][oO])
                echo -e "  ${DIM}Skipped. Create config/nodes.json manually before starting.${NC}"
                ;;
            *)
                mkdir -p "$TOOLKIT_DIR/config"
                cat > "$NODES_JSON" << 'NODES_EOF'
{
  "nodes": [
    {
      "id": "node1",
      "label": "My First Node",
      "url": "http://REPLACE_WITH_NODE_IP:4050",
      "toolkit_url": "http://REPLACE_WITH_NODE_IP:5000",
      "toolkit_api_key": "REPLACE_WITH_DASHBOARD_API_KEY"
    },
    {
      "id": "node2",
      "label": "My Second Node",
      "url": "http://REPLACE_WITH_NODE_IP:4050",
      "toolkit_url": "http://REPLACE_WITH_NODE_IP:5000",
      "toolkit_api_key": "REPLACE_WITH_DASHBOARD_API_KEY"
    }
  ]
}
NODES_EOF
                echo -e "  ${GREEN}✓ Template created: config/nodes.json${NC}"
                echo -e "  ${YELLOW}  → Edit this file and replace REPLACE_WITH_* values before starting.${NC}"
                echo -e "  ${DIM}  Find the api key in each node's config/setup.json${NC}"
                ;;
        esac
    fi
    echo
fi

# ============ STEP 11: APPLY & PERSIST KERNEL TUNING ============
# Only relevant when the Mysterium node runs ON THIS machine (local mode).
# Skip automatically for remote/server deployments where the node is elsewhere.
TOOLKIT_MODE=$(python3 -c "
import json, pathlib
cfg = pathlib.Path('config/setup.json')
if cfg.exists():
    d = json.loads(cfg.read_text())
    print(d.get('toolkit_mode', 'local'))
else:
    print('local')
" 2>/dev/null || echo "local")

if [ "$TOOLKIT_MODE" = "remote" ]; then
    echo "Step 11: Kernel tuning — skipped (remote mode, node is not on this machine)."
    echo -e "  ${DIM}Kernel optimisations are for the machine running the node itself.${NC}"
    echo -e "  ${DIM}Run setup on your node machine to apply them there.${NC}"
    echo ""
else

# ── Check sudo capability before asking ──────────────────────────────────────
HAVE_SUDO=false
if [ "$(id -u)" = "0" ]; then
    # Already root — no sudo needed
    HAVE_SUDO=true
elif sudo -n true 2>/dev/null; then
    # Passwordless sudo available (NOPASSWD in sudoers or SSH agent)
    HAVE_SUDO=true
fi

if [ "$HAVE_SUDO" = "false" ]; then
    echo "Step 11: Kernel tuning — skipped."
    echo ""
    echo -e "  ${YELLOW}⚠ Sudo requires a password on this machine.${NC}"
    echo -e "  ${DIM}Kernel optimisations need root. To apply them later, run:${NC}"
    echo -e "  ${DIM}  sudo python3 scripts/system_health.py --health-fix --health-persist${NC}"
    echo -e "  ${DIM}Or open the System Health panel in the dashboard and click 'Fix All'.${NC}"
    echo ""
elif [ "$SETUP_MODE" = "3" ]; then
    echo "Step 11: Skipping kernel tuning (lightweight backend mode)..."
    echo -e "  ${DIM}Kernel optimisations are for node machines only. Skipped.${NC}"
    echo
else
echo "Step 11: Applying system optimisations for Mysterium node..."
echo ""

# Detect if we are on a VPS/VM — skip bare-metal-only tweaks
IS_VIRTUAL=false
if systemd-detect-virt --quiet 2>/dev/null; then
    IS_VIRTUAL=true
    VIRT_TYPE=$(systemd-detect-virt 2>/dev/null || echo "vm")
    echo -e "  ${CYAN}ℹ Virtual machine detected ($VIRT_TYPE)${NC}"
    echo -e "  ${DIM}  CPU governor and IRQ tuning will be skipped (not applicable on VPS).${NC}"
    echo -e "  ${DIM}  Network tuning (BBR, buffers, ip_forward) will still be applied.${NC}"
elif grep -qE "^flags.*hypervisor" /proc/cpuinfo 2>/dev/null; then
    IS_VIRTUAL=true
    echo -e "  ${CYAN}ℹ Virtual machine detected (hypervisor flag)${NC}"
    echo -e "  ${DIM}  Applying VPS-compatible optimisations only.${NC}"
fi
echo ""
echo "  This applies and persists kernel network tuning, BBR congestion"
echo "  control, and NIC settings so they survive reboot."
echo ""
read -p "  Apply and persist all system optimisations? [Y/n]: " -r OPT_REPLY
OPT_REPLY="${OPT_REPLY:-Y}"
if [[ "$OPT_REPLY" =~ ^[Yy]$ ]]; then
    echo ""
    HEALTH_FLAGS="--health-fix --health-persist"
    [ "$IS_VIRTUAL" = "true" ] && HEALTH_FLAGS="$HEALTH_FLAGS --vps-mode"
    if python3 scripts/system_health.py $HEALTH_FLAGS 2>/dev/null; then
        echo -e "  ${GREEN}✓ System optimisations applied and persisted${NC}"
    else
        # Fallback: apply only VPS-safe network tuning directly
        echo -e "  ${YELLOW}⚠ Auto-optimisation had issues — applying network fixes manually...${NC}"

        # 1. Kernel network tuning (sysctl)
        $SUDO sysctl -w net.ipv4.ip_forward=1 >/dev/null 2>&1 || true
        $SUDO sysctl -w net.core.rmem_max=134217728 >/dev/null 2>&1 || true
        $SUDO sysctl -w net.core.wmem_max=134217728 >/dev/null 2>&1 || true
        $SUDO sysctl -w net.ipv4.tcp_congestion_control=bbr >/dev/null 2>&1 || true
        $SUDO sysctl -w net.core.default_qdisc=fq >/dev/null 2>&1 || true

        # Persist sysctl settings
        $SUDO mkdir -p /etc/sysctl.d
        cat << 'SYSCTL_EOF' | $SUDO tee /etc/sysctl.d/99-mysterium-node.conf >/dev/null
# Mysterium Node Toolkit — network tuning (persisted at setup)
net.ipv4.ip_forward = 1
net.core.rmem_max = 134217728
net.core.wmem_max = 134217728
net.ipv4.tcp_rmem = 4096 87380 134217728
net.ipv4.tcp_wmem = 4096 65536 134217728
net.ipv4.tcp_congestion_control = bbr
net.core.default_qdisc = fq
net.netfilter.nf_conntrack_max = 524288
vm.swappiness = 60
SYSCTL_EOF
        echo -e "  ${GREEN}✓ sysctl settings persisted to /etc/sysctl.d/99-mysterium-node.conf${NC}"

        # 2. BBR module
        echo tcp_bbr | $SUDO tee /etc/modules-load.d/tcp_bbr.conf >/dev/null 2>&1 || true
        $SUDO modprobe tcp_bbr 2>/dev/null || true

        # 3. CPU performance governor — skip on VPS (no cpufreq available)
        if [ "$IS_VIRTUAL" != "true" ]; then
        CPU_COUNT=$(nproc 2>/dev/null || echo 4)
        cat << 'GOV_SCRIPT_EOF' | $SUDO tee /usr/local/bin/mysterium-cpu-governor.sh >/dev/null
#!/bin/bash
# Mysterium Node Toolkit — CPU performance governor (runs at boot)
for g in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
    echo performance > "$g" 2>/dev/null
done
GOV_SCRIPT_EOF
        $SUDO chmod +x /usr/local/bin/mysterium-cpu-governor.sh

        cat << 'GOV_SVC_EOF' | $SUDO tee /etc/systemd/system/mysterium-cpu-governor.service >/dev/null
[Unit]
Description=Mysterium CPU Performance Governor
After=multi-user.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/mysterium-cpu-governor.sh
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
GOV_SVC_EOF
        $SUDO systemctl daemon-reload
        $SUDO systemctl enable --now mysterium-cpu-governor 2>/dev/null || true
        echo -e "  ${GREEN}✓ CPU governor service created and enabled${NC}"

        # Apply governor live now
        for g in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
            echo performance | $SUDO tee "$g" >/dev/null 2>/dev/null || true
        done
        else
            echo -e "  ${DIM}  CPU governor skipped (VPS — not applicable)${NC}"
        fi
    fi
    echo ""
else
    echo -e "  ${YELLOW}⚠ Skipped — run System Health panel in the dashboard to apply later${NC}"
    echo ""
fi
fi  # end HAVE_SUDO check
fi  # end toolkit_mode=local check

# ── vnstat: extend day retention to 3 years (1095 days) ──────────────
if command -v vnstat &>/dev/null; then
    VNSTAT_CONF="/etc/vnstat.conf"
    if [ -f "$VNSTAT_CONF" ]; then
        if grep -q "DayEntries" "$VNSTAT_CONF"; then
            $SUDO sed -i 's/DayEntries.*/DayEntries 1095/' "$VNSTAT_CONF" 2>/dev/null &&                 echo -e "  ${GREEN}✓ vnstat: DayEntries set to 1095 (3 years)${NC}" || true
        else
            echo "DayEntries 1095" | $SUDO tee -a "$VNSTAT_CONF" >/dev/null 2>&1 &&                 echo -e "  ${GREEN}✓ vnstat: DayEntries 1095 added${NC}" || true
        fi
        # Also set MonthEntries to 36 (3 years of monthly totals — default is already unlimited but be explicit)
        if grep -q "MonthEntries" "$VNSTAT_CONF"; then
            $SUDO sed -i 's/MonthEntries.*/MonthEntries 36/' "$VNSTAT_CONF" 2>/dev/null || true
        fi
        $SUDO systemctl restart vnstat 2>/dev/null || $SUDO service vnstat restart 2>/dev/null || true
    else
        echo -e "  ${DIM}vnstat.conf not found — skipping day retention config${NC}"
    fi
fi


_apply_firewall_rules() {
# ── Apply rules ────────────────────────────────────────────────────────────
# Detect firewall, enable ufw if inactive
_FW_TYPE=$(_detect_firewall)
echo -e "  ${DIM}Firewall: ${_FW_TYPE}${NC}"
if [ "$_FW_TYPE" = "ufw" ]; then
    _ufw_state=$(_sudo ufw status 2>/dev/null || echo "")
    if echo "$_ufw_state" | grep -qi "inactive"; then
        _sudo ufw --force enable &>/dev/null 2>&1 && \
            echo -e "  ${GREEN}✓ ufw enabled${NC}" || \
            echo -e "  ${YELLOW}⚠ ufw enable failed${NC}"
        _UFW_STATUS_CACHE=""
    fi
fi

# Always open toolkit dashboard port
_open_port "${DASHBOARD_PORT:-5000}" tcp "Toolkit dashboard"

# Open Mysterium node ports if node is local
TOOLKIT_MODE=$(python3 -c "
import json, pathlib
cfg = pathlib.Path('config/setup.json')
if cfg.exists():
    d = json.loads(cfg.read_text())
    print(d.get('toolkit_mode', 'local'))
else:
    print('local')
" 2>/dev/null || echo "local")

if [ "$TOOLKIT_MODE" = "local" ]; then
    _open_port 4449 tcp  "TequilAPI / Node UI"
    _open_port 1194 udp  "OpenVPN UDP"
    _open_port 1194 tcp  "OpenVPN TCP"
    _open_port 51820 udp "WireGuard"
    _open_range 10000 65000 udp  # P2P / NAT hole punching
    echo -e "  ${GREEN}✓ Mysterium node ports configured (4449, 1194, 51820, 10000-65000/udp)${NC}"
fi

# Persist iptables rules if that's what we used
case "$_FW_TYPE" in
    iptables*) _ipt_persist ;;
    firewalld) _firewalld_reload ;;
esac

echo -e "  ${DIM}Node UI accessible at: http://$(python3 -c "import socket; s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.connect(('8.8.8.8',80)); print(s.getsockname()[0]); s.close()" 2>/dev/null || echo "YOUR_IP"):4449/ui${NC}"
echo
    echo -e "  ${DIM}─────────────────────────────────────────────${NC}"
    echo -e "  ${GREEN}Firewall configuration done. Press Enter to continue...${NC}"
    read -r _fw_confirm
}

# ============ STEP 11.5: OPEN REQUIRED FIREWALL PORTS ============
if [ "$SETUP_MODE" = "3" ]; then
    echo "Step 11.5: Skipping firewall configuration (lightweight backend mode)..."
    echo -e "  ${DIM}Firewall rules are managed by the node machine itself. Skipped.${NC}"
    echo
else
echo "Step 11.5: Configuring firewall..."

# ── Firewall detection ─────────────────────────────────────────────────────
# Ensure sbin directories are in PATH (sudo bash may strip them)
export PATH="/usr/sbin:/sbin:/usr/bin:/bin:$PATH"
# Priority: firewalld → ufw → nftables → iptables → iptables-legacy → warn
_detect_firewall() {
    # Ensure sbin in PATH — sudo bash may strip it
    export PATH="/usr/sbin:/sbin:/usr/bin:/bin:$PATH"

    # Detection based on ACTIVE rules, not binary presence.
    # A binary being installed does not mean it is the active firewall.

    # 1. firewalld: only if the service is actually running
    if command -v firewall-cmd &>/dev/null; then
        if systemctl is-active --quiet firewalld 2>/dev/null; then
            echo "firewalld"; return
        fi
    fi

    # 2. iptables with actual rules — check first before nftables
    #    On Parrot/Debian: nft binary exists but iptables may be the active manager
    #    Key signal: iptables -L INPUT has more than the default 2 lines (policy + header)
    if command -v iptables &>/dev/null; then
        local ipt_rules_count
        ipt_rules_count=$(iptables -L INPUT -n 2>/dev/null | grep -c "^ACCEPT\|^DROP\|^REJECT" || echo "0")
        if [ "$ipt_rules_count" -gt 0 ] 2>/dev/null; then
            local ipt_ver
            ipt_ver=$(iptables --version 2>/dev/null || echo "")
            if echo "$ipt_ver" | grep -q "nf_tables"; then
                echo "iptables-nft"; return
            fi
            echo "iptables"; return
        fi
    fi

    # 3. ufw: only if explicitly active
    if command -v ufw &>/dev/null; then
        local ufw_out
        ufw_out=$(ufw status 2>/dev/null || $SUDO -n ufw status 2>/dev/null || echo "")
        if echo "$ufw_out" | grep -qi "^Status: active"; then
            echo "ufw"; return
        fi
    fi

    # 4. nftables: only if it has actual tables/rules configured
    if command -v nft &>/dev/null; then
        local nft_out
        nft_out=$(nft list ruleset 2>/dev/null || $SUDO -n nft list ruleset 2>/dev/null || echo "")
        if echo "$nft_out" | grep -q "table"; then
            echo "nftables"; return
        fi
    fi

    # 5. Fallback: iptables exists but has no rules yet — still use it
    if command -v iptables-legacy &>/dev/null; then
        echo "iptables-legacy"; return
    fi
    if command -v iptables &>/dev/null; then
        local ipt_ver
        ipt_ver=$(iptables --version 2>/dev/null || echo "")
        if echo "$ipt_ver" | grep -q "nf_tables"; then
            echo "iptables-nft"; return
        fi
        echo "iptables"; return
    fi

    # 6. ufw inactive fallback — enable it
    if command -v ufw &>/dev/null; then
        echo "ufw"; return
    fi

    echo "none"
}

# ── UFW helpers ────────────────────────────────────────────────────────────
# Cache ufw status to avoid multiple calls
_UFW_STATUS_CACHE=""
_ufw_status() {
    if [ -z "$_UFW_STATUS_CACHE" ]; then
        _UFW_STATUS_CACHE=$(_sudo ufw status verbose 2>/dev/null || _sudo ufw status 2>/dev/null || echo "")
    fi
    echo "$_UFW_STATUS_CACHE"
}

_ufw_rule_exists() {
    local port=$1 proto=$2
    # Check multiple formats: port/proto, port (any), port/proto ALLOW
    _ufw_status | grep -qiE "^${port}/${proto}|^${port} |ALLOW.*${port}/${proto}|ALLOW.*${port} " 2>/dev/null
}

_ufw_open() {
    local port=$1 proto=${2:-tcp} label=${3:-}
    if _ufw_rule_exists "$port" "$proto"; then
        echo -e "  ${DIM}· ufw: ${port}/${proto} already allowed${NC}"
        return 0
    fi
    if _sudo ufw allow "${port}/${proto}" &>/dev/null 2>&1; then
        _UFW_STATUS_CACHE=""  # Invalidate cache after change
        echo -e "  ${GREEN}✓ ufw: ${port}/${proto} opened${label:+ ($label)}${NC}"
    else
        echo -e "  ${YELLOW}⚠ ufw: ${port}/${proto} failed — run manually: sudo ufw allow ${port}/${proto}${NC}"
    fi
}

_ufw_open_range() {
    local start=$1 end=$2 proto=${3:-udp}
    if _ufw_status | grep -qE "${start}:${end}/${proto}|${start}-${end}/${proto}" 2>/dev/null; then
        echo -e "  ${DIM}· ufw: ${start}:${end}/${proto} already allowed${NC}"
        return 0
    fi
    if _sudo ufw allow "${start}:${end}/${proto}" &>/dev/null 2>&1; then
        _UFW_STATUS_CACHE=""
        echo -e "  ${GREEN}✓ ufw: ${start}:${end}/${proto} opened${NC}"
    else
        echo -e "  ${YELLOW}⚠ ufw: range ${start}:${end}/${proto} failed${NC}"
    fi
}

# ── firewalld helpers ──────────────────────────────────────────────────────
_firewalld_open() {
    local port=$1 proto=${2:-tcp} label=${3:-}
    local zone
    zone=$(_sudo firewall-cmd --get-default-zone 2>/dev/null || echo "public")
    # Check if already open (permanent) in active zone
    if _sudo firewall-cmd --permanent --zone="$zone" --query-port="${port}/${proto}" &>/dev/null 2>&1; then
        echo -e "  ${DIM}· firewalld: ${port}/${proto} already open in zone ${zone}${NC}"
        return 0
    fi
    # Add permanently and to runtime
    if _sudo firewall-cmd --permanent --zone="$zone" --add-port="${port}/${proto}" &>/dev/null 2>&1 && \
       _sudo firewall-cmd --zone="$zone" --add-port="${port}/${proto}" &>/dev/null 2>&1; then
        echo -e "  ${GREEN}✓ firewalld (${zone}): ${port}/${proto} opened${label:+ ($label)}${NC}"
    else
        echo -e "  ${YELLOW}⚠ firewalld: ${port}/${proto} failed — run: sudo firewall-cmd --permanent --zone=${zone} --add-port=${port}/${proto}${NC}"
    fi
}

_firewalld_open_range() {
    local start=$1 end=$2 proto=${3:-udp}
    if _sudo firewall-cmd --permanent --query-port="${start}-${end}/${proto}" &>/dev/null 2>&1; then
        echo -e "  ${DIM}· firewalld: ${start}-${end}/${proto} already open${NC}"
        return 0
    fi
    if _sudo firewall-cmd --permanent --add-port="${start}-${end}/${proto}" &>/dev/null 2>&1 && \
       _sudo firewall-cmd --add-port="${start}-${end}/${proto}" &>/dev/null 2>&1; then
        echo -e "  ${GREEN}✓ firewalld: ${start}-${end}/${proto} opened${NC}"
    else
        echo -e "  ${YELLOW}⚠ firewalld: range failed — run: sudo firewall-cmd --permanent --add-port=${start}-${end}/${proto}${NC}"
    fi
}

_firewalld_reload() {
    _sudo firewall-cmd --reload &>/dev/null 2>&1 || true
}

# ── iptables helpers (works for iptables, iptables-nft, iptables-legacy) ──
_ipt_bin=""
_ipt_detect_bin() {
    if [ -n "$_ipt_bin" ]; then return; fi
    # Ensure sbin is in PATH — sudo bash may not inherit full PATH
    export PATH="/usr/sbin:/sbin:/usr/bin:/bin:$PATH"
    # Prefer iptables-legacy if explicitly available, otherwise use iptables
    for _candidate in iptables-legacy /usr/sbin/iptables-legacy /sbin/iptables-legacy; do
        if command -v "$_candidate" &>/dev/null 2>&1; then
            _ipt_bin="$_candidate"; return
        fi
    done
    for _candidate in iptables /usr/sbin/iptables /sbin/iptables; do
        if command -v "$_candidate" &>/dev/null 2>&1; then
            _ipt_bin="$_candidate"; return
        fi
    done
    _ipt_bin=""
}

# Cache iptables ruleset to avoid repeated calls
_IPT_RULES_CACHE=""
_ipt_rules() {
    if [ -z "$_IPT_RULES_CACHE" ]; then
        _IPT_RULES_CACHE=$(_sudo "$_ipt_bin" -L INPUT -n 2>/dev/null || echo "")
    fi
    echo "$_IPT_RULES_CACHE"
}

_ipt_open() {
    local port=$1 proto=${2:-tcp} label=${3:-}
    _ipt_detect_bin
    [ -z "$_ipt_bin" ] && return 1
    # First check cached ruleset, then use -C for exact match
    if _ipt_rules | grep -qE "ACCEPT.*${proto}.*dpt:${port}([^0-9]|$)" 2>/dev/null; then
        echo -e "  ${DIM}· iptables: ${port}/${proto} already open${NC}"
        return 0
    fi
    if _sudo "$_ipt_bin" -C INPUT -p "$proto" --dport "$port" -j ACCEPT &>/dev/null 2>&1; then
        echo -e "  ${DIM}· iptables: ${port}/${proto} already open${NC}"
        return 0
    fi
    if _sudo "$_ipt_bin" -A INPUT -p "$proto" --dport "$port" -j ACCEPT &>/dev/null 2>&1; then
        _IPT_RULES_CACHE=""  # Invalidate cache
        echo -e "  ${GREEN}✓ iptables: ${port}/${proto} opened${label:+ ($label)}${NC}"
    else
        echo -e "  ${YELLOW}⚠ iptables: ${port}/${proto} failed — run: sudo iptables -A INPUT -p ${proto} --dport ${port} -j ACCEPT${NC}"
    fi
}

_ipt_open_range() {
    local start=$1 end=$2 proto=${3:-udp}
    _ipt_detect_bin
    [ -z "$_ipt_bin" ] && return 1
    if _ipt_rules | grep -qE "ACCEPT.*${proto}.*dpts:${start}:" 2>/dev/null; then
        echo -e "  ${DIM}· iptables: ${start}:${end}/${proto} already open${NC}"
        return 0
    fi
    if _sudo "$_ipt_bin" -C INPUT -p "$proto" --dport "${start}:${end}" -j ACCEPT &>/dev/null 2>&1; then
        echo -e "  ${DIM}· iptables: ${start}:${end}/${proto} already open${NC}"
        return 0
    fi
    if _sudo "$_ipt_bin" -A INPUT -p "$proto" --dport "${start}:${end}" -j ACCEPT &>/dev/null 2>&1; then
        _IPT_RULES_CACHE=""
        echo -e "  ${GREEN}✓ iptables: ${start}:${end}/${proto} opened${NC}"
    else
        echo -e "  ${YELLOW}⚠ iptables: range ${start}:${end}/${proto} failed${NC}"
    fi
}

_ipt_persist() {
    # Save iptables rules so they survive reboot
    # Try in order: iptables-save → netfilter-persistent → iptables-persistent
    if command -v iptables-save &>/dev/null; then
        local rules_file="/etc/iptables/rules.v4"
        local rules_dir; rules_dir=$(dirname "$rules_file")
        if _sudo mkdir -p "$rules_dir" &>/dev/null 2>&1 && \
           _sudo bash -c "iptables-save > ${rules_file}" &>/dev/null 2>&1; then
            echo -e "  ${GREEN}✓ iptables rules saved to ${rules_file}${NC}"
            # Enable netfilter-persistent if available
            if command -v netfilter-persistent &>/dev/null; then
                _sudo systemctl enable netfilter-persistent &>/dev/null 2>&1 || true
            fi
            return 0
        fi
    fi
    echo -e "  ${DIM}· iptables-save not available — rules may reset on reboot${NC}"
    echo -e "  ${DIM}  Install: sudo apt install iptables-persistent  (Debian/Ubuntu)${NC}"
    echo -e "  ${DIM}           sudo dnf install iptables-services    (RHEL/Fedora)${NC}"
}

# ── nftables helpers ───────────────────────────────────────────────────────
_nft_table="inet"
_nft_chain="input"
_nft_file="/etc/nftables.conf"

_NFT_RULESET_CACHE=""
_nft_ruleset() {
    if [ -z "$_NFT_RULESET_CACHE" ]; then
        _NFT_RULESET_CACHE=$(_sudo nft list ruleset 2>/dev/null || echo "")
    fi
    echo "$_NFT_RULESET_CACHE"
}

_nft_rule_exists() {
    local port=$1 proto=$2
    _nft_ruleset | grep -qE "${proto}.*dport.*${port}.*accept|dport.*${port}.*${proto}.*accept" 2>/dev/null
}

_nft_ensure_chain() {
    # Create inet filter table + input chain if not present (needed on fresh Debian VPS)
    if ! _sudo nft list table inet filter &>/dev/null 2>&1; then
        _sudo nft add table inet filter &>/dev/null 2>&1 || true
    fi
    if ! _sudo nft list chain inet filter input &>/dev/null 2>&1; then
        _sudo nft add chain inet filter input '{ type filter hook input priority 0; policy accept; }' &>/dev/null 2>&1 || true
        _NFT_RULESET_CACHE=""
    fi
}

_nft_open() {
    local port=$1 proto=${2:-tcp} label=${3:-}
    if _nft_rule_exists "$port" "$proto"; then
        echo -e "  ${DIM}· nftables: ${port}/${proto} already open${NC}"
        return 0
    fi
    _nft_ensure_chain
    if _sudo nft add rule inet filter input "$proto" dport "$port" accept &>/dev/null 2>&1; then
        _NFT_RULESET_CACHE=""
        echo -e "  ${GREEN}✓ nftables: ${port}/${proto} opened${label:+ ($label)}${NC}"
        _nft_persist
    else
        echo -e "  ${YELLOW}⚠ nftables: ${port}/${proto} failed — add manually:${NC}"
        echo -e "  ${DIM}  sudo nft add rule inet filter input ${proto} dport ${port} accept${NC}"
    fi
}

_nft_open_range() {
    local start=$1 end=$2 proto=${3:-udp}
    if _nft_ruleset | grep -qE "${proto}.*dport.*${start}-${end}.*accept" 2>/dev/null; then
        echo -e "  ${DIM}· nftables: ${start}-${end}/${proto} already open${NC}"
        return 0
    fi
    _nft_ensure_chain
    if _sudo nft add rule inet filter input "$proto" dport "{ ${start}-${end} }" accept &>/dev/null 2>&1; then
        _NFT_RULESET_CACHE=""
        echo -e "  ${GREEN}✓ nftables: ${start}-${end}/${proto} opened${NC}"
        _nft_persist
    else
        echo -e "  ${YELLOW}⚠ nftables: range failed — add manually:${NC}"
        echo -e "  ${DIM}  sudo nft add rule inet filter input ${proto} dport { ${start}-${end} } accept${NC}"
    fi
}

_nft_persist() {
    # Save nftables ruleset to conf file for persistence
    if [ -f "$_nft_file" ] && _sudo bash -c "nft list ruleset > ${_nft_file}" &>/dev/null 2>&1; then
        return 0
    fi
    # Try alternate paths
    for conf in /etc/nftables.conf /etc/nftables/main.conf; do
        if [ -f "$conf" ] && _sudo bash -c "nft list ruleset > ${conf}" &>/dev/null 2>&1; then
            return 0
        fi
    done
}

# ── Root-aware sudo wrapper ────────────────────────────────────────────────
_sudo() {
    if [ "$(id -u)" = "0" ]; then
        "$@"
    else
        _sudo "$@"
    fi
}

# ── Main port opener (auto-detects firewall) ───────────────────────────────
_FW_TYPE=""
_open_port() {
    local port=$1 proto=${2:-tcp} label=${3:-}
    # _FW_TYPE is set before apply rules section; detect here as fallback
    if [ -z "$_FW_TYPE" ]; then
        _FW_TYPE=$(_detect_firewall)
    fi
    case "$_FW_TYPE" in
        firewalld)     _firewalld_open "$port" "$proto" "$label" ;;
        ufw)           _ufw_open       "$port" "$proto" "$label" ;;
        nftables)      _nft_open       "$port" "$proto" "$label" ;;
        iptables*)     _ipt_open       "$port" "$proto" "$label" ;;
        none)
            echo -e "  ${YELLOW}⚠ No firewall detected — port ${port}/${proto} not configured${NC}"
            echo -e "  ${DIM}  Install ufw: sudo apt install ufw && sudo ufw allow ${port}/${proto}${NC}"
            ;;
    esac
}

_open_range() {
    local start=$1 end=$2 proto=${3:-udp}
    case "$_FW_TYPE" in
        firewalld) _firewalld_open_range "$start" "$end" "$proto" ;;
        ufw)       _ufw_open_range       "$start" "$end" "$proto" ;;
        nftables)  _nft_open_range       "$start" "$end" "$proto" ;;
        iptables*) _ipt_open_range       "$start" "$end" "$proto" ;;
    esac
}

_apply_firewall_rules

fi  # end Type 3 firewall skip

# ============ STEP 12: UPDATE SYSTEMD SERVICE IF EXISTS ============
_SERVICE_NAME="mysterium-toolkit"
_SERVICE_FILE="/etc/systemd/system/${_SERVICE_NAME}.service"
if [ -f "$_SERVICE_FILE" ]; then
    echo "Step 12a: Updating systemd service to new directory..."
    _VENV_PYTHON="$TOOLKIT_DIR/venv/bin/python"
    _REAL_USER="${SUDO_USER:-$USER}"
    _REAL_HOME=$(getent passwd "$_REAL_USER" | cut -d: -f6)
    mkdir -p "$TOOLKIT_DIR/logs"
    chown -R "$_REAL_USER:$_REAL_USER" "$TOOLKIT_DIR/logs" 2>/dev/null || true
    # Detect Mysterium node service name — modern installs use 'myst'
    _MYST_SVC=""
    for _svc in myst mysterium myst.service; do
        if systemctl is-enabled "$_svc" 2>/dev/null | grep -qE "enabled|static|disabled" || \
           systemctl is-active "$_svc" 2>/dev/null | grep -qE "active|inactive"; then
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
    echo -e "  ${GREEN}✓ Systemd service updated → $TOOLKIT_DIR${NC}"

    # Write sudoers.d for health fixes — always rewrite to ensure latest commands are included
    _SUDOERS_FILE="/etc/sudoers.d/mysterium-toolkit"
    $SUDO tee "$_SUDOERS_FILE" > /dev/null << SUDOERS_EOF
# Mysterium Node Toolkit — passwordless sudo for health fixes only
# Generated by setup.sh — do not edit manually, re-run setup.sh to update
#
# Each entry is the minimum needed for a specific subsystem:
#   sysctl          — kernel network tuning (conntrack, buffers, BBR)
#   ethtool         — NIC interrupt coalescing and checksum offload
#   conntrack       — read connection tracking table
#   modprobe        — load kernel modules (tcp_bbr, nf_conntrack)
#   bash            — write config files to /etc/sysctl.d/, /usr/local/bin/, /etc/systemd/
#   tee             — write to specific system paths
#   cat             — read persisted sysctl config
#   systemctl       — manage mysterium-* and irqbalance services
#   cpupower        — set CPU frequency governor
#   update-alternatives — switch iptables backend (nftables vs legacy)
#   fallocate/dd    — create swapfile
#   chmod/mkswap/swapon/rm — configure and activate swap
#   iptables/ip6tables/nft — read firewall rules
$_REAL_USER ALL=(ALL) NOPASSWD: \
  /sbin/sysctl, \
  /usr/sbin/ethtool, \
  /usr/sbin/conntrack, \
  /sbin/modprobe, /usr/sbin/modprobe, \
  /bin/bash, /usr/bin/bash, \
  /bin/cat, /usr/bin/cat, \
  /usr/bin/tee /etc/sysctl.d/*, \
  /usr/bin/tee /usr/local/bin/*, \
  /usr/bin/tee /etc/systemd/system/mysterium-*.service, \
  /usr/bin/tee /etc/systemd/system/mysterium-*.timer, \
  /usr/bin/tee /etc/modules-load.d/*, \
  /usr/bin/tee /etc/default/cpupower, \
  /usr/bin/tee /etc/default/cpufrequtils, \
  /bin/systemctl start mysterium-*, \
  /bin/systemctl stop mysterium-*, \
  /bin/systemctl restart mysterium-*, \
  /bin/systemctl enable mysterium-*, \
  /bin/systemctl disable mysterium-*, \
  /bin/systemctl enable irqbalance, \
  /bin/systemctl start irqbalance, \
  /bin/systemctl daemon-reload, \
  /usr/bin/cpupower frequency-set, \
  /usr/bin/update-alternatives --set iptables *, \
  /usr/bin/update-alternatives --set ip6tables *, \
  /usr/bin/fallocate, \
  /bin/dd if=/dev/zero *, \
  /usr/bin/chmod 600 *, \
  /sbin/mkswap *, /usr/sbin/mkswap *, \
  /sbin/swapon *, /usr/bin/swapon *, \
  /bin/rm /swapfile, /usr/bin/rm /swapfile, \
  /usr/sbin/iptables, /sbin/iptables, \
  /usr/sbin/iptables-legacy, /sbin/iptables-legacy, \
  /usr/sbin/ip6tables, /sbin/ip6tables, \
  /usr/sbin/nft, /sbin/nft
SUDOERS_EOF
    $SUDO chmod 440 "$_SUDOERS_FILE"
    if $SUDO visudo -c -f "$_SUDOERS_FILE" >/dev/null 2>&1; then
        echo -e "  ${GREEN}✓ Sudoers configured — health fixes and firewall scan work without password${NC}"
    else
        $SUDO rm -f "$_SUDOERS_FILE"
        echo -e "  ${YELLOW}⚠ Sudoers config failed — health fixes will require password${NC}"
    fi
fi

# ============ STEP 13: OPEN MENU ============
echo "Step 13: Opening menu..."
echo
echo -e "  ${BOLD}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "  ${BOLD}║  Setup complete — read before continuing                 ║${NC}"
echo -e "  ${BOLD}╚══════════════════════════════════════════════════════════╝${NC}"
echo
echo -e "  ${GREEN}✓ Dashboard:${NC}  http://$(hostname -I | awk '{print $1}' 2>/dev/null || echo 'localhost'):${DASHBOARD_PORT:-5000}"
echo -e "  ${GREEN}✓ Config:${NC}     $TOOLKIT_DIR/config/setup.json"
echo
echo -e "  ${CYAN}Key tips:${NC}"
echo -e "  ${DIM}  • Option 9  — enable autostart so toolkit survives reboots${NC}"
echo -e "  ${DIM}  • Option 4  — open the CLI dashboard (terminal UI)${NC}"
echo -e "  ${DIM}  • Option 7  — maintenance, uninstall, cleanup old versions${NC}"
if [ "$SETUP_MODE" = "2" ]; then
echo
echo -e "  ${YELLOW}Fleet master setup:${NC}"
echo -e "  ${DIM}  • Edit config/nodes.json to add your remote nodes${NC}"
echo -e "  ${DIM}  • Each node needs: id, label, url, toolkit_url, toolkit_api_key${NC}"
echo -e "  ${DIM}  • The remote node's API key is in its config/setup.json${NC}"
fi
if [ "$SETUP_MODE" = "3" ]; then
echo
echo -e "  ${YELLOW}Lightweight backend:${NC}"
echo -e "  ${DIM}  • This node serves /peer/data for the fleet master${NC}"
echo -e "  ${DIM}  • Fleet master URL for this node: http://$(hostname -I | awk '{print $1}' 2>/dev/null || echo 'THIS_IP'):${DASHBOARD_PORT:-5000}${NC}"
echo
echo -e "  ${YELLOW}  ⚠ Autostart (option 9) — important order:${NC}"
echo -e "  ${DIM}    1. First start the backend manually via option 1 or ./start.sh${NC}"
echo -e "  ${DIM}    2. Only then activate autostart via option 9 in the menu${NC}"
echo -e "  ${DIM}    Activating autostart before the backend runs will fail on this node type.${NC}"
fi
echo
read -p "  Press Enter to open the dashboard menu..." _setup_done
echo
"$TOOLKIT_DIR/bin/start.sh"

