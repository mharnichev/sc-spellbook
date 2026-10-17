from pathlib import Path
import unittest


class SupportIsolationTests(unittest.TestCase):
    def test_public_image_includes_cross_app_static_assets(self):
        dockerfile = (Path(__file__).parents[1] / 'examples/frontend/Dockerfile.public-site').read_text()
        self.assertIn('COPY apps/blog/assets ./apps/blog/assets', dockerfile)

    def test_support_uses_only_exact_www_exception(self):
        caddy = (Path(__file__).parents[1] / 'caddy/Caddyfile').read_text()
        www = caddy.split('www.soulcuts.com.ua {', 1)[1].split('\nsoulcuts.com.ua {', 1)[0]
        self.assertIn('handle /support-widget {', www)
        self.assertIn('header_down -X-Frame-Options', www)
        self.assertIn('redir https://soulcuts.com.ua{uri} 308', www)
        self.assertNotIn('handle /support-widget*', www)
        apex = caddy.split('\nsoulcuts.com.ua {', 1)[1].split('\nadmin.soulcuts.com.ua {', 1)[0]
        self.assertIn('respond /support-widget 404', apex)


if __name__ == '__main__':
    unittest.main()
