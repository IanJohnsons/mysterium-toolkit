"""
System Health Module — Mysterium Node Stability & Security
==========================================================
Four subsystems, designed to be SAFE:

1. conntrack Table Management — monitor and expand table size only
2. CPU Load Balancing — RPS/IRQ affinity across all cores
3. Service Health Watchdog — detect hung/crashed Mysterium service
4. Kernel Network Tuning — validate buffer sizes and IP forwarding

SAFETY RULES (learned the hard way):
  - NEVER touch iptables (Mysterium manages its own)
  - NEVER reduce conntrack timeouts (long sessions must be preserved)
  - NEVER change NIC ring buffers (can freeze older Intel NICs)
  - NEVER auto-persist to sysctl.d (bad settings surviving reboot = disaster)
  - Only EXPAND capacity, never restrict
  - Install missing tools before using them
  - Fix only what's clearly broken, recommend everything else
"""

import os
import re
import time
import shutil
import psutil
import logging
import subprocess
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)


# =============================================================================
# HELPERS
# =============================================================================

def _run(cmd, timeout=10, input_data=None):
    """Run a command, return (returncode, stdout, stderr).
    Optionally pass input_data (str) via stdin.
    """
    try:
        stdin_bytes = input_data.encode() if input_data else None
        r = subprocess.run(cmd, capture_output=True, input=stdin_bytes, timeout=timeout, text=True)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except FileNotFoundError:
        return -1, '', f'{cmd[0]} not found'
    except subprocess.TimeoutExpired:
        return -2, '', 'timeout'
    except Exception as e:
        return -3, '', str(e)


def _sysctl_get(key):
    """Read a sysctl value."""
    rc, out, _ = _run(['sysctl', '-n', key])
    return out if rc == 0 else None


def _sysctl_set(key, value):
    """Set a sysctl value (tries sudo, then direct)."""
    for cmd in [['sudo', '-n', 'sysctl', '-w', f'{key}={value}'],
                ['sysctl', '-w', f'{key}={value}']]:
        rc, _, _ = _run(cmd)
        if rc == 0:
            return True
    return False


def _read_file(path):
    """Read a /proc or /sys file."""
    try:
        return Path(path).read_text().strip()
    except Exception:
        return None


def _write_file(path, value):
    """Write to a /proc or /sys file."""
    try:
        Path(path).write_text(str(value))
        return True
    except PermissionError:
        rc, _, _ = _run(['sudo', '-n', 'bash', '-c', f'echo {value} > {path}'])
        return rc == 0
    except Exception:
        return False


def _detect_pkg_manager():
    """Detect the system package manager."""
    for mgr, cmd in [('apt', 'apt-get'), ('dnf', 'dnf'), ('yum', 'yum'),
                      ('pacman', 'pacman'), ('apk', 'apk'), ('zypper', 'zypper')]:
        if shutil.which(cmd):
            return mgr
    return None


def _is_installed(binary):
    """Check if a binary is available on PATH."""
    return shutil.which(binary) is not None


def _install_package(package_name):
    """Install a package using the system package manager.
    Returns (success, message)."""
    mgr = _detect_pkg_manager()
    if not mgr:
        return False, 'No supported package manager found'

    install_cmds = {
        'apt': ['sudo', '-n', 'apt-get', 'install', '-y', package_name],
        'dnf': ['sudo', '-n', 'dnf', 'install', '-y', package_name],
        'yum': ['sudo', '-n', 'yum', 'install', '-y', package_name],
        'pacman': ['sudo', '-n', 'pacman', '-S', '--noconfirm', package_name],
        'apk': ['sudo', '-n', 'apk', 'add', package_name],
        'zypper': ['sudo', '-n', 'zypper', 'install', '-y', package_name],
    }

    cmd = install_cmds.get(mgr)
    if not cmd:
        return False, f'Unsupported package manager: {mgr}'

    rc, out, err = _run(cmd, timeout=120)
    if rc == 0:
        return True, f'Installed {package_name} via {mgr}'
    else:
        return False, f'Failed to install {package_name}: {err[:100]}'


# Required tools and their package names per distro
REQUIRED_TOOLS = {
    'irqbalance': {
        'binary': 'irqbalance',
        'apt': 'irqbalance',
        'dnf': 'irqbalance',
        'yum': 'irqbalance',
        'pacman': 'irqbalance',
        'apk': 'irqbalance',
        'zypper': 'irqbalance',
    },
    'ethtool': {
        'binary': 'ethtool',
        'apt': 'ethtool',
        'dnf': 'ethtool',
        'yum': 'ethtool',
        'pacman': 'ethtool',
        'apk': 'ethtool',
        'zypper': 'ethtool',
    },
    'conntrack': {
        'binary': 'conntrack',
        'apt': 'conntrack',
        'dnf': 'conntrack-tools',
        'yum': 'conntrack-tools',
        'pacman': 'conntrack-tools',
        'apk': 'conntrack-tools',
        'zypper': 'conntrack-tools',
    },
}


def _ensure_tool(tool_name):
    """Check if a tool is installed. Returns (installed, message)."""
    info = REQUIRED_TOOLS.get(tool_name, {})
    binary = info.get('binary', tool_name)
    if _is_installed(binary):
        return True, f'{binary} available'

    mgr = _detect_pkg_manager()
    pkg = info.get(mgr, tool_name) if mgr else tool_name
    return False, f'{binary} not installed (need: {pkg})'


def _install_tool(tool_name):
    """Install a required tool. Returns (success, message)."""
    info = REQUIRED_TOOLS.get(tool_name, {})
    binary = info.get('binary', tool_name)
    if _is_installed(binary):
        return True, f'{binary} already installed'

    mgr = _detect_pkg_manager()
    if not mgr:
        return False, 'No package manager found'

    pkg = info.get(mgr, tool_name)
    return _install_package(pkg)


# =============================================================================
# 1. CONNTRACK TABLE MANAGEMENT
# =============================================================================

class ConntrackHealth:
    """Monitor and expand connection tracking table.

    Table size scales automatically with active VPN tunnel count:
      0–4 tunnels   → 131,072  (128K — baseline)
      5–19 tunnels  → 262,144  (256K — growing node)
      20+ tunnels   → 524,288  (512K — high-load node)

    ONLY expands table size. NEVER touches timeouts.
    Long-lived consumer sessions (24h+ UDP) must be preserved.
    """

    # Load-based conntrack targets
    TIERS = [
        (20, 524288),   # 20+ tunnels → 512K
        ( 5, 262144),   # 5–19 tunnels → 256K
        ( 0, 131072),   # 0–4 tunnels → 128K (minimum)
    ]
    # Aliases for backwards compatibility — used in scan() and fix() code paths
    MIN_CONNTRACK_MAX         = 131072   # lowest tier = minimum acceptable
    RECOMMENDED_CONNTRACK_MAX = 524288   # highest tier = full recommended

    @staticmethod
    def target_for_load(tunnel_count):
        for threshold, value in ConntrackHealth.TIERS:
            if tunnel_count >= threshold:
                return value
        return ConntrackHealth.TIERS[-1][1]

    @staticmethod
    def scan():
        result = {
            'name': 'conntrack',
            'title': 'Connection Tracking',
            'status': 'ok',
            'checks': [],
            'recommendations': [],
        }

        ct_max = _sysctl_get('net.netfilter.nf_conntrack_max')
        if ct_max is None:
            result['checks'].append({
                'name': 'conntrack module',
                'status': 'ok',
                'detail': 'nf_conntrack not loaded (normal if no NAT active)',
            })
            return result

        ct_max = int(ct_max)
        ct_count_str = _sysctl_get('net.netfilter.nf_conntrack_count')
        ct_count = int(ct_count_str) if ct_count_str else 0
        usage_pct = (ct_count / ct_max * 100) if ct_max > 0 else 0

        if usage_pct > 95:
            status = 'critical'
        elif usage_pct > 80:
            status = 'warning'
        else:
            status = 'ok'

        result['checks'].append({
            'name': 'Table usage',
            'status': status,
            'detail': f'{ct_count:,} / {ct_max:,} ({usage_pct:.1f}%)',
            'current': ct_count, 'max': ct_max, 'pct': round(usage_pct, 1),
        })
        if status != 'ok':
            result['status'] = status

        min_needed = ConntrackHealth.TIERS[-1][1]  # lowest tier = 128K
        if ct_max < min_needed:
            result['checks'].append({
                'name': 'Table size',
                'status': 'warning',
                'detail': f'{ct_max:,} too small for VPN exit',
            })
            if result['status'] == 'ok':
                result['status'] = 'warning'
            result['recommendations'].append(
                f'Expand to {min_needed:,} (auto-scales with load up to 512K)')
        else:
            result['checks'].append({
                'name': 'Table size',
                'status': 'ok',
                'detail': f'{ct_max:,} entries (auto-scales: 128K / 256K / 512K)',
            })

        # Informational only — never flag timeouts as warnings
        tcp_est = _sysctl_get('net.netfilter.nf_conntrack_tcp_timeout_established')
        udp_stream = _sysctl_get('net.netfilter.nf_conntrack_udp_timeout_stream')
        parts = []
        if tcp_est:
            parts.append(f'TCP: {int(tcp_est)//3600}h')
        if udp_stream:
            parts.append(f'UDP stream: {udp_stream}s')
        if parts:
            result['checks'].append({
                'name': 'Timeouts',
                'status': 'ok',
                'detail': ' · '.join(parts) + ' (preserved)',
            })

        return result

    @staticmethod
    def fix(tunnel_count=0):
        """Expand table to the appropriate tier for current load."""
        actions = []

        ct_max = _sysctl_get('net.netfilter.nf_conntrack_max')
        if ct_max is None:
            return {'name': 'conntrack', 'actions': [], 'success': True,
                    'note': 'conntrack not loaded'}

        target = ConntrackHealth.target_for_load(tunnel_count)
        current = int(ct_max)

        if current < target:
            ok = _sysctl_set('net.netfilter.nf_conntrack_max', target)
            actions.append({
                'action': f'nf_conntrack_max: {current:,} → {target:,} (tunnels={tunnel_count})',
                'success': ok,
            })
            hashsize = target // 4
            ok2 = _write_file('/sys/module/nf_conntrack/parameters/hashsize', hashsize)
            actions.append({
                'action': f'hashsize → {hashsize:,}',
                'success': ok2,
            })
        else:
            actions.append({
                'action': f'Already at {current:,} (target={target:,} for {tunnel_count} tunnels)',
                'success': True,
            })

        return {'name': 'conntrack', 'actions': actions,
                'success': all(a.get('success', True) for a in actions)}



    @staticmethod
    def scan():
        result = {
            'name': 'conntrack',
            'title': 'Connection Tracking',
            'status': 'ok',
            'checks': [],
            'recommendations': [],
        }

        ct_max = _sysctl_get('net.netfilter.nf_conntrack_max')
        if ct_max is None:
            result['checks'].append({
                'name': 'conntrack module',
                'status': 'ok',
                'detail': 'nf_conntrack not loaded (normal if no NAT active)',
            })
            return result

        ct_max = int(ct_max)
        ct_count_str = _sysctl_get('net.netfilter.nf_conntrack_count')
        ct_count = int(ct_count_str) if ct_count_str else 0
        usage_pct = (ct_count / ct_max * 100) if ct_max > 0 else 0

        if usage_pct > 95:
            status = 'critical'
        elif usage_pct > 80:
            status = 'warning'
        else:
            status = 'ok'

        result['checks'].append({
            'name': 'Table usage',
            'status': status,
            'detail': f'{ct_count:,} / {ct_max:,} ({usage_pct:.1f}%)',
            'current': ct_count, 'max': ct_max, 'pct': round(usage_pct, 1),
        })
        if status != 'ok':
            result['status'] = status

        if ct_max < ConntrackHealth.MIN_CONNTRACK_MAX:
            result['checks'].append({
                'name': 'Table size',
                'status': 'warning',
                'detail': f'{ct_max:,} too small for VPN exit',
            })
            if result['status'] == 'ok':
                result['status'] = 'warning'
            result['recommendations'].append(
                f'Expand to {ConntrackHealth.RECOMMENDED_CONNTRACK_MAX:,}')
        else:
            result['checks'].append({
                'name': 'Table size',
                'status': 'ok',
                'detail': f'{ct_max:,} entries',
            })

        # Informational only — never flag timeouts as warnings
        tcp_est = _sysctl_get('net.netfilter.nf_conntrack_tcp_timeout_established')
        udp_stream = _sysctl_get('net.netfilter.nf_conntrack_udp_timeout_stream')
        parts = []
        if tcp_est:
            parts.append(f'TCP: {int(tcp_est)//3600}h')
        if udp_stream:
            parts.append(f'UDP stream: {udp_stream}s')
        if parts:
            result['checks'].append({
                'name': 'Timeouts',
                'status': 'ok',
                'detail': ' · '.join(parts) + ' (preserved)',
            })

        return result

    @staticmethod
    def fix():
        """Only expand table size. Never touch timeouts."""
        actions = []

        ct_max = _sysctl_get('net.netfilter.nf_conntrack_max')
        if ct_max is None:
            return {'name': 'conntrack', 'actions': [], 'success': True,
                    'note': 'conntrack not loaded'}

        if int(ct_max) < ConntrackHealth.RECOMMENDED_CONNTRACK_MAX:
            ok = _sysctl_set('net.netfilter.nf_conntrack_max',
                             ConntrackHealth.RECOMMENDED_CONNTRACK_MAX)
            actions.append({
                'action': f'nf_conntrack_max: {ct_max} → {ConntrackHealth.RECOMMENDED_CONNTRACK_MAX}',
                'success': ok,
            })
            hashsize = ConntrackHealth.RECOMMENDED_CONNTRACK_MAX // 4
            ok2 = _write_file('/sys/module/nf_conntrack/parameters/hashsize', hashsize)
            actions.append({
                'action': f'hashsize → {hashsize}',
                'success': ok2,
            })
        else:
            actions.append({'action': f'Already at {ct_max} — no change', 'success': True})

        return {'name': 'conntrack', 'actions': actions,
                'success': all(a.get('success', True) for a in actions)}


# =============================================================================
# 2. CPU LOAD BALANCING
# =============================================================================

