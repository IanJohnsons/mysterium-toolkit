#!/usr/bin/env python3
"""
Mysterium Node Toolkit — Data Migration Tool
=============================================
Handles two scenarios:

  UPDATE  — Existing previous version detected on the same machine.
             Auto-discovers the most recent older install and copies
             any missing data files into the new version's config/.

  IMPORT  — Fresh install on a new machine, or user wants to restore
             from a backup zip exported from a previous install.
             Guided interactive flow with --import or --from-zip PATH.

Data files migrated / merged:
  config/earnings_history.json  — Delta tracker snapshots (daily/weekly/monthly)
  config/setup.json             — Node config (host, port, auth, theme)

  NOTE: config/.agreed is NOT migrated. The disclaimer must be accepted on
  every new install. start.sh handles this automatically.

Merge strategy:
  earnings_history.json  → JSON merge: deduplicate by 'time', sort ascending
  setup.json             → Copy if destination missing; never overwrite existing

Safe by design:
  - Never overwrites an existing file unless --force is passed
  - Never touches the Mysterium node itself (/etc/mysterium-node, myst service)
  - Non-fatal: always exits 0 so setup.sh continues regardless
"""

import os
import sys
import json
import shutil
import zipfile
import argparse
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict

# ── Colours ───────────────────────────────────────────────────────────────────
R = '\033[0;31m'
Y = '\033[1;33m'
G = '\033[0;32m'
C = '\033[96m'
B = '\033[1m'
D = '\033[2m'
N = '\033[0m'


def _c(color, sym, msg):
    print(f"{color}{sym} {msg}{N}")


def _box(title):
    w = min(72, max(len(title) + 6, 50))
    inner = w - 2
    print(f"\n{B}{C}╔{'═' * inner}╗{N}")
    print(f"{B}{C}║ {title:<{inner - 2}} ║{N}")
    print(f"{B}{C}╚{'═' * inner}╝{N}\n")


def _ask(prompt, default=False):
    hint = '[Y/n]' if default else '[y/N]'
    r = input(f"  {C}{prompt} {hint}:{N} ").strip().lower()
    if r in ('y', 'yes'):
        return True
    if r in ('n', 'no'):
        return False
    return default


# ── Data file definitions ──────────────────────────────────────────────────────
DATA_FILES = [
    {
        'name':    'earnings_history.json',
        'relpath': 'config/earnings_history.json',
        'label':   'Earnings delta history (daily/weekly/monthly tracking)',
        'merge':   'json_list_snapshots',   # special merge strategy
        'key':     'time',                  # dedup key
    },
    {
        'name':    'node_identity.txt',
        'relpath': 'config/node_identity.txt',
        'label':   'Node identity (for uptime tracking)',
        'merge':   'copy_if_missing',
    },
    {
        'name':    'uptime_log.json',
        'relpath': 'config/uptime_log.json',
        'label':   'Uptime ping history',
        'merge':   'uptime_conditional',   # Only copy if same node identity
        'key':     None,
    },
    {
        'name':    'setup.json',
        'relpath': 'config/setup.json',
        'label':   'Node configuration (host, port, auth)',
        'merge':   'copy_if_missing',
    },
    {
        'name':    'nodes.json',
        'relpath': 'config/nodes.json',
        'label':   'Fleet node list (ids, labels, URLs, API keys)',
        'merge':   'copy_if_missing',
    },
    # NOTE: config/.agreed is intentionally NOT in this list.
    # The disclaimer must be shown and accepted on every new install and on
    # every major version bump. start.sh handles this with a version stamp.
    # Silently migrating .agreed would bypass operator consent entirely.
]


# ── Toolkit fingerprinting (minimal, borrowed from env_scanner) ────────────────
FINGERPRINTS = [
    'backend/app.py',
    'frontend/Dashboard.jsx',
    'scripts/setup_wizard.py',
    'bin/setup.sh',
]

def _is_toolkit_dir(path: Path) -> bool:
    """Return True if path looks like a Mysterium toolkit installation."""
    if not path.is_dir():
        return False
    hits = sum(1 for f in FINGERPRINTS if (path / f).exists())
    return hits >= 2


def _toolkit_version(path: Path) -> str:
    vf = path / 'VERSION'
    if vf.exists():
        return vf.read_text().strip()
    return '0.0.0'


