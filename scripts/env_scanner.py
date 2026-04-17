#!/usr/bin/env python3
"""
Mysterium Toolkit - Environment Scanner & Cleanup
==================================================
Finds previous toolkit installations across the system and offers to clean them up.

SAFETY GUARANTEES:
  - The directory this script runs FROM is NEVER modified in any way.
  - The actual Mysterium node (/etc/mysterium-node/, myst service, docker) is NEVER touched.
  - Unrelated Python virtual environments are NEVER flagged or removed.
  - System packages and other user projects are NEVER touched.
  - SQLite databases with real data trigger an explicit warning before removal.

Identification uses strict multi-signal fingerprinting — a directory must score >= 3
to be considered a toolkit install.

Distro support: Debian, Ubuntu, Parrot, Fedora, RHEL, Arch, Alpine.
Process detection: pgrep -af (GNU), pgrep -a (Alpine), ps aux (POSIX fallback).
Privilege escalation: sudo (Debian/Ubuntu/Fedora/Arch), doas (Alpine/OpenBSD).
"""

import os
import sys
import time
import shutil
import signal
import sqlite3
import subprocess
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple


# ============ TERMINAL COLORS ============

class Colors:
    RED    = '\033[0;31m'
    YELLOW = '\033[1;33m'
    GREEN  = '\033[0;32m'
    BLUE   = '\033[0;34m'
    CYAN   = '\033[96m'
    BOLD   = '\033[1m'
    DIM    = '\033[2m'
    NC     = '\033[0m'


def cprint(color: str, symbol: str, text: str) -> None:
    """Print a colored line with a symbol prefix."""
    print(f"{color}{symbol} {text}{Colors.NC}")


def print_header(text: str) -> None:
    """Print a bordered section header."""
    try:
        tw = os.get_terminal_size().columns
    except OSError:
        tw = 80
    box_w = min(tw - 2, max(72, len(text) + 6))
    inner = box_w - 2
    print(f"\n{Colors.BOLD}{Colors.CYAN}╔{'═' * inner}╗{Colors.NC}")
    print(f"{Colors.BOLD}{Colors.CYAN}║ {text:<{inner - 2}} ║{Colors.NC}")
    print(f"{Colors.BOLD}{Colors.CYAN}╚{'═' * inner}╝{Colors.NC}\n")


def confirm(prompt: str, default: bool = False) -> bool:
    """Prompt the user for a yes/no answer. Returns bool."""
    hint = "[Y/n]" if default else "[y/N]"
    response = input(f"{Colors.BLUE}  {prompt} {hint}: {Colors.NC}").strip().lower()
    if response in ('y', 'yes'):
        return True
    if response in ('n', 'no'):
        return False
    return default


# ============ FINGERPRINTING ============
# Scoring system: a directory must score >= MIN_SCORE to be flagged.
# Multiple strong signals prevent false positives on random venvs or node installs.

TOOLKIT_FINGERPRINTS = {
    # (check_type, points, description)
    'scripts/setup_wizard.py':  ('file_exists',              2, 'Setup wizard script'),
    'backend/app.py':           ('file_exists',              2, 'Flask backend'),
    'frontend/Dashboard.jsx':   ('file_exists',              2, 'React dashboard'),
    'config/setup.json':        ('file_json_key',            2, 'Toolkit config'),
    '.env':                     ('file_contains_key',        1, 'Environment config'),
    'requirements.txt':         ('file_contains_flask_psutil', 1, 'Python deps'),
    'bin/setup.sh':             ('file_exists',              1, 'Setup launcher'),
    'bin/start.sh':             ('file_exists',              1, 'Start launcher'),
    'venv':                     ('dir_exists',               1, 'Virtual environment'),
    'node_modules':             ('dir_exists',               0, 'Node packages'),  # 0 pts — not unique
}

SETUP_JSON_KEYS   = {'node_host', 'node_port', 'dashboard_port', 'dashboard_auth_method'}
ENV_REQUIRED_KEYS = {'MYSTERIUM_NODE_API', 'DASHBOARD_PORT'}
MIN_SCORE         = 3
MAX_SCAN_DEPTH    = 5

# Paths that are NEVER scanned or touched under any circumstances
EXCLUDED_PATHS = {
    '/etc/mysterium-node',
    '/var/lib/mysterium-node',
    '/usr/bin/myst',
    '/usr/lib/mysterium-node',
    '/var/log/mysterium-node',
    '/snap', '/proc', '/sys', '/dev', '/run',
}


# ============ DATA STRUCTURES ============

