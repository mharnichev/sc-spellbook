import contextlib
import datetime
import importlib.util
import io
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("deploy_under_test", ROOT / "monitoring/deploy.py")
deploy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(deploy)


class MonitoringDeployTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        # Every subprocess is blocked unless a test supplies a mock response.
        self.process = patch.object(deploy.subprocess, "run", side_effect=AssertionError("Unexpected subprocess"))
        self.process.start()
        self.addCleanup(self.process.stop)

    def test_cron_preserves_existing_bytes_and_refuses_duplicate_or_partial_block(self):
        for existing in ("", "MAILTO=ops\n0 2 * * * backup\n", "0 2 * * * backup"):
            with self.subTest(existing=existing):
                result = deploy.cron_text(existing)
                self.assertTrue(result.startswith(existing))
                self.assertEqual(result.count(deploy.CRON_ENTRY), 1)
                self.assertTrue(result.endswith(deploy.CRON_END + "\n"))
                with self.assertRaises(deploy.DeploymentError):
                    deploy.cron_text(result)
        for existing in (deploy.CRON_BEGIN, deploy.CRON_END):
            with self.assertRaises(deploy.DeploymentError):
                deploy.cron_text(existing)

    def test_read_cron_only_accepts_explicit_no_crontab_or_success(self):
        cases = ((0, "existing\n", "", "existing\n"), (1, "", "no crontab for synthetic", ""))
        for code, stdout, stderr, expected in cases:
            with patch.object(deploy.subprocess, "run", return_value=subprocess.CompletedProcess([], code, stdout, stderr)):
                self.assertEqual(deploy.read_cron(), expected)
        for code, stdout, stderr in ((1, "", "permission denied"), (1, "partial", "no crontab for synthetic"), (2, "", "failure")):
            with patch.object(deploy.subprocess, "run", return_value=subprocess.CompletedProcess([], code, stdout, stderr)):
                with self.assertRaises(deploy.DeploymentError):
                    deploy.read_cron()

    def pin_file(self, lines):
        path = self.root / "monitoring/images.env"
        path.parent.mkdir(exist_ok=True)
        path.write_text("\n".join(lines) + "\n")

    def valid_pins(self):
        repos = ("grafana/grafana", "prom/prometheus", "grafana/loki", "grafana/alloy", "prom/node-exporter")
        return {deploy.KEYS[s]: repo + ":1.2.3@sha256:" + "a" * 64
                for s, repo in zip(deploy.SERVICES, repos)}

    def test_image_pins_accept_digest_and_reject_mutable_unknown_duplicate_missing(self):
        expected = self.valid_pins()
        lines = [key + "=" + value for key, value in expected.items()]
        self.pin_file(["# synthetic fixture", "", *lines])
        self.assertEqual(deploy.pins(self.root), expected)
        bad_cases = [lines + [lines[0]], lines + ["UNKNOWN_IMAGE=" + next(iter(expected.values()))], lines[:-1]]
        for value in ("grafana/grafana:latest", "grafana/grafana:1@sha256:abc", "untrusted/grafana:1@sha256:" + "a" * 64,
                      "grafana/grafana:1@sha256:" + "A" * 64):
            bad_cases.append(["GRAFANA_IMAGE=" + value, *lines[1:]])
        for bad in bad_cases:
            with self.subTest(lines=bad):
                self.pin_file(bad)
                with self.assertRaises(deploy.DeploymentError):
                    deploy.pins(self.root)

    def test_secret_created_preserved_private_and_never_printed(self):
        path = self.root / "synthetic-secret"
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            first = deploy.secret(path)
            original = path.read_bytes()
            with patch.object(deploy.secrets, "token_urlsafe", side_effect=AssertionError("Must preserve existing secret")):
                self.assertEqual(deploy.secret(path), first)
            self.assertEqual(path.read_bytes(), original)
        self.assertGreaterEqual(len(first), 32)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o640)
        self.assertEqual((output.getvalue(), errors.getvalue()), ("", ""))

    def test_secret_rejects_public_permissions_short_values_and_symlinks(self):
        target = self.root / "target"
        target.write_text("s" * 40)
        target.chmod(0o644)
        with self.assertRaises(deploy.DeploymentError):
            deploy.secret(target)
        target.chmod(0o600)
        link = self.root / "link"
        link.symlink_to(target)
        with self.assertRaises(deploy.DeploymentError):
            deploy.secret(link)
        self.assertEqual(target.read_text(), "s" * 40)
        target.write_text("short")
        with self.assertRaises(deploy.DeploymentError):
            deploy.secret(target)

    def test_existing_production_lock_is_not_removed_or_modified(self):
        lock = self.root / "release.lock"
        lock.mkdir()
        (lock / "pid").write_text("other-owner\n")
        with patch.object(deploy, "APP", self.root):
            with self.assertRaises(deploy.DeploymentError):
                with deploy.release_lock():
                    self.fail("Existing lock must prevent entry")
        self.assertTrue(lock.is_dir())
        self.assertEqual((lock / "pid").read_text(), "other-owner\n")

    def install_paths(self, stack):
        revision = "a" * 40
        monitoring = self.root / "monitoring"
        release = monitoring / "releases" / revision
        release.mkdir(parents=True)
        stack.enter_context(patch.object(deploy, "APP", self.root))
        stack.enter_context(patch.object(deploy, "ROOT", monitoring))
        stack.enter_context(patch.object(deploy, "__file__", str(release / "monitoring/deploy.py")))
        return revision

    def test_install_refuses_nonimmutable_path_invalid_revision_and_root_before_commands(self):
        with patch.object(deploy, "run") as run:
            for revision in ("a" * 40, "main", "A" * 40, "a" * 39):
                with self.assertRaisesRegex(deploy.DeploymentError, "immutable"):
                    deploy.install(revision)
            with contextlib.ExitStack() as stack:
                revision = self.install_paths(stack)
                stack.enter_context(patch.object(deploy.os, "getuid", return_value=0))
                with self.assertRaisesRegex(deploy.DeploymentError, "unprivileged"):
                    deploy.install(revision)
            run.assert_not_called()

    def test_install_preflight_refuses_disk_and_old_docker_without_application_commands(self):
        with contextlib.ExitStack() as stack:
            revision = self.install_paths(stack)
            stack.enter_context(patch.object(deploy.os, "getuid", return_value=1234))
            disk = stack.enter_context(patch.object(deploy.shutil, "disk_usage"))
            run = stack.enter_context(patch.object(deploy, "run", return_value="27.5.0"))
            app = stack.enter_context(patch.object(deploy, "application_state"))
            disk.return_value.free = 0
            with self.assertRaises(deploy.DeploymentError):
                deploy.install(revision)
            run.assert_not_called()
            disk.return_value.free = 20 * 2**30
            with self.assertRaises(deploy.DeploymentError):
                deploy.install(revision)
            self.assertEqual(run.call_args.args[0], ["docker", "info", "--format", "{{.ServerVersion}}"])
            app.assert_not_called()

    def test_install_commands_only_start_isolated_monitoring_services(self):
        class StopBeforeRuntime(Exception):
            pass

        commands = []

        def run(args, **kwargs):
            commands.append(args)
            if args[:2] == ["docker", "info"]:
                return "28.0.0"
            if "up" in args:
                raise StopBeforeRuntime()
            return ""

        with contextlib.ExitStack() as stack:
            revision = self.install_paths(stack)
            stack.enter_context(patch.dict(deploy.os.environ, {}, clear=False))
            stack.enter_context(patch.object(deploy.os, "getuid", return_value=1234))
            disk = stack.enter_context(patch.object(deploy.shutil, "disk_usage"))
            disk.return_value.free = 20 * 2**30
            stack.enter_context(patch.object(deploy, "release_lock", return_value=contextlib.nullcontext()))
            for name, result in (("application_state", {}), ("directory", None), ("secret", "s" * 40),
                                 ("pins", self.valid_pins()), ("read_cron", ""), ("durable_json", None)):
                stack.enter_context(patch.object(deploy, name, return_value=result))
            stack.enter_context(patch.object(deploy, "run", side_effect=run))
            with self.assertRaises(StopBeforeRuntime):
                deploy.install(revision)
        starts = [args for args in commands if "up" in args]
        self.assertEqual(len(starts), 1)
        self.assertEqual(starts[0][starts[0].index("up"):], ["up", "-d", "--no-deps", *deploy.SERVICES])
        for args in commands:
            if args[:2] == ["docker", "compose"]:
                self.assertEqual(args[args.index("--project-name") + 1], "soulcuts-monitoring")
                self.assertFalse(set(args) & set(deploy.APP_SERVICES))
                self.assertFalse(set(args) & {"down", "restart", "rm", "stop", "build"})

    def test_cron_changed_during_acceptance_aborts_without_crontab_write(self):
        original = "0 2 * * * original-job\n"
        changed = original + "0 3 * * * newly-added-job\n"
        events = []

        def read_cron():
            events.append("read-cron")
            return original if events.count("read-cron") == 1 else changed

        def ready(*args, **kwargs):
            events.append("acceptance")
            return {"status": "PASS"}

        with contextlib.ExitStack() as stack:
            revision = self.install_paths(stack)
            stack.enter_context(patch.dict(deploy.os.environ, {}, clear=False))
            stack.enter_context(patch.object(deploy.os, "getuid", return_value=1234))
            disk = stack.enter_context(patch.object(deploy.shutil, "disk_usage"))
            disk.return_value.free = 20 * 2**30
            stack.enter_context(patch.object(deploy, "release_lock", return_value=contextlib.nullcontext()))
            for name, result in (("application_state", {}), ("directory", None), ("secret", "s" * 40),
                                 ("pins", self.valid_pins()), ("durable_json", None),
                                 ("verify_containers", None), ("sync_dir", None), ("Grafana", Mock())):
                stack.enter_context(patch.object(deploy, name, return_value=result))
            cron = stack.enter_context(patch.object(deploy, "read_cron", side_effect=read_cron))
            wait = stack.enter_context(patch.object(deploy, "wait_ready", side_effect=ready))
            run = stack.enter_context(patch.object(deploy, "run", return_value="28.0.0"))
            collector = Mock(dt=datetime)
            stack.enter_context(patch.object(deploy.importlib.util, "spec_from_file_location", return_value=Mock()))
            stack.enter_context(patch.object(deploy.importlib.util, "module_from_spec", return_value=collector))
            with self.assertRaisesRegex(deploy.DeploymentError, "Crontab changed"):
                deploy.install(revision)
            self.assertEqual(events, ["read-cron", "acceptance", "read-cron"])
            self.assertEqual(cron.call_count, 2)
            wait.assert_called_once()
            collector.append_events.assert_called_once()
            self.assertFalse(any(call.args[0][0] == "crontab" for call in run.call_args_list))


if __name__ == "__main__":
    unittest.main()