def _toolkit_mtime(path: Path) -> float:
    """Most recent mtime across tracked data files."""
    mtimes = []
    for df in DATA_FILES:
        fp = path / df['relpath']
        if fp.exists():
            mtimes.append(fp.stat().st_mtime)
    vf = path / 'VERSION'
    if vf.exists():
        mtimes.append(vf.stat().st_mtime)
    return max(mtimes) if mtimes else 0.0


# ── Search for previous toolkit installs ──────────────────────────────────────
def _get_search_roots(current_dir: Path) -> list:
    """
    Build search roots at runtime — not at import time.
    Derives the real home dir from current_dir, the USER env var,
    and /etc/passwd as fallbacks, so it works regardless of how the
    script is invoked (sudo, su, direct, from setup.sh, etc.)
    """
    candidates = set()

    # 1. Derive from current_dir itself — most reliable: the install's
    #    parent and grandparent cover the common ~/Github/toolkit-vX.Y.Z layout
    candidates.add(current_dir.parent)          # e.g. ~/Github
    candidates.add(current_dir.parent.parent)   # e.g. ~

    # 2. The real user (not root even if running via sudo)
    real_user = os.environ.get('SUDO_USER') or os.environ.get('USER') or os.environ.get('LOGNAME')
    if real_user and real_user != 'root':
        # Only scan /home/<user> — never /root (permission denied for non-root)
        user_home = Path('/home') / real_user
        for base in [user_home,
                     user_home / 'Github',
                     user_home / 'github',
                     user_home / 'projects',
                     user_home / 'Projects']:
            candidates.add(base)

    # 3. Standard fallbacks — home() is safe, /root is NOT added unless we are root
    try:
        home = Path.home()
        candidates.add(home)
        candidates.add(home / 'Github')
        candidates.add(home / 'github')
        candidates.add(home / 'projects')
        candidates.add(home / 'Projects')
    except Exception:
        pass

    candidates.add(Path('/opt'))
    candidates.add(Path('/srv'))

    # Also check common toolkit locations inside hidden dirs
    # (e.g. ~/.local/share is hidden but toolkits may be installed there via file manager)
    try:
        home = Path.home()
        candidates.add(home / '.local' / 'share' / 'Trash' / 'files')
    except Exception:
        pass
    if real_user and real_user != 'root':
        user_home = Path('/home') / real_user
        candidates.add(user_home / '.local' / 'share' / 'Trash' / 'files')

    # Safe exists() check — PermissionError means "exists but not readable" → skip it
    def _safe_exists(p):
        try:
            return p.exists()
        except (PermissionError, OSError):
            return False

    return [p for p in candidates if _safe_exists(p)]

def _find_data_by_filename(current_dir: Path) -> List[Dict]:
    """Fallback: scan sibling dirs for known data filenames regardless of toolkit structure."""
    found = []
    seen = set()
    data_filenames = {'earnings_history.db', 'sessions_history.db', 'earnings_history.json', 'quality_history.db', 'system_metrics.db', 'service_events.db'}

    search_dirs = [current_dir.parent, current_dir.parent.parent]
    real_user = os.environ.get('SUDO_USER') or os.environ.get('USER') or ''
    if real_user and real_user != 'root':
        home = Path('/home') / real_user
        search_dirs += [home / 'Github', home / 'github', home / 'projects', home]

    for base in search_dirs:
        if not base.exists():
            continue
        try:
            for child in sorted(base.iterdir()):
                if child.resolve() == current_dir.resolve():
                    continue
                key = str(child.resolve())
                if key in seen or not child.is_dir():
                    continue
                seen.add(key)
                config_dir = child / 'config'
                if not config_dir.exists():
                    continue
                if any((config_dir / fn).exists() for fn in data_filenames):
                    found.append({
                        'path':      child.resolve(),
                        'version':   _toolkit_version(child),
                        'mtime':     _toolkit_mtime(child),
                        'snapshots': _count_snapshots(child),
                    })
        except PermissionError:
            pass

    return sorted(found, key=lambda x: (x['snapshots'], x['mtime']), reverse=True)


def find_toolkit_installs(current_dir: Path, max_depth: int = 3) -> List[Dict]:
    """Scan sibling dirs for toolkit data files by filename only."""
    return _find_data_by_filename(current_dir)


