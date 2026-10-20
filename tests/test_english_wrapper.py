import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PIN = 'ghcr.io/mharnichev/sc-be/api@sha256:'+'a'*64


class EnglishWrapperTests(unittest.TestCase):
    def exercise(self, mode='apply', failure=None, recovery=False):
        with tempfile.TemporaryDirectory(prefix='english-wrapper-') as directory:
            app = Path(directory)
            release = app/'releases/candidate'
            scripts = release/'scripts'
            scripts.mkdir(parents=True)
            (app/'env').mkdir()
            (app/'env/backend.env').write_text('UNCHANGED=fixture\n')
            (app/'backend-recovery-required').write_text('release='+str(release)+'\nphase=pending_acceptance\n')
            (scripts/'release-lock.sh').write_text('acquire_release_lock() { mkdir -p "$APP_DIR/release.lock"; printf "%s" "$$" > "$APP_DIR/release.lock/pid"; }\n')
            (scripts/'release-backend-pin.py').write_text('import os; print("bad" if os.environ.get("BAD_PIN") else '+repr(PIN)+')\n')
            (scripts/'apply-english-backfill.py').write_text('''import os,signal,sys,json,hashlib
from pathlib import Path
app=Path(os.environ['TEST_APP'])
assert int(os.environ['RELEASE_LOCK_OWNER_PID'])==os.getppid()==int((app/'release.lock/pid').read_text())
(app/'english-backfill-required').write_text(json.dumps(dict(release=os.environ['EXPECTED_RELEASE'],env_sha256=hashlib.sha256((app/'env/backend.env').read_bytes()).hexdigest())))
if os.environ.get('ENV_DRIFT'):(app/'env/backend.env').write_text('CHANGED=fixture')
if os.environ.get('HELPER_FAIL'):raise SystemExit(11)
if sys.argv[1]=='finalize':
 (app/'finalized.json').write_text('durable fixture acceptance receipt')
 (app/'english-backfill-required').unlink()
 if os.environ.get('SIGNAL_AFTER_FINALIZE'):os.kill(os.getppid(),signal.SIGTERM)
elif os.environ.get('SIGNAL_PARENT'):os.kill(os.getppid(),signal.SIGTERM)
''')
            binary = app/'bin'
            binary.mkdir()
            docker = binary/'docker'
            docker.write_text('#!'+sys.executable+'\n'+'''import json,os,sys
from pathlib import Path
with (Path(os.environ['TEST_APP'])/'calls.jsonl').open('a') as stream:
 stream.write(json.dumps({'args':sys.argv[1:],'pin':os.environ.get('BACKEND_IMAGE')})+'\\n')
raise SystemExit(73 if 'up' in sys.argv and os.environ.get('FAIL_UP') else 0)
''')
            docker.chmod(0o700)
            env = dict(os.environ, TEST_APP=directory, EXPECTED_RELEASE=str(release),
                       EXPECTED_BACKEND_IMAGE=PIN, BACKEND_IMAGE='foreign-shell-override',
                       PATH=str(binary)+':'+os.environ['PATH'])
            if failure:
                env[failure] = '1'
            source = (ROOT/'scripts/run-english-backfill.sh').read_text().replace('APP_DIR=/opt/soulcuts\n','APP_DIR='+directory+'\n')
            tools = scripts
            if recovery:
                tools = app/'backups/reviewed-recovery-tools'
                tools.mkdir(parents=True,mode=0o700)
                (tools/'apply-english-backfill.py').write_bytes((scripts/'apply-english-backfill.py').read_bytes())
                (scripts/'apply-english-backfill.py').write_text('raise SystemExit(86)\n')
            wrapper = tools/'run-english-backfill.sh'
            wrapper.write_text(source)
            result = subprocess.run(['bash',str(wrapper),mode,'fixture-input','b'*64,'c'*64],
                                    text=True,capture_output=True,env=env,timeout=15)
            calls = [json.loads(line) for line in (app/'calls.jsonl').read_text().splitlines()] if (app/'calls.jsonl').exists() else []
            return result, calls, (app/'backend-recovery-required').exists(), (app/'english-backfill-required').exists(), (app/'finalized.json').exists()

    def test_pinned_apply_restart_has_no_pull_or_build(self):
        result,calls,backend,english,_ = self.exercise()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(backend and english)
        self.assertEqual(len(calls),2)
        self.assertTrue(all(call['pin']==PIN for call in calls))
        self.assertIn('stop',calls[0]['args'])
        self.assertIn('up',calls[1]['args'])
        self.assertIn('--no-build',calls[1]['args'])
        self.assertEqual(calls[1]['args'][calls[1]['args'].index('--pull')+1],'never')

    def test_bad_pin_fails_before_stopping_writers(self):
        result,calls,backend,english,_ = self.exercise(failure='BAD_PIN')
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(calls,[])
        self.assertTrue(backend)
        self.assertFalse(english)

    def test_environment_drift_after_helper_never_restarts_writers(self):
        result,calls,backend,english,_ = self.exercise(failure='ENV_DRIFT')
        self.assertNotEqual(result.returncode,0)
        self.assertTrue(backend and english)
        self.assertTrue(calls)
        self.assertTrue(all('up' not in call['args'] for call in calls))
        self.assertIn('stop',calls[-1]['args'])

    def test_private_recovery_pair_uses_new_operator_bound_to_pending_release(self):
        result,calls,backend,english,_ = self.exercise(recovery=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(backend and english)
        self.assertEqual(len(calls),2)
        self.assertTrue(all(call['pin']==PIN for call in calls))
        self.assertIn('up',calls[-1]['args'])

    def test_helper_and_partial_restart_failure_stop_both_and_retain_fences(self):
        for failure,code in (('HELPER_FAIL',11),('FAIL_UP',73)):
            with self.subTest(failure=failure):
                result,calls,backend,english,_ = self.exercise(failure=failure)
                self.assertEqual(result.returncode,code,result.stderr)
                self.assertTrue(backend and english)
                self.assertIn('stop',calls[-1]['args'])
                self.assertEqual(calls[-1]['args'][-2:],['backend','booking-sms-reminders'])

    def test_failed_finalize_also_stops_running_writers(self):
        result,calls,backend,english,_ = self.exercise(mode='finalize',failure='HELPER_FAIL')
        self.assertEqual(result.returncode,11,result.stderr)
        self.assertTrue(backend and english)
        self.assertEqual(len(calls),1)
        self.assertIn('stop',calls[0]['args'])

    def test_signal_before_finalization_stops_writers_and_preserves_both_fences(self):
        result,calls,backend,english,receipt = self.exercise(failure='SIGNAL_PARENT')
        self.assertNotEqual(result.returncode,0)
        self.assertTrue(backend and english)
        self.assertFalse(receipt)
        self.assertTrue(calls)
        self.assertIn('stop',calls[-1]['args'])

    def test_lost_ack_after_committed_finalize_retains_receipt_backend_fence_and_stops_writers(self):
        result,calls,backend,english,receipt = self.exercise(mode='finalize',failure='SIGNAL_AFTER_FINALIZE')
        self.assertNotEqual(result.returncode,0)
        self.assertTrue(backend and receipt)
        self.assertFalse(english)
        self.assertEqual(len(calls),1)
        self.assertIn('stop',calls[-1]['args'])

    def test_successful_finalize_does_not_restart_writers_or_accept_infrastructure(self):
        result,calls,backend,english,receipt = self.exercise(mode='finalize')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(backend and receipt)
        self.assertFalse(english)
        self.assertEqual(calls,[])