class ToolkitInstall:
    """
    Represents a single discovered toolkit installation on disk.

    Attributes set at init:
      path          — absolute resolved Path of the installation directory
      score         — fingerprint score (higher = more confident match)
      signals       — list of matched fingerprint descriptions
      has_venv      — whether venv/ directory exists
      has_node_modules — whether node_modules/ exists
      has_config    — whether config/setup.json exists
      has_env       — whether .env exists
      has_logs      — whether logs/ has files
      has_db_data   — whether any SQLite DB contains real rows (earnings/sessions/traffic)
      venv_size     — size of venv in bytes
      total_size    — venv + node_modules combined bytes
      last_modified — datetime of most recently changed key file
      running_pids  — list of (type_str, pid_int) tuples for active processes
    """

    def __init__(self, path: Path, score: int, signals: List[str]):
        self.path    = path
        self.score   = score
        self.signals = signals

        self.has_venv         = (path / 'venv').is_dir()
        self.has_node_modules = (path / 'node_modules').is_dir()
        self.has_config       = (path / 'config' / 'setup.json').is_file()
        self.has_env          = (path / '.env').is_file()
        self.has_logs         = (path / 'logs').is_dir() and any((path / 'logs').iterdir())
        self.has_db_data      = self._check_db_data()

        self.venv_size          = dir_size(path / 'venv') if self.has_venv else 0
        self.node_modules_size  = dir_size(path / 'node_modules') if self.has_node_modules else 0
        self.total_size         = self.venv_size + self.node_modules_size

        self.last_modified = self._get_last_modified()
        self.running_pids  = []
        self._check_running_processes()

    def _check_db_data(self) -> bool:
        """
        Return True if any SQLite DB in config/ contains at least one real data row.
        Used to warn the user before deleting historical earnings/session data.
        Does NOT read or modify any data — read-only check only.
        """
        db_checks = {
            'config/earnings_history.db':  'earnings_snapshots',
            'config/sessions_history.db':  'sessions',
            'config/traffic_history.db':   'daily_traffic',
        }
        for rel, table in db_checks.items():
            db_path = self.path / rel
            if not db_path.exists():
                continue
            try:
                conn = sqlite3.connect(str(db_path), timeout=3)
                row = conn.execute(
                    f"SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",(table,)
                ).fetchone()
                if row and row[0] > 0:
                    count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    conn.close()
                    if count > 0:
                        return True
                conn.close()
            except Exception:
                pass
        return False

    def _get_last_modified(self) -> Optional[datetime]:
        """Return the most recent mtime across key tracked files, or None."""
        candidates = [
            self.path / '.env',
            self.path / 'config' / 'setup.json',
            self.path / 'logs' / 'app.log',
            self.path / 'backend' / 'app.py',
        ]
        latest = None
        for f in candidates:
            try:
                if f.exists():
                    mtime = datetime.fromtimestamp(f.stat().st_mtime)
                    if latest is None or mtime > latest:
                        latest = mtime
            except OSError:
                pass
        return latest

    def _check_running_processes(self) -> None:
        """
        Populate running_pids with (type, pid) tuples for processes launched from this path.

        Detection strategy (in order):
          1. pgrep -af  — GNU/Linux: Debian, Ubuntu, Parrot, Fedora, Arch
          2. pgrep -a   — Alpine Linux (busybox pgrep, no -f flag)
          3. ps aux     — POSIX fallback for any system
        """
        self.running_pids = []
        path_str = str(self.path)

        def _find_pids(pattern: str) -> List[int]:
            """Return PIDs of processes matching pattern whose cmdline contains path_str."""
            found = []

            # Strategy 1: pgrep -af (GNU — Debian/Ubuntu/Parrot/Fedora/Arch)
            try:
                r = subprocess.run(['pgrep', '-af', pattern],
                                   capture_output=True, text=True, timeout=5)
                if r.returncode == 0:
                    for line in r.stdout.strip().splitlines():
                        if line.strip() and path_str in line:
                            parts = line.split(None, 1)
                            if parts and parts[0].isdigit():
                                found.append(int(parts[0]))
                    if found:
                        return found
            except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
                pass

            # Strategy 2: pgrep -a (Alpine — busybox pgrep, -f not supported)
            try:
                r = subprocess.run(['pgrep', '-a', pattern],
                                   capture_output=True, text=True, timeout=5)
                if r.returncode == 0:
                    for line in r.stdout.strip().splitlines():
                        if line.strip() and path_str in line:
                            parts = line.split(None, 1)
                            if parts and parts[0].isdigit():
                                found.append(int(parts[0]))
                    if found:
                        return found
            except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
                pass

            # Strategy 3: ps aux (universal POSIX fallback)
            try:
                r = subprocess.run(['ps', 'aux'],
                                   capture_output=True, text=True, timeout=5)
                if r.returncode == 0:
                    for line in r.stdout.strip().splitlines():
                        if pattern in line and path_str in line and 'grep' not in line:
                            parts = line.split()
                            if len(parts) >= 2 and parts[1].isdigit():
                                found.append(int(parts[1]))
            except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
                pass

            return found

        for pid in _find_pids('backend/app.py'):
            self.running_pids.append(('backend', pid))
        for pid in _find_pids('vite'):
            self.running_pids.append(('frontend', pid))

    @property
    def is_running(self) -> bool:
        """True if any toolkit process from this path is currently active."""
        return len(self.running_pids) > 0

    @property
    def is_current_dir(self) -> bool:
        """
        True if this installation is the directory the script is currently running from.
        SAFETY: this property is used to unconditionally block all modifications to the
        active installation directory.
        """
        try:
            return self.path.resolve() == Path(__file__).resolve().parent.parent
        except OSError:
            return False


