#!/usr/bin/env python3
"""
Mysterium Node Toolkit - Setup Wizard
=====================================
Interactive setup that tests connections and configures everything for you.
"""

import os
import sys
import json
import secrets
import requests
import base64
import subprocess
from pathlib import Path
from typing import Tuple


def detect_docker_myst():
    """Detect if Mysterium node is running in Docker. Returns (found, port, container_name) or (False, None, None)."""
    try:
        result = subprocess.run(
            ['docker', 'ps', '--format', '{{.ID}}\t{{.Image}}\t{{.Ports}}\t{{.Names}}'],
            capture_output=True, timeout=5, text=True
        )
        if result.returncode != 0:
            return False, None, None

        for line in result.stdout.strip().split('\n'):
            if not line.strip():
                continue
            parts = line.split('\t')
            if len(parts) < 4:
                continue
            cid, image, ports, name = parts[0], parts[1], parts[2], parts[3]
            if 'myst' in image.lower() or 'myst' in name.lower():
                # Parse port mapping: "0.0.0.0:4449->4449/tcp" → extract host port
                mapped_port = None
                if ports:
                    for mapping in ports.split(','):
                        mapping = mapping.strip()
                        if '4449' in mapping or '4050' in mapping:
                            # Format: 0.0.0.0:PORT->CONTAINER/tcp
                            if '->' in mapping and ':' in mapping:
                                host_part = mapping.split('->')[0]
                                mapped_port = int(host_part.split(':')[-1])
                                break
                return True, mapped_port, name
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return False, None, None

# Color codes for terminal output
class Colors:
    HEADER = '\033[96m'   # Cyan (matches web dashboard)
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def print_header(text):
    """Print header in a box that fits the terminal"""
    try:
        tw = os.get_terminal_size().columns
    except OSError:
        tw = 80
    box_w = min(tw - 2, max(72, len(text) + 6))
    inner = box_w - 2  # inside the ║ ... ║
    print(f"\n{Colors.BOLD}{Colors.HEADER}╔{'═' * inner}╗{Colors.ENDC}")
    print(f"{Colors.BOLD}{Colors.HEADER}║ {text:<{inner - 2}} ║{Colors.ENDC}")
    print(f"{Colors.BOLD}{Colors.HEADER}╚{'═' * inner}╝{Colors.ENDC}\n")

def print_success(text):
    """Print success message"""
    print(f"{Colors.OKGREEN}✓ {text}{Colors.ENDC}")

def print_error(text):
    """Print error message"""
    print(f"{Colors.FAIL}✗ {text}{Colors.ENDC}")

def print_warning(text):
    """Print warning message"""
    print(f"{Colors.WARNING}⚠ {text}{Colors.ENDC}")

def print_info(text):
    """Print info message"""
    print(f"{Colors.OKCYAN}{text}{Colors.ENDC}")

def input_text(prompt: str, default: str = "") -> str:
    """Get text input from user"""
    if default:
        prompt = f"{prompt} [{default}]: "
    else:
        prompt = f"{prompt}: "

    user_input = input(f"{Colors.OKBLUE}{prompt}{Colors.ENDC}").strip()
    return user_input if user_input else default

def input_choice(prompt: str, options: list) -> str:
    """Get choice from user"""
    print(f"\n{Colors.OKBLUE}{prompt}{Colors.ENDC}")
    for i, option in enumerate(options, 1):
        print(f"  {i}. {option}")

    while True:
        try:
            choice = int(input(f"\n{Colors.OKBLUE}Select (1-{len(options)}): {Colors.ENDC}"))
            if 1 <= choice <= len(options):
                return options[choice - 1]
            print_error(f"Please select a number between 1 and {len(options)}")
        except ValueError:
            print_error("Please enter a valid number")

def input_port(prompt: str, default: str = "4449") -> int:
    """Get and validate a port number"""
    while True:
        try:
            port_input = input_text(prompt, default)
            port = int(port_input)

            if 1 <= port <= 65535:
                return port
            else:
                print_error("Port must be between 1 and 65535")
        except ValueError:
            print_error(f"'{port_input}' is not a valid port number. Enter a number like {default}")
            print_info("(If you pasted your Mystnodes.com API key here, that's NOT what we need!)")
            print()

