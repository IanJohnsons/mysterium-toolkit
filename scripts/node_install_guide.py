#!/usr/bin/env python3
"""
Mysterium Node Installation Guide
==================================
Detects whether a Mysterium node is running.
If not, walks the user through installation step-by-step.

Supports:
  - Native install (Debian/Ubuntu/Parrot)
  - Docker install
  - Manual / other distros

Author: Ian Johnsons
License: CC BY-NC-SA 4.0
"""

import subprocess
import sys
import os
import shutil
import time

# ============ COLORS ============
GREEN = '\033[0;32m'
YELLOW = '\033[1;33m'
RED = '\033[0;31m'
CYAN = '\033[96m'
BOLD = '\033[1m'
DIM = '\033[2m'
NC = '\033[0m'


def cprint(color, icon, msg):
    print(f"  {color}{icon}{NC} {msg}")


def header(title):
    w = len(title) + 8
    print(f"\n  {CYAN}{'═' * w}{NC}")
    print(f"  {CYAN}║{NC}   {BOLD}{title}{NC}   {CYAN}║{NC}")
    print(f"  {CYAN}{'═' * w}{NC}\n")


def run(cmd, timeout=10):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return -1, ''


def detect_node():
    """Detect if Mysterium node is running. Returns (running, method, details)."""

    # Check 1: systemd service
    rc, out = run(['systemctl', 'is-active', 'mysterium-node'])
    if rc == 0 and 'active' in out:
        return True, 'systemd', 'mysterium-node service is active'

    # Check 2: Docker container
    rc, out = run(['docker', 'ps', '--filter', 'name=myst', '--format', '{{.Names}}'])
    if rc == 0 and out:
        return True, 'docker', f'Docker container: {out.splitlines()[0]}'

    # Check 3: Process check — exclude toolkit/installer processes (false positive)
    rc, out = run(['pgrep', '-af', 'myst'])
    if rc == 0 and out:
        for line in out.splitlines():
            # Skip toolkit processes — they contain 'mysterium' in path but are NOT the node
            skip_keywords = ['mysterium-toolkit', 'setup.sh', 'start.sh', 'setup_wizard',
                             'node_install', 'node_installer', 'dashboard.py', 'app.py']
            if any(kw in line for kw in skip_keywords):
                continue
            if 'mysterium' in line.lower() or '/myst' in line:
                return True, 'process', f'Process found: {line[:60]}'

    # Check 4: TequilAPI reachable
    try:
        import requests
        resp = requests.get('http://localhost:4449/healthcheck', timeout=3)
        if resp.status_code == 200:
            return True, 'tequilapi', 'TequilAPI responding on port 4449'
    except Exception:
        pass

    return False, None, None


def detect_distro():
    """Detect Linux distribution."""
    try:
        with open('/etc/os-release') as f:
            data = {}
            for line in f:
                if '=' in line:
                    k, v = line.strip().split('=', 1)
                    data[k] = v.strip('"')
            return data.get('ID', 'unknown'), data.get('ID_LIKE', ''), data.get('PRETTY_NAME', 'Linux')
    except FileNotFoundError:
        return 'unknown', '', 'Linux'


def is_debian_like(distro_id, id_like):
    return distro_id in ('debian', 'ubuntu', 'parrot', 'linuxmint', 'pop', 'elementary', 'kali') or \
           'debian' in id_like or 'ubuntu' in id_like


def guide_native_debian():
    """Step-by-step native install for Debian/Ubuntu/Parrot."""
    header("Native Install — Debian/Ubuntu/Parrot")

    steps = [
        {
            'title': 'Step 1: Add Mysterium Repository',
            'desc': 'Add the official Mysterium apt repository to your system.',
            'commands': [
                'sudo add-apt-repository ppa:mysteriumnetwork/node || true',
                'curl -sSf https://raw.githubusercontent.com/mysteriumnetwork/node/master/install.sh | sudo bash',
            ],
            'note': 'The install script auto-adds the repository and installs the node.',
        },
        {
            'title': 'Step 2: Verify Installation',
            'desc': 'Check that the Mysterium node service is running.',
            'commands': [
                'sudo systemctl status mysterium-node',
            ],
            'note': 'You should see "active (running)" in green.',
        },
        {
            'title': 'Step 3: Set Node Password',
            'desc': 'Set the TequilAPI password for your node.',
            'commands': [
                'myst cli --agreed-terms-and-conditions',
            ],
            'note': 'Inside the CLI, use: password set <your-password>',
        },
        {
            'title': 'Step 4: Claim Your Node',
            'desc': 'Register at mystnodes.network and claim your node.',
            'commands': [],
            'note': None,
        },
    ]

    for step in steps:
        print(f"  {BOLD}{CYAN}{step['title']}{NC}")
        print(f"  {DIM}{step['desc']}{NC}")
        print()
        for cmd in step['commands']:
            print(f"    {GREEN}${NC} {BOLD}{cmd}{NC}")
        if step['note']:
            print(f"\n  {YELLOW}ℹ {step['note']}{NC}")
        print()
        input(f"  {DIM}Press Enter when ready for next step...{NC}")
        print()

    _show_registration_info()


