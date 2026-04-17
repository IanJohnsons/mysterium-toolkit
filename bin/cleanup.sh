#!/bin/bash

# Mysterium Node Toolkit - Cleanup & Uninstall
# ==============================================
# Three modes:
#   1. Clean: Remove runtime files (venv, node_modules, logs) — source stays
#   2. Config: Remove config only (.env, setup.json) — rerun wizard
#   3. Full Uninstall: Delete EVERYTHING — cannot be undone
#
# Called from menu (option 8) or standalone: ./bin/cleanup.sh

# Intentionally NO set -e — each deletion is individually guarded

TOOLKIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$TOOLKIT_DIR"

# Colors
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
CYAN='\033[96m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'


# ── Detect package manager once ──────────────────────────────
PKG_MGR=""
command -v apt-get >/dev/null 2>&1 && PKG_MGR="apt"
command -v dnf     >/dev/null 2>&1 && [ -z "$PKG_MGR" ] && PKG_MGR="dnf"
command -v yum     >/dev/null 2>&1 && [ -z "$PKG_MGR" ] && PKG_MGR="yum"
command -v pacman  >/dev/null 2>&1 && [ -z "$PKG_MGR" ] && PKG_MGR="pacman"
command -v apk     >/dev/null 2>&1 && [ -z "$PKG_MGR" ] && PKG_MGR="apk"

# ── Portable process kill ─────────────────────────────────────
_pkill_toolkit() {
    local pattern="$1"
    local pids
    if pgrep --help 2>&1 | grep -q -- "-a"; then
        pids=$(pgrep -af "$pattern" 2>/dev/null | grep "$TOOLKIT_DIR" | awk '{print $1}' || true)
    else
        pids=$(ps aux 2>/dev/null | grep "$pattern" | grep "$TOOLKIT_DIR" | grep -v grep | awk '{print $2}' || true)
    fi
    [ -n "$pids" ] && echo "$pids" | xargs kill 2>/dev/null || true
}

# ── Safe delete helpers ───────────────────────────────────────
safe_rmdir() {
    local path="$1" label="$2"
    [ -d "$path" ] || return 0
    local size; size=$(du -sh "$path" 2>/dev/null | cut -f1 || echo "?")
    rm -rf "$path" 2>/dev/null \
        && echo -e "  ${GREEN}✓${NC} ${label} removed (${size})" \
        || echo -e "  ${RED}✗${NC} Cannot remove ${label} — try: sudo rm -rf \"${path}\""
}

safe_rmfile() {
    local path="$1" label="$2"
    [ -f "$path" ] || return 0
    rm -f "$path" 2>/dev/null \
        && echo -e "  ${GREEN}✓${NC} ${label} removed" \
        || echo -e "  ${RED}✗${NC} Cannot remove ${label}"
}

safe_rmlogs() {
    local dir="$1"
    [ -d "$dir" ] || return 0
    local removed=0
    while IFS= read -r -d '' f; do
        rm -f "$f" 2>/dev/null && removed=$((removed + 1)) || true
    done < <(find "$dir" -maxdepth 1 \( -name "*.log" -o -name ".*.pid" \) -print0 2>/dev/null)
    [ $removed -gt 0 ] \
        && echo -e "  ${GREEN}✓${NC} logs cleaned ($removed files)" \
        || echo -e "  ${DIM}  logs already empty${NC}"
}

