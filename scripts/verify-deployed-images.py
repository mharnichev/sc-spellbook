#!/usr/bin/env python3
"""Compare release references with running image IDs, without pulling or env dumps."""
import argparse
import os
from pathlib import Path
import re
import subprocess
import sys

SERVICES = {
    'backend': 'BACKEND_IMAGE', 'booking-sms-reminders': 'BACKEND_IMAGE',
    'shop': 'SHOP_IMAGE', 'admin-app': 'ADMIN_APP_IMAGE',
    'public-site': 'PUBLIC_SITE_IMAGE', 'blog': 'BLOG_IMAGE',
    'caddy': 'CADDY_IMAGE', 'postgres': 'POSTGRES_IMAGE',
}
DIGEST_KEYS = {'BACKEND_IMAGE', 'SHOP_IMAGE', 'ADMIN_APP_IMAGE', 'CADDY_IMAGE', 'POSTGRES_IMAGE'}
IMAGE_ID = re.compile(r'sha256:[0-9a-f]{64}')


class VerificationError(Exception):
    pass


def pins(path):
    values = {}
    for line in path.read_text().splitlines():
        key, separator, value = line.partition('=')
        if not separator or key not in SERVICES.values():
            continue
        if key in values:
            raise VerificationError('duplicate image pin')
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if not value or any(c.isspace() or c in '$`' for c in value):
            raise VerificationError('invalid image pin')
        if key in DIGEST_KEYS and not re.fullmatch(r'[^@\s]+@sha256:[0-9a-f]{64}', value):
            raise VerificationError('immutable engine/application pin required')
        values[key] = value
    if set(values) != set(SERVICES.values()):
        raise VerificationError('required release image pin missing')
    return values


def command(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        raise VerificationError('Docker query unavailable or timed out') from None
    if result.returncode:
        raise VerificationError('Docker query failed')
    return result.stdout.strip()


def verify(root, project):
    expected = pins(root / 'versions/production.env')
    compose = ['docker', 'compose', '--project-name', project, '--env-file',
               str(root / 'versions/production.env'), '-f', str(root / 'docker-compose.prod.yml')]
    # Force the release's literal references, not shell image overrides.
    env_before = {key: os.environ.get(key) for key in expected}
    os.environ.update(expected)
    try:
        for service, key in SERVICES.items():
            try:
                intended_id = command(['docker', 'image', 'inspect', '--format', '{{.Id}}', expected[key]])
                if not IMAGE_ID.fullmatch(intended_id):
                    raise VerificationError('invalid local image identity')
                ids = command([*compose, 'ps', '-q', service]).splitlines()
                if len(ids) != 1 or not re.fullmatch(r'[0-9a-f]{64}', ids[0]):
                    raise VerificationError('exactly one service container required')
                template = '{{.Image}}|{{.State.Running}}|{{index .Config.Labels "com.docker.compose.service"}}|{{index .Config.Labels "com.docker.compose.project"}}'
                actual = command(['docker', 'inspect', '--format', template, ids[0]])
                if actual != '|'.join((intended_id, 'true', service, project)):
                    raise VerificationError('running container image/state/labels mismatch')
            except VerificationError as error:
                raise VerificationError(f'{service}: {error}') from None
    finally:
        for key, old in env_before.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pins-only', action='store_true')
    parser.add_argument('root', nargs='?', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        root = args.root.resolve()
        if args.pins_only:
            pins(root / 'versions/production.env')
        else:
            verify(root, os.environ.get('COMPOSE_PROJECT_NAME', 'soulcuts'))
    except (VerificationError, OSError, ValueError):
        # Do not expose Docker stderr, file contents, environment or references.
        print('Deployed image verification failed; release acceptance refused.', file=sys.stderr)
        raise SystemExit(1)
    print('Release image pins validated.' if args.pins_only else 'Release image IDs match all eight running services.')
