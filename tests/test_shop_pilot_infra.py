import importlib.util
import json
import os
import signal
import time
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ingress', ROOT / 'scripts/check-ingress-network.py')
ingress = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ingress)
owner_spec = importlib.util.spec_from_file_location('owner', ROOT / 'scripts/verify-background-owner.py')
owner = importlib.util.module_from_spec(owner_spec)
owner_spec.loader.exec_module(owner)


class OwnerTests(unittest.TestCase):
    def test_latest_state_must_be_running_owner(self):
        running = 'background_workers state=running role=owner code=None'
        owner.require_owner([running])
        for lines in ([], ['private noise'], [running, 'background_workers state=failed role=owner code=worker_failed'],
                      ['background_workers state=standby role=follower code=owner_busy']):
            with self.subTest(lines=lines), self.assertRaises(ValueError):
                owner.require_owner(lines)


class NetworkTests(unittest.TestCase):
    def test_supplied_host_routes_do_not_overlap(self):
        ingress.validate([{'dst': 'default'}, {'dst': '172.17.0.0/16'}, {'dst': '172.18.0.0/16'},
                          {'dst': '172.31.1.1/32'}], [], 'soulcuts_api_ingress')

    def test_routes_and_other_docker_networks_cannot_overlap(self):
        for route in ('172.30.0.0/16', '172.30.41.0/29', '172.30.41.2/32'):
            with self.subTest(route=route), self.assertRaises(ValueError):
                ingress.validate([{'dst': route, 'dev': 'vpn0'}], [], 'soulcuts_api_ingress')
        with self.assertRaises(ValueError):
            ingress.validate([], [{'Name': 'other', 'IPAM': {'Config': [{'Subnet': '172.30.41.0/24'}]}}], 'soulcuts_api_ingress')

    def test_existing_internal_bridge_allows_own_connected_and_local_routes(self):
        network = {'Name': 'soulcuts_api_ingress', 'Id': '123456789abc000', 'Internal': True,
                   'IPAM': {'Config': [{'Subnet': '172.30.41.0/29'}]}}
        ingress.validate([{'dst': '172.30.41.0/29', 'dev': 'br-123456789abc'},
                          {'dst': '172.30.41.1/32', 'dev': 'br-123456789abc'}], [network], network['Name'])
        network['Internal'] = False
        with self.assertRaises(ValueError):
            ingress.validate([], [network], network['Name'])