def _count_snapshots(path: Path) -> int:
    """Count earnings snapshots from SQLite DB (primary) or JSON (legacy fallback).

    The backend migrated from JSON to SQLite. The DB is the real source of truth —
    the JSON file stopped growing after migration and shows a stale (lower) count.
    """
    # Primary: SQLite earnings_history.db — the real store since migration
    db_file = path / 'config' / 'earnings_history.db'
    if db_file.exists():
        try:
            import sqlite3
            conn = sqlite3.connect(str(db_file), timeout=5)
            row = conn.execute(
                "SELECT COUNT(*) FROM earnings_snapshots WHERE source='identity'"
            ).fetchone()
            conn.close()
            if row and row[0] > 0:
                return int(row[0])
        except Exception:
            pass  # fall through to JSON

    # Fallback: legacy JSON (only present in older installs pre-SQLite migration)
    history_file = path / 'config' / 'earnings_history.json'
    if not history_file.exists():
        return 0
    try:
        data = json.loads(history_file.read_text())
        if isinstance(data, dict):
            snaps = data.get('snapshots', data.get('data', []))
        else:
            snaps = data
        return len(snaps) if isinstance(snaps, list) else 0
    except Exception:
        return 0


# ── Data file helpers ──────────────────────────────────────────────────────────
def _read_json(path: Path):
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def _merge_snapshot_list(dest_data, src_data, key: str):
    """
    Merge two lists of dicts, deduplicating by `key` field.
    Returns merged list sorted by key ascending.
    """
    by_key = {}
    for item in (src_data or []):
        if isinstance(item, dict) and key in item:
            by_key[item[key]] = item
    for item in (dest_data or []):
        if isinstance(item, dict) and key in item:
            by_key[item[key]] = item   # dest wins on collision
    return sorted(by_key.values(), key=lambda x: x.get(key, ''))


def _merge_plain_list(dest_data, src_data):
    """Merge two plain lists, dedup, sort."""
    combined = list(set((src_data or []) + (dest_data or [])))
    try:
        return sorted(combined)
    except TypeError:
        return combined


def _available_data(install_path: Path) -> List[Dict]:
    """Return list of data file defs that exist in install_path.
    Also checks for SQLite DB files which are the primary data store.
    Returns non-empty list if ANY tracked data exists.
    """
    available = []
    for df in DATA_FILES:
        fp = install_path / df['relpath']
        if fp.exists():
            size = fp.stat().st_size
            available.append({**df, 'src_path': fp, 'size': size})

    # Also check SQLite DBs — primary data store since v4+
    # These are NOT in DATA_FILES (copied separately) but their existence
    # means there IS data worth migrating.
    db_sentinel = [
        'config/earnings_history.db',
        'config/sessions_history.db',
        'config/traffic_history.db',
    ]
    for rel in db_sentinel:
        fp = install_path / rel
        if fp.exists() and fp.stat().st_size > 4096:  # >4KB = has real data
            # Add a synthetic entry so the caller knows data exists
            available.append({
                'name': fp.name,
                'relpath': rel,
                'label': f'SQLite data ({fp.name})',
                'merge': '_db_sentinel',  # not used for copy — handled separately
                'src_path': fp,
                'size': fp.stat().st_size,
            })
    return available


def _db_is_empty(db_path: Path, table: str) -> bool:
    """Return True if the SQLite DB at db_path exists but has 0 rows in table.
    Returns False if the DB does not exist (caller handles that separately),
    or if the table doesn't exist, or on any read error.
    An empty placeholder DB must never block migration of real data.
    """
    if not db_path.exists():
        return False
    try:
        import sqlite3
        conn = sqlite3.connect(str(db_path), timeout=5)
        # Check table exists first
        tbl = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if not tbl:
            conn.close()
            return True  # Table missing = effectively empty
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        conn.close()
        return count == 0
    except Exception:
        return False


