import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PIN = 'ghcr.io/mharnichev/sc-be/api@sha256:'+'a'*64


class ShopOnlineWrapperTests(unittest.TestCase):
    def exercise(self, mode='apply', failure=None):
        with tempfile.TemporaryDirectory(prefix='shop-wrapper-') as directory:
            app = Path(directory)
            release = app/'releases/candidate'
            scripts = release/'scripts'
            scripts.mkdir(parents=True)
            (app/'env').mkdir()
            (app/'env/backend.env').write_text('UNCHANGED=fixture\n')
            (app/'backend-recovery-required').write_text('release='+str(release)+'\nphase=pending_acceptance\n')
            (scripts/'release-lock.sh').write_bytes((ROOT/'scripts/release-lock.sh').read_bytes())
            (scripts/'release-backend-pin.py').write_text('import os; print("bad" if os.environ.get("BAD_PIN") else '+repr(PIN)+')\n')
            (scripts/'activate-shop-online.py').write_text('''import hashlib,json,os,signal,sys
from pathlib import Path
app=Path(os.environ['TEST_APP'])
def release_context():
    if int(os.environ['RELEASE_LOCK_OWNER_PID'])!=os.getppid() or os.getppid()!=int((app/'release.lock/pid').read_text()):
        raise RuntimeError('Not direct owning child')
    return Path(os.environ['EXPECTED_RELEASE']),None
def cleanup_release(root):
    (app/'cleanup-called').write_text(str(root))
def main():
    root,_=release_context()
    marker=app/'shop-online-activation-required'
    state=dict(release=str(root),after_sha256=hashlib.sha256((app/'env/backend.env').read_bytes()).hexdigest(),pre_restart_original_verified=True,tools={})
    marker.write_text(json.dumps(state))
    if os.environ.get('ENV_DRIFT'):(app/'env/backend.env').write_text('FOREIGN=true')
    if os.environ.get('HELPER_FAIL'):raise SystemExit(11)
    if sys.argv[1]=='finalize':
        (app/'finalized.json').write_text(json.dumps(dict(finalized=True,state=state)))
        marker.unlink()
        if os.environ.get('SIGNAL_AFTER_FINALIZE'):os.kill(os.getppid(),signal.SIGTERM)
    elif os.environ.get('SIGNAL_PARENT'):os.kill(os.getppid(),signal.SIGTERM)
if __name__=='__main__':main()
''')
            binary = app/'bin'
            binary.mkdir()
            docker = binary/'docker'
            docker.write_text('#!'+sys.executable+'\n'+'''import json,os,sys
from pathlib import Path
with (Path(os.environ['TEST_APP'])/'calls.jsonl').open('a') as stream:
    stream.write(json.dumps(dict(args=sys.argv[1:],pin=os.environ.get('BACKEND_IMAGE'),backend_env=os.environ.get('BACKEND_ENV_FILE'),postgres_env=os.environ.get('POSTGRES_ENV_FILE')))+'\\n')
raise SystemExit(73 if 'up' in sys.argv and os.environ.get('FAIL_UP') else 0)
''')
            docker.chmod(0o700)
            env = dict(os.environ, TEST_APP=directory, EXPECTED_RELEASE=str(release),
                       EXPECTED_BACKEND_IMAGE=PIN, BACKEND_IMAGE='foreign-inherited-override',
                       PATH=str(binary)+':'+os.environ['PATH'])
            if failure:
                env[failure] = '1'
            wrapper = scripts/'run-shop-online-activation.sh'
            wrapper.write_text((ROOT/'scripts/run-shop-online-activation.sh').read_text().replace(
                'APP_DIR=/opt/soulcuts\n', 'APP_DIR='+directory+'\n'))
            result = subprocess.run(['bash', str(wrapper), mode, 'fixture', '1'],
                                    env=env, text=True, capture_output=True, timeout=15)
            calls = [json.loads(line) for line in (app/'calls.jsonl').read_text().splitlines()] if (app/'calls.jsonl').exists() else []
            return result, calls, dict(backend=(app/'backend-recovery-required').exists(),
                activation=(app/'shop-online-activation-required').exists(),
                receipt=(app/'finalized.json').exists(), cleanup=(app/'cleanup-called').exists(),
                lock=(app/'release.lock').exists())

    def test_apply_uses_direct_owner_and_pinned_no_pull_no_build_restart(self):
        result, calls, state = self.exercise()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(state['backend'] and state['activation'])
        self.assertFalse(state['lock'])
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(call['pin'] == PIN for call in calls))
        self.assertTrue(all(call['backend_env'].endswith('/env/backend.env') for call in calls))
        self.assertTrue(all(call['postgres_env'].endswith('/env/postgres.env') for call in calls))
        self.assertIn('stop', calls[0]['args'])
        self.assertIn('up', calls[1]['args'])
        self.assertIn('--no-deps', calls[1]['args'])
        self.assertIn('--no-build', calls[1]['args'])
        self.assertEqual(calls[1]['args'][calls[1]['args'].index('--pull')+1], 'never')

    def test_bad_pin_is_nonmutating_before_writer_stop(self):
        result, calls, state = self.exercise(failure='BAD_PIN')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, [])
        self.assertTrue(state['backend'])
        self.assertFalse(state['activation'] or state['cleanup'])

    def test_helper_and_partial_restart_failure_stop_writers_and_cleanup_tasks(self):
        for failure, code in (('HELPER_FAIL', 11), ('FAIL_UP', 73)):
            with self.subTest(failure=failure):
                result, calls, state = self.exercise(failure=failure)
                self.assertEqual(result.returncode, code, result.stderr)
                self.assertTrue(state['backend'] and state['activation'] and state['cleanup'])
                self.assertIn('stop', calls[-1]['args'])
                self.assertEqual(calls[-1]['args'][-2:], ['backend', 'booking-sms-reminders'])

    def test_env_drift_blocks_restart_and_preserves_fences(self):
        result, calls, state = self.exercise(failure='ENV_DRIFT')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(state['backend'] and state['activation'] and state['cleanup'])
        self.assertTrue(all('up' not in call['args'] for call in calls))

    def test_signal_during_apply_stops_writers(self):
        result, calls, state = self.exercise(failure='SIGNAL_PARENT')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(state['backend'] and state['activation'] and state['cleanup'])
        self.assertIn('stop', calls[-1]['args'])

    def test_failed_finalize_stops_both_running_writers(self):
        result, calls, state = self.exercise(mode='finalize', failure='HELPER_FAIL')
        self.assertEqual(result.returncode, 11, result.stderr)
        self.assertTrue(state['backend'] and state['activation'] and state['cleanup'])
        self.assertEqual(len(calls), 1)
        self.assertIn('stop', calls[0]['args'])

    def test_finalize_lost_ack_preserves_receipt_backend_and_stops_writers(self):
        result, calls, state = self.exercise(mode='finalize', failure='SIGNAL_AFTER_FINALIZE')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(state['backend'] and state['receipt'] and state['cleanup'])
        self.assertFalse(state['activation'])
        self.assertEqual(len(calls), 1)
        self.assertIn('stop', calls[0]['args'])

    def test_successful_finalize_does_not_restart_or_accept_backend(self):
        result, calls, state = self.exercise(mode='finalize')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(state['backend'] and state['receipt'])
        self.assertFalse(state['activation'])
        self.assertEqual(calls, [])