class StartupTests(unittest.TestCase):
    def run_start(self, **overrides):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for command in ('python', 'uvicorn'):
                target = root / command
                target.write_text('#!/bin/sh\nprintf "%s\\n" "$0 $*" >> "$CALLS"\n'
                                  'case "$*" in *migration_readiness*) exit "${SCHEMA_EXIT:-0}";; esac\n')
                target.chmod(0o755)
            env = {**os.environ, 'PATH': f'{root}:{os.environ["PATH"]}', 'CALLS': str(root / 'calls'), **overrides}
            result = subprocess.run(['sh', str(ROOT / 'examples/backend/start.sh')], env=env, capture_output=True, text=True)
            calls = (root / 'calls').read_text() if (root / 'calls').exists() else ''
            return result, calls

    def test_schema_failure_never_starts_uvicorn(self):
        result, calls = self.run_start(SCHEMA_EXIT='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('uvicorn', calls)

    def test_api_rejects_migration_and_multiple_workers(self):
        for override in ({'MIGRATIONS_MODE': 'apply'}, {'API_WORKERS': '2'}):
            result, calls = self.run_start(**override)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(calls, '')

    def test_explicit_forwarding_and_one_worker(self):
        result, calls = self.run_start()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--workers 1 --proxy-headers --forwarded-allow-ips 172.30.41.2', calls)
        self.assertNotIn('alembic', calls)


class ComposeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = {**os.environ, 'SHOP_IMAGE': 'local/shop:validation-only'}
        for service in ('caddy', 'postgres', 'backend', 'public-site', 'blog', 'admin-app', 'shop'):
            env[service.upper().replace('-', '_') + '_ENV_FILE'] = str(ROOT / 'env' / f'{service}.env.example')
        cls.env = env
        cls.command = ['docker', 'compose', '--env-file', str(ROOT / 'versions/production.env'),
                       '-f', str(ROOT / 'docker-compose.prod.yml'), '--profile', 'release', 'config', '--format', 'json']
        result = subprocess.run(cls.command,
                                env=env, capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stderr)
        cls.config = json.loads(result.stdout)

    def test_digest_pins_are_opaque_image_references(self):
        pins = {key: 'ghcr.io/example/' + name + '@sha256:' + digit * 64
                for key, name, digit in [('BACKEND_IMAGE', 'api', '1'), ('SHOP_IMAGE', 'shop', '2'),
                                         ('ADMIN_APP_IMAGE', 'admin', '3')]}
        pins.update(
            CADDY_IMAGE='caddy@sha256:af32e97399febea808609119bb21544d0265c58a02836576e32a2d082c262c17',
            POSTGRES_IMAGE='postgres@sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea')
        result = subprocess.run(self.command, env={**self.env, **pins}, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        services = json.loads(result.stdout)['services']
        for name, key in [('backend', 'BACKEND_IMAGE'), ('migrate', 'BACKEND_IMAGE'),
                          ('booking-sms-reminders', 'BACKEND_IMAGE'), ('shop', 'SHOP_IMAGE'),
                          ('admin-app', 'ADMIN_APP_IMAGE'), ('caddy', 'CADDY_IMAGE'),
                          ('postgres', 'POSTGRES_IMAGE')]:
            self.assertEqual(services[name]['image'], pins[key])

    def test_local_engine_defaults_preserve_existing_tags(self):
        env = {key: value for key, value in self.env.items() if key not in {'CADDY_IMAGE', 'POSTGRES_IMAGE'}}
        # Use an empty interpolation file so future production pins do not alter
        # this local-default contract. App image references come from the env.
        for key, name in [('PUBLIC_SITE_IMAGE', 'public'), ('BLOG_IMAGE', 'blog'),
                          ('ADMIN_APP_IMAGE', 'admin'), ('BACKEND_IMAGE', 'api')]:
            env[key] = f'local/{name}:validation-only'
        with tempfile.NamedTemporaryFile() as empty:
            command = list(self.command)
            command[command.index('--env-file') + 1] = empty.name
            result = subprocess.run(command, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        services = json.loads(result.stdout)['services']
        self.assertEqual(services['caddy']['image'], 'caddy:2.8-alpine')
        self.assertEqual(services['postgres']['image'], 'postgres:16-alpine')

    def test_owner_and_release_service_are_separate(self):
        api, migration = (self.config['services'][name] for name in ('backend', 'migrate'))
        self.assertEqual(api['environment']['API_WORKERS'], '1')
        self.assertEqual(api['environment']['MIGRATIONS_MODE'], 'check')
        self.assertEqual(api['command'], ['sh', '/app/scripts/start.sh'])
        self.assertEqual(api['stop_grace_period'], '1m30s')
        self.assertEqual(self.config['services']['booking-sms-reminders']['stop_grace_period'], '1m30s')
        self.assertEqual(migration['command'], ['alembic', 'upgrade', 'head'])
        self.assertEqual(migration['entrypoint'], [])
        self.assertEqual(migration['restart'], 'no')
        self.assertEqual(set(migration['networks']), {'default'})
        self.assertEqual(migration['profiles'], ['release'])
        self.assertNotIn('volumes', migration)

    def test_all_backend_processes_have_identical_explicit_https_cors(self):
        expected = 'https://soulcuts.com.ua,https://www.soulcuts.com.ua,https://admin.soulcuts.com.ua'
        for service in ('backend', 'migrate', 'booking-sms-reminders'):
            self.assertEqual(self.config['services'][service]['environment']['CORS_ORIGINS'], expected, service)

    def test_static_exact_trust_and_no_backend_published_port(self):
        services = self.config['services']
        self.assertEqual(services['backend']['environment']['TRUSTED_PROXY_IPS'], '172.30.41.2')
        for name, ip in [('caddy', '172.30.41.2'), ('backend', '172.30.41.3')]:
            self.assertEqual(services[name]['networks']['api_ingress']['ipv4_address'], ip)
        self.assertNotIn('ports', services['backend'])
        self.assertTrue(self.config['networks']['api_ingress']['internal'])
        self.assertNotIn('caddy', services['backend']['depends_on'])

    def test_reminder_term_drains_current_child_without_next_iteration(self):
        # `compose config` re-escapes dollars for round-trip serialization;
        # the container command receives a single dollar after Compose expansion.
        command = [part.replace('$$', '$') for part in self.config['services']['booking-sms-reminders']['command']]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            child = root / 'python'
            child.write_text('#!/bin/sh\nprintf started >> "$EVENTS"\nsleep 0.3\nprintf completed >> "$EVENTS"\n')
            child.chmod(0o755)
            env = {**os.environ, 'PATH': f'{root}:{os.environ["PATH"]}', 'EVENTS': str(root / 'events')}
            process = subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                for _ in range(100):
                    if (root / 'events').exists():
                        break
                    time.sleep(0.01)
                self.assertTrue((root / 'events').exists())
                process.send_signal(signal.SIGTERM)
                time.sleep(0.05)
                self.assertIsNone(process.poll(), 'Reminder shell exited before its in-flight child drained')
                stdout, stderr = process.communicate(timeout=3)
                self.assertEqual(process.returncode, 0, stderr)
                self.assertEqual((root / 'events').read_text(), 'startedcompleted')
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate()

    def test_shop_and_all_provider_switches_fail_closed(self):
        self.assertEqual(self.config['services']['admin-app']['environment']['NUXT_PUBLIC_API_BASE'], '/api/v1')
        api = self.config['services']['backend']['environment']
        keys = [key for key in api if key.startswith('SHOP_') or key.endswith('_MOCK_ENABLED')]
        for key in keys + ['PROVIDER_SANDBOX_ENABLED', 'SANDBOX_PROVIDER_NETWORK_ENABLED',
                           'NP_MOCK_SHIPMENTS_ENABLED', 'LOCAL_SALES_SIMULATION_ENABLED', 'NP_TRACKING_ENABLED']:
            self.assertEqual(api[key], 'false', key)
        self.assertEqual(api['BACKGROUND_WORKERS_ENABLED'], 'true')
        self.assertEqual(api['CAMPAIGN_RUN_SCHEDULER_ENABLED'], 'true')
        self.assertEqual(api['SMS_QUEUE_WORKER_ENABLED'], 'true')
        shop = self.config['services']['shop']['environment']
        self.assertEqual(shop['NUXT_PUBLIC_API_BASE'], '/api/v1')
        self.assertEqual(shop['NUXT_API_BASE'], 'http://backend:8000/api/v1')
        self.assertEqual(shop['NUXT_APP_BASE_URL'], '/shop/')
        self.assertEqual(shop['NUXT_PUBLIC_DOBRODESK_ENABLED'], 'false')


if __name__ == '__main__':
    unittest.main()
