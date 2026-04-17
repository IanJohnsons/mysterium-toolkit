#!/bin/bash
# ============================================================
# Mysterium Node — System Diagnostics  v4.7.5
# ============================================================
# Investigates system issues under VPN node load.
# Tests: thermal, memory, NIC driver, IRQ, disk, kernel,
#        conntrack, WireGuard tunnels, process pressure.
#
# Run: sudo bash bin/diagnose.sh
# Run: sudo bash bin/diagnose.sh --stress   (includes load test)
#
# Compatible: Debian, Ubuntu, Parrot, Fedora, Arch, Alpine,
#             and any Linux with bash 4+ and /proc filesystem.
# ============================================================
#
# NOTE: Intentionally NO set -e here.
# A diagnostic script must survive partial failures and keep
# running all sections. Every command is individually guarded.
# ============================================================

# Only -u (catch unbound vars) — NOT -e (exit on any error)
set -uo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[96m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

STRESS_MODE=false
REPORT_FILE="/tmp/mysterium-diagnostic-$(date +%Y%m%d-%H%M%S).log"
ISSUES=0
WARNINGS=0

# ── Distro detection — used by recommendations engine ────────
DISTRO_ID=""
DISTRO_LIKE=""
DISTRO_NAME="Linux"
if [ -f /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    DISTRO_ID="${ID:-}"
    DISTRO_LIKE="${ID_LIKE:-}"
    DISTRO_NAME="${PRETTY_NAME:-Linux}"
fi
# Detect package manager
_pkg() {
    # Usage: _pkg <apt-pkg> [dnf-pkg] [pacman-pkg] [apk-pkg]
    local pa="${1:-}" pd="${2:-$1}" pp="${3:-$1}" pk="${4:-$1}"
    if   command -v apt-get >/dev/null 2>&1; then echo "sudo apt-get install -y ${pa}"
    elif command -v dnf     >/dev/null 2>&1; then echo "sudo dnf install -y ${pd}"
    elif command -v pacman  >/dev/null 2>&1; then echo "sudo pacman -S ${pp}"
    elif command -v apk     >/dev/null 2>&1; then echo "sudo apk add ${pk}"
    else echo "# install ${pa} with your package manager"
    fi
}

# ── Tracking flags for recommendation engine ─────────────────
IS_LAPTOP=false
CPU_THROTTLED=false
CPU_TEMP=""
SWAP_PCT=0
NIC_HAS_ERRORS=false
NIC_MISSING_COALESCING=false
IRQBALANCE_RUNNING=true
MISSING_SENSORS=false

if [[ "${1:-}" == "--stress" ]]; then
    STRESS_MODE=true
fi

# ── Must be root ─────────────────────────────────────────────
if [ "${EUID:-$(id -u)}" -ne 0 ]; then
    echo -e "${RED}Run as root: sudo bash bin/diagnose.sh${NC}"
    exit 1
fi

# ── Helpers ──────────────────────────────────────────────────

# Check if a command exists — portable, no set -e issues
cmd_exists() { command -v "$1" >/dev/null 2>&1; }

# Run a command with optional timeout; echo fallback on any failure
# Usage: timed_cmd <seconds> <fallback> cmd [args...]
timed_cmd() {
    local t="$1" fallback="$2"; shift 2
    if cmd_exists timeout; then
        timeout "$t" "$@" 2>/dev/null || echo "$fallback"
    else
        "$@" 2>/dev/null || echo "$fallback"
    fi
}

log() { echo -e "$1" | tee -a "$REPORT_FILE"; }

header() {
    log ""
    log "${CYAN}${BOLD}═══════════════════════════════════════════════════════════${NC}"
    log "${CYAN}${BOLD}  $1${NC}"
    log "${CYAN}${BOLD}═══════════════════════════════════════════════════════════${NC}"
}

check() {
    local label="$1" status="$2" detail="$3"
    case "$status" in
        ok)       log "  ${GREEN}✓${NC} ${label}: ${detail}" ;;
        warn)     log "  ${YELLOW}▲${NC} ${label}: ${YELLOW}${detail}${NC}" ;;
        critical) log "  ${RED}✗${NC} ${label}: ${RED}${detail}${NC}" ;;
    esac
}

issue() {
    ISSUES=$((ISSUES + 1))
    log "  ${RED}${BOLD}>>> ISSUE: $1${NC}"
}

warning() {
    WARNINGS=$((WARNINGS + 1))
    log "  ${YELLOW}${BOLD}>>> WARNING: $1${NC}"
}

