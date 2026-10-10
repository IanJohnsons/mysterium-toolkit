"""Privileged actions through the toolkit helper (v1.4.60, sole route since v1.4.64).

Every change the toolkit makes as root goes through
/usr/local/lib/mysterium-toolkit/toolkit-helper, a root-owned copy of
bin/toolkit-helper.sh with a closed list of actions. See that script for why.

v1.4.60 added the helper and kept the old sudoers grants as a fallback, with a
warning whenever it was used. v1.4.64 removed those grants and the fallback:
when the helper is missing, not allowed by sudo, or refuses an action, the
action fails and the log says why — once per action and reason.

run() returns (returncode, stdout, stderr), the shape the callers already use.
"""
import logging
import os
import subprocess

HELPER = '/usr/local/lib/mysterium-toolkit/toolkit-helper'
EX_REFUSED = 64

logger = logging.getLogger('mysterium.privileged')
_noted = set()


def helper_available():
    return os.path.isfile(HELPER) and os.access(HELPER, os.X_OK)


def _exec(cmd, input_data=None, timeout=30):
    try:
        r = subprocess.run(cmd, input=input_data, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or '').strip(), (r.stderr or '').strip()
    except FileNotFoundError:
        return -1, '', f'{cmd[0]} not found'
    except subprocess.TimeoutExpired:
        return -2, '', 'timeout'
    except Exception as e:
        return -3, '', str(e)


def _sudo_refused(rc, err):
    e = (err or '').lower()
    return rc == 1 and ('password is required' in e or 'not allowed to execute' in e
                        or 'may not run sudo' in e or 'a terminal is required' in e)


def _note(action, reason):
    """Warn once per action and reason — the conntrack fix runs every cycle."""
    key = (action, reason[:60])
    if key in _noted:
        return
    _noted.add(key)
    logger.warning(f"privileged: '{action}' failed — {reason}")


def run(action, *args, timeout=30):
    """Run one helper action. A helper that ran the action is returned as is,
    whatever its result; a helper that could not run says why in stderr."""
    argv = [str(a) for a in args]
    if not helper_available():
        reason = 'helper not installed — run ./update.sh'
        _note(action, reason)
        return 1, '', reason
    cmd = ([HELPER] if os.geteuid() == 0 else ['sudo', '-n', HELPER]) + [action] + argv
    rc, out, err = _exec(cmd, timeout=timeout)
    if rc == EX_REFUSED:
        _note(action, f'refused: {err[:120]}')
    elif _sudo_refused(rc, err):
        reason = 'sudo does not allow the helper — run ./update.sh'
        _note(action, reason)
        return rc, out, reason
    return rc, out, err


# Read-only commands that need root. A command list that starts with ROOT is
# run through the helper's read actions; any other list runs as it is. v1.4.64:
# these reads used their own sudoers grants — iptables, ufw, nft, wg and
# fail2ban-client without any argument restriction, which was root in itself
# (fail2ban-client can set an action, `wg show*` matched `wg showconf`).
ROOT = '@root'
_IPT_BINS = {'iptables', 'iptables-legacy', 'iptables-nft', 'ip6tables', 'ip6tables-legacy'}
_IPT_LIST = {'-L', '--list', '-S', '--list-rules'}
_IPT_WRITE = {'-A', '-I', '-D', '-R', '-F', '-Z', '-N', '-X', '-P', '-E', '--append', '--insert',
              '--delete', '--replace', '--flush', '--zero', '--new-chain', '--delete-chain',
              '--policy', '--rename-chain'}


def read(argv, timeout=10):
    """One read-only root command through the helper. Returns (rc, out, err)."""
    a = [str(x) for x in argv]
    if not a:
        return 1, '', 'empty command'
    name = os.path.basename(a[0])
    if name in _IPT_BINS:
        # The helper's ipt action also changes tables; a read must only list.
        if not (_IPT_LIST & set(a[1:])) or (_IPT_WRITE & set(a[1:])):
            return 1, '', 'not a listing: ' + ' '.join(a)
        return run('ipt', name, *a[1:], timeout=timeout)
    if name == 'ufw' and a[1:2] == ['status']:
        return run('ufw-status', *a[2:], timeout=timeout)
    if name == 'nft' and a[1:] == ['list', 'ruleset']:
        return run('nft-list', timeout=timeout)
    if name == 'wg' and a[1:] == ['show', 'all', 'latest-handshakes']:
        return run('wg-handshakes', timeout=timeout)
    if name == 'fail2ban-client':
        return run('f2b-read', *a[1:], timeout=timeout)
    return 1, '', f'no root read defined for {name}'


def run_read(cmd, timeout=5, **_ignored):
    """subprocess.run() for a command list that may start with ROOT. Returns a
    CompletedProcess, so call sites keep reading .returncode and .stdout."""
    cmd = list(cmd)
    if cmd and cmd[0] == ROOT:
        rc, out, err = read(cmd[1:], timeout=timeout)
        return subprocess.CompletedProcess(cmd, rc, out, err)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def ok(action, *args, **kw):
    """run() reduced to success/failure."""
    return run(action, *args, **kw)[0] == 0


def firewall(argv, timeout=10):
    """Route a ufw / iptables command line through the helper.

    argv is the command as the caller built it (['ufw', ...] or
    ['iptables-legacy', ...]); the helper validates the arguments itself."""
    argv = [str(a) for a in argv]
    if not argv:
        return 1, '', 'empty command'
    if argv[0] == 'ufw':
        return run('ufw', *argv[1:], timeout=timeout)
    return run('ipt', *argv, timeout=timeout)
