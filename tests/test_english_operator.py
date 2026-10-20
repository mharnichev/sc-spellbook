from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT/'scripts'/filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


OP = load('english_operator', 'apply-english-backfill.py')
DB = load('english_operator_db', 'english-backfill-db.py')


class EnglishOperatorTests(unittest.TestCase):
    def test_private_records_are_exclusive_and_fsynced(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'snapshot.json'
            with patch.object(OP.os, 'fsync', wraps=os.fsync) as sync:
                OP.persist(path, {'before':None})
                self.assertEqual(sync.call_count, 2)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                OP.persist(path, {'clobber':True})
            self.assertEqual(OP.private_json(path), {'before':None})
            with patch.object(OP.os, 'fsync', side_effect=OSError('fixture fsync failure')):
                with self.assertRaises(OSError):
                    OP.persist(path, {'phase':'uncertain'}, replace=True)
            self.assertEqual(OP.private_json(path), {'before':None})

    def test_renamed_or_foreign_recovery_tasks_are_never_stopped(self):
        with patch.object(OP, 'run') as run:
            with self.assertRaises(RuntimeError):
                OP.quiesce(['foreign-container'], 'english-catalog-abc', stop=True)
            run.assert_not_called()

    def test_owned_task_is_stopped_and_quiescence_verified(self):
        name = 'english-catalog-abc-products-apply'
        with patch.object(OP, 'run', side_effect=['owned-id','', '']) as run:
            OP.quiesce([name], 'english-catalog-abc', stop=True)
        calls = [call.args[0] for call in run.call_args_list]
        self.assertIn('label=com.docker.compose.service=migrate', calls[0])
        self.assertEqual(calls[1], ['docker','stop','--time','5','owned-id'])
        with patch.object(OP, 'run', return_value='still-running'):
            with self.assertRaises(RuntimeError):
                OP.quiesce([name], 'english-catalog-abc', stop=False)

    def test_cleanup_failure_is_not_reported_as_quiescence(self):
        with patch.object(OP, 'run', side_effect=['owned','', 'still-running']):
            with self.assertRaisesRegex(RuntimeError, 'cleanup'):
                OP.quiesce(['english-catalog-abc-apply'], 'english-catalog-abc', stop=True)

    def test_target_validation_rejects_extra_fields_duplicate_ids_and_blank_values(self):
        baseline = {'english': {'products':[{'id':1,'name_en':None,'product_type_en':None}],
                                'categories':[{'id':2,'name_en':None}]}}
        target = {'products':[{'id':1,'name_en':'English name','product_type_en':'Paste'}],
                  'categories':[{'id':2,'name_en':'For Body'}]}
        DB.validate_targets(baseline, target)
        cases = []
        value = deepcopy(target); value['products'][0]['stock_quantity'] = 999; cases.append(value)
        value = deepcopy(target); value['products'].append(deepcopy(value['products'][0])); cases.append(value)
        value = deepcopy(target); value['categories'][0]['name_en'] = ' '; cases.append(value)
        value = deepcopy(target); value['products'][0]['id'] = True; cases.append(value)
        for value in cases:
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                DB.validate_targets(baseline, value)

    def test_original_provenance_checks_ignore_only_english_vector(self):
        before = dict(head=DB.HEAD,database_identity={'database':'fixture'},inventory=['columns'],fingerprints={'products':'hash'},
                      sequences={'id':1},catalog={'products':['identity']},english={'products':['old']})
        current = deepcopy(before)
        current['english'] = {'products':['new']}
        DB.verify_original(current, before)
        for key in ('head','database_identity','inventory','fingerprints','sequences','catalog'):
            value = deepcopy(current); value[key] = 'foreign drift'
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                DB.verify_original(value, before)

    def test_rollback_queries_use_bound_json_not_interpolated_values(self):
        source = (ROOT/'scripts/english-backfill-db.py').read_text()
        self.assertIn('jsonb_to_recordset(CAST(:rows AS jsonb))', source)
        self.assertIn("{'rows':json.dumps(baseline['english'][table])}", source)
        self.assertIn('LOCK TABLE categories, products IN SHARE ROW EXCLUSIVE MODE', source)
        self.assertNotIn('DO $$', source)
