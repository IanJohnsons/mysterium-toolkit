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

# ── Fix .git ownership if any part is foreign-owned ───────────────────────
# v1.4.5: this used to test only .git/objects. On the Pi it was .git/logs that
# root owned while objects was fine, so the check passed and the pull then died
# on "unable to append to .git/logs/refs/remotes/origin/dev". Test the whole
# tree instead — one find, first hit is enough.
if [ -d ".git" ] && [ -n "$_REAL_USER" ]; then
    _GIT_FOREIGN=$(find .git ! -user "$_REAL_USER" -print -quit 2>/dev/null)
    if [ -n "$_GIT_FOREIGN" ]; then
        echo -e "  ${YELLOW}⚠ .git contains files not owned by $_REAL_USER — fixing ownership...${NC}"
        echo -e "  ${DIM}    first offender: $_GIT_FOREIGN${NC}"
        $SUDO chown -R "$_REAL_USER:" ".git" 2>/dev/null || true
        if [ -n "$(find .git ! -user "$_REAL_USER" -print -quit 2>/dev/null)" ]; then
            echo -e "  ${RED}✗ could not restore .git ownership — run:${NC}"
            echo -e "  ${DIM}    sudo chown -R $_REAL_USER: $(pwd)${NC}"
        else
            echo -e "  ${GREEN}✓ .git ownership restored to $_REAL_USER${NC}"
        fi
    fi
fi

# ── Git safe.directory ────────────────────────────────────────────────────
# Git refuses to touch a repository owned by another user ("dubious ownership")
# even for read-only commands. Ownership is corrected above where possible; if
# git still objects, register the exception instead of leaving the operator to
# decode the message.
if ! git rev-parse --git-dir >/dev/null 2>&1; then
    if git rev-parse --git-dir 2>&1 | grep -q "dubious ownership"; then
        echo -e "  ${YELLOW}⚠ git reports dubious ownership — registering safe.directory${NC}"
        git config --global --add safe.directory "$(pwd)" 2>/dev/null || true
    fi
fi

# ── Pull latest code ──────────────────────────────────────────────────────
echo -e "  Pulling latest code..."
_SELF_BEFORE=$(md5sum "$0" 2>/dev/null | cut -d' ' -f1)
_PULL_OUT=$(git pull 2>&1)
_PULL_RC=$?
echo "$_PULL_OUT"
if [ $_PULL_RC -ne 0 ]; then
    # v1.4.5: this said "check your network or repo access" for every failure,
    # including two that had nothing to do with either — a root-owned .git and
    # git's dubious-ownership guard. Read the actual message and say what it is.
    if echo "$_PULL_OUT" | grep -qi "permission denied"; then
        echo -e "${RED}✗ git pull failed — permission denied inside .git${NC}"
        echo -e "  ${DIM}A sudo operation left files owned by another user. Fix with:${NC}"
        echo -e "  ${DIM}    sudo chown -R $_REAL_USER: $(pwd)${NC}"
    elif echo "$_PULL_OUT" | grep -qi "dubious ownership"; then
        echo -e "${RED}✗ git pull failed — git refuses this repository's ownership${NC}"
        echo -e "  ${DIM}    sudo chown -R $_REAL_USER: $(pwd)${NC}"
        echo -e "  ${DIM}    or: git config --global --add safe.directory $(pwd)${NC}"
    elif echo "$_PULL_OUT" | grep -qiE "local changes|would be overwritten|conflict"; then
        echo -e "${RED}✗ git pull failed — local changes block the update${NC}"
        echo -e "  ${DIM}Inspect them first, they may be yours:${NC}"
        echo -e "  ${DIM}    git status --short${NC}"
    elif echo "$_PULL_OUT" | grep -qiE "could not resolve host|network is unreachable|timed out|connection refused"; then
        echo -e "${RED}✗ git pull failed — cannot reach GitHub${NC}"
        echo -e "  ${DIM}    git remote -v${NC}"
    else
        echo -e "${RED}✗ git pull failed — see the git output above.${NC}"
    fi
    exit 1