# ============ UTILITY FUNCTIONS ============

def dir_size(path: Path) -> int:
    """Return total byte size of all files under path. Returns 0 on any error."""
    total = 0
    try:
        for entry in path.rglob('*'):
            try:
                if entry.is_file():
                    total += entry.stat().st_size
            except OSError:
                pass
    except OSError:
        pass
    return total


def format_size(size_bytes: int) -> str:
    """Convert byte count to human-readable string (e.g. '46.6 MB')."""
    if size_bytes == 0:
        return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def is_excluded(path: Path) -> bool:
    """Return True if path starts with any entry in EXCLUDED_PATHS (real node / system dirs)."""
    path_str = str(path.resolve())
    for excluded in EXCLUDED_PATHS:
        if path_str.startswith(excluded):
            return True
    return False


def _rm_rf(path: Path) -> Tuple[bool, Optional[str]]:
    """
    Remove a path recursively.

    Returns (True, None) on success, (False, error_string) on failure.

    Privilege escalation order (tried only when PermissionError occurs):
      1. sudo rm -rf  — Debian, Ubuntu, Parrot, Fedora, Arch
      2. doas rm -rf  — Alpine Linux, some Arch setups
    Never escalates on the current working directory.
    """
    try:
        if path.is_file() or path.is_symlink():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(str(path))
        return True, None
    except PermissionError as e:
        # Try sudo first (most distros)
        for escalator in ('sudo', 'doas'):
            try:
                r = subprocess.run(
                    [escalator, 'rm', '-rf', str(path)],
                    capture_output=True, timeout=30
                )
                if r.returncode == 0:
                    return True, None
            except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
                continue
        return False, str(e)
    except Exception as e:
        return False, str(e)


# ============ SCANNING ============

def score_directory(directory: Path) -> Tuple[int, List[str]]:
    """
    Score a directory against TOOLKIT_FINGERPRINTS.

    Returns (score, matched_signal_descriptions).
    A score >= MIN_SCORE means the directory is considered a toolkit install.
    """
    score = 0
    signals = []

    for rel_path, (check_type, points, desc) in TOOLKIT_FINGERPRINTS.items():
        target = directory / rel_path
        try:
            if check_type == 'file_exists':
                if target.is_file():
                    score += points
                    signals.append(desc)

            elif check_type == 'dir_exists':
                if target.is_dir():
                    score += points
                    signals.append(desc)

            elif check_type == 'file_json_key':
                if target.is_file():
                    try:
                        data = json.loads(target.read_text())
                        if SETUP_JSON_KEYS.issubset(set(data.keys())):
                            score += points
                            signals.append(desc)
                    except (json.JSONDecodeError, OSError):
                        pass

            elif check_type == 'file_contains_key':
                if target.is_file():
                    try:
                        content = target.read_text(errors='ignore')
                        if all(key in content for key in ENV_REQUIRED_KEYS):
                            score += points
                            signals.append(desc)
                    except OSError:
                        pass

            elif check_type == 'file_contains_flask_psutil':
                if target.is_file():
                    try:
                        content = target.read_text(errors='ignore').lower()
                        if 'flask' in content and 'psutil' in content and 'flask-cors' in content:
                            score += points
                            signals.append(desc)
                    except OSError:
                        pass

        except (PermissionError, OSError):
            continue

    return score, signals


def scan_directory(base: Path, depth: int = 0, results: list = None) -> List[ToolkitInstall]:
    """
    Recursively scan base for toolkit installations up to MAX_SCAN_DEPTH.

    Returns a list of ToolkitInstall objects. Each confirmed install stops
    recursion at that level (we never scan inside a found toolkit directory).
    """
    if results is None:
        results = []
    if depth > MAX_SCAN_DEPTH:
        return results
    try:
        base = base.resolve()
    except OSError:
        return results
    if is_excluded(base):
        return results

    skip_names = {
        'venv', 'node_modules', '.git', '__pycache__', 'dist', 'build',
        '.cache', '.local', '.config', '.npm', '.nvm', 'snap', 'mysterium-node',
    }

    score, signals = score_directory(base)
    if score >= MIN_SCORE:
        results.append(ToolkitInstall(base, score, signals))
        return results  # Do not recurse into a confirmed install

    try:
        for entry in sorted(base.iterdir()):
            try:
                if entry.is_dir() and not entry.is_symlink():
                    if entry.name not in skip_names and not entry.name.startswith('.'):
                        scan_directory(entry, depth + 1, results)
            except (PermissionError, OSError):
                continue
    except (PermissionError, OSError):
        pass

    return results


