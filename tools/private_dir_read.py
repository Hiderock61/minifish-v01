#!/usr/bin/env python3
"""MiniFish private-directory failure triage. STRICTLY READ-ONLY.

No chmod, mkdir, write, file content reads, HTTP, process starts, or retries.
Print only fixed label, object type, numeric mode, same-owner boolean.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat

CODESPACE = 'accursed-apparition-6q7jwqq5965h4rpq'
LABELS = (
    ('home', ''),
    ('local', '.local'),
    ('share', '.local/share'),
    ('minifish', '.local/share/minifish'),
    ('bootstrap', '.local/share/minifish/api-bootstrap'),
    ('runtime', '.local/share/minifish/g1b-mock-only'),
    ('bootlog', '.local/share/minifish/owner-desktop-boot.log'),
)


def inspect_path(path: Path, euid: int) -> dict[str, object]:
    try:
        meta = path.lstat()  # Does not follow symlinks.
    except FileNotFoundError:
        return {'type': 'MISSING', 'mode': None, 'owner_is_current': None}
    except PermissionError:
        return {'type': 'INACCESSIBLE', 'mode': None, 'owner_is_current': None}
    except OSError:
        return {'type': 'STAT_ERROR', 'mode': None, 'owner_is_current': None}
    if stat.S_ISLNK(meta.st_mode):
        kind = 'SYMLINK'
    elif stat.S_ISDIR(meta.st_mode):
        kind = 'DIR'
    elif stat.S_ISREG(meta.st_mode):
        kind = 'FILE'
    else:
        kind = 'OTHER'
    return {'type': kind, 'mode': format(stat.S_IMODE(meta.st_mode), '04o'),
            'owner_is_current': meta.st_uid == euid}


def decide(entries: dict[str, dict[str, object]]) -> str:
    root = entries['minifish']
    if root['type'] == 'SYMLINK':
        return 'ROOT_SYMLINK_MATCHES_REJECTION'
    if root['type'] == 'DIR' and root['mode'] != '0700':
        return 'ROOT_MODE_MISMATCH_MATCHES_REJECTION'
    if root['type'] == 'DIR' and root['mode'] == '0700':
        return 'ROOT_MODE_OK_AT_READ_TIME_CAUSE_UNCONFIRMED'
    if root['type'] == 'MISSING':
        return 'ROOT_MISSING_AT_READ_TIME_CAUSE_UNCONFIRMED'
    return 'ROOT_UNEXPECTED_TYPE_OR_UNREADABLE'


def collect(home: Path, euid: int) -> dict[str, object]:
    entries = {label: inspect_path(home / suffix, euid) for label, suffix in LABELS}
    return {'event': 'PRIVATE_DIR_READ', 'entries': entries,
            'verdict': decide(entries), 'mutation_count': 0, 'owner_post_count': 0}


def main() -> int:
    # Inspect only the one approved Codespace; do not print raw environment.
    if os.environ.get('CODESPACE_NAME') != CODESPACE:
        print(json.dumps({'event': 'GATE', 'verdict': 'HOLD_WRONG_CODESPACE',
                          'mutation_count': 0, 'owner_post_count': 0}, sort_keys=True))
        return 2
    result = collect(Path.home(), os.geteuid())
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
