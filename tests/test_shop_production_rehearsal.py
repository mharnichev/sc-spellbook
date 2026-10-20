import importlib.util
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/rehearse-shop-production-copy.py'
SPEC = importlib.util.spec_from_file_location('rehearsal', SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class RehearsalTests(unittest.TestCase):
    def test_current_english_baseline_is_a_supported_payment_source(self):
        calls,error,reported,output=self.exercise(source_head='0136_category_names_en')
        self.assertIsNone(error)
        self.assertTrue(reported)
        self.assertIn('"result": "passed"',output)
        self.assertTrue(any(call[-2:]==['upgrade','head'] for call in calls))

    def test_dump_guard_only_removes_a_paired_top_level_guard(self):
        self.assertEqual(MODULE.strip_dump_guard(b'-- dump\n\\restrict Ab123\nCREATE TABLE x();\n\\unrestrict Ab123\n'),
                         b'-- dump\nCREATE TABLE x();\n')
        self.assertEqual(MODULE.strip_dump_guard(b'CREATE TABLE x();\n'), b'CREATE TABLE x();\n')

    def test_non_guard_function_bytes_and_line_endings_are_preserved(self):
        a = b'\\restrict Key\nCREATE FUNCTION f() AS $$a\r\nb$$;\n\\unrestrict Key\n'
        b = a.replace(b'\r\n', b'\n')
        self.assertNotEqual(MODULE.strip_dump_guard(a), MODULE.strip_dump_guard(b))

    def test_dump_guard_rejects_mismatch_or_embedded_guard(self):
        for data in (b'\\restrict Ab123\nDDL\n\\unrestrict Different',
                     b'\\restrict Ab123\nDDL',
                     b'\\restrict Ab123\nBODY\n\\restrict Embedded\n\\unrestrict Ab123'):
            with self.subTest(data=data), self.assertRaises(RuntimeError):
                MODULE.strip_dump_guard(data)

    def test_finite_constraint_rewrite_requires_exact_object_and_line(self):
        pair = dict(kind='constraint', table='example', name='ck_example')
        MODULE.verify_raw_schema(b'    CONSTRAINT ck_example CHECK (old),',
                                 b'    CONSTRAINT ck_example CHECK (new),', [pair],
                                 {'example:ck_example': 'CHECK (old)'}, {'example:ck_example': 'CHECK (new)'}, {}, {})

    def test_finite_contract_never_hides_other_ddl_changes(self):
        pair = dict(kind='constraint', table='example', name='ck_example')
        with self.assertRaisesRegex(RuntimeError, 'Unrecognized raw schema'):
            MODULE.verify_raw_schema(b'    CONSTRAINT ck_example CHECK (old),\nCREATE TABLE protected(id integer);',
                                     b'    CONSTRAINT ck_example CHECK (new),\nCREATE TABLE protected(id text);', [pair],
                                     {'example:ck_example': 'CHECK (old)'}, {'example:ck_example': 'CHECK (new)'}, {}, {})

    def test_finite_contract_rejects_unrecognized_line_and_duplicate_objects(self):
        pair = dict(kind='index', name='ix_example')
        for before in (b'UNKNOWN INDEX;', b'CREATE INDEX old;\nCREATE INDEX old;'):
            with self.subTest(before=before), self.assertRaises(RuntimeError):
                MODULE.verify_raw_schema(before, b'CREATE INDEX new;', [pair], {}, {},
                                         {'ix_example': 'CREATE INDEX old'}, {'ix_example': 'CREATE INDEX new'})

    def test_empty_finite_allowlist_cannot_accept_a_schema_difference(self):
        with self.assertRaises(RuntimeError):
            MODULE.verify_raw_schema(b'CREATE TABLE x(id integer);', b'CREATE TABLE x(id text);', [], {}, {}, {}, {})

    def exercise(self, *, stop_fails=False, row_drift=False, no_space=False,
                 source_head=None, restored_head=None, locale='en_US.utf8',
                 english=False, english_row_drift=False, english_cli_failure=None,
                 observed=None):
        expected_head = source_head or ('0134_shop_canonical_collation' if english else MODULE.BASE)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'backups').mkdir()
            calls, migrated, fingerprints = [], False, 0
            english_calls, fingerprint_queries = [], []
            inputs = root / 'backups' / 'input-fixture'
            hashes, input_bytes = {}, {}
            if english:
                inputs.mkdir(mode=0o700)
                for kind, name, _, count in MODULE.ENGLISH_INPUTS:
                    data = json.dumps(dict(count=count, **{kind: [dict(id=i) for i in range(count)]})).encode()
                    (inputs / name).write_bytes(data)
                    (inputs / name).chmod(0o600)
                    hashes[kind] = hashlib.sha256(data).hexdigest()
                    input_bytes[name] = data
            original_tables = ({'products': ['id', 'name', 'stock_quantity'],
                                'categories': ['id', 'name', 'parent_id']} if english else {'customers': ['id']})
            upgraded_tables = dict(original_tables)
            if english:
                upgraded_tables = {'products': original_tables['products'] + ['name_en', 'product_type_en'],
                                   'categories': original_tables['categories'] + ['name_en'],
                                   'alembic_version': ['version_num']}

            def fake_path(value):
                if value == '/opt/soulcuts/backups':
                    return root / 'backups'
                if value == '/opt/soulcuts/backups/input-fixture':
                    return inputs
                if value == '/proc/meminfo':
                    return SimpleNamespace(read_text=lambda: 'MemAvailable: 16000000 kB\n')
                return Path(value)

            def run(command, **kwargs):
                nonlocal migrated, fingerprints
                calls.append(command)
                value, status = b'', 0
                if command[:3] == ['docker', 'exec', 'soulcuts-postgres-1']:
                    if 'pg_database_size' in command[-1]:
                        value = b'16000000\n'
                    else:
                        self.assertIn('pg_dump', command[-1])
                        kwargs['stdout'].write(b'PGDMP synthetic only')
                elif 'psql' in command:
                    query = kwargs['input'].decode()
                    if query == MODULE.ENGLISH_COUNTS_SQL:
                        value = b'{"products":552,"categories":44}'
                    elif query == MODULE.SCHEMA_SQL:
                        value = b'{"unvalidated_constraints":0,"invalid_indexes":0,"indexes":[]}'
                    elif 'pg_get_constraintdef(oid,false)' in query:
                        value = b'{}'
                    elif query == 'SELECT version_num FROM alembic_version':
                        value = (MODULE.HEAD if migrated else (restored_head or expected_head)).encode()
                    elif query in ('SELECT datcollate FROM pg_database WHERE datname=current_database()',
                                   'SELECT datctype FROM pg_database WHERE datname=current_database()'):
                        value = locale.encode()
                    elif 'json_object_agg' in query:
                        tables = original_tables if "table_name <> 'alembic_version'" in query else upgraded_tables
                        value = json.dumps(tables).encode()
                    elif 'json_agg(s ORDER BY name)' in query:
                        fingerprints += 1
                        database = command[command.index('-d') + 1]
                        fingerprint_queries.append((database, query))
                        changed = (row_drift and fingerprints == 2) or (english_row_drift and fingerprints == 3)
                        digest = 'changed' if changed else 'with-english' if '"name_en"' in query else 'same'
                        value = json.dumps([dict(name=table, rows=1, digest=digest)
                                            for table in sorted(upgraded_tables if '"name_en"' in query else original_tables)]).encode()
                    elif 'pg_sequences' in query:
                        value = b'["customers_id_seq"]'
                    elif 'last_value,is_called' in query:
                        value = b'10|t'
                    else:
                        self.assertIn('CREATE DATABASE restore_copy', query)
                elif command[:2] == ['docker', 'run'] and command[-2:] == ['upgrade', 'head']:
                    migrated = True
                elif command[:2] == ['docker', 'run'] and '-m' in command:
                    self.assertTrue(english)
                    self.assertTrue(migrated)
                    module = command[command.index('-m') + 1]
                    kind, name, _, count = next(item for item in MODULE.ENGLISH_INPUTS if item[2] == module)
                    report_name = command[command.index('--report') + 1].split('/')[-1]
                    phase = report_name.removeprefix(kind + '-').removesuffix('.json')
                    english_calls.append((kind, phase))
                    self.assertEqual(command[command.index('--input') + 1], '/reviewed-inputs/' + name)
                    mounts = [command[i + 1] for i, arg in enumerate(command) if arg == '-v']
                    sealed = Path(next(mount.split(':')[0] for mount in mounts if mount.endswith(':/reviewed-inputs:ro')))
                    reports = Path(next(mount.split(':')[0] for mount in mounts if mount.endswith(':/rehearsal-reports:rw')))
                    self.assertEqual(sealed.stat().st_mode & 0o777, 0o500)
                    self.assertEqual((sealed / name).stat().st_mode & 0o777, 0o400)
                    self.assertEqual((sealed / name).read_bytes(), input_bytes[name])
                    self.assertNotEqual(sealed, inputs)
                    if english_cli_failure == (kind, phase):
                        status = 1
                    else:
                        report = dict(count=count, input_sha256=hashes[kind],
                                      status='prepared_apply' if phase == 'apply' else 'dry_run')
                        with (reports / report_name).open('x') as stream:
                            json.dump(report, stream)
                        (reports / report_name).chmod(0o600)
                        value = json.dumps(dict(count=count, updated=0 if phase == 'idempotent' else count,
                                                status='committed' if phase == 'apply' else 'dry_run')).encode()
                elif command[:2] == ['docker', 'run'] and command[-1] == MODULE.FINITE_COMPARISON:
                    value = b'[]'
                elif 'pg_dump' in command:
                    kwargs['stdout'].write(b'CREATE TABLE public.customers(id integer);\n')
                elif command[:2] == ['docker', 'stop']:
                    status = int(stop_fails)
                elif command[:3] == ['docker', 'ps', '-aq'] and english:
                    # Model owned leftovers even after a failed Docker CLI reply.
                    value = b'owned-fixture-task\n'
                elif command[:2] == ['docker', 'inspect']:
                    value = b'false\n'
                return subprocess.CompletedProcess(command, status, value, b'')

            argv = [str(SCRIPT), '--candidate', 'ghcr.io/mharnichev/sc-be/api@sha256:' + 'a' * 64,
                    '--previous', 'ghcr.io/mharnichev/sc-be/api@sha256:' + 'b' * 64,
                    '--postgres-image', 'postgres@sha256:' + 'c' * 64, '--confirm-production-copy']
            if source_head or english:
                argv += ['--source-head', expected_head]
            if english:
                argv += ['--english-input-dir', '/opt/soulcuts/backups/input-fixture',
                         '--english-products-sha256', hashes['products'],
                         '--english-categories-sha256', hashes['categories']]
            output, error = io.StringIO(), None
            old_umask = os.umask(0o077)
            try:
                with patch.object(sys, 'argv', argv), patch.object(MODULE, 'Path', side_effect=fake_path), \
                     patch.object(MODULE.subprocess, 'run', side_effect=run), \
                     patch.object(MODULE.shutil, 'disk_usage', return_value=SimpleNamespace(free=0 if no_space else 100 * 1024**3)), \
                     contextlib.redirect_stdout(output):
                    try:
                        MODULE.main()
                    except RuntimeError as cause:
                        error = str(cause)
            finally:
                os.umask(old_umask)
            report = list((root / 'backups').glob('*/result.json'))
            metadata = None
            if report:
                metadata = json.loads(report[0].read_text())
                self.assertEqual(metadata['source_head'], expected_head)
                self.assertEqual(metadata['source_collation'], locale)
                self.assertEqual(metadata['source_ctype'], locale)
                self.assertIn('production-' + expected_head[:4] + '.dump', metadata['archives'])
            for path in (root / 'backups').glob('*/*'):
                if path.is_file():
                    self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                else:
                    self.assertIn(path.name, ('reviewed-inputs', 'english-reports'))
                    expected_mode = 0o500 if path.name == 'reviewed-inputs' else 0o700
                    self.assertEqual(path.stat().st_mode & 0o777, expected_mode)
                    for child in path.iterdir():
                        self.assertEqual(child.stat().st_mode & 0o777, 0o400 if path.name == 'reviewed-inputs' else 0o600)
            if observed is not None:
                observed.update(argv=argv, metadata=metadata, hashes=hashes, english_calls=english_calls,
                                fingerprint_queries=fingerprint_queries,
                                reports={path.name: json.loads(path.read_text())
                                         for path in (root / 'backups').glob('*/english-reports/*.json')})
            return calls, error, bool(report), output.getvalue()

    def test_full_copy_plan_never_restores_or_migrates_production(self):
        calls, error, reported, output = self.exercise()
        self.assertIsNone(error)
        self.assertTrue(reported)
        self.assertIn('"result": "passed"', output)
        production = [call for call in calls if 'soulcuts-postgres-1' in call]
        self.assertEqual(len(production), 2)
        self.assertTrue(all('pg_database_size' in call[-1] or 'pg_dump' in call[-1] for call in production))
        self.assertTrue(any('--internal' in call for call in calls))
        migration = next(call for call in calls if call[-2:] == ['upgrade', 'head'])
        self.assertIn('--memory=768m', migration)
        self.assertIn('--pull=never', migration)
        comparison = next(call for call in calls if call[-1] == MODULE.FINITE_COMPARISON)
        self.assertEqual(comparison[comparison.index('--network') + 1], 'none')

    def test_full_main_english_134_seals_inputs_backfills_and_restores_all_columns(self):
        observed = {}
        calls, error, reported, output = self.exercise(english=True, observed=observed)
        self.assertIsNone(error)
        self.assertTrue(reported)
        self.assertIn('"result": "passed"', output)
        argv = observed['argv']
        self.assertEqual(argv[argv.index('--source-head') + 1], '0134_shop_canonical_collation')
        self.assertEqual(argv[argv.index('--english-input-dir') + 1], '/opt/soulcuts/backups/input-fixture')
        for kind in ('products', 'categories'):
            self.assertEqual(argv[argv.index('--english-' + kind + '-sha256') + 1], observed['hashes'][kind])
        expected = [('products', 'dry-run'), ('categories', 'dry-run'),
                    ('products', 'apply'), ('categories', 'apply'),
                    ('products', 'idempotent'), ('categories', 'idempotent')]
        self.assertEqual(observed['english_calls'], expected)
        metadata = observed['metadata']
        self.assertEqual(metadata['head'], '0137_shop_online_payment')
        self.assertEqual(set(metadata['archives']), {'production-0134.dump', 'upgraded-0137.dump'})
        english = metadata['english_backfill']
        self.assertEqual(english['counts'], dict(products=552, categories=44))
        self.assertEqual(english['input_sha256'], observed['hashes'])
        self.assertEqual(english['transactions'], 'separate products and categories')
        self.assertTrue(english['original_columns_unchanged'])
        self.assertTrue(english['sequences_unchanged'])
        self.assertTrue(metadata['restored_rows_equal'])
        self.assertTrue(metadata['restored_sequences_equal'])
        self.assertEqual(len(observed['reports']), 6)
        for kind, phase in expected:
            count = 552 if kind == 'products' else 44
            summary = english['summaries'][kind + '-' + phase]
            self.assertEqual(summary, dict(count=count, updated=0 if phase == 'idempotent' else count,
                                           status='committed' if phase == 'apply' else 'dry_run'))
            report = observed['reports'][kind + '-' + phase + '.json']
            self.assertEqual(report['input_sha256'], observed['hashes'][kind])
            self.assertEqual(report['status'], 'prepared_apply' if phase == 'apply' else 'dry_run')
        sql = observed['fingerprint_queries']
        self.assertEqual(len(sql), 5)
        for database, query in sql[:3]:
            self.assertEqual(database, 'upgrade_copy')
            self.assertIn('SELECT "id","name","stock_quantity" FROM public."products"', query)
            self.assertIn('SELECT "id","name","parent_id" FROM public."categories"', query)
            self.assertNotIn('"name_en"', query)
            self.assertNotIn('SELECT *', query)
        self.assertEqual([database for database, _ in sql[3:]], ['upgrade_copy', 'restore_copy'])
        self.assertEqual(sql[3][1], sql[4][1])
        self.assertIn('"name_en"', sql[3][1])
        self.assertIn('"product_type_en"', sql[3][1])
        network = next(call[-1] for call in calls if call[:3] == ['docker', 'network', 'create'])
        for call in (call for call in calls if call[:2] == ['docker', 'run'] and '-m' in call):
            self.assertEqual(call[call.index('--network') + 1], network)
            self.assertEqual(call[call.index('--user') + 1], f'{os.geteuid()}:{os.getegid()}')
            for guard in ('--rm', '--pull=never', '--memory=768m', '--cpus=1', '--pids-limit=128'):
                self.assertIn(guard, call)
            self.assertNotIn('--privileged', call)
            self.assertEqual('--apply' in call, call[call.index('--report') + 1].endswith('-apply.json'))
        production = [call for call in calls if 'soulcuts-postgres-1' in call]
        self.assertEqual(len(production), 2)
        self.assertTrue(all('pg_database_size' in call[-1] or 'pg_dump' in call[-1] for call in production))

    def assert_english_failure_cleanup(self, calls):
        network = next(call[-1] for call in calls if call[:3] == ['docker', 'network', 'create'])
        run = network.removesuffix('-net')
        expected = [run + suffix for suffix in ('-migration', '-compatibility', '-schema-comparison')]
        expected += [run + '-english-' + kind + '-' + phase
                     for phase in ('dry-run', 'apply', 'idempotent') for kind in ('products', 'categories')]
        probes = [call for call in calls if call[:3] == ['docker', 'ps', '-aq']]
        self.assertEqual([call[-1] for call in probes], ['name=^/' + task + '$' for task in expected])
        stopped = [call[-1] for call in calls if call[:4] == ['docker', 'stop', '--time', '5']]
        self.assertEqual(stopped, expected)
        self.assertEqual(calls[-1], ['docker', 'stop', '--time', '30', run + '-pg'])
        self.assertFalse(any(call[:2] == ['docker', 'stop'] and 'soulcuts-postgres-1' in call for call in calls))

    def test_full_main_english_original_column_drift_rejects_after_backfill(self):
        observed = {}
        calls, error, reported, output = self.exercise(english=True, english_row_drift=True, observed=observed)
        self.assertIn('English backfill changed original production columns', error)
        self.assertFalse(reported)
        self.assertNotIn('"result": "passed"', output)
        self.assertEqual(len(observed['english_calls']), 6)
        self.assertEqual(len(observed['fingerprint_queries']), 3)
        self.assertNotIn('"name_en"', observed['fingerprint_queries'][-1][1])
        self.assertFalse(any('pg_restore' in call and 'restore_copy' in call for call in calls))
        self.assert_english_failure_cleanup(calls)

    def test_full_main_english_cli_failures_clean_every_owned_task(self):
        phases = [(kind, phase) for phase in ('dry-run', 'apply', 'idempotent')
                  for kind in ('products', 'categories')]
        for index, failure in enumerate(phases):
            with self.subTest(kind=failure[0], phase=failure[1]):
                observed = {}
                calls, error, reported, output = self.exercise(english=True, english_cli_failure=failure,
                                                               observed=observed)
                self.assertIn('Rehearsal command failed', error)
                self.assertFalse(reported)
                self.assertNotIn('"result": "passed"', output)
                self.assertEqual(observed['english_calls'], phases[:index + 1])
                self.assertFalse(any(call[-1] == MODULE.FINITE_COMPARISON for call in calls))
                self.assert_english_failure_cleanup(calls)

    def test_failed_cleanup_cannot_report_success(self):
        _, error, reported, output = self.exercise(stop_fails=True)
        self.assertIn('private copy stop failed', error)
        self.assertFalse(reported)
        self.assertNotIn('passed', output)

    def test_current_production_copy_keeps_explicit_source_in_archive_and_report(self):
        _, error, reported, _ = self.exercise(source_head='0129_shop_ingress_limits')
        self.assertIsNone(error)
        self.assertTrue(reported)

    def test_restored_head_or_locale_mismatch_stops_without_migration(self):
        for options in (dict(restored_head=MODULE.BASE), dict(locale='C')):
            with self.subTest(options=options):
                calls, error, reported, _ = self.exercise(source_head='0129_shop_ingress_limits', **options)
                self.assertIn('reviewed production', error)
                self.assertFalse(reported)
                self.assertFalse(any(call[-2:] == ['upgrade', 'head'] for call in calls))
                self.assertTrue(any(call[:2] == ['docker', 'stop'] for call in calls))

    def test_changed_rows_stop_the_copy_and_fail_acceptance(self):
        calls, error, reported, _ = self.exercise(row_drift=True)
        self.assertIn('Existing production rows changed', error)
        self.assertFalse(reported)
        self.assertTrue(any(call[:2] == ['docker', 'stop'] for call in calls))

    def test_insufficient_capacity_never_dumps_or_starts_a_copy(self):
        calls, error, reported, _ = self.exercise(no_space=True)
        self.assertIn('headroom', error)
        self.assertFalse(reported)
        self.assertEqual(len(calls), 1)

    def test_quotes_identifiers(self):
        self.assertEqual(MODULE.identifier('odd"name'), '"odd""name"')

    def test_fingerprints_use_old_explicit_columns(self):
        query = MODULE.fingerprint_sql({'customers': ['id', 'phone']})
        self.assertIn('SELECT "id","phone" FROM public."customers"', query)
        self.assertNotIn('SELECT *', query)
        self.assertIn('ORDER BY md5(row_to_json(t)::text)', query)

    def test_invalid_image_exits_before_any_docker_or_private_file_action(self):
        result = subprocess.run([sys.executable, str(SCRIPT), '--candidate', 'untrusted:latest',
                                 '--previous', 'untrusted:latest', '--postgres-image', 'postgres:latest', '--confirm-production-copy'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('immutable digests', result.stderr)

    def test_copy_requires_explicit_confirmation(self):
        result = subprocess.run([sys.executable, str(SCRIPT), '--candidate', 'unused', '--previous', 'unused'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('--confirm-production-copy', result.stderr)


if __name__ == '__main__':
    unittest.main()
