"""Opt-in cached-image tests: no published ports, DNS or external network."""
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.environ.get('RUN_CADDY_INTEGRATION') == '1', 'requires explicit local Docker opt-in')
class CaddyPilotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.name = 'shop-pilot-caddy-' + uuid.uuid4().hex[:12]
        source = (ROOT / 'caddy/Caddyfile').read_text()
        for host in ('www.soulcuts.com.ua', 'soulcuts.com.ua', 'admin.soulcuts.com.ua', 'api.soulcuts.com.ua'):
            source = source.replace('\n' + host + ' {', '\nhttp://' + host + ':18080 {')
        for index, upstream in enumerate(('public-site:3000', 'blog:3000', 'admin-app:3000', 'shop:3000', 'api-ingress-backend:8000')):
            port = 18081 + index
            source = source.replace(upstream, f'127.0.0.1:{port}')
            label = upstream.split(':')[0]
            missing = '\n respond /media/products/missing.webp "missing" 404' if label == 'api-ingress-backend' else ''
            source += f'\nhttp://:{port} {{{missing}\n header X-Fixture-Upstream "{label}"\n respond "{label}|{{http.request.uri}}|{{http.request.header.Authorization}}|{{http.request.header.X-Forwarded-For}}"\n}}\n'
        path = Path(cls.temp.name) / 'Caddyfile'
        path.write_text(source)
        subprocess.run(['docker', 'run', '-d', '--rm', '--pull=never', '--network', 'none', '--name', cls.name,
                        '-e', 'ACME_EMAIL=admin@soulcuts.com.ua', '-v', f'{path}:/etc/caddy/Caddyfile:ro',
                        os.environ.get('CADDY_TEST_IMAGE', 'caddy:2.8-alpine'), 'caddy', 'run', '--config', '/etc/caddy/Caddyfile', '--adapter', 'caddyfile'],
                       check=True, capture_output=True)
        cls.addClassCleanup(cls.cleanup)
        for _ in range(30):
            result = cls.request('/api/v1/public/customers/me', check=False)
            if result.returncode == 0:
                return
            time.sleep(0.1)
        raise AssertionError(subprocess.check_output(['docker', 'logs', cls.name], stderr=subprocess.STDOUT).decode())

    @classmethod
    def cleanup(cls):
        subprocess.run(['docker', 'stop', '-t', '1', cls.name], check=True, capture_output=True)
        cls.temp.cleanup()

    @classmethod
    def request(cls, path, host='soulcuts.com.ua', headers=(), check=True, body=None):
        command = ['docker', 'exec', cls.name, 'wget', '-S', '-q', '-O', '-', '-T', '2',
                   '--header', 'Host: ' + host]
        for header in headers:
            command.extend(['--header', header])
        if body is not None:
            command.extend(['--post-data', body])
        return subprocess.run(command + ['http://127.0.0.1:18080' + path], capture_output=True, text=True, check=check)

    def test_shop_and_blog_prefixes_not_stripped(self):
        for path, upstream in [('/shop/', 'shop'), ('/shop/_nuxt/app.js', 'shop'),
                               ('/blog/story?x=1', 'blog'), ('/services', 'public-site')]:
            with self.subTest(path=path):
                result = self.request(path)
                self.assertTrue(result.stdout.startswith(f'{upstream}|{path}|'), result.stdout)
                if path.startswith('/shop/'):
                    self.assertIn('X-Robots-Tag: noindex, nofollow, noarchive', result.stderr)

    def test_bff_sensitive_paths_still_reach_public_site(self):
        for path in ('/api/v1/public/bookings', '/api/v1/public/bookings/quote',
                     '/api/v1/public/customer-activity/session', '/api/v1/public/reviews/request',
                     '/api/v1/public/repeat-booking/context', '/api/v1/public/campaign-offers/test',
                     '/api/v1/backoffice/auth/refresh'):
            with self.subTest(path=path):
                self.assertTrue(self.request(path).stdout.startswith('public-site|'))

    def test_shop_admin_and_api_host_keep_auth_and_replace_spoofed_source(self):
        for host, path in [('soulcuts.com.ua', '/api/v1/public/customers/me'),
                           ('admin.soulcuts.com.ua', '/api/v1/backoffice/auth/refresh'),
                           ('api.soulcuts.com.ua', '/api/v1/public/orders')]:
            with self.subTest(host=host):
                result = self.request(path, host, ['Authorization: Bearer synthetic',
                                      'CF-Connecting-IP: 198.51.100.17', 'X-Forwarded-For: 198.51.100.18'])
                self.assertEqual(result.stdout, f'api-ingress-backend|{path}|Bearer synthetic|127.0.0.1')
                self.assertIn('Cache-Control: no-store, private', result.stderr)

    def test_shop_redirect_and_www_support_exception(self):
        result = self.request('/shop?x=1', check=False)
        self.assertIn('308', result.stderr)
        self.assertIn('Location: /shop/', result.stderr)
        support = self.request('/support-widget', 'www.soulcuts.com.ua')
        self.assertTrue(support.stdout.startswith('public-site|'))
        self.assertNotIn('X-Frame-Options:', support.stderr)

    def test_promo_quote_preserves_shop_auth_without_broadening_public_routes(self):
        path = '/api/v1/public/shop-promotions/quote'
        result = self.request(path, headers=['Authorization: Bearer synthetic', 'Content-Type: application/json'], body='{"items":[]}')
        self.assertEqual(result.stdout, f'api-ingress-backend|{path}|Bearer synthetic|127.0.0.1')
        self.assertIn('Cache-Control: no-store, private', result.stderr)
        for neighbor in ('/api/v1/public/shop-promotions', '/api/v1/public/shop-promotions/quote/extra',
                         '/api/v1/public/shop-promotions/private', '/api/v1/backoffice/shop-promotions'):
            self.assertTrue(self.request(neighbor).stdout.startswith('public-site|'))

    def test_admin_product_media_reaches_existing_backend_without_rewriting(self):
        for path in ('/media/products/processed.webp', '/media/products/nested/photo.webp?version=1'):
            with self.subTest(path=path):
                result = self.request(path, 'admin.soulcuts.com.ua')
                self.assertEqual(result.stdout, f'api-ingress-backend|{path}||127.0.0.1')
                self.assertIn('Cache-Control: no-store, private', result.stderr)
                self.assertIn('X-Content-Type-Options: nosniff', result.stderr)
                self.assertIn("Content-Security-Policy: sandbox; default-src 'none'; frame-ancestors 'none'", result.stderr)

    def test_admin_missing_product_media_preserves_backend_404(self):
        result = self.request('/media/products/missing.webp', 'admin.soulcuts.com.ua', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('404', result.stderr)
        self.assertNotIn('admin-app|', result.stdout)

    def test_admin_product_media_head_and_mutation_boundaries(self):
        for method, upstream in [('HEAD', 'api-ingress-backend'), ('POST', 'admin-app'),
                                 ('PUT', 'admin-app'), ('DELETE', 'admin-app')]:
            with self.subTest(method=method):
                wire = (f'{method} /media/products/photo.webp HTTP/1.1\r\n'
                        'Host: admin.soulcuts.com.ua\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
                # Keep the request socket open until the proxy can finish its response.
                result = subprocess.run(['docker', 'exec', '-i', self.name, 'sh', '-c',
                                         '{ cat; sleep 1; } | nc -w 2 127.0.0.1 18080'], input=wire, capture_output=True,
                                        text=True, check=True, timeout=5)
                self.assertIn(f'X-Fixture-Upstream: {upstream}', result.stdout)
                if method == 'HEAD':
                    self.assertNotIn('api-ingress-backend|', result.stdout)

    def test_admin_media_fix_does_not_route_other_paths_to_backend(self):
        for path in ('/media/barbers/passports/example.webp', '/media/products-archive/photo.webp',
                     '/products', '/_nuxt/app.js'):
            with self.subTest(path=path):
                self.assertTrue(self.request(path, 'admin.soulcuts.com.ua').stdout.startswith('admin-app|'))


if __name__ == '__main__':
    unittest.main()
