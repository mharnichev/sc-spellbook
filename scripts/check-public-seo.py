#!/usr/bin/env python3
"""Read-only SEO release/monitoring probe. Exit nonzero on a broken public surface."""
import argparse
import json
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

PRIVATE_PREFIXES = ('/booking', '/review', '/account', '/cabinet', '/admin', '/api')


def validate_sitemap(body, origin, *, blog=False):
    root = ET.fromstring(body)
    namespace = '{http://www.sitemaps.org/schemas/sitemap/0.9}'
    if root.tag != namespace + 'urlset':
        raise ValueError('Expected a sitemap urlset')
    locations = [node.text or '' for node in root.findall(f'{namespace}url/{namespace}loc')]
    if not locations or len(locations) != len(set(locations)):
        raise ValueError('Sitemap must contain unique public URLs')
    expected_origin = urlsplit(origin)
    for location in locations:
        url = urlsplit(location)
        if (url.scheme, url.netloc) != (expected_origin.scheme, expected_origin.netloc):
            raise ValueError('Sitemap contains a noncanonical origin')
        if url.query or url.fragment or url.username or url.password:
            raise ValueError('Sitemap contains query parameters or credentials')
        if any(url.path == prefix or url.path.startswith(prefix + '/') for prefix in PRIVATE_PREFIXES):
            raise ValueError('Sitemap contains a private route')
        if blog and not url.path.startswith('/blog/'):
            raise ValueError('Blog sitemap contains a route outside the blog')
    return len(locations)


def request(url):
    # curl uses the host trust store and does not execute scripts or follow redirects.
    with tempfile.TemporaryDirectory(prefix='soulcuts-seo-') as directory:
        body_path = Path(directory) / 'body'
        headers_path = Path(directory) / 'headers'
        result = subprocess.run([
            'curl', '--silent', '--show-error', '--max-time', '20',
            '--proto', '=https,http', '--dump-header', str(headers_path),
            '--output', str(body_path), '--write-out', '%{http_code}', url,
        ], check=True, capture_output=True, text=True)
        headers = {}
        for line in headers_path.read_text().splitlines():
            if ':' in line:
                name, value = line.split(':', 1)
                headers[name.lower()] = value.strip()
        return int(result.stdout), headers, body_path.read_bytes()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin', default='https://soulcuts.com.ua')
    args = parser.parse_args()
    url = urlsplit(args.origin)
    if url.scheme != 'https' or not url.hostname or url.path not in ('', '/') or url.query or url.fragment or url.username or url.password or url.port:
        parser.error('--origin must be a public HTTPS origin without path, credentials or port')
    origin = f'https://{url.hostname}'
    host = url.hostname
    if host.startswith('www.'):
        parser.error('--origin must be the canonical host without www')
    checks = []
    for source in [f'https://www.{host}', f'http://{host}']:
        target = origin + '/services?seo_probe=1'
        status, headers, _ = request(source + '/services?seo_probe=1')
        if status not in (301, 308) or headers.get('location') != target:
            raise ValueError(f'Canonical redirect failed: {source} (HTTP {status})')
        checks.append({'check': 'canonical_redirect', 'origin': source, 'status': status})
    status, _, robots = request(origin + '/robots.txt')
    expected_maps = [origin + '/sitemap.xml', origin + '/blog/sitemap.xml']
    lines = robots.decode('utf-8').splitlines()
    if status != 200 or any('Sitemap: ' + value not in lines for value in expected_maps):
        raise ValueError('robots.txt does not advertise both sitemaps')
    checks.append({'check': 'robots', 'status': status})
    for index, sitemap in enumerate(expected_maps):
        status, headers, body = request(sitemap)
        if status != 200 or 'xml' not in headers.get('content-type', ''):
            raise ValueError(f'Sitemap endpoint failed (HTTP {status})')
        count = validate_sitemap(body, origin, blog=index == 1)
        checks.append({'check': 'sitemap', 'url': sitemap, 'status': status, 'urls': count,
                       'cache': headers.get('x-sitemap-freshness', 'not-reported')})
    degraded = any(check.get('cache') == 'stale' for check in checks)
    print(json.dumps({'success': not degraded, 'degraded': degraded, 'checks': checks}, ensure_ascii=False, indent=2))
    if degraded:
        raise SystemExit(2)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, ET.ParseError, OSError, subprocess.SubprocessError) as error:
        print(json.dumps({'success': False, 'error': str(error)}, ensure_ascii=False))
        raise SystemExit(1)
