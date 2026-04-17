#!/usr/bin/env python3
"""
Mysterium Node Installer
=========================
Full interactive installer for the Mysterium node on any Linux distro.

Supports:
  - APT install       (Debian / Ubuntu / Parrot / Mint / Pop / Kali)
  - DNF/YUM install   (Fedora / RHEL / CentOS / Rocky / Alma)
  - Pacman install    (Arch / Manjaro / EndeavourOS)
  - APK install       (Alpine)
  - Docker install    (any distro with Docker)
  - Manual .deb       (offline / specific version)
  - Script install    (curl | bash — Mysterium official)

Author: Ian Johnsons
License: CC BY-NC-SA 4.0
"""

import subprocess
import sys
import os
import shutil
import time
import json
import urllib.request
import tempfile
from pathlib import Path

# ── Colors ────────────────────────────────────────────────────────────────────
GREEN  = '\033[0;32m'
YELLOW = '\033[1;33m'
RED    = '\033[0;31m'
CYAN   = '\033[96m'
BOLD   = '\033[1m'
DIM    = '\033[2m'
NC     = '\033[0m'

def c(color, sym, msg):
    print(f"  {color}{sym}{NC} {msg}")

def header(title):
    w = min(70, max(len(title) + 8, 52))
    inner = w - 2
    print(f"\n  {BOLD}{CYAN}╔{'═' * inner}╗{NC}")
    print(f"  {BOLD}{CYAN}║  {title:<{inner - 3}}║{NC}")
    print(f"  {BOLD}{CYAN}╚{'═' * inner}╝{NC}\n")

def ask(prompt, options=None, default=None):
    """Simple prompt. If options given, validates input. Returns string."""
    if options:
        while True:
            try:
                choice = input(f"  {CYAN}{prompt}{NC} ").strip()
                if not choice and default is not None:
                    return default
                if choice in options:
                    return choice
                print(f"  {YELLOW}⚠ Enter one of: {', '.join(options)}{NC}")
            except (KeyboardInterrupt, EOFError):
                print()
                sys.exit(0)
    else:
        try:
            val = input(f"  {CYAN}{prompt}{NC} ").strip()
            return val if val else (default or '')
        except (KeyboardInterrupt, EOFError):
            print()
            sys.exit(0)

def run(cmd, timeout=60, check=False, capture=False):
    """Run a shell command. Returns (returncode, stdout)."""
    try:
        r = subprocess.run(
            cmd if isinstance(cmd, list) else cmd,
            shell=isinstance(cmd, str),
            capture_output=capture,
            text=True,
            timeout=timeout
        )
        return r.returncode, (r.stdout or '').strip()
    except subprocess.TimeoutExpired:
        return -1, 'timeout'
    except FileNotFoundError:
        return -1, 'not found'
    except Exception as e:
        return -1, str(e)

def need_sudo():
    """Check if sudo is needed (not running as root)."""
    return os.geteuid() != 0

def sudo(cmd):
    """Prefix with sudo if needed."""
    if need_sudo():
        if isinstance(cmd, list):
            return ['sudo'] + cmd
        return 'sudo ' + cmd
    return cmd

# ── Distro detection ──────────────────────────────────────────────────────────
def detect_distro():
    info = {'id': 'unknown', 'id_like': '', 'pretty': 'Linux', 'version': ''}
    try:
        with open('/etc/os-release') as f:
            for line in f:
                if '=' in line:
                    k, v = line.strip().split('=', 1)
                    v = v.strip('"')
                    if k == 'ID':           info['id'] = v.lower()
                    elif k == 'ID_LIKE':    info['id_like'] = v.lower()
                    elif k == 'PRETTY_NAME': info['pretty'] = v
                    elif k == 'VERSION_ID':  info['version'] = v
    except Exception:
        pass
    return info

