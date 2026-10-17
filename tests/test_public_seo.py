import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout
from io import StringIO
import json

MODULE = Path(__file__).resolve().parents[1] / 'scripts/check-public-seo.py'
spec = importlib.util.spec_from_file_location('public_seo', MODULE)
seo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seo)


def sitemap(*urls):
    return '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + ''.join(
        '<url><loc>' + url + '</loc></url>' for url in urls
    ) + '</urlset>'


class PublicSeoTests(unittest.TestCase):
    def test_accepts_public_canonical_urls(self):
        self.assertEqual(seo.validate_sitemap(sitemap('https://soulcuts.com.ua/', 'https://soulcuts.com.ua/services/haircut'), 'https://soulcuts.com.ua'), 2)

    def test_rejects_private_aliases_and_tokens(self):
        for path in ['/booking', '/booking/repeat/token', '/review/secret', '/api/v1/public', '/services?token=secret', '/masters#private']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                seo.validate_sitemap(sitemap('https://soulcuts.com.ua' + path), 'https://soulcuts.com.ua')

    def test_rejects_noncanonical_origin_duplicates_and_empty(self):
        for urls in [[], ['https://www.soulcuts.com.ua/services'], ['https://other.example/services'], ['https://soulcuts.com.ua/', 'https://soulcuts.com.ua/']]:
            with self.subTest(urls=urls), self.assertRaises(ValueError):
                seo.validate_sitemap(sitemap(*urls), 'https://soulcuts.com.ua')

    def test_blog_stays_under_blog_prefix(self):
        self.assertEqual(seo.validate_sitemap(sitemap('https://soulcuts.com.ua/blog/story'), 'https://soulcuts.com.ua', blog=True), 1)
        with self.assertRaises(ValueError):
            seo.validate_sitemap(sitemap('https://soulcuts.com.ua/services'), 'https://soulcuts.com.ua', blog=True)

    def test_probe_reports_success_and_degraded_fallback(self):
        origin = 'https://soulcuts.com.ua'
        for freshness in ['fresh', 'stale']:
            def fake_request(url):
                if '?seo_probe=1' in url:
                    return 308, {'location': origin + '/services?seo_probe=1'}, b''
                if url.endswith('/robots.txt'):
                    return 200, {}, ('Sitemap: ' + origin + '/sitemap.xml\nSitemap: ' + origin + '/blog/sitemap.xml\n').encode()
                blog = url.endswith('/blog/sitemap.xml')
                return 200, {'content-type': 'application/xml', 'x-sitemap-freshness': 'fresh' if blog else freshness}, sitemap(origin + ('/blog/posts/story' if blog else '/services')).encode()
            output = StringIO()
            with self.subTest(freshness=freshness), patch.object(seo, 'request', fake_request), patch('sys.argv', ['probe']), redirect_stdout(output):
                if freshness == 'stale':
                    with self.assertRaises(SystemExit) as error:
                        seo.main()
                    self.assertEqual(error.exception.code, 2)
                else:
                    seo.main()
            result = json.loads(output.getvalue())
            self.assertEqual(result['success'], freshness == 'fresh')
            self.assertEqual(len(result['checks']), 5)

    def test_probe_rejects_redirect_that_loses_query(self):
        with patch.object(seo, 'request', return_value=(308, {'location': 'https://soulcuts.com.ua/services'}, b'')), patch('sys.argv', ['probe']):
            with self.assertRaisesRegex(ValueError, 'Canonical redirect failed'):
                seo.main()
