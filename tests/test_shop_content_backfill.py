import copy
from contextlib import ExitStack, redirect_stdout
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
    spec = importlib.util.spec_from_file_location(name, ROOT/'scripts'/filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


OP = load('content_operator_test', 'apply-shop-content-backfill.py')
DB = load('content_database_test', 'shop-content-backfill-db.py').DB
PIN = 'ghcr.io/mharnichev/sc-be/api@sha256:'+'a'*64


class ContentTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app = Path(self.directory.name).resolve()
        self.root = self.app/'releases/candidate'
        self.root.mkdir(parents=True)
        (self.app/'env').mkdir()
        (self.app/'backups').mkdir()
        self.env = self.app/'env/backend.env'
        OP.SAFE.persist_bytes(self.env, b'UNCHANGED=synthetic\n')
        self.marker = self.app/'english-backfill-required'
        self.backend = self.app/'backend-recovery-required'
        self.backend.write_text('pending backend fixture')
        self.inputs = self.app/'backups/reviewed-content'
        self.inputs.mkdir(mode=0o700)
        products = [dict(id=i, slug=f'product-{i}', source=dict(description=f'<p>Source {i}</p>',
            short_description=None, ingredients=None), translations=dict(description_en=f'<p>English {i}</p>',
            short_description_en=None, ingredients_en=None)) for i in range(1, OP.COUNT+1)]
        self.input = dict(count=OP.COUNT, failures=[], products=products)
        raw = json.dumps(self.input).encode()
        self.input_sha = hashlib.sha256(raw).hexdigest()
        OP.SAFE.persist_bytes(self.inputs/OP.NAME, raw)
        catalog = [dict(id=i, name=f'Original {i}', slug=f'product-{i}', product_type='Original',
                        description=f'<p>Source {i}</p>', short_description=None, ingredients=None)
                   for i in range(1, OP.COUNT+3)]
        self.database = dict(head=OP.HEAD, database_identity={'database':'fixture'}, inventory=['all columns'],
            fingerprints={'products':'original names, stock and source', 'orders':'untouched ledger'},
            sequences={'id': {'last_value':500, 'is_called':True}}, catalog={'products':catalog},
            grants={'admins':[{'id':1,'is_active':True}], 'masters':[]},
            english={'products':[dict(id=i, **dict.fromkeys(OP.FIELDS)) for i in range(1, OP.COUNT+3)]})
        self.before = copy.deepcopy(self.database)
        self.running = False
        self.fail = None
        self.active = {}
        self.calls = []
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(OP, 'APP', self.app))
        self.stack.enter_context(patch.object(OP, 'INPUT_SHA', self.input_sha))
        self.stack.enter_context(patch.object(OP.SAFE, 'release_context', return_value=(self.root, PIN)))
        self.stack.enter_context(patch.object(OP.SAFE, 'run', side_effect=self.fake_run))
        self.stack.enter_context(patch.object(OP.SAFE, 'writers', side_effect=self.writers))
        self.stack.enter_context(patch.object(OP, 'TOOLS', self.root/'scripts'))
        self.stack.enter_context(patch.object(OP, 'tool_hashes', return_value={'fixture.py':'f'*64}))
        self.stack.enter_context(patch.dict(os.environ, {'ENGLISH_RUNTIME_VERIFIED':'true'}))

    @property
    def report(self):
        return next((self.app/'backups').glob('english-content-*'))

    def writers(self, running, pin):
        self.assertEqual((running, pin), (self.running, PIN))

    def invoke(self, mode):
        args = [str(self.inputs), self.input_sha] if mode == 'apply' else [str(self.report)]
        with patch.object(OP.sys, 'argv', ['operator', mode, *args]), redirect_stdout(io.StringIO()):
            OP.main()

    def db(self, mode, payload):
        owner = self
        class Connection:
            def execute(self, query, values=None):
                if query.startswith('UPDATE '):
                    owner.database['english']['products'] = json.loads(values['rows'])
                else:
                    owner.assertTrue(query.startswith(('SET ', 'LOCK TABLE ')), query)
        before = copy.deepcopy(self.database)
        try:
            with patch.object(DB, 'snapshot', side_effect=lambda *_: copy.deepcopy(self.database)):
                return DB.operate(Connection(), lambda sql: sql, mode, payload)
        except BaseException:
            self.database = before
            raise

    def fake_run(self, args, *, data=None, timeout=120):
        self.calls.append(args)
        if args[:2] == ['docker', 'ps']:
            if '-aq' in args:
                return 'a'*12
            return '\n'.join(identifier+' '+name for identifier, name in self.active.items())
        if args[:2] == ['docker', 'stop']:
            if self.fail == 'cleanup':
                raise RuntimeError('owned task cleanup failed')
            self.active.pop(args[-1])
            return ''
        self.assertEqual(args[:2], ['docker','run'])
        command = args[args.index('/release-tools/scripts/english-backfill-network-guard.py')+1:]
        if command[0].endswith('shop-content-backfill-db.py'):
            return json.dumps(self.db(command[1], None if data is None else json.loads(data)))
        self.assertEqual(command[:2], ['-m','app.utils.backfill_shop_content_en'])
        self.assertIn('--network', args)
        self.assertEqual(args[args.index('--network')+1], 'container:'+'a'*12)
        self.assertIn('BACKGROUND_WORKERS_ENABLED=false', args)
        path = self.report/'reports'/Path(command[command.index('--report')+1]).name
        apply = '--apply' in command
        records, changed = [], 0
        vector = {row['id']:row for row in self.database['english']['products']}
        catalog = {row['id']:row for row in self.database['catalog']['products']}
        for item in self.input['products']:
            previous = {key: vector[item['id']][key] for key in OP.FIELDS}
            if any(previous[key] not in (None,item['translations'][key]) for key in OP.FIELDS):
                raise RuntimeError('manual content conflict')
            changed += previous != item['translations']
            records.append(dict(id=item['id'],slug=item['slug'],source_raw={key:catalog[item['id']][key] for key in OP.SOURCE_FIELDS},
                source_public=item['source'],previous=previous,desired=item['translations']))
        OP.SAFE.persist(path, dict(status='prepared_apply' if apply else 'dry_run',input_sha256=self.input_sha,
                                  count=OP.COUNT,records=records))
        if apply:
            self.assertTrue(self.marker.exists())
            for item in self.input['products']:
                vector[item['id']].update(item['translations'])
            if self.fail in ('lost-ack','cleanup'):
                if self.fail == 'cleanup':
                    self.active['b'*12] = args[args.index('--name')+1]
                raise RuntimeError('lost apply acknowledgment')
        return json.dumps(dict(status='committed' if apply else 'dry_run',count=OP.COUNT,updated=changed))

    def test_apply_preserves_out_of_scope_rows_then_finalize_and_receipt_only_recovery(self):
        self.invoke('apply')
        self.assertEqual(self.database['english']['products'][-2:], self.before['english']['products'][-2:])
        for key in DB.ORIGINAL_KEYS:
            self.assertEqual(self.database[key], self.before[key])
        self.assertTrue(json.loads(self.marker.read_text())['pre_restart_original_verified'])
        self.assertEqual((self.report/'reviewed-inputs'/OP.NAME).stat().st_mode & 0o777, 0o400)
        self.running = True
        self.invoke('finalize')
        self.assertFalse(self.marker.exists())
        self.assertTrue(self.backend.exists())
        self.running = False
        self.invoke('recover-finalize')
        self.assertFalse(self.marker.exists())
        self.running = True
        self.invoke('finalize')

    def test_unknown_commit_reconciles_without_reapply(self):
        self.fail = 'lost-ack'
        with self.assertRaises(RuntimeError):
            self.invoke('apply')
        self.fail = None
        calls = len(self.calls)
        self.invoke('reconcile')
        self.assertTrue(json.loads(self.marker.read_text())['pre_restart_original_verified'])
        self.assertFalse(any('app.utils.backfill_shop_content_en' in args for args in self.calls[calls:]))

    def test_rollback_restores_only_exact_vector_and_is_receipt_retry_safe(self):
        self.invoke('apply')
        self.invoke('rollback')
        self.assertEqual(self.database, self.before)
        self.assertFalse(self.marker.exists())
        self.invoke('rollback')

    def test_source_stock_ledger_grant_and_partial_english_drift_refuse_rollback(self):
        self.invoke('apply')
        original = copy.deepcopy(self.database)
        for kind in ('catalog','fingerprints','sequences','grants','english'):
            self.database = copy.deepcopy(original)
            if kind == 'english':
                self.database[kind]['products'][0]['description_en'] = 'Foreign manual translation'
            else:
                self.database[kind] = {'foreign':'changed'}
            with self.subTest(kind=kind), self.assertRaises(RuntimeError):
                self.invoke('rollback')
            self.assertTrue(self.marker.exists())

    def test_environment_and_tool_drift_prevent_reconcile(self):
        self.invoke('apply')
        OP.SAFE.persist_bytes(self.env, b'FOREIGN=true\n', replace=True)
        with self.assertRaises(RuntimeError):
            self.invoke('reconcile')
        self.assertTrue(self.marker.exists())

    def test_finalize_requires_runtime_ack_and_current_grants(self):
        self.invoke('apply')
        self.running = True
        with patch.dict(os.environ, {'ENGLISH_RUNTIME_VERIFIED':'false'}), self.assertRaises(RuntimeError):
            self.invoke('finalize')
        self.database['grants'] = {'foreign':'permission drift'}
        with self.assertRaises(RuntimeError):
            self.invoke('finalize')
        self.assertTrue(self.marker.exists())

    def test_receipt_fsync_failure_retains_marker_and_retry_resyncs_receipt(self):
        self.invoke('apply')
        self.running = True
        native = OP.SAFE.persist
        def fail(path, value, **kwargs):
            native(path,value,**kwargs)
            if path.name == 'finalized.json':
                raise OSError('receipt directory fsync failed')
        with patch.object(OP.SAFE, 'persist', side_effect=fail), self.assertRaises(OSError):
            self.invoke('finalize')
        self.assertTrue(self.marker.exists())
        with patch.object(OP.SAFE, 'resync', side_effect=OSError('receipt resync failed')), self.assertRaises(OSError):
            self.invoke('finalize')
        self.assertTrue(self.marker.exists())
        self.invoke('finalize')

    def test_failed_payload_fsync_precedes_any_database_updates(self):
        native = OP.SAFE.persist
        def fail(path,value,**kwargs):
            if path.name == 'snapshot.json':
                raise OSError('payload fsync failed')
            return native(path,value,**kwargs)
        with patch.object(OP.SAFE, 'persist', side_effect=fail), self.assertRaises(OSError):
            self.invoke('apply')
        self.assertEqual(self.database,self.before)

    def test_cleanup_failure_remains_a_failure_and_preserves_fences(self):
        self.fail = 'cleanup'
        with self.assertRaisesRegex(RuntimeError,'cleanup'):
            self.invoke('apply')
        self.assertTrue(self.marker.exists() and self.backend.exists())
        self.assertTrue(self.active)

    def test_db_validation_allows_nullable_long_html_but_rejects_foreign_shape(self):
        target = copy.deepcopy(self.before['english'])
        target['products'][0]['description_en'] = '<p>'+'Long English '*300+'</p>'
        DB.validate_targets(self.before,target)
        target['products'][0]['stock_quantity'] = 999
        with self.assertRaises(RuntimeError):
            DB.validate_targets(self.before,target)

    def test_unreviewed_input_refuses_before_backfill(self):
        OP.SAFE.persist_bytes(self.inputs/OP.NAME,b'{}',replace=True)
        with self.assertRaises(RuntimeError):
            self.invoke('apply')
        self.assertEqual(self.database,self.before)
