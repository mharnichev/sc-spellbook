"""Install the isolated monitoring stack; application services are never mutated."""
import argparse
import contextlib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import time

_verify_spec = importlib.util.spec_from_file_location('monitoring_verify', Path(__file__).with_name('verify.py'))
_verify = importlib.util.module_from_spec(_verify_spec)
_verify_spec.loader.exec_module(_verify)
Grafana, wait_ready = _verify.Grafana, _verify.wait_ready

APP = Path('/opt/soulcuts')
ROOT = APP / 'monitoring'
PROJECT = 'soulcuts-monitoring'
SERVICES = ('grafana', 'prometheus', 'loki', 'alloy', 'node-exporter')
APP_SERVICES = ('caddy', 'public-site', 'blog', 'admin-app', 'shop', 'backend', 'booking-sms-reminders', 'postgres')
KEYS = dict(zip(SERVICES, ('GRAFANA_IMAGE', 'PROMETHEUS_IMAGE', 'LOKI_IMAGE', 'ALLOY_IMAGE', 'NODE_EXPORTER_IMAGE')))
CRON_BEGIN = '# BEGIN SOULCUTS MONITORING'
CRON_END = '# END SOULCUTS MONITORING'
CRON_ENTRY = '* * * * * /usr/bin/nice -n 10 /usr/bin/python3 -I /opt/soulcuts/monitoring/current/monitoring/collect.py --root /opt/soulcuts/monitoring >/dev/null 2>&1'


class DeploymentError(Exception):
    pass


def run(args, *, label, timeout=300, input=None, allowed=(0,)):
    try:
        result = subprocess.run(args, input=input, capture_output=True, text=True, timeout=timeout)
    except Exception:
        raise DeploymentError(label) from None
    if result.returncode not in allowed:
        raise DeploymentError(label)
    return result.stdout


