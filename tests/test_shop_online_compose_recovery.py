import copy
from contextlib import ExitStack, redirect_stdout
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT/'scripts'/filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


OP = load('compose_recovery_test', 'recover-shop-online-compose.py')
OLD = load('original_activation_recovery_test', 'activate-shop-online.py')
PIN = 'ghcr.io/mharnichev/sc-be/api@sha256:'+'a'*64
SOURCE = 'ghcr.io/mharnichev/sc-be/api@sha256:'+'b'*64


class Fixture:
    def __init__(self, directory):
        self.app = Path(directory).resolve()
        self.root = self.app/'releases/pending'
        (self.root/'scripts').mkdir(parents=True)
        (self.root/'versions').mkdir()
        (self.root/'docker-compose.prod.yml').write_text('immutable old compose fixture')
        (self.root/'versions/production.env').write_text('BACKEND_IMAGE='+PIN+'\n')
        accepted = self.app/'releases/accepted'
        accepted.mkdir()
        (self.app/'current').symlink_to(accepted)
        (self.app/'env').mkdir()
        for name in OP.ENV_FILES.values():
            OLD.persist_bytes(self.app/('env/'+name+'.env'), b'FIXTURE=private\n')
        (self.app/'release.lock').mkdir()
        (self.app/'release.lock/pid').write_text(str(os.getppid()))
        (self.app/'backend-recovery-required').write_text('release='+str(self.root)+'\nphase=pending_acceptance\n')
        self.stage = self.app/'reviewed-staging'
        self.stage.mkdir(mode=0o700)
        self.hashes = {}
        for name in ('recover-shop-online-compose.py', 'run-shop-online-compose-recovery.sh'):
            OLD.persist_bytes(self.stage/name, (ROOT/'scripts'/name).read_bytes())
            self.hashes[name] = OP.sha((self.stage/name).read_bytes())
        self.tools = {}
        for name in ('activate-shop-online.py', 'shop-online-config.py', 'run-shop-online-activation.sh'):
            path = self.root/'scripts'/name
            path.write_bytes((ROOT/'scripts'/name).read_bytes())
            self.tools[name] = OP.sha(path.read_bytes())
        (self.app/'backups').mkdir()
        self.state_dir = self.app/'backups'/('shop-online-activation-'+'d'*24)
        self.state_dir.mkdir(mode=0o700)
        self.baseline = dict(head=[OLD.HEAD], identity={'database': 'barbershop_platform'},
            operator={'id': 1, 'is_active': True, 'can_record_sales': True},
            grants={'admins': [{'id': 1, 'can_record_sales': True}], 'masters': []},
            shop_orders=0, inventory=[], sequences={},
            tables={name: {'rows': 0, 'sha256': 'fixture'} for name in OLD.SHOP_TABLES})
        self.current = copy.deepcopy(self.baseline)
        self.current['tables']['product_views'] = {'rows': 9, 'sha256': 'legitimate-runtime-drift'}
        self.plan = {'aliases': {'fixture': True}, 'profile_sha256': 'synthetic-profile-hash'}
        self.before, self.after = b'FIXTURE=false\n', b'FIXTURE=private\n'
        OLD.persist_bytes(self.state_dir/'before.env', self.before)
        OLD.persist_bytes(self.state_dir/'after.env', self.after)
        OLD.persist(self.state_dir/'snapshot.json', self.baseline)
        OLD.persist(self.state_dir/'plan.json', self.plan)
        proof = dict(env_sha256=OP.sha(self.before), source_image=SOURCE,
                     merchant_profile_sha256=self.plan['profile_sha256'], verified=True)
        OLD.persist(self.state_dir/'proof.json', proof)
        self.state = dict(run=str(self.state_dir), release=str(self.root), image=PIN, source_image=SOURCE,
            head=OLD.HEAD, operator_id=1, pre_restart_original_verified=True, phase='verified', tools=self.tools,
            before_sha256=OP.sha(self.before), after_sha256=OP.sha(self.after),
            snapshot_sha256=OP.sha(OP.canonical(self.baseline)), plan_sha256=OP.sha(OP.canonical(self.plan)),
            proof_sha256=OP.sha(OP.canonical(proof)))
        self.marker = self.app/'shop-online-activation-required'
        OLD.persist(self.marker, self.state)
        self.before_config = dict(name='soulcuts', services={
            'backend': {'image': PIN, 'environment': dict.fromkeys(OP.KEYS, 'false'), 'ports': []},
            'booking-sms-reminders': {'image': PIN, 'environment': {'UNCHANGED': 'yes'}},
            'shop': {'image': 'fixture-unchanged-shop', 'ports': ['fixture']}})
        self.after_config = copy.deepcopy(self.before_config)
        self.after_config['services']['backend']['environment'].update(dict.fromkeys(OP.KEYS, 'true'))
        self.running = True
        self.flags = 'false'
        self.calls = []
        self.mutate_after_db = None

    @property
    def report(self):
        return self.app/'backups'/('shop-online-compose-recovery-'+'d'*24)

    def run(self, args, *, data=None, timeout=120):
        self.calls.append((args, data))
        if args[0] == 'python3':
            return SOURCE if '/accepted/' in args[-1] else PIN
        if args[:2] == ['docker', 'compose']:
            assert args[-3:] == ['config', '--format', 'json']
            return json.dumps(self.after_config if str(self.report/'overlay.yml') in args else self.before_config)
        if args[:2] == ['docker', 'ps']:
            service = next(arg.split('=', 2)[-1] for arg in args if arg.startswith('label=com.docker.compose.service='))
            return {'backend': 'a'*12, 'booking-sms-reminders': 'b'*12, 'postgres': 'c'*12}[service]
        if args[:2] == ['docker', 'inspect']:
            service = 'backend' if args[-1] == 'a'*12 else 'booking-sms-reminders'
            running = self.running[service] if isinstance(self.running, dict) else self.running
            if '--format' in args:
                return str(running).lower() if '.State.Running' in args[3] else PIN
            return json.dumps([{'Config': {'Image': PIN, 'Env': [key+'='+self.flags for key in OP.KEYS],
                'Labels': {'com.docker.compose.project': 'soulcuts', 'com.docker.compose.service': service}},
                'State': {'Running': running, 'StartedAt': 'fixture-start'}}])
        if args[:2] == ['docker', 'exec']:
            rows = [{'kind': k, 'value': v} for k, v in self.current.items() if k not in ('tables', 'sequences')]
            for key, kind in (('tables', 'table'), ('sequences', 'sequence')):
                rows += [{'kind': kind, 'name': k, 'value': v} for k, v in self.current[key].items()]
            result = '\n'.join(json.dumps(row) for row in rows)
            if self.mutate_after_db:
                self.mutate_after_db()
            return result
        raise AssertionError('Unexpected controlled command')

    def patches(self):
        stack = ExitStack()
        stack.enter_context(patch.object(OP, 'APP', self.app))
        stack.enter_context(patch.object(OP, 'TOOLS', self.stage))
        stack.enter_context(patch.object(OP, 'import_original', return_value=OLD))
        stack.enter_context(patch.object(OLD, 'APP', self.app))
        stack.enter_context(patch.object(OLD, 'TOOLS', self.root/'scripts'))
        stack.enter_context(patch.object(OLD, 'run', side_effect=self.run))
        stack.enter_context(patch.object(OLD, 'validate_plan'))
        stack.enter_context(patch.object(OLD, 'edit_env', return_value=self.after))
        stack.enter_context(patch.object(os, 'kill'))
        env = {key: value for key, value in os.environ.items() if key not in OP.PIN_KEYS}
        env.update(EXPECTED_RELEASE=str(self.root), EXPECTED_BACKEND_IMAGE=PIN, BACKEND_IMAGE=PIN,
            BACKEND_ENV_FILE=str(self.app/'env/backend.env'), POSTGRES_ENV_FILE=str(self.app/'env/postgres.env'),
            RELEASE_LOCK_OWNER_PID=str(os.getppid()),
            SHOP_ONLINE_COMPOSE_HELPER_SHA256=self.hashes['recover-shop-online-compose.py'],
            SHOP_ONLINE_COMPOSE_WRAPPER_SHA256=self.hashes['run-shop-online-compose-recovery.sh'])
        env.update({key: str(self.app/('env/'+name+'.env')) for key, name in OP.ENV_FILES.items()})
        stack.enter_context(patch.dict(os.environ, env, clear=True))
        stack.enter_context(redirect_stdout(io.StringIO()))
        return stack