fi
echo -e "  ${GREEN}✓ Code updated${NC}"
# Re-exec with new update.sh if the script itself changed
_SELF_AFTER=$(md5sum "$0" 2>/dev/null | cut -d' ' -f1)
if [ "$_SELF_BEFORE" != "$_SELF_AFTER" ]; then
    echo -e "  ${YELLOW}update.sh changed — restarting with new version...${NC}"
    exec "$0" "$@"
fi
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

# ── Migrate databases from config/ to backend/databases/ (v1.2.28+) ─────────
# Copies if src exists and has data, and dst is missing or smaller than src
_DB_MIGRATED=0
for _dbname in earnings_history.db sessions_history.db traffic_history.db quality_history.db system_metrics.db service_events.db; do
    _src="$TOOLKIT_DIR/config/$_dbname"
    _dst="$TOOLKIT_DIR/backend/databases/$_dbname"
    if [ -f "$_src" ]; then
        _src_size=$(stat -c%s "$_src" 2>/dev/null || echo 0)
        _dst_size=$(stat -c%s "$_dst" 2>/dev/null || echo 0)
        if [ "$_src_size" -gt 8192 ] && [ "$_src_size" -gt "$_dst_size" ]; then
            mkdir -p "$TOOLKIT_DIR/backend/databases"
            cp "$_src" "$_dst"
            echo -e "  ${GREEN}✓ Migrated $_dbname → backend/databases/ ($_src_size bytes)${NC}"
            _DB_MIGRATED=$((_DB_MIGRATED + 1))
        fi
    fi
done
[ "$_DB_MIGRATED" -gt 0 ] && echo -e "  ${GREEN}✓ Database migration complete ($_DB_MIGRATED files)${NC}"

