"""Host collector tests use synthetic payloads only; no Docker daemon required."""
import contextlib
import datetime as dt
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "monitoring_collect", Path(__file__).resolve().parents[1] / "monitoring/collect.py")
c = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(c)
NOW = dt.datetime(2026, 10, 23, 10, 0, tzinfo=dt.timezone.utc)
IDENT = "a" * 64
SECRET = ("postgres://user:pass@db/private?token=synthetic-token "
          "+380991234567 person@example.test SELECT private FROM orders "
          "https://example.test/private?q=secret ENV_VALUE=synthetic-password")


class CollectorTests(unittest.TestCase):
    def test_inspect_template_uses_safe_optional_health_lookup(self):
        self.assertNotIn('.State.Health', c.INSPECT)
        self.assertIn('with index .State "Health"', c.INSPECT)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "spool/logs").mkdir(parents=True)
        self.calls = []
        self.ident = IDENT
        self.project = "soulcuts"
        self.logs = "2026-10-23T09:59:59.123456789Z ERROR RuntimeError: " + SECRET

    def docker(self, args):
        self.calls.append(args)
        if args[0] == "ps":
            return self.ident + "\n"
        if args[0] == "inspect":
            service = next(call[call.index("--filter", 5) + 1].split("=")[-1]
                           for call in reversed(self.calls) if call[0] == "ps")
            return json.dumps({"id": self.ident, "project": self.project, "service": service,
                               "state": "running", "health": "healthy",
                               "started": "2026-10-23T09:00:00Z"})
        if args[0] == "stats":
            return json.dumps({"CPUPerc": "12.50%", "MemUsage": "2.5MiB / 1GiB"})
        if args[0] == "logs":
            return self.logs
        raise AssertionError("unexpected command")

    def collect_service(self, state=None):
        with patch.object(c, "docker", self.docker):
            return c.service_collect("backend", self.root, state if state is not None else {}, NOW)

    def test_redaction_all_fields_and_recognized_patterns(self):
        bodies = [SECRET, "ERROR " + SECRET, "RuntimeError: " + SECRET,
                  "HTTP GET 200 " + SECRET, '{"message":"' + SECRET + '"}',
                  "untrusted.RuntimeError: " + SECRET, "INFO ValueError: " + SECRET]
        output = "\n".join(json.dumps(c.event("2026-10-23T09:59:59.123456789Z " + body,
                                              "backend")) for body in bodies)
        for secret in SECRET.split():
            self.assertNotIn(secret, output)
        records = [json.loads(line) for line in output.splitlines()]
        self.assertEqual(records[2]["message"], "RuntimeError (details redacted)")
        self.assertEqual(records[3]["message"], "HTTP GET 200")
        self.assertEqual(records[5]["event"], "application")
        self.assertEqual(set(records[0]), {"timestamp", "service", "level", "event", "message"})

    def test_timestamp_nanoseconds_and_malformed(self):
        self.assertEqual(c.timestamp("2026-10-23T09:59:59.123456789Z").microsecond, 123456)
        for value in ("secret", "2026-99-99T09:59:59Z", "2026-10-23T09:59:59", None):
            with self.assertRaises((ValueError, TypeError)):
                c.timestamp(value)

    def test_uvicorn_access_redacts_address_target_and_query(self):
        for address in ("192.0.2.45:54321", "[2001:db8::1]:54321"):
            body = f'INFO:     {address} - "POST /private?token=synthetic-token&email=person@example.test&phone=+380991234567 HTTP/1.1" 422 Unprocessable Entity'
            record = c.event("2026-10-23T09:59:59Z " + body, "backend")
            self.assertEqual(record["message"], "HTTP POST 422")
            self.assertEqual(record["event"], "http")
            output = json.dumps(record)
            for private in (address, "/private", "synthetic-token", "person@example.test", "+380991234567"):
                self.assertNotIn(private, output)
        for body in ('prefix 192.0.2.45:1 - "GET /secret HTTP/1.1" 200 OK',
                     '192.0.2.45:1 - "SECRET /secret HTTP/1.1" 200 OK',
                     '192.0.2.45:1 - "GET /secret HTTP/1.1" 999 OK'):
            self.assertEqual(c.event("2026-10-23T09:59:59Z " + body, "backend")["event"], "application")

    def test_caddy_structured_level_allowlist_never_copies_message(self):
        for candidate, expected in (("error", "ERROR"), ("warn", "WARNING"),
                                    ("debug", "DEBUG"), ("fatal", "CRITICAL"),
                                    ("unknown " + SECRET, "INFO"), (None, "INFO"),
                                    ([SECRET], "INFO"), (42, "INFO")):
            body = json.dumps({"level": candidate, "msg": SECRET, "request": {"uri": SECRET}})
            record = c.event("2026-10-23T09:59:59Z " + body, "caddy")
            self.assertEqual(record["level"], expected)
            self.assertEqual(record["message"], "Application log (details redacted)")
            for private in SECRET.split():
                self.assertNotIn(private, json.dumps(record))
        for body in (json.dumps({"msg": SECRET}), '{"level":"error",', "[]", "null"):
            self.assertEqual(c.event("2026-10-23T09:59:59Z " + body, "caddy")["level"], "INFO")

    def test_postgres_anchored_severity_redacts_statement(self):
        for severity, expected in (("ERROR", "ERROR"), ("WARNING", "WARNING"),
                                   ("FATAL", "CRITICAL"), ("PANIC", "CRITICAL"),
                                   ("DEBUG1", "DEBUG"), ("LOG", "INFO"),
                                   ("NOTICE", "INFO"), ("UNKNOWN", "INFO")):
            body = f"2026-10-23 09:59:59.123 UTC [1234] {severity}:  {SECRET}"
            record = c.event("2026-10-23T09:59:59Z " + body, "postgres")
            self.assertEqual(record["level"], expected)
            for private in SECRET.split():
                self.assertNotIn(private, json.dumps(record))
        body = "prefix 2026-10-23 09:59:59 UTC [1234] ERROR: " + SECRET
        self.assertEqual(c.event("2026-10-23T09:59:59Z " + body, "postgres")["level"], "INFO")

    def test_health_without_check_and_unhealthy_are_distinct(self):
        original = self.docker
        for status, health, healthy, present in (("running", "none", 1, 0),
                                                ("running", "healthy", 1, 1),
                                                ("running", "unhealthy", 0, 1),
                                                ("running", "starting", 0, 1),
                                                ("exited", "none", 0, 0)):
            def inspect(args):
                output = original(args)
                if args[0] == "inspect":
                    info = json.loads(output)
                    info.update(state=status, health=health)
                    return json.dumps(info)
                return output
            with self.subTest(status=status, health=health), patch.object(c, "docker", inspect):
                values = c.service_collect("booking-sms-reminders", self.root, {}, NOW)
                self.assertEqual(values["soulcuts_service_healthy"], healthy)
                self.assertEqual(values["soulcuts_service_healthcheck_present"], present)
                self.assertEqual(values["soulcuts_service_collection_errors"], 0)

    def test_service_metrics_safe_cli_and_modes(self):
        state = {}
        values = self.collect_service(state)
        self.assertEqual(values["soulcuts_service_collection_errors"], 0)
        self.assertEqual(values["soulcuts_container_memory_bytes"], 2.5 * 1024 ** 2)
        self.assertEqual(values["soulcuts_container_cpu_percent"], 12.5)
        self.assertEqual(values["soulcuts_service_uptime_seconds"], 3600)
        self.assertEqual(values["soulcuts_service_healthy"], 1)
        for call in self.calls:
            self.assertIn(call[0], ("ps", "inspect", "stats", "logs"))
            self.assertNotIn("exec", call)
            self.assertNotIn(".Config.Env", " ".join(call))
        logcall = self.calls[-1]
        self.assertEqual(logcall[logcall.index("--tail") + 1], "200")
        self.assertEqual(logcall[logcall.index("--since") + 1], "2026-10-23T09:59:00.000000Z")
        self.assertEqual((self.root / "state.json").stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.root / "spool/logs/backend.log").stat().st_mode & 0o777, 0o640)
        self.assertNotIn("synthetic", (self.root / "spool/logs/backend.log").read_text())

    def test_identity_mismatch_and_truncated_id(self):
        self.project = "other"
        self.assertEqual(self.collect_service()["soulcuts_service_collection_errors"], 1)
        self.assertFalse(any(call[0] == "logs" for call in self.calls))
        self.calls.clear()
        self.ident = "a" * 12
        self.collect_service()
        self.assertEqual(len(self.calls), 1)

    def test_cursor_restart_and_resume(self):
        state = {"backend": {"id": IDENT, "until": "2026-10-23T09:50:00Z"}}
        self.collect_service(state)
        self.assertIn("2026-10-23T09:50:00.000000Z", self.calls[-1])
        self.calls.clear()
        self.ident = "b" * 64
        self.collect_service(state)
        self.assertIn("2026-10-23T09:59:00.000000Z", self.calls[-1])
        self.assertEqual(state["backend"]["id"], "b" * 64)

    def test_fsync_failure_does_not_advance_cursor(self):
        state = {}
        with patch.object(c.os, "fsync", side_effect=OSError(SECRET)):
            self.assertEqual(self.collect_service(state)["soulcuts_service_collection_errors"], 1)
        self.assertEqual(state, {})
        self.assertFalse((self.root / "state.json").exists())

    def test_cursor_write_failure_does_not_advance(self):
        state = {}
        with patch.object(c, "atomic", side_effect=OSError(SECRET)):
            self.collect_service(state)
        self.assertEqual(state, {})

    def test_malformed_logs_counted_and_never_written(self):
        self.logs += "\n" + SECRET + "\n2026-10-23T09:59:59Z " + SECRET
        self.assertEqual(self.collect_service()["soulcuts_service_collection_errors"], 1)
        self.assertNotIn("synthetic", (self.root / "spool/logs/backend.log").read_text())

    def test_rotation_only_one_backup(self):
        path = self.root / "spool/logs/backend.log"
        record = c.event("2026-10-23T09:59:59Z " + SECRET, "backend")
        with patch.object(c, "MAX_LOG", 300):
            for _ in range(5):
                c.append_events(path, [record])
        self.assertLessEqual(path.stat().st_size, 300)
        self.assertLessEqual(path.with_suffix(".log.1").stat().st_size, 300)
        self.assertEqual(len(list(path.parent.iterdir())), 2)

    def spool_record(self, date):
        return (json.dumps(c.event(date + " " + SECRET, "backend")) + "\n").encode()

    def test_quiet_service_prunes_active_and_rotated_under_lock(self):
        import fcntl
        now = dt.datetime.now(dt.timezone.utc)
        expired = self.spool_record(c.iso(now - dt.timedelta(hours=73)))
        fresh = self.spool_record(c.iso(now - dt.timedelta(hours=1)))
        paths = [self.root / ("spool/logs/backend" + suffix) for suffix in (".log", ".log.1")]
        for path in paths:
            path.write_bytes(expired + fresh)
        self.logs = ""
        original = c.prune_spool
        def prune(path, service, collected_at):
            with (self.root / "collector.lock").open("r") as lock:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return original(path, service, collected_at)
        with patch.object(c, "host_metrics", return_value=({}, [100, 80])), \
                patch.object(c, "docker", self.docker), patch.object(c, "prune_spool", prune):
            self.assertEqual(c.collect(self.root), 0)
        for path in paths:
            self.assertEqual(path.read_bytes(), fresh)
            self.assertEqual(path.stat().st_mode & 0o777, 0o640)

    def test_retention_timezone_boundary_and_future_dates(self):
        path = self.root / "spool/logs/backend.log"
        boundary = self.spool_record("2026-10-20T13:00:00+03:00")
        fresh = self.spool_record("2026-10-20T05:00:01-05:00")
        expired = self.spool_record("2026-10-20T12:59:59+03:00")
        future = self.spool_record("2026-10-24T10:00:00Z")
        path.write_bytes(boundary + expired + fresh + future)
        c.prune_spool(path, "backend", NOW)
        self.assertEqual(path.read_bytes(), boundary + fresh)

    def test_all_fresh_retention_leaves_inode_mtime_and_bytes_unchanged(self):
        for suffix in (".log", ".log.1"):
            path = self.root / ("spool/logs/backend" + suffix)
            data = self.spool_record("2026-10-23T09:59:59.123456789Z")
            path.write_bytes(data)
            before = path.stat()
            with patch.object(c.os, "replace") as replace, patch.object(c.os, "fsync") as fsync:
                c.prune_spool(path, "backend", NOW)
            replace.assert_not_called()
            fsync.assert_not_called()
            self.assertEqual(path.read_bytes(), data)
            self.assertEqual(path.stat().st_ino, before.st_ino)
            self.assertEqual(path.stat().st_mtime_ns, before.st_mtime_ns)

    def test_retention_malformed_records_fail_closed_without_staging_them(self):
        path = self.root / "spool/logs/backend.log"
        fresh = self.spool_record("2026-10-23T09:59:59Z")
        malformed = [SECRET.encode() + b"\n", b"\xff\n", b"null\n", b"{}\n",
                     b'{"timestamp":"2026-10-23T09:59:59Z","private":"synthetic-token"}\n',
                     fresh.replace(b'"INFO"', b'[]'),
                     fresh.replace(b'"2026-10-23T09:59:59.000000Z"', b'"bad-date"'),
                     fresh.replace(b'Application log (details redacted)', SECRET.encode())]
        path.write_bytes(b"".join(malformed) + fresh)
        original = c.os.replace
        def replace(source, destination, **kwargs):
            fd = os.open(source, os.O_RDONLY, dir_fd=kwargs["src_dir_fd"])
            with os.fdopen(fd, "rb") as staged:
                self.assertEqual(staged.read(), fresh)
            return original(source, destination, **kwargs)
        with patch.object(c.os, "replace", replace):
            c.prune_spool(path, "backend", NOW)
        self.assertEqual(path.read_bytes(), fresh)
        self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_retention_symlink_refusal_active_backup_and_temp(self):
        target = self.root / "untouched"
        target.write_bytes(b"synthetic-secret")
        for suffix in (".log", ".log.1"):
            path = self.root / ("spool/logs/backend" + suffix)
            path.symlink_to(target)
            with self.assertRaises(OSError):
                c.prune_spool(path, "backend", NOW)
            self.assertTrue(path.is_symlink())
            path.unlink()
        path = self.root / "spool/logs/backend.log"
        expired = self.spool_record("2026-10-19T10:00:00Z")
        path.write_bytes(expired)
        temp = path.with_name(path.name + ".prune-fixed.tmp")
        temp.symlink_to(target)
        with patch.object(c.uuid, "uuid4") as identifier:
            identifier.return_value.hex = "fixed"
            with self.assertRaises(FileExistsError):
                c.prune_spool(path, "backend", NOW)
        self.assertTrue(temp.is_symlink())
        self.assertEqual(target.read_bytes(), b"synthetic-secret")
        self.assertEqual(path.read_bytes(), expired)

    def test_retention_fsync_failure_preserves_original(self):
        path = self.root / "spool/logs/backend.log"
        expired = self.spool_record("2026-10-19T10:00:00Z")
        path.write_bytes(expired)
        with patch.object(c.os, "fsync", side_effect=OSError(SECRET)):
            with self.assertRaises(OSError):
                c.prune_spool(path, "backend", NOW)
        self.assertEqual(path.read_bytes(), expired)
        self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_old_cursor_cannot_reintroduce_expired_records(self):
        state = {"backend": {"id": IDENT, "until": "2026-10-01T10:00:00Z"}}
        self.logs = "2026-10-19T10:00:00Z " + SECRET
        values = self.collect_service(state)
        self.assertIn("2026-10-20T10:00:00.000000Z", self.calls[-1])
        self.assertEqual((self.root / "spool/logs/backend.log").read_bytes(), b"")
        self.assertEqual(values["soulcuts_service_collection_errors"], 1)

    def test_retention_symlink_failure_reports_fixed_error_and_skips_docker(self):
        target = self.root / "untouched"
        target.write_text("synthetic-secret")
        (self.root / "spool/logs/backend.log.1").symlink_to(target)
        with patch.object(c, "docker") as docker, contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(c.collect(self.root), 1)
        docker.assert_not_called()
        self.assertEqual(target.read_text(), "synthetic-secret")
        self.assertEqual(err.getvalue(), "collector: collection failed\n")
        output = (self.root / "spool/metrics/soulcuts.prom").read_text()
        self.assertIn("soulcuts_collector_success 0", output)
        self.assertNotIn("synthetic", output)

    def test_oversized_retention_discards_without_unbounded_read(self):
        path = self.root / "spool/logs/backend.log"
        path.write_bytes(b"x" * 1025)
        with patch.object(c, "MAX_LOG", 1024):
            c.prune_spool(path, "backend", NOW)
        self.assertEqual(path.read_bytes(), b"")

    def test_stat_parse_rejects_nonfinite_and_units(self):
        self.assertEqual(c.memory("1.25 GB"), 1250000000)
        for bad in ("nan", "inf", "-1"):
            with self.assertRaises(ValueError):
                c.number(bad)
        for bad in ("1 secrets", "NaNMiB", "-1B"):
            with self.assertRaises(ValueError):
                c.memory(bad)

    def test_timeout_service_errors_and_no_secret_stderr(self):
        with patch.object(c, "docker", side_effect=subprocess.TimeoutExpired(SECRET, 3)):
            values = c.service_collect("backend", self.root, {}, NOW)
        self.assertEqual(values["soulcuts_service_collection_errors"], 1)
        self.assertEqual(values["soulcuts_service_running"], 0)

    def test_global_failure_preserves_samples_marks_failure(self):
        path = self.root / "spool/metrics"
        path.mkdir()
        metric = path / "soulcuts.prom"
        metric.write_text('soulcuts_container_cpu_percent{service="backend"} 12\n'
                          'soulcuts_collector_success 1\n'
                          'soulcuts_collector_last_success_unixtime 123\n')
        with patch.object(c, "host_metrics", side_effect=c.Deadline()), contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(c.collect(self.root), 1)
        output = metric.read_text()
        self.assertIn('soulcuts_container_cpu_percent{service="backend"} 12', output)
        self.assertIn("soulcuts_collector_success 0", output)
        self.assertIn("soulcuts_collector_last_success_unixtime 123", output)
        self.assertNotIn("soulcuts_collector_success 1", output)
        self.assertEqual(err.getvalue(), "collector: collection failed\n")

    def test_nonoverlapping_runs(self):
        import fcntl
        with (self.root / "collector.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with patch.object(c, "docker") as mock:
                self.assertEqual(c.collect(self.root), 0)
                mock.assert_not_called()

    def test_collect_all_eight_files_and_metric_permissions(self):
        self.logs = ""
        host = ({"soulcuts_host_cpu_busy_ratio": .2}, [100, 80])
        with patch.object(c, "host_metrics", return_value=host), patch.object(c, "docker", self.docker):
            self.assertEqual(c.collect(self.root), 0)
        self.assertEqual({p.stem for p in (self.root / "spool/logs").iterdir()}, set(c.SERVICES))
        self.assertEqual((self.root / "spool/logs").stat().st_mode & 0o777, 0o750)
        metric = self.root / "spool/metrics/soulcuts.prom"
        self.assertEqual(metric.stat().st_mode & 0o777, 0o644)
        self.assertIn("soulcuts_collector_success 1", metric.read_text())

    def test_unknown_service_cannot_invoke_docker(self):
        with patch.object(c, "docker") as mock:
            with self.assertRaises(c.CollectionError):
                c.service_collect("not-allowed", self.root, {}, NOW)
            mock.assert_not_called()

    def test_main_does_not_limit_docker_address_space(self):
        import sys
        with patch.object(sys, "argv", ["collect.py", "--root", str(self.root)]), \
                patch.object(c.resource, "setrlimit") as limits, \
                patch.object(c, "collect", return_value=0), patch.object(c.os, "umask"):
            self.assertEqual(c.main(), 0)
        self.assertEqual(limits.call_args_list, [
            unittest.mock.call(c.resource.RLIMIT_CORE, (0, 0)),
            unittest.mock.call(c.resource.RLIMIT_CPU, (20, 20))])

    def test_monotonic_uptime_ignores_wall_clock_change(self):
        state = {"backend": {"id": IDENT, "until": "2026-10-23T09:59:00Z",
                             "started": "2026-10-23T09:00:00Z", "uptime": 4000,
                             "monotonic": 100}}
        with patch.object(c.time, "monotonic", return_value=160):
            self.assertEqual(self.collect_service(state)["soulcuts_service_uptime_seconds"], 4060)

    def test_docker_runner_bounds_timeout_and_output(self):
        import sys
        original = subprocess.Popen
        for program, limit in (("import time; time.sleep(2)", 1000),
                               ("print('x' * 5000)", 100)):
            def launch(args, **kwargs):
                self.assertEqual(args, ["docker", "logs", IDENT])
                self.assertNotIn("DOCKER_HOST", kwargs["env"])
                return original([sys.executable, "-c", program], **kwargs)
            with patch.object(c.subprocess, "Popen", side_effect=launch), \
                    patch.object(c, "CALL_TIMEOUT", .1), patch.object(c, "MAX_OUTPUT", limit):
                with self.assertRaises(c.CollectionError):
                    c.docker(["logs", IDENT])

    def test_docker_runner_discards_command_failure_payload(self):
        import sys
        original = subprocess.Popen
        def launch(args, **kwargs):
            return original([sys.executable, "-c", "import sys; print('synthetic-secret'); sys.exit(1)"], **kwargs)
        with patch.object(c.subprocess, "Popen", side_effect=launch):
            with self.assertRaises(c.CollectionError) as error:
                c.docker(["inspect", IDENT])
        self.assertEqual(str(error.exception), "")

    def test_host_proc_metrics(self):
        files = {"/proc/meminfo": "MemTotal: 1000 kB\nMemAvailable: 250 kB\n",
                 "/proc/stat": "cpu  20 0 10 60 10 0 0 0 0 0\n",
                 "/proc/uptime": "1234.5 100\n",
                 "/proc/net/dev": "header\nheader\n lo: 99 0 0 0 0 0 0 0 99\n eth0: 42 0 0 0 0 0 0 0 84\n"}
        with patch.object(c.Path, "read_text", lambda path: files[str(path)]):
            metrics, cpu = c.host_metrics(self.root, {"cpu": [50, 40]})
        self.assertEqual(cpu, [100, 70])
        self.assertAlmostEqual(metrics["soulcuts_host_cpu_busy_ratio"], .4)
        self.assertEqual(metrics["soulcuts_host_memory_total_bytes"], 1024000)
        self.assertEqual(metrics["soulcuts_host_memory_available_bytes"], 256000)
        self.assertEqual(metrics["soulcuts_host_network_receive_bytes_total"], 42)
        self.assertEqual(metrics["soulcuts_host_network_transmit_bytes_total"], 84)
        self.assertGreater(metrics["soulcuts_host_disk_size_bytes"], 0)

    def test_real_global_alarm_marks_failure(self):
        import time
        with patch.object(c, "GLOBAL_TIMEOUT", 1), \
                patch.object(c, "host_metrics", side_effect=lambda *_: time.sleep(2)), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(c.collect(self.root), 1)
        output = (self.root / "spool/metrics/soulcuts.prom").read_text()
        self.assertIn("soulcuts_collector_success 0", output)
        self.assertIn("soulcuts_collector_last_success_unixtime 0", output)

    def test_corrupt_stats_is_fixed_error_not_exception_text(self):
        original = self.docker
        def bad_stats(args):
            return '{"CPUPerc":null}' if args[0] == "stats" else original(args)
        with patch.object(c, "docker", bad_stats):
            result = c.service_collect("backend", self.root, {}, NOW)
        self.assertEqual(result["soulcuts_service_collection_errors"], 1)
        self.assertFalse((self.root / "state.json").exists())

    def test_partial_failure_replaces_previous_healthy_metrics(self):
        self.logs = ""
        with patch.object(c, "host_metrics", return_value=({}, [100, 80])), \
                patch.object(c, "docker", self.docker):
            self.assertEqual(c.collect(self.root), 0)
        previous = json.loads((self.root / "state.json").read_text())["last_success"]
        with patch.object(c, "host_metrics", return_value=({}, [100, 80])), \
                patch.object(c, "docker", side_effect=OSError(SECRET)), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(c.collect(self.root), 1)
        output = (self.root / "spool/metrics/soulcuts.prom").read_text()
        self.assertIn("soulcuts_collector_success 0", output)
        self.assertIn(f"soulcuts_collector_last_success_unixtime {previous}", output)
        for service in c.SERVICES:
            self.assertIn(f'soulcuts_service_running{{service="{service}"}} 0', output)
            self.assertIn(f'soulcuts_service_collection_errors{{service="{service}"}} 1', output)
        self.assertNotIn("synthetic", output + err.getvalue())


if __name__ == "__main__":
    unittest.main()
