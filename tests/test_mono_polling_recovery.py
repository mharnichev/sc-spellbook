import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import runpy
import signal
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/recover-mono-polling-cutover.py'
if not SCRIPT.is_file():
    SCRIPT = Path(__file__).with_name('controller.py')
SPEC = importlib.util.spec_from_file_location('recovery', SCRIPT)
C = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(C)
FIXTURE = Path(__file__).with_name('test_master_mono_dispatch_cutover.py')
if not FIXTURE.is_file():
    FIXTURE = Path('/Users/markgarnicev/sc-local-work/ready-ui-release-20261109/publish-sc-spellbook/tests/test_master_mono_dispatch_cutover.py')


def pending(revision):
    return dict(enabled=True, order_id=7, revision=revision, mode='mono_checkbox', paid=True,
        receipt_accepted=False, status='mono_checkbox_receipt_pending', amount_minor=480000,
        invoice_id='opaque-synthetic-invoice', payment_url=None, payment_url_source='mono_authenticated_create_v1',
        payment_url_expires_at=None, receipt_pdf_path=None, can_handover=False,
        can_verify_invoice=False, blocking_reasons=['pending'])


def row(index, response_json=None, order_id=1):
    return {'scope_key': hashlib.sha256(str(index).encode()).hexdigest(),
            'payload_hash': C.sha(json.dumps({'expected_revision': response_json['revision'] - 1},
                sort_keys=True, separators=(',', ':')).encode()) if response_json else 'a' * 64,
            'order_id': order_id, 'response_json': response_json,
            'row_hash': hashlib.md5(str(index).encode()).hexdigest()}


def rows():
    before = [row(index) for index in range(351)] + [row(351, pending(337), 7)]
    return before, copy.deepcopy(before) + [row(352, pending(338), 7), row(353, pending(339), 7)]


