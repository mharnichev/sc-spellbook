#!/usr/bin/env python3
"""Validate the operator-provisioned private incident directory without changing it."""
from pathlib import Path
import os
import re
import stat
import sys


STORE = Path('/opt/soulcuts/data/sentry-incidents')
FILES = tuple('incidents.sqlite3' + suffix for suffix in ('', '-wal', '-shm', '-journal'))


def validate(path, runtime_uid):
    if not re.fullmatch(r'0|[1-9][0-9]*', runtime_uid):
        raise ValueError('Invalid backend runtime UID')
    # Reject symlinked parents too: the bind must refer to the reviewed host path.
    for component in (*reversed(path.parents), path):
        metadata = component.lstat()
        if not stat.S_ISDIR(metadata.st_mode):
            raise ValueError('Incident store path must contain only real directories')
    if stat.S_IMODE(metadata.st_mode) != 0o700 or metadata.st_uid != int(runtime_uid):
        raise ValueError('Incident store requires mode 0700 and backend runtime UID ownership')


def validate_files(path):
    validate(path, str(os.geteuid()))
    for name in FILES:
        file = path / name
        try:
            metadata = file.lstat()
        except FileNotFoundError:
            continue
        mode = stat.S_IMODE(metadata.st_mode)
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid()
                or mode & 0o600 != 0o600 or mode & 0o7022):
            raise ValueError('Incident database and sidecars require regular owned files, owner RW and no shared write')
        # The bind is read-only: verify reads without SQLite recovery or writes.
        # Owner write bits above are checked explicitly, even for runtime root.
        fd = os.open(file, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            opened = os.fstat(fd)
            if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
                raise ValueError('Incident file changed during preflight')
            os.read(fd, 1)
        finally:
            os.close(fd)


if __name__ == '__main__':
    try:
        if len(sys.argv) != 2:
            raise ValueError('Expected backend runtime UID')
        if sys.argv[1] == '--runtime-store':
            validate_files(Path('/state'))
        else:
            validate(STORE, sys.argv[1])
    except (OSError, ValueError) as error:
        raise SystemExit('Sentry incident store preflight failed: ' + str(error)) from None
