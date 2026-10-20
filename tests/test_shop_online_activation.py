import copy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
import io
from unittest.mock import patch

from test_shop_online_config import CONFIG, settings

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('shop_activation_test', ROOT/'scripts/activate-shop-online.py')
OP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(OP)
PIN = 'ghcr.io/mharnichev/sc-be/api@sha256:'+'a'*64
OLD = 'ghcr.io/mharnichev/sc-be/api@sha256:'+'b'*64


class Fixture:
    def __init__(self, directory):
        self.app = Path(directory)
        self.root = self.app/'releases/candidate'
        self.root.mkdir(parents=True)
        (self.app/'env').mkdir()
        (self.app/'backups').mkdir()
        accepted = self.app/'releases/accepted'
        accepted.mkdir()
        (self.app/'current').symlink_to(accepted)
        self.env = self.app/'env/backend.env'
        self.before = (b'# keep all unrelated bytes\nMASTER_MONO_ENABLED=true\n'
                       b'UNCHANGED="quoted # value"\nSHOP_CHECKOUT_PILOT_CUSTOMER_IDS=10\n')
        OP.persist_bytes(self.env, self.before)
        self.proof = self.app/'backups/shop-online-readiness-fixture'
        self.proof.mkdir(mode=0o700)
        self.plan = CONFIG.plan(settings(), 1)
        OP.persist(self.proof/'proof.json', dict(schema_version=1, verified=True, merchant_get_requests=1,
            merchant_profile_sha256=self.plan['profile_sha256'], env_sha256=OP.sha(self.before),
            created_at=datetime.now(timezone.utc).isoformat(), source_image=OLD))
        self.marker = self.app/'shop-online-activation-required'
        (self.app/'backend-recovery-required').write_text('backend fence fixture')
        self.baseline = dict(identity={'database': 'barbershop_platform'}, head=[OP.HEAD],
            operator=dict(id=1, is_active=True, is_superuser=False, can_record_sales=True),
            grants={'admins': [{'id': 1, 'can_record_sales': True}], 'masters': []},
            inventory=[], shop_orders=0,
            tables={name: dict(rows=0, sha256='fixture') for name in OP.SHOP_TABLES}, sequences={})
        self.baseline['tables']['master_mono_payments'] = dict(rows=7, sha256='master-history-preserved')
        self.calls, self.db_calls = [], 0
        self.fail = None

    @property
    def report(self):
        return next((self.app/'backups').glob('shop-online-activation-*'))

    def run(self, args, *, data=None, timeout=120):
        self.calls.append((args, data))
        if args[:2] == ['docker', 'ps']:
            return 'a'*12 if '-aq' in args else ''
        if args[:2] == ['docker', 'run']:
            if self.fail == 'timeout':
                raise subprocess.TimeoutExpired('docker', 120)
            return json.dumps(self.plan)
        if args[:2] == ['docker', 'exec']:
            self.db_calls += 1
            if self.fail == 'post-replace-db' and self.env.read_bytes() != self.before:
                raise RuntimeError('injected lost acknowledgement')
            result = copy.deepcopy(self.baseline)
            lines = [json.dumps({'kind': key, 'value': value}) for key, value in result.items()
                     if key not in ('tables', 'sequences')]
            for section, kind in (('tables', 'table'), ('sequences', 'sequence')):
                lines += [json.dumps({'kind': kind, 'name': name, 'value': value})
                          for name, value in result[section].items()]
            return '\n'.join(lines)
        raise AssertionError('Unexpected command: '+repr(args))

    def invoke(self, mode, *, runtime=False):
        arguments = [str(self.proof), '1'] if mode == 'apply' else [str(self.report)]
        with patch.object(OP, 'APP', self.app), \
             patch.object(OP, 'release_context', return_value=(self.root, PIN)), \
             patch.object(OP, 'writers') as writers, \
             patch.object(OP, 'pin_for', return_value=OLD), \
             patch.object(OP, 'run', side_effect=self.run), \
             patch.object(sys, 'argv', ['activate', mode, *arguments]), \
             patch.dict(os.environ, {'SHOP_ONLINE_RUNTIME_VERIFIED': str(runtime).lower()}), \
             redirect_stdout(io.StringIO()):
            OP.main()
            expected = [(mode == 'finalize', PIN)] * (2 if mode == 'apply' else 1)
            if [call.args for call in writers.call_args_list] != expected:
                raise AssertionError('Wrong writer-state safety checks')