class ProofTests(unittest.TestCase):
    def setUp(self):
        self.before, self.after = rows()
        self.baseline_hash = C.aggregate(self.before)

    def prove(self):
        return C.prove_append_only(self.before, self.after, self.baseline_hash)

    def test_exact_finite_append_proof_preserves_inputs(self):
        original = copy.deepcopy(self.before)
        proof = self.prove()
        self.assertEqual((proof['added_count'], proof['first_revision'], proof['last_revision']), (2, 338, 339))
        C.verify_frozen(proof, self.after)
        self.assertEqual(self.before, original)

    def test_old_row_mutation_or_deletion_refused(self):
        for change in ('delete', 'mutate', 'replace'):
            with self.subTest(change=change):
                self.setUp()
                if change == 'delete': self.after.pop(0)
                if change == 'mutate': self.after[0]['row_hash'] = 'b' * 32
                if change == 'replace': self.after[0]['scope_key'] = 'b' * 64
                with self.assertRaises(RuntimeError): self.prove()

    def test_added_order_status_financial_and_full_template_drift_refused(self):
        changes = [('order_id', 8), ('status', 'accepted'), ('amount_minor', 1), ('paid', False),
            ('receipt_accepted', True), ('can_handover', True), ('invoice_id', 'different'),
            ('payment_url', 'https://synthetic.invalid'), ('payment_url_source', None),
            ('payment_url_expires_at', '2099-01-01'), ('receipt_pdf_path', '/new.pdf'),
            ('can_verify_invoice', True), ('blocking_reasons', []), ('enabled', False),
            ('mode', 'different')]
        for key, value in changes:
            with self.subTest(key=key):
                self.setUp(); self.after[-1]['response_json'][key] = value
                with self.assertRaises(RuntimeError): self.prove()
        self.setUp(); self.after[-1]['order_id'] = 8
        with self.assertRaises(RuntimeError): self.prove()

    def test_exact_json_keys_and_types_required(self):
        for key, value in [('revision', True), ('paid', 1), ('amount_minor', 480000.0),
                           ('blocking_reasons', 'pending'), ('receipt_accepted', 0), ('order_id', True)]:
            with self.subTest(key=key):
                self.setUp(); self.after[-1]['response_json'][key] = value
                with self.assertRaises(RuntimeError): self.prove()
        for key in ('status', 'revision'):
            self.setUp(); del self.after[-1]['response_json'][key]
            with self.assertRaises(RuntimeError): self.prove()
        self.setUp(); self.after[-1]['response_json']['extra'] = None
        with self.assertRaises(RuntimeError): self.prove()

    def test_payload_gaps_duplicates_and_untrusted_baseline_refused(self):
        self.after[-1]['payload_hash'] = '0' * 64
        with self.assertRaises(RuntimeError): self.prove()
        self.setUp(); self.after[-1]['response_json']['revision'] = 340
        self.after[-1]['payload_hash'] = C.sha(b'{"expected_revision":339}')
        with self.assertRaises(RuntimeError): self.prove()
        self.setUp(); self.after.append(copy.deepcopy(self.after[-1]))
        with self.assertRaises(RuntimeError): self.prove()
        self.setUp()
        with self.assertRaises(RuntimeError): C.prove_append_only(self.before, self.after, '0' * 32)
        with self.assertRaises(RuntimeError): C.prove_append_only(self.before[:-1], self.after, self.baseline_hash)

    def test_any_change_after_freeze_is_refused(self):
        proof = self.prove()
        for change in ('addition', 'old_mutation', 'new_mutation', 'deletion'):
            with self.subTest(change=change):
                _, after = rows()
                if change == 'addition': after.append(row(354, pending(340), 7))
                if change == 'old_mutation': after[0]['row_hash'] = 'c' * 32
                if change == 'new_mutation': after[-1]['row_hash'] = 'c' * 32
                if change == 'deletion': after.pop()
                with self.assertRaises(RuntimeError): C.verify_frozen(proof, after)

    def test_exact_release_and_every_hash_binding_required(self):
        binding = {'version': C.VERSION, 'release': str(C.RELEASE), 'helper_sha256': C.HELPER_SHA,
            'pins_sha256': C.PINS_SHA, 'manifest_sha256': C.MANIFEST_SHA,
            'original_journal_sha256': C.ORIGINAL_JOURNAL_SHA}
        actual = {key: value for key, value in binding.items() if key.endswith('_sha256')}
        C.verify_binding(binding, actual)
        for key in binding:
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                C.verify_binding({**binding, key: 'wrong'}, actual)
        for key in actual:
            with self.subTest(actual=key), self.assertRaises(RuntimeError):
                C.verify_binding(binding, {**actual, key: '0' * 64})


class StateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = runpy.run_path(str(FIXTURE), run_name='fixture')
        cls.fixture['CutoverTests'].setUpClass()
        cls.module = cls.fixture['MODULE']

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        runtime = self.fixture['CutoverTests']().paused_runtime(self.tmp.name, same_head=True)
        self.original = runtime.journal.read_bytes()
        self.paths = patch.multiple(C, APP=runtime.app, RELEASE=runtime.release,
                                    BACKUP=runtime.app / 'backups/paired')
        self.paths.start(); self.addCleanup(self.paths.stop)
        cls = C.make_controller(self.module)
        job = cls.__new__(cls)
        job.__dict__.update(runtime.__dict__)
        job.generation = runtime.generation; job.running = runtime.running
        job.target = True; job.requests = 'all'; job.failure = None
        for name in ('run', 'service', 'flags'):
            setattr(job, name, types.MethodType(getattr(type(runtime), name), job))
        job.initial = runtime.load()
        before, after = rows()
        proof = C.prove_append_only(before, after, C.aggregate(before))
        job.initial['baseline']['compatibility'] = {'bound': 'original-bound', 'prepared_intents': C.aggregate(before)}
        job.live_snapshot = {**runtime.snapshot(), 'compatibility': {'bound': 'original-bound', 'prepared_intents': proof['prepared_intents']}}
        job.snapshot = lambda: copy.deepcopy(job.live_snapshot)
        job.live_intents = after
        job.intents = lambda container=None: copy.deepcopy(job.live_intents)
        job.actual_financial = {'ledger': 'same', 'stock': 'same', 'sales': 'same'}
        job.financial = lambda container=None: copy.deepcopy(job.actual_financial)
        job.frozen_proof = copy.deepcopy(proof)
        job.paired_financial = copy.deepcopy(job.actual_financial)
        job.binding = {'synthetic': True}
        job.guardian_pid = os.getpid()
        job.check_lease = lambda: None
        job.sidecar_dir = runtime.app / 'backups/polling-recovery'
        job.sidecar_dir.mkdir(mode=0o700)
        job.sidecar = job.sidecar_dir / 'journal.json'
        job.original_journal = runtime.journal
        job.original_raw = self.original
        job.verify_original = lambda: C.require(job.original_journal.read_bytes() == self.original, 'Original journal changed')
        state = copy.deepcopy(job.initial)
        state.update(controller_version=C.VERSION, binding=job.binding, finite_intent_proof=proof,
                     paired_financial=copy.deepcopy(job.actual_financial))
        self.module.persist(job.sidecar, state)
        (runtime.app / 'release.lock').mkdir()
        (runtime.app / 'release.lock/pid').write_text(str(os.getpid()))
        self.job = job
        self.env = patch.dict(os.environ, PILOT_MANUAL_GATE='verified', EXPECTED_RELEASE=str(runtime.release))
        self.env.start(); self.addCleanup(self.env.stop)

    def assert_fenced(self):
        self.assertFalse(self.job.running)
        self.assertIn(b'=false', self.job.env.read_bytes())
        self.assertTrue(self.job.marker.exists())
        self.assertEqual(self.job.original_journal.read_bytes(), self.original)

    def test_full_cycle_preserves_original_and_literal_baseline(self):
        original_baseline = copy.deepcopy(self.job.initial['baseline'])
        state = self.job.resume_accept()
        self.assertEqual(state['phase'], 'complete')
        self.assertEqual(state['baseline'], original_baseline)
        self.assertEqual(self.job.original_journal.read_bytes(), self.original)
        self.assertEqual((self.job.app / 'current').resolve(), self.job.release)
        self.assertTrue(self.job.running)
        self.assertIn(b'=true', self.job.env.read_bytes())
        self.assertFalse(self.job.marker.exists())

    def test_original_sidecar_fields_and_frozen_proof_cannot_drift(self):
        for key in ('flags', 'writers', 'original_hash', 'paused_hash', 'previous', 'pins_hash', 'paused_ids', 'baseline'):
            with self.subTest(key=key):
                state = json.loads(self.job.sidecar.read_bytes())
                old = state[key]; state[key] = 'tampered'; self.module.persist(self.job.sidecar, state)
                with self.assertRaises(RuntimeError): self.job.load()
                state[key] = old; self.module.persist(self.job.sidecar, state)
        state = self.job.load(); state['finite_intent_proof']['prepared_intents'] = 'changed'
        with self.assertRaises(RuntimeError): self.job.verify_live(state, True, {key: value['id'] for key, value in state['writers'].items()})

    def test_compatibility_bound_protected_financial_and_stock_drift_blocks_enable(self):
        cases = ('bound', 'requests', 'protected', 'stock', 'ledger', 'sales', 'head')
        for change in cases:
            with self.subTest(change=change):
                snapshot = copy.deepcopy(self.job.live_snapshot); finance = copy.deepcopy(self.job.actual_financial)
                if change == 'bound': self.job.live_snapshot['compatibility']['bound'] = 'changed'
                elif change in ('stock', 'ledger', 'sales'): self.job.actual_financial[change] = 'changed'
                else: self.job.live_snapshot[change] = 'changed'
                with self.assertRaises(RuntimeError): self.job.resume_accept()
                self.assertIn(b'=false', self.job.env.read_bytes())
                self.job.live_snapshot = snapshot; self.job.actual_financial = finance

    def test_polling_addition_after_proof_blocks_enable(self):
        self.job.live_intents.append(row(354, pending(340), 7))
        with self.assertRaises(RuntimeError): self.job.resume_accept()
        self.assertIn(b'=false', self.job.env.read_bytes())

    def test_post_start_polling_toctou_refences_and_keeps_marker(self):
        start = self.job.start_writers
        def changed_start():
            start(); self.job.live_intents.append(row(354, pending(340), 7))
        self.job.start_writers = changed_start
        with self.assertRaises(RuntimeError): self.job.resume_accept()
        self.assert_fenced()
        self.assertEqual(json.loads(self.job.sidecar.read_bytes())['phase'], 'recovery_required')

    def test_post_enable_lease_loss_refences(self):
        checkpoint = self.job.check_lease
        self.job.check_lease = lambda: C.require(b'=false' in self.job.env.read_bytes(), 'Synthetic lease loss')
        with self.assertRaises(RuntimeError): self.job.resume_accept()
        self.assert_fenced()

    def test_failed_start_and_failed_acceptance_both_refence(self):
        self.job.failure = 'up'
        with self.assertRaises(RuntimeError): self.job.resume_accept()
        self.assert_fenced()

    def test_failed_stop_after_enable_still_persists_fence_marker_and_audit(self):
        start = self.job.start_writers
        def failed_start():
            start(); self.job.failure = 'stop'
            self.job.marker.unlink()
            raise RuntimeError('Synthetic post-start failure')
        self.job.start_writers = failed_start
        with self.assertRaises(RuntimeError): self.job.resume_accept()
        self.assertTrue(self.job.running)  # Stop was deliberately unavailable.
        self.assertIn(b'=false', self.job.env.read_bytes())
        self.assertTrue(self.job.marker.exists())
        self.assertEqual(json.loads(self.job.sidecar.read_bytes())['phase'], 'recovery_required')
        self.assertEqual(self.job.original_journal.read_bytes(), self.original)

    def test_restore_waits_for_final_tcp_and_uses_it_for_archive_and_sql(self):
        bin_dir = self.job.app / 'fake-bin'; bin_dir.mkdir()
        trace = self.job.app / 'readiness.trace'; ready = self.job.app / 'final.ready'
        (bin_dir / 'pg_isready').write_text('#!/bin/sh\n' +
            'if [ -f "$FINAL_READY" ]; then echo final_tcp >> "$READINESS_TRACE"; exit 0; fi\n' +
            'case "$*" in *"-h 127.0.0.1"*) echo temporary_tcp_refused >> "$READINESS_TRACE"; exit 1;;\n' +
            '*) echo premature_socket_ready >> "$READINESS_TRACE"; exit 0;; esac\n')
        (bin_dir / 'sleep').write_text('#!/bin/sh\ntouch "$FINAL_READY"\n')
        for path in bin_dir.iterdir(): path.chmod(0o700)
        before, after = rows()
        self.job.intents = lambda container=None: copy.deepcopy(before if container else after)
        real_run = subprocess.run
        seen = []
        def boundary_run(command, data=None):
            seen.append(command)
            if command[:2] == ['docker', 'exec'] and 'pg_isready' in command[-1]:
                result = real_run(['sh', '-ec', command[-1]], capture_output=True,
                    env={**os.environ, 'PATH': str(bin_dir) + ':' + os.environ['PATH'],
                         'FINAL_READY': str(ready), 'READINESS_TRACE': str(trace)})
                self.assertEqual(result.returncode, 0)
                self.assertEqual(trace.read_text().splitlines(), ['temporary_tcp_refused', 'final_tcp'])
            if 'psql' in command:
                self.assertIn('-h', command)
                self.assertEqual(command[command.index('-h') + 1], '127.0.0.1')
                return (C.HEAD + '\n').encode()
            return b''
        def archive_run(command, **kwargs):
            self.assertEqual(trace.read_text().splitlines()[-1], 'final_tcp')
            self.assertIn('-h', command)
            self.assertEqual(command[command.index('-h') + 1], '127.0.0.1')
            return types.SimpleNamespace(returncode=0, stderr=b'')
        self.job.run = boundary_run
        real_proof = C.prove_append_only
        with patch.object(C.subprocess, 'run', side_effect=archive_run), \
             patch.object(C, 'prove_append_only', side_effect=lambda baseline, current: real_proof(baseline, current, C.aggregate(before))):
            proof, financial = self.job.restore_proof()
        self.assertEqual(proof['added_count'], 2)
        self.assertTrue(any('psql' in command for command in seen))
        self.assertEqual(self.job.original_journal.read_bytes(), self.original)

    def test_restore_error_records_exact_stage_and_bounded_private_stderr(self):
        diagnostic = b'FATAL: database "restore_copy" does not exist\n' + b'PRIVATE_SYNTHETIC_PROVIDER_DATA' * 500
        with patch.object(C.subprocess, 'run', return_value=types.SimpleNamespace(returncode=1, stderr=diagnostic)):
            with self.assertRaises(RuntimeError): self.job.restore_proof()
        failure = json.loads((self.job.sidecar_dir / 'failure.json').read_bytes())
        self.assertEqual(failure['stage'], 'restore_archive_load')
        self.assertEqual(failure['detail_code'], 'database_missing')
        self.assertNotIn('PRIVATE_SYNTHETIC_PROVIDER_DATA', json.dumps(failure))
        private = self.job.sidecar_dir / 'restore.stderr.private'
        self.assertEqual(private.stat().st_mode & 0o777, 0o600)
        self.assertEqual(private.read_bytes(), diagnostic[:8192])
        self.assertIn(b'=false', self.job.env.read_bytes())
        self.assertEqual(self.job.original_journal.read_bytes(), self.original)

    def test_restore_cleanup_always_attempts_own_network_after_container_cleanup_failure(self):
        commands = []
        def run(command, data=None):
            commands.append(command)
            if command[:2] == ['docker', 'exec']:
                raise RuntimeError('Synthetic restore readiness failure')
            if command[:3] == ['docker', 'rm', '-f']:
                raise RuntimeError('Synthetic own container cleanup failure')
            return b''
        self.job.run = run
        with self.assertRaises(RuntimeError): self.job.restore_proof()
        self.assertTrue(any(command[:3] == ['docker', 'network', 'rm'] for command in commands))
        self.assertFalse(any('stop' in command or 'up' in command for command in commands))

    def test_restart_or_flag_drift_or_missing_manual_gate_blocks_enable(self):
        self.job.generation += 3
        with self.assertRaises(RuntimeError): self.job.resume_accept()
        self.assertIn(b'=false', self.job.env.read_bytes())
        self.job.generation -= 3
        with patch.object(self.job, 'flags', return_value={self.module.FLAG: True}):
            with self.assertRaises(RuntimeError): self.job.resume_accept()
        with patch.dict(os.environ, PILOT_MANUAL_GATE=''):
            with self.assertRaises(RuntimeError): self.job.resume_accept()
        self.assertIn(b'=false', self.job.env.read_bytes())

    def test_configuration_current_and_mutex_drift_block(self):
        original = self.job.env.read_bytes()
        self.job.env.write_bytes(original + b'NEW=false\n')
        with self.assertRaises(RuntimeError): self.job.resume_accept()
        self.job.env.write_bytes(original)
        (self.job.app / 'release.lock/pid').write_text('99999')
        with self.assertRaises(RuntimeError): self.job.resume_accept()
        (self.job.app / 'release.lock/pid').write_text(str(os.getpid()))
        (self.job.app / 'current').unlink(); (self.job.app / 'current').symlink_to(self.job.release)
        with self.assertRaises(RuntimeError): self.job.resume_accept()

    def test_final_transition_failure_restores_marker_and_fence_without_old_rollback(self):
        save = self.job.save
        def failing_save(state, phase):
            if phase == 'complete': raise OSError('Synthetic final fsync failure')
            save(state, phase)
        self.job.save = failing_save
        with self.assertRaises(OSError): self.job.resume_accept()
        self.assert_fenced()
        self.assertEqual((self.job.app / 'current').resolve(), self.job.release)

    def test_original_journal_drift_refuses_before_enable(self):
        self.job.original_journal.write_bytes(self.original + b' ')
        with self.assertRaises(RuntimeError): self.job.resume_accept()
        self.assertIn(b'=false', self.job.env.read_bytes())


