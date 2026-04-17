#!/usr/bin/env python3
"""
Mysterium Node Monitoring Dashboard — Terminal (CLI) Version
=============================================================
Lightweight terminal UI that connects to the backend API.
No browser needed, minimal resource usage.

Usage:
    python cli/dashboard.py                    # defaults: localhost:5000, 10s refresh
    python cli/dashboard.py --port 5000 --interval 30
    python cli/dashboard.py --url http://remote:5000
"""

import argparse
import curses
import json
import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

# Try importing requests (available in venv)
try:
    import requests
except ImportError:
    print("Error: 'requests' package required. Run from toolkit venv or: pip install requests")
    sys.exit(1)

# Try importing psutil for local resource display when backend is unreachable
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

_VERSION_FILE = Path(__file__).parent.parent / 'VERSION'
VERSION = _VERSION_FILE.read_text().strip() if _VERSION_FILE.exists() else 'unknown'

# ============ PAYMENT CONFIG TUNER CONSTANTS ============
CONFIG_KEYS_META = [
    {
        'key':   'payments.zero-stake-unsettled-amount',
        'label': 'Auto-Settle Threshold',
        'unit':  'MYST',
        'group': 'settlement',
        'desc':  'Unsettled MYST to trigger auto-settlement. Default:5. Higher=fewer TX, more MYST at risk.',
    },
    {
        'key':   'payments.unsettled-max-amount',
        'label': 'Max Unsettled',
        'unit':  'MYST',
        'group': 'settlement',
        'desc':  'Hard ceiling on unsettled balance. Default:~10. High-load recommended: 25.',
    },
    {
        'key':   'payments.settle.min-amount',
        'label': 'Manual Settle Min',
        'unit':  'MYST',
        'group': 'settlement',
        'desc':  'Min balance for manual Settle button. Default:1. Set 0.01 to settle anytime.',
    },
    {
        'key':   'payments.min_promise_amount',
        'label': 'Min Promise Amount',
        'unit':  'MYST',
        'group': 'session',
        'desc':  'Min MYST in consumer first promise. Lower=accepts micro-sessions.',
    },
    {
        'key':   'payments.provider.invoice-frequency',
        'label': 'Invoice Frequency',
        'unit':  'seconds',
        'group': 'timing',
        'desc':  'Invoice interval per session. Default:60s. 300s = ~5x fewer API calls.',
    },
    {
        'key':   'pingpong.balance-check-interval',
        'label': 'Balance Check Interval',
        'unit':  'seconds',
        'group': 'timing',
        'desc':  'Consumer balance poll interval. Primary rate-limit fix. DO NOT exceed 300s.',
    },
    {
        'key':   'pingpong.promise-wait-timeout',
        'label': 'Promise Wait Timeout',
        'unit':  'seconds',
        'group': 'timing',
        'desc':  'Patience for slow consumer promise. Default:180s. DO NOT exceed 600s.',
    },
]

CONFIG_PRESETS = {
    'defaults': {
        'payments.zero-stake-unsettled-amount': '5.0',
        'payments.unsettled-max-amount':        '10.0',
        'payments.settle.min-amount':           '1.0',
        'payments.min_promise_amount':          '0.05',
        'payments.provider.invoice-frequency':  '60',
        'pingpong.balance-check-interval':      '90',
        'pingpong.promise-wait-timeout':        '180',
    },
    'high-traffic': {
        'payments.zero-stake-unsettled-amount': '10',
        'payments.unsettled-max-amount':        '25',
        'payments.settle.min-amount':           '0.01',
        'payments.min_promise_amount':          '0.01',
        'payments.provider.invoice-frequency':  '300',
        'pingpong.balance-check-interval':      '300',
        'pingpong.promise-wait-timeout':        '600',
    },
}

# ============ CLI THEMES (match webdash names) ============
# Curses only has 8 base colors: BLACK RED GREEN YELLOW BLUE MAGENTA CYAN WHITE
# Color pair roles:
#   1 = Values      — main numbers, data         → theme ACCENT
#   2 = Headers     — section titles              → theme ACCENT (+ BOLD applied at draw time)
#   3 = Warnings    — ALWAYS YELLOW               → SEMANTIC — never change
#   4 = Errors      — ALWAYS RED                  → SEMANTIC — never change
#   5 = Labels      — dim supporting text         → -1 (terminal default)
#   6 = Accents     — highlights, secondary data  → theme HIGHLIGHT (2nd color for depth)
CLI_THEMES = {
    'emerald': {
        'name': 'Emerald',
        'colors': {
            1: (curses.COLOR_GREEN,   -1),  # Values     — emerald green
            2: (curses.COLOR_GREEN,   -1),  # Headers    — emerald green bold
            3: (curses.COLOR_YELLOW,  -1),  # Warnings   — semantic amber
            4: (curses.COLOR_RED,     -1),  # Errors     — semantic red
            5: (curses.COLOR_WHITE,   -1),  # Labels     — dim white
            6: (curses.COLOR_CYAN,    -1),  # Accents    — cyan highlight for depth
        },
        'header_bold': True,
    },
    'cyber': {
        'name': 'Cyber',
        'colors': {
            1: (curses.COLOR_CYAN,    -1),  # Values     — synthwave cyan
            2: (curses.COLOR_CYAN,    -1),  # Headers    — synthwave cyan bold
            3: (curses.COLOR_YELLOW,  -1),  # Warnings   — semantic amber
            4: (curses.COLOR_RED,     -1),  # Errors     — semantic red
            5: (curses.COLOR_WHITE,   -1),  # Labels     — white
            6: (curses.COLOR_BLUE,    -1),  # Accents    — deep blue for depth
        },
        'header_bold': True,
    },
    'sunset': {
        'name': 'Sunset',
        'colors': {
            1: (curses.COLOR_YELLOW,  -1),  # Values     — yellow (closest to orange)
            2: (curses.COLOR_YELLOW,  -1),  # Headers    — yellow bold
            3: (curses.COLOR_YELLOW,  -1),  # Warnings   — yellow (theme=warm; bold distinguishes)
            4: (curses.COLOR_RED,     -1),  # Errors     — semantic red
            5: (curses.COLOR_WHITE,   -1),  # Labels     — white
            6: (curses.COLOR_MAGENTA, -1),  # Accents    — magenta/pink for depth
        },
        'header_bold': True,
    },
    'violet': {
        'name': 'Violet',
        'colors': {
            1: (curses.COLOR_MAGENTA, -1),  # Values     — magenta/violet
            2: (curses.COLOR_MAGENTA, -1),  # Headers    — magenta bold
            3: (curses.COLOR_YELLOW,  -1),  # Warnings   — semantic amber
            4: (curses.COLOR_RED,     -1),  # Errors     — semantic red
            5: (curses.COLOR_WHITE,   -1),  # Labels     — white
            6: (curses.COLOR_BLUE,    -1),  # Accents    — blue/indigo for depth
        },
        'header_bold': True,
    },
    'ruby': {
        'name': 'Ruby',
        'colors': {
            1: (curses.COLOR_RED,     -1),  # Values     — crimson red
            2: (curses.COLOR_RED,     -1),  # Headers    — crimson bold
            3: (curses.COLOR_YELLOW,  -1),  # Warnings   — semantic amber
            4: (curses.COLOR_RED,     -1),  # Errors     — red (same; bold+context distinguishes)
            5: (curses.COLOR_WHITE,   -1),  # Labels     — white
            6: (curses.COLOR_MAGENTA, -1),  # Accents    — magenta/pink for depth
        },
        'header_bold': True,
    },
    'matrix': {
        'name': 'Matrix',
        'colors': {
            1: (curses.COLOR_GREEN,   -1),  # Values     — matrix green
            2: (curses.COLOR_GREEN,   -1),  # Headers    — matrix green bold
            3: (curses.COLOR_YELLOW,  -1),  # Warnings   — semantic amber (FIXED: was GREEN)
            4: (curses.COLOR_RED,     -1),  # Errors     — semantic red
            5: (curses.COLOR_GREEN,   -1),  # Labels     — dim green (hacker aesthetic)
            6: (curses.COLOR_CYAN,    -1),  # Accents    — cyan terminal highlight
        },
        'header_bold': True,
    },
    'phosphor': {
        'name': 'Phosphor',
        'colors': {
            1: (curses.COLOR_YELLOW,  -1),  # Values     — phosphor amber glow
            2: (curses.COLOR_YELLOW,  -1),  # Headers    — amber bold
            3: (curses.COLOR_YELLOW,  -1),  # Warnings   — yellow (CRT = all amber; context distinguishes)
            4: (curses.COLOR_RED,     -1),  # Errors     — semantic red
            5: (curses.COLOR_YELLOW,  -1),  # Labels     — dim amber (full CRT immersion)
            6: (curses.COLOR_WHITE,   -1),  # Accents    — white for contrast on amber
        },
        'header_bold': True,
    },
    'ghost': {
        'name': 'Ghost',
        'colors': {
            1: (curses.COLOR_WHITE,   -1),  # Values     — pale white
            2: (curses.COLOR_WHITE,   -1),  # Headers    — white (no bold = softer)
            3: (curses.COLOR_YELLOW,  -1),  # Warnings   — semantic amber
            4: (curses.COLOR_RED,     -1),  # Errors     — semantic red
            5: (curses.COLOR_WHITE,   -1),  # Labels     — white
            6: (curses.COLOR_CYAN,    -1),  # Accents    — slight cyan tint
        },
        'header_bold': False,   # No bold = softer, stealthier look
    },
    'crimson': {
        'name': 'Crimson',
        'colors': {
            1: (curses.COLOR_RED,     -1),
            2: (curses.COLOR_RED,     -1),
            3: (curses.COLOR_YELLOW,  -1),
            4: (curses.COLOR_RED,     -1),
            5: (curses.COLOR_WHITE,   -1),
            6: (curses.COLOR_YELLOW,  -1),
        },
        'header_bold': True,
    },
    'midnight': {
        'name': 'Midnight',
        'colors': {
            1: (curses.COLOR_BLUE,    -1),
            2: (curses.COLOR_BLUE,    -1),
            3: (curses.COLOR_YELLOW,  -1),
            4: (curses.COLOR_RED,     -1),
            5: (curses.COLOR_WHITE,   -1),
            6: (curses.COLOR_CYAN,    -1),
        },
        'header_bold': True,
    },
    'military': {
        'name': 'Military',
        'colors': {
            1: (curses.COLOR_GREEN,   -1),
            2: (curses.COLOR_GREEN,   -1),
            3: (curses.COLOR_YELLOW,  -1),
            4: (curses.COLOR_RED,     -1),
            5: (curses.COLOR_YELLOW,  -1),
            6: (curses.COLOR_WHITE,   -1),
        },
        'header_bold': True,
    },
}
CLI_THEME_ORDER = ['emerald', 'cyber', 'sunset', 'violet', 'crimson', 'matrix', 'phosphor', 'ghost', 'midnight', 'military']