# ── Core migration logic ───────────────────────────────────────────────────────
def migrate_from_dir(src_dir: Path, dest_dir: Path, force: bool = False,
                     silent: bool = False) -> Dict[str, str]:
    """
    Migrate data files from src_dir into dest_dir/config/.
    Returns dict of {filename: 'migrated'|'merged'|'skipped'|'error'}.
    """
    results = {}
    dest_dir.mkdir(parents=True, exist_ok=True)

    for df in DATA_FILES:
        src = src_dir / df['relpath']
        dst = dest_dir / df['relpath']
        name = df['name']

        if not src.exists():
            results[name] = 'not_in_source'
            continue

        dst.parent.mkdir(parents=True, exist_ok=True)
        strategy = df['merge']

        try:
            if strategy == 'copy_if_missing':
                if dst.exists() and not force:
                    results[name] = 'skipped (already exists)'
                else:
                    shutil.copy2(src, dst)
                    results[name] = 'copied'

            elif strategy == 'json_list_snapshots':
                src_data = _read_json(src)
                if src_data is None:
                    results[name] = 'error: unreadable source'
                    continue

                # Extract snapshots list
                if isinstance(src_data, dict):
                    src_snaps = src_data.get('snapshots', src_data.get('data', []))
                else:
                    src_snaps = src_data

                if dst.exists() and not force:
                    dst_data = _read_json(dst)
                    if isinstance(dst_data, dict):
                        dst_snaps = dst_data.get('snapshots', dst_data.get('data', []))
                    else:
                        dst_snaps = dst_data or []
                    merged = _merge_snapshot_list(dst_snaps, src_snaps, df['key'])
                    # Preserve structure: backend expects {'snapshots': [...]}
                    if isinstance(dst_data, dict):
                        dst_data['snapshots'] = merged
                        _write_json(dst, dst_data)
                    else:
                        _write_json(dst, {'snapshots': merged})
                    delta = len(merged) - len(dst_snaps)
                    results[name] = f'merged (+{max(0,delta)} new snapshots, {len(merged)} total)'
                else:
                    # Fresh — just copy as-is
                    shutil.copy2(src, dst)
                    results[name] = f'copied ({len(src_snaps)} snapshots)'

            elif strategy == 'json_list_dedup':
                src_data = _read_json(src)
                if src_data is None:
                    results[name] = 'error: unreadable source'
                    continue

                if dst.exists() and not force:
                    dst_data = _read_json(dst) or []
                    merged = _merge_plain_list(dst_data, src_data)
                    _write_json(dst, merged)
                    delta = len(merged) - len(dst_data)
                    results[name] = f'merged (+{max(0,delta)} entries, {len(merged)} total)'
                else:
                    shutil.copy2(src, dst)
                    count = len(src_data) if isinstance(src_data, list) else '?'
                    results[name] = f'copied ({count} entries)'

            elif strategy == 'uptime_conditional':
                # Only copy uptime_log if both installs share the same node identity.
                # Same identity = update on the same machine → preserve history.
                # Different identity = different node → start fresh.
                src_identity = src_dir / 'config' / 'node_identity.txt'
                dst_identity = dest_dir / 'config' / 'node_identity.txt'
                same_node = False
                if src_identity.exists() and dst_identity.exists():
                    same_node = (src_identity.read_text().strip() ==
                                 dst_identity.read_text().strip())
                elif src_identity.exists() and not dst_identity.exists():
                    # Destination has no identity yet — assume same machine (update flow)
                    same_node = True

                if same_node:
                    src_data = _read_json(src)
                    if src_data is None:
                        results[name] = 'skipped (unreadable)'
                    elif dst.exists() and not force:
                        dst_data = _read_json(dst) or []
                        merged = _merge_plain_list(dst_data, src_data)
                        _write_json(dst, merged)
                        results[name] = f'merged ({len(merged)} entries — same node)'
                    else:
                        shutil.copy2(src, dst)
                        count = len(src_data) if isinstance(src_data, list) else '?'
                        results[name] = f'copied ({count} entries — same node)'
                else:
                    results[name] = 'skipped (different node identity — starting fresh)'

        except Exception as e:
            results[name] = f'error: {e}'
            if not silent:
                _c(R, '✗', f"  {name}: {e}")

    # earnings_history.db — SQLite earnings snapshot archive
    # Only copy if same node identity — earnings snapshots contain node-specific lifetime totals.
    # IMPORTANT: an empty DB (0 rows) at the destination is treated as non-existent.
    earnings_db_src = src_dir / 'config' / 'earnings_history.db'
    earnings_db_dst = dest_dir / 'config' / 'earnings_history.db'
    if earnings_db_src.exists():
        src_identity = src_dir / 'config' / 'node_identity.txt'
        dst_identity = dest_dir / 'config' / 'node_identity.txt'
        earnings_same_node = False
        if src_identity.exists() and dst_identity.exists():
            earnings_same_node = (src_identity.read_text().strip() ==
                                  dst_identity.read_text().strip())
        elif src_identity.exists() and not dst_identity.exists():
            earnings_same_node = True
        elif not src_identity.exists():
            earnings_same_node = True

        if not earnings_same_node:
            results['earnings_history.db'] = 'skipped (different node identity — earnings belong to source node only)'
        else:
            earnings_db_dst.parent.mkdir(parents=True, exist_ok=True)
            dst_is_empty = _db_is_empty(earnings_db_dst, 'earnings_snapshots')
            if not earnings_db_dst.exists() or dst_is_empty or force:
                try:
                    shutil.copy2(str(earnings_db_src), str(earnings_db_dst))
                    size_kb = earnings_db_src.stat().st_size // 1024
                    reason = 'was empty — overwritten' if dst_is_empty else 'copied'
                    results['earnings_history.db'] = f'{reason} ({size_kb} KB — unlimited earnings history)'
                except Exception as e:
                    results['earnings_history.db'] = f'error: {e}'
            else:
                results['earnings_history.db'] = 'skipped (already exists with data)'

    # sessions_history.db — SQLite session archive
    # Only copy if same node identity — sessions belong to a specific node.
    # Copying sessions from a different node would corrupt the analytics.
    sessions_src = src_dir / 'config' / 'sessions_history.db'
    sessions_dst = dest_dir / 'config' / 'sessions_history.db'
    if sessions_src.exists():
        # Check node identity before copying
        src_identity = src_dir / 'config' / 'node_identity.txt'
        dst_identity = dest_dir / 'config' / 'node_identity.txt'
        sessions_same_node = False
        if src_identity.exists() and dst_identity.exists():
            sessions_same_node = (src_identity.read_text().strip() ==
                                  dst_identity.read_text().strip())
        elif src_identity.exists() and not dst_identity.exists():
            # No identity at destination yet — assume same machine (update flow)
            sessions_same_node = True
        elif not src_identity.exists():
            # No identity file at source — old install, allow copy
            sessions_same_node = True

        if not sessions_same_node:
            results['sessions_history.db'] = 'skipped (different node identity — sessions belong to source node only)'
        else:
            sessions_dst.parent.mkdir(parents=True, exist_ok=True)
            dst_is_empty = _db_is_empty(sessions_dst, 'sessions')
            if not sessions_dst.exists() or dst_is_empty or force:
                try:
                    shutil.copy2(str(sessions_src), str(sessions_dst))
                    size_kb = sessions_src.stat().st_size // 1024
                    reason = 'was empty — overwritten' if dst_is_empty else 'copied'
                    results['sessions_history.db'] = f'{reason} ({size_kb} KB — session earnings archive)'
                except Exception as e:
                    results['sessions_history.db'] = f'error: {e}'
            else:
                results['sessions_history.db'] = 'skipped (already exists with data)'

    # traffic_history.db — SQLite, copy as-is (binary, no merge needed)
    traffic_src = src_dir / 'config' / 'traffic_history.db'
    traffic_dst = dest_dir / 'config' / 'traffic_history.db'
    if traffic_src.exists():
        traffic_dst.parent.mkdir(parents=True, exist_ok=True)
        dst_is_empty = _db_is_empty(traffic_dst, 'daily_traffic')
        if not traffic_dst.exists() or dst_is_empty or force:
            try:
                shutil.copy2(str(traffic_src), str(traffic_dst))
                size_kb = traffic_src.stat().st_size // 1024
                reason = 'was empty — overwritten' if dst_is_empty else 'copied'
                results['traffic_history.db'] = f'{reason} ({size_kb} KB — long-term traffic data)'
            except Exception as e:
                results['traffic_history.db'] = f'error: {e}'
        else:
            results['traffic_history.db'] = 'skipped (already exists with data)'

    # quality_history.db — QualityDB snapshots (new in v1.5.1)
    quality_src = src_dir / 'config' / 'quality_history.db'
    quality_dst = dest_dir / 'config' / 'quality_history.db'
    if quality_src.exists() and not quality_dst.exists():
        quality_dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(str(quality_src), str(quality_dst))
            size_kb = quality_src.stat().st_size // 1024
            results['quality_history.db'] = f'copied ({size_kb} KB — node quality history)'
        except Exception as e:
            results['quality_history.db'] = f'error: {e}'

    # system_metrics.db — SystemMetricsDB snapshots (new in v1.5.1)
    system_src = src_dir / 'config' / 'system_metrics.db'
    system_dst = dest_dir / 'config' / 'system_metrics.db'
    if system_src.exists() and not system_dst.exists():
        system_dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(str(system_src), str(system_dst))
            size_kb = system_src.stat().st_size // 1024
            results['system_metrics.db'] = f'copied ({size_kb} KB — system metrics history)'
        except Exception as e:
            results['system_metrics.db'] = f'error: {e}'

    # service_events.db — ServiceEventsDB events (new in v1.5.1)
    events_src = src_dir / 'config' / 'service_events.db'
    events_dst = dest_dir / 'config' / 'service_events.db'
    if events_src.exists() and not events_dst.exists():
        events_dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(str(events_src), str(events_dst))
            size_kb = events_src.stat().st_size // 1024
            results['service_events.db'] = f'copied ({size_kb} KB — service event log)'
        except Exception as e:
            results['service_events.db'] = f'error: {e}'

    return results


