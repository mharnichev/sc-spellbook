#!/usr/bin/env python3
"""Validate narrow application scopes against immutable pins and shared inputs."""
import importlib.util
from pathlib import Path
import sys

spec = importlib.util.spec_from_file_location('release_images', Path(__file__).with_name('verify-deployed-images.py'))
images = importlib.util.module_from_spec(spec)
spec.loader.exec_module(images)


def admin_image(previous, current, *, allow_unchanged=False, backend_admin=False,
                admin_shop=False, select_shop=False, shop_ingress=False,
                select_caddy=False):
    try:
        old = images.pins(previous / 'versions/production.env')
        new = images.pins(current / 'versions/production.env')
        changed = {key for key in new if new[key] != old[key]}
        if sum((backend_admin, admin_shop, shop_ingress)) > 1 or (select_shop and select_caddy):
            return ''
        if select_shop and not (admin_shop or shop_ingress) or select_caddy and not shop_ingress:
            return ''
        if shop_ingress:
            if changed - {'SHOP_IMAGE'} or (not changed and not allow_unchanged):
                return ''
        elif admin_shop:
            if changed - {'ADMIN_APP_IMAGE', 'SHOP_IMAGE'} or (not changed and not allow_unchanged):
                return ''
        elif backend_admin:
            if 'BACKEND_IMAGE' not in changed or changed - {'BACKEND_IMAGE', 'ADMIN_APP_IMAGE'}:
                return ''
        elif changed != {'ADMIN_APP_IMAGE'} and not (allow_unchanged and not changed):
            return ''
        for name in ('docker-compose.prod.yml', 'caddy/Caddyfile'):
            before, after = (previous / name).read_bytes(), (current / name).read_bytes()
            if shop_ingress and name == 'caddy/Caddyfile':
                token = b' /api/v1/public/shop-promotions/quote'
                matchers = [line for line in after.splitlines() if line.startswith(b'\t@shop_api path ')]
                if len(matchers) != 1 or token.strip() not in matchers[0].split()[2:] or after.count(token) != 1:
                    return ''
                if before != after and (token in before or after.replace(token, b'', 1) != before):
                    return ''
            elif before != after:
                return ''
        return new['CADDY_IMAGE' if select_caddy else 'SHOP_IMAGE' if select_shop else 'ADMIN_APP_IMAGE']
    except (OSError, images.VerificationError):
        return ''


if __name__ == '__main__':
    print(admin_image(Path(sys.argv[1]), Path(sys.argv[2]),
                      allow_unchanged='--allow-unchanged' in sys.argv[3:],
                      backend_admin='--backend-admin' in sys.argv[3:],
                      admin_shop='--admin-shop' in sys.argv[3:],
                      shop_ingress='--shop-ingress' in sys.argv[3:],
                      select_caddy='--caddy-image' in sys.argv[3:],
                      select_shop='--shop-image' in sys.argv[3:]))