def get_scan_paths() -> List[Path]:
    """
    Build the list of directories to scan.

    Sources (no hardcoded personal paths):
      - Home directory and its immediate subdirectories
      - Parent and grandparent of the current working directory (catches sibling installs)
      - System-wide locations: /opt, /srv, /tmp
    """
    paths = set()
    home = Path.home()
    paths.add(home)

    cwd = Path.cwd()
    if cwd.parent != cwd:
        paths.add(cwd.parent)
    if cwd.parent.parent != cwd.parent:
        paths.add(cwd.parent.parent)

    for sys_dir in ('/opt', '/srv', '/tmp'):
        p = Path(sys_dir)
        if p.is_dir() and str(p) not in {str(x) for x in EXCLUDED_PATHS}:
            paths.add(p)

    try:
        for child in home.iterdir():
            if child.is_dir() and not child.name.startswith('.') and \
               child.name not in ('snap', 'cache', 'local', 'config'):
                paths.add(child)
    except PermissionError:
        pass

    return sorted(paths)


def anonymize_path(p: Path) -> str:
    """Replace home directory prefix with ~ for display."""
    try:
        home = str(Path.home())
        s = str(p)
        if s.startswith(home):
            return '~' + s[len(home):]
        return s
    except Exception:
        return str(p)


# ============ DISPLAY ============

def display_installs(installs: List[ToolkitInstall]) -> None:
    """Print a formatted list of toolkit installations with their details."""
    for i, inst in enumerate(installs, 1):
        status_parts = []
        if inst.is_running:
            status_parts.append(f"{Colors.RED}● RUNNING{Colors.NC}")
        if inst.is_current_dir:
            status_parts.append(f"{Colors.CYAN}★ CURRENT{Colors.NC}")
        status = "  ".join(status_parts) if status_parts else ""

        print(f"  {Colors.BOLD}{Colors.YELLOW}[{i}]{Colors.NC} "
              f"{Colors.BOLD}{anonymize_path(inst.path)}{Colors.NC}")
        if status:
            print(f"      {status}")

        age = ""
        if inst.running_pids:
            age = "active now"
        elif inst.last_modified:
            delta = datetime.now() - inst.last_modified
            if delta.days > 0:
                age = f"{delta.days}d ago"
            elif delta.seconds > 3600:
                age = f"{delta.seconds // 3600}h ago"
            elif delta.seconds > 60:
                age = f"{delta.seconds // 60}m ago"
            else:
                age = "recent"

        detail_parts = []
        if inst.has_venv:
            detail_parts.append(f"venv: {format_size(inst.venv_size)}")
        if inst.has_node_modules:
            detail_parts.append(f"node_modules: {format_size(inst.node_modules_size)}")
        if age:
            detail_parts.append(f"last active: {age}")
        if inst.has_db_data:
            detail_parts.append(f"{Colors.YELLOW}⚠ has DB data{Colors.NC}")

        print(f"      {Colors.DIM}{' │ '.join(detail_parts)}{Colors.NC}")

        components = []
        if inst.has_venv:          components.append("venv")
        if inst.has_node_modules:  components.append("node_modules")
        if inst.has_config:        components.append("config")
        if inst.has_env:           components.append(".env")
        if inst.has_logs:          components.append("logs")
        if inst.has_db_data:       components.append(f"{Colors.YELLOW}DB data{Colors.NC}")

        print(f"      {Colors.DIM}contains: {', '.join(components)}{Colors.NC}")
        print(f"      {Colors.DIM}signals:  {', '.join(inst.signals)} (score: {inst.score}){Colors.NC}")
        print()


# ============ PROCESS MANAGEMENT ============

def kill_processes(install: ToolkitInstall) -> bool:
    """
    Terminate all running processes belonging to install.

    Sends SIGTERM first, waits 2 seconds, then SIGKILL to any stragglers.
    Returns True if all processes were killed (or there were none).
    Returns False if the user declined or a permission error occurred.

    Note: Never kills processes from the current installation (is_current_dir).
    """
    if not install.running_pids:
        return True

    cprint(Colors.YELLOW, "⚠", f"Processes running from {anonymize_path(install.path)}:")
    for proc_type, pid in install.running_pids:
        print(f"      PID {pid} ({proc_type})")

    if not confirm("Kill these processes?"):
        cprint(Colors.YELLOW, "⚠", "Skipping — cannot clean while processes are running")
        return False

    for proc_type, pid in install.running_pids:
        try:
            os.kill(pid, signal.SIGTERM)
            cprint(Colors.GREEN, "✓", f"Sent SIGTERM to PID {pid} ({proc_type})")
        except ProcessLookupError:
            cprint(Colors.DIM, "·", f"PID {pid} already gone")
        except PermissionError:
            cprint(Colors.RED, "✗", f"No permission to kill PID {pid} — try running as root")
            return False

    time.sleep(2)

    for proc_type, pid in install.running_pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    return True