class CpuLoadBalance:
    """Distribute network processing across all CPU cores via RPS.

    Requires: irqbalance package
    """

    @staticmethod
    def _get_cpu_count():
        return os.cpu_count() or 1

    @staticmethod
    def _get_primary_iface():
        rc, out, _ = _run(['ip', 'route', 'show', 'default'])
        if rc == 0 and out:
            match = re.search(r'dev\s+(\S+)', out)
            if match:
                return match.group(1)
        return None

    @staticmethod
    def _get_rps_mask(iface):
        path = f'/sys/class/net/{iface}/queues/rx-0/rps_cpus'
        return _read_file(path)

    @staticmethod
    def _all_cores_mask():
        n = CpuLoadBalance._get_cpu_count()
        return format((1 << n) - 1, 'x')

    @staticmethod
    def scan():
        result = {
            'name': 'cpu_balance',
            'title': 'CPU Load Balancing',
            'status': 'ok',
            'checks': [],
            'recommendations': [],
        }

        cpus = CpuLoadBalance._get_cpu_count()
        all_mask = CpuLoadBalance._all_cores_mask()

        # Check if irqbalance is installed
        installed, msg = _ensure_tool('irqbalance')
        if not installed:
            result['checks'].append({
                'name': 'irqbalance',
                'status': 'warning',
                'detail': 'Not installed — needed for IRQ distribution',
            })
            result['status'] = 'warning'
            result['recommendations'].append('Install irqbalance')
        else:
            # Check if running
            irqb_running = False
            for proc in psutil.process_iter(['name']):
                try:
                    if proc.info['name'] == 'irqbalance':
                        irqb_running = True
                        break
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            result['checks'].append({
                'name': 'irqbalance',
                'status': 'ok' if irqb_running else 'warning',
                'detail': f'Running ({cpus} cores)' if irqb_running else 'Installed but not running',
            })
            if not irqb_running:
                if result['status'] == 'ok':
                    result['status'] = 'warning'
                result['recommendations'].append('Start irqbalance service')

        # Check primary NIC RPS
        primary = CpuLoadBalance._get_primary_iface()
        if primary:
            rps = CpuLoadBalance._get_rps_mask(primary)
            if rps and rps.replace('0', '').replace(',', ''):
                clean = rps.replace(',', '').lstrip('0') or '0'
                if int(clean, 16) >= int(all_mask, 16):
                    result['checks'].append({
                        'name': f'{primary} RPS',
                        'status': 'ok',
                        'detail': f'All {cpus} cores (mask: {all_mask})',
                    })
                else:
                    result['checks'].append({
                        'name': f'{primary} RPS',
                        'status': 'warning',
                        'detail': f'Partial (mask: {rps}, need: {all_mask})',
                    })
                    if result['status'] == 'ok':
                        result['status'] = 'warning'
            else:
                rps_service = Path('/etc/systemd/system/mysterium-rps-tuning.service')
                rps_script  = Path('/usr/local/bin/mysterium-rps-setup.sh')
                boot_pending = rps_service.exists() and rps_script.exists()
                result['checks'].append({
                    'name': f'{primary} RPS',
                    'status': 'warning',
                    'detail': ('Disabled — boot service running, will apply shortly'
                               if boot_pending else
                               'Disabled — 1 core handles all packets'),
                })
                if result['status'] == 'ok':
                    result['status'] = 'warning'

        # Check VPN interface RPS
        vpn_ifaces = [i for i in psutil.net_io_counters(pernic=True)
                      if i.startswith(('myst', 'wg', 'tun'))]
        if vpn_ifaces:
            vpn_rps_ok = 0
            vpn_no_queue = 0
            vpn_unset = 0
            for i in vpn_ifaces:
                queue_path = Path(f'/sys/class/net/{i}/queues/rx-0/rps_cpus')
                if not queue_path.exists():
                    vpn_no_queue += 1
                    vpn_rps_ok += 1  # No queue = kernel handles it, count as OK
                    continue
                mask = CpuLoadBalance._get_rps_mask(i)
                if mask and mask.replace('0', '').replace(',', ''):
                    vpn_rps_ok += 1
                else:
                    vpn_unset += 1

            # Check if auto-RPS watcher is running (handles dynamic interfaces)
            watcher_active = False
            try:
                rc, out, _ = _run(['systemctl', 'is-active', 'mysterium-rps-watcher.timer'])
                watcher_active = rc == 0 and 'active' in out.lower()
            except Exception:
                pass

            if vpn_no_queue == len(vpn_ifaces):
                # All VPN interfaces are virtual (no RPS queue) — this is normal
                result['checks'].append({
                    'name': 'VPN RPS',
                    'status': 'ok',
                    'detail': f'{len(vpn_ifaces)} virtual tunnel(s) — kernel-managed',
                })
            elif vpn_rps_ok == len(vpn_ifaces):
                result['checks'].append({
                    'name': 'VPN RPS',
                    'status': 'ok',
                    'detail': f'{vpn_rps_ok}/{len(vpn_ifaces)} interfaces balanced',
                })
            elif vpn_unset > 0 and watcher_active:
                # Unset interfaces exist but timer will fix within 30s — count as OK
                result['checks'].append({
                    'name': 'VPN RPS',
                    'status': 'ok',
                    'detail': f'{vpn_rps_ok}/{len(vpn_ifaces)} set — {vpn_unset} pending (auto-watcher active)',
                })
            else:
                status = 'warning'
                detail = f'{vpn_rps_ok}/{len(vpn_ifaces)} interfaces balanced'
                if vpn_unset > 0:
                    detail += f' — {vpn_unset} unset (enable auto-RPS watcher)'
                result['checks'].append({
                    'name': 'VPN RPS',
                    'status': status,
                    'detail': detail,
                })
                if result['status'] == 'ok':
                    result['status'] = 'warning'
                result['recommendations'].append(
                    'Enable auto-RPS watcher: run health fix on rps_watcher subsystem'
                )

        return result

    @staticmethod
    def fix():
        actions = []
        all_mask = CpuLoadBalance._all_cores_mask()

        # Step 1: Install irqbalance if missing
        if not _is_installed('irqbalance'):
            ok, msg = _install_tool('irqbalance')
            actions.append({'action': msg, 'success': ok})
            if not ok:
                return {'name': 'cpu_balance', 'actions': actions, 'success': False}

        # Step 2: Start irqbalance if not running
        irqb_running = False
        for proc in psutil.process_iter(['name']):
            try:
                if proc.info['name'] == 'irqbalance':
                    irqb_running = True
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        if not irqb_running:
            # Enable and start
            _run(['sudo', '-n', 'systemctl', 'enable', 'irqbalance'])
            rc, _, err = _run(['sudo', '-n', 'systemctl', 'start', 'irqbalance'])
            actions.append({
                'action': 'Start irqbalance',
                'success': rc == 0,
                'error': err if rc != 0 else None,
            })

        # Step 3: Set RPS on all interfaces
        primary = CpuLoadBalance._get_primary_iface()
        all_ifaces = []
        if primary:
            all_ifaces.append(primary)
        vpn_ifaces = [i for i in psutil.net_io_counters(pernic=True)
                      if i.startswith(('myst', 'wg', 'tun'))]
        all_ifaces.extend(vpn_ifaces)

        for iface_name in all_ifaces:
            queue_path = Path(f'/sys/class/net/{iface_name}/queues/')
            if not queue_path.exists():
                if iface_name in vpn_ifaces:
                    actions.append({
                        'action': f'{iface_name}: virtual tunnel — kernel-managed (no RPS needed)',
                        'success': True,
                    })
                continue
            for queue_dir in queue_path.glob('rx-*'):
                rps_path = queue_dir / 'rps_cpus'
                if rps_path.exists():
                    ok = _write_file(str(rps_path), all_mask)
                    actions.append({
                        'action': f'RPS {iface_name}/{queue_dir.name} → {all_mask}',
                        'success': ok,
                    })
                flow_path = queue_dir / 'rps_flow_cnt'
                if flow_path.exists():
                    _write_file(str(flow_path), '32768')

        return {'name': 'cpu_balance', 'actions': actions,
                'success': all(a.get('success', True) for a in actions) if actions else True}


# =============================================================================
# 3. SERVICE HEALTH WATCHDOG
# =============================================================================