def guide_docker():
    """Step-by-step Docker install."""
    header("Docker Install")

    print(f"  {BOLD}{CYAN}Step 1: Pull Mysterium Node Image{NC}")
    print()
    print(f"    {GREEN}${NC} {BOLD}docker pull mysteriumnetwork/myst:latest{NC}")
    print()
    input(f"  {DIM}Press Enter when ready...{NC}")
    print()

    print(f"  {BOLD}{CYAN}Step 2: Run the Container{NC}")
    print(f"  {DIM}Choose a data directory for persistent storage.{NC}")
    print()
    print(f"    {GREEN}${NC} {BOLD}docker run --cap-add NET_ADMIN \\")
    print(f"        -d --name myst \\")
    print(f"        -p 4449:4449 \\")
    print(f"        -v myst-data:/var/lib/mysterium-node \\")
    print(f"        mysteriumnetwork/myst:latest \\")
    print(f"        service --agreed-terms-and-conditions{NC}")
    print()
    print(f"  {YELLOW}ℹ NET_ADMIN capability is required for WireGuard tunnels.{NC}")
    print(f"  {YELLOW}  Port 4449 is the TequilAPI management port.{NC}")
    print()
    input(f"  {DIM}Press Enter when ready...{NC}")
    print()

    print(f"  {BOLD}{CYAN}Step 3: Verify Container{NC}")
    print()
    print(f"    {GREEN}${NC} {BOLD}docker ps --filter name=myst{NC}")
    print(f"    {GREEN}${NC} {BOLD}docker logs myst --tail 20{NC}")
    print()
    print(f"  {YELLOW}ℹ Container should show status 'Up' with port 4449 mapped.{NC}")
    print()
    input(f"  {DIM}Press Enter when ready...{NC}")
    print()

    print(f"  {BOLD}{CYAN}Step 4: Set Password{NC}")
    print()
    print(f"    {GREEN}${NC} {BOLD}docker exec -it myst myst cli --agreed-terms-and-conditions{NC}")
    print(f"  {DIM}Inside the CLI, use: password set <your-password>{NC}")
    print()
    input(f"  {DIM}Press Enter when ready...{NC}")
    print()

    _show_registration_info()


def _show_registration_info():
    """Show mystnodes registration steps."""
    header("Register Your Node")

    print(f"  {BOLD}{CYAN}Step A: Create Account{NC}")
    print()
    print(f"    Go to: {BOLD}https://mystnodes.com{NC}")
    print()
    print(f"    {YELLOW}{BOLD}⚠ IMPORTANT: Use email + password to register.{NC}")
    print(f"    {YELLOW}  Do NOT use Google login. Email+password lets you{NC}")
    print(f"    {YELLOW}  change your password later and recover your account.{NC}")
    print()
    input(f"  {DIM}Press Enter when ready...{NC}")
    print()

    print(f"  {BOLD}{CYAN}Step B: Claim Your Node{NC}")
    print()
    print(f"  Open the Node UI in your browser:")
    print(f"    {BOLD}http://localhost:4449{NC}")
    print()
    print(f"  Follow the on-screen instructions to:")
    print(f"    1. Set your node password (if not already done)")
    print(f"    2. Claim the node to your mystnodes.com account")
    print(f"    3. Wait for the node to appear in your dashboard")
    print()
    print(f"  {GREEN}✓ Once claimed, your node will start earning MYST!{NC}")
    print()
    input(f"  {DIM}Press Enter to continue to toolkit setup...{NC}")


def main():
    header("Mysterium Node Detection")

    running, method, details = detect_node()

    if running:
        cprint(GREEN, '✓', f'Mysterium node detected ({method})')
        if details:
            cprint(DIM, ' ', details)
        print()
        return True

    cprint(RED, '✗', 'No Mysterium node detected on this system.')
    print()
    print(f"  {BOLD}The toolkit needs a running Mysterium node to monitor.{NC}")
    print(f"  {DIM}Would you like help installing one?{NC}")
    print()

    distro_id, id_like, pretty_name = detect_distro()
    cprint(CYAN, 'ℹ', f'Detected OS: {pretty_name}')
    print()

    print(f"  {BOLD}Installation Options:{NC}")
    print()
    if is_debian_like(distro_id, id_like):
        print(f"    1. {BOLD}Native install{NC} (recommended for {pretty_name})")
    else:
        print(f"    1. {BOLD}Native install{NC} (for Debian/Ubuntu — may need adaptation)")
    print(f"    2. {BOLD}Docker install{NC} (works on any Linux)")
    print(f"    3. {BOLD}Skip{NC} — I'll install the node myself")
    print()

    choice = input(f"  Select (1-3): ").strip()

    if choice in ('1', '2'):
        # Launch the real automatic installer
        import os
        installer = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'node_installer.py')
        if os.path.exists(installer):
            method_arg = ['--method', 'apt'] if choice == '1' else ['--method', 'docker']
            try:
                import importlib.util
                spec = importlib.util.spec_from_file_location('node_installer', installer)
                mod  = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                result = mod.main(['--install'] + method_arg)
                return bool(result)
            except Exception as e:
                cprint(RED, '✗', f'Installer error: {e}')
                return False
        else:
            cprint(RED, '✗', 'node_installer.py not found.')
            return False
    elif choice == '3':
        print()
        cprint(YELLOW, '⚠', 'Skipping node install.')
        cprint(DIM, ' ', 'Install a Mysterium node, then run the toolkit again.')
        cprint(DIM, ' ', 'Docs: https://docs.mysterium.network/node-runners/')
        print()
        return False
    else:
        cprint(RED, '✗', 'Invalid choice.')
        return False


if __name__ == '__main__':
    result = main()
    sys.exit(0 if result else 1)