def migrate_from_zip(zip_path: Path, dest_dir: Path, force: bool = False,
                     silent: bool = False) -> Dict[str, str]:
    """
    Extract data files from a toolkit backup zip into dest_dir/config/.
    The zip may contain files at:
      mysterium-toolkit-vX.Y.Z/config/...   (standard zip structure)
      config/...                             (flat config export)
      earnings_history.json etc.            (bare files)
    """
    import tempfile

    if not zip_path.exists():
        return {'error': f'zip not found: {zip_path}'}

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                zf.extractall(tmp_path)
        except Exception as e:
            return {'error': f'could not open zip: {e}'}

        # Find the config dir inside the extracted zip
        config_src = None

        # Strategy 1: look for config/ dir in extracted root
        candidate = tmp_path / 'config'
        if candidate.is_dir():
            config_src = candidate

        # Strategy 2: look for mysterium-toolkit-vX.Y.Z/config/
        if config_src is None:
            for child in tmp_path.iterdir():
                if child.is_dir() and 'mysterium' in child.name.lower():
                    c2 = child / 'config'
                    if c2.is_dir():
                        config_src = c2
                        break

        # Strategy 3: bare files in root
        if config_src is None:
            bare_found = any(
                (tmp_path / df['name']).exists()
                for df in DATA_FILES
            )
            if bare_found:
                config_src = tmp_path

        if config_src is None:
            return {'error': 'no recognisable data files found in zip'}

        # Build a fake src_dir by creating a temp toolkit structure
        fake_src = tmp_path / '_src'
        fake_config = fake_src / 'config'
        fake_config.mkdir(parents=True, exist_ok=True)
        for df in DATA_FILES:
            src_candidate = config_src / df['name']
            if src_candidate.exists():
                shutil.copy2(src_candidate, fake_config / df['name'])

        return migrate_from_dir(fake_src, dest_dir, force=force, silent=silent)