def get_pkg_manager(distro):
    """Return package manager name for the distro."""
    d = distro['id']
    like = distro['id_like']
    if d in ('debian', 'ubuntu', 'parrot', 'linuxmint', 'pop', 'elementary',
             'kali', 'raspbian', 'neon') or 'debian' in like or 'ubuntu' in like:
        return 'apt'
    if d in ('fedora',) or 'fedora' in like:
        return 'dnf'
    if d in ('rhel', 'centos', 'rocky', 'almalinux', 'ol') or 'rhel' in like:
        rc, _ = run(['dnf', '--version'], capture=True)
        return 'dnf' if rc == 0 else 'yum'
    if d in ('arch', 'manjaro', 'endeavouros', 'garuda') or 'arch' in like:
        return 'pacman'
    if d in ('alpine',):
        return 'apk'
    if d in ('opensuse-leap', 'opensuse-tumbleweed', 'sles') or 'suse' in like:
        return 'zypper'
    return 'unknown'

# ── Node detection ────────────────────────────────────────────────────────────
def detect_node():
    """Check if a node is already running. Returns (running, method, detail)."""
    rc, _ = run(['systemctl', 'is-active', 'mysterium-node'], capture=True)
    if rc == 0:
        return True, 'systemd', 'mysterium-node service is active'

    rc, out = run(['docker', 'ps', '--filter', 'name=myst', '--format', '{{.Names}}'],
                  capture=True)
    if rc == 0 and out:
        return True, 'docker', f'Docker container: {out.splitlines()[0]}'

    rc, out = run(['pgrep', '-af', 'myst'], capture=True)
    if rc == 0 and out:
        skip_keywords = ['mysterium-toolkit', 'setup.sh', 'start.sh', 'setup_wizard',
                         'node_install', 'node_installer', 'dashboard.py', 'app.py']
        for line in out.splitlines():
            if any(kw in line for kw in skip_keywords):
                continue
            if 'mysterium' in line.lower() or '/myst' in line:
                return True, 'process', f'Process: {line[:60]}'

    try:
        import urllib.request
        urllib.request.urlopen('http://localhost:4449/healthcheck', timeout=2)
        return True, 'api', 'TequilAPI responding on port 4449'
    except Exception:
        pass

    return False, None, None

# ── Install methods ───────────────────────────────────────────────────────────

def install_apt(distro):
    """Native install via apt. On Debian 12/13 (no apt-key), uses direct .deb download."""
    header("APT Install — Debian / Ubuntu / Parrot / Kali")
    c(CYAN, '·', f"Detected: {distro['pretty']}")
    print()
    c(CYAN, '·', "The installer will run automatically. This may take 1-3 minutes.")
    print()
    val = ask("Continue? [Y/n]:", options=['y', 'Y', 'n', 'N', ''], default='y')
    if val.lower() == 'n':
        return False
    print()

    # Check if apt-key is available
    import shutil
    has_apt_key = shutil.which('apt-key') is not None

    if has_apt_key:
        c(CYAN, '→', "Using official Mysterium install script...")
        rc, _ = run(
            "curl -sSf https://raw.githubusercontent.com/mysteriumnetwork/node/master/install.sh | bash",
            timeout=300
        )
        if rc == 0:
            time.sleep(2)
            rc, _ = run(['systemctl', 'is-active', 'mysterium-node'], capture=True)
            if rc == 0:
                c(GREEN, '✓', "Mysterium node installed and running!")
                return True
            run(sudo('systemctl start mysterium-node'))
            time.sleep(3)
            rc, _ = run(['systemctl', 'is-active', 'mysterium-node'], capture=True)
            if rc == 0:
                c(GREEN, '✓', "Service started!")
                return True

    # Debian 12/13: apt-key removed, PPA not supported — use direct .deb
    c(CYAN, '→', "Downloading latest .deb directly from GitHub releases...")
    return _install_deb_direct()


def _install_apt_modern(distro):
    """Stub — redirects to direct .deb install (Debian 12/13 has no working Mysterium PPA)."""
    return _install_deb_direct()


