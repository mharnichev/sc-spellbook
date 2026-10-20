import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1]/'scripts/rehearse-shop-production-copy.py'
SPEC = importlib.util.spec_from_file_location('english_rehearsal', SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class EnglishRehearsalTests(unittest.TestCase):
    def test_sealed_inputs_are_bounded_checksum_verified_and_readonly(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backups = root/'backups'
            backups.mkdir()
            inputs = backups/'inputs'
            inputs.mkdir(mode=0o700)
            output = root/'output'
            output.mkdir()
            hashes = {}
            for kind, name, _, count in MODULE.ENGLISH_INPUTS:
                data = json.dumps(dict(count=count, **{kind:[{}]*count})).encode()
                (inputs/name).write_bytes(data)
                (inputs/name).chmod(0o600)
                hashes[kind] = hashlib.sha256(data).hexdigest()

            def fake_path(value):
                return backups if value == '/opt/soulcuts/backups' else Path(value)

            with patch.object(MODULE, 'Path', side_effect=fake_path):
                sealed, actual = MODULE.seal_english_inputs(inputs, hashes, output)
            self.assertEqual(actual, hashes)
            self.assertEqual(sealed.stat().st_mode & 0o777, 0o500)
            for _, name, _, _ in MODULE.ENGLISH_INPUTS:
                self.assertEqual((sealed/name).stat().st_mode & 0o777, 0o400)
                self.assertEqual((sealed/name).read_bytes(), (inputs/name).read_bytes())
            rejected = root/'rejected'
            rejected.mkdir()
            with patch.object(MODULE, 'Path', side_effect=fake_path), self.assertRaisesRegex(RuntimeError, 'checksum'):
                MODULE.seal_english_inputs(inputs, dict(hashes, products='0'*64), rejected)

    def exercise_backfill(self, *, wrong_status=False, wrong_hash=False, unsafe_mode=False, wrong_counts=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = root/'inputs'
            inputs.mkdir()
            hashes = {}
            for kind, name, _, _ in MODULE.ENGLISH_INPUTS:
                (inputs/name).write_bytes(kind.encode())
                hashes[kind] = hashlib.sha256(kind.encode()).hexdigest()
            calls = []

            def execute(command):
                calls.append(command)
                name = command[command.index('--report')+1].split('/')[-1]
                kind, phase = name.removesuffix('.json').split('-', 1)
                count = {'products':552, 'categories':44}[kind]
                report = dict(status='prepared_apply' if phase == 'apply' else 'dry_run', count=count,
                              input_sha256='0'*64 if wrong_hash else hashes[kind])
                fd = os.open(root/'english-reports'/name, os.O_WRONLY|os.O_CREAT|os.O_EXCL,
                             0o644 if unsafe_mode else 0o600)
                with os.fdopen(fd, 'w') as stream:
                    json.dump(report, stream)
                if unsafe_mode:
                    (root/'english-reports'/name).chmod(0o644)
                summary = dict(status='committed' if phase == 'apply' else 'dry_run', count=count,
                               updated=0 if phase == 'idempotent' else count)
                if wrong_status:
                    summary['status'] = 'unknown'
                return json.dumps(summary).encode()

            def sql(database, query):
                self.assertEqual(database, 'upgrade_copy')
                self.assertEqual(query, MODULE.ENGLISH_COUNTS_SQL)
                return json.dumps(dict(products=551 if wrong_counts else 552, categories=44))

            result = MODULE.rehearse_english(execute, sql, 'pinned-candidate', 'internal-fixture-network',
                                             root/'copy.env', 'private-run', root, inputs, hashes)
            return calls, result

    def test_both_dry_runs_precede_separate_applies_and_idempotent_checks(self):
        calls, result = self.exercise_backfill()
        reports = [call[call.index('--report')+1].split('/')[-1] for call in calls]
        self.assertEqual(reports, ['products-dry-run.json','categories-dry-run.json',
                                  'products-apply.json','categories-apply.json',
                                  'products-idempotent.json','categories-idempotent.json'])
        self.assertEqual(result['counts'], dict(products=552, categories=44))
        self.assertEqual(result['transactions'], 'separate products and categories')
        for call in calls:
            self.assertEqual(call[call.index('--network')+1], 'internal-fixture-network')
            self.assertIn('--pull=never', call)
            self.assertIn('--memory=768m', call)
            self.assertIn('--cpus=1', call)
            self.assertEqual(call[call.index('--user')+1], str(os.geteuid())+':'+str(os.getegid()))
            self.assertEqual('--apply' in call, call[call.index('--report')+1].endswith('-apply.json'))

    def test_unknown_status_report_hash_permissions_or_coverage_fail_closed(self):
        for option in ('wrong_status', 'wrong_hash', 'unsafe_mode', 'wrong_counts'):
            with self.subTest(option=option), self.assertRaises(RuntimeError):
                self.exercise_backfill(**{option:True})

    def test_english_requires_explicit_134_and_all_hashes_before_any_io(self):
        args = [sys.executable, str(SCRIPT), '--candidate', 'candidate', '--previous', 'previous',
                '--postgres-image', 'postgres', '--confirm-production-copy',
                '--english-input-dir', '/not-accessed']
        result = subprocess.run(args, text=True, capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('requires all reviewed input arguments', result.stderr)