# ── Display helpers ────────────────────────────────────────────────────────────
def _print_results(results: Dict[str, str]):
    for name, status in results.items():
        if status.startswith('error'):
            _c(R, '  ✗', f"{name}: {status}")
        elif status.startswith('skipped') or status == 'not_in_source':
            _c(D + N, '  –', f"{name}: {D}{status}{N}")
        elif status.startswith('merged'):
            _c(G, '  ✓', f"{name}: {status}")
        elif status.startswith('copied'):
            _c(G, '  ✓', f"{name}: {status}")
        else:
            print(f"  • {name}: {status}")


def _describe_source(install: Dict) -> str:
    ts = datetime.fromtimestamp(install['mtime']).strftime('%Y-%m-%d %H:%M') if install['mtime'] else '?'
    return f"{install['path']}  {D}[v{install['version']} · last data: {ts}]{N}"


# ── Export helper (for the export-to-zip feature) ─────────────────────────────
def export_data_zip(src_dir: Path, zip_out: Path) -> bool:
    """
    Create a portable backup zip of all data files from src_dir.
    The zip extracts as config/earnings_history.json etc. (flat).
    """
    files_added = 0
    try:
        zip_out.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_out, 'w', zipfile.ZIP_DEFLATED) as zf:
            for df in DATA_FILES:
                fp = src_dir / df['relpath']
                if fp.exists():
                    zf.write(fp, f"config/{df['name']}")
                    files_added += 1
        return files_added > 0
    except Exception as e:
        _c(R, '✗', f"Export failed: {e}")
        return False