def _install_deb_direct():
    """Download latest .deb directly from GitHub releases — auto-detects architecture."""
    import urllib.request, json, os, tempfile, platform

    # Detect architecture
    machine = platform.machine().lower()
    arch_map = {
        'x86_64': 'amd64',
        'aarch64': 'arm64',
        'arm64': 'arm64',
        'armv7l': 'armhf',
        'armv6l': 'armv6l',
    }
    arch = arch_map.get(machine, 'amd64')
    c(CYAN, '·', f"Architecture: {machine} → {arch}")
    c(CYAN, '·', "Fetching latest release from GitHub...")

    try:
        url = "https://api.github.com/repos/mysteriumnetwork/node/releases/latest"
        req = urllib.request.Request(url, headers={'User-Agent': 'mysterium-toolkit'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())

        version = data.get('tag_name', 'unknown')
        c(CYAN, '·', f"Latest version: {version}")

        # Look for matching .deb — name format: myst_linux_amd64.deb
        deb_url = None
        for asset in data.get('assets', []):
            name = asset['name']
            if name.endswith(f'_{arch}.deb') and 'myst' in name:
                deb_url = asset['browser_download_url']
                c(CYAN, '·', f"Found: {name}")
                break

        if not deb_url:
            c(RED, '✗', f"No .deb found for arch={arch} in release {version}.")
            c(CYAN, '·', f"Check manually: https://github.com/mysteriumnetwork/node/releases")
            return False

        tmp = tempfile.mktemp(suffix='.deb')
        c(CYAN, '·', f"Downloading {deb_url} ...")
        rc, _ = run(f"curl -fsSL '{deb_url}' -o {tmp}", timeout=120)
        if rc != 0:
            c(RED, '✗', "Download failed.")
            return False

        c(CYAN, '·', "Installing .deb...")
        rc, out = run(sudo(f"dpkg -i {tmp}"), timeout=120)
        run(sudo("apt-get install -f -y"), timeout=60)
        os.unlink(tmp)

        run(sudo("myst service --agreed-terms-and-conditions"), timeout=30)
        run(sudo("systemctl enable --now mysterium-node"), timeout=15)
        time.sleep(3)

        rc, _ = run(['systemctl', 'is-active', 'mysterium-node'], capture=True)
        return rc == 0

    except Exception as e:
        c(RED, '✗', f"Direct .deb install failed: {e}")
        return False


def install_apt_manual(distro):
    """Manual apt install step by step."""
    header("Manual APT Install")

    steps = [
        ("Install dependencies", sudo("apt-get install -y curl gnupg")),
        ("Add GPG key", "curl -fsSL https://raw.githubusercontent.com/mysteriumnetwork/node/master/install.sh | sudo bash"),
    ]

    c(CYAN, '·', "Running manual install...")
    rc, _ = run(sudo("apt-get update -qq"), timeout=120)
    rc, _ = run(sudo("apt-get install -y curl"), timeout=60)
    rc, _ = run(
        "curl -sSf https://raw.githubusercontent.com/mysteriumnetwork/node/master/install.sh | sudo bash",
        timeout=300
    )
    if rc == 0:
        c(GREEN, '✓', "Install complete.")
        return True
    c(RED, '✗', "Manual install failed.")
    return False


def install_dnf(distro):
    """Install via DNF (Fedora/RHEL/Rocky/Alma)."""
    header(f"DNF Install — {distro['pretty']}")

    c(CYAN, '·', "Installing via official Mysterium install script...")
    print()
    val = ask("Continue? [Y/n]:", options=['y', 'Y', 'n', 'N', ''], default='y')
    if val.lower() == 'n':
        return False

    rc, _ = run(
        "curl -sSf https://raw.githubusercontent.com/mysteriumnetwork/node/master/install.sh | sudo bash",
        timeout=300
    )
    if rc == 0:
        c(GREEN, '✓', "Install complete.")
        run(sudo("systemctl enable --now mysterium-node"))
        return True

    # Manual RPM fallback
    c(YELLOW, '⚠', "Script failed — trying manual RPM install...")
    latest_url = "https://github.com/mysteriumnetwork/node/releases/latest"
    c(DIM, '·', f"Get the latest .rpm from: {latest_url}")
    rpm_url = ask("Paste the direct .rpm download URL (or press Enter to skip):")
    if rpm_url:
        rc, _ = run(sudo(f"dnf install -y '{rpm_url}'"), timeout=300)
        if rc == 0:
            c(GREEN, '✓', "RPM installed.")
            return True
    c(RED, '✗', "DNF install failed.")
    return False


def install_docker():
    """Install Mysterium node via Docker."""
    header("Docker Install")

    # Check Docker is available
    rc, docker_ver = run(['docker', '--version'], capture=True)
    if rc != 0:
        c(YELLOW, '⚠', "Docker not found. Installing Docker first...")
        install_docker_engine()
        rc, docker_ver = run(['docker', '--version'], capture=True)
        if rc != 0:
            c(RED, '✗', "Docker install failed. Install Docker manually: https://docs.docker.com/engine/install/")
            return False

    c(GREEN, '✓', f"Docker found: {docker_ver}")
    print()

    c(CYAN, '·', "This will create a Docker container named 'myst' with:")
    print(f"    · Port 4449 mapped (TequilAPI)")
    print(f"    · Volume 'myst-data' for persistent storage")
    print(f"    · NET_ADMIN capability (required for WireGuard)")
    print()

    val = ask("Continue? [Y/n]:", options=['y', 'Y', 'n', 'N', ''], default='y')
    if val.lower() == 'n':
        return False

    # Pull image
    c(CYAN, '→', "Pulling Mysterium node image...")
    rc, _ = run("docker pull mysteriumnetwork/myst:latest", timeout=300)
    if rc != 0:
        c(RED, '✗', "Failed to pull Docker image. Check your internet connection.")
        return False
    c(GREEN, '✓', "Image pulled.")

    # Stop existing container if any
    run("docker stop myst 2>/dev/null; docker rm myst 2>/dev/null", timeout=15)

    # Run container
    c(CYAN, '→', "Creating and starting container...")
    cmd = (
        "docker run --cap-add NET_ADMIN -d --name myst --restart=unless-stopped "
        "-p 4449:4449 "
        "-v myst-data:/var/lib/mysterium-node "
        "mysteriumnetwork/myst:latest "
        "service --agreed-terms-and-conditions"
    )
    rc, _ = run(cmd, timeout=60)
    if rc != 0:
        c(RED, '✗', "Failed to start container.")
        return False

    time.sleep(5)
    rc, out = run("docker ps --filter name=myst --format '{{.Status}}'", capture=True)
    if 'Up' in out:
        c(GREEN, '✓', "Container is running!")
        c(CYAN, '·', "TequilAPI available at: http://localhost:4449")
        c(CYAN, '·', "Set password with: docker exec -it myst myst cli --agreed-terms-and-conditions")
        return True
    else:
        c(RED, '✗', "Container not running. Check: docker logs myst")
        return False


def install_docker_engine():
    """Install Docker on Debian/Ubuntu."""
    distro = detect_distro()
    pkg = get_pkg_manager(distro)
    c(CYAN, '→', "Installing Docker Engine...")
    if pkg == 'apt':
        cmds = [
            sudo("apt-get update -qq"),
            sudo("apt-get install -y ca-certificates curl gnupg"),
            "curl -fsSL https://get.docker.com | sudo bash",
        ]
    else:
        cmds = ["curl -fsSL https://get.docker.com | sudo bash"]

    for cmd in cmds:
        run(cmd, timeout=300)
    run(sudo(f"usermod -aG docker {os.environ.get('USER', 'root')}"))


def install_script():
    """Install via official Mysterium install script (universal)."""
    header("Script Install — Official Mysterium Installer")

    c(CYAN, '·', "Uses the official install.sh from mysteriumnetwork/node on GitHub.")
    c(CYAN, '·', "Works on Debian, Ubuntu, Fedora, and most systemd-based distros.")
    print()
    val = ask("Continue? [Y/n]:", options=['y', 'Y', 'n', 'N', ''], default='y')
    if val.lower() == 'n':
        return False

    print()
    c(CYAN, '→', "Running official install script...")
    print()
    rc, _ = run(
        "curl -sSf https://raw.githubusercontent.com/mysteriumnetwork/node/master/install.sh | sudo bash",
        timeout=300
    )
    if rc == 0:
        c(GREEN, '✓', "Install complete.")
        run(sudo("systemctl enable --now mysterium-node"))
        return True
    c(RED, '✗', "Install script failed. Check your internet connection or try Docker install.")
    return False


def install_deb_manual():
    """Manual .deb download and install."""
    header("Manual .deb Install")

    c(CYAN, '·', "Downloads the latest .deb directly from GitHub releases.")
    print()

    # Try to get latest release URL
    latest_deb = None
    try:
        import json
        import urllib.request
        url = "https://api.github.com/repos/mysteriumnetwork/node/releases/latest"
        with urllib.request.urlopen(url, timeout=8) as r:
            data = json.loads(r.read())
        for asset in data.get('assets', []):
            name = asset['name']
            if name.endswith('.deb') and 'amd64' in name and 'myst_' in name:
                latest_deb = asset['browser_download_url']
                c(GREEN, '✓', f"Latest release: {name}")
                break
    except Exception:
        c(YELLOW, '⚠', "Could not auto-detect latest release.")

    if latest_deb:
        val = ask(f"Download and install {latest_deb.split('/')[-1]}? [Y/n]:",
                  options=['y', 'Y', 'n', 'N', ''], default='y')
        if val.lower() == 'n':
            latest_deb = None

    if not latest_deb:
        c(CYAN, '·', "Get .deb from: https://github.com/mysteriumnetwork/node/releases")
        latest_deb = ask("Paste .deb download URL or local file path:")
        if not latest_deb:
            return False

    with tempfile.TemporaryDirectory() as tmp:
        deb_name = latest_deb.split('/')[-1].split('?')[0] or 'myst.deb'
        local_path = Path(tmp) / deb_name

        if latest_deb.startswith('http'):
            c(CYAN, '→', f"Downloading {deb_name}...")
            try:
                urllib.request.urlretrieve(latest_deb, local_path)
                c(GREEN, '✓', "Downloaded.")
            except Exception as e:
                c(RED, '✗', f"Download failed: {e}")
                return False
        else:
            local_path = Path(latest_deb).expanduser().resolve()
            if not local_path.exists():
                c(RED, '✗', f"File not found: {local_path}")
                return False

        c(CYAN, '→', f"Installing {local_path.name}...")
        rc, _ = run(sudo(f"dpkg -i '{local_path}'"), timeout=120)
        if rc != 0:
            c(YELLOW, '⚠', "dpkg had issues — fixing dependencies...")
            run(sudo("apt-get install -f -y"), timeout=120)

        run(sudo("systemctl enable --now mysterium-node"))
        time.sleep(3)
        rc, _ = run(['systemctl', 'is-active', 'mysterium-node'], capture=True)
        if rc == 0:
            c(GREEN, '✓', "Node installed and running!")
            return True
        c(YELLOW, '⚠', "Installed. Check: sudo systemctl status mysterium-node")
        return True


def install_arch():
    """Install on Arch/Manjaro via AUR or manual."""
    header("Arch Linux Install")

    c(CYAN, '·', "Checking for yay/paru AUR helper...")
    has_yay  = shutil.which('yay')  is not None
    has_paru = shutil.which('paru') is not None

    if has_yay or has_paru:
        helper = 'yay' if has_yay else 'paru'
        c(GREEN, '✓', f"Found: {helper}")
        print()
        val = ask(f"Install mysterium-node from AUR via {helper}? [Y/n]:",
                  options=['y', 'Y', 'n', 'N', ''], default='y')
        if val.lower() != 'n':
            rc, _ = run(f"{helper} -S --noconfirm mysterium-node", timeout=300)
            if rc == 0:
                run(sudo("systemctl enable --now mysterium-node"))
                c(GREEN, '✓', "Installed from AUR!")
                return True
    else:
        c(YELLOW, '⚠', "No AUR helper found (yay/paru).")

    c(CYAN, '·', "Falling back to Docker install...")
    return install_docker()


def install_alpine():
    """Install on Alpine Linux."""
    header("Alpine Linux Install")
    c(CYAN, '·', "Mysterium does not provide an Alpine APK package.")
    c(CYAN, '·', "Using Docker install instead (recommended on Alpine).")
    print()
    return install_docker()


# ── Post-install: node password setup ─────────────────────────────────────────
def setup_node_password(is_docker=False):
    """Set node password automatically via myst config set, then restart."""
    header("Set Node Password")

    c(CYAN, '·', "Setting TequilAPI password via myst config set...")
    print()

    password = ask("Choose a TequilAPI password (press Enter to use default 'mystberry'):", default='mystberry')
    if not password:
        password = 'mystberry'

    if is_docker:
        rc, _ = run(
            f"docker exec myst myst config set tequilapi.auth.password '{password}'",
            timeout=15
        )
    else:
        rc, _ = run(
            f"myst config set tequilapi.auth.password '{password}'",
            timeout=15
        )

    if rc == 0:
        c(GREEN, '✓', f"Password set successfully.")
        c(CYAN, '·', "Restarting node to apply password...")
        run(sudo('systemctl restart mysterium-node'), timeout=15)
        time.sleep(3)
        c(GREEN, '✓', "Node restarted with new password.")
    else:
        c(YELLOW, '⚠', "Could not set password automatically.")
        c(CYAN, '·', f"Set it manually: myst config set tequilapi.auth.password YOUR_PASSWORD")
        c(CYAN, '·', f"Then restart: sudo systemctl restart mysterium-node")

    print()
    c(CYAN, '·', f"Remember this password — you need it in the toolkit setup wizard.")
    print()

    return password


def _start_all_services(is_docker=False, password='mystberry'):
    """Start all Mysterium services and make them persistent via myst config set."""
    import urllib.request, json as _json, time as _time

    c(CYAN, '·', "Starting all Mysterium services...")
    print()

    # Wait for TequilAPI to be ready
    for _ in range(10):
        try:
            urllib.request.urlopen('http://localhost:4449/healthcheck', timeout=2)
            break
        except Exception:
            _time.sleep(2)

    # Get identity via TequilAPI
    identity = None
    try:
        # Authenticate first
        auth_data = _json.dumps({"username": "myst", "password": password}).encode()
        req = urllib.request.Request(
            'http://localhost:4449/auth/authenticate',
            data=auth_data,
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            token = _json.loads(resp.read())['token']

        # Get identity
        req2 = urllib.request.Request(
            'http://localhost:4449/identities',
            headers={'Authorization': f'Bearer {token}'}
        )
        with urllib.request.urlopen(req2, timeout=5) as resp2:
            ids = _json.loads(resp2.read())
            if ids.get('identities'):
                identity = ids['identities'][0]['id']
    except Exception as e:
        c(YELLOW, '⚠', f"Could not get identity via API: {e}")

    if not identity:
        c(YELLOW, '⚠', "Could not detect identity — skipping service start.")
        c(CYAN, '·', "Start services manually: myst cli → service start <identity> wireguard")
        return

    c(CYAN, '·', f"Identity: {identity}")

    services = ['wireguard', 'dvpn', 'data_transfer', 'scraping', 'noop', 'monitoring']
    started = []

    for svc in services:
        if is_docker:
            cmd = f"docker exec myst myst cli service start {identity} {svc}"
        else:
            cmd = f"myst cli service start {identity} {svc}"
        rc, out = run(cmd, timeout=15)
        if rc == 0:
            c(GREEN, '✓', f"{svc} started")
            started.append(svc)
        else:
            c(YELLOW, '·', f"{svc} — skipped or already running")

    # Persist active services via config
    if started:
        services_str = ','.join(started)
        run(f"myst config set active-services '{services_str}'", timeout=10)
        c(GREEN, '✓', f"Services persisted: {services_str}")

    print()



def main(args=None):
    import argparse
    parser = argparse.ArgumentParser(description='Mysterium Node Installer')
    parser.add_argument('--install', action='store_true',
                        help='Jump directly to install method selection')
    parser.add_argument('--method', choices=['apt', 'docker', 'script', 'deb'],
                        help='Skip method selection')
    opts = parser.parse_args(args)

    header("Mysterium Node Installer")

    distro = detect_distro()
    pkg    = get_pkg_manager(distro)

    c(CYAN, 'ℹ', f"Detected OS: {distro['pretty']}")
    c(CYAN, 'ℹ', f"Package manager: {pkg}")
    print()

    # Check if already installed
    running, method, detail = detect_node()
    if running:
        c(GREEN, '✓', f"Mysterium node already running ({method})")
        c(DIM,   ' ', detail)
        print()
        val = ask("Node is already installed. Reinstall? [y/N]:",
                  options=['y', 'Y', 'n', 'N', ''], default='n')
        if val.lower() != 'y':
            return True

    # Method selection
    print(f"  {BOLD}Choose installation method:{NC}")
    print()

    options = {}
    num = 1

    # Recommended method per distro
    if pkg == 'apt':
        print(f"  {CYAN}{num}{NC}. {BOLD}APT install{NC} (recommended for {distro['pretty']})")
        print(f"     Adds Mysterium repository and installs via apt")
        options[str(num)] = ('apt', False)
        num += 1
    elif pkg in ('dnf', 'yum'):
        print(f"  {CYAN}{num}{NC}. {BOLD}DNF/YUM install{NC} (recommended for {distro['pretty']})")
        options[str(num)] = ('dnf', False)
        num += 1
    elif pkg == 'pacman':
        print(f"  {CYAN}{num}{NC}. {BOLD}AUR install{NC} (recommended for Arch)")
        options[str(num)] = ('arch', False)
        num += 1
    elif pkg == 'apk':
        print(f"  {CYAN}{num}{NC}. {BOLD}Docker install{NC} (recommended for Alpine)")
        options[str(num)] = ('docker', False)
        num += 1

    print(f"  {CYAN}{num}{NC}. {BOLD}Docker install{NC} — works on any Linux")
    print(f"     Runs node in a container (isolated, easy to update)")
    options[str(num)] = ('docker', True)
    num += 1

    if pkg == 'apt':
        print(f"  {CYAN}{num}{NC}. {BOLD}Manual .deb{NC} — download and install specific version")
        options[str(num)] = ('deb', False)
        num += 1

    print(f"  {CYAN}{num}{NC}. {BOLD}Official script{NC} — curl | bash (universal)")
    options[str(num)] = ('script', False)
    num += 1

    print(f"  {CYAN}0{NC}. Cancel")
    options['0'] = ('cancel', False)
    print()

    if opts.method:
        method_key = opts.method
    else:
        choice = ask(f"Select (0-{num-1}):", options=list(options.keys()))
        method_key, _ = options[choice]

    if method_key == 'cancel':
        c(DIM, '·', "Install cancelled.")
        return False

    # Run chosen installer
    is_docker = False
    if method_key == 'apt':
        success = install_apt(distro)
    elif method_key == 'dnf':
        success = install_dnf(distro)
    elif method_key == 'docker':
        is_docker = True
        success = install_docker()
    elif method_key == 'deb':
        success = install_deb_manual()
    elif method_key == 'script':
        success = install_script()
    elif method_key == 'arch':
        success = install_arch()
    elif method_key == 'alpine':
        success = install_alpine()
    else:
        success = install_script()

    if success:
        print()
        node_password = setup_node_password(is_docker=is_docker)
        print()
        _start_all_services(is_docker=is_docker, password=node_password)
        c(GREEN, '✓', "Node install complete!")
        print()
        c(CYAN, '·', "━" * 55)
        c(CYAN, '·', "IMPORTANT: Complete your node setup in the browser:")
        print()
        c(CYAN, '·', "  1. Open http://YOUR_SERVER_IP:4449/ui")
        c(CYAN, '·', "     (replace YOUR_SERVER_IP with this machine's IP)")
        print()
        c(CYAN, '·', "  2. Log in and accept the Terms & Conditions")
        c(CYAN, '·', "  3. Claim your node on mystnodes.com:")
        c(CYAN, '·', "     Settings → MMN API Key → paste your key")
        c(CYAN, '·', "  4. Set your payout wallet (beneficiary address)")
        print()
        c(CYAN, '·', "━" * 55)
        print()
        c(CYAN, '·', "Then return here and continue the toolkit setup wizard.")
    else:
        print()
        c(RED, '✗', "Node installation failed.")
        c(CYAN, '·', "Manual install docs: https://docs.mysterium.network/node-runners/node-ui/")
        c(CYAN, '·', "Docker install: https://docs.mysterium.network/node-runners/setup/docker/")

    return success


if __name__ == '__main__':
    try:
        result = main()
        sys.exit(0 if result else 1)
    except KeyboardInterrupt:
        print()
        print(f"\n  {YELLOW}⚠ Install cancelled.{NC}")
        sys.exit(1)