# ── Banner ────────────────────────────────────────────────────
log "${CYAN}${BOLD}"
_bl() { local t="   $1"; local w=68; local p=$((w - ${#t})); [ $p -lt 0 ] && p=0; printf "║%s%*s║\n" "$t" "$p" ""; }
printf "╔"; printf '═%.0s' $(seq 1 68); printf "╗\n"
_bl "Mysterium Node - System Diagnostics"
_bl "$(date)"
printf "╚"; printf '═%.0s' $(seq 1 68); printf "╝\n"
log "${NC}"
log "  Report: ${REPORT_FILE}"
log "  Stress mode: ${STRESS_MODE}"

# ============================================================
# 1. HARDWARE IDENTIFICATION
# ============================================================
header "1. HARDWARE"

MACHINE="unknown"
BIOS_VER="unknown"
if cmd_exists dmidecode; then
    MACHINE=$(dmidecode -s system-product-name 2>/dev/null || echo "unknown")
    BIOS_VER=$(dmidecode -s bios-version   2>/dev/null || echo "unknown")
    # Detect laptop via DMI chassis type
    CHASSIS=$(dmidecode -s chassis-type 2>/dev/null || echo "")
    case "${CHASSIS,,}" in
        *notebook*|*laptop*|*portable*|*sub*notebook*) IS_LAPTOP=true ;;
    esac
fi

CPU_MODEL=$(grep -m1 "model name" /proc/cpuinfo 2>/dev/null | cut -d: -f2 | xargs || echo "unknown")
CPU_CORES=$(nproc 2>/dev/null || grep -c "^processor" /proc/cpuinfo 2>/dev/null || echo "1")
TOTAL_RAM=$(awk '/MemTotal/{printf "%d", $2/1024}' /proc/meminfo 2>/dev/null || echo "0")
TOTAL_SWAP=$(awk '/SwapTotal/{printf "%d", $2/1024}' /proc/meminfo 2>/dev/null || echo "0")

log "  Machine: ${MACHINE}"
log "  BIOS:    ${BIOS_VER}"
log "  CPU:     ${CPU_MODEL} (${CPU_CORES} cores)"
log "  RAM:     ${TOTAL_RAM} MB"
log "  Swap:    ${TOTAL_SWAP} MB"

if [ "${TOTAL_RAM:-0}" -lt 4096 ] 2>/dev/null; then
    issue "Only ${TOTAL_RAM} MB RAM — VPN exit node needs minimum 4 GB"
elif [ "${TOTAL_RAM:-0}" -lt 8192 ] 2>/dev/null; then
    warning "Only ${TOTAL_RAM} MB RAM — 8 GB recommended for heavy VPN load"
fi

if [ "${TOTAL_SWAP:-0}" -eq 0 ] 2>/dev/null; then
    issue "No swap configured — system will OOM under memory pressure"
elif [ "${TOTAL_SWAP:-0}" -lt 2048 ] 2>/dev/null; then
    warning "Swap only ${TOTAL_SWAP} MB — recommend at least 2 GB for VPN node"
fi

# ============================================================
# 2. THERMAL
# ============================================================
header "2. THERMAL"

HAS_SENSORS=false
SENSORS_OUT=""
if cmd_exists sensors; then
    HAS_SENSORS=true
    SENSORS_OUT=$(sensors 2>/dev/null || echo "")
    if [ -n "$SENSORS_OUT" ]; then
        log "${DIM}${SENSORS_OUT}${NC}"
        # Extract highest CPU / Package temp
        CPU_TEMP=$(echo "$SENSORS_OUT" | grep -iE "^(core 0|package id 0|cpu)" \
                   | grep -oP '\+\K[0-9.]+' | head -1 || echo "")
        if [ -z "${CPU_TEMP:-}" ]; then
            CPU_TEMP=$(echo "$SENSORS_OUT" | grep -oP '\+\K[0-9]+\.[0-9]+' | head -1 || echo "")
        fi
        if [ -n "${CPU_TEMP:-}" ]; then
            TEMP_INT=${CPU_TEMP%%.*}
            if   [ "${TEMP_INT:-0}" -gt 90 ] 2>/dev/null; then issue   "CPU at ${CPU_TEMP}°C — THERMAL THROTTLE/SHUTDOWN territory"
            elif [ "${TEMP_INT:-0}" -gt 80 ] 2>/dev/null; then warning "CPU at ${CPU_TEMP}°C — getting hot for sustained load"
            elif [ "${TEMP_INT:-0}" -gt 70 ] 2>/dev/null; then check "CPU Temp" "warn" "${CPU_TEMP}°C"
            else                                                check "CPU Temp" "ok"   "${CPU_TEMP}°C"
            fi
        fi
    fi
else
    warning "lm-sensors not installed — cannot check temperatures"
    MISSING_SENSORS=true
    log "  ${DIM}Install: $(_pkg lm-sensors lm_sensors lm_sensors lm-sensors)${NC}"
fi

# Kernel thermal zones — works on every Linux, supplements sensors output
for tz in /sys/class/thermal/thermal_zone*/temp; do
    [ -f "$tz" ] || continue
    TEMP_MC=$(cat "$tz" 2>/dev/null || echo "0")
    TEMP_C=$(( ${TEMP_MC:-0} / 1000 ))
    ZONE_DIR=$(dirname "$tz")
    TYPE=$(cat "${ZONE_DIR}/type" 2>/dev/null || echo "unknown")
    if   [ "${TEMP_C:-0}" -gt 90 ] 2>/dev/null; then issue   "Thermal zone ${TYPE} at ${TEMP_C}°C — CRITICAL"
    elif [ "${TEMP_C:-0}" -gt 80 ] 2>/dev/null; then warning "Thermal zone ${TYPE} at ${TEMP_C}°C — hot"
    elif [ "$HAS_SENSORS" = false ];              then check "Thermal ${TYPE}" "ok" "${TEMP_C}°C"
    fi
done

# CPU frequency / throttle check
if [ -f /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq ]; then
    CUR_FREQ=$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq 2>/dev/null || echo "0")
    MAX_FREQ=$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_max_freq 2>/dev/null || echo "${CUR_FREQ:-1}")
    CUR_MHZ=$(( ${CUR_FREQ:-0} / 1000 ))
    MAX_MHZ=$(( ${MAX_FREQ:-1} / 1000 ))
    PCT=100
    [ "${MAX_FREQ:-0}" -gt 0 ] 2>/dev/null && PCT=$(( CUR_FREQ * 100 / MAX_FREQ )) || true
    if   [ "${PCT:-100}" -lt 60 ] 2>/dev/null; then issue   "CPU throttled to ${CUR_MHZ}/${MAX_MHZ} MHz (${PCT}%) — likely thermal"; CPU_THROTTLED=true
    elif [ "${PCT:-100}" -lt 80 ] 2>/dev/null; then warning "CPU at ${CUR_MHZ}/${MAX_MHZ} MHz (${PCT}%)"; CPU_THROTTLED=true
    else                                             check "CPU Frequency" "ok" "${CUR_MHZ}/${MAX_MHZ} MHz (${PCT}%)"
    fi
fi

# Fan check
if [ "$HAS_SENSORS" = true ] && [ -n "${SENSORS_OUT:-}" ]; then
    FAN=$(echo "$SENSORS_OUT" | grep -i "fan" | head -1 || echo "")
    if [ -n "${FAN:-}" ]; then
        FAN_RPM=$(echo "$FAN" | grep -oP '[0-9]+(?= RPM)' | head -1 || echo "")
        if [ -n "${FAN_RPM:-}" ] && [ "${FAN_RPM:-1}" -eq 0 ] 2>/dev/null; then
            issue "Fan at 0 RPM — fan might be dead or disconnected"
        else
            check "Fan" "ok" "$FAN"
        fi
    fi
fi

# ============================================================
# 3. MEMORY PRESSURE
# ============================================================
header "3. MEMORY PRESSURE"

MEM_USED=$(awk '/MemTotal/{t=$2} /MemAvailable/{a=$2} END{printf "%d",(t-a)/1024}' /proc/meminfo 2>/dev/null || echo "0")
MEM_AVAIL=$(awk '/MemAvailable/{printf "%d",$2/1024}' /proc/meminfo 2>/dev/null || echo "0")
SWAP_USED=$(awk '/SwapFree/{f=$2} /SwapTotal/{t=$2} END{printf "%d",(t-f)/1024}' /proc/meminfo 2>/dev/null || echo "0")
MEM_PCT=0
[ "${TOTAL_RAM:-1}" -gt 0 ] 2>/dev/null && MEM_PCT=$(( MEM_USED * 100 / TOTAL_RAM )) || true

check "RAM Usage" \
    "$([ "${MEM_PCT:-0}" -gt 90 ] && echo critical || ([ "${MEM_PCT:-0}" -gt 75 ] && echo warn || echo ok))" \
    "${MEM_USED}/${TOTAL_RAM} MB (${MEM_PCT}%) — Available: ${MEM_AVAIL} MB"

if [ "${TOTAL_SWAP:-0}" -gt 0 ] && [ "${SWAP_USED:-0}" -gt 0 ] 2>/dev/null; then
    SWAP_PCT=$(( SWAP_USED * 100 / TOTAL_SWAP )) 2>/dev/null || SWAP_PCT=0
    if [ "${SWAP_PCT:-0}" -gt 50 ] 2>/dev/null; then
        issue "Swap ${SWAP_PCT}% used (${SWAP_USED} MB) — system is memory-starved"
    else
        warning "Swap in use: ${SWAP_USED} MB — some memory pressure"
    fi
fi

OVERCOMMIT=$(sysctl -n vm.overcommit_memory 2>/dev/null || echo "?")
check "vm.overcommit_memory" "ok" "${OVERCOMMIT} (0=heuristic, 1=always, 2=strict)"

OOM_COUNT=$(dmesg 2>/dev/null | grep -ciE "oom|killed process|out of memory" || echo "0")
if [ "${OOM_COUNT:-0}" -gt 0 ] 2>/dev/null; then
    issue "Found ${OOM_COUNT} OOM-related kernel messages — system ran out of memory!"
    dmesg 2>/dev/null | grep -iE "oom|killed process|out of memory" | tail -5 | while read -r line; do
        log "    ${DIM}${line}${NC}"
    done || true
else
    check "OOM Kills" "ok" "None found in dmesg"
fi

if [ -f /proc/pressure/memory ]; then
    SOME_AVG10=$(awk '/^some/{for(i=1;i<=NF;i++) if($i~/^avg10=/) {split($i,a,"="); print a[2]}}' \
                 /proc/pressure/memory 2>/dev/null || echo "0")
    PINT=${SOME_AVG10%%.*}
    if   [ "${PINT:-0}" -gt 25 ] 2>/dev/null; then issue   "Memory pressure avg10=${SOME_AVG10}% — processes stalling waiting for memory"
    elif [ "${PINT:-0}" -gt 5  ] 2>/dev/null; then warning "Memory pressure avg10=${SOME_AVG10}%"
    else                                             check "Memory Pressure" "ok" "avg10=${SOME_AVG10}%"
    fi
fi

log ""
log "  ${DIM}Top 5 memory consumers:${NC}"
ps aux --sort=-%mem 2>/dev/null | head -6 | tail -5 | while read -r line; do
    log "    ${DIM}${line}${NC}"
done || true

# ============================================================
# 4. DISK / I/O
# ============================================================
header "4. DISK / I/O"

ROOT_DISK=""

# Strategy 1: lsblk + findmnt (modern Debian/Ubuntu/Fedora/Arch)
if cmd_exists lsblk && cmd_exists findmnt; then
    _SRC=$(timed_cmd 3 "" findmnt -n -o SOURCE / 2>/dev/null || echo "")
    if [ -n "${_SRC:-}" ]; then
        ROOT_DISK=$(timed_cmd 5 "" lsblk -no PKNAME "$_SRC" 2>/dev/null | head -1 || echo "")
    fi
fi

# Strategy 2: lsblk alone — scan for the / mount point
if [ -z "${ROOT_DISK:-}" ] && cmd_exists lsblk; then
    ROOT_DISK=$(lsblk -no PKNAME,MOUNTPOINT 2>/dev/null | awk '$2=="/" {print $1; exit}' || echo "")
fi

# Strategy 3: df — widely available everywhere
if [ -z "${ROOT_DISK:-}" ]; then
    _DEV=$(df / 2>/dev/null | awk 'NR==2{print $1}' || echo "")
    ROOT_DISK=$(echo "${_DEV:-}" | sed 's|^/dev/||; s/[0-9]*p[0-9]*$//; s/[0-9]*$//' || echo "")
fi

# Strategy 4: /proc/mounts — absolute fallback, always present
if [ -z "${ROOT_DISK:-}" ]; then
    _DEV=$(awk '$2=="/" {print $1; exit}' /proc/mounts 2>/dev/null || echo "")
    ROOT_DISK=$(echo "${_DEV:-}" | sed 's|^/dev/||; s/[0-9]*p[0-9]*$//; s/[0-9]*$//' || echo "")
fi

if [ -n "${ROOT_DISK:-}" ]; then
    log "  ${DIM}Root disk: /dev/${ROOT_DISK}${NC}"
    if cmd_exists smartctl; then
        SMART_HEALTH=$(timed_cmd 10 "unknown" smartctl -H "/dev/${ROOT_DISK}" \
                       | grep -iE "overall|result" | head -1 || echo "unknown")
        if echo "${SMART_HEALTH:-}" | grep -qiE "passed|ok"; then
            check "SMART" "ok" "${SMART_HEALTH} (/dev/${ROOT_DISK})"
        else
            issue "SMART health: ${SMART_HEALTH:-unavailable} (/dev/${ROOT_DISK})"
        fi
        REALLOC=$(timed_cmd 10 "" smartctl -A "/dev/${ROOT_DISK}" \
                  | grep -i "reallocat" | awk '{print $NF}' || echo "")
        if [ -n "${REALLOC:-}" ] && [ "${REALLOC:-0}" -gt 0 ] 2>/dev/null; then
            warning "Reallocated sectors: ${REALLOC} on /dev/${ROOT_DISK}"
        fi
    else
        log "  ${DIM}smartctl not installed (install smartmontools for SMART data)${NC}"
    fi
else
    log "  ${DIM}Could not determine root disk device — skipping SMART check${NC}"
fi

# I/O wait via vmstat (available on virtually all Linux distros)
if cmd_exists vmstat; then
    IOWAIT=$(vmstat 1 2 2>/dev/null | tail -1 | awk '{print $16}' || echo "0")
else
    IOWAIT="0"
    log "  ${DIM}vmstat not available — skipping I/O wait check${NC}"
fi
IOWAIT_INT=${IOWAIT%%.*}
if   [ "${IOWAIT_INT:-0}" -gt 20 ] 2>/dev/null; then issue   "I/O wait at ${IOWAIT}% — disk is bottleneck"
elif [ "${IOWAIT_INT:-0}" -gt 5  ] 2>/dev/null; then warning "I/O wait at ${IOWAIT}%"
else                                                  check "I/O Wait" "ok" "${IOWAIT:-0}%"
fi

DISK_PCT=$(df / 2>/dev/null | awk 'NR==2{print $5}' | tr -d '%' || echo "0")
check "Disk Space /" \
    "$([ "${DISK_PCT:-0}" -gt 95 ] && echo critical || ([ "${DISK_PCT:-0}" -gt 85 ] && echo warn || echo ok))" \
    "${DISK_PCT:-?}% used"

# ============================================================
# 5. NETWORK INTERFACE
# ============================================================
header "5. NETWORK INTERFACE"

PRIMARY_IFACE=""
# Strategy 1: ip route (iproute2 — standard on all modern distros)
if cmd_exists ip; then
    PRIMARY_IFACE=$(ip route show default 2>/dev/null | grep -oP 'dev \K\S+' | head -1 || echo "")
fi
# Strategy 2: route (net-tools — older/minimal systems)
if [ -z "${PRIMARY_IFACE:-}" ] && cmd_exists route; then
    PRIMARY_IFACE=$(route -n 2>/dev/null | awk '$1=="0.0.0.0"{print $8; exit}' || echo "")
fi
# Strategy 3: /proc/net/route — always present, no tools needed
if [ -z "${PRIMARY_IFACE:-}" ]; then
    PRIMARY_IFACE=$(awk 'NR>1 && $2=="00000000"{print $1; exit}' /proc/net/route 2>/dev/null || echo "")
fi

DRIVER="unknown"
if [ -n "${PRIMARY_IFACE:-}" ]; then
    # Get driver info — ethtool preferred, sysfs fallback
    if cmd_exists ethtool; then
        DRIVER=$(ethtool -i "$PRIMARY_IFACE" 2>/dev/null | awk '/^driver:/{print $2}' || echo "unknown")
        FW_VER=$(ethtool -i "$PRIMARY_IFACE" 2>/dev/null | awk '/^firmware-version:/{print $2}' || echo "unknown")
    elif [ -f "/sys/class/net/${PRIMARY_IFACE}/device/driver" ]; then
        DRIVER=$(basename "$(readlink -f "/sys/class/net/${PRIMARY_IFACE}/device/driver" 2>/dev/null)" || echo "unknown")
        FW_VER="n/a (ethtool missing)"
    else
        FW_VER="n/a (ethtool missing)"
    fi
    check "NIC" "ok" "${PRIMARY_IFACE} — driver: ${DRIVER}, firmware: ${FW_VER}"

    # Known problematic driver
    if [ "${DRIVER:-}" = "e1000e" ]; then
        warning "e1000e driver — known to cause hangs under heavy interrupt load on older Intel NICs"
        log "    ${DIM}e1000e (Intel GbE) can cause hangs under high IRQ rates — coalescing recommended${NC}"
        log "    ${DIM}Fix: ethtool -C ${PRIMARY_IFACE} adaptive-rx on rx-usecs 250${NC}"
        NIC_MISSING_COALESCING=true
        if cmd_exists ethtool; then
            COAL=$(ethtool -c "$PRIMARY_IFACE" 2>/dev/null || echo "")
            RX_USECS=$(echo "${COAL:-}" | awk '/rx-usecs:/{print $2}' || echo "0")
            ADAPTIVE=$(echo "${COAL:-}" | awk '/Adaptive RX:/{print $3}' || echo "off")
            if [ "${ADAPTIVE:-off}" != "on" ] && [ "${RX_USECS:-0}" -lt 100 ] 2>/dev/null; then
                issue "NIC interrupt coalescing not optimized — can cause hangs under e1000e high IRQ load"
                NIC_MISSING_COALESCING=true
            fi
        fi
    fi

    if cmd_exists ethtool; then
        ERRORS=$(ethtool -S "$PRIMARY_IFACE" 2>/dev/null \
                 | grep -iE "error|drop|miss|overflow|fifo" | grep -v ": 0$" || echo "")
        if [ -n "${ERRORS:-}" ]; then
            warning "NIC has non-zero error counters:"
            NIC_HAS_ERRORS=true
            echo "$ERRORS" | head -10 | while read -r line; do
                log "    ${YELLOW}${line}${NC}"
            done
        else
            check "NIC Errors" "ok" "All counters zero"
        fi

        CUR_RX=$(ethtool -g "$PRIMARY_IFACE" 2>/dev/null \
                 | awk '/Current hardware/{f=1} f && /RX:/{print $2; exit}' || echo "?")
        MAX_RX=$(ethtool -g "$PRIMARY_IFACE" 2>/dev/null \
                 | awk '/Pre-set/{f=1} f && /RX:/{print $2; exit}' || echo "?")
        check "Ring Buffer" "ok" "RX: ${CUR_RX}/${MAX_RX}"

        SPEED=$(ethtool "$PRIMARY_IFACE" 2>/dev/null | awk '/Speed:/{print $2}' || echo "unknown")
        check "Link Speed" "ok" "${SPEED}"
    else
        log "  ${DIM}ethtool not installed — limited NIC diagnostics${NC}"
        log "  ${DIM}Install: sudo apt install ethtool  |  sudo dnf install ethtool  |  sudo pacman -S ethtool${NC}"
        # Fallback: sysfs link speed
        if [ -f "/sys/class/net/${PRIMARY_IFACE}/speed" ]; then
            SPEED=$(cat "/sys/class/net/${PRIMARY_IFACE}/speed" 2>/dev/null || echo "unknown")
            check "Link Speed" "ok" "${SPEED} Mbps (sysfs)"
        fi
    fi
else
    warning "Could not determine primary network interface"
fi

# ============================================================
# 6. IRQ DISTRIBUTION
# ============================================================
header "6. IRQ / INTERRUPT LOAD"

log "  ${DIM}Interrupt distribution across CPUs:${NC}"
IRQ_TOTAL=0
CPU_CORES_INT=${CPU_CORES:-1}
for cpu_n in $(seq 0 $((CPU_CORES_INT - 1))); do
    CPU_IRQ=$(awk -v col=$((cpu_n + 2)) '{sum += $col} END {print sum+0}' \
              /proc/interrupts 2>/dev/null || echo 0)
    log "    CPU${cpu_n}: ${CPU_IRQ}"
    IRQ_TOTAL=$((IRQ_TOTAL + CPU_IRQ))
done

if [ "${IRQ_TOTAL:-0}" -gt 0 ]; then
    for cpu_n in $(seq 0 $((CPU_CORES_INT - 1))); do
        CPU_IRQ=$(awk -v col=$((cpu_n + 2)) '{sum += $col} END {print sum+0}' \
                  /proc/interrupts 2>/dev/null || echo 0)
        PCT=0
        [ "$IRQ_TOTAL" -gt 0 ] 2>/dev/null && PCT=$(( CPU_IRQ * 100 / IRQ_TOTAL )) || true
        if [ "${PCT:-0}" -gt 80 ] 2>/dev/null; then
            warning "CPU${cpu_n} handles ${PCT}% of all interrupts — severe imbalance"
        fi
    done
fi

if [ -n "${PRIMARY_IFACE:-}" ]; then
    NIC_IRQS=$(grep -iE "${PRIMARY_IFACE}|${DRIVER:-NOMATCH}" \
               /proc/interrupts 2>/dev/null | head -5 || echo "")
    if [ -n "${NIC_IRQS:-}" ]; then
        log ""
        log "  ${DIM}NIC interrupt lines:${NC}"
        echo "$NIC_IRQS" | while read -r line; do
            log "    ${DIM}${line}${NC}"
        done
    fi
fi

if cmd_exists irqbalance; then
    if pgrep -x irqbalance >/dev/null 2>&1 || pgrep irqbalance >/dev/null 2>&1; then
        check "irqbalance" "ok" "Running"
    else
        warning "irqbalance installed but not running — all interrupts land on CPU0"
        IRQBALANCE_RUNNING=false
    fi
else
    warning "irqbalance not installed — all NIC interrupts handled by CPU0"
    IRQBALANCE_RUNNING=false
    log "  ${DIM}Install: $(_pkg irqbalance)${NC}"
fi

# ============================================================
# 7. KERNEL DIAGNOSTICS
# ============================================================
header "7. KERNEL DIAGNOSTICS"

KERNEL=$(uname -r 2>/dev/null || echo "unknown")
ARCH=$(uname -m 2>/dev/null || echo "unknown")
check "Kernel" "ok" "${KERNEL} (${ARCH})"

LOCKUPS=$(dmesg 2>/dev/null | grep -ciE "soft lockup|hard lockup|hung_task|rcu.*stall" || echo "0")
if [ "${LOCKUPS:-0}" -gt 0 ] 2>/dev/null; then
    issue "Found ${LOCKUPS} lockup/stall messages in dmesg — kernel was stuck!"
    dmesg 2>/dev/null | grep -iE "soft lockup|hard lockup|hung_task|rcu.*stall" | tail -5 | while read -r line; do
        log "    ${DIM}${line}${NC}"
    done || true
else
    check "Lockups" "ok" "No soft/hard lockups in dmesg"
fi

MCE=$(dmesg 2>/dev/null | grep -ciE "mce|machine check" || echo "0")
if [ "${MCE:-0}" -gt 0 ] 2>/dev/null; then
    issue "Found ${MCE} Machine Check Exceptions — possible hardware failure"
else
    check "MCE" "ok" "No machine check errors"
fi

# journalctl (systemd distros) or fall back to syslog/messages
if cmd_exists journalctl; then
    BOOT_COUNT=$(timed_cmd 8 "" journalctl --list-boots 2>/dev/null | wc -l || echo "1")
    check "Boot count" "ok" "${BOOT_COUNT} boots recorded"
    if [ "${BOOT_COUNT:-1}" -gt 1 ] 2>/dev/null; then
        PREV_CRASH=$(journalctl -b -1 --no-pager 2>/dev/null | tail -20 \
                     | grep -ciE "panic|oops|bug:|lockup|oom" || echo "0")
        if [ "${PREV_CRASH:-0}" -gt 0 ] 2>/dev/null; then
            warning "Previous boot had crash indicators — check: journalctl -b -1 | tail -50"
        fi
    fi
else
    for logfile in /var/log/syslog /var/log/messages /var/log/kern.log; do
        [ -f "$logfile" ] || continue
        PREV_CRASH=$(grep -ciE "panic|kernel bug|general protection" "$logfile" 2>/dev/null || echo "0")
        if [ "${PREV_CRASH:-0}" -gt 0 ] 2>/dev/null; then
            warning "Found ${PREV_CRASH} crash indicators in ${logfile}"
        else
            check "Crash log" "ok" "No panics found in ${logfile}"
        fi
        break
    done
fi

# ============================================================
# 8. CONNECTION TRACKING
# ============================================================
header "8. CONNECTION TRACKING"

CT_MAX=$(sysctl -n net.netfilter.nf_conntrack_max 2>/dev/null || echo "0")
CT_COUNT=$(sysctl -n net.netfilter.nf_conntrack_count 2>/dev/null || echo "0")
if [ "${CT_MAX:-0}" -gt 0 ] 2>/dev/null; then
    CT_PCT=$(( CT_COUNT * 100 / CT_MAX )) 2>/dev/null || CT_PCT=0
    check "Conntrack" \
        "$([ "${CT_PCT:-0}" -gt 90 ] && echo critical || ([ "${CT_PCT:-0}" -gt 70 ] && echo warn || echo ok))" \
        "${CT_COUNT}/${CT_MAX} (${CT_PCT}%)"
    if [ "${CT_PCT:-0}" -gt 90 ] 2>/dev/null; then
        issue "Conntrack table nearly full — new connections will be DROPPED silently"
    fi
else
    log "  ${DIM}nf_conntrack module not loaded — no conntrack data${NC}"
fi

CT_DROPS=$(dmesg 2>/dev/null | grep -ciE "nf_conntrack.*table full|dropping packet" || echo "0")
if [ "${CT_DROPS:-0}" -gt 0 ] 2>/dev/null; then
    issue "Found ${CT_DROPS} conntrack table full messages — connections were dropped!"
fi

# ============================================================
# 9. WIREGUARD & MYSTERIUM
# ============================================================
header "9. WIREGUARD & MYSTERIUM"

WG_COUNT=$(ip link show type wireguard 2>/dev/null | grep -c "mtu" || echo "0")
MYST_IFACES=$(ip link 2>/dev/null | grep -cE "myst|: wg" || echo "0")
check "WireGuard tunnels" "ok" "${WG_COUNT} WG interfaces, ${MYST_IFACES} myst/wg links"

# Find Mysterium process — multiple name patterns
MYST_PID=""
for _pat in "^myst$" "mysterium-node" "/usr/bin/myst"; do
    MYST_PID=$(pgrep -f "$_pat" 2>/dev/null | head -1 || echo "")
    [ -n "${MYST_PID:-}" ] && break
done

if [ -n "${MYST_PID:-}" ]; then
    MYST_MEM=$(ps -p "$MYST_PID" -o rss= 2>/dev/null | xargs || echo "0")
    MYST_MEM_MB=$(( ${MYST_MEM:-0} / 1024 ))
    MYST_CPU=$(ps -p "$MYST_PID" -o %cpu= 2>/dev/null | xargs || echo "0")
    MYST_THREADS=$(ls "/proc/${MYST_PID}/task" 2>/dev/null | wc -l || echo "?")
    MYST_FDS=$(ls "/proc/${MYST_PID}/fd" 2>/dev/null | wc -l || echo "?")
    check "Mysterium Process" "ok" \
        "PID=${MYST_PID}, Mem=${MYST_MEM_MB}MB, CPU=${MYST_CPU}%, Threads=${MYST_THREADS}, FDs=${MYST_FDS}"
    if [ "${MYST_MEM_MB:-0}" -gt 512 ] 2>/dev/null; then warning "Mysterium using ${MYST_MEM_MB} MB — might be leaking memory"; fi
    if [ "${MYST_FDS:-0}" -gt 5000 ] 2>/dev/null; then warning "Mysterium has ${MYST_FDS} open file descriptors — possible FD leak"; fi
    # Read FD limit from /proc — no ulimit subshell needed
    FD_SOFT=$(awk '/Max open files/{print $4}' "/proc/${MYST_PID}/limits" 2>/dev/null || echo "?")
    check "FD Limit" "ok" "soft=${FD_SOFT}, used=${MYST_FDS:-?}"
else
    issue "Mysterium node process not found"
fi

# Service status — systemd or OpenRC
MYST_SVC="unknown"
if cmd_exists systemctl; then
    MYST_SVC=$(systemctl is-active mysterium-node 2>/dev/null || echo "inactive")
elif cmd_exists rc-service; then
    MYST_SVC=$(rc-service mysterium-node status 2>/dev/null | grep -oiE "started|stopped" | head -1 || echo "unknown")
fi
check "Service status" \
    "$([ "${MYST_SVC}" = "active" ] || [ "${MYST_SVC}" = "started" ] && echo ok || echo critical)" \
    "${MYST_SVC}"

# ============================================================
# 10. SYSTEM LOAD & PRESSURE
# ============================================================
header "10. SYSTEM LOAD & PRESSURE"

LOAD=$(cat /proc/loadavg 2>/dev/null || echo "0.0 0.0 0.0 0/0 0")
LOAD1=$(echo "$LOAD" | awk '{print $1}')
LOAD5=$(echo "$LOAD" | awk '{print $2}')
LOAD15=$(echo "$LOAD" | awk '{print $3}')
check "Load Average" "ok" "1m=${LOAD1} 5m=${LOAD5} 15m=${LOAD15} (${CPU_CORES} cores)"
LOAD1_INT=${LOAD1%%.*}
if   [ "${LOAD1_INT:-0}" -gt "$(( CPU_CORES * 3 ))" ] 2>/dev/null; then issue   "Load ${LOAD1} is >3x CPU count — severely overloaded"
elif [ "${LOAD1_INT:-0}" -gt "$(( CPU_CORES * 2 ))" ] 2>/dev/null; then warning "Load ${LOAD1} is >2x CPU count"
fi

for resource in cpu io memory; do
    [ -f "/proc/pressure/${resource}" ] || continue
    SOME=$(awk '/^some/{for(i=1;i<=NF;i++) if($i~/^avg10=/) {split($i,a,"="); print a[2]}}' \
           "/proc/pressure/${resource}" 2>/dev/null || echo "?")
    FULL=$(awk '/^full/{for(i=1;i<=NF;i++) if($i~/^avg10=/) {split($i,a,"="); print a[2]}}' \
           "/proc/pressure/${resource}" 2>/dev/null || echo "n/a")
    check "PSI ${resource}" "ok" "some=${SOME}% full=${FULL}%"
done

# ============================================================
# 11. TOOLKIT RESOURCE USAGE
# ============================================================
header "11. TOOLKIT RESOURCE USAGE"

TOOLKIT_PROCS=$(ps aux 2>/dev/null | grep -E "app\.py|dashboard\.py|gunicorn|vite" | grep -v grep || echo "")
if [ -n "${TOOLKIT_PROCS:-}" ]; then
    log "  ${DIM}Toolkit processes:${NC}"
    echo "$TOOLKIT_PROCS" | while read -r line; do
        PCPU=$(echo "$line" | awk '{print $3}')
        PMEM=$(echo "$line" | awk '{print $4}')
        PCMD=$(echo "$line" | awk '{for(i=11;i<=NF;i++) printf "%s ",$i; print ""}' | cut -c1-80)
        log "    CPU: ${PCPU}%  MEM: ${PMEM}%  ${PCMD}"
    done
else
    log "  ${DIM}No toolkit processes running${NC}"
fi

# ============================================================
# 12. STRESS TEST (optional)
# ============================================================
if [ "$STRESS_MODE" = true ]; then
    header "12. STRESS TEST (monitoring for 60 seconds)"
    log "  ${YELLOW}Monitoring system under current load for 60 seconds...${NC}"
    log "  ${YELLOW}Watch for thermal spikes, memory growth, IRQ storms${NC}"
    log ""
    for i in $(seq 1 12); do
        sleep 5
        # Highest thermal zone temp
        TEMP="?"
        for tz in /sys/class/thermal/thermal_zone*/temp; do
            [ -f "$tz" ] || continue
            T=$(( $(cat "$tz" 2>/dev/null || echo 0) / 1000 ))
            [ "$T" -gt "${TEMP:-0}" ] 2>/dev/null && TEMP="$T" || true
        done
        M_USED=$(awk '/MemTotal/{t=$2} /MemAvailable/{a=$2} END{printf "%d",(t-a)/1024}' /proc/meminfo 2>/dev/null || echo "?")
        M_AVAIL=$(awk '/MemAvailable/{printf "%d",$2/1024}' /proc/meminfo 2>/dev/null || echo "?")
        S_USED=$(awk '/SwapFree/{f=$2} /SwapTotal/{t=$2} END{printf "%d",(t-f)/1024}' /proc/meminfo 2>/dev/null || echo "?")
        L=$(awk '{print $1}' /proc/loadavg 2>/dev/null || echo "?")
        CT=$(sysctl -n net.netfilter.nf_conntrack_count 2>/dev/null || echo "?")
        log "  [${i}/12] T:${TEMP}°C  RAM:${M_USED}MB(${M_AVAIL}free)  Swap:${S_USED}MB  Load:${L}  CT:${CT}"
        if [ "${TEMP:-0}" -gt 90 ] 2>/dev/null; then
            issue "TEMPERATURE HIT ${TEMP}°C during monitoring — likely thermal overload!"
        fi
    done
fi

# ============================================================
# SUMMARY & RECOMMENDATIONS
# ============================================================
header "SUMMARY"

if [ "${ISSUES:-0}" -gt 0 ]; then
    log "  ${RED}${BOLD}${ISSUES} ISSUE(S) found — address these first${NC}"
else
    log "  ${GREEN}${BOLD}No critical issues found${NC}"
fi
if [ "${WARNINGS:-0}" -gt 0 ]; then
    log "  ${YELLOW}${WARNINGS} warning(s) — see details above${NC}"
fi

# ── Recommendation engine ──────────────────────────────────────────────────────
# Each guide only prints when the relevant problem was actually detected.
# Install commands are auto-tailored to the detected package manager.
REC_COUNT=0

_rec() {
    REC_COUNT=$((REC_COUNT + 1))
    log ""
    log "  ${CYAN}${BOLD}── ${REC_COUNT}. $1 ──${NC}"
    shift
    for line in "$@"; do log "     ${line}"; done
}
_step() { log "     ${BOLD}Step $1:${NC} $2"; }
_cmd()  { log "       ${DIM}→ $1${NC}"; }
_note() { log "     ${YELLOW}Note:${NC} $1"; }

log ""
log "  ${DIM}OS: ${DISTRO_NAME}${NC}"
log ""

# ── 1. HIGH CPU TEMPERATURE ────────────────────────────────────────────────────
if [ -n "${CPU_TEMP:-}" ]; then
    TEMP_INT_S=${CPU_TEMP%%.*}
    if [ "${TEMP_INT_S:-0}" -gt 70 ] 2>/dev/null; then
        if [ "$IS_LAPTOP" = true ]; then
            _rec "HIGH CPU TEMPERATURE — ${CPU_TEMP}°C (laptop)"
            _step 1 "Clean fan vents and heatsink with compressed air"
            _step 2 "Check if CPU is actively throttling:"
            _cmd  "cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq"
            _step 3 "Install TLP for automatic power/thermal management:"
            _cmd  "$(_pkg tlp tlp tlp tlp)"
            _cmd  "sudo systemctl enable --now tlp"
            _step 4 "Limit max CPU frequency to reduce heat output:"
            _cmd  "$(_pkg linux-cpupower kernel-tools cpupower cpufrequtils)"
            _cmd  "sudo cpupower frequency-set -u 2400MHz"
            _step 5 "Reapply thermal paste if machine is 3+ years old"
            _note "Sustained temps above 85°C cause Linux to throttle the CPU, reducing" \
                  "VPN tunnel throughput by up to 50% and causing session drops."
        else
            _rec "HIGH CPU TEMPERATURE — ${CPU_TEMP}°C (desktop/server)"
            _step 1 "Check CPU cooler seating and that the fan is spinning"
            _step 2 "Clean dust from heatsink, CPU fan and case fans"
            _step 3 "Reapply thermal paste — replace every 3-5 years"
            _step 4 "Add case fans or improve airflow direction"
            _step 5 "Verify performance governor is active:"
            _cmd  "$(_pkg linux-cpupower kernel-tools cpupower cpufrequtils)"
            _cmd  "sudo cpupower frequency-set -g performance"
            _note "Thermal throttling reduces VPN throughput and causes session drops."
        fi
    fi
fi

# ── 2. MISSING TEMPERATURE MONITORING ─────────────────────────────────────────
if [ "${MISSING_SENSORS:-false}" = true ]; then
    _rec "TEMPERATURE MONITORING NOT AVAILABLE"
    _step 1 "Install lm-sensors:"
    _cmd  "$(_pkg lm-sensors lm_sensors lm_sensors lm-sensors)"
    _step 2 "Run sensor detection once (answer YES to defaults):"
    _cmd  "sudo sensors-detect --auto"
    _step 3 "Verify sensors are working:"
    _cmd  "sensors"
    _step 4 "If no output, load modules manually:"
    _cmd  "sudo modprobe coretemp   # Intel CPUs"
    _cmd  "sudo modprobe k10temp    # AMD CPUs"
    _cmd  "sudo modprobe dell_smm   # Dell laptops"
    _note "Without temperature data you cannot detect thermal throttling on your node."
fi

# ── 3. NO SWAP ────────────────────────────────────────────────────────────────
if [ "${TOTAL_SWAP:-0}" -eq 0 ] 2>/dev/null; then
    _rec "NO SWAP CONFIGURED"
    _step 1 "Create a 4 GB swapfile (works on all distros):"
    _cmd  "sudo fallocate -l 4G /swapfile"
    _cmd  "# If fallocate fails (btrfs/zfs): sudo dd if=/dev/zero of=/swapfile bs=1M count=4096"
    _cmd  "sudo chmod 600 /swapfile"
    _cmd  "sudo mkswap /swapfile && sudo swapon /swapfile"
    _step 2 "Make permanent across reboots:"
    _cmd  "echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab"
    _step 3 "Tune swappiness for VPN workloads:"
    _cmd  "echo 'vm.swappiness=60' | sudo tee /etc/sysctl.d/99-myst.conf"
    _cmd  "sudo sysctl --system"
    _note "Each WireGuard tunnel uses ~2-5 MB RAM. 50 tunnels = ~250 MB. Swap prevents" \
          "the kernel from killing myst during memory spikes."
elif [ "${SWAP_PCT:-0}" -gt 30 ] 2>/dev/null; then
    _rec "MEMORY PRESSURE — swap ${SWAP_PCT}% used"
    _step 1 "Check what is consuming memory:"
    _cmd  "ps aux --sort=-%mem | head -15"
    _step 2 "Close non-essential apps — Brave/Chrome use 300-700 MB per renderer tab"
    _step 3 "Expand swap if it is under 4 GB:"
    _cmd  "sudo swapoff /swapfile"
    _cmd  "sudo fallocate -l 4G /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile"
    _step 4 "Tune swappiness:"
    _cmd  "sudo sysctl -w vm.swappiness=60"
    _note "Swap above 50% means your node is close to running out of memory entirely."
fi

# ── 4. NIC INTERRUPT PROBLEM ──────────────────────────────────────────────────
if [ "${NIC_MISSING_COALESCING:-false}" = true ]; then
    _rec "NIC INTERRUPT PROBLEM — ${PRIMARY_IFACE:-eno1} (${DRIVER:-e1000e} driver)"
    _step 1 "Enable adaptive interrupt coalescing (batches interrupts under load):"
    _cmd  "sudo ethtool -C ${PRIMARY_IFACE:-eno1} adaptive-rx on rx-usecs 250 tx-usecs 250"
    _step 2 "Enable RPS to spread NIC processing across all CPU cores:"
    _cmd  "CORES=\$(nproc)"
    _cmd  "MASK=\$(python3 -c \"print(hex((1<<\$CORES)-1)[2:])\" 2>/dev/null || printf '%x' \$(( (1<<\$CORES)-1 )))"
    _cmd  "echo \$MASK | sudo tee /sys/class/net/${PRIMARY_IFACE:-eno1}/queues/rx-0/rps_cpus"
    _step 3 "Make persistent across reboots:"
    if command -v systemctl >/dev/null 2>&1; then
        _cmd  "sudo tee /etc/systemd/system/myst-nic-tune.service << 'EOF'"
        _cmd  "[Unit]"
        _cmd  "Description=Mysterium NIC tuning for ${PRIMARY_IFACE:-eno1}"
        _cmd  "After=network.target"
        _cmd  "[Service]"
        _cmd  "Type=oneshot"
        _cmd  "RemainAfterExit=yes"
        _cmd  "ExecStart=/sbin/ethtool -C ${PRIMARY_IFACE:-eno1} adaptive-rx on rx-usecs 250"
        _cmd  "[Install]"
        _cmd  "WantedBy=multi-user.target"
        _cmd  "EOF"
        _cmd  "sudo systemctl enable --now myst-nic-tune.service"
    elif command -v rc-update >/dev/null 2>&1; then
        _cmd  "echo 'ethtool -C ${PRIMARY_IFACE:-eno1} adaptive-rx on rx-usecs 250' | sudo tee /etc/local.d/myst-nic.start"
        _cmd  "sudo chmod +x /etc/local.d/myst-nic.start && sudo rc-update add local default"
    else
        _cmd  "echo 'ethtool -C ${PRIMARY_IFACE:-eno1} adaptive-rx on rx-usecs 250' | sudo tee -a /etc/rc.local"
    fi
    _note "Intel e1000e (82579/82578/82574/82573) generates one interrupt per packet at" \
          "default settings. Under 50+ VPN tunnels this saturates CPU0, causing dropped" \
          "packets and high latency. Adaptive coalescing batches interrupts intelligently."
fi

# ── 5. NIC ERROR COUNTERS ─────────────────────────────────────────────────────
if [ "${NIC_HAS_ERRORS:-false}" = true ]; then
    _rec "NIC ERROR COUNTERS — ${PRIMARY_IFACE:-eno1}"
    _step 1 "View all non-zero counters:"
    _cmd  "sudo ethtool -S ${PRIMARY_IFACE:-eno1} | grep -v ': 0'"
    _step 2 "rx_csum_offload_errors — disable hardware checksumming:"
    _cmd  "sudo ethtool -K ${PRIMARY_IFACE:-eno1} rx off"
    _step 3 "tx_dropped — increase TX ring buffer:"
    _cmd  "sudo ethtool -G ${PRIMARY_IFACE:-eno1} tx 4096"
    _step 4 "Verify cable and link health:"
    _cmd  "sudo ethtool ${PRIMARY_IFACE:-eno1} | grep -E 'Speed|Duplex|Link detected'"
    _note "Non-zero NIC errors cause silent packet drops — consumers see connection failures" \
          "with no corresponding error in myst logs."
fi

# ── 6. IRQBALANCE NOT RUNNING ─────────────────────────────────────────────────
if [ "${IRQBALANCE_RUNNING:-true}" = false ]; then
    _rec "IRQ BALANCE — all interrupts on one CPU core"
    if ! command -v irqbalance >/dev/null 2>&1; then
        _step 1 "Install irqbalance:"
        _cmd  "$(_pkg irqbalance)"
    fi
    _step 2 "Enable and start irqbalance:"
    if command -v systemctl >/dev/null 2>&1; then
        _cmd  "sudo systemctl enable --now irqbalance"
        _cmd  "sudo systemctl status irqbalance"
    elif command -v rc-update >/dev/null 2>&1; then
        _cmd  "sudo rc-service irqbalance start && sudo rc-update add irqbalance default"
    else
        _cmd  "sudo service irqbalance start"
    fi
    _note "Without irqbalance all NIC interrupts land on CPU0. Under VPN load this core" \
          "saturates while the others idle — causing packet drops and latency spikes."
fi

# ── 7. CONNTRACK TABLE PRESSURE ───────────────────────────────────────────────
if [ -n "${CT_MAX:-}" ] && [ "${CT_MAX:-0}" -gt 0 ] 2>/dev/null \
   && [ -n "${CT_PCT:-}" ] && [ "${CT_PCT:-0}" -gt 50 ] 2>/dev/null; then
    _rec "CONNTRACK TABLE — ${CT_PCT}% full"
    _step 1 "Increase the table immediately:"
    _cmd  "sudo sysctl -w net.netfilter.nf_conntrack_max=524288"
    _step 2 "Persist across reboots:"
    _cmd  "echo 'net.netfilter.nf_conntrack_max=524288' | sudo tee /etc/sysctl.d/99-myst-conntrack.conf"
    _cmd  "sudo sysctl --system"
    _step 3 "Shorten timeouts to free entries faster:"
    _cmd  "sudo sysctl -w net.netfilter.nf_conntrack_tcp_timeout_time_wait=30"
    _cmd  "sudo sysctl -w net.netfilter.nf_conntrack_tcp_timeout_close_wait=15"
    _step 4 "Monitor in real time:"
    _cmd  "watch -n1 'cat /proc/sys/net/netfilter/nf_conntrack_count'"
    _note "If the table reaches 100%, new connections are silently dropped." \
          "Consumers see failures; myst logs show nothing."
fi

# ── 8. CPU GOVERNOR / SCALING PROBLEM ────────────────────────────────────────
if [ "${CPU_THROTTLED:-false}" = true ]; then
    if [ "${TEMP_INT_S:-0}" -le 70 ] 2>/dev/null; then
        _rec "CPU FREQUENCY SCALING — running below maximum speed"
        _step 1 "Check current governor and frequency:"
        _cmd  "cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"
        _cmd  "grep 'cpu MHz' /proc/cpuinfo | sort -rn | head -4"
        _step 2 "Install cpupower tools:"
        _cmd  "$(_pkg linux-cpupower kernel-tools cpupower cpufrequtils)"
        _step 3 "Set performance governor:"
        _cmd  "sudo cpupower frequency-set -g performance"
        _step 4 "Verify all cores are at full speed:"
        _cmd  "grep 'cpu MHz' /proc/cpuinfo | sort -rn"
        _step 5 "Persist on reboot:"
        _cmd  "sudo systemctl enable --now cpupower  2>/dev/null  # if unit available"
        _cmd  "# OR: echo 'GOVERNOR=performance' >> /etc/default/cpufrequtils"
        _note "The powersave governor can halve your VPN throughput at idle."
    fi
fi

# ── Nothing found ─────────────────────────────────────────────────────────────
if [ "${REC_COUNT:-0}" -eq 0 ]; then
    log "  ${DIM}No specific recommendations — system looks healthy for VPN node operation.${NC}"
fi

log ""
log "  Full report: ${REPORT_FILE}"
[ "$STRESS_MODE" = false ] && log "  Stress test: sudo bash bin/diagnose.sh --stress"
log "  Apply fixes: sudo bash bin/diagnose.sh --fix"
log ""
# ============================================================
# --fix  (sudo bash bin/diagnose.sh --fix)
# ============================================================
# Applies targeted fixes for issues found in the diagnostic.
# Shows each command before running it — nothing executes
# without explicit y/N confirmation.
# ============================================================
if [[ "${1:-}" == "--fix" ]]; then

    RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
    CYAN='\033[96m'; BOLD='\033[1m'; DIM='\033[2m'; NC='\033[0m'

    if [ "${EUID:-$(id -u)}" -ne 0 ]; then
        echo -e "${RED}Run as root: sudo bash bin/diagnose.sh --fix${NC}"
        exit 1
    fi

    cmd_exists() { command -v "$1" >/dev/null 2>&1; }

    echo ""
    printf "${CYAN}${BOLD}╔%s╗${NC}\n" "$(printf '═%.0s' $(seq 1 68))"
    printf "${CYAN}${BOLD}║  %-66s║${NC}\n" "Mysterium Node — Fix Wizard"
    printf "${CYAN}${BOLD}╚%s╝${NC}\n" "$(printf '═%.0s' $(seq 1 68))"
    echo ""
    echo -e "  ${DIM}Each fix shows the exact command and asks y/N. Nothing runs without your approval.${NC}"
    echo ""

    APPLIED=0

    # Detect primary NIC and driver
    IFACE=""
    cmd_exists ip && IFACE=$(ip route show default 2>/dev/null | grep -oP 'dev \K\S+' | head -1 || true)
    [ -z "$IFACE" ] && IFACE=$(awk 'NR>1 && $2=="00000000"{print $1;exit}' /proc/net/route 2>/dev/null || echo "eno1")
    DRIVER=$(cmd_exists ethtool && ethtool -i "$IFACE" 2>/dev/null | awk '/^driver:/{print $2}' || echo "")
    CORES=$(nproc 2>/dev/null || echo "4")

    # PKG_MGR
    PKG_MGR=""
    cmd_exists apt-get && PKG_MGR="apt"
    cmd_exists dnf     && [ -z "$PKG_MGR" ] && PKG_MGR="dnf"
    cmd_exists yum     && [ -z "$PKG_MGR" ] && PKG_MGR="yum"
    cmd_exists pacman  && [ -z "$PKG_MGR" ] && PKG_MGR="pacman"
    cmd_exists apk     && [ -z "$PKG_MGR" ] && PKG_MGR="apk"

    echo -e "  ${DIM}NIC: ${IFACE} (${DRIVER:-unknown}) | Cores: ${CORES} | PKG: ${PKG_MGR:-unknown}${NC}"
    echo ""

    # ── Fix helper ────────────────────────────────────────────
    # offer_fix "Title" "description line1\nline2" "already_ok_check" "command_to_run"
    offer_fix() {
        local title="$1" desc="$2" check_cmd="$3" fix_cmd="$4"
        echo -e "  ${CYAN}${BOLD}▸ ${title}${NC}"
        echo -e "  ${DIM}${desc}${NC}"
        echo ""
        if [ -n "$check_cmd" ] && eval "$check_cmd" >/dev/null 2>&1; then
            echo -e "  ${GREEN}✓ Already applied${NC}"
            echo ""
            return 0
        fi
        echo -e "  Command: ${BOLD}${fix_cmd}${NC}"
        echo ""
        read -p "  Apply? [y/N]: " -r -n 1; echo
        if [[ ${REPLY:-n} =~ ^[Yy]$ ]]; then
            eval "$fix_cmd" && echo -e "  ${GREEN}✓ Applied${NC}" || echo -e "  ${RED}✗ Failed${NC}"
            APPLIED=$((APPLIED + 1))
        else
            echo -e "  ${DIM}Skipped${NC}"
        fi
        echo ""
    }

    # ── Fix 1: CPU Performance Governor ──────────────────────
    CUR_GOV=$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null || echo "unknown")
    CUR_MHZ=$(awk '{printf "%d", $1/1000}' /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq 2>/dev/null || echo "?")
    MAX_MHZ=$(awk '{printf "%d", $1/1000}' /sys/devices/system/cpu/cpu0/cpufreq/scaling_max_freq 2>/dev/null || echo "?")
    offer_fix \
        "CPU Performance Governor" \
        "Current governor: ${CUR_GOV} (running at ${CUR_MHZ}/${MAX_MHZ} MHz)\nSwitches all ${CORES} cores to 'performance' — runs at full speed, improves VPN throughput.\nNote: reverts on reboot. To persist, add to /etc/rc.local or a systemd unit." \
        "[ \"\$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null)\" = 'performance' ]" \
        "for g in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do echo performance > \"\$g\"; done && echo '${CORES} cores set to performance'"

    # ── Fix 2: NIC Interrupt Coalescing (e1000e only) ─────────
    if [ "${DRIVER:-}" = "e1000e" ] && cmd_exists ethtool; then
        ADAPTIVE=$(ethtool -c "$IFACE" 2>/dev/null | awk '/Adaptive RX:/{print $3}' || echo "off")
        offer_fix \
            "NIC Interrupt Coalescing — ${IFACE} (e1000e)" \
            "Adaptive RX is currently: ${ADAPTIVE}\nEnables adaptive coalescing (rx-usecs 250) on ${IFACE}.\nReduces interrupt rate under VPN load — fixes e1000e packet drops and latency spikes." \
            "ethtool -c ${IFACE} 2>/dev/null | grep -q 'Adaptive RX: on'" \
            "ethtool -C ${IFACE} adaptive-rx on rx-usecs 250 tx-usecs 250"
    fi

    # ── Fix 3: RX Checksum Offload Errors ─────────────────────
    if cmd_exists ethtool; then
        RX_CSUM=$(ethtool -S "$IFACE" 2>/dev/null | awk '/rx_csum_offload_errors/{print $2}' || echo "0")
        if [ "${RX_CSUM:-0}" -gt 0 ] 2>/dev/null; then
            offer_fix \
                "RX Checksum Offload — ${IFACE}" \
                "Detected ${RX_CSUM} rx_csum_offload_errors — NIC hardware failing checksum computation.\nDisables hardware RX checksum offload, forces software checksumming.\nStops packet drops caused by failed hardware offload." \
                "ethtool -k ${IFACE} 2>/dev/null | grep -q 'rx-checksumming: off'" \
                "ethtool -K ${IFACE} rx off"
        fi
    fi

    # ── Fix 4: RPS — Spread NIC load across all cores ─────────
    RPS_FILE="/sys/class/net/${IFACE}/queues/rx-0/rps_cpus"
    if [ -f "$RPS_FILE" ]; then
        RPS_MASK=$(python3 -c "print(hex((1<<${CORES})-1)[2:])" 2>/dev/null || printf '%x' $(( (1 << CORES) - 1 )) 2>/dev/null || echo "f")
        CUR_RPS=$(cat "$RPS_FILE" 2>/dev/null || echo "0")
        offer_fix \
            "Receive Packet Steering (RPS) — ${IFACE}" \
            "Current rps_cpus mask: ${CUR_RPS} — target: ${RPS_MASK} (all ${CORES} cores)\ne1000e has one interrupt queue — irqbalance cannot split it.\nRPS distributes packet processing across all cores in software.\nWithout this, one core handles all incoming VPN traffic." \
            "[ \"\$(cat ${RPS_FILE} 2>/dev/null | tr -d '\\n' | tr -d ' ')\" = '${RPS_MASK}' ]" \
            "echo ${RPS_MASK} > ${RPS_FILE} && echo 'RPS enabled — all ${CORES} cores active on ${IFACE}'"
    fi

    # ── Fix 5: Conntrack Table Size ───────────────────────────
    CT_MAX=$(sysctl -n net.netfilter.nf_conntrack_max 2>/dev/null || echo "0")
    if [ "${CT_MAX:-0}" -gt 0 ] && [ "${CT_MAX:-0}" -lt 524288 ] 2>/dev/null; then
        offer_fix \
            "Conntrack Table Size" \
            "Current nf_conntrack_max: ${CT_MAX} — target: 524288\nEach VPN tunnel + its connections uses conntrack entries.\nIf the table fills, new connections are silently dropped.\nAlso writes to /etc/sysctl.d/ so it persists across reboots." \
            "[ \"\$(sysctl -n net.netfilter.nf_conntrack_max 2>/dev/null)\" -ge 524288 ]" \
            "sysctl -w net.netfilter.nf_conntrack_max=524288 && echo 'net.netfilter.nf_conntrack_max=524288' > /etc/sysctl.d/99-myst-conntrack.conf && echo 'Applied and persisted'"
    fi

    # ── Fix 6: irqbalance not running ─────────────────────────
    if cmd_exists irqbalance; then
        if ! pgrep -x irqbalance >/dev/null 2>&1 && ! pgrep irqbalance >/dev/null 2>&1; then
            if cmd_exists systemctl; then
                offer_fix \
                    "irqbalance Service" \
                    "irqbalance is installed but not running.\nStarts and enables it to distribute IRQs across CPU cores.\nPrevents single-core saturation under heavy NIC interrupt load." \
                    "pgrep irqbalance >/dev/null 2>&1" \
                    "systemctl enable --now irqbalance"
            elif cmd_exists rc-service; then
                offer_fix \
                    "irqbalance Service (OpenRC)" \
                    "irqbalance is installed but not running (OpenRC system).\nStarts it and adds to default runlevel." \
                    "pgrep irqbalance >/dev/null 2>&1" \
                    "rc-service irqbalance start && rc-update add irqbalance default"
            fi
        fi
    fi

    # ── Summary ───────────────────────────────────────────────
    echo -e "${CYAN}${BOLD}═══════════════════════════════════════════════════════════${NC}"
    echo ""
    if [ "$APPLIED" -gt 0 ]; then
        echo -e "  ${GREEN}${BOLD}${APPLIED} fix(es) applied.${NC}"
        echo ""
        echo -e "  ${YELLOW}Note: CPU governor, RPS, and coalescing revert on reboot.${NC}"
        echo -e "  ${DIM}  To persist them, add commands to /etc/rc.local or a systemd unit.${NC}"
        echo ""
        echo -e "  ${DIM}Run diagnostics again to verify: sudo bash bin/diagnose.sh${NC}"
    else
        echo -e "  ${DIM}No fixes applied.${NC}"
    fi
    echo ""
    exit 0
fi