# ── Fix ownership — git pull and sudo migrations can leave files root-owned ──
# v1.4.2: this used to cover config/ only. The databases moved to
# backend/databases/ in v1.2.28, and on at least one install a sudo migration
# left them owned by root while the service ran as a normal user. SQLite could
# not write, the database modules swallowed the error, and three databases
# recorded nothing for six weeks without a single visible warning.
_REAL_USER="${SUDO_USER:-$USER}"
if [ "$_REAL_USER" != "root" ]; then
    # dist/ is included since v1.4.4: a sudo build or a root-run update leaves the
    # built frontend owned by root, and the next build then fails with EACCES while
    # update.sh still reports success. The stale bundle keeps being served, so new
    # UI features silently never appear.
    for _d in "$TOOLKIT_DIR/config" "$TOOLKIT_DIR/backend" "$TOOLKIT_DIR/dist"; do
        if [ -d "$_d" ]; then
            # Looking only for root-owned files missed the case that actually
            # happened: a dist/ owned by neither root nor the service user, where
            # the check stayed quiet and the Vite build then failed on EACCES
            # while update.sh reported a successful run. Anything not owned by the
            # user the service runs as is a problem, whoever owns it.
            #
            # find exits non-zero when it cannot resolve the user name, and an
            # unresolvable name also makes it print nothing — which would read as
            # "all good" and reintroduce the silence this check exists to break.
            _bad=$(find "$_d" ! -user "$_REAL_USER" -print -quit 2>/dev/null)
            _find_rc=$?
            if [ "$_find_rc" -ne 0 ]; then
                echo -e "  ${YELLOW}⚠ could not check ownership of $(basename "$_d")/ — is '$_REAL_USER' a valid user?${NC}"
                _bad=""
            fi
            if [ -n "$_bad" ]; then
                # The success line used to print unconditionally after a chown that
                # swallowed its own errors, so a failed repair announced itself as a
                # completed one — and the build then failed further down for a reason
                # the operator had just been told was fixed.
                if $SUDO chown -R "$_REAL_USER:" "$_d" 2>/dev/null; then
                    echo -e "  ${GREEN}✓ $(basename "$_d")/ ownership corrected → $_REAL_USER${NC}"
                else
                    echo -e "  ${YELLOW}⚠ $(basename "$_d")/ has root-owned files and could not be corrected${NC}"
                    echo -e "  ${DIM}    sudo chown -R $_REAL_USER: $_d${NC}"
                fi
            fi
        fi
    done

    # Verify the databases are writable now — a database the service cannot write
    # to is a silent failure, so surface it here where the operator will see it.
    _DBDIR="$TOOLKIT_DIR/backend/databases"
    if [ -d "$_DBDIR" ]; then
        _unwritable=""
        for _db in "$_DBDIR"/*.db; do
            [ -e "$_db" ] || continue
            $SUDO -u "$_REAL_USER" test -w "$_db" 2>/dev/null || _unwritable="$_unwritable $(basename "$_db")"
        done
        if [ -n "$_unwritable" ]; then
            echo -e "  ${RED}✗ Not writable by $_REAL_USER:$_unwritable${NC}"
            echo -e "  ${DIM}    These databases will silently record nothing.${NC}"
            echo -e "  ${DIM}    Fix with: sudo chown -R $_REAL_USER: $_DBDIR${NC}"
        fi
    fi
fi

# ── Retention defaults are deliberately NOT written here ─────────────────────
# This block used to add a data_retention dict to setup.json when one was
# missing. scripts/setup_wizard.py stopped doing exactly that in v1.3.3, for a
# reason: pre-writing defaults makes every install look user-configured, and the
# Data Manager then shows retention windows the operator never chose. One Pi
# carried 30/90/365/730 purely because this ran on its first update.
#
# Data is kept forever until the operator saves retention in the Data Manager,
# which is also what sets data_retention_enabled. Leave it to them.


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
# v1.4.39: pip runs as "venv/bin/python -m pip", never as venv/bin/pip. The pip
# script carries the absolute path of the directory the venv was created in in
# its shebang; after the install directory was moved or renamed it failed with
# exit 127, its output in /dev/null, and set -e ended the whole update right
# there — no frontend build, no service update, no restart, no error message.
# The auto-update timer would have failed that way every hour. The python
# binary holds no path and keeps working wherever the directory goes.
_PIP_FAILED=0
_VENV_PY="$TOOLKIT_DIR/venv/bin/python"
if [ -x "$_VENV_PY" ]; then
    echo -e "  Updating Python packages..."
    mkdir -p logs
    _PIP_LOG="logs/pip_install.log"
    # A pip self-upgrade needs the network and is optional; its failure alone
    # is not a failed update. The requirements install is what matters.
    "$_VENV_PY" -m pip install --upgrade pip > "$_PIP_LOG" 2>&1 || true
    if "$_VENV_PY" -m pip install -r requirements.txt >> "$_PIP_LOG" 2>&1; then
        rm -f "$_PIP_LOG"
        echo -e "  ${GREEN}✓ Python packages updated${NC}"
    else
        _PIP_FAILED=1
        echo -e "  ${YELLOW}⚠ Python packages NOT updated — the backend keeps the packages it already had${NC}"
        _PIP_PAT="error|denied|No space|bad interpreter|not found"
        if grep -qiE "$_PIP_PAT" "$_PIP_LOG"; then
            grep -iE "$_PIP_PAT" "$_PIP_LOG" | tail -6
        else
            tail -6 "$_PIP_LOG"
        fi
        echo -e "  ${DIM}    Full log: $TOOLKIT_DIR/$_PIP_LOG${NC}"
    fi
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

# ── fail2ban filter migration (v1.4.4) ───────────────────────────────────────
# The old filter matched a web-server access log line. Since the dashboard moved
# from werkzeug to cheroot there is no access log, so the jail loaded, reported
# zero bans and detected nothing at all — worse than having no jail, because it
# looked like protection. Replace it with one that matches the line the
# application writes itself.
_F2B_FILTER="/etc/fail2ban/filter.d/mysterium-dashboard.conf"
if [ -f "$_F2B_FILTER" ] && grep -q '401' "$_F2B_FILTER" 2>/dev/null; then
    echo -e "  Updating fail2ban filter (the old one could not match anything)..."
    $SUDO tee "$_F2B_FILTER" > /dev/null << 'F2B_MIG_EOF'
[Definition]
failregex = ^.*Auth failed from <HOST>\s.*$
ignoreregex =
F2B_MIG_EOF
    if $SUDO systemctl reload fail2ban 2>/dev/null || $SUDO systemctl restart fail2ban 2>/dev/null; then
        sleep 2
        if $SUDO fail2ban-client status 2>/dev/null | grep -q "mysterium-dashboard"; then
            echo -e "  ${GREEN}✓ fail2ban filter updated — jail active${NC}"
        else
            echo -e "  ${YELLOW}⚠ Filter updated but the jail is not loaded${NC}"
            echo -e "  ${DIM}    Check: sudo journalctl -u fail2ban -n 20${NC}"
        fi
    else
        echo -e "  ${YELLOW}⚠ Filter updated but fail2ban could not be reloaded${NC}"
    fi
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
    # npm install output used to go to /dev/null. On one install the esbuild binary
    # crashed with SIGSEGV during install, so vite was never unpacked and the build
    # then failed with "Cannot find module .../vite.js". The six lines printed below
    # described that missing module — the actual cause was in the discarded output.
    mkdir -p logs
    _NPM_LOG="logs/npm_install.log"
    npm install --legacy-peer-deps > "$_NPM_LOG" 2>&1
    _NPM_RC=$?
    BUILD_OUT=$(npm run build 2>&1)
    set -e
    if [ "$_NPM_RC" -ne 0 ] && ! echo "$BUILD_OUT" | grep -q "built in"; then
        echo -e "  ${YELLOW}⚠ npm install failed (exit $_NPM_RC) — the build below could not use fresh packages${NC}"
        grep -iE "error|SIGSEGV|EACCES|ENOSPC" "$_NPM_LOG" | tail -8 || tail -8 "$_NPM_LOG"
        echo -e "  ${DIM}    Full log: $TOOLKIT_DIR/$_NPM_LOG${NC}"
    fi
    if [ -f "dist/index.html" ] && echo "$BUILD_OUT" | grep -q "built in"; then
        # Build succeeded into dist/ — rename to dist_new and swap
        mv dist dist_new 2>/dev/null && rm -rf dist/ 2>/dev/null || true
        mv dist_new dist 2>/dev/null || true
        rm -f "$_NPM_LOG"
        echo -e "  ${GREEN}✓ Frontend rebuilt${NC}"
    else
        # v1.4.4: this used to report success whenever dist/index.html existed,
        # even when the build had failed — so a stale bundle kept being served and
        # new UI features appeared to be missing with no error anywhere. The most
        # common cause is dist/ being owned by root while the build runs as the
        # service user, which fails with EACCES.
        echo -e "  ${YELLOW}⚠ Frontend build FAILED — the dashboard still serves the previous build${NC}"
        echo "$BUILD_OUT" | tail -6
        if echo "$BUILD_OUT" | grep -q "EACCES"; then
            echo -e "  ${YELLOW}    Permission problem on dist/. Fix with:${NC}"
            echo -e "  ${DIM}    sudo chown -R \$USER: $TOOLKIT_DIR/dist${NC}"
        fi
        [ -s "$_NPM_LOG" ] && echo -e "  ${DIM}    npm install log: $TOOLKIT_DIR/$_NPM_LOG${NC}"
    fi
    rm -f vite.config.js postcss.config.js tailwind.config.js package.json package-lock.json index.html
else
    echo -e "  ${YELLOW}⚠ npm not found — frontend not rebuilt${NC}"
fi

# ── Executable bits ───────────────────────────────────────────────────────
# A file copied by hand out of a browser download loses its executable bit, and
# git does not restore it on a file that is already tracked. bin/node_update.sh
# is invoked through sudo, so a missing bit shows up as a permission error with
# no obvious cause.
chmod +x "$TOOLKIT_DIR"/bin/*.sh 2>/dev/null || true
chmod +x "$TOOLKIT_DIR"/*.sh 2>/dev/null || true

# ── Update systemd service path and sudoers ───────────────────────────────
_SERVICE_FILE="/etc/systemd/system/mysterium-toolkit.service"
if [ -f "$_SERVICE_FILE" ]; then
    echo -e "  Updating systemd service..."
    _REAL_USER="${SUDO_USER:-$USER}"
    _REAL_HOME=$(getent passwd "$_REAL_USER" | cut -d: -f6)
    _VENV_PYTHON="$TOOLKIT_DIR/venv/bin/python"
    mkdir -p "$TOOLKIT_DIR/logs"
[ "$(stat -c '%U' "$TOOLKIT_DIR/logs" 2>/dev/null)" = "root" ] && $SUDO chown -R "$_REAL_USER:" "$TOOLKIT_DIR/logs" 2>/dev/null || true

    _MYST_SVC=""
    # systemd needs the unit suffix here. Written without it, the dependency is
    # refused outright — `systemd-analyze verify` reports "Failed to add
    # dependency on mysterium-node, ignoring: Invalid argument" — and the toolkit
    # is then free to start before the node it monitors, with nothing in the
    # startup output to say so.
    #
    # The loop below matches on a substring of `systemctl list-units`, so it also
    # matched the bare name; appending .service makes the result usable.
    for _svc in mysterium-node myst mysterium; do
        if systemctl list-units --all --no-legend 2>/dev/null | grep -q "^.*${_svc}.service"; then
            _MYST_SVC="${_svc}.service"
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
StandardOutput=journal
StandardError=journal
Environment=HOME=$_REAL_HOME

[Install]
WantedBy=multi-user.target
UNIT_EOF
    $SUDO systemctl daemon-reload
    echo -e "  ${GREEN}✓ Systemd service updated${NC}"

fi

# ── Migrate: move toolkit jail from jail.local block → standalone jail.d file ──
# Older versions wrote a managed block into jail.local. We now use an isolated
# jail.d file that cannot conflict with a user's jail.local. Strip the old block;
# the jail.d file itself is (re)written by the backend/setup when fail2ban is used.
_F2B_LOCAL="/etc/fail2ban/jail.local"
_BLOCK_START="# --- Mysterium Toolkit managed jails ---"
_BLOCK_END="# --- End Mysterium Toolkit ---"
if [ -f "$_F2B_LOCAL" ] && $SUDO grep -q "$_BLOCK_START" "$_F2B_LOCAL" 2>/dev/null; then
    $SUDO sed -i "/$_BLOCK_START/,/$_BLOCK_END/d" "$_F2B_LOCAL" 2>/dev/null || true
    $SUDO fail2ban-client reload >/dev/null 2>&1 || true
    echo -e "  ${GREEN}✓ Migrated: moved toolkit jail out of jail.local (now in jail.d)${NC}"
fi

# ── Sudoers update — always runs, regardless of autostart ─────────────────
# Runs unconditionally so fail2ban and other new permissions reach all users
_REAL_USER="${SUDO_USER:-$USER}"
_SUDOERS_FILE="/etc/sudoers.d/mysterium-toolkit"
# Write sudoers via heredoc — multi-line format required for Parrot OS and
# other security-hardened Debian distros that reject single-line sudoers content.
_SUDOERS_NEW=$(cat << 'SUDOERS_CONTENT_EOF'
# Mysterium Toolkit — passwordless sudo for specific commands only
# Generated by update.sh — do not edit manually, re-run update.sh to update
# Disable use_pty so sudo works from systemd timers and non-interactive shells (e.g. Parrot OS)
SUDOERS_CONTENT_EOF
)
_SUDOERS_NEW="${_SUDOERS_NEW}
Defaults:${_REAL_USER} !use_pty
#
${_REAL_USER} ALL=(ALL) NOPASSWD: \
  ${TOOLKIT_DIR}/update.sh, \
  ${TOOLKIT_DIR}/bin/node_update.sh, \
  /sbin/sysctl, /usr/sbin/sysctl, \
  /usr/sbin/ethtool, \
  /usr/sbin/conntrack, \
  /usr/bin/wg show*, /usr/sbin/wg show*, \
  /sbin/modprobe, /usr/sbin/modprobe, \
  /bin/bash, /usr/bin/bash, \
  /bin/cat, /usr/bin/cat, \
  /usr/local/bin/mysterium-rps-watcher.sh, \
  /usr/local/bin/mysterium-rps-setup.sh, \
  /usr/bin/tee /etc/sysctl.d/*, \
  /usr/bin/tee /etc/modules-load.d/*, \
  /usr/bin/tee /sys/module/nf_conntrack/parameters/hashsize, \
  /usr/bin/tee /usr/local/bin/*, \
  /usr/bin/tee /etc/systemd/system/mysterium-*.service, \
  /usr/bin/tee /etc/systemd/system/mysterium-*.timer, \
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
  /bin/systemctl reset-failed mysterium-toolkit, \
  /usr/bin/systemctl start mysterium-*, \
  /usr/bin/systemctl stop mysterium-*, \
  /usr/bin/systemctl restart mysterium-*, \
  /usr/bin/systemctl enable mysterium-*, \
  /usr/bin/systemctl disable mysterium-*, \
  /usr/bin/systemctl enable irqbalance, \
  /usr/bin/systemctl start irqbalance, \
  /usr/bin/systemctl daemon-reload, \
  /usr/bin/systemctl reset-failed mysterium-toolkit, \
  /usr/bin/cpupower frequency-set, \
  /usr/bin/update-alternatives --set iptables *, \
  /usr/bin/update-alternatives --set ip6tables *, \
  /usr/bin/fallocate, \
  /bin/dd if=/dev/zero *, \
  /usr/bin/chmod 600 *, \
  /sbin/mkswap *, /usr/sbin/mkswap *, \
  /sbin/swapon *, /usr/bin/swapon *, \
  /bin/rm /swapfile, /usr/bin/rm /swapfile, \
  /usr/sbin/ufw, \
  /usr/sbin/iptables, /sbin/iptables, \
  /usr/sbin/iptables-legacy, /sbin/iptables-legacy, \
  /usr/sbin/iptables-nft, \
  /usr/sbin/ip6tables, /sbin/ip6tables, \
  /usr/sbin/nft, /sbin/nft, \
  /usr/bin/tee /sys/devices/system/cpu/*/cpufreq/scaling_governor, \
  /usr/bin/cpupower, \
  /usr/bin/fail2ban-client, /usr/local/bin/fail2ban-client, /bin/fail2ban-client, \
  /usr/bin/tee /etc/fail2ban/jail.d/mysterium-toolkit.conf, \
  /usr/bin/tee /etc/fail2ban/filter.d/*, \
  /usr/bin/tee /etc/sudoers.d/mysterium-toolkit, \
  /usr/bin/chmod 440 /etc/sudoers.d/mysterium-toolkit, \
  /usr/sbin/visudo -c -f /etc/sudoers.d/mysterium-toolkit, \
  /usr/bin/rm -f /etc/sudoers.d/mysterium-toolkit"
_SUDOERS_CURRENT=""
if [ -f "$_SUDOERS_FILE" ]; then
    _SUDOERS_CURRENT=$(cat "$_SUDOERS_FILE" 2>/dev/null || true)
fi
if [ "$_SUDOERS_NEW" != "$_SUDOERS_CURRENT" ]; then
    printf '%s\n' "$_SUDOERS_NEW" | $SUDO tee "$_SUDOERS_FILE" > /dev/null
    $SUDO chmod 440 "$_SUDOERS_FILE"
    if $SUDO visudo -c -f "$_SUDOERS_FILE" >/dev/null 2>&1; then
        echo -e "  ${GREEN}✓ Sudoers updated — health fixes and firewall access enabled${NC}"
    else
        $SUDO rm -f "$_SUDOERS_FILE"
        echo -e "  ${YELLOW}⚠ Sudoers validation failed — skipped${NC}"
    fi
else
    echo -e "  ${DIM}  Sudoers unchanged${NC}"
fi

# ── Auto-update wrapper — always rewrite so path is correct ──────────────
# The wrapper is always rewritten on every update.sh run so that:
#   1. A broken wrapper from an older install gets fixed automatically
#   2. If the toolkit moved to a different directory the path stays correct
_WRAPPER="/usr/local/bin/mysterium-toolkit-update-check.sh"
if command -v systemctl &>/dev/null; then
    _REAL_USER="${SUDO_USER:-$USER}"
    $SUDO tee "$_WRAPPER" > /dev/null << WRAPPER_EOF
#!/bin/bash
# Auto-generated by update.sh — do not edit manually
CURRENT=\$(cat "$TOOLKIT_DIR/VERSION" 2>/dev/null)
# v1.4.0: compare against the branch this install is on, not always main. An
# install on a test branch used to see main's version number and update forever.
BRANCH=\$(cd "$TOOLKIT_DIR" && git rev-parse --abbrev-ref HEAD 2>/dev/null)
[ -z "\$BRANCH" ] || [ "\$BRANCH" = "HEAD" ] && BRANCH=main
LATEST=\$(curl -sf "https://raw.githubusercontent.com/IanJohnsons/mysterium-toolkit/\$BRANCH/VERSION" 2>/dev/null)

# Everything below reports why it did nothing. This script used to end in a bare
# exit 0 on every path, so a failed version check and an up-to-date install were
# indistinguishable: systemd logged "Finished successfully" hourly while the
# machine sat on an older release. Output goes to the journal via the unit.
if [ -z "\$CURRENT" ]; then
    echo "auto-update: cannot read \$TOOLKIT_DIR/VERSION — skipping"
    exit 0
fi
if [ -z "\$LATEST" ]; then
    echo "auto-update: could not fetch the VERSION for branch \$BRANCH from GitHub — skipping"
    exit 0
fi
if [ "\$CURRENT" = "\$LATEST" ]; then
    echo "auto-update: already on \$CURRENT (\$BRANCH)"
    exit 0
fi

echo "auto-update: \$CURRENT -> \$LATEST on \$BRANCH"
if [ "\$(id -u)" -eq 0 ]; then
    exec "$TOOLKIT_DIR/update.sh"
fi
# sudo -n fails outright without NOPASSWD, and an exec that cannot start leaves
# nothing behind to explain the silence.
if ! sudo -n true 2>/dev/null; then
    echo "auto-update: sudo requires a password for \$(whoami) — cannot update unattended"
    echo "auto-update: run ./update.sh by hand, or grant NOPASSWD for it"
    exit 1
fi
exec sudo -n "$TOOLKIT_DIR/update.sh"
WRAPPER_EOF
    $SUDO chmod +x "$_WRAPPER"
fi

# ── Auto-update timer — always rewrite service file so User/path stay correct ──
_TIMER_FILE="/etc/systemd/system/mysterium-toolkit-update.timer"
_TIMER_SVC="/etc/systemd/system/mysterium-toolkit-update.service"
if command -v systemctl &>/dev/null; then
    _REAL_USER="${SUDO_USER:-$USER}"
    # Always rewrite the timer file
    printf '[Unit]\nDescription=Mysterium Toolkit auto-update\n\n[Timer]\nOnCalendar=hourly\nPersistent=true\n\n[Install]\nWantedBy=timers.target\n' \
        | $SUDO tee "$_TIMER_FILE" > /dev/null
    # Always rewrite the service file — ensures User, WorkingDirectory and ExecStart are current
    printf '[Unit]\nDescription=Mysterium Toolkit auto-update\n\n[Service]\nType=oneshot\nUser=%s\nWorkingDirectory=%s\nExecStart=%s\n' \
        "$_REAL_USER" "$TOOLKIT_DIR" "$_WRAPPER" \
        | $SUDO tee "$_TIMER_SVC" > /dev/null
    $SUDO systemctl daemon-reload 2>/dev/null || true
    $SUDO systemctl enable mysterium-toolkit-update.timer 2>/dev/null || true
    # Start only if not already active
    systemctl is-active --quiet mysterium-toolkit-update.timer 2>/dev/null \
        || $SUDO systemctl start mysterium-toolkit-update.timer 2>/dev/null || true
    echo -e "  ${GREEN}✓ Auto-update timer refreshed${NC}"
fi

# ── Restart backend ───────────────────────────────────────────────────────
echo
echo -e "  Restarting backend..."
$SUDO systemctl stop mysterium-toolkit 2>/dev/null || true
# Wait and handle auto-restart: backend exits with code 1 on SIGTERM which triggers
# Restart=on-failure after RestartSec (10s). Detect and stop any auto-restart.
_wait=0
while [ $_wait -lt 20 ]; do
    sleep 1
    _wait=$((_wait + 1))
    if systemctl is-active --quiet mysterium-toolkit 2>/dev/null; then
        $SUDO systemctl stop mysterium-toolkit 2>/dev/null || true
    fi
    if ! ss -tlnp 2>/dev/null | grep -q ':5000 '; then
        break
    fi
done
# Kill any remaining process on port 5000
_pid=$(ss -tlnp 2>/dev/null | grep ':5000 ' | awk -F'pid=' '{print $2}' | awk -F',' '{print $1}' | head -1 || true)
if [ -n "$_pid" ] && [ "$_pid" -gt 1 ] 2>/dev/null; then
    kill -9 "$_pid" 2>/dev/null || true
    sleep 1
fi
# Wait until port 5000 is actually free (max 15s)
_port_wait=0
while ss -tlnp 2>/dev/null | grep -q ':5000 ' && [ $_port_wait -lt 15 ]; do
    sleep 1
    _port_wait=$((_port_wait + 1))
done
# An install without autostart has no unit. The stop above still killed the
# backend that start.sh had launched, so starting only through systemd left the
# dashboard down after every update, with nothing but "Unit not found" to show
# for it — and after an unattended run of the auto-update timer, not even that.
_HAS_UNIT=false
if [ -f "/etc/systemd/system/mysterium-toolkit.service" ] \
   || systemctl list-unit-files 2>/dev/null | grep -q '^mysterium-toolkit\.service'; then
    _HAS_UNIT=true
fi

if [ "$_HAS_UNIT" = true ]; then
    $SUDO systemctl reset-failed mysterium-toolkit 2>/dev/null || true
    $SUDO systemctl start mysterium-toolkit
    sleep 3
    if systemctl is-active --quiet mysterium-toolkit 2>/dev/null; then
        echo -e "  ${GREEN}✓ Backend restarted via systemd${NC}"
    else
        echo -e "  ${RED}✗ Backend failed to restart — check: journalctl -u mysterium-toolkit -n 20${NC}"
    fi
else
    # Same launch start.sh uses, including its PID file, so the menu keeps
    # recognising the process it did not start itself.
    echo -e "  ${DIM}No systemd service on this install — starting the backend directly${NC}"
    mkdir -p "$TOOLKIT_DIR/logs"
    _PY_BIN="$TOOLKIT_DIR/venv/bin/python"
    [ -x "$_PY_BIN" ] || _PY_BIN=$(command -v python3 || command -v python)
    # No subshell around this: $! inside one reports the subshell's own child,
    # not the backend, and start.sh then reads a PID file pointing at a process
    # that is not the dashboard. update.sh already runs from TOOLKIT_DIR.
    nohup "$_PY_BIN" backend/app.py > "$TOOLKIT_DIR/logs/backend.log" 2>&1 &
    _NEW_PID=$!
    echo "$_NEW_PID" > "$TOOLKIT_DIR/logs/.backend.pid"
    sleep 5
    if [ -n "$_NEW_PID" ] && kill -0 "$_NEW_PID" 2>/dev/null; then
        echo -e "  ${GREEN}✓ Backend restarted (PID $_NEW_PID)${NC}"
        echo -e "  ${DIM}    Enable autostart from ./start.sh so it also survives a reboot${NC}"
    else
        rm -f "$TOOLKIT_DIR/logs/.backend.pid"
        echo -e "  ${RED}✗ Backend failed to start — check: tail -20 $TOOLKIT_DIR/logs/backend.log${NC}"
    fi
fi

echo
echo -e "${GREEN}✓ Update complete — v${NEW_VERSION}${NC}"
if [ "${_PIP_FAILED:-0}" = "1" ]; then
    echo -e "  ${YELLOW}⚠ except the Python packages — see $TOOLKIT_DIR/logs/pip_install.log${NC}"
fi
echo
