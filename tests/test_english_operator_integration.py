"""Operator main with real private files and controlled Docker responses; no PG."""
from contextlib import ExitStack, redirect_stdout
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


OP = load('english_operator_protocol', 'apply-english-backfill.py')
DB = load('english_operator_protocol_db', 'english-backfill-db.py')
PIN = 'ghcr.io/mharnichev/sc-be/api@sha256:' + 'a' * 64
FILES = {'products': 'prod-all-names-en.json', 'categories': 'prod-all-category-names-en.json'}


class EnglishOperatorMainTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='english-operator-protocol-')
        self.addCleanup(self.temp.cleanup)
        self.app = Path(self.temp.name)
        self.release = self.app / 'releases' / 'candidate'
        (self.release / 'scripts').mkdir(parents=True)
        # Exercise the real input sealer, including private modes and fsyncs.
        (self.release / 'scripts' / 'rehearse-shop-production-copy.py').write_bytes(
            (ROOT / 'scripts' / 'rehearse-shop-production-copy.py').read_bytes())
        (self.app / 'backups').mkdir()
        (self.app / 'env').mkdir()
        self.envfile = self.app / 'env' / 'backend.env'
        self.envfile.write_bytes(b'UNCHANGED=fixture\n')
        self.envfile.chmod(0o600)
        (self.app / 'release.lock').mkdir()
        (self.app / 'release.lock' / 'pid').write_text(str(os.getppid()))
        self.backend = self.app / 'backend-recovery-required'
        self.backend.write_text(f'release={self.release}\nphase=pending_acceptance\n')
        self.marker = self.app / 'english-backfill-required'
        self.inputs = self.app / 'backups' / 'reviewed'
        self.inputs.mkdir(mode=0o700)
        self.hashes = {}
        catalog, english = {}, {}
        for table, count in (('products', 552), ('categories', 44)):
            items, originals = [], []
            for identifier in range(1, count + 1):
                item = dict(id=identifier, name_original=f'Original {identifier}',
                            slug=f'{table}-{identifier}', name_en=f'English {identifier}')
                original = dict(id=identifier, name=item['name_original'], slug=item['slug'])
                if table == 'products':
                    item['product_type_en'] = 'Hair care'
                    original['product_type'] = 'Original type'
                else:
                    item['parent_id'] = None if identifier == 1 else 1
                    original['parent_id'] = item['parent_id']
                items.append(item)
                originals.append(original)
            path = self.inputs / FILES[table]
            data = json.dumps({'count': count, table: items}).encode()
            path.write_bytes(data)
            path.chmod(0o600)
            self.hashes[table] = hashlib.sha256(data).hexdigest()
            catalog[table] = originals
            english[table] = [dict(id=row['id'], **dict.fromkeys(OP.FIELDS[table])) for row in items]
        self.database = dict(head=OP.HEAD, database_identity={'database': 'fixture', 'role': 'fixture'},
                             inventory=['all-original-and-English-columns'],
                             fingerprints={'products': 'original-products', 'categories': 'original-categories',
                                           'unrelated': 'protected-row'},
                             sequences={'products_id_seq': {'last_value': 552, 'is_called': True}},
                             catalog=catalog, english=english)
        self.baseline = deepcopy(self.database)
        self.target = OP.targets_from_inputs(self.inputs, self.baseline)
        self.running = False
        self.active_tasks = set()
        self.calls, self.events = [], []
        self.fail_ack = None
        self.hang = None
        self.cleanup_fails = False
        self.report_root = None
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(OP, 'APP', self.app))
        self.stack.enter_context(patch.object(OP, 'ENV', self.envfile))
        self.stack.enter_context(patch.object(OP, 'MARKER', self.marker))
        self.stack.enter_context(patch.object(OP, 'run', side_effect=self.docker))
        self.stack.enter_context(patch.dict(os.environ, {
            'EXPECTED_RELEASE': str(self.release), 'EXPECTED_BACKEND_IMAGE': PIN,
            'RELEASE_LOCK_OWNER_PID': str(os.getppid()), 'ENGLISH_RUNTIME_VERIFIED': 'true',
        }))
        old_umask = os.umask(0o077)
        self.addCleanup(os.umask, old_umask)

    def invoke(self, mode):
        argv = ['operator', mode]
        if mode == 'apply':
            argv += [str(self.inputs), self.hashes['products'], self.hashes['categories']]
        else:
            argv += [str(self.report_root)]
        output = io.StringIO()
        with patch.object(OP.sys, 'argv', argv), redirect_stdout(output):
            OP.main()
        return json.loads(output.getvalue().splitlines()[-1])

    def state(self):
        return OP.private_json(self.marker)

    def assert_fences(self):
        self.assertTrue(self.backend.exists())
        self.assertTrue(self.marker.exists())

    def database_operation(self, mode, payload):
        owner = self

        class Connection:
            def execute(self, sql, values=None):
                if sql.startswith('UPDATE '):
                    table = sql.split()[1]
                    owner.database['english'][table] = json.loads(values['rows'])
                elif not sql.startswith(('SET ', 'LOCK TABLE ')):
                    raise AssertionError('Unexpected mocked SQL: ' + sql)

        # Real DB-helper validation/CAS/control flow, but snapshot and SQL effects
        # are modeled here. Transaction/driver behavior requires the PG suite.
        before = deepcopy(self.database)
        try:
            with patch.object(DB, 'snapshot', side_effect=lambda *_: deepcopy(self.database)):
                return DB.operate(Connection(), lambda sql: sql, mode, payload)
        except BaseException:
            self.database = before
            raise

    def docker(self, args, *, data=None, env=None, timeout=120):
        self.calls.append(list(args))
        if args[0] == 'python3':
            self.assertEqual(args[1:], [str(self.release / 'scripts' / 'release-backend-pin.py'),
                                        str(self.release / 'versions' / 'production.env')])
            return PIN
        self.assertEqual(args[0], 'docker')
        if args[1] == 'inspect':
            return str(self.running).lower() if args[3] == '{{.State.Running}}' else PIN
        if args[1] == 'stop':
            if self.cleanup_fails:
                raise RuntimeError('Injected task cleanup failure')
            self.active_tasks.discard(args[-1])
            self.events.append(('stop', args[-1]))
            return ''
        if args[1] == 'ps':
            filters = [args[i + 1] for i, arg in enumerate(args) if arg == '--filter']
            named = next((value[7:-1] for value in filters if value.startswith('name=^/')), None)
            if named is not None:
                return named if named in self.active_tasks else ''
            if '--format' in args:
                return '\n'.join(sorted(self.active_tasks))
            service = next(value.split('=', 2)[-1] for value in filters
                           if value.startswith('label=com.docker.compose.service='))
            return service + '-id'
        self.assertEqual(args[1], 'run')
        name = args[args.index('--name') + 1]
        self.active_tasks.add(name)
        self.report_root = self.app / 'backups' / name[:len('english-catalog-') + 24]
        step = name[len(self.report_root.name) + 1:]
        self.events.append(('task', step))
        self.assertEqual(args[args.index('--network') + 1], 'container:postgres-id')
        self.assertIn('--memory=768m', args)
        self.assertIn('--cpus=1', args)
        self.assertIn('--pids-limit=128', args)
        self.assertEqual(args[args.index('--user') + 1], f'{os.geteuid()}:{os.getegid()}')
        self.assertIn('--pull=never', args)
        self.assertEqual(env['BACKEND_IMAGE'], PIN)
        self.assertEqual(env['BACKEND_ENV_FILE'], str(self.envfile))
        self.assertIn(PIN, args)
        if self.hang == step:
            self.hang = None
            raise TimeoutError('Injected Docker timeout with surviving task')
        if '-m' in args:
            table = 'products' if 'product_names_en' in args[args.index('-m') + 1] else 'categories'
            phase = step[len(table) + 1:]
            if phase == 'apply':
                self.assert_fences()
                state = self.state()
                self.assertEqual(state['phase'], 'executing-' + step)
                self.assertIn(name, state['tasks'])
                self.assertEqual(state['snapshot_sha256'], OP.checksum(self.report_root / 'snapshot.json'))
            updated = sum(old != new for old, new in zip(self.database['english'][table], self.target[table]))
            report = dict(status='prepared_apply' if phase == 'apply' else 'dry_run',
                          input_sha256=self.hashes[table], count=len(self.target[table]))
            OP.persist(self.report_root / 'reports' / (table + '-' + phase + '.json'), report)
            if phase == 'apply':
                self.database['english'][table] = deepcopy(self.target[table])
                self.events.append(('commit', table))
            result = dict(status='committed' if phase == 'apply' else 'dry_run',
                          count=len(self.target[table]), updated=updated, unchanged=len(self.target[table]) - updated)
        else:
            self.assertIn('/release-tools/scripts/english-backfill-db.py', args)
            result = self.database_operation(args[-1], {} if data is None else json.loads(data))
        self.active_tasks.remove(name)
        if self.fail_ack == step:
            self.fail_ack = None
            raise RuntimeError('Injected lost task acknowledgement')
        return json.dumps(result)

    def test_apply_finalize_and_idempotent_receipt_preserve_provenance(self):
        self.assertTrue(self.invoke('apply')['applied'])
        self.assertEqual(self.database['english'], self.target)
        DB.verify_original(self.database, self.baseline)
        self.assert_fences()
        self.assertTrue(self.state()['pre_restart_original_verified'])
        self.assertEqual([step for event, step in self.events if event == 'task'], [
            'snapshot', 'products-dry-run', 'categories-dry-run', 'products-apply',
            'categories-apply', 'products-idempotent', 'categories-idempotent', 'verify-original'])
        self.running = True
        self.assertTrue(self.invoke('finalize')['accepted'])
        receipt = self.report_root / 'finalized.json'
        original = receipt.read_bytes()
        self.assertTrue(OP.private_json(receipt)['accepted'])
        self.assertFalse(self.marker.exists())
        self.assertTrue(self.backend.exists())
        self.assertTrue(self.invoke('finalize')['accepted'])
        self.assertEqual(receipt.read_bytes(), original)
        self.assertEqual(sum(event == 'commit' for event, _ in self.events), 2)

    def test_partial_product_commit_lost_ack_rolls_back_both_vectors(self):
        self.fail_ack = 'products-apply'
        with self.assertRaisesRegex(RuntimeError, 'lost task acknowledgement'):
            self.invoke('apply')
        self.assert_fences()
        self.assertEqual(self.database['english']['products'], self.target['products'])
        self.assertEqual(self.database['english']['categories'], self.baseline['english']['categories'])
        self.assertTrue(self.invoke('rollback')['rolled_back'])
        self.assertEqual(self.database, self.baseline)
        self.assertFalse(self.marker.exists())
        self.assertTrue(self.backend.exists())

    def test_already_translated_baseline_is_a_safe_noop_apply(self):
        self.database['english'] = deepcopy(self.target)
        result = self.invoke('apply')
        self.assertEqual([result['results'][table]['updated'] for table in OP.FIELDS], [0, 0])
        self.assertEqual(self.database['english'], self.target)
        self.assert_fences()
        self.assertTrue(self.invoke('rollback')['rolled_back'])
        self.assertEqual(self.database['english'], self.target)

    def test_source_parent_drift_before_planning_never_reaches_apply(self):
        self.database['catalog']['categories'][1]['parent_id'] = None
        before = deepcopy(self.database)
        with self.assertRaisesRegex(RuntimeError, 'hierarchy changed'):
            self.invoke('apply')
        self.assertEqual(self.database, before)
        self.assertFalse(any(event == 'commit' for event, _ in self.events))
        self.assertFalse(self.marker.exists())
        self.assertTrue(self.backend.exists())

    def test_both_commits_lost_ack_reconcile_without_another_apply(self):
        self.fail_ack = 'categories-apply'
        with self.assertRaisesRegex(RuntimeError, 'lost task acknowledgement'):
            self.invoke('apply')
        self.assertTrue(self.invoke('reconcile')['reconciled'])
        self.assertEqual(self.database['english'], self.target)
        self.assertEqual(self.state()['phase'], 'verified')
        self.assertEqual(sum(event == 'commit' for event, _ in self.events), 2)
        self.assert_fences()

    def test_source_drift_refuses_rollback_without_partial_restoration(self):
        self.invoke('apply')
        self.database['catalog']['categories'][0]['parent_id'] = 7
        before = deepcopy(self.database)
        with self.assertRaisesRegex(RuntimeError, 'provenance changed: catalog'):
            self.invoke('rollback')
        self.assertEqual(self.database, before)
        self.assert_fences()

    def test_original_unrelated_row_drift_blocks_reconciliation(self):
        self.fail_ack = 'categories-apply'
        with self.assertRaises(RuntimeError):
            self.invoke('apply')
        self.database['fingerprints']['unrelated'] = 'foreign edit'
        with self.assertRaisesRegex(RuntimeError, 'provenance changed: fingerprints'):
            self.invoke('reconcile')
        self.assert_fences()

    def test_mixed_english_vector_refuses_entire_rollback(self):
        self.invoke('apply')
        self.database['english']['categories'][0]['name_en'] = None
        before = deepcopy(self.database)
        with self.assertRaisesRegex(RuntimeError, 'mixed or foreign'):
            self.invoke('rollback')
        self.assertEqual(self.database, before)
        self.assert_fences()

    def test_environment_drift_refuses_before_any_database_task(self):
        self.invoke('apply')
        self.envfile.write_bytes(b'UNCHANGED=foreign-edit\n')
        tasks_before = len(self.events)
        with self.assertRaisesRegex(RuntimeError, 'Environment drift'):
            self.invoke('rollback')
        self.assertEqual(len(self.events), tasks_before)
        self.assert_fences()

    def test_snapshot_tampering_refuses_before_database_task(self):
        self.invoke('apply')
        (self.report_root / 'snapshot.json').write_bytes(b'{}')
        tasks_before = len(self.events)
        with self.assertRaises(RuntimeError):
            self.invoke('rollback')
        self.assertEqual(len(self.events), tasks_before)
        self.assert_fences()

    def test_prepared_marker_directory_fsync_failure_precedes_all_updates(self):
        native = OP.sync_dir

        def fail_prepared(path):
            if path == self.app and self.marker.exists():
                raise OSError('Injected marker directory fsync failure')
            return native(path)

        with patch.object(OP, 'sync_dir', side_effect=fail_prepared):
            with self.assertRaisesRegex(OSError, 'directory fsync'):
                self.invoke('apply')
        self.assertEqual(self.database, self.baseline)
        self.assertFalse(any(event == 'commit' for event, _ in self.events))
        self.assert_fences()

    def test_snapshot_file_fsync_failure_does_not_start_applies(self):
        native = OP.persist

        def fail_snapshot(path, value, **kwargs):
            if path.name == 'snapshot.json':
                with patch.object(OP.os, 'fsync', side_effect=OSError('Injected file fsync failure')):
                    return native(path, value, **kwargs)
            return native(path, value, **kwargs)

        with patch.object(OP, 'persist', side_effect=fail_snapshot):
            with self.assertRaisesRegex(OSError, 'file fsync'):
                self.invoke('apply')
        self.assertEqual(self.database, self.baseline)
        self.assertFalse(self.marker.exists())
        self.assertTrue(self.backend.exists())

    def test_timeout_cleanup_failure_retains_fences_and_blocks_recovery(self):
        self.hang = 'products-apply'
        self.cleanup_fails = True
        with self.assertRaisesRegex(RuntimeError, 'cleanup failure'):
            self.invoke('apply')
        self.assertTrue(self.active_tasks)
        self.assert_fences()
        with self.assertRaisesRegex(RuntimeError, 'cleanup failure'):
            self.invoke('rollback')
        self.assertEqual(self.database, self.baseline)
        self.cleanup_fails = False
        self.assertTrue(self.invoke('rollback')['rolled_back'])
        self.assertFalse(self.active_tasks)

    def test_receipt_before_marker_unlink_failure_is_retried_without_reapply(self):
        self.invoke('apply')
        self.running = True
        native = Path.unlink

        def fail_unlink(path, *args, **kwargs):
            if path == self.marker:
                raise OSError('Injected marker unlink failure')
            return native(path, *args, **kwargs)

        with patch.object(Path, 'unlink', fail_unlink):
            with self.assertRaisesRegex(OSError, 'unlink failure'):
                self.invoke('finalize')
        receipt = (self.report_root / 'finalized.json').read_bytes()
        self.assert_fences()
        self.assertTrue(self.invoke('finalize')['accepted'])
        self.assertEqual((self.report_root / 'finalized.json').read_bytes(), receipt)
        self.assertEqual(sum(event == 'commit' for event, _ in self.events), 2)

    def test_lost_finalize_ack_recovers_from_receipt_only_with_fresh_live_check(self):
        self.invoke('apply')
        self.running = True
        native = OP.sync_dir

        def fail_after_unlink(path):
            if path == self.app and not self.marker.exists():
                raise OSError('Injected lost finalization acknowledgement')
            return native(path)

        with patch.object(OP, 'sync_dir', side_effect=fail_after_unlink):
            with self.assertRaisesRegex(OSError, 'finalization acknowledgement'):
                self.invoke('finalize')
        self.assertFalse(self.marker.exists())
        self.assertTrue(self.backend.exists())
        receipt = (self.report_root / 'finalized.json').read_bytes()
        self.running = False
        self.assertTrue(self.invoke('recover-finalize')['finalization_reconciled'])
        self.assertEqual(self.events[-1], ('task', 'recover-finalize'))
        self.assertFalse(self.marker.exists())
        self.running = True
        self.assertTrue(self.invoke('finalize')['accepted'])
        self.assertEqual((self.report_root / 'finalized.json').read_bytes(), receipt)
        self.assertEqual(sum(event == 'commit' for event, _ in self.events), 2)

    def test_receipt_only_source_drift_refuses_live_recovery(self):
        self.invoke('apply')
        self.running = True
        self.invoke('finalize')
        self.running = False
        self.database['catalog']['products'][0]['name'] = 'Foreign edit'
        with self.assertRaisesRegex(RuntimeError, 'source identity changed'):
            self.invoke('recover-finalize')
        self.assertTrue((self.report_root / 'finalized.json').exists())
        self.assertTrue(self.backend.exists())
        self.assertFalse(self.marker.exists())

    def test_recover_finalize_requires_durable_pre_restart_original_verification(self):
        self.fail_ack = 'categories-apply'
        with self.assertRaises(RuntimeError):
            self.invoke('apply')
        self.assertNotIn('pre_restart_original_verified', self.state())
        self.assertEqual(self.database['english'], self.target)
        tasks_before = len(self.events)
        with self.assertRaises(RuntimeError):
            self.invoke('recover-finalize')
        self.assertEqual(len(self.events), tasks_before)
        self.assert_fences()

    def test_receipt_only_provenance_mismatch_is_rejected_before_database_task(self):
        self.invoke('apply')
        self.running = True
        self.invoke('finalize')
        receipt_path = self.report_root / 'finalized.json'
        receipt = OP.private_json(receipt_path)
        receipt['state']['image'] = PIN.replace('a' * 64, 'b' * 64)
        OP.persist(receipt_path, receipt, replace=True)
        self.running = False
        tasks_before = len(self.events)
        with self.assertRaises(RuntimeError):
            self.invoke('recover-finalize')
        self.assertEqual(len(self.events), tasks_before)
        self.assertTrue(self.backend.exists())
        self.assertFalse(self.marker.exists())

    def test_failed_receipt_file_fsync_must_be_reestablished_before_retry_unlinks_fence(self):
        self.invoke('apply')
        self.running = True
        receipt = self.report_root / 'finalized.json'
        native = OP.os.fsync

        def receipt_fd(fd):
            return receipt.exists() and os.fstat(fd).st_ino == receipt.stat().st_ino

        def fail_receipt(fd):
            if receipt_fd(fd):
                raise OSError('Injected receipt file fsync failure')
            return native(fd)

        with patch.object(OP.os, 'fsync', side_effect=fail_receipt):
            with self.assertRaisesRegex(OSError, 'receipt file fsync'):
                self.invoke('finalize')
        self.assert_fences()
        self.assertTrue(OP.private_json(receipt)['accepted'])
        synced = []

        def observe(fd):
            if receipt_fd(fd):
                synced.append(True)
            return native(fd)

        with patch.object(OP.os, 'fsync', side_effect=observe):
            self.invoke('finalize')
        self.assertTrue(synced, 'Retry removed the fence without re-fsyncing the previously failed receipt')

    def test_failed_receipt_directory_fsync_must_be_reestablished_before_retry_unlinks_fence(self):
        self.invoke('apply')
        self.running = True
        receipt = self.report_root / 'finalized.json'
        native = OP.sync_dir

        def fail_receipt_directory(path):
            if path == self.report_root and receipt.exists():
                raise OSError('Injected receipt directory fsync failure')
            return native(path)

        with patch.object(OP, 'sync_dir', side_effect=fail_receipt_directory):
            with self.assertRaisesRegex(OSError, 'receipt directory fsync'):
                self.invoke('finalize')
        self.assert_fences()
        original = receipt.read_bytes()
        synced = []

        def observe(path):
            if path == self.report_root:
                synced.append(True)
            return native(path)

        with patch.object(OP, 'sync_dir', side_effect=observe):
            self.invoke('finalize')
        self.assertEqual(receipt.read_bytes(), original)
        self.assertTrue(synced, 'Retry removed the fence without re-fsyncing the receipt directory')

    def test_apply_env_drift_from_each_task_callback_blocks_remaining_flow(self):
        steps = ['snapshot', 'products-dry-run', 'categories-dry-run', 'products-apply',
                 'categories-apply', 'products-idempotent', 'categories-idempotent', 'verify-original']
        for index, step in enumerate(steps):
            with self.subTest(step=step):
                case = EnglishOperatorMainTests('test_apply_finalize_and_idempotent_receipt_preserve_provenance')
                case.setUp()
                try:
                    native = case.docker
                    injected = []

                    def drift_after_task(args, **kwargs):
                        result = native(args, **kwargs)
                        if args[:2] == ['docker', 'run'] and args[args.index('--name') + 1].endswith('-' + step):
                            case.envfile.write_bytes(b'UNCHANGED=drift-during-task\n')
                            injected.append(step)
                        return result

                    OP.run.side_effect = drift_after_task
                    with self.assertRaisesRegex(RuntimeError, 'Environment drift'):
                        case.invoke('apply')
                    self.assertEqual(injected, [step])
                    self.assertEqual([value for event, value in case.events if event == 'task'], steps[:index + 1])
                    commits = sum(value in ('products-apply', 'categories-apply') for value in steps[:index + 1])
                    self.assertEqual(sum(event == 'commit' for event, _ in case.events), commits)
                    self.assertTrue(case.backend.exists())
                    self.assertFalse(case.running)
                    self.assertFalse(case.active_tasks)
                    if commits:
                        case.assert_fences()
                        self.assertIsNot(case.state().get('pre_restart_original_verified'), True)
                        self.assertNotEqual(case.state()['env_sha256'], OP.checksum(case.envfile))
                    else:
                        self.assertFalse(case.marker.exists())
                        self.assertEqual(case.database, case.baseline)
                    self.assertFalse((case.report_root / 'finalized.json').exists())
                finally:
                    case.doCleanups()

    def test_env_drift_after_prepared_fsync_blocks_first_apply_and_keeps_fences(self):
        native = OP.persist
        injected = []

        def drift_after_prepared(path, value, **kwargs):
            result = native(path, value, **kwargs)
            if path == self.marker and value['phase'] == 'prepared':
                self.envfile.write_bytes(b'UNCHANGED=drift-before-first-apply\n')
                injected.append(True)
            return result

        with patch.object(OP, 'persist', side_effect=drift_after_prepared):
            with self.assertRaisesRegex(RuntimeError, 'Environment drift'):
                self.invoke('apply')
        self.assertEqual(injected, [True])
        self.assertEqual([step for event, step in self.events if event == 'task'],
                         ['snapshot', 'products-dry-run', 'categories-dry-run'])
        self.assertEqual(self.database, self.baseline)
        self.assertFalse(any(event == 'commit' for event, _ in self.events))
        self.assertFalse(self.active_tasks)
        self.assertFalse(self.running)
        self.assert_fences()
        self.assertEqual(self.state()['phase'], 'prepared')
        self.assertNotIn('pre_restart_original_verified', self.state())

    def test_reconcile_env_drift_after_last_verify_never_authorizes_restart(self):
        self.fail_ack = 'categories-apply'
        with self.assertRaisesRegex(RuntimeError, 'lost task acknowledgement'):
            self.invoke('apply')
        native = self.docker
        injected = []

        def drift_after_verify(args, **kwargs):
            result = native(args, **kwargs)
            if args[:2] == ['docker', 'run'] and args[args.index('--name') + 1].endswith('-reconcile'):
                self.envfile.write_bytes(b'UNCHANGED=drift-after-reconcile-verify\n')
                injected.append(True)
            return result

        OP.run.side_effect = drift_after_verify
        with self.assertRaisesRegex(RuntimeError, 'Environment drift'):
            self.invoke('reconcile')
        self.assertEqual(injected, [True])
        self.assertEqual(self.database['english'], self.target)
        self.assertEqual(sum(event == 'commit' for event, _ in self.events), 2)
        self.assertNotIn('pre_restart_original_verified', self.state())
        self.assertEqual(self.state()['phase'], 'executing-reconcile')
        self.assertFalse(self.running)
        self.assertFalse(self.active_tasks)
        self.assert_fences()

    def test_recover_finalize_env_drift_after_last_verify_retains_marker(self):
        self.invoke('apply')
        native = self.docker
        injected = []

        def drift_after_verify(args, **kwargs):
            result = native(args, **kwargs)
            if args[:2] == ['docker', 'run'] and args[args.index('--name') + 1].endswith('-recover-finalize'):
                self.envfile.write_bytes(b'UNCHANGED=drift-after-recover-verify\n')
                injected.append(True)
            return result

        OP.run.side_effect = drift_after_verify
        with self.assertRaisesRegex(RuntimeError, 'Environment drift'):
            self.invoke('recover-finalize')
        self.assertEqual(injected, [True])
        self.assertEqual(self.state()['phase'], 'executing-recover-finalize')
        self.assertEqual(self.database['english'], self.target)
        self.assertEqual(sum(event == 'commit' for event, _ in self.events), 2)
        self.assertFalse((self.report_root / 'finalized.json').exists())
        self.assertFalse(self.active_tasks)
        self.assertFalse(self.running)
        self.assert_fences()

    def test_receipt_only_recovery_env_drift_after_last_verify_preserves_receipt(self):
        self.invoke('apply')
        self.running = True
        self.invoke('finalize')
        self.running = False
        receipt = self.report_root / 'finalized.json'
        original = receipt.read_bytes()
        native = self.docker
        injected = []

        def drift_after_verify(args, **kwargs):
            result = native(args, **kwargs)
            if args[:2] == ['docker', 'run'] and args[args.index('--name') + 1].endswith('-recover-finalize'):
                self.envfile.write_bytes(b'UNCHANGED=drift-after-receipt-recovery-verify\n')
                injected.append(True)
            return result

        OP.run.side_effect = drift_after_verify
        with self.assertRaisesRegex(RuntimeError, 'Environment drift'):
            self.invoke('recover-finalize')
        self.assertEqual(injected, [True])
        self.assertEqual(receipt.read_bytes(), original)
        self.assertTrue(OP.private_json(receipt)['accepted'])
        self.assertFalse(self.marker.exists())
        self.assertTrue(self.backend.exists())
        self.assertFalse(self.running)
        self.assertFalse(self.active_tasks)
        self.assertEqual(sum(event == 'commit' for event, _ in self.events), 2)

    def test_finalize_env_drift_after_live_verify_preserves_acceptance_fence(self):
        self.invoke('apply')
        self.running = True
        native = self.docker
        injected = []

        def drift_after_verify(args, **kwargs):
            result = native(args, **kwargs)
            if args[:2] == ['docker', 'run'] and args[args.index('--name') + 1].endswith('-verify-live'):
                self.envfile.write_bytes(b'UNCHANGED=drift-before-finalize-receipt\n')
                injected.append(True)
            return result

        OP.run.side_effect = drift_after_verify
        with self.assertRaises(RuntimeError):
            self.invoke('finalize')
        self.assertEqual(injected, [True])
        self.assertFalse((self.report_root / 'finalized.json').exists())
        self.assertFalse(self.active_tasks)
        self.assert_fences()


if __name__ == '__main__':
    unittest.main()
