import argparse
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock, patch


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/rehearse-shop-production-copy.py'
SPEC = importlib.util.spec_from_file_location('rehearsal_source_head', SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class RehearsalSourceHeadTests(unittest.TestCase):
    def test_restored_head_mismatch_fails_before_locale_or_migration(self):
        sql = Mock(return_value=MODULE.BASE)
        with self.assertRaisesRegex(RuntimeError, 'reviewed production baseline'):
            MODULE.verify_source_copy(sql, '0129_shop_ingress_limits')
        sql.assert_called_once_with('upgrade_copy', 'SELECT version_num FROM alembic_version')

    def test_matching_source_is_propagated_to_archive_and_report_metadata(self):
        for head in MODULE.SOURCE_HEADS:
            with self.subTest(head=head):
                sql = Mock(side_effect=[head, 'en_US.utf8', 'en_US.utf8'])
                self.assertEqual(MODULE.verify_source_copy(sql, head),
                                 dict(source_head=head, source_collation='en_US.utf8', source_ctype='en_US.utf8'))
                self.assertEqual([call.args[1] for call in sql.call_args_list],
                                 ['SELECT version_num FROM alembic_version',
                                  'SELECT datcollate FROM pg_database WHERE datname=current_database()',
                                  'SELECT datctype FROM pg_database WHERE datname=current_database()'])
                self.assertEqual(MODULE.source_archive_name(head), 'production-' + head[:4] + '.dump')
        with self.assertRaisesRegex(RuntimeError, 'Unreviewed'):
            MODULE.source_archive_name('0133_master_mono_live')

    def test_wrong_clone_locale_is_not_accepted(self):
        for collation, ctype in (('C', 'en_US.utf8'), ('en_US.utf8', 'C')):
            with self.subTest(collation=collation, ctype=ctype):
                sql = Mock(side_effect=['0129_shop_ingress_limits', collation, ctype])
                with self.assertRaisesRegex(RuntimeError, 'production locale'):
                    MODULE.verify_source_copy(sql, '0129_shop_ingress_limits')

    def test_source_head_is_explicit_and_bounded_before_any_copy(self):
        original = argparse.ArgumentParser.parse_args
        required = ['--candidate', 'candidate', '--previous', 'previous',
                    '--postgres-image', 'postgres', '--confirm-production-copy']
        for extra, expected in (([], MODULE.BASE),
                                (['--source-head', '0129_shop_ingress_limits'], '0129_shop_ingress_limits'),
                                (['--source-head', '0134_shop_canonical_collation'], '0134_shop_canonical_collation')):
            with self.subTest(extra=extra):
                captured = []

                def capture(parser):
                    captured.append(original(parser, required + extra))
                    raise RuntimeError('stop after argument validation')

                with patch.object(argparse.ArgumentParser, 'parse_args', capture), patch.object(Path, 'mkdir') as mkdir:
                    with self.assertRaisesRegex(RuntimeError, 'stop after argument validation'):
                        MODULE.main()
                    mkdir.assert_not_called()
                self.assertEqual(captured[0].source_head, expected)

        def invalid(parser):
            return original(parser, required + ['--source-head', '0133_master_mono_live'])

        with patch.object(argparse.ArgumentParser, 'parse_args', invalid), patch.object(Path, 'mkdir') as mkdir:
            with self.assertRaises(SystemExit) as error:
                MODULE.main()
            self.assertEqual(error.exception.code, 2)
            mkdir.assert_not_called()