# ============ CLEANUP ============

def clean_install(install: ToolkitInstall, remove_all: bool = False) -> Dict[str, bool]:
    """
    Remove generated artifacts from a toolkit installation.

    What this removes (with remove_all=False):
      - venv/            Python virtual environment
      - node_modules/    Node.js packages
      - package-lock.json
      - config/setup.json  (credentials)
      - .env               (credentials)
      - logs/              (log files, keeps .gitkeep)
      - __pycache__/       (compiled bytecode)
      - *.pid, *.pyc, .env.bak  (runtime artifacts)

    What this removes additionally with remove_all=True:
      - The entire installation directory

    What this NEVER removes:
      - The directory this script runs from (is_current_dir = hard block)
      - The actual Mysterium node or any system paths
      - SQLite DB files without explicit user confirmation when they contain data

    Returns:
      Dict[str, bool] mapping artifact name to True (removed) / False (failed).
      Always returns a dict — never None.
    """
    results: Dict[str, bool] = {}
    base = install.path

    # ── HARD SAFETY BLOCK ──────────────────────────────────────────────────────
    # The current installation directory is NEVER modified under any circumstances.
    if install.is_current_dir:
        cprint(Colors.RED, "✗", "Refusing to clean current installation directory — skipped.")
        return results

    # ── 1. Kill running processes ───────────────────────────────────────────────
    if install.is_running:
        if not kill_processes(install):
            # User declined to kill or permission error — abort this install
            return results

    # ── 2. Warn about DB data before touching config/ ──────────────────────────
    # If the install has SQLite databases with real rows, warn the user explicitly.
    # This data is historical earnings/session history that cannot be recovered.
    db_files = [
        (base / 'config' / 'earnings_history.db',  'earnings_snapshots'),
        (base / 'config' / 'sessions_history.db',  'sessions'),
        (base / 'config' / 'traffic_history.db',   'daily_traffic'),
    ]
    dbs_with_data = []
    for db_path, table in db_files:
        if not db_path.exists():
            continue
        try:
            conn = sqlite3.connect(str(db_path), timeout=3)
            row = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            if row and row[0] > 0:
                count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                if count > 0:
                    dbs_with_data.append((db_path, count))
            conn.close()
        except Exception:
            pass

    if dbs_with_data:
        cprint(Colors.YELLOW, "⚠", f"This install has SQLite databases with real data:")
        for db_path, count in dbs_with_data:
            print(f"      {db_path.name}: {count} rows")
        cprint(Colors.YELLOW, "·",
               "This is historical earnings/session data. It cannot be recovered after deletion.")
        if not confirm("Delete these databases too?", default=False):
            cprint(Colors.CYAN, "·", "Databases preserved — cleaning everything else.")
            # Mark DB files as protected so step 5 skips them
            protected_dbs = {str(d) for d, _ in dbs_with_data}
        else:
            protected_dbs = set()
    else:
        protected_dbs = set()

    # ── 3. Remove venv ─────────────────────────────────────────────────────────
    if install.has_venv:
        ok, err = _rm_rf(base / 'venv')
        results['venv'] = ok
        if ok:
            cprint(Colors.GREEN, "✓", f"Removed venv ({format_size(install.venv_size)})")
        else:
            cprint(Colors.RED, "✗", f"Could not remove venv: {err}")

    # ── 4. Remove node_modules ─────────────────────────────────────────────────
    if install.has_node_modules:
        ok, err = _rm_rf(base / 'node_modules')
        results['node_modules'] = ok
        if ok:
            cprint(Colors.GREEN, "✓",
                   f"Removed node_modules ({format_size(install.node_modules_size)})")
        else:
            cprint(Colors.RED, "✗", f"Could not remove node_modules: {err}")

    # ── 5. Remove package-lock.json ────────────────────────────────────────────
    lock_path = base / 'package-lock.json'
    if lock_path.is_file():
        ok, err = _rm_rf(lock_path)
        if ok:
            results['package-lock'] = True

    # ── 6. Remove config/ contents (setup.json + DB files unless protected) ───
    config_dir = base / 'config'
    if config_dir.is_dir():
        # Remove setup.json
        setup_json = config_dir / 'setup.json'
        if setup_json.is_file():
            ok, err = _rm_rf(setup_json)
            results['config/setup.json'] = ok
            if ok:
                cprint(Colors.GREEN, "✓", "Removed config/setup.json")
            else:
                cprint(Colors.RED, "✗", f"Could not remove config/setup.json: {err}")

        # Remove DB files (unless user chose to protect them)
        for db_path, _ in db_files:
            if not db_path.exists():
                continue
            if str(db_path) in protected_dbs:
                cprint(Colors.DIM, "·", f"Kept {db_path.name} (user chose to preserve)")
                continue
            ok, err = _rm_rf(db_path)
            results[db_path.name] = ok
            if ok:
                cprint(Colors.GREEN, "✓", f"Removed {db_path.name}")
            else:
                cprint(Colors.RED, "✗", f"Could not remove {db_path.name}: {err}")

        # Remove other config files (uptime_log.json, etc.) — not DBs
        for f in config_dir.iterdir():
            if f.is_file() and f.suffix != '.db' and f.name not in ('setup.json', '.gitkeep'):
                try:
                    f.unlink()
                except Exception:
                    pass

        # Remove empty config dir
        try:
            if not any(config_dir.iterdir()):
                config_dir.rmdir()
        except Exception:
            pass

    # ── 7. Remove .env ─────────────────────────────────────────────────────────
    if install.has_env:
        ok, err = _rm_rf(base / '.env')
        results['.env'] = ok
        if ok:
            cprint(Colors.GREEN, "✓", "Removed .env")
        else:
            cprint(Colors.RED, "✗", f"Could not remove .env: {err}")

    # ── 8. Clear logs ──────────────────────────────────────────────────────────
    if install.has_logs:
        logs_dir = base / 'logs'
        try:
            removed_any = False
            for f in logs_dir.iterdir():
                if f.is_file() and f.name != '.gitkeep':
                    f.unlink()
                    removed_any = True
            results['logs'] = True
            if removed_any:
                cprint(Colors.GREEN, "✓", "Cleared logs")
            # Remove empty logs dir
            if not any(logs_dir.iterdir()):
                logs_dir.rmdir()
        except Exception as e:
            results['logs'] = False
            cprint(Colors.RED, "✗", f"Could not clear logs: {e}")

    # ── 9. Remove __pycache__, *.pyc, *.pid, .env.bak ─────────────────────────
    for pycache in base.rglob('__pycache__'):
        if pycache.is_dir():
            try:
                shutil.rmtree(str(pycache))
                results['pycache'] = True
            except Exception:
                pass
    for pattern in ['*.pid', '*.pyc', '.env.bak']:
        for f in base.glob(pattern):
            try:
                f.unlink()
            except Exception:
                pass

    # ── 10. Optionally remove entire directory ─────────────────────────────────
    # remove_all=True only from option 'd'. is_current_dir already blocked above.
    if remove_all:
        score, _ = score_directory(base)
        if (base / 'backend').is_dir() or (base / 'scripts').is_dir():
            if confirm(f"Delete entire directory {anonymize_path(base)}?"):
                ok, err = _rm_rf(base)
                results['directory'] = ok
                if ok:
                    cprint(Colors.GREEN, "✓", "Removed entire directory")
                else:
                    cprint(Colors.RED, "✗", f"Could not remove directory: {err}")
        else:
            cprint(Colors.YELLOW, "⚠",
                   "Skipping full removal — directory structure doesn't match expected toolkit layout")

    return results


