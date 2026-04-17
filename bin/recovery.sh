#!/bin/bash
# ============================================================
# Mysterium Node Toolkit — Recovery Script
# ============================================================
# Undoes all system health fixes that may have caused issues:
#   - Removes persisted sysctl overrides
#   - Reloads kernel defaults
#   - Ensures IP forwarding stays enabled (critical for VPN)
#   - Restarts Mysterium node service
#
# Note: NIC ring buffers are NOT touched — the health module never
#       changes them (risk of freezing older Intel NICs), so recovery
#       has nothing to undo there.
#
# Run: sudo bash bin/recovery.sh
# ============================================================
#
# Intentionally NO set -e — a recovery script must survive
# partial failures and complete as many steps as possible.
# Each step handles its own errors individually.
# ============================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[96m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

echo
_bl() { local t="   $1"; local w=68; local p=$((w - ${#t})); [ $p -lt 0 ] && p=0
        printf "${CYAN}${BOLD}║%s%*s║${NC}\n" "$t" "$p" ""; }
echo -e "${CYAN}${BOLD}╔$(printf '═%.0s' $(seq 1 68))╗${NC}"
_bl "Mysterium Node Toolkit — Recovery"
echo -e "${CYAN}${BOLD}╚$(printf '═%.0s' $(seq 1 68))╝${NC}"
echo

if [ "${EUID:-$(id -u)}" -ne 0 ]; then
    echo -e "${RED}Please run as root: sudo bash bin/recovery.sh${NC}"
    exit 1
fi

CHANGES=0
ERRORS=0

# ── Portable service restart ──────────────────────────────────────────────────
_restart_myst_service() {
    # systemd (Debian, Ubuntu, Parrot, Fedora, Arch)
    if command -v systemctl >/dev/null 2>&1; then
        if systemctl list-units --type=service 2>/dev/null | grep -q mysterium; then
            systemctl restart mysterium-node 2>/dev/null \
                && { echo -e "  ${GREEN}✓${NC} mysterium-node restarted (systemd)"; return 0; } \
                || { echo -e "  ${YELLOW}⚠${NC} Could not restart — try: sudo systemctl restart mysterium-node"; return 1; }
        fi
    fi
    # OpenRC (Alpine, Gentoo)
    if command -v rc-service >/dev/null 2>&1; then
        if rc-service mysterium-node status >/dev/null 2>&1; then
            rc-service mysterium-node restart 2>/dev/null \
                && { echo -e "  ${GREEN}✓${NC} mysterium-node restarted (OpenRC)"; return 0; } \
                || { echo -e "  ${YELLOW}⚠${NC} Could not restart — try: sudo rc-service mysterium-node restart"; return 1; }
        fi
    fi
    # Docker
    if command -v docker >/dev/null 2>&1; then
        if docker ps 2>/dev/null | grep -q mysterium; then
            docker restart myst 2>/dev/null \
                && { echo -e "  ${GREEN}✓${NC} mysterium Docker container restarted"; return 0; } \
                || { echo -e "  ${YELLOW}⚠${NC} Could not restart Docker container"; return 1; }
        fi
    fi
    echo -e "  ${DIM}mysterium-node service not found — start manually${NC}"
    return 0
}

# ── Step 1: Remove persisted sysctl overrides ────────────────────────────────
echo -e "${BOLD}[1/4] Checking persisted sysctl overrides...${NC}"
_removed_sysctl=false
for conf in \
    /etc/sysctl.d/99-mysterium-node.conf \
    /etc/sysctl.d/99-myst-conntrack.conf \
    /etc/sysctl.d/99-myst-network.conf
do
    if [ -f "$conf" ]; then
        echo -e "  ${YELLOW}Found:${NC} $conf"
        if rm -f "$conf" 2>/dev/null; then
            echo -e "  ${GREEN}✓${NC} Removed"
            CHANGES=$((CHANGES + 1))
            _removed_sysctl=true
        else
            echo -e "  ${RED}✗${NC} Could not remove — try: sudo rm -f $conf"
            ERRORS=$((ERRORS + 1))
        fi
    fi
done
[ "$_removed_sysctl" = false ] && echo -e "  ${DIM}No overrides found — OK${NC}"
echo

# ── Step 2: Reload system sysctl defaults ────────────────────────────────────
echo -e "${BOLD}[2/4] Reloading system sysctl defaults...${NC}"
if sysctl --system > /dev/null 2>&1; then
    echo -e "  ${GREEN}✓${NC} System defaults reloaded"
    CHANGES=$((CHANGES + 1))
else
    echo -e "  ${YELLOW}⚠${NC} sysctl --system failed — try manually: sudo sysctl --system"
    ERRORS=$((ERRORS + 1))
fi
echo

# ── Step 3: Ensure IP forwarding stays ON ────────────────────────────────────
echo -e "${BOLD}[3/4] Verifying IP forwarding (required for VPN)...${NC}"
IP_FWD=$(sysctl -n net.ipv4.ip_forward 2>/dev/null || echo "0")
if [ "$IP_FWD" != "1" ]; then
    if sysctl -w net.ipv4.ip_forward=1 > /dev/null 2>/dev/null; then
        echo -e "  ${YELLOW}⚠${NC} Was disabled — re-enabled"
        CHANGES=$((CHANGES + 1))
    else
        echo -e "  ${RED}✗${NC} Could not enable — try: sudo sysctl -w net.ipv4.ip_forward=1"
        ERRORS=$((ERRORS + 1))
    fi
else
    echo -e "  ${GREEN}✓${NC} Already enabled"
fi
echo

# ── Step 4: Restart Mysterium node ───────────────────────────────────────────
echo -e "${BOLD}[4/4] Restarting Mysterium node service...${NC}"
_restart_myst_service || ERRORS=$((ERRORS + 1))
echo

# ── Summary ───────────────────────────────────────────────────────────────────
echo -e "${GREEN}${BOLD}Recovery complete.${NC}"
echo -e "  Changes applied: ${CHANGES}"
[ "$ERRORS" -gt 0 ] && echo -e "  ${YELLOW}Steps with warnings: ${ERRORS}${NC}"
echo
echo -e "${DIM}Your node should start accepting connections within 2–5 minutes."
echo -e "Check with: myst service status${NC}"
echo
