#!/bin/bash
# Mysterium Node Toolkit — Stop Script
# =====================================
# Stops backend and frontend processes cleanly.
# Uses PID files first; falls back to directory-scoped process search.
# Never uses broad pkill patterns — only kills processes from THIS toolkit.
#
# Usage: ./bin/stop.sh
#        Called automatically by cleanup.sh and start.sh

# Intentionally NO set -e — each step handles its own errors

TOOLKIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$TOOLKIT_DIR"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
DIM='\033[2m'
BOLD='\033[1m'
NC='\033[0m'

BACKEND_PID_FILE="$TOOLKIT_DIR/logs/.backend.pid"
FRONTEND_PID_FILE="$TOOLKIT_DIR/logs/.frontend.pid"

# ── Portable directory-scoped process finder ──────────────────────────────────
# Strategy 1: pgrep -af  — GNU/Linux (Debian, Ubuntu, Parrot, Fedora, Arch)
# Strategy 2: ps aux     — busybox/Alpine and any POSIX-compliant system
_find_pids_in_dir() {
    local pattern="$1"
    local dir="$2"

    if pgrep --help 2>&1 | grep -q -- '-a'; then
        pgrep -af "$pattern" 2>/dev/null \
            | awk -v d="$dir" '$0 ~ d {print $1}' || true
    else
        ps aux 2>/dev/null \
            | awk -v p="$pattern" -v d="$dir" \
              '$0 ~ p && $0 ~ d && $0 !~ /awk/ {print $2}' || true
    fi
}

# ── SIGTERM → wait 1s → SIGKILL if still alive ───────────────────────────────
_stop_pid() {
    local pid="$1"
    [ -z "$pid" ] && return 1
    kill -0 "$pid" 2>/dev/null || return 1      # Already gone
    kill    "$pid" 2>/dev/null || true           # SIGTERM
    sleep 1
    kill -0 "$pid" 2>/dev/null || return 0       # Exited cleanly
    kill -9 "$pid" 2>/dev/null || true           # SIGKILL
    return 0
}

# ── Stop backend ──────────────────────────────────────────────────────────────
_stop_backend() {
    local stopped=false

    if [ -f "$BACKEND_PID_FILE" ]; then
        local pid; pid=$(cat "$BACKEND_PID_FILE" 2>/dev/null)
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            _stop_pid "$pid"
            echo -e "  ${GREEN}✓${NC} Backend stopped ${DIM}(PID $pid)${NC}"
            stopped=true
        fi
        rm -f "$BACKEND_PID_FILE"
    fi

    local orphans; orphans=$(_find_pids_in_dir "backend/app.py" "$TOOLKIT_DIR")
    if [ -n "$orphans" ]; then
        echo "$orphans" | while IFS= read -r pid; do
            [ -z "$pid" ] && continue
            _stop_pid "$pid" || true
            echo -e "  ${GREEN}✓${NC} Backend orphan stopped ${DIM}(PID $pid)${NC}"
            stopped=true
        done
    fi

    [ "$stopped" = false ] && echo -e "  ${DIM}· Backend was not running${NC}"
}

# ── Stop frontend ─────────────────────────────────────────────────────────────
_stop_frontend() {
    local stopped=false

    if [ -f "$FRONTEND_PID_FILE" ]; then
        local pid; pid=$(cat "$FRONTEND_PID_FILE" 2>/dev/null)
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            _stop_pid "$pid"
            echo -e "  ${GREEN}✓${NC} Frontend stopped ${DIM}(PID $pid)${NC}"
            stopped=true
        fi
        rm -f "$FRONTEND_PID_FILE"
    fi

    local vite_pids; vite_pids=$(_find_pids_in_dir "vite" "$TOOLKIT_DIR")
    if [ -n "$vite_pids" ]; then
        echo "$vite_pids" | while IFS= read -r pid; do
            [ -z "$pid" ] && continue
            _stop_pid "$pid" || true
            echo -e "  ${GREEN}✓${NC} Vite orphan stopped ${DIM}(PID $pid)${NC}"
            stopped=true
        done
    fi

    [ "$stopped" = false ] && echo -e "  ${DIM}· Frontend was not running${NC}"
}

# ── Main ──────────────────────────────────────────────────────────────────────
echo
echo -e "  ${BOLD}Stopping Mysterium Toolkit...${NC}"
echo
_stop_backend
_stop_frontend
echo
echo -e "  ${GREEN}✓${NC} Done."
echo