def test_tequilapi_connection(host: str, port: int, username: str, password: str) -> Tuple[bool, str]:
    """Test connection to TequilAPI and verify credentials.

    Strategy:
    1. POST /auth/authenticate with username+password → get JWT token (proper auth test)
    2. If that works, GET /healthcheck with the token → confirm version
    3. If /auth/authenticate returns 401 → wrong password, say so clearly
    4. /healthcheck alone is NOT a credential test — it may succeed even with wrong password
    """
    base = f"http://{host}:{port}"
    basic_headers = {
        'Authorization': f'Basic {base64.b64encode(f"{username}:{password}".encode()).decode()}'
    }

    try:
        # Step 1: Try JWT auth (newer nodes) — this actually verifies the password
        auth_resp = requests.post(
            f"{base}/auth/authenticate",
            json={"username": username, "password": password},
            headers={"Content-Type": "application/json"},
            timeout=5,
        )

        if auth_resp.status_code == 200:
            token = auth_resp.json().get("token", "")
            bearer = {"Authorization": f"Bearer {token}"} if token else basic_headers
        elif auth_resp.status_code == 401:
            return False, "Authentication failed — password is incorrect"
        else:
            # /auth/authenticate not available on this node version — fall back to Basic
            bearer = basic_headers

        # Step 2: GET /healthcheck to confirm node is running and get version
        hc = requests.get(f"{base}/healthcheck", headers=bearer, timeout=5)
        if hc.status_code == 200:
            version = hc.json().get("version", "unknown")
            return True, f"Connected! Node version: {version}"
        elif hc.status_code == 401:
            return False, "Authentication failed — password is incorrect"
        elif hc.status_code == 404:
            return False, "API endpoint not found — check host and port"
        else:
            return False, f"HTTP {hc.status_code}: {hc.reason}"

    except requests.exceptions.ConnectionError:
        return False, f"Cannot connect to {host}:{port} — node not running or wrong port"
    except requests.exceptions.Timeout:
        return False, "Connection timeout — node is not responding"
    except Exception as e:
        return False, f"Error: {str(e)}"


def setup_wizard():
    """Run the setup wizard (uses loop instead of recursion for retries)"""

    while True:
        result = _run_wizard_steps()
        if result:
            return True
        # If _run_wizard_steps returns False, the user chose to restart


def _run_wizard_steps() -> bool:
    """Execute all wizard steps. Returns True on success, False to restart."""

    print_header("Mysterium Node Toolkit - Setup Wizard")

    # Read setup mode from environment (set by setup.sh)
    import os as _os
    _setup_mode_env = _os.environ.get('TOOLKIT_SETUP_MODE', '1')
    _setup_mode_map = {'1': 'full', '2': 'fleet_master', '3': 'lightweight'}
    _setup_mode = _setup_mode_map.get(_setup_mode_env, 'full')

    print_info("This wizard connects the dashboard to your Mysterium node.")
    print_info("")

    # ============ MODE SELECTION: Easy vs Advanced ============
    mode = input_choice(
        "Setup mode:",
        [
            "Easy  — node on this machine, auto-detect port & auth",
            "Custom — node on another machine, different IP, or advanced settings",
        ]
    )

    if mode.startswith("Easy"):
        return _run_easy_wizard()
    else:
        return _run_advanced_wizard()


