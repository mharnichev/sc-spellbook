"""Static Grafana contracts; runtime/API acceptance belongs to integration."""

import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
GRAFANA = ROOT / "monitoring/grafana"
SERVICES = (
    "backend", "booking-sms-reminders", "public-site", "admin-app",
    "shop", "blog", "caddy", "postgres",
)
METRICS = {
    "soulcuts_collector_last_success_unixtime", "soulcuts_collector_success",
    "soulcuts_service_running", "soulcuts_service_healthy",
    "soulcuts_container_cpu_percent", "soulcuts_container_memory_bytes",
    "soulcuts_host_memory_total_bytes", "soulcuts_host_memory_available_bytes",
    "soulcuts_host_disk_size_bytes", "soulcuts_host_disk_free_bytes",
    "soulcuts_host_cpu_busy_ratio",
}


def load(relative):
    # Provisioning uses the JSON subset of YAML: no optional YAML dependency.
    return json.loads((GRAFANA / relative).read_text())


class MonitoringDashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dashboard = load("dashboards/soulcuts-production.json")
        cls.panels = cls.dashboard["panels"]
        cls.sources = load("provisioning/datasources/soulcuts.yaml")
        cls.providers = load("provisioning/dashboards/soulcuts.yaml")

    def test_all_config_documents_parse_and_only_expected_files_exist(self):
        configs = sorted(p for p in GRAFANA.rglob("*") if p.suffix in {".json", ".yaml", ".yml"})
        self.assertEqual(len(configs), 3)
        for path in configs:
            with self.subTest(path=path):
                self.assertIsInstance(json.loads(path.read_text()), dict)

    def test_datasources_are_internal_proxy_readonly_and_have_stable_uids(self):
        self.assertEqual(self.sources["apiVersion"], 1)
        sources = self.sources["datasources"]
        self.assertEqual(len(sources), 2)
        by_uid = {source["uid"]: source for source in sources}
        expected = {
            "soulcuts-prometheus": ("prometheus", "http://prometheus:9090", True),
            "soulcuts-loki": ("loki", "http://loki:3100", False),
        }
        self.assertEqual(set(by_uid), set(expected))
        for uid, (kind, url, default) in expected.items():
            source = by_uid[uid]
            self.assertEqual((source["type"], source["url"], source["isDefault"]), (kind, url, default))
            self.assertEqual(source["access"], "proxy")
            self.assertIs(source["editable"], False)
            self.assertFalse(set(source) & {"basicAuth", "basicAuthUser", "user", "password", "secureJsonData"})
        self.assertEqual(by_uid["soulcuts-loki"]["jsonData"]["maxLines"], 200)

    def test_readonly_file_provider_and_dashboard_identity(self):
        self.assertEqual(self.providers["apiVersion"], 1)
        self.assertEqual(len(self.providers["providers"]), 1)
        provider = self.providers["providers"][0]
        self.assertEqual(provider["folder"], "Soulcuts")
        self.assertEqual(provider["type"], "file")
        self.assertIs(provider["allowUiUpdates"], False)
        self.assertIs(provider["disableDeletion"], True)
        self.assertEqual(provider["options"]["path"], "/var/lib/grafana/dashboards")
        self.assertEqual(self.dashboard["uid"], "soulcuts-production")
        self.assertEqual(self.dashboard["schemaVersion"], 39)
        self.assertIs(self.dashboard["editable"], False)
        self.assertEqual(self.dashboard["timezone"], "Europe/Kyiv")
        self.assertEqual(self.dashboard["refresh"], "30s")
        self.assertEqual(self.dashboard["time"], {"from": "now-1h", "to": "now"})

    def test_service_variable_is_fixed_multiselect_with_bounded_all_regex(self):
        variables = self.dashboard["templating"]["list"]
        self.assertEqual(len(variables), 1)
        service = variables[0]
        self.assertEqual((service["name"], service["type"]), ("service", "custom"))
        self.assertEqual(tuple(service["query"].split(",")), SERVICES)
        self.assertIs(service["multi"], True)
        self.assertIs(service["includeAll"], True)
        self.assertIs(service["skipUrlSync"], True)
        self.assertEqual(service["allValue"], "|".join(SERVICES))
        self.assertEqual([o["value"] for o in service["options"]], ["$__all", *SERVICES])
        self.assertEqual(service["current"]["value"], ["$__all"])
        for name in SERVICES:
            self.assertRegex(name, r"^[a-z][a-z-]+$")
            self.assertIsNotNone(re.fullmatch(service["allValue"], name))
        for rejected in ("", "other", "pilot", "backend-extra", ".*", 'backend"} |~ ".*'):
            self.assertIsNone(re.fullmatch(service["allValue"], rejected))

    def test_metric_contract_and_queries_are_closed_and_service_scoped(self):
        queries = [t["expr"] for p in self.panels if p["type"] != "logs" for t in p["targets"]]
        self.assertEqual(len(queries), 10)
        used = set(re.findall(r"\bsoulcuts_[a-z_]+\b", " ".join(queries)))
        self.assertEqual(used, METRICS)
        service_selector = '{service=~"${service:regex}"}'
        allowed = {
            "soulcuts_host_cpu_busy_ratio",
            "1 - soulcuts_host_memory_available_bytes / soulcuts_host_memory_total_bytes",
            "1 - soulcuts_host_disk_free_bytes / soulcuts_host_disk_size_bytes",
            "time() - soulcuts_collector_last_success_unixtime",
            "soulcuts_collector_success", "up",
            *{metric + service_selector for metric in (
                "soulcuts_service_running", "soulcuts_service_healthy",
                "soulcuts_container_cpu_percent", "soulcuts_container_memory_bytes",
            )},
        }
        self.assertEqual(set(queries), allowed)

    def test_panels_are_compact_described_nonoverlapping_and_queries_bounded(self):
        ids = [p["id"] for p in self.panels]
        self.assertEqual(len(ids), len(set(ids)))
        occupied = set()
        for panel in self.panels:
            with self.subTest(panel=panel["title"]):
                self.assertTrue(panel["description"])
                expected = ("loki", "soulcuts-loki") if panel["type"] == "logs" else ("prometheus", "soulcuts-prometheus")
                self.assertEqual((panel["datasource"]["type"], panel["datasource"]["uid"]), expected)
                pos = panel["gridPos"]
                self.assertGreater(pos["h"], 0)
                self.assertGreater(pos["w"], 0)
                self.assertGreaterEqual(pos["x"], 0)
                self.assertGreaterEqual(pos["y"], 0)
                self.assertLessEqual(pos["x"] + pos["w"], 24)
                cells = {(x, y) for x in range(pos["x"], pos["x"] + pos["w"])
                         for y in range(pos["y"], pos["y"] + pos["h"])}
                self.assertFalse(occupied & cells)
                occupied |= cells
                if panel["type"] == "stat":
                    self.assertTrue(all(t["instant"] for t in panel["targets"]))
                    self.assertIn(panel["fieldConfig"]["defaults"]["noValue"], ("No data", "Unknown"))
                elif panel["type"] == "timeseries":
                    self.assertLessEqual(panel["maxDataPoints"], 600)
                    self.assertEqual(panel["interval"], "30s")
        by_title = {p["title"]: p for p in self.panels}
        self.assertEqual(by_title["Host CPU busy"]["fieldConfig"]["defaults"]["unit"], "percentunit")
        self.assertEqual(by_title["Container CPU"]["fieldConfig"]["defaults"]["unit"], "percent")
        self.assertNotIn("max", by_title["Container CPU"]["fieldConfig"]["defaults"])
        self.assertIn("one fully utilized logical CPU", by_title["Container CPU"]["description"])

    def test_logs_are_scoped_sanitized_json_and_limited(self):
        logs = [p for p in self.panels if p["type"] == "logs"]
        self.assertEqual(len(logs), 1)
        panel = logs[0]
        self.assertEqual(panel["timeFrom"], "1h")
        self.assertEqual(len(panel["targets"]), 1)
        target = panel["targets"][0]
        self.assertEqual(target["expr"], '{job="soulcuts",service=~"${service:regex}"} | json | __error__=""')
        self.assertEqual(target["maxLines"], 200)
        self.assertEqual(target["direction"], "backward")
        for term in ("redacted", "200", "timestamp", "service", "level", "event", "message", "truncation", "not complete"):
            self.assertIn(term, panel["description"])

    def test_no_external_endpoints_links_or_literal_credentials(self):
        allowed_urls = {"http://prometheus:9090", "http://loki:3100"}
        for path in GRAFANA.rglob("*"):
            if not path.is_file():
                continue
            content = path.read_text()
            urls = set(re.findall(r'https?://[^\s"<>]+', content))
            self.assertLessEqual(urls, allowed_urls)
            self.assertNotRegex(content, r"(?i)(?:password|api[_-]?key|authorization|bearer|client[_-]?secret)\s*[\"']?\s*[:=]")
            self.assertNotRegex(content, r"(?:AKIA[0-9A-Z]{16}|-----BEGIN .*PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{20,})")
        self.assertEqual(self.dashboard["links"], [])
        self.assertEqual(self.dashboard["annotations"]["list"], [])
        for panel in self.panels:
            self.assertFalse(panel.get("links"))
            self.assertFalse(panel.get("fieldConfig", {}).get("defaults", {}).get("links"))


if __name__ == "__main__":
    unittest.main()