def load_config():
    """Load backend URL from .env or config/setup.json if available"""
    toolkit_dir = Path(__file__).resolve().parent.parent
    port = 5000

    # Try .env
    env_file = toolkit_dir / '.env'
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith('DASHBOARD_PORT='):
                try:
                    port = int(line.split('=', 1)[1].strip())
                except ValueError:
                    pass

    # Try config/setup.json
    config_file = toolkit_dir / 'config' / 'setup.json'
    if config_file.exists():
        try:
            cfg = json.loads(config_file.read_text())
            port = cfg.get('dashboard_port', port)
        except (json.JSONDecodeError, KeyError):
            pass

    return port


def format_size(mb):
    """Format MB value to human-readable string, scaling to TiB"""
    if mb >= 1024 * 1024: return f"{mb / 1024 / 1024:.2f} TiB"
    if mb >= 1024:        return f"{mb / 1024:.2f} GiB"
    if mb >= 1:           return f"{mb:.1f} MB"
    if mb > 0:            return f"{mb * 1024:.0f} KB"
    return "0 MB"


def format_speed(mbps):
    """Format speed in bytes/s with auto-scale"""
    if mbps <= 0:
        return "0 B/s"
    Bps = mbps * 1024 * 1024
    if mbps >= 1:
        return f"{mbps:.2f} MB/s"
    if Bps >= 1024:
        return f"{Bps / 1024:.1f} KB/s"
    return f"{Bps:.0f} B/s"


def format_speed_short(mbps):
    """Short speed format"""
    if mbps <= 0:
        return "0 B/s"
    Bps = mbps * 1024 * 1024
    if mbps >= 1:
        return f"{mbps:.2f} MB/s"
    if Bps >= 1024:
        return f"{Bps / 1024:.1f} KB/s"
    return f"{Bps:.0f} B/s"


def format_myst(val):
    """Format MYST value"""
    return f"{float(val):.4f}" if val else "0.0000"


def short_addr(addr):
    """Shorten wallet address"""
    if addr and len(addr) > 10:
        return f"{addr[:6]}...{addr[-4:]}"
    return addr or "—"


def format_uptime(uptime):
    """Clean TequilAPI uptime string like '11h4m1.364053s' → '11h 4m'"""
    import re
    if not uptime or uptime == '—':
        return uptime or '—'
    if isinstance(uptime, str):
        d = re.search(r'(\d+)d', uptime)
        h = re.search(r'(\d+)h', uptime)
        m = re.search(r'(\d+)m', uptime)
        days = int(d.group(1)) if d else 0
        hours = int(h.group(1)) if h else 0
        mins = int(m.group(1)) if m else 0
        if days > 0:
            return f"{days}d {hours}h"
        if hours > 0:
            return f"{hours}h {mins}m"
        if mins > 0:
            return f"{mins}m"
        return '0m'
    try:
        secs = int(uptime)
        if secs < 60:
            return f"{secs}s"
        if secs < 3600:
            return f"{secs // 60}m"
        return f"{secs // 3600}h {(secs % 3600) // 60}m"
    except (ValueError, TypeError):
        return str(uptime)


