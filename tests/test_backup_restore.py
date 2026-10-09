import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
DOCKER_STUB = '''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ["DOCKER_CALLS"], "a") as out:
    out.write(json.dumps(args) + "\\n")
if "--list" in args and os.environ.get("FAIL_LIST"):
    sys.exit(1)
if "ps" in args:
    if os.environ.get("FAIL_PS"):
        sys.exit(1)
    print("synthetic-container" if "-q" in args else os.environ.get("RUNNING_WRITERS", "backend\\nbooking-sms-reminders"))
if "inspect" in args:
    print("unhealthy" if os.environ.get("FAIL_HEALTH") else "healthy")
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
        self.path = Path(self.temp.name)
        self.env = {**os.environ, "APP_DIR": str(self.path), "BACKUP_DIR": str(self.path / "backups")}

    def run_script(self, name, *args):
        return subprocess.run(["bash", str(ROOT / "scripts" / name), *map(str, args)],
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
        (self.path / "env").mkdir()
        for name in ("caddy", "postgres", "backend", "public-site", "blog", "admin-app"):
            (self.path / "env" / f"{name}.env").write_text("# synthetic\n")
        previous = self.path / "previous"
        (previous / "versions").mkdir(parents=True)
        (previous / "versions/production.env").write_text("BACKEND_IMAGE=synthetic:previous\n")
        (self.path / "current").symlink_to(previous)
        self.previous = previous

    def test_backend_deploy_quiesces_writers_and_backs_up_files(self):
        self.prepare_deploy()
        result = self.run_script("deploy.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.operations()
        stop = next(i for i, call in enumerate(calls) if "stop" in call)
        dump = next(i for i, call in enumerate(calls) if any("pg_dump" in arg for arg in call))
        up = next(i for i, call in enumerate(calls) if "up" in call)
        self.assertLess(stop, dump)
        self.assertLess(dump, up)
        self.assertTrue(list((self.path / "backups").glob("*.tar.gz")))
        self.assertEqual((self.path / "current").resolve(), ROOT)
        self.assertFalse((self.path / "backend-recovery-required").exists())

    def test_backend_deploy_failure_never_automatically_starts_old_code(self):
        self.prepare_deploy()
        self.env["FAIL_UP"] = "1"
        result = self.run_script("deploy.sh")
        self.assertNotEqual(result.returncode, 0)
        calls = self.operations()
        self.assertEqual(sum("up" in call for call in calls), 1)
        self.assertEqual(calls[-1][-3:], ["stop", "backend", "booking-sms-reminders"])
        self.assertEqual((self.path / "current").resolve(), self.previous.resolve())
        self.assertIn("Refusing automatic image rollback", result.stderr)

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
