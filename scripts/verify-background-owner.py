#!/usr/bin/env python3
"""Check existing API owner logs; never print raw application logs."""
import re
import sys

STATE = re.compile(r'background_workers state=([a-z]+) role=([a-z]+) code=([A-Za-z_]+)')


def require_owner(lines):
    states = [match.groups() for line in lines for match in [STATE.search(line)] if match]
    if not states or states[-1] != ('running', 'owner', 'None'):
        raise ValueError('Latest API background state is not running/owner or owner log evidence is absent')


if __name__ == '__main__':
    try:
        require_owner(sys.stdin)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
    print('Existing API process latest owner state: running/owner')
