"""
Mysterium Node Monitoring API Backend
====================================
Complete monitoring system that collects metrics from Mysterium Node TequilAPI.
Configured via setup wizard for easy user setup.
"""

import os
import json
import copy
import time
import shutil
import sqlite3
import psutil
import subprocess
import requests
import base64
import logging
from datetime import datetime, timezone, timedelta
from functools import wraps
from collections import deque
from threading import Thread, Lock
from pathlib import Path

from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv

# System health module
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
try:
    import system_health
except ImportError:
    system_health = None

# ============ VERSION ============
_VERSION_FILE = Path(__file__).parent.parent / 'VERSION'
APP_VERSION = _VERSION_FILE.read_text().strip() if _VERSION_FILE.exists() else 'unknown'

# ============ ENSURE DIRECTORIES EXIST ============
Path('logs').mkdir(parents=True, exist_ok=True)
Path('config').mkdir(parents=True, exist_ok=True)

# ============ PERSISTENT VPN TRAFFIC TRACKER ============
class VpnTrafficSnapshot:
    """Simple VPN traffic snapshot — NO persistent accumulation.

    Why: The old VpnTrafficTracker accumulated phantom data because myst* interfaces
    are ephemeral (created/destroyed per consumer). Each disconnect looked like a
    "counter reset" and inflated baselines.

    New approach:
    - "Today" and "Month" come from vnstat (if it tracks myst* interfaces)
    - If no vnstat, show psutil counters labeled "since service start"
    - Per-interface breakdown always from psutil (real-time, accurate)
    """
    _lock = Lock()

    @classmethod
    def get_snapshot(cls):
        """Return current psutil VPN counters as-is. No baseline magic."""
        with cls._lock:
            rx_total = 0
            tx_total = 0
            iface_details = {}
            try:
                per_nic = psutil.net_io_counters(pernic=True)
                for name, c in per_nic.items():
                    if any(name.startswith(p) for p in ('myst', 'wg', 'tun')):
                        rx_total += c.bytes_recv
                        tx_total += c.bytes_sent
                        iface_details[name] = {
                            'rx': c.bytes_recv,
                            'tx': c.bytes_sent,
                        }
            except Exception:
                pass
            return rx_total, tx_total, iface_details

