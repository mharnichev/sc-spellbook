import copy
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('shop_config_test', ROOT/'scripts/shop-online-config.py')
CONFIG = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONFIG)


class Secret:
    def get_secret_value(self):
        return 'synthetic-token-not-a-provider-secret'


def settings():
    result = SimpleNamespace(app_env='production', mono_checkbox_auto_enabled=True,
        shop_checkout_enabled=False, shop_checkout_pilot_enabled=True,
        shop_checkout_pilot_customer_ids='10',
        master_monobank_profile=dict(merchant_id='fixture-merchant', environment='production',
                                     external_fiscalization_disabled=False),
        master_mono_enabled=True, master_mono_checkbox_link_confirmed=True,
        shop_checkbox_enabled=False, shop_fiscal_mock_enabled=False,
        shop_checkbox_profile=None, shop_payment_manual_policy=None, shop_monobank_token=Secret())
    for key in CONFIG.FIELDS:
        setattr(result, key.lower(), False if key in CONFIG.FLAGS else None)
    return result


class ShopOnlineConfigTests(unittest.TestCase):
    def test_only_exact_singleton_customer_10_is_approved(self):
        config = settings()
        CONFIG.plan(config, 1)
        self.assertEqual(config.shop_checkout_pilot_customer_ids, '10')
        for value in (','.join(map(str, range(1, 11))), '10,10', '10,11', '1', '',
                      '010', '+10', '10.0', ' 10', '10 ', '10,', ',10', '10\n',
                      '\u0661\u0660', None, 10, ['10']):
            for verify in (False, True):
                config = settings()
                if verify:
                    CONFIG.plan(config, 1)
                config.shop_checkout_pilot_customer_ids = value
                before = copy.copy(vars(config))
                with self.subTest(value=value, verify=verify), self.assertRaises(RuntimeError):
                    CONFIG.plan(config, 1, verify=verify)
                self.assertEqual(vars(config), before)

    def test_plan_only_changes_owned_fields_and_verify_matches_exactly(self):
        config = settings()
        before = copy.copy(vars(config))
        plan = CONFIG.plan(config, 1)
        self.assertEqual(set(plan['aliases']), set(CONFIG.FIELDS))
        self.assertEqual(plan, CONFIG.plan(config, 1, verify=True))
        for key, value in before.items():
            if key.upper() not in CONFIG.FIELDS:
                self.assertEqual(getattr(config, key), value)
        self.assertNotIn(config.shop_monobank_token.get_secret_value(), str(plan))

    def test_each_enabled_flag_and_existing_manual_configuration_refused(self):
        for key in CONFIG.FIELDS:
            config = settings()
            setattr(config, key.lower(), True if key in CONFIG.FLAGS else 1 if key.endswith('_ID') else {})
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                CONFIG.plan(config, 1)
        for key, value in (('shop_payment_manual_policy', {}), ('shop_checkbox_profile', {}),
                           ('shop_checkbox_enabled', True), ('shop_fiscal_mock_enabled', True)):
            config = settings()
            setattr(config, key, value)
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                CONFIG.plan(config, 1)

    def test_public_checkout_pilot_autopoll_and_master_guards(self):
        changes = (('shop_checkout_enabled', True), ('shop_checkout_pilot_enabled', False),
                   ('mono_checkbox_auto_enabled', False), ('master_mono_enabled', False),
                   ('master_mono_checkbox_link_confirmed', False), ('app_env', 'test'),
                   ('shop_checkout_pilot_customer_ids', '1,2'),
                   ('shop_checkout_pilot_customer_ids', ','.join(['1']*10)),
                   ('master_monobank_profile', {'environment': 'test'}),
                   ('shop_monobank_token', None))
        for key, value in changes:
            config = settings()
            setattr(config, key, value)
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                CONFIG.plan(config, 1)

    def test_verify_rejects_operator_policy_and_profile_drift(self):
        for key, value in (('shop_online_payment_operator_id', 3),
                           ('shop_monobank_profile', {}), ('shop_online_payment_fiscal_policy', {}),
                           ('shop_online_payment_enabled', False)):
            config = settings()
            CONFIG.plan(config, 1)
            setattr(config, key, value)
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                CONFIG.plan(config, 1, verify=True)

    def test_operator_id_must_be_positive_non_boolean_integer(self):
        for value in (True, 0, -1, '1'):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                CONFIG.plan(settings(), value)
