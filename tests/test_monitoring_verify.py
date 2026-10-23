import base64
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import urllib.parse


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("verify_under_test", ROOT / "monitoring/verify.py")
verify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify)


class MonitoringVerifyTests(unittest.TestCase):
    def setUp(self):
        blocker = patch.object(verify.urllib.request, "urlopen", side_effect=AssertionError("Network forbidden"))
        blocker.start()
        self.addCleanup(blocker.stop)
        self.client = verify.Grafana("http://127.0.0.1:3300", "synthetic-test-only")
        self.sources = [{"uid": "soulcuts-prometheus"}, {"uid": "soulcuts-loki"}]
        self.dashboard = {"uid": "soulcuts-production", "panels": [{} for _ in range(11)]}
        self.metrics = {
            "sum(soulcuts_service_running)": 8, "sum(soulcuts_service_healthy)": 8,
            "sum(soulcuts_service_healthcheck_present)": 7, "sum(up)": 4,
            "soulcuts_collector_success": 1, "node_textfile_scrape_error": 0,
            "time() - soulcuts_collector_last_success_unixtime": 10,
            "soulcuts_host_memory_total_bytes": 1024,
            "soulcuts_collector_last_attempt_unixtime": 1100,
        }
        self.anonymous_allowed = False
        self.log_status = "success"
        self.lines = ["synthetic monitoring_smoke fixture-marker"]
        self.expected_marker = None
        self.calls = []

    def fake_get(self, path, authenticated=True):
        self.calls.append((path, authenticated))
        if path == "/api/health":
            return {"database": "ok"}
        if path == "/api/search" and not authenticated:
            if self.anonymous_allowed:
                return []
            raise verify.VerificationError("Denied")
        if path == "/api/datasources":
            return self.sources
        if path.endswith("/health"):
            return {"status": "OK"}
        if path == "/api/dashboards/uid/soulcuts-production":
            return {"dashboard": self.dashboard}
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)
        if "/soulcuts-prometheus/" in path:
            expression = query["query"][0]
            value = self.metrics.get(expression)
            return {"status": "success", "data": {"result": [] if value is None else [{"value": [1000, str(value)]}]}}
        if "/soulcuts-loki/" in path:
            expression = '{job="soulcuts"}'
            if self.expected_marker:
                expression += ' |= ' + json.dumps(self.expected_marker)
            self.assertEqual(query, {"query": [expression], "limit": ["200"], "since": ["15m"]})
            return {"status": self.log_status, "data": {"result": [{"values": [["1000000000", line] for line in self.lines]}]}}
        raise AssertionError("Unexpected API path: " + path)

    def check(self, **kwargs):
        self.expected_marker = kwargs.get("marker")
        with patch.object(self.client, "get", side_effect=self.fake_get):
            return self.client.verify(**kwargs)

    def test_marker_filter_runs_on_server_before_limit_with_over_200_newer_events(self):
        marker = 'fixture-"literal\\marker'
        newest_first = [f"unrelated newer event {i}" for i in range(250)] + ["synthetic " + marker]
        self.assertFalse(any(marker in line for line in newest_first[:200]))

        def get(path, authenticated=True):
            if "/loki/api/v1/query_range?" not in path:
                return self.fake_get(path, authenticated)
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)
            self.assertEqual(query["query"], ['{job="soulcuts"} |= ' + json.dumps(marker)])
            self.assertEqual(query["limit"], ["200"])
            self.assertEqual(query["since"], ["15m"])
            # Model Loki's literal filtering before applying the response cap.
            filtered = [line for line in newest_first if marker in line][:int(query["limit"][0])]
            return {"status": "success", "data": {"result": [{"values": [["1000000000", line] for line in filtered]}]}}

        with patch.object(self.client, "get", side_effect=get):
            report = self.client.verify(marker=marker)
        self.assertEqual(report["status"], "PASS")
        self.assertIs(report["synthetic_marker_received"], True)

    def test_only_http_loopback_is_accepted(self):
        for url in ("http://127.0.0.1:3300", "http://localhost:3300"):
            self.assertIsInstance(verify.Grafana(url, "synthetic"), verify.Grafana)
        for url in ("https://127.0.0.1:3300", "http://example.org", "http://0.0.0.0:3300",
                    "http://127.0.0.1.example.org", "http://localhost@example.org", "file:///tmp/grafana"):
            with self.subTest(url=url), self.assertRaises(verify.VerificationError):
                verify.Grafana(url, "synthetic")

    def test_get_authentication_headers_and_sanitized_failure(self):
        response = io.BytesIO(json.dumps({"database": "ok"}).encode())
        with patch.object(verify.urllib.request, "urlopen") as open_url:
            open_url.return_value.__enter__.return_value = response
            self.assertEqual(self.client.get("/api/health"), {"database": "ok"})
            request = open_url.call_args.args[0]
            expected = "Basic " + base64.b64encode(b"admin:synthetic-test-only").decode()
            self.assertEqual(request.get_header("Authorization"), expected)
            self.assertEqual(open_url.call_args.kwargs["timeout"], 10)
            open_url.return_value.__enter__.return_value = io.BytesIO(b'{"database":"ok"}')
            self.client.get("/api/health", authenticated=False)
            self.assertIsNone(open_url.call_args.args[0].get_header("Authorization"))
        with patch.object(verify.urllib.request, "urlopen", side_effect=RuntimeError("PRIVATE_RESPONSE")):
            with self.assertRaises(verify.VerificationError) as error:
                self.client.get("/api/search", authenticated=False)
            self.assertEqual(str(error.exception), "Monitoring API check failed")

    def test_success_requires_auth_datasources_dashboard_metrics_and_marker(self):
        report = self.check(marker="fixture-marker", collected_after=1000)
        self.assertEqual(report["status"], "PASS")
        self.assertIs(report["synthetic_marker_received"], True)
        self.assertIs(report["scheduled_collection_verified"], True)
        self.assertIn(("/api/search", False), self.calls)
        self.assertTrue(all(auth for path, auth in self.calls if path not in {"/api/health", "/api/search"}))

    def test_anonymous_dashboard_access_is_refused(self):
        self.anonymous_allowed = True
        with self.assertRaises(verify.VerificationError):
            self.check()

    def test_missing_or_unexpected_datasources_are_refused(self):
        for sources in ([], [{"uid": "soulcuts-prometheus"}], [*self.sources, {"uid": "unexpected"}]):
            self.sources = sources
            with self.subTest(sources=sources), self.assertRaises(verify.VerificationError):
                self.check()

    def test_missing_dashboard_or_insufficient_panels_are_refused(self):
        for dashboard in ({"uid": "wrong", "panels": [{}] * 11}, {"uid": "soulcuts-production", "panels": []}):
            self.dashboard = dashboard
            with self.subTest(dashboard=dashboard), self.assertRaises(verify.VerificationError):
                self.check()

    def test_missing_each_required_metric_is_refused(self):
        for expression in list(self.metrics):
            value = self.metrics.pop(expression)
            with self.subTest(expression=expression), self.assertRaises(verify.VerificationError):
                self.check(collected_after=1000)
            self.metrics[expression] = value

    def test_failed_collection_stale_or_future_success_age_is_refused(self):
        self.metrics["soulcuts_collector_success"] = 0
        with self.assertRaises(verify.VerificationError):
            self.check()
        self.metrics["soulcuts_collector_success"] = 1
        for age in (180, 181, -1):
            self.metrics["time() - soulcuts_collector_last_success_unixtime"] = age
            with self.subTest(age=age), self.assertRaises(verify.VerificationError):
                self.check()

    def test_scheduled_tick_must_be_after_install_boundary(self):
        for attempt in (999, 1000):
            self.metrics["soulcuts_collector_last_attempt_unixtime"] = attempt
            with self.subTest(attempt=attempt), self.assertRaises(verify.VerificationError):
                self.check(collected_after=1000)
        self.metrics["soulcuts_collector_last_attempt_unixtime"] = 1001
        self.assertEqual(self.check(collected_after=1000)["status"], "PASS")

    def test_loki_failure_empty_logs_or_missing_marker_is_refused(self):
        for status, lines in (("error", self.lines), ("success", []), ("success", ["unrelated synthetic event"])):
            self.log_status, self.lines = status, lines
            with self.subTest(status=status, lines=lines), self.assertRaises(verify.VerificationError):
                self.check(marker="fixture-marker")

    def test_wait_ready_retries_without_real_sleep_and_stops_at_deadline(self):
        with patch.object(self.client, "verify", side_effect=[verify.VerificationError("pending"), {"status": "PASS"}]) as check:
            with patch.object(verify.time, "monotonic", return_value=0), patch.object(verify.time, "sleep") as sleep:
                self.assertEqual(verify.wait_ready(self.client, marker="fixture", collected_after=10), {"status": "PASS"})
                self.assertEqual(check.call_count, 2)
                check.assert_called_with(marker="fixture", collected_after=10)
                sleep.assert_called_once()
        with patch.object(self.client, "verify", side_effect=verify.VerificationError("pending")):
            with patch.object(verify.time, "monotonic", side_effect=[0, 151]), patch.object(verify.time, "sleep") as sleep:
                with self.assertRaises(verify.VerificationError):
                    verify.wait_ready(self.client, timeout=150)
                sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
