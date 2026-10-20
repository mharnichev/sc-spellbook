"""Actual provenance checks plus subprocess faults with a synthetic Docker inventory."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import test_shop_content_backfill as fixture

OP = fixture.OP
REAL_TOOL_HASHES = OP.tool_hashes
SCRIPTS = fixture.ROOT/'scripts'


class ContentToolFaultTests(unittest.TestCase):
    def prepare(self):
        case = fixture.ContentTests(methodName='runTest')
        case.setUp()
        self.addCleanup(case.doCleanups)
        tools = case.root/'scripts'
        tools.mkdir()
        for name in OP.TOOL_NAMES:
            shutil.copyfile(SCRIPTS/name, tools/name)
        case.stack.enter_context(patch.object(OP, 'tool_hashes', REAL_TOOL_HASHES))
        return case

    def test_every_real_tool_hash_is_bound_and_recovery_rejects_drift(self):
        case = self.prepare()
        case.invoke('apply')
        state = json.loads(case.marker.read_text())
        self.assertEqual(state['tools'], {name: hashlib.sha256((SCRIPTS/name).read_bytes()).hexdigest()
                                         for name in OP.TOOL_NAMES})
        baseline = copy.deepcopy(case.database)
        for name in OP.TOOL_NAMES:
            path = case.root/'scripts'/name
            original = path.read_bytes()
            path.write_bytes(original+b'\n# synthetic drift\n')
            for mode in ('reconcile', 'rollback', 'finalize'):
                case.running = mode == 'finalize'
                calls = len(case.calls)
                with self.subTest(tool=name, mode=mode), self.assertRaises(RuntimeError):
                    case.invoke(mode)
                self.assertFalse(any(args[:2] == ['docker', 'run'] for args in case.calls[calls:]))
                self.assertTrue(case.marker.exists() and case.backend.exists())
                self.assertEqual(case.database, baseline)
            path.write_bytes(original)

    def test_drift_during_dry_run_refuses_before_apply(self):
        case = self.prepare()
        def run(args, **kwargs):
            result = case.fake_run(args, **kwargs)
            if 'app.utils.backfill_shop_content_en' in args and '--apply' not in args:
                path = case.root/'scripts/shop-content-backfill-db.py'
                path.write_bytes(path.read_bytes()+b'\n# drift across await\n')
            return result
        with patch.object(OP.SAFE, 'run', side_effect=run), self.assertRaises(RuntimeError):
            case.invoke('apply')
        self.assertEqual(case.database, case.before)
        self.assertFalse(any('--apply' in args for args in case.calls))
        self.assertTrue(case.backend.exists())

    def test_symlink_tool_is_not_a_valid_hash_source(self):
        case = self.prepare()
        path = case.root/'scripts/shop-content-backfill-db.py'
        path.unlink()
        path.symlink_to(SCRIPTS/path.name)
        with self.assertRaises(RuntimeError):
            case.invoke('apply')
        self.assertEqual(case.database, case.before)


DOCKER_STUB = r'''
import json, os, sys
from pathlib import Path
base=Path(os.environ['SYNTHETIC_APP'])
args=sys.argv[1:]
with (base/'calls.jsonl').open('a') as log:
    log.write(json.dumps(args)+'\n')
if args[0]=='compose':
    sys.exit(0 if 'stop' in args else 91)
tasks=json.loads((base/'tasks.json').read_text())
if args[0]=='ps':
    filters=[args[i+1][6:] for i,value in enumerate(args) if value=='--filter']
    selected=[task for task in tasks if all(task['labels'].get(f.split('=',1)[0])==f.split('=',1)[1] for f in filters)]
    names=args[args.index('--format')+1]=='{{.Names}}'
    print('\n'.join(task['name'] if names else task['id']+' '+task['name'] for task in selected))
elif args[0]=='stop':
    if os.environ.get('CLEANUP_FAIL')=='true': sys.exit(73)
    (base/'tasks.json').write_text(json.dumps([task for task in tasks if task['id']!=args[-1]]))
else:
    sys.exit(92)
'''

SYNTHETIC_MAIN = r'''
if __name__ == '__main__':
    import signal
    base=Path(os.environ['SYNTHETIC_APP'])
    assert int(os.environ['RELEASE_LOCK_OWNER_PID'])==os.getppid()
    assert int((base/'release.lock/pid').read_text())==os.getppid()
    def task(identifier, prefix, release):
        return dict(id=identifier, name=prefix+'-apply-12345678', labels={
            'com.docker.compose.project':'soulcuts',
            'com.docker.compose.service':'migrate',
            'com.soulcuts.english-content-run':prefix,
            'com.soulcuts.english-content-release':release})
    tasks=[task('b'*12,'english-content-'+'a'*24,os.environ['EXPECTED_RELEASE']),
           task('c'*12,'english-content-'+'c'*24,'/foreign/release')]
    (base/'tasks.json').write_text(json.dumps(tasks))
    fault=os.environ['FAULT']
    if fault=='helper-timeout':
        SAFE.run([sys.executable,'-c','import time; time.sleep(2)'],timeout=0.02)
    if fault=='parent-term':
        os.kill(os.getppid(),signal.SIGTERM)
        sys.exit(11)
    os.kill(os.getpid(),signal.SIGKILL if fault=='helper-kill' else signal.SIGTERM)
'''


class ContentProcessFaultTests(unittest.TestCase):
    def exercise(self, fault, cleanup_fail=False):
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory).resolve()
            root = app/'releases/candidate'
            tools = root/'scripts'
            tools.mkdir(parents=True)
            (root/'versions').mkdir()
            (root/'versions/production.env').write_text('synthetic pins\n')
            backend = app/'backend-recovery-required'
            backend.write_text('release='+str(root)+'\nphase=pending_acceptance\n')
            marker = app/'english-backfill-required'
            marker.write_text('durable synthetic prepared fence\n')
            fences = (backend.read_bytes(), marker.read_bytes())
            for name in ('activate-shop-online.py', 'shop-online-config.py', 'release-lock.sh'):
                shutil.copyfile(SCRIPTS/name, tools/name)
            (tools/'release-backend-pin.py').write_text('print('+repr(fixture.PIN)+')\n')
            # Keep actual cleanup implementation; replace only the synthetic operation boundary.
            source = (SCRIPTS/'apply-shop-content-backfill.py').read_text()
            (tools/'apply-shop-content-backfill.py').write_text(source.split("if __name__ == '__main__':")[0]+SYNTHETIC_MAIN)
            wrapper = (SCRIPTS/'run-shop-content-backfill.sh').read_text()
            (tools/'run-shop-content-backfill.sh').write_text(wrapper.replace('APP_DIR=/opt/soulcuts\n', 'APP_DIR='+str(app)+'\n'))
            binary = app/'bin'
            binary.mkdir()
            docker = binary/'docker'
            docker.write_text('#!'+sys.executable+'\n'+DOCKER_STUB)
            docker.chmod(0o700)
            env = dict(os.environ, PATH=str(binary)+os.pathsep+os.environ['PATH'],
                       EXPECTED_RELEASE=str(root), EXPECTED_BACKEND_IMAGE=fixture.PIN,
                       SYNTHETIC_APP=str(app), FAULT=fault, CLEANUP_FAIL=str(cleanup_fail).lower(),
                       PYTHONDONTWRITEBYTECODE='1')
            result = subprocess.run(['bash', str(tools/'run-shop-content-backfill.sh'), 'apply', 'synthetic'],
                                    env=env, capture_output=True, text=True, timeout=15)
            self.assertNotEqual(result.returncode, 0, result.stderr)
            if fault == 'helper-kill':
                self.assertEqual(result.returncode, 137, result.stderr)
            if fault == 'helper-term':
                self.assertEqual(result.returncode, 143, result.stderr)
            self.assertEqual((backend.read_bytes(), marker.read_bytes()), fences)
            calls = [json.loads(line) for line in (app/'calls.jsonl').read_text().splitlines()]
            self.assertEqual(sum(args[0]=='compose' and 'stop' in args for args in calls), 2,
                             (result.returncode, result.stderr, calls))
            self.assertFalse(any('up' in args for args in calls))
            self.assertIn(['stop', '--time', '5', 'b'*12], calls)
            self.assertFalse(any(args[0]=='stop' and args[-1]=='c'*12 for args in calls))
            remaining = json.loads((app/'tasks.json').read_text())
            self.assertEqual({task['id'] for task in remaining}, {'c'*12, 'b'*12} if cleanup_fail else {'c'*12})
            if cleanup_fail:
                self.assertIn('CRITICAL: content task cleanup failed; retain fences.', result.stderr)

    def test_helper_sigterm_cleans_owned_live_task(self):
        self.exercise('helper-term')

    def test_helper_sigkill_oom_like_exit_cleans_owned_live_task(self):
        self.exercise('helper-kill')

    def test_parent_sigterm_cleans_owned_live_task(self):
        self.exercise('parent-term')

    def test_helper_subprocess_timeout_cleans_owned_live_task(self):
        self.exercise('helper-timeout')

    def test_failed_docker_cleanup_is_not_reported_as_success(self):
        self.exercise('helper-kill', cleanup_fail=True)
