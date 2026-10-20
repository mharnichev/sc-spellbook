#!/usr/bin/env python3
"""Pure candidate Settings planning. Never connects to a database or provider."""
import hashlib
import json
import socket
import sys

FLAGS = ('SHOP_PAYMENTS_ENABLED', 'SHOP_ORDER_OPERATIONS_ENABLED', 'SHOP_MONO_CHECKBOX_ENABLED',
         'SHOP_MONOBANK_LIVE_TRANSPORT_ENABLED', 'SHOP_ONLINE_PAYMENT_ENABLED',
         'SHOP_ONLINE_PAYMENT_INVOICE_CREATE_ENABLED', 'SHOP_ONLINE_PAYMENT_LINK_CONFIRMED')
FIELDS = (*FLAGS, 'SHOP_ONLINE_PAYMENT_OPERATOR_ID', 'SHOP_MONOBANK_PROFILE',
          'SHOP_ONLINE_PAYMENT_FISCAL_POLICY')


def require(value):
    if not value:
        raise RuntimeError('Shop configuration safety condition failed')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False).encode()).hexdigest()


def deny_network(*args, **kwargs):
    raise RuntimeError('Network access is forbidden')


def plan(settings, operator_id, *, verify=False):
    require(type(operator_id) is int and operator_id > 0)
    require(settings.app_env == 'production' and settings.mono_checkbox_auto_enabled is True)
    require(settings.shop_checkout_enabled is False and settings.shop_checkout_pilot_enabled is True)
    # The approved pilot is customer ID 10, not a count of ten customers.
    require(type(settings.shop_checkout_pilot_customer_ids) is str
            and settings.shop_checkout_pilot_customer_ids == '10')
    master = settings.master_monobank_profile
    require(isinstance(master, dict) and master.get('environment') == 'production'
            and master.get('external_fiscalization_disabled') is False
            and settings.master_mono_enabled is True
            and settings.master_mono_checkbox_link_confirmed is True)
    require(not settings.shop_checkbox_enabled and not settings.shop_fiscal_mock_enabled)
    require(settings.shop_checkbox_profile is None and settings.shop_payment_manual_policy is None)
    token = settings.shop_monobank_token
    secret = token.get_secret_value() if token else ''
    require(bool(secret) and isinstance(master.get('merchant_id'), str) and bool(master['merchant_id']))
    profile = dict(id='soulcuts-shop-online-tax8-v1', merchant_id=master['merchant_id'],
                   token_sha256=hashlib.sha256(secret.encode()).hexdigest(), environment='production',
                   external_fiscalization_disabled=False)
    policy = dict(id='soulcuts-shop-tax8-v1', tax_codes=[8], unit='шт.')
    aliases = {**dict.fromkeys(FLAGS, True), 'SHOP_ONLINE_PAYMENT_OPERATOR_ID': operator_id,
               'SHOP_MONOBANK_PROFILE': profile, 'SHOP_ONLINE_PAYMENT_FISCAL_POLICY': policy}
    for alias, value in aliases.items():
        name = alias.lower()
        old = getattr(settings, name)
        if verify:
            require(type(old) is type(value) and old == value)
        elif alias in FLAGS:
            require(old is False)
        else:
            require(old is None)
    # Mutation is confined to this network-none one-shot process.
    for alias, value in aliases.items():
        setattr(settings, alias.lower(), value)
    return dict(aliases=aliases, profile_sha256=digest(profile))


def main():
    require(not sys.flags.optimize and len(sys.argv) == 3 and sys.argv[1] in ('plan', 'verify'))
    socket.socket.connect = deny_network
    socket.socket.connect_ex = deny_network
    socket.create_connection = deny_network
    from app.core.config import settings
    result = plan(settings, int(sys.argv[2]), verify=sys.argv[1] == 'verify')
    from app.services.monobank_provider import MonobankGateway
    from app.services.shop_online_payment import config_ready
    provider = MonobankGateway(create_capability='shop')
    require(provider.available and provider.external_checkbox and provider.profile == result['aliases']['SHOP_MONOBANK_PROFILE'])
    require(config_ready(provider))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        raise SystemExit('Shop configuration refused; private values suppressed') from None
