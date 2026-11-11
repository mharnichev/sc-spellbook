import json
import os
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MonitoringStackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = dict(os.environ, MONITORING_ROOT='/tmp/monitoring-config-test', MONITORING_UID='1000', MONITORING_GID='1000')
        for line in (ROOT / 'monitoring/images.env').read_text().splitlines():
            if line and not line.startswith('#'):
                key, value = line.split('=', 1)
                env[key] = value
        cls.config = json.loads(subprocess.check_output([
            'docker', 'compose', '--env-file', 'monitoring/images.env', '-f', 'monitoring/compose.yml',
            'config', '--format', 'json'], cwd=ROOT, env=env, text=True))

    def test_only_grafana_publishes_a_loopback_port(self):
        published = []
        for service, cfg in self.config['services'].items():
            for port in cfg.get('ports', []):
                published.append((service, port['host_ip'], str(port['published']), port['target']))
        self.assertEqual(published, [('grafana', '127.0.0.1', '3300', 3000)])

    def test_project_network_is_private_and_has_no_application_dependencies(self):
        self.assertEqual(self.config['name'], 'soulcuts-monitoring')
        self.assertEqual(set(self.config['services']), {'grafana', 'prometheus', 'loki', 'alloy', 'node-exporter'})
        self.assertTrue(self.config['networks']['monitoring']['internal'])
        for cfg in self.config['services'].values():
            self.assertEqual(set(cfg['networks']), {'monitoring', 'ui'} if cfg is self.config['services']['grafana'] else {'monitoring'})
            self.assertFalse(cfg.get('depends_on'))

    def test_images_are_immutable_and_resources_are_bounded(self):
        for cfg in self.config['services'].values():
            self.assertRegex(cfg['image'], r'@sha256:[0-9a-f]{64}$')
            self.assertGreater(int(cfg['mem_limit']), 0)
            self.assertGreater(float(cfg['cpus']), 0)
            self.assertEqual(cfg['pids_limit'], 128)
            self.assertEqual(cfg['logging']['options']['max-file'], '2')

    def test_no_privileged_host_or_docker_socket_access(self):
        for cfg in self.config['services'].values():
            self.assertTrue(cfg['read_only'])
            self.assertEqual(cfg['cap_drop'], ['ALL'])
            self.assertIn('no-new-privileges:true', cfg['security_opt'])
            self.assertFalse(cfg.get('privileged'))
            self.assertNotIn(cfg.get('network_mode'), {'host', 'service:backend'})
            for mount in cfg['volumes']:
                source = mount['source']
                self.assertNotIn('docker.sock', source)
                self.assertNotIn(source, {'/', '/proc', '/sys', '/var/lib/docker', '/opt/soulcuts/env'})
                if mount['type'] == 'bind' and '/data/alloy' not in source:
                    self.assertTrue(mount['read_only'])

    def test_grafana_uses_file_secrets_and_rejects_anonymous_access(self):
        env = self.config['services']['grafana']['environment']
        self.assertEqual(env['GF_SECURITY_ADMIN_PASSWORD__FILE'], '/run/secrets/admin_password')
        self.assertEqual(env['GF_SECURITY_SECRET_KEY__FILE'], '/run/secrets/secret_key')
        self.assertNotIn('GF_SECURITY_ADMIN_PASSWORD', env)
        self.assertEqual(env['GF_AUTH_ANONYMOUS_ENABLED'], 'false')
        self.assertEqual(env['GF_USERS_ALLOW_SIGN_UP'], 'false')
        self.assertEqual(env['GF_ANALYTICS_REPORTING_ENABLED'], 'false')
        self.assertEqual(env['GF_PATHS_PLUGINS'], '/usr/share/grafana/data/plugins-bundled')
        self.assertEqual(env['GF_PLUGINS_PREINSTALL_DISABLED'], 'true')
        self.assertEqual(env['GF_PLUGINS_PREINSTALL_AUTO_UPDATE'], 'false')

    def test_retention_and_scrape_contract(self):
        command = self.config['services']['prometheus']['command']
        self.assertIn('--storage.tsdb.retention.time=15d', command)
        self.assertIn('--storage.tsdb.retention.size=512MB', command)
        self.assertIn('retention_period: 72h', (ROOT / 'monitoring/loki.yml').read_text())
        self.assertEqual((ROOT / 'monitoring/prometheus.yml').read_text().count('job_name:'), 4)
        alloy = (ROOT / 'monitoring/config.alloy').read_text()
        self.assertNotIn('loki.source.docker', alloy)
        self.assertNotIn('/var/lib/docker', alloy)
        self.assertEqual(len(re.findall(r'"__path__" = "/spool/logs/[^\"]+\.log"', alloy)), 8)


if __name__ == '__main__':
    unittest.main()