def _run_easy_wizard() -> bool:
    """Easy mode — minimal questions. Node must be on localhost."""
    print_header("Easy Setup")
    print_info("Auto-detecting your node configuration...")
    print_info("")

    config = {}

    # Try common ports in order
    node_host = 'localhost'
    found_port = None
    found_version = None

    import base64
    for port in [4449, 4050, 14449, 14050]:
        try:
            import requests as _req
            resp = _req.get(f"http://localhost:{port}/healthcheck", timeout=2)
            if resp.status_code == 200:
                found_port = port
                found_version = resp.json().get('version', 'unknown')
                break
        except Exception:
            pass

    if found_port:
        print_success(f"Node found on port {found_port}  (version {found_version})")
        config['node_host'] = 'localhost'
        config['node_port'] = found_port
    else:
        print_warning("Node not found on localhost. Is it running?")
        print_info("  Check: sudo systemctl status mysterium-node")
        print_info("  Start: sudo systemctl start mysterium-node")
        print_info("")
        retry = input_choice("Try again or switch to Custom mode?",
                             ["Switch to Custom mode", "Exit setup"])
        if retry.startswith("Switch"):
            return _run_advanced_wizard()
        return False

    # Ask just the node password
    print_info("")
    print_info(f"Your node's TequilAPI is on port {found_port}.")
    print_info("Enter the password you set in the Node UI (http://localhost:4449).")
    print_info("If you never set one, try leaving it blank or use 'mystberry'.")
    print_info("")

    password = input_text("Node UI password (press Enter if none)", "")
    username = "myst"

    # Test auth
    success, msg = test_tequilapi_connection(node_host, found_port, username, password)
    if success:
        print_success(msg)
    else:
        print_warning(f"Auth check: {msg}")
        print_info("Continuing anyway — you can update the password later in config/setup.json")

    config['node_username'] = username
    config['node_password'] = password

    # Dashboard authentication — easy mode: API Key or admin + password
    print_info("")
    print_info("=" * 60)
    print_info("DASHBOARD AUTHENTICATION")
    print_info("=" * 60)
    print_info("")
    print_info("How do you want to log in to the dashboard?")
    print_info("")
    print_info("  1. API Key  — paste a secret key in the login screen")
    print_info("               Best for remote / mobile access.")
    print_info("")
    print_info("  2. Admin + Password  — classic username/password login")
    print_info("               Username is always: admin")
    print_info("")

    import secrets as _secrets
    auth_choice = input_choice(
        "Authentication method:",
        [
            "API Key (recommended — copy/paste, no typos)",
            "Admin + Password (username: admin)"
        ]
    )

    if auth_choice.startswith("API Key"):
        api_key_input = input_text(
            "Enter a secret API key (leave blank to auto-generate)", ""
        )
        if not api_key_input:
            api_key_input = _secrets.token_urlsafe(32)

        config['dashboard_api_key']    = api_key_input
        config['dashboard_auth_method'] = 'apikey'

        print_info("")
        print_info("=" * 60)
        print_info("  IMPORTANT — SAVE YOUR API KEY")
        print_info("=" * 60)
        print_info("")
        print_success(f"  API Key: {api_key_input}")
        print_info("")
        print_info("  Login screen: paste this key exactly — do NOT type it.")
        print_info("  Store it in a password manager or secure note now.")
        print_info("  You can find it later in: .env  and  config/setup.json")
        print_info("=" * 60)
        print_info("")
        input("  Press Enter to continue...")

    else:
        dash_pass = input_text("Dashboard password (leave blank to auto-generate)", "")
        if not dash_pass:
            dash_pass = _secrets.token_urlsafe(16)

        config['dashboard_username']   = 'admin'
        config['dashboard_password']   = dash_pass
        config['dashboard_auth_method'] = 'userpass'

        print_info("")
        print_info("=" * 60)
        print_info("  IMPORTANT — SAVE YOUR CREDENTIALS")
        print_info("=" * 60)
        print_info("")
        print_success(f"  Username : admin")
        print_success(f"  Password : {dash_pass}")
        print_info("")
        print_info("  The login screen will ask for these credentials.")
        print_info("  You can find them later in: .env  and  config/setup.json")
        print_info("=" * 60)
        print_info("")
        input("  Press Enter to continue...")

    config['update_interval'] = 10
    config['debug'] = False

    # Port — detect conflict and auto-suggest
    import socket as _sock
    def _port_free(p):
        try:
            s = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
            s.settimeout(1)
            result = s.connect_ex(('127.0.0.1', p))
            s.close()
            return result != 0
        except Exception:
            return True

    default_port = 5000
    if not _port_free(default_port):
        for _p in range(5001, 5020):
            if _port_free(_p):
                default_port = _p
                break
        print_warning(f"Port 5000 is already in use — suggesting port {default_port}")
        print_info("Press Enter to accept or type a different port number:")
        _port_input = input(f"  Dashboard port [{default_port}]: ").strip()
        if _port_input.isdigit():
            default_port = int(_port_input)

    config['dashboard_port'] = default_port

    # Auto-detect system timezone for easy mode
    import subprocess as _sp2, os as _os2
    _sys_tz2 = 'UTC'
    try:
        _sys_tz2 = _sp2.check_output(['timedatectl', 'show', '--property=Timezone', '--value'],
                                      text=True, stderr=_sp2.DEVNULL).strip() or 'UTC'
    except Exception:
        try:
            _sys_tz2 = _os2.readlink('/etc/localtime').split('zoneinfo/')[-1]
        except Exception:
            _sys_tz2 = 'UTC'
    config['timezone'] = _sys_tz2
    print_success(f"Timezone auto-detected: {_sys_tz2} (change in config/setup.json if needed)")

    # Optional wallet address
    print_info("")
    ben = input_text("Your Polygon wallet address (0x...) — optional, press Enter to skip", "")
    if ben and ben.startswith('0x') and len(ben) == 42:
        config['beneficiary_address'] = ben
    else:
        config['beneficiary_address'] = ''

    return _save_config(config)