def durable_json(path, payload):
    temporary = path.with_name(path.name + '.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(payload, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    sync_dir(path.parent)


def sync_dir(path):
    fd = os.open(path, os.O_DIRECTORY | os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def directory(path, mode=0o700):
    if path.is_symlink():
        raise DeploymentError('Unexpected symlink in monitoring state')
    path.mkdir(mode=mode, parents=True, exist_ok=True)
    if not path.is_dir() or path.stat().st_uid != os.getuid():
        raise DeploymentError('Unexpected monitoring state owner')
    path.chmod(mode)


def secret(path):
    if path.is_symlink():
        raise DeploymentError('Secret symlink refused')
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o640)
        with os.fdopen(fd, 'w') as stream:
            stream.write(secrets.token_urlsafe(36) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        sync_dir(path.parent)
    info = path.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o007:
        raise DeploymentError('Unsafe monitoring secret permissions')
    path.chmod(0o640)
    value = path.read_text().strip()
    if len(value) < 32:
        raise DeploymentError('Monitoring secret is missing or too short')
    return value


def application_state():
    state = {}
    for service in APP_SERVICES:
        info = json.loads(run(['docker', 'inspect', 'soulcuts-' + service + '-1'], label='Application inspection failed'))[0]
        health = info['State'].get('Health', {}).get('Status', info['State']['Status'])
        if not info['State']['Running'] or health != ('running' if service == 'booking-sms-reminders' else 'healthy'):
            raise DeploymentError('Existing application service is not ready')
        state[service] = {
            'id': info['Id'], 'started': info['State']['StartedAt'], 'image': info['Image'],
            'env_sha256': hashlib.sha256(json.dumps(sorted(info['Config']['Env'])).encode()).hexdigest(),
        }
    return {'release': str((APP / 'current').resolve()), 'services': state,
            'env_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((APP / 'env').glob('*.env'))}}


def cron_text(existing):
    if CRON_BEGIN in existing or CRON_END in existing:
        raise DeploymentError('Monitoring cron already exists; initial-install only')
    return existing + ('' if not existing or existing.endswith('\n') else '\n') + CRON_BEGIN + '\n' + CRON_ENTRY + '\n' + CRON_END + '\n'


def read_cron():
    result = subprocess.run(['crontab', '-l'], capture_output=True, text=True, timeout=10)
    if result.returncode == 0:
        return result.stdout
    if result.returncode == 1 and not result.stdout and result.stderr.strip().startswith('no crontab for '):
        return ''
    raise DeploymentError('Cannot safely read the existing crontab')


@contextlib.contextmanager
def release_lock():
    lock = APP / 'release.lock'
    try:
        lock.mkdir()
    except FileExistsError:
        raise DeploymentError('Another release owns the production lock') from None
    pid = lock / 'pid'
    pid.write_text(str(os.getpid()) + '\n')
    try:
        yield
    finally:
        if pid.read_text().strip() == str(os.getpid()):
            pid.unlink()
            lock.rmdir()


def pins(release):
    values = {}
    for line in (release / 'monitoring/images.env').read_text().splitlines():
        if not line or line.startswith('#'):
            continue
        key, value = line.split('=', 1)
        if key not in KEYS.values() or key in values or not re.fullmatch(r'(?:grafana/(?:grafana|loki|alloy)|prom/(?:prometheus|node-exporter)):[A-Za-z0-9.\-]+@sha256:[0-9a-f]{64}', value):
            raise DeploymentError('Invalid monitoring image pin')
        values[key] = value
    if set(values) != set(KEYS.values()):
        raise DeploymentError('Missing monitoring image pin')
    return values


def verify_containers(expected):
    for service in SERVICES:
        info = json.loads(run(['docker', 'inspect', PROJECT + '-' + service + '-1'], label='Monitoring container inspection failed'))[0]
        intended = run(['docker', 'image', 'inspect', '--format', '{{.Id}}', expected[KEYS[service]]], label='Monitoring image inspection failed').strip()
        if not info['State']['Running'] or info['Image'] != intended:
            raise DeploymentError('Monitoring image/state mismatch')
        config = info['HostConfig']
        if config['Privileged'] or not config['ReadonlyRootfs'] or 'ALL' not in config.get('CapDrop', []) or config['Memory'] <= 0 or config['NanoCpus'] <= 0:
            raise DeploymentError('Monitoring resource/isolation guard failed')
        for target, bindings in (info['NetworkSettings'].get('Ports') or {}).items():
            if bindings and (service != 'grafana' or target != '3000/tcp' or any(b['HostIp'] != '127.0.0.1' or b['HostPort'] != '3300' for b in bindings)):
                raise DeploymentError('Unexpected public monitoring port')
        if service == 'grafana' and info['NetworkSettings'].get('Ports', {}).get('3000/tcp') != [{'HostIp': '127.0.0.1', 'HostPort': '3300'}]:
            raise DeploymentError('Grafana loopback port is not actually published')
        if any('/docker.sock' in mount['Source'] for mount in info['Mounts']):
            raise DeploymentError('Docker socket mount refused')
    network = json.loads(run(['docker', 'network', 'inspect', PROJECT + '_monitoring'], label='Monitoring network inspection failed'))[0]
    if not network['Internal'] or len(network['Containers']) != len(SERVICES):
        raise DeploymentError('Monitoring network isolation failed')
    ui = json.loads(run(['docker', 'network', 'inspect', PROJECT + '_ui'], label='Grafana UI network inspection failed'))[0]
    if len(ui['Containers']) != 1:
        raise DeploymentError('Only Grafana may join the UI bridge')


def install(revision):
    release = Path(__file__).resolve().parent.parent
    if not re.fullmatch(r'[0-9a-f]{40}', revision) or release != ROOT / 'releases' / revision:
        raise DeploymentError('Monitoring must deploy an immutable server release')
    if os.getuid() == 0:
        raise DeploymentError('Use the unprivileged deployment account')
    if shutil.disk_usage(APP).free < 10 * 2**30:
        raise DeploymentError('Insufficient free disk for safe monitoring install')
    server = run(['docker', 'info', '--format', '{{.ServerVersion}}'], label='Docker preflight failed').strip()
    if not server.split('.')[0].isdigit() or int(server.split('.')[0]) < 28:
        raise DeploymentError('Docker 28 or newer is required for loopback publishing safety')
    with release_lock():
        for name in ['backend-recovery-required', 'english-backfill-required', 'shop-online-activation-required', 'master-qr-activation-required']:
            if (APP / name).exists() or (APP / name).is_symlink():
                raise DeploymentError('An application recovery fence is active')
        before = application_state()
        directory(ROOT)
        marker = ROOT / 'deployment-required.json'
        if marker.exists() or marker.is_symlink() or (ROOT / 'current').exists() or (ROOT / 'current').is_symlink():
            raise DeploymentError('Monitoring state already exists; inspect before recovery/upgrade')
        expected = pins(release)
        for path in [ROOT / 'secrets', ROOT / 'data', ROOT / 'data/alloy', ROOT / 'evidence']:
            directory(path)
        password = secret(ROOT / 'secrets/grafana_admin_password')
        secret(ROOT / 'secrets/grafana_secret_key')
        existing_cron = read_cron()
        next_cron = cron_text(existing_cron)
        compose = ['docker', 'compose', '--project-name', PROJECT, '--env-file', str(release / 'monitoring/images.env'), '-f', str(release / 'monitoring/compose.yml')]
        os.environ.update(expected)
        os.environ.update(MONITORING_ROOT=str(ROOT), MONITORING_UID=str(os.getuid()), MONITORING_GID=str(os.getgid()))
        run([*compose, 'config', '-q'], label='Monitoring Compose validation failed')
        run([*compose, 'pull'], label='Monitoring image pull failed', timeout=600)
        durable_json(ROOT / 'evidence/before.json', before)
        durable_json(ROOT / 'evidence/previous-cron.json', {'crontab': existing_cron})
        durable_json(marker, {'revision': revision, 'phase': 'initial-install', 'application_before': before})
        run(['/usr/bin/python3', '-I', str(release / 'monitoring/collect.py'), '--root', str(ROOT)], label='Initial host collection failed', timeout=60)
        run([*compose, 'up', '-d', '--no-deps', *SERVICES], label='Monitoring start failed')
        verify_containers(expected)
        # A clearly labelled synthetic line verifies Alloy -> Loki -> Grafana.
        spec = importlib.util.spec_from_file_location('monitoring_collect', release / 'monitoring/collect.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        marker_id = secrets.token_hex(8)
        module.append_events(ROOT / 'spool/logs/backend.log', [{
            'timestamp': module.iso(module.dt.datetime.now(module.dt.timezone.utc)),
            'service': 'backend', 'level': 'INFO', 'event': 'monitoring_smoke',
            'message': 'Monitoring pipeline verification (synthetic) ' + marker_id,
        }])
        client = Grafana('http://127.0.0.1:3300', password)
        wait_ready(client, marker=marker_id)
        if before != application_state():
            raise DeploymentError('Protected application state changed during monitoring install')
        os.symlink(release, ROOT / 'current')
        sync_dir(ROOT)
        cron_started = time.time()
        if read_cron() != existing_cron:
            raise DeploymentError('Crontab changed during acceptance; refusing replacement')
        run(['crontab', '-'], label='Monitoring cron install failed', input=next_cron)
        if run(['crontab', '-l'], label='Monitoring cron verification failed') != next_cron:
            raise DeploymentError('Monitoring cron verification mismatch')
        report = wait_ready(client, marker=marker_id, collected_after=cron_started, timeout=150)
        verify_containers(expected)
        if before != application_state():
            raise DeploymentError('Protected application state changed during cron acceptance')
        report.update(revision=revision, application_unchanged=True, ports='127.0.0.1:3300 only',
                      privacy='Operational metadata only; no raw application log text', cron_verified=True)
        durable_json(ROOT / 'evidence/accepted.json', report)
        marker.unlink()
        sync_dir(ROOT)
        print(json.dumps(report))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', required=True)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        install(args.revision)
    except DeploymentError as error:
        print(str(error), file=sys.stderr)
        print('Monitoring install did not complete; retain evidence/fence and inspect before retry.', file=sys.stderr)
        return 1
    except Exception:
        # Never print Docker stderr, HTTP bodies, credentials or raw exceptions.
        print('Monitoring install did not complete; retain evidence/fence and inspect before retry.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