class CLIDashboard:
    def __init__(self, base_url, interval, api_key=None, username=None, password=None, theme='emerald'):
        self.base_url   = base_url.rstrip('/')
        self.interval   = interval
        self.api_key    = api_key
        self.username   = username
        self.password   = password
        self.metrics    = {}
        self.last_fetch = None
        self.last_error = None
        self.running    = True
        self.theme_key  = theme if theme in CLI_THEMES else 'emerald'
        self.show_health       = False   # health overlay toggle
        self.show_help         = False   # help overlay toggle
        self.show_config       = False   # payment config overlay toggle
        # Config overlay state
        self._config_phase      = 1      # 1=read 2=edit
        self._config_scroll     = 0      # phase-1 scroll
        self._config_scrolled_bottom = False
        self._config_acknowledged = False
        self._config_cursor     = 0      # phase-2 selected setting index
        self._config_editing    = False  # inline edit active
        self._config_edit_buf   = ''     # edit buffer
        self._config_current    = {}     # values from backend
        self._config_pending    = {}     # user-modified values
        self._config_results    = {}     # {key: 'ok'|error_str}
        self._config_applying   = set()  # keys currently being applied
        self.health_message    = None    # one-line status after action
        self.health_msg_time   = 0
        self.health_selected   = 0       # highlighted subsystem index
        self.health_scroll     = 0       # content scroll offset in overlay
        self.health_last_result = None   # full API result for results view
        self.health_result_scroll = 0    # scroll in results view
        self.page = 1                    # 1=Status 2=Earnings
        # Sessions page sort: key + dir for each section
        self.sess_sort = {
            'tunnels':  {'key': 'total_mb',       'dir': 'desc'},
            'active':   {'key': 'earnings_myst',   'dir': 'desc'},
            'history':  {'key': 'earnings_myst',   'dir': 'desc'},
            'consumers':{'key': 'total_earnings',  'dir': 'desc'},
        }
        self.sess_section = 'active'   # which section's sort is focused

    # ── auth ──────────────────────────────────────────────────────────────────
    def _auth_headers(self):
        h = {}
        if self.api_key:
            h['Authorization'] = f'Bearer {self.api_key}'
        return h

    def _auth_tuple(self):
        if self.username and self.password:
            return (self.username, self.password)
        return None

    # ── theme ──────────────────────────────────────────────────────────────────
    def _apply_theme(self):
        t = CLI_THEMES[self.theme_key]
        for pair_id, (fg, bg) in t['colors'].items():
            curses.init_pair(pair_id, fg, bg)
        # Pair 7: dim — always dark grey if 256-color, else default
        if curses.COLORS >= 256:
            curses.init_pair(7, 240, -1)
        else:
            curses.init_pair(7, -1, -1)

    def _cycle_theme(self):
        idx = CLI_THEME_ORDER.index(self.theme_key)
        self.theme_key = CLI_THEME_ORDER[(idx + 1) % len(CLI_THEME_ORDER)]
        self._apply_theme()

    # ── data ───────────────────────────────────────────────────────────────────
    def fetch_metrics(self):
        try:
            headers = self._auth_headers()
            auth    = self._auth_tuple()
            kwargs  = {'headers': headers, 'timeout': 10}
            if auth:
                kwargs['auth'] = auth
            resp = requests.get(f'{self.base_url}/metrics', **kwargs)
            if resp.status_code == 200:
                self.metrics    = resp.json()
                self.last_fetch = datetime.now()
                self.last_error = None
            elif resp.status_code == 401:
                self.last_error = 'Auth required — check your .env file (DASHBOARD_API_KEY)'
            else:
                self.last_error = f'HTTP {resp.status_code}'
        except requests.exceptions.ConnectionError:
            self.last_error = f'Cannot connect to {self.base_url}'
        except requests.exceptions.Timeout:
            self.last_error = 'Request timed out'
        except Exception as e:
            self.last_error = str(e)[:60]

    def prompt_api_key(self, stdscr):
        h, w = stdscr.getmaxyx()
        curses.echo()
        curses.curs_set(1)
        stdscr.addstr(h // 2, 2, 'Enter API key: ')
        stdscr.refresh()
        try:
            key = stdscr.getstr(h // 2, 17, 60).decode('utf-8').strip()
            if key:
                self.api_key = key
        except Exception:
            pass
        curses.noecho()
        curses.curs_set(0)

    # ── API actions ───────────────────────────────────────────────────────────
    def _health_api_action(self, endpoint, method, label, subsystem='all'):
        self.health_message      = f'⏳ {label}'
        self.health_msg_time     = time.time()
        self.health_last_result  = None
        self.health_result_scroll = 0
        try:
            headers = self._auth_headers()
            headers['Content-Type'] = 'application/json'
            resp = requests.post(
                f'{self.base_url}{endpoint}',
                json={'subsystem': subsystem},
                headers=headers, timeout=30
            )
            if resp.status_code == 200:
                data    = resp.json()
                success = data.get('overall_success', data.get('success', True))
                self.health_last_result = data    # store full result for display
                if success:
                    self.health_message = '✓ Done — refreshing...'
                else:
                    self.health_message = '⚠ Partial — some actions failed (need sudo?)'
            else:
                self.health_message = f'✗ HTTP {resp.status_code}'
        except requests.exceptions.ConnectionError:
            self.health_message = '✗ Backend not reachable'
        except Exception as e:
            self.health_message = f'✗ {str(e)[:40]}'
        self.health_msg_time = time.time()
        self.fetch_metrics()

    def _node_action(self, stdscr, endpoint, method, label):
        self.health_message  = f'⏳ {label}'
        self.health_msg_time = time.time()
        try:
            headers = self._auth_headers()
            headers['Content-Type'] = 'application/json'
            timeout = 120 if 'settle' in endpoint else 30
            resp = requests.post(
                f'{self.base_url}{endpoint}',
                json={}, headers=headers, timeout=timeout
            )
            data = resp.json()
            if data.get('success'):
                self.health_message = f'✓ {data.get("message", "Done")}'
            else:
                self.health_message = f'✗ {data.get("error", f"HTTP {resp.status_code}")[:50]}'
        except requests.exceptions.Timeout:
            self.health_message = '⏳ Timed out — may still be processing'
        except requests.exceptions.ConnectionError:
            self.health_message = '✗ Backend not reachable'
        except Exception as e:
            self.health_message = f'✗ {str(e)[:40]}'
        self.health_msg_time = time.time()
        self.fetch_metrics()

    def _test_node(self, stdscr):
        """Live node reachability test via Discovery API (bypasses cache)."""
        self.health_message  = '⏳ Testing node visibility on Discovery network…'
        self.health_msg_time = time.time()
        try:
            headers = self._auth_headers()
            headers['Content-Type'] = 'application/json'
            resp = requests.post(
                f'{self.base_url}/node/test',
                json={}, headers=headers, timeout=20
            )
            data = resp.json()
            if data.get('visible'):
                parts = ['✓ Node visible on Discovery']
                if data.get('monitoring_ok') is not None:
                    parts.append('Mon:OK' if data['monitoring_ok'] else 'Mon:FAIL')
                if data.get('uptime_24h_net') is not None:
                    parts.append(f'Up:{data["uptime_24h_net"]:.1f}%')
                if data.get('quality_score') is not None:
                    parts.append(f'Q:{data["quality_score"]:.2f}')
                self.health_message = '  '.join(parts)
            else:
                self.health_message = f'✗ Not visible — {data.get("error", "not found in Discovery")[:50]}'
        except requests.exceptions.Timeout:
            self.health_message = '✗ Test timed out'
        except requests.exceptions.ConnectionError:
            self.health_message = '✗ Backend not reachable'
        except Exception as e:
            self.health_message = f'✗ Test error: {str(e)[:40]}'
        self.health_msg_time = time.time()

    # ── helpers ────────────────────────────────────────────────────────────────
    def _safe_addstr(self, win, y, x, text, attr=0):
        max_y, max_x = win.getmaxyx()
        if y < 0 or y >= max_y or x < 0 or x >= max_x:
            return
        text = str(text)[:max(0, max_x - x)]
        try:
            win.addstr(y, x, text, attr)
        except curses.error:
            pass

    def _has_fleet(self):
        return bool(self.metrics and self.metrics.get('fleet', {}).get('fleet_mode'))

    # ── main run loop ──────────────────────────────────────────────────────────
    def run(self, stdscr):
        curses.curs_set(0)
        stdscr.nodelay(True)
        stdscr.timeout(250)
        curses.start_color()
        curses.use_default_colors()
        self._apply_theme()

        GREEN  = curses.color_pair(1)
        CYAN   = curses.color_pair(2)   # not used directly — kept for compat
        YELLOW = curses.color_pair(3)
        RED    = curses.color_pair(4)
        WHITE  = curses.color_pair(5)
        ACCENT = curses.color_pair(6)
        DIM    = curses.color_pair(7) if curses.COLORS >= 256 else curses.A_DIM
        BOLD   = curses.A_BOLD

        last_poll = 0

        while self.running:
            now = time.time()
            if now - last_poll >= self.interval:
                self.fetch_metrics()
                last_poll = now

            try:
                key = stdscr.getch()
                max_page = 2

                if key in (ord('q'), 27):
                    self.running = False
                    break

                elif key == ord('r'):
                    self._settle_cache = None  # Force wallet refresh too
                    self.fetch_metrics()
                    last_poll = now

                elif key == ord('w'):
                    self._node_action(stdscr, '/node/restart', 'POST', 'Restarting node...')

                elif key == ord('$'):
                    self._node_action(stdscr, '/node/settle', 'POST', 'Settling MYST...')

                elif key == ord('t'):
                    self._cycle_theme()

                elif key == ord('T'):
                    self._test_node(stdscr)

                elif key == ord('?'):
                    self.show_help = not self.show_help
                    if not self.show_help:
                        self._help_scroll = 0

                elif key == ord('h'):
                    self.show_health = not self.show_health
                    if not self.show_health:
                        self.health_message     = None
                        self.health_last_result = None
                        self.health_scroll      = 0
                        self.health_result_scroll = 0

                elif key == ord('c'):
                    if self.show_config:
                        self.show_config = False
                        self._config_phase = 1
                        self._config_scroll = 0
                        self._config_scrolled_bottom = False
                        self._config_acknowledged = False
                        self._config_editing = False
                    else:
                        self.show_health = False
                        self.show_help   = False
                        self.show_config = True
                        self._config_phase = 1
                        self._config_scroll = 0
                        self._config_scrolled_bottom = False
                        self._config_acknowledged = False
                        self._config_cursor = 0
                        self._fetch_config_values()

                elif key == ord('+'):
                    self.interval = min(60, self.interval + 5)
                elif key == ord('-'):
                    self.interval = max(2, self.interval - 5)



                # ── page switching (only when overlays closed) ──
                elif not self.show_health and not self.show_help and not self.show_config:
                    if key == 9:  # Tab
                        self.page = (self.page % max_page) + 1
                    elif ord('1') <= key <= ord('2'):
                        pg = key - ord('0')
                        if pg <= max_page:
                            self.page = pg
                    # ── page-3 sort keys ──
                    elif self.page == 5 and key == ord('s'):
                        # Cycle through sort keys within focused section, then move to next section
                        cycles = {
                            'tunnels':   ['total_mb','download_mb','upload_mb','speed_total','duration'],
                            'active':    ['earnings_myst','data_out','data_in','duration','service_type','consumer_country'],
                            'history':   ['earnings_myst','data_total','duration','service_type','consumer_country'],
                            'consumers': ['total_earnings','total_data_mb','sessions'],
                        }
                        sections = ['tunnels','active','history','consumers']
                        sec = self.sess_section
                        cyc = cycles[sec]
                        cur_key = self.sess_sort[sec]['key']
                        if cur_key in cyc:
                            nxt_idx = (cyc.index(cur_key) + 1) % len(cyc)
                            if nxt_idx == 0:
                                # Wrapped — move to next section
                                self.sess_section = sections[(sections.index(sec) + 1) % len(sections)]
                                self.sess_sort[self.sess_section]['key'] = cycles[self.sess_section][0]
                            else:
                                self.sess_sort[sec]['key'] = cyc[nxt_idx]
                        else:
                            self.sess_sort[sec]['key'] = cyc[0]
                    elif self.page == 5 and key == ord('d'):
                        # Flip sort direction for current focused section
                        sec = self.sess_section
                        self.sess_sort[sec]['dir'] = 'asc' if self.sess_sort[sec]['dir'] == 'desc' else 'desc'

                # ── health overlay keys ──
                elif self.show_health:
                    subs = self.metrics.get('systemHealth', {}).get('subsystems', [])
                    n_subs = len(subs)

                    if self.health_last_result:
                        # Results view: scroll + clear
                        if key == curses.KEY_UP:
                            self.health_result_scroll = max(0, self.health_result_scroll - 1)
                        elif key == curses.KEY_DOWN:
                            self.health_result_scroll += 1
                        elif key == ord('2'):
                            self.health_last_result   = None
                            self.health_result_scroll = 0
                    else:
                        # Subsystem navigation view
                        if key == curses.KEY_UP:
                            if n_subs:
                                self.health_selected = (self.health_selected - 1) % n_subs
                        elif key == curses.KEY_DOWN:
                            if n_subs:
                                self.health_selected = (self.health_selected + 1) % n_subs
                        elif key == ord('1'):
                            # Scan now
                            self._health_api_action('/system-health/scan', 'POST',
                                'Scanning...', subsystem='all')
                        elif key == ord('f') and n_subs:
                            sub_name = subs[self.health_selected].get('name', 'all')
                            self._health_api_action('/system-health/fix', 'POST',
                                f'Fixing {sub_name}...', subsystem=sub_name)
                        elif key == ord('3'):
                            self._health_api_action('/system-health/fix', 'POST',
                                'Fixing all...', subsystem='all')
                        elif key == ord('p') and n_subs:
                            sub_name = subs[self.health_selected].get('name', 'all')
                            self._health_api_action('/system-health/persist', 'POST',
                                f'Persisting {sub_name}...', subsystem=sub_name)
                        elif key == ord('4'):
                            self._health_api_action('/system-health/persist', 'POST',
                                'Persisting all...', subsystem='all')
                        elif key == ord('u') and n_subs:
                            sub_name = subs[self.health_selected].get('name', 'all')
                            self._health_api_action('/system-health/unpersist', 'POST',
                                f'Unpersisting {sub_name}...', subsystem=sub_name)
                        elif key == ord('5'):
                            self._health_api_action('/system-health/unpersist', 'POST',
                                'Unpersisting all...', subsystem='all')

                # ── help overlay scroll ──
                elif self.show_help:
                    if key == curses.KEY_DOWN:
                        self._help_scroll = getattr(self, '_help_scroll', 0) + 1
                    elif key == curses.KEY_UP:
                        self._help_scroll = max(0, getattr(self, '_help_scroll', 0) - 1)

                # ── config overlay keys ──
                elif self.show_config:
                    if self._config_phase == 1:
                        # Phase 1 — read/scroll
                        if key == curses.KEY_DOWN:
                            self._config_scroll += 1
                        elif key == curses.KEY_UP:
                            self._config_scroll = max(0, self._config_scroll - 1)
                        elif key == ord(' ') or key == ord('\n') or key == 10:
                            if self._config_scrolled_bottom:
                                self._config_acknowledged = True
                                self._config_phase = 2
                    elif self._config_phase == 2:
                        if self._config_editing:
                            # Inline edit mode
                            if key in (curses.KEY_BACKSPACE, 127, 8):
                                self._config_edit_buf = self._config_edit_buf[:-1]
                            elif key == 27:  # ESC — cancel
                                self._config_editing = False
                                self._config_edit_buf = ''
                            elif key in (10, curses.KEY_ENTER):  # Enter — confirm
                                meta = CONFIG_KEYS_META[self._config_cursor]
                                self._config_pending[meta['key']] = self._config_edit_buf
                                self._config_editing = False
                                self._config_edit_buf = ''
                            elif 32 <= key < 127:
                                self._config_edit_buf += chr(key)
                        else:
                            if key == curses.KEY_DOWN:
                                self._config_cursor = min(len(CONFIG_KEYS_META) - 1, self._config_cursor + 1)
                            elif key == curses.KEY_UP:
                                self._config_cursor = max(0, self._config_cursor - 1)
                            elif key == ord('e'):
                                meta = CONFIG_KEYS_META[self._config_cursor]
                                cur = self._config_pending.get(meta['key'],
                                      self._config_current.get(meta['key'], ''))
                                self._config_edit_buf = str(cur)
                                self._config_editing = True
                            elif key == ord('a'):
                                # Apply focused setting
                                meta = CONFIG_KEYS_META[self._config_cursor]
                                self._apply_config_key(meta['key'])
                            elif key == ord('z'):
                                # Apply all pending
                                for meta in CONFIG_KEYS_META:
                                    self._apply_config_key(meta['key'])
                            elif key == ord('n'):
                                # Load standard preset
                                for meta in CONFIG_KEYS_META:
                                    self._config_pending[meta['key']] = CONFIG_PRESETS['defaults'][meta['key']]
                                self._config_results = {}
                            elif key == ord('m'):
                                # Load high-traffic preset
                                for meta in CONFIG_KEYS_META:
                                    self._config_pending[meta['key']] = CONFIG_PRESETS['high-traffic'][meta['key']]
                                self._config_results = {}
                            elif key == ord('x'):
                                # Reset focused key to default
                                meta = CONFIG_KEYS_META[self._config_cursor]
                                self._apply_config_reset(meta['key'])

            except curses.error:
                pass

            try:
                self._draw(stdscr, GREEN, CYAN, YELLOW, RED, WHITE, ACCENT, DIM, BOLD)
            except curses.error:
                pass

    # ─────────────────────────────────────────────────────────────────────────
    # DRAW — main dispatcher
    # ─────────────────────────────────────────────────────────────────────────
    def _draw(self, stdscr, GREEN, CYAN, YELLOW, RED, WHITE, ACCENT, DIM, BOLD):
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        m    = self.metrics
        has_fleet = self._has_fleet()
        max_page  = 2

        # ── HEADER: professional bordered box, 3 lines ───────────────────────
        ns         = m.get('nodeStatus', {}) if m else {}
        earn       = m.get('earnings', {}) if m else {}
        status     = ns.get('status', 'unknown')
        s_col      = GREEN if status == 'online' else (YELLOW if status == 'degraded' else RED)
        theme_name = CLI_THEMES[self.theme_key]['name']
        uptime     = format_uptime(ns.get('uptime', ''))

        # ─ Line 0: top border ─────────────────────────────────────────────
        #  ╔══ Mysterium Node Monitor  v{VERSION} ════════════════[ ● ONLINE  12h 4m ]╗
        status_badge = f'● {status.upper()}'
        if uptime:
            status_badge += f'  {uptime}'
        title_inner  = f' Mysterium Node Monitor  v{VERSION} '
        badge_inner  = f' {status_badge} '
        # available fill width between title and badge
        inner_w      = w - 2  # inside the ╔ ╗
        fill_len     = max(2, inner_w - 4 - len(title_inner) - 2 - len(badge_inner))
        line0        = '╔══' + title_inner + '═' * fill_len + '[ ' + status_badge + ' ]╗'
        # clip if wider than terminal (rare but safe)
        if len(line0) > w:
            line0 = line0[:w]
        elif len(line0) < w:
            # rebuild with correct fill
            fill_len = w - 6 - len(title_inner) - len(badge_inner)
            line0 = '╔══' + title_inner + '═' * max(0, fill_len) + '[ ' + status_badge + ' ]╗'
            line0 = line0[:w]

        self._safe_addstr(stdscr, 0, 0, line0, ACCENT | BOLD)
        # Colour just the status badge portion
        badge_x = line0.rfind('[ ') + 2
        if 0 < badge_x < w:
            self._safe_addstr(stdscr, 0, badge_x, status_badge, s_col | BOLD)

        # ─ Line 1: node identity row ──────────────────────────────────────
        #  ║  ID: 0xaf44...663  ·  Full Cone NAT  ·  IP: x.x.x.x  ·  v1.37.2   ║
        nat      = ns.get('nat_type', '')
        pub_ip   = ns.get('public_ip', '')
        node_ver = ns.get('version', '')
        wallet   = earn.get('wallet_address', '')
        id_short = short_addr(wallet) if wallet else '—'
        id_parts = []
        if wallet:        id_parts.append(f'ID: {id_short}')
        if nat and nat != 'unknown': id_parts.append(f'NAT: {nat}')
        if pub_ip:        id_parts.append(f'IP: {pub_ip}')
        if node_ver and node_ver != 'unknown': id_parts.append(f'v{node_ver}')
        # On narrow screens, only show ID and version (drop IP and NAT)
        if w < 80 and id_parts:
            id_parts = [p for p in id_parts if p.startswith('ID:') or p.startswith('v')]
        id_row   = '  ·  '.join(id_parts) if id_parts else 'connecting...'
        # Pad to fill the box interior
        id_padded = f'  {id_row}'
        id_padded = id_padded + ' ' * max(0, w - 2 - len(id_padded))
        id_padded = id_padded[:w - 2]
        self._safe_addstr(stdscr, 1, 0, '║', ACCENT)
        self._safe_addstr(stdscr, 1, 1, id_padded, DIM)
        self._safe_addstr(stdscr, 1, w - 1, '║', ACCENT)

        # ─ Line 2: tab bar ────────────────────────────────────────────────
        #  ╠═[ 1:Status ]══ 2:Traffic ══ 3:Sessions ══ 4:System ══[Emerald]══════╣
        page_names = {1: 'Status', 2: 'Earnings'}

        # Build tab segments
        tab_segs = []
        for pg in sorted(page_names.keys()):
            tab_segs.append((pg, page_names[pg], pg == self.page))

        # Draw base ╠═...═╣ line
        self._safe_addstr(stdscr, 2, 0, '╠' + '═' * (w - 2) + '╣', ACCENT | BOLD)

        # Overlay tab labels
        tx = 1
        for pg, name, is_active in tab_segs:
            if is_active:
                seg = f'[ {pg}:{name} ]'
                # carve out the tab area with spaces first
                self._safe_addstr(stdscr, 2, tx, ' ' * min(len(seg), w - tx - 1), ACCENT)
                self._safe_addstr(stdscr, 2, tx, seg, ACCENT | BOLD)
            else:
                seg = f'  {pg}:{name}  '
                self._safe_addstr(stdscr, 2, tx, seg, DIM)
            tx += len(seg)
            if tx >= w - 12:
                break

        # Theme label right-aligned
        theme_lbl = f'[{theme_name}]'
        self._safe_addstr(stdscr, 2, max(tx + 2, w - len(theme_lbl) - 2), theme_lbl, ACCENT)

        y = 3  # content starts at row 3

        # Minimum terminal size guard
        if h < 10 or w < 40:
            self._safe_addstr(stdscr, 3, 2, 'Terminal too small', RED | BOLD)
            self._safe_addstr(stdscr, 4, 2, f'Need 40x10 min', DIM)
            self._safe_addstr(stdscr, 5, 2, f'Current: {w}x{h}', DIM)
            stdscr.refresh()
            return

        # Error / no-data states
        if self.last_error:
            self._safe_addstr(stdscr, y, 2, f'✗ {self.last_error}', RED | BOLD)
            if 'Cannot connect' in self.last_error or 'timed out' in self.last_error:
                self._safe_addstr(stdscr, y + 1, 2, 'Is the Mysterium node running?  →  sudo systemctl status mysterium-node', DIM)
                self._safe_addstr(stdscr, y + 2, 2, 'Node UI (browser):  http://localhost:4449/ui', DIM)
                self._safe_addstr(stdscr, y + 4, 2, "Press 'r' to retry, 'a' for API key, 'q' to quit", WHITE)
            else:
                self._safe_addstr(stdscr, y + 2, 2, "Press 'r' to retry, 'a' for API key, 'q' to quit", WHITE)
            stdscr.refresh()
            return
        if not m:
            self._safe_addstr(stdscr, y, 2, 'Connecting...', YELLOW)
            stdscr.refresh()
            return

        # ── PAGE CONTENT ─────────────────────────────────────────────────────
        content_h = h - 5   # 3 header + 2 footer
        # compact = True on small screens (< 27 rows or < 90 cols)
        # Compact mode collapses non-critical rows to fit any terminal
        compact = (h < 27 or w < 90)
        if   self.page == 1: self._draw_page1 (stdscr, y, y + content_h, w, m, GREEN, YELLOW, RED, WHITE, ACCENT, DIM, BOLD, compact)
        elif self.page == 2: self._draw_page2 (stdscr, y, y + content_h, w, m, GREEN, YELLOW, RED, WHITE, ACCENT, DIM, BOLD, compact)

        # ── FOOTER: clean status bar + hint row ───────────────────────────
        fy = h - 2

        # Bottom close line
        self._safe_addstr(stdscr, fy - 1, 0, '╚' + '═' * max(0, w - 2) + '╝', ACCENT)

        # Status info written inside the bottom border
        time_str = self.last_fetch.strftime('%H:%M:%S') if self.last_fetch else '——:——'
        next_in  = max(0, int(self.interval - (time.time() -
                              (self.last_fetch.timestamp() if self.last_fetch else 0))))
        upd_str  = f'  ↻ {time_str}  next: {next_in}s  ·  {theme_name}'
        self._safe_addstr(stdscr, fy - 1, 1, upd_str[:w - 2], DIM)

        # Health action message (if recent) — right-aligned on same line
        if self.health_message and (time.time() - self.health_msg_time) < 8:
            mc  = GREEN if '✓' in self.health_message else YELLOW if '⏳' in self.health_message else RED
            msg = self.health_message[:w - len(upd_str) - 4]
            self._safe_addstr(stdscr, fy - 1, len(upd_str) + 3, msg, mc | BOLD)

        # Key hints row (fy = h-2) — key letters accented
        pages_hint = '1-2'
        # Narrow screens get abbreviated hints
        if w < 90:
            hint_pairs = [
                (pages_hint, 'pg'), ('r', 'ref'), ('?', 'help'), ('w', 'restart'), ('$', 'settle'), ('q', 'quit'),
            ]
        else:
            hint_pairs = [
                (pages_hint, 'page'), ('Tab', 'next'), ('r', 'refresh'),
                ('t', 'theme'), ('T', 'test'), ('h', 'health'), ('c', 'config'), ('?', 'help'),
                ('w', 'restart'), ('$', 'settle'), ('q', 'quit'),
            ]
        hx = 2
        for key, label in hint_pairs:
            if hx >= w - 6:
                break
            self._safe_addstr(stdscr, fy, hx, key, ACCENT | BOLD)
            hx += len(key)
            seg = f':{label}  '
            self._safe_addstr(stdscr, fy, hx, seg, DIM)
            hx += len(seg)

        # ── OVERLAYS ──────────────────────────────────────────────────────────
        if self.show_health:
            self._draw_health_panel(stdscr, h, w, GREEN, YELLOW, RED, WHITE, ACCENT, DIM, BOLD)
        if self.show_help:
            self._draw_help_panel(stdscr, h, w, GREEN, YELLOW, RED, WHITE, ACCENT, DIM, BOLD)
        if self.show_config:
            self._draw_config_panel(stdscr, h, w, GREEN, YELLOW, RED, WHITE, ACCENT, DIM, BOLD)

        stdscr.refresh()


    # ─────────────────────────────────────────────────────────────────────────
    # LAYOUT HELPERS
    # ─────────────────────────────────────────────────────────────────────────
    def _row(self, stdscr, y, w, label, value, val_col,
             label2=None, value2=None, val2_col=None,
             label3=None, value3=None, val3_col=None):
        """Draw a clean label: VALUE row, optionally with 2-3 columns."""
        if y < 0:
            return
        L1 = 4          # left margin
        C2 = w // 3     # col 2 start
        C3 = (w * 2) // 3  # col 3 start

        self._safe_addstr(stdscr, y, L1, f'{label}', curses.A_DIM)
        self._safe_addstr(stdscr, y, L1 + len(label) + 1, str(value), val_col | curses.A_BOLD)

        if label2 is not None:
            self._safe_addstr(stdscr, y, C2, f'{label2}', curses.A_DIM)
            self._safe_addstr(stdscr, y, C2 + len(label2) + 1,
                              str(value2), (val2_col or val_col) | curses.A_BOLD)

        if label3 is not None:
            self._safe_addstr(stdscr, y, C3, f'{label3}', curses.A_DIM)
            self._safe_addstr(stdscr, y, C3 + len(label3) + 1,
                              str(value3), (val3_col or val_col) | curses.A_BOLD)

    def _divider(self, stdscr, y, w):
        """Thin horizontal divider line."""
        self._safe_addstr(stdscr, y, 2, '─' * max(0, w - 4), curses.A_DIM)

    def _section(self, stdscr, y, w, title, ACCENT, DIM, BOLD):
        """Section header — accent-coloured left label + thin rule."""
        lbl  = f' {title} '
        fill = max(0, min(w - 6, 70) - len(lbl))
        line = f'  ──{lbl}' + '─' * fill
        self._safe_addstr(stdscr, y, 0, line, ACCENT | BOLD)
        return y + 1

    def _spacer(self, y):
        return y + 1

    def _bar(self, pct, width=20):
        pct    = max(0.0, min(100.0, pct))
        filled = int(width * pct / 100)
        return '█' * filled + '░' * (width - filled)

    # ─────────────────────────────────────────────────────────────────────────
    # PAGE 1 — STATUS
    #   Node identity · NAT · IP · version · uptime
    #   Resource bars (CPU / RAM / Disk)
    #   Active clients + services
    #   Node Quality (score, uptime bars, latency)
    # ─────────────────────────────────────────────────────────────────────────
    # ─────────────────────────────────────────────────────────────────────────
    # CONFIG OVERLAY — fetch / apply / reset / draw
    # ─────────────────────────────────────────────────────────────────────────

    def _draw_health_panel(self, stdscr, h, w, GREEN, YELLOW, RED, WHITE, ACCENT, DIM, BOLD):
        """Draw the system health overlay.
        Shows all 13 subsystems with status, allows fix/persist/unpersist actions.
        Keys: ↑↓=select  1=scan  f=fix  3=fix all  p=persist  4=persist all
              u=unpersist  5=unpersist all  2=back from results  ESC=close
        """
        pw = min(w - 4, 80)
        ph = min(h - 4, 32)
        py = max(0, (h - ph) // 2)
        px = max(0, (w - pw) // 2)

        try:
            for row in range(ph):
                stdscr.addstr(py + row, px, ' ' * pw)
            stdscr.addstr(py,          px, '╔' + '═' * (pw - 2) + '╗', ACCENT | BOLD)
            stdscr.addstr(py + ph - 1, px, '╚' + '═' * (pw - 2) + '╝', ACCENT | BOLD)
            for row in range(1, ph - 1):
                stdscr.addstr(py + row, px,          '║', ACCENT)
                stdscr.addstr(py + row, px + pw - 1, '║', ACCENT)
        except curses.error:
            pass

        self._safe_addstr(stdscr, py, px + 2, ' ● System Health ', ACCENT | BOLD)
        self._safe_addstr(stdscr, py, px + pw - 8, ' ESC=close ', DIM)

        inner_w = pw - 4
        y = py + 1
        subs = self.metrics.get('systemHealth', {}).get('subsystems', []) if self.metrics else []

        if self.health_last_result:
            # Results view
            self._safe_addstr(stdscr, y, px + 2,
                              '  Results (↑↓ scroll, 2=back):', ACCENT)
            y += 1
            lines = []
            for r in self.health_last_result.get('results', []):
                name    = r.get('name', '')
                status  = r.get('status', '')
                actions = r.get('actions_taken', [])
                lines.append(f'  {name}: {status}')
                for a in actions:
                    lines.append(f'    · {a}')

            scroll = getattr(self, 'health_result_scroll', 0)
            for line in lines[scroll:scroll + ph - 5]:
                if y >= py + ph - 1:
                    break
                col = GREEN if 'ok' in line.lower() or '✓' in line else \
                      RED   if 'fail' in line.lower() or '✗' in line else WHITE
                self._safe_addstr(stdscr, y, px + 2, line[:inner_w], col)
                y += 1
        else:
            # Subsystem list view
            self._safe_addstr(stdscr, y, px + 2,
                              '  1=scan  f=fix  3=fix all  p=persist  4=pers all  '
                              'u=unpers  5=unpers all', DIM)
            y += 1

            # Status message
            if self.health_message and (time.time() - self.health_msg_time) < 8:
                mc = GREEN if '✓' in self.health_message else \
                     YELLOW if '⏳' in self.health_message else RED
                self._safe_addstr(stdscr, y, px + 2,
                                  f'  {self.health_message}'[:inner_w], mc | BOLD)
            y += 1

            visible = ph - 5
            start   = max(0, self.health_selected - visible + 1)
            for i, sub in enumerate(subs[start:start + visible]):
                real_idx = i + start
                if y >= py + ph - 1:
                    break
                sel     = real_idx == self.health_selected
                name    = sub.get('name', '?')
                status  = sub.get('status', '?')
                persist = '🔒' if sub.get('persisted') else ''
                prefix  = '▶ ' if sel else '  '
                col     = GREEN if status == 'ok' else \
                          YELLOW if status == 'warning' else \
                          RED    if status in ('error', 'critical') else WHITE
                line    = f'{prefix}{name}: {status} {persist}'
                self._safe_addstr(stdscr, y, px + 2, line[:inner_w],
                                  (col | BOLD) if sel else col)
                y += 1

        overall = self.metrics.get('systemHealth', {}).get('overall', '?') if self.metrics else '?'
        oc = GREEN if overall == 'ok' else YELLOW if overall == 'warning' else RED
        self._safe_addstr(stdscr, py + ph - 1, px + 2,
                          f' overall: {overall} ', oc | BOLD)

    def _draw_help_panel(self, stdscr, h, w, GREEN, YELLOW, RED, WHITE, ACCENT, DIM, BOLD):
        """Draw the help overlay with key bindings and field explanations.
        Keys: ↑↓ scroll  ESC=close
        """
        pw = min(w - 4, 76)
        ph = min(h - 4, 32)
        py = max(0, (h - ph) // 2)
        px = max(0, (w - pw) // 2)

        try:
            for row in range(ph):
                stdscr.addstr(py + row, px, ' ' * pw)
            stdscr.addstr(py,          px, '╔' + '═' * (pw - 2) + '╗', ACCENT | BOLD)
            stdscr.addstr(py + ph - 1, px, '╚' + '═' * (pw - 2) + '╝', ACCENT | BOLD)
            for row in range(1, ph - 1):
                stdscr.addstr(py + row, px,          '║', ACCENT)
                stdscr.addstr(py + row, px + pw - 1, '║', ACCENT)
        except curses.error:
            pass

        self._safe_addstr(stdscr, py, px + 2, ' ? Help ', ACCENT | BOLD)
        self._safe_addstr(stdscr, py, px + pw - 8, ' ESC=close ', DIM)

        inner_w = pw - 4
        lines = [
            ('head', 'Key Bindings'),
            ('key',  '1 / 2',         'Switch page (Status / Earnings)'),
            ('key',  'Tab',            'Cycle to next page'),
            ('key',  'r',              'Refresh data now'),
            ('key',  't',              'Cycle colour theme'),
            ('key',  'T',              'Test node (live Discovery probe)'),
            ('key',  'h',              'Toggle health overlay'),
            ('key',  'c',              'Toggle payment config overlay'),
            ('key',  '?',              'Toggle this help'),
            ('key',  'w',              'Restart Mysterium node'),
            ('key',  '$',              'Settle MYST on-chain'),
            ('key',  '+  /  -',        'Increase / decrease refresh interval'),
            ('key',  'q  /  ESC',      'Quit CLI'),
            ('blank','',''),
            ('head', 'Pages'),
            ('item', '1 Status',       'Node info, NAT, IP, quality, resources, uptime'),
            ('item', '2 Earnings',     'Balance, daily/weekly/monthly, history chart'),
            ('blank','',''),
            ('head', 'Earnings fields'),
            ('item', 'Unsettled',      'Earned, not yet settled on-chain'),
            ('item', 'Lifetime Gross', 'All-time cumulative, pre-fee (never decreases)'),
            ('item', 'Daily',          'Snapshot delta: last 24h (needs 24h of history)'),
            ('item', 'Weekly',         'Snapshot delta: last 7d  (needs 7d of history)'),
            ('item', 'Monthly',        'Snapshot delta: last 30d (needs 30d of history)'),
            ('item', 'BUILDING',       'Not enough history yet — accumulating snapshots'),
            ('item', 'RATE LIMITED',   'Identity API blocked — history paused'),
            ('item', 'TRACKED',        'Delta tracking active — values from snapshot DB'),
            ('blank','',''),
            ('head', 'Config overlay (c)'),
            ('item', 'e',              'Edit selected setting'),
            ('item', 'a',              'Apply selected setting to node'),
            ('item', 'z',              'Apply all pending settings'),
            ('item', 'n',              'Load defaults preset'),
            ('item', 'm',              'Load high-traffic preset (50+ sessions)'),
            ('item', 'x',              'Reset selected setting to node default'),
        ]

        scroll    = getattr(self, '_help_scroll', 0)
        visible   = ph - 2
        max_scroll = max(0, len(lines) - visible)
        if not hasattr(self, '_help_scroll'):
            self._help_scroll = 0
        self._help_scroll = min(self._help_scroll, max_scroll)

        y = py + 1
        for kind, *parts in lines[scroll:scroll + visible]:
            if y >= py + ph - 1:
                break
            if kind == 'head':
                self._safe_addstr(stdscr, y, px + 2,
                                  f'  ── {parts[0]} ──'[:inner_w], ACCENT | BOLD)
            elif kind == 'key':
                self._safe_addstr(stdscr, y, px + 2,
                                  f'  {parts[0]:<14}'[:inner_w // 2], ACCENT)
                self._safe_addstr(stdscr, y, px + 2 + 16,
                                  parts[1][:inner_w - 18], WHITE)
            elif kind == 'item':
                self._safe_addstr(stdscr, y, px + 2,
                                  f'  {parts[0]:<14}'[:inner_w // 2], GREEN)
                self._safe_addstr(stdscr, y, px + 2 + 16,
                                  parts[1][:inner_w - 18], DIM)
            y += 1

        self._safe_addstr(stdscr, py + ph - 1, px + 2,
                          f' ↑↓ scroll  {scroll + 1}/{len(lines)} ', DIM)

    def _fetch_config_values(self):
        """Fetch current payment config values from backend /node/config/current.
        Populates self._config_current with key→value pairs.
        Called when the user opens the config overlay (c key).
        Non-blocking: runs in a background thread so the UI stays responsive.
        On error: _config_current stays as-is (last known or empty).
        """
        import threading
        def _fetch():
            try:
                resp = requests.get(
                    f'{self.base_url}/node/config/current',
                    headers=self._auth_headers(),
                    timeout=5,
                )
                if resp.ok:
                    data = resp.json()
                    self._config_current = data.get('current', {})
            except Exception:
                pass
        threading.Thread(target=_fetch, daemon=True).start()

    def _apply_config_key(self, key):
        """Send a single config key+value to backend /node/config/set.
        Uses the pending value if set, otherwise the current value.
        Runs in a background thread. Updates _config_results with 'ok' or error string.
        A node restart is required after applying — shown in the overlay.
        """
        import threading
        value = self._config_pending.get(key, self._config_current.get(key, ''))
        if not value and value != 0:
            self._config_results[key] = 'no value'
            return
        self._config_applying.add(key)
        self._config_results[key] = '⏳'
        def _apply():
            try:
                resp = requests.post(
                    f'{self.base_url}/node/config/set',
                    headers=self._auth_headers(),
                    json={'key': key, 'value': str(value)},
                    timeout=10,
                )
                data = resp.json()
                self._config_results[key] = 'ok' if data.get('success') else (data.get('error') or 'failed')
            except Exception as e:
                self._config_results[key] = str(e)[:40]
            finally:
                self._config_applying.discard(key)
        threading.Thread(target=_apply, daemon=True).start()

    def _apply_config_reset(self, key):
        """Reset a single config key to node default via backend /node/config/reset.
        Runs in a background thread. Clears any pending value for this key.
        Updates _config_results with 'ok' or error string.
        """
        import threading
        self._config_pending.pop(key, None)
        self._config_applying.add(key)
        self._config_results[key] = '⏳'
        def _reset():
            try:
                resp = requests.post(
                    f'{self.base_url}/node/config/reset',
                    headers=self._auth_headers(),
                    json={'key': key},
                    timeout=10,
                )
                data = resp.json()
                if data.get('success'):
                    self._config_results[key] = 'ok (reset)'
                    # Refresh displayed values after reset
                    self._fetch_config_values()
                else:
                    self._config_results[key] = data.get('error') or 'failed'
            except Exception as e:
                self._config_results[key] = str(e)[:40]
            finally:
                self._config_applying.discard(key)
        threading.Thread(target=_reset, daemon=True).start()

    def _draw_config_panel(self, stdscr, h, w, GREEN, YELLOW, RED, WHITE, ACCENT, DIM, BOLD):
        """Draw the payment config overlay on top of the main dashboard.

        Phase 1 — Read/scroll: shows current values, scroll to bottom to continue.
        Phase 2 — Edit:        arrow keys select setting, e=edit, a=apply,
                                z=apply all, n=defaults preset, m=high-traffic preset,
                                x=reset to node default, ESC=close.

        All backend calls are non-blocking (background threads).
        A restart hint is shown after any successful apply.
        """
        pw = min(w - 4, 80)
        ph = min(h - 4, 30)
        py = max(0, (h - ph) // 2)
        px = max(0, (w - pw) // 2)

        # Draw panel border
        try:
            for row in range(ph):
                stdscr.addstr(py + row, px, ' ' * pw)
            stdscr.addstr(py,          px, '╔' + '═' * (pw - 2) + '╗', ACCENT | BOLD)
            stdscr.addstr(py + ph - 1, px, '╚' + '═' * (pw - 2) + '╝', ACCENT | BOLD)
            for row in range(1, ph - 1):
                stdscr.addstr(py + row, px,          '║', ACCENT)
                stdscr.addstr(py + row, px + pw - 1, '║', ACCENT)
        except curses.error:
            pass

        title = ' ⚙  Node Payment Config '
        self._safe_addstr(stdscr, py, px + 2, title, ACCENT | BOLD)
        self._safe_addstr(stdscr, py, px + pw - 8, ' ESC=close ', DIM)

        inner_w = pw - 4
        y = py + 1

        if self._config_phase == 1:
            # ── Phase 1: read current values ────────────────────────────────
            lines = []
            lines.append(('header', 'Current payment config values (read-only in this view):'))
            lines.append(('blank', ''))
            for meta in CONFIG_KEYS_META:
                key   = meta['key']
                val   = self._config_current.get(key, '—')
                src   = '(default)' if self._config_current.get(f'{key}.__source') == 'default' else ''
                label = meta['label']
                unit  = meta['unit']
                desc  = meta['desc']
                lines.append(('setting', f"  {label}: {val} {unit}  {src}"))
                lines.append(('desc',    f"    {desc}"))
                lines.append(('blank',   ''))
            lines.append(('hint', '  Scroll to bottom then press SPACE or ENTER to edit settings.'))

            visible_lines = ph - 3
            max_scroll    = max(0, len(lines) - visible_lines)
            self._config_scroll = min(self._config_scroll, max_scroll)
            at_bottom = self._config_scroll >= max_scroll
            if at_bottom:
                self._config_scrolled_bottom = True

            for i, (kind, text) in enumerate(lines[self._config_scroll:self._config_scroll + visible_lines]):
                if y >= py + ph - 1:
                    break
                col = WHITE
                if kind == 'header':
                    col = ACCENT | BOLD
                elif kind == 'setting':
                    col = GREEN
                elif kind == 'desc':
                    col = DIM
                elif kind == 'hint':
                    col = YELLOW
                self._safe_addstr(stdscr, y, px + 2, text[:inner_w], col)
                y += 1

            scroll_hint = f'↑↓ scroll  {self._config_scroll + 1}/{len(lines)}'
            if at_bottom:
                scroll_hint += '  SPACE/ENTER → edit'
            self._safe_addstr(stdscr, py + ph - 1, px + 2, scroll_hint[:inner_w], DIM)

        else:
            # ── Phase 2: edit settings ───────────────────────────────────────
            self._safe_addstr(stdscr, y, px + 2,
                              '  ↑↓=select  e=edit  a=apply  z=apply all  '
                              'n=defaults  m=high-traffic  x=reset  ESC=close',
                              DIM)
            y += 1
            self._safe_addstr(stdscr, y, px + 2,
                              '  ⚠ Node restart required after applying changes.',
                              YELLOW)
            y += 2

            visible_items = ph - 6
            start_idx = max(0, self._config_cursor - visible_items + 1)

            for i, meta in enumerate(CONFIG_KEYS_META[start_idx:start_idx + visible_items]):
                real_idx = i + start_idx
                if y >= py + ph - 1:
                    break
                key    = meta['key']
                label  = meta['label']
                unit   = meta['unit']
                cur    = self._config_current.get(key, '—')
                pend   = self._config_pending.get(key)
                result = self._config_results.get(key, '')
                sel    = real_idx == self._config_cursor

                # Prefix: cursor indicator
                prefix = '▶ ' if sel else '  '
                # Value: show pending if different from current
                if pend is not None and str(pend) != str(cur):
                    val_str = f'{cur} → {pend} {unit}'
                    val_col = YELLOW
                else:
                    val_str = f'{cur} {unit}'
                    val_col = GREEN if sel else WHITE

                # Result indicator
                res_col = GREEN if result == 'ok' or 'reset' in result else \
                          YELLOW if result == '⏳' else \
                          RED    if result and result not in ('no value', '') else DIM
                res_str = f'  [{result}]' if result else ''

                line = f'{prefix}{label}: {val_str}{res_str}'
                self._safe_addstr(stdscr, y, px + 2, line[:inner_w],
                                  (ACCENT | BOLD) if sel else val_col)

                # Inline edit buffer on selected row
                if sel and self._config_editing:
                    edit_str = f'  → editing: {self._config_edit_buf}_'
                    self._safe_addstr(stdscr, y, px + 2 + len(line[:inner_w // 2]),
                                      edit_str[:inner_w // 2], CYAN | BOLD)
                y += 1

    # ─────────────────────────────────────────────────────────────────────────
    # PAGES
    # ─────────────────────────────────────────────────────────────────────────
    def _draw_page1(self, stdscr, y, ymax, w, m, GREEN, YELLOW, RED, WHITE, ACCENT, DIM, BOLD, compact=False):
        """PAGE 1 — STATUS: node identity, resources, quality."""
        ns   = m.get('nodeStatus', {})
        res  = m.get('resources', {})
        nq   = m.get('nodeQuality', {})
        cli  = m.get('clients', {})
        svc  = m.get('services', {})
        sess = m.get('sessions', {})

        status   = ns.get('status', 'unknown')
        s_col    = GREEN if status == 'online' else (YELLOW if status == 'degraded' else RED)
        nat      = ns.get('nat_type', '—')
        pub_ip   = ns.get('public_ip', '—')
        node_ver = ns.get('version', '—')
        uptime   = format_uptime(ns.get('uptime', ''))
        nodes_on = ns.get('nodes_online', 1)
        nodes_tot= ns.get('nodes_total', 1)

        y = self._spacer(y)

        # ── Node Status ───────────────────────────────────────────────────
        y = self._section(stdscr, y, w, 'NODE', ACCENT, DIM, BOLD)

        if y < ymax:
            st_txt = status.upper()
            if nodes_tot > 1:
                st_txt += f'  ({nodes_on}/{nodes_tot} nodes)'
            self._safe_addstr(stdscr, y, 4,  'Status:', DIM)
            self._safe_addstr(stdscr, y, 12, st_txt, s_col | BOLD)
            if uptime:
                self._safe_addstr(stdscr, y, 12 + len(st_txt) + 2, f'up {uptime}', DIM)
            y += 1

        if y < ymax:
            self._safe_addstr(stdscr, y, 4,  'NAT Type:', DIM)
            nat_c = GREEN if 'cone' in nat.lower() else (YELLOW if nat and nat != '—' else DIM)
            self._safe_addstr(stdscr, y, 14, nat, nat_c | BOLD)
            C2 = min(w // 2, 40)
            self._safe_addstr(stdscr, y, C2, 'IP:', DIM)
            self._safe_addstr(stdscr, y, C2 + 4, pub_ip, WHITE | BOLD)
            y += 1

        if y < ymax:
            self._safe_addstr(stdscr, y, 4,  'Version:', DIM)
            self._safe_addstr(stdscr, y, 13, node_ver, ACCENT | BOLD)
            connected      = cli.get('connected', 0)
            peak           = cli.get('peak', 0)
            active_sessions= sess.get('active', 0) if 'sessions' in m else connected
            C2 = min(w // 2, 40)
            self._safe_addstr(stdscr, y, C2, 'Clients:', DIM)
            cc = GREEN if connected > 0 else WHITE
            self._safe_addstr(stdscr, y, C2 + 9, str(connected), cc | BOLD)
            if active_sessions > connected:
                self._safe_addstr(stdscr, y, C2 + 11, f' · {active_sessions} sessions', DIM)
            else:
                self._safe_addstr(stdscr, y, C2 + 11, f' peak {peak}', DIM)
            y += 1

        if svc.get('total', 0) > 0 and y < ymax:
            self._safe_addstr(stdscr, y, 4, 'Services:', DIM)
            svc_c = GREEN if svc.get('active', 0) > 0 else YELLOW
            self._safe_addstr(stdscr, y, 14, f'{svc.get("active",0)} running', svc_c | BOLD)
            self._safe_addstr(stdscr, y, 26, f'/ {svc.get("total",0)} total', DIM)
            y += 1

        y = self._spacer(y)

        # ── Resources ─────────────────────────────────────────────────────
        y = self._section(stdscr, y, w, 'RESOURCES', ACCENT, DIM, BOLD)

        cpu   = res.get('cpu', 0)
        ram   = res.get('ram', 0)
        disk  = res.get('disk', 0)
        all_t = res.get('all_temps', [])

        def _color_pct(p, hi=90, med=70):
            return GREEN if p < med else (YELLOW if p < hi else RED)
        def _color_temp(t):
            return GREEN if t < 60 else (YELLOW if t < 80 else RED)

        bar_w = min(20, max(10, w // 5))
        for label, pct, tkey in [('CPU ', cpu, 'cpu'), ('RAM ', ram, 'mem'), ('Disk', disk, None)]:
            if y >= ymax:
                break
            col  = _color_pct(pct)
            bar  = self._bar(pct, bar_w)
            temp = next((t['value'] for t in all_t
                         if tkey and tkey in t.get('label','').lower()), None)
            self._safe_addstr(stdscr, y, 4,  label, DIM)
            self._safe_addstr(stdscr, y, 9,  f'[{bar}]', col)
            self._safe_addstr(stdscr, y, 11 + bar_w, f'{pct:5.1f}%', col | BOLD)
            if temp is not None:
                tc = _color_temp(temp)
                self._safe_addstr(stdscr, y, 19 + bar_w, f'{temp:.0f}°C', tc | BOLD)
            y += 1

        # Extra temps (ambient etc.)
        extra = [t for t in all_t if 'cpu' not in t.get('label','').lower()
                                  and 'mem' not in t.get('label','').lower()]
        if extra and y < ymax and not compact:
            parts = [f"{t['label']}: {t['value']:.0f}°C" for t in extra[:4]]
            self._safe_addstr(stdscr, y, 4, '  '.join(parts), DIM)
            y += 1

        y = self._spacer(y)

        # ── Node Quality ──────────────────────────────────────────────────
        if nq.get('available') and y < ymax:
            y = self._section(stdscr, y, w, 'NODE QUALITY', ACCENT, DIM, BOLD)

            score = nq.get('quality_score')
            if score is not None and y < ymax:
                sc  = GREEN if score >= 2.0 else (YELLOW if score >= 1.0 else RED)
                bars = min(3, max(0, round(score)))
                bstr = '▮' * bars + '▯' * (3 - bars)
                self._safe_addstr(stdscr, y, 4,  'Score:', DIM)
                self._safe_addstr(stdscr, y, 11, f'{score:.2f} / 3.00', sc | BOLD)
                self._safe_addstr(stdscr, y, 26, bstr, sc | BOLD)
                mon = '  ● Monitoring OK' if not nq.get('monitoring_failed') else '  ▲ Monitoring FAILED'
                mc  = GREEN if not nq.get('monitoring_failed') else RED
                self._safe_addstr(stdscr, y, 29, mon, mc)
                y += 1

            lat = nq.get('latency_ms'); bw_q = nq.get('bandwidth_mbps')
            if (lat is not None or bw_q is not None) and y < ymax:
                if lat is not None:
                    lc = GREEN if lat < 100 else (YELLOW if lat < 300 else RED)
                    self._safe_addstr(stdscr, y, 4,  'Latency:', DIM)
                    self._safe_addstr(stdscr, y, 13, f'{lat:.0f} ms', lc | BOLD)
                if bw_q is not None:
                    bc = GREEN if bw_q >= 10 else (YELLOW if bw_q >= 2 else RED)
                    C2 = min(w // 2, 40)
                    self._safe_addstr(stdscr, y, C2, 'Link:', DIM)
                    self._safe_addstr(stdscr, y, C2 + 6, f'{bw_q:.1f} Mbit/s', bc | BOLD)
                y += 1

            def _ubar(lbl, pct):
                nonlocal y
                if pct is None or y >= ymax:
                    return
                uc  = GREEN if pct >= 90 else (YELLOW if pct >= 70 else RED)
                bar = self._bar(pct, bar_w)
                self._safe_addstr(stdscr, y, 4,  f'{lbl:<12}', DIM)
                self._safe_addstr(stdscr, y, 16, f'[{bar}]', uc)
                self._safe_addstr(stdscr, y, 18 + bar_w, f'{pct:5.1f}%', uc | BOLD)
                y += 1

            t_days = nq.get('tracking_days', 0) or 0
            _ubar('24h network', nq.get('uptime_24h_net'))
            if nq.get('uptime_24h_net') is None:
                _ubar('24h local',   nq.get('uptime_24h_local'))
            _ubar(f'{t_days}d online' if t_days < 30 else '30d online',
                  nq.get('uptime_30d_local'))

            pl = nq.get('packet_loss_net')
            if pl is not None and y < ymax:
                pc  = GREEN if pl == 0 else (YELLOW if pl < 2 else RED)
                self._safe_addstr(stdscr, y, 4,  'Packet loss:', DIM)
                self._safe_addstr(stdscr, y, 17, f'{pl:.1f}%', pc | BOLD)
                self._safe_addstr(stdscr, y, 24, f'  Connected: {100 - pl:.1f}%', pc)
                y += 1

    # ─────────────────────────────────────────────────────────────────────────
    # PAGE 2 — EARNINGS
    #   Unsettled · Lifetime Gross · Settled Balance
    #   Daily / Weekly / Monthly tracked
    #   Earnings history mini-chart (last 30 days)
    # ─────────────────────────────────────────────────────────────────────────
    def _draw_page2(self, stdscr, y, ymax, w, m, GREEN, YELLOW, RED, WHITE, ACCENT, DIM, BOLD, compact=False):
        earn  = m.get('earnings', {})

        raw_uns   = earn.get('unsettled', 0) or 0
        ses_total = earn.get('session_total', 0) or 0
        lifetime  = earn.get('lifetime', 0) or 0
        balance   = earn.get('balance', 0) or 0
        src       = earn.get('earnings_source', 'sessions')
        is_trk    = src == 'delta'
        is_rl     = src == 'rate_limited'
        is_bld    = src in ('building', 'sessions')
        wallet    = earn.get('wallet_address', '')

        def _fe(v): return f'{float(v):.4f}' if v is not None else '—'

        y = self._spacer(y)
        y = self._section(stdscr, y, w, 'CURRENT BALANCE', ACCENT, DIM, BOLD)

        # Unsettled / session
        if y < ymax:
            if raw_uns > 0:
                self._safe_addstr(stdscr, y, 4,  'Unsettled:', DIM)
                self._safe_addstr(stdscr, y, 15, f'{_fe(raw_uns)} MYST', GREEN | BOLD)
                self._safe_addstr(stdscr, y, 30, '← not yet on-chain', DIM)
            elif ses_total > 0:
                self._safe_addstr(stdscr, y, 4,  'Session:', DIM)
                self._safe_addstr(stdscr, y, 13, f'{_fe(ses_total)} MYST', YELLOW | BOLD)
                self._safe_addstr(stdscr, y, 28, '← pending promises', DIM)
            else:
                self._safe_addstr(stdscr, y, 4,  'Unsettled:', DIM)
                self._safe_addstr(stdscr, y, 15, '0.0000 MYST', DIM)
            y += 1

        if y < ymax:
            self._safe_addstr(stdscr, y, 4,  'Settled:', DIM)
            bal_c = ACCENT if balance > 0 else DIM
            self._safe_addstr(stdscr, y, 13, f'{_fe(balance)} MYST', bal_c | BOLD)
            self._safe_addstr(stdscr, y, 28, '← withdrawable', DIM)
            y += 1

        if y < ymax:
            self._safe_addstr(stdscr, y, 4,  'Lifetime:', DIM)
            self._safe_addstr(stdscr, y, 14, f'{_fe(lifetime)} MYST', ACCENT)
            self._safe_addstr(stdscr, y, 30, '← gross, pre-fee', DIM)
            y += 1

        if wallet and y < ymax:
            self._safe_addstr(stdscr, y, 4,  'Identity:', DIM)
            self._safe_addstr(stdscr, y, 14, short_addr(wallet), DIM)
            y += 1

        y = self._spacer(y)

        # ── Tracked periods ───────────────────────────────────────────────
        y = self._section(stdscr, y, w, 'TRACKED EARNINGS', ACCENT, DIM, BOLD)

        _daily  = earn.get('daily')
        _weekly = earn.get('weekly')
        _mthly  = earn.get('monthly')

        if is_rl and y < ymax:
            self._safe_addstr(stdscr, y, 4, '▲ Identity API rate-limited — history paused', YELLOW | BOLD)
            y += 1
            self._safe_addstr(stdscr, y, 4, f'Session approx: {_fe(ses_total)} MYST  (raw token sum, not exact)', YELLOW)
            y += 1
        elif is_bld and y < ymax:
            self._safe_addstr(stdscr, y, 4, '[BUILDING]', YELLOW | BOLD)
            self._safe_addstr(stdscr, y, 15, 'collecting history — needs 24h for daily, 7d for weekly', DIM)
            y += 1
        elif is_trk and y < ymax:
            self._safe_addstr(stdscr, y, 4, '[TRACKED]', GREEN | BOLD)
            self._safe_addstr(stdscr, y, 14, 'delta-based — blockchain accurate', DIM)
            y += 1

        if y < ymax and not is_bld:
            col = w // 3

            def _period_str(v):
                if v is None: return '—'
                return f'{float(v):.4f}'

            self._safe_addstr(stdscr, y, 4,     'Daily:', DIM)
            dc = (GREEN if _daily is not None else DIM)
            self._safe_addstr(stdscr, y, 11,    _period_str(_daily), dc | BOLD)
            self._safe_addstr(stdscr, y, col,   'Weekly:', DIM)
            wc = (GREEN if _weekly is not None else DIM)
            self._safe_addstr(stdscr, y, col+8, _period_str(_weekly), wc | BOLD)
            self._safe_addstr(stdscr, y, col*2, 'Monthly:', DIM)
            mc2 = (GREEN if _mthly is not None else DIM)
            self._safe_addstr(stdscr, y, col*2+9, _period_str(_mthly), mc2 | BOLD)
            y += 1

        y = self._spacer(y)

        # ── Mini bar chart ─────────────────────────────────────────────────
        chart      = m.get('earnings_chart', {})
        chart_days = chart.get('daily', [])
        if chart_days and y < ymax - 4:
            y = self._section(stdscr, y, w, 'EARNINGS HISTORY  (daily · last 30d)', ACCENT, DIM, BOLD)
            bar_area = max(10, w - 6)
            recent   = chart_days[-bar_area:]
            if recent:
                max_e = max((d.get('earned', 0) for d in recent), default=0.0001) or 0.0001
                bar_h = min(5, ymax - y - 2)
                try:
                    from datetime import date as _date
                    today_str = _date.today().isoformat()
                except Exception:
                    today_str = ''
                col_chars = []
                for d in recent:
                    e    = d.get('earned', 0)
                    fill = int(round((e / max_e) * bar_h)) if max_e > 0 else 0
                    col_chars.append((fill, d.get('date','') == today_str, e))
                for row in range(bar_h - 1, -1, -1):
                    if y >= ymax: break
                    for col_idx, (filled, is_today, earned) in enumerate(col_chars):
                        ch  = '█' if filled > row else ' '
                        col = ACCENT if is_today else (GREEN if earned > 0 else DIM)
                        if 2 + col_idx < w:
                            self._safe_addstr(stdscr, y, 2 + col_idx, ch, col)
                    y += 1
                if y < ymax and recent:
                    lbl_l = recent[0].get('date','')[-5:]
                    lbl_r = recent[-1].get('date','')[-5:]
                    self._safe_addstr(stdscr, y, 2, lbl_l, DIM)
                    self._safe_addstr(stdscr, y, max(2, 2 + len(recent) - 5), lbl_r, DIM)
                    y += 1

    # ─────────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description='Mysterium Node Monitor — Terminal UI')
    parser.add_argument('--url',      default='http://localhost:5000', help='Toolkit backend URL')
    parser.add_argument('--port',     type=int, default=None,          help='Backend port (overrides --url port)')
    parser.add_argument('--interval', type=int, default=10,            help='Refresh interval in seconds (default: 10)')
    parser.add_argument('--api-key',  default=None,                    help='Dashboard API key')
    parser.add_argument('--theme',    default='emerald',               help='Color theme (default: emerald)')
    args = parser.parse_args()

    base_url = args.url
    if args.port:
        from urllib.parse import urlparse, urlunparse
        p = urlparse(base_url)
        base_url = urlunparse(p._replace(netloc=f'{p.hostname}:{args.port}'))

    # Auto-load API key from setup.json if not provided
    api_key = args.api_key
    if not api_key:
        try:
            import json
            from pathlib import Path
            cfg_path = Path(__file__).parent.parent / 'config' / 'setup.json'
            if cfg_path.exists():
                cfg = json.loads(cfg_path.read_text())
                api_key = cfg.get('api_key') or cfg.get('dashboard_api_key') or None
        except Exception:
            pass

    dashboard = CLIDashboard(
        base_url=base_url,
        interval=args.interval,
        api_key=api_key,
        theme=args.theme,
    )
    try:
        curses.wrapper(dashboard.run)
    except KeyboardInterrupt:
        pass

if __name__ == '__main__':
    main()
