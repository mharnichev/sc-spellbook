"""Authenticated local-only monitoring acceptance. Never print credentials/logs."""
import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request


class VerificationError(Exception):
    pass


class Grafana:
    def __init__(self, url, password):
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != 'http' or parsed.hostname not in {'localhost', '127.0.0.1'}:
            raise VerificationError('Grafana acceptance must use loopback')
        self.url = url.rstrip('/')
        self.authorization = 'Basic ' + base64.b64encode(('admin:' + password).encode()).decode()

    def get(self, path, authenticated=True):
        headers = {'Authorization': self.authorization} if authenticated else {}
        request = urllib.request.Request(self.url + path, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return json.load(response)
        except Exception:
            raise VerificationError('Monitoring API check failed') from None

    def query(self, expression):
        payload = self.get('/api/datasources/proxy/uid/soulcuts-prometheus/api/v1/query?' +
                           urllib.parse.urlencode({'query': expression}))
        if payload.get('status') != 'success':
            raise VerificationError('Prometheus query failed')
        return payload['data']['result']

    def scalar(self, expression):
        result = self.query(expression)
        if len(result) != 1:
            raise VerificationError('Monitoring metric missing')
        return float(result[0]['value'][1])

    def verify(self, marker=None, collected_after=None):
        health = self.get('/api/health', authenticated=False)
        if health.get('database') != 'ok':
            raise VerificationError('Grafana database unhealthy')
        # Authentication is mandatory even on the SSH-only listener.
        try:
            self.get('/api/search', authenticated=False)
        except VerificationError:
            pass
        else:
            raise VerificationError('Unauthenticated dashboard access is enabled')
        sources = self.get('/api/datasources')
        if {source['uid'] for source in sources} != {'soulcuts-prometheus', 'soulcuts-loki'}:
            raise VerificationError('Unexpected datasource set')
        for uid in ['soulcuts-prometheus', 'soulcuts-loki']:
            if self.get('/api/datasources/uid/' + uid + '/health').get('status') != 'OK':
                raise VerificationError('Datasource not ready')
        dashboard = self.get('/api/dashboards/uid/soulcuts-production')['dashboard']
        if dashboard['uid'] != 'soulcuts-production' or len(dashboard.get('panels', [])) < 10:
            raise VerificationError('Provisioned dashboard missing')
        required = {
            'sum(soulcuts_service_running)': 8,
            'sum(soulcuts_service_healthy)': 8,
            'sum(soulcuts_service_healthcheck_present)': 7,
            'sum(up)': 4,
            'soulcuts_collector_success': 1,
            'node_textfile_scrape_error': 0,
        }
        for expression, expected in required.items():
            if self.scalar(expression) != expected:
                raise VerificationError('Production monitoring metric check failed')
        if not 0 <= self.scalar('time() - soulcuts_collector_last_success_unixtime') < 180:
            raise VerificationError('Collector is stale')
        if self.scalar('soulcuts_host_memory_total_bytes') <= 0:
            raise VerificationError('Host memory metric missing')
        if collected_after is not None and self.scalar('soulcuts_collector_last_attempt_unixtime') <= collected_after:
            raise VerificationError('Scheduled collector has not run yet')
        query = '{job="soulcuts"}'
        if marker:
            query += ' |= ' + json.dumps(marker)
        payload = self.get('/api/datasources/proxy/uid/soulcuts-loki/loki/api/v1/query_range?' +
                           urllib.parse.urlencode({'query': query, 'limit': '200', 'since': '15m'}))
        if payload.get('status') != 'success':
            raise VerificationError('Loki query failed')
        entries = [line for stream in payload['data']['result'] for _, line in stream['values']]
        if not entries or (marker and not any(marker in line for line in entries)):
            raise VerificationError('Log pipeline marker not received')
        return {'status': 'PASS', 'grafana_database': 'ok', 'datasources': 2,
                'dashboard_panels': len(dashboard['panels']), 'running_services': 8,
                'healthy_services': 8, 'scrape_targets_up': 4,
                'logs_received': True, 'synthetic_marker_received': bool(marker),
                'scheduled_collection_verified': collected_after is not None}


def wait_ready(client, *, marker=None, collected_after=None, timeout=150):
    end = time.monotonic() + timeout
    while True:
        try:
            return client.verify(marker=marker, collected_after=collected_after)
        except VerificationError:
            if time.monotonic() >= end:
                raise
            time.sleep(3)