# ============ LOGGING SETUP ============
_log_level_str = os.getenv('LOG_LEVEL', 'INFO').upper()
_log_level = getattr(logging, _log_level_str, logging.INFO)
logging.basicConfig(
    level=_log_level,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    handlers=[
        logging.FileHandler('logs/backend.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ============ DATABASE MODULE IMPORTS ============
sys.path.insert(0, str(Path(__file__).parent))
try:
    from databases.quality_db import QualityDB
    logger.info("QualityDB loaded")
except Exception as e:
    logger.warning(f"QualityDB not available: {e}")
    QualityDB = None

try:
    from databases.system_metrics_db import SystemMetricsDB
    logger.info("SystemMetricsDB loaded")
except Exception as e:
    logger.warning(f"SystemMetricsDB not available: {e}")
    SystemMetricsDB = None

try:
    from databases.service_events_db import ServiceEventsDB
    logger.info("ServiceEventsDB loaded")
except Exception as e:
    logger.warning(f"ServiceEventsDB not available: {e}")
    ServiceEventsDB = None

try:
    from databases.data_manager import DataManager
    logger.info("DataManager loaded")
except Exception as e:
    logger.warning(f"DataManager not available: {e}")
    DataManager = None

# ============ LOAD ENVIRONMENT ============
load_dotenv()

# Load setup configuration
setup_config = {}
setup_config_path = Path('config/setup.json')
if setup_config_path.exists():
    try:
        with open(setup_config_path) as f:
            setup_config = json.load(f)
        logger.info("Loaded configuration from setup wizard")
    except Exception as e:
        logger.warning(f"Could not load setup config: {e}")

# ============ TIMEZONE ============
# All "today" and "this month" calculations use this timezone.
# Earnings snapshot timestamps stay in UTC — only display bucketing uses local tz.
#
# Priority: setup.json 'timezone' → OS /etc/localtime symlink → UTC
# Auto-detected timezone is written back to setup.json so it persists across restarts.
# After a git pull + restart the correct timezone is picked up automatically.

def _detect_system_tz() -> str:
    """Detect OS timezone from /etc/localtime symlink. Returns IANA name or 'UTC'."""
    try:
        import os as _os
        lt = _os.readlink('/etc/localtime')
        # Typical: /usr/share/zoneinfo/Europe/Brussels
        if 'zoneinfo/' in lt:
            tz = lt.split('zoneinfo/')[-1].strip('/')
            if tz:
                return tz
    except Exception:
        pass
    try:
        # Fallback: read /etc/timezone (Debian/Ubuntu)
        with open('/etc/timezone') as _f:
            tz = _f.read().strip()
            if tz:
                return tz
    except Exception:
        pass
    return 'UTC'

try:
    from zoneinfo import ZoneInfo
    _tz_name = setup_config.get('timezone') or ''
    _tz_source = 'config'
    if not _tz_name:
        _tz_name = _detect_system_tz()
        _tz_source = 'auto-detected'
        # Persist detected timezone to setup.json so it survives restarts/updates
        try:
            _cfg_data = {}
            if setup_config_path.exists():
                with open(setup_config_path) as _f:
                    _cfg_data = json.load(_f)
            if not _cfg_data.get('timezone'):
                _cfg_data['timezone'] = _tz_name
                with open(setup_config_path, 'w') as _f:
                    json.dump(_cfg_data, _f, indent=2)
                logger.info(f"Timezone auto-detected and saved to setup.json: {_tz_name}")
        except Exception as _save_e:
            logger.warning(f"Could not save timezone to setup.json: {_save_e}")
    TOOLKIT_TZ = ZoneInfo(_tz_name)
    logger.info(f"Toolkit timezone: {_tz_name} (source: {_tz_source})")
except Exception as _tz_e:
    from datetime import timezone as _dtz
    TOOLKIT_TZ = _dtz.utc
    logger.warning(f"Could not load timezone, falling back to UTC: {_tz_e}")

def local_now() -> datetime:
    """Current datetime in the configured toolkit timezone."""
    return datetime.now(TOOLKIT_TZ)

def local_today() -> str:
    """Today's date string (YYYY-MM-DD) in the configured toolkit timezone."""
    return local_now().strftime('%Y-%m-%d')

# ============ CONFIGURATION ============
node_host = setup_config.get('node_host', 'localhost')
node_port = setup_config.get('node_port', 4449)  # 4449 = standard Mysterium port
node_api_from_env = os.getenv('MYSTERIUM_NODE_API', '')

# Multi-node support:
# Option 1: MYSTERIUM_NODE_APIS=http://localhost:4449,http://localhost:4450
# Option 2: MYSTERIUM_NODE_PORTS=4449,4450 (assumes localhost)
# Option 3: Single MYSTERIUM_NODE_API=http://localhost:4449 (backwards compatible)
# Option 4: setup_config node_ports: [4449, 4450]
# Option 5: nodes.json file (v3.0.0 — full multi-node fleet monitoring)

def _normalize_url(url):
    """Strip trailing /api suffix so we have clean base URL"""
    url = url.strip().rstrip('/')
    if url.endswith('/api'):
        url = url[:-4]
    return url


# ============ NODES.JSON FLEET SYSTEM (v3.0.0) ============
NODES_JSON_PATHS = [
    Path('nodes.json'),
    Path('config/nodes.json'),
    Path(os.getenv('NODES_JSON', 'nodes.json')),
]

MULTI_NODE_MODE = False
_nodes_json_path = None
_nodes_json_mtime = 0
_node_registry = []  # List of {id, label, url, username, password}


def _load_nodes_json():
    """Load nodes.json if it exists. Returns list of node dicts or empty list.
    Format: [{"label": "My VPS", "url": "http://host:port"}, ...] or
            {"nodes": [{"label": ..., "url": ...}, ...]}
    """
    global _nodes_json_path, _nodes_json_mtime
    for p in NODES_JSON_PATHS:
        if p.exists():
            try:
                mtime = p.stat().st_mtime
                with open(p) as f:
                    data = json.load(f)
                nodes = data if isinstance(data, list) else data.get('nodes', [])
                result = []
                for i, n in enumerate(nodes):
                    if isinstance(n, str):
                        # Simple URL string
                        n = {'url': n}
                    if 'url' not in n:
                        continue
                    entry = {
                        'id': n.get('id', f'node{i}'),
                        'label': n.get('label', n.get('name', f'Node {i}')),
                        'url': _normalize_url(n['url']),
                        'username': n.get('username', NODE_USERNAME),
                        'password': n.get('password', NODE_PASSWORD),
                    }
                    # Peer mode fields — must be preserved for toolkit-to-toolkit comms
                    if n.get('toolkit_url'):
                        entry['toolkit_url'] = _normalize_url(n['toolkit_url'])
                    if n.get('toolkit_api_key'):
                        entry['toolkit_api_key'] = n['toolkit_api_key']
                    if n.get('toolkit_username'):
                        entry['toolkit_username'] = n['toolkit_username']
                    if n.get('toolkit_password'):
                        entry['toolkit_password'] = n['toolkit_password']
                    result.append(entry)
                if result:
                    _nodes_json_path = p
                    _nodes_json_mtime = mtime
                    logger.info(f"Loaded {len(result)} nodes from {p}")
                return result
            except Exception as e:
                logger.warning(f"Error loading {p}: {e}")
    return []


def _check_nodes_json_changed():
    """Hot-reload: check if nodes.json was modified since last load."""
    if _nodes_json_path and _nodes_json_path.exists():
        try:
            return _nodes_json_path.stat().st_mtime > _nodes_json_mtime
        except OSError:
            pass
    return False


def reload_node_registry():
    """Reload node registry from nodes.json. Returns True if multi-node mode active.

    IMPORTANT: NODE_API_URLS is NOT overwritten with fleet node URLs.
    The local background_collector uses NODE_API_URLS to poll the local node only.
    Fleet nodes are collected separately by multi_node_background_collector.
    Mixing them causes metrics_cache to contain data from remote nodes.
    """
    global MULTI_NODE_MODE, _node_registry
    loaded = _load_nodes_json()
    if loaded:
        _node_registry = loaded
        MULTI_NODE_MODE = True
        logger.info(f"Multi-node mode: {len(loaded)} nodes registered")
        return True
    return False


# ============ SINGLE-NODE CONFIGURATION (unchanged) ============
NODE_API_URLS = []

# Node TequilAPI credentials — declared here so _load_nodes_json can use them as defaults
NODE_USERNAME = os.getenv('MYSTERIUM_NODE_USERNAME', 'myst')
NODE_PASSWORD = os.getenv('MYSTERIUM_NODE_PASSWORD', setup_config.get('node_password', 'mystberry'))

# Check for multi-node env vars first
multi_apis = os.getenv('MYSTERIUM_NODE_APIS', '')
multi_ports = os.getenv('MYSTERIUM_NODE_PORTS', '')
config_ports = setup_config.get('node_ports', [])

if multi_apis:
    NODE_API_URLS = [_normalize_url(u) for u in multi_apis.split(',') if u.strip()]
elif multi_ports:
    NODE_API_URLS = [f"http://{node_host}:{p.strip()}" for p in multi_ports.split(',') if p.strip()]
elif config_ports:
    NODE_API_URLS = [f"http://{node_host}:{p}" for p in config_ports]
elif node_api_from_env:
    NODE_API_URLS = [_normalize_url(node_api_from_env)]
else:
    NODE_API_URLS = [f"http://{node_host}:{node_port}"]

# Try loading nodes.json — overrides all above if found
reload_node_registry()

# Keep single NODE_API_URL for backward compatibility (first node)
NODE_API_URL = NODE_API_URLS[0] if NODE_API_URLS else f"http://{node_host}:{node_port}"

API_KEY = os.getenv('DASHBOARD_API_KEY', setup_config.get('dashboard_api_key'))
USERNAME = os.getenv('DASHBOARD_USERNAME', setup_config.get('dashboard_username'))
PASSWORD = os.getenv('DASHBOARD_PASSWORD', setup_config.get('dashboard_password'))
ALLOW_NO_AUTH = os.getenv('ALLOW_NO_AUTH', 'false').lower() == 'true'

# Log auth source for debugging
_api_key_src = 'env' if os.getenv('DASHBOARD_API_KEY') else ('setup.json' if setup_config.get('dashboard_api_key') else 'none')
_pass_src = 'env' if os.getenv('DASHBOARD_PASSWORD') else ('setup.json' if setup_config.get('dashboard_password') else 'none')
if API_KEY:
    logger.info(f"Auth: API Key loaded from {_api_key_src} (last 6: ...{API_KEY[-6:]})")
elif USERNAME:
    logger.info(f"Auth: Username/Password loaded from {_pass_src} (user: {USERNAME})")

# If no auth configured at all, allow local-only access automatically
if not API_KEY and not USERNAME and not PASSWORD and not ALLOW_NO_AUTH:
    ALLOW_NO_AUTH = True
    logger.warning("No dashboard credentials configured — allowing local access only. Run setup wizard for remote access.")

PORT = int(os.getenv('DASHBOARD_PORT', setup_config.get('dashboard_port', 5000)))
DEBUG = os.getenv('DEBUG', 'false').lower() == 'true'
# UPDATE_INTERVAL: old setup.sh wrote 10 to .env — override that stale value.
# 3s backend collection ensures fresh data is always ready for 5s frontend polls.
_raw_interval = int(os.getenv('UPDATE_INTERVAL', 3))
UPDATE_INTERVAL = 3 if _raw_interval >= 10 else max(_raw_interval, 2)

if MULTI_NODE_MODE:
    logger.info(f"=== MULTI-NODE MODE: {len(_node_registry)} nodes from nodes.json ===")
    for n in _node_registry:
        logger.info(f"  {n['id']}: {n['label']} → {n['url']}")
else:
    logger.info(f"Single-node mode: {NODE_API_URLS}")
logger.info(f"Update Interval: {UPDATE_INTERVAL}s")
logger.info(f"Port: {PORT}")


def detect_environment():
    """Detect if running in Docker, LXC, Proxmox, or bare metal.
    Returns dict with 'type', 'details', and 'in_container'.

    Detection order:
      1. Proxmox host   — /etc/pve/.version or pve kernel
      2. LXC container  — /run/systemd/container, environ, cgroup v1/v2, marker files
      3. Docker         — /run/systemd/container, /.dockerenv, cgroup v1/v2
      4. Docker host    — docker daemon reachable from host
      5. bare_metal     — fallback
    """
    env = {'type': 'bare_metal', 'details': '', 'in_container': False}
    try:
        # ── 1. Proxmox host ───────────────────────────────────────────────────
        if os.path.exists('/etc/pve/.version'):
            env['type'] = 'proxmox_host'
            env['details'] = 'Proxmox VE host'
            return env
        try:
            with open('/proc/version', 'r') as f:
                if 'pve' in f.read().lower():
                    env['type'] = 'proxmox_host'
                    env['details'] = 'Proxmox VE kernel'
                    return env
        except Exception:
            pass

        # ── Read cgroup once (used by both LXC and Docker checks) ─────────────
        cgroup_text = ''
        try:
            with open('/proc/1/cgroup', 'r') as f:
                cgroup_text = f.read()
        except Exception:
            pass

        # ── 2. LXC container ──────────────────────────────────────────────────
        # /run/systemd/container is the most reliable indicator on systemd hosts
        try:
            with open('/run/systemd/container', 'r') as f:
                ct = f.read().strip().lower()
                if 'lxc' in ct:
                    env['type'] = 'lxc_container'
                    env['details'] = 'LXC container (systemd)'
                    env['in_container'] = True
                    return env
        except Exception:
            pass

        # container=lxc in /proc/1/environ (set by Proxmox LXC)
        try:
            with open('/proc/1/environ', 'rb') as f:
                environ_data = f.read().replace(b'\x00', b'\n').decode('utf-8', errors='ignore')
                if 'container=lxc' in environ_data:
                    env['type'] = 'lxc_container'
                    env['details'] = 'LXC container (environ)'
                    env['in_container'] = True
                    return env
        except Exception:
            pass

        # cgroup v1 string match
        if 'lxc' in cgroup_text:
            env['type'] = 'lxc_container'
            env['details'] = 'LXC container (cgroup v1)'
            env['in_container'] = True
            return env

        # cgroup v2 — check /sys/fs/cgroup for lxc marker
        try:
            with open('/sys/fs/cgroup/cgroup.controllers', 'r') as f:
                pass  # file exists → cgroup v2 active
            if os.path.exists('/dev/.lxc') or os.path.exists('/.lxc.conf') or os.path.exists('/run/.lxc'):
                env['type'] = 'lxc_container'
                env['details'] = 'LXC container (cgroup v2)'
                env['in_container'] = True
                return env
        except Exception:
            pass

        # Marker files fallback
        if os.path.exists('/.lxc.conf') or os.path.exists('/run/.lxc'):
            env['type'] = 'lxc_container'
            env['details'] = 'LXC container (marker)'
            env['in_container'] = True
            return env

        # ── 3. Docker container ───────────────────────────────────────────────
        # /run/systemd/container
        try:
            with open('/run/systemd/container', 'r') as f:
                ct = f.read().strip().lower()
                if 'docker' in ct:
                    env['type'] = 'docker_container'
                    env['details'] = 'Docker container (systemd)'
                    env['in_container'] = True
                    return env
        except Exception:
            pass

        # /.dockerenv marker (most common)
        if os.path.exists('/.dockerenv'):
            env['type'] = 'docker_container'
            env['details'] = 'Docker container'
            env['in_container'] = True
            return env

        # cgroup v1
        if 'docker' in cgroup_text or '/docker/' in cgroup_text:
            env['type'] = 'docker_container'
            env['details'] = 'Docker container (cgroup v1)'
            env['in_container'] = True
            return env

        # cgroup v2 — /proc/self/mountinfo contains docker overlay
        try:
            with open('/proc/self/mountinfo', 'r') as f:
                mi = f.read()
                if '/docker/' in mi or 'overlay' in mi:
                    # Only treat as docker if combined with other evidence
                    if not os.path.exists('/etc/hostname') or \
                       open('/etc/hostname').read().strip().isalnum():
                        env['type'] = 'docker_container'
                        env['details'] = 'Docker container (cgroup v2)'
                        env['in_container'] = True
                        return env
        except Exception:
            pass

        # ── 4. Docker host (daemon reachable) ─────────────────────────────────
        try:
            result = subprocess.run(['docker', 'ps', '-q'],
                                    capture_output=True, timeout=2)
            if result.returncode == 0:
                env['type'] = 'docker_host'
                env['details'] = 'Docker host'
        except Exception:
            pass

    except Exception:
        pass
    return env


RUNTIME_ENV = detect_environment()
logger.info(f"Runtime environment: {RUNTIME_ENV['type']} — {RUNTIME_ENV.get('details', '')}")

# ============ INITIALIZATION ============
# Serve built frontend from dist/ if it exists (production mode)
# Falls back gracefully when dist/ is not built yet (dev mode with Vite)
_toolkit_root = Path(__file__).resolve().parent.parent
_dist_dir     = _toolkit_root / 'dist'
_has_dist     = (_dist_dir / 'index.html').exists()

if _has_dist:
    app = Flask(__name__, static_folder=str(_dist_dir), static_url_path='')
    logger.info(f"Production mode: serving frontend from {_dist_dir}")
else:
    app = Flask(__name__)
    logger.info("Dev mode: frontend served by Vite dev server (run npm start)")

CORS(app)

# Metrics storage
metrics_cache = {}
metrics_lock = Lock()
metrics_history = deque(maxlen=200)  # Reduced from 1000 — less memory
last_update_time = time.time()
node_status = {'connected': False, 'error': None}
peak_clients = 0  # Persistent peak tracker — highest connected count seen

# ============ TIERED COLLECTION ============
# Fast (every cycle ~5s): performance, live_connections, resources — psutil only
# Medium (every 120s): bandwidth, services, sessions, clients — TequilAPI calls
# Slow (every 600s / 10min): earnings, node_status — blockchain/identity data
_tier_medium_cache = {}
_tier_medium_last = 0
TIER_MEDIUM_INTERVAL = 120  # seconds — reduced API calls (was 60)

_tier_slow_cache = {}
_traffic_history_imported = False  # Set True after first vnstat history import

# Fast tier snapshot — written after each fast collection, read by get_resources()
# for tunnel count, speed and latency when writing SystemMetricsDB snapshots.
_last_fast_data = {}

# VPN daily psutil baseline — used when vnstat does not track myst* interfaces.
# At midnight (or first run) we snapshot psutil bytes_recv/sent on myst*/wg*/tun*
# so "today's VPN" = current_psutil - baseline.  Resets each calendar day.
_vpn_day_baseline = {
    'date': None,   # 'YYYY-MM-DD' of the baseline snapshot
    'rx':   0,      # bytes_recv at baseline
    'tx':   0,      # bytes_sent at baseline
}
_vpn_day_baseline_lock = Lock()
_tier_slow_last = 0
TIER_SLOW_INTERVAL = 600    # 10 minutes — reduced API calls (was 300)

# ============ DATA RETENTION ============
# Default retention periods (days) per database type.
# Override in config/setup.json under key 'data_retention': {'earnings': 365, ...}
_DEFAULT_RETENTION = {
    'earnings': 365,
    'sessions': 365,
    'traffic':  730,
    'quality':  365,
    'system':   365,
    'services': 365,
    'uptime':   365,
}
_last_prune_date = ''   # 'YYYY-MM-DD' — retention prune runs once per calendar day


def _get_retention_config() -> dict:
    """Read data retention config from setup.json. Falls back to defaults."""
    try:
        cfg_path = Path('config/setup.json')
        if cfg_path.exists():
            d = json.loads(cfg_path.read_text())
            user_ret = d.get('data_retention', {})
            if isinstance(user_ret, dict):
                result = dict(_DEFAULT_RETENTION)
                for k, v in user_ret.items():
                    if k in result and isinstance(v, int) and v > 0:
                        result[k] = v
                return result
    except Exception:
        pass
    return dict(_DEFAULT_RETENTION)


def _prune_old_data():
    """Delete rows older than the configured retention window. Runs once per day."""
    global _last_prune_date
    today = local_today()
    if _last_prune_date == today:
        return
    if DataManager is None:
        return
    node_id = _local_node_id if _local_node_id else None
    retention = _get_retention_config()
    pruned = {}
    for data_type, keep_days in retention.items():
        try:
            res = DataManager.delete_range(
                data_type=data_type,
                node_id=node_id,
                keep_days=keep_days,
            )
            deleted = sum(
                v.get('deleted', 0)
                for v in res.get('results', {}).values()
                if isinstance(v, dict)
            )
            if deleted:
                pruned[data_type] = deleted
        except Exception as _pe:
            logger.debug(f"Retention prune {data_type}: {_pe}")
    _last_prune_date = today
    if pruned:
        logger.info(f"Daily retention prune: {pruned}")
    else:
        logger.debug("Daily retention prune: nothing to remove")

# Discovery API (external) — quality data.  Separate interval to keep it
# clearly distinct from TequilAPI calls and not risk cross-contamination.
TIER_DISCOVERY_INTERVAL = 600   # 10 minutes — same cadence as slow tier
_discovery_cache = {}
_discovery_last = 0
_discovery_wallet = ''  # Track which wallet the cache belongs to
_local_node_id = ''         # Cached local node identity for DB writes (set by slow tier)
_identity_cache = {'address': '', 'ts': 0}  # Cache identity to reduce /identities API calls

# Uptime tracking — persisted to disk so 30-day stats survive restarts
UPTIME_FILE    = Path('config/uptime_log.json')   # list of epoch timestamps (online pings)
IDENTITY_FILE  = Path('config/node_identity.txt')  # last known node identity — reset uptime if changed


# ============ TEQUILAPI RESPONSE CACHE ============
# Fetch each TequilAPI endpoint ONCE per medium cycle, share across functions
_tequila_cache = {}          # {endpoint: response_data}
_tequila_cache_time = 0

# ============ AUTHENTICATION ============
def require_auth(f):
    """Decorator for API authentication.
    Local requests (127.0.0.1, ::1) always bypass auth — this is a local monitoring tool.
    Auth is only enforced for remote/network access."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Always allow localhost — no reason to auth against yourself
        if is_local_request():
            return f(*args, **kwargs)

        auth = request.headers.get('Authorization')
        if not auth:
            return jsonify({'error': 'Missing Authorization header'}), 401

        # Bearer token (API Key)
        if auth.startswith('Bearer '):
            token = auth.split(' ', 1)[1]
            if API_KEY and token == API_KEY:
                return f(*args, **kwargs)
            logger.warning(f"Invalid API key attempt from {request.remote_addr}")
            return jsonify({'error': 'Invalid API key'}), 401

        # Basic Auth
        if auth.startswith('Basic '):
            try:
                credentials = base64.b64decode(auth.split(' ', 1)[1]).decode('utf-8')
                user, pwd = credentials.split(':', 1)
                if user == USERNAME and pwd == PASSWORD:
                    return f(*args, **kwargs)
            except Exception as e:
                logger.warning(f"Basic auth error: {e}")
            logger.warning(f"Invalid credentials from {request.remote_addr}")
            return jsonify({'error': 'Invalid credentials'}), 401

        return jsonify({'error': 'Invalid authorization'}), 401

    return decorated_function


def is_local_request():
    """Check if request originates from local network.

    When requests come through the Vite dev proxy, Flask sees remote_addr=127.0.0.1
    (the proxy itself). We check X-Forwarded-For for the real client IP so that
    remote browsers accessing via the Vite proxy are correctly identified as non-local
    and require authentication.
    """
    # Real client IP from Vite proxy (set by vite.config.js configure hook)
    forwarded_for = request.headers.get('X-Forwarded-For', '').split(',')[0].strip()
    # Direct connection address
    remote_addr = request.remote_addr or ''

    # If proxy forwarded a real remote IP, use that for the check
    check_addr = forwarded_for if forwarded_for else remote_addr

    def _is_local(addr):
        return (addr in ('127.0.0.1', '::1', 'localhost') or
                addr.startswith('192.168.') or
                addr.startswith('10.') or
                addr.startswith('172.16.') or
                addr.startswith('172.17.') or
                addr.startswith('172.18.') or
                addr.startswith('172.19.') or
                addr.startswith('172.2') or
                addr.startswith('172.3'))

    return _is_local(check_addr)


# ============ METRIC COLLECTION ============

class SessionStore:
    """Full session history store with pagination support.

    Problem: TequilAPI /sessions returns 50 items per page by default. A node with
    2393 sessions across 48 pages would only ever see the most recent 50 without
    pagination — 97.9% of history invisible, earnings calculations severely wrong.

    Strategy:
    - Startup: fetch ALL pages once in a background thread (~15s for 48 pages).
    - Medium cycle (every 120s): fetch page 1 only, merge any new sessions.
    - Sessions stored by ID in a dict — O(1) deduplication, no duplicates.
    - get_all() returns the full in-memory store sorted by started desc.
    """

    _sessions = {}          # {session_id: raw_session_dict}
    _lock = Lock()
    _initialized = {}       # {node_url: bool} — True once full fetch completes
    _total_items = {}       # {node_url: int} — API-reported total
    _loading = {}           # {node_url: bool} — startup fetch in progress

    @classmethod
    def fetch_all_pages(cls, node_url, headers):
        """Fetch every page from TequilAPI /sessions. Called ONCE at startup per node.
        Runs in a dedicated daemon thread — does not block the main collector."""
        cls._loading[node_url] = True
        page = 1
        fetched = 0
        total_pages = 1
        try:
            while page <= total_pages:
                try:
                    resp = requests.get(
                        f'{node_url}/sessions',
                        params={'page': page, 'page_size': 50},
                        headers=headers, timeout=15
                    )
                    if resp.status_code != 200:
                        logger.warning(f"SessionStore: /sessions page {page} returned {resp.status_code}")
                        break
                    data = resp.json()
                    items = data.get('items', [])
                    if not items:
                        break
                    with cls._lock:
                        for s in items:
                            sid = s.get('id', '')
                            if sid:
                                cls._sessions[sid] = s
                    # Persist to SessionDB before Mysterium zeros tokens after settlement
                    try:
                        SessionDB.upsert_sessions(items)
                    except Exception as _sdb_e:
                        logger.debug(f"SessionDB upsert (fetch_all): {_sdb_e}")
                    fetched += len(items)
                    total_pages = data.get('total_pages', 1)
                    cls._total_items[node_url] = data.get('total_items', fetched)
                    page += 1
                    if page <= total_pages:
                        time.sleep(0.3)   # gentle rate — no burst against TequilAPI
                except Exception as e:
                    logger.warning(f"SessionStore: page {page} fetch failed for {node_url}: {e}")
                    break
        finally:
            cls._initialized[node_url] = True
            cls._loading[node_url] = False
            # After full history load: backfill consumer_country for all sessions that have it
            try:
                all_with_country = [s for s in cls._sessions.values() if s.get('consumer_country') and s.get('id')]
                if all_with_country:
                    updated = SessionDB.backfill_countries(all_with_country)
                    logger.info(f"SessionStore: country backfill after full load — {updated} rows updated from {len(all_with_country)} sessions with country")
                else:
                    logger.info(f"SessionStore: no sessions with consumer_country in full history")
            except Exception as _bf_e:
                logger.debug(f"SessionStore: country backfill failed: {_bf_e}")
            # After full history load: backfill provider_id for all sessions stored with empty
            # provider_id (happens when IDENTITY_FILE doesn't exist yet at startup).
            # Without this, DataManager stats (which filter by provider_id) show 0 sessions.
            try:
                _pid = ''
                if IDENTITY_FILE.exists():
                    _pid = IDENTITY_FILE.read_text().strip()
                if not _pid:
                    # Identity not in file yet — try fetching directly from TequilAPI
                    try:
                        _headers = MetricsCollector.get_tequilapi_headers()
                        _id_resp = requests.get(f'{node_url}/identities', headers=_headers, timeout=5)
                        if _id_resp.status_code == 200:
                            _ids = _id_resp.json().get('identities', [])
                            if _ids:
                                _pid = _ids[0].get('id', '')
                    except Exception:
                        pass
                if _pid:
                    updated_pid = SessionDB.backfill_provider_id(_pid)
                    if updated_pid > 0:
                        logger.info(f"SessionStore: provider_id backfill — set provider_id on {updated_pid} sessions that had empty provider_id")
            except Exception as _pid_e:
                logger.debug(f"SessionStore: provider_id backfill failed: {_pid_e}")
            logger.info(
                f"SessionStore: loaded {fetched} sessions from {node_url} "
                f"({page - 1}/{total_pages} pages, "
                f"total_items={cls._total_items.get(node_url, '?')})"
            )
            # Invalidate sessions/analytics cache so next UI request recomputes
            # country breakdown and service breakdown with ALL loaded sessions.
            # Without this, the cache built before the fetch completed shows wrong data
            # (e.g. 1 country DE instead of DE/RO/FI/FR) until the next 120s cycle.
            try:
                with metrics_lock:
                    metrics_cache.pop('sessions', None)
                    metrics_cache.pop('analytics', None)
                logger.info("SessionStore: sessions cache invalidated after full fetch — analytics will recompute on next request")
            except Exception as _ci_e:
                logger.debug(f"SessionStore: cache invalidation failed: {_ci_e}")

    @classmethod
    def refresh_page1(cls, node_url, headers):
        """Fetch the latest page (page 1 = most recent sessions) and merge into store.
        Called every 120s medium cycle. Adds new sessions without re-fetching history."""
        try:
            resp = requests.get(
                f'{node_url}/sessions',
                params={'page': 1, 'page_size': 50},
                headers=headers, timeout=8
            )
            if resp.status_code == 200:
                data = resp.json()
                items = data.get('items', [])
                with cls._lock:
                    for s in items:
                        sid = s.get('id', '')
                        if sid:
                            cls._sessions[sid] = s
                # Persist page 1 (most recent sessions) to SessionDB
                try:
                    SessionDB.upsert_sessions(items)
                    # Backfill consumer_country for any archived sessions that had it empty
                    live_with_country = [s for s in items if s.get('consumer_country')]
                    if live_with_country:
                        SessionDB.backfill_countries(live_with_country)
                except Exception as _sdb_e:
                    logger.debug(f"SessionDB upsert (page1): {_sdb_e}")
                cls._total_items[node_url] = data.get('total_items', 0)
        except Exception as e:
            logger.debug(f"SessionStore: page1 refresh failed for {node_url}: {e}")

    @classmethod
    def get_all(cls):
        """Return all sessions as a list (thread-safe copy)."""
        with cls._lock:
            return list(cls._sessions.values())

    @classmethod
    def is_ready(cls, node_url):
        """True once the startup full-fetch has completed for this node."""
        return cls._initialized.get(node_url, False)

    @classmethod
    def stats(cls):
        """Return a summary dict for diagnostics."""
        with cls._lock:
            return {
                'total_in_store': len(cls._sessions),
                'initialized': dict(cls._initialized),
                'loading': dict(cls._loading),
                'total_items_api': dict(cls._total_items),
            }


class TequilaCache:
    """Fetch each TequilAPI endpoint ONCE per cycle, share data across all functions.
    Sessions are managed by SessionStore (full pagination). This class handles /services."""

    _data = {}       # {endpoint: response_json}
    _headers = None
    _lock = Lock()

    @classmethod
    def refresh(cls, headers):
        """Fetch /services for all nodes. Sessions handled separately by SessionStore.
        SAFETY: Only replaces cache if at least one call succeeded."""
        cls._headers = headers
        new_data = {}
        for node_url in NODE_API_URLS:
            try:
                resp = requests.get(f'{node_url}/services', headers=headers, timeout=8)
                if resp.status_code == 200:
                    key = f'{node_url}/services'
                    new_data[key] = resp.json()
            except Exception as e:
                logger.debug(f"TequilaCache: /services failed for {node_url}: {e}")

            # Merge latest sessions (page 1 only — history already in SessionStore)
            SessionStore.refresh_page1(node_url, headers)

        if new_data:
            cls._data = new_data
        else:
            logger.warning("TequilaCache: /services call failed — keeping previous cache")

    @classmethod
    def get(cls, node_url, endpoint):
        """Get cached response for a node+endpoint combo."""
        return cls._data.get(f'{node_url}{endpoint}')

    @classmethod
    def get_all_sessions(cls):
        """Return all sessions from SessionStore (full history, all pages)."""
        return SessionStore.get_all()

    @classmethod
    def get_all_services(cls):
        """Get all service objects across all nodes (cached)."""
        services = []
        for node_url in NODE_API_URLS:
            data = cls.get(node_url, '/services')
            if data and isinstance(data, list):
                services.extend(data)
        return services


# ─────────────────────────────────────────────────────────────────────────────
# Traffic History Database
# Stores daily VPN + NIC traffic snapshots for 3-month, yearly, all-time views.
# vnstat keeps day[] for 30 days only — we persist daily data in SQLite forever.
# vnstat months[] and years[] are also imported at startup for complete history.
# ─────────────────────────────────────────────────────────────────────────────
class TrafficDB:
    """Persistent traffic history using SQLite.

    Schema:
      daily_traffic(date TEXT PRIMARY KEY,
                    vpn_rx_mb REAL, vpn_tx_mb REAL,
                    nic_rx_mb REAL, nic_tx_mb REAL,
                    source TEXT)   -- 'vnstat_daily' | 'vnstat_month_import' | 'snapshot'

    One row per calendar day. Updated once per slow cycle from live vnstat data.
    At startup we import all historical vnstat month[] entries so history is
    complete from the day vnstat was first installed — not just from toolkit install.
    """

    _db_path = Path(__file__).parent.parent / 'config' / 'traffic_history.db'
    _initialized = False
    _lock = Lock()

    @classmethod
    def _conn(cls):
        conn = sqlite3.connect(str(cls._db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    @classmethod
    def init(cls):
        """Create table if needed. Idempotent."""
        if cls._initialized:
            return
        cls._db_path.parent.mkdir(parents=True, exist_ok=True)
        with cls._lock:
            try:
                conn = cls._conn()
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS daily_traffic (
                        date       TEXT PRIMARY KEY,
                        vpn_rx_mb  REAL DEFAULT 0,
                        vpn_tx_mb  REAL DEFAULT 0,
                        nic_rx_mb  REAL DEFAULT 0,
                        nic_tx_mb  REAL DEFAULT 0,
                        source     TEXT DEFAULT 'snapshot'
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_date ON daily_traffic(date)")
                conn.commit()
                conn.close()
                cls._initialized = True
            except Exception as e:
                logger.warning(f"TrafficDB init failed: {e}")

    @classmethod
    def upsert_day(cls, date_str, vpn_rx_mb, vpn_tx_mb, nic_rx_mb, nic_tx_mb, source='snapshot'):
        """Insert or update one day's traffic. date_str = YYYY-MM-DD."""
        cls.init()
        with cls._lock:
            try:
                conn = cls._conn()
                conn.execute("""
                    INSERT INTO daily_traffic(date, vpn_rx_mb, vpn_tx_mb, nic_rx_mb, nic_tx_mb, source)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(date) DO UPDATE SET
                        vpn_rx_mb = excluded.vpn_rx_mb,
                        vpn_tx_mb = excluded.vpn_tx_mb,
                        nic_rx_mb = excluded.nic_rx_mb,
                        nic_tx_mb = excluded.nic_tx_mb,
                        source    = excluded.source
                """, (date_str, round(vpn_rx_mb, 3), round(vpn_tx_mb, 3),
                      round(nic_rx_mb, 3), round(nic_tx_mb, 3), source))
                conn.commit()
                conn.close()
            except Exception as e:
                logger.warning(f"TrafficDB upsert_day failed: {e}")

    @classmethod
    def import_vnstat_history(cls, vnstat_data):
        """Import vnstat day[] and month[] data at startup — VPN-only filter.

        Runs once per toolkit start (_traffic_history_imported flag).

        FILTER RULE — only import days/months where VPN traffic actually existed:
          - A day is imported ONLY if myst*/wg*/tun* interfaces had traffic that day.
          - NIC (eno1) data is included alongside VPN data for correct overhead calc.
          - Days with no VPN activity are skipped entirely — no relevance to
            Mysterium node monitoring, avoids polluting overhead with non-Mysterium
            traffic (browsing, SSH, updates, etc.).
          - Protects fresh installs: vnstat history before Mysterium = not imported.

        Priority rules:
          - vnstat_daily rows from the running backend are never overwritten.
          - vnstat_month_import rows are replaced by daily rows for same month.
          - Monthly fallback only for months with VPN data but no daily rows.
        """
        cls.init()
        if not vnstat_data:
            return 0
        interfaces = vnstat_data.get("interfaces", [])
        json_ver = vnstat_data.get("jsonversion", "2")
        unit_mult = 1024 if json_ver == "1" else 1
        MB = 1024 * 1024
        vpn_prefixes = ("myst", "wg", "tun")

        day_vpn = {}   # YYYY-MM-DD -> {rx, tx}  VPN interfaces only
        day_nic = {}   # YYYY-MM-DD -> {rx, tx}  physical NIC only
        month_vpn = {} # YYYY-MM -> {rx, tx}
        month_nic = {}

        for iface in interfaces:
            name = iface.get("name", "")
            is_vpn = any(name.startswith(p) for p in vpn_prefixes)
            traffic = iface.get("traffic", {})

            for entry in traffic.get("day", []):
                d = entry.get("date", {})
                yr, mo, dy = d.get("year", 0), d.get("month", 0), d.get("day", 0)
                if not yr or not mo or not dy:
                    continue
                key = f"{yr:04d}-{mo:02d}-{dy:02d}"
                rx_mb = entry.get("rx", 0) * unit_mult / MB
                tx_mb = entry.get("tx", 0) * unit_mult / MB
                if is_vpn:
                    if key not in day_vpn:
                        day_vpn[key] = {"rx": 0.0, "tx": 0.0}
                    day_vpn[key]["rx"] += rx_mb
                    day_vpn[key]["tx"] += tx_mb
                else:
                    if key not in day_nic:
                        day_nic[key] = {"rx": 0.0, "tx": 0.0}
                    day_nic[key]["rx"] += rx_mb
                    day_nic[key]["tx"] += tx_mb

            for m in traffic.get("month", []):
                d = m.get("date", {})
                yr, mo = d.get("year", 0), d.get("month", 0)
                if not yr or not mo:
                    continue
                key = f"{yr:04d}-{mo:02d}"
                rx_mb = m.get("rx", 0) * unit_mult / MB
                tx_mb = m.get("tx", 0) * unit_mult / MB
                if is_vpn:
                    if key not in month_vpn:
                        month_vpn[key] = {"rx": 0.0, "tx": 0.0}
                    month_vpn[key]["rx"] += rx_mb
                    month_vpn[key]["tx"] += tx_mb
                else:
                    if key not in month_nic:
                        month_nic[key] = {"rx": 0.0, "tx": 0.0}
                    month_nic[key]["rx"] += rx_mb
                    month_nic[key]["tx"] += tx_mb

        imported_days = 0
        imported_months = 0

        with cls._lock:
            try:
                conn = cls._conn()

                # Step 1: Daily rows — only where VPN traffic existed
                for date_str in sorted(day_vpn.keys()):
                    v = day_vpn[date_str]
                    if v["rx"] + v["tx"] == 0:
                        continue  # No VPN traffic this day — skip
                    n = day_nic.get(date_str, {"rx": 0.0, "tx": 0.0})
                    # Remove month_import placeholder — daily is better
                    conn.execute(
                        "DELETE FROM daily_traffic WHERE date = ? AND source = ?",
                        (date_str[:7] + "-01", "vnstat_month_import")
                    )
                    # Never overwrite vnstat_daily rows from the running backend
                    conn.execute("""
                        INSERT OR IGNORE INTO daily_traffic
                            (date, vpn_rx_mb, vpn_tx_mb, nic_rx_mb, nic_tx_mb, source)
                        VALUES (?, ?, ?, ?, ?, 'vnstat_backfill')
                    """, (date_str,
                          round(v["rx"], 3), round(v["tx"], 3),
                          round(n["rx"], 3), round(n["tx"], 3)))
                    imported_days += conn.execute("SELECT changes()").fetchone()[0]

                # Step 2: Monthly fallback — only months with VPN traffic, no daily rows
                for key in sorted(month_vpn.keys()):
                    v = month_vpn[key]
                    if v["rx"] + v["tx"] == 0:
                        continue  # No VPN traffic this month — skip
                    existing = conn.execute(
                        "SELECT COUNT(*) FROM daily_traffic WHERE strftime('%Y-%m', date) = ? AND source != ?",
                        (key, "vnstat_month_import")
                    ).fetchone()[0]
                    if existing > 0:
                        continue
                    n = month_nic.get(key, {"rx": 0.0, "tx": 0.0})
                    conn.execute("""
                        INSERT OR REPLACE INTO daily_traffic
                            (date, vpn_rx_mb, vpn_tx_mb, nic_rx_mb, nic_tx_mb, source)
                        VALUES (?, ?, ?, ?, ?, 'vnstat_month_import')
                    """, (key + "-01",
                          round(v["rx"], 3), round(v["tx"], 3),
                          round(n["rx"], 3), round(n["tx"], 3)))
                    imported_months += conn.execute("SELECT changes()").fetchone()[0]

                conn.commit()
                conn.close()
                if imported_days:
                    logger.info(f"TrafficDB: imported {imported_days} vnstat daily rows (VPN-filtered)")
                if imported_months:
                    logger.info(f"TrafficDB: imported {imported_months} vnstat month fallback rows (VPN-filtered)")
            except Exception as e:
                logger.warning(f"TrafficDB import_vnstat_history failed: {e}")

        return imported_days + imported_months

    @classmethod
    def get_range(cls, days_back=None, months_back=None):
        """Return list of daily records sorted ascending.
        days_back=30    → last 30 calendar days
        months_back=3   → first day of the month 3 months ago (real boundaries)
        None            → all records
        """
        cls.init()
        # De-duplication filter: exclude vnstat_month_import records for any month
        # that already has vnstat_daily records — avoids double-counting.
        no_dupe = """
            NOT (
                source = 'vnstat_month_import'
                AND strftime('%Y-%m', date) IN (
                    SELECT DISTINCT strftime('%Y-%m', date)
                    FROM daily_traffic
                    WHERE source = 'vnstat_daily'
                )
            )
        """
        try:
            conn = cls._conn()
            if days_back is not None:
                cutoff = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
                rows = conn.execute(
                    f"SELECT * FROM daily_traffic WHERE date >= ? AND {no_dupe} ORDER BY date ASC",
                    (cutoff,)
                ).fetchall()
            elif months_back is not None:
                # Use real month boundary: first day of the month N months ago
                from datetime import date as _date
                today = _date.today()
                month = today.month - months_back
                year  = today.year + month // 12
                month = month % 12 or 12
                if today.month - months_back <= 0:
                    year  = today.year - ((-( today.month - months_back) // 12) + 1)
                    month = (today.month - months_back) % 12 or 12
                cutoff = f"{year:04d}-{month:02d}-01"
                rows = conn.execute(
                    f"SELECT * FROM daily_traffic WHERE date >= ? AND {no_dupe} ORDER BY date ASC",
                    (cutoff,)
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT * FROM daily_traffic WHERE {no_dupe} ORDER BY date ASC"
                ).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.warning(f"TrafficDB get_range failed: {e}")
            return []

    @classmethod
    def get_totals(cls):
        """Return all-time totals, consistent with get_range() live-month supplement.

        The current month's partial daily rows are replaced by the live vnstat
        monthly total — same logic as the supplement in get_traffic_history() —
        so All Time never differs from the history-tab totals.
        """
        cls.init()
        try:
            from datetime import date as _date
            today = _date.today()
            this_month = today.strftime('%Y-%m')

            conn = cls._conn()

            # Sum all rows except current month (current month replaced by live data below)
            row = conn.execute("""
                SELECT
                    SUM(vpn_rx_mb) as vpn_rx,
                    SUM(vpn_tx_mb) as vpn_tx,
                    SUM(nic_rx_mb) as nic_rx,
                    SUM(nic_tx_mb) as nic_tx,
                    MIN(date) as oldest,
                    COUNT(*) as days
                FROM daily_traffic
                WHERE strftime('%Y-%m', date) != ?
                AND NOT (
                    source = 'vnstat_month_import'
                    AND strftime('%Y-%m', date) IN (
                        SELECT DISTINCT strftime('%Y-%m', date)
                        FROM daily_traffic
                        WHERE source = 'vnstat_daily'
                    )
                )
            """, (this_month,)).fetchone()
            conn.close()

            vpn_rx = row['vpn_rx'] or 0
            vpn_tx = row['vpn_tx'] or 0
            nic_rx = row['nic_rx'] or 0
            nic_tx = row['nic_tx'] or 0
            oldest = row['oldest']
            days   = row['days'] or 0

            # Add live current-month data from vnstat (same supplement as get_range)
            try:
                vnstat = MetricsCollector._get_vnstat_traffic()
                if vnstat:
                    MB = 1024 * 1024
                    vpn_rx += vnstat.get('vpn_month_rx', 0) / MB
                    vpn_tx += vnstat.get('vpn_month_tx', 0) / MB
                    nic_rx += vnstat.get('month_rx', 0) / MB
                    nic_tx += vnstat.get('month_tx', 0) / MB
                    days   += 1  # current month counts as 1 entry
            except Exception:
                pass

            return {
                'vpn_rx_mb':  round(vpn_rx, 2),
                'vpn_tx_mb':  round(vpn_tx, 2),
                'nic_rx_mb':  round(nic_rx, 2),
                'nic_tx_mb':  round(nic_tx, 2),
                'oldest':     oldest,
                'newest':     today.isoformat(),
                'days':       days,
            }
        except Exception as e:
            logger.warning(f"TrafficDB get_totals failed: {e}")
        return {'vpn_rx_mb': 0, 'vpn_tx_mb': 0, 'nic_rx_mb': 0, 'nic_tx_mb': 0,
                'oldest': None, 'newest': None, 'days': 0}


class SessionDB:
    """Persistent session history database using SQLite.

    Stores every session fetched from TequilAPI before Mysterium zeros the
    tokens field after settlement. This gives permanent per-session earnings
    history that survives node restarts, settlements, and toolkit updates.

    Schema:
      sessions(
        id              TEXT PRIMARY KEY,   -- TequilAPI session UUID
        consumer_id     TEXT,
        service_type    TEXT,
        status          TEXT,
        started_at      TEXT,               -- ISO datetime
        duration_secs   INTEGER,
        bytes_sent      INTEGER,
        bytes_received  INTEGER,
        tokens          INTEGER,            -- raw wei — saved BEFORE zeroing
        consumer_country TEXT,
        first_seen      TEXT,               -- when toolkit first recorded it
        last_seen       TEXT,               -- last update from API
        tokens_frozen   INTEGER DEFAULT 0   -- 1 = tokens were > 0 when first seen
      )
    """

    _db_path = Path(__file__).parent.parent / 'config' / 'sessions_history.db'
    _initialized = False
    _lock = Lock()

    @classmethod
    def _conn(cls):
        conn = sqlite3.connect(str(cls._db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    @classmethod
    def init(cls):
        if cls._initialized:
            return
        cls._db_path.parent.mkdir(parents=True, exist_ok=True)
        with cls._lock:
            try:
                conn = cls._conn()
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS sessions (
                        id               TEXT PRIMARY KEY,
                        consumer_id      TEXT DEFAULT '',
                        service_type     TEXT DEFAULT '',
                        status           TEXT DEFAULT '',
                        started_at       TEXT DEFAULT '',
                        duration_secs    INTEGER DEFAULT 0,
                        bytes_sent       INTEGER DEFAULT 0,
                        bytes_received   INTEGER DEFAULT 0,
                        tokens           INTEGER DEFAULT 0,
                        consumer_country TEXT DEFAULT '',
                        first_seen       TEXT DEFAULT '',
                        last_seen        TEXT DEFAULT '',
                        tokens_frozen    INTEGER DEFAULT 0,
                        provider_id      TEXT DEFAULT ''
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_started ON sessions(started_at)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_service ON sessions(service_type)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_provider ON sessions(provider_id)")
                # Migrate existing databases — add provider_id column if missing
                try:
                    conn.execute("ALTER TABLE sessions ADD COLUMN provider_id TEXT DEFAULT ''")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_provider ON sessions(provider_id)")
                    logger.info("SessionDB: added provider_id column to existing database")
                except Exception:
                    pass  # Column already exists
                # Note: we do NOT backfill provider_id for existing rows.
                # Existing rows without provider_id may belong to a different node
                # that was migrated. Only new sessions get provider_id set.
                # Analytics uses date filter as fallback for rows without provider_id.
                conn.commit()
                conn.close()
                cls._initialized = True
            except Exception as e:
                logger.warning(f"SessionDB init failed: {e}")

    @classmethod
    def upsert_sessions(cls, sessions_list):
        """Upsert a batch of sessions from TequilAPI.

        Critical: on INSERT we save the tokens value as-is.
        On UPDATE we only overwrite tokens if the new value > 0 OR if tokens
        were never frozen (tokens_frozen=0). This prevents a zeroed API
        response from wiping a previously recorded real token value.
        """
        cls.init()
        if not sessions_list:
            return 0
        now = datetime.now(timezone.utc).isoformat()
        # Read provider identity from file — set once, never changes for this install
        _provider_id = ''
        try:
            if IDENTITY_FILE.exists():
                _provider_id = IDENTITY_FILE.read_text().strip()
        except Exception:
            pass
        saved = 0
        with cls._lock:
            try:
                conn = cls._conn()
                for s in sessions_list:
                    sid = s.get('id', '')
                    if not sid:
                        continue
                    # Clamp tokens to SQLite INTEGER max (2^63-1) — raw wei can exceed this
                    _raw_tokens = int(s.get('tokens', 0) or 0)
                    tokens = min(_raw_tokens, 9223372036854775807)
                    conn.execute("""
                        INSERT INTO sessions
                            (id, consumer_id, service_type, status, started_at,
                             duration_secs, bytes_sent, bytes_received, tokens,
                             consumer_country, first_seen, last_seen, tokens_frozen,
                             provider_id)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(id) DO UPDATE SET
                            status           = excluded.status,
                            duration_secs    = excluded.duration_secs,
                            bytes_sent       = MAX(sessions.bytes_sent,    excluded.bytes_sent),
                            bytes_received   = MAX(sessions.bytes_received, excluded.bytes_received),
                            -- Preserve tokens: only update if incoming > 0 or never frozen
                            tokens           = CASE
                                WHEN excluded.tokens > 0 THEN excluded.tokens
                                WHEN sessions.tokens_frozen = 1 THEN sessions.tokens
                                ELSE excluded.tokens
                            END,
                            tokens_frozen    = CASE
                                WHEN excluded.tokens > 0 THEN 1
                                ELSE sessions.tokens_frozen
                            END,
                            last_seen        = excluded.last_seen,
                            -- Only update country if we don't have it yet
                            consumer_country = CASE
                                WHEN sessions.consumer_country = '' THEN excluded.consumer_country
                                ELSE sessions.consumer_country
                            END,
                            provider_id      = CASE
                                WHEN sessions.provider_id = '' THEN excluded.provider_id
                                ELSE sessions.provider_id
                            END
                    """, (
                        sid,
                        s.get('consumer_id', ''),
                        s.get('service_type', ''),
                        s.get('status', ''),
                        s.get('created_at', s.get('started_at', '')),
                        int(s.get('duration', 0) or 0),
                        int(s.get('bytes_sent', 0) or 0),
                        int(s.get('bytes_received', 0) or 0),
                        tokens,
                        s.get('consumer_country', ''),
                        now,  # first_seen (ignored on conflict)
                        now,  # last_seen
                        1 if tokens > 0 else 0,
                        _provider_id,
                    ))
                    saved += 1
                conn.commit()
                conn.close()
            except Exception as e:
                logger.warning(f"SessionDB upsert failed: {e}")
        return saved

    @classmethod
    def get_stats(cls):
        """Return summary stats for display."""
        cls.init()
        try:
            conn = cls._conn()
            row = conn.execute("""
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN tokens_frozen=1 THEN 1 ELSE 0 END) as with_earnings,
                       MIN(started_at) as oldest,
                       MAX(started_at) as newest
                FROM sessions WHERE service_type != 'monitoring'
            """).fetchone()
            # Fetch tokens and bytes separately to avoid integer overflow on SUM
            row2 = conn.execute("""
                SELECT SUM(CAST(tokens AS REAL)) as total_tokens,
                       SUM(CAST(bytes_sent AS REAL) + CAST(bytes_received AS REAL)) as total_bytes
                FROM sessions WHERE service_type != 'monitoring'
            """).fetchone()
            conn.close()
            if row:
                total_tokens = float(row2['total_tokens'] or 0) if row2 else 0.0
                total_bytes  = float(row2['total_bytes']  or 0) if row2 else 0.0
                return {
                    'total':         row['total'] or 0,
                    'with_earnings': row['with_earnings'] or 0,
                    'total_tokens':  int(total_tokens),
                    'total_myst':    round(total_tokens / 1e18, 6),
                    'total_gb':      round(total_bytes / (1024**3), 3),
                    'oldest':        (row['oldest'] or '')[:10],
                    'newest':        (row['newest'] or '')[:10],
                }
        except Exception as e:
            logger.warning(f"SessionDB get_stats failed: {e}")
        return {'total': 0, 'with_earnings': 0, 'total_tokens': 0,
                'total_myst': 0, 'total_gb': 0, 'oldest': None, 'newest': None}

    @classmethod
    def get_range(cls, limit=500, offset=0, service_type=None):
        """Return sessions sorted newest first."""
        cls.init()
        try:
            conn = cls._conn()
            if service_type:
                rows = conn.execute(
                    "SELECT * FROM sessions WHERE service_type=? AND service_type!='monitoring' "
                    "ORDER BY started_at DESC LIMIT ? OFFSET ?",
                    (service_type, limit, offset)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM sessions WHERE service_type!='monitoring' "
                    "ORDER BY started_at DESC LIMIT ? OFFSET ?",
                    (limit, offset)
                ).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.warning(f"SessionDB get_range failed: {e}")
            return []

    @classmethod
    def backfill_countries(cls, live_sessions):
        """Backfill consumer_country for archived sessions that have an empty country.

        Called after get_sessions() loads live TequilAPI data.
        Matches by session ID and updates the DB row when:
        - The DB row has consumer_country = ''
        - The live TequilAPI session has a non-empty consumer_country

        This repairs old archive entries that were saved before consumer_country
        was available (e.g. sessions saved while API was loading).
        """
        cls.init()
        if not live_sessions:
            return 0
        # Build lookup: id → country from live sessions
        country_map = {
            s['id']: s['consumer_country']
            for s in live_sessions
            if s.get('id') and s.get('consumer_country')
        }
        if not country_map:
            return 0
        updated = 0
        try:
            with cls._lock:
                conn = cls._conn()
                for sid, country in country_map.items():
                    cur = conn.execute(
                        "UPDATE sessions SET consumer_country=? WHERE id=? AND consumer_country=''",
                        (country, sid)
                    )
                    updated += cur.rowcount
                conn.commit()
                conn.close()
            if updated:
                logger.info(f"SessionDB.backfill_countries: updated {updated} rows")
        except Exception as e:
            logger.warning(f"SessionDB.backfill_countries failed: {e}")
        return updated

    @classmethod
    def backfill_provider_id(cls, provider_id: str) -> int:
        """Set provider_id on all sessions that have empty provider_id.

        Called after the full startup fetch completes. During backfill, sessions
        are inserted before the identity is known, so provider_id is stored as ''.
        This one-time fix ensures DataManager stats (which filter by provider_id)
        count all backfilled sessions correctly.
        """
        if not provider_id:
            return 0
        cls.init()
        updated = 0
        try:
            with cls._lock:
                conn = cls._conn()
                cur = conn.execute(
                    "UPDATE sessions SET provider_id=? WHERE provider_id='' OR provider_id IS NULL",
                    (provider_id,)
                )
                updated = cur.rowcount
                conn.commit()
                conn.close()
        except Exception as e:
            logger.warning(f"SessionDB.backfill_provider_id failed: {e}")
        return updated


class EarningsDB:
    """Permanent SQLite storage for earnings snapshots.

    Replaces the 31-day JSON cap with unlimited storage.
    One row per hourly snapshot: time, unsettled, lifetime.
    Grows ~8 KB/month. After 3 years: ~300 KB.

    Schema:
      earnings_snapshots(
        time       TEXT PRIMARY KEY,  -- ISO datetime UTC
        unsettled  REAL,              -- current unsettled MYST
        lifetime   REAL,              -- cumulative lifetime gross MYST
        source     TEXT DEFAULT 'identity'
      )
    """

    _db_path = Path(__file__).parent.parent / 'config' / 'earnings_history.db'
    _initialized = False
    _lock = Lock()

    @classmethod
    def _conn(cls):
        conn = sqlite3.connect(str(cls._db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    @classmethod
    def init(cls):
        if cls._initialized:
            return
        cls._db_path.parent.mkdir(parents=True, exist_ok=True)
        with cls._lock:
            try:
                conn = cls._conn()
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS earnings_snapshots (
                        time       TEXT PRIMARY KEY,
                        unsettled  REAL DEFAULT 0,
                        lifetime   REAL DEFAULT 0,
                        source     TEXT DEFAULT 'identity'
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_time ON earnings_snapshots(time)")
                conn.commit()
                conn.close()
                cls._initialized = True
            except Exception as e:
                logger.warning(f"EarningsDB init failed: {e}")

    @classmethod
    def migrate_from_json(cls, json_path):
        """One-time import of existing earnings_history.json into SQLite.
        Preserves all snapshots without the 31-day cutoff.
        """
        cls.init()
        if not Path(json_path).exists():
            return 0
        try:
            data = json.loads(Path(json_path).read_text())
            snaps = data.get('snapshots', [])
            imported = 0
            with cls._lock:
                conn = cls._conn()
                for s in snaps:
                    t = s.get('time', '')
                    if not t:
                        continue
                    conn.execute("""
                        INSERT OR IGNORE INTO earnings_snapshots(time, unsettled, lifetime, source)
                        VALUES (?, ?, ?, ?)
                    """, (t, float(s.get('unsettled', 0) or 0),
                          float(s.get('lifetime', 0) or 0),
                          s.get('source', 'identity')))
                    imported += conn.execute("SELECT changes()").fetchone()[0]
                conn.commit()
                conn.close()
            if imported:
                logger.info(f"EarningsDB: migrated {imported} snapshots from JSON")
            return imported
        except Exception as e:
            logger.warning(f"EarningsDB migrate_from_json failed: {e}")
            return 0

    @classmethod
    def record(cls, time_iso, unsettled, lifetime, source='identity'):
        """Insert a snapshot. Silently ignores duplicates (same time)."""
        cls.init()
        with cls._lock:
            try:
                conn = cls._conn()
                conn.execute("""
                    INSERT OR IGNORE INTO earnings_snapshots(time, unsettled, lifetime, source)
                    VALUES (?, ?, ?, ?)
                """, (time_iso, round(unsettled, 6), round(lifetime, 6), source))
                conn.commit()
                conn.close()
            except Exception as e:
                logger.warning(f"EarningsDB record failed: {e}")

    @classmethod
    def find_nearest(cls, target_dt, max_diff_seconds=7200):
        """Return snapshot closest to target_dt within max_diff_seconds, or None."""
        cls.init()
        try:
            # Search within ±max_diff_seconds window
            t_lo = (target_dt - timedelta(seconds=max_diff_seconds)).isoformat()
            t_hi = (target_dt + timedelta(seconds=max_diff_seconds)).isoformat()
            target_iso = target_dt.isoformat()
            conn = cls._conn()
            row = conn.execute("""
                SELECT *, ABS(julianday(time) - julianday(?)) as diff
                FROM earnings_snapshots
                WHERE time >= ? AND time <= ? AND source = 'identity'
                ORDER BY diff ASC
                LIMIT 1
            """, (target_iso, t_lo, t_hi)).fetchone()
            conn.close()
            if row:
                return dict(row)
        except Exception as e:
            logger.warning(f"EarningsDB find_nearest failed: {e}")
        return None

    @classmethod
    def get_oldest(cls):
        """Return oldest identity snapshot or None."""
        cls.init()
        try:
            conn = cls._conn()
            row = conn.execute(
                "SELECT * FROM earnings_snapshots WHERE source='identity' ORDER BY time ASC LIMIT 1"
            ).fetchone()
            conn.close()
            return dict(row) if row else None
        except Exception:
            return None

    @classmethod
    def get_all_for_chart(cls, days_back=None):
        """Return all snapshots for chart aggregation, newest first."""
        cls.init()
        try:
            conn = cls._conn()
            if days_back:
                cutoff = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat()
                rows = conn.execute(
                    "SELECT * FROM earnings_snapshots WHERE time >= ? AND source='identity' ORDER BY time ASC",
                    (cutoff,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM earnings_snapshots WHERE source='identity' ORDER BY time ASC"
                ).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.warning(f"EarningsDB get_all_for_chart failed: {e}")
            return []

    @classmethod
    def get_last_time(cls):
        """Return ISO time of most recent snapshot, or None."""
        cls.init()
        try:
            conn = cls._conn()
            row = conn.execute(
                "SELECT time FROM earnings_snapshots ORDER BY time DESC LIMIT 1"
            ).fetchone()
            conn.close()
            return row['time'] if row else None
        except Exception:
            return None


_earnings_db_migrated = False  # one-time JSON migration flag

# Polygonscan wallet balance cache — refreshed at most once per hour
_polygonscan_cache = {
    'balance':   None,     # float MYST or None
    'timestamp': 0.0,      # epoch of last successful fetch
    'address':   '',       # address the cache belongs to
}
POLYGONSCAN_CACHE_TTL = 3600  # 1 hour


class EarningsDeltaTracker:
    """Track earnings over time by recording unsettled balance snapshots.
    Persists to disk so it survives toolkit restarts.

    Problem: TequilAPI /sessions only returns sessions from current node process.
    After a node restart, daily/weekly/monthly all show the same (all sessions are 'new').

    Solution: Record unsettled balance every hour. Compute:
      daily = current_unsettled - unsettled_24h_ago
      weekly = current_unsettled - unsettled_7d_ago
      monthly = current_unsettled - unsettled_30d_ago
    Falls back to session-based calculation when no history exists yet.
    """

    _data_file = Path(__file__).parent.parent / 'config' / 'earnings_history.json'
    _snapshots = []   # [{'time': iso_str, 'unsettled': float, 'lifetime': float}]
    _loaded = False
    _load_date = None  # date of last full DB reload — triggers daily refresh
    _was_rate_limited = False  # True after a rate-limited cycle — forces immediate snapshot on recovery

    @classmethod
    def _load(cls, force=False):
        """Load snapshots from SQLite (primary) with one-time JSON migration.
        Auto-refreshes daily so the 35-day rolling window stays current."""
        today = datetime.now(timezone.utc).date()
        if cls._loaded and not force and cls._load_date == today:
            return
        cls._loaded = True
        cls._load_date = today
        global _earnings_db_migrated
        # One-time migration from JSON to SQLite
        if not _earnings_db_migrated:
            EarningsDB.migrate_from_json(cls._data_file)
            _earnings_db_migrated = True
        # Load from SQLite into memory cache (35 days — 5 day margin over 30d delta window
        # prevents snap_30d from missing due to minor timestamp drift near the boundary)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=35)).isoformat()
        rows = EarningsDB.get_all_for_chart(days_back=35) or []
        cls._snapshots = rows

    @classmethod
    def _save(cls):
        """No-op: EarningsDB writes directly in record(). JSON no longer used."""
        pass

    @classmethod
    def record(cls, unsettled, lifetime, identity_ok=True):
        """Record a snapshot of blockchain earnings for delta tracking.

        CRITICAL: Only record when the identity API is confirmed reachable
        (identity_ok=True). When TequilAPI is rate-limited, the identity
        endpoint returns zeros and the caller falls back to session_total —
        a cumulative sum of raw session tokens that can be 50-100+ MYST.
        If we store that as a snapshot and compute deltas against it after
        rate-limiting lifts, we get absurd daily figures like 89 MYST/day.
        Block all non-identity data from entering the history file.
        """
        if not identity_ok:
            logger.info("EarningsDeltaTracker: skipping snapshot — identity API not available")
            cls._was_rate_limited = True  # flag: force immediate snapshot on recovery
            return

        cls._load()
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()

        # On recovery from rate limit: bypass cooldown so the snapshot is timestamped
        # at the actual recovery moment — correct day attribution after a gap.
        recovering = cls._was_rate_limited
        cls._was_rate_limited = False  # clear flag regardless

        # Only record if last snapshot is >9 minutes old (or recovering from rate limit)
        if cls._snapshots:
            last_time = cls._snapshots[-1].get('time', '')
            last_lifetime = float(cls._snapshots[-1].get('lifetime', 0) or 0)
            try:
                last_dt = datetime.fromisoformat(last_time.replace('Z', '+00:00'))
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                elapsed = (now - last_dt).total_seconds()
                if elapsed < 540 and not recovering:  # 9 min — bypass on rate-limit recovery
                    logger.info(f"EarningsDeltaTracker: skip snapshot — only {int(elapsed)}s since last ({last_time[:16]})")
                    return  # Too soon
                else:
                    if recovering:
                        logger.info(f"EarningsDeltaTracker: rate-limit recovery — forcing snapshot after {int(elapsed)}s gap")
                    else:
                        logger.info(f"EarningsDeltaTracker: {int(elapsed)}s since last snapshot — recording new one")
            except (ValueError, TypeError) as e:
                logger.warning(f"EarningsDeltaTracker: bad last_time format '{last_time}' — {e}")
                last_lifetime = 0.0

            # Sanity check: lifetime must be >= previous and must not jump by more
            # than 50 MYST since the last snapshot. A jump larger than this means
            # the data came from a different node (e.g. fleet peer returning laptop
            # earnings) and must never enter the local snapshot history.
            if lifetime < last_lifetime:
                logger.warning(
                    f"EarningsDeltaTracker: REJECTED snapshot — lifetime went backwards "
                    f"({last_lifetime:.4f} → {lifetime:.4f}). Corrupt or wrong-node data."
                )
                return
            if last_lifetime > 0 and (lifetime - last_lifetime) > 50.0:
                logger.warning(
                    f"EarningsDeltaTracker: REJECTED snapshot — lifetime jumped {lifetime - last_lifetime:.4f} MYST "
                    f"({last_lifetime:.4f} → {lifetime:.4f}). Likely wrong-node data from fleet peer."
                )
                return
        else:
            last_lifetime = 0.0

        snap = {
            'time': now_iso,
            'unsettled': round(unsettled, 6),
            'lifetime': round(lifetime, 6),
            'source': 'identity',
        }
        # Write to permanent SQLite storage
        EarningsDB.record(now_iso, unsettled, lifetime, source='identity')
        # Update in-memory cache so 55-min check sees the new snapshot immediately
        # Without this, _snapshots stays stale and the 55-min gate never opens again
        cls._snapshots.append(snap)
        logger.info(f"EarningsDeltaTracker: snapshot recorded — unsettled={unsettled:.4f} lifetime={lifetime:.4f} total_in_memory={len(cls._snapshots)}")
        cls._save()  # no-op but kept for safety

    @classmethod
    def get_deltas(cls, current_unsettled, current_lifetime):
        """Calculate daily/weekly/monthly earnings from snapshot history.

        Strategy:
        - daily:   snapshot closest to 24h ago, within 2h window
        - weekly:  snapshot closest to 168h ago but NEVER older than 168h
                   (stays strictly within 7 days — no inflation possible)
                   search window is dynamic: wider when DB is sparse (startup),
                   tighter when DB is dense (normal operation)
        - monthly: same logic, strictly within 30 days
        - If exact target not found, fallback to oldest available snapshot
          within the period boundary.
        """
        cls._load()
        now = datetime.now(timezone.utc)

        # Dynamic search window based on DB density.
        # With 15-min snapshots: 96/day. A full 7d DB has ~672 snapshots.
        # When sparse (fresh install / gaps), we widen the window so startup
        # periods still produce useful values without crossing period boundaries.
        snap_count = len(cls._snapshots)
        if snap_count < 48:       # less than ~12h of data
            window_long = 28800   # 8 hours
        elif snap_count < 192:    # less than ~2 days
            window_long = 21600   # 6 hours
        else:
            window_long = 14400   # 4 hours (normal operation)

        def find_nearest(hours_ago, max_window_seconds, within_only=False):
            """Find snapshot closest to hours_ago.

            Args:
                hours_ago:          Target age in hours.
                max_window_seconds: Maximum allowed distance from target in seconds.
                within_only:        If True, only consider snapshots that are
                                    YOUNGER than the target time (i.e. strictly
                                    within the period). This prevents a snapshot
                                    from 8 days ago being used as a 7-day baseline.
            """
            target = now - timedelta(hours=hours_ago)
            best = None
            best_diff = float('inf')
            for snap in cls._snapshots:
                try:
                    t = datetime.fromisoformat(snap['time'].replace('Z', '+00:00'))
                    if t.tzinfo is None:
                        t = t.replace(tzinfo=timezone.utc)
                    # within_only: snapshot must be newer than target
                    # (i.e. between target and now — inside the period)
                    if within_only and t < target:
                        continue
                    diff = abs((t - target).total_seconds())
                    if diff < best_diff:
                        best_diff = diff
                        best = snap
                except (ValueError, TypeError, KeyError):
                    pass
            if best and best_diff < max_window_seconds:
                return best
            return None

        result = {'daily': None, 'weekly': None, 'monthly': None, 'source': 'delta'}

        # daily: 2h window, no within_only (small period, both sides fine)
        snap_24h = find_nearest(24,      7200,         within_only=False)
        # weekly: dynamic window, strictly within 7 days
        snap_7d  = find_nearest(24 * 7,  window_long,  within_only=True)
        # monthly: dynamic window, strictly within 30 days
        snap_30d = find_nearest(24 * 30, window_long,  within_only=True)

        def oldest_within(max_age_days):
            """Return the oldest snapshot strictly within max_age_days.
            Never returns a snapshot older than the period — 7d cap stays hard.
            """
            if not cls._snapshots:
                return None
            cutoff = (now - timedelta(days=max_age_days)).isoformat()
            candidates = [
                s for s in cls._snapshots
                if s.get('time', '') >= cutoff
            ]
            if not candidates:
                return None
            try:
                return sorted(candidates, key=lambda s: s.get('time', ''))[0]
            except Exception:
                return None

        if snap_24h:
            result['daily'] = round(max(0, current_lifetime - snap_24h['lifetime']), 4)

        if snap_7d:
            result['weekly'] = round(max(0, current_lifetime - snap_7d['lifetime']), 4)
        elif snap_24h:
            # No snapshot near 7d mark — use oldest within 7 days as partial week baseline.
            # oldest_within guarantees we never cross the 7-day boundary.
            old_snap = oldest_within(max_age_days=7)
            if old_snap:
                delta = round(max(0, current_lifetime - old_snap['lifetime']), 4)
                result['weekly'] = delta if delta <= 20.0 * 7 else None

        if snap_30d:
            result['monthly'] = round(max(0, current_lifetime - snap_30d['lifetime']), 4)
        elif snap_24h:
            # No snapshot near 30d mark — use oldest within 30 days as partial month baseline.
            old_snap = oldest_within(max_age_days=30)
            if old_snap:
                delta = round(max(0, current_lifetime - old_snap['lifetime']), 4)
                result['monthly'] = delta if delta <= 20.0 * 30 else None

        # Sanity check: weekly can never exceed monthly
        if result['weekly'] is not None and result['monthly'] is not None:
            if result['weekly'] > result['monthly']:
                result['weekly'] = result['monthly']

        # If no 24h snapshot yet, signal caller to use session fallback
        if not snap_24h:
            result['source'] = 'sessions'
            return result

        return result


class MetricsCollector:
    """Collects all metrics from Mysterium Node"""

    @staticmethod
    def get_tequilapi_headers():
        """Get auth headers for TequilAPI"""
        auth_string = base64.b64encode(f"{NODE_USERNAME}:{NODE_PASSWORD}".encode()).decode()
        return {'Authorization': f'Basic {auth_string}'}

    @staticmethod
    def _node_label(node_url):
        """Generate short label from node URL, e.g. 'myst0' for port 4050"""
        try:
            port = int(node_url.split(':')[-1].split('/')[0])
            idx = NODE_API_URLS.index(node_url)
            return f"myst{idx}"
        except Exception:
            return node_url

    @staticmethod
    def get_node_status():
        """Get node status from TequilAPI — checks all configured nodes"""
        try:
            headers = MetricsCollector.get_tequilapi_headers()
            nodes_online = []
            nodes_info = []

            for node_url in NODE_API_URLS:
                try:
                    response = requests.get(
                        f'{node_url}/healthcheck',
                        headers=headers,
                        timeout=5
                    )
                    label = MetricsCollector._node_label(node_url)
                    if response.status_code == 200:
                        data = response.json()
                        nodes_online.append(label)
                        nodes_info.append({
                            'label': label,
                            'url': node_url,
                            'status': 'online',
                            'uptime': data.get('uptime', '0s'),
                            'version': data.get('version', 'unknown'),
                        })
                    else:
                        nodes_info.append({
                            'label': label,
                            'url': node_url,
                            'status': 'error',
                            'uptime': '0s',
                            'version': 'unknown',
                        })
                except Exception:
                    label = MetricsCollector._node_label(node_url)
                    nodes_info.append({
                        'label': label,
                        'url': node_url,
                        'status': 'offline',
                        'uptime': '0s',
                        'version': 'unknown',
                    })

            if nodes_online:
                node_status['connected'] = True
                node_status['error'] = None
                # Use first online node's uptime as primary
                primary = nodes_info[0] if nodes_info else {}

                # Fetch NAT type from first online node
                nat_type = 'unknown'
                public_ip = ''
                try:
                    primary_url = primary.get('url', NODE_API_URL)
                    for ep in ('/nat/type', '/connection/status'):
                        try:
                            resp = requests.get(f'{primary_url}{ep}', headers=headers, timeout=3)
                            if resp.status_code == 200:
                                data = resp.json()
                                nt = data.get('type') or data.get('nat_type', '')
                                # 'none' = no NAT (direct connection — best case for VPS)
                                # Accept it as a valid nat_type, not as Python None
                                if nt and nt.lower() != 'unknown':
                                    nat_type = nt.lower()
                                    break
                        except Exception:
                            continue
                    # Fetch public IP
                    try:
                        resp = requests.get(f'{primary_url}/connection/ip', headers=headers, timeout=3)
                        if resp.status_code == 200:
                            public_ip = resp.json().get('ip', '')
                    except Exception:
                        pass
                except Exception:
                    pass

                # Fetch identity from primary node for quality tracking
                # Use cached value if recent (< 10 min) to avoid duplicate /identities calls
                identity_addr = ''
                try:
                    global _identity_cache
                    if _identity_cache['address'] and (time.time() - _identity_cache['ts']) < 600:
                        identity_addr = _identity_cache['address']
                    else:
                        primary_url = primary.get('url', NODE_API_URL)
                        id_resp = requests.get(
                            f'{primary_url}/identities',
                            headers=headers, timeout=3
                        )
                        if id_resp.status_code == 200:
                            ids = id_resp.json().get('identities', [])
                            if ids:
                                identity_addr = ids[0].get('id', '')
                                _identity_cache = {'address': identity_addr, 'ts': time.time()}
                except Exception:
                    pass

                return {
                    'status': 'online',
                    'uptime': primary.get('uptime', '0s'),
                    'version': primary.get('version', 'unknown'),
                    'nat_type': nat_type,
                    'public_ip': public_ip,
                    'identity': identity_addr,
                    'nodes_online': len(nodes_online),
                    'nodes_total': len(NODE_API_URLS),
                    'nodes': nodes_info,
                }
            else:
                node_status['connected'] = False
                node_status['error'] = 'All nodes unreachable'

        except requests.exceptions.ConnectionError as e:
            node_status['error'] = 'Cannot connect to node'
            logger.warning(f"Node connection failed: {e}")
        except Exception as e:
            node_status['error'] = str(e)
            logger.warning(f"Error fetching node status: {e}")

        node_status['connected'] = False
        return {'status': 'offline', 'uptime': '0s', 'version': 'unknown', 'error': node_status['error']}

    @staticmethod
    def _wei_to_myst(wei_value):
        """Convert wei (big int) to MYST. Handles both raw wei and already-converted values."""
        try:
            val = int(wei_value)
            # If value is huge (> 1e15), it's in wei → convert
            # If small, it might already be in MYST from a _tokens field
            if val > 1e15:
                return round(val / 1e18, 4)
            else:
                return round(val, 4)
        except (ValueError, TypeError):
            return 0.0

    # Service types that are internal/infrastructure — excluded from analytics
    # monitoring = Mysterium network probes (0 MYST, infrastructure quality checks)
    # noop       = manual test service, no real consumer traffic
    # NOTE: wireguard = the "Public" service (NodeUI maps Public → wireguard type).
    #       Wireguard sessions ARE real consumer sessions with real MYST earnings.
    #       They must NOT be excluded from analytics.
    INTERNAL_SERVICE_TYPES = frozenset({'monitoring', 'noop'})

    @staticmethod
    def _get_identity_earnings(headers):
        """Get real balance/earnings from /identities/{id} endpoint across ALL nodes"""
        result = {'balance': 0.0, 'unsettled': 0.0, 'lifetime': 0.0,
                  'wallet_address': '', 'channel_address': '', 'hermes_id': '',
                  'reachable': False}  # True when at least one node identity API responded
        try:
            for node_url in NODE_API_URLS:
                try:
                    # Step 1: Get identity list for this node
                    resp = requests.get(f'{node_url}/identities', headers=headers, timeout=5)
                    if resp.status_code != 200:
                        continue
                    identities = resp.json().get('identities', [])
                    if not identities:
                        continue
                    identity_address = identities[0].get('id', '')
                    if not identity_address:
                        continue

                    # Store wallet address (0x... identity)
                    if not result['wallet_address']:
                        result['wallet_address'] = identity_address

                    # Step 2: Get identity details with balance and earnings
                    resp = requests.get(
                        f'{node_url}/identities/{identity_address}',
                        headers=headers, timeout=5
                    )
                    if resp.status_code != 200:
                        continue
                    data = resp.json()

                    # Channel/hermes address if available
                    if not result['channel_address']:
                        result['channel_address'] = data.get('channel_address', '')
                    # hermes_id — needed by settle endpoint
                    if not result.get('hermes_id'):
                        result['hermes_id'] = data.get('hermes_id', '')

                    # Balance (settled)
                    balance_tokens = data.get('balance_tokens', {})
                    if isinstance(balance_tokens, dict) and 'ether' in balance_tokens:
                        result['balance'] += float(balance_tokens['ether'])
                    elif 'balance' in data:
                        result['balance'] += MetricsCollector._wei_to_myst(data['balance'])

                    # Unsettled earnings
                    earnings_tokens = data.get('earnings_tokens', {})
                    if isinstance(earnings_tokens, dict) and 'ether' in earnings_tokens:
                        result['unsettled'] += float(earnings_tokens['ether'])
                    elif 'earnings' in data:
                        result['unsettled'] += MetricsCollector._wei_to_myst(data['earnings'])

                    # Lifetime total
                    earnings_total_tokens = data.get('earnings_total_tokens', {})
                    if isinstance(earnings_total_tokens, dict) and 'ether' in earnings_total_tokens:
                        result['lifetime'] += float(earnings_total_tokens['ether'])
                    elif 'earnings_total' in data:
                        result['lifetime'] += MetricsCollector._wei_to_myst(data['earnings_total'])

                    label = MetricsCollector._node_label(node_url)
                    logger.info(f"Identity earnings [{label}]: unsettled={round(result['unsettled'],4)}")
                    result['reachable'] = True  # at least one node responded with valid identity data
                except Exception as e:
                    logger.warning(f"Error fetching identity from {node_url}: {e}")

            # Round final numeric sums
            for k, v in result.items():
                if isinstance(v, float):
                    result[k] = round(v, 4)
        except Exception as e:
            logger.warning(f"Error fetching identity earnings: {e}")
        return result

    @staticmethod
    def _get_session_earnings(headers):
        """Get time-based earnings breakdown from cached /sessions data"""
        result = {'daily': 0.0, 'weekly': 0.0, 'monthly': 0.0}
        try:
            now = datetime.now(timezone.utc)
            daily_tokens = 0
            weekly_tokens = 0
            monthly_tokens = 0

            items = TequilaCache.get_all_sessions()
            for session in items:
                if session.get('service_type', '').lower() in MetricsCollector.INTERNAL_SERVICE_TYPES:
                    continue
                tokens = int(session.get('tokens', 0))
                if tokens == 0:
                    continue
                started = session.get('created_at', session.get('started_at', ''))
                if started:
                    try:
                        session_time = datetime.fromisoformat(
                            started.replace('Z', '+00:00')
                        )
                        if session_time.tzinfo is None:
                            session_time = session_time.replace(tzinfo=timezone.utc)
                        age_days = (now - session_time).total_seconds() / 86400
                        if age_days <= 1:
                            daily_tokens += tokens
                        if age_days <= 7:
                            weekly_tokens += tokens
                        if age_days <= 30:
                            monthly_tokens += tokens
                        # Sessions older than 30d are simply not counted
                    except (ValueError, TypeError):
                        pass  # Skip sessions with unparseable timestamps

            result['daily'] = round(daily_tokens / 1e18, 4)
            result['weekly'] = round(weekly_tokens / 1e18, 4)
            result['monthly'] = round(monthly_tokens / 1e18, 4)
        except Exception as e:
            logger.warning(f"Error fetching session earnings: {e}")
        return result

    @staticmethod
    def get_earnings():
        """Get earnings combining identity balance (blockchain) with smart time breakdowns.

        Strategy:
        1. Try identity API for real unsettled/balance/lifetime (blockchain source of truth)
        2. Always compute session_total from /sessions tokens (available even when identity blocked)
        3. Record whichever value we have into EarningsDeltaTracker
        4. If 24h+ of history → daily/weekly/monthly from deltas (accurate)
        5. If <24h of history → show session_total as "since boot", don't fake daily=weekly=monthly
        """
        headers = MetricsCollector.get_tequilapi_headers()

        # Real balance/unsettled/lifetime from identity endpoint
        identity_data = MetricsCollector._get_identity_earnings(headers)

        # Always compute session total (works even when identity API is blocked)
        session_data = MetricsCollector._get_session_earnings(headers)
        session_total = session_data.get('monthly', 0)  # monthly = all sessions within 30d

        # identity_ok = True only when the identity API actually returned real blockchain data.
        # If rate-limited, identity_data is all zeros — we must NOT record session_total
        # as a snapshot because it will corrupt future delta calculations.
        # FIX: check 'reachable' flag instead of lifetime > 0.
        # A fresh node with 0 lifetime earnings is valid and must record snapshots.
        # Previously: identity_ok = identity_data['lifetime'] > 0 — wrong, blocked fresh nodes.
        identity_ok = identity_data.get('reachable', identity_data['lifetime'] > 0)

        # For delta tracking always use blockchain values — never session_total fallback.
        # session_total is a cumulative raw token sum (can be 100+ MYST) and would
        # produce absurd daily/weekly figures when compared against real lifetime later.
        if identity_ok:
            EarningsDeltaTracker.record(
                identity_data['unsettled'],
                identity_data['lifetime'],
                identity_ok=True,
            )

        # Try delta-based earnings (accurate across node restarts)
        delta = EarningsDeltaTracker.get_deltas(
            identity_data['unsettled'],
            identity_data['lifetime'],
        )

        if not identity_ok:
            # Rate-limited or blocked: identity API unavailable.
            # Show session_total as a rough indicator but clearly label it.
            # Never compute deltas without real data.
            daily = session_total if session_total > 0 else None
            weekly = None
            monthly = None
            earnings_source = 'rate_limited'
        elif delta['source'] == 'delta':
            # Best case: delta tracking has enough history → accurate period breakdowns.
            daily = delta['daily']
            weekly = delta['weekly']
            monthly = delta['monthly']
            earnings_source = 'delta'
        else:
            # Identity API OK but <24h of snapshot history.
            # We DO NOT show session_total as "daily" — session_total is an
            # inflated cumulative sum of raw promise tokens (can be 1000+ MYST
            # while real lifetime is 277 MYST). It must never be labelled as
            # a time-period figure. Show None and let UI say "Building...".
            daily = None
            weekly = None
            monthly = None
            earnings_source = 'building'

        return {
            'balance': identity_data['balance'],
            'unsettled': identity_data['unsettled'],
            'lifetime': identity_data['lifetime'],
            'session_total': session_total,
            'daily': daily,
            'weekly': weekly,
            'monthly': monthly,
            'earnings_source': earnings_source,
            'wallet_address': identity_data.get('wallet_address', ''),
            'channel_address': identity_data.get('channel_address', ''),
        }

    # VPN interface name patterns (myst0..myst14+, wg0..wgN, tun0..tunN)
    VPN_IFACE_PREFIXES = ('myst', 'wg', 'tun')

    @staticmethod
    def get_bandwidth():
        """Get bandwidth using real data sources — no phantom accumulation.

        Data hierarchy (best → fallback):
        1. vnstat on myst*/wg*/tun* interfaces → accurate today/month with correct in/out
        2. psutil snapshot → live per-interface counters (since service start only)
        3. TequilAPI sessions → paid/unpaid breakdown only (underreports total)

        Traffic direction on myst* interfaces (exit node provider perspective):
          rx = bytes from consumer entering tunnel (requests — SMALL)
          tx = bytes to consumer leaving tunnel (content forwarded — BIG)
        So: tx is what you earn for. rx is consumer requests.
        """
        try:
            # ---- Live VPN interface snapshot (psutil) ----
            vpn_rx, vpn_tx, vpn_ifaces = VpnTrafficSnapshot.get_snapshot()

            # ---- vnstat for time-windowed data ----
            vnstat = MetricsCollector._get_vnstat_traffic()

            # ---- Determine today/month data source ----
            has_vpn_vnstat = vnstat and vnstat.get('has_vpn_vnstat', False)

            if has_vpn_vnstat:
                # Best source: vnstat tracks myst* interfaces directly
                today_rx = vnstat['vpn_today_rx']
                today_tx = vnstat['vpn_today_tx']
                month_rx = vnstat['vpn_month_rx']
                month_tx = vnstat['vpn_month_tx']
                data_source = 'vnstat'
            else:
                # Fallback: psutil counters (only valid since last service start)
                today_rx = vpn_rx
                today_tx = vpn_tx
                month_rx = vpn_rx  # same — can't distinguish without vnstat
                month_tx = vpn_tx
                data_source = 'psutil'

            # ---- Paid session traffic from TequilaCache (no HTTP calls) ----
            paid_in = 0
            paid_out = 0

            for session in TequilaCache.get_all_sessions():
                if session.get('service_type', '').lower() in MetricsCollector.INTERNAL_SERVICE_TYPES:
                    continue
                tokens = int(session.get('tokens', 0))
                if tokens > 0:
                    paid_in += int(session.get('bytes_received', 0))
                    paid_out += int(session.get('bytes_sent', 0))

            result = {
                # Data source indicator
                'data_source': data_source,

                # Today's VPN tunnel traffic
                'vpn_today_in': round(today_rx / (1024 * 1024), 2),
                'vpn_today_out': round(today_tx / (1024 * 1024), 2),
                'vpn_today_total': round((today_rx + today_tx) / (1024 * 1024), 2),

                # This month's VPN tunnel traffic
                'vpn_month_in': round(month_rx / (1024 * 1024), 2),
                'vpn_month_out': round(month_tx / (1024 * 1024), 2),
                'vpn_month_total': round((month_rx + month_tx) / (1024 * 1024), 2),

                # Live psutil snapshot (since service start)
                'in': round(vpn_rx / (1024 * 1024), 2),
                'out': round(vpn_tx / (1024 * 1024), 2),
                'total': round((vpn_rx + vpn_tx) / (1024 * 1024), 2),

                # Paid session bandwidth from TequilAPI
                'paid_in': round(paid_in / (1024 * 1024), 2),
                'paid_out': round(paid_out / (1024 * 1024), 2),
                'paid_total': round((paid_in + paid_out) / (1024 * 1024), 2),

                # Per-interface breakdown (always psutil, always live)
                'vpn_interfaces': {
                    name: {
                        'rx_mb': round(d['rx'] / (1024 * 1024), 2),
                        'tx_mb': round(d['tx'] / (1024 * 1024), 2),
                    } for name, d in vpn_ifaces.items()
                },
            }

            # Enrich with vnstat NIC data
            if vnstat:
                MB = 1024 * 1024
                result['vnstat_nic_name']     = vnstat['nic_name']
                result['vnstat_today_rx']     = round(vnstat['today_rx']    / MB, 2)
                result['vnstat_today_tx']     = round(vnstat['today_tx']    / MB, 2)
                result['vnstat_today_total']  = round(vnstat['today_total'] / MB, 2)
                result['vnstat_month_rx']     = round(vnstat['month_rx']    / MB, 2)
                result['vnstat_month_tx']     = round(vnstat['month_tx']    / MB, 2)
                result['vnstat_month_total']  = round(vnstat['month_total'] / MB, 2)
                result['vnstat_available']    = True
                result['has_vpn_vnstat']      = has_vpn_vnstat
            else:
                result['vnstat_nic_name']    = 'NIC'
                result['vnstat_today_rx']    = 0.0
                result['vnstat_today_tx']    = 0.0
                result['vnstat_today_total'] = 0.0
                result['vnstat_month_rx']    = 0.0
                result['vnstat_month_tx']    = 0.0
                result['vnstat_month_total'] = 0.0
                result['vnstat_available']   = False
                result['has_vpn_vnstat']     = False

            return result
        except Exception as e:
            logger.warning(f"Error fetching bandwidth: {e}")

        return {
            'paid_in': 0.0, 'paid_out': 0.0, 'paid_total': 0.0,
            'in': 0.0, 'out': 0.0, 'total': 0.0,
            'vpn_today_in': 0.0, 'vpn_today_out': 0.0, 'vpn_today_total': 0.0,
            'vpn_month_in': 0.0, 'vpn_month_out': 0.0, 'vpn_month_total': 0.0,
            'vnstat_available': False, 'vnstat_nic_name': 'NIC',
            'vnstat_today_total': 0.0, 'vnstat_month_total': 0.0,
            'vpn_interfaces': {}, 'has_vpn_vnstat': False, 'data_source': 'none',
        }

    @staticmethod
    def get_services():
        """Get running services from TequilaCache (no HTTP calls)"""
        try:
            services = []
            for node_url in NODE_API_URLS:
                data = TequilaCache.get(node_url, '/services')
                if not data:
                    continue
                items = data if isinstance(data, list) else data.get('items', data.get('services', []))
                node_label = MetricsCollector._node_label(node_url)

                for svc in items:
                    svc_type = svc.get('type', svc.get('service_type', 'unknown'))
                    svc_status = svc.get('status', 'unknown')
                    proposal = svc.get('proposal', {})

                    services.append({
                        'id': svc.get('id', ''),
                        'type': svc_type,
                        'status': svc_status,
                        'provider_id': proposal.get('provider_id', svc.get('provider_id', ''))[:16],
                        'is_active': svc_status.lower() in ('running', 'active'),
                        'node': node_label,
                    })

            if ServiceEventsDB:
                try:
                    ServiceEventsDB.record_services_snapshot(services, node_id=_local_node_id)
                except Exception as e:
                    logger.debug(f"ServiceEventsDB record failed: {e}")
            return {
                'items': services,
                'total': len(services),
                'active': sum(1 for s in services if s['is_active']),
            }
        except Exception as e:
            logger.warning(f"Error fetching services: {e}")

        return {'items': [], 'total': 0, 'active': 0}

    @staticmethod
    def _count_vpn_tunnels():
        """Count active VPN tunnel interfaces — ground truth for connected clients.
        psutil is authoritative: if a myst* interface exists with traffic, a client IS connected."""
        try:
            per_nic = psutil.net_io_counters(pernic=True)
            active = 0
            for name, counters in per_nic.items():
                if any(name.startswith(p) for p in MetricsCollector.VPN_IFACE_PREFIXES):
                    if counters.bytes_sent + counters.bytes_recv > 0:
                        active += 1
            return active
        except Exception:
            return 0

    @staticmethod
    def get_sessions():
        """Get actual client sessions from ALL configured nodes (via TequilaCache).
        Filters out monitoring probes and service registration entries.

        CRITICAL: TequilAPI marks sessions as "Completed" even while tunnels are still active.
        We use VPN interface count (psutil) as ground truth for active session count.
        """
        try:
            now = datetime.now(timezone.utc)
            sessions = []
            total_svc_connections = 0

            # Get connection count from cached services
            for svc in TequilaCache.get_all_services():
                cc = int(svc.get('connection_count', svc.get('connections_count', 0)))
                total_svc_connections += cc

            # Ground truth: count active VPN tunnel interfaces
            vpn_tunnel_count = MetricsCollector._count_vpn_tunnels()

            # Collect live VPN interface bytes (psutil, cumulative since boot)
            # These are the REAL bytes flowing through WireGuard/myst* interfaces.
            # TequilAPI only reports bytes AFTER session completion, so for active
            # sessions we show these totals as a live indicator instead.
            live_vpn_rx = 0
            live_vpn_tx = 0
            try:
                per_nic_live = psutil.net_io_counters(pernic=True)
                for iname, counters in per_nic_live.items():
                    if any(iname.startswith(p) for p in MetricsCollector.VPN_IFACE_PREFIXES):
                        live_vpn_rx += counters.bytes_recv
                        live_vpn_tx += counters.bytes_sent
            except Exception:
                pass

            # Process all cached sessions
            for session in TequilaCache.get_all_sessions():
                tokens = int(session.get('tokens', 0))
                b_in = int(session.get('bytes_received', 0))
                b_out = int(session.get('bytes_sent', 0))
                service_type = session.get('service_type', 'unknown')
                status = session.get('status', '')
                session_id = session.get('id', '')

                if service_type.lower() in MetricsCollector.INTERNAL_SERVICE_TYPES:
                    continue
                # Only skip sessions with zero bytes AND zero tokens AND no duration
                # Sessions with bytes but 0 tokens are valid (tokens zeroed after settlement)
                if b_in == 0 and b_out == 0 and tokens == 0:
                    # Still include if session has a meaningful status
                    status_lower_check = (session.get('status', '') or '').lower()
                    if status_lower_check not in ('new', 'running', 'established', 'active'):
                        continue

                # Active detection from API status
                status_lower = status.lower().strip() if status else ''
                explicitly_closed = status_lower in (
                    'completed', 'closed', 'errored', 'canceled',
                    'cancelled', 'finished', 'terminated'
                )
                active_status_val = status_lower in (
                    'new', 'running', 'established', 'active', 'connecting'
                )
                no_status = status_lower == ''

                recently_updated = False
                updated_at = session.get('updated_at', '')
                if updated_at:
                    try:
                        update_time = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
                        if update_time.tzinfo is None:
                            update_time = update_time.replace(tzinfo=timezone.utc)
                        if (now - update_time).total_seconds() < 600:
                            recently_updated = True
                    except (ValueError, TypeError):
                        pass

                recently_started = False
                started = session.get('created_at', session.get('started_at', ''))
                if started and not explicitly_closed:
                    try:
                        start_time = datetime.fromisoformat(started.replace('Z', '+00:00'))
                        if start_time.tzinfo is None:
                            start_time = start_time.replace(tzinfo=timezone.utc)
                        if (now - start_time).total_seconds() < 86400:
                            recently_started = True
                    except (ValueError, TypeError):
                        pass

                is_active = (
                    active_status_val
                    or (no_status and (recently_updated or recently_started))
                    or (not explicitly_closed and recently_updated)
                )

                # Ghost session filter:
                # Mysterium sometimes leaves sessions as 'running' after settlement
                # but zeros out bytes and tokens. A real idle session always has
                # at least handshake bytes and is relatively recent.
                # If session is 4h+ old with zero bytes AND zero tokens → ghost, mark inactive.
                if is_active and b_in == 0 and b_out == 0 and tokens == 0:
                    if started:
                        try:
                            start_time = datetime.fromisoformat(started.replace('Z', '+00:00'))
                            if start_time.tzinfo is None:
                                start_time = start_time.replace(tzinfo=timezone.utc)
                            age_hours = (now - start_time).total_seconds() / 3600
                            if age_hours > 4:
                                is_active = False  # ghost — too old with no traffic at all
                        except (ValueError, TypeError):
                            pass

                # Parse duration — format HH:MM:SS
                # Priority: API-provided 'duration' field (seconds int) — accurate for all sessions.
                # Fallback for active sessions: now - created_at (elapsed so far).
                # The old updated_at - started_at approach is abandoned: updated_at is None
                # for historical sessions and started_at is also None (only created_at exists).
                duration_str = '00:00:00'
                started_fmt = ''

                # Format started timestamp for display
                if started:
                    try:
                        start_time = datetime.fromisoformat(started.replace('Z', '+00:00'))
                        if start_time.tzinfo is None:
                            start_time = start_time.replace(tzinfo=timezone.utc)
                        started_fmt = start_time.strftime('%d/%m/%Y, %H:%M:%S')
                    except (ValueError, TypeError):
                        started_fmt = ''

                # Duration calculation
                api_duration = session.get('duration')
                delta_secs = 0  # initialised before try so duration_secs is always defined
                try:
                    if api_duration is not None and not is_active:
                        # Completed session: use API-provided duration (seconds integer) — exact
                        delta_secs = max(0, int(api_duration))
                    elif started:
                        # Active session: elapsed since created_at
                        start_time = datetime.fromisoformat(started.replace('Z', '+00:00'))
                        if start_time.tzinfo is None:
                            start_time = start_time.replace(tzinfo=timezone.utc)
                        delta_secs = max(0, (now - start_time).total_seconds())
                    else:
                        delta_secs = 0
                    h = int(delta_secs // 3600)
                    m = int((delta_secs % 3600) // 60)
                    s = int(delta_secs % 60)
                    duration_str = f"{h:02d}:{m:02d}:{s:02d}"
                except (ValueError, TypeError):
                    duration_str = '—'

                # Extract consumer country (FIX 5)
                consumer_country = session.get('consumer_country', '')
                if not consumer_country:
                    consumer_country = session.get('consumer_location', {}).get('country', '') if isinstance(session.get('consumer_location'), dict) else ''

                # bytes_pending: True when session is active but TequilAPI hasn't
                # reported bytes yet (Mysterium only settles bytes at session close).
                # The frontend shows "—" instead of "0 MB" for these sessions.
                bytes_pending = is_active and b_in == 0 and b_out == 0

                sessions.append({
                    'id': session_id,
                    'consumer_id': session.get('consumer_id', 'unknown'),
                    'service_type': service_type,
                    'status': status or '(active)',
                    'started': started,
                    'started_fmt': started_fmt,
                    'duration': duration_str,
                    'duration_secs': round(delta_secs),
                    'data_in': round(b_in / (1024 * 1024), 2),
                    'data_out': round(b_out / (1024 * 1024), 2),
                    'data_total': round((b_in + b_out) / (1024 * 1024), 2),
                    'tokens': tokens,
                    'earnings_myst': round(tokens / 1e18, 8),
                    'is_paid': tokens > 0,
                    'is_active': is_active,
                    'bytes_pending': bytes_pending,
                    'consumer_country': consumer_country,
                })

            # Sort: active first, then by start time (most recent first)
            sessions.sort(key=lambda s: s.get('started', ''), reverse=True)   # newest first
            sessions.sort(key=lambda s: s['is_active'], reverse=True)          # active on top
            active_count = sum(1 for s in sessions if s['is_active'])

            # VPN ground truth override — last resort only.
            # WireGuard interfaces linger for minutes after a consumer disconnects.
            # If we compared vpn_tunnel_count > active_count we would force-mark
            # recently-completed sessions as active (causing the same consumer to
            # appear twice when they reconnect before the stale interface is cleaned up).
            # Only trigger when TequilAPI reports ZERO active sessions despite live
            # tunnels existing — that is the real "API hasn't caught up yet" case.
            effective_active = max(vpn_tunnel_count, total_svc_connections)
            if effective_active > 0 and active_count == 0 and sessions:
                # Mark the N most recent sessions as active
                marked = 0
                for s in sessions:
                    if marked >= effective_active:
                        break
                    if not s['is_active']:
                        s['is_active'] = True
                        s['status'] = '(active — tunnel up)'
                        marked += 1
                active_count = sum(1 for s in sessions if s['is_active'])

            # ===== CONSUMER ANALYTICS (Items 4-6) =====
            consumer_map = {}
            for s in sessions:
                cid = s.get('consumer_id', 'unknown')
                if cid not in consumer_map:
                    consumer_map[cid] = {
                        'consumer_id': cid,
                        'consumer_country': s.get('consumer_country', ''),
                        'sessions': 0,
                        'active_sessions': 0,
                        'total_data_mb': 0,
                        'total_earnings': 0,
                        'last_seen': s.get('started', ''),
                        '_service_types': set(),
                    }
                c = consumer_map[cid]
                c['sessions'] += 1
                if s['is_active']:
                    c['active_sessions'] += 1
                c['total_data_mb'] += s.get('data_total', 0)
                c['total_earnings'] += s.get('earnings_myst', 0)
                if s.get('consumer_country') and not c['consumer_country']:
                    c['consumer_country'] = s['consumer_country']
                if s.get('service_type'):
                    c['_service_types'].add(s['service_type'])

            # Sort consumers by earnings descending, convert sets to lists for JSON
            for c in consumer_map.values():
                c['service_types'] = sorted(c.pop('_service_types', set()))
            top_consumers = sorted(consumer_map.values(),
                                   key=lambda c: (-c['total_earnings'], -c['total_data_mb']))

            unique_consumers = len(consumer_map)
            paying_consumers = sum(1 for c in consumer_map.values() if c['total_earnings'] > 0)

            # ===== SERVICE TYPE BREAKDOWN =====
            # Count sessions, earnings and data per business service type.
            # Combine live TequilAPI sessions with all historical sessions from SessionDB.
            # SessionDB contains every session ever seen, with tokens frozen before settlement.
            # Live sessions override DB version for active sessions (most recent data wins).
            # No date filter — each node's database contains only its own sessions.
            # Cross-node mixing is prevented by migrate_data.py identity checks.
            db_sessions = []
            db_rows = []  # kept for country breakdown below
            try:
                db_rows = SessionDB.get_range(limit=50000, offset=0)
                live_ids = {s.get('id') for s in sessions if s.get('id')}
                for row in db_rows:
                    if row.get('id') not in live_ids:
                        tokens_wei = row.get('tokens', 0) or 0
                        earnings_myst = tokens_wei / 1e18
                        bytes_total = (row.get('bytes_sent', 0) or 0) + (row.get('bytes_received', 0) or 0)
                        db_sessions.append({
                            'id':               row.get('id', ''),
                            'service_type':     row.get('service_type', 'unknown') or 'unknown',
                            'consumer_country': row.get('consumer_country', '') or '',
                            'earnings_myst':    earnings_myst,
                            'data_total':       bytes_total / (1024 * 1024),
                            'is_active':        False,
                        })
            except Exception as _db_e:
                logger.warning(f"SessionDB read for analytics failed: {_db_e}")

            # Merge: live sessions first, then historical DB sessions not in live set
            analytics_sessions = sessions + db_sessions

            # monitoring and noop are excluded — they are internal infrastructure sessions.
            # wireguard = Public service — these ARE real consumer sessions (NodeUI confirms).
            svc_map = {}
            monitoring_sessions = 0  # monitoring probe sessions (excluded from analytics)
            total_earnings_all = 0.0
            total_data_all_mb  = 0.0
            total_session_time_s = 0
            total_sessions_all   = 0  # business sessions only
            for s in analytics_sessions:
                st = s.get('service_type', 'unknown') or 'unknown'
                if st in MetricsCollector.INTERNAL_SERVICE_TYPES:
                    if st == 'monitoring':
                        monitoring_sessions += 1
                    continue
                total_sessions_all += 1
                if st not in svc_map:
                    svc_map[st] = {'service_type': st, 'sessions': 0,
                                   'earnings_myst': 0.0, 'data_mb': 0.0}
                svc_map[st]['sessions']      += 1
                svc_map[st]['earnings_myst'] += s.get('earnings_myst', 0)
                svc_map[st]['data_mb']       += s.get('data_total', 0)
                total_earnings_all += s.get('earnings_myst', 0)
                total_data_all_mb  += s.get('data_total', 0)

            service_breakdown = []
            for st, entry in sorted(svc_map.items(), key=lambda x: -x[1]['earnings_myst']):
                pct_earn = round(entry['earnings_myst'] / total_earnings_all * 100, 1) \
                           if total_earnings_all > 0 else 0.0
                pct_sess = round(entry['sessions'] / total_sessions_all * 100, 1) \
                           if total_sessions_all > 0 else 0.0
                pct_data = round(entry['data_mb'] / total_data_all_mb * 100, 1) \
                           if total_data_all_mb > 0 else 0.0
                service_breakdown.append({
                    'service_type':  st,
                    'sessions':      entry['sessions'],
                    'earnings_myst': round(entry['earnings_myst'], 6),
                    'data_mb':       round(entry['data_mb'], 2),
                    'pct_earnings':  pct_earn,
                    'pct_sessions':  pct_sess,
                    'pct_data':      pct_data,
                })

            # ===== COUNTRY BREAKDOWN =====
            # IMPORTANT: scan ALL sessions for countries — not just analytics_sessions.
            # analytics_sessions filters out 0-bytes/0-tokens completed sessions (e.g. Public
            # sessions from RO/FI/FR that connected briefly but transferred nothing).
            # Those sessions are real consumers with a real country and must appear here.
            # We build country data from three sources:
            #   1. Full TequilaCache (all live sessions including 0-byte ones)
            #   2. SessionDB rows not already covered by live
            country_map = {}
            total_sessions_with_country = 0

            # Source 1: full live cache — includes 0-byte/0-token completed sessions
            all_live_for_country = TequilaCache.get_all_sessions()
            all_live_ids_country = set()
            for s in all_live_for_country:
                st_cc = (s.get('service_type', '') or '').lower()
                if st_cc in MetricsCollector.INTERNAL_SERVICE_TYPES:
                    continue
                sid = s.get('id', '')
                if sid:
                    all_live_ids_country.add(sid)
                cc = s.get('consumer_country', '') or ''
                if not cc:
                    continue
                total_sessions_with_country += 1
                if cc not in country_map:
                    country_map[cc] = {'country': cc, 'sessions': 0,
                                       'earnings_myst': 0.0, 'data_mb': 0.0}
                tokens_raw = int(s.get('tokens', 0) or 0)
                b_s = int(s.get('bytes_sent', 0) or 0)
                b_r = int(s.get('bytes_received', 0) or 0)
                country_map[cc]['sessions']      += 1
                country_map[cc]['earnings_myst'] += round(tokens_raw / 1e18, 8)
                country_map[cc]['data_mb']       += (b_s + b_r) / (1024 * 1024)

            # Source 2: DB sessions not in live cache
            for row in db_rows:
                if row.get('id') in all_live_ids_country:
                    continue
                st_cc = (row.get('service_type', '') or '').lower()
                if st_cc in MetricsCollector.INTERNAL_SERVICE_TYPES:
                    continue
                cc = row.get('consumer_country', '') or ''
                if not cc:
                    continue
                total_sessions_with_country += 1
                if cc not in country_map:
                    country_map[cc] = {'country': cc, 'sessions': 0,
                                       'earnings_myst': 0.0, 'data_mb': 0.0}
                tokens_wei = row.get('tokens', 0) or 0
                bytes_total = (row.get('bytes_sent', 0) or 0) + (row.get('bytes_received', 0) or 0)
                country_map[cc]['sessions']      += 1
                country_map[cc]['earnings_myst'] += tokens_wei / 1e18
                country_map[cc]['data_mb']       += bytes_total / (1024 * 1024)

            country_breakdown = sorted(
                [{'country': k,
                  'sessions': v['sessions'],
                  'earnings_myst': round(v['earnings_myst'], 6),
                  'data_mb': round(v['data_mb'], 2),
                  'pct_sessions': round(v['sessions'] / total_sessions_with_country * 100, 1)
                                  if total_sessions_with_country > 0 else 0.0}
                 for k, v in country_map.items()],
                key=lambda x: -x['sessions']
            )

            # ===== NODE TOTALS FROM TEQUILAPI (what the node currently has in memory) =====
            # This is what the node's /sessions endpoint reports — all pages loaded at startup.
            # Separate from SessionDB (toolkit archive) which is shown below in the UI.
            lifetime_totals = {
                'sessions':      total_sessions_all,
                'earnings_myst': round(total_earnings_all, 6),
                'data_gb':       round(total_data_all_mb / 1024, 3),
            }

            active_items = [s for s in sessions if s.get('is_active')]
            active_unique_consumers = len({s['consumer_id'] for s in sessions if s.get('is_active') and s.get('consumer_id')})

            return {
                'items': sessions,
                'active_items': active_items,
                'active_unique_consumers': active_unique_consumers,
                'total': len(sessions),
                'total_shown': len(sessions),
                'total_in_store': len(sessions),
                'total_items_api': SessionStore._total_items.get(NODE_API_URLS[0] if NODE_API_URLS else '', 0),
                'history_loaded': SessionStore.is_ready(NODE_API_URLS[0] if NODE_API_URLS else ''),
                'active': active_count,
                'vpn_tunnel_count': vpn_tunnel_count,
                'live_vpn_rx_mb': round(live_vpn_rx / (1024 * 1024), 2),
                'live_vpn_tx_mb': round(live_vpn_tx / (1024 * 1024), 2),
                'unique_consumers': unique_consumers,
                'paying_consumers': paying_consumers,
                'top_consumers': top_consumers,
                'service_breakdown': service_breakdown,
                'monitoring_sessions': monitoring_sessions,
                'country_breakdown': country_breakdown,
                'lifetime_totals':   lifetime_totals,
            }
        except Exception as e:
            logger.warning(f"Error fetching sessions: {e}")

        return {'items': [], 'total': 0, 'active': 0, 'vpn_tunnel_count': 0,
                'unique_consumers': 0, 'paying_consumers': 0, 'top_consumers': [],
                'service_breakdown': [], 'country_breakdown': [], 'lifetime_totals': {'sessions': 0, 'earnings_myst': 0, 'data_gb': 0}}

    @staticmethod
    def get_clients():
        """Get connected client count — uses VPN tunnel count as ground truth.
        TequilAPI connection_count is unreliable (often 0), so we use psutil."""
        try:
            svc_connections = 0

            # API-reported connection count (often 0, unreliable)
            for svc in TequilaCache.get_all_services():
                cc = int(svc.get('connection_count', svc.get('connections_count', 0)))
                svc_connections += cc

            # Ground truth: VPN tunnel count from psutil
            vpn_tunnels = MetricsCollector._count_vpn_tunnels()

            # Use the higher of the two — psutil is authoritative
            connected = max(svc_connections, vpn_tunnels)

            global peak_clients
            if connected > peak_clients:
                peak_clients = connected

            # active_sessions: read from cached medium-cycle data if available
            # This is the number of sessions with is_active=True (may be > vpn_tunnels
            # because each physical client can have multiple service sessions).
            cached_sessions = data_cache.get('sessions', {}) if 'data_cache' in dir() else {}
            active_sessions = cached_sessions.get('active', connected)

            # unique_consumers: distinct consumer IDs from active sessions
            cached_sessions2 = data_cache.get('sessions', {}) if 'data_cache' in dir() else {}
            unique_consumers = cached_sessions2.get('unique_consumers', 0)

            return {
                'connected': connected,
                'peak': peak_clients,
                'vpn_tunnels': vpn_tunnels,
                'api_connections': svc_connections,
                'active_sessions': active_sessions,
                'unique_consumers': unique_consumers,
            }
        except Exception as e:
            logger.warning(f"Error fetching clients: {e}")

        return {'connected': 0, 'peak': peak_clients, 'vpn_tunnels': 0, 'api_connections': 0}

    # Track previous net_io for delta-based speed calculation (per-VPN-interface)
    _prev_vpn_rx = None
    _prev_vpn_tx = None
    _prev_net_time = None

    # System-wide NIC speed tracking
    _prev_sys_rx = None
    _prev_sys_tx = None
    _prev_sys_time = None

    # Cached ping result — updated async so it doesn't block collection
    _cached_latency = 0.0
    _cached_packet_loss = 0.0
    _ping_thread = None

    # Cached CPU — use interval=0 (instant, delta from last call)
    _cpu_primed = False

    @staticmethod
    def _ping_worker():
        """Run ping in background, update cached result."""
        try:
            result = subprocess.run(
                ['ping', '-c', '1', '-W', '3', '8.8.8.8'],
                capture_output=True, timeout=5, text=True
            )
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'time=' in line:
                        try:
                            MetricsCollector._cached_latency = float(
                                line.split('time=')[1].split(' ')[0])
                        except (ValueError, IndexError):
                            pass
                        break
                MetricsCollector._cached_packet_loss = 0.0
            else:
                MetricsCollector._cached_packet_loss = 100.0
        except Exception:
            pass
        MetricsCollector._ping_thread = None

    @staticmethod
    def _ensure_vnstat_interfaces():
        """Auto-register any myst* interfaces that vnstat is not yet tracking.

        Called in the medium-tier collection cycle (every 120s).  Each myst*
        interface that exists in the kernel but is absent from vnstat's database
        is registered with `vnstat --add -i <iface>`.  The operation is harmless
        if the interface is already registered (vnstat prints an error and exits
        non-zero, which we just log and ignore).

        This mirrors what the udev rule does at the instant an interface appears,
        serving as a catch-all for interfaces created before the toolkit started
        or on systems where the udev rule has not yet been installed.
        """
        if not shutil.which('vnstat'):
            return  # vnstat not installed

        # Get list of currently active myst* interfaces from the kernel
        try:
            active_myst = [
                name for name in psutil.net_if_stats().keys()
                if name.startswith('myst')
            ]
        except Exception:
            return

        if not active_myst:
            return

        # Get list of interfaces already registered in vnstat's database
        registered = set()
        try:
            r = subprocess.run(
                ['vnstat', '--json'],
                capture_output=True, timeout=5, text=True
            )
            if r.returncode == 0:
                data = json.loads(r.stdout)
                for iface in data.get('interfaces', []):
                    registered.add(iface.get('name', ''))
        except Exception:
            pass  # If we can't query, attempt registration anyway

        # Register any myst* interfaces not yet in vnstat
        for iface in active_myst:
            if iface not in registered:
                try:
                    result = subprocess.run(
                        ['vnstat', '--add', '-i', iface],
                        capture_output=True, timeout=5, text=True
                    )
                    if result.returncode == 0:
                        logger.info(f"vnstat: registered new interface {iface}")
                    else:
                        # Already registered or permission error — not a problem
                        logger.debug(f"vnstat --add {iface}: {result.stderr.strip()}")
                except Exception as e:
                    logger.debug(f"vnstat --add {iface} failed: {e}")

    # ------------------------------------------------------------------ #
    #  NODE QUALITY — sourced from Mysterium's public Discovery API        #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _load_uptime_log() -> list:
        """Load persisted uptime ping timestamps from disk."""
        try:
            if UPTIME_FILE.exists():
                data = json.loads(UPTIME_FILE.read_text())
                if isinstance(data, list):
                    return [float(t) for t in data]
        except Exception:
            pass
        return []

    @staticmethod
    def _save_uptime_log(timestamps: list):
        """Persist uptime ping timestamps to disk, pruning entries > 31 days."""
        cutoff = time.time() - (31 * 86400)
        pruned = [t for t in timestamps if t >= cutoff]
        try:
            UPTIME_FILE.parent.mkdir(parents=True, exist_ok=True)
            UPTIME_FILE.write_text(json.dumps(pruned))
        except Exception as e:
            logger.debug(f"uptime log write failed: {e}")
        return pruned

    @staticmethod
    def record_uptime_ping(identity=None):
        """Record that the node was observed online right now.

        If identity has changed (new node / reinstall), uptime log is reset
        so stale 30d data from a previous node is not shown.
        """
        # Identity guard — reset uptime log if identity changed OR on fresh install
        if identity:
            try:
                IDENTITY_FILE.parent.mkdir(parents=True, exist_ok=True)
                is_fresh = not IDENTITY_FILE.exists()
                stored = IDENTITY_FILE.read_text().strip() if not is_fresh else ''

                if is_fresh:
                    # Fresh install — always reset uptime log so we start clean
                    logger.info(f"Fresh install detected (identity: {identity[:10]}…) — resetting uptime log")
                    if UPTIME_FILE.exists():
                        UPTIME_FILE.unlink()
                elif stored != identity:
                    # Identity changed — reset uptime log
                    logger.info(f"Node identity changed ({stored[:10]}→{identity[:10]}) — resetting uptime log")
                    if UPTIME_FILE.exists():
                        UPTIME_FILE.unlink()

                IDENTITY_FILE.write_text(identity)
            except Exception as e:
                logger.debug(f"Identity file write failed: {e}")

        ts = time.time()
        pings = MetricsCollector._load_uptime_log()
        pings.append(ts)
        return MetricsCollector._save_uptime_log(pings)

    @staticmethod
    def compute_uptime_stats() -> dict:
        """Compute online percentage for last 24 h and last 30 days.

        Logic: count observed-online pings in each window, divide by the
        number of poll slots that actually occurred (i.e. when the toolkit
        was running).  Gaps larger than 2.5x the collection interval are treated
        as "toolkit not running" and excluded from the denominator so that
        server restarts do not falsely lower the uptime percentage.  Cap at 100%.

        Returns dict with keys:
          uptime_24h      — float 0-100
          uptime_30d      — float 0-100
          total_pings     — int (all stored pings)
          tracking_since  — ISO datetime of oldest ping, or None
          tracking_days   — int days of data accumulated, 0-30
        """
        pings = MetricsCollector._load_uptime_log()
        now = time.time()

        window_24h = now - 86400
        window_30d = now - (30 * 86400)

        interval = max(TIER_SLOW_INTERVAL, 1)
        gap_threshold = interval * 2.5  # gaps larger than this = toolkit was stopped

        def _active_slots(ping_list, window_start):
            """Count expected poll slots in window, excluding restart/stop gaps."""
            in_window = sorted(t for t in ping_list if t >= window_start)
            if not in_window:
                return 0
            slots = 1  # first ping counts as one slot
            prev = in_window[0]
            for t in in_window[1:]:
                gap = t - prev
                if gap <= gap_threshold:
                    slots += max(1, round(gap / interval))
                # else: toolkit was stopped — exclude gap from denominator
                prev = t
            # Add slots from last ping to now if tool is still running
            tail = now - in_window[-1]
            if tail <= gap_threshold:
                slots += max(0, round(tail / interval))
            return max(slots, len(in_window))  # never less than actual ping count

        pings_24h = sum(1 for t in pings if t >= window_24h)
        pings_30d = sum(1 for t in pings if t >= window_30d)

        # 24h: use standard time-based denominator (short window, low restart risk)
        max_24h = max(1, int(86400 / interval))

        tracking_since = None
        tracking_days  = 0
        max_30d        = max(1, int(30 * 86400 / interval))

        if pings:
            oldest = min(pings)
            tracking_since = datetime.fromtimestamp(oldest).isoformat(timespec='seconds')
            tracking_days  = min(30, int((now - oldest) / 86400))
            # 30d: use restart-aware active-slot count as denominator
            max_30d = max(1, _active_slots(pings, window_30d))

        # Minimum tracking requirement before showing percentages:
        # 24h: need at least 3 pings (30 min of data)
        # 30d: need at least 1 full day of tracking
        min_pings_24h = 3
        min_days_30d  = 1

        uptime_24h = min(100.0, round(pings_24h / max_24h * 100, 1)) if pings_24h >= min_pings_24h else 0.0
        uptime_30d = min(100.0, round(pings_30d / max_30d * 100, 1)) if tracking_days >= min_days_30d else 0.0

        return {
            'uptime_24h': uptime_24h,
            'uptime_30d': uptime_30d,
            'total_pings': len(pings),
            'tracking_since': tracking_since,
            'tracking_days':  tracking_days,   # actual days of data, 0-30
        }

    @staticmethod
    def get_node_quality(wallet_address: str) -> dict:
        """Fetch node quality metrics from Mysterium's public Discovery API.

        Endpoint:
          https://discovery.mysterium.network/api/v3/proposals
            ?provider_id=<identity>
            &include_monitoring_failed=true

        Discovery returns a list of proposals (one per service_type offered by
        the provider).  Each entry has a 'quality' sub-object:

          {
            "provider_id": "0x...",
            "service_type": "wireguard",
            "monitoring_failed": false,
            "quality": {
              "quality":   2.4,    // 0–3 composite score
              "latency":  45.2,    // ms (round-trip, 0 = no data yet)
              "bandwidth": 88.5,   // MB/s measured by monitoring agent
              "uptime":   0.98     // fraction 0–1 (24 h window)
            }
          }

        We aggregate across all proposals to build a summary.  If multiple
        service types are returned (e.g. dvpn + wireguard), we keep all of
        them individually and also surface the best quality score.

        Returns an empty/default dict on any error so callers never crash.
        """
        empty = {
            'available': False,
            'quality_score': None,
            'latency_ms': None,
            'bandwidth_mbps': None,
            'uptime_24h_net': None,   # Mysterium-reported 24 h uptime (0-100)
            'packet_loss_net': None,  # Mysterium monitoring agent packet loss (%)
            'monitoring_failed': None,
            'services': [],
            'error': None,
        }

        if not wallet_address:
            empty['error'] = 'No identity address available'
            return empty

        url = (
            'https://discovery.mysterium.network/api/v3/proposals'
            f'?provider_id={wallet_address}&include_monitoring_failed=true'
        )

        try:
            resp = requests.get(url, timeout=8)
            if resp.status_code != 200:
                empty['error'] = f'Discovery API HTTP {resp.status_code}'
                return empty

            proposals = resp.json()
            if not proposals:
                empty['error'] = 'Node not found in Discovery (not yet registered or offline)'
                return empty

            services = []
            best_quality = None
            best_latency = None
            best_bandwidth = None       # wireguard-specific (matches mystnodes.com display)
            wg_bw_found = False         # True once a wireguard bandwidth reading is recorded
            best_uptime = None          # wireguard-specific uptime (matches mystnodes.com display)
            wg_uptime_found = False     # True once a wireguard uptime reading is recorded
            best_packet_loss = None     # wireguard-specific packet loss from monitoring agent
            wg_pl_found = False
            any_monitoring_failed = False

            for p in proposals:
                svc_type = p.get('service_type', 'unknown').lower()
                q = p.get('quality') or {}
                score = q.get('quality')       # float 0–3
                latency = q.get('latency')     # ms
                bw = q.get('bandwidth')        # Mbit/s (measured by Discovery monitoring agent)
                uptime_frac = q.get('uptime')  # hours (0–24) in the Discovery v3 API
                packet_loss = q.get('packetLoss')  # % packet loss measured by monitoring agent

                # Normalize to percentage (0–100).
                # Discovery returns uptime as hours in the 24 h window (0–24),
                # NOT as a 0–1 fraction as the quality-formula docs suggest.
                # Dividing by 24 converts to fraction, then ×100 for percent.
                # Guard: if value is already ≤1 treat as fraction (future-proof).
                uptime_pct = None
                if uptime_frac is not None:
                    if uptime_frac > 1:
                        uptime_pct = min(100.0, round(uptime_frac / 24.0 * 100, 1))
                    else:
                        uptime_pct = min(100.0, round(uptime_frac * 100, 1))
                mon_fail = p.get('monitoring_failed', False)

                svc_entry = {
                    'service_type':       p.get('service_type', 'unknown'),
                    'monitoring_failed':  mon_fail,
                    'quality_score':      round(score, 3) if score is not None else None,
                    'latency_ms':         round(latency, 1) if latency is not None else None,
                    'bandwidth_mbps':     round(bw, 1) if bw is not None else None,
                    'uptime_net_pct':     uptime_pct,
                    'packet_loss_pct':    round(packet_loss, 2) if packet_loss is not None else None,
                }
                # Exclude noop and monitoring from displayed services list
                # They are internal Mysterium services not relevant to earnings
                if svc_type not in ('noop', 'monitoring'):
                    services.append(svc_entry)

                if mon_fail:
                    any_monitoring_failed = True

                if score is not None and (best_quality is None or score > best_quality):
                    best_quality = score
                if latency is not None and latency > 0 and (best_latency is None or latency < best_latency):
                    best_latency = latency

                # Bandwidth: prefer wireguard proposal to match mystnodes.com display.
                # Taking the max across all service types inflates this figure because
                # data-scraping/dvpn proposals may reflect fast datacenter clients
                # rather than the actual line speed of the node.
                # Strategy: lock onto wireguard bandwidth on first wireguard proposal seen;
                # only fall back to other service types if no wireguard proposal exists.
                if bw is not None:
                    if svc_type == 'wireguard':
                        # Wireguard wins. If multiple wireguard entries exist, take highest.
                        if not wg_bw_found or bw > best_bandwidth:
                            best_bandwidth = bw
                            wg_bw_found = True
                    elif not wg_bw_found and best_bandwidth is None:
                        # Non-wireguard fallback: only if no wireguard proposal seen yet
                        best_bandwidth = bw

                # Uptime: prefer wireguard proposal to match mystnodes.com display.
                # Averaging all service types inflates the figure — data-scraping
                # and dvpn proposals may show 100% even when wireguard is degraded.
                # Strategy mirrors bandwidth: lock onto wireguard on first WG proposal;
                # fall back to other types only if no wireguard proposal exists.
                if uptime_pct is not None:
                    if svc_type == 'wireguard':
                        if not wg_uptime_found or uptime_pct > best_uptime:
                            best_uptime = uptime_pct
                            wg_uptime_found = True
                    elif not wg_uptime_found and best_uptime is None:
                        best_uptime = uptime_pct

                # Packet loss: prefer wireguard (same strategy as bandwidth and uptime)
                if packet_loss is not None:
                    if svc_type == 'wireguard':
                        if not wg_pl_found:
                            best_packet_loss = packet_loss
                            wg_pl_found = True
                    elif not wg_pl_found and best_packet_loss is None:
                        best_packet_loss = packet_loss

            return {
                'available': True,
                'quality_score':     round(best_quality, 2) if best_quality is not None else None,
                'latency_ms':        round(best_latency, 1) if best_latency is not None else None,
                'bandwidth_mbps':    round(best_bandwidth, 1) if best_bandwidth is not None else None,
                'uptime_24h_net':    round(best_uptime, 1) if best_uptime is not None else None,
                'packet_loss_net':   round(best_packet_loss, 2) if best_packet_loss is not None else None,
                'monitoring_failed': any_monitoring_failed,
                'services':          services,
                'error':             None,
            }

        except requests.exceptions.Timeout:
            empty['error'] = 'Discovery API timeout'
            return empty
        except Exception as e:
            empty['error'] = str(e)
            logger.debug(f"Discovery API error: {e}")
            return empty

    @staticmethod
    def _get_vnstat_traffic():
        """Get traffic data from vnstat — properly separated by interface type.

        CRITICAL: vnstat rx/tx on VPN tunnel interfaces (myst/wg/tun):
          - rx = bytes received by interface = packets written to TUN by wireguard-go
                = consumer requests entering the tunnel (SMALL)
          - tx = bytes transmitted by interface = packets kernel routes to TUN
                = content responses going back through tunnel to consumer (BIG)

        This matches psutil bytes_recv/bytes_sent on the same interfaces.

        Returns dict with separated nic/vpn data, or None if unavailable.
        """
        try:
            result = subprocess.run(
                ['vnstat', '--json'],
                capture_output=True, timeout=5, text=True
            )
            if result.returncode != 0:
                return None

            data = json.loads(result.stdout)
            interfaces = data.get('interfaces', [])
            if not interfaces:
                return None

            # Detect vnstat JSON version for unit handling
            # vnstat 2.x JSON: values in bytes. vnstat 1.x: KiB (but used --dumpdb, not --json)
            json_ver = data.get('jsonversion', '2')
            # If jsonversion=1, multiply by 1024 to convert KiB→bytes
            unit_mult = 1024 if json_ver == '1' else 1

            now = local_now()
            today_str = now.strftime('%Y-%m-%d')
            this_month = now.month
            this_year = now.year

            vpn_prefixes = ('myst', 'wg', 'tun')

            # Separate accumulators for physical NIC vs VPN interfaces
            nic_today_rx = 0
            nic_today_tx = 0
            nic_month_rx = 0
            nic_month_tx = 0
            nic_name = None

            vpn_today_rx = 0
            vpn_today_tx = 0
            vpn_month_rx = 0
            vpn_month_tx = 0
            has_vpn_vnstat = False

            # Raw debug data for diagnostic endpoint
            raw_iface_data = []

            for iface in interfaces:
                iface_name = iface.get('name', '')
                is_vpn = any(iface_name.startswith(p) for p in vpn_prefixes)
                traffic = iface.get('traffic', {})

                iface_debug = {'name': iface_name, 'is_vpn': is_vpn}

                # ---- Today's traffic (validate date matches today) ----
                day_rx = 0
                day_tx = 0
                days = traffic.get('day', [])
                for day_entry in reversed(days):  # Search backwards for today
                    d = day_entry.get('date', {})
                    if (d.get('year') == this_year and d.get('month') == this_month
                            and d.get('day') == now.day):
                        day_rx = day_entry.get('rx', 0) * unit_mult
                        day_tx = day_entry.get('tx', 0) * unit_mult
                        break

                # ---- This month's traffic (validate month matches) ----
                mon_rx = 0
                mon_tx = 0
                months = traffic.get('month', [])
                for mon_entry in reversed(months):  # Search backwards for this month
                    d = mon_entry.get('date', {})
                    if d.get('year') == this_year and d.get('month') == this_month:
                        mon_rx = mon_entry.get('rx', 0) * unit_mult
                        mon_tx = mon_entry.get('tx', 0) * unit_mult
                        break

                iface_debug['today_rx'] = day_rx
                iface_debug['today_tx'] = day_tx
                iface_debug['month_rx'] = mon_rx
                iface_debug['month_tx'] = mon_tx
                raw_iface_data.append(iface_debug)

                if is_vpn:
                    vpn_today_rx += day_rx
                    vpn_today_tx += day_tx
                    vpn_month_rx += mon_rx
                    vpn_month_tx += mon_tx
                    if day_rx + day_tx + mon_rx + mon_tx > 0:
                        has_vpn_vnstat = True
                else:
                    # Physical NIC (eno1, eth0, etc.)
                    nic_today_rx += day_rx
                    nic_today_tx += day_tx
                    nic_month_rx += mon_rx
                    nic_month_tx += mon_tx
                    if nic_name is None and not iface_name.startswith(('lo', 'docker', 'br-', 'veth')):
                        nic_name = iface_name

            return {
                # Physical NIC only (eno1/eth0 — NOT including VPN interfaces)
                'nic_name': nic_name or 'eno1',
                'today_rx': nic_today_rx,
                'today_tx': nic_today_tx,
                'today_total': nic_today_rx + nic_today_tx,
                'month_rx': nic_month_rx,
                'month_tx': nic_month_tx,
                'month_total': nic_month_rx + nic_month_tx,
                # VPN-specific (myst/wg/tun interfaces)
                'vpn_today_rx': vpn_today_rx,
                'vpn_today_tx': vpn_today_tx,
                'vpn_today_total': vpn_today_rx + vpn_today_tx,
                'vpn_month_rx': vpn_month_rx,
                'vpn_month_tx': vpn_month_tx,
                'vpn_month_total': vpn_month_rx + vpn_month_tx,
                'has_vpn_vnstat': has_vpn_vnstat,
                # Raw data for diagnostics
                '_raw_interfaces': raw_iface_data,
                '_json_version': json_ver,
                '_unit_multiplier': unit_mult,
            }
        except FileNotFoundError:
            logger.debug("vnstat not installed, skipping")
            return None
        except Exception as e:
            logger.debug(f"vnstat query failed: {e}")
            return None

    @staticmethod
    def get_performance():
        """Get network performance — non-blocking.
        Ping runs in background thread.
        Node speed = VPN interface deltas (myst*).
        System speed = primary NIC deltas (total system throughput)."""
        try:
            # Launch ping in background if not already running
            if MetricsCollector._ping_thread is None:
                MetricsCollector._ping_thread = Thread(
                    target=MetricsCollector._ping_worker, daemon=True)
                MetricsCollector._ping_thread.start()

            now = time.time()

            # ---- Node speed (VPN interfaces only) ----
            vpn_rx, vpn_tx, _ = VpnTrafficSnapshot.get_snapshot()

            speed_in = 0.0
            speed_out = 0.0
            speed_total = 0.0

            if MetricsCollector._prev_vpn_rx is not None and MetricsCollector._prev_net_time is not None:
                elapsed = now - MetricsCollector._prev_net_time
                if elapsed > 0:
                    bytes_in_delta = vpn_rx - MetricsCollector._prev_vpn_rx
                    bytes_out_delta = vpn_tx - MetricsCollector._prev_vpn_tx
                    if bytes_in_delta >= 0 and bytes_out_delta >= 0:
                        speed_in = (bytes_in_delta / elapsed) / (1024 * 1024)
                        speed_out = (bytes_out_delta / elapsed) / (1024 * 1024)
                        speed_total = speed_in + speed_out

            MetricsCollector._prev_vpn_rx = vpn_rx
            MetricsCollector._prev_vpn_tx = vpn_tx
            MetricsCollector._prev_net_time = now

            # ---- System speed (primary NIC — total throughput) ----
            sys_speed_in = 0.0
            sys_speed_out = 0.0
            sys_speed_total = 0.0
            sys_nic_name = 'NIC'
            try:
                per_nic = psutil.net_io_counters(pernic=True)
                # Find primary NIC (not loopback, not VPN, has most traffic)
                best_nic = None
                best_total = 0
                for name, counters in per_nic.items():
                    if name == 'lo' or name.startswith(('myst', 'wg', 'tun', 'docker', 'veth', 'br-')):
                        continue
                    total = counters.bytes_recv + counters.bytes_sent
                    if total > best_total:
                        best_total = total
                        best_nic = name

                if best_nic:
                    sys_nic_name = best_nic
                    counters = per_nic[best_nic]
                    sys_rx = counters.bytes_recv
                    sys_tx = counters.bytes_sent

                    if MetricsCollector._prev_sys_rx is not None and MetricsCollector._prev_sys_time is not None:
                        elapsed = now - MetricsCollector._prev_sys_time
                        if elapsed > 0:
                            rx_delta = sys_rx - MetricsCollector._prev_sys_rx
                            tx_delta = sys_tx - MetricsCollector._prev_sys_tx
                            if rx_delta >= 0 and tx_delta >= 0:
                                sys_speed_in = (rx_delta / elapsed) / (1024 * 1024)
                                sys_speed_out = (tx_delta / elapsed) / (1024 * 1024)
                                sys_speed_total = sys_speed_in + sys_speed_out

                    MetricsCollector._prev_sys_rx = sys_rx
                    MetricsCollector._prev_sys_tx = sys_tx
                    MetricsCollector._prev_sys_time = now
            except Exception:
                pass

            # Determine if node is idle (has tunnels but no real traffic)
            is_idle = speed_total < 0.001 and speed_total > 0  # < 1 KB/s but some traffic

            return {
                'latency': round(MetricsCollector._cached_latency, 2),
                'packet_loss': round(MetricsCollector._cached_packet_loss, 2),
                # Node speed (VPN tunnels only)
                'speed_in': round(speed_in, 6),
                'speed_out': round(speed_out, 6),
                'speed_total': round(speed_total, 6),
                # System speed (primary NIC — includes everything)
                'sys_speed_in': round(sys_speed_in, 6),
                'sys_speed_out': round(sys_speed_out, 6),
                'sys_speed_total': round(sys_speed_total, 6),
                'sys_nic': sys_nic_name,
                'idle': is_idle,
            }
        except Exception as e:
            logger.warning(f"Error fetching performance: {e}")

        return {'latency': 0.0, 'packet_loss': 0.0, 'speed_in': 0.0, 'speed_out': 0.0,
                'speed_total': 0.0, 'sys_speed_in': 0.0, 'sys_speed_out': 0.0,
                'sys_speed_total': 0.0, 'sys_nic': 'NIC', 'idle': False}

    @staticmethod
    def get_resources():
        """Get system resources — non-blocking.
        Uses cpu_percent(interval=0) which returns delta since last call (instant)."""
        try:
            # Prime the CPU counter on first call (returns 0.0)
            if not MetricsCollector._cpu_primed:
                psutil.cpu_percent(interval=0)
                MetricsCollector._cpu_primed = True

            # CPU temperature — collect ALL useful sensor readings
            cpu_temp = None
            cpu_temp_source = ''
            all_temps = []  # List of {'label': str, 'value': float, 'sensor': str}

            # Labels to skip (exact match, lowered)
            SKIP_EXACT = {'acpitz', 'package id 0', 'pch'}
            # Prefixes to skip (individual cores are redundant when CPU is shown)
            SKIP_PREFIX = ('core ',)
            # Sensor names to skip entirely
            SKIP_SENSORS = {'acpitz'}
            # Rename map for friendlier names
            RENAME_MAP = {'sodimm': 'RAM'}

            try:
                temps = psutil.sensors_temperatures()
                if temps:
                    for sensor_name, entries in temps.items():
                        if sensor_name.lower() in SKIP_SENSORS:
                            continue
                        for entry in entries:
                            label = entry.label or sensor_name
                            lbl_lower = label.lower()

                            # Skip useless/duplicate entries
                            if lbl_lower in SKIP_EXACT:
                                continue
                            if any(lbl_lower.startswith(p) for p in SKIP_PREFIX):
                                continue

                            # Rename for clarity
                            display_label = label
                            for key, rename in RENAME_MAP.items():
                                if key in lbl_lower:
                                    display_label = rename
                                    break

                            all_temps.append({
                                'label': display_label,
                                'value': round(entry.current, 1),
                                'sensor': sensor_name,
                            })

                            # Pick best CPU temp as primary
                            if lbl_lower in ('tctl', 'cpu') or \
                               (cpu_temp is None and sensor_name in ('coretemp', 'k10temp', 'zenpower', 'cpu_thermal')):
                                cpu_temp = entry.current
                                cpu_temp_source = display_label
            except (AttributeError, OSError):
                pass

            # Fallback: sysfs thermal zones
            if cpu_temp is None:
                try:
                    for zone in sorted(Path('/sys/class/thermal/').glob('thermal_zone*')):
                        temp_file = zone / 'temp'
                        type_file = zone / 'type'
                        if temp_file.exists():
                            raw = int(temp_file.read_text().strip())
                            val = raw / 1000.0 if raw > 1000 else raw
                            try:
                                label = type_file.read_text().strip() if type_file.exists() else 'sysfs'
                            except OSError:
                                label = 'sysfs'
                            lbl_lower = label.lower()
                            if lbl_lower not in SKIP_EXACT and not any(lbl_lower.startswith(p) for p in SKIP_PREFIX):
                                all_temps.append({'label': label, 'value': round(val, 1), 'sensor': 'sysfs'})
                            if cpu_temp is None:
                                cpu_temp = val
                                cpu_temp_source = label
                except (OSError, ValueError):
                    pass

            resources_data = {
                'cpu': psutil.cpu_percent(interval=0),
                'ram': psutil.virtual_memory().percent,
                'disk': psutil.disk_usage('/').percent,
                'cpu_temp': round(cpu_temp, 1) if cpu_temp is not None else None,
                'cpu_temp_source': cpu_temp_source,
                'all_temps': all_temps,
            }
            if SystemMetricsDB:
                # Rate-limit: only write every 5 minutes (fast tier runs every ~3s)
                _now = time.time()
                if not hasattr(MetricsCollector, '_metrics_db_last') or _now - MetricsCollector._metrics_db_last >= 300:
                    try:
                        # Read performance and live_connections from the previous
                        # fast tier cycle — stored in _last_fast_data after each
                        # collect_all() run. This gives correct tunnel count, VPN
                        # speed, NIC speed and latency for the DB snapshot.
                        _perf = _last_fast_data.get('performance') or {}
                        _live = _last_fast_data.get('live_connections') or {}
                        _perf_ext = {
                            'tunnel_count':    _live.get('active'),
                            'speed_total':     _perf.get('speed_total'),
                            'sys_speed_total': _perf.get('sys_speed_total'),
                            'latency_ms':      _perf.get('latency_ms'),
                        }
                        SystemMetricsDB.record(resources_data, node_id=_local_node_id,
                                               performance_data=_perf_ext)
                        MetricsCollector._metrics_db_last = _now
                    except Exception as e:
                        logger.debug(f"SystemMetricsDB record failed: {e}")
            return resources_data
        except Exception as e:
            logger.warning(f"Error fetching resources: {e}")

        return {'cpu': 0.0, 'ram': 0.0, 'disk': 0.0, 'cpu_temp': None, 'cpu_temp_source': '', 'all_temps': []}

    @staticmethod
    def get_firewall():
        """Get firewall status with actual rule details.
        Detects active firewall type: firewalld, ufw, nftables, iptables."""
        rules_list = []
        blocked_count = 0
        fw_status = 'unknown'
        fw_type = 'unknown'

        # ── Detect active firewall type ──────────────────────────────────
        try:
            # firewalld
            r = subprocess.run(['systemctl', 'is-active', 'firewalld'],
                               capture_output=True, timeout=3, text=True)
            if r.returncode == 0 and r.stdout.strip() == 'active':
                fw_type = 'firewalld'
        except Exception:
            pass

        if fw_type == 'unknown':
            try:
                r = subprocess.run(['ufw', 'status'], capture_output=True, timeout=3, text=True)
                if r.returncode == 0 and ('active' in r.stdout.lower() or 'inactive' in r.stdout.lower()):
                    fw_type = 'ufw'
            except Exception:
                pass

        if fw_type == 'unknown':
            try:
                r = subprocess.run(['nft', 'list', 'ruleset'], capture_output=True, timeout=3, text=True)
                if r.returncode == 0 and r.stdout.strip():
                    fw_type = 'nftables'
            except Exception:
                pass

        if fw_type == 'unknown':
            try:
                r = subprocess.run(['iptables', '--version'], capture_output=True, timeout=3, text=True)
                if r.returncode == 0:
                    fw_type = 'iptables-nft' if 'nf_tables' in r.stdout else 'iptables-legacy'
            except Exception:
                pass

        # Detect correct binary: prefer whichever has actual rules
        iptables_binaries = []
        try:
            result = subprocess.run(['iptables', '--version'], capture_output=True, timeout=3, text=True)
            if result.returncode == 0 and 'legacy' in result.stdout:
                iptables_binaries = ['iptables']
            elif result.returncode == 0 and 'nf_tables' in result.stdout:
                iptables_binaries = ['iptables-legacy', 'iptables']
            else:
                iptables_binaries = ['iptables']
        except Exception:
            iptables_binaries = ['iptables']

        # Try each binary with sudo fallback, without --line-numbers for nftables compat
        found_rules = False
        for iptables_bin in iptables_binaries:
            if found_rules:
                break
            for cmd in [
                ['sudo', '-n', iptables_bin, '-w', '5', '-L', '-n', '-v'],
                [iptables_bin, '-w', '5', '-L', '-n', '-v'],
                ['sudo', '-n', iptables_bin, '-L', '-n', '-v'],
                [iptables_bin, '-L', '-n', '-v'],
                ['sudo', '-n', iptables_bin, '-L', '-n'],
                [iptables_bin, '-L', '-n'],
            ]:
                try:
                    result = subprocess.run(cmd, capture_output=True, timeout=5, text=True)
                    if result.returncode == 0 and result.stdout.strip():
                        fw_status = 'active'
                        current_chain = ''
                        for line in result.stdout.split('\n'):
                            stripped = line.strip()
                            if not stripped:
                                continue
                            # Skip legacy warning line
                            if stripped.startswith('#'):
                                continue
                            if stripped.startswith('Chain'):
                                parts = stripped.split()
                                current_chain = parts[1] if len(parts) > 1 else ''
                                continue
                            # Skip column header line
                            if stripped.startswith('num') or stripped.startswith('pkts'):
                                continue
                            # Parse actual rule
                            # With -v: pkts bytes target prot opt in out source destination [extra]
                            # Without -v: target prot opt source destination [extra]
                            parts = stripped.split()
                            if len(parts) >= 9:
                                # -v format (has pkts + bytes columns)
                                action = parts[2]
                                proto = parts[3]
                                source = parts[7]
                                dest = parts[8]
                                extra = ' '.join(parts[9:]) if len(parts) > 9 else ''
                            elif len(parts) >= 5:
                                # non-verbose format
                                action = parts[0]
                                proto = parts[1]
                                source = parts[3]
                                dest = parts[4]
                                extra = ' '.join(parts[5:]) if len(parts) > 5 else ''
                            else:
                                continue

                            is_blocked = action in ('DROP', 'REJECT')
                            if is_blocked:
                                blocked_count += 1

                            rules_list.append({
                                'chain': current_chain,
                                'action': action,
                                'protocol': proto,
                                'source': source,
                                'destination': dest,
                                'extra': extra,
                                'blocked': is_blocked,
                            })
                        found_rules = True
                        break  # Got results from this binary
                except (FileNotFoundError, OSError):
                    continue
                except Exception as e:
                    logger.warning(f"iptables error with {cmd[0]}: {e}")
                    continue

        # Also check ufw if available
        ufw_rules = []
        try:
            result = subprocess.run(
                ['sudo', '-n', 'ufw', 'status', 'verbose'],
                capture_output=True, timeout=5, text=True
            )
            if result.returncode != 0:
                result = subprocess.run(
                    ['ufw', 'status', 'verbose'],
                    capture_output=True, timeout=5, text=True
                )
            if result.returncode == 0:
                in_rules = False
                for line in result.stdout.split('\n'):
                    stripped = line.strip()
                    if stripped.startswith('Status:'):
                        if 'active' in stripped.lower():
                            fw_status = 'active'
                        elif 'inactive' in stripped.lower():
                            fw_status = fw_status or 'inactive'
                    if stripped.startswith('--'):
                        in_rules = True
                        continue
                    if in_rules and stripped:
                        ufw_rules.append(stripped)
        except (FileNotFoundError, OSError):
            pass

        # nft fallback — Debian 12/13 uses nftables, iptables may show nothing
        if fw_status != 'active' or not rules_list:
            try:
                for nft_cmd in [['sudo', '-n', 'nft', 'list', 'ruleset'], ['nft', 'list', 'ruleset']]:
                    nft_r = subprocess.run(nft_cmd, capture_output=True, timeout=5, text=True)
                    if nft_r.returncode == 0 and nft_r.stdout.strip():
                        fw_status = 'active'
                        for line in nft_r.stdout.split('\n'):
                            s = line.strip()
                            # Skip empty, comments, chain declarations and table declarations
                            if not s or s.startswith('#'):
                                continue
                            # Skip chain/table structure lines — not actual rules
                            if s.startswith('table ') or s.startswith('chain ') or s == '{' or s == '}':
                                continue
                            # Skip lines that are only chain jump references (e.g. "jump ufw-reject-input")
                            if s.startswith('type ') or s.startswith('hook ') or s.startswith('policy '):
                                # These are chain policy lines — count as rules but not blocked
                                continue
                            # Only count real action lines with counter
                            if 'counter' not in s:
                                continue
                            # Skip jump rules - they redirect to other chains, not real actions
                            if ' jump ' in s:
                                continue
                            if any(kw in s for kw in ('accept', 'drop', 'reject', 'masquerade')):
                                action = ('DROP' if ' drop' in s else
                                          'REJECT' if ' reject' in s else
                                          'MASQUERADE' if 'masquerade' in s else 'ACCEPT')
                                # ct state invalid drop is a normal system rule, not a user block
                                is_system_rule = 'ct state invalid' in s
                                is_blocked = action in ('DROP', 'REJECT') and not is_system_rule
                                if is_blocked:
                                    blocked_count += 1
                                rules_list.append({
                                    'chain': 'nft',
                                    'action': action,
                                    'protocol': 'all',
                                    'source': '0.0.0.0/0',
                                    'destination': '0.0.0.0/0',
                                    'extra': s[:80],
                                    'blocked': is_blocked,
                                })
                        break
            except Exception:
                pass

        return {
            'status': fw_status,
            'fw_type': fw_type,
            'rules': len(rules_list),
            'blocked': blocked_count,
            'rule_details': rules_list[:100],
            'ufw_rules': ufw_rules[:50],
        }

    @staticmethod
    def get_logs(limit=50):
        """Get toolkit logs from backend.log — only toolkit entries, no system noise."""
        logs = []
        try:
            log_file = Path('logs/backend.log')
            if not log_file.exists():
                return []

            # Read last N lines efficiently without loading entire file
            with open(log_file, 'rb') as f:
                # Seek to end and read backwards to find last `limit` lines
                f.seek(0, 2)
                file_size = f.tell()
                chunk_size = min(32768, file_size)
                buffer = b''
                pos = file_size
                lines = []

                while pos > 0 and len(lines) < limit + 1:
                    read_size = min(chunk_size, pos)
                    pos -= read_size
                    f.seek(pos)
                    chunk = f.read(read_size)
                    buffer = chunk + buffer
                    lines = buffer.split(b'\n')

            # Take last `limit` non-empty lines
            raw_lines = [l.decode('utf-8', errors='replace') for l in lines if l.strip()][-limit:]

            for line in reversed(raw_lines):
                # Parse standard Python logging format:
                # "2026-04-08 12:34:56,789 INFO module:line message"
                # or Flask/werkzeug: "192.168.1.1 - - [08/Apr/2026 12:34:56] ..."
                timestamp = ''
                message = line
                level = 'INFO'

                # Try: "YYYY-MM-DD HH:MM:SS,mmm LEVEL ..."
                import re as _re
                m = _re.match(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})[,.]?\d*\s+(DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+(.*)', line)
                if m:
                    timestamp = m.group(1)
                    level = m.group(2)
                    message = m.group(3)
                else:
                    # Try werkzeug: "[08/Apr/2026 12:34:56] ..."
                    m2 = _re.match(r'.*\[(\d{2}/\w+/\d{4} \d{2}:\d{2}:\d{2})\]\s*(.*)', line)
                    if m2:
                        timestamp = m2.group(1)
                        message = m2.group(2)

                # Skip very verbose debug lines
                if level == 'DEBUG':
                    continue

                logs.append({
                    'timestamp': timestamp,
                    'message':   message,
                    'level':     level,
                })

            return logs
        except Exception as e:
            logger.warning(f"Error reading backend.log: {e}")
            return []

        return []

    # Per-interface traffic history for speed calculation
    _prev_iface_stats = {}   # {iface_name: {'rx': bytes, 'tx': bytes, 'time': timestamp}}

    @staticmethod
    def get_live_connections():
        """Get REAL-TIME active connections from VPN interfaces + services.

        Each myst*/wg*/tun* network interface IS a live consumer tunnel.
        Mysterium uses wireguard-go (userspace) so `wg show` can't see them.
        Instead we read per-interface traffic from psutil — this is ground truth.

        NOTE on in/out perspective for PROVIDER dashboard:
        - Consumer downloads content → data flows OUT of node → node tx_bytes
        - Consumer uploads/requests → data flows IN to node → node rx_bytes
        We label from the CONSUMER perspective (what they're doing through our node):
        - "download" = node tx_bytes (we send to consumer)
        - "upload"   = node rx_bytes (we receive from consumer)
        """
        live = []
        now = time.time()

        try:
            per_nic = psutil.net_io_counters(pernic=True)
            vpn_ifaces = {name: counters for name, counters in per_nic.items()
                          if any(name.startswith(p) for p in MetricsCollector.VPN_IFACE_PREFIXES)}

            for iface_name, counters in sorted(vpn_ifaces.items()):
                rx = counters.bytes_recv    # From consumer (their uploads/requests)
                tx = counters.bytes_sent    # To consumer (their downloads/content)
                total = rx + tx

                # Calculate per-interface speed (delta since last sample)
                speed_down = 0.0  # Consumer download speed (our tx delta)
                speed_up = 0.0    # Consumer upload speed (our rx delta)
                prev = MetricsCollector._prev_iface_stats.get(iface_name)
                if prev:
                    elapsed = now - prev['time']
                    if elapsed > 0:
                        tx_delta = tx - prev['tx']
                        rx_delta = rx - prev['rx']
                        if tx_delta >= 0:
                            speed_down = (tx_delta / elapsed) / (1024 * 1024)  # MB/s
                        if rx_delta >= 0:
                            speed_up = (rx_delta / elapsed) / (1024 * 1024)

                # Update history
                MetricsCollector._prev_iface_stats[iface_name] = {
                    'rx': rx, 'tx': tx, 'time': now
                }

                # Consider active if any traffic at all (interface exists = tunnel is up)
                is_active = total > 0
                has_speed = (speed_down + speed_up) > 0.0001  # > 0.1 KB/s

                # Try to get interface uptime from /sys
                duration = '—'
                try:
                    carrier_path = Path(f'/sys/class/net/{iface_name}/carrier')
                    if carrier_path.exists():
                        # Use file creation time as proxy for interface age
                        stat = Path(f'/sys/class/net/{iface_name}').stat()
                        age = now - stat.st_ctime
                        h = int(age // 3600)
                        m = int((age % 3600) // 60)
                        duration = f"{h}h {m}m" if h > 0 else f"{m}m"
                except Exception:
                    pass

                live.append({
                    'interface': iface_name,
                    'is_active': is_active,
                    'has_speed': has_speed,
                    # Consumer perspective: download = our tx, upload = our rx
                    'download_mb': round(tx / (1024 * 1024), 2),
                    'upload_mb': round(rx / (1024 * 1024), 2),
                    'total_mb': round(total / (1024 * 1024), 2),
                    'speed_down': round(speed_down, 4),  # Consumer download MB/s
                    'speed_up': round(speed_up, 4),       # Consumer upload MB/s
                    'speed_total': round(speed_down + speed_up, 4),
                    'duration': duration,
                    # Raw bytes for advanced use
                    'rx_bytes': rx,
                    'tx_bytes': tx,
                })
        except Exception as e:
            logger.warning(f"Error reading VPN interfaces: {e}")

        # Clean stale interfaces from speed history
        current_ifaces = {c['interface'] for c in live}
        stale = [k for k in MetricsCollector._prev_iface_stats if k not in current_ifaces]
        for k in stale:
            del MetricsCollector._prev_iface_stats[k]

        # Service connection count — use tunnel count as ground truth
        # (TequilAPI connection_count is often 0 even with active tunnels)
        api_svc_connections = 0
        for svc in TequilaCache.get_all_services():
            api_svc_connections += int(svc.get('connection_count',
                                           svc.get('connections_count', 0)))

        # Sort: active with speed first, then by total traffic desc
        live.sort(key=lambda p: (not p['has_speed'], not p['is_active'], -p['total_mb']))
        active_count = sum(1 for p in live if p['is_active'])
        with_speed = sum(1 for p in live if p['has_speed'])

        return {
            'peers': live,
            'active': active_count,
            'transferring': with_speed,
            'total': len(live),
            'svc_connections': max(api_svc_connections, active_count),
        }

    @staticmethod
    def collect_all():
        """Collect metrics using tiered caching to minimize TequilAPI load.

        FAST  (every cycle ~10s): performance, live_connections, resources — psutil only, 0 HTTP calls
        MEDIUM (every 60s): bandwidth, services, sessions, clients — 3 HTTP calls via TequilaCache
        SLOW  (every 5min): earnings, node_status — 3 HTTP calls (identity/healthcheck)

        Old system: 17 HTTP requests every 5 seconds = 204/min = 12,240/hour
        New system: ~4 HTTP requests every 60 seconds = 4/min = 240/hour (98% reduction)
        """
        global last_update_time, _tier_medium_cache, _tier_medium_last
        global _tier_slow_cache, _tier_slow_last
        now = time.time()
        last_update_time = now

        # ---- FAST TIER (every cycle) — psutil only ----
        fast = {
            'performance': MetricsCollector.get_performance(),
            'live_connections': MetricsCollector.get_live_connections(),
            'resources': MetricsCollector.get_resources(),
        }

        # Store fast tier snapshot so get_resources() DB write can read
        # performance and live_connections from the same cycle.
        global _last_fast_data
        _last_fast_data = fast

        # ---- MEDIUM TIER (every 60s) — TequilaCache refresh ----
        if now - _tier_medium_last >= TIER_MEDIUM_INTERVAL or not _tier_medium_cache:
            try:
                # Auto-register any new myst* interfaces with vnstat
                MetricsCollector._ensure_vnstat_interfaces()

                headers = MetricsCollector.get_tequilapi_headers()
                TequilaCache.refresh(headers)  # 2 HTTP calls per node: /services, /sessions
                _tier_medium_cache = {
                    'bandwidth': MetricsCollector.get_bandwidth(),
                    'services': MetricsCollector.get_services(),
                    'sessions': MetricsCollector.get_sessions(),
                    'clients': MetricsCollector.get_clients(),
                    'firewall': MetricsCollector._get_firewall_cached(),
                }
                _tier_medium_last = now
                logger.debug("Medium tier refreshed (TequilaCache)")
            except Exception as e:
                logger.warning(f"Medium tier error: {e}")

        # ---- SLOW TIER (every 5min) — blockchain/identity ----
        if now - _tier_slow_last >= TIER_SLOW_INTERVAL or not _tier_slow_cache:
            try:
                node_status_data = MetricsCollector.get_node_status()
                earnings_data    = MetricsCollector.get_earnings()

                # Record online ping for uptime tracking if node is reachable
                identity = node_status_data.get('identity', '') or earnings_data.get('wallet_address', '')
                global _local_node_id
                if identity:
                    _local_node_id = identity
                if node_status_data.get('status') == 'online':
                    MetricsCollector.record_uptime_ping(identity=identity)

                # Fetch quality from Discovery API (external, public — no auth)
                # Use identity from node status (most reliable) or fall back to earnings wallet
                wallet = identity or earnings_data.get('wallet_address', '')
                global _discovery_cache, _discovery_last, _discovery_wallet
                # Reset cache if wallet changed (node identity changed)
                if wallet and wallet != _discovery_wallet:
                    _discovery_cache = {}
                    _discovery_last = 0
                    _discovery_wallet = wallet
                if now - _discovery_last >= TIER_DISCOVERY_INTERVAL or not _discovery_cache:
                    quality_data  = MetricsCollector.get_node_quality(wallet)
                    uptime_stats  = MetricsCollector.compute_uptime_stats()
                    quality_data['uptime_24h_local'] = uptime_stats['uptime_24h']
                    quality_data['uptime_30d_local'] = uptime_stats['uptime_30d']
                    quality_data['tracking_since']   = uptime_stats['tracking_since']
                    quality_data['tracking_days']    = uptime_stats['tracking_days']
                    _discovery_cache = quality_data
                    _discovery_last  = now

                    if QualityDB and quality_data.get('available'):
                        try:
                            nat_type = node_status_data.get('nat_type', '') if node_status_data else ''
                            QualityDB.record(quality_data, node_id=identity, wallet_address=wallet, nat_type=nat_type)
                        except Exception as e:
                            logger.debug(f"QualityDB record failed: {e}")

                    # Periodic country backfill — use ALL sessions in SessionStore, not just page 1
                    # This catches countries from sessions that were on later pages
                    try:
                        all_known = TequilaCache.get_all_sessions() if hasattr(TequilaCache, 'get_all_sessions') else []
                        # Also include from SessionStore directly
                        for node_url in NODE_API_URLS:
                            store_sessions = list(SessionStore._sessions.values()) if hasattr(SessionStore, '_sessions') else []
                            all_with_country = [s for s in store_sessions if s.get('consumer_country') and s.get('id')]
                            if all_with_country:
                                updated = SessionDB.backfill_countries(all_with_country)
                                if updated:
                                    logger.info(f"Slow tier country backfill: {updated} rows updated")
                    except Exception as _bf_e:
                        logger.debug(f"Periodic country backfill: {_bf_e}")

                # Build earnings chart data for CLI (lightweight — just reads from cache)
                try:
                    EarningsDeltaTracker._load()
                    snaps = EarningsDeltaTracker._snapshots
                    from datetime import date as _date
                    today_str = local_today()
                    cutoff_90 = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
                    daily_map_cli = {}
                    for s in snaps:
                        if s.get('time', '') < cutoff_90:
                            continue
                        # Use TOOLKIT_TZ for date bucketing (same as /earnings/chart endpoint)
                        try:
                            _t = datetime.fromisoformat(str(s['time']).replace('Z', '+00:00'))
                            if _t.tzinfo is None:
                                _t = _t.replace(tzinfo=timezone.utc)
                            day = _t.astimezone(TOOLKIT_TZ).strftime('%Y-%m-%d')
                        except Exception:
                            day = s.get('time', '')[:10]
                        lt  = float(s.get('lifetime', 0) or 0)
                        if day not in daily_map_cli:
                            daily_map_cli[day] = {'first': lt, 'last': lt, 'date': day}
                        else:
                            daily_map_cli[day]['last'] = lt
                    dlist = sorted(daily_map_cli.values(), key=lambda x: x['date'])
                    daily_cli = []
                    MAX_J = 20.0
                    for i, d in enumerate(dlist):
                        earned = 0.0
                        if i > 0:
                            prev = dlist[i-1]['last']
                            delta = d['last'] - prev
                            if 0 < delta <= MAX_J:
                                earned = round(delta, 4)
                        daily_cli.append({'date': d['date'], 'earned': earned})
                    earnings_chart_data = {'daily': daily_cli[-30:]}
                except Exception:
                    earnings_chart_data = {'daily': []}

                # ── TrafficDB: import vnstat history + record today's snapshot ──
                try:
                    raw_vnstat = MetricsCollector._get_vnstat_traffic()
                    if raw_vnstat:
                        # One-time import of all historical vnstat month data
                        global _traffic_history_imported
                        if not _traffic_history_imported:
                            vnstat_raw_json = None
                            try:
                                import subprocess as _sp
                                r = _sp.run(['vnstat', '--json'], capture_output=True, timeout=5, text=True)
                                if r.returncode == 0:
                                    vnstat_raw_json = json.loads(r.stdout)
                            except Exception:
                                pass
                            if vnstat_raw_json:
                                TrafficDB.import_vnstat_history(vnstat_raw_json)
                            _traffic_history_imported = True

                        # Record today's VPN + NIC snapshot (MB)
                        MB = 1024 * 1024
                        today_str = local_today()

                        vpn_rx_bytes = raw_vnstat.get('vpn_today_rx', 0)
                        vpn_tx_bytes = raw_vnstat.get('vpn_today_tx', 0)

                        # Fallback: if vnstat doesn't track myst* interfaces,
                        # use psutil with a midnight-reset daily baseline so
                        # "today" = current counters - baseline (not cumulative).
                        if vpn_rx_bytes == 0 and vpn_tx_bytes == 0:
                            try:
                                cur_rx, cur_tx, _ = VpnTrafficSnapshot.get_snapshot()
                                with _vpn_day_baseline_lock:
                                    if _vpn_day_baseline['date'] != today_str:
                                        # New calendar day — reset baseline
                                        _vpn_day_baseline['date'] = today_str
                                        _vpn_day_baseline['rx']   = cur_rx
                                        _vpn_day_baseline['tx']   = cur_tx
                                    base_rx = _vpn_day_baseline['rx']
                                    base_tx = _vpn_day_baseline['tx']
                                vpn_rx_bytes = max(0, cur_rx - base_rx)
                                vpn_tx_bytes = max(0, cur_tx - base_tx)
                                _psutil_vpn_source = True
                            except Exception:
                                _psutil_vpn_source = False
                        else:
                            _psutil_vpn_source = False

                        TrafficDB.upsert_day(
                            today_str,
                            vpn_rx_mb = vpn_rx_bytes / MB,
                            vpn_tx_mb = vpn_tx_bytes / MB,
                            nic_rx_mb = raw_vnstat.get('today_rx', 0) / MB,
                            nic_tx_mb = raw_vnstat.get('today_tx', 0) / MB,
                            source    = 'vnstat_daily',
                        )
                        if _psutil_vpn_source:
                            logger.debug(f"TrafficDB: VPN bytes from psutil baseline (vnstat has no myst* data)")
                except Exception as _tdb_e:
                    logger.debug(f"TrafficDB snapshot error: {_tdb_e}")

                _tier_slow_cache = {
                    'nodeStatus':     node_status_data,
                    'earnings':       earnings_data,
                    'systemHealth':   MetricsCollector._get_health_cached(),
                    'runtimeEnv':     RUNTIME_ENV,
                    'nodeQuality':    _discovery_cache,
                    'earnings_chart': earnings_chart_data,
                }
                _tier_slow_last = now

                # Daily retention prune — runs once per calendar day
                # Keeps databases within configured retention windows silently
                try:
                    _prune_old_data()
                except Exception as _prune_e:
                    logger.debug(f"Retention prune skipped: {_prune_e}")

                # Dynamic CPU governor + conntrack — adjust based on active sessions
                # Runs after cache is built so we have the latest session count
                try:
                    if system_health:
                        _active = fast.get('live_connections', {}).get('active', 0) or 0
                        _tunnels = fast.get('live_connections', {}).get('peers', [])
                        _tunnel_count = len(_tunnels) if isinstance(_tunnels, list) else int(_active)
                        system_health.CpuGovernorHealth.adjust_for_sessions(int(_active))
                        system_health.ConntrackHealth.fix(tunnel_count=int(_tunnel_count))
                except Exception as _gov_e:
                    logger.debug(f'Governor/conntrack adjust error: {_gov_e}')

                logger.debug("Slow tier refreshed (earnings/health/quality)")
            except Exception as e:
                logger.warning(f"Slow tier error: {e}")

        # Merge all tiers
        result = {'timestamp': datetime.now().isoformat()}
        result.update(fast)
        result.update(_tier_medium_cache)
        result.update(_tier_slow_cache)
        # Ensure nodeQuality always present with safe defaults
        if 'nodeQuality' not in result:
            result['nodeQuality'] = {
                'available': False, 'quality_score': None, 'latency_ms': None,
                'bandwidth_mbps': None, 'uptime_24h_net': None,
                'uptime_24h_local': None, 'uptime_30d_local': None,
                'tracking_since': None, 'tracking_days': 0,
                'monitoring_failed': None,
                'packet_loss_net': None,
                'services': [], 'error': 'Not yet fetched',
            }
        result['logs'] = MetricsCollector._get_logs_cached()
        result['nodeConnected'] = node_status['connected']
        return result

    # Health scan cache — runs every 5 minutes, not every collection cycle
    _health_cache = {'overall': 'unknown', 'subsystems': []}
    _health_last_scan = 0
    HEALTH_SCAN_INTERVAL = 300  # 5 minutes

    @staticmethod
    def _get_health_cached():
        now = time.time()
        if system_health and (now - MetricsCollector._health_last_scan > MetricsCollector.HEALTH_SCAN_INTERVAL):
            try:
                MetricsCollector._health_cache = system_health.scan_all()
                MetricsCollector._health_last_scan = now
            except Exception as e:
                logger.warning(f"Health scan error: {e}")
        return MetricsCollector._health_cache

    # Cached firewall — iptables/nft every 5 min, not every 5 seconds
    _firewall_cache = None
    _firewall_last_scan = 0
    FIREWALL_SCAN_INTERVAL = 60  # 1 minute — moved to medium tier

    @staticmethod
    def _get_firewall_cached():
        now = time.time()
        if (MetricsCollector._firewall_cache is None or
                now - MetricsCollector._firewall_last_scan >= MetricsCollector.FIREWALL_SCAN_INTERVAL):
            MetricsCollector._firewall_cache = MetricsCollector.get_firewall()
            MetricsCollector._firewall_last_scan = now
        return MetricsCollector._firewall_cache

    # Cached logs — journalctl every 60s
    _logs_cache = []
    _logs_last_scan = 0
    LOGS_SCAN_INTERVAL = 60

    @staticmethod
    def _get_logs_cached():
        now = time.time()
        if (not MetricsCollector._logs_cache or
                now - MetricsCollector._logs_last_scan >= MetricsCollector.LOGS_SCAN_INTERVAL):
            MetricsCollector._logs_cache = MetricsCollector.get_logs()
            MetricsCollector._logs_last_scan = now
        return MetricsCollector._logs_cache


# ============ BACKGROUND COLLECTION ============

# Per-node metrics for multi-node mode
_per_node_metrics = {}  # {node_id: {timestamp, status, earnings, sessions, ...}}
_per_node_lock = Lock()
_fleet_aggregate = {}  # Aggregated view across all nodes
_fleet_lock = Lock()


def _is_local_toolkit_url(url):
    """Return True if url points to this toolkit instance (localhost / 127.0.0.1 / own IP)."""
    if not url:
        return False
    url = url.lower().rstrip('/')
    local_hosts = {'localhost', '127.0.0.1', '::1', '0.0.0.0'}
    for h in local_hosts:
        if f'://{h}:' in url or url.endswith(f'://{h}'):
            return True
    # Check own port
    try:
        own_port = str(PORT)
        if url.endswith(f':{own_port}') or f':{own_port}/' in url:
            # Also verify hostname is local
            from urllib.parse import urlparse
            parsed = urlparse(url)
            if parsed.hostname in local_hosts:
                return True
    except Exception:
        pass
    return False


def _collect_single_node(node_entry):
    """Collect metrics for a single remote node.

    Three modes:
    1. LOCAL mode: toolkit_url points to this instance → read directly from metrics_cache
    2. PEER mode: node_entry has 'toolkit_url' → fetch from /peer/data (rich data)
    3. TEQUILA mode: fallback via TequilAPI (live only)
    """
    node_id     = node_entry['id']
    label       = node_entry.get('label', node_id)
    tequila_url = node_entry['url']
    toolkit_url = node_entry.get('toolkit_url')

    result = {
        'node_id':   node_id,
        'label':     label,
        'url':       tequila_url,
        'toolkit_url': toolkit_url,
        'timestamp': datetime.now().isoformat(),
        'status':    'offline',
        'uptime':    '0s',
        'version':   'unknown',
        'error':     None,
        'peer_mode': False,
    }

    # ── LOCAL MODE: toolkit_url points to this instance ────────────────────────
    # Read directly from metrics_cache — no HTTP call, no self-referential loop,
    # data is always fresh and never shows as offline due to startup timing.
    if toolkit_url and _is_local_toolkit_url(toolkit_url):
        try:
            with metrics_lock:
                cache = copy.deepcopy(metrics_cache)
            if cache:
                ns = cache.get('nodeStatus', {})
                earnings = cache.get('earnings', {})
                result.update({
                    'peer_mode':    True,
                    'status':       ns.get('status', 'unknown'),
                    'uptime':       ns.get('uptime', '0s'),
                    'version':      ns.get('version', APP_VERSION),
                    'earnings':     earnings,
                    'sessions':     cache.get('sessions', {}),
                    'services':     cache.get('services', {}),
                    'resources':    cache.get('resources', {}),
                    'performance':  cache.get('performance', {}),
                    'firewall':     cache.get('firewall', {}),
                    'systemHealth': cache.get('systemHealth', {}),
                    'node_quality': cache.get('nodeQuality', {}),
                    'nat':          ns.get('nat', ''),
                    'ip':           ns.get('ip', ''),
                    'identity':     ns.get('identity', earnings.get('wallet_address', '')),
                    'uptime_stats': cache.get('nodeQuality', {}),
                    'db_stats':     {},
                    'traffic':      cache.get('bandwidth', {}),
                    'live_connections': cache.get('live_connections', {}),
                })
                return result
        except Exception as e:
            result['error'] = f'Local cache read failed: {str(e)[:60]}'
            # Fall through to peer/tequila mode

    # ── PEER MODE: toolkit-to-toolkit ─────────────────────────────────────────
    if toolkit_url:
        try:
            # Build auth header for remote toolkit
            api_key  = node_entry.get('toolkit_api_key', '')
            username = node_entry.get('toolkit_username', '')
            password = node_entry.get('toolkit_password', '')
            headers  = {}
            if api_key:
                headers['Authorization'] = f'Bearer {api_key}'
            elif username and password:
                import base64 as b64
                creds = b64.b64encode(f'{username}:{password}'.encode()).decode()
                headers['Authorization'] = f'Basic {creds}'

            resp = requests.get(f'{toolkit_url}/peer/data', headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                ns   = data.get('node_status', {})
                result.update({
                    'peer_mode':        True,
                    'status':           ns.get('status', 'unknown'),
                    'uptime':           ns.get('uptime', '0s'),
                    'version':          data.get('version', 'unknown'),
                    'earnings':         data.get('earnings', {}),
                    'sessions':         data.get('sessions', {}),
                    'services':         data.get('services', {}),
                    'resources':        data.get('resources', {}),
                    'performance':      data.get('performance', {}),
                    'node_quality':     data.get('node_quality', {}),
                    'live_connections': data.get('live_connections', {}),
                    'firewall':         data.get('firewall', {}),
                    'systemHealth':     data.get('systemHealth', {}),
                    'uptime_stats':     data.get('uptime_stats', {}),
                    'db_stats':         data.get('db_stats', {}),
                    'earnings_history': data.get('earnings_history', []),
                    'traffic':          data.get('bandwidth', {}),
                    'traffic_history':  data.get('traffic_history', {}),
                    'analytics':        data.get('analytics', {}),
                    'logs':             data.get('logs', []),
                    'nat':              ns.get('nat', ns.get('nat_type', '')),
                    'ip':               ns.get('public_ip', ns.get('ip', '')),
                    'identity':         ns.get('identity', ''),
                    'wallet':           data.get('earnings', {}).get('wallet_address', ''),
                })
                return result
            else:
                result['error'] = f'Peer API HTTP {resp.status_code}'
                # Fall through to TequilAPI fallback
        except Exception as e:
            result['error'] = f'Peer connection failed: {str(e)[:60]}'
            # Fall through to TequilAPI fallback

    # ── TEQUILA MODE: direct TequilAPI ────────────────────────────────────────
    username = node_entry.get('username', NODE_USERNAME)
    password = node_entry.get('password', NODE_PASSWORD)
    headers  = {}
    if username and password:
        import base64 as b64
        creds = b64.b64encode(f'{username}:{password}'.encode()).decode()
        headers['Authorization'] = f'Basic {creds}'

    # Healthcheck
    try:
        resp = requests.get(f'{tequila_url}/healthcheck', headers=headers, timeout=8)
        if resp.status_code == 200:
            d = resp.json()
            result['status']  = 'online'
            result['uptime']  = d.get('uptime', '0s')
            result['version'] = d.get('version', 'unknown')
        else:
            result['error'] = f'HTTP {resp.status_code}'
            return result
    except Exception as e:
        result['error'] = str(e)[:60]
        return result

    # Identity + Earnings
    earnings = {'balance': 0, 'unsettled': 0, 'lifetime': 0, 'wallet_address': ''}
    try:
        resp = requests.get(f'{tequila_url}/identities', headers=headers, timeout=5)
        if resp.status_code == 200:
            identities = resp.json().get('identities', [])
            if identities:
                identity_id = identities[0].get('id', '')
                earnings['wallet_address'] = identity_id
                resp2 = requests.get(f'{tequila_url}/identities/{identity_id}', headers=headers, timeout=5)
                if resp2.status_code == 200:
                    d = resp2.json()
                    bt  = d.get('balance_tokens', {})
                    et  = d.get('earnings_tokens', {})
                    ett = d.get('earnings_total_tokens', {})
                    if isinstance(bt,  dict): earnings['balance']   = float(bt.get('ether', 0))
                    if isinstance(et,  dict): earnings['unsettled'] = float(et.get('ether', 0))
                    if isinstance(ett, dict): earnings['lifetime']  = float(ett.get('ether', 0))
    except Exception:
        pass
    result['earnings'] = earnings

    # Sessions
    sessions_data = {'items': [], 'active_items': [], 'total': 0, 'active': 0,
                     'unique_consumers': 0, 'session_total': 0,
                     'country_breakdown': [], 'lifetime_totals': {'sessions': 0, 'earnings_myst': 0, 'data_gb': 0}}
    try:
        resp = requests.get(f'{tequila_url}/sessions', headers=headers, timeout=8)
        if resp.status_code == 200:
            raw = resp.json()
            sess_list = raw.get('items', []) if isinstance(raw, dict) else raw
            if isinstance(sess_list, list):
                total_tokens = 0.0
                total_data_mb = 0.0
                consumers = set()
                active = 0
                items = []
                active_items = []
                country_map = {}
                for s in sess_list:
                    st = (s.get('service_type') or 'unknown').lower()
                    if st in MetricsCollector.INTERNAL_SERVICE_TYPES:
                        continue
                    is_active = s.get('status', '').lower() not in ('completed', 'closed', '')
                    tokens    = int(s.get('tokens', 0))
                    myst_val  = tokens / 1e18
                    b_in      = int(s.get('bytes_received', 0))
                    b_out     = int(s.get('bytes_sent', 0))
                    data_mb   = (b_in + b_out) / (1024 * 1024)
                    # Ghost filter: session marked running but 0 bytes + 0 tokens + >4h old
                    if is_active and b_in == 0 and b_out == 0 and tokens == 0:
                        started_raw = s.get('created_at', s.get('started_at', ''))
                        if started_raw:
                            try:
                                from datetime import timezone as _tz
                                st = datetime.fromisoformat(started_raw.replace('Z', '+00:00'))
                                if st.tzinfo is None:
                                    st = st.replace(tzinfo=_tz.utc)
                                if (datetime.now(_tz.utc) - st).total_seconds() > 14400:
                                    is_active = False
                            except (ValueError, TypeError):
                                pass
                    total_tokens  += myst_val
                    total_data_mb += data_mb
                    cid = s.get('consumer_id', 'unknown')
                    cc  = s.get('consumer_country', '') or ''
                    consumers.add(cid)
                    # Country breakdown
                    if cc:
                        if cc not in country_map:
                            country_map[cc] = {'country': cc, 'sessions': 0, 'total_earnings': 0.0, 'total_data_mb': 0.0}
                        country_map[cc]['sessions']      += 1
                        country_map[cc]['total_earnings'] += myst_val
                        country_map[cc]['total_data_mb']  += data_mb
                    item = {
                        'id':               s.get('id', ''),
                        'consumer_id':      cid,
                        'consumer_country': cc,
                        'service_type':     s.get('service_type', 'unknown'),
                        'is_active':        is_active,
                        'earnings_myst':    round(myst_val, 8),
                        'data_out':         round(b_out / (1024 * 1024), 2),
                        'data_in':          round(b_in  / (1024 * 1024), 2),
                        'data_total':       round(data_mb, 2),
                        'duration':         s.get('duration', '—'),
                        'started':          s.get('created_at', s.get('started_at', '')),
                    }
                    if is_active:
                        active += 1
                        active_items.append(item)
                    items.append(item)
                country_list = sorted(country_map.values(), key=lambda x: -x['sessions'])
                sessions_data.update({
                    'total':            len(items),
                    'active':           active,
                    'active_items':     active_items,
                    'unique_consumers': len(consumers),
                    'session_total':    round(total_tokens, 4),
                    'items':            items[:50],
                    'country_breakdown': country_list[:20],
                    'lifetime_totals':  {
                        'sessions':      len(items),
                        'earnings_myst': round(total_tokens, 6),
                        'data_gb':       round(total_data_mb / 1024, 3),
                    },
                })
    except Exception:
        pass
    result['sessions'] = sessions_data

    # Services
    services_data = {'active': 0, 'total': 0}
    try:
        resp = requests.get(f'{tequila_url}/services', headers=headers, timeout=5)
        if resp.status_code == 200:
            svc_list = resp.json() if isinstance(resp.json(), list) else []
            services_data['total']  = len(svc_list)
            services_data['active'] = sum(1 for s in svc_list if s.get('status', '').lower() in ('running', 'active'))
    except Exception:
        pass
    result['services'] = services_data

    return result




def _build_fleet_aggregate():
    """Build an aggregate view from all per-node metrics."""
    with _per_node_lock:
        nodes = list(_per_node_metrics.values())

    if not nodes:
        return {}

    agg = {
        'fleet_mode':    True,
        'fleet_nodes':   len(nodes),
        'fleet_online':  sum(1 for n in nodes if n.get('status') == 'online'),
        'fleet_offline': sum(1 for n in nodes if n.get('status') != 'online'),
        'fleet_earnings': {
            'balance':       sum(n.get('earnings', {}).get('balance', 0) for n in nodes),
            'unsettled':     sum(n.get('earnings', {}).get('unsettled', 0) for n in nodes),
            'lifetime':      sum(n.get('earnings', {}).get('lifetime', 0) for n in nodes),
            'session_total': sum(n.get('sessions', {}).get('session_total', 0) for n in nodes),
            # Peer mode: use richer archive data if available
            'lifetime_archived': sum(
                n.get('db_stats', {}).get('total_myst', 0) for n in nodes if n.get('peer_mode')
            ),
        },
        'fleet_sessions': {
            'total':            sum(n.get('sessions', {}).get('total', 0) for n in nodes),
            'active':           sum(n.get('sessions', {}).get('active', 0) for n in nodes),
            'unique_consumers': sum(n.get('sessions', {}).get('unique_consumers', 0) for n in nodes),
            # Peer mode: sessions archive total
            'archived_total':   sum(
                n.get('db_stats', {}).get('total', 0) for n in nodes if n.get('peer_mode')
            ),
        },
        'fleet_services': {
            'active': sum(n.get('services', {}).get('active', 0) for n in nodes),
            'total':  sum(n.get('services', {}).get('total', 0) for n in nodes),
        },
        'nodes': [{
            'id':          n.get('node_id'),
            'label':       n.get('label'),
            'url':         n.get('url'),
            'toolkit_url': n.get('toolkit_url'),
            'peer_mode':   n.get('peer_mode', False),
            'status':      n.get('status'),
            'uptime':      n.get('uptime'),
            'version':     n.get('version'),
            'nat':         n.get('nat', n.get('node_status', {}).get('nat', '')),
            'ip':          n.get('ip', n.get('node_status', {}).get('ip', '')),
            'identity':    n.get('identity', n.get('earnings', {}).get('wallet_address', '')),
            'error':       n.get('error'),
            'earnings':    n.get('earnings', {}),
            'sessions':    {k: v for k, v in n.get('sessions', {}).items() if k != 'items'},
            'services':    n.get('services', {}),
            'wallet':      n.get('earnings', {}).get('wallet_address', ''),
            # Rich peer data
            'uptime_stats':     n.get('uptime_stats', {}),
            'db_stats':         n.get('db_stats', {}),
            'node_quality':     n.get('node_quality', {}),
            'resources':        n.get('resources', {}),
        } for n in nodes],
        'timestamp': datetime.now().isoformat(),
    }
    return agg


def multi_node_background_collector():
    """Background collector for multi-node mode — staggered to avoid bursts."""
    logger.info(f"Multi-node collector started: {len(_node_registry)} nodes, "
                f"stagger={max(1, UPDATE_INTERVAL // max(1, len(_node_registry)))}s between nodes")
    cycle = 0
    while True:
        try:
            # Hot-reload nodes.json if changed
            if cycle % 30 == 0 and _check_nodes_json_changed():
                reload_node_registry()
                logger.info(f"nodes.json reloaded: {len(_node_registry)} nodes")

            # Stagger: spread node queries across the interval
            stagger_delay = max(0.5, UPDATE_INTERVAL / max(1, len(_node_registry)))

            for node_entry in _node_registry:
                try:
                    node_data = _collect_single_node(node_entry)
                    with _per_node_lock:
                        _per_node_metrics[node_entry['id']] = node_data
                except Exception as e:
                    logger.warning(f"Error collecting {node_entry['id']}: {e}")

                if len(_node_registry) > 5:
                    time.sleep(stagger_delay)

            # Build aggregate
            agg = _build_fleet_aggregate()
            with _fleet_lock:
                _fleet_aggregate.clear()
                _fleet_aggregate.update(agg)

            cycle += 1
        except Exception as e:
            logger.error(f"Multi-node collection error: {e}")

        time.sleep(max(UPDATE_INTERVAL, 5))  # Min 5s cycle in multi-node


def background_collector():
    """Background thread for metric collection — tiered caching.
    Single-node mode only. Multi-node uses multi_node_background_collector."""
    logger.info(f"Background collector started (interval={UPDATE_INTERVAL}s, "
                f"medium_tier={TIER_MEDIUM_INTERVAL}s, slow_tier={TIER_SLOW_INTERVAL}s)")
    while True:
        try:
            metrics = MetricsCollector.collect_all()
            with metrics_lock:
                metrics_cache.clear()
                metrics_cache.update(metrics)
                metrics_history.append(copy.deepcopy(metrics))
            logger.debug(f"Metrics collected at {metrics['timestamp']}")
        except Exception as e:
            logger.error(f"Collection error: {e}")

        time.sleep(UPDATE_INTERVAL)


def _setup_mysterium_forward_chain():
    """Consolidate Mysterium's duplicate FORWARD rules into a dedicated chain.

    Problem: Mysterium adds FORWARD rules via 'iptables -A' without checking
    if they already exist. After restarts, identical rules accumulate. This is
    a known Mysterium bug — it opens rules but never closes them.

    Solution (iptables only — nftables/ufw manages this correctly):
    1. Create a MYSTERIUM-FORWARD chain if it doesn't exist.
    2. Move all 10.182.x.x/24 FORWARD rules into that chain (deduplicated).
    3. Add a single jump rule: FORWARD → MYSTERIUM-FORWARD.
    4. On next call (restart): flush MYSTERIUM-FORWARD and re-populate.

    This way there are never duplicates regardless of how many times
    Mysterium restarts.

    Skipped on: nftables, ufw, non-iptables systems.
    Safe: only touches Mysterium's own 10.182.x.x subnet rules.
    """
    try:
        # Detect firewall type — only run on iptables systems
        ipt_bin = None
        for candidate in ['iptables-legacy', 'iptables']:
            try:
                r = subprocess.run(['which', candidate],
                                   capture_output=True, timeout=3, text=True)
                if r.returncode == 0:
                    # Verify it's not a nftables wrapper
                    ver = subprocess.run([candidate.strip(), '--version'],
                                         capture_output=True, timeout=3, text=True)
                    if ver.returncode == 0:
                        ipt_bin = candidate.strip()
                        break
            except Exception:
                pass

        if not ipt_bin:
            return  # No iptables — skip

        # Check if nftables is the primary firewall.
        # On Ubuntu/Debian, iptables may be a wrapper around nftables (iptables-nft).
        # Signals that nftables is primary:
        #   1. 'nft list ruleset' returns actual tables with rules
        #   2. iptables --version contains 'nf_tables'
        # If either is true, Mysterium manages its rules correctly — skip.
        try:
            nft = subprocess.run(['nft', 'list', 'ruleset'],
                                  capture_output=True, timeout=3, text=True)
            if nft.returncode == 0 and 'table' in nft.stdout and len(nft.stdout) > 50:
                logger.debug("_setup_mysterium_forward_chain: nftables active with rules, skipping")
                return
        except Exception:
            pass

        # Also check if iptables itself is a nft wrapper
        try:
            if ipt_bin:
                ver = subprocess.run([ipt_bin, '--version'],
                                     capture_output=True, timeout=3, text=True)
                if ver.returncode == 0 and 'nf_tables' in ver.stdout:
                    logger.debug("_setup_mysterium_forward_chain: iptables is nft wrapper, skipping")
                    return
        except Exception:
            pass

        # Check ufw active — ufw manages its own rules, skip
        try:
            ufw = subprocess.run(['ufw', 'status'],
                                  capture_output=True, timeout=3, text=True)
            if ufw.returncode == 0 and 'active' in ufw.stdout.lower():
                logger.debug("_setup_mysterium_forward_chain: ufw active, skipping")
                return
        except Exception:
            pass

        def _ipt(*args):
            """Run iptables command, try with sudo -n first."""
            for prefix in [['sudo', '-n'], []]:
                try:
                    r = subprocess.run(prefix + [ipt_bin] + list(args),
                                       capture_output=True, timeout=5, text=True)
                    if r.returncode == 0:
                        return True, r.stdout
                except Exception:
                    pass
            return False, ''

        # Step 1: Create MYSTERIUM-FORWARD chain if not exists
        ok, _ = _ipt('-L', 'MYSTERIUM-FORWARD', '-n')
        if not ok:
            _ipt('-N', 'MYSTERIUM-FORWARD')

        # Step 2: Flush the chain (remove old rules — will re-add deduplicated)
        _ipt('-F', 'MYSTERIUM-FORWARD')

        # Step 3: Read current FORWARD rules, find Mysterium's 10.182.x.x rules
        ok, output = _ipt('-L', 'FORWARD', '-n', '--line-numbers')
        if not ok:
            return

        mysterium_rules = []  # list of (line_num, src, dst) tuples
        seen_sigs = set()

        for line in output.split('\n'):
            parts = line.split()
            if not parts or not parts[0].isdigit():
                continue
            line_num = int(parts[0])
            rule_str = ' '.join(parts[1:])

            # Only touch 10.182.x.x/24 rules (Mysterium's WireGuard subnets)
            if '10.182.' not in rule_str:
                continue

            sig = rule_str
            if sig not in seen_sigs:
                seen_sigs.add(sig)
                mysterium_rules.append((line_num, rule_str))

        if not mysterium_rules:
            # No Mysterium FORWARD rules yet — add jump rule for later
            _ipt('-C', 'FORWARD', '-j', 'MYSTERIUM-FORWARD') or \
                _ipt('-I', 'FORWARD', '1', '-j', 'MYSTERIUM-FORWARD')
            return

        # Step 4: Remove all 10.182.x.x FORWARD rules (incl. duplicates)
        # Re-read with line numbers after each delete (indices shift)
        removed = 0
        for _ in range(50):  # max 50 iterations safety cap
            ok, output = _ipt('-L', 'FORWARD', '-n', '--line-numbers')
            if not ok:
                break
            deleted_any = False
            for line in output.split('\n'):
                parts = line.split()
                if not parts or not parts[0].isdigit():
                    continue
                if '10.182.' in ' '.join(parts[1:]):
                    line_num = parts[0]
                    ok2, _ = _ipt('-D', 'FORWARD', line_num)
                    if ok2:
                        removed += 1
                        deleted_any = True
                        break  # Re-read after each delete
            if not deleted_any:
                break

        # Step 5: Add deduplicated rules to MYSTERIUM-FORWARD chain
        added = 0
        for _, rule_str in mysterium_rules:
            # Parse src/dst to reconstruct the rule
            parts = rule_str.split()
            # Rule format: ACCEPT all -- src dst [extra]
            # We re-add as: -A MYSTERIUM-FORWARD -s src -j ACCEPT (or -d dst)
            if len(parts) >= 4:
                src = parts[2] if parts[2] != '--' else None
                dst = parts[3] if len(parts) > 3 else None
                if src and src != '0.0.0.0/0' and '10.182.' in src:
                    ok2, _ = _ipt('-A', 'MYSTERIUM-FORWARD', '-s', src, '-j', 'ACCEPT')
                    if ok2:
                        added += 1
                elif dst and dst != '0.0.0.0/0' and '10.182.' in dst:
                    ok2, _ = _ipt('-A', 'MYSTERIUM-FORWARD', '-d', dst, '-j', 'ACCEPT')
                    if ok2:
                        added += 1

        # Step 6: Ensure jump rule exists in FORWARD chain
        ok, _ = _ipt('-C', 'FORWARD', '-j', 'MYSTERIUM-FORWARD')
        if not ok:
            _ipt('-I', 'FORWARD', '1', '-j', 'MYSTERIUM-FORWARD')

        logger.info(f"Firewall: consolidated {removed} Mysterium FORWARD rules → "
                    f"{added} deduplicated in MYSTERIUM-FORWARD chain (iptables)")

    except Exception as e:
        logger.debug(f"_setup_mysterium_forward_chain failed (non-fatal): {e}")


def start_collector():
    """Start the appropriate background collector thread(s).
    Also launches a one-time startup thread to fetch full session history (all pages)."""

    # Consolidate Mysterium's duplicate FORWARD rules into a dedicated chain.
    # Runs only on iptables systems — skipped on nftables/ufw.
    try:
        _setup_mysterium_forward_chain()
    except Exception as e:
        logger.debug(f"Firewall chain setup skipped: {e}")

    # Pre-load earnings snapshot history immediately at startup (main thread).
    # Without this, the first get_deltas() call from the background loop returns
    # source='sessions' (building) because _snapshots is empty until _load() runs.
    # This causes weekly/monthly to show 'building' for up to 10 minutes after restart.
    try:
        EarningsDB.init()
        EarningsDeltaTracker._load(force=True)
        logger.info(f"EarningsDeltaTracker: pre-loaded {len(EarningsDeltaTracker._snapshots)} snapshots at startup")
    except Exception as e:
        logger.warning(f"EarningsDeltaTracker pre-load failed: {e}")

    # Pre-load firewall and system health at startup so peer/data has them immediately
    # without waiting 10 minutes for the first slow tier cycle
    try:
        global _tier_slow_cache
        _tier_slow_cache['firewall']     = MetricsCollector.get_firewall()
        _tier_slow_cache['systemHealth'] = MetricsCollector._get_health_cached()
        logger.info("Pre-loaded firewall and system health at startup")
    except Exception as e:
        logger.warning(f"Startup pre-load of firewall/health failed: {e}")

    def _startup_session_fetch():
        """Fetch all pages of session history once at startup. Runs in background.
        After loading, backfills consumer_country into SessionDB for older entries.
        If a delete lock exists (user deleted data), skip writing back to DB so the
        delete has a permanent effect across restarts."""
        try:
            headers = MetricsCollector.get_tequilapi_headers()
            for node_url in NODE_API_URLS:
                logger.info(f"SessionStore: starting full history fetch for {node_url} ...")
                SessionStore.fetch_all_pages(node_url, headers)
            # After all pages loaded, backfill consumer_country for archive entries
            # that were saved before country tracking was added
            try:
                live_sessions = MetricsCollector.get_sessions()
                live_items = live_sessions.get('items', []) if live_sessions else []
                live_with_country = [s for s in live_items if s.get('consumer_country') and s.get('id')]
                if live_with_country:
                    SessionDB.backfill_countries(live_with_country)
                    logger.info(f"Country backfill: updated from {len(live_with_country)} live sessions")
            except Exception as be:
                logger.debug(f"Country backfill failed: {be}")
        except Exception as e:
            logger.error(f"SessionStore startup fetch error: {e}")

    # Always launch the startup session fetch regardless of mode
    startup_thread = Thread(target=_startup_session_fetch, daemon=True, name='session-history-fetch')
    startup_thread.start()

    if MULTI_NODE_MODE:
        # Multi-node: run fleet collector AND local single-node collector
        fleet_thread = Thread(target=multi_node_background_collector, daemon=True)
        fleet_thread.start()
        # Also run local single-node for psutil data (CPU/RAM/tunnels)
        local_thread = Thread(target=background_collector, daemon=True)
        local_thread.start()
        logger.info("Started fleet collector + local collector + session history fetch")
        return fleet_thread
    else:
        collector_thread = Thread(target=background_collector, daemon=True)
        collector_thread.start()
        return collector_thread


# ============ API ENDPOINTS ============

@app.route('/config/setup.json', methods=['GET'])
def serve_setup_config():
    """Serve minimal safe config to the frontend.
    Only exposes auth method — never passwords, API keys or node credentials.
    Safe to call from remote — contains no sensitive data."""
    cfg_path = Path('config/setup.json')
    if cfg_path.exists():
        try:
            data = json.loads(cfg_path.read_text())
            # Only expose auth method and port — never passwords, keys, node credentials
            safe = {
                'dashboard_auth_method': data.get('dashboard_auth_method', 'apikey'),
                'dashboard_port':        data.get('dashboard_port', 5000),
            }
            return jsonify(safe), 200
        except Exception as e:
            logger.warning(f"Could not read setup.json: {e}")
            return jsonify({'error': 'Config unreadable'}), 500
    else:
        return jsonify({'error': 'No config found — run setup wizard first'}), 404


@app.route('/api/version', methods=['GET'])
def get_version():
    """Return toolkit version — no auth required."""
    return jsonify({'version': APP_VERSION}), 200


@app.route('/api/update-check', methods=['GET'])
def check_for_update():
    """Check if a newer version is available on GitHub.
    Polls raw VERSION file from GitHub main branch — cached 1 hour.
    No auth token required — raw file is publicly accessible even on private repos
    when accessed via the correct raw URL.
    """
    import urllib.request as _ur
    _VERSION_URL = 'https://raw.githubusercontent.com/IanJohnsons/mysterium-toolkit/main/VERSION'
    _cache = getattr(check_for_update, '_cache', None)
    _cache_time = getattr(check_for_update, '_cache_time', 0)

    now = time.time()
    if _cache is not None and now - _cache_time < 3600:
        return jsonify(_cache), 200

    try:
        req = _ur.Request(_VERSION_URL, headers={'User-Agent': 'mysterium-toolkit'})
        with _ur.urlopen(req, timeout=5) as resp:
            latest = resp.read().decode().strip()
        result = {
            'current':    APP_VERSION,
            'latest':     latest,
            'up_to_date': latest == APP_VERSION,
            'update_available': latest != APP_VERSION,
        }
    except Exception as e:
        result = {
            'current':          APP_VERSION,
            'latest':           None,
            'up_to_date':       True,
            'update_available': False,
            'error':            str(e)[:80],
        }

    check_for_update._cache      = result
    check_for_update._cache_time = now
    return jsonify(result), 200


@app.route('/api/node-update-check', methods=['GET'])
def check_node_update():
    """Check if a newer Mysterium node version is available on GitHub.
    Follows the GitHub releases/latest redirect to extract the tag — no token needed.
    Cached 1 hour. Compares against live node version from nodeStatus.
    """
    _cache = getattr(check_node_update, '_cache', None)
    _cache_time = getattr(check_node_update, '_cache_time', 0)

    now = time.time()
    if _cache is not None and now - _cache_time < 3600:
        return jsonify(_cache), 200

    latest = None
    try:
        import urllib.request as _ur
        req = _ur.Request(
            'https://github.com/mysteriumnetwork/node/releases/latest',
            headers={'User-Agent': 'mysterium-toolkit'}
        )
        # Don't follow redirect — we just want the Location header
        opener = _ur.build_opener(_ur.HTTPRedirectHandler())
        class _NoFollow(_ur.HTTPRedirectHandler):
            def redirect_request(self, *a, **kw): return None
        no_follow = _ur.build_opener(_NoFollow())
        try:
            no_follow.open(req, timeout=5)
        except Exception as redirect_exc:
            # urllib raises on redirect — extract URL from exception
            loc = getattr(redirect_exc, 'headers', {})
            if hasattr(loc, 'get'):
                url = loc.get('Location', '')
            else:
                url = str(redirect_exc)
            if '/tag/' in url:
                latest = url.split('/tag/')[-1].strip()
    except Exception:
        pass

    # Fallback: direct API call (may be rate-limited without token)
    if not latest:
        try:
            import urllib.request as _ur2
            req2 = _ur2.Request(
                'https://api.github.com/repos/mysteriumnetwork/node/releases/latest',
                headers={'User-Agent': 'mysterium-toolkit', 'Accept': 'application/vnd.github.v3+json'}
            )
            with _ur2.urlopen(req2, timeout=5) as resp:
                import json as _json
                data = _json.loads(resp.read())
                latest = data.get('tag_name', '').lstrip('v')
        except Exception:
            pass

    # Get current node version from live cache
    with metrics_lock:
        current = metrics_cache.get('nodeStatus', {}).get('version', 'unknown')

    def _norm(v):
        """Normalize version string for comparison: strip leading v, whitespace."""
        return str(v or '').strip().lstrip('v')

    current_n = _norm(current)
    latest_n  = _norm(latest) if latest else None

    update_available = bool(
        latest_n and current_n and
        current_n != 'unknown' and
        latest_n != current_n
    )

    result = {
        'current':          current_n or 'unknown',
        'latest':           latest_n,
        'update_available': update_available,
    }
    if not latest_n:
        result['error'] = 'Could not fetch latest version from GitHub'

    check_node_update._cache      = result
    check_node_update._cache_time = now
    return jsonify(result), 200
def health():
    """Health check - no auth required"""
    with metrics_lock:
        has_cache = bool(metrics_cache)

    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'node_connected': node_status['connected'],
        'node_error': node_status['error'],
        'has_metrics': has_cache
    }), 200


@app.route('/status', methods=['GET'])
@require_auth
def get_status():
    """Node status"""
    with metrics_lock:
        data = copy.deepcopy(metrics_cache)
    return jsonify(data.get('nodeStatus', {})), 200


@app.route('/earnings', methods=['GET'])
@require_auth
def get_earnings():
    """MYST earnings"""
    with metrics_lock:
        data = copy.deepcopy(metrics_cache)
    return jsonify(data.get('earnings', {})), 200


@app.route('/bandwidth', methods=['GET'])
@require_auth
def get_bandwidth():
    """Bandwidth metrics"""
    with metrics_lock:
        data = copy.deepcopy(metrics_cache)
    return jsonify(data.get('bandwidth', {})), 200


@app.route('/clients', methods=['GET'])
@require_auth
def get_clients():
    """Connected clients"""
    with metrics_lock:
        data = copy.deepcopy(metrics_cache)
    return jsonify(data.get('clients', {})), 200


@app.route('/performance', methods=['GET'])
@require_auth
def get_performance():
    """Performance metrics"""
    with metrics_lock:
        data = copy.deepcopy(metrics_cache)
    return jsonify(data.get('performance', {})), 200


@app.route('/resources', methods=['GET'])
@require_auth
def get_resources():
    """System resources"""
    with metrics_lock:
        data = copy.deepcopy(metrics_cache)
    return jsonify(data.get('resources', {})), 200


@app.route('/firewall', methods=['GET'])
@require_auth
def get_firewall():
    """Firewall status"""
    with metrics_lock:
        data = copy.deepcopy(metrics_cache)
    return jsonify(data.get('firewall', {})), 200


@app.route('/firewall/cleanup', methods=['POST'])
@require_auth
def firewall_cleanup():
    """Remove duplicate FORWARD rules left behind by Mysterium node.

    Mysterium adds FORWARD rules for WireGuard tunnel subnets (10.182.x.x/24)
    when tunnels are created but does not remove them on disconnect. After
    weeks of operation these accumulate as duplicates. This endpoint removes
    all but the first occurrence of each duplicate FORWARD rule.

    Works on: iptables, iptables-legacy, iptables-nft.
    Safe: only touches FORWARD chain duplicates, never INPUT or user rules.
    """
    try:
        # Detect iptables binary
        ipt_bin = None
        for candidate in ['iptables-legacy', 'iptables']:
            try:
                r = subprocess.run(['which', candidate], capture_output=True, timeout=3, text=True)
                if r.returncode == 0:
                    ipt_bin = candidate.strip()
                    break
            except Exception:
                pass

        if not ipt_bin:
            return jsonify({'ok': False, 'error': 'iptables not found'}), 200

        # Read current FORWARD rules with line numbers
        result = None
        for cmd in [
            ['sudo', '-n', ipt_bin, '-L', 'FORWARD', '-n', '--line-numbers'],
            [ipt_bin, '-L', 'FORWARD', '-n', '--line-numbers'],
        ]:
            try:
                r = subprocess.run(cmd, capture_output=True, timeout=5, text=True)
                if r.returncode == 0:
                    result = r.stdout
                    break
            except Exception:
                pass

        if not result:
            return jsonify({'ok': False, 'error': 'Cannot read FORWARD rules — sudo may be required'}), 200

        # Parse rules: build signature → list of line numbers
        from collections import OrderedDict
        seen = OrderedDict()  # signature → first_line_num
        duplicates = []       # line numbers to delete (descending order)

        for line in result.split('\n'):
            parts = line.split()
            if not parts or not parts[0].isdigit():
                continue
            line_num = int(parts[0])
            # Signature = everything except the line number
            signature = ' '.join(parts[1:])
            if signature in seen:
                duplicates.append(line_num)
            else:
                seen[signature] = line_num

        if not duplicates:
            # Also try flushing MYSTERIUM-FORWARD chain if it exists
            for cmd in [['sudo', '-n', ipt_bin, '-F', 'MYSTERIUM-FORWARD'],
                        [ipt_bin, '-F', 'MYSTERIUM-FORWARD']]:
                try:
                    subprocess.run(cmd, capture_output=True, timeout=5, text=True)
                    break
                except Exception:
                    pass
            return jsonify({'ok': True, 'removed': 0, 'message': 'No duplicates found'}), 200

        # Delete in reverse order (highest line number first) to avoid index shifting
        removed = 0
        errors = []
        for line_num in sorted(duplicates, reverse=True):
            for cmd in [
                ['sudo', '-n', ipt_bin, '-D', 'FORWARD', str(line_num)],
                [ipt_bin, '-D', 'FORWARD', str(line_num)],
            ]:
                try:
                    r = subprocess.run(cmd, capture_output=True, timeout=5, text=True)
                    if r.returncode == 0:
                        removed += 1
                        break
                except Exception as e:
                    errors.append(str(e))

        # Invalidate firewall cache so next /metrics fetch shows clean rules
        with metrics_lock:
            if 'firewall' in metrics_cache:
                metrics_cache['firewall'] = MetricsCollector.get_firewall()

        msg = f"Removed {removed} duplicate FORWARD rule(s)"
        if errors:
            msg += f" ({len(errors)} errors)"
        logger.info(f"Firewall cleanup: {msg}")
        return jsonify({'ok': True, 'removed': removed, 'message': msg}), 200

    except Exception as e:
        logger.warning(f"Firewall cleanup error: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 200


@app.route('/sessions', methods=['GET'])
@require_auth
def get_sessions():
    """Individual session details"""
    with metrics_lock:
        data = copy.deepcopy(metrics_cache)
    return jsonify(data.get('sessions', {})), 200


@app.route('/live-connections', methods=['GET'])
@require_auth
def get_live_connections():
    """Real-time WireGuard peer connections"""
    with metrics_lock:
        data = copy.deepcopy(metrics_cache)
    return jsonify(data.get('live_connections', {})), 200


@app.route('/debug/traffic', methods=['GET'])
@require_auth
def debug_traffic():
    """Diagnostic endpoint: compare raw vnstat vs psutil vs what dashboard shows.
    Use this to verify traffic numbers match actual vnstat output.
    Access: http://localhost:5000/debug/traffic"""
    diag = {}

    # 1. Raw vnstat JSON output
    try:
        result = subprocess.run(['vnstat', '--json'], capture_output=True, timeout=5, text=True)
        if result.returncode == 0:
            diag['vnstat_raw_json'] = json.loads(result.stdout)
        else:
            diag['vnstat_raw_json'] = {'error': result.stderr}
    except Exception as e:
        diag['vnstat_raw_json'] = {'error': str(e)}

    # 2. Raw vnstat CLI output (human-readable)
    try:
        result = subprocess.run(['vnstat', '-m'], capture_output=True, timeout=5, text=True)
        diag['vnstat_cli_monthly'] = result.stdout if result.returncode == 0 else result.stderr
    except Exception as e:
        diag['vnstat_cli_monthly'] = str(e)

    # 3. Our parsed vnstat data
    diag['vnstat_parsed'] = MetricsCollector._get_vnstat_traffic()

    # 4. Raw psutil per-interface counters
    per_nic = psutil.net_io_counters(pernic=True)
    diag['psutil_interfaces'] = {}
    for name, c in sorted(per_nic.items()):
        if any(name.startswith(p) for p in ('myst', 'wg', 'tun', 'eno', 'eth', 'enp')):
            diag['psutil_interfaces'][name] = {
                'bytes_recv': c.bytes_recv,
                'bytes_sent': c.bytes_sent,
                'recv_mb': round(c.bytes_recv / (1024 * 1024), 2),
                'sent_mb': round(c.bytes_sent / (1024 * 1024), 2),
                'note': 'recv=packets FROM tunnel (consumer requests), sent=packets TO tunnel (content served)'
                        if any(name.startswith(p) for p in ('myst', 'wg', 'tun'))
                        else 'physical NIC',
            }

    # 5. What the dashboard currently shows
    with metrics_lock:
        data = copy.deepcopy(metrics_cache)
    bw = data.get('bandwidth', {})
    diag['dashboard_shows'] = {
        'vpn_today_total_mb': bw.get('vpn_today_total', 0),
        'vpn_today_in_mb': bw.get('vpn_today_in', 0),
        'vpn_today_out_mb': bw.get('vpn_today_out', 0),
        'vpn_month_total_mb': bw.get('vpn_month_total', 0),
        'vnstat_nic_name': bw.get('vnstat_nic_name', '?'),
        'vnstat_today_total_mb': bw.get('vnstat_today_total', 0),
        'vnstat_month_total_mb': bw.get('vnstat_month_total', 0),
        'vnstat_vpn_month_total_mb': bw.get('vnstat_vpn_month_total', 0),
        'has_vpn_vnstat': bw.get('has_vpn_vnstat', False),
        'data_source_note': 'All _mb values are in MiB (÷1024÷1024 from bytes)',
    }

    return jsonify(diag), 200


@app.route('/services', methods=['GET'])
@require_auth
def get_services():
    """Running node services"""
    with metrics_lock:
        data = copy.deepcopy(metrics_cache)
    return jsonify(data.get('services', {})), 200


@app.route('/logs', methods=['GET'])
@require_auth
def get_logs():
    """System logs"""
    limit = request.args.get('limit', 50, type=int)
    limit = min(max(limit, 1), 500)  # Clamp between 1-500
    with metrics_lock:
        data = copy.deepcopy(metrics_cache)
    logs = data.get('logs', [])[:limit]
    return jsonify({'logs': logs}), 200


@app.route('/metrics', methods=['GET'])
@require_auth
def get_all_metrics():
    """All metrics — includes fleet aggregate if multi-node mode active"""
    with metrics_lock:
        data = copy.deepcopy(metrics_cache)
    # Inject fleet data if multi-node mode
    if MULTI_NODE_MODE:
        with _fleet_lock:
            fleet = copy.deepcopy(_fleet_aggregate)
        data['fleet'] = fleet
    return jsonify(data), 200

@app.route('/fast', methods=['GET'])
@require_auth
def get_fast_metrics():
    """Fast-tier metrics only — psutil data: resources, performance, live_connections.
    Safe to poll every 3 seconds. No TequilAPI or blockchain calls."""""
    with metrics_lock:
        data = copy.deepcopy(metrics_cache)
    return jsonify({
        'resources':       data.get('resources', {}),
        'performance':     data.get('performance', {}),
        'live_connections': data.get('live_connections', {}),
        'nodeQuality':     data.get('nodeQuality', {}),
        'nodeConnected':   data.get('nodeConnected', False),
        'timestamp':       data.get('timestamp', ''),
    }), 200


@app.route('/fleet', methods=['GET'])
@require_auth
def get_fleet():
    """Fleet overview — aggregate metrics across all nodes.
    Only available when nodes.json is configured."""
    if not MULTI_NODE_MODE:
        return jsonify({'error': 'Multi-node mode not active. Create a nodes.json file to enable.'}), 404
    with _fleet_lock:
        data = copy.deepcopy(_fleet_aggregate)
    return jsonify(data), 200


@app.route('/fleet/node/<node_id>', methods=['GET'])
@require_auth
def get_fleet_node(node_id):
    """Per-node metrics for a specific node in the fleet."""
    if not MULTI_NODE_MODE:
        return jsonify({'error': 'Multi-node mode not active'}), 404
    with _per_node_lock:
        node_data = _per_node_metrics.get(node_id)
    if not node_data:
        return jsonify({'error': f'Node {node_id} not found'}), 404
    return jsonify(copy.deepcopy(node_data)), 200


@app.route('/fleet/nodes', methods=['GET'])
@require_auth
def get_fleet_nodes():
    """List all registered nodes and their current status."""
    if not MULTI_NODE_MODE:
        return jsonify({'error': 'Multi-node mode not active'}), 404
    with _per_node_lock:
        nodes = [{
            'id': n.get('node_id'),
            'label': n.get('label'),
            'url': n.get('url'),
            'status': n.get('status', 'unknown'),
            'uptime': n.get('uptime', '—'),
            'version': n.get('version', ''),
            'error': n.get('error'),
            'earnings_unsettled': n.get('earnings', {}).get('unsettled', 0),
            'earnings_lifetime': n.get('earnings', {}).get('lifetime', 0),
            'sessions_active': n.get('sessions', {}).get('active', 0),
            'sessions_total': n.get('sessions', {}).get('total', 0),
            'wallet': n.get('earnings', {}).get('wallet_address', ''),
        } for n in _per_node_metrics.values()]
    return jsonify({'nodes': nodes, 'total': len(nodes)}), 200


@app.route('/fleet/reload', methods=['POST'])
@require_auth
def reload_fleet():
    """Force reload nodes.json without restarting."""
    if reload_node_registry():
        return jsonify({'success': True, 'nodes': len(_node_registry)}), 200
    return jsonify({'success': False, 'error': 'No nodes.json found or empty'}), 400


@app.route('/fleet/config', methods=['GET'])
@require_auth
def get_fleet_config():
    """Read current nodes.json config for the fleet manager UI."""
    config_path = _nodes_json_path or Path('config/nodes.json')
    try:
        if config_path.exists():
            with open(config_path) as f:
                data = json.load(f)
            nodes = data if isinstance(data, list) else data.get('nodes', [])
        else:
            nodes = []
        return jsonify({'nodes': nodes, 'path': str(config_path)}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/fleet/config', methods=['POST'])
@require_auth
def save_fleet_config():
    """Write nodes.json and hot-reload the fleet registry."""
    try:
        body = request.get_json() or {}
        nodes = body.get('nodes', [])

        # Validate each node has required fields
        for i, n in enumerate(nodes):
            if not n.get('toolkit_url'):
                return jsonify({'error': f'Node {i+1} missing toolkit_url'}), 400
            if not n.get('toolkit_api_key'):
                return jsonify({'error': f'Node {i+1} missing toolkit_api_key'}), 400
            # Auto-generate id if missing
            if not n.get('id'):
                import re as _re
                base = _re.sub(r'[^a-z0-9]', '-', (n.get('label', f'node{i}')).lower())
                n['id'] = base.strip('-') or f'node{i}'

        config_path = _nodes_json_path or Path('config/nodes.json')
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, 'w') as f:
            json.dump({'nodes': nodes}, f, indent=2)

        reload_node_registry()
        return jsonify({'success': True, 'nodes': len(nodes), 'path': str(config_path)}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/fleet/probe', methods=['POST'])
@require_auth
def probe_fleet_node():
    """Test connection to a toolkit URL and auto-discover node info.
    Body: {toolkit_url, toolkit_api_key}
    Returns: node identity, version, label, status
    """
    try:
        body = request.get_json() or {}
        toolkit_url = body.get('toolkit_url', '').rstrip('/')
        api_key = body.get('toolkit_api_key', '')

        if not toolkit_url:
            return jsonify({'success': False, 'error': 'toolkit_url required'}), 400

        headers = {}
        if api_key:
            headers['Authorization'] = f'Bearer {api_key}'

        # Test /health first
        try:
            health = requests.get(f'{toolkit_url}/health', headers=headers, timeout=6)
            if health.status_code == 401:
                return jsonify({'success': False, 'error': 'Invalid API key — authentication failed'}), 200
            if health.status_code != 200:
                return jsonify({'success': False, 'error': f'Toolkit returned HTTP {health.status_code}'}), 200
        except requests.exceptions.ConnectionError:
            return jsonify({'success': False, 'error': f'Cannot reach {toolkit_url} — check URL and port forwarding'}), 200
        except requests.exceptions.Timeout:
            return jsonify({'success': False, 'error': f'Connection timed out — node may be offline'}), 200

        # Fetch peer/data for node info
        node_info = {}
        try:
            peer = requests.get(f'{toolkit_url}/peer/data', headers=headers, timeout=8)
            if peer.status_code == 200:
                data = peer.json()
                ns = data.get('node_status', {})
                earnings = data.get('earnings', {})
                node_info = {
                    'identity': ns.get('identity') or earnings.get('wallet_address', ''),
                    'version':  ns.get('version', ''),
                    'status':   ns.get('status', 'unknown'),
                    'nat':      ns.get('nat', ''),
                    'ip':       ns.get('public_ip', ns.get('ip', '')),
                }
        except Exception:
            pass

        # Try /metrics as fallback
        if not node_info.get('identity'):
            try:
                m = requests.get(f'{toolkit_url}/metrics', headers=headers, timeout=6)
                if m.status_code == 200:
                    md = m.json()
                    ns2 = md.get('nodeStatus', {})
                    node_info['identity'] = ns2.get('identity', '')
                    node_info['version']  = ns2.get('version', '')
                    node_info['status']   = ns2.get('status', 'unknown')
            except Exception:
                pass

        # Auto-generate label from IP + version
        ip = node_info.get('ip', '')
        ver = node_info.get('version', '')
        identity = node_info.get('identity', '')
        short_id = f'{identity[:6]}…{identity[-4:]}' if len(identity) > 10 else identity
        suggested_label = ip or short_id or 'Remote Node'
        if ver:
            suggested_label += f' (v{ver})'

        return jsonify({
            'success':         True,
            'suggested_label': suggested_label,
            'identity':        identity,
            'version':         ver,
            'status':          node_info.get('status', 'unknown'),
            'nat':             node_info.get('nat', ''),
            'ip':              ip,
        }), 200

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500



@app.route('/fleet/test/<node_id>', methods=['GET'])
@require_auth
def test_fleet_node(node_id):
    """Connectivity test for a specific fleet node.
    Tests both TequilAPI (port 4449) and toolkit peer API (port 5000).
    Useful for diagnosing port-forwarding issues without a full restart.
    """
    node_entry = next((n for n in _node_registry if n['id'] == node_id), None)
    if not node_entry:
        return jsonify({'error': f'Node {node_id!r} not in registry. Check nodes.json.'}), 404

    tequila_url = node_entry.get('url', '')
    toolkit_url = node_entry.get('toolkit_url', '')
    api_key     = node_entry.get('toolkit_api_key', '')

    result = {
        'node_id':    node_id,
        'label':      node_entry.get('label', node_id),
        'tequila_url': tequila_url,
        'toolkit_url': toolkit_url,
        'tequila': {'ok': False, 'status': None, 'error': None, 'latency_ms': None},
        'toolkit': {'ok': False, 'status': None, 'error': None, 'latency_ms': None},
    }

    import time as _t

    # Test TequilAPI
    if tequila_url:
        try:
            t0 = _t.time()
            r = requests.get(f'{tequila_url}/healthcheck', timeout=8,
                             headers=MetricsCollector.get_tequilapi_headers())
            ms = round((_t.time() - t0) * 1000)
            result['tequila'] = {'ok': r.status_code == 200, 'status': r.status_code,
                                 'error': None, 'latency_ms': ms}
        except Exception as e:
            result['tequila']['error'] = str(e)

    # Test toolkit peer API
    if toolkit_url:
        try:
            hdrs = {'Authorization': f'Bearer {api_key}'} if api_key else {}
            t0 = _t.time()
            r = requests.get(f'{toolkit_url}/peer/data', headers=hdrs, timeout=10)
            ms = round((_t.time() - t0) * 1000)
            result['toolkit'] = {'ok': r.status_code == 200, 'status': r.status_code,
                                 'error': None, 'latency_ms': ms}
            if r.status_code == 401:
                result['toolkit']['error'] = 'Auth failed — check toolkit_api_key in nodes.json'
            elif r.status_code == 404:
                result['toolkit']['error'] = '/peer/data not found — is toolkit v5.5+ running on remote?'
        except Exception as e:
            result['toolkit']['error'] = str(e)

    result['summary'] = (
        'Both OK' if result['tequila']['ok'] and result['toolkit']['ok']
        else 'TequilAPI OK, toolkit unreachable — check port 5000 forwarding' if result['tequila']['ok']
        else 'Both unreachable — check IP/firewall'
    )
    return jsonify(result), 200


@app.route('/fleet/node/<node_id>/proxy/<path:endpoint>', methods=['GET', 'POST'])
@require_auth
def fleet_node_proxy(node_id, endpoint):
    """Proxy health fix/scan/persist/unpersist requests to a remote fleet node.
    The frontend sends health fix requests to the central backend.
    The central backend forwards them to the correct remote node using the stored API key.
    This way the API key never leaves the server side.
    Only allowed endpoints: system-health/fix, system-health/persist,
    system-health/unpersist, system-health/scan, earnings/chart,
    traffic/history, settle/history, sessions/archive,
    node/restart, node/settle, node/test, firewall/cleanup,
    services (stop/start).
    """
    ALLOWED = {
        'system-health/fix', 'system-health/persist',
        'system-health/unpersist', 'system-health/scan',
        'earnings/chart', 'settle/history',
        'node/restart', 'node/settle', 'node/test',
        'node/config/current', 'node/config/set', 'node/config/reset',
        'firewall/cleanup',
        'data/stats', 'data/delete', 'data/retention',
        'data/quality/history', 'data/system/history',
        'analytics/service-split', 'analytics/earnings-efficiency',
    }
    endpoint_base = endpoint.split('?')[0]
    if (endpoint_base not in ALLOWED
            and not endpoint_base.startswith('traffic/history')
            and not endpoint_base.startswith('sessions/archive')
            and not endpoint_base.startswith('services/')):
        return jsonify({'error': f'Proxy not allowed for endpoint: {endpoint}'}), 403

    node_entry = next((n for n in _node_registry if n['id'] == node_id), None)
    if not node_entry:
        return jsonify({'error': f'Node {node_id!r} not in registry'}), 404

    toolkit_url = node_entry.get('toolkit_url', '')
    if not toolkit_url:
        return jsonify({'error': 'No toolkit_url configured for this node'}), 400

    api_key  = node_entry.get('toolkit_api_key', '')
    username = node_entry.get('toolkit_username', '')
    password = node_entry.get('toolkit_password', '')
    headers  = {'Content-Type': 'application/json'}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    elif username and password:
        import base64 as _b64
        creds = _b64.b64encode(f'{username}:{password}'.encode()).decode()
        headers['Authorization'] = f'Basic {creds}'

    try:
        body = request.get_data() or b'{}'
        # Forward query params (e.g. ?range=month&limit=50&offset=0)
        query_string = request.query_string.decode('utf-8')
        target_url = f'{toolkit_url}/{endpoint}'
        if query_string:
            target_url = f'{target_url}?{query_string}'
        resp = requests.request(
            method=request.method,
            url=target_url,
            headers=headers,
            data=body,
            timeout=30,
        )
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({'error': f'Proxy request failed: {str(e)[:80]}'}), 502


# ── MYST token price cache ───────────────────────────────────────────────────
_myst_price_cache = {'usd': None, 'eur': None, 'fetched_at': 0}
_myst_price_lock  = Lock()
MYST_PRICE_TTL    = 300  # 5 minutes


@app.route('/myst-price', methods=['GET'])
@require_auth
def get_myst_price():
    """Live MYST token price in USD and EUR. No API key required.

    Sources — both completely free, no registration:
      USD: CoinPaprika public API (api.coinpaprika.com)
      EUR: Frankfurter ECB exchange rates (api.frankfurter.app) applied to USD price

    Returns {usd, eur, cached, stale?} — never errors, returns nulls on failure.
    """
    now = time.time()
    with _myst_price_lock:
        if now - _myst_price_cache['fetched_at'] < MYST_PRICE_TTL:
            return jsonify({
                'usd': _myst_price_cache['usd'],
                'eur': _myst_price_cache['eur'],
                'source': 'coinpaprika',
                'cached': True,
            }), 200

    try:
        # Step 1: MYST/USD from CoinPaprika — free public API, no key needed
        resp = requests.get(
            'https://api.coinpaprika.com/v1/tickers/myst-mysterium',
            timeout=6,
        )
        resp.raise_for_status()
        usd = float(resp.json()['quotes']['USD']['price'])

        # Step 2: USD→EUR rate from Frankfurter (ECB data) — free, no key needed
        eur = None
        try:
            fx = requests.get(
                'https://api.frankfurter.app/latest',
                params={'from': 'USD', 'to': 'EUR'},
                timeout=5,
            )
            fx.raise_for_status()
            eur_rate = float(fx.json()['rates']['EUR'])
            eur = round(usd * eur_rate, 6)
        except Exception:
            pass  # EUR unavailable — USD still shown

        usd = round(usd, 6)
        with _myst_price_lock:
            _myst_price_cache.update({'usd': usd, 'eur': eur, 'fetched_at': time.time()})
        return jsonify({'usd': usd, 'eur': eur, 'source': 'coinpaprika', 'cached': False}), 200

    except Exception as e:
        logger.warning(f'MYST price fetch failed: {e}')
        with _myst_price_lock:
            if _myst_price_cache['usd'] is not None:
                return jsonify({
                    'usd': _myst_price_cache['usd'],
                    'eur': _myst_price_cache['eur'],
                    'source': 'coinpaprika',
                    'cached': True,
                    'stale': True,
                }), 200
        return jsonify({'usd': None, 'eur': None, 'error': str(e)}), 200


@app.route('/history', methods=['GET'])
@require_auth
def get_history():
    """Historical metrics"""
    limit = request.args.get('limit', 100, type=int)
    limit = min(max(limit, 1), 1000)  # Clamp between 1-1000
    with metrics_lock:
        history = list(metrics_history)[-limit:]
    return jsonify({'history': history}), 200


@app.route('/earnings/snapshots/delete', methods=['POST'])
@require_auth
def delete_earnings_snapshots():
    """Delete earnings snapshots.

    Body options:
      {"keep_last_days": N}                          — keep last N days, delete everything older
      {"period": "all"}                              — delete everything
      {"period": "before", "before_date": "YYYY-MM-DD"} — delete before specific date
    """
    body = request.get_json(silent=True) or {}

    EarningsDB.init()
    try:
        # Primary: keep_last_days — delete everything older than N days from now
        keep_last_days = body.get('keep_last_days')
        if keep_last_days is not None:
            try:
                keep_last_days = int(keep_last_days)
            except (ValueError, TypeError):
                return jsonify({'error': 'keep_last_days must be an integer'}), 400
            cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_last_days)).isoformat()
            conn = EarningsDB._conn()
            cur = conn.execute("DELETE FROM earnings_snapshots WHERE time < ?", (cutoff,))
            deleted = cur.rowcount
            remaining = conn.execute("SELECT COUNT(*) FROM earnings_snapshots").fetchone()[0]
            conn.commit()
            conn.close()
            EarningsDeltaTracker._loaded = False
            logger.info(f"earnings/snapshots/delete: keep_last={keep_last_days}d deleted={deleted} remaining={remaining}")
            return jsonify({
                'deleted': deleted, 'remaining': remaining,
                'message': f'Deleted {deleted} snapshots older than {keep_last_days} days. {remaining} remain.',
            }), 200

        period = body.get('period', '')
        if not period:
            return jsonify({'error': 'keep_last_days or period required'}), 400
        if period not in ('all', 'before'):
            return jsonify({'error': 'Use keep_last_days, period=all, or period=before with before_date'}), 400
        if period == 'before' and not body.get('before_date', ''):
            return jsonify({'error': 'before_date required for period=before'}), 400

        conn = EarningsDB._conn()
        if period == 'all':
            cur = conn.execute("DELETE FROM earnings_snapshots")
            deleted = cur.rowcount
        else:
            cur = conn.execute("DELETE FROM earnings_snapshots WHERE time < ?", (body['before_date'],))
            deleted = cur.rowcount

        remaining = conn.execute("SELECT COUNT(*) FROM earnings_snapshots").fetchone()[0]
        conn.commit()
        conn.close()
        EarningsDeltaTracker._loaded = False
        logger.info(f"earnings/snapshots/delete: period={period} deleted={deleted} remaining={remaining}")
        return jsonify({
            'deleted': deleted, 'remaining': remaining, 'period': period,
            'message': f'Deleted {deleted} snapshots. {remaining} remain.',
        }), 200

    except Exception as e:
        logger.error(f'earnings/snapshots/delete error: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/earnings/snapshots/info', methods=['GET'])
@require_auth
def earnings_snapshots_info():
    """Return snapshot DB stats for the delete UI: total count, oldest, newest, per-period counts."""
    EarningsDB.init()
    try:
        conn = EarningsDB._conn()
        total = conn.execute("SELECT COUNT(*) FROM earnings_snapshots").fetchone()[0]
        if total == 0:
            conn.close()
            return jsonify({'total': 0, 'oldest': None, 'newest': None, 'periods': {}}), 200

        oldest_row = conn.execute("SELECT time FROM earnings_snapshots ORDER BY time ASC LIMIT 1").fetchone()
        newest_row = conn.execute("SELECT time FROM earnings_snapshots ORDER BY time DESC LIMIT 1").fetchone()
        oldest_dt = datetime.fromisoformat(oldest_row['time'].replace('Z', '+00:00'))
        if oldest_dt.tzinfo is None:
            oldest_dt = oldest_dt.replace(tzinfo=timezone.utc)

        periods = {}
        for label, (d_from, d_to) in [('week1',(0,7)),('week2',(7,14)),('week3',(14,21)),('week4',(21,28)),('month1',(0,30)),('month2',(30,60)),('month3',(60,90))]:
            s = (oldest_dt + timedelta(days=d_from)).isoformat()
            e = (oldest_dt + timedelta(days=d_to)).isoformat()
            cnt = conn.execute(
                "SELECT COUNT(*) FROM earnings_snapshots WHERE time >= ? AND time < ?", (s, e)
            ).fetchone()[0]
            periods[label] = {
                'count': cnt,
                'from':  s[:10],
                'to':    e[:10],
            }

        conn.close()
        return jsonify({
            'total':   total,
            'oldest':  oldest_row['time'][:10],
            'newest':  newest_row['time'][:10],
            'periods': periods,
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/earnings/chart', methods=['GET'])
@require_auth
def get_earnings_chart():
    """Return earnings snapshot history for charting.

    Aggregates hourly snapshots into daily buckets.
    Corrupt snapshots (from rate-limited sessions where session_total was
    stored as lifetime) are detected and removed before aggregation.
    A snapshot is corrupt when lifetime makes an unrealistically large jump
    (>20 MYST between consecutive hourly snapshots — impossible in normal
    operation where the node earns ~0.5-2 MYST/day).
    """
    try:
        # Read from EarningsDB SQLite — no time limit, full history
        EarningsDB.init()
        raw_rows = EarningsDB.get_all_for_chart()  # all time, no cutoff

        if not raw_rows:
            # Fallback to in-memory cache if DB empty
            EarningsDeltaTracker._load(force=True)
            raw_rows = EarningsDeltaTracker._snapshots

        if not raw_rows:
            return jsonify({'daily': [], 'snapshots': [], 'days': 0}), 200

        # Parse timestamps
        parsed = []
        for s in raw_rows:
            try:
                t = datetime.fromisoformat(str(s['time']).replace('Z', '+00:00'))
                if t.tzinfo is None:
                    t = t.replace(tzinfo=timezone.utc)
                parsed.append({
                    't':        t,
                    'lifetime': float(s.get('lifetime', 0) or 0),
                    'source':   s.get('source', 'unknown'),
                })
            except Exception:
                pass

        if not parsed:
            return jsonify({'daily': [], 'snapshots': [], 'days': 0}), 200

        clean = sorted(parsed, key=lambda x: x['t'])

        # Filter out snapshots where lifetime went backwards — these are corrupt
        # entries caused by node restarts, settlements gone wrong, or DB migration
        # issues. A lifetime value that is lower than the previous one is impossible
        # in normal operation and causes inflated daily delta calculations.
        validated = []
        prev_lt = None
        for entry in clean:
            if prev_lt is None or entry['lifetime'] >= prev_lt - 0.001:
                validated.append(entry)
                prev_lt = entry['lifetime']
        clean = validated


        # ── Daily aggregation ───────────────────────────────────────────
        from collections import OrderedDict
        daily_map = OrderedDict()
        for entry in clean:
            # Use TOOLKIT_TZ for date bucketing so bars align with local midnight,
            # not UTC midnight. Without this, Belgium (UTC+2) sees the first 2h of
            # each local day attributed to the previous bar.
            day = entry['t'].astimezone(TOOLKIT_TZ).strftime('%Y-%m-%d')
            if day not in daily_map:
                daily_map[day] = {'first': entry['lifetime'], 'last': entry['lifetime'], 'date': day}
            else:
                daily_map[day]['last'] = entry['lifetime']

        # Fill gaps: ensure every calendar day between oldest and newest is present
        # Days without a snapshot get earned=0 and carry forward the last known lifetime
        if daily_map:
            from datetime import date as _date
            oldest_d = _date.fromisoformat(list(daily_map.keys())[0])
            newest_d = datetime.now(TOOLKIT_TZ).date()  # local date — matches bucketing above
            filled_map = OrderedDict()
            last_lifetime = list(daily_map.values())[0]['first']
            cur = oldest_d
            while cur <= newest_d:
                day_str = cur.isoformat()
                if day_str in daily_map:
                    filled_map[day_str] = daily_map[day_str]
                    last_lifetime = daily_map[day_str]['last']
                else:
                    # Gap day — no snapshot, carry forward last known lifetime
                    filled_map[day_str] = {'first': last_lifetime, 'last': last_lifetime, 'date': day_str, 'gap': True}
                cur = _date.fromordinal(cur.toordinal() + 1)
            daily_map = filled_map

        days_list = list(daily_map.values())
        daily_out = []
        last_real_lifetime = None
        for i, d in enumerate(days_list):
            if d.get('gap'):
                earned = 0.0
            else:
                if last_real_lifetime is not None:
                    earned = max(0.0, round(d['last'] - last_real_lifetime, 4))
                else:
                    # First real snapshot day — earned = delta within that day itself
                    # (last - first of that day), not forced to 0 anymore
                    earned = max(0.0, round(d['last'] - d['first'], 4))
                last_real_lifetime = d['last']
            daily_out.append({
                'date':     d['date'],
                'earned':   earned,
                'lifetime': round(d['last'], 4),
                'gap':      d.get('gap', False),
            })

        # days = total calendar span (oldest to newest), regardless of gaps
        calendar_span = ((_date.fromisoformat(daily_out[-1]['date']) - _date.fromisoformat(daily_out[0]['date'])).days + 1) if daily_out else 0

        step = max(1, len(clean) // 200)  # Max 200 points for charting
        raw = [{'time': e['t'].isoformat(), 'lifetime': round(e['lifetime'], 4)}
               for e in clean[::step]]

        return jsonify({
            'daily':     daily_out,
            'snapshots': raw,
            'days':      calendar_span,
            'oldest':    daily_out[0]['date'] if daily_out else None,
            'newest':    daily_out[-1]['date'] if daily_out else None,
        }), 200

    except Exception as e:
        logger.warning(f'earnings/chart error: {e}')
        return jsonify({'daily': [], 'snapshots': [], 'days': 0, 'error': str(e)}), 200


@app.route('/traffic/delete', methods=['POST'])
@require_auth
def delete_traffic_history():
    """Delete traffic history rows.

    Body options:
      {"keep_last_days": N}   — keep last N days, delete everything older
      {"period": "all"}       — delete everything
    """
    body = request.get_json(silent=True) or {}
    TrafficDB.init()
    try:
        keep_last_days = body.get('keep_last_days')
        if keep_last_days is not None:
            keep_last_days = int(keep_last_days)
            from datetime import date as _date
            cutoff = (_date.today() - timedelta(days=keep_last_days)).isoformat()
            conn = TrafficDB._conn()
            cur = conn.execute("DELETE FROM daily_traffic WHERE date < ?", (cutoff,))
            deleted = cur.rowcount
            remaining = conn.execute("SELECT COUNT(*) FROM daily_traffic").fetchone()[0]
            conn.commit(); conn.close()
            logger.info(f"traffic/delete: keep_last={keep_last_days}d deleted={deleted} remaining={remaining}")
            return jsonify({'deleted': deleted, 'remaining': remaining,
                'message': f'Deleted {deleted} traffic days older than {keep_last_days} days. {remaining} remain.'}), 200

        if body.get('period') == 'all':
            conn = TrafficDB._conn()
            cur = conn.execute("DELETE FROM daily_traffic")
            deleted = cur.rowcount
            conn.commit(); conn.close()
            logger.info(f"traffic/delete: all deleted={deleted}")
            return jsonify({'deleted': deleted, 'remaining': 0,
                'message': f'Deleted all {deleted} traffic history rows.'}), 200

        return jsonify({'error': 'keep_last_days or period=all required'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/traffic/info', methods=['GET'])
@require_auth
def get_traffic_info():
    """Return traffic DB stats for the delete UI."""
    TrafficDB.init()
    try:
        conn = TrafficDB._conn()
        total = conn.execute("SELECT COUNT(*) FROM daily_traffic").fetchone()[0]
        if total == 0:
            conn.close()
            return jsonify({'total': 0, 'oldest': None, 'newest': None}), 200
        oldest = conn.execute("SELECT date FROM daily_traffic ORDER BY date ASC LIMIT 1").fetchone()[0]
        newest = conn.execute("SELECT date FROM daily_traffic ORDER BY date DESC LIMIT 1").fetchone()[0]
        conn.close()
        return jsonify({'total': total, 'oldest': oldest, 'newest': newest}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/uptime/reset', methods=['POST'])
@require_auth
def reset_uptime_tracking():
    """Reset local uptime tracking — wipes uptime_log.json and node_identity.txt."""
    try:
        deleted = []
        if UPTIME_FILE.exists():
            UPTIME_FILE.unlink()
            deleted.append('uptime_log.json')
        if IDENTITY_FILE.exists():
            IDENTITY_FILE.unlink()
            deleted.append('node_identity.txt')
        # Reset in-memory cache
        MetricsCollector._uptime_log_cache = None if hasattr(MetricsCollector, '_uptime_log_cache') else None
        logger.info(f"uptime/reset: deleted {deleted}")
        return jsonify({'deleted': deleted,
            'message': f'Uptime tracking reset. Deleted: {", ".join(deleted) if deleted else "nothing to delete"}'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/traffic/history', methods=['GET'])
@require_auth
def get_traffic_history():
    """Return traffic history from SQLite for charting.

    Query params:
      range = '3month' | 'year' | 'all'  (default: all)

    Data source strategy:
      - SQLite daily_traffic rows are the primary source (vnstat_daily snapshots).
      - vnstat_month_import rows fill months BEFORE the toolkit existed.
      - For any month that has both monthly-import and daily rows, daily rows win
        UNLESS the daily rows only cover a partial month — in that case we keep
        the monthly import so the total isn't understated.
      - Period totals are summed from the resulting de-duplicated rows.
    """
    try:
        rng = request.args.get('range', 'all')
        if rng == '7d':
            rows = TrafficDB.get_range(days_back=7)
        elif rng == '30d':
            rows = TrafficDB.get_range(days_back=30)
        elif rng == '90d' or rng == '3month':
            rows = TrafficDB.get_range(months_back=3)
        elif rng == '1y' or rng == 'year':
            rows = TrafficDB.get_range(months_back=12)
        else:
            rows = TrafficDB.get_range()

        totals = TrafficDB.get_totals()

        # Supplement: for the CURRENT month, replace SQLite partial-daily total
        # with the live vnstat monthly total (which is always complete).
        # This fixes the "3 Months < Month" anomaly caused by partial daily coverage.
        try:
            vnstat = MetricsCollector._get_vnstat_traffic()
            if vnstat:
                from datetime import date as _date
                today = _date.today()
                this_month = today.strftime('%Y-%m')
                MB = 1024 * 1024

                live_vpn_rx = vnstat.get('vpn_month_rx', 0) / MB
                live_vpn_tx = vnstat.get('vpn_month_tx', 0) / MB
                live_nic_rx = vnstat.get('month_rx', 0) / MB
                live_nic_tx = vnstat.get('month_tx', 0) / MB

                # Remove all rows for the current month from the SQLite result
                rows = [r for r in rows
                        if not r['date'].startswith(this_month)]

                # Inject a synthetic "current month total" row
                rows.append({
                    'date':       f"{this_month}-01",
                    'vpn_rx_mb':  round(live_vpn_rx, 2),
                    'vpn_tx_mb':  round(live_vpn_tx, 2),
                    'nic_rx_mb':  round(live_nic_rx, 2),
                    'nic_tx_mb':  round(live_nic_tx, 2),
                    'source':     'vnstat_live_month',
                })
                rows.sort(key=lambda r: r['date'])
        except Exception as _e:
            logger.debug(f"traffic/history live supplement failed: {_e}")

        # Compute period totals from final rows
        period_vpn_rx = sum(r['vpn_rx_mb'] for r in rows)
        period_vpn_tx = sum(r['vpn_tx_mb'] for r in rows)
        period_nic_rx = sum(r['nic_rx_mb'] for r in rows)
        period_nic_tx = sum(r['nic_tx_mb'] for r in rows)

        return jsonify({
            'rows':             rows,
            'range':            rng,
            'period_vpn_rx':    round(period_vpn_rx, 2),
            'period_vpn_tx':    round(period_vpn_tx, 2),
            'period_vpn_total': round(period_vpn_rx + period_vpn_tx, 2),
            'period_nic_rx':    round(period_nic_rx, 2),
            'period_nic_tx':    round(period_nic_tx, 2),
            'period_nic_total': round(period_nic_rx + period_nic_tx, 2),
            'alltime':          totals,
        }), 200
    except Exception as e:
        logger.warning(f'traffic/history error: {e}')
        return jsonify({'rows': [], 'error': str(e)}), 200


@app.route('/sessions/archive', methods=['GET'])
@require_auth
def get_sessions_archive():
    """Return sessions from SessionDB (persistent SQLite archive).
    These include sessions from before node restarts — the full history.
    The frontend uses this to fill the History tab with sessions not in
    the live TequilAPI store (which resets on each node daemon restart).

    Query params:
      limit  (int, default 200, max 500)
      offset (int, default 0)
      service_type (str, optional filter)
    """
    try:
        limit  = min(int(request.args.get('limit', 200)), 500)
        offset = int(request.args.get('offset', 0))
        svc    = request.args.get('service_type', None)

        rows = SessionDB.get_range(limit=limit, offset=offset, service_type=svc)
        stats = SessionDB.get_stats()

        # Normalize rows to match the live session format the frontend expects
        out = []
        for r in rows:
            tokens = int(r.get('tokens', 0) or 0)
            b_sent = int(r.get('bytes_sent', 0) or 0)
            b_recv = int(r.get('bytes_received', 0) or 0)
            started = r.get('started_at', '') or ''
            started_fmt = ''
            if started:
                try:
                    from datetime import timezone as _tz
                    st = datetime.fromisoformat(started.replace('Z', '+00:00'))
                    if st.tzinfo is None:
                        st = st.replace(tzinfo=_tz.utc)
                    started_fmt = st.strftime('%d/%m/%Y, %H:%M:%S')
                except Exception:
                    started_fmt = started[:16]

            dur_secs = int(r.get('duration_secs', 0) or 0)
            h = dur_secs // 3600
            m = (dur_secs % 3600) // 60
            s = dur_secs % 60
            duration_str = f"{h:02d}:{m:02d}:{s:02d}" if dur_secs > 0 else '—'

            out.append({
                'id':               r.get('id', ''),
                'consumer_id':      r.get('consumer_id', ''),
                'consumer_country': r.get('consumer_country', ''),
                'service_type':     r.get('service_type', 'unknown'),
                'status':           r.get('status', 'completed'),
                'started':          started,
                'started_fmt':      started_fmt,
                'duration':         duration_str,
                'duration_secs':    dur_secs,
                'data_in':          round(b_recv / (1024 * 1024), 2),
                'data_out':         round(b_sent / (1024 * 1024), 2),
                'data_total':       round((b_sent + b_recv) / (1024 * 1024), 2),
                'tokens':           tokens,
                'earnings_myst':    round(tokens / 1e18, 8),
                'is_paid':          tokens > 0,
                'is_active':        False,
                'bytes_pending':    False,
                'source':           'archive',  # distinguish from live sessions
            })

        return jsonify({
            'items':       out,
            'total':       stats.get('total', 0),
            'offset':      offset,
            'limit':       limit,
            'has_more':    (offset + len(out)) < stats.get('total', 0),
            'stats':       stats,
        }), 200

    except Exception as e:
        logger.warning(f'sessions/archive error: {e}')
        return jsonify({'items': [], 'total': 0, 'error': str(e)}), 200


@app.route('/sessions/db/country-debug', methods=['GET'])
@require_auth
def sessions_db_country_debug():
    """Diagnostic: show consumer_country distribution in SessionDB."""
    try:
        conn = SessionDB._conn()
        rows = conn.execute(
            """SELECT consumer_country, COUNT(*) as cnt,
                      SUM(CAST(tokens AS REAL))/1e18 as myst
               FROM sessions
               WHERE service_type != 'monitoring' AND service_type != 'wireguard'
               GROUP BY consumer_country
               ORDER BY cnt DESC LIMIT 50"""
        ).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE service_type != 'monitoring'"
        ).fetchone()[0]
        conn.close()
        result = [{'country': r['consumer_country'] or '(empty)', 'sessions': r['cnt'],
                   'myst': round(float(r['myst'] or 0), 4)} for r in rows]
        return jsonify({'total': total, 'countries': result}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/sessions/db/stats', methods=['GET'])
@require_auth
def get_session_db_stats():
    """Return SessionDB summary stats for display in Analytics card."""
    try:
        stats = SessionDB.get_stats()
        return jsonify(stats), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 200


@app.route('/sessions/delete', methods=['POST'])
@require_auth
def delete_sessions():
    """Delete session archive rows.

    Body options:
      {"keep_last_days": N}   — keep sessions started in last N days
      {"period": "all"}       — delete everything
    """
    body = request.get_json(silent=True) or {}
    SessionDB.init()
    try:
        keep_last_days = body.get('keep_last_days')
        if keep_last_days is not None:
            keep_last_days = int(keep_last_days)
            cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_last_days)).isoformat()
            conn = SessionDB._conn()
            cur = conn.execute("DELETE FROM sessions WHERE started_at < ? AND started_at != ''", (cutoff,))
            deleted = cur.rowcount
            remaining = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
            conn.commit(); conn.close()
            logger.info(f"sessions/delete: keep_last={keep_last_days}d deleted={deleted} remaining={remaining}")
            return jsonify({'deleted': deleted, 'remaining': remaining,
                'message': f'Deleted {deleted} sessions older than {keep_last_days} days. {remaining} remain.'}), 200

        if body.get('period') == 'all':
            conn = SessionDB._conn()
            cur = conn.execute("DELETE FROM sessions")
            deleted = cur.rowcount
            conn.commit(); conn.close()
            logger.info(f"sessions/delete: all deleted={deleted}")
            return jsonify({'deleted': deleted, 'remaining': 0,
                'message': f'Deleted all {deleted} sessions from archive.'}), 200

        return jsonify({'error': 'keep_last_days or period=all required'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/services/<service_id>/stop', methods=['POST'])
@require_auth
def stop_service(service_id):
    """Stop a running service via TequilAPI DELETE /services/{id}.
    Accepts optional service_type in body to resolve stale UUIDs and handle linked services.
    scraping <-> quic_scraping are always stopped together.
    """
    LINKED = {'scraping': 'quic_scraping', 'quic_scraping': 'scraping'}
    try:
        body = request.get_json() or {}
        service_type = body.get('service_type', '')
        headers = MetricsCollector.get_tequilapi_headers()
        for node_url in NODE_API_URLS:
            try:
                # Fetch current running services to resolve fresh UUIDs
                current = {}
                try:
                    sr = requests.get(f'{node_url}/services', headers=headers, timeout=5)
                    if sr.status_code == 200:
                        for s in sr.json():
                            current[s.get('type', '')] = s.get('id', '')
                except Exception:
                    pass

                # Resolve UUID: use fresh one if available, fall back to passed service_id
                target_id = current.get(service_type, service_id) if service_type else service_id

                def do_stop(sid):
                    r = requests.delete(f'{node_url}/services/{sid}', headers=headers, timeout=10)
                    return r.status_code in (200, 202, 204)

                ok = do_stop(target_id)

                # Stop linked service if applicable (scraping <-> quic_scraping)
                if service_type in LINKED:
                    linked_type = LINKED[service_type]
                    linked_id = current.get(linked_type)
                    if linked_id:
                        do_stop(linked_id)

                if ok:
                    return jsonify({'success': True, 'message': f'Service stopped'}), 200
                else:
                    return jsonify({'success': False, 'error': f'Stop failed for {target_id}'}), 200
            except Exception as e:
                return jsonify({'success': False, 'error': str(e)}), 200
        return jsonify({'success': False, 'error': 'No node available'}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 200


@app.route('/services/start', methods=['POST'])
@require_auth
def start_service():
    """Start a service via TequilAPI POST /services.
    Body: {service_type: 'wireguard'|'dvpn'|'data_transfer'|'scraping'|'noop'|'monitoring'}
    Automatically fetches provider identity from TequilAPI.
    scraping <-> quic_scraping are always started together.
    """
    LINKED = {'scraping': 'quic_scraping', 'quic_scraping': 'scraping'}
    try:
        body = request.get_json() or {}
        service_type = body.get('service_type', '')
        if not service_type:
            return jsonify({'success': False, 'error': 'service_type required'}), 200

        headers = MetricsCollector.get_tequilapi_headers()
        headers['Content-Type'] = 'application/json'

        for node_url in NODE_API_URLS:
            try:
                # Get provider identity first
                provider_id = None
                try:
                    id_resp = requests.get(f'{node_url}/identities', headers=headers, timeout=5)
                    if id_resp.status_code == 200:
                        ids = id_resp.json().get('identities', [])
                        if ids:
                            provider_id = ids[0]['id']
                except Exception:
                    pass

                def do_start(stype):
                    payload = {'type': stype}
                    if provider_id:
                        payload['provider_id'] = provider_id
                    r = requests.post(f'{node_url}/services', headers=headers, json=payload, timeout=10)
                    return r.status_code in (200, 201)

                ok = do_start(service_type)

                # Start linked service if applicable (scraping <-> quic_scraping)
                if service_type in LINKED:
                    do_start(LINKED[service_type])

                if ok:
                    return jsonify({'success': True, 'message': f'Service {service_type} started'}), 200
                else:
                    return jsonify({'success': False, 'error': f'Start failed for {service_type}'}), 200
            except Exception as e:
                return jsonify({'success': False, 'error': str(e)}), 200

        return jsonify({'success': False, 'error': 'No node available'}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 200


@app.route('/analytics/service-split', methods=['GET'])
@require_auth
def get_service_split():
    """Return per-day service type breakdown for stacked bar chart (Feature 2).
    Query param: days (default 90)
    Returns: [{date, service_type, earnings_myst, sessions, data_mb}, ...]
    """
    try:
        days = request.args.get('days', 90, type=int)
        node_id = request.args.get('node_id')
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        SessionDB.init()
        conn = SessionDB._conn()
        q = """
            SELECT
                started_at,
                service_type,
                COALESCE(tokens, 0) AS tokens,
                COALESCE(bytes_sent, 0) + COALESCE(bytes_received, 0) AS total_bytes
            FROM sessions
            WHERE started_at >= ?
              AND service_type NOT IN ('monitoring', 'noop', '')
              AND tokens > 0
        """
        params = [cutoff]
        if node_id:
            q += " AND provider_id = ?"
            params.append(node_id)
        rows = conn.execute(q, params).fetchall()
        conn.close()

        # Bucket by local date (TOOLKIT_TZ) — same as earnings chart
        from collections import defaultdict
        day_type_map = defaultdict(lambda: {'sessions': 0, 'earnings_myst': 0.0, 'data_mb': 0.0})
        for r in rows:
            try:
                t = datetime.fromisoformat(str(r[0]).replace('Z', '+00:00'))
                if t.tzinfo is None:
                    t = t.replace(tzinfo=timezone.utc)
                day = t.astimezone(TOOLKIT_TZ).strftime('%Y-%m-%d')
            except Exception:
                day = str(r[0])[:10]
            key = (day, r[1])
            day_type_map[key]['sessions']      += 1
            day_type_map[key]['earnings_myst'] += float(r[2]) / 1e18
            day_type_map[key]['data_mb']       += float(r[3]) / (1024 * 1024)

        result = sorted([
            {'date': k[0], 'service_type': k[1],
             'sessions': v['sessions'],
             'earnings_myst': round(v['earnings_myst'], 6),
             'data_mb': round(v['data_mb'], 2)}
            for k, v in day_type_map.items()
        ], key=lambda x: x['date'])

        return jsonify({'data': result, 'days': days}), 200
    except Exception as e:
        logger.error(f'service-split error: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/analytics/earnings-efficiency', methods=['GET'])
@require_auth
def get_earnings_efficiency():
    """Return per-day MYST/GB timeseries (Feature 5).
    Query param: days (default 90)
    Returns: [{date, earnings_myst, data_mb, myst_per_gb}, ...]
    """
    try:
        days = request.args.get('days', 90, type=int)
        node_id = request.args.get('node_id')
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        SessionDB.init()
        conn = SessionDB._conn()
        q = """
            SELECT
                started_at,
                COALESCE(tokens, 0) AS tokens,
                COALESCE(bytes_sent, 0) + COALESCE(bytes_received, 0) AS total_bytes
            FROM sessions
            WHERE started_at >= ?
              AND service_type NOT IN ('monitoring', 'noop', '')
              AND tokens > 0
              AND (bytes_sent > 0 OR bytes_received > 0)
        """
        params = [cutoff]
        if node_id:
            q += " AND provider_id = ?"
            params.append(node_id)
        rows = conn.execute(q, params).fetchall()
        conn.close()

        # Bucket by local date (TOOLKIT_TZ)
        from collections import defaultdict
        day_map = defaultdict(lambda: {'earnings_myst': 0.0, 'data_mb': 0.0})
        for r in rows:
            try:
                t = datetime.fromisoformat(str(r[0]).replace('Z', '+00:00'))
                if t.tzinfo is None:
                    t = t.replace(tzinfo=timezone.utc)
                day = t.astimezone(TOOLKIT_TZ).strftime('%Y-%m-%d')
            except Exception:
                day = str(r[0])[:10]
            day_map[day]['earnings_myst'] += float(r[1]) / 1e18
            day_map[day]['data_mb']       += float(r[2]) / (1024 * 1024)

        result = []
        for day in sorted(day_map.keys()):
            v = day_map[day]
            data_gb = v['data_mb'] / 1024 if v['data_mb'] else 0
            myst_per_gb = round(v['earnings_myst'] / data_gb, 6) if data_gb > 0 else None
            result.append({'date': day, 'earnings_myst': round(v['earnings_myst'], 6),
                           'data_mb': round(v['data_mb'], 2), 'myst_per_gb': myst_per_gb})
        return jsonify({'data': result, 'days': days}), 200
    except Exception as e:
        logger.error(f'earnings-efficiency error: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/settle/history', methods=['GET'])
@require_auth
def get_settle_history():
    """Return settlement history from TequilAPI + on-chain wallet balance from Polygonscan.

    TequilAPI GET /settle/history returns:
      items[]: { settled_at, amount (wei), beneficiary, tx_hash, error, hermes_id, provider_id }

    On-chain wallet balance fetched from Polygonscan free API (no key needed).
    MYST token contract on Polygon: 0x1379e8886a944d2d9d440b3d88df536aea08d9f3
    """
    try:
        headers = MetricsCollector.get_tequilapi_headers()
        settlements = []
        beneficiary = None
        wallet_balance_myst = None

        for node_url in NODE_API_URLS:
            try:
                # Paginate through all pages until empty
                page = 1
                while True:
                    resp = requests.get(
                        f'{node_url}/transactor/settle/history',
                        headers=headers, timeout=8,
                        params={'page_size': 50, 'page': page}
                    )
                    if resp.status_code != 200:
                        break
                    data = resp.json()
                    items = data.get('items', data if isinstance(data, list) else [])
                    if not items:
                        break
                    for item in items:
                        raw_amount = item.get('amount', 0) or 0
                        try:
                            # TequilAPI may return amount as:
                            #   int/float in wei (large number like 5000000000000000000)
                            #   int/float already in MYST (small number like 5.0)
                            #   dict with 'ether' key: {"ether": "5.0", "wei": "5000000000000000000"}
                            #   string representation of any of the above
                            if isinstance(raw_amount, dict):
                                if 'ether' in raw_amount:
                                    myst_amt = round(float(raw_amount['ether']), 6)
                                elif 'wei' in raw_amount:
                                    myst_amt = round(int(raw_amount['wei']) / 1e18, 6)
                                else:
                                    myst_amt = 0.0
                            else:
                                amt_str = str(raw_amount).split('.')[0]
                                amt_int = int(amt_str) if amt_str else 0
                                myst_amt = round(amt_int / 1e18, 6) if amt_int > 1e15 else round(float(raw_amount), 6)
                        except Exception:
                            myst_amt = 0.0

                        tx_hash  = item.get('tx_hash', '')  or item.get('txHash', '')
                        settled_at = item.get('settled_at', '') or item.get('settledAt', '')
                        ben      = item.get('beneficiary', '') or item.get('Beneficiary', '')
                        if page == 1 and len(settlements) == 0:
                            logger.info(f"settle/history sample item keys={list(item.keys())} amount_raw={repr(raw_amount)} myst_amt={myst_amt}")
                        if ben and not beneficiary:
                            beneficiary = ben

                        settlements.append({
                            'settled_at':    settled_at[:19].replace('T', ' ') if settled_at else '—',
                            'amount_myst':   myst_amt,
                            'beneficiary':   ben,
                            'tx_hash':       tx_hash,
                            'polygonscan_url': f'https://polygonscan.com/tx/{tx_hash}' if tx_hash else None,
                            'error':         item.get('error', '') or '',
                        })

                    # Stop only when API returns empty page
                    # (TequilAPI may ignore page_size param and return fewer items)
                    if len(items) == 0:
                        break
                    page += 1
                    if page > 20:  # safety cap — max 1000 settlements
                        break
                break
            except Exception as e:
                logger.debug(f'settle/history fetch error: {e}')

        # Sort newest first
        settlements.sort(key=lambda x: x.get('settled_at', ''), reverse=True)

        # Fallback: use beneficiary from setup.json if not found in settlement history
        if not beneficiary:
            beneficiary = setup_config.get('beneficiary_address', '')

        # Fetch on-chain MYST balance
        # Supports both Etherscan key (via v2 API chainid=137) and Polygonscan key
        # Re-reads setup.json each call so key changes take effect without restart
        # Cached 1 hour — rate-limited state cached 5 min
        MYST_CONTRACT = '0x1379e8886a944d2d9d440b3d88df536aea08d9f3'
        if beneficiary:
            import time as _time
            global _polygonscan_cache
            _live_api_key = ''
            try:
                _live_cfg = json.loads(setup_config_path.read_text()) if setup_config_path.exists() else {}
                _live_api_key = _live_cfg.get('polygonscan_api_key', '')
            except Exception:
                _live_api_key = setup_config.get('polygonscan_api_key', '')

            now_ts = _time.time()
            _cache_age = now_ts - _polygonscan_cache['timestamp']
            _cache_match = _polygonscan_cache['address'] == beneficiary
            if _cache_match and _polygonscan_cache['balance'] is not None and _cache_age < POLYGONSCAN_CACHE_TTL:
                wallet_balance_myst = _polygonscan_cache['balance']
                logger.debug(f'Wallet balance: cached {wallet_balance_myst} MYST ({int(_cache_age)}s old)')
            elif _cache_match and _polygonscan_cache['balance'] is None and _cache_age < 300:
                logger.debug('Wallet balance: rate-limited recently, skipping (5 min cooldown)')
            else:
                def _fetch_balance(api_key):
                    """Try Etherscan v2 (chainid=137) first, fallback to Polygonscan."""
                    # Strategy 1: Etherscan v2 API with Polygon chainid — works with Etherscan keys
                    if api_key:
                        try:
                            r = requests.get(
                                'https://api.etherscan.io/v2/api',
                                params={
                                    'chainid': '137',
                                    'module': 'account',
                                    'action': 'tokenbalance',
                                    'contractaddress': MYST_CONTRACT,
                                    'address': beneficiary,
                                    'tag': 'latest',
                                    'apikey': api_key,
                                },
                                timeout=10
                            )
                            if r.status_code == 200:
                                d = r.json()
                                if d.get('status') == '1' and str(d.get('result', '')).isdigit():
                                    return round(int(d['result']) / 1e18, 6), None
                                msg = str(d.get('message', '')) + str(d.get('result', ''))
                                if 'rate limit' in msg.lower():
                                    return None, 'rate_limit'
                                logger.debug(f'Etherscan v2: {d.get("message")} {d.get("result","")}')
                        except Exception as e:
                            logger.debug(f'Etherscan v2 error: {e}')

                    # Strategy 2: Polygonscan API (works with Polygonscan keys or no key)
                    try:
                        params2 = {
                            'module': 'account',
                            'action': 'tokenbalance',
                            'contractaddress': MYST_CONTRACT,
                            'address': beneficiary,
                            'tag': 'latest',
                        }
                        if api_key:
                            params2['apikey'] = api_key
                        r2 = requests.get('https://api.polygonscan.com/api', params=params2, timeout=10)
                        if r2.status_code == 200:
                            d2 = r2.json()
                            if d2.get('status') == '1' and str(d2.get('result', '')).isdigit():
                                return round(int(d2['result']) / 1e18, 6), None
                            msg2 = str(d2.get('message', '')) + str(d2.get('result', ''))
                            if 'rate limit' in msg2.lower():
                                return None, 'rate_limit'
                    except Exception as e:
                        logger.debug(f'Polygonscan error: {e}')
                    return None, 'error'

                bal, err = _fetch_balance(_live_api_key)
                if bal is not None:
                    wallet_balance_myst = bal
                    _polygonscan_cache.update({'balance': bal, 'timestamp': now_ts, 'address': beneficiary})
                elif err == 'rate_limit':
                    _polygonscan_cache.update({'balance': None, 'timestamp': now_ts, 'address': beneficiary})
                    if _polygonscan_cache.get('balance') is not None:
                        wallet_balance_myst = _polygonscan_cache['balance']
                    logger.debug('Wallet balance: rate limited on both APIs — 5 min cooldown')
                else:
                    logger.debug('Wallet balance: both APIs failed')

        total_settled = round(sum(s['amount_myst'] for s in settlements if not s['error']), 6)

        # Fetch on-chain token transfers from Polygonscan/Etherscan
        # More complete than TequilAPI — shows all 40 blockchain transactions
        onchain_txs = []
        if beneficiary and _live_api_key:
            try:
                def _fetch_tokentx(api_key):
                    # Try Etherscan v2 first (chainid=137 = Polygon)
                    for url, params in [
                        ('https://api.etherscan.io/v2/api', {
                            'chainid': '137', 'module': 'account', 'action': 'tokentx',
                            'contractaddress': MYST_CONTRACT, 'address': beneficiary,
                            'sort': 'desc', 'apikey': api_key,
                        }),
                        ('https://api.polygonscan.com/api', {
                            'module': 'account', 'action': 'tokentx',
                            'contractaddress': MYST_CONTRACT, 'address': beneficiary,
                            'sort': 'desc', 'apikey': api_key,
                        }),
                    ]:
                        try:
                            r = requests.get(url, params=params, timeout=10)
                            if r.status_code == 200:
                                d = r.json()
                                if d.get('status') == '1' and isinstance(d.get('result'), list):
                                    return d['result']
                        except Exception as e:
                            logger.debug(f'tokentx fetch error {url}: {e}')
                    return []

                raw_txs = _fetch_tokentx(_live_api_key)
                ben_lower = beneficiary.lower()
                for tx in raw_txs:
                    try:
                        val_wei = int(tx.get('value', 0) or 0)
                        val_myst = round(val_wei / 1e18, 6)
                        ts = int(tx.get('timeStamp', 0) or 0)
                        import datetime as _dt
                        dt_str = _dt.datetime.utcfromtimestamp(ts).strftime('%Y-%m-%d %H:%M') if ts else '—'
                        tx_hash = tx.get('hash', '')
                        direction = 'in' if tx.get('to', '').lower() == ben_lower else 'out'
                        onchain_txs.append({
                            'date':             dt_str,
                            'amount_myst':      val_myst,
                            'direction':        direction,
                            'tx_hash':          tx_hash,
                            'polygonscan_url':  f'https://polygonscan.com/tx/{tx_hash}' if tx_hash else None,
                            'from':             tx.get('from', ''),
                            'to':               tx.get('to', ''),
                        })
                    except Exception:
                        pass
            except Exception as e:
                logger.debug(f'on-chain tx fetch error: {e}')

        total_onchain = round(sum(t['amount_myst'] for t in onchain_txs if t['direction'] == 'in'), 6)

        return jsonify({
            'settlements':      settlements,
            'total_settled':    total_settled,
            'count':            len(settlements),
            'onchain_txs':      onchain_txs,
            'total_onchain':    total_onchain,
            'onchain_count':    len(onchain_txs),
            'beneficiary':      beneficiary or '',
            'wallet_balance':   wallet_balance_myst,
            'polygonscan_wallet': f'https://polygonscan.com/token/{MYST_CONTRACT}?a={beneficiary}' if beneficiary else None,
        }), 200

    except Exception as e:
        logger.warning(f'settle/history error: {e}')
        return jsonify({'settlements': [], 'error': str(e)}), 200


@app.route('/system-health', methods=['GET'])
@require_auth
def get_system_health():
    """System health scan results"""
    with metrics_lock:
        data = copy.deepcopy(metrics_cache)
    return jsonify(data.get('systemHealth', {'overall': 'unknown', 'subsystems': []})), 200


@app.route('/system-health/fix', methods=['POST'])
@require_auth
def fix_system_health():
    """Run system health fixes. POST body: {"subsystem": "all"} or {"subsystem": "conntrack"}"""
    if not system_health:
        return jsonify({'error': 'System health module not available'}), 500

    body = request.get_json(silent=True) or {}
    subsystem = body.get('subsystem', 'all')

    # Cooldown: prevent hammering fixes — 30s per subsystem, 60s for "all"
    now = time.time()
    cooldown_key = f'fix_{subsystem}'
    last_fix = getattr(fix_system_health, '_cooldowns', {}).get(cooldown_key, 0)
    cooldown = 60 if subsystem == 'all' else 30
    if now - last_fix < cooldown:
        remaining = int(cooldown - (now - last_fix))
        return jsonify({'error': f'Fix cooldown active — wait {remaining}s before retrying', 'cooldown': remaining}), 429

    if not hasattr(fix_system_health, '_cooldowns'):
        fix_system_health._cooldowns = {}
    fix_system_health._cooldowns[cooldown_key] = now

    if subsystem == 'all':
        result = system_health.fix_all()
    else:
        result = system_health.fix_one(subsystem)

    return jsonify(result), 200


@app.route('/system-health/persist', methods=['POST'])
@require_auth
def persist_system_health():
    """Lock health settings to survive reboots.
    POST body: {} → persist all,  {"subsystem": "conntrack"} → persist one.
    """
    if not system_health:
        return jsonify({'error': 'System health module not available'}), 500
    body = request.get_json(silent=True) or {}
    subsystem = body.get('subsystem', 'all')
    if subsystem and subsystem != 'all':
        result = system_health.persist_one(subsystem)
    else:
        result = system_health.persist_all()
    return jsonify(result), 200


@app.route('/system-health/unpersist', methods=['POST'])
@require_auth
def unpersist_system_health():
    """Remove persisted health settings, revert to defaults on reboot.
    POST body: {} → unpersist all,  {"subsystem": "conntrack"} → unpersist one.
    """
    if not system_health:
        return jsonify({'error': 'System health module not available'}), 500
    body = request.get_json(silent=True) or {}
    subsystem = body.get('subsystem', 'all')
    if subsystem and subsystem != 'all':
        result = system_health.unpersist_one(subsystem)
    else:
        result = system_health.unpersist_all()
    return jsonify(result), 200


@app.route('/system-health/scan', methods=['POST'])
@require_auth
def force_health_scan():
    """Force an immediate health scan (resets the cache timer)."""
    if not system_health:
        return jsonify({'error': 'System health module not available'}), 500
    try:
        result = system_health.scan_all()
        # Push directly into cache so next GET reflects it
        with metrics_lock:
            metrics_cache['systemHealth'] = result
        MetricsCollector._health_last_scan = 0  # Reset timer so next poll also refreshes
        return jsonify(result), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ============ NODE CONTROL ENDPOINTS ============


def _invalidate_metric_cache():
    """Force both polling tiers to refresh on next cycle.
    Call after any operation that changes node state (restart, config apply)."""
    global _tier_slow_last, _tier_medium_last
    _tier_slow_last = 0
    _tier_medium_last = 0


@app.route('/node/restart', methods=['POST'])
@require_auth
def restart_node():
    """Restart the Mysterium node service.
    Tries systemctl first (most common), then service, then docker, then TequilAPI stop/start."""
    actions = []
    try:
        # Strategy 1: systemctl (most common — bare-metal/VM installs)
        result = subprocess.run(
            ['sudo', '-n', 'systemctl', 'restart', 'mysterium-node'],
            capture_output=True, timeout=30, text=True
        )
        if result.returncode == 0:
            actions.append('Restarted via systemctl')
            time.sleep(5)
            _invalidate_metric_cache()
            return jsonify({'success': True, 'method': 'systemctl', 'actions': actions}), 200

        # Strategy 2: service command
        result = subprocess.run(
            ['sudo', '-n', 'service', 'mysterium-node', 'restart'],
            capture_output=True, timeout=30, text=True
        )
        if result.returncode == 0:
            actions.append('Restarted via service command')
            time.sleep(5)
            _invalidate_metric_cache()
            return jsonify({'success': True, 'method': 'service', 'actions': actions}), 200

        # Strategy 3: Docker — find and restart the myst container
        for container_name in ('myst', 'mysterium', 'mysterium-node', 'myst-node'):
            result = subprocess.run(
                ['docker', 'restart', container_name],
                capture_output=True, timeout=60, text=True
            )
            if result.returncode == 0:
                actions.append(f'Restarted Docker container: {container_name}')
                time.sleep(8)
                _invalidate_metric_cache()
                return jsonify({'success': True, 'method': 'docker', 'actions': actions}), 200

        # Strategy 3b: Docker — find by image name
        try:
            ps_result = subprocess.run(
                ['docker', 'ps', '--format', '{{.ID}} {{.Image}}'],
                capture_output=True, timeout=10, text=True
            )
            if ps_result.returncode == 0:
                for line in ps_result.stdout.strip().split('\n'):
                    parts = line.split()
                    if len(parts) >= 2 and 'myst' in parts[1].lower():
                        container_id = parts[0]
                        result = subprocess.run(
                            ['docker', 'restart', container_id],
                            capture_output=True, timeout=60, text=True
                        )
                        if result.returncode == 0:
                            actions.append(f'Restarted Docker container: {container_id} ({parts[1]})')
                            time.sleep(8)
                            _invalidate_metric_cache()
                            return jsonify({'success': True, 'method': 'docker', 'actions': actions}), 200
        except FileNotFoundError:
            pass  # Docker not installed

        # Strategy 4: docker-compose
        for compose_cmd in (['docker-compose', 'restart'], ['docker', 'compose', 'restart']):
            try:
                result = subprocess.run(
                    compose_cmd,
                    capture_output=True, timeout=60, text=True
                )
                if result.returncode == 0:
                    actions.append(f'Restarted via {" ".join(compose_cmd)}')
                    return jsonify({'success': True, 'method': 'docker-compose', 'actions': actions}), 200
            except FileNotFoundError:
                continue

        # Strategy 5: TequilAPI stop (node auto-restarts via systemd/docker)
        headers = MetricsCollector.get_tequilapi_headers()
        for node_url in NODE_API_URLS:
            try:
                resp = requests.post(f'{node_url}/stop', headers=headers, timeout=10)
                if resp.status_code in (200, 202):
                    actions.append(f'Sent stop to {node_url}')
                    time.sleep(3)
                    # Node should restart itself via systemd after stop
            except Exception:
                pass

        if actions:
            return jsonify({'success': True, 'method': 'tequilapi', 'actions': actions}), 200

        return jsonify({
            'success': False,
            'error': 'Could not restart — sudo permission required',
            'actions': actions,
            'hint': 'Fix: run "sudo visudo" and add: your_user ALL=(ALL) NOPASSWD: /bin/systemctl restart mysterium-node\n'
                    'Or manually: sudo systemctl restart mysterium-node\n'
                    'For Docker: docker restart myst | docker-compose restart'
        }), 500

    except Exception as e:
        logger.error(f"Node restart error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/node/test', methods=['POST'])
@require_auth
def test_node():
    """Real-time node reachability test via Discovery API — bypasses cache.
    Fleet: pass {toolkit_url} to test a remote node via its toolkit backend.
    Local: no body needed — uses cached identity.
    """
    try:
        from datetime import datetime as _dt
        body = request.get_json() or {}
        target_toolkit_url = body.get('toolkit_url', None)

        wallet = ''
        try:
            if target_toolkit_url:
                # Fleet mode — fetch identity from remote toolkit peer/data
                _tk_headers = {}
                _reg_entry = next((n for n in _node_registry
                    if n.get('toolkit_url', '').rstrip('/') == target_toolkit_url.rstrip('/')), None)
                if _reg_entry and _reg_entry.get('toolkit_api_key'):
                    _tk_headers['Authorization'] = f"Bearer {_reg_entry['toolkit_api_key']}"
                try:
                    _pd = requests.get(f'{target_toolkit_url.rstrip("/")}/peer/data',
                                       headers=_tk_headers, timeout=6)
                    if _pd.status_code == 200:
                        _pd_data = _pd.json()
                        wallet = (_pd_data.get('node_status') or {}).get('identity', '') or                                  (_pd_data.get('earnings') or {}).get('wallet_address', '')
                except Exception:
                    pass
            else:
                # Local node — use cached identity
                if _identity_cache.get('address'):
                    wallet = _identity_cache['address']
                else:
                    headers = MetricsCollector.get_tequilapi_headers()
                    for node_url in NODE_API_URLS:
                        id_resp = requests.get(f'{node_url}/identities', headers=headers, timeout=5)
                        if id_resp.status_code == 200:
                            ids = id_resp.json().get('identities', [])
                            if ids:
                                wallet = ids[0]['id']
                                _identity_cache['address'] = wallet
                                _identity_cache['ts'] = time.time()
                                break
        except Exception:
            pass

        if not wallet:
            return jsonify({'visible': False, 'error': 'Node identity not available'}), 400

        result = MetricsCollector.get_node_quality(wallet)  # always fresh — not cached
        ts = _dt.now().isoformat(timespec='seconds')

        if not result.get('available'):
            # Fallback: check if node is at least locally reachable via TequilAPI
            node_reachable = False
            try:
                hc_resp = requests.get(
                    f'{NODE_API_URL}/healthcheck',
                    headers=MetricsCollector.get_tequilapi_headers(), timeout=3
                )
                node_reachable = hc_resp.status_code == 200
            except Exception:
                pass

            error_msg = result.get('error') or 'Node not found in Discovery network'
            if node_reachable:
                error_msg += ' — node is online locally but not yet indexed by Discovery (can take 10-15 min after start or reclaim)'

            return jsonify({
                'visible': False,
                'node_online': node_reachable,
                'error': error_msg,
                'timestamp': ts,
            }), 200

        services_out = [
            {
                'service_type':      s.get('service_type'),
                'monitoring_failed': s.get('monitoring_failed'),
                'quality_score':     s.get('quality_score'),
                'uptime_net_pct':    s.get('uptime_net_pct'),
                'latency_ms':        s.get('latency_ms'),
                'bandwidth_mbps':    s.get('bandwidth_mbps'),
            }
            for s in result.get('services', [])
        ]

        return jsonify({
            'visible':        True,
            'monitoring_ok':  not result.get('monitoring_failed', True),
            'quality_score':  result.get('quality_score'),
            'uptime_24h_net': result.get('uptime_24h_net'),
            'latency_ms':     result.get('latency_ms'),
            'bandwidth_mbps': result.get('bandwidth_mbps'),
            'services':       services_out,
            'error':          None,
            'timestamp':      ts,
        }), 200

    except Exception as e:
        logger.error(f'node/test error: {e}')
        return jsonify({'visible': False, 'error': str(e)}), 500


@app.route('/node/settle', methods=['POST'])
@require_auth
def settle_earnings():
    """Trigger MYST earnings settlement via TequilAPI transactor.
    Moves unsettled earnings into the payment channel (settled balance)."""
    try:
        headers = MetricsCollector.get_tequilapi_headers()

        # Fetch identity — single call gives us address, unsettled balance AND hermes_id.
        # hermes_id is REQUIRED in the settle body. Wrong/missing hermes_id gives:
        # "nothing to settle for the given provider".
        identity_address = None
        unsettled        = 0.0
        hermes_id        = None

        for node_url in NODE_API_URLS:
            try:
                # Step 1: get identity address
                resp = requests.get(f'{node_url}/identities', headers=headers, timeout=5)
                if resp.status_code != 200:
                    continue
                identities = resp.json().get('identities', [])
                if not identities:
                    continue
                identity_address = identities[0].get('id', '')
                if not identity_address:
                    continue

                # Step 2: get full identity details (unsettled + hermes_id in one call)
                resp2 = requests.get(
                    f'{node_url}/identities/{identity_address}',
                    headers=headers, timeout=5,
                )
                if resp2.status_code == 200:
                    idata = resp2.json()
                    et = idata.get('earnings_tokens', {})
                    if isinstance(et, dict) and 'ether' in et:
                        unsettled = float(et['ether'])
                    elif 'earnings' in idata:
                        unsettled = MetricsCollector._wei_to_myst(idata['earnings'])
                    hermes_id = idata.get('hermes_id', '')
                    logger.info(
                        f'Settle: id={identity_address[:10]}… '
                        f'unsettled={round(unsettled,4)} hermes={hermes_id}'
                    )
                break
            except Exception as ex:
                logger.warning(f'Settle identity fetch error ({node_url}): {ex}')
                continue

        if not identity_address:
            return jsonify({'success': False, 'error': 'Could not find node identity'}), 500

        if unsettled <= 0:
            return jsonify({
                'success': False,
                'error': 'No unsettled earnings to settle',
                'unsettled': 0.0,
            }), 400

        # Trigger settlement — try all known TequilAPI endpoint variants in order.
        # Mysterium node v1.37.x: POST /transactor/settle/sync
        # The body MUST include hermes_id (the Hermes smart contract address).
        # Without it the node returns: "nothing to settle for the given provider".
        # hermes_id is fetched above from GET /identities/{id}.
        if not hermes_id:
            # Fallback: known Mysterium mainnet Hermes contract address
            hermes_id = '0x80Ed28d84792d8b153bf2F25F0C4B7a1381dE4ab'
            logger.warning(f'Settle: hermes_id not in identity response, using fallback: {hermes_id}')

        settle_data = {
            'provider_id': identity_address,
            'hermes_id':   hermes_id,
        }
        settle_attempts = [
            (f'{node_url}/transactor/settle/sync', settle_data, 120, 'sync'),
            (f'{node_url}/transactor/settle',      settle_data, 30,  'async'),
        ]

        for node_url in NODE_API_URLS:
            try:
                last_status = None
                last_body   = ''
                for url, payload, tout, variant in settle_attempts:
                    try:
                        resp = requests.post(url, headers=headers,
                                             json=payload, timeout=tout)
                        last_status = resp.status_code
                        last_body   = resp.text[:300]
                        logger.info(f'Settle attempt [{variant}] → {resp.status_code}: {url}')
                        if resp.status_code in (200, 202):
                            label = 'initiated' if variant == 'sync' else                                     'queued'    if variant == 'async' else 'requested'
                            return jsonify({
                                'success':  True,
                                'identity': identity_address,
                                'amount':   round(unsettled, 4),
                                'message':  f'Settlement {label} for {round(unsettled, 4)} MYST ({variant})',
                                'variant':  variant,
                            }), 200
                            # Bust caches so next poll shows updated balance
                            _polygonscan_cache['timestamp'] = 0
                            global _tier_slow_last
                            _tier_slow_last = 0
                    except requests.exceptions.Timeout:
                        logger.warning(f'Settle [{variant}] timed out: {url}')
                        # Sync settle timing out may still succeed on-chain
                        if variant == 'sync':
                            return jsonify({
                                'success': False,
                                'error': 'Settlement timed out — may still be processing on-chain',
                                'hint':  'Check settlement status in NodeUI in a few minutes',
                            }), 504
                        continue

                return jsonify({
                    'success': False,
                    'error': (f'All settle endpoints returned errors. '
                              f'Last: HTTP {last_status}: {last_body}'),
                    'hint':  ('Run on your node: '
                              'curl -s -u myst:myst http://localhost:4449/tequilapi/doc '
                              '| python3 -c "import sys,json; d=json.load(sys.stdin); '
                              '[print(p) for p in d[\"paths\"] if \"settle\" in p]"'),
                }), 500

            except requests.exceptions.Timeout:
                return jsonify({
                    'success': False,
                    'error': 'Settlement timed out — may still be processing on-chain',
                    'hint': 'Check settlement status in a few minutes',
                }), 504
            except Exception as e:
                logger.error(f"Settle error for {node_url}: {e}")
                continue

        return jsonify({'success': False, 'error': 'Could not reach any node for settlement'}), 500

    except Exception as e:
        logger.error(f"Settle error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ============ NODE CONFIG ROUTES ============

# TOML config file path (same on all standard installs)
NODE_CONFIG_TOML = Path('/etc/mysterium-node/config-mainnet.toml')

# Canonical config keys and their metadata
# dual_key: if set, a second key is written simultaneously (balance-check-interval quirk)
NODE_CONFIG_KEYS = {
    'payments.zero-stake-unsettled-amount': {
        'toml_section': 'payments', 'toml_key': 'zero-stake-unsettled-amount',
        'unit': 'MYST', 'type': 'float', 'node_default': '5.0',
        'description': 'Auto-settle threshold (zero-stake)',
    },
    'payments.unsettled-max-amount': {
        'toml_section': 'payments', 'toml_key': 'unsettled-max-amount',
        'unit': 'MYST', 'type': 'float', 'node_default': '10.0',
        'description': 'Maximum unsettled MYST before forced settlement',
    },
    'payments.min_promise_amount': {
        'toml_section': 'payments', 'toml_key': 'min_promise_amount',
        'unit': 'MYST', 'type': 'float', 'node_default': '0.05',
        'description': 'Minimum promise value to accept a session',
    },
    'payments.provider.invoice-frequency': {
        'toml_section': 'payments.provider', 'toml_key': 'invoice-frequency',
        'unit': 'seconds', 'type': 'int', 'node_default': '60',
        'description': 'How often to send payment invoices during a session',
    },
    'pingpong.balance-check-interval': {
        'toml_section': 'pingpong', 'toml_key': 'balance-check-interval',
        'unit': 'seconds', 'type': 'int', 'node_default': '90',
        'description': 'Consumer balance poll interval (promise settler)',
        # Also writes session.pingpong.balance-check-interval as Go duration
        'dual_key': 'session.pingpong.balance-check-interval',
    },
    'pingpong.promise-wait-timeout': {
        'toml_section': 'pingpong', 'toml_key': 'promise-wait-timeout',
        'unit': 'seconds', 'type': 'int', 'node_default': '180',
        'description': 'How long to wait for a consumer promise before timeout',
    },
    'payments.settle.min-amount': {
        'toml_section': 'payments.settle', 'toml_key': 'min-amount',
        'unit': 'MYST', 'type': 'float', 'node_default': '1.0',
        'description': 'Minimum balance required for manual settlement',
    },
}

# Presets
NODE_CONFIG_PRESETS = {
    'defaults': {
        'label': 'Node Defaults',
        'values': {
            'payments.zero-stake-unsettled-amount': '5.0',
            'payments.unsettled-max-amount': '10.0',
            'payments.min_promise_amount': '0.05',
            'payments.provider.invoice-frequency': '60',
            'pingpong.balance-check-interval': '90',
            'pingpong.promise-wait-timeout': '180',
            'payments.settle.min-amount': '1.0',
        }
    },
    'high-traffic': {
        'label': 'High Load · 50+ Sessions (rate limiting relief)',
        'values': {
            'payments.zero-stake-unsettled-amount': '10',
            'payments.unsettled-max-amount': '25',
            'payments.min_promise_amount': '0.01',
            'payments.provider.invoice-frequency': '300',
            'pingpong.balance-check-interval': '300',
            'pingpong.promise-wait-timeout': '600',
            'payments.settle.min-amount': '0.01',
        }
    },
}


def _parse_toml_simple(toml_path):
    """Minimal TOML parser — reads flat keys and one-level sections.
    Returns dict of section.key -> value strings.
    Uses tomllib (3.11+) or falls back to manual parsing."""
    result = {}
    try:
        if hasattr(__import__('builtins'), '__loader__'):
            pass
        import sys
        if sys.version_info >= (3, 11):
            import tomllib
            with open(toml_path, 'rb') as f:
                data = tomllib.load(f)
        else:
            try:
                import tomli as tomllib
                with open(toml_path, 'rb') as f:
                    data = tomllib.load(f)
            except ImportError:
                data = None

        if data is not None:
            def flatten(d, prefix=''):
                for k, v in d.items():
                    full = f'{prefix}.{k}' if prefix else k
                    if isinstance(v, dict):
                        flatten(v, full)
                    else:
                        result[full] = str(v)
            flatten(data)
            return result
    except Exception:
        pass

    # Manual line-by-line fallback (handles the known TOML structure)
    try:
        section = ''
        with open(toml_path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if line.startswith('['):
                    section = line.strip('[]').strip()
                    continue
                if '=' in line:
                    k, _, v = line.partition('=')
                    k = k.strip()
                    v = v.strip().strip('"')
                    full_key = f'{section}.{k}' if section else k
                    result[full_key] = v
    except Exception as e:
        logger.warning(f"TOML parse fallback failed: {e}")

    return result


def _seconds_to_duration(seconds):
    """Convert integer seconds to Go duration string (e.g. 300 -> '5m', 600 -> '10m')."""
    try:
        s = int(seconds)
        if s % 60 == 0:
            return f'{s // 60}m'
        return f'{s}s'
    except Exception:
        return str(seconds)


def _run_myst_config_set(key, value):
    """Run myst config set KEY VALUE. Returns (success, method, error)."""
    # Try sudo -n first (passwordless sudo configured)
    for cmd_prefix in (['sudo', '-n'], []):
        try:
            cmd = cmd_prefix + ['myst', 'config', 'set', key, str(value)]
            result = subprocess.run(cmd, capture_output=True, timeout=15, text=True)
            if result.returncode == 0:
                return True, 'myst-subprocess', None
        except FileNotFoundError:
            continue
        except subprocess.TimeoutExpired:
            return False, None, 'myst config set timed out'
        except Exception as e:
            continue
    return False, None, 'myst binary not found or sudo permission denied'


@app.route('/node/config/current', methods=['GET'])
@require_auth
def get_node_config():
    """Read current payment config values from TOML file.
    Returns live values for all 7 tunable keys plus preset definitions."""
    try:
        toml_data = _parse_toml_simple(NODE_CONFIG_TOML) if NODE_CONFIG_TOML.exists() else {}

        current = {}
        for key, meta in NODE_CONFIG_KEYS.items():
            # Try section.key first, then bare key
            toml_lookup = f"{meta['toml_section']}.{meta['toml_key']}"
            raw = toml_data.get(toml_lookup) or toml_data.get(meta['toml_key'])

            if raw is not None:
                # Normalise Go duration strings to seconds for display
                if meta['unit'] == 'seconds' and isinstance(raw, str):
                    if raw.endswith('m'):
                        try:
                            raw = str(int(raw[:-1]) * 60)
                        except ValueError:
                            pass
                    elif raw.endswith('s'):
                        raw = raw[:-1]
                current[key] = raw
            else:
                current[key] = meta['node_default']
                current[f'{key}.__source'] = 'default'

        return jsonify({
            'success': True,
            'current': current,
            'presets': NODE_CONFIG_PRESETS,
            'toml_exists': NODE_CONFIG_TOML.exists(),
            'toml_path': str(NODE_CONFIG_TOML),
        }), 200

    except Exception as e:
        logger.error(f"Node config read error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/node/config/set', methods=['POST'])
@require_auth
def set_node_config():
    """Set one payment config key via myst config set.
    Handles dual-write for balance-check-interval automatically.
    Body: {key, value}"""
    try:
        data = request.get_json() or {}
        key = data.get('key', '').strip()
        value = str(data.get('value', '')).strip()

        if not key or not value:
            return jsonify({'success': False, 'error': 'key and value are required'}), 400

        if key not in NODE_CONFIG_KEYS:
            return jsonify({'success': False,
                            'error': f'Unknown key: {key}. Allowed: {list(NODE_CONFIG_KEYS.keys())}'}), 400

        meta = NODE_CONFIG_KEYS[key]

        # Validate type loosely — reject obviously bad input
        try:
            if meta['type'] == 'float':
                float(value)
            elif meta['type'] == 'int':
                int(float(value))
                value = str(int(float(value)))
        except ValueError:
            return jsonify({'success': False,
                            'error': f'Invalid value "{value}" for {key} (expected {meta["type"]})'}), 400

        results = []

        # Primary write
        ok, method, err = _run_myst_config_set(key, value)
        results.append({'key': key, 'value': value, 'success': ok, 'error': err})

        # Dual write for balance-check-interval
        if ok and meta.get('dual_key'):
            dual_key = meta['dual_key']
            dual_value = _seconds_to_duration(value)
            ok2, _, err2 = _run_myst_config_set(dual_key, dual_value)
            results.append({'key': dual_key, 'value': dual_value, 'success': ok2, 'error': err2})

        overall_success = all(r['success'] for r in results)

        return jsonify({
            'success': overall_success,
            'method': method,
            'results': results,
            'restart_required': True,
            'hint': '' if overall_success else
                    'Ensure myst is in PATH and sudo NOPASSWD is set for myst. '
                    'Run: sudo visudo  →  add: your_user ALL=(ALL) NOPASSWD: /usr/bin/myst'
        }), 200 if overall_success else 500

    except Exception as e:
        logger.error(f"Node config set error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/node/config/reset', methods=['POST'])
@require_auth
def reset_node_config():
    """Reset one or all payment config keys to node defaults.
    Body: {key} for single, or {key: 'all'} for all 7 keys."""
    try:
        data = request.get_json() or {}
        key = data.get('key', '').strip()

        keys_to_reset = list(NODE_CONFIG_KEYS.keys()) if key == 'all' else [key]

        if key != 'all' and key not in NODE_CONFIG_KEYS:
            return jsonify({'success': False, 'error': f'Unknown key: {key}'}), 400

        results = []
        for k in keys_to_reset:
            meta = NODE_CONFIG_KEYS[k]
            default_val = meta['node_default']
            ok, method, err = _run_myst_config_set(k, default_val)
            results.append({'key': k, 'value': default_val, 'success': ok, 'error': err})

            # Dual write for balance-check-interval
            if ok and meta.get('dual_key'):
                dual_val = _seconds_to_duration(default_val)
                ok2, _, err2 = _run_myst_config_set(meta['dual_key'], dual_val)
                results.append({'key': meta['dual_key'], 'value': dual_val, 'success': ok2, 'error': err2})

        overall = all(r['success'] for r in results)
        return jsonify({
            'success': overall,
            'results': results,
            'restart_required': True,
        }), 200 if overall else 500

    except Exception as e:
        logger.error(f"Node config reset error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ============ ERROR HANDLERS ============

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Endpoint not found'}), 404


@app.errorhandler(500)
def server_error(error):
    logger.error(f"Server error: {error}")
    return jsonify({'error': 'Internal server error'}), 500


# ============ STARTUP ============

@app.route('/peer/data', methods=['GET'])
@require_auth
def peer_data():
    """Rich data endpoint for peer-to-peer fleet mode.
    Called by a remote toolkit to get full local data including:
    - Earnings history (daily/weekly/monthly from snapshots)
    - Uptime stats (30d local tracking)
    - Session archive stats (from sessions_history.db)
    - Node quality (Discovery API)
    - Live metrics snapshot
    """
    try:
        with metrics_lock:
            cache = copy.deepcopy(metrics_cache)

        # Earnings history snapshots — read from SQLite (earnings_snapshots table)
        # Previously read from stale earnings_history.json (last updated Mar 25).
        # EarningsDB has 600+ live snapshots; JSON was never updated after migration.
        # Send full earnings history — no days_back limit for fleet peers
        # The fleet master shows this node's complete history as-is
        earnings_history = EarningsDB.get_all_for_chart(days_back=None)

        # Uptime stats
        uptime_stats = MetricsCollector.compute_uptime_stats()

        # Session archive stats
        db_stats = SessionDB.get_stats()

        # Bug fix: read from 'daily_traffic' (not 'monthly_traffic' which doesn't exist)
        # Also send the live bandwidth shape so fleet master can display it correctly
        traffic_history = {}
        try:
            rows = TrafficDB.get_range(days_back=30)
            traffic_history['daily'] = rows
            totals = TrafficDB.get_totals()
            traffic_history['totals'] = totals
        except Exception:
            pass

        # Send live bandwidth from metrics cache — same shape as /metrics bandwidth
        # This is what the frontend maps to 'bandwidth' in the fleet node view
        bandwidth = cache.get('bandwidth', {})

        # Send pre-computed analytics from sessions cache
        # Analytics is computed locally by get_sessions() which reads this node's own DB
        # Fleet master uses this directly — no re-computation, no cross-node mixing
        sessions_cache = cache.get('sessions', {})
        analytics = {
            'service_breakdown': sessions_cache.get('service_breakdown', []),
            'country_breakdown': sessions_cache.get('country_breakdown', []),
            'lifetime_totals':   sessions_cache.get('lifetime_totals', {}),
            'monitoring_sessions': sessions_cache.get('monitoring_sessions', 0),
        }

        return jsonify({
            'peer_mode':        True,
            'version':          cache.get('nodeStatus', {}).get('version', 'unknown'),
            'node_status':      cache.get('nodeStatus', {}),
            'earnings':         cache.get('earnings', {}),
            'sessions':         cache.get('sessions', {}),
            'services':         cache.get('services', {}),
            'resources':        cache.get('resources', {}),
            'performance':      cache.get('performance', {}),
            'node_quality':     cache.get('nodeQuality', {}),
            'live_connections': cache.get('live_connections', {}),
            'firewall':         cache.get('firewall', {}),
            'systemHealth':     cache.get('systemHealth', {}),
            'uptime_stats':     uptime_stats,
            'db_stats':         db_stats,
            'earnings_history': earnings_history,
            'bandwidth':        bandwidth,
            'traffic_history':  traffic_history,
            'analytics':        analytics,
            'logs':             MetricsCollector._get_logs_cached(),
            'myst_price':       _myst_price_cache.copy(),
            'timestamp':        datetime.now().isoformat(),
        }), 200
    except Exception as e:
        logger.error(f'peer/data error: {e}')
        return jsonify({'error': str(e)}), 500






# ============ DATA MANAGEMENT ROUTES ============

@app.route('/data/stats', methods=['GET'])
@require_auth
def get_data_stats():
    """Get consolidated statistics from all databases."""
    try:
        if DataManager is None:
            return jsonify({'error': 'DataManager not available'}), 500
        node_id = request.args.get('node_id')
        stats = DataManager.get_all_stats(node_id=node_id)
        return jsonify(stats), 200
    except Exception as e:
        logger.error(f'Data stats error: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/data/retention', methods=['GET'])
@require_auth
def get_data_retention():
    """Return current data retention configuration (days per type)."""
    try:
        retention = _get_retention_config()
        return jsonify({
            'retention':  retention,
            'defaults':   _DEFAULT_RETENTION,
            'last_prune': _last_prune_date or None,
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/data/retention', methods=['POST'])
@require_auth
def save_data_retention():
    """Save data retention settings to config/setup.json.
    Accepts a JSON body with any subset of retention keys (days as integers).
    Only valid keys and positive integers are accepted.
    Changes take effect immediately — no restart required.
    """
    try:
        body = request.get_json(silent=True) or {}
        new_values = body.get('retention', {})
        if not isinstance(new_values, dict):
            return jsonify({'error': 'retention must be a JSON object'}), 400

        # Validate: only known keys, only positive integers
        accepted = {}
        rejected = {}
        for k, v in new_values.items():
            if k not in _DEFAULT_RETENTION:
                rejected[k] = f'unknown key'
            elif not isinstance(v, int) or v <= 0:
                rejected[k] = f'must be a positive integer (got {v!r})'
            else:
                accepted[k] = v

        if not accepted:
            return jsonify({'error': 'No valid retention values provided', 'rejected': rejected}), 400

        # Read current setup.json, merge, write back
        cfg_path = Path('config/setup.json')
        try:
            current = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
        except Exception:
            current = {}

        existing = current.get('data_retention', {})
        if not isinstance(existing, dict):
            existing = {}
        existing.update(accepted)
        current['data_retention'] = existing
        cfg_path.write_text(json.dumps(current, indent=2))

        logger.info(f"data/retention updated: {accepted}")
        return jsonify({
            'success':  True,
            'saved':    accepted,
            'rejected': rejected,
            'retention': _get_retention_config(),
        }), 200
    except Exception as e:
        logger.error(f'data/retention POST error: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/data/delete', methods=['POST'])
@require_auth
def delete_data():
    """Unified data deletion across all databases.
    
    Deletes from DB and immediately syncs in-memory caches to match.
    No locks needed — memory is filtered to match DB after delete.
    Each node only deletes its own data (filtered by node_id/provider_id).
    """
    try:
        if DataManager is None:
            return jsonify({'success': False, 'error': 'DataManager not available'}), 500
        body = request.get_json() or {}
        data_type   = body.get('type', 'all')
        keep_days   = body.get('keep_days')
        before_date = body.get('before_date')
        # Use node_id from body, fall back to live _local_node_id set by slow-tier collector.
        # Never pass 'local' or a beneficiary address — DataManager validates with startswith('0x').
        node_id = body.get('node_id') or (_local_node_id if _local_node_id else None)

        # Perform the actual deletion in all relevant DBs
        result = DataManager.delete_range(data_type=data_type, node_id=node_id,
                                          keep_days=keep_days, before_date=before_date)

        # Compute cutoff datetime for in-memory filtering
        cutoff_dt = None
        if keep_days is not None:
            cutoff_dt = datetime.now(timezone.utc) - timedelta(days=keep_days)

        # Sync earnings in-memory snapshots to match DB
        if data_type in ('earnings', 'all'):
            try:
                if cutoff_dt is not None:
                    # Filter: keep only snapshots newer than cutoff
                    cutoff_iso = cutoff_dt.isoformat()
                    EarningsDeltaTracker._snapshots = [
                        s for s in EarningsDeltaTracker._snapshots
                        if s.get('time', '') >= cutoff_iso
                    ]
                else:
                    # Delete everything — clear all snapshots
                    EarningsDeltaTracker._snapshots = []
                # Force immediate reload from DB so chart reflects delete instantly
                # without waiting for the next 60s collector cycle
                EarningsDeltaTracker._loaded = False
                EarningsDeltaTracker._load(force=True)
                logger.info(f"EarningsDeltaTracker: reloaded from DB after delete (keep_days={keep_days}, snapshots={len(EarningsDeltaTracker._snapshots)})")
            except Exception as _ee:
                logger.warning(f"EarningsDeltaTracker sync after delete failed: {_ee}")

        # Invalidate sessions cache — will recompute from live node data on next request
        if data_type in ('sessions', 'all'):
            try:
                with metrics_lock:
                    metrics_cache.pop('sessions', None)
                    metrics_cache.pop('analytics', None)
            except Exception:
                pass

            # Mirror the DB delete into SessionStore._sessions (in-memory TequilAPI cache).
            # Without this, analytics still shows deleted sessions because it merges
            # live TequilAPI sessions (SessionStore._sessions) with DB rows.
            # Deleted DB rows are gone, but SessionStore._sessions is untouched → stale data.
            try:
                if keep_days is not None:
                    # Keep sessions started within the last keep_days days
                    cutoff_iso = cutoff_dt.isoformat() if cutoff_dt else None
                    if cutoff_iso:
                        def _session_started(s):
                            return s.get('created_at', s.get('started_at', '')) or ''
                        with SessionStore._lock:
                            SessionStore._sessions = {
                                sid: s for sid, s in SessionStore._sessions.items()
                                if _session_started(s) >= cutoff_iso
                            }
                        logger.info(f"SessionStore: filtered in-memory sessions to keep_days={keep_days} "
                                    f"(cutoff={cutoff_iso[:10]}, remaining={len(SessionStore._sessions)})")
                elif before_date is not None:
                    # Keep sessions started on or after before_date
                    with SessionStore._lock:
                        SessionStore._sessions = {
                            sid: s for sid, s in SessionStore._sessions.items()
                            if (s.get('created_at', s.get('started_at', '')) or '') >= before_date
                        }
                    logger.info(f"SessionStore: filtered in-memory sessions before_date={before_date} "
                                f"(remaining={len(SessionStore._sessions)})")
                else:
                    # Delete everything — wipe in-memory session store entirely
                    with SessionStore._lock:
                        SessionStore._sessions.clear()
                    logger.info("SessionStore: cleared all in-memory sessions after delete-all")
            except Exception as _se:
                logger.warning(f"SessionStore in-memory sync after delete failed: {_se}")

        # Invalidate slow/medium tier caches for all affected types
        try:
            for _k in list(_tier_slow_cache.keys()):
                if data_type == 'all' or _k in (data_type, 'sessions', 'earnings'):
                    _tier_slow_cache.pop(_k, None)
            # Reset both tier timestamps — forces full rebuild on next poll
            global _tier_medium_last, _tier_slow_last
            _tier_medium_last = 0
            _tier_slow_last   = 0
        except Exception:
            pass

        return jsonify(result), 200
    except Exception as e:
        logger.error(f'Data delete error: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/data/quality/history', methods=['GET'])
@require_auth
def get_quality_history():
    """Get node quality history for charting."""
    try:
        if QualityDB is None:
            return jsonify({'history': [], 'error': 'QualityDB not available'}), 200
        days    = request.args.get('days', 30, type=int)
        node_id = request.args.get('node_id')
        history = QualityDB.get_history(days_back=days, node_id=node_id)
        return jsonify({'history': history, 'days': days}), 200
    except Exception as e:
        logger.error(f'Quality history error: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/data/system/history', methods=['GET'])
@require_auth
def get_system_history():
    """Get system metrics history for charting."""
    try:
        if SystemMetricsDB is None:
            return jsonify({'history': [], 'error': 'SystemMetricsDB not available'}), 200
        days    = request.args.get('days', 7, type=int)
        node_id = request.args.get('node_id')
        history = SystemMetricsDB.get_history(days_back=days, node_id=node_id)
        return jsonify({'history': history, 'days': days}), 200
    except Exception as e:
        logger.error(f'System history error: {e}')
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    # Write PID file so start.sh menu can detect running backend
    # regardless of whether it was started manually or via systemd
    try:
        _pid_file = Path('logs/.backend.pid')
        _pid_file.parent.mkdir(parents=True, exist_ok=True)
        _pid_file.write_text(str(os.getpid()))
    except Exception:
        pass

    start_collector()

    # ── SPA catch-all: serve index.html for all non-API routes ──────────────
    # This makes React Router work correctly in production.
    # Only active when dist/ is built — in dev mode Vite handles routing.
    # Type 3 (lightweight backend) — no frontend, do not serve HTML
    _setup_mode = setup_config.get('setup_mode', 'full')
    if _setup_mode == 'lightweight':
        @app.route('/', defaults={'path': ''})
        @app.route('/<path:path>')
        def serve_spa(path):
            """Lightweight mode — backend only, no frontend."""
            # Only serve API responses, not HTML
            if path and not path.startswith('api'):
                return jsonify({
                    'mode': 'lightweight',
                    'message': 'This is a lightweight backend (Type 3). No dashboard UI available. Data is served via /peer/data to a fleet master.',
                    'peer_data': '/peer/data',
                    'health': '/health',
                }), 200
            return jsonify({'status': 'ok'}), 200
    elif _has_dist:
        @app.route('/', defaults={'path': ''})
        @app.route('/<path:path>')
        def serve_spa(path):
            """Serve React SPA — catch all non-API routes.
            Flask already prioritises specific routes (like /health, /metrics) over
            this catch-all, so we only reach here for unknown paths → serve index.html.
            """
            # Serve static file from dist/ if it exists (JS, CSS, images)
            if path:
                target = _dist_dir / path
                if target.exists() and target.is_file():
                    return app.send_static_file(path)
            # Everything else → React app (no-cache so version updates are immediate)
            from flask import make_response
            resp = make_response(app.send_static_file('index.html'))
            resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            resp.headers['Pragma'] = 'no-cache'
            resp.headers['Expires'] = '0'
            return resp

    auth_mode = 'API Key' if API_KEY else ('Basic Auth' if USERNAME else 'None (local only)')
    mode_str  = 'PRODUCTION (dist/)' if _has_dist else 'DEV (use npm start for frontend)'

    print(f"""
    ╔════════════════════════════════════════════════════════════╗
    ║   Mysterium Node Toolkit v{APP_VERSION} — Backend                  ║
    ╚════════════════════════════════════════════════════════════╝

    ✓ Mode:     {mode_str}
    ✓ Port:     {PORT}
    ✓ Node API: {NODE_API_URL}
    ✓ Auth:     {auth_mode}
    {'✓ Frontend: http://0.0.0.0:' + str(PORT) + '/' if _has_dist else '⚠ Frontend: start Vite with ./start.sh'}
    """)

    app.run(host='0.0.0.0', port=PORT, debug=DEBUG)