class LeaseTests(unittest.TestCase):
    def fake_psql(self, fail=False):
        code = """import sys
for line in sys.stdin:
 if line.startswith('SELECT pg_backend_pid'): print('321:1',flush=True)
 if line.startswith('\\\\echo '): print(line.strip().split(' ',1)[1],flush=True)
"""
        return [sys.executable, '-u', '-c', code]

    def test_lease_roundtrip_identity_and_process_loss(self):
        lease = C.Lease(self.fake_psql(), time.monotonic() + 10)
        try:
            self.assertEqual(lease.backend, '321')
            lease.check()
            lease.process.terminate(); lease.process.wait(timeout=2)
            with self.assertRaises(RuntimeError): lease.check()
        finally: lease.close()

    def test_lease_deadline_refuses(self):
        lease = C.Lease(self.fake_psql(), time.monotonic() + 10)
        try:
            lease.deadline = time.monotonic() - 1
            with self.assertRaises(RuntimeError): lease.check()
        finally: lease.close()

class SupervisorTests(unittest.TestCase):
    def script(self, failure):
        # Entire controller main runs in a child process; Docker/DB boundaries remain fake.
        # Real fork, signals, pipes, filesystem CAS, private journals and symlink are used.
        return 'failure_mode=' + repr(failure) + '\n' + '''import importlib.util,json,os,sys,time,signal
from pathlib import Path
spec=importlib.util.spec_from_file_location('tests',TEST)
t=importlib.util.module_from_spec(spec);spec.loader.exec_module(t)
t.StateTests.setUpClass();case=t.StateTests();case.setUp();c=t.C;job=case.job
binding=job.app/'binding.json';binding.write_text('{}');binding.chmod(0o600)
(job.app/'release.lock/pid').unlink();(job.app/'release.lock').rmdir()
source_sidecar=job.sidecar
commands=job.app/'commands.jsonl'
run=job.run
def recording_run(command,data=None):
 with commands.open('a') as log:log.write(json.dumps(command)+chr(10))
 return run(command,data)
job.run=recording_run
cas=case.module.cas_env
def recording_cas(*args):
 with commands.open('a') as log:log.write(json.dumps(['CAS'])+chr(10))
 return cas(*args)
case.module.cas_env=recording_cas
def prepared():
 if job.sidecar!=source_sidecar:
  job.sidecar_dir.mkdir(mode=0o700);case.module.persist(job.sidecar,json.loads(source_sidecar.read_bytes()))
 if failure_mode=='proof_restore_error':raise RuntimeError('Synthetic restore/proof failure')
 if failure_mode=='proof_lease':time.sleep(3)
 return job.load()
job.prepare_sidecar=prepared
if failure_mode=='proof_error':job.actual_financial={'stock':'drift'}
if failure_mode=='proof_cleanup_error':
 close=c.Lease.close
 def failing_close(lease):close(lease);raise RuntimeError('Synthetic lease cleanup failure')
 c.Lease.close=failing_close


code="""import sys,os,signal
from pathlib import Path
count=0
for line in sys.stdin:
 if line.startswith('SELECT pg_backend_pid'):
  count+=1
  if FAILURE=='proof_lease' and count>=3:raise SystemExit(7)
  lost=FAILURE in ('after_cas','guardian_death') and b'=true' in Path(ENV).read_bytes()
  late=FAILURE=='after_marker' and not Path(MARKER).exists()
  if lost or late:
   if FAILURE=='guardian_death':os.kill(os.getppid(),signal.SIGKILL)
   raise SystemExit(7)
  print('321:1',flush=True)
 if line.startswith('\\\\echo '): print(line.strip().split(' ',1)[1],flush=True)
""".replace('FAILURE',repr(failure_mode)).replace('ENV',repr(str(job.env))).replace('MARKER',repr(str(job.marker)))
job.psql_command=lambda:[sys.executable,'-u','-c',code]
if failure_mode in ('after_cas','guardian_death'):
 start=job.start_writers
 def slow_start():
  start();time.sleep(4)
 job.start_writers=slow_start
c.load_helper=lambda:case.module
c.make_controller=lambda module:lambda binding:job
sys.argv=['controller.py','prove' if failure_mode.startswith('proof_') else 'resume-accept','--binding',str(binding)]
print(json.dumps({'app':str(job.app),'sidecar':str(job.sidecar)}),flush=True)
try:c.main();outcome='accepted'
except BaseException:outcome='refused'
print(json.dumps({'outcome':outcome,'paused':b'=false' in job.env.read_bytes(),'marker':job.marker.exists(),
 'phase':json.loads(job.sidecar.read_bytes())['phase'],'current_new':(job.app/'current').resolve()==job.release,
 'original_unchanged':job.original_journal.read_bytes()==case.original,'mutex':(job.app/'release.lock').exists(),
 'commands':[json.loads(line) for line in commands.read_text().splitlines()] if commands.exists() else []}),flush=True)
'''.replace('TEST', repr(str(Path(__file__).resolve())))

    def test_actual_supervisor_refences_lease_loss_after_cas_and_after_marker_removal(self):
        for failure in ('after_cas', 'after_marker'):
            with self.subTest(failure=failure):
                result = subprocess.run([sys.executable, '-B', '-c', self.script(failure)],
                    capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr)
                state = json.loads(result.stdout.splitlines()[-1])
                self.assertEqual(state['outcome'], 'refused', result.stdout)
                self.assertTrue(state['paused']); self.assertTrue(state['marker'])
                self.assertTrue(state['original_unchanged']); self.assertFalse(state['mutex'])
                self.assertEqual(state['phase'], 'recovery_required')
                self.assertEqual(state['current_new'], failure == 'after_marker')

    def test_prove_mode_never_mutates_production_on_success_or_any_failure(self):
        for failure in ('proof_ok', 'proof_error', 'proof_restore_error', 'proof_lease', 'proof_cleanup_error'):
            with self.subTest(failure=failure):
                result = subprocess.run([sys.executable, '-B', '-c', self.script(failure)],
                    capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
                state = json.loads(result.stdout.splitlines()[-1])
                self.assertTrue(state['paused']); self.assertTrue(state['marker'])
                self.assertTrue(state['original_unchanged']); self.assertFalse(state['mutex'])
                self.assertFalse(state['current_new'])
                for command in state['commands']:
                    self.assertFalse(any(token in command for token in ('CAS', 'up', 'stop')), command)
                if failure == 'proof_ok': self.assertEqual(state['phase'], 'proof_verified')

    def test_worker_refences_when_its_own_guardian_is_killed(self):
        process = subprocess.Popen([sys.executable, '-B', '-c', self.script('guardian_death')],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            info = json.loads(process.stdout.readline())
            self.assertEqual(process.wait(timeout=15), -signal.SIGKILL)
            app = Path(info['app']); journal = Path(info['sidecar'])
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                phase = json.loads(journal.read_bytes())['phase']
                if phase == 'recovery_required' and b'=false' in (app/'env/backend.env').read_bytes(): break
                time.sleep(0.05)
            self.assertEqual(phase, 'recovery_required')
            self.assertIn(b'=false', (app/'env/backend.env').read_bytes())
            self.assertTrue((app/'backend-recovery-required').exists())
            # Killed guardian cannot clean its mutex; retaining it is fail closed.
            self.assertTrue((app/'release.lock').exists())
        finally:
            if process.poll() is None: process.kill(); process.wait(timeout=5)
            process.stdout.close(); process.stderr.close()


if __name__ == '__main__':
    unittest.main()