class ShopOnlineActivationTests(unittest.TestCase):
    def test_apply_finalize_receipt_only_recovery_and_idempotent_finalize(self):
        with tempfile.TemporaryDirectory() as directory:
            f = Fixture(directory)
            f.invoke('apply')
            self.assertTrue(json.loads(f.marker.read_text())['pre_restart_original_verified'])
            self.assertIn(b'MASTER_MONO_ENABLED=true\nUNCHANGED="quoted # value"\n', f.env.read_bytes())
            self.assertEqual(f.env.read_bytes().count(b'SHOP_CHECKOUT_PILOT_CUSTOMER_IDS=10\n'), 1)
            self.assertEqual(f.env.read_bytes()[:len(f.before)], f.before)
            f.baseline['shop_orders'] = 1
            f.baseline['tables']['shop_online_payment_requests']['rows'] = 1
            f.invoke('finalize', runtime=True)
            self.assertFalse(f.marker.exists())
            self.assertTrue((f.report/'finalized.json').exists())
            f.invoke('recover-finalize')
            f.invoke('finalize', runtime=True)
            self.assertTrue((f.app/'backend-recovery-required').exists())

    def test_replacement_ack_loss_then_reconcile_never_reapplies(self):
        with tempfile.TemporaryDirectory() as directory:
            f = Fixture(directory)
            f.fail = 'post-replace-db'
            with self.assertRaises(RuntimeError):
                f.invoke('apply')
            self.assertTrue(f.marker.exists())
            after = f.env.read_bytes()
            f.fail = None
            f.invoke('reconcile')
            self.assertEqual(f.env.read_bytes(), after)
            self.assertTrue(json.loads(f.marker.read_text())['pre_restart_original_verified'])

    def test_ack_loss_then_rollback_restores_only_exact_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            f = Fixture(directory)
            f.fail = 'post-replace-db'
            with self.assertRaises(RuntimeError):
                f.invoke('apply')
            f.fail = None
            baseline = copy.deepcopy(f.baseline)
            f.invoke('rollback')
            self.assertEqual(f.env.read_bytes(), f.before)
            self.assertEqual(f.baseline, baseline)
            self.assertFalse(f.marker.exists())
            self.assertTrue((f.app/'backend-recovery-required').exists())
            f.invoke('rollback')
            self.assertEqual(f.env.read_bytes(), f.before)

    def test_environment_or_original_database_drift_blocks_reconcile_and_rollback(self):
        for drift in ('environment', 'database'):
            for mode in ('reconcile', 'rollback'):
                with self.subTest(drift=drift, mode=mode), tempfile.TemporaryDirectory() as directory:
                    f = Fixture(directory)
                    f.invoke('apply')
                    if drift == 'environment':
                        OP.persist_bytes(f.env, b'FOREIGN=true\n', replace=True)
                    else:
                        f.baseline['tables']['master_mono_payments']['rows'] += 1
                    before = f.env.read_bytes()
                    with self.assertRaises(RuntimeError):
                        f.invoke(mode)
                    self.assertTrue(f.marker.exists())
                    self.assertEqual(f.env.read_bytes(), before)

    def test_existing_shop_facts_and_operator_unavailable_refused_before_mutation(self):
        for change in ('shop_orders', *OP.SHOP_TABLES, 'operator'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                f = Fixture(directory)
                if change == 'shop_orders':
                    f.baseline[change] = 1
                elif change == 'operator':
                    f.baseline[change] = None
                else:
                    f.baseline['tables'][change]['rows'] = 1
                with self.assertRaises(RuntimeError):
                    f.invoke('apply')
                self.assertEqual(f.env.read_bytes(), f.before)

    def test_finalize_requires_runtime_ack_and_original_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            f = Fixture(directory)
            f.invoke('apply')
            with self.assertRaises(RuntimeError):
                f.invoke('finalize')
            state = json.loads(f.marker.read_text())
            state['pre_restart_original_verified'] = False
            OP.persist(f.marker, state, replace=True)
            with self.assertRaises(RuntimeError):
                f.invoke('recover-finalize')
            self.assertTrue(f.marker.exists())

    def test_live_grant_drift_retains_fence(self):
        with tempfile.TemporaryDirectory() as directory:
            f = Fixture(directory)
            f.invoke('apply')
            f.baseline['grants']['admins'][0]['can_record_sales'] = False
            with self.assertRaises(RuntimeError):
                f.invoke('finalize', runtime=True)
            self.assertTrue(f.marker.exists())

    def test_marker_is_durable_before_environment_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            f = Fixture(directory)
            native = OP.persist_bytes
            def observed(path, data, **kwargs):
                if path == f.env:
                    self.assertTrue(f.marker.exists())
                    self.assertEqual(json.loads(f.marker.read_text())['phase'], 'prepared')
                    for name in ('snapshot.json', 'plan.json', 'before.env', 'after.env', 'proof.json'):
                        self.assertTrue((f.report/name).exists())
                return native(path, data, **kwargs)
            with patch.object(OP, 'persist_bytes', side_effect=observed):
                f.invoke('apply')

    def test_failed_snapshot_fsync_prevents_environment_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            f = Fixture(directory)
            native = OP.persist_bytes
            def failed(path, data, **kwargs):
                if path.name == 'snapshot.json':
                    raise OSError('injected fsync failure')
                return native(path, data, **kwargs)
            with patch.object(OP, 'persist_bytes', side_effect=failed), self.assertRaises(OSError):
                f.invoke('apply')
            self.assertEqual(f.env.read_bytes(), f.before)

    def test_reconcile_retries_environment_durability_before_restart_ack(self):
        with tempfile.TemporaryDirectory() as directory:
            f = Fixture(directory)
            native = OP.sync_dir
            def failed(path):
                if path == f.env.parent:
                    raise OSError('environment directory fsync failed after rename')
                return native(path)
            with patch.object(OP, 'sync_dir', side_effect=failed), self.assertRaises(OSError):
                f.invoke('apply')
            self.assertNotEqual(f.env.read_bytes(), f.before)
            self.assertEqual(json.loads(f.marker.read_text())['phase'], 'prepared')
            with patch.object(OP, 'resync', side_effect=OSError('environment retry fsync failed')) as synced:
                with self.assertRaises(OSError):
                    f.invoke('reconcile')
                synced.assert_called_once_with(f.env)
            self.assertTrue(f.marker.exists())
            self.assertFalse(json.loads(f.marker.read_text())['pre_restart_original_verified'])
            with patch.object(OP, 'resync', wraps=OP.resync) as synced:
                f.invoke('reconcile')
                synced.assert_called_once_with(f.env)
            self.assertTrue(json.loads(f.marker.read_text())['pre_restart_original_verified'])

    def test_rollback_retries_matching_original_durability_before_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            f = Fixture(directory)
            f.invoke('apply')
            native = OP.sync_dir
            def failed(path):
                if path == f.env.parent:
                    raise OSError('rollback environment directory fsync failed after rename')
                return native(path)
            with patch.object(OP, 'sync_dir', side_effect=failed), self.assertRaises(OSError):
                f.invoke('rollback')
            self.assertEqual(f.env.read_bytes(), f.before)
            self.assertTrue(f.marker.exists())
            self.assertFalse((f.report/'rolled-back.json').exists())
            with patch.object(OP, 'resync', side_effect=OSError('rollback retry fsync failed')) as synced:
                with self.assertRaises(OSError):
                    f.invoke('rollback')
                synced.assert_called_once_with(f.env)
            self.assertTrue(f.marker.exists())
            self.assertFalse((f.report/'rolled-back.json').exists())
            with patch.object(OP, 'resync', wraps=OP.resync) as synced:
                f.invoke('rollback')
                synced.assert_called_once_with(f.env)
            self.assertFalse(f.marker.exists())
            self.assertTrue((f.app/'backend-recovery-required').exists())

    def test_failed_existing_receipt_resync_never_unlinks_fence(self):
        with tempfile.TemporaryDirectory() as directory:
            f = Fixture(directory)
            f.invoke('apply')
            native = OP.persist
            def failed(path, value, **kwargs):
                native(path, value, **kwargs)
                if path.name == 'finalized.json':
                    raise OSError('receipt fsync acknowledgement lost')
            with patch.object(OP, 'persist', side_effect=failed), self.assertRaises(OSError):
                f.invoke('finalize', runtime=True)
            self.assertTrue(f.marker.exists())
            native_resync = OP.resync
            def failed_receipt_resync(path):
                if path == f.report/'finalized.json':
                    raise OSError('receipt retry fsync failure')
                return native_resync(path)
            with patch.object(OP, 'resync', side_effect=failed_receipt_resync) as synced:
                with self.assertRaisesRegex(OSError, 'receipt retry fsync failure'):
                    f.invoke('finalize', runtime=True)
                self.assertEqual([call.args[0] for call in synced.call_args_list],
                                 [f.env, f.report/'finalized.json'])
            self.assertTrue(f.marker.exists())
            f.invoke('finalize', runtime=True)
            self.assertFalse(f.marker.exists())

    def test_prepared_marker_fsync_failure_never_changes_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            f = Fixture(directory)
            native = OP.persist
            def failed(path, value, **kwargs):
                native(path, value, **kwargs)
                if path == f.marker:
                    raise OSError('prepared marker durability failed')
            with patch.object(OP, 'persist', side_effect=failed), self.assertRaises(OSError):
                f.invoke('apply')
            self.assertEqual(f.env.read_bytes(), f.before)
            self.assertTrue(f.marker.exists())
            f.invoke('rollback')

    def test_replacement_directory_fsync_ack_loss_recovers_exactly(self):
        with tempfile.TemporaryDirectory() as directory:
            f = Fixture(directory)
            native = OP.sync_dir
            def failed(path):
                if path == f.env.parent and f.env.read_bytes() != f.before:
                    raise OSError('replacement directory fsync failed')
                return native(path)
            with patch.object(OP, 'sync_dir', side_effect=failed), self.assertRaises(OSError):
                f.invoke('apply')
            self.assertEqual(json.loads(f.marker.read_text())['phase'], 'prepared')
            f.invoke('rollback')
            self.assertEqual(f.env.read_bytes(), f.before)

    def test_private_material_refuses_wrong_mode_and_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'private.json'
            OP.persist(path, {'fixture': True})
            path.chmod(0o644)
            with self.assertRaises(RuntimeError):
                OP.read_private(path)
            path.chmod(0o600)
            link = path.parent/'link'
            link.symlink_to(path)
            with self.assertRaises(OSError):
                OP.read_private(link)

    def test_optimized_cli_execution_refused_before_configuration_or_docker(self):
        result = subprocess.run([sys.executable, '-O', '-B', str(ROOT/'scripts/activate-shop-online.py'),
                                 'apply', '/nonexistent-proof', '1'], capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')
        self.assertIn('failed closed', result.stderr)

    def test_lock_owner_pending_release_and_pin_guards(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory)
            root = app/'releases/candidate'
            (root/'scripts').mkdir(parents=True)
            (app/'release.lock').mkdir()
            (app/'release.lock/pid').write_text(str(os.getppid()))
            (app/'env').mkdir()
            for name in ('backend', 'postgres'):
                OP.persist_bytes(app/('env/'+name+'.env'), b'FIXTURE=true\n')
            marker = app/'backend-recovery-required'
            marker.write_text('release='+str(root)+'\nphase=pending_acceptance\n')
            with patch.object(OP, 'APP', app), patch.object(OP, 'TOOLS', root.resolve()/'scripts'), \
                 patch.object(OP, 'pin_for', return_value=PIN), patch.object(os, 'kill') as probe, \
                 patch.dict(os.environ, EXPECTED_RELEASE=str(root), EXPECTED_BACKEND_IMAGE=PIN,
                            RELEASE_LOCK_OWNER_PID=str(os.getppid())):
                self.assertEqual(OP.release_context(), (root, PIN))
                probe.assert_called_once_with(os.getppid(), 0)
                with patch.dict(os.environ, RELEASE_LOCK_OWNER_PID='-1'), self.assertRaises(RuntimeError):
                    OP.release_context()
                with patch.dict(os.environ, EXPECTED_BACKEND_IMAGE=OLD), self.assertRaises(RuntimeError):
                    OP.release_context()
                marker.write_text('release='+str(root)+'\nphase=foreign\n')
                with self.assertRaises(RuntimeError):
                    OP.release_context()

    def test_timeout_and_cleanup_failure_never_replace_environment(self):
        for cleanup_failure in (False, True):
            with self.subTest(cleanup_failure=cleanup_failure), tempfile.TemporaryDirectory() as directory:
                f = Fixture(directory)
                f.fail = 'timeout'
                with patch.object(OP, 'quiesce', side_effect=RuntimeError('cleanup failed') if cleanup_failure else None) as cleanup:
                    with self.assertRaises((RuntimeError, subprocess.TimeoutExpired)):
                        f.invoke('apply')
                    cleanup.assert_called_once()
                self.assertEqual(f.env.read_bytes(), f.before)
                self.assertTrue((f.app/'backend-recovery-required').exists())

    def test_environment_parser_rejects_duplicate_export_and_missing_newline(self):
        for original in (b'X=1\nX=2\n', b'export SHOP_ONLINE_PAYMENT_ENABLED=false\n',
                         b'X=1', b'not an assignment\n'):
            with self.subTest(original=original), self.assertRaises(RuntimeError):
                OP.edit_env(original, CONFIG.plan(settings(), 1)['aliases'])

    def test_proof_requires_exact_fresh_bindings(self):
        now = datetime.now(timezone.utc)
        plan = CONFIG.plan(settings(), 1)
        proof = dict(schema_version=1, verified=True, merchant_get_requests=1,
            merchant_profile_sha256=plan['profile_sha256'], env_sha256='fixture',
            created_at=now.isoformat(), source_image=OLD)
        OP.validate_proof(proof, 'fixture', plan, OLD, now)
        for key, value in (('source_image', PIN), ('env_sha256', 'foreign'),
                           ('merchant_profile_sha256', 'foreign'), ('verified', False),
                           ('merchant_get_requests', True), ('schema_version', True),
                           ('created_at', (now-timedelta(hours=3)).isoformat()),
                           ('created_at', (now+timedelta(seconds=1)).isoformat())):
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                OP.validate_proof({**proof, key: value}, 'fixture', plan, OLD, now)

    def test_docker_boundaries_and_generated_sql_are_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            f = Fixture(directory)
            f.invoke('apply')
            for args, data in f.calls:
                if args[:2] == ['docker', 'run']:
                    for flag in ('--network=none', '--pull=never', '--memory=768m', '--cpus=1', '--pids-limit=128'):
                        self.assertIn(flag, args)
                    self.assertIn('BACKGROUND_WORKERS_ENABLED=false', args)
                    self.assertEqual(args[args.index('--user')+1], f'{os.geteuid()}:{os.getegid()}')
                    env_files = [args[i+1] for i, arg in enumerate(args) if arg == '--env-file']
                    self.assertEqual(env_files[0], str(f.app/'env/postgres.env'))
                    self.assertIn(env_files[1], (str(f.env), str(f.report/'after.env')))
                if args[:2] == ['docker', 'exec']:
                    self.assertIn('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;', data)
                    self.assertIn("''last_value'',last_value,''log_cnt'',log_cnt,''is_called'',is_called", data)
                    self.assertNotIn('to_jsonb(s)', data)
                    for write in ('UPDATE ', 'DELETE ', 'INSERT ', 'CREATE ', 'ALTER '):
                        self.assertNotIn(write, data)
                    self.assertIn('NOT EXISTS(SELECT 1 FROM masters', data)
                    self.assertIn('a.is_active AND (a.is_superuser OR a.can_record_sales)', data)