def _run_advanced_wizard() -> bool:
    """Full advanced wizard — same as original, all options."""
    print_header("Custom Setup")

    print_info("Configure all connection options manually.")
    print_info("")

    config = {}

    # ============ STEP 1: Node Location ============
    print_header("Step 1: Where is your Mysterium Node?")

    node_location = input_choice(
        "Is your node running on:",
        [
            "This computer (localhost)",
            "Another computer on my network (LAN)",
            "A remote server (VPS/Cloud)"
        ]
    )

    if node_location == "This computer (localhost)":
        config['node_host'] = 'localhost'
        print_success("Node host set to: localhost")
    elif node_location == "Another computer on my network (LAN)":
        config['node_host'] = input_text("Enter your node's IP address on your network", "YOUR_NODE_IP")
        print_success(f"Node host set to: {config['node_host']}")
    else:
        config['node_host'] = input_text("Enter your node's IP or domain", "")
        print_success(f"Node host set to: {config['node_host']}")

    # ============ STEP 1b: Docker Detection ============
    docker_detected = False
    docker_port = None
    docker_name = None
    if config['node_host'] in ('localhost', '127.0.0.1', '::1'):
        docker_detected, docker_port, docker_name = detect_docker_myst()
        if docker_detected:
            print()
            print_success(f"Docker container detected: {docker_name}")
            if docker_port:
                print_success(f"  Mapped TequilAPI port: {docker_port}")
                print_info("  We'll use this port automatically.")
            else:
                print_warning("  Container found but port mapping not detected.")
                print_info("  Make sure you exposed port 4449 with: docker run -p 4449:4449 ...")
            config['docker_mode'] = True
            config['docker_container'] = docker_name
            print()

    # ============ STEP 2: Node API Port ============
    print_header("Step 2: TequilAPI Port")

    if docker_detected and docker_port:
        print_info(f"Auto-detected Docker port: {docker_port}")
        use_detected = input_text(f"Use detected port {docker_port}? (y/n)", "y")
        if use_detected.lower() in ('y', 'yes', ''):
            config['node_port'] = docker_port
        else:
            config['node_port'] = input_port("Enter TequilAPI port number", str(docker_port))
    else:
        print_info("Your Mysterium Node exposes an API called TequilAPI on a specific port.")
        if docker_detected:
            print_info("Docker container found — common ports: 4449 (default Docker), 4050 (bare metal)")
        else:
            print_info("Default port is 4449 (Node UI) or 4050 (custom config)")
        print_warning("PORT is a NUMBER, not an API key string!")
        print_info("Examples: 4050, 4449, 14050, 5000")
        print()

        default_port = "4449"  # Mysterium node default is always 4449
        config['node_port'] = input_port("Enter TequilAPI port number", default_port)
    print_success(f"TequilAPI port set to: {config['node_port']}")

    # ============ STEP 3: Node Authentication ============
    print_header("Step 3: TequilAPI Authentication")

    print_info("TequilAPI Authentication — this is your Node UI password.")
    print_info("")
    print_info("Where to find your password:")
    print_info("  Open http://localhost:4449/ui in your browser.")
    print_info("  The password was shown ONCE when you first set up your node.")
    print_info("  It looks like: xK9#mP2$vL7@nQ4w  (random, unique per install)")
    print_info("")
    print_info("  NOT 'mystberry' — that is an old default that newer nodes no longer use.")
    print_info("  If you forgot your password, reset it with:")
    print_info("    sudo myst account --config-dir=/etc/mysterium-node reset-password")
    print_info("")
    print_info("The username is always: myst")

    config['node_username'] = input_text("TequilAPI username", "myst")
    config['node_password'] = input_text("TequilAPI password (your Node UI password)", "")
    if not config['node_password']:
        print_warning("Empty password — connection test may fail. Check your Node UI password.")

    # ============ STEP 4: Test Node Connection ============
    print_header("Step 4: Testing Node Connection")

    print_info(f"Testing connection to {config['node_host']}:{config['node_port']}...\n")

    success, message = test_tequilapi_connection(
        config['node_host'],
        config['node_port'],
        config['node_username'],
        config['node_password']
    )

    if success:
        print_success(message)
    else:
        print_error(message)
        print_warning("Connection failed. Please check:")
        print_warning("  1. Is Mysterium Node running?")
        print_warning("  2. Is the host/port correct?")
        print_warning("  3. Is the username/password correct?")
        print_warning("  4. If on LAN, check firewall allows port 4050")

        retry = input_choice(
            "Try different settings?",
            ["Yes, let me try again", "No, continue anyway"]
        )

        if retry == "Yes, let me try again":
            return False  # Signal to restart

    # ============ STEP 5: Dashboard Server Port ============
    print_header("Step 5: Dashboard API Server Port")

    print_info("The dashboard backend will run on this port on your computer.")
    print_info("Default is 5000. Only change this if port 5000 is already in use.")
    # Always ask fresh — never inherit from previous install to avoid stale ports
    config['dashboard_port'] = input_port("Dashboard API port", "5000")
    print_success(f"Dashboard API port set to: {config['dashboard_port']}")

    # ============ STEP 5.5: Timezone ============
    print_header("Step 5.5: Timezone")

    # Detect system timezone as default
    import subprocess as _sp, os as _os
    _sys_tz = 'UTC'
    try:
        _sys_tz = _sp.check_output(['timedatectl', 'show', '--property=Timezone', '--value'],
                                    text=True, stderr=_sp.DEVNULL).strip() or 'UTC'
    except Exception:
        try:
            _sys_tz = _os.readlink('/etc/localtime').split('zoneinfo/')[-1]
        except Exception:
            _sys_tz = 'UTC'

    print_info("Used for daily/monthly resets — earnings and traffic 'today' tracking.")
    print_info(f"Detected system timezone: {_sys_tz}")
    print_info("Examples: UTC, Europe/Brussels, Europe/Amsterdam, America/New_York")
    print_info("Full list: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones")
    print_info("")

    _tz_input = input(f"  Timezone [{_sys_tz}]: ").strip() or _sys_tz

    # Validate
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(_tz_input)
        config['timezone'] = _tz_input
        print_success(f"Timezone set to: {_tz_input}")
    except Exception:
        print_warning(f"Unknown timezone '{_tz_input}' — falling back to UTC")
        config['timezone'] = 'UTC'

    # ============ STEP 6: Dashboard Authentication ============
    print_header("Step 6: Dashboard API Authentication")

    print_info("These are separate credentials for protecting your dashboard.")
    print_info("Choose how you want to authenticate:")

    auth_method = input_choice(
        "Authentication method:",
        [
            "API Key (Bearer token) - Recommended",
            "Username & Password (Basic auth)",
            "No auth (local network only, NOT RECOMMENDED)"
        ]
    )

    if "API Key" in auth_method:
        api_key_val = input_text(
            "Create a secret API key (leave blank to auto-generate)", ""
        )
        if not api_key_val:
            api_key_val = secrets.token_urlsafe(32)
        config['dashboard_api_key']     = api_key_val
        config['dashboard_auth_method'] = 'apikey'

        print_info("")
        print_info("=" * 60)
        print_info("  IMPORTANT — SAVE YOUR API KEY")
        print_info("=" * 60)
        print_info("")
        print_success(f"  API Key : {api_key_val}")
        print_info("")
        print_info("  COPY/PASTE this key in the login screen — never type it.")
        print_info("  Typing causes typos (i vs l, 5 vs 2, 0 vs O, etc).")
        print_info("  Store it in a password manager or secure note now.")
        print_info("  Find it later in: .env  and  config/setup.json")
        print_info("=" * 60)
        print_info("")
        input("  Press Enter to continue...")

    elif "Username" in auth_method:
        config['dashboard_username'] = input_text("Dashboard username", "admin")
        config['dashboard_password'] = input_text("Dashboard password (choose a strong one!)", "")
        if not config['dashboard_password']:
            print_warning("Empty password is insecure! Consider re-running setup.")
        config['dashboard_auth_method'] = 'userpass'

        print_info("")
        print_info("=" * 60)
        print_info("  IMPORTANT — SAVE YOUR CREDENTIALS")
        print_info("=" * 60)
        print_info("")
        print_success(f"  Username : {config['dashboard_username']}")
        print_success(f"  Password : {config['dashboard_password']}")
        print_info("")
        print_info("  The login screen asks for these credentials.")
        print_info("  Find them later in: .env  and  config/setup.json")
        print_info("=" * 60)
        print_info("")
        input("  Press Enter to continue...")

    else:
        print_warning("No authentication enabled - only accessible from localhost!")
        config['dashboard_allow_no_auth'] = 'true'
        config['dashboard_auth_method'] = 'noauth'

    # Set defaults — interval is managed by backend tiered caching
    config['update_interval'] = 10

    # Debug mode
    debug_choice = input_choice(
        "Enable debug mode? (verbose logging for troubleshooting)",
        ["No (production — minimal logging)", "Yes (development — detailed logs)"]
    )
    config['debug'] = debug_choice.startswith("Yes")

    # ============ STEP 7: Review & Save ============
    print_header("Step 7: Review Configuration")

    print("Your configuration:\n")
    print(f"  {Colors.BOLD}Node Connection:{Colors.ENDC}")
    print(f"    Host:     {config['node_host']}")
    print(f"    Port:     {config['node_port']}")
    print(f"    Username: {config['node_username']}")
    print(f"    Password: {'*' * len(config['node_password'])}")

    print(f"\n  {Colors.BOLD}Dashboard API:{Colors.ENDC}")
    print(f"    Port:     {config['dashboard_port']}")
    if config.get('dashboard_auth_method') == 'apikey':
        print(f"    Auth:     API Key")
    elif config.get('dashboard_auth_method') == 'userpass':
        print(f"    Auth:     {config['dashboard_username']}:{'*' * len(config.get('dashboard_password', ''))}")
    else:
        print(f"    Auth:     None (local only)")

    confirm = input_choice(
        "\nSave this configuration?",
        ["Yes, save", "No, start over"]
    )

    if confirm == "No, start over":
        return False  # Signal to restart

    return _save_config(config)


