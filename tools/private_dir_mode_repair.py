#!/usr/bin/env python3
"""Repair exactly one MiniFish directory mode in a known Codespace.

No recursive changes, no network, no process changes, no Runtime POST,
no reading or emitting private file contents. Default is read-only.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys

EXPECTED_CODESPACE = 'accursed-apparition-6q7jwqq5965h4rpq'
KNOWN_ROLES = {
    'owner_api': 'cloud_api:app',
    'bridge': 'bridge_worker.py',
    'updater': 'codespace_self_update.py',
    'desktop': 'start_g1b_mock.sh',
    'controller': 'g1b_mock_app:app',
}
O_DIRECTORY = getattr(os, 'O_DIRECTORY', 0)
O_NOFOLLOW = getattr(os, 'O_NOFOLLOW', 0)
CLOSE_ON_EXEC = getattr(os, 'O_CLOEXEC', 0)
DIR_FLAGS = os.O_RDONLY | O_DIRECTORY | O_NOFOLLOW | CLOSE_ON_EXEC


def label(fstat_result: os.stat_result) -> dict[str, object]:
    return {
        'type': 'DIR' if stat.S_ISDIR(fstat_result.st_mode) else 'OTHER',
        'mode': format(stat.S_IMODE(fstat_result.st_mode), '04o'),
        'owner_is_current': fstat_result.st_uid == os.geteuid(),
    }


def known_role(args: list[bytes]) -> str | None:
    """Classify only explicit executable arguments, not arbitrary substrings."""
    decoded = [s.decode('utf-8', 'replace') for s in args if s]
    for role, name in KNOWN_ROLES.items():
        if name in decoded or any(x.endswith('/' + name) for x in decoded):
            return role
    return None


def check_process_owners(proc: Path = Path('/proc')) -> dict[str, object]:
    roles = set()
    other_owner = set()
    unreadable = 0
    try:
        items = list(proc.iterdir())
    except OSError:
        return {'state': 'PROC_UNAVAILABLE', 'roles': [], 'different_owner_roles': [],
                'unreadable_processes': None}
    for item in items:
        if not item.name.isdigit():
            continue
        try:
            args = (item / 'cmdline').read_bytes().split(b'\x00')
            role = known_role(args)
            if not role:
                continue
            uid = (item / 'status').read_text(encoding='utf-8', errors='replace')
            effective_uid = next((line.split()[2] for line in uid.splitlines()
                              if line.startswith('Uid:')), None)
            if effective_uid is None:
                return {'state': 'PROC_PARTIAL', 'roles': sorted(roles),
                        'different_owner_roles': sorted(other_owner),
                        'unreadable_processes': unreadable}
            roles.add(role)
            if int(effective_uid) != os.geteuid():
                other_owner.add(role)
        except (OSError, ValueError, IndexError):
            unreadable += 1
    return {'state': 'READABLE', 'roles': sorted(roles),
            'different_owner_roles': sorted(other_owner),
            'unreadable_processes': unreadable}


def runtime_listeners(proc_net: Path = Path('/proc/net')) -> dict[str, object]:
    """Read Linux socket table only; hold if unknown, or if Runtime is in use."""
    ports = {5911: 'vnc_5911', 6081: 'novnc_6081', 8002: 'controller_8002'}
    listening = set()
    read_any = False
    for file in (proc_net / 'tcp', proc_net / 'tcp6'):
        try:
            lines = file.read_text(encoding='ascii').splitlines()[1:]
            read_any = True
        except OSError:
            continue
        for line in lines:
            fields = line.split()
            if len(fields) < 4 or fields[3] != '0A':
                continue
            parts = fields[1].split(':')
            if len(parts) != 2:
                continue
            try:
                port = int(parts[1], 16)
            except ValueError:
                continue
            if port in ports:
                listening.add(ports[port])
    return {'state': 'READABLE' if read_any else 'UNKNOWN',
            'active': sorted(listening)}


def emit(code: str, *, mode_before: str | None = None,
         mode_after: str | None = None, changed: bool = False,
         processes: dict[str, object] | None = None) -> None:
    event = {'event': 'PRIVATE_MODE_REPAIR', 'verdict': code,
             'mode_before': mode_before, 'mode_after': mode_after,
             'directory_changes': 1 if changed else 0,
             'other_changes': 0, 'owner_post_count': 0}
    if processes is not None:
        event['processes'] = processes
    print(json.dumps(event, sort_keys=True), flush=True)


def repair(*, apply: bool, home: Path | None = None,
           processes: dict[str, object] | None = None,
           listeners: dict[str, object] | None = None) -> str:
    if os.environ.get('CODESPACE_NAME') != EXPECTED_CODESPACE:
        emit('HOLD_WRONG_CODESPACE')
        return 'HOLD_WRONG_CODESPACE'
    home = home or Path.home()
    processes = processes if processes is not None else check_process_owners()
    listeners = listeners if listeners is not None else runtime_listeners()
    # Only services with recognized command signatures are attributable.
    # An inaccessible /proc is a hold. For ordinary unreadable processes,
    # avoid asserting they are safe; the result explicitly reports the count.
    if processes['state'] != 'READABLE':
        emit('HOLD_PROCESS_SCAN_INCOMPLETE', processes=processes)
        return 'HOLD_PROCESS_SCAN_INCOMPLETE'
    if processes['different_owner_roles']:
        emit('HOLD_SHARED_SERVICE_OTHER_OWNER', processes=processes)
        return 'HOLD_SHARED_SERVICE_OTHER_OWNER'
    if listeners['state'] != 'READABLE':
        emit('HOLD_RUNTIME_PORTS_UNKNOWN', processes=processes)
        return 'HOLD_RUNTIME_PORTS_UNKNOWN'
    if listeners['active']:
        emit('HOLD_RUNTIME_ACTIVE_OR_PARTIAL', processes=processes)
        return 'HOLD_RUNTIME_ACTIVE_OR_PARTIAL'

    fds = []
    try:
        fd = os.open(home, DIR_FLAGS)
        fds.append(fd)
        if not stat.S_ISDIR(os.fstat(fd).st_mode):
            emit('HOLD_PARENT_UNSAFE', processes=processes)
            return 'HOLD_PARENT_UNSAFE'
        for component in ('.local', 'share', 'minifish'):
            fd = os.open(component, DIR_FLAGS, dir_fd=fd)
            fds.append(fd)
            if not stat.S_ISDIR(os.fstat(fd).st_mode):
                emit('HOLD_PARENT_UNSAFE', processes=processes)
                return 'HOLD_PARENT_UNSAFE'
        target = fds[-1]
        before = os.fstat(target)
        prior = format(stat.S_IMODE(before.st_mode), '04o')
        if before.st_uid != os.geteuid():
            emit('HOLD_OWNER_MISMATCH', mode_before=prior, processes=processes)
            return 'HOLD_OWNER_MISMATCH'
        if prior == '0700':
            emit('ALREADY_0700', mode_before=prior, mode_after=prior, processes=processes)
            return 'ALREADY_0700'
        if prior != '0755':
            emit('HOLD_UNEXPECTED_MODE', mode_before=prior, processes=processes)
            return 'HOLD_UNEXPECTED_MODE'
        # Confirm the opened inode is still the directory at the designated path.
        path_stat = os.stat('minifish', dir_fd=fds[-2], follow_symlinks=False)
        if (path_stat.st_dev, path_stat.st_ino) != (before.st_dev, before.st_ino):
            emit('HOLD_TARGET_CHANGED', mode_before=prior, processes=processes)
            return 'HOLD_TARGET_CHANGED'
        if not apply:
            emit('READY_TO_RESTRICT', mode_before=prior, mode_after=prior, processes=processes)
            return 'READY_TO_RESTRICT'
        # One mutation only. fd + O_NOFOLLOW prevents symlink traversal.
        os.fchmod(target, 0o700)
        after = os.fstat(target)
        # Repeat the path-identity check after change to reject a swapped target.
        path_after = os.stat('minifish', dir_fd=fds[-2], follow_symlinks=False)
        same = (path_after.st_dev, path_after.st_ino) == (after.st_dev, after.st_ino)
        final = format(stat.S_IMODE(after.st_mode), '04o')
        verdict = ('CHMOD_0700_VERIFIED' if final == '0700' and same
                   else 'HOLD_POSTCHANGE_IDENTITY_OR_MODE')
        emit(verdict, mode_before=prior, mode_after=final, changed=True, processes=processes)
        return verdict
    except (OSError, ValueError, TypeError):
        emit('HOLD_PATH_UNSAFE_OR_UNREADABLE', processes=processes)
        return 'HOLD_PATH_UNSAFE_OR_UNREADABLE'
    finally:
        for handle in reversed(fds):
            os.close(handle)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check', action='store_true', help='READ-only (default)')
    mode.add_argument('--apply', action='store_true', help='Authorize exactly one chmod 0700')
    args = parser.parse_args(argv)
    result = repair(apply=args.apply)
    return 0 if result in ('READY_TO_RESTRICT', 'ALREADY_0700', 'CHMOD_0700_VERIFIED') else 2


if __name__ == '__main__':
    sys.exit(main())
