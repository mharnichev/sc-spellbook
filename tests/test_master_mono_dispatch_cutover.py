import importlib.util
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import sys
import signal
import subprocess
import types
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/master-mono-dispatch-cutover.py'
SPEC = importlib.util.spec_from_file_location('cutover', SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)


class CutoverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        SPEC.loader.exec_module(MODULE)

    def test_flag_edit_preserves_every_other_byte(self):
        original = b'# private\r\nSECRET_KEY=synthetic\r\nMASTER_MONO_INVOICE_CREATE_ENABLED=true # retained\r\nOTHER=false\r\n'
        paused = MODULE.paused_env(original)
        self.assertEqual(paused, original.replace(b'=true #', b'=false #'))
        for bad in (b'OTHER=true\n', original + b'MASTER_MONO_INVOICE_CREATE_ENABLED=false\n',
                    original + b'master_mono_invoice_create_enabled=true\n',
                    b'MASTER_MONO_INVOICE_CREATE_ENABLED=unsupported\n'):
            with self.subTest(bad=bad), self.assertRaises(RuntimeError):
                MODULE.paused_env(bad)

    def test_private_cas_refuses_drift_and_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'backend.env'
            path.write_bytes(b'original'); path.chmod(0o600)
            MODULE.cas_env(path, b'original', b'paused')
            self.assertEqual(path.read_bytes(), b'paused')
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(RuntimeError):
                MODULE.cas_env(path, b'original', b'resumed')
            self.assertEqual(path.read_bytes(), b'paused')
            link = Path(directory) / 'link'; link.symlink_to(path)
            with self.assertRaises(RuntimeError):
                MODULE.cas_env(link, b'paused', b'resumed')
            path.chmod(0o644)
            with self.assertRaises(RuntimeError):
                MODULE.private_bytes(path)

    def test_failed_atomic_replace_preserves_exact_original_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'backend.env'
            path.write_bytes(b'original'); path.chmod(0o600)
            with patch.object(MODULE.os, 'replace', side_effect=OSError('synthetic replace failure')):
                with self.assertRaises(OSError): MODULE.cas_env(path, b'original', b'paused')
            self.assertEqual(path.read_bytes(), b'original')
            self.assertEqual([p.name for p in Path(directory).iterdir()], ['backend.env'])

    def test_drain_exempts_only_exact_pinned_historical_requests(self):
        protected = [{'id': 1, 'order_id': 3, 'hash': 'a'}, {'id': 2, 'order_id': 4, 'hash': 'b'}]
        baseline = dict(head=MODULE.SOURCE, unresolved=protected, requests='all', protected={'closures': 'two'}, compatibility='same',
                        closure_orders=[5, 6], closures=2, conflicts=0, sessions=2)
        stopped = {**baseline, 'sessions': 0}
        MODULE.verify_drain(baseline, stopped)
        for change in ({'unresolved': protected + [{'id': 9, 'order_id': 10, 'hash': 'old-but-ambiguous'}]},
                       {'unresolved': [protected[0], {**protected[1], 'hash': 'changed'}]},
                       {'requests': 'fresh'}, {'protected': {'closures': 'changed'}},
                       {'sessions': 1}, {'closure_orders': [5, 7]}, {'closures': 1}, {'compatibility': 'changed'}):
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                MODULE.verify_drain(baseline, {**stopped, **change})

    def test_clean_shutdown_requires_exit_logs_and_no_sigkill(self):
        info = {'State': {'Running': False, 'ExitCode': 0, 'OOMKilled': False, 'Error': '',
                          'FinishedAt': '2026-11-09T12:01:00Z', 'StartedAt': '2026-11-09T12:00:00Z'}}
        MODULE.verify_shutdown(info, b'Application shutdown complete.', [], api=True)
        for altered, logs, events in (({'ExitCode': 137}, b'Application shutdown complete.', []),
                                     ({'OOMKilled': True}, b'Application shutdown complete.', []),
                                     ({}, b'no shutdown evidence', []),
                                     ({}, b'Application shutdown complete.', [{'Action': 'kill', 'Actor': {'Attributes': {'signal': '9'}}}])):
            with self.subTest(altered=altered, logs=logs), self.assertRaises(RuntimeError):
                MODULE.verify_shutdown({'State': {**info['State'], **altered}}, logs, events, api=True)

    def test_candidate_config_accepts_checkout_drift_and_refuses_enabled_refunds(self):
        checkout, pilot = MODULE.CHECKOUT_FLAGS
        original = {MODULE.FLAG: True, 'DEBUG': False, checkout: True, pilot: False}
        target = {**original, checkout: False, MODULE.REFUND_FLAG: False}
        MODULE.verify_candidate_flags(original, target, 'backend')
        for changed in ({checkout: True}, {pilot: True}, {MODULE.REFUND_FLAG: True},
                        {'DEBUG': True}, {'NEW_FLAG': True}):
            with self.subTest(changed=changed), self.assertRaises(RuntimeError):
                MODULE.verify_candidate_flags(original, {**target, **changed}, 'backend')
        with self.assertRaises(RuntimeError):
            MODULE.verify_candidate_flags(original, original, 'backend')

    def test_paused_flags_allow_exactly_one_difference(self):
        original = {MODULE.FLAG: True, 'DEBUG': False, 'SHOP_CHECKOUT_ENABLED': False}
        MODULE.verify_flags(original, {**original, MODULE.FLAG: False}, paused=True)
        MODULE.verify_flags(original, original, paused=False)
        for values in (original, {**original, MODULE.FLAG: False, 'DEBUG': True},
                       {MODULE.FLAG: False}, {**original, MODULE.FLAG: False, 'NEW': False}):
            with self.subTest(values=values), self.assertRaises(RuntimeError):
                MODULE.verify_flags(original, values, paused=True)

    def test_effective_settings_probe_uses_process_environment_and_aliases_without_secrets(self):
        class Settings:
            def model_dump(self, by_alias=False):
                self_alias = by_alias
                if not self_alias: raise AssertionError('Aliases required')
                return {MODULE.FLAG: os.environ[MODULE.FLAG] == 'true', 'DEBUG': False,
                        'SECRET_KEY': 'PRIVATE_SYNTHETIC_SECRET', 'LIMIT': 10}
        modules = {'app': types.ModuleType('app'), 'app.core': types.ModuleType('app.core'),
                   'app.core.config': types.SimpleNamespace(Settings=Settings)}
        output = io.StringIO()
        with patch.dict(sys.modules, modules), patch.dict(os.environ, {MODULE.FLAG: 'true'}), \
             patch.object(Path, 'read_bytes', return_value=(MODULE.FLAG + '=false\0').encode()), \
             contextlib.redirect_stdout(output):
            exec(MODULE.FLAGS_CODE + MODULE.SETTINGS_FLAGS_CODE, {})
        self.assertEqual(json.loads(output.getvalue()), {MODULE.FLAG: False, 'DEBUG': False})
        self.assertNotIn('PRIVATE_SYNTHETIC_SECRET', output.getvalue())

    def test_journal_is_private_durable_and_unique(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'job.json'
            MODULE.persist(target, {'phase': 'prepared'}, exclusive=True)
            self.assertEqual(json.loads(target.read_text()), {'phase': 'prepared'})
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                MODULE.persist(target, {'phase': 'overwritten'}, exclusive=True)
            MODULE.persist(target, {'phase': 'paused'})
            self.assertEqual(json.loads(target.read_text())['phase'], 'paused')

    def setUp(self):
        source = patch.object(MODULE, 'SOURCE', 'previous_schema')
        source.start()
        self.addCleanup(source.stop)

    def runtime(self, directory):
        app = Path(directory); release = app / 'releases/new'
        (release / 'versions').mkdir(parents=True)
        (release / 'versions/production.env').write_text('BACKEND_IMAGE=synthetic@sha256:' + 'a' * 64 + '\n')
        (app / 'env').mkdir(); (app / 'backups').mkdir()
        (app / 'env/backend.env').write_bytes(b'SECRET_KEY=synthetic\nMASTER_MONO_INVOICE_CREATE_ENABLED=true\n')
        (app / 'env/backend.env').chmod(0o600)
        (app / 'old').mkdir(); (app / 'current').symlink_to(app / 'old')
        backup = app / 'backups/paired'; backup.mkdir(mode=0o700)
        for name in ('database.dump', 'files.tar.gz'):
            (backup / name).write_bytes(b'synthetic'); (backup / name).chmod(0o600)
        MODULE.persist(backup / 'manifest.json', {name: {'bytes': 9, 'sha256': MODULE.digest(b'synthetic')}
                       for name in ('database.dump', 'files.tar.gz')})
        marker = app / 'backend-recovery-required'
        marker.write_text(f'release={release.resolve()}\nbackup={backup}\nphase=pending_acceptance\n'); marker.chmod(0o600)

        candidate = {MODULE.FLAG: True, 'DEBUG': False, MODULE.REFUND_FLAG: False,
                     **dict.fromkeys(MODULE.CHECKOUT_FLAGS, False)}

        class Runtime(MODULE.Cutover):
            generation = 0
            running = True
            failure = None
            target = False
            requests = 'all'

            def service(self, name):
                return {'Id': str(self.generation + (1 if name == 'backend' else 2)) * 64,
                        'State': {'Running': self.running, 'ExitCode': 0, 'OOMKilled': False, 'Error': '',
                                  'StartedAt': '2026-11-09T12:00:00Z', 'FinishedAt': '2026-11-09T12:01:00Z',
                                  'Health': {'Status': 'healthy'}}}

            def flags(self, info):
                create = b'=true' in self.env.read_bytes()
                if self.generation > 0 or self.target:
                    return {**candidate, MODULE.FLAG: create}
                return {MODULE.FLAG: create, 'DEBUG': False, MODULE.CHECKOUT_FLAGS[0]: True}

            def candidate_flags(self):
                return {name: candidate.copy() for name in MODULE.WRITERS}

            def snapshot(self):
                return dict(head=MODULE.HEAD if self.target else MODULE.SOURCE, watermark='private timestamp',
                            sessions=2 if self.running else 0, requests=self.requests, lease_verified=True,
                            unresolved=[{'id': 1, 'order_id': 3, 'hash': 'a'}, {'id': 2, 'order_id': 4, 'hash': 'b'}],
                            closures=2, closure_orders=[5, 6], conflicts=0, protected={'orders': 'same', 'stock': 'same'}, compatibility='same')

            def run(self, command, data=None):
                if self.failure and self.failure in command:
                    raise RuntimeError('synthetic system failure')
                if command[:2] == ['docker', 'events']:
                    return b''
                if command[:2] == ['docker', 'logs']:
                    return b'Application shutdown complete.'
                if 'up' in command:
                    self.generation += 3; self.running = True
                if 'stop' in command:
                    self.running = False
                return b''

        # The CI Compose example is not this isolated fixture's private environment.
        with patch.dict(os.environ, BACKEND_ENV_FILE=str((app / 'env/backend.env').resolve()),
                        COMPOSE_FILE='', COMPOSE_PROFILES=''):
            job = Runtime(release, app)
        return job

    def test_inherited_configuration_overrides_remain_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            job = self.runtime(directory)
            expected = {'BACKEND_ENV_FILE': str(job.env), 'COMPOSE_FILE': '', 'COMPOSE_PROFILES': ''}
            for key in expected:
                with self.subTest(key=key), patch.dict(os.environ, {**expected, key: 'unexpected'}):
                    with self.assertRaises(RuntimeError):
                        MODULE.Cutover(job.release, job.app)

    def paused_runtime(self, directory, same_head=False):
        job = self.runtime(directory)
        job.target = same_head
        job.prepare(); job.running = False; job.pause()
        job.target = True; job.generation = 3; job.running = True
        job.paused()
        return job

    def test_same_head_release_completes_the_guarded_acceptance_cycle(self):
        with tempfile.TemporaryDirectory() as directory:
            job = self.paused_runtime(directory, same_head=True)
            self.assertEqual(job.load()['baseline']['head'], MODULE.HEAD)
            self.assertIn(b'=false', job.env.read_bytes())
            with patch.dict(os.environ, PILOT_MANUAL_GATE='verified', EXPECTED_RELEASE=str(job.release)):
                job.resume()
            job.accepted()
            (job.app / 'current').unlink(); (job.app / 'current').symlink_to(job.release)
            job.switched()
            self.assertEqual(job.load(allow_accepted_current=True)['phase'], 'accepted')
            self.assertTrue(job.running)
            self.assertIn(b'=true', job.env.read_bytes())

    def test_drain_requires_the_exact_supported_captured_head(self):
        with tempfile.TemporaryDirectory() as directory:
            job = self.runtime(directory)
            for head in (MODULE.SOURCE, MODULE.HEAD):
                baseline = {**job.snapshot(), 'head': head}
                MODULE.verify_drain(baseline, {**baseline, 'sessions': 0})
                for changed_head in (MODULE.SOURCE, MODULE.HEAD, 'unknown'):
                    if changed_head == head:
                        continue
                    with self.subTest(head=head, changed_head=changed_head), self.assertRaises(RuntimeError):
                        MODULE.verify_drain(baseline, {**baseline, 'head': changed_head, 'sessions': 0})
            baseline = {**job.snapshot(), 'head': 'unknown'}
            with self.assertRaises(RuntimeError):
                MODULE.verify_drain(baseline, {**baseline, 'sessions': 0})

    def test_unknown_head_cannot_be_prepared(self):
        with tempfile.TemporaryDirectory() as directory:
            job = self.runtime(directory); snapshot = {**job.snapshot(), 'head': 'unknown'}
            with patch.object(job, 'snapshot', return_value=snapshot), self.assertRaises(RuntimeError):
                job.prepare()
            self.assertFalse(job.journal.exists())
            self.assertEqual(job.generation, 0)

    def test_schema_drift_during_either_pause_snapshot_is_refused(self):
        for same_head in (False, True):
            for second_snapshot in (False, True):
                with self.subTest(same_head=same_head, second_snapshot=second_snapshot), tempfile.TemporaryDirectory() as directory:
                    job = self.runtime(directory); job.target = same_head; job.prepare(); job.running = False
                    baseline = job.snapshot()
                    changed = {**baseline, 'head': MODULE.SOURCE if same_head else MODULE.HEAD}
                    snapshots = [baseline, changed] if second_snapshot else [changed]
                    with patch.object(job, 'snapshot', side_effect=snapshots), self.assertRaises(RuntimeError):
                        job.pause()
                    self.assertFalse(job.running)
                    self.assertEqual(job.load()['phase'], 'pause_intent' if second_snapshot else 'prepared')
                    self.assertIn(b'=false' if second_snapshot else b'=true', job.env.read_bytes())

    def test_same_head_early_recovery_only_reconciles_stopped_original_pair(self):
        for phase in ('prepared', 'pause_intent'):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as directory:
                job = self.runtime(directory); job.target = True; job.prepare()
                state = job.load(); job.save(state, phase)
                if phase == 'pause_intent':
                    MODULE.cas_env(job.env, job.original(state), MODULE.paused_env(job.original(state)))
                # Backup is not available at these checkpoints and cannot authorize a start.
                (job.app / 'backups/paired/manifest.json').unlink()
                with patch.dict(os.environ, PILOT_MANUAL_GATE='verified', EXPECTED_RELEASE=str(job.release)):
                    job.recover_paused()
                self.assertEqual(job.load()['phase'], 'paused')
                self.assertEqual(job.generation, 0)
                self.assertFalse(job.running)
                self.assertIn(b'=false', job.env.read_bytes())

    def test_same_head_target_recovery_requires_verified_backup_and_reviewed_phase(self):
        for phase in ('paused', 'paused_verified', 'recovery_required'):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as directory:
                job = self.paused_runtime(directory, same_head=True)
                state = job.load(); job.save(state, phase)
                generation = job.generation
                with patch.dict(os.environ, PILOT_MANUAL_GATE='verified', EXPECTED_RELEASE=str(job.release)):
                    job.recover_paused()
                self.assertEqual(job.load()['phase'], 'paused_verified')
                self.assertGreater(job.generation, generation)
                self.assertTrue(job.running)
                self.assertIn(b'=false', job.env.read_bytes())
                with self.assertRaises(RuntimeError): job.accepted()

    def test_same_head_recovery_never_starts_without_paired_backup_or_pending_acceptance(self):
        for change in ('missing', 'checksum', 'marker'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                job = self.paused_runtime(directory, same_head=True)
                state = job.load(); job.save(state, 'paused')
                if change == 'missing': (job.app / 'backups/paired/manifest.json').unlink()
                if change == 'checksum': (job.app / 'backups/paired/database.dump').write_bytes(b'changed')
                if change == 'marker':
                    job.marker.write_text(job.marker.read_text().replace('phase=pending_acceptance\n', ''))
                generation = job.generation
                with patch.dict(os.environ, PILOT_MANUAL_GATE='verified', EXPECTED_RELEASE=str(job.release)):
                    with self.assertRaises((RuntimeError, FileNotFoundError)): job.recover_paused()
                self.assertEqual(job.generation, generation)
                self.assertFalse(job.running)
                self.assertIn(b'=false', job.env.read_bytes())
                self.assertTrue(job.marker.exists())

    def test_same_head_recovery_refuses_unknown_regressed_or_post_stop_drifted_head(self):
        for change in ('unknown', 'regressed', 'post_stop'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                job = self.paused_runtime(directory, same_head=True)
                baseline = job.snapshot()
                changed = {**baseline, 'head': 'unknown' if change == 'unknown' else MODULE.SOURCE, 'sessions': 0}
                snapshots = [baseline, changed] if change == 'post_stop' else [changed]
                generation = job.generation
                with patch.object(job, 'snapshot', side_effect=snapshots), \
                     patch.dict(os.environ, PILOT_MANUAL_GATE='verified', EXPECTED_RELEASE=str(job.release)):
                    with self.assertRaises(RuntimeError): job.recover_paused()
                self.assertEqual(job.generation, generation)
                self.assertIn(b'=false', job.env.read_bytes())

    def test_same_head_startup_still_requires_exact_target_head(self):
        with tempfile.TemporaryDirectory() as directory:
            job = self.runtime(directory); job.target = True; job.prepare(); job.running = False; job.pause()
            job.generation = 3; job.running = True; job.target = False
            with self.assertRaises(RuntimeError): job.paused()
            self.assertEqual(job.load()['phase'], 'paused')
            self.assertIn(b'=false', job.env.read_bytes())

    def test_complete_fenced_cycle_requires_explicit_resume_and_new_container_identities(self):
        with tempfile.TemporaryDirectory() as directory:
            job = self.paused_runtime(directory)
            self.assertIn(b'=false', job.env.read_bytes())
            with self.assertRaises(RuntimeError): job.accepted()
            with self.assertRaises(RuntimeError): job.resume()
            with patch.dict(os.environ, PILOT_MANUAL_GATE='verified', EXPECTED_RELEASE=str(job.release)):
                job.resume()
            self.assertEqual(job.load()['phase'], 'resumed')
            self.assertIn(b'=true', job.env.read_bytes())
            job.accepted()
            with self.assertRaises(RuntimeError): job.resume()
            job.generation += 3
            with self.assertRaises(RuntimeError): job.accepted()

    def test_failed_resume_stops_new_writers_refences_and_keeps_recovery_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            job = self.paused_runtime(directory); job.failure = 'up'
            with patch.dict(os.environ, PILOT_MANUAL_GATE='verified', EXPECTED_RELEASE=str(job.release)):
                with self.assertRaises(RuntimeError): job.resume()
            self.assertFalse(job.running)
            self.assertIn(b'=false', job.env.read_bytes())
            self.assertTrue(job.marker.exists())
            self.assertEqual(job.load()['phase'], 'recovery_required')
            with self.assertRaises(RuntimeError): job.accepted()

    def test_pause_drift_leaves_fence_or_stopped_writers_without_restoring_original(self):
        with tempfile.TemporaryDirectory() as directory:
            job = self.runtime(directory); job.prepare(); job.running = False
            job.requests = 'fresh ambiguous dispatch'
            with self.assertRaises(RuntimeError): job.pause()
            self.assertEqual(job.load()['phase'], 'prepared')
            self.assertFalse(job.running)
            with self.assertRaises(FileExistsError): job.prepare()

    def test_restart_between_paused_verification_and_resume_is_not_admitted(self):
        with tempfile.TemporaryDirectory() as directory:
            job = self.paused_runtime(directory)
            job.generation += 3
            with patch.dict(os.environ, PILOT_MANUAL_GATE='verified', EXPECTED_RELEASE=str(job.release)):
                with self.assertRaises(RuntimeError): job.resume()
            self.assertIn(b'=false', job.env.read_bytes())
        with tempfile.TemporaryDirectory() as directory:
            job = self.paused_runtime(directory)
            job.env.write_bytes(job.env.read_bytes() + b'NEW_SETTING=false\n')
            with patch.dict(os.environ, PILOT_MANUAL_GATE='verified', EXPECTED_RELEASE=str(job.release)):
                with self.assertRaises(RuntimeError): job.resume()
            self.assertIn(b'=false', job.env.read_bytes())

    def test_changed_backup_and_pins_block_resume_before_enable(self):
        for change in ('backup', 'pins'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                job = self.paused_runtime(directory)
                target = job.app / 'backups/paired/database.dump' if change == 'backup' else job.release / 'versions/production.env'
                target.write_bytes(b'changed')
                with patch.dict(os.environ, PILOT_MANUAL_GATE='verified', EXPECTED_RELEASE=str(job.release)):
                    with self.assertRaises(RuntimeError): job.resume()
                self.assertIn(b'=false', job.env.read_bytes())

    def test_failed_journal_after_enable_still_stops_and_refences(self):
        with tempfile.TemporaryDirectory() as directory:
            job = self.paused_runtime(directory)
            save = job.save
            def failing_save(state, phase):
                if phase in ('resumed', 'recovery_required'):
                    raise OSError('synthetic disk failure')
                save(state, phase)
            with patch.object(job, 'save', side_effect=failing_save), patch.dict(os.environ, PILOT_MANUAL_GATE='verified', EXPECTED_RELEASE=str(job.release)):
                with self.assertRaises(OSError): job.resume()
            self.assertFalse(job.running)
            self.assertIn(b'=false', job.env.read_bytes())
            self.assertTrue(job.marker.exists())

    def test_original_file_process_flag_drift_blocks_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            job = self.runtime(directory)
            with patch.object(job, 'flags', return_value={MODULE.FLAG: False, 'DEBUG': False}):
                with self.assertRaises(RuntimeError): job.prepare()
            self.assertFalse(job.journal.exists())

    def test_inspected_recovery_only_recreates_paused_new_code(self):
        with tempfile.TemporaryDirectory() as directory:
            job = self.paused_runtime(directory); job.failure = 'up'
            with patch.dict(os.environ, PILOT_MANUAL_GATE='verified', EXPECTED_RELEASE=str(job.release)):
                with self.assertRaises(RuntimeError): job.resume()
                job.failure = None
                job.recover_paused()
            self.assertEqual(job.load()['phase'], 'paused_verified')
            self.assertTrue(job.running)
            self.assertIn(b'=false', job.env.read_bytes())
            with self.assertRaises(RuntimeError): job.accepted()

    def test_source_recovery_reconciles_pause_intent_but_never_starts_old_code(self):
        with tempfile.TemporaryDirectory() as directory:
            job = self.runtime(directory); job.prepare(); job.running = False
            state = job.load(); job.save(state, 'pause_intent')
            MODULE.cas_env(job.env, job.original(state), MODULE.paused_env(job.original(state)))
            with patch.dict(os.environ, PILOT_MANUAL_GATE='verified', EXPECTED_RELEASE=str(job.release)):
                job.recover_paused()
            self.assertEqual(job.load()['phase'], 'paused')
            self.assertFalse(job.running)
            self.assertFalse(job.target)
            self.assertIn(b'=false', job.env.read_bytes())

    def test_recovery_preserves_fence_on_unknown_new_dispatch_or_config_drift(self):
        for change in ('dispatch', 'config'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                job = self.paused_runtime(directory)
                state = job.load(); job.save(state, 'recovery_required')
                if change == 'dispatch': job.requests = 'unexpected-new-dispatch'
                else: job.env.write_bytes(job.env.read_bytes() + b'UNKNOWN_SETTING=true\n')
                with patch.dict(os.environ, PILOT_MANUAL_GATE='verified', EXPECTED_RELEASE=str(job.release)):
                    with self.assertRaises(RuntimeError): job.recover_paused()
                self.assertFalse(job.running)
                self.assertIn(b'=false', job.env.read_bytes())
                self.assertTrue(job.marker.exists())

    def test_acceptance_failure_can_refence_resumed_pair_without_start_or_old_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            job = self.paused_runtime(directory)
            with patch.dict(os.environ, PILOT_MANUAL_GATE='verified', EXPECTED_RELEASE=str(job.release)):
                job.resume()
            generation = job.generation
            job.refence()
            self.assertFalse(job.running)
            self.assertEqual(job.generation, generation)
            self.assertIn(b'=false', job.env.read_bytes())
            self.assertEqual(job.load()['phase'], 'recovery_required')
            self.assertTrue(job.marker.exists())

    def test_interruption_after_current_switch_keeps_verified_acceptance_retry_available(self):
        with tempfile.TemporaryDirectory() as directory:
            job = self.paused_runtime(directory)
            with patch.dict(os.environ, PILOT_MANUAL_GATE='verified', EXPECTED_RELEASE=str(job.release)):
                job.resume()
            job.accepted()
            (job.app / 'current').unlink(); (job.app / 'current').symlink_to(job.release)
            with self.assertRaises(RuntimeError): job.load()
            job.accepted()  # Rechecks pins, exact resumed IDs, flags, protected history, backup.
            self.assertTrue(job.marker.exists())
            job.switched()
            self.assertEqual(job.load(allow_accepted_current=True)['phase'], 'accepted')
            job.marker.unlink()
            self.assertEqual(job.load(allow_accepted_current=True)['phase'], 'accepted')
            with self.assertRaises(FileNotFoundError): job.accepted()

    def test_current_switch_without_acceptance_checkpoint_is_never_admitted(self):
        with tempfile.TemporaryDirectory() as directory:
            job = self.paused_runtime(directory)
            (job.app / 'current').unlink(); (job.app / 'current').symlink_to(job.release)
            with self.assertRaises(RuntimeError): job.load(allow_accepted_current=True)

    def test_lost_lease_after_current_switch_does_not_commit_acceptance(self):
        with tempfile.TemporaryDirectory() as directory:
            job = self.paused_runtime(directory)
            with patch.dict(os.environ, PILOT_MANUAL_GATE='verified', EXPECTED_RELEASE=str(job.release)):
                job.resume()
            job.accepted()
            (job.app / 'current').unlink(); (job.app / 'current').symlink_to(job.release)
            with patch.object(job, 'snapshot', return_value={'lease_verified': False}):
                with self.assertRaisesRegex(RuntimeError, 'lease required'):
                    job.switched()
            self.assertTrue(job.marker.exists())
            self.assertEqual(job.load(allow_accepted_current=True)['phase'], 'accepting')

    def test_forward_recovery_after_current_switch_never_reverts_pointer_or_starts_old_code(self):
        with tempfile.TemporaryDirectory() as directory:
            job = self.paused_runtime(directory)
            with patch.dict(os.environ, PILOT_MANUAL_GATE='verified', EXPECTED_RELEASE=str(job.release)):
                job.resume(); job.accepted()
                (job.app / 'current').unlink(); (job.app / 'current').symlink_to(job.release)
                job.refence(); job.recover_paused()
                self.assertEqual((job.app / 'current').resolve(), job.release)
                self.assertEqual(job.load(allow_accepted_current=True)['phase'], 'paused_verified')
                self.assertIn(b'=false', job.env.read_bytes())
                job.resume()
            job.accepted(); job.switched()
            self.assertEqual((job.app / 'current').resolve(), job.release)
            self.assertTrue(job.running)
            self.assertTrue(job.marker.exists())

    def test_wrong_release_stale_journal_and_unrelated_current_are_refused(self):
        for change in ('marker', 'journal', 'current'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                job = self.paused_runtime(directory)
                if change == 'marker': job.marker.write_text('release=/wrong/release\nphase=pending_acceptance\n')
                if change == 'journal':
                    state = job.load(); state['release'] = '/wrong/release'; MODULE.persist(job.journal, state)
                if change == 'current':
                    (job.app / 'other').mkdir()
                    (job.app / 'current').unlink(); (job.app / 'current').symlink_to(job.app / 'other')
                with patch.dict(os.environ, PILOT_MANUAL_GATE='verified', EXPECTED_RELEASE=str(job.release)):
                    with self.assertRaises(RuntimeError): job.resume()
                self.assertIn(b'=false', job.env.read_bytes())

    def test_sighup_and_sigterm_after_enable_refence_in_a_real_child_process(self):
        for number in (signal.SIGHUP, signal.SIGTERM):
            with self.subTest(signal=number):
                code = '''import runpy,tempfile,os,signal,json
ns=runpy.run_path(TEST_FILE,run_name='fixture')
t=ns['CutoverTests']();t.setUpClass();m=ns['MODULE'];m.install_signal_handlers()
with tempfile.TemporaryDirectory() as directory:
 job=t.paused_runtime(directory);run=job.run
 def interrupted_run(command,data=None):
  result=run(command,data)
  if 'up' in command:os.kill(os.getpid(),SIGNAL)
  return result
 job.run=interrupted_run
 os.environ.update(PILOT_MANUAL_GATE='verified',EXPECTED_RELEASE=str(job.release))
 try:job.resume()
 except m.CutoverInterrupted:pass
 print(json.dumps({'phase':job.load()['phase'],'running':job.running,'paused':b'=false' in job.env.read_bytes(),'marker':job.marker.exists()}))
'''.replace('TEST_FILE', repr(str(Path(__file__).resolve()))).replace('SIGNAL', str(int(number)))
                result = subprocess.run([sys.executable, '-B', '-c', code], capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), {'phase': 'recovery_required', 'running': False, 'paused': True, 'marker': True})

    def test_first_termination_during_ordinary_failure_cleanup_cannot_interrupt_stop(self):
        for number in (signal.SIGHUP, signal.SIGTERM):
            with self.subTest(signal=number):
                code = '''import runpy,tempfile,os,json
ns=runpy.run_path(TEST_FILE,run_name='fixture')
t=ns['CutoverTests']();t.setUpClass();m=ns['MODULE'];m.install_signal_handlers()
with tempfile.TemporaryDirectory() as directory:
 job=t.paused_runtime(directory);run=job.run
 def interrupted_run(command,data=None):
  if 'up' in command:
   run(command,data)
   raise RuntimeError('ordinary post-start failure')
  if 'stop' in command:os.kill(os.getpid(),SIGNAL)
  return run(command,data)
 job.run=interrupted_run
 os.environ.update(PILOT_MANUAL_GATE='verified',EXPECTED_RELEASE=str(job.release))
 try:job.resume()
 except RuntimeError:pass
 print(json.dumps({'phase':job.load()['phase'],'running':job.running,'paused':b'=false' in job.env.read_bytes(),'marker':job.marker.exists()}))
'''.replace('TEST_FILE', repr(str(Path(__file__).resolve()))).replace('SIGNAL', str(int(number)))
                result = subprocess.run([sys.executable, '-B', '-c', code], capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), {'phase': 'recovery_required', 'running': False, 'paused': True, 'marker': True})


if __name__ == '__main__':
    unittest.main()