# ── Main flow ──────────────────────────────────────────────────────────────────
def run(args):
    current_dir = Path(args.dest or os.getcwd()).resolve()
    (current_dir / 'config').mkdir(parents=True, exist_ok=True)

    # ── MODE: count-snapshots — print snapshot count for current install ────────
    if getattr(args, 'count_snapshots', False):
        print(_count_snapshots(current_dir))
        return

    # ── MODE: scan-only — print best previous install path for setup.sh ───────
    if args.scan_only:
        installs = find_toolkit_installs(current_dir)
        for inst in installs:
            if _available_data(inst['path']):
                print(f"v{inst['version']} at {inst['path']} ({inst['snapshots']} snapshots)")
                return
        return

    # ── MODE: list-old — list old installs for cleanup prompt in setup.sh ─────
    if getattr(args, 'list_old', False):
        installs = find_toolkit_installs(current_dir)
        for inst in installs:
            size_mb = sum(
                f.stat().st_size for f in inst['path'].rglob('*') if f.is_file()
            ) // (1024 * 1024)
            print(f"v{inst['version']} — {inst['path']} ({size_mb} MB)")
        return

    # ── MODE: remove-old — delete old installs ────────────────────────────────
    if getattr(args, 'remove_old', False):
        import shutil
        installs = find_toolkit_installs(current_dir)
        removed = 0
        for inst in installs:
            try:
                shutil.rmtree(inst['path'])
                _c(G, '✓', f"Removed: {inst['path']}")
                removed += 1
            except Exception as e:
                _c(R, '✗', f"Could not remove {inst['path']}: {e}")
        if removed == 0:
            _c(D + N, '·', 'Nothing to remove.')
        return

    # ── MODE: auto — migrate missing files silently, called from setup.sh ─────
    if args.auto:
        installs = find_toolkit_installs(current_dir)
        best = next((i for i in installs if _available_data(i['path'])), None)
        if best is None:
            return

        _c(C, '·', f"Copying from v{best['version']} ({best['snapshots']} snapshots): {best['path']}")
        results = migrate_from_dir(best['path'], current_dir, force=False, silent=False)
        meaningful = {k: v for k, v in results.items()
                      if not v.startswith('not_in_source') and not v.startswith('skipped')}
        if meaningful:
            _print_results(meaningful)
            _c(G, '✓', 'Data copied.')
        print()
        return

    # ── MODE: interactive — guided, for when setup.sh prompts y/n ────────────
    _box('Mysterium Toolkit — Data Migration')
    print(f"  Destination: {C}{current_dir}{N}\n")

    installs = find_toolkit_installs(current_dir)
    if not installs:
        _c(D + N, '·', 'No previous installations found.')
        return

    best = next((i for i in installs if _available_data(i['path'])), None)
    if best is None:
        _c(D + N, '·', 'Previous installs found but no data files available.')
        return

    # Show all found installs so user can see what was considered
    print(f"  {B}All previous installs found (sorted by tracking data):{N}")
    for i, inst in enumerate(installs):
        marker = f"{G}► best{N}" if inst['path'] == best['path'] else f"{D}  {N}"
        print(f"    {marker} v{inst['version']}  {inst['snapshots']} snapshots  {D}{inst['path']}{N}")
    print()

    available = _available_data(best['path'])
    print(f"  {B}Will copy from: v{best['version']} — {best['path']}{N}")
    for df in available:
        dst = current_dir / df['relpath']
        action = f"{G}merge{N}" if dst.exists() else f"{C}copy{N}"
        print(f"    · {df['label']}  [{action}]")
    print()

    if not _ask('Proceed?', default=True):
        _c(D + N, '·', 'Skipped.')
        return

    results = migrate_from_dir(best['path'], current_dir, force=args.force)
    _print_results(results)
    print()
    _c(G, '✓', 'Done. Restart the backend to apply.')

    # ── MODE: interactive (fresh install or explicit run) ─────────────────────
    _box('Mysterium Toolkit — Data Migration')
    print(f"  Current install: {C}{current_dir}{N}")
    print()

    # Check what data this install already has
    existing = _available_data(current_dir)
    if existing:
        print(f"  {G}Data already present in this install:{N}")
        for df in existing:
            ts = datetime.fromtimestamp((current_dir / df['relpath']).stat().st_mtime).strftime('%Y-%m-%d')
            print(f"    {G}✓{N} {df['label']} ({D}{ts}{N})")
        print()

    # Scan for previous installs
    print(f"  {D}Scanning for previous installations...{N}", end='', flush=True)
    installs = find_toolkit_installs(current_dir)
    print(f"\r  {D}Scan complete.                        {N}")
    print()

    has_installs = bool(installs)
    choice = None

    if has_installs:
        print(f"  {B}Previous installations found:{N}")
        for i, inst in enumerate(installs[:5]):
            avail = _available_data(inst['path'])
            ts = datetime.fromtimestamp(inst['mtime']).strftime('%Y-%m-%d %H:%M') if inst['mtime'] else '?'
            print(f"  {C}[{i+1}]{N} v{inst['version']}  {D}{inst['path']}{N}")
            print(f"       {D}Last data: {ts}  |  {len(avail)} data file(s) available{N}")
        print(f"  {C}[z]{N} Import from a backup zip file")
        print(f"  {C}[s]{N} Skip migration")
        print()
        raw = input(f"  Select source (1-{min(5,len(installs))}/z/s): ").strip().lower()

        if raw == 's' or raw == '':
            _c(D + N, '–', 'Migration skipped.')
            return
        elif raw == 'z':
            choice = 'zip'
        else:
            try:
                idx = int(raw) - 1
                if 0 <= idx < min(5, len(installs)):
                    choice = installs[idx]
                else:
                    _c(Y, '⚠', 'Invalid selection — skipping migration.')
                    return
            except ValueError:
                _c(Y, '⚠', 'Invalid input — skipping migration.')
                return
    else:
        print(f"  {D}No previous installations found automatically.{N}")
        print()
        print(f"  Options:")
        print(f"  {C}[z]{N} Import from a backup zip file")
        print(f"  {C}[s]{N} Skip")
        print()
        raw = input('  Select (z/s): ').strip().lower()
        if raw == 'z':
            choice = 'zip'
        else:
            _c(D + N, '–', 'Migration skipped.')
            return

    # ── ZIP import path ───────────────────────────────────────────────────────
    if choice == 'zip':
        zip_str = input(f"  {C}Path to backup zip:{N} ").strip().strip('"').strip("'")
        zip_path = Path(zip_str).expanduser().resolve()
        if not zip_path.exists():
            _c(R, '✗', f"File not found: {zip_path}")
            return
        print()
        results = migrate_from_zip(zip_path, current_dir, force=args.force)
        _print_results(results)
        _c(G, '✓', 'Import complete.')
        return

    # ── Dir migration path ────────────────────────────────────────────────────
    src_install = choice
    src_dir = src_install['path']
    available = _available_data(src_dir)

    if not available:
        _c(Y, '⚠', 'No data files found in that installation.')
        return

    print()
    print(f"  {B}Files available to migrate from v{src_install['version']}:{N}")
    for df in available:
        dst = current_dir / df['relpath']
        status = f"{G}will merge{N}" if dst.exists() else f"{C}will copy{N}"
        print(f"    • {df['label']}  →  {status}")
    print()

    if not _ask('Proceed with migration?', default=True):
        _c(D + N, '–', 'Migration cancelled.')
        return

    print()
    results = migrate_from_dir(src_dir, current_dir, force=args.force)
    _print_results(results)
    print()
    _c(G, '✓', 'Migration complete. Restart the backend to apply.')


