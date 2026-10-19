#!/usr/bin/env python3
"""Seal a private paired backup directory only after both archives validate."""
import hashlib
import json
from pathlib import Path
import sys


def main():
    root = Path(sys.argv[1])
    dumps, media = list(root.glob('*.dump')), list(root.glob('*.tar.gz'))
    if len(dumps) != 1 or len(media) != 1:
        raise ValueError('Exactly one database and one media archive required')
    manifest = {}
    for path in dumps + media:
        if path.stat().st_size == 0 or path.stat().st_mode & 0o077:
            raise ValueError('Empty or non-private backup')
        with path.open('rb') as stream:
            checksum = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                checksum.update(chunk)
            digest = checksum.hexdigest()
        manifest[path.name] = {'bytes': path.stat().st_size, 'sha256': digest}
    with (root / 'manifest.json').open('x') as out:
        json.dump(manifest, out, indent=2)


if __name__ == '__main__':
    main()
