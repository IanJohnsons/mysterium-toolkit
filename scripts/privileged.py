"""Privileged actions through the toolkit helper (v1.4.60).

Every change the toolkit makes as root goes through
/usr/local/lib/mysterium-toolkit/toolkit-helper, a root-owned copy of
bin/toolkit-helper.sh with a closed list of actions. See that script for why.

v1.4.60 is the first of two steps. The helper is installed and used, and the
old sudoers grants are still in place: when the helper is not installed yet,
or sudo does not allow it yet, or it refuses an action, the caller's previous
command runs instead (`legacy`) and a warning names the action. That warning is
how a missing action shows up on a test machine before v1.4.61 removes the old
grants and the fallback with them.

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
    logger.warning(f"privileged: '{action}' did not go through the helper ({reason}) — "
                   f"used the previous sudo command instead")


def run(action, *args, legacy=(), input_data=None, timeout=30):
    """Run one helper action; fall back to the legacy commands (tried in order),
    or to a legacy callable returning (rc, out, err), only when the helper did not
    handle it. A helper that ran the action and got
    a non-zero result is returned as is — running the legacy command after it
    would do the same thing twice."""
    argv = [str(a) for a in args]
    rc, out, err = 1, '', ''
    if helper_available():
        cmd = ([HELPER] if os.geteuid() == 0 else ['sudo', '-n', HELPER]) + [action] + argv
        rc, out, err = _exec(cmd, timeout=timeout)
        if rc == EX_REFUSED:
            reason = f'refused: {err[:120]}'
        elif _sudo_refused(rc, err):
            reason = 'sudo does not allow the helper yet — run ./update.sh'
        else:
            return rc, out, err
    else:
        reason = 'helper not installed — run ./update.sh'
    if not legacy:
        return rc, out, err or reason
    _note(action, reason)
    if callable(legacy):
        # A step that took several commands before the helper existed.
        try:
            return legacy()
        except Exception as e:
            return -3, '', str(e)
    last = (1, '', reason)
    for c in legacy:
        last = _exec(list(c), input_data=input_data, timeout=timeout)
        if last[0] == 0:
            return last
    return last


def ok(action, *args, **kw):
    """run() reduced to success/failure."""
    return run(action, *args, **kw)[0] == 0


def firewall(argv, legacy=(), timeout=10):
    """Route a ufw / iptables command line through the helper.

    argv is the command as the caller built it (['ufw', ...] or
    ['iptables-legacy', ...]); the helper validates the arguments itself."""
    argv = [str(a) for a in argv]
    if not argv:
        return 1, '', 'empty command'
    if argv[0] == 'ufw':
        return run('ufw', *argv[1:], legacy=legacy, timeout=timeout)
    return run('ipt', *argv, legacy=legacy, timeout=timeout)