def main():
    parser = argparse.ArgumentParser(
        description='Mysterium Toolkit data migration tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Scan for previous installs (called from setup.sh):
  python3 scripts/migrate_data.py --scan-only --dest /path/to/mysterium-toolkit-v3.17.0

  # Migrate missing files automatically (called from setup.sh):
  python3 scripts/migrate_data.py --auto --dest /path/to/mysterium-toolkit-v3.17.0

  # Interactive guided migration (run manually at any time):
  python3 scripts/migrate_data.py
"""
    )
    parser.add_argument('--auto',      action='store_true',
                        help='Non-interactive: migrate missing files from best found source')
    parser.add_argument('--count-snapshots', action='store_true',
                        help='Print snapshot count for current install and exit')
    parser.add_argument('--scan-only', action='store_true',
                        help='Print path of best previous install and exit')
    parser.add_argument('--dest',      metavar='DIR',
                        help='Destination toolkit dir (default: cwd)')
    parser.add_argument('--force',     action='store_true',
                        help='Overwrite existing destination files')
    parser.add_argument('--list-old',  action='store_true',
                        help='List old toolkit installations for cleanup')
    parser.add_argument('--remove-old', action='store_true',
                        help='Remove old toolkit installations to reclaim disk space')
    args = parser.parse_args()

    try:
        run(args)
    except KeyboardInterrupt:
        print()
        _c(Y, '⚠', 'Migration interrupted — continuing setup.')
    except Exception as e:
        _c(R, '✗', f"Migration error: {e}")
        # Non-fatal — setup.sh continues regardless


if __name__ == '__main__':
    main()