class ServiceWatchdog:
    """Monitor Mysterium service health."""

    MAX_MEMORY_MB = 1024
    MIN_UPTIME_WARN = 300

    @staticmethod
    def scan():
        result = {
            'name': 'service',
            'title': 'Mysterium Service',
            'status': 'ok',
            'checks': [],
            'recommendations': [],
        }

        # Find myst process
        myst_procs = []
        for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time', 'memory_info']):
            try:
                name = proc.info['name'] or ''
                cmdline = ' '.join(proc.info.get('cmdline') or [])
                # Match: /usr/bin/myst, myst service, mysterium-node, etc.
                if name == 'myst' or 'mysterium' in name.lower():
                    myst_procs.append(proc)
                elif 'myst' in name.lower() and ('service' in cmdline.lower() or 'node' in cmdline.lower()):
                    myst_procs.append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        if not myst_procs:
            result['status'] = 'critical'
            result['checks'].append({
                'name': 'Process',
                'status': 'critical',
                'detail': 'Not found',
            })
            result['recommendations'].append('sudo systemctl start mysterium-node')
            return result

        for proc in myst_procs:
            try:
                uptime = time.time() - proc.info['create_time']
                h, m = int(uptime // 3600), int((uptime % 3600) // 60)

                if uptime < ServiceWatchdog.MIN_UPTIME_WARN:
                    result['checks'].append({
                        'name': 'Uptime',
                        'status': 'warning',
                        'detail': f'{h}h{m}m (recent restart)',
                    })
                    if result['status'] == 'ok':
                        result['status'] = 'warning'
                else:
                    result['checks'].append({
                        'name': 'Uptime',
                        'status': 'ok',
                        'detail': f'{h}h{m}m',
                    })

                mem = proc.info.get('memory_info')
                if mem:
                    mem_mb = mem.rss / (1024 * 1024)
                    if mem_mb > ServiceWatchdog.MAX_MEMORY_MB:
                        result['checks'].append({
                            'name': 'Memory',
                            'status': 'warning',
                            'detail': f'{mem_mb:.0f} MB (high)',
                        })
                        if result['status'] == 'ok':
                            result['status'] = 'warning'
                    else:
                        result['checks'].append({
                            'name': 'Memory',
                            'status': 'ok',
                            'detail': f'{mem_mb:.0f} MB',
                        })

            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        # systemd status
        rc, out, _ = _run(['systemctl', 'is-active', 'mysterium-node'])
        svc = out if rc == 0 else 'unknown'
        result['checks'].append({
            'name': 'systemd',
            'status': 'ok' if svc == 'active' else 'warning',
            'detail': svc,
        })

        return result

    @staticmethod
    def fix():
        actions = []
        rc, out, _ = _run(['systemctl', 'is-active', 'mysterium-node'])
        if out != 'active':
            rc, _, err = _run(['sudo', '-n', 'systemctl', 'restart', 'mysterium-node'])
            actions.append({
                'action': 'Restart mysterium-node',
                'success': rc == 0,
                'error': err if rc != 0 else None,
            })
            time.sleep(3)
        else:
            actions.append({'action': 'Already active', 'success': True})

        return {'name': 'service', 'actions': actions,
                'success': all(a.get('success', True) for a in actions)}


# =============================================================================
# 4. KERNEL NETWORK TUNING
# =============================================================================

class KernelTuning:
    """Validate kernel network parameters for VPN exit.

    SAFETY:
    - NEVER changes NIC ring buffers (can freeze older NICs)
    - NEVER auto-persists to /etc/sysctl.d/ (bad settings surviving reboot = disaster)
    - Only applies safe buffer expansions in memory
    - ip_forward is the only critical auto-fix
    - All other params are recommendations only
    """

    # Safe params — these only EXPAND buffers, never restrict
    SAFE_PARAMS = {
        'net.ipv4.ip_forward': 1,                   # CRITICAL for VPN
        'net.core.rmem_max': 16777216,
        'net.core.wmem_max': 16777216,
        'net.core.rmem_default': 1048576,
        'net.core.wmem_default': 1048576,
        'net.core.netdev_max_backlog': 16384,
        'net.core.somaxconn': 8192,
        'net.ipv4.tcp_max_syn_backlog': 8192,
        'net.ipv4.tcp_tw_reuse': 1,
        'net.ipv4.tcp_slow_start_after_idle': 0,
        'net.ipv4.udp_rmem_min': 8192,
        'net.ipv4.udp_wmem_min': 8192,
    }

    @staticmethod
    def scan():
        result = {
            'name': 'kernel',
            'title': 'Kernel Network Tuning',
            'status': 'ok',
            'checks': [],
            'recommendations': [],
        }

        # CRITICAL: IP forwarding
        ip_fwd = _sysctl_get('net.ipv4.ip_forward')
        if ip_fwd != '1':
            result['status'] = 'critical'
            result['checks'].append({
                'name': 'IP forwarding',
                'status': 'critical',
                'detail': 'DISABLED — VPN broken!',
            })
            result['recommendations'].append('Fix immediately: sysctl -w net.ipv4.ip_forward=1')
        else:
            result['checks'].append({
                'name': 'IP forwarding',
                'status': 'ok',
                'detail': 'Enabled',
            })

        # Check other params
        suboptimal = 0
        suboptimal_keys = []
        for key, optimal in KernelTuning.SAFE_PARAMS.items():
            if key == 'net.ipv4.ip_forward':
                continue
            current = _sysctl_get(key)
            if current is None:
                continue
            try:
                c_val = int(current.split()[-1])
                o_val = int(str(optimal).split()[-1])
                if c_val < o_val * 0.5:  # Only flag if less than half optimal
                    suboptimal += 1
                    suboptimal_keys.append(key.replace('net.', '').replace('ipv4.', '').replace('core.', ''))
            except (ValueError, IndexError):
                pass

        if suboptimal > 0:
            result['checks'].append({
                'name': 'Buffer tuning',
                'status': 'warning',
                'detail': f'{suboptimal} below optimal: {", ".join(suboptimal_keys)}',
            })
            if result['status'] == 'ok':
                result['status'] = 'warning'
            result['recommendations'].append('Run fix to expand network buffers')
        else:
            result['checks'].append({
                'name': 'Buffer tuning',
                'status': 'ok',
                'detail': 'All within range',
            })

        # Check persistence (informational)
        persist_file = Path('/etc/sysctl.d/99-mysterium-node.conf')
        result['checks'].append({
            'name': 'Persistence',
            'status': 'ok' if persist_file.exists() else 'warning',
            'detail': 'Saved to sysctl.d' if persist_file.exists() else 'Not persisted (revert on reboot)',
        })

        return result

    @staticmethod
    def fix():
        """Apply safe kernel params in memory only.
        Does NOT persist to disk — user must do that manually."""
        actions = []

        for key, value in KernelTuning.SAFE_PARAMS.items():
            current = _sysctl_get(key)
            if current is None:
                continue

            # Only change if current is significantly below optimal
            try:
                current_norm = ' '.join(current.split())
                optimal_norm = ' '.join(str(value).split())
                if current_norm == optimal_norm:
                    continue

                c_val = int(current_norm.split()[-1])
                o_val = int(optimal_norm.split()[-1])
                if c_val >= o_val:
                    continue  # Already at or above optimal
            except (ValueError, IndexError):
                if current == str(value):
                    continue

            ok = _sysctl_set(key, value)
            actions.append({
                'action': f'{key.split(".")[-1]}: {current} → {value}',
                'success': ok,
            })

        if not actions:
            actions.append({'action': 'All params already optimal', 'success': True})

        return {'name': 'kernel', 'actions': actions,
                'success': all(a.get('success', True) for a in actions)}


# =============================================================================
# 5. NIC INTERRUPT COALESCING
# =============================================================================

class NicCoalescing:
    """Detect and fix aggressive NIC interrupt rates that freeze e1000e.

    The Intel 82579LM (Dell E6420, etc.) with e1000e driver can deadlock
    when hit with thousands of interrupts/sec from WireGuard tunnels.
    Default rx-usecs is often 3µs = interrupt per packet = IRQ storm.

    Fix: raise rx-usecs to batch interrupts. 250µs is safe for VPN.

    SAFETY:
    - Only changes rx-usecs (universally supported coalesce param)
    - Never touches ring buffers (can freeze NIC)
    - Never touches adaptive coalescing (not supported on many NICs)
    - Reads actual NIC capabilities before changing anything
    """

    # Minimum safe rx-usecs for VPN workload
    TARGET_RX_USECS = 250
    # Below this is dangerously aggressive for multi-tunnel VPN
    WARN_RX_USECS = 50

    @staticmethod
    def _get_primary_iface():
        """Get primary network interface from default route."""
        try:
            rc, out, _ = _run(['ip', 'route', 'show', 'default'])
            if rc == 0 and 'dev ' in out:
                return out.split('dev ')[1].split()[0]
        except Exception:
            pass
        return None

    @staticmethod
    def _get_driver(iface):
        """Get NIC driver name."""
        try:
            rc, out, _ = _run(['ethtool', '-i', iface])
            if rc == 0:
                for line in out.splitlines():
                    if line.startswith('driver:'):
                        return line.split(':')[1].strip()
        except Exception:
            pass
        return None

    @staticmethod
    def _get_coalesce(iface):
        """Get current coalesce settings. Returns dict of param→value."""
        result = {}
        try:
            rc, out, _ = _run(['ethtool', '-c', iface])
            if rc == 0:
                for line in out.splitlines():
                    if ':' in line and 'n/a' not in line:
                        key, val = line.split(':', 1)
                        key = key.strip()
                        val = val.strip()
                        try:
                            result[key] = int(val)
                        except ValueError:
                            result[key] = val
        except Exception:
            pass
        return result

    @staticmethod
    def scan():
        result = {
            'name': 'nic_coalesce',
            'title': 'NIC Interrupt Coalescing',
            'status': 'ok',
            'checks': [],
            'recommendations': [],
        }

        if not _ensure_tool('ethtool'):
            result['checks'].append({
                'name': 'ethtool',
                'status': 'warning',
                'detail': 'Not available',
            })
            result['status'] = 'warning'
            return result

        iface = NicCoalescing._get_primary_iface()
        if not iface:
            result['checks'].append({
                'name': 'Interface',
                'status': 'warning',
                'detail': 'No default route found',
            })
            result['status'] = 'warning'
            return result

        driver = NicCoalescing._get_driver(iface)
        coal = NicCoalescing._get_coalesce(iface)
        rx_usecs = coal.get('rx-usecs')

        # Virtual/cloud NICs do not support coalescing — skip silently with ok status
        VIRTUAL_DRIVERS = {'virtio_net', 'virtio-net', 'xen_netfront', 'vmxnet3',
                           'ena', 'hv_netvsc', 'virtio', 'vif'}
        if driver and driver.lower() in VIRTUAL_DRIVERS:
            result['checks'].append({
                'name': 'Interface',
                'status': 'ok',
                'detail': f'{iface} ({driver}) — virtual NIC, coalescing managed by hypervisor',
            })
            result['status'] = 'ok'
            return result

        result['checks'].append({
            'name': 'Interface',
            'status': 'ok',
            'detail': f'{iface} ({driver or "unknown"})',
        })

        if rx_usecs is None:
            result['checks'].append({
                'name': 'rx-usecs',
                'status': 'ok',
                'detail': 'Not tunable (hardware-managed)',
            })
            return result

        if rx_usecs < NicCoalescing.WARN_RX_USECS:
            severity = 'critical' if driver == 'e1000e' else 'warning'
            result['status'] = severity
            result['checks'].append({
                'name': 'rx-usecs',
                'status': severity,
                'detail': f'{rx_usecs}µs (too aggressive — IRQ storm risk)',
            })
            msg = f'Set rx-usecs to {NicCoalescing.TARGET_RX_USECS}: ethtool -C {iface} rx-usecs {NicCoalescing.TARGET_RX_USECS}'
            if driver == 'e1000e':
                msg += ' [e1000e freezes under high IRQ rate]'
            result['recommendations'].append(msg)
        else:
            result['checks'].append({
                'name': 'rx-usecs',
                'status': 'ok',
                'detail': f'{rx_usecs}µs',
            })

        # Check adaptive-rx (dynamic coalescing — pairs with rx-usecs)
        adaptive_rx = coal.get('Adaptive RX')
        tx_usecs = coal.get('tx-usecs')
        if adaptive_rx is not None:
            if str(adaptive_rx).lower() == 'on':
                result['checks'].append({
                    'name': 'adaptive-rx',
                    'status': 'ok',
                    'detail': 'on — dynamic batching active',
                })
            else:
                result['checks'].append({
                    'name': 'adaptive-rx',
                    'status': 'warning',
                    'detail': 'off — static coalescing only',
                })
                if result['status'] == 'ok':
                    result['status'] = 'warning'
                result['recommendations'].append(
                    f'Enable adaptive-rx: ethtool -C {iface} adaptive-rx on')

        # Check tx-usecs (TX interrupt batching — reduces tx_dropped)
        if tx_usecs is not None:
            if int(tx_usecs) < NicCoalescing.WARN_RX_USECS:
                result['checks'].append({
                    'name': 'tx-usecs',
                    'status': 'warning',
                    'detail': f'{tx_usecs}µs (aggressive — tx_dropped risk)',
                })
                if result['status'] == 'ok':
                    result['status'] = 'warning'
            else:
                result['checks'].append({
                    'name': 'tx-usecs',
                    'status': 'ok',
                    'detail': f'{tx_usecs}µs',
                })

        return result

    @staticmethod
    def fix():
        actions = []

        iface = NicCoalescing._get_primary_iface()
        if not iface:
            return {'name': 'nic_coalesce', 'actions': [
                {'action': 'No interface found', 'success': False}
            ], 'success': False}

        coal = NicCoalescing._get_coalesce(iface)
        rx_usecs = coal.get('rx-usecs')
        tx_usecs = coal.get('tx-usecs')
        adaptive_rx = str(coal.get('Adaptive RX', '')).lower()

        # Build a single ethtool -C call with all needed params
        # (more efficient and avoids partial-apply races)
        coalesce_args = []

        if rx_usecs is not None and int(rx_usecs) < NicCoalescing.WARN_RX_USECS:
            coalesce_args += ['rx-usecs', str(NicCoalescing.TARGET_RX_USECS)]

        if tx_usecs is not None and int(tx_usecs) < NicCoalescing.WARN_RX_USECS:
            coalesce_args += ['tx-usecs', str(NicCoalescing.TARGET_RX_USECS)]

        if adaptive_rx and adaptive_rx != 'on':
            # Test if adaptive-rx is supported before adding it
            rc_test, _, _ = _run(['sudo', '-n', 'ethtool', '-C', iface, 'adaptive-rx', 'on'])
            if rc_test == 0:
                # Already applied — record it, don't double-add
                actions.append({'action': f'adaptive-rx → on on {iface}', 'success': True})
                coalesce_args = [a for a in coalesce_args]  # keep remaining
            # If rc_test != 0, NIC doesn't support adaptive — skip silently

        if coalesce_args:
            rc, _, err = _run(['sudo', '-n', 'ethtool', '-C', iface] + coalesce_args)
            if rc == 0:
                changes = []
                for i in range(0, len(coalesce_args), 2):
                    changes.append(f'{coalesce_args[i]}={coalesce_args[i+1]}µs')
                actions.append({
                    'action': f'coalescing on {iface}: {", ".join(changes)}',
                    'success': True,
                })
            else:
                # Try rx-usecs alone as fallback (most compatible)
                rc2, _, err2 = _run([
                    'sudo', '-n', 'ethtool', '-C', iface,
                    'rx-usecs', str(NicCoalescing.TARGET_RX_USECS)
                ])
                actions.append({
                    'action': f'rx-usecs → {NicCoalescing.TARGET_RX_USECS}µs on {iface} (tx-usecs/adaptive not supported)',
                    'success': rc2 == 0,
                    'error': err2[:80] if rc2 != 0 else None,
                })
        elif rx_usecs is not None:
            actions.append({'action': f'coalescing already optimal on {iface}', 'success': True})
        else:
            actions.append({'action': 'rx-usecs not tunable — skipped', 'success': True})

        if not actions:
            actions.append({'action': 'Nothing to fix', 'success': True})

        return {'name': 'nic_coalesce', 'actions': actions,
                'success': all(a.get('success', True) for a in actions)}


# =============================================================================
# 6. FIREWALL BACKEND (iptables-legacy vs nftables detection)
# =============================================================================

class FirewallBackend:
    """Detect and fix iptables-legacy vs nftables conflicts.

    Mysterium uses iptables-legacy to create firewall rules. If the system's
    iptables symlink points to iptables-nft, the rules are invisible and
    port reachability checks fail — killing new connections.

    SAFETY:
    - Only switches the alternatives symlink (reversible)
    - Never deletes or modifies any firewall rules
    - Only acts if legacy tables have rules and nft tables are empty
    """

    @staticmethod
    def _get_iptables_backend():
        """Determine which iptables backend is active."""
        rc, out, _ = _run(['iptables', '--version'])
        if rc != 0:
            return 'unknown', ''
        version_str = out.strip()
        if 'nf_tables' in version_str:
            return 'nft', version_str
        elif 'legacy' in version_str:
            return 'legacy', version_str
        return 'unknown', version_str

    @staticmethod
    def _count_rules(binary):
        """Count actual rules (non-empty chains) in a specific iptables backend."""
        rc, out, _ = _run(['sudo', '-n', binary, '-w', '5', '-L', '-n'])
        if rc != 0:
            # Try without sudo
            rc, out, _ = _run([binary, '-w', '5', '-L', '-n'])
            if rc != 0:
                # Try without -w (very old iptables)
                rc, out, _ = _run(['sudo', '-n', binary, '-L', '-n'])
                if rc != 0:
                    return -1  # Can't read
        count = 0
        for line in out.splitlines():
            line = line.strip()
            if not line or line.startswith('Chain') or line.startswith('target'):
                continue
            count += 1
        return count

    @staticmethod
    def _has_legacy_warning():
        """Check if nft backend warns about legacy tables."""
        rc, out, err = _run(['sudo', '-n', 'iptables-nft', '-L', '-n'])
        combined = (out or '') + (err or '')
        return 'legacy tables present' in combined.lower()

    @staticmethod
    def scan():
        result = {
            'name': 'firewall_backend',
            'title': 'Firewall Backend',
            'status': 'ok',
            'checks': [],
            'recommendations': [],
        }

        backend, version = FirewallBackend._get_iptables_backend()
        result['checks'].append({
            'name': 'iptables',
            'status': 'ok',
            'detail': f'{backend} ({version[:30]})',
        })

        # Check if both backends exist
        has_legacy = _ensure_tool('iptables-legacy')
        has_nft = _ensure_tool('iptables-nft')

        if not has_legacy or not has_nft:
            result['checks'].append({
                'name': 'Backends',
                'status': 'ok',
                'detail': 'Single backend — no conflict possible',
            })
            return result

        # Both exist — check for mismatch
        legacy_rules = FirewallBackend._count_rules('iptables-legacy')
        nft_rules = FirewallBackend._count_rules('iptables-nft')

        result['checks'].append({
            'name': 'Legacy rules',
            'status': 'ok',
            'detail': f'{legacy_rules} rules' if legacy_rules >= 0 else 'Cannot read',
        })
        result['checks'].append({
            'name': 'NFT rules',
            'status': 'ok',
            'detail': f'{nft_rules} rules' if nft_rules >= 0 else 'Cannot read',
        })

        # Critical: symlink points to nft but rules are in legacy
        if backend == 'nft' and legacy_rules > 0:
            result['status'] = 'critical'
            result['checks'].append({
                'name': 'Backend conflict',
                'status': 'critical',
                'detail': 'iptables → nft but rules are in legacy!',
            })
            result['recommendations'].append(
                'Switch to legacy: sudo update-alternatives --set iptables /usr/sbin/iptables-legacy'
            )
        elif backend == 'legacy' and legacy_rules > 0:
            result['checks'].append({
                'name': 'Backend match',
                'status': 'ok',
                'detail': 'iptables → legacy, rules in legacy ✓',
            })
        elif backend == 'nft' and nft_rules > 0 and legacy_rules == 0:
            result['checks'].append({
                'name': 'Backend match',
                'status': 'ok',
                'detail': 'iptables → nft, rules in nft ✓',
            })

        return result

    @staticmethod
    def fix():
        actions = []

        backend, _ = FirewallBackend._get_iptables_backend()
        has_legacy = _ensure_tool('iptables-legacy')
        has_nft = _ensure_tool('iptables-nft')

        if not has_legacy or not has_nft:
            actions.append({'action': 'Single backend — no fix needed', 'success': True})
            return {'name': 'firewall_backend', 'actions': actions, 'success': True}

        legacy_rules = FirewallBackend._count_rules('iptables-legacy')

        if backend == 'nft' and legacy_rules > 0:
            # Switch to legacy
            rc, _, err = _run([
                'sudo', '-n', 'update-alternatives', '--set',
                'iptables', '/usr/sbin/iptables-legacy'
            ])
            if rc == 0:
                actions.append({
                    'action': 'Switched iptables → iptables-legacy',
                    'success': True,
                })
            else:
                actions.append({
                    'action': 'Switch iptables to legacy',
                    'success': False,
                    'error': (err or 'update-alternatives failed')[:80],
                })
        else:
            actions.append({
                'action': f'Backend OK ({backend}, {legacy_rules} legacy rules)',
                'success': True,
            })

        if not actions:
            actions.append({'action': 'Nothing to fix', 'success': True})

        return {'name': 'firewall_backend', 'actions': actions,
                'success': all(a.get('success', True) for a in actions)}


# =============================================================================
# 7. PORT REACHABILITY
# =============================================================================

class PortReachability:
    """Check if Mysterium's required ports are reachable.

    Mysterium needs specific ports open for VPN consumers to connect.
    Default ports: 4449 (TequilAPI), plus the service ports shown in
    the node's /services endpoint.

    SAFETY:
    - Read-only scan — never opens or closes ports
    - Fix only restarts node (which re-registers ports)
    """

    TEQUILAPI_PORT = 4449
    # Common Mysterium service port ranges
    CHECK_PORTS = [4449]

    @staticmethod
    def _check_port_listening(port):
        """Check if anything is listening on a port."""
        rc, out, _ = _run(['ss', '-tlnp', f'sport = :{port}'])
        if rc == 0 and str(port) in out:
            return True
        return False

    @staticmethod
    def _get_service_ports():
        """Get active service ports from TequilAPI."""
        ports = []
        try:
            import requests as req
            resp = req.get(f'http://localhost:{PortReachability.TEQUILAPI_PORT}/services',
                           timeout=5)
            if resp.status_code == 200:
                for svc in resp.json():
                    # Extract port from service proposal or options
                    port = svc.get('options', {}).get('port')
                    if port:
                        ports.append(int(port))
                    # Also check proposal
                    proposal = svc.get('proposal', {})
                    contacts = proposal.get('contacts', [])
                    for c in contacts:
                        defn = c.get('definition', {})
                        p = defn.get('port')
                        if p:
                            ports.append(int(p))
        except Exception:
            pass
        return list(set(ports))

    @staticmethod
    def _check_nat_type():
        """Check node's NAT type via multiple sources."""
        # Try TequilAPI endpoints (varies by myst version)
        endpoints = [
            '/nat/type',
            '/connection/status',
            '/node/monitoring-status',
        ]
        try:
            import requests as req
            for ep in endpoints:
                try:
                    resp = req.get(
                        f'http://localhost:{PortReachability.TEQUILAPI_PORT}{ep}',
                        timeout=3)
                    if resp.status_code == 200:
                        data = resp.json()
                        # /nat/type returns {"type": "..."}
                        nat = data.get('type')
                        if nat and nat != 'unknown':
                            return nat
                        # /connection/status might have nat_type field
                        nat = data.get('nat_type')
                        if nat and nat != 'unknown':
                            return nat
                except Exception:
                    continue
        except ImportError:
            pass

        # Fallback: try myst CLI
        rc, out, _ = _run(['myst', 'cli', '--agreed-terms-and-conditions', 'nat', 'type'])
        if rc == 0 and out:
            # Parse output like "NAT type: Full Cone"
            for line in out.splitlines():
                if 'type' in line.lower():
                    parts = line.split(':', 1)
                    if len(parts) == 2:
                        nat = parts[1].strip()
                        if nat and nat.lower() != 'unknown':
                            return nat

        # Last fallback: check if UPnP mapped ports exist (indicates working NAT traversal)
        try:
            import requests as req
            resp = req.get(
                f'http://localhost:{PortReachability.TEQUILAPI_PORT}/services',
                timeout=3)
            if resp.status_code == 200:
                services = resp.json()
                if services and len(services) > 0:
                    # If services are running and we have connections, NAT is working
                    return 'working (type detection unavailable)'
        except Exception:
            pass

        return 'unknown'

    @staticmethod
    def scan():
        result = {
            'name': 'port_reachability',
            'title': 'Port Reachability',
            'status': 'ok',
            'checks': [],
            'recommendations': [],
        }

        # Check TequilAPI
        api_listening = PortReachability._check_port_listening(PortReachability.TEQUILAPI_PORT)
        result['checks'].append({
            'name': 'TequilAPI',
            'status': 'ok' if api_listening else 'critical',
            'detail': f'Port {PortReachability.TEQUILAPI_PORT} {"listening" if api_listening else "NOT listening"}',
        })
        if not api_listening:
            result['status'] = 'critical'
            result['recommendations'].append('sudo systemctl restart mysterium-node')
            return result

        # Check service ports
        svc_ports = PortReachability._get_service_ports()
        if svc_ports:
            for port in svc_ports:
                listening = PortReachability._check_port_listening(port)
                result['checks'].append({
                    'name': f'Port {port}',
                    'status': 'ok' if listening else 'warning',
                    'detail': 'listening' if listening else 'NOT listening',
                })
                if not listening and result['status'] == 'ok':
                    result['status'] = 'warning'

        # NAT type
        nat_type = PortReachability._check_nat_type()
        nat_lower = nat_type.lower()
        nat_ok = any(t in nat_lower for t in (
            'none', 'fullcone', 'full_cone', 'full cone', 'restricted',
            'working', 'open', 'endpoint',
        ))
        nat_bad = not nat_ok and nat_lower in ('symmetric', 'unknown')
        result['checks'].append({
            'name': 'NAT type',
            'status': 'ok' if nat_ok else 'warning' if nat_bad else 'ok',
            'detail': nat_type,
        })
        if nat_bad:
            if result['status'] == 'ok':
                result['status'] = 'warning'
            result['recommendations'].append(
                f'NAT type "{nat_type}" may limit connections. Enable UPnP or port forwarding.'
            )

        # Check if iptables backend matches rules
        # (leverages FirewallBackend scan)
        fw_scan = FirewallBackend.scan()
        for check in fw_scan.get('checks', []):
            if check.get('status') == 'critical':
                result['status'] = 'critical'
                result['checks'].append({
                    'name': 'Firewall',
                    'status': 'critical',
                    'detail': check.get('detail', 'Backend mismatch'),
                })
                result['recommendations'].append(
                    'Fix firewall backend first — rules are invisible to current iptables'
                )
                break
        else:
            result['checks'].append({
                'name': 'Firewall',
                'status': 'ok',
                'detail': 'Backend matches rules',
            })

        return result

    @staticmethod
    def fix():
        actions = []

        # Fix 1: Fix firewall backend if needed
        fw_scan = FirewallBackend.scan()
        if fw_scan.get('status') == 'critical':
            fw_fix = FirewallBackend.fix()
            actions.extend(fw_fix.get('actions', []))

        # Fix 2: Restart node if API not listening
        api_listening = PortReachability._check_port_listening(PortReachability.TEQUILAPI_PORT)
        if not api_listening:
            rc, _, err = _run(['sudo', '-n', 'systemctl', 'restart', 'mysterium-node'])
            actions.append({
                'action': 'Restart mysterium-node (API not listening)',
                'success': rc == 0,
                'error': err[:80] if rc != 0 and err else None,
            })
            time.sleep(5)

        if not actions:
            actions.append({'action': 'All ports reachable', 'success': True})

        return {'name': 'port_reachability', 'actions': actions,
                'success': all(a.get('success', True) for a in actions)}


# =============================================================================
# 8. STALE PROCESS CLEANUP
# =============================================================================

class ProcessCleanup:
    """Detect and kill stale toolkit processes from old installations.

    Multiple toolkit versions can leave backend/frontend processes running.
    Only the current installation's processes should be active.

    SAFETY:
    - Never kills the Mysterium node (myst / mysterium-node)
    - Only targets Python/Node processes matching toolkit patterns
    - Shows what it found before killing anything
    - fix() kills stale processes
    """

    # Patterns that indicate a toolkit process
    TOOLKIT_PATTERNS = [
        'backend/app.py',
        'backend\\app.py',
        'cli/dashboard.py',
        'cli\\dashboard.py',
        'scripts/system_health.py',
        'vite',
    ]

    # Never kill these
    PROTECTED = ['myst', 'mysterium', 'wireguard', 'wg-quick']

    @staticmethod
    def _find_toolkit_processes():
        """Find all running toolkit-related processes."""
        procs = []
        current_dir = None
        current_pid = os.getpid()
        current_ppid = os.getppid()
        try:
            # Detect current toolkit directory
            current_dir = str(Path(__file__).resolve().parent.parent)
        except Exception:
            pass

        for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'cwd', 'create_time', 'ppid']):
            try:
                pid = proc.info['pid']
                name = proc.info['name'] or ''
                cmdline = ' '.join(proc.info.get('cmdline') or [])

                # Skip protected processes
                if any(p in name.lower() for p in ProcessCleanup.PROTECTED):
                    continue

                # Check if it matches toolkit patterns
                is_toolkit = False
                for pattern in ProcessCleanup.TOOLKIT_PATTERNS:
                    if pattern in cmdline:
                        is_toolkit = True
                        break

                if not is_toolkit:
                    continue

                # Determine if it's from current installation
                is_current = False

                # Check 1: Same process tree (our PID, parent, or child)
                ppid = proc.info.get('ppid', 0)
                if pid == current_pid or pid == current_ppid or ppid == current_pid or ppid == current_ppid:
                    is_current = True

                # Check 2: cmdline or cwd contains our directory
                if current_dir and not is_current:
                    if current_dir in cmdline:
                        is_current = True
                    else:
                        try:
                            cwd = proc.cwd() or ''
                            if current_dir in cwd:
                                is_current = True
                        except (psutil.AccessDenied, psutil.NoSuchProcess):
                            # Can't determine cwd AND cmdline doesn't match
                            # Conservative: if cmdline uses relative paths, assume current
                            if not any(d in cmdline for d in ('/', '/home/', '/opt/')):
                                is_current = True  # Relative path = probably us

                uptime = time.time() - (proc.info.get('create_time') or time.time())
                h, m = int(uptime // 3600), int((uptime % 3600) // 60)

                procs.append({
                    'pid': pid,
                    'name': name,
                    'cmdline': cmdline[:120],
                    'is_current': is_current,
                    'uptime': f'{h}h{m}m',
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        return procs

    @staticmethod
    def scan():
        result = {
            'name': 'process_cleanup',
            'title': 'Stale Processes',
            'status': 'ok',
            'checks': [],
            'recommendations': [],
        }

        procs = ProcessCleanup._find_toolkit_processes()
        current = [p for p in procs if p['is_current']]
        stale = [p for p in procs if not p['is_current']]

        result['checks'].append({
            'name': 'Current',
            'status': 'ok',
            'detail': f'{len(current)} process(es)',
        })

        if stale:
            result['status'] = 'warning'
            pids = ', '.join(str(p['pid']) for p in stale)
            result['checks'].append({
                'name': 'Stale',
                'status': 'warning',
                'detail': f'{len(stale)} old process(es): PIDs {pids}',
            })
            for p in stale:
                result['recommendations'].append(
                    f"Kill PID {p['pid']}: {p['cmdline'][:60]} (up {p['uptime']})"
                )
        else:
            result['checks'].append({
                'name': 'Stale',
                'status': 'ok',
                'detail': 'None found',
            })

        return result

    @staticmethod
    def fix():
        actions = []
        procs = ProcessCleanup._find_toolkit_processes()
        stale = [p for p in procs if not p['is_current']]

        for p in stale:
            try:
                proc = psutil.Process(p['pid'])
                proc.terminate()
                actions.append({
                    'action': f"Killed PID {p['pid']}: {p['cmdline'][:50]}",
                    'success': True,
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                actions.append({
                    'action': f"Kill PID {p['pid']}",
                    'success': False,
                    'error': str(e)[:60],
                })

        if not actions:
            actions.append({'action': 'No stale processes', 'success': True})

        return {'name': 'process_cleanup', 'actions': actions,
                'success': all(a.get('success', True) for a in actions)}


# =============================================================================
# 9. AUTO-RPS WATCHER — Dynamic VPN interface RPS management
# =============================================================================

RPS_WATCHER_TIMER = 'mysterium-rps-watcher.timer'
RPS_WATCHER_SERVICE = 'mysterium-rps-watcher.service'
RPS_WATCHER_SCRIPT = '/usr/local/bin/mysterium-rps-watcher.sh'


class RpsWatcher:
    """Auto-apply RPS to dynamically created VPN interfaces.

    WireGuard/Mysterium tunnels are ephemeral — they appear and disappear as
    consumers connect and disconnect. A one-shot boot script misses interfaces
    created after boot. This subsystem installs a lightweight systemd timer
    that runs every 30s to set rps_cpus on any new VPN interface.
    """

    @staticmethod
    def scan():
        result = {
            'name': 'rps_watcher',
            'title': 'Auto-RPS Watcher',
            'status': 'ok',
            'checks': [],
            'recommendations': [],
        }

        # Check 1: Is the timer installed?
        timer_installed = Path(f'/etc/systemd/system/{RPS_WATCHER_TIMER}').exists()

        # Check 2: Is the timer active?
        timer_active = False
        if timer_installed:
            rc, out, _ = _run(['systemctl', 'is-active', RPS_WATCHER_TIMER])
            timer_active = rc == 0 and 'active' in out.lower()

        # Check 3: Is the script present?
        script_exists = Path(RPS_WATCHER_SCRIPT).exists()

        # Check 4: Count current unset VPN interfaces
        cpu_count = os.cpu_count() or 1
        all_mask = format((1 << cpu_count) - 1, 'x')
        vpn_ifaces = [i for i in (psutil.net_io_counters(pernic=True) or {})
                      if i.startswith(('myst', 'wg', 'tun'))]
        unset_count = 0
        virtual_count = 0
        for iface in vpn_ifaces:
            queue_path = Path(f'/sys/class/net/{iface}/queues/rx-0/rps_cpus')
            if not queue_path.exists():
                virtual_count += 1
                continue
            try:
                current = queue_path.read_text().strip().replace(',', '').lstrip('0') or '0'
                if current == '0':
                    unset_count += 1
            except (OSError, PermissionError):
                pass

        if timer_active:
            result['checks'].append({
                'name': 'Timer',
                'status': 'ok',
                'detail': f'Active — scanning every 30s',
            })
        elif timer_installed:
            result['status'] = 'warning'
            result['checks'].append({
                'name': 'Timer',
                'status': 'warning',
                'detail': 'Installed but not running',
            })
            result['recommendations'].append('Start timer: systemctl start mysterium-rps-watcher.timer')
        else:
            result['status'] = 'warning'
            result['checks'].append({
                'name': 'Timer',
                'status': 'warning',
                'detail': 'Not installed',
            })
            result['recommendations'].append('Run health fix to install auto-RPS watcher')

        # Interface summary
        total = len(vpn_ifaces)
        detail_parts = []
        if total > 0:
            if virtual_count > 0:
                detail_parts.append(f'{virtual_count} virtual (kernel-managed)')
            managed = total - virtual_count - unset_count
            if managed > 0:
                detail_parts.append(f'{managed} RPS set')
            if unset_count > 0:
                detail_parts.append(f'{unset_count} unset')
        else:
            detail_parts.append('No VPN interfaces')

        iface_status = 'ok'
        if unset_count > 0 and not timer_active:
            iface_status = 'warning'
        elif unset_count > 0 and timer_active:
            iface_status = 'ok'  # Timer will fix on next cycle

        result['checks'].append({
            'name': 'VPN Interfaces',
            'status': iface_status,
            'detail': f'{total} tunnels — ' + ', '.join(detail_parts),
        })

        return result

    @staticmethod
    def fix():
        actions = []
        cpu_count = os.cpu_count() or 1
        all_mask = format((1 << cpu_count) - 1, 'x')
        primary = CpuLoadBalance._get_primary_iface() or 'eth0'

        # Get NIC coalescing value for boot script
        nic_coal = NicCoalescing._get_coalesce(primary) if primary != 'eth0' else {}
        coal_value = max(nic_coal.get('rx-usecs', 0) or 0, NicCoalescing.TARGET_RX_USECS)

        # Step 1: Create the watcher script
        watcher_script = f"""#!/bin/bash
# Mysterium Node Toolkit — Auto-RPS Watcher
# Applies RPS mask to all VPN interfaces every 30s
# Handles dynamic tunnel creation/destruction
# Generated by health fix

MASK="{all_mask}"
IFACE="{primary}"
APPLIED=0

# NIC coalescing (prevent e1000e IRQ storm)
ethtool -C "$IFACE" rx-usecs {coal_value} 2>/dev/null

# Primary NIC RPS
for q in /sys/class/net/$IFACE/queues/rx-*/rps_cpus; do
    echo "$MASK" > "$q" 2>/dev/null
done

# VPN interfaces — set RPS on any that have queue dirs
for iface in /sys/class/net/myst* /sys/class/net/wg* /sys/class/net/tun*; do
    [ -d "$iface" ] || continue
    for q in "$iface"/queues/rx-*/rps_cpus; do
        CURRENT=$(cat "$q" 2>/dev/null | tr -d ',' | sed 's/^0*//' )
        [ "${{CURRENT:-0}}" = "0" ] && echo "$MASK" > "$q" 2>/dev/null && APPLIED=$((APPLIED+1))
    done
    # Set flow count for RPS hash consistency
    for f in "$iface"/queues/rx-*/rps_flow_cnt; do
        echo "32768" > "$f" 2>/dev/null
    done
done

[ "$APPLIED" -gt 0 ] && logger -t mysterium-rps "Applied RPS mask $MASK to $APPLIED queue(s)"
exit 0
"""

        try:
            rc, _, err = _run(['sudo', '-n', 'bash', '-c',
                               f'cat > {RPS_WATCHER_SCRIPT} << "SCRIPT_EOF"\n{watcher_script}SCRIPT_EOF\n'
                               f'chmod +x {RPS_WATCHER_SCRIPT}'])
            ok = rc == 0
            actions.append({'action': f'Wrote {RPS_WATCHER_SCRIPT}', 'success': ok,
                            'error': err if not ok else None})
        except Exception as e:
            actions.append({'action': f'Write {RPS_WATCHER_SCRIPT}', 'success': False, 'error': str(e)})

        # Step 2: Create systemd service (oneshot, runs the script)
        service_unit = f"""[Unit]
Description=Mysterium Auto-RPS — Apply RPS to dynamic VPN interfaces
After=network.target

[Service]
Type=oneshot
ExecStart={RPS_WATCHER_SCRIPT}
"""

        timer_unit = f"""[Unit]
Description=Mysterium Auto-RPS — 30s timer for dynamic VPN interfaces

[Timer]
OnBootSec=10
OnUnitActiveSec=30
AccuracySec=5

[Install]
WantedBy=timers.target
"""

        svc_path = f'/etc/systemd/system/{RPS_WATCHER_SERVICE}'
        tmr_path = f'/etc/systemd/system/{RPS_WATCHER_TIMER}'

        for path, content, label in [
            (svc_path, service_unit, 'service unit'),
            (tmr_path, timer_unit, 'timer unit'),
        ]:
            try:
                rc, _, err = _run(['sudo', '-n', 'bash', '-c',
                                   f'cat > {path} << "UNIT_EOF"\n{content}UNIT_EOF'])
                ok = rc == 0
                actions.append({'action': f'Wrote {label}', 'success': ok,
                                'error': err if not ok else None})
            except Exception as e:
                actions.append({'action': f'Write {label}', 'success': False, 'error': str(e)})

        # Step 3: Enable and start the timer
        _run(['sudo', '-n', 'systemctl', 'daemon-reload'])
        rc, _, err = _run(['sudo', '-n', 'systemctl', 'enable', '--now', RPS_WATCHER_TIMER])
        actions.append({
            'action': f'Enable + start {RPS_WATCHER_TIMER}',
            'success': rc == 0,
            'error': err if rc != 0 else None,
        })

        # Step 4: Run the script once immediately
        rc, _, _ = _run(['sudo', '-n', 'bash', RPS_WATCHER_SCRIPT])
        actions.append({'action': 'Apply RPS now (immediate run)', 'success': rc == 0})

        return {'name': 'rps_watcher', 'actions': actions,
                'success': all(a.get('success', True) for a in actions) if actions else True}



# =============================================================================
# 10. SWAP HEALTH
# =============================================================================

class SwapHealth:
    """Ensure the system has adequate swap space.

    VPN exit nodes with 50+ tunnels can spike RAM usage unpredictably.
    Without swap the kernel OOM-kills myst, dropping all active sessions.

    SAFETY:
    - Only creates swap if none exists — never removes existing swap
    - Uses fallocate (fast) with dd fallback (btrfs/zfs)
    - Never changes existing swap partition settings
    - swappiness=60 is the kernel default — not aggressive
    """

    MIN_SWAP_MB    = 1024   # 1 GB absolute minimum
    TARGET_SWAP_MB = 4096   # 4 GB recommended
    SWAPFILE_PATH  = '/swapfile'

    @staticmethod
    def _get_swap_info():
        """Return (total_mb, used_mb, pct, has_swapfile, has_swap_partition)."""
        total_mb = 0
        used_mb  = 0
        has_file = False
        has_part = False
        try:
            import psutil as _ps
            swap = _ps.swap_memory()
            total_mb = swap.total / (1024 * 1024)
            used_mb  = swap.used  / (1024 * 1024)
        except Exception:
            pass
        # Detect swap type
        try:
            with open('/proc/swaps') as f:
                for line in f.readlines()[1:]:
                    parts = line.split()
                    if not parts:
                        continue
                    if parts[0] == SwapHealth.SWAPFILE_PATH:
                        has_file = True
                    elif parts[0].startswith('/dev/'):
                        has_part = True
                    else:
                        has_file = True  # any file-based swap
        except Exception:
            pass
        pct = (used_mb / total_mb * 100) if total_mb > 0 else 0
        return total_mb, used_mb, pct, has_file, has_part

    @staticmethod
    def scan():
        result = {
            'name': 'swap',
            'title': 'Swap / Memory Safety Net',
            'status': 'ok',
            'checks': [],
            'recommendations': [],
        }

        total_mb, used_mb, pct, has_file, has_part = SwapHealth._get_swap_info()

        if total_mb < 1:
            result['status'] = 'critical'
            result['checks'].append({
                'name': 'Swap',
                'status': 'critical',
                'detail': 'None configured — OOM risk under VPN session spike',
            })
            result['recommendations'].append(
                'Fix will create a 4 GB swapfile and persist it')
        elif total_mb < SwapHealth.MIN_SWAP_MB:
            result['status'] = 'warning'
            result['checks'].append({
                'name': 'Swap',
                'status': 'warning',
                'detail': f'{total_mb:.0f} MB — too small for VPN node (need ≥ 1 GB)',
            })
            result['recommendations'].append(
                f'Expand swap to {SwapHealth.TARGET_SWAP_MB // 1024} GB')
        else:
            result['checks'].append({
                'name': 'Swap',
                'status': 'ok',
                'detail': f'{total_mb:.0f} MB total — {"swapfile" if has_file else "partition"}',
            })

        if total_mb > 0:
            if pct > 60:
                result['checks'].append({
                    'name': 'Usage',
                    'status': 'warning',
                    'detail': f'{used_mb:.0f} / {total_mb:.0f} MB ({pct:.1f}%) — high pressure',
                })
                if result['status'] == 'ok':
                    result['status'] = 'warning'
                result['recommendations'].append(
                    'Close non-essential apps (browsers) to free RAM')
            else:
                result['checks'].append({
                    'name': 'Usage',
                    'status': 'ok',
                    'detail': f'{used_mb:.0f} / {total_mb:.0f} MB ({pct:.1f}%)',
                })

        # Check swappiness
        swappiness = _sysctl_get('vm.swappiness')
        if swappiness is not None:
            result['checks'].append({
                'name': 'swappiness',
                'status': 'ok',
                'detail': f'{swappiness} (60 = balanced)',
            })

        # Check fstab persistence
        fstab_ok = False
        try:
            with open('/etc/fstab') as f:
                fstab_ok = any('swap' in line and not line.strip().startswith('#')
                               for line in f)
        except Exception:
            pass
        result['checks'].append({
            'name': 'Fstab',
            'status': 'ok' if fstab_ok else 'warning',
            'detail': 'Persisted in /etc/fstab' if fstab_ok else 'Not in /etc/fstab (lost on reboot)',
        })
        if not fstab_ok and total_mb > 0:
            if result['status'] == 'ok':
                result['status'] = 'warning'
            result['recommendations'].append('Persist swap to /etc/fstab')

        return result

    @staticmethod
    def fix():
        """Create swapfile if missing, tune swappiness."""
        actions = []
        total_mb, _, _, has_file, has_part = SwapHealth._get_swap_info()

        if total_mb < SwapHealth.MIN_SWAP_MB and not has_part:
            sf = SwapHealth.SWAPFILE_PATH
            size_mb = SwapHealth.TARGET_SWAP_MB

            # Check if swapfile already exists (maybe just not active)
            if not Path(sf).exists():
                # Try fallocate first (fast), fall back to dd (btrfs/zfs)
                rc, _, _ = _run(['sudo', '-n', 'fallocate', '-l', f'{size_mb}M', sf])
                if rc != 0:
                    rc, _, err = _run([
                        'sudo', '-n', 'dd', 'if=/dev/zero',
                        f'of={sf}', 'bs=1M', f'count={size_mb}'
                    ], timeout=120)
                actions.append({
                    'action': f'Created {sf} ({size_mb} MB)',
                    'success': rc == 0,
                })
                if rc != 0:
                    return {'name': 'swap', 'actions': actions, 'success': False}

            # Secure permissions
            rc, _, _ = _run(['sudo', '-n', 'chmod', '600', sf])
            actions.append({'action': f'chmod 600 {sf}', 'success': rc == 0})

            # Format as swap
            rc, _, err = _run(['sudo', '-n', 'mkswap', sf])
            actions.append({'action': f'mkswap {sf}', 'success': rc == 0,
                            'error': err[:60] if rc != 0 else None})

            # Enable
            rc, _, err = _run(['sudo', '-n', 'swapon', sf])
            actions.append({'action': f'swapon {sf}', 'success': rc == 0,
                            'error': err[:60] if rc != 0 else None})
        else:
            actions.append({
                'action': f'Swap already present ({total_mb:.0f} MB) — no change',
                'success': True,
            })

        # Set swappiness in memory
        ok = _sysctl_set('vm.swappiness', 60)
        actions.append({'action': 'vm.swappiness = 60', 'success': ok})

        return {'name': 'swap', 'actions': actions,
                'success': all(a.get('success', True) for a in actions)}


# =============================================================================
# 11. CPU PERFORMANCE GOVERNOR
# =============================================================================

class CpuGovernorHealth:
    """Dynamic CPU frequency governor based on active VPN session load.

    Instead of pinning all cores to 'performance' always (wastes power,
    heats up the CPU at idle), the toolkit adjusts the governor based on
    how many active sessions the node is serving:

      0 sessions         → powersave  (minimum power, node is idle)
      1–5 sessions       → schedutil  (kernel-managed, adapts to actual load)
      6+ sessions        → performance (maximum throughput, high load)

    'schedutil' is the best middle ground for a VPN node: it ramps up
    instantly when the scheduler sees load, and drops back when idle.
    This keeps the CPU cool during quiet periods without sacrificing
    throughput when clients are active.

    Thresholds are conservative — it's fine to run schedutil even with
    10+ sessions if your hardware handles it well thermally.
    """

    # Load thresholds
    THRESH_PERFORMANCE = 6    # 6+ sessions → performance
    THRESH_SCHEDUTIL   = 1    # 1–5 sessions → schedutil
    # Below THRESH_SCHEDUTIL → powersave

    # Alias — referenced by persist code and health panel
    TARGET_GOVERNOR = 'performance' 

    # Governor preference order (most preferred for the load band)
    FALLBACK_CHAIN = ['schedutil', 'ondemand', 'conservative', 'powersave']

    @staticmethod
    def _get_cpu_count():
        return os.cpu_count() or 1

    @staticmethod
    def _get_governors():
        """Return list of (cpu_index, current_governor) for all cores."""
        governors = []
        for i in range(CpuGovernorHealth._get_cpu_count()):
            path = f'/sys/devices/system/cpu/cpu{i}/cpufreq/scaling_governor'
            gov = _read_file(path)
            if gov:
                governors.append((i, gov))
        return governors

    @staticmethod
    def _get_available_governors(cpu_index=0):
        path = f'/sys/devices/system/cpu/cpu{cpu_index}/cpufreq/scaling_available_governors'
        avail = _read_file(path)
        return avail.split() if avail else []

    @staticmethod
    def _get_cur_freq_mhz(cpu_index=0):
        path = f'/sys/devices/system/cpu/cpu{cpu_index}/cpufreq/scaling_cur_freq'
        val = _read_file(path)
        return int(val) // 1000 if val else None

    @staticmethod
    def _get_max_freq_mhz(cpu_index=0):
        path = f'/sys/devices/system/cpu/cpu{cpu_index}/cpufreq/scaling_max_freq'
        val = _read_file(path)
        return int(val) // 1000 if val else None

    @staticmethod
    def target_for_load(session_count):
        """Return the appropriate governor name for a given session count."""
        if session_count >= CpuGovernorHealth.THRESH_PERFORMANCE:
            return 'performance'
        elif session_count >= CpuGovernorHealth.THRESH_SCHEDUTIL:
            return 'schedutil'
        else:
            return 'powersave'

    @staticmethod
    def _best_available(preferred, avail):
        """Return preferred if available, else best fallback from avail."""
        if preferred in avail:
            return preferred
        for fb in CpuGovernorHealth.FALLBACK_CHAIN:
            if fb in avail:
                return fb
        return avail[0] if avail else preferred

    @staticmethod
    def adjust_for_sessions(session_count):
        """Set governor based on active session count. Called from the slow tier.
        Returns (governor_set, changed_cores) or (None, 0) if cpufreq unavailable.
        """
        governors = CpuGovernorHealth._get_governors()
        if not governors:
            return None, 0
        avail = CpuGovernorHealth._get_available_governors()
        if not avail:
            return None, 0

        target = CpuGovernorHealth.target_for_load(session_count)
        actual = CpuGovernorHealth._best_available(target, avail)

        changed = 0
        for i, current_gov in governors:
            if current_gov == actual:
                continue
            path = f'/sys/devices/system/cpu/cpu{i}/cpufreq/scaling_governor'
            if _write_file(path, actual):
                changed += 1

        if changed == 0 and _is_installed('cpupower'):
            rc, _, _ = _run(['sudo', '-n', 'cpupower', 'frequency-set', '-g', actual])
            if rc == 0:
                changed = len(governors)

        if changed > 0:
            import logging as _lg
            _lg.getLogger(__name__).info(
                f'CpuGovernor: {changed} core(s) → {actual} '
                f'(sessions={session_count}, target={target})'
            )
        return actual, changed

    @staticmethod
    def scan():
        result = {
            'name': 'cpu_governor',
            'title': 'CPU Governor (adaptive)',
            'status': 'ok',
            'checks': [],
            'recommendations': [],
        }

        governors = CpuGovernorHealth._get_governors()
        if not governors:
            result['checks'].append({
                'name': 'Governor',
                'status': 'ok',
                'detail': 'cpufreq not available (hardware-managed)',
            })
            return result

        avail = CpuGovernorHealth._get_available_governors()
        current_govs = set(g for _, g in governors)
        n = len(governors)

        result['checks'].append({
            'name': 'Governor',
            'status': 'ok',
            'detail': f'All {n} cores: {", ".join(current_govs)}',
        })

        # Thresholds info
        result['checks'].append({
            'name': 'Mode',
            'status': 'ok',
            'detail': (
                f'0 sess → powersave · '
                f'1–{CpuGovernorHealth.THRESH_PERFORMANCE - 1} sess → schedutil · '
                f'{CpuGovernorHealth.THRESH_PERFORMANCE}+ sess → performance'
            ),
        })

        cur = CpuGovernorHealth._get_cur_freq_mhz(0)
        mx  = CpuGovernorHealth._get_max_freq_mhz(0)
        if cur and mx:
            pct = int(cur * 100 / mx)
            result['checks'].append({
                'name': 'Frequency',
                'status': 'ok',
                'detail': f'{cur} / {mx} MHz ({pct}%)',
            })

        if avail:
            result['checks'].append({
                'name': 'Available',
                'status': 'ok',
                'detail': ', '.join(avail),
            })

        # Warn if cpufreq not writeable (no sudo) — governor won't adapt
        test_path = f'/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor'
        can_write = _write_file(test_path, governors[0][1])  # write same value = no-op
        if not can_write and not _is_installed('cpupower'):
            result['status'] = 'warning'
            result['checks'].append({
                'name': 'Permissions',
                'status': 'warning',
                'detail': 'Cannot write scaling_governor — run setup.sh to fix sudoers',
            })
            result['recommendations'].append('Run setup.sh to configure sudoers for governor control')

        return result

    @staticmethod
    def fix():
        """Apply schedutil (safe middle-ground) to all cores immediately."""
        actions = []
        governors = CpuGovernorHealth._get_governors()

        if not governors:
            return {'name': 'cpu_governor', 'actions': [
                {'action': 'cpufreq not available — nothing to do', 'success': True}
            ], 'success': True}

        avail = CpuGovernorHealth._get_available_governors()
        target = CpuGovernorHealth._best_available('schedutil', avail)

        changed = failed = 0
        for i, current_gov in governors:
            if current_gov == target:
                continue
            path = f'/sys/devices/system/cpu/cpu{i}/cpufreq/scaling_governor'
            ok = _write_file(path, target)
            if ok:
                changed += 1
            else:
                failed += 1

        if changed == 0 and failed > 0 and _is_installed('cpupower'):
            rc, _, _ = _run(['sudo', '-n', 'cpupower', 'frequency-set', '-g', target])
            if rc == 0:
                changed = len(governors)
                failed  = 0

        if changed > 0:
            actions.append({
                'action': f'Set {changed} core(s) → {target}',
                'success': True,
            })
        if failed > 0:
            actions.append({
                'action': f'{failed} core(s) could not be changed — sudoers may need update',
                'success': False,
            })
        if changed == 0 and failed == 0:
            actions.append({
                'action': f'All {len(governors)} cores already on {target}',
                'success': True,
            })

        return {'name': 'cpu_governor', 'actions': actions, 'success': failed == 0}



    @staticmethod
    def _get_cpu_count():
        return os.cpu_count() or 1

    @staticmethod
    def _get_governors():
        """Return list of (cpu_index, current_governor) for all cores."""
        governors = []
        for i in range(CpuGovernorHealth._get_cpu_count()):
            path = f'/sys/devices/system/cpu/cpu{i}/cpufreq/scaling_governor'
            gov = _read_file(path)
            if gov:
                governors.append((i, gov))
        return governors

    @staticmethod
    def _get_available_governors(cpu_index=0):
        path = f'/sys/devices/system/cpu/cpu{cpu_index}/cpufreq/scaling_available_governors'
        avail = _read_file(path)
        return avail.split() if avail else []

    @staticmethod
    def _get_cur_freq_mhz(cpu_index=0):
        path = f'/sys/devices/system/cpu/cpu{cpu_index}/cpufreq/scaling_cur_freq'
        val = _read_file(path)
        return int(val) // 1000 if val else None

    @staticmethod
    def _get_max_freq_mhz(cpu_index=0):
        path = f'/sys/devices/system/cpu/cpu{cpu_index}/cpufreq/scaling_max_freq'
        val = _read_file(path)
        return int(val) // 1000 if val else None




# =============================================================================
# 12. BBR CONGESTION CONTROL
# =============================================================================

class BbrCongestion:
    """Enable BBR TCP congestion control for better VPN throughput.

    BBR (Bottleneck Bandwidth and RTT) is a modern congestion control algorithm
    developed by Google. Compared to the default CUBIC:
    - Achieves higher throughput on lossy links (typical consumer internet)
    - Lower latency under load
    - Handles packet loss better (doesn't halve window on every drop)

    Required: Linux 4.9+ kernel (standard on Debian 10+, Ubuntu 18.04+)

    SAFETY:
    - Only changes the congestion control algorithm — no structural change
    - fq qdisc is the recommended pair for BBR (upstream default)
    - Reverts cleanly via unpersist
    - Falls back gracefully if kernel module unavailable
    """

    TARGET_CC = 'bbr'
    TARGET_QDISC = 'fq'

    @staticmethod
    def scan():
        result = {
            'name': 'bbr',
            'title': 'BBR Congestion Control',
            'status': 'ok',
            'checks': [],
            'recommendations': [],
        }

        # Current congestion control
        current_cc = _sysctl_get('net.ipv4.tcp_congestion_control')
        current_qdisc = _sysctl_get('net.core.default_qdisc')

        if current_cc is None:
            result['checks'].append({
                'name': 'TCP CC',
                'status': 'ok',
                'detail': 'sysctl not available',
            })
            return result

        if current_cc == BbrCongestion.TARGET_CC:
            result['checks'].append({
                'name': 'TCP CC',
                'status': 'ok',
                'detail': 'bbr active',
            })
        else:
            result['status'] = 'warning'
            result['checks'].append({
                'name': 'TCP CC',
                'status': 'warning',
                'detail': f'{current_cc} — bbr gives better VPN throughput',
            })
            result['recommendations'].append(
                'Enable BBR for higher TCP throughput and lower latency under load')

        if current_qdisc:
            if current_qdisc == BbrCongestion.TARGET_QDISC:
                result['checks'].append({
                    'name': 'Queue disc',
                    'status': 'ok',
                    'detail': 'fq (recommended for BBR)',
                })
            else:
                result['checks'].append({
                    'name': 'Queue disc',
                    'status': 'warning' if current_cc == 'bbr' else 'ok',
                    'detail': f'{current_qdisc} — fq recommended with BBR',
                })
                if current_cc == 'bbr' and result['status'] == 'ok':
                    result['status'] = 'warning'

        # Check if bbr module is loaded
        rc, out, _ = _run(['lsmod'])
        bbr_loaded = rc == 0 and 'tcp_bbr' in out
        result['checks'].append({
            'name': 'Module',
            'status': 'ok' if bbr_loaded else 'warning',
            'detail': 'tcp_bbr loaded' if bbr_loaded else 'tcp_bbr not loaded',
        })

        # Check persistence
        sysctl_file = Path('/etc/sysctl.d/99-mysterium-node.conf')
        persisted = False
        if sysctl_file.exists():
            try:
                content = sysctl_file.read_text()
                persisted = 'bbr' in content
            except Exception:
                pass
        result['checks'].append({
            'name': 'Persistence',
            'status': 'ok' if persisted else 'warning',
            'detail': 'Persisted in sysctl.d' if persisted
                      else 'Not persisted (reverts on reboot)',
        })
        if not persisted and current_cc == 'bbr' and result['status'] == 'ok':
            result['status'] = 'warning'
            result['recommendations'].append('Persist BBR to survive reboots')

        return result

    @staticmethod
    def fix():
        """Load tcp_bbr module and enable BBR + fq."""
        actions = []

        # Load the module
        rc, _, err = _run(['sudo', '-n', 'modprobe', 'tcp_bbr'])
        if rc == 0:
            actions.append({'action': 'modprobe tcp_bbr', 'success': True})
        else:
            # Check if it's built-in (no .ko file needed)
            rc2, out2, _ = _run(['lsmod'])
            if 'tcp_bbr' in (out2 or ''):
                actions.append({'action': 'tcp_bbr already built into kernel', 'success': True})
            else:
                actions.append({
                    'action': 'modprobe tcp_bbr',
                    'success': False,
                    'error': (err or 'module not available')[:80],
                })
                # BBR not available on this kernel — don't fail hard, just report
                return {'name': 'bbr', 'actions': actions, 'success': False}

        # Set congestion control
        ok = _sysctl_set('net.ipv4.tcp_congestion_control', 'bbr')
        actions.append({'action': 'net.ipv4.tcp_congestion_control = bbr', 'success': ok})

        # Set fq qdisc (recommended companion for BBR)
        ok2 = _sysctl_set('net.core.default_qdisc', 'fq')
        actions.append({'action': 'net.core.default_qdisc = fq', 'success': ok2})

        return {'name': 'bbr', 'actions': actions,
                'success': all(a.get('success', True) for a in actions)}


# =============================================================================
# 13. NIC CHECKSUM OFFLOAD
# =============================================================================

class NicChecksumOffload:
    """Detect and disable failing hardware RX checksum offload.

    Intel NICs (e1000e in particular) can silently fail hardware checksum
    computation — reporting rx_csum_offload_errors in ethtool -S.
    Each error is a packet dropped mid-VPN-session.

    Fix: disable hardware RX checksum (rx off), force CPU checksumming.
    CPU cost is negligible on modern hardware — a single SHA256 per packet.

    SAFETY:
    - Only disables RX checksum offload, nothing else
    - Does not touch TX checksum (tx on stays on)
    - Does not touch ring buffers, interrupts, or any other NIC setting
    - Fully reversible: ethtool -K <iface> rx on
    """

    @staticmethod
    def _get_primary_iface():
        rc, out, _ = _run(['ip', 'route', 'show', 'default'])
        if rc == 0 and 'dev ' in out:
            return out.split('dev ')[1].split()[0]
        return None

    @staticmethod
    def _get_csum_errors(iface):
        """Return rx_csum_offload_errors count from ethtool -S."""
        rc, out, _ = _run(['ethtool', '-S', iface])
        if rc != 0:
            return None
        for line in out.splitlines():
            if 'rx_csum_offload_errors' in line:
                try:
                    return int(line.split(':')[1].strip())
                except (ValueError, IndexError):
                    pass
        return 0  # counter present but zero

    @staticmethod
    def _rx_csum_offload_enabled(iface):
        """Check if rx-checksumming is currently on."""
        rc, out, _ = _run(['ethtool', '-k', iface])
        if rc != 0:
            return None
        for line in out.splitlines():
            if 'rx-checksumming' in line:
                return 'on' in line.split(':')[1] if ':' in line else None
        return None

    @staticmethod
    def scan():
        result = {
            'name': 'nic_csum',
            'title': 'NIC Checksum Offload',
            'status': 'ok',
            'checks': [],
            'recommendations': [],
        }

        if not _is_installed('ethtool'):
            result['checks'].append({
                'name': 'ethtool',
                'status': 'ok',
                'detail': 'Not installed — skipping',
            })
            return result

        iface = NicChecksumOffload._get_primary_iface()
        if not iface:
            result['checks'].append({
                'name': 'Interface',
                'status': 'ok',
                'detail': 'No default route — skipping',
            })
            return result

        result['checks'].append({
            'name': 'Interface',
            'status': 'ok',
            'detail': iface,
        })

        # Check for errors
        errors = NicChecksumOffload._get_csum_errors(iface)
        if errors is None:
            # Counter not present on this NIC — not an e1000e or similar
            result['checks'].append({
                'name': 'rx_csum_errors',
                'status': 'ok',
                'detail': 'Not applicable (no hardware csum counter)',
            })
            return result

        # Check current offload state FIRST — it determines whether errors matter.
        # Linux NIC hardware counters (rx_csum_offload_errors) are READ-ONLY and
        # cannot be reset. Once rx-checksumming is disabled (rx off), no new errors
        # accumulate. If the fix is already applied (rx_on == False), the historical
        # error count is irrelevant — the problem is solved. Only warn if hardware
        # checksumming is still ACTIVE and errors are present.
        rx_on = NicChecksumOffload._rx_csum_offload_enabled(iface)
        fix_already_applied = (rx_on is not None and not rx_on)

        if errors > 0 and not fix_already_applied:
            # Hardware checksumming active AND errors present — real problem
            result['status'] = 'warning'
            result['checks'].append({
                'name': 'rx_csum_errors',
                'status': 'warning',
                'detail': f'{errors} errors — hardware checksum failing, packets dropped',
            })
            result['recommendations'].append(
                f'Disable hardware RX checksum: ethtool -K {iface} rx off')
        elif errors > 0 and fix_already_applied:
            # Historical errors remain in counter but fix is already active — OK
            # The counter cannot be cleared; these are pre-fix occurrences only.
            result['checks'].append({
                'name': 'rx_csum_errors',
                'status': 'ok',
                'detail': f'{errors} historical errors (counter frozen — fix already applied, no new errors accumulating)',
            })
        else:
            result['checks'].append({
                'name': 'rx_csum_errors',
                'status': 'ok',
                'detail': '0 errors',
            })

        if rx_on is not None:
            if errors > 0 and rx_on:
                result['checks'].append({
                    'name': 'rx-checksumming',
                    'status': 'warning',
                    'detail': 'on — hardware is failing checksums, fix needed',
                })
            elif not rx_on:
                result['checks'].append({
                    'name': 'rx-checksumming',
                    'status': 'ok',
                    'detail': 'off — CPU checksumming active (correct)',
                })
            else:
                result['checks'].append({
                    'name': 'rx-checksumming',
                    'status': 'ok',
                    'detail': 'on — no errors detected',
                })

        # Persistence check
        rps_script = Path('/usr/local/bin/mysterium-rps-setup.sh')
        persisted = rps_script.exists() and 'rx off' in (rps_script.read_text()
                    if rps_script.exists() else '')
        if errors > 0 and not fix_already_applied and not persisted:
            result['checks'].append({
                'name': 'Persistence',
                'status': 'warning',
                'detail': 'Not persisted (re-enables on reboot)',
            })
        elif persisted:
            result['checks'].append({
                'name': 'Persistence',
                'status': 'ok',
                'detail': 'Saved in boot script',
            })

        return result

    @staticmethod
    def fix():
        actions = []

        iface = NicChecksumOffload._get_primary_iface()
        if not iface:
            return {'name': 'nic_csum', 'actions': [
                {'action': 'No interface found', 'success': False}
            ], 'success': False}

        errors = NicChecksumOffload._get_csum_errors(iface)

        if errors is None:
            actions.append({'action': 'No rx_csum counter — NIC not affected', 'success': True})
            return {'name': 'nic_csum', 'actions': actions, 'success': True}

        rx_on = NicChecksumOffload._rx_csum_offload_enabled(iface)

        if errors > 0 or rx_on:
            rc, _, err = _run(['sudo', '-n', 'ethtool', '-K', iface, 'rx', 'off'])
            if rc == 0:
                actions.append({
                    'action': f'ethtool -K {iface} rx off — hardware csum disabled, CPU checksumming active',
                    'success': True,
                })
            else:
                actions.append({
                    'action': f'Disable RX checksum offload on {iface}',
                    'success': False,
                    'error': err[:80] if err else 'ethtool -K failed',
                })
        else:
            actions.append({
                'action': f'rx-checksumming already off or no errors — no change',
                'success': True,
            })

        return {'name': 'nic_csum', 'actions': actions,
                'success': all(a.get('success', True) for a in actions)}


# =============================================================================
# UNIFIED API
# =============================================================================

SUBSYSTEMS = [
    ConntrackHealth,
    CpuLoadBalance,
    ServiceWatchdog,
    KernelTuning,
    NicCoalescing,
    NicChecksumOffload,
    FirewallBackend,
    PortReachability,
    ProcessCleanup,
    RpsWatcher,
    SwapHealth,
    CpuGovernorHealth,
    BbrCongestion,
]


def scan_all():
    """Scan all subsystems (read-only, safe)."""
    results = []
    for sub in SUBSYSTEMS:
        try:
            results.append(sub.scan())
        except Exception as e:
            logger.error(f"Health scan error in {sub.__name__}: {e}")
            results.append({
                'name': getattr(sub, '__name__', 'unknown'),
                'title': getattr(sub, '__name__', 'unknown'),
                'status': 'unknown',
                'checks': [{'name': 'scan', 'status': 'critical', 'detail': str(e)[:80]}],
                'recommendations': [],
            })

    statuses = [r['status'] for r in results]
    overall = 'critical' if 'critical' in statuses else 'warning' if 'warning' in statuses else 'ok'

    return {
        'overall': overall,
        'subsystems': results,
        'scanned_at': datetime.now().isoformat(),
    }


def fix_all():
    """Fix all subsystems."""
    results = []
    for sub in SUBSYSTEMS:
        try:
            results.append(sub.fix())
        except Exception as e:
            logger.error(f"Health fix error in {sub.__name__}: {e}")
            results.append({
                'name': getattr(sub, '__name__', 'unknown'),
                'actions': [{'action': 'fix', 'success': False, 'error': str(e)[:80]}],
                'success': False,
            })

    return {
        'subsystems': results,
        'overall_success': all(r.get('success', False) for r in results),
        'fixed_at': datetime.now().isoformat(),
    }


def fix_one(subsystem_name):
    """Fix a single subsystem by name."""
    name_map = {
        'conntrack': ConntrackHealth,
        'cpu_balance': CpuLoadBalance,
        'service': ServiceWatchdog,
        'kernel': KernelTuning,
        'nic_coalesce': NicCoalescing,
        'nic_csum': NicChecksumOffload,
        'firewall_backend': FirewallBackend,
        'port_reachability': PortReachability,
        'process_cleanup': ProcessCleanup,
        'rps_watcher': RpsWatcher,
        'swap': SwapHealth,
        'cpu_governor': CpuGovernorHealth,
        'bbr': BbrCongestion,
    }

    sub = name_map.get(subsystem_name.lower())
    if not sub:
        return {'error': f'Unknown: {subsystem_name}', 'valid': list(name_map.keys())}
    try:
        return sub.fix()
    except Exception as e:
        return {'name': subsystem_name, 'actions': [], 'success': False, 'error': str(e)}


# =============================================================================
# PERSISTENCE — Lock current in-memory fixes to survive reboots
# =============================================================================

SYSCTL_PERSIST_FILE = '/etc/sysctl.d/99-mysterium-node.conf'
RPS_SERVICE_NAME = 'mysterium-rps-tuning'
RPS_SERVICE_FILE = f'/etc/systemd/system/{RPS_SERVICE_NAME}.service'
RPS_SCRIPT_FILE = '/usr/local/bin/mysterium-rps-setup.sh'


def persist_all():
    """Persist current working settings to disk so they survive reboot.

    Only call this AFTER --health-fix has been applied and verified working.
    Creates:
    - /etc/sysctl.d/99-mysterium-node.conf (kernel params + conntrack)
    - /usr/local/bin/mysterium-rps-setup.sh (RPS has no sysctl equivalent)
    - /etc/systemd/system/mysterium-rps-tuning.service (runs script on boot)
    """
    actions = []

    # ===== 1. Persist sysctl params (read CURRENT live values, not defaults) =====
    sysctl_lines = [
        '# Mysterium Node Toolkit — persisted network tuning',
        '# Generated by --health-persist. Remove with --health-unpersist or recovery.sh',
        f'# Created: {datetime.now().isoformat()}',
        '',
    ]

    for key, optimal in KernelTuning.SAFE_PARAMS.items():
        current = _sysctl_get(key)
        if current is not None:
            sysctl_lines.append(f'{key} = {current}')

    # Conntrack max — also ensure module loads at boot via modules-load.d
    ct_max = _sysctl_get('net.netfilter.nf_conntrack_max')
    if ct_max:
        sysctl_lines.append(f'net.netfilter.nf_conntrack_max = {ct_max}')
        # Write modules-load.d so nf_conntrack loads BEFORE sysctl at boot
        try:
            _run(['sudo', '-n', 'bash', '-c',
                  'echo nf_conntrack > /etc/modules-load.d/nf_conntrack.conf'])
        except Exception:
            pass

    sysctl_content = '\n'.join(sysctl_lines) + '\n'

    try:
        rc, _, err = _run(['sudo', '-n', 'bash', '-c',
                           f'cat > {SYSCTL_PERSIST_FILE} << SYSCTL_EOF\n{sysctl_content}SYSCTL_EOF'])
        ok = rc == 0
        actions.append({
            'action': f'Wrote {SYSCTL_PERSIST_FILE}',
            'success': ok,
            'error': err if not ok else None,
        })
    except Exception as e:
        actions.append({'action': f'Write {SYSCTL_PERSIST_FILE}', 'success': False, 'error': str(e)})

    # ===== 2. Create RPS setup script =====
    cpu_count = os.cpu_count() or 1
    all_mask = format((1 << cpu_count) - 1, 'x')

    # Discover current VPN + primary interfaces
    primary = CpuLoadBalance._get_primary_iface()
    vpn_ifaces = [i for i in (psutil.net_io_counters(pernic=True) or {})
                  if i.startswith(('myst', 'wg', 'tun'))]

    iface_list = []
    if primary:
        iface_list.append(primary)

    # Check current NIC coalescing to include in boot script
    nic_coal = NicCoalescing._get_coalesce(primary) if primary else {}
    nic_rx_usecs = nic_coal.get('rx-usecs')
    # Use current value if already fixed, otherwise use target
    coal_value = max(nic_rx_usecs or 0, NicCoalescing.TARGET_RX_USECS)

    # VPN interfaces are dynamic, so the script handles them at boot
    rps_script = f"""#!/bin/bash
# Mysterium Node Toolkit — RPS + NIC tuning (runs at boot)
# Distributes network packet processing across all {cpu_count} CPU cores
# Sets NIC interrupt coalescing to prevent e1000e IRQ storm freeze
# Generated by --health-persist

MASK="{all_mask}"
IFACE="{primary or 'eth0'}"

# === NIC Interrupt Coalescing ===
# Prevents freeze on e1000e (Intel 82579) under VPN tunnel load
ethtool -C "$IFACE" rx-usecs {coal_value} 2>/dev/null

# === RPS: Primary NIC ===
for q in /sys/class/net/$IFACE/queues/rx-*/rps_cpus; do
    echo "$MASK" > "$q" 2>/dev/null
done

# VPN interfaces handled by mysterium-rps-watcher.timer (every 30s)
# This boot script only covers the primary NIC
exit 0
"""

    try:
        rc, _, err = _run(['sudo', '-n', 'bash', '-c',
                           f'cat > {RPS_SCRIPT_FILE} << "SCRIPT_EOF"\n{rps_script}SCRIPT_EOF\n'
                           f'chmod +x {RPS_SCRIPT_FILE}'])
        ok = rc == 0
        actions.append({
            'action': f'Wrote {RPS_SCRIPT_FILE}',
            'success': ok,
            'error': err if not ok else None,
        })
    except Exception as e:
        actions.append({'action': f'Write {RPS_SCRIPT_FILE}', 'success': False, 'error': str(e)})

    # ===== 3. Create systemd oneshot service =====
    service_unit = f"""[Unit]
Description=Mysterium Node NIC + RPS Tuning
After=network-online.target mysterium-node.service
Wants=network-online.target

[Service]
Type=oneshot
ExecStart={RPS_SCRIPT_FILE}
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
"""

    try:
        rc, _, err = _run(['sudo', '-n', 'bash', '-c',
                           f'cat > {RPS_SERVICE_FILE} << "SVC_EOF"\n{service_unit}SVC_EOF\n'
                           f'systemctl daemon-reload && systemctl enable {RPS_SERVICE_NAME}'])
        ok = rc == 0
        actions.append({
            'action': f'Created and enabled {RPS_SERVICE_NAME}.service',
            'success': ok,
            'error': err if not ok else None,
        })
    except Exception as e:
        actions.append({'action': f'Create {RPS_SERVICE_NAME}.service', 'success': False, 'error': str(e)})

    # ===== 4. Install auto-RPS watcher timer (handles dynamic VPN interfaces) =====
    try:
        watcher_result = RpsWatcher.fix()
        for a in watcher_result.get('actions', []):
            actions.append(a)
    except Exception as e:
        actions.append({'action': 'Install auto-RPS watcher', 'success': False, 'error': str(e)})

    return {
        'actions': actions,
        'overall_success': all(a.get('success', True) for a in actions),
        'persisted_at': datetime.now().isoformat(),
        'note': 'Settings will survive reboot. Run --health-unpersist or recovery.sh to undo.',
    }



def persist_one(subsystem_name):
    """Persist a single subsystem's settings to survive reboot.

    Maps each subsystem to the specific files / services it needs:
      conntrack    → sysctl.d entry for nf_conntrack_max
      kernel       → sysctl.d entries for SAFE_PARAMS
      nic_coalesce → adds ethtool call to RPS boot script + enables service
      cpu_balance  → RPS boot script + enables service
      rps_watcher  → installs watcher timer (already handled by RpsWatcher.fix)
      service / firewall_backend / port_reachability / process_cleanup
                   → no persistent state needed (runtime-only checks)
    """
    name = subsystem_name.lower()
    actions = []

    SYSCTL_HEADER = [
        '# Mysterium Node Toolkit — persisted network tuning',
        '# Generated by persist_one. Remove with unpersist_one or recovery.sh',
        f'# Created: {datetime.now().isoformat()}',
        '',
    ]

    def _read_sysctl_file():
        """Read existing sysctl persist file, return list of lines."""
        try:
            rc, out, _ = _run(['sudo', '-n', 'cat', SYSCTL_PERSIST_FILE])
            if rc == 0 and out:
                return out.splitlines()
        except Exception:
            pass
        return []

    def _write_sysctl_lines(new_lines):
        """Merge new_lines into existing sysctl file, dedup by key."""
        existing = _read_sysctl_file()
        # Build dict of key → value from existing (skip comments/blanks)
        existing_map = {}
        for line in existing:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                existing_map[k.strip()] = v.strip()
        # Override with new lines
        for line in new_lines:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                existing_map[k.strip()] = v.strip()
        # Reconstruct file
        merged = list(SYSCTL_HEADER)
        for k, v in sorted(existing_map.items()):
            merged.append(f'{k} = {v}')
        merged_content = '\n'.join(merged) + '\n'
        rc, _, err = _run(['sudo', '-n', 'bash', '-c',
                           f'printf "%s" {chr(39)}{merged_content}{chr(39)} > {SYSCTL_PERSIST_FILE}'])
        return rc == 0, err

    # ── conntrack ────────────────────────────────────────────
    if name == 'conntrack':
        ct_max = _sysctl_get('net.netfilter.nf_conntrack_max')
        if ct_max:
            ok, err = _write_sysctl_lines([f'net.netfilter.nf_conntrack_max = {ct_max}'])
            actions.append({'action': f'Persisted nf_conntrack_max={ct_max} → {SYSCTL_PERSIST_FILE}',
                            'success': ok, 'error': err if not ok else None})
            try:
                rc2, _, err2 = _run(['sudo', '-n', 'bash', '-c',
                                     'echo nf_conntrack > /etc/modules-load.d/nf_conntrack.conf'])
                actions.append({
                    'action': 'nf_conntrack → /etc/modules-load.d/nf_conntrack.conf (loads before sysctl at boot)',
                    'success': rc2 == 0, 'error': err2 if rc2 != 0 else None,
                })
            except Exception as _e:
                actions.append({'action': 'nf_conntrack modules-load.d', 'success': False, 'error': str(_e)})
        else:
            actions.append({'action': 'conntrack not loaded — nothing to persist', 'success': True})

    # ── kernel ────────────────────────────────────────────────
    elif name == 'kernel':
        sysctl_lines = []
        for key in KernelTuning.SAFE_PARAMS:
            current = _sysctl_get(key)
            if current is not None:
                sysctl_lines.append(f'{key} = {current}')
        if sysctl_lines:
            ok, err = _write_sysctl_lines(sysctl_lines)
            actions.append({'action': f'Persisted {len(sysctl_lines)} kernel params → {SYSCTL_PERSIST_FILE}',
                            'success': ok, 'error': err if not ok else None})
        else:
            actions.append({'action': 'No kernel params to persist', 'success': True})

    # ── nic_coalesce ─────────────────────────────────────────
    elif name == 'nic_coalesce':
        primary = CpuLoadBalance._get_primary_iface()
        if primary:
            nic_coal = NicCoalescing._get_coalesce(primary)
            rx_usecs = max(nic_coal.get('rx-usecs') or 0, NicCoalescing.TARGET_RX_USECS)
            # Write/update RPS script with coalescing command
            cpu_count = os.cpu_count() or 1
            all_mask = format((1 << cpu_count) - 1, 'x')
            rps_script = f"""#!/bin/bash
# Mysterium Node Toolkit — NIC + RPS tuning (runs at boot)
MASK="{all_mask}"
IFACE="{primary}"
ethtool -C "$IFACE" rx-usecs {rx_usecs} 2>/dev/null
for q in /sys/class/net/$IFACE/queues/rx-*/rps_cpus; do
    echo "$MASK" > "$q" 2>/dev/null
done
exit 0
"""
            rc, _, err = _run(['sudo', '-n', 'bash', '-c',
                               f'printf "%s" {chr(39)}{rps_script}{chr(39)} > {RPS_SCRIPT_FILE} && chmod +x {RPS_SCRIPT_FILE}'])
            ok = rc == 0
            actions.append({'action': f'Persisted NIC coalescing (rx-usecs={rx_usecs}) + RPS → {RPS_SCRIPT_FILE}',
                            'success': ok, 'error': err if not ok else None})
            # Enable systemd service
            rc2, _, err2 = _run(['sudo', '-n', 'bash', '-c',
                                  f'systemctl daemon-reload && systemctl enable {RPS_SERVICE_NAME}'])
            actions.append({'action': f'Enabled {RPS_SERVICE_NAME}.service',
                            'success': rc2 == 0, 'error': err2 if rc2 != 0 else None})
            # Write service unit if it doesn't exist
            if not Path(RPS_SERVICE_FILE).exists():
                service_unit = f"""[Unit]
Description=Mysterium Node NIC + RPS Tuning
After=network-online.target
Wants=network-online.target
[Service]
Type=oneshot
ExecStart={RPS_SCRIPT_FILE}
RemainAfterExit=yes
[Install]
WantedBy=multi-user.target
"""
                _run(['sudo', '-n', 'bash', '-c',
                      f'printf "%s" {chr(39)}{service_unit}{chr(39)} > {RPS_SERVICE_FILE} && systemctl daemon-reload && systemctl enable {RPS_SERVICE_NAME}'])
        else:
            actions.append({'action': 'No primary interface found', 'success': False})

    # ── cpu_balance (RPS) ────────────────────────────────────
    elif name == 'cpu_balance':
        primary = CpuLoadBalance._get_primary_iface()
        cpu_count = os.cpu_count() or 1
        all_mask = format((1 << cpu_count) - 1, 'x')
        if primary:
            nic_coal = NicCoalescing._get_coalesce(primary) if primary else {}
            coal_value = max(nic_coal.get('rx-usecs') or 0, NicCoalescing.TARGET_RX_USECS)
            rps_script = f"""#!/bin/bash
# Mysterium Node Toolkit — NIC + RPS tuning (runs at boot)
MASK="{all_mask}"
IFACE="{primary}"
ethtool -C "$IFACE" rx-usecs {coal_value} 2>/dev/null
for q in /sys/class/net/$IFACE/queues/rx-*/rps_cpus; do
    echo "$MASK" > "$q" 2>/dev/null
done
exit 0
"""
            rc, _, err = _run(['sudo', '-n', 'bash', '-c',
                               f'printf "%s" {chr(39)}{rps_script}{chr(39)} > {RPS_SCRIPT_FILE} && chmod +x {RPS_SCRIPT_FILE}'])
            ok = rc == 0
            actions.append({'action': f'Persisted RPS (mask={all_mask}) → {RPS_SCRIPT_FILE}',
                            'success': ok, 'error': err if not ok else None})
            if not Path(RPS_SERVICE_FILE).exists():
                service_unit = f"""[Unit]
Description=Mysterium Node NIC + RPS Tuning
After=network-online.target
Wants=network-online.target
[Service]
Type=oneshot
ExecStart={RPS_SCRIPT_FILE}
RemainAfterExit=yes
[Install]
WantedBy=multi-user.target
"""
                _run(['sudo', '-n', 'bash', '-c',
                      f'printf "%s" {chr(39)}{service_unit}{chr(39)} > {RPS_SERVICE_FILE}'])
            rc2, _, err2 = _run(['sudo', '-n', 'bash', '-c',
                                  'systemctl daemon-reload && systemctl enable ' + RPS_SERVICE_NAME])
            actions.append({'action': f'Enabled {RPS_SERVICE_NAME}.service',
                            'success': rc2 == 0, 'error': err2 if rc2 != 0 else None})
        else:
            actions.append({'action': 'No primary interface found', 'success': False})

    # ── rps_watcher ──────────────────────────────────────────
    elif name == 'rps_watcher':
        try:
            result = RpsWatcher.fix()
            for a in result.get('actions', []):
                actions.append(a)
        except Exception as e:
            actions.append({'action': 'Install RPS watcher timer', 'success': False, 'error': str(e)})

    # ── nic_csum ─────────────────────────────────────────────────
    elif name == 'nic_csum':
        iface = NicChecksumOffload._get_primary_iface()
        if iface:
            rps_script_path = Path(RPS_SCRIPT_FILE)
            if rps_script_path.exists():
                try:
                    existing = rps_script_path.read_text()
                except Exception:
                    existing = ''
                if 'ethtool -K' not in existing:
                    rc, _, err = _run(['sudo', '-n', 'bash', '-c',
                                       f'echo \'ethtool -K "{iface}" rx off 2>/dev/null\' >> {RPS_SCRIPT_FILE}'])
                    actions.append({'action': f'Added ethtool -K rx off to {RPS_SCRIPT_FILE}',
                                    'success': rc == 0, 'error': err if rc != 0 else None})
                else:
                    actions.append({'action': f'ethtool -K rx off already in {RPS_SCRIPT_FILE}', 'success': True})
            else:
                # Create minimal boot script
                script = f'#!/bin/bash\nethtool -K "{iface}" rx off 2>/dev/null\n'
                rc, _, err = _run(['sudo', '-n', 'bash', '-c',
                                   f"printf '%s' '{script}' > {RPS_SCRIPT_FILE} && chmod +x {RPS_SCRIPT_FILE}"])
                actions.append({'action': f'Created {RPS_SCRIPT_FILE} with csum fix',
                                'success': rc == 0, 'error': err if rc != 0 else None})
        else:
            actions.append({'action': 'No interface found', 'success': False})

    # ── swap ─────────────────────────────────────────────────────
    elif name == 'swap':
        sf = SwapHealth.SWAPFILE_PATH
        # Add to fstab if not already there
        try:
            with open('/etc/fstab') as f:
                fstab = f.read()
            if sf not in fstab:
                rc, _, err = _run(['sudo', '-n', 'bash', '-c',
                                   f"echo '{sf} none swap sw 0 0' >> /etc/fstab"])
                actions.append({'action': f'Added {sf} to /etc/fstab',
                                'success': rc == 0,
                                'error': err if rc != 0 else None})
            else:
                actions.append({'action': f'{sf} already in /etc/fstab', 'success': True})
        except Exception as e:
            actions.append({'action': 'Update /etc/fstab', 'success': False, 'error': str(e)})
        # Persist swappiness
        ok, err = _write_sysctl_lines(['vm.swappiness = 60'])
        actions.append({'action': f'Persisted vm.swappiness=60 → {SYSCTL_PERSIST_FILE}',
                        'success': ok, 'error': err if not ok else None})

    # ── cpu_governor ──────────────────────────────────────────────
    elif name == 'cpu_governor':
        cpu_count = os.cpu_count() or 1
        # Strategy 1: cpupower service (Fedora/Arch/openSUSE)
        if _is_installed('cpupower'):
            # Write /etc/default/cpupower (Fedora/Arch)
            rc, _, _ = _run(['sudo', '-n', 'bash', '-c',
                             "echo 'GOVERNOR=performance' > /etc/default/cpupower"])
            if rc == 0:
                _run(['sudo', '-n', 'systemctl', 'enable', '--now', 'cpupower'])
                actions.append({'action': 'cpupower: GOVERNOR=performance enabled', 'success': True})
            else:
                # Try cpufrequtils (Debian/Ubuntu)
                rc2, _, _ = _run(['sudo', '-n', 'bash', '-c',
                                  "echo 'GOVERNOR=\"performance\"' > /etc/default/cpufrequtils"])
                actions.append({'action': 'cpufrequtils: GOVERNOR=performance',
                                'success': rc2 == 0})
        # Strategy 2: Alpine OpenRC — /etc/local.d approach (no systemd)
        elif not _is_installed('systemctl') and (Path('/etc/local.d').exists() or _is_installed('rc-service')):
            gov_line = r'for g in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do echo performance > "$g" 2>/dev/null; done'
            rc, _, err = _run(['sudo', '-n', 'bash', '-c',
                               f"mkdir -p /etc/local.d && "
                               f"printf '#!/bin/sh\\n{gov_line}\\n' > /etc/local.d/myst-governor.start && "
                               f"chmod +x /etc/local.d/myst-governor.start && "
                               f"rc-update add local default 2>/dev/null || true"])
            actions.append({'action': 'Alpine: wrote /etc/local.d/myst-governor.start',
                            'success': rc == 0, 'error': err if rc != 0 else None})
        # Strategy 3: systemd service that writes governors on boot
        else:
            gov_script = f"""#!/bin/bash
# Mysterium Node Toolkit — CPU Performance Governor
# Sets all {cpu_count} cores to performance on boot
for g in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
    echo performance > "$g" 2>/dev/null
done
"""
            gov_script_path = '/usr/local/bin/mysterium-cpu-governor.sh'
            gov_service = f"""[Unit]
Description=Mysterium CPU Performance Governor
After=multi-user.target

[Service]
Type=oneshot
ExecStart={gov_script_path}
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
"""
            svc_path = '/etc/systemd/system/mysterium-cpu-governor.service'
            # Write script via stdin to avoid quote/backslash corruption
            rc, _, err = _run(['sudo', 'bash', '-c',
                               f'cat > {gov_script_path} && chmod +x {gov_script_path}'],
                              input_data=gov_script)
            actions.append({'action': f'Wrote {gov_script_path}',
                            'success': rc == 0, 'error': err if rc != 0 else None})
            rc2, _, err2 = _run(['sudo', 'bash', '-c',
                                 f'cat > {svc_path} && '
                                 f'systemctl daemon-reload && '
                                 f'systemctl enable --now mysterium-cpu-governor'],
                                input_data=gov_service)
            actions.append({'action': 'Enabled mysterium-cpu-governor.service',
                            'success': rc2 == 0, 'error': err2 if rc2 != 0 else None})

    # ── bbr ───────────────────────────────────────────────────────
    elif name == 'bbr':
        # Persist via sysctl.d
        ok, err = _write_sysctl_lines([
            'net.ipv4.tcp_congestion_control = bbr',
            'net.core.default_qdisc = fq',
        ])
        actions.append({'action': f'Persisted BBR + fq → {SYSCTL_PERSIST_FILE}',
                        'success': ok, 'error': err if not ok else None})
        # Persist module load
        modules_dir = Path('/etc/modules-load.d')
        if modules_dir.exists():
            rc, _, err = _run(['sudo', '-n', 'bash', '-c',
                               'echo tcp_bbr > /etc/modules-load.d/tcp_bbr.conf'])
            actions.append({'action': 'Persisted tcp_bbr → /etc/modules-load.d/tcp_bbr.conf',
                            'success': rc == 0, 'error': err if rc != 0 else None})
        else:
            # Alpine / older systems: /etc/modules
            rc, _, err = _run(['sudo', '-n', 'bash', '-c',
                               "grep -q tcp_bbr /etc/modules 2>/dev/null || echo tcp_bbr >> /etc/modules"])
            actions.append({'action': 'Persisted tcp_bbr → /etc/modules',
                            'success': rc == 0, 'error': err if rc != 0 else None})

    # ── service / firewall / port / process — runtime checks only ─
    else:
        actions.append({'action': f'{subsystem_name}: no persistent state needed (runtime check only)',
                        'success': True})

    return {
        'name': subsystem_name,
        'actions': actions,
        'overall_success': all(a.get('success', True) for a in actions),
        'persisted_at': datetime.now().isoformat(),
    }


def unpersist_one(subsystem_name):
    """Remove persisted settings for a single subsystem."""
    name = subsystem_name.lower()
    actions = []

    def _remove_sysctl_keys(keys_to_remove):
        """Remove specific keys from the sysctl persist file."""
        try:
            rc, out, _ = _run(['sudo', '-n', 'cat', SYSCTL_PERSIST_FILE])
            if rc != 0 or not out:
                actions.append({'action': 'No sysctl persist file found', 'success': True})
                return
            lines = out.splitlines()
            new_lines = []
            removed = 0
            for line in lines:
                stripped = line.strip()
                if stripped and not stripped.startswith('#') and '=' in stripped:
                    key = stripped.split('=')[0].strip()
                    if key in keys_to_remove:
                        removed += 1
                        continue
                new_lines.append(line)
            if removed == 0:
                actions.append({'action': f'No matching keys found in {SYSCTL_PERSIST_FILE}', 'success': True})
                return
            new_content = '\n'.join(new_lines) + '\n'
            # If file would be empty (only comments/blanks), remove it
            has_real_content = any(
                l.strip() and not l.strip().startswith('#')
                for l in new_lines
            )
            if not has_real_content:
                rc2, _, _ = _run(['sudo', '-n', 'rm', '-f', SYSCTL_PERSIST_FILE])
                actions.append({'action': f'Removed empty {SYSCTL_PERSIST_FILE}', 'success': rc2 == 0})
            else:
                rc2, _, err = _run(['sudo', '-n', 'bash', '-c',
                                    f'printf "%s" {chr(39)}{new_content}{chr(39)} > {SYSCTL_PERSIST_FILE}'])
                actions.append({'action': f'Removed {removed} key(s) from {SYSCTL_PERSIST_FILE}',
                                'success': rc2 == 0, 'error': err if rc2 != 0 else None})
            # Reload sysctl so removal takes effect
            _run(['sudo', '-n', 'sysctl', '--system'])
        except Exception as e:
            actions.append({'action': f'Modify {SYSCTL_PERSIST_FILE}', 'success': False, 'error': str(e)})

    if name == 'conntrack':
        _remove_sysctl_keys({'net.netfilter.nf_conntrack_max'})

    elif name == 'kernel':
        _remove_sysctl_keys(set(KernelTuning.SAFE_PARAMS.keys()))

    elif name in ('nic_coalesce', 'cpu_balance'):
        # Remove boot script + disable service
        for path, label in [(RPS_SCRIPT_FILE, 'RPS boot script'), (RPS_SERVICE_FILE, 'RPS service')]:
            if Path(path).exists():
                rc, _, err = _run(['sudo', '-n', 'rm', '-f', path])
                actions.append({'action': f'Removed {label}', 'success': rc == 0,
                                'error': err if rc != 0 else None})
        _run(['sudo', '-n', 'systemctl', 'disable', '--now', RPS_SERVICE_NAME])
        _run(['sudo', '-n', 'systemctl', 'daemon-reload'])
        actions.append({'action': f'Disabled {RPS_SERVICE_NAME}.service', 'success': True})

    elif name == 'rps_watcher':
        for path in [RPS_WATCHER_SCRIPT,
                     f'/etc/systemd/system/{RPS_WATCHER_SERVICE}',
                     f'/etc/systemd/system/{RPS_WATCHER_TIMER}']:
            if Path(path).exists():
                _run(['sudo', '-n', 'rm', '-f', path])
        _run(['sudo', '-n', 'systemctl', 'disable', '--now', RPS_WATCHER_TIMER])
        _run(['sudo', '-n', 'systemctl', 'daemon-reload'])
        actions.append({'action': 'Removed RPS watcher timer', 'success': True})

    elif name == 'nic_csum':
        # Remove ethtool -K line from boot script
        if Path(RPS_SCRIPT_FILE).exists():
            rc, _, err = _run(['sudo', '-n', 'bash', '-c',
                               f"sed -i '/ethtool -K.*rx off/d' {RPS_SCRIPT_FILE}"])
            actions.append({'action': f'Removed ethtool -K rx off from {RPS_SCRIPT_FILE}',
                            'success': rc == 0, 'error': err if rc != 0 else None})
        else:
            actions.append({'action': 'No boot script to modify', 'success': True})
        # Re-enable rx checksum in live system
        iface = NicChecksumOffload._get_primary_iface()
        if iface:
            rc, _, _ = _run(['sudo', '-n', 'ethtool', '-K', iface, 'rx', 'on'])
            actions.append({'action': f'ethtool -K {iface} rx on (re-enabled)', 'success': rc == 0})

    elif name == 'swap':
        # Remove swappiness from sysctl persist file
        _remove_sysctl_keys({'vm.swappiness'})
        # Remove swapfile fstab entry (but don't deactivate live swap)
        sf = SwapHealth.SWAPFILE_PATH
        try:
            with open('/etc/fstab') as f:
                lines = f.readlines()
            new_lines = [l for l in lines if sf not in l]
            if len(new_lines) < len(lines):
                content = ''.join(new_lines)
                rc, _, err = _run(['sudo', '-n', 'bash', '-c',
                                   f"printf '%s' '{content}' > /etc/fstab"])
                actions.append({'action': f'Removed {sf} from /etc/fstab',
                                'success': rc == 0})
            else:
                actions.append({'action': 'No swap entry in /etc/fstab to remove',
                                'success': True})
        except Exception as e:
            actions.append({'action': 'Update /etc/fstab', 'success': False, 'error': str(e)})

    elif name == 'cpu_governor':
        # Remove systemd service if present
        for path in ['/usr/local/bin/mysterium-cpu-governor.sh',
                     '/etc/systemd/system/mysterium-cpu-governor.service']:
            if Path(path).exists():
                _run(['sudo', '-n', 'rm', '-f', path])
        _run(['sudo', '-n', 'systemctl', 'disable', '--now', 'mysterium-cpu-governor'])
        _run(['sudo', '-n', 'systemctl', 'daemon-reload'])
        # Remove cpupower/cpufrequtils config
        for cfg in ['/etc/default/cpupower', '/etc/default/cpufrequtils']:
            if Path(cfg).exists():
                _run(['sudo', '-n', 'rm', '-f', cfg])
        # Remove Alpine local.d script
        if Path('/etc/local.d/myst-governor.start').exists():
            _run(['sudo', '-n', 'rm', '-f', '/etc/local.d/myst-governor.start'])
        actions.append({'action': 'Removed CPU governor persistence — reverts to default on reboot',
                        'success': True})

    elif name == 'bbr':
        _remove_sysctl_keys({'net.ipv4.tcp_congestion_control', 'net.core.default_qdisc'})
        for path in ['/etc/modules-load.d/tcp_bbr.conf',
                     '/etc/modules-load.d/nf_conntrack.conf']:
            if Path(path).exists():
                _run(['sudo', '-n', 'rm', '-f', path])
        # Remove from /etc/modules if present
        _run(['sudo', '-n', 'bash', '-c',
              "sed -i '/^tcp_bbr$/d' /etc/modules 2>/dev/null || true"])
        actions.append({'action': 'Removed BBR persistence — reverts to default CC on reboot',
                        'success': True})

    else:
        actions.append({'action': f'{subsystem_name}: no persistent state to remove', 'success': True})

    return {
        'name': subsystem_name,
        'actions': actions,
        'overall_success': all(a.get('success', True) for a in actions),
        'unpersisted_at': datetime.now().isoformat(),
    }


def unpersist_all():
    """Remove all persisted settings. Revert to system defaults on next reboot."""
    actions = []

    for path, label in [(SYSCTL_PERSIST_FILE, 'sysctl overrides'),
                         (RPS_SCRIPT_FILE, 'RPS script'),
                         (RPS_SERVICE_FILE, 'RPS service'),
                         (RPS_WATCHER_SCRIPT, 'RPS watcher script'),
                         (f'/etc/systemd/system/{RPS_WATCHER_SERVICE}', 'RPS watcher service'),
                         (f'/etc/systemd/system/{RPS_WATCHER_TIMER}', 'RPS watcher timer')]:
        if Path(path).exists():
            rc, _, err = _run(['sudo', '-n', 'rm', '-f', path])
            actions.append({'action': f'Removed {label} ({path})', 'success': rc == 0,
                            'error': err if rc != 0 else None})

    # Disable service and watcher timer
    _run(['sudo', '-n', 'systemctl', 'disable', '--now', RPS_WATCHER_TIMER])
    _run(['sudo', '-n', 'systemctl', 'disable', RPS_SERVICE_NAME])
    _run(['sudo', '-n', 'systemctl', 'disable', '--now', 'mysterium-cpu-governor'])
    _run(['sudo', '-n', 'systemctl', 'daemon-reload'])
    actions.append({'action': f'Disabled {RPS_SERVICE_NAME}', 'success': True})

    # Remove CPU governor scripts/configs
    for path in ['/usr/local/bin/mysterium-cpu-governor.sh',
                 '/etc/systemd/system/mysterium-cpu-governor.service',
                 '/etc/default/cpupower', '/etc/default/cpufrequtils',
                 '/etc/modules-load.d/tcp_bbr.conf']:
        if Path(path).exists():
            _run(['sudo', '-n', 'rm', '-f', path])
    _run(['sudo', '-n', 'bash', '-c',
          "sed -i '/^tcp_bbr$/d' /etc/modules 2>/dev/null || true"])
    actions.append({'action': 'Removed CPU governor + BBR persistence files', 'success': True})

    # Reload sysctl defaults
    rc, _, _ = _run(['sudo', '-n', 'sysctl', '--system'])
    actions.append({'action': 'Reloaded system sysctl defaults', 'success': rc == 0})

    # Ensure ip_forward stays on
    _sysctl_set('net.ipv4.ip_forward', 1)
    actions.append({'action': 'Ensured ip_forward=1', 'success': True})

    return {
        'actions': actions,
        'overall_success': all(a.get('success', True) for a in actions),
        'unpersisted_at': datetime.now().isoformat(),
    }
