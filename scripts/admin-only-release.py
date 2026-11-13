#!/usr/bin/env python3
"""Validate narrow application scopes against immutable pins and shared inputs."""
import importlib.util
from pathlib import Path
import sys

spec = importlib.util.spec_from_file_location('release_images', Path(__file__).with_name('verify-deployed-images.py'))
images = importlib.util.module_from_spec(spec)
spec.loader.exec_module(images)

BALANCE_INGRESS = (
    b'\t@shop_balance_login {\n\t\tmethod POST\n\t\tpath /api/v1/shop-balance/login\n\t}\n'
    b'\thandle @shop_balance_login {\n\t\timport direct_api\n\t}\n'
    b'\t@shop_balance_entries {\n\t\tmethod GET POST\n\t\tpath /api/v1/shop-balance/entries\n\t}\n'
    b'\thandle @shop_balance_entries {\n\t\timport direct_api\n\t}\n'
)
SHOP_PAYMENT_CSP = (
    b'\t@shop_payment_pages path /shop/checkout /shop/checkout/* /shop/payment/* /shop/cabinet/orders/*\n'
    b'\theader @shop_payment_pages Content-Security-Policy "frame-src https://pay.mbnk.biz https://pay.monobank.ua"\n'
)


def admin_image(previous, current, *, allow_unchanged=False, backend_admin=False,
                admin_shop=False, select_shop=False, shop_ingress=False,
                select_caddy=False, public_admin=False, select_public=False):
    try:
        old = images.pins(previous / 'versions/production.env')
        new = images.pins(current / 'versions/production.env')
        changed = {key for key in new if new[key] != old[key]}
        if sum((backend_admin, admin_shop, shop_ingress, public_admin)) > 1 or sum((select_shop, select_caddy, select_public)) > 1:
            return ''
        if (select_shop and not (admin_shop or shop_ingress)
                or select_caddy and not shop_ingress or select_public and not public_admin):
            return ''
        if public_admin:
            if changed - {'PUBLIC_SITE_IMAGE', 'ADMIN_APP_IMAGE'} or (not changed and not allow_unchanged):
                return ''
        elif shop_ingress:
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
            runtime_override = b'      NUXT_PUBLIC_DOBRODESK_ENABLED: "false"\n'
            shop_block = before.partition(b'\n  shop:\n')[2].partition(b'\n  backend:\n')[0]
            if (admin_shop and name == 'docker-compose.prod.yml'
                    and before.count(runtime_override) == 1
                    and runtime_override in shop_block
                    and after == before.replace(runtime_override, b'', 1)):
                continue
            if shop_ingress and name == 'caddy/Caddyfile':
                csp_anchor = b'\theader @shop_pages Cache-Control "no-store, private"\n'
                if (before.count(csp_anchor) == 1 and SHOP_PAYMENT_CSP not in before
                        and after == before.replace(csp_anchor, csp_anchor + SHOP_PAYMENT_CSP, 1)):
                    continue
                anchor = b'\tredir /shop /shop/ 308\n'
                if (before.count(anchor) == 1 and BALANCE_INGRESS not in before
                        and after == before.replace(anchor, BALANCE_INGRESS + anchor, 1)):
                    continue
                token = b' /api/v1/public/shop-promotions/quote'
                matchers = [line for line in after.splitlines() if line.startswith(b'\t@shop_api path ')]
                if len(matchers) != 1 or token.strip() not in matchers[0].split()[2:] or after.count(token) != 1:
                    return ''
                if before != after and (token in before or after.replace(token, b'', 1) != before):
                    return ''
            elif before != after:
                return ''
        return new['PUBLIC_SITE_IMAGE' if select_public else 'CADDY_IMAGE' if select_caddy else 'SHOP_IMAGE' if select_shop else 'ADMIN_APP_IMAGE']
    except (OSError, images.VerificationError):
        return ''


if __name__ == '__main__':
    print(admin_image(Path(sys.argv[1]), Path(sys.argv[2]),
                      allow_unchanged='--allow-unchanged' in sys.argv[3:],
                      backend_admin='--backend-admin' in sys.argv[3:],
                      admin_shop='--admin-shop' in sys.argv[3:],
                      shop_ingress='--shop-ingress' in sys.argv[3:],
                      select_caddy='--caddy-image' in sys.argv[3:],
                      public_admin='--public-admin' in sys.argv[3:],
                      select_public='--public-image' in sys.argv[3:],
                      select_shop='--shop-image' in sys.argv[3:]))
