import json
import os
import shutil
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
DOCKER_STUB = '''#!/usr/bin/env python3
import hashlib, json, os, sys
args = sys.argv[1:]
with open(os.environ["DOCKER_CALLS"], "a") as out:
    out.write(json.dumps(args) + "\\n")
if os.environ.get('EXPECT_ADMIN_LITERAL') and ('pull' in args or 'up' in args):
    assert args[-1] == 'admin-app'
    assert os.environ.get('ADMIN_APP_IMAGE') == json.loads(os.environ['TEST_IMAGE_REFS'])['admin-app']
services = ['backend', 'booking-sms-reminders', 'shop', 'admin-app', 'public-site', 'blog', 'caddy', 'postgres']
container_ids = {hashlib.sha256(name.encode()).hexdigest(): name for name in services}
if args[:1] == ['run'] and args[-1] == 'import os; print(os.geteuid())':
    print(os.geteuid()); sys.exit(0)
if args[:1] == ['run'] and args[-1] == '--runtime-store':
    sys.exit(1 if os.environ.get('FAIL_INCIDENT_FILES') else 0)
if args[:2] == ['image', 'inspect']:
    if os.environ.get('FAIL_IMAGE_LOOKUP'):
        print('PRIVATE_TEST_SENTINEL', file=sys.stderr); sys.exit(1)
    print('sha256:' + hashlib.sha256(args[-1].encode()).hexdigest()); sys.exit(0)
if args[:1] == ['inspect'] and any('com.docker.compose.service' in arg for arg in args):
    service = container_ids[args[-1]]
    refs = json.loads(os.environ['TEST_IMAGE_REFS'])
    image_id = 'sha256:' + hashlib.sha256(refs[service].encode()).hexdigest()
    if os.environ.get('FAIL_IMAGE_SERVICE') == service:
        image_id = 'sha256:' + '0' * 64
    print(image_id + '|true|' + service + '|soulcuts'); sys.exit(0)
if "stop" in args and os.environ.get("DEPLOY_TEST"):
    open(os.environ["DOCKER_CALLS"] + ".stopped", "w").close()
if any("pg_dump" in arg for arg in args):
    if os.environ.get("FAIL_DUMP"):
        sys.exit(1)
    print("synthetic custom archive")
if "run" in args and args[-1] == "migrate" and os.environ.get("FAIL_MIGRATE"):
    sys.exit(1)
if "app.core.migration_readiness" in args and os.environ.get("FAIL_SCHEMA"):
    sys.exit(1)
if any("count(*) FROM pg_locks" in arg for arg in args) and os.environ.get("FAIL_LOCK"):
    sys.exit(1)
if any("Backend release preflight failed:" in arg for arg in args) and os.environ.get("FAIL_PREFLIGHT"):
    sys.exit(1)
if "--list" in args and os.environ.get("FAIL_LIST"):
    sys.exit(1)
if "ps" in args:
    if os.environ.get("FAIL_PS"):
        sys.exit(1)
    stopped = os.path.exists(os.environ["DOCKER_CALLS"] + ".stopped")
    print(hashlib.sha256(args[-1].encode()).hexdigest() if "-q" in args else "" if stopped else os.environ.get("RUNNING_WRITERS", "backend\\nbooking-sms-reminders"))
if "inspect" in args:
    print("2026-10-19T00:00:00Z" if any("StartedAt" in arg for arg in args) else "unhealthy" if os.environ.get("FAIL_HEALTH") else "healthy")
if "logs" in args:
    print("background_workers state=failed role=owner code=worker_exited" if os.environ.get("FAIL_OWNER") else "background_workers state=running role=owner code=None")
if "up" in args and os.environ.get("FAIL_UP"):
    sys.exit(1)
if "pull" in args and os.environ.get("FAIL_PULL"):
    sys.exit(1)
if any("pg_restore --exit-on-error" in arg for arg in args) and os.environ.get("FAIL_RESTORE"):
    sys.exit(1)
'''


class BackupRestoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name).resolve()
        self.release_root = ROOT
        self.env = {**os.environ, "APP_DIR": str(self.path), "BACKUP_DIR": str(self.path / "backups")}

    def run_script(self, name, *args):
        return subprocess.run(["bash", str(self.release_root / "scripts" / name), *map(str, args)],
                              env=self.env, capture_output=True, text=True)

    def stub_docker(self):
        binary = self.path / "bin"
        binary.mkdir()
        docker = binary / "docker"
        docker.write_text(DOCKER_STUB)
        docker.chmod(0o755)
        self.calls = self.path / "calls.jsonl"
        self.env.update(PATH=f"{binary}:{os.environ['PATH']}", DOCKER_CALLS=str(self.calls))
        self.dump = self.path / "backup.dump"
        self.dump.write_bytes(b"synthetic archive")

    def operations(self):
        return [json.loads(line) for line in self.calls.read_text().splitlines()]

    def test_files_include_uploads_and_imports_with_private_permissions(self):
        for folder in ("uploads", "imports"):
            target = self.path / "data" / folder
            target.mkdir(parents=True)
            (target / "synthetic.txt").write_text(folder)
        result = self.run_script("backup-files.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        archive, = (self.path / "backups").glob("*.tar.gz")
        self.assertEqual(archive.stat().st_mode & 0o777, 0o600)
        with tarfile.open(archive) as data:
            self.assertIn("uploads/synthetic.txt", data.getnames())
            self.assertIn("imports/synthetic.txt", data.getnames())
            self.assertEqual(data.extractfile("imports/synthetic.txt").read(), b"imports")

    def test_files_allow_absent_imports(self):
        (self.path / "data/uploads").mkdir(parents=True)
        result = self.run_script("backup-files.sh")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_files_fail_when_uploads_missing(self):
        self.assertNotEqual(self.run_script("backup-files.sh").returncode, 0)

    def test_restore_requires_explicit_confirmation(self):
        self.stub_docker()
        self.assertNotEqual(self.run_script("restore-db.sh", self.dump).returncode, 0)
        self.assertFalse(self.calls.exists())

    def test_bad_archive_never_stops_writers_or_drops_database(self):
        self.stub_docker()
        self.env.update(CONFIRM_RESTORE="production", FAIL_LIST="1")
        self.assertNotEqual(self.run_script("restore-db.sh", self.dump).returncode, 0)
        self.assertEqual(len(self.operations()), 1)

    def test_restore_stops_all_writers_then_resumes_only_previous_services(self):
        self.stub_docker()
        self.env.update(CONFIRM_RESTORE="production")
        result = self.run_script("restore-db.sh", self.dump)
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.operations()
        stop = next(call for call in calls if "stop" in call)
        self.assertEqual(stop[-2:], ["backend", "booking-sms-reminders"])
        self.assertEqual(stop[stop.index('stop') + 1:stop.index('stop') + 3], ['--timeout', '90'])
        restore = next(call for call in calls if any("pg_restore --exit-on-error" in arg for arg in call))
        self.assertIn("--single-transaction", restore[-1])
        self.assertLess(calls.index(stop), calls.index(restore))
        self.assertEqual(calls[-1][-3:], ["start", "backend", "booking-sms-reminders"])

    def test_restore_does_not_start_dependencies_or_previously_stopped_writers(self):
        self.stub_docker()
        self.env.update(CONFIRM_RESTORE="production")
        for running in ("backend", "booking-sms-reminders", ""):
            with self.subTest(running=running):
                self.calls.write_text("")
                self.env["RUNNING_WRITERS"] = running
                result = self.run_script("restore-db.sh", self.dump)
                self.assertEqual(result.returncode, 0, result.stderr)
                calls = self.operations()
                self.assertFalse(any("up" in call for call in calls))
                starts = [call for call in calls if "start" in call]
                self.assertEqual(len(starts), int(bool(running)))
                if starts:
                    self.assertEqual(starts[0][-2:], ["start", running])

    def test_restore_failure_keeps_writers_stopped(self):
        self.stub_docker()
        self.env.update(CONFIRM_RESTORE="production", FAIL_RESTORE="1")
        result = self.run_script("restore-db.sh", self.dump)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any("up" in call for call in self.operations()))
        self.assertIn("writers remain stopped", result.stderr)

    def test_failed_writer_inventory_never_drops_database(self):
        self.stub_docker()
        self.env.update(CONFIRM_RESTORE="production", FAIL_PS="1")
        self.assertNotEqual(self.run_script("restore-db.sh", self.dump).returncode, 0)
        self.assertFalse(any(any("dropdb" in arg for arg in call) for call in self.operations()))

    def prepare_deploy(self):
        self.stub_docker()
        self.release_root = self.path / 'candidate'
        shutil.copytree(ROOT / 'scripts', self.release_root / 'scripts', ignore=shutil.ignore_patterns('__pycache__'))
        incident_store = self.path / 'data/sentry-incidents'
        incident_store.mkdir(parents=True, mode=0o700)
        preflight = self.release_root / 'scripts/check-sentry-incident-store.py'
        preflight.write_text(preflight.read_text().replace(
            "Path('/opt/soulcuts/data/sentry-incidents')", f'Path({str(incident_store)!r})'))
        shutil.copy2(ROOT / 'docker-compose.prod.yml', self.release_root / 'docker-compose.prod.yml')
        (self.release_root / 'versions').mkdir()
        pins = dict(line.split('=', 1) for line in (ROOT / 'versions/production.env').read_text().splitlines() if line and not line.startswith('#'))
        for key, digit in [('BACKEND_IMAGE', '1'), ('SHOP_IMAGE', '2'), ('ADMIN_APP_IMAGE', '3'), ('CADDY_IMAGE', '4'), ('POSTGRES_IMAGE', '5')]:
            pins[key] = 'local/' + key.lower() + '@sha256:' + digit * 64
        (self.release_root / 'versions/production.env').write_text('\n'.join(f'{key}={value}' for key, value in pins.items()) + '\n')
        refs = {name: pins[key] for name, key in [('backend', 'BACKEND_IMAGE'), ('booking-sms-reminders', 'BACKEND_IMAGE'),
                ('shop', 'SHOP_IMAGE'), ('admin-app', 'ADMIN_APP_IMAGE'), ('public-site', 'PUBLIC_SITE_IMAGE'),
                ('blog', 'BLOG_IMAGE'), ('caddy', 'CADDY_IMAGE'), ('postgres', 'POSTGRES_IMAGE')]}
        self.env['TEST_IMAGE_REFS'] = json.dumps(refs)
        (self.path / "env").mkdir()
        for name in ("caddy", "postgres", "backend", "public-site", "blog", "admin-app", "shop"):
            (self.path / "env" / f"{name}.env").write_text("# synthetic\n")
        previous = self.path / "previous"
        (previous / "versions").mkdir(parents=True)
        (previous / "versions/production.env").write_text("BACKEND_IMAGE=synthetic:previous\n")
        (self.path / "current").symlink_to(previous)
        self.previous = previous
        (self.path / "data/uploads").mkdir(parents=True)
        (self.path / "data/uploads/synthetic.txt").write_text("synthetic media")
        ip = self.path / "bin/ip"
        ip.write_text('#!/bin/sh\nprintf "[]"\n')
        ip.chmod(0o755)
        self.env["DEPLOY_TEST"] = "1"

    def test_backend_deploy_quiesces_writers_and_backs_up_files(self):
        self.prepare_deploy()
        result = self.run_script("deploy.sh")
        self.assertEqual(result.returncode, 3, result.stderr)
        calls = self.operations()
        stop = next(i for i, call in enumerate(calls) if "stop" in call)
        dump = next(i for i, call in enumerate(calls) if any("pg_dump" in arg for arg in call))
        up = next(i for i, call in enumerate(calls) if "up" in call)
        self.assertLess(stop, dump)
        self.assertEqual(calls[stop][calls[stop].index('stop') + 1:calls[stop].index('stop') + 3], ['--timeout', '90'])
        self.assertLess(dump, up)
        self.assertTrue(list((self.path / "backups").glob("pilot-*/*.tar.gz")))
        manifest, = (self.path / "backups").glob("pilot-*/manifest.json")
        self.assertEqual(len(json.loads(manifest.read_text())), 2)
        self.assertEqual((self.path / "current").resolve(), self.previous.resolve())
        self.assertTrue((self.path / "backend-recovery-required").exists())
        self.env.update(PILOT_MANUAL_GATE='verified', EXPECTED_RELEASE=str(self.release_root))
        accepted = self.run_script('accept-shop-pilot.sh')
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertEqual((self.path / "current").resolve(), self.release_root)
        self.assertFalse((self.path / "backend-recovery-required").exists())

    def same_backend(self):
        (self.previous / 'versions/production.env').write_text((self.release_root / 'versions/production.env').read_text())

    def test_frontend_only_does_not_quiesce_backup_migrate_or_create_marker(self):
        self.prepare_deploy()
        self.same_backend()
        self.env['FAIL_MIGRATE'] = '1'
        result = self.run_script('deploy.sh')
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.operations()
        self.assertFalse(any('stop' in call or 'run' in call for call in calls))

        self.assertFalse(any(any('pg_dump' in arg for arg in call) for call in calls))
        self.assertFalse((self.path / 'backend-recovery-required').exists())
        self.assertFalse((self.path / 'backups').exists())
        up, = [call for call in calls if 'up' in call]
        self.assertIn('--no-deps', up)
        self.assertNotIn('backend', up)
        self.assertNotIn('booking-sms-reminders', up)
        self.assertEqual((self.path / 'current').resolve(), self.release_root)

    def test_frontend_only_failure_does_not_stop_writers_or_mark_backend_recovery(self):
        self.prepare_deploy()
        self.same_backend()
        self.env['FAIL_UP'] = '1'
        self.assertNotEqual(self.run_script('deploy.sh').returncode, 0)
        self.assertFalse(any('stop' in call or 'run' in call for call in self.operations()))
        self.assertFalse((self.path / 'backend-recovery-required').exists())
        self.assertEqual((self.path / 'current').resolve(), self.previous.resolve())

    def prepare_admin_only(self):
        self.prepare_deploy()
        self.same_backend()
        path = self.previous / 'versions/production.env'
        path.write_text(path.read_text().replace('admin_app_image@sha256:' + '3' * 64,
                                                'admin_app_image@sha256:' + '6' * 64))
        shutil.copy2(self.release_root / 'docker-compose.prod.yml', self.previous / 'docker-compose.prod.yml')
        for root in (self.release_root, self.previous):
            (root / 'caddy').mkdir()
            (root / 'caddy/Caddyfile').write_text('synthetic identical caddy configuration')
        (self.release_root / 'versions/deploy.scope').write_text('admin-app\n')
        self.env['EXPECT_ADMIN_LITERAL'] = '1'

    def test_admin_only_never_pulls_or_recreates_other_services(self):
        self.prepare_admin_only()
        self.env['ADMIN_APP_IMAGE'] = 'untrusted-shell-override'
        result = self.run_script('deploy.sh')
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.operations()
        self.assertEqual([call[call.index('pull'):] for call in calls if 'pull' in call], [['pull', 'admin-app']])
        self.assertEqual([call[call.index('up'):] for call in calls if 'up' in call], [['up', '-d', '--no-deps', 'admin-app']])
        self.assertFalse(any('stop' in call or 'run' in call for call in calls))
        self.assertFalse((self.path / 'backend-recovery-required').exists())
        self.assertEqual((self.path / 'current').resolve(), self.release_root)

    def prepare_backend_admin(self):
        self.prepare_admin_only()
        self.env.pop('EXPECT_ADMIN_LITERAL')
        path = self.previous / 'versions/production.env'
        path.write_text(path.read_text().replace('backend_image@sha256:' + '1' * 64,
                                                'backend_image@sha256:' + '7' * 64))
        (self.release_root / 'versions/deploy.scope').write_text('backend-admin\n')

    def test_backend_admin_keeps_backup_migration_and_acceptance_gates_scoped(self):
        self.prepare_backend_admin()
        result = self.run_script('deploy.sh')
        self.assertEqual(result.returncode, 3, result.stderr)
        calls = self.operations()
        self.assertEqual([c[c.index('pull'):] for c in calls if 'pull' in c],
                         [['pull', 'backend', 'booking-sms-reminders', 'migrate', 'admin-app']])
        self.assertEqual([c[c.index('up'):] for c in calls if 'up' in c],
                         [['up', '-d', '--no-deps', 'backend', 'booking-sms-reminders', 'admin-app']])
        self.assertTrue(any(any('pg_dump' in arg for arg in c) for c in calls))
        self.assertTrue(any(c[-1] == 'migrate' for c in calls))
        self.assertTrue((self.path / 'backend-recovery-required').exists())
        self.assertEqual((self.path / 'current').resolve(), self.previous)

    def test_backend_admin_rejects_unrelated_pins_config_and_missing_inputs_before_docker(self):
        for mutation in ('shop', 'backend-unchanged', 'compose', 'caddy', 'missing-pins'):
            with self.subTest(mutation=mutation):
                test = BackupRestoreTests()
                test.setUp()
                self.addCleanup(test.doCleanups)
                test.prepare_backend_admin()
                path = test.previous / 'versions/production.env'
                if mutation == 'shop':
                    path.write_text(path.read_text().replace('shop_image@sha256:' + '2' * 64,
                                                            'shop_image@sha256:' + '8' * 64))
                elif mutation == 'backend-unchanged':
                    path.write_text(path.read_text().replace('backend_image@sha256:' + '7' * 64,
                                                            'backend_image@sha256:' + '1' * 64))
                elif mutation == 'missing-pins':
                    path.unlink()
                else:
                    path = test.previous / ('docker-compose.prod.yml' if mutation == 'compose' else 'caddy/Caddyfile')
                    path.write_text('changed')
                self.assertNotEqual(test.run_script('deploy.sh').returncode, 0)
                self.assertFalse(test.calls.exists())

    def test_backend_admin_failures_preserve_current_and_never_broaden_scope(self):
        for failure in ('FAIL_PULL', 'FAIL_PREFLIGHT', 'FAIL_DUMP', 'FAIL_MIGRATE', 'FAIL_SCHEMA',
                        'FAIL_UP', 'FAIL_HEALTH', 'FAIL_OWNER', 'FAIL_IMAGE_LOOKUP'):
            with self.subTest(failure=failure):
                test = BackupRestoreTests()
                test.setUp()
                self.addCleanup(test.doCleanups)
                test.prepare_backend_admin()
                test.env[failure] = '1'
                result = test.run_script('deploy.sh')
                self.assertNotIn(result.returncode, (0, 3))
                self.assertEqual((test.path / 'current').resolve(), test.previous)
                for call in test.operations():
                    if 'pull' in call or 'up' in call:
                        self.assertNotIn('--remove-orphans', call)
                        self.assertFalse(set(call) & {'shop', 'public-site', 'blog', 'caddy', 'postgres'})

    def test_admin_only_failure_keeps_current_and_other_services(self):
        self.prepare_admin_only()
        self.env['FAIL_UP'] = '1'
        self.assertNotEqual(self.run_script('deploy.sh').returncode, 0)
        self.assertEqual((self.path / 'current').resolve(), self.previous.resolve())
        self.assertEqual([call[call.index('up'):] for call in self.operations() if 'up' in call], [['up', '-d', '--no-deps', 'admin-app']])
        self.assertFalse(any('stop' in call for call in self.operations()))

    def test_changed_shared_configuration_refuses_admin_only_path(self):
        for name in ('docker-compose.prod.yml', 'caddy/Caddyfile'):
            with self.subTest(name=name):
                # Separate synthetic releases avoid shared test state.
                test = BackupRestoreTests('runTest')
                test.setUp()
                try:
                    test.prepare_admin_only()
                    path = test.previous / name
                    path.write_text(path.read_text() + '\nchanged')
                    result = test.run_script('deploy.sh')
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('Required scope refused', result.stderr)
                    self.assertFalse(test.calls.exists())
                finally:
                    test.doCleanups()

    def test_required_admin_only_rejects_other_pins_and_missing_inputs_before_docker(self):
        for change in ('BACKEND_IMAGE', 'SHOP_IMAGE', 'PUBLIC_SITE_IMAGE', 'missing-caddy', 'duplicate-admin'):
            with self.subTest(change=change):
                test = BackupRestoreTests('runTest')
                test.setUp()
                try:
                    test.prepare_admin_only()
                    path = test.release_root / 'versions/production.env'
                    if change == 'missing-caddy':
                        (test.previous / 'caddy/Caddyfile').unlink()
                    elif change == 'duplicate-admin':
                        path.write_text(path.read_text() + 'ADMIN_APP_IMAGE=invalid\n')
                    else:
                        path.write_text('\n'.join(line+'-different' if line.startswith(change+'=') else line for line in path.read_text().splitlines())+'\n')
                    self.assertNotEqual(test.run_script('deploy.sh').returncode, 0)
                    self.assertFalse(test.calls.exists())
                    self.assertEqual((test.path / 'current').resolve(), test.previous.resolve())
                finally:
                    test.doCleanups()

    def test_required_admin_only_acceptance_failures_never_broaden_scope(self):
        for flag in ('FAIL_PULL', 'FAIL_SCHEMA', 'FAIL_HEALTH', 'FAIL_OWNER', 'FAIL_IMAGE_SERVICE'):
            with self.subTest(flag=flag):
                test = BackupRestoreTests('runTest')
                test.setUp()
                try:
                    test.prepare_admin_only()
                    test.env[flag] = 'admin-app' if flag == 'FAIL_IMAGE_SERVICE' else '1'
                    self.assertNotEqual(test.run_script('deploy.sh').returncode, 0)
                    self.assertEqual((test.path / 'current').resolve(), test.previous.resolve())
                    calls = test.operations()
                    self.assertFalse(any('stop' in call or 'run' in call for call in calls))
                    self.assertTrue(all(call[-1]=='admin-app' for call in calls if 'up' in call or 'pull' in call))
                finally:
                    test.doCleanups()

    def test_required_admin_only_noop_rerun_stays_scoped(self):
        self.prepare_admin_only()
        self.same_backend()
        result = self.run_script('deploy.sh')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([call[call.index('up'):] for call in self.operations() if 'up' in call], [['up', '-d', '--no-deps', 'admin-app']])

    def test_existing_release_is_required(self):
        self.prepare_deploy()
        (self.path / 'current').unlink()
        self.assertNotEqual(self.run_script('deploy.sh').returncode, 0)
        self.assertFalse(self.calls.exists())

    def test_identical_backend_frontend_rollback_never_restarts_backend(self):
        self.prepare_deploy()
        self.same_backend()
        (self.previous / 'scripts').mkdir()
        for name in ('verify-background-owner.sh', 'verify-background-owner.py'):
            shutil.copy2(ROOT / 'scripts' / name, self.previous / 'scripts' / name)
        result = self.run_script('rollback.sh', self.release_root)
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.operations()
        self.assertFalse(any('stop' in call or 'run' in call for call in calls))
        up, = [call for call in calls if 'up' in call]
        self.assertNotIn('backend', up)
        self.assertNotIn('booking-sms-reminders', up)
        self.assertIn('--no-deps', up)

    def test_backend_changing_rollback_refused_before_docker(self):
        self.prepare_deploy()
        self.assertNotEqual(self.run_script('rollback.sh', self.release_root).returncode, 0)
        self.assertFalse(self.calls.exists())

    def test_missing_or_failed_owner_never_clears_marker(self):
        self.prepare_deploy()
        self.env['FAIL_OWNER'] = '1'
        result = self.run_script('deploy.sh')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((self.path / 'backend-recovery-required').exists())
        self.env.update(PILOT_MANUAL_GATE='verified', EXPECTED_RELEASE=str(self.release_root))
        self.assertNotEqual(self.run_script('accept-shop-pilot.sh').returncode, 0)
        self.assertTrue((self.path / 'backend-recovery-required').exists())

    def test_acceptance_requires_manual_gate_for_exact_release(self):
        self.prepare_deploy()
        (self.path / 'backend-recovery-required').write_text(f'release={self.release_root}\nphase=pending_acceptance\n')
        for overrides in ({}, {'PILOT_MANUAL_GATE': 'verified', 'EXPECTED_RELEASE': '/wrong/release'}):
            self.env.update(overrides)
            self.assertNotEqual(self.run_script('accept-shop-pilot.sh').returncode, 0)
            self.assertTrue((self.path / 'backend-recovery-required').exists())

    def test_absent_owner_lock_blocks_acceptance(self):
        self.prepare_deploy()
        (self.path / 'backend-recovery-required').write_text(f'release={self.release_root}\nphase=pending_acceptance\n')
        self.env.update(PILOT_MANUAL_GATE='verified', EXPECTED_RELEASE=str(self.release_root), FAIL_LOCK='1')
        self.assertNotEqual(self.run_script('accept-shop-pilot.sh').returncode, 0)
        self.assertTrue((self.path / 'backend-recovery-required').exists())

    def test_pending_master_qr_activation_blocks_acceptance_before_docker(self):
        self.prepare_deploy()
        (self.path/'backend-recovery-required').write_text(f'release={self.release_root}\nphase=pending_acceptance\n')
        (self.path/'master-qr-activation-required').write_text('private activation marker')
        self.env.update(PILOT_MANUAL_GATE='verified',EXPECTED_RELEASE=str(self.release_root))
        result=self.run_script('accept-shop-pilot.sh')
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(self.calls.exists())
        self.assertTrue((self.path/'backend-recovery-required').exists())
        self.assertTrue((self.path/'master-qr-activation-required').exists())

    def test_acceptance_refuses_failed_phase_without_docker_queries(self):
        self.prepare_deploy()
        (self.path / 'backend-recovery-required').write_text(f'release={self.release_root}\nbackup=/missing\n')
        self.env.update(PILOT_MANUAL_GATE='verified', EXPECTED_RELEASE=str(self.release_root))
        self.assertNotEqual(self.run_script('accept-shop-pilot.sh').returncode, 0)
        self.assertFalse(self.calls.exists())
        self.assertTrue((self.path / 'backend-recovery-required').exists())

    def test_pending_or_dangling_english_fence_blocks_acceptance(self):
        self.prepare_deploy()
        (self.path/'backend-recovery-required').write_text(f'release={self.release_root}\nphase=pending_acceptance\n')
        self.env.update(PILOT_MANUAL_GATE='verified', EXPECTED_RELEASE=str(self.release_root))
        marker = self.path/'english-backfill-required'
        for symlink in (False, True):
            with self.subTest(symlink=symlink):
                if symlink:
                    marker.symlink_to(self.path/'missing-private-target')
                else:
                    marker.write_text('private recovery state')
                self.assertNotEqual(self.run_script('accept-shop-pilot.sh').returncode, 0)
                self.assertFalse(self.calls.exists())
                self.assertTrue((self.path/'backend-recovery-required').exists())
                self.assertEqual((self.path/'current').resolve(), self.previous.resolve())
                marker.unlink()

    def test_wrong_deployed_image_or_lookup_failure_never_accepts_or_leaks_errors(self):
        self.prepare_deploy()
        (self.path / 'backend-recovery-required').write_text(f'release={self.release_root}\nphase=pending_acceptance\n')
        self.env.update(PILOT_MANUAL_GATE='verified', EXPECTED_RELEASE=str(self.release_root))
        for key, value in [('FAIL_IMAGE_SERVICE', 'blog'), ('FAIL_IMAGE_LOOKUP', '1')]:
            with self.subTest(key=key):
                self.env[key] = value
                result = self.run_script('accept-shop-pilot.sh')
                self.env.pop(key)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('PRIVATE_TEST_SENTINEL', result.stdout + result.stderr)
                self.assertTrue((self.path / 'backend-recovery-required').exists())
                self.assertEqual((self.path / 'current').resolve(), self.previous.resolve())

    def test_pending_or_dangling_shop_online_fence_blocks_acceptance(self):
        self.prepare_deploy()
        (self.path/'backend-recovery-required').write_text(f'release={self.release_root}\nphase=pending_acceptance\n')
        self.env.update(PILOT_MANUAL_GATE='verified',EXPECTED_RELEASE=str(self.release_root))
        marker=self.path/'shop-online-activation-required'
        for symlink in (False,True):
            with self.subTest(symlink=symlink):
                if symlink:
                    marker.symlink_to(self.path/'missing-private-target')
                else:
                    marker.write_text('private recovery state')
                self.assertNotEqual(self.run_script('accept-shop-pilot.sh').returncode,0)
                self.assertFalse(self.calls.exists())
                self.assertTrue((self.path/'backend-recovery-required').exists())
                self.assertEqual((self.path/'current').resolve(),self.previous.resolve())
                marker.unlink()

    def test_frontend_image_mismatch_leaves_current_and_writers_untouched(self):
        self.prepare_deploy()
        self.same_backend()
        self.env['FAIL_IMAGE_SERVICE'] = 'admin-app'
        self.assertNotEqual(self.run_script('deploy.sh').returncode, 0)
        self.assertEqual((self.path / 'current').resolve(), self.previous.resolve())
        self.assertFalse((self.path / 'backend-recovery-required').exists())
        self.assertFalse(any('stop' in call for call in self.operations()))

    def test_old_image_fails_preflight_before_stopping_writers(self):
        self.prepare_deploy()
        self.env['FAIL_PREFLIGHT'] = '1'
        self.assertNotEqual(self.run_script('deploy.sh').returncode, 0)
        self.assertFalse(any('stop' in call or 'up' in call for call in self.operations()))
        self.assertFalse((self.path / 'backend-recovery-required').exists())

    def test_unsafe_incident_store_aborts_before_writers_or_migrations(self):
        self.prepare_deploy()
        store = self.path / 'data/sentry-incidents'
        store.chmod(0o755)
        result = self.run_script('deploy.sh')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Sentry incident store preflight failed', result.stderr)
        self.assertFalse(any('stop' in call or 'up' in call for call in self.operations()))
        self.assertFalse((self.path / 'backend-recovery-required').exists())

    def test_runtime_incident_file_failure_aborts_before_writers_or_migrations(self):
        self.prepare_deploy()
        self.env['FAIL_INCIDENT_FILES'] = '1'
        self.assertNotEqual(self.run_script('deploy.sh').returncode, 0)
        calls = self.operations()
        self.assertTrue(any('--runtime-store' in call for call in calls))
        self.assertFalse(any('stop' in call or 'up' in call or 'migrate' in call for call in calls))
        self.assertFalse((self.path / 'backend-recovery-required').exists())

    def test_actual_preflight_sanitizes_settings_import_validation_failure(self):
        self.prepare_deploy()
        self.env['FAIL_PREFLIGHT'] = '1'
        self.assertNotEqual(self.run_script('deploy.sh').returncode, 0)
        call = next(call for call in self.operations() if any('Backend release preflight failed:' in arg for arg in call))
        code = call[-1]
        self.assertIn('from app.core.config import Settings', code)
        self.assertIn('Settings()', code)
        self.assertIn('import app.services.master_mono', code)
        self.assertIn('import app.services.mono_checkbox_poll', code)
        self.assertIn('["0144_master_rewards"]', code)
        self.assertIn('import app.dependencies.shop_input', code)
        self.assertIn('import app.core.shop_request_size', code)
        for module in ('checkout_reminders', 'checkout_reminder_email', 'checkout_reminder_smtp'):
            self.assertIn('import app.services.' + module, code)
        self.assertIn('import app.utils.backfill_shop_content_en', code)
        self.assertIn('import app.services.shop_online_payment', code)
        self.assertIn('import app.utils.backfill_product_names_en', code)
        self.assertIn('import app.utils.backfill_category_names_en', code)
        harness = '''import builtins
original_import = builtins.__import__
def guarded_import(name, *args, **kwargs):
    if name == 'app.core.config':
        raise ValueError('PRIVATE_SYNTHETIC_VALIDATION_INPUT')
    return original_import(name, *args, **kwargs)
builtins.__import__ = guarded_import
'''
        result = subprocess.run(['python3', '-B', '-c', harness + '\n' + code], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Backend release preflight failed:', result.stderr)
        self.assertNotIn('PRIVATE_SYNTHETIC_VALIDATION_INPUT', result.stdout + result.stderr)
        self.assertNotIn('Traceback', result.stderr)

    def test_mutable_engine_pin_is_rejected_before_pull_or_writer_stop(self):
        self.prepare_deploy()
        path = self.release_root / 'versions/production.env'
        data = path.read_text()
        data = '\n'.join('POSTGRES_IMAGE=postgres:16-alpine' if line.startswith('POSTGRES_IMAGE=') else line
                         for line in data.splitlines())
        path.write_text(data + '\n')
        self.assertNotEqual(self.run_script('deploy.sh').returncode, 0)
        self.assertFalse(any('pull' in call or 'stop' in call or 'up' in call for call in self.operations()))

    def test_backend_deploy_failure_never_automatically_starts_old_code(self):
        self.prepare_deploy()
        self.env["FAIL_UP"] = "1"
        result = self.run_script("deploy.sh")
        self.assertNotEqual(result.returncode, 0)
        calls = self.operations()
        self.assertEqual(sum("up" in call for call in calls), 1)
        self.assertEqual(calls[-1][-5:], ["stop", "--timeout", "90", "backend", "booking-sms-reminders"])
        self.assertEqual((self.path / "current").resolve(), self.previous.resolve())
        self.assertIn("Refusing automatic image rollback", result.stderr)

    def test_failed_backup_or_migration_keeps_writers_stopped(self):
        self.prepare_deploy()
        for failure in ("FAIL_DUMP", "FAIL_LIST", "FAIL_MIGRATE", "FAIL_SCHEMA"):
            with self.subTest(failure=failure):
                self.calls.write_text("")
                (self.path / "backend-recovery-required").unlink(missing_ok=True)
                self.env[failure] = "1"
                result = self.run_script("deploy.sh")
                self.env.pop(failure)
                self.assertNotEqual(result.returncode, 0)
                calls = self.operations()
                self.assertFalse(any("up" in call for call in calls))
                self.assertTrue((self.path / "backend-recovery-required").exists())
                self.assertEqual((self.path / "current").resolve(), self.previous.resolve())

    def test_mutex_rejects_deploy_before_docker(self):
        self.prepare_deploy()
        (self.path / "release.lock").mkdir()
        result = self.run_script("deploy.sh")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.calls.exists())

    def test_failed_backend_health_blocks_a_later_deploy_even_if_pull_would_fail(self):
        self.prepare_deploy()
        self.env["FAIL_HEALTH"] = "1"
        result = self.run_script("deploy.sh")
        self.assertNotEqual(result.returncode, 0)
        marker = self.path / "backend-recovery-required"
        self.assertTrue(marker.exists())
        self.assertEqual(marker.stat().st_mode & 0o777, 0o600)
        before = self.operations()
        self.env.pop("FAIL_HEALTH")
        self.env["FAIL_PULL"] = "1"
        retry = self.run_script("deploy.sh")
        self.assertNotEqual(retry.returncode, 0)
        self.assertIn("Backend recovery is required", retry.stderr)
        self.assertEqual(self.operations(), before)
        self.assertEqual((self.path / "current").resolve(), self.previous.resolve())


if __name__ == "__main__":
    unittest.main()