# ============ STALE PROCESS DETECTION ============

def scan_stale_processes() -> List[Dict]:
    """
    Find toolkit processes running from directories OTHER than the current install.

    Returns a list of dicts with keys: pid, name, cmdline, uptime.

    Detection strategy:
      1. psutil (available after venv install) — most accurate
      2. ps aux (POSIX fallback) — works on all distros without extra packages
    """
    current_dir = str(Path(__file__).resolve().parent.parent)
    toolkit_patterns = ['backend/app.py', 'cli/dashboard.py', 'scripts/system_health.py', 'vite']
    protected_names  = ['myst', 'mysterium', 'wireguard', 'wg-quick', 'wg']
    stale = []

    # Strategy 1: psutil
    try:
        import psutil
        current_pid  = os.getpid()
        current_ppid = os.getppid()

        for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time', 'ppid']):
            try:
                pid     = proc.info['pid']
                name    = (proc.info['name'] or '').lower()
                cmdline = ' '.join(proc.info.get('cmdline') or [])

                if any(p in name for p in protected_names):
                    continue
                if not any(pat in cmdline for pat in toolkit_patterns):
                    continue

                ppid = proc.info.get('ppid', 0)
                if pid in (current_pid, current_ppid) or ppid in (current_pid, current_ppid):
                    continue
                if current_dir in cmdline:
                    continue
                try:
                    if current_dir in (proc.cwd() or ''):
                        continue
                except Exception:
                    if not any(d in cmdline for d in ('/', '/home/', '/opt/', '/root/')):
                        continue

                uptime = time.time() - (proc.info.get('create_time') or time.time())
                h, m = int(uptime // 3600), int((uptime % 3600) // 60)
                stale.append({
                    'pid':     pid,
                    'name':    proc.info['name'],
                    'cmdline': cmdline[:120],
                    'uptime':  f'{h}h{m}m',
                })
            except Exception:
                continue
        return stale

    except ImportError:
        pass

    # Strategy 2: ps aux fallback
    try:
        r = subprocess.run(['ps', 'aux'], capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            return stale

        for line in r.stdout.strip().splitlines()[1:]:
            parts = line.split(None, 10)
            if len(parts) < 11:
                continue
            cmdline = parts[10]
            pid_str = parts[1]

            if not pid_str.isdigit():
                continue
            pid  = int(pid_str)
            name = os.path.basename(parts[10].split()[0]) if parts[10].split() else ''

            if any(p in name.lower() for p in protected_names):
                continue
            if not any(pat in cmdline for pat in toolkit_patterns):
                continue
            if current_dir in cmdline:
                continue

            stale.append({'pid': pid, 'name': name, 'cmdline': cmdline[:120], 'uptime': 'unknown'})

    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass

    return stale


# ============ MAIN INTERACTIVE FLOW ============

def run_scanner(auto_mode: bool = False, current_dir_only: bool = False,
                remove_source: bool = False) -> int:
    """
    Main interactive scanner entry point.

    Args:
        auto_mode:        Non-interactive mode for setup.sh integration.
                          Scans and reports but defers cleanup to migrate_data.py.
        current_dir_only: Only check current directory — fast single-dir check.
        remove_source:    (unused, kept for CLI compatibility)

    Returns:
        Number of installations cleaned (0 if none or cancelled).
    """
    print_header("Toolkit Environment Scanner")
    cprint(Colors.CYAN, "·", "Scanning for previous Mysterium Toolkit installations...")
    cprint(Colors.CYAN, "·", "Only toolkit dashboard venvs are targeted — your Mysterium node is safe.\n")

    scan_paths = [Path.cwd()] if current_dir_only else get_scan_paths()

    if not current_dir_only:
        cprint(Colors.DIM, " ", "Scanning locations:")
        for p in scan_paths:
            print(f"      {anonymize_path(p)}")
        print()

    all_installs: List[ToolkitInstall] = []
    seen_paths: set = set()

    for scan_root in scan_paths:
        for inst in scan_directory(scan_root):
            resolved = str(inst.path.resolve())
            if resolved not in seen_paths:
                seen_paths.add(resolved)
                all_installs.append(inst)

    current  = [i for i in all_installs if i.is_current_dir]
    previous = [i for i in all_installs if not i.is_current_dir]

    # Stale process check
    stale_procs = scan_stale_processes()
    if stale_procs:
        cprint(Colors.RED, "⚠",
               f"Found {len(stale_procs)} stale toolkit process(es) from old installations:\n")
        for p in stale_procs:
            print(f"    {Colors.RED}PID {p['pid']}{Colors.NC}  "
                  f"{p['cmdline'][:80]}  (up {p['uptime']})")
        print()

    if not previous and not current:
        cprint(Colors.GREEN, "✓", "No previous toolkit installations found. You're clean!")
        return 0

    if current:
        cprint(Colors.CYAN, "★", "Current installation (this directory):")
        display_installs(current)

    if not previous:
        cprint(Colors.GREEN, "✓", "No OTHER toolkit installations found.")
        return 0

    cprint(Colors.YELLOW, "⚠", f"Found {len(previous)} previous toolkit installation(s):\n")
    display_installs(previous)

    total_space   = sum(i.total_size for i in previous)
    running_count = sum(1 for i in previous if i.is_running)
    db_data_count = sum(1 for i in previous if i.has_db_data)

    print(f"  {Colors.BOLD}Summary:{Colors.NC}")
    print(f"    Previous installs:  {len(previous)}")
    print(f"    Reclaimable space:  {format_size(total_space)}")
    if running_count:
        print(f"    {Colors.RED}Still running:  {running_count}{Colors.NC}")
    if db_data_count:
        print(f"    {Colors.YELLOW}With DB data (will prompt before deleting): {db_data_count}{Colors.NC}")
    print()

    if auto_mode:
        if stale_procs:
            try:
                import psutil
                for p in stale_procs:
                    try:
                        psutil.Process(p['pid']).terminate()
                        cprint(Colors.GREEN, "✓", f"Killed stale PID {p['pid']}")
                    except Exception:
                        pass
            except ImportError:
                pass
        cprint(Colors.CYAN, "·", "Scan complete — data copy and cleanup handled in next step")
        return 0

    # Interactive menu
    print(f"  {Colors.BOLD}Options:{Colors.NC}")
    print(f"    {Colors.BOLD}a{Colors.NC} — Clean ALL previous installations (venv + config + logs)")
    print(f"    {Colors.BOLD}#{Colors.NC}  — Clean specific install by number (e.g. '1' or '1,3')")
    print(f"    {Colors.BOLD}d{Colors.NC} — Clean ALL and delete entire directories")
    print(f"    {Colors.BOLD}q{Colors.NC} — Quit without cleaning")
    print()

    choice = input(f"{Colors.BLUE}  Select: {Colors.NC}").strip().lower()

    if choice in ('q', ''):
        cprint(Colors.CYAN, "·", "No changes made")
        return 0

    remove_dirs = False
    targets: List[ToolkitInstall] = []

    if choice == 'a':
        targets = previous
    elif choice == 'd':
        targets = previous
        remove_dirs = True
    else:
        try:
            indices = [int(x.strip()) for x in choice.split(',')]
            for idx in indices:
                if 1 <= idx <= len(previous):
                    targets.append(previous[idx - 1])
                else:
                    cprint(Colors.RED, "✗", f"Invalid number: {idx}")
                    return 0
        except ValueError:
            cprint(Colors.RED, "✗", "Invalid input")
            return 0

    if not targets:
        cprint(Colors.CYAN, "·", "Nothing selected")
        return 0

    # Confirmation summary
    print()
    cprint(Colors.YELLOW, "⚠", f"About to clean {len(targets)} installation(s):")
    has_any_artifacts = False
    for t in targets:
        markers = []
        if t.has_venv:
            markers.append(f"venv ({format_size(t.venv_size)})")
            has_any_artifacts = True
        if t.has_node_modules:
            markers.append(f"node_modules ({format_size(t.node_modules_size)})")
            has_any_artifacts = True
        if t.has_config:
            markers.append("config")
            has_any_artifacts = True
        if t.has_env:
            markers.append(".env")
            has_any_artifacts = True
        if t.has_db_data:
            markers.append(f"{Colors.YELLOW}⚠ DB data (will prompt){Colors.NC}")
        print(f"      {anonymize_path(t.path)}  [{', '.join(markers)}]")

    if remove_dirs:
        cprint(Colors.RED, "⚠", "ENTIRE DIRECTORIES will be deleted!")
    print()

    if not has_any_artifacts and not remove_dirs:
        cprint(Colors.YELLOW, "⚠",
               "These installations have no generated artifacts (venv, node_modules, config).")
        cprint(Colors.CYAN, "·",
               "Nothing to remove with option 'a'. Use option 'd' to delete entire directories.")
        return 0

    if not confirm("Proceed with cleanup?"):
        cprint(Colors.CYAN, "·", "Cancelled")
        return 0

    # Execute cleanup
    cleaned = 0
    for inst in targets:
        print(f"\n  {Colors.BOLD}Cleaning: {anonymize_path(inst.path)}{Colors.NC}")
        results = clean_install(inst, remove_all=remove_dirs)
        # Count as cleaned if anything meaningful was removed (exclude pycache-only)
        meaningful = {k: v for k, v in results.items()
                      if k not in ('pycache',) and v is True}
        if meaningful or remove_dirs:
            cleaned += 1

    print()
    if cleaned:
        cprint(Colors.GREEN, "✓", f"Cleaned {cleaned} installation(s)")
        total_freed = sum(i.total_size for i in targets)
        if total_freed > 0:
            cprint(Colors.GREEN, "✓", f"Freed approximately {format_size(total_freed)}")
    elif not remove_dirs:
        cprint(Colors.CYAN, "·", "No artifacts were found to remove in the selected installations.")
        cprint(Colors.CYAN, "·", "Use option 'd' to delete entire directories.")

    return cleaned


# ============ ENTRY POINT ============

def main() -> None:
    """CLI entry point for env_scanner. Run with --help for options."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Scan for and clean up previous Mysterium Toolkit installations'
    )
    parser.add_argument('--auto',          action='store_true',
                        help='Auto mode for setup.sh (scan only, no cleanup prompts)')
    parser.add_argument('--scan-only',     action='store_true',
                        help='Scan and report only — no cleanup offered')
    parser.add_argument('--path',          type=str, default=None,
                        help='Additional path to scan')
    parser.add_argument('--remove-source', action='store_true',
                        help='With option d: also delete entire source directories')
    args = parser.parse_args()

    if args.path:
        custom = Path(args.path)
        if custom.is_dir():
            found = scan_directory(custom)
            if found:
                display_installs(found)
            else:
                cprint(Colors.GREEN, "✓", f"No toolkit installations found in {custom}")
        if args.scan_only:
            return

    if args.scan_only:
        scan_paths   = get_scan_paths()
        all_installs = []
        seen: set    = set()
        for p in scan_paths:
            for inst in scan_directory(p):
                key = str(inst.path.resolve())
                if key not in seen:
                    seen.add(key)
                    all_installs.append(inst)
        if all_installs:
            print_header("Toolkit Installations Found")
            display_installs(all_installs)
        else:
            cprint(Colors.GREEN, "✓", "No toolkit installations found")
        return

    run_scanner(auto_mode=args.auto,
                remove_source=getattr(args, 'remove_source', False))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{Colors.RED}✗ Cancelled{Colors.NC}")
        sys.exit(1)
    except Exception as e:
        print(f"\n{Colors.RED}✗ Scanner error: {e}{Colors.NC}")
        sys.exit(1)
