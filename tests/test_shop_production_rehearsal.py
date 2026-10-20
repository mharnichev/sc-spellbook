import importlib.util
import contextlib
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
                 source_head=None, restored_head=None, locale='en_US.utf8'):
        expected_head = source_head or MODULE.BASE
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'backups').mkdir()
            calls, migrated, fingerprints = [], False, 0

            def fake_path(value):
                if value == '/opt/soulcuts/backups':
                    return root / 'backups'
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
                    if query == MODULE.SCHEMA_SQL:
                        value = b'{"unvalidated_constraints":0,"invalid_indexes":0,"indexes":[]}'
                    elif 'pg_get_constraintdef(oid,false)' in query:
                        value = b'{}'
                    elif 'version_num' in query:
                        value = (MODULE.HEAD if migrated else (restored_head or expected_head)).encode()
                    elif query in ('SELECT datcollate FROM pg_database WHERE datname=current_database()',
                                   'SELECT datctype FROM pg_database WHERE datname=current_database()'):
                        value = locale.encode()
                    elif 'json_object_agg' in query:
                        value = b'{"customers":["id"]}'
                    elif 'json_agg(s ORDER BY name)' in query:
                        fingerprints += 1
                        digest = 'changed' if row_drift and fingerprints == 2 else 'same'
                        value = json.dumps([dict(name='customers', rows=1, digest=digest)]).encode()
                    elif 'pg_sequences' in query:
                        value = b'["customers_id_seq"]'
                    elif 'last_value,is_called' in query:
                        value = b'10|t'
                    else:
                        self.assertIn('CREATE DATABASE restore_copy', query)
                elif command[:2] == ['docker', 'run'] and command[-2:] == ['upgrade', 'head']:
                    migrated = True
                elif command[:2] == ['docker', 'run'] and command[-1] == MODULE.FINITE_COMPARISON:
                    value = b'[]'
                elif 'pg_dump' in command:
                    kwargs['stdout'].write(b'CREATE TABLE public.customers(id integer);\n')
                elif command[:2] == ['docker', 'stop']:
                    status = int(stop_fails)
                elif command[:2] == ['docker', 'inspect']:
                    value = b'false\n'
                return subprocess.CompletedProcess(command, status, value, b'')

            argv = [str(SCRIPT), '--candidate', 'ghcr.io/mharnichev/sc-be/api@sha256:' + 'a' * 64,
                    '--previous', 'ghcr.io/mharnichev/sc-be/api@sha256:' + 'b' * 64,
                    '--postgres-image', 'postgres@sha256:' + 'c' * 64, '--confirm-production-copy']
            if source_head:
                argv += ['--source-head', source_head]
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
            if report:
                metadata = json.loads(report[0].read_text())
                self.assertEqual(metadata['source_head'], expected_head)
                self.assertEqual(metadata['source_collation'], locale)
                self.assertEqual(metadata['source_ctype'], locale)
                self.assertIn('production-' + expected_head[:4] + '.dump', metadata['archives'])
            for path in (root / 'backups').glob('*/*'):
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
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