class ComposeRecoveryTests(unittest.TestCase):
    def test_config_allows_exactly_three_backend_string_false_to_true_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            f = Fixture(directory)
            OP.validate_delta(f.before_config, f.after_config, PIN)
            for mutation in ('port', 'image', 'reminder', 'missing', 'bool', 'extra', 'project'):
                after = copy.deepcopy(f.after_config)
                if mutation == 'port': after['services']['backend']['ports'] = ['public-exposure']
                elif mutation == 'image': after['services']['shop']['image'] = 'foreign'
                elif mutation == 'reminder': after['services']['booking-sms-reminders']['environment']['UNCHANGED'] = 'no'
                elif mutation == 'missing': del after['services']['backend']['environment'][OP.KEYS[0]]
                elif mutation == 'bool': after['services']['backend']['environment'][OP.KEYS[0]] = True
                elif mutation == 'extra': after['services']['backend']['environment']['FOREIGN'] = 'true'
                else: after['name'] = 'foreign'
                with self.subTest(mutation=mutation), self.assertRaises(RuntimeError):
                    OP.validate_delta(f.before_config, after, PIN)

    def test_protocol_preserves_both_fences_env_and_old_tools_with_legitimate_initial_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            f = Fixture(directory)
            with f.patches():
                OP.execute('prepare', f.state_dir)
                self.assertTrue(f.running)
                journal = OLD.json_private(f.report/'journal.json')
                self.assertEqual(journal['phase'], 'prepared_before_stop')
                f.running = False
                OP.execute('after-stop', f.state_dir)
                OP.execute('before-restart', f.state_dir)
                f.running, f.flags = True, 'true'
                OP.execute('record-restart', f.state_dir)
                self.assertEqual(OLD.json_private(f.report/'journal.json')['phase'], 'restart_returned_not_accepted')
                self.assertEqual((f.app/'env/backend.env').read_bytes(), f.after)
                self.assertEqual(OLD.json_private(f.marker), f.state)
                self.assertTrue((f.app/'backend-recovery-required').exists())
                self.assertEqual(OLD.tool_hashes(), f.tools)

    def test_ack_loss_refuses_apply_retry_requires_explicit_reconcile_and_fresh_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            f = Fixture(directory)
            with f.patches():
                OP.execute('prepare', f.state_dir)
                with self.assertRaisesRegex(RuntimeError, 'explicit reconcile'):
                    OP.execute('prepare', f.state_dir)
                OP.execute('reconcile', f.state_dir)
                f.running = False
                OP.execute('after-stop', f.state_dir)
                OP.execute('before-restart', f.state_dir)
                f.running, f.flags = True, 'true'
                # Lost Docker ACK: a healthy desired runtime is not restarted.
                with self.assertRaisesRegex(RuntimeError, 'already run desired flags'):
                    OP.execute('reconcile', f.state_dir)
                f.running = False
                OP.execute('reconcile', f.state_dir)
                f.current['tables']['product_views']['rows'] += 1
                OP.execute('after-stop', f.state_dir)
                OP.execute('before-restart', f.state_dir)

    def test_initial_prepare_refuses_already_desired_running_without_stopping_writers(self):
        with tempfile.TemporaryDirectory() as directory:
            f = Fixture(directory)
            f.flags = 'true'
            with f.patches(), self.assertRaises(RuntimeError):
                OP.execute('prepare', f.state_dir)
            self.assertTrue(f.running)
            self.assertTrue(all('stop' not in args and 'up' not in args for args, _ in f.calls))

    def test_explicit_reconcile_of_each_partial_runtime_recaptures_stopped_snapshot(self):
        for running_service in ('backend', 'booking-sms-reminders'):
            with self.subTest(running_service=running_service), tempfile.TemporaryDirectory() as directory:
                f = Fixture(directory)
                with f.patches():
                    OP.execute('prepare', f.state_dir)
                    f.flags = 'true'
                    f.running = {name: name == running_service for name in ('backend', 'booking-sms-reminders')}
                    OP.execute('reconcile', f.state_dir)
                    self.assertEqual(OLD.json_private(f.report/'journal.json')['phase'], 'reconciled_before_stop')
                    f.running = False
                    OP.execute('after-stop', f.state_dir)
                    OP.execute('before-restart', f.state_dir)

    def test_reconcile_already_desired_running_preserves_journal_and_requests_manual_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            f = Fixture(directory)
            with f.patches():
                OP.execute('prepare', f.state_dir)
                f.running, f.flags = True, 'true'
                journal = (f.report/'journal.json').read_bytes()
                with self.assertRaisesRegex(RuntimeError, 'primary runtime verification required, no restart'):
                    OP.execute('reconcile', f.state_dir)
                self.assertEqual((f.report/'journal.json').read_bytes(), journal)
                self.assertTrue(all('stop' not in args and 'up' not in args for args, _ in f.calls))

    def test_env_state_compose_tool_and_overlay_drift_block_before_restart(self):
        for mutation in ('env', 'state', 'compose', 'tool', 'overlay'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                f = Fixture(directory)
                with f.patches():
                    OP.execute('prepare', f.state_dir)
                    f.running = False
                    OP.execute('after-stop', f.state_dir)
                    if mutation == 'env': OLD.persist_bytes(f.app/'env/backend.env', b'FOREIGN=true\n', replace=True)
                    elif mutation == 'state': OLD.persist(f.marker, {**f.state, 'operator_id': 3}, replace=True)
                    elif mutation == 'compose': (f.root/'docker-compose.prod.yml').write_text('foreign compose')
                    elif mutation == 'tool': (f.stage/'recover-shop-online-compose.py').write_text('foreign tool')
                    else: OLD.persist_bytes(f.report/'overlay.yml', b'services: {}\n', replace=True)
                    with self.assertRaises(RuntimeError): OP.execute('before-restart', f.state_dir)
                    self.assertTrue(f.marker.exists())

    def test_post_stop_shop_facts_and_operator_grant_drift_refused(self):
        for mutation in ('shop', 'grants', 'operator', 'database'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                f = Fixture(directory)
                with f.patches():
                    OP.execute('prepare', f.state_dir)
                    f.running = False
                    if mutation == 'shop': f.current['shop_orders'] = 1
                    elif mutation == 'grants': f.current['grants'] = {'foreign': True}
                    elif mutation == 'operator': f.current['operator'] = None
                    else: f.current['identity']['role'] = 'foreign'
                    with self.assertRaises(RuntimeError): OP.execute('after-stop', f.state_dir)

    def test_fresh_snapshot_drift_and_env_change_during_db_await_refused(self):
        for mutation in ('db', 'env'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                f = Fixture(directory)
                with f.patches():
                    OP.execute('prepare', f.state_dir)
                    f.running = False
                    OP.execute('after-stop', f.state_dir)
                    if mutation == 'db': f.current['tables']['product_views']['rows'] += 1
                    else: f.mutate_after_db = lambda: OLD.persist_bytes(f.app/'env/backend.env', b'FOREIGN=true\n', replace=True)
                    with self.assertRaises(RuntimeError): OP.execute('before-restart', f.state_dir)
                    self.assertEqual(OLD.json_private(f.report/'journal.json')['phase'], 'stopped_snapshot')

    def test_journal_fsync_failure_is_reported_before_any_writer_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            f = Fixture(directory)
            with f.patches():
                native = OLD.resync
                def failed(path):
                    if path.name == 'journal.json': raise OSError('injected journal fsync failure')
                    return native(path)
                with patch.object(OLD, 'resync', side_effect=failed), self.assertRaises(OSError):
                    OP.execute('prepare', f.state_dir)
                self.assertTrue(f.running)
                self.assertTrue(all('stop' not in args and 'up' not in args for args, _ in f.calls))

    def test_source_tool_hash_owner_and_inherited_override_guards(self):
        with tempfile.TemporaryDirectory() as directory:
            f = Fixture(directory)
            with f.patches():
                for key, value in (('RELEASE_LOCK_OWNER_PID', '-1'), ('EXPECTED_BACKEND_IMAGE', SOURCE),
                                   ('SHOP_ONLINE_COMPOSE_HELPER_SHA256', '0'*64), ('SHOP_IMAGE', 'foreign'),
                                   ('CADDY_ENV_FILE', '/foreign'), ('UNREVIEWED_ENV_FILE', '/foreign')):
                    with self.subTest(key=key), patch.dict(os.environ, {key: value}), self.assertRaises(RuntimeError):
                        OP.context(f.state_dir)
                f.state['source_image'] = 'foreign'
                OLD.persist(f.marker, f.state, replace=True)
                with self.assertRaises(RuntimeError): OP.context(f.state_dir)


class ComposeRecoveryWrapperTests(unittest.TestCase):
    def exercise(self, failure=None, mode='apply'):
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory).resolve()
            root = app/'releases/pending'
            (root/'scripts').mkdir(parents=True)
            (root/'scripts/release-lock.sh').write_bytes((ROOT/'scripts/release-lock.sh').read_bytes())
            (root/'scripts/release-backend-pin.py').write_text('print('+repr(PIN)+')\n')
            stage = app/'staging'
            stage.mkdir(mode=0o700)
            (app/'backups').mkdir()
            state_dir = app/'backups'/('shop-online-activation-'+'d'*24)
            state_dir.mkdir(mode=0o700)
            for name in ('shop-online-activation-required', 'backend-recovery-required'):
                (app/name).write_text('immutable fence fixture')
            helper = stage/'recover-shop-online-compose.py'
            helper.write_text('''import json,os,signal,sys
from pathlib import Path
app=Path(os.environ['TEST_APP'])
if int(os.environ['RELEASE_LOCK_OWNER_PID'])!=os.getppid() or os.getppid()!=int((app/'release.lock/pid').read_text()):
    raise RuntimeError('Not direct owning child')
report=app/'backups'/('shop-online-compose-recovery-'+'d'*24)
mode=sys.argv[1]
if mode=='reconcile' and os.environ.get('ALREADY_DESIRED'):
    raise SystemExit('Both pinned writers already run desired flags; primary runtime verification required, no restart')
if mode in ('prepare','reconcile'):
    report.mkdir(exist_ok=True,mode=0o700)
    (report/'overlay.yml').write_text('reviewed fixture overlay')
    (report/'journal.json').write_text('durable fixture journal')
if os.environ.get('FAIL_PHASE')==mode:raise SystemExit(11)
if os.environ.get('SIGNAL_PHASE')==mode:os.kill(os.getppid(),signal.SIGTERM)
''')
            helper.chmod(0o600)
            wrapper = stage/'run-shop-online-compose-recovery.sh'
            wrapper.write_text((ROOT/'scripts/run-shop-online-compose-recovery.sh').read_text().replace(
                'APP_DIR=/opt/soulcuts\n', 'APP_DIR='+str(app)+'\n'))
            wrapper.chmod(0o600)
            binary = app/'bin'
            binary.mkdir()
            docker = binary/'docker'
            docker.write_text('#!'+sys.executable+'\n'+'''import json,os,sys
from pathlib import Path
app=Path(os.environ['TEST_APP'])
if not list((app/'backups').glob('shop-online-compose-recovery-*/journal.json')):
    raise RuntimeError('Writer operation before durable journal')
with (app/'calls.jsonl').open('a') as stream:
    stream.write(json.dumps(dict(args=sys.argv[1:],pin=os.environ.get('BACKEND_IMAGE'),shop_override=os.environ.get('SHOP_IMAGE'),env_files={key:value for key,value in os.environ.items() if key.endswith('_ENV_FILE')}))+'\\n')
raise SystemExit(73 if 'up' in sys.argv and os.environ.get('FAIL_UP') else 0)
''')
            docker.chmod(0o700)
            env = dict(os.environ, TEST_APP=str(app), EXPECTED_RELEASE=str(root), EXPECTED_BACKEND_IMAGE=PIN,
                BACKEND_IMAGE='foreign', SHOP_IMAGE='foreign', PATH=str(binary)+':'+os.environ['PATH'],
                SHOP_ONLINE_COMPOSE_HELPER_SHA256=OP.sha(helper.read_bytes()),
                SHOP_ONLINE_COMPOSE_WRAPPER_SHA256=OP.sha(wrapper.read_bytes()))
            env.update({key: '/foreign/'+name+'.env' for key, name in OP.ENV_FILES.items()})
            if failure:
                key, value = failure
                env[key] = value
            result = subprocess.run(['bash', str(wrapper), mode, str(state_dir)], env=env,
                                    text=True, capture_output=True, timeout=15)
            calls = [json.loads(line) for line in (app/'calls.jsonl').read_text().splitlines()] if (app/'calls.jsonl').exists() else []
            return result, calls, all((app/name).exists() for name in
                ('shop-online-activation-required', 'backend-recovery-required'))

    def test_success_uses_only_overlay_restart_after_journal_and_clears_inherited_overrides(self):
        result, calls, fences = self.exercise()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(fences)
        self.assertEqual(len(calls), 2)
        self.assertIn('stop', calls[0]['args'])
        self.assertIn('up', calls[1]['args'])
        self.assertEqual(calls[1]['args'].count('-f'), 2)
        self.assertIn('--no-deps', calls[1]['args'])
        self.assertIn('--no-build', calls[1]['args'])
        self.assertEqual(calls[1]['args'][calls[1]['args'].index('--pull')+1], 'never')
        self.assertTrue(all(call['pin'] == PIN and call['shop_override'] is None for call in calls))
        for call in calls:
            for key, name in OP.ENV_FILES.items():
                self.assertTrue(call['env_files'][key].endswith('/env/'+name+'.env'))
                self.assertNotIn('/foreign/', call['env_files'][key])

    def test_wrong_supplied_hash_and_preflight_failure_do_not_touch_healthy_writers(self):
        for failure in (('SHOP_ONLINE_COMPOSE_HELPER_SHA256', '0'*64), ('FAIL_PHASE', 'prepare')):
            with self.subTest(failure=failure):
                result, calls, fences = self.exercise(failure)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(calls, [])
                self.assertTrue(fences)

    def test_partial_restart_and_failed_post_stop_checks_stop_both_and_keep_fences(self):
        for failure in (('FAIL_UP', '1'), ('FAIL_PHASE', 'after-stop'),
                        ('FAIL_PHASE', 'before-restart'), ('FAIL_PHASE', 'record-restart')):
            with self.subTest(failure=failure):
                result, calls, fences = self.exercise(failure)
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(fences)
                self.assertIn('stop', calls[-1]['args'])
                self.assertEqual(calls[-1]['args'][-2:], ['backend', 'booking-sms-reminders'])

    def test_signal_after_stopping_or_restart_ack_stops_both_without_clearing_fences(self):
        for phase in ('after-stop', 'before-restart', 'record-restart'):
            with self.subTest(phase=phase):
                result, calls, fences = self.exercise(('SIGNAL_PHASE', phase))
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(fences)
                self.assertIn('stop', calls[-1]['args'])

    def test_explicit_reconcile_wrapper_uses_same_checked_protocol(self):
        result, calls, fences = self.exercise(mode='reconcile')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(fences)
        self.assertEqual(len(calls), 2)

    def test_already_desired_reconcile_refusal_never_calls_stop_or_up(self):
        result, calls, fences = self.exercise(('ALREADY_DESIRED', '1'), mode='reconcile')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('primary runtime verification required, no restart', result.stderr)
        self.assertTrue(fences)
        self.assertEqual(calls, [])
