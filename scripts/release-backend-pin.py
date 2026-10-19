#!/usr/bin/env python3
"""Read one literal backend image pin without evaluating shell environment files."""
from pathlib import Path
import sys


def read_pin(path):
    values = [line.split('=', 1)[1].strip() for line in Path(path).read_text().splitlines()
              if line.startswith('BACKEND_IMAGE=')]
    if len(values) != 1:
        raise ValueError('Release must contain exactly one BACKEND_IMAGE pin')
    value = values[0]
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    if not value or any(c.isspace() or c in '$`' for c in value):
        raise ValueError('Backend image pin must be literal and nonempty')
    return value


if __name__ == '__main__':
    print(read_pin(sys.argv[1]))