echo
_bl() { local t="   $1"; local w=68; local p=$((w - ${#t})); [ $p -lt 0 ] && p=0; printf "${CYAN}${BOLD}║%s%*s║${NC}\n" "$t" "$p" ""; }
echo -e "${CYAN}${BOLD}╔$(printf '═%.0s' $(seq 1 68))╗${NC}"
_bl "Mysterium Node Toolkit - Cleanup"
echo -e "${CYAN}${BOLD}╚$(printf '═%.0s' $(seq 1 68))╝${NC}"
echo

# Show what exists
echo -e "  ${BOLD}Installation: ${TOOLKIT_DIR}${NC}"
echo
echo -e "  ${DIM}Detected:${NC}"
[ -d "venv" ]              && echo -e "    ${GREEN}●${NC} venv/           $(du -sh venv 2>/dev/null | cut -f1)" || echo -e "    ${DIM}○ venv/ (not present)${NC}"
[ -d "node_modules" ]      && echo -e "    ${GREEN}●${NC} node_modules/   $(du -sh node_modules 2>/dev/null | cut -f1)" || echo -e "    ${DIM}○ node_modules/ (not present)${NC}"
[ -f ".env" ]              && echo -e "    ${GREEN}●${NC} .env" || echo -e "    ${DIM}○ .env (not present)${NC}"
[ -f "config/setup.json" ] && echo -e "    ${GREEN}●${NC} config/setup.json" || echo -e "    ${DIM}○ config/setup.json (not present)${NC}"
[ -d "logs" ] && ls logs/*.log &>/dev/null 2>&1 && echo -e "    ${GREEN}●${NC} logs/           $(du -sh logs 2>/dev/null | cut -f1)" || echo -e "    ${DIM}○ logs/ (empty)${NC}"
[ -f "package-lock.json" ] && echo -e "    ${GREEN}●${NC} package-lock.json" || echo -e "    ${DIM}○ package-lock.json (not present)${NC}"
echo

# ===== MODE SELECTION =====
echo -e "  ${BOLD}What would you like to do?${NC}"
echo
echo "  1. Clean runtime files (venv, node_modules, logs, lock files)"
echo "     Config (.env, setup.json) and source code stay intact."
echo "     Run ./setup.sh afterwards to reinstall."
echo
echo "  2. Remove config only (.env, config/setup.json)"
echo "     Keeps everything else — just rerun the setup wizard."
echo
echo -e "  3. ${RED}Full uninstall — delete EVERYTHING (cannot be undone)${NC}"
echo
echo "  4. Scan & clean ALL other toolkit installs found on this system"
echo "     (removes venv/config/source from old installs)"
echo
echo "  5. Cancel"
echo

read -p "  Select (1-5): " MODE

case $MODE in
    1)
        echo
        echo -e "  ${BOLD}Cleaning runtime files...${NC}"
        echo
        echo -e "  ${DIM}Each item asks individually. Press y or n.${NC}"
        echo

        # Stop processes from THIS toolkit only
        _pkill_toolkit "python.*backend/app.py"
        _pkill_toolkit "vite"
        _pkill_toolkit "npm.*start"
        sleep 1

        if [ -d "venv" ]; then
            read -p "  Remove venv/? [y/N]: " -r -n 1; echo
            [[ ${REPLY:-n} =~ ^[Yy]$ ]] && safe_rmdir "venv" "venv" || echo -e "  ${DIM}  skipped${NC}"
        fi

        if [ -d "node_modules" ]; then
            read -p "  Remove node_modules/? [y/N]: " -r -n 1; echo
            [[ ${REPLY:-n} =~ ^[Yy]$ ]] && safe_rmdir "node_modules" "node_modules" || echo -e "  ${DIM}  skipped${NC}"
        fi

        if [ -f "package-lock.json" ]; then
            read -p "  Remove package-lock.json? [y/N]: " -r -n 1; echo
            [[ ${REPLY:-n} =~ ^[Yy]$ ]] && safe_rmfile "package-lock.json" "package-lock.json" || echo -e "  ${DIM}  skipped${NC}"
        fi

        if [ -d "logs" ]; then
            read -p "  Clean log files? [y/N]: " -r -n 1; echo
            [[ ${REPLY:-n} =~ ^[Yy]$ ]] && safe_rmlogs "logs" || echo -e "  ${DIM}  skipped${NC}"
        fi

        # Always clean pycache silently
        find "$TOOLKIT_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
        find "$TOOLKIT_DIR" -name "*.pyc" -delete 2>/dev/null || true

        echo
        echo -e "  ${GREEN}Done.${NC} Run ${BOLD}./setup.sh${NC} to reinstall."
        ;;

    2)
        echo
        echo -e "  ${BOLD}Removing configuration...${NC}"
        echo

        if [ -f ".env" ]; then
            read -p "  Remove .env? [y/N]: " -r -n 1; echo
            [[ ${REPLY:-n} =~ ^[Yy]$ ]] && safe_rmfile ".env" ".env" || echo -e "  ${DIM}  skipped${NC}"
        fi

        if [ -f "config/setup.json" ]; then
            read -p "  Remove config/setup.json? [y/N]: " -r -n 1; echo
            [[ ${REPLY:-n} =~ ^[Yy]$ ]] && safe_rmfile "config/setup.json" "config/setup.json" || echo -e "  ${DIM}  skipped${NC}"
        fi

        echo
        echo -e "  ${GREEN}Done.${NC} Run ${BOLD}python scripts/setup_wizard.py${NC} to reconfigure."
        ;;

    3)
        echo
        echo -e "  ${RED}${BOLD}════════════════════════════════════════${NC}"
        echo -e "  ${RED}${BOLD}  FULL UNINSTALL — PERMANENT DELETION  ${NC}"
        echo -e "  ${RED}${BOLD}════════════════════════════════════════${NC}"
        echo
        echo -e "  ${RED}This will delete EVERYTHING:${NC}"
        echo -e "  ${RED}  → All source code (backend, frontend, cli, scripts)${NC}"
        echo -e "  ${RED}  → All config (.env, setup.json)${NC}"
        echo -e "  ${RED}  → All runtime (venv, node_modules, logs)${NC}"
        echo -e "  ${RED}  → The entire directory: ${BOLD}${TOOLKIT_DIR}${NC}"
        echo
        echo -e "  ${YELLOW}You will need to re-download the toolkit to use it again.${NC}"
        echo -e "  ${YELLOW}If you just want to clean up, use option 1 instead.${NC}"
        echo

        # Safety checks
        if [ "$TOOLKIT_DIR" = "/" ] || [ "$TOOLKIT_DIR" = "/home" ] || [ "$TOOLKIT_DIR" = "/root" ] || [ "$TOOLKIT_DIR" = "$HOME" ]; then
            echo -e "  ${RED}✗ SAFETY: Refusing to delete system directory: ${TOOLKIT_DIR}${NC}"
            exit 1
        fi

        # Gate 1
        read -p "  Are you sure? [yes/no]: " -r CONFIRM1
        if [[ ! "$CONFIRM1" =~ ^[Yy][Ee][Ss]$ ]]; then
            echo -e "  ${DIM}Cancelled${NC}"
            exit 0
        fi

        # Gate 2 — must type the folder name
        DIR_NAME=$(basename "$TOOLKIT_DIR")
        echo
        echo -e "  ${RED}To confirm, type the folder name: ${BOLD}${DIR_NAME}${NC}"
        read -p "  > " -r CONFIRM2
        if [ "$CONFIRM2" != "$DIR_NAME" ]; then
            echo -e "  ${DIM}Did not match — cancelled${NC}"
            exit 0
        fi

        echo
        echo -e "  ${BOLD}Stopping processes...${NC}"
        # Only kill processes from THIS toolkit directory
        _pkill_toolkit "python.*backend/app.py"
        _pkill_toolkit "vite"
        _pkill_toolkit "npm.*start"
        sleep 1

        # Offer to remove system packages installed by setup
        echo
        echo -e "  ${YELLOW}The toolkit may have installed these system packages during setup:${NC}"
        echo -e "  ${DIM}  vnstat, ethtool, irqbalance, lm-sensors${NC}"
        echo
        read -p "  Remove toolkit-installed system packages too? [y/N]: " -r REMOVE_PKGS
        if [[ "$REMOVE_PKGS" =~ ^[Yy]$ ]]; then
            echo -e "  ${BOLD}Removing system packages...${NC}"
            PKGS="vnstat ethtool irqbalance lm-sensors"
            case "$PKG_MGR" in
                apt)    sudo apt-get remove -y $PKGS 2>/dev/null && sudo apt-get autoremove -y 2>/dev/null || true ;;
                dnf|yum) sudo dnf remove -y $PKGS 2>/dev/null || true ;;
                pacman) sudo pacman -Rns --noconfirm $PKGS 2>/dev/null || true ;;
                apk)    apk del $PKGS 2>/dev/null || true ;;
                *)      echo -e "  ${YELLOW}⚠ No supported package manager — remove manually${NC}" ;;
            esac
            echo -e "  ${GREEN}✓ Done${NC}"
        else
            echo -e "  ${DIM}  Keeping system packages${NC}"
        fi

        # Remove udev rule if installed
        [ -f '/etc/udev/rules.d/99-myst-vnstat.rules' ] &&             sudo rm -f '/etc/udev/rules.d/99-myst-vnstat.rules' 2>/dev/null &&             sudo udevadm control --reload-rules 2>/dev/null || true

        echo -e "  ${RED}Deleting ${TOOLKIT_DIR}...${NC}"
        PARENT=$(dirname "$TOOLKIT_DIR")
        cd "$PARENT"
        if rm -rf "$TOOLKIT_DIR" 2>/dev/null; then
            echo -e "  ${GREEN}✓ Toolkit removed from: ${TOOLKIT_DIR}${NC}"
        else
            echo -e "  ${RED}✗ Could not remove — try: sudo rm -rf \"${TOOLKIT_DIR}\"${NC}"
        fi
        exit 0
        ;;

    4)
        echo
        echo -e "  ${CYAN}${BOLD}Scanning for ALL toolkit installations on this system...${NC}"
        echo
        SCAN_PY=""
        command -v python3 >/dev/null 2>&1 && SCAN_PY="python3"
        command -v python  >/dev/null 2>&1 && [ -z "$SCAN_PY" ] && SCAN_PY="python"
        if [ -n "$SCAN_PY" ] && [ -f "$TOOLKIT_DIR/scripts/env_scanner.py" ]; then
            $SCAN_PY "$TOOLKIT_DIR/scripts/env_scanner.py" --remove-source
        else
            echo -e "  ${RED}✗ Scanner not available${NC}"
        fi
        ;;

    5|*)
        echo -e "  ${DIM}Cancelled${NC}"
        exit 0
        ;;
esac

echo
