#!/usr/bin/env python3
"""Validate narrow application scopes against immutable pins and shared inputs."""
import importlib.util
from pathlib import Path
import sys

spec = importlib.util.spec_from_file_location('release_images', Path(__file__).with_name('verify-deployed-images.py'))
images = importlib.util.module_from_spec(spec)
spec.loader.exec_module(images)


def admin_image(previous, current, *, allow_unchanged=False, backend_admin=False,
                admin_shop=False, select_shop=False):
    try:
        old = images.pins(previous / 'versions/production.env')
        new = images.pins(current / 'versions/production.env')
        changed = {key for key in new if new[key] != old[key]}
        if backend_admin and admin_shop or select_shop and not admin_shop:
            return ''
        if admin_shop:
            if changed - {'ADMIN_APP_IMAGE', 'SHOP_IMAGE'} or (not changed and not allow_unchanged):
                return ''
        elif backend_admin:
            if 'BACKEND_IMAGE' not in changed or changed - {'BACKEND_IMAGE', 'ADMIN_APP_IMAGE'}:
                return ''
        elif changed != {'ADMIN_APP_IMAGE'} and not (allow_unchanged and not changed):
            return ''
        for name in ('docker-compose.prod.yml', 'caddy/Caddyfile'):
            if (previous / name).read_bytes() != (current / name).read_bytes():
                return ''
        return new['SHOP_IMAGE' if select_shop else 'ADMIN_APP_IMAGE']
    except (OSError, images.VerificationError):
        return ''


if __name__ == '__main__':
    print(admin_image(Path(sys.argv[1]), Path(sys.argv[2]),
                      allow_unchanged='--allow-unchanged' in sys.argv[3:],
                      backend_admin='--backend-admin' in sys.argv[3:],
                      admin_shop='--admin-shop' in sys.argv[3:],
                      select_shop='--shop-image' in sys.argv[3:]))