def _save_config(config: dict) -> bool:
    """Save .env and config/setup.json. Shared by easy and advanced wizard."""
    import os as _os
    _setup_mode_env = _os.environ.get('TOOLKIT_SETUP_MODE', '1')
    _setup_mode_map = {'1': 'full', '2': 'fleet_master', '3': 'lightweight'}
    if 'setup_mode' not in config:
        config['setup_mode'] = _setup_mode_map.get(_setup_mode_env, 'full')
    print_header("Saving Configuration")

    Path('config').mkdir(parents=True, exist_ok=True)
    Path('logs').mkdir(parents=True, exist_ok=True)

    # Create .env file
    env_content = f"""# Mysterium Node API Configuration
# NOTE: URL has no /api suffix - TequilAPI endpoints are at root (e.g. /healthcheck)
MYSTERIUM_NODE_API=http://{config['node_host']}:{config['node_port']}
MYSTERIUM_NODE_USERNAME={config['node_username']}
MYSTERIUM_NODE_PASSWORD={config['node_password']}

# Dashboard API Server
DASHBOARD_PORT={config['dashboard_port']}

# Dashboard Authentication
"""

    if config.get('dashboard_auth_method') == 'apikey':
        env_content += f"DASHBOARD_API_KEY={config['dashboard_api_key']}\n"
    elif config.get('dashboard_auth_method') == 'userpass':
        env_content += f"DASHBOARD_USERNAME={config['dashboard_username']}\nDASHBOARD_PASSWORD={config['dashboard_password']}\n"
    else:
        env_content += "ALLOW_NO_AUTH=true\n"

    env_content += f"""
# Monitoring Configuration
DEBUG={'true' if config.get('debug') else 'false'}
LOG_LEVEL={config.get('log_level', 'INFO')}
"""

    Path('.env').write_text(env_content)
    print_success(".env file created")

    # Wallet address (skip interactive prompt if already in config from easy mode)
    if 'beneficiary_address' not in config:
        print()
        print_header("On-Chain Wallet Address (optional)")
        print_info("Polygon wallet where settled MYST lands. Leave blank to skip.")
        print_info("Dashboard will auto-detect it from your settlement history.")
        print()
        ben_addr = input("  Beneficiary wallet address (0x...): ").strip()
        if ben_addr and ben_addr.startswith('0x') and len(ben_addr) == 42:
            config['beneficiary_address'] = ben_addr
            print_success(f"Saved: {ben_addr[:8]}...{ben_addr[-6:]}")
        else:
            config['beneficiary_address'] = ''
            if ben_addr:
                print_warning("Invalid format — skipped.")

    # Log level
    if 'log_level' not in config:
        print()
        print_header("Log Level")
        print_info("Controls how much detail is written to logs/backend.log")
        print_info("  1. Normal  — INFO level (recommended)")
        print_info("  2. Minimal — WARNING and above only (less disk usage)")
        print_info("  3. Verbose — DEBUG level (very detailed, for troubleshooting)")
        log_choice = input("  Select (1-3) [default: 1]: ").strip() or '1'
        level_map = {'1': 'INFO', '2': 'WARNING', '3': 'DEBUG'}
        config['log_level'] = level_map.get(log_choice, 'INFO')
        print_success(f"Log level: {config['log_level']}")

    # Polygonscan API key (skip if already in config)
    if 'polygonscan_api_key' not in config:
        print()
        print_header("Polygonscan API Key (optional)")
        print_info("Used to show your on-chain MYST balance. Without it: once/hour refresh.")
        print_info("Get a free key at https://etherscan.io → My Account → API Keys")
        print()
        poly_key = input("  API key (or press Enter to skip): ").strip()
        if poly_key and len(poly_key) >= 20:
            config['polygonscan_api_key'] = poly_key
            print_success("API key saved.")
        else:
            config['polygonscan_api_key'] = ''

    # MYST price — no setup needed, just inform the user
    print()
    print_header("MYST Token Price")
    print_info("Live MYST/EUR and MYST/USD prices are shown in the Earnings card.")
    print_info("Source: CoinPaprika (USD) + Frankfurter ECB rates (EUR) — both free, no account, no API key.")
    print_info("Price is fetched automatically and cached every 5 minutes.")

    # Build and write setup.json
    node_is_local = config['node_host'] in ('localhost', '127.0.0.1', '::1')
    config_json = {
        'node_host':             config['node_host'],
        'node_port':             config['node_port'],
        'dashboard_port':        config['dashboard_port'],
        'dashboard_auth_method': config.get('dashboard_auth_method', 'userpass'),
        'toolkit_mode':          'local' if node_is_local else 'remote',
    }

    if config.get('beneficiary_address'):
        config_json['beneficiary_address'] = config['beneficiary_address']
    if config.get('polygonscan_api_key'):
        config_json['polygonscan_api_key'] = config['polygonscan_api_key']
    if config.get('dashboard_auth_method') == 'apikey':
        config_json['dashboard_api_key'] = config.get('dashboard_api_key')
    # Save setup mode so backend knows if it's lightweight (Type 3)
    if config.get('setup_mode'):
        config_json['setup_mode'] = config['setup_mode']
    # Save timezone
    config_json['timezone'] = config.get('timezone', 'UTC')

    # Data retention defaults — written so users can edit them directly in setup.json
    # All values are in days. Edit and restart the backend to apply changes.
    config_json['data_retention'] = {
        'earnings': 365,
        'sessions': 90,
        'traffic':  730,
        'quality':  90,
        'system':   30,
        'services': 30,
        'uptime':   90,
    }

    Path('config/setup.json').write_text(json.dumps(config_json, indent=2))
    print_success("config/setup.json created")

    # Summary
    print_header("Setup Complete!")

    if config.get('dashboard_auth_method') == 'apikey':
        print()
        print(f"{Colors.WARNING}{'='*60}{Colors.ENDC}")
        print(f"{Colors.WARNING}  IMPORTANT — SAVE YOUR API KEY NOW{Colors.ENDC}")
        print(f"{Colors.WARNING}{'='*60}{Colors.ENDC}")
        print(f"\n  {config.get('dashboard_api_key', '')}\n")
        print(f"{Colors.WARNING}  You will need this key to log into the dashboard.{Colors.ENDC}")
        print(f"{Colors.WARNING}  It is stored in config/setup.json — keep that file safe.{Colors.ENDC}")
        print()
        input(f"{Colors.OKBLUE}  → Press Enter once you have saved the API key...{Colors.ENDC}")
        print()
    elif config.get('dashboard_auth_method') == 'userpass':
        print()
        print(f"{Colors.WARNING}{'='*60}{Colors.ENDC}")
        print(f"{Colors.WARNING}  IMPORTANT — SAVE YOUR LOGIN CREDENTIALS{Colors.ENDC}")
        print(f"{Colors.WARNING}{'='*60}{Colors.ENDC}")
        print(f"\n  Username: {config.get('dashboard_username', 'admin')}")
        print(f"  Password: {config.get('dashboard_password', '')}")
        print()
        print(f"{Colors.WARNING}  You will need these to log into the dashboard.{Colors.ENDC}")
        print(f"{Colors.WARNING}  They are stored in config/setup.json — keep that file safe.{Colors.ENDC}")
        print()
        input(f"{Colors.OKBLUE}  → Press Enter once you have saved your credentials...{Colors.ENDC}")
        print()

    if config.get('polygonscan_api_key'):
        print(f"{Colors.OKGREEN}Polygonscan API key saved to config/setup.json{Colors.ENDC}")
    else:
        print(f"{Colors.WARNING}No Polygonscan API key — wallet balance refreshes once per hour.{Colors.ENDC}")
        print(f"  Get a free key at https://etherscan.io and add it to config/setup.json")
        print(f"  as \"polygonscan_api_key\": \"your_key_here\"\n")

    print(f"{Colors.OKBLUE}Configuration saved!{Colors.ENDC}")
    print()
    # Detect own IP for access URL
    import socket
    dashboard_port = config.get('dashboard_port', 5000)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        own_ip = s.getsockname()[0]
        s.close()
    except Exception:
        own_ip = 'localhost'

    input(f"{Colors.OKBLUE}  → Press Enter to continue to the dashboard menu...{Colors.ENDC}")
    print()
    print("Next steps:")
    print(f"  Start the dashboard:  ./start.sh")
    print(f"  Access locally:       http://localhost:{dashboard_port}")
    print(f"  Access from network:  http://{own_ip}:{dashboard_port}")
    print()
    print("  Or manually:")
    print("    source venv/bin/activate && python backend/app.py")

    return True


if __name__ == "__main__":
    try:
        setup_wizard()
        sys.exit(0)
    except KeyboardInterrupt:
        print_error("\nSetup cancelled")
        sys.exit(1)
    except Exception as e:
        print_error(f"Setup failed: {e}")
        sys.exit(1)
